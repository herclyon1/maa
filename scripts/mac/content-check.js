/* content-check.js (数据 10-01): content assertions for the phone remote page (web/), one per user-reported bug. They read page state and
   call page functions directly — no synthetic taps, no waiting on animations (sleeps of 50 ms at most) — and put back what they changed
   (curQueue, edits, the ark-monthcard localStorage key, the save sheet). Each assertion is caught on its own: a name missing in an old tree is a
   red result with the reason, never a crash of the group.

   Two uses:
   - scripts/mac/content-check.py injects it into headless Chrome through sweep-chrome.py (SWEEP_JS) with its own prelude / epilogue;
   - sweep.js (检查) can call it at the end of MODE=all: `if (window.__contentCheck) R.content = await window.__contentCheck(window.__ccExpect);`

   window.__contentCheck(expect) -> { ms, results: [{ id, pass, got, want, ms }], restored: { ok, changed } }
   expect = { tacet: [[[set1, set2], index], ...] } — built by content-check.py from the current repo's relay/ark_relay/wuwa_tacet.py, never
   from the tree under test (an old tree's schema.js and relay table go stale together).

   view.js / schema.js are classic scripts: curQueue, snap, edits, render, doSave, $, TABS, SCHEMA, TACET, SET_ICONS are global lexical
   bindings, reachable by bare name here, not as window.X — hence the typeof guards. */
