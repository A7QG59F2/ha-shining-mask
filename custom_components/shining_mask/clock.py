"""The clock screen: keeps a live clock (sky, weather, 24-hour time, temperature) on the mask.

How it works
------------
The mask can't draw anything itself, so every minute we draw the next minute's picture
(two frames: colon on / colon off, with the sun's rays, rain, snow... moved a step) and upload
it into DIY slots. Two pairs of slots are used in turn (double buffering): while one pair is
on screen, the next minute goes into the other pair, then a single PLAY switches over exactly
when the minute changes. The screen never shows a half-uploaded picture.

When it runs
------------
Only while the clock is the chosen face and actually on screen: not while the mask is off,
not while music bars or an assistant face are showing. When the screen comes back to the
chosen face (restore_selected), the last uploaded minute is shown at once and refreshed.

Sky data
--------
Sun: today's sunrise/sunset from Home Assistant's location, elevation from `sun.sun`.
Moon: phase from astral; its path is estimated (it rises ~phase x 24 h after the sun), which
is close enough to show where it roughly is in the sky.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from . import protocol as p

if TYPE_CHECKING:
    from .device import ShiningMask

_LOGGER = logging.getLogger(__name__)

FRAMES = 2  # pictures per minute (colon on / off)
PREPARE_AT_SECOND = 35  # start drawing + uploading the next minute at hh:mm:35
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


class MaskClock:
    """Runs the clock screen for one mask."""

    def __init__(self, hass: HomeAssistant, mask: ShiningMask, first_slot: int) -> None:
        self.hass = hass
        self.mask = mask
        # two buffers of FRAMES slots each, e.g. 46-47 and 48-49
        self.buffers = [
            list(range(first_slot, first_slot + FRAMES)),
            list(range(first_slot + FRAMES, first_slot + 2 * FRAMES)),
        ]
        self._ready: int | None = None  # buffer holding the newest uploaded minute
        self._ready_minute: datetime | None = None  # which minute that buffer shows
        self._on_screen: int | None = None  # buffer currently playing
        self._unsub_tick: CALLBACK_TYPE | None = None
        self._unsub_flip: CALLBACK_TYPE | None = None
        self._busy = False  # an upload is running
        for buf in self.buffers:  # label the slots on the dashboard
            for slot in buf:
                mask.slot_names[slot] = "clock"

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        """Begin the once-a-minute preparation tick."""
        if self._unsub_tick is None:
            self._unsub_tick = async_track_time_change(self.hass, self._tick, second=PREPARE_AT_SECOND)

    def stop(self) -> None:
        """Stop ticking (integration unloading)."""
        for unsub in (self._unsub_tick, self._unsub_flip):
            if unsub:
                unsub()
        self._unsub_tick = self._unsub_flip = None

    @property
    def showing(self) -> bool:
        """The clock is the chosen face and nothing outranks it on screen right now."""
        m = self.mask
        chosen = bool(m.state.selected) and m.state.selected[0] == "clock"
        return chosen and m.state.is_on and not m.music_hold and not m.bars_on_top

    # ------------------------------------------------------------- showing
    async def async_show(self) -> None:
        """Put the clock on screen now (chosen face restored, or clock just switched on)."""
        if self._unsub_flip:  # a flip planned before we were interrupted would now be stale
            self._unsub_flip()
            self._unsub_flip = None
        now = dt_util.now()
        if self._ready is not None and self._ready_minute == now.replace(second=0, microsecond=0):
            await self._play(self._ready)  # already have this minute uploaded
            return
        if self._ready is not None:
            await self._play(self._ready)  # show the stale minute at once...
        await self._prepare(now)  # ...then draw the current minute and switch to it
        if self._ready is not None:
            await self._play(self._ready)

    def forget_uploads(self) -> None:
        """The DIY slots were wiped (reset): nothing uploaded is valid any more."""
        self._ready = self._ready_minute = self._on_screen = None
        for buf in self.buffers:
            for slot in buf:
                self.mask.slot_names[slot] = "clock"

    async def _play(self, buf: int) -> None:
        """Play one buffer's frames (temporary: the chosen face stays 'clock')."""
        speed = self.mask.state.clock_speed
        await self.mask.async_play_diy(self.buffers[buf], speed, temporary=True)
        self._on_screen = buf

    # ------------------------------------------------------------- minute tick
    @callback
    def _tick(self, now: datetime) -> None:
        """hh:mm:35 - draw the coming minute into the free buffer, then flip at hh:mm+1:00."""
        if not self.showing or self._busy:
            return
        self.hass.async_create_task(self._prepare_and_flip(now))

    async def _prepare_and_flip(self, now: datetime) -> None:
        next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        await self._prepare(next_minute)
        if self._ready is None or self._ready_minute != next_minute:
            return
        delay = max(0.0, (next_minute - dt_util.now()).total_seconds())

        @callback
        def _flip(_now) -> None:
            self._unsub_flip = None
            if self.showing and self._ready is not None:
                self.hass.async_create_task(self._play(self._ready))

        self._unsub_flip = async_call_later(self.hass, delay, _flip)

    async def _prepare(self, when: datetime) -> None:
        """Draw the clock for minute `when` and upload it into the buffer not on screen."""
        if self._busy:
            return
        self._busy = True
        try:
            buf = 1 if self._on_screen == 0 else 0
            frames = await self.hass.async_add_executor_job(self._render, when, self._sky(when))
            for slot, img in zip(self.buffers[buf], frames):
                # an assistant face or music took over: stop uploading, it can wait
                if not self.showing and self._on_screen is not None:
                    return
                payload = p.encode_image_pixels(list(img.getdata()), self.mask.pixel_order)
                await self.mask.async_upload_image(slot, payload)
            self._ready, self._ready_minute = buf, when.replace(second=0, microsecond=0)
            await self.hass.async_add_executor_job(self._save_preview, self.buffers[buf][0], frames[0])
            self.mask.preview_changed()
        except Exception as err:  # noqa: BLE001 - a missed minute must never break the mask
            _LOGGER.warning("Clock update failed: %s", err)
        finally:
            self._busy = False

    # ------------------------------------------------------------- data
    def _sky(self, when: datetime) -> dict:
        """Everything the picture needs from Home Assistant, read on the event loop."""
        hass = self.hass
        sun = hass.states.get("sun.sun")
        elev = float(sun.attributes.get("elevation", 0)) if sun else 0.0
        rise = get_astral_event_date(hass, "sunrise", when.date())
        sset = get_astral_event_date(hass, "sunset", when.date())
        sun_frac = _frac(when, rise, sset)

        # moon: phase 0..28 days from astral; path estimated from the sun's, shifted by phase
        try:
            from astral import moon

            age = moon.phase(when.date())
        except Exception:  # noqa: BLE001
            age = 0.0
        phase = (age / 28.0) % 1.0
        moon_frac = None
        if rise and sset:
            shift = timedelta(hours=24 * phase)
            for back in (0, 1):  # tonight's moon may have risen yesterday
                mrise = rise + shift - timedelta(days=back)
                mset = sset + shift - timedelta(days=back)
                if (f := _frac(when, mrise, mset)) is not None:
                    moon_frac = f
                    break
        if 0.02 < phase < 0.98 and moon_frac is not None and sun_frac is not None and elev > 10:
            moon_frac = None  # don't draw a pale moon next to a high sun

        weather = hass.states.get(self.mask.state.clock_weather or "")
        cond, temp, unit = None, None, "F"
        if weather:
            cond = weather.state
            temp = weather.attributes.get("temperature")
            unit = "C" if "C" in str(weather.attributes.get("temperature_unit", "°F")) else "F"
        return {"sun_frac": sun_frac, "elev": elev, "moon_frac": moon_frac, "moon_phase": phase,
                "cond": cond, "temp": float(temp) if temp is not None else None, "unit": unit}

    @staticmethod
    def _render(when: datetime, sky: dict) -> list:
        """Draw FRAMES pictures for minute `when` (runs in the executor)."""
        from .clockface import render

        date = f"{DAYS[when.weekday()]} {when.day}"
        return [render(when.hour, when.minute, frame=f, h24=True, date=date, **sky) for f in range(FRAMES)]

    def _save_preview(self, slot: int, img) -> None:
        """Keep the dashboard's 'Face now showing' picture current."""
        from .previews import save_diy_preview

        save_diy_preview(self.hass, slot, img)


def _frac(now: datetime, start: datetime | None, end: datetime | None) -> float | None:
    """How far `now` is between start and end (0..1), or None outside that span."""
    if not start or not end or end <= start:
        return None
    f = (now - start).total_seconds() / (end - start).total_seconds()
    return f if 0.0 <= f <= 1.0 else None
