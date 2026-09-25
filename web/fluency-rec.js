/* fluency-rec.js — the phone's own fluency recorder (D78 item 5, BOARD/会议-录屏逐帧与三样方案-0926-结论.md §5 + its DeepSeek review items 1–2;
   the user 09-26 04:21: 「手机流畅度测试能不能做成在我手机上实测？我开个开关实时记录流畅度，然后结果交给你们看？」).

   Two modes, one recorder:
   · ALWAYS ON, LIGHT: every gesture (pointerdown … the page at rest again) becomes one line in an in-memory ring of the last 30 minutes. A line
     with an anomaly (below) is sent with the lines 30 s before and after it — 30 s after it while the page is visible, or at once when the page
     goes to the background (visibilitychange → hidden, pagehide as a fallback; fetch keepalive, its body is capped at 64 KB by the Fetch spec, so a
     segment is never the whole ring). At most 20 segments a day (the user 09-24 19:4x: 「传了一堆垃圾上去」). A send that fails is tried once more on
     the next visible and then dropped — nothing is written to disk.
   · 流畅度实测 (settings switch, localStorage ark-flutest = 1): every gesture also carries its frame intervals; everything is sent — in pieces of
     ~30 KB while visible, the rest when the switch goes off or the page goes to the background. No daily limit.

   A line: at (Date.now(), to match the time he says), pn (performance.now() at the press, for intervals), v (the page's ?v=), ctl (the control's
   on-screen words, from a whitelist of control kinds only: tab / segment / switch / row label / button), kind, tab (current tab), shift (current
   segment), press (down → up ms), first (down → first frame with any change: DOM mutation or animation start), react (first change after the up
   when the page did not change during the press), scene (overlays that appeared / went: sheet, dialog, menu, subpage, toast) + scene_ms, anim
   (animations that ran: all / on the control, the longest on the control in ms), sw (a switch's checked before → after), frames: nf, max (the
   longest frame, ms), n50 / n100 (frames over 50 / 100 ms), hitch (ms of hitch per s over the active span — Apple, Understanding hitches in your
   app: a frame that stays on screen past its expected presentation is late by that much; the metric is ms of pause per s: ≤ 10 good, ≤ 25
   warning, ≤ 50 critical, > 50 immediate attention), span (ms from the press to the last frame with a change), err (JS errors in the window).
   NEVER RECORDED: the screen, screenshots, the text in any input (input.value is never read), localStorage, the URL's query, push text, a
   device id.

   Anomalies (bad[]): err (a JS error) · long (a frame > 100 ms) · slow (the page's first change > 200 ms after the press, or after the up when the
   press changed nothing — web.dev INP 「good」 line) · noanim (a switch changed state and no animation ran on it: 「开关的动画整个被吞了」, R5 / R8) ·
   late (an overlay reached the screen > 100 ms after the up — native sheets
   come at up + 54…65 ms, + 90 the cold first time, remote-ref/cell-native-shorttap.md; R6 「多选选择的那个弹窗动画也有延迟」) · stall (an overlay appeared while no animation ran — it popped in: R10's class) · tabfix (a tab in the tab bar whose page, in this shift, holds
   only an entry row: R1 「切换到晚班的时候不应该显示终末地」, fixed c8ae591). Pure picture faults (a white flash, a double image — R2 / R4) are not
   visible to this recorder; those stay with frame-by-frame video (conclusion §2).

   Not in an iframe, and never sending under ?accept (the self-check clicks the page; its lines stay in memory). window.FluRec = {lines, test(on),
   flush(), stats} for the settings switch and for the simulator proof. */
