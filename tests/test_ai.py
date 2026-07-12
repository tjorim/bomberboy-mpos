import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bomberboy"))

import model
from ai import THINK_MS, _bfs_nearest, _live_bomb_threats, choose_action, danger_cells
from levels import OpenArenaLevel, PortalMazeLevel
from model import Bomb, Crate, Floor, Game, Gunpowder, Wall


class DangerAvoidanceTests(unittest.TestCase):
    def test_bot_flees_when_standing_in_a_pending_blast(self):
        game = Game(OpenArenaLevel())
        bot, opponent = game.players
        # A live bomb from the opponent, right where the bot is standing.
        opponent.x, opponent.y = bot.x + 2, bot.y
        opponent.flame_range = 3
        game.place_bomb(opponent)
        self.assertIn((bot.x, bot.y), danger_cells(game))
        action = choose_action(game, bot, opponent)
        self.assertIsNotNone(action)
        self.assertEqual(action[0], "move")
        kind, direction = action
        dx, dy = model.DELTA[direction]
        self.assertNotIn((bot.x + dx, bot.y + dy), danger_cells(game))

    def test_bot_escapes_its_own_blast_after_bombing(self):
        # Force a bombing situation deterministically (same mid-arena setup
        # as AttackTests), then simulate the think-ticks that follow: the
        # bot starts on its own bomb -- every neighbouring cell is a
        # pending-blast cell, so escaping requires walking *through* the
        # blast area, not around it -- and must end up outside the blast
        # before the fuse runs out, using the same 350ms cadence as the UI.
        now = [0]
        game = Game(OpenArenaLevel(), clock=lambda: now[0])
        bot, opponent = game.players
        game.set_tile(bot.x, bot.y, Floor())
        game.set_tile(opponent.x, opponent.y, Floor())
        bot.x, bot.y = 5, 5
        opponent.x, opponent.y = 6, 5
        game.set_tile(bot.x, bot.y, bot)
        game.set_tile(opponent.x, opponent.y, opponent)
        bot.flame_range = 1
        self.assertEqual(choose_action(game, bot, opponent), ("bomb",))
        game.place_bomb(bot)
        self.assertIn((bot.x, bot.y), danger_cells(game))
        while now[0] + THINK_MS < model.BOMB_FUSE_MS:
            if (bot.x, bot.y) not in danger_cells(game):
                break
            now[0] += THINK_MS
            game.tick()
            action = choose_action(game, bot, opponent)
            self.assertIsNotNone(action, "bot froze while standing in a pending blast")
            self.assertEqual(action[0], "move")
            self.assertTrue(game.move_player(bot, action[1]))
        self.assertFalse(bot.on_fire)
        self.assertNotIn((bot.x, bot.y), danger_cells(game))

    def test_bot_refuses_bomb_when_safe_tile_is_beyond_the_fuse_deadline(self):
        game = Game(OpenArenaLevel(), clock=lambda: 0)
        bot, opponent = game.players
        game.set_tile(bot.x, bot.y, Floor())
        game.set_tile(opponent.x, opponent.y, Floor())
        bot.x, bot.y = 2, 5
        opponent.x, opponent.y = 1, 5
        bot.flame_range = 5
        game.set_tile(bot.x, bot.y, bot)
        game.set_tile(opponent.x, opponent.y, opponent)
        for x in range(2, 8):
            game.set_tile(x, 4, Wall())
            game.set_tile(x, 6, Wall())

        self.assertIsNone(choose_action(game, bot, opponent))

    def test_chain_reaction_uses_the_earliest_bomb_deadline(self):
        now = [1000]
        game = Game(OpenArenaLevel(), clock=lambda: now[0])
        first_owner, second_owner = game.players
        first_owner.flame_range = 2
        first = Bomb(first_owner, 3, 5, Floor(), placed_at=0)
        second = Bomb(second_owner, 4, 5, Floor(), placed_at=900)
        game.set_tile(first.x, first.y, first)
        game.set_tile(second.x, second.y, second)
        game.bombs.extend((first, second))

        threats = _live_bomb_threats(game)

        self.assertEqual(threats[0][1], 1000)
        self.assertEqual(threats[1][1], 1000)


class AttackTests(unittest.TestCase):
    def test_bot_bombs_opponent_when_aligned_with_a_clear_safe_shot(self):
        game = Game(OpenArenaLevel())
        bot, opponent = game.players
        # Put both players in the open middle of the arena, away from the
        # corner spawns, so the bot actually has somewhere to retreat to
        # after bombing (a cornered bot correctly refuses to self-trap).
        game.set_tile(bot.x, bot.y, Floor())
        game.set_tile(opponent.x, opponent.y, Floor())
        bot.x, bot.y = 5, 5
        opponent.x, opponent.y = 6, 5
        game.set_tile(bot.x, bot.y, bot)
        game.set_tile(opponent.x, opponent.y, opponent)
        bot.flame_range = 1
        action = choose_action(game, bot, opponent)
        self.assertEqual(action, ("bomb",))


