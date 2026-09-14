"""GBOT usage and host-data views with small, selective updates.

Percentages represent remaining capacity. The renderer shares the face buffer
and transfers RGB565 strips. Bars animate on entry for 420 ms; a subtle
freshness indicator then pulses without repainting the full display."""

import framebuf
import gc
import math
import time

from gc9a01 import rgb565

# Load glyphs after the face builds its temporary background data.
# This shares the heap without changing the face renderer or allocating
# another framebuffer.
FONTS = None

BRANDS = {"CLAUDE": (232, 165, 130), "CODEX": (127, 171, 245)}
_FALLBACK = (180, 190, 207)
_BG_RGB = (6, 9, 14)
_BG = rgb565(*_BG_RGB)
_WHITE = (240, 242, 247)
_MUTED = (123, 134, 151)
_DIM = (67, 78, 95)
_TRACK = rgb565(27, 34, 45)
MAX_WIN = 3
MAX_PAGES = 4
STALE_MS = 300_000
STRIP_H = 82
CX = 120
_BAR_X = 76
_BAR_W = 94
_BAR_H = 4
_BAR_PAD = 2
_INTRO_MS = 420
_PULSE_MS = 120
_CLOCK_Y = 145
_CLOCK_H = 16
_CARD_X, _CARD_Y, _CARD_W, _CARD_H = 32, 60, 176, 112
_WEATHER_COLOR = (143, 207, 195)
_HUM_X, _HUM_Y, _HUM_W = 38, 184, 164
WEATHER_STALE_S = 900
_TRM_COLOR = (167, 218, 157)
_CALENDAR_COLOR = (192, 167, 244)

# A 5x7 matrix supplies card and panel digits. Titles and details use Inter,
# so no additional font is needed in the heap.
_CARD_DIGITS = {
    "0": (5, b"\x0e\x11\x11\x11\x11\x11\x0e"),
    "1": (5, b"\x04\x0c\x04\x04\x04\x04\x1f"),
    "2": (5, b"\x0e\x11\x01\x02\x04\x08\x1f"),
    "3": (5, b"\x1f\x01\x02\x06\x01\x11\x0e"),
    "4": (5, b"\x02\x06\x0a\x12\x1f\x02\x02"),
    "5": (5, b"\x1f\x10\x1e\x01\x01\x11\x0e"),
    "6": (5, b"\x06\x08\x10\x1e\x11\x11\x0e"),
    "7": (5, b"\x1f\x01\x02\x04\x08\x08\x08"),
    "8": (5, b"\x0e\x11\x11\x0e\x11\x11\x0e"),
    "9": (5, b"\x0e\x11\x11\x0f\x01\x02\x0c"),
    "%": (5, b"\x19\x19\x02\x04\x08\x13\x13"),
    "-": (3, b"\x00\x00\x00\x07\x00\x00\x00"),
    "°": (3, b"\x02\x05\x02\x00\x00\x00\x00"),
    "C": (5, b"\x0e\x11\x10\x10\x10\x11\x0e"),
    ".": (1, b"\x00\x00\x00\x00\x00\x00\x01"),
    ",": (2, b"\x00\x00\x00\x00\x00\x01\x02"),
    ":": (1, b"\x00\x01\x01\x00\x01\x01\x00"),
}


def _card_title(fb, title, palette):
    """Center the visible glyph ink, excluding Inter side bearings."""
    glyphs = FONTS["brand"][1]
    left, right, top, cursor = 255, 0, 255, 0
    for char in title:
        _, advance, data = glyphs[char]
        for n in range(0, len(data), 4):
            left = min(left, cursor + data[n + 1])
            right = max(right, cursor + data[n + 1] + data[n + 2])
            top = min(top, data[n])
        cursor += advance
    _text(fb, title, (_CARD_W - (right - left)) // 2 - left, 12 - top,
          "brand", palette, rows=_CARD_H)


