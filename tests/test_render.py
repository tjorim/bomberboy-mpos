"""Tests for render.py's canvas blitting.

render.py is the one module that imports lvgl at module level, so these
tests install a stand-in `lvgl` in sys.modules first. The stand-in models
the parts the renderer actually leans on -- lv_canvas_set_px() writing one
packed pixel into the buffer handed to lv_canvas_set_buffer() -- in a few
different color formats, since the renderer's whole fast path rests on
discovering that layout at runtime rather than assuming one.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bomberboy"))


class FakeColor:
    def __init__(self, value):
        self.value = value


def _make_fake_lvgl():
    module = types.ModuleType("lvgl")
    module.OPA = types.SimpleNamespace(COVER=255)
    module.COLOR_FORMAT = types.SimpleNamespace(NATIVE="native")
    module.color_hex = FakeColor
    module.canvas = None  # set per test
    return module


_fake_lv = _make_fake_lvgl()
sys.modules.setdefault("lvgl", _fake_lv)

import render  # noqa: E402
import sprites  # noqa: E402
from levels import LEVELS  # noqa: E402
from model import Bomb, Floor, Game  # noqa: E402


class FakeCanvas:
    """Shared behaviour of the canvas stand-ins below.

    Subclasses vary bytes per pixel, packing order, row padding and whether
    lv_canvas_set_buffer() keeps the caller's buffer or a copy of it.
    """

    bytes_per_px = 4
    row_padding = 0
    shares_buffer = True

    def __init__(self, parent=None):
        self.parent = parent
        self.buf = None
        self.width = 0
        self.height = 0
        self.set_px_calls = 0
        self.invalidate_calls = 0

    def set_size(self, width, height):
        self.width, self.height = width, height

    def set_buffer(self, buf, width, height, color_format):
        self.buf = buf if self.shares_buffer else bytearray(len(buf))
        self.width, self.height = width, height

    @property
    def stride(self):
        return self.width * self.bytes_per_px + self.row_padding

    def encode(self, value):
        raise NotImplementedError

    def set_px(self, x, y, color, opa):
        self.set_px_calls += 1
        offset = y * self.stride + x * self.bytes_per_px
        self.buf[offset:offset + self.bytes_per_px] = self.encode(color.value)

    def invalidate(self):
        self.invalidate_calls += 1

    def align(self, *args):
        pass


class Xrgb8888Canvas(FakeCanvas):
    """LVGL's 32-bit native format: little-endian B, G, R, A."""

    def encode(self, value):
        return bytes(((value >> 0) & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF, 0xFF))


class Rgb565Canvas(FakeCanvas):
    bytes_per_px = 2

    def encode(self, value):
        packed = (
            ((value >> 19) & 0x1F) << 11
            | ((value >> 10) & 0x3F) << 5
            | ((value >> 3) & 0x1F)
        )
        return bytes((packed & 0xFF, packed >> 8))


class PaddedRgb565Canvas(Rgb565Canvas):
    """Same, but with rows aligned up -- stride != width * bytes per pixel."""

    row_padding = 12


class CopyingCanvas(Xrgb8888Canvas):
    """A port that copies rather than adopting the caller's buffer.

    Writing straight into our bytearray would draw nothing at all on a
    build like this, so the renderer has to notice and stay on set_px().
    """

    shares_buffer = False


def _renderer(canvas_class, seed=7):
    render.lv.canvas = canvas_class
    game = Game(LEVELS[0](), seed=seed)
    return game, render.BoardRenderer(None, game)


def _expected_buffer(game, canvas, renderer):
    """The board painted independently of the code under test."""
    expected = bytearray(len(renderer._buf))
    for y in range(game.height):
        for x in range(game.width):
            grid = renderer._sprite_for(renderer._tile_signature(x, y))
            for py in range(sprites.TILE_SIZE):
                row = grid[py]
                offset = (y * sprites.TILE_SIZE + py) * canvas.stride
                offset += x * sprites.TILE_SIZE * canvas.bytes_per_px
                for value in row:
                    expected[offset:offset + canvas.bytes_per_px] = canvas.encode(value)
                    offset += canvas.bytes_per_px
    return expected


class BufferLayoutProbeTests(unittest.TestCase):
    def test_probe_finds_the_layout_of_each_color_format(self):
        for canvas_class in (Xrgb8888Canvas, Rgb565Canvas, PaddedRgb565Canvas):
            with self.subTest(canvas=canvas_class.__name__):
                _game, renderer = _renderer(canvas_class)
                canvas = renderer.canvas
                self.assertEqual(renderer._bytes_per_px, canvas_class.bytes_per_px)
                self.assertEqual(renderer._stride, canvas.stride)

    def test_probing_leaves_the_buffer_blank(self):
        _game, renderer = _renderer(Xrgb8888Canvas)
        self.assertEqual(bytes(renderer._buf), bytes(len(renderer._buf)))

    def test_a_copying_port_falls_back_to_set_px(self):
        _game, renderer = _renderer(CopyingCanvas)
        self.assertEqual(renderer._stride, 0)
        self.assertEqual(renderer._draw_tile, renderer._set_px_tile)


