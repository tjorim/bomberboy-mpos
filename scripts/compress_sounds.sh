#!/bin/sh
# Re-encode sounds_src/*.wav (lossless PCM masters) to bomberboy/sounds/*.wav
# (4-bit IMA ADPCM, what actually ships with the app), using adpcm-xq
# (https://github.com/dbry/adpcm-xq) -- quarters the file size with minimal
# audible loss, and is the format MicroPythonOS's AudioManager decodes
# natively (see https://docs.micropythonos.com/frameworks/audiomanager/).
#
# Always encode from sounds_src/, never from bomberboy/sounds/: adpcm-xq
# picks encode vs. decode based on the *input* file's format, so pointing it
# at an already-ADPCM file silently decodes it back to bloated PCM (exit 0,
# no error) instead of failing loudly. Keeping the lossless masters separate
# avoids that footgun and repeated lossy re-encodes.
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
SRC_DIR="$REPO_ROOT/sounds_src"
OUT_DIR="$REPO_ROOT/bomberboy/sounds"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for f in "$SRC_DIR"/*.wav; do
    name="$(basename "$f")"
    src="$f"
    if ! "$ADPCM_XQ" -q -y "$src" "$TMP/$name" 2>/dev/null; then
        ffmpeg -y -loglevel error -i "$src" -acodec pcm_s16le "$TMP/16bit_$name"
        "$ADPCM_XQ" -q -y "$TMP/16bit_$name" "$TMP/$name"
    fi
    out_size=$(wc -c < "$TMP/$name")
    src_size=$(wc -c < "$src")
    if [ "$out_size" -ge "$src_size" ]; then
        echo "compress_sounds.sh: $name grew ($src_size -> $out_size bytes)," \
             "expected encoding to shrink it -- is $src already ADPCM? aborting" >&2
        exit 1
    fi
    mv "$TMP/$name" "$OUT_DIR/$name"
done
