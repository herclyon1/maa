/* 信箱协议（从 app.js 原样切出）：send / readMessages / envelope / joinChunks / unwrap / latestState。依赖 view.js 的 cfg（运行时才读）。 */
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

/* 一条状态可能以三种形态到达：明文、压缩过的、或者太大被 ntfy 转成的附件。
   三种都要认。
   2026-09-09 之前超限的处理是**砍字段**——先砍明日安排、再砍选项表，手机上那些
   中文下拉不声不响就没了；砍完还超就发一个读不懂的包，页面只好一直显示旧值，
   看上去像刷新坏了。实测通道其实允许 15MB：超过 4096 字节 ntfy 会自动存成附件
   并给出网址，取回来一字不差。所以现在什么都不砍。 */
function envelope(e) {
  /* 一条 ntfy 消息 → 我们的信封对象。 */
  try {
    const m = JSON.parse(e.message);
    return m && m.kind ? m : null;
  } catch { return null; }
}

/* 太大的状态被切成了多条普通消息（不用附件：附件三小时就过期，而昨晚关机前
   发的那份正是第二天早上要看的；普通消息和别的一样保留十二小时）。
   同一份状态的每一片带同一个 sid 和自己的 i/n，凑齐才还原——凑不齐就当没有，
   绝不把半份状态当成完整的显示出来。 */
const chunkBox = new Map();

async function joinChunks(m) {
  if (m.gzp === undefined) return null;
  const got = chunkBox.get(m.sid) || new Map();
  got.set(m.i, m.gzp);
  chunkBox.set(m.sid, got);
  if (got.size < m.n) return null;
  chunkBox.delete(m.sid);
  const blob = Array.from({ length: m.n }, (_, i) => got.get(i)).join("");
  return await unwrap({ gz: blob });
}

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
  chunkBox.clear();
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = envelope(msgs[i]);
    if (!m || m.kind !== "state") continue;
    pinScan.seen++;
    if (m.pin !== cfg.pin) continue;
    pinScan.matched++;
    if (m.gzp !== undefined) {
      // 切片是从新往旧扫到的，同一份的都会遇上；凑齐了就还原，凑不齐接着往前找
      try { const done = await joinChunks(m); if (done) return done; } catch {}
      continue;
    }
    try { return await unwrap(m); } catch { return null; }
  }
  return null;
}
