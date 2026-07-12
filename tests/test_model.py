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
        time.sleep(0.2)  # each check should fail on the wall, not the move cooldown
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

    def test_a_dead_player_blocks_movement_instead_of_being_erased(self):
        # Player.is_walkable() is unconditionally True (dead or alive),
        # and player_at() deliberately excludes dead players so they
        # don't participate in kick/shift/swap -- but move_player() used
        # to fall through to the generic floor-walk path in that case,
        # using the dead Player object itself as "the tile left behind".
        # That erased the body from the grid (dedicated dead-player
        # sprite art exists specifically so it stays visible) and left
        # the walker's own standing_on pointing at a Player instead of a
        # real tile.
        self.game.set_tile(self.p2.x, self.p2.y, Floor())
        self.p2.x, self.p2.y = self.p1.x + 1, self.p1.y
        self.game.set_tile(self.p2.x, self.p2.y, self.p2)
        self.p2.lives = 0
        self.assertTrue(self.p2.is_dead)

        self.assertFalse(self.game.move_player(self.p1, RIGHT))
        self.assertEqual((self.p1.x, self.p1.y), (1, 1))
        self.assertIs(self.game.tile_at(self.p2.x, self.p2.y), self.p2)


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

    def test_owner_takes_damage_from_their_own_bomb_if_still_standing_on_it(self):
        # _explode() used to restore the grid at the bomb's own position
        # to bomb.under (e.g. Floor) *before* igniting it, so if the owner
        # never moved off their own bomb, _ignite() would see that
        # restored tile instead of them -- placing a bomb and simply not
        # moving was a free, undetectable way to dodge its own blast.
        lives_before = self.p1.lives
        self.game.place_bomb(self.p1)
        time.sleep(0.02)
        self.game.tick()
        self.assertTrue(self.p1.on_fire)
        self.assertEqual(self.p1.lives, lives_before)
        time.sleep(0.02)
        self.game.tick()
        self.assertEqual(self.p1.lives, lives_before - 1)

    def test_origin_tile_is_marked_burning_even_when_owner_is_still_on_it(self):
        # An earlier version of this fix skipped _ignite(bomb.x, bomb.y)
        # entirely when the owner was still standing on it, so nothing
        # marked the tile as burning -- no fire rendered there, and if the
        # bomb was on gunpowder, the network under the player would never
        # ignite (see the next test). Caught by Gemini Code Assist review
        # on the PR that introduced the owner-damage fix:
        # https://github.com/tjorim/bomberboy-mpos/pull/12#discussion_r3566685249
        self.game.place_bomb(self.p1)
        origin = (self.p1.x, self.p1.y)
        time.sleep(0.02)
        self.game.tick()
        self.assertTrue(self.game.is_burning(*origin))

    def test_gunpowder_under_the_owner_still_ignites_the_whole_network(self):
        self.p1.standing_on = Gunpowder()
        other_gunpowder = (self.p1.x + 3, self.p1.y)
        self.game.set_tile(*other_gunpowder, Gunpowder())
        self.assertTrue(self.game.place_bomb(self.p1))
        time.sleep(0.02)
        self.game.tick()
        self.assertIn(other_gunpowder, self.game.burning_tile_positions())

    def test_owner_who_moved_away_is_not_hit_at_the_bombs_old_position(self):
        self.game.place_bomb(self.p1)
        origin = (self.p1.x, self.p1.y)
        # Simulate having walked well clear of the blast (flame_range 1
        # only reaches directly-adjacent tiles) via direct placement
        # rather than pathing through the maze, which isn't guaranteed
        # clear beyond the spawn pocket -- matches this suite's existing
        # pattern for other tests that don't care about the path itself.
        self.game.set_tile(*origin, Floor())
        self.p1.standing_on = Floor()
        self.p1.x, self.p1.y = origin[0] + 3, origin[1] + 3
        self.game.set_tile(self.p1.x, self.p1.y, self.p1)
        time.sleep(0.02)
        self.game.tick()
        self.assertFalse(self.p1.on_fire)

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


