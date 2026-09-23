#!/usr/bin/env python3
"""Make real 诊断记录 samples headless and read them back with diag-frames.py (BOARD DECISIONS D28, WORKLIST P3).

  scripts/mac/diag-sample.py [light|dark] [--web <dir>] [--out <dir>]      (default: light, this checkout's web/, a new temp dir)
  scripts/mac/diag-sample.py --serve [--web <dir>] [--out <dir>]          (only the server: open <base>/diag-sample-init in a real WebKit —
                                                                          the simulator — and touch the page yourself; then diag-frames.py <out>/diag)

What it does, all on this Mac, nothing sent anywhere:
  1. serves <dir> on a free 127.0.0.1 port; the same server takes the recorder's PUT diag/<time>-<id>.json (the diagnostic bucket's
     request, seg-frames-logger.js put() :423) and writes the body to <out>/diag/ — the page is opened with ?diagbucket=<this server>
     (seg-frames-logger.js :411), so no record reaches the real bucket;
  2. headless Chrome, a 440×956 touch screen (Emulation.setTouchEmulationEnabled, Input.dispatchTouchEvent → pointer events with
     pointerType "touch", the way the phone's finger arrives), ?diag=1 (the 诊断记录 switch's path), the fake remote config + snapshot
     accept-run.py uses so the 状态 tab has its two-queue segmented control;
  3. six actions: drag the segmented control 0 → 1 (gesture record), tap the second tab and back (two tab-bar gesture records), tap
     「现在跑一趟」 and the confirm alert's 取消 (two light records; nothing is sent), press 「就是这里」 through window.__diagMark (a mark on the last record), focus a text field (kbd record) when
     the page shows one;
  4. every PUT body is kept as sent; diag-frames.py reads the whole <out>/diag/ and its exit status is this script's check.
Prints one line per record (kind, frames, where the down landed) and exits 1 when an action made no record, a PUT body is not JSON, or
diag-frames.py fails.
"""
import base64, fcntl, http.server, json, os, shutil, signal, socket, struct, subprocess, sys, tempfile, threading, time, urllib.request

CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LOCK = "/tmp/ark-accept-run.lock"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
NOW = int(time.time())
# the same fake config / snapshot as accept-run.py SNAP (two queues → #queueseg on 状态)
SNAP = {"at": NOW - 180, "config": {"MAA": {"关卡": "1-7", "理智药": 0, "作战开关": True, "活动关优先": True, "活动关序号": 1}},
        "run": {"服务": True, "在跑的": []},
        "queues": [{"名": "早班", "脚本": ["MAA", "MaaEnd", "OK-WW"], "定时": True, "时刻": "09:00"}, {"名": "晚班", "脚本": ["MAA"], "定时": True, "时刻": "21:30"}],
        "relay": {"调试模式": "15:50", "刷声骸": {}, "下次别关机": True, "今天跳过": "", "无音区截图": True, "最近指令": [], "周本": {}, "周常": {}},
        "plan": "", "今天": {"跑了": 2, "失败": 0, "最近": "鸣潮"}, "master": {}, "options": {}}


def opt(args, name, default):
    return args[args.index(name) + 1] if name in args else default


def free_port():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


