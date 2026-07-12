import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bomberboy"))

import model
from levels import MazeLevel, GunpowderCrossLevel, OpenArenaLevel, PortalMazeLevel
from model import Crate, Floor, Game, Gunpowder, Portal, PowerUp, Wall, DOWN, LEFT, RIGHT, UP


def fast_timers():
    """Speed up bomb fuse/burn so tests don't need multi-second sleeps."""
    model.BOMB_FUSE_MS = 5
    model.BOMB_BURN_MS = 5


def slow_timers():
    model.BOMB_FUSE_MS = 2000
    model.BOMB_BURN_MS = 1000


def fast_shrink_timers():
    model.ARENA_SHRINK_START_MS = 5
    model.ARENA_SHRINK_STEP_MS = 5


def slow_shrink_timers():
    model.ARENA_SHRINK_START_MS = 120000
    model.ARENA_SHRINK_STEP_MS = 400


def fast_roll_timer():
    model.BOMB_ROLL_STEP_MS = 5


def slow_roll_timer():
    model.BOMB_ROLL_STEP_MS = 120


class MovementTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(OpenArenaLevel())
        self.p1, self.p2 = self.game.players

    def test_walk_onto_open_floor(self):
        x, y = self.p1.x, self.p1.y
        self.assertTrue(self.game.move_player(self.p1, RIGHT))
        self.assertEqual((self.p1.x, self.p1.y), (x + 1, y))
        self.assertIsInstance(self.game.tile_at(x, y), Floor)

    def test_wall_blocks_movement(self):
        # player 1 starts at (1,1); moving UP/LEFT runs into the border wall.
        self.assertFalse(self.game.move_player(self.p1, UP))
        self.assertFalse(self.game.move_player(self.p1, LEFT))
        self.assertEqual((self.p1.x, self.p1.y), (1, 1))

    def test_players_swap_places(self):
        # Bring them adjacent, then swap.
        self.game.set_tile(self.p2.x, self.p2.y, Floor())
        self.p2.x, self.p2.y = self.p1.x + 1, self.p1.y
        self.game.set_tile(self.p2.x, self.p2.y, self.p2)
        self.assertTrue(self.game.move_player(self.p1, RIGHT))
        self.assertEqual((self.p1.x, self.p1.y), (2, 1))
        self.assertEqual((self.p2.x, self.p2.y), (1, 1))


class BombTests(unittest.TestCase):
    def setUp(self):
        fast_timers()
        self.game = Game(MazeLevel())
        self.p1, self.p2 = self.game.players

    def tearDown(self):
        slow_timers()

    def test_bomb_appears_on_grid_and_consumes_charge(self):
        available = self.p1.bombs_available
        self.assertTrue(self.game.place_bomb(self.p1))
        self.assertEqual(self.p1.bombs_available, available - 1)
        self.assertIsInstance(self.game.tile_at(self.p1.x, self.p1.y), model.Bomb)

    def test_cannot_place_bomb_without_charge(self):
        self.p1.bombs_available = 0
        self.assertFalse(self.game.place_bomb(self.p1))

    def test_bomb_explodes_and_returns_tile_and_charge(self):
        x, y = self.p1.x, self.p1.y
        self.game.place_bomb(self.p1)
        time.sleep(0.02)
        self.game.tick()
        self.assertNotIsInstance(self.game.tile_at(x, y), model.Bomb)
        self.assertEqual(self.p1.bombs_available, 1)

    def test_explosion_damages_player_after_burn_delay(self):
        # Move player 2 next to player 1 so the blast reaches them.
        self.p2.x, self.p2.y = self.p1.x + 1, self.p1.y
        self.game.set_tile(self.p2.x, self.p2.y, self.p2)
        lives_before = self.p2.lives
        self.game.place_bomb(self.p1)
        time.sleep(0.02)
        self.game.tick()  # explode: ignites, marks player on fire, no damage yet
        self.assertTrue(self.p2.on_fire)
        self.assertEqual(self.p2.lives, lives_before)
        time.sleep(0.02)
        self.game.tick()  # extinguish: damage applied now
        self.assertFalse(self.p2.on_fire)
        self.assertEqual(self.p2.lives, lives_before - 1)

    def test_explosion_stops_at_wall(self):
        game = Game(MazeLevel())
        p1 = game.players[0]
        # (2,2) is always a pillar wall per the base-grid algorithm.
        self.assertIsInstance(game.tile_at(2, 2), Wall)
        game.place_bomb(p1)
        time.sleep(0.02)
        game.tick()
        self.assertFalse(game.is_burning(2, 2))

    def test_explosion_breaks_one_crate_and_stops(self):
        game = Game(MazeLevel())
        p1 = game.players[0]
        # Place crates directly right of the player and confirm only the
        # first one ignites (crates stop propagation).
        game.set_tile(p1.x + 1, p1.y, Crate())
        game.set_tile(p1.x + 2, p1.y, Crate())
        p1.flame_range = 3
        game.place_bomb(p1)
        time.sleep(0.02)
        game.tick()
        self.assertTrue(game.is_burning(p1.x + 1, p1.y))
        self.assertFalse(game.is_burning(p1.x + 2, p1.y))
        time.sleep(0.02)
        game.tick()
        self.assertIsInstance(game.tile_at(p1.x + 1, p1.y), Floor)
        self.assertIsInstance(game.tile_at(p1.x + 2, p1.y), Crate)

    def test_gunpowder_chain_hits_standing_player_once(self):
        game = Game(OpenArenaLevel())
        p1, p2 = game.players
        # A short gunpowder trail near p1, unrelated to p2's grid position:
        # the chain should still reach p2 purely because they're standing on
        # gunpowder, wherever that is on the board.
        game.set_tile(p1.x + 1, p1.y, Gunpowder())
        game.set_tile(p1.x + 2, p1.y, Gunpowder())
        p2.standing_on = Gunpowder()
        lives_before = p2.lives
        p1.flame_range = 1  # direct blast alone wouldn't reach p2's tile
        game.place_bomb(p1)
        time.sleep(0.02)
        game.tick()
        self.assertTrue(p2.on_fire)
        time.sleep(0.02)
        game.tick()
        self.assertEqual(p2.lives, lives_before - 1)


