#!/usr/bin/env python3
"""Where every control of the remote page sits on the simulator screen, in simulator points, without reading a screenshot (数据-串7).

  scripts/mac/sim-coords.py inject <staged-web-dir> [--rx <port>] [--out <dir>]
      Method A — the page reports itself. Only for a self-check copy (webclip-serve.sh's scratch dir, never the repo's web/): writes
      <dir>/__coords.js and one <script> line into <dir>/index.html, then runs a receiver on 127.0.0.1:<rx> (default 9341, 数据's
      second port, BOARD A21). The page posts a table 1.5 s after load and 0.7 s after every finger-up, plus where each finger-down
      landed (clientX/Y and the control under it) — that is the hit check. Each report → <out>/NNN-<why>.json and <out>/latest.md.
  scripts/mac/sim-coords.py rwi [arm|taps|--js <expr>] [--udid <UDID>] [--match <url part>] [--out <file>]
      Method B — Web Inspector's remote protocol. Connects to the simulator's webinspectord_sim socket (the one Safari's Develop menu
      uses; always on for simulators, webkit.org/web-inspector/enabling-web-inspector/), picks the page whose URL contains --match
      (default localhost:9320 — the dd25 home-screen clip), evaluates the same collector with Runtime.evaluate and prints the table.
      Nothing is injected; the page is not reloaded.

Coordinates: point = (client + offset) × visualViewport.scale. The offset is 0 for a home-screen (standalone) window with
viewport-fit=cover, whose CSS viewport covers the screen from its top-left (the page reports innerWidth/innerHeight against
screen.width/height; a mismatch is printed and the column is marked). A row is a visible, on-screen button / a[href] / input / select /
textarea / summary / [role=button|tab|switch|link|menuitem*] / [onclick] / [tabindex≥0]; the tap point is the centre of its on-screen
part, and 「中心命中」 says whether document.elementFromPoint there is that control (something covering it → no).

Protocol (undocumented by Apple; framing and selectors as google/ios-webkit-debug-proxy src/rpc.c, src/webinspector.c; keys as WebKit
Source/JavaScriptCore/inspector/remote/RemoteInspectorConstants.h): 4-byte big-endian length + binary plist
{__selector, __argument}; the simulator socket takes the plist bare (no WIRFinalMessageKey wrapper, webinspector.c is_sim).
"""
import http.server, json, os, plistlib, re, socket, struct, subprocess, sys, threading, time, uuid

UDID_A = "8E793B8A-922B-46BC-86E2-E0F2BE845CA5"

COLLECT = r"""(function (why) {
  var SEL = 'button,a[href],input,select,textarea,summary,[role=button],[role=tab],[role=switch],[role=link],[role^=menuitem],[onclick],[tabindex]:not([tabindex="-1"])';
  var vv = window.visualViewport, sc = vv ? vv.scale : 1, ox = vv ? vv.offsetLeft : 0, oy = vv ? vv.offsetTop : 0;
  var W = innerWidth, H = innerHeight;
  function txt(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
  function name(el) {
    var a = el.getAttribute('aria-label'); if (a) return txt(a);
    if (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') {
      var row = el.closest('.cell,.row,li,label') || el.parentElement.parentElement;
      var t = row ? txt(row.innerText).split(' ')[0] : '';
      return (t || el.id || el.name || el.type) + ' [' + (el.type || el.tagName.toLowerCase()) + (el.type === 'checkbox' ? (el.checked ? ' 开' : ' 关') : '') + ']';
    }
    return txt(el.innerText).slice(0, 30) || el.title || el.id || el.className || el.tagName.toLowerCase();
  }
  function desc(el) { return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/).join('.') : ''); }
  var els = Array.prototype.filter.call(document.querySelectorAll(SEL), function (el) {
    var r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1) return false;
    var cs = getComputedStyle(el); if (cs.visibility !== 'visible' || cs.display === 'none') return false;
    if (el.closest('[hidden],[inert],[aria-hidden=true]')) return false;
    return Math.min(r.right, W) - Math.max(r.left, 0) >= 1 && Math.min(r.bottom, H) - Math.max(r.top, 0) >= 1;
  });
  // one row per control: an ancestor with (nearly) the same box as a listed descendant is dropped, the innermost stays
  els = els.filter(function (el) { var r = el.getBoundingClientRect();
    return !els.some(function (d) { if (d === el || !el.contains(d)) return false; var q = d.getBoundingClientRect();
      return Math.abs(q.left - r.left) < 2 && Math.abs(q.top - r.top) < 2 && Math.abs(q.width - r.width) < 2 && Math.abs(q.height - r.height) < 2; }); });
  var rows = els.map(function (el) {
    var r = el.getBoundingClientRect();
    var x0 = Math.max(r.left, 0), y0 = Math.max(r.top, 0), x1 = Math.min(r.right, W), y1 = Math.min(r.bottom, H);
    var cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, hit = document.elementFromPoint(cx, cy);
    var sw = el.closest('.sw');
    return { name: name(el), x: Math.round((cx + ox) * sc), y: Math.round((cy + oy) * sc), w: Math.round(r.width * sc), h: Math.round(r.height * sc),
             el: desc(el), hit: !!hit && (hit === el || el.contains(hit) || (!!sw && sw.contains(hit))), hitEl: hit ? desc(hit) : null };
  });
  return JSON.stringify({ why: why, at: Date.now(), url: location.href, title: document.title,
    meta: { innerW: W, innerH: H, screenW: screen.width, screenH: screen.height, dpr: devicePixelRatio, scale: sc,
            standalone: !!navigator.standalone || matchMedia('(display-mode: standalone)').matches, scrollY: Math.round(scrollY),
            tab: (document.querySelector('#tabs [aria-selected=true], #tabs .on') || {}).innerText || null },
    rows: rows });
})"""

