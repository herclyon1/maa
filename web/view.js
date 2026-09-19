/* 界面与状态（app.js 拆分后剩下的部分，原样）：全局状态、外观、渲染、事件、保存、启动；末尾 boot()。 */
/* 游戏机遥控。
   一根管道：ntfy 上一个信箱。手机写指令，机器写状态。零轮询——
   机器那头挂长连接，这头只在你按刷新时发一条 ping。
   信箱名和 PIN 只存在这台手机里，不在这份代码里。 */
const NTFY = "https://ntfy.sh";
const LS = "ark-remote-cfg";
const $ = (s) => document.querySelector(s);

let cfg = null;      // {topic, pin}
/* 当前在看哪一趟班。它管两件事：下面两个按钮作用在哪趟，以及配置区
   只显示这趟要跑的游戏。记在这台手机上，换页不丢。 */
let curQueue = localStorage.getItem("ark-remote-cfg-queue") || "";
let snap = null;     // 机器最近一次上报的状态
let edits = {};      // 改了但还没保存的：key -> {label, script, path, from, to}


/* ---------- 外观 ---------- */
/* Appearance follows the system (HIG「Settings」: respect systemwide settings and
   do not offer redundant versions of them). The page carries no theme of its own;
   only the browser chrome colour is kept in step with light/dark. */
function applyTheme() {
  delete document.documentElement.dataset.theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = matchMedia("(prefers-color-scheme: dark)").matches ? "#000000" : "#f2f2f7";
}


/* ---------- 界面 ---------- */
/* 确认弹窗（UIAlertController 的形，数字见 index.html dialog 段）：标题 / 说明 / 取消 + 主钮。resolve(true) = 按了主钮。 */
function ask(title, msg, okLabel = "好", danger = false) {
  const d = $("#alert");
  if (!d || !d.showModal) return Promise.resolve(confirm(`${title}\n${msg}`));
  if (d.open) return Promise.resolve(false);   // one alert at a time (UIAlertController presents one); a second ask while it is open is dropped — 2026-09-19 数据实拍的双层弹窗
  $("#alert-t").textContent = title; $("#alert-m").textContent = msg;
  const ok = $("#alert-ok"); ok.textContent = okLabel; ok.className = danger ? "danger" : "primary";
  return new Promise((res) => {
    const done = (v) => {
      ok.onclick = null; $("#alert-cancel").onclick = null;
      /* 消失只淡出（--ios-motion-alert-*），淡完再 close()；resolve 不等动效 */
      d.classList.add("closing");
      const ms = parseFloat(getComputedStyle(d).getPropertyValue("--ios-motion-alert-duration")) * 1000 || 0;
      setTimeout(() => { d.classList.remove("closing"); d.close(); }, ms);
      res(v);
    };
    ok.onclick = () => done(true); $("#alert-cancel").onclick = () => done(false);
    d.oncancel = (e) => { e.preventDefault(); done(false); };
    /* Behaviour 1: `.settled` marks the end of the appear animation (index.html: Chrome runs the glass flat until then). The two frame stamps
       after showModal go to the ?diag=1 line, so the first-frame delay can be read off a phone. */
    d.classList.remove("settled"); d.addEventListener("animationend", () => d.classList.add("settled"), { once: true });
    const t0 = performance.now(); d.showModal();
    d.scrollTop = 0;   // 验收 09-19 18:0x: the glass .pane (inset −60) made the dialog scrollable by 60 px and the focus showModal() moves could scroll the title out; overflow:clip in index.html, this is the belt
    requestAnimationFrame((f1) => requestAnimationFrame((f2) => { window.ALERT_T = { open: t0, f1, f2 }; d.scrollTop = 0; }));
  });
}
/* "8:30" / "08:30" → "08:30"; anything else (08:930, 25:00, 08:75, letters) → null */
function timeHHMM(s) { const m = /^\s*(\d{1,2}):(\d{2})\s*$/.exec(String(s || "")); if (!m || +m[1] > 23 || +m[2] > 59) return null; return `${m[1].padStart(2, "0")}:${m[2]}`; }
function toast(t, ms = 2600) {
  const el = $("#toast"); el.textContent = t; el.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => el.classList.remove("show"), ms);
}

function ago(ts) {
  const s = Math.max(0, now() - ts);
  if (s < 60) return `${s} 秒前`;
  if (s < 3600) return `${Math.floor(s/60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s/3600)} 小时 ${Math.floor(s%3600/60)} 分前`;
  return `${Math.floor(s/86400)} 天前`;
}

function setStatus(text, state) {
  $("#status").textContent = text;
  $("#dot").className = "dot" + (state ? " " + state : "");
  /* The status card on the 状态 tab (the header's copy is hidden): the first 「 · 」 splits the line — the head joins the name
     (「游戏机 · 开机中」), the rest is the second line (「实时 · 配置 1 分钟前」); a line without 「 · 」 goes whole into the second line. */
  const s2 = $("#status2"), d2 = $("#dot2"), n2 = $("#dname2"), side = $("#side2");
  const i = text.indexOf(" · "), head = i > 0 ? text.slice(0, i) : "", rest = i > 0 ? text.slice(i + 3) : text;
  if (n2) n2.textContent = `游戏机${DEMO ? "（演示）" : ""}${head ? " · " + head : ""}`;
  if (s2) s2.textContent = rest;
  if (d2) d2.className = "dot" + (state ? " " + state : "");
  if (side) side.textContent = state === "on" ? "在线" : state === "off" ? "关机" : "";
}

function fmt(v) {
  if (v === true) return "开"; if (v === false) return "关";
  if (v === null || v === undefined) return "（空）";
  return String(v);
}

function setupScreen() {
  /* Same shape as every other card: two rows with a text field, the action as a
     blue text row, the explanation as the group footer. iOS capitalises the first
     letter of a text field by default, which silently breaks a case-sensitive
     topic (seen on the simulator 2026-09-14) - so autocapitalize/autocorrect off. */
  $("#app").innerHTML = `
    <section><h2>第一次使用</h2>
      <div class="row"><label>信箱名</label>
        <input id="s-topic" type="text" placeholder="ark-…" autocapitalize="none" autocorrect="off" spellcheck="false" autocomplete="off"></div>
      <div class="row"><label>PIN</label>
        <input id="s-pin" type="text" inputmode="numeric" placeholder="4 位数字" autocomplete="off"></div>
      <div class="acts"><button class="wide" id="s-go">开始使用</button></div>
      <div class="foot"><p>填一次就好，之后不再问。这两样只存在这台手机里。</p></div>
    </section>`;
  layoutTabs();
  $("#s-go").onclick = () => {
    const topic = $("#s-topic").value.trim().toLowerCase(), pin = $("#s-pin").value.trim();
    if (!topic || !pin) return toast("两样都要填");
    cfg = { topic, pin };
    localStorage.setItem(LS, JSON.stringify(cfg));
    boot();
  };
}

let lastGoodConfig = null;
let lastGoodMaster = null;
try { lastGoodMaster = JSON.parse(localStorage.getItem(LS + "-master") || "null"); } catch {}
try { lastGoodConfig = JSON.parse(localStorage.getItem(LS + "-config") || "null"); } catch {}

/* 字段的显示名：一律用**脚本自己**的译名（MaaEnd 的语言包、OK-WW 的 ok.po、
   AUTO-MAS 的中文标注），SCHEMA 里写的那个只是兜底。渲染和确认框都用这一个，
   免得列表里是中文、确认框里蹦出 `@enabled` 这种键名。
   2026-09-03 发现原来「模拟领域第几个／凝素领域第几个」是我编的，
   而且和官方译名正好编反了——所以译名一律去问脚本，不自己写。 */
function labelOf(g, f) {
  const M = ((snap && snap.master) || {})[g.game] || {};
  return (g.src === "master"
      ? (M.labels || {})[f.path]
      : ((((snap && snap.options) || {})._labels || {})[`${g.script}|${f.path}`]))
    || f.label || f.key || f.path.split("/").pop();
}

// 「现在在跑什么」每条状态包都带着，页面以前一个字不显示——而它正是
// 「按下去会不会被丢掉」和「这趟跑到哪个游戏了」的答案。
// 刷 4C 声骸那一块。正在刷的时候只给「提前收工」，不给再开一趟——中继那边也会拒。
function echoFarmBlock(relay) {
  const cur = (relay || {})["刷声骸"] || {};
  if (cur["到"]) {
    return `<div class="hint">🥚 正在刷「${cur["名字"] || "?"}」，刷到 ${String(cur["到"]).slice(11)} 为止（${cur["从"] ? String(cur["从"]).slice(11) + " 开始" : ""}）</div>
      <div class="row"><label>改成刷到几点
        <span class="hint">提前或延后都行，填 21:00 这种。已经过了的时刻＝立刻收工</span></label>
        <input type="text" class="short" id="efnew" value="${String(cur["到"]).slice(11)}" inputmode="numeric" data-time></div>
      <div class="acts"><button class="wide" id="echofarmuntil">改收工时刻</button></div>
      <div class="acts"><button class="wide" id="echofarmstop">提前收工（关掉脚本和游戏）</button></div>`;
  }
  const opts = BOSSES.map((b) => `<option value="${b[0]}">${b[0]}. ${b[1]}</option>`).join("");
  return `<div class="row"><label>刷 4C 声骸 · 打哪个
      <span class="hint">序号＝「讨伐强敌」列表从上往下数。刷的期间不花波片、不领周本奖励</span></label>
      <select id="efboss">${opts}</select></div>
    <div class="row"><label>刷到几点（机器时间）
      <span class="hint">填 08:30 这种，已过就算明天。到点自动收工、配置还原</span></label>
      <input type="text" class="short" id="efuntil" value="08:30" inputmode="numeric" data-time></div>
    <div class="acts"><button class="wide" id="echofarm">开始刷</button></div>`;
}

function runLine() {
  const run = (snap && snap.run) || {};
  const busy = run["在跑的"] || [];
  if (!snap) return "";
  return busy.length
    ? `<div class="hint">🎮 现在在跑：${busy.join("、")}（这时改设置会被推迟到跑完）</div>`
    : `<div class="hint">现在没有脚本在跑</div>`;
}

/* ---------- 状态页的三种块（docs/PHONE-NATIVE-REFERENCES.md） ----------
   设备卡：查找 › 设备 的那张卡的结构（名字、一行状态、右侧一个词）。
   提示卡：健康 › 摘要 的提示卡（小灰标题 / 粗体一句 / 灰说明 / 淡色胶囊按钮），
           量自 iOS 26.5 模拟器：内距 16、标题 13、正文 17 粗 + 15 灰、按钮高 30。
   磁贴：提醒事项首页的 2×2 磁贴几何（195.67×80.33、间距 8、圆角 16，量自模拟器），
         长相按查找的「播放声音 / 路线」磁贴：左上彩色圆图标、名字、下面一行状态。 */
const SYM = {"chevron.right": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADQAAABICAYAAAC5mNZRAAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAAEgAAAAAQAAASAAAAABAAKgAgAEAAAAAQAAADSgAwAEAAAAAQAAAEgAAAAAA2ZLFgAAAAlwSFlzAAAsSwAALEsBpT2WqQAAAzlJREFUaAXtml1oTnEcx2dMGLI0smhroRUpygXlwoXiQpFCLrhx50paudqNNiVFSaK0hPKStLxcUFqKsgu1vEZsyPtbk8i7z/di9TyndnZ+W+p7dH71ac95zu+s7+f/nJ3nnP9/FRVFFSNQjEAxAv/zCIwYptxsjl8HM+AlnIS7kMtqJvVP+FPCL15vg9zVKhKXiiRft+TN6PogQhJszZPUlwxCktqVF6m3GYUktScPUkcCQpLaD8O9ov7TcWngt38Ahc3KIXqtpRYTsC8gJPF2qATbWkiy6Cd1lGNG2hoRbD68g6ynnvpOwCiwrbkkew0RqTP0V9kaEawJnkNEqoP+0WBbM0n2FCJSF+kfY2tEsAbogYjUJfrHgm3pceIhRKSu0F9ta0SwaXAPIlJX6Z8AtjWFZLcgIqU7+Ym2RgSbDDchItVF/ySwrRqSKWRESoOgwbAtnUbXICLVTX+trRHBxkMnRKRu0z8VbGscyS5DROo+/XW2RgTTncEFiEjpe2062Jbu4c5CROox/fW2RgTTI8QpiEg9ob8RbEsPe8cgIvWMfmupSgIeDkrpQmF9l64JlANBqS3029deEmY9/fTUW1b6qN3qHIE06Z+l9J1WVm5Cy0l3HrLOCt0pszHbWEmeb5D1dFOvHvktaw2pvkNWmd/0brI0IdR6+AERmc2uMhsJllwFTBPTxcL2k9EoK2CaQOk+iW8Ay9IXov4OSgOnvdYpudbShFBbAyKS1MViNVjWdlKlfRLJfbo063JuWS2kSgZO2/5K/wpLE0K1BWW0KL3MVWZ3UOYz/UsdZfQ4sC8o84n+Ja4yB4MyffQvcpTRHXx7UOYj/VqvtSvd9h+HtKtXct97+hfYmRCoCk5DMnDa9hv654FdaY6tA9LCJ/e9on+OnQmBNPOiddJk4LTtF/Q3gV0NZZ5ac2qz7EwINJSVhF6Oa3SU0QWgE9JOq+S+R/TXg2U1kyoZOG37Af3WKweahk0TKN2nlfA6sC49p5SGHui1/epb/yj3ZBDqpqe2/wD3n62DCNmvYCcHuJo3ugaQusH7NckD8rCtL9UdoMuxJjJ6YSdY/xMS+YoqRqAYgWIEcjwCfwH2GatJXyGJtQAAAABJRU5ErkJggg==", "chevron.left": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADQAAABICAYAAAC5mNZRAAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAAEgAAAAAQAAASAAAAABAAKgAgAEAAAAAQAAADSgAwAEAAAAAQAAAEgAAAAAA2ZLFgAAAAlwSFlzAAAsSwAALEsBpT2WqQAAA2tJREFUaAXtmk2IT1EYxsc3IRlJKUSUhSIjoSg0NJFkwYIFJtGULLAgiykxpZSNfCVFamysfDQWNhZKEkWUUojI+P7+9ntq3s3cP/Oe/+L+36v71tOZ/5nnnvM859yP85576+rKKEegHIFyBP7nEegVwNxCNDSBIeAuOA06QeGiP4rbwe9ueM3vRlCoGIjaC6C7Gfv9nv+NKYqjQQi99A8zZqqtCIYGI/Kyw4xMXazGUN9qDqrymKEcdx7MdR7/0cmrCW0YvV4Fdjp5yuaaKHV0OhzOtUQz1+H3c7SdO2UEPd4Anhkxzm34o3JX6uhwJJxbwIR6ypvwdVy40AjfAR4TxtFpVh/OCYJGg3vAhHpK3TB04wgXerrfBx4TxrkCX7f0cDEORQ+ACfWUesjqYRsuJqDoIfCYME4HfC2DwsUkFD0GJtRTnoM/IJwTBE0GT4HHhHHOwlfqEC6moOg5MKGe8gz8PNeP7kGbCvNFoplT8Pu4e8iR2EBfL4FnRoxzHH7vHDW6u5oJUymyCfWUh+BH2LvImJxDzdtEMwcyrQSpmIcO5fmeGTHOviDaMzIWUKPs0YR6yt2ZVoJULELHp0Qzu4Joz8hYQs2XRDPbM60EqViKjq+JZrYE0Z6RoeVMyjXzC/6mTCuBKtrR4rnwxfkJ1gfSXlFKJ7UeQz/granYQrDKz05DWmWPD6a9opyUPbRHtDCxYiuBKlejxXPKGecJfN1IQscx1JlgT/kMvvKjsKGl/gngMWMc5UfTwjpCmJb8R4EJ9pSv4M8AYUOmDgKPGeO8gT8rrKMuYcprTLCnfAff+x6oZt6V33jMGOcD/Pk1U+vseE+iKaUeSkFCRyvqbBY8pVIQpSKhYyfqPGaMo1RkeWhHiNuWaOo7/JXRTSmps1nwlFqha2kVOlpQpyTPY0gc5VDrQOjYgLoUU+JuDO0IcWuBRt87UzK1GYQOXR+6TrymxNsa2hHiVgHd0VJM7YhuagUCvyWaao1uahkCU/f29kY31YRA76aLnaL7o5tqRGDq/nhbdFNKI5RO2Cx4ytnRTSnhS3nHdCS6IenTqHvfAnZUY0i7O3mGPlLSNaV9h55CO7OFieko7elN+uLCuOkSqm8d/vbhxuGimTG9Y/njJNAmpVJ1fc7ZDMooR6AcgXIEyhGoOAJ/ADHdrr++9w/kAAAAAElFTkSuQmCC", "play.fill": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAFAAAABYCAYAAABiQnDAAAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAAEgAAAAAQAAASAAAAABAAKgAgAEAAAAAQAAAFCgAwAEAAAAAQAAAFgAAAAAY2usVQAAAAlwSFlzAAAsSwAALEsBpT2WqQAABA1JREFUeAHtnE2ITlEYx8f3dwmJZEZKlFJTUxYWiljYKEoRCxsLRY1CLKYUpdhYKDKLsbAgysJGKUpSFiIaEQ2TfCQMjXx//J/FTHeO9733nnOe83Xvc+rf3DPnPM85/99933fue8+509IiRQgIASEgBISAEBACQkAICAFtAmO0I0YGzEW1FfoDfR3ZJLU8AlvR+AT6m1EvjvdB0yApOQS60JYFpx6/Qft2aFROjto2tcM5vV1VaI3qd9BveW1JNTF+piS8IaAEuweaA0kBAfVzbwhU0c/PiN0Lja87xUEAKIKV1/4Y8evqDDEPjk7bFUBcVEeQOpCK+n4HwKNQrS57iqCYtL8CxG1QLS57TACVjbkNiB1QpUtZGKb96LKnG5pdVYqmYHTjBgCwExpXNZC6IGz7PwLAtVWCaAvENP4yIC6sAkhTABxx3wDwCDQlZZAcIGxzvATALalCtDXPGX8TEOnuUFKFEwBHrt+gdxqalQpFDtMucnwEwN3Q2NhBujDPmfMhAK6OGSKnWZe5LgHighhBujTNnZtWCQ9Bk2MCyW3SR75+ANwUC0Qfhl2NcQMQl4UG6cqcr7y/APAkNCMUSF9GXY/zHgB3QrY7M7TPg2tjvvPfB4GV2hQsAnwb9DXeeTBpteBSOtSXoRDjfAGFLmhiaRoGHUMY8z1mH7hsNGBTKsS3mZDjXQORxaWoaHQKaSjE2HQTd48Gn8KuIUzEMGYPyIwupFOiQwxmQs1hfyM+ursBaPJ1LXTxTevVtHY9XFhelsPZqn0wE/bmqxYFoEokv/5DbRaAKpHm9Wdoeq02C0CVSPP6geZN5VtC/QUMOS6t/NGCFUsJaSTE2P2gxrpIFcJEiDHpj8VxaCrLyy6TJIQZ32Nehd8lGc+sh77N+BzvKUitZ6XVIJlPQ77GGoTPg9CEBn7Zf+XLlK9xzoHQPHZKOQl9GXM9zl14XJHj01mTa2Ou878DmR1QsC8Qrg26yv8T0E5A06GgxZVBl3np1vzSoNQyg7s0yp27D/PekJl7FIfcJl3k87I8aXo2XBjmzEkL5P/d9DQ16yKO0yxnLu9bNEzhcprmyBVsk1DqAINvU0sZ4HVMPvhGyRQBvsCko9mqmxLAoc3ik0wnHVMcxwe/To6LMN8WEwDbueiYt+n7ABNdZTvZGONtoJSJ/QDTu6DoH9kyPTllIJj0oaXDU1AyDw3GBDDJx1ZjAEgPTm82nUiqcSZvTzWGdn0ehpJ+dN/0BH5CoApEp16Zfx5hCvCeIcBexK0xHbRKccc0AQ6gfydU2csS3ZPbhgC641v0tqXLkm6ItsRKUQjQF3rafNMM4i20dSgxUlUItKN+AXoLEczn0Fmokl+/4EuKEBACQkAICAEhEB2Bf1yna2SEanmMAAAAAElFTkSuQmCC", "forward.end.fill": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABQCAYAAADvCdDvAAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAAEgAAAAAQAAASAAAAABAAKgAgAEAAAAAQAAAGSgAwAEAAAAAQAAAFAAAAAAGeFr3AAAAAlwSFlzAAAsSwAALEsBpT2WqQAABONJREFUeAHtnH3ITmccx21m2DA92qzWij+QbY+8lCSizVpKU0iW7A/ZHzOLGMofaqQwkja1pvZCYX8opeSleAqjZIw2Q4uFUTQMMXvh8+15ru7T09Nz39ftPve53n71ea7rPvd5+V3f77nOuc91znk6dEiRFEgKJAWSAkmBpEBSICmQFEgKJAXqq8BTVW6uF8vNgEHwP5yC7XAFQol+NGQ4NMAzZRr1iO/vw2U4BLehbvEmW7oJSiLLQz5vADXA53iF5PdBtm029Xss+yk8DbmHkr0F7SV4ne9nQrW9j0ULi+fY8q/QXvsq/W5ZPVqx0iLZw8w7uB5J1XAbH1u0r5wxOoTlfrQ4YZnwv8y/DnqAD7GHJMsJbfP95LwbrZOVTUJm3qss917eydVg/b9V2T7TztblQtucbE881e7pL5PYFjgAr9kmWcf5u9d4W9brszXkSfMdywpOgs5Fz4NrUfgPkXobIgM6wWI4A5MgRUaBIgwxm3+Vii4md4MuwlKgQJGGGAPeoXIadDHV1UyMtXTBEGnfGZbCzzABog1XDDEG9KWyE3ZAH4guXDPEGDCRyi+wBJ41E2MoXTVE2ut8sgJ0fnkbogiXDTEG9KeyF74HDW4GHT4YYgyYSkUjsQug3P0Js4x3pU+GSNxusAZ0tT8GggvfDDEGvE6lCTZBbwgmfDXEGKDbyGdhDnQ0E30ufTdE2r8An8MxGAFeRwiGGAOGUPkBNkIvM9G3MiRDpL2Gz2fBOfig5TOFPxGaIUZ53cv+Co7CUDPRhzJUQ4z2eq5K55YvoKeZ6HIZuiHSXm38CPRr7H1wOmIwxBjwEpXv4CA0momulTEZYrQfReVHWAu68ncqYjREBmgsbD5oiH8cOBOxGmIM0H19jSR/YiYUXQY7amohrK5dPoM/LZbJbdZkSElamdKp9LGYWjKkpLsuJguP2M8hhRvQOoFkSEkRvQn2sPSxmFoypKT7Jqp/lT4WU0uGNOt+mEI3uQqPZEjz/RNdHOrdwMIj5l9ZejlHg456a8qZiLGH/I36y+ENcMoM7RWx9RC9+qBzhXqHkxFLD7mE+lNgPDhrhvaQ0A35hzauhoGgl4Ocj5APWftRXydtPX7qTYTYQ/QK9nR4C7wyQ3tNSIb8R3vWwwDYAl5GKIcsXWnPhlNeupBJ2vcecp22zITR4L0Z8sVXQzQy+yXo8PQN6F9aBBE+HrKOofyHcDwIB1o1wqceonveMmIEBGmGvPGhh+hw9C0sghsQdLhuyE+or15xJGgXMo1z9ZClO3fzYBhEY4Z8cbGH6KJOb9peU4KxhUuG6LFOjT01xWZCtr0uHLJ061T/P2swNEHUUXQP0ZC4zhWXo3Yh0/iiDDlPDrpzpwedU2QUqPch6z7bXgqNkMzIGGGqtj3kAQt2MQtbljuZfy5csFyunrNrh6llSC+rsO0hV63W3jzzRYp3W3DZDGX7h/7UMK7UcF1trmozUzWUUQnmcZuuba7JzYmrKmxbJe3XiHTfvJs5ssKE9bxTv7yTyWH9fVjnXahE8HLzbMshvzZXuaKdhM3jNm0u6MnECeR5p502ljNC3zdBVe/F63WuamIaC+kEPQjUNU/CVvgarE9kLONavEhCM2A4NEC5Hz8yQT8IfoddLWhaiqRAUiApkBRICiQFkgJJAScUeAyjR2von5DLPAAAAABJRU5ErkJggg==", "arrow.clockwise": "data:image/png;base64,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", "stop.fill": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAFwAAABUCAYAAAAPvFA1AAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAAEgAAAAAQAAASAAAAABAAKgAgAEAAAAAQAAAFygAwAEAAAAAQAAAFQAAAAAM4MpBQAAAAlwSFlzAAAsSwAALEsBpT2WqQAAAp5JREFUeAHt3b1OVFEUxfFBiY0dhQk1PgTGxEAs+LASXoHYGZ+MzsAbwBOgJny0YKOVjaK4N2aSmaxgzh5ZI8z5n2RncnfOXXfO796ZzG3uDAYMBBBAAAEEEEAAAQQGcwaDR5E5b8j9H5GXcdDvt3ngfwV/GG9mO2oz6nnUYtTjqFka32Ix51EHUXtRu1F5IqY+1uKIp1FXndVZrHcjaqrjbRztZ1Rv2MP15trfTUt8vXPsUXT7lZ7f2cdRw4P2/noSFmnSPB40z/wz8XW8PC3uM8vTl2JxW5UFVsHtH6HKm78jc/MrtnlUwZ81J/czcbmy1Cr4k0p4J3NLJtUbn/w5VD1Js+6eJs131lXw/FXCUIFmR65WxbN2ALfyajjgamLtAG7l1XDA1cTaAdzKq+GAq4m1A7iVV8MBVxNrB3Arr4YDribWDuBWXg0HXE2sHcCtvBoOuJpYO4BbeTUccDWxdgC38mo44Gpi7QBu5dVwwNXE2gHcyqvhgKuJtQO4lVfDAVcTawdwK6+GA64m1g7gVl4NB1xNrB3ArbwaDriaWDuAW3k1HHA1sXYAt/JqOOBqYu0AbuXVcMDVxNoB3Mqr4YCribUDuJVXwwFXE2sHcCuvhgOuJtYO4FZeDQdcTawdwK28Gg64mlg7gFt5NRxwNbF2quC/rO/mfobnI5iaRxX8S3NyPxO/VpZaBf9cCe9k7kVlnVXwfKQzY1zgcHzz71tV8Hx+NmNcYH9883a38gR9jOr9Ib/D9X8Ki+pFWz4jq7HHD9Cvn5L/sqw34Q47naPnXxK8mdBu4t1exJ5HUcOPVy+vH2LNK1ETjeZHeN6Qnvu/ihr9042F2C49xPyG7LvQzpuavPcY/dON97GdFxcDAQQQQAABBBCYIYHf/eAl3JIyb9MAAAAASUVORK5CYII=", "desktopcomputer": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAHwAAABkCAYAAABEm1RIAAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAAEgAAAAAQAAASAAAAABAAKgAgAEAAAAAQAAAHygAwAEAAAAAQAAAGQAAAAAvAGjeQAAAAlwSFlzAAAsSwAALEsBpT2WqQAABEBJREFUeAHtnctqFEEUhhNv4IWo0U3AhUJciYKgG1EhIKgb3asb8RF0qS+gD+DKhRBEfQURgqiI7rygCxMRXGSh4iVBFBP9DziQQLpj1dScOZ3+Cn5MurvqnP4+Z6YnM8wMDDAgAAEIQAACEIAABCAAAQhAoI8EBgvV3qN1DisjyrCyWmGkE/ijKTPKR+WV8kCZVUKMNerigjKpWKOkPIOf4npD2an0ddit+L6CZB8G38X6dL+Mr1Php8h2/88+J+Yn+iH9KrLdZXfuSe2xfVs30lMvrrar2C1lbTdFmZtNYINm/lAmcldYlTjxjI63ooz+EbAL5exhV9opY6zmYLuiHFemlPma49hVT2CTdp9S9lYctkPbR5W3FftrN6cK31ez2iXte1+zn13/T+CZDr2sHKiYYh6yhKfepVddMNhVO7Ir7GRstnvIOzXz7Foqa6QK31xRZbpiO5vzCXypmTpUs692V6rwqsV4zK4ik7/dnopVjcGqHcttLyV8uTrsD0IA4UFEeLWBcC/SQeogPIgIrzYQ7kU6SB2EBxHh1QbCvUgHqYPwICK82kC4F+kgdRAeRIRXGwj3Ih2kDsKDiPBqA+FepIPUQXgQEV5tINyLdJA6CA8iwqsNhHuRDlIH4UFEeLWBcC/SQeogPIgIrzYQ7kU6SB2EBxHh1QbCvUgHqYPwICK82kC4F+kgdRAeRIRXGwj3Ih2kDsKDiPBqA+FepIPUQXgQEV5tINyLdJA6CA8iwqsNhHuRDlIH4UFEeLWBcC/SQeogPIgIrzYQ7kU6SB2EBxHh1QbCvUgHqVNKeNUH9gU5zUa20ZMPMU79rNUqcke046HyQan7QLmq+WxfTGC9fj23eFOZ30oJt3WulGmJVXpJoNRdei97ZO2CBBBeEGYTlkJ4EywV7BHhBWE2YSmEN8FSwR4RXhBmE5ZCeBMsFewR4QVhNmGpVOH2HZiM/hPI9pAq/FP/z5UORCDbQ6rwN+AOQeB1bhepwidyCzGvGIHOl8lnLZgq/Laq/M6qxKRSBMa1UPYrkqnfLvxVxXYp+0t1zzpJBOybhc8q35JmdXmwvdlhUul8pzX/+rE436W77OmjmmkXcMj2YTAn1hezbRWaaLf0a8qsgvjeMXgkvvaOoiIj+zssF1Tfop+PKdbUiDKspF4baErWOKhZG7Nmpk16rsM/p03JOtpuODOKXYm/VO4pLxTGPwImwuPe5fhKIZ76tGylnHdrzwPhLVOPcIS3jEDLTpdbOMJbRqBlp8stvGXCm3i6Q2r6ujKtzCsez8Ptr4lPlDGF4UxgQvU8JC9V45dq21/3GE4EjqrOUiI8t911OteelGnaY/junlBIW9ReKWzsaJrwqQCk3wXooTUt2Kt7jxXPu/CFteztXYdaQzvIiW5VHzcVe5vPQhm9/NlE2ytzJxUGBCAAAQhAAAIQgAAEIACBggT+ArMqcY2PWzpzAAAAAElFTkSuQmCC", "clock.fill": "data:image/png;base64,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", "gamecontroller.fill": "data:image/png;base64,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", "sparkles": "data:image/png;base64,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", "power": "data:image/png;base64,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", "moon.fill": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGgAAABkCAYAAABq3nXaAAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAAEgAAAAAQAAASAAAAABAAKgAgAEAAAAAQAAAGigAwAEAAAAAQAAAGQAAAAA2FgdywAAAAlwSFlzAAAsSwAALEsBpT2WqQAABkpJREFUeAHtnFusXVMUho9LG60WvSlF5RClGiIuJYSQCJKmkdaDB6QIIhGECE8evHggFZKmTSRC1ItXkSAVLVURqZBQRSQn2qprk6KUqsv3J/ukK9s5e88511pzzbXmGMl/9uWsMccY/7/nusw51xoZMTMGjAFjwBgwBowBY8AYMAaMgYoZOKzi9so0NwfnVeAK8BdYB94CZg0zsID4q8E+8G8BB3h/FjBriIGZxH0c7AdFYYrv72kot+zDalf27QBhxkW6KXumIhNwMvFecxBGAv0NTgBmkRi4kTh7wXjvGPa6IVJe2YeZAgNPewgzLtyd2TMXgYDZxNgcII5EOjFCflmHOJXqt4PxHuHz+kXWzEUofjExdgeKIyGfi5BjtiEWUXkZcSTQ7dmyV3Pho7S/C/jsziba9pya88yy+WOp+rMKxPmHNqZlyWCNRR9J27pumag3+H63s8Y8s236qYrEkZgbs2WxpsKXVSiOBFpfU56tbPbwkllrquCFkm30u+/p/yLnz2UFWgN5cysmUPNCZj0Gygh0PW2sqIFJzaaa9RgIFWg6/uo9dZgGV816DIQKdD/+mtupwyS+WY+BEIE0Qv1IjQzaRWqB3BCBHsJfowZ1mQlUYNZXoKPxvbvgX8dbLSYx6zHgK9Ct+M2qmb1Tam6/081/TnW+Y2u+22u1j1kAA0vx8SU7ZHuNZk8NyK+TLj67uFhr1LQcua5T+E6KqKJE2ncgpEeE+GiUwgwGXHvQBWw7PyJjimcGA64CXROZrQsjx2t9uE1UELKrCvX5ofWMRSxAvey3yAJJ2CURa0w2lMsu7kyyb2IAc3myrEVMzEWg8yPmUwxlAsGGi0BaJdqEXULQeU0ETimmi0ALG0pYud3cUOxWhd1EtqFnY2X9viR2Sjc6RxfOpQedFD2rQwHP4O3Vhz7m985FoBkN03Jfw/GTD/8zGZbdVZX1vzR5lhpMUMugyhJc1n9Lg/UnH/pgAgJJ4JXJM9VQgr8nIpDuO6p7ur0hisuF/SkRgdSLXi5XSje9dUNv2WNIlf63dJPm8KreTUwgjaxfHF5OuzxdroN2JFaSRtZfBbqI7by5CDSWIAtzyel1oPuTOm0uAulhFCnaaST1Hsj+mXLnQkKVB/mq29IdeZeBbE13cDcx5e0j5H5yvBdkO/K9keJ9CGtq2zfIs1MPYXI5BlHzyNv60wLT8rBPgB6lqZ6fjem6o6leERpXk3035KKQetr3LRRJ4n4M7gK6t6nTtpbqQn/NKfjpcZzPAM0tue7a2bRSqzXu5aSaAtFV5KCVq88DTWHMB3WZRj2uBXokqMY0dWvNDrACOJnvaamCLHJquV0baSpjaw+qUQ90EpHarYvUYXYEG+jOwFGgIajzgNaX63UK6Ld9fKEfhqZyBpqvQA/S2uqBLXbrn5pN1m03IlLQ9ZYg01qNmT3o1N73rFFCfgUGmq9ASuprMHtgq/bPYQxoncfx4MCwDX0PWuqaOtCalWPgRdyHiqMQvj1IPscB9aJj9MHMm4E/8Dgd7Hbx9O1BanMvsF7kwu7E26zjaydxJnZ3+3Yam42BKk55c2pD6zuiHb+Xm0DeP9A74CyqvUK0nHpAmVq3wFXIMb+UoHqegbptmcRz8P0VjnRi0IgtI6qutnMgOrTG6Lu2/l/CEybQpD/Ql/rJauKzhjk2m0j/E2krnOiMNwmbRRbbQOhuoGt+u+AiuUer6aRBowxdI9u3nj1wcDZI0rRO7UfgW1RXttdA6NIklSkkJZE0n9IV0l3r0CWH5oFaYdrdfQpci2v7dt9Q65JWKFNIUicOOZzdfUCdCwp1t+qtTsF1ndTVi9n11HZUqxSZJFmNOHRpWOgX6lk1Sa2t/VrHpS4MsL5DHY2NrcVQX1MVY6BtJwa6fLgNRB+VJmZ00xDIY0DXDakLpRU9T4Jok23ESsa0xuFRkOLxSbfdrAFaVpW9zYCBB0CMp9sP67EarnoYZNljqHuoaZnxWqCVncPIrOr/Gj97FlwFQhbT4Fa9pX6wE1EXgevAlUBjXNNBFfYnjXwINoA3wfvgIEjKUheonyxd9GqUWPfNLgajYCGYB+YAiTcVqFfpwK5lulpsqWGYnT1s5/UjoNfkBCEnM2PAGDAGjAFjwBgwBoyB1jPwH+Qw0tR2FCdbAAAAAElFTkSuQmCC", "ladybug.fill": "data:image/png;base64,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", "bolt.fill": "data:image/png;base64,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", "checkmark": "data:image/png;base64,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", "xmark": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAFwAAABUCAYAAAAPvFA1AAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAAEgAAAAAQAAASAAAAABAAKgAgAEAAAAAQAAAFygAwAEAAAAAQAAAFQAAAAAM4MpBQAAAAlwSFlzAAAsSwAALEsBpT2WqQAAA0FJREFUeAHt3T2r1EAUBuDrF4iFYKHIBQvBRhQLQRAbbyXYWCiIoKCNlZ2d/0h/giC2IiiCCIKKhVztLFQQv/UduAfikJ3Mmc1k55y8Ay+zyU4ymSdLdtnNnbu2xkIBClCAAhSgAAUoQAEKUMC5wI7C8R3CdteRc8hu5C3iuQSnC8hl5CjyDvmKTFKuoJdvyN9OHuDxXsRj2Y9BPUa64/2M5fNTDPYwOvkedS4H8gjrvaEfwJheLBjvF6w/iFQtd7B3Ae6rPaGnsGXst7Ta25UbDJ3R09jffcT6Kz1cRh4ix5BUCe2qlpvYu5zdVG35lR4QF11G4jFfrKqNne9B3iBxx33LFtE12M/gsBOpXo6gh02kDzleZwldg/0K41+vLt3pwBt609ji7gXdBLYXdFPY1tFNYltFN41tDd0FthV0V9ito7vEbhXdNXZr6LPAbgV9VtirRp8l9qrQZ409NTqxRRx17S+8iN3Bloe10Iktwj312OjE7kGOV42FTuxYNrG8LDqxE7iLnipFJ/Yi0Yz1WvTQPvdWhsl/8M0YbxNNNOg/ccTxHQJ9y8QeOLUa9D7g7jpiD2DL02OgE1s0M+tl0ImdiRw3K0EndqyoXD6D9t3rcurxb7QNf53AUiig+ZwtJ8LSvYyFLHU2K8EmeuG5WAab6Er0MbCJnok+JjbRB9A12OGj31lkExHYVM030ghfi72+tb3mczrRt9BKseWcEV0kMuplsaULootEoh4LW7ogukj01GNjSxdEF4lOXQtbuiC6SKCujS1dEX1CbKKvAHvW6FNdRgQ5rmd1eVk1tuDPAr0V7Fmgt4btGr1VbJforWO7QreC7QLdGrZpdKvYJtGtY5tC94JtAt0bdtPou3B0T5DUr+TynMUbKzVfA4QJjrfJ2apVX3WMLWYa9DCdt6po554Nc8sOlddosIF8GGrY6PNh5tEN5H3G8Z3KaPNfEy14mDc7Vaxjy9hy0T/JBrXqk9jxH0Su093a4jV7yCl1eQnzqIf/FFC93EYPMfpzrJM7oqofwMQdBPR4guNfWHej5DhK32WPo7NLyD7kKXIP+YF4LWFW6WvICeQjchd5ibBQgAIUoAAFKEABJwL/ANIEGLUtlObmAAAAAElFTkSuQmCC", "checkmark.circle.fill": "data:image/png;base64,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", "xmark.circle.fill": "data:image/png;base64,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", "exclamationmark.triangle.fill": "data:image/png;base64,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"};

function sf(name, extra = "") {
  return `<i class="sf${extra ? " " + extra : ""}" style="-webkit-mask-image:url(${SYM[name]});mask-image:url(${SYM[name]})" aria-hidden="true"></i>`;
}
const AI = `<span class="ai on"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>`;
function tile(id, icon, tint, title, sub, cls = "") {
  return `<button type="button" class="tile${cls ? " " + cls : ""}" id="${id}">
    <span class="tico" style="background:${tint}">${sf(icon)}${id === "refresh" ? AI : ""}</span>
    <span class="ttitle">${title}</span>${sub ? `<span class="tsub">${sub}</span>` : ""}</button>`;
}
function notice(caption, title, body, buttons = "") {
  return `<section><div class="group notice">
    <div class="ncap">${caption}</div>
    <div class="ntitle">${title}</div>${body ? `<div class="nbody">${body}</div>` : ""}
    ${buttons ? `<div class="nacts">${buttons}</div>` : ""}</div></section>`;
}
/* 排班：明日安排原来是一段 <pre>；现在每个时刻一行（带「今天跑/今天跳过」的开关，
   开关走和别的中继开关一样的待保存→确认→回执），每个游戏一行，说明进脚注。
   时刻行对应哪趟班：看这一段里的游戏和队列的脚本名对得上（2026-09-15）。 */
const OWNER_OF = { "明日方舟": "MAA", "终末地": "MaaEnd", "鸣潮": "OK-WW" };
let QUEUE_SWITCHES = [];
function beijingToday() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
}
function planRows(text, qs = [], relay = {}, curQueue = "", thisShift = null) {
  QUEUE_SWITCHES = [];
  const OWNER_NAME = { MAA: "明日方舟", MaaEnd: "终末地", "OK-WW": "鸣潮" };
  const fallback = `<section><h2>这一趟</h2>` +
    `<div class="row"><label>${curQueue || "班次"}<span class="hint">${(thisShift || []).map((o) => OWNER_NAME[o] || o).join(" → ") || "机器还没上报排班"}</span></label></div></section>`;
  if (!text) return { thisShift: fallback, tomorrow: "" };
  const lines = text.split("\n").map((l) => l.replace(/</g, "&lt;"));
  const blocks = []; let cur = null, game = null; const foot = [];
  for (const raw of lines) {
    const l = raw.trim();
    if (!l || l.startsWith("📅")) continue;
    if (l.startsWith("🕘")) { const m = l.replace("🕘", "").trim().split(/\s+东京\s+/); cur = { t: m[0], tokyo: m[1] || "", games: [] }; blocks.push(cur); game = null; continue; }
    if (l.startsWith("▸")) { game = { name: l.replace("▸", "").trim(), h: [] }; if (cur) cur.games.push(game); continue; }
    if (game) game.h.push(l); else if (!cur) foot.push(l);
  }
  const skipped = String(relay["今天跳过"] || "");
  let rows = "", mine = "";
  for (const b of blocks) {
    const owners = b.games.map((g) => OWNER_OF[g.name]).filter(Boolean).sort().join("|");
    const q = qs.find((x) => (x["脚本"] || []).slice().sort().join("|") === owners);
    let part = "";
    if (q) {
      const sw = { id: `relay|queue:${q["名"]}`, label: `${q["名"]} · ${b.t}`,
                   on: { action: "unskip_today", queue: q["名"] },
                   off: { action: "skip_today", queue: q["名"], day: beijingToday() } };
      QUEUE_SWITCHES.push(sw);
      const on = skipped !== q["名"];
      liveVals[sw.id] = on;
      const hint = [b.tokyo ? "东京 " + b.tokyo : "", on ? "今天照常" : "今天跳过，明天照常"].filter(Boolean).join(" · ");
      part += `<div class="row" data-row="${sw.id}"><label>${sw.label}<span class="hint">${hint}</span></label>
        <span class="sw"><input type="checkbox" data-relay="${sw.id}" ${on ? "checked" : ""}><span></span></span></div>`;
    } else {
      part += `<div class="row"><label>${b.t}${b.tokyo ? `<span class="hint">东京 ${b.tokyo}</span>` : ""}</label></div>`;
    }
    for (const g of b.games) part += `<div class="row"><label>${g.name}${g.h.length ? `<span class="hint">${g.h.join("，")}</span>` : ""}</label></div>`;
    if (q && q["名"] === curQueue) mine += part; else rows += part;
  }
  foot.push("时刻行的开关：关掉 = 这趟今天不跑，明天照常；再打开就恢复");
  const thisShiftHtml = mine
    ? `<section><h2>这一趟</h2>${mine}<div class="foot"><p>${foot[foot.length - 1]}</p></div></section>`
    : fallback;
  const tomorrow = rows ? `<section><h2>明日安排</h2>${rows}<div class="foot">${foot.map((x) => `<p>${x}</p>`).join("")}</div></section>` : "";
  return { thisShift: thisShiftHtml, tomorrow };
}

