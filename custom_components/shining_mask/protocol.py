"""Shining Mask BLE protocol (no Home Assistant imports, so it can be reused by tools).

Protocol notes collected from public reverse-engineering work:
  * mjg59 / r/ReverseEngineering thread (command format + AES key)
  * GoneUp/mask-go (command list, text bitmap encoding, upload flow)
  * bishopfox/shining-mask (DIY image upload: 8004-byte RGB frame)

Command packets: [len][ASCII tag][args], zero padded to 16 bytes, AES-128-ECB
encrypted with a fixed key, written to CMD_UUID. Replies arrive (encrypted) on
NOTIFY_UUID. Bulk upload data is written *unencrypted* to UPLOAD_UUID as
[len(data)+1][packet counter][data<=98 bytes].
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

AES_KEY = bytes.fromhex("32672f7974ad43451d9c6c894a0e8764")

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CMD_UUID = "d44bc439-abfd-45a2-b575-925416129600"
NOTIFY_UUID = "d44bc439-abfd-45a2-b575-925416129601"
UPLOAD_UUID = "d44bc439-abfd-45a2-b575-92541612960a"
RHYTHM_UUID = "d44bc439-abfd-45a2-b575-92541612960b"  # music/mic visualiser frames (app write channel 3)

# DIY image frame: 8004 bytes = 2668 RGB pixels = 46 x 58.
IMAGE_WIDTH = 46
IMAGE_HEIGHT = 58
IMAGE_BYTES = IMAGE_WIDTH * IMAGE_HEIGHT * 3

TEXT_HEIGHT = 16
UPLOAD_CHUNK = 98

TEXT_MODE_STEADY = 1
TEXT_MODE_BLINK = 2
TEXT_MODE_SCROLL_LEFT = 3
TEXT_MODE_SCROLL_RIGHT = 4


def _cipher() -> Cipher:
    """AES-128-ECB with the mask's fixed key (every command packet is encrypted)."""
    return Cipher(algorithms.AES(AES_KEY), modes.ECB())  # noqa: S305 - device protocol


def encrypt_block(block: bytes) -> bytes:
    """Encrypt one 16-byte packet."""
    if len(block) != 16:
        raise ValueError("block must be 16 bytes")
    enc = _cipher().encryptor()
    return enc.update(block) + enc.finalize()


def decrypt_block(block: bytes) -> bytes:
    """Decrypt one 16-byte packet."""
    dec = _cipher().decryptor()
    return dec.update(block[:16]) + dec.finalize()


def build_plain(tag: str, args: bytes | Iterable[int] = b"") -> bytes:
    """Unencrypted packet: [length] [ASCII tag] [args], zero-padded to 16 bytes."""
    body = tag.encode("ascii") + bytes(args)
    pkt = bytes([len(body)]) + body
    if len(pkt) > 16:
        raise ValueError(f"command {tag} too long ({len(pkt)} > 16 bytes)")
    return pkt.ljust(16, b"\x00")


def build_command(tag: str, args: bytes | Iterable[int] = b"") -> bytes:
    """Return the encrypted 16-byte packet for a command."""
    return encrypt_block(build_plain(tag, args))


def parse_notification(data: bytes) -> str:
    """Decrypt a notification and return its ASCII payload (e.g. 'DATSOK')."""
    if len(data) < 16:
        return data.decode("ascii", "ignore")
    plain = decrypt_block(data)
    length = min(plain[0], 15)
    return plain[1 : 1 + length].decode("ascii", "ignore")


# ---------------------------------------------------------------- commands
def cmd_brightness(value: int) -> bytes:
    """LIGHT: brightness 0-255."""
    return build_command("LIGHT", [max(0, min(255, value))])


def cmd_image(index: int) -> bytes:
    """IMAG: show built-in image N."""
    return build_command("IMAG", [index & 0xFF])


def cmd_animation(index: int) -> bytes:
    """ANIM: play built-in animation N."""
    return build_command("ANIM", [index & 0xFF])


def cmd_text_mode(mode: int) -> bytes:
    """MODE: how uploaded text moves (steady / blink / scroll)."""
    return build_command("MODE", [mode & 0xFF])


def cmd_speed(speed: int) -> bytes:
    """SPEED: animation / DIY / text speed 0-255."""
    return build_command("SPEED", [speed & 0xFF])


def cmd_play(slots: Sequence[int]) -> bytes:
    """Play uploaded DIY images (1-based slots), cycling in the given order."""
    if not 1 <= len(slots) <= 10:
        raise ValueError("between 1 and 10 slots per PLAY command")
    return build_command("PLAY", [len(slots), *[s & 0xFF for s in slots]])


