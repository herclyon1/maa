"""collect_watch: the gathering routes narrow from the live maafw.log, not from records.

Fixture: the real MaaFW event lines of 2026-09-14 attempt 3 (10:53-11:20),
where Route10 failed and AUTO-MAS retried all 17 routes at 11:21:43.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import collect_watch

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


FIX = Path(__file__).resolve().parent / "fixtures" / "collect-watch-2026-09-14" / "maafw-attempt3.log"
LINES = FIX.read_text(encoding="utf-8").splitlines()


def _master(root):
    mdir = root / "data" / "abc" / "Default" / "ConfigFile"
    mdir.mkdir(parents=True)
    doc = {"instances": [{"tasks": [{"taskName": "AutoCollect", "enabled": True, "optionValues": {
        "AutoCollectSchedule": {"type": "checkbox", "caseNames": ["AutoCollectScheduleMonday"]},
        "AutoCollectValleyIVRareRoutes": {"type": "checkbox", "caseNames": ["Route4", "Route5", "Route6", "Route10", "Route13", "Route14"]},
        "AutoCollectWulingRareRoutes": {"type": "checkbox", "caseNames": ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"]},
        "AutoCollectMode": {"type": "select", "caseName": "Always"}}}]}]}
    (mdir / "mxu-MaaEnd.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return mdir / "mxu-MaaEnd.json"


def _lists(f):
    ov = json.loads(f.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["optionValues"]
    return ov["AutoCollectValleyIVRareRoutes"]["caseNames"], ov["AutoCollectWulingRareRoutes"]["caseNames"]


class _N:
    def __init__(self):
        self.sent = []

    def send(self, title, body, **kw):
        self.sent.append((title, body))


def _setup():
    root = tmpdir()
    f = _master(root)
    maaend = root / "MaaEnd"
    (maaend / "debug").mkdir(parents=True)
    (maaend / "locales" / "interface").mkdir(parents=True)
    (maaend / "locales" / "interface" / "zh_cn.json").write_text(json.dumps(
        {"option.AutoCollectRoute10.label": "路线10：<b>晶簇</b>"}, ensure_ascii=False), encoding="utf-8")

    class Cfg:
        automas_dir = root
        state_dir = root / "state"
        maaend_dir = maaend
    Cfg.state_dir.mkdir()
    return Cfg, f, _N()


print("[真实日志：Route10Failed 一出现母本就只剩 Route10]")
cfg, f, n = _setup()
w = collect_watch.Watcher(cfg, n)
before_failed = [ln for ln in LINES if "Route10Failed" not in ln and "Tasker.Task.Failed" not in ln]
check("走到失败之前不动母本", w.feed("\n".join(before_failed)), [])
check("母本原样", _lists(f), (["Route4", "Route5", "Route6", "Route10", "Route13", "Route14"],
                            ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"]))
failed_lines = [ln for ln in LINES if "Route10Failed" in ln or "Tasker.Task.Failed" in ln]
notes = w.feed("\n".join(failed_lines))
check("收窄有说明", any("只留 1/12" in x for x in notes), True)
check("母本只剩 Route10", _lists(f), (["Route10"], []))
check("记住了没走通的", w.failed, ["Route10"])
check("通知点名中文路线名（去掉标签）", n.sent and "路线10：晶簇" in n.sent[0][1], True)
check("同一条只通知一次", len(n.sent), 1)

print("\n[重跑一开始（Tasker.Task.Starting）就改回原来的路线]")
start_line = next(ln for ln in LINES if "Tasker.Task.Starting" in ln)
notes = w.feed(start_line.replace("10:53:13", "11:21:43"))
check("改回有说明", any("改回原来的 12 条" in x for x in notes), True)
check("母本改回", _lists(f), (["Route4", "Route5", "Route6", "Route10", "Route13", "Route14"],
                            ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"]))
check("记录清空", (w.failed, w.narrowed), ([], False))

print("\n[两条路线先后失败：第二条要加进去，不是把第一条挤掉]")
cfg, f, n = _setup()
w = collect_watch.Watcher(cfg, n)
r10 = next(ln for ln in LINES if "Route10Failed" in ln)
w.feed(r10)
w.feed(r10.replace("Route10", "Route15"))
check("两条都留", _lists(f), (["Route10"], ["Route15"]))
check("两条通知", len(n.sent), 2)
w.feed(start_line)
check("改回全部", _lists(f), (["Route4", "Route5", "Route6", "Route10", "Route13", "Route14"],
                            ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"]))

print("\n[只认调度器自己那一行；agent 回显的同一事件不算第二次]")
cfg, f, n = _setup()
w = collect_watch.Watcher(cfg, n)
echo = [ln for ln in LINES if "Route10Failed" in ln]
check("样本里事件被回显了两次", len(echo) >= 2 and all("EventDispatcher::notify" in x for x in echo), True)
w.feed("\n".join(echo))
check("只收窄一次、只通知一次", (w.failed, len(n.sent)), (["Route10"], 1))

print("\n[读文件：增量读、跟着轮转走]")
cfg, f, n = _setup()
w = collect_watch.Watcher(cfg, n)
lp = w.log_path()
lp.write_text("\n".join(before_failed) + "\n", encoding="utf-8")
check("第一次读完没有动作", w.poll(), [])
check("偏移量走到文件尾", w._offset, lp.stat().st_size)
with lp.open("a", encoding="utf-8") as fh:
    fh.write(failed_lines[0][:100])          # a half-written line
check("半行不算", w.poll(), [])
with lp.open("a", encoding="utf-8") as fh:
    fh.write(failed_lines[0][100:] + "\n")
notes = w.poll()
check("补完那半行就收窄", _lists(f), (["Route10"], []))
# Rotation: MaaFW renames the file and starts over; the retry's Task.Starting
# lands in the new one.
lp.rename(lp.parent / "maafw.bak.2026.09.14-11.20.24.685.log")
lp.write_text(start_line.replace("10:53:13", "11:21:43") + "\n", encoding="utf-8")
notes = w.poll()
check("轮转后读新文件，重跑开始就改回", _lists(f)[1], ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"])
check("偏移量重置到新文件", w._offset, lp.stat().st_size)

print("\n[09-14 的时序：Failed 写进旧文件两秒后就轮转，尾巴要从 .bak 里补读]")
cfg, f, n = _setup()
w = collect_watch.Watcher(cfg, n)
lp = w.log_path()
lp.write_text("\n".join(before_failed) + "\n", encoding="utf-8")
w.poll()
with lp.open("a", encoding="utf-8") as fh:
    fh.write("\n".join(failed_lines) + "\n")
lp.rename(lp.parent / "maafw.bak.2026.09.14-11.20.24.685.log")     # not polled in between
lp.write_text("x\n", encoding="utf-8")
notes = w.poll()
check("从旧文件尾巴读到失败并收窄", (_lists(f), len(n.sent)), ((["Route10"], []), 1))
with lp.open("a", encoding="utf-8") as fh:
    fh.write(start_line.replace("10:53:13", "11:21:43") + "\n")
w.poll()
check("新文件里的重跑开始就改回", _lists(f)[0], ["Route4", "Route5", "Route6", "Route10", "Route13", "Route14"])

print("\n[线程：目录一有变化就读，不用定时]")
cfg, f, n = _setup()
lp = Path(cfg.maaend_dir) / "debug" / "maafw.log"
lp.write_text("\n".join(before_failed) + "\n", encoding="utf-8")
check("挂上了", collect_watch.start(cfg, n), True)
with lp.open("a", encoding="utf-8") as fh:
    fh.write("\n".join(failed_lines) + "\n")
# On Windows FILE_NOTIFY_CHANGE_LAST_WRITE fires for the append itself; the Mac
# kqueue in watch.py only sees the directory entry, so poke it with a new file.
(lp.parent / "mxu-agent-0-1.log").write_text("x", encoding="utf-8")
deadline = time.monotonic() + 8
while time.monotonic() < deadline and _lists(f)[0] != ["Route10"]:
    time.sleep(0.2)
check("几秒内母本就收窄了", _lists(f), (["Route10"], []))

print("\n[没有 MaaEnd 目录就不挂监听，并说明]")
class _NoDir:
    maaend_dir = None
check("没目录返回 False", collect_watch.start(_NoDir, _N()), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
