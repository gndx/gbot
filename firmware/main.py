"""GBOT availability monitor and USB command loop.

Starts when powered, restores state and rotation, and accepts commands from
the gbot host CLI over USB serial. Standalone controls:
    Short BOOT press: next availability state.
    Long BOOT press: cycle full-screen views.
    Case tap: next state, detected by the accelerometer.
    Sustained shake: temporary angry expression, then restore prior state."""

import gc
import random
import time

import rp2

import palette
from gc9a01 import Display
from face import Face
from hud import Hud
from limits import Limits
from link import Link
from sensors import Sensors

STATE_FILE = "state.txt"
LIMITS_FILE = "limits.txt"
LIMITS_SAVE_MS = 300_000   # minimum interval between flash writes
FRAME_MS = 33          # target about 30 fps for the face
ANGER_MS = 45_000      # temporary anger duration after shaking
HUD_EVERY = 2          # refresh the system view at half the frame rate
IDLE_MS = 120          # loop interval while the screen sleeps
FACE_MS = 45_000       # eyes and expressions between cards
CARD_MS = 8_000        # brief card inside the state ring
DATA_VIEW_MS = 60_000  # return to the same face and availability afterward
DATA_VIEWS = ("limits", "weather", "trm")
CALENDAR_VIEW_MS = 120_000
CALENDAR_LEAD_MS = 300_000

VIEWS = ("face", "hud", "limits", "weather", "trm", "calendar")

HELP = (
    "busy|hold|await|open  set availability and show the eyes",
    "next             next state (same as a short BOOT press)",
    "view [face|hud|limits|weather|trm|calendar]  select a view",
    "face: 45 s of eyes, then an 8 s card inside the state ring",
    "usage, weather, TRM: return to the previous face after 60 s",
    "weather [set temp10 code humidity epoch]  host weather data",
    "trm [set cents from_day to_day valid_for]  host USD/COP data",
    "calendar [set id seconds HH:MM title|clear]  next meeting",
    "calendar: alert 5 min early for 2 min; dismiss with BOOT or CLI",
    "rotate <0-3>     rotate the image in 90-degree steps",
    "state            availability, expression, and sensors",
    "bright <0-100>   display brightness",
    "sleep|wake       turn the display off/on",
    "ping             check the USB connection",
)


def load_state():
    """Restore state and rotation; every boot starts with the face view."""
    try:
        with open(STATE_FILE) as f:
            parts = f.read().split()
        state = palette.resolve(parts[0]) or palette.DEFAULT
        rot = int(parts[1]) % 4 if len(parts) > 1 else 0
        return state, rot, "face"
    except (OSError, ValueError, IndexError):
        return palette.DEFAULT, 0, "face"


def save_state(name, rot, view):
    try:
        with open(STATE_FILE, "w") as f:
            f.write("%s %d %s" % (name, rot, view))
    except OSError:
        pass  # Continue if flash is full or read-only.


def save_limits(pages):
    """Persist usage percentages across restarts.

    Only the host fetches provider data. Save percentages as a stale reference,
    but omit countdowns because the board cannot measure time while powered off.
    Each line contains TITLE label,pct label,pct."""
    try:
        with open(LIMITS_FILE, "w") as f:
            f.write("\n".join(pages))
    except OSError:
        pass  # Continue if flash is full or read-only.


def load_limits():
    """Return saved pages as [(title, [(label, percent, None), ...])]."""
    out = []
    try:
        with open(LIMITS_FILE) as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                wins = []
                for chunk in parts[1:]:
                    label, _, pct = chunk.partition(",")
                    try:
                        wins.append((label, int(pct), None))
                    except ValueError:
                        pass
                if wins:
                    out.append((parts[0], wins))
    except (OSError, ValueError):
        pass
    return out