def cmd_delete(slots: Sequence[int]) -> bytes:
    """DELE: delete DIY slots."""
    if not 1 <= len(slots) <= 10:
        raise ValueError("between 1 and 10 slots per DELE command")
    return build_command("DELE", [len(slots), *[s & 0xFF for s in slots]])


def cmd_check() -> bytes:
    """CHEC: ask how many DIY images are stored."""
    return build_command("CHEC")


def cmd_front_color(rgb: Sequence[int], enable: bool = True) -> bytes:
    """FC: text colour [enable r g b]."""
    return build_command("FC", [int(enable), *rgb[:3]])


def cmd_back_color(rgb: Sequence[int], enable: bool = True) -> bytes:
    """Text background colour (confirmed 'BC' from the app's protocol code)."""
    return build_command("BC", [int(enable), *rgb[:3]])


def cmd_text_color_mode(mode: int, enable: bool = True) -> bytes:
    """00-03 text gradients, 04-07 background animations."""
    return build_command("M", [int(enable), mode & 0xFF])


def cmd_upload_start_text(total_len: int, bitmap_len: int) -> bytes:
    """DATS for text: total bytes, bitmap width, type 0."""
    return build_command("DATS", total_len.to_bytes(2, "big") + bitmap_len.to_bytes(2, "big") + b"\x00")


def cmd_upload_start_image(total_len: int, slot: int) -> bytes:
    """DATS for a DIY image: total bytes, target slot, type 1."""
    return build_command("DATS", total_len.to_bytes(2, "big") + slot.to_bytes(2, "big") + b"\x01")


def cmd_upload_complete() -> bytes:
    """DATCP: upload finished."""
    return build_command("DATCP")


def upload_packets(payload: bytes) -> list[bytes]:
    """Split payload into unencrypted upload packets."""
    packets = []
    for counter, offset in enumerate(range(0, len(payload), UPLOAD_CHUNK)):
        chunk = payload[offset : offset + UPLOAD_CHUNK]
        packets.append(bytes([len(chunk) + 1, counter & 0xFF]) + chunk)
    return packets


# ---------------------------------------------------------------- encoders
def encode_text_columns(columns: Sequence[Sequence[int]], colors: Sequence[Sequence[int]]) -> tuple[bytes, int]:
    """Encode text bitmap.

    columns: per column, 16 truthy/falsy row values (row 0 = top).
    colors: per column RGB.
    Returns (payload, bitmap_len). Payload = bitmap (2 bytes/column) + colors (3 bytes/column).
    """
    bitmap = bytearray()
    for col in columns:
        lo = hi = 0
        for row in range(8):
            if col[row]:
                lo |= 0x80 >> row
        for row in range(8, 16):
            if col[row]:
                hi |= 0x80 >> (row - 8)
        bitmap += bytes([lo, hi])
    color_bytes = bytearray()
    for rgb in colors:
        color_bytes += bytes(int(c) & 0xFF for c in rgb[:3])
    return bytes(bitmap) + bytes(color_bytes), len(bitmap)


def encode_image_pixels(pixels: Sequence[Sequence[int]], order: str = "column") -> bytes:
    """Encode a 46x58 RGB frame.

    pixels: flat row-major list (len 46*58) of (r, g, b), as from PIL getdata().
    order: 'column' = left->right columns, each top->bottom (default guess);
           'row' = top->bottom rows, each left->right.
    """
    if len(pixels) != IMAGE_WIDTH * IMAGE_HEIGHT:
        raise ValueError("expected a 46x58 image")
    out = bytearray()
    if order == "row":
        for px in pixels:
            out += bytes(px[:3])
    else:
        for x in range(IMAGE_WIDTH):
            for y in range(IMAGE_HEIGHT):
                out += bytes(pixels[y * IMAGE_WIDTH + x][:3])
    return bytes(out)


# ---------------------------------------------------- confirmed from the app (v1.2.7)
def cmd_animation_loop() -> bytes:
    """Cycle through all built-in animations."""
    return build_command("LOOA")


def cmd_exit_rhythm() -> bytes:
    """Leave music/microphone rhythm mode."""
    return build_command("SOUT")


def cmd_rhythm_frame(mode: int, levels: Sequence[int]) -> bytes:
    """One frame of the music/mic visualiser: no ASCII tag, [0x0F][mode][12 bar levels].

    levels: 12 values 0-15 (bar heights). Send repeatedly (e.g. 10-20 per second).
    Write to RHYTHM_UUID (not the command characteristic).
    """
    lv = [max(0, min(15, int(v))) for v in list(levels)[:12]]
    lv += [0] * (12 - len(lv))
    return encrypt_block(bytes([0x0F, mode & 0xFF, *lv]).ljust(16, b"\x00"))


