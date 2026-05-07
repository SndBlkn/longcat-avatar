"""RunPod Serverless handler for LongCat-Avatar (ComfyUI / WanVideoWrapper).

Accepts a job with a reference image, a driving audio file, and a text prompt;
queues the LongCat-Avatar workflow against the local ComfyUI server; returns
the generated video as base64.

Job input schema:
{
  "input": {
    "image":           "<base64 png/jpg>",        # required
    "audio":           "<base64 wav/mp3>",        # required
    "prompt":          "<positive text prompt>",  # required
    "negative_prompt": "<text>",                  # optional
    "width":           832,                        # optional
    "height":          480,                        # optional
    "frames_per_window": 93,                       # optional
    "overlap":         13,                          # optional
    "cfg":             1.0,                        # optional
    "seed":            -1,                          # optional, -1 = random
    "audio_max_seconds": null                      # optional, trims audio
  }
}
"""

from __future__ import annotations

import base64
import json
import os
import random
import time
import urllib.parse
import uuid
from pathlib import Path

import requests
import runpod
import websocket

COMFY_HOST = os.environ.get("COMFY_HOST", "127.0.0.1:8188")
COMFY_INPUT_DIR = Path(os.environ.get("COMFY_INPUT_DIR", "/comfyui/input"))
COMFY_OUTPUT_DIR = Path(os.environ.get("COMFY_OUTPUT_DIR", "/comfyui/output"))
WORKFLOW_PATH = Path(os.environ.get(
    "WORKFLOW_PATH",
    "/workflows/LongCatAvatar_audio_image_to_video_example_01.json",
))
MODEL_FILENAME = os.environ.get(
    "MODEL_FILENAME",
    "LongCat/LongCat-Avatar-single_fp8_e4m3fn_scaled_mixed_KJ.safetensors",
)
LORA_FILENAME = os.environ.get(
    "LORA_FILENAME",
    "LongCat_distill_lora_rank128_bf16.safetensors",
)

DEFAULT_NEGATIVE = (
    "Close-up, bright tones, overexposed, static, blurred details, subtitles, "
    "style, works, paintings, images, static, overall gray, worst quality, "
    "low quality, JPEG compression residue, ugly, incomplete, extra fingers, "
    "poorly drawn hands, poorly drawn faces, deformed, disfigured, "
    "misshapen limbs, fused fingers, still picture, messy background, "
    "three legs, many people in the background, walking backwards"
)

# Node IDs we override on each request — see docs/WORKFLOW_NOTES.md
NODE_LOAD_IMAGE = 284
NODE_LOAD_AUDIO = 125
NODE_TEXT_ENCODE = 241
NODE_WIDTH = 245
NODE_HEIGHT = 246
NODE_MODEL_LOADER = 122
NODE_LORA_SELECT = 138
NODE_TRIM_AUDIO = 317
NODE_OVERLAP = 423
NODE_FRAMES_PER_WINDOW = 438
NODE_CFG = 427


def _b64_to_file(b64: str, dest: Path) -> Path:
    """Decode a base64 payload (with optional data: prefix) to disk."""
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(base64.b64decode(b64))
    return dest


def _file_to_b64(path: Path) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def _load_workflow() -> dict:
    with open(WORKFLOW_PATH) as fh:
        return json.load(fh)


def _set_widget(workflow: dict, node_id: int, index: int, value):
    """Mutate widgets_values[index] for the given node id."""
    for node in workflow["nodes"]:
        if node.get("id") == node_id:
            wv = node.get("widgets_values")
            if wv is None or not isinstance(wv, list):
                raise RuntimeError(
                    f"Node {node_id} has no list widgets_values; cannot patch."
                )
            while len(wv) <= index:
                wv.append(None)
            wv[index] = value
            return
    raise RuntimeError(f"Node id={node_id} not found in workflow.")


def _patch_workflow(
    workflow: dict,
    image_filename: str,
    audio_filename: str,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    frames_per_window: int,
    overlap: int,
    cfg: float,
    audio_max_samples: int | None,
) -> None:
    _set_widget(workflow, NODE_LOAD_IMAGE, 0, image_filename)
    _set_widget(workflow, NODE_LOAD_AUDIO, 0, audio_filename)
    _set_widget(workflow, NODE_TEXT_ENCODE, 2, prompt)
    _set_widget(workflow, NODE_TEXT_ENCODE, 3, negative_prompt)
    _set_widget(workflow, NODE_WIDTH, 0, int(width))
    _set_widget(workflow, NODE_HEIGHT, 0, int(height))
    _set_widget(workflow, NODE_FRAMES_PER_WINDOW, 0, int(frames_per_window))
    _set_widget(workflow, NODE_OVERLAP, 0, int(overlap))
    _set_widget(workflow, NODE_CFG, 0, float(cfg))
    _set_widget(workflow, NODE_MODEL_LOADER, 0, MODEL_FILENAME)
    _set_widget(workflow, NODE_LORA_SELECT, 0, LORA_FILENAME)
    if audio_max_samples is not None:
        _set_widget(workflow, NODE_TRIM_AUDIO, 1, int(audio_max_samples))


