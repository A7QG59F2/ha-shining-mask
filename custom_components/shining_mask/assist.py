"""Voice-assistant face, built in (replaces the old voice-face blueprint and its automation).

Watches one assist_satellite entity and shows a face for each of its states:

    satellite state   face setting      music bars
    ---------------   ---------------   ---------------------------------
    listening         Listening face    held off (assistant face wins)
    processing        Thinking face     held off
    responding        Talking face      held off (played at Talking speed)
    idle              Idle face         back on at once if music is playing
    unavailable       Error face        back on; after a delay: restore or off

A face setting is one of the choices from `face_options()`:
    "Face pack"     the matching role of the installed face pack (listening/thinking/...)
    "Chosen face"   the face you picked yourself (idle only makes sense here)
    "None"          do nothing for this state
    "Image N" / "Animation N" / "DIY N ..."   a specific built-in picture or DIY slot

Idle return: if the idle face isn't "Chosen face", go back to the chosen face after N seconds.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

if TYPE_CHECKING:
    from .device import ShiningMask

_LOGGER = logging.getLogger(__name__)

# satellite state -> (face setting key, face-pack role)
STATES = {
    "listening": ("listening", "listening"),
    "processing": ("thinking", "thinking"),
    "responding": ("talking", "talking"),
    "idle": ("idle", "idle"),
    "unavailable": ("error", "error"),
}
BUSY = ("listening", "processing", "responding")
FACE_KEYS = ("listening", "thinking", "talking", "idle", "error")
DEFAULT_FACES = {"listening": "Face pack", "thinking": "Face pack", "talking": "Face pack",
                 "idle": "Chosen face", "error": "Face pack"}
UNAVAILABLE_ACTIONS = ["Restore chosen face", "Turn off", "Keep error face"]


def face_options(mask: ShiningMask, max_image: int, max_animation: int) -> list[str]:
    """Every choice a face setting can take, for the select entities."""
    opts = ["Face pack", "Chosen face", "None"]
    opts += [f"Image {i}" for i in range(1, max_image + 1)]
    opts += [f"Animation {i}" for i in range(1, max_animation + 1)]
    from .const import MAX_DIY_SLOT

    for slot in range(1, MAX_DIY_SLOT + 1):
        name = mask.slot_names.get(slot)
        opts.append(f"DIY {slot} ({name})" if name else f"DIY {slot}")
    return opts


class MaskAssistant:
    """Follows the chosen satellite and drives the mask's assistant faces."""

    def __init__(self, hass: HomeAssistant, mask: ShiningMask) -> None:
        self.hass = hass
        self.mask = mask
        self._unsub_state: CALLBACK_TYPE | None = None
        self._unsub_timer: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        """(Re)subscribe to the configured satellite."""
        self.stop()
        sat = self.mask.state.assist_satellite
        if sat:
            self._unsub_state = async_track_state_change_event(self.hass, [sat], self._changed)

    def stop(self) -> None:
        """Unsubscribe and cancel any pending idle/unavailable timer."""
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        self._cancel_timer()

    def _cancel_timer(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    # ------------------------------------------------------------- reacting
    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        """Satellite changed state: show the matching face (ignores attribute-only changes)."""
        new, old = event.data["new_state"], event.data["old_state"]
        if new is not None and old is not None and new.state == old.state:
            return
        raw = new.state if new else "unavailable"
        key = raw if raw in STATES else ("unavailable" if raw in ("unavailable", "unknown") else "idle")
        self.hass.async_create_task(self._apply(key))

    async def _apply(self, key: str) -> None:
        """Show the face for satellite state `key` and set up any follow-up timer."""
        self._cancel_timer()  # a newer state always replaces older plans
        s = self.mask.state
        face_key, role = STATES[key]
        choice = s.assist_faces.get(face_key, DEFAULT_FACES[face_key])
        busy = key in BUSY
        try:
            # the assistant face always beats the music bars while the assistant is busy
            await self.mask.async_set_music_hold(busy)
            speed = s.assist_talk_speed if key == "responding" else None
            await self._show(choice, role, speed)
        except HomeAssistantError as err:
            _LOGGER.warning("Assistant face for '%s' failed: %s", key, err)
            return

        if key == "idle" and choice not in ("Chosen face", "None") and s.assist_idle_return > 0:
            self._later(s.assist_idle_return, self.mask.async_restore_selected)
        elif key == "unavailable" and s.assist_unavailable_after > 0:
            action = s.assist_unavailable_action
            if action == "Turn off":
                self._later(s.assist_unavailable_after, self.mask.async_turn_off)
            elif action == "Restore chosen face":
                self._later(s.assist_unavailable_after, self.mask.async_restore_selected)

    async def _show(self, choice: str, role: str, speed: int | None) -> None:
        """Show one face setting. Temporary: never changes the chosen face."""
        m = self.mask
        if choice == "None":
            return
        if choice == "Chosen face":
            await m.async_restore_selected()
        elif choice == "Face pack":
            await m.async_play_role(role, speed)
        elif choice.startswith("Image "):
            await m.async_show_image(int(choice.split()[1]), temporary=True)
        elif choice.startswith("Animation "):
            await m.async_show_animation(int(choice.split()[1]), temporary=True)
        elif choice.startswith("DIY "):
            await m.async_play_diy([int(choice.split()[1])], speed, temporary=True)

    def _later(self, seconds: float, job) -> None:
        """Run `job()` after `seconds`, unless the satellite changes state first."""

        @callback
        def _fire(_now) -> None:
            self._unsub_timer = None
            self.hass.async_create_task(job())

        self._unsub_timer = async_call_later(self.hass, seconds, _fire)