def _card_number(fb, text, palette):
    """Center dotted digits and their unit as one visual group."""
    columns = sum(_CARD_DIGITS[char][0] for char in text) + len(text) - 1
    # 100% fits with 5 px dots; longer negative temperatures scale to fit.
    pitch = min(7, (_CARD_W - 16 + 2) // columns)
    x = (_CARD_W - (columns * pitch - 2)) // 2
    y = 47 + (47 - (7 * pitch - 2)) // 2
    _matrix_text(fb, text, x, y, pitch, palette)


def _matrix_width(text, pitch):
    if not text:
        return 0
    columns = sum(_CARD_DIGITS[char][0] for char in text) + len(text) - 1
    return columns * pitch - 2


def _matrix_text(fb, text, x, y, pitch, palette, top=0):
    """Draw RGB565 dots clipped to the current strip framebuffer."""
    dot = pitch - 2
    for char in text:
        width, rows = _CARD_DIGITS[char]
        for row, bits in enumerate(rows):
            for col in range(width):
                if bits & (1 << (width - col - 1)):
                    dx, dy = x + col * pitch, y + row * pitch - top
                    fb.fill_rect(dx, dy, dot, dot, palette[15 if dot <= 2 else 7])
                    if dot > 2:
                        fb.fill_rect(dx + 1, dy, dot - 2, dot, palette[15])
                        fb.fill_rect(dx, dy + 1, dot, dot - 2, palette[15])
        x += (width + 1) * pitch


def _hero_number(fb, value, unit, palette, top):
    """Draw the main dotted value with a smaller, muted unit."""
    width = _matrix_width(value, 8)
    group = width + (7 + _matrix_width(unit, 4) if unit else 0)
    left = CX - group // 2
    _matrix_text(fb, value, left, 68, 8, palette, top)
    _matrix_text(fb, unit, left + width + 7, 96, 4, _MUTED_PAL, top)


def _cop(cents):
    whole = str(cents // 100)
    if len(whole) > 3:
        whole = whole[:-3] + "." + whole[-3:]
    return whole + ",%02d" % (cents % 100)


def _date_label(day):
    return "%02d/%02d/%04d" % (day % 100, day // 100 % 100, day // 10000)


def _valid_date(day):
    year, month, date = day // 10000, day // 100 % 100, day % 100
    if not 2000 <= year <= 2099 or not 1 <= month <= 12:
        return False
    days = (31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return 1 <= date <= days[month - 1]


def _palette(rgb, background=_BG_RGB):
    return tuple(rgb565(*tuple(background[i] + (rgb[i] - background[i]) * a // 15
                               for i in range(3))) for a in range(16))


def _load_fonts():
    global FONTS
    if FONTS is None:
        gc.collect()
        from limits_font import FONTS as fonts
        FONTS = fonts
        gc.collect()


def _weather_condition(code):
    if code == 0:
        return "CLEAR"
    if code in (1, 2):
        return "PARTLY CLOUDY"
    if code == 3:
        return "OVERCAST"
    if code in (45, 48):
        return "FOG"
    if 51 <= code <= 57:
        return "DRIZZLE"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "RAIN"
    if 71 <= code <= 77 or code in (85, 86):
        return "SNOW"
    if 95 <= code <= 99:
        return "THUNDERSTORM"
    return "VARIABLE"


_WHITE_PAL = _palette(_WHITE)
_MUTED_PAL = _palette(_MUTED)
_DIM_PAL = _palette(_DIM)


def _width(text, font, spacing=0):
    glyphs = FONTS[font][1]
    return sum(glyphs.get(char, glyphs.get(" ", (0, 0, b"")))[1]
               for char in text) + max(0, len(text) - 1) * spacing


def _text(fb, text, x, y, font, palette, top=0, rows=240, spacing=0):
    """Draw pre-rasterized 16-level Inter glyphs using horizontal runs."""
    glyphs = FONTS[font][1]
    for char in text:
        glyph = glyphs.get(char, glyphs.get(" "))
        if glyph is None:
            continue
        _, advance, data = glyph
        for n in range(0, len(data), 4):
            row = y + data[n] - top
            if 0 <= row < rows:
                fb.hline(x + data[n + 1], row, data[n + 2],
                         palette[data[n + 3]])
        x += advance + spacing


def _center(fb, text, y, font, palette, top=0, rows=240, spacing=0):
    _text(fb, text, CX - _width(text, font, spacing) // 2, y, font,
          palette, top, rows, spacing)


def _meeting_title(title):
    """Fit one centered line using the real glyph widths."""
    glyphs = FONTS["brand"][1]
    title = " ".join("".join(c if c in glyphs else " " for c in title).split()) or "Meeting"
    if _width(title, "brand") <= 186:
        return title
    while _width(title + "...", "brand") > 186:
        title = title[:-1].rstrip()
    return title + "..."


def _meeting_clock(clock):
    """Format the display clock; the protocol keeps local 24-hour time."""
    if clock == "--:--":
        return clock, ""
    hour = int(clock[:2])
    return "%02d%s" % (hour % 12 or 12, clock[2:]), "AM" if hour < 12 else "PM"


def _pill(fb, x, y, width, height, color):
    """Draw a compact capsule, preserving partial corner pixels at height four."""
    if width <= 0:
        return
    if height == 4 and width >= 4:
        fb.hline(x + 1, y, width - 2, color)
        fb.fill_rect(x, y + 1, width, 2, color)
        fb.hline(x + 1, y + 3, width - 2, color)
    else:
        fb.fill_rect(x, y, width, height, color)


def _human(secs):
    if secs < 0:
        return "--"
    if secs >= 86400:
        return "%dd %dh" % (secs // 86400, secs % 86400 // 3600)
    if secs >= 3600:
        return "%dh %02dm" % (secs // 3600, secs % 3600 // 60)
    return "%02d:%02d" % (secs // 60, secs % 60)


def _worst(page):
    return min(range(len(page.pct)), key=lambda i: page.pct[i])


def _row_y(count, index):
    if count == 1:
        return 187
    if count == 2:
        return 175 + index * 21
    return 168 + index * 16


class _Page:
    """One account usage page with the time its data arrived."""

    __slots__ = ("title", "labels", "pct", "reset_left", "age", "clock_at")

    def __init__(self, title):
        self.title = title
        self.labels = []
        self.pct = []
        self.reset_left = []
        self.age = 0
        self.clock_at = time.ticks_ms()


class Limits:
    def __init__(self, lcd, band, fb):
        self.lcd = lcd
        self.buf = band          # reused as a strip drawing buffer
        self.pages = []
        self.page = 0
        self._clock = None
        self._dirty = True
        self._stale = False
        self._intro_at = time.ticks_ms()
        self._pulse_at = self._intro_at
        self._fill = 0.0
        self._pulse_x = CX
        self._brand = _FALLBACK
        self._brand_pal = _palette(_FALLBACK)
        self._bar_color = self._brand_pal[15]
        self._weather = None
        self._card_kind = None
        self._card_key = None
        self._weather_screen_key = None
        self._trm = None
        self._trm_screen_key = None
        self._calendar_content = ("--:--", "No upcoming meetings")
        self._calendar_screen_key = None

    # ---- data ----

    def set(self, title, groups):
        """Create or replace an account page.

        groups: [(window_label, percent_remaining, seconds_until_reset_or_None)]"""
        title = title[:8].upper()
        page = None
        for p in self.pages:
            if p.title == title:
                page = p
                break
        if page is None:
            if len(self.pages) >= MAX_PAGES:
                return 0
            page = _Page(title)
            self.pages.append(page)

        now = time.ticks_ms()
        page.labels = []
        page.pct = []
        page.reset_left = []
        for label, pct, secs in groups[:MAX_WIN]:
            page.labels.append(label[:4].upper())
            page.pct.append(0 if pct < 0 else (100 if pct > 100 else pct))
            page.reset_left.append(None if secs is None else max(0, secs))
        page.age = 0
        page.clock_at = now
        self._dirty = True
        return len(page.labels)

    def clear(self):
        self.pages = []
        self.page = 0
        self._dirty = True

    def lines(self):
        """Serialize usage labels and percentages for flash storage.

        Do not persist countdowns: the board cannot know how long it was powered off."""
        return ["%s %s" % (p.title,
                           " ".join("%s,%d" % (p.labels[i], p.pct[i])
                                    for i in range(len(p.labels))))
                for p in self.pages]

    def stale_all(self):
        """Mark restored values as stale because their original age is unknown."""
        now = time.ticks_ms()
        for p in self.pages:
            p.age = STALE_MS // 1000 + 1
            p.clock_at = now
        self._dirty = True

    def next_page(self):
        """Advance and return the page index, wrapping to zero."""
        self._dirty = True
        if len(self.pages) < 2:
            self.page = 0
            return 0
        self.page = (self.page + 1) % len(self.pages)
        return self.page

    def select(self, arg):
        """Select by index or next; return the active index."""
        if arg == "next":
            return self.next_page()
        try:
            n = int(arg)
        except ValueError:
            return self.page
        if self.pages:
            self.page = n % len(self.pages)
        self._dirty = True
        return self.page

    def report(self):
        """Return a CLI status line covering all saved pages."""
        if not self.pages:
            return "limits=0"
        now = time.ticks_ms()
        parts = ["limits=%d" % len(self.pages), "page=%d" % self.page]
        oldest = 0
        for p in self.pages:
            wins = ";".join(
                "%s,%d,%d" % (p.labels[i], p.pct[i], self._left(p, i, now))
                for i in range(len(p.labels)))
            parts.append("%s:%s" % (p.title, wins))
            if p.age > oldest:
                oldest = p.age
        parts.append("age=%d" % oldest)
        return " ".join(parts)

    def _left(self, page, i, now):
        """Return seconds until reset, or -1 if unknown."""
        self._advance_page(page, now)
        left = page.reset_left[i]
        if left is None:
            return -1
        return left

    def _advance_page(self, page, now):
        """Advance page age and countdowns without creating a future tick.

        Weekly windows can exceed MicroPython ticks_add limits. Store seconds remaining
        and consume short elapsed intervals to avoid ticks interval overflow."""
        elapsed_ms = time.ticks_diff(now, page.clock_at)
        if elapsed_ms < 1000:
            return
        elapsed = elapsed_ms // 1000
        page.clock_at = time.ticks_add(page.clock_at, elapsed * 1000)
        page.age += elapsed
        for i in range(len(page.reset_left)):
            left = page.reset_left[i]
            if left is not None:
                page.reset_left[i] = max(0, left - elapsed)

    def advance(self, now):
        """Keep countdowns current while any view is visible."""
        for page in self.pages:
            self._advance_page(page, now)
        self._advance_weather(now)
        self._advance_trm(now)

    # ---- cards inside the ring ----

    def set_weather(self, temp_tenths, code, humidity, observed_at):
        if (not -900 <= temp_tenths <= 600 or not 0 <= code <= 99 or
                not 0 <= humidity <= 100 or observed_at <= 0):
            raise ValueError("invalid weather data")
        self._weather = {"temp": temp_tenths, "code": code,
                         "humidity": humidity, "observed": observed_at,
                         "age": 0, "clock_at": time.ticks_ms()}
        return True

    def _advance_weather(self, now):
        data = self._weather
        if data is None:
            return
        elapsed = time.ticks_diff(now, data["clock_at"]) // 1000
        if elapsed > 0:
            data["age"] += elapsed
            data["clock_at"] = time.ticks_add(data["clock_at"], elapsed * 1000)

    def weather_report(self):
        self._advance_weather(time.ticks_ms())
        data = self._weather
        if data is None:
            return "source=host available=0 city=Medellin"
        return ("source=host available=1 city=Medellin temp_tenths=%d "
                "temperature=%.1f code=%d humidity=%d observed=%d age=%d stale=%d"
                % (data["temp"], data["temp"] / 10, data["code"],
                   data["humidity"], data["observed"], data["age"],
                   1 if data["age"] > WEATHER_STALE_S else 0))

    def card_choices(self):
        choices = [p.title for p in self.pages
                   if p.title in ("CLAUDE", "CODEX") and p.pct]
        self._advance_weather(time.ticks_ms())
        # Brief cards have no stale-data label: omit outdated weather until
        # the next host update.
        if self._weather and self._weather["age"] <= WEATHER_STALE_S:
            choices.append("WEATHER")
        return choices

    def enter_card(self, kind, pal):
        """Draw only inside the black eye rectangle, preserving the state ring."""
        _load_fonts()
        self._card_kind = kind.upper()
        self._card_key = None
        self.tick_card()

    def leave_card(self):
        self._card_kind = None
        self._card_key = None
        view = memoryview(self.buf)[:_CARD_W * _CARD_H * 2]
        fb = framebuf.FrameBuffer(view, _CARD_W, _CARD_H, framebuf.RGB565)
        fb.fill(0)
        self.lcd.blit(view, _CARD_X, _CARD_Y, _CARD_W, _CARD_H)

    def _card_content(self):
        kind = self._card_kind
        now = time.ticks_ms()
        if kind == "WEATHER":
            self._advance_weather(now)
            data = self._weather
            color = _WEATHER_COLOR
            if data is None:
                return ("Medellín", None, "", color, True)
            stale = data["age"] > WEATHER_STALE_S
            value = str(int(round(data["temp"] / 10)))
            return ("Medellín", value, "°C", color, stale)
        for page in self.pages:
            if page.title == kind and page.pct:
                self._advance_page(page, now)
                stale = page.age > STALE_MS // 1000
                return (page.title[:1] + page.title[1:].lower(),
                        str(page.pct[_worst(page)]), "%",
                        BRANDS.get(page.title, _FALLBACK), stale)
        return ("GBOT", None, "", _FALLBACK, True)

    def tick_card(self):
        if self._card_kind is None:
            return
        content = self._card_content()
        if content == self._card_key:
            return
        self._card_key = content
        title, value, unit, color, stale = content
        background = (0, 0, 0)
        if stale:
            color = tuple(channel * 3 // 4 for channel in color)
        brand = _palette(color, background)
        view = memoryview(self.buf)[:_CARD_W * _CARD_H * 2]
        fb = framebuf.FrameBuffer(view, _CARD_W, _CARD_H, framebuf.RGB565)
        fb.fill(0)
        _card_title(fb, title, brand)
        _card_number(fb, "--" if value is None else value + unit, brand)
        self.lcd.blit(view, _CARD_X, _CARD_Y, _CARD_W, _CARD_H)

    # ---- full-screen views, independent of eye cards ----

    def set_calendar(self, clock, title):
        self._calendar_content = (clock, title)

    def enter_calendar(self, pal):
        self._calendar_screen_key = None
        self.tick_calendar()

    def _render_calendar(self, fb, top, rows, content):
        title, clock, period = content
        _center(fb, title, 51, "brand", self._brand_pal, top, rows)
        width = _matrix_width(clock, 8)
        _matrix_text(fb, clock, CX - width // 2, 87, 8, _WHITE_PAL, top)
        _center(fb, period, 158, "brand", _MUTED_PAL, top, rows, 2)

    def tick_calendar(self):
        if self._calendar_content == self._calendar_screen_key:
            return
        _load_fonts()
        self._calendar_screen_key = self._calendar_content
        self._brand_pal = _palette(_CALENDAR_COLOR)
        clock, period = _meeting_clock(self._calendar_content[0])
        content = (_meeting_title(self._calendar_content[1]), clock, period)
        for top in range(0, 240, STRIP_H):
            rows = min(STRIP_H, 240 - top)
            view = memoryview(self.buf)[:240 * rows * 2]
            fb = framebuf.FrameBuffer(view, 240, rows, framebuf.RGB565)
            fb.fill(_BG)
            self._render_calendar(fb, top, rows, content)
            self.lcd.blit(view, 0, top, 240, rows)

    def set_trm(self, cents, from_day, to_day, valid_for):
        if (not 1 <= cents <= 9999999 or not _valid_date(from_day)
                or not _valid_date(to_day) or from_day > to_day
                or not 0 < valid_for <= 32 * 86400):
            raise ValueError("invalid value or validity period")
        self._trm = {"cents": cents, "from": from_day, "to": to_day,
                     "left": valid_for, "clock_at": time.ticks_ms()}

    def _advance_trm(self, now):
        data = self._trm
        if data is None:
            return
        elapsed = time.ticks_diff(now, data["clock_at"]) // 1000
        if elapsed > 0:
            data["left"] = max(0, data["left"] - elapsed)
            data["clock_at"] = time.ticks_add(data["clock_at"], elapsed * 1000)

    def trm_report(self):
        self._advance_trm(time.ticks_ms())
        data = self._trm
        if data is None:
            return "source=host available=0 pair=USD-COP"
        return ("source=host available=1 pair=USD-COP cents=%d from=%d to=%d "
                "valid_for=%d stale=%d" % (data["cents"], data["from"], data["to"],
                                          data["left"], 1 if data["left"] <= 0 else 0))

    def _trm_content(self):
        self._advance_trm(time.ticks_ms())
        data = self._trm
        if data is None:
            return ("--", "NO DATA", "WAITING FOR TRM", True)
        return (_cop(data["cents"]),
                "FROM " + _date_label(data["from"]),
                "UNTIL " + _date_label(data["to"]), data["left"] <= 0)

    def enter_trm(self, pal):
        self._trm_screen_key = None
        self.tick_trm()

    def _render_trm(self, fb, top, rows, content):
        value, stale = content[0], content[-1]
        _center(fb, "TRM", 60, "brand", self._brand_pal, top, rows)
        palette = _MUTED_PAL if stale else _WHITE_PAL
        columns = sum(_CARD_DIGITS[char][0] for char in value) + len(value) - 1
        pitch = min(8, 214 // columns)
        width = _matrix_width(value, pitch)
        _matrix_text(fb, value, CX - width // 2, 98 + (54 - (7 * pitch - 2)) // 2,
                     pitch, palette, top)
        label = ("OUTDATED" if self._trm else "NO DATA") if stale else "1 USD IN COP"
        _center(fb, label, 157, "micro", _MUTED_PAL, top, rows, 1)

    def tick_trm(self):
        content = self._trm_content()
        if content == self._trm_screen_key:
            return
        _load_fonts()
        self._trm_screen_key = content
        self._stale = content[-1]
        self._brand_pal = _palette(_TRM_COLOR)
        self._bar_color = self._brand_pal[9 if self._stale else 15]
        for top in range(0, 240, STRIP_H):
            rows = min(STRIP_H, 240 - top)
            view = memoryview(self.buf)[:240 * rows * 2]
            fb = framebuf.FrameBuffer(view, 240, rows, framebuf.RGB565)
            fb.fill(_BG)
            self._render_trm(fb, top, rows, content)
            self.lcd.blit(view, 0, top, 240, rows)

    def _weather_screen_content(self):
        self._advance_weather(time.ticks_ms())
        data = self._weather
        if data is None:
            return ("-", "NO DATA", None, "WAITING FOR WEATHER", True)
        stale = data["age"] > WEATHER_STALE_S
        # The protocol uses UNIX UTC; Medellin uses UTC-5 year-round.
        # Compute only hour/minute to avoid depending on the MicroPython epoch.
        local = data["observed"] - 5 * 3600
        updated = "UPDATED %02d:%02d" % ((local // 3600) % 24,
                                               (local // 60) % 60)
        return (str(int(round(data["temp"] / 10))),
                "OUTDATED" if stale else _weather_condition(data["code"]),
                data["humidity"], updated, stale)

    def enter_weather(self, pal):
        """Show Medellin weather with the same typography as usage pages."""
        self._paint_weather(self._weather_screen_content())

    def _paint_weather(self, content):
        _load_fonts()
        self._weather_screen_key = content
        self._stale = content[-1]
        self._brand = _WEATHER_COLOR
        self._brand_pal = _palette(self._brand)
        self._bar_color = self._brand_pal[9 if self._stale else 15]
        self._pulse_x = CX + _width("Medellín", "brand") // 2 + 10
        self._fill = 1.0 if self._stale else 0.0
        top = 0
        while top < 240:
            rows = min(STRIP_H, 240 - top)
            view = memoryview(self.buf)[:240 * rows * 2]
            fb = framebuf.FrameBuffer(view, 240, rows, framebuf.RGB565)
            fb.fill(_BG)
            self._render_weather(fb, top, rows, content)
            self.lcd.blit(view, 0, top, 240, rows)
            top += rows
        self._intro_at = time.ticks_ms()
        self._pulse_at = self._intro_at

    def _render_weather(self, fb, top, rows, content):
        value, condition, humidity, updated, stale = content
        palette = _MUTED_PAL if stale else _WHITE_PAL
        _center(fb, "GBOT", 19, "micro", _DIM_PAL, top, rows, 3)
        _center(fb, "Medellín", 39, "brand", self._brand_pal, top, rows)
        if humidity is not None:
            self._dot(fb, self._pulse_x, 45 - top, 0.65)
        unit = "°C" if humidity is not None else ""
        _hero_number(fb, value, unit, palette, top)
        if stale:
            _center(fb, condition, 127, "micro", _MUTED_PAL, top, rows, 1)
        _center(fb, updated, _CLOCK_Y, "small", _MUTED_PAL, top, rows)
        if humidity is not None:
            _text(fb, "HUMIDITY", _HUM_X, 170, "micro", _MUTED_PAL, top, rows)
            label = "%d%%" % humidity
            _text(fb, label, 204 - _width(label, "micro"), 170, "micro",
                  palette, top, rows)
            self._humidity_bar(fb, _HUM_X, _HUM_Y - top, humidity)
        _center(fb, "COLOMBIA", 200, "micro", _DIM_PAL, top, rows, 1)
        _pill(fb, CX - 4, 218 - top, 8, 3, self._bar_color)

    def _humidity_bar(self, fb, x, y, humidity):
        _pill(fb, x, y, _HUM_W, _BAR_H, _TRACK)
        fill = int(_HUM_W * humidity * self._fill / 100 + 0.5)
        _pill(fb, x, y, fill, _BAR_H, self._bar_color)

    def tick_weather(self):
        content = self._weather_screen_content()
        if content != self._weather_screen_key:
            self._paint_weather(content)
            return
        if content[2] is None:
            return
        now = time.ticks_ms()
        if self._fill < 1.0:
            t = min(1.0, time.ticks_diff(now, self._intro_at) / _INTRO_MS)
            self._fill = 1 - (1 - t) ** 3
            width, height = _HUM_W + _BAR_PAD * 2, _BAR_H + _BAR_PAD * 2
            view = memoryview(self.buf)[:width * height * 2]
            fb = framebuf.FrameBuffer(view, width, height, framebuf.RGB565)
            fb.fill(_BG)
            self._humidity_bar(fb, _BAR_PAD, _BAR_PAD, content[2])
            self.lcd.blit(view, _HUM_X - _BAR_PAD, _HUM_Y - _BAR_PAD,
                          width, height)
        if not self._stale and time.ticks_diff(now, self._pulse_at) >= _PULSE_MS:
            self._pulse_at = now
            intensity = 0.65 + 0.20 * math.sin((now % 4800) * math.pi / 2400)
            view = memoryview(self.buf)[:11 * 11 * 2]
            fb = framebuf.FrameBuffer(view, 11, 11, framebuf.RGB565)
            fb.fill(_BG)
            self._dot(fb, 5, 5, intensity)
            self.lcd.blit(view, self._pulse_x - 5, 40, 11, 11)

    def enter(self, pal):
        self._dirty = True
        self.paint()

    def refresh(self):
        self._dirty = True

    def paint(self):
        """Render three strips using the same buffer without a second framebuffer."""
        _load_fonts()
        self._dirty = False
        self._clock = None
        self._fill = 0.0
        if self.pages:
            page = self.pages[self.page]
            self._advance_page(page, time.ticks_ms())
            self._stale = page.age > STALE_MS // 1000
            self._brand = BRANDS.get(page.title, _FALLBACK)
            self._brand_pal = _palette(self._brand)
            self._bar_color = self._brand_pal[9 if self._stale else 15]
            title = page.title[:1] + page.title[1:].lower()
            self._pulse_x = CX + _width(title, "brand") // 2 + 10
            self._clock = self._clock_str(page)
            if self._stale:
                self._fill = 1.0
        top = 0
        while top < 240:
            rows = min(STRIP_H, 240 - top)
            view = memoryview(self.buf)[:240 * rows * 2]
            fb = framebuf.FrameBuffer(view, 240, rows, framebuf.RGB565)
            fb.fill(_BG)
            self._render(fb, top, rows)
            self.lcd.blit(view, 0, top, 240, rows)
            top += rows
        self._intro_at = time.ticks_ms()
        self._pulse_at = self._intro_at

    def _render(self, fb, top, rows):
        _center(fb, "GBOT", 19, "micro", _DIM_PAL, top, rows, 3)
        if not self.pages:
            _center(fb, "No data", 87, "brand", _WHITE_PAL, top, rows)
            _center(fb, "CONNECT ACCOUNTS", 114, "micro", _MUTED_PAL,
                    top, rows, 1)
            _center(fb, "gbot claude / gbot codex", 142, "small", _MUTED_PAL,
                    top, rows)
            return

        page = self.pages[self.page]
        title = page.title[:1] + page.title[1:].lower()
        _center(fb, title, 39, "brand", self._brand_pal, top, rows)
        self._dot(fb, self._pulse_x, 45 - top, 0.65)

        value = str(page.pct[_worst(page)])
        palette = _MUTED_PAL if self._stale else _WHITE_PAL
        _hero_number(fb, value, "%", palette, top)
        if self._stale:
            _center(fb, "OUTDATED", 127, "micro", _MUTED_PAL, top, rows, 1)
        _center(fb, self._clock, _CLOCK_Y, "small", _MUTED_PAL, top, rows)

        for i, label in enumerate(page.labels):
            y = _row_y(len(page.labels), i)
            _text(fb, label, 38, y - 2, "micro", _MUTED_PAL, top, rows)
            value = "%d%%" % page.pct[i]
            _text(fb, value, 204 - _width(value, "micro"), y - 2,
                  "micro", palette, top, rows)
            self._bar(fb, _BAR_X, y - top, page.pct[i], self._fill)

        # An active capsule and small dots identify the saved account pages.
        left = CX - (len(self.pages) * 13 - 5) // 2
        for i in range(len(self.pages)):
            color = self._bar_color if i == self.page else _TRACK
            width = 8 if i == self.page else 3
            x = left + i * 13 + (0 if i == self.page else 2)
            _pill(fb, x, 218 - top, width, 3, color)

    def _bar(self, fb, x, y, pct, fraction):
        _pill(fb, x, y, _BAR_W, _BAR_H, _TRACK)
        fill = int(_BAR_W * pct * fraction / 100 + 0.5)
        _pill(fb, x, y, fill, _BAR_H, self._bar_color)

    def _dot(self, fb, x, y, intensity):
        """Rebuild an 11-pixel halo over its original background."""
        palette = _DIM_PAL if self._stale else self._brand_pal
        for dy in range(-5, 6):
            for dx in range(-5, 6):
                distance = math.sqrt(dx * dx + dy * dy)
                if distance <= 5:
                    coverage = min(1.0, max(0.0, 2.4 - distance))
                    glow = max(0.0, (5.0 - distance) / 5.0) * 0.12
                    alpha = int(min(1.0, (coverage + glow) * intensity) * 15)
                    fb.pixel(x + dx, y + dy, palette[alpha])

    def _clock_str(self, page):
        left = self._left(page, _worst(page), time.ticks_ms())
        return "RESETS IN " + _human(left)

    def _clock_patch(self, page):
        text = self._clock_str(page)
        if text == self._clock:
            return
        self._clock = text
        view = memoryview(self.buf)[:240 * _CLOCK_H * 2]
        fb = framebuf.FrameBuffer(view, 240, _CLOCK_H, framebuf.RGB565)
        fb.fill(_BG)
        _center(fb, text, _CLOCK_Y, "small", _MUTED_PAL,
                _CLOCK_Y, _CLOCK_H)
        self.lcd.blit(view, 0, _CLOCK_Y, 240, _CLOCK_H)

    def tick(self):
        if self._dirty:
            self.paint()
            return
        if not self.pages:
            return
        page = self.pages[self.page]
        now = time.ticks_ms()
        self._advance_page(page, now)
        if (page.age > STALE_MS // 1000) != self._stale:
            self.paint()
            return
        self._clock_patch(page)

        if self._fill < 1.0:
            t = min(1.0, time.ticks_diff(now, self._intro_at) / _INTRO_MS)
            self._fill = 1 - (1 - t) ** 3
            width, height = _BAR_W + _BAR_PAD * 2, _BAR_H + _BAR_PAD * 2
            view = memoryview(self.buf)[:width * height * 2]
            fb = framebuf.FrameBuffer(view, width, height, framebuf.RGB565)
            for i, pct in enumerate(page.pct):
                fb.fill(_BG)
                self._bar(fb, _BAR_PAD, _BAR_PAD, pct, self._fill)
                self.lcd.blit(view, _BAR_X - _BAR_PAD,
                              _row_y(len(page.pct), i) - _BAR_PAD,
                              width, height)

        if not self._stale and time.ticks_diff(now, self._pulse_at) >= _PULSE_MS:
            self._pulse_at = now
            intensity = 0.65 + 0.20 * math.sin((now % 4800) * math.pi / 2400)
            view = memoryview(self.buf)[:11 * 11 * 2]
            fb = framebuf.FrameBuffer(view, 11, 11, framebuf.RGB565)
            fb.fill(_BG)
            self._dot(fb, 5, 5, intensity)
            self.lcd.blit(view, self._pulse_x - 5, 40, 11, 11)
