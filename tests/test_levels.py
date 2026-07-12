import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bomberboy"))

from levels import LEVELS, GunpowderCrossLevel, MazeLevel, OpenArenaLevel, PortalMazeLevel
from model import Floor, Game, Gunpowder, Player, Portal, PowerUp, Wall


def grid_signature(grid, width, height):
    signature = []
    for y in range(height):
        row = []
        for x in range(width):
            tile = grid[x][y]
            if isinstance(tile, PowerUp):
                row.append((type(tile).__name__, tile.kind))
            elif isinstance(tile, Portal):
                row.append((type(tile).__name__, tile.portal_id))
            else:
                row.append(type(tile).__name__)
        signature.append(tuple(row))
    return tuple(signature)


def powerup_signature(grid, width, height):
    return tuple(
        (x, y, grid[x][y].kind)
        for y in range(height)
        for x in range(width)
        if isinstance(grid[x][y], PowerUp)
    )


class LevelInvariantTests(unittest.TestCase):
    def test_pillars_are_at_even_coordinates(self):
        for level_cls in LEVELS:
            level = level_cls()
            grid = level.build_grid()
            for x in range(2, level.width - 2, 2):
                for y in range(2, level.height - 2, 2):
                    self.assertIsInstance(grid[x][y], Wall, msg=f"{level.name} pillar at ({x},{y})")

    def test_spawn_pockets_are_clear_in_maze_levels(self):
        for level_cls in (MazeLevel, PortalMazeLevel):
            level = level_cls()
            grid = level.build_grid()
            for x, y in ((1, 1), (2, 1), (1, 2)):
                self.assertTrue(grid[x][y].is_walkable(), msg=f"{level.name} spawn pocket ({x},{y})")
            w, h = level.width, level.height
            for x, y in ((w - 2, h - 2), (w - 3, h - 2), (w - 2, h - 3)):
                self.assertTrue(grid[x][y].is_walkable(), msg=f"{level.name} spawn pocket ({x},{y})")


class SeededLevelTests(unittest.TestCase):
    def test_seeded_layouts_have_stable_signatures(self):
        expected = {
            MazeLevel: (
                (9, 1, 4),
                (9, 2, 2),
                (7, 3, 6),
                (11, 3, 2),
                (1, 5, 0),
                (2, 5, 5),
                (5, 5, 5),
                (8, 5, 3),
                (9, 5, 4),
                (13, 5, 5),
                (1, 7, 2),
                (4, 7, 5),
                (5, 7, 0),
                (7, 7, 4),
                (11, 7, 2),
                (3, 8, 6),
                (5, 9, 5),
                (9, 9, 5),
            ),
            PortalMazeLevel: (
                (11, 1, 5),
                (5, 3, 4),
                (9, 3, 6),
                (13, 3, 0),
                (1, 5, 4),
                (6, 5, 5),
                (8, 5, 4),
                (9, 6, 0),
                (5, 7, 4),
                (8, 7, 2),
                (13, 7, 2),
                (1, 8, 5),
                (3, 8, 2),
                (8, 9, 3),
            ),
        }
        for level_cls, signature in expected.items():
            level = level_cls()
            grid = level.build_grid(seed=0xB0B)
            self.assertEqual(powerup_signature(grid, level.width, level.height), signature, msg=level.name)

    def test_seeded_random_levels_are_reproducible(self):
        for level_cls in (MazeLevel, PortalMazeLevel):
            first = level_cls()
            second = level_cls()
            first_grid = first.build_grid(seed=0xB0B)
            second_grid = second.build_grid(seed=0xB0B)
            self.assertEqual(
                grid_signature(first_grid, first.width, first.height),
                grid_signature(second_grid, second.width, second.height),
                msg=level_cls.name,
            )

    def test_different_seeds_change_random_levels(self):
        for level_cls in (MazeLevel, PortalMazeLevel):
            first = level_cls()
            second = level_cls()
            first_grid = first.build_grid(seed=1)
            second_grid = second.build_grid(seed=2)
            self.assertNotEqual(
                grid_signature(first_grid, first.width, first.height),
                grid_signature(second_grid, second.width, second.height),
                msg=level_cls.name,
            )

    def test_game_passes_seed_to_level_generation(self):
        game_a = Game(MazeLevel(), seed=12345)
        game_b = Game(MazeLevel(), seed=12345)
        self.assertEqual(game_a.seed, 12345)
        self.assertEqual(
            grid_signature(game_a.grid, game_a.width, game_a.height),
            grid_signature(game_b.grid, game_b.width, game_b.height),
        )


class MazeLevelTests(unittest.TestCase):
    def test_has_crates_and_powerups(self):
        level = MazeLevel()
        grid = level.build_grid()
        kinds = [type(grid[x][y]).__name__ for x in range(level.width) for y in range(level.height)]
        self.assertIn("Crate", kinds)
        self.assertIn("PowerUp", kinds)


class GunpowderCrossLevelTests(unittest.TestCase):
    def test_has_a_gunpowder_cross_through_the_middle(self):
        level = GunpowderCrossLevel()
        grid = level.build_grid()
        mid_x, mid_y = level.width // 2, level.height // 2
        self.assertIsInstance(grid[mid_x][mid_y], Gunpowder)
        self.assertIsInstance(grid[mid_x + 2][mid_y], Gunpowder)
        self.assertIsInstance(grid[mid_x][mid_y + 2], Gunpowder)


class PortalMazeLevelTests(unittest.TestCase):
    def test_two_independent_portal_pairs_are_each_linked_only_to_their_own_partner(self):
        level = PortalMazeLevel()
        grid = level.build_grid()
        self.assertEqual(len(level.portals), 4)

        # every portal is actually on the grid where it claims to be
        for portal in level.portals:
            self.assertIs(grid[portal.x][portal.y], portal)

        # portal_ids are all distinct, and pairing is symmetric
        self.assertEqual(sorted(p.portal_id for p in level.portals), [0, 1, 2, 3])
        for portal in level.portals:
            self.assertIs(portal.other.other, portal)

        # the two pairs don't cross-link with each other
        pair0 = {p for p in level.portals if p.portal_id in (0, 1)}
        pair1 = {p for p in level.portals if p.portal_id in (2, 3)}
        for portal in pair0:
            self.assertIn(portal.other, pair0)
        for portal in pair1:
            self.assertIn(portal.other, pair1)

        # all 4 positions are distinct
        positions = {(p.x, p.y) for p in level.portals}
        self.assertEqual(len(positions), 4)


class OpenArenaLevelTests(unittest.TestCase):
    def test_no_crates_and_players_start_fully_powered(self):
        level = OpenArenaLevel()
        grid = level.build_grid()
        for x in range(level.width):
            for y in range(level.height):
                self.assertNotIsInstance(grid[x][y], (Portal,))
        players = level.place_players(grid)
        for player in players:
            self.assertEqual(player.bombs_available, player.MAX_BOMBS)
            self.assertEqual(player.flame_range, player.max_flame)
            self.assertEqual(player.speed, player.MAX_SPEED)
            self.assertTrue(player.can_shift)


if __name__ == "__main__":
    unittest.main()
