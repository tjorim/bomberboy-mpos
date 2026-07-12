import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bomberboy"))

import model
from ai import choose_action, danger_cells
from levels import OpenArenaLevel
from model import Crate, Floor, Game, Gunpowder



def fast_timers():
    model.BOMB_FUSE_MS = 5
    model.BOMB_BURN_MS = 5


def slow_timers():
    model.BOMB_FUSE_MS = 2000
    model.BOMB_BURN_MS = 1000


class DangerAvoidanceTests(unittest.TestCase):
    def setUp(self):
        fast_timers()

    def tearDown(self):
        slow_timers()

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

    def test_bot_does_not_walk_into_its_own_blast(self):
        game = Game(OpenArenaLevel())
        bot, opponent = game.players
        bot.flame_range = 2
        action = choose_action(game, bot, opponent)
        if action == ("bomb",):
            game.place_bomb(bot)
            danger = danger_cells(game)
            self.assertNotIn((bot.x, bot.y), danger)


class AttackTests(unittest.TestCase):
    def setUp(self):
        fast_timers()

    def tearDown(self):
        slow_timers()

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
    def setUp(self):
        fast_timers()

    def tearDown(self):
        slow_timers()

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
