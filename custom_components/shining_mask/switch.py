"""Gesture face switch (app: Settings > gesture page)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MaskConfigEntry
from .entity import MaskEntity


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    mask = entry.runtime_data
    async_add_entities([MaskGestureSwitch(mask), MaskVisualizerSwitch(mask), MaskClockSwitch(mask)])


class MaskGestureSwitch(MaskEntity, SwitchEntity):
    """Gesture face switch on/off (app: gesture page). Faces/library are separate entities."""
    _attr_name = "Gesture"
    _attr_icon = "mdi:hand-wave"
    _attr_assumed_state = True

    def __init__(self, mask) -> None:
        super().__init__(mask, "gesture_switch")

    @property
    def is_on(self) -> bool:
        return self.mask.state.gesture_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.mask.state
        return {"library": s.gesture_library, "circulation": s.gesture_circulation, "faces": self.mask.gesture_items()}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.mask.async_set_gesture(enable=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.mask.async_set_gesture(enable=False)


class MaskVisualizerSwitch(MaskEntity, SwitchEntity):
    """Music bars from Music Assistant (Sendspin visualizer)."""

    _attr_name = "Visualizer"
    _attr_icon = "mdi:equalizer"

    def __init__(self, mask) -> None:
        super().__init__(mask, "music_visualizer")

    @property
    def is_on(self) -> bool:
        return self.mask.state.visualizer_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        v = self.mask.visualizer
        return {
            "music_assistant_connected": bool(v and v.connected),
            "music_playing": bool(v and v.playing),
            "port": self.mask.visualizer_port,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.mask.async_set_visualizer(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.mask.async_set_visualizer(False)


class MaskClockSwitch(MaskEntity, SwitchEntity):
    """Clock screen as the chosen face: sky with sun/moon and weather, 24-hour time, temperature.

    On: the clock becomes the face the mask goes back to (assistant faces and music bars still
    take over and give it back). Off: back to the face chosen before the clock.
    """

    _attr_name = "Clock"
    _attr_icon = "mdi:clock-digital"

    def __init__(self, mask) -> None:
        super().__init__(mask, "clock")

    @property
    def is_on(self) -> bool:
        sel = self.mask.state.selected
        return bool(sel) and sel[0] == "clock"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.mask.async_set_clock(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.mask.async_set_clock(False)