/* The games' own stamina icons (his 09-15 order): 明日方舟 理智 and 终末地 理智 from the
   games' wikis (arknights.wiki.gg Sanity.png, endfield.wiki.gg Sanity.png), 鸣潮 波片 from
   库街区's own widget asset (web-static.kurobbs.com/gamerdata/widget/game3/energy.png). */
const RES = {"ak": "data:image/png;base64,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", "ef": "data:image/png;base64,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", "ww": "data:image/png;base64,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"};
/* Reminders' smart-list tile: coloured circle top-left, count top-right in the label
   colour, name in grey at the bottom. A read error takes the count's place in red.
   `icon` is an SF Symbol name or a RES key. */
function numTile(icon, colour, big, unit, label, sub, err) {
  const ico = RES[icon] ? `<img class="rico" src="${RES[icon]}" alt="">` : sf(icon);
  if (err) return `<div class="num err" style="--c:${colour}"><span class="nico">${ico}</span>
    <span class="lab">${label}</span><span class="sub">${err.replace(/</g, "&lt;")}</span></div>`;
  return `<div class="num" style="--c:${colour}"><span class="nico">${ico}</span>
    <span class="big">${big ?? "–"}${unit ? `<small>${unit}</small>` : ""}</span>
    <span class="lab">${label}</span>${sub ? `<span class="sub">${sub}</span>` : ""}</div>`;
}
/* 「回满」 the way Health and Reminders date things: 今天 19:24, 明天 01:38, else the date. */
function whenFull(stamp) {
  const m = /^(\d\d)-(\d\d) (\d\d:\d\d)$/.exec(stamp || "");
  if (!m) return stamp ? `回满 ${stamp}` : "";
  const p = (x) => String(x).padStart(2, "0"), d = new Date(), t = new Date(Date.now() + 864e5);
  const day = `${m[1]}-${m[2]}`;
  const name = day === `${p(d.getMonth() + 1)}-${p(d.getDate())}` ? "今天" : day === `${p(t.getMonth() + 1)}-${p(t.getDate())}` ? "明天" : day;
  return `${name} ${m[3]} 回满`;
}
function numTiles(snap) {
  /* 「今天跑了 N 趟」那格 2026-09-18 删了（用户：无意义数据；sitemap 里早没有）。三格体力 2 + 1，
     最后一格占满一行，照提醒事项首页奇数张智能列表磁贴的排法（AX-57）。「最近一趟」搬到回执组头。 */
  const r = (window.Stamina && Stamina.data) || null;
  /* Behaviour 2: no reading yet but the phone is configured → the three tiles are drawn with placeholders (icon and name are known), and
     replaced in place when the first reading lands; with a cached reading (state restoration) the real numbers show at once. */
  if (!r) {
    if (!(window.Stamina && Stamina.loadTokens())) return "";
    const ph = (icon, colour, label) => `<div class="num" style="--c:${colour}"><span class="nico">${RES[icon] ? `<img class="rico" src="${RES[icon]}" alt="">` : sf(icon)}</span>
      <span class="big"><i class="ph"></i></span><span class="lab">${label}</span><span class="sub"><i class="ph"></i></span></div>`;
    return `<section><div class="group nums">${ph("ak", "var(--ios-tint)", "明日方舟 理智")}${ph("ef", "var(--ios-orange)", "终末地 理智")}${ph("ww", "#30b0c7", "鸣潮 波片")}</div><div class="foot">正在读取…</div></section>`;
  }
  const ak = r["明日方舟"] || {}, ef = r["终末地"] || {}, ww = r["鸣潮"] || {};
  let h = "";
  if (r) {
    /* The tab bar carries each game's own icon; the tile shows the resource's own icon,
       so the two never repeat. */
    h += numTile("ak", "var(--ios-tint)", ak["理智"], ak["上限"] != null ? `/${ak["上限"]}` : "", "明日方舟 理智", whenFull(ak["回满"]) || (ak["理智"] >= ak["上限"] ? "已满" : ""), ak["错误"]);
    h += numTile("ef", "var(--ios-orange)", ef["理智"], ef["上限"] != null ? `/${ef["上限"]}` : "", "终末地 理智", whenFull(ef["回满"]) || (ef["理智"] >= ef["上限"] ? "已满" : ""), ef["错误"]);
    h += numTile("ww", "#30b0c7" /* 待 tokens：systemTeal 探针色表未列 */, ww["波片"], ww["上限"] != null ? `/${ww["上限"]}` : "", "鸣潮 波片",
      ww["错误"] ? "" : [whenFull(ww["回满"]), `备用 ${ww["备用"] ?? "–"}`, `周本 ${ww["周本"] ?? "–"}/${ww["周本上限"] ?? "–"}`].filter(Boolean).join(" · "), ww["错误"]);
  }
  return `<section><div class="group nums">${h}</div>${r && r["取自"] ? `<div class="foot">${r["取自"]} 读取，下拉刷新会重新读</div>` : ""}</section>`;
}

function render() {
  liveVals = {};
  if (window.Stamina && Stamina.fromSnapshot(snap)) Stamina.refresh(true).then(() => render()).catch(() => {});
  let c = (snap && snap.config) || {};
  const relay = (snap && snap.relay) || {};
  let html = "";
  /* AUTO-MAS 没在运行时，中继读不到配置，快照里只有一条 _错误。
     2026-09-02 晚：用户在机器上玩，AUTO-MAS 被关了，页面把空配置当成配置显示——
     「一坨屎」。现在：明说读不到，配置区退回上一次读到的那份，并标明是旧的。 */
  let cfgNote = "";
  if (c._错误 || !Object.keys(c).length) {
    cfgNote = `<div class="warn">${sf("exclamationmark.triangle.fill", "inl")}读不到 AUTO-MAS 的配置（它没在运行？）${lastGoodConfig ? "——下面显示的是上次读到的，改了也要等它开着才生效" : ""}</div>`;
    c = lastGoodConfig || {};
  } else {
    lastGoodConfig = c;
    try { localStorage.setItem(LS + "-config", JSON.stringify(c)); } catch {}
  }

  const qs = (snap && snap.queues) || [];
  /* 选中的班次记住，并且**只显示这趟班要跑的游戏**。用户 2026-09-04：
     「早班晚班切换的时候应该只显示当次班次的游戏，否则极容易和早班混淆。」
     晚班只有明日方舟，把终末地和鸣潮摆在那儿，改了也不是这趟的事。 */
  if (qs.length && !qs.some((q) => q["名"] === curQueue)) curQueue = qs[0]["名"];
  const qopts = qs.map((q) => {
    const t = (q["定时"] === false) ? "未启用定时" : "";
    return `<option value="${q["名"]}"${q["名"] === curQueue ? " selected" : ""}>${q["名"]}${t ? "（" + t + "）" : ""}</option>`;
  }).join("");
  const thisShift = (qs.find((q) => q["名"] === curQueue) || {})["脚本"] || null;
  const inShift = (owner) => !thisShift || !thisShift.length || thisShift.includes(owner);
  const run = (snap && snap.run) || {};
  const busy = run["在跑的"] || [];
  const nextAt = (() => { const m = /🕘\s*(\d\d:\d\d)/.exec((snap && snap.plan) || ""); return m ? m[1] : ""; })();
  const ef = relay["刷声骸"] || {};
  /* 设备卡（查找的结构）：名字 + 一行状态；右边一个词。状态文字由 setStatus 同步。 */
  /* 设备行（46 Apple 账户页的值行：名字左、状态右灰字）。id 不变：setStatus 写 #status2/#dot2/#side2。 */
  /* 状态卡：两行行——点 + 「游戏机 · 开机中」 / 「实时 · 配置 1 分钟前」（index.html .devcard 写了来源）；文字由 setStatus 拆分同步。 */
  { const st = $("#status") ? $("#status").textContent : "正在读取…", dotCls = $("#dot") ? $("#dot").className : "dot";
    const i = st.indexOf(" · "), head = i > 0 ? st.slice(0, i) : "", rest = i > 0 ? st.slice(i + 3) : st;
    html += `<section><div class="group devcard"><i class="${dotCls}" id="dot2"></i>
      <div class="dtext"><div class="dname" id="dname2">游戏机${DEMO ? "（演示）" : ""}${head ? " · " + head : ""}</div><div class="dsub" id="status2">${rest}</div></div>
      <span class="dside" id="side2"></span></div></section>`; }
  /* 提示卡（健康摘要的样式）：只在有事时出现。「现在在跑」只在机器真的在线时说——
     机器关了以后快照里还留着最后一趟的名字，09-15 10:58 页面一边写「关机中」一边写
     「现在在跑 MaaEnd」。 */
  const alive = !!(lastHb && (Date.now() - lastHb < hbWindowMs()));
  if (busy.length && alive) html += notice("现在在跑", busy.join("、"), "这时改设置会被推迟到跑完再生效");
  if (ef["到"]) html += notice("刷声骸", `正在刷「${ef["名字"] || "?"}」`,
    `刷到 ${String(ef["到"]).slice(11)} 为止${ef["从"] ? "，" + String(ef["从"]).slice(11) + " 开始" : ""}`,
    `<button type="button" class="capsule" id="echofarmuntil">改收工时刻</button><button type="button" class="capsule red" id="echofarmstop">提前收工</button>`);
  /* 动作磁贴（查找 / 家庭的磁贴，提醒事项的几何）。 */
  html += `<section><div class="group tiles">
    ${tile("runnow", "play.fill", "var(--accent)", "现在跑一趟", curQueue ? `${curQueue}${nextAt ? " · 下一趟 " + nextAt : ""}` : "")}
    ${tile("refresh", "arrow.clockwise", "var(--ios-gray)", "刷新", snap ? ago(snap.at) : "还没有数据")}
    ${tile("estop", "stop.fill", "var(--bad)", "停止一切", "脚本和游戏", "danger")}
  </div></section>`;
  /* 体力（老页的方块磁贴，不做环）——首屏，三格正下方（验收 2026-09-18）。 */
  html += numTiles(snap);
  /* 停止一切之后：一行「已停止 · 下一趟 HH:MM 照常」，脚注放机器的回执原文（没回执就写等着）。6 小时后不再提。 */
  const estopAt = Number(localStorage.getItem("ark-remote-estop") || 0);
  if (estopAt && now() - estopAt < 6 * 3600) {
    const rcs = Array.isArray(relay["最近指令"]) ? relay["最近指令"] : [];
    const rc = rcs.slice().reverse().find((r) => /停|estop/i.test(String(r.text || "")) || (r.at && r.at >= hhmm(estopAt)));
    html += `<section><div class="group estopnote"><div class="row"><label>已停止 · 下一趟${nextAt ? " " + nextAt : ""} 照常
      <span class="hint">${rc ? `回执 ${rc.at}：${String(rc.text || "").replace(/</g, "&lt;")}` : "等机器回执：停干净没有以回执为准"}</span></label></div></div></section>`;
  }
  /* 班次分段控件（34 屏幕时间「每周 / 每天」）：选早班还是晚班。原生 <select id="queue"> 留着不显示——wire() 的 onchange 还挂在它上面。 */
  if (qs.length) html += `<div class="segctl" id="queueseg" role="tablist" style="--n:${qs.length};--i:${Math.max(0, qs.findIndex((q) => q["名"] === curQueue))}"><i class="lens"></i>${qs.map((q) =>
      `<button type="button" role="tab" aria-selected="${q["名"] === curQueue}" class="${q["名"] === curQueue ? "on" : ""}" data-q="${q["名"]}">${q["名"]}${q["定时"] === false ? "（未启用定时）" : ""}</button>`).join("")}</div>
    <select id="queue" class="native" hidden>${qopts}</select>`;
  /* 这一趟：选中班次要跑的游戏和要点、今天跳过开关；明日安排另起一节。 */
  const plan = planRows(snap && snap.plan, qs, relay, curQueue, thisShift);
  html += plan.thisShift;
  /* 刷 4C 声骸（限时任务）；机器的两个一次性开关。 */
  html += `<section><h2>刷 4C 声骸</h2>
    ${ef["到"] ? `<div class="row"><label>改成刷到几点
        <span class="hint">提前或延后都行，填 21:00 这种。已经过了的时刻＝立刻收工</span></label>
        <input type="text" class="short" id="efnew" value="${String(ef["到"]).slice(11)}" inputmode="numeric" data-time></div>` : echoFarmBlock(relay)}
  </section>`;
  html += `<section><h2>机器</h2>
    ${RELAY_SWITCHES.filter((x) => x.tab === "状态").map((x) => relayRow(x, relay)).join("")}
  </section>${cfgNote}`;
  html += plan.tomorrow;
  /* The machine's answer to each order, newest first. Used to be a push per
     order; the answer belongs where the button was pressed (2026-09-14). */
  const rc = Array.isArray(relay["最近指令"]) ? relay["最近指令"].slice().reverse() : [];
  /* 组头右边的小字：最近一趟跑的是哪个、今天有没有失败（原来「今天跑了」磁贴里唯一有用的两项）。 */
  const td = (snap && snap["今天"]) || {};
  const tdNote = [td["最近"] ? `最近一趟 ${td["最近"]}` : "", td["失败"] ? `失败 ${td["失败"]} 趟` : ""].filter(Boolean).join(" · ");
  /* Behaviour 4 (2026-09-19): the home page shows the newest 3 and a 「查看全部 ›」 row (Health › 摘要's 「显示所有健康数据 ›」 row, AX-13
     (20,577.67,400,52) with the chevron at 387.67; row form = the page's .row.nav per AX-46) that pushes the full list grouped by day
     (Health › 显示所有数据: one group per day, AX-11 / AX-12). The relay itself keeps at most 12 (modes.RECEIPTS_KEEP). */
  const rcRow = (r) => `<div class="row"><label>${sf(r.ok ? "checkmark.circle.fill" : "xmark.circle.fill", r.ok ? "ok inl" : "bad inl")}${(r.text || "").replace(/</g,"&lt;")}</label>
      <span class="ro short">${r.at}</span></div>`;
  if (rc.length) html += `<section><h2>机器最近的回执${tdNote ? ` <small>${tdNote}</small>` : ""}</h2>` + rc.slice(0, 3).map(rcRow).join("")
    + (rc.length > 3 ? `<div class="row nav" data-page="receipts"><label>查看全部</label><span class="val">${rc.length} 条</span>${sf("chevron.right", "chev")}</div>` : "") + `</section>`;
  receiptsPage = () => {
    const days = [];
    for (const r of rc) { const d = String(r.at || "").slice(0, 5); const g = days.find((x) => x.d === d) || (days.push({ d, rows: [] }), days[days.length - 1]); g.rows.push(r); }
    const dayName = (d) => { const m = /^(\d\d)-(\d\d)$/.exec(d); return m ? `${+m[1]}月${+m[2]}日` : d; };   // 回执只带 月-日（modes.add_receipt "%m-%d %H:%M"）；日期写法照 AX-11「2026年9月17日」去掉年
    return days.map((g) => `<section><h2>${dayName(g.d)}</h2><div class="group">${g.rows.map((r) => rcRow({ ...r, at: String(r.at || "").slice(6) })).join("")}</div></section>`).join("");   // the card is written here: layoutTabs only wraps #app sections
  };

  for (const g of SCHEMA) {
    if (!inShift(g.owner)) continue;
    const M = ((snap && snap.master) || {})[g.game] || {};
    const cur = g.src === "master" ? (M.values || {}) : (c[g.sec] || {});
    const ro = M.readonly || {};
    /* 母本读不到：不摆空壳（2026-09-02 那次「一坨屎」），但也不能一声不吭地把
       整段抽掉——那看着像功能被删了。明说读不到，有上次那份就退回去用。 */
    let masterNote = "";
    let curM = cur;
    if (g.src === "master" && !Object.keys(cur).length && !Object.keys(ro).length) {
      const last = (lastGoodMaster || {})[g.game];
      if (!last || !Object.keys(last.values || {}).length) {
        html += `<section><h2>${g.title}</h2><div class="warn">${sf("exclamationmark.triangle.fill", "inl")}这一段的配置文件读不到（机器上那份母本不在或坏了），这次没法改</div></section>`;
        continue;
      }
      masterNote = `<div class="warn">${sf("exclamationmark.triangle.fill", "inl")}配置文件这次读不到——下面是上次读到的，改了要等它能读到才生效</div>`;
      curM = last.values || {};
    } else if (g.src === "master" && Object.keys(cur).length) {
      lastGoodMaster = lastGoodMaster || {};
      lastGoodMaster[g.game] = M;
      try { localStorage.setItem(LS + "-master", JSON.stringify(lastGoodMaster)); } catch {}
    }
    if (g.src === "master" && Array.isArray(M.untranslated) && M.untranslated.length) {
      masterNote += `<div class="warn">${sf("exclamationmark.triangle.fill", "inl")}有 ${M.untranslated.length} 项的名字没翻译出来（脚本这一版换了定义文件的位置），显示的是原始键名</div>`;
    }
    if (g.src === "master" && Array.isArray(M.orphans) && M.orphans.length) {
      masterNote += `<div class="warn">${sf("exclamationmark.triangle.fill", "inl")}这一版脚本的定义文件里没有这些任务，配置里却还留着：${M.orphans.join("、")}——这些设置改了不会有效果</div>`;
    }
    html += `<section><h2>${g.title}</h2>${masterNote}`;
    if (curM !== cur) Object.assign(cur, curM);
    /* 选择树：OK-WW 自己声明了「选了哪个才出现哪些子项」（sub_configs）。
       选「模拟领域」时不该还摆着「刷第几个无音区」——那是给人看的噪音。 */
    const hidden = new Set();
    if (g.game === "OK-WW") {
      const picked = cur["DailyTask.json/Which to Farm"];
      for (const [k, paths] of Object.entries(M.subs || {})) {
        if (k !== picked) for (const pth of paths) hidden.add(pth);
      }
    }
    for (const f of g.fields) {
      if (hidden.has(f.path)) continue;
      const id = `${g.src}|${g.game || g.script}|${f.path}`;
      const val = g.src === "master"
        ? (f.path in cur ? cur[f.path] : ro[f.path])
        : cur[f.key];
      if (val === undefined) continue;   // 机器上没有这一项就别画
      liveVals[id] = val;
      /* f.choices 是我们自己核对出来的取值表（无音区那种：机器只存序号，
         它自己不知道对应什么）。有就优先用它，机器发来的选项表兜底。 */
      const live = f.choices || (g.src === "master"
        ? (M.options || {})[f.path]
        : (((snap && snap.options) || {})[g.script] || {})[f.path]);
      const label = labelOf(g, f);
      const hint = f.hint ? `<span class="hint">${f.hint}</span>` : "";
      const zh = (VALUE_ZH[f.path] || {})[String(val)];
      const pick = (v) => {
        const hit = (live || []).find(([, x]) => String(x) === String(v));
        return hit ? hit[0] : (zh || fmt(v));
      };
      let ctl, rowCls = "";
      if (f.ro) {
        ctl = `<span class="ro">${pick(val)}</span>`;
      } else if (f.type === "bool") {
        ctl = `<span class="sw"><input type="checkbox" data-id="${id}" ${val ? "checked" : ""}><span></span></span>`;
      } else if (f.type === "icons") {
        /* 单选（无音区：每个序号掉两个声骸套装）→ 设置的值行「套装A ＋ 套装B ›」，点开 37b 式勾选页选一个；名字进待保存清单。 */
        const hit = (f.choices || []).find(([, v]) => String(v) === String(val));
        ctl = `<span class="val" data-single="${id}">${hit ? hit[0].join(" ＋ ") : fmt(val)}</span>${sf("chevron.right", "chev")}`;
        rowCls = " nav";
      } else if (f.type === "pills") {
        /* 多选（地区 / 采集日 / 路线）→ 设置的值行「已选 N/M ›」，点开 38 式勾选页（每行一个 ✓）；iOS 没有胶囊多选。 */
        const on = new Set((Array.isArray(val) ? val : [val]).map(String));
        const opts = live || [];
        ctl = `<span class="val" data-multi="${id}">已选 ${opts.filter(([, v]) => on.has(String(v))).length}/${opts.length}</span>${sf("chevron.right", "chev")}`;
        rowCls = " nav";
      } else if (live && live.length) {
        ctl = `<select data-id="${id}">` + live.map(([lb, v]) =>
          `<option value="${String(v)}" ${String(val) === String(v) ? "selected" : ""}>${lb}</option>`
        ).join("") + `</select>`;
      } else {
        ctl = `<input type="${f.type}" data-id="${id}" value="${val === null ? "" : String(val)}">`;
      }
      html += `<div class="row${rowCls}" data-row="${id}"><label>${label}${hint}</label>${ctl}</div>`;
    }
    html += RELAY_SWITCHES.filter((x) => x.tab === g.game).map((x) => relayRow(x, relay)).join("");
    html += `</section>`;
  }

  /* 三个「一周一次」的东西一个形状：本周做完自动停，下周一 04:00 自动恢复。
     用户 2026-09-07：「逻辑上一致的东西就应该强统一」——手机页、中继判定、通知三处一致。 */
  const weekly = relay["周常"] || {};
  const wb = weekly["周本"] || relay["周本"] || {};
  const wg = weekly["周常乐园"] || {};
  const an = weekly["剿灭"] || {};
  const doneTag = (d, done, todo) => `<span class="ro short">${d ? done : todo}</span>`;   // 值行：值在同一行右侧（AX-46）
  if (inShift("MAA")) html += `<section><h2>明日方舟 · 周常</h2>
    <div class="row"><label>剿灭
      <span class="hint">打满本周剿灭后自动停掉，下周一 04:00 自动恢复</span></label>
      ${doneTag(an["本周已完成"], "本周已打满", "本周还没打满")}</div>
  </section>`;
  if (inShift("OK-WW")) html += `<section><h2>鸣潮 · 周常</h2>
    <div class="row"><label>周常乐园
      <span class="hint">不花体力。做完就停到下周一</span></label>
      ${doneTag(wg["本周已完成"], "本周已完成", "本周还没做")}</div>
    <div class="row"><label>周本 <small>战歌重奏</small>
      <span class="hint">花体力。一周领 3 次奖励、每次 60 结晶波片、固定打 90 级，领满就停到下周一</span></label>
      ${doneTag(wb["本周已打"], "本周已领满", "本周还没领满")}</div>
    <div class="row" data-row="wb|OK-WW|第几个周本"><label>周本打第几个
      <span class="hint">游戏里按 F2 打开周本列表，从上往下数，第一个填 1。新 Boss 上线顺序会变，换本时记得来改</span></label>
      <input type="number" data-id="wb|OK-WW|第几个周本" id="wb-idx" value="${wb["第几个周本"] || 1}"></div>
  </section>`;

  html += `<section><h2>这台手机</h2>
    <div class="acts"><button id="mklink">复制免输入链接</button></div>
    <p class="foot">把这条链接存成书签或加到主屏幕，以后打开就直接是控制台，
      再也不用填信箱和 PIN。链接里带着这两样，别转发给别人</p>
  </section>
  <section><h2>游戏账号</h2>
    <div class="row"><label>已配置<span class="hint">体力数字由这台手机直接问森空岛和库街区，密钥只存在这台手机里</span></label>
      <span class="ro short">${(window.Stamina && Stamina.status()) || "没有"}</span></div>
    <div class="acts"><button id="tokpaste">粘贴密钥串</button>${(window.Stamina && Stamina.status()) ? `<button class="danger" id="tokclear">清除密钥</button>` : ""}</div>
    <p class="foot">免输入链接会把这里存着的密钥一起带上，换手机开一次那条链接就全有。森空岛的会话由机器交过来；库街区的：打开电脑上 scripts/mac/phone-link.py 打出来的链接，或把 ~/.config/ark/.env 里 KUROBBS_TOKEN 和 KUROBBS_DID 那两行粘贴进来</p>
  </section>`;

  /* The segmented control survives a re-render (patch 02, seg-impl-review.md #2; B2-b): commit() → render() used to rebuild #app wholesale,
     which destroyed the pressed label mid-transition and gave the weight cross-fade no start value. Moving the old node into the new tree
     (replaceWith) was not enough: a detached-and-reinserted element loses its running CSS transitions (the drag-release snapped to 198×28 at
     up + 1 ms, 4317ecd). Now the old #queueseg is never detached — replaceKeeping swaps everything around its ancestor chain — and only its
     state is synced (segSync): the lens, the labels, the copies and the running glass fall keep their elements AND their transitions. */
  const oldSeg = $("#queueseg"), probe = document.createElement("template"); probe.innerHTML = html;
  const cand = probe.content.querySelector("#queueseg");
  const tR = performance.now(), before = flipPending ? flipSnapshot($("#app")) : null; flipPending = false;   // B3: where every block was, before the content changes
  if (before) segMeasure("seg:render:snapshot", tR);
  flipStop();   // a render during a running content transition (a new value change or a data refresh) ends it — 快速连点 未量, wired as "the new change interrupts the old"
  const tD = performance.now();
  if (oldSeg && cand && segSameQueues(oldSeg, cand)) { const fresh = replaceKeeping($("#app"), html, oldSeg); if (fresh) segSync(oldSeg, fresh); }
  else $("#app").innerHTML = html;
  if (before) segMeasure("seg:render:dom", tD);
  const tL = performance.now(); layoutTabs(); if (before) segMeasure("seg:render:layoutTabs", tL);   // the other tabs' sections are hidden here — the "after" positions are read only after that
  const tF = performance.now(); if (before) { flipRun(before, $("#app")); segMeasure("seg:render:flip", tF); }
  const tW = performance.now(); wire(); if (before) { segMeasure("seg:render:wire", tW); segMeasure("seg:render:total", tR); }
}

