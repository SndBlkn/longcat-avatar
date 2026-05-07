#!/usr/bin/env bash
set -euo pipefail

# Optional sshd for debugging / interactive workflow runs in regular pods.
if [[ -n "${PUBLIC_KEY:-}" ]]; then
    echo "[boot] PUBLIC_KEY set; configuring sshd..."
    mkdir -p /root/.ssh
    chmod 700 /root/.ssh
    echo "$PUBLIC_KEY" > /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
    sed -i 's/#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config || true
    ssh-keygen -A
    /usr/sbin/sshd
fi

cd /comfyui

echo "[boot] Starting ComfyUI server in background..."
python main.py \
    --listen 127.0.0.1 \
    --port 8188 \
    --disable-auto-launch \
    --disable-metadata \
    --extra-model-paths-config /comfyui/extra_model_paths.yaml \
    > /comfyui/comfyui.log 2>&1 &

COMFY_PID=$!
echo "[boot] ComfyUI PID=$COMFY_PID, waiting for /system_stats ..."

for i in $(seq 1 120); do
    if curl -sf http://127.0.0.1:8188/system_stats > /dev/null; then
        echo "[boot] ComfyUI ready after ${i}s"
        break
    fi
    if ! kill -0 $COMFY_PID 2>/dev/null; then
        echo "[boot] ComfyUI process died. Last 80 log lines:"
        tail -n 80 /comfyui/comfyui.log
        exit 1
    fi
    sleep 1
done

if ! curl -sf http://127.0.0.1:8188/system_stats > /dev/null; then
    echo "[boot] ComfyUI did not become ready in 120s. Logs:"
    tail -n 100 /comfyui/comfyui.log
    exit 1
fi

echo "[boot] Launching RunPod handler..."
exec python -u /handler.py
