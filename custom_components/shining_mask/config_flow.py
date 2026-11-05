"""Config flow for Shining Mask."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak, async_discovered_service_info
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import (
    CONF_DISCONNECT_AFTER,
    CONF_MAX_ANIMATION,
    CONF_MAX_IMAGE,
    CONF_PIXEL_ORDER,
    DEFAULT_DISCONNECT_AFTER,
    DEFAULT_MAX_ANIMATION,
    DEFAULT_MAX_IMAGE,
    DEFAULT_PIXEL_ORDER,
    DOMAIN,
)
from .protocol import SERVICE_UUID


def _is_mask(info: BluetoothServiceInfoBleak) -> bool:
    name = (info.name or "").upper()
    return name.startswith("MASK") or (SERVICE_UUID in info.service_uuids and "MASK" in name)


class ShiningMaskConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._found: dict[str, str] = {}

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._discovery
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery.name or "Shining Mask", data={CONF_ADDRESS: self._discovery.address}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders={"name": self._discovery.name}
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=self._found.get(address, "Shining Mask"), data={CONF_ADDRESS: address})

        current = self._async_current_ids()
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address not in current and _is_mask(info):
                self._found[info.address] = f"{info.name} ({info.address})"
        if not self._found:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(self._found)})
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ShiningMaskOptionsFlow()


class ShiningMaskOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DISCONNECT_AFTER, default=o.get(CONF_DISCONNECT_AFTER, DEFAULT_DISCONNECT_AFTER)): vol.All(
                        vol.Coerce(int), vol.Range(min=0, max=3600)
                    ),
                    vol.Required(CONF_PIXEL_ORDER, default=o.get(CONF_PIXEL_ORDER, DEFAULT_PIXEL_ORDER)): vol.In(
                        ["column", "row"]
                    ),
                    vol.Required(CONF_MAX_IMAGE, default=o.get(CONF_MAX_IMAGE, DEFAULT_MAX_IMAGE)): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=255)
                    ),
                    vol.Required(CONF_MAX_ANIMATION, default=o.get(CONF_MAX_ANIMATION, DEFAULT_MAX_ANIMATION)): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=255)
                    ),
                }
            ),
        )
