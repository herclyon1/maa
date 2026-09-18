/* seg-frames-logger.js — per-frame recorder of the segmented control's selection lens, for the native-vs-web comparison
   (remote-ref/tools/touch/seg_compare.py takes this file's JSON next to seg-native-<name>-frames.json).

   Loaded by index.html only with ?accept=1, ?diag=1 or ?segframes=1 (the ui session wires the script tag; nothing here touches
   view.js). Independent of the page's own handlers: it listens to pointer events in the capture phase and reads the DOM each
   requestAnimationFrame — AFTER the page's own rAF callbacks of that frame (2026-09-19: the ui session's raf_order.py showed the
   sampler running before the lens loop every frame, so every earlier web recording carried the lens rect of the previous frame
   under this frame's counter). The sampler now wraps window.requestAnimationFrame: every callback the page registers is followed
   by a registration of the sampler for the same frame, so the last sample of a frame is taken after the lens loop has moved the
   lens; a self-loop keeps the counter and the record running when nothing else animates. A frame's record is the last sample
   taken in it (committed when the next frame starts); `samples` = how many samples the frame got, `after_others` = whether a
   foreign callback ran in it before the last sample.

   What it records, from the first pointerdown inside `.segctl` until the lens has settled after the pointerup (rect within
   0.5 pt for 300 ms) or 3 s after the up, plus the 40 frames before the down:
     performance.now (s), phase (before / hold / drag / released, the same rule as seg_strip.py: drag starts at the first move),
     lens rect x/y/w/h = `.lens`.getBoundingClientRect() (viewport pt = screen pt in the standalone clip, transforms included),
     the lens's CSS scale, the warp copy's zoom, the current `#seg-lens-warp feDisplacementMap` scale attribute, the selected
     index, and the pointer events (down / moves / up / cancel) with their times.
   Output: localStorage["ark-segframes"] (read out of Safari's localstorage.sqlite3 like ark-accept) and window.__segFrames,
   in the seg-native-*-frames.json shape: {name, t_down_pts, t_up_pts, moves_since_down, control_events,
   first_lens_change_since_down, frames:[{file:null, frame, pts, t_since_down, t_since_up, phase, lens:[{view, rect, alpha, scale}],
   zoom, warp_scale, index}], counter:{x, y, cell, bits}}. `pts` is performance.now()/1000.
   A frame counter is painted at the top-left of the screen every frame (10 gray-coded 6-pt cells + digits) so the simulator's 60 Hz
   recording can be aligned with the JS frames: seg_web_frames.py reads the cells off each video frame. */
