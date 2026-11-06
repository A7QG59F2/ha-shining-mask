"""Light entity (brightness) + all mask services, targeted at this entity."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_RGB_COLOR, ColorMode, LightEntity
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MaskConfigEntry, protocol as p
from .const import DOMAIN, TEXT_MODES
from .entity import MaskEntity

_LOGGER = logging.getLogger(__name__)

SLOT = vol.All(vol.Coerce(int), vol.Range(min=1, max=255))


def _slots(value: Any) -> list[int]:
    """Validate one number or a comma list of numbers (1-255), e.g. '1, 2, 3'."""
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        value = [v for v in value.replace(" ", "").split(",") if v]
    return [SLOT(v) for v in cv.ensure_list(value)]


RGB = vol.All(vol.ExactSequence((cv.byte, cv.byte, cv.byte)), vol.Coerce(tuple))


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    mask = entry.runtime_data
    async_add_entities([MaskLight(mask), MaskTextColorLight(mask), MaskBackgroundLight(mask)])
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
            vol.Required("kind"): vol.In(["image", "animation", "diy", "pack"]),
            vol.Required("value"): cv.string,
            vol.Optional("speed"): cv.byte,
            vol.Optional("temporary", default=False): cv.boolean,
            vol.Optional("hold_music"): cv.boolean,
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
    platform.async_register_entity_service("restore_selected", {}, "svc_restore_selected")
    platform.async_register_entity_service("set_music_hold", {vol.Required("hold"): cv.boolean}, "svc_set_music_hold")
    platform.async_register_entity_service("loop_animations", {}, "svc_loop_animations")
    platform.async_register_entity_service(
        "rhythm",
        {
            vol.Optional("mode", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=4)),
            vol.Required("levels"): cv.string,
            vol.Optional("interval", default=0.08): vol.All(vol.Coerce(float), vol.Range(min=0.02, max=2)),
        },
        "svc_rhythm",
    )
    platform.async_register_entity_service("stop_rhythm", {}, "svc_stop_rhythm")
    platform.async_register_entity_service(
        "set_gesture",
        {
            vol.Optional("enabled"): cv.boolean,
            vol.Optional("library"): vol.In(["all", "gallery", "diy"]),
            vol.Optional("circulation"): vol.In(["order", "random"]),
            vol.Optional("items"): cv.string,
        },
        "svc_set_gesture",
    )
    platform.async_register_entity_service(
        "install_face_pack",
        {
            vol.Required("folder"): cv.string,
            vol.Optional("start_slot", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=200)),
            vol.Optional("fit", default="auto"): vol.In(["auto", "crop", "scale"]),
        },
        "svc_install_face_pack",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        "install_effect",
        {
            vol.Optional("effect", default="matrix"): vol.In(["matrix"]),
            vol.Optional("start_slot", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            # PLAY takes at most 10 slots, so an effect is at most 10 frames
            vol.Optional("frames", default=8): vol.All(vol.Coerce(int), vol.Range(min=4, max=10)),
            vol.Optional("speed", default=200): cv.byte,
        },
        "svc_install_effect",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        "generate_dashboard",
        {vol.Optional("columns", default=4): vol.All(vol.Coerce(int), vol.Range(min=1, max=12))},
        "svc_generate_dashboard",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        "reset_mask", {vol.Required("confirm"): vol.All(cv.boolean, True)}, "svc_reset_mask"
    )
    platform.async_register_entity_service("delete_diy", {vol.Required("slots"): _slots}, "svc_delete_diy")
    platform.async_register_entity_service(
        "send_command",
        {vol.Required("command"): cv.string, vol.Optional("args", default=""): cv.string},
        "svc_send_command",
    )


class MaskLight(MaskEntity, LightEntity):
    """The mask itself: on/off and brightness. All mask actions are registered on this entity."""
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
            "assistant_face_holding_music": self.mask.music_hold,
            "selected_face": f"{s.selected[0]} {','.join(map(str, s.selected[1]))}" if s.selected else None,
            "face_pack": s.pack_name,
            "face_pack_roles": s.pack or None,
            "last_error": s.last_error,
            "gatt": s.gatt,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.mask.async_turn_on(kwargs.get(ATTR_BRIGHTNESS))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.mask.async_turn_off()

    # ---------------------------------------------------------------- services
    async def svc_show_image(self, image: int) -> None:
        """Action: show a built-in image (it becomes the chosen face)."""
        await self.mask.async_show_image(image)

    async def svc_show_animation(self, animation: int) -> None:
        """Action: play a built-in animation (it becomes the chosen face)."""
        await self.mask.async_show_animation(animation)

    async def svc_play_diy(self, slots: list[int], speed: int | None = None) -> None:
        """Action: play DIY slots, optionally at a speed."""
        await self.mask.async_play_diy(slots, speed)

    async def svc_show_face(
        self,
        kind: str,
        value: str,
        speed: int | None = None,
        temporary: bool = False,
        hold_music: bool | None = None,
    ) -> None:
        """Action: show any kind of face; temporary=True for assistant faces that shouldn't stick.

        A temporary face is the assistant's, and the assistant beats the music bars. So unless the
        caller says otherwise (hold_music), a temporary face holds the bars off until the chosen
        face comes back (restore_selected) or set_music_hold(false). Pack roles 'idle', 'sleep'
        and 'error' don't hold: the assistant isn't busy then. This makes the priority work even
        with scripts of your own that never call set_music_hold.
        """
        if temporary:
            role = value.strip().lower() if kind == "pack" else None
            hold = hold_music if hold_music is not None else role not in ("idle", "sleep", "error")
            await self.mask.async_set_music_hold(hold)
        if kind == "pack":
            await self.mask.async_play_role(value.strip().lower(), speed)
            return
        try:
            slots = _slots(value)
        except vol.Invalid as err:
            raise ServiceValidationError(f"Invalid value '{value}': use a number or comma list") from err
        if kind == "image":
            await self.mask.async_show_image(slots[0], temporary)
        elif kind == "animation":
            await self.mask.async_show_animation(slots[0], temporary)
        else:
            await self.mask.async_play_diy(slots, speed, temporary)

    async def svc_install_face_pack(self, folder: str, start_slot: int = 10, fit: str = "auto") -> dict[str, Any]:
        """Action: upload a folder of face pictures into DIY slots and map them to assistant roles."""
        from .facepack import list_packs, path_allowed, plan_pack, resolve_folder
        from .graphics import fit_image

        path = await self.hass.async_add_executor_job(resolve_folder, self.hass, folder)
        if not path_allowed(self.hass, path):
            raise ServiceValidationError(f"{path} is outside the config folder and not in allowlist_external_dirs")

        def _plan():
            if not path.is_dir():
                raise ServiceValidationError(
                    f"Folder {path} not found. Packs found: {', '.join(list_packs(self.hass)) or 'none'}"
                )
            return plan_pack(path)

        try:
            plan = await self.hass.async_add_executor_job(_plan)
        except FileNotFoundError as err:
            raise ServiceValidationError(str(err)) from err

        # every distinct frame gets one slot, in role order
        frame_slot: dict[str, int] = {}
        next_slot = start_slot
        for role in ("idle", "listening", "thinking", "talking", "error", "sleep"):
            for f in plan.get(role, []):
                key = str(f)
                if key not in frame_slot:
                    if next_slot == self.mask.blank_slot:
                        next_slot += 1
                    frame_slot[key] = next_slot
                    next_slot += 1

        def _loader(p):
            def _load():
                from PIL import Image

                with Image.open(p) as img:
                    img.seek(0)  # first frame of GIFs
                    return fit_image(img, fit)

            return _load

        for f_str, slot in frame_slot.items():
            await self._upload_canvas(slot, _loader(f_str))
            self.mask.slot_names[slot] = f"{path.name}/{f_str.rsplit('/', 1)[-1]}"

        pack = {role: [frame_slot[str(f)] for f in frames] for role, frames in plan.items()}
        self.mask.state.pack = pack
        self.mask.state.pack_name = path.name
        self.mask.preview_changed()
        await self.mask.async_play_role("idle")
        return {
            "pack": path.name,
            "roles": {role: [f"slot {frame_slot[str(f)]}: {f.name}" for f in frames] for role, frames in plan.items()},
            "slots_used": f"{start_slot}-{next_slot - 1}",
        }

    async def svc_loop_animations(self) -> None:
        """Action: loop through the mask's animations."""
        await self.mask.async_animation_loop()

    async def svc_rhythm(self, levels: str, mode: int = 0, interval: float = 0.08) -> None:
        """levels: one frame "0,3,7,15,..." (12 numbers 0-15); several frames separated by ';'."""
        frames = []
        for chunk in levels.split(";"):
            vals = [v for v in chunk.replace(" ", "").split(",") if v]
            if not vals:
                continue
            try:
                frames.append([int(v) for v in vals])
            except ValueError as err:
                raise ServiceValidationError(f"Bad levels '{chunk}': use numbers 0-15") from err
        if not frames:
            raise ServiceValidationError("Give at least one frame of up to 12 levels (0-15)")
        await self.mask.async_rhythm(mode, frames, interval)

    async def svc_stop_rhythm(self) -> None:
        """Action: leave music-bar mode and show the last face again."""
        await self.mask.async_exit_rhythm()

    async def svc_set_gesture(
        self,
        enabled: bool | None = None,
        library: str | None = None,
        circulation: str | None = None,
        items: str | None = None,
    ) -> None:
        # items: face numbers for the chosen library ("1, 4, 7-9"); no limit - long lists are
        # sent in several packets. Empty string clears the list.
        """Action: set the gesture face switch (on/off, library, circulation, faces)."""
        item_list = None
        if items is not None:
            try:
                item_list = p.parse_number_list(items)
            except ValueError as err:
                raise ServiceValidationError(f"Use face numbers like '1, 4, 7-9' ({err})") from err
        await self.mask.async_set_gesture(enabled, library, circulation, item_list)

    async def svc_set_music_hold(self, hold: bool) -> None:
        """Action: hold the music bars off while the assistant face is up (the built-in assistant does this itself)."""
        await self.mask.async_set_music_hold(hold)

    async def svc_restore_selected(self) -> None:
        """Action: go back to the chosen face (does nothing while music bars are up)."""
        await self.mask.async_restore_selected()

    async def svc_set_text(self, text: str, color, mode: str, speed: int | None = None) -> None:
        """Action: show text with a colour, mode and speed."""
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
        """Action: upload a picture or built-in face into a DIY slot."""
        from .graphics import BUILTIN_FACES, fit_image

        if builtin:
            if builtin not in BUILTIN_FACES:
                raise ServiceValidationError(f"Unknown builtin face; choose from {', '.join(BUILTIN_FACES)}")
            await self._upload_canvas(slot, lambda: fit_image(BUILTIN_FACES[builtin]()))
            self.mask.slot_names[slot] = builtin
            self.mask.preview_changed()
        elif path:
            from .facepack import path_allowed

            if not path_allowed(self.hass, path):
                raise ServiceValidationError(f"{path} is outside the config folder and not in allowlist_external_dirs")

            def _load():
                from PIL import Image

                with Image.open(path) as img:
                    return fit_image(img)

            try:
                await self._upload_canvas(slot, _load)
            except OSError as err:
                raise HomeAssistantError(f"Could not read image {path}: {err}") from err
            self.mask.slot_names[slot] = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            self.mask.preview_changed()
        else:
            raise ServiceValidationError("Provide either path or builtin")

    async def svc_install_default_faces(self) -> None:
        """Action: upload the built-in assistant faces into DIY slots 1-7."""
        from .graphics import BUILTIN_FACES, DEFAULT_SLOTS, fit_image

        for slot, name in DEFAULT_SLOTS.items():
            await self._upload_canvas(slot, lambda n=name: fit_image(BUILTIN_FACES[n]()))
            self.mask.slot_names[slot] = name
        self.mask.preview_changed()
        await self.mask.async_check()

    async def svc_install_effect(
        self, effect: str = "matrix", start_slot: int = 1, frames: int = 8, speed: int = 200
    ) -> dict[str, Any]:
        """Action: draw an animated effect, upload its frames to DIY slots, then play it.

        The frames are uploaded one slot each (start_slot, start_slot+1, ...), get dashboard
        previews like any DIY image, and play as a DIY sequence that becomes the chosen face.
        Uploading takes a few seconds per frame; it only has to be done once.
        """
        from .const import CLOCK_FIRST_SLOT, MAX_DIY_SLOT
        from .effects import EFFECTS

        last = start_slot + frames - 1
        if last > MAX_DIY_SLOT:
            raise ServiceValidationError(
                f"Slots {start_slot}-{last} don't fit: the mask stores DIY slots 1-{MAX_DIY_SLOT}"
            )
        if last >= CLOCK_FIRST_SLOT:
            _LOGGER.warning("Effect slots %s-%s overlap the clock's slots %s-%s", start_slot, last, CLOCK_FIRST_SLOT, MAX_DIY_SLOT)
        images = await self.hass.async_add_executor_job(EFFECTS[effect], frames)
        slots = list(range(start_slot, start_slot + len(images)))
        for i, (slot, img) in enumerate(zip(slots, images), 1):
            await self._upload_canvas(slot, lambda im=img: im)
            self.mask.slot_names[slot] = f"{effect} {i}"
        await self.mask.async_play_diy(slots, speed)
        return {"effect": effect, "slots": slots, "play_again": f"play_diy slots: {start_slot}-{slots[-1]}"}

    async def svc_generate_dashboard(self, columns: int = 4) -> dict[str, Any]:
        """Action: write the face-picker card, the panel view and the settings card as YAML."""
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
        settings = self._settings_card()

        def _write_settings():
            import pathlib

            import yaml

            (pathlib.Path(base) / "settings_card.yaml").write_text(yaml.safe_dump(settings, sort_keys=False))

        await self.hass.async_add_executor_job(_write_settings)
        return {
            "settings_card_file": f"{base}/settings_card.yaml",
            "settings_card": settings,
            "card_file": f"{base}/dashboard_card.yaml",
            "panel_view_file": f"{base}/dashboard_panel_view.yaml",
            "builtin_folder": folder,
            "builtin_pictures_found": found,
            "unassigned_builtin_files": unassigned,
        }

    def _settings_card(self) -> dict[str, Any]:
        """Every mask setting, grouped into sections in a sensible order."""
        from homeassistant.helpers import entity_registry as er

        reg = er.async_get(self.hass)
        addr = self.mask.address

        def ent(domain: str, key: str):
            return reg.async_get_entity_id(domain, DOMAIN, f"{addr}_{key}")

        def section(title: str, rows: list[tuple[str, str, str]]) -> dict[str, Any]:
            items = [{"entity": e, "name": n} for d, k, n in rows if (e := ent(d, k))]
            return {"type": "entities", "title": title, "state_color": True, "entities": items}

        # Gesture: on/off, library, then the face list - shown only when the library has one to
        # pick (gallery/diy), the way the app opens its picker - then circulation.
        gesture = section("Gesture", [("switch", "gesture_switch", "On / off"),
                                      ("select", "gesture_library", "Library")])
        library, faces = ent("select", "gesture_library"), ent("text", "gesture_faces")
        if library and faces:
            gesture["entities"].append({
                "type": "conditional",
                "conditions": [{"entity": library, "state_not": "all"}],
                "row": {"entity": faces, "name": "Faces (image numbers / DIY slots)"},
            })
        gesture["entities"] += section("", [("select", "gesture_circulation", "Circulation")])["entities"]

        return {
            "type": "vertical-stack",
            "cards": [
                section("Mask", [("light", "light", "Mask"), ("image", "current_face", "Now showing")]),
                section("Assistant face", [
                    ("select", "assist_satellite", "Satellite"),
                    ("select", "assist_face_listening", "Listening"),
                    ("select", "assist_face_thinking", "Thinking"),
                    ("select", "assist_face_talking", "Talking"),
                    ("number", "assist_talk_speed", "Talking speed"),
                    ("select", "assist_face_idle", "Idle"),
                    ("number", "assist_idle_return", "Back to chosen face after"),
                    ("select", "assist_face_error", "Unavailable"),
                    ("number", "assist_unavailable_after", "Unavailable for"),
                    ("select", "assist_unavailable_action", "Then"),
                ]),
                section("Clock", [("switch", "clock", "Clock face"), ("select", "clock_theme", "Colors"),
                                  ("select", "clock_weather", "Weather"), ("select", "clock_motion", "Motion"),
                                  ("number", "clock_speed", "Blink speed")]),
                section("Face", [("number", "image", "Image"), ("number", "animation", "Animation"),
                                 ("number", "speed", "Speed")]),
                section("Text", [("text", "text", "Text"), ("select", "text_effect", "Effect"),
                                 ("select", "text_mode", "Mode"), ("light", "text_color", "Color"),
                                 ("light", "bg_color", "Background color")]),
                section("Visualizer", [("switch", "music_visualizer", "On / off"),
                                       ("select", "bars_style_select", "Style"),
                                       ("number", "bars_sensitivity", "Sensitivity"),
                                       ("number", "bars_contrast", "Contrast"),
                                       ("number", "bars_bass", "Bass"), ("number", "bars_mid", "Mid"),
                                       ("number", "bars_treble", "Treble"), ("number", "bars_delay", "Delay")]),
                gesture,
            ],
        }

    async def svc_reset_mask(self, confirm: bool) -> None:
        """Action: delete every uploaded DIY image, switch extras off, clear previews."""
        from .previews import diy_dir

        await self.mask.async_reset()

        def _clear_previews() -> None:
            folder = diy_dir(self.hass)
            if folder.is_dir():
                for f in folder.glob("*.png"):
                    if f.stem.isdigit():  # previews are named <slot>.png
                        f.unlink(missing_ok=True)

        await self.hass.async_add_executor_job(_clear_previews)
        self.mask.preview_changed()

    async def svc_delete_diy(self, slots: list[int]) -> None:
        """Action: delete DIY slots."""
        await self.mask.async_delete_diy(slots)

    async def svc_send_command(self, command: str, args: str = "") -> None:
        """Action: send a raw command tag + hex arguments, for experimenting."""
        try:
            raw = bytes.fromhex(args.replace(" ", ""))
            await self.mask.async_raw(command.upper(), raw)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err


