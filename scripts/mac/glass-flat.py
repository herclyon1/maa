# -*- coding: utf-8 -*-
"""Five-grey flat-background check of the read-key glass chains (alert-glass.js, menu.js) in headless Chrome — R57′ (2号, 2026-09-20).
usage: glass-flat.py <url-without-query> [alert|menu] [light|dark|both]  → one line per theme × grey: the panel centre's value, the closed
       chain's prediction (alert-native-formula.md §4 ⑦ from the page's own keys), Δ, the flatness (sd of a 40 × 40 device-px box) and the
       centre column / row profiles.
What it does: the page is loaded with a fake snapshot (the same seed as accept-run.py); #app is emptied (alert) or reduced to the menu button
(menu: every other element visibility hidden, the kept ancestors' backgrounds cleared, the button itself opacity 0 so the copy sees nothing);
body / html get the flat grey; the alert is opened with ask() / the menu by clicking the button; after the settle (the menu's full chain
arrives once the morph rests) a screenshot at dpr 3 is sampled. The prediction is ⑦'s grey path: dimming (alert only) → MaxLuma → face with
the premultiplied fill → bleed mix; the keys are read from AlertGlass.keysFor(theme) / Menu.glass.keys(theme) so the formula follows the page.
Needs Pillow. Exit 1 when a panel did not open."""
import socket, os, base64, json, struct, sys, subprocess, time, urllib.request, tempfile, shutil, statistics, io
from PIL import Image
CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
class WS:
    def __init__(s, url):
        host, port = url.split('/')[2].split(':'); path = '/' + '/'.join(url.split('/')[3:])
        s.sock = socket.create_connection((host, int(port))); key = base64.b64encode(os.urandom(16)).decode()
        s.sock.send(f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        buf = b''
        while b'\r\n\r\n' not in buf: buf += s.sock.recv(4096)
        s.id = 0
    def send(s, method, params=None):
        s.id += 1; data = json.dumps({'id': s.id, 'method': method, 'params': params or {}}).encode(); mask = os.urandom(4); L = len(data)
        hdr = bytes([0x81]) + (bytes([0x80 | L]) if L < 126 else bytes([0x80 | 126]) + struct.pack('>H', L) if L < 65536 else bytes([0x80 | 127]) + struct.pack('>Q', L))
        s.sock.send(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        while True:
            m = s.recv()
            if m.get('id') == s.id: return m
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
SNAP = {"at": NOW - 180, "config": {"MAA": {"关卡": "1-7", "理智药": 0, "作战开关": True, "活动关优先": True, "活动关序号": 1}}, "run": {"服务": True, "在跑的": []},
        "queues": [{"名": "早班", "脚本": ["MAA", "MaaEnd", "OK-WW"], "定时": True, "时刻": "09:00"}, {"名": "晚班", "脚本": ["MAA"], "定时": True, "时刻": "21:30"}],
        "relay": {"调试模式": "15:50", "刷声骸": {}, "下次别关机": True, "今天跳过": "", "无音区截图": True, "最近指令": [], "周本": {}, "周常": {}},
        "plan": "📅 明日安排", "今天": {"跑了": 2, "失败": 0, "最近": "鸣潮"}, "master": {}, "options": {}}
JS_ALERT = """(async () => { await new Promise(r => setTimeout(r, 1500)); const app = document.getElementById("app"); app.innerHTML = ""; app.style.cssText = "background:rgb(N,N,N);min-height:1400px";
  for (const el of [document.body, document.documentElement]) el.style.background = "rgb(N,N,N)"; await new Promise(r => setTimeout(r, 300)); ask("确认", "说明", "好", false); await new Promise(r => setTimeout(r, 900));
  const d = document.querySelector("dialog[open]"), r = d.getBoundingClientRect(); return { rect: [r.left, r.top, r.width, r.height], keys: AlertGlass.keysFor(AlertGlass.theme()), theme: AlertGlass.theme(), layer: !!AlertGlass.layer }; })()"""
JS_MENU = """(async () => { await new Promise(r => setTimeout(r, 1500)); const btn = document.querySelector("main .menubtn"); const keep = new Set(); for (let e = btn; e; e = e.parentElement) keep.add(e);
  document.querySelectorAll("#app *").forEach(e => { if (!keep.has(e)) e.style.visibility = "hidden"; else { e.style.background = "transparent"; e.style.boxShadow = "none"; e.style.border = "0"; e.style.backdropFilter = "none"; } }); btn.style.opacity = "0";
  for (const el of [document.body, document.documentElement]) el.style.background = "rgb(N,N,N)"; document.getElementById("app").style.minHeight = "1400px";
  btn.scrollIntoView({ block: "center" }); await new Promise(r => setTimeout(r, 300)); btn.click(); await new Promise(r => setTimeout(r, 1800));
  const p = document.querySelector(".menu.morph"), r = p.getBoundingClientRect(), w3 = p.querySelector(".menu-glass-w3"); return { rect: [r.left, r.top, r.width, r.height], keys: Menu.glass.keys(Menu.glass.theme()), theme: Menu.glass.theme(), full: /f3/.test(w3 && w3.style.filter || "") }; })()"""
def predict(D, k, dimming):
    D = D * (1 - dimming); comp = 1 - k["FaceColorMatrixMaxLumaSDR"]; a = k["FaceColorMatrixFillColor"][3]
    c1 = D * (1 - comp * D); c2 = (1 - a) * ((k["FaceColorMatrixWhite"] - k["FaceColorMatrixBlack"]) * c1 + k["FaceColorMatrixBlack"]) + a
    w = (c2 ** 4 if k["BleedDarkenBlend"] else ((1 - c2) ** 2) ** 2) * k["BleedOpacity"]; cb = (k["BleedColorMatrixWhite"] - k["BleedColorMatrixBlack"]) * D + k["BleedColorMatrixBlack"]
    return (c2 + w * (cb - c2)) * 255
def shot(url, js, dark):
    with socket.socket() as sk: sk.bind(('127.0.0.1', 0)); port = sk.getsockname()[1]
    prof = tempfile.mkdtemp(); p = subprocess.Popen([CH, '--headless=new', '--hide-scrollbars', f'--remote-debugging-port={port}', f'--user-data-dir={prof}', '--window-size=440,956', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        page = None
        for i in range(100):
            try: page = next(t for t in json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json')) if t['type'] == 'page'); break
            except (OSError, ValueError, StopIteration): time.sleep(0.2)   # DevTools not up yet: refused / half-written JSON / no page target
        ws = WS(page['webSocketDebuggerUrl']); ws.send('Runtime.enable'); ws.send('Page.enable'); ws.send('Emulation.setDeviceMetricsOverride', {'width': 440, 'height': 956, 'deviceScaleFactor': 3, 'mobile': True})
        ws.send('Page.addScriptToEvaluateOnNewDocument', {'source': 'localStorage.setItem("ark-remote-cfg", %s); localStorage.setItem("ark-remote-cfg-snap", %s); localStorage.setItem("ark-remote-tab", "状态");' % (json.dumps(json.dumps({'topic': 'smoke-test-topic', 'pin': '1234'})), json.dumps(json.dumps(SNAP, ensure_ascii=False)))})
        if dark: ws.send('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': 'dark'}]})
        ws.send('Page.navigate', {'url': url}); time.sleep(4)
        r = ws.send('Runtime.evaluate', {'expression': js, 'awaitPromise': True, 'returnByValue': True}); info = r.get('result', {}).get('result', {}).get('value')
        time.sleep(1.0); png = base64.b64decode(ws.send('Page.captureScreenshot', {'format': 'png'})['result']['data'])
        return info, Image.open(io.BytesIO(png)).convert('RGB')
    finally:
        p.kill(); shutil.rmtree(prof, ignore_errors=True)
if __name__ == '__main__':
    url = sys.argv[1]; which = [w for w in sys.argv[2:] if w in ('alert', 'menu')] or ['alert', 'menu']; th = next((w for w in sys.argv[2:] if w in ('light', 'dark', 'both')), 'both'); themes = ['light', 'dark'] if th == 'both' else [th]
    bad = 0
    for what in which:
        for theme in themes:
            for N in [255, 192, 128, 64, 0]:
                js = (JS_ALERT if what == 'alert' else JS_MENU).replace('N,N,N', f'{N},{N},{N}'); info, im = shot(url, js, theme == 'dark')
                if not info or not info.get('rect'): print(f'{what} {theme} {N}: no panel'); bad += 1; continue
                x, y, w, h = info['rect']; D = 3; cx, cy = int((x + w / 2) * D), int((y + h / 2) * D)
                box = [im.getpixel((i, j))[0] for i in range(cx - 20, cx + 20) for j in range(cy - 20, cy + 20)]; mean = statistics.mean(box); sd = statistics.pstdev(box)
                col = [im.getpixel((cx, j))[0] for j in range(int(y * D) + 3, int((y + h) * D) - 3, max(1, int(h * D / 20)))]; row = [im.getpixel((i, cy))[0] for i in range(int(x * D) + 3, int((x + w) * D) - 3, max(1, int(w * D / 20)))]
                want = predict(N / 255, info['keys'], info['keys'].get('Dimming', 0) if what == 'alert' else 0)
                print(f"{what} {theme} {N}: centre {mean:.1f} want {want:.1f} Δ {mean - want:+.2f} sd {sd:.2f} | col {col} | row {row}" + ('' if what == 'alert' else f" | full chain {info.get('full')}"))
    sys.exit(1 if bad else 0)
