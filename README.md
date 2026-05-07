# LongCat-Avatar on RunPod Serverless

Cold-start, pay-per-use avatar video generation: portrait + audio → talking
head video. Click **Çalıştır** in the local UI, RunPod spins up a GPU worker,
ComfyUI runs the LongCat-Video-Avatar workflow, you get a video back. Worker
scales to zero when idle.

```
┌─────────────────────┐         ┌──────────────────────────┐
│  Local Next.js UI   │  HTTPS  │  RunPod Serverless       │
│  (browser on Mac)   │ ──────▶ │  Endpoint                │
│  • image + audio    │         │  • ComfyUI               │
│  • prompt + params  │         │  • WanVideoWrapper       │
│  • Çalıştır         │ ◀────── │  • LongCat-Avatar fp8    │
└─────────────────────┘         │  + Network Volume (25GB) │
                                └──────────────────────────┘
```

## Repo layout

| Path | Purpose |
|---|---|
| `worker/` | Docker image: ComfyUI + custom nodes + RunPod handler |
| `worker/workflows/` | Kijai's LongCat-Avatar workflow JSON (patched per request) |
| `seed/` | One-shot script that fills the Network Volume with model weights |
| `ui/` | Next.js 14 web UI (App Router + Tailwind) |
| `examples/` | Test portrait + audio for the first run |
| `docs/SETUP.md` | Step-by-step deployment guide |
| `docs/WORKFLOW_NOTES.md` | Reference: model files, node IDs, constraints |
| `.github/workflows/docker-publish.yml` | Auto-build worker image to GHCR |

## Quick start (after RunPod endpoint is live — see `docs/SETUP.md`)

```bash
# 1. Configure UI
cd ui
cp .env.local.example .env.local
$EDITOR .env.local        # set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID
npm install
npm run dev               # http://localhost:3000

# 2. Grab test inputs
cd ../examples
./fetch_samples.sh
```

Then in the browser, drop in the sample image + audio, click **Çalıştır**.

## Stack decisions, in short

- **Why Serverless instead of a dedicated pod?** Pay only for the seconds you
  generate; idle = no cost. RunPod's Flashboot keeps cold-starts ~60 s.
- **Why fp8 safetensors instead of GGUF?** The Frederic75 GGUF currently fails
  with `multitalk_audio_proj.proj1.weight` errors in WanVideoWrapper
  ([issue #1876](https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/1876)).
  Kijai's `LongCat-Avatar-single_fp8_e4m3fn_scaled_mixed_KJ.safetensors` is the
  same size (~14 GB), runs on the same RTX 4090, and is the one Kijai actually
  tests his wrapper against.
- **Why a Network Volume instead of baking models into the image?**
  ~25 GB of weights → 25 GB of image pull on every cold start otherwise.
  Volume-resident weights load in seconds.
- **Why GHCR instead of Docker Hub?** No separate account; GitHub Actions
  pushes with the workflow's built-in token. Public packages pull without auth.

## What you still need to do

- [ ] Push this repo to GitHub (worker image will auto-build on first push).
- [ ] Create a RunPod Network Volume (30 GB) and run `seed/seed_volume.py`.
- [ ] Create the Serverless Endpoint pointing at the GHCR image, attach the
      volume, copy the endpoint ID.
- [ ] Drop API key + endpoint ID into `ui/.env.local`.
- [ ] `npm run dev` and generate.

Full walk-through: [`docs/SETUP.md`](docs/SETUP.md).

## Cost estimate (rough, 2026 prices)

| Item | $ |
|---|---|
| Network Volume (30 GB), monthly | $2.10 |
| RTX 4090 serverless, per second | $0.00044 |
| One ~5 s avatar (avg ~150 s GPU time) | ~$0.07 |
| One ~17 s avatar (3 chunks, avg ~450 s GPU time) | ~$0.20 |

Cold-start (~75 s) is billed too, so the first request after idle costs an
extra ~$0.03.
