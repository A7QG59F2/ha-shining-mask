"""Scrolling text entity."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MaskConfigEntry
from .const import TEXT_MODES
from .entity import MaskEntity


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([MaskText(entry.runtime_data)])


class MaskText(MaskEntity, TextEntity):
    _attr_translation_key = "text"
    _attr_name = "Text"
    _attr_icon = "mdi:message-text"
    _attr_native_max = 80

    def __init__(self, mask) -> None:
        super().__init__(mask, "text")

    @property
    def native_value(self) -> str:
        return self.mask.state.text

    async def async_set_value(self, value: str) -> None:
        await self.mask.async_set_text(value, mode=TEXT_MODES.get(self.mask.state.text_mode))
