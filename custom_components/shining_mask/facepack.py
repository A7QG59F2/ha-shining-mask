"""Assistant face packs: a folder of frames turned into idle/listening/thinking/talking/error roles.

Folder: /config/assistant_face/<name>/   (pass the name, e.g. "1", or a full path)
Role from file name (case-insensitive, first match wins):
  idle | neutral | default | rest   -> idle
  listen | hear | ear                -> listening
  think | process | wait | load      -> thinking
  talk | speak | mouth | say         -> talking   (several frames cycle, in name order)
  error | sad | unavail | offline    -> error
  sleep | off | night                -> sleep
Plain numbered files (1.bmp, 2.bmp, ...) with no keywords: frame 1 = idle and
all frames cycle while talking. Missing roles fall back to idle.
"""

from __future__ import annotations

from pathlib import Path
import re

from homeassistant.core import HomeAssistant

PACK_ROOT = "assistant_face"
IMAGE_EXTS = {".png", ".bmp", ".gif", ".jpg", ".jpeg", ".webp"}
MAX_FRAMES_PER_ROLE = 10  # PLAY takes at most 10 slots
ROLES = ("idle", "listening", "thinking", "talking", "error", "sleep")
_KEYWORDS = (
    ("listening", ("listen", "hear", "ear")),
    ("thinking", ("think", "process", "wait", "load")),
    ("talking", ("talk", "speak", "mouth", "say")),
    ("error", ("error", "sad", "unavail", "offline")),
    ("sleep", ("sleep", "night", "off")),
    ("idle", ("idle", "neutral", "default", "rest")),
)


def _natural_key(p: Path):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", p.stem.lower())]


def resolve_folder(hass: HomeAssistant, folder: str) -> Path:
    p = Path(folder)
    return p if p.is_absolute() else Path(hass.config.path(PACK_ROOT, folder))


def list_packs(hass: HomeAssistant) -> list[str]:
    root = Path(hass.config.path(PACK_ROOT))
    return sorted((d.name for d in root.iterdir() if d.is_dir()), key=lambda n: _natural_key(Path(n))) if root.is_dir() else []


def plan_pack(folder: Path) -> dict[str, list[Path]]:
    """Blocking: assign frames to roles."""
    files = sorted((f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS), key=_natural_key)
    if not files:
        raise FileNotFoundError(f"No images in {folder}")
    roles: dict[str, list[Path]] = {r: [] for r in ROLES}
    unmatched = []
    for f in files:
        stem = f.stem.lower()
        for role, words in _KEYWORDS:
            if any(w in stem for w in words):
                roles[role].append(f)
                break
        else:
            unmatched.append(f)
    if not any(roles.values()):
        # plain numbered frames
        roles["idle"] = [files[0]]
        roles["talking"] = files[:MAX_FRAMES_PER_ROLE]
    else:
        # leftovers without keywords join the talking cycle if it is empty, otherwise idle if empty
        if unmatched and not roles["talking"]:
            roles["talking"] = unmatched
        elif unmatched and not roles["idle"]:
            roles["idle"] = unmatched[:1]
    if not roles["idle"]:
        roles["idle"] = [(roles["talking"] or files)[0]]
    return {r: v[:MAX_FRAMES_PER_ROLE] for r, v in roles.items() if v}