/* B3 — content transition on a value change (remote-ref/seg-value-change-content.md, 设置 › 屏幕使用时间 每周/每天, iOS 27.0 simulator recordings; every
   number below is a sampled per-frame value from that document — the CAAnimation durations / curves could not be read there, §5):
   §0/§4: at the frame the value changes the card content is simply the new content (no fade, no slide, numbers do not roll); only rows that
   appear or disappear animate, UITableView-style — a deleted row fades in place (.72 → .52 → .35 → .21 → .10 → .04 → 0 by +240 ms, drifting up
   1–4 pt) while the content below slides up by its height (133 pt there) from ~+60 ms over ~300 ms (133 → 111 @75 → 88 @92 → 70 @108 → 54 @128 →
   42 @142 → 32 @160 → 24 @177 → 14 @210 → 8 @243 → 4 @277 → 2 @308 → 1 @342 → 0 @400); an inserted row waits ~100 ms then fades in over ~300 ms
   (old-content share a: .66 @0, .69 @40, .65 @90, .56 @140, .39 @190, .24 @240, .10 @290, .03 @340, 0 @390) while the content below slides down at
   once (−133 @0 → −129 @40 → −72 @74 → −43 @107 → −6 @144 → −4 @175 → −2 @210 → −1 @245 → 0 @310). Everything starts at the value-change frame,
   together with the lens (§0 "与透镜开始滑动同一帧").
   Web: blocks = the sections of #app and the rows inside their groups, keyed by the section title, the group index and the row index (index paths,
   as the native table: a row at the same index path stays and simply shows its new content).
   Old and new positions are compared (FLIP): a block that moved gets translateY(old − new) → 0 on the up-slide (moved up) or down-slide (moved down)
   sequence scaled to its own distance ("一行高" there was 133 pt); a row whose key vanished is cloned into a fixed overlay at its old place and fades
   on the deletion sequence; a row whose key is new fades in on the insertion sequence. Curves are the sampled sequences, linearly interpolated. */
let flipPending = false, flipState = null;
const FLIP_DEL_FADE = [[0, .72], [10, .67], [27, .52], [42, .44], [57, .35], [75, .25], [92, .21], [108, .14], [128, .10], [160, .07], [193, .04], [227, .02], [243, 0]];   // §1 template registration, ms from the switch frame
const FLIP_DEL_DRIFT = [[0, 0], [27, -1], [57, -2], [92, -3], [128, -4], [243, -4]];   // §1 position of the fading row (pt)
const FLIP_UP = [[0, 0], [75, .165], [92, .338], [108, .474], [128, .594], [142, .684], [160, .759], [177, .820], [210, .895], [243, .940], [277, .970], [308, .985], [342, .992], [400, 1]];   // §0 up-slide: 1 − offset / 133
const FLIP_DOWN = [[0, 0], [40, .030], [74, .459], [107, .677], [144, .955], [175, .970], [210, .985], [245, .992], [310, 1]];   // §2 down-slide: 1 − |offset| / 133
const FLIP_INS = [[0, 0], [40, 0], [90, .015], [140, .15], [190, .41], [240, .64], [290, .85], [340, .95], [390, 1]];   // §2 inserted row: 1 − a / .66 (a = the sampled old-content share)
const FLIP_END = 420;
function flipKeys(root) {   // key → { el, top, height, kind }
  const out = new Map();
  [...root.querySelectorAll(":scope > section")].forEach((sec, si) => {
    const h2 = sec.querySelector(":scope > h2"), sk = "s:" + (h2 ? h2.textContent.trim() : "#" + si);
    const r = sec.getBoundingClientRect(); if (r.height > 0) out.set(sk, { el: sec, top: r.top, height: r.height, kind: "section" });
    [...sec.querySelectorAll(":scope > .group")].forEach((g, gi) => {
      const rows = [...g.children].filter((c) => c.classList.contains("row") || c.classList.contains("acts"));
      rows.forEach((row, ri) => {   // rows keyed by index path (section, group, row) like the native table: same index = the row stays and shows its new content in one frame
        const rr = row.getBoundingClientRect(); if (rr.height > 0) out.set(`${sk}/g${gi}/#${ri}`, { el: row, top: rr.top, left: rr.left, width: rr.width, height: rr.height, kind: "row", sec: sk }); });
    });
  });
  return out;
}
function flipSnapshot(root) { const m = flipKeys(root); for (const v of m.values()) if (v.kind === "row") v.clone = v.el.cloneNode(true); return m; }
function flipStop() {
  if (!flipState) return;
  cancelAnimationFrame(flipState.raf);
  for (const b of flipState.moves) if (b.el.isConnected) b.el.style.transform = "";
  for (const b of flipState.ins) if (b.el.isConnected) b.el.style.opacity = "";
  flipState.overlay.remove(); flipState = null;
}
function flipRun(before, root) {
  const after = flipKeys(root), moves = [], ins = [], dels = [];
  const secD = new Map();
  for (const [k, n] of after) { const o = before.get(k); if (!o) { if (n.kind === "row") ins.push(n); continue; } const d = o.top - n.top;
    if (n.kind === "section") { secD.set(k, d); if (Math.abs(d) >= 0.5) moves.push({ el: n.el, d }); }
    else { const rel = d - (secD.get(n.sec) || 0); if (Math.abs(rel) >= 0.5) moves.push({ el: n.el, d: rel }); } }   // a row moves only by what its section's move does not already carry
  for (const [k, o] of before) if (!after.has(k) && o.kind === "row") dels.push(o);
  if (!moves.length && !ins.length && !dels.length) return;
  const overlay = document.createElement("div"); overlay.className = "flipgone-wrap";
  for (const d of dels) { const g = document.createElement("div"); g.className = "group flipgone"; g.style.cssText = `left:${d.left}px;top:${d.top}px;width:${d.width}px;height:${d.height}px`; g.appendChild(d.clone); overlay.appendChild(g); d.node = g; }
  document.body.appendChild(overlay);
  const t0 = performance.now(); flipState = { raf: 0, moves, ins, overlay };
  const step = (now) => {
    if (flipState === null || flipState.overlay !== overlay) return;
    const t = now - t0;
    for (const b of moves) { if (!b.el.isConnected) continue; const p = tabAt(b.d > 0 ? FLIP_UP : FLIP_DOWN, t); b.el.style.transform = t >= FLIP_END ? "" : `translateY(${(b.d * (1 - p)).toFixed(2)}px)`; }
    for (const b of ins) { if (!b.el.isConnected) continue; b.el.style.opacity = t >= FLIP_END ? "" : tabAt(FLIP_INS, t).toFixed(3); }
    for (const d of dels) { d.node.style.opacity = tabAt(FLIP_DEL_FADE, t).toFixed(3); d.node.style.transform = `translateY(${tabAt(FLIP_DEL_DRIFT, t).toFixed(2)}px)`; }
    if (t >= FLIP_END) { flipStop(); return; }
    flipState.raf = requestAnimationFrame(step);
  };
  step(t0);   // the first frame at the switch itself (.72, +H)
}

/* Replace `root`'s content with `html` while keeping `keep` (a descendant of root) attached: at every level of its ancestor chain the siblings are
   swapped for the new markup's and the ancestor's attributes are refreshed from its counterpart (same child-index path), but neither the ancestors
   nor `keep` are ever removed — so the CSS transitions / animations running inside `keep` go on (CSS Transitions §3: a transition on an element
   that leaves the document is cancelled; Chrome does so even for a same-task re-insertion). Returns the (detached) new counterpart of `keep` for
   state sync, or null after a plain innerHTML swap when the structure around it changed. */
function replaceKeeping(root, html, keep) {
  const tpl = document.createElement("template"); tpl.innerHTML = html;
  const fresh = keep.id ? tpl.content.querySelector("#" + keep.id) : null;
  const pathOf = (node, top) => { const p = []; for (let n = node; n && n !== top; n = n.parentNode) p.unshift(n); return p; };
  const oldPath = pathOf(keep, root), newPath = fresh ? pathOf(fresh, tpl.content) : [];
  if (!fresh || oldPath.length !== newPath.length || !oldPath.length || oldPath[0].parentNode !== root) { root.innerHTML = html; return null; }
  let oc = root, nc = tpl.content;
  for (let i = 0; i < oldPath.length; i++) {
    const oa = oldPath[i], na = newPath[i];
    for (const k of [...oc.childNodes]) if (k !== oa) k.remove();
    const kids = [...nc.childNodes], at = kids.indexOf(na);
    for (let j = 0; j < at; j++) oc.insertBefore(kids[j], oa);
    for (let j = at + 1; j < kids.length; j++) oc.appendChild(kids[j]);
    if (oa !== keep) { for (const a of [...oa.attributes]) if (!na.hasAttribute(a.name)) oa.removeAttribute(a.name); for (const a of na.attributes) oa.setAttribute(a.name, a.value); }
    oc = oa; nc = na;
  }
  return fresh;
}
/* The two controls describe the same queues (same names, same order, same 未启用定时 tags) — only then is the old node kept. */
function segSameQueues(a, b) {
  const key = (seg) => [...seg.querySelectorAll("button")].map((x) => x.dataset.q + "|" + x.textContent).join("\u0001");
  return key(a) === key(b) && a.style.getPropertyValue("--n") === b.style.getPropertyValue("--n");
}
/* Bring the kept control to the freshly rendered state: --i and the selected label (aria/.on) from the new markup.
   A changed --i on the same lens element is a CSS transition from wherever the lens visually is right now (mid-flight included:
   rapid taps change direction, spec §1 G12/G13); the pressed label's .dim was already removed by attachSegmented's `end`, so its
   opacity runs .2 → 1 over --ios-touch-segment-undim-duration on the same element, and .on moving between the same two buttons
   gives the weight transition its start and end values. The commit stretch (.spring) restarts when the value changed. */
function segSync(seg, fresh) {
  const lens = seg.querySelector(".lens"), to = fresh.style.getPropertyValue("--i"), from = seg.style.getPropertyValue("--i");
  if (seg.__gl) { const onIdx = [...fresh.querySelectorAll("button")].findIndex((b) => b.classList.contains("on")), gs = seg.__gl.gs;
    if (gs.futureOn != null && gs.futureOn === onIdx) gs.futureOn = null;   // the textures were drawn for this selection at the down — no upload in the lift's frame
    else { gs.futureOn = null; requestAnimationFrame(() => segGlRedraw(seg)); } }   // WebGL: the labels' weight / the selection changed under the lens (README §0.8.7 step 4)
  const freshBs = [...fresh.querySelectorAll("button")];
  [...seg.querySelectorAll("button")].forEach((b, i) => {
    const on = freshBs[i] && freshBs[i].classList.contains("on");
    b.classList.toggle("on", !!on); b.setAttribute("aria-selected", on ? "true" : "false");
  });
  if (lens && to !== "" && Math.abs(parseFloat(to) - parseFloat(from)) > 0.001) {
    if (segCommitMode === "tap" && seg.__lensLoop && !seg.__lensLoop.state.done) {
      lens.classList.remove("spring");   // 点按外观: the segLens tap chain (SEG_TAP_T) drives the lens — glass lift in place, glass slide on the value-change spring, fall; no CSS keyframe slide
    } else if (segCommitMode === "tap") {
      lens.classList.remove("spring"); void lens.offsetWidth;   // restart the stretch keyframes when a previous commit's are still running (keyboard / click path without the loop)
      lens.classList.add("spring");                             // measured x path + width/height stretch (spec §1 G1/G3, --ios-touch-segment-lens-*-keys)
    } else {
      lens.classList.remove("spring");   // patch 03 (seg-impl-review.md #3): after a lifted drag the native lens only falls back 220×44 → 196×28 (.25 s, the .lift removal)
    }                                    // and glides to the target on the plain response .4 / ζ .85 spring (--ios-motion-lens-*) — no tap stretch (interaction-spec §1 G4/G21)
    seg.style.setProperty("--i", to);
    segCommitMode = "tap";
  } else if (lens && lens.classList.contains("spring") && performance.now() - segCommitAt >= SEG_SETTLE_MS) {
    lens.classList.remove("spring");   // a heartbeat / snapshot render after the lens settled: back to the resting transition (accept: 重画时透镜不动)
  }
}
let segCommitAt = -Infinity;   // performance.now() of the last value change through the control
let segCommitMode = "tap";     // "tap" (pressed an unselected segment / keyboard) or "drag" (lifted the selected one and released elsewhere)
const SEG_SETTLE_MS = 1209;    // the measured lens sequence ends at 1209 ms (--ios-touch-segment-lens-*-keys / --seg-settle)

/* 分页：按卡片标题归到「状态 / 方舟 / 终末地 / 鸣潮 / 周常 / 手机」，一次只显示
   一页；上次看的那页记住。所有卡片都照常渲染，只是藏起来——待保存的改动和回执
   在别的页上也照常记着。用户 2026-09-14：「太长了……我要找某一个功能去修改，
   我要滑到最底下或者滑到某个中间段」。 */
/* Tab icons. 状态 and 手机: Apple's SF Symbols (gauge.with.dots.needle.67percent,
   iphone) rendered from the system font by scripts/mac/sf-symbols-export.swift and
   used as CSS masks. The three games: the projects' own icons from their GitHub
   repositories (MAA newlogo.ico, MaaEnd MaaEnd-Tiny-512.png, OK-WW icons/icon.png),
   shown in colour (the user, 2026-09-14: 「用 github 上面他们项目的图标」). */
