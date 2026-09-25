/* fluency-rec.js — the phone's own recorder (D78 item 5 → D79 K10–K12, BOARD/会议-全量扫-0926-结论.md; the user 09-26 04:21 「开个开关实时记录流畅度，
   然后结果交给你们看」, 04:26 「你们手机自动记录的只在出问题时这个触发点是什么，这个网站从来没有崩溃过」; always on + sent back: the user 03:05).

   The rules are not here: ScanRules.func / ScanRules.display (scan-rules.js, loaded first) are the one rule set the full scan uses too (K4 / K9).

   ALWAYS ON:
   · every gesture (pointerdown … the page at rest again) becomes one summary line (below) in an in-memory ring of 30 minutes, judged at once by
     ScanRules.func.judge (errors, dead tap 1 s, rage 3 in 2 s, undo, reopen, long frame, slow, late overlay, swallowed switch animation, pop-in);
   · after the gesture settles, the page self-check runs — ScanRules.func.check (tab bar ↔ this shift, switch drawn ↔ checked, covered controls)
     plus ScanRules.display.run (外观's display rules, level "bug" only) — at most once a second, timed; a run over 4 ms drops the display rules on
     this phone (K10 「超 4 ms 减规则」). A hit that was already there at the last run is not counted again;
   · ALL summary lines go to the diag bucket when the page goes to the background (visibilitychange → hidden, pagehide as a fallback; fetch
     keepalive, body ≤ 64 KB by the Fetch spec, so while visible a piece leaves on its own once the unsent part passes ~40 KB) — K11: when the user
     says 「刚才 X 不对」 and no rule fired, the lines at that time ± 5 min still exist. Frame intervals only ride along within 10 s either side of a
     rule hit, and only the first time for one version × rule × control (K12). At most 1 MB a day; over it only the lines with a hit go (K11).
   · 流畅度实测 (settings switch, localStorage ark-flutest = 1): every line carries its frame intervals, pieces of ~30 KB, no daily limit.

   A line: at (Date.now(), to match the time he says), pn (performance.now() at the press), v (the page's ?v=), ctl (the control's on-screen
   words, whitelisted control kinds only), kind, tab, shift, press (down → up ms), first (down → first frame with any change), react (first
   change after the up when the press itself changed nothing), near (down → first change in the control's own region: DOM / class / aria, an
   overlay appearing, a scroll), scene + scene_ms / scene_up (an overlay that appeared, ms after the down / the up), anim, vis (frames in which
   the control visibly moved), sw (a switch before → after), was_on (the tab / segment was already the selected one), refresh (pull to refresh
   fired), back (the page came back from the background: at, away ms), nf / exp / max / n50 / n100 / hitch (Apple's ms-per-s) / span, err, page
   (page self-check hits), chk_ms, bad (the rules broken).
   NEVER RECORDED: the screen, the text in any input (input.value is never read), localStorage, the URL's query, a fetch's path (only its host),
   push text, a device id.

   Not in an iframe, and never sending under ?accept (the self-check clicks the page). window.FluRec = {lines, stats, testing, test(on), flush()}. */
