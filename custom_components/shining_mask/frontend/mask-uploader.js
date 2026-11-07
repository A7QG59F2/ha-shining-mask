// Shining Mask sidebar panel: a Settings tab with every mask setting (real Home Assistant
// entity rows, laid out by the integration via the shining_mask/layout websocket command),
// and a Pictures tab, the photo uploader:
// Pick, drop or paste any picture, drag/zoom it into the mask outline (eye holes and the
// LED-less bottom corners are shown), tune brightness/contrast/colour while watching a live
// 46x58 LED preview, then send it to the mask. The 46x58 frame is rendered here in the browser
// and uploaded as base64 PNG through shining_mask.upload_image, so no file ever needs to be
// copied to /config.

const W = 46, H = 58;
const EYES = [[12.5, 18.5], [32.5, 18.5]], EYE_RX = 5.6, EYE_RY = 3.4;

// LEDs that exist: not in the eye holes, not in the cut-off bottom corners
function ledExists(x, y) {
  if (y > 46 && (x < y - 46 || x > 45 - (y - 46))) return false;
  return !EYES.some(([ex, ey]) => ((x - ex) / EYE_RX) ** 2 + ((y - ey) / EYE_RY) ** 2 <= 1);
}

class MaskUploader extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.img = null;
    this.view = { zoom: 1, x: 0, y: 0, rot: 0 }; // image placement on the mask, in LED units
    this.adj = { bright: 100, contrast: 100, sat: 100 };
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._fillMasks();
    for (const c of this._cards || []) c.hass = hass;
    if (!this._layoutAsked) this._loadSettings();
  }

  // Settings tab: ask the integration for each mask's settings card and render it with the
  // frontend's own card helpers, so every row is a normal Home Assistant control.
  async _loadSettings() {
    this._layoutAsked = true;
    const box = this.$("settings");
    try {
      const res = await this._hass.connection.sendMessagePromise({ type: "shining_mask/layout" });
      const helpers = await window.loadCardHelpers();
      box.innerHTML = "";
      this._cards = [];
      for (const m of res.masks) {
        if (res.masks.length > 1) box.insertAdjacentHTML("beforeend", `<h2>${m.title}</h2>`);
        // lay the sections out side by side instead of one tall stack
        const grid = document.createElement("div");
        grid.className = "grid";
        for (const sub of m.card.cards) {
          const el = helpers.createCardElement(sub);
          el.hass = this._hass;
          this._cards.push(el);
          grid.appendChild(el);
        }
        box.appendChild(grid);
      }
      if (!res.masks.length) box.textContent = "No mask set up yet.";
    } catch (err) {
      box.textContent = `Couldn't load the settings: ${err?.message || err}`;
      this._layoutAsked = false;
    }
  }

  _tab(name) {
    for (const t of ["settings", "pictures"]) {
      this.$(t).style.display = t === name ? "" : "none";
      this.$(`tab-${t}`).classList.toggle("on", t === name);
    }
  }
  set panel(p) { this._panel = p; }
  set narrow(n) { this._narrow = n; }

  // ------------------------------------------------------------------ UI
  _build() {
    this._built = true;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; padding:16px; color:var(--primary-text-color); font-family:var(--paper-font-body1_-_font-family, sans-serif); }
        h1 { font-size:22px; margin:0 0 12px; font-weight:400; }
        .wrap { display:flex; flex-wrap:wrap; gap:20px; align-items:flex-start; }
        .card { background:var(--card-background-color); border-radius:12px; padding:16px; box-shadow:var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.3)); }
        #stage { width:368px; height:464px; background:#111; border-radius:8px; touch-action:none; cursor:grab; display:block; }
        #stage.drag { cursor:grabbing; }
        #led { width:276px; height:348px; background:#080808; border-radius:8px; display:block; }
        .drop { border:2px dashed var(--divider-color); border-radius:8px; padding:14px; text-align:center; margin-bottom:12px; cursor:pointer; }
        .drop.over { border-color:var(--primary-color); }
        label { display:flex; align-items:center; gap:8px; margin:6px 0; font-size:14px; }
        label span { width:90px; }
        input[type=range] { flex:1; }
        .row { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
        button { background:var(--primary-color); color:var(--text-primary-color, #fff); border:0; border-radius:6px; padding:9px 14px; font-size:14px; cursor:pointer; }
        button.sec { background:var(--secondary-background-color); color:var(--primary-text-color); }
        button:disabled { opacity:.5; cursor:default; }
        select, input[type=text] { padding:6px; border-radius:6px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); }
        #status { margin-top:10px; font-size:14px; min-height:20px; }
        .hint { font-size:12px; color:var(--secondary-text-color); margin-top:6px; }
        .tabs { display:flex; gap:6px; margin-bottom:14px; }
        .tab { background:var(--secondary-background-color); color:var(--primary-text-color); }
        .tab.on { background:var(--primary-color); color:var(--text-primary-color, #fff); }
        .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(340px, 1fr)); gap:16px; align-items:start; }
        h2 { font-weight:400; font-size:18px; }
      </style>
      <h1>Shining Mask</h1>
      <div class="tabs"><button class="tab on" id="tab-settings">Settings</button><button class="tab" id="tab-pictures">Pictures</button></div>
      <div id="settings">Loading…</div>
      <div class="wrap" id="pictures" style="display:none">
        <div class="card">
          <div class="drop" id="drop">Drop a picture here, paste it, or <u>choose a file</u>
            <input type="file" id="file" accept="image/*" hidden></div>
          <canvas id="stage" width="368" height="464"></canvas>
          <div class="hint">Drag to move · scroll or pinch to zoom · the outline is the mask (eye holes and bottom corners have no LEDs)</div>
        </div>
        <div class="card">
          <canvas id="led" width="276" height="348"></canvas>
          <div class="hint">Live preview of the LEDs</div>
        </div>
        <div class="card" style="min-width:280px">
          <label><span>Zoom</span><input type="range" id="zoom" min="10" max="800" value="100"></label>
          <label><span>Rotate</span><input type="range" id="rot" min="-180" max="180" value="0"></label>
          <label><span>Brightness</span><input type="range" id="bright" min="20" max="200" value="100"></label>
          <label><span>Contrast</span><input type="range" id="contrast" min="20" max="250" value="100"></label>
          <label><span>Colour</span><input type="range" id="sat" min="0" max="250" value="100"></label>
          <div class="row">
            <button class="sec" id="fit">Fit</button>
            <button class="sec" id="fill">Fill</button>
            <button class="sec" id="reset">Reset colours</button>
          </div>
          <label style="margin-top:14px"><span>Mask</span><select id="mask"></select></label>
          <label><span>Name</span><input type="text" id="name" placeholder="my picture"></label>
          <label><span>Slot</span><select id="slot"><option value="">Automatic (safe)</option></select></label>
          <div class="row">
            <button id="show" disabled>Show on mask</button>
            <button id="keep" disabled>Set as chosen face</button>
          </div>
          <div class="hint">Automatic picks a slot that won't overwrite the assistant's faces.<br>
            "Show" is temporary; "Set as chosen face" makes it the face the mask returns to.</div>
          <div id="status"></div>
        </div>
      </div>`;
    const $ = (id) => this.shadowRoot.getElementById(id);
    this.$ = $;
    $("tab-settings").onclick = () => this._tab("settings");
    $("tab-pictures").onclick = () => this._tab("pictures");
    for (let s = 1; s <= 34; s++) $("slot").insertAdjacentHTML("beforeend", `<option value="${s}">${s}</option>`);

    $("drop").onclick = () => $("file").click();
    $("file").onchange = (e) => e.target.files[0] && this._load(e.target.files[0]);
    const drop = $("drop");
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
    drop.ondragleave = () => drop.classList.remove("over");
    drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); const f = e.dataTransfer.files[0]; f && this._load(f); };
    window.addEventListener("paste", (e) => {
      const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
      if (item) this._load(item.getAsFile());
    });

    for (const k of ["bright", "contrast", "sat"]) $(k).oninput = (e) => { this.adj[k] = +e.target.value; this._draw(); };
    $("zoom").oninput = (e) => { this._zoomAbout(+e.target.value / 100, W / 2, H / 2); };
    $("rot").oninput = (e) => { this.view.rot = +e.target.value; this._draw(); };
    $("fit").onclick = () => this._place(false);
    $("fill").onclick = () => this._place(true);
    $("reset").onclick = () => { this.adj = { bright: 100, contrast: 100, sat: 100 }; ["bright", "contrast", "sat"].forEach((k) => ($(k).value = 100)); this._draw(); };
    $("show").onclick = () => this._send(false);
    $("keep").onclick = () => this._send(true);

    // drag / wheel / pinch on the stage
    const st = $("stage");
    const toLed = (ev) => { const r = st.getBoundingClientRect(); return [((ev.clientX - r.left) / r.width) * W, ((ev.clientY - r.top) / r.height) * H]; };
    const pts = new Map();
    let last = null, pinch = null;
    st.onpointerdown = (e) => { st.setPointerCapture(e.pointerId); pts.set(e.pointerId, toLed(e)); st.classList.add("drag"); last = toLed(e); };
    st.onpointermove = (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, toLed(e));
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (pinch) this._zoomAbout(this.view.zoom * (d / pinch), (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
        pinch = d;
        return;
      }
      const p = toLed(e);
      if (last) { this.view.x += p[0] - last[0]; this.view.y += p[1] - last[1]; this._draw(); }
      last = p;
    };
    const up = (e) => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; if (!pts.size) { st.classList.remove("drag"); last = null; } };
    st.onpointerup = up; st.onpointercancel = up;
    st.onwheel = (e) => { e.preventDefault(); const [px, py] = toLed(e); this._zoomAbout(this.view.zoom * (e.deltaY < 0 ? 1.08 : 1 / 1.08), px, py); };
    this._draw();
  }

  // the mask's light entities (one per mask), for the Mask dropdown
  _fillMasks() {
    const sel = this.$ && this.$("mask");
    if (!sel || !this._hass) return;
    const lights = Object.keys(this._hass.states).filter((id) => id.startsWith("light.") && "selected_face" in (this._hass.states[id].attributes || {}));
    const key = lights.join(",");
    if (key === this._masksKey) return;
    this._masksKey = key;
    sel.innerHTML = lights.map((id) => `<option value="${id}">${this._hass.states[id].attributes.friendly_name || id}</option>`).join("");
  }

  _load(file) {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      this.img = img;
      if (!this.$("name").value) this.$("name").value = (file.name || "picture").replace(/\.[^.]+$/, "").slice(0, 30);
      this.view.rot = 0; this.$("rot").value = 0;
      this._place(true);
      this.$("show").disabled = this.$("keep").disabled = false;
      this._status("");
    };
    img.onerror = () => this._status("That file isn't a picture the browser can read.", true);
    img.src = url;
  }

  // fit (whole picture visible) or fill (cover the mask), centred
  _place(fill) {
    if (!this.img) return;
    const sx = W / this.img.width, sy = H / this.img.height;
    this.view.zoom = fill ? Math.max(sx, sy) : Math.min(sx, sy);
    this.view.x = W / 2; this.view.y = H / 2;
    this._syncZoom();
    this._draw();
  }

  _zoomAbout(z, px, py) {
    if (!this.img) return;
    const base = Math.min(W / this.img.width, H / this.img.height);
    z = Math.min(Math.max(z, base * 0.1), base * 8);
    const k = z / this.view.zoom;
    this.view.x = px + (this.view.x - px) * k; // keep the point under the cursor still
    this.view.y = py + (this.view.y - py) * k;
    this.view.zoom = z;
    this._syncZoom();
    this._draw();
  }

  _syncZoom() {
    const base = Math.min(W / this.img.width, H / this.img.height);
    this.$("zoom").value = Math.round((this.view.zoom / base) * 100);
  }

  // draw the picture into a canvas of size w x h (scale = pixels per LED)
  _paint(ctx, scale, smooth) {
    ctx.save();
    ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W * scale, H * scale);
    if (this.img) {
      const a = this.adj;
      ctx.filter = `brightness(${a.bright}%) contrast(${a.contrast}%) saturate(${a.sat}%)`;
      ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = smooth ? "high" : "medium";
      ctx.translate(this.view.x * scale, this.view.y * scale);
      ctx.rotate((this.view.rot * Math.PI) / 180);
      const z = this.view.zoom * scale;
      ctx.drawImage(this.img, (-this.img.width * z) / 2, (-this.img.height * z) / 2, this.img.width * z, this.img.height * z);
    }
    ctx.restore();
  }

  // the 46x58 frame that goes to the mask (averaged down from 8x for quality)
  _frame() {
    const big = document.createElement("canvas");
    big.width = W * 8; big.height = H * 8;
    this._paint(big.getContext("2d"), 8, true);
    const small = document.createElement("canvas");
    small.width = W; small.height = H;
    const sc = small.getContext("2d");
    sc.imageSmoothingEnabled = true; sc.imageSmoothingQuality = "high";
    sc.drawImage(big, 0, 0, W, H);
    return small;
  }

  _draw() {
    if (!this.$) return;
    // editor: picture plus mask outline
    const st = this.$("stage"), s = st.width / W, ctx = st.getContext("2d");
    this._paint(ctx, s, false);
    ctx.save();
    ctx.fillStyle = "rgba(0,0,0,.55)"; // dim what the mask can't show
    ctx.beginPath();
    ctx.rect(0, 0, st.width, st.height);
    ctx.moveTo(0, 47 * s); ctx.lineTo(11 * s, H * s); ctx.lineTo(0, H * s); ctx.closePath();
    ctx.moveTo(W * s, 47 * s); ctx.lineTo(W * s, H * s); ctx.lineTo(35 * s, H * s); ctx.closePath();
    ctx.fill("evenodd");
    ctx.restore();
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,.8)"; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
    for (const [ex, ey] of EYES) { ctx.beginPath(); ctx.ellipse(ex * s, ey * s, EYE_RX * s, EYE_RY * s, 0, 0, Math.PI * 2); ctx.stroke(); }
    ctx.beginPath(); ctx.moveTo(0, 47 * s); ctx.lineTo(11 * s, H * s); ctx.moveTo(W * s, 47 * s); ctx.lineTo(35 * s, H * s); ctx.stroke();
    ctx.restore();

    // LED preview
    const led = this.$("led"), ls = led.width / W, lc = led.getContext("2d");
    lc.fillStyle = "#080808"; lc.fillRect(0, 0, led.width, led.height);
    const px = this._frame().getContext("2d").getImageData(0, 0, W, H).data;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      if (!ledExists(x, y)) continue;
      const i = (y * W + x) * 4;
      const r = px[i], g = px[i + 1], b = px[i + 2];
      lc.fillStyle = r + g + b < 12 ? "#161616" : `rgb(${r},${g},${b})`;
      lc.beginPath(); lc.arc((x + 0.5) * ls, (y + 0.5) * ls, ls * 0.38, 0, Math.PI * 2); lc.fill();
    }
  }

  async _send(keep) {
    const entity = this.$("mask").value;
    if (!this.img || !entity) return;
    const data = this._frame().toDataURL("image/png").split(",")[1];
    const name = this.$("name").value.trim() || "picture";
    const slot = this.$("slot").value;
    this.$("show").disabled = this.$("keep").disabled = true;
    this._status("Uploading… (the mask shows its download arrow for a few seconds)");
    try {
      const svc = { data, name };
      if (slot) svc.slot = +slot;
      const res = await this._hass.callService("shining_mask", "upload_image", svc, { entity_id: entity }, false, true);
      const used = res?.response?.[entity]?.slot ?? (slot ? +slot : undefined);
      await this._hass.callService("shining_mask", "show_face",
        { kind: "diy", value: String(used), temporary: !keep, hold_music: false }, { entity_id: entity });
      this._status(`On the mask in DIY slot ${used}${keep ? " – now your chosen face" : ""}.`);
    } catch (err) {
      this._status(`Failed: ${err?.message || err}`, true);
    } finally {
      this.$("show").disabled = this.$("keep").disabled = false;
    }
  }

  _status(msg, bad) {
    const el = this.$("status");
    el.textContent = msg;
    el.style.color = bad ? "var(--error-color, #db4437)" : "";
  }
}

customElements.define("shining-mask-uploader", MaskUploader);
