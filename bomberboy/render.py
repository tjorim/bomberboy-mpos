"""Draws the Bomberboy grid onto a single LVGL canvas.

Only tiles whose visual state changed since the last frame are redrawn
(dirty tracking keyed by a small per-cell signature), so a normal tick --
a couple of players moving, a bomb blinking -- costs a handful of tile
redraws rather than repainting all WIDTH*HEIGHT cells.
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
        self._last_signature = {}

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
            return ("bomb", tile.blink_phase(self.game.now()))
        if isinstance(tile, Crate):
            return ("crate", burning)
        if isinstance(tile, Gunpowder):
            return ("gunpowder", burning)
        if isinstance(tile, PowerUp):
            return ("powerup", tile.kind, tile.revealed, burning)
        if isinstance(tile, Portal):
            return ("portal", tile.portal_id)
        if isinstance(tile, Wall):
            return ("wall",)
        return ("floor", burning)

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

    def _draw_tile(self, x, y, pixel_grid):
        ox, oy = x * TILE_SIZE, y * TILE_SIZE
        canvas = self.canvas
        set_px = canvas.set_px
        opa_cover = lv.OPA.COVER
        for py in range(TILE_SIZE):
            row = pixel_grid[py]
            row_y = oy + py
            for px in range(TILE_SIZE):
                set_px(ox + px, row_y, _color(row[px]), opa_cover)

    def render(self, force=False):
        for x in range(self.game.width):
            for y in range(self.game.height):
                signature = self._tile_signature(x, y)
                if not force and self._last_signature.get((x, y)) == signature:
                    continue
                self._last_signature[(x, y)] = signature
                self._draw_tile(x, y, self._sprite_for(signature))
