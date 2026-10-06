"""collect_watch: failed gathering routes are read from the live maafw.log, and the
master is never narrowed (the user, 2026-10-06: 「我开的任务是谁说要关的」);
lists an older relay version narrowed go back at the next attempt's start.

Fixture: the real MaaFW event lines of 2026-09-14 attempt 3 (10:53-11:20),
where Route10 failed and AUTO-MAS retried all 17 routes at 11:21:43.
"""
import json
import logging
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


# Every 「目录监听掉了」 the watcher logs while the test runs. It must stay empty:
# the line Windows CI showed after the result line (2026-10-07) is the watcher
# seeing its directory removed by _tmp's cleanup at exit, not a drop mid-test.
class _Drops(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


_drops = _Drops()
logging.getLogger("ark.watch").addHandler(_drops)


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


FULL = (["Route4", "Route5", "Route6", "Route10", "Route13", "Route14"],
        ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"])


def _old_narrowing(cfg, f, kept):
    """What a relay before 2026-10-06 left behind: the master narrowed to `kept`, the original in narrow.json."""
    doc = json.loads(f.read_text(encoding="utf-8"))
    ov = doc["instances"][0]["tasks"][0]["optionValues"]
    saved = {"AutoCollectValleyIVRareRoutes": list(FULL[0]), "AutoCollectWulingRareRoutes": list(FULL[1])}
    ov["AutoCollectValleyIVRareRoutes"]["caseNames"] = list(kept[0])
    ov["AutoCollectWulingRareRoutes"]["caseNames"] = list(kept[1])
    f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    nf = Path(cfg.state_dir) / "collect-retry" / "narrow.json"
    nf.parent.mkdir(parents=True, exist_ok=True)
    nf.write_text(json.dumps({"run_id": "11:20:22 自动采集失败", "at": "2026-09-14T11:20:22+08:00",
                              "lists": saved}, ensure_ascii=False), encoding="utf-8")
    return nf


print("[真实日志：Route10Failed 出现了，母本一条路线都不动，只记下来]")
cfg, f, n = _setup()
w = collect_watch.Watcher(cfg, n)
before_failed = [ln for ln in LINES if "Route10Failed" not in ln and "Tasker.Task.Failed" not in ln]
check("走到失败之前没有动作", w.feed("\n".join(before_failed)), [])
failed_lines = [ln for ln in LINES if "Route10Failed" in ln or "Tasker.Task.Failed" in ln]
check("失败了也没有动作", w.feed("\n".join(failed_lines)), [])
check("母本原样（用户选的路线一条不关）", _lists(f), FULL)
check("没有收窄记录", (Path(cfg.state_dir) / "collect-retry" / "narrow.json").exists(), False)
check("记住了没走通的", w.failed, ["Route10"])
check("不单独推送（失败从记录和补跑那里报）", n.sent, [])
check("收窄的函数没了", (hasattr(collect_watch.Watcher, "_narrow"), hasattr(__import__("ark_relay.collect_retry").collect_retry, "narrow_master")),
      (False, False))

print("\n[两条路线先后失败：都记下，母本还是不动]")
cfg, f, n = _setup()
w = collect_watch.Watcher(cfg, n)
r10 = next(ln for ln in LINES if "Route10Failed" in ln)
w.feed(r10)
w.feed(r10.replace("Route10", "Route15"))
check("两条都记下", w.failed, ["Route10", "Route15"])
check("母本不动", _lists(f), FULL)
start_line = next(ln for ln in LINES if "Tasker.Task.Starting" in ln)
w.feed(start_line)
check("新一趟开始就清空", w.failed, [])

print("\n[旧版本收窄过的母本：新一趟（Tasker.Task.Starting）一开始就改回]")
cfg, f, n = _setup()
nf = _old_narrowing(cfg, f, (["Route10"], []))
w = collect_watch.Watcher(cfg, n)
notes = w.feed(start_line.replace("10:53:13", "11:21:43"))
check("改回有说明", any("改回原来的 12 条" in x for x in notes), True)
check("母本改回", _lists(f), FULL)
check("收窄记录删掉", nf.exists(), False)
check("没有记录时开始一趟什么都不做", w.feed(start_line), [])

print("\n[只认调度器自己那一行；agent 回显的同一事件不算第二次]")
cfg, f, n = _setup()
w = collect_watch.Watcher(cfg, n)
echo = [ln for ln in LINES if "Route10Failed" in ln]
check("样本里事件被回显了两次", len(echo) >= 2 and all("EventDispatcher::notify" in x for x in echo), True)
w.feed("\n".join(echo))
check("只记一次、不推送", (w.failed, n.sent), (["Route10"], []))

print("\n[读文件：增量读、跟着轮转走]")
cfg, f, n = _setup()
w = collect_watch.Watcher(cfg, n)
lp = w.log_path()
lp.write_text("\n".join(before_failed) + "\n", encoding="utf-8")
check("第一次读完没有动作", w.poll(), [])
check("偏移量走到文件尾", w._offset, lp.stat().st_size)
with lp.open("a", encoding="utf-8") as fh:
    fh.write(failed_lines[0][:100])          # a half-written line
w.poll()
check("半行不算", w.failed, [])
with lp.open("a", encoding="utf-8") as fh:
    fh.write(failed_lines[0][100:] + "\n")
w.poll()
check("补完那半行就认出失败", w.failed, ["Route10"])
# Rotation: MaaFW renames the file and starts over; the retry's Task.Starting
# lands in the new one.
_old_narrowing(cfg, f, (["Route10"], []))
lp.rename(lp.parent / "maafw.bak.2026.09.14-11.20.24.685.log")
lp.write_text(start_line.replace("10:53:13", "11:21:43") + "\n", encoding="utf-8")
notes = w.poll()
check("轮转后读新文件，新一趟开始就改回旧收窄", _lists(f), FULL)
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
w.poll()
check("从旧文件尾巴读到失败", w.failed, ["Route10"])
check("母本还是不动", _lists(f), FULL)

print("\n[线程：目录一有变化就读，不用定时]")
cfg, f, n = _setup()
nf = _old_narrowing(cfg, f, (["Route10"], []))
lp = Path(cfg.maaend_dir) / "debug" / "maafw.log"
lp.write_text("\n".join(before_failed) + "\n", encoding="utf-8")
check("挂上了", collect_watch.start(cfg, n), True)
with lp.open("a", encoding="utf-8") as fh:
    fh.write("\n".join(failed_lines) + "\n" + start_line.replace("10:53:13", "11:21:43") + "\n")
# On Windows FILE_NOTIFY_CHANGE_LAST_WRITE fires for the append itself; the Mac
# kqueue in watch.py only sees the directory entry, so poke it with a new file.
(lp.parent / "mxu-agent-0-1.log").write_text("x", encoding="utf-8")
deadline = time.monotonic() + 8
while time.monotonic() < deadline and nf.exists():
    time.sleep(0.2)
check("几秒内旧收窄就改回了", (_lists(f), nf.exists()), (FULL, False))

print("\n[没有 MaaEnd 目录就不挂监听，并说明]")
class _NoDir:
    maaend_dir = None
    state_dir = str(tmpdir())   # collect_watch.start prunes old task shots there first
check("没目录返回 False", collect_watch.start(_NoDir, _N()), False)

check("目录监听在测试期间没掉过", _drops.msgs, [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
