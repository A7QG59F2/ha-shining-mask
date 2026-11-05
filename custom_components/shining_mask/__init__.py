"""Shining Mask (LED face mask) integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_DISCONNECT_AFTER,
    CONF_BLANK_SLOT,
    CONF_MAX_BRIGHTNESS,
    CONF_PIXEL_ORDER,
    DEFAULT_BLANK_SLOT,
    DEFAULT_DISCONNECT_AFTER,
    DEFAULT_MAX_BRIGHTNESS,
    DEFAULT_PIXEL_ORDER,
)
from .device import ShiningMask

PLATFORMS = [Platform.LIGHT, Platform.NUMBER, Platform.SELECT, Platform.TEXT]

type MaskConfigEntry = ConfigEntry[ShiningMask]


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry) -> bool:
    address: str = entry.data[CONF_ADDRESS]
    mask = ShiningMask(
        hass,
        address,
        entry.title,
        entry.options.get(CONF_DISCONNECT_AFTER, DEFAULT_DISCONNECT_AFTER),
        entry.options.get(CONF_PIXEL_ORDER, DEFAULT_PIXEL_ORDER),
        entry.options.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS),
        entry.options.get(CONF_BLANK_SLOT, DEFAULT_BLANK_SLOT),
    )
    if dev := bluetooth.async_ble_device_from_address(hass, address, connectable=True):
        mask.set_ble_device(dev)

    @callback
    def _seen(service_info: bluetooth.BluetoothServiceInfoBleak, _change) -> None:
        mask.set_ble_device(service_info.device)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass, _seen, bluetooth.BluetoothCallbackMatcher(address=address, connectable=True),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )
    entry.runtime_data = mask
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: MaskConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MaskConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_disconnect()
    return ok
