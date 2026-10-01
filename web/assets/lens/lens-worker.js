/* lens-worker.js — the tab bar lens's GL drawing in a Dedicated Worker (动效 10-01, 验收's dispatch; BOARD/evidence/动效-1001-镜片Worker/README.md).
   Why: Chrome on Android runs the page's requestAnimationFrame at 60 Hz once no input arrives (ThrottleMainFrameTo60Hz, CL 6054335; the 120 Hz main
   frames are the input's: UrgentMainFrameForInput) — so after the finger lifts, the main-thread lens drew every other display frame. A Dedicated Worker's
   own requestAnimationFrame is not throttled (Chromium 8037 worker_animation_frame_provider.cc; phone flu 10-01 09:32: a worker rAF at 8.3 ms intervals
   after the lift while the page's fi read 16.6). tab-lens.js transfers its canvas here (transferControlToOffscreen) and keeps everything else: the springs,
   the flex, the DOM. Loaded as new Worker("assets/lens/lens-worker.js?v=…"); the same lens-webgl.js (its worker form: opts.bitmaps / loadImage / search).
   Messages in (tab-lens.js wkProxy): init {id, canvas, opts, bitmaps} · bitmaps {id, page, labels} (a redrawn backdrop) · state {id, s} (one frame's setState
   while the finger is down, s.t = that frame's epoch time: drawn ON ARRIVAL when it is newer than the state drawn last (NOW below), else at this worker's next rAF;
   the latest one wins) · table {id, t0, dt, n, rows, c} (the rest of the motion after the lift:
   t0 = node 0 on the epoch clock (performance.timeOrigin + now — the window's and the worker's timeOrigin differ), dt ms between nodes, rows = n × ROW
   Float64 [cx, w, h, p, wh, dcx, dw, dh, dp] with d* per ms; drawn at every rAF by cubic Hermite between the two nodes around the frame's own epoch time,
   held at the last node) · cancel {id} (a new input / retarget: stop at the row drawn last, then states again) · rest {id} (the driver stopped: cleared
   at the next rAF) · gesture {} / up {} / report {rid} (the per-gesture counts for fluency-rec.js: frames drawn and their intervals) · lose / restore {id}
   (WEBGL_lose_context, an instrument) · destroy {id} · draws {rid} (the last 600 draws: epoch ms, cx, w, h, lift, age ms — an instrument) · echo {on} (stats per drawn frame).
   Out: ready {id, sets} · fail {id, err} · sets {id, sets} · drew {id, r} (the first frame with p > 0 of the driver's run r) · stats {id, last, frames, set}
   (only with echo) · lost / restored {id} · report {rid, lw} · draws {rid, t}. */
importScripts("lens-webgl.js" + location.search);
const ROW = 9, inst = new Map(), bmp = new Map();
/* a frame within SNAP ms of a node IS that node: the nodes sit on the page's frame times (node 0 = a main rAF timestamp, 1/120 s apart = the display's frames), and the
   two contexts' epoch clocks (timeOrigin + rAF time) read the same frame 0.1–0.2 ms apart (headless 154: the worker's 0.13–0.27 ms early) — without the snap every
   draw interpolated 1–3 % short of its node (0.06–0.12 px at the slide's speed) */
const SNAP = 0.75;
/* a table whose node 0 lies more than ANCHOR ms AHEAD of this worker's clock at its arrival is played from its arrival instead: the page's clock is not this one
   (CDP virtual time moves the page's performance.now on its own — a node 0 seconds ahead would hold the worker on node 0, redrawing at every rAF, until the wall
   clock got there). A table that arrives late (the worker held up) keeps its own clock: it jumps to the row of the moment, in step with the page's replica and stop */
const ANCHOR = 100;
const epoch = (t) => performance.timeOrigin + t;
const k3 = (d) => (d < 12 ? 0 : d < 20 ? 1 : 2);
/* NOW (动效 10-01 ③, 验收): a finger-down state is drawn when its message arrives, not at this worker's next rAF — the main thread posts it from its own rAF, and the
   worker's rAF of that frame has usually run already (headless 154: every finger-down draw showed the previous main frame's state, age 16.6–16.7 ms, BOARD/evidence/
   动效-1001-镜片Worker c1), so the lens trailed the DOM / the finger by one frame. Drawn in the message task, the OffscreenCanvas frame is pushed when the task ends
   (no rAF in between); only a state not older (s.t) than the one drawn last is drawn, so a late message never brings an older state back; one main frame
   is one draw. The post-lift table stays on the rAF (it has no messages). ?lwnow=0 (the page's query) = the rAF as before; ?lwmark=1 = a performance.mark per draw ("lw:draw|<age ms>"). */