const TAB_ICONS = {"状态": "data:image/png;base64,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", "手机": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAFgAAABoCAYAAAB17zeZAAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAAEgAAAAAQAAASAAAAABAAKgAgAEAAAAAQAAAFigAwAEAAAAAQAAAGgAAAAAJFpbTQAAAAlwSFlzAAAsSwAALEsBpT2WqQAABHdJREFUeAHtnbmLFEEUxtf72PW+Fg8QMVgVRFZQMRAXRRQDDTQQRPdfMFpQzMTIIxBjwcRAMVhFE4/FIzDbRBEVBQ1WvFZd8F71+8SBCbpqqqfr0dXD9+Bj23rVr1795k11jUFXW5tMBERABERABERABEQgQQJjDHNqR+xt0BZoA7QY6oDGQmXZHwz8FRqCBqEb0HXoDVQZI9gj0FuIE0pd35DjWWgRlLx1IcOHUOpQs/J7h7y3p0x4FZL7WFG4NeC/kf/eFCHPRlIvKg63BvkL5tGdGuRTLQK3Bvl+LMAxdhELkcxzaFJgUnyojAb2jdmNc52aI+BO9L2Wo39m1/GZrfka96G7Dy7XtYvQAPQaKgMuhv1n3CJyOVsLHYCmQS7rhaMw4BgVzCR2OLIkzD7oicNfZvMsDH4CmudI4j3a5zp8wc0xNv3cPbjsPBwpwmW+w9BpXjhsDto7Hb7g5hhLxALPaHc8PpdrHRwHIW78Q79hhNUPXYbyGPfsn6AZjpvmo53LWtMWo4Jd6+9PZMWvWR5bjs6HoSUQcyPgEHFd7YXy/lDgruEx5LLJLkdoewzArrE+uxye9k3wFcmpxxPb5RpxOdAe+g1yhigyGWfQ/w5WR14rmk9hIHkTbtS/6IQaxc/rv4cbmvlgauPcrV2k8jc1wFwP+WT/kBMQf7xcgq7mvM+8e4xdROwkBxCQmgKFFAArnv/HW6TycbuNpQi4NlNCq7yFVEjlJ1nmBATYmL4AC7AxAePwqmABNiZgHF4VLMDGBIzDq4IF2JiAcXhVsAAbEzAOrwoWYGMCxuFVwQJsTMA4vCpYgI0JGIdXBQuwMQHj8KpgATYmYBxeFSzAxgSMw6uCBdiYgHF4VbAAGxMwDq8KFmBjAsbhVcECbEzAOLwqWICNCRiHVwULsDEB4/CqYAE2JmAcXhUswMYEjMOrggXYmIBxeFWwABsTMA6vChZgYwLG4VXBAmxMwDi8KliAjQkYh1cFC7AxAePwqmABNiZgHF4VLMDGBIzDq4IF2JiAcfiUXq04EXMdF2G+fIclXxaahKUAmEcvHIVWQrHe/8tjc45Dz6BSLYU1eDMI8EX7seASKE8PSOLIHEvArhfPE0C9/aj/R8Tr74GxOjz9Cr8yN8YSwYlkvSh/Atp5VEKjF+UPoM9qqBviPUWNUF5CFwIDdXn6hX5IzhAxAPOwO54akGUb0Xgly1HX9gvXPAupDFuBQWd6BubcClmMJeKRJ4Ne+JZ5/GW6uIQd8iQwDN+Qxx/kigH4lmckfuVPQnsgHmgS80GGcE0ZwfZAZ6BOT4TbHl+wK8aEuTxwO8R9bCMbRQeer8G/Zdh0DBqSJ3PbBfXzIgVjNfDh0ip6kALU+hx4otWrFgHMX4Hr6yeXyvUaJDICVb2K96cCNCsP7mefVhQyD3zdnTWp1Nr4IDkGMeEqVDNPDTsHLYWiW4xdhCspbod4LuZWiGsadxvtUIytIcI0ZfzAeQAK97eD0E2Ix/Pw+SETAREQAREQAREQgYQI/AXTUETyJ+l9oQAAAABJRU5ErkJggg=="};
const TAB_IMAGES = {"方舟": "data:image/png;base64,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", "终末地": "data:image/png;base64,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", "鸣潮": "data:image/png;base64,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"};
const TABS = [["状态", /^机器状态|^第一次使用|^机器最近的回执/], ["方舟", /^明日方舟/], ["终末地", /^终末地/],
              ["鸣潮", /^鸣潮/], ["手机", /^这台手机|^游戏账号/]];
let curTab = (() => { try { return localStorage.getItem("ark-remote-tab") || "状态"; } catch { return "状态"; } })();

function layoutTabs() {
  const secs = [...document.querySelectorAll("#app > section")];
  const present = new Set();
  for (const sec of secs) {
    const title = ((sec.querySelector("h2") || {}).textContent || "").trim();
    const hit = TABS.find(([, re]) => re.test(title));
    sec.dataset.tab = hit ? hit[0] : "状态";
    present.add(sec.dataset.tab);
    /* iOS grouped list: the title sits above the card as a small grey header,
       the rows live inside one inset card. */
    if (!sec.querySelector(":scope > .group")) {
      const g = document.createElement("div");
      g.className = "group";
      for (const child of [...sec.children]) if (child.tagName !== "H2" && !child.classList.contains("foot")) g.appendChild(child);
      const firstFoot = sec.querySelector(":scope > .foot");
      if (firstFoot) sec.insertBefore(g, firstFoot); else sec.appendChild(g);
    }
    // A header with nothing under it is not a group (a game whose config has no
    // rows this time); Settings never shows an empty card.
    const group = sec.querySelector(":scope > .group");
    if (!group.children.length) sec.dataset.empty = "1";
    /* Settings explains a setting in a footer under the card, not inside the row
       (Settings › Accessibility › Motion, measured on the simulator 2026-09-14).
       Each row's hint moves to the group's footer, prefixed by the row's name when
       the card has more than one row. */
    if (!sec.querySelector(":scope > .foot")) {
      const hints = [...group.querySelectorAll(":scope > .row > label > .hint")];
      if (hints.length) {
        const foot = document.createElement("div");
        foot.className = "foot";
        const rows = group.querySelectorAll(":scope > .row").length;
        for (const h of hints) {
          const label = h.parentElement;
          const title = [...label.childNodes].filter((n) => n !== h && !(n.tagName === "SMALL"))
            .map((n) => n.textContent).join("").trim();
          const p = document.createElement("p");
          p.textContent = (rows > 1 && title ? title + "：" : "") + h.textContent.trim();
          foot.appendChild(p);
          h.remove();
        }
        sec.appendChild(foot);
      }
    }
  }
  if (!present.has(curTab)) curTab = "状态";
  for (const sec of secs) sec.hidden = sec.dataset.tab !== curTab || sec.dataset.empty === "1";
  for (const el of document.querySelectorAll("#app > .segctl")) el.hidden = curTab !== "状态";   // 班次分段只在「状态」首页（验收 2026-09-18）；其他页照旧用 curQueue
  const nav = $("#tabs");
  nav.hidden = present.size < 2;
  /* platter, lens and buttons are siblings (index.html: a lens nested in the backdrop-filtered platter cannot filter it).
     The nav's DOM is rebuilt only when the SET of tabs changes; otherwise the nodes stay (only .on is toggled and the glide re-placed) — every render
     used to recreate the platter's backdrop-filter layer, the glide and the buttons, so the value flip's render at a segment tap (c3c1e58, in the
     tap's own frame) recreated the whole bottom capsule under the finger (监督局 19:3x: "底部标签胶囊往下闪一下" on the phone). */
  const wantTabs = TABS.filter(([t]) => present.has(t)).map(([t]) => t), haveTabs = [...nav.querySelectorAll(".seg > button")].map((b) => b.dataset.tab);
  if (wantTabs.join("|") !== haveTabs.join("|") || !nav.querySelector(".plat") || !nav.querySelector(".glide")) {
    nav.innerHTML = `<div class="plat"></div><i class="glide"></i><div class="seg">` + wantTabs.map((t) =>
      `<button type="button" class="${t === curTab ? "on" : ""}" data-tab="${t}" aria-label="${t}">` +
      `<span class="ico">` + (TAB_IMAGES[t] ? `<img class="tabimg" src="${TAB_IMAGES[t]}" alt="">`
                     : `<i class="sf" style="-webkit-mask-image:url(${TAB_ICONS[t]});mask-image:url(${TAB_ICONS[t]})" aria-hidden="true"></i>`) + `</span>` +
      `<span>${t}</span></button>`).join("") + `</div>`;
  } else for (const x of nav.querySelectorAll(".seg > button")) x.classList.toggle("on", x.dataset.tab === curTab);
  const glide = (animate) => {
    /* The selection capsule slides to the chosen tab (the Liquid Glass tab bar's
       own motion); brief, and off under Reduce Motion (HIG: Motion). On a
       (re)render it is placed without motion - otherwise every state refresh
       replayed the slide from the left edge. */
    const on = nav.querySelector("button.on"), g = nav.querySelector(".glide");
    if (!on || !g) return;
    if (!animate) g.style.transition = "none";
    g.style.left = on.offsetLeft + "px"; g.style.width = on.offsetWidth + "px";
    if (!animate) { void g.offsetWidth; g.style.transition = ""; }
  };
  glide(false);
  requestAnimationFrame(() => glide(false));
  const selectTab = (b) => {
    /* Behaviour 3: each tab keeps its own scroll position — UITabBarController keeps every tab's view controller alive, HIG Tab bars:
       “preserving the current navigation state within each section”; Health measured: switch away and back = 0 px difference
       (remote-ref/tabscroll/README.md §1). Tapping the selected tab scrolls to the top instead (attachTabBar → springToTop). */
    tabScroll[curTab] = window.scrollY;
    curTab = b.dataset.tab;
    try { localStorage.setItem("ark-remote-tab", curTab); } catch {}
    for (const sec of document.querySelectorAll("#app > section")) sec.hidden = sec.dataset.tab !== curTab || sec.dataset.empty === "1";
    for (const el of document.querySelectorAll("#app > .segctl")) el.hidden = curTab !== "状态";
    for (const x of nav.querySelectorAll("button")) x.classList.toggle("on", x.dataset.tab === curTab);
    glide(true);
    window.scrollTo(0, tabScroll[curTab] || 0);
  };
  attachTabBar(nav, selectTab);
}

let receiptsPage = null;   // Behaviour 4: builder for the pushed receipts page (set by render)
/* A pushed page (UINavigationController push): title in the nav bar, back button pops. index.html .page for the geometry / motion sources. */
function openPage(title, html) {
  const pg = $("#subpage"); if (!pg) return;
  pg.querySelector(".ptitle").textContent = title; pg.querySelector(".pbody").innerHTML = html;
  pg.classList.remove("out"); pg.hidden = false; pg.scrollTop = 0; void pg.offsetWidth;
  pg.classList.add("in"); document.body.classList.add("pushed");
  const back = () => {
    pg.classList.add("out"); pg.classList.remove("in"); document.body.classList.remove("pushed");
    const ms = parseFloat(getComputedStyle(pg).getPropertyValue("--ios-motion-nav-pop-duration")) * 1000 || 350;
    setTimeout(() => { if (!pg.classList.contains("in")) { pg.hidden = true; pg.classList.remove("out"); } }, ms);
  };
  pg.querySelector(".pback").onclick = back;
  return back;
}
function wire() {
  for (const el of document.querySelectorAll('.row.nav[data-page="receipts"]')) el.onclick = () => { if (receiptsPage) openPage("回执", receiptsPage()); };
  // 必须包一层：`onclick = ping` 会把**鼠标事件对象**当成 minAt 传进去，
  // 于是 `s.at >= floor` 变成「数字 >= 事件对象」，永远为假——
  // 机器明明开着也判成关机。2026-08-31 我加 minAt 参数时就这么弄坏过一次。
  $("#refresh").onclick = () => ping();
  const theQueue = () => curQueue || "早班";
  const qsel = $("#queue");
  /* 分段控件照 UISegmentedControl：抬手那一刻选中同步生效、内容立刻切（不等透镜动画、不等任何异步；SEG_VC_NOW 换值即抬手），
     透镜靠 CSS 过渡自己滑过去（render() 里接力）；按住可以横着滑，抬手时手指在哪段就选哪段。
     2026-09-18 用户线上抓到的 bug：原先 click 后 setTimeout(0.55 s) 才派 change，快速交替点时
     旧 <select> 的定时器带着过期值回来重画，看起来像点击被吞。 */
  const segEl = $("#queueseg");
  if (segEl && qsel) {
    const bs = [...segEl.querySelectorAll("button")];
    attachSegmented(segEl, () => Math.max(0, bs.findIndex((b) => b.dataset.q === qsel.value)), (i, mode = "tap") => {
      const q = bs[i].dataset.q; if (qsel.value === q) return;
      qsel.value = q;   // the model changes at the up (the next touch already sees the new index)
      /* valueChanged — the content switch (one render) and, in the loop, the lens's slide. A tap: in the up's own task (SEG_VC_NOW, 换值即抬手 — the +66 ms
         timer of seg-value-change-content.md §0 put the phone's visible switch at up +136…143 against the native's +50…92, data 78284dd; ?vcnow=0 = the
         timer + vcsplit path). A slide's up: +25 ms (--seg-commit-delay-drag, tokens.css --ios-touch-segment-commit-delay note). A newer value change
         before a timer fires simply renders again (快速连点 未量). */
      const begin = () => { segCommitAt = performance.now(); segCommitMode = mode; flipPending = true; performance.mark("seg:commit"); };
      const select = () => { bs.forEach((b, k) => { b.classList.toggle("on", k === i); b.setAttribute("aria-selected", k === i ? "true" : "false"); }); segMeasure("seg:commit-select", segCommitAt); };   // the selection state (labels .on / aria; the lens is the loop's)
      const content = () => { const tR = performance.now(); performance.mark("seg:commit-render-start"); qsel.dispatchEvent(new Event("change")); segMeasure("seg:commit-render", tR); };   // the content render (segSync keeps the control)
      if (SEG_VC_NOW && mode !== "drag") { begin(); select(); content(); return; }   // 换值即抬手: selection + content now, one frame — the frames until the lift (up +82) carry the render, not the lift's
      const delay = touchMs(mode === "drag" ? "--seg-commit-delay-drag" : "--seg-commit-delay-tap", 0);
      setTimeout(() => { if (qsel.value !== q) return; begin();
        if (SEG_VC_SPLIT) { select(); requestAnimationFrame(() => { if (qsel.value !== q) return; content(); }); }   // 换值重画不阻塞 (监督局 09-19): this frame the selection only, the content render next frame
        else { qsel.dispatchEvent(new Event("change")); segMeasure("seg:commit-render", segCommitAt); } }, delay);
    });
  }
  if (qsel) qsel.onchange = () => {
    curQueue = qsel.value;
    try { localStorage.setItem("ark-remote-cfg-queue", curQueue); } catch {}
    const keep = { ...edits };
    render(); edits = keep; updateBar();
    for (const k of Object.keys(edits)) {
      const r = document.querySelector(`[data-row="${CSS.escape(k)}"]`);
      if (r) r.classList.add("changed");
    }
  };
  // 这是页面上唯一会真花掉理智/波片的按钮，却一直是单击直发——而无损的
  // 红按钮反倒有确认框，两边的防护装反了。后端把 run_now 归进「要人确认」，
  // 页面不该替人把 confirmed:true 填好。另外正在跑的时候派一趟等于让 AUTO-MAS
  // 和手动派发打架（09-01 上午三个游戏同时在线就是这么来的），先拦下。
  $("#runnow").onclick = async () => {
    const busy = ((snap && snap.run) || {})["在跑的"] || [];
    if (busy.length) {
      toast(`现在正在跑 ${busy.join("、")}，跑完再派。硬要派会和它打架。`, 5000);
      return;
    }
    if (!(await ask("现在跑一趟？", `让「${theQueue()}」现在多跑一趟。会真的花掉理智／波片；机器关着就变成下次开机跑。`, "跑一趟"))) return;
    oneShot(
      { action:"run_now", confirmed:true, queue:theQueue() },
      `已让「${theQueue()}」现在开跑。机器关着时这条会等到下次开机才执行，` +
      "那时候它本来也要跑，所以等于没多跑一趟");
  };
  // 刷 4C 声骸：选一个 boss、选刷到几点，中继到点自己收工并还原配置。
  // 用户 2026-09-09：「刷的时候不要按次数，而是时间来，比如说刷到北京时间八点半这种。」
  const ef = $("#echofarm");
  if (ef) ef.onclick = () => {
    const boss = Number(($("#efboss") || {}).value || 0);
    const until = (($("#efuntil") || {}).value || "").trim();
    const nm = (BOSSES.find((b) => b[0] === boss) || [])[1] || `第 ${boss} 个`;
    if (!boss || !/^\d{1,2}:\d{2}$/.test(until)) {
      toast("先选 boss，再填结束时刻（08:30 这种）", 4000); return;
    }
    if (!confirm(`刷「${nm}」到机器时间 ${until} 为止？期间脚本会一直在打，别的任务不跑。`)) return;
    oneShot({ action: "echo_farm", confirmed: true, boss, until, name: nm },
            `已让它刷「${nm}」到 ${until}。到点中继会自己收工并把配置还原`);
  };
  /* HH:MM inputs (刷到几点 / 改成刷到几点, data-time): anything else rolls back to the last valid value with a toast — 数据 181053 ⑤2: 08:930 was accepted */
  for (const el of document.querySelectorAll("input[data-time]")) { el.dataset.last = el.value; el.onchange = () => { const t = timeHHMM(el.value); if (t) { el.value = t; el.dataset.last = t; } else { toast("时刻要填 08:30 这种（时:分）", 3000); el.value = el.dataset.last || ""; } }; }
  const efu = $("#echofarmuntil");
  if (efu) efu.onclick = () => {
    const v = timeHHMM(($("#efnew") || {}).value || "");
    if (!v) { toast("时刻要填 08:30 这种（时:分）", 3000); return; }
    if (!confirm(`把收工时刻改成 ${v}（机器时间）？`)) return;
    oneShot({ action: "echo_farm_until", until: v }, "收工时刻已改");
  };
  const efs = $("#echofarmstop");
  if (efs) efs.onclick = () => {
    if (!confirm("现在收工？会关掉脚本和游戏，配置还原成你原来那份。")) return;
    oneShot({ action: "echo_farm_stop" }, "已收工，脚本和游戏都关了，配置还原");
  };
  /* 中继开关和改配置走同一条路：拨了先进「待保存」，点「保存修改」看一遍改了什么、
     再确认才寄出（2026-09-15，用户：「改动配置直接就应用了，完全没有二次确认」——
     09-14 晚把它们改成一拨就发是错的）。寄出后行下面挂「已寄出，等机器回执」。 */
  for (const el of document.querySelectorAll("[data-relay]")) el.onchange = () => {
    const sw = RELAY_SWITCHES.find((x) => x.id === el.dataset.relay) || QUEUE_SWITCHES.find((x) => x.id === el.dataset.relay);
    if (!sw) return;
    const to = el.checked, from = !!liveVals[sw.id];
    const row = el.closest(".row");
    if (to === from) { delete edits[sw.id]; if (row) row.classList.remove("changed"); }
    else { edits[sw.id] = { src: "relay", label: sw.label, from, to, body: to ? sw.on : sw.off }; if (row) row.classList.add("changed"); }
    updateBar();
  };
  $("#estop").onclick = async () => {
    if (!(await ask("停止一切？", "停掉现在在跑的：队列、脚本和游戏。不动排班、不动任何设置，下一趟照常。回执会告诉你停干净没有。", "停止", true))) return;
    try { localStorage.setItem("ark-remote-estop", String(now())); } catch {}
    await oneShot({ action:"estop", confirmed:true }, "已下令停止一切，机器上几秒内生效");
    render();
  };

  /* 周本那四项走同一个保存栏。原来它自己有一个「保存周本设置」按钮，
     和下面的「保存修改」两套并存——用户 2026-09-04 问「何意味」。
     现在它和别的设置一样进待保存清单，保存时合成一条指令发出去。 */

  const locate = (id) => {
    const i = id.indexOf("|"), j = id.indexOf("|", i + 1);
    const src = id.slice(0, i), owner = id.slice(i + 1, j), path = id.slice(j + 1);
    const g = SCHEMA.find((x) => x.src === src && (x.game || x.script) === owner
                                 && x.fields.some((y) => y.path === path));
    return { src, owner, path, g, f: g && g.fields.find((y) => y.path === path) };
  };
  const valueNow = (g, f) => g.src === "master"
    ? ((((snap && snap.master) || {})[g.game] || {}).values || {})[f.path]
    : (((snap && snap.config) || {})[g.sec] || {})[f.key];

  const note = (id, g, f, from, to) => {
    const same = JSON.stringify(from) === JSON.stringify(to);
    const row = document.querySelector(`[data-row="${CSS.escape(id)}"]`);
    if (same) { delete edits[id]; if (row) row.classList.remove("changed"); }
    else {
      edits[id] = { label:`${g.title} · ${labelOf(g, f)}`,
                    src:g.src, owner:g.game || g.script, path:f.path, from, to };
      if (row) row.classList.add("changed");
    }
    updateBar();
  };

  const tp = $("#tokpaste");
  if (tp) tp.onclick = async () => {
    const s = prompt("把 KUROBBS_TOKEN=… 和 KUROBBS_DID=… 两行粘贴到这里：");
    if (!s) return;
    try { Stamina.fromPaste(s); toast("密钥已存到这台手机"); await Stamina.refresh(true); render(); }
    catch (e) { toast("没存：" + e.message, 5000); }
  };
  const tc = $("#tokclear");
  if (tc) tc.onclick = () => { if (confirm("清除这台手机里的游戏密钥？体力数字会消失。")) { Stamina.clear(); render(); } };
  const mk = $("#mklink");
  if (mk) mk.onclick = async () => {
    const url = myLink();
    try { await navigator.clipboard.writeText(url); toast("链接已复制。存成书签或加到主屏幕就不用再填了"); }
    catch { prompt("长按复制这条链接：", url); }
  };

  for (const el of document.querySelectorAll("[data-id]")) {
    el.addEventListener("change", () => {
      if (el.dataset.id.startsWith("wb|")) {
        const wbNow = ((((snap && snap.relay) || {})["周常"]) || {})["周本"] || (((snap && snap.relay) || {})["周本"]) || {};
        const from = Number(wbNow["第几个周本"] ?? 1), to = Number(el.value) || 1;
        const id = el.dataset.id;
        const row = document.querySelector(`[data-row="${CSS.escape(id)}"]`);
        if (from === to) { delete edits[id]; if (row) row.classList.remove("changed"); }
        else { edits[id] = { label:"周本 · 打第几个", src:"wb", key:"第几个周本", from, to };
               if (row) row.classList.add("changed"); }
        updateBar();
        return;
      }
      const { g, f } = locate(el.dataset.id);
      if (!g) return;
      const from = valueNow(g, f);
      let to;
      if (f.type === "bool") to = el.checked;
      else if (f.type === "number") to = el.value === "" ? null : Number(el.value);
      else to = el.value;
      /* 母本里数字有时是字符串（MaaEnd 的输入框存的就是 "5"）。
         按**现值的类型**回写，别把字符串改成数字让它对不上。 */
      if (f.type === "number" && typeof from === "string") to = String(to);
      note(el.dataset.id, g, f, from, to);
      // 「刷什么」决定下面出现哪些子项，改了就得重画一次
      if (f.path === "DailyTask.json/Which to Farm") {
        const keep = { ...edits };
        const M = ((snap && snap.master) || {})["OK-WW"] || {};
        snap = { ...snap, master: { ...snap.master,
          "OK-WW": { ...M, values: { ...(M.values || {}), [f.path]: to } } } };
        render(); edits = keep; updateBar();
        for (const k of Object.keys(edits)) {
          const r2 = document.querySelector(`[data-row="${CSS.escape(k)}"]`);
          if (r2) r2.classList.add("changed");
        }
      }
    });
  }

  /* 值行 → 勾选页（多选照 38 添加新键盘、单选照 37b 日历）：行上点一下打开，页里点行切换 ✓，右上「完成」写进待保存清单，返回 = 放弃。
     全关掉不许——MaaEnd 自己写着「若全不选则任务终止」。 */
  for (const el of document.querySelectorAll("[data-multi],[data-single]")) {
    const id = el.dataset.multi || el.dataset.single, multi = "multi" in el.dataset;
    const { g, f } = locate(id);
    if (!g) continue;
    const row = el.closest(".row");
    row.onclick = () => {
      const opts = f.choices ? f.choices.map(([names, v]) => [Array.isArray(names) ? names : [names], v])
                 : ((live_(g, f)) || []).map(([lb, v]) => [[lb], v]);
      const cur = id in edits ? edits[id].to : valueNow(g, f);
      const onSet = new Set((Array.isArray(cur) ? cur : [cur]).map(String));
      openPicker({ title: labelOf(g, f), multi, opts, on: onSet, icons: f.type === "icons" }, (nextSet) => {
        const from = valueNow(g, f);
        if (multi) {
          const order = opts.map(([, v]) => String(v));
          const next = order.filter((v) => nextSet.has(v)).map((v) => { const raw = opts.find(([, x]) => String(x) === v)[1]; return raw; });
          if (!next.length) { toast("至少要留一个，全不选的话这个任务会直接结束"); return false; }
          note(id, g, f, Array.isArray(from) ? [...from] : from, next);
        } else {
          const v = [...nextSet][0]; if (v === undefined) return false;
          const raw = opts.find(([, x]) => String(x) === v)[1];
          note(id, g, f, from, typeof raw === "number" ? raw : Number.isNaN(Number(raw)) ? raw : Number(raw));
        }
        render();
        return true;
      });
    };
  }
}
/* the option table a field draws from: our own table (f.choices) or the machine's (master options / mas options) */
function live_(g, f) {
  return f.choices || (g.src === "master"
    ? (((((snap && snap.master) || {})[g.game] || {}).options || {})[f.path])
    : (((((snap && snap.options) || {})[g.script] || {}))[f.path]));
}
/* 勾选页 = 38「添加新键盘 › 简体中文」的弹出页：表从 y 62 起、导航栏 54 在 +20（y 82）、返回圆钮 44 at x 20、完成圆钮 36 at x 380 (y 86)、
   组头空 17.67、行 53.33 文字 x 40、✓ 19×17.33 右缘距行右 22.5 = 探针 checkmark 帧 ← AX-38 */
function openPicker(spec, commit) {
  const sh = $("#picker"); if (!sh) return;
  const on = new Set(spec.on);
  sh.querySelector(".ptitle").textContent = spec.title;
  const list = sh.querySelector(".plist");
  const draw = () => {
    list.innerHTML = `<div class="group">` + spec.opts.map(([names, v]) => {
      const key = String(v), sel = on.has(key);
      const icons = spec.icons ? names.map((n) => `<img class="pico" src="${SET_ICONS[n] || ""}" alt="">`).join("") : "";
      return `<div class="row check${sel ? " on" : ""}" data-v="${key}">${icons}<label>${names.join(" ＋ ")}</label>${sf("checkmark", "ck")}</div>`;
    }).join("") + `</div>`;
    for (const r of list.querySelectorAll(".row.check")) r.onclick = () => {
      const k = r.dataset.v;
      if (spec.multi) { if (on.has(k)) on.delete(k); else on.add(k); }
      else { on.clear(); on.add(k); }
      draw();
    };
  };
  draw();
  /* Behaviour 5: present / dismiss ride the sheet spring (index.html .sheet .card / .dim transitions ← pagesheet-motion.md); the
     element stays open until the dismiss has travelled (--ios-motion-sheet-duration). */
  const close = () => {
    sh.classList.remove("in"); document.documentElement.classList.remove("sheet-open");
    const ms = parseFloat(getComputedStyle(sh).getPropertyValue("--ios-motion-sheet-duration")) * 1000 || 500;
    setTimeout(() => { if (!sh.classList.contains("in")) sh.removeAttribute("open"); }, ms);
  };
  sh.querySelector(".pback").onclick = close;
  const done = sh.querySelector(".pdone"); if (!done.firstChild) done.innerHTML = sf("checkmark");
  done.onclick = () => { if (commit(on) !== false) close(); };
  sh.setAttribute("open", ""); document.documentElement.classList.add("sheet-open");
  list.scrollTop = 0;
  void sh.offsetWidth; sh.classList.add("in");   // start from the bottom (translateY(100%)), then travel up on the spring
}

function locateGlobal(id) {
  const i = id.indexOf("|"), j = id.indexOf("|", i + 1);
  const src = id.slice(0, i), owner = id.slice(i + 1, j), path = id.slice(j + 1);
  const g = SCHEMA.find((x) => x.src === src && (x.game || x.script) === owner && x.fields.some((y) => y.path === path));
  return { g, f: g && g.fields.find((y) => y.path === path) };
}

function applyEdits() {
  applyPending();
  for (const [key, e] of Object.entries(edits)) {
    const el = document.querySelector(`[data-id="${CSS.escape(key)}"]`);
    if (!el) continue;
    if (el.type === "checkbox") el.checked = !!e.to;
    else el.value = String(e.to);
  }
  for (const [key, e] of Object.entries(edits)) {
    const m = document.querySelector(`[data-multi="${CSS.escape(key)}"]`), s1 = document.querySelector(`[data-single="${CSS.escape(key)}"]`);
    const el = m || s1; if (!el) continue;
    const { g, f } = locateGlobal(key);
    if (g) {
      const opts = live_(g, f) || [];
      if (m) m.textContent = `已选 ${(e.to || []).length}/${opts.length}`;
      else { const hit = (f.choices || []).find(([, v]) => String(v) === String(e.to)); if (hit) s1.textContent = hit[0].join(" ＋ "); }
    }
    const row = document.querySelector(`[data-row="${CSS.escape(key)}"]`);
    if (row) row.classList.add("changed");
  }
  /* 三态第一态：改了还没保存的行，控件下一行小字「待保存」。 */
  for (const key of Object.keys(edits)) {
    const row = document.querySelector(`[data-row="${CSS.escape(key)}"]`);
    if (!row) continue;
    row.classList.add("changed");
    row.querySelectorAll(".cap.edit").forEach((x) => x.remove());
    const tag = document.createElement("div"); tag.className = "cap edit"; tag.textContent = "待保存"; row.appendChild(tag);
  }
  updateBar();
}

/* Pending edits turn the nav bar into an edit bar: ✕ 放弃 / 待保存 N 项 / ✓ 完成. */
function updateBar() {
  const n = Object.keys(edits).length, bar = $("#topbar");
  bar.classList.toggle("editing", n > 0);
  bar.querySelector("span").textContent = n ? `待保存 ${n} 项` : "游戏机遥控";
  if (!$("#save").firstChild) { $("#save").innerHTML = sf("checkmark"); $("#discard").innerHTML = sf("xmark"); }
}


function relayRow(sw, relay) {
  const v = relay[sw.key];
  const on = !!v;
  liveVals[sw.id] = on;
  const hint = on && sw.hintOn ? sw.hintOn(v) : sw.hint;
  return `<div class="row" data-row="${sw.id}"><label>${sw.label}<span class="hint">${hint}</span></label>
    <span class="sw"><input type="checkbox" data-relay="${sw.id}" ${on ? "checked" : ""}><span></span></span></div>`;
}

async function oneShot(body, okText) {
  try { await send(body); toast(okText + "（机器开着就是马上，关着就是下次开机）"); }
  catch (e) { toast("发不出去：" + e.message); }
}


function save_cache() {
  try { localStorage.setItem(LS + "-snap", JSON.stringify(snap)); } catch {}
}

/* 把内部值翻成人看的字。改动确认框必须用它——
   2026-09-01 实测：下拉里显示的是「计划表：新 MAA 计划表」，
   确认框里却甩出 `c88cfe9e-6617-4fb8-9225-183ca571e3ae`。
   那个框存在的全部意义就是让人看清改了什么，显示 UUID 等于没有。
   取名顺序和渲染下拉时完全一致：机器发来的选项表 → VALUE_ZH → 原样。 */
function valLabel(e, v) {
  if (e.src === "relay") return v ? "开" : "关";
  const live = CHOICES[e.path] || (e.src === "master"
    ? ((((snap && snap.master) || {})[e.owner] || {}).options || {})[e.path]
    : (((snap && snap.options) || {})[e.owner] || {})[e.path]);
  const one = (x) => {
    const hit = (live || []).find(([, val]) => String(val) === String(x));
    return hit ? hit[0] : ((VALUE_ZH[e.path] || {})[String(x)] || fmt(x));
  };
  return Array.isArray(v) ? (v.length ? v.map(one).join("、") : "（一个都没选）") : one(v);
}

async function doSave() {
  const items = Object.values(edits);
  if (!items.length) return;
  $("#difflist").innerHTML = items.map((e) =>
    `<div class="diff"><b>${e.label}</b><br>` +
    `<span class="old">${valLabel(e, e.from)}</span> → ` +
    `<span class="new">${valLabel(e, e.to)}</span></div>`).join("");
  $("#confirm").showModal();
}


/* 免输入链接：把信箱和 PIN 放在链接的 `#` 后面，页面读一次存下来就把它抹掉。
   为什么不直接写进代码里：这个页面挂在公开的 GitHub Pages 上、仓库也是公开的，
   写进去等于把遥控信道贴在互联网上——任何人都能按那个红色的「停止一切」。
   `#` 后面的内容浏览器不会发给服务器，也不进仓库，只存在你自己那条书签里。
   用户 2026-09-04：「把信箱和 pin 这个设计删了就行」——要删的是**每次去填**，
   这样就一次都不用填了。 */
function fromLink() {
  if (window.Stamina) Stamina.fromLink();       // #t=… 游戏密钥串，同一条链接里可以一起带
  const m = /[#&]k=([A-Za-z0-9_-]+)/.exec(location.hash || "");
  if (!m) return false;
  try {
    const j = JSON.parse(decodeURIComponent(escape(
      atob(m[1].replace(/-/g, "+").replace(/_/g, "/")))));
    if (!j.t || !j.p) return false;
    localStorage.setItem(LS, JSON.stringify({ topic: j.t, pin: String(j.p) }));
    history.replaceState(null, "", location.pathname + location.search);
    return true;
  } catch { return false; }
}

/* 免输入链接带上这台手机里存着的游戏密钥（#k=信箱和 PIN，&t=密钥），换手机打开它一次就全有了。 */
function myLink() {
  const enc = (o) => btoa(unescape(encodeURIComponent(JSON.stringify(o))))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const tok = window.Stamina ? Stamina.loadTokens() : null;
  return location.origin + location.pathname + "#k=" + enc({ t: cfg.topic, p: cfg.pin }) + (tok ? "&t=" + enc(tok) : "");
}

/* 原生行为三件：大标题滚动收进顶栏、下拉刷新、「几分钟前」自己走。 */
/* Every <select> in the page gets a button in its place that opens a menu (the
   iOS pull-down menu; numbers in index.html). The select itself stays in the DOM,
   hidden: choosing from the menu sets its value and fires `change`, so every handler
   wired to the select keeps working; on a re-render the buttons are built again. */
function dressSelects() {
  for (const sel of document.querySelectorAll("main select:not(.native)")) {
    sel.classList.add("native");
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "menubtn";
    const label = () => { const o = sel.options[sel.selectedIndex]; btn.textContent = o ? o.textContent : ""; };
    label();
    sel.addEventListener("change", label);
    btn.onclick = (ev) => { ev.stopPropagation(); openMenu(btn, sel); };
    sel.insertAdjacentElement("afterend", btn);
  }
}
function openMenu(anchor, sel) {
  closeMenu();
  const scrim = document.createElement("div"); scrim.className = "menu-scrim";
  const menu = document.createElement("div"); menu.className = "menu"; menu.setAttribute("role", "menu");
  for (const o of sel.options) {
    const b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "menuitemradio");
    if (o.selected) b.classList.add("on");
    b.innerHTML = `<i class="ck" style="-webkit-mask-image:url(${SYM["checkmark"]});mask-image:url(${SYM["checkmark"]})"></i>${o.textContent.replace(/</g, "&lt;")}`;
    b.onclick = () => { if (sel.value !== o.value) { sel.value = o.value; sel.dispatchEvent(new Event("change", { bubbles: true })); } closeMenu(); };
    menu.appendChild(b);
  }
  scrim.onclick = closeMenu;
  document.body.append(scrim, menu);
  /* Below the value, right edge on the value's right edge; above it when there is no room. */
  const r = anchor.getBoundingClientRect(), mh = menu.offsetHeight, gap = 6;
  const right = Math.max(8, innerWidth - r.right);
  menu.style.right = right + "px";
  if (r.bottom + gap + mh <= innerHeight - 8) menu.style.top = (r.bottom + gap) + "px";
  else { menu.classList.add("up"); menu.style.bottom = Math.max(8, innerHeight - r.top + gap) + "px"; }
  addEventListener("keydown", escMenu);
}
function escMenu(e) { if (e.key === "Escape") closeMenu(); }
function closeMenu() {
  for (const el of document.querySelectorAll(".menu, .menu-scrim")) el.remove();
  removeEventListener("keydown", escMenu);
}

/* ---------- 触摸交互（remote-ref/interaction-spec.md，iOS 27 注入实测；时长/余量读 tokens.css 的 --ios-touch-*） ---------- */
const touchMs = (name, fallback) => { const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim(); if (v.endsWith("ms")) return parseFloat(v); if (v.endsWith("s")) return parseFloat(v) * 1000; const n = parseFloat(v); return Number.isNaN(n) ? fallback : n; };
const touchPx = (name, fallback) => { const n = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)); return Number.isNaN(n) ? fallback : n; };
/* One press = one closure; pointerup and pointercancel both end it and remove each other, so a cancelled press never leaves a listener behind. */
function press(el, e, handlers) {
  if (e.pointerType === "mouse" && e.button !== 0) return false;
  e.preventDefault(); try { el.setPointerCapture(e.pointerId); } catch {}
  const move = (ev) => handlers.move && handlers.move(ev);
  const end = (ev, cancelled) => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", cancel); handlers.end(ev, cancelled); };
  const up = (ev) => end(ev, false), cancel = (ev) => end(ev, true);
  el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", cancel);
  return true;
}
/* §1 UISegmentedControl: touch-down changes nothing but the pressed label's opacity (unselected) or lifts the lens (selected); a lifted lens follows
   the finger; the index changes at the up - target = the segment under the finger's x - unless the finger is > 70 pt outside the control
   (cancel, no event) or back on the selected segment (no event). No debounce: every up counts, same segment twice = one event. */
