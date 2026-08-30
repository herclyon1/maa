/* 游戏机遥控。
   一根管道：ntfy 上一个信箱。手机写指令，机器写状态。零轮询——
   机器那头挂长连接，这头只在你按刷新时发一条 ping。
   信箱名和 PIN 只存在这台手机里，不在这份代码里。 */
const NTFY = "https://ntfy.sh";
const LS = "ark-remote-cfg";
const $ = (s) => document.querySelector(s);

let cfg = null;      // {topic, pin}
let snap = null;     // 机器最近一次上报的状态
let edits = {};      // 改了但还没保存的：key -> {label, script, path, from, to}

/* ---------- 外观 ---------- */
const THEME_KEY = "ark-remote-theme";
const ACCENTS = [
  ["蓝", "#4aa3ff"], ["绿", "#3fb950"], ["紫", "#a371f7"],
  ["橙", "#e3873c"], ["红", "#f85149"], ["青", "#2dd4bf"],
];

function loadTheme() {
  try { return JSON.parse(localStorage.getItem(THEME_KEY)) || {}; }
  catch { return {}; }
}

function applyTheme() {
  const t = loadTheme();
  // mode 为空 = 跟随系统：什么都不标，交给 prefers-color-scheme
  if (t.mode === "light" || t.mode === "dark") {
    document.documentElement.dataset.theme = t.mode;
  } else {
    delete document.documentElement.dataset.theme;
  }
  document.documentElement.style.setProperty("--accent", t.accent || ACCENTS[0][1]);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    const dark = t.mode === "dark" ||
      (!t.mode && matchMedia("(prefers-color-scheme: dark)").matches);
    meta.content = dark ? "#0f1216" : "#f5f7fa";
  }
}

function saveTheme(patch) {
  const t = { ...loadTheme(), ...patch };
  localStorage.setItem(THEME_KEY, JSON.stringify(t));
  applyTheme();
}

/* 每一项：在快照里从哪读(sec/key)，写的时候写到哪(script/path) */
/* 值 → 中文。来源都在仓库里，不是我编的：
   · Fixed=固定 出自 plan.py 里给日报排班用的同一套换算
   · 剿灭 Close 的含义出自 docs/CONFIG.md：既是「本周已完成」也可能是
     「被人手动关掉了」，后者没人会自动打开，等于每周少一份奖励 */
const VALUE_ZH = {
  "Info.StageMode": { Fixed: "固定关卡" },
  "Info.Annihilation": { Close: "关闭 / 本周已完成" },
  "Info.SeriesNumb": { "0": "0（不指定，用游戏里的设置）" },
};

/* 每一项：在快照里从哪读(sec/key)，写的时候写到哪(script/path)。
   `ro:true` = 只读：这一项我没有可靠的选项来源，与其给你一个我编的
   下拉列表（826 就是编字段含义出的事），不如老实显示现值并说明含义。 */
