/* crash-rec.js — the always-on freeze & error recorder (the user approved it 2026-09-28, input-box contents allowed in the record).
   When the page errors or freezes on his phone the evidence is kept on the phone and PUT to the diagnostic bucket by itself — at once when
   the network allows, else on the next start. He does nothing. Loaded on every page load by index.html (first external script, in <head>,
   so the other scripts' errors are caught), independent of ?diag.

   WHAT IS RECORDED
   · errors: window "error" and "unhandledrejection" — message, file:line:col, stack (the file's query / hash stripped);
   · actions: a ring of the last RING_N user actions — at, tab, control (tag#id.class + its words), kind (down / tap / change / scroll),
     value (input / select / checkbox; inputs ARE recorded — the user's order — except the PIN field #s-pin (view.js first-use form) and
     any type=password, which never are);
   · stalls: a setInterval heartbeat every BEAT_MS; a gap over STALL_MS while the page is visible = the main thread was blocked. Time in the
     background is taken out: every visibilitychange / pagehide / pageshow restarts the baseline, a tick while hidden is ignored, and a gap
     seen by a tick is only reported when the NEXT tick confirms nothing about visibility changed in between (iOS may run the first timer
     of a resumed page before it delivers visibilitychange). A freeze the user escapes by leaving the app is caught by the hide handler: it
     is the first code to run after the blocked task, and a gap before it is a stall. No requestAnimationFrame loop and no rAF wrapper —
     the page keeps its idle frames;
   · unclean exit: a marker {sid, beat, vis, ended} in localStorage (throttled, at most every PERSIST_MS). The next start reports the
     previous session as "died while frozen" only when its last beat was while visible and no hide / pagehide came after it — a page
     swiped away from the app switcher was hidden first, a reload / navigation fires pagehide, so neither is reported.
   Every record carries the page's ?v= stamp, the userAgent and location without query / hash (the no-typing login link carries the key
   there). Not recorded: localStorage, the URL's query / hash, the PIN.

   WHERE IT GOES: an anonymous PUT into the diagnostic bucket's diag/crash/ prefix — the same bucket, CORS rule and forbid-overwrite as
   seg-frames-logger.js 件 C (its header: the bucket admits PUT on diag/* from https://herclyon1.github.io; the same key twice = 409
   FileAlreadyExists, so every key is timestamp + 16 random hex, and a 409 means an earlier try already landed). Records wait in
   localStorage (QKEY, QUEUE_N newest, BODY_MAX each) until a PUT answers 2xx; the queue is retried at every start. Nothing is sent
   without an error, a stall or an unclean exit. localStorage["ark-diag-bucket"] / ?crashbucket= override the bucket (a localhost page
   cannot pass the bucket's CORS: scripts/mac flu-forward.py stands in). Under ?accept (the self-check clicks through the page) and in
   iframes it does nothing. Reading them back: scripts/mac/diag-pull.py (keys land under ~/Claude/ark-diag/crash/).

   window.CrashRec = {actions, incidents, queue(), flush(), sid}. Every handler is wrapped: the recorder never throws into the page. */
