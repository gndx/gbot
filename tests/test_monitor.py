"""Exercise USB commands and the face/card scheduler without RP2040 hardware."""

import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, mock_open, patch


ROOT = Path(__file__).resolve().parents[1]


class Clock:
    period = 1 << 20

    def __init__(self):
        self.now = 100

    def ticks_ms(self):
        return self.now

    def ticks_diff(self, a, b):
        return (a - b + self.period // 2) % self.period - self.period // 2

    def ticks_add(self, a, b):
        return (a + b) % self.period

    def advance(self, milliseconds):
        self.now = self.ticks_add(self.now, milliseconds)


def load_monitor(clock, events):
    class Display:
        def __init__(self):
            self.rot = 0
            self.level = 1

        def rotation(self, rotation):
            self.rot = rotation

        def backlight(self, level):
            self.level = level

        def sleep(self):
            events.append("sleep")

        def wake(self):
            events.append("wake")

    class Face:
        def __init__(self, lcd, states, exprs, name):
            self.states = states
            self.name = name
            self.pending = None
            self.pal = states[name]
            self.mood = self.pal["exprs"][0]
            self.gain = 1
            self.band = bytearray()
            self.fb = None
            self.dirty = None
            self.repaint()

        def repaint(self):
            events.append("face.repaint")

        def request(self, state):
            self.pending = state

        def _apply(self, state):
            self.name = state
            self.pending = None
            self.pal = self.states[state]
            self.mood = self.pal["exprs"][0]
            self.repaint()

        def _breath(self, now):
            return 0.7

        def tick(self):
            if self.pending:
                self._apply(self.pending)
            events.append("face.tick")

    class Limits:
        def __init__(self, lcd, band, fb):
            self.pages = []
            self.page = 0
            self.weather = None
            self.trm = None

        def set(self, title, groups):
            title = title.upper()
            for page in self.pages:
                if page.title == title:
                    page.groups = groups
                    return len(groups)
            self.pages.append(types.SimpleNamespace(title=title, groups=groups))
            return len(groups)

        def stale_all(self):
            pass

        def clear(self):
            self.pages = []
            self.page = 0

        def select(self, index):
            if self.pages:
                self.page = ((self.page + 1) if index == "next" else int(index)) % len(self.pages)
            return self.page

        def card_choices(self):
            choices = [p.title for p in self.pages if p.title in ("CLAUDE", "CODEX")]
            if self.weather:
                choices.append("WEATHER")
            return choices

        def enter_card(self, kind, pal):
            events.append("card.enter:" + kind)

        def tick_card(self):
            events.append("card.tick")

        def leave_card(self):
            events.append("card.leave")

        def enter(self, pal):
            events.append("limits.enter")

        def tick(self):
            events.append("limits.tick")

        def refresh(self):
            events.append("limits.refresh")

        def enter_weather(self, pal):
            events.append("weather.enter")

        def tick_weather(self):
            events.append("weather.tick")

        def report(self):
            return "limits=%d" % len(self.pages)

        def set_weather(self, temp, code, humidity, epoch):
            if not (-1000 <= temp <= 1000 and 0 <= code <= 99
                    and 0 <= humidity <= 100 and epoch > 0):
                raise ValueError("invalid weather")
            self.weather = (temp, code, humidity, epoch)

        def weather_report(self):
            if self.weather is None:
                return "source=host weather=none"
            return "source=host temp_tenths=%d code=%d humidity=%d observed_at=%d" % self.weather

        def set_trm(self, cents, start, end, left):
            if cents <= 0 or start > end or left <= 0:
                raise ValueError("invalid trm")
            self.trm = (cents, start, end, left)

        def trm_report(self):
            return "source=host available=%d" % bool(self.trm)

        def enter_trm(self, pal):
            events.append("trm.enter")

        def tick_trm(self):
            events.append("trm.tick")

        def set_calendar(self, clock, title):
            self.calendar = (clock, title)

        def enter_calendar(self, pal):
            events.append("calendar.enter")

        def tick_calendar(self):
            events.append("calendar.tick")

    class Hud:
        def __init__(self, *args):
            pass

        def enter(self, pal):
            events.append("hud.enter")

        def tick(self, *args):
            events.append("hud.tick")

    class Sensors:
        def accel(self):
            return 0.0, 0.0, 1.0

        def chip_temp(self):
            return 35.5

        def voltage(self):
            return 4.8

    class Link:
        def __init__(self):
            self.lines = []

        def send(self, line):
            self.lines.append(line)

    palette_spec = importlib.util.spec_from_file_location("monitor_palette", ROOT / "firmware/palette.py")
    palette = importlib.util.module_from_spec(palette_spec)
    palette_spec.loader.exec_module(palette)
    modules = {
        "gc": types.SimpleNamespace(collect=lambda: None, mem_free=lambda: 90000),
        "time": clock,
        "rp2": types.SimpleNamespace(bootsel_button=lambda: False),
        "palette": palette,
        "gc9a01": types.SimpleNamespace(Display=Display),
        "face": types.SimpleNamespace(Face=Face),
        "limits": types.SimpleNamespace(Limits=Limits),
        "hud": types.SimpleNamespace(Hud=Hud),
        "sensors": types.SimpleNamespace(Sensors=Sensors),
        "link": types.SimpleNamespace(Link=Link),
    }
    spec = importlib.util.spec_from_file_location("monitor_under_test", ROOT / "firmware/main.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", modules):
        spec.loader.exec_module(module)
    return module


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.events = []
        self.module = load_monitor(self.clock, self.events)
        self.original_load_state = self.module.load_state
        self.module.load_state = Mock(return_value=("await", 0, "face"))
        self.module.load_limits = Mock(return_value=[])
        self.module.save_state = Mock()
        self.module.save_limits = Mock()
        self.monitor = self.module.Monitor()
        self.events.clear()

    def populate(self):
        self.monitor._limits(["CLAUDE", "5H,82,1234"])
        self.monitor._limits(["CODEX", "5H,67,2345"])

    def frame(self, milliseconds=0):
        self.clock.advance(milliseconds)
        self.monitor._tick_scene(self.clock.ticks_ms(), 2)

    def test_boot_restores_state_and_rotation_but_always_returns_to_eyes(self):
        for persisted_view in ("limits", "weather", "trm", "hud", "face"):
            with self.subTest(view=persisted_view):
                with patch("builtins.open", mock_open(read_data="hold 3 " + persisted_view)):
                    state = self.original_load_state()
                self.assertEqual(state, ("hold", 3, "face"))
                self.module.load_state.return_value = state
                monitor = self.module.Monitor()
                self.assertEqual((monitor.face.name, monitor.lcd.rot, monitor.view),
                                 ("hold", 3, "face"))
                self.assertIsNone(monitor.card)

    def test_every_state_command_restores_eyes_from_every_data_view(self):
        self.populate()
        for view in ("limits", "weather", "trm", "hud"):
            for state in self.module.palette.CYCLE:
                with self.subTest(view=view, state=state):
                    self.monitor.set_view(view)
                    self.monitor.face.gain = 0.35
                    self.monitor.lcd.rot = 3
                    self.monitor.handle(state)
                    self.frame()
                    self.assertEqual(self.monitor.view, "face")
                    self.assertIsNone(self.monitor.card)
                    self.assertEqual(self.monitor.face.name, state)
                    self.assertEqual(self.monitor.scene_ms, 0)
                    self.assertEqual(self.monitor.face.gain, 0.35)
                    self.assertEqual(self.monitor.lcd.rot, 3)
                    self.module.save_state.assert_called_with(state, 3, "face")

    def test_auto_cards_wait_45_seconds_stay_8_and_do_not_change_the_state(self):
        self.populate()
        for state in self.module.palette.CYCLE:
            with self.subTest(state=state), patch.object(self.module.random, "randint", return_value=0):
                self.monitor.go(state)
                self.frame()
                self.events.clear()
                self.frame(44999)
                self.assertIsNone(self.monitor.card)
                self.frame(1)
                first = self.monitor.card
                self.assertIn(first, ("CLAUDE", "CODEX"))
                self.assertEqual(self.monitor.view, "face")
                self.assertEqual(self.monitor.face.name, state)
                self.frame(7999)
                self.assertEqual(self.monitor.card, first)
                self.frame(1)
                self.assertIsNone(self.monitor.card)
                self.assertEqual(self.monitor.view, "face")
                self.assertEqual(self.monitor.face.name, state)
                self.assertEqual(self.monitor.face.dirty, (0, 111))
                self.frame(45000)
                self.assertNotEqual(self.monitor.card, first)
                self.assertNotIn("face.repaint", self.events)
        # User state commands persist; automatic card transitions never do.
        self.assertEqual(self.module.save_state.call_count, len(self.module.palette.CYCLE))

    def test_time_wraparound_and_many_cycles_keep_the_same_durations(self):
        self.populate()
        self.clock.now = self.clock.period - 1000
        self.monitor.set_view("face")
        for _ in range(25):
            self.frame(44999)
            self.assertIsNone(self.monitor.card)
            self.frame(1)
            self.assertIsNotNone(self.monitor.card)
            self.frame(7999)
            self.assertIsNotNone(self.monitor.card)
            self.frame(1)
            self.assertIsNone(self.monitor.card)

    def test_sleep_pauses_remaining_eye_and_card_time(self):
        self.populate()
        self.frame(20000)
        self.monitor.sleep()
        self.frame(60000)
        self.assertEqual(self.monitor.scene_ms, 20000)
        self.monitor.wake()
        self.frame(24999)
        self.assertIsNone(self.monitor.card)
        self.frame(1)
        selected = self.monitor.card
        self.frame(3000)
        self.monitor.sleep()
        self.frame(60000)
        self.monitor.wake()
        self.frame(4999)
        self.assertEqual(self.monitor.card, selected)
        self.frame(1)
        self.assertIsNone(self.monitor.card)

    def test_command_wakes_and_resets_a_sleeping_card_to_full_eye_interval(self):
        self.populate()
        self.frame(45000)
        self.assertIsNotNone(self.monitor.card)
        self.monitor.sleep()
        self.clock.advance(60000)
        self.monitor.handle("hold")
        self.assertFalse(self.monitor.asleep)
        self.assertEqual(self.monitor.view, "face")
        self.assertIsNone(self.monitor.card)
        self.frame(44999)
        self.assertIsNone(self.monitor.card)
        self.frame(1)
        self.assertIsNotNone(self.monitor.card)

    def test_no_data_keeps_animating_eyes_and_new_data_does_not_interrupt(self):
        for _ in range(4):
            self.frame(60000)
            self.assertIsNone(self.monitor.card)
        self.monitor.set_view("face")
        self.frame(10000)
        self.populate()
        self.monitor._weather(["set", "235", "3", "72", "1788900000"])
        self.assertEqual(self.monitor.view, "face")
        self.assertEqual(self.monitor.scene_ms, 10000)
        self.frame(34999)
        self.assertIsNone(self.monitor.card)
        with patch.object(self.module.random, "randint", return_value=2):
            self.frame(1)
        self.assertEqual(self.monitor.card, "WEATHER")

    def test_provider_mini_card_dismisses_and_page_updates_do_not_change_it(self):
        self.populate()
        with patch.object(self.module.random, "randint", return_value=1):
            self.frame(45000)
        self.assertEqual(self.monitor.card, "CODEX")
        self.assertEqual(self.monitor.view, "face")
        self.events.clear()
        self.monitor.face.gain = 0.4
        self.frame(4000)
        self.assertNotIn("face.tick", self.events)
        self.assertIn("card.tick", self.events)
        self.assertAlmostEqual(self.monitor.lcd.level, 0.28)
        self.monitor._limits(["page", "0"])
        self.monitor._limits(["CLAUDE", "5H,75,2000"])
        self.monitor._limits(["CODEX", "5H,52,2000"])
        self.assertEqual(self.monitor.card, "CODEX")
        self.assertEqual(self.monitor.scene_ms, 4000)
        self.monitor.handle("status")
        self.assertIn("card=CODEX face_ms=0 card_ms=4000", self.monitor.link.lines[-1])
        self.frame(4000)
        self.assertIsNone(self.monitor.card)
        self.assertIn("face.tick", self.events)
        self.assertFalse(self.module.save_state.called)

    def test_data_views_return_to_same_state_after_exactly_one_visible_minute(self):
        self.populate()
        self.monitor._limits(["page", "1"])
        for state in self.module.palette.CYCLE:
            for view in ("limits", "weather", "trm"):
                with self.subTest(state=state, view=view):
                    self.monitor.go(state)
                    # Abrir inmediatamente debe conservar incluso el estado
                    # que todavia espera al siguiente parpadeo para aplicarse.
                    original_face = self.monitor.face
                    self.monitor.face.gain = 0.4
                    self.monitor.lcd.rot = 2
                    self.monitor.handle("view " + view)
                    self.module.save_state.reset_mock()
                    self.frame(59999)
                    self.assertEqual(self.monitor.view, view)
                    self.assertEqual(self.monitor.scene_ms, 59999)
                    self.frame(1)
                    self.assertEqual(self.monitor.view, "face")
                    self.assertIsNone(self.monitor.card)
                    self.assertIs(self.monitor.face, original_face)
                    self.assertEqual(self.monitor.face.name, state)
                    self.assertEqual(self.monitor.face.gain, 0.4)
                    self.assertEqual(self.monitor.lcd.rot, 2)
                    self.assertEqual(self.monitor.limits.page, 1)
                    self.assertEqual(self.monitor.scene_ms, 0)
                    self.module.save_state.assert_not_called()
                    self.frame(44999)
                    self.assertIsNone(self.monitor.card)
                    self.frame(1)
                    self.assertIsNotNone(self.monitor.card)

    def test_data_timer_pauses_in_sleep_and_wraps_and_ignores_repaint(self):
        self.clock.now = self.clock.period - 1000
        self.monitor.set_view("trm")
        self.frame(20000)
        self.monitor.handle("rotate 3")
        self.monitor.handle("bright 50")
        self.monitor.sleep()
        self.frame(120000)
        self.monitor.wake()
        self.frame(39999)
        self.assertEqual(self.monitor.view, "trm")
        self.frame(1)
        self.assertEqual(self.monitor.view, "face")
        self.assertEqual(self.monitor.face.name, "await")

    def test_opening_another_view_or_manually_selecting_a_page_restarts_minute(self):
        self.populate()
        self.monitor.set_view("weather")
        self.frame(50000)
        self.monitor.set_view("limits")
        self.frame(40000)
        self.monitor.handle("limits page 1")
        self.frame(59999)
        self.assertEqual(self.monitor.view, "limits")
        self.frame(1)
        self.assertEqual(self.monitor.view, "face")

    def test_long_press_cycles_all_data_views_then_hud_and_face_without_changing_state(self):
        self.populate()
        expected = (("limits", 0), ("limits", 1), ("weather", 1),
                    ("trm", 1), ("hud", 1), ("face", 1))
        for view, page in expected:
            self.monitor.handle("press long")
            self.assertEqual((self.monitor.view, self.monitor.limits.page), (view, page))
            self.assertEqual(self.monitor.face.name, "await")
            self.frame(1000)
        # Physical press and the CLI diagnostic share next_view().
        for presses in (1, 2, 3, 4):
            self.monitor.set_view("face")
            for _ in range(presses):
                self.monitor.next_view(announce=True)
            self.frame(59999)
            self.assertNotEqual(self.monitor.view, "face")
            self.frame(1)
            self.assertEqual(self.monitor.view, "face")
            self.assertEqual(self.monitor.face.name, "await")

    def test_diagnostic_view_is_manual_and_missing_accounts_are_skipped_by_button(self):
        self.monitor.handle("press long")
        self.assertEqual(self.monitor.view, "weather")
        self.monitor.set_view("hud")
        self.frame(120000)
        self.assertEqual(self.monitor.view, "hud")

    def test_full_view_to_eyes_to_mini_to_full_view_clears_only_the_correct_region(self):
        self.populate()
        self.monitor.set_view("limits")
        self.events.clear()
        self.monitor.set_view("face")
        self.assertEqual(self.events, ["face.repaint"])
        self.events.clear()
        with patch.object(self.module.random, "randint", return_value=0):
            self.frame(45000)
        self.assertEqual(self.events, ["card.enter:CLAUDE", "card.tick"])
        self.assertEqual(self.monitor.view, "face")
        self.events.clear()
        self.monitor.set_view("weather")
        self.assertEqual(self.events, ["card.leave", "weather.enter"])
        self.assertIsNone(self.monitor.card)
        self.frame(10000)
        self.assertEqual(self.monitor.view, "weather")
        self.events.clear()
        self.monitor.set_view("face")
        self.assertEqual(self.events, ["face.repaint"])
        self.frame(44999)
        self.assertIsNone(self.monitor.card)
        self.frame(1)
        self.assertEqual(self.monitor.card, "CODEX")
        self.assertEqual(self.monitor.view, "face")

    def test_manual_limits_page_refreshes_dashboard_and_feed_preserves_selected_page(self):
        self.populate()
        self.monitor.set_view("limits")
        self.events.clear()
        self.monitor._limits(["page", "1"])
        self.assertEqual(self.events, ["limits.refresh"])
        self.assertEqual(self.monitor.limits.page, 1)
        self.frame(20000)
        self.monitor._limits(["CLAUDE", "5H,75,2000"])
        self.monitor._limits(["CODEX", "5H,52,2000"])
        self.monitor._weather(["set", "235", "3", "72", "1788900000"])
        self.frame(39999)
        self.assertEqual(self.monitor.view, "limits")
        self.assertIsNone(self.monitor.card)
        self.assertEqual(self.monitor.limits.page, 1)
        self.assertEqual(self.events, ["limits.refresh", "limits.tick", "limits.tick"])
        self.frame(1)
        self.assertEqual(self.monitor.view, "face")

    def test_short_press_cycles_actual_state_from_cards_instead_of_resetting_to_open(self):
        self.populate()
        self.monitor.go("await")
        self.frame()
        self.monitor.set_view("limits")
        self.monitor.handle("press short")
        self.frame()
        self.assertEqual(self.monitor.face.name, "hold")
        self.assertEqual(self.monitor.view, "face")
        self.assertIsNone(self.monitor.card)
        self.monitor.go("busy")
        self.frame()
        self.monitor.handle("press short")
        self.frame()
        self.assertEqual(self.monitor.face.name, "open")
        self.assertEqual(self.monitor.view, "face")

    def test_weather_protocol_validates_data_does_not_switch_view_and_has_manual_dashboard(self):
        self.monitor.handle("weather")
        self.assertEqual(self.monitor.link.lines[-1], "ok source=host weather=none")
        self.monitor.handle("weather set 235 3 72 1788900000")
        self.assertIn("temp_tenths=235", self.monitor.link.lines[-1])
        self.assertEqual(self.monitor.view, "face")
        for command in ("weather set", "weather set bad 3 72 1788900000",
                        "weather set 235 3 101 1788900000"):
            self.monitor.handle(command)
            self.assertTrue(self.monitor.link.lines[-1].startswith("err weather"))
            self.assertEqual(self.monitor.limits.weather, (235, 3, 72, 1788900000))
        self.monitor.handle("view weather")
        self.assertIsNone(self.monitor.card)
        self.frame(59999)
        self.assertEqual(self.monitor.view, "weather")

    def test_clear_limits_leaves_usage_card_but_keeps_weather_and_eye_scene(self):
        self.populate()
        self.frame(45000)
        self.assertIsNotNone(self.monitor.card)
        self.monitor.handle("limits clear")
        self.assertEqual(self.monitor.view, "face")
        self.assertIsNone(self.monitor.card)
        self.monitor._weather(["set", "235", "3", "72", "1788900000"])
        self.frame(45000)
        self.assertEqual(self.monitor.card, "WEATHER")
        self.monitor.handle("limits clear")
        self.assertEqual(self.monitor.card, "WEATHER")
        self.monitor.set_view("limits")
        self.events.clear()
        self.monitor.handle("limits clear")
        self.assertEqual(self.monitor.view, "limits")
        self.assertEqual(self.events, ["limits.refresh"])

    def test_rotation_status_and_manual_empty_dashboard_keep_protocol_working(self):
        self.monitor.handle("view limits")
        self.assertIsNone(self.monitor.card)
        self.events.clear()
        self.monitor.handle("rotate 3")
        self.assertEqual(self.events, ["limits.enter"])
        self.assertEqual(self.monitor.link.lines[-1], "ok rotate=3")
        self.monitor.handle("status")
        self.assertIn("state=await", self.monitor.link.lines[-1])
        self.assertIn("view=limits", self.monitor.link.lines[-1])
        self.assertIn("card=none face_ms=0 card_ms=0", self.monitor.link.lines[-1])
        self.monitor.handle("view face")
        self.monitor.handle("status")
        self.assertIn("card=none", self.monitor.link.lines[-1])

    def test_trm_protocol_updates_without_entering_face_rotation(self):
        self.monitor.handle("trm set 311647 20260909 20260909 86400")
        self.assertIn("available=1", self.monitor.link.lines[-1])
        self.assertEqual(self.monitor.view, "face")
        for command in ("trm set", "trm set nan 20260909 20260909 100",
                        "trm set -1 20260909 20260909 100"):
            self.monitor.handle(command)
            self.assertTrue(self.monitor.link.lines[-1].startswith("err trm"))
        self.frame(60000)
        self.assertIsNone(self.monitor.card)
        self.monitor.handle("view trm")
        self.frame(59999)
        self.assertEqual(self.monitor.view, "trm")
        self.monitor.handle("await")
        self.frame()
        self.assertEqual(self.monitor.view, "face")

    def test_rotation_sleep_and_wake_preserve_each_manual_view_and_mini_card(self):
        self.populate()
        for view in ("limits", "weather", "trm", "hud", "face"):
            with self.subTest(view=view):
                self.monitor.set_view(view)
                self.events.clear()
                self.monitor.handle("rotate 1")
                expected = "face.repaint" if view == "face" else view + ".enter"
                self.assertEqual(self.events, [expected])
                self.monitor.sleep()
                self.clock.advance(60000)
                self.events.clear()
                self.monitor.wake()
                self.assertEqual(self.monitor.view, view)
                self.assertEqual(self.events, ["wake", expected])
        with patch.object(self.module.random, "randint", return_value=0):
            self.frame(45000)
        self.assertEqual(self.monitor.card, "CLAUDE")
        self.events.clear()
        self.monitor.handle("rotate 2")
        self.assertEqual(self.events, ["face.repaint", "card.enter:CLAUDE"])
        self.monitor.sleep()
        self.clock.advance(60000)
        self.events.clear()
        self.monitor.wake()
        self.assertEqual(self.monitor.view, "face")
        self.assertEqual(self.monitor.card, "CLAUDE")
        self.assertEqual(self.events, ["wake", "face.repaint", "card.enter:CLAUDE"])

    def test_temporary_anger_restores_previous_state_without_leaving_a_data_view(self):
        self.populate()
        self.monitor.go("hold")
        self.frame()
        self.monitor.set_view("limits")
        self.monitor.anger()
        self.frame()
        self.assertEqual(self.monitor.face.name, "busy")
        self.assertEqual(self.monitor.view, "face")
        self.clock.advance(self.module.ANGER_MS)
        self.monitor.calm(self.clock.ticks_ms())
        self.frame()
        self.assertEqual(self.monitor.face.name, "hold")
        self.assertEqual(self.monitor.view, "face")

    def test_meeting_alerts_five_minutes_before_and_returns_after_two_minutes(self):
        self.monitor.go("hold")
        self.frame()
        self.monitor.handle("calendar set ab12 301 10:00 Daily sync")
        self.module.save_state.reset_mock()
        self.frame(999)
        self.assertEqual(self.monitor.view, "face")
        self.frame(1)
        self.assertEqual(self.monitor.view, "calendar")
        self.assertEqual(self.monitor.face.name, "hold")
        self.frame(119999)
        self.assertEqual(self.monitor.view, "calendar")
        self.frame(1)
        self.assertEqual(self.monitor.view, "face")
        self.assertEqual(self.monitor.face.name, "hold")
        self.assertIsNone(self.monitor.card)
        self.module.save_state.assert_not_called()

    def test_meeting_updates_and_manual_dismissals_never_repeat_the_same_alert(self):
        for command in ("face", "busy", "view trm", "press long", "press short"):
            with self.subTest(command=command):
                self.setUp()
                self.monitor.handle("calendar set ab12 300 10:00 Daily sync")
                self.frame()
                self.assertEqual(self.monitor.view, "calendar")
                self.frame(60000)
                self.monitor.handle("calendar set ab12 240 10:00 Daily renamed")
                self.assertEqual(self.monitor.scene_ms, 60000)
                # face is a host alias; the raw protocol uses view face.
                self.monitor.handle("view face" if command == "face" else command)
                self.frame()
                selected = self.monitor.view
                self.assertNotEqual(selected, "calendar")
                self.monitor.handle("calendar set ab12 230 10:00 Daily renamed")
                self.frame(1000)
                self.assertEqual(self.monitor.view, selected)

    def test_calendar_cancellation_reschedule_and_invalid_data(self):
        self.monitor.handle("calendar set ab12 300 10:00 Daily sync")
        self.frame()
        self.monitor.handle("calendar clear")
        self.assertEqual(self.monitor.view, "face")
        self.assertIsNone(self.monitor.calendar)
        for command in ("calendar set bad-id 300 10:00 Meeting",
                        "calendar set ab12 -1 10:00 Meeting",
                        "calendar set ab12 300 25:00 Meeting", "calendar set"):
            self.monitor.handle(command)
            self.assertTrue(self.monitor.link.lines[-1].startswith("err"))
            self.assertIsNone(self.monitor.calendar)
        self.monitor.handle("calendar set ab12 290 10:00 Daily sync")
        self.frame()
        self.assertEqual(self.monitor.view, "face")
        self.monitor.handle("calendar set cd34 299 10:10 Daily sync")
        self.frame()
        self.assertEqual(self.monitor.view, "calendar")

    def test_calendar_wrap_sleep_and_early_manual_preview_keep_due_time(self):
        self.clock.now = self.clock.period - 1000
        self.monitor.handle("calendar set ab12 421 10:00 Daily sync")
        self.monitor.handle("view calendar")
        self.frame(120000)
        self.assertEqual(self.monitor.view, "face")
        self.assertNotIn("ab12", self.monitor.calendar_seen)
        self.monitor.sleep()
        self.frame(50000)
        self.assertEqual(self.monitor.view, "face")
        self.monitor.wake()
        self.frame()
        self.assertEqual(self.monitor.view, "calendar")
        self.frame(119999)
        self.assertEqual(self.monitor.view, "calendar")
        self.frame(1)
        self.assertEqual(self.monitor.view, "face")

    def test_temporary_anger_can_end_without_dismissing_meeting(self):
        self.monitor.go("hold")
        self.frame()
        self.monitor.anger()
        self.frame()
        self.monitor.handle("calendar set ab12 300 10:00 Daily sync")
        self.frame()
        self.clock.advance(self.module.ANGER_MS)
        self.monitor.calm(self.clock.ticks_ms())
        self.frame()
        self.assertEqual(self.monitor.view, "calendar")
        self.frame(75000)
        self.assertEqual(self.monitor.view, "face")
        self.assertEqual(self.monitor.face.name, "hold")


if __name__ == "__main__":
    unittest.main()