(function () {
  if (window.top !== window || window.FluRec) return;
  const q = new URLSearchParams(location.search);
  const NO_SEND = q.has("accept");
  const RING_MS = 30 * 60e3, CTX_MS = 30e3, DAY_MAX = 20, PIECE = 30e3, SETTLE_MS = 400, HARD_MS = 10e3;
  const BUCKET = (() => { let v = ""; try { v = q.get("flubucket") || localStorage.getItem("ark-diag-bucket") || ""; } catch (e) {} return (v || "https://ark-diag-1315873325.cos.ap-shanghai.myqcloud.com").trim().replace(/\/+$/, ""); })();
  const raf = window.requestAnimationFrame.bind(window);
  const ver = (() => { const s = [...document.scripts].map((x) => x.src || "").find((x) => /fluency-rec\.js/.test(x)); const m = s && /[?&]v=([^&#]+)/.exec(s); return m ? m[1] : "本地"; })();
  const sid = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, "0")).join("");
  let test = false; try { test = localStorage.getItem("ark-flutest") === "1"; } catch (e) {}
  const lines = [], stats = { sent: 0, failed: 0, dropped: 0, capped: 0 };
  let seq = 0, pendingAt = 0, timer = 0, retry = [], sentUpTo = 0;   // sentUpTo: in test mode, lines[i].pn below it have left the phone

  /* ---- what the finger touched ---- */
  const txt = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, 24);
  const rowLabel = (el) => { const r = el.closest(".row"); const l = r && r.querySelector("label"); return l ? txt(l.firstChild && l.firstChild.nodeType === 3 ? l.firstChild.textContent : l.textContent) : ""; };
  const control = (t) => {
    if (!t || !t.closest) return { ctl: "", kind: "other", root: null };
    let el;
    if ((el = t.closest("nav.tabs button"))) return { ctl: txt(el.dataset.tab || el.textContent), kind: "tab", root: t.closest("nav.tabs") };
    if ((el = t.closest(".segctl button"))) return { ctl: txt(el.dataset.q || el.textContent), kind: "seg", root: el.closest(".segctl") };
    if ((el = t.closest(".sw, [role=switch]"))) return { ctl: (rowLabel(el) || txt(el.getAttribute("aria-label"))) + "·开关", kind: "switch", root: el, input: el.querySelector("input[type=checkbox]") || (el.matches("input") ? el : null) };
    if ((el = t.closest("input, textarea, select"))) return { ctl: rowLabel(el) + "·输入框", kind: "input", root: el };   // never el.value
    if ((el = t.closest("button, a, summary, [role=button], [role=tab], [role=menuitem]"))) return { ctl: txt(el.getAttribute("aria-label") || el.textContent), kind: el.closest("[role=menu], .menu") ? "menu" : "button", root: el };
    if ((el = t.closest(".row"))) return { ctl: rowLabel(el), kind: "row", root: el };
    return { ctl: "", kind: "other", root: null };
  };
  const curTab = () => { const b = document.querySelector("nav.tabs button.on"); return b ? txt(b.dataset.tab || b.textContent) : ""; };
  const curShift = () => { const b = document.querySelector("#app > .segctl:not([hidden]) button.on"); return b ? txt(b.dataset.q || b.textContent) : ""; };
  const OVERLAYS = "dialog[open], .sheet, .menu, #subpage, #toast, [role=dialog], [role=menu]";
  const scene = () => { const out = []; for (const e of document.querySelectorAll(OVERLAYS)) { if (e.hidden || !e.getClientRects().length) continue; const cs = getComputedStyle(e); if (cs.visibility === "hidden" || cs.display === "none" || +cs.opacity === 0) continue; out.push(e.id ? "#" + e.id : e.tagName.toLowerCase() + (e.classList[0] ? "." + e.classList[0] : "")); } return out.sort().join(" "); };
  const tabs = () => [...document.querySelectorAll("nav.tabs button")].map((b) => txt(b.dataset.tab || b.textContent));
  /* R1: a tab whose page, now, holds nothing but data-tabfix entry rows (view.js 787–792 builds the tab set from the sections) */
  const entryOnlyTabs = () => { const out = []; for (const t of tabs()) { const secs = [...document.querySelectorAll("#app > section")].filter((s) => s.dataset.tab === t && s.dataset.empty !== "1"); if (secs.length && secs.every((s) => s.dataset.tabfix)) out.push(t); } return out; };
  const finiteAnims = () => { try { return document.getAnimations().filter((a) => { const e = a.effect && a.effect.getComputedTiming && a.effect.getComputedTiming(); return a.playState === "running" && e && Number.isFinite(e.endTime); }); } catch (e) { return []; } };

  /* what the control shows, as one string: its box and up to 12 of its elements' boxes / transform / opacity / fill, plus any canvas laid over it
     (the switch's knob lens is a page-level canvas moved over the pressed switch, switch.js 5cf6364). A frame whose string differs from the last is a
     frame in which the control visibly moved — `vis` counts them (the exam's 「frames between off-rest and on-rest in the switch box」, cases.md R5) */
  const visSig = (root) => {
    const R = root.getBoundingClientRect(), r2 = (v) => Math.round(v * 2) / 2;
    const els = [root, ...Array.prototype.slice.call(root.querySelectorAll("*"), 0, 12)];
    for (const c of document.querySelectorAll("canvas")) { const b = c.getBoundingClientRect(); if (b.width && b.right > R.left && b.left < R.right && b.bottom > R.top && b.top < R.bottom && !root.contains(c)) els.push(c); }
    let s = "";
    const look = (cs) => `${cs.transform},${cs.translate},${cs.scale},${cs.left},${cs.width},${cs.opacity},${cs.backgroundColor},${cs.boxShadow}`;
    for (const e of els) { const b = e.getBoundingClientRect(); s += `${r2(b.x)},${r2(b.y)},${r2(b.width)},${r2(b.height)},${look(getComputedStyle(e))}`;
      if (e.childElementCount < 3) s += `/${look(getComputedStyle(e, "::before"))}/${look(getComputedStyle(e, "::after"))}`;   // a switch's knob can be a pseudo-element
      s += "|"; }
    return s;
  };

  /* ---- errors ---- */
  let errs = [];
  addEventListener("error", (e) => { errs.push({ pn: performance.now(), m: txt((e.message || "error") + " @" + String(e.filename || "").split("/").pop().split("?")[0] + ":" + (e.lineno || 0)).slice(0, 120) }); }, true);
  addEventListener("unhandledrejection", (e) => { errs.push({ pn: performance.now(), m: txt("promise: " + ((e.reason && e.reason.message) || String(e.reason))).slice(0, 120) }); });

  /* ---- one gesture ---- */
  let g = null;
  const mo = new MutationObserver(() => { if (g) g.dirty = true; });
  const onAnimStart = (e) => { if (!g) return; g.dirty = true; g.anims++; if (g.c.root && g.c.root.contains(e.target)) g.ctlAnims++; };
  const start = (e) => {
    if (g) finish(false);
    const c = control(e.target);
    g = { c, at: Date.now(), pn: performance.now(), up: 0, last: performance.now(), dirty: false, first: 0, firstAfterUp: 0, anims: 0, ctlAnims: 0, ctlMs: 0, vis: 0,
      scene0: scene(), sceneMs: 0, sceneTo: "", fi: [], prev: 0, maxAnim: 0, animFrames: 0, stallSeen: false,
      sw0: c.input ? !!c.input.checked : null, tab: curTab(), shift: curShift(), errs0: errs.length };
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
      const s = g.sceneMs ? "" : scene();
      if (!g.sceneMs && s.split(" ").some((x) => x && !g.scene0.split(" ").includes(x))) {   // an overlay APPEARED (one closing is the gesture's own end, not a wait)
        g.sceneMs = ts - g.pn; g.sceneTo = s; g.stallSeen = !running.length && g.anims === 0; }
      g.last = now; g.dirty = false;
    }
    const quiet = !g.down && now - g.last > SETTLE_MS;
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
      scene: G.sceneMs ? [G.scene0, G.sceneTo] : null, scene_ms: G.sceneMs ? Math.round(G.sceneMs) : null,
      scene_up: G.sceneMs && G.up && G.sceneMs > G.up - G.pn ? Math.round(G.sceneMs - (G.up - G.pn)) : null,
      anim: { n: G.anims, ctl: G.ctlAnims, ctl_ms: Math.round(G.ctlMs), frames: G.animFrames }, vis: G.vis,
      sw: G.sw0 === null ? null : [G.sw0, !!(G.c.input && G.c.input.checked)],
      nf: fi.length, exp: Math.round(exp * 10) / 10, max: fi.length ? Math.round(Math.max(...fi)) : null,
      n50: fi.filter((x) => x > 50).length, n100: fi.filter((x) => x > 100).length,
      hitch: Math.round(hitch / spanMs * 1000 * 10) / 10, span: Math.round(spanMs), settled, bad: [] };
    const e = errs.slice(G.errs0); if (e.length) L.err = e.map((x) => x.m).slice(0, 5);
    if (G.c.kind === "tab" || G.c.kind === "seg") { L.tabs = tabs(); const eo = entryOnlyTabs(); if (eo.length) L.entry_only = eo; }
    if (L.err) L.bad.push("err");
    if (L.n100) L.bad.push("long");
    if (L.react !== null && L.react > 200 && G.c.kind !== "input") L.bad.push("slow");
    if (L.scene_up !== null && L.scene_up > 100) L.bad.push("late");   // an overlay on screen > 100 ms after the up: native sheets land at up + 54…65 ms, the cold first one + 90 (remote-ref/cell-native-shorttap.md); R6 on 42ff6d0 measured up + 187 / 236
    if (L.sw && L.sw[0] !== L.sw[1] && !G.ctlAnims && !G.ctlMs) L.bad.push("noanim");
    if (G.stallSeen) L.bad.push("stall");
    if (L.entry_only) L.bad.push("tabfix");
    if (test) L.fi = fi;
    lines.push(L);
    const cut = performance.now() - RING_MS; while (lines.length && lines[0].pn < cut && (!test || lines[0].pn < sentUpTo)) lines.shift();   // 30 min; in 实测 an unsent line stays
    try { window.dispatchEvent(new CustomEvent("flurec", { detail: L })); } catch (err) {}
    if (L.bad.length && !test) { if (!pendingAt) pendingAt = L.pn; clearTimeout(timer); timer = setTimeout(() => send(false), CTX_MS); }
    if (test && JSON.stringify(unsent()).length > PIECE) send(false);
  };
  addEventListener("pointerdown", (e) => { if (!e.isPrimary) return; start(e); if (g) g.down = true; }, true);
  const lift = () => { if (g && g.down) { g.down = false; g.up = performance.now(); g.last = g.up; } };
  addEventListener("pointerup", lift, true); addEventListener("pointercancel", lift, true);
  addEventListener("scroll", () => { if (g) g.dirty = true; }, { capture: true, passive: true });

  /* ---- leaving the phone ---- */
  const unsent = () => lines.filter((l) => l.pn >= sentUpTo);
  const tokyo = (ms) => new Date(ms + 9 * 3600e3).toISOString().replace(/[-:T]/g, "").slice(0, 14);   // YYYYMMDDHHMMSS in Tokyo
  const dayCount = (inc) => { const d = tokyo(Date.now()).slice(0, 8); let n = 0; try { const [dd, nn] = (localStorage.getItem("ark-flu-day") || "").split(":"); n = dd === d ? +nn || 0 : 0; if (inc) localStorage.setItem("ark-flu-day", d + ":" + (n + 1)); } catch (e) {} return n; };
  const a11y = () => { const mm = (s) => { try { return matchMedia(s).matches; } catch (e) { return null; } }; return { reduce_motion: mm("(prefers-reduced-motion: reduce)"), reduce_transparency: mm("(prefers-reduced-transparency: reduce)") }; };
  const put = async (body, keepalive) => {
    const key = `diag/flu/${tokyo(Date.now())}-${sid}-${++seq}-${test ? "test" : "auto"}.json`;
    const r = await fetch(`${BUCKET}/${key}`, { method: "PUT", keepalive, headers: { "Content-Type": "application/json", "x-cos-forbid-overwrite": "true" }, body });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return key;
  };
  const payload = (ls, why) => JSON.stringify({ kind: "flu", mode: test ? "test" : "auto", why, v: ver, sid, sent: Date.now(), dpr: devicePixelRatio, standalone: !!(navigator.standalone || matchMedia("(display-mode: standalone)").matches), a11y: a11y(), lines: ls });
  const ship = async (ls, why, keepalive, isRetry) => {
    if (!ls.length) return;
    let body = payload(ls, why);
    while (keepalive && body.length > 60e3 && ls.length > 1) { ls = ls.slice(Math.ceil(ls.length / 4)); body = payload(ls, why); }   // the keepalive quota (64 KB): keep the latest
    try { await put(body, keepalive); stats.sent++; stats.last = why; }
    catch (e) { stats.failed++; if (isRetry) stats.dropped++; else retry.push([ls, why]); }
  };
  const send = (hidden) => {
    clearTimeout(timer); timer = 0;
    if (NO_SEND) { pendingAt = 0; return; }
    if (test) { const ls = unsent(); if (!ls.length) return; sentUpTo = ls[ls.length - 1].pn + 1; ship(ls, hidden ? "background" : "piece", hidden); return; }
    if (!pendingAt) return;
    /* each anomaly with 30 s either side; overlapping windows merge into one segment */
    const bad = lines.filter((l) => l.bad.length && l.pn >= pendingAt);
    pendingAt = 0;
    const segs = [];
    for (const b of bad) { const s = segs[segs.length - 1]; if (s && b.pn - CTX_MS <= s[1]) s[1] = b.pn + CTX_MS; else segs.push([b.pn - CTX_MS, b.pn + CTX_MS]); }
    for (const [a, z] of segs) {
      if (dayCount(false) >= DAY_MAX) { stats.capped++; continue; }
      dayCount(true);
      ship(lines.filter((l) => l.pn >= a && l.pn <= z), "anomaly", hidden);
    }
  };
  const flushHidden = () => { if (g) finish(false); send(true); };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushHidden();
    else if (retry.length) { const r = retry; retry = []; for (const [ls, why] of r) ship(ls, why + "+retry", false, true); }
  });
  addEventListener("pagehide", flushHidden);

  window.FluRec = { lines, stats, get testing() { return test; },
    test(on) { on = !!on; if (on === test) return; if (!on) send(false); test = on; try { if (on) localStorage.setItem("ark-flutest", "1"); else localStorage.removeItem("ark-flutest"); } catch (e) {} if (on) sentUpTo = performance.now(); },
    flush() { send(false); } };
})();
