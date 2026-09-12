// JXA driver for scripts/mac/wecom-trust-ip.sh - runs inside Chrome's
// admin-console tab via "Allow JavaScript from Apple Events".
// Selectors (.js_openapi_block, .app_ipConfig_dialog, .js_ipConfig_textarea,
// .js_ipConfig_confirmBtn) were read off the live console on 2026-09-12.
function run(argv) {
  const ip = argv[0];
  const chrome = Application("Google Chrome");
  chrome.activate();
  const js = (code) => chrome.windows[0].activeTab.execute({ javascript: code });

  // Reuse an admin-console tab if one exists, else open one in the front window.
  let found = false;
  for (const w of chrome.windows()) {
    const tabs = w.tabs();
    for (let i = 0; i < tabs.length; i++) {
      if (tabs[i].url().includes("work.weixin.qq.com/wework_admin")) {
        w.activeTabIndex = i + 1; w.index = 1; found = true; break;
      }
    }
    if (found) break;
  }
  if (!found) {
    chrome.windows[0].tabs.push(new chrome.Tab({ url: "https://work.weixin.qq.com/wework_admin/frame#apps" }));
    delay(4);
  } else {
    js('location.hash = "#apps"; location.reload();');
    delay(4);
  }
  if (js("location.pathname").includes("loginpage")) {
    console.log("✗ 管理后台没登录：Chrome 里现在是扫码页，用手机企业微信扫一次再重跑");
    return 2;
  }
  // Self-built app card → detail page.
  const opened = js('(function(){var el=Array.from(document.querySelectorAll(".js_openapi_block .app_index_item")).find(e=>/Server酱/.test(e.textContent)); if(!el) return "no-card"; el.click(); return "ok";})()');
  if (opened !== "ok") { console.log("✗ 应用列表里找不到自建应用卡片"); return 1; }
  delay(3);
  // Trusted-IP dialog.
  js('(function(){var blk=Array.from(document.querySelectorAll("*")).find(e=>e.children.length>0&&/Trusted IP|可信IP/.test(e.textContent)&&e.textContent.length<600); blk.querySelector("a").click();})()');
  delay(2);
  const before = js('document.querySelector(".app_ipConfig_dialog .js_ipConfig_textarea").value');
  const list = before.split(";").map(s => s.trim()).filter(Boolean);
  console.log("▶ 现有名单：" + list.join(" "));
  if (list.includes(ip)) {
    js('document.querySelector(".app_ipConfig_dialog .ww_dialog_close").click()');
    console.log("✅ " + ip + " 已经在名单里，不用改");
    return 0;
  }
  list.push(ip);
  const value = JSON.stringify(list.join(";"));
  js('(function(){var d=document.querySelector(".app_ipConfig_dialog");var ta=d.querySelector(".js_ipConfig_textarea");ta.focus();ta.value=' + value + ';ta.dispatchEvent(new Event("input",{bubbles:true}));ta.dispatchEvent(new Event("change",{bubbles:true}));d.querySelector(".js_ipConfig_confirmBtn").click();})()');
  delay(3);
  const after = js('(function(){var d=document.querySelector(".app_ipConfig_dialog");if(d&&d.offsetParent){return "ERR:"+(d.querySelector(".js_ipConfig_err_msg").innerText||"dialog still open")}var c=Array.from(document.querySelectorAll("*")).find(e=>/Trusted IP|可信IP/.test(e.textContent)&&e.textContent.length<300);return c?c.innerText.replace(/\\n/g," "):"no-card"})()');
  if (after.startsWith("ERR:")) { console.log("✗ 保存失败：" + after.slice(4)); return 1; }
  console.log("✅ 已保存：" + after);
  return 0;
}