(function () {
  if (window.top !== window || window.FluRec || !window.ScanRules || !ScanRules.func) return;
  const F = ScanRules.func, D = ScanRules.display;
  const q = new URLSearchParams(location.search);
  const NO_SEND = q.has("accept");
  const RING_MS = 30 * 60e3, FI_CTX = 10e3, DAY_BYTES = 1e6, PIECE_AUTO = 40e3, PIECE_TEST = 30e3, SETTLE_MS = 400, HARD_MS = 10e3, DEAD_MS = 1000, CHK_MS = 4;
  const BUCKET = (() => { let v = ""; try { v = q.get("flubucket") || localStorage.getItem("ark-diag-bucket") || ""; } catch (e) {} return (v || "https://ark-diag-1315873325.cos.ap-shanghai.myqcloud.com").trim().replace(/\/+$/, ""); })();
  const raf = window.requestAnimationFrame.bind(window), fetch0 = window.fetch.bind(window);
  const ver = (() => { const s = [...document.scripts].map((x) => x.src || "").find((x) => /fluency-rec\.js/.test(x)); const m = s && /[?&]v=([^&#]+)/.exec(s); return m ? m[1] : "本地"; })();
  const sid = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, "0")).join("");
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} return null; };
  let test = store("ark-flutest") === "1";
  const lines = [], stats = { sent: 0, failed: 0, dropped: 0, capped: 0, chk: [] };
  let seq = 0, retry = [], sentUpTo = 0, back = null, hiddenAt = 0, chkNext = 0, dispOn = true, lastHits = new Set(), sinceSize = 0;
  const { txt } = F;

  /* the control's visible look as one string (its box, 12 descendants, their ::before / ::after — a switch's knob is span::after — and any canvas
     laid over it: the knob lens, switch.js 5cf6364); a frame whose string differs from the last one is a frame in which the control moved (vis) */
  const visSig = (root) => {
    const R = root.getBoundingClientRect(), r2 = (v) => Math.round(v * 2) / 2;
    const els = [root, ...Array.prototype.slice.call(root.querySelectorAll("*"), 0, 12)];
    for (const c of document.querySelectorAll("canvas")) { const b = c.getBoundingClientRect(); if (b.width && b.right > R.left && b.left < R.right && b.bottom > R.top && b.top < R.bottom && !root.contains(c)) els.push(c); }
    let s = "";
    const look = (cs) => `${cs.transform},${cs.translate},${cs.scale},${cs.left},${cs.width},${cs.opacity},${cs.backgroundColor},${cs.boxShadow}`;
    for (const e of els) { const b = e.getBoundingClientRect(); s += `${r2(b.x)},${r2(b.y)},${r2(b.width)},${r2(b.height)},${look(getComputedStyle(e))}`;
      if (e.childElementCount < 3) s += `/${look(getComputedStyle(e, "::before"))}/${look(getComputedStyle(e, "::after"))}`;
      s += "|"; }
    return s;
  };
  const finiteAnims = () => { try { return document.getAnimations().filter((a) => { const e = a.effect && a.effect.getComputedTiming && a.effect.getComputedTiming(); return a.playState === "running" && e && Number.isFinite(e.endTime); }); } catch (e) { return []; } };

  /* ---- errors: JS errors, rejections, console.error, fetches answered non-2xx or failed while online and visible (K4 「功能」) ---- */
  const errs = [];
  const clean = (s) => txt(String(s == null ? "" : s).replace(/https?:\/\/([^/\s?#]+)[^\s]*/g, "$1")).slice(0, 120);   // a URL keeps only its host
  const note = (m) => { errs.push({ pn: performance.now(), m: clean(m) }); if (errs.length > 200) errs.splice(0, 100); };
  addEventListener("error", (e) => { if (e.target && e.target !== window) return; note((e.message || "error") + " @" + String(e.filename || "").split("/").pop().split("?")[0] + ":" + (e.lineno || 0)); }, true);
  addEventListener("unhandledrejection", (e) => note("promise: " + ((e.reason && e.reason.message) || String(e.reason))));
  const cerr = console.error;
  console.error = function (...a) { try { note("console: " + a.map((x) => (x && x.message) || (typeof x === "string" ? x : typeof x)).join(" ")); } catch (e) {} return cerr.apply(this, a); };
  const host = (u) => { try { return new URL(u, location.href).host; } catch (e) { return "?"; } };
  window.fetch = function (input, init) {
    const p = fetch0(input, init), u = typeof input === "string" ? input : input && input.url;
    p.then((r) => { if (!r.ok && r.type !== "opaque") note("net " + host(u) + " " + r.status); },
      (e) => { if (navigator.onLine !== false && document.visibilityState === "visible" && !(e && e.name === "AbortError")) note("net " + host(u) + " 失败"); });
    return p;
  };

  /* ---- one gesture ---- */
  let g = null;
  const mo = new MutationObserver((recs) => {
    if (!g) return; g.dirty = true;
    for (const r of recs) {
      const t = r.target;
      if (t.id === "ptr" && r.attributeName === "data-state" && t.dataset.state === "3") g.refresh = true;   // refresh.js setState(3) = the pull fired
      if (!g.nearT && g.c.region && (g.c.region.contains(t) || (r.type === "childList" && t.contains(g.c.region)))) g.nearT = performance.now();
    }
  });
  const onAnimStart = (e) => { if (!g) return; g.dirty = true; g.anims++; if (g.c.root && g.c.root.contains(e.target)) g.ctlAnims++; if (!g.nearT && g.c.region && g.c.region.contains(e.target)) g.nearT = performance.now(); };
  const start = (e) => {
    if (g) finish(false);
    const c = F.control(e.target);
    g = { c, at: Date.now(), pn: performance.now(), up: 0, last: performance.now(), dirty: false, first: 0, firstAfterUp: 0, nearT: 0, anims: 0, ctlAnims: 0, ctlMs: 0, vis: 0,
      scene0: F.scene(), sceneMs: 0, sceneTo: "", fi: [], prev: 0, animFrames: 0, stallSeen: false, refresh: false,
      sw0: c.input ? !!c.input.checked : null, tab: F.curTab(), shift: F.curShift(), errs0: errs.length };
    mo.observe(document.documentElement, { attributes: true, childList: true, subtree: true, characterData: true });
    document.addEventListener("transitionrun", onAnimStart, true); document.addEventListener("animationstart", onAnimStart, true);
    raf(frame);
  };
  const frame = (ts) => {
    if (!g) return;
    const now = performance.now();
    if (g.prev) g.fi.push(Math.round((ts - g.prev) * 10) / 10);
    g.prev = ts;
    const running = finiteAnims();
    if (running.length) { g.dirty = true; g.animFrames++; for (const a of running) { const t = a.effect.target; if (g.c.root && t && g.c.root.contains(t)) g.ctlMs = Math.max(g.ctlMs, a.effect.getComputedTiming().endTime); } }
    if (g.c.root) { const v = visSig(g.c.root); if (g.sig !== undefined && v !== g.sig) g.vis++; g.sig = v; }
    if (g.dirty) {
      if (!g.first) g.first = ts - g.pn;
      if (g.up && !g.firstAfterUp) g.firstAfterUp = ts - g.pn;
      const s = g.sceneMs ? "" : F.scene();
      if (!g.sceneMs && s.split(" ").some((x) => x && !g.scene0.split(" ").includes(x))) {   // an overlay APPEARED (one closing is the gesture's own end, not a wait)
        g.sceneMs = ts - g.pn; g.sceneTo = s; g.stallSeen = !running.length && g.anims === 0; if (!g.nearT) g.nearT = now; }
      g.last = now; g.dirty = false;
    }
    const watchDead = !g.nearT && g.c.region && now - g.pn < DEAD_MS + 50;   // keep looking for the region's first change for the whole dead-tap second
    const quiet = !g.down && now - g.last > SETTLE_MS && !watchDead;
    if (quiet || now - g.pn > HARD_MS) finish(true); else raf(frame);
  };
  const finish = (settled) => {
    const G = g; g = null; mo.disconnect();
    document.removeEventListener("transitionrun", onAnimStart, true); document.removeEventListener("animationstart", onAnimStart, true);
    if (!G || document.visibilityState !== "visible" && G.fi.length < 2) return;
    const fi = G.fi.slice(1);                                            // the first interval straddles the press itself
    const exp = (() => { const s = fi.filter((x) => x > 4).sort((a, b) => a - b); return s.length ? Math.min(s[Math.floor(s.length / 2)], 17.5) : 16.7; })();
    const spanMs = Math.max(G.last - G.pn, 100);
    let hitch = 0, acc = 0;
    for (const x of fi) { acc += x; if (acc > spanMs + exp) break; if (x > exp * 1.5) hitch += x - exp; }
    const L = { at: G.at, pn: Math.round(G.pn), v: ver, ctl: G.c.ctl, kind: G.c.kind, tab: G.tab, shift: G.shift,
      press: G.up ? Math.round(G.up - G.pn) : null, first: G.first ? Math.round(G.first) : null,
      react: G.first ? Math.round(G.up && G.first > G.up - G.pn ? G.first - (G.up - G.pn) : G.first) : null,
      near: G.nearT ? Math.round(G.nearT - G.pn) : null, was_on: !!G.c.on, disabled: !!G.c.off,
      scene: G.sceneMs ? [G.scene0, G.sceneTo] : null, scene_ms: G.sceneMs ? Math.round(G.sceneMs) : null,
      scene_up: G.sceneMs && G.up && G.sceneMs > G.up - G.pn ? Math.round(G.sceneMs - (G.up - G.pn)) : null, stall: G.stallSeen,
      anim: { n: G.anims, ctl: G.ctlAnims, ctl_ms: Math.round(G.ctlMs), frames: G.animFrames }, vis: G.vis,
      sw: G.sw0 === null ? null : [G.sw0, !!(G.c.input && G.c.input.checked)], refresh: G.refresh, back: back && G.at - back.at <= 10e3 ? back : null,
      nf: fi.length, exp: Math.round(exp * 10) / 10, max: fi.length ? Math.round(Math.max(...fi)) : null,
      n50: fi.filter((x) => x > 50).length, n100: fi.filter((x) => x > 100).length,
      hitch: Math.round(hitch / spanMs * 1000 * 10) / 10, span: Math.round(spanMs), settled, bad: [] };
    const e = errs.slice(G.errs0); if (e.length) L.err = e.map((x) => x.m).slice(0, 5);
    if (G.c.kind === "tab" || G.c.kind === "seg") L.tabs = F.tabs();
    L.bad = F.judge(L, lines);
    if (settled) selfCheck(L);
    L.fi = fi.slice(0, 600);
    record(L);
  };
  /* the page self-check (K10): ≤ 1 per s, timed; only hits that were not there at the last run */
  const selfCheck = (L) => {
    const now = performance.now(); if (now < chkNext) return; chkNext = now + 1000;
    const f = F.check(); let ms = f.ms, hits = f.hits;
    if (dispOn && D && D.run) { try { const d = D.run({ rules: D.bugRules, view: true });   /* the six rules that can say "bug", on what reaches into the screen only (外观 ui2 01b8f20: same in-view bugs, 40–51 % of the time) */ ms += d.ms; hits = hits.concat(d.out.filter((x) => x.level === "bug").map((x) => ({ rule: x.rule, ctl: txt(x.where), note: txt(x.detail) }))); } catch (err) { hits.push({ rule: "display", ctl: "", note: clean(err.message) }); } }
    if (ms > CHK_MS && dispOn) dispOn = false;                    // over 4 ms on this phone: the display rules stop here, the function ones stay
    L.chk_ms = Math.round(ms * 10) / 10; stats.chk.push(L.chk_ms); if (stats.chk.length > 50) stats.chk.shift();
    const keys = new Set(hits.map((h) => h.rule + "|" + h.ctl)), fresh = hits.filter((h) => !lastHits.has(h.rule + "|" + h.ctl));
    lastHits = keys;
    if (fresh.length) { L.page = fresh.slice(0, 8); for (const h of fresh) if (!L.bad.includes(h.rule)) L.bad.push(h.rule); }
  };
  const record = (L) => {
    if (L.bad.length) {                                           // frames ride along only the first time for version × rule × control (K12)
      let seen = []; try { seen = JSON.parse(store("ark-flu-fi") || "[]"); } catch (e) {}
      const ks = L.bad.map((r) => ver + "|" + r + "|" + L.ctl), fresh = ks.filter((k) => !seen.includes(k));
      if (fresh.length) { L.fik = true; store("ark-flu-fi", JSON.stringify(seen.concat(fresh).slice(-300))); }
    }
    lines.push(L);
    const cut = performance.now() - RING_MS; while (lines.length && lines[0].pn < cut && lines[0].pn < sentUpTo) lines.shift();   // an unsent line stays
    try { window.dispatchEvent(new CustomEvent("flurec", { detail: L })); } catch (err) {}
    if (++sinceSize >= 10 || test) { sinceSize = 0; if (JSON.stringify(outLines(unsent())).length > (test ? PIECE_TEST : PIECE_AUTO)) send(false); }
  };
  addEventListener("pointerdown", (e) => { if (!e.isPrimary) return; start(e); if (g) g.down = true; }, true);
  const lift = () => { if (g && g.down) { g.down = false; g.up = performance.now(); g.last = g.up; } };
  addEventListener("pointerup", lift, true); addEventListener("pointercancel", lift, true);
  addEventListener("scroll", () => { if (g) { g.dirty = true; if (!g.nearT) g.nearT = performance.now(); } }, { capture: true, passive: true });

  /* a reload right after a tap (10 s) or right after coming back (30 s away) is 「重开」 too (K10) */
  try {
    const nav = performance.getEntriesByType("navigation")[0], s = JSON.parse(sessionStorage.getItem("ark-flu-leave") || "null"), now = Date.now();
    if (nav && nav.type === "reload" && s && (now - s.tap <= 10e3 || (s.hid && now - s.hid <= 30e3)))
      lines.push({ at: now, pn: 0, v: ver, ctl: s.ctl || "", kind: "reload", tab: "", shift: "", refresh: true, bad: ["reopen"], fik: false, fi: [] });
  } catch (e) {}
  const leave = () => { try { const l = lines.filter((x) => x.kind !== "reload").pop(); sessionStorage.setItem("ark-flu-leave", JSON.stringify({ tap: l ? l.at : 0, ctl: l ? l.ctl : "", hid: hiddenAt })); } catch (e) {} };

  /* ---- leaving the phone ---- */
  const unsent = () => lines.filter((l) => l.pn >= sentUpTo);
  const outLines = (ls) => {                                      // frames only within 10 s of a first-time hit, or everything in 实测
    const keys = test ? null : lines.filter((l) => l.fik).map((l) => l.pn);
    return ls.map((l) => { const { fi, fik, ...r } = l; if (test || keys.some((p) => Math.abs(p - l.pn) <= FI_CTX)) r.fi = fi; return r; });
  };
  const tokyo = (ms) => new Date(ms + 9 * 3600e3).toISOString().replace(/[-:T]/g, "").slice(0, 14);   // YYYYMMDDHHMMSS in Tokyo
  const dayBytes = (add) => { const d = tokyo(Date.now()).slice(0, 8); const [dd, nn] = (store("ark-flu-day") || "").split(":"); const n = dd === d ? +nn || 0 : 0; if (add) store("ark-flu-day", d + ":" + (n + add)); return n; };
  const a11y = () => { const mm = (s) => { try { return matchMedia(s).matches; } catch (e) { return null; } }; return { reduce_motion: mm("(prefers-reduced-motion: reduce)"), reduce_transparency: mm("(prefers-reduced-transparency: reduce)") }; };
  const put = async (body, keepalive) => {
    const key = `diag/flu/${tokyo(Date.now())}-${sid}-${++seq}-${test ? "test" : "auto"}.json`;
    const r = await fetch0(`${BUCKET}/${key}`, { method: "PUT", keepalive, headers: { "Content-Type": "application/json", "x-cos-forbid-overwrite": "true" }, body });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return key;
  };
  const payload = (ls, why) => JSON.stringify({ kind: "flu", mode: test ? "test" : "auto", why, v: ver, sid, sent: Date.now(), dpr: devicePixelRatio,
    standalone: !!(navigator.standalone || matchMedia("(display-mode: standalone)").matches), a11y: a11y(), dispOn, lines: ls });
  const ship = async (ls, why, keepalive, isRetry) => {
    if (!ls.length) return;
    let body = payload(ls, why);
    if (keepalive && body.length > 60e3) { ls = ls.map((l) => { if (l.bad && l.bad.length) return l; const { fi, ...r } = l; return r; }); body = payload(ls, why); }   // the keepalive quota (64 KB): frames go first,
    while (keepalive && body.length > 60e3 && ls.length > 1) { ls = ls.slice(Math.ceil(ls.length / 4)); body = payload(ls, why); }                                // then the oldest lines
    if (!test && !isRetry) {                                      // 1 MB a day; over it only the lines with a hit
      if (dayBytes(0) + body.length > DAY_BYTES) { ls = ls.filter((l) => l.bad && l.bad.length); body = payload(ls, why); if (!ls.length || dayBytes(0) + body.length > DAY_BYTES) { stats.capped++; return; } }
      dayBytes(body.length);
    }
    try { await put(body, keepalive); stats.sent++; stats.last = why; }
    catch (e) { stats.failed++; if (isRetry) stats.dropped++; else retry.push([ls, why]); }
  };
  const send = (hidden) => {
    if (NO_SEND) return;
    const ls = unsent(); if (!ls.length) return;
    sentUpTo = ls[ls.length - 1].pn + 1;
    ship(outLines(ls), hidden ? "background" : "piece", hidden);
  };
  const flushHidden = () => { if (g) finish(false); hiddenAt = Date.now(); leave(); send(true); };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushHidden();
    else { if (hiddenAt) back = { at: Date.now(), away: Date.now() - hiddenAt };
      if (retry.length) { const r = retry; retry = []; for (const [ls, why] of r) ship(ls, why + "+retry", false, true); } }
  });
  addEventListener("pagehide", flushHidden);

  window.FluRec = { lines, stats, get testing() { return test; },
    test(on) { on = !!on; if (on === test) return; send(false); test = on; store("ark-flutest", on ? "1" : null); },
    flush() { send(false); } };
})();
