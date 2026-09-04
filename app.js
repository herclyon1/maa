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

/* 页面上出现哪些设置——2026-09-03 重排过一次，两条规矩：
   ① **改了不生效的一律不摆出来。** 终末地和鸣潮的「快速配置」是关的，
      AUTO-MAS 那边直接 return，不把 MAS 用户配置下发给脚本
      （app/task/Okww/AutoProxy.py:320、MaaEnd/AutoProxy.py:537）。
      这两个游戏原来那 10 项按下去有回执、值也真写进了 MAS，可脚本看的是
      自己那份母本，等于没改。现在它们改母本，src:"master"。
      明日方舟不一样：它压根没有快速配置这回事，关卡和理智药每次派发都会
      被写进 gui.new.json，所以照旧走 MAS。
   ② **不用改的不摆出来。** 关卡模式常年「固定」、连战常年 0、
      剿灭每周自己开关自己、任务序号原本的说明就是「除非它跑错否则别动」。

   src:"mas"    → 值取 snap.config[sec][key]，写 set_config(script, path)
   src:"master" → 值取 snap.master[game].values[path]，写 set_master(game, path) */
const SCHEMA = [
  { title:"明日方舟", owner:"MAA", src:"mas", script:"MAA", sec:"MAA", fields:[
    { key:"关卡",       path:"Info.Stage",        type:"text",
      hint:"游戏内的关卡号。例如 1-7（常规）、CE-6（龙门币）、AT-4（活动关）" },
    { key:"理智药",     path:"Info.MedicineNumb", type:"number",
      hint:"一趟最多使用几瓶理智药。0＝不使用；999＝不限量" },
    { key:"作战开关",   path:"Task.IfFight",      type:"bool",
      hint:"关掉后不刷关卡，只做基建、公招等日常" },
    { key:"活动关优先", path:"Task.IfActivityFirst", type:"bool",
      hint:"开着＝有活动就刷活动关，活动结束后自动回到上面那个固定关。开着时下面的序号才生效" },
    { key:"活动关序号", path:"Task.ActivityStageIndex", type:"number",
      hint:"刷活动里的第几关，数的是活动关卡列表从上往下的位置，第一关填 1。只在上面那项开着时才有用" },
    { key:"剿灭",       path:"Info.Annihilation", type:"text", ro:true,
      hint:"每周自动开关：打满后置为关闭，下周一自动恢复。此处仅显示当前状态" },
  ]},
  { title:"终末地 · 基质刷取", owner:"MaaEnd", src:"master", game:"MaaEnd", fields:[
    { path:"AutoEssence/@enabled", type:"bool", label:"跑这个任务",
      hint:"关掉后不再刷基质，理智会持续累积" },
    { path:"AutoEssence/AutoEssenceDoOverride", type:"bool",
      hint:"使用刻写券定向刷取词条。需事先在淤积点开始界面选定要刻写的属性；券不足时改为不刻写领取" },
    { path:"AutoEssence/AutoEssenceObtainMode", type:"select",
      hint:"每轮打完的结算方式。单倍＝一份理智一张券；双倍＝双倍理智两张券，奖励翻倍；不领取＝只刷素材" },
    { path:"AutoEssence/AutoEssenceRepeatCount", type:"number",
      hint:"一趟最多执行的轮数。单倍每轮 80 理智，双倍 160" },
    { path:"AutoEssence/AutoEssenceChooseLocation", type:"pills",
      hint:"从勾选的地区里随机挑一个。藏剑谷与清波寨成功率较高，试验园区较低" },
    { path:"AutoEssence/EssenceFilterAfterBattle", type:"bool",
      hint:"每轮结束后立即筛选并锁定符合条件的基质" },
  ]},
  { title:"终末地 · 另外两个任务", owner:"MaaEnd", src:"master", game:"MaaEnd", fields:[
    { path:"AutoUseSpMedication/@enabled", type:"bool",
      hint:"理智不足时自动使用应急理智加强剂" },
    { path:"AutoCollect/@enabled", type:"bool",
      hint:"下面两项决定它去采哪几条、哪天采" },
    /* 光一个开关看不出它会去采哪几条、哪天采，所以把路线和排班一起显示。 */
    { path:"AutoCollect/AutoCollectRoutes", type:"pills",
      hint:"勾上的路线才会去采。路线 3 和 13 目前寻路走不到，已取消勾选" },
    { path:"AutoCollect/AutoCollectSchedule", type:"pills",
      hint:"只在勾选的星期执行。没勾的日子这个任务会立即结束" },
  ]},
  { title:"鸣潮", owner:"OK-WW", src:"master", game:"OK-WW", fields:[
    { path:"DailyTask.json/Which to Farm", type:"text", label:"体力刷什么",
      hint:"每天的体力花在哪" },
    { path:"DailyTask.json/Material Selection", type:"text", label:"刷哪种材料",
      hint:"只在上面选「模拟领域」时才有用" },
    /* 这两项 OK-WW 只存**序号**，它按游戏里 F2 传送列表从上往下数着传送，
       名字和掉落它都不知道。所以这里的说明必须写清楚序号是哪来的，
       别再写成上一版那种和标题对不上的话（无音区那条写着「选凝素领域才有用」）。
       用户 2026-09-04：「给我标数字，我怎么知道 1234 是什么东西呢？」
       ——序号对应哪个套装要拿游戏里的 F2 列表核对，见 docs/欠的活.md。 */
    { path:"DailyTask.json/Which Forgery Challenge to Farm", type:"number",
      hint:"游戏里按 F2 打开传送列表，凝素领域从上往下数第几个。只在上面选「凝素领域」时才有用" },
    { path:"DailyTask.json/Which Tacet Suppression to Farm", type:"number",
      hint:"F2 → 素材获取 → 无音清剿，按地区分组从上往下连续数第几个。1 方掌西峰、2 玄幽东岳（白+绿套）、3 落日堤屿、4 冰原运输港、5 加拉尔冠阶，其余见 docs/鸣潮-无音区序号对照.md。只在上面选「无音区」时才有用" },
    { path:"NightmareNestTask.json/Only Farm These Nests", type:"text",
      label:"残象聚落点位", ro:true,
      hint:"只刷落渊南丘，这是定好的。要换点位在电脑上改" },
  ]},
];