const SCHEMA = [
  { title: "明日方舟", script: "MAA", sec: "MAA", fields: [
    { key:"关卡",       path:"Info.Stage",        type:"text",
      hint:"游戏里的关卡号，自己填。像 1-7（常规）、CE-6（龙门币）、AT-4（活动关）。只在上面选「固定」时才生效" },
    { key:"关卡模式",   path:"Info.StageMode",    type:"text",
      hint:"「固定」＝天天刷下面填的那一关。选「计划表」＝按你在电脑上排好的日程刷（哪天刷哪关），这时下面的关卡、连战、理智药都由计划表说了算，改这里没用" },
    { key:"理智药",     path:"Info.MedicineNumb", type:"number",
      hint:"一趟最多嗑几瓶理智药。999＝有多少嗑多少；0＝一瓶都不嗑" },
    { key:"连战",       path:"Info.SeriesNumb",   type:"select",
      opts:["0","1","2","3","4","5","6"], asText:true,
      hint:"进本后连打几场再出来。「0」＝不改，用游戏里当前的设置" },
    { key:"剿灭",       path:"Info.Annihilation", type:"text",
      hint:"选「关闭」＝这周不打剿灭（本周已打满时也会自动变成这个）。其余几项是指定去打哪个剿灭关卡" },
    { key:"作战开关",   path:"Task.IfFight",      type:"bool",
      hint:"关掉就完全不刷关卡，只做基建、公招这些日常" },
    { key:"活动关优先", path:"Task.IfActivityFirst", type:"bool",
      hint:"开着＝有活动期间去刷活动关，活动一结束自动回到上面那个固定关。关着＝永远只刷固定关。下面两项只有它开着时才起作用" },
    { key:"活动关序号", path:"Task.ActivityStageIndex", type:"number",
      hint:"刷活动里的第几关——数的是活动关卡列表里从上往下的位置，第一关填 1（不是 0）。只在上面「活动期间优先刷活动关」打开时才生效" },
    { key:"活动关理智药", path:"Task.ActivityMedicineNumb", type:"number",
      hint:"刷活动关那趟最多嗑几瓶药，和上面常规那个是分开算的。同样只在活动优先打开时才生效" },
  ]},
  { title: "终末地", script: "MaaEnd", sec: "MaaEnd", fields: [
    { key:"开理智",   path:"Task.IfSanity", type:"bool",
      hint:"关掉就不花理智刷本，只做每日签到这类日常" },
    { key:"自动吃药", path:"Task.IfAutoUseSpMedication", type:"bool",
      hint:"理智不够时自动嗑理智药接着刷" },
    { key:"理智任务", path:"Task.SanityTaskType", type:"text",
      hint:"理智花在哪个方向。选「基质刷取」时，下面那个地点才有意义" },
    { key:"基质地点", path:"Task.AutoEssenceSpecifiedLocation", type:"text",
      hint:"去哪个区刷基质。只在上面选「基质刷取」时才生效" },
  ]},
  { title: "鸣潮", script: "OK-WW", sec: "OK-WW(MAS侧)", fields: [
    { key:"WhichToFarm", path:"Task.WhichToFarm", type:"text", label:"体力刷什么",
      hint:"每天的体力花在哪。选了哪个，下面才会出现对应的那一项设置" },
    { key:"WhichTacetSuppressionToFarm", path:"Task.WhichTacetSuppressionToFarm",
      type:"number", label:"凝素领域第几个",
      hint:"游戏里按 F2 打开的列表中，从上往下第几个" },
    { key:"WhichForgeryChallengeToFarm", path:"Task.WhichForgeryChallengeToFarm",
      type:"number", label:"模拟领域第几个",
      hint:"游戏里按 F2 打开的列表中，从上往下第几个" },
    { key:"MaterialSelection", path:"Task.MaterialSelection", type:"text",
      label:"刷哪种材料" },
    { key:"FarmNightmareNestForDailyEcho", path:"Task.FarmNightmareNestForDailyEcho",
      type:"bool", label:"残象聚落",
      hint:"每日任务差一个声骸时，去残象聚落补一个凑满" },
    { key:"TaskIndex", path:"Task.TaskIndex", type:"number", label:"任务序号",
      hint:"OK-WW 内部用来定位任务的编号。除非它跑错任务，否则别动" },
  ]},
];

/* ---------- 信箱 ---------- */
const now = () => Math.floor(Date.now() / 1000);

async function send(body) {
  const msg = JSON.stringify({ v:1, kind:"cmd", pin:cfg.pin, ts:now(), body });
  const r = await fetch(`${NTFY}/${cfg.topic}`,
                       { method:"POST", body:msg, cache:"no-store" });
  if (!r.ok) throw new Error("发不出去 " + r.status);
}