window.__contentCheck = async (expect) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const t0 = performance.now(), results = [];
  const has = (names) => names.filter((n) => { try { return (0, eval)(`typeof ${n}`) === "undefined"; } catch { return true; } });
  const run = async (id, fn) => {
    const t = performance.now(); let r;
    try { r = await fn(); } catch (e) { r = { pass: false, got: "threw: " + String(e && (e.stack || e.message) || e).slice(0, 300), want: "" }; }
    results.push({ id, pass: !!r.pass, got: r.got, want: r.want, ms: Math.round(performance.now() - t) });
  };
  /* what the assertions change, read before and after: the run reports whether it all came back */
  const state = () => { const g = (n) => { try { return (0, eval)(n); } catch { return "(missing)"; } };
    let mc = null; try { mc = localStorage.getItem("ark-monthcard"); } catch {}
    const ed = g("edits"), dlg = document.querySelector("#confirm");
    return { curQueue: g("curQueue"), edits: ed && typeof ed === "object" ? Object.keys(ed).length : ed, monthcard: mc, confirmOpen: !!(dlg && dlg.open), go: ((document.querySelector("#go") || {}).textContent || "") }; };
  const s0 = state();

  /* #1 晚班还显示终末地 (fix c8ae5914): in every shift, every tab but 状态 owns a game section of its own (not only the data-tabfix 库存 row),
     and no tab belongs to a game whose owner is not in that shift's 脚本. Same rule as web/accept-tabbar-view.js row ①′ (c8ae5914). */
  await run("#1 shift-tabs", async () => {
    const miss = has(["curQueue", "snap", "render", "SCHEMA"]);
    if (miss.length) return { pass: false, got: "API missing: " + miss.join(", "), want: "curQueue / snap / render / SCHEMA" };
    const qs = (snap && snap.queues) || [];
    if (!qs.length) return { pass: false, got: "snap.queues empty", want: "the demo snapshot's shifts" };
    const tabRules = has(["TABS"]).length ? null : TABS;
    const tabOf = (title) => { const hit = tabRules && tabRules.find(([, re]) => re.test(title)); return hit ? hit[0] : String(title).split(" · ")[0]; };
    const saved = curQueue, per = [];
    try {
      for (const q of qs) {
        curQueue = q["名"]; render(); await sleep(50);
        const nv = document.querySelector("nav.tabs");
        const tabs = nv ? [...nv.querySelectorAll(":scope > .seg > button")].map((b) => b.dataset.tab) : [];
        const orphan = tabs.filter((t) => t !== "状态" && ![...document.querySelectorAll("#app section")].some((x) => x.dataset.tab === t && !x.dataset.tabfix && x.querySelector("h2")));
        const scripts = q["脚本"] || [];
        const inTabs = new Set(SCHEMA.filter((g) => !scripts.length || scripts.includes(g.owner)).map((g) => tabOf(g.title)));
        const outTabs = new Set(SCHEMA.filter((g) => scripts.length && !scripts.includes(g.owner)).map((g) => tabOf(g.title)).filter((t) => !inTabs.has(t)));
        const foreign = tabs.filter((t) => outTabs.has(t));
        per.push({ nm: q["名"], tabs, orphan, foreign, out: [...outTabs] });
      }
    } finally { curQueue = saved; render(); }
    const got = per.map((x) => `${x.nm}: ${x.tabs.join("/") || "(no tab bar)"}${x.orphan.length ? " empty " + x.orphan.join("/") : ""}${x.foreign.length ? " foreign " + x.foreign.join("/") : ""}`).join(" · ");
    const want = per.map((x) => `${x.nm}: no empty tab, none of ${x.out.join("/") || "-"}`).join(" · ");
    return { pass: per.every((x) => x.tabs.length && !x.orphan.length && !x.foreign.length) && per.some((x) => x.out.length), got, want };
  });

  /* #19 登记月卡后「还剩」不当场变 (fix b7e08bae): a registration kept on the phone (monthcard.js LOCAL "ark-monthcard",
     { game: { last, at, sentAt } }) shows on the 状态 page's 月卡 row at once. last = Shanghai today + 40 (not the demo relay's 2026-10-19, so
     entry() keeps the local record); sentAt = now so resend() sends nothing. want is counted here from last, not through MonthCard.entry. */
  await run("#19 monthcard-left", async () => {
    const miss = has(["render"]);
    if (miss.length) return { pass: false, got: "API missing: " + miss.join(", "), want: "render" };
    const KEY = "ark-monthcard", G = "明日方舟", N = 40;
    const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" }).format(new Date());
    const d = new Date(day + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + N); const last = d.toISOString().slice(0, 10);
    const want = Math.round((Date.parse(last + "T00:00:00Z") - Date.parse(day + "T00:00:00Z")) / 864e5);
    const md = `${+last.slice(5, 7)}月${+last.slice(8, 10)}日`;
    let before = null; try { before = localStorage.getItem(KEY); } catch {}
    let txt = "";
    try {
      const o = (() => { try { return JSON.parse(before || "{}") || {}; } catch { return {}; } })();
      o[G] = { last, at: Date.now(), sentAt: Date.now() };
      localStorage.setItem(KEY, JSON.stringify(o));
      render(); await sleep(50);
      const row = document.querySelector(`#app .row.nav[data-page="monthcard"][data-game="${G}"]`);
      txt = row ? (row.querySelector(".mc-sub") || row).textContent.trim() : "(no 月卡 row)";
    } finally {
      try { if (before === null) localStorage.removeItem(KEY); else localStorage.setItem(KEY, before); } catch {}
      render();
    }
    const m = /还剩\s*(\d+)\s*天/.exec(txt);
    return { pass: !!m && +m[1] === want && txt.includes(md), got: `${G}: ${txt}`, want: `${G}: 最后一次领取：${md}（还剩 ${want} 天）` };
  });

  /* #24 声骸选项是旧的 (fixes 6a93a0e8 icons, 05499e9e 3.7 list): schema.js TACET equals the current relay table, set pair and index for
     each entry in order, and SET_ICONS has an icon for every set the table names. */
  await run("#24 tacet", async () => {
    const want = (expect && expect.tacet) || null;
    if (!want || !want.length) return { pass: false, got: "no expectation (window.__ccExpect.tacet)", want: "relay/ark_relay/wuwa_tacet.py TACET" };
    const miss = has(["TACET", "SET_ICONS"]);
    if (miss.length) return { pass: false, got: "API missing: " + miss.join(", "), want: JSON.stringify(want) };
    const page = TACET.map(([names, v]) => [[...names], v]);
    const sets = [...new Set(want.flatMap(([names]) => names))];
    const noIcon = sets.filter((s) => !Object.prototype.hasOwnProperty.call(SET_ICONS, s) || !SET_ICONS[s]);
    const same = JSON.stringify(page) === JSON.stringify(want);
    const fmt = (l) => l.map(([n, v]) => `${v}:${n.join("+")}`).join(" ");
    return { pass: same && !noIcon.length, got: `${fmt(page)}${noIcon.length ? " | no icon: " + noIcon.join("/") : ""}`, want: `${fmt(want)} | icons for all ${sets.length}` };
  });

  /* #25 保存把没保存的开关当跳过寄出 (fix 661a3f89): the save sheet lists a queue skip first, in plain words (.diff.skip
     「今天不跑：早班（09:00）」), the button says 「寄出 N 项」, one line per edit. The skip is put second in edits so the order is tested.
     Edit shapes: view.js queue switch (relay, body.action skip_today, label 「早班 · 09:00」) and note() (label / src / owner / path / from / to).
     Only doSave() runs; #go is never touched. Not covered: the 400 ms guard on #go and the resend path. */
  await run("#25 save-sheet", async () => {
    const miss = has(["edits", "doSave", "render", "$"]);
    if (miss.length) return { pass: false, got: "API missing: " + miss.join(", "), want: "edits / doSave / render / $" };
    const dlg = $("#confirm"), go = $("#go"), list = $("#difflist");
    if (!dlg || !go || !list) return { pass: false, got: "no #confirm / #go / #difflist", want: "the save sheet" };
    const savedEdits = edits, goText = go.textContent, listHtml = list.innerHTML;
    const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" }).format(new Date());
    edits = {
      "mas|MAA|关卡": { label: "明日方舟 · 关卡", src: "mas", owner: "MAA", path: "关卡", from: "1-7", to: "1-8" },
      "relay|queue:早班": { src: "relay", label: "早班 · 09:00", from: true, to: false, body: { action: "skip_today", queue: "早班", day } },
    };
    const n = Object.keys(edits).length;
    let first = null, firstText = "", rows = 0, btn = "", opened = false;
    try {
      await doSave();
      opened = !!dlg.open;
      const items = [...list.querySelectorAll(":scope > .diff")];
      rows = items.length; first = items[0] || null; firstText = first ? first.textContent.trim() : ""; btn = go.textContent.trim();
    } finally {
      try { if (dlg.open) dlg.close(); } catch {}
      edits = savedEdits && typeof savedEdits === "object" ? savedEdits : {};   // doSave() does not touch edits: the page's own (in the demo: none) go back
      go.textContent = goText; list.innerHTML = listHtml;
      render(); try { if (typeof updateBar === "function") updateBar(); } catch {}
    }
    const firstSkip = !!first && first.classList.contains("skip");
    const pass = opened && firstSkip && firstText === "今天不跑：早班（09:00）" && btn === `寄出 ${n} 项` && rows === n;
    return { pass, got: `open ${opened} · rows ${rows} · first ${firstSkip ? ".diff.skip" : ".diff"} 「${firstText.replace(/\s+/g, " ")}」 · #go 「${btn}」`,
      want: `open true · rows ${n} · first .diff.skip 「今天不跑：早班（09:00）」 · #go 「寄出 ${n} 项」` };
  });

  const s1 = state(), changed = Object.keys(s0).filter((k) => JSON.stringify(s0[k]) !== JSON.stringify(s1[k]));
  return { ms: Math.round(performance.now() - t0), results, restored: { ok: !changed.length, changed: changed.map((k) => `${k}: ${JSON.stringify(s0[k])} -> ${JSON.stringify(s1[k])}`) } };
};
