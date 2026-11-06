"""Text entities: the scrolling text, and the gesture face list."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MaskConfigEntry
from . import protocol as p
from .const import TEXT_MODES
from .entity import MaskEntity


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([MaskText(entry.runtime_data), MaskGestureFacesText(entry.runtime_data)])


class MaskText(MaskEntity, TextEntity):
    """Type text here to upload it and show it on the mask."""

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


class MaskGestureFacesText(MaskEntity, TextEntity):
    """Which faces the gesture face switch cycles through (app: library > pick images).

    Type numbers like "1, 4, 7-9". They mean built-in image numbers when Gesture library is
    'gallery', and DIY slot numbers when it is 'diy'. Each library keeps its own list, like the
    app, so switching library shows (and uses) that library's list. Unused for 'all'.
    """

    _attr_name = "Gesture faces"
    _attr_icon = "mdi:format-list-numbered"
    _attr_native_max = 255
    _attr_pattern = r"^[0-9,\- ]*$"  # digits, commas, dashes and spaces only

    def __init__(self, mask) -> None:
        super().__init__(mask, "gesture_faces")

    @property
    def available(self) -> bool:
        # 'all' plays everything, so there is nothing to pick
        return self.mask.state.gesture_library != "all"

    @property
    def native_value(self) -> str:
        return p.format_number_list(self.mask.gesture_items())

    async def async_set_value(self, value: str) -> None:
        try:
            numbers = p.parse_number_list(value)
        except ValueError as err:
            raise ServiceValidationError(f"Use face numbers like '1, 4, 7-9' ({err})") from err
        await self.mask.async_set_gesture(items=numbers)
