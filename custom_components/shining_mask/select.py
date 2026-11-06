"""Text display mode select."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MaskConfigEntry
from .const import (
    BAR_STYLES,
    CONF_MAX_ANIMATION,
    CONF_MAX_IMAGE,
    DEFAULT_MAX_ANIMATION,
    DEFAULT_MAX_IMAGE,
    TEXT_EFFECTS,
    TEXT_MODES,
)
from .entity import MaskEntity


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    m = entry.runtime_data
    from .assist import FACE_KEYS

    max_img = entry.options.get(CONF_MAX_IMAGE, DEFAULT_MAX_IMAGE)
    max_anim = entry.options.get(CONF_MAX_ANIMATION, DEFAULT_MAX_ANIMATION)
    async_add_entities(
        [MaskAssistSatelliteSelect(m), MaskAssistUnavailableSelect(m)]
        + [MaskAssistFaceSelect(m, key, max_img, max_anim) for key in FACE_KEYS]
    )
    async_add_entities([MaskTextModeSelect(m), MaskTextEffectSelect(m), MaskGestureLibrarySelect(m), MaskGestureCirculationSelect(m), MaskBarsStyleSelect(m), MaskClockWeatherSelect(m), MaskClockThemeSelect(m), MaskClockMotionSelect(m)])


class MaskTextModeSelect(MaskEntity, SelectEntity):
    """How uploaded text moves: steady, blink, scroll left or right."""
    _attr_translation_key = "text_mode"
    _attr_name = "Text mode"
    _attr_icon = "mdi:format-text-variant"
    _attr_options = list(TEXT_MODES)

    def __init__(self, mask) -> None:
        super().__init__(mask, "text_mode")

    @property
    def current_option(self) -> str:
        return self.mask.state.text_mode

    async def async_select_option(self, option: str) -> None:
        await self.mask.async_set_text_mode(option, TEXT_MODES[option])


class MaskTextEffectSelect(MaskEntity, SelectEntity):
    """Colour effects on the text (dots, rainbow edges, fades) and built-in backgrounds behind it (background_1-4)."""

    _attr_name = "Text effect"
    _attr_icon = "mdi:gradient-horizontal"
    _attr_options = list(TEXT_EFFECTS)

    def __init__(self, mask) -> None:
        super().__init__(mask, "text_effect")

    @property
    def current_option(self) -> str:
        return self.mask.state.text_effect

    async def async_select_option(self, option: str) -> None:
        await self.mask.async_set_text_effect(option, TEXT_EFFECTS[option])


class MaskGestureLibrarySelect(MaskEntity, SelectEntity):
    """App: gesture page > Library selection."""

    _attr_name = "Gesture library"
    _attr_icon = "mdi:image-multiple"
    _attr_options = ["all", "gallery", "diy"]

    def __init__(self, mask) -> None:
        super().__init__(mask, "gesture_library")

    @property
    def current_option(self) -> str:
        return self.mask.state.gesture_library

    async def async_select_option(self, option: str) -> None:
        await self.mask.async_set_gesture(library=option)


class MaskGestureCirculationSelect(MaskEntity, SelectEntity):
    """App: gesture page > Circulation mode."""

    _attr_name = "Gesture circulation"
    _attr_icon = "mdi:shuffle-variant"
    _attr_options = ["order", "random"]

    def __init__(self, mask) -> None:
        super().__init__(mask, "gesture_circulation")

    @property
    def current_option(self) -> str:
        return self.mask.state.gesture_circulation

    async def async_select_option(self, option: str) -> None:
        await self.mask.async_set_gesture(circulation=option)


class MaskBarsStyleSelect(MaskEntity, SelectEntity):
    """Look of the music bars (the mask's five rhythm styles)."""

    _attr_name = "Visualizer style"
    _attr_icon = "mdi:chart-bar"
    _attr_options = list(BAR_STYLES)

    def __init__(self, mask) -> None:
        super().__init__(mask, "bars_style_select")

    @property
    def current_option(self) -> str:
        by_value = {v: k for k, v in BAR_STYLES.items()}
        return by_value.get(self.mask.state.visualizer_style, "Rainbow")

    async def async_select_option(self, option: str) -> None:
        self.mask.set_visualizer_tuning(style=BAR_STYLES[option])


class MaskClockWeatherSelect(MaskEntity, SelectEntity):
    """Which weather entity drives the clock's sky (condition) and temperature."""

    _attr_name = "Clock weather"
    _attr_icon = "mdi:weather-partly-cloudy"

    def __init__(self, mask) -> None:
        super().__init__(mask, "clock_weather")

    @property
    def options(self) -> list[str]:
        found = sorted(self.hass.states.async_entity_ids("weather")) if self.hass else []
        return found or ["none"]

    @property
    def current_option(self) -> str | None:
        chosen = self.mask.state.clock_weather
        if chosen in self.options:
            return chosen
        # nothing chosen yet: prefer weather.home, else the first weather entity
        return "weather.home" if "weather.home" in self.options else self.options[0]

    async def async_select_option(self, option: str) -> None:
        self.mask.set_clock_option(clock_weather=None if option == "none" else option)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.mask.state.clock_weather is None and self.current_option != "none":
            self.mask.set_clock_option(clock_weather=self.current_option)  # remember the default


class MaskClockThemeSelect(MaskEntity, SelectEntity):
    """Colour theme of the clock's time, temperature and date (sky colours stay natural)."""

    _attr_name = "Clock colors"
    _attr_icon = "mdi:palette"

    def __init__(self, mask) -> None:
        super().__init__(mask, "clock_theme")
        from .clockface import CLOCK_THEMES

        self._attr_options = list(CLOCK_THEMES)

    @property
    def current_option(self) -> str:
        return self.mask.state.clock_theme

    async def async_select_option(self, option: str) -> None:
        self.mask.set_clock_option(clock_theme=option)
        await self.mask.async_refresh_clock()


class MaskClockMotionSelect(MaskEntity, SelectEntity):
    """Animated (2 frames a minute: blinking colon, moving weather) or Still (1 frame).

    Each frame is an upload, and the mask shows a download arrow while it receives one, so
    Still halves how long the arrow appears each minute.
    """

    _attr_name = "Clock motion"
    _attr_icon = "mdi:motion-play-outline"
    _attr_options = ["Animated", "Still"]

    def __init__(self, mask) -> None:
        super().__init__(mask, "clock_motion")

    @property
    def current_option(self) -> str:
        return self.mask.state.clock_motion

    async def async_select_option(self, option: str) -> None:
        self.mask.set_clock_option(clock_motion=option)
        await self.mask.async_refresh_clock()


class MaskAssistSatelliteSelect(MaskEntity, SelectEntity):
    """Which voice satellite the mask follows. 'none' switches the assistant faces off."""

    _attr_name = "Assistant satellite"
    _attr_icon = "mdi:account-voice"

    def __init__(self, mask) -> None:
        super().__init__(mask, "assist_satellite")

    @property
    def options(self) -> list[str]:
        found = sorted(self.hass.states.async_entity_ids("assist_satellite")) if self.hass else []
        return ["none", *found]

    @property
    def current_option(self) -> str:
        return self.mask.state.assist_satellite or "none"

    async def async_select_option(self, option: str) -> None:
        self.mask.set_assist_option(satellite=None if option == "none" else option)


class MaskAssistFaceSelect(MaskEntity, SelectEntity):
    """Face shown for one assistant state (listening, thinking, talking, idle, error)."""

    _attr_icon = "mdi:emoticon-outline"

    LABELS = {"listening": "Listening", "thinking": "Thinking", "talking": "Talking", "idle": "Idle", "error": "Error"}

    def __init__(self, mask, key: str, max_image: int, max_animation: int) -> None:
        super().__init__(mask, f"assist_face_{key}")
        self._key = key
        self._max = (max_image, max_animation)
        self._attr_name = f"Assistant {self.LABELS[key].lower()} face"

    @property
    def options(self) -> list[str]:
        from .assist import face_options

        return face_options(self.mask, *self._max)

    @property
    def current_option(self) -> str | None:
        from .assist import DEFAULT_FACES

        choice = self.mask.state.assist_faces.get(self._key, DEFAULT_FACES[self._key])
        if choice in self.options:
            return choice
        # DIY labels include the slot's name, which can change; match on "DIY <n>"
        if choice.startswith("DIY "):
            num = choice.split()[1]
            return next((o for o in self.options if o.split()[:2] == ["DIY", num]), None)
        return None

    async def async_select_option(self, option: str) -> None:
        self.mask.set_assist_option(**{f"face_{self._key}": option})


class MaskAssistUnavailableSelect(MaskEntity, SelectEntity):
    """What to do once the satellite has been unavailable for 'Assistant unavailable after'."""

    _attr_name = "Assistant unavailable action"
    _attr_icon = "mdi:lan-disconnect"

    def __init__(self, mask) -> None:
        super().__init__(mask, "assist_unavailable_action")
        from .assist import UNAVAILABLE_ACTIONS

        self._attr_options = list(UNAVAILABLE_ACTIONS)

    @property
    def current_option(self) -> str:
        return self.mask.state.assist_unavailable_action

    async def async_select_option(self, option: str) -> None:
        self.mask.set_assist_option(unavailable_action=option)
