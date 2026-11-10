"""BLE connection manager for one Shining Mask (local adapter or ESPHome Bluetooth proxy)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import logging
import time

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
    """Everything we know or last sent to the mask. The mask never reports back, so this is our memory."""
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
    # the face last chosen by a person (dashboard / numbers / actions), not by the assistant
    selected: tuple[str, list[int]] | None = None
    # installed assistant face pack: role -> DIY slots
    pack: dict[str, list[int]] = field(default_factory=dict)
    pack_name: str | None = None
    # text appearance (app: text colour, background colour, effects)
    text_color: list[int] = field(default_factory=lambda: [255, 255, 255])
    text_color_on: bool = False
    bg_color: list[int] = field(default_factory=lambda: [0, 0, 0])
    bg_color_on: bool = False
    text_effect: str = "solid"
    gesture_on: bool = False
    gesture_library: str = "all"
    gesture_circulation: str = "order"
    # faces picked for the gesture face switch, kept per library like the app does
    # (gallery = built-in image numbers, diy = DIY slot numbers)
    gesture_gallery_items: list[int] = field(default_factory=list)
    gesture_diy_items: list[int] = field(default_factory=list)
    visualizer_on: bool = False
    visualizer_style: int = 0
    visualizer_delay_ms: int = 0
    bars_sensitivity: int = 100  # %
    bars_contrast: float = 1.6
    bars_bass: int = 100  # %
    bars_mid: int = 100
    bars_treble: int = 100
    # clock screen (see clock.py)
    clock_weather: str | None = None  # weather entity for the sky and temperature
    clock_speed: int = 230  # playback speed of the clock's two frames (colon blink)
    clock_prev: tuple[str, list[int]] | None = None  # chosen face before the clock was switched on
    clock_theme: str = "Classic"  # colours of time/temperature/date (clockface.CLOCK_THEMES)
    clock_motion: str = "Animated"  # "Animated" = 2 frames a minute, "Still" = 1 (less upload arrow)
    clock_style: str = "Picture"  # "Picture" (uploads each minute) or "Digit flip" (no uploads)
    clock_digits: str | None = None  # theme the digit-flip digits were uploaded in (None = not there)
    clock_digit_slots: list[int] = field(default_factory=list)  # 0-9, ':', info screen
    clock_slots: list[int] = field(default_factory=list)  # picture clock: 2 buffers x 2 frames
    # who uploaded each DIY slot: pack, blank, digits, clock, effect, other (see allocate_slots)
    slot_owner: dict[int, str] = field(default_factory=dict)
    slot_played: dict[int, float] = field(default_factory=dict)  # slot -> last time it was played
    # voice-assistant face (see assist.py)
    assist_satellite: str | None = None  # assist_satellite entity to follow; None = off
    assist_faces: dict[str, str] = field(default_factory=dict)  # listening/thinking/talking/idle/error -> choice
    assist_talk_speed: int = 220  # DIY speed while talking
    assist_idle_return: int = 0  # seconds before idle face -> chosen face (0 = stay)
    assist_unavailable_after: int = 180  # seconds showing the error face before the action below
    assist_unavailable_action: str = "Restore chosen face"


class ShiningMask:
    """One mask: the Bluetooth link, every command, saved state, and the screen-priority rules.

    Screen priority (highest first): assistant face (music_hold) > music bars > chosen face.
    """
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
        self.visualizer = None  # MaskVisualizer when the music visualizer is on
        self.clock = None  # MaskClock, set up by __init__.py
        self.assistant = None  # MaskAssistant (voice-assistant faces), set up by __init__.py
        self.music_hold = False  # True while the voice assistant face is showing
        self._bars_live = False  # the mask is currently in rhythm (music bars) mode
        self._restoring = False
        self.visualizer_port = 8928
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
        self._rhythm_char = p.RHYTHM_UUID
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
        s.text_color = list(data.get("text_color", s.text_color))
        s.text_color_on = bool(data.get("text_color_on", False))
        s.bg_color = list(data.get("bg_color", s.bg_color))
        s.bg_color_on = bool(data.get("bg_color_on", False))
        old_names = {"gradient_1": "dots_on_white", "gradient_2": "rainbow_edges",
                     "gradient_3": "yellow_to_blue", "gradient_4": "green_blue_circle"}  # before 0.22
        s.text_effect = old_names.get(data.get("text_effect", "solid"), data.get("text_effect", "solid"))
        s.gesture_on = bool(data.get("gesture_on", False))
        s.gesture_library = data.get("gesture_library", "all")
        s.gesture_circulation = data.get("gesture_circulation", "order")
        s.gesture_gallery_items = [int(v) for v in data.get("gesture_gallery_items", [])]
        s.gesture_diy_items = [int(v) for v in data.get("gesture_diy_items", [])]
        # before 0.17 there was one list; keep it for whichever library was selected then
        if "gesture_items" in data and s.gesture_library in ("gallery", "diy"):
            setattr(s, f"gesture_{s.gesture_library}_items", [int(v) for v in data["gesture_items"]])
        s.visualizer_on = bool(data.get("visualizer_on", False))
        s.visualizer_style = max(0, min(4, int(data.get("visualizer_style", 0))))
        s.visualizer_delay_ms = int(data.get("visualizer_delay_ms", 0))
        for key in ("bars_sensitivity", "bars_bass", "bars_mid", "bars_treble"):
            setattr(s, key, int(data.get(key, 100)))
        s.bars_contrast = float(data.get("bars_contrast", 1.6))
        s.clock_weather = data.get("clock_weather")
        s.clock_speed = int(data.get("clock_speed", 230))
        s.clock_theme = data.get("clock_theme", "Classic")
        s.clock_motion = data.get("clock_motion", "Animated")
        s.clock_style = data.get("clock_style", "Picture")
        s.clock_digits = data.get("clock_digits")
        s.clock_digit_slots = [int(v) for v in data.get("clock_digit_slots", [])]
        s.clock_slots = [int(v) for v in data.get("clock_slots", [])]
        s.slot_owner = {int(k): v for k, v in (data.get("slot_owner") or {}).items()}
        s.slot_played = {int(k): float(v) for k, v in (data.get("slot_played") or {}).items()}
        s.assist_satellite = data.get("assist_satellite")
        s.assist_faces = dict(data.get("assist_faces") or {})
        s.assist_talk_speed = int(data.get("assist_talk_speed", 220))
        s.assist_idle_return = int(data.get("assist_idle_return", 0))
        s.assist_unavailable_after = int(data.get("assist_unavailable_after", 180))
        s.assist_unavailable_action = data.get("assist_unavailable_action", "Restore chosen face")
        if prev := data.get("clock_prev"):
            s.clock_prev = (prev[0], [int(v) for v in prev[1]])

    def _data_to_save(self) -> dict:
        """The parts of the state that survive a restart (written to .storage)."""
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
            "text_color": s.text_color,
            "text_color_on": s.text_color_on,
            "bg_color": s.bg_color,
            "bg_color_on": s.bg_color_on,
            "text_effect": s.text_effect,
            "gesture_on": s.gesture_on,
            "gesture_library": s.gesture_library,
            "gesture_circulation": s.gesture_circulation,
            "gesture_gallery_items": s.gesture_gallery_items,
            "gesture_diy_items": s.gesture_diy_items,
            "visualizer_on": s.visualizer_on,
            "visualizer_style": s.visualizer_style,
            "visualizer_delay_ms": s.visualizer_delay_ms,
            "bars_sensitivity": s.bars_sensitivity,
            "bars_contrast": s.bars_contrast,
            "bars_bass": s.bars_bass,
            "bars_mid": s.bars_mid,
            "bars_treble": s.bars_treble,
            "clock_weather": s.clock_weather,
            "clock_speed": s.clock_speed,
            "clock_theme": s.clock_theme,
            "clock_motion": s.clock_motion,
            "clock_style": s.clock_style,
            "clock_digits": s.clock_digits,
            "clock_digit_slots": s.clock_digit_slots,
            "clock_slots": s.clock_slots,
            "slot_owner": {str(k): v for k, v in s.slot_owner.items()},
            "slot_played": {str(k): v for k, v in s.slot_played.items()},
            "assist_satellite": s.assist_satellite,
            "assist_faces": s.assist_faces,
            "assist_talk_speed": s.assist_talk_speed,
            "assist_idle_return": s.assist_idle_return,
            "assist_unavailable_after": s.assist_unavailable_after,
            "assist_unavailable_action": s.assist_unavailable_action,
            "clock_prev": [s.clock_prev[0], s.clock_prev[1]] if s.clock_prev else None,
        }

    # ------------------------------------------------------------ listeners
    @callback
    def async_add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        """Register an entity callback for state changes; returns the unsubscribe function."""
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def _notify_listeners(self) -> None:
        """Tell every entity to refresh, and schedule a save of the state."""
        self._store.async_delay_save(self._data_to_save, 5)
        for cb in list(self._listeners):
            cb()

    @callback
    def preview_changed(self) -> None:
        """Previews/thumbnails changed on disk: bump the version so image entities reload."""
        self.preview_version += 1
        self._notify_listeners()

    @callback
    def set_ble_device(self, device: BLEDevice) -> None:
        """Remember the newest BLEDevice from an advertisement (picks the best adapter/proxy)."""
        self._ble_device = device

    # ------------------------------------------------------------ connection
    async def _ensure_connected(self) -> BleakClientWithServiceCache:
        """Return a connected client, connecting (and finding the characteristics) if needed."""
        if self._client and self._client.is_connected:
            return self._client
        device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True) or self._ble_device
        if device is None:
            raise HomeAssistantError(
                f"{self.name} is not in range of any connectable Bluetooth adapter or proxy "
                "(is the mask on, and does the proxy allow active connections?)"
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
        self._rhythm_char = p.RHYTHM_UUID
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
                elif u == p.RHYTHM_UUID:
                    self._rhythm_char = ch
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
        """Bleak callback (may run off the event loop): hand the disconnect to the loop."""
        _LOGGER.debug("%s disconnected", self.address)
        self._client = None
        self.hass.loop.call_soon_threadsafe(self._mark_disconnected)

    @callback
    def _mark_disconnected(self) -> None:
        """Forget the client and show 'not connected' on the entities."""
        self.state.connected = False
        self._notify_listeners()

    def _on_notification(self, _char, data: bytearray) -> None:
        """Decrypt a notification from the mask (DATSOK, REOK, FACEOK, CHEC...) and queue it."""
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
        """Wait up to `timeout` seconds for a notification starting with `prefix`; False on timeout."""
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
        """Throw away queued notifications, so the next _expect only sees fresh answers."""
        while not self._notify.empty():
            self._notify.get_nowait()

    def _schedule_idle_disconnect(self) -> None:
        """Disconnect after the configured idle time (0 = stay connected)."""
        if self._idle_handle:
            self._idle_handle.cancel()
            self._idle_handle = None
        if self.disconnect_after > 0:
            self._idle_handle = self.hass.loop.call_later(
                self.disconnect_after, lambda: self.hass.async_create_task(self.async_disconnect())
            )

    async def async_disconnect(self) -> None:
        """Close the Bluetooth link now."""
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
        """Write one encrypted 16-byte packet to the command characteristic."""
        await client.write_gatt_char(self._cmd_char, packet, response=self._cmd_response)

    async def _drop(self) -> None:
        """Close and forget the current client after an error, so the next send reconnects."""
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
        """Upload a text bitmap or DIY image: start packet, data packets (each answered REOK), finish."""
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
        """Set brightness 0-255; scaled down to the brightness cap so the mask doesn't flicker."""
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
        """Make sure the all-black DIY slot exists (used for 'off', which really goes dark)."""
        if self._blank_uploaded:
            return
        from .graphics import face_blank, image_to_payload

        payload = await self.hass.async_add_executor_job(lambda: image_to_payload(face_blank(), self.pixel_order))
        await self.async_upload_image(self.blank_slot, payload, owner="blank")
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

    @property
    def holding_music(self) -> bool:
        """True while an assistant face must stay on top of the music bars."""
        return self.music_hold

    @property
    def bars_on_top(self) -> bool:
        """Music is playing to the mask and no assistant face is holding it off.

        Priority: assistant face > music bars > chosen (static) face. While this is True, faces
        other than the assistant's are not sent; the chosen one comes back when the music stops."""
        v = self.visualizer
        return v is not None and self.state.is_on and v.has_music and not self.music_hold and not self._restoring

    def _leave_bars(self) -> list[bytes]:
        """Packets to put before a face: exit rhythm mode first, or the bars keep drawing over it."""
        if self._bars_live:
            self._bars_live = False
            return [p.cmd_exit_rhythm()]
        return []

    async def _restore_face(self) -> None:
        """Show again whatever was last on screen (image, animation or DIY), e.g. after leaving bar mode."""
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

    def _covered_by_bars(self, kind: str, values: list[int], temporary: bool) -> bool:
        """Music bars own the screen: remember a hand-picked face for later, drop the rest."""
        if not self.bars_on_top:
            return False
        if not temporary:
            self.state.selected = (kind, values)
            self._notify_listeners()
        return True

    async def async_show_image(self, index: int, temporary: bool = False) -> None:
        """Show built-in image `index`. temporary=True (assistant faces) doesn't change the chosen face."""
        if self._covered_by_bars("image", [index], temporary):
            return
        await self._wake()
        await self.async_send(*self._leave_bars(), p.cmd_image(index))
        self.state.image, self.state.animation, self.state.diy = index, None, []
        if not temporary:
            self.state.selected = ("image", [index])
        self._notify_listeners()

    async def async_show_animation(self, index: int, temporary: bool = False) -> None:
        """Play built-in animation `index`. temporary=True doesn't change the chosen face."""
        if self._covered_by_bars("animation", [index], temporary):
            return
        await self._wake()
        await self.async_send(*self._leave_bars(), p.cmd_animation(index))
        self.state.animation, self.state.image, self.state.diy = index, None, []
        if not temporary:
            self.state.selected = ("animation", [index])
        self._notify_listeners()

    async def async_restore_selected(self, force: bool = False) -> None:
        """Go back to the face a person last chose (falls back to DIY slot 1).
        While music bars are up this does nothing: the chosen face returns when the music stops."""
        kind, values = self.state.selected or ("diy", [1])
        # going back to the chosen face means the assistant is done: let the music bars back in
        if self.music_hold:
            await self.async_set_music_hold(False)
        if self.bars_on_top and not force:
            return
        if kind == "clock" and self.clock is not None:
            await self.clock.async_show()  # shows the last minute at once, then refreshes it
            return
        self._restoring = True
        try:
            if kind == "image":
                await self.async_show_image(values[0], temporary=True)
            elif kind == "animation":
                await self.async_show_animation(values[0], temporary=True)
            else:
                await self.async_play_diy(values, temporary=True)
        finally:
            self._restoring = False

    async def async_set_clock(self, on: bool) -> None:
        """Make the clock the chosen face (on), or go back to the face chosen before it (off)."""
        s = self.state
        is_clock = bool(s.selected) and s.selected[0] == "clock"
        if on and not is_clock:
            s.clock_prev = s.selected
            s.selected = ("clock", [])
        elif not on and is_clock:
            s.selected = s.clock_prev or ("diy", [1])
        else:
            return
        self._notify_listeners()
        await self.async_restore_selected()

    def set_assist_option(self, **values) -> None:
        """Change voice-assistant face settings. A new satellite is followed immediately.

        Keys: satellite, talk_speed, idle_return, unavailable_after, unavailable_action, and
        face_<key> for listening/thinking/talking/idle/error.
        """
        s = self.state
        for key, value in values.items():
            if key.startswith("face_"):
                s.assist_faces[key[5:]] = value
            else:
                setattr(s, f"assist_{key}", value)
        if "satellite" in values and self.assistant is not None:
            self.assistant.start()
        self._notify_listeners()

    async def async_refresh_clock(self) -> None:
        """Redraw the clock now (after a colour/motion change) if it is on screen."""
        if self.clock is not None and self.clock.showing:
            self.clock.forget_uploads()
            await self.clock.async_show()

    def set_clock_option(self, **values) -> None:
        """clock_weather/speed/theme/motion/style; used from the next minute on."""
        for key in ("clock_weather", "clock_speed", "clock_theme", "clock_motion", "clock_style"):
            if key in values:
                setattr(self.state, key, values[key])
        self._notify_listeners()

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
        """Play DIY slots (one = still picture, several = animation). temporary=True keeps the chosen face."""
        packets = []
        if speed is not None:
            packets.append(p.cmd_speed(speed))
        packets.append(p.cmd_play(list(slots)))
        if self._covered_by_bars("diy", list(slots), temporary or slots == [self.blank_slot]):
            return
        now = time.time()
        for slot in slots:
            self.state.slot_played[slot] = now  # for allocate_slots: recently used = keep
        await self._wake()
        await self.async_send(*self._leave_bars(), *packets)
        self.state.diy, self.state.image, self.state.animation = list(slots), None, None
        if speed is not None:
            self.state.speed = speed
        if not temporary and slots != [self.blank_slot]:
            self.state.selected = ("diy", list(slots))
        self._notify_listeners()

    async def async_set_speed(self, speed: int) -> None:
        """Animation / DIY / text speed (0-255)."""
        await self.async_send(p.cmd_speed(speed))
        self.state.speed = speed
        self._notify_listeners()

    async def async_set_text_color(self, rgb: Sequence[int] | None, enable: bool) -> None:
        """Text colour: rgb plus whether the custom colour is on (FC command)."""
        rgb = list(rgb) if rgb is not None else self.state.text_color
        await self.async_send(p.cmd_front_color(rgb, enable))
        self.state.text_color, self.state.text_color_on = rgb, enable
        self._notify_listeners()

    async def async_set_bg_color(self, rgb: Sequence[int] | None, enable: bool) -> None:
        """Background colour behind text: rgb plus on/off (BC command)."""
        rgb = list(rgb) if rgb is not None else self.state.bg_color
        await self.async_send(p.cmd_back_color(rgb, enable))
        self.state.bg_color, self.state.bg_color_on = rgb, enable
        self._notify_listeners()

    async def async_set_text_effect(self, name: str, value: int | None) -> None:
        """Text effect: solid, colour gradients, or animated backgrounds (M command).

        value None = solid (effects off)."""
        await self.async_send(p.cmd_text_color_mode(value or 0, value is not None))
        self.state.text_effect = name
        self._notify_listeners()

    async def async_animation_loop(self) -> None:
        """Make the mask loop through its animations (LOOA command)."""
        await self._wake()
        await self.async_send(p.cmd_animation_loop())
        self.state.image, self.state.animation, self.state.diy = None, None, []
        self._notify_listeners()

    async def async_rhythm(self, mode: int, frames: Sequence[Sequence[int]], interval: float = 0.08) -> None:
        """Send one or more visualiser frames (12 levels 0-15 each)."""
        await self._wake()
        for i, levels in enumerate(frames):
            async with self._lock:
                if self.holding_music:
                    return  # an assistant face arrived while this frame waited: it wins
                client = await self._ensure_connected()
                await client.write_gatt_char(self._rhythm_char, p.cmd_rhythm_frame(mode, levels), response=False)
                self._bars_live = True
                self._schedule_idle_disconnect()
            if i < len(frames) - 1:
                await asyncio.sleep(interval)

    async def async_exit_rhythm(self, to_chosen: bool = False) -> None:
        """Leave bar mode; to_chosen=True goes to the hand-picked face instead of the last one shown."""
        self._bars_live = False
        await self.async_send(p.cmd_exit_rhythm())
        if to_chosen:
            await self.async_restore_selected(force=True)
        else:
            await self._restore_face()

    async def async_set_visualizer(self, on: bool) -> None:
        """Start/stop the Music Assistant (Sendspin) music-bars bridge."""
        from .visualizer import MaskVisualizer

        if on and self.visualizer is None:
            # The music-bars library is installed only when needed, so a missing internet
            # connection at startup can never stop the mask itself from loading.
            from homeassistant.requirements import RequirementsNotFound, async_process_requirements

            from .const import DOMAIN, VISUALIZER_REQUIREMENT

            try:
                await async_process_requirements(self.hass, DOMAIN, [VISUALIZER_REQUIREMENT])
            except RequirementsNotFound as err:
                raise HomeAssistantError(
                    f"Music visualizer needs {VISUALIZER_REQUIREMENT}, which couldn't be installed "
                    "(no internet?). The rest of the mask works; try the switch again later."
                ) from err
            viz = MaskVisualizer(self.hass, self, self.visualizer_port, self.state.visualizer_style, self.state.visualizer_delay_ms)
            try:
                await viz.async_start()
            except OSError as err:
                raise HomeAssistantError(f"Could not open port {self.visualizer_port}: {err}") from err
            self.visualizer = viz
            self._apply_tuning()
        elif not on and self.visualizer is not None:
            viz, self.visualizer = self.visualizer, None
            await viz.async_stop()
        self.state.visualizer_on = on
        self._notify_listeners()

    async def async_set_music_hold(self, hold: bool) -> None:
        """Voice assistant active: music bars pause so its face always wins."""
        self.music_hold = hold
        if hold and self.visualizer is not None:
            self.visualizer.pause_for_assist()
        if hold and self._bars_live:
            self._bars_live = False
            await self.async_send(p.cmd_exit_rhythm())  # leave bar mode so the face can show
        self._notify_listeners()

    def set_visualizer_tuning(self, **values) -> None:
        """style, delay_ms, bars_sensitivity, bars_contrast, bars_bass, bars_mid, bars_treble."""
        s = self.state
        if "style" in values:
            s.visualizer_style = max(0, min(4, int(values["style"])))
        if "delay_ms" in values:
            s.visualizer_delay_ms = int(values["delay_ms"])
        for key in ("bars_sensitivity", "bars_contrast", "bars_bass", "bars_mid", "bars_treble"):
            if key in values:
                setattr(s, key, values[key])
        self._apply_tuning()
        self._notify_listeners()

    def _apply_tuning(self) -> None:
        """Copy the saved bar settings (style, delay, sensitivity, EQ) to the running visualizer."""
        v, s = self.visualizer, self.state
        if v is None:
            return
        v.style, v.delay_ms = s.visualizer_style, s.visualizer_delay_ms
        v.sensitivity = s.bars_sensitivity / 100
        v.contrast = s.bars_contrast
        v.eq = (s.bars_bass / 100, s.bars_mid / 100, s.bars_treble / 100)

    def gesture_items(self, library: str | None = None) -> list[int]:
        """Faces picked for a library ('gallery' or 'diy'); 'all' has none."""
        lib = library or self.state.gesture_library
        return list(getattr(self.state, f"gesture_{lib}_items", []))

    async def async_set_gesture(
        self,
        enable: bool | None = None,
        library: str | None = None,
        circulation: str | None = None,
        items: Sequence[int] | None = None,
    ) -> None:
        """Change any gesture setting and send the complete setting to the mask.

        Anything left as None keeps its current value. `items` are the face numbers for the
        library being set (built-in image numbers for 'gallery', DIY slots for 'diy').
        """
        s = self.state
        on = s.gesture_on if enable is None else enable
        lib = library or s.gesture_library
        circ = circulation or s.gesture_circulation
        picked = self.gesture_items(lib) if items is None else list(items)
        if on and lib != "all" and not picked:
            # Nothing picked yet for this library: remember the choice but don't send an empty
            # list. Setting 'Gesture faces' next sends everything in one go.
            _LOGGER.info("Gesture library '%s' has no faces picked yet; waiting for Gesture faces", lib)
        else:
            packets = p.gesture_packets(on, p.GESTURE_LIBRARIES[lib], p.GESTURE_CIRCULATION[circ], picked)
            await self._async_send_acked(packets, "FACEOK")
        s.gesture_on, s.gesture_library, s.gesture_circulation = on, lib, circ
        if lib != "all":
            setattr(s, f"gesture_{lib}_items", picked)
        self._notify_listeners()

    async def _async_send_acked(self, packets: Sequence[bytes], ack: str) -> None:
        """Send packets one by one, waiting for the mask's `ack` notification between them.

        Long gesture lists are split across several packets; the app only sends the next one
        after the mask answers FACEOK, so we do the same. A single packet needs no wait.
        """
        if len(packets) == 1:
            await self.async_send(packets[0])
            return
        async with self._lock:
            client = await self._ensure_connected()
            self._drain()  # forget old notifications so we only see this exchange's answers
            for i, pkt in enumerate(packets):
                await self._write_cmd(client, pkt)
                if i < len(packets) - 1 and not await self._expect(ack, ACK_TIMEOUT):
                    raise HomeAssistantError(f"Mask did not answer {ack} (sent {i + 1} of {len(packets)} packets)")
            self._schedule_idle_disconnect()

    async def async_set_text_mode(self, mode_name: str, mode_value: int) -> None:
        """Steady, blink or scroll for uploaded text (MODE command)."""
        await self.async_send(p.cmd_text_mode(mode_value))
        self.state.text_mode = mode_name
        self._notify_listeners()

    async def async_set_text(self, text: str, color=(255, 255, 255), mode: int | None = None, speed: int | None = None) -> None:
        """Render `text` to a bitmap, upload it and show it."""
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

    async def async_upload_image(self, slot: int, payload: bytes, owner: str = "other") -> None:
        """Upload a picture into a DIY slot and record who owns it (see allocate_slots)."""
        if len(payload) != p.IMAGE_BYTES:
            raise HomeAssistantError(f"Image payload must be {p.IMAGE_BYTES} bytes")
        from .const import MAX_DIY_SLOT

        if not 1 <= slot <= MAX_DIY_SLOT:
            raise HomeAssistantError(f"DIY slot {slot} is out of range: the mask stores slots 1-{MAX_DIY_SLOT}")
        await self.async_upload(p.cmd_upload_start_image(len(payload), slot), payload)
        self.state.slot_owner[slot] = owner
        if slot == self.blank_slot:
            self._blank_uploaded = payload == bytes(len(payload))

    async def async_delete_diy(self, slots: Sequence[int]) -> None:
        """Delete DIY slots from the mask (DELE command)."""
        for i in range(0, len(slots), 10):
            await self.async_send(p.cmd_delete(list(slots[i : i + 10])))

    # ------------------------------------------------------------- DIY slot allocation
    # Lower = overwritten first. pack/blank (and your chosen DIY face) are never overwritten.
    OWNER_RANK = {None: 0, "other": 1, "photo": 1, "effect": 2, "clock": 3, "digits": 3}
    PROTECTED = ("pack", "blank")

    def slot_owner(self, slot: int) -> str | None:
        """Who uses a slot. Older uploads without a record are guessed from names/pack roles."""
        s = self.state
        if slot == self.blank_slot:
            return "blank"
        if any(slot in v for v in s.pack.values()):
            return "pack"
        if slot in s.slot_owner:
            # a slot dropped from the face pack (set_pack_role) is free to reuse
            return "other" if s.slot_owner[slot] == "pack" else s.slot_owner[slot]
        name = self.slot_names.get(slot, "")
        if name.startswith("clock"):
            return "clock"
        if name.startswith("matrix"):
            return "effect"
        return "other" if name else None

    def allocate_slots(self, count: int, owner: str) -> list[int]:
        """Pick `count` DIY slots for `owner`, overwriting the least likely to be missed first.

        Order: slots this owner already has, then empty slots, then other uploads (default
        faces, tests), then effects (Matrix, re-uploaded when you run it), then the clocks -
        and within each group the one played longest ago. Never touched: the face pack, the
        black 'off' frame, and a DIY face you chose yourself.
        """
        from .const import MAX_DIY_SLOT

        s = self.state
        keep = set(s.selected[1]) if s.selected and s.selected[0] == "diy" else set()
        free: list[tuple] = []
        for slot in range(1, MAX_DIY_SLOT + 1):
            who = self.slot_owner(slot)
            if who in self.PROTECTED or slot in keep:
                continue
            rank = -1 if who == owner else self.OWNER_RANK.get(who, 1)
            # the clock style you aren't using is cheaper to lose than the one you are
            if (who == "clock") == (s.clock_style == "Digit flip") and who in ("clock", "digits"):
                rank = 1.5
            free.append((rank, s.slot_played.get(slot, 0.0), slot))
        free.sort()
        if len(free) < count:
            raise HomeAssistantError(f"Not enough free DIY slots: need {count}, {len(free)} can be reused")
        return sorted(slot for _, _, slot in free[:count])

    def set_pack_role(self, role: str, slots: list[int]) -> None:
        """Change which DIY slots a face-pack role plays; dropped slots become reusable."""
        if slots:
            self.state.pack[role] = list(slots)
        else:
            self.state.pack.pop(role, None)
        self._notify_listeners()

    def slots_owned(self, slots: Sequence[int], owner: str) -> bool:
        """True if every slot in the list still holds `owner`'s upload."""
        return bool(slots) and all(self.slot_owner(x) == owner for x in slots)

    async def async_reset(self) -> None:
        """Back to a clean mask: delete every uploaded DIY image and switch extras off.

        Built-in images/animations live in the mask's firmware and can't be removed. Also clears
        what the integration remembers about uploads (face pack, slot names, clock buffers).
        """
        from .const import TEXT_EFFECTS

        await self.async_delete_diy(list(range(1, 256)))  # DELE takes 10 slots per packet
        await self.async_set_text_color(None, False)
        await self.async_set_bg_color(None, False)
        await self.async_set_text_effect("solid", TEXT_EFFECTS.get("solid"))
        await self.async_set_gesture(enable=False)
        s = self.state
        s.pack, s.pack_name = {}, None
        s.gesture_gallery_items, s.gesture_diy_items = [], []
        s.selected, s.clock_prev, s.diy = ("image", [1]), None, []
        s.clock_digits = None
        s.clock_digit_slots, s.clock_slots = [], []
        s.slot_owner.clear()
        s.slot_played.clear()
        self.slot_names.clear()
        self._blank_uploaded = False  # 'off' re-uploads its black frame when next needed
        if self.clock is not None:
            self.clock.forget_uploads()
        await self.async_show_image(1)

    async def async_check(self) -> int | None:
        """Ask the mask how many DIY images it holds (CHEC); the answer arrives as a notification."""
        async with self._lock:
            client = await self._ensure_connected()
            self._drain()
            await self._write_cmd(client, p.cmd_check())
            await self._expect("CHEC", ACK_TIMEOUT)
            self._schedule_idle_disconnect()
        self._notify_listeners()
        return self.state.diy_count

    async def async_raw(self, tag: str, args: bytes) -> None:
        """Send any command tag with raw argument bytes, for experimenting."""
        await self.async_send(p.build_command(tag, args))
