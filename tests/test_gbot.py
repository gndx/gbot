"""Pruebas del CLI sin placa, red ni credenciales del usuario.

Ejecutar: python3 -m unittest discover -s tests -v
"""

import contextlib
import copy
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import unittest
from unittest import mock


CLI_PATH = Path(__file__).resolve().parents[1] / "cli" / "gbot"
LOADER = importlib.machinery.SourceFileLoader("gbot_cli", str(CLI_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
gbot_cli = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(gbot_cli)

DEVICE = "/dev/cu.gbot-test"
FD = 123
CLAUDE_WINDOWS = [("5H", 84, 1830), ("7D", 89, 432000)]
CODEX_WINDOWS = [("5H", 63, 2400), ("7D", 72, 326877)]


class FakeBoard:
    """Estado minimo del protocolo, sin depender del firmware MicroPython."""

    def __init__(self, pages=(), supported=True):
        self.pages = copy.deepcopy(list(pages))
        self.page = 0
        self.view = "face"
        self.asleep = True
        self.supported = supported
        self.commands = []

    def talk(self, fd, command, *args, **kwargs):
        if fd != FD:
            raise AssertionError("descriptor de la placa inesperado")
        self.commands.append(command)
        if command == "status":
            return "ok state=open view=%s" % self.view
        if not self.supported and (
                command.startswith("limits") or command == "view limits"):
            return "err unknown command: limits"
        if command == "limits":
            parts = ["ok limits=%d page=%d" % (len(self.pages), self.page)]
            for title, windows in self.pages:
                encoded = ";".join("%s,%d,%d" % window for window in windows)
                parts.append("%s:%s" % (title, encoded))
            parts.append("age=0")
            return " ".join(parts)
        if command == "view limits":
            self.view = "limits"
            return "ok view=limits"
        if command == "wake":
            self.asleep = False
            return "ok sleep=0"
        if command.startswith("limits page "):
            self.page = int(command.split()[2]) % len(self.pages)
            return "ok page=%d" % self.page
        if command == "limits clear":
            self.pages = []
            self.page = 0
            return "ok limits=0"
        if command.startswith("limits "):
            _, title, *encoded = command.split()
            title = title[:8].upper()
            windows = []
            for window in encoded:
                label, pct, *reset = window.split(",")
                windows.append((label, int(pct), int(reset[0]) if reset else -1))
            for index, (existing, _) in enumerate(self.pages):
                if existing == title:
                    self.pages[index] = (title, windows)
                    break
            else:
                self.pages.append((title, windows))
            return "ok limits=%d" % len(windows)
        raise AssertionError("comando inesperado: %s" % command)


class ProviderCommandsTests(unittest.TestCase):
    @contextlib.contextmanager
    def cli(self, board, claude=None, codex=None, sleep=None):
        """Toda llamada externa queda sustituida, incluso si falla el CLI."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            connect = stack.enter_context(mock.patch.object(
                gbot_cli, "connect", return_value=(FD, DEVICE)))
            stack.enter_context(mock.patch.object(gbot_cli, "talk", side_effect=board.talk))
            close = stack.enter_context(mock.patch.object(gbot_cli.os, "close"))
            claude_fetch = stack.enter_context(mock.patch.object(
                gbot_cli, "claude_usage",
                return_value=claude or ("CLAUDE", CLAUDE_WINDOWS)))
            codex_fetch = stack.enter_context(mock.patch.object(
                gbot_cli, "codex_usage",
                return_value=codex or ("CODEX", CODEX_WINDOWS)))
            sleeper = stack.enter_context(mock.patch.object(
                gbot_cli.time, "sleep", side_effect=sleep))
            yield out, err, connect, close, claude_fetch, codex_fetch, sleeper

    def test_provider_updates_and_selects_its_actual_page(self):
        # Indices invertidos y una tercera cuenta evitan asumir CLAUDE=0/CODEX=1.
        for provider, title, other, windows in (
                ("claude", "CLAUDE", "CODEX", CLAUDE_WINDOWS),
                ("codex", "CODEX", "CLAUDE", CODEX_WINDOWS)):
            for existing in (False, True):
                with self.subTest(provider=provider, existing=existing):
                    initial = [(other, [("7D", 17, 987)]),
                               ("EXTRA", [("1D", 45, 123)])]
                    if existing:
                        initial.append((title, [("5H", 2, 1)]))
                    board = FakeBoard(initial)
                    with self.cli(board) as state:
                        out, err, connect, close, claude, codex, _ = state
                        result = gbot_cli.main(["-d", DEVICE, provider])

                    self.assertEqual(result, 0)
                    self.assertEqual(connect.call_args_list, [mock.call(DEVICE)] * 2)
                    self.assertEqual(close.call_args_list, [mock.call(FD)] * 2)
                    selected_fetch = claude if provider == "claude" else codex
                    other_fetch = codex if provider == "claude" else claude
                    selected_fetch.assert_called_once_with()
                    other_fetch.assert_not_called()
                    self.assertEqual(board.pages[:2], initial[:2])
                    self.assertEqual(board.pages[2:], [(title, windows)])
                    self.assertEqual(board.page, 2)
                    self.assertEqual(board.view, "limits")
                    self.assertFalse(board.asleep)
                    self.assertNotIn("limits clear", board.commands)
                    self.assertIn(title, out.getvalue())
                    self.assertNotIn(other, out.getvalue())
                    self.assertNotIn("EXTRA", out.getvalue())
                    for _, pct, _ in windows:
                        self.assertIn("%d%%" % pct, out.getvalue())
                    self.assertEqual(err.getvalue(), "")

    def test_missing_credentials_preserve_data_and_display(self):
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider):
                initial = [("CLAUDE", [("5H", 91, 100)]),
                           ("CODEX", [("7D", 80, 200)])]
                board = FakeBoard(initial)
                problem = "%s: sin credenciales de prueba" % provider
                with self.cli(board, **{provider: (None, problem)}) as state:
                    out, err, _, close, claude, codex, _ = state
                    with self.assertRaises(SystemExit) as failure:
                        gbot_cli.main([provider])

                self.assertEqual(failure.exception.code, 1)
                self.assertEqual(board.pages, initial)
                self.assertEqual(board.view, "face")
                self.assertTrue(board.asleep)
                self.assertEqual(board.page, 0)
                self.assertTrue(all(command in ("limits", "status")
                                    for command in board.commands), board.commands)
                self.assertIn(problem, out.getvalue() + err.getvalue())
                (claude if provider == "claude" else codex).assert_called_once_with()
                (codex if provider == "claude" else claude).assert_not_called()
                self.assertEqual(close.call_args_list, [mock.call(FD)] * 2)

    def test_unsupported_firmware_reports_error_and_keeps_current_display(self):
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider):
                board = FakeBoard(supported=False)
                with self.cli(board) as state:
                    out, err, _, close, _, _, _ = state
                    with self.assertRaises(SystemExit) as failure:
                        gbot_cli.main([provider])

                self.assertEqual(failure.exception.code, 1)
                self.assertIn("limits", err.getvalue().lower())
                self.assertEqual(board.pages, [])
                self.assertEqual(board.view, "face")
                self.assertTrue(board.asleep)
                self.assertNotIn("%", out.getvalue())
                close.assert_called_once_with(FD)

    def test_rate_limit_opens_correct_cached_page_without_refreshing_its_values(self):
        initial = [("CODEX", CODEX_WINDOWS), ("CLAUDE", CLAUDE_WINDOWS)]
        board = FakeBoard(initial)
        paused = gbot_cli.UsageDeferred("claude: consultas en pausa por HTTP 429")
        with self.cli(board, claude=(None, paused)) as state:
            out, err, _, _, _, codex, _ = state
            self.assertEqual(gbot_cli.main(["claude"]), 0)
        self.assertEqual(board.pages, initial)
        self.assertEqual(board.page, 1)
        self.assertEqual(board.view, "limits")
        self.assertFalse(board.asleep)
        self.assertFalse(any(cmd.startswith("limits CLAUDE") for cmd in board.commands))
        self.assertNotIn("limits clear", board.commands)
        self.assertIn("CACHED DATA", out.getvalue())
        self.assertIn("429", out.getvalue())
        self.assertEqual(err.getvalue(), "")
        codex.assert_not_called()

    def test_rate_limit_without_cached_account_keeps_display_and_never_invents_data(self):
        board = FakeBoard([("CODEX", CODEX_WINDOWS)])
        with self.cli(board, claude=(None, gbot_cli.UsageDeferred("HTTP 429"))) as state:
            out, err, *_ = state
            with self.assertRaises(SystemExit):
                gbot_cli.main(["claude"])
        self.assertEqual(board.view, "face")
        self.assertTrue(board.asleep)
        self.assertEqual(board.pages, [("CODEX", CODEX_WINDOWS)])
        self.assertIn("no cached data for CLAUDE", err.getvalue())
        self.assertNotIn("%", out.getvalue())

    def test_one_shot_claude_does_not_hold_usb_while_waiting_for_http(self):
        board = FakeBoard([("CLAUDE", CLAUDE_WINDOWS)])
        with self.cli(board) as state:
            _, _, _, close, fetch, _, _ = state
            def network():
                close.assert_called_once_with(FD)
                return "CLAUDE", CLAUDE_WINDOWS
            fetch.side_effect = network
            self.assertEqual(gbot_cli.main(["claude"]), 0)

    def test_watch_refreshes_only_requested_provider_and_closes_on_interrupt(self):
        for provider, title, other in (
                ("claude", "CLAUDE", "CODEX"),
                ("codex", "CODEX", "CLAUDE")):
            with self.subTest(provider=provider):
                initial = [(other, [("7D", 17, 987)])]
                board = FakeBoard(initial)
                with self.cli(board, sleep=[None, KeyboardInterrupt]) as state:
                    _, _, _, close, claude, codex, sleeper = state
                    fetch = claude if provider == "claude" else codex
                    other_fetch = codex if provider == "claude" else claude
                    updated = [("5H", 53, 111)]
                    fetch.side_effect = [(title, [("5H", 60, 222)]),
                                         (title, updated)]
                    with self.assertRaises(KeyboardInterrupt):
                        gbot_cli.main([provider, "--watch", "60"])

                self.assertEqual(fetch.call_count, 2)
                other_fetch.assert_not_called()
                self.assertEqual(board.pages, initial + [(title, updated)])
                self.assertEqual(board.page, 1)
                self.assertEqual(board.view, "limits")
                self.assertEqual(board.commands.count("view limits"), 1)
                self.assertEqual(board.commands.count("limits page 1"), 1)
                self.assertEqual(board.commands.count("wake"), 1)
                self.assertEqual(sleeper.call_args_list, [mock.call(60), mock.call(60)])
                # Una consulta de compatibilidad y dos lotes, todos cerrados.
                self.assertEqual(close.call_args_list, [mock.call(FD)] * 3)

    def test_watch_releases_port_before_network_and_sleep_and_reopens_for_each_batch(self):
        for command in (["claude"], ["codex"], ["limits", "--live"],
                        ["limits", "--demo"], ["limits"],
                        ["limits", "CLAUDE", "5H,42,600"]):
            with self.subTest(command=command):
                board = FakeBoard([("CLAUDE", CLAUDE_WINDOWS), ("CODEX", CODEX_WINDOWS)])
                ownership = {"open": False, "sleeps": 0}
                with self.cli(board) as state:
                    _, _, connect, close, claude, codex, sleeper = state
                    def open_batch(device):
                        self.assertFalse(ownership["open"], "reopened before closing USB")
                        ownership["open"] = True
                        return FD, DEVICE
                    def close_batch(fd):
                        self.assertTrue(ownership["open"], "closed a port without ownership")
                        ownership["open"] = False
                    def fetch(title, windows):
                        self.assertFalse(ownership["open"], "HTTP retained the USB lock")
                        return title, windows
                    def wait(seconds):
                        self.assertFalse(ownership["open"], "sleep retained the USB lock")
                        ownership["sleeps"] += 1
                        if ownership["sleeps"] == 2:
                            raise KeyboardInterrupt
                        # Otro comando puede cambiar la vista/pagina durante la espera.
                        board.view = "face"
                        board.page = 1 if command[0] == "claude" else 0
                        board.asleep = True
                    connect.side_effect = open_batch
                    close.side_effect = close_batch
                    claude.side_effect = lambda: fetch("CLAUDE", CLAUDE_WINDOWS)
                    codex.side_effect = lambda: fetch("CODEX", CODEX_WINDOWS)
                    sleeper.side_effect = wait
                    with self.assertRaises(KeyboardInterrupt):
                        gbot_cli.main(command + ["--watch", "60"])
                self.assertFalse(ownership["open"])
                self.assertEqual(connect.call_count, close.call_count)
                self.assertGreaterEqual(connect.call_count, 2)
                # Refrescar datos respeta tanto el retorno automatico como
                # los cambios de pantalla, pagina o reposo durante la espera.
                self.assertEqual(board.view, "face")
                self.assertEqual(board.page, 1 if command[0] == "claude" else 0)
                self.assertTrue(board.asleep)
                opens_view = command[0] in ("claude", "codex") or any(
                    flag in command for flag in ("--demo", "--live"))
                self.assertEqual(board.commands.count("view limits"), int(opens_view))
                if "--demo" in command:
                    self.assertEqual(board.pages, gbot_cli.demo_pages(1))


if __name__ == "__main__":
    unittest.main()
