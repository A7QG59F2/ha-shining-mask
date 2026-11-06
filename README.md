# Shining Mask for Home Assistant

Control a "Shining Mask" app LED mask from Home Assistant over Bluetooth, via any
connectable Bluetooth proxy (here a **TECHO5 Echo Show**), and give a voice
satellite a face.

## 1. Prepare the TECHO5 Show as a Bluetooth proxy
1. Update TECHO5 to **v1.6.10 or newer** (proxy connections need 1.6.8+, and an API encryption key is required since 1.6.10).
2. In the Show's ESPHome device page in HA, turn on **Bluetooth proxy connections**.
   The Show lends up to **3** active connections; this mask uses 1 while connected.
3. Keep the mask within a few metres of the Show for the first setup.

## 2. Install
- **HACS:** add this repo as a custom repository (type Integration), install, restart HA.
- **Manual:** copy `custom_components/shining_mask` into `/config/custom_components/`, restart HA.

Turn the mask on. It advertises as `MASK-xxxx` and HA should discover it
(Settings → Devices & services). Otherwise click **Add integration → Shining Mask**.
**Close the phone app first.** The mask accepts only one connection at a time.

## 3. Entities
| Entity | What it does |
|---|---|
| `light.mask_…` | On/off + brightness (off = brightness 0) |
| `number.…_image` | Show built-in image N |
| `number.…_animation` | Play built-in animation N |
| `number.…_speed` | Animation/DIY/text speed |
| `select.…_text_mode` | steady / blink / scroll left / scroll right |
| `text.…_text` | Type text to upload and show it |
| `light.…_text_color` | Text colour (on = custom colour, colour picker = colour) |
| `light.…_text_background_color` | Background colour behind text |
| `select.…_text_effect` | `solid`, `gradient_1`–`4` (text gradients), `background_1`–`4` (animated backgrounds) |

