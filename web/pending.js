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
/* 三态的第三态：机器回执对上了，记下「已应用 HH:MM」在控件下面再挂一天（2026-09-18，用户要三态文案都在）。
   以前对上就直接删掉 pending，行下什么都不剩，看不出这项是刚生效的还是一直如此。 */
const ACKED_KEY = "ark-remote-acked";
let acked = {};      // id -> {at, label}
try { acked = JSON.parse(localStorage.getItem(ACKED_KEY) || "{}") || {}; } catch { acked = {}; }
function saveAcked() { try { localStorage.setItem(ACKED_KEY, JSON.stringify(acked)); } catch {} }
let liveVals = {};   // 最近一次 render 时每个字段在机器上的值：id -> value
const sameVal = (a, b) => b && typeof b === "object" && !Array.isArray(b)   // multi-input: the boxes that were sent now read back as sent
  ? Object.entries(b).every(([k, x]) => String((a || {})[k] ?? "") === String(x ?? ""))
  : Array.isArray(a) || Array.isArray(b)
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
      for (const b of document.querySelectorAll(`[data-box="${CSS.escape(key)}"]`))
        if (p.to && typeof p.to === "object" && b.dataset.k in p.to) b.value = p.to[b.dataset.k];
      const box = row.querySelector(`[data-pills="${CSS.escape(key)}"]`);
      if (box) {
        const on = new Set([].concat(p.to ?? []).map(String));
        for (const b of box.querySelectorAll(".pill")) b.classList.toggle("on", on.has(b.dataset.v));
      }
    }
    row.querySelectorAll(".sent").forEach((x) => x.remove());
    /* 控件下的一行小字（信息 App「已送达」的位置和字号）：已寄出 · 机器开机后生效 / 没生效 · 再发一次 */
    const tag = document.createElement("div");
    if (p.mismatchAt) {
      tag.className = "sent bad";
      tag.innerHTML = `没生效 · 机器 ${hhmm(p.mismatchAt)} 报的还是「${valLabel(p, liveVals[key])}」<button type="button" class="again" data-again="${key}">再发一次</button>`;
    } else {
      tag.className = "sent";
      const old = (now() - p.sentAt) > 10 * 3600;
      tag.textContent = `已寄出 ${hhmm(p.resentAt || p.sentAt)} · ${snap && (now() - snap.at) < FRESH_MS / 1000 ? "几秒内回执" : "机器开机后生效"}` +
        (old ? " · 超过 10 小时，机器开机时会自动重发" : "");
    }
    row.appendChild(tag);
    row.classList.add("posted");
  }
  /* 已应用 HH:MM：对上回执的项，挂一天；再改这项就撤掉。 */
  for (const [key, a] of Object.entries(acked)) {
    if (key in pending || key in edits || now() - a.at > 24 * 3600) { if (now() - a.at > 24 * 3600) { delete acked[key]; saveAcked(); } continue; }
    const row = document.querySelector(`[data-row="${CSS.escape(key)}"]`);
    if (!row) continue;
    row.querySelectorAll(".sent").forEach((x) => x.remove());
    const tag = document.createElement("div");
    tag.className = "sent ok"; tag.textContent = `已应用 ${hhmm(a.at)}`;
    row.appendChild(tag);
  }
  const n = Object.keys(pending).length;
  const bar = $("#pendbar");
  if (bar) {
    bar.hidden = !n;
    if (n) {
      const bad = Object.values(pending).filter((p) => p.mismatchAt).length;
      bar.innerHTML = (bad
        ? `${sf("xmark.circle.fill", "bad inl")}${bad} 项改动机器没接受（见红字）` + (n - bad ? `，另 ${n - bad} 项还在等回执` : "")
        : `${n} 项改动已寄出 · 机器开机后生效`) +
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
      acked[key] = { at: snap.at, label: p.label }; saveAcked();
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