PROBE = r"""(function () {
  var RX = %s, collect = %s, taps = [], seq = 0;
  function post(why) { try { var body = JSON.parse(collect(why)); body.seq = ++seq; body.taps = taps.splice(0);
    fetch(RX, { method: 'POST', mode: 'no-cors', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify(body) }); } catch (e) {} }
  addEventListener('pointerdown', function (e) {
    var c = e.target.closest ? e.target.closest('button,a[href],input,select,textarea,summary,[role],[onclick],[tabindex]') : null;
    taps.push({ at: Date.now(), cx: Math.round(e.clientX * 10) / 10, cy: Math.round(e.clientY * 10) / 10, type: e.pointerType,
                target: e.target.tagName.toLowerCase() + (e.target.id ? '#' + e.target.id : ''), control: c ? (c.getAttribute('aria-label') || (c.innerText || '').trim().slice(0, 30) || c.id || c.tagName.toLowerCase()) : null });
  }, true);
  var t = 0;
  addEventListener('pointerup', function () { clearTimeout(t); t = setTimeout(function () { post('tap'); }, 700); }, true);
  addEventListener('load', function () { setTimeout(function () { post('load'); }, 1500); });
})();
"""


# the hit check without injecting anything: `rwi arm` leaves a capture pointerdown listener in the page, `rwi taps` reads and clears
# what it caught (client point, the element, the control around it) — a tap sent at a table's (x, y) must come back as that control
ARM = r"""(function () { if (window.__simTaps) return 'armed already'; window.__simTaps = [];
  addEventListener('pointerdown', function (e) { var c = e.target.closest ? e.target.closest('button,a[href],input,select,textarea,summary,[role],[onclick],[tabindex]') : null;
    window.__simTaps.push({ cx: Math.round(e.clientX * 10) / 10, cy: Math.round(e.clientY * 10) / 10, type: e.pointerType, target: e.target.tagName.toLowerCase() + (e.target.id ? '#' + e.target.id : ''),
      control: c ? (c.getAttribute('aria-label') || (c.innerText || '').trim().slice(0, 30) || c.id || c.tagName.toLowerCase()) : null }); }, true);
  return 'armed'; })()"""
TAPS = "JSON.stringify((window.__simTaps || []).splice(0))"


def table(rep):
    m = rep["meta"]
    off = "0" if (m["innerW"], m["innerH"]) == (m["screenW"], m["screenH"]) else f"未知（视口 {m['innerW']}×{m['innerH']} ≠ 屏 {m['screenW']}×{m['screenH']}）"
    out = [f"<!-- {rep['why']} · {time.strftime('%H:%M:%S', time.localtime(rep['at'] / 1000))} · {rep['url']} · 标签 {m['tab']} · 滚动 {m['scrollY']} · "
           f"主屏窗口 {m['standalone']} · 缩放 {m['scale']} · 偏移 {off} -->",
           "| 项 | 动作 | 坐标 | 说明 |", "|---|---|---|---|"]
    for r in rep["rows"]:
        out.append(f"| {r['name'].replace('|', '/')} | tap | ({r['x']},{r['y']}) | {r['el']} {r['w']}×{r['h']}"
                   + ("" if r["hit"] else f" · 中心被 {r['hitEl']} 盖住") + " |")
    for t in rep.get("taps", []):
        out.append(f"<!-- 按下 client ({t['cx']},{t['cy']}) {t['type']} → {t['target']} · 控件 {t['control']} -->")
    return "\n".join(out)


