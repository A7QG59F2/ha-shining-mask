#!/usr/bin/env python3
"""Standalone tester for the Shining Mask protocol from a PC with Bluetooth.

pip install bleak cryptography pillow
python mask_cli.py scan
python mask_cli.py light 120
python mask_cli.py image 5
python mask_cli.py anim 2
python mask_cli.py text "Hello"
python mask_cli.py upload 8 test_pattern        # builtin face, or a path to a PNG
python mask_cli.py play 4 5 --speed 220
python mask_cli.py --order row upload 8 test_pattern
"""

import argparse
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "shining_mask"))

from bleak import BleakClient, BleakScanner  # noqa: E402

import graphics  # noqa: E402
import protocol as p  # noqa: E402


async def find(address):
    if address:
        return address
    dev = await BleakScanner.find_device_by_filter(lambda d, ad: (d.name or "").upper().startswith("MASK"), 10)
    if not dev:
        sys.exit("No mask found")
    print("Using", dev.name, dev.address)
    return dev.address


async def upload(client, q, start, payload):
    await client.write_gatt_char(p.CMD_UUID, start, response=False)
    print("start ->", await asyncio.wait_for(q.get(), 5))
    for pkt in p.upload_packets(payload):
        await client.write_gatt_char(p.UPLOAD_UUID, pkt, response=False)
        try:
            await asyncio.wait_for(q.get(), 2)
        except TimeoutError:
            print("no REOK for", pkt[1])
    await client.write_gatt_char(p.CMD_UUID, p.cmd_upload_complete(), response=False)
    print("done ->", await asyncio.wait_for(q.get(), 5))


async def main(a):
    if a.cmd == "scan":
        for d in await BleakScanner.discover(8):
            if (d.name or "").upper().startswith("MASK"):
                print(d.address, d.name)
        return
    q: asyncio.Queue = asyncio.Queue()
    async with BleakClient(await find(a.address)) as client:
        await client.start_notify(p.NOTIFY_UUID, lambda _c, d: q.put_nowait(p.parse_notification(bytes(d))))
        w = lambda pkt: client.write_gatt_char(p.CMD_UUID, pkt, response=False)  # noqa: E731
        if a.cmd == "light":
            await w(p.cmd_brightness(int(a.args[0])))
        elif a.cmd == "image":
            await w(p.cmd_image(int(a.args[0])))
        elif a.cmd == "anim":
            await w(p.cmd_animation(int(a.args[0])))
        elif a.cmd == "play":
            if a.speed is not None:
                await w(p.cmd_speed(a.speed))
            await w(p.cmd_play([int(x) for x in a.args]))
        elif a.cmd == "text":
            payload, blen = graphics.render_text(" ".join(a.args), (255, 120, 0))
            await upload(client, q, p.cmd_upload_start_text(len(payload), blen), payload)
            await w(p.cmd_text_mode(p.TEXT_MODE_SCROLL_LEFT))
        elif a.cmd == "upload":
            slot, src = int(a.args[0]), a.args[1]
            from PIL import Image

            img = graphics.BUILTIN_FACES[src]() if src in graphics.BUILTIN_FACES else Image.open(src)
            payload = graphics.image_to_payload(img, a.order)
            await upload(client, q, p.cmd_upload_start_image(len(payload), slot), payload)
            await w(p.cmd_play([slot]))
        elif a.cmd == "check":
            await w(p.cmd_check())
            print(await asyncio.wait_for(q.get(), 5))
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--address")
    ap.add_argument("--order", default="column", choices=["column", "row"])
    ap.add_argument("--speed", type=int)
    ap.add_argument("cmd", choices=["scan", "light", "image", "anim", "play", "text", "upload", "check"])
    ap.add_argument("args", nargs="*")
    asyncio.run(main(ap.parse_args()))
