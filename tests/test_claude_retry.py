"""Claude 429: persisted cooldown, Retry-After and independent provider updates."""

import contextlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
from email.message import Message


CLI_PATH = Path(__file__).resolve().parents[1] / "cli/gbot"
loader = importlib.machinery.SourceFileLoader("gbot_retry_cli", str(CLI_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)

SUCCESS = {"limits": [{"kind": "session", "percent": 16,
                       "resets_at": None}]}


class ClaudeRetryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "claude-retry.json")
        patcher = mock.patch.object(cli, "CLAUDE_RETRY_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    @contextlib.contextmanager
    def network(self, response):
        credential = subprocess.CompletedProcess([], 0, json.dumps({
            "claudeAiOauth": {"accessToken": "unit-test-token"}}), "")
        with mock.patch.object(cli.subprocess, "run", return_value=credential) as keychain, \
                mock.patch.object(cli, "_get_json", return_value=response) as http:
            yield keychain, http

    def test_429_skips_network_and_credentials_until_deadline_then_recovers(self):
        with mock.patch.object(cli.time, "time", return_value=1000), \
                self.network((429, None)) as (keychain, http):
            result = cli.claude_usage()
            self.assertIsNone(result[0])
            self.assertIsInstance(result[1], cli.UsageDeferred)
            self.assertIn("10 min", result[1])
            cli.claude_usage()
            keychain.assert_called_once()
            http.assert_called_once()
        state = json.loads(Path(self.path).read_text())
        self.assertEqual(state, {"retry_at": 1600, "failures": 1})
        self.assertEqual(Path(self.path).stat().st_mode & 0o777, 0o600)
        self.assertNotIn("unit-test-token", Path(self.path).read_text())
        with mock.patch.object(cli.time, "time", return_value=1600), \
                self.network((200, SUCCESS)) as (_, http):
            self.assertEqual(cli.claude_usage(), ("CLAUDE", [("5H", 84, -1)]))
            http.assert_called_once()
        self.assertEqual(json.loads(Path(self.path).read_text()),
                         {"retry_at": 0, "failures": 0})

    def test_repeated_429_uses_exponential_pause_capped_at_one_hour(self):
        now = 1000
        for expected in (600, 1200, 2400, 3600, 3600):
            with mock.patch.object(cli.time, "time", return_value=now), \
                    self.network((429, {})):
                self.assertIsNone(cli.claude_usage()[0])
            state = json.loads(Path(self.path).read_text())
            self.assertEqual(state["retry_at"] - now, expected)
            now += expected

    def test_retry_after_seconds_and_http_date_override_default_pause(self):
        for value, expected in (("120", 120),
                                ("Thu, 01 Jan 1970 02:16:40 GMT", 7200)):
            with self.subTest(value=value):
                with mock.patch.object(cli.time, "time", return_value=1000), \
                        self.network((429, {"retry_after": value})):
                    cli.claude_usage()
                self.assertEqual(json.loads(Path(self.path).read_text())["retry_at"],
                                 1000 + expected)
                Path(self.path).unlink()
        self.assertIsNone(cli._retry_after_seconds("nonsense"))

    def test_http_layer_keeps_only_retry_header_and_never_reads_error_body(self):
        headers = Message()
        headers["Retry-After"] = "720"
        body = mock.Mock()
        error = HTTPError("https://example.test", 429, "limited", headers, body)
        with mock.patch("urllib.request.urlopen", side_effect=error):
            self.assertEqual(cli._get_json("https://example.test", {}),
                             (429, {"retry_after": "720"}))
        body.read.assert_not_called()

    def test_separate_cli_process_observes_same_pause(self):
        Path(self.path).write_text(json.dumps({"retry_at": 1600, "failures": 1}))
        code = """
import runpy, sys
c = runpy.run_path(sys.argv[1])
g = c['claude_usage'].__globals__
g['CLAUDE_RETRY_FILE'] = sys.argv[2]
g['time'].time = lambda: 1000
def forbidden(state):
    raise AssertionError('Another process bypassed the cooldown')
g['_fetch_claude_usage'] = forbidden
title, message = c['claude_usage']()
assert title is None and isinstance(message, c['UsageDeferred'])
print('shared pause')
"""
        result = subprocess.run([sys.executable, "-c", code, str(CLI_PATH), self.path],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "shared pause")

    def test_concurrent_claude_query_is_deferred_before_keychain_or_http(self):
        import fcntl
        with open(self.path + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.network((200, SUCCESS)) as (keychain, http):
                result = cli.claude_usage()
                self.assertIsInstance(result[1], cli.UsageDeferred)
                keychain.assert_not_called()
                http.assert_not_called()

    def test_feed_continues_codex_and_weather_during_claude_pause(self):
        Path(self.path).write_text(json.dumps({"retry_at": 1600, "failures": 1}))
        weather = {"temp_tenths": 240}
        with mock.patch.object(cli.time, "time", return_value=1000), \
                mock.patch.object(cli, "_fetch_claude_usage") as fetch, \
                mock.patch.object(cli, "codex_usage", return_value=("CODEX", [("7D", 60, 100)])), \
                mock.patch.object(cli, "fetch_weather", return_value=(weather, None)):
            pages, result_weather, problems = cli.feed_snapshot()
        fetch.assert_not_called()
        self.assertEqual(pages, [("CODEX", [("7D", 60, 100)])])
        self.assertEqual(result_weather, weather)
        self.assertIn("429", problems[0])


if __name__ == "__main__":
    unittest.main()