class ShiftAndKickTests(unittest.TestCase):
    def setUp(self):
        fast_roll_timer()

    def tearDown(self):
        slow_roll_timer()

    @staticmethod
    def _place_bomb(game, x, y, owner, under=None):
        bomb = model.Bomb(owner, x, y, under or Floor())
        game.set_tile(x, y, bomb)
        game.bombs.append(bomb)
        return bomb

    def test_shift_pushes_bomb_one_tile_and_player_follows(self):
        game = Game(OpenArenaLevel())
        p1 = game.players[0]
        p1.can_shift = True
        bomb = self._place_bomb(game, 2, 1, p1)
        self.assertTrue(game.move_player(p1, RIGHT))
        self.assertEqual((p1.x, p1.y), (2, 1))
        self.assertEqual((bomb.x, bomb.y), (3, 1))
        self.assertIsNone(bomb.rolling)
        game.tick()  # a shifted bomb doesn't keep moving on its own
        self.assertEqual((bomb.x, bomb.y), (3, 1))

    def test_kick_sends_bomb_rolling_multiple_tiles_player_stays_put(self):
        game = Game(OpenArenaLevel())
        p1 = game.players[0]
        p1.can_kick = True
        bomb = self._place_bomb(game, 2, 1, p1)
        self.assertTrue(game.move_player(p1, RIGHT))
        self.assertEqual((p1.x, p1.y), (1, 1))  # kicker doesn't follow
        self.assertEqual((bomb.x, bomb.y), (3, 1))  # first step happens immediately
        self.assertEqual(bomb.rolling, (1, 0))
        time.sleep(0.02)
        game.tick()
        self.assertEqual((bomb.x, bomb.y), (4, 1))
        time.sleep(0.02)
        game.tick()
        self.assertEqual((bomb.x, bomb.y), (5, 1))

    def test_kicked_bomb_stops_when_it_hits_a_wall(self):
        game = Game(OpenArenaLevel())
        p1 = game.players[0]
        p1.can_kick = True
        bomb = self._place_bomb(game, 2, 1, p1)
        game.set_tile(4, 1, Wall())
        self.assertTrue(game.move_player(p1, RIGHT))
        self.assertEqual((bomb.x, bomb.y), (3, 1))
        time.sleep(0.02)
        game.tick()
        self.assertEqual((bomb.x, bomb.y), (3, 1))  # blocked by the wall at (4,1)
        self.assertIsNone(bomb.rolling)

    def test_kicked_bomb_stops_before_hitting_a_player(self):
        game = Game(OpenArenaLevel())
        p1, p2 = game.players
        p1.can_kick = True
        bomb = self._place_bomb(game, 2, 1, p1)
        game.set_tile(p2.x, p2.y, Floor())
        p2.x, p2.y = 4, 1
        game.set_tile(p2.x, p2.y, p2)
        self.assertTrue(game.move_player(p1, RIGHT))
        self.assertEqual((bomb.x, bomb.y), (3, 1))
        time.sleep(0.02)
        game.tick()
        self.assertEqual((bomb.x, bomb.y), (3, 1))  # blocked by p2 at (4,1)
        self.assertIsNone(bomb.rolling)

    def test_cannot_kick_a_bomb_out_from_under_the_player_standing_on_it(self):
        # place_bomb() puts the Bomb object in the grid at the owner's own
        # position (not the player) so blast-chaining can find it there --
        # move_player() used to check isinstance(target, Bomb) before ever
        # checking whether a live player (the owner, mid-placement) still
        # occupies that tile, so another player with the kick powerup could
        # roll the bomb away without the standing owner moving at all.
        game = Game(OpenArenaLevel())
        p1, p2 = game.players
        p2.can_kick = True
        game.set_tile(p1.x, p1.y, Floor())
        p1.x, p1.y = 5, 5
        game.set_tile(p1.x, p1.y, p1)
        p1.standing_on = Floor()
        self.assertTrue(game.place_bomb(p1))
        bomb = game.bombs[0]
        self.assertIs(game.tile_at(p1.x, p1.y), bomb)

        game.set_tile(p2.x, p2.y, Floor())
        p2.x, p2.y = 4, 5
        game.set_tile(p2.x, p2.y, p2)

        self.assertFalse(game.move_player(p2, RIGHT))
        self.assertEqual((p1.x, p1.y), (5, 5))
        self.assertEqual((p2.x, p2.y), (4, 5))
        self.assertEqual((bomb.x, bomb.y), (5, 5))
        self.assertIsNone(bomb.rolling)
        self.assertIs(p1.standing_on, bomb)

    def test_kick_takes_priority_over_shift_when_player_has_both(self):
        game = Game(OpenArenaLevel())
        p1 = game.players[0]
        p1.can_kick = True
        p1.can_shift = True
        bomb = self._place_bomb(game, 2, 1, p1)
        self.assertTrue(game.move_player(p1, RIGHT))
        self.assertEqual((p1.x, p1.y), (1, 1))  # stayed put -- was kicked, not shifted
        self.assertIsNotNone(bomb.rolling)

    def test_bomb_under_tile_is_restored_when_it_moves_off_gunpowder(self):
        game = Game(OpenArenaLevel())
        p1 = game.players[0]
        p1.can_shift = True
        self._place_bomb(game, 2, 1, p1, under=Gunpowder())
        self.assertTrue(game.move_player(p1, RIGHT))
        # The player follows the bomb onto (2,1), so the gunpowder that was
        # under the bomb is now what the player is standing on -- not
        # silently overwritten by a hardcoded blank floor tile.
        self.assertIsInstance(p1.standing_on, Gunpowder)
        # And it reappears on the grid once the player steps off again
        # (back the way they came -- (3,1) now holds the shifted bomb, and
        # straight up/down from (2,1) is a pillar wall in this layout).
        self.assertTrue(game.move_player(p1, LEFT))
        self.assertIsInstance(game.tile_at(2, 1), Gunpowder)


