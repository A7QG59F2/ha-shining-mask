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


class ShiningMask:
    def __init__(self, hass: HomeAssistant, address: str, name: str, disconnect_after: int, pixel_order: str) -> None:
        self.hass = hass
        self.address = address
        self.name = name
        self.disconnect_after = disconnect_after
        self.pixel_order = pixel_order
        self.state = MaskState()
        self._ble_device: BLEDevice | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._notify: asyncio.Queue[str] = asyncio.Queue()
        self._idle_handle: asyncio.TimerHandle | None = None
        self._listeners: list[Callable[[], None]] = []
        self._cmd_response = False
        self._upload_response = False

    # ------------------------------------------------------------ listeners
    @callback
    def async_add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def _notify_listeners(self) -> None:
        for cb in list(self._listeners):
            cb()

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
        client = await establish_connection(
            BleakClientWithServiceCache, device, self.name, disconnected_callback=self._on_disconnect, max_attempts=3
        )
        cmd_char = client.services.get_characteristic(p.CMD_UUID)
        up_char = client.services.get_characteristic(p.UPLOAD_UUID)
        if cmd_char is None:
            await client.disconnect()
            raise HomeAssistantError("Device does not expose the Shining Mask command characteristic")
        self._cmd_response = "write-without-response" not in cmd_char.properties
        self._upload_response = up_char is not None and "write-without-response" not in up_char.properties
        self._notify = asyncio.Queue()
        await client.start_notify(p.NOTIFY_UUID, self._on_notification)
        self._client = client
        self.state.connected = True
        self._notify_listeners()
        return client

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
        await client.write_gatt_char(p.CMD_UUID, packet, response=self._cmd_response)

    async def async_send(self, *packets: bytes) -> None:
        """Send one or more encrypted command packets."""
        async with self._lock:
            client = await self._ensure_connected()
            for pkt in packets:
                await self._write_cmd(client, pkt)
            self._schedule_idle_disconnect()

    async def async_upload(self, start_packet: bytes, payload: bytes) -> None:
        async with self._lock:
            client = await self._ensure_connected()
            self._drain()
            await self._write_cmd(client, start_packet)
            if not await self._expect("DATSOK", ACK_TIMEOUT):
                raise HomeAssistantError("Mask did not acknowledge upload start (DATSOK)")
            for pkt in p.upload_packets(payload):
                await client.write_gatt_char(p.UPLOAD_UUID, pkt, response=self._upload_response)
                if not await self._expect("REOK", PACKET_ACK_TIMEOUT):
                    _LOGGER.debug("No REOK for packet %d, continuing", pkt[1])
            await self._write_cmd(client, p.cmd_upload_complete())
            if not await self._expect("DATCPOK", ACK_TIMEOUT):
                _LOGGER.warning("Upload finished but mask did not send DATCPOK")
            self._schedule_idle_disconnect()

    # ------------------------------------------------------------ high level
    async def async_set_brightness(self, value: int) -> None:
        await self.async_send(p.cmd_brightness(value))
        if value > 0:
            self.state.brightness = value
        self.state.is_on = value > 0
        self._notify_listeners()

    async def async_turn_on(self, brightness: int | None = None) -> None:
        await self.async_set_brightness(brightness or self.state.brightness or 255)

    async def async_turn_off(self) -> None:
        await self.async_send(p.cmd_brightness(0))
        self.state.is_on = False
        self._notify_listeners()

    async def async_show_image(self, index: int) -> None:
        await self.async_send(p.cmd_image(index))
        self.state.image, self.state.animation, self.state.diy = index, None, []
        self._notify_listeners()

    async def async_show_animation(self, index: int) -> None:
        await self.async_send(p.cmd_animation(index))
        self.state.animation, self.state.image, self.state.diy = index, None, []
        self._notify_listeners()

    async def async_play_diy(self, slots: Sequence[int], speed: int | None = None) -> None:
        packets = []
        if speed is not None:
            packets.append(p.cmd_speed(speed))
        packets.append(p.cmd_play(list(slots)))
        await self.async_send(*packets)
        self.state.diy, self.state.image, self.state.animation = list(slots), None, None
        if speed is not None:
            self.state.speed = speed
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
