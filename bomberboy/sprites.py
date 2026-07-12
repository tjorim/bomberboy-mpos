"""Pixel-art sprites for Bomberboy tiles, TILE_SIZE x TILE_SIZE each.

Pure Python (no lv/mpos import) so it stays testable without LVGL. Most
tiles reuse the real 2019 pixel art from tjorim/bomberboy-gba's
Bomberboy port (decoded into original_sprites.py -- see
scripts/convert_gba_sprites.py), nearest-neighbor upscaled from their
native 8x8/8x16 GBA resolution to TILE_SIZE. Floor and the explosion
overlay have no equivalent in that source (that port never got around to
converting them), so they're small procedural sprites instead.

Every sprite function returns a row-major list of TILE_SIZE lists of
TILE_SIZE 0xRRGGBB ints; every gameplay tile fully covers its cell, so
there's no per-pixel transparency to track past this point.
"""

import original_sprites as og

TILE_SIZE = 20

FLOOR_BG = 0x2E7D32
FLOOR_EDGE = 0x388E3C
FIRE_A = 0xFF7043
FIRE_B = 0xFFCA28
FIRE_CORE = 0xFFFFFF

_POWERUP_ART = {
    0: og.ITEM_BOMB,  # EXTRA_BOMB
    1: og.ITEM_FLAME,  # MORE_FLAME
    2: og.ITEM_GOLDENFLAME,  # GOLDEN_FLAME
    3: og.ITEM_LIFE,  # EXTRA_LIFE
    4: og.ITEM_SHIFTER,  # SHIFTER
    5: og.ITEM_SPEEDUP,  # SPEED_UP
    6: og.ITEM_KICKER,  # KICKER
}

_PLAYER_ART = {
    (1, "up"): og.BLAUW_BOVEN,
    (1, "down"): og.BLAUW_ONDER,
    (1, "left"): og.BLAUW_LINKS,
    (1, "right"): og.BLAUW_RECHTS,
    (1, "dead"): og.BLAUW_DOOD,
    (2, "up"): og.ROOD_BOVEN,
    (2, "down"): og.ROOD_ONDER,
    (2, "left"): og.ROOD_LINKS,
    (2, "right"): og.ROOD_RECHTS,
    (2, "dead"): og.ROOD_DOOD,
}

_PORTAL_ART = {0: og.PORTAAL_1, 1: og.PORTAAL_2}


def _memoize(fn):
    """Cache a sprite function's pixel grid by its call arguments.

    Every sprite function here is pure -- same arguments always produce the
    same TILE_SIZE x TILE_SIZE grid -- but without this, render.py's
    per-frame, per-tile calls were rebuilding that grid pixel-by-pixel from
    scratch every time (including the whole board on first render), which is
    the main source of slow level loads and mid-game stutter during
    multi-tile redraws (chain explosions, gunpowder ignition). Callers only
    ever read the returned grid, never mutate it, so sharing the cached
    object across calls is safe.
    """
    cache = {}

    def wrapper(*args, **kwargs):
        key = (args, tuple(sorted(kwargs.items()))) if kwargs else args
        cached = cache.get(key)
        if cached is None:
            cached = fn(*args, **kwargs)
            cache[key] = cached
        return cached

    return wrapper


def _grid(bg):
    return [[bg for _x in range(TILE_SIZE)] for _y in range(TILE_SIZE)]


def _circle(grid, cx, cy, r, color):
    r2 = r * r
    for y in range(TILE_SIZE):
        for x in range(TILE_SIZE):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                grid[y][x] = color


def _upscale(art, bg=FLOOR_BG):
    """Nearest-neighbor scale a (width, height, flat_pixels) sprite from
    original_sprites.py up to TILE_SIZE x TILE_SIZE, filling transparent
    (None) pixels with bg."""
    width, height, pixels = art
    grid = _grid(bg)
    for y in range(TILE_SIZE):
        sy = min(height - 1, y * height // TILE_SIZE)
        row_offset = sy * width
        for x in range(TILE_SIZE):
            sx = min(width - 1, x * width // TILE_SIZE)
            value = pixels[row_offset + sx]
            if value is not None:
                grid[y][x] = value
    return grid


@_memoize
def floor_sprite():
    g = _grid(FLOOR_BG)
    for x in range(TILE_SIZE):
        g[0][x] = FLOOR_EDGE
        g[x][0] = FLOOR_EDGE
    return g


@_memoize
def explosion_sprite():
    g = _grid(FIRE_A)
    _circle(g, 10, 10, 9, FIRE_B)
    _circle(g, 10, 10, 4, FIRE_CORE)
    return g


@_memoize
def wall_sprite():
    return _upscale(og.MUUR)


@_memoize
def crate_sprite():
    return _upscale(og.KRAT)


@_memoize
def gunpowder_sprite():
    return _upscale(og.KRUIT, bg=FLOOR_BG)


@_memoize
def bomb_sprite():
    return _upscale(og.BOM, bg=FLOOR_BG)


def _tint(grid, color, strength):
    """Blend every pixel in `grid` toward `color` by `strength` (0-1)."""
    cr, cg, cb = (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF
    tinted = []
    for row in grid:
        new_row = []
        for px in row:
            r, g, b = (px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF
            r += int((cr - r) * strength)
            g += int((cg - g) * strength)
            b += int((cb - b) * strength)
            new_row.append((r << 16) | (g << 8) | b)
        tinted.append(new_row)
    return tinted


@_memoize
def bomb_flash_sprite():
    # No dedicated "about to explode" art exists in the decoded GBA set
    # (og.BOM is the only bomb sprite), so this reuses the real bomb's
    # silhouette, just brightened -- render.py blinks between this and
    # bomb_sprite() as a bomb's fuse runs down, same idea as the original
    # explosion_sprite() being procedural rather than hand-drawn.
    return _tint(bomb_sprite(), 0xFFFFFF, 0.6)


@_memoize
def portal_sprite(pair_index=0):
    # Color identifies which linked PAIR a portal belongs to, not which
    # end of that pair it is -- both ends of one pair look identical, a
    # different pair gets a different look (same fix applied upstream in
    # tjorim/bomberboy-java#3, where the equivalent Java code had briefly done
    # this backwards too).
    return _upscale(_PORTAL_ART.get(pair_index % 2, og.PORTAAL_1), bg=FLOOR_BG)


@_memoize
def powerup_sprite(kind):
    return _upscale(_POWERUP_ART.get(kind, og.ITEM_BOMB), bg=FLOOR_BG)


@_memoize
def player_sprite(player_id, facing="down", dead=False):
    key = (player_id, "dead") if dead else (player_id, facing)
    return _upscale(_PLAYER_ART.get(key, og.BLAUW_ONDER), bg=FLOOR_BG)
