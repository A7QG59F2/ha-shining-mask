"""Gesture face switch (app: Settings > gesture page)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MaskConfigEntry
from .entity import MaskEntity


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([MaskGestureSwitch(entry.runtime_data)])


class MaskGestureSwitch(MaskEntity, SwitchEntity):
    _attr_name = "Gesture face switch"
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
        return {"library": s.gesture_library, "circulation": s.gesture_circulation, "items": s.gesture_items}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.mask.async_set_gesture(enable=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.mask.async_set_gesture(enable=False)
