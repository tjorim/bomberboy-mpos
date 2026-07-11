"""Onboard-LED life counter, using whatever NeoPixel strip
mpos.lights.LightsManager already has initialized -- 5 LEDs below the
screen on the Fri3d Camp 2026 Badge, a no-op everywhere else (including
the desktop simulator, which has none).

Splits the available LEDs into two halves, one per player, and lights a
number proportional to that player's remaining lives in their sprite
color (see sprites.py's P1_BODY/P2_BODY, duplicated here rather than
imported since this module intentionally has no lv/mpos-free-testing
constraint the way model.py does, but also has no reason to depend on
the LVGL-facing sprites module).
"""

import mpos.lights as LightsManager

P1_COLOR = (0x1E, 0x88, 0xE5)
P2_COLOR = (0xE5, 0x39, 0x35)
OFF = (0, 0, 0)


def update(p1_lives, p1_max_lives, p2_lives, p2_max_lives):
    if not LightsManager.is_available():
        return
    total = LightsManager.get_led_count()
    if total <= 0:
        return
    half = total // 2
    _fill(0, half, p1_lives, p1_max_lives, P1_COLOR)
    _fill(half, total - half, p2_lives, p2_max_lives, P2_COLOR)
    LightsManager.write()


def _fill(start, count, lives, max_lives, color):
    if count <= 0:
        return
    lit = round(count * lives / max_lives) if max_lives else 0
    lit = max(0, min(count, lit))
    for i in range(count):
        LightsManager.set_led(start + i, *(color if i < lit else OFF))


def clear():
    if LightsManager.is_available():
        LightsManager.clear()
        LightsManager.write()
