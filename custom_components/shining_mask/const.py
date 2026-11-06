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
# Built-in ids that show real content (higher ids show out-of-bounds data), per
# brickcraftdream/shining-mask-stuff: images up to 0x69, animations up to 0x45.
DEFAULT_MAX_IMAGE = 105
DEFAULT_MAX_ANIMATION = 69
# PLAY takes at most 10 DIY slots, so a DIY animation has at most 10 frames.
MAX_PLAY_SLOTS = 10
# Text bitmaps much wider than this can hang the mask until its battery is pulled.
MAX_TEXT_COLUMNS = 512
DEFAULT_MAX_BRIGHTNESS = 128  # 0x80 tested clean; slight flicker reported at 160, strong at 200
DEFAULT_BLANK_SLOT = 9  # DIY slot holding an all-black frame, used for "off"
# The mask refuses DIY uploads above slot 34 (tested: 34 accepted, 35 and up get no DATSOK).
MAX_DIY_SLOT = 34
# Which slots the clock and effects use is decided by ShiningMask.allocate_slots.

TEXT_MODES = {
    "steady": 1,
    "blink": 2,
    "scroll_left": 3,
    "scroll_right": 4,
}

# "M" command: 0-3 colour effects on the text, 4-7 built-in background pictures behind it.
# Descriptions from brickcraftdream/shining-mask-stuff (ble-protocol.md).
TEXT_EFFECTS = {
    "solid": None,
    "dots_on_white": 0,  # random colour dots on white
    "rainbow_edges": 1,  # rainbow top/bottom edges, red -> purple left to right
    "yellow_to_blue": 2,  # fade yellow (top) to blue (bottom)
    "green_blue_circle": 3,  # green at the sides to blue in the middle
    "background_1": 4,
    "background_2": 5,
    "background_3": 6,
    "background_4": 7,
}

CONF_VISUALIZER_PORT = "visualizer_port"
DEFAULT_VISUALIZER_PORT = 8928

# music-bars (rhythm) styles, mode byte 0-4
BAR_STYLES = {"Rainbow": 0, "Warm": 1, "Cool": 2, "Mirror": 3, "Vertical": 4}
