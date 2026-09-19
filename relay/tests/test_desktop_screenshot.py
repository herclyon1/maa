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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