class PowerUpAndPortalTests(unittest.TestCase):
    def setUp(self):
        fast_timers()

    def tearDown(self):
        slow_timers()

    def test_powerup_is_revealed_not_destroyed_when_hit(self):
        game = Game(OpenArenaLevel())
        p1 = game.players[0]
        pu = PowerUp(model.EXTRA_BOMB)
        game.set_tile(p1.x + 1, p1.y, pu)
        game.place_bomb(p1)
        time.sleep(0.02)
        game.tick()
        self.assertFalse(pu.revealed)
        time.sleep(0.02)
        game.tick()
        self.assertTrue(pu.revealed)
        self.assertIsInstance(game.tile_at(p1.x + 1, p1.y), PowerUp)

    def test_picking_up_powerup_applies_effect(self):
        game = Game(OpenArenaLevel())
        p1 = game.players[0]
        p1.bombs_available = 1
        old_x, old_y = p1.x, p1.y
        pu = PowerUp(model.EXTRA_BOMB)
        pu.revealed = True
        game.set_tile(p1.x + 1, p1.y, pu)
        self.assertTrue(game.move_player(p1, RIGHT))
        self.assertEqual(p1.bombs_available, 2)
        self.assertIsInstance(game.tile_at(old_x, old_y), Floor)

    def test_portal_teleports_player(self):
        game = Game(PortalMazeLevel())
        p1 = game.players[0]
        portal_a = game.portals[0]
        portal_b = portal_a.other
        p1.x, p1.y = portal_a.x - 1, portal_a.y
        game.set_tile(p1.x, p1.y, p1)
        p1.standing_on = Floor()
        self.assertTrue(game.move_player(p1, RIGHT))
        self.assertEqual((p1.x, p1.y), (portal_b.x, portal_b.y))


