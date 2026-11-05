"""Constants for Shining Mask."""

DOMAIN = "shining_mask"

CONF_DISCONNECT_AFTER = "disconnect_after"
CONF_PIXEL_ORDER = "pixel_order"
CONF_MAX_IMAGE = "max_image"
CONF_MAX_ANIMATION = "max_animation"

DEFAULT_DISCONNECT_AFTER = 0  # seconds; 0 = stay connected (lowest latency for a voice face)
DEFAULT_PIXEL_ORDER = "column"
DEFAULT_MAX_IMAGE = 60
DEFAULT_MAX_ANIMATION = 60

TEXT_MODES = {
    "steady": 1,
    "blink": 2,
    "scroll_left": 3,
    "scroll_right": 4,
}
