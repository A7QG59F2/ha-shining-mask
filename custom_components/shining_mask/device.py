"""BLE connection manager for one Shining Mask (works through ESPHome/TECHO5 proxies)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import logging

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from . import protocol as p

_LOGGER = logging.getLogger(__name__)

ACK_TIMEOUT = 5.0
PACKET_ACK_TIMEOUT = 2.0


@dataclass
class MaskState:
    brightness: int = 255
    is_on: bool = True
    image: int | None = None
    animation: int | None = None
    diy: list[int] = field(default_factory=list)
    text: str = ""
    text_mode: str = "scroll_left"
    speed: int | None = None
    connected: bool = False
    diy_count: int | None = None
    gatt: list[str] = field(default_factory=list)
    last_error: str | None = None
    # the face last chosen by a person (dashboard / numbers / actions), not by the voice-face automation
    selected: tuple[str, list[int]] | None = None
    # installed assistant face pack: role -> DIY slots
    pack: dict[str, list[int]] = field(default_factory=dict)
    pack_name: str | None = None


class ShiningMask:
    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        name: str,
        disconnect_after: int,
        pixel_order: str,
        max_brightness: int = 128,
        blank_slot: int = 9,
    ) -> None:
        self.hass = hass
        self.address = address
        self.name = name
        self.disconnect_after = disconnect_after
        self.pixel_order = pixel_order
        self.max_brightness = max(1, min(255, max_brightness))
        self.blank_slot = blank_slot
        self._blank_uploaded = False
        self.slot_names: dict[int, str] = {}
        self.preview_version = 0
        self.state = MaskState()
        self._ble_device: BLEDevice | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._notify: asyncio.Queue[str] = asyncio.Queue()
        self._idle_handle: asyncio.TimerHandle | None = None
        self._listeners: list[Callable[[], None]] = []
        self._cmd_response = False
        self._upload_response = False
        self._response_override: bool | None = None
        self._cmd_char = p.CMD_UUID
        self._up_char = p.UPLOAD_UUID
        self._store: Store = Store(hass, 1, f"shining_mask.{address.replace(':', '').lower()}")

    # ------------------------------------------------------------ persistence
    async def async_load(self) -> None:
        """Restore remembered state (chosen face, slot names, brightness, last face) after a restart."""
        data = await self._store.async_load() or {}
        s = self.state
        if sel := data.get("selected"):
            s.selected = (sel[0], [int(v) for v in sel[1]])
        s.brightness = int(data.get("brightness", s.brightness))
        s.is_on = bool(data.get("is_on", s.is_on))
        s.image = data.get("image")
        s.animation = data.get("animation")
        s.diy = [int(v) for v in data.get("diy", [])]
        s.text = data.get("text", "")
        s.text_mode = data.get("text_mode", s.text_mode)
        s.speed = data.get("speed")
        self.slot_names = {int(k): v for k, v in data.get("slot_names", {}).items()}
        s.pack = {r: [int(v) for v in slots] for r, slots in (data.get("pack") or {}).items()}
        s.pack_name = data.get("pack_name")

    def _data_to_save(self) -> dict:
        s = self.state
        return {
            "selected": [s.selected[0], s.selected[1]] if s.selected else None,
            "brightness": s.brightness,
            "is_on": s.is_on,
            "image": s.image,
            "animation": s.animation,
            "diy": s.diy,
            "text": s.text,
            "text_mode": s.text_mode,
            "speed": s.speed,
            "slot_names": {str(k): v for k, v in self.slot_names.items()},
            "pack": s.pack,
            "pack_name": s.pack_name,
        }

    # ------------------------------------------------------------ listeners
    @callback
    def async_add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def _notify_listeners(self) -> None:
        self._store.async_delay_save(self._data_to_save, 5)
        for cb in list(self._listeners):
            cb()

    @callback
    def preview_changed(self) -> None:
        self.preview_version += 1
        self._notify_listeners()

    @callback
    def set_ble_device(self, device: BLEDevice) -> None:
        self._ble_device = device

    # ------------------------------------------------------------ connection
    async def _ensure_connected(self) -> BleakClientWithServiceCache:
        if self._client and self._client.is_connected:
            return self._client
        device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True) or self._ble_device
        if device is None:
            raise HomeAssistantError(
                f"{self.name} is not in range of any connectable Bluetooth adapter or proxy "
                "(is 'Bluetooth proxy connections' enabled on the TECHO5 Show, and is the mask on?)"
            )
        _LOGGER.debug("Connecting to %s via %s", self.address, getattr(device, "details", None))
        try:
            client = await establish_connection(
                BleakClientWithServiceCache, device, self.name, disconnected_callback=self._on_disconnect, max_attempts=3
            )
        except Exception as err:  # noqa: BLE001
            self.state.last_error = f"connect: {type(err).__name__}: {err}"
            self._notify_listeners()
            raise HomeAssistantError(f"Could not connect to {self.name}: {err}") from err

        chars = self._resolve(client)
        if chars[0] is None:
            # stale GATT cache is the usual cause - clear it and rediscover once
            _LOGGER.debug("Command characteristic missing, clearing GATT cache and retrying")
            try:
                await client.clear_cache()
            except Exception:  # noqa: BLE001
                pass
            await client.disconnect()
            client = await establish_connection(
                BleakClientWithServiceCache, device, self.name, disconnected_callback=self._on_disconnect, max_attempts=3
            )
            chars = self._resolve(client)
        cmd_char, notify_char, up_char = chars
        if cmd_char is None:
            await client.disconnect()
            self.state.last_error = "no command characteristic; see 'gatt' attribute"
            self._notify_listeners()
            raise HomeAssistantError(
                "Connected, but the mask has no recognised command characteristic. "
                "Check the 'gatt' attribute on the mask light entity and share it."
            )
        self._cmd_char, self._up_char = cmd_char, (up_char or p.UPLOAD_UUID)
        self._cmd_response = (
            self._response_override
            if self._response_override is not None
            else "write-without-response" not in cmd_char.properties
        )
        self._upload_response = up_char is not None and "write-without-response" not in up_char.properties
        self._notify = asyncio.Queue()
        if notify_char is not None:
            try:
                await client.start_notify(notify_char, self._on_notification)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Could not subscribe to mask notifications: %s", err)
        self._client = client
        self.state.connected = True
        self.state.last_error = None
        self._notify_listeners()
        return client

    def _resolve(self, client):
        """Find command / notify / upload characteristics; record the GATT table for diagnostics."""
        summary, cmd, notify, up = [], None, None, None
        writable = []
        for service in client.services:
            for ch in service.characteristics:
                props = ",".join(ch.properties)
                summary.append(f"{service.uuid[4:8]}/{ch.uuid} h{ch.handle} [{props}]")
                u = ch.uuid.lower()
                if u == p.CMD_UUID:
                    cmd = ch
                elif u == p.NOTIFY_UUID:
                    notify = ch
                elif u == p.UPLOAD_UUID:
                    up = ch
                if service.uuid.lower() == p.SERVICE_UUID and ({"write", "write-without-response"} & set(ch.properties)):
                    writable.append(ch)
        if cmd is None and writable:
            # fallback for variants: first writable char in the FFF0 service
            cmd = writable[0]
            _LOGGER.warning("Known command characteristic not found; falling back to %s", cmd.uuid)
        if notify is None:
            notify = next(
                (ch for s in client.services if s.uuid.lower() == p.SERVICE_UUID
                 for ch in s.characteristics if {"notify", "indicate"} & set(ch.properties)),
                None,
            )
        self.state.gatt = summary
        return cmd, notify, up

    def _on_disconnect(self, _client) -> None:
        _LOGGER.debug("%s disconnected", self.address)
        self._client = None
        self.hass.loop.call_soon_threadsafe(self._mark_disconnected)

    @callback
    def _mark_disconnected(self) -> None:
        self.state.connected = False
        self._notify_listeners()

    def _on_notification(self, _char, data: bytearray) -> None:
        try:
            msg = p.parse_notification(bytes(data))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Undecodable notification %s", bytes(data).hex())
            return
        _LOGGER.debug("Mask notification: %s", msg)
        if msg.startswith("CHEC") and len(data) >= 16:
            plain = p.decrypt_block(bytes(data))
            self.state.diy_count = plain[5]
        self._notify.put_nowait(msg)

    async def _expect(self, prefix: str, timeout: float) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            try:
                msg = await asyncio.wait_for(self._notify.get(), remaining)
            except TimeoutError:
                return False
            if msg.startswith(prefix):
                return True

    def _drain(self) -> None:
        while not self._notify.empty():
            self._notify.get_nowait()

    def _schedule_idle_disconnect(self) -> None:
        if self._idle_handle:
            self._idle_handle.cancel()
            self._idle_handle = None
        if self.disconnect_after > 0:
            self._idle_handle = self.hass.loop.call_later(
                self.disconnect_after, lambda: self.hass.async_create_task(self.async_disconnect())
            )

    async def async_disconnect(self) -> None:
        async with self._lock:
            if self._client:
                client, self._client = self._client, None
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            self.state.connected = False
        self._notify_listeners()

    # ------------------------------------------------------------ primitives
    async def _write_cmd(self, client, packet: bytes) -> None:
        await client.write_gatt_char(self._cmd_char, packet, response=self._cmd_response)

    async def _drop(self) -> None:
        client, self._client = self._client, None
        if client:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self.state.connected = False

    async def async_send(self, *packets: bytes) -> None:
        """Send one or more encrypted command packets (one reconnect-and-retry on failure)."""
        async with self._lock:
            for attempt in (1, 2):
                client = await self._ensure_connected()
                try:
                    for pkt in packets:
                        await self._write_cmd(client, pkt)
                    break
                except Exception as err:  # noqa: BLE001
                    self.state.last_error = f"write: {type(err).__name__}: {err}"
                    _LOGGER.warning("Mask write failed (attempt %d): %s: %s", attempt, type(err).__name__, err)
                    # some masks reject write-with-response; flip mode on the retry
                    self._response_override = not self._cmd_response
                    await self._drop()
                    if attempt == 2:
                        self._notify_listeners()
                        raise HomeAssistantError(f"Mask rejected the command: {type(err).__name__}: {err}") from err
            self._schedule_idle_disconnect()

    async def async_upload(self, start_packet: bytes, payload: bytes) -> None:
        async with self._lock:
            client = await self._ensure_connected()
            self._drain()
            await self._write_cmd(client, start_packet)
            if not await self._expect("DATSOK", ACK_TIMEOUT):
                raise HomeAssistantError("Mask did not acknowledge upload start (DATSOK)")
            for pkt in p.upload_packets(payload):
                await client.write_gatt_char(self._up_char, pkt, response=self._upload_response)
                if not await self._expect("REOK", PACKET_ACK_TIMEOUT):
                    _LOGGER.debug("No REOK for packet %d, continuing", pkt[1])
            await self._write_cmd(client, p.cmd_upload_complete())
            if not await self._expect("DATCPOK", ACK_TIMEOUT):
                _LOGGER.warning("Upload finished but mask did not send DATCPOK")
            self._schedule_idle_disconnect()

    # ------------------------------------------------------------ high level
    def _scale(self, value: int) -> int:
        """Map HA brightness 1-255 onto the mask's usable 1..max_brightness."""
        if value <= 0:
            return 0
        return max(1, round(value * self.max_brightness / 255))

    async def async_set_brightness(self, value: int) -> None:
        if value <= 0:
            await self.async_turn_off()
            return
        await self.async_send(p.cmd_brightness(self._scale(value)))
        was_off = not self.state.is_on
        self.state.brightness = value
        self.state.is_on = True
        if was_off:
            await self._restore_face()
        self._notify_listeners()

    async def async_turn_on(self, brightness: int | None = None) -> None:
        await self.async_set_brightness(brightness or self.state.brightness or 255)

    async def _ensure_blank(self) -> None:
        if self._blank_uploaded:
            return
        from .graphics import face_blank, image_to_payload

        payload = await self.hass.async_add_executor_job(lambda: image_to_payload(face_blank(), self.pixel_order))
        await self.async_upload_image(self.blank_slot, payload)
        self._blank_uploaded = True

    async def async_turn_off(self) -> None:
        """The mask has no power-off command: show an all-black DIY frame at minimum brightness."""
        try:
            await self._ensure_blank()
            await self.async_send(p.cmd_brightness(0), p.cmd_play([self.blank_slot]))
        except HomeAssistantError:
            await self.async_send(p.cmd_brightness(0))
            raise
        self.state.is_on = False
        self._notify_listeners()

    async def _restore_face(self) -> None:
        s = self.state
        if s.diy:
            await self.async_send(p.cmd_play(s.diy))
        elif s.animation is not None:
            await self.async_send(p.cmd_animation(s.animation))
        elif s.image is not None:
            await self.async_send(p.cmd_image(s.image))
        else:
            await self.async_send(p.cmd_image(1))

    async def _wake(self) -> None:
        """Showing something while 'off' turns the light back on."""
        if not self.state.is_on:
            await self.async_send(p.cmd_brightness(self._scale(self.state.brightness or 255)))
            self.state.is_on = True

    async def async_show_image(self, index: int, temporary: bool = False) -> None:
        await self._wake()
        await self.async_send(p.cmd_image(index))
        self.state.image, self.state.animation, self.state.diy = index, None, []
        if not temporary:
            self.state.selected = ("image", [index])
        self._notify_listeners()

    async def async_show_animation(self, index: int, temporary: bool = False) -> None:
        await self._wake()
        await self.async_send(p.cmd_animation(index))
        self.state.animation, self.state.image, self.state.diy = index, None, []
        if not temporary:
            self.state.selected = ("animation", [index])
        self._notify_listeners()

    async def async_restore_selected(self) -> None:
        """Go back to the face a person last chose (falls back to DIY slot 1)."""
        kind, values = self.state.selected or ("diy", [1])
        if kind == "image":
            await self.async_show_image(values[0], temporary=True)
        elif kind == "animation":
            await self.async_show_animation(values[0], temporary=True)
        else:
            await self.async_play_diy(values, temporary=True)

    async def async_play_role(self, role: str, speed: int | None = None) -> None:
        """Show a face-pack role (idle/listening/thinking/talking/error/sleep); falls back to idle."""
        pack = self.state.pack
        if not pack:
            raise HomeAssistantError("No face pack installed - run shining_mask.install_face_pack first")
        slots = pack.get(role) or pack.get("idle")
        if not slots:
            raise HomeAssistantError(f"Face pack has no '{role}' or 'idle' frames")
        await self.async_play_diy(slots, speed, temporary=True)

    async def async_play_diy(self, slots: Sequence[int], speed: int | None = None, temporary: bool = False) -> None:
        packets = []
        if speed is not None:
            packets.append(p.cmd_speed(speed))
        packets.append(p.cmd_play(list(slots)))
        await self._wake()
        await self.async_send(*packets)
        self.state.diy, self.state.image, self.state.animation = list(slots), None, None
        if speed is not None:
            self.state.speed = speed
        if not temporary and slots != [self.blank_slot]:
            self.state.selected = ("diy", list(slots))
        self._notify_listeners()

    async def async_set_speed(self, speed: int) -> None:
        await self.async_send(p.cmd_speed(speed))
        self.state.speed = speed
        self._notify_listeners()

    async def async_set_text_mode(self, mode_name: str, mode_value: int) -> None:
        await self.async_send(p.cmd_text_mode(mode_value))
        self.state.text_mode = mode_name
        self._notify_listeners()

    async def async_set_text(self, text: str, color=(255, 255, 255), mode: int | None = None, speed: int | None = None) -> None:
        from .graphics import render_text  # Pillow import off the event-loop hot path

        payload, bitmap_len = await self.hass.async_add_executor_job(render_text, text, color)
        await self._wake()
        await self.async_upload(p.cmd_upload_start_text(len(payload), bitmap_len), payload)
        extra = []
        if mode is not None:
            extra.append(p.cmd_text_mode(mode))
        if speed is not None:
            extra.append(p.cmd_speed(speed))
        if extra:
            await self.async_send(*extra)
        self.state.text = text
        self._notify_listeners()

    async def async_upload_image(self, slot: int, payload: bytes) -> None:
        if len(payload) != p.IMAGE_BYTES:
            raise HomeAssistantError(f"Image payload must be {p.IMAGE_BYTES} bytes")
        await self.async_upload(p.cmd_upload_start_image(len(payload), slot), payload)
        if slot == self.blank_slot:
            self._blank_uploaded = payload == bytes(len(payload))

    async def async_delete_diy(self, slots: Sequence[int]) -> None:
        for i in range(0, len(slots), 10):
            await self.async_send(p.cmd_delete(list(slots[i : i + 10])))

    async def async_check(self) -> int | None:
        async with self._lock:
            client = await self._ensure_connected()
            self._drain()
            await self._write_cmd(client, p.cmd_check())
            await self._expect("CHEC", ACK_TIMEOUT)
            self._schedule_idle_disconnect()
        self._notify_listeners()
        return self.state.diy_count

    async def async_raw(self, tag: str, args: bytes) -> None:
        await self.async_send(p.build_command(tag, args))
