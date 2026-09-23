# -*- coding: utf-8 -*-
"""Run web/accept.js in headless Chrome (desktop Chromium: no safe area) with a fake snapshot.
usage: accept-run.py <url-without-query> [light|dark|both] [nodata] [--only <控件[,控件]>] [--out <prefix>] [--shard N] [--no-virtual-time] [--timeout S]  → prints the ark-accept rows
  Hard timeouts (八条④, 验收 15:2x: a --virtual-time run hung 30 minutes holding the machine lock): every CDP send has a 30 s socket timeout, a
  virtual-time step that sees no budget-expired event / no page rAF for 10 s prints "virtual time stalled at step k" and that theme is re-run on
  the wall clock once, and a watchdog ends the whole run at --timeout seconds (default 300): it prints what it was waiting for, kills Chrome and
  exits 1; the finally always releases the lock, Chrome and the profile.
  S3 (老网页 2026-09-20 13:2x, SPEED2-summary): by default (since 15:3x) the page runs on CDP virtual time once it is ready and the hold is released: Chrome
  is started with --enable-begin-frame-control --disable-frame-rate-limit, the clock is set to 'pause', then stepped 16.667 ms at a time
  (Emulation.setVirtualTimePolicy advance, budget 16.667); the page's requestAnimationFrame is replaced by a queue (VT_PATCH) that the runner
  drains once per step (__vtStep: the callbacks run with the step's time, nested requests wait for the next step) and then one real compositor
  frame is forced and awaited (__vt.f) — exactly one frame per 16.667 ms of page time, steps = frames (the earlier rAF counter let the
  free-running renderer paint 6–15 frames a step and the per-frame timing rows drifted by a frame, 验收 15:4x), so setTimeout / rAF /
  performance.now / CSS animations all advance together and the accept files' sleeps cost no wall time. Measured 2026-09-20 13:16 (light, 703 rows): 52 s wall for 109.5 s of page time (6570 steps) vs 115 s on the
  wall clock; nav / nav-edge alone 4 s (7.5 s page time). The 9 rows that first read differently on the virtual clock (cell / glassbtn / tabbar /
  nav R69′: PointerEvent timeStamps, transitions armed after a double rAF, a one-frame sampling window) were made clock-agnostic by their
  authors (night 81a961f / 29640bf / 47fb198); 验收's two full sharded runs then read 572/572 · 281/281 on both clocks (25 s wall) and the
  default flipped. --no-virtual-time keeps the wall clock (for checking a row that differs); --virtual-time is a no-op. The row format is
  unchanged; the ready line says "virtual time: <steps> steps / <frames> frames = <s> s of page time".
  S2 (2号 2026-09-20 13:0x, SPEED2-summary): --shard N runs each theme in N browser contexts at once, each loading a share of the accept files /
  sections through the loader's ?only= (TAGS below, packed by the explicit-sleep cost of each tag), and merges the rows back into the one list:
  rows an identical (item, expect) produced by a second shard — the core rows (readiness / loader / errors) and sections tagged with two names —
  are kept once; each shard's tag list is printed once as "--- shard k: … ---" before its readiness lines; every row ends with ⟨file⟩ = the
  loader's tag of the section that produced it (accept.js check() `tag`; a page without it gets the shard's list) — 验收 S6 attributes red rows
  by it; totals are recomputed. --only and --shard combine (the shards divide the --only list); the lock and `both` are unchanged; the dark
  context's page also gets ?theme=dark (S4-tags.md (d)). Measured 2026-09-20 13:01 (both, 707 rows per theme): --shard 3 46 s wall (the
  tabbar shard 45 s) vs 115 s unsharded; six renderers at once flaked 3 timing rows of 1414 (0 unsharded) — S3's virtual time is the fix.
  T2 (2号 2026-09-20 12:2x, SPEED-summary §三): `both` runs light and dark in ONE Chrome, each in its own browser context (separate localStorage — the
  result key ark-accept must not be shared — and its own renderer), in parallel; the two results print as separate sections and, with --out <prefix>,
  land in <prefix>-light.txt / <prefix>-dark.txt. `--only a,b` is passed to the page as ?only=a,b (accept.js's loader, 界面 T1, loads only those
  accept-<控件>.js files; absent = the whole suite). A machine-wide lock (/tmp/ark-accept-run.lock, flock) queues concurrent runners of any session
  instead of letting them share the CPU (timing rows) — a waiting runner says so every 15 s.
Order of events (监督局 2026-09-19 18:3x: no more "no result / first-run retry"):
  1. the page is opened with ?accept=1&quiet=1; window.__acceptHold = true is set before any page script, so accept.js
     (which also waits for window.__viewReady) does not start measuring yet;
  2. the runner waits up to 60 s for document.readyState === "complete" and window.__viewReady === true (set at the end
     of view.js — the inline loader in index.html can deliver view.js late);
  3. the stamina data is injected, render() / updateLive() run, the hold is released;
  4. the runner waits up to 180 s for accept.js's result (localStorage ark-accept; the night batch's full run is ~70 s).
  2b. before the hold is released the runner checks that every <script src> of the document appears in the resource-timing
     entries and that no exception was thrown so far; otherwise it reloads the page once and waits again (2026-09-19 18:41,
     first run of this runner: headless Chrome never requested pending.js?v=… — server log — and render() threw
     "reconcilePending is not defined"; the second run was clean. A lost script fetch is detected here, not retried by hand).
Any JS exception seen on the way is printed; exit 1 when a step does not complete."""
import socket, os, re, base64, json, struct, sys, subprocess, time, urllib.request, http.client, tempfile, shutil, signal, threading, fcntl
# SIGTERM (the `timeout` wrapper) must run the finally below, or the Chrome profile in $TMPDIR leaks (271 of them, 8.8 GB, 2026-09-20 08:4x)
signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(143)))
CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# What a DevTools /json probe raises while Chrome is still starting or a target is not listed yet: refused / reset (OSError, URLError),
# a truncated HTTP answer (HTTPException), half-written JSON (ValueError), no matching target yet (StopIteration, KeyError).
PROBE_ERRORS = (OSError, http.client.HTTPException, ValueError, StopIteration, KeyError)
# What a CDP call over WS raises: the 30 s timeout and a dead socket (OSError), a closed stream (EOFError), a frame that is not JSON
# (ValueError), and an error reply that has no ['result'] (KeyError, TypeError).
CDP_ERRORS = (OSError, EOFError, ValueError, KeyError, TypeError)
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
        s.sock.settimeout(30.0)   # a hung renderer never answers: 30 s and the call raises (socket.timeout) instead of holding the lock forever
        try:
            while True:
                m = s.recv()
                if m.get('id') == s.id: return m
                s.events.append(m)
        finally: s.sock.settimeout(None)
    def recv_event(s, timeout=5.0):
        """read one event (a message without our id) — used while waiting for Emulation.virtualTimeBudgetExpired (S3); raises on timeout"""
        s.sock.settimeout(timeout)
        try:
            m = s.recv(); s.events.append(m); return m
        finally: s.sock.settimeout(None)
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
args = sys.argv[2:]
def opt(name):
    if name in args:
        i = args.index(name); v = args[i + 1] if i + 1 < len(args) else ''; del args[i:i + 2]; return v
    return None
