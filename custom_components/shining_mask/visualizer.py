"""Music Assistant -> mask music bars, via the Sendspin visualizer@v1 role.

The mask advertises itself on the network as a Sendspin client with only the visualizer role.
Music Assistant connects to it; once it is grouped with a playing player, MA streams
time-stamped spectrum/beat frames. Each frame is converted to the mask's 12 bars (0-15) and
sent on the rhythm channel at the moment that audio is actually heard.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiohttp import web

from homeassistant.components import zeroconf
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

if TYPE_CHECKING:
    from .device import ShiningMask

_LOGGER = logging.getLogger(__name__)

N_BARS = 12
SEND_INTERVAL = 1 / 15  # BLE-friendly frame rate
IDLE_RESTORE_S = 2.0  # no frames for this long -> give the face back


class MaskVisualizer:
    def __init__(self, hass: HomeAssistant, mask: ShiningMask, port: int, style: int = 0, delay_ms: int = 0) -> None:
        # EQ / response (updated live from the mask's settings)
        self.sensitivity = 1.0  # overall gain
        self.contrast = 1.6  # >1 pushes quiet bands down, keeps peaks
        self.eq = (1.0, 1.0, 1.0)  # bass (bars 1-4), mid (5-8), treble (9-12)
        self.hass = hass
        self.mask = mask
        self.port = port
        self.style = style
        self.delay_ms = delay_ms
        self._store: Store = Store(hass, 1, f"shining_mask.sendspin.{mask.address.replace(':', '').lower()}")
        self._client = None
        self._runner: web.AppRunner | None = None
        self._mdns = None
        self._latest: list[int] | None = None
        self._last_frame_at = 0.0
        self._sender: asyncio.Task | None = None
        self._active = False  # mask currently showing bars
        self._peak = 2000.0  # auto-gain reference
        self._beat_boost = 0.0
        self.connected = False
        self.playing = False

    # ------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        from aiosendspin.client.client import SendspinClient
        from aiosendspin.models.types import Roles
        from aiosendspin.models.visualizer import (
            ClientHelloVisualizerSpectrum,
            ClientHelloVisualizerSupport,
            VisualizerStatePayload,
        )
        from aiosendspin.noise.keys import Identity
        from aiosendspin.noise.trust_store import FileClientPairingStore

        data = await self._store.async_load() or {}
        if "identity" in data:
            identity = Identity.from_private_bytes(bytes.fromhex(data["identity"]))
        else:
            identity = Identity.generate()
            await self._store.async_save({"identity": identity.private_bytes.hex()})

        pairing = FileClientPairingStore(
            self.hass.config.path(".storage", f"shining_mask.sendspin_pairing.{self.mask.address.replace(':', '').lower()}.json")
        )
        self._client = SendspinClient(
            identity,
            f"{self.mask.name} (mask)",
            [Roles.VISUALIZER],
            pairing_store=pairing,
            visualizer_support=ClientHelloVisualizerSupport(buffer_capacity=1_000_000),
            visualizer_state=VisualizerStatePayload(
                types=["spectrum", "loudness", "beat"],
                rate_max=30,
                spectrum=ClientHelloVisualizerSpectrum(n_disp_bins=N_BARS, scale="log", f_min=40, f_max=12000),
            ),
        )
        # let Music Assistant connect without a pairing ceremony (LAN only)
        try:
            await self._client.set_unpaired_access(enabled=True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("set_unpaired_access failed: %s", err)
        self._client.add_visualizer_listener(self._on_frames)
        self._client.add_stream_start_listener(lambda *_: self._set_playing(True))
        self._client.add_stream_end_listener(lambda *_: self._set_playing(False))

        app = web.Application()
        app.router.add_get("/sendspin", self._handle_ws)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, "0.0.0.0", self.port).start()
        await self._advertise(identity.peer_id)
        self._sender = self.hass.async_create_background_task(self._send_loop(), "shining_mask_visualizer")
        _LOGGER.info("Mask music visualizer listening on port %s", self.port)

    async def async_stop(self) -> None:
        if self._sender:
            self._sender.cancel()
            self._sender = None
        if self._mdns:
            try:
                aiozc = await zeroconf.async_get_async_instance(self.hass)
                await aiozc.async_unregister_service(self._mdns)
            except Exception:  # noqa: BLE001
                pass
            self._mdns = None
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        if self._active:
            await self._end_bars()

    async def _advertise(self, peer_id: str) -> None:
        from zeroconf.asyncio import AsyncServiceInfo

        from homeassistant.components.network import async_get_source_ip

        ip = await async_get_source_ip(self.hass)
        name = f"shiningmask-{self.mask.address.replace(':', '').lower()}"
        self._mdns = AsyncServiceInfo(
            "_sendspin._tcp.local.",
            f"{name}._sendspin._tcp.local.",
            server=f"{name}.local.",
            parsed_addresses=[ip],
            port=self.port,
            properties={"path": "/sendspin", "name": f"{self.mask.name} (mask)"},
        )
        aiozc = await zeroconf.async_get_async_instance(self.hass)
        await aiozc.async_register_service(self._mdns)

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self.connected = True
        self.mask.preview_changed()
        try:
            await self._client.attach_websocket(ws)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Sendspin connection ended: %s", err)
        finally:
            self.connected = False
            self._set_playing(False)
        return ws

    # ------------------------------------------------------------ frames
    def _set_playing(self, playing: bool) -> None:
        self.playing = playing
        self.hass.loop.call_soon_threadsafe(self.mask.preview_changed)

    def _on_frames(self, frames) -> None:
        loop = self.hass.loop
        client = self._client
        for frame in frames:
            # when this audio is actually heard, in seconds from now
            at = (client.compute_play_time(frame.timestamp_us) - client.now_us()) / 1e6 + self.delay_ms / 1000
            if frame.spectrum is not None:
                bars = list(frame.spectrum)
                loop.call_soon_threadsafe(loop.call_later, max(0.0, at), self._show, bars)
            elif frame.is_downbeat is not None:  # beat event
                strength = 1.0 if frame.is_downbeat else 0.6
                loop.call_soon_threadsafe(loop.call_later, max(0.0, at), self._beat, strength)

    def _beat(self, strength: float) -> None:
        self._beat_boost = max(self._beat_boost, strength)

    def _show(self, raw: list[int]) -> None:
        # auto-gain reference: the loudest bin of the last several seconds (slow decay),
        # so normal passages sit well below full height and only peaks reach the top
        top = max(raw) if raw else 0
        self._peak = max(top, self._peak * 0.997, 3000.0)
        boost = 1.0 + 0.25 * self._beat_boost
        self._beat_boost *= 0.6
        gate = 0.08
        bars = []
        for i, v in enumerate(raw[:N_BARS]):
            x = v / self._peak
            x = max(0.0, x - gate) / (1 - gate)  # noise gate
            x = x ** self.contrast  # contrast curve
            x *= self.sensitivity * self.eq[min(2, i * 3 // N_BARS)] * boost
            bars.append(max(0, min(15, int(round(15 * x)))))
        bars += [0] * (N_BARS - len(bars))
        self._latest = bars
        self._last_frame_at = self.hass.loop.time()

    def pause_for_assist(self) -> None:
        """The assistant's face is taking over: stop sending bars, don't restore any face."""
        self._latest = None
        self._active = False

    async def _send_loop(self) -> None:
        while True:
            await asyncio.sleep(SEND_INTERVAL)
            now = self.hass.loop.time()
            if self.mask.holding_music:
                self._latest = None  # drop frames while the assistant face is up
                continue
            if self._latest is not None and now - self._last_frame_at < IDLE_RESTORE_S:
                bars, self._latest = self._latest, None
                try:
                    await self.mask.async_rhythm(self.style, [bars])
                    self._active = True
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Visualizer frame not sent: %s", err)
            elif self._active and now - self._last_frame_at >= IDLE_RESTORE_S:
                await self._end_bars()

    async def _end_bars(self) -> None:
        self._active = False
        if self.mask.holding_music:
            return  # never cover the assistant face
        try:
            await self.mask.async_exit_rhythm()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not leave rhythm mode: %s", err)