class _ColorLight(MaskEntity, LightEntity):
    """RGB colour setting shown as a light: on = custom colour enabled, colour picker = the colour."""

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_assumed_state = True
    _key = ""

    def __init__(self, mask) -> None:
        super().__init__(mask, self._key)

    def _get(self) -> tuple[list[int], bool]:
        raise NotImplementedError

    async def _set(self, rgb, enable: bool) -> None:
        raise NotImplementedError

    @property
    def is_on(self) -> bool:
        return self._get()[1]

    @property
    def rgb_color(self):
        return tuple(self._get()[0])

    @property
    def brightness(self) -> int:
        return 255

    async def async_turn_on(self, **kwargs: Any) -> None:
        rgb = kwargs.get(ATTR_RGB_COLOR) or self._get()[0]
        if ATTR_BRIGHTNESS in kwargs:  # brightness slider dims the colour itself
            scale = kwargs[ATTR_BRIGHTNESS] / 255
            rgb = [round(c * scale) for c in rgb]
        await self._set(list(rgb), True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(None, False)


class MaskTextColorLight(_ColorLight):
    """Text colour as a colour light: on = use the colour, colour picker = the colour."""
    _attr_name = "Text color"
    _attr_icon = "mdi:format-color-text"
    _key = "text_color"

    def _get(self):
        return self.mask.state.text_color, self.mask.state.text_color_on

    async def _set(self, rgb, enable):
        await self.mask.async_set_text_color(rgb, enable)


class MaskBackgroundLight(_ColorLight):
    """Background colour behind text, as a colour light."""
    _attr_name = "Text background color"
    _attr_icon = "mdi:format-color-fill"
    _key = "bg_color"

    def _get(self):
        return self.mask.state.bg_color, self.mask.state.bg_color_on

    async def _set(self, rgb, enable):
        await self.mask.async_set_bg_color(rgb, enable)
