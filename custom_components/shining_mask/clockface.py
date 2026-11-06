"""Draws the clock screen (pure Pillow, no Home Assistant): sky, time, temperature, date.

Canvas 46 x 58. Layout (rows):
  0-12  sky: sun or moon riding an arc (rise on the left -> set on the right), weather on top
 13-26  eye zone: left dark for the eye holes
 27-40  time, 8x14 digits, the colon blinks between the two frames
 43-47  temperature, coloured from cold blue to hot red
 50-54  day and date, dim

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
    """Draw a bitmap glyph (rows of '#'/'.') at x, y, each dot scale x scale pixels."""
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch == "#":
                d.rectangle((x + c * scale, y + r * scale, x + c * scale + scale - 1, y + r * scale + scale - 1), fill=color)


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


def _small_text(d, txt, y, col):
    """Centred 3x5 text."""
    widths = [len(SM[c][0]) + 1 for c in txt]
    x = (W - sum(widths) + 1) // 2
    for c, w in zip(txt, widths):
        _glyph(d, x, y, SM[c], col)
        x += w


# Home Assistant weather conditions -> the few looks we draw
CONDITION_LOOK = {
    "sunny": "sunny", "clear-night": "clear-night", "partlycloudy": "partlycloudy", "windy": "partlycloudy",
    "windy-variant": "partlycloudy", "cloudy": "cloudy", "exceptional": "cloudy", "fog": "fog",
    "rainy": "rainy", "pouring": "pouring", "hail": "pouring", "lightning": "lightning-rainy",
    "lightning-rainy": "lightning-rainy", "snowy": "snowy", "snowy-rainy": "snowy",
}


def render(hour, minute, sun_frac, elev, moon_frac, moon_phase, cond, temp, unit="F", frame=0, h24=True, date="FRI 6"):
    """One frame of the clock.

    sun_frac / moon_frac: 0..1 across the sky (rise -> set), or None while below the horizon.
    elev: sun elevation in degrees (sky colour). moon_phase: 0 new, 0.5 full, 1 new again.
    cond: Home Assistant weather condition. temp: number in `unit` ('F' or 'C'), or None.
    """
    cond = CONDITION_LOOK.get(cond, "cloudy" if cond else "")
    """One frame. sun_frac/moon_frac: 0..1 across the sky, or None when below the horizon."""
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

    # time: 4x7 digits drawn at 2x (8x14), colon blinks on alternate frames
    h = hour if h24 else (hour % 12 or 12)
    digits = f"{h:02d}{minute:02d}" if h24 else f"{h:>2}{minute:02d}"
    tcol = (255, 255, 255) if elev > -6 else (150, 150, 190)  # dimmer at night
    # positions for 4 digits; with 3 (e.g. 7:12) the whole block shifts right to stay centred
    shift = 5 if digits[0] == " " else 0
    for ch, x in zip(digits, (2, 12, 26, 36)):
        if ch != " ":
            _glyph(d, x - shift, 27, DIG[ch], tcol, scale=2)
    if frame % 2 == 0:
        d.rectangle((22 - shift, 30, 23 - shift, 31), fill=tcol)
        d.rectangle((22 - shift, 36, 23 - shift, 37), fill=tcol)

    # temperature, coloured cold blue -> hot red
    if temp is not None:
        tf = temp if unit == "F" else temp * 9 / 5 + 32
        col = next(c for t, c in TEMP_COL if tf <= t)
        _small_text(d, f"{round(temp)}°{unit}", 43, col)
    # day + date, dim, in the narrow bottom part
    _small_text(d, date, 50, (90, 90, 110))
    return img
