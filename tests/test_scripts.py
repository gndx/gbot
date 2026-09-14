"""Exercise install/deploy safety using isolated files and fake host tools.

These tests never open serial ports, flash hardware, install real services,
read user credentials or write to the user's application directories.
"""

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest
import venv


ROOT = Path(__file__).resolve().parents[1]


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gbot-script-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.repo = self.folder / "repo with spaces"
        shutil.copytree(ROOT / "scripts", self.repo / "scripts")
        self.bin = self.repo / ".venv/bin"
        venv.EnvBuilder(with_pip=False, symlinks=True).create(self.repo / ".venv")
        self.board = self.folder / "fake board"
        self.board.mkdir()
        self.log = self.folder / "calls.jsonl"
        self.env = {**os.environ, "GBOT_TEST_LOG": str(self.log),
                    "GBOT_TEST_BOARD": str(self.board),
                    "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "")}
        for name in ("board", "limits", "limits_font", "main"):
            path = self.repo / "firmware" / (name + ".py")
            path.parent.mkdir(exist_ok=True)
            path.write_text("# " + name + "\nVALUE = 1\n")
        (self.repo / "fonts").mkdir()
        (self.repo / "fonts/Inter-OFL.txt").write_text("Sample license\n")
        self.executable("mpy-cross", """
            import json, os
            from pathlib import Path
            import sys
            with open(os.environ['GBOT_TEST_LOG'], 'a') as log:
                log.write(json.dumps(['compile', *sys.argv[1:]]) + '\\n')
            if os.environ.get('GBOT_TEST_COMPILE_FAIL'):
                print('synthetic compiler failure', file=sys.stderr)
                raise SystemExit(1)
            output = Path(sys.argv[sys.argv.index('-o') + 1])
            output.write_bytes(b'compiled:' + Path(sys.argv[-1]).read_bytes())
        """)
        self.executable("mpremote", """
            import json, os
            from pathlib import Path
            import sys
            args = sys.argv[1:]
            with open(os.environ['GBOT_TEST_LOG'], 'a') as log:
                log.write(json.dumps(['remote', *args]) + '\\n')
            board = Path(os.environ['GBOT_TEST_BOARD'])
            if args[2:4] == ['fs', 'cp']:
                source, target = args[4:6]
                if source.startswith(':'):
                    data = (board / source[1:]).read_bytes()
                    if os.environ.get('GBOT_TEST_CORRUPT'):
                        data += b'corrupt'
                    Path(target).write_bytes(data)
                else:
                    if os.environ.get('GBOT_TEST_COPY_FAIL'):
                        print('synthetic transfer failure', file=sys.stderr)
                        raise SystemExit(1)
                    (board / target[1:]).write_bytes(Path(source).read_bytes())
        """)
        self.executable("sleep", "pass\n")

    def executable(self, name, source):
        path = self.bin / name
        path.write_text("#!" + sys.executable + "\n" + textwrap.dedent(source).lstrip())
        path.chmod(0o755)
        return path

    def run_script(self, name, *args, **env):
        return subprocess.run(["bash", str(self.repo / "scripts" / name), *map(str, args)],
                              cwd=self.folder, env={**self.env, **env}, text=True,
                              capture_output=True, timeout=20)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_deploy_requires_explicit_port_before_running_tools(self):
        result = self.run_script("deploy.sh")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_compile_failure_never_opens_serial_port(self):
        result = self.run_script("deploy.sh", "/dev/gbot-test", GBOT_TEST_COMPILE_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("synthetic compiler failure", result.stderr)
        self.assertTrue(self.calls())
        self.assertTrue(all(call[0] == "compile" for call in self.calls()))
        self.assertEqual(list(self.board.iterdir()), [])

    def test_verified_deploy_compiles_first_copies_main_last_and_reads_every_file(self):
        result = self.run_script("deploy.sh", "/dev/gbot-test", "--verify")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertTrue(all(call[0] == "compile" for call in calls[:4]))
        remote = calls[4:]
        self.assertTrue(all(call[:3] == ["remote", "connect", "/dev/gbot-test"] for call in remote))
        writes = [call for call in remote if call[3:5] == ["fs", "cp"] and not call[5].startswith(":")]
        reads = [call for call in remote if call[3:5] == ["fs", "cp"] and call[5].startswith(":")]
        self.assertEqual([call[6] for call in writes],
                         [":board.py", ":limits_font.mpy", ":limits.mpy", ":Inter-OFL.txt", ":main.py"])
        self.assertEqual([call[5] for call in reads], [call[6] for call in writes])
        self.assertEqual(remote[-1][3:], ["reset"])
        self.assertEqual((self.board / "main.py").read_bytes(), (self.repo / "firmware/main.py").read_bytes())

    def test_readback_mismatch_stops_before_main_and_reset(self):
        result = self.run_script("deploy.sh", "/dev/gbot-test", "--verify", GBOT_TEST_CORRUPT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Readback mismatch", result.stderr)
        self.assertFalse((self.board / "main.py").exists())
        self.assertFalse(any(call[-1] == "reset" for call in self.calls()))

    def test_transfer_failure_reports_error_and_stops_before_reset(self):
        result = self.run_script("deploy.sh", "/dev/gbot-test", GBOT_TEST_COPY_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("synthetic transfer failure", result.stderr)
        self.assertIn("partial update", result.stderr)
        self.assertEqual(len([call for call in self.calls() if call[0] == "remote"]), 3)
        self.assertFalse(any(call[-1] == "reset" for call in self.calls()))

    def uf2(self, family=0xE48BFF56):
        block = bytearray(512)
        struct.pack_into("<8I", block, 0, 0x0A324655, 0x9E5D5157, 0x2000,
                         0x10000000, 256, 0, 1, family)
        struct.pack_into("<I", block, 508, 0x0AB16F30)
        path = self.folder / "firmware.uf2"
        path.write_bytes(block)
        return path

    def volume(self):
        volume = self.folder / "RPI-RP2"
        volume.mkdir()
        (volume / "INFO_UF2.TXT").write_text("UF2 Bootloader\nBoard-ID: RPI-RP2\n")
        return volume

    def test_flash_rejects_other_family_before_copy(self):
        source, volume = self.uf2(family=0xE48BFF59), self.volume()
        result = self.run_script("flash.sh", source, volume)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not marked for RP2040", result.stderr)
        self.assertFalse((volume / source.name).exists())

    def test_flash_rejects_directory_without_bootloader_identity(self):
        source = self.uf2()
        result = self.run_script("flash.sh", source, self.board)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BOOTSEL volume", result.stderr)
        self.assertFalse((self.board / source.name).exists())

    def test_flash_validates_and_copies_to_explicit_volume(self):
        source, volume = self.uf2(), self.volume()
        result = self.run_script("flash.sh", source, volume)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((volume / source.name).read_bytes(), source.read_bytes())

    def test_flash_does_not_hide_copy_failure(self):
        self.executable("cp", "import sys\nraise SystemExit(1)\n")
        result = self.run_script("flash.sh", self.uf2(), self.volume())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("The copy failed", result.stderr)
        self.assertNotIn("UF2 copied", result.stdout)

    def test_installer_preserves_existing_symlink_target_and_uses_venv_python(self):
        (self.repo / "cli").mkdir()
        (self.repo / "cli/gbot").write_text("import json, sys\nprint(json.dumps([sys.executable, *sys.argv[1:]]))\n")
        destination = self.folder / "bin with spaces"
        destination.mkdir()
        unrelated = self.folder / "unrelated-cli"
        unrelated.write_text("preserve this file\n")
        (destination / "gbot").symlink_to(unrelated)
        result = self.run_script("install-cli.sh", destination)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(unrelated.read_text(), "preserve this file\n")
        self.assertFalse((destination / "gbot").is_symlink())
        launched = subprocess.run([str(destination / "gbot"), "argument with spaces"],
                                  text=True, capture_output=True, check=True)
        interpreter, argument = json.loads(launched.stdout)
        self.assertEqual(Path(interpreter).parent.resolve(), self.bin.resolve())
        self.assertEqual(argument, "argument with spaces")

    def test_macos_installers_stop_on_linux_without_user_writes(self):
        self.executable("uname", "print('Linux')\n")
        for name, args in (("install-calendar.sh", ()), ("install-feed.sh", ("/dev/gbot-test",))):
            with self.subTest(script=name):
                result = self.run_script(name, *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("requires macOS", result.stderr)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