async function readMessages(since = "48h") {
  /* `cache:"no-store"` + 一个变化的参数，两道都要。
     2026-08-31 的 bug：不加这个，Chrome 把第一次的结果一直重复返回，
     机器明明收到了刷新请求也回了状态，页面却永远看不到新的，
     于是判成「关机中」——机器其实开着。 */
  const r = await fetch(
    `${NTFY}/${cfg.topic}/json?poll=1&since=${since}&_=${Date.now()}`,
    { cache: "no-store" });
  if (!r.ok) throw new Error("读不到 " + r.status);
  const text = await r.text();
  return text.split("\n").filter(Boolean).map((l) => {
    try { return JSON.parse(l); } catch { return null; }
  }).filter((e) => e && e.event === "message");
}

async function latestState(since = "48h") {
  const msgs = await readMessages(since);
  for (let i = msgs.length - 1; i >= 0; i--) {
    let m;
    try { m = JSON.parse(msgs[i].message); } catch { continue; }
    if (m && m.kind === "state" && m.pin === cfg.pin) return m.body;
  }
  return null;
}

/* ---------- 界面 ---------- */
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
}

function fmt(v) {
  if (v === true) return "开"; if (v === false) return "关";
  if (v === null || v === undefined) return "（空）";
  return String(v);
}

function setupScreen() {
  $("#app").innerHTML = `
    <section><h2>第一次使用</h2>
      <div class="setup">
        <p style="color:var(--dim);font-size:14px;margin:0 0 10px">
          填一次就好，之后不再问。这两样只存在这台手机里。</p>
        <label>信箱名<input id="s-topic" type="text" placeholder="ark-…"></label>
        <label style="display:block;margin-top:12px">PIN<input id="s-pin" type="text" inputmode="numeric" placeholder="4 位数字"></label>
      </div>
      <div class="acts"><button class="primary wide" id="s-go">开始使用</button></div>
    </section>`;
  $("#s-go").onclick = () => {
    const topic = $("#s-topic").value.trim(), pin = $("#s-pin").value.trim();
    if (!topic || !pin) return toast("两样都要填");
    cfg = { topic, pin };
    localStorage.setItem(LS, JSON.stringify(cfg));
    boot();
  };
}

