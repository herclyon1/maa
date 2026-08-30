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
      hint:"自己填，像 1-7、CE-6、AT-4" },
    { key:"关卡模式",   path:"Info.StageMode",    type:"text", ro:true,
      hint:"固定关卡＝每次都刷上面那一关。这项要在电脑上改" },
    { key:"理智药",     path:"Info.MedicineNumb", type:"number",
      hint:"最多吃几个。999＝有多少吃多少" },
    { key:"连战",       path:"Info.SeriesNumb",   type:"select",
      opts:["0","1","2","3","4","5","6"], asText:true,
      hint:"一次连打几场。0＝不指定，听游戏里的" },
    { key:"剿灭",       path:"Info.Annihilation", type:"text", ro:true,
      hint:"关闭／本周已完成。注意：被手动关掉也是这个值，那样每周会少一份奖励。这项要在电脑上改" },
    { key:"作战开关",   path:"Task.IfFight",      type:"bool",
      hint:"关掉就完全不刷关，只做别的日常" },
    { key:"活动关优先", path:"Task.IfActivityFirst", type:"bool",
      hint:"开着＝有活动就刷活动关，活动结束自动回到上面那个固定关" },
    { key:"活动关序号", path:"Task.ActivityStageIndex", type:"number",
      hint:"活动里第几关，从 1 起算（不是从 0）" },
    { key:"活动关理智药", path:"Task.ActivityMedicineNumb", type:"number",
      hint:"刷活动关时最多吃几个药" },
  ]},
  { title: "终末地", script: "MaaEnd", sec: "MaaEnd", fields: [
    { key:"开理智",   path:"Task.IfSanity", type:"bool",
      hint:"关掉就不花理智，只做日常" },
    { key:"自动吃药", path:"Task.IfAutoUseSpMedication", type:"bool",
      hint:"理智不够时自动嗑药" },
    { key:"理智任务", path:"Task.SanityTaskType", type:"text", ro:true,
      hint:"理智花在哪一类上。这项要在电脑上改" },
    { key:"基质地点", path:"Task.AutoEssenceSpecifiedLocation", type:"text",
      hint:"去哪个区采基质" },
  ]},
  { title: "鸣潮", script: "OK-WW", sec: "OK-WW(MAS侧)", fields: [
    { key:"WhichToFarm", path:"Task.WhichToFarm", type:"text", label:"体力刷什么",
      hint:"选了哪个，下面才出现对应的那一项" },
    { key:"WhichTacetSuppressionToFarm", path:"Task.WhichTacetSuppressionToFarm",
      type:"number", label:"凝素领域第几个", hint:"游戏里 F2 列表中的序号" },
    { key:"WhichForgeryChallengeToFarm", path:"Task.WhichForgeryChallengeToFarm",
      type:"number", label:"模拟领域第几个", hint:"游戏里 F2 列表中的序号" },
    { key:"MaterialSelection", path:"Task.MaterialSelection", type:"text",
      label:"刷哪种材料" },
    { key:"FarmNightmareNestForDailyEcho", path:"Task.FarmNightmareNestForDailyEcho",
      type:"bool", label:"残象聚落",
      hint:"日常差一个声骸时，去残象聚落补一个" },
    { key:"TaskIndex", path:"Task.TaskIndex", type:"number", label:"任务序号",
      hint:"OK-WW 内部用的编号，一般不用动" },
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

  html += `<section><h2>机器状态 <small>${snap ? ago(snap.at) : "还没有数据"}</small></h2>
    <div class="acts">
      <button id="refresh">刷新（同时检测开没开机）</button>
      <button id="runnow">立刻跑一趟</button>
      <button id="noshut">${relay["下次别关机"] ? "已设：跑完不关机" : "今晚跑完别关机"}</button>
      <button id="skiptoday">今天跳过队列</button>
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
      const label = ((((snap && snap.options) || {})._labels || {})[f.path])
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
  $("#runnow").onclick = () => oneShot({ action:"run_now", confirmed:true, queue:"新队列" }, "已让它立刻跑一趟");
  $("#noshut").onclick = () => oneShot({ action:"skip_shutdown" }, "这趟跑完不关机");
  $("#skiptoday").onclick = () => oneShot({ action:"skip_today", queue:"新队列" }, "今天这个队列跳过");
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