/* ---------- 信箱 ---------- */
const now = () => Math.floor(Date.now() / 1000);

async function send(body) {
  const msg = JSON.stringify({ v:1, kind:"cmd", pin:cfg.pin, ts:now(), body });
  const r = await fetch(`${NTFY}/${cfg.topic}`,
                       { method:"POST", body:msg, cache:"no-store" });
  if (!r.ok) throw new Error(r.status === 429
    ? "太频繁了，歇几秒再点（429）" : "HTTP " + r.status);
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

/* 状态包可能是压缩的。机器那头只在明文会超 ntfy 大小上限时才压
   （选项表那一堆中文候选占了一多半），压不下也压。两种都要认：
   以前超限的处理是**砍字段**——先砍明日安排、再砍选项表，
   于是手机上那些中文下拉不声不响就没了。 */
async function unwrap(m) {
  if (m.body !== undefined) return m.body;
  if (!m.gz) return null;
  const bin = Uint8Array.from(atob(m.gz), (c) => c.charCodeAt(0));
  const ds = new DecompressionStream("gzip");
  const buf = await new Response(new Blob([bin]).stream().pipeThrough(ds)).arrayBuffer();
  return JSON.parse(new TextDecoder().decode(buf));
}

/* 顺带统计：信箱里有几条状态、几条 PIN 对得上。
   PIN 填错时页面原来**一声不吭**地显示「还没有数据」，
   用户会以为机器坏了——2026-09-01 模拟新用户实测出来的。 */
let pinScan = { seen: 0, matched: 0 };

async function latestState(since = "48h") {
  const msgs = await readMessages(since);
  pinScan = { seen: 0, matched: 0 };
  for (let i = msgs.length - 1; i >= 0; i--) {
    let m;
    try { m = JSON.parse(msgs[i].message); } catch { continue; }
    if (!m || m.kind !== "state") continue;
    pinScan.seen++;
    if (m.pin === cfg.pin) {
      pinScan.matched++;
      try { return await unwrap(m); } catch { return null; }
    }
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

let lastGoodConfig = null;
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

function render() {
  let c = (snap && snap.config) || {};
  const relay = (snap && snap.relay) || {};
  let html = "";
  /* AUTO-MAS 没在运行时，中继读不到配置，快照里只有一条 _错误。
     2026-09-02 晚：用户在机器上玩，AUTO-MAS 被关了，页面把空配置当成配置显示——
     「一坨屎」。现在：明说读不到，配置区退回上一次读到的那份，并标明是旧的。 */
  let cfgNote = "";
  if (c._错误 || !Object.keys(c).length) {
    cfgNote = `<div class="warn">⚠️ 读不到 AUTO-MAS 的配置（它没在运行？）${lastGoodConfig ? "——下面显示的是上次读到的，改了也要等它开着才生效" : ""}</div>`;
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
  html += `<section><h2>机器状态 <small>${snap ? ago(snap.at) : "还没有数据"}</small></h2>
    <div class="acts">
      <button class="wide" id="refresh">刷新（顺便看开没开机）</button>
    </div>
    ${qs.length ? `<div class="row"><label>看哪一趟班
        <span class="hint">下面两个按钮作用在这趟班上，配置也只显示这趟班要跑的游戏。
        ${thisShift && thisShift.length ? "这趟跑：" + thisShift.join("、") : ""}</span></label>
      <select id="queue">${qopts}</select></div>` : ""}
    <div class="acts">
      <button id="runnow">让它现在跑一趟</button>
      <button id="skiptoday">跳过它下一趟</button>
      <button class="wide" id="noshut">${relay["下次别关机"] ? "✕ 取消「下次跑完不关机」" : "下次跑完不关机"}</button>
      <button class="wide danger" id="estop">🛑 停止一切脚本和游戏</button>
    </div>
    ${snap && snap.plan ? `<pre>${snap.plan.replace(/</g,"&lt;")}</pre>` : ""}
  </section>${cfgNote}`;

  for (const g of SCHEMA) {
    if (!inShift(g.owner)) continue;
    const M = ((snap && snap.master) || {})[g.game] || {};
    const cur = g.src === "master" ? (M.values || {}) : (c[g.sec] || {});
    const ro = M.readonly || {};
    /* 母本读不到就整段不摆——空壳比没有更误导人（2026-09-02 那次「一坨屎」）。 */
    if (g.src === "master" && !Object.keys(cur).length && !Object.keys(ro).length) continue;
    html += `<section><h2>${g.title}</h2>`;
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
      const live = g.src === "master"
        ? (M.options || {})[f.path]
        : (((snap && snap.options) || {})[g.script] || {})[f.path];
      const label = labelOf(g, f);
      const hint = f.hint ? `<span class="hint">${f.hint}</span>` : "";
      const zh = (VALUE_ZH[f.path] || {})[String(val)];
      const pick = (v) => {
        const hit = (live || []).find(([, x]) => String(x) === String(v));
        return hit ? hit[0] : (zh || fmt(v));
      };
      let ctl;
      if (f.ro) {
        ctl = `<span class="ro">${pick(val)}</span>`;
      } else if (f.type === "bool") {
        ctl = `<span class="sw"><input type="checkbox" data-id="${id}" ${val ? "checked" : ""}><span></span></span>`;
      } else if (f.type === "pills") {
        const on = new Set((Array.isArray(val) ? val : [val]).map(String));
        const opts = live || [];
        const btns = opts.map(([lb, v]) =>
          `<button type="button" class="pill${on.has(String(v)) ? " on" : ""}" data-v="${v}">${lb}</button>`
        ).join("");
        /* 选项一多，一屏几乎全被这些按钮占满。超过 8 个就默认收起，
           只留一行「已选 N/M」，点开才展开。收起时按钮仍在 DOM 里，
           编辑追踪照常工作。 */
        ctl = opts.length > 8
          ? `<details class="pillbox"><summary>已选 ${opts.filter(([, v]) => on.has(String(v))).length}/${opts.length}</summary>` +
            `<div class="pills" data-pills="${id}">${btns}</div></details>`
          : `<div class="pills" data-pills="${id}">${btns}</div>`;
      } else if (live && live.length) {
        ctl = `<select data-id="${id}">` + live.map(([lb, v]) =>
          `<option value="${String(v)}" ${String(val) === String(v) ? "selected" : ""}>${lb}</option>`
        ).join("") + `</select>`;
      } else {
        ctl = `<input type="${f.type}" data-id="${id}" value="${val === null ? "" : String(val)}">`;
      }
      html += `<div class="row" data-row="${id}"><label>${label}${hint}</label>${ctl}</div>`;
    }
    html += `</section>`;
  }

  const wb = (relay["周本"]) || {};
  if (inShift("OK-WW")) html += `<section><h2>鸣潮周本 <small>战歌重奏</small></h2>
    <div class="row" data-row="wb|OK-WW|开"><label>打周本
      <span class="hint">和剿灭一个逻辑：本周打完自动停，下周一 04:00 自动开回来。
      现在是关着的——它出厂设置是「一直刷」，次数得你定</span></label>
      <span class="sw"><input type="checkbox" data-id="wb|OK-WW|开" id="wb-on" ${wb["开"] ? "checked" : ""}><span></span></span>
    </div>
    <div class="row" data-row="wb|OK-WW|第几个周本"><label>打第几个
      <span class="hint">游戏里按 F2 打开周本列表，从上往下数，第一个填 1。
      OK-WW 只认位置不认名字，新 Boss 上线顺序会变，换本时记得来改</span></label>
      <input type="number" data-id="wb|OK-WW|第几个周本" id="wb-idx" value="${wb["第几个周本"] || 1}"></div>
    <div class="row" data-row="wb|OK-WW|打几次"><label>一周打几次
      <span class="hint">奖励是**进本时扣 60 结晶波片**直接给的，没有打完开宝箱这一步。
      一周只能领 3 次，填 3 就够，三次共 180 波片。
      波片不够时会自动跳过这次周本（不空转、也不会白打），下一趟再补。
      这项在 OK-WW 里出厂是 10000，等于一直打</span></label>
      <input type="number" data-id="wb|OK-WW|打几次" id="wb-cnt" value="${wb["打几次"] || 1}"></div>
    <div class="row" data-row="wb|OK-WW|难度等级"><label>难度等级
      <span class="hint">**周本要选最高的 90** —— 等级决定奖励档次。
      （OK-WW 这一项的说明写的是「挑能掉声骸的最低级」，那是刷声骸的思路，
      和周本正好相反，别被它带偏）</span></label>
      <select data-id="wb|OK-WW|难度等级" id="wb-lvl">${["50","60","70","80","90"].map(v =>
        `<option value="${v}"${String(wb["难度等级"]) === v ? " selected" : ""}>${v}${v === "90" ? "（推荐）" : ""}</option>`).join("")}</select></div>
    ${wb["本周已打"] ? `<div class="row"><span class="ro">本周已经打过了，下周一自动恢复</span></div>` : ""}
  </section>`;

  html += `<section><h2>这台手机</h2>
    <div class="row"><label>免输入链接
      <span class="hint">把这条链接存成书签或加到主屏幕，以后打开就直接是控制台，
      再也不用填信箱和 PIN。链接里带着这两样，别转发给别人</span></label>
      <button id="mklink">复制链接</button></div>
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
  const theQueue = () => curQueue || "早班";
  const qsel = $("#queue");
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
  $("#runnow").onclick = () => oneShot(
    { action:"run_now", confirmed:true, queue:theQueue() },
    `已让「${theQueue()}」现在开跑。机器关着时这条会等到下次开机才执行，` +
    "那时候它本来也要跑，所以等于没多跑一趟");
  // 已经设过就变成「取消」。只能开不能关是半个功能——2026-08-31 实测发现的。
  // 这里**不能**用渲染函数里的 `relay`：绑定发生在另一个函数里，
  // 那个名字在这个作用域不存在，点一下就 ReferenceError，按钮彻底失灵。
  // 2026-08-31 我就是这么把它写坏的，实测才发现。走模块级的 snap。
  $("#noshut").onclick = () => (((snap && snap.relay) || {})["下次别关机"]
    ? oneShot({ action:"skip_shutdown", off:true }, "已取消，下次跑完照常关机")
    : oneShot({ action:"skip_shutdown" },
        "下一次本该关机时会跳过（只跳这一次，再下一趟照常关）"));
  // 说明必须准：这条跳的是**机器执行它那一天**。机器关着时你现在按，
  // 它要等下次开机才执行，跳掉的就是那一天，不是今天。
  $("#estop").onclick = () => {
    if (!confirm("立刻停掉所有脚本和游戏？正在跑的这趟会作废。")) return;
    oneShot({ action:"estop", confirmed:true }, "已下令停止一切，机器上几秒内生效");
  };
  $("#skiptoday").onclick = () => oneShot(
    { action:"skip_today", queue:theQueue() },
    `「${theQueue()}」下一趟不跑了。机器开着＝跳今天这趟；` +
    "机器关着＝这条等到下次开机才生效，跳的是那一天。只跳一次，之后自动恢复");
  const tm = $("#th-mode");
  if (tm) tm.onchange = () => saveTheme({ mode: tm.value === "auto" ? null : tm.value });
  for (const sw of document.querySelectorAll(".sw-c")) {
    sw.onclick = () => {
      saveTheme({ accent: sw.dataset.c });
      for (const o of document.querySelectorAll(".sw-c")) o.classList.remove("on");
      sw.classList.add("on");
    };
  }

  /* 周本那四项走同一个保存栏。原来它自己有一个「保存周本设置」按钮，
     和下面的「保存修改」两套并存——用户 2026-09-04 问「何意味」。
     现在它和别的设置一样进待保存清单，保存时合成一条指令发出去。 */
  const WB_ZH = { "开":"打周本", "第几个周本":"打第几个", "打几次":"一周打几次",
                  "难度等级":"难度等级" };

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

  const mk = $("#mklink");
  if (mk) mk.onclick = async () => {
    const url = myLink();
    try { await navigator.clipboard.writeText(url); toast("链接已复制。存成书签或加到主屏幕就不用再填了"); }
    catch { prompt("长按复制这条链接：", url); }
  };

  for (const el of document.querySelectorAll("[data-id]")) {
    el.addEventListener("change", () => {
      if (el.dataset.id.startsWith("wb|")) {
        const key = el.dataset.id.slice("wb|OK-WW|".length);
        const wbNow = (((snap && snap.relay) || {})["周本"]) || {};
        const from = key === "开" ? !!wbNow["开"]
          : key === "难度等级" ? String(wbNow[key] ?? "")
          : Number(wbNow[key] ?? 1);
        const to = key === "开" ? el.checked
          : key === "难度等级" ? el.value : (Number(el.value) || 1);
        const id = el.dataset.id;
        const row = document.querySelector(`[data-row="${CSS.escape(id)}"]`);
        if (String(from) === String(to)) { delete edits[id]; if (row) row.classList.remove("changed"); }
        else { edits[id] = { label:`鸣潮周本 · ${WB_ZH[key] || key}`, src:"wb", key, from, to };
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

  /* 多选（地区选择）：一排小按钮，按一下切一个。全关掉不许——
     MaaEnd 自己写着「若全不选则任务终止」。 */
  for (const box of document.querySelectorAll("[data-pills]")) {
    const id = box.dataset.pills;
    const { g, f } = locate(id);
    if (!g) continue;
    for (const btn of box.querySelectorAll(".pill")) {
      btn.onclick = () => {
        const on = [...box.querySelectorAll(".pill.on")].map((b) => b.dataset.v);
        const next = btn.classList.contains("on")
          ? on.filter((v) => v !== btn.dataset.v) : on.concat(btn.dataset.v);
        if (!next.length) { toast("至少要留一个地区，全不选的话这个任务会直接结束"); return; }
        btn.classList.toggle("on");
        const from = valueNow(g, f) || [];
        const order = ((((snap && snap.master) || {})[g.game] || {}).options || {})[f.path] || [];
        const rank = (v) => order.findIndex(([, x]) => String(x) === String(v));
        note(id, g, f, [...from], next.slice().sort((a, b) => rank(a) - rank(b)));
      };
    }
  }
}

/* 重渲染后把**未保存的改动**写回控件。没有这一步，一刷新界面就"复原"
   （下拉显示旧值、高亮消失），但「N 项待保存」还挂着，点保存会把
   已经看不见的改动发出去——界面骗人。2026-09-01 实测出来的。 */
function applyEdits() {
  for (const [key, e] of Object.entries(edits)) {
    const el = document.querySelector(`[data-id="${CSS.escape(key)}"]`);
    if (!el) continue;
    if (el.type === "checkbox") el.checked = !!e.to;
    else el.value = String(e.to);
  }
  for (const [key, e] of Object.entries(edits)) {
    const box = document.querySelector(`[data-pills="${CSS.escape(key)}"]`);
    if (!box) continue;
    const on = new Set((e.to || []).map(String));
    for (const b of box.querySelectorAll(".pill")) b.classList.toggle("on", on.has(b.dataset.v));
    const row = document.querySelector(`[data-row="${CSS.escape(key)}"]`);
    if (row) row.classList.add("changed");
  }
  updateBar();
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
/* 判开关机只有一条依据：**最新状态够不够新鲜**。

   慢和误报的共同根源（2026-09-01 用户反馈「每次等好久、开机有时显示成
   关机」）：机器开着但闲着时中继不推状态（只在开机/跑完/改配置时推），
   页面全靠那一条 refresh 应答；而旧实现是 600ms 一轮地轮询 ntfy，
   应答丢一次（中继长连接恰在重连的窗口）就走满全程然后误判关机。

   现在：
   · 用 SSE 实时流收应答——状态一推就到，开机响应从「轮询碰运气」变成
     一两秒内必达；
   · 4 秒没动静自动补发一次 refresh，单条丢失不再致命；
   · 8 秒时再用一次普通拉取兜底（SSE 万一被网络设备掐断）；
   · 判定给依据：「没应答刷新」写进文案，不再假装确定。 */
const FRESH_MS = 3 * 60 * 1000;
const JUST_MS = 60 * 1000;

async function ping(minAt) {
  if (!cfg || !cfg.topic || !cfg.pin) {
    return setStatus("还没设置信箱，先去设置里填", "off");
  }
  setStatus("正在问机器…", "");
  const floor = (typeof minAt === "number" ? minAt : null) ?? 0;
  let best = snap;
  let sseLatest = null;

  // 先挂流再发指令，免得应答赶在监听之前
  let es = null;
  try {
    es = new EventSource(`${NTFY}/${cfg.topic}/sse?since=30s`);
    es.onmessage = async (ev) => {
      try {
        const d = JSON.parse(ev.data);
        if (d.event && d.event !== "message") return;
        const m = JSON.parse(d.message);
        if (!m || m.kind !== "state" || m.pin !== cfg.pin) return;
        const body = await unwrap(m);
        if (body && (!sseLatest || body.at > sseLatest.at)) sseLatest = body;
      } catch {}
    };
  } catch {}

  try { await send({ action: "refresh" }); }
  catch (e) { es && es.close(); return setStatus("发不出去：" + e.message, "off"); }

  const t0 = Date.now();
  let resent = false, polled = false;
  try {
    while (Date.now() - t0 < 11000) {
      await new Promise((r) => setTimeout(r, 500));
      if (sseLatest && (!best || sseLatest.at > best.at)) best = sseLatest;
      if (best && best.at >= floor && Date.now() - best.at * 1000 < FRESH_MS
          && (!snap || best.at > snap.at)) {
        snap = best; save_cache(); render();
        const a = Date.now() - best.at * 1000;
        return setStatus(a < JUST_MS ? "开机中 · 刚刚更新"
                                     : `开机中 · 在忙，状态是 ${ago(best.at)}的`, "on");
      }
      if (!resent && Date.now() - t0 > 4000) {
        resent = true;
        send({ action: "refresh" }).catch(() => {});
      }
      if (!polled && Date.now() - t0 > 8000) {
        polled = true;
        try { const s = await latestState("2h");
              if (s && (!best || s.at > best.at)) best = s; } catch {}
      }
    }
  } finally { es && es.close(); }

  // 走满全程没等到应答——按最新状态的年龄下结论，并写明依据
  if (best && (!snap || best.at > snap.at)) { snap = best; save_cache(); render(); }
  if (!best) {
    try { await latestState("2h"); } catch {}
    if (pinScan.seen > 0 && pinScan.matched === 0) {
      return setStatus(`信箱里有 ${pinScan.seen} 条消息但 PIN 对不上——检查设置里的 PIN`, "off");
    }
    return setStatus("关机中 · 还没有过状态", "off");
  }
  const age = Date.now() - best.at * 1000;
  if (age < JUST_MS)  return setStatus("开机中 · 刚刚更新", "on");
  if (age < FRESH_MS) return setStatus(`开机中 · 在忙，状态是 ${ago(best.at)}的`, "on");
  return setStatus(`关机中（没应答刷新）· 状态是 ${ago(best.at)}的`, "off");
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
  const live = e.src === "master"
    ? ((((snap && snap.master) || {})[e.owner] || {}).options || {})[e.path]
    : (((snap && snap.options) || {})[e.owner] || {})[e.path];
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

/* ---------- 启动 ---------- */
/* ---------- ToDesk 式在线状态 ----------
   用户 2026-09-02：「和 ToDesk 一样，打开就是在线或离线，不用手动刷新，
   不用轮询；手动刷新是兜底不是常规。」

   页面打开：查一眼最近 90 秒有没有心跳（一次拉取），同时发一条「我在看」
   (watch)，机器收到立刻跳一次、之后每 30 秒跳一次，持续 10 分钟（页面在
   前台每 8 分钟续一次）。页面挂一条 SSE 实时收：心跳/状态一到翻开机，
   收到 bye（优雅关机）秒翻关机，硬断电靠 90 秒没心跳翻过来。
   updateLive 的定时器是本地计时，不碰网络——页面上没有轮询。

   为什么机器不盲跳：ntfy.sh 每个 IP 每天 250 条，盲跳会把额度吃光。 */
const HB_FRESH_MS = 90 * 1000;
const WATCH_RENEW_MS = 8 * 60 * 1000;
const CONFIRM_MS = 8 * 1000;
let lastHb = 0;
let liveES = null;
let pendingUntil = 0;

function updateLive() {
  if (!cfg) return;
  const alive = lastHb && (Date.now() - lastHb < HB_FRESH_MS);
  if (alive) {
    setStatus(`开机中 · 实时${snap ? `（配置是 ${ago(snap.at)}的）` : ""}`, "on");
  } else if (Date.now() < pendingUntil) {
    setStatus("正在确认是否在线…", "");
  } else if (snap) {
    setStatus(`关机中 · 最后状态 ${ago(snap.at)}前`, "off");
  } else {
    setStatus("关机中 · 还没有过状态", "off");
  }
}
setInterval(updateLive, 5000);

function askWatch() {
  // 「我在看」：机器收到立刻跳一次。8 秒内没回应就按关机算。
  if (!cfg || !cfg.topic || !cfg.pin) return;
  if (!(lastHb && Date.now() - lastHb < HB_FRESH_MS)) pendingUntil = Date.now() + CONFIRM_MS;
  updateLive();          // 马上显示「正在确认…」，别让旧的「关机中」多挂 5 秒
  send({ action: "watch" }).catch(() => {});
}
setInterval(() => { if (!document.hidden) askWatch(); }, WATCH_RENEW_MS);

async function probeHb() {
  // 打开页面/回到前台时查一次心跳历史，有就立判开机
  try {
    const r = await fetch(`${NTFY}/${cfg.topic}-hb/json?poll=1&since=90s&_=${Date.now()}`,
                          { cache: "no-store" });
    let hb = 0, bye = 0;
    for (const l of (await r.text()).split("\n")) {
      if (!l.trim()) continue;
      try {
        const e = JSON.parse(l);
        if (e.event !== "message") continue;
        if (e.message === "bye") bye = Math.max(bye, e.time * 1000);
        else hb = Math.max(hb, e.time * 1000);
      } catch {}
    }
    lastHb = (bye >= hb) ? 0 : hb;
  } catch {}
}

function startLive() {
  if (liveES) { try { liveES.close(); } catch {} }
  try {
    liveES = new EventSource(`${NTFY}/${cfg.topic},${cfg.topic}-hb/sse?since=30s`);
    liveES.onmessage = async (ev) => {
      try {
        const d = JSON.parse(ev.data);
        if (d.event && d.event !== "message") return;
        if (d.topic === cfg.topic + "-hb") {
          if (d.message === "bye") { lastHb = 0; pendingUntil = 0; }
          else lastHb = d.time * 1000;
          updateLive();
          return;
        }
        let m; try { m = JSON.parse(d.message); } catch { return; }
        if (!m || m.kind !== "state" || m.pin !== cfg.pin) return;
        const body = await unwrap(m);
        if (!body) return;
        if (!snap || body.at > snap.at) { snap = body; save_cache(); render(); }
        lastHb = Math.max(lastHb, d.time * 1000);   // 状态包也是活着的证据
        updateLive();
      } catch {}
    };
  } catch {}
}

document.addEventListener("visibilitychange", async () => {
  if (document.hidden || !cfg) return;
  startLive();
  await probeHb(); updateLive();
  askWatch();
});

/* 免输入链接：把信箱和 PIN 放在链接的 `#` 后面，页面读一次存下来就把它抹掉。
   为什么不直接写进代码里：这个页面挂在公开的 GitHub Pages 上、仓库也是公开的，
   写进去等于把遥控信道贴在互联网上——任何人都能按那个红色的「停止一切」。
   `#` 后面的内容浏览器不会发给服务器，也不进仓库，只存在你自己那条书签里。
   用户 2026-09-04：「把信箱和 pin 这个设计删了就行」——要删的是**每次去填**，
   这样就一次都不用填了。 */
function fromLink() {
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

function myLink() {
  const b = btoa(unescape(encodeURIComponent(
    JSON.stringify({ t: cfg.topic, p: cfg.pin }))))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return location.origin + location.pathname + "#k=" + b;
}

async function boot() {
  fromLink();
  const raw = localStorage.getItem(LS);
  if (!raw) return setupScreen();
  cfg = JSON.parse(raw);
  try { snap = JSON.parse(localStorage.getItem(LS + "-snap") || "null"); } catch { snap = null; }
  render();
  setStatus(snap ? `状态是 ${ago(snap.at)}的` : "正在读取…", "");
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
    setStatus("读不到信箱：" + e.message, "off");
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
  const all = Object.values(edits);
  const wbEdits = all.filter((e) => e.src === "wb");
  const items = all.filter((e) => e.src !== "wb");
  let sent = 0;
  for (const e of items) {
    const body = e.src === "master"
      ? { action:"set_master", confirmed:true, game:e.owner, path:e.path, value:e.to }
      : { action:"set_config", confirmed:true, script:e.owner, path:e.path, value:e.to };
    try { await send(body); sent++; }
    catch (err) { toast("第 " + (sent + 1) + " 项发不出去：" + err.message); break; }
  }
  /* 周本是一条指令带四个参数，不能一项一条发——分开发的话，中间那条
     会拿着别的三个旧值去覆盖。所以按现值合成一次发。 */
  if (wbEdits.length) {
    const base = (((snap && snap.relay) || {})["周本"]) || {};
    const get = (k, d) => {
      const hit = wbEdits.find((e) => e.key === k);
      return hit ? hit.to : (base[k] ?? d);
    };
    try {
      await send({ action:"weekly_boss", on: !!get("开", false),
                   index: Number(get("第几个周本", 1)) || 1,
                   count: Number(get("打几次", 1)) || 1,
                   level: String(get("难度等级", "90")) });
      sent += wbEdits.length;
    } catch (err) { toast("周本设置发不出去：" + err.message); }
  }
  if (sent) {
    edits = {}; updateBar();
    toast(`${sent} 项已发出。机器开着就是马上生效，关着就是下次开机；生效后会有通知。`, 5000);
    const after = now();          // 只认这一刻之后上报的状态
    setTimeout(() => ping(after), 2000);
  }
  saving = false;
};

applyTheme();
// 跟随系统时，系统切了日夜要立刻跟上
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
boot();

/* 所有重渲染之后都要把未保存的改动写回控件（见 applyEdits 的注释）。
   包在这里统一接管，免得每个 render() 调用点都要记得跟一句。 */
{
  const _renderRaw = render;
  render = (...a) => { _renderRaw(...a); applyEdits(); };
}
