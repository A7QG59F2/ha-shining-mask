"""Constants for Shining Mask."""

DOMAIN = "shining_mask"

CONF_DISCONNECT_AFTER = "disconnect_after"
CONF_PIXEL_ORDER = "pixel_order"
CONF_MAX_IMAGE = "max_image"
CONF_MAX_ANIMATION = "max_animation"
CONF_MAX_BRIGHTNESS = "max_brightness"
CONF_BLANK_SLOT = "blank_slot"

DEFAULT_DISCONNECT_AFTER = 0  # seconds; 0 = stay connected (lowest latency for a voice face)
DEFAULT_PIXEL_ORDER = "column"
DEFAULT_MAX_IMAGE = 60
DEFAULT_MAX_ANIMATION = 60
DEFAULT_MAX_BRIGHTNESS = 128  # 0x80 tested clean; slight flicker reported at 160, strong at 200
DEFAULT_BLANK_SLOT = 9  # DIY slot holding an all-black frame, used for "off"
CLOCK_FIRST_SLOT = 46  # clock screen uses DIY slots 46-49 (two frames x two buffers)

TEXT_MODES = {
    "steady": 1,
    "blink": 2,
    "scroll_left": 3,
    "scroll_right": 4,
}

# "M" command: 0-3 text gradients, 4-7 background animations
TEXT_EFFECTS = {
    "solid": None,
    "gradient_1": 0,
    "gradient_2": 1,
    "gradient_3": 2,
    "gradient_4": 3,
    "background_1": 4,
    "background_2": 5,
    "background_3": 6,
    "background_4": 7,
}

CONF_VISUALIZER_PORT = "visualizer_port"
DEFAULT_VISUALIZER_PORT = 8928

# music-bars (rhythm) styles, mode byte 0-4
BAR_STYLES = {"Rainbow": 0, "Warm": 1, "Cool": 2, "Mirror": 3, "Vertical": 4}
