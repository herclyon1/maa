/* 验收：页面地址加 ?accept 时加载，在这台设备的浏览器里量 DOM，逐项和
   docs/HIG-CHECKLIST.md 的数字比。只认 iOS Safari 的数（桌面 Chromium 没有安全区）。
   结果存进 localStorage 的 ark-accept，scripts/mac/phone-accept.sh 从模拟器的存储里
   读出来；不加 &quiet 时左上角盖一张表。
   方法照 ~/Money/transit/ui/accept.js（另一个会话 2026-09-15 定型）。
   2026-09-18：期望值改成 web/tokens.css 的原值（每项后面写变量名；出处在 tokens.css
   该变量上一行的注释：UIProbe 探针 / AX json / Kit NUMBERS）。期望值故意写死在这里，
   不从 tokens.css 读——两边同源的话 tokens 写错也会「通过」。颜色比对解析 rgb，不比字串。 */
/* night batch (BOARD.md A6): per-control acceptance files register through ACCEPT.add(fn); accept.js loads them in index.html hook order and runs
   each fn(ctx) after its own rows, ctx = { check, num, col, sleep }. A file that is still a shell registers nothing. */
/* T1 (2026-09-20): ?only=<控件>[,…] runs one control's file and sections only — see the note at ACCEPT.files below. */
window.ACCEPT = window.ACCEPT || { fns: [], add(fn, opt) { fn.__opt = opt || {}; fn.__file = this.loading || null; this.fns.push(fn); } };   // S4: opt = { layer, dark } (the file's layer tags); __file: the accept-<控件>.js being loaded (files load one after another) — its rows' tag (S6 / T1)
(function () {
  const q = new URLSearchParams(location.search);
  if (!q.has("accept")) return;
  /* 真机自检 (index.html head, window.__acceptDevice): a strip at the top says a run is on so nobody touches the page; it hangs off <html>, not <body>, and
     takes no pointer, so no check that walks body or hit-tests a point sees it. finish() takes it off and hands the result to view.js's share sheet. */
  const devStrip = window.__acceptDevice ? document.createElement("div") : null;
  if (devStrip) { devStrip.id = "accept-dev-strip"; devStrip.textContent = "自检进行中，约两分钟，别碰屏幕；跑完弹出结果";
    devStrip.style.cssText = "position:fixed;left:0;right:0;top:0;z-index:2147483647;pointer-events:none;padding:calc(env(safe-area-inset-top) + 4px) 12px 6px;background:rgba(0,0,0,.72);color:#fff;font:600 13px/1.3 -apple-system,system-ui,sans-serif;text-align:center";
    document.documentElement.appendChild(devStrip);
    /* the phone really leaving the page (another app, the lock button) stalls the run for good — a resumed page never finished (simulator 17:53, 88c25e1:
       the web app went to the background, came back and hung on 方舟 with no result). A real hidden (visibilityState; the checks' own synthetic
       visibilitychange events keep "visible") restarts the page without ?accept, so index.html's head puts the phone's data back, and view.js says so. */
    document.addEventListener("visibilitychange", () => { if (document.visibilityState !== "hidden" || !devStrip.isConnected) return;
      try { sessionStorage.setItem("ark-accept-cut", "1"); } catch (e) {}
      const q2 = new URLSearchParams(location.search); q2.delete("accept"); location.replace(location.pathname + (q2.toString() ? "?" + q2.toString() : "")); }); }
  /* the per-control files are appended dynamically; headless Chrome occasionally drops one of those fetches (night 00:3x: accept-sheet.js never
     requested in one run → 17 rows silently missing). Each load is tracked; a file that has not loaded when the checks start is re-appended, and
     a file still missing gets a ✗ row so the total never drops silently. */
  window.ACCEPT.files = ["page","tile","segctl","alert-view","tabbar-view","topbar-view","cell","motion","nav","nav-edge","sheet","menu","topbar","refresh","glassbtn","alert","switch","tabbar","diagmark","stockpile","textfit","toast","selfcheck"]; window.ACCEPT.loaded = new Set();   // 2026-09-20 split: page / tile / segctl / alert-view / tabbar-view / topbar-view / cell hold what were accept.js's own sections (run first: the static rows measure the untouched page)
  /* T1 (BOARD SPEED-summary §二 1): ?only=<控件>[,<控件>…] loads only those accept-<控件>.js files (the names above) and produces only their rows plus
     accept.js's own sections tagged with the same names through sec() — a worker's pre-push check runs in seconds; the whole suite (no ?only) is
     unchanged. Tags that exist only here: segctl (分段控件的交互行), cell (B14 行按压), page (页面行为：占位 / 回执 / 时间输入 / 迟到的 view.js / confirm),
     topbar / tabbar / alert / sheet / switch / tile (their static rows + interaction sections). "core" rows (readiness, loader, script errors) always count. */
  const ONLY = (() => { const v = (q.get("only") || "").split(",").map((s) => s.trim()).filter(Boolean); return v.length ? new Set(v) : null; })();
  const onlyHit = (c) => !ONLY || ONLY.has(c) || [...ONLY].some((o) => c.startsWith(o + "-"));   // ?only=alert → accept-alert.js and accept-alert-view.js; nav → nav, nav-edge
  if (ONLY) window.ACCEPT.files = window.ACCEPT.files.filter(onlyHit);
  let cur = "core";   // the section tag of the rows being produced now
  /* S4 (数据 S4-tags.md (c)(d)): layers. A file (ACCEPT.add(fn, { layer, dark })) or a section (sec(name, { layer, dark }); ctx.sec(name, opt) inside a file,
     falling back to the file's opt) is static (default), timing or release-only; ?layer=daily (default) runs static + timing, ?layer=release everything;
     ?theme=dark runs only dark:true files / sections (a light run ignores the dark flag). A skipped section produces no rows; "core" rows always count. */
  const LAYER = q.get("layer") === "release" ? "release" : "daily", DARKONLY = q.get("theme") === "dark";
  const runs = (o) => !((LAYER !== "release" && (o.layer || "static") === "release-only") || (DARKONLY && o.dark !== true));
  let secOn = true, curLayer = "static", curSec = null;   // the current section's decision / layer / (file sub-section) name
  const sec = (...args) => { const opt = args.length && typeof args[args.length - 1] === "object" && args[args.length - 1] !== null ? args.pop() : {}; cur = args[0]; curSec = null;
    let on = true; if (ONLY) { const hit = args.find((t) => onlyHit(t)); if (hit) cur = hit; on = !!hit; }   // T1: tags the rows that follow; false = skip the section under ?only (no section uses this since the split; kept for the files' ctx.sec fallback)
    curLayer = opt.layer || "static"; secOn = on && runs(opt); return secOn; };
  const secFile = (file, fo) => (name, opt) => { cur = file; curSec = name || null; const o = { ...fo, ...(opt || {}) }; curLayer = o.layer || "static"; secOn = runs(o); return secOn; };   // ctx.sec: the file stays the tag (?only / S6), layer / dark decide
  /* S2 (2号 2026-09-20 13:0x): each row records the tag of the section that produced it (`tag`, printed by accept-run.py as ⟨file⟩ — 验收 S6 attributes a red row
     to its file by it). A control file's rows get the file's name: ACCEPT.add is wrapped here so the function it registers sets `cur` to the name of the
     script that called it (document.currentScript — the loader's classic <script> tags) when it starts; no other behaviour changes. */
  { const add0 = window.ACCEPT.add.bind(window.ACCEPT), from = new Map();   // file → the <script> src its fns came from
    window.ACCEPT.add = (fn, opt) => { const src = (document.currentScript || {}).src || "", m = /accept-([^./?]+)\.js/.exec(src); if (!m) return add0(fn, opt);
      /* a second copy of a file (its first fetch outlived the loader's 4 s timeout, then ran after the retry — OPEN.md 验收 on 0fe960c) registers
         nothing: only the first script element of a file counts (nav / topbar register two fns from one element) */
      if (from.has(m[1]) && from.get(m[1]) !== src) return; from.set(m[1], src);
      const w = async (ctx) => { cur = m[1]; return fn(ctx); }; Object.defineProperty(w, "name", { value: fn.name }); add0(w, opt); w.__file = m[1]; }; }   // S4: opt passed through; __file from the script's own name
  /* one script per file: a load already done or in flight is answered, not appended again — on the phone the checks start before this chain
     has appended every file, and the retry below then appended a second copy of each (simulator A 18:36, b8bc7e3: 42 fetches for 21 files,
     every fn registered twice, 1320 rows for 660) */
  const pend = new Map();
  window.ACCEPT.load = (c) => window.ACCEPT.loaded.has(c) ? Promise.resolve(true) : pend.get(c) || (pend.set(c, new Promise((res) => { window.ACCEPT.loading = c; let fin = false; const done = (v) => { if (fin) return; fin = true; if (window.ACCEPT.loading === c) window.ACCEPT.loading = null; pend.delete(c); res(v); };
    const s = document.createElement("script"); s.src = "accept-" + c + ".js?r=" + Math.random().toString(36).slice(2, 7); s.onload = () => { window.ACCEPT.loaded.add(c); done(true); }; s.onerror = () => done(false); document.head.appendChild(s); setTimeout(() => done(false), 4000); })), pend.get(c));
  (async () => { for (const c of window.ACCEPT.files) await window.ACCEPT.load(c); })();   // one after another (≈ 50 ms each): ACCEPT.loading names the file whose fn registers
  const rows = [];
  const near = (a, b, tol = 0.6) => Math.abs(a - b) <= tol;
  const cs = (el, pseudo) => el ? getComputedStyle(el, pseudo || null) : null;
  const px = (v) => parseFloat(v) || 0;
  /* top safe-area inset as the page sees it: 62 in the standalone web clip (black-translucent, web view covers the whole 956),
     0 in a browser viewport — the geometry below is expressed relative to it, the way the page's own CSS is */
  const satTop = () => { const pr = document.createElement("div"); pr.style.cssText = "position:fixed;top:0;left:0;width:1px;padding-top:env(safe-area-inset-top);visibility:hidden";
    document.body.appendChild(pr); const v = px(cs(pr).paddingTop); pr.remove(); return v; };
  /* S5 / S4: a row records its section (`tag`, S6 attribution), its layer (S4) and, inside a control file, the ctx.sec name (`sec`); check(item, expect, got,
     ok, { tags: [...] }) may add free tags. Rows of a skipped section (?only / ?layer / ?theme) are not produced; "core" rows always are. */
  function check(item, expect, got, ok, opts) {
    if (cur !== "core" && (!secOn || !onlyHit(cur))) return;
    const row = { item, expect: String(expect), got: got === undefined || got === null ? "缺" : String(typeof got === "number" ? Math.round(got * 100) / 100 : got), ok: !!ok, tag: cur, layer: curLayer };
    if (curSec) row.sec = curSec;
    if (opts && opts.tags && opts.tags.length) row.tags = [...opts.tags];
    rows.push(row);
  }
  function num(item, expect, got, tol, opts) { check(item, expect, got, typeof got === "number" && near(got, expect, tol), opts); }
  /* Colours: computed styles come back as rgb(r, g, b) / rgba(r, g, b, a); compare the
     numbers (tolerance 3 per channel, .02 alpha), never the string. */
  const rgb = (c) => { const m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/.exec(c || ""); return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null; };
  const same = (c, want, tol = 3) => { const a = rgb(c); return !!a && a.slice(0, 3).every((v, i) => Math.abs(v - want[i]) <= tol) && Math.abs(a[3] - (want[3] === undefined ? 1 : want[3])) <= 0.02; };
  const fmt = (want) => want.length > 3 && want[3] !== 1 ? `rgba(${want[0]},${want[1]},${want[2]},${want[3]})` : `rgb(${want[0]},${want[1]},${want[2]})`;
  function col(item, want, got, opts) { check(item, fmt(want), got, same(got, want), opts); }
  /* A page variable's colour, resolved by the browser (var(--accent) → rgb). */
  const varColor = (name, probe) => { probe.style.color = `var(${name})`; return cs(probe).color; };

  function run() {
    const dark = matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light" || document.documentElement.dataset.theme === "dark";
    /* tokens.css semantic colours (UIProbe colour table, light / dark) */
    const T = {
      tint: dark ? [0, 145, 255] : [0, 136, 255],               // --ios-tint
      link: dark ? [9, 132, 255] : [0, 122, 255],               // --ios-link
      red: dark ? [255, 66, 69] : [255, 56, 60],                // --ios-red
      green: dark ? [48, 209, 88] : [52, 199, 89],              // --ios-green / --ios-switch-on
      swOff: dark ? [235, 235, 245, .298] : [60, 60, 67, .298], // --ios-switch-off
      sep: dark ? [84, 84, 88, .5] : [60, 60, 67, .12],         // --ios-separator
      card: dark ? [28, 28, 30] : [255, 255, 255],              // --ios-card-bg
      bg: dark ? [0, 0, 0] : [242, 242, 247],                   // --ios-grouped-bg
      dim: dark ? [235, 235, 245, .6] : [60, 60, 67, .6],       // --ios-secondary-label
    };
    const probe = document.createElement("i"); probe.style.cssText = "position:fixed;left:-9999px;top:0"; document.body.appendChild(probe);

    check("view.js 就绪后才量（window.__viewReady，accept.js 等它 ≤ 60 s）", "true", String(window.__viewReady), window.__viewReady === true);
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    /* S1 (BOARD SPEED2): a settle wait ends when the driver's own rest flag holds (checked every frame) or after maxMs — the old fixed wait, so no
       wait is longer than before; returns the ms waited. segRest: view.js's lens loop writes __segLens.phase "done" when it stops. */
    const raf = () => new Promise(requestAnimationFrame);
    const settle = async (pred, maxMs) => { const t0 = performance.now(); await raf(); while (!pred() && performance.now() - t0 < maxMs) await raf(); return performance.now() - t0; };
    const segRest = (maxMs) => settle(() => { const L = window.__segLens; return !L || L.phase === "done"; }, maxMs);
    const tabRest = (maxMs) => settle(() => { const n = document.querySelector("nav.tabs"); return !n || !n.classList.contains("tl-on"); }, maxMs);   // tab-lens.js drops .tl-on when its driver rests
    const fadeRest = async (el, maxMs) => { await settle(() => !el.getAnimations || el.getAnimations().length === 0, maxMs); await raf(); };   // the element's CSS transitions have finished (+ one frame)
    const at = (el, fx = .5, fy = .5, dx = 0, dy = 0) => { const r = el.getBoundingClientRect(); return { x: r.left + r.width * fx + dx, y: r.top + r.height * fy + dy }; };
    /* 两钟同读 (收尾单 ③): a synthetic event's timeStamp is stamped by the browser's real clock; the drivers read e.timeStamp as their time base (view.js segLens
       downAt / drag / up), so under the runner's virtual time (accept-run.py --virtual-time) the two clocks mixed. The event gets the PAGE clock — an own
       timeStamp property = performance.now() — exactly what a real touch carries. */
    const stamp = (e) => { Object.defineProperty(e, "timeStamp", { value: performance.now(), configurable: true }); return e; };
    const pev = (el, type, p, id = 11) => el.dispatchEvent(stamp(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: id, clientX: p.x, clientY: p.y, isPrimary: true, button: 0, buttons: type === "pointerup" ? 0 : 1, pointerType: "touch" })));
    const segQ = () => document.querySelector("#queueseg"), segBs = () => [...document.querySelectorAll("#queueseg button")];   // the segmented control's helpers for the files (q / bs in their ctx; q here is the URLSearchParams)
    const onText = () => (document.querySelector("#queueseg button.on") || {}).textContent || "";
    const thisShift = (name) => { const sec = [...document.querySelectorAll("#app section")].find((x) => ((x.querySelector("h2") || {}).textContent || "").trim() === "这一趟"); return !!sec && [...sec.querySelectorAll(".row label")].some((l) => l.textContent.includes(name + " · ")); };
    /* the page's render() count for the control files (segctl / cell rows): wrapped for the run, restored after every file has run */
    const R = { n: 0 }; const origRender = window.render; window.render = function () { if (!/live\.js|stamina\.js/.test(String(new Error().stack))) R.n++; return origRender.apply(this, arguments); };   // R.n counts the CONTROLS' renders: a live.js tick / snapshot arrival (its own clock) landing inside a row's window is not the control's re-render (收尾单 ③: G3 / G1 renders+2)
    const ctx0 = { check, num, col, sleep, settle, raf, segRest, tabRest, fadeRest, at, pev, cs, px, T, dark, near, rgb, same, fmt, satTop, varColor, probe, q: segQ, bs: segBs, onText, thisShift, R, stamp };
    const finish = () => {
      const fails = rows.filter((r) => !r.ok).length;
      const out = { at: new Date().toISOString(), href: location.href, viewport: `${innerWidth}×${innerHeight}`,
                    standalone: matchMedia("(display-mode: standalone)").matches,
                    dark, only: ONLY ? [...ONLY].join(",") : null, layer: LAYER, dark_only: DARKONLY, total: rows.length, fails, rows };
      try { localStorage.setItem("ark-accept", JSON.stringify(out)); } catch {}
      if (devStrip) { devStrip.remove(); dispatchEvent(new CustomEvent("arkaccept", { detail: out })); }
      document.title = `验收 ${rows.length - fails}/${rows.length}`;
      if (!q.has("quiet")) {
        const box = document.createElement("pre");
        box.style.cssText = "position:fixed;left:8px;top:60px;z-index:99;max-height:70vh;overflow:auto;background:rgba(0,0,0,.82);color:#fff;font:11px/1.35 -apple-system,monospace;padding:8px;border-radius:8px;margin:0;white-space:pre";
        box.textContent = `${out.viewport}${out.standalone ? " 主屏幕" : " Safari"}${out.dark ? " 深色" : ""}  ${rows.length - fails}/${rows.length}\n` +
          rows.map((r) => `${r.ok ? "✓" : "✗"} ${r.item}  ${r.got}${r.ok ? "" : "（要 " + r.expect + "）"}`).join("\n");
        document.body.appendChild(box);
      }
    };
    /* every row now comes from an accept-<控件>.js file (2026-09-20 split, BOARD 收尾单 ②): load what is missing, run the files in ACCEPT.files order */
    const extra = async () => {
      if (window.ACCEPT) { for (const c of window.ACCEPT.files) { cur = c; secOn = true; curLayer = "static"; curSec = null; if (!window.ACCEPT.loaded.has(c)) await window.ACCEPT.load(c); if (!window.ACCEPT.loaded.has(c)) await window.ACCEPT.load(c);
          check(`accept-${c}.js 已加载（动态脚本，丢了会重取两次）`, "已加载", window.ACCEPT.loaded.has(c) ? "已加载" : "缺", window.ACCEPT.loaded.has(c)); } }
      for (const fn of (window.ACCEPT ? window.ACCEPT.fns : [])) { const file = fn.__file || "core", fo = fn.__opt || {}; cur = file; curSec = null; curLayer = fo.layer || "static"; secOn = runs(fo);
        if (!secOn) continue;   // S4: the file's layer is not in this run (release-only under daily / not dark:true under ?theme=dark)
        try { await fn({ ...ctx0, sec: secFile(file, fo) }); } catch (e) { secOn = true; check("控件检查文件出错 " + (fn.name || ""), "", String(e), false); } }
      cur = "core"; secOn = true; curSec = null; window.render = origRender; probe.remove(); };
    extra().then(finish, (e) => { cur = "core"; check("控件检查出错", "", String(e), false); finish(); });
  }
  /* The page renders after its first snapshot and the number tiles after the game
     APIs answer: measure once the tiles exist (or after 8 s) — never before view.js's top-level bindings exist (window.__viewReady, set at the
     end of view.js; the inline loader can deliver it late) and never while a runner holds the start (window.__acceptHold: scripts/mac/accept-run.py
     sets it before any page script and clears it once its snapshot / stamina data is injected). 60 s hard cap so a stuck page still reports. */
  let tries = 0;
  const t = setInterval(() => { tries++;
    const ready = window.__viewReady === true && !window.__acceptHold;
    if ((ready && (document.querySelector(".num") || tries > 80)) || tries > 600) { clearInterval(t); run(); } }, 100);
})();
