/* 体力数字：网页自己去问游戏的官方接口，不经过机器。
   森空岛（明日方舟理智、终末地理智）和库街区（鸣潮波片）的接口都允许浏览器
   跨域调用（2026-09-15 实测 OPTIONS 预检全部放行）。
   森空岛的登录会话（cred、签名 token、设备号、账号 id）由机器在状态快照里交过来
   （浏览器做不了 token 换 cred 那一步），网页收到就存进这台手机的 localStorage；
   库街区的 token 和设备号在「手机 › 游戏账号」里粘贴。

   只在你动作的时候读：打开页面、下拉刷新、按「刷新」磁贴。没有任何定时器。
   一分钟内重复动作复用上一次的结果。

   森空岛签名（照 relay/ark_relay/skland.py 移植）：
     secret = path + query + timestamp + JSON({platform,timestamp,dId,vName})
     sign   = md5(hex(hmac_sha256(token, secret)))
   时间戳要用服务器的：先 GET /web/v1/auth/refresh，它回 timestamp 和新 token。 */
(function () {
  const LS_TOKENS = "ark-remote-tokens";
  const ZONAI = "https://zonai.skland.com";
  const KURO = "https://api.kurobbs.com";
  const MIN_GAP_MS = 60 * 1000;

  const Stamina = { data: null, at: 0, busy: false, tokens: null, err: "" };

  // ---- MD5（森空岛的 sign 要它；WebCrypto 没有）----
  function md5(str) {
    const bytes = new TextEncoder().encode(str);
    const n = bytes.length;
    const words = new Array(((n + 8 >> 6) + 1) * 16).fill(0);
    for (let i = 0; i < n; i++) words[i >> 2] |= bytes[i] << ((i % 4) * 8);
    words[n >> 2] |= 0x80 << ((n % 4) * 8);
    words[words.length - 2] = n * 8;
    const K = new Array(64), S = [7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21];
    for (let i = 0; i < 64; i++) K[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 2 ** 32);
    let a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
    const rotl = (x, c) => (x << c) | (x >>> (32 - c));
    for (let j = 0; j < words.length; j += 16) {
      let a = a0, b = b0, c = c0, d = d0;
      for (let i = 0; i < 64; i++) {
        let f, g;
        if (i < 16) { f = (b & c) | (~b & d); g = i; }
        else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) % 16; }
        else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) % 16; }
        else { f = c ^ (b | ~d); g = (7 * i) % 16; }
        const tmp = d; d = c; c = b;
        b = (b + rotl((a + f + K[i] + words[j + g]) | 0, S[(i >> 4) * 4 + (i % 4)])) | 0;
        a = tmp;
      }
      a0 = (a0 + a) | 0; b0 = (b0 + b) | 0; c0 = (c0 + c) | 0; d0 = (d0 + d) | 0;
    }
    const hex = (x) => [0, 1, 2, 3].map((i) => ((x >>> (i * 8)) & 255).toString(16).padStart(2, "0")).join("");
    return hex(a0) + hex(b0) + hex(c0) + hex(d0);
  }

  async function hmacHex(key, msg) {
    const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const sig = await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(msg));
    return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  // ---- 密钥进出 ----
  function loadTokens() {
    try { Stamina.tokens = JSON.parse(localStorage.getItem(LS_TOKENS) || "null"); } catch { Stamina.tokens = null; }
    return Stamina.tokens;
  }
  function saveTokens(t) {
    Stamina.tokens = t;
    try { localStorage.setItem(LS_TOKENS, JSON.stringify(t)); } catch {}
  }
  function decodeB64(s) {
    return JSON.parse(decodeURIComponent(escape(atob(s.replace(/-/g, "+").replace(/_/g, "/")))));
  }
  /* 链接里的 #t=… 或粘贴的一串：{sk:{cred,token,dId,uid,efRole,efServer}, kuro:{token,did,roleId,serverId}} */
  function fromLink() {
    const m = /[#&]t=([A-Za-z0-9_-]+)/.exec(location.hash || "");
    if (!m) return false;
    try {
      const j = decodeB64(m[1]);
      if (!j.sk && !j.kuro) return false;
      saveTokens(j);
      history.replaceState(null, "", location.pathname + location.search + (location.hash.replace(/[#&]t=[A-Za-z0-9_-]+/, "") === "#" ? "" : location.hash.replace(/[#&]t=[A-Za-z0-9_-]+/, "")));
      return true;
    } catch { return false; }
  }
  /* 粘贴：两行 KUROBBS_TOKEN=… / KUROBBS_DID=…（和电脑上 ~/.config/ark/.env 里一样），
     或者一整段 JSON。 */
  function fromPaste(s) {
    const str = String(s || "").trim();
    let j = null;
    if (/^\s*[{\[]/.test(str)) { j = JSON.parse(str); }
    else {
      const kv = {};
      for (const line of str.split(/\r?\n|[;,\s]+(?=KUROBBS_)/)) { const m = /^\s*(KUROBBS_TOKEN|KUROBBS_DID)\s*[=:]\s*(\S+)/.exec(line); if (m) kv[m[1]] = m[2]; }
      if (kv.KUROBBS_TOKEN && kv.KUROBBS_DID) j = { kuro: { token: kv.KUROBBS_TOKEN, did: kv.KUROBBS_DID } };
    }
    if (!j || (!j.sk && !j.kuro)) throw new Error("没认出密钥：要 KUROBBS_TOKEN=… 和 KUROBBS_DID=… 两行");
    const cur = Stamina.tokens || loadTokens() || {};
    saveTokens({ ...cur, ...j });
    return j;
  }
  /* 机器在快照里交来的森空岛会话；和存着的不同才写。 */
  function fromSnapshot(snap) {
    const sk = snap && snap["密钥"] && snap["密钥"].sk;
    if (!sk || sk["错误"] || !sk.cred) return false;
    const cur = Stamina.tokens || loadTokens() || {};
    if (cur.sk && cur.sk.cred === sk.cred) return false;
    saveTokens({ ...cur, sk });
    return true;
  }
  function clear() { Stamina.tokens = null; Stamina.data = null; try { localStorage.removeItem(LS_TOKENS); } catch {} }

  // ---- 森空岛 ----
  async function skRefresh(sk) {
    const r = await fetch(`${ZONAI}/web/v1/auth/refresh`, { headers: { cred: sk.cred, dId: sk.dId || "" } });
    const j = await r.json();
    if (j.code !== 0 && j.code !== undefined) throw new Error("森空岛刷新失败：" + (j.message || j.code));
    const skew = j.timestamp ? Number(j.timestamp) - Math.floor(Date.now() / 1000) : 0;
    const token = (j.data || {}).token || sk.token;
    if (token !== sk.token) saveTokens({ ...Stamina.tokens, sk: { ...sk, token } });
    return { token, skew };
  }
  async function skGet(sk, tokenSkew, path) {
    const ts = String(Math.floor(Date.now() / 1000) + tokenSkew.skew);
    const u = new URL(ZONAI + path);
    const ca = { platform: "3", timestamp: ts, dId: sk.dId || "", vName: "1.0.0" };
    const secret = u.pathname + u.search.replace(/^\?/, "") + ts + JSON.stringify(ca);
    const sign = md5(await hmacHex(tokenSkew.token, secret));
    const r = await fetch(u.toString(), { headers: { cred: sk.cred, sign, ...ca } });
    const j = await r.json();
    if (j.code !== 0 && j.code !== undefined) throw new Error(j.message || ("code " + j.code));
    return j.data || {};
  }
  function stampFrom(epoch) {
    if (!epoch) return "";
    const d = new Date(Number(epoch) * 1000);
    const p = (x) => String(x).padStart(2, "0");
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  async function skland(sk) {
    const out = { "明日方舟": {}, "终末地": {} };
    let ts;
    try { ts = await skRefresh(sk); }
    catch (e) { out["明日方舟"] = { "错误": e.message }; out["终末地"] = { "错误": e.message }; return out; }
    try {
      if (!sk.uid) throw new Error("密钥串里没有明日方舟的 uid");
      const d = await skGet(sk, ts, `/api/v1/game/player/info?uid=${encodeURIComponent(sk.uid)}`);
      const ap = ((d.status || {}).ap) || {};
      out["明日方舟"] = arknightsLive(ap, Math.floor(Date.now() / 1000) + ts.skew);
    } catch (e) { out["明日方舟"] = { "错误": e.message }; }
    try {
      if (!sk.efRole) throw new Error("密钥串里没有终末地的角色");
      const d = await skGet(sk, ts, `/api/v1/game/endfield/card/detail?roleId=${encodeURIComponent(sk.efRole)}&serverId=${encodeURIComponent(sk.efServer || "1")}`);
      const dg = ((d.detail || {}).dungeon) || {};
      out["终末地"] = endfieldFromDungeon(dg);
    } catch (e) { out["终末地"] = { "错误": e.message }; }
    return out;
  }
  /* 真实样本（2026-09-15 08:5x，森空岛 player/info）：
       ap = {current: 2, max: 210, lastApAddTime: 1789392987, completeRecoveryTime: 1789467867}
     current 是 lastApAddTime 那一刻的数（游戏最后一次同步），之后森空岛不再动它——
     09-15 早上页面显示了一上午的 2/210 就是这么来的。现在的值要自己推：每 6 分钟 1 点，
     封顶 max。第三方工具（skland-daily 之类）也是这么算的。 */
  function arknightsLive(ap, nowSec) {
    const cur = Number(ap.current), top = Number(ap.max), last = Number(ap.lastApAddTime);
    if (!Number.isFinite(cur) || !Number.isFinite(top)) return { "错误": "森空岛没给理智" };
    let live = cur;
    if (Number.isFinite(last) && last > 0 && nowSec > last) live = Math.min(top, cur + Math.floor((nowSec - last) / 360));
    const o = { "理智": live, "上限": top };
    if (live < top && ap.completeRecoveryTime) o["回满"] = stampFrom(ap.completeRecoveryTime);
    return o;
  }
  /* 真实样本（2026-09-15 03:45，森空岛 card/detail）：
       dungeon = {"curStamina": "179", "maxTs": "1789490362", "maxStamina": "360"}
     值是字符串。curStamina 是活的（09-15 早上 216→219→221 跟着走），maxTs 反推每
     7.2 分钟回 1 点，所以直接用。先按这三个名字取；名字变了再按含义认（带 stamina/ap/sanity 的数字，
     带 max 的是上限），都认不出就把看到的名字列出来。 */
  function endfieldFromDungeon(dg) {
    const keys = Object.keys(dg || {});
    if (!keys.length) return { "错误": "森空岛没给终末地的理智" };
    const num = (v) => (v === undefined || v === null || v === "" || isNaN(Number(v))) ? undefined : Number(v);
    let cur = num(dg.curStamina), top = num(dg.maxStamina), full = num(dg.maxTs);
    if (cur === undefined || top === undefined) {
      const cands = keys.filter((k) => /stamina|ap|sanity|energy|power/i.test(k) && num(dg[k]) !== undefined);
      const big = cands.filter((k) => /max|limit/i.test(k)), small = cands.filter((k) => !/max|limit/i.test(k));
      if (cur === undefined && small.length) cur = Math.min(...small.map((k) => num(dg[k])));
      if (top === undefined && big.length) top = Math.max(...big.map((k) => num(dg[k])));
      if (full === undefined) { const k = keys.find((x) => /ts|time|recover|full/i.test(x) && num(dg[x]) > 1e9); if (k) full = num(dg[k]); }
    }
    if (cur === undefined) return { "错误": "终末地的理智没认出来：" + keys.slice(0, 6).join("、") };
    const o = { "理智": cur, "上限": top };
    if (full && cur < (top ?? Infinity)) o["回满"] = stampFrom(full);
    return o;
  }

  // ---- 库街区 ----
  async function kuroPost(path, headers, data) {
    const body = new URLSearchParams(data).toString();
    const r = await fetch(KURO + path, { method: "POST", headers: { source: "android", version: "3.1.3", "Content-Type": "application/x-www-form-urlencoded; charset=utf-8", ...headers }, body });
    const j = await r.json();
    if (!j.success || j.code !== 200) throw new Error(j.msg || j.message || ("code " + j.code));
    let d = j.data;
    if (typeof d === "string") { try { d = JSON.parse(d); } catch {} }
    return d;
  }
  async function kuro(k) {
    try {
      let roleId = k.roleId, serverId = k.serverId;
      if (!roleId) {
        const roles = await kuroPost("/gamer/role/list", { token: k.token, devCode: k.did }, { gameId: 3 });
        const w = (roles || []).find((r) => Number(r.gameId) === 3);
        if (!w) throw new Error("库街区账号下没有鸣潮角色");
        roleId = String(w.roleId); serverId = w.serverId || "";
        saveTokens({ ...Stamina.tokens, kuro: { ...k, roleId, serverId } });
      }
      /* akiBox/baseData 的 energy 是游戏上次同步时的数，几个小时不动（09-15 早上一直 91）；
         小组件接口 widget/game3/refresh 给的是现在的数，带回满时刻。真实样本：
           energyData = {name:"结晶波片", cur:141, total:240, refreshTimeStamp:1789465776}
           storeEnergyData = {cur:3, total:480}  weeklyData = {name:"战歌重奏", cur:1, total:3}
           livenessData = {cur:0, total:100} */
      const w = await kuroPost("/gamer/widget/game3/refresh", { token: k.token, did: k.did }, { gameId: 3, serverId, roleId, type: 1, sizeType: 1 });
      const e = w.energyData || {}, st = w.storeEnergyData || {}, wk = w.weeklyData || {}, lv = w.livenessData || {};
      if (e.cur === undefined) throw new Error("库街区没给波片：" + Object.keys(w).slice(0, 6).join("、"));
      const o = { "波片": e.cur, "上限": e.total, "备用": st.cur, "备用上限": st.total,
                  "周本": wk.cur, "周本上限": wk.total, "活跃": lv.cur, "活跃上限": lv.total };
      if (e.refreshTimeStamp > 0 && e.cur < e.total) o["回满"] = stampFrom(e.refreshTimeStamp);
      return o;
    } catch (e) { return { "错误": e.message }; }
  }

  // ---- 入口 ----
  /* 读一遍。`force` 跳过一分钟内的复用。返回和机器快照里同一形状的对象。 */
  async function refresh(force = false) {
    const t = Stamina.tokens || loadTokens();
    if (!t) return null;
    if (!force && Stamina.data && Date.now() - Stamina.at < MIN_GAP_MS) return Stamina.data;
    if (Stamina.busy) return Stamina.data;
    Stamina.busy = true;
    try {
      const [sk, ww] = await Promise.all([
        t.sk ? skland(t.sk) : Promise.resolve({ "明日方舟": { "错误": "没配森空岛" }, "终末地": { "错误": "没配森空岛" } }),
        t.kuro ? kuro(t.kuro) : Promise.resolve({ "错误": "没配库街区" }),
      ]);
      const d = new Date(); const p = (x) => String(x).padStart(2, "0");
      Stamina.data = { ...sk, "鸣潮": ww, "取自": `${p(d.getHours())}:${p(d.getMinutes())}` };
      Stamina.at = Date.now();
      return Stamina.data;
    } finally { Stamina.busy = false; }
  }
  function status() {
    const t = Stamina.tokens || loadTokens();
    if (!t) return "";
    return [t.sk ? "森空岛" : "", t.kuro ? "库街区" : ""].filter(Boolean).join("、");
  }

  Object.assign(Stamina, { refresh, fromLink, fromPaste, fromSnapshot, loadTokens, clear, status, endfieldFromDungeon, md5 });
  window.Stamina = Stamina;
})();
