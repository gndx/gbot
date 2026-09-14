"""TRM vigente en Colombia, precision monetaria, USB y composicion del panel."""

import contextlib
import datetime
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("gbot_trm_cli", str(ROOT / "cli/gbot"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)
spec = importlib.util.spec_from_file_location("trm_cards", ROOT / "scripts/preview-cards.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)

NOW = datetime.datetime(2026, 9, 10, 1, tzinfo=datetime.timezone.utc).timestamp()
ROW = {"valor": "3116.47", "vigenciadesde": "2026-09-09T00:00:00.000",
       "vigenciahasta": "2026-09-09T00:00:00.000"}
TRM = {"cents": 311647, "from_day": 20260909, "to_day": 20260909, "valid_for": 14400}


class TrmCliTests(unittest.TestCase):
    def setUp(self):
        isolated = patch.object(cli, "fetch_calendar", return_value=(None, None))
        isolated.start()
        self.addCleanup(isolated.stop)

    def fetch(self, rows, status=200):
        with patch.object(cli, "_get_json", return_value=(status, rows)), \
                patch.object(cli.time, "time", return_value=NOW):
            return cli.fetch_trm()

    def test_query_uses_colombian_day_and_exact_decimal_cents(self):
        with patch.object(cli, "_get_json", return_value=(200, [ROW])) as get, \
                patch.object(cli.time, "time", return_value=NOW):
            data, problem = cli.fetch_trm()
        self.assertIsNone(problem)
        self.assertEqual(data, TRM)
        query = parse_qs(urlsplit(get.call_args.args[0]).query)
        self.assertEqual(query["$where"], ["vigenciadesde <= '2026-09-09T00:00:00' AND vigenciahasta >= '2026-09-09T00:00:00'"])
        self.assertEqual(cli.cop_amount(data["cents"]), "3.116,47")
        self.assertEqual(cli.trm_payload(data), "trm set 311647 20260909 20260909 14400")

    def test_weekend_range_includes_last_day_until_colombian_midnight(self):
        row = dict(ROW, vigenciadesde="2026-09-05T00:00:00.000",
                   vigenciahasta="2026-09-09T00:00:00.000")
        data, problem = self.fetch([row])
        self.assertIsNone(problem)
        self.assertEqual(data["from_day"], 20260905)
        self.assertEqual(data["valid_for"], 14400)

    def test_future_expired_invalid_and_unavailable_rates_are_rejected(self):
        rows = [[], [None], [{}]]
        rows += [[dict(ROW, valor=x)] for x in ("NaN", "Infinity", "0", "-5", "3116.471", True, "100000")]
        rows += [[dict(ROW, vigenciadesde="2026-09-10T00:00:00")],
                 [dict(ROW, vigenciahasta="2026-09-08T00:00:00")]]
        for response in rows:
            with self.subTest(response=response):
                data, problem = self.fetch(response)
                self.assertIsNone(data)
                self.assertTrue(problem)
        self.assertIn("429", self.fetch(None, 429)[1])

    def test_terminal_commands_do_not_require_or_mutate_board(self):
        weather = {"temp_tenths": 261, "humidity": 53, "code": 3, "observed_epoch": NOW}
        with patch.object(cli, "connect") as connect, \
                patch.object(cli, "fetch_trm", return_value=(TRM, None)), \
                patch.object(cli, "fetch_weather", return_value=(weather, None)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["clima", "terminal"]), 0)
            self.assertEqual(cli.main(["trm", "terminal"]), 0)
        connect.assert_not_called()
        self.assertIn("Medellín  26.1 °C", output.getvalue())
        self.assertIn("1 USD = $3.116,47 COP", output.getvalue())
        self.assertIn("09/09/2026", output.getvalue())

    def test_trm_default_and_view_alias_fetch_before_usb_then_open_screen(self):
        for args in (["trm"], ["trm", "view"]):
            with self.subTest(args=args), \
                    patch.object(cli, "connect", return_value=(123, "/dev/gbot")) as connect, \
                    patch.object(cli, "close_port"), patch.object(cli, "talk", return_value="ok") as talk, \
                    patch.object(cli, "fetch_trm") as fetch, contextlib.redirect_stdout(io.StringIO()):
                def network():
                    connect.assert_not_called()
                    return TRM, None
                fetch.side_effect = network
                self.assertEqual(cli.main(args), 0)
                self.assertEqual([call.args[1] for call in talk.call_args_list],
                                 [cli.trm_payload(TRM), "view trm", "wake"])

    def test_feed_decreases_validity_and_refetches_at_expiry(self):
        clock = [1000]
        def sleep(seconds):
            clock[0] += seconds
            if clock[0] >= 1180:
                raise KeyboardInterrupt
        with patch.object(cli.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(cli.time, "sleep", side_effect=sleep), \
                patch.object(cli, "feed_snapshot", return_value=([], None, [])), \
                patch.object(cli, "fetch_trm", side_effect=[(dict(TRM, valid_for=120), None), (None, "TRM offline")]) as fetch, \
                patch.object(cli, "push_feed", return_value=(["TRM"], [], "/dev/gbot")) as push, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                cli.watch_feed(watch=60)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([call.args[3]["valid_for"] for call in push.call_args_list], [120, 60])

    def test_feed_failure_keeps_other_providers_running_and_last_rate_until_expiry(self):
        clock = [1000]
        def sleep(seconds):
            clock[0] += seconds
            if clock[0] >= 8200:
                raise KeyboardInterrupt
        with patch.object(cli.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(cli.time, "sleep", side_effect=sleep), \
                patch.object(cli, "feed_snapshot", return_value=([("CODEX", [])], None, [])), \
                patch.object(cli, "fetch_trm", side_effect=[(dict(TRM, valid_for=14400), None), (None, "TRM offline")]), \
                patch.object(cli, "push_feed", return_value=(["CODEX"], [], "/dev/gbot")) as push, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                cli.watch_feed(watch=3600)
        self.assertEqual([call.args[3]["valid_for"] for call in push.call_args_list], [14400, 10800])

    def test_trm_usb_update_never_switches_existing_face_or_usage_page(self):
        with patch.object(cli, "connect", return_value=(123, "/dev/gbot")), \
                patch.object(cli, "close_port"), patch.object(cli, "talk", return_value="ok") as talk:
            success, problems, _ = cli.push_feed(None, [], None, TRM)
        self.assertEqual(success, ["TRM"])
        self.assertEqual(problems, [])
        self.assertEqual([call.args[1] for call in talk.call_args_list], [cli.trm_payload(TRM)])


class TrmDisplayTests(unittest.TestCase):
    def setUp(self):
        self.modules = preview.environment()
        self.clock, self.face, self.screen, self.lcd = preview.setup("await", self.modules)

    def test_expiry_across_tick_wrap_marks_full_view_stale(self):
        self.clock.now = self.clock.period - 1000
        self.screen.set_trm(311647, 20260909, 20260909, 2)
        self.screen.enter_trm(None)
        before = bytes(self.lcd.data)
        self.clock.advance(2000)
        self.screen.advance(self.clock.ticks_ms())
        self.screen.tick_trm()
        self.assertIn("stale=1", self.screen.trm_report())
        self.assertNotEqual(bytes(self.lcd.data), before)

    def test_trm_never_joins_rotation_or_changes_existing_usage(self):
        preview.sample_data(self.screen)
        choices = self.screen.card_choices()
        original = self.screen.lines()
        self.screen.set_trm(311647, 20260909, 20260909, 100)
        self.assertEqual(self.screen.card_choices(), choices)
        self.assertEqual(self.screen.lines(), original)

    def test_strips_match_complete_frame_and_exact_money_fits_circle(self):
        renderer = self.modules[3]
        for cents in (1, 311647, 9999999):
            self.screen.set_trm(cents, 20260909, 20260909, 100)
            self.screen.enter_trm(None)
            self.assertEqual(self.screen._trm_content()[0], cli.cop_amount(cents))
            expected = bytearray(240 * 240 * 2)
            fb = preview.base.FrameBuffer(expected, 240, 240, preview.base.RGB565)
            fb.fill(renderer._BG)
            self.screen._render_trm(fb, 0, 240, self.screen._trm_content())
            self.assertEqual(self.lcd.data, expected)
            for y in range(240):
                for x in range(240):
                    if (x - 119.5) ** 2 + (y - 119.5) ** 2 > 120 ** 2:
                        self.assertEqual(fb.pixel(x, y), renderer._BG)

    def test_invalid_payload_keeps_last_valid_rate_and_no_data_invents_nothing(self):
        self.screen.enter_trm(None)
        self.assertIn("available=0", self.screen.trm_report())
        self.screen.set_trm(311647, 20260909, 20260909, 100)
        original = self.screen.trm_report()
        for args in ((0, 20260909, 20260909, 100), (311647, 20260931, 20260931, 100),
                     (311647, 20260910, 20260909, 100), (311647, 20260909, 20260909, 0)):
            with self.assertRaises(ValueError):
                self.screen.set_trm(*args)
            self.assertEqual(self.screen.trm_report(), original)


if __name__ == "__main__":
    unittest.main()