(function () {
  try {
    if (window.top !== window || window.CrashRec) return;
    const q = new URLSearchParams(location.search);
    if (q.has("accept")) return;
    const RING_N = 50, BEAT_MS = 500, STALL_MS = 1000, PERSIST_MS = 1500, SETTLE_MS = 2500, QUEUE_N = 10, BODY_MAX = 60000,
      INC_MAX = 30, REC_MAX = 6, VAL_MAX = 200;
    const RKEY = "ark-crash-ring", MKEY = "ark-crash-alive", QKEY = "ark-crash-queue";
    const BUCKET = (() => { let v = ""; try { v = q.get("crashbucket") || localStorage.getItem("ark-diag-bucket") || ""; } catch (e) {}
      return (v || "https://ark-diag-1315873325.cos.ap-shanghai.myqcloud.com").trim().replace(/\/+$/, ""); })();
    const fetch0 = window.fetch && window.fetch.bind(window);
    const ver = (() => { try { const s = (document.currentScript && document.currentScript.src) || ""; const m = /[?&]v=([^&#]+)/.exec(s); return m ? m[1] : "本地"; } catch (e) { return "?"; } })();
    const hex = (n) => { try { return Array.from(crypto.getRandomValues(new Uint8Array(n)), (b) => b.toString(16).padStart(2, "0")).join(""); }
      catch (e) { let s = ""; while (s.length < n * 2) s += Math.random().toString(16).slice(2); return s.slice(0, n * 2); } };
    const sid = hex(4);
    const get = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
    const set = (k, v) => { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } };
    const parse = (s, d) => { try { return s ? JSON.parse(s) : d; } catch (e) { return d; } };
    const bare = (u) => { try { return String(u || "").replace(/[?#].*$/s, ""); } catch (e) { return ""; } };
    const cut = (s, n) => { s = s == null ? "" : String(s); return s.length > n ? s.slice(0, n) + "…" : s; };
    const iso = (t) => { try { return new Date(t).toISOString(); } catch (e) { return String(t); } };
    const now = () => performance.now();

    /* ---- where the user is ---- */
    const tabNow = () => { try {
      const b = document.querySelector("nav.tabs button.on"); let t = b ? (b.dataset.tab || b.textContent.trim()) : (get("ark-remote-tab") || "");
      const sp = document.getElementById("subpage"); if (sp && !sp.hidden) { const pt = sp.querySelector(".ptitle"); t += " › " + cut(pt ? pt.textContent.trim() : "推入页", 30); }
      const sh = document.querySelector(".sheet.open, .sheet[open], dialog[open]"); if (sh) t += " + " + (sh.id ? "#" + sh.id : sh.tagName.toLowerCase());
      return t;
    } catch (e) { return ""; } };
    const PIN = (el) => !!el && (el.id === "s-pin" || (el.type || "").toLowerCase() === "password");
    const ctlOf = (t) => { try {
      const hit = t && t.closest ? t.closest("button, a, input, select, textarea, label, [role=button], [role=tab], [role=switch], .row, .cell, li") : null, el = hit || t;
      if (!el || !el.tagName) return { el: null, d: String(t && t.nodeName || "?") };
      const cls = typeof el.className === "string" && el.className.trim() ? "." + el.className.trim().split(/\s+/).slice(0, 3).join(".") : "";
      let words = el.getAttribute("aria-label") || "";
      if (!words && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) { const row = el.closest(".row"); const lb = row && row.querySelector("label"); words = (lb && lb.textContent) || el.placeholder || el.name || ""; }
      if (!words && hit) words = el.textContent || "";              // a bare container (html / body / a section) carries no words: its text is the whole page
      return { el, d: `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${cls} ${cut(words.replace(/\s+/g, " ").trim(), 40)}`.trim() };
    } catch (e) { return { el: null, d: "?" }; } };
    const valOf = (el) => { try {
      if (!el || !el.tagName) return undefined;
      if (PIN(el)) return "[不记]";
      if (el.tagName === "SELECT") { const o = el.options[el.selectedIndex]; return cut(o ? o.text : el.value, VAL_MAX); }
      if (el.tagName === "INPUT" && /^(checkbox|radio)$/i.test(el.type)) return el.checked;
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") return cut(el.value, VAL_MAX);
      if (el.isContentEditable) return cut(el.textContent, VAL_MAX);
    } catch (e) {} return undefined; };

    /* ---- the action ring (persisted on every action: it must survive a page that never comes back) ---- */
    const actions = parse(get(RKEY), null);
    const prevRing = actions && actions.sid ? actions : null;
    const ring = [];
    const persistRing = () => set(RKEY, JSON.stringify({ sid, a: ring }));
    const act = (kind, t, extra) => { try {
      const c = ctlOf(t), a = { at: Date.now(), pn: Math.round(now()), tab: tabNow(), kind, ctl: c.d };
      const v = valOf(c.el && /^(INPUT|SELECT|TEXTAREA)$/.test(c.el.tagName) ? c.el : t); if (v !== undefined) a.value = v;
      if (extra) Object.assign(a, extra);
      let down = null;                                                // one entry per tap: the click turns its own pointerdown (one of the last 3 entries) into "tap"
      if (kind === "tap") for (let i = ring.length - 1; i >= Math.max(0, ring.length - 3); i--) { const d = ring[i]; if (d.kind === "down" && d.ctl === a.ctl && a.at - d.at < 1500) { down = d; break; } }
      if (down) { down.kind = "tap"; down.up_ms = a.at - down.at; if (v !== undefined) down.value = v; }
      else { ring.push(a); if (ring.length > RING_N) ring.splice(0, ring.length - RING_N); }
      persistRing();
    } catch (e) {} };
    let scrollAt = -1e9;
    const on = (tgt, ev, fn, opt) => { try { tgt.addEventListener(ev, (e) => { try { fn(e); } catch (x) {} }, opt); } catch (e) {} };
    on(document, "pointerdown", (e) => act("down", e.target), { capture: true, passive: true });
    on(document, "click", (e) => act("tap", e.target), { capture: true, passive: true });
    on(document, "change", (e) => act("change", e.target), { capture: true, passive: true });
    on(document, "scroll", (e) => { const t = now(); if (t - scrollAt > 800) act("scroll", e.target === document ? document.documentElement : e.target, { y: Math.round(scrollY) }); scrollAt = t; }, { capture: true, passive: true });

    /* ---- incidents: errors and stalls; one record per burst (SETTLE_MS after the last one) ---- */
    const incidents = [];
    let pending = [], settleT = 0, recN = 0;
    const incident = (x) => { try {
      x.at = x.at || Date.now(); x.tab = tabNow(); incidents.push(x);
      if (pending.length < INC_MAX) pending.push(x); else pending[INC_MAX - 1].more = (pending[INC_MAX - 1].more || 0) + 1;
      clearTimeout(settleT); settleT = setTimeout(seal, SETTLE_MS);
    } catch (e) {} };
    const base = () => ({ kind: "crash-rec", v: ver, sid, ua: navigator.userAgent, url: bare(location.href), at: iso(Date.now()),
      standalone: (() => { try { return navigator.standalone === true || matchMedia("(display-mode: standalone)").matches; } catch (e) { return null; } })(),
      viewport: [innerWidth, innerHeight, devicePixelRatio || 1], online: navigator.onLine });
    function seal() { try {
      if (!pending.length) return;
      if (cand && !seal.late) { seal.late = true; settleT = setTimeout(seal, BEAT_MS + 100); return; }   // a gap waits for its confirming tick: same burst, same record
      seal.late = false;
      const inc = pending; pending = [];
      if (recN >= REC_MAX) return; recN++;
      const r = Object.assign(base(), { reasons: [...new Set(inc.map((x) => x.type))], incidents: inc, tab: tabNow(), actions: ring.slice() });
      enqueue(r); flush();
    } catch (e) {} }
    on(window, "error", (e) => { if (e.error == null && !e.message && e.target && e.target !== window) return;   // a failed <img>/<script> load: not a script error
      const st = e.error && e.error.stack; incident({ type: "error", message: cut(e.message, 500), file: bare(e.filename), line: e.lineno, col: e.colno, stack: st ? cut(String(st).replace(/\?[^\s:)]*/g, ""), 3000) : null }); });
    on(window, "unhandledrejection", (e) => { const r = e.reason, st = r && r.stack;
      incident({ type: "rejection", message: cut(r && r.message ? r.message : (() => { try { return typeof r === "string" ? r : JSON.stringify(r); } catch (x) { return String(r); } })(), 500),
        stack: st ? cut(String(st).replace(/\?[^\s:)]*/g, ""), 3000) : null }); });

    /* ---- heartbeat ---- */
    let visible = document.visibilityState !== "hidden", last = now(), epoch = 0, cand = null, persistAt = -1e9;
    const marker = (ended) => set(MKEY, JSON.stringify({ sid, v: ver, beat: Date.now(), vis: visible ? "visible" : "hidden", ended: !!ended, tab: tabNow() }));
    /* ms = the heartbeat gap (tick to tick, or tick to the hide handler); the page was blocked for at least ms − BEAT_MS of it */
    const stall = (gap, how, end) => { end = end || Date.now(); incident({ type: "stall", ms: Math.round(gap), blocked_min_ms: Math.max(0, Math.round(gap - BEAT_MS)), how, at: end - Math.round(gap), ended_at: end,
      before: ring.filter((a) => a.at <= end).slice(-10) }); };
    const beat = () => { try {
      const t = now(), gap = t - last;
      if (cand && cand.epoch === epoch && visible) stall(cand.gap, "timer", cand.end);   // the tick after the gap saw no visibility change: a real stall
      cand = null;
      if (visible && gap > STALL_MS) cand = { gap, epoch, end: Date.now() };
      last = t;
      if (t - persistAt >= PERSIST_MS) { persistAt = t; marker(false); }
    } catch (e) {} };
    setInterval(beat, BEAT_MS);
    const vis = (hide, why) => { try {
      const t = now();
      if (hide && visible && t - last > STALL_MS) stall(t - last, why);   // the hide handler is the first code to run after a blocked task
      if (hide && pending.length) seal();                                 // keep what this burst has before the page may be frozen / killed
      epoch++; cand = null; visible = !hide && document.visibilityState !== "hidden"; last = t;
      persistAt = t; marker(hide);
    } catch (e) {} };
    on(document, "visibilitychange", () => vis(document.visibilityState === "hidden", "hide"));
    on(window, "pagehide", () => vis(true, "pagehide"));
    on(window, "pageshow", () => vis(false, "pageshow"));

    /* ---- the queue ---- */
    const readQ = () => { const a = parse(get(QKEY), []); return Array.isArray(a) ? a : []; };
    const writeQ = (a) => { while (a.length > QUEUE_N) a.shift(); for (;;) { if (set(QKEY, JSON.stringify(a))) return; if (!a.length) return; a.shift(); } };
    const keyFor = () => { const d = new Date(), z = (n) => String(n).padStart(2, "0");
      return `diag/crash/${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}${z(d.getSeconds())}-${hex(8)}.json`; };
    function enqueue(r) { try {
      let body = JSON.stringify(r);
      if (body.length > BODY_MAX) { r.actions = r.actions.slice(-15); r.truncated = true; body = JSON.stringify(r); }
      if (body.length > BODY_MAX) { r.incidents = r.incidents.slice(0, 5); body = JSON.stringify(r); }
      const a = readQ(); a.push({ key: keyFor(), body, tries: 0 }); writeQ(a);
    } catch (e) {} }
    let busy = false, sent = 0, lastErr = null;
    async function flush() {
      if (busy || !fetch0 || !BUCKET) return; busy = true;
      try {
        for (;;) {
          const a = readQ(); if (!a.length) break;
          const it = a[0]; let ok = false;
          try { const r = await fetch0(`${BUCKET}/${it.key}`, { method: "PUT", headers: { "Content-Type": "application/json", "x-cos-forbid-overwrite": "true" }, body: it.body });
            ok = r.ok || r.status === 409; lastErr = ok ? null : r.status; } catch (e) { lastErr = String(e && e.message || e); }
          const b = readQ(), i = b.findIndex((x) => x.key === it.key);
          if (ok) { if (i >= 0) b.splice(i, 1); writeQ(b); sent++; continue; }
          if (i >= 0) { b[i].tries = (b[i].tries || 0) + 1; writeQ(b); }
          break;                                                          // offline / refused: the rest waits for the next start
        }
      } finally { busy = false; }
    }

    /* ---- the previous session ---- */
    const prev = parse(get(MKEY), null);
    if (prev && prev.sid && prev.vis === "visible" && !prev.ended) {
      const r = Object.assign(base(), { reasons: ["unclean-exit"], incidents: [{ type: "unclean-exit", prev_sid: prev.sid, prev_v: prev.v, last_beat: iso(prev.beat),
        tab: prev.tab, since_last_beat_ms: Date.now() - prev.beat }], tab: prev.tab, actions: prevRing && prevRing.sid === prev.sid ? prevRing.a || [] : [] });
      enqueue(r);
    }
    marker(false); persistRing();
    setTimeout(flush, 1500);                                              // after the page's own start
    on(window, "online", () => flush());

    window.CrashRec = { sid, actions: ring, incidents, queue: readQ, flush, get sent() { return sent; }, get lastErr() { return lastErr; } };
  } catch (e) {}
})();
