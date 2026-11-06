"""Text rendering and built-in face generation (Pillow)."""

from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

try:
    from .protocol import IMAGE_HEIGHT, IMAGE_WIDTH, TEXT_HEIGHT, encode_image_pixels, encode_text_columns
except ImportError:  # imported standalone by tools/mask_cli.py
    from protocol import IMAGE_HEIGHT, IMAGE_WIDTH, TEXT_HEIGHT, encode_image_pixels, encode_text_columns

W, H = IMAGE_WIDTH, IMAGE_HEIGHT


MAX_TEXT_COLUMNS = 512  # wider text bitmaps can hang the mask (same as const.MAX_TEXT_COLUMNS)


def render_text(text: str, color: Sequence[int] = (255, 255, 255)) -> tuple[bytes, int]:
    """Render text into the mask's 16-px-high text format. Returns (payload, bitmap_len)."""
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:  # very old Pillow
        font = ImageFont.load_default()
    left, top, right, bottom = font.getbbox(text)
    width = max(1, right + 1)
    if width > MAX_TEXT_COLUMNS:  # very wide bitmaps can hang the mask
        raise ValueError(f"Text too long for the mask ({width} px wide, max {MAX_TEXT_COLUMNS})")
    img = Image.new("L", (width, TEXT_HEIGHT), 0)
    draw = ImageDraw.Draw(img)
    # vertically centre the glyph box in 16 rows
    y = (TEXT_HEIGHT - (bottom - top)) // 2 - top
    draw.text((0, y), text, fill=255, font=font)
    px = img.load()
    columns = [[px[x, r] > 96 for r in range(TEXT_HEIGHT)] for x in range(width)]
    colors = [tuple(color)] * width
    return encode_text_columns(columns, colors)


def fit_image(img: Image.Image, mode: str = "scale") -> Image.Image:
    """Fit an image into the 46x58 frame.

    scale: shrink to fit, letterboxed (photos, big pictures)
    crop:  keep pixels 1:1, centred; trims or pads edges (pixel art drawn for the mask)
    auto:  crop when the image is within 16 px of the frame size, otherwise scale
    """
    img = img.convert("RGB")
    if mode == "auto":
        mode = "crop" if abs(img.width - W) <= 16 and abs(img.height - H) <= 16 else "scale"
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    if mode == "crop":
        canvas.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
        return canvas
    small = img.width <= 2 * W and img.height <= 2 * H
    img.thumbnail((W, H), Image.Resampling.NEAREST if small else Image.Resampling.LANCZOS)
    canvas.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
    return canvas


def image_to_payload(img: Image.Image, order: str = "column") -> bytes:
    """Fit any image into 46x58 (letterboxed, black) and encode it."""
    return encode_image_pixels(list(fit_image(img).getdata()), order)


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
    """Draw the two eyes used by the built-in faces."""
    for cx in (L_EYE_X, R_EYE_X):
        d.ellipse((cx - rx, EYE_Y + dy - ry, cx + rx, EYE_Y + dy + ry), fill=color)
        if pupil:
            d.ellipse((cx - 2, EYE_Y + dy - 1, cx + 2, EYE_Y + dy + 3), fill=(0, 0, 0))


def _new():
    """A blank black canvas the size of the mask."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    return img, ImageDraw.Draw(img)


def face_idle():
    """Built-in face: cyan eyes and a small smile."""
    img, d = _new()
    _eyes(d, CYAN)
    d.arc((14, 34, 31, 46), 20, 160, fill=CYAN, width=2)  # small smile
    return img


def face_sleep():
    """Built-in face: purple closed eyes, flat mouth."""
    img, d = _new()
    for cx in (L_EYE_X, R_EYE_X):
        d.arc((cx - 5, EYE_Y - 3, cx + 5, EYE_Y + 5), 20, 160, fill=PURPLE, width=2)
    d.line((19, 41, 27, 41), fill=PURPLE, width=2)
    return img


def face_listening():
    """Built-in face: big green eyes and a little "o" mouth."""
    img, d = _new()
    _eyes(d, GREEN, rx=6, ry=9)
    d.ellipse((19, 37, 27, 45), outline=GREEN, width=2)  # little "o"
    return img


def face_thinking():
    """Built-in face: amber eyes raised, three dots for a mouth."""
    img, d = _new()
    _eyes(d, AMBER, ry=6, dy=-2)
    for x in (15, 23, 31):
        d.ellipse((x - 2, 39, x + 2, 43), fill=AMBER)
    return img


def face_talk_closed():
    """Built-in face: talking, mouth closed (paired with talk_open)."""
    img, d = _new()
    _eyes(d, CYAN)
    d.line((14, 40, 32, 40), fill=CYAN, width=3)
    return img


def face_talk_open():
    """Built-in face: talking, mouth open."""
    img, d = _new()
    _eyes(d, CYAN)
    d.ellipse((14, 34, 32, 50), fill=CYAN)
    d.ellipse((17, 37, 29, 47), fill=(0, 0, 0))
    return img


def face_error():
    """Built-in face: red X eyes and a frown."""
    img, d = _new()
    for cx in (L_EYE_X, R_EYE_X):
        d.line((cx - 5, EYE_Y - 5, cx + 5, EYE_Y + 5), fill=RED, width=3)
        d.line((cx - 5, EYE_Y + 5, cx + 5, EYE_Y - 5), fill=RED, width=3)
    d.arc((14, 38, 32, 52), 200, 340, fill=RED, width=2)
    return img


def face_blank():
    """All black: used as the real 'off' picture."""
    return _new()[0]


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
    "blank": face_blank,
}

# Slot layout used by install_default_faces.
DEFAULT_SLOTS = {
    1: "idle",
    2: "listening",
    3: "thinking",
    4: "talk_closed",
    5: "talk_open",
    6: "error",
    7: "sleep",
}
