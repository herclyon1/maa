/* accept-diagmark.js — the self-check of the phone diagnostics path (BOARD/派单-真机核-界面, D46): 件 A the generic recorder (a record for a
   control that is neither .segctl nor nav.tabs), 件 B the 「就是这里」 mark, 件 C the upload's report. It loads seg-frames-logger.js itself —
   index.html injects that only for ?diag / ?segframes — drives one synthetic list row, and hands the page back through
   window.__segFramesStop() so the rows of any file after this one run on an unwrapped requestAnimationFrame. The phone's own
   localStorage (ark-segframes, ark-diag-queue) is put back the way it was: the user runs this suite on his own phone. */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptDiagmark(ctx) {
    const { check, sleep, settle, at, pev, sec } = ctx;
    if (!sec("diagmark", { layer: "timing" })) return;
    const LS = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
    const put = (k, v) => { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch {} };
    const q0 = LS("ark-diag-queue"), r0 = LS("ark-segframes");

    /* ---- the recorder loads on demand ---- */
    if (!window.__diagMark) {
      await new Promise((res) => { const s = document.createElement("script"); s.src = "seg-frames-logger.js?v=20260923&r=" + Math.random().toString(36).slice(2, 7); s.onload = res; s.onerror = res; document.body.appendChild(s); });
      await settle(() => !!window.__diagMark, 3000);
    }
    check("诊断：记录器加载后标记接口在（window.__diagMark）", "function", typeof window.__diagMark, typeof window.__diagMark === "function");
    check("诊断：验收模式没有「就是这里」钮（只在诊断开关开着时出现）", "无", document.querySelector("#diagmark") ? "有" : "无", !document.querySelector("#diagmark"));
    check("诊断：验收模式帧计数器照旧在（分段逐帧对比不受影响）", "有", document.querySelector("#segframes-counter") ? "有" : "无", !!document.querySelector("#segframes-counter"));

    /* ---- 件 A: a control that is neither the segmented control nor the tab bar ---- */
    const lab = document.createElement("div"); lab.id = "diagprobe";
    lab.style.cssText = "position:fixed;left:20px;top:560px;width:400px;z-index:99;opacity:0";
    lab.innerHTML = '<div class="group"><div class="row nav" id="diagprobe-row"><label>自检行</label><span class="val">值</span></div></div>';
    document.body.appendChild(lab);
    const row = lab.querySelector("#diagprobe-row"), p = at(row);
    let got = null; const onLight = (e) => { got = e.detail; };
    addEventListener("segframes-light", onLight);
    pev(row, "pointerdown", p); await sleep(60);
    if (typeof window.toast === "function") window.toast("诊断自检", 300);          // a visible change during the gesture: the scene must record it
    await sleep(60);
    window.__diagMark("卡住了");                                                     // 件 B without the button
    pev(row, "pointerup", p);
    const waited = await settle(() => !!got, 5000);
    removeEventListener("segframes-light", onLight);
    const r = got || {}, evs = (r.control_events || []).map((e) => e.events);
    check("诊断：点普通控件（列表行）也产出记录", "有记录", got ? "有记录" : `等 ${Math.round(waited)} ms 没有`, !!got);
    check("诊断：记录标成 light（不占分段对比的形状）", "light", r.kind || "无", r.kind === "light");
    check("诊断：记录写明点的是哪个控件", "路径含 diagprobe-row", (r.control && r.control.path) || "无", !!(r.control && r.control.path && r.control.path.indexOf("diagprobe-row") >= 0));
    check("诊断：逐帧有这个控件自己的位置", "≥ 1 帧且首帧有 rect", `${(r.frames || []).length} 帧`, !!(r.frames && r.frames.length && Array.isArray(r.frames[0].rect)));
    check("诊断：手势序列进了记录（按下 + 抬手）", "down,up", (r.pointer || []).map((x) => x.type).join(",") || "无", (r.pointer || []).some((x) => x.type === "down") && (r.pointer || []).some((x) => x.type === "up"));
    check("诊断：可见变化被记下（toast 弹出 = sceneChanged）", "有 sceneChanged", evs.join(",") || "无", evs.indexOf("sceneChanged") >= 0);
    check("诊断：停录原因写进记录", "非空", r.stopped_by || "无", !!r.stopped_by);

    /* ---- 件 B: the mark rides in the same record ---- */
    check("诊断：标记进了同一份记录", "卡住了", (r.marks && r.marks.map((m) => m.word).join(",")) || "无", !!(r.marks && r.marks.some((m) => m.word === "卡住了")));
    check("诊断：标记带着他刚碰的控件", "路径含 diagprobe", (r.marks && r.marks[0] && r.marks[0].control && r.marks[0].control.path) || "无", !!(r.marks && r.marks[0] && r.marks[0].control && r.marks[0].control.path.indexOf("diagprobe") >= 0));

    /* ---- 件 C: the upload always reports, never goes quiet ---- */
    await settle(() => !!(window.__segFrames && window.__segFrames.upload), 3000);
    const up = (window.__segFrames || {}).upload || {};
    check("诊断：上传状态与原因都写进记录（不静默）", "状态 + 原因", `${up.state || "无"} / ${up.detail || "无"}`, (up.state === "kept" || up.state === "sent") && !!up.detail);
    const qn = (() => { try { return JSON.parse(LS("ark-diag-queue") || "[]").length; } catch { return -1; } })();
    check("诊断：没送出去的记录留在手机本地（可补送 / 复制）", up.state === "sent" ? "已送达，本地不留" : "≥ 1 份", `${qn} 份`, up.state === "sent" ? qn >= 0 : qn >= 1);

    /* ---- the next gesture is not blocked by the finished one ---- */
    got = null; addEventListener("segframes-light", onLight);
    pev(row, "pointerdown", p); await sleep(30); pev(row, "pointerup", p);
    await settle(() => !!got, 5000); removeEventListener("segframes-light", onLight);
    check("诊断：一份记录结束后接着能记下一份", "有第二份", got ? "有" : "没有", !!got);

    /* ---- 数据 17:3x, two gaps: a light frame carries the control's background (read, never written), and the alert's cancel fade (.40 s, longer
       than the 300 ms rest) keeps the record open until the alert is really closed ---- */
    check("诊断：轻记录逐帧带控件底色（bg）", "首帧有 bg", String((r.frames || [])[0] && r.frames[0].bg), !!((r.frames || [])[0] && typeof r.frames[0].bg === "string" && r.frames[0].bg));
    const dlg = document.querySelector("dialog#alert"), cancel = document.getElementById("alert-cancel");
    if (typeof window.ask === "function" && dlg && cancel) {
      window.ask("诊断自检", "取消后关窗要进记录");
      await settle(() => dlg.open && dlg.classList.contains("settled"), 3000);
      got = null; addEventListener("segframes-light", onLight);
      const pc = at(cancel); pev(cancel, "pointerdown", pc); await sleep(30); pev(cancel, "pointerup", pc); cancel.click();
      await settle(() => !!got, 5000); removeEventListener("segframes-light", onLight);
      const al = ((got || {}).frames || []).filter((f) => f.scene).map((f) => String(f.scene.alert));
      check("诊断：弹窗点取消 → 淡出与关窗都在同一份记录里（场景 true → closing → false）", "…closing → false", al.join(" → ") || (got ? "无场景帧" : "没有记录"),
        al.indexOf("closing") >= 0 && al[al.length - 1] === "false" && al.lastIndexOf("false") > al.indexOf("closing"));
      await settle(() => !dlg.open, 2000);
    } else check("诊断：弹窗取消自检（页面有 ask() 与 #alert）", "有", "缺", false);

    /* ---- handing the page back ---- */
    const stopOk = typeof window.__segFramesStop === "function" && window.__segFramesStop() === true;
    got = null; addEventListener("segframes-light", onLight);
    pev(row, "pointerdown", p); await sleep(30); pev(row, "pointerup", p);
    await settle(() => !!got, 1200); removeEventListener("segframes-light", onLight);
    check("诊断：收回后不再起录（验收后面的行跑在原样页面上）", "收回且不再记", `${stopOk ? "收回" : "没收回"}，${got ? "仍在记" : "不记了"}`, stopOk && !got);

    lab.remove();
    const ts = document.querySelector("#toast"); if (ts) ts.classList.remove("show");
    put("ark-diag-queue", q0); put("ark-segframes", r0);
  }, { layer: "timing" });
})();
