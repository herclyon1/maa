/* accept-tabbar-view.js — the bottom tab bar as view.js drives it (attachTabBar / layoutTabs / the keyboard rule; 界面): the static rows (platter,
   buttons, glide tokens) and the interactions that were accept.js's "tabbar" sections — the keyboard rule (html.kbd, R28′), §2 UITabBar T1–T11 /
   R59′c / R106 / R10 scroll-to-top / R0③ set change / R31. accept-tabbar.js (2号) holds the lens driver rows. Split out of accept.js 2026-09-20
   (BOARD 收尾单 ②); row texts and expected values unchanged. */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptTabbarView(ctx) {
    const { check, num, col, sleep, settle, raf, sec, segRest, tabRest, fadeRest, at, pev, cs, px, T, dark, near, rgb, same, fmt, satTop, varColor, probe, q, bs, onText, thisShift, R } = ctx;
    sec("static", { layer: "static", dark: true });
  /* Tab bar: hidden when the snapshot has a single tab (nav.hidden = present.size < 2);
     measure a synthetic one then, so the run does not depend on the data. */
  let seg = document.querySelector("nav.tabs:not([hidden]) .seg"), fakeNav = null;
  if (!seg) {
    fakeNav = document.createElement("nav"); fakeNav.className = "tabs"; fakeNav.style.visibility = "hidden";
    fakeNav.innerHTML = `<div class="plat"></div><i class="glide"></i><div class="seg"><button type="button" class="on"><span class="ico"><i class="sf"></i></span>状态</button><button type="button"><span class="ico"><i class="sf"></i></span>手机</button></div>`;
    document.body.appendChild(fakeNav); seg = fakeNav.querySelector(".seg");
  }
  if (seg) {
    const r = seg.getBoundingClientRect();
    num("标签栏胶囊高 62（--ios-tab-capsule-h，探针平台 274×62）", 62, r.height);
    num("标签栏胶囊内缩 4（--ios-tab-button-pad）", 4, px(cs(seg).paddingLeft));
    if (!fakeNav) {
      const gap = innerHeight - r.bottom;
      const standalone = matchMedia("(display-mode: standalone)").matches;
      if (standalone) num("标签栏底边距屏底 21（--ios-tab-capsule-bottom）", 21, gap);
      else check("标签栏在 Safari 地址栏之上", "> 0", Math.round(gap), gap > 0);
    }
    const bs = seg.querySelectorAll("button"), b = bs[0];
    if (b) {
      const w = b.getBoundingClientRect().width, want = Math.min(94, (r.width - 8) / bs.length);
      num("标签按钮高 54（--ios-tab-button-h）", 54, b.getBoundingClientRect().height);
      num(`标签按钮宽 ${Math.round(want * 100) / 100}（--ios-tab-button-w 94，${bs.length} 个标签放不下时等比缩）`, want, w);
      num("标签文字 10（--ios-tab-label-size）", 10, px(cs(b).fontSize), 0.05); num("标签按钮圆角 27（--ios-tab-lens-radius）", 27, px(cs(b).borderTopLeftRadius));
      const lb = [...b.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim()) || b.querySelector(".tcg > span:not(.ico)") || b.querySelector("span:not(.ico)");   // the unselected copy (P0b-tabclip); the selected copy (.tcs) must sit on it
      const lbs = b.querySelector(".tcs > span:not(.ico)"), ics = b.querySelector(".tcs > .ico"), icg = b.querySelector(".tcg > .ico");
      if (lbs && lb && ics && icg) { const a = lbs.getBoundingClientRect(), c = b.querySelector(".tcg > span:not(.ico)").getBoundingClientRect(), d = ics.getBoundingClientRect(), e = icg.getBoundingClientRect();
        num("标签两份（选中色 / 灰）叠在同一处：字与图标框差之和", 0, Math.abs(a.left - c.left) + Math.abs(a.top - c.top) + Math.abs(a.width - c.width) + Math.abs(d.left - e.left) + Math.abs(d.top - e.top) + Math.abs(d.width - e.width), 0.5); }
      if (lb) { const rg = document.createRange(); rg.selectNodeContents(lb); const lr = rg.getBoundingClientRect(); num("标签文字顶 = 胶囊顶 + 39（--ios-tab-label-top）", 39, lr.top - r.top, 1.5); }
    }
    const ico = seg.querySelector(".ico"); if (ico) num("标签符号框 28（--ios-tab-symbol-box，探针 27–31）", 28, ico.getBoundingClientRect().height);
    const plat = seg.parentElement.querySelector(".plat") || seg, segbf = cs(plat).backdropFilter || cs(plat).webkitBackdropFilter || "";
    check("标签栏平台玻璃 blur 10（= --ios-glass-blur 5 ÷ backdrop scale .5 ← ⑨）", "blur(10px)", (/blur\([\d.]+px\)/.exec(segbf) || [])[0], /blur\(10px\)/.test(segbf));
    check("透镜不嵌在平台里（平台 backdrop-filter 是 backdrop root）", "sibling", seg.parentElement.querySelector(":scope > .glide") ? "sibling" : "nested", !!seg.parentElement.querySelector(":scope > .glide"));
    const gl = seg.parentElement.querySelector(".glide"); if (gl) { const gbf = cs(gl).backdropFilter || cs(gl).webkitBackdropFilter || "";
      check("标签栏选中透镜 blur 2（--ios-lens-blur）", "blur(2px)", (/blur\([\d.]+px\)/.exec(gbf) || [])[0], /blur\(2px\)/.test(gbf));
      const wantF = dark ? "blur(2px) saturate(1.379) brightness(0.763) contrast(1.14)" : "blur(2px) saturate(1.062) brightness(0.807) contrast(1.4)";
      check("标签栏透镜滤镜链 = 矩阵（--ios-lens-filter：blur · saturate · brightness · contrast）", wantF, gbf.replace(/\s+/g, " "), gbf.replace(/\s+/g, " ") === wantF);
      check("标签栏透镜无叠层（::after 不参与）", "none", cs(gl, "::after").content, cs(gl, "::after").content === "none");
      check("透镜滑动 0.55 s（--ios-motion-lens-duration，dampingRatio .85 / response .4）", "0.55s", cs(gl).transitionDuration.split(",")[0].trim(), /^0\.55s/.test(cs(gl).transitionDuration)); }
  }
  if (fakeNav) fakeNav.remove();
  /* 数据终核 181053 ⑤1/3: with the keyboard up (visual viewport > 120 px shorter) the tab capsule is hidden (html.kbd), and comes back when it closes */
  if (sec("keyboard", { layer: "timing" })) { const nav0 = document.querySelector("nav.tabs"), on = window.__tabKbd && window.__tabKbd(innerHeight - 300), hid = nav0 ? getComputedStyle(nav0).display : "-";
    const off = window.__tabKbd && window.__tabKbd(null), shown = nav0 ? getComputedStyle(nav0).display : "-", nb = nav0 ? nav0.getBoundingClientRect() : null;
    check("键盘弹出（视口矮 300）时底部标签胶囊藏起（html.kbd → display none），收起后回到屏底（原生 tab bar 被键盘盖住，不浮到键盘上）", "kbd hidden → shown at bottom", `kbd ${on} ${hid} → ${off} ${shown} bottom gap ${nb ? Math.round(innerHeight - nb.bottom) : "-"}`, on === true && hid === "none" && off === false && shown !== "none" && !!nb && innerHeight - nb.bottom >= 0 && innerHeight - nb.bottom < 120);
    const fi = document.querySelector("input[data-time]") || document.querySelector('#app input[type="text"]');
    if (fi && nav0) { const sy0 = scrollY; fi.focus({ preventScroll: true }); const hasF = document.hasFocus(); await sleep(360); const dF = !document.documentElement.classList.contains("kbd") && getComputedStyle(nav0).display !== "none";
      /* the reveal (数据 190821: the first focus of the time field stayed under the keyboard): with a pretended 300 px visible height the active field must be scrolled into it */
      scrollTo(0, 0); const r0 = fi.getBoundingClientRect().top, did = window.__kbdReveal && window.__kbdReveal(300); await sleep(700); const r1 = fi.getBoundingClientRect(); const inside = r1.top >= 0 && r1.bottom <= 300;
      fi.blur(); await sleep(120); const dB = !document.documentElement.classList.contains("kbd") && getComputedStyle(nav0).display !== "none"; scrollTo(0, sy0);
      check("聚焦本身不动胶囊（只认视口变矮，监督局 19:3x）：文本框聚焦 360 ms 后胶囊仍在，失焦后仍在", "focus shown · blur shown", `hasFocus ${hasF} · focus ${dF ? "shown" : "hidden!"} · blur ${dB ? "shown" : "hidden!"}`, dF && dB);
      check("键盘露出 300 px 时聚焦的字段滚进可见区（I3 起按 scrollRectToVisible 最少滚动 + 大标题停点，不再居中；190821 首次聚焦字段留在键盘下）", "field inside 0…300", `top ${Math.round(r0)} → ${Math.round(r1.top)}…${Math.round(r1.bottom)} · scrolled ${did}`, hasF ? (did === true && inside) : true); } }
  /* 监督局 19:4x: keyboard state = viewport evidence only. Android shrinks innerHeight itself (vv.height = innerHeight): H0 − innerHeight > 120 hides; the
     viewport recovering shows — with a text field focused the whole time (the keyboard may go without a blur: iOS tap on the segments, Android back key) */
  if (sec("keyboard", { layer: "timing" })) { const fi2 = document.querySelector("input[data-time]"), nv2 = document.querySelector("nav.tabs");
    if (fi2 && nv2) { fi2.focus({ preventScroll: true }); const a1 = window.__tabKbd(innerHeight - 300, innerHeight - 300), d1 = getComputedStyle(nv2).display;
      const a2 = window.__tabKbd(null), d2 = getComputedStyle(nv2).display; const a3 = window.__tabKbd(innerHeight - 300), d3 = getComputedStyle(nv2).display; const a4 = window.__tabKbd(null), d4 = getComputedStyle(nv2).display; fi2.blur();
      check("键盘只信视口：安卓式 innerHeight 缩 300（H0 基线）→ 藏，回高 → 放回；iOS 式 vv 缩 300 → 藏，回高 → 放回；全程字段保持聚焦（不经失焦收键盘也放回）", "hidden shown hidden shown", `${a1} ${d1} · ${a2} ${d2} · ${a3} ${d3} · ${a4} ${d4}`, a1 === true && d1 === "none" && a2 === false && d2 !== "none" && a3 === true && d3 === "none" && a4 === false && d4 !== "none"); } }
  /* BOARD R28′ (state-tables/tabbar.md §6, R28 probe): the native floating tab bar does not move, hide or fade while the keyboard shows / hides (317 frames at
     (0, 873, 440, 83), alpha 1) — the keyboard window simply covers it and slides away in .3833 s. The page hides the capsule while the viewport is short
     (browsers float fixed elements above the keyboard); the equivalence to check: when the keyboard goes, the capsule is back in the very same rect, the same
     nodes, without any transition — within one frame */
  if (sec("keyboard", { layer: "timing" })) { const nv3 = document.querySelector("nav.tabs");
    if (nv3) { const r0 = nv3.getBoundingClientRect(), plat0 = nv3.querySelector(":scope > .plat"), gl0 = nv3.querySelector(":scope > .glide");
      window.__tabKbd(innerHeight - 300); const hidden = getComputedStyle(nv3).display === "none"; window.__tabKbd(null); await new Promise(requestAnimationFrame);
      const r1 = nv3.getBoundingClientRect(), same = Math.abs(r1.top - r0.top) < 0.01 && Math.abs(r1.left - r0.left) < 0.01 && Math.abs(r1.width - r0.width) < 0.01 && Math.abs(r1.height - r0.height) < 0.01, nodes = plat0 === nv3.querySelector(":scope > .plat") && gl0 === nv3.querySelector(":scope > .glide");
      const tr = getComputedStyle(nv3).transitionProperty, trOK = !/transform|bottom|top|opacity/.test(tr) || getComputedStyle(nv3).transitionDuration.split(",").every((d) => parseFloat(d) === 0);
      check("R28′ 键盘收起后胶囊原位原样：视口回高后下一帧 rect 与键盘前逐项相同（±.01）、.plat/.glide 同一节点、nav 无位置/透明度过渡（原生 R28：标签栏全程一帧不动，只是被键盘盖住）", "hidden → same rect · same nodes · no transition", `hidden ${hidden} · same ${same} · nodes ${nodes} · transition ${tr} ${getComputedStyle(nv3).transitionDuration}`, hidden && same && nodes && trOK); } }
  /* §2 UITabBar */
  const nav = document.querySelector("nav.tabs:not([hidden])"), tseg = nav && nav.querySelector(".seg"), tbs = nav ? [...nav.querySelectorAll(".seg button")] : [];
  if (sec("selection", { layer: "timing" }) && nav && tbs.length > 1) {
    const tOn = () => (nav.querySelector(".seg button.on") || {}).dataset.tab, g = nav.querySelector(".glide"), startTab = tOn();
    const other = tbs.find((b) => !b.classList.contains("on")), cur = tbs.find((b) => b.classList.contains("on"));
    const shown = () => [...document.querySelectorAll("#app > section:not([hidden])")].map((x) => x.dataset.tab).filter((v, i, a) => a.indexOf(v) === i).join(",");
    pev(tseg, "pointerdown", at(other));
    check("标签栏 T1 按下未选中项 +0 ms：不选中；高亮类 .lift 即在（R59′e / R108：落指 → highlightedItemIndex → setLifted 无定时器，+140 令牌作废）", `${startTab} · lift`, `${tOn()} lift=${g.classList.contains("lift")}`, tOn() === startTab && g.classList.contains("lift"));
    /* +60 / +200 / +600 are read on the driver's own clock (BOARD A15: window.__tabLens.t, the frame time the springs were stepped to), not the harness's
       wall clock: on 模拟器 A under 老网页's full run (0fe960c, OPEN.md 09-23 18:50) the driver had drawn no frame 60 ms of wall time after the synthetic down
       and the rows read "p -" / "h 54" (why that frame was late is not measured — the harness's own waits are what the row must not depend on); a real finger on 模拟器 B, fresh load, lifts from +2 ms: +64 p .486, +198 h 73.2
       (evidence 界面-OPEN78-T1-新载首按.json) */
    const untilT = async (tt, max) => { const end = performance.now() + max; while (performance.now() < end) { const L = window.__tabLens; if (L && L.t >= tt) return L; await new Promise(requestAnimationFrame); } return window.__tabLens; };
    await untilT(0.06, 1500);
    { const L = window.__tabLens; check("标签栏 T1 +60 ms：驱动器已在抬（按下下一 tick 起，探针 +47 已 95.76）：p > 0、仍不选中", "p > 0 · not selected", `p ${L ? L.p.toFixed(3) : "-"} · ${tOn()}`, !!L && L.p > 0 && tOn() === startTab); }
    await untilT(0.2, 1500);
    { const gr = g.getBoundingClientRect();   // #7a (tab-lens.js geometry mode): the lift is the box itself, w0 × 54 → (w0 + 16) × 70 on ζ 1 / .25 from +140 ms (tab-lens-motion.md §0 / §4), view.js's inline left = the pressed item is the target
      check("标签栏 T1 +200 ms：透镜抬起中并滑向被按项（R59′d / R108：按下下一帧起 ζ1/.25 抬向 +22.7 × 74、位置 ζ.85/.4；.lift 类自按下即在）", `left→${other.offsetLeft}, lift, 54 < h ≤ 74`, `left ${g.style.left} ${g.classList.contains("lift") ? "lift" : "-"} h ${gr.height.toFixed(1)}`, g.classList.contains("lift") && g.style.left === other.offsetLeft + "px" && gr.height > 54 && gr.height <= 74.5); }   // 2号 R59′d: the lens's lifted size per the probe (tab-lens-motion §6.9 ⑤)
    await untilT(0.6, 1500);
    { const gr = g.getBoundingClientRect();
      check("标签栏 T5 按住 600 ms：仍不选中，透镜停在 (w0 + 22.7) × 74（R108 探针 94×54 → 116.7 × 74.0，tab-lens-motion §6.9 ⑤；旧 +16 两轴是选中框的 inset）", `${startTab} ${(other.offsetWidth + 22.7).toFixed(1)}×74`, `${tOn()} ${gr.width.toFixed(1)}×${gr.height.toFixed(1)}`, tOn() === startTab && Math.abs(gr.width - (other.offsetWidth + 22.7)) <= 0.5 && Math.abs(gr.height - 74) <= 0.5); }   // 2号 R59′d
    const t1 = performance.now(); pev(tseg, "pointerup", at(other)); const d1 = performance.now() - t1;
    check("标签栏 T1 抬手：+0 ms 选中、内容同步切", other.dataset.tab, `${tOn()} 显示 ${shown()} +${Math.round(d1 * 10) / 10} ms`, tOn() === other.dataset.tab && shown() === other.dataset.tab && d1 < 50);
    /* Behaviour 3: scroll offsets are kept per tab (Health: 0 px difference after switching away and back, tabscroll/README §1) */
    { const nv = document.querySelector("nav.tabs"), sg = nv.querySelector(".seg"), bb = [...sg.querySelectorAll("button")], startB = bb.find((b) => b.dataset.tab === startTab), otherB = bb.find((b) => b.dataset.tab === other.dataset.tab);
      window.scrollTo(0, 150); const y1 = window.scrollY;
      pev(sg, "pointerdown", at(startB)); pev(sg, "pointerup", at(startB)); await sleep(30); const yStart = window.scrollY;
      pev(sg, "pointerdown", at(otherB)); pev(sg, "pointerup", at(otherB)); await sleep(30);
      check("切标签保留各自滚动位置（切走 → 切回差 0，Health 实测）", `${y1} → ${y1}`, `${y1} → ${yStart} → ${window.scrollY}`, y1 > 0 && yStart === 0 && Math.abs(window.scrollY - y1) < 1);
      /* tap on the selected tab: to the top on the system scroll-to-top (tabscroll/README §2b, R17: progress = S(1.6 · bezier(0,.2,1,1)(t / 1.6)), S = ζ 1 / response .6);
         sampled every frame against the driver's own clock (window.ScrollTop.state.t0, A15), rms ≤ 1 pt; 0 by 1.6 s */
      const y2 = window.scrollY; pev(sg, "pointerdown", at(otherB)); pev(sg, "pointerup", at(otherB));
      const stS = []; { const tEnd = performance.now() + 1700; while (performance.now() < tEnd) { await new Promise(requestAnimationFrame); const s = window.ScrollTop && window.ScrollTop.state; if (s && s.last) stS.push({ t: s.last.t, yW: s.last.y, y: window.scrollY, y0: s.y0 }); } }   // the driver's own frame (t, written y) and the browser's scrollY after it (A15)
      const F = window.ScrollTop && window.ScrollTop.formula, rmsTop = F && stS.length ? Math.sqrt(stS.reduce((acc, s) => acc + Math.pow(s.yW - s.y0 * (1 - F.progress(s.t)), 2), 0) / stS.length) : NaN, rmsScr = stS.length ? Math.sqrt(stS.reduce((acc, s) => acc + Math.pow(s.y - s.yW, 2), 0) / stS.length) : NaN;
      const p2 = F ? Math.round(F.progress(0.2) * 1000) / 10 : NaN;
      check("点已选中标签回顶：系统回顶式（§2b：贝塞尔 (0,.2,1,1) 再临界弹簧 ζ1/.6，D 1.6 s；.2 s 应 85.8 %）驱动器逐帧写入值对闭式 rms ≤ .01 pt（本帧 t，A15），浏览器 scrollY 对写入值 rms ≤ 1 pt（整数取整），1.6 s 内到 0", `rms ≤ .01 · scrollY rms ≤ 1 · progress(.2) 85.8 · end 0`, `${stS.length} frames · rms ${isNaN(rmsTop) ? "-" : rmsTop.toFixed(3)} · scrollY rms ${isNaN(rmsScr) ? "-" : rmsScr.toFixed(2)} · progress(.2) ${p2} · end ${window.scrollY}`, y2 > 0 && stS.length > 20 && rmsTop <= 0.01 && rmsScr <= 1 && Math.abs(p2 - 85.8) < 0.2 && window.scrollY === 0);
      window.scrollTo(0, 0); }
    { const sg = document.querySelector("#queueseg"); check("班次分段只在「状态」页（别的标签页隐藏）", "hidden", sg ? (sg.hidden ? "hidden" : "shown") : "缺", !!sg && sg.hidden && getComputedStyle(sg).display === "none"); }
    /* T7/T8: release 250 pt above still selects */
    const nav2 = document.querySelector("nav.tabs"), seg2 = nav2.querySelector(".seg"), b2 = [...seg2.querySelectorAll("button")];
    const back = b2.find((b) => b.dataset.tab === startTab);
    pev(seg2, "pointerdown", at(back)); pev(seg2, "pointermove", at(back, .5, .5, 0, -250)); pev(seg2, "pointerup", at(back, .5, .5, 0, -250));
    check("标签栏 T7 竖向滑出 250 pt 抬手：仍选中被按项（无距离取消）", startTab, (nav2.querySelector(".seg button.on") || {}).dataset.tab, (nav2.querySelector(".seg button.on") || {}).dataset.tab === startTab);
    /* T3/T9: pressing the selected tab, releasing on it - no event */
    const nav3 = document.querySelector("nav.tabs"), seg3 = nav3.querySelector(".seg"), on3 = seg3.querySelector("button.on");
    const before = (nav3.querySelector(".seg button.on") || {}).dataset.tab, g3 = nav3.querySelector(".glide"); pev(seg3, "pointerdown", at(on3)); await sleep(100);
    { const L = window.__tabLens; check("标签栏 T3 按下已选中项 +100 ms：高亮类 .lift-sel 自按下即在、驱动器已在抬（R59′e / R108：+125 令牌作废）", "lift-sel · p > 0", `${g3.classList.contains("lift-sel") ? "lift-sel" : "-"} · p ${L ? L.p.toFixed(3) : "-"}`, g3.classList.contains("lift-sel") && !!L && L.p > 0); }
    await sleep(120);
    { const gr = g3.getBoundingClientRect();   // #7a: the selected item's press lifts the same box (+16 on both axes, tab-lens-motion §0 "抬起（按住已选中项）"), from +125 ms on ζ 1 / .25
      check("标签栏 T3 +220 ms：透镜抬起中（R59′d / R108：按下下一帧起 ζ1/.25 抬向 74，+125 令牌作废）", "lift-sel, 54 < h ≤ 74", `${g3.classList.contains("lift-sel") ? "lift-sel" : "-"} h ${gr.height.toFixed(1)}`, g3.classList.contains("lift-sel") && gr.height > 54 && gr.height <= 74.5); }   // 2号 R59′d
    pev(seg3, "pointerup", at(on3));
    check("标签栏 T3 按下已选中项抬手：无事件", before, (nav3.querySelector(".seg button.on") || {}).dataset.tab, (nav3.querySelector(".seg button.on") || {}).dataset.tab === before && !g3.classList.contains("lift-sel"));
    await tabRest(900);   // S1: the T3 lens has fallen back — tab-lens.js's own rest (.tl-on off), ≤ the old 900
    /* R59′c (tab-lens-motion.md §6.9 ② / R106 ②): the reselect of the selected item (here the scroll-to-top) is withheld once the finger has moved ≥ 4 pt in x from the
       initial location, even when the up is still on the same item; a lift outside window.bounds inset by 8 only clears — nothing is selected */
    { const on4 = seg3.querySelector("button.on"), tab4 = on4.dataset.tab; window.scrollTo(0, 150); await sleep(60); const y4 = window.scrollY;
      pev(seg3, "pointerdown", at(on4)); pev(seg3, "pointermove", at(on4, .5, .5, 6, 0)); await sleep(30); pev(seg3, "pointerup", at(on4, .5, .5, 6, 0)); await sleep(120);
      check("标签栏 R59′c 按住已选中项、横移 6 pt 仍在同一项、抬手：不重选（不回顶）、不选中别项、透镜回位（R106 ②：|adj.x − initial.x| ≥ 4 → shouldReselectHighlightedItemOnLift 0）", `${tab4} · scrollY ${y4} · no ScrollTop`, `${seg3.querySelector("button.on").dataset.tab} · scrollY ${window.scrollY} · ${window.ScrollTop && window.ScrollTop.state ? "ScrollTop running" : "no ScrollTop"}`, seg3.querySelector("button.on").dataset.tab === tab4 && Math.abs(window.scrollY - y4) < 1 && !(window.ScrollTop && window.ScrollTop.state) && !g3.classList.contains("lift-sel"));
      pev(seg3, "pointerdown", at(on4)); pev(seg3, "pointermove", at(on4, .5, .5, 2, 0)); await sleep(30); pev(seg3, "pointerup", at(on4, .5, .5, 2, 0)); await sleep(60);
      check("标签栏 R59′c 按住已选中项、横移 2 pt（< 4）抬手：重选 → 回顶起（对照）", "ScrollTop running", window.ScrollTop && window.ScrollTop.state ? "ScrollTop running" : "no ScrollTop", !!(window.ScrollTop && window.ScrollTop.state));
      await settle(() => !(window.ScrollTop && window.ScrollTop.state) && !nav3.classList.contains("tl-on"), 1700); window.scrollTo(0, 0);   // S1: the scroll-to-top's own end + the lens at rest
      const other4 = [...seg3.querySelectorAll("button")].find((b) => !b.classList.contains("on")), rO = other4.getBoundingClientRect();
      pev(seg3, "pointerdown", at(other4)); await sleep(30); pev(seg3, "pointermove", { x: rO.left + rO.width / 2, y: 2 }); pev(seg3, "pointerup", { x: rO.left + rO.width / 2, y: 2 }); await sleep(60);
      check("标签栏 R59′c 按住未选中项、抬手在窗口内缩 8 之外（y 2）：只清高亮，不选中", tab4, seg3.querySelector("button.on").dataset.tab, seg3.querySelector("button.on").dataset.tab === tab4 && !nav3.classList.contains("drag"));
      await tabRest(700); }
    /* BOARD R31 (page side): the labels textures for every segment are prepared at idle and the down on an unselected segment binds one (useLabels) — no
       backdrop redraw in the down's task (marks: seg:gl-uselabels present, seg:gl-redraw count unchanged across the down) */
    { const sg = q(), g = sg.__gl;
      if (g && typeof g.lens.hasLabels === "function") {
        await sleep(600);   // idle: the variants prepared
        const n = sg.querySelectorAll("button").length; const prepared = [...Array(n).keys()].every((i) => g.lens.hasLabels(i));
        const on0 = onText(), off = bs().find((b) => !b.classList.contains("on")), pressedIdx = bs().indexOf(off);
        const redraws0 = performance.getEntriesByName("seg:gl-redraw").length;
        pev(sg, "pointerdown", at(off)); const labelsAtDown = g.lens.stats.labels, used = performance.getEntriesByName("seg:gl-uselabels").length > 0; await sleep(40);
        const redraws1 = performance.getEntriesByName("seg:gl-redraw").length;
        pev(sg, "pointerup", at(off)); await segRest(1300);
        check("R31 页面侧：空闲期每段的「将选中」标签纹理已预备（hasLabels 全 true）；按下未选中段只切绑定（stats.labels = 被按段、seg:gl-uselabels 有记录），按下任务内无底图重画（seg:gl-redraw 计数不变）", `prepared · labels ${pressedIdx} · uselabels · redraw +0`, `prepared ${prepared} · labels ${labelsAtDown} · uselabels ${used} · redraw +${redraws1 - redraws0}`, prepared && labelsAtDown === pressedIdx && used && redraws1 === redraws0);
        const back = bs().find((b) => b.textContent === on0); if (back && onText() !== on0) { pev(q(), "pointerdown", at(back)); pev(q(), "pointerup", at(back)); await segRest(1300); }   // the selection restored for the rows after
      } else check("R31 页面侧【GL 不可用或包无 prepareLabels：不核】", "-", g ? "no hasLabels" : "no gl", true); }
    /* BOARD R0① (user bug 2): a shift change (早班 5 tabs ↔ 晚班 3 tabs) must not rebuild the tab bar — .plat / .glide / .seg stay the same elements, the nav's
       top and display never change, the button count goes 5 → 3 → 5 with no frame at 0, and the glide sits on the selected button every frame */
    if (typeof snap === "object" && snap && Array.isArray(snap.queues) && snap.queues.length > 1) {
      const nv0 = document.querySelector("nav.tabs"), plat0 = nv0.querySelector(":scope > .plat"), gl0 = nv0.querySelector(":scope > .glide"), sg0 = nv0.querySelector(":scope > .seg"), top0 = nv0.getBoundingClientRect().top, savedQ = curQueue, savedTab = curTab;
      const counts = [], bad = [];
      const sampleFrames = async (n) => { for (let i = 0; i < n; i++) { await new Promise(requestAnimationFrame); const nv = document.querySelector("nav.tabs"), bsN = nv.querySelectorAll(":scope > .seg > button").length, on = nv.querySelector(":scope > .seg > button.on"), g = nv.querySelector(":scope > .glide");
        counts.push(bsN); const r = nv.getBoundingClientRect();
        if (nv !== nv0 || nv.querySelector(":scope > .plat") !== plat0 || g !== gl0 || nv.querySelector(":scope > .seg") !== sg0) bad.push("rebuilt");
        if (Math.abs(r.top - top0) > 0.5) bad.push("top " + r.top.toFixed(1)); if (getComputedStyle(nv).display === "none") bad.push("display none"); if (bsN === 0) bad.push("0 buttons");
        if (on && g && !nv.classList.contains("tl-on")) { const gr = g.getBoundingClientRect(), orr = on.getBoundingClientRect(); if (Math.abs(gr.left - orr.left) > 1 || Math.abs(gr.width - orr.width) > 1) bad.push("glide off " + gr.left.toFixed(1) + "/" + orr.left.toFixed(1)); } } };   // viewport rects: during the R0③ set animation the button is translated and the glide rides it
      const names = snap.queues.map((x) => x["名"]); const other = names.find((nm) => nm !== savedQ) || names[0];
      curQueue = other; window.render(); await sampleFrames(8); curQueue = savedQ; window.render(); await sampleFrames(8); curQueue = other; window.render(); await sampleFrames(8); curQueue = savedQ; window.render(); await sampleFrames(4);
      const uniq = [...new Set(counts)];
      check("R0① 换班次三次（早→晚→早→晚→早，render）逐帧：标签栏 .plat/.glide/.seg 同一元素、nav top 不变、display 不为 none、按钮数在两个值间切换且无一帧 0、glide 每帧贴着选中按钮（≤ 1 pt）", "same nodes · top = · counts {5,3} · glide on", `${bad.length ? bad.slice(0, 4).join(" · ") : "clean"} · counts ${uniq.join("/")} · ${counts.length} frames`, bad.length === 0 && uniq.length === 2 && !uniq.includes(0) && counts.length >= 20);
      /* R0③ (tab-lens-motion.md §7, R24): on a set change the kept buttons' translateX follows ζ 1 / .3 from their FLIP delta, the removed ones fade on ζ 1 / .2 at their
         old place and leave when the .3 spring settles, the added ones fade in on ζ 1 / .3; sampled on the driver's own clock (nav.__tabAnim, A15) */
      { const nv = document.querySelector("nav.tabs"); const closed = (t, resp) => { const w = 2 * Math.PI / resp; return (1 + w * t) * Math.exp(-w * t); };
        curQueue = other; window.render(); const A = nv.__tabAnim;
        const smp = []; let removedSeen = 0; const tEnd = performance.now() + 1200;
        while (performance.now() < tEnd) { await new Promise(requestAnimationFrame); if (nv.__tabAnim === A && A && A.tNow) { const t = (A.tNow - A.t0) / 1000;   // the driver's own frame time (A15)
          for (const it of A.items) { const m = /translateX\(([-\d.]+)px\)/.exec(it.el.style.transform || ""); smp.push({ kind: "pos", t, got: m ? parseFloat(m[1]) : 0, want: it.dx * closed(t, 0.3) }); }
          for (const b of A.removed) { if (b.isConnected) { removedSeen++; smp.push({ kind: "out", t, got: parseFloat(b.style.opacity || "1"), want: closed(t, 0.2) }); } }
          for (const b of A.added) smp.push({ kind: "in", t, got: parseFloat(b.style.opacity || "1"), want: 1 - closed(t, 0.3) }); } }
        const rmsOf = (k) => { const a = smp.filter((s) => s.kind === k); return a.length ? Math.sqrt(a.reduce((acc, s) => acc + Math.pow(s.got - s.want, 2), 0) / a.length) : 0; };
        const goneAfter = A ? A.removed.every((b) => !b.isConnected) : true, hadAnim = !!A && (A.items.length + A.removed.length + A.added.length) > 0;
        check("R0③ 换班次时项增删动画（§7）：保留项位移逐帧对 ζ1/.3 闭式（rms ≤ 1 pt）、删项淡出对 ζ1/.2（rms ≤ .03）、加项淡入对 ζ1/.3（rms ≤ .03）、删项在动画结束后摘掉、驱动器存在", "anim · pos ≤ 1 · out ≤ .03 · in ≤ .03 · removed gone", `anim ${hadAnim} · ${smp.length} samples · pos ${rmsOf("pos").toFixed(2)} · out ${rmsOf("out").toFixed(3)} (${removedSeen} frames) · in ${rmsOf("in").toFixed(3)} · gone ${goneAfter}`, hadAnim && rmsOf("pos") <= 1 && rmsOf("out") <= 0.03 && rmsOf("in") <= 0.03 && goneAfter);
        curQueue = savedQ; window.render(); await sleep(1300); }
      /* 界面-串2 (09-23 18:4x): a tap on another tab while the item-set animation runs — the glide must end on the tapped tab; before, the driver
         wrote the old selection's left every frame and at its end, and the glide stayed on the old tab (view.js tabSetAnimate, mine()) */
      { const nv = document.querySelector("nav.tabs"), gl = nv.querySelector(":scope > .glide");
        curQueue = other; window.render(); const A = nv.__tabAnim; await sleep(150);
        const tgt = [...nv.querySelectorAll(":scope > .seg > button")].find((b) => !b.classList.contains("on") && !(A && A.removed.includes(b)));
        const mid = !!A && nv.__tabAnim === A; if (tgt) tgt.click(); await sleep(900);
        const on = nv.querySelector(":scope > .seg > button.on"), gr = gl.getBoundingClientRect(), orr = on ? on.getBoundingClientRect() : null;
        check("R0③′ 项增删动画途中点另一个标签：选中切过去，动画结束后透镜停在新选中项上（≤ 1 pt），不回旧项", "点时动画在跑 · 选中 = 点的 · 透镜贴新项", `${mid ? "动画在跑" : "动画没在跑"} · 选中 ${on ? on.dataset.tab : "无"}（点 ${tgt ? tgt.dataset.tab : "无"}） · 透镜 x ${gr.left.toFixed(1)} vs 项 ${orr ? orr.left.toFixed(1) : "-"} · 宽 ${gr.width.toFixed(1)} vs ${orr ? orr.width.toFixed(1) : "-"}`,
          mid && !!tgt && on === tgt && !!orr && Math.abs(gr.left - orr.left) <= 1 && Math.abs(gr.width - orr.width) <= 1);
        curQueue = savedQ; window.render(); await sleep(1300); }
      /* 界面-串2 (用户 09-23 18:27 真机 ①「切换到晚班的时候不应该显示终末地，因为终末地不在晚班里面」): in every shift each tab except 状态 must own a
         game group of its own; the 库存 entry row (data-tabfix, view.js SCHEMA loop) was emitted before the inShift test and alone kept 终末地 in 晚班 */
      { const per = [];
        for (const nm of names) { curQueue = nm; window.render(); await sleep(50);
          const nv = document.querySelector("nav.tabs"), tabs = [...nv.querySelectorAll(":scope > .seg > button")].map((b) => b.dataset.tab);
          const orphan = tabs.filter((t) => t !== "状态" && ![...document.querySelectorAll("#app section")].some((x) => x.dataset.tab === t && !x.dataset.tabfix && x.querySelector("h2")));
          per.push({ nm, tabs, orphan }); }
        curQueue = savedQ; window.render(); await sleep(1300);
        check("①′ 每个班次的标签只含本班有的游戏：除「状态」外每个标签都有本班自己的游戏分组，不靠库存入口行撑出一个标签", "无空标签", per.map((x) => `${x.nm}：${x.tabs.join("/")}${x.orphan.length ? "（空 " + x.orphan.join("/") + "）" : ""}`).join(" · "), per.every((x) => !x.orphan.length)); }
      /* 界面-串2 (用户 09-23 18:27 真机 ②「切换到晚班再切早班的时候会出现晚班的底图重叠」): the tab lens's backdrop (lens-webgl scratch canvases, the page
         layer = body colour + the platter capsule) was painted on tabs-changed, the first frame of the item-set animation, from a platter still at the old
         width — on 模拟器 B the live page canvas had its capsule at css 45..370 of a 416 bar (evidence 界面-串2-②-底图画布.json), and every set change left
         one more scratch pair in the body. After 早→晚→早 and the settle: one scratch box per lens, and the tab page canvas's capsule spans the whole bar */
      { const nv = document.querySelector("nav.tabs"), boxes0 = [...document.body.children].filter((e) => e.style && e.style.left === "-100000px").length;
        curQueue = other; window.render(); await sleep(1500); curQueue = savedQ; window.render(); await sleep(1800);
        const dpr = window.devicePixelRatio || 1, navW = nv.offsetWidth, navH = nv.offsetHeight, boxes = [...document.body.children].filter((e) => e.style && e.style.left === "-100000px");
        const pg = boxes.map((b) => b.querySelector("canvas")).filter((c) => c && c.width > navW * dpr && Math.abs(c.width / dpr - navW - (c.height / dpr - navH)) < 1).pop();
        if (!pg) check("②′ 换班次后标签透镜底图【标签透镜 GL 不可用：不核】", "-", "no tab canvas", true);
        else { const m = (pg.width / dpr - navW) / 2, d = pg.getContext("2d").getImageData(0, Math.round(pg.height / 2), pg.width, 1).data, px = (i) => d.slice(i * 4, i * 4 + 4).join(",");
          let a = -1, b = -1; for (let i = 0; i < pg.width; i++) if (px(i) !== px(0)) { if (a < 0) a = i; b = i; }
          const l = a / dpr - m, r = (b + 1) / dpr - m;
          check("②′ 换班次（早→晚→早）动画落定后：标签透镜底图里的平台胶囊横跨整条标签栏（左 0、右 = 栏宽，≤ 1 pt），离屏底图画布不随换班次累积", `0..${navW} · 画布盒 ${boxes0}`, `${l.toFixed(1)}..${r.toFixed(1)} · 画布盒 ${boxes0} → ${boxes.length}`, Math.abs(l) <= 1 && Math.abs(r - navW) <= 1 && boxes.length <= boxes0); } }
      curTab = savedTab; window.render(); await sleep(100);
    }
  }
  }, { layer: "timing" });
})();
