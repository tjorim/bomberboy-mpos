import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bomberboy"))


class FakeLightsManager:
    leds = [(0, 0, 0)] * 5
    set_calls = 0
    write_calls = 0

    @classmethod
    def reset(cls):
        cls.leds = [(0, 0, 0)] * 5
        cls.set_calls = 0
        cls.write_calls = 0

    @staticmethod
    def is_available():
        return True

    @classmethod
    def get_led_count(cls):
        return len(cls.leds)

    @classmethod
    def set_led(cls, index, red, green, blue):
        cls.set_calls += 1
        cls.leds[index] = (red, green, blue)

    @classmethod
    def write(cls):
        cls.write_calls += 1

    @classmethod
    def clear(cls):
        cls.leds = [(0, 0, 0)] * len(cls.leds)


sys.modules.setdefault("mpos", types.SimpleNamespace(LightsManager=FakeLightsManager))

import led_indicator


class LedIndicatorCachingTests(unittest.TestCase):
    def setUp(self):
        FakeLightsManager.reset()
        led_indicator.LightsManager = FakeLightsManager
        led_indicator._last_state = None

    def test_unchanged_lives_do_not_rewrite_the_strip(self):
        led_indicator.update(3, 3, 3, 3)
        first_set_calls = FakeLightsManager.set_calls
        first_write_calls = FakeLightsManager.write_calls

        led_indicator.update(3, 3, 3, 3)

        self.assertEqual(FakeLightsManager.set_calls, first_set_calls)
        self.assertEqual(FakeLightsManager.write_calls, first_write_calls)

    def test_changed_lives_refresh_the_strip(self):
        led_indicator.update(3, 3, 3, 3)
        led_indicator.update(2, 3, 3, 3)

        self.assertEqual(FakeLightsManager.write_calls, 2)


if __name__ == "__main__":
    unittest.main()
