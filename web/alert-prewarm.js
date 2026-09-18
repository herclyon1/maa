/* alert-prewarm.js — build the alert's glass layer once at page load so the first alert opens as fast as the second.

   The first time a page uses `backdrop-filter` the engine builds the backdrop layer and its filter pipeline (shader / kernel
   setup); on the simulator that made the first alert's first frame ≈ 776 ms vs 28 ms on the second open (3 ms without the
   blur). This script inserts, at load, a copy of the alert's `.pane` — the same box (320×172 at the alert's position, oversized
   by 60 pt and clipped back to r 34), the same `backdrop-filter` chain and fill (`--ios-alert-glass-filter`, `--alert-fill`) —
   in a fixed host that is invisible (opacity 0 by default), inert and outside layout, keeps it for two painted frames plus a
   grace period, then removes it, so nothing stays composited while the page scrolls. The real alert keeps its exact glass from
   its first frame; nothing is shown without blur first.

   Query flags (measurement, `?diag=1` line and localStorage["ark-alertwarm"]):
     ?prewarm=0     no prewarm (the "before" number)     ?prewarm=eps  the host at opacity .01 instead of 0 (engines that skip
     ?prewarm=keep  never remove the host                                painting fully transparent layers do not warm up)
     ?prewarm=dialog  show the real dialog invisibly for two frames at load instead of a copy
     ?alertwarm=1   auto-measure (a number > 1 = ms to wait after load, default 1500): open the alert (view.js ask()), read the first two frame stamps after
                    showModal, cancel, wait 1.2 s, open again, store {first, second} (ms from showModal to the first frame). */
(function () {
  const q = new URLSearchParams(location.search), mode = q.get("prewarm") ?? "1";
  const KEY = "ark-alertwarm";
  /* mode "dialog": show the real dialog itself, invisible (opacity 0, no appear animation, backdrop transparent), for two painted
     frames — warms the whole first-open path (backdrop, glass layer, fonts, animation compositing) with the exact same structure */
  function prewarm_dialog() {
    const dlg = document.getElementById("alert"); if (!dlg || dlg.open) return null;
    const st = document.createElement("style"); st.id = "alert-prewarm-style";
    st.textContent = "dialog#alert.prewarming{opacity:0 !important;animation:none !important;pointer-events:none} dialog#alert.prewarming::backdrop{opacity:0 !important}";
    document.head.appendChild(st); dlg.classList.add("prewarming", "settled"); const act = document.activeElement;
    try { dlg.showModal(); } catch { dlg.classList.remove("prewarming"); st.remove(); return null; }
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(() => { dlg.close(); dlg.classList.remove("prewarming", "settled"); st.remove(); if (act && act.focus) act.focus(); }, 50)));
    return dlg;
  }
  function prewarm() {
    if (mode === "0") return null;
    if (mode === "dialog") return prewarm_dialog();
    const dlg = document.getElementById("alert"); if (!dlg) return null;
    const host = document.createElement("div"); host.className = "alert-prewarm"; host.setAttribute("aria-hidden", "true"); host.inert = true;
    /* the dialog's own box: index.html `dialog{position:fixed; width:var(--ios-alert-w); top:calc(50dvh + 14px); translate:0 -50%; border-radius:34}` */
    host.style.cssText = `position:fixed;left:0;right:0;margin:0 auto;top:calc(50dvh + 14px);translate:0 -50%;width:var(--ios-alert-w);max-width:calc(100vw - 32px);height:172px;` +
      `border-radius:var(--ios-alert-radius);overflow:hidden;pointer-events:none;opacity:${mode === "eps" ? ".01" : "0"};z-index:0;contain:strict`;
    /* the pane: index.html `dialog > .pane{inset:-60px; clip-path:inset(60px round r); background:var(--alert-fill); backdrop-filter:var(--ios-alert-glass-filter)}` */
    const pane = document.createElement("div"); pane.className = "pane";
    pane.style.cssText = `position:absolute;inset:-60px;clip-path:inset(60px round var(--ios-alert-radius));background:var(--alert-fill);` +
      `backdrop-filter:var(--ios-alert-glass-filter);-webkit-backdrop-filter:var(--ios-alert-glass-filter)`;
    host.appendChild(pane); document.body.appendChild(host);
    if (mode !== "keep") requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(() => host.remove(), 1500)));   // two painted frames + grace, then gone
    return host;
  }
  const start = () => { window.ALERT_PREWARM = { mode, host: prewarm(), at: performance.now() }; if (q.has("alertwarm")) setTimeout(measure, parseInt(q.get("alertwarm"), 10) > 1 ? parseInt(q.get("alertwarm"), 10) : 1500); };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", start); else start();

  /* ---- measurement ---- */
  async function open_once(label) {
    if (typeof ask !== "function") return null;
    delete window.ALERT_T; const t_call = performance.now(); const p = ask("预热测量", label, "好"); const t_open = performance.now();
    const stamps = []; const tick = (t) => { stamps.push(t); if (stamps.length < 6) requestAnimationFrame(tick); }; requestAnimationFrame(tick);
    const t0 = performance.now();
    while (stamps.length < 6 && performance.now() - t0 < 3000) await new Promise((r) => setTimeout(r, 5));
    const T = window.ALERT_T ? { f1: Math.round((ALERT_T.f1 - ALERT_T.open) * 10) / 10, f2: Math.round((ALERT_T.f2 - ALERT_T.open) * 10) / 10 } : {};
    T.call_ms = Math.round((t_open - t_call) * 10) / 10;                                     // ask() + showModal itself
    T.frames = stamps.map((t) => Math.round((t - t_open) * 10) / 10);                       // rAF timestamps after showModal (frame cadence)
    await new Promise((r) => setTimeout(r, 600));
    const c = document.getElementById("alert-cancel"); if (c) c.click();
    await p; await new Promise((r) => setTimeout(r, 600));
    return T;
  }
  async function measure() {
    const first = await open_once("第一次"); await new Promise((r) => setTimeout(r, 600)); const second = await open_once("第二次");
    const out = { prewarm: mode, first, second, ua: navigator.userAgent, standalone: matchMedia("(display-mode: standalone)").matches, at: new Date().toISOString(), href: location.href };
    try { localStorage.setItem(KEY, JSON.stringify(out)); } catch {}
    window.ALERT_WARM = out;
    const line = document.createElement("div");
    line.style.cssText = "position:fixed;left:0;right:0;bottom:calc(env(safe-area-inset-bottom) + 100px);text-align:center;font:12px/16px ui-monospace,monospace;color:var(--dim);pointer-events:none;z-index:99";
    line.textContent = `alert warm (prewarm ${mode}): first f1 +${first ? first.f1 : "?"} f2 +${first ? first.f2 : "?"} [${first ? first.frames.join(" ") : ""}] · second f1 +${second ? second.f1 : "?"} f2 +${second ? second.f2 : "?"} [${second ? second.frames.join(" ") : ""}] ms`;
    document.body.appendChild(line);
  }
})();
