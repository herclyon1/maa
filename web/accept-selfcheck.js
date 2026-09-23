/* accept-selfcheck.js — 真机自检 on the user's phone (WORKLIST P3, DECISIONS D31): the 运行自检 button, index.html's head sandbox (backup / restore /
   ntfy writes kept on the phone) and the 诊断记录 sheet carrying accept.js's result. The head script is re-run here against a stand-in storage and location
   (the real ones belong to the runner), so each branch — device start, restart after the run, a second start before the restore, a backup that cannot be
   written — is checked by what it leaves behind, not by reading the code. */
ACCEPT.add(async function selfcheck({ check, sleep }) {
  const $ = (s) => document.querySelector(s);
  /* 1. the runners (&quiet) never enter the sandbox: their fake mailbox stays, no backup key is written */
  check("自检沙箱：带 &quiet 的跑不进沙箱（__acceptDevice = false，无 ark-accept-restore）", "false, 无", `${window.__acceptDevice}, ${localStorage.getItem("ark-accept-restore") === null ? "无" : "有"}`,
        window.__acceptDevice === false && localStorage.getItem("ark-accept-restore") === null);
  /* 2. the head script, run against a stand-in localStorage / location / fetch */
  let code = "";
  try { const html = await (await fetch("index.html?v=" + Date.now(), { cache: "no-store" })).text(); const m = /<script>(\/\* 诊断记录 \(手机 tab[\s\S]*?)<\/script>/.exec(html); code = m ? m[1] : ""; } catch (e) {}
  check("自检沙箱：index.html 头部脚本读得到", "有", code.includes("ark-accept-restore") ? "有" : "缺", code.includes("ark-accept-restore"));
  const store = (init, failSet) => { const m = new Map(Object.entries(init)); return { get length() { return m.size; }, key: (i) => [...m.keys()][i] ?? null, getItem: (k) => m.has(k) ? m.get(k) : null,
    setItem: (k, v) => { if (failSet && k === "ark-accept-restore") throw new Error("QuotaExceededError"); m.set(k, String(v)); }, removeItem: (k) => { m.delete(k); }, clear: () => m.clear(), dump: () => Object.fromEntries([...m].sort()) }; };
  const run = (ls, search, top) => { const w = { calls: [], alerts: [], replaced: null }; w.top = top || w; w.fetch = (u, o) => { w.calls.push([String(u), o && o.method || "GET"]); return Promise.resolve(new Response("orig")); };
    const loc = { search, pathname: "/maa/", hash: "", replace: (u) => { w.replaced = u; } };
    new Function("window", "localStorage", "location", "alert", "history", code)(w, ls, loc, (t) => w.alerts.push(t), { replaceState() {} }); return w; };
  if (code) {
    const ls = store({ "ark-remote-cfg": "{\"topic\":\"T\",\"pin\":\"1\"}", "ark-stock": "A", "ark-accept": "old" });
    const w = run(ls, "?accept=1");
    const bak = JSON.parse(ls.getItem("ark-accept-restore") || "{}");
    check("自检沙箱 · 真机开跑：整份本机数据进备份（不含 ark-accept），信箱设置摘掉 → 演示数据，从「状态」起跑", "cfg 已备份, ark-stock 已备份, 信箱摘掉, 状态",
          `${bak["ark-remote-cfg"] ? "cfg 已备份" : "cfg 缺"}, ${bak["ark-stock"] === "A" ? "ark-stock 已备份" : "ark-stock 缺"}, ${ls.getItem("ark-remote-cfg") === null ? "信箱摘掉" : "信箱还在"}, ${ls.getItem("ark-remote-tab")}`,
          w.__acceptDevice === true && bak["ark-remote-cfg"] && bak["ark-stock"] === "A" && !("ark-accept" in bak) && ls.getItem("ark-remote-cfg") === null && ls.getItem("ark-remote-tab") === "状态");
    const post = await (await w.fetch("https://ntfy.sh/T", { method: "POST", body: "x" })).text(), put = await (await w.fetch("https://ntfy.sh/T", { method: "PUT" })).text();
    const get = await (await w.fetch("https://ntfy.sh/T/json?poll=1")).text(), other = await (await w.fetch("view.js", { method: "POST" })).text();
    check("自检沙箱 · 发往 ntfy 的 POST / PUT 不出手机（原 fetch 0 次），读信箱与别处照常", "POST/PUT 拦 0 次出手机, GET 与别处 2 次", `原 fetch ${w.calls.length} 次：${w.calls.map((c) => c[1] + " " + c[0]).join(" / ")}`,
          post === "{}" && put === "{}" && get === "orig" && other === "orig" && w.calls.length === 2 && w.calls.every((c) => !(c[0].startsWith("https://ntfy.sh/") && /POST|PUT/.test(c[1]))));
    ls.setItem("ark-stock", "B"); ls.setItem("ark-theme", "dark"); ls.setItem("ark-accept", "new");   // what the run leaves behind
    /* a check's iframe (index.html?demo=1&viewdelay=…) inside the run: no restore there, its ntfy writes stay on the phone (simulator 17:38, 3b081a3) */
    const kid = run(ls, "?demo=1&viewdelay=5500", { __acceptDevice: true }), kidPost = await (await kid.fetch("https://ntfy.sh/accept-demo", { method: "POST" })).text();
    check("自检沙箱 · 跑动中的子框架页（检查项 iframe 载 index.html）：不还原、不删备份，发往 ntfy 的写也不出手机", "备份在, ark-stock B, 原 fetch 0 次",
          `${ls.getItem("ark-accept-restore") !== null ? "备份在" : "备份没了"}, ark-stock ${ls.getItem("ark-stock")}, 原 fetch ${kid.calls.length} 次`,
          ls.getItem("ark-accept-restore") !== null && ls.getItem("ark-stock") === "B" && kidPost === "{}" && kid.calls.length === 0 && !kid.__acceptDevice);
    run(ls, "?accept=1");   // the app killed half-way and 运行自检 tapped again: the first backup must survive
    check("自检沙箱 · 没还原又开一次：备份不被跑后的数据盖掉", "ark-stock A", `ark-stock ${JSON.parse(ls.getItem("ark-accept-restore") || "{}")["ark-stock"]}`, JSON.parse(ls.getItem("ark-accept-restore") || "{}")["ark-stock"] === "A");
    run(ls, "");   // 关闭 → the page restarts without ?accept
    const d = ls.dump();
    check("自检沙箱 · 关闭后重开：本机数据原样换回、只多新的 ark-accept、备份键删掉", JSON.stringify({ "ark-accept": "new", "ark-remote-cfg": "{\"topic\":\"T\",\"pin\":\"1\"}", "ark-stock": "A" }), JSON.stringify(d),
          JSON.stringify(d) === JSON.stringify({ "ark-accept": "new", "ark-remote-cfg": "{\"topic\":\"T\",\"pin\":\"1\"}", "ark-stock": "A" }));
    const ls2 = store({ "ark-remote-cfg": "C" }, true), w2 = run(ls2, "?accept=1");
    check("自检沙箱 · 备份写不进：不开跑、提示原因、本机数据没动、回到不带 ?accept 的页面", "不跑, 1 条提示, cfg 在, 回 /maa/",
          `${w2.__acceptDevice ? "跑" : "不跑"}, ${w2.alerts.length} 条提示, ${ls2.getItem("ark-remote-cfg") === "C" ? "cfg 在" : "cfg 没了"}, 回 ${w2.replaced}`,
          w2.__acceptDevice === false && w2.alerts.length === 1 && /自检没有开始/.test(w2.alerts[0]) && ls2.getItem("ark-remote-cfg") === "C" && w2.replaced === "/maa/");
  }
  /* 3. the 运行自检 button follows the 诊断记录 switch */
  const sc = $("#selfcheck"), dsw = $("#diagsw");
  if (!sc || !dsw) check("运行自检钮 / 诊断记录开关在页面里", "有", `${sc ? "钮有" : "钮缺"} ${dsw ? "开关有" : "开关缺"}`, false);
  else {
    const was = dsw.checked, h0 = sc.hidden, href0 = location.href;
    dsw.checked = !was; dsw.dispatchEvent(new Event("change")); const h1 = sc.hidden;
    dsw.checked = was; dsw.dispatchEvent(new Event("change")); const h2 = sc.hidden;
    history.replaceState(null, "", href0);   // the switch rewrites ?diag; the run's own address (?accept=1) stays what the result reports
    check("运行自检钮：诊断记录开着才出现（切开关当场跟着变）", `${was ? "显示" : "隐藏"} → ${was ? "隐藏" : "显示"} → ${was ? "显示" : "隐藏"}`,
          `${h0 ? "隐藏" : "显示"} → ${h1 ? "隐藏" : "显示"} → ${h2 ? "隐藏" : "显示"}`, h0 === !was && h1 === was && h2 === !was);
  }
  /* 4. the sheet: a finished run comes up as 自检结果, a frame record carries the last run */
  const sh = $("#diagsheet");
  if (!sh || typeof showDiagSheet !== "function") { check("诊断记录面板 / showDiagSheet", "有", "缺", false); return; }
  const clip = navigator.clipboard, got = [];
  try { Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (t) => { got.push(t); } } }); } catch (e) {}
  const res = { at: "2026-09-23T00:00:00Z", href: "x?accept=1", viewport: "440×956", standalone: true, dark: false, total: 4, fails: 1,
                rows: [{ item: "a", ok: true }, { item: "b", ok: true }, { item: "c", ok: true }, { item: "坏的一项", expect: "1", got: "2", ok: false }] };
  dispatchEvent(new CustomEvent("arkaccept", { detail: res })); await sleep(50);
  $("#diagsheet-copy").click(); await sleep(50);
  check("自检跑完弹诊断面板：标题「自检结果」、写明通过 3 / 4、复制出整份结果", "自检结果, 通过 3 / 4, 整份",
        `${$("#diagsheet-t").textContent}, ${/通过 3 \/ 4，不通过 1 项/.test($("#diagsheet-m").textContent) ? "通过 3 / 4" : $("#diagsheet-m").textContent}, ${got[0] === JSON.stringify(res) ? "整份" : "不对"}`,
        !sh.hidden && $("#diagsheet-t").textContent === "自检结果" && /通过 3 \/ 4，不通过 1 项/.test($("#diagsheet-m").textContent) && got[0] === JSON.stringify(res));
  sh.hidden = true;   // not 关闭: in a run from the button it restarts the page
  const src0 = lastSelfcheck.src;   // never the real ark-accept key: the runners poll it for the result (light run 17:4x read this 4-row fake as the result)
  lastSelfcheck.src = () => JSON.stringify(res);
  showDiagSheet({ name: "t", frames: [{}, {}] }); $("#diagsheet-copy").click(); await sleep(50);
  let rec = null; try { rec = JSON.parse(got[1] || "null"); } catch (e) {}
  const sc1 = rec && rec.selfcheck;
  check("诊断记录带上这台手机最近一次自检（总数、不通过数、不通过的那几行）", "4 项, 1 不通过, 坏的一项", sc1 ? `${sc1.total} 项, ${sc1.fails} 不通过, ${(sc1.failRows || []).map((r) => r.item).join("/")}` : "缺",
        !!sc1 && sc1.total === 4 && sc1.fails === 1 && sc1.failRows.length === 1 && sc1.failRows[0].item === "坏的一项" && rec.frames.length === 2 && $("#diagsheet-t").textContent === "诊断记录已生成");
  lastSelfcheck.src = () => null; showDiagSheet({ name: "t", frames: [] }); $("#diagsheet-copy").click(); await sleep(50);
  let rec2 = null; try { rec2 = JSON.parse(got[2] || "null"); } catch (e) {}
  check("没跑过自检的手机：诊断记录里 selfcheck = null（写明没跑过，不是漏了）", "null", rec2 ? JSON.stringify(rec2.selfcheck) : "缺", !!rec2 && "selfcheck" in rec2 && rec2.selfcheck === null);
  sh.hidden = true;
  lastSelfcheck.src = src0;
  try { if (clip) Object.defineProperty(navigator, "clipboard", { configurable: true, value: clip }); else delete navigator.clipboard; } catch (e) {}
});