/* Segmented lens — geometry, glass and follow in one per-frame loop (segLens): view.js owns the lens's inline left/top/width/height/border-radius
   from the lift to the settle. Every spring below is an ORIGINAL read off the control's UIViewSpringAnimationBehavior(Settings) objects
   (remote-ref/seg-lens-refraction.md §4.4, iOS 27.0 probe with model-value differencing, dumps tools/touch/seg-native-springs-{abc,tap}-motion.json);
   ω₀ = 2π / response, x'' = −ω₀²(x − target) − 2ζω₀x' (§4.4 换算 row). Structure = §4.4's attribution column (differential evidence):
   - lift: +109 ms after the down (--ios-touch-segment-lift-delay ← §4.1 frames) ONE spring ζ 1 / response .25 s drives bounds 196×28 → 220×44,
     corner 14 → 22, the displacement amount (filter scale 0 → 32), the platter (1 → 0), the highlight — so here q = that spring's progress and every
     lifted quantity is a function of q. The DestOut punch-out's opacity is the §4.1 frame values (--ios-touch-segment-destout-keys).
   - drag (flex-interaction.md §6, UIKitCore -[UISegmentedControl touchesMoved:] → _updateSelectionToSegment:): every move sets the lens centre
     target to the tracked segment's centre + the finger's accumulated delta since the touch down (locationInView only — no predicted / coalesced
     touches; pressed at the centre this is the finger's x), through ONE spring behaviour ζ .85 / response .2 s created anew per move and continuing
     from the current value and velocity (analytic step); the first displaced frame reaches the screen two frames after the one the move arrived in
     (§6e.2 chain; §6e.3 the page rule) — see the tick for the frame-by-frame account. The on-screen centre = this spring + the flex drift (1 − sX)·W/2 — the slow start and the
     run past the finger after it stops are that drift, not a latency constant. Beyond an END segment's own centre the excess is rubber-banded
     (§6, 0x1c41358bc–0x1c4135978, by segmentPosition 0 left / 1 middle / 2 right / 3 alone): raw = c_tracked + Σdelta; middle → raw; alone → the
     centre (no follow); left end: o = max(0, c − raw) → target = c − 12·(1 − 1/(1 + .55·o/12)); right end: o = max(0, raw − c) → c + the same
     (c .55 = [0x1c5718380], the left end's [0x1c571a4e8] = −.55 cancels the sign; d = 12 immediate — UIScrollView's rubber band, asymptote 12 pt,
     initial slope .55: 24 pt past the end centre → 6.29, 120 → 10.2). Inward of its own centre the end segment follows raw (the abc recording: the
     tracked left segment carried the lens to 320). The stretch while dragging (244×38.4, 253×36), the drift and the bounce after the up are UIKitCore's
     _UIFlexInteraction on the lens's presentation transform (flex-interaction.md; FLEX_VARIANT / flexSpec / flexIntegrator / flexTargets below);
     its "tracking" springs ζ .6533 / .4559 (dragging) and ζ .56 / .444 (196×28) are what the probe saw retargeting every frame (§4.4 row 4) — they
     drive scale / drift, not the position.
   - release: geometry back with the same ζ 1 / .25 spring (bounds, corner, position of the lifted rect), the material half — displacement,
     platter, highlight — with ζ 1 / .4 (§4.4 rows 5–6), both from up + 31 ms (§4.3 frames: first changed frame); the DestOut fade = §4.3 frame
     values (--ios-touch-segment-release-destout-*). The position: one spring ζ .85 / .4 s to the segment the lens ends on (§4.4 换值行程 row);
     the flex floats keep running (smallLoupe ζ .56 / .444 once the lens is 196×28).
   While the loop runs the lens carries `transition: none` inline (so the resting lens's CSS transitions — the tap commit's slide on --i — do not react
   to the per-frame values); at the end the inline values equal the CSS rest values and are removed. The copies (bg + track through the displacement
   map, labels), the platter and the rim are positioned to the lens's presented rect each frame. Tab-bar curves (LENS_P) stay for the tab bar. */
const LENS_P = [[0.020, 0], [0.036, .11], [0.053, .26], [0.070, .41], [0.086, .54], [0.103, .65], [0.120, .74], [0.153, .86], [0.203, .95], [0.253, .98], [0.303, .994], [0.370, 1]];
const lensP = (t) => tabAt(LENS_P, t);
function tabAt(tab, t) { if (t <= tab[0][0]) return tab[0][1]; for (let i = 1; i < tab.length; i++) if (t <= tab[i][0]) { const [t0, v0] = tab[i - 1], [t1, v1] = tab[i]; return v0 + (v1 - v0) * (t - t0) / (t1 - t0); } return tab[tab.length - 1][1]; }
/* `<ms> <value>, …` key list from a CSS custom property (seg-keys.css / tokens.css convention) → [[s, value], …]; the fallback tables below are the same
   numbers hand-copied from seg-keys.css / seg-lens-refraction §4.1 / §4.3 (used only if the stylesheet is missing) */
function cssKeys(name, fallback) {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim(); if (!raw) return fallback;
  const out = raw.split(",").map((k) => k.trim().split(/\s+/).map(Number)).filter((k) => k.length === 2 && k.every(Number.isFinite)).map(([ms, v]) => [ms / 1000, v]);
  return out.length >= 2 ? out : fallback;
}
/* §4.3 DestOut opacity after the up (1 until +198 ms, then the fade) */
const SEG_DROP_DESTOUT = [[0, 1], [.198, 1], [.215, .841], [.231, .69], [.248, .564], [.265, .46], [.281, .374], [.298, .303], [.315, .245], [.331, .197], [.348, .159], [.365, .127], [.381, .102], [.398, .082], [.415, .065], [.431, .052], [.448, .042], [.465, .033], [.481, .026], [.498, .021], [.515, .017], [.531, .013], [.548, .01], [.565, .008], [.581, .007], [.598, 0]];
/* §4.1 DestOut opacity after the lift starts (+109 ms): .396 / .98 / 1 on the first three frames */
const SEG_LIFT_DESTOUT = [[0, 0], [.016, .396], [.033, .98], [.05, 1]];
/* §4.4 springs [原值]: [ζ, response s] */
const SEG_SPRING = { lift: [1.0, .25], fallMaterial: [1.0, .4], model: [.85, .2], travel: [.85, .4] };
/* 点按 (tap on an unselected segment) schedule, s after the up [原值 seg-lens-refraction.md §4.4, the hooked tap run: calls at +171 / +181 / +187 /
   +532 / +539 from the down, the synthetic up at +89 (touch-local.uiprobe-springs-tap.json)]: lift geometry ζ1/.25 in place, lift material
   ζ1/.25, the value-change travel ζ .85/.4 (one retarget to the target centre), fall geometry ζ1/.25, fall material ζ1/.4. The unhooked frames
   (seg-native-tap-frames.json: up +62, valueChanged +148 = up +86, first displaced frame +183) put geometry + travel in the same frame. */
const SEG_TAP_T = { geo: .082, mat: .092, travel: .098, fallGeo: .082 + .22, fallMat: .082 + .22 };
/* the fall (老网页 09-19, seg-lens-refraction.md §4.4 end, 0x1c54c798c / 0x1c54c7a64–0x1c54c7bd4): `_UILiquidLensView setLifted:NO` arms an NSTimer of
   lensHangTime .22 s × dragCoefficient MINUS the time since setLifted:YES (liftTime, ivar +0x230); ≤ 0 → immediate. The tap's touchesEnded sets the
   value + lifts, then un-highlights → elapsed ≈ 0 → the full .22 s from the lift start; actuallySetLifted:NO then builds both fall animations
   (geometry ζ1/.25, material ζ1/.4) in one call. First fallen frame ≈ up + .24 … .27 (the unhooked frames read +.29); the hooked dump's +.443 was the
   slowed process. */   // position springs; the .6533/.4559 and .56/.444 tracking springs of §4.4 are the flex interaction's (FLEX_VARIANT)
/* B5 — the lens's stretch while dragging and its bounce after the up: UIKitCore `_UIFlexInteraction` (remote-ref/flex-interaction.md, the old
   page session's decompilation of the iOS 27.0 simulator UIKitCore; offsets there). Structure (§1): `_UILiquidLensView.flexInteraction`; every
   frame (UIUpdateLink 0x1c5050900) the lens's OWN presentation-layer centre goes into `_UIVelocityIntegrator addSample:` (config 0x1c504f3d8:
   5 samples, EMA α 0.3 on position / velocity / acceleration, consecutive-sample differentiation, hysteresis 0.05 s → reset, directionless
   acceleration = the component along the velocity), then `updateFlex` (0x1c5052ce8) sets scaleX / scaleY / drift targets that
   `_UIDebouncingAnimatableFloat`s reach on spec.scaleSpring (tracking values while the gesture is on) and a presentation modifier puts them on the
   transform — the model bounds stay. Spec (§2, `liquidLensWithSize:` 0x1c512710c): d = min(w, h), t = clamp((d − 37) / 33, 0, 1), every field
   linear between smallLoupe (0x1c5127b94: pts 10, min .9, max 1.1, N 2000, ζ .56 / .444, tracking the same, retargetImpulse .032) and loupe
   (0x1c5127a48: pts 100, min .75, max 1.15, N 2500, ζ 1.0 / .5, tracking .9 / .5): 220×44 → pts 29.1, [.8682, 1.1106], N 2106, ζ .653 / .456
   (tracking .632 / .456); 196×28 → smallLoupe. Per frame (§3, 0x1c5052558 / 0x1c505297c): m = a / N; per axis lo = max(min, (D − pts) / D),
   hi = min(max, (D + pts) / D); sX = clamp(lerp(1, hiX, m), loX, hiX), sY = clamp(lerp(1, loY, m), loY, hiY) (accelerating: X out, Y in);
   drift = sign(v)·(1 − sX)·W/2; the translation term (threshold 6000) is negligible here; at the END of updateFlex the hard clamp [0.9, 1.1]
   (0x1c54c53d4) on the TARGET scaleX / scaleY — the presented values are the spring floats and are not clamped (§6f.3: the native peak 253.4 =
   1.152·220 is the ζ .632 / .653 spring's overshoot past the clamped target; B5-d, §6f.4). Not read
   (§4): the retargetImpulse .032 impulse form — the recomputation peaks at 244 where the native reaches 253.5 (标「retargetImpulse 未读」).
   B5-d check (§7.3): the drift is not applied instantly — its target sign(v)·(1 − sX)·W/2 feeds the closed-form scaleSpring float (tracking
   ζ .632 / .456 while the finger is down, ζ .653 / .456 after the up: the `springStep(fl.dx, tg.drift, sp, dt)` line of the tick, since 71e89fa) and
   the presented centre = the position spring + that float (setGeo + the translateX of the presentation transform). The whole chain replayed on the
   probe's sample grid (remote-ref/tools/touch/b5c/dragsim_full.py over touch-local.uiprobe-abc.json; the position spring ζ .85 / .2 with the one-stage
   adoption above): B ramp .60–.738 s rms 1.39 / max 2.27 / signed −1.05 pt; after the last move .738–1.041 s rms 6.33 / max 10.39 / signed +5.22 (the
   same chain with the drift applied instantly 8.32 / 11.92 / −7.05 and 16.28 / 29.66 / +11.52; with no drift 1.20 / 2.92 / +.68 and 12.26 / 19.33 /
   +7.92); the peak width 242.0 against the native 253.5 is the retargetImpulse gap. The simulator run on d9ebf5f (the data session's C1 dynamic,
   standalone) read the web centre +33 (light) / +55 (dark) pt ahead of the native during the drag and +12.8 / +24.3 after the finger stopped — far
   beyond this replay; the cause is not named here — the per-tick state window.__segLens and the seg: measures exist for the re-recording. */
const FLEX_VARIANT = { smallLoupe: { pts: 10, min: .9, max: 1.1, N: 2000, zeta: .56, resp: .444, tzeta: .56, tresp: .444 }, loupe: { pts: 100, min: .75, max: 1.15, N: 2500, zeta: 1.0, resp: .5, tzeta: .9, tresp: .5 } };
/* retargetImpulse: none. 老网页 (13:3x) read liquidLensWithSize: (0x1c5126e6c) to the end — the lens spec is the smallLoupe → loupe interpolation by t for
   pts / min / max / N / ζ / response and the two tracking values (flexSpec below); the two impulse fields are NOT interpolated and take the Loupe
   default 0 (the probe getter's .032 is the SmallLoupe class default, not the lens's spec). So no Δv at a retarget; flex §7.1b's formula is recorded
   only. (Replayed for the record on the page's own C1 run with .032: peak 243.3, not 253.5, and a faster fall — b5c/dragsim_web.py imp=0.032.) */
function flexSpec(W, H) {
  const t = Math.max(0, Math.min(1, (Math.min(W, H) - 37) / 33)), a = FLEX_VARIANT.smallLoupe, b = FLEX_VARIANT.loupe, L = (x, y) => x + (y - x) * t;
  return { pts: L(a.pts, b.pts), min: L(a.min, b.min), max: L(a.max, b.max), N: L(a.N, b.N), zeta: L(a.zeta, b.zeta), resp: L(a.resp, b.resp), tzeta: L(a.tzeta, b.tzeta), tresp: L(a.tresp, b.tresp) };
}
/* _UIVelocityIntegrator with flex's configuration (1-D: the lens moves along x) */
function flexIntegrator() {
  const vi = { pf: null, vf: 0, af: 0, t: null };
  return { add(p, t) {
      if (vi.pf === null || t - vi.t > .05) { vi.pf = p; vi.vf = 0; vi.af = 0; vi.t = t; return; }   // first sample / hysteresis 0.05 s → reset
      const dt = t - vi.t; if (dt <= 0) return;
      const pf = .3 * p + .7 * vi.pf, v = (pf - vi.pf) / dt, vf = .3 * v + .7 * vi.vf, acc = (vf - vi.vf) / dt;   // EMA α .3 on position, velocity, acceleration; consecutive differentiation
      vi.af = .3 * acc + .7 * vi.af; vi.pf = pf; vi.vf = vf; vi.t = t;
    },
    get velocity() { return vi.vf; },
    get acceleration() { return Math.sign(vi.vf) * vi.af; },   // prefersDirectionlessAcceleration: the component along the velocity
  };
}
/* one updateFlex: targets from the acceleration (§3) */
function flexTargets(spec, W, H, accel, vel) {
  const m = accel / spec.N, loX = Math.max(spec.min, (W - spec.pts) / W), hiX = Math.min(spec.max, (W + spec.pts) / W), loY = Math.max(spec.min, (H - spec.pts) / H), hiY = Math.min(spec.max, (H + spec.pts) / H);
  const sX = Math.max(loX, Math.min(hiX, 1 + (hiX - 1) * m)), sY = Math.max(loY, Math.min(hiY, 1 + (loY - 1) * m));
  const hard = (q) => Math.max(.9, Math.min(1.1, q));   // updateFlex's final hard clamp on the targets (0x1c54c53d4); the drift term was formed from sX before it (§3 order)
  return { sX: hard(sX), sY: hard(sY), drift: Math.sign(vel) * (1 - sX) * W / 2 };
}
/* damped spring x'' = −ω₀²(x − target) − 2ζω₀x' (ω₀ = 2π / response) — the ANALYTIC step over dt from the current (x, v) (flex-interaction.md §6e.3:
   AnimationKit evaluates the closed-form solution, §4 0x1de3cfb00–0x1de3d4000; the old page's dragsim.py spring_step). A retarget keeps (x, v) and only
   changes `target` (§6 retarget 语义). ζ < 1: under-damped form; ζ = 1 (the lift / fall springs): critically damped form. Replaces the former 4 ms
   semi-implicit Euler (its replay on the probe grid read rms 2.58 vs 1.11 analytic, §6e.1). */
function springStep(s, target, [zeta, response], dt) {
  if (!(dt > 0)) return; const w = 2 * Math.PI / response, dx = s.x - target, v = s.v;
  if (zeta < 1) { const wd = w * Math.sqrt(1 - zeta * zeta), B = (v + zeta * w * dx) / wd, e = Math.exp(-zeta * w * dt), c = Math.cos(wd * dt), sn = Math.sin(wd * dt);
    s.x = target + e * (dx * c + B * sn); s.v = e * (-zeta * w * (dx * c + B * sn) + (-dx * wd * sn + B * wd * c)); }
  else { const e = Math.exp(-w * dt), B = v + w * dx; s.x = target + e * (dx + B * dt); s.v = e * (B - w * (dx + B * dt)); }
}
/* B6: the lifted lens's rim from the decompiled formulas (remote-ref/keyfill-highlight.md §2 / §4 / §5.1 / §5.2; parameters = the probe's set
   values, seg-lens-refraction.md §1c(g)); the drawing is in segLens (SVG ring strokes), the arithmetic is here. Depth e = pt into the capsule. */
const SEG_RIM = (() => {
  const sat = (x) => Math.max(0, Math.min(1, x)), mean = (f, a, b, n = 240) => { let s = 0; for (let i = 0; i < n; i++) s += f(a + (b - a) * (i + .5) / n); return s / n; };
  /* #36 CASDFKeyFillHighlightEffect (§2): main band h 1 curvature .75 (prof .25 + .75(1 − e)), amount .5 → bias 0; diffuse band 8·h, linear, bias 1/(.15·.5) − 2;
     spreads 1.3963 (main) / .65·1.3963 (diffuse); ang = sat((n·dir − cos s)/(1 − cos s)) */
  const HL_COS = Math.cos(1.3963), HD_COS = Math.cos(.65 * 1.3963), HD_BIAS = 1 / (.15 * .5) - 2;
  const hlMain = (e, ang = 1) => (e >= 0 && e < 1 ? (.25 + .75 * (1 - e)) * ang : 0);
  const hlDiff = (e, ang = 1) => { if (e < 0 || e >= 8) return 0; const v = (1 - e / 8) * ang; return v / (1 + HD_BIAS * (1 - v)); };
  const EDGES = [0, 1 / 3, 2 / 3, 1, 2, 3, 4, 5, 6, 7, 8];   // ring edges: 1/3 pt over the first pt, then 1 pt
  const hlRings = EDGES.slice(0, -1).map((e0, i) => ({ e0, e1: EDGES[i + 1], main: i < 3 ? mean(hlMain, e0, EDGES[i + 1]) : 0, diff: mean(hlDiff, e0, EDGES[i + 1]) }));
  const angMain = (nx) => sat((Math.sqrt(Math.max(0, 1 - nx * nx)) - HL_COS) / (1 - HL_COS));   // along the arcs n·dir = cos φ = √(1 − n_x²)
  const dFull = mean(hlDiff, 0, 1), angDiff = (nx) => { const c = sat((Math.sqrt(Math.max(0, 1 - nx * nx)) - HD_COS) / (1 - HD_COS)); return mean((e) => hlDiff(e, c), 0, 1) / dFull; };
  /* glassBackground built-in KeyFill (§5.1): Amount .5 → uniform 1/.5 − 2 = 0 (x′ = x; B6-c §1), ColorBias −.3, EffectOffset −.6667, Height 1, Angle π/2 → dir (sin θ, −cos θ) = (1, 0),
     SpreadSDR 2.0944 → S = −.5; band e = −(d + offset) from .667 outside to .333 inside, prof .25 + .75(1 − e) */
  const KF_S = Math.cos(2.0944), KF_AMOUNT = 1 / .5 - 2, g = (x) => x / (1 + KF_AMOUNT * (1 - x));   // B6-c §1: the CPU loads the Amount uniform as 1/amount − 2 (render 0x1c399425c–0x1c3994264 → +280; keyfill §5.1 B6-3) = 0 for the lens's .5 → x′ = x, no compression
  const kfK = (v, nx) => g(v * sat((nx - KF_S) / (1 - KF_S))) + g(v * sat((-nx - KF_S) / (1 - KF_S)));
  const kfRings = [[0, 1 / 3], [1 / 3, 2 / 3], [2 / 3, 1]].map(([a, b]) => ({ e0: a - 2 / 3, e1: b - 2 / 3, v: mean((e) => .25 + .75 * (1 - e), a, b) }));   // e0/e1 as depth into the capsule (negative = outside)
  const NXS = [-1, -.98, -.95, -.9, -.8, -.7, -.6, -.5, -.4, -.3, -.2, -.1, 0];
  const grey = (c) => { const m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/.exec(c || ""); return m ? { r: +m[1], g: +m[2], b: +m[3], a: m[4] == null ? 1 : +m[4] } : null; };
  return { hlRings, angMain, angDiff, kfRings, kfK, NXS, MULT: 1 - .9118, ADD: .1471, COLOR_BIAS: -.3, grey };
})();
const SEGX = ((new URLSearchParams(location.search).get("segx") || "") + "," + (new URLSearchParams(location.search).get("segx1") || "")).split(",").filter(Boolean);   // ?segx=a,b / ?segx1=<key> (first-glass-frame list): one switch set
const SEG_DISP_ON = new URLSearchParams(location.search).get("disp") === "1";
const SEG_VC_SPLIT = new URLSearchParams(location.search).get("vcsplit") !== "0";
/* 换值即抬手 (监督局 09-19 15:5x, bug fix): a tap's value change — selection + content, one frame — runs in the up's own task. With the +66 ms timer
   (--seg-commit-delay-tap ← seg-value-change-content.md §0: the native's content switch at up +50…92 in its recordings) and the vcsplit frame, the page's
   switch showed at up +136…143 on the phone (data: tools/touch/seg-web-valuechange-78284dd-light.md; marks tap-up +0 → commit-select +67 → commit-render
   +83…87): queued behind the lens's first glass frame (up +82). ?vcnow=0 = the timer path (with vcsplit). The slide's up keeps --seg-commit-delay-drag. */
const SEG_VC_NOW = new URLSearchParams(location.search).get("vcnow") !== "0";
const SEG_LPQ = new URLSearchParams(location.search).get("lpq") !== "0";   // lpq: per-frame filter / opacity writes quantised to the 8-bit raster (1/255; displacement scale .1) and written only on change — the springs are untouched (?lpq=0 off)
const lpq = (x) => SEG_LPQ ? Math.round(x * 255) / 255 : x;
const SEG_PREWARM_ON = new URLSearchParams(location.search).get("prewarm") !== "0";
/* WebGL lens (2号 lens-webgl.js, README §0.8.7): the lifted lens drawn on an overlay canvas by two fragment-shader passes (the same maps, the constants
   with their sources in the shaders); ?gl=0 keeps the SVG stack. segGlAvailable() = the switch + the package + a WebGL2 context, decided once. */
const SEG_GL_WANT = new URLSearchParams(location.search).get("gl") !== "0";
const SEG_GLM = 24;   // the canvas reaches 24 pt above and below the control (the lifted lens is 6 pt outside it, the wrapper 16 more, the ring shadow 11 below)
let segGlOk = null;
const segGlAvailable = () => { if (segGlOk == null) { try { segGlOk = SEG_GL_WANT && !!window.LensWebGL && !!document.createElement("canvas").getContext("webgl2"); } catch (e) { segGlOk = false; } } return segGlOk; };
const segRgb = (css) => { const m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)/.exec(css || ""); return m ? [+m[1], +m[2], +m[3]] : [0, 0, 0]; };
const segRgba = (css) => { const m = /rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[\/,]\s*([\d.]+%?))?/.exec(css || ""); if (!m) return [255, 255, 255, 1]; let a = m[4] == null ? 1 : parseFloat(m[4]); if (m[4] && m[4].endsWith("%")) a /= 100; return [+m[1], +m[2], +m[3], a]; };   // "rgb(235 235 245 / .3)" / "rgba(235, 235, 245, 0.3)"
/* the GL lens of a control: the canvas + the LensWebGL instance + the backdrop drawing (page colour + track; the labels at the buttons' DOM centres) */
/* segGlRedraw: the page's backdrop redraws (the value flip, a cancelled press, a theme change) go through the package's deferred redrawBackdrop
   (lens-webgl.js a334bed: draw + upload in the next task, then its warm-up frame). That warm-up leaves the package's `last` state = its own lifted
   frame, and the next warm-up "puts the previous frame back" after clearing (prewarm(): prev = last … setState(prev)) — so from the second re-render
   on a lifted capsule of the preloaded set's width sat at the canvas's left on a RESTING control (验收 09-19 17:5x, the one-queue page: 400 wide, the
   capsule ≈ 256; two segments hide it under the platter; sh/ghost_check.py). Here every page-side redraw is followed, in the task after the package's,
   by an explicit rest state — canvas cleared, `last` = lift 0 — unless a gesture loop is running (its ticks own the canvas). */
function segGlRedraw(seg) {
  const glo = seg.__gl; if (!glo) return;
  try { glo.lens.redrawBackdrop(); } catch (e) {}
  setTimeout(() => { if (!seg.isConnected || seg.__gl !== glo) return; if (seg.__lensLoop && !seg.__lensLoop.state.done) return; try { glo.lens.setState({ cx: 0, cy: 0, w: glo.w, h: glo.h, lift: 0 }); } catch (e) {} }, 0);
}
/* the page shown again (the appearance switch on the phone happens with the web app in the background, the theme change is delivered on the way back):
   every resting GL control is put to its rest state — canvas cleared, `last` = lift 0 — so nothing drawn while hidden can stay on screen (验收 09-19 18:0x:
   the ghost capsule after dark → light on the one-queue page) */
try { document.addEventListener("visibilitychange", () => { if (document.visibilityState !== "visible") return; for (const s of document.querySelectorAll(".segctl")) { const glo = s.__gl; if (!glo || (s.__lensLoop && !s.__lensLoop.state.done)) continue; try { glo.lens.setState({ cx: 0, cy: 0, w: glo.w, h: glo.h, lift: 0 }); } catch (e) {} } }); } catch (e) {}
function segGlCreate(seg, lens, bs, setW) {
  const cur = seg.__gl; if (cur && cur.w === seg.clientWidth && cur.h === seg.clientHeight && cur.setW === setW) return cur;
  if (cur) { try { cur.lens.destroy(); } catch (e) {} cur.canvas.remove(); seg.__gl = null; }
  let canvas = seg.querySelector("canvas.glens"); if (!canvas) { canvas = document.createElement("canvas"); canvas.className = "glens"; seg.appendChild(canvas); }
  const segW = seg.clientWidth, segH = seg.clientHeight;
  const sets = LensWebGL.setsFromFilters("seg"); if (!sets[setW]) return null;
  const onB = bs.find((b) => b.classList.contains("on")) || bs[0], offB = bs.find((b) => !b.classList.contains("on")) || bs[0];
  const gs = { futureOn: null, fontOn: getComputedStyle(onB).font, fontOff: getComputedStyle(offB).font };   // futureOn: the selection the labels texture is drawn for while a tap is in flight (set at the down, cleared at the commit / cancel)   // the one set the SVG path rides (the model width; the lift and the drag stay on it, README §0.3)
  const opts = { sets: { [setW]: sets[setW] }, preload: [setW], dpr: window.devicePixelRatio || 1, width: segW, height: segH + 2 * SEG_GLM, margin: 16, ink: segRgb(getComputedStyle(bs[0]).color),
    backdrop: (x, which) => {   // canvas pt; the canvas origin = the control's left, 24 pt above its top
      if (which === "page") { x.fillStyle = getComputedStyle(document.body).backgroundColor || "#fff"; x.fillRect(0, 0, segW, segH + 2 * SEG_GLM);
        const cs = getComputedStyle(seg); x.fillStyle = cs.backgroundColor; x.beginPath(); x.roundRect(0, SEG_GLM, segW, segH, parseFloat(cs.borderTopLeftRadius) || 16); x.fill(); }   // the track over the page colour; no platter (the DOM's shows at rest)
      else { const sr = seg.getBoundingClientRect(); x.textAlign = "center"; x.textBaseline = "middle";
        bs.forEach((b, i) => { const r = b.getBoundingClientRect(), c = getComputedStyle(b), on = gs.futureOn != null ? i === gs.futureOn : b.classList.contains("on");
          x.font = on ? gs.fontOn : gs.fontOff; x.fillStyle = c.color; x.fillText(b.textContent, r.left - sr.left + r.width / 2, SEG_GLM + r.top - sr.top + r.height / 2); }); } } };
  let glLens; try { glLens = LensWebGL.create(canvas, opts); } catch (e) { console.warn("LensWebGL", e); canvas.remove(); segGlOk = false; return null; }
  return (seg.__gl = { canvas, lens: glLens, opts, w: segW, h: segH, setW, gs, platter: segRgba(getComputedStyle(seg).getPropertyValue("--ios-segment-selected-bg")) });   // the platter colour token (light (255,255,255,1) / dark (235,235,245,.3), tokens.css)
}
try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { for (const s of document.querySelectorAll(".segctl")) if (s.__gl) { const b = s.querySelector("button"); if (b) s.__gl.opts.ink = segRgb(getComputedStyle(b).color); s.__gl.platter = segRgba(getComputedStyle(s).getPropertyValue("--ios-segment-selected-bg")); segGlRedraw(s); } }); } catch (e) {}   // theme change: the backdrop's colours and the ink   // 换值重画不阻塞: the commit frame switches the selection only, the content render runs in the next frame (?vcsplit=0 = one frame, the old path)   // layer-5 colour fringe (7-tap chain on .stack, per-frame W/H matrix + tap scales): default off, ?disp=1 on (监督局 09-19 12:0x, phone fps bisect)
/* instrumentation (仪器, no behaviour): the lens loop publishes its per-tick internals as window.__segLens — a flat object of numbers and strings,
   rewritten at the end of every tick, read as is by 2号's frame recorder (seg-frames-logger.js `state`; a field named t or ending in _t is a
   performance.now() ms the recorder converts to s since the down). The agreed names: t (the tick's performance.now()), x (the position spring, pt),
   v (pt/s), target (the target this tick integrated toward), dt (the step, s), pointer_t (performance.now() of the last move the loop consumed),
   retarget_t (the tick at which the spring's target last changed), phase (lift | hold | drag | release | done); the rest: target_next (the target the
   next tick will use — a move is adopted after the step, see the tick's time-base note), adopted (1 when this tick adopted a move), pointer_ev_t (that
   move's event timeStamp), pointer_x (its finger x in control coordinates), pointer_target (the target it set), pointer_n (moves consumed since the
   previous tick), raf_t (the tick's rAF timestamp), tick (count), tick_ms (the tick's own duration), drift / sx / sy (the flex floats), x_screen
   (x + drift = the presented centre), accel / vel (the flex integrator), p (lift progress), set (displacement-map set), rel_t (the release time),
   gl_trace (WebGL, ?gltrace=1 only: the package's per-step gl.finish timing of this frame's draw, lens-webgl.js e1e5633 stats.trace, as a JSON string — ms since the draw began).
   window.__segDiag() returns the same object; window.__segPerf() lists the seg: performance measures (lift build, first tick, commit, render stages). */
