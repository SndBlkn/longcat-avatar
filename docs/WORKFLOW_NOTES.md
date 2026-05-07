# LongCat-Avatar Workflow Reference

Source: `kijai/ComfyUI-WanVideoWrapper/example_workflows/LongCatAvatar_audio_image_to_video_example_01.json`

## Custom nodes required

- `ComfyUI-WanVideoWrapper` (kijai) — main avatar nodes
- `ComfyUI-KJNodes` (kijai) — utility / GetSet / image ops
- `ComfyUI-VideoHelperSuite` (Kosinkadink) — VHS_VideoCombine

## Model files (placed on RunPod Network Volume at `/runpod-volume/models/`)

| Logical type         | Filename                                                        | ComfyUI subfolder       | HF source                                                     | Size  |
|----------------------|-----------------------------------------------------------------|-------------------------|---------------------------------------------------------------|-------|
| Diffusion (avatar)   | `LongCat-Avatar-single_fp8_e4m3fn_scaled_mixed_KJ.safetensors`  | `diffusion_models/LongCat/` | `Kijai/LongCat-Video_comfy/Avatar/`                       | ~14GB |
| Distill LoRA         | `LongCat_distill_lora_rank128_bf16.safetensors`                 | `loras/`                | `Kijai/LongCat-Video_comfy/`                                  | ~600MB |
| WAN VAE              | `Wan2_1_VAE_bf16.safetensors`                                   | `vae/`                  | `Kijai/WanVideo_comfy/`                                       | ~250MB |
| Text encoder (UMT5)  | `umt5-xxl-enc-bf16.safetensors`                                 | `text_encoders/`        | `Kijai/WanVideo_comfy/`                                       | ~10GB |
| Speech embed (wav2vec)| `wav2vec2-chinese-base_fp16.safetensors`                       | `wav2vec/`              | `Kijai/wav2vec2_safetensors/`                                 | ~190MB |
| Vocal separator      | `MelBandRoformer_fp32.safetensors`                              | `diffusion_models/`     | `Kijai/MelBandRoFormer_comfy/`                                | ~340MB |

Total: ~25GB → fits comfortably on a 30GB Network Volume.

> Note on wav2vec model name: it's "chinese-base" but the model is trained on phoneme-level audio
> features, so it works for any language including Turkish/English. This is what the avatar model
> was trained against — do not swap it.

## Critical workflow constraints (from notes inside the JSON)

1. **base_precision MUST be `bf16`** in `WanVideoModelLoader`, even with fp8 weights file.
2. **sageattention 1.0.6 does NOT work** — install >= 2.0 or fall back to `flash_attn` / `sdpa`.
3. **3-stage chunk pipeline** — workflow generates video in 3 windows of 93 frames each
   (~5.8s @ 16fps per window) and stitches with overlap=13 frames. Final video = ~17s.
   Final output node: `id=453` (last `VHS_VideoCombine`). Filename prefix: `LongCat-Avatar`.

## Node IDs to override per request

| Node ID | Type                          | Field index / key   | What to set                                      |
|---------|-------------------------------|---------------------|--------------------------------------------------|
| 284     | LoadImage                     | widgets_values[0]   | input image filename (in ComfyUI/input/)         |
| 125     | LoadAudio                     | widgets_values[0]   | input audio filename                             |
| 241     | WanVideoTextEncodeCached      | widgets_values[2]   | positive prompt                                  |
| 241     | WanVideoTextEncodeCached      | widgets_values[3]   | negative prompt                                  |
| 245     | INTConstant (Width)           | widgets_values[0]   | output width (default 832)                       |
| 246     | INTConstant (Height)          | widgets_values[0]   | output height (default 480)                      |
| 122     | WanVideoModelLoader           | widgets_values[0]   | model filename (we use the fp8 KJ variant)       |
| 138     | WanVideoLoraSelect            | widgets_values[0]   | distill lora filename                            |
| 317     | TrimAudioDuration             | widgets_values[1]   | max audio samples (default 2048)                 |
| 423     | INTConstant (Overlap)         | widgets_values[0]   | chunk overlap frames (default 13)                |
| 438     | INTConstant (frames_per_window)| widgets_values[0]  | frames per chunk (default 93)                    |
| 427     | FloatConstant (cfg)           | widgets_values[0]   | classifier-free guidance scale (default 1)       |

## Output

- VHS_VideoCombine writes to `ComfyUI/output/LongCat-Avatar_<NNNNN>-audio.mp4`
- Handler reads the latest matching file from output dir.
