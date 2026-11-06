"""Number entities: built-in image, built-in animation, speed."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MaskConfigEntry
from .const import CONF_MAX_ANIMATION, CONF_MAX_IMAGE, DEFAULT_MAX_ANIMATION, DEFAULT_MAX_IMAGE
from .entity import MaskEntity


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    mask = entry.runtime_data
    async_add_entities(
        [
            MaskImageNumber(mask, entry.options.get(CONF_MAX_IMAGE, DEFAULT_MAX_IMAGE)),
            MaskAnimationNumber(mask, entry.options.get(CONF_MAX_ANIMATION, DEFAULT_MAX_ANIMATION)),
            MaskSpeedNumber(mask),
            MaskBarsStyleNumber(mask),
            MaskBarsDelayNumber(mask),
            MaskBarsTuneNumber(mask, "bars_sensitivity", "Music bars sensitivity", "mdi:tune-vertical", 10, 300, 5, "%"),
            MaskBarsTuneNumber(mask, "bars_contrast", "Music bars contrast", "mdi:contrast-box", 1.0, 3.0, 0.1, None),
            MaskBarsTuneNumber(mask, "bars_bass", "Music bars bass", "mdi:speaker", 0, 200, 5, "%"),
            MaskBarsTuneNumber(mask, "bars_mid", "Music bars mid", "mdi:speaker", 0, 200, 5, "%"),
            MaskBarsTuneNumber(mask, "bars_treble", "Music bars treble", "mdi:speaker", 0, 200, 5, "%"),
        ]
    )


class MaskImageNumber(MaskEntity, NumberEntity):
    _attr_translation_key = "image"
    _attr_name = "Image"
    _attr_icon = "mdi:emoticon-outline"
    _attr_native_min_value = 1
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, mask, maximum: int) -> None:
        super().__init__(mask, "image")
        self._attr_native_max_value = maximum

    @property
    def native_value(self):
        return self.mask.state.image

    async def async_set_native_value(self, value: float) -> None:
        await self.mask.async_show_image(int(value))


class MaskAnimationNumber(MaskEntity, NumberEntity):
    _attr_translation_key = "animation"
    _attr_name = "Animation"
    _attr_icon = "mdi:animation-play"
    _attr_native_min_value = 1
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, mask, maximum: int) -> None:
        super().__init__(mask, "animation")
        self._attr_native_max_value = maximum

    @property
    def native_value(self):
        return self.mask.state.animation

    async def async_set_native_value(self, value: float) -> None:
        await self.mask.async_show_animation(int(value))


class MaskSpeedNumber(MaskEntity, NumberEntity):
    _attr_translation_key = "speed"
    _attr_name = "Speed"
    _attr_icon = "mdi:speedometer"
    _attr_native_min_value = 0
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, mask) -> None:
        super().__init__(mask, "speed")

    @property
    def native_value(self):
        return self.mask.state.speed

    async def async_set_native_value(self, value: float) -> None:
        await self.mask.async_set_speed(int(value))


class MaskBarsStyleNumber(MaskEntity, NumberEntity):
    """Rhythm effect used for the music bars (the app's rhythm styles)."""

    _attr_name = "Music bars style"
    _attr_icon = "mdi:chart-bar"
    _attr_native_min_value = 0
    _attr_native_max_value = 4  # five styles (0-4); 5+ freezes the mask
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, mask) -> None:
        super().__init__(mask, "bars_style")

    @property
    def native_value(self):
        return self.mask.state.visualizer_style

    async def async_set_native_value(self, value: float) -> None:
        self.mask.set_visualizer_tuning(style=int(value))


class MaskBarsDelayNumber(MaskEntity, NumberEntity):
    """Shift the bars later (+) or earlier (-) to line up with what you hear."""

    _attr_name = "Music bars delay"
    _attr_icon = "mdi:timer-sync-outline"
    _attr_native_min_value = -1000
    _attr_native_max_value = 2000
    _attr_native_step = 10
    _attr_native_unit_of_measurement = "ms"
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, mask) -> None:
        super().__init__(mask, "bars_delay")

    @property
    def native_value(self):
        return self.mask.state.visualizer_delay_ms

    async def async_set_native_value(self, value: float) -> None:
        self.mask.set_visualizer_tuning(delay_ms=int(value))


class MaskBarsTuneNumber(MaskEntity, NumberEntity):
    """Music bars EQ / response setting (applies live)."""

    _attr_mode = NumberMode.SLIDER

    def __init__(self, mask, key, name, icon, lo, hi, step, unit) -> None:
        super().__init__(mask, key)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self):
        return getattr(self.mask.state, self._key)

    async def async_set_native_value(self, value: float) -> None:
        v = round(float(value), 2) if self._key == "bars_contrast" else int(value)
        self.mask.set_visualizer_tuning(**{self._key: v})