let segActiveLoop = null;
window.__segLens = null;
window.__segDiag = () => window.__segLens;
window.__segPerf = () => performance.getEntriesByType("measure").filter((e) => e.name.startsWith("seg:")).map((e) => ({ name: e.name, start: Math.round(e.startTime * 100) / 100, dur: Math.round(e.duration * 100) / 100 }));
const segMeasure = (name, from) => { try { performance.measure(name, { start: from, end: performance.now() }); } catch (e) { /* older engines */ } };   // ?segx switches (index.html hook; ios-switch-list.md): scale0 holds the displacement scale at 0
function segLens(seg, lens, bs, downClientX, tap, downAt) {   // downAt = the pointerdown's event timeStamp (the press path's time base: the lift delay counts from the touch)   // tap = { target, upAt }: the 点按 schedule (SEG_TAP_T) instead of the press / drag / release chain; tap = { prewarm: true }: build + one invisible paint, no loop (A 起手预建); tap = { deferred: true }: build now, arm later with loop.beginTap(target, upAt) (the tap's work done at the down)
  const prewarm = !!(tap && tap.prewarm), deferred = !!(tap && tap.deferred); if (prewarm || deferred) tap = null;
  if (seg.__lensLoop && !prewarm) seg.__lensLoop.stop();   // a new press ends the previous loop (its tail and its inline geometry)
  if (!prewarm && SEGX.includes("nokeep")) seg.classList.remove("prewarm");   // ?segx1=nokeep: the old behaviour (layers display:none from the down to the lift) for the first-frame A/B
  // (otherwise .prewarm stays until the lift frame — frame() removes it as it sets .lift, so the layers never pass through display:none; liftgap_check.py)
  let warp = seg.querySelector(".warp"), warpl = seg.querySelector(".warpl"), plat = seg.querySelector(".plat"), rimb = seg.querySelector(".rimb"), hls = [...seg.querySelectorAll(".hlk, .hlw")];
  const mk = (cls, inner) => { const d = document.createElement("div"); d.className = cls; d.innerHTML = inner; seg.appendChild(d); return d; };
  if (!warp) warp = mk("warp", '<div class="disp"><div class="copy"></div><div class="punch"><div class="copy"></div></div></div>'); else if (!warp.querySelector(".punch")) warp.firstElementChild.innerHTML = '<div class="copy"></div><div class="punch"><div class="copy"></div></div>';
  if (!warpl) warpl = mk("warpl", '<div class="displ"><div class="copy"></div></div>'); else if (warpl.querySelector(".portal")) warpl.firstElementChild.innerHTML = '<div class="copy"></div>';   // B4-c': portal #32 does not clip
  if (!plat) plat = mk("plat", "");
  /* B4-c' layer 5: .stack = lens box + 16 pt wrapper carrying the colour-fringe chain; .base = the plain copy of the page under the displaced layers */
  let stack = seg.querySelector(".stack"), base = stack && stack.querySelector(".base");
  if (!stack) { stack = mk("stack", '<div class="base"><div class="copy"><div class="cbgwrap"><div class="cbg"></div><div class="ctrack"></div></div></div></div>'); base = stack.firstElementChild; }
  const AM = 16;   // the wrapper's extension beyond the lens (lens-field.json aberration.wrapper; the chain's outward taps read the page there)
  /* WebGL path (README §0.8.7): the SVG layers above stay built but hidden (.segctl.gl); the canvas draws the lens from the loop's state each tick */
  let GL = segGlAvailable(), glo = null;
  if (GL) { const segW0 = seg.clientWidth, n0 = bs.length, pad0 = parseFloat(getComputedStyle(seg).paddingTop) || 2; const W00 = segW0 / n0 - 2 * pad0;
    glo = segGlCreate(seg, lens, bs, Math.max(196, Math.min(256, 2 * Math.round((W00 + 2 * touchPx("--ios-touch-segment-lift-x", 12)) / 2)))); if (!glo) GL = false; }
  seg.classList.toggle("gl", GL);
  const DISPERSION = SEG_DISP_ON && seg.dataset.dispersion !== "0" && !SEGX.includes("noab");   // 监督局 09-19 12:0x: the fringe chain is OFF by default (?disp=1 on) while the phone's 20–25 fps rendering is bisected
  /* B6 rim (index.html "B6" block, SEG_RIM): .rimb = inner shadow div + SVG (ring shadow rect.rs, dark line rect.kf ×3 under the page/track mask);
     .hlk / .hlw = the #36 highlight as SVG ring strokes, black (normal) / white (plus-lighter) */
  const NS = "http://www.w3.org/2000/svg", svgEl = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
  const uid = seg.id || "seg";
  const hgrad = (id, fn, colour) => { const gr = svgEl("linearGradient", { id, gradientUnits: "userSpaceOnUse", x1: 0, y1: 0, x2: 1, y2: 0 }); const nx = SEG_RIM.NXS;
    for (const side of [0, 1]) for (const n of (side ? [...nx].reverse() : nx)) gr.appendChild(svgEl("stop", { offset: 0, "stop-color": colour, "stop-opacity": fn(n).toFixed(4), "data-nx": n, "data-side": side }));
    return gr; };
  const ringRect = (cls, e0, e1, extra) => svgEl("rect", Object.assign({ class: cls, "data-e0": e0, "data-e1": e1 }, extra || {}));
  const buildSvg = (cls) => { const s = svgEl("svg", { class: cls }); const defs = svgEl("defs", {}); s.appendChild(defs); const gg = svgEl("g", { transform: "translate(12 12)" }); s.appendChild(gg); return { s, defs, g: gg }; };
  if (!rimb) { rimb = mk("rimb", '<div class="ish"></div>'); const { s, defs, g } = buildSvg("rsv");
    const f = svgEl("filter", { id: "seg-rs-blur", x: "-50%", y: "-50%", width: "200%", height: "200%" }); f.appendChild(svgEl("feGaussianBlur", { stdDeviation: 3 })); defs.appendChild(f);
    const vg = svgEl("linearGradient", { id: `${uid}-kf-vg`, gradientUnits: "userSpaceOnUse", x1: 0, y1: 0, x2: 0, y2: 1 });
    for (const [o, cls] of [[0, "pf"], [0, "tk"], [1, "tk"], [1, "pf"]]) vg.appendChild(svgEl("stop", { offset: o, "stop-color": "#fff", "stop-opacity": 1, class: cls }));
    defs.appendChild(vg);
    const m = svgEl("mask", { id: `${uid}-kf-vm`, maskUnits: "userSpaceOnUse", x: -12, y: -12, width: 1, height: 1 }); m.appendChild(svgEl("rect", { x: -12, y: -12, width: 1, height: 1, fill: `url(#${uid}-kf-vg)` })); defs.appendChild(m);
    g.appendChild(ringRect("rs", 0, 4, { "data-dy": 8 }));
    const kg = svgEl("g", { class: "kfg" }); if (!SEGX.includes("nokfmask")) kg.setAttribute("mask", `url(#${uid}-kf-vm)`); g.appendChild(kg);   // ?segx=nokfmask (experiment): the three rings without the SVG mask (the page factor is then not applied)
    SEG_RIM.kfRings.forEach((r, i) => { defs.appendChild(hgrad(`${uid}-kf-g${i}`, (nx) => SEG_RIM.kfK(r.v, nx) / SEG_RIM.kfK(r.v, -1), "#000")); kg.appendChild(ringRect("kf", r.e0, r.e1, { stroke: `url(#${uid}-kf-g${i})`, "data-v": r.v })); });
    rimb.appendChild(s); }
  /* the #36 layer is THREE emits, each source-over through the vibrant matrix (predict-seg-hold.md §0 item 6, keyfill-highlight.md §2 07:12): out ← (1 − α_i)·out + α_i·V(out)
     for the main band, then the diffuse key band, then the diffuse fill band — not one pass with the summed α (dark edge row: summed 35, three passes 44.0, measured 45.3).
     Each pass = a black multiply stack (1 − .0882α_i) followed by a white plus-lighter stack (+.1471α_i), so the pass order is the element order:
     black-main, white-main, black-diffuse, white-diffuse. The two diffuse bands never overlap (key lights within 52° of the top, fill of the bottom), so one diffuse pair carries both. */
  /* B6-c §4b (predict-seg-hold.md §6.1 rows 5–6): the MAIN band runs only along the two straight edges, |x − W/2| ≤ W/2 − R (the native arc rows 603–605 at
     x_arc + .5 carry no lightening; keyfill §0a item 2 withdrawn) — two <line> per ring (top / bottom), plain colour (n·dir = 1 there), no gradient;
     the diffuse tail stays a full ring under the first ring's angular ratio. Unresolved (recorded): the shader's angular term would give .65 of the
     band at 45° on the arc where the reading says 0 — the #36 layer's shape / clip (cornerRadii 0×4), for the data session. */
  const mkHl = (cls, band, colour, mult) => { const { s, defs, g } = buildSvg(cls); s.classList.add(band); const gid = `${uid}-${cls}-${band}`; if (band !== "m") defs.appendChild(hgrad(gid, SEG_RIM.angDiff, colour));
    for (const r of SEG_RIM.hlRings) { const a = band === "m" ? r.main : r.diff; if (!a) continue;
      if (band === "m") for (const run of ["top", "bot"]) g.appendChild(svgEl("line", { class: "hl", "data-e0": r.e0, "data-e1": r.e1, "data-run": run, stroke: colour, "stroke-opacity": (mult * a).toFixed(4), "stroke-linecap": "butt" }));
      else g.appendChild(ringRect("hl", r.e0, r.e1, { stroke: `url(#${gid})`, "stroke-opacity": (mult * a).toFixed(4) })); }
    seg.appendChild(s); return s; };
  /* ?segx=hlcss (experiment, ios-switch-list.md): the same four passes as CSS inset box-shadow ring stacks on plain divs (each shadow covers the rings
     inside it, so the per-ring alphas are solved for the cumulative source-over) with the angular factor as a mask-image gradient — no SVG. */
  const HLCSS = SEGX.includes("hlcss");
  const mkHlCss = (cls, band, colour, mult) => { const el = mk(cls, ""); el.classList.add(band, "css"); const rings = SEG_RIM.hlRings.filter((r) => (band === "m" ? r.main : r.diff) > 0), eff = rings.map((r) => mult * (band === "m" ? r.main : r.diff));
    const a = []; for (let j = eff.length - 1; j >= 0; j--) { const inner = j + 1 < eff.length ? eff[j + 1] : 0; a[j] = 1 - (1 - eff[j]) / (1 - inner); }
    el.style.boxShadow = rings.map((r, j) => `inset 0 0 0 ${(r.e1).toFixed(4)}px rgb(${colour} / ${a[j].toFixed(4)})`).join(", ");
    const fn = band === "m" ? SEG_RIM.angMain : SEG_RIM.angDiff, L = SEG_RIM.NXS.map((nx) => `rgb(0 0 0 / ${fn(nx).toFixed(4)}) calc(var(--rr, 14px) * ${(1 + nx).toFixed(2)})`), R = [...SEG_RIM.NXS].reverse().map((nx) => `rgb(0 0 0 / ${fn(nx).toFixed(4)}) calc(100% - var(--rr, 14px) * ${(1 + nx).toFixed(2)})`);
    const g = `linear-gradient(90deg, ${L.join(", ")}, ${R.join(", ")})`; el.style.webkitMaskImage = g; el.style.maskImage = g; return el; };
  if (hls.length !== 4) { for (const e of hls) e.remove(); hls = HLCSS ? [mkHlCss("hlk", "m", "0 0 0", SEG_RIM.MULT), mkHlCss("hlw", "m", "255 255 255", SEG_RIM.ADD), mkHlCss("hlk", "d", "0 0 0", SEG_RIM.MULT), mkHlCss("hlw", "d", "255 255 255", SEG_RIM.ADD)]
    : [mkHl("hlk", "m", "#000", SEG_RIM.MULT), mkHl("hlw", "m", "#fff", SEG_RIM.ADD), mkHl("hlk", "d", "#000", SEG_RIM.MULT), mkHl("hlw", "d", "#fff", SEG_RIM.ADD)]; }
  /* the dark line's alphas for this theme: black source-over α = .3·k_tip·(3 − 2B) on the track the ends lie on, × (3 − 2B_page)/(3 − 2B_track) on the page rows
     (B = the mean grey of the actual backdrop: --ios-segment-track composited on --bg) */
  { const pg = SEG_RIM.grey(getComputedStyle(document.body).backgroundColor) || { r: 242, g: 242, b: 247, a: 1 }, tk = SEG_RIM.grey(getComputedStyle(seg).backgroundColor) || { r: 118, g: 118, b: 128, a: .12 };
    const Bp = (pg.r + pg.g + pg.b) / 765, Bt = ((tk.r * tk.a + pg.r * (1 - tk.a)) + (tk.g * tk.a + pg.g * (1 - tk.a)) + (tk.b * tk.a + pg.b * (1 - tk.a))) / 765;
    seg.querySelectorAll(".rimb rect.kf, .rimo rect.kf").forEach((r) => r.setAttribute("stroke-opacity", (-SEG_RIM.COLOR_BIAS * SEG_RIM.kfK(+r.dataset.v, -1) * (3 - 2 * Bt)).toFixed(4)));
    const pf = Math.min(1, (3 - 2 * Bp) / (3 - 2 * Bt)); rimb.querySelectorAll("stop.pf").forEach((st) => st.setAttribute("stop-opacity", pf.toFixed(4))); }
  /* ?segx=wide1 (ios-switch-list.md, experiment only): every run of 1/3-pt ring strokes (the dark line's three, the highlight's first three) becomes ONE
     whole-pt stroke with the mean stroke-opacity and the middle ring's gradient — to see whether the 3× raster's antialiasing of three 1/3-pt strokes is
     what the simulator shows as a weaker / merged line. Not a drawing of the formula (the .875 / .625 / .375 profile is flattened). */
  if (SEGX.includes("wide1")) for (const s of [rimb.querySelector("svg"), ...hls]) { const thin = [...s.querySelectorAll("rect[data-e0]")].filter((r) => +r.dataset.e1 - +r.dataset.e0 < .5);
    const groups = new Map(); for (const r of thin) { const k = r.parentElement.getAttribute("class") || r.getAttribute("class"); (groups.get(k) || groups.set(k, []).get(k)).push(r); }
    for (const rs of groups.values()) { rs.sort((a, b) => +a.dataset.e0 - +b.dataset.e0); const mid = rs[Math.floor(rs.length / 2)], mean = rs.reduce((t, r) => t + parseFloat(r.getAttribute("stroke-opacity") || 1), 0) / rs.length;
      mid.dataset.e0 = rs[0].dataset.e0; mid.dataset.e1 = rs[rs.length - 1].dataset.e1; mid.setAttribute("stroke-opacity", mean.toFixed(4)); for (const r of rs) if (r !== mid) r.remove(); } }
  /* .rimo: the outside-the-capsule half of .rimb (see index.html): a clone above the wrapper, clipped to the outside; its rects reference the first
     (rimb's) gradients / mask by id, which the loop updates */
  let rimo = seg.querySelector(".rimo");
  if (!rimo) { rimo = rimb.cloneNode(true); rimo.className = "rimo"; seg.appendChild(rimo); } else if (!rimo.querySelector("rect.rs")) { rimo.innerHTML = rimb.innerHTML; }
  { const ri = rimo.querySelector(".ish"); if (ri) ri.remove(); }   // the inner shadow lies inside the capsule, which .rimo's clip removes — no second σ-3 blur per frame
  let rimoKey = "";
  let rimKey = "";
  const rimGeo = (Wd, Hd, T) => {   // SVG geometry in lens-box coordinates (the <g> is translated by the 12 px margin)
    const key = `${Wd}|${Hd}|${T}`; if (key === rimKey) return; rimKey = key; const R = Hd / 2;
    for (const s of [rimb.querySelector("svg"), rimo.querySelector("svg"), ...(HLCSS ? [] : hls)]) { s.setAttribute("width", Wd + 24); s.setAttribute("height", Hd + 24);
      for (const r of s.querySelectorAll("rect[data-e0]")) { const e0 = +r.dataset.e0, e1 = +r.dataset.e1, em = (e0 + e1) / 2, dy = +(r.dataset.dy || 0);
        r.setAttribute("x", em); r.setAttribute("y", em + dy); r.setAttribute("width", Wd - 2 * em); r.setAttribute("height", Hd - 2 * em); r.setAttribute("rx", R - em); r.setAttribute("stroke-width", e1 - e0); }
      for (const l of s.querySelectorAll("line[data-e0]")) { const e0 = +l.dataset.e0, e1 = +l.dataset.e1, em = (e0 + e1) / 2, y = l.dataset.run === "top" ? em : Hd - em;   // B6-c §4b: the main band's straight runs x ∈ [R, W − R]
        l.setAttribute("x1", R); l.setAttribute("x2", Wd - R); l.setAttribute("y1", y); l.setAttribute("y2", y); l.setAttribute("stroke-width", e1 - e0); }
      for (const gr of s.querySelectorAll("linearGradient")) { if (gr.getAttribute("x2") === "0") { gr.setAttribute("y1", -T); gr.setAttribute("y2", segH - T); continue; }   // the page / track mask: the track's rows in lens-box coordinates
        gr.setAttribute("x2", Wd); for (const st of gr.children) { const nx = +st.dataset.nx, o = R * (1 + nx) / Wd; st.setAttribute("offset", (st.dataset.side === "1" ? 1 - o : o).toFixed(5)); } }
      for (const m of s.querySelectorAll("mask")) { m.setAttribute("width", Wd + 24); m.setAttribute("height", Hd + 24); m.firstElementChild.setAttribute("width", Wd + 24); m.firstElementChild.setAttribute("height", Hd + 24); } } };
  /* copies of what lies under the lens (glass-displacement-formula.md §4b): .warp = the BackdropView capture = page bg + track (opaque, covers the
     real labels inside the lens box) + .punch = the labels with the lens capsule cut out (DestOut #43 removes the segment content inside the capsule
     only; the box corners outside it keep their label pixels, which the backdrop map's clamp_to_edge replicates into the rim band — §6d); .warpl = the
     labels through portal #20 (the box, clipped to the capsule before the filter), no 196×28 clip (portal #32 masksToBounds 0). Spans, not buttons,
     so the control's own button list stays the real one. */
  const disp = warp.firstElementChild, copy = disp.firstElementChild, punch = disp.lastElementChild, copyp = punch.firstElementChild, displ = warpl.firstElementChild, copyl = displ.firstElementChild, copyb = base.firstElementChild;
  copy.innerHTML = '<div class="cbgwrap"><div class="cbg"></div><div class="ctrack"></div></div>';
  const labelsHTML = bs.map((b) => `<span class="cb ${b.className}" style="width:${b.offsetWidth}px">${b.innerHTML}</span>`).join("");
  copyl.innerHTML = labelsHTML; copyp.innerHTML = labelsHTML; copyb.innerHTML = '<div class="cbgwrap"><div class="cbg"></div><div class="ctrack"></div></div>' + labelsHTML;
  const segW = seg.clientWidth, segH = seg.clientHeight; for (const c of [copy, copyl, copyp, copyb]) { c.style.width = segW + "px"; c.style.height = segH + "px"; }
  for (const el of [warp, plat, rimb, warpl]) if (el.parentElement !== stack) stack.appendChild(el);   // the displaced layers live inside the wrapper (DOM order = z order 4 / 5 / 6 / 7 inside it)

  const cbs = [...copyl.querySelectorAll(".cb"), ...copyp.querySelectorAll(".cb"), ...copyb.querySelectorAll(".cb")];
  const sOf = (id) => { const f = document.querySelector(id); return f ? parseFloat(f.getAttribute("data-s")) || 40 : 40; };   // map encoding per set (ui2 c4efe4b, README §0.3): byte = 128 + round(u · 255 / S), S = the filter's data-s (40; 48 on the eleven widest stretch sets) → feDisplacementMap scale = S × progress
  /* the formula-map set = the lens's MODEL width (README §0.3, ui2 d3cc467: the drag stretch is the 220×44 model scaled by the lens's presentation
     transform — the flex scale, B5 — so the model stays 220 while dragging and the 220 set is the one; the lift rides it with scale 0 → S). The
     196 … 256 sets remain for a model of another width. */
  const setFor = (Wm) => Math.max(196, Math.min(256, 2 * Math.round(Wm / 2)));
  let curSet = 0, punchKey = "", abKey = "", ishKey = "", lpKey = "", lpdKey = "";
  /* layer 5 per frame: the W/H colour matrix from the lens's SCREEN rect (§3b.6 capture box = frame + 100 pt each side clamped to the viewport;
     1.72 dragged to the divider on the 440 screen, 1.35 lifted in place) and the seven taps' scales = ±S_ab·k × lift progress */
  const abFrame = (set, p) => {
    const f = document.querySelector(`#seg-lens-f-ab-${set}`); if (!f) return;
    const r = lens.getBoundingClientRect(), sw = innerWidth, sh = innerHeight;
    const wh = (Math.min(r.right + 100, sw) - Math.max(r.left - 100, 0)) / (Math.min(r.bottom + 100, sh) - Math.max(r.top - 100, 0));
    const key = `${set}|${wh.toFixed(4)}|${p.toFixed(3)}`; if (key === abKey) return; abKey = key;
    const m = f.querySelector(`#seg-lens-f-ab-${set}-wh`); if (m) m.setAttribute("values", `${wh.toFixed(4)} 0 0 0 ${(0.5 * (1 - wh)).toFixed(4)}  0 ${(1 / wh).toFixed(4)} 0 0 ${(0.5 * (1 - 1 / wh)).toFixed(4)}  0 0 1 0 0  0 0 0 1 0`);
    const S = parseFloat(f.getAttribute("data-s")) || 12, taps = f.querySelectorAll("feDisplacementMap"), n = taps.length;   // 7 taps k = 1, 2/3, 1/3, 0, −1/3, −2/3, −1 (README §0.5)
    taps.forEach((t, i) => t.setAttribute("scale", (S * p * (1 - 2 * i / (n - 1))).toFixed(3)));
  };
  /* geometry: resting lens = the padded interior / n (pad ← --ios-segment-lens-pad, h ← --ios-segment-lens-h), lifted = +12 / +8 per side ← --ios-touch-segment-lift-x/-y */
  const cs0 = getComputedStyle(seg), n = bs.length, pad = parseFloat(cs0.getPropertyValue("--ios-segment-lens-pad")) || 2, H0 = parseFloat(cs0.getPropertyValue("--ios-segment-lens-h")) || 28;
  const LX = touchPx("--ios-touch-segment-lift-x", 12), LY = touchPx("--ios-touch-segment-lift-y", 8), PITCH = segW / n, W0 = PITCH - 2 * pad, CY = pad + H0 / 2;   // segment pitch 200, resting lens 196 (inset 2 ← seg-native-abc-frames.json rest rect 22 610 196×28)
  const restCentre = (i) => i * PITCH + PITCH / 2, idx0 = Math.max(0, bs.findIndex((b) => b.classList.contains("on")));
  const liftDelay = touchMs("--ios-touch-segment-lift-delay", 109) / 1000, relDelay = touchMs("--ios-touch-segment-release-delay", 31) / 1000;
  const destDelay = touchMs("--ios-touch-segment-release-destout-delay", 198) / 1000;
  const K_LIFT_DEST = cssKeys("--ios-touch-segment-destout-keys", SEG_LIFT_DESTOUT), K_DEST = cssKeys("--ios-touch-segment-release-destout-keys", SEG_DROP_DESTOUT.filter(([t]) => t >= .198).map(([t, v]) => [t - .198, v]));
  const destEnd = destDelay + K_DEST[K_DEST.length - 1][0];
  const downX = (typeof downClientX === "number" ? downClientX : NaN) - seg.getBoundingClientRect().left;   // the touch-down x in control coordinates (the drag delta's origin, §6 _dragDelta)
  const st = { t0: tap ? tap.upAt : (downAt > 0 && downAt <= performance.now() ? downAt : performance.now()), prev: performance.now(), rel: tap ? tap.upAt : null, raf: 0, done: false, dragged: false, cx: null, pending: null, rest: tap ? tap.target : idx0, pr: 0, ticks: 0, ev: { t: null, evt: null, x: null, target: null, n: 0 }, retargetT: null,
               tap: tap || null, sMt: { x: 0, v: 0 },   // 点按: the material spring of the tap schedule (geometry rides sL)
               sL: { x: 0, v: 0 }, sM: { x: 1, v: 0 }, pos: { x: restCentre(idx0), v: 0 }, geo: null,   // pos = the lens position (one spring; the flex drift rides on top of it in the transform)
               flex: { vi: flexIntegrator(), sx: { x: 1, v: 0 }, sy: { x: 1, v: 0 }, dx: { x: 0, v: 0 }, out: { sx: 1, sy: 1, dx: 0 } } };   // B5: the flex interaction's integrator and its three animatable floats
  const setGeo = (left, top, w, h) => {
    lens.style.transition = "none"; lens.style.left = left + "px"; lens.style.top = top + "px"; lens.style.width = w + "px"; lens.style.height = h + "px"; lens.style.margin = "0"; lens.style.borderRadius = (h / 2) + "px";
    st.geo = { left, top, w, h };
    const f = st.flex.out, idle = Math.abs(f.sx - 1) < 1.5e-3 && Math.abs(f.sy - 1) < 1.5e-3 && Math.abs(f.dx) < .1;   // at rest the transform is dropped: a transform within 1/700 of identity (< .17 px at the lens edge) still makes the browser resample the filtered layers (blurs the 1 pt lines, shifts the end columns) — CoreAnimation renders its vector layers sharp at any transform
    const tf = idle ? "none" : `translateX(${f.dx.toFixed(3)}px) scale(${f.sx.toFixed(5)}, ${f.sy.toFixed(5)})`;   // the flex presentation transform (§1: on the transform, the model bounds unchanged); every layer of the lens carries it
    if (GL) { lens.style.transform = tf; lens.style.transformOrigin = "50% 50%"; glo.canvas.style.transform = tf; glo.canvas.style.transformOrigin = `${left + w / 2}px ${SEG_GLM + top + h / 2}px`; }   // the flex transform about the lens centre, on the canvas (control-wide) and the platter
    else for (const el of [lens, stack, rimo, ...hls]) { el.style.transform = tf; el.style.transformOrigin = "50% 50%"; }   // the wrapper carries the transform for the four layers inside it (its centre = the lens centre)
  };
  const frame = (p, pd) => {   // p = glass / displacement progress, pd = DestOut (copies) opacity
    const g = st.geo || { left: pad + idx0 * PITCH, top: pad, w: W0, h: H0 };   // the model box (the flex transform sits on top of it, so not getBoundingClientRect)
    const L = g.left, T = g.top, Wd = g.w, Hd = g.h, R = Hd / 2;   // capsule: corner = h/2 (r22 at 44 ← §0; the lift's corner 14 → 22 on the same spring ← §4.4 row 1)
    if (GL) {   // WebGL: one setState per tick — uniforms only (README §0.8.7 step 3); wh = the §3b.6 capture-box rule from the lens's screen rect
      const r = lens.getBoundingClientRect(), sw = innerWidth, sh = innerHeight, wh = (Math.min(r.right + 100, sw) - Math.max(r.left - 100, 0)) / (Math.min(r.bottom + 100, sh) - Math.max(r.top - 100, 0));
      /* pd = the DestOut α (§4.1 -destout-keys, the first three frames .396 / .98 / 1): in the package (7940efc) it fades the REAL labels out of the backdrop copy
         at the source position only — the capsule stays opaque and the platter layer is not scaled by it (the a20df11 flash: the earlier package multiplied the
         whole capsule by pd, so the platter was gone on the first two lifted frames). */
      glo.lens.setState({ cx: L + Wd / 2, cy: SEG_GLM + T + Hd / 2, w: Wd, h: Hd, lift: SEGX.includes("scale0") ? 0 : p, pd, wh, platter: { rgba: glo.platter, alpha: 1 - p } });   // platter = restingBackground (_controlForegroundColor) fading 1 − p inside the capsule, above the displaced backdrop, below lines / labels (§4b; 2号 dc2af2a uniform)
      { const a = lpq(p).toFixed(4), b = lpq(pd).toFixed(4); if (lpKey !== a) { lpKey = a; seg.style.setProperty("--lp", a); } if (lpdKey !== b) { lpdKey = b; seg.style.setProperty("--lpd", b); } }
      if (p > 0 || pd > 0) { seg.classList.add("lift"); seg.classList.remove("prewarm"); } else seg.classList.remove("lift");
      return; }
    stack.style.left = (L - AM) + "px"; stack.style.top = (T - AM) + "px"; stack.style.width = (Wd + 2 * AM) + "px"; stack.style.height = (Hd + 2 * AM) + "px";
    copyb.style.left = (AM - L) + "px"; copyb.style.top = (AM - T) + "px";   // the plain copy aligned with the real control
    for (const el of [warp, warpl, plat, rimb]) { el.style.left = AM + "px"; el.style.top = AM + "px"; el.style.width = Wd + "px"; el.style.height = Hd + "px"; el.style.setProperty("--rr", R + "px"); }
    stack.style.setProperty("--rr", R + "px"); rimo.style.left = L + "px"; rimo.style.top = T + "px"; rimo.style.width = Wd + "px"; rimo.style.height = Hd + "px"; rimo.style.setProperty("--rr", R + "px");
    if (rimoKey !== `${Wd}|${Hd}`) { rimoKey = `${Wd}|${Hd}`; rimo.style.clipPath = `path(evenodd, "M-14 -14H${Wd + 14}V${Hd + 14}H-14Z M${R} 0H${Wd - R}A${R} ${R} 0 0 1 ${Wd - R} ${Hd}H${R}A${R} ${R} 0 0 1 ${R} 0Z")`; }   // the outside of the capsule (the ring shadow reaches 11 pt out)
    for (const el of hls) { if (HLCSS) { el.style.left = L + "px"; el.style.top = T + "px"; el.style.width = Wd + "px"; el.style.height = Hd + "px"; el.style.setProperty("--rr", R + "px"); } else { el.style.left = (L - 12) + "px"; el.style.top = (T - 12) + "px"; el.style.width = (Wd + 24) + "px"; el.style.height = (Hd + 24) + "px"; el.style.setProperty("--rr", R + "px"); } }   // --rr: the capsule clip of the highlight stacks (B6-c §3)   // the highlight SVGs' box = lens box + the 12 px margin (WebKit clips an outer <svg> to its box whatever overflow says)
    rimGeo(Wd, Hd, T);   // B6: the ring strokes follow the model box
    copy.style.left = -L + "px"; copy.style.top = -T + "px";   // the backdrop copy stays aligned with the real control
    copyp.style.left = -L + "px"; copyp.style.top = -T + "px"; copyl.style.left = -L + "px"; copyl.style.top = -T + "px";   // the label copies aligned with the real labels (B4-c': no 196×28 portal offset)
    if (punchKey !== `${Wd}|${Hd}`) { punchKey = `${Wd}|${Hd}`; punch.style.clipPath = `path(evenodd, "M0 0H${Wd}V${Hd}H0Z M${R} 0H${Wd - R}A${R} ${R} 0 0 1 ${Wd - R} ${Hd}H${R}A${R} ${R} 0 0 1 ${R} 0Z")`; }   // DestOut = the lens capsule (r = h/2 on the lift path; the drag stretch is the flex transform on top)
    const set = setFor(Math.max(W0 + 2 * LX, Wd));   // the model width (220 lifted; Wd is the model box — the flex transform is separate)
    if (set !== curSet) { curSet = set; disp.style.filter = SEGX.includes("nobgmap") ? "none" : `url(#seg-lens-f-bg-${set})`; displ.style.filter = SEGX.includes("nolabmap") ? "none" : `url(#seg-lens-f-lab-${set})`; /* ?segx1=nobgmap / nolabmap: the copy without its displacement filter */ stack.style.filter = DISPERSION && document.querySelector(`#seg-lens-f-ab-${set}`) ? `url(#seg-lens-f-ab-${set})` : "none"; }
    if (DISPERSION) abFrame(set, p);
    { const pq = lpq(p); if (ishKey !== pq.toFixed(4)) { ishKey = pq.toFixed(4); const f = document.querySelector("#seg-lens-f-ish"); if (f) { const off = f.querySelector("feOffset"), bl = f.querySelector("feGaussianBlur"), fa = f.querySelector("feFuncA");   // B6-c §4: #21's offset / radius / opacity on the lift curve (seg-lens-refraction §1c(b)); lpq: written on 1/255 steps only
        if (off) off.setAttribute("dy", (7 * pq).toFixed(3)); if (bl) bl.setAttribute("stdDeviation", (3 * pq).toFixed(3)); if (fa) fa.setAttribute("slope", (.06 * pq).toFixed(4)); } } }
    { const a = lpq(p).toFixed(4), b = lpq(pd).toFixed(4); if (lpKey !== a) { lpKey = a; seg.style.setProperty("--lp", a); } if (lpdKey !== b) { lpdKey = b; seg.style.setProperty("--lpd", b); } }   // lpq: 1/255 steps, written on change
    for (const id of [`#seg-lens-f-bg-${set}`, `#seg-lens-f-lab-${set}`]) { const fd = document.querySelector(`${id} feDisplacementMap`); if (!fd) continue; const sc = SEGX.includes("scale0") ? "0" : (SEG_LPQ ? (Math.round(sOf(id) * p * 10) / 10).toFixed(1) : (sOf(id) * p).toFixed(3)); if (fd.getAttribute("scale") !== sc) fd.setAttribute("scale", sc); }   // lpq: .1 steps (.0025 pt), written on change   // both stacks' amounts on the lift spring (§4.4 row 2: ClearGlass 0 → −17.5, ContentLensing 0 → −8.8, BackdropView 0 → 9 in the same call)
    cbs.forEach((c, i) => c.className = "cb " + bs[i % bs.length].className);
    if (p > 0 || pd > 0) { seg.classList.add("lift"); seg.classList.remove("prewarm"); } else seg.classList.remove("lift");   // .prewarm → .lift in one style update: the layers stay display:block, only their opacity changes (A: keep the compositing layers alive)
  };
  const clear = () => {
    seg.classList.remove("lift"); seg.style.removeProperty("--lp"); seg.style.removeProperty("--lpd");
    if (SEG_PREWARM_ON && !SEGX.includes("nokeep")) seg.classList.add("prewarm"); else { copy.innerHTML = ""; copyl.innerHTML = ""; }   // the layers stay displayed at .01 between gestures (copies kept), so the next lift's first frame finds them composited
    if (curSet) for (const id of [`#seg-lens-f-bg-${curSet}`, `#seg-lens-f-lab-${curSet}`]) { const fd = document.querySelector(`${id} feDisplacementMap`); if (fd) fd.setAttribute("scale", String(sOf(id))); }   // the file's rest value; the layers are hidden now
    for (const k of ["transition", "left", "top", "width", "height", "margin", "border-radius", "transform", "transform-origin"]) lens.style.removeProperty(k);   // the CSS rest values are what the loop ended on
    for (const el of [stack, warp, warpl, plat, rimb, rimo, ...hls]) { el.style.removeProperty("transform"); el.style.removeProperty("transform-origin"); }
    if (GL) { try { glo.lens.setState({ cx: 0, cy: 0, w: W0, h: H0, lift: 0 }); } catch (e) {} glo.canvas.style.removeProperty("transform"); glo.canvas.style.removeProperty("transform-origin"); }   // the canvas cleared: the DOM platter shows
    if (curSet) { const f = document.querySelector(`#seg-lens-f-ab-${curSet}`); if (f) { const S = parseFloat(f.getAttribute("data-s")) || 12, taps = f.querySelectorAll("feDisplacementMap"), n = taps.length; taps.forEach((t, i) => t.setAttribute("scale", (S * (1 - 2 * i / (n - 1))).toFixed(3))); } }   // the file's rest values
    st.done = true; if (seg.__lensLoop === loop) seg.__lensLoop = null;
    if (st.__lens && window.__segLens === st.__lens) window.__segLens = st.__lens = { ...st.__lens, phase: "done" };   // 仪器: the last state stays readable, marked done
  };
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const tick = (now) => {
    if (st.done) return;
    if (!seg.isConnected || !lens.isConnected) { clear(); return; }
    const tickStart = performance.now(), cxBefore = st.cx, pendingBefore = st.pending;
    const dt = Math.min(.04, Math.max(0, (now - st.prev) / 1000)); st.prev = now;
    let p, pd, moving = false, liftedModel = false;   // liftedModel: the MODEL bounds are 220×44 (setLifted:YES … actuallySetLifted:NO) — the flex spec and W/H follow the model, as a step (§7.4)
    if (st.tap) {
      /* 点按 (SEG_TAP_T, s after the up): geometry lifts in place on the lift spring, material follows 10 ms later, the position springs to the target
         on the value-change spring; at +443 / +450 both fall (geometry ζ1/.25, material ζ1/.4); DestOut rides the material (§4.4: 0 → 1 with the
         lift material, 1 → 0 with the fall material) */
      const tu = (now - st.t0) / 1000, T = SEG_TAP_T;
      liftedModel = tu >= T.geo && tu < T.fallGeo;
      if (tu >= T.geo) springStep(st.sL, tu >= T.fallGeo ? 0 : 1, SEG_SPRING.lift, dt);
      if (tu >= T.mat) springStep(st.sMt, tu >= T.fallMat ? 0 : 1, tu >= T.fallMat ? SEG_SPRING.fallMaterial : SEG_SPRING.lift, dt);
      if (tu >= T.travel) springStep(st.pos, restCentre(st.rest), SEG_SPRING.travel, dt);
      p = clamp01(st.sMt.x); pd = p; st.pr = p;
      const fx = st.flex.out, settled = tu > T.fallMat + .1 && st.sL.x < .001 && st.sMt.x < .001 && Math.abs(st.pos.x - restCentre(st.rest)) < .05 && Math.abs(st.pos.v) < 1 && Math.abs(fx.sx - 1) < .001 && Math.abs(fx.sy - 1) < .001 && Math.abs(fx.dx) < .05;
      if (settled || tu > 3) { clear(); return; }
    } else if (st.rel == null) {
      const tl = (now - st.t0) / 1000 - liftDelay;   // time since the lift started (+109 ms)
      liftedModel = tl > 0;
      if (tl > 0) springStep(st.sL, 1, SEG_SPRING.lift, dt);
      if (st.dragged && st.cx != null) springStep(st.pos, st.cx, SEG_SPRING.model, dt);   // B5-b: the position is ONE spring ζ .85 / .2 s continuing from its value and velocity at every retarget (§6 retarget 语义) — the ζ .6533/.4559 tracking spring belongs to the flex floats, not to the position
      /* B5-c time base (flex-interaction.md §6e.2 / §6e.3, the UIUpdate cycle's order HIDEvents → CADisplayLinks → CATransactionCommit → next vsync):
         a move delivered at T (between frames) → cycle V_{j+1}: the handler builds the new spring behaviour, AnimationKit evaluates it at t = 0 from the
         current (x, v) (value unchanged), commit → screen V_{j+2} still the old value → cycle V_{j+2} evaluates t = 16.7 ms → screen V_{j+3} shows the
         first displacement. Here: the tick R_{j+1} (first rAF after the move) integrates its interval with the old target (= the value at t = 0 of the
         new behaviour), then adopts the move as the target below; R_{j+2} integrates 16.7 ms toward it; a tick's frame is displayed one vsync later, so
         the screen shows old / old / first displacement at V_{j+1} / V_{j+2} / V_{j+3} — the probe's sample sequence .5887 = 120, .6054 = 120,
         .6220 = 122.04 for the move at .5787 (§6e.2). Replayed literally on the probe's display-frame grid (tools/touch/b5c/dragsim_ours2.py): this
         rule rms 1.11 / max 2.54 over .60–.86 s (= the judge's grid+1, fork_judge.py); adopting one tick later 13.5 / 19.6; Euler instead of the
         analytic step 2.58 / 3.50. */
      if (st.pending != null) { st.cx = st.pending; st.pending = null; }
      p = clamp01(st.sL.x); pd = tl <= 0 ? 0 : Math.max(p > 0 ? tabAt(K_LIFT_DEST, tl) : 0, p > 0.5 ? 1 : 0);   // --ios-touch-segment-destout-keys (first 3 frames)
      st.pr = p; moving = true;
    } else {
      const tr = (now - st.rel) / 1000;
      liftedModel = st.pr > 0 && tr < relDelay;   // the fall animation (model bounds → 196×28) is created at release + relDelay
      if (tr >= relDelay) { springStep(st.sL, 0, SEG_SPRING.lift, dt); springStep(st.sM, 0, SEG_SPRING.fallMaterial, dt); }
      springStep(st.pos, restCentre(st.rest), SEG_SPRING.travel, dt);   // after the up: one spring ζ .85 / .4 s to the segment the lens ends on (§4.4 换值行程 row); the ζ .56/.444 "settle" spring is the flex's smallLoupe scale/drift spring once the lens is 196×28 (flexSpec)
      p = st.pr * clamp01(st.sM.x); pd = tr <= destDelay ? 1 : tabAt(K_DEST, tr - destDelay);
      const fx = st.flex.out, settled = Math.abs(st.pos.x - restCentre(st.rest)) < .05 && Math.abs(st.pos.v) < 1 && st.sL.x < .001 && st.sM.x < .001 && Math.abs(fx.sx - 1) < .001 && Math.abs(fx.sy - 1) < .001 && Math.abs(fx.dx) < .05;
      if ((tr >= destEnd && settled) || tr > 3) { clear(); return; }
    }
    /* B5 — the flex interaction, once per frame: the model bounds are the lift's (196×28 → 220×44), the presentation centre = the position spring + the
       flex drift goes into the integrator, updateFlex sets the targets, the three animatable floats follow on spec.scaleSpring (tracking while the finger is
       down), the result is the presentation transform */
    const q = clamp01(st.sL.x), w = W0 + 2 * LX * q, h = H0 + 2 * LY * q, fl = st.flex;
    fl.vi.add(st.pos.x + fl.out.dx, now / 1000);   // the presentation centre = position + flex drift (the update link reads the presentation layer, §1)
    /* §7.4 (老网页 13:2x): preferredVariant 4 = liquidLensWithSize:(_UILiquidLensView.bounds) recomputed per frame from the MODEL bounds — a step 196×28 ↔ 220×44 at
       setLifted:YES / actuallySetLifted:NO, not the presented size; the same W / H feed the targets' per-axis range and the drift (§3: W, H = view.bounds) */
    const Wm = liftedModel ? W0 + 2 * LX : W0, Hm = liftedModel ? H0 + 2 * LY : H0;
    const spec = flexSpec(Wm, Hm), tg = flexTargets(spec, Wm, Hm, fl.vi.acceleration, fl.vi.velocity), sp = st.rel == null ? [spec.tzeta, spec.tresp] : [spec.zeta, spec.resp];
    springStep(fl.sx, tg.sX, sp, dt); springStep(fl.sy, tg.sY, sp, dt); springStep(fl.dx, tg.drift, sp, dt);
    fl.out = { sx: fl.sx.x, sy: fl.sy.x, dx: fl.dx.x };   // B5-d: the presented values are the spring floats, unclamped (the [0.9, 1.1] clamp is on the targets in flexTargets; §6f.4)
    setGeo(st.pos.x - w / 2, CY - h / 2, w, h);
    frame(p, pd);
    /* 仪器: what this tick used and produced — window.__segLens for the frame recorder (names: see the note at segActiveLoop) */
    st.ticks++; const adopted = pendingBefore != null && st.cx === pendingBefore; if (adopted && st.cx !== cxBefore) st.retargetT = tickStart;
    const r3 = (q) => Math.round(q * 1000) / 1000, r2 = (q) => Math.round(q * 100) / 100;
    window.__segLens = st.__lens = { t: r2(tickStart), raf_t: r2(now), tick: st.ticks, dt: Math.round(dt * 100000) / 100000, tick_ms: r2(performance.now() - tickStart),
      x: r3(st.pos.x), v: Math.round(st.pos.v * 10) / 10, target: cxBefore == null ? null : r3(cxBefore), target_next: st.cx == null ? null : r3(st.cx), adopted: adopted ? 1 : 0, retarget_t: st.retargetT == null ? null : r2(st.retargetT),
      pointer_t: st.ev.t == null ? null : r2(st.ev.t), pointer_ev_t: st.ev.evt == null ? null : r2(st.ev.evt), pointer_x: st.ev.x == null ? null : r2(st.ev.x), pointer_target: st.ev.target == null ? null : r2(st.ev.target), pointer_n: st.ev.n,
      drift: r3(fl.out.dx), x_screen: r3(st.pos.x + fl.out.dx), sx: Math.round(fl.out.sx * 10000) / 10000, sy: Math.round(fl.out.sy * 10000) / 10000, accel: Math.round(fl.vi.acceleration), vel: Math.round(fl.vi.velocity),
      p: Math.round(p * 10000) / 10000, set: curSet || 0, rel_t: st.rel == null ? null : r2(st.rel), phase: st.tap ? "tap" : st.rel != null ? "release" : st.dragged ? "drag" : p < 1 ? "lift" : "hold",
      gl_trace: GL && glo.lens.stats.trace ? JSON.stringify(glo.lens.stats.trace) : null };   // ?gltrace=1 (lens-webgl.js e1e5633): this frame's per-step gl.finish ms (bindFbo_useP1 / uniforms_binds1 / pass1 / clear_useP2 / uniforms_binds2 / pass2, set, total) as a JSON string — the recorder copies numbers and strings only; null otherwise
    st.ev.n = 0;   // moves consumed since the previous tick (the last move's fields stay until the next move)
    if (st.ticks === 1) segMeasure("seg:first-tick", tickStart);
    st.raf = requestAnimationFrame(tick);
  };
  const loop = {
    drag: (clientX, evTs) => {   // a finger move (§6): target = the pressed segment's centre + (finger x − touch-down x), adopted at the next tick (see the tick's time-base note); past an end segment's own centre the excess is rubber-banded (§6 0x1c41358bc–0x1c4135978, see the header)
      if (st.rel != null || st.done) return;
      const evNow = performance.now();
      const x = clientX - seg.getBoundingClientRect().left, delta = Number.isNaN(downX) ? x - restCentre(idx0) : x - downX, c = restCentre(idx0), raw = c + delta;
      const rubber = (o) => 12 * (1 - 1 / (1 + .55 * o / 12));   // (1 − 1/(c·o/d + 1))·d with c .55, d 12
      st.pending = n === 1 ? c : (idx0 === 0 && raw < c) ? c - rubber(c - raw) : (idx0 === n - 1 && raw > c) ? c + rubber(raw - c) : raw;
      st.ev = { t: evNow, evt: evTs == null ? null : evTs, x, target: st.pending, n: st.ev.n + 1 };   // 仪器: the move the loop consumed (window.__segLens pointer_*)
      if (!st.dragged) st.dragged = true;
    },
    release: (restIdx) => {   // every way out — up, out of bounds, pointercancel — falls the same way, to the rest rect of `restIdx`
      if (st.rel != null || st.done) return;
      st.rel = performance.now(); st.rest = restIdx;
    },
    stop: () => { cancelAnimationFrame(st.raf); if (!st.done) clear(); },
    freeze: () => { cancelAnimationFrame(st.raf); },   // ?segtap=<ms> (index.html hook): hold the current frame for a snapshot
    step: (dtMs) => { if (!st.done) { cancelAnimationFrame(st.raf); tick(dtMs ? st.prev + dtMs : performance.now()); } },   // one frame by hand, optionally on a virtual clock (an offscreen WKWebView runs neither requestAnimationFrame nor timers at speed; the ?seghold hook drives it)
    get state() { return { dragged: st.dragged, cx: st.cx, pending: st.pending, pos: st.pos.x, q: st.sL.x, rel: st.rel, done: st.done, flex: st.flex.out, accel: st.flex.vi.acceleration }; },
    get diag() { return st.__lens || null; },
  };
  loop.cancel = loop.release;
  if (prewarm) {   // A 起手预建: the layers exist now and stay painted invisibly (.prewarm: display, opacity .01), so their compositing layers and filter pipeline are alive when the first press comes (the press removes .prewarm and lifts them)
    /* 预建 2 (数据 36916a9: the first glass frame still stalled 30–72 ms after a rest-state prewarm — at scale 0 the displacement is skipped): two frames in
       the LIFTED state — the model box 220×44 at the rest position, progress 1 (displacement scale S on both maps, the label filter, the inner-shadow and
       ring-shadow blurs evaluated for real, the maps decoded) — then back to rest; the white .lens is never touched (frame()'s .lift class is removed at once) */
    if (GL) { const s = glo.lens.sets[glo.setW]; const warm = () => { try { glo.lens.setState({ cx: pad + idx0 * PITCH + W0 / 2, cy: SEG_GLM + pad + H0 / 2, w: W0 + 2 * LX, h: H0 + 2 * LY, lift: 1, wh: 1.35 }); glo.lens.setState({ cx: 0, cy: 0, w: W0, h: H0, lift: 0 }); } catch (e) {} seg.__prewarmed = performance.now(); };
      if (s && s.ready) s.ready.then(() => requestAnimationFrame(warm)); else requestAnimationFrame(warm); st.done = true; return loop; }   // WebGL prewarm: shaders + maps + one lifted frame (FBO, pipeline), then cleared
    st.geo = { left: pad + idx0 * PITCH - LX, top: pad - LY, w: W0 + 2 * LX, h: H0 + 2 * LY }; frame(1, 1); seg.classList.remove("lift");
    seg.classList.add("prewarm"); seg.__prewarmed = performance.now(); st.done = true;
    requestAnimationFrame(() => requestAnimationFrame(() => { if (!seg.isConnected || !seg.classList.contains("prewarm")) return; st.geo = null; frame(0, 0); seg.classList.remove("lift"); }));
    return loop;
  }
  seg.__lensLoop = loop; segActiveLoop = loop;
  if (deferred) {   // built at the down; the up arms the tap schedule (or stops it): nothing runs or shows until then
    loop.beginTap = (target, upAt) => { if (st.done || st.tap) return; st.tap = { target, upAt }; st.t0 = upAt; st.rel = upAt; st.rest = target; st.prev = performance.now(); st.raf = requestAnimationFrame(tick); };
    return loop;
  }
  st.raf = requestAnimationFrame(tick);
  return loop;
}
/* A 起手预建: schedule the build + invisible paint for a control once it exists — after the page's first frames, in an idle slot, and after the engine
   correction has swapped the maps (so the painted filters are the ones the press will use). ?prewarm=0 leaves it out. */
