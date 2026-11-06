"""Animated effects drawn for the mask, uploaded as DIY frames that loop (e.g. Matrix rain)."""
from __future__ import annotations

import random
from PIL import Image

W, H = 46, 58


def matrix_frames(frames: int = 24, seed: int = 1999, density: float = 1.0) -> list[Image.Image]:
    """Return `frames` 46x58 images that loop seamlessly.

    Each column holds 1-2 drops. A drop moves `speed` px per frame along a lane of length
    speed * frames, so after the last frame every drop is exactly back where it started.
    The head is near-white green, the trail fades through bright to dark green, and a few
    trail pixels flicker brighter each frame, like changing glyphs.
    """
    rng = random.Random(seed)
    drops = []  # (column, speed, start offset, trail length)
    for x in range(W):
        for _ in range(1 if rng.random() > 0.35 * density else 2):
            speed = rng.choice((2, 3, 3, 4))
            lane = speed * frames  # one full cycle; longer than the mask, so there are gaps
            while lane < H + 24:  # make sure the trail fully leaves before it comes back
                lane += speed * frames
            drops.append((x, speed, rng.randrange(lane), rng.randint(8, 22), lane))
    flick = [[rng.random() for _ in range(W * H)] for _ in range(frames)]
    out = []
    for f in range(frames):
        img = Image.new("RGB", (W, H))
        px = img.load()
        for x, speed, start, trail, lane in drops:
            head = (start + speed * f) % lane - trail  # some time off-screen above
            for i in range(trail):
                y = head - i
                if not 0 <= y < H:
                    continue
                if i == 0:
                    c = (200, 255, 200)  # bright head
                else:
                    t = 1 - i / trail  # 1 near the head -> 0 at the tail
                    g = int(30 + 200 * t ** 1.6)
                    if flick[f][y * W + x] > 0.93:  # a glyph "changes"
                        g = min(255, g + 90)
                    c = (0, g, int(g * 0.25))
                old = px[x, y]
                if sum(c) > sum(old):
                    px[x, y] = c
        out.append(img)
    return out



# name -> frame generator; each returns a list of 46x58 RGB images that loop seamlessly
EFFECTS = {"matrix": matrix_frames}
