"""Text display mode select."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MaskConfigEntry
from .const import TEXT_MODES
from .entity import MaskEntity


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([MaskTextModeSelect(entry.runtime_data)])


class MaskTextModeSelect(MaskEntity, SelectEntity):
    _attr_translation_key = "text_mode"
    _attr_name = "Text mode"
    _attr_icon = "mdi:format-text-variant"
    _attr_options = list(TEXT_MODES)

    def __init__(self, mask) -> None:
        super().__init__(mask, "text_mode")

    @property
    def current_option(self) -> str:
        return self.mask.state.text_mode

    async def async_select_option(self, option: str) -> None:
        await self.mask.async_set_text_mode(option, TEXT_MODES[option])