# Gesture page ("face switch") settings, decoded from the app (SettingActivity / GallerySelectionActivity).
# Library = the app's "image_select_mode" radio buttons: rb_all=0, rb_image (gallery)=1, rb_diy=2.
GESTURE_LIBRARIES = {"all": 0, "gallery": 1, "diy": 2}
# Circulation = the app's "loop_mode": play the picked faces in order or shuffled.
GESTURE_CIRCULATION = {"order": 0, "random": 1}
# How many picked faces fit in the first FACE packet, and in each follow-up packet.
GESTURE_FIRST_ITEMS = 7
GESTURE_MORE_ITEMS = 15


def gesture_item_bytes(library: int, numbers: Sequence[int]) -> list[int]:
    """Turn the face numbers a person picks into the bytes the mask expects.

    gallery: the app sends each built-in image's 0-based position, so image 1 -> 0.
    diy:     the app sends the DIY slot number unchanged.
    all:     no list (the mask cycles through everything).
    """
    if library == GESTURE_LIBRARIES["gallery"]:
        return [(n - 1) & 0xFF for n in numbers if n >= 1]
    if library == GESTURE_LIBRARIES["diy"]:
        return [n & 0xFF for n in numbers]
    return []


def cmd_gesture(enable: bool, library: int = 0, circulation: int = 0, items: Sequence[int] = ()) -> bytes:
    """First 'FACE' packet of the gesture setting (app: Agreement.getGestureSettings).

    Plain layout: [len] 'FACE' [enable] [circulation] [library] [count] [item1 .. item7]
      count  - the TOTAL number of picked faces; 0 for library 'all'
      items  - already converted with gesture_item_bytes(); only the first 7 go here,
               the rest follow in cmd_gesture_more() packets after the mask answers FACEOK.
    The app writes len = 8 + n for up to 7 items and 16 when there are more; we copy that exactly.
    """
    if not enable:
        # the app still sends circulation and library when switching gestures off
        body = bytes([8]) + b"FACE" + bytes([0, circulation & 0xFF, library & 0xFF, 0])
        return encrypt_block(body.ljust(16, b"\x00"))
    picked = [i & 0xFF for i in items] if library else []
    first = picked[:GESTURE_FIRST_ITEMS]
    length = 8 + (8 if len(picked) > GESTURE_FIRST_ITEMS else len(picked))
    body = bytes([length]) + b"FACE" + bytes([1, circulation & 0xFF, library & 0xFF, len(picked) & 0xFF, *first])
    return encrypt_block(body.ljust(16, b"\x00"))


def cmd_gesture_more(chunk: Sequence[int]) -> bytes:
    """Follow-up packet with up to 15 more picked faces (app: Agreement.getGestureSettings2).

    Plain layout: [n] [item1 .. item_n], no tag. Sent only after the mask replies 'FACEOK'.
    """
    chunk = list(chunk)[:GESTURE_MORE_ITEMS]
    return encrypt_block((bytes([len(chunk)]) + bytes(i & 0xFF for i in chunk)).ljust(16, b"\x00"))


def gesture_packets(enable: bool, library: int, circulation: int, numbers: Sequence[int]) -> list[bytes]:
    """All packets for one gesture setting: the FACE packet, then 15-item follow-ups."""
    items = gesture_item_bytes(library, numbers) if enable else []
    packets = [cmd_gesture(enable, library, circulation, items)]
    rest = items[GESTURE_FIRST_ITEMS:]
    for i in range(0, len(rest), GESTURE_MORE_ITEMS):
        packets.append(cmd_gesture_more(rest[i : i + GESTURE_MORE_ITEMS]))
    return packets


def parse_number_list(text: str) -> list[int]:
    """'1, 4, 7-9' -> [1, 4, 7, 8, 9]. Keeps the order typed (the mask plays them in that order)."""
    out: list[int] = []
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(v) for v in part.split("-", 1))
            step = 1 if hi >= lo else -1
            out.extend(range(lo, hi + step, step))
        else:
            out.append(int(part))
    if any(n < 1 or n > 255 for n in out):
        raise ValueError("face numbers must be 1-255")
    return out


def format_number_list(numbers: Sequence[int]) -> str:
    """[1, 4, 7, 8, 9] -> '1, 4, 7-9' (runs of 3+ collapse into ranges)."""
    parts: list[str] = []
    i = 0
    nums = list(numbers)
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(f"{nums[i]}-{nums[j]}" if j - i >= 2 else ", ".join(str(n) for n in nums[i : j + 1]))
        i = j + 1
    return ", ".join(parts)
