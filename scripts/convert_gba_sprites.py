"""Emit a compact original_sprites.py module from the pixel art in
github.com/tjorim/bomberboy-gba's bomberboy/sprites/ directory (grit
.h exports, 8x8/8x16 tiles, one shared 8bpp palette), at native resolution.
Transparent (palette index 0) pixels become None.

(That repo was renamed from gba-sprite-engine to bomberboy-gba -- it's a
general sprite engine with several unrelated demos, but Bomberboy was the
only one of its apps this project ever needed anything from.)

Usage:
    python convert_gba_sprites.py <path-to-bomberboy-gba-checkout>

Regenerates bomberboy/original_sprites.py in this repo.
"""

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_PATH = REPO_ROOT / "bomberboy" / "original_sprites.py"

# name in .h file -> constant name to emit
WANTED = {
    "muur": "MUUR",
    "krat": "KRAT",
    "kruit": "KRUIT",
    "bom": "BOM",
    "portaal_1": "PORTAAL_1",
    "portaal_2": "PORTAAL_2",
    "item_bomb": "ITEM_BOMB",
    "item_flame": "ITEM_FLAME",
    "item_goldenflame": "ITEM_GOLDENFLAME",
    "item_life": "ITEM_LIFE",
    "item_shifter": "ITEM_SHIFTER",
    "item_speedup": "ITEM_SPEEDUP",
    "item_kicker": "ITEM_KICKER",
    "blauw_onder": "BLAUW_ONDER",
    "blauw_boven": "BLAUW_BOVEN",
    "blauw_links": "BLAUW_LINKS",
    "blauw_rechts": "BLAUW_RECHTS",
    "blauw_dood": "BLAUW_DOOD",
    "rood_onder": "ROOD_ONDER",
    "rood_boven": "ROOD_BOVEN",
    "rood_links": "ROOD_LINKS",
    "rood_rechts": "ROOD_RECHTS",
    "rood_dood": "ROOD_DOOD",
}


def parse_array(text: str, name: str) -> list[int]:
    m = re.search(name + r"\[\d+\][^=]*=\s*\{(.*?)\};", text, re.S)
    body = m.group(1)
    return [int(n, 16) for n in re.findall(r"0x[0-9A-Fa-f]+", body)]


def gba_color_to_rgb888(c: int) -> int:
    r5, g5, b5 = c & 0x1F, (c >> 5) & 0x1F, (c >> 10) & 0x1F
    expand = lambda v: (v << 3) | (v >> 2)
    return (expand(r5) << 16) | (expand(g5) << 8) | expand(b5)


def unpack_tile_words(words: list[int]) -> list[int]:
    pixels = []
    for w in words:
        for shift in (0, 8, 16, 24):
            pixels.append((w >> shift) & 0xFF)
    return pixels


def decode(path: Path, palette: list[int]) -> tuple[int, int, list[int | None]]:
    with open(path) as f:
        text = f.read()
    dims = re.search(r"//\s*(\w+),\s*(\d+)x(\d+)@8", text)
    name, w, h = dims.group(1), int(dims.group(2)), int(dims.group(3))
    words = parse_array(text, name + "Tiles")
    tiles_x, tiles_y = w // 8, h // 8
    flat = [None] * (w * h)
    for t in range(tiles_x * tiles_y):
        tile_words = words[t * 16:(t + 1) * 16]
        indices = unpack_tile_words(tile_words)
        tile_col, tile_row = t % tiles_x, t // tiles_x
        ox, oy = tile_col * 8, tile_row * 8
        for i, idx in enumerate(indices):
            px, py = i % 8, i // 8
            if idx == 0:
                continue
            flat[(oy + py) * w + (ox + px)] = palette[idx] if idx < len(palette) else 0xFF00FF
    return w, h, flat


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bomberboy_gba_checkout", type=Path, help="Path to a clone of tjorim/bomberboy-gba")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args()

    src_dir = args.bomberboy_gba_checkout / "bomberboy" / "sprites"
    with open(src_dir / "shared.h") as f:
        raw = parse_array(f.read(), "sharedPal")
    palette = [gba_color_to_rgb888(c) for c in raw]

    lines = [
        '"""Original pixel art, decoded from the bomberboy-gba Bomberboy',
        'port (github.com/tjorim/bomberboy-gba) at its native 8x8/8x16',
        "GBA tile resolution. Generated -- see scripts/convert_gba_sprites.py",
        'for the decoder. Each constant is (width, height, flat_pixels) where',
        "flat_pixels is a row-major list of 0xRRGGBB ints, or None for a",
        'transparent pixel."""',
        "",
    ]
    for src_name, const_name in WANTED.items():
        w, h, flat = decode(src_dir / (src_name + ".h"), palette)
        pixel_repr = "[" + ",".join("None" if p is None else hex(p) for p in flat) + "]"
        lines.append(f"{const_name} = ({w}, {h}, {pixel_repr})")
    args.out.write_text("\n".join(lines) + "\n")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
