# LongCat-Avatar — çalıştırma rehberi

Bu doküman:
1. Repoda **kalıcı olarak duran** şeyler,
2. **Yeni bir görüntü üretmek istediğinde** sıfırdan ne yapacağın,
3. Yol üstündeki bilinen sorunları ve workaround'ları

anlatır. Yapılan testlerin örnek çıktıları `examples/longcat_avatar_test_*.mp4` altında.

---

## 0. Mevcut durum

**RunPod tarafı boş.** Aylık $2.45 volume ücreti yakmasın diye bütün RunPod kaynaklarını sildik:

| Kaynak | Durum |
|---|---|
| Network Volume `longcat-models` (35 GB, EU-RO-1) | **silindi** — modeller dahil tüm seed'leme yok oldu |
| Serverless Endpoint `91cujy5v5fmfeg` | **silindi** |
| Template `pau7ztq2t2` | **silindi** |
| Pod | yok (her zaman silinmiş halde tutuluyor) |

**Repoda duran:**

| Kaynak | Değer |
|---|---|
| GitHub repo | https://github.com/SndBlkn/longcat-avatar |
| GHCR image | `ghcr.io/sndblkn/longcat-avatar/longcat-avatar-worker:latest` (public, anonymous-pullable, GitHub Actions otomatik build ediyor) |
| Worker kodu, workflow JSON, seed script, UI, doc'lar | kalıcı |

Yani **yeniden başlamak için**: yeni volume yarat → seed et → pod (veya endpoint) ayağa kaldır → çalıştır. Bu doc bunu adım adım anlatıyor.

`ui/.env.local` içindeki `RUNPOD_ENDPOINT_ID` artık geçersiz — yeni endpoint kurulduğunda güncelle. `RUNPOD_API_KEY` (şayet rotate ettiysen) yeni key ile değiştirilmeli.

---

## 1. Bilinmesi gereken iki şey önce

### 1.1 Yeni hesapta serverless throttle riski

Yeni RunPod hesaplarına başlangıçta **0 (veya çok dar) serverless worker kotası** veriliyor. Endpoint'e job gönderince `workers.throttled=1` görüp kapasite tahsis edilmeyebilir.

→ Çözüm: RunPod Discord/Contact'a yaz: "I want serverless to work for endpoint `<id>`, EU-RO-1, RTX 4090. Pods work fine but serverless can't get capacity." Genelde aynı gün açıyorlar.

Bu açılana kadar **regular GPU pod** ile aynı image'i çalıştır (Yol A) — sonuç aynı, sadece auto-scaling yok.

### 1.2 GHCR image build'i dengesizdi

Ana build chain'i 7 push gerekti çünkü `runpod/worker-comfyui:5.0.0-base` base image'ı ile WanVideoWrapper'ın yeni sürümleri arasında çelişkiler var. Çözülmüş şeyler `worker/Dockerfile`'da:

- `sageattention==2.1.1` PyPI'da yok → düşürüldü, SDPA fallback default
- `pip` python3.10'a kuruluymuş ama ComfyUI python3.11 çalışıyormuş → `python -m pip` kullanılıyor + `get-pip.py` ile python3.11'e fresh pip kuruluyor
- Base image'daki **ComfyUI 0.3.30 çok eski** → `git fetch origin && git reset --hard origin/master` ile master'a çıkarılıyor (KJNodes ve WanVideoWrapper master gerektiriyor: `apply_rope1`, `comfy_api`)
- Audio cleanup için `MelBandRoFormer` custom node'u eklendi
- `start.sh` artık `PUBLIC_KEY` env'i varsa sshd'yi de açıyor — pod'da debug için

Bu fix'lerden bazıları `:latest` tag'lı son başarılı build'de yok olabilir (build #7 sırası şu an `a91475d` commit'inde — bu zincir hâlâ deneme aşamasında). Bu yüzden aşağıdaki kullanım rehberi pod boot'tan sonra **manuel düzeltme adımı** içeriyor — image stabilize olunca atlayabilirsin.

---

## 2. Sıfırdan başlatma — checklist

Volume yokken her şey sıfırdan kuruluyor. Sıra:

1. **(zorunlu)** Network Volume yarat → seed et — § 2.0
2. **(seçenek A)** Pod ile manuel run — § 2.1
3. **(seçenek B)** Serverless endpoint kur + UI ile run — § 2.2

`docs/SETUP.md` ilk kurulumun daha geniş hali; § 2.0 burada özet.

