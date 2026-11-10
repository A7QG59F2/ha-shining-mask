"""Shining Mask (LED face mask) integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_DISCONNECT_AFTER,
    CONF_BLANK_SLOT,
    CONF_MAX_BRIGHTNESS,
    CONF_PIXEL_ORDER,
    CONF_VISUALIZER_PORT,
    DEFAULT_BLANK_SLOT,
    DEFAULT_VISUALIZER_PORT,
    DEFAULT_DISCONNECT_AFTER,
    DEFAULT_MAX_BRIGHTNESS,
    DEFAULT_PIXEL_ORDER,
)
from .device import ShiningMask
from .previews import async_register_static

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.IMAGE, Platform.LIGHT, Platform.NUMBER, Platform.SELECT, Platform.SWITCH, Platform.TEXT]

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
    await mask.async_load()
    mask.visualizer_port = entry.options.get(CONF_VISUALIZER_PORT, DEFAULT_VISUALIZER_PORT)
    if dev := bluetooth.async_ble_device_from_address(hass, address, connectable=True):
        mask.set_ble_device(dev)

    @callback
    def _seen(service_info: bluetooth.BluetoothServiceInfoBleak, _change) -> None:
        """Bluetooth callback: keep the mask's latest BLEDevice so reconnects use the best adapter/proxy."""
        mask.set_ble_device(service_info.device)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass, _seen, bluetooth.BluetoothCallbackMatcher(address=address, connectable=True),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )
    # clock screen: ticks every minute but only draws while it is the face on screen
    from .clock import MaskClock

    mask.clock = MaskClock(hass, mask)
    mask.clock.start()
    entry.async_on_unload(mask.clock.stop)
    # voice-assistant faces: follows the satellite chosen on the mask's "Assistant satellite"
    from .assist import MaskAssistant

    mask.assistant = MaskAssistant(hass, mask)
    mask.assistant.start()
    entry.async_on_unload(mask.assistant.stop)
    entry.runtime_data = mask
    await async_register_static(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    if mask.state.visualizer_on:
        # in the background: installing its library can take a while (or fail offline)
        async def _start_viz() -> None:
            try:
                await mask.async_set_visualizer(True)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Music visualizer could not start: %s", err)

        entry.async_create_background_task(hass, _start_viz(), "shining_mask visualizer start")
    return True


async def _reload(hass: HomeAssistant, entry: MaskConfigEntry) -> None:
    """Reload the entry when its options change (new proxy timeout, limits, port...)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MaskConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        if entry.runtime_data.visualizer is not None:
            viz, entry.runtime_data.visualizer = entry.runtime_data.visualizer, None
            await viz.async_stop()
        await entry.runtime_data.async_disconnect()
    return ok