class BlitRenderTests(unittest.TestCase):
    def test_blitted_board_matches_a_pixel_by_pixel_paint(self):
        for canvas_class in (Xrgb8888Canvas, Rgb565Canvas, PaddedRgb565Canvas):
            with self.subTest(canvas=canvas_class.__name__):
                game, renderer = _renderer(canvas_class)
                expected = _expected_buffer(game, renderer.canvas, renderer)
                renderer.render(force=True)
                self.assertEqual(bytes(renderer._buf), bytes(expected))

    def test_full_board_costs_no_set_px_calls_beyond_probing(self):
        _game, renderer = _renderer(Xrgb8888Canvas)
        renderer.canvas.set_px_calls = 0
        renderer.render(force=True)
        # Only the one-off palette encoding, which is a couple of dozen
        # colors for the whole game, not the 66000 pixels of the board.
        self.assertLess(renderer.canvas.set_px_calls, 200)
        self.assertEqual(renderer.canvas.set_px_calls, len(renderer._pixel_bytes))

    def test_one_invalidate_per_rendered_frame(self):
        _game, renderer = _renderer(Xrgb8888Canvas)
        renderer.canvas.invalidate_calls = 0
        renderer.render(force=True)
        self.assertEqual(renderer.canvas.invalidate_calls, 1)

    def test_an_unchanged_board_redraws_nothing(self):
        _game, renderer = _renderer(Xrgb8888Canvas)
        renderer.render(force=True)
        painted = bytes(renderer._buf)
        renderer.canvas.invalidate_calls = 0
        signature_calls = [0]
        original = renderer._tile_signature

        def counted(x, y):
            signature_calls[0] += 1
            return original(x, y)

        renderer._tile_signature = counted
        renderer.render()
        self.assertEqual(signature_calls[0], 0)
        self.assertEqual(renderer.canvas.invalidate_calls, 0)
        self.assertEqual(bytes(renderer._buf), painted)

    def test_only_a_model_dirty_cell_is_rescanned(self):
        game, renderer = _renderer(Xrgb8888Canvas)
        renderer.render(force=True)
        signature_calls = []
        original = renderer._tile_signature

        def counted(x, y):
            signature_calls.append((x, y))
            return original(x, y)

        renderer._tile_signature = counted
        game.set_tile(2, 2, Floor())
        renderer.render()

        self.assertEqual(signature_calls, [(2, 2)])

    def test_live_bomb_is_rechecked_when_its_blink_phase_changes(self):
        now = [0]
        game = Game(LEVELS[0](), seed=7, clock=lambda: now[0])
        render.lv.canvas = Xrgb8888Canvas
        renderer = render.BoardRenderer(None, game)
        owner = game.players[0]
        bomb = Bomb(owner, 2, 2, Floor(), placed_at=0)
        game.set_tile(2, 2, bomb)
        game.bombs.append(bomb)
        renderer.render(force=True)
        initial_signature = renderer._last_signature[2 * game.width + 2]
        renderer.canvas.invalidate_calls = 0

        now[0] = 1000
        renderer.render()

        self.assertNotEqual(renderer._last_signature[2 * game.width + 2], initial_signature)
        self.assertEqual(renderer.canvas.invalidate_calls, 1)

    def test_moving_a_player_repaints_both_tiles(self):
        game, renderer = _renderer(Xrgb8888Canvas)
        renderer.render(force=True)
        player = game.players[0]
        start = (player.x, player.y)
        for direction in ("right", "down", "left", "up"):
            if game.move_player(player, direction):
                break
        else:
            self.skipTest("player is boxed in on this level seed")
        self.assertNotEqual((player.x, player.y), start)
        renderer.render()
        self.assertEqual(bytes(renderer._buf), bytes(_expected_buffer(game, renderer.canvas, renderer)))

    def test_fallback_path_paints_the_same_board(self):
        game, renderer = _renderer(CopyingCanvas)
        expected = _expected_buffer(game, renderer.canvas, renderer)
        renderer.render(force=True)
        self.assertEqual(bytes(renderer.canvas.buf), bytes(expected))


class SpriteEncodingCacheTests(unittest.TestCase):
    def test_each_sprite_is_encoded_once(self):
        _game, renderer = _renderer(Xrgb8888Canvas)
        renderer.render(force=True)
        encoded = len(renderer._tile_bytes)
        renderer.render(force=True)
        self.assertEqual(len(renderer._tile_bytes), encoded)
        self.assertIs(
            renderer._tile_pixels(sprites.wall_sprite()),
            renderer._tile_pixels(sprites.wall_sprite()),
        )

    def test_static_tile_signatures_are_not_rebuilt_per_frame(self):
        game, renderer = _renderer(Xrgb8888Canvas)
        walls = [
            (x, y)
            for y in range(game.height)
            for x in range(game.width)
            if renderer._tile_signature(x, y)[0] == "wall"
        ]
        self.assertTrue(walls)
        x, y = walls[0]
        self.assertIs(renderer._tile_signature(x, y), renderer._tile_signature(x, y))


if __name__ == "__main__":
    unittest.main()