only = opt('--only'); outp = opt('--out'); shard = int(opt('--shard') or 1); total_timeout = float(opt('--timeout') or 300)
virtual_time = '--no-virtual-time' not in args   # S3: the default since 2026-09-20 15:3x (the 9 clock-mixing rows read the same on both clocks; 验收 two full runs 572/572 · 281/281); --virtual-time is accepted as a no-op
for f in ('--virtual-time', '--no-virtual-time'):
    if f in args: args.remove(f)
url = sys.argv[1]; nodata = 'nodata' in args
themes = ['light', 'dark'] if 'both' in args else (['dark'] if 'dark' in args else ['light'])
base_url = url
if only: url = url + ('&' if '?' in url else '?') + 'only=' + only
# the loader's tags (web/accept.js ACCEPT.files + its own section tags segctl / cell / page) with the cost used to pack the shards: the sum of the
# explicit sleep() ms in accept-<tag>.js plus in accept.js's sec("<tag>") regions at night 7250d29 (BOARD S4-tags.md (e) has the per-file column)
TAGS = [('tabbar', 26.1), ('segctl', 17.4), ('page', 10.9), ('cell', 6.7), ('sheet', 6.5), ('switch', 6.5), ('glassbtn', 5.0), ('alert', 4.3), ('topbar', 1.8),
        ('nav', 1.3), ('refresh', 1.1), ('nav-edge', 1.1), ('menu', 0.7), ('tile', 0.6), ('motion', 0.2),
        ('stockpile', 4.0), ('diagmark', 4.0), ('tabbar-view', 4.0), ('alert-view', 4.0), ('topbar-view', 4.0),
        ('selfcheck', 0.2)]   # 老网页 P3 (accept-selfcheck.js: 4 × sleep(50))
        # 验收 09-23 17:5x: the five tags added since the table was measured; a tag missing here was in no shard, so --shard silently dropped its rows (night 573 vs 590, merged main 577 vs 632); 4.0 = shards_of's own default for an unmeasured tag
