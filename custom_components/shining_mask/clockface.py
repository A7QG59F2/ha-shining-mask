"""Draws the clock screen (pure Pillow, no Home Assistant): sky, time, temperature, date.

Canvas 46 x 58. Layout (rows):
  0-12  sky: sun or moon riding an arc (rise on the left -> set on the right), weather on top
 13-19  eye zone: left dark for the eye holes
 20-33  time, 8x14 digits, the colon blinks between the two frames
 38-42  temperature
 46-50  day and date
Colours come from a theme (CLOCK_THEMES).

Every frame is a still picture; animation comes from uploading a couple of frames that the
mask loops (see clock.py). `frame` picks which variant to draw (colon on/off, rays, rain...).
"""
from __future__ import annotations

import math
import random
from PIL import Image, ImageDraw

W, H = 46, 58

# 4x7 digits (drawn at 2x), '#' = lit LED
DIG = {
"0": ["####","#..#","#..#","#..#","#..#","#..#","####"],
"1": ["..#.",".##.","..#.","..#.","..#.","..#.",".###"],
"2": ["####","...#","...#","####","#...","#...","####"],
"3": ["####","...#","...#",".###","...#","...#","####"],
"4": ["#..#","#..#","#..#","####","...#","...#","...#"],
"5": ["####","#...","#...","####","...#","...#","####"],
"6": ["####","#...","#...","####","#..#","#..#","####"],
"7": ["####","...#","...#","..#.",".#..",".#..",".#.."],
"8": ["####","#..#","#..#","####","#..#","#..#","####"],
"9": ["####","#..#","#..#","####","...#","...#","####"],
}
# 3x5 small font for temperature and date
SM = {
"0":["###","#.#","#.#","#.#","###"],"1":[".#.","##.",".#.",".#.","###"],"2":["###","..#","###","#..","###"],
"3":["###","..#",".##","..#","###"],"4":["#.#","#.#","###","..#","..#"],"5":["###","#..","###","..#","###"],
"6":["###","#..","###","#.#","###"],"7":["###","..#",".#.",".#.",".#."],"8":["###","#.#","###","#.#","###"],
"9":["###","#.#","###","..#","###"],"-":["...","...","###","...","..."],"°":["##.","##.","...","...","..."],
"F":["###","#..","##.","#..","#.."],"C":["###","#..","#..","#..","###"]," ":["...","...","...","...","..."],
"A":["###","#.#","###","#.#","#.#"],"D":["##.","#.#","#.#","#.#","##."],"E":["###","#..","##.","#..","###"],
"H":["#.#","#.#","###","#.#","#.#"],"I":["###",".#.",".#.",".#.","###"],"M":["#.#","###","###","#.#","#.#"],
"N":["##.","#.#","#.#","#.#","#.#"],"O":["###","#.#","#.#","#.#","###"],"R":["##.","#.#","##.","#.#","#.#"],
"S":["###","#..","###","..#","###"],"T":["###",".#.",".#.",".#.",".#."],"U":["#.#","#.#","#.#","#.#","###"],
"W":["#.#","#.#","###","###","#.#"],"J":["..#","..#","..#","#.#","###"],"L":["#..","#..","#..","#..","###"],
"G":["###","#..","#.#","#.#","###"],"P":["###","#.#","###","#..","#.."],"V":["#.#","#.#","#.#","#.#",".#."],
"B":["##.","#.#","##.","#.#","##."],"Y":["#.#","#.#",".#.",".#.",".#."],
}


def _glyph(d, x, y, rows, color, scale=1):
    """Draw a bitmap glyph (rows of '#'/'.') at x, y, each dot scale x scale pixels.

    color: an (r, g, b) tuple, or a function (row_fraction 0..1) -> (r, g, b) for gradients.
    """
    n = max(1, len(rows) - 1)
    for r, line in enumerate(rows):
        col = color(r / n) if callable(color) else color
        for c, ch in enumerate(line):
            if ch == "#":
                d.rectangle((x + c * scale, y + r * scale, x + c * scale + scale - 1, y + r * scale + scale - 1), fill=col)


