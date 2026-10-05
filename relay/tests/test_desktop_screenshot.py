"""Desktop.screenshot(): one picture of the real desktop through the interactive
agent, None when the agent does not come back with a file. No Windows here:
the spawn is faked to behave like the agent (write the result JSON, drop the
png the request names)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.desktop import Desktop
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def agent(write_png=True, ok=True):
    """A fake interactive session: reads the request the way agent.ps1 does."""
    seen = []

    def spawn(exe, cwd, args):
        req, res = Path(args[-2]), Path(args[-1])
        r = json.loads(req.read_text(encoding="utf-8"))
        seen.append(r)
        if write_png:
            Path(r["shot"]).write_bytes(b"\x89PNG fake")
        res.write_text(json.dumps({"ok": ok, "log": ["shot"], "ocr": [], "clicked": []}), encoding="utf-8")
        return True
    spawn.seen = seen
    return spawn


print("[能截到：返回 png 路径，请求里只有一个 shot 动作、不做 OCR]")
sp = agent()
d = Desktop(tmpdir() / "state", spawn=sp, timeout=5)
shot = d.screenshot()
check("拿到文件", shot is not None and shot.is_file(), True)
check("文件名是 shot-<id>.png", shot.name.startswith("shot-") and shot.suffix == ".png", True)
check("请求只有 shot 一个动作", sp.seen[0]["actions"], [{"act": "shot"}])
check("请求不带 focus（不抢前台）", sp.seen[0]["focus"], None)

print("\n[助手回来了但没写图：None]")
d2 = Desktop(tmpdir() / "state", spawn=agent(write_png=False), timeout=5)
check("None", d2.screenshot(), None)

print("\n[助手说失败：None，即使有图]")
d3 = Desktop(tmpdir() / "state", spawn=agent(ok=False), timeout=5)
check("None", d3.screenshot(), None)

print("\n[助手起不来：None，不抛]")
d4 = Desktop(tmpdir() / "state", spawn=lambda *a: False, timeout=5)
check("None", d4.screenshot(), None)

print("\n[读图文件：请求只有 ocrfile 一个动作，行原样回来；失败 None]")
seen = []


def ocr_agent(exe, cwd, args):
    req, res = Path(args[-2]), Path(args[-1])
    seen.append(json.loads(req.read_text(encoding="utf-8")))
    res.write_text(json.dumps({"ok": True, "log": ["ocrfile 1 行"], "clicked": [],
                               "ocr": [{"text": "10.22~11.11", "x": 609, "y": 172, "w": 91, "h": 22}]},
                              ensure_ascii=False), encoding="utf-8")
    return True


d5 = Desktop(tmpdir() / "state", spawn=ocr_agent, timeout=5)
img = tmpdir() / "img.png"
got = d5.read_file(img)
check("请求", seen[0]["actions"], [{"act": "ocrfile", "path": str(img)}])
check("行", [(x.text, x.x, x.y) for x in got or []], [("10.22~11.11", 609, 172)])
check("助手起不来：None", Desktop(tmpdir() / "state", spawn=lambda *a: False, timeout=5).read_file(img), None)

print("\n[two threads (task pictures and a launcher OCR): one agent at a time]")
import threading
import time
live, peak = [0], [0]


def slow_spawn(exe, cwd, args):
    live[0] += 1
    peak[0] = max(peak[0], live[0])
    time.sleep(0.3)
    live[0] -= 1
    return False          # the agent "did not come back"; only the overlap matters here


ds = [Desktop(tmpdir() / "state", spawn=slow_spawn, timeout=2) for _ in range(2)]
ts = [threading.Thread(target=d.screenshot) for d in ds]
for t in ts:
    t.start()
for t in ts:
    t.join(10)
check("never two agents at once", peak[0], 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
