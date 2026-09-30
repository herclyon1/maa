/* crash-rec.js — the always-on freeze & error recorder (the user approved it 2026-09-28, input-box contents allowed in the record).
   When the page errors or freezes on his phone the evidence is kept on the phone and PUT to the diagnostic bucket by itself — at once when
   the network allows, else on the next start. He does nothing. Loaded on every page load by index.html (first external script, in <head>,
   right after the ?accept / ?diag URL rewrite, so every later script's error is caught), independent of ?diag.

   WHAT IS RECORDED
   · errors: window "error" and "unhandledrejection" — message, file:line:col, stack. Identical ones (type + message + file:line:col) are
     one entry with a count, first_at / last_at;
   · actions: a ring of the last RING_N user actions — at, tab, control (tag#id.class + its words), kind (down / tap / change / scroll),
     value (input / select / checkbox; inputs ARE recorded — the user's order — except secret fields, by rule: type=password, or an id /
     name / placeholder / aria-label / autocomplete / row label matching SECRET — which covers the first-use PIN #s-pin in view.js);
   · gaps: a setInterval heartbeat every BEAT_MS; EVERY tick-to-tick gap over STALL_MS is kept (GAPS_N newest), tagged: vis (the page's
     visibility when the gap began; hidden gaps are the app in the background), vis_changed (a visibilitychange / pagehide / pageshow came
     during it), focused / focus_changed (window focus / blur), dialog (a native alert / confirm / prompt was open during it — view.js
     still calls confirm() without <dialog> and prompt() for the copy-link / token paste fallbacks; the page blocks inside those, it is not
     frozen), phase ("load" until 1 s after window load, then "interaction"). A gap is a STALL — the thing that triggers an upload — only
     when it began visible, no visibility event came during it (confirmed by the NEXT tick: iOS may run the first timer of a resumed page
     before it delivers visibilitychange) and no native dialog overlapped it. Focus is a tag only. A freeze the user escapes by leaving
     the app is judged by the hide event's own timeStamp (see vis()). No requestAnimationFrame loop and no rAF wrapper: the page keeps its
     idle frames;
   · unclean exit: a marker {sid, beat, vis, ended} in localStorage (heartbeat writes throttled to PERSIST_MS; visibilitychange(hidden)
     and pagehide write at once). The next start reports the previous session as "died while frozen" only when its last beat was while
     visible and no hide / pagehide came after it — a page swiped away from the app switcher was hidden first, a reload / navigation
     fires pagehide, so neither is reported — AND that last beat is older than 2 × PERSIST_MS. The marker is one shared key: a second
     tab of the page (iOS Safari "Open in Background") starting while another tab is alive and visible reads that live tab's fresh
     marker (a live visible tab rewrites its beat at least every PERSIST_MS), which is not a death. A missing / non-numeric beat is not
     reported. Known loss: a page that crashes without freezing and is reloaded within ~3 s is not reported — outside the target, which
     is freeze-then-death (the beat stopped at the freeze, long before the next start).

   NO KEYS IN A RECORD: every recorded string (error message / file / stack, input values, label words, location) goes through scrub():
   everything from a ? or # up to the next space / quote / bracket / colon goes (the no-typing login link carries the key in its #k=, and an
   inline-script error names the page URL as its file), and any run of 32+ token characters becomes […] (a pasted token that a JSON.parse
   error quotes back). The copy-link fallback is a native prompt(): its text never reaches the page's DOM, so it is never read.

   FLOOD CONTROL: one record per page load (all of this load's errors and stalls, updated in place while unsent), uploaded at most once
   per load — plus one more upload when a stall comes after that; anything later stays queued for the next start. At most DAY_MAX PUTs
   a day (ark-crash-day); over it the queue waits for tomorrow.
   STORAGE: the recorder's own keys (ark-crash-*) stay under OWN_MAX bytes together; only its own oldest queued records are evicted,
   never another key; a full localStorage (QuotaExceeded) is swallowed.

   WHERE IT GOES: an anonymous PUT into the diagnostic bucket's diag/crash/ prefix — the same bucket, CORS rule and forbid-overwrite as
   seg-frames-logger.js 件 C (its header: the bucket admits PUT on diag/* from https://herclyon1.github.io; the same key twice = 409
   FileAlreadyExists, so every key is timestamp + 16 random hex, and a 409 means an earlier try already landed). Nothing is sent without
   an error, a stall or an unclean exit. ?diagbucket= / localStorage["ark-diag-bucket"] override the bucket (a localhost page cannot pass
   the bucket's CORS). Under ?accept (the self-check clicks through the page) and in iframes it does nothing. Reading them back:
   scripts/mac/diag-pull.py (keys land under ~/Claude/ark-diag/crash/).

   window.CrashRec = {sid, actions, gaps, record, queue(), flush(), sent, lastErr, day()}. Every handler is wrapped: the recorder never
   throws into the page. */