class BombBlinkPhaseTests(unittest.TestCase):
    """Bomb.blink_phase() is a presentation-only hint (0 = normal, 1 =
    "flash") consumed by render.py to blink a bomb faster as its fuse
    runs down -- pure elapsed-time math, so it's tested here directly
    rather than through the LVGL-facing renderer, which can't be
    unit-tested under plain CPython at all."""

    @staticmethod
    def _bomb():
        return model.Bomb(owner=None, x=0, y=0, under=Floor(), placed_at=0)

    def test_no_blink_for_the_first_half_of_the_fuse(self):
        bomb = self._bomb()
        self.assertEqual(bomb.blink_phase(0), 0)
        self.assertEqual(bomb.blink_phase(model.BOMB_FUSE_MS // 2 - 1), 0)

    def test_slow_blink_starts_at_the_halfway_point(self):
        bomb = self._bomb()
        start = model.BOMB_FUSE_MS // 2
        self.assertNotEqual(
            bomb.blink_phase(start),
            bomb.blink_phase(start + model.BOMB_BLINK_WARN_PERIOD_MS),
        )

    def test_fast_blink_starts_in_the_final_quarter(self):
        bomb = self._bomb()
        start = model.BOMB_FUSE_MS - model.BOMB_BLINK_CRITICAL_REMAINING_MS
        self.assertNotEqual(
            bomb.blink_phase(start),
            bomb.blink_phase(start + model.BOMB_BLINK_CRITICAL_PERIOD_MS),
        )

    def test_critical_blink_is_faster_than_warning_blink(self):
        self.assertLess(model.BOMB_BLINK_CRITICAL_PERIOD_MS, model.BOMB_BLINK_WARN_PERIOD_MS)


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

    def test_kicked_bomb_stops_before_a_portal(self):
        # Portal.is_walkable() is just "not occupied", so without an
        # explicit check a rolling bomb would park on top of a portal
        # instead of stopping -- with nothing to actually teleport it the
        # way _use_portal() teleports a player, leaving the grid showing
        # the Bomb instead of the Portal while portal.occupied never gets
        # set, so a player could still teleport into that same tile and
        # silently overwrite the bomb.
        game = Game(PortalMazeLevel())
        p1 = game.players[0]
        p1.can_kick = True
        portal = game.portals[0].other  # (11, 7); room to its left for a clear lane
        for x in (portal.x - 3, portal.x - 2, portal.x - 1):
            game.set_tile(x, portal.y, Floor())
        bomb = self._place_bomb(game, portal.x - 2, portal.y, p1)
        p1.x, p1.y = portal.x - 3, portal.y
        game.set_tile(p1.x, p1.y, p1)
        self.assertTrue(game.move_player(p1, RIGHT))
        self.assertEqual((bomb.x, bomb.y), (portal.x - 1, portal.y))
        time.sleep(0.02)
        game.tick()
        self.assertEqual((bomb.x, bomb.y), (portal.x - 1, portal.y))  # blocked by the portal
        self.assertIsNone(bomb.rolling)
        self.assertIs(game.tile_at(portal.x, portal.y), portal)
        self.assertFalse(portal.occupied)

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

    def test_cannot_swap_when_the_initiating_player_is_standing_on_a_bomb(self):
        # Symmetric to the case above: move_player() originally only
        # checked isinstance(target, Bomb) -- the *destination* tile --
        # so it missed the case where `player`, the one initiating the
        # move, is themselves standing on their own bomb. target there
        # is just an ordinary Player (occupant), so the swap branch would
        # have run and _swap_players() would have overwritten player's
        # own grid cell (holding the Bomb) with the swapped-in occupant,
        # losing the Bomb the grid needs there for fuse/blast-chain
        # detection -- and later erasing whoever ends up standing there
        # once the bomb explodes.
        game = Game(OpenArenaLevel())
        p1, p2 = game.players
        game.set_tile(p1.x, p1.y, Floor())
        p1.x, p1.y = 5, 5
        game.set_tile(p1.x, p1.y, p1)
        p1.standing_on = Floor()
        self.assertTrue(game.place_bomb(p1))
        bomb = game.bombs[0]
        self.assertIs(game.tile_at(p1.x, p1.y), bomb)

        game.set_tile(p2.x, p2.y, Floor())
        p2.x, p2.y = 6, 5
        game.set_tile(p2.x, p2.y, p2)

        self.assertFalse(game.move_player(p1, RIGHT))
        self.assertEqual((p1.x, p1.y), (5, 5))
        self.assertEqual((p2.x, p2.y), (6, 5))
        self.assertEqual((bomb.x, bomb.y), (5, 5))
        self.assertIs(p1.standing_on, bomb)
        self.assertIs(game.tile_at(5, 5), bomb)

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
        time.sleep(0.2)  # clear the move cooldown (model.MOVE_COOLDOWN_MS)
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

    def test_portal_stops_blocking_teleport_after_the_player_walks_away(self):
        # dest.occupied was only ever cleared by _use_portal() itself (on
        # the *source* side of a later teleport) -- walking away from a
        # portal normally, through _enter_tile(), never cleared it, so a
        # portal stayed permanently un-teleportable-into for the rest of
        # the match after its first arrival, even with nobody standing on
        # it anymore.
        game = Game(PortalMazeLevel())
        p1, p2 = game.players
        portal_a = game.portals[0]
        portal_b = portal_a.other

        p1.x, p1.y = portal_a.x - 1, portal_a.y
        game.set_tile(p1.x, p1.y, p1)
        p1.standing_on = Floor()
        self.assertTrue(game.move_player(p1, RIGHT))
        self.assertEqual((p1.x, p1.y), (portal_b.x, portal_b.y))
        self.assertTrue(portal_b.occupied)

        # Walk away to plain floor -- not back through the portal.
        game.set_tile(portal_b.x + 1, portal_b.y, Floor())
        time.sleep(0.2)  # clear the move cooldown (model.MOVE_COOLDOWN_MS)
        self.assertTrue(game.move_player(p1, RIGHT))
        self.assertFalse(portal_b.occupied)

        # A second player can now teleport into portal_b too.
        p2.x, p2.y = portal_a.x - 1, portal_a.y
        game.set_tile(p2.x, p2.y, p2)
        p2.standing_on = Floor()
        game.move_player(p2, RIGHT)
        self.assertEqual((p2.x, p2.y), (portal_b.x, portal_b.y))

    def test_move_reports_failure_when_portal_destination_is_occupied(self):
        game = Game(PortalMazeLevel())
        p1, _p2 = game.players
        portal = game.portals[0]
        portal.other.occupied = True
        game.set_tile(p1.x, p1.y, Floor())
        p1.x, p1.y = portal.x - 1, portal.y
        p1.standing_on = Floor()
        game.set_tile(p1.x, p1.y, p1)

        self.assertFalse(game.move_player(p1, RIGHT))
        self.assertEqual((p1.x, p1.y), (portal.x - 1, portal.y))


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

    def test_upcoming_positions_preview_wall_pairs_without_advancing_state(self):
        game = Game(OpenArenaLevel())
        game._shrink_started = True

        self.assertEqual(
            game.upcoming_shrink_positions(2),
            [((1, 1), (13, 9)), ((2, 1), (12, 9))],
        )
        self.assertEqual((game._shrink_i, game._shrink_j, game._shrink_k), (1, 1, 2))

    def test_upcoming_positions_stop_immediately_after_rectangular_arena_is_consumed(self):
        game = Game(OpenArenaLevel())
        game._shrink_started = True
        # Terminal state reached after the fifth horizontal ring on a 15x11
        # board: both edge ranges are exhausted and k has passed its limit.
        game._shrink_i = 5
        game._shrink_j = 10
        game._shrink_k = 6
        game._shrink_horizontal = True

        self.assertEqual(game.upcoming_shrink_positions(2), [])

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


class MoveCooldownTests(unittest.TestCase):
    """SPEED_UP used to increment Player.speed with nothing ever reading
    it, so the powerup had zero gameplay effect. Player.move_cooldown_ms()
    is the fix: speed divides down the minimum interval between accepted
    moves.

    OpenArenaLevel gives an open, crate-free lane to move along, but also
    sets give_max_stats -- including speed = MAX_SPEED -- so every test
    here resets p1.speed back to 1 (the real default elsewhere) to actually
    exercise the cooldown instead of the trivially-short one at max speed.
    """

    def test_first_move_is_never_blocked_even_with_a_clock_starting_at_zero(self):
        # last_move_at starts as None specifically so this doesn't collide
        # with an injected clock legitimately starting at 0.
        now = [0]
        game = Game(OpenArenaLevel(), clock=lambda: now[0])
        p1 = game.players[0]
        p1.speed = 1
        self.assertTrue(game.move_player(p1, RIGHT))

    def test_move_is_rejected_before_the_cooldown_elapses(self):
        now = [0]
        game = Game(OpenArenaLevel(), clock=lambda: now[0])
        p1 = game.players[0]
        p1.speed = 1
        self.assertTrue(game.move_player(p1, RIGHT))
        pos = (p1.x, p1.y)
        now[0] = model.MOVE_COOLDOWN_MS - 1
        self.assertFalse(game.move_player(p1, RIGHT))
        self.assertEqual((p1.x, p1.y), pos)

    def test_move_succeeds_once_the_cooldown_elapses(self):
        now = [0]
        game = Game(OpenArenaLevel(), clock=lambda: now[0])
        p1 = game.players[0]
        p1.speed = 1
        self.assertTrue(game.move_player(p1, RIGHT))
        now[0] = model.MOVE_COOLDOWN_MS
        self.assertTrue(game.move_player(p1, RIGHT))

    def test_higher_speed_shortens_the_cooldown(self):
        now = [0]
        game = Game(OpenArenaLevel(), clock=lambda: now[0])
        p1 = game.players[0]
        p1.speed = 2  # half the base (speed-1) cooldown
        self.assertTrue(game.move_player(p1, RIGHT))
        now[0] = model.MOVE_COOLDOWN_MS // 2
        self.assertTrue(game.move_player(p1, RIGHT))


if __name__ == "__main__":
    unittest.main()
