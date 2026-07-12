import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bomberboy"))

from model import DOWN, LEFT, RIGHT, UP
import dj_addon


class DJAddonInputTests(unittest.TestCase):
    def test_maps_all_configured_buttons_from_driver_to_game_actions(self):
        expected = {
            0: (0, "move", RIGHT),
            1: (0, "bomb", None),
            2: (0, "move", UP),
            3: (0, "move", DOWN),
            4: (0, "move", LEFT),
            5: (0, "bomb", None),
            6: (0, "bomb", None),
            7: (0, "bomb", None),
        }

        for raw_index, action in expected.items():
            with self.subTest(raw_index=raw_index):
                current = [False] * 8
                current[raw_index] = True
                self.assertEqual(
                    dj_addon.actions_from_buttons(current),
                    [action],
                )

    def test_bomb_buttons_are_edge_triggered(self):
        current = [False] * 8
        current[1] = True  # raw 1 -> logical pad 7 -> bomb
        previous = list(current)

        self.assertEqual(dj_addon.actions_from_buttons(current, previous), [])
        self.assertEqual(dj_addon.actions_from_buttons(current, [False] * 8), [(0, "bomb", None)])

    def test_multiple_bomb_buttons_emit_one_action_per_poll(self):
        current = [False] * 8
        current[1] = True
        current[5] = True

        self.assertEqual(
            dj_addon.actions_from_buttons(current, [False] * 8),
            [(0, "bomb", None)],
        )

    def test_movement_repeats_while_held(self):
        current = [False] * 8
        current[2] = True

        self.assertEqual(
            dj_addon.actions_from_buttons(current, current),
            [(0, "move", UP)],
        )

    def test_extra_driver_values_are_ignored(self):
        current = [False] * 9
        current[8] = True

        self.assertEqual(dj_addon.actions_from_buttons(current), [])

    def test_probe_constructs_live_addon_from_i2c_bus(self):
        bus = object()
        addon = mock.Mock()
        addon.is_alive.return_value = True
        addon_class = mock.Mock(return_value=addon)
        modules = {
            "mpos": types.SimpleNamespace(
                DeviceManager=types.SimpleNamespace(getBus=mock.Mock(return_value=bus))
            ),
            "drivers.fri3d.dj": types.SimpleNamespace(DJAddon=addon_class),
        }

        with mock.patch.dict(sys.modules, modules):
            result = dj_addon.DJInput.probe()

        self.assertIsInstance(result, dj_addon.DJInput)
        self.assertIs(result.addon, addon)
        modules["mpos"].DeviceManager.getBus.assert_called_once_with(type="i2c")
        addon_class.assert_called_once_with(i2c_bus=bus)

    def test_probe_returns_none_for_missing_or_unavailable_addon(self):
        cases = (
            mock.Mock(side_effect=ImportError),
            mock.Mock(return_value=types.SimpleNamespace(
                DeviceManager=types.SimpleNamespace(getBus=mock.Mock(side_effect=OSError))
            )),
        )
        real_import = __import__

        for mpos_import in cases:
            with self.subTest(mpos_import=mpos_import):
                def import_module(name, *args, **kwargs):
                    if name == "mpos":
                        return mpos_import()
                    return real_import(name, *args, **kwargs)

                with mock.patch("builtins.__import__", side_effect=import_module):
                    self.assertIsNone(dj_addon.DJInput.probe())

    def test_failed_poll_preserves_state_and_does_not_retrigger_bomb(self):
        addon = mock.Mock()
        pressed = [False] * 8
        pressed[7] = True
        addon.buttons.side_effect = (pressed, OSError("I2C glitch"), pressed)
        input_device = dj_addon.DJInput(addon)

        self.assertEqual(input_device.read_actions(), [(0, "bomb", None)])
        self.assertEqual(input_device.read_actions(), [])
        self.assertEqual(input_device.read_actions(), [])


if __name__ == "__main__":
    unittest.main()