class WS:
    """the minimal CDP socket accept-run.py uses (text frames, client-masked)"""
    def __init__(s, url):
        host, port = url.split("/")[2].split(":")
        path = "/" + "/".join(url.split("/")[3:])
        s.sock = socket.create_connection((host, int(port)))
        key = base64.b64encode(os.urandom(16)).decode()
        s.sock.send(f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += s.sock.recv(4096)
        s.id = 0

    def send(s, method, params=None):
        s.id += 1
        data = json.dumps({"id": s.id, "method": method, "params": params or {}}).encode()
        mask, n = os.urandom(4), len(data)
        hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n))
        s.sock.send(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        s.sock.settimeout(30.0)
        try:
            while True:
                m = s.recv()
                if m.get("id") == s.id:
                    if "error" in m:
                        raise RuntimeError(f"{method}: {m['error']}")
                    return m.get("result", {})
        finally:
            s.sock.settimeout(None)

    def recvn(s, n):
        b = b""
        while len(b) < n:
            c = s.sock.recv(n - len(b))
            if not c:
                raise EOFError
            b += c
        return b

    def recv(s):
        h = s.recvn(2)
        n = h[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", s.recvn(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", s.recvn(8))[0]
        return json.loads(s.recvn(n))

    def js(s, expr):
        r = s.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in r:
            raise RuntimeError(f"page threw: {r['exceptionDetails'].get('text')} {expr[:80]}")
        return r["result"].get("value")


def serve(web, out):
    got = []

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(s, *a, **k):
            super().__init__(*a, directory=web, **k)

        def log_message(s, *a):
            pass

        def handle(s):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError):   # the page dropped a fetch it no longer needed (a reload, a superseded image)
                pass

        def do_GET(s):
            if s.path.startswith("/diag-sample-init"):   # --serve: the same fake config the headless run injects, then the page on ?diag
                base = f"http://{s.headers.get('Host')}"
                page = (f"<!doctype html><meta name=viewport content='width=device-width'><script>{init_js()} "
                        f"location.replace({json.dumps(base + '/index.html?diag=1&diagbucket=' + base)});</script>").encode()
                s.send_response(200); s.send_header("Content-Type", "text/html; charset=utf-8"); s.send_header("Content-Length", str(len(page))); s.end_headers()
                s.wfile.write(page)
                return
            super().do_GET()

        def do_PUT(s):
            body = s.rfile.read(int(s.headers.get("Content-Length") or 0))
            name = os.path.basename(s.path.split("?")[0])
            if not s.path.startswith("/diag/") or not name.endswith(".json"):
                s.send_response(403); s.end_headers(); return
            with open(os.path.join(out, "diag", name), "wb") as fh:
                fh.write(body)
            got.append(name)
            s.send_response(200); s.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, got


def init_js():
    return ('localStorage.setItem("ark-remote-cfg", %s); localStorage.setItem("ark-remote-cfg-snap", %s); localStorage.setItem("ark-remote-tab", "状态");'
            % (json.dumps(json.dumps({"topic": "smoke-test-topic", "pin": "1234"})), json.dumps(json.dumps(SNAP, ensure_ascii=False))))


def wait(cond, secs, what):
    t = time.time() + secs
    while time.time() < t:
        v = cond()
        if v:
            return v
        time.sleep(0.1)
    raise TimeoutError(what)


def touch(ws, kind, x, y):
    pts = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1, "radiusX": 5, "radiusY": 5, "force": 1}]
    ws.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": pts})


def tap(ws, x, y, hold=0.08):
    touch(ws, "touchStart", x, y); time.sleep(hold); touch(ws, "touchEnd", x, y)


def center(ws, sel):
    return ws.js(f"(() => {{ const e = document.querySelector({json.dumps(sel)}); if (!e || !e.offsetParent) return null; const r = e.getBoundingClientRect(); "
                 f"return [r.left + r.width / 2, r.top + r.height / 2]; }})()")


def take_lock():
    """the lock file, held; None when it stayed busy 120 s"""
    # the headless runners' machine lock (accept-run.py LOCK): one headless Chrome per machine at a time, so this run and an accept-run
    # never share the CPU; wait for it like accept-run does
    lockf = open(LOCK, "a+")
    t_lock = time.time()
    while True:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if int(time.time() - t_lock) % 15 == 0:
                lockf.seek(0)
                print(f"waiting for {LOCK} (held by {lockf.read().strip()[:80]}) …", flush=True)
            if time.time() - t_lock > 120:
                print(f"✗ {LOCK} still held after 120 s", flush=True)
                return None
            time.sleep(1)
    lockf.seek(0); lockf.truncate(); lockf.write(f"pid {os.getpid()} {time.strftime('%H:%M:%S')} diag-sample.py\n"); lockf.flush()
    if time.time() - t_lock > 1:
        print(f"waited {time.time() - t_lock:.0f} s for {LOCK}", flush=True)
    return lockf


