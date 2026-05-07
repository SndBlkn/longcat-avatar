# LongCat-Avatar on RunPod Serverless — End-to-End Setup

This guide walks you through standing up the whole pipeline:

1. Push the worker Docker image to **GHCR**
2. Seed the **Network Volume** with model weights
3. Create a **Serverless Endpoint** that pulls the image and mounts the volume
4. Configure the **local UI** with your API key + endpoint ID
5. Run your first generation

Estimated one-time setup time: **45–75 minutes** (mostly waiting on downloads
and image build).

---

## Prerequisites

| What | Why |
|---|---|
| GitHub account + a repo containing this codebase | GHCR hosts the worker image |
| RunPod account with billing enabled | GPU + storage |
| ~$5 of RunPod credit | Image-pull pod, seeding, first test runs |

---

## Step 1 — Push the worker image to GHCR

The repo includes `.github/workflows/docker-publish.yml`. The first push to
`main` will build the image and push it to:

    ghcr.io/<your-gh-user-or-org>/<repo-name>/longcat-avatar-worker:latest

> **Make the package public** after the first push: GitHub → your profile →
> Packages → `longcat-avatar-worker` → Package settings → Change visibility →
> Public. Otherwise RunPod can't pull it without a registry credential.

Alternatively, you can build & push locally:

```bash
cd worker
docker buildx build --platform linux/amd64 \
  -t ghcr.io/<you>/longcat/longcat-avatar-worker:latest \
  --push .
```

Image size: ~6 GB (no models — they live on the volume).

---

## Step 2 — Create & seed the Network Volume

See [`seed/README.md`](../seed/README.md) for the detailed flow. TL;DR:

1. RunPod Console → **Storage → Network Volumes → New Network Volume**:
   - Datacenter: pick one (e.g. `EU-RO-1`)
   - Size: **30 GB**
2. Create a temporary CPU pod with that volume attached at `/runpod-volume`.
3. Run `seed/seed_volume.py` on it. Wait ~15–25 min.
4. Terminate the pod. Volume persists.

Note the **Volume ID** — you will need it in Step 3.

---

## Step 3 — Create the Serverless Endpoint

RunPod Console → **Serverless → New Endpoint**.

| Field | Value |
|---|---|
| Endpoint name | `longcat-avatar` |
| Worker source | **Container image** |
| Image | `ghcr.io/<you>/longcat/longcat-avatar-worker:latest` |
| Container disk | **20 GB** (worker image + ComfyUI scratch) |
| Container start command | *(leave blank — `CMD` in Dockerfile handles it)* |
| GPU | **RTX 4090 (24 GB)** — minimum for fp8. RTX A5000 also works. |
| Max workers | 1 (raise later if you need parallelism) |
| Idle timeout | 5 s |
| Execution timeout | 1800 s (30 min — generation takes a few minutes) |
| Flashboot | **Enabled** (cuts cold-start dramatically) |
| Network Volume | **Attach** the volume from Step 2; mount path `/runpod-volume` |
| Datacenter | **Must match the volume's datacenter** |

Hit **Deploy**. Wait until status shows `READY`.

Copy the **Endpoint ID** (looks like `abc123def456ghi`).

Generate an **API Key**: Console → Settings → API Keys → Create.

---

## Step 4 — Configure the local UI

```bash
cd ui
cp .env.local.example .env.local
# Edit .env.local:
#   RUNPOD_API_KEY=rpa_...
#   RUNPOD_ENDPOINT_ID=abc123def456ghi

npm install
npm run dev
# Open http://localhost:3000
```

---

## Step 5 — First generation

In the UI:

1. Drop a **portrait image** (PNG/JPG, ideally a centered face, 832×480 fits the workflow's default size best).
2. Drop an **audio file** (WAV/MP3, ≤ ~10 s for first test).
3. Type a **prompt** describing the scene.
4. Hit **Çalıştır**.

Expected timing on RTX 4090:

| Phase | Time |
|---|---|
| Cold start (first request only) | 60–90 s |
| Generation (per ~5.8 s of video) | 90–180 s |
| Video transfer back | a few seconds |

The video appears in the UI when ready. Click download to save it.

Subsequent requests within 5 minutes reuse the warm worker (~5–10 s overhead).
After 5 min of idle the worker scales to zero and the next request is cold again.

---

## Troubleshooting

- **Endpoint stuck on `IN_QUEUE`** → check the worker logs in the endpoint's
  **Workers** tab. Most common cause: image still pulling, or model files
  missing on the volume.
- **`KeyError: 'multitalk_audio_proj.proj1.weight'`** → you accidentally
  pointed the loader at a GGUF file. The fp8 KJ safetensors does not have
  this issue. Verify `MODEL_FILENAME` env or workflow node 122 widget value.
- **OOM on RTX 4090** → enable BlockSwap in the workflow (the example already
  has the node) and reduce `frames_per_window` from 93 → 53.
- **Cold start very slow (> 3 min)** → enable Flashboot on the endpoint, and
  make sure the volume is in the same datacenter as the worker.
