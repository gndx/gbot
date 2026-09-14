"""Regression checks for the real display renderer, with no board or Pillow.

Run: python3 -m unittest discover -s tests -v
"""

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("limits_preview", ROOT / "scripts/preview-limits.py")
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


class LimitsTests(unittest.TestCase):
    def setUp(self):
        self.clock = preview.Clock()
        preview.install_shims(self.clock)
        self.renderer = preview.load_renderer(ROOT / "firmware/limits.py")
        self.screen, self.lcd = preview.new_screen(self.renderer)

    def populate(self, windows=None):
        self.screen.set("CLAUDE", windows or [("5H", 84, 9234), ("7D", 96, 604800)])
        self.screen.set("CODEX", [("5H", 63, 2400), ("7D", 72, 326877)])

    def settle(self):
        self.clock.advance(640)
        self.screen.tick()

    def test_provider_updates_preserve_other_account_and_selected_page(self):
        self.populate()
        self.screen.select("1")
        self.screen.set("CLAUDE", [("5H", 7, None)])
        self.assertEqual(self.screen.lines(), ["CLAUDE 5H,7", "CODEX 5H,63 7D,72"])
        self.assertEqual(self.screen.page, 1)
        self.assertIn("CLAUDE:5H,7,-1", self.screen.report())
        self.assertEqual(self.screen.next_page(), 0)

    def test_weekly_reset_survives_tick_wraparound(self):
        self.clock.now = self.clock.period - 200
        self.screen.set("CODEX", [("7D", 100, 604800), ("5H", 50, None)])
        self.clock.advance(1200)
        self.assertIn("CODEX:7D,100,604799;5H,50,-1", self.screen.report())
        self.assertEqual(self.screen.pages[0].age, 1)

    def test_enter_reuses_band_and_matches_full_render(self):
        self.populate()
        band = self.screen.buf
        self.screen.enter(None)
        self.assertIs(self.screen.buf, band)
        self.assertLessEqual(len(band), 39424)
        self.assertEqual(self.lcd.blits, [(0, 0, 240, 82), (0, 82, 240, 82),
                                         (0, 164, 240, 76)])
        expected = bytearray(240 * 240 * 2)
        fb = preview.FrameBuffer(expected, 240, 240, preview.RGB565)
        fb.fill(self.renderer._BG)
        self.screen._render(fb, 0, 240)
        self.assertEqual(self.lcd.data, expected)

    def test_zero_and_full_bars_represent_actual_percent_after_intro(self):
        self.populate([("5H", 0, 9234), ("7D", 100, 604800)])
        self.screen.enter(None)
        self.settle()
        fb = preview.FrameBuffer(self.lcd.data, 240, 240, preview.RGB565)
        for row, color in ((0, self.renderer._TRACK), (1, self.screen._bar_color)):
            y = self.renderer._row_y(2, row) + 1
            for x in range(self.renderer._BAR_X, self.renderer._BAR_X + self.renderer._BAR_W):
                self.assertEqual(fb.pixel(x, y), color, (row, x))

    def test_animation_keeps_spi_work_small_and_never_repaints_whole_screen(self):
        self.populate([("5H", 96, 9234), ("7D", 100, 604800), ("7DS", 98, None)])
        self.screen.enter(None)
        for _ in range(90):
            self.lcd.blits.clear()
            self.clock.advance(64)
            self.screen.tick()
            self.assertTrue(all(height <= 16 for _, _, _, height in self.lcd.blits))
            self.assertLessEqual(sum(width * height * 2 for _, _, width, height
                                     in self.lcd.blits), 12000)

    def test_repeated_pulse_does_not_leave_marks_or_change_other_content(self):
        self.screen.set("CLAUDE", [("5H", 50, None)])
        self.screen.enter(None)
        self.settle()
        before = bytes(self.lcd.data)
        for _ in range(80):
            self.clock.advance(120)
            self.screen.tick()
        left = self.screen._pulse_x - 5
        for y in range(240):
            for x in range(240):
                if 40 <= y < 51 and left <= x < left + 11:
                    continue
                offset = (y * 240 + x) * 2
                self.assertEqual(self.lcd.data[offset:offset + 2], before[offset:offset + 2],
                                 (x, y))

    def test_old_data_is_visibly_stale_and_stops_pulsing(self):
        self.populate()
        self.screen.enter(None)
        self.clock.advance(301000)
        self.screen.tick()
        self.assertTrue(self.screen._stale)
        self.assertEqual(self.screen._fill, 1.0)
        self.lcd.blits.clear()
        self.clock.advance(120)
        self.screen.tick()
        self.assertEqual(self.lcd.blits, [])

    def test_empty_and_clear_render_without_provider_data(self):
        self.screen.enter(None)
        self.assertEqual(self.screen.report(), "limits=0")
        self.populate()
        self.screen.clear()
        self.screen.tick()
        self.assertEqual(self.screen.report(), "limits=0")

    def test_wide_labels_and_three_rows_stay_inside_round_panel(self):
        self.screen.set("WWWWWWWW", [("WWWW", 100, None), ("MMMM", 100, None),
                                      ("8888", 100, None)])
        self.screen.enter(None)
        self.settle()
        fb = preview.FrameBuffer(self.lcd.data, 240, 240, preview.RGB565)
        for y in range(240):
            for x in range(240):
                if (x - 119.5) ** 2 + (y - 119.5) ** 2 > 120 ** 2:
                    self.assertEqual(fb.pixel(x, y), self.renderer._BG, (x, y))


if __name__ == "__main__":
    unittest.main()