function segPrewarm(seg, bs, lens) {
  if (!lens || seg.__prewarmQueued || new URLSearchParams(location.search).get("prewarm") === "0") return;
  seg.__prewarmQueued = true;
  const go = () => { if (!seg.isConnected || seg.querySelector(".warp") || (seg.__lensLoop && !seg.__lensLoop.state.done)) return; const t = performance.now(); performance.mark("seg:prewarm"); segLens(seg, lens, bs, NaN, { prewarm: true }); segMeasure("seg:prewarm-build", t); };
  const idle = () => { if (window.requestIdleCallback) requestIdleCallback(go, { timeout: 600 }); else setTimeout(go, 200); };
  const after = () => requestAnimationFrame(() => requestAnimationFrame(idle));
  /* the WebGL lens does not use the SVG maps the engine fix re-encodes (a fetch + decode per map, long on the phone): with GL available the build runs at the
     first idle slot after load instead of waiting for that event — 2号 18:4x: the first gesture after load still paid seg:build 30 ms (the layers + the GL
     instance built at the down), the second 0 ms */
  if (segGlAvailable() || window.LENS_ENGINE_FIX_DONE || window.LENS_ENGINE_FIX === false) after(); else addEventListener("lens-engine-fix", after, { once: true });
}
function attachSegmented(seg, getIndex, commit) {
  const bs = [...seg.querySelectorAll("button")], lens = seg.querySelector(".lens"), n = bs.length;
  segPrewarm(seg, bs, lens);   // A 起手预建: the lens layers built and painted once before the first touch
  const segAt = (x) => { const r = seg.getBoundingClientRect(); return Math.max(0, Math.min(n - 1, Math.floor((x - r.left) / (r.width / n)))); };   // 跨分隔线即换目标（G22/G24/G25）
  const outside = (x, y) => { const r = seg.getBoundingClientRect(), s = touchPx("--ios-touch-inside-slop", 70); return x < r.left - s || x > r.right + s || y < r.top - s || y > r.bottom + s; };
  const showLens = (i) => seg.style.setProperty("--i", String(i));
  seg.onpointerdown = (e) => {
    const idx = getIndex(), pressed = segAt(e.clientX), onSelected = pressed === idx;
    let liftTimer = 0, glass = null;
    if (lens) lens.classList.remove("spring");   // a new touch ends the previous commit's stretch (G12/G13: no queueing)
    if (!press(seg, e, {
      move: (ev) => { if (onSelected && glass && lens && lens.classList.contains("lift")) glass.drag(ev.clientX, ev.timeStamp); },   // the lifted lens follows the finger (edge springs); the index never changes while sliding (G4/G22)
      end: (ev, cancelled) => {
        clearTimeout(liftTimer);
        const lifted = !!(lens && lens.classList.contains("lift"));   // patch 03 (seg-impl-review.md #3): a lifted lens commits by falling + gliding (G4/G21), a tap commits with the stretch sequence (G1/G3)
        bs[pressed].classList.remove("dim");                        // label back to 1 in .1 s (G12)
        seg.classList.remove("drag"); if (lens) lens.classList.remove("lift");
        const target = segAt(ev.clientX), noEvent = cancelled || outside(ev.clientX, ev.clientY) || target === idx;   // cancel (> 70 pt out, G17/G18) or back on the selected one (G8/G10/G23): no event
        if (glass && !glass.beginTap) glass.release(noEvent ? idx : target);   // glass, copies and geometry fall on the lens's own curve, to the rest rect it ends on
        if (noEvent) { if (glass && glass.beginTap) glass.stop(); showLens(idx);
          if (seg.__gl && seg.__gl.gs.futureOn != null) { seg.__gl.gs.futureOn = null; requestAnimationFrame(() => segGlRedraw(seg)); }   // the speculative labels texture undone (nothing was lifted)
          return; }
        if (!lifted && !onSelected && lens) {   // 点按外观: the tap runs the lift chain from the up (SEG_TAP_T) — glass in place, glass slide, solid again on settling; the loop owns the lens, segSync skips the old CSS slide
          const tUp = performance.now(), upAt = ev.timeStamp > 0 && ev.timeStamp <= tUp ? ev.timeStamp : tUp; performance.mark("seg:tap-up");
          if (glass && glass.beginTap) glass.beginTap(target, upAt); else segLens(seg, lens, bs, NaN, { target, upAt });   // the loop was built at the down (deferred); arm it — or build now if the down had none
          segMeasure("seg:tap-arm", tUp); }
        commit(target, lifted ? "drag" : "tap");                    // the up: the index changes now (G1–G3); a tap's content switches in this task (wire(): SEG_VC_NOW), a slide's at +25 ms; the lens's slide is the loop's (SEG_TAP_T.travel)
      },
    })) return;
    seg.dataset.pe = "1";
    if (!onSelected) { bs[pressed].classList.add("dim");           // G15: only the label dims; no highlight, no lens move, no value
      if (lens) { const tBuild = performance.now(); performance.mark("seg:down"); glass = segLens(seg, lens, bs, NaN, { deferred: true }); segMeasure("seg:build", tBuild);
        if (seg.__gl && seg.__gl.gs.futureOn !== pressed) { const tU = performance.now(); seg.__gl.gs.futureOn = pressed; segGlRedraw(seg); segMeasure("seg:gl-upload", tU); } } }   // WebGL: the backdrop textures for the tap's outcome uploaded now (and prewarmed by the package), not at the value flip   // the tap's build work at the down (copies, labels, SVG state); the up only arms the schedule
    else {
      const tBuild = performance.now(); performance.mark("seg:down");
      glass = lens ? segLens(seg, lens, bs, e.clientX, null, e.timeStamp) : null; segMeasure("seg:build", tBuild);   // 仪器: DOM / SVG construction of the lens layers     // the loop: glass, copies, geometry — the lift itself starts at +109 ms (G4/G16); the down x is the drag delta's origin (B5-c)
      liftTimer = setTimeout(() => { if (lens) lens.classList.add("lift"); seg.classList.add("drag"); }, touchMs("--ios-touch-segment-lift-delay", 109));   // 抬起 +109 ms 起动 ← seg-keys.css --ios-touch-segment-lift-delay（seg-lens-refraction §4.1）
    }
  };
  // The browser's click after our pointerup is redundant; keyboard / synthetic clicks still select.
  for (const b of bs) b.onclick = () => { if (seg.dataset.pe) { delete seg.dataset.pe; return; } const i = bs.indexOf(b); if (i !== getIndex()) commit(i); };
}
/* §2 UITabBar: pressing an unselected tab starts the lens gliding to it after 140 ms (lifted 119×64), a hold does not select, the up selects
   the tab under the finger's x (no distance cancel - 450 pt away still selects); pressing the selected tab lifts the lens and a drag moves it,
   releasing on the original tab is no event. */
const tabScroll = {};   // Behaviour 3: scroll offset per tab
/* Behaviour 3: scroll-to-top on tapping the selected tab — UIScrollView's system curve, measured on Health (remote-ref/tabscroll/README.md §2,
   采样, 逐帧): critical spring ω ≈ 12 /s (0.2 s 71 %, 0.33 s 92 %, 0.5 s 98 %, ~0.7 s stop). Not scrollTo({behavior:"smooth"}) — that is the
   browser's own curve. */
