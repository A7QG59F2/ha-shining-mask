"""Config flow for Shining Mask."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak, async_discovered_service_info
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import (
    CONF_BLANK_SLOT,
    CONF_MAX_BRIGHTNESS,
    CONF_VISUALIZER_PORT,
    DEFAULT_VISUALIZER_PORT,
    DEFAULT_BLANK_SLOT,
    DEFAULT_MAX_BRIGHTNESS,
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


MANUAL = "manual"


def _is_mask(info: BluetoothServiceInfoBleak) -> bool:
    name = (info.name or "").upper()
    return "MASK" in name or SERVICE_UUID in info.service_uuids


def _label(info: BluetoothServiceInfoBleak) -> str:
    name = info.name or "(no name)"
    extra = "" if info.connectable else " - heard only via a non-connectable proxy"
    return f"{name} ({info.address}, {info.rssi} dBm){extra}"


class ShiningMaskConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._names: dict[str, str] = {}

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

    async def _create(self, address: str, title: str) -> ConfigFlowResult:
        address = address.strip().upper()
        await self.async_set_unique_id(address, raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=title, data={CONF_ADDRESS: address})

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address == MANUAL:
                return await self.async_step_manual()
            return await self._create(address, self._names.get(address, "Shining Mask"))

        current = self._async_current_ids()
        infos: dict[str, BluetoothServiceInfoBleak] = {}
        # connectable=False returns everything heard, including via listen-only proxies
        for info in async_discovered_service_info(self.hass, connectable=False):
            if info.address in current:
                continue
            prev = infos.get(info.address)
            if prev is None or (info.connectable and not prev.connectable):
                infos[info.address] = info
        likely = [i for i in infos.values() if _is_mask(i)]
        # nothing matched: show every named device so the user can spot the mask
        shown = likely or [i for i in infos.values() if i.name and i.name != i.address]
        shown.sort(key=lambda i: i.rssi or -999, reverse=True)
        self._names = {i.address: i.name or "Shining Mask" for i in shown[:40]}
        options = {i.address: _label(i) for i in shown[:40]}
        options[MANUAL] = "Enter Bluetooth address manually"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(options)}),
            description_placeholders={
                "hint": "Likely masks found." if likely else "No device named MASK found - showing all named devices (strongest signal first)."
            },
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            addr = user_input[CONF_ADDRESS].strip().upper()
            if len(addr.split(":")) == 6:
                return await self._create(addr, "Shining Mask")
            errors["base"] = "invalid_address"
        return self.async_show_form(
            step_id="manual", data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}), errors=errors
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
                    vol.Required(CONF_MAX_BRIGHTNESS, default=o.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=255)
                    ),
                    vol.Required(CONF_BLANK_SLOT, default=o.get(CONF_BLANK_SLOT, DEFAULT_BLANK_SLOT)): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=255)
                    ),
                    vol.Required(CONF_VISUALIZER_PORT, default=o.get(CONF_VISUALIZER_PORT, DEFAULT_VISUALIZER_PORT)): vol.All(
                        vol.Coerce(int), vol.Range(min=1024, max=65535)
                    ),
                }
            ),
        )
