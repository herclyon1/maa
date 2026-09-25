/* 只为「机器关着也能打开看最后状态」。数据本身走网络，不缓存。 */
const CACHE = "ark-remote-v20260925173618";
/* Everything index.html and manifest.webmanifest load statically (accept.js only rides ?accept), plus what tab-lens.js
   fetches at run time: its lens-filter.svg / lens-field.json and the map images that filter names.
   relay/tests/test_web_shell.py fails when one is missing. */
const SHELL = ["./", "index.html", "tokens.css", "controls.css", "textfit.css", "schema.js", "net.js", "pending.js", "live.js", "stamina.js", "inventory.js", "stockpile.js", "seg-frames-logger.js", "view.js", "alert-prewarm.js", "seg-keys.css", "assets/lens/lens-webgl.js", "assets/lens/lens-engine-fix.js", "assets/lens/lens-supersample.js", "controls.js", "motion.js", "nav.js", "nav-edge.js", "sheet.js", "menu.js", "topbar.js", "refresh.js", "glassbtn.js", "alert-glass.js", "toast-glass.js", "switch.js", "assets/lens/tab-lens.js", "motion.css", "nav.css", "sheet.css", "menu.css", "topbar.css", "refresh.css", "glassbtn.css", "alert-glass.css", "switch.css", "tile.css", "manifest.webmanifest", "icon.svg", "icon-192.png", "icon-512.png", "apple-touch-icon.png",
  // segmented-control lens maps, <feImage href> in index.html
  "assets/lens/seg-f-bg-196.png", "assets/lens/seg-f-bg-198.png", "assets/lens/seg-f-bg-200.png", "assets/lens/seg-f-bg-202.png", "assets/lens/seg-f-bg-204.png", "assets/lens/seg-f-bg-206.png", "assets/lens/seg-f-bg-208.png", "assets/lens/seg-f-bg-210.png", "assets/lens/seg-f-bg-212.png", "assets/lens/seg-f-bg-214.png", "assets/lens/seg-f-bg-216.png", "assets/lens/seg-f-bg-218.png", "assets/lens/seg-f-bg-220.png", "assets/lens/seg-f-bg-222.png", "assets/lens/seg-f-bg-224.png", "assets/lens/seg-f-bg-226.png", "assets/lens/seg-f-bg-228.png", "assets/lens/seg-f-bg-230.png", "assets/lens/seg-f-bg-232.png", "assets/lens/seg-f-bg-234.png", "assets/lens/seg-f-bg-236.png", "assets/lens/seg-f-bg-238.png", "assets/lens/seg-f-bg-240.png", "assets/lens/seg-f-bg-242.png", "assets/lens/seg-f-bg-244.png", "assets/lens/seg-f-bg-246.png", "assets/lens/seg-f-bg-248.png", "assets/lens/seg-f-bg-250.png", "assets/lens/seg-f-bg-252.png", "assets/lens/seg-f-bg-254.png", "assets/lens/seg-f-bg-256.png",
  "assets/lens/seg-f-lab-196.png", "assets/lens/seg-f-lab-198.png", "assets/lens/seg-f-lab-200.png", "assets/lens/seg-f-lab-202.png", "assets/lens/seg-f-lab-204.png", "assets/lens/seg-f-lab-206.png", "assets/lens/seg-f-lab-208.png", "assets/lens/seg-f-lab-210.png", "assets/lens/seg-f-lab-212.png", "assets/lens/seg-f-lab-214.png", "assets/lens/seg-f-lab-216.png", "assets/lens/seg-f-lab-218.png", "assets/lens/seg-f-lab-220.png", "assets/lens/seg-f-lab-222.png", "assets/lens/seg-f-lab-224.png", "assets/lens/seg-f-lab-226.png", "assets/lens/seg-f-lab-228.png", "assets/lens/seg-f-lab-230.png", "assets/lens/seg-f-lab-232.png", "assets/lens/seg-f-lab-234.png", "assets/lens/seg-f-lab-236.png", "assets/lens/seg-f-lab-238.png", "assets/lens/seg-f-lab-240.png", "assets/lens/seg-f-lab-242.png", "assets/lens/seg-f-lab-244.png", "assets/lens/seg-f-lab-246.png", "assets/lens/seg-f-lab-248.png", "assets/lens/seg-f-lab-250.png", "assets/lens/seg-f-lab-252.png", "assets/lens/seg-f-lab-254.png", "assets/lens/seg-f-lab-256.png",
  "assets/lens/seg-f-ab-196.png", "assets/lens/seg-f-ab-198.png", "assets/lens/seg-f-ab-200.png", "assets/lens/seg-f-ab-202.png", "assets/lens/seg-f-ab-204.png", "assets/lens/seg-f-ab-206.png", "assets/lens/seg-f-ab-208.png", "assets/lens/seg-f-ab-210.png", "assets/lens/seg-f-ab-212.png", "assets/lens/seg-f-ab-214.png", "assets/lens/seg-f-ab-216.png", "assets/lens/seg-f-ab-218.png", "assets/lens/seg-f-ab-220.png", "assets/lens/seg-f-ab-222.png", "assets/lens/seg-f-ab-224.png", "assets/lens/seg-f-ab-226.png", "assets/lens/seg-f-ab-228.png", "assets/lens/seg-f-ab-230.png", "assets/lens/seg-f-ab-232.png", "assets/lens/seg-f-ab-234.png", "assets/lens/seg-f-ab-236.png", "assets/lens/seg-f-ab-238.png", "assets/lens/seg-f-ab-240.png", "assets/lens/seg-f-ab-242.png", "assets/lens/seg-f-ab-244.png", "assets/lens/seg-f-ab-246.png", "assets/lens/seg-f-ab-248.png", "assets/lens/seg-f-ab-250.png", "assets/lens/seg-f-ab-252.png", "assets/lens/seg-f-ab-254.png", "assets/lens/seg-f-ab-256.png",
  // tab bar lens (assets/lens/tab-lens.js FAMILY)
  "assets/lens/tab5/lens-filter.svg", "assets/lens/tab5/lens-field.json",
  "assets/lens/tab5/tab-f-bg-82.png", "assets/lens/tab5/tab-f-bg-84.png", "assets/lens/tab5/tab-f-bg-86.png", "assets/lens/tab5/tab-f-bg-88.png", "assets/lens/tab5/tab-f-bg-90.png", "assets/lens/tab5/tab-f-bg-92.png", "assets/lens/tab5/tab-f-bg-94.png", "assets/lens/tab5/tab-f-bg-96.png", "assets/lens/tab5/tab-f-bg-98.png",
  "assets/lens/tab5/tab-f-lab-82.png", "assets/lens/tab5/tab-f-lab-84.png", "assets/lens/tab5/tab-f-lab-86.png", "assets/lens/tab5/tab-f-lab-88.png", "assets/lens/tab5/tab-f-lab-90.png", "assets/lens/tab5/tab-f-lab-92.png", "assets/lens/tab5/tab-f-lab-94.png", "assets/lens/tab5/tab-f-lab-96.png", "assets/lens/tab5/tab-f-lab-98.png",
  "assets/lens/tab5/tab-f-ab-82.png", "assets/lens/tab5/tab-f-ab-84.png", "assets/lens/tab5/tab-f-ab-86.png", "assets/lens/tab5/tab-f-ab-88.png", "assets/lens/tab5/tab-f-ab-90.png", "assets/lens/tab5/tab-f-ab-92.png", "assets/lens/tab5/tab-f-ab-94.png", "assets/lens/tab5/tab-f-ab-96.png", "assets/lens/tab5/tab-f-ab-98.png"];
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) =>
    Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (u.origin !== location.origin) return;          // ntfy 一律走网络
  e.respondWith(fetch(e.request).then((r) => {
    const copy = r.clone();
    caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
    return r;
  }).catch(() => caches.match(e.request)
    // index.html asks for view.js?v=…, SHELL holds view.js: an exact hit first, else the same path without the query
    .then((r) => r || caches.match(e.request, { ignoreSearch: true }))));
});
