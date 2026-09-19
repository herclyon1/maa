# -*- coding: utf-8 -*-
"""Run web/accept.js in headless Chrome (desktop Chromium: no safe area) with a fake snapshot.
usage: accept-run.py <url-without-query> [dark] [nodata]  → prints the ark-accept rows
Order of events (监督局 2026-09-19 18:3x: no more "no result / first-run retry"):
  1. the page is opened with ?accept=1&quiet=1; window.__acceptHold = true is set before any page script, so accept.js
     (which also waits for window.__viewReady) does not start measuring yet;
  2. the runner waits up to 60 s for document.readyState === "complete" and window.__viewReady === true (set at the end
     of view.js — the inline loader in index.html can deliver view.js late);
  3. the stamina data is injected, render() / updateLive() run, the hold is released;
  4. the runner waits up to 60 s for accept.js's result (localStorage ark-accept).
  2b. before the hold is released the runner checks that every <script src> of the document appears in the resource-timing
     entries and that no exception was thrown so far; otherwise it reloads the page once and waits again (2026-09-19 18:41,
     first run of this runner: headless Chrome never requested pending.js?v=… — server log — and render() threw
     "reconcilePending is not defined"; the second run was clean. A lost script fetch is detected here, not retried by hand).
Any JS exception seen on the way is printed; exit 1 when a step does not complete."""
import socket, os, base64, json, struct, sys, subprocess, time, urllib.request, tempfile, shutil, random
CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
class WS:
    def __init__(s, url):
        host, port = url.split('/')[2].split(':'); path = '/' + '/'.join(url.split('/')[3:])
        s.sock = socket.create_connection((host, int(port))); key = base64.b64encode(os.urandom(16)).decode()
        s.sock.send(f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        buf = b''
        while b'\r\n\r\n' not in buf: buf += s.sock.recv(4096)
        s.id = 0; s.events = []
    def send(s, method, params=None):
        s.id += 1; data = json.dumps({'id': s.id, 'method': method, 'params': params or {}}).encode(); mask = os.urandom(4); L = len(data)
        hdr = bytes([0x81]) + (bytes([0x80 | L]) if L < 126 else bytes([0x80 | 126]) + struct.pack('>H', L) if L < 65536 else bytes([0x80 | 127]) + struct.pack('>Q', L))
        s.sock.send(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        while True:
            m = s.recv()
            if m.get('id') == s.id: return m
            s.events.append(m)
    def recvn(s, n):
        b = b''
        while len(b) < n:
            c = s.sock.recv(n - len(b))
            if not c: raise EOFError
            b += c
        return b
    def recv(s):
        h = s.recvn(2); L = h[1] & 0x7f
        if L == 126: L = struct.unpack('>H', s.recvn(2))[0]
        elif L == 127: L = struct.unpack('>Q', s.recvn(8))[0]
        return json.loads(s.recvn(L))
NOW = int(time.time())
SNAP = {"at": NOW - 180, "config": {"MAA": {"关卡": "1-7", "理智药": 0, "作战开关": True, "活动关优先": True, "活动关序号": 1}},
        "run": {"服务": True, "在跑的": []},
        "queues": [{"名": "早班", "脚本": ["MAA", "MaaEnd", "OK-WW"], "定时": True, "时刻": "09:00"}, {"名": "晚班", "脚本": ["MAA"], "定时": True, "时刻": "21:30"}],
        "relay": {"调试模式": "15:50", "刷声骸": {}, "下次别关机": True, "今天跳过": "", "无音区截图": True, "最近指令": [], "周本": {}, "周常": {}},
        "plan": "📅 明日安排\n🕘 09:00　东京 10:00\n▸ 明日方舟\n理智 1-7（固定）\n理智药 0 瓶\n▸ 终末地\n基质刷取 双倍，最多 6 轮\n▸ 鸣潮\n凝素领域 第 4 个\n🕘 21:30　东京 22:30\n▸ 明日方舟\n理智 1-7（固定）",
        "今天": {"跑了": 2, "失败": 0, "最近": "鸣潮"}, "master": {}, "options": {}}
STAMINA = {"明日方舟": {"理智": 128, "上限": 135, "回满": "09-18 15:42"}, "终末地": {"理智": 96, "上限": 240, "回满": "09-19 02:10"},
           "鸣潮": {"波片": 172, "上限": 240, "回满": "09-18 18:20"}, "取自": "14:20"}
url = sys.argv[1]; dark = 'dark' in sys.argv[2:]; nodata = 'nodata' in sys.argv[2:]
def free_port():
    # several sessions run this runner at once: a fixed / random port can already belong to ANOTHER session's Chrome, and we would then talk to it
    # (EOF, "view.js not ready", 0/0 results). Ask the kernel for a free port instead.
    with socket.socket() as sk: sk.bind(('127.0.0.1', 0)); return sk.getsockname()[1]
port = free_port(); prof = tempfile.mkdtemp()
chrome_log = open(os.path.join(prof, 'chrome.log'), 'wb')   # Chrome's own stderr: a renderer crash shows here (printed on failure)
p = subprocess.Popen([CH, '--headless=new', '--hide-scrollbars', f'--remote-debugging-port={port}', f'--user-data-dir={prof}', '--window-size=440,956', 'about:blank'], stdout=subprocess.DEVNULL, stderr=chrome_log)
try:
    page = None
    for i in range(100):
        try: page = next(t for t in json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json')) if t['type'] == 'page'); break
        except Exception: time.sleep(0.2)
    ws = WS(page['webSocketDebuggerUrl'])
    own = ws.send('Browser.getVersion')['result'].get('userAgent', '')   # sanity: the DevTools endpoint answers → it is a live Chrome on our port
    ws.send('Runtime.enable'); ws.send('Page.enable')
    ws.send('Emulation.setFocusEmulationEnabled', {'enabled': True})   # a headless document is otherwise unfocused: focusin never fires (界面1号 5d71467's capsule row)
    ws.send('Emulation.setDeviceMetricsOverride', {'width': 440, 'height': 956, 'deviceScaleFactor': 3, 'mobile': True})
    if dark: ws.send('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': 'dark'}]})
    init = 'window.__acceptHold = true; localStorage.setItem("ark-remote-cfg", %s); localStorage.setItem("ark-remote-cfg-snap", %s); localStorage.setItem("ark-remote-tab", "状态");' % (
        json.dumps(json.dumps({"topic": "smoke-test-topic", "pin": "1234"})), json.dumps(json.dumps(SNAP, ensure_ascii=False)))
    if not nodata: ws.send('Page.addScriptToEvaluateOnNewDocument', {'source': init})
    t0 = time.time()
    def errors():
        return [e['params']['exceptionDetails'].get('text', '') + ' ' + ((e['params']['exceptionDetails'].get('exception') or {}).get('description', '')[:200]) for e in ws.events if e.get('method') == 'Runtime.exceptionThrown']
    def wait_ready():
        ready = None
        for i in range(300):                   # ≤ 60 s for view.js
            time.sleep(0.2)
            try: ready = ws.send('Runtime.evaluate', {'expression': 'document.readyState === "complete" && window.__viewReady === true', 'returnByValue': True})['result']['result'].get('value')
            except Exception: ready = None
            if ready is True: return True
        return False
    MISSING = ('(() => { const got = new Set(performance.getEntriesByType("resource").map(e => e.name)); '
               'return [...document.scripts].filter(s => s.src && !/accept[^/]*\\.js/.test(s.src) && !got.has(s.src)).map(s => s.src.split("/").pop()); })()')   # accept*.js are appended lazily by the page / by accept.js itself and may still be loading at this point
    ws.send('Page.navigate', {'url': url + ('&' if '?' in url else '?') + 'accept=1&quiet=1'})
    for attempt in (1, 2):
        if not wait_ready():
            print('view.js not ready in 60 s (document.readyState / window.__viewReady)'); print('JS errors:', errors()); sys.exit(1)
        missing = ws.send('Runtime.evaluate', {'expression': MISSING, 'returnByValue': True})['result']['result'].get('value') or []
        if missing: time.sleep(1.5); missing = ws.send('Runtime.evaluate', {'expression': MISSING, 'returnByValue': True})['result']['result'].get('value') or []   # a script still in flight is not a lost fetch
        early = errors()
        if not missing and not early: break
        if attempt == 2:
            print('page did not load cleanly twice: missing scripts', missing, 'errors', early); sys.exit(1)
        print('load incomplete (missing scripts %s, %d errors) — reloading once' % (missing, len(early)))
        ws.events = []; ws.send('Page.reload', {'ignoreCache': True})
    t_ready = time.time() - t0
    inj = ('window.Stamina && (Stamina.data = %s, Stamina.at = Date.now()); typeof lastHb !== "undefined" && (lastHb = Date.now()); '
           'typeof render === "function" && render(); typeof updateLive === "function" && updateLive(); ' % json.dumps(STAMINA, ensure_ascii=False)) if not nodata else ''
    res = ws.send('Runtime.evaluate', {'expression': inj + 'window.__acceptHold = false; 1', 'returnByValue': True})
    if 'exceptionDetails' in res.get('result', {}):
        print('injection threw:', res['result']['exceptionDetails'].get('text', ''), (res['result']['exceptionDetails'].get('exception') or {}).get('description', '')[:200])
    r = None
    for i in range(300):                       # ≤ 60 s for accept.js's result
        time.sleep(0.2)
        r = ws.send('Runtime.evaluate', {'expression': 'localStorage.getItem("ark-accept")', 'returnByValue': True})['result']['result'].get('value')
        if r: break
    errs = errors()
    if errs: print('JS errors:', errs)
    if not r: print(f'no result in 60 s after view.js ready (ready at {t_ready:.1f} s)'); sys.exit(1)
    print(f'view.js ready at {t_ready:.1f} s, result at {time.time() - t0:.1f} s')
    out = json.loads(r)
    print(f"{url} {'dark' if dark else 'light'}  {out['total'] - out['fails']}/{out['total']}")
    for row in out['rows']:
        print(('✓' if row['ok'] else '✗'), row['item'], '|', row['got'], '' if row['ok'] else '（要 ' + row['expect'] + '）')
except Exception as e:
    try:
        chrome_log.flush(); tail = open(os.path.join(prof, 'chrome.log'), 'rb').read()[-3000:].decode('utf-8', 'replace')
        print('runner failed:', repr(e)); print('chrome stderr tail:', tail)
    except Exception: pass
    raise
finally:
    p.terminate()
    try: p.wait(timeout=5)
    except Exception: p.kill()
    shutil.rmtree(prof, ignore_errors=True)
