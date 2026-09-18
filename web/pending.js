/* 寄出未回执的改动（从 app.js 原样切出）：pending 持久化、applyPending（写回控件 + 行下标签，用 DOM 钩子 data-row/data-id/data-relay/data-pills/#pendbar）、reconcilePending、resend。 */
/* ---------- 寄出了、还没拿到回执的改动 ----------
   2026-09-13 用户：机器关着时改配置「完全没有任何显示成功，感觉像没生效，
   静默失败」。原因：保存后 5 秒的提示一闪就没了，随后 render() 把控件
   写回机器上次上报的旧值——看起来就是「改了又弹回去」。
   现在每一项寄出去的改动都记在这里（localStorage，关页面也在），控件显示
   寄出去的新值、行下面挂一条「已寄出 HH:MM，等机器开机」；机器上报一份
   **晚于寄出时刻**的状态时逐项核对：值对上＝生效，划掉；对不上＝红字
   「机器上报的还是旧值，这项没生效」，并给「再发一次」。 */
const PENDING_KEY = "ark-remote-pending";
let pending = {};    // id -> {label, src, owner, path, from, to, sentAt, resentAt?, mismatchAt?}
try { pending = JSON.parse(localStorage.getItem(PENDING_KEY) || "{}") || {}; } catch { pending = {}; }
function savePending() { try { localStorage.setItem(PENDING_KEY, JSON.stringify(pending)); } catch {} }
let liveVals = {};   // 最近一次 render 时每个字段在机器上的值：id -> value
const sameVal = (a, b) => Array.isArray(a) || Array.isArray(b)
  ? JSON.stringify([].concat(a ?? []).map(String).sort()) === JSON.stringify([].concat(b ?? []).map(String).sort())
  : String(a ?? "") === String(b ?? "");
const hhmm = (ts) => new Date(ts * 1000).toTimeString().slice(0, 5);
/* 重渲染后把**未保存的改动**写回控件。没有这一步，一刷新界面就"复原"
   （下拉显示旧值、高亮消失），但「N 项待保存」还挂着，点保存会把
   已经看不见的改动发出去——界面骗人。2026-09-01 实测出来的。 */
function applyPending() {
  for (const [key, p] of Object.entries(pending)) {
    const row = document.querySelector(`[data-row="${CSS.escape(key)}"]`);
    if (!row) continue;
    if (!(key in edits)) {
      const el = row.querySelector(`[data-id="${CSS.escape(key)}"]`) || row.querySelector(`[data-relay="${CSS.escape(key)}"]`);
      if (el) { if (el.type === "checkbox") el.checked = !!p.to; else el.value = String(p.to); }
      for (const b of row.querySelectorAll(".pick"))
        b.classList.toggle("on", String(b.dataset.v) === String(p.to));
      const box = row.querySelector(`[data-pills="${CSS.escape(key)}"]`);
      if (box) {
        const on = new Set([].concat(p.to ?? []).map(String));
        for (const b of box.querySelectorAll(".pill")) b.classList.toggle("on", on.has(b.dataset.v));
      }
    }
    row.querySelectorAll(".sent").forEach((x) => x.remove());
    const tag = document.createElement("div");
    if (p.mismatchAt) {
      tag.className = "sent bad";
      tag.innerHTML = `${sf("xmark.circle.fill", "bad inl")}机器 ${hhmm(p.mismatchAt)} 上报的还是「${valLabel(p, liveVals[key])}」，` +
        `这项没生效 <button type="button" class="again" data-again="${key}">再发一次</button>`;
    } else {
      tag.className = "sent";
      const old = (now() - p.sentAt) > 10 * 3600;
      tag.textContent = `📮 已寄出 ${hhmm(p.sentAt)}${p.resentAt ? `（${hhmm(p.resentAt)} 又发了一次）` : ""}` +
        `，${snap && (now() - snap.at) < FRESH_MS / 1000 ? "机器开着，几秒内回执" : "等机器开机生效，还没回执"}` +
        (old ? "。寄出超过 10 小时：信箱只保管 12 小时，机器再开机时这页若开着会自动重发" : "");
    }
    row.appendChild(tag);
    row.classList.add("posted");
  }
  const n = Object.keys(pending).length;
  const bar = $("#pendbar");
  if (bar) {
    bar.hidden = !n;
    if (n) {
      const bad = Object.values(pending).filter((p) => p.mismatchAt).length;
      bar.innerHTML = (bad
        ? `${sf("xmark.circle.fill", "bad inl")}${bad} 项改动机器没接受（见红字）` + (n - bad ? `，另 ${n - bad} 项还在等回执` : "")
        : `📮 ${n} 项改动已寄出，机器开机后生效；生效了这条会自己消失`) +
        ` <button type="button" id="pendclear">不等了，清掉</button>`;
      $("#pendclear").onclick = () => { pending = {}; savePending(); render(); };
    }
  }
  for (const b of document.querySelectorAll("[data-again]")) b.onclick = () => resend(b.dataset.again);
}

/* 机器上报了一份晚于寄出时刻的状态：逐项对答案。 */
function reconcilePending() {
  if (!snap || !snap.at) return;
  let changed = false;
  for (const [key, p] of Object.entries(pending)) {
    if (snap.at <= (p.resentAt || p.sentAt)) continue;
    if (!(key in liveVals)) continue;          // 这一份状态里没带这个字段，等下一份
    if (sameVal(liveVals[key], p.to)) {
      delete pending[key]; changed = true;
      toast(`「${p.label}」已生效：${valLabel(p, p.to)}`, 5000);
    } else if (p.mismatchAt !== snap.at) {
      p.mismatchAt = snap.at; changed = true;
    }
  }
  if (changed) savePending();
}

async function resend(key) {
  const p = pending[key];
  if (!p) return;
  const body = p.src === "relay" ? p.body
    : p.src === "master"
    ? { action:"set_master", confirmed:true, game:p.owner, path:p.path, value:p.to }
    : { action:"set_config", confirmed:true, script:p.owner, path:p.path, value:p.to };
  try { await send(body); p.resentAt = now(); delete p.mismatchAt; savePending(); render();
        toast(`「${p.label}」又发了一次`, 4000); }
  catch (e) { toast("发不出去：" + why(e), 6000); }
}

/* 信箱只保管 12 小时。机器开机时这页若开着，寄出超过 10 小时还没回执的
   自动再发一次（改同一个值两遍没有副作用）。 */
function resendStale() {
  for (const [key, p] of Object.entries(pending)) {
    const at = p.resentAt || p.sentAt;
    if (!p.mismatchAt && now() - at > 10 * 3600) resend(key);
  }
}
