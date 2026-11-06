"""Preview images for the mask: uploaded DIY faces + user-supplied built-in thumbnails.

Folder layout (inside the HA config dir, never shipped with the integration):
  shining_mask/diy/<slot>.png      written automatically when a DIY image is uploaded
  shining_mask/builtin/*.png|webp  YOUR pictures of the mask's built-in images/animations.
      Names map by the last number in the file name. GIFs (or names containing "anim") are animations:
        3.bmp, 3.png, image_03.png  -> built-in image 3
        3.gif, anim_3.png           -> built-in animation 3
Served (read-only) at /shining_mask/diy/... and /shining_mask/builtin/...
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from homeassistant.core import HomeAssistant

ROOT = "shining_mask"
URL_ROOT = "/shining_mask"
IMAGE_EXTS = {".png", ".webp", ".jpg", ".jpeg", ".gif", ".bmp"}
DATA_STATIC = "shining_mask_static_registered"
PREVIEW_SCALE = 6


def root(hass: HomeAssistant) -> Path:
    """The integration's folder in /config (shining_mask), created if missing."""
    return Path(hass.config.path(ROOT))


def diy_dir(hass: HomeAssistant) -> Path:
    """Where previews of uploaded DIY slots are kept (<slot>.png)."""
    return root(hass) / "diy"


def builtin_dir(hass: HomeAssistant) -> Path:
    """Where you put pictures of the built-in images (N.bmp) and animations (N.gif)."""
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
            # the picture-uploader panel's code
            StaticPathConfig(f"{URL_ROOT}/frontend", str(Path(__file__).parent / "frontend"), False),
        ]
    )
    hass.data[DATA_STATIC] = True
    await _register_panel(hass)


async def _register_panel(hass: HomeAssistant) -> None:
    """Sidebar panel 'Mask pictures': crop any photo and send it to the mask (admins only)."""
    from homeassistant.components import panel_custom

    js = Path(__file__).parent / "frontend" / "mask-uploader.js"
    stamp = int((await hass.async_add_executor_job(js.stat)).st_mtime)  # browser cache-buster
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="shining-mask-uploader",
        frontend_url_path="shining-mask",
        module_url=f"{URL_ROOT}/frontend/mask-uploader.js?v={stamp}",
        sidebar_title="Mask pictures",
        sidebar_icon="mdi:drama-masks",
        require_admin=True,
        config={},
    )


def save_diy_preview(hass: HomeAssistant, slot: int, canvas) -> None:
    """Save an upscaled PNG of a 46x58 frame (blocking; run in executor)."""
    from PIL import Image

    d = diy_dir(hass)
    d.mkdir(parents=True, exist_ok=True)
    big = canvas.resize((canvas.width * PREVIEW_SCALE, canvas.height * PREVIEW_SCALE), Image.Resampling.NEAREST)
    big.save(d / f"{slot}.png")


@dataclass
class BuiltinPic:
    """One picture found in the builtin folder: what it shows (image/animation N) and its URL."""
    kind: str  # "image" | "animation"
    number: int | None
    path: Path

    rel: str = ""

    @property
    def url(self) -> str:
        from urllib.parse import quote

        return f"{URL_ROOT}/builtin/{quote(self.rel or self.path.name)}"


_NUM = re.compile(r"(\d+)")


def scan_builtin(hass: HomeAssistant) -> list[BuiltinPic]:
    """Blocking scan of the builtin folder."""
    out: list[BuiltinPic] = []
    d = builtin_dir(hass)
    if not d.is_dir():
        return out
    for f in sorted(d.rglob("*")):  # subfolders included
        if f.suffix.lower() not in IMAGE_EXTS or not f.is_file():
            continue
        stem = f.stem.lower()
        nums = _NUM.findall(stem)
        # GIFs are animations (e.g. 3.gif = built-in animation 3); so is anything named "anim..."
        kind = "animation" if (f.suffix.lower() == ".gif" or "anim" in stem) else "image"
        out.append(BuiltinPic(kind, int(nums[-1]) if nums else None, f, f.relative_to(d).as_posix()))
    return out


def scan_diy(hass: HomeAssistant) -> dict[int, Path]:
    """Slot number -> preview file for every DIY preview saved so far."""
    d = diy_dir(hass)
    if not d.is_dir():
        return {}
    return {int(f.stem): f for f in d.glob("*.png") if f.stem.isdigit()}


def find_builtin(hass: HomeAssistant, kind: str, number: int) -> Path | None:
    """Preview file for built-in image or animation N, if you've added one."""
    for pic in scan_builtin(hass):
        if pic.kind == kind and pic.number == number:
            return pic.path
    return None


def _card(image_url: str, action: str, data: dict, entity_id: str, label: str) -> dict:
    """One tap-to-show picture card for the dashboard grid."""
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


def build_dashboard(
    hass: HomeAssistant, entity_id: str, slot_names: dict[int, str], blank_slot: int, columns: int = 4
) -> tuple[dict, list[str]]:
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
        sections += [{"type": "heading", "heading": "My faces"}, {"type": "grid", "columns": columns, "square": True, "cards": diy_cards}]

    for kind, title, action, field in (
        ("image", "Built-in images", "shining_mask.show_image", "image"),
        ("animation", "Built-in animations", "shining_mask.show_animation", "animation"),
    ):
        pics = sorted((p for p in builtin if p.kind == kind and p.number is not None), key=lambda p: p.number)
        if pics:
            cards = [_card(p.url, action, {field: p.number}, entity_id, f"{title[:-1]} {p.number}") for p in pics]
            sections += [{"type": "heading", "heading": title}, {"type": "grid", "columns": columns, "square": True, "cards": cards}]

    unassigned = [p for p in builtin if p.number is None]
    if unassigned:
        # shown so you can see them; rename to 3.png / anim_2.png etc. to make them tappable
        cards = [{"type": "picture", "image": p.url, "alt_text": p.rel, "tap_action": {"action": "none"}} for p in unassigned[:120]]
        sections += [
            {"type": "heading", "heading": "Unsorted (rename with a number to make tappable)"},
            {"type": "grid", "columns": columns + 2, "square": True, "cards": cards},
        ]
    return {"type": "vertical-stack", "cards": sections}, [p.rel for p in unassigned]
