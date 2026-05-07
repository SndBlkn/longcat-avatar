# Test inputs

The pipeline accepts any portrait image (PNG/JPG, frontal face) and any short
audio clip (WAV/MP3 with clear speech). For the very first run we suggest open
test data so you can verify the endpoint end-to-end before swapping in your own
content.

Run `./fetch_samples.sh` to populate `examples/` with:

- `portrait.jpg` — a public-domain portrait from Wikimedia Commons
- `speech.wav` — a public-domain LJSpeech excerpt (~6 seconds, English)

Then in the UI:

1. Click **Referans portre** → pick `portrait.jpg`.
2. Click **Konuşma sesi** → pick `speech.wav`.
3. Prompt: leave the default, or write your own scene description.
4. Hit **Çalıştır**.

Expected: a ~5–17 s talking-head video in 90–180 s on RTX 4090
(plus 60–90 s cold-start the very first time).