_OBJECT_INFO_CACHE: dict | None = None
_UI_ONLY_TYPES = {"Reroute", "GetNode", "SetNode", "Note", "MarkdownNote",
                  "PrimitiveNode"}


def _get_object_info() -> dict:
    """Fetch ComfyUI's full node schema (cached for the worker's lifetime)."""
    global _OBJECT_INFO_CACHE
    if _OBJECT_INFO_CACHE is None:
        resp = requests.get(f"http://{COMFY_HOST}/object_info", timeout=60)
        resp.raise_for_status()
        _OBJECT_INFO_CACHE = resp.json()
    return _OBJECT_INFO_CACHE


def _is_widget_spec(spec) -> bool:
    """Decide whether a `/object_info` input spec represents a widget (vs. a link)."""
    if not isinstance(spec, list) or not spec:
        return False
    type_def = spec[0]
    # Combo (dropdown) is given as a list of choices.
    if isinstance(type_def, list):
        return True
    # Forceable widgets: scalar types render as on-canvas controls.
    return type_def in {"STRING", "INT", "FLOAT", "BOOLEAN"}


def _consumes_extra_control_widget(spec) -> bool:
    """Some INT widgets (typically `seed`/`noise_seed`) implicitly add a paired
    `control_after_generate` widget value in the UI workflow that is NOT part of the
    API schema. Detect via the spec options dict."""
    if not isinstance(spec, list) or len(spec) < 2:
        return False
    opts = spec[1]
    if not isinstance(opts, dict):
        return False
    return bool(opts.get("control_after_generate"))


def _walk_through_proxies(node_id: int, slot: int, nodes_by_id: dict,
                          links_by_id: dict, workflow: dict):
    """Resolve through Reroute / GetNode / SetNode so an API edge points at a real producer."""
    visited = set()
    while node_id not in visited:
        visited.add(node_id)
        node = nodes_by_id.get(node_id)
        if not node:
            return node_id, slot
        ntype = node.get("type")
        if ntype == "Reroute":
            inp = (node.get("inputs") or [{}])[0]
            link_id = inp.get("link")
            if link_id is None:
                return node_id, slot
            src = links_by_id.get(link_id)
            if not src:
                return node_id, slot
            node_id, slot = src
            continue
        if ntype == "GetNode":
            name = (node.get("widgets_values") or [None])[0]
            if not name:
                return node_id, slot
            for cand in workflow["nodes"]:
                if cand.get("type") == "SetNode" and \
                        (cand.get("widgets_values") or [None])[0] == name:
                    inp = (cand.get("inputs") or [{}])[0]
                    link_id = inp.get("link")
                    if link_id is None:
                        return node_id, slot
                    src = links_by_id.get(link_id)
                    if not src:
                        return node_id, slot
                    node_id, slot = src
                    break
            else:
                return node_id, slot
            continue
        return node_id, slot
    return node_id, slot


def _workflow_to_api_format(workflow: dict) -> dict:
    """Convert a ComfyUI UI-format workflow (`nodes` + `links`) to the API format
    the `/prompt` endpoint expects: `{node_id_str: {"class_type", "inputs"}}`.

    Uses `/object_info` to learn each node's true input names + types so widgets
    map to the right keys. UI-only proxies (Reroute/GetNode/SetNode) are walked
    through to find the real producing node for each link.
    """
    object_info = _get_object_info()

    nodes_by_id = {n["id"]: n for n in workflow["nodes"]}
    links_by_id = {}
    for link in workflow.get("links", []):
        if isinstance(link, list) and len(link) >= 5:
            links_by_id[link[0]] = (link[1], link[2])

    api: dict = {}

    for node in workflow["nodes"]:
        if node.get("mode") in (2, 4):  # 2=muted, 4=bypassed
            continue
        ntype = node["type"]
        if ntype in _UI_ONLY_TYPES:
            continue

        schema = object_info.get(ntype)
        if not schema:
            # Unknown node type — skip rather than crash; ComfyUI will tell us
            # if the resulting graph is incomplete.
            continue

        ordered_inputs: list[tuple[str, object]] = []
        input_schema = schema.get("input") or {}
        for kind in ("required", "optional"):
            section = input_schema.get(kind) or {}
            for name, spec in section.items():
                ordered_inputs.append((name, spec))

        inputs_in_node = {inp["name"]: inp for inp in (node.get("inputs") or [])}
        wv_iter = iter(node.get("widgets_values") or [])

        api_inputs: dict = {}
        for name, spec in ordered_inputs:
            if name in inputs_in_node:
                # This input is wired to another node — resolve the link.
                link_id = inputs_in_node[name].get("link")
                if link_id is None:
                    continue
                src = links_by_id.get(link_id)
                if not src:
                    continue
                from_id, from_slot = _walk_through_proxies(
                    src[0], src[1], nodes_by_id, links_by_id, workflow,
                )
                api_inputs[name] = [str(from_id), from_slot]
                continue

            if not _is_widget_spec(spec):
                continue  # unconnected optional connection input

            try:
                value = next(wv_iter)
            except StopIteration:
                break

            api_inputs[name] = value

            if _consumes_extra_control_widget(spec):
                try:
                    next(wv_iter)  # discard the UI-only control_after_generate value
                except StopIteration:
                    pass

        api[str(node["id"])] = {"class_type": ntype, "inputs": api_inputs}

    return api


