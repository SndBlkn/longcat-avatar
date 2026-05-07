FROM runpod/worker-comfyui:5.0.0-base

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    COMFY_HOME=/comfyui

WORKDIR /comfyui

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ffmpeg libsndfile1 openssh-server \
    && mkdir -p /var/run/sshd \
    && rm -rf /var/lib/apt/lists/*

# The base image ships ComfyUI 0.3.30; KJNodes/WanVideoWrapper require a
# newer ComfyUI (apply_rope1, comfy_api). Pull master.
RUN git fetch origin && git reset --hard origin/master && \
    python -m pip install --no-cache-dir -r requirements.txt

RUN cd custom_nodes && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-WanVideoWrapper.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git && \
    git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git

RUN python -m pip install --no-cache-dir \
        -r custom_nodes/ComfyUI-WanVideoWrapper/requirements.txt \
        -r custom_nodes/ComfyUI-KJNodes/requirements.txt \
        -r custom_nodes/ComfyUI-VideoHelperSuite/requirements.txt

RUN python -m pip install --no-cache-dir \
        librosa==0.10.2 \
        soundfile==0.12.1 \
        einops==0.8.0 \
        transformers>=4.45.0

COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml
COPY workflows/ /workflows/
COPY handler.py /handler.py
COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]