### 2.0 Network Volume yarat ve seed et

Yaklaşık 25-30 dk sürer (~14 GB main fp8 + 11 GB UMT5 + diğer dosyalar HF'den indirilir).

```bash
export RUNPOD_API_KEY='rpa_...'

# 1) 35 GB volume yarat (EU-RO-1, RTX 4090 stoku iyi)
curl -s -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" \
     -H "Content-Type: application/json" \
     https://rest.runpod.io/v1/networkvolumes \
     -d '{"name":"longcat-models","size":35,"dataCenterId":"EU-RO-1"}'
# Dönüş: {"id":"xxxxxxxxxx", ...} → bu id'yi her yerde kullanacaksın
export VOLUME_ID="..."

# 2) Geçici seed pod'u (RTX 4090; A5000 stoku varsa daha ucuz: $0.16/h)
export PUBKEY="$(cat ~/.ssh/longcat_ed25519.pub)"   # yoksa: ssh-keygen -t ed25519 -N "" -f ~/.ssh/longcat_ed25519
python3 - <<PY > /tmp/seed_pod.json
import json, os
PK = os.environ['PUBKEY']
script = f'''#!/bin/bash
set -e
mkdir -p /root/.ssh && chmod 700 /root/.ssh
printf %s '{PK}' > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
ssh-keygen -A
/usr/sbin/sshd
apt-get update -qq && apt-get install -y -qq curl ca-certificates
pip install --no-cache-dir huggingface_hub tqdm
mkdir -p /runpod-volume/models
curl -fsSL https://raw.githubusercontent.com/SndBlkn/longcat-avatar/main/seed/seed_volume.py -o /tmp/seed.py
python3 /tmp/seed.py
touch /runpod-volume/.SEED_DONE
echo SEEDING_COMPLETE
sleep 7200
'''
body = {{
  'name': 'longcat-seed',
  'imageName': 'python:3.11',
  'gpuTypeIds': ['NVIDIA GeForce RTX 4090'],
  'gpuCount': 1, 'cloudType': 'SECURE',
  'containerDiskInGb': 15, 'volumeInGb': 0,
  'networkVolumeId': '{os.environ.get("VOLUME_ID","REPLACE_ME")}',
  'volumeMountPath': '/runpod-volume',
  'ports': ['22/tcp'],
  'env': {{'PUBLIC_KEY': PK, 'VOLUME_ROOT': '/runpod-volume/models'}},
  'dockerEntrypoint': ['bash','-c'],
  'dockerStartCmd': [script],
}}
print(json.dumps(body))
PY

curl -s -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
     https://rest.runpod.io/v1/pods -d @/tmp/seed_pod.json
# Dönüş: {"id":"...", ...} → POD_ID
```

Pod'da seed script'i ~20 dk çalışır. SSH host:port öğrenip bağlan, `SEEDING_COMPLETE` mesajını ve 6 dosyayı görene kadar bekle:

```bash
# host:port öğren
curl -s -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
     https://api.runpod.io/graphql \
     -d "{\"query\":\"{ pod(input:{podId:\\\"$POD_ID\\\"}) { runtime { ports { ip publicPort privatePort isIpPublic } } } }\"}"

# Bağlan, ilerlemeyi gör
ssh -i ~/.ssh/longcat_ed25519 -p $PORT root@$HOST 'find /runpod-volume/models -name "*.safetensors" -exec ls -lh {} +'
```

6 dosya geldiğinde pod'u sil:

```bash
curl -s -X DELETE -H "Authorization: Bearer $RUNPOD_API_KEY" "https://rest.runpod.io/v1/pods/$POD_ID"
```

Volume artık dolu, $2.45/ay duruyor. İleride yeniden silmek istersen § 6'ya bak.

Volume'daki dosya layout (toplam ~30 GB):

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

> Not: `wav2vec2-chinese-base` Çince konuşma için fine-tune edilmiş — **Türkçe lip-sync zayıf olur**. § 4.7'ye bak.

---

### 2.1 Yol A — pod ile manuel çalıştırma

Volume seed'lendikten sonra. Bu yöntem RunPod'un serverless kotası açılana kadar (veya hiç açılmasa bile) her zaman işe yarar.

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
  'networkVolumeId': os.environ['VOLUME_ID'],
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

### 2.2 Yol B — serverless endpoint kur ve UI ile çalıştır

Volume seed'lendikten sonra endpoint'i kurarsın. RunPod yeni hesaplara serverless kotası dar verdiği için ilk job'lar capacity throttle yiyebilir; o zaman ya RunPod desteğinden quota artırmasını iste, ya Yol A'ya dön.

```bash
export RUNPOD_API_KEY='rpa_...'
export VOLUME_ID="..."

# 1) Template yarat
curl -s -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
     https://rest.runpod.io/v1/templates -d '{
  "name": "longcat-avatar-worker",
  "imageName": "ghcr.io/sndblkn/longcat-avatar/longcat-avatar-worker:latest",
  "containerDiskInGb": 20,
  "volumeMountPath": "/runpod-volume",
  "isServerless": true,
  "category": "NVIDIA",
  "isPublic": false,
  "env": {
    "LORA_FILENAME": "LongCat_distill_lora_alpha64_bf16.safetensors",
    "MODEL_FILENAME": "LongCat/LongCat-Avatar-single_fp8_e4m3fn_scaled_mixed_KJ.safetensors",
    "ATTENTION_MODE": "sdpa"
  }
}'
# Dönüş: {"id": "TEMPLATE_ID", ...}
export TEMPLATE_ID="..."

# 2) Endpoint yarat
curl -s -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
     https://rest.runpod.io/v1/endpoints \
     -d "{\"templateId\":\"$TEMPLATE_ID\",\"name\":\"longcat-avatar\"}"
# Dönüş: {"id": "ENDPOINT_ID", ...}
export ENDPOINT_ID="..."

# 3) PATCH ile GPU + scaling + volume + DC ayarları
curl -s -X PATCH -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
     "https://rest.runpod.io/v1/endpoints/$ENDPOINT_ID" -d "{
  \"gpuTypeIds\": [\"NVIDIA GeForce RTX 4090\", \"NVIDIA RTX A6000\", \"NVIDIA GeForce RTX 5090\"],
  \"gpuCount\": 1,
  \"workersMin\": 0,
  \"workersMax\": 1,
  \"idleTimeout\": 5,
  \"executionTimeoutMs\": 1800000,
  \"flashboot\": true,
  \"networkVolumeId\": \"$VOLUME_ID\",
  \"dataCenterIds\": [\"EU-RO-1\"],
  \"scalerType\": \"QUEUE_DELAY\",
  \"scalerValue\": 4
}"
```

UI'a yaz:

```bash
cat > ui/.env.local <<EOF
RUNPOD_API_KEY=$RUNPOD_API_KEY
RUNPOD_ENDPOINT_ID=$ENDPOINT_ID
EOF

cd ui && npm run dev
# http://localhost:3000
```

UI'da portrait + audio + prompt → **Çalıştır**. Veya doğrudan API:

```bash
curl -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" \
     -H "Content-Type: application/json" \
     "https://api.runpod.ai/v2/$ENDPOINT_ID/run" \
     -d '{"input": {"image": "<base64>", "audio": "<base64>", "prompt": "...", "audio_max_seconds": 7.3}}'

curl -H "Authorization: Bearer $RUNPOD_API_KEY" \
     "https://api.runpod.ai/v2/$ENDPOINT_ID/status/<job_id>"
```

Çıkış `output.video_b64` — base64 decode → `.mp4`.

**Quota throttle yiyorsan**: `health` endpoint'i 5+ dakika `workers.throttled=1` döndürüyorsa quota dar. RunPod Discord/Contact'a yaz: "I want serverless to work for endpoint `<id>`, EU-RO-1, RTX 4090. Pods work fine but serverless can't get capacity." Genelde aynı gün açıyorlar.

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

- **4.1 Yüz crop'u**: Workflow ImageResizeKJv2 ile center-crop yapıyor. Yüz fotoğrafının ortada olduğundan emin ol. Geniş açılı çekimlerde yüz dışarı taşabilir.
- **4.2 8 sn üzeri video**: `frames_per_window` 53'te kalır, audio uzunluğu artar → daha çok pencere. Süre lineer artar.
- **4.3 Sageattn yok**: SDPA fallback'i kullanıyoruz (Dockerfile'dan sageattention pin'i kaldırıldı). Sageattention 2.x kurmak istersen image'a `flash_attn` + `sageattention` (kaynak derlemesi) eklemen gerek — bizim setup'ta yok.
- **4.4 Volume kotası 35 GB**: Şu an ~31 GB dolu (volume yarattığında). Yeni model dosyası eklemek istersen `seed/seed_volume.py`'ye ekleyip pod'da rerun et, 35 GB'a sığmazsa `PATCH /v1/networkvolumes/{id}` ile büyüt.
- **4.5 Build cache**: RunPod aynı host'a aynı image tekrar pull etmiyor. İlk pod 5-10 dk pull eder, sonraki pod'lar aynı host'a düşerse 30 sn'de kalkar.
- **4.6 GHCR image stable mi?**: Son başarılı build commit'i `git log` ile gör — workflow `:latest` tag'ını sadece o build pushladı. Pod'da manuel düzeltme adımını atlamak istersen önce `worker/Dockerfile` build'inin yeşil olduğundan emin ol.
- **4.7 Türkçe / İngilizce lip-sync zayıf**: LongCat-Video-Avatar **Çince konuşma** verisiyle eğitilmiş. Workflow audio feature extractor'ı `TencentGameMate/chinese-wav2vec2-base` indiriyor. Çince dışında dillerde dudak hareketleri kabaca senkronize ama söylenen sözcüklerle eşleşmez (genelde "ortalama" bir açma-kapama hareketi). Multilingual istiyorsan **HunyuanAvatar / Hallo-3 / EchoMimicV2 / OmniHuman-1** gibi başka modellere bak — bu pipeline yetmez.

---

## 5. Maliyet özeti (gerçek ölçüm)

| Kalem | Tutar |
|---|---|
| Network Volume (35 GB), aylık | $2.45 |
| RTX 4090 SECURE pod, saatlik | $0.69 |
| Bir avatar generation (8 sn video) | ~$0.20 (15-17 dk × $0.69/h) |
| Volume seed (tek seferlik, ~25 dk pod) | $0.30 |

Endpoint scale-to-zero olduğu için **kullanmadığın saatlerde sadece $2.45/ay volume ücreti**.

> Bu bölümde tek "kalıcı" maliyet volume. Volume sildiğinde aylık ücret 0 olur ama bir sonraki kullanımda 25 dk ek seed bekleme + tekrar $0.30.

---

## 6. Acil temizlik / tasarruf checklist

### 6.1 Hepsini sil (volume dahil — ay sonu maliyet 0)

```bash
export RUNPOD_API_KEY='rpa_...'

# Pod'lar (varsa)
for id in $(curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" https://rest.runpod.io/v1/pods | python3 -c 'import sys,json;[print(p["id"]) for p in json.load(sys.stdin)]'); do
  curl -s -X DELETE -H "Authorization: Bearer $RUNPOD_API_KEY" "https://rest.runpod.io/v1/pods/$id"
done

# Endpoint
for id in $(curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" https://rest.runpod.io/v1/endpoints | python3 -c 'import sys,json;[print(e["id"]) for e in json.load(sys.stdin)]'); do
  curl -s -X DELETE -H "Authorization: Bearer $RUNPOD_API_KEY" "https://rest.runpod.io/v1/endpoints/$id"
done

# Template
for id in $(curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" https://rest.runpod.io/v1/templates | python3 -c 'import sys,json;[print(t["id"]) for t in json.load(sys.stdin) if t.get("name","").startswith("longcat")]'); do
  curl -s -X DELETE -H "Authorization: Bearer $RUNPOD_API_KEY" "https://rest.runpod.io/v1/templates/$id"
done

# Volume — ÖNCE endpoint silinmeli yoksa "must remove from all pods" hatası verir
for id in $(curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" https://rest.runpod.io/v1/networkvolumes | python3 -c 'import sys,json;[print(v["id"]) for v in json.load(sys.stdin)]'); do
  curl -s -X DELETE -H "Authorization: Bearer $RUNPOD_API_KEY" "https://rest.runpod.io/v1/networkvolumes/$id"
done
```

### 6.2 Hızlı sanity check

- Yanlışlıkla bırakılmış pod var mı?
  ```bash
  curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" https://rest.runpod.io/v1/pods | python3 -c "import sys,json;[print(p['id'],p['desiredStatus'],p.get('costPerHr')) for p in json.load(sys.stdin)]"
  ```
- Endpoint `workersMin` > 0 ise idle workers para yakar.
- Eskimiş `examples/longcat_avatar_test_*.mp4` dosyaları aynı isimle üst üste yazılıyor — yeni testten önce eski sonucu yedeklemek istiyorsan kopyala.

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
