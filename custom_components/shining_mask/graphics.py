"""Text rendering and built-in face generation (Pillow)."""

from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

try:
    from .protocol import IMAGE_HEIGHT, IMAGE_WIDTH, TEXT_HEIGHT, encode_image_pixels, encode_text_columns
except ImportError:  # imported standalone by tools/mask_cli.py
    from protocol import IMAGE_HEIGHT, IMAGE_WIDTH, TEXT_HEIGHT, encode_image_pixels, encode_text_columns

W, H = IMAGE_WIDTH, IMAGE_HEIGHT


def render_text(text: str, color: Sequence[int] = (255, 255, 255)) -> tuple[bytes, int]:
    """Render text into the mask's 16-px-high text format. Returns (payload, bitmap_len)."""
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:  # very old Pillow
        font = ImageFont.load_default()
    left, top, right, bottom = font.getbbox(text)
    width = max(1, right + 1)
    img = Image.new("L", (width, TEXT_HEIGHT), 0)
    draw = ImageDraw.Draw(img)
    # vertically centre the glyph box in 16 rows
    y = (TEXT_HEIGHT - (bottom - top)) // 2 - top
    draw.text((0, y), text, fill=255, font=font)
    px = img.load()
    columns = [[px[x, r] > 96 for r in range(TEXT_HEIGHT)] for x in range(width)]
    colors = [tuple(color)] * width
    return encode_text_columns(columns, colors)


def image_to_payload(img: Image.Image, order: str = "column") -> bytes:
    """Fit any image into 46x58 (letterboxed, black) and encode it."""
    img = img.convert("RGB")
    img.thumbnail((W, H), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
    return encode_image_pixels(list(canvas.getdata()), order)


# ----------------------------------------------------------- built-in faces
CYAN = (0, 200, 255)
GREEN = (0, 255, 90)
AMBER = (255, 150, 0)
RED = (255, 0, 0)
WHITE = (255, 255, 255)
PURPLE = (170, 60, 255)

EYE_Y = 19
L_EYE_X, R_EYE_X = 13, 32


def _eyes(d: ImageDraw.ImageDraw, color, rx=5, ry=7, dy=0, pupil=True):
    for cx in (L_EYE_X, R_EYE_X):
        d.ellipse((cx - rx, EYE_Y + dy - ry, cx + rx, EYE_Y + dy + ry), fill=color)
        if pupil:
            d.ellipse((cx - 2, EYE_Y + dy - 1, cx + 2, EYE_Y + dy + 3), fill=(0, 0, 0))


def _new():
    img = Image.new("RGB", (W, H), (0, 0, 0))
    return img, ImageDraw.Draw(img)


def face_idle():
    img, d = _new()
    _eyes(d, CYAN)
    d.arc((14, 34, 31, 46), 20, 160, fill=CYAN, width=2)  # small smile
    return img


def face_sleep():
    img, d = _new()
    for cx in (L_EYE_X, R_EYE_X):
        d.arc((cx - 5, EYE_Y - 3, cx + 5, EYE_Y + 5), 20, 160, fill=PURPLE, width=2)
    d.line((19, 41, 27, 41), fill=PURPLE, width=2)
    return img


def face_listening():
    img, d = _new()
    _eyes(d, GREEN, rx=6, ry=9)
    d.ellipse((19, 37, 27, 45), outline=GREEN, width=2)  # little "o"
    return img


def face_thinking():
    img, d = _new()
    _eyes(d, AMBER, ry=6, dy=-2)
    for x in (15, 23, 31):
        d.ellipse((x - 2, 39, x + 2, 43), fill=AMBER)
    return img


def face_talk_closed():
    img, d = _new()
    _eyes(d, CYAN)
    d.line((14, 40, 32, 40), fill=CYAN, width=3)
    return img


def face_talk_open():
    img, d = _new()
    _eyes(d, CYAN)
    d.ellipse((14, 34, 32, 50), fill=CYAN)
    d.ellipse((17, 37, 29, 47), fill=(0, 0, 0))
    return img


def face_error():
    img, d = _new()
    for cx in (L_EYE_X, R_EYE_X):
        d.line((cx - 5, EYE_Y - 5, cx + 5, EYE_Y + 5), fill=RED, width=3)
        d.line((cx - 5, EYE_Y + 5, cx + 5, EYE_Y - 5), fill=RED, width=3)
    d.arc((14, 38, 32, 52), 200, 340, fill=RED, width=2)
    return img


def face_test_pattern():
    """Orientation check: red top-left, green top-right, blue bottom-left, white arrow up."""
    img, d = _new()
    d.rectangle((0, 0, 7, 7), fill=RED)
    d.rectangle((W - 8, 0, W - 1, 7), fill=GREEN)
    d.rectangle((0, H - 8, 7, H - 1), fill=(0, 0, 255))
    d.polygon(((W // 2, 12), (W // 2 - 8, 26), (W // 2 + 8, 26)), fill=WHITE)
    d.rectangle((W // 2 - 3, 26, W // 2 + 3, 44), fill=WHITE)
    return img


BUILTIN_FACES = {
    "idle": face_idle,
    "listening": face_listening,
    "thinking": face_thinking,
    "talk_closed": face_talk_closed,
    "talk_open": face_talk_open,
    "error": face_error,
    "sleep": face_sleep,
    "test_pattern": face_test_pattern,
}

# Slot layout used by install_default_faces and the blueprint defaults.
DEFAULT_SLOTS = {
    1: "idle",
    2: "listening",
    3: "thinking",
    4: "talk_closed",
    5: "talk_open",
    6: "error",
    7: "sleep",
}
