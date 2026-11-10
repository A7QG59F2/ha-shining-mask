# Changelog

All notable changes. Versions follow semver: new features bump the minor number, fixes bump the patch number.

## 0.29.0 - 2026-11-10
- Releases are published automatically: a GitHub Action creates a release (with these notes) whenever the version changes.

## 0.28.3 - 2026-11-10
- Added this changelog and the remaining code comments.
- Earlier: mask loads even without internet (0.28.2), stretch/skew controls (0.28.1), Shining Mask sidebar panel with all settings (0.28.0).

## 0.28.2 - 2026-11-10
- Mask loads even without internet: music-visualizer library installed on demand, in the background

## 0.28.1 - 2026-11-06
- Pictures tab: stretch and skew controls

## 0.28.0 - 2026-11-06
- Sidebar panel 'Shining Mask': Settings tab with every setting + Pictures tab

## 0.27.0 - 2026-11-06
- Mask pictures sidebar panel: crop/zoom/adjust any photo with live LED preview and upload; upload_image auto slot + response

## 0.26.0 - 2026-11-06
- upload_image accepts base64 image data (no file in /config needed)

## 0.25.1 - 2026-11-06
- Built-in images stop at 69 (70+ is leftover data on a real mask)

## 0.25.0 - 2026-11-06
- set_pack_role action: trim face-pack roles and free their slots

## 0.24.0 - 2026-11-06
- DIY slot allocator: clocks and effects take the least-needed slots, never the face pack or blank frame

## 0.23.0 - 2026-11-06
- Digit-flip clock style (no per-minute uploads); shared slot pool for digits and on-demand effects

## 0.22.0 - 2026-11-06
- Use brickcraftdream protocol notes: image/animation ranges 105/69, effect frames max 10 (PLAY limit), text width cap, descriptive text effect names

## 0.21.0 - 2026-11-06
- Built-in assistant faces: satellite + per-state face settings on the mask; blueprint removed

## 0.20.0 - 2026-11-06
- Clock: time moved up 7 px, colour themes, Animated/Still motion

## 0.19.1 - 2026-11-06
- Clock moved to DIY slots 31-34 (mask stores 1-34 only); slot range checks; Matrix defaults to 8 frames in 1-8

## 0.19.0 - 2026-11-06
- Clock screen (sun/moon sky, weather, 24h time, temperature, date) as a chosen face; reset_mask action

## 0.18.0 - 2026-11-06
- Matrix digital-rain effect: install_effect action uploads a seamless loop to DIY slots

## 0.17.1 - 2026-11-06
- Assistant faces hold the music bars by themselves (works with older blueprints); hold_music option; holding attribute

## 0.17.0 - 2026-11-06
- Gesture faces picker (per library, any length, multi-packet like the app), settings card row; docstrings throughout

## 0.16.0 - 2026-11-06
- Settings grouped into sections (Face, Text, Visualizer, Gesture) plus an ordered settings card; generic Bluetooth wording

## 0.15.0 - 2026-11-06
- Screen priority: assistant face > music bars > chosen face; music stop goes straight to the chosen face

## 0.14.1 - 2026-11-06
- Assistant face now beats the music bars: exit bar mode before the face, block queued frames

## 0.14.0 - 2026-11-06
- Music bars style is now a named dropdown: Rainbow, Warm, Cool, Mirror, Vertical

## 0.13.3 - 2026-11-06
- Music bars style back to 0-4: the mask has five styles

## 0.13.2 - 2026-11-06
- Music bars style range 0-5, matching the app's six styles

## 0.13.1 - 2026-11-06
- Limit music bars style to 0-4 (style 5+ freezes the mask firmware)

## 0.13.0 - 2026-11-06
- Assistant face takes precedence over music bars: set_music_hold action + blueprint hold

## 0.12.0 - 2026-11-06
- Music bars EQ: sensitivity, contrast, bass/mid/treble; slower auto-gain + noise gate so bars sit lower

## 0.11.0 - 2026-11-06
- Music bars from Music Assistant via Sendspin visualizer@v1: music visualizer switch, bars style and delay

## 0.10.1 - 2026-11-05
- Fix: send rhythm visualiser frames on the 960b characteristic, as the app does

## 0.10.0 - 2026-11-05
- Gesture face switch matching the app: switch + library/circulation selects, picked items

## 0.9.0 - 2026-11-05
- Animation loop, rhythm visualiser frames, stop rhythm, experimental gesture face-change; background colour uses confirmed BC

## 0.8.0 - 2026-11-05
- App text settings: text colour, background colour, text effects (gradients/background animations), persisted

## 0.7.1 - 2026-11-05
- Fix: allow face packs/images anywhere inside the config folder; find packs in /config/shining_mask/assistant_face too

## 0.7.0 - 2026-11-05
- Assistant face packs: install_face_pack from /config/assistant_face/<folder>, role detection, pixel-exact fit; blueprint 'pack' kind

## 0.6.0 - 2026-11-05
- Blueprint: idle returns to the chosen face by default; optional return-after seconds

## 0.5.0 - 2026-11-05
- Persist chosen face/state across restarts; blueprint unavailable timeout in seconds

## 0.4.0 - 2026-11-05
- Remember the user-chosen face; restore_selected action; blueprint: unavailable timeout then off/restore

## 0.3.1 - 2026-11-05
- Treat .gif files in the builtin folder as animations

## 0.3.0 - 2026-11-05
- Switched to semantic version numbers.

## 0.2.3 - 2026-11-05
- BMP thumbnails; generate_dashboard writes a full panel view too; columns option

## 0.2.2 - 2026-11-05
- Dashboard: scan builtin subfolders, show unnumbered pictures in an Unsorted section, report counts

## 0.2.1 - 2026-11-05
- Lower default max brightness to 128

## 0.2.0 - 2026-11-04
- Face previews: current-face image entity, DIY preview PNGs, user-supplied built-in thumbnails, generate_dashboard tap-to-show grid

## 0.1.3 - 2026-11-04
- Brightness capped/scaled to mask range (default 160), real off via blank DIY frame, restore face on
- README: troubleshooting for non-connectable proxies (2026-11-04)

## 0.1.2 - 2026-11-04
- Robust command channel: GATT cache retry, fallback characteristic, write-mode retry, diagnostics

## 0.1.1 - 2026-11-04
- Config flow: list all candidate devices, flag non-connectable proxies, allow manual address

## 0.1.0 - 2026-11-04
- Initial Shining Mask integration for Home Assistant

