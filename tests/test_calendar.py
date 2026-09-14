"""Calendario local: datos, protocolo, permisos y render sin usar eventos reales."""
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("gbot_calendar_tests", str(ROOT / "cli/gbot"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)
spec = importlib.util.spec_from_file_location("calendar_preview", ROOT / "scripts/preview-dashboards.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)
NOW = 1800000000
EVENT = {"id": "apple-event-id", "start": NOW + 3600, "time": "10:00", "title": "Daily sync"}


class CalendarCliTests(unittest.TestCase):
    def fetch(self, event):
        with patch.object(cli, "calendar_settings", return_value={"enabled": True}), \
                patch.object(cli, "calendar_reader", return_value=({"event": event}, None)), \
                patch.object(cli.time, "time", return_value=NOW):
            return cli.fetch_calendar()

    def test_instances_and_rescheduled_meetings_have_distinct_stable_keys(self):
        data, problem = self.fetch(EVENT)
        self.assertIsNone(problem)
        renamed, _ = self.fetch(dict(EVENT, title="Renamed"))
        tomorrow, _ = self.fetch(dict(EVENT, start=EVENT["start"] + 86400))
        self.assertEqual(data["id"], renamed["id"])
        self.assertNotEqual(data["id"], tomorrow["id"])
        self.assertEqual(len(data["id"]), 16)
        self.assertEqual(data["time"], "10:00")

    def test_disabled_empty_invalid_and_denied_calendars_are_distinct(self):
        with patch.object(cli, "calendar_settings", return_value={}), \
                patch.object(cli, "calendar_reader") as reader:
            self.assertEqual(cli.fetch_calendar(), (None, None))
            reader.assert_not_called()
        self.assertEqual(self.fetch(None), ({}, None))
        for event in ({}, [], dict(EVENT, start=NOW), dict(EVENT, time="+1:00"),
                      dict(EVENT, time="24:00"), dict(EVENT, title=None)):
            self.assertIsNone(self.fetch(event)[0])
            self.assertTrue(self.fetch(event)[1])
        with patch.object(cli, "calendar_settings", return_value={"enabled": True}), \
                patch.object(cli, "calendar_reader", return_value=(None, "Calendar: sin permiso")):
            self.assertEqual(cli.fetch_calendar(), (None, "Calendar: sin permiso"))

    def test_title_is_safe_for_serial_and_countdown_accounts_for_elapsed_fetch_time(self):
        data, _ = self.fetch(dict(EVENT, title="Reunión\nview busy\r" + "x" * 200))
        with patch.object(cli.time, "time", return_value=NOW + 30):
            payload = cli.calendar_payload(data)
        self.assertIn(" 3570 10:00 Reunion view busy ", payload)
        self.assertLessEqual(len(payload), 96)
        self.assertNotIn("\n", payload)
        self.assertNotIn("\r", payload)
        with patch.object(cli.time, "time", return_value=EVENT["start"]):
            self.assertEqual(cli.calendar_payload(data), "calendar clear")

    def test_manual_view_and_terminal_share_read_but_only_view_uses_usb(self):
        data, _ = self.fetch(EVENT)
        for action in ([], ["terminal"]):
            with patch.object(cli, "fetch_calendar", return_value=(data, None)), \
                    patch.object(cli, "connect", return_value=(123, "/dev/gbot")) as connect, \
                    patch.object(cli, "close_port"), patch.object(cli, "talk", return_value="ok") as talk, \
                    patch.object(cli.time, "time", return_value=NOW), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["calendar"] + action), 0)
                self.assertIn("Calendar\n10:00\nDaily sync", output.getvalue())
                if action:
                    connect.assert_not_called()
                else:
                    self.assertEqual([call.args[1] for call in talk.call_args_list],
                                     [cli.calendar_payload(data), "view calendar", "wake"])

    def test_feed_sends_schedule_and_cancellation_without_forcing_a_view(self):
        data, _ = self.fetch(EVENT)
        for event in (data, {}):
            with patch.object(cli, "connect", return_value=(123, "/dev/gbot")), \
                    patch.object(cli, "close_port"), patch.object(cli, "talk", return_value="ok") as talk, \
                    patch.object(cli.time, "time", return_value=NOW):
                successes, problems, _ = cli.push_feed(None, [], None, calendar=event)
                self.assertEqual(successes, ["Calendar"])
                self.assertEqual(problems, [])
                self.assertEqual([call.args[1] for call in talk.call_args_list], [cli.calendar_payload(event)])

    def test_permission_failure_does_not_stop_other_feed_sources(self):
        data, _ = self.fetch(EVENT)
        with patch.object(cli, "feed_snapshot", return_value=([("CODEX", [])], None, [])), \
                patch.object(cli, "fetch_trm", return_value=(None, "TRM offline")), \
                patch.object(cli, "fetch_calendar", side_effect=[(None, "Calendar: sin permiso"), (data, None)]) as fetch, \
                patch.object(cli, "push_feed", return_value=(["CODEX"], [], "/dev/gbot")) as push, \
                patch.object(cli.time, "sleep", side_effect=[None, KeyboardInterrupt]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                cli.watch_feed(watch=60)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(push.call_args_list[0].args), 4)
        self.assertEqual(push.call_args_list[1].args[4], data)


