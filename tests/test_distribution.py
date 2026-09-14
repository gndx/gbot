"""Public distribution boundaries, with no real devices or account access."""

import contextlib
import datetime
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

loader = importlib.machinery.SourceFileLoader(
    "gbot_distribution", str(Path(__file__).resolve().parents[1] / "cli/gbot"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class DistributionTests(unittest.TestCase):
    def test_discovery_includes_macos_and_linux_native_usb(self):
        devices = {
            "/dev/cu.usbmodem*": ["/dev/cu.usbmodemTEST"],
            "/dev/ttyACM*": ["/dev/ttyACM0"],
        }
        with mock.patch.object(cli.glob, "glob", side_effect=lambda p: devices.get(p, [])):
            self.assertEqual(cli.candidates(), ["/dev/cu.usbmodemTEST", "/dev/ttyACM0"])

    def test_missing_gbot_cache_does_not_read_legacy_projects(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(cli, "CACHE", str(Path(folder) / "device")), \
                    mock.patch("builtins.open", side_effect=FileNotFoundError) as opened:
                self.assertIsNone(cli.cached_device())
            self.assertEqual(opened.call_count, 1)
            self.assertEqual(opened.call_args.args[0], str(Path(folder) / "device"))

    def test_unsupported_radio_commands_fail_before_opening_usb(self):
        for command in (["wifi", "set"], ["clock"]):
            with self.subTest(command=command), \
                    mock.patch.object(cli, "connect") as connect, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    cli.main(command)
                self.assertEqual(error.exception.code, 1)
                connect.assert_not_called()

    def test_weather_terminal_never_opens_usb(self):
        weather = {"temp_tenths": 230, "humidity": 60, "observed_epoch": 1700000000}
        with mock.patch.object(cli, "fetch_weather", return_value=(weather, None)), \
                mock.patch.object(cli, "connect") as connect, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["weather", "terminal"]), 0)
        connect.assert_not_called()
        self.assertIn("23.0 °C", output.getvalue())
        self.assertIn("Humidity 60%", output.getvalue())

    def test_usage_reset_accepts_utc_z_suffix_on_supported_python(self):
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1))
        seconds = cli._until(future.isoformat().replace("+00:00", "Z"))
        self.assertTrue(3590 <= seconds <= 3600, seconds)


if __name__ == "__main__":
    unittest.main()