function render() {
  const c = (snap && snap.config) || {};
  const relay = (snap && snap.relay) || {};
  let html = "";

  const qs = (snap && snap.queues) || [];
  const qopts = qs.map((q) => {
    const t = (q["定时"] === false) ? "未启用定时" : "";
    return `<option value="${q["名"]}">${q["名"]}${t ? "（" + t + "）" : ""}</option>`;
  }).join("");
  html += `<section><h2>机器状态 <small>${snap ? ago(snap.at) : "还没有数据"}</small></h2>
    <div class="acts">
      <button class="wide" id="refresh">刷新（顺便看开没开机）</button>
    </div>
    ${qs.length ? `<div class="row"><label>下面两个按钮作用在哪个队列
        <span class="hint">这台机器有两趟：一趟早上、一趟晚上</span></label>
      <select id="queue">${qopts}</select></div>` : ""}
    <div class="acts">
      <button id="runnow">让它现在跑一趟</button>
      <button id="skiptoday">跳过它下一趟</button>
      <button class="wide" id="noshut">${relay["下次别关机"] ? "✓ 已设：下次跑完不关机" : "下次跑完不关机"}</button>
    </div>
    ${snap && snap.plan ? `<pre>${snap.plan.replace(/</g,"&lt;")}</pre>` : ""}
  </section>`;

  for (const g of SCHEMA) {
    const cur = c[g.sec] || {};
    html += `<section><h2>${g.title} <small>${g.script}</small></h2>`;
    /* 选择树：OK-WW 声明了「选了哪个才出现哪些子项」（sub_configs）。
       选「刷模拟领域」时不该还摆着「凝素领域序号」——那是给人看的噪音。 */
    const subs = (snap && snap.subs) || {};
    const picked = cur["WhichToFarm"];
    const hidden = new Set();
    for (const [k, paths] of Object.entries(subs)) {
      if (k !== picked) for (const pth of paths) hidden.add(pth);
    }
    const optsOf = (path) => (((snap && snap.options) || {})[g.script] || {})[path];

    for (const f of g.fields) {
      const id = `${g.script}|${f.path}`;
      if (hidden.has(f.path)) continue;
      const val = cur[f.key];
      const live = optsOf(f.path);        // 机器发过来的真实选项
      /* 字段名用 AUTO-MAS 自己的中文标注（它界面就是中文的），
         没有才退回我在 SCHEMA 里写的那个。 */
      // 标签按「脚本|路径」取：不同脚本有同名字段，全局匹配会串标签
      const label = ((((snap && snap.options) || {})._labels || {})[`${g.script}|${f.path}`])
                 || f.label || f.key;
      const hint = f.hint ? `<span class="hint">${f.hint}</span>` : "";
      let ctl;
      const zh = (VALUE_ZH[f.path] || {})[String(val)];
      if (f.ro && !(live && live.length)) {
        // 没有可靠选项来源的，老实显示现值，不假装成选择题
        ctl = `<span class="ro">${zh || fmt(val)}</span>`;
      } else if (f.type === "bool") {
        ctl = `<span class="sw"><input type="checkbox" data-id="${id}" ${val ? "checked" : ""}><span></span></span>`;
      } else if (live && live.length) {
        const opts = live.map(([lb, v]) =>
          `<option value="${String(v)}" ${String(val) === String(v) ? "selected" : ""}>${lb}</option>`).join("");
        ctl = `<select data-id="${id}">${opts}</select>`;
      } else if (f.type === "select") {
        const opts = f.opts.map((o) => `<option ${String(val) === o ? "selected" : ""}>${o}</option>`).join("");
        ctl = `<select data-id="${id}">${opts}</select>`;
      } else {
        ctl = `<input type="${f.type}" data-id="${id}" value="${val === undefined || val === null ? "" : String(val)}">`;
      }
      html += `<div class="row" data-row="${id}"><label>${label}${hint}</label>${ctl}</div>`;
    }
    html += `</section>`;
  }

  const wb = (relay["周本"]) || {};
  html += `<section><h2>鸣潮周本 <small>战歌重奏</small></h2>
    <div class="row"><label>打周本
      <span class="hint">和剿灭一个逻辑：本周打完自动停，下周一 04:00 自动开回来。
      现在是关着的——它出厂设置是「一直刷」，次数得你定</span></label>
      <span class="sw"><input type="checkbox" id="wb-on" ${wb["开"] ? "checked" : ""}><span></span></span>
    </div>
    <div class="row"><label>打第几个
      <span class="hint">游戏里按 F2 打开周本列表，从上往下数，第一个填 1</span></label>
      <input type="number" id="wb-idx" value="${wb["第几个周本"] || 1}"></div>
    <div class="row"><label>一周打几次
      <span class="hint">别填大数：这项在 OK-WW 里出厂是 10000，等于一直打</span></label>
      <input type="number" id="wb-cnt" value="${wb["打几次"] || 1}"></div>
    ${wb["本周已打"] ? `<div class="row"><span class="ro">本周已经打过了，下周一自动恢复</span></div>` : ""}
    <div class="acts"><button class="wide primary" id="wb-save">保存周本设置</button></div>
  </section>`;

  const th = loadTheme();
  const mode = th.mode || "auto";
  html += `<section><h2>外观</h2>
    <div class="row"><label>深浅模式<span class="hint">跟随系统就是跟着手机的日夜切换</span></label>
      <select id="th-mode">
        <option value="auto" ${mode === "auto" ? "selected" : ""}>跟随系统</option>
        <option value="light" ${mode === "light" ? "selected" : ""}>浅色</option>
        <option value="dark" ${mode === "dark" ? "selected" : ""}>深色</option>
      </select></div>
    <div class="row"><label>主题色</label>
      <span class="swatches">${ACCENTS.map(([n, c]) =>
        `<i class="sw-c${(th.accent || ACCENTS[0][1]) === c ? " on" : ""}" data-c="${c}" title="${n}" style="background:${c}"></i>`).join("")}</span>
    </div>
  </section>`;

  $("#app").innerHTML = html;
  wire();
}