def _mix(a, b, t):
    """Blend colour a towards b by t (0..1)."""
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def sky_colors(elev: float):
    """Top/bottom sky colours by sun elevation (degrees). Kept dim: LEDs are bright."""
    night, dawn, day = ((0, 0, 18), (2, 2, 30)), ((40, 10, 40), (90, 35, 0)), ((0, 25, 70), (20, 60, 90))
    if elev <= -10:
        return night
    if elev <= 0:
        t = (elev + 10) / 10
        return _mix(night[0], dawn[0], t), _mix(night[1], dawn[1], t)
    if elev <= 10:
        t = elev / 10
        return _mix(dawn[0], day[0], t), _mix(dawn[1], day[1], t)
    return day


def arc_pos(frac: float):
    """frac 0 = rising (left horizon), 0.5 = top, 1 = setting (right). Returns pixel (x, y)."""
    x = 4 + frac * (W - 9)
    y = 11 - math.sin(frac * math.pi) * 8
    return round(x), round(y)


def draw_moon(d, cx, cy, phase: float, r=3):
    """phase 0 new, 0.5 full, 1 new. Lit part drawn pale, dark part faint."""
    lit, dark = (230, 230, 190), (25, 25, 35)
    for y in range(-r, r + 1):
        for x in range(-r, r + 1):
            if x * x + y * y > r * r + 1:
                continue
            w = math.sqrt(max(0, r * r - y * y)) or 1
            # terminator position along x for this row
            k = math.cos(phase * 2 * math.pi)  # 1 new, -1 full
            edge = k * w
            if phase < 0.5:  # waxing: right side lit
                on = x > edge
            else:  # waning: left side lit
                on = x < -edge
            d.point((cx + x, cy + y), fill=lit if on else dark)


def draw_sun(d, cx, cy, frame, elev):
    """Sun disc (orange near the horizon, yellow higher up) with rays that twinkle per frame."""
    core = (255, 200, 40) if elev > 8 else (255, 120, 20)
    d.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=core)
    ray = (160, 110, 0)
    pts = [(0, -4), (3, -3), (4, 0), (3, 3), (0, 4), (-3, 3), (-4, 0), (-3, -3)]
    for i, (dx, dy) in enumerate(pts):
        if (i + frame) % 2 == 0:  # rays twinkle alternately
            d.point((cx + dx, cy + dy), fill=ray)


def cloud(d, x, y, col):
    """A small three-puff cloud."""
    for dx, dy, r in ((0, 0, 2), (3, -1, 3), (6, 0, 2)):
        d.ellipse((x + dx - r, y + dy - r + 1, x + dx + r, y + dy + r), fill=col)


def draw_weather(d, cond, frame, rng):
    """Weather over the sky strip for a Home Assistant condition; `frame` moves it along."""
    grey, dark = (70, 70, 80), (35, 35, 45)
    if cond in ("cloudy", "partlycloudy", "rainy", "pouring", "lightning-rainy", "snowy", "fog"):
        heavy = cond != "partlycloudy"
        off = frame * 2
        for base in ((2, 4), (18, 3), (33, 5)) if heavy else ((10, 4),):
            cloud(d, (base[0] + off) % 50 - 4, base[1], dark if cond in ("pouring", "lightning-rainy") else grey)
    if cond in ("rainy", "pouring", "lightning-rainy"):
        n = 14 if cond != "rainy" else 8
        for i in range(n):
            x = (i * 7 + frame * 2) % W
            y = 7 + (i * 3 + frame * 3) % 7
            d.line((x, y, x - 1, y + 2), fill=(40, 90, 200))
    if cond == "snowy":
        for i in range(10):
            x = (i * 5 + (frame % 2)) % W
            y = 7 + (i * 2 + frame) % 6
            d.point((x, y), fill=(200, 200, 220))
    if cond == "lightning-rainy" and frame % 4 == 1:
        d.line([(24, 6), (21, 9), (24, 9), (21, 13)], fill=(255, 255, 120))
    if cond == "fog":
        for i, y in enumerate((5, 8, 11)):
            d.line((((frame + i) % 3), y, W - 3 + ((frame + i) % 3), y), fill=(50, 50, 55))
    if cond in ("clear-night",):
        for i in range(8):  # stars twinkle
            x, y = rng.randrange(W), rng.randrange(1, 11)
            if (i + frame) % 3:
                d.point((x, y), fill=(120, 120, 140))


