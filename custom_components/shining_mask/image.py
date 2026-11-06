"""'Current face' image entity: shows what the mask is (assumed to be) displaying."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import MaskConfigEntry
from .entity import MaskEntity
from .previews import diy_dir, find_builtin

_CONTENT_TYPES = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".bmp": "image/bmp"}


async def async_setup_entry(hass: HomeAssistant, entry: MaskConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([MaskCurrentFace(hass, entry.runtime_data)])


class MaskCurrentFace(MaskEntity, ImageEntity):
    _attr_name = "Face now showing"
    _attr_icon = "mdi:face-man-shimmer"

    def __init__(self, hass: HomeAssistant, mask) -> None:
        MaskEntity.__init__(self, mask, "current_face")
        ImageEntity.__init__(self, hass)
        self._key: tuple | None = None
        self._attr_image_last_updated = dt_util.utcnow()

    def _current_key(self) -> tuple:
        s = self.mask.state
        if not s.is_on:
            return ("off",)
        if s.diy:
            return ("diy", s.diy[0], self.mask.preview_version)
        if s.animation is not None:
            return ("animation", s.animation)
        if s.image is not None:
            return ("image", s.image)
        return ("none",)

    @callback
    def _changed(self) -> None:
        key = self._current_key()
        if key != self._key:
            self._key = key
            self._attr_image_last_updated = dt_util.utcnow()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._key = self._current_key()
        self.async_on_remove(self.mask.async_add_listener(self._changed))

    def _path(self) -> Path | None:
        key = self._current_key()
        if key[0] == "diy":
            p = diy_dir(self.hass) / f"{key[1]}.png"
            return p if p.is_file() else None
        if key[0] in ("image", "animation"):
            return find_builtin(self.hass, key[0], key[1])
        return None

    def _read(self) -> tuple[bytes | None, str]:
        path = self._path()
        if path is None:
            return None, "image/png"
        return path.read_bytes(), _CONTENT_TYPES.get(path.suffix.lower(), "image/png")

    async def async_image(self) -> bytes | None:
        data, ctype = await self.hass.async_add_executor_job(self._read)
        self._attr_content_type = ctype
        return data

    @property
    def extra_state_attributes(self):
        key = self._current_key()
        return {"showing": " ".join(str(k) for k in key[:2])}