class GameOverTests(unittest.TestCase):
    def test_game_ends_when_a_player_runs_out_of_lives(self):
        game = Game(OpenArenaLevel())
        p1, p2 = game.players
        p2.lives = 1
        p2.hit()
        game._check_game_over()
        self.assertTrue(game.game_over)
        self.assertIs(game.winner, p1)


class ArenaShrinkTests(unittest.TestCase):
    def setUp(self):
        fast_shrink_timers()

    def tearDown(self):
        slow_shrink_timers()

    @staticmethod
    def _advance(game):
        # Crossing the start threshold and taking the first step are two
        # separate ticks by design (a tick that notices the timer elapsed
        # arms the spiral; the step itself waits for ARENA_SHRINK_STEP_MS
        # after that), so tests need to cross both boundaries explicitly.
        time.sleep(0.02)
        game.tick()
        time.sleep(0.02)
        game.tick()

    def test_no_walls_before_the_timer_starts(self):
        game = Game(OpenArenaLevel())
        game.tick()
        self.assertIsInstance(game.tile_at(1, 2), Floor)

    def test_first_ring_places_mirrored_walls_once_players_are_clear(self):
        game = Game(OpenArenaLevel())
        p1, p2 = game.players
        # Move both players off (1,1)/(13,9) -- the very first ring's
        # targets -- so this step should place walls, not kill anyone.
        game.set_tile(p1.x, p1.y, Floor())
        game.set_tile(p2.x, p2.y, Floor())
        p1.x, p1.y = 7, 5
        p2.x, p2.y = 7, 6
        game.set_tile(p1.x, p1.y, p1)
        game.set_tile(p2.x, p2.y, p2)
        self._advance(game)
        self.assertIsInstance(game.tile_at(1, 1), Wall)
        self.assertIsInstance(game.tile_at(game.width - 2, game.height - 2), Wall)

    def test_player_caught_by_the_closing_arena_dies_instantly_no_wall(self):
        game = Game(OpenArenaLevel())
        p1 = game.players[0]
        self.assertEqual((p1.x, p1.y), (1, 1))  # OpenArenaLevel's spawn
        self._advance(game)
        self.assertTrue(p1.is_dead)
        self.assertTrue(game.game_over)
        # No wall placed this step -- the kill takes priority.
        self.assertNotIsInstance(game.tile_at(1, 1), Wall)

    def test_second_spot_only_killed_when_first_spot_is_clear(self):
        game = Game(OpenArenaLevel())
        p1, p2 = game.players
        # Clear the first ring's first spot, but leave a player on its
        # mirrored second spot -- only that one should die.
        game.set_tile(p1.x, p1.y, Floor())
        p1.x, p1.y = 5, 5
        game.set_tile(p1.x, p1.y, p1)
        second_x, second_y = game.width - 2, game.height - 2
        self.assertEqual((p2.x, p2.y), (second_x, second_y))
        self._advance(game)
        self.assertFalse(p1.is_dead)
        self.assertTrue(p2.is_dead)
        self.assertNotIsInstance(game.tile_at(1, 1), Wall)
        self.assertNotIsInstance(game.tile_at(second_x, second_y), Wall)


class LevelGenerationTests(unittest.TestCase):
    def test_every_level_has_intact_border_and_reachable_spawns(self):
        for level_cls in (MazeLevel, GunpowderCrossLevel, PortalMazeLevel, OpenArenaLevel):
            level = level_cls()
            grid = level.build_grid()
            for x in range(level.width):
                self.assertIsInstance(grid[x][0], Wall)
                self.assertIsInstance(grid[x][level.height - 1], Wall)
            for y in range(level.height):
                self.assertIsInstance(grid[0][y], Wall)
                self.assertIsInstance(grid[level.width - 1][y], Wall)
            self.assertTrue(grid[1][1].is_walkable())
            self.assertTrue(grid[level.width - 2][level.height - 2].is_walkable())


class DeterministicClockTests(unittest.TestCase):
    def test_injected_clock_controls_bomb_fuse(self):
        now = [0]
        game = Game(OpenArenaLevel(), clock=lambda: now[0])
        self.assertTrue(game.place_bomb(game.players[0]))
        now[0] = model.BOMB_FUSE_MS - 1
        game.tick()
        self.assertEqual(len(game.bombs), 1)
        now[0] = model.BOMB_FUSE_MS
        game.tick()
        self.assertEqual(len(game.bombs), 0)


if __name__ == "__main__":
    unittest.main()