def _queue_prompt(api_workflow: dict, client_id: str) -> str:
    resp = requests.post(
        f"http://{COMFY_HOST}/prompt",
        json={"prompt": api_workflow, "client_id": client_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["prompt_id"]


def _wait_for_prompt(prompt_id: str, client_id: str, timeout_s: int = 1800) -> dict:
    """Block on the WebSocket until the prompt finishes; returns the history record."""
    ws = websocket.WebSocket()
    ws.connect(f"ws://{COMFY_HOST}/ws?clientId={client_id}", timeout=30)
    ws.settimeout(60)
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            try:
                msg = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if isinstance(msg, (bytes, bytearray)):
                continue
            data = json.loads(msg)
            if data.get("type") == "executing":
                payload = data.get("data") or {}
                if payload.get("node") is None and payload.get("prompt_id") == prompt_id:
                    break
        else:
            raise TimeoutError(f"prompt {prompt_id} did not finish in {timeout_s}s")
    finally:
        ws.close()

    # Fetch history
    hist_resp = requests.get(f"http://{COMFY_HOST}/history/{prompt_id}", timeout=15)
    hist_resp.raise_for_status()
    hist = hist_resp.json().get(prompt_id, {})
    return hist


def _collect_video_outputs(history: dict) -> list[Path]:
    outputs = history.get("outputs") or {}
    paths: list[Path] = []
    for node_id, node_output in outputs.items():
        for key in ("gifs", "videos", "images"):
            for item in node_output.get(key, []) or []:
                fname = item.get("filename")
                if not fname:
                    continue
                if not fname.lower().endswith((".mp4", ".webm", ".gif", ".mov")):
                    continue
                subfolder = item.get("subfolder") or ""
                folder_type = item.get("type", "output")
                base = COMFY_OUTPUT_DIR
                if folder_type == "temp":
                    base = Path("/comfyui/temp")
                p = base / subfolder / fname
                if p.exists():
                    paths.append(p)
    # Sort by mtime asc (last is final)
    paths.sort(key=lambda p: p.stat().st_mtime)
    return paths


def handler(job: dict) -> dict:
    job_input = job.get("input") or {}

    image_b64 = job_input.get("image")
    audio_b64 = job_input.get("audio")
    if not image_b64 or not audio_b64:
        return {"error": "Both 'image' and 'audio' (base64) are required."}

    prompt = job_input.get("prompt") or "A person speaking, natural lighting, detailed."
    negative_prompt = job_input.get("negative_prompt") or DEFAULT_NEGATIVE
    width = int(job_input.get("width") or 832)
    height = int(job_input.get("height") or 480)
    frames_per_window = int(job_input.get("frames_per_window") or 93)
    overlap = int(job_input.get("overlap") or 13)
    cfg = float(job_input.get("cfg") or 1.0)
    audio_max_seconds = job_input.get("audio_max_seconds")

    # Stage inputs
    job_id = uuid.uuid4().hex[:12]
    image_path = COMFY_INPUT_DIR / f"input_{job_id}.png"
    audio_path = COMFY_INPUT_DIR / f"input_{job_id}.wav"
    _b64_to_file(image_b64, image_path)
    _b64_to_file(audio_b64, audio_path)

    audio_max_samples = None
    if audio_max_seconds:
        # 16 kHz reference rate * seconds; the workflow's TrimAudioDuration uses sample count.
        audio_max_samples = int(float(audio_max_seconds) * 16000)

    workflow_ui = _load_workflow()
    _patch_workflow(
        workflow_ui,
        image_filename=image_path.name,
        audio_filename=audio_path.name,
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        frames_per_window=frames_per_window,
        overlap=overlap,
        cfg=cfg,
        audio_max_samples=audio_max_samples,
    )
    api_workflow = _workflow_to_api_format(workflow_ui)

    client_id = str(uuid.uuid4())
    prompt_id = _queue_prompt(api_workflow, client_id)

    history = _wait_for_prompt(prompt_id, client_id)

    # Surface ComfyUI execution errors clearly
    if history.get("status", {}).get("status_str") == "error":
        return {
            "error": "ComfyUI execution failed.",
            "messages": history.get("status", {}).get("messages"),
        }

    videos = _collect_video_outputs(history)
    if not videos:
        return {"error": "Workflow finished but produced no video output."}

    final_video = videos[-1]
    video_b64 = _file_to_b64(final_video)

    # Cleanup staged inputs (keep outputs for debugging)
    for p in (image_path, audio_path):
        try:
            p.unlink()
        except OSError:
            pass

    return {
        "video_b64": video_b64,
        "video_filename": final_video.name,
        "video_size_bytes": final_video.stat().st_size,
        "prompt_id": prompt_id,
    }


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
