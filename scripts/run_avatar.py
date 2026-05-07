"""End-to-end avatar generation test against a remote ComfyUI exposed via
RunPod's HTTP proxy. Uploads image+audio, patches the LongCat workflow,
queues, polls, downloads the result video.

This is a slimmed-down adaptation of worker/handler.py that talks to a
remote ComfyUI rather than localhost.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

import requests

POD_ID = os.environ["POD_ID"]
COMFY_HTTP = f"https://{POD_ID}-8188.proxy.runpod.net"
WORKFLOW_PATH = Path("/Volumes/External/Avatar/longcat/worker/workflows/LongCatAvatar_audio_image_to_video_example_01.json")

MODEL_FILENAME = "LongCat/LongCat-Avatar-single_fp8_e4m3fn_scaled_mixed_KJ.safetensors"
LORA_FILENAME = "LongCat_distill_lora_alpha64_bf16.safetensors"

DEFAULT_NEGATIVE = (
    "Close-up, bright tones, overexposed, static, blurred details, subtitles, "
    "style, works, paintings, images, static, overall gray, worst quality, "
    "low quality, JPEG compression residue, ugly, incomplete, extra fingers, "
    "poorly drawn hands, poorly drawn faces, deformed, disfigured, "
    "misshapen limbs, fused fingers, still picture, messy background, "
    "three legs, many people in the background, walking backwards"
)

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

_UI_ONLY_TYPES = {"Reroute", "GetNode", "SetNode", "Note", "MarkdownNote", "PrimitiveNode"}


def upload_file(local_path: Path, remote_name: str, kind: str = "input") -> str:
    """Upload to ComfyUI's /upload/image (works for any file). Returns server filename."""
    with open(local_path, "rb") as fh:
        files = {"image": (remote_name, fh, "application/octet-stream")}
        data = {"type": kind, "subfolder": "", "overwrite": "true"}
        r = requests.post(f"{COMFY_HTTP}/upload/image", files=files, data=data, timeout=120)
        r.raise_for_status()
        return r.json().get("name", remote_name)


def set_widget(workflow, node_id, index, value):
    for n in workflow["nodes"]:
        if n.get("id") == node_id:
            wv = n.get("widgets_values")
            if wv is None or not isinstance(wv, list):
                raise RuntimeError(f"Node {node_id} has no list widgets_values")
            while len(wv) <= index:
                wv.append(None)
            wv[index] = value
            return
    raise RuntimeError(f"Node id={node_id} not found")


def get_object_info():
    r = requests.get(f"{COMFY_HTTP}/object_info", timeout=120)
    r.raise_for_status()
    return r.json()


def is_widget_spec(spec):
    if not isinstance(spec, list) or not spec:
        return False
    type_def = spec[0]
    if isinstance(type_def, list):
        return True
    return type_def in {"STRING", "INT", "FLOAT", "BOOLEAN", "COMBO"}


def consumes_extra_control(spec):
    if not isinstance(spec, list) or len(spec) < 2:
        return False
    opts = spec[1]
    if not isinstance(opts, dict):
        return False
    return bool(opts.get("control_after_generate"))


def walk_through_proxies(node_id, slot, nodes_by_id, links_by_id, workflow):
    visited = set()
    while node_id not in visited:
        visited.add(node_id)
        node = nodes_by_id.get(node_id)
        if not node:
            return node_id, slot
        nt = node.get("type")
        if nt == "Reroute":
            inp = (node.get("inputs") or [{}])[0]
            link_id = inp.get("link")
            if link_id is None:
                return node_id, slot
            src = links_by_id.get(link_id)
            if not src:
                return node_id, slot
            node_id, slot = src
            continue
        if nt == "GetNode":
            name = (node.get("widgets_values") or [None])[0]
            if not name:
                return node_id, slot
            for cand in workflow["nodes"]:
                if cand.get("type") == "SetNode" and (cand.get("widgets_values") or [None])[0] == name:
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


def workflow_to_api(workflow, object_info):
    nodes_by_id = {n["id"]: n for n in workflow["nodes"]}
    links_by_id = {}
    for link in workflow.get("links", []):
        if isinstance(link, list) and len(link) >= 5:
            links_by_id[link[0]] = (link[1], link[2])

    api = {}
    for node in workflow["nodes"]:
        if node.get("mode") in (2, 4):
            continue
        nt = node["type"]
        if nt in _UI_ONLY_TYPES:
            continue
        schema = object_info.get(nt)
        if not schema:
            continue
        ordered = []
        for kind in ("required", "optional"):
            section = (schema.get("input") or {}).get(kind) or {}
            for name, spec in section.items():
                ordered.append((name, spec))
        inputs_in_node = {inp["name"]: inp for inp in (node.get("inputs") or [])}
        wv = node.get("widgets_values")
        wv_is_dict = isinstance(wv, dict)
        wv_iter = iter(wv or [])

        api_inputs = {}
        for name, spec in ordered:
            is_widget = is_widget_spec(spec)
            if name in inputs_in_node:
                link_id = inputs_in_node[name].get("link")
                if link_id is not None:
                    src = links_by_id.get(link_id)
                    if src:
                        from_id, from_slot = walk_through_proxies(
                            src[0], src[1], nodes_by_id, links_by_id, workflow,
                        )
                        api_inputs[name] = [str(from_id), from_slot]
                # Some inputs are widget-able AND linkable; their value still
                # appears in widgets_values even when wired. Consume it to keep
                # the positional iter aligned with the schema.
                if is_widget and not wv_is_dict:
                    try:
                        next(wv_iter)
                    except StopIteration:
                        pass
                    if consumes_extra_control(spec):
                        try:
                            next(wv_iter)
                        except StopIteration:
                            pass
                continue
            if not is_widget:
                continue
            if wv_is_dict:
                if name in wv:
                    api_inputs[name] = wv[name]
                continue
            try:
                value = next(wv_iter)
            except StopIteration:
                break
            api_inputs[name] = value
            if consumes_extra_control(spec):
                try:
                    next(wv_iter)
                except StopIteration:
                    pass
        api[str(node["id"])] = {"class_type": nt, "inputs": api_inputs}
    return api