class Button:
    """Read short and long BOOT presses in software.

    rp2.bootsel_button() briefly pauses flash access, so poll it between SPI
    transfers. RESET is wired to RUN and cannot act as another input. A long
    press fires at its threshold without waiting for release; only one long
    press threshold is used so one gesture cannot trigger multiple actions."""

    def __init__(self, every_ms=50, long_ms=600):
        self.every = every_ms
        self.long = long_ms
        self.at = 0
        self.down = False
        self.since = 0
        self.fired = False

    def poll(self, now):
        if time.ticks_diff(now, self.at) < self.every:
            return None
        self.at = now
        try:
            raw = rp2.bootsel_button()
        except AttributeError:
            return None
        if raw:
            if not self.down:
                self.down = True
                self.since = now
                self.fired = False
            elif (not self.fired
                    and time.ticks_diff(now, self.since) >= self.long):
                self.fired = True
                return "long"
        elif self.down:
            self.down = False
            if not self.fired:
                return "short"
        return None


class Tap:
    """Detect individual case taps with the accelerometer.

    Magnitude is approximately 1 g at rest regardless of orientation. Detect a
    deviation and apply a cooldown. Delay the action briefly so a sustained
    shake can cancel its initial tap before it changes the availability state."""

    def __init__(self, threshold=0.75, settle=320, cooldown=800):
        self.threshold = threshold
        self.settle = settle
        self.cooldown = cooldown
        self.last = 0
        self.armed = 0
        self.peak = 0.0

    def hit(self, now, magnitude):
        delta = abs(magnitude - 1.0)
        if delta > self.peak:
            self.peak = delta
        if (delta >= self.threshold
                and time.ticks_diff(now, self.last) >= self.cooldown):
            self.last = now
            self.armed = now or 1
        if self.armed and time.ticks_diff(now, self.armed) >= self.settle:
            self.armed = 0
            return True
        return False

    def cancel(self):
        self.armed = 0


class Shake:
    """Detect sustained movement with a leaky acceleration accumulator.

    Decay 0.86 at 30 fps lets a single impact subside while repeated movement
    crosses the threshold. A slowly adapting baseline absorbs calibration bias
    instead of integrating a constant error against a fixed 1 g reference."""

    def __init__(self, decay=0.86, level=2.4, cooldown=2500, ease=0.02):
        self.decay = decay
        self.level = level
        self.cooldown = cooldown
        self.ease = ease
        self.base = None
        self.energy = 0.0
        self.last = 0
        self.peak = 0.0

    def hit(self, now, magnitude):
        if self.base is None:
            self.base = magnitude
            return False
        self.base += (magnitude - self.base) * self.ease
        self.energy = self.energy * self.decay + abs(magnitude - self.base)
        if self.energy > self.peak:
            self.peak = self.energy
        if self.energy < self.level:
            return False
        if time.ticks_diff(now, self.last) < self.cooldown:
            return False
        self.last = now
        return True

    @property
    def active(self):
        """Remain active while movement continues, even after triggering.

        Do not clear accumulated energy on trigger: it suppresses tap detection
        throughout a sustained shake."""
        return self.energy > self.level * 0.5