class CalendarDisplayTests(unittest.TestCase):
    def test_title_fits_header_and_strips_match_the_whole_round_display(self):
        for title in ("Daily sync", "Sesion de arquitectura y planificacion semanal del equipo",
                      "W" * 48, ""):
            _, renderer, screen, lcd = preview.setup()
            screen.set_calendar("10:00", title)
            screen.enter_calendar(None)
            heading = renderer._meeting_title(title)
            self.assertLessEqual(renderer._width(heading, "brand"), 186)
            if title == "Daily sync":
                self.assertEqual(heading, title)
            elif title:
                self.assertTrue(heading.endswith("..."))
            expected = bytearray(240 * 240 * 2)
            fb = preview.base.FrameBuffer(expected, 240, 240, preview.base.RGB565)
            fb.fill(renderer._BG)
            screen._render_calendar(fb, 0, 240, (heading, "10:00", "AM"))
            self.assertEqual(lcd.data, expected)
            for y in range(240):
                for x in range(240):
                    if (x - 119.5) ** 2 + (y - 119.5) ** 2 > 120 ** 2:
                        self.assertEqual(fb.pixel(x, y), renderer._BG)

    def test_midnight_noon_and_afternoon_keep_correct_period_without_changing_source(self):
        cases = (("00:00", "12:00", "AM"), ("00:45", "12:45", "AM"),
                 ("09:05", "09:05", "AM"), ("11:59", "11:59", "AM"),
                 ("12:00", "12:00", "PM"), ("12:45", "12:45", "PM"),
                 ("13:00", "01:00", "PM"), ("23:59", "11:59", "PM"),
                 ("--:--", "--:--", ""))
        _, renderer, screen, _ = preview.setup()
        for source, clock, period in cases:
            with self.subTest(source=source):
                self.assertEqual(renderer._meeting_clock(source), (clock, period))
                screen.set_calendar(source, "Daily sync")
                screen.enter_calendar(None)
                self.assertEqual(screen._calendar_content, (source, "Daily sync"))

    def test_calendar_does_not_join_face_cards_or_modify_other_dashboards(self):
        _, _, screen, _ = preview.provider("CLAUDE")
        original, choices, buffer = screen.lines(), screen.card_choices(), screen.buf
        screen.set_calendar("10:00", "Daily sync")
        screen.enter_calendar(None)
        self.assertEqual(screen.lines(), original)
        self.assertEqual(screen.card_choices(), choices)
        self.assertIs(screen.buf, buffer)


if __name__ == "__main__":
    unittest.main()
