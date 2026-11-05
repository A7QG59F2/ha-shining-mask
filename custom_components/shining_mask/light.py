"""Light entity (brightness) + all mask services, targeted at this entity."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant, SupportsResponse
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
    platform.async_register_entity_service(
        "generate_dashboard",
        {vol.Optional("columns", default=4): vol.All(vol.Coerce(int), vol.Range(min=1, max=12))},
        "svc_generate_dashboard",
        supports_response=SupportsResponse.OPTIONAL,
    )
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
            "last_error": s.last_error,
            "gatt": s.gatt,
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

    async def _upload_canvas(self, slot: int, make_canvas) -> None:
        """make_canvas: blocking callable returning a 46x58 RGB canvas."""
        from .graphics import encode_image_pixels
        from .previews import save_diy_preview

        order = self.mask.pixel_order

        def _prep():
            canvas = make_canvas()
            return canvas, encode_image_pixels(list(canvas.getdata()), order)

        canvas, payload = await self.hass.async_add_executor_job(_prep)
        await self.mask.async_upload_image(slot, payload)
        await self.hass.async_add_executor_job(save_diy_preview, self.hass, slot, canvas)
        self.mask.preview_changed()

    async def svc_upload_image(self, slot: int, path: str | None = None, builtin: str | None = None) -> None:
        from .graphics import BUILTIN_FACES, fit_image

        if builtin:
            if builtin not in BUILTIN_FACES:
                raise ServiceValidationError(f"Unknown builtin face; choose from {', '.join(BUILTIN_FACES)}")
            await self._upload_canvas(slot, lambda: fit_image(BUILTIN_FACES[builtin]()))
            self.mask.slot_names[slot] = builtin
        elif path:
            if not self.hass.config.is_allowed_path(path):
                raise ServiceValidationError(f"{path} is not in allowlist_external_dirs (use a path under /config or /media)")

            def _load():
                from PIL import Image

                with Image.open(path) as img:
                    return fit_image(img)

            try:
                await self._upload_canvas(slot, _load)
            except OSError as err:
                raise HomeAssistantError(f"Could not read image {path}: {err}") from err
            self.mask.slot_names[slot] = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        else:
            raise ServiceValidationError("Provide either path or builtin")

    async def svc_install_default_faces(self) -> None:
        from .graphics import BUILTIN_FACES, DEFAULT_SLOTS, fit_image

        for slot, name in DEFAULT_SLOTS.items():
            await self._upload_canvas(slot, lambda n=name: fit_image(BUILTIN_FACES[n]()))
            self.mask.slot_names[slot] = name
        await self.mask.async_check()

    async def svc_generate_dashboard(self, columns: int = 4) -> dict[str, Any]:
        import yaml

        from .previews import build_dashboard, builtin_dir, root, scan_builtin

        def _build():
            dump = lambda obj: yaml.safe_dump(obj, sort_keys=False, allow_unicode=True)  # noqa: E731
            card, unassigned = build_dashboard(self.hass, self.entity_id, self.mask.slot_names, self.mask.blank_slot, columns)
            # a full-width panel view: wider grids, current-face preview + brightness on top
            panel_card, _ = build_dashboard(self.hass, self.entity_id, self.mask.slot_names, self.mask.blank_slot, columns * 2)
            face_entity = self.entity_id.replace("light.", "image.", 1) + "_current_face"
            panel_card["cards"][0:0] = [
                {
                    "type": "horizontal-stack",
                    "cards": [
                        {"type": "picture-entity", "entity": face_entity, "show_state": False, "show_name": True, "name": "Now showing"},
                        {"type": "tile", "entity": self.entity_id, "features": [{"type": "light-brightness"}]},
                    ],
                }
            ]
            view = {"title": "Mask", "path": "mask", "icon": "mdi:drama-masks", "type": "panel", "cards": [panel_card]}
            base = root(self.hass)
            (base / "dashboard_card.yaml").write_text(dump(card))
            (base / "dashboard_panel_view.yaml").write_text(dump(view))
            return card, unassigned, str(base), str(builtin_dir(self.hass)), len(scan_builtin(self.hass))

        card, unassigned, base, folder, found = await self.hass.async_add_executor_job(_build)
        return {
            "card_file": f"{base}/dashboard_card.yaml",
            "panel_view_file": f"{base}/dashboard_panel_view.yaml",
            "builtin_folder": folder,
            "builtin_pictures_found": found,
            "unassigned_builtin_files": unassigned,
        }

    async def svc_delete_diy(self, slots: list[int]) -> None:
        await self.mask.async_delete_diy(slots)

    async def svc_send_command(self, command: str, args: str = "") -> None:
        try:
            raw = bytes.fromhex(args.replace(" ", ""))
            await self.mask.async_raw(command.upper(), raw)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