(function () {
  try {
    if (window.top !== window || window.CrashRec) return;
    const q = new URLSearchParams(location.search);
    if (q.has("accept")) return;
    const RING_N = 50, BEAT_MS = 500, STALL_MS = 1000, PERSIST_MS = 1500, SETTLE_MS = 2500, SAVE_MS = 1000, GAPS_N = 20, INC_MAX = 30,
      VAL_MAX = 200, OWN_MAX = 100000, RING_MAX = 25000, BODY_MAX = 40000, DAY_MAX = 12;
    const RKEY = "ark-crash-ring", MKEY = "ark-crash-alive", QKEY = "ark-crash-queue", DKEY = "ark-crash-day";
    const SECRET = /pin|密码|口令|password|passwd|key|token|secret/i;
    const BUCKET = (() => { let v = ""; try { v = q.get("diagbucket") || localStorage.getItem("ark-diag-bucket") || ""; } catch (e) {}
      return (v || "https://ark-diag-1315873325.cos.ap-shanghai.myqcloud.com").trim().replace(/\/+$/, ""); })();
    const fetch0 = window.fetch && window.fetch.bind(window);
    const ver = (() => { try { const s = (document.currentScript && document.currentScript.src) || ""; const m = /[?&]v=([^&#]+)/.exec(s); return m ? m[1] : "local"; } catch (e) { return "?"; } })();
    const hex = (n) => { try { return Array.from(crypto.getRandomValues(new Uint8Array(n)), (b) => b.toString(16).padStart(2, "0")).join(""); }
      catch (e) { let s = ""; while (s.length < n * 2) s += Math.random().toString(16).slice(2); return s.slice(0, n * 2); } };
    const sid = hex(4);
    const get = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
    const set = (k, v) => { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } };
    const parse = (s, d) => { try { return s ? JSON.parse(s) : d; } catch (e) { return d; } };
    const scrub = (s) => { try { return String(s == null ? "" : s).replace(/[?#][^\s"'`<>()[\]{}:,]*/g, "").replace(/[A-Za-z0-9_\-+=]{32,}/g, "[…]"); } catch (e) { return ""; } };
    const cut = (s, n) => { s = scrub(s); return s.length > n ? s.slice(0, n) + "…" : s; };
    const iso = (t) => { try { return new Date(t).toISOString(); } catch (e) { return String(t); } };
    const now = () => performance.now();

    /* ---- where the user is ---- */
    const SHEET_OPEN = ".sheet.open, .sheet[open], dialog[open]";
    /* the open sheet / dialog, first in document order: the body children but the lens filter <svg>s and topbar.js's .topbar-pocket copies (ids stripped,
       POCKET_DROP), ≈ 7600 of ≈ 8900 elements a document.querySelector walked three times a tap (down / tap / change) when nothing is open (动效 09-30:
       0.84 ms at 4× CPU; 外观 q2.py: 0.79 → 0.14 ms, same node). Sheets (index.html:918) and dialogs (:893 / :904) are body children */
    const openSheet = () => { if (document.body) for (const e of document.body.children) { const t = e.localName;
      if (t === "svg" || t === "script" || e.classList.contains("topbar-pocket")) continue;
      if (e.matches(SHEET_OPEN)) return e; const x = e.querySelector(SHEET_OPEN); if (x) return x; } return null; };
    const tabNow = () => { try {
      const b = document.querySelector("nav.tabs button.on"); let t = cut(b ? (b.dataset.tab || b.textContent.trim()) : (get("ark-remote-tab") || ""), 20);
      const sp = document.getElementById("subpage"); if (sp && !sp.hidden) { const pt = sp.querySelector(".ptitle"); t += " > " + cut(pt ? pt.textContent.trim() : "subpage", 30); }
      const sh = openSheet(); if (sh) t += " + " + (sh.id ? "#" + sh.id : sh.tagName.toLowerCase());
      return t;
    } catch (e) { return ""; } };
    const rowLabel = (el) => { try { const row = el.closest(".row"); const lb = row && row.querySelector("label"); return (lb && lb.textContent) || ""; } catch (e) { return ""; } };
    const isSecret = (el) => { try {
      if (!el || !el.tagName) return false;
      if ((el.type || "").toLowerCase() === "password") return true;
      return [el.id, el.name, el.placeholder, el.getAttribute("aria-label"), el.getAttribute("autocomplete"), rowLabel(el)].some((s) => s && SECRET.test(s));
    } catch (e) { return true; } };
    const ctlOf = (t) => { try {
      const hit = t && t.closest ? t.closest("button, a, input, select, textarea, label, [role=button], [role=tab], [role=switch], .row, .cell, li") : null, el = hit || t;
      if (!el || !el.tagName) return { el: null, d: String(t && t.nodeName || "?") };
      const cls = typeof el.className === "string" && el.className.trim() ? "." + el.className.trim().split(/\s+/).slice(0, 3).join(".") : "";
      let words = el.getAttribute("aria-label") || "";
      if (!words && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) words = rowLabel(el) || el.placeholder || el.name || "";
      if (!words && hit) words = el.textContent || "";              // a bare container (html / body / a section) carries no words: its text is the whole page
      return { el, d: `${el.tagName.toLowerCase()}${el.id ? "#" + cut(el.id, 40) : ""}${cut(cls, 60)} ${cut(words.replace(/\s+/g, " ").trim(), 40)}`.trim() };
    } catch (e) { return { el: null, d: "?" }; } };
    const valOf = (el) => { try {
      if (!el || !el.tagName) return undefined;
      if (/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) && isSecret(el)) return "[secret]";
      if (el.tagName === "SELECT") { const o = el.options[el.selectedIndex]; return cut(o ? o.text : el.value, VAL_MAX); }
      if (el.tagName === "INPUT" && /^(checkbox|radio)$/i.test(el.type)) return el.checked;
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") return cut(el.value, VAL_MAX);
    } catch (e) {} return undefined; };

    /* ---- the action ring (persisted on every action: it must survive a page that never comes back) ---- */
    const prevRing = parse(get(RKEY), null);
    const ring = [];
    const ringJson = () => { let s = JSON.stringify({ sid, a: ring }); let k = 0; while (s.length > RING_MAX && k < ring.length) { k++; s = JSON.stringify({ sid, a: ring.slice(k) }); } return s; };
    const persistRing = () => store(RKEY, ringJson());
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

    /* ---- storage: the recorder's own keys only, OWN_MAX together; the oldest queued record goes first ---- */
    const readQ = () => { const a = parse(get(QKEY), []); return Array.isArray(a) ? a : []; };
    const ownOther = () => [RKEY, MKEY, DKEY].reduce((n, k) => n + ((get(k) || "").length), 0);
    function writeQ(a) {
      for (;;) {
        const s = JSON.stringify(a);
        if ((s.length + ownOther() <= OWN_MAX || !a.length) && set(QKEY, s)) return a;
        if (!a.length) return a;
        a.shift();                                                    // over the cap or QuotaExceeded: drop our own oldest, never anyone else's key
      }
    }
    function store(k, v) {                                            // ring / marker / day: on a full localStorage make room from our own queue, else give up silently
      if (set(k, v)) return true;
      const a = readQ(); while (a.length) { a.shift(); try { localStorage.setItem(QKEY, JSON.stringify(a)); } catch (e) {} if (set(k, v)) return true; }
      return false;
    }

    /* ---- this load's record ---- */
    const base = () => ({ kind: "crash-rec", v: ver, sid, ua: navigator.userAgent, url: scrub(location.origin + location.pathname), at: iso(Date.now()),
      standalone: (() => { try { return navigator.standalone === true || matchMedia("(display-mode: standalone)").matches; } catch (e) { return null; } })(),
      viewport: [innerWidth, innerHeight, devicePixelRatio || 1], online: navigator.onLine });
    const incidents = [], gaps = [], errIndex = new Map();
    let dirty = false, stallSeq = 0, stallSentSeq = 0, loadSent = false, stallBonus = false, curKey = null, saveT = 0, settleT = 0;
    const keyFor = () => { const d = new Date(), z = (n) => String(n).padStart(2, "0");
      return `diag/crash/${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}${z(d.getSeconds())}-${hex(8)}.json`; };
    const recordNow = () => Object.assign(base(), { reasons: [...new Set(incidents.map((x) => x.type))], incidents: incidents.slice(), gaps: gaps.slice(),
      tab: tabNow(), actions: ring.slice() });
    const body = (r) => { let s = JSON.stringify(r);
      if (s.length > BODY_MAX) { r.actions = r.actions.slice(-15); r.gaps = r.gaps.slice(-5); r.truncated = true; s = JSON.stringify(r); }
      if (s.length > BODY_MAX) { r.incidents = r.incidents.slice(0, 8).map((x) => Object.assign({}, x, { stack: x.stack ? x.stack.slice(0, 600) : x.stack })); s = JSON.stringify(r); }
      return s; };
    const sentKeys = new Set(); let inflight = null;
    function save() { try {                                            // write this load's record into the queue (in place while it is still unsent)
      clearTimeout(saveT); saveT = 0;
      if (!dirty || !incidents.length) return;
      dirty = false;
      if (!curKey || sentKeys.has(curKey) || inflight === curKey) curKey = keyFor();   // already sent / being sent: later news goes in a new part
      const a = readQ(), s = body(recordNow()), i = a.findIndex((x) => x.key === curKey);
      if (i >= 0) a[i].body = s; else a.push({ key: curKey, body: s });
      writeQ(a);
    } catch (e) {} }
    const saveSoon = () => { dirty = true; if (!saveT) saveT = setTimeout(save, SAVE_MS); };
    function settle() { try {                                          // the burst is over: save, then upload if this load's budget allows
      if (cand && !settle.late) { settle.late = true; settleT = setTimeout(settle, BEAT_MS + 100); return; }   // a gap waits for its confirming tick: same burst
      settle.late = false;
      save();
      if (!loadSent) { loadSent = true; stallSentSeq = stallSeq; flush(true); }
      else if (!stallBonus && stallSeq > stallSentSeq) { stallBonus = true; stallSentSeq = stallSeq; flush(true); }
    } catch (e) {} }
    const incident = (x) => { try {
      x.tab = tabNow();
      if (x.type === "error" || x.type === "rejection" || x.type === "load") {
        const k = [x.type, x.message, x.file, x.line, x.col].join("|"), old = errIndex.get(k);
        if (old) { old.count++; old.last_at = Date.now(); saveSoon(); return; }
        x.count = 1; x.first_at = x.last_at = Date.now(); if (incidents.length >= INC_MAX) return; errIndex.set(k, x);
      } else { if (incidents.length >= INC_MAX) return; stallSeq++; }
      incidents.push(x); saveSoon();
      clearTimeout(settleT); settleT = setTimeout(settle, SETTLE_MS);
    } catch (e) {} };
    on(window, "error", (e) => { if (e.error == null && !e.message && e.target && e.target !== window) return;   // a failed <img>/<script> load: not a script error
      const st = e.error && e.error.stack; incident({ type: "error", message: cut(e.message, 500), file: cut(e.filename, 200), line: e.lineno, col: e.colno, stack: st ? cut(st, 3000) : null }); });
    /* a page script (or stylesheet) that did not load: the page then runs without it — no window.Motion / window.Menu and view.js falls back to its own
       menu, the pushed page stuck at p = 0 — and nothing else says so (the error above skips resource errors, and they do not bubble to window).
       检查 10-01, evidence/菜单外拖动-1001: headless Chrome against a backlog-5 server, 2 of 11 loads had motion.js and menu.js fail with
       net::ERR_CONNECTION_RESET; a phone on a bad network can drop a request the same way. Captured, so it reaches the window listener. */
    on(window, "error", (e) => { const t = e.target; if (!t || t === window || !t.tagName) return; const k = t.tagName;
      if (k !== "SCRIPT" && !(k === "LINK" && /stylesheet/i.test(t.rel || ""))) return;
      incident({ type: "load", message: k === "SCRIPT" ? "script did not load" : "stylesheet did not load", file: cut(t.src || t.href || "", 200), line: 0, col: 0, stack: null }); }, true);
    on(window, "unhandledrejection", (e) => { const r = e.reason, st = r && r.stack;
      incident({ type: "rejection", message: cut(r && r.message ? r.message : (() => { try { return typeof r === "string" ? r : JSON.stringify(r); } catch (x) { return String(r); } })(), 500),
        file: "", line: 0, col: 0, stack: st ? cut(st, 3000) : null }); });

    /* ---- native dialogs: the page blocks inside them, it is not frozen ---- */
    const dlg = [];                                                   // [start, end] (performance.now), end = Infinity while open
    for (const n of ["alert", "confirm", "prompt"]) { try { const o = window[n]; if (typeof o !== "function") continue;
      window[n] = function () { const d = [now(), Infinity]; dlg.push(d); if (dlg.length > 8) dlg.shift(); try { return o.apply(window, arguments); } finally { d[1] = now(); } }; } catch (e) {} }
    const dialogIn = (a, b) => dlg.some((d) => d[0] < b && d[1] > a);

    /* ---- focus and load phase (tags) ---- */
    let focused = (() => { try { return document.hasFocus(); } catch (e) { return null; } })(), focusEpoch = 0, loadedAt = document.readyState === "complete" ? now() : Infinity;
    on(window, "focus", () => { focused = true; focusEpoch++; });
    on(window, "blur", () => { focused = false; focusEpoch++; });
    on(window, "load", () => { loadedAt = now(); });
    const phaseAt = (t) => (t < loadedAt + 1000 ? "load" : "interaction");

    /* ---- heartbeat ---- */
    let visible = document.visibilityState !== "hidden", last = now(), epoch = 0, cand = null, persistAt = -1e9, focusAtLast = focused, focusEpochAtLast = 0;
    const marker = (ended) => store(MKEY, JSON.stringify({ sid, v: ver, beat: Date.now(), vis: visible ? "visible" : "hidden", ended: !!ended, tab: tabNow() }));
    const gapRec = (from, to, how) => { const g = { at: iso(Date.now() - (now() - from)), ms: Math.round(to - from), how, vis: visible ? "visible" : "hidden",
        focused: focusAtLast, focus_changed: focusEpoch !== focusEpochAtLast || undefined, dialog: dialogIn(from, to), phase: phaseAt(from), stall: false };
      gaps.push(g); if (gaps.length > GAPS_N) { const h = gaps.findIndex((x) => x.vis === "hidden"); gaps.splice(h >= 0 ? h : 0, 1); } return g; };   // background gaps go first
    const stall = (g, end) => { g.stall = true; incident({ type: "stall", ms: g.ms, blocked_min_ms: Math.max(0, g.ms - BEAT_MS), how: g.how, at: g.at, ended_at: iso(end),
      focused: g.focused, focus_changed: g.focus_changed, phase: g.phase, before: ring.filter((a) => a.at <= end).slice(-10) }); };
    const beat = () => { try {
      const t = now(), gap = t - last;
      if (cand) {                                                     // the tick after a gap: confirm it only if nothing about visibility changed since
        if (cand.epoch === epoch && visible) stall(cand.g, cand.end); else { cand.g.vis_changed = true; saveSoon(); }
        cand = null;
      }
      if (gap > STALL_MS) {
        const g = gapRec(last, t, "timer");
        if (visible && !g.dialog) cand = { g, epoch, from: last, end: Date.now() };
        else if (incidents.length && curKey && !sentKeys.has(curKey)) saveSoon();   // a tagged non-stall gap rides along in a record not yet sent (never a new part of its own)
      }
      last = t; focusAtLast = focused; focusEpochAtLast = focusEpoch;
      if (t - persistAt >= PERSIST_MS) { persistAt = t; marker(false); }
    } catch (e) {} };
    setInterval(beat, BEAT_MS);
    /* A hide right after a gap is judged by the event's own timeStamp (performance.now() when the OS raised it), not by when it ran:
       a user leaving a frozen page raised the hide DURING the gap, over STALL_MS after the last tick before it → a stall, whether the
       overdue tick (cand) or this handler ran first; iOS delivering a queued hide late after a resume raised it within a beat of the last
       tick → no stall, however long the suspension. No usable timeStamp → no stall (never report a backgrounding). */
    const vis = (hide, why, e) => { try {
      const t = now(), ts = e && Number.isFinite(e.timeStamp) && e.timeStamp > 0 && e.timeStamp <= t + 50 ? e.timeStamp : NaN;
      if (hide && visible) {
        if (cand && cand.epoch === epoch) { if (ts === ts && ts - cand.from > STALL_MS) { cand.g.how = why; stall(cand.g, cand.end); } else cand.g.vis_changed = true; }
        else if (t - last > STALL_MS) { const g = gapRec(last, t, why); g.vis_changed = true;
          if (ts === ts && ts - last > STALL_MS && !g.dialog) { g.vis_changed = undefined; stall(g, Date.now()); } }
      }
      epoch++; cand = null; visible = !hide && document.visibilityState !== "hidden"; last = t; focusAtLast = focused; focusEpochAtLast = focusEpoch;
      persistAt = t; marker(hide);                                    // immediate: the page may be frozen or killed right after this
      if (hide) { save(); persistRing(); }                        // save() is a no-op when nothing changed since the last save
    } catch (e) {} };
    on(document, "visibilitychange", (e) => vis(document.visibilityState === "hidden", "hide", e));
    on(window, "pagehide", (e) => vis(true, "pagehide", e));
    on(window, "pageshow", (e) => vis(false, "pageshow", e));

    /* ---- upload ---- */
    const today = () => { const d = new Date(); return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`; };
    const day = () => { const o = parse(get(DKEY), null); return o && o.d === today() ? o : { d: today(), n: 0 }; };
    let busy = false, sent = 0, lastErr = null, again = false;
    async function flush(mine) {                                       // mine: this load's own record may go (settle() only; start / online send earlier loads' records)
      if (!fetch0 || !BUCKET) return;
      if (busy) { again = again || !!mine; return; }                 // settle() while an earlier flush runs: its turn comes right after
      busy = true;
      try {
        for (;;) {
          const a = readQ(); if (!a.length) break;
          const dd = day(); if (dd.n >= DAY_MAX) { lastErr = "daily cap"; break; }
          const it = mine ? a[0] : a.find((x) => x.key !== curKey); if (!it) break; let ok = false;
          if (it.key === curKey && saveT) save();                     // send the newest version of this load's record
          const cur = readQ().find((x) => x.key === it.key) || it;
          inflight = cur.key;
          try { const r = await fetch0(`${BUCKET}/${cur.key}`, { method: "PUT", headers: { "Content-Type": "application/json", "x-cos-forbid-overwrite": "true" }, body: cur.body });
            ok = r.ok || r.status === 409; lastErr = ok ? null : r.status; } catch (e) { lastErr = scrub(e && e.message || e); }
          inflight = null;
          if (!ok) break;                                             // offline / refused: the rest waits for the next start
          sentKeys.add(cur.key); sent++; dd.n++; store(DKEY, JSON.stringify(dd));   // the cap counts PUTs that landed
          const b = readQ(), i = b.findIndex((x) => x.key === cur.key); if (i >= 0) b.splice(i, 1); writeQ(b);
          if (cur.key === curKey) curKey = null;                       // later news of this load starts a new part
        }
      } finally { busy = false; inflight = null; if (again) { again = false; flush(true); } }
    }

    /* ---- the previous session ---- */
    const prev = parse(get(MKEY), null);
    if (prev && prev.sid && prev.vis === "visible" && !prev.ended && Number.isFinite(prev.beat) && Date.now() - prev.beat > 2 * PERSIST_MS) {
      const r = Object.assign(base(), { reasons: ["unclean-exit"], incidents: [{ type: "unclean-exit", prev_sid: prev.sid, prev_v: prev.v, last_beat: iso(prev.beat),
        tab: prev.tab, since_last_beat_ms: Date.now() - prev.beat }], tab: prev.tab, actions: prevRing && prevRing.sid === prev.sid ? prevRing.a || [] : [], gaps: [] });
      const a = readQ(); a.push({ key: keyFor(), body: body(r) }); writeQ(a);
    }
    marker(false); persistRing();
    setTimeout(flush, 1500);                                          // the queue left by earlier loads, after the page's own start
    on(window, "online", () => flush());

    window.CrashRec = { sid, actions: ring, gaps, get record() { return recordNow(); }, queue: readQ, flush, day, get sent() { return sent; }, get lastErr() { return lastErr; } };
  } catch (e) {}
})();
