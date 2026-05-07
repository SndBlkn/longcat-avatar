"""Populate a RunPod Network Volume with all model files LongCat-Avatar needs.

Run this ONCE, on a small CPU-only RunPod pod that has the Network Volume
attached at `/runpod-volume`. Re-running is safe — files already present at the
expected size are skipped.

Usage:
    pip install huggingface_hub tqdm
    python seed_volume.py

The volume layout afterwards:

    /runpod-volume/models/
    ├── diffusion_models/
    │   ├── LongCat/
    │   │   └── LongCat-Avatar-single_fp8_e4m3fn_scaled_mixed_KJ.safetensors
    │   └── MelBandRoformer_fp32.safetensors
    ├── vae/
    │   └── Wan2_1_VAE_bf16.safetensors
    ├── text_encoders/
    │   └── umt5-xxl-enc-bf16.safetensors
    ├── loras/
    │   └── LongCat_distill_lora_alpha64_bf16.safetensors
    └── wav2vec/
        └── wav2vec2-chinese-base_fp16.safetensors
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import hf_hub_download

VOLUME_ROOT = Path(os.environ.get("VOLUME_ROOT", "/runpod-volume/models"))


@dataclass(frozen=True)
class ModelFile:
    repo_id: str
    repo_path: str          # path inside the HF repo
    local_subdir: str       # subfolder under VOLUME_ROOT
    local_filename: str     # filename to write (usually basename of repo_path)


MODELS: list[ModelFile] = [
    # Main diffusion model — fp8 mixed scaled (Kijai)
    ModelFile(
        repo_id="Kijai/LongCat-Video_comfy",
        repo_path="Avatar/LongCat-Avatar-single_fp8_e4m3fn_scaled_mixed_KJ.safetensors",
        local_subdir="diffusion_models/LongCat",
        local_filename="LongCat-Avatar-single_fp8_e4m3fn_scaled_mixed_KJ.safetensors",
    ),
    # Distill LoRA (speeds up sampling)
    ModelFile(
        repo_id="Kijai/LongCat-Video_comfy",
        repo_path="LongCat_distill_lora_alpha64_bf16.safetensors",
        local_subdir="loras",
        local_filename="LongCat_distill_lora_alpha64_bf16.safetensors",
    ),
    # WAN VAE
    ModelFile(
        repo_id="Kijai/WanVideo_comfy",
        repo_path="Wan2_1_VAE_bf16.safetensors",
        local_subdir="vae",
        local_filename="Wan2_1_VAE_bf16.safetensors",
    ),
    # UMT5-XXL text encoder
    ModelFile(
        repo_id="Kijai/WanVideo_comfy",
        repo_path="umt5-xxl-enc-bf16.safetensors",
        local_subdir="text_encoders",
        local_filename="umt5-xxl-enc-bf16.safetensors",
    ),
    # Wav2Vec2 (speech features for lip-sync)
    ModelFile(
        repo_id="Kijai/wav2vec2_safetensors",
        repo_path="wav2vec2-chinese-base_fp16.safetensors",
        local_subdir="wav2vec",
        local_filename="wav2vec2-chinese-base_fp16.safetensors",
    ),
    # Mel-band RoFormer (vocal isolation)
    ModelFile(
        repo_id="Kijai/MelBandRoFormer_comfy",
        repo_path="MelBandRoformer_fp32.safetensors",
        local_subdir="diffusion_models",
        local_filename="MelBandRoformer_fp32.safetensors",
    ),
]


def fetch(model: ModelFile, hf_token: str | None) -> Path:
    target_dir = VOLUME_ROOT / model.local_subdir
    target_path = target_dir / model.local_filename
    target_dir.mkdir(parents=True, exist_ok=True)

    if target_path.exists() and target_path.stat().st_size > 0:
        print(f"[skip] {target_path} already exists ({target_path.stat().st_size / 1e9:.2f} GB)")
        return target_path

    print(f"[get ] {model.repo_id}/{model.repo_path}")
    cached = hf_hub_download(
        repo_id=model.repo_id,
        filename=model.repo_path,
        token=hf_token,
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
    )
    cached = Path(cached)

    if cached != target_path:
        # hf_hub_download mirrors the repo path inside local_dir; flatten to our layout.
        if cached.exists() and cached != target_path:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            cached.rename(target_path)
            # Clean up any empty intermediate dirs left behind.
            for parent in cached.parents:
                if parent == target_dir:
                    break
                try:
                    parent.rmdir()
                except OSError:
                    break

    print(f"[done] {target_path}  ({target_path.stat().st_size / 1e9:.2f} GB)")
    return target_path


def main() -> int:
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not VOLUME_ROOT.parent.exists():
        print(f"[err ] {VOLUME_ROOT.parent} does not exist — is the Network Volume mounted?",
              file=sys.stderr)
        return 1

    print(f"[info] Seeding into {VOLUME_ROOT}")
    print(f"[info] Files to ensure: {len(MODELS)}")

    failed: list[str] = []
    for model in MODELS:
        try:
            fetch(model, hf_token)
        except Exception as exc:  # noqa: BLE001 — best-effort per file
            print(f"[FAIL] {model.repo_id}/{model.repo_path}: {exc}", file=sys.stderr)
            failed.append(f"{model.repo_id}/{model.repo_path}")

    if failed:
        print("\nThe following downloads failed:")
        for f in failed:
            print(f"  - {f}")
        return 2

    print("\nAll model files are in place. Volume layout:")
    for model in MODELS:
        p = VOLUME_ROOT / model.local_subdir / model.local_filename
        print(f"  {p}  ({p.stat().st_size / 1e9:.2f} GB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
