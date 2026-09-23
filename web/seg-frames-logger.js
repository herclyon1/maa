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
   THE LIGHT BRANCH (2026-09-23, BOARD/派单-真机核-界面 件 A, D46): the rich sampling above is for `.segctl` and `nav.tabs` only — the native
   comparison and the acceptance rows read those fields. A pointerdown on ANY other control starts a LIGHT record instead: `kind:"light"`,
   {control:{path,label,tag,cls}, frames:[{frame, pts, t_since_down, t_since_up, phase, rect, alpha, scale, transform, cls, scene?}],
   pointer, control_events (click / change / sceneChanged), marks}. Per frame it reads that control's own geometry plus the scene around it
   (current tab, open .sheet ids, dialog#alert, #subpage, #diagsheet, #toast, html.sheet-open / .kbd, scrollY); `scene` is written only on the
   frames where it changed. No 40-frame preroll, no lens / warp / GL fields, no frame counter: a few tens of KB that say whether the control
   reacted, when, and to what. It stops on the same rule as the rich record (rect + scene still for 300 ms, or 3 s after the up) with a 10 s
   hard cap. 件 B: the mark button (`#diagmark`, diag sessions only) writes {at, control, point, word} into `marks[]` — window.__diagMark(word)
   is the same call without the UI. 件 C: a finished record is PUT to the diagnostic bucket (long random key, x-cos-forbid-overwrite: true);
   a failure falls back to the copy / share sheet and a line on the page (`#diagline`), never silence.
   A frame counter is painted at the top-left of the screen every frame (10 gray-coded 6-pt cells + digits) so the simulator's 60 Hz
   recording can be aligned with the JS frames: seg_web_frames.py reads the cells off each video frame. */
(function () {
  const q = new URLSearchParams(location.search);
  let lsDiag = false; try { lsDiag = localStorage.getItem("ark-diag") === "1"; } catch {}   // the phone's own switch (the ui session's diag sheet sets it; no query string needed)
  if (!(q.has("accept") || q.has("diag") || q.has("segframes") || lsDiag)) return;
  const KEY = "ark-segframes", BEFORE = 40, SETTLE_PT = 0.5, SETTLE_MS = 300, MAX_AFTER_UP_MS = 3000, BITS = 10, CELL = 6;
  const HARD_MS = 10000;                                          // 件 A: a light record never runs longer than this, whatever the page keeps animating
  const DIAG_UI = !q.has("accept") && !q.has("segframes");         // the phone's own diagnostic session: mark button + status line, and no frame counter
  /* 件 C: where a finished record goes — the diagnostic bucket (BOARD DECISIONS-DATA DATA16 / DATA17, 事实-上传目标-老中继2号 28–31):
     ark-diag-1315873325 in ap-shanghai; anonymous name/cos:PutObject on diag/* only (read / list / anything else 403), CORS rule
     diag-from-pages = origin https://herclyon1.github.io, PUT, AllowedHeader *, ExposeHeader ETag, MaxAge 600; lifecycle 7 days. Measured
     2026-09-23 04:5x from this Mac: the preflight for PUT + content-type,x-cos-forbid-overwrite from that origin 200; the anonymous PUT 200;
     the same key again 409 FileAlreadyExists; an anonymous GET 403. No key in this page. localStorage["ark-diag-bucket"] / ?diagbucket=
     override it. An acceptance run (?accept) never writes to the bucket: its records take the keep-local path, which is what its rows check. */
  /* ⓪ 打回 (验收 09-23 20:1x): the phone's accessibility display settings in every record — Reduce Motion (the switch never lifts its lens), Reduce
     Transparency and Increase Contrast (the glass materials change) — read by the standard media queries at the moment the record is made */
  const a11yNow = () => { const mm = (q) => { try { return matchMedia(q).matches; } catch (e) { return null; } };
    return { reduce_motion: mm("(prefers-reduced-motion: reduce)"), reduce_transparency: mm("(prefers-reduced-transparency: reduce)"),
      contrast: ["more", "less", "custom"].find((v) => mm(`(prefers-contrast: ${v})`)) || (mm("(prefers-contrast: no-preference)") ? "no-preference" : null) }; };
  const COS_BASE = "https://ark-diag-1315873325.cos.ap-shanghai.myqcloud.com";
  const QKEY = "ark-diag-queue";
  const name = q.get("segframes") && q.get("segframes") !== "1" ? q.get("segframes") : "web";

  /* ---- the frame counter (canvas, top-left, below the status bar in the standalone clip) ---- */
  const cv = document.createElement("canvas"); cv.id = "segframes-counter";
  const dpr = devicePixelRatio || 1, W = BITS * CELL, H = CELL + 10;
  cv.width = W * dpr; cv.height = H * dpr;
  cv.style.cssText = `position:fixed;left:0;top:env(safe-area-inset-top, 0px);width:${W}px;height:${H}px;z-index:2147483647;pointer-events:none;image-rendering:pixelated`;
  const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
  const paint = (n, note) => {
    if (DIAG_UI) return;                                          // 件 A: the counter is for aligning a simulator video; on the phone it is just a white box
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, W, H);
    const g = n ^ (n >> 1);                                       // gray code: consecutive frames differ in one cell, a half-changed frame is still readable
    for (let b = 0; b < BITS; b++) { ctx.fillStyle = (g >> (BITS - 1 - b)) & 1 ? "#000" : "#fff"; ctx.fillRect(b * CELL, 0, CELL, CELL); }
    ctx.fillStyle = "#000"; ctx.font = "9px ui-monospace, Menlo, monospace"; ctx.textBaseline = "top"; ctx.fillText(`f${n}${note ? " " + note : ""}`, 1, CELL + 1);
  };
  const mount = () => { if (document.body) document.body.appendChild(cv); else addEventListener("DOMContentLoaded", () => document.body.appendChild(cv)); };
  if (!DIAG_UI) mount();

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
  /* ---- 件 A: the light branch's readings ---------------------------------------------------------------------------------------------
     CTRL_SEL is what counts as "the control the finger is on": the nearest of these ancestors of the event target, so a record says
     「设置行 开机自检」 and not 「span」. Everything here is read-only DOM. */
  const CTRL_SEL = "button, a, input, select, textarea, label, .row, .cell, .tile, .sw, .navbtn, .seg, .segctl, [role=button], [data-id], [data-tab]";
  const clip = (v, n) => (v == null ? null : String(v).replace(/\s+/g, " ").trim().slice(0, n) || null);
  const labelOf = (el) => clip((el.getAttribute && (el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("placeholder"))) || el.textContent, 28);
  const pathOf = (el) => {                                        // up to four steps, stopping at the first id: "#app > section.group > div.row.nav"
    const out = [];
    for (let n = el; n && n.nodeType === 1 && n !== document.documentElement && out.length < 4; n = n.parentElement) {
      let t = n.tagName.toLowerCase();
      if (n.id) t += "#" + n.id;
      const c = [...n.classList].slice(0, 2).join(".");
      if (c) t += "." + c;
      const d = n.dataset && (n.dataset.id || n.dataset.tab);
      if (d) t += "[" + d + "]";
      out.unshift(t);
      if (n.id) break;
    }
    return out.join(" > ");
  };
  const rectOf = (el) => { const r = el.getBoundingClientRect(); return [round(r.left), round(r.top), round(r.width), round(r.height)]; };
  /* what the user can SEE around the control: which tab, which sheet / page / alert is up, the toast, the scroll — this is what turns
     「点了没反应」 into a fact (nothing in the scene changed) or into 「反应错了」 (the wrong thing changed). */
  const sceneReading = () => {
    const dlg = document.querySelector("dialog#alert"), sp = document.getElementById("subpage"), ds = document.getElementById("diagsheet"), ts = document.getElementById("toast");
    const tab = document.querySelector("nav.tabs button.on, nav.tabs [aria-selected=\"true\"]");
    return { tab: tab ? clip((tab.querySelector(".tcg") || tab).textContent, 12) : null,   // the tab button holds two copies of its label (P0b-tabclip); read one
             sheets: [...document.querySelectorAll(".sheet")].filter((x) => x.hasAttribute("open")).map((x) => (x.id || "sheet") + (x.classList.contains("in") ? ":in" : "")),
             alert: dlg && dlg.open ? (dlg.classList.contains("closing") ? "closing" : true) : false,   // "closing" = the fade-out before close() (view.js ask()) subpage: sp && !sp.hidden ? ([...sp.classList].join(".") || "open") : null,
             diagsheet: !!(ds && !ds.hidden), toast: ts && ts.classList.contains("show") ? clip(ts.textContent, 40) : null,
             html: [...document.documentElement.classList].filter((c) => c === "sheet-open" || c === "kbd").join(" ") || null,
             scroll: round(scrollY) };
  };
  /* running finite animations / transitions on what the user sees (the control, the alert, open sheets, the sub page, the toast): a record must not stop
     "still" while one of them is still moving — 数据 17:3x: the alert's cancel fade (--ios-motion-alert-duration .40 s) outlasts the 300 ms rest, so
     the close never reached the record */
  const animsOf = (el) => {
    const els = [el, document.querySelector("dialog#alert"), document.getElementById("subpage"), document.getElementById("toast"), ...document.querySelectorAll(".sheet[open]")];
    let n = 0;
    for (const x of els) if (x && x.getAnimations) for (const a of x.getAnimations()) if (a.playState === "running" && isFinite(a.effect && a.effect.getComputedTiming().endTime)) n++;
    return n;
  };
  function lightReading(now) {
    const el = rec && rec.el;
    if (!el || !el.isConnected) return { pts: now / 1000, rect: null, gone: true, anims: animsOf(null), scene: sceneReading(), last_pointer_t: rec && rec.pointer.length ? rec.pointer[rec.pointer.length - 1].t : null };
    const cs = getComputedStyle(el), sc = scaleOf(cs);
    return { pts: now / 1000, rect: rectOf(el), alpha: num(cs.opacity, 1), scale: [round(sc[0], 4), round(sc[1], 4)],
             transform: cs.transform === "none" ? "none" : cs.transform.slice(0, 48), bg: cs.backgroundColor, anims: animsOf(el),
             cls: [...el.classList].join(" ").slice(0, 60) || null, scene: sceneReading(),
             last_pointer_t: rec && rec.pointer.length ? rec.pointer[rec.pointer.length - 1].t : null };
  }
  const rid = () => { try { const a = new Uint8Array(16); crypto.getRandomValues(a); return [...a].map((b) => b.toString(16).padStart(2, "0")).join(""); }
                      catch { return (Date.now().toString(16) + Math.random().toString(16).slice(2)).padEnd(32, "0").slice(0, 32); } };

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
  let markUI = null, lastTouch = null, lastOut = null, lastOutAt = 0, sentN = 0, keptN = 0, sheetShown = false;
  let lineEl = null;
  const inSeg = (e) => { const s = segctl(), nav = document.querySelector("nav.tabs"); return (!!s && s.contains(e.target)) || (!!nav && nav.contains(e.target)) || (!!rec && !rec.done && rec.pointerId === e.pointerId); };
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
    if (stopped) return;
    if (markUI && markUI.contains(e.target)) return;              // 件 B: our own button is not the page
    lastTouch = { path: pathOf(e.target), label: labelOf(e.target), x: round(e.clientX, 1), y: round(e.clientY, 1), t: performance.now() };
    if (rec && !rec.done) return;
    if (!inSeg(e)) { startLight(e); return; }                     // 件 A: everything that is not .segctl / nav.tabs gets the light record
    const nav = document.querySelector("nav.tabs"), inTab = !!nav && nav.contains(e.target);
    const sc = segctl(), glMode = sc ? (sc.__gl ? "webgl" : (sc.classList.contains("gl") ? "webgl (no instance yet)" : "svg fallback")) : "no segmented control on this tab";
    rec = { name: inTab ? name + "-tab" : name, gl_mode: glMode, pointerId: e.pointerId, t_down: performance.now(), t_up: null, moves: [], events: [], frames: ring.map((f) => ({ ...f, phase: "before" })), pointer: [{ type: "down", t: performance.now(), x: e.clientX, y: e.clientY, lag: lagOf(e) }], marks: [], done: false, rest: null, settledSince: null };
    const first = reading(performance.now()); rec.rest = first ? first.rect.slice() : null; rec.index0 = first ? first.index : -1;
  }, true);
  function startLight(e) {
    const el = (e.target.closest && e.target.closest(CTRL_SEL)) || e.target;
    const t = performance.now();
    rec = { kind: "light", name: name + "-light", el, pointerId: e.pointerId, t_down: t, t_up: null, moves: [], events: [], frames: [], marks: [],
            control: { path: pathOf(el), label: labelOf(el), tag: el.tagName ? el.tagName.toLowerCase() : null, cls: el.classList ? [...el.classList].join(" ").slice(0, 80) || null : null,
                       hit: { path: pathOf(e.target), label: labelOf(e.target) }, rect: el.getBoundingClientRect ? rectOf(el) : null },
            pointer: [{ type: "down", t, x: e.clientX, y: e.clientY, lag: lagOf(e) }], done: false, rest: null, settledSince: null };
    cur = null;                                                   // see (2) above: no rich-shaped frame in a light record
    const first = lightReading(t); rec.rest = first.rect ? first.rect.slice() : null; rec.scene0 = first.scene;
    /* the scene between frames: a state shorter than a frame gap (the alert's .40 s closing fade under 1.5 s frames — simulator A 0fe960c run, 老网页 res json
       09-23 18:50: frames read true → false, the closing never sampled) is still a fact of what the page did; a class / open / hidden change anywhere writes
       the scene at that moment to control_events as "sceneMutation" (only when it differs from the last one written) */
    const r0 = rec; let lastMut = JSON.stringify(first.scene);
    r0.mo = new MutationObserver(() => { if (r0.done) return; const sc = sceneReading(), js = JSON.stringify(sc); if (js === lastMut) return; lastMut = js;
      r0.events.push({ t_since_down: round((performance.now() - r0.t_down) / 1000, 3), events: "sceneMutation", scene: sc }); });
    r0.mo.observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ["class", "open", "hidden"] });
  }
  /* 「动作 → 可见响应」 needs the action too: the click / change the page itself acts on, in the capture phase like the pointers */
  for (const type of ["click", "change", "input"]) addEventListener(type, (e) => {
    if (!rec || rec.done || rec.kind !== "light") return;
    if (markUI && markUI.contains(e.target)) return;
    /* the browser's own click after a press the page already answered with its own click at the up is swallowed further down the capture
       path (view.js installPressables: ghost / data-pe; motion.js: data-rc) — after this window-capture listener, so it used to land here as a
       second "click" (界面-串2 09-23 18:4x, simulator B: alert 取消 pointerup @8 ms, the page's click @8 untrusted, the browser's @10 trusted;
       the page acted once). Once the dispatch is over, a click whose default was prevented is renamed click-swallowed */
    const ent = { t_since_down: round((performance.now() - rec.t_down) / 1000, 3), events: type, on: pathOf(e.target),
                  value: type === "click" ? null : clip(e.target && (e.target.type === "checkbox" ? String(e.target.checked) : e.target.value), 24) };
    rec.events.push(ent);
    if (type === "click") setTimeout(() => { if (e.defaultPrevented) ent.events = "click-swallowed"; }, 0);
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
    rec = { name: name + "-kbd", kind: "kbd", gl_mode: "n/a (keyboard record)", pointerId: null, t_down: t, t_up: t, moves: [], events: [{ t_since_down: 0, events: "focusin", index: -1, field: e.target.tagName.toLowerCase() + (e.target.id ? "#" + e.target.id : "") }], frames: ring.map((f) => ({ ...f, phase: "before" })), pointer: [], marks: [], done: false, settledSince: null };
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
      viewport: `${innerWidth}×${innerHeight}`, standalone: matchMedia("(display-mode: standalone)").matches, a11y: a11yNow(), href: location.href, at: new Date().toISOString(),
      sampler: "after the page's rAF callbacks (rAF wrapper, last sample of the frame; 2026-09-19)", frame_interval: round(interval, 4),
      time_semantics: "pts = presentation time = the sampling frame's rAF timestamp (sample_t) + frame_interval (the next vsync); t_since_down / t_since_up from pts",
      state_source: window.__segLens ? "window.__segLens (the page's lens loop)" : "window.__segLens not present",
      longtask_supported: longtaskSupported, pointer_lag: "lag = performance.now() − event.timeStamp at the capture listener (ms): the event's wait for the main thread",
      vp_events: vpEvents.filter((e) => e.t >= rec.t_down - 1000 && e.t <= (rec.t_up === null ? rec.t_down : rec.t_up) + MAX_AFTER_UP_MS).map((e) => ({ ...e, t: round(e.t / 1000 - td, 3) })),
      gl_mode: rec.gl_mode, gl_query: new URLSearchParams(location.search).get("gl"),
      ua: navigator.userAgent, page_version: (() => { const t = document.querySelector('script[src^="view.js"]'); const m = t && /v=([0-9]+)/.exec(t.getAttribute("src")); return m ? m[1] : null; })(),
      tab_lens: (() => { const t = document.querySelector('script[src*="tab-lens.js"]'); return { src: t ? t.getAttribute("src") : null, loaded: !!window.__tabLensStep, mode: window.__tabLensGL ? (window.__tabLensGL() ? "geometry+gl" : "geometry") : null, sw: !!(navigator.serviceWorker && navigator.serviceWorker.controller), rm: matchMedia("(prefers-reduced-motion: reduce)").matches, err: window.__tabLensErr || null }; })(),   // #15: which tab-lens.js the device runs and whether the driver is present
      trigger: q.has("accept") ? "?accept" : q.has("diag") ? "?diag" : q.has("segframes") ? "?segframes" : "localStorage ark-diag", kind: rec.kind || "gesture" };
    out.record_id = rid(); out.marks = rec.marks || [];
    emit(out, true);                                              // rich records keep popping the copy / share sheet (2号 / 老网页 flows, ?accept)
    lastNote = `${frames.length}fr ok`;
  }
  /* ---- 件 A: the light record's own output ------------------------------------------------------------------------------------------- */
  function finishLight(why) {
    rec.done = true; if (rec.mo) { rec.mo.disconnect(); delete rec.mo; }
    const td = rec.t_down / 1000, tu = (rec.t_up === null ? rec.t_down : rec.t_up) / 1000;
    const st = rec.frames.map((f) => f.sample_t ?? f.pts), gaps = st.slice(1).map((v, i) => v - st[i]).filter((g) => g > 0).sort((a, b) => a - b);
    const interval = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 1 / 60;
    let lastScene = null;
    const frames = rec.frames.map((f) => {
      const sm = f.sample_t ?? f.pts, pt = sm + interval, sc = JSON.stringify(f.scene);
      const o = { frame: f.frame, pts: round(pt, 3), t_since_down: round(pt - td, 3), t_since_up: round(pt - tu, 3), phase: phaseAt(pt * 1000),
                  rect: f.rect, alpha: f.alpha, scale: f.scale, transform: f.transform, bg: f.bg, anims: f.anims, cls: f.cls,   // bg: 数据 17:3x — read but never written
                  last_pointer_t: f.last_pointer_t === null || f.last_pointer_t === undefined ? null : round(f.last_pointer_t / 1000 - td, 3) };
      if (f.gone) o.gone = true;
      if (sc !== lastScene) { o.scene = f.scene; lastScene = sc; }  // only the frames where the visible scene changed carry it
      return o;
    });
    const moved = frames.find((f) => f.t_since_down >= 0 && f.rect && rec.rest && changed(f.rect, rec.rest, 0.3));
    const out = { kind: "light", record_id: rid(), name: rec.name, control: rec.control, marks: rec.marks, stopped_by: why,
      t_down_pts: round(td, 3), t_up_pts: round(tu, 3), moves_since_down: rec.moves.map((m) => round(m / 1000 - td, 3)),
      control_events: rec.events, scene0: rec.scene0, first_change_since_down: moved ? moved.t_since_down : null, frames,
      pointer: rec.pointer.map((x) => ({ ...x, t: round(x.t / 1000 - td, 3) })), frame_interval: round(interval, 4),
      viewport: `${innerWidth}×${innerHeight}`, standalone: matchMedia("(display-mode: standalone)").matches, a11y: a11yNow(), href: location.href, at: new Date().toISOString(),
      vp_events: vpEvents.filter((e) => e.t >= rec.t_down - 1000 && e.t <= (rec.t_up === null ? rec.t_down : rec.t_up) + MAX_AFTER_UP_MS).map((e) => ({ ...e, t: round(e.t / 1000 - td, 3) })),
      ua: navigator.userAgent, page_version: pageVersion(), trigger: triggerName(), longtask_supported: longtaskSupported,
      time_semantics: "pts = presentation time = the sampling frame's rAF timestamp + frame_interval; t_since_down / t_since_up from pts" };
    emit(out, false);                                             // no sheet for a light record: the user taps a lot of controls; the line + the upload report instead
    lastNote = `${frames.length}fr light`;
  }
  const pageVersion = () => { const t = document.querySelector('script[src^="view.js"]'); const m = t && /v=([0-9]+)/.exec(t.getAttribute("src")); return m ? m[1] : null; };
  const triggerName = () => (q.has("accept") ? "?accept" : q.has("diag") ? "?diag" : q.has("segframes") ? "?segframes" : "localStorage ark-diag");
  function emit(out, popSheet) {
    try { localStorage.setItem(KEY, JSON.stringify(out)); } catch {}
    window.__segFrames = out; lastOut = out; lastOutAt = performance.now();
    dispatchEvent(new CustomEvent(popSheet ? "segframes" : "segframes-light", { detail: out }));
    upload(out);
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
      if (rec.kind === "light") {
        const sceneSame = prev && JSON.stringify(prev.scene) === JSON.stringify(f.scene);
        if (prev && !sceneSame) rec.events.push({ t_since_down: round((now - rec.t_down) / 1000, 3), events: "sceneChanged", scene: f.scene });
        if (now - rec.t_down >= HARD_MS) { finishLight("10 s 硬上限"); return; }
        if (rec.t_up !== null) {
          const still = sceneSame && f.rect && prev.rect && !changed(f.rect, prev.rect, SETTLE_PT) && f.alpha === prev.alpha && f.transform === prev.transform && f.bg === prev.bg && !f.anims;
          rec.settledSince = still ? (rec.settledSince ?? now) : null;
          if (rec.settledSince !== null && now - rec.settledSince >= SETTLE_MS) finishLight("静止 300 ms");
          else if (now - rec.t_up >= MAX_AFTER_UP_MS) finishLight("抬手后 3 s");
        }
        return;
      }
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
    const r = rec && !rec.done && rec.kind === "light" ? lightReading(now) : reading(now);
    if (r) cur = { frame: frameNo, ...r, phase: phaseAt(now), samples: (cur && cur.frame === frameNo ? cur.samples : 0) + 1, after_others: othersThisFrame };
  }
  /* ---- 件 B (BOARD/派单-真机核-界面): 「就是这里」 ---------------------------------------------------------------------------------------
     A record says what happened; only the user knows which of it was wrong. The button writes his judgement into the same record:
     when, which control he had just touched, where his finger was, and one of five words. window.__diagMark(word) is the same call
     without the UI (the acceptance file uses it). A mark that arrives after the record was already sent re-sends that record under the
     same record_id, so the two copies join. */
  const MARK_WORDS = ["不该动", "动错了", "卡住了", "慢半拍", "位置不对"], MARK_WINDOW_MS = 120000;
  let stopped = false;
  function markNow(word) {
    const m = { at: new Date().toISOString(), word: word || null, since_touch: lastTouch ? round((performance.now() - lastTouch.t) / 1000, 2) : null,
                control: lastTouch ? { path: lastTouch.path, label: lastTouch.label } : null, point: lastTouch ? [lastTouch.x, lastTouch.y] : null };
    if (rec && !rec.done) { rec.marks.push(m); m.into = "running"; line("标记已记下，这次手势结束后一起送"); return m; }
    if (lastOut && performance.now() - lastOutAt <= MARK_WINDOW_MS) {
      lastOut.marks = (lastOut.marks || []).concat([m]); lastOut.marked = true; m.into = lastOut.record_id;
      try { localStorage.setItem(KEY, JSON.stringify(lastOut)); } catch {}
      dispatchEvent(new CustomEvent("segframes-mark", { detail: lastOut }));
      upload(lastOut); return m;
    }
    emit({ kind: "mark", record_id: rid(), marks: [m], at: new Date().toISOString(), href: location.href, viewport: `${innerWidth}×${innerHeight}`,
           standalone: matchMedia("(display-mode: standalone)").matches, a11y: a11yNow(), ua: navigator.userAgent, page_version: pageVersion(), trigger: triggerName() }, false);
    return m;
  }
  window.__diagMark = markNow;
  function line(t) {
    if (!DIAG_UI || !document.body) return;
    if (!lineEl) {
      lineEl = document.createElement("div"); lineEl.id = "diagline";
      lineEl.style.cssText = "position:fixed;left:12px;right:88px;bottom:calc(env(safe-area-inset-bottom, 0px) + 8px);z-index:2147483645;padding:6px 10px;border-radius:10px;background:rgba(28,28,30,.9);color:#fff;font:12px/1.35 -apple-system, ui-sans-serif, system-ui;-webkit-user-select:none;user-select:none";
      lineEl.addEventListener("click", () => { if (lastOut) dispatchEvent(new CustomEvent("segframes", { detail: lastOut })); });   // tap the line = the copy / share sheet for the latest record
      document.body.appendChild(lineEl);
      addEventListener("resize", placeLine);
    }
    lineEl.textContent = t; placeLine();
  }
  /* the line sits above the floating tab bar: at the screen's bottom it covered the first four tabs, so with diagnostics on a tap on a tab hit
     the line (opened the copy / share sheet) instead of switching (模拟器 A 18:12, 界面 自核) */
  function placeLine() {
    if (!lineEl) return;
    const nav = document.querySelector("nav.tabs"), r = nav && getComputedStyle(nav).display !== "none" ? nav.getBoundingClientRect() : null;
    lineEl.style.bottom = r && r.height ? `${Math.round(innerHeight - r.top + 8)}px` : "calc(env(safe-area-inset-bottom, 0px) + 8px)";
  }
  function buildMarkUI() {
    if (!DIAG_UI || markUI || !document.body) return;
    markUI = document.createElement("div"); markUI.id = "diagmark";
    markUI.style.cssText = "position:fixed;right:12px;bottom:calc(env(safe-area-inset-bottom, 0px) + 96px);z-index:2147483646;display:flex;flex-direction:column;align-items:flex-end;gap:8px;font:600 13px/1.15 -apple-system, ui-sans-serif, system-ui;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none";
    /* open / closed through style.display: the inline display:flex outranks the UA's [hidden]{display:none}, so toggling .hidden alone left the
       word panel open over the page from the start (模拟器 A 18:10, 界面 自核) */
    const panel = document.createElement("div"); panel.id = "diagmark-words";
    const openWords = (o) => { panel.hidden = !o; panel.style.display = o ? "flex" : "none"; };
    panel.style.cssText = "display:none;flex-direction:column;gap:6px;padding:8px;border-radius:14px;background:rgba(28,28,30,.92);color:#fff;box-shadow:0 8px 24px rgba(0,0,0,.35)";
    const word = (t, w) => { const b = document.createElement("button"); b.type = "button"; b.textContent = t;
      b.style.cssText = "all:unset;padding:8px 12px;border-radius:10px;background:rgba(255,255,255,.14);color:#fff;text-align:center";
      b.addEventListener("click", () => { markNow(w); openWords(false); }); panel.appendChild(b); };
    for (const w of MARK_WORDS) word(w, w);
    word("直接发（不选词）", null);
    const btn = document.createElement("button"); btn.type = "button"; btn.id = "diagmark-btn"; btn.textContent = "就是这里";
    btn.style.cssText = "all:unset;width:64px;height:64px;border-radius:32px;background:#ff3b30;color:#fff;display:flex;align-items:center;justify-content:center;text-align:center;box-shadow:0 6px 18px rgba(0,0,0,.35)";
    btn.addEventListener("click", () => { openWords(panel.style.display === "none"); });
    markUI.append(panel, btn); document.body.appendChild(markUI);
    line("诊断记录开着：点任意控件都会记一份；出问题按右下角「就是这里」");
  }
  if (document.body) buildMarkUI(); else addEventListener("DOMContentLoaded", buildMarkUI);

  /* ---- 件 C: the record leaves the phone by itself -----------------------------------------------------------------------------------
     One anonymous PUT into the diagnostic bucket's own prefix: no key in this page (the page is served from a public repo), a long random
     object key, and x-cos-forbid-overwrite so a key collision can never overwrite an earlier record. Anything that does not end in a 2xx
     keeps the record on the phone (localStorage queue, retried on the next upload and on the next start) and says so on the page — the
     copy / share sheet stays as the manual way out. Nothing here is silent: every state writes the line. */
  const BUCKET = q.has("accept") ? "" : (() => { let v = ""; try { v = q.get("diagbucket") || localStorage.getItem("ark-diag-bucket") || ""; } catch {} return (v || COS_BASE).trim().replace(/\/+$/, ""); })();
  const keyFor = () => { const d = new Date(), z = (n) => String(n).padStart(2, "0");
    return `diag/${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}${z(d.getSeconds())}-${rid()}.json`; };
  const readQ = () => { try { return JSON.parse(localStorage.getItem(QKEY) || "[]"); } catch { return []; } };
  const writeQ = (a) => {                                          // localStorage throws when full: drop the oldest records first and say that on the line
    let dropped = 0;
    for (;;) {
      try { localStorage.setItem(QKEY, JSON.stringify(a)); keptN = a.length; if (dropped) line(`本地存不下，扔掉最早的 ${dropped} 份；现存 ${a.length} 份`); return true; }
      catch (e) { if (!a.length) { line("本地也存不下这份记录，请用复制 / 分享"); return false; } a.shift(); dropped++; }
    }
  };
  const keep = (key, body, why) => { const a = readQ(); a.push({ key, body, why, at: new Date().toISOString() }); writeQ(a); };
  async function put(key, body) {
    const res = await fetch(`${BUCKET}/${key}`, { method: "PUT", headers: { "Content-Type": "application/json", "x-cos-forbid-overwrite": "true" }, body });
    if (!res.ok) throw new Error(`${res.status}${res.statusText ? " " + res.statusText : ""}`);
    return res;
  }
  function report(out, state, detail, key) {
    out.upload = { state, detail, key: key || null, at: new Date().toISOString() };
    try { localStorage.setItem(KEY, JSON.stringify(out)); } catch {}
    dispatchEvent(new CustomEvent("segframes-upload", { detail: out }));
    line(detail);
    if (state !== "sent" && !sheetShown) { sheetShown = true; dispatchEvent(new CustomEvent("segframes", { detail: out })); }   // the first failure of a page load opens copy / share; after that the line does it on a tap
  }
  async function flush() {
    if (!BUCKET) return;
    let a = readQ();
    while (a.length) {
      const it = a[0];
      try { await put(it.key, it.body); } catch { break; }
      a.shift(); writeQ(a); sentN++;
      line(`补送成功，本地还剩 ${a.length} 份`);
    }
  }
  async function upload(out) {
    /* 老网页 串2 ① P3 (status-老网页 09-23 18:47, OPEN.md 18:50): the record that reaches the bucket carries this phone's last self-check, as the copied one
       does (view.js showDiagSheet → lastSelfcheck(): {total, fails, failRows} or null = never run) */
    if (!("selfcheck" in out)) { try { out.selfcheck = typeof window.lastSelfcheck === "function" ? window.lastSelfcheck() : null; } catch (e) { out.selfcheck = null; } }
    let body = "";
    try { body = JSON.stringify(out); } catch (e) { report(out, "failed", "记录转不成 JSON：" + (e && e.message ? e.message : e)); return; }
    const key = keyFor(), kb = Math.round(body.length / 1024 * 10) / 10;
    if (!BUCKET) { const why = q.has("accept") ? "验收模式不往桶里写" : "收件桶地址是空的"; keep(key, body, why); report(out, "kept", `${why}，已存在手机里（共 ${keptN} 份，${kb} KB 这份）`, key); return; }
    try { await put(key, body); sentN++; report(out, "sent", `已送达 ${sentN} 份（这份 ${kb} KB）`, key); await flush(); }
    catch (e) { const why = e && e.message ? e.message : String(e); keep(key, body, why); report(out, "kept", `没送到（${why}），已存在手机里共 ${keptN} 份；点这行可复制 / 分享`, key); }
  }
  flush();

  /* the sampler keeps asking for frames for as long as it is loaded. window.__segFramesStop() gives it back: the rAF wrapper is undone, the
     self-loop ends, no new record starts, and the two overlays go away — the acceptance file loads the recorder for its own rows and hands the
     page back to the rows that follow (it is also the clean way for the diag switch to stop recording without a reload). */
  const origRAF = window.requestAnimationFrame.bind(window);
  const tick = (now) => { sample(now, false); if (!stopped) origRAF(tick); };
  const after = (now) => { if (!stopped) sample(now, true); };
  window.requestAnimationFrame = function (cb) { const id = origRAF(cb); if (!stopped && cb !== tick && cb !== after) origRAF(after); return id; };
  window.__segFramesStop = () => {
    stopped = true; rec = null; window.requestAnimationFrame = origRAF;
    for (const el of [markUI, lineEl, cv]) if (el && el.parentNode) el.parentNode.removeChild(el);
    markUI = null; lineEl = null;
    return true;
  };
  origRAF(tick);
})();