let NOW = true, MARK = false;
let echo = false, gid = 0, ph = 0, cnt = null, prevDraw = 0, raf = false;
const drawLog = [];   // [epoch ms, cx, w, h, lift, age ms] of every frame drawn (≤ 600): the block / curve checks' instrument
const loadImage = (src) => { let p = bmp.get(src); if (!p) { p = fetch(src).then((r) => { if (!r.ok) throw new Error("lens-worker: " + src + " " + r.status); return r.blob(); }).then((b) => createImageBitmap(b, { premultiplyAlpha: "none", colorSpaceConversion: "none" })); bmp.set(src, p); } return p; };   // kept: a restored context re-uploads from them
const summary = (L) => { const o = {}; for (const [w, s] of Object.entries(L.sets)) o[w] = { S: s.S, Sab: s.Sab, h: s.h, loaded: !!s.loaded }; return o; };
const build = (I) => {
  const o = Object.assign({}, I.opts, { bitmaps: I.bitmaps, loadImage, onSet: () => { if (I.lens) postMessage({ k: "sets", id: I.id, sets: summary(I.lens) }); } });
  const L = LensWebGL.create(I.canvas, o); if (!L) throw new Error("lens-worker: no webgl2 context");
  I.lens = L; L.ready.then(() => { if (I.lens === L) { const st = L.stats; postMessage({ k: "ready", id: I.id, sets: summary(L), warmMs: st.warmMs, stats: { labMode: st.labMode, rmax: st.rmax, labelStages: st.labelStages, labelSdf: st.labelSdf, fields: st.fields, linComp: st.linComp, prewarm: st.prewarm } }); } }, (e) => postMessage({ k: "fail", id: I.id, err: String(e && e.message || e) }));
};
const kick = () => { if (!raf) { raf = true; requestAnimationFrame(tick); } };   // one rAF chain (fluency-rec's wk lesson: chains piled up when a second one started beside a pending callback)
const herm = (a, b, ma, mb, u, h) => { const u2 = u * u, u3 = u2 * u; return (2 * u3 - 3 * u2 + 1) * a + (u3 - 2 * u2 + u) * h * ma + (-2 * u3 + 3 * u2) * b + (u3 - u2) * h * mb; };
const fromTable = (T, now) => {   // the state at epoch time now: Hermite between the nodes around it (the springs' own velocities as the tangents), the last node after the end
  let f = (now - T.t0) / T.dt; const R = T.rows, n = T.n; if (Math.abs(f - Math.round(f)) * T.dt < SNAP) f = Math.round(f); let i = Math.floor(f), u = f - i;
  if (f >= n - 1) { i = n - 1; u = 0; } else if (f < 0) { i = 0; u = 0; }
  const a = i * ROW; let cx, w, h, p, wh;
  if (u === 0) { cx = R[a]; w = R[a + 1]; h = R[a + 2]; p = R[a + 3]; wh = R[a + 4]; }
  else { const b = a + ROW, H = T.dt; cx = herm(R[a], R[b], R[a + 5], R[b + 5], u, H); w = herm(R[a + 1], R[b + 1], R[a + 6], R[b + 6], u, H); h = herm(R[a + 2], R[b + 2], R[a + 7], R[b + 7], u, H);
    p = herm(R[a + 3], R[b + 3], R[a + 8], R[b + 8], u, H); wh = R[a + 4] + (R[b + 4] - R[a + 4]) * u; }
  p = Math.max(0, Math.min(1, p)); const c = T.c;
  return { s: { cx, cy: c.cy, w, h, lift: p, pd: p, wh, platter: { rgba: c.rgba, alpha: 1 - p }, items: { scale: 1 + (c.item - 1) * p, cy: c.icy, cx: c.icx }, t: T.t0 + f * T.dt }, end: f >= n - 1, f };
};
const draw = (I, s, ts, rest) => {
  I.lens.setState(s); I.last = rest ? null : s; const t = epoch(ts); if (!rest && s.t != null) I.lastT = s.t; if (MARK) performance.mark("lw:draw|" + (s.t != null ? (t - s.t).toFixed(1) : "") + (rest ? "|rest" : ""));   // the instrument: the name carries the drawn state's age (ms)
  if (I.id === inst.active && !rest) {   // the rest clear is not a motion frame: not counted (it comes when the main thread stops, after the table's end)
    if (cnt) { cnt.n++; if (prevDraw) { const d = t - prevDraw; cnt[ph][k3(d)]++; if (d > cnt.m) cnt.m = d; } prevDraw = t; }
    drawLog.push([t, s.cx, s.w, s.h, s.lift, s.t == null ? null : t - s.t]); if (drawLog.length > 600) drawLog.shift();   // + the age of what was drawn: this frame − the state's own time (a main frame's state: one frame while the finger is down)
  }
  if (s.lift > 0 && I.r != null && I.drewR !== I.r) { I.drewR = I.r; postMessage({ k: "drew", id: I.id, r: I.r }); }   // the driver run's first lifted frame on the canvas: the page may hide its glide now
  if (echo) { const st = I.lens.stats; postMessage({ k: "stats", id: I.id, last: st.last, frames: st.frames, set: st.set, q: I.q }); }   // q: the page's message this frame answers (the proxy drops answers older than its last rest)
};
const tick = (ts) => {
  raf = false; let more = false; const now = epoch(ts);
  for (const I of inst.values()) {
    if (!I.lens || I.lost) continue;
    try {
      if (I.rest) { I.rest = false; I.table = null; I.pending = null; draw(I, { cx: 0, cy: 0, w: 82, h: 54, lift: 0 }, ts, true); continue; }
      if (I.table) { const r = fromTable(I.table, now); draw(I, r.s, ts); I.tableF = r.f; if (!r.end) more = true; else I.table = null; continue; }
      if (I.pending) { const s = I.pending; I.pending = null; if (!(s.t != null && I.lastT != null && s.t < I.lastT)) draw(I, s, ts); }   // never an older state than the one drawn last
    } catch (e) { postMessage({ k: "err", id: I.id, err: String(e && e.stack || e) }); }
  }
  if (more) kick();
};
self.onmessage = (e) => {
  const m = e.data, I = m.id != null ? inst.get(m.id) : null;
  try {
    switch (m.k) {
      case "init": {
        { const qs = new URLSearchParams(m.opts.search || ""); NOW = qs.get("lwnow") !== "0"; MARK = qs.get("lwmark") === "1"; }
        const J = { id: m.id, canvas: m.canvas, opts: m.opts, bitmaps: m.bitmaps, lens: null, lost: false, table: null, pending: null, rest: false };
        inst.set(m.id, J);
        /* context loss (WebGL 1.0 §5.15.2: preventDefault on webglcontextlost or no restore ever comes): rebuilt on restore — the shaders, the maps from the kept
           bitmaps, the backdrop from the last ImageBitmaps; the last frame drawn again */
        m.canvas.addEventListener("webglcontextlost", (ev) => { ev.preventDefault(); J.lost = true; postMessage({ k: "lost", id: J.id }); });
        m.canvas.addEventListener("webglcontextrestored", () => { J.lost = false; try { build(J); J.lens.ready.then(() => { if (J.last && !J.table) { J.pending = J.last; kick(); } else if (J.table) kick(); postMessage({ k: "restored", id: J.id }); }); } catch (x) { postMessage({ k: "fail", id: J.id, err: String(x && x.message || x) }); } });
        try { build(J); } catch (x) { inst.delete(m.id); postMessage({ k: "fail", id: m.id, err: String(x && x.message || x) }); }
        break; }
      case "bitmaps": if (I) { I.bitmaps = { page: m.page, labels: m.labels }; if (I.lens && !I.lost) I.lens.setBitmaps(I.bitmaps); if (I.last && I.last.lift > 0) { I.pending = I.pending || I.last; kick(); } } break;
      case "active": inst.active = m.id; break;
      case "state": if (I) { I.q = m.q; I.r = m.s.r; I.table = null; I.rest = false;
        if (NOW && I.lens && !I.lost && I.id === inst.active && m.s.t != null && !(I.lastT != null && m.s.t < I.lastT)) { I.pending = null; draw(I, m.s, performance.now()); }   // on arrival: this frame (NOW above); its ts = the draw's own time
        else { I.pending = m.s; kick(); } } break;
      case "table": if (I) { const now = epoch(performance.now()), late = now - m.t0; I.q = m.q; I.table = { t0: late < -ANCHOR ? now : m.t0, dt: m.dt, n: m.n, rows: m.rows, c: m.c, late }; I.r = m.r; I.pending = null; I.rest = false; kick(); } break;
      case "cancel": if (I) I.table = null; break;   // the row drawn last stays on the canvas until the next state
      case "rest": if (I) { I.q = m.q; I.rest = true; I.table = null; I.pending = null; kick(); } break;
      case "gesture": gid = m.gid; ph = 0; prevDraw = 0; cnt = { n: 0, 0: [0, 0, 0], 1: [0, 0, 0], m: 0 }; break;
      case "up": ph = 1; break;
      case "report": postMessage({ k: "report", rid: m.rid, lw: cnt ? { n: cnt.n, d: cnt[0], u: cnt[1], max: Math.round(cnt.m * 10) / 10 } : null }); break;
      case "draws": postMessage({ k: "draws", rid: m.rid, t: drawLog.slice() }); break;
      case "echo": echo = !!m.on; break;
      case "lose": if (I && I.lens) { I.lx = I.lens.gl.getExtension("WEBGL_lose_context"); I.lx.loseContext(); } break;
      case "restore": if (I && I.lx) I.lx.restoreContext(); break;
      case "destroy": if (I) { inst.delete(m.id); try { I.lens && I.lens.destroy(); } catch (x) {} } break;
    }
  } catch (x) { postMessage({ k: "err", id: m.id, err: String(x && x.stack || x) }); }
};
