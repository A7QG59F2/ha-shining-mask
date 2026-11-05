"""Light entity (brightness) + all mask services, targeted at this entity."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MaskConfigEntry
from .const import TEXT_MODES
from .entity import MaskEntity

SLOT = vol.All(vol.Coerce(int), vol.Range(min=1, max=255))


def _slots(value: Any) -> list[int]:
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        value = [v for v in value.replace(" ", "").split(",") if v]
    return [SLOT(v) for v in cv.ensure_list(value)]


RGB = vol.All(vol.ExactSequence((cv.byte, cv.byte, cv.byte)), vol.Coerce(tuple))


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([MaskLight(entry.runtime_data)])
    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service("show_image", {vol.Required("image"): SLOT}, "svc_show_image")
    platform.async_register_entity_service("show_animation", {vol.Required("animation"): SLOT}, "svc_show_animation")
    platform.async_register_entity_service(
        "play_diy",
        {vol.Required("slots"): _slots, vol.Optional("speed"): cv.byte},
        "svc_play_diy",
    )
    platform.async_register_entity_service(
        "show_face",
        {
            vol.Required("kind"): vol.In(["image", "animation", "diy"]),
            vol.Required("value"): cv.string,
            vol.Optional("speed"): cv.byte,
        },
        "svc_show_face",
    )
    platform.async_register_entity_service(
        "set_text",
        {
            vol.Required("text"): cv.string,
            vol.Optional("color", default=[255, 255, 255]): RGB,
            vol.Optional("mode", default="scroll_left"): vol.In(list(TEXT_MODES)),
            vol.Optional("speed"): cv.byte,
        },
        "svc_set_text",
    )
    platform.async_register_entity_service(
        "upload_image",
        {
            vol.Required("slot"): SLOT,
            vol.Exclusive("path", "source"): cv.string,
            vol.Exclusive("builtin", "source"): cv.string,
        },
        "svc_upload_image",
    )
    platform.async_register_entity_service("install_default_faces", {}, "svc_install_default_faces")
    platform.async_register_entity_service("delete_diy", {vol.Required("slots"): _slots}, "svc_delete_diy")
    platform.async_register_entity_service(
        "send_command",
        {vol.Required("command"): cv.string, vol.Optional("args", default=""): cv.string},
        "svc_send_command",
    )


class MaskLight(MaskEntity, LightEntity):
    _attr_name = None  # use device name
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_assumed_state = True

    def __init__(self, mask) -> None:
        super().__init__(mask, "light")

    @property
    def is_on(self) -> bool:
        return self.mask.state.is_on

    @property
    def brightness(self) -> int:
        return self.mask.state.brightness

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.mask.state
        return {
            "connected": s.connected,
            "image": s.image,
            "animation": s.animation,
            "diy_slots": s.diy,
            "text": s.text,
            "diy_image_count": s.diy_count,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.mask.async_turn_on(kwargs.get(ATTR_BRIGHTNESS))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.mask.async_turn_off()

    # ---------------------------------------------------------------- services
    async def svc_show_image(self, image: int) -> None:
        await self.mask.async_show_image(image)

    async def svc_show_animation(self, animation: int) -> None:
        await self.mask.async_show_animation(animation)

    async def svc_play_diy(self, slots: list[int], speed: int | None = None) -> None:
        await self.mask.async_play_diy(slots, speed)

    async def svc_show_face(self, kind: str, value: str, speed: int | None = None) -> None:
        try:
            slots = _slots(value)
        except vol.Invalid as err:
            raise ServiceValidationError(f"Invalid value '{value}': use a number or comma list") from err
        if kind == "image":
            await self.mask.async_show_image(slots[0])
        elif kind == "animation":
            await self.mask.async_show_animation(slots[0])
        else:
            await self.mask.async_play_diy(slots, speed)

    async def svc_set_text(self, text: str, color, mode: str, speed: int | None = None) -> None:
        await self.mask.async_set_text(text, color, TEXT_MODES[mode], speed)

    async def svc_upload_image(self, slot: int, path: str | None = None, builtin: str | None = None) -> None:
        from .graphics import BUILTIN_FACES, image_to_payload

        order = self.mask.pixel_order
        if builtin:
            if builtin not in BUILTIN_FACES:
                raise ServiceValidationError(f"Unknown builtin face; choose from {', '.join(BUILTIN_FACES)}")
            payload = await self.hass.async_add_executor_job(lambda: image_to_payload(BUILTIN_FACES[builtin](), order))
        elif path:
            if not self.hass.config.is_allowed_path(path):
                raise ServiceValidationError(f"{path} is not in allowlist_external_dirs (use a path under /config or /media)")

            def _load() -> bytes:
                from PIL import Image

                with Image.open(path) as img:
                    return image_to_payload(img, order)

            try:
                payload = await self.hass.async_add_executor_job(_load)
            except OSError as err:
                raise HomeAssistantError(f"Could not read image {path}: {err}") from err
        else:
            raise ServiceValidationError("Provide either path or builtin")
        await self.mask.async_upload_image(slot, payload)

    async def svc_install_default_faces(self) -> None:
        from .graphics import BUILTIN_FACES, DEFAULT_SLOTS, image_to_payload

        order = self.mask.pixel_order
        for slot, name in DEFAULT_SLOTS.items():
            payload = await self.hass.async_add_executor_job(
                lambda n=name: image_to_payload(BUILTIN_FACES[n](), order)
            )
            await self.mask.async_upload_image(slot, payload)
        await self.mask.async_check()

    async def svc_delete_diy(self, slots: list[int]) -> None:
        await self.mask.async_delete_diy(slots)

    async def svc_send_command(self, command: str, args: str = "") -> None:
        try:
            raw = bytes.fromhex(args.replace(" ", ""))
            await self.mask.async_raw(command.upper(), raw)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