def main():
    portrait = Path(os.environ.get("PORTRAIT", "/Volumes/External/Avatar/longcat/examples/portrait.jpg"))
    audio = Path(os.environ.get("AUDIO", "/Volumes/External/Avatar/longcat/examples/speech.wav"))

    print(f"[1/6] Uploading inputs to ComfyUI ({COMFY_HTTP})...")
    img_name = upload_file(portrait, "input_" + portrait.name, "input")
    aud_name = upload_file(audio, "input_" + audio.name, "input")
    print(f"  image: {img_name}")
    print(f"  audio: {aud_name}")

    print("[2/6] Loading + patching workflow...")
    workflow = json.loads(WORKFLOW_PATH.read_text())
    set_widget(workflow, NODE_LOAD_IMAGE, 0, img_name)
    set_widget(workflow, NODE_LOAD_AUDIO, 0, aud_name)
    set_widget(workflow, NODE_TEXT_ENCODE, 2, os.environ.get("PROMPT", "A woman with curly brown hair and a green sweater speaks calmly to the camera in a cozy bookshelf-lined home interior, soft natural daylight from windows, plants in background, warm cinematic, gentle smile, clear lip-sync, photorealistic, detailed skin texture."))
    set_widget(workflow, NODE_TEXT_ENCODE, 3, DEFAULT_NEGATIVE)
    set_widget(workflow, NODE_WIDTH, 0, 832)
    set_widget(workflow, NODE_HEIGHT, 0, 480)
    set_widget(workflow, NODE_FRAMES_PER_WINDOW, 0, 53)
    set_widget(workflow, NODE_OVERLAP, 0, 13)
    set_widget(workflow, NODE_CFG, 0, 1.0)
    set_widget(workflow, NODE_MODEL_LOADER, 0, MODEL_FILENAME)
    set_widget(workflow, NODE_MODEL_LOADER, 4, "sdpa")  # sageattn not installed; use SDPA fallback
    set_widget(workflow, NODE_LORA_SELECT, 0, LORA_FILENAME)
    set_widget(workflow, NODE_TRIM_AUDIO, 1, int(float(os.environ.get("AUDIO_MAX_SECONDS", "7.3")) * 16000))

    print("[3/6] Fetching /object_info...")
    oi = get_object_info()

    print("[4/6] Converting UI workflow → API workflow...")
    api_wf = workflow_to_api(workflow, oi)
    print(f"  {len(api_wf)} nodes")

    print("[5/6] POST /prompt...")
    r = requests.post(f"{COMFY_HTTP}/prompt", json={"prompt": api_wf, "client_id": "longcat-test"}, timeout=60)
    if not r.ok:
        print(f"  HTTP {r.status_code}: {r.text[:1000]}")
        sys.exit(1)
    prompt_id = r.json()["prompt_id"]
    print(f"  prompt_id={prompt_id}")

    print("[6/6] Polling /history until done...")
    start = time.time()
    last_log = 0
    while time.time() - start < 1800:
        time.sleep(5)
        elapsed = int(time.time() - start)
        if elapsed - last_log >= 20:
            print(f"  [{elapsed}s] still running...")
            last_log = elapsed
        try:
            h = requests.get(f"{COMFY_HTTP}/history/{prompt_id}", timeout=20).json()
        except Exception as e:
            print(f"  poll error: {e}")
            continue
        record = h.get(prompt_id)
        if not record:
            continue
        status = record.get("status", {})
        if status.get("completed") or status.get("status_str") in ("success", "error"):
            print(f"  done in {elapsed}s; status_str={status.get('status_str')}")
            if status.get("status_str") == "error":
                print("  messages:", json.dumps(status.get("messages"), indent=2)[:3000])
                sys.exit(2)
            outputs = record.get("outputs") or {}
            for nid, no in outputs.items():
                for key in ("gifs", "videos", "images"):
                    for item in no.get(key, []) or []:
                        fname = item.get("filename")
                        if not fname:
                            continue
                        if not fname.lower().endswith((".mp4", ".webm", ".gif", ".mov")):
                            continue
                        sub = item.get("subfolder") or ""
                        ftype = item.get("type", "output")
                        params = {"filename": fname, "subfolder": sub, "type": ftype}
                        url = f"{COMFY_HTTP}/view?{urllib.parse.urlencode(params)}"
                        print(f"  fetching {url}")
                        vr = requests.get(url, timeout=300)
                        vr.raise_for_status()
                        out = Path("/Volumes/External/Avatar/longcat/examples") / f"longcat_avatar_test_{fname}"
                        out.write_bytes(vr.content)
                        print(f"  saved: {out} ({len(vr.content)/1e6:.2f} MB)")
            return
    print("  TIMEOUT after 30 min")
    sys.exit(3)


if __name__ == "__main__":
    main()
