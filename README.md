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
   - idle → slot 1, listening → slot 2, thinking → slot 3
   - **talking → slots `4,5` cycling** (a flapping mouth), with adjustable speed
   - unavailable → slot 6

Any state can use a built-in image or animation instead (kind = image/animation).

## Options
- **Disconnect after idle seconds**: 0 (default) keeps the link open for instant face changes.
  Set this to e.g. 60 to save mask battery or free a proxy slot.
- **Pixel order**: see step 5.1.
- **Max image/animation**: range limits for the number entities.

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