class Monitor:
    def __init__(self):
        gc.collect()
        self.lcd = Display()
        state, rot, view = load_state()
        self.lcd.rotation(rot)
        self.face = Face(self.lcd, palette.STATES, palette.EXPRESSIONS, state)
        self.sensors = Sensors()
        self.sensors.accel()          # discard the first IMU sample
        self.hud = Hud(self.lcd, self.face.band, self.face.fb, self.sensors)
        # All views share one 38 KB eye-band framebuffer;
        # there is no space for a second copy.
        self.limits = Limits(self.lcd, self.face.band, self.face.fb)
        # Restore saved percentages as stale reference values.
        # Their age and reset countdown remain unknown until
        # the host supplies fresh data.
        for title, windows in load_limits():
            self.limits.set(title, windows)
        self.limits.stale_all()
        self.limits_saved = ""
        self.limits_at = 0
        self.limits_pending = False
        self.limits_touched = 0
        self.link = Link()
        self.button = Button()
        self.tap = Tap()
        self.shake = Shake()
        self.anger_at = 0        # anger start time, or zero when inactive
        self.anger_from = None   # face to restore when anger expires
        self.view = view
        self.card = None
        self.last_card = None
        self.calendar = None
        self.calendar_seen = []
        self.asleep = False
        self.started = time.ticks_ms()
        self.scene_at = self.started
        self.scene_ms = 0
        self.fps = 0
        self.free = gc.mem_free()
        self._frames = 0
        self._fps_at = self.started
        if view != "face":
            self.repaint()

    # ---- views and states ----

    def go(self, state):
        # A deliberate state change cancels temporary anger.
        # Do not undo the user-selected state 45 seconds later.
        self.anger_at = 0
        self.anger_from = None
        self._return_face(time.ticks_ms())
        if self.asleep:
            self.wake()
        self.face.request(state)
        save_state(state, self.lcd.rot, "face")

    def _return_face(self, now):
        """Restore eyes without changing availability or unnecessarily repainting the ring."""
        was_full = self.view != "face"
        if self.card is not None:
            self.limits.leave_card()
            # The face only clears remembered eye rows. A card can cover more
            # rows, so returning from a card must invalidate the entire band.
            self.face.dirty = (0, 111)
        self.card = None
        self.view = "face"
        self.scene_at = now
        self.scene_ms = 0
        if was_full and not self.asleep:
            self.face.repaint()

    def _show_card(self, kind, now):
        """Cover only the eye band and preserve the active state palette."""
        was_full = self.view != "face"
        self.card = kind
        self.last_card = kind
        self.view = "face"
        self.scene_at = now
        self.scene_ms = 0
        if self.asleep:
            self.wake()
            return
        if self.face.pending:
            # Consecutive state and view commands may leave a palette pending
            # until the blink. Apply it before covering the eyes.
            self.face._apply(self.face.pending)
        elif was_full:
            self.face.repaint()
        self.limits.enter_card(kind, self.face.pal)

    def _advance_scene(self, now):
        """Time scenes: eyes 45 s, cards 8 s, data views 60 s, calendar 120 s."""
        elapsed = max(0, time.ticks_diff(now, self.scene_at))
        self.scene_at = now
        if self.asleep:
            return
        if self.view in DATA_VIEWS or self.view == "calendar":
            self.scene_ms += elapsed
            timeout = CALENDAR_VIEW_MS if self.view == "calendar" else DATA_VIEW_MS
            if self.scene_ms >= timeout:
                self._return_face(now)
            return
        if self.view != "face":
            return
        self.scene_ms += elapsed
        if self.card is not None:
            if self.scene_ms >= CARD_MS:
                self._return_face(now)
            return
        if self.scene_ms < FACE_MS:
            return
        choices = self.limits.card_choices()
        if not choices:
            # Keep the eyes active without accumulating an unbounded idle timer.
            self.scene_ms = FACE_MS
            return
        if len(choices) > 1 and self.last_card in choices:
            choices = [kind for kind in choices if kind != self.last_card]
        self._show_card(choices[random.randint(0, len(choices) - 1)], now)

    def _tick_scene(self, now, ticks):
        self._advance_calendar(now)
        self._advance_scene(now)
        if self.asleep:
            return
        if self.card is not None:
            # Brightness and breathing follow availability even when a card
            # covers the eyes. Never call face.tick over a data card.
            self.lcd.backlight(self.face._breath(now) * self.face.gain)
            if ticks % HUD_EVERY == 0:
                self.limits.tick_card()
        elif self.view == "face":
            self.face.tick()
        elif ticks % HUD_EVERY == 0:
            self.lcd.backlight(self.face._breath(now) * self.face.gain)
            if self.view == "hud":
                self.hud.tick(self.face.name, self.fps, self.free)
            elif self.view == "limits":
                self.limits.tick()
            elif self.view == "weather":
                self.limits.tick_weather()
            elif self.view == "calendar":
                self.limits.tick_calendar()
            else:
                self.limits.tick_trm()

    def _remember_calendar(self):
        if (self.calendar and self.calendar["left"] <= CALENDAR_LEAD_MS
                and self.calendar["id"] not in self.calendar_seen):
            self.calendar_seen.append(self.calendar["id"])
            self.calendar_seen = self.calendar_seen[-8:]

    def _advance_calendar(self, now):
        data = self.calendar
        if data is None:
            return
        elapsed = max(0, time.ticks_diff(now, data["at"]))
        data["at"] = now
        data["left"] = max(0, data["left"] - elapsed)
        # Do not repeat an event after refresh, dismissal, or alert expiry.
        if (not self.asleep and 0 < data["left"] <= CALENDAR_LEAD_MS
                and data["id"] not in self.calendar_seen):
            self._remember_calendar()
            if self.card is not None:
                self.limits.leave_card()
            self.card = None
            if self.face.pending:
                self.face._apply(self.face.pending)
            self.view = "calendar"
            self.scene_at = now
            self.scene_ms = 0
            self.repaint()
            self.link.send("# board view=calendar")

    def _calendar(self, args):
        if not args:
            data = self.calendar
            return ("ok source=host available=0" if data is None else
                    "ok source=host available=1 id=%s starts_in=%d time=%s title=%s" %
                    (data["id"], data["left"] // 1000, data["clock"], data["title"]))
        if args == ["clear"]:
            self.calendar = None
            self.limits.set_calendar("--:--", "No upcoming meetings")
            if self.view == "calendar":
                self._return_face(time.ticks_ms())
            return "ok calendar=none"
        try:
            if args[0] != "set" or len(args) < 5:
                raise ValueError()
            key, seconds, clock = args[1], int(args[2]), args[3]
            if (not 1 <= len(key) <= 24 or not all(c in "0123456789abcdef" for c in key)
                    or not 0 < seconds <= 7 * 86400 or len(clock) != 5 or clock[2] != ":"
                    or not clock[:2].isdigit() or not clock[3:].isdigit()
                    or not 0 <= int(clock[:2]) <= 23 or not 0 <= int(clock[3:]) <= 59):
                raise ValueError()
            title = " ".join(args[4:])[:48]
        except (TypeError, ValueError):
            return "err calendar set id seconds HH:MM title"
        self.calendar = {"id": key, "left": seconds * 1000, "at": time.ticks_ms(),
                         "clock": clock, "title": title}
        self.limits.set_calendar(clock, title)
        return "ok calendar=" + key

    def cycle(self, announce=False):
        order = palette.CYCLE
        current = self.face.pending or self.face.name
        try:
            index = order.index(current)
        except ValueError:
            index = -1
        nxt = order[(index + 1) % len(order)]
        self.go(nxt)
        if announce:
            # A physical-board action is unsolicited, not a command reply:
            # prefix it with # so the CLI can distinguish it.
            self.link.send("# board state=" + nxt)
        return nxt

    def _limits(self, args):
        """Report usage with no arguments, or replace one account page.

        Arguments are TITLE followed by label,percent[,seconds_until_reset].
        Percentages are remaining capacity, calculated by the host."""
        if not args:
            return "ok " + self.limits.report()
        if args[0] == "clear":
            self.limits.clear()
            if self.card is not None and self.card != "WEATHER":
                self._return_face(time.ticks_ms())
            elif self.view == "limits":
                self.limits.refresh()
            self.limits_saved = ""
            self.limits_at = 0
            self.limits_pending = False
            save_limits([])
            return "ok limits=0"
        if args[0] == "page":
            n = self.limits.select(args[1] if len(args) > 1 else "next")
            if self.view == "limits":
                self.limits.refresh()
                self.scene_at = time.ticks_ms()
                self.scene_ms = 0
            return "ok page=%d" % n

        groups = []
        for arg in args[1:9]:
            f = arg.split(",")
            if len(f) < 2 or not f[0]:
                return "err limits requires label,pct[,seconds]"
            try:
                pct = int(f[1])
                secs = int(f[2]) if len(f) > 2 and f[2] else None
            except ValueError:
                return "err limits: pct and seconds must be integers"
            groups.append((f[0], pct, secs))
        if not groups:
            return "err limits requires at least one window"
        n = self.limits.set(args[0], groups)
        if not n:
            return "err limits: account capacity reached"
        self._store_limits()
        return "ok limits=%d" % n

    def _weather(self, args):
        if not args:
            return "ok " + self.limits.weather_report()
        if len(args) != 5 or args[0] != "set":
            return "err weather requires set temp10 code humidity epoch"
        try:
            self.limits.set_weather(*(int(value) for value in args[1:]))
        except (TypeError, ValueError):
            return "err weather: invalid data"
        return "ok " + self.limits.weather_report()

    def _trm(self, args):
        if not args:
            return "ok " + self.limits.trm_report()
        if len(args) != 5 or args[0] != "set":
            return "err trm requires set cents from_day to_day valid_for"
        try:
            self.limits.set_trm(*(int(value) for value in args[1:]))
        except (TypeError, ValueError):
            return "err trm: invalid data"
        return "ok " + self.limits.trm_report()

    def _store_limits(self):
        """Mark usage data for deferred saving by the main loop."""
        self.limits_pending = True
        self.limits_touched = time.ticks_ms()

    def _flush_limits(self, now):
        """Persist changed usage data at most once per five minutes.

        Wait two seconds after the latest update so multiple account lines sent by
        gbot limits --live are saved together. Avoid repeated writes of identical
        data to limit flash wear."""
        if not self.limits_pending:
            return
        if time.ticks_diff(now, self.limits_touched) < 2000:
            return
        if self.limits_at and time.ticks_diff(now, self.limits_at) < LIMITS_SAVE_MS:
            return
        self.limits_pending = False
        pages = self.limits.lines()
        blob = "|".join(pages)
        if blob == self.limits_saved:
            return
        self.limits_saved = blob
        self.limits_at = now
        save_limits(pages)

    def anger(self, announce=False):
        """Temporarily show anger after a shake, then restore the previous state.

        Repeated shakes restart the timer; an already deliberate busy state remains."""
        angry = palette.ANGRY
        now = time.ticks_ms()
        current = self.face.pending or self.face.name
        if current == angry:
            if self.anger_at:
                self.anger_at = now     # still angry: restart the timer
            return angry
        self.go(angry)                  # go() clears the previous timer
        self.anger_from = current
        self.anger_at = now
        if announce:
            self.link.send("# board state=" + angry)
        return angry

    def calm(self, now):
        """Restore the previous face after the temporary anger period."""
        if not self.anger_at:
            return
        if time.ticks_diff(now, self.anger_at) < ANGER_MS:
            return
        back = self.anger_from
        self.anger_at = 0
        self.anger_from = None
        if back and (self.face.pending or self.face.name) == palette.ANGRY:
            if self.view == "calendar":
                # Calming updates the underlying face without interrupting
                # the visible two-minute calendar alert.
                self.face.request(back)
                save_state(back, self.lcd.rot, "face")
            else:
                self.go(back)
            self.link.send("# board state=" + back)

    def step(self, announce=False):
        """Advance availability with one click, including from a card or HUD."""
        return self.cycle(announce=announce)

    def next_view(self, announce=False):
        """Cycle full-screen views on a long press without changing availability."""
        if self.view == "calendar":
            return self.set_view("face", announce)
        choices = []
        for title in ("CLAUDE", "CODEX"):
            for index, page in enumerate(self.limits.pages):
                if page.title == title:
                    choices.append(("limits", index))
                    break
        choices.extend((("weather", None), ("trm", None), ("hud", None), ("face", None)))
        current = (self.view, self.limits.page if self.view == "limits" else None)
        try:
            index = (choices.index(current) + 1) % len(choices)
        except ValueError:
            index = 0
        view, page = choices[index]
        if page is not None:
            self.limits.select(str(page))
        return self.set_view(view, announce)

    def set_view(self, view, announce=False):
        if view not in VIEWS:
            return self.view
        now = time.ticks_ms()
        if self.view == "calendar" or view == "calendar":
            self._remember_calendar()
        if view == "face":
            self._return_face(now)
            if self.asleep:
                self.wake()
        else:
            if self.card is not None:
                self.limits.leave_card()
            self.card = None
            if self.face.pending:
                self.face._apply(self.face.pending)
            self.view = view
            self.scene_at = now
            self.scene_ms = 0
            if self.asleep:
                self.wake()
            else:
                self.repaint()
        # Only manual view changes use this path; automatic cards never
        # write flash. load_state always starts with the face on boot.
        save_state(self.face.pending or self.face.name, self.lcd.rot, view)
        if announce:
            self.link.send("# board view=" + view)
        return self.view

    # ---- commands ----

    def handle(self, line):
        parts = line.strip().split()
        if not parts:
            return
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else None

        state = palette.resolve(cmd)
        if state:
            self.go(state)
            self.link.send("ok state=" + state)
            return

        if cmd == "view":
            if arg is None:
                other = "face" if self.view == "hud" else "hud"
                self.link.send("ok view=" + self.set_view(other))
            elif arg in VIEWS:
                self.link.send("ok view=" + self.set_view(arg))
            else:
                self.link.send("err view accepts face, hud, limits, weather, trm or calendar")
        elif cmd == "rotate":
            try:
                value = int(arg) % 4
            except (TypeError, ValueError):
                self.link.send("err rotate requires 0, 1, 2 or 3")
                return
            self.lcd.rotation(value)
            self.repaint()
            save_state(self.face.name, value, self.view)
            self.link.send("ok rotate=%d" % value)
        elif cmd == "next":
            self.link.send("ok state=" + self.cycle())
        elif cmd == "state" or cmd == "status":
            ax, ay, az = self.sensors.accel()
            self.link.send(
                "ok state=%s mood=%s view=%s rot=%d bright=%d sleep=%d fps=%d "
                "free=%d temp=%.1f volts=%.2f tilt=%.2f,%.2f,%.2f uptime=%d "
                "card=%s face_ms=%d card_ms=%d view_ms=%d"
                % (self.face.pending or self.face.name, self.face.mood,
                   self.view, self.lcd.rot, int(self.face.gain * 100),
                   1 if self.asleep else 0, self.fps, self.free,
                   self.sensors.chip_temp(), self.sensors.voltage() or 0.0,
                   ax, ay, az,
                   time.ticks_diff(time.ticks_ms(), self.started) // 1000,
                   self.card or "none",
                   self.scene_ms if self.view == "face" and self.card is None else 0,
                   self.scene_ms if self.card is not None else 0,
                   self.scene_ms if self.view in DATA_VIEWS or self.view == "calendar" else 0)
            )
        elif cmd == "bright":
            try:
                value = int(arg)
            except (TypeError, ValueError):
                self.link.send("err bright requires 0-100")
                return
            value = 0 if value < 0 else (100 if value > 100 else value)
            self.face.gain = value / 100.0
            self.link.send("ok bright=%d" % value)
        elif cmd == "tap":
            # Diagnostic: peak strength of the largest detected tap.
            self.link.send(
                "ok peak=%.2f threshold=%.2f shake=%.2f level=%.2f base=%.2f"
                % (self.tap.peak, self.tap.threshold, self.shake.peak,
                   self.shake.level, self.shake.base or 0.0))
            self.tap.peak = 0.0
            self.shake.peak = 0.0
        elif cmd == "press":
            # Diagnostic: use the same path as the physical button.
            if arg in ("short", None):
                self.step()
                self.link.send("ok view=%s state=%s page=%d"
                               % (self.view, self.face.pending or
                                  self.face.name, self.limits.page))
            elif arg == "long":
                self.next_view()
                self.link.send("ok view=%s" % self.view)
            elif arg == "shake":
                # Simulate a shake, including automatic state restoration.
                self.anger()
                self.link.send("ok state=%s back=%s in=%d"
                               % (self.face.pending or self.face.name,
                                  self.anger_from or "-", ANGER_MS // 1000))
            else:
                self.link.send("err press accepts short, long or shake")
        elif cmd == "limits":
            self.link.send(self._limits(parts[1:]))
        elif cmd == "weather":
            self.link.send(self._weather(parts[1:]))
        elif cmd == "trm":
            self.link.send(self._trm(parts[1:]))
        elif cmd == "calendar":
            self.link.send(self._calendar(parts[1:]))
        elif cmd == "sleep":
            self.sleep()
            self.link.send("ok sleep=1")
        elif cmd == "wake":
            self.wake()
            self.link.send("ok sleep=0")
        elif cmd == "ping":
            self.link.send("ok pong")
        elif cmd == "mem":
            gc.collect()
            self.link.send("ok free=%d fps=%d" % (gc.mem_free(), self.fps))
        elif cmd == "help":
            for text in HELP:
                self.link.send("# " + text)
            self.link.send("ok help")
        else:
            self.link.send("err unknown command: " + cmd)

    def repaint(self):
        """Paint the background of the active view."""
        if self.view == "hud":
            self.hud.enter(self.face.pal)
        elif self.view == "limits":
            self.limits.enter(self.face.pal)
        elif self.view == "weather":
            self.limits.enter_weather(self.face.pal)
        elif self.view == "trm":
            self.limits.enter_trm(self.face.pal)
        elif self.view == "calendar":
            self.limits.enter_calendar(self.face.pal)
        elif self.card is not None:
            # Rotation and wake must rebuild the whole ring before drawing
            # the card. Normal card alternation updates only the band.
            if self.face.pending:
                self.face._apply(self.face.pending)
            else:
                self.face.repaint()
            self.limits.enter_card(self.card, self.face.pal)
        else:
            self.face.repaint()

    def sleep(self):
        if not self.asleep:
            self._advance_scene(time.ticks_ms())
            self.asleep = True
            self.lcd.sleep()

    def wake(self):
        if self.asleep:
            self.asleep = False
            self.scene_at = time.ticks_ms()
            self.lcd.wake()
            self.repaint()

    # ---- main loop ----

    def run(self):
        self.link.send("ready state=%s view=%s" % (self.face.name, self.view))
        errors = 0
        ticks = 0
        while True:
            start = time.ticks_ms()
            try:
                line = self.link.readline()
                if line:
                    self.handle(line)

                # Weekly windows can exceed ticks_add limits.
                # Consume short elapsed intervals even when the
                # usage view is hidden.
                self.limits.advance(start)
                self._advance_calendar(start)

                press = self.button.poll(start)
                if press == "short":
                    self.step(announce=True)
                elif press == "long":
                    self.next_view(announce=True)

                if not self.asleep:
                    # A sustained shake takes precedence: its first impact
                    # must not also count as a button-like tap.
                    mag = self.sensors.magnitude()
                    self.calm(start)
                    self._flush_limits(start)
                    if self.shake.hit(start, mag):
                        self.tap.cancel()
                        self.anger(announce=True)
                    elif self.tap.hit(start, mag) and not self.shake.active:
                        self.cycle(announce=True)
                    ticks += 1
                    self._tick_scene(start, ticks)
                    self._frames += 1
                    elapsed = time.ticks_diff(start, self._fps_at)
                    if elapsed >= 2000:
                        self.fps = self._frames * 1000 // elapsed
                        self._frames = 0
                        self._fps_at = start
                        self.free = gc.mem_free()
                errors = 0
            except Exception as exc:   # KeyboardInterrupt is intentionally not caught here
                errors += 1
                self.link.send("err %s" % exc)
                if errors > 20:
                    raise
                time.sleep_ms(200)

            budget = IDLE_MS if self.asleep else FRAME_MS
            rest = budget - time.ticks_diff(time.ticks_ms(), start)
            if rest > 0:
                time.sleep_ms(rest)


if __name__ == "__main__":
    Monitor().run()
