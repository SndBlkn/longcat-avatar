# Network Volume Seeding

This is a **one-time** setup step that copies ~25 GB of model weights into your
RunPod Network Volume so that the serverless worker can read them at cold-start
without baking them into the Docker image.

## What you need

1. A **RunPod Network Volume** (any datacenter — but it must match the region
   your serverless endpoint will run in). 30 GB is the recommended minimum.
2. A throwaway **CPU pod** in the same region with that volume attached at
   `/runpod-volume`. CPU-only is fine and cheap (~$0.05/hr).
3. A Hugging Face token if you want faster/private downloads (optional — the
   models we use are public).

## Steps

1. Create the Network Volume in RunPod's web UI: **Storage → Network Volumes
   → New Network Volume**. Pick a datacenter (e.g. `EU-RO-1` or `US-CA-2`)
   and 30 GB. Note the **Volume ID** and **datacenter** — you will pin your
   serverless endpoint to the same datacenter.
2. Spin up a temporary CPU pod (RunPod Console → Pods → Deploy →
   `runpod/base:0.6.2` or any Ubuntu/Python image), attach the volume.
3. SSH into the pod and run:

   ```bash
   pip install huggingface_hub
   curl -O https://raw.githubusercontent.com/<your-fork>/longcat/main/seed/seed_volume.py
   # Or scp the file from your local clone:
   #   scp seed/seed_volume.py root@<pod-ip>:/root/

   export HF_TOKEN=hf_...        # optional but speeds things up
   python seed_volume.py
   ```

   First run takes 10–25 minutes depending on region/network. The script
   checkpoints per file: a re-run will skip everything already on disk.

4. Verify:

   ```bash
   du -sh /runpod-volume/models/*
   ```

   Expected:

   ```
    14G  /runpod-volume/models/diffusion_models
   600M  /runpod-volume/models/loras
    10G  /runpod-volume/models/text_encoders
   250M  /runpod-volume/models/vae
   200M  /runpod-volume/models/wav2vec
   ```

5. Stop and **terminate** the seeding pod (the volume persists). The volume
   is now ready to attach to the serverless endpoint.

## Cost estimate

- CPU pod for 30 min: ~$0.03
- Volume storage: $0.07/GB/month → 30 GB ≈ **$2.10/month**, ongoing.
