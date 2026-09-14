"""Clima y alimentador USB: contrato, datos invalidos y fallos independientes."""

import contextlib
import copy
import errno
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


LOADER = importlib.machinery.SourceFileLoader(
    "gbot_weather_cli", str(Path(__file__).resolve().parents[1] / "cli" / "gbot"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
gbot_cli = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(gbot_cli)

NOW = 1788976800
WEATHER = {"temp_tenths": 238, "code": 61, "humidity": 76,
           "observed_epoch": NOW - 300}
RESPONSE = {
    "current_units": {"temperature_2m": "°C", "relative_humidity_2m": "%",
                      "weather_code": "wmo code", "time": "unixtime"},
    "current": {"temperature_2m": 23.8, "relative_humidity_2m": 76,
                "weather_code": 61, "time": NOW - 300},
}


class WeatherFetchTests(unittest.TestCase):
    def fetch(self, response, code=200):
        with mock.patch.object(gbot_cli, "_get_json", return_value=(code, response)), \
                mock.patch.object(gbot_cli.time, "time", return_value=NOW):
            return gbot_cli.fetch_weather()

    def test_current_celsius_and_unix_time_become_fixed_point_usb_data(self):
        result, problem = self.fetch(RESPONSE)
        self.assertIsNone(problem)
        self.assertEqual(result, WEATHER)
        self.assertEqual(gbot_cli.weather_payload(result),
                         "weather set 238 61 76 %d" % (NOW - 300))

    def test_invalid_units_missing_fields_and_stale_data_are_rejected(self):
        variants = []
        wrong_units = copy.deepcopy(RESPONSE)
        wrong_units["current_units"]["temperature_2m"] = "°F"
        variants.append(wrong_units)
        for field, value in (("temperature_2m", None), ("temperature_2m", float("nan")),
                             ("relative_humidity_2m", 101), ("weather_code", 7),
                             ("time", NOW - 86400), ("time", NOW + 1000),
                             ("temperature_2m", True)):
            response = copy.deepcopy(RESPONSE)
            response["current"][field] = value
            variants.append(response)
        variants.extend(({}, {"current": []}, None))
        for response in variants:
            with self.subTest(response=response):
                data, problem = self.fetch(response)
                self.assertIsNone(data)
                self.assertTrue(problem)

    def test_http_failure_contains_no_server_body_or_credentials(self):
        data, problem = self.fetch("untrusted secret-shaped body", code=403)
        self.assertIsNone(data)
        self.assertIn("403", problem)
        self.assertNotIn("secret", problem)

    def test_temperature_upper_bound_matches_firmware_contract(self):
        response = copy.deepcopy(RESPONSE)
        response["current"]["temperature_2m"] = 60.0
        data, problem = self.fetch(response)
        self.assertIsNone(problem)
        self.assertEqual(data["temp_tenths"], 600)
        response["current"]["temperature_2m"] = 60.1
        data, problem = self.fetch(response)
        self.assertIsNone(data)
        self.assertIn("out of range", problem)


class WeatherCommandTests(unittest.TestCase):
    @contextlib.contextmanager
    def board(self, weather_reply="ok source=host city=Medellin ready=0"):
        commands = []
        def talk(fd, command):
            commands.append(command)
            return weather_reply if command == "weather" else "ok"
        with mock.patch.object(gbot_cli, "connect", return_value=(123, "/dev/gbot")), \
                mock.patch.object(gbot_cli, "talk", side_effect=talk), \
                mock.patch.object(gbot_cli.os, "close") as close, \
                mock.patch.object(gbot_cli, "fetch_weather", return_value=(WEATHER, None)) as fetch, \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            yield commands, close, fetch

    def test_host_weather_fetches_with_port_closed_and_shows_card(self):
        for command in ("weather", "clima"):
            with self.subTest(command=command), self.board() as (commands, close, fetch):
                def network():
                    close.assert_called_once_with(123)
                    return WEATHER, None
                fetch.side_effect = network
                self.assertEqual(gbot_cli.main([command, "-d", "/dev/gbot"]), 0)
                self.assertEqual(commands, ["weather", gbot_cli.weather_payload(WEATHER),
                                            "view weather", "wake"])
                self.assertEqual(close.call_count, 2)

    def test_status_only_and_native_c3_never_fetch_or_change_display(self):
        for argv, reply in ((["weather", "status"], "ok source=host ready=0"),
                            (["weather"], "ok city=Medellin temp=23.8 wifi=connected")):
            with self.subTest(argv=argv, reply=reply):
                with self.board(reply) as (commands, close, fetch):
                    self.assertEqual(gbot_cli.main(argv), 0)
                self.assertEqual(commands, ["weather"])
                fetch.assert_not_called()
                close.assert_called_once_with(123)

    def test_network_failure_keeps_last_data_and_existing_face(self):
        with self.board() as (commands, close, fetch):
            fetch.return_value = (None, "clima: offline")
            with self.assertRaises(SystemExit):
                gbot_cli.main(["weather"])
        self.assertEqual(commands, ["weather"])
        close.assert_called_once_with(123)

    def test_face_shortcut_restores_eyes_without_fetching_data(self):
        with self.board() as (commands, close, fetch):
            self.assertEqual(gbot_cli.main(["face"]), 0)
        self.assertEqual(commands, ["view face"])
        fetch.assert_not_called()
        close.assert_called_once_with(123)


class FeedTests(unittest.TestCase):
    def setUp(self):
        isolated = mock.patch.object(gbot_cli, "fetch_calendar", return_value=(None, None))
        isolated.start()
        self.addCleanup(isolated.stop)

    def test_provider_failure_does_not_block_other_usage_or_weather(self):
        with mock.patch.object(gbot_cli, "claude_usage", return_value=(None, "sin Claude")), \
                mock.patch.object(gbot_cli, "codex_usage", return_value=("CODEX", [("5H", 61, 100)])), \
                mock.patch.object(gbot_cli, "fetch_weather", return_value=(WEATHER, None)):
            pages, weather, problems = gbot_cli.feed_snapshot()
        self.assertEqual(pages, [("CODEX", [("5H", 61, 100)])])
        self.assertEqual(weather, WEATHER)
        self.assertEqual(problems, ["sin Claude"])

    def test_unexpected_provider_schema_does_not_stop_the_feed(self):
        with mock.patch.object(gbot_cli, "claude_usage", side_effect=TypeError("bad schema")), \
                mock.patch.object(gbot_cli, "codex_usage", return_value=("CODEX", [("5H", 61, 100)])), \
                mock.patch.object(gbot_cli, "fetch_weather", return_value=(WEATHER, None)):
            pages, weather, problems = gbot_cli.feed_snapshot()
        self.assertEqual(pages, [("CODEX", [("5H", 61, 100)])])
        self.assertEqual(weather, WEATHER)
        self.assertEqual(problems, ["Claude: invalid response"])

    def test_feed_updates_data_without_any_display_or_state_command(self):
        commands = []
        def talk(fd, command):
            commands.append(command)
            return "ok source=host ready=0" if command == "weather" else "ok"
        with mock.patch.object(gbot_cli, "connect", return_value=(123, "/dev/gbot")), \
                mock.patch.object(gbot_cli, "talk", side_effect=talk), \
                mock.patch.object(gbot_cli.os, "close") as close:
            successes, problems, _ = gbot_cli.push_feed(
                None, [("CLAUDE", [("5H", 12, 77)]), ("CODEX", [("5H", 61, 100)])], WEATHER)
        self.assertEqual(successes, ["CLAUDE", "CODEX", "Medellin"])
        self.assertEqual(problems, [])
        self.assertEqual(commands, ["weather", "limits CLAUDE 5H,12,77",
                                    "limits CODEX 5H,61,100", gbot_cli.weather_payload(WEATHER)])
        close.assert_called_once_with(123)

    def test_rejected_provider_still_updates_the_other_provider(self):
        with mock.patch.object(gbot_cli, "connect", return_value=(123, "/dev/gbot")), \
                mock.patch.object(gbot_cli, "talk", side_effect=["err invalid", "ok"]), \
                mock.patch.object(gbot_cli.os, "close") as close:
            successes, problems, _ = gbot_cli.push_feed(
                None, [("CLAUDE", [("5H", 12, 77)]), ("CODEX", [("5H", 61, 100)])], None)
        self.assertEqual(successes, ["CODEX"])
        self.assertEqual(len(problems), 1)
        close.assert_called_once_with(123)

    def test_weather_is_fetched_every_ten_minutes_while_usage_continues(self):
        pages = [("CODEX", [("5H", 61, 100)])]
        clock = [1000]
        def sleep(seconds):
            clock[0] += seconds
            if clock[0] >= 1660:
                raise KeyboardInterrupt
        with mock.patch.object(gbot_cli.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(gbot_cli.time, "sleep", side_effect=sleep), \
                mock.patch.object(gbot_cli, "feed_snapshot", return_value=(pages, WEATHER, [])) as snapshot, \
                mock.patch.object(gbot_cli, "fetch_trm", return_value=(None, "TRM offline")), \
                mock.patch.object(gbot_cli, "push_feed", return_value=(["CODEX"], [], "/dev/gbot")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                gbot_cli.main(["feed", "--watch", "60"])
        self.assertEqual(snapshot.call_args_list,
                         [mock.call(True)] + [mock.call(False)] * 9 + [mock.call(True)])

    def test_disconnected_board_does_not_stop_watch(self):
        clock = [1000]
        def sleep(seconds):
            clock[0] += seconds
            if clock[0] >= 1120:
                raise KeyboardInterrupt
        with mock.patch.object(gbot_cli.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(gbot_cli.time, "sleep", side_effect=sleep), \
                mock.patch.object(gbot_cli, "feed_snapshot", return_value=([], WEATHER, [])) as snapshot, \
                mock.patch.object(gbot_cli, "fetch_trm", return_value=(None, "TRM offline")), \
                mock.patch.object(gbot_cli, "push_feed", side_effect=[SystemExit(1), (["Medellin"], [], "/dev/gbot")]) as push, \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                gbot_cli.main(["feed", "--watch", "60"])
        self.assertEqual(push.call_count, 2)
        self.assertEqual(snapshot.call_args_list, [mock.call(True), mock.call(True)])


class PortLockTests(unittest.TestCase):
    """Dos procesos y archivos temporales; ninguna placa o puerto real."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.device = str(Path(self.temp.name) / "cu.gbot-test")
        Path(self.device).touch()
        self.locks = str(Path(self.temp.name) / "locks")
        patch = mock.patch.object(gbot_cli, "LOCK_DIR", self.locks)
        patch.start()
        self.addCleanup(patch.stop)

    @contextlib.contextmanager
    def fake_serial(self, settle_error=None):
        with mock.patch.object(gbot_cli.tty, "setraw"), \
                mock.patch.object(gbot_cli.termios, "tcgetattr", return_value=[0] * 7), \
                mock.patch.object(gbot_cli.termios, "tcsetattr"), \
                mock.patch.object(gbot_cli.termios, "tcflush"), \
                mock.patch.object(gbot_cli, "settle", side_effect=settle_error):
            yield

    def other_process_can_lock(self):
        script = """
import fcntl
import os
import sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print('available')
except BlockingIOError:
    print('busy')
finally:
    os.close(fd)
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(Path(self.locks) / Path(self.device).name)],
            check=True, capture_output=True, text=True, timeout=3)
        return result.stdout.strip() == "available"

    def test_processes_cannot_share_port_until_close_releases_lock(self):
        with self.fake_serial():
            fd = gbot_cli.open_port(self.device)
        try:
            self.assertFalse(self.other_process_can_lock())
        finally:
            gbot_cli.close_port(fd)
        self.assertTrue(self.other_process_can_lock())
        self.assertNotIn(fd, gbot_cli._PORT_LOCKS)

    def test_busy_port_wait_is_bounded_and_reports_explicit_error(self):
        lock = gbot_cli._acquire_port_lock(self.device)
        started = time.monotonic()
        try:
            with self.assertRaises(OSError) as error:
                gbot_cli._acquire_port_lock(self.device, timeout=0.05)
            self.assertEqual(error.exception.errno, errno.EBUSY)
            self.assertIn("port busy", str(error.exception))
            self.assertLess(time.monotonic() - started, 1)
        finally:
            os.close(lock)
        self.assertTrue(self.other_process_can_lock())

    def test_missing_device_releases_lock(self):
        Path(self.device).unlink()
        with self.assertRaises(FileNotFoundError):
            gbot_cli.open_port(self.device)
        self.assertTrue(self.other_process_can_lock())

    def test_serial_initialization_failure_or_interrupt_releases_lock(self):
        for error in (OSError("USB disconnected"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with self.fake_serial(settle_error=error):
                    with self.assertRaises(type(error)):
                        gbot_cli.open_port(self.device)
                self.assertTrue(self.other_process_can_lock())
                self.assertEqual(gbot_cli._PORT_LOCKS, {})

    def test_connection_ping_interrupt_releases_lock(self):
        with self.fake_serial(), mock.patch.object(gbot_cli, "talk", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                gbot_cli.connect(self.device)
        self.assertTrue(self.other_process_can_lock())
        self.assertEqual(gbot_cli._PORT_LOCKS, {})


if __name__ == "__main__":
    unittest.main()
