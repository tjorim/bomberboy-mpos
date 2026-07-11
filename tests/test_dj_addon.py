import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bomberboy"))

from model import DOWN, RIGHT, UP
import dj_addon


class DJAddonInputTests(unittest.TestCase):
    def test_maps_existing_raw_order_to_default_big_button_actions(self):
        current = [False] * 8
        current[2] = True  # raw 2 -> logical pad 1 -> up
        current[5] = True  # raw 5 -> logical pad 5 -> down
        current[6] = True  # raw 6 -> logical pad 6 -> right

        self.assertEqual(
            dj_addon.actions_from_buttons(current),
            [(0, "move", UP), (0, "move", DOWN), (0, "move", RIGHT)],
        )

    def test_bomb_buttons_are_edge_triggered(self):
        current = [False] * 8
        current[1] = True  # raw 1 -> logical pad 7 -> P2 bomb
        previous = list(current)

        self.assertEqual(dj_addon.actions_from_buttons(current, previous, two_player=True), [])
        self.assertEqual(dj_addon.actions_from_buttons(current, [False] * 8, two_player=True), [(1, "bomb", None)])

    def test_player_two_button_is_ignored_outside_two_player_mode(self):
        current = [False] * 8
        current[1] = True

        self.assertEqual(dj_addon.actions_from_buttons(current, [False] * 8, two_player=False), [])


if __name__ == "__main__":
    unittest.main()
