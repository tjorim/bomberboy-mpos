#!/bin/sh
# Re-encode bomberboy/sounds/*.wav in place from PCM to IMA ADPCM, using
# adpcm-xq (https://github.com/dbry/adpcm-xq) -- quarters the file size with
# minimal audible loss, and is what MicroPythonOS's AudioManager decodes
# (see https://docs.micropythonos.com/frameworks/audiomanager/).
#
# adpcm-xq only reads 16-bit PCM; BombDrop.wav ships as 8-bit, so it's
# upsampled with ffmpeg first.
#
# Usage:
#   git clone https://github.com/dbry/adpcm-xq.git
#   cmake -S adpcm-xq -B adpcm-xq/build && cmake --build adpcm-xq/build
#   scripts/compress_sounds.sh adpcm-xq/build/adpcm-xq
set -eu

ADPCM_XQ="${1:?usage: compress_sounds.sh /path/to/adpcm-xq}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOUNDS_DIR="$REPO_ROOT/bomberboy/sounds"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for f in "$SOUNDS_DIR"/*.wav; do
    name="$(basename "$f")"
    src="$f"
    if ! "$ADPCM_XQ" -q -y "$src" "$TMP/$name" 2>/dev/null; then
        ffmpeg -y -loglevel error -i "$src" -acodec pcm_s16le "$TMP/16bit_$name"
        "$ADPCM_XQ" -q -y "$TMP/16bit_$name" "$TMP/$name"
    fi
    mv "$TMP/$name" "$f"
done
