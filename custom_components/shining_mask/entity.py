"""Base entity for Shining Mask."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .device import ShiningMask


class MaskEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, mask: ShiningMask, key: str) -> None:
        self.mask = mask
        self._attr_unique_id = f"{mask.address}_{key}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, mask.address)},
            name=mask.name,
            manufacturer="Shining Mask",
            model="LED face mask",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.mask.async_add_listener(self.async_write_ha_state))
