/* 验收：页面地址加 ?accept 时加载，在这台设备的浏览器里量 DOM，逐项和
   docs/HIG-CHECKLIST.md 的数字比。只认 iOS Safari 的数（桌面 Chromium 没有安全区）。
   结果存进 localStorage 的 ark-accept，scripts/mac/phone-accept.sh 从模拟器的存储里
   读出来；不加 &quiet 时左上角盖一张表。
   方法照 ~/Money/transit/ui/accept.js（另一个会话 2026-09-15 定型）。
   2026-09-18：期望值改成 web/tokens.css 的原值（每项后面写变量名；出处在 tokens.css
   该变量上一行的注释：UIProbe 探针 / AX json / Kit NUMBERS）。期望值故意写死在这里，
   不从 tokens.css 读——两边同源的话 tokens 写错也会「通过」。颜色比对解析 rgb，不比字串。 */
(function () {
  const q = new URLSearchParams(location.search);
  if (!q.has("accept")) return;
  const rows = [];
  const near = (a, b, tol = 0.6) => Math.abs(a - b) <= tol;
  const cs = (el, pseudo) => el ? getComputedStyle(el, pseudo || null) : null;
  const px = (v) => parseFloat(v) || 0;
  function check(item, expect, got, ok) {
    rows.push({ item, expect: String(expect), got: got === undefined || got === null ? "缺" : String(typeof got === "number" ? Math.round(got * 100) / 100 : got), ok: !!ok });
  }
  function num(item, expect, got, tol) { check(item, expect, got, typeof got === "number" && near(got, expect, tol)); }
  /* Colours: computed styles come back as rgb(r, g, b) / rgba(r, g, b, a); compare the
     numbers (tolerance 3 per channel, .02 alpha), never the string. */
  const rgb = (c) => { const m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/.exec(c || ""); return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null; };
  const same = (c, want, tol = 3) => { const a = rgb(c); return !!a && a.slice(0, 3).every((v, i) => Math.abs(v - want[i]) <= tol) && Math.abs(a[3] - (want[3] === undefined ? 1 : want[3])) <= 0.02; };
  const fmt = (want) => want.length > 3 && want[3] !== 1 ? `rgba(${want[0]},${want[1]},${want[2]},${want[3]})` : `rgb(${want[0]},${want[1]},${want[2]})`;
  function col(item, want, got) { check(item, fmt(want), got, same(got, want)); }
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

    const root = px(cs(document.documentElement).fontSize);
    num("根字号 17（--ios-body-size）", 17, root, 0.01);
    num("正文行框 20.33（--ios-body-lh）", 20.33, px(cs(document.body).lineHeight), 0.05);
    const ff = cs(document.body).fontFamily;
    check("字体栈含 -apple-system 或 PingFang（--ios-font）", "是", /-apple-system|PingFang/i.test(ff) ? "是" : ff.slice(0, 40), /-apple-system|PingFang/i.test(ff));
    col("tint（--ios-tint）", T.tint, varColor("--accent", probe));
    col("蓝字行 link（--ios-link）", T.link, varColor("--link", probe));
    col("页底色（--ios-grouped-bg）", T.bg, cs(document.body).backgroundColor);

    const main = document.querySelector("main");
    if (main) num("卡片距屏边 20（--ios-card-inset）", 20, px(cs(main).paddingLeft));
    const group = document.querySelector("section .group:not(.tiles):not(.nums):not(.devcard):not(.notice)");
    if (group) {
      num("卡片圆角 26（--ios-card-radius）", 26, px(cs(group).borderTopLeftRadius));
      col("卡片底色（--ios-card-bg）", T.card, cs(group).backgroundColor);
      const r = group.getBoundingClientRect();
      num("卡片左边 = 20", 20, r.left);
      num("卡片宽 = 视口 − 40", innerWidth - 40, r.width);
    }
    const row = document.querySelector(".row:has(> .sw), .row:has(> select)") || document.querySelector(".row");
    if (row) {
      num("行高 ≥ 53.33（--ios-row-h）", 53.33, Math.min(row.getBoundingClientRect().height, 53.33));
      num("行左内边距 20（--ios-row-text-x）", 20, px(cs(row).paddingLeft));
      const a = cs(row, "::after");
      const sy = /matrix\([^,]+,[^,]+,[^,]+,\s*([\d.]+)/.exec(a.transform);
      num("分隔线 1.0 pt（--ios-separator-h；探针 1.0，不是 1/3）", 1, px(a.height) * (sy ? parseFloat(sy[1]) : 1), 0.02);
      col("分隔线色（--ios-separator）", T.sep, a.backgroundColor);
      num("分隔线左缩进 20（--ios-separator-inset-l）", 20, px(a.left));
      num("分隔线右缩进 20（--ios-separator-inset-r）", 20, px(a.right));
    }
    const sw = document.querySelector(".sw");
    if (sw) {
      const r = sw.getBoundingClientRect();
      num("开关宽 63（--ios-switch-w）", 63, r.width); num("开关高 28（--ios-switch-h）", 28, r.height);
      num("开关圆角 14（--ios-switch-radius）", 14, px(cs(sw.querySelector("span")).borderTopLeftRadius));
      const knob = cs(sw.querySelector("span"), "::after");
      num("开关圆钮宽 37（--ios-switch-knob-w）", 37, px(knob.width)); num("开关圆钮高 24（--ios-switch-knob-h）", 24, px(knob.height));
      const rr = sw.closest(".row");
      if (rr) num("开关距卡片右边 18（--ios-switch-inset）", 18, rr.getBoundingClientRect().right - r.right);
    }
    /* A plain header: not the first section (10 under the large title, 待 tokens) and
       not one right after a footer (the footer already carries the group gap). */
    const h2 = [...document.querySelectorAll("section h2")].find((h) => {
      const sec = h.parentElement, prev = sec.previousElementSibling;
      if (!prev || prev.tagName !== "SECTION") return false;
      return !(prev.lastElementChild && prev.lastElementChild.classList.contains("foot"));
    });
    if (h2) {
      const c = cs(h2);
      num("段头字号 17（--ios-body-size）", 17, px(c.fontSize), 0.05); check("段头字重 600（--ios-headline-weight）", 600, c.fontWeight, String(c.fontWeight) === "600");
      num("段头上边距 18.67（--ios-header-text-top）", 18.67, px(c.paddingTop), 0.05);
      num("段头下边距 6.33（45.33 − 18.67 − 20.33：--ios-header-h）", 6.33, px(c.paddingBottom), 0.05);
      num("段头文字内缩 20（--ios-row-text-x）", 20, px(c.paddingLeft));
      col("段头色 secondaryLabel（--ios-secondary-label）", T.dim, c.color);
    }
    /* The footer under the number tiles sits 8 below them (tiles have no card edge); measure a plain one. */
    const foot = [...document.querySelectorAll("section .foot")].find((f) => !(f.previousElementSibling && f.previousElementSibling.classList.contains("nums")));
    if (foot) {
      const c = cs(foot);
      num("段尾字号 13（--ios-footnote-size）", 13, px(c.fontSize), 0.05); num("段尾行框 15.67（--ios-footnote-lh）", 15.67, px(c.lineHeight), 0.05);
      num("段尾上边距 7.67（--ios-footer-text-top）", 7.67, px(c.paddingTop), 0.05);
      num("段尾下边距 24.66（30.33 − 7.67 − 15.67 + 17.67：--ios-footer-h + --ios-group-gap）", 24.66, px(c.paddingBottom), 0.05);
    }
    const tile = document.querySelector(".tile");
    if (tile) {
      const r = tile.getBoundingClientRect();
      num("动作磁贴高 ≥ 80（待 tokens：提醒事项磁贴）", 80, Math.min(r.height, 80)); num("动作磁贴圆角 16（待 tokens）", 16, px(cs(tile).borderTopLeftRadius));
      num("磁贴间距 8（待 tokens）", 8, px(cs(tile.parentElement).columnGap));
      const ico = tile.querySelector(".tico"); if (ico) num("磁贴图标圆 28（待 tokens）", 28, ico.getBoundingClientRect().width);
      num("磁贴标题 15（--ios-sub-size）", 15, px(cs(tile.querySelector(".ttitle") || tile).fontSize), 0.05);
    }
    const numT = document.querySelector(".num");
    if (numT) {
      const r = numT.getBoundingClientRect();
      num("数字磁贴高 ≥ 80.33（待 tokens）", 80.33, Math.min(r.height, 80.33)); num("数字磁贴圆角 16（待 tokens）", 16, px(cs(numT).borderTopLeftRadius));
      const ico = numT.querySelector(".nico"); if (ico) num("数字磁贴图标圆 32（待 tokens）", 32, ico.getBoundingClientRect().width);
      const big = numT.querySelector(".big"); if (big) num("数字磁贴大数字号 24（待 tokens）", 24, px(cs(big).fontSize), 0.1);
      const lab = numT.querySelector(".lab"); if (lab) num("数字磁贴名字字号 15（--ios-sub-size）", 15, px(cs(lab).fontSize), 0.1);
    }
    /* 2026-09-18: the device card is a Settings value row (46 Apple 账户页), no icon. */
    const dev = document.querySelector(".devcard");
    if (dev) { num("设备行高 ≥ 53.33（--ios-row-h）", 53.33, Math.min(dev.getBoundingClientRect().height, 53.33)); const s2 = dev.querySelector(".dsub"); if (s2) col("设备行右灰值 secondaryLabel（--ios-secondary-label）", T.dim, cs(s2).color); }
    /* Segmented control (状态 tab, 早班/晚班; 34 屏幕时间) */
    const segc = document.querySelector(".segctl");
    if (segc) {
      const r = segc.getBoundingClientRect();
      num("分段控件高 32（--ios-segment-h）", 32, r.height); num("分段控件圆角 16（--ios-segment-radius）", 16, px(cs(segc).borderTopLeftRadius));
      num("分段控件宽 = 卡片宽", innerWidth - 40, r.width);
      const lens = segc.querySelector(".lens"), b = segc.querySelector("button");
      if (lens) { num("分段透镜高 28（--ios-segment-lens-h）", 28, lens.getBoundingClientRect().height); num("分段透镜圆角 14（--ios-segment-lens-radius）", 14, px(cs(lens).borderTopLeftRadius)); num("分段透镜内缩 2（--ios-segment-lens-pad）", 2, lens.getBoundingClientRect().top - r.top); }
      if (b) { num("分段文字 13（--ios-segment-label-size）", 13, px(cs(b).fontSize), 0.05); check("分段选中字重 500（--ios-medium-weight）", 500, cs(segc.querySelector("button.on") || b).fontWeight, String(cs(segc.querySelector("button.on") || b).fontWeight) === "500"); }
    }
    /* The confirm alert (closed, but its computed geometry is there) */
    const alert = document.querySelector("dialog#alert");
    if (alert) {
      num("弹窗宽 320（--ios-alert-w）", 320, px(cs(alert).width)); num("弹窗圆角 34（--ios-alert-radius）", 34, px(cs(alert).borderTopLeftRadius));
      const ab = alert.querySelector(".acts button"); if (ab) { num("弹窗按钮高 48（--ios-alert-button-h）", 48, px(cs(ab).height)); num("弹窗按钮圆角 24（--ios-alert-button-radius）", 24, px(cs(ab).borderTopLeftRadius)); }
    }
    /* Tab bar: hidden when the snapshot has a single tab (nav.hidden = present.size < 2);
       measure a synthetic one then, so the run does not depend on the data. */
    let seg = document.querySelector("nav.tabs:not([hidden]) .seg"), fakeNav = null;
    if (!seg) {
      fakeNav = document.createElement("nav"); fakeNav.className = "tabs"; fakeNav.style.visibility = "hidden";
      fakeNav.innerHTML = `<div class="seg"><i class="glide"></i><button type="button" class="on"><span class="ico"><i class="sf"></i></span>状态</button><button type="button"><span class="ico"><i class="sf"></i></span>手机</button></div>`;
      document.body.appendChild(fakeNav); seg = fakeNav.querySelector(".seg");
    }
    if (seg) {
      const r = seg.getBoundingClientRect();
      num("标签栏胶囊高 62（Kit；探针 UITabBar 83 含安全区，待 tokens）", 62, r.height);
      if (!fakeNav) {
        const gap = innerHeight - r.bottom;
        const standalone = matchMedia("(display-mode: standalone)").matches;
        if (standalone) num("标签栏底边距屏底 22（主屏幕 app；待 tokens）", 22, gap);
        else check("标签栏在 Safari 地址栏之上", "> 0", Math.round(gap), gap > 0);
      }
      const b = seg.querySelector("button"); if (b) { const w = b.getBoundingClientRect().width; num("标签按钮高 54（--ios-tab-lens-h）", 54, b.getBoundingClientRect().height); check("标签按钮宽 ≥ 72（Kit，待 tokens）", "≥ 72", w, w >= 71.5); num("标签文字 10（--ios-tab-label-size）", 10, px(cs(b).fontSize), 0.05); num("标签按钮圆角 27（--ios-tab-lens-radius）", 27, px(cs(b).borderTopLeftRadius)); }
      const ico = seg.querySelector(".ico"); if (ico) num("标签符号框 28（Kit，待 tokens）", 28, ico.getBoundingClientRect().height);
    }
    if (fakeNav) fakeNav.remove();
    const top = document.querySelector(".topbar");
    if (top) {
      const pr = document.createElement("div"); pr.style.cssText = "position:fixed;top:0;left:0;width:1px;padding-top:env(safe-area-inset-top);visibility:hidden";
      document.body.appendChild(pr); const sat = px(cs(pr).paddingTop); pr.remove();
      num("顶栏高 = 安全区 + 44（老量法；AX-45 NavigationBar 54 = --ios-nav-h 待换）", 44, top.getBoundingClientRect().height - sat);
    }
    const h1 = document.querySelector("header h1");
    if (h1) { num("大标题字号 34（--ios-large-title-size）", 34, px(cs(h1).fontSize), 0.1); num("大标题行框 40.57（--ios-large-title-lh）", 40.57, px(cs(h1).lineHeight), 0.05); check("大标题字重 700（NUMBERS 56）", 700, cs(h1).fontWeight, String(cs(h1).fontWeight) === "700"); }
    /* State colours, probed on synthetic controls so they are checked whatever the
       data happens to show: a switch on/off, the danger tile title, the selected
       tab, the edit bar's two capsules. 2026-09-15 the green track rule vanished
       and nobody noticed until the phone showed grey everywhere. */
    const lab = document.createElement("div"); lab.style.cssText = "position:fixed;left:-9999px;top:0";
    lab.innerHTML = `<label class="sw"><input type="checkbox" checked><span></span></label><label class="sw"><input type="checkbox"><span></span></label>` +
      `<button class="tile danger"><span class="ttitle">x</span></button><nav class="tabs"><div class="seg"><button class="on">x</button></div></nav>` +
      `<div class="topbar editing"><button class="navbtn" id="_d">x</button><button class="navbtn" id="_s">x</button></div>` +
      `<div class="group"><div class="row"><label>x</label><span class="sent">已寄出 10:00</span></div><div class="acts"><button>开始刷</button></div></div>`;
    document.body.appendChild(lab);
    const [on, off] = lab.querySelectorAll(".sw span");
    col("开关开 = 系统绿（--ios-switch-on）", T.green, cs(on).backgroundColor);
    col("开关关 = 灰（--ios-switch-off）", T.swOff, cs(off).backgroundColor);
    const kx = /matrix\([^)]*,\s*([-\d.]+),\s*[-\d.]+\)$/.exec(cs(on, "::after").transform);
    num("开关开：圆钮位移 22（--ios-switch-travel = 63 − 37 − 2×2）", 22, kx ? parseFloat(kx[1]) : NaN);
    /* Finger down: the kit's Pressed knob is 58×38 (scale 1.526 × 1.583 of 38×24). */
    const held = lab.querySelectorAll(".sw")[1]; held.classList.add("live", "hold");   // as view.js sets them: no transition in the way
    const hm = /matrix\(([-\d.]+),\s*[-\d.]+,\s*[-\d.]+,\s*([-\d.]+)/.exec(cs(held.querySelector("span"), "::after").transform);
    num("按住：圆钮放大成 58 宽（Kit Toggle Pressed）", 1.526, hm ? parseFloat(hm[1]) : NaN, 0.02); num("按住：圆钮放大成 38 高（Kit Toggle Pressed）", 1.583, hm ? parseFloat(hm[2]) : NaN, 0.02);
    check("按住：圆钮变半透明玻璃", "非纯白", cs(held.querySelector("span"), "::after").backgroundImage.slice(0, 15), /gradient/.test(cs(held.querySelector("span"), "::after").backgroundImage));
    held.classList.remove("hold");
    /* Motion tokens (spec-extract.md ⑤): knob 0.35 s on the probed spring, track 0.2 s. */
    const kt = cs(on, "::after");
    check("开关圆钮动效 0.35 s（--ios-motion-switch-knob-duration）", "0.35s", kt.transitionDuration.split(",")[0].trim(), /^0\.35s/.test(kt.transitionDuration));
    check("开关圆钮曲线 linear()（--ios-motion-switch-knob-easing）", "linear(…)", kt.transitionTimingFunction.slice(0, 12), /^linear\(/.test(kt.transitionTimingFunction));
    check("开关轨道交叉淡 0.2 s（--ios-motion-switch-track-duration）", "0.2s", cs(on).transitionDuration, /^0\.2s/.test(cs(on).transitionDuration));
    /* A tap through the page's own pointer handling, followed by the click the
       browser fires anyway: the switch must flip exactly once and `change` fire
       once (12:0x: it flipped twice and stayed put). */
    const tapSw = lab.querySelectorAll(".sw")[1], tapIn = tapSw.querySelector("input"); let changes = 0;
    tapIn.addEventListener("change", () => changes++);
    const was = tapIn.checked;
    const pe = (type, target) => target.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: 7, clientX: 10, clientY: 10, isPrimary: true }));
    pe("pointerdown", tapIn); pe("pointerup", tapSw); tapIn.click();
    check("轻点一下：开关翻转一次", !was, tapIn.checked, tapIn.checked === !was);
    check("轻点一下：change 只发一次", 1, changes, changes === 1);
    col("停止一切标题 = 红（--ios-red）", T.red, cs(lab.querySelector(".ttitle")).color);
    col("选中的标签 = tint（--ios-tint）", T.tint, cs(lab.querySelector("nav.tabs button.on")).color);
    col("蓝字行 = link（--ios-link）", T.link, cs(lab.querySelector(".acts button")).color);
    const cap = lab.querySelector(".sent");
    num("三态小字 11（--ios-caption2-size）", 11, px(cs(cap).fontSize), 0.05); num("三态小字行框 13.13（--ios-caption2-lh）", 13.13, px(cs(cap).lineHeight), 0.05);
    col("三态小字色 secondaryLabel（--ios-secondary-label）", T.dim, cs(cap).color);
    lab.querySelector("#_d").id = "discard"; lab.querySelector("#_s").id = "save";
    check("编辑栏 ✓ = tint 底白符号（--ios-tint）", fmt(T.tint), cs(lab.querySelector("#save")).backgroundColor, same(cs(lab.querySelector("#save")).backgroundColor, T.tint) && same(cs(lab.querySelector("#save")).color, [255, 255, 255]));
    num("编辑栏圆钮 44（--ios-nav-button）", 44, lab.querySelector("#save").getBoundingClientRect().height); num("编辑栏圆钮宽 44（--ios-nav-button）", 44, lab.querySelector("#save").getBoundingClientRect().width);
    num("编辑栏圆钮距边 20（--ios-nav-side）", 20, px(cs(lab.querySelector("#discard")).left));
    check("编辑栏圆钮是圆的", "50%", cs(lab.querySelector("#save")).borderRadius, cs(lab.querySelector("#save")).borderRadius === "50%" || px(cs(lab.querySelector("#save")).borderRadius) >= 22);
    lab.remove(); probe.remove();
    const meta = document.querySelector('meta[name="theme-color"]');
    check("theme-color 存在", "是", meta ? "是" : "缺", !!meta);

    const fails = rows.filter((r) => !r.ok).length;
    const out = { at: new Date().toISOString(), href: location.href, viewport: `${innerWidth}×${innerHeight}`,
                  standalone: matchMedia("(display-mode: standalone)").matches,
                  dark, total: rows.length, fails, rows };
    try { localStorage.setItem("ark-accept", JSON.stringify(out)); } catch {}
    document.title = `验收 ${rows.length - fails}/${rows.length}`;
    if (!q.has("quiet")) {
      const box = document.createElement("pre");
      box.style.cssText = "position:fixed;left:8px;top:60px;z-index:99;max-height:70vh;overflow:auto;background:rgba(0,0,0,.82);color:#fff;font:11px/1.35 -apple-system,monospace;padding:8px;border-radius:8px;margin:0;white-space:pre";
      box.textContent = `${out.viewport}${out.standalone ? " 主屏幕" : " Safari"}${out.dark ? " 深色" : ""}  ${rows.length - fails}/${rows.length}\n` +
        rows.map((r) => `${r.ok ? "✓" : "✗"} ${r.item}  ${r.got}${r.ok ? "" : "（要 " + r.expect + "）"}`).join("\n");
      document.body.appendChild(box);
    }
  }
  /* The page renders after its first snapshot and the number tiles after the game
     APIs answer: measure once the tiles exist (or after 8 s). */
  let tries = 0;
  const t = setInterval(() => { tries++; if (document.querySelector(".num") || tries > 80) { clearInterval(t); run(); } }, 100);
})();