function wire() {
  // 必须包一层：`onclick = ping` 会把**鼠标事件对象**当成 minAt 传进去，
  // 于是 `s.at >= floor` 变成「数字 >= 事件对象」，永远为假——
  // 机器明明开着也判成关机。2026-08-31 我加 minAt 参数时就这么弄坏过一次。
  $("#refresh").onclick = () => ping();
  const theQueue = () => (document.querySelector("#queue") || {}).value || "新队列";
  $("#runnow").onclick = () => oneShot(
    { action:"run_now", confirmed:true, queue:theQueue() },
    `已让「${theQueue()}」现在开跑。机器关着时这条会等到下次开机才执行，` +
    "那时候它本来也要跑，所以等于没多跑一趟");
  $("#noshut").onclick = () => oneShot({ action:"skip_shutdown" },
    "下一次本该关机时会跳过（只跳这一次，再下一趟照常关）");
  // 说明必须准：这条跳的是**机器执行它那一天**。机器关着时你现在按，
  // 它要等下次开机才执行，跳掉的就是那一天，不是今天。
  $("#skiptoday").onclick = () => oneShot(
    { action:"skip_today", queue:theQueue() },
    `「${theQueue()}」下一趟不跑了。机器开着＝跳今天这趟；` +
    "机器关着＝这条等到下次开机才生效，跳的是那一天。只跳一次，之后自动恢复");
  const wbSave = $("#wb-save");
  if (wbSave) wbSave.onclick = () => {
    const on = $("#wb-on").checked;
    const index = Number($("#wb-idx").value) || 1;
    const count = Number($("#wb-cnt").value) || 1;
    if (!confirm(on
      ? `打开周本：打第 ${index} 个，一周打 ${count} 次。确定？`
      : "关掉周本？")) return;
    oneShot({ action:"weekly_boss", on, index, count },
      on ? `周本已开：第 ${index} 个，打 ${count} 次` : "周本已关");
    setTimeout(() => ping(now()), 2000);
  };

  const tm = $("#th-mode");
  if (tm) tm.onchange = () => saveTheme({ mode: tm.value === "auto" ? null : tm.value });
  for (const sw of document.querySelectorAll(".sw-c")) {
    sw.onclick = () => {
      saveTheme({ accent: sw.dataset.c });
      for (const o of document.querySelectorAll(".sw-c")) o.classList.remove("on");
      sw.classList.add("on");
    };
  }

  for (const el of document.querySelectorAll("[data-id]")) {
    el.addEventListener("change", () => {
      const [script, path] = el.dataset.id.split("|");
      const g = SCHEMA.find((x) => x.script === script);
      const f = g.fields.find((x) => x.path === path);
      const cur = ((snap && snap.config) || {})[g.sec] || {};
      const from = cur[f.key];
      let to;
      if (f.type === "bool") to = el.checked;
      else if (f.type === "number") to = el.value === "" ? null : Number(el.value);
      else to = el.value;
      if (f.type === "select" && !f.asText && /^\d+$/.test(String(to)) && typeof from === "number") to = Number(to);

      const key = el.dataset.id;
      const row = document.querySelector(`[data-row="${CSS.escape(key)}"]`);
      if (to === from) { delete edits[key]; row.classList.remove("changed"); }
      else { edits[key] = { label:`${g.title} ${f.label || f.key}`, script, path, from, to };
             row.classList.add("changed"); }
      updateBar();
      // 「刷什么」决定下面出现哪些子项，改了就得重画一次
      if (f.path === "Task.WhichToFarm") {
        const keep = { ...edits };
        snap = { ...snap, config: { ...snap.config,
          [g.sec]: { ...(snap.config[g.sec] || {}), WhichToFarm: to } } };
        render(); edits = keep; updateBar();
        for (const k of Object.keys(edits)) {
          const r2 = document.querySelector(`[data-row="${CSS.escape(k)}"]`);
          if (r2) r2.classList.add("changed");
        }
      }
    });
  }
}

