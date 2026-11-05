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
