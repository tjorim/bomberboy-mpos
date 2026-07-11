"""Optional Fri3d DJ Add-on input for Bomberboy.

The DJ Add-on is not registered by MicroPythonOS as a normal LVGL input
source, so the app has to probe it directly over I2C and poll its eight big
buttons. The physical button order used here mirrors the existing
``com.micropythonos.dj_addon`` app's raw-to-pad mapping; keep the gameplay
mapping in the constants below easy to adjust after a real-hardware layout
check.
"""

from model import DOWN, LEFT, RIGHT, UP

REFRESH_MS = 100
_DJ_TO_PAD = (3, 7, 1, 2, 0, 5, 6, 4)

# Pad indices are a 2x4 logical grid after applying _DJ_TO_PAD:
#   0 1 2 3
#   4 5 6 7
# The default makes the left cluster a P1 D-pad and the right side bombs.
_PAD_ACTIONS = {
    1: (0, "move", UP),
    4: (0, "move", LEFT),
    5: (0, "move", DOWN),
    6: (0, "move", RIGHT),
    3: (0, "bomb", None),
    7: (1, "bomb", None),
}


class DJInput:
    def __init__(self, addon):
        self.addon = addon
        self.previous = (False,) * 8

    @classmethod
    def probe(cls):
        """Return a DJInput when the add-on is attached, otherwise None."""
        try:
            mpos = __import__("mpos")
            dj_module = __import__("drivers.fri3d.dj", None, None, ("DJAddon",))
            bus = mpos.DeviceManager.getBus(type="i2c")
            addon = dj_module.DJAddon(i2c_bus=bus)
            if addon.is_alive():
                return cls(addon)
        except Exception:
            pass
        return None

    def read_actions(self, two_player=False):
        """Poll the add-on and return ``(player_index, kind, direction)`` actions.

        Movement is repeated while held so the big buttons feel like a D-pad.
        Bomb actions are edge-triggered to avoid dropping a bomb every poll.
        """
        try:
            current = tuple(bool(value) for value in self.addon.buttons())
        except Exception:
            current = (False,) * 8
        actions = actions_from_buttons(current, self.previous, two_player=two_player)
        self.previous = current
        return actions


def actions_from_buttons(current, previous=None, two_player=False):
    if previous is None:
        previous = (False,) * 8
    actions = []
    for raw_index, pressed in enumerate(current):
        if raw_index >= len(_DJ_TO_PAD) or not pressed:
            continue
        pad_index = _DJ_TO_PAD[raw_index]
        action = _PAD_ACTIONS.get(pad_index)
        if action is None:
            continue
        player_index, kind, direction = action
        if player_index == 1 and not two_player:
            continue
        if kind == "bomb" and raw_index < len(previous) and previous[raw_index]:
            continue
        actions.append(action)
    return actions