function updateBar() {
  const n = Object.keys(edits).length;
  $("#savebar").classList.toggle("show", n > 0);
  $("#savenote").textContent = n ? `${n} 项待保存` : "";
}

/* ---------- 动作 ---------- */
async function oneShot(body, okText) {
  try { await send(body); toast(okText + "（机器开着就是马上，关着就是下次开机）"); }
  catch (e) { toast("发不出去：" + e.message); }
}

/* `minAt` 是「只接受这个时刻之后上报的状态」。保存完之后必须传它——
   否则可能收到**改动之前**发布的那一条，界面上就会显示成「没改成」。
   2026-08-31 实测撞到过：机器上已经是新值了，页面还显示旧值。 */
async function ping(minAt) {
  setStatus("正在问机器…", "");
  const floor = (typeof minAt === "number" ? minAt : null)
             ?? (snap ? snap.at : 0);
  try { await send({ action:"refresh" }); }
  catch (e) { return setStatus("发不出去：" + e.message, "off"); }
  for (let i = 0; i < 16; i++) {
    await new Promise((r) => setTimeout(r, 700));
    let s;
    try { s = await latestState("2h"); } catch { continue; }
    if (s && s.at >= floor && (!snap || s.at > snap.at)) {
      snap = s; save_cache(); render();
      return setStatus("开机中 · 刚刚更新", "on");
    }
  }
  setStatus(snap ? `关机中 · 状态是 ${ago(snap.at)}的` : "关机中 · 还没有过状态", "off");
}

function save_cache() {
  try { localStorage.setItem(LS + "-snap", JSON.stringify(snap)); } catch {}
}

async function doSave() {
  const items = Object.values(edits);
  if (!items.length) return;
  $("#difflist").innerHTML = items.map((e) =>
    `<div class="diff"><b>${e.label}</b><br><span class="old">${fmt(e.from)}</span> → <span class="new">${fmt(e.to)}</span></div>`).join("");
  $("#confirm").showModal();
}

/* ---------- 启动 ---------- */
async function boot() {
  const raw = localStorage.getItem(LS);
  if (!raw) return setupScreen();
  cfg = JSON.parse(raw);
  try { snap = JSON.parse(localStorage.getItem(LS + "-snap") || "null"); } catch { snap = null; }
  render();
  setStatus(snap ? `状态是 ${ago(snap.at)}的` : "正在读取…", "");
  try {
    const s = await latestState();
    if (s) { snap = s; save_cache(); render(); }
    setStatus(snap ? `状态是 ${ago(snap.at)}的 · 按刷新看是否开机` : "还没有过状态", "");
  } catch (e) {
    setStatus("读不到信箱：" + e.message, "off");
  }
}

$("#save").onclick = doSave;
$("#discard").onclick = () => { edits = {}; render(); updateBar(); };
$("#cancel").onclick = () => $("#confirm").close();
$("#go").onclick = async () => {
  $("#confirm").close();
  const items = Object.values(edits);
  let sent = 0;
  for (const e of items) {
    try { await send({ action:"set_config", confirmed:true, script:e.script, path:e.path, value:e.to }); sent++; }
    catch (err) { toast("第 " + (sent + 1) + " 项发不出去：" + err.message); break; }
  }
  if (sent) {
    edits = {}; updateBar();
    toast(`${sent} 项已发出。机器开着就是马上生效，关着就是下次开机；生效后会有通知。`, 5000);
    const after = now();          // 只认这一刻之后上报的状态
    setTimeout(() => ping(after), 2000);
  }
};

applyTheme();
// 跟随系统时，系统切了日夜要立刻跟上
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
boot();
