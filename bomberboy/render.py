"""Draws the Bomberboy grid onto a single LVGL canvas.

The model records coordinates it mutates and the renderer adds the few
time-driven bomb cells, then verifies only those cells against a small
per-cell signature. A normal tick therefore examines and redraws a handful
of tiles rather than scanning or repainting all WIDTH*HEIGHT cells.

Tiles that *do* need redrawing are blitted a row at a time straight into
the canvas' pixel buffer rather than pixel by pixel through
lv_canvas_set_px(). set_px() is a Python->C call per pixel that also
invalidates the whole canvas object on every call, so a tile cost
TILE_SIZE*TILE_SIZE (400) of them and a full-board repaint -- every level
start -- cost 66000, which is what made level loads and chain explosions
visibly hitch on the badge. A row-slice blit is one memcpy per sprite row
(20 per tile) into a bytearray we own, plus exactly one canvas
invalidation per rendered frame.

Doing that needs to know how LVGL packs a pixel into that buffer (bytes
per pixel, row stride, channel order), which varies with the build's
color format. Rather than hardcode a guess, _probe_buffer_layout() and
_encode_pixel() below ask LVGL itself: write a known pixel with set_px()
and look at which bytes changed. If those probes come back inconsistent
-- most likely because a port hands lv_canvas_set_buffer() a copy rather
than using our bytearray in place -- the renderer silently falls back to
the original per-pixel path, which is slow but always correct.
"""

import lvgl as lv

import sprites
from model import Bomb, Crate, Gunpowder, Player, PowerUp, Portal, Wall

TILE_SIZE = sprites.TILE_SIZE

# lv.color_hex() builds a color object on every call; sprites only ever use
# a small, fixed palette (a few dozen distinct 0xRRGGBB values total across
# all tiles), so caching by int avoids rebuilding the same color object for
# every one of the (up to) TILE_SIZE*TILE_SIZE repeats of it within a single
# sprite, and across sprites that share background/edge colors.
_color_cache = {}

# Signatures for the tile kinds whose look is fully determined by the kind
# plus one boolean/small int. Most of the board is floor, wall and crate,
# and render() builds a signature for every cell on every frame, so handing
# back one of these shared tuples instead of a fresh one keeps a full-board
# scan allocation-free for those cells (~150 tuples a frame otherwise, i.e.
# ~1500/second of pure GC churn at TICK_MS=100). The dict lookup in
# _sprite_for() and the comparison against the previous frame's signature
# both stay exactly as they were -- these are the same values the inline
# tuples were, just not rebuilt each time.
_WALL_SIGNATURE = ("wall",)
_FLOOR_SIGNATURES = (("floor", False), ("floor", True))
_CRATE_SIGNATURES = (("crate", False), ("crate", True))
_GUNPOWDER_SIGNATURES = (("gunpowder", False), ("gunpowder", True))
_BOMB_SIGNATURES = (("bomb", 0), ("bomb", 1))


def _color(value):
    color = _color_cache.get(value)
    if color is None:
        color = lv.color_hex(value)
        _color_cache[value] = color
    return color