(function () {
  const q = new URLSearchParams(location.search);
  if (!(q.has("accept") || q.has("diag") || q.has("segframes"))) return;
  const KEY = "ark-segframes", BEFORE = 40, SETTLE_PT = 0.5, SETTLE_MS = 300, MAX_AFTER_UP_MS = 3000, BITS = 10, CELL = 6;
  const name = q.get("segframes") && q.get("segframes") !== "1" ? q.get("segframes") : "web";

  /* ---- the frame counter (canvas, top-left, below the status bar in the standalone clip) ---- */
  const cv = document.createElement("canvas"); cv.id = "segframes-counter";
  const dpr = devicePixelRatio || 1, W = BITS * CELL, H = CELL + 10;
  cv.width = W * dpr; cv.height = H * dpr;
  cv.style.cssText = `position:fixed;left:0;top:env(safe-area-inset-top, 0px);width:${W}px;height:${H}px;z-index:2147483647;pointer-events:none;image-rendering:pixelated`;
  const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
  const paint = (n, note) => {
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, W, H);
    const g = n ^ (n >> 1);                                       // gray code: consecutive frames differ in one cell, a half-changed frame is still readable
    for (let b = 0; b < BITS; b++) { ctx.fillStyle = (g >> (BITS - 1 - b)) & 1 ? "#000" : "#fff"; ctx.fillRect(b * CELL, 0, CELL, CELL); }
    ctx.fillStyle = "#000"; ctx.font = "9px ui-monospace, Menlo, monospace"; ctx.textBaseline = "top"; ctx.fillText(`f${n}${note ? " " + note : ""}`, 1, CELL + 1);
  };
  const mount = () => { if (document.body) document.body.appendChild(cv); else addEventListener("DOMContentLoaded", () => document.body.appendChild(cv)); };
  mount();

  /* ---- readings ---- */
  const segctl = () => document.querySelector(".segctl:not([hidden])");
  const num = (v, d) => { const n = parseFloat(v); return Number.isFinite(n) ? n : d; };
  const scaleOf = (cs) => {
    if (cs.scale && cs.scale !== "none") { const p = cs.scale.split(" ").map(parseFloat); return [p[0], p.length > 1 ? p[1] : p[0]]; }
    const m = /matrix\(([^)]+)\)/.exec(cs.transform || "");
    if (m) { const v = m[1].split(",").map(parseFloat); return [Math.hypot(v[0], v[1]), Math.hypot(v[2], v[3])]; }
    return [1, 1];
  };
  const round = (v, d = 2) => Math.round(v * 10 ** d) / 10 ** d;
  function reading(now) {
    const seg = segctl(); const lens = seg && seg.querySelector(".lens");
    if (!lens) return null;
    const r = lens.getBoundingClientRect(), cs = getComputedStyle(lens), sc = scaleOf(cs);
    const warp = seg.querySelector(".warp"), copy = warp && (warp.querySelector(".copy") || warp);
    const fd = document.querySelector("#seg-lens-warp feDisplacementMap");
    const bs = [...seg.querySelectorAll("button")];
    return { pts: now / 1000, rect: [round(r.left), round(r.top), round(r.width), round(r.height)], alpha: num(cs.opacity, 1), scale: [round(sc[0], 4), round(sc[1], 4)],
             zoom: copy ? round(num(getComputedStyle(copy).zoom, 1), 4) : null, warp_scale: fd ? num(fd.getAttribute("scale"), 0) : null,
             index: bs.findIndex((b) => b.classList.contains("on")), lift: lens.classList.contains("lift"), drag: !!seg && seg.classList.contains("drag"), spring: lens.classList.contains("spring") };
  }

  /* ---- pointer timeline (capture phase: seen before the page's own handlers and pointer capture) ---- */
  let frameNo = 0, ring = [], rec = null, lastNote = "", cur = null, lastTs = null;
  const inSeg = (e) => { const s = segctl(); return !!s && (s.contains(e.target) || (rec && rec.pointerId === e.pointerId)); };
  addEventListener("pointerdown", (e) => {
    if (!inSeg(e) || (rec && !rec.done)) return;
    rec = { name, pointerId: e.pointerId, t_down: performance.now(), t_up: null, moves: [], events: [], frames: ring.map((f) => ({ ...f, phase: "before" })), pointer: [{ type: "down", t: performance.now(), x: e.clientX, y: e.clientY }], done: false, rest: null, settledSince: null };
    const first = reading(performance.now()); rec.rest = first ? first.rect.slice() : null; rec.index0 = first ? first.index : -1;
  }, true);
  addEventListener("pointermove", (e) => { if (rec && !rec.done && e.pointerId === rec.pointerId) { rec.moves.push(performance.now()); rec.pointer.push({ type: "move", t: performance.now(), x: e.clientX, y: e.clientY }); } }, true);
  const up = (e) => { if (rec && !rec.done && e.pointerId === rec.pointerId && rec.t_up === null) { rec.t_up = performance.now(); rec.pointer.push({ type: e.type === "pointercancel" ? "cancel" : "up", t: rec.t_up, x: e.clientX, y: e.clientY }); } };
  addEventListener("pointerup", up, true); addEventListener("pointercancel", up, true);

  const phaseAt = (t) => !rec || t < rec.t_down ? "before" : rec.t_up !== null && t >= rec.t_up ? "released" : rec.moves.length && t >= rec.moves[0] ? "drag" : "hold";
  const changed = (a, b, tol) => !a || !b || a.some((v, i) => Math.abs(v - b[i]) > tol);
  function finish() {
    rec.done = true;
    const td = rec.t_down / 1000, tu = (rec.t_up === null ? rec.t_down : rec.t_up) / 1000;
    const frames = rec.frames.map((f) => ({ file: null, frame: f.frame, pts: round(f.pts, 3), t_since_down: round(f.pts - td, 3), t_since_up: round(f.pts - tu, 3), phase: f.phase,
      lens: [{ view: "segctl .lens", rect: f.rect, alpha: f.alpha, scale: f.scale }], zoom: f.zoom, warp_scale: f.warp_scale, index: f.index, lift: f.lift, drag: f.drag, spring: f.spring, samples: f.samples, after_others: f.after_others }));
    const firstChange = frames.find((f) => f.t_since_down >= 0 && changed(f.lens[0].rect, rec.rest, 0.3));
    const out = { name: rec.name, t_down_pts: round(td, 3), t_up_pts: round(tu, 3), moves_since_down: rec.moves.map((m) => round(m / 1000 - td, 3)),
      control_events: rec.events, first_lens_change_since_down: firstChange ? firstChange.t_since_down : null, frames,
      pointer: rec.pointer.map((p) => ({ ...p, t: round(p.t / 1000 - td, 3) })), counter: { x: 0, y: "env(safe-area-inset-top)", cell: CELL, bits: BITS, gray: true, dpr },
      viewport: `${innerWidth}×${innerHeight}`, standalone: matchMedia("(display-mode: standalone)").matches, href: location.href, at: new Date().toISOString(),
      sampler: "after the page's rAF callbacks (rAF wrapper, last sample of the frame; 2026-09-19)" };
    try { localStorage.setItem(KEY, JSON.stringify(out)); } catch {}
    window.__segFrames = out; dispatchEvent(new CustomEvent("segframes", { detail: out }));
    lastNote = `${frames.length}fr ok`;
  }
  /* commit the previous frame's record (its last sample) */
  function commit(f) {
    if (!f) return;
    const now = f.pts * 1000;
    if (rec && !rec.done) {
      rec.frames.push(f);
      const prev = rec.frames[rec.frames.length - 2];
      if (prev && f.index !== prev.index) rec.events.push({ t_since_down: round(now / 1000 - rec.t_down / 1000, 3), events: "valueChanged", index: f.index });
      if (rec.t_up !== null) {
        const still = prev && !changed(f.rect, prev.rect, SETTLE_PT) && f.scale[0] === prev.scale[0] && f.scale[1] === prev.scale[1];
        rec.settledSince = still ? (rec.settledSince ?? now) : null;
        if ((rec.settledSince !== null && now - rec.settledSince >= SETTLE_MS && !f.spring) || now - rec.t_up >= MAX_AFTER_UP_MS) finish();
      }
    } else { ring.push(f); if (ring.length > BEFORE) ring.shift(); }
  }
  /* one sample; several may run in a frame (the self-loop first, then one after each foreign rAF callback) — the last one wins */
  let othersThisFrame = 0;
  function sample(now, afterOther) {
    if (now !== lastTs) { commit(cur); cur = null; lastTs = now; frameNo++; othersThisFrame = 0; paint(frameNo, rec ? (rec.done ? lastNote : phaseAt(now)) : ""); }
    if (afterOther) othersThisFrame++;
    const r = reading(now);
    if (r) cur = { frame: frameNo, ...r, phase: phaseAt(now), samples: (cur && cur.frame === frameNo ? cur.samples : 0) + 1, after_others: othersThisFrame };
  }
  const origRAF = window.requestAnimationFrame.bind(window);
  const tick = (now) => { sample(now, false); origRAF(tick); };
  const after = (now) => { sample(now, true); };
  window.requestAnimationFrame = function (cb) { const id = origRAF(cb); if (cb !== tick && cb !== after) origRAF(after); return id; };
  origRAF(tick);
})();