def inject(argv):
    d = argv[0]
    rx = int(opt(argv, "--rx", "9341"))
    out = opt(argv, "--out", os.path.join(d, "..", "coords-out"))
    os.makedirs(out, exist_ok=True)
    idx = os.path.join(d, "index.html")
    html = open(idx, encoding="utf-8").read()
    if "__coords.js" not in html:
        if "</body>" not in html:
            sys.exit("index.html has no </body>")
        html = html.replace("</body>", '<script src="__coords.js"></script>\n</body>', 1)
        open(idx, "w", encoding="utf-8").write(html)
    open(os.path.join(d, "__coords.js"), "w", encoding="utf-8").write(PROBE % (json.dumps(f"http://127.0.0.1:{rx}/coords"), COLLECT))
    n = [len([f for f in os.listdir(out) if f.endswith(".json")])]

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(s, *a):
            pass

        def do_POST(s):
            body = s.rfile.read(int(s.headers.get("Content-Length") or 0))
            s.send_response(204); s.send_header("Access-Control-Allow-Origin", "*"); s.end_headers()
            rep = json.loads(body)
            n[0] += 1
            got = time.time()
            json.dump(rep, open(os.path.join(out, f"{n[0]:03d}-{rep['why']}.json"), "w"), ensure_ascii=False, indent=1)
            md = table(rep)
            open(os.path.join(out, "latest.md"), "w", encoding="utf-8").write(md + "\n")
            taps = "; ".join(f"({t['cx']},{t['cy']})→{t['control']}" for t in rep.get("taps", []))
            print(f"{time.strftime('%H:%M:%S')}.{int(got % 1 * 1000):03d} #{n[0]} {rep['why']} rows {len(rep['rows'])} tab {rep['meta']['tab']}"
                  + (f" · down {taps}" if taps else ""), flush=True)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", rx), H)
    print(f"injected {idx} · receiver 127.0.0.1:{rx} · reports → {os.path.abspath(out)} · pid {os.getpid()}", flush=True)
    srv.serve_forever()


# ---- method B: Web Inspector remote protocol over the simulator's webinspectord_sim socket ----

def sim_socket(udid):
    ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    pid = next((l.split()[0] for l in ps.splitlines() if "launchd_sim" in l and udid in l), None)
    if not pid:
        sys.exit(f"simulator {udid} is not booted (no launchd_sim)")
    ls = subprocess.run(["lsof", "-a", "-p", pid, "-U", "-Fn"], capture_output=True, text=True).stdout
    path = next((l[1:] for l in ls.splitlines() if l.endswith("com.apple.webinspectord_sim.socket")), None)
    if not path:
        sys.exit(f"launchd_sim {pid} holds no webinspectord_sim socket")
    return path


class RWI:
    def __init__(s, path):
        s.sock = socket.socket(socket.AF_UNIX); s.sock.connect(path); s.sock.settimeout(0.2)
        s.conn, s.buf = str(uuid.uuid4()).upper(), b""

    def send(s, sel, arg):
        arg = dict(arg, WIRConnectionIdentifierKey=s.conn)
        b = plistlib.dumps({"__selector": sel, "__argument": arg}, fmt=plistlib.FMT_BINARY)
        s.sock.sendall(struct.pack(">I", len(b)) + b)

    def until(s, pred, secs):
        end = time.time() + secs
        while time.time() < end:
            while len(s.buf) >= 4 and len(s.buf) >= 4 + struct.unpack(">I", s.buf[:4])[0]:
                n = struct.unpack(">I", s.buf[:4])[0]
                m = plistlib.loads(s.buf[4:4 + n]); s.buf = s.buf[4 + n:]
                v = pred(m)
                if v is not None:
                    return v
            try:
                d = s.sock.recv(1 << 20)
            except socket.timeout:
                continue
            if not d:
                break
            s.buf += d
        return None


