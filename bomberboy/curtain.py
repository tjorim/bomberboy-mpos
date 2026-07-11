"""Curtain-wipe transition, ported from the never-finished Qt attempt at
this game (github.com/tjorim/bomberboy-qt, curtain/curtain.cpp) -- two
panels slide apart to open, or slide together to close. The original used
four small rects per side for a slightly fancier look; this keeps it to
one panel per side, which reads fine at this screen size and keeps the
LVGL object count down.
"""

import lvgl as lv

STEP_PX = 16
INTERVAL_MS = 30


class Curtain:
    def __init__(self, parent, width, height, color=0x000000):
        self.width = width
        self.half = width // 2
        self.left = lv.obj(parent)
        self.right = lv.obj(parent)
        for panel in (self.left, self.right):
            panel.set_size(self.half, height)
            panel.set_style_bg_color(lv.color_hex(color), 0)
            panel.set_style_bg_opa(lv.OPA.COVER, 0)
            panel.set_style_border_width(0, 0)
            panel.set_style_radius(0, 0)
            panel.set_style_pad_all(0, 0)
        self._progress = 0  # 0 = fully closed, self.half = fully open
        self._timer = None
        self._render()

    def _render(self):
        self.left.set_pos(-self._progress, 0)
        self.right.set_pos(self.half + self._progress, 0)

    def _step(self, opening, on_done):
        self._progress += STEP_PX if opening else -STEP_PX
        self._progress = max(0, min(self.half, self._progress))
        self._render()
        done = self._progress >= self.half if opening else self._progress <= 0
        if done:
            self._timer.delete()
            self._timer = None
            if on_done:
                on_done()

    def open(self, on_done=None):
        self._start(True, on_done)

    def close(self, on_done=None):
        self._start(False, on_done)

    def _start(self, opening, on_done):
        if self._timer:
            self._timer.delete()
        self._timer = lv.timer_create(lambda t: self._step(opening, on_done), INTERVAL_MS, None)

    def delete(self):
        if self._timer:
            self._timer.delete()
            self._timer = None
        self.left.delete()
        self.right.delete()