def shards_of(n, wanted):
    """the ?only= list of each shard: the wanted tags (all when --only is absent) greedy-packed by cost into n bins, heaviest first"""
    known = dict(TAGS)
    tags = [(t, known.get(t, 4.0)) for t in wanted] if wanted else list(TAGS)
    if n <= 1: return [','.join(t for t, _ in tags) if wanted else '']
    bins = [[0.0, []] for _ in range(n)]
    for t, c in sorted(tags, key=lambda x: -x[1]):
        b = min(bins, key=lambda x: x[0]); b[0] += c; b[1].append(t)
    return [','.join(b[1]) for b in bins if b[1]]
SHARDS = shards_of(shard, [x.strip() for x in only.split(',') if x.strip()] if only else None)   # '' = the whole suite in one context
if shard > 1 and not only:   # a page file whose tag is not in TAGS lands in no shard and its rows vanish without a red row: refuse instead
    try: page_files = re.findall(r'"([a-z-]+)"', re.search(r'ACCEPT\.files = \[([^\]]*)\]', urllib.request.urlopen(base_url.rsplit('/', 1)[0] + '/accept.js', timeout=10).read().decode('utf-8')).group(1))
    except (OSError, AttributeError) as e: sys.exit(f'✗ --shard: could not read ACCEPT.files from accept.js ({e}); run without --shard')
    lost = [t for t in page_files if t not in dict(TAGS)]
    if lost: sys.exit('✗ --shard: accept.js loads ' + ', '.join(lost) + ' but TAGS has no entry, so no shard would run them; add them to TAGS')
def free_port():
    # several sessions run this runner at once: a fixed / random port can already belong to ANOTHER session's Chrome, and we would then talk to it
    # (EOF, "view.js not ready", 0/0 results). Ask the kernel for a free port instead.
    with socket.socket() as sk: sk.bind(('127.0.0.1', 0)); return sk.getsockname()[1]
# Chrome leaves a code-signing clone of its own bundle per launch under $TMPDIR/../X/com.google.Chrome.code_sign_clone and a killed
# instance never removes it (320 of them by 2026-09-20 11:50, ≈ 1 GB real, 440 GB apparent); sweep the ones older than 10 minutes —
# no live Chrome keeps a clone that old — before every run (BOARD disk-2026-09-20.md)
def sweep_code_sign_clones():
    try:
        base = os.path.join(os.path.dirname(tempfile.gettempdir().rstrip('/')), 'X', 'com.google.Chrome.code_sign_clone')
        if not os.path.isdir(base): return
        now = time.time()
        for name in os.listdir(base):
            d = os.path.join(base, name)
            try:
                if now - os.stat(d).st_mtime > 600: shutil.rmtree(d, ignore_errors=True)
            except OSError: pass
    except OSError: pass
sweep_code_sign_clones()
LOCK = '/tmp/ark-accept-run.lock'   # one headless run per machine at a time (several sessions run this runner; two at once share the CPU and flake the timing rows)
open(LOCK, 'a').close(); lockf = open(LOCK, 'r+')
t_lock = time.time()
while True:
    try: fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB); break
    except OSError:
        if int(time.time() - t_lock) % 15 == 0:
            try: lockf.seek(0); holder = lockf.read().strip()[:80]
            except (OSError, ValueError): holder = '?'   # ValueError: a half-written holder line that is not UTF-8
            print(f'waiting for {LOCK} (held by {holder}) …', flush=True)
        time.sleep(1)
