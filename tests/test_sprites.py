import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bomberboy"))

import sprites


class SpriteCachingTests(unittest.TestCase):
    def test_repeated_calls_return_the_same_cached_grid(self):
        first = sprites.wall_sprite()
        second = sprites.wall_sprite()
        self.assertIs(first, second)

    def test_distinct_arguments_are_cached_separately(self):
        pair0 = sprites.portal_sprite(0)
        pair1 = sprites.portal_sprite(1)
        self.assertIsNot(pair0, pair1)
        self.assertEqual(pair0, sprites.portal_sprite(0))
        self.assertEqual(pair1, sprites.portal_sprite(1))

    def test_player_sprite_caches_by_positional_and_keyword_args(self):
        facing = sprites.player_sprite(1, "up", dead=False)
        dead = sprites.player_sprite(1, "up", dead=True)
        self.assertIsNot(facing, dead)
        self.assertIs(facing, sprites.player_sprite(1, "up", dead=False))
        self.assertIs(dead, sprites.player_sprite(1, "up", dead=True))

    def test_cached_grid_has_the_expected_shape(self):
        grid = sprites.crate_sprite()
        self.assertEqual(len(grid), sprites.TILE_SIZE)
        self.assertTrue(all(len(row) == sprites.TILE_SIZE for row in grid))


if __name__ == "__main__":
    unittest.main()