class BoardRenderer:
    def __init__(self, parent, game):
        self.game = game
        width_px = game.width * TILE_SIZE
        height_px = game.height * TILE_SIZE
        self.canvas = lv.canvas(parent)
        self.canvas.set_size(width_px, height_px)
        self._buf = bytearray(width_px * height_px * 4)
        self.canvas.set_buffer(self._buf, width_px, height_px, lv.COLOR_FORMAT.NATIVE)
        # One slot per cell, indexed y * game.width + x. A flat list rather
        # than a dict keyed by (x, y) because that key was another tuple
        # built per cell per frame, for the same reason as the shared
        # signatures above.
        self._last_signature = [None] * (game.width * game.height)
        self._bytes_per_px, self._stride = self._probe_buffer_layout(width_px, height_px)
        self._pixel_bytes = {}
        self._tile_bytes = {}
        if self._stride:
            self._draw_tile = self._blit_tile
        else:
            self._draw_tile = self._set_px_tile

    # --- canvas buffer layout probing -------------------------------------

    def _probe_offset(self, x, y, start, end):
        """Byte offset LVGL writes pixel (x, y) at, or 0 if it can't be found.

        Writes an all-channels-set pixel (white at full opacity is non-zero
        in every color format LVGL has) into an otherwise blank buffer and
        reports where the first changed byte landed, then blanks the search
        window again so the probe leaves no visible mark.
        """
        buf = self._buf
        if end > len(buf):
            end = len(buf)
        if start >= end:
            return 0
        self.canvas.set_px(x, y, _color(0xFFFFFF), lv.OPA.COVER)
        offset = 0
        for index in range(start, end):
            if buf[index]:
                offset = index
                break
        buf[start:end] = bytes(end - start)
        return offset

    def _probe_buffer_layout(self, width_px, height_px):
        """Discover (bytes per pixel, row stride) for the canvas buffer.

        Both are read back from LVGL rather than assumed: pixel (1, 0)
        starts one pixel in, and pixel (0, 1) starts one row in. Returns
        (0, 0) when the numbers don't add up, which switches the renderer
        to the per-pixel fallback.
        """
        if width_px < 2 or height_px < 2:
            return 0, 0
        # The buffer is freshly allocated, so it is still all zeros here and
        # both probes start from a known-blank window.
        bytes_per_px = self._probe_offset(1, 0, 1, 65)
        if not bytes_per_px:
            return 0, 0
        row_bytes = bytes_per_px * width_px
        stride = self._probe_offset(0, 1, row_bytes, row_bytes + 257)
        if not stride:
            return 0, 0
        # A stride that would run the bottom row off the end of the buffer
        # means the layout isn't what these two probes suggest; blitting on
        # that basis would corrupt memory, so don't.
        if (height_px - 1) * stride + row_bytes > len(self._buf):
            return 0, 0
        return bytes_per_px, stride

    def _encode_pixel(self, value):
        """The raw canvas bytes for one 0xRRGGBB sprite pixel.

        Asks LVGL to encode the color by setting it on a scratch pixel and
        copying back what it wrote, so channel order and bit depth come from
        the build rather than from an assumption here. Pixel (0, 0) is the
        scratch space and its previous contents are restored, so this stays
        safe to call mid-render.
        """
        raw = self._pixel_bytes.get(value)
        if raw is None:
            buf = self._buf
            bytes_per_px = self._bytes_per_px
            saved = bytes(buf[0:bytes_per_px])
            self.canvas.set_px(0, 0, _color(value), lv.OPA.COVER)
            raw = bytes(buf[0:bytes_per_px])
            buf[0:bytes_per_px] = saved
            self._pixel_bytes[value] = raw
        return raw

    def _tile_pixels(self, pixel_grid):
        """A sprite's TILE_SIZE rows pre-encoded as canvas bytes.

        One contiguous blob of encoded pixels, handed back as a list of
        per-row views into it so a blit is a straight slice copy that
        allocates nothing at all per frame.

        Sprite grids come from sprites.py's memoized builders, so the same
        grid object comes back for the same tile look for the lifetime of
        the app and this encoding is done once per distinct sprite (about
        two dozen of them, ~1.6KB each at 4 bytes per pixel). The cache
        holds the grid itself alongside the rows: that keeps the object
        (and therefore its id()) alive, so the id() key can't be reused by
        a later object.
        """
        cached = self._tile_bytes.get(id(pixel_grid))
        if cached is not None and cached[0] is pixel_grid:
            return cached[1]
        encode = self._encode_pixel
        blob = bytearray()
        for row in pixel_grid:
            for value in row:
                blob += encode(value)
        pixels = memoryview(bytes(blob))
        row_bytes = TILE_SIZE * self._bytes_per_px
        rows = [pixels[i:i + row_bytes] for i in range(0, len(pixels), row_bytes)]
        self._tile_bytes[id(pixel_grid)] = (pixel_grid, rows)
        return rows

    # --- tile drawing ------------------------------------------------------

    def _blit_tile(self, x, y, pixel_grid):
        buf = self._buf
        stride = self._stride
        row_bytes = TILE_SIZE * self._bytes_per_px
        offset = y * TILE_SIZE * stride + x * row_bytes
        for row in self._tile_pixels(pixel_grid):
            buf[offset:offset + row_bytes] = row
            offset += stride

    def _set_px_tile(self, x, y, pixel_grid):
        ox, oy = x * TILE_SIZE, y * TILE_SIZE
        set_px = self.canvas.set_px
        opa_cover = lv.OPA.COVER
        for py in range(TILE_SIZE):
            row = pixel_grid[py]
            row_y = oy + py
            for px in range(TILE_SIZE):
                set_px(ox + px, row_y, _color(row[px]), opa_cover)

    # --- frame -------------------------------------------------------------

    def _tile_signature(self, x, y):
        tile = self.game.tile_at(x, y)
        burning = self.game.is_burning(x, y)
        if isinstance(tile, Player):
            # is_burning()/burning above only tracks *tile* burn entries --
            # Game._hit_player() records an on-fire player as its own
            # separate "player"-kind entry in _burning, never added to the
            # position set (see model.py), so a player standing on their
            # own tile never shows up as "burning" through that path. Use
            # the player's own on_fire flag directly instead, or a player
            # who's on fire (unable to move or place a bomb for about a
            # second, per model.BOMB_BURN_MS) renders identically to one
            # who isn't -- no visual cue at all for why input stopped
            # working.
            return ("player", tile.player_id, tile.facing, tile.is_dead, tile.on_fire)
        if isinstance(tile, Bomb):
            return _BOMB_SIGNATURES[tile.blink_phase(self.game.now())]
        if isinstance(tile, Crate):
            return _CRATE_SIGNATURES[burning]
        if isinstance(tile, Gunpowder):
            return _GUNPOWDER_SIGNATURES[burning]
        if isinstance(tile, PowerUp):
            return ("powerup", tile.kind, tile.revealed, burning)
        if isinstance(tile, Portal):
            return ("portal", tile.portal_id)
        if isinstance(tile, Wall):
            return _WALL_SIGNATURE
        return _FLOOR_SIGNATURES[burning]

    def _sprite_for(self, signature):
        kind = signature[0]
        if kind == "floor":
            return sprites.explosion_sprite() if signature[1] else sprites.floor_sprite()
        if kind == "wall":
            return sprites.wall_sprite()
        if kind == "crate":
            return sprites.explosion_sprite() if signature[1] else sprites.crate_sprite()
        if kind == "gunpowder":
            return sprites.explosion_sprite() if signature[1] else sprites.gunpowder_sprite()
        if kind == "bomb":
            return sprites.bomb_flash_sprite() if signature[1] else sprites.bomb_sprite()
        if kind == "portal":
            return sprites.portal_sprite(signature[1] // 2)
        if kind == "powerup":
            _, power_kind, revealed, burning = signature
            if burning and not revealed:
                return sprites.explosion_sprite()
            if revealed:
                return sprites.powerup_sprite(power_kind)
            return sprites.crate_sprite()
        if kind == "player":
            _, player_id, facing, dead, on_fire = signature
            if on_fire and not dead:
                return sprites.explosion_sprite()
            return sprites.player_sprite(player_id, facing, dead=dead)
        return sprites.floor_sprite()

    def render(self, force=False):
        game = self.game
        width = game.width
        last_signature = self._last_signature
        tile_signature = self._tile_signature
        sprite_for = self._sprite_for
        draw_tile = self._draw_tile
        drawn = False
        dirty = game.consume_dirty_tiles()
        if force:
            dirty = (
                (x, y)
                for y in range(game.height)
                for x in range(width)
            )
        else:
            # Bomb appearance changes with the clock even when the model does
            # not mutate, so those few cells remain time-driven. Every other
            # visual transition marks itself dirty in Game.
            dirty.update((bomb.x, bomb.y) for bomb in game.bombs)
        for x, y in dirty:
            signature = tile_signature(x, y)
            index = y * width + x
            if not force and last_signature[index] == signature:
                continue
            last_signature[index] = signature
            draw_tile(x, y, sprite_for(signature))
            drawn = True
        if drawn:
            # _blit_tile() writes the buffer behind LVGL's back, so nothing
            # has told it the canvas changed; set_px() would have done this
            # itself (once per pixel, which is part of what made it slow).
            self.canvas.invalidate()
