"""Regress the English GBOT dashboard layout against reviewed desktop renders."""

import hashlib
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dashboard_preview", ROOT / "scripts/preview-dashboards.py")
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)

# RGB565 outside the main value. Baselines reflect the English GBOT branding
# reviewed in software on 2026-09-14; they do not certify physical LCD behavior.
# Titles, labels, bars, reset times and indicators must remain identical.
APPROVED_USAGE_SURROUNDINGS = {
    "CLAUDE": "560499ebba2ac65bb68e50a047348981dd9fcd41f08b239df929beaa5054dea2",
    "CODEX": "77ed2ec741b7617818bd19761a4a3f7599a003606346cc2db016a5c5c21b8f01",
}


def outside_hero_hash(lcd):
    return hashlib.sha256(lcd.data[:65 * 240 * 2] + lcd.data[125 * 240 * 2:]).hexdigest()


class DashboardTests(unittest.TestCase):
    def test_weather_full_views_keep_everything_outside_the_main_value(self):
        cases = (
            ({}, "c005fe79e2a8c2e095083c0b9151a9adb99440a7fa8dd53fe2ba39c1114faedf"),
            ({"stale": True}, "e34d60484e9c551730a109171df39b8a81877945f0ab563127939c19371c095a"),
            ({"empty": True}, "d28833f23deeef117d86f153c38aaed82c71343b5a0aac7d1cab6bdfebcf044c"),
        )
        for settings, expected in cases:
            with self.subTest(settings=settings):
                _, _, _, lcd = preview.weather(**settings)
                self.assertEqual(outside_hero_hash(lcd), expected)

    def test_usage_full_views_keep_everything_outside_the_main_value(self):
        for brand, expected in APPROVED_USAGE_SURROUNDINGS.items():
            with self.subTest(brand=brand):
                _, _, _, lcd = preview.provider(brand)
                self.assertEqual(outside_hero_hash(lcd), expected)

    def test_weather_content_stays_inside_round_panel(self):
        for settings in ({}, {"code": 95, "temp": -80, "humidity": 100},
                         {"stale": True}, {"empty": True}):
            with self.subTest(settings=settings):
                _, renderer, _, lcd = preview.weather(**settings)
                fb = preview.base.FrameBuffer(lcd.data, 240, 240, preview.base.RGB565)
                for y in range(240):
                    for x in range(240):
                        if (x - 119.5) ** 2 + (y - 119.5) ** 2 > 120 ** 2:
                            self.assertEqual(fb.pixel(x, y), renderer._BG, (x, y))

    def test_weather_strips_match_one_complete_frame_without_text_seams(self):
        clock, renderer, screen, lcd = preview.setup()
        screen.set_weather(256, 3, 68, 1788976800)
        screen.enter_weather(None)
        expected = bytearray(240 * 240 * 2)
        fb = preview.base.FrameBuffer(expected, 240, 240, preview.base.RGB565)
        fb.fill(renderer._BG)
        screen._render_weather(fb, 0, 240, screen._weather_screen_content())
        self.assertEqual(lcd.data, expected)
        self.assertEqual(lcd.blits, [(0, 0, 240, 82), (0, 82, 240, 82),
                                     (0, 164, 240, 76)])

    def test_weather_dashboard_updates_without_changing_saved_account_data(self):
        clock, renderer, screen, lcd = preview.provider("CODEX")
        original = screen.lines()
        buffer = screen.buf
        screen.set_weather(256, 3, 68, 1788976800)
        screen.enter_weather(None)
        before = bytes(lcd.data)
        screen.set_weather(198, 63, 92, 1788977700)
        clock.advance(1000)
        screen.tick_weather()
        self.assertNotEqual(bytes(lcd.data), before)
        self.assertIs(screen.buf, buffer)
        self.assertEqual(screen.lines(), original)
        self.assertEqual(screen.page, 1)
        self.assertTrue(all(height <= renderer.STRIP_H for _, _, _, height in lcd.blits))

    def test_weather_missing_and_stale_are_visibly_different_from_current(self):
        outputs = []
        for settings in ({}, {"empty": True}, {"stale": True}):
            _, _, _, lcd = preview.weather(**settings)
            outputs.append(bytes(lcd.data))
        self.assertEqual(len(set(outputs)), 3)


if __name__ == "__main__":
    unittest.main()