function springToTop() {
  const y0 = window.scrollY; if (!(y0 > 0.5)) return;
  const w = 12, t0 = performance.now();
  const f = (now) => { const t = (now - t0) / 1000, y = y0 * (1 + w * t) * Math.exp(-w * t); if (y < 0.5) { window.scrollTo(0, 0); return; } window.scrollTo(0, y); requestAnimationFrame(f); };
  requestAnimationFrame(f);
}
function attachTabBar(nav, select) {
  const seg = nav.querySelector(".seg"), g = nav.querySelector(".glide"), bs = [...seg.querySelectorAll("button")];
  if (!seg || !g || !bs.length) return;
  const itemAt = (x) => { let best = 0, d = Infinity; bs.forEach((b, i) => { const r = b.getBoundingClientRect(); const dd = x < r.left ? r.left - x : x > r.right ? x - r.right : 0; if (dd < d) { d = dd; best = i; } }); return best; };
  const liftTo = (i, cls) => { g.classList.add(cls); g.style.left = bs[i].offsetLeft + "px"; g.style.width = bs[i].offsetWidth + "px"; };
  seg.onpointerdown = (e) => {
    const cur = bs.findIndex((b) => b.classList.contains("on")), pressed = itemAt(e.clientX), onSelected = pressed === cur;
    let timer = 0, lifted = false, movedAway = false;
    if (!press(seg, e, {
      move: (ev) => { if (itemAt(ev.clientX) !== cur) movedAway = true; if (lifted) { nav.classList.add("drag"); liftTo(itemAt(ev.clientX), onSelected ? "lift-sel" : "lift"); } },   // T4/T9/T11: lens follows (110×70 while dragging), value waits for the up
      end: (ev, cancelled) => {
        clearTimeout(timer); g.classList.remove("lift", "lift-sel"); nav.classList.remove("drag");
        const target = cancelled ? cur : itemAt(ev.clientX);
        if (target === cur) {
          g.style.left = bs[cur].offsetLeft + "px"; g.style.width = bs[cur].offsetWidth + "px";
          if (onSelected && !cancelled && !movedAway) springToTop();   // Behaviour 3: a tap on the selected tab scrolls its page to the top (Health, tabscroll §2); still no selection event (T3)
          return;                                                    // T3/T9: no selection event
        }
        select(bs[target]);                                          // T1/T2: +0–2 ms after the up
      },
    })) return;
    seg.dataset.pe = "1";
    timer = setTimeout(() => { lifted = true; liftTo(pressed, onSelected ? "lift-sel" : "lift"); },
      onSelected ? touchMs("--ios-touch-tab-selected-lift-delay", 125) : touchMs("--ios-touch-tab-glide-delay", 140));   // T1: +140 ms glide 119×64 / T3: selected lifts +125 ms → 103×63 by +180
  };
  for (const b of bs) b.onclick = () => { if (seg.dataset.pe) { delete seg.dataset.pe; return; } if (!b.classList.contains("on")) select(b); };
}
/* §4 UIButton / alert action: highlighted at touch-down, stays while the finger is within 70 pt of the edge (alert actions: 0 pt, and the
   highlight moves to the neighbour under the finger), triggers at the up when inside, never on a cancel. The browser's own click is swallowed
   because we fire our own (so a release 50 pt outside still triggers, as UIKit does). */
function installPressables() {
  const SEL = ".tile, .acts button, .capsule, #pendbar button";
  let synthetic = false, ghost = false;
  document.addEventListener("pointerdown", (e) => {
    const el = e.target.closest && e.target.closest(SEL); if (!el || el.disabled) return;
    const inAlert = !!el.closest("dialog");
    const slop = inAlert ? touchPx("--ios-touch-alert-slop", 0) : touchPx("--ios-touch-inside-slop", 70);
    const group = inAlert ? [...el.parentElement.querySelectorAll("button")] : [el];
    const inside = (b, x, y) => { const r = b.getBoundingClientRect(); return x >= r.left - slop && x <= r.right + slop && y >= r.top - slop && y <= r.bottom + slop; };
    let cur = el;
    if (!press(el, e, {
      move: (ev) => { const hit = group.find((b) => inside(b, ev.clientX, ev.clientY)) || null; if (hit !== cur) { if (cur) cur.classList.remove("pressed"); cur = hit; if (cur) cur.classList.add("pressed"); } },   // U3–U6 / A3–A5
      end: (ev, cancelled) => {
        if (cur) cur.classList.remove("pressed");
        const hit = cancelled ? null : group.find((b) => inside(b, ev.clientX, ev.clientY));
        ghost = true;                                                 // the browser's own click for this up is next; wherever it lands, it is not a second tap
        setTimeout(() => { delete el.dataset.pe; ghost = false; }, 0);   // the browser's click (if any) arrives before this
        if (hit) { synthetic = true; try { hit.click(); } finally { synthetic = false; } }   // U1–U5: touchUpInside +0–1 ms
      },
    })) return;
    el.dataset.pe = "1"; el.classList.add("pressed");               // U1/U2: highlighted within a frame
  });
  document.addEventListener("click", (e) => {
    if (synthetic) return;
    /* 2026-09-18 数据会话 862de97 实拍：点弹窗「取消」后紧接着弹出「现在跑一趟?」——我们在 pointerup 就关了弹窗，浏览器随后补的 click
       落到弹窗底下的磁贴上，开出第二个弹窗。这一下 click 不管落在谁身上都吞掉。 */
    if (ghost) { ghost = false; e.preventDefault(); e.stopImmediatePropagation(); return; }
    const el = e.target.closest && e.target.closest(SEL);
    if (el && el.dataset.pe) { e.preventDefault(); e.stopImmediatePropagation(); delete el.dataset.pe; }
  }, true);
}

function installNative() {
  // 开关的动效只在被人摸过之后才播（.live），页面重画时不会每个开关都弹一下
  /* The switch behaves like UISwitch: finger down shows the glass lens (.hold), the
     knob follows a drag, release snaps - past the middle after a drag, or to the
     other side for a tap. Long holds must not fall into Safari's own long-press
     handling (the 2026-09-15 11:20 recording: a 0.9 s hold flipped nothing), so
     the pointer is captured and the click is synthesised. */
  document.addEventListener("pointerdown", (e) => {
    const sw = e.target.closest && e.target.closest(".sw"); if (!sw) return;
    const input = sw.querySelector("input"); if (!input || input.disabled) return;
    e.preventDefault();
    /* The browser still fires its own click after pointerup, and a click on a
       checkbox toggles it - so a plain tap toggled twice (mine, then the
       browser's) and ended where it started. 2026-09-15 12:0x on his Android:
       「单击没办法开关了，只能长按拖动」. The click that follows this press is
       swallowed; keyboard activation (no pointer press first) still works. */
    sw.dataset.pe = "1";
    /* spec §3 (interaction-spec.md): the knob lifts +195 ms after touch-down (--ios-touch-switch-lift-delay), follows a drag and may
       stretch 7 pt past either end; the value flips at the up whatever the position or direction - the ONLY no-flip case is the knob
       dragged beyond the far end (finger displacement > the 22 pt travel) and then back inside. pointercancel = no flip. */
    const startOn = input.checked, x0 = e.clientX; let dx = 0, maxOut = 0;
    const T = 22, OVER = 7;   // travel 63 − 37 − 2×2 = --ios-switch-travel; stretch past the ends (spec §3 X11)
    const home = startOn ? T : 0;
    sw.style.setProperty("--kx", home + "px");
    const lift = setTimeout(() => sw.classList.add("live", "hold"), touchMs("--ios-touch-switch-lift-delay", 195));
    const move = (ev) => {
      dx = ev.clientX - x0; const toward = startOn ? -dx : dx; maxOut = Math.max(maxOut, toward);
      sw.style.setProperty("--kx", Math.max(-OVER, Math.min(T + OVER, home + dx)) + "px");
    };
    const finish = (cancelled) => {
      clearTimeout(lift); sw.removeEventListener("pointermove", move); sw.removeEventListener("pointerup", up); sw.removeEventListener("pointercancel", cancel);
      sw.classList.remove("hold"); sw.style.removeProperty("--kx");
      if (cancelled) return;
      const final = startOn ? -dx : dx;
      const noFlip = maxOut > T && final <= T;   // beyond the far end and back (spec §3 N2–N4 / RO); beyond and released there still flips (X11)
      if (noFlip) return;
      input.checked = !startOn; input.dispatchEvent(new Event("change", { bubbles: true }));
    };
    const up = () => finish(false), cancel = () => finish(true);
    sw.addEventListener("pointermove", move);
    sw.addEventListener("pointerup", up);
    sw.addEventListener("pointercancel", cancel);
    try { sw.setPointerCapture(e.pointerId); } catch {}
  });
  installPressables();
  document.addEventListener("click", (e) => {
    const sw = e.target.closest && e.target.closest(".sw");
    if (sw && sw.dataset.pe) { e.preventDefault(); delete sw.dataset.pe; }
  }, true);
  const bar = $("#topbar"), h1 = document.querySelector("header h1");
  if (bar && h1) {
    const root = document.documentElement;
    /* Measured on the simulator's recording of Settings (2026-09-15 05:04, a slow
       drag): the large title fades out while it slides under the bar, and the
       small title fades in only once the large one is gone - one after the
       other, not a cross-fade. --big drives the large title, --title the small. */
    const clamp = (v) => Math.max(0, Math.min(1, v));
    const onScroll = () => {
      const y = window.scrollY;
      const top = h1.offsetTop, hgt = h1.offsetHeight || 41;
      root.style.setProperty("--bar", String(clamp(y / 12)));
      root.style.setProperty("--big", String(clamp((y - top + 24) / (hgt * 0.9))));
      root.style.setProperty("--title", String(clamp((y - top - hgt * 0.5) / (hgt * 0.6))));
    };
    addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }
  const ptr = $("#ptr");
  let y0 = null, pulled = 0, armed = false;
  const THRESH = 72;
  addEventListener("touchstart", (e) => { y0 = (window.scrollY <= 0 && e.touches.length === 1) ? e.touches[0].clientY : null; pulled = 0; armed = false; }, { passive: true });
  addEventListener("touchmove", (e) => {
    if (y0 === null || !ptr) return;
    pulled = e.touches[0].clientY - y0;
    const on = pulled > THRESH;
    if (on !== armed) { armed = on; ptr.classList.toggle("arm", on); }
  }, { passive: true });
  addEventListener("touchend", () => {
    const ai = $("#ptrai");
    if (armed && ptr) { ptr.classList.add("go"); if (ai) ai.classList.add("on"); ping().finally(() => { ptr.classList.remove("go", "arm"); if (ai) ai.classList.remove("on"); }); }
    else if (ptr) ptr.classList.remove("arm");
    y0 = null; armed = false;
  }, { passive: true });
  // 「x 分钟前」 every 30 s, only while the page is visible; no network.
  setInterval(() => {
    if (document.hidden || !snap) return;
    const t = ago(snap.at);
    const sub = document.querySelector("#refresh .tsub");
    if (sub) sub.textContent = t;
    const s2 = $("#status2");
    if (s2 && /前/.test(s2.textContent)) s2.textContent = s2.textContent.replace(/[0-9]+ (秒|分钟|小时 [0-9]+ 分|天)前/, t);
  }, 30000);
}
addEventListener("DOMContentLoaded", installNative);


/* ?accept 模式（docs/HIG-CHECKLIST.md 的验收程序）：没有信箱凭据也要把每个块画出来给 accept.js 量，
   所以用内置的演示快照（两条队列、一条待应用、体力三格、回执），不碰网络，设备行名字写「演示数据」。
   有真凭据时照常走真数据。 */
const DEMO = (new URLSearchParams(location.search).has("accept") || new URLSearchParams(location.search).has("demo")) && !localStorage.getItem(LS);   // ?demo=1：只要演示数据、不跑 accept.js（截图用；accept 的交互回放会切分段/标签）
function demoSnapshot() {
  const at = now() - 180;
  return { at, config: { MAA: { "关卡": "1-7", "理智药": 0, "作战开关": true, "活动关优先": true, "活动关序号": 1 } },
    run: { "服务": true, "在跑的": [] },
    queues: [{ "名": "早班", "脚本": ["MAA", "MaaEnd", "OK-WW"], "定时": true, "时刻": "09:00" }, { "名": "晚班", "脚本": ["MAA"], "定时": true, "时刻": "21:30" }],
    relay: { "调试模式": "15:50", "刷声骸": {}, "下次别关机": true, "今天跳过": "", "无音区截图": true,
             "最近指令": [{ at: "09-17 21:35", action: "set_config", ok: true, text: "关卡 1-7 → 活动关 已写入（演示）" }, { at: "09-17 21:40", action: "run_now", ok: false, text: "晚班没开始：机器在忙（演示）" },
                        { at: "09-18 09:02", action: "run_now", ok: true, text: "已开始早班（演示）" }, { at: "09-18 14:22", action: "set_config", ok: true, text: "理智药 0 → 3 已写入（演示）" }, { at: "09-18 14:31", action: "run_now", ok: true, text: "已开始早班（演示）" }],
             "周本": {}, "周常": {} },
    plan: "📅 明日安排\n🕘 09:00　东京 10:00\n▸ 明日方舟\n理智 1-7（固定）\n理智药 0 瓶\n▸ 终末地\n基质刷取 双倍，最多 6 轮\n▸ 鸣潮\n凝素领域 第 4 个\n🕘 21:30　东京 22:30\n▸ 明日方舟\n理智 1-7（固定）",
    "今天": { "跑了": 2, "失败": 0, "最近": "鸣潮" }, master: DEMO_MASTER, options: {} };
}
/* 演示用的母本（仅 ?demo / ?accept 且没配信箱时）。结构与真快照一致：master[game] = {values, options, labels, readonly}；
   路径 = SCHEMA 的 path；MaaEnd 的 case 名与中文名由 relay 的 mastercfg.read_maaend 对着 relay/tests/fixtures/maaend228（v2.28 真定义文件）读出，
   MAA 的选项与中文名 = mastercfg.MAA_DRONES / MAA_AWARD，OK-WW 的 case 名与译名 = docs/AUTOMAS.md（Forgery Challenge = 凝素领域、Tacet Suppression = 无音区）。
   v2.28 定义里没有 beta.5 才拆出的 AutoCollectValleyIV / Wuling / Mode，所以演示里不放它们。 */
const DEMO_MASTER = {"MAA":{"values":{"Infrast/UsesOfDrones":"Money","Award/Mail":true,"Award/Orundum":false,"Award/Mining":true,"Award/SpecialAccess":false},"options":{"Infrast/UsesOfDrones":[["贸易站 · 龙门币","Money"],["贸易站 · 合成玉","SyntheticJade"],["制造站 · 作战记录","CombatRecord"],["制造站 · 赤金","PureGold"],["制造站 · 源石碎片","OriginStone"],["制造站 · 芯片","Chip"]]},"labels":{"Infrast/UsesOfDrones":"基建无人机用在哪","Award/Mail":"领取所有邮件奖励","Award/Orundum":"领取幸运墙的每日合成玉奖励","Award/Mining":"领取限时开采许可的每日合成玉奖励","Award/SpecialAccess":"领取周年赠送月卡奖励"}},"MaaEnd":{"values":{"AutoEssence/@enabled":true,"AutoEssence/AutoEssenceDoOverride":false,"AutoEssence/AutoEssenceObtainMode":"ObtainScaling2","AutoEssence/AutoEssenceRepeatCount":"6","AutoEssence/AutoEssenceChooseLocation":["WLSwordVaultDale","WLQingboStockade"],"AutoEssence/EssenceFilterAfterBattle":true,"AutoEssence/AutoUseSpMedication":"EndTask","AutoEssence/AutoEssenceSpMedicationExpireWithinDays":"Days3","AutoCollect/@enabled":true,"AutoCollect/AutoCollectSchedule":["AutoCollectScheduleMonday","AutoCollectScheduleWednesday","AutoCollectScheduleFriday"]},"options":{"AutoEssence/AutoEssenceObtainMode":[["不领取（仅刷素材）","Discard"],["单倍领取","ObtainScaling1"],["双倍领取","ObtainScaling2"]],"AutoEssence/AutoEssenceChooseLocation":[["枢纽区","VFTheHub"],["源石研究园","VFOriginiumSciencePark"],["矿脉源区","VFOriginLodespring"],["供能高地","VFPowerPlateau"],["武陵城区","WLWulingCity"],["清波寨","WLQingboStockade"],["首墩","WLMarkerStone"],["试验园区","WLTestArea"],["藏剑谷","WLSwordVaultDale"],["应龙关","WLYinglungPass"],["北部禁区","WLNorthWulingExclusionZone"],["雪松林","WLSnowyForest"]],"AutoEssence/AutoUseSpMedication":[["结束任务","EndTask"],["使用药剂恢复","UseMedication"]],"AutoEssence/AutoEssenceSpMedicationExpireWithinDays":[["全部","All"],["10天内","Days10"],["7天内","Days7"],["3天内","Days3"],["1天内","Days1"]],"AutoCollect/AutoCollectSchedule":[["周一","AutoCollectScheduleMonday"],["周二","AutoCollectScheduleTuesday"],["周三","AutoCollectScheduleWednesday"],["周四","AutoCollectScheduleThursday"],["周五","AutoCollectScheduleFriday"],["周六","AutoCollectScheduleSaturday"],["周日","AutoCollectScheduleSunday"]]},"labels":{"AutoEssence/@enabled":"🎱基质刷取","AutoEssence/AutoEssenceDoOverride":"使用刻写券","AutoEssence/AutoEssenceObtainMode":"领取方式","AutoEssence/AutoEssenceRepeatCount":"循环执行","AutoEssence/AutoEssenceChooseLocation":"随机地区","AutoEssence/EssenceFilterAfterBattle":"战后基质筛选","AutoEssence/AutoUseSpMedication":"理智不足时","AutoEssence/AutoEssenceSpMedicationExpireWithinDays":"使用几天内","AutoCollect/@enabled":"🧺自动采集","AutoCollect/AutoCollectSchedule":"执行周期(游戏时间)"}},"OK-WW":{"values":{"DailyTask.json/Which to Farm":"Tacet Suppression","DailyTask.json/Material Selection":"Shell Credit","DailyTask.json/Which Forgery Challenge to Farm":3,"DailyTask.json/Which Tacet Suppression to Farm":2},"options":{"DailyTask.json/Which to Farm":[["凝素领域","Forgery Challenge"],["无音区","Tacet Suppression"],["模拟领域","Simulation Challenge"]],"DailyTask.json/Material Selection":[["Resonator EXP","Resonator EXP"],["Weapon EXP","Weapon EXP"],["Shell Credit","Shell Credit"]]},"labels":{},"readonly":{"NightmareNestTask.json/Only Farm These Nests":"落渊南丘"}}};
const DEMO_STAMINA = { "明日方舟": { "理智": 128, "上限": 135, "回满": "09-18 15:42" }, "终末地": { "理智": 96, "上限": 240, "回满": "09-19 02:10" },
                       "鸣潮": { "波片": 172, "上限": 240, "回满": "09-18 18:20", "备用": 480, "周本": 2, "周本上限": 3 }, "取自": "演示数据" };

async function boot() {
  fromLink();
  if (DEMO) {
    cfg = { topic: "accept-demo", pin: "0000" };
    snap = demoSnapshot();
    if (window.Stamina) { Stamina.data = DEMO_STAMINA; Stamina.at = Date.now(); }
    pending = { "relay|debug_mode": { label: "调试模式", src: "relay", path: "", from: false, to: true, sentAt: now() - 120 } };
    lastHb = Date.now(); netOk = true;
    setInterval(() => { lastHb = Date.now(); }, 1000);   // 演示数据里机器永远在线，截图不会随真实时间变成「关机 · 最后心跳」
    render(); updateLive();
    return;
  }
  const raw = localStorage.getItem(LS);
  if (!raw) return setupScreen();
  cfg = JSON.parse(raw);
  try { snap = JSON.parse(localStorage.getItem(LS + "-snap") || "null"); } catch { snap = null; }
  render();
  setStatus(snap ? `状态 ${ago(snap.at)}` : "正在读取…", "");
  // 打开页面这一下也问一次游戏（有密钥才问）
  if (window.Stamina && Stamina.loadTokens()) Stamina.refresh(false).then(() => render()).catch(() => {});
  // 先挂流再问：心跳判定、「我在看」、最新配置并行——打开即知开关机
  startLive();
  probeHb().then(() => { updateLive(); askWatch(); });
  try {
    const s = await latestState();
    if (s && (!snap || s.at > snap.at)) { snap = s; save_cache(); render(); }
    updateLive();
    if (!snap && pinScan.seen > 0 && pinScan.matched === 0) {
      setStatus(`信箱里有 ${pinScan.seen} 条消息但 PIN 对不上——检查设置里的 PIN`, "off");
    }
  } catch (e) {
    // 读不到信箱不等于机器关了，多半是这一端没网。红色的「关机中」是断言，
    // 这里没有资格下这个断言；而且 5 秒后 updateLive 还会把它换成「关机中」。
    netOk = false;
    setStatus("读不到信箱 · " + why(e) + "，先看看你这边有没有网", "");
  }
}

$("#save").onclick = doSave;
$("#discard").onclick = () => { edits = {}; render(); updateBar(); };
$("#cancel").onclick = () => $("#confirm").close();
let saving = false;          // 防连点：2026-09-01 实测连点 3 下发了 3 遍
$("#go").onclick = async () => {
  if (saving) return;
  saving = true;
  $("#confirm").close();
  // 带上 edits 里的键：发成功一项就删一项，发不出去的必须原样留在页面上。
  const all = Object.entries(edits).map(([id, e]) => ({ ...e, _id: id }));
  const wbEdits = all.filter((e) => e.src === "wb");
  const relayEdits = all.filter((e) => e.src === "relay");
  const items = all.filter((e) => e.src !== "wb" && e.src !== "relay");
  let sent = 0;
  let failed = null;           // 第一项发不出去的原因；有它就不许说「已发出」
  const doneKeys = [];         // 真发出去的那几项，只清这些
  for (const e of items) {
    const body = e.src === "master"
      ? { action:"set_master", confirmed:true, game:e.owner, path:e.path, value:e.to }
      : { action:"set_config", confirmed:true, script:e.owner, path:e.path, value:e.to };
    try {
      await send(body); sent++; doneKeys.push(e._id);
      pending[e._id] = { label:e.label, src:e.src, owner:e.owner, path:e.path,
                         from:e.from, to:e.to, sentAt: now() };
      savePending();
    }
    catch (err) { failed = err; break; }
  }
  // 中继开关：一项一条指令，寄出后挂回执
  for (const e of relayEdits) {
    try {
      await send(e.body); sent++; doneKeys.push(e._id);
      pending[e._id] = { label: e.label, src: "relay", body: e.body, to: e.to, sentAt: now() };
      savePending();
    } catch (err) { if (!failed) failed = err; }
  }
  /* 周本只剩「打第几个」一项可改；次数 3、等级 90 固定在中继里。 */
  if (wbEdits.length) {
    try {
      await send({ action:"weekly_boss", index: Number(wbEdits[wbEdits.length - 1].to) || 1 });
      sent += wbEdits.length;
      for (const w of wbEdits) doneKeys.push(w._id);
    } catch (err) { if (!failed) failed = err; }
  }
  // 发出去的清掉，没发出去的原样留在页面上——原来只要成功过一项就 `edits = {}`，
  // 剩下的改动连同它们的提示一起消失（两次 toast 用的是同一个元素，后一次会把
  // 前一次的错误文本盖掉，那句话实际停留 0 毫秒）。他会以为全发了。
  for (const k of doneKeys) delete edits[k];
  updateBar(); render();
  if (failed) {
    const left = Object.keys(edits).length;
    toast(sent
      ? `发出去 ${sent} 项，剩下 ${left} 项没发出去（${why(failed)}）。没发出去的还在页面上，可以再按一次保存。`
      : `一项都没发出去（${why(failed)}）。改动还在页面上，可以再按一次保存。`, 7000);
  } else if (sent) {
    toast(`${sent} 项已寄出。机器开着几秒内生效；关着就等开机——每一项下面都标着「已寄出」，生效了才会消失。`, 7000);
  }
  if (sent) {
    const after = now();          // 只认这一刻之后上报的状态
    setTimeout(() => ping(after), 2000);
  }
  saving = false;
};

/* 所有重渲染之后都要把未保存的改动写回控件（见 applyEdits 的注释）。
   包在这里统一接管，免得每个 render() 调用点都要记得跟一句。
   必须在 boot() 之前装上：boot() 用缓存的状态先画一遍，那一遍要是没走这层，
   已寄出的回执要等下一次上报才出现——机器关着时就是永远不出现（2026-09-14）。 */
{
  const _renderRaw = render;
  render = (...a) => { _renderRaw(...a); reconcilePending(); applyEdits(); dressSelects(); };
}

applyTheme();
// 跟随系统时，系统切了日夜要立刻跟上
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
window.__viewReady = true;   // every top-level binding above exists now: live.js's timers / events may use cfg, snap, render … (they return until this)
boot();

/* the bottom tab capsule and the keyboard (数据终核 181053 ⑤ 1/3): iOS keeps position:fixed elements in the layout viewport — with the keyboard up the
   visual viewport shrinks and Safari may float the capsule above the keyboard over the content (the dark time input: capsule y≈516), and after the keyboard
   closes the capsule can stay where the shrunken viewport left it (y≈840 instead of 905) until the next layout. The native tab bar is simply covered by
   the keyboard. Here: while the visual viewport is > 120 px shorter than the window (keyboard up) html.kbd hides the capsule; on every visualViewport
   resize / scroll and after a focus leaves a field the state is re-applied — the capsule comes back through display:none → block, i.e. freshly placed at
   the bottom. window.__tabKbd(h) runs the same code with a pretended visual-viewport height (accept). */
{ const vv = window.visualViewport;   // 监督局 19:3x: the state comes from the visual viewport ONLY — no focus-driven hiding (a focused segment / tab button must never touch the capsule)
  const kbInput = (el) => !!el && ((el.tagName === "INPUT" && !/^(checkbox|radio|range|button|submit|reset|file|color|hidden)$/i.test(el.type)) || el.tagName === "TEXTAREA" || el.isContentEditable === true);   // a <select> opens a menu, not the keyboard
  const apply = (h) => { const vh = h != null ? h : (vv ? vv.height : innerHeight), kbd = innerHeight - vh > 120; document.documentElement.classList.toggle("kbd", kbd); return kbd; };
  window.__tabKbd = (h) => apply(h);
  /* the focused field must end up inside the visible (keyboard-free) part of the viewport. WebKit reveals it itself on focus; on the phone the first
     focus of the time field after load stayed under the keyboard (数据 190821 vs 181053, +1.5 s still hidden; the second focus was revealed). What this
     block does at focus time is one class toggle on <html> (the fixed capsule → display:none) — no preventDefault, no blur, no scrollTop / scroll writes,
     no html height or overflow change; the visualViewport handlers only toggle that class (the older unsink() writes scrollTo(0, 0) only for scrollY < 0).
     验收 19:2x (git show 5d71467): the one timing change between the two builds is that toggle — 181053 ran it 300 ms after focusin, 5d71467 synchronously
     in the focusin dispatch, i.e. before WebKit's reveal. Back to the 300 ms delay (the visualViewport resize hides the capsule as the keyboard comes up
     anyway), and after every visualViewport resize the next frame checks the active field against the visible range [offsetTop, offsetTop + height] and
     scrolls the window so the field's centre lands at that range's centre when it is outside (scrollIntoView would centre in the LAYOUT viewport, under
     the keyboard; 监督局 09-19 19:2x). */
  const reveal = (h) => { const el = document.activeElement; if (!kbInput(el)) return false; const top = vv ? vv.offsetTop : 0, vh = h != null ? h : (vv ? vv.height : innerHeight), r = el.getBoundingClientRect();
    if (r.bottom > top + vh - 8 || r.top < top + 8) { scrollBy({ top: (r.top + r.height / 2) - (top + vh / 2), behavior: "smooth" }); return true; } return false; };
  window.__kbdReveal = (h) => reveal(h);
  if (vv) { vv.addEventListener("resize", () => { apply(); requestAnimationFrame(() => reveal()); }); vv.addEventListener("scroll", () => apply()); }
  addEventListener("focusout", (e) => { if (kbInput(e.target)) setTimeout(() => apply(), 60); }); }   // a text field losing focus: re-read the viewport (the keyboard's resize event normally does it); focusin does nothing

/* 添加到主屏幕后**第一次**从图标启动，滚动位置停在 −62（visualViewport offsetTop −62，整页下沉 62；杀掉重开为 0）——数据会话 9c22044 ?diag 实拍，
   每次添加后的首启必现，不是 env() 也不是 padding。发现负滚动就归零。 */
{ const unsink = () => { if (window.scrollY < 0) window.scrollTo(0, 0); };
  addEventListener("load", unsink); if (window.visualViewport) window.visualViewport.addEventListener("resize", unsink); setTimeout(unsink, 300); setTimeout(unsink, 1200); }

/* ?diag=1：standalone 里看不到控制台，把几何数写在屏幕底部给截图读（数据会话 862de97 实拍：从主屏图标首次启动时整页下沉，
   要靠 innerHeight / 安全区顶 / body padding / 标题顶 这几个数分辨是 web view 的高度、env() 还是我们的 padding 在变）。 */
if (new URLSearchParams(location.search).has("diag")) {
  const d = document.createElement("div");
  d.style.cssText = "position:fixed;left:0;right:0;bottom:calc(env(safe-area-inset-bottom) + 130px);text-align:center;font:12px/16px ui-monospace,monospace;color:var(--dim);pointer-events:none;z-index:99;white-space:pre-wrap";
  const upd = () => {
    const pr = document.createElement("div"); pr.style.cssText = "position:fixed;top:0;left:0;width:1px;padding-top:env(safe-area-inset-top);visibility:hidden";
    document.body.appendChild(pr); const sat = getComputedStyle(pr).paddingTop; pr.remove();
    const h1 = document.querySelector("header h1"), vv = window.visualViewport;
    d.textContent = `ih ${innerHeight} · vv ${vv ? Math.round(vv.height) + "@" + Math.round(vv.offsetTop) : "-"} · sat ${sat} · body ${getComputedStyle(document.body).paddingTop}`
      + ` · h1 ${h1 ? Math.round(h1.getBoundingClientRect().top) : "-"} · sy ${Math.round(scrollY)} · sa ${matchMedia("(display-mode: standalone)").matches ? 1 : 0} · ${new Date().toTimeString().slice(0, 8)}`
      + (window.ALERT_T ? ` · alert f1 +${Math.round(ALERT_T.f1 - ALERT_T.open)} f2 +${Math.round(ALERT_T.f2 - ALERT_T.open)} ms` : "");
  };
  document.body.appendChild(d); upd();
  addEventListener("resize", upd); addEventListener("scroll", upd, { passive: true }); setInterval(upd, 1000);
}
