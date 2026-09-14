"""Nonblocking USB serial command channel.

MicroPython's REPL and this channel share USB CDC. poll(0) leaves the animation
running when no command is pending. Ctrl-C remains enabled so mpremote can
recover the REPL and upload files without unplugging the board."""

import select
import sys

_MAX_LINE = 96


class Link:
    def __init__(self):
        self._poll = select.poll()
        self._poll.register(sys.stdin, select.POLLIN)
        self._buf = ""

    def readline(self):
        """Return the next complete received line, or None."""
        while self._poll.poll(0):
            ch = sys.stdin.read(1)
            if not ch:
                return None
            if ch == "\n" or ch == "\r":
                if self._buf:
                    line = self._buf
                    self._buf = ""
                    return line
            else:
                self._buf += ch
                if len(self._buf) > _MAX_LINE:
                    self._buf = ""
        return None

    def send(self, msg):
        try:
            sys.stdout.write(msg + "\n")
        except Exception:
            pass  # Host disconnected: keep the standalone board running.
