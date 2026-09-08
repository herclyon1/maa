// Replacement for the in-game network panel, which mihoyo removed from the floating ball.
//
// Everything here is driven by events, never by a timer:
//   - MutationObserver notices the <video> element appearing
//   - requestVideoFrameCallback fires once per PRESENTED frame; the HUD and the
//     WebRTC getStats() pull both happen inside that callback, so the video stream
//     itself is the clock.
//
// Numbers shown:
//   presented  frames actually painted in the last second (60 Hz display wants 60)
//   dropped    frames the browser decoded but could not paint
//   recv/dec   frames received vs decoded by WebRTC (a gap = decoder falling behind)
//   Mbps       inbound video bitrate
//   rtt        round trip to the game node
//   loss       cumulative packet loss on the video track
// A rolling copy is written to localStorage.__cgStats so it can be read afterwards.
(function () {
  'use strict';
  if (window.__cgStats) return;
  window.__cgStats = true;

  var pc = null;
  var RealPC = window.RTCPeerConnection;
  if (RealPC) {
    var Patched = function () {
      var o = new RealPC(...arguments);
      pc = o;
      return o;
    };
    Patched.prototype = RealPC.prototype;
    Object.setPrototypeOf(Patched, RealPC);
    window.RTCPeerConnection = Patched;
  }

  var hud = null;
  function ensureHud() {
    if (hud) return hud;
    hud = document.createElement('div');
    hud.style.cssText = [
      'position:fixed', 'top:6px', 'left:6px', 'z-index:2147483647',
      'font:11px/1.45 ui-monospace,Menlo,monospace', 'color:#9ef',
      'background:rgba(0,0,0,.55)', 'padding:4px 7px', 'border-radius:5px',
      'white-space:pre', 'pointer-events:none', 'text-shadow:0 1px 2px #000'
    ].join(';');
    document.documentElement.appendChild(hud);
    return hud;
  }

  var win = [];            // presentation timestamps of the last second
  var lastQuality = null;  // previous getVideoPlaybackQuality snapshot
  var lastRtc = null;      // previous inbound-rtp snapshot
  var pending = false;

  function pullRtc(cb) {
    if (!pc || pending) return cb(null);
    pending = true;
    pc.getStats(null).then(function (report) {
      pending = false;
      var v = null;
      report.forEach(function (s) {
        if (s.type === 'inbound-rtp' && s.kind === 'video') v = s;
      });
      var rtt = null;
      report.forEach(function (s) {
        if (s.type === 'candidate-pair' && s.state === 'succeeded' && s.currentRoundTripTime != null) {
          rtt = Math.round(s.currentRoundTripTime * 1000);
        }
      });
      cb(v ? { v: v, rtt: rtt } : null);
    }).catch(function () { pending = false; cb(null); });
  }

  function attach(video) {
    if (video.__cgHooked || !video.requestVideoFrameCallback) return;
    video.__cgHooked = true;

    var frames = 0;
    var text = '';

    function onFrame(now, meta) {
      video.requestVideoFrameCallback(onFrame);
      win.push(now);
      while (win.length && now - win[0] > 1000) win.shift();
      frames++;
      if (frames % 60) return;

      var q = video.getVideoPlaybackQuality ? video.getVideoPlaybackQuality() : null;
      var droppedNow = 0;
      if (q) {
        if (lastQuality) droppedNow = q.droppedVideoFrames - lastQuality.droppedVideoFrames;
        lastQuality = { droppedVideoFrames: q.droppedVideoFrames, totalVideoFrames: q.totalVideoFrames };
      }

      pullRtc(function (r) {
        var line = '显示 ' + win.length + ' fps  丢帧 ' + droppedNow;
        var rec = { t: Date.now(), presented: win.length, droppedNow: droppedNow };
        if (r) {
          var v = r.v, mbps = null, decFps = v.framesPerSecond;
          if (lastRtc && v.timestamp > lastRtc.timestamp) {
            mbps = (v.bytesReceived - lastRtc.bytesReceived) * 8 / (v.timestamp - lastRtc.timestamp) / 1000;
          }
          lastRtc = { timestamp: v.timestamp, bytesReceived: v.bytesReceived };
          line += '\n收帧 ' + (decFps != null ? decFps : '-') + '  解码丢 ' + (v.framesDropped || 0);
          line += '\n码率 ' + (mbps != null ? mbps.toFixed(1) : '-') + ' Mbps';
          line += '\n延迟 ' + (r.rtt != null ? r.rtt : '-') + ' ms  丢包 ' + (v.packetsLost || 0);
          if (v.freezeCount != null) line += '\n卡顿 ' + v.freezeCount + ' 次 ' + (v.totalFreezesDuration || 0).toFixed(1) + 's';
          rec.decodeFps = decFps;
          rec.framesDropped = v.framesDropped;
          rec.mbps = mbps != null ? +mbps.toFixed(2) : null;
          rec.rtt = r.rtt;
          rec.packetsLost = v.packetsLost;
          rec.freezeCount = v.freezeCount;
          rec.totalFreezesDuration = v.totalFreezesDuration;
        }
        line += '\n视频 ' + video.videoWidth + 'x' + video.videoHeight;
        rec.w = video.videoWidth; rec.h = video.videoHeight;
        if (line !== text) { ensureHud().textContent = text = line; }
        try {
          var a = JSON.parse(localStorage.getItem('__cgStatsLog') || '[]');
          a.push(rec);
          localStorage.setItem('__cgStatsLog', JSON.stringify(a.slice(-600)));
        } catch (e) {}
      });
    }
    video.requestVideoFrameCallback(onFrame);
  }

  function scan(root) {
    if (!root || root.nodeType !== 1) return;
    if (root.tagName === 'VIDEO') attach(root);
    var vs = root.querySelectorAll ? root.querySelectorAll('video') : [];
    for (var i = 0; i < vs.length; i++) attach(vs[i]);
  }

  new MutationObserver(function (muts) {
    for (var i = 0; i < muts.length; i++) {
      for (var j = 0; j < muts[i].addedNodes.length; j++) scan(muts[i].addedNodes[j]);
    }
  }).observe(document.documentElement, { childList: true, subtree: true });

  scan(document.documentElement);
})();