try: lockf.seek(0); lockf.truncate(); lockf.write(f'pid {os.getpid()} {time.strftime("%H:%M:%S")} {url}'); lockf.flush()
except OSError: pass
if time.time() - t_lock > 2: print(f'lock acquired after {time.time() - t_lock:.0f} s')
port = free_port(); prof = tempfile.mkdtemp()
chrome_log = open(os.path.join(prof, 'chrome.log'), 'wb')   # Chrome's own stderr: a renderer crash shows here (printed on failure)
p = subprocess.Popen([CH, '--headless=new', '--hide-scrollbars', f'--remote-debugging-port={port}', f'--user-data-dir={prof}', '--window-size=440,956'] + (['--enable-begin-frame-control', '--disable-frame-rate-limit'] if virtual_time else []) + ['about:blank'], stdout=subprocess.DEVNULL, stderr=chrome_log)   # S3: frames are issued by the runner (HeadlessExperimental.beginFrame) in step with the virtual clock
try:
    page = None
    for i in range(100):
        try: page = next(t for t in json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json')) if t['type'] == 'page'); break
        except PROBE_ERRORS: time.sleep(0.2)
    bws = WS(json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version'))['webSocketDebuggerUrl'])   # the browser endpoint: contexts and targets
    own = bws.send('Browser.getVersion')['result'].get('userAgent', '')   # sanity: the DevTools endpoint answers → it is a live Chrome on our port
    # the heartbeat probe (live.js probeHb: fetch <ntfy>/<topic>-hb/json) lands ≈ .5 s after load and, finding no heartbeat for the fake topic, sets
    # lastHb = 0 → updateLive() re-renders main ("off"); the demo's 1 s interval restores lastHb → a second re-render ≤ 1 s later. A control file that
    # picked its elements before those renders holds detached nodes (2号 14:3x: accept-menu under ?only=menu opened on a button the +520 ms render
    # replaced → close() read a zero anchor rect). The hold is released only after the probe's fetch settled (window.__hbProbed, ≤ 5 s), so the
    # injected lastHb = now below is the last word and main stays put from the first row on.
    init = ('window.__acceptHold = true; window.__hbProbed = false; (() => { const f = window.fetch; window.fetch = function (u) { const p = f.apply(this, arguments); '
            'if (/-hb\\/json/.test(String(u))) p.then(() => { window.__hbProbed = true; }, () => { window.__hbProbed = true; }); return p; }; })(); '
            'localStorage.setItem("ark-remote-cfg", %s); localStorage.setItem("ark-remote-cfg-snap", %s); localStorage.setItem("ark-remote-tab", "状态");') % (
        json.dumps(json.dumps({"topic": "smoke-test-topic", "pin": "1234"})), json.dumps(json.dumps(SNAP, ensure_ascii=False)))
    MISSING = ('(() => { const ok = new Set(performance.getEntriesByType("resource").filter(e => (e.responseStatus === 0 || e.responseStatus === 200 || e.responseStatus === 304) && (e.transferSize > 0 || e.encodedBodySize > 0 || e.decodedBodySize > 0)).map(e => e.name)); '
               'const js = [...document.scripts].filter(s => s.src && !/accept[^/]*\\.js/.test(s.src) && !ok.has(s.src)).map(s => s.src.split("/").pop()); '
               'const size = (h) => { const e = performance.getEntriesByType("resource").find(x => x.name === h); return e ? Math.max(e.decodedBodySize || 0, e.encodedBodySize || 0) : 0; }; '
               'const css = [...document.querySelectorAll("link[rel=stylesheet]")].filter(l => { try { const sh = [...document.styleSheets].find(x => x.href === l.href); return !sh || (sh.cssRules.length === 0 && size(l.href) > 300); } catch (e) { return false; } }).map(l => l.href.split("/").pop()); '
               'return js.concat(css); })()')   # a script counts as arrived only with a body (a refused / reset connection leaves an empty entry and it silently never runs); a stylesheet counts only when it is in document.styleSheets with rules (数据: topbar.css once never applied); accept*.js are appended lazily and may still be loading
    def wait_hb_probe(ws, log):
        """≤ 5 s for the heartbeat probe's fetch to settle (window.__hbProbed, see init): ≈ .5 s with the network up, at once without; not under nodata"""
        if nodata: return
        for i in range(25):
            if ws.send('Runtime.evaluate', {'expression': 'window.__hbProbed === true', 'returnByValue': True})['result']['result'].get('value') is True: return
            time.sleep(0.2)
        log('heartbeat probe not settled in 5 s (window.__hbProbed) — injecting anyway')
    VT_PATCH = ("window.__vt = { q: new Map(), n: 0, f: 0, orig: window.requestAnimationFrame.bind(window) }; "
                "window.requestAnimationFrame = (cb) => { const id = ++__vt.n; __vt.q.set(id, cb); return id; }; "
                "window.cancelAnimationFrame = (id) => { __vt.q.delete(id); }; "
                "window.__vtStep = () => { const q = __vt.q; __vt.q = new Map(); const t = performance.now(); "
                "for (const cb of q.values()) { try { cb(t); } catch (e) { console.error(e); } } "
                "__vt.orig(() => { __vt.f++; }); return __vt.f; }; 1")
    def run_theme(dark, wsurl, only_list):  # noqa: C901 — one CDP session from navigate to rows; split, its steps would pass ws/lines/t0 around
        """one theme × one shard in its own browser context (own localStorage, own renderer — the browser-level WS is not thread-safe, so the context and
        target are made in the main thread); returns (lines, ok, rows)"""
        lines = []
        def log(*a): lines.append(' '.join(str(x) for x in a))
        url = base_url + (('&' if '?' in base_url else '?') + 'only=' + only_list if only_list else '')
        if dark: url += ('&' if '?' in url else '?') + 'theme=dark'   # S4 (数据 S4-tags.md (d)): the loader skips the dark:false files / sections under ?theme=dark once 界面 wires it; the media emulation below is what sets the colours
        ws = WS(wsurl)
        ws.send('Runtime.enable'); ws.send('Page.enable')
        ws.send('Emulation.setFocusEmulationEnabled', {'enabled': True})   # a headless document is otherwise unfocused: focusin never fires (界面1号 5d71467's capsule row)
        ws.send('Emulation.setDeviceMetricsOverride', {'width': 440, 'height': 956, 'deviceScaleFactor': 3, 'mobile': True})
        if dark: ws.send('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': 'dark'}]})
        if not nodata: ws.send('Page.addScriptToEvaluateOnNewDocument', {'source': init})
        t0 = time.time()
        def errors():
            return [e['params']['exceptionDetails'].get('text', '') + ' ' + ((e['params']['exceptionDetails'].get('exception') or {}).get('description', '')[:200]) for e in ws.events if e.get('method') == 'Runtime.exceptionThrown']
        def wait_ready():
            ready = None
            for i in range(300):                   # ≤ 60 s for view.js
                time.sleep(0.2)
                try: ready = ws.send('Runtime.evaluate', {'expression': 'document.readyState === "complete" && window.__viewReady === true', 'returnByValue': True})['result']['result'].get('value')
                except CDP_ERRORS: ready = None
                if ready is True: return True
            return False
        ws.send('Page.navigate', {'url': url + ('&' if '?' in url else '?') + 'accept=1&quiet=1'})
        for attempt in (1, 2):
            if not wait_ready():
                log('view.js not ready in 60 s (document.readyState / window.__viewReady)'); log('JS errors:', errors()); return lines, False, []
            missing = ws.send('Runtime.evaluate', {'expression': MISSING, 'returnByValue': True})['result']['result'].get('value') or []
            if missing: time.sleep(1.5); missing = ws.send('Runtime.evaluate', {'expression': MISSING, 'returnByValue': True})['result']['result'].get('value') or []   # a script still in flight is not a lost fetch
            early = errors()
            if not missing and not early: break
            if attempt == 2:
                log('page did not load cleanly twice: missing scripts', missing, 'errors', early); return lines, False, []
            log('load incomplete (missing scripts %s, %d errors) — reloading once' % (missing, len(early)))
            ws.events = []; ws.send('Page.reload', {'ignoreCache': True})
        t_ready = time.time() - t0
        wait_hb_probe(ws, log)
        inj = ('window.Stamina && (Stamina.data = %s, Stamina.at = Date.now()); typeof lastHb !== "undefined" && (lastHb = Date.now()); '
               'typeof render === "function" && render(); typeof updateLive === "function" && updateLive(); ' % json.dumps(STAMINA, ensure_ascii=False)) if not nodata else ''
        if virtual_time:   # S3: from here on the page's clock is virtual — stepped 16.7 ms at a time below, so every rAF gets its frame (one big 'advance' budget starves rAF: timers race ahead, the drives see 1 s dt steps)
            ws.send('Emulation.setVirtualTimePolicy', {'policy': 'pause'})
        if virtual_time:   # one frame per step (用户 15:4x): the page's requestAnimationFrame is replaced by a queue the runner drains once per 16.667 ms step — __vtStep() runs the queued callbacks with the step's time (nested requests land in the next step: afterPaint = two steps) and then asks the real compositor for exactly one frame (__vt.f), so steps = frames whatever the renderer's free-running frame rate does
            ws.send('Runtime.evaluate', {'expression': VT_PATCH})
        res = ws.send('Runtime.evaluate', {'expression': inj + 'window.__acceptHold = false; 1', 'returnByValue': True})
        if 'exceptionDetails' in res.get('result', {}):
            log('injection threw:', res['result']['exceptionDetails'].get('text', ''), (res['result']['exceptionDetails'].get('exception') or {}).get('description', '')[:200])
        r = None
        vsteps = 0; vframes = 0; stalls = 0
        for i in range(900 if not virtual_time else 60000):   # ≤ 180 s wall for accept.js's result; virtual: ≤ 60000 frames = 1000 s of page time
            if virtual_time:
                # one frame of page time per step: advance the virtual clock by 16.667 ms and wait for the budget to expire — timers due in that slice run,
                # and the renderer produces the frame (rAF callbacks) before the next step; the accept's sleeps thus cost the CDP round trip only
                ws.send('Emulation.setVirtualTimePolicy', {'policy': 'advance', 'budget': 16.667, 'maxVirtualTimeTaskStarvationCount': 10000})
                expired = False; t_step = time.time()
                while time.time() - t_step < 10:
                    if any(e.get('method') == 'Emulation.virtualTimeBudgetExpired' for e in ws.events): expired = True; break
                    try: ws.recv_event(timeout=2.0)
                    except socket.timeout: continue
                    except CDP_ERRORS: break
                ws.events = [e for e in ws.events if e.get('method') != 'Emulation.virtualTimeBudgetExpired']
                got_frame = False
                ws.send('Runtime.evaluate', {'expression': 'window.__vtStep ? window.__vtStep() : -1', 'returnByValue': True})['result']['result'].get('value')   # the frame's rAF callbacks, at this step's time
                for k in range(400):                # then exactly one real compositor frame (style / layout / animation events) before the next step
                    f = ws.send('Runtime.evaluate', {'expression': 'window.__vt ? window.__vt.f : -1', 'returnByValue': True})['result']['result'].get('value')
                    if isinstance(f, int) and f > vframes: vframes = f; got_frame = True; break
                    time.sleep(0.0005)
                stalls = stalls + 1 if not (expired and got_frame) else 0
                if stalls >= 3:                     # 3 consecutive slices without the clock or the frame moving = a hung page: give up on virtual time here
                    msg = f'virtual time stalled at step {vsteps} (budget expired {expired}, frame {got_frame}; {vframes} frames so far) — this theme is re-run on the wall clock'
                    log(msg); print(msg, flush=True)
                    return lines, None, []
                vsteps += 1
                if vsteps % 30: continue            # poll the result every 30 frames (≈ .5 s of page time)
            else: time.sleep(0.2)
            r = ws.send('Runtime.evaluate', {'expression': 'localStorage.getItem("ark-accept")', 'returnByValue': True})['result']['result'].get('value')
            if r: break
        errs = errors()
        if errs: log('JS errors:', errs)
        if not r: log(f'no result in 180 s after view.js ready (ready at {t_ready:.1f} s)'); return lines, False, []
        log(f'view.js ready at {t_ready:.1f} s, result at {time.time() - t0:.1f} s' + (f' (virtual time: {vsteps} steps / {vframes} frames = {vsteps / 60:.1f} s of page time)' if virtual_time else ' (wall clock)'))
        return lines, True, json.loads(r)['rows']
    jobs = [(th, k) for th in themes for k in range(len(SHARDS))]   # (theme, shard index); SHARDS[k] is the shard's ?only list
    targets = {}
    for job in jobs:
        ctx = bws.send('Target.createBrowserContext')['result']['browserContextId']
        tid = bws.send('Target.createTarget', {'url': 'about:blank', 'browserContextId': ctx})['result']['targetId']
        wsurl = None
        for i in range(50):
            try: wsurl = next(t['webSocketDebuggerUrl'] for t in json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json')) if t.get('id') == tid); break
            except PROBE_ERRORS: time.sleep(0.2)
        targets[job] = (ctx, tid, wsurl)
    results = {}
    def worker(job):
        global virtual_time  # noqa: PLW0603 — after one stall every later context of this run falls back to the wall clock
        try:
            res = run_theme(job[0] == 'dark', targets[job][2], SHARDS[job[1]])
            if res[1] is None:                       # virtual time stalled: once more on the wall clock in a fresh context (the hung page is closed)
                lines0 = res[0]; virtual_time = False
                ctx = bws.send('Target.createBrowserContext')['result']['browserContextId']
                tid = bws.send('Target.createTarget', {'url': 'about:blank', 'browserContextId': ctx})['result']['targetId']
                wsurl = None
                for i in range(50):
                    try: wsurl = next(t['webSocketDebuggerUrl'] for t in json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json')) if t.get('id') == tid); break
                    except PROBE_ERRORS: time.sleep(0.2)
                res = run_theme(job[0] == 'dark', wsurl, SHARDS[job[1]]); res = (lines0 + res[0], bool(res[1]), res[2])
            results[job] = res
        except Exception as e: results[job] = ([f'runner failed ({job[0]}{" shard %d" % (job[1] + 1) if len(SHARDS) > 1 else ""}): {e!r}'], False, [])   # noqa: BLE001 — a thread's exception would otherwise vanish and the job read "no result"; any failure becomes its row
    threads = [threading.Thread(target=worker, args=(job,), daemon=True) for job in jobs]
    t_start = time.time()
    for t in threads: t.start()
    for t in threads: t.join(max(0.0, total_timeout - (time.time() - t_start)))
    if any(t.is_alive() for t in threads):          # the watchdog: whatever a thread is still waiting for, the run ends here — Chrome and the lock go in the finally
        print(f'runner timed out after {total_timeout:.0f} s (--timeout): still waiting on ' + ', '.join(f'{job[0]}' + (f' shard {job[1] + 1}' if len(SHARDS) > 1 else '') for job, t in zip(jobs, threads) if t.is_alive()) + ' — Chrome killed, lock released', flush=True)
        sys.exit(1)
    for job in jobs:
        try: bws.send('Target.closeTarget', {'targetId': targets[job][1]}); bws.send('Target.disposeBrowserContext', {'browserContextId': targets[job][0]})
        except CDP_ERRORS: pass
    failed = False
    for th in themes:
        lines = []; rows = []; first = {}; ok_all = True   # first: (item, expect) → shard index that produced it first (a copy from another shard is dropped)
        for job in jobs:
            if job[0] != th: continue
            jl, ok, jr = results.get(job, (['no result'], False, [])); ok_all = ok_all and ok
            if len(SHARDS) > 1: lines.append(f'--- shard {job[1] + 1}: {SHARDS[job[1]]} ---')
            lines += jl
            for row in jr:
                key = (row['item'], row['expect'])
                if first.setdefault(key, job[1]) != job[1]: continue
                rows.append((row, row.get('tag') or (SHARDS[job[1]] if len(SHARDS) > 1 else '')))
        failed = failed or not ok_all
        fails = sum(1 for row, _ in rows if not row['ok'])
        lines.append(f"{url} {th}  {len(rows) - fails}/{len(rows)}" + (f'  (--shard {len(SHARDS)})' if len(SHARDS) > 1 else ''))
        for row, tag in rows:
            lines.append(('✓' if row['ok'] else '✗') + ' ' + row['item'] + ' | ' + row['got'] + ('' if row['ok'] else '（要 ' + row['expect'] + '）') + (' ⟨' + tag + '⟩' if tag else ''))
        if len(themes) > 1: print(f'=== {th} ===')
        print('\n'.join(lines))
        if outp:
            with open(f'{outp}-{th}.txt', 'w') as f: f.write('\n'.join(lines) + '\n')
    if failed: sys.exit(1)
except Exception as e:
    try:
        chrome_log.flush(); tail = open(os.path.join(prof, 'chrome.log'), 'rb').read()[-3000:].decode('utf-8', 'replace')
        print('runner failed:', repr(e)); print('chrome stderr tail:', tail)
    except OSError: pass
    raise
finally:
    p.terminate()
    try: p.wait(timeout=5)
    except subprocess.TimeoutExpired: p.kill()
    shutil.rmtree(prof, ignore_errors=True)
    try: fcntl.flock(lockf, fcntl.LOCK_UN); lockf.close()
    except OSError: pass
