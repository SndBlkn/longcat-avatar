# LongCat-Avatar — çalıştırma rehberi

Bu doküman:
1. Bu repoda **şimdiye kadar deploy edilmiş** kaynakları,
2. **Yeni bir görüntü üretmek istediğinde** ne yapacağını,
3. Yol üstündeki bilinen sorunları ve workaround'ları

anlatır. Yapılan testlerin örnek çıktıları `examples/longcat_avatar_test_*.mp4` altında.

---

## 0. Şu an deploy edilmiş kaynaklar

| Kaynak | Değer |
|---|---|
| GitHub repo | https://github.com/SndBlkn/longcat-avatar |
| GHCR image | `ghcr.io/sndblkn/longcat-avatar/longcat-avatar-worker:latest` (public, anonymous-pullable) |
| RunPod Network Volume | id `4v75cezaqm`, **35 GB**, datacenter `EU-RO-1`, 6/6 model dosyası seed'li |
| RunPod Serverless Endpoint | id `91cujy5v5fmfeg` (configured ama yeni hesap kotası nedeniyle worker capacity'si yok — aşağıya bak) |
| RunPod Template | id `pau7ztq2t2` |
| Local UI config | `ui/.env.local` (`RUNPOD_API_KEY` + `RUNPOD_ENDPOINT_ID` yazılı) |

Volume'da bulunan model dosyaları (toplam ~30 GB):

```
/runpod-volume/models/
├── diffusion_models/
│   ├── LongCat/LongCat-Avatar-single_fp8_e4m3fn_scaled_mixed_KJ.safetensors  (16.9 GB)
│   └── MelBandRoformer_fp32.safetensors                                       (0.91 GB)
├── loras/LongCat_distill_lora_alpha64_bf16.safetensors                        (1.20 GB)
├── text_encoders/umt5-xxl-enc-bf16.safetensors                                (11.4 GB)
├── vae/Wan2_1_VAE_bf16.safetensors                                            (0.25 GB)
└── wav2vec/wav2vec2-chinese-base_fp16.safetensors                             (0.19 GB)
```

---

## 1. Bilinmesi gereken iki şey önce

### 1.1 Serverless şu an çalışmıyor (yeni hesap kotası)

Endpoint kuruldu, doğru template + volume + GPU listesi var, image public. **Ama** RunPod yeni hesaplara başlangıçta **0 serverless worker kotası** veriyor. Endpoint'e iş gönderince worker `throttled=1` durumunda kalıyor, kapasite tahsis edilmiyor.

→ Çözüm: RunPod Discord / Contact'tan kotanın artırılmasını iste. ("I want serverless to work for endpoint `91cujy5v5fmfeg`, EU-RO-1, RTX 4090. Pods work fine but serverless can't get capacity.") Genelde aynı gün açıyorlar.

Bu açılana kadar **regular GPU pod** ile aynı image'i çalıştırıyoruz — sonuç aynı, sadece auto-scaling yok.

### 1.2 GHCR image build'i dengesizdi

Ana build chain'i 7 push gerekti çünkü `runpod/worker-comfyui:5.0.0-base` base image'ı ile WanVideoWrapper'ın yeni sürümleri arasında çelişkiler var. Çözülmüş şeyler `worker/Dockerfile`'da:

- `sageattention==2.1.1` PyPI'da yok → düşürüldü, SDPA fallback default
- `pip` python3.10'a kuruluymuş ama ComfyUI python3.11 çalışıyormuş → `python -m pip` kullanılıyor + `get-pip.py` ile python3.11'e fresh pip kuruluyor
- Base image'daki **ComfyUI 0.3.30 çok eski** → `git fetch origin && git reset --hard origin/master` ile master'a çıkarılıyor (KJNodes ve WanVideoWrapper master gerektiriyor: `apply_rope1`, `comfy_api`)
- Audio cleanup için `MelBandRoFormer` custom node'u eklendi
- `start.sh` artık `PUBLIC_KEY` env'i varsa sshd'yi de açıyor — pod'da debug için

Bu fix'lerden bazıları `:latest` tag'lı son başarılı build'de yok olabilir (build #7 sırası şu an `a91475d` commit'inde — bu zincir hâlâ deneme aşamasında). Bu yüzden aşağıdaki kullanım rehberi pod boot'tan sonra **manuel düzeltme adımı** içeriyor — image stabilize olunca atlayabilirsin.