def rwi(argv):
    t0 = time.time()
    udid, match = opt(argv, "--udid", UDID_A), opt(argv, "--match", "localhost:9320")
    c = RWI(sim_socket(udid))
    c.send("_rpc_reportIdentifier:", {})
    c.send("_rpc_getConnectedApplications:", {})
    apps = {}

    def app_list(m):
        a = m["__argument"].get("WIRApplicationDictionaryKey")
        if m["__selector"] == "_rpc_reportConnectedApplicationList:" and a is not None:
            apps.update(a); return True
    c.until(app_list, 12)   # webinspectord is socket-activated; after an idle exit launchd respawns it with a throttle (18:24 measured: "spawn scheduled", answer after ~10 s)
    pages = []
    for k in apps:
        c.send("_rpc_forwardGetListing:", {"WIRApplicationIdentifierKey": k})

    def listing(m):   # listings also come unsolicited from apps that connect later (a home-screen clip's web content process
        a = m["__argument"]   # reports under its own PID, not Web.app's — 18:24 on simulator A: app PID:46500, page from PID:10514)
        if m["__selector"] == "_rpc_applicationConnected:":
            apps[a["WIRApplicationIdentifierKey"]] = a
            c.send("_rpc_forwardGetListing:", {"WIRApplicationIdentifierKey": a["WIRApplicationIdentifierKey"]})
        if m["__selector"] == "_rpc_applicationSentListing:":
            for p in a.get("WIRListingKey", {}).values():
                pages.append((a["WIRApplicationIdentifierKey"], p))
                if match in (p.get("WIRURLKey") or ""):
                    return a["WIRApplicationIdentifierKey"], p
    hit = c.until(listing, 5)
    if not hit:
        sys.exit("no inspectable page matches %r; pages: %s" % (match, [(a, p.get("WIRURLKey")) for a, p in pages]))
    app, page = hit
    pid, sender = page["WIRPageIdentifierKey"], str(uuid.uuid4()).upper()
    base = {"WIRApplicationIdentifierKey": app, "WIRPageIdentifierKey": pid, "WIRSenderKey": sender}
    c.send("_rpc_forwardSocketSetup:", dict(base, WIRAutomaticallyPause=False))

    def data(m):
        if m["__selector"] == "_rpc_applicationSentData:":
            return json.loads(m["__argument"]["WIRMessageDataKey"])
    target = None
    msg = c.until(data, 3)
    while msg is not None and target is None:
        if msg.get("method") == "Target.targetCreated":
            target = msg["params"]["targetInfo"]["targetId"]
        else:
            msg = c.until(data, 2)
    mode = next((a for a in argv if a in ("arm", "taps")), "js" if "--js" in argv else "table")
    expr = {"table": f"{COLLECT}('rwi')", "arm": ARM, "taps": TAPS, "js": opt(argv, "--js", "")}[mode]
    inner = {"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr, "returnByValue": True}}
    outer = ({"id": 1001, "method": "Target.sendMessageToTarget", "params": {"targetId": target, "message": json.dumps(inner)}}
             if target else inner)   # older WebKit: no Target domain, the page answers directly
    t1 = time.time()
    c.send("_rpc_forwardSocketData:", dict(base, WIRSocketDataKey=json.dumps(outer).encode()))

    def answer(m):
        d = data(m)
        if d is None:
            return None
        if d.get("method") == "Target.dispatchMessageFromTarget":
            d = json.loads(d["params"]["message"])
        if d.get("id") == 1 and "result" in d:
            return d
    res = c.until(answer, 5)
    c.send("_rpc_forwardDidClose:", base)
    t2 = time.time()
    if res is None or "wasThrown" in res["result"] and res["result"]["wasThrown"]:
        sys.exit(f"no answer / threw: {res}")
    if mode != "table":
        print(res["result"]["result"].get("value"), f"· total {t2 - t0:.2f} s")
        return
    rep = json.loads(res["result"]["result"]["value"])
    md = table(rep)
    if opt(argv, "--out", None):
        open(opt(argv, "--out", None), "w", encoding="utf-8").write(md + "\n")
    print(md)
    print(f"<!-- app {app} {apps.get(app, {}).get('WIRApplicationBundleIdentifierKey')} page {pid} target {target} · connect+list {t1 - t0:.2f} s · evaluate {t2 - t1:.2f} s · total {t2 - t0:.2f} s -->")


def opt(args, name, default):
    return args[args.index(name) + 1] if name in args else default


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("inject", "rwi"):
        sys.exit(__doc__)
    {"inject": inject, "rwi": rwi}[sys.argv[1]](sys.argv[2:])
