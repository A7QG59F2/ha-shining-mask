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
    return Cipher(algorithms.AES(AES_KEY), modes.ECB())  # noqa: S305 - device protocol


def encrypt_block(block: bytes) -> bytes:
    if len(block) != 16:
        raise ValueError("block must be 16 bytes")
    enc = _cipher().encryptor()
    return enc.update(block) + enc.finalize()


def decrypt_block(block: bytes) -> bytes:
    dec = _cipher().decryptor()
    return dec.update(block[:16]) + dec.finalize()


def build_plain(tag: str, args: bytes | Iterable[int] = b"") -> bytes:
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
    return build_command("LIGHT", [max(0, min(255, value))])


def cmd_image(index: int) -> bytes:
    return build_command("IMAG", [index & 0xFF])


def cmd_animation(index: int) -> bytes:
    return build_command("ANIM", [index & 0xFF])


def cmd_text_mode(mode: int) -> bytes:
    return build_command("MODE", [mode & 0xFF])


def cmd_speed(speed: int) -> bytes:
    return build_command("SPEED", [speed & 0xFF])


def cmd_play(slots: Sequence[int]) -> bytes:
    """Play uploaded DIY images (1-based slots), cycling in the given order."""
    if not 1 <= len(slots) <= 10:
        raise ValueError("between 1 and 10 slots per PLAY command")
    return build_command("PLAY", [len(slots), *[s & 0xFF for s in slots]])


def cmd_delete(slots: Sequence[int]) -> bytes:
    if not 1 <= len(slots) <= 10:
        raise ValueError("between 1 and 10 slots per DELE command")
    return build_command("DELE", [len(slots), *[s & 0xFF for s in slots]])


def cmd_check() -> bytes:
    return build_command("CHEC")


def cmd_front_color(rgb: Sequence[int], enable: bool = True) -> bytes:
    return build_command("FC", [int(enable), *rgb[:3]])


def cmd_back_color(rgb: Sequence[int], enable: bool = True) -> bytes:
    return build_command("BG", [int(enable), *rgb[:3]])


def cmd_text_color_mode(mode: int, enable: bool = True) -> bytes:
    """00-03 text gradients, 04-07 background animations."""
    return build_command("M", [int(enable), mode & 0xFF])


def cmd_upload_start_text(total_len: int, bitmap_len: int) -> bytes:
    return build_command("DATS", total_len.to_bytes(2, "big") + bitmap_len.to_bytes(2, "big") + b"\x00")


def cmd_upload_start_image(total_len: int, slot: int) -> bytes:
    return build_command("DATS", total_len.to_bytes(2, "big") + slot.to_bytes(2, "big") + b"\x01")


def cmd_upload_complete() -> bytes:
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