---

## 2. Yeni bir avatar video'su üretmek

İki yol var: **A) Pod ile** (her zaman çalışan), **B) Serverless ile** (kota açılınca tek tıkla).

### 2.1 Yol A — pod ile manuel çalıştırma (şu anki yöntem)

#### Adım 1 — input dosyalarını hazırla

**Portrait** — `examples/` altına bir kare/yatay yüz fotoğrafı koy. Yatay video için 16:9'a yakın oran tercih et (örnek `portrait.png` 2000×1116). Yüz merkezde olmalı çünkü workflow center-crop yapıyor.

**Audio** — 16 kHz mono WAV ya da MP3. Türkçe TTS için macOS'ta:

```bash
say -v Yelda -r 170 -o /tmp/sp.aiff "Türkçe metin buraya"
ffmpeg -y -i /tmp/sp.aiff -ar 16000 -ac 1 -c:a pcm_s16le examples/speech_tr.wav
```

Diğer seçenekler: ElevenLabs (paid, çok daha iyi), OpenAI TTS, Coqui XTTS (yerel GPU).

#### Adım 2 — pod aç

`scripts/launch_pod.sh` (aşağıda) RunPod REST API'yi kullanarak pod açıyor — sshd ile, volume mount'lu, ComfyUI 0.0.0.0:8188'de:

```bash
export RUNPOD_API_KEY='rpa_...'        # ui/.env.local'den
export PUBKEY="$(cat ~/.ssh/longcat_ed25519.pub)"   # SSH key (önce yarat: ssh-keygen -t ed25519 -N "" -f ~/.ssh/longcat_ed25519)

python3 - <<'PY'
import json, os
PK = os.environ['PUBKEY']
script = f'''#!/bin/bash
set -e
mkdir -p /root/.ssh && chmod 700 /root/.ssh
printf %s '{PK}' > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
ssh-keygen -A
/usr/sbin/sshd
cd /comfyui
mkdir -p /runpod-volume/_debug
exec python -u main.py --listen 0.0.0.0 --port 8188 --disable-auto-launch --disable-metadata --extra-model-paths-config /comfyui/extra_model_paths.yaml > /runpod-volume/_debug/comfy.log 2>&1
'''
body = {
  'name': 'longcat-run',
  'imageName': 'ghcr.io/sndblkn/longcat-avatar/longcat-avatar-worker:latest',
  'gpuTypeIds': ['NVIDIA GeForce RTX 4090'],
  'gpuCount': 1, 'cloudType': 'SECURE',
  'containerDiskInGb': 25, 'volumeInGb': 0,
  'networkVolumeId': '4v75cezaqm',
  'volumeMountPath': '/runpod-volume',
  'ports': ['22/tcp', '8188/http'],
  'dockerEntrypoint': ['bash','-c'],
  'dockerStartCmd': [script],
}
print(json.dumps(body))
PY > /tmp/pod.json

curl -s -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
     https://rest.runpod.io/v1/pods -d @/tmp/pod.json
```

`POD_ID` döner (örn. `1gdni6a6tp7fn1`). Image pull ~5-10 dk (12 GB compressed). Pod kuruldu mu test:

```bash
curl -s "https://${POD_ID}-8188.proxy.runpod.net/system_stats" -m 30
```

200 dönüyorsa ComfyUI ayakta. SSH portu için:

```bash
curl -s -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
  https://api.runpod.io/graphql \
  -d "{\"query\":\"{ pod(input:{podId:\\\"$POD_ID\\\"}) { runtime { ports { ip publicPort privatePort isIpPublic } } } }\"}"
```

`privatePort=22, isIpPublic=true` olan satır → host:port.

#### Adım 3 — pod'a manuel düzeltmeleri uygula

`:latest` image'da ComfyUI henüz upgrade edilmediyse (build #5+ stabilize olmadıysa) bu adım gerek. SSH'le bağlan ve sırayla:

```bash
SSH="ssh -i ~/.ssh/longcat_ed25519 -p $SSH_PORT root@$SSH_HOST"

# Eksik python3.11 paketleri
$SSH '/usr/bin/python -m pip install --no-cache-dir \
    ftfy accelerate einops diffusers peft sentencepiece protobuf \
    pyloudnorm gguf opencv-python imageio_ffmpeg color-matcher mss \
    librosa soundfile transformers rotary_embedding_torch'

# ComfyUI'yi master'a güncelle
$SSH 'cd /comfyui && git fetch origin master && git reset --hard origin/master && \
      /usr/bin/python -m pip install --no-cache-dir -r requirements.txt'

# MelBandRoFormer custom node'u
$SSH 'cd /comfyui/custom_nodes && [ -d ComfyUI-MelBandRoFormer ] || \
      git clone --depth 1 https://github.com/kijai/ComfyUI-MelBandRoFormer.git'

# Container restart (PID 1 öl → docker-init yeniden başlatır)
$SSH 'kill -TERM 1 2>/dev/null; true'
```

~1-2 dk sonra ComfyUI yeniden ayağa kalkar. Doğrula:

```bash
curl -s "https://${POD_ID}-8188.proxy.runpod.net/object_info" | python3 -c "
import sys,json
d=json.load(sys.stdin)
ok = 'WanVideoModelLoader' in d and 'MelBandRoFormerModelLoader' in d
print(f'WanVideo+Mel loaded: {ok}, total nodes: {len(d)}')"
```

`WanVideo+Mel loaded: True, total nodes: ~1100` görmen lazım.

#### Adım 4 — generation script'ini çalıştır

