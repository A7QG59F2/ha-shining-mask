"""Text display mode select."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MaskConfigEntry
from .const import BAR_STYLES, TEXT_EFFECTS, TEXT_MODES
from .entity import MaskEntity


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    m = entry.runtime_data
    async_add_entities([MaskTextModeSelect(m), MaskTextEffectSelect(m), MaskGestureLibrarySelect(m), MaskGestureCirculationSelect(m), MaskBarsStyleSelect(m)])


class MaskTextModeSelect(MaskEntity, SelectEntity):
    """How uploaded text moves: steady, blink, scroll left or right."""
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


class MaskTextEffectSelect(MaskEntity, SelectEntity):
    """Text gradients (gradient_1-4) and background animations behind text (background_1-4)."""

    _attr_name = "Text effect"
    _attr_icon = "mdi:gradient-horizontal"
    _attr_options = list(TEXT_EFFECTS)

    def __init__(self, mask) -> None:
        super().__init__(mask, "text_effect")

    @property
    def current_option(self) -> str:
        return self.mask.state.text_effect

    async def async_select_option(self, option: str) -> None:
        await self.mask.async_set_text_effect(option, TEXT_EFFECTS[option])


class MaskGestureLibrarySelect(MaskEntity, SelectEntity):
    """App: gesture page > Library selection."""

    _attr_name = "Gesture library"
    _attr_icon = "mdi:image-multiple"
    _attr_options = ["all", "gallery", "diy"]

    def __init__(self, mask) -> None:
        super().__init__(mask, "gesture_library")

    @property
    def current_option(self) -> str:
        return self.mask.state.gesture_library

    async def async_select_option(self, option: str) -> None:
        await self.mask.async_set_gesture(library=option)


class MaskGestureCirculationSelect(MaskEntity, SelectEntity):
    """App: gesture page > Circulation mode."""

    _attr_name = "Gesture circulation"
    _attr_icon = "mdi:shuffle-variant"
    _attr_options = ["order", "random"]

    def __init__(self, mask) -> None:
        super().__init__(mask, "gesture_circulation")

    @property
    def current_option(self) -> str:
        return self.mask.state.gesture_circulation

    async def async_select_option(self, option: str) -> None:
        await self.mask.async_set_gesture(circulation=option)


class MaskBarsStyleSelect(MaskEntity, SelectEntity):
    """Look of the music bars (the mask's five rhythm styles)."""

    _attr_name = "Visualizer style"
    _attr_icon = "mdi:chart-bar"
    _attr_options = list(BAR_STYLES)

    def __init__(self, mask) -> None:
        super().__init__(mask, "bars_style_select")

    @property
    def current_option(self) -> str:
        by_value = {v: k for k, v in BAR_STYLES.items()}
        return by_value.get(self.mask.state.visualizer_style, "Rainbow")

    async def async_select_option(self, option: str) -> None:
        self.mask.set_visualizer_tuning(style=BAR_STYLES[option])