State is *assumed* (the mask doesn't report back), so the entities show the last value you sent.

## 4. Actions (target the mask's light entity)
`shining_mask.show_image`, `show_animation`, `play_diy`, `show_face`, `set_text`,
`upload_image` (file under /config or a built-in face), `install_default_faces`,
`delete_diy`, `send_command` (raw, for experimenting).

## 5. Give the voice assistant a face
1. Check orientation first. Run `shining_mask.upload_image` with `slot: 8, builtin: test_pattern`,
   then `shining_mask.play_diy` with `slots: "8"`. You should see **red top-left, green top-right,
   blue bottom-left, and a white arrow pointing up**. If it's scrambled or rotated, switch
   *Pixel order* to `row` in the integration options and try again.
2. Run **`shining_mask.install_default_faces`**. This writes slots 1–7:
   1 idle · 2 listening · 3 thinking · 4 talk (closed) · 5 talk (open) · 6 error · 7 sleep.
3. Import the blueprint `blueprints/automation/shining_mask/voice_face.yaml`
   (copy it to `/config/blueprints/automation/shining_mask/`), then create an automation from it.
   Pick the Show's `assist_satellite` entity and the mask.
   - idle (finished speaking) → back to the face you picked yourself (or a fixed face, optionally
     returning to your face after N seconds); listening → slot 2, thinking → slot 3
   - **talking → slots `4,5` cycling** (a flapping mouth), with adjustable speed
   - unavailable → slot 6, then after **N seconds** (default 180) either go black (`off`) or
     go back to the face you last picked yourself (`restore`, the default)

   Voice faces are shown as *temporary*, so they never replace your chosen face. Your choice
   (dashboard tap, Image/Animation number, or an action) is in the light's `selected_face`
   attribute, and `shining_mask.restore_selected` brings it back. It is remembered across restarts.

Any state can use a built-in image or animation instead (kind = image/animation).

## 6. Your own assistant face (face packs)
1. Put a folder of frames in `/config/assistant_face/<name>/` or `/config/shining_mask/assistant_face/<name>/`.
   File names choose the role: `idle`, `listen`, `think`, `talk`/`speak` (several frames cycle in name
   order), `error`/`sad`, `sleep`. Plain numbered frames (`1.bmp`, `2.bmp`, …): frame 1 is idle and
   all frames cycle while talking. Missing roles fall back to idle.
2. Run `shining_mask.install_face_pack` with `folder: "1"` (tick *return response* to see which
   frame went to which slot). Frames go into DIY slots from 10 up (`start_slot`). `fit: auto` keeps
   pixel art 1:1, centred, for frames drawn for the mask.
3. In the voice-face automation, set the Listening / Thinking / Talking / Unavailable kinds (and Idle
   if you like) to `pack`.

## 7. Face previews and a tap-to-show grid
- **`image.…_current_face`** shows what the mask is displaying: your DIY faces, plus built-in
  images and animations if you supply pictures of them.
- **Built-in thumbnails:** put pictures (photos of the mask or app screenshots, kept for your own
  use only) in `/config/shining_mask/builtin/`. The last number in a file name sets the number, and
  GIFs (or names containing `anim`) are animations: `3.bmp` or `3.png` maps to image 3;
  `3.gif` (or `anim_3.png`) maps to animation 3. GIF thumbnails play in the dashboard.
- **DIY previews** are saved automatically to `/config/shining_mask/diy/<slot>.png` whenever you upload.
- Run **`shining_mask.generate_dashboard`** (tick *return response* in Developer tools) to build a card
  with headings and 4-wide grids of thumbnails. Tapping one shows it on the mask. The card is written
  to `/config/shining_mask/dashboard_card.yaml`. Paste it into a dashboard via *Add card → Manual*.
  Re-run it after adding pictures.
- Preview files are served read-only at `/shining_mask/diy/…` and `/shining_mask/builtin/…`.

## More app features
- `shining_mask.loop_animations`: cycle through all built-in animations (the app's loop mode).
- `shining_mask.rhythm`: music-rhythm visualiser bars. Each frame is 12 levels 0–15; separate frames
  with `;`. `mode` picks the rhythm effect. `shining_mask.stop_rhythm` returns to the previous face.
- **Gesture face switch** (the app's gesture page): `switch.…_gesture_face_switch`,
  `select.…_gesture_library` (all / gallery / diy) and `select.…_gesture_circulation` (order / random).
  To pick specific pictures for gallery or DIY, use `shining_mask.set_gesture` with `items: "1,2,3"`
  (up to 7).
- Text background colour now uses the confirmed `BC` command.

## Music bars from Music Assistant (Sendspin visualizer)
Music Assistant (2.9+) works out each song's spectrum and beats and streams them, in time with
playback, to Sendspin "visualizer" clients. The mask can be one of those clients:
1. Turn on `switch.…_music_visualizer`. The mask advertises itself on your network as a Sendspin
   visualizer (port 8928, changeable in the integration options).
2. In Music Assistant, approve the new **"MASK-… (mask)"** Sendspin client if it asks.
3. Group it with the player you're listening to (a Sendspin player or a bridged speaker).
   When that player plays, the mask shows the bars; about 2 s after the music stops, its face returns.
- `select.…_music_bars_style`: Rainbow, Warm, Cool, Mirror or Vertical.
- `number.…_music_bars_delay`: shift the bars later (+) or earlier (−) if they don't line up with
  what you hear (e.g. a speaker that adds its own delay).
- **The assistant face always wins:** the voice-face blueprint pauses the bars while the assistant is
  listening, thinking or talking (`shining_mask.set_music_hold`), and they resume when it goes idle.
- **EQ:** `…_music_bars_sensitivity` (overall height), `…_music_bars_contrast` (higher = quiet bands
  drop further, peaks still reach the top), and `…_music_bars_bass` / `_mid` / `_treble`
  (bars 1–4 / 5–8 / 9–12). All apply live while music plays.

## Options
- **Disconnect after idle seconds**: 0 (default) keeps the link open for instant face changes.
  Set this to e.g. 60 to save mask battery or free a proxy slot.
- **Pixel order**: see step 5.1.
- **Max image/animation**: range limits for the number entities.

## Troubleshooting
- **"Not in range of any connectable Bluetooth adapter or proxy"**: HA hears the mask only through a
  listen-only path. Open Settings → Devices & services → Bluetooth → Configure → *Advertisement monitor*
  and find `MASK-xxxxxx`. If `connectable` is `false`, the proxy (`source`) isn't allowing connections.
  On TECHO5, turn on the **Bluetooth proxy connections** toggle, power-cycle the mask, and wait until
  the monitor shows `connectable: true`.
- **Setup finds no masks**: the setup screen lists every named nearby device and has a manual-address option.
- **Commands fail after connecting**: the mask light entity's `last_error` and `gatt` attributes show
  the real Bluetooth error and the mask's GATT table.
- Keep the mask within a couple of metres of the proxy for setup. Around -77 dBm, a proxy can still
  hear it but connecting may fail.

## Testing from a PC (optional)
`tools/mask_cli.py` speaks the same protocol directly with `bleak`:
`python tools/mask_cli.py upload 8 test_pattern`, `… text "Boo"`, `… image 5`.

## Protocol credits
mjg59 and others (r/ReverseEngineering), GoneUp/mask-go, beclamide/mask-controller,
shawnrancatore/shining-mask, bishopfox/shining-mask.

## Notes / unverified
- The DIY frame is 8004 bytes (46×58 RGB, inferred from Bishop Fox's upload). Pixel order is the one unverified detail; that's what the test pattern checks.
- Speed direction (higher = faster or slower) and the number of built-in images/animations vary by mask firmware.
- Only control your own mask. The protocol has no pairing, so the integration only talks to the address you set up.
