/* menu.js — the value row's pull-down menu: a geometry morph from the button's frame to the panel, in place of the old scale-and-fade
   (BOARD.md #3, night batch: geometry and timing only, no material).
   Basis (read values): menu-motion-formula.md §0 table / §2 — appear = one spring each for position x / y, width, height, ζ .8 / response .3 s
   (the liquidMorph spec, ω = 2π/.3); dismiss = the same four with ζ .9 / .3 (liquidMorphShrink); reduce-motion = ζ 1 / .15 cross-fade
   (liquidMorphReduceMotion); no dimming (_hasVisibleBackground NO, the scrim stays transparent); the source is the trigger button's own frame
   (morphPreviewFromAttachmentPoint, anchor (.5, .5)) — here the .menubtn's rect; the corner follows the same spring from the button's corner to
   the menu's (§4.1). menu-card-material.md §1.2 — width 250 (defaultMenuWidth), corner 32 (menuCornerRadius), section insets 10 / 10, item 42
   (the item rules stay index.html's `.menu button`). The panel's placement (below the value, 6 pt gap, ≥ 8 pt from the edges, above when
   there is no room) is the page's existing rule (view.js openMenu), kept.
   Unread, left out (menu-motion-formula.md §6): the intermediate shape (growing .25 / shrinking .9) and the .03 s second-step delay that belongs
   to it — the four springs run straight to the target from the frame of the call; the content's cross-blur / contentScale on the menu path —
   the items sit in the panel from the first frame, clipped by it.
   Springs come from web/motion.js only (BOARD A7, #1). Without Motion this file defines nothing and view.js's old openMenu stays in charge
   (its first line is `if (window.Menu) return Menu.open(anchor, sel);`). */
(function () {
  if (!window.Motion || typeof Motion.spring !== "function") return;
  const APPEAR = [0.8, 0.3], DISMISS = [0.9, 0.3], REDUCE = [1, 0.15];   // [ζ, response s]
  const W = 250, R = 32, GAP = 6, EDGE = 8;
  let cur = null;   // the open menu: { panel, scrim, sel, from, to, s: { left, top, width, height, r, a }, phase: "in" | "out", prev, raf }
  const reduce = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const restRect = (anchor, h) => { const r = anchor.getBoundingClientRect(); const right = Math.max(EDGE, innerWidth - r.right), left = innerWidth - right - W;
    const top = r.bottom + GAP + h <= innerHeight - EDGE ? r.bottom + GAP : Math.max(EDGE, r.top - GAP - h); return { left, top, width: W, height: h }; };
  const anchorRect = (anchor) => { const r = anchor.getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width, height: r.height }; };
  const cornerOf = (el) => parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0;
  const apply = () => { const p = cur.panel.style, s = cur.s; p.left = s.left.x + "px"; p.top = s.top.x + "px"; p.width = s.width.x + "px"; p.height = s.height.x + "px"; p.borderRadius = s.r.x + "px"; p.opacity = String(Math.max(0, Math.min(1, s.a.x))); };
  const settled = (goal) => Object.keys(goal).every((k) => Math.abs(cur.s[k].x - goal[k]) < 0.05 && Math.abs(cur.s[k].v) < 1);
  const strip = () => { if (!cur) return; cancelAnimationFrame(cur.raf); cur.panel.remove(); cur.scrim.remove(); removeEventListener("keydown", onKey); cur = null; };
  const tick = (now) => { if (!cur) return;
    const dt = Math.min(0.04, Math.max(0, (now - cur.prev) / 1000)); cur.prev = now;
    const goal = cur.phase === "in" ? cur.goalIn : cur.goalOut, spec = cur.phase === "in" ? (cur.reduced ? REDUCE : APPEAR) : (cur.reduced ? REDUCE : DISMISS);
    for (const k of Object.keys(goal)) Motion.spring(cur.s[k], goal[k], spec, dt);
    apply();
    if (settled(goal)) { if (cur.phase === "out") { strip(); return; } cur.raf = 0; return; }   // "in" settled: the panel rests, the loop stops
    cur.raf = requestAnimationFrame(tick); };
  const run = () => { if (cur.raf) cancelAnimationFrame(cur.raf); cur.prev = performance.now(); cur.raf = requestAnimationFrame(tick); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function open(anchor, sel) {
    strip();
    const scrim = document.createElement("div"); scrim.className = "menu-scrim";
    const panel = document.createElement("div"); panel.className = "menu morph"; panel.setAttribute("role", "menu");
    const body = document.createElement("div"); body.className = "menu-body"; panel.appendChild(body);
    for (const o of sel.options) {
      const b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "menuitemradio"); if (o.selected) b.classList.add("on");
      const ck = document.createElement("i"); ck.className = "ck"; const sym = typeof SYM !== "undefined" && SYM["checkmark"];   // view.js's SYM is a top-level const (not on window)
      if (sym) ck.setAttribute("style", `-webkit-mask-image:url(${sym});mask-image:url(${sym})`);
      b.appendChild(ck); b.appendChild(document.createTextNode(o.textContent));
      b.onclick = () => { if (sel.value !== o.value) { sel.value = o.value; sel.dispatchEvent(new Event("change", { bubbles: true })); } close(); };
      body.appendChild(b);
    }
    scrim.onclick = close;
    document.body.append(scrim, panel);
    const h = body.offsetHeight;   // items × 42 + the 10 / 10 insets
    const from = anchorRect(anchor), to = restRect(anchor, h), reduced = reduce();
    const start = reduced ? { ...to } : from;
    const s = { left: { x: start.left, v: 0 }, top: { x: start.top, v: 0 }, width: { x: start.width, v: 0 }, height: { x: start.height, v: 0 }, r: { x: reduced ? R : cornerOf(anchor), v: 0 }, a: { x: reduced ? 0 : 1, v: 0 } };
    cur = { panel, scrim, sel, anchor, from, to, s, reduced, phase: "in", goalIn: { left: to.left, top: to.top, width: to.width, height: to.height, r: R, a: 1 }, goalOut: null, prev: 0, raf: 0, t0: 0 };
    apply(); addEventListener("keydown", onKey); run(); cur.t0 = cur.prev;   // t0 = the spring's start (the call's performance.now()): the closed form x(t) holds at t = frame timestamp − t0
  }
  function close() {
    if (!cur) return;
    if (cur.phase === "out") return;
    const back = anchorRect(cur.anchor);   // the button's frame now (the page may have scrolled)
    cur.phase = "out"; cur.from = { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x }; cur.to = back;
    cur.goalOut = cur.reduced ? { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x, r: R, a: 0 } : { left: back.left, top: back.top, width: back.width, height: back.height, r: cornerOf(cur.anchor), a: 1 };
    cur.scrim.style.pointerEvents = "none"; run(); cur.t0 = cur.prev;
  }
  /* hidden strips the state at once (BOARD A6 template): nothing animates while the page is away and a half-open menu must not come back */
  const onHidden = (force) => { if (force || document.hidden) strip(); };
  document.addEventListener("visibilitychange", () => onHidden(false));
  window.Menu = { open, close, onHidden, state: () => cur ? { phase: cur.phase, from: { ...cur.from }, to: { ...cur.to }, reduced: cur.reduced, t0: cur.t0 } : null };
})();
