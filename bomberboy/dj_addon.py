"""Optional Fri3d DJ Add-on input for Bomberboy.

The DJ Add-on is not registered by MicroPythonOS as a normal LVGL input
source, so the app has to probe it directly over I2C and poll its eight big
buttons. The physical button order used here mirrors the existing
``com.micropythonos.dj_addon`` app's raw-to-pad mapping for the two adjacent
2x2 button clusters. The gameplay mapping is kept in constants so it remains
easy to tune after hands-on accessibility testing.
"""

from model import DOWN, LEFT, RIGHT, UP

REFRESH_MS = 100
_DJ_TO_PAD = (3, 7, 1, 2, 0, 5, 6, 4)

# Pad indices are a 2x4 logical grid after applying _DJ_TO_PAD:
#   0 1 2 3
#   4 5 6 7
# The buttons are a linear bank rather than a physical D-pad. Use the top row
# for clearly labelled directions and the entire bottom row as one large,
# redundant bomb target:
#   left  up    down  right
#   bomb  bomb  bomb  bomb
_PAD_ACTIONS = {
    0: (0, "move", LEFT),
    1: (0, "move", UP),
    2: (0, "move", DOWN),
    3: (0, "move", RIGHT),
    4: (0, "bomb", None),
    5: (0, "bomb", None),
    6: (0, "bomb", None),
    7: (0, "bomb", None),
}


class DJInput:
    def __init__(self, addon):
        self.addon = addon
        self.previous = (False,) * 8

    @classmethod
    def probe(cls):
        """Return a DJInput when the add-on is attached, otherwise None."""
        try:
            import mpos
            from drivers.fri3d.dj import DJAddon

            bus = mpos.DeviceManager.getBus(type="i2c")
            addon = DJAddon(i2c_bus=bus)
            if addon.is_alive():
                return cls(addon)
        except Exception:
            pass
        return None

    def read_actions(self):
        """Poll the add-on and return ``(player_index, kind, direction)`` actions.

        Movement is repeated while held so the big buttons feel like a D-pad.
        Bomb actions are edge-triggered to avoid dropping a bomb every poll.
        """
        try:
            current = tuple(bool(value) for value in self.addon.buttons())
        except Exception:
            # Preserve the last known state. Treating a failed read as a
            # release would make a held bomb button fire again after I2C
            # communication recovers.
            return []
        actions = actions_from_buttons(current, self.previous)
        self.previous = current
        return actions


def actions_from_buttons(current, previous=None):
    if previous is None:
        previous = (False,) * 8
    actions = []
    emitted = set()
    for raw_index, pressed in enumerate(current):
        if raw_index >= len(_DJ_TO_PAD) or not pressed:
            continue
        pad_index = _DJ_TO_PAD[raw_index]
        action = _PAD_ACTIONS.get(pad_index)
        if action is None:
            continue
        player_index, kind, direction = action
        if kind == "bomb" and raw_index < len(previous) and previous[raw_index]:
            continue
        if action in emitted:
            continue
        actions.append(action)
        emitted.add(action)
    return actions