# temperature (deg F) upper bound -> colour
TEMP_COL = [(32, (80, 140, 255)), (55, (0, 200, 200)), (75, (90, 220, 60)), (90, (255, 160, 0)), (999, (255, 50, 30))]


def _small_text(d, txt, y, col, scale=1):
    """Centred 3x5 text (scale 2 = 6x10 letters)."""
    widths = [(len(SM[c][0]) + 1) * scale for c in txt]
    x = (W - sum(widths) + scale) // 2
    for c, w in zip(txt, widths):
        _glyph(d, x, y, SM[c], col, scale=scale)
        x += w


def _grad(top, bottom):
    """Vertical gradient for a digit: top colour fading to bottom colour."""
    return lambda t: _mix(top, bottom, t)


def _hue(h):
    """Fully saturated colour for hue 0..1."""
    import colorsys

    r, g, b = colorsys.hsv_to_rgb(h % 1.0, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


# Colour themes for the time and date.
#   digits(i, temp_colour) -> colour or gradient for digit i (0-3)
#   colon / date: colours. temp: "scale" = cold-blue..hot-red by temperature, or a fixed colour.
CLOCK_THEMES = {
    "Classic": dict(digits=lambda i, tc: (255, 255, 255), colon=(255, 255, 255), date=(90, 90, 110), temp="scale"),
    "Matrix": dict(digits=lambda i, tc: _grad((180, 255, 180), (0, 150, 30)), colon=(0, 200, 60), date=(0, 90, 30), temp=(0, 220, 80)),
    "Amber": dict(digits=lambda i, tc: (255, 150, 0), colon=(255, 110, 0), date=(120, 60, 0), temp=(255, 190, 60)),
    "Ice": dict(digits=lambda i, tc: _grad((220, 250, 255), (0, 120, 255)), colon=(120, 200, 255), date=(40, 80, 130), temp="scale"),
    "Sunset": dict(digits=lambda i, tc: _grad((255, 210, 0), (255, 0, 120)), colon=(255, 90, 60), date=(130, 40, 80), temp="scale"),
    "Neon": dict(digits=lambda i, tc: (0, 255, 255) if i < 2 else (255, 0, 200), colon=(255, 255, 255), date=(120, 0, 120), temp=(0, 255, 255)),
    "Rainbow": dict(digits=lambda i, tc: _hue(i / 4), colon=(255, 255, 255), date=(90, 90, 110), temp="scale"),
    "Temperature": dict(digits=lambda i, tc: tc, colon=(200, 200, 200), date=(90, 90, 110), temp="scale"),
}


# Home Assistant weather conditions -> the few looks we draw
CONDITION_LOOK = {
    "sunny": "sunny", "clear-night": "clear-night", "partlycloudy": "partlycloudy", "windy": "partlycloudy",
    "windy-variant": "partlycloudy", "cloudy": "cloudy", "exceptional": "cloudy", "fog": "fog",
    "rainy": "rainy", "pouring": "pouring", "hail": "pouring", "lightning": "lightning-rainy",
    "lightning-rainy": "lightning-rainy", "snowy": "snowy", "snowy-rainy": "snowy",
}


COLON = ["....", ".##.", ".##.", "....", ".##.", ".##.", "...."]


def render_digit(ch: str, theme: str = "Classic", index: int = 0):
    """One big character for the digit-flip clock: 4x7 font at 5x (20x35), below the eyes.

    ch: '0'-'9' or ':'. index: digit position 0-3 (themes like Neon/Rainbow colour by position;
    for the flip clock every digit image is shared, so index 0 is used).
    """
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    th = CLOCK_THEMES.get(theme, CLOCK_THEMES["Classic"])
    rows = COLON if ch == ":" else DIG[ch]
    col = th["colon"] if ch == ":" else th["digits"](index, (200, 200, 200))
    _glyph(d, (W - 20) // 2, 20, rows, col, scale=5)
    return img


def render(hour, minute, sun_frac, elev, moon_frac, moon_phase, cond, temp, unit="F", frame=0, h24=True,
           date="FRI 6", theme="Classic", show_time=True):
    """One frame of the clock.

    sun_frac / moon_frac: 0..1 across the sky (rise -> set), or None while below the horizon.
    elev: sun elevation in degrees (sky colour). moon_phase: 0 new, 0.5 full, 1 new again.
    cond: Home Assistant weather condition. temp: number in `unit` ('F' or 'C'), or None.
    theme: one of CLOCK_THEMES (colours of the time, temperature and date).
    """
    cond = CONDITION_LOOK.get(cond, "cloudy" if cond else "")
    th = CLOCK_THEMES.get(theme, CLOCK_THEMES["Classic"])
    night = elev <= -6  # dim the text at night so it isn't glaring in the dark
    temp_col = (200, 200, 200)
    if temp is not None:
        tf = temp if unit == "F" else temp * 9 / 5 + 32
        temp_col = next(c for t, c in TEMP_COL if tf <= t)

    def dim(c):
        """Night dimming for a colour or a gradient."""
        if callable(c):
            return lambda t: dim(c(t))
        return tuple(int(v * 0.6) for v in c) if night else c

    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    top, bot = sky_colors(elev)
    for y in range(13):
        d.line((0, y, W - 1, y), fill=_mix(top, bot, y / 12))
    d.line((0, 12, W - 1, 12), fill=(15, 30, 10) if elev > -6 else (5, 8, 5))  # horizon / ground
    rng = random.Random(7)
    if cond == "clear-night" or (elev < -6 and cond in ("sunny", "clear-night")):
        draw_weather(d, "clear-night", frame, rng)
    if moon_frac is not None:
        draw_moon(d, *arc_pos(moon_frac), moon_phase)
    if sun_frac is not None:
        draw_sun(d, *arc_pos(sun_frac), frame, elev)
    sky = Image.new("RGB", (W, 13))
    sky.paste(img.crop((0, 0, W, 13)))
    sd = ImageDraw.Draw(sky)
    draw_weather(sd, cond, frame, rng)
    img.paste(sky, (0, 0))  # weather never spills into the eye zone

    # time: 4x7 digits drawn at 2x (8x14) on rows 20-33, colon blinks on alternate frames
    if not show_time:  # digit-flip clock: this is the info screen (sky, temperature, date)
        hour = None
    h = 0 if hour is None else hour if h24 else (hour % 12 or 12)
    digits = f"{h:02d}{minute:02d}" if h24 else f"{h:>2}{minute:02d}"
    shift = 5 if digits[0] == " " else 0  # 3-digit times (12-hour) stay centred
    top = 20
    for i, (ch, x) in enumerate(zip(digits, (2, 12, 26, 36))):
        if ch != " " and hour is not None:
            _glyph(d, x - shift, top, DIG[ch], dim(th["digits"](i, temp_col)), scale=2)
    if frame % 2 == 0 and hour is not None:
        colon = dim(th["colon"])
        d.rectangle((22 - shift, top + 3, 23 - shift, top + 4), fill=colon)
        d.rectangle((22 - shift, top + 9, 23 - shift, top + 10), fill=colon)

    # temperature (rows 38-42) and day + date (rows 46-50, the narrow bottom part).
    # Info screen (no time): temperature big in the middle instead.
    big = hour is None
    if temp is not None:
        col = temp_col if th["temp"] == "scale" else th["temp"]
        _small_text(d, f"{round(temp)}°{unit}", 22 if big else 38, dim(col), scale=2 if big else 1)
    _small_text(d, date, 40 if big else 46, dim(th["date"]))
    return img