def summarise(out, got, fails):
    """one line per record, then diag-frames.py over <out>/diag; 1 when anything failed"""
    for n in got:
        try:
            with open(os.path.join(out, "diag", n), encoding="utf-8") as fh:
                r = json.load(fh)
            fr = r.get("frames") or []
            down = next((f for f in fr if f.get("t_since_down", -1) >= 0), None)
            print(f"  {n}: kind {r.get('kind')} · {r.get('name')} · {len(fr)} frames · pointer {len(r.get('pointer') or [])} · marks {len(r.get('marks') or [])}"
                  + (f" · first frame after down {down['frame']} at {down['t_since_down'] * 1000:.0f} ms" if down else ""))
        except (OSError, ValueError) as e:
            fails.append(f"{n}: not JSON ({e})")
    md = os.path.join(out, "frames.md")
    rc = subprocess.run([sys.executable, os.path.join(HERE, "diag-frames.py"), os.path.join(out, "diag"), "--out", md]).returncode
    print(f"diag-frames.py → {md} (exit {rc}); samples in {out}/diag")
    if rc:
        fails.append(f"diag-frames.py exit {rc}")
    for f in fails:
        print("✗ " + f)
    return 1 if fails else 0




def main(argv):
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # a `timeout` still runs the finally below: Chrome and its profile go
    args = argv[1:]
    theme = "dark" if "dark" in args else "light"
    web = os.path.abspath(opt(args, "--web", os.path.join(REPO, "web")))
    out = os.path.abspath(opt(args, "--out", tempfile.mkdtemp(prefix=f"diag-sample-{theme}-")))
    os.makedirs(os.path.join(out, "diag"), exist_ok=True)
    srv, got = serve(web, out)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    if "--serve" in args:   # for a real WebKit (the simulator's Safari / home-screen icon): open <base>/diag-sample-init, touch the page by hand
        print(f"serving {web} · open {base}/diag-sample-init · records land in {out}/diag · pid {os.getpid()}", flush=True)
        try:
            while True:
                time.sleep(3600)
        finally:
            srv.shutdown()
    lockf = take_lock()
    if lockf is None:
        return 1
    port, prof = free_port(), tempfile.mkdtemp(prefix="diag-sample-prof-")
    chrome = subprocess.Popen([CH, "--headless=new", "--hide-scrollbars", f"--remote-debugging-port={port}", f"--user-data-dir={prof}", "--window-size=440,956", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fails = []
    try:
        tgt = wait(lambda: next((t for t in json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2).read()) if t.get("type") == "page"), None)
                   if _up(port) else None, 20, "chrome did not start")
        ws = WS(tgt["webSocketDebuggerUrl"])
        print(f"chrome up (pid {chrome.pid}, port {port})", flush=True)
        ws.send("Page.enable"); ws.send("Runtime.enable")
        ws.send("Emulation.setDeviceMetricsOverride", {"width": 440, "height": 956, "deviceScaleFactor": 3, "mobile": True})
        ws.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        ws.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": theme}]})
        ws.send("Page.addScriptToEvaluateOnNewDocument", {"source": init_js()})
        url = f"{base}/index.html?diag=1&diagbucket={base}" + ("&theme=dark" if theme == "dark" else "")
        ws.send("Page.navigate", {"url": url})
        print(f"navigating {url}", flush=True)
        state = 'JSON.stringify([document.readyState, window.__viewReady === true, typeof window.__segFramesStop])'
        try:
            wait(lambda: ws.js(state) == '["complete",true,"function"]', 30, "")
        except TimeoutError:
            raise TimeoutError(f"page / recorder not ready after 30 s: [readyState, __viewReady, typeof __segFramesStop] = {ws.js(state)}")
        time.sleep(2.0)   # the heartbeat probe's re-render (accept-run.py wait_hb_probe) lands ≤ 1.5 s after load; the snapshot renders from localStorage
        print(f"page {url} · theme {theme} · recorder loaded · bucket stand-in {base}/diag/")

        def act(label, fn):
            n0 = len(got)
            try:
                fn()
                wait(lambda: len(got) > n0, 12, "no PUT")
                print(f"  {label}: record {got[-1]}")
                time.sleep(0.3)
                # a gesture record pops the 诊断记录 sheet over the page (view.js showDiagSheet); its 关闭 does sh.hidden = true — done here in
                # script so the close tap is not itself recorded, and the next action lands on the page, not on the sheet
                ws.js('(() => { const s = document.querySelector("#diagsheet"); if (s && !s.hidden) { s.hidden = true; return true; } return false; })()')
            except (TimeoutError, RuntimeError) as e:
                fails.append(f"{label}: {e}")
                print(f"  ✗ {label}: {e}")

        def seg():
            b = ws.js('(() => { const s = document.querySelector("#queueseg"); if (!s || s.hidden) return null; return [...s.querySelectorAll("button")].map((b) => { const r = b.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }); })()')
            if not b or len(b) < 2:
                raise RuntimeError("no #queueseg with two segments on 状态")
            (x0, y0), (x1, _) = b[0], b[1]
            touch(ws, "touchStart", x0, y0); time.sleep(0.25)
            for i in range(1, 11):
                touch(ws, "touchMove", x0 + (x1 - x0) * i / 10, y0); time.sleep(0.03)
            time.sleep(0.1); touch(ws, "touchEnd", x1, y0)

        def tabs(i):
            def go():
                c = ws.js(f'(() => {{ const b = document.querySelectorAll("nav.tabs button, nav.tabs [data-tab]"); const e = b[{i}]; if (!e) return null; const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()')
                if not c:
                    raise RuntimeError(f"no tab button {i}")
                tap(ws, *c)
            return go

        def tap_sel(sel):
            def go():
                c = center(ws, sel)
                if not c:
                    raise RuntimeError(f"{sel} not visible")
                tap(ws, *c)
            return go

        act("segmented control drag 0 → 1", seg)
        time.sleep(0.5)
        act("tab bar → second tab", tabs(1))
        time.sleep(0.5)
        act("tab bar → back to 状态", tabs(0))
        time.sleep(0.5)
        # 「现在跑一趟」 only opens the confirm alert (dialog#alert); 取消 closes it without sending anything — two light records, the
        # first with the scene change to the alert, the second with the change back
        act("light record: 现在跑一趟 → confirm alert", tap_sel("#runnow"))
        time.sleep(0.5)
        act("light record: alert 取消", tap_sel("#alert-cancel"))
        time.sleep(0.5)
        m = ws.js('typeof window.__diagMark === "function" ? (() => { const m = window.__diagMark("样本标记"); return m ? (m.into || "standalone") : null; })() : "no __diagMark"')
        print(f"  mark 「就是这里」 → {m}")
        if not m or m == "no __diagMark":
            fails.append(f"mark: {m}")
        time.sleep(1.0)
        n0 = len(got)
        has_text = ws.js('(() => { const e = [...document.querySelectorAll("input[type=text], textarea")].find((e) => e.offsetParent); if (!e) return false; const was = document.activeElement === e; if (was) e.blur(); e.focus(); return (e.id || e.tagName) + (was ? " (was focused)" : "") + " active=" + (document.activeElement && (document.activeElement.id || document.activeElement.tagName)) + " hasFocus=" + document.hasFocus() + " dialog=" + !!document.querySelector("dialog[open]"); })()')
        if has_text:
            try:
                wait(lambda: len(got) > n0, 12, "no PUT")
                print(f"  kbd record (focus {has_text}): {got[-1]}")
            except TimeoutError as e:
                fails.append(f"kbd: {e}")
                print(f"  ✗ kbd record (focus {has_text}): {e}")
        else:
            print("  kbd: no visible text field on 状态 (skipped, not a failure)")
        time.sleep(1.0)
        ls = ws.js('localStorage.getItem("ark-segframes")')
        if ls:
            with open(os.path.join(out, "ark-segframes-last.json"), "w", encoding="utf-8") as fh:
                fh.write(ls)
    finally:
        chrome.terminate()
        try:
            chrome.wait(5)
        except subprocess.TimeoutExpired:
            chrome.kill()
        srv.shutdown()
        shutil.rmtree(prof, ignore_errors=True)
        fcntl.flock(lockf, fcntl.LOCK_UN); lockf.close()
    return summarise(out, got, fails)


def _up(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(main(sys.argv))
