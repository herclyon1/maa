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
   TIME SEMANTICS (2026-09-19, the acceptance session on d9ebf5f): what the sampler reads in rAF frame N is painted at the end of
   that frame and reaches the screen at the NEXT vsync, so a frame's `pts` (and t_since_down / t_since_up) is its PRESENTATION
   time = the sampling frame's rAF timestamp + one frame interval (the median rAF interval of the run, `frame_interval` in the
   header; `sample_t` keeps the rAF timestamp of the sampling frame and `next_t` the next frame's, for the record). The native
   trace's times are presentation times, so the two compare like with like; nothing is shifted after the fact.
   INSTRUMENT FIELDS (2026-09-19, 监督局: why does the drag lead the native by 33–55 pt): every frame also carries
     `state`  = a copy of window.__segLens as the page's lens loop leaves it (the ui session exposes it; numbers only, copied as is;
                the agreed names: t = the loop tick's performance.now() (ms), x = the lens centre (pt), v = its velocity (pt/s),
                target = the spring target (pt), dt = the tick's step (s), pointer_t = performance.now() of the last pointer event
                the loop consumed (ms), retarget_t = when the target last changed (ms), phase = the loop's own phase string;
                any field ending in `_t` or named `t` is converted to seconds since the down in the record),
     `last_pointer_t` = the time of the latest pointer event this recorder saw before the sample (s since the down),
     `marks` = performance marks / measures whose name starts with "seg:" and whose start falls in (previous sample, this sample]
                — e.g. seg:lens-create, seg:map-blob, seg:value-repaint — as {name, start (s since down), dur (s)}.

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
  let lsDiag = false; try { lsDiag = localStorage.getItem("ark-diag") === "1"; } catch {}   // the phone's own switch (the ui session's diag sheet sets it; no query string needed)
  if (!(q.has("accept") || q.has("diag") || q.has("segframes") || lsDiag)) return;
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
  /* WHERE THE TWO FLASHES COME FROM (2026-09-19 20:0x, the user's phone on 194602: the segment flashes at the end of a tap, the bottom capsule
     flashes downward): per frame, next to the lens loop's state, the three things that can blank a platter or move the capsule —
       gl: the GL lens of the visible control — lift (the control carries .lift: the DOM platter is transparent then), lens_bg (the DOM platter's
           computed background-color), frames (the package's stats.frames so far), tick ("drew" = stats.frames grew this frame; "clear" = the page
           asked for lift ≤ 0 this frame (setState wrapped, recording only); "none" = neither), lift_req (the lift the page last asked for);
       tab: the bottom nav.tabs — rect top / height, computed display / opacity / transform, plat_same (its .plat is the same node as last frame:
           false = the bar was rebuilt), glide rect left / width / top, glide_lift (.glide.lift), kbd (html.kbd: the keyboard rule hides the bar);
       vp: visualViewport height / offsetTop / scale, innerHeight, the active element (tag#id) — the keyboard / viewport candidates.
     Events (window resize, visualViewport resize / scroll, window scroll) go to `vp_events` with the viewport numbers at that moment. */
  let lastPlat = null, glWrapped = null, glReq = null;
  const wrapGl = (seg) => { const g = seg && seg.__gl; if (!g || !g.lens || glWrapped === g.lens) return g; const L = g.lens, orig = L.setState;
    L.setState = function (st) { glReq = { lift: st && st.lift, t: performance.now() }; return orig.call(this, st); }; glWrapped = L; return g; };
  let lastFrames = null;
  const glReading = (seg, lens) => { const g = wrapGl(seg); if (!g) return { lift: seg.classList.contains("lift"), lens_bg: lens ? getComputedStyle(lens).backgroundColor : null, gl: false };
    const fr = g.lens.stats.frames, drew = lastFrames !== null && fr > lastFrames; lastFrames = fr;
    const req = glReq && performance.now() - glReq.t < 40 ? glReq : null;   // a request older than this frame is not this frame's
    return { gl: true, lift: seg.classList.contains("lift"), lens_bg: lens ? getComputedStyle(lens).backgroundColor : null, frames: fr, tick: ((drew ? "drew" : "") + (req && !(req.lift > 0) ? (drew ? "+clear" : "clear") : "")) || "none", lift_req: req ? round(req.lift, 4) : null }; };
  const tabReading = () => { const nav = document.querySelector("nav.tabs"); if (!nav) return null; const r = nav.getBoundingClientRect(), cs = getComputedStyle(nav), plat = nav.querySelector(".plat"), glide = nav.querySelector(".glide"), gr = glide && glide.getBoundingClientRect();
    const same = plat === lastPlat; lastPlat = plat;
    /* #15 (2号, 2026-09-20): the tab-lens driver's own state per frame — window.__tabLens (phase / p / x / target / frame, null when the loop is off), the classes it sets (tl-on / drag),
       its finger record (__tabLensFinger: down / x / moved / a), why it last stopped (__tabLensStop), the last down it saw (__tabLensRM), any error (__tabLensErr) — so a device record
       says whether the pointer events reached the driver and what it did with them */
    const tl = window.__tabLens, fg = window.__tabLensFinger, stp = window.__tabLensStop, rmd = window.__tabLensRM;
    return { top: round(r.top), h: round(r.height), display: cs.display, opacity: num(cs.opacity, 1), transform: cs.transform === "none" ? "none" : cs.transform.slice(0, 60), plat_same: same, glide: gr ? [round(gr.left), round(gr.width), round(gr.top)] : null, glide_lift: !!(glide && glide.classList.contains("lift")), glide_liftsel: !!(glide && glide.classList.contains("lift-sel")), kbd: document.documentElement.classList.contains("kbd"),
      tl_on: nav.classList.contains("tl-on"), drag: nav.classList.contains("drag"), tlens: nav.classList.contains("tlens"), tl_vars: [nav.style.getPropertyValue("--tl-left"), nav.style.getPropertyValue("--tl-w")].join("/"),
      tl: tl ? { phase: tl.phase, p: round(tl.p, 4), x: round(tl.x, 2), target: round(tl.target, 2), frame: tl.frame, w: round(tl.w, 2), h: round(tl.h, 2), rm: tl.rm } : null,
      finger: fg ? { down: fg.down, x: fg.x === null ? null : round(fg.x, 1), moved: fg.moved, a: round(fg.a, 3), last: fg.last ? { t: fg.last.t, pt: fg.last.pt, id: fg.last.id, at: round(fg.last.at, 1), target: fg.last.target || null } : null } : null, stop: stp ? { why: stp.why, at: round(stp.at, 1) } : null, down_seen: rmd ? { at: round(rmd.at, 1), started: rmd.started, why: rmd.why || null } : null, err: window.__tabLensErr || null }; };
  const vpReading = () => { const vv = window.visualViewport; const ae = document.activeElement; return { vvh: vv ? round(vv.height) : null, vvt: vv ? round(vv.offsetTop) : null, vvs: vv ? round(vv.scale, 3) : null, ih: innerHeight, ae: ae ? ae.tagName.toLowerCase() + (ae.id ? "#" + ae.id : "") : null }; };
  const vpEvents = []; const vpEvent = (type) => () => { if (vpEvents.length < 400) vpEvents.push({ type, t: performance.now(), ...vpReading() }); };
  addEventListener("resize", vpEvent("resize")); addEventListener("scroll", vpEvent("scroll"), { passive: true });
  if (window.visualViewport) { visualViewport.addEventListener("resize", vpEvent("vv-resize")); visualViewport.addEventListener("scroll", vpEvent("vv-scroll")); }
  function reading(now) {
    const seg = segctl(); const lens = seg && seg.querySelector(".lens");
    const tab = tabReading();
    if (!lens && !tab) return null;
    /* no segmented control on this tab (the bottom capsule's flash is recorded from any tab): the tab bar's .glide stands in as the tracked rect */
    const el = lens || document.querySelector("nav.tabs .glide") || document.querySelector("nav.tabs");
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el), sc = scaleOf(cs);
    const warp = seg && seg.querySelector(".warp"), copy = warp && (warp.querySelector(".copy") || warp);
    const fd = document.querySelector("#seg-lens-warp feDisplacementMap");
    const bs = seg ? [...seg.querySelectorAll("button")] : [];
    const st = window.__segLens && typeof window.__segLens === "object" ? Object.fromEntries(Object.entries(window.__segLens).filter(([k, v]) => typeof v === "number" || typeof v === "string").map(([k, v]) => [k, typeof v === "number" ? round(v, 4) : v])) : null;
    const marks = [];
    try { for (const e of performance.getEntriesByType("mark").concat(performance.getEntriesByType("measure"))) { if (e.name.startsWith("seg:") && e.startTime > lastSampleT && e.startTime <= now) marks.push({ name: e.name, start: e.startTime, dur: round(e.duration, 3) }); } } catch {}
    return { pts: now / 1000, rect: [round(r.left), round(r.top), round(r.width), round(r.height)], alpha: num(cs.opacity, 1), scale: [round(sc[0], 4), round(sc[1], 4)],
             zoom: copy ? round(num(getComputedStyle(copy).zoom, 1), 4) : null, warp_scale: fd ? num(fd.getAttribute("scale"), 0) : null,
             index: bs.findIndex((b) => b.classList.contains("on")), lift: el.classList.contains("lift"), drag: !!seg && seg.classList.contains("drag"), spring: el.classList.contains("spring"),
             state: st, marks, last_pointer_t: rec && rec.pointer.length ? rec.pointer[rec.pointer.length - 1].t : null,
             gl: seg ? glReading(seg, lens) : null, tab, vp: vpReading(), tracked: lens ? "segctl .lens" : "nav.tabs .glide" };
  }

  /* ---- pointer timeline (capture phase: seen before the page's own handlers and pointer capture) ---- */
  let frameNo = 0, ring = [], rec = null, lastNote = "", cur = null, lastTs = null, lastSampleT = -1;
  const inSeg = (e) => { const s = segctl(), nav = document.querySelector("nav.tabs"); return (!!s && s.contains(e.target)) || (!!nav && nav.contains(e.target)) || (!!rec && rec.pointerId === e.pointerId); };
  /* WHERE THE FIRST GESTURE'S TIME GOES (2026-09-19 18:4x, the data session's seg-final-181053.md ①: the first lens gesture after load had
     ~190 ms of main-thread silence before its lift, the second none): three readings, none of them changing the page:
       `lag` on each pointer entry = performance.now() − event.timeStamp at this capture listener (ms): how long the event waited for the main
                thread before it was dispatched (the OS stamps the touch when it happens; a busy main thread delivers it late);
       seg:longtask = every Long Task the engine reports (PerformanceObserver "longtask", where supported — `longtask_supported` in the header)
                re-emitted as a performance measure, so it lands in the frames' `marks` like any other seg: entry;
       seg:page-render / seg:page-updateLive = the page's own render() / updateLive() wrapped in a measure (they are the page's periodic
                and re-render tasks; wrapped only if they exist on window). */
  let longtaskSupported = false;
  try { longtaskSupported = !!(window.PerformanceObserver && PerformanceObserver.supportedEntryTypes && PerformanceObserver.supportedEntryTypes.includes("longtask"));
    if (longtaskSupported) new PerformanceObserver((list) => { for (const e of list.getEntries()) { try { performance.measure("seg:longtask", { start: e.startTime, end: e.startTime + e.duration }); } catch {} } }).observe({ entryTypes: ["longtask"] }); } catch {}
  for (const fn of ["render", "updateLive"]) { const orig = window[fn]; if (typeof orig !== "function") continue;
    window[fn] = function (...args) { const t = performance.now(); try { return orig.apply(this, args); } finally { try { performance.measure("seg:page-" + fn, { start: t, end: performance.now() }); } catch {} } }; }
  const lagOf = (e) => (e.timeStamp > 0 && e.timeStamp <= performance.now() ? round(performance.now() - e.timeStamp, 1) : null);
  addEventListener("pointerdown", (e) => {
    if (!inSeg(e) || (rec && !rec.done)) return;
    const nav = document.querySelector("nav.tabs"), inTab = !!nav && nav.contains(e.target);
    const sc = segctl(), glMode = sc ? (sc.__gl ? "webgl" : (sc.classList.contains("gl") ? "webgl (no instance yet)" : "svg fallback")) : "no segmented control on this tab";
    rec = { name: inTab ? name + "-tab" : name, gl_mode: glMode, pointerId: e.pointerId, t_down: performance.now(), t_up: null, moves: [], events: [], frames: ring.map((f) => ({ ...f, phase: "before" })), pointer: [{ type: "down", t: performance.now(), x: e.clientX, y: e.clientY, lag: lagOf(e) }], done: false, rest: null, settledSince: null };
    const first = reading(performance.now()); rec.rest = first ? first.rect.slice() : null; rec.index0 = first ? first.index : -1;
  }, true);
  addEventListener("pointermove", (e) => { if (rec && !rec.done && e.pointerId === rec.pointerId) { rec.moves.push(performance.now()); rec.pointer.push({ type: "move", t: performance.now(), x: e.clientX, y: e.clientY, lag: lagOf(e) }); } }, true);
  const up = (e) => { if (rec && !rec.done && e.pointerId === rec.pointerId && rec.t_up === null) { rec.t_up = performance.now(); rec.pointer.push({ type: e.type === "pointercancel" ? "cancel" : "up", t: rec.t_up, x: e.clientX, y: e.clientY, lag: lagOf(e) }); } };
  addEventListener("pointerup", up, true); addEventListener("pointercancel", up, true);
  /* T7 (2号, 2026-09-20 12:3x, WORKLIST): the keyboard case — a text field's focus starts a 1.5 s record ("<name>-kbd") with no pointer: every frame carries `vp`
     (innerHeight, visualViewport height / offsetTop, the active element) and `tab` (the capsule's top / display, html.kbd), `vp_events` lists the resize / scroll /
     visualViewport events from 1 s before the focus; the focus / blur moments go to control_events. Only when no gesture record is running. */
  const KBD_MS = 1500, isText = (el) => !!el && ((el.tagName === "INPUT" && !/^(checkbox|radio|range|button|submit|reset|file|color|hidden)$/i.test(el.type)) || el.tagName === "TEXTAREA" || el.isContentEditable === true);
  addEventListener("focusin", (e) => {
    if (!isText(e.target) || (rec && !rec.done)) return;
    const t = performance.now();
    rec = { name: name + "-kbd", kind: "kbd", gl_mode: "n/a (keyboard record)", pointerId: null, t_down: t, t_up: t, moves: [], events: [{ t_since_down: 0, events: "focusin", index: -1, field: e.target.tagName.toLowerCase() + (e.target.id ? "#" + e.target.id : "") }], frames: ring.map((f) => ({ ...f, phase: "before" })), pointer: [], done: false, settledSince: null };
    const first = reading(t); rec.rest = first ? first.rect.slice() : null; rec.index0 = first ? first.index : -1;
  }, true);
  addEventListener("focusout", (e) => { if (rec && !rec.done && rec.kind === "kbd") rec.events.push({ t_since_down: round((performance.now() - rec.t_down) / 1000, 3), events: "focusout", index: -1 }); }, true);

  const phaseAt = (t) => !rec || t < rec.t_down ? "before" : rec.t_up !== null && t >= rec.t_up ? "released" : rec.moves.length && t >= rec.moves[0] ? "drag" : "hold";
  const changed = (a, b, tol) => !a || !b || a.some((v, i) => Math.abs(v - b[i]) > tol);
  function finish() {
    rec.done = true;
    const td = rec.t_down / 1000, tu = (rec.t_up === null ? rec.t_down : rec.t_up) / 1000;
    const st = rec.frames.map((f) => f.sample_t ?? f.pts), gaps = st.slice(1).map((v, i) => v - st[i]).filter((g) => g > 0).sort((a, b) => a - b);
    const interval = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 1 / 60;                       // the run's median rAF interval (s)
    const frames = rec.frames.map((f) => { const s = f.sample_t ?? f.pts, p = s + interval; return { file: null, frame: f.frame, pts: round(p, 3), sample_t: round(s, 3), next_t: f.next_t === null || f.next_t === undefined ? null : round(f.next_t, 3), t_since_down: round(p - td, 3), t_since_up: round(p - tu, 3), phase: phaseAt(p * 1000),   // the phase by the presentation time, like the native trace
      lens: [{ view: f.tracked || "segctl .lens", rect: f.rect, alpha: f.alpha, scale: f.scale }], zoom: f.zoom, warp_scale: f.warp_scale, index: f.index, lift: f.lift, drag: f.drag, spring: f.spring, samples: f.samples, after_others: f.after_others,
      state: f.state ? Object.fromEntries(Object.entries(f.state).map(([k, v]) => [k, typeof v === "number" && (k === "t" || k.endsWith("_t")) ? round(v / 1000 - td, 3) : v])) : null,
      last_pointer_t: f.last_pointer_t === null || f.last_pointer_t === undefined ? null : round(f.last_pointer_t / 1000 - td, 3),
      marks: (f.marks || []).map((m) => ({ name: m.name, start: round(m.start / 1000 - td, 3), dur: round(m.dur / 1000, 3) })),
      gl: f.gl || null, tab: f.tab || null, vp: f.vp || null, tracked: f.tracked || null }; });
    const firstChange = frames.find((f) => f.t_since_down >= 0 && changed(f.lens[0].rect, rec.rest, 0.3));
    const out = { name: rec.name, t_down_pts: round(td, 3), t_up_pts: round(tu, 3), moves_since_down: rec.moves.map((m) => round(m / 1000 - td, 3)),
      control_events: rec.events, first_lens_change_since_down: firstChange ? firstChange.t_since_down : null, frames,
      pointer: rec.pointer.map((p) => ({ ...p, t: round(p.t / 1000 - td, 3) })), counter: { x: 0, y: "env(safe-area-inset-top)", cell: CELL, bits: BITS, gray: true, dpr },
      viewport: `${innerWidth}×${innerHeight}`, standalone: matchMedia("(display-mode: standalone)").matches, href: location.href, at: new Date().toISOString(),
      sampler: "after the page's rAF callbacks (rAF wrapper, last sample of the frame; 2026-09-19)", frame_interval: round(interval, 4),
      time_semantics: "pts = presentation time = the sampling frame's rAF timestamp (sample_t) + frame_interval (the next vsync); t_since_down / t_since_up from pts",
      state_source: window.__segLens ? "window.__segLens (the page's lens loop)" : "window.__segLens not present",
      longtask_supported: longtaskSupported, pointer_lag: "lag = performance.now() − event.timeStamp at the capture listener (ms): the event's wait for the main thread",
      vp_events: vpEvents.filter((e) => e.t >= rec.t_down - 1000 && e.t <= (rec.t_up === null ? rec.t_down : rec.t_up) + MAX_AFTER_UP_MS).map((e) => ({ ...e, t: round(e.t / 1000 - td, 3) })),
      gl_mode: rec.gl_mode, gl_query: new URLSearchParams(location.search).get("gl"),
      ua: navigator.userAgent, page_version: (() => { const t = document.querySelector('script[src^="view.js"]'); const m = t && /v=([0-9]+)/.exec(t.getAttribute("src")); return m ? m[1] : null; })(),
      tab_lens: (() => { const t = document.querySelector('script[src*="tab-lens.js"]'); return { src: t ? t.getAttribute("src") : null, loaded: !!window.__tabLensStep, mode: window.__tabLensGL ? (window.__tabLensGL() ? "geometry+gl" : "geometry") : null, sw: !!(navigator.serviceWorker && navigator.serviceWorker.controller), rm: matchMedia("(prefers-reduced-motion: reduce)").matches, err: window.__tabLensErr || null }; })(),   // #15: which tab-lens.js the device runs and whether the driver is present
      trigger: q.has("accept") ? "?accept" : q.has("diag") ? "?diag" : q.has("segframes") ? "?segframes" : "localStorage ark-diag", kind: rec.kind || "gesture" };
    try { localStorage.setItem(KEY, JSON.stringify(out)); } catch {}
    window.__segFrames = out; dispatchEvent(new CustomEvent("segframes", { detail: out }));
    lastNote = `${frames.length}fr ok`;
  }
  /* commit the previous frame's record (its last sample) */
  function commit(f, nextTs) {
    if (!f) return;
    f.sample_t = f.pts; f.next_t = nextTs === undefined ? null : nextTs / 1000;   // pts is resolved to the presentation time in finish()
    const now = f.pts * 1000;
    if (rec && !rec.done) {
      rec.frames.push(f);
      const prev = rec.frames[rec.frames.length - 2];
      if (prev && f.index !== prev.index) rec.events.push({ t_since_down: round(now / 1000 - rec.t_down / 1000, 3), events: "valueChanged", index: f.index });
      if (rec.kind === "kbd") { if (now - rec.t_down >= KBD_MS) finish(); return; }   // T7: a fixed 1.5 s window from the focus
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
    if (now !== lastTs) { commit(cur, now); cur = null; lastSampleT = lastTs === null ? -1 : lastTs; lastTs = now; frameNo++; othersThisFrame = 0; paint(frameNo, rec ? (rec.done ? lastNote : phaseAt(now)) : ""); }
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
