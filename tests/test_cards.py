"""Real pixel checks for face cards and all four availability rings."""

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cards_preview", ROOT / "scripts/preview-cards.py")
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


class CardPixelsTests(unittest.TestCase):
    def setUp(self):
        self.modules = preview.environment()
        self.clock, self.face_module, self.palette, self.renderer = self.modules

    def assert_only_band_blits(self, lcd):
        for x, y, width, height in lcd.blits:
            self.assertGreaterEqual(x, self.face_module.BAND_X)
            self.assertGreaterEqual(y, self.face_module.BAND_Y)
            self.assertLessEqual(x + width, self.face_module.BAND_X + self.face_module.BAND_W)
            self.assertLessEqual(y + height, self.face_module.BAND_Y + self.face_module.BAND_H)

    def test_repeated_state_command_changes_expression_and_animates_same_ring(self):
        for state in ("open", "await", "hold", "busy"):
            with self.subTest(state=state):
                clock, face, screen, lcd = preview.setup(state, self.modules)
                previous = face.mood
                ring = preview.outside_band(lcd.data)
                face.request(state)
                frames = set()
                blink_seen = False
                for _ in range(18):
                    clock.advance(33)
                    face.tick()
                    frames.add(bytes(lcd.data))
                    blink_seen = blink_seen or max(face.blink) > 0.8
                self.assertNotEqual(face.mood, previous)
                self.assertEqual(face.name, state)
                self.assertIsNone(face.pending)
                self.assertTrue(blink_seen)
                self.assertGreater(len(frames), 3)
                self.assertEqual(preview.outside_band(lcd.data), ring)

    def test_every_card_keeps_each_state_ring_and_all_surrounding_pixels(self):
        for state in ("open", "await", "hold", "busy"):
            with self.subTest(state=state):
                clock, face, screen, lcd = preview.setup(state, self.modules)
                preview.sample_data(screen)
                baseline = preview.outside_band(lcd.data, self.face_module)
                framebuffer = preview.base.FrameBuffer(lcd.data, 240, 240, preview.base.RGB565)
                # (120, 8) is radius 112, in the real palette's solid ring.
                from gc9a01 import rgb565
                self.assertEqual(framebuffer.pixel(120, 8), rgb565(*face.pal["ring"]))
                for kind in ("CLAUDE", "CODEX", "WEATHER"):
                    with self.subTest(card=kind):
                        lcd.blits.clear()
                        screen.enter_card(kind, face.pal)
                        for _ in range(8):
                            clock.advance(1000)
                            screen.tick_card()
                        screen.leave_card()
                        self.assertEqual(preview.outside_band(lcd.data, self.face_module), baseline)
                        self.assert_only_band_blits(lcd)
                        self.assertEqual(framebuffer.pixel(120, 8), rgb565(*face.pal["ring"]))

    def test_cards_share_actual_eye_buffer_and_keep_account_selection(self):
        clock, face, screen, lcd = preview.setup("await", self.modules)
        preview.sample_data(screen)
        screen.select("1")
        original = screen.report()
        original_buffer = face.band
        for kind in ("CLAUDE", "WEATHER", "CODEX"):
            screen.enter_card(kind, face.pal)
            screen.tick_card()
            screen.leave_card()
        self.assertIs(screen.buf, original_buffer)
        self.assertEqual(len(screen.buf), 176 * 112 * 2)
        self.assertEqual(screen.page, 1)
        self.assertEqual(screen.report(), original)

    def test_zero_ten_and_full_percent_render_distinctly_without_touching_ring(self):
        for kind in ("CLAUDE", "CODEX"):
            clock, face, screen, lcd = preview.setup("busy", self.modules)
            ring = preview.outside_band(lcd.data)
            snapshots = []
            for percent in (0, 10, 100):
                preview.sample_data(screen, percent)
                screen.enter_card(kind, face.pal)
                clock.advance(640)
                screen.tick_card()
                snapshots.append(bytes(lcd.data))
                self.assertEqual(preview.outside_band(lcd.data), ring)
                screen.leave_card()
            self.assertEqual(len(set(snapshots)), 3)

    def test_weather_update_changes_visible_temperature_inside_band(self):
        clock, face, screen, lcd = preview.setup("hold", self.modules)
        preview.sample_data(screen)
        ring = preview.outside_band(lcd.data)
        screen.enter_card("WEATHER", face.pal)
        before = bytes(lcd.data)
        screen.set_weather(189, 61, 92, 1788977700)
        clock.advance(1000)
        screen.tick_card()
        self.assertNotEqual(bytes(lcd.data), before)
        self.assertEqual(preview.outside_band(lcd.data), ring)

    def test_leaving_card_clears_whole_center_before_small_eyes_return(self):
        clock, face, screen, lcd = preview.setup("open", self.modules)
        preview.sample_data(screen)
        ring = preview.outside_band(lcd.data)
        screen.enter_card("WEATHER", face.pal)
        screen.leave_card()
        framebuffer = preview.base.FrameBuffer(lcd.data, 240, 240, preview.base.RGB565)
        for y in range(60, 172):
            for x in range(32, 208):
                self.assertEqual(framebuffer.pixel(x, y), 0, (x, y))
        self.assertEqual(preview.outside_band(lcd.data), ring)

    def test_fresh_weather_joins_rotation_and_expired_weather_leaves_across_tick_wrap(self):
        self.clock.now = self.clock.period - 1000
        clock, face, screen, lcd = preview.setup("await", self.modules)
        screen.set_weather(256, 3, 68, 1788976800)
        self.assertEqual(screen.card_choices(), ["WEATHER"])
        screen.set("CLAUDE", [("5H", 84, None)])
        self.assertEqual(screen.card_choices(), ["CLAUDE", "WEATHER"])
        clock.advance(900000)
        self.assertIn("stale=0", screen.weather_report())
        self.assertEqual(screen.card_choices(), ["CLAUDE", "WEATHER"])
        clock.advance(1000)
        self.assertIn("stale=1", screen.weather_report())
        self.assertEqual(screen.card_choices(), ["CLAUDE"])
        clock.advance(1800000)
        self.assertEqual(screen.card_choices(), ["CLAUDE"])
        self.assertIn("age=2701 stale=1", screen.weather_report())
        screen.set_weather(240, 2, 76, 1788978600)
        self.assertEqual(screen.card_choices(), ["CLAUDE", "WEATHER"])
        self.assertIn("age=0 stale=0", screen.weather_report())

    def test_titles_and_digital_values_are_centered_and_share_brand_color(self):
        from gc9a01 import rgb565
        for kind in ("CLAUDE", "CODEX", "WEATHER"):
            for value in (0, 1, 20, 100):
                with self.subTest(kind=kind, value=value):
                    clock, face, screen, lcd = preview.setup("await", self.modules)
                    preview.sample_data(screen, value)
                    screen.enter_card(kind, face.pal)
                    fb = preview.base.FrameBuffer(lcd.data, 240, 240, preview.base.RGB565)
                    color = (self.renderer._WEATHER_COLOR if kind == "WEATHER"
                             else self.renderer.BRANDS[kind])
                    for first_y, last_y in ((60, 100), (100, 172)):
                        pixels = [(x, y, fb.pixel(x, y))
                                  for y in range(first_y, last_y) for x in range(32, 208)
                                  if fb.pixel(x, y)]
                        self.assertTrue(pixels)
                        left, right = min(p[0] for p in pixels), max(p[0] for p in pixels)
                        self.assertLessEqual(abs((left + right) / 2 - 119.5), 0.5)
                        self.assertIn(rgb565(*color), [p[2] for p in pixels])
                        self.assertGreater(left, 32)
                        self.assertLess(right, 207)

    def test_weather_mini_has_only_city_and_temperature(self):
        clock, face, screen, lcd = preview.setup("await", self.modules)
        screen.set_weather(200, 0, 10, 1788976800)
        screen.enter_card("WEATHER", face.pal)
        before = bytes(lcd.data)
        screen.set_weather(200, 95, 100, 1788978600)
        screen.tick_card()
        self.assertEqual(bytes(lcd.data), before)

    def test_stale_usage_keeps_its_brand_hue_instead_of_turning_gray(self):
        from gc9a01 import rgb565
        for kind in ("CLAUDE", "CODEX"):
            clock, face, screen, lcd = preview.setup("busy", self.modules)
            preview.sample_data(screen, 20)
            screen.enter_card(kind, face.pal)
            fresh = bytes(lcd.data)
            clock.advance(301000)
            screen.tick_card()
            fb = preview.base.FrameBuffer(lcd.data, 240, 240, preview.base.RGB565)
            dim_brand = rgb565(*(channel * 3 // 4 for channel in self.renderer.BRANDS[kind]))
            self.assertNotEqual(bytes(lcd.data), fresh)
            self.assertIn(dim_brand, [fb.pixel(x, y) for y in range(107, 155)
                                     for x in range(32, 208)])

    def test_missing_data_has_no_automatic_cards_or_invented_percent(self):
        clock, face, screen, lcd = preview.setup("busy", self.modules)
        self.assertEqual(screen.card_choices(), [])
        self.assertIn("available=0", screen.weather_report())
        ring = preview.outside_band(lcd.data)
        screen.enter_card("LIMITS", face.pal)
        missing = bytes(lcd.data)
        screen.set("CLAUDE", [("5H", 0, None)])
        screen.enter_card("CLAUDE", face.pal)
        self.assertNotEqual(bytes(lcd.data), missing)
        self.assertEqual(screen.card_choices(), ["CLAUDE"])
        self.assertEqual(preview.outside_band(lcd.data), ring)

    def test_all_eighteen_expressions_remain_drawable_after_card_and_repaint(self):
        seen = set()
        for state in ("open", "await", "hold", "busy"):
            clock, face, screen, lcd = preview.setup(state, self.modules)
            preview.sample_data(screen)
            ring = preview.outside_band(lcd.data)
            for mood in face.pal["exprs"]:
                with self.subTest(state=state, mood=mood):
                    preview.pose(face, mood, clock)
                    expected = bytes(lcd.data)
                    screen.enter_card("CLAUDE", face.pal)
                    screen.leave_card()
                    face.repaint()
                    preview.pose(face, mood, clock)
                    self.assertEqual(bytes(lcd.data), expected)
                    self.assertEqual(preview.outside_band(lcd.data), ring)
                    seen.add(mood)
        self.assertEqual(seen, set(self.palette.EXPRESSIONS))
        self.assertEqual(len(seen), 18)


if __name__ == "__main__":
    unittest.main()
