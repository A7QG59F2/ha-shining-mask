"""Preview images for the mask: uploaded DIY faces + user-supplied built-in thumbnails.

Folder layout (inside the HA config dir, never shipped with the integration):
  shining_mask/diy/<slot>.png      written automatically when a DIY image is uploaded
  shining_mask/builtin/*.png|webp  YOUR pictures of the mask's built-in images/animations.
      Names map by the last number in the file name; names containing "anim" are animations:
        3.png, image_03.png  -> built-in image 3
        anim_2.png, animation2.webp -> built-in animation 2
Served (read-only) at /shining_mask/diy/... and /shining_mask/builtin/...
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from homeassistant.core import HomeAssistant

ROOT = "shining_mask"
URL_ROOT = "/shining_mask"
IMAGE_EXTS = {".png", ".webp", ".jpg", ".jpeg", ".gif"}
DATA_STATIC = "shining_mask_static_registered"
PREVIEW_SCALE = 6


def root(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(ROOT))


def diy_dir(hass: HomeAssistant) -> Path:
    return root(hass) / "diy"


def builtin_dir(hass: HomeAssistant) -> Path:
    return root(hass) / "builtin"


async def async_register_static(hass: HomeAssistant) -> None:
    """Serve the two preview folders once per HA run."""
    if hass.data.get(DATA_STATIC):
        return
    from homeassistant.components.http import StaticPathConfig

    def _mk() -> None:
        diy_dir(hass).mkdir(parents=True, exist_ok=True)
        builtin_dir(hass).mkdir(parents=True, exist_ok=True)

    await hass.async_add_executor_job(_mk)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(f"{URL_ROOT}/diy", str(diy_dir(hass)), False),
            StaticPathConfig(f"{URL_ROOT}/builtin", str(builtin_dir(hass)), False),
        ]
    )
    hass.data[DATA_STATIC] = True


def save_diy_preview(hass: HomeAssistant, slot: int, canvas) -> None:
    """Save an upscaled PNG of a 46x58 frame (blocking; run in executor)."""
    from PIL import Image

    d = diy_dir(hass)
    d.mkdir(parents=True, exist_ok=True)
    big = canvas.resize((canvas.width * PREVIEW_SCALE, canvas.height * PREVIEW_SCALE), Image.Resampling.NEAREST)
    big.save(d / f"{slot}.png")


@dataclass
class BuiltinPic:
    kind: str  # "image" | "animation"
    number: int | None
    path: Path

    @property
    def url(self) -> str:
        return f"{URL_ROOT}/builtin/{self.path.name}"


_NUM = re.compile(r"(\d+)")


def scan_builtin(hass: HomeAssistant) -> list[BuiltinPic]:
    """Blocking scan of the builtin folder."""
    out: list[BuiltinPic] = []
    d = builtin_dir(hass)
    if not d.is_dir():
        return out
    for f in sorted(d.iterdir()):
        if f.suffix.lower() not in IMAGE_EXTS or not f.is_file():
            continue
        stem = f.stem.lower()
        nums = _NUM.findall(stem)
        kind = "animation" if "anim" in stem else "image"
        out.append(BuiltinPic(kind, int(nums[-1]) if nums else None, f))
    return out


def scan_diy(hass: HomeAssistant) -> dict[int, Path]:
    d = diy_dir(hass)
    if not d.is_dir():
        return {}
    return {int(f.stem): f for f in d.glob("*.png") if f.stem.isdigit()}


def find_builtin(hass: HomeAssistant, kind: str, number: int) -> Path | None:
    for pic in scan_builtin(hass):
        if pic.kind == kind and pic.number == number:
            return pic.path
    return None


def _card(image_url: str, action: str, data: dict, entity_id: str, label: str) -> dict:
    return {
        "type": "picture",
        "image": image_url,
        "alt_text": label,
        "tap_action": {
            "action": "perform-action",
            "perform_action": action,
            "target": {"entity_id": entity_id},
            "data": data,
        },
    }


def build_dashboard(hass: HomeAssistant, entity_id: str, slot_names: dict[int, str], blank_slot: int) -> tuple[dict, list[str]]:
    """Blocking: build a Lovelace vertical-stack card; returns (card, unassigned file names)."""
    diy = scan_diy(hass)
    builtin = scan_builtin(hass)
    sections = []

    diy_cards = [
        _card(f"{URL_ROOT}/diy/{slot}.png", "shining_mask.play_diy", {"slots": str(slot)}, entity_id,
              slot_names.get(slot, f"Slot {slot}"))
        for slot in sorted(diy)
        if slot != blank_slot
    ]
    if diy_cards:
        sections += [{"type": "heading", "heading": "My faces"}, {"type": "grid", "columns": 4, "square": True, "cards": diy_cards}]

    for kind, title, action, field in (
        ("image", "Built-in images", "shining_mask.show_image", "image"),
        ("animation", "Built-in animations", "shining_mask.show_animation", "animation"),
    ):
        pics = sorted((p for p in builtin if p.kind == kind and p.number is not None), key=lambda p: p.number)
        if pics:
            cards = [_card(p.url, action, {field: p.number}, entity_id, f"{title[:-1]} {p.number}") for p in pics]
            sections += [{"type": "heading", "heading": title}, {"type": "grid", "columns": 4, "square": True, "cards": cards}]

    unassigned = [p.path.name for p in builtin if p.number is None]
    return {"type": "vertical-stack", "cards": sections}, unassigned
