#!/usr/bin/env bash
# Download a portrait + a short speech clip for end-to-end UI testing.
#
# Sources are public-domain / freely-licensed:
#   - Portrait: Wikimedia Commons (CC0 / PD)
#   - Speech:   LJ Speech (public domain)
set -euo pipefail

cd "$(dirname "$0")"

UA="Mozilla/5.0 (longcat-avatar-examples)"

PORTRAIT_URL="https://upload.wikimedia.org/wikipedia/commons/thumb/8/8d/President_Barack_Obama.jpg/640px-President_Barack_Obama.jpg"
PORTRAIT_FALLBACK="https://upload.wikimedia.org/wikipedia/commons/8/8d/President_Barack_Obama.jpg"

# Short, clear English speech sample (signalogic.com — public engineering sample).
SPEECH_URL="https://www.signalogic.com/melp/EngSamples/Orig/male.wav"

if [ ! -f portrait.jpg ]; then
    echo "[get] portrait.jpg"
    if ! curl -fsSL -A "$UA" "$PORTRAIT_URL" -o portrait.jpg; then
        echo "[warn] thumbnail URL failed; trying full-size original" >&2
        curl -fsSL -A "$UA" "$PORTRAIT_FALLBACK" -o portrait.jpg
    fi
fi

if [ ! -f speech.wav ]; then
    echo "[get] speech.wav"
    if ! curl -fsSL -A "$UA" "$SPEECH_URL" -o speech.wav; then
        echo "[warn] online sample unreachable; generating one with macOS 'say'." >&2
        if command -v say >/dev/null 2>&1; then
            tmp_aiff="$(mktemp -t longcat).aiff"
            say -v Samantha -o "$tmp_aiff" \
                "Hello! This is a test of the LongCat Avatar pipeline. \
The quick brown fox jumps over the lazy dog."
            # Convert AIFF to WAV via afconvert (preinstalled on macOS).
            afconvert -f WAVE -d LEI16@22050 "$tmp_aiff" speech.wav
            rm -f "$tmp_aiff"
        else
            echo "[err ] no fallback available — provide your own speech.wav" >&2
            exit 1
        fi
    fi
fi

ls -lh portrait.jpg speech.wav
echo
echo "Drop these into the UI (http://localhost:3000) once your endpoint is live."
