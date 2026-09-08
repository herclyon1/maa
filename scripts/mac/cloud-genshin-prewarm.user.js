// ==UserScript==
// @name         Cloud Genshin ping prewarm
// @namespace    herclyon
// @version      1.0
// @description  Keep WebSocket connections to the cloud-game ping servers open so the SDK's 1-second latency test completes over a high-RTT tunnel (WARP). Reports the real echo RTT; nothing is faked.
// @match        https://ys.mihoyo.com/cloud/*
// @run-at       document-start
// @grant        none
// ==/UserScript==

// Why this exists (2026-09-09):
//   cg-sdk 6.1.0.62 calls testRttMs(20, 1000) per ping server: within 1000 ms it must finish
//   TCP + TLS + WebSocket handshakes AND receive 20 echoes, i.e. ~4 RTT < 1 s => RTT < ~230 ms.
//   Through Cloudflare WARP the RTT to mainland China is ~270 ms, so every server times out,
//   ping_results is sent empty, and getNodesInfo answers -110013 "网络连接失败".
//   The server itself accepts any RTT (a 1005 ms result was dispatched fine).
// What it does:
//   Opens the ping-server WebSockets ahead of time and hands the SDK a thin wrapper that reuses
//   them, so the 1 s window only has to cover the 20 echoes (~300 ms).
(function () {
  'use strict';
  if (window.__cgPrewarm) return;
  window.__cgPrewarm = true;

  var Real = window.WebSocket;
  var RE = /-wssping\.mhystatic\.com\/wsspingsvr\/echo/;
  var KEY = '__cgPingHosts';
  var DEFAULT_HOSTS = [
    'cg-t-mhyfs1', 'cg-t-mhywh1', 'cg-t-mhytj1', 'cg-t-mhycs1', 'cg-t-mhycd1',
    'cg-t-mhyjx1', 'cg-t-ensdg17', 'yys-t-ensdg13', 'cg-t-mhyly1'
  ].map(function (h) { return 'wss://' + h + '-wssping.mhystatic.com/wsspingsvr/echo'; });

  var pool = {};
  window.__cgPool = pool;

  function loadHosts() {
    try { var a = JSON.parse(localStorage.getItem(KEY) || '[]'); if (a.length) return a; } catch (e) {}
    return DEFAULT_HOSTS;
  }
  function saveHosts(urls) {
    try { localStorage.setItem(KEY, JSON.stringify(urls)); } catch (e) {}
  }

  // One real socket per URL. Reopened on close (event-driven, no timers).
  function ensure(url) {
    var p = pool[url];
    if (p && (p.ws.readyState === 0 || p.ws.readyState === 1)) return p;
    p = { ws: null, active: null, q: [] };
    pool[url] = p;
    var w = new Real(url);
    p.ws = w;
    w.onopen = function () { p.q.splice(0).forEach(function (d) { w.send(d); }); };
    w.onmessage = function (ev) {
      if (p.active && p.active.readyState === 1) p.active._fire('message', { data: ev.data });
    };
    w.onclose = function () { if (pool[url] === p) pool[url] = null; };
    w.onerror = function () {};
    return p;
  }

  // Minimal WebSocket look-alike the SDK talks to; traffic goes over the pooled socket.
  function Pooled(url) {
    this.url = url; this.readyState = 0; this._l = {}; this.binaryType = 'blob';
    var self = this, p = ensure(url); p.active = self;
    Promise.resolve().then(function () {
      if (self.readyState === 0) { self.readyState = 1; self._fire('open', {}); }
    });
  }
  Pooled.prototype.addEventListener = function (t, f) { (this._l[t] = this._l[t] || []).push(f); };
  Pooled.prototype.removeEventListener = function (t, f) { this._l[t] = (this._l[t] || []).filter(function (x) { return x !== f; }); };
  Pooled.prototype._fire = function (t, ev) {
    (this._l[t] || []).forEach(function (f) { try { f(ev); } catch (e) {} });
    var h = this['on' + t]; if (h) { try { h(ev); } catch (e) {} }
  };
  Pooled.prototype.send = function (d) {
    var p = ensure(this.url); p.active = this;
    if (p.ws.readyState === 1) p.ws.send(d); else p.q.push(d);
  };
  Pooled.prototype.close = function () {
    if (this.readyState === 3) return;
    this.readyState = 3;
    var p = pool[this.url]; if (p && p.active === this) p.active = null;
    var self = this; Promise.resolve().then(function () { self._fire('close', { code: 1000 }); });
  };
  Pooled.CONNECTING = 0; Pooled.OPEN = 1; Pooled.CLOSING = 2; Pooled.CLOSED = 3;

  var Patched = function (url, proto) {
    if (RE.test(String(url))) return new Pooled(String(url));
    return proto ? new Real(url, proto) : new Real(url);
  };
  Patched.prototype = Real.prototype;
  Patched.CONNECTING = 0; Patched.OPEN = 1; Patched.CLOSING = 2; Patched.CLOSED = 3;
  window.WebSocket = Patched;

  // Learn the current server list from listPingServer so new hosts are warm next time.
  var origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, u) {
    if (/dispatcher\/api\/listPingServer/.test(String(u))) {
      this.addEventListener('loadend', function () {
        try {
          var d = JSON.parse(this.responseText);
          var urls = (d.data && d.data.ping_svr || []).map(function (s) { return s.wss_url; }).filter(Boolean);
          if (urls.length) { saveHosts(urls); urls.forEach(ensure); }
        } catch (e) {}
      });
    }
    return origOpen.apply(this, arguments);
  };

  loadHosts().forEach(ensure);
})();