class GunpowderNetworkDangerTests(unittest.TestCase):
    def test_danger_cells_include_the_whole_gunpowder_network_not_just_local_blast(self):
        # Game._ignite_gunpowder_network ignites every Gunpowder tile on the
        # board the instant a blast reaches any one of them -- not just the
        # tiles within normal flame range. The AI's danger model has to
        # account for that or it can consider a far-away gunpowder tile
        # "safe" right up until it also catches fire.
        game = Game(OpenArenaLevel())
        bot, opponent = game.players
        game.set_tile(bot.x, bot.y, Floor())
        game.set_tile(opponent.x, opponent.y, Floor())
        opponent.x, opponent.y = 5, 5
        game.set_tile(opponent.x, opponent.y, opponent)
        bot.x, bot.y = 9, 5
        game.set_tile(bot.x, bot.y, bot)

        near = (opponent.x + 1, opponent.y)
        game.set_tile(*near, Gunpowder())
        far = (2, 9)
        game.set_tile(*far, Gunpowder())

        opponent.flame_range = 1
        game.place_bomb(opponent)

        self.assertIn(far, danger_cells(game))


class PortalPathfindingTests(unittest.TestCase):
    def test_safe_portal_is_one_pathfinding_move_to_its_destination(self):
        game = Game(PortalMazeLevel())
        bot, _opponent = game.players
        game.set_tile(bot.x, bot.y, Floor())
        source = game.portals[0]
        bot.x, bot.y = source.x - 1, source.y
        game.set_tile(bot.x, bot.y, bot)

        path = _bfs_nearest(
            game,
            (bot.x, bot.y),
            lambda pos: pos == (source.other.x, source.other.y),
            avoid=set(),
        )

        self.assertEqual(path, [(source.x, source.y)])

    def test_bot_does_not_escape_through_a_portal_into_a_pending_blast(self):
        now = [1900]
        game = Game(PortalMazeLevel(), clock=lambda: now[0])
        bot, opponent = game.players
        game.set_tile(bot.x, bot.y, Floor())
        source = game.portals[0]
        destination = source.other
        bot.x, bot.y = source.x - 1, source.y
        game.set_tile(bot.x, bot.y, bot)

        near = Bomb(bot, bot.x, bot.y - 1, Floor(), placed_at=0)
        exit_bomb = Bomb(opponent, destination.x - 1, destination.y, Floor(), placed_at=0)
        game.set_tile(near.x, near.y, near)
        game.set_tile(exit_bomb.x, exit_bomb.y, exit_bomb)
        game.bombs.extend((near, exit_bomb))

        self.assertIn((bot.x, bot.y), danger_cells(game))
        self.assertNotIn((destination.x, destination.y), danger_cells(game))
        self.assertIsNone(choose_action(game, bot, opponent))


class ArenaShrinkAwarenessTests(unittest.TestCase):
    def _started_game(self):
        now = [0]
        game = Game(OpenArenaLevel(), clock=lambda: now[0])
        now[0] = model.ARENA_SHRINK_START_MS
        game.tick()
        self.assertTrue(game.is_shrinking())
        return game

    def test_bot_moves_off_an_imminent_shrink_position(self):
        game = self._started_game()
        bot, opponent = game.players
        self.assertIn((bot.x, bot.y), danger_cells(game))
        action = choose_action(game, bot, opponent)
        self.assertIsNotNone(action)
        self.assertEqual(action[0], "move")
        dx, dy = model.DELTA[action[1]]
        self.assertNotIn((bot.x + dx, bot.y + dy), danger_cells(game))

    def test_bot_biases_wandering_toward_center_after_shrink_starts(self):
        game = self._started_game()
        bot, opponent = game.players
        game.set_tile(bot.x, bot.y, Floor())
        bot.x, bot.y = 1, 3
        game.set_tile(bot.x, bot.y, bot)
        center = (game.width // 2, game.height // 2)
        before = max(abs(bot.x - center[0]), abs(bot.y - center[1]))

        action = choose_action(game, bot, opponent)
        self.assertIsNotNone(action)
        self.assertEqual(action[0], "move")
        dx, dy = model.DELTA[action[1]]
        after = max(abs(bot.x + dx - center[0]), abs(bot.y + dy - center[1]))
        self.assertLess(after, before)


class CrateBreakingTests(unittest.TestCase):
    def test_bot_moves_towards_a_reachable_crate(self):
        game = Game(OpenArenaLevel())
        bot, opponent = game.players
        # Wall the bot off from the opponent's whole side with a single
        # crate one step to its right, so the only useful move is towards it.
        game.set_tile(bot.x + 1, bot.y, Crate())
        action = choose_action(game, bot, opponent)
        self.assertIsNotNone(action)
        self.assertIn(action[0], ("move", "bomb"))


if __name__ == "__main__":
    unittest.main()
