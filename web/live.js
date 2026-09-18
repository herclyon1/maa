/* ToDesk 式在线判定（从 app.js 原样切出）：ping/_ping、心跳窗口、SSE startLive、updateLive（写 #status/#dot）。 */
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
  const rt = $("#refresh"); if (rt) rt.classList.add("busy");
  // 体力数字：和问机器同时问游戏（一分钟内重复的动作复用上次的）；回来就重画磁贴
  const stam = window.Stamina ? Stamina.refresh(false).then(() => render()).catch(() => {}) : null;
  try { return await _ping(minAt); } finally { if (stam) await stam; const r2 = $("#refresh"); if (r2) r2.classList.remove("busy"); }
}
async function _ping(minAt) {
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
        const m = envelope(d);
        if (!m || m.kind !== "state" || m.pin !== cfg.pin) return;
        const body = m.gzp !== undefined ? await joinChunks(m) : await unwrap(m);
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
                                     : `开机中 · 在忙 · 状态 ${ago(best.at)}`, "on");
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
    return setStatus(lastBeat() ? `关机 · 最后心跳 ${lastBeat()}` : "关机 · 还没有过心跳", "off");
  }
  const age = Date.now() - best.at * 1000;
  if (age < JUST_MS)  return setStatus("开机中 · 刚刚更新", "on");
  if (age < FRESH_MS) return setStatus(`开机中 · 在忙 · 状态 ${ago(best.at)}`, "on");
  sawHb(best.at * 1000);
  return setStatus(`关机 · 没应答刷新 · 最后心跳 ${lastBeat()}`, "off");
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
const HB_FRESH_MS = 90 * 1000;      // 正常节奏（30 秒一跳）下的判定窗口
// 机器把当前心跳节奏写在消息里（"hb 30" / "hb 300"）。日上限一到它就降到 5 分钟
// 一跳，而这边固定按 90 秒判「关机中」——于是每 5 分钟里有 3 分半是假的红，
// 机器正在跑。窗口不能一味放宽：那会拖慢它唯一存在的理由（看出真的关机了）。
let hbEvery = 30;                   // 秒，由心跳消息本身报上来
function hbWindowMs() {
  return Math.max(HB_FRESH_MS, hbEvery * 2000 + 30000);
}
const WATCH_RENEW_MS = 8 * 60 * 1000;
const CONFIRM_MS = 8 * 1000;
let lastHb = 0;
/* 最后一次看到机器活着的时刻（心跳、状态包或 bye），关机文案「关机 · 最后心跳 HH:MM」用；存 localStorage 免得刷新后不知道。 */
let hbSeen = Number(localStorage.getItem("ark-remote-hb") || 0);
function sawHb(ms) { if (ms > hbSeen) { hbSeen = ms; try { localStorage.setItem("ark-remote-hb", String(ms)); } catch {} } }
const lastBeat = () => hbSeen ? new Date(hbSeen).toTimeString().slice(0, 5) : (snap && snap.at ? new Date(snap.at * 1000).toTimeString().slice(0, 5) : "");
let liveES = null;
let pendingUntil = 0;
// 上一次跟外面说话成功了没有。没有它的话，页面分不清「机器关了」和「我这边没网」，
// 于是他在信号差的地方看到的是一句斩钉截铁的「关机中」，据此以为机器没开。
let netOk = true;
addEventListener("online", () => { netOk = true; updateLive(); });
addEventListener("offline", () => { netOk = false; updateLive(); });

function offline() {
  return !navigator.onLine || !netOk;
}

function why(err) {
  // 浏览器的原文是英文（Failed to fetch / NetworkError），直接甩给他等于没说。
  const m = String((err && err.message) || err || "");
  if (/fetch|network|load failed/i.test(m)) return "网络不通";
  if (/429/.test(m)) return "发得太频繁，被限流了";
  if (/abort|timeout/i.test(m)) return "等太久没回应";
  return m || "原因不明";
}

let wasAlive = null;
function updateLive() {
  if (!cfg) return;
  const alive = lastHb && (Date.now() - lastHb < hbWindowMs());
  if (wasAlive !== null && !!alive !== wasAlive && snap) render();   // the 「现在在跑」 card follows the verdict
  wasAlive = !!alive;
  if (alive) {
    setStatus(`开机中 · ${hbEvery > 60 ? `每 ${Math.round(hbEvery / 60)} 分钟报一次` : "实时"}`
              + (snap ? ` · 配置 ${ago(snap.at)}` : ""), "on");
  } else if (Date.now() < pendingUntil) {
    setStatus("正在确认是否在线…", "");
  } else if (offline()) {
    // 连不上就只说连不上。这台机器可能开着，只是话传不过来。
    setStatus(snap ? `连不上 · 先看看你这边有没有网 · 最后状态 ${ago(snap.at)}`
                   : "连不上 · 先看看你这边有没有网", "");
  } else if (lastBeat()) {
    setStatus(`关机 · 最后心跳 ${lastBeat()}`, "off");   // 验收 2026-09-18 定的离线文案
  } else {
    setStatus("关机 · 还没有过心跳", "off");
  }
}
setInterval(updateLive, 5000);

function askWatch() {
  // 「我在看」：机器收到立刻跳一次。8 秒内没回应就按关机算。
  if (!cfg || !cfg.topic || !cfg.pin) return;
  if (!(lastHb && Date.now() - lastHb < hbWindowMs())) pendingUntil = Date.now() + CONFIRM_MS;
  updateLive();          // 马上显示「正在确认…」，别让旧的「关机中」多挂 5 秒
  send({ action: "watch" }).then(() => { netOk = true; })
                           .catch(() => { netOk = false; updateLive(); });
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
        else {
          hb = Math.max(hb, e.time * 1000);
          const m = /^hb\s+(\d+)$/.exec(String(e.message || ""));
          if (m) hbEvery = Number(m[1]) || hbEvery;
        }
      } catch {}
    }
    lastHb = (bye >= hb) ? 0 : hb; sawHb(Math.max(hb, bye));
    netOk = true;
  } catch { netOk = false; }
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
          sawHb(d.time * 1000);
          if (d.message === "bye") { lastHb = 0; pendingUntil = 0; }
          else {
            lastHb = d.time * 1000;
            const hm = /^hb\s+(\d+)$/.exec(String(d.message || ""));
            if (hm) hbEvery = Number(hm[1]) || hbEvery;
            resendStale();
          }
          updateLive();
          return;
        }
        let m; try { m = JSON.parse(d.message); } catch { return; }
        if (!m || m.kind !== "state" || m.pin !== cfg.pin) return;
        const body = await unwrap(m);
        if (!body) return;
        if (!snap || body.at > snap.at) { snap = body; save_cache(); render(); }
        lastHb = Math.max(lastHb, d.time * 1000); sawHb(d.time * 1000);   // 状态包也是活着的证据
        resendStale();
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