`scripts/run_avatar.py` (bu doküman ile aynı PR'da repoya konuyor; yoksa konuşmadaki sürüm `/tmp/run_avatar.py` altında).

```bash
POD_ID=$POD_ID \
PORTRAIT="examples/portrait.png" \
AUDIO="examples/speech_tr.wav" \
AUDIO_MAX_SECONDS=7.3 \
PROMPT="A woman with curly brown hair speaks calmly to the camera in a cozy bookshelf-lined room, soft natural daylight, photorealistic, clear lip-sync." \
python3 scripts/run_avatar.py
```

Script:
- ComfyUI'ye `/upload/image` ile portrait + audio'yu yükler
- workflow JSON'ını input filename + override'larla patch'ler
- UI workflow'u API formatına çevirir (handler.py'deki conversion logic'i)
- `/prompt` POST eder
- `/history` ile polling yapar
- Bitince `/view`'dan video'yu indirir

Çıkış: `examples/longcat_avatar_test_LongCat-Avatar_0000{1,2,3}-audio.mp4`. **00003 final** (overlap'ler birleşmiş tam sequence). Generation süresi RTX 4090 + SDPA ile ~16-18 dk (8 sn'lik video için).

#### Adım 5 — pod'u kapat (önemli, $0.69/saat akar)

```bash
curl -s -X DELETE -H "Authorization: Bearer $RUNPOD_API_KEY" \
     "https://rest.runpod.io/v1/pods/$POD_ID"
```

### 2.2 Yol B — serverless ile (RunPod kotanı açtıktan sonra)

Endpoint zaten kurulu (`91cujy5v5fmfeg`). `ui/.env.local` zaten yazılı.

```bash
cd ui
npm run dev
# http://localhost:3000
```

UI'da portrait + audio + prompt → **Çalıştır**. Veya doğrudan API'ye:

```bash
curl -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" \
     -H "Content-Type: application/json" \
     "https://api.runpod.ai/v2/91cujy5v5fmfeg/run" \
     -d '{"input": {"image": "<base64>", "audio": "<base64>", "prompt": "...", "audio_max_seconds": 7.3}}'

# Sonra polling:
curl -H "Authorization: Bearer $RUNPOD_API_KEY" \
     "https://api.runpod.ai/v2/91cujy5v5fmfeg/status/<job_id>"
```

Cevap `output.video_b64` içeriyor — base64-decode et, `.mp4` olarak yaz.

---

## 3. Önemli parametreler

`run_avatar.py` veya handler.py input olarak şunları kabul ediyor:

| Param | Default | Anlam |
|---|---|---|
| `width`, `height` | 832, 480 | Çıkış videosu boyutu. RTX 4090 (24 GB) için fp8 LongCat'in pratikte sığdığı max bu civarda. |
| `frames_per_window` | 53 | Bir sampling penceresinde üretilen frame sayısı. 53 ≈ 3.3 sn @ 16 fps. Daha uzun video → daha çok pencere → daha çok süre. |
| `overlap` | 13 | Pencereler arası overlap. 13'ten az = sallantılı, çok = redundant. |
| `cfg` | 1.0 | Classifier-free guidance. 1.0 = lora-distilled hızlı. 3-5 = daha "doğru" ama yavaş. |
| `audio_max_seconds` | yok | Audio'yu trim eder. Saniye cinsinden float. Tüm audio'yu kullanmak istersen es geç. |
| `seed` | -1 | -1 = random. Sabit seed üreten aynı çıkışı ver. |

UI ya da handler input format'ı `docs/WORKFLOW_NOTES.md`'de detaylı.

---

## 4. Bilinen sorunlar / notlar

- **Yüz crop'u**: Workflow ImageResizeKJv2 ile center-crop yapıyor. Yüz fotoğrafının ortada olduğundan emin ol. Geniş açılı çekimlerde yüz dışarı taşabilir.
- **8 sn üzeri video**: `frames_per_window` 53'te kalır, audio uzunluğu artar → daha çok pencere. Süre lineer artar.
- **Sageattn yok**: SDPA fallback'i kullanıyoruz (Dockerfile'dan sageattention pin'i kaldırıldı). Sageattention 2.x kurmak istersen image'a `flash_attn` + `sageattention` (kaynak derlemesi) eklemen gerek — bizim setup'ta yok.
- **Volume kotası 35 GB**: Şu an ~31 GB dolu. Yeni model dosyası eklemek istersen `seed/seed_volume.py`'ye ekleyip pod'da rerun et, 35 GB'a sığmazsa `PATCH /v1/networkvolumes/{id}` ile büyüt.
- **Build cache**: RunPod aynı host'a aynı image tekrar pull etmiyor. İlk pod 5-10 dk pull eder, sonraki pod'lar aynı host'a düşerse 30 sn'de kalkar.
- **GHCR image stable mi?**: Son başarılı build commit'i `git log` ile gör — workflow `:latest` tag'ını sadece o build pushladı. Image'da Pod'da manuel düzeltme adımı atlamak istersen önce `worker/Dockerfile` build'inin yeşil olduğundan emin ol.

---

## 5. Maliyet özeti (gerçek ölçüm)

| Kalem | Tutar |
|---|---|
| Network Volume (35 GB), aylık | $2.45 |
| RTX 4090 SECURE pod, saatlik | $0.69 |
| Bir avatar generation (8 sn video) | ~$0.20 (15-17 dk × $0.69/h) |
| Volume seed (tek seferlik, ~25 dk pod) | $0.30 |
| Toplam ilk kurulum + 2 test | ~$2.30 |

Endpoint scale-to-zero olduğu için **kullanmadığın saatlerde sadece $2.45/ay volume ücreti**.

---

## 6. Acil temizlik / tasarruf checklist

- [ ] Yanlışlıkla bırakılmış pod var mı? `curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" https://rest.runpod.io/v1/pods | jq '.[] | "\(.id) \(.desiredStatus) \(.costPerHr)"'`
- [ ] Endpoint workersMin = 0 mı? > 0 ise idle workers para yakar.
- [ ] Eskimiş `examples/longcat_avatar_test_*.mp4` dosyaları aynı isimle üst üste yazılıyor — yeni testten önce eski sonucu yedeklemek istiyorsan kopyala.

---

## 7. Repo'da ilgili dosyalar

| Dosya | Ne işe yarar |
|---|---|
| `worker/Dockerfile` | GHCR image — tüm fix'ler yapıştırılı |
| `worker/handler.py` | Serverless dispatch + workflow→API converter |
| `worker/start.sh` | Container entrypoint (sshd + ComfyUI + handler) |
| `worker/workflows/LongCatAvatar_audio_image_to_video_example_01.json` | Kijai'nin orijinal workflow JSON'u |
| `seed/seed_volume.py` | Volume seed script'i (model dosyalarını HF'den çekiyor) |
| `ui/` | Next.js 14 frontend (serverless endpoint'e konuşuyor) |
| `docs/SETUP.md` | İlk kurulum (volume + endpoint + UI) |
| `docs/WORKFLOW_NOTES.md` | Hangi node ID neyi override eder |
| `docs/RUN_GUIDE.md` | (bu doküman) |
