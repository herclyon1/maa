/* tap-platter-check.js — the fixed check of README §0.8.12: through a whole tap (lift → fall → rest) the control's platter must be visible on
   at least one side every tick — the DOM platter (`.lens`, transparent while the control carries `.lift`) or the WebGL canvas (drawn while the
   package has a lift > 0). Run by scripts/mac/seg-tap-platter-check.sh in an offscreen WKWebView on index.html?demo=1: presses the unselected
   segment, releases, steps the page's own loop 16.7 ms at a time and reads per tick p / .lift / the DOM platter's background / drew-or-cleared /
   the canvas's opaque pixels (offscreen nothing is presented, so readPixels reads the real buffer). window.__seq holds the result;
   `bad` = ticks with .lift on and the canvas clear. */
(() => { window.__seq = { note: "started" }; (async () => { const seg = document.querySelector("#queueseg"); if (!seg) { window.__seq = { note: "no #queueseg" }; return; }
  const bs = [...seg.querySelectorAll("button")], on = bs.findIndex((b) => b.classList.contains("on")), tgt = bs[on === 0 ? 1 : 0], r = tgt.getBoundingClientRect(); const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const lens = seg.querySelector(".lens");
  const ev = (t) => tgt.dispatchEvent(new PointerEvent(t, { bubbles: true, cancelable: true, pointerId: 1, isPrimary: true, pointerType: "touch", clientX: x, clientY: y, button: 0, buttons: t === "pointerup" ? 0 : 1 }));
  ev("pointerdown"); const L = seg.__gl && seg.__gl.lens; if (!L) { window.__seq = { note: "no gl after the down" }; return; } await L.ready; await new Promise((res) => setTimeout(res, 300));
  const alpha = () => { const gl = L.gl, cv = L.canvas, px = new Uint8Array(cv.width * cv.height * 4); gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.readPixels(0, 0, cv.width, cv.height, gl.RGBA, gl.UNSIGNED_BYTE, px); let n = 0; for (let i = 3; i < px.length; i += 4) if (px[i]) n++; return n; };
  ev("pointerup"); const loop = seg.__lensLoop; if (!loop) { window.__seq = { note: "no loop after the up" }; return; }
  const seq = []; let f0 = L.stats.frames;
  for (let i = 0; i < 400 && !loop.state.done; i++) { loop.step(16.7); const s = window.__segLens || {}; const fr = L.stats.frames; seq.push({ i, p: s.p, ph: s.phase, lift: seg.classList.contains("lift"), lensBg: getComputedStyle(lens).backgroundColor, drew: fr > f0, alpha: alpha() }); f0 = fr; }
  const bad = seq.filter((t) => t.lift && t.alpha === 0);
  window.__seq = { done: loop.state.done, n: seq.length, bad: bad.length, badTicks: bad.map((t) => [t.i, t.p]), seq }; })(); return "ok"; })()
