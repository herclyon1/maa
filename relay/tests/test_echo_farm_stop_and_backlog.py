"""The red button ends an echo farm, and a farm order that waited out its deadline is refused.

Both from the 0.4.4 review (BOARD/0.4.4-审查/指令与显示.txt):
* :38 estop stopped AUTO-MAS and killed processes only. The farm's record stayed,
  and echofarm.tick relaunched OK-WW minutes later (from the second try with the
  game), farming until the deadline and holding off the shutdown.
* :31 a 「刷到 08:30」 pressed while the machine was off waited in the mailbox; read
  against the boot time it rolled to the next day's 08:30 - a whole day of farming.
"""
import json
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for name in ("win32serviceutil", "win32service", "win32event", "win32api",
             "win32con", "win32file", "servicemanager", "win32process",
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(name, _Stub(name))

from ark_relay import commands, echofarm            # noqa: E402
from ark_relay.config import SERVER_TZ               # noqa: E402
import boot_stages                                   # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


ORIGINAL = {"Teleport to Boss": "Weekly Challenge", "Which Boss Challenge to Teleport": 1,
            "Repeat Farm Count": 3}


class Cfg:
    def __init__(self, root):
        self.okww_dir = root
        self.state_dir = root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)


def fresh():
    root = tmpdir()
    d = root.joinpath(*echofarm._WORKING, "configs")
    d.mkdir(parents=True)
    (d / "FarmEchoTask.json").write_text(json.dumps(ORIGINAL), encoding="utf-8")
    return Cfg(root)


launched = []
echofarm._launch = lambda: (launched.append("launch"), (True, ""))[1]
echofarm.stop_okww = lambda: launched.append("stop")
echofarm.NO_CLAIM = str(tmpdir() / "no-claim")


def at(d, hh, mm):
    return datetime(2026, 10, d, hh, mm, tzinfo=SERVER_TZ)


print("\n[关机时 22:00 按「刷到 08:30」、第二天 08:45 开机才收到：不开刷]")
c, launched[:] = fresh(), []
ok, msg = echofarm.start(c, 1, "08:30", "天傀劫煞", now=at(6, 8, 45), sent=at(5, 22, 0))
check("拒收", ok, False)
check("没开 OK-WW", launched, [])
check("没留刷声骸记录", echofarm.current(c.state_dir), {})
check("配置没动", json.loads(echofarm._cfg_path(c.okww_dir).read_text(encoding="utf-8")), ORIGINAL)
check("说了是几点发的、已经过了", "10-05 22:00 发的" in msg and "已经过了 08:30" in msg)

print("\n[同一条、08:00 开机就收到：照常刷到当天 08:30，不顺延到后天]")
c, launched[:] = fresh(), []
ok, msg = echofarm.start(c, 1, "08:30", "天傀劫煞", now=at(6, 8, 0), sent=at(5, 22, 0))
check("开刷了", ok)
check("刷到 10-06 08:30", echofarm.current(c.state_dir).get("until"), "2026-10-06 08:30")

print("\n[在线按的（几秒前发出）：和以前一样]")
c, launched[:] = fresh(), []
ok, _ = echofarm.start(c, 1, "21:00", "天傀劫煞", now=at(5, 20, 0), sent=at(5, 20, 0) - timedelta(seconds=3))
check("开刷了", ok)
check("刷到当天 21:00", echofarm.current(c.state_dir).get("until"), "2026-10-05 21:00")
c, launched[:] = fresh(), []
ok, _ = echofarm.start(c, 1, "08:30", "天傀劫煞", now=at(5, 20, 0))
check("不知道发出时刻的：按现在算，顺延到明天", (ok, echofarm.current(c.state_dir).get("until")),
      (True, "2026-10-06 08:30"))

print("\n[指令带来的发出时刻（unix 秒）交给 echofarm.start]")
got = {}
real_start = echofarm.start
echofarm.start = lambda cfg, boss, until, name, sent=None, **kw: (got.update(sent=sent), (True, ""))[1]
commands.apply_command({"action": "echo_farm", "confirmed": True, "boss": 1, "until": "08:30",
                        "sent": int(at(5, 22, 0).timestamp())})
check("换成了机器时区的时刻", got.get("sent"), at(5, 22, 0))
commands.apply_command({"action": "echo_farm", "confirmed": True, "boss": 1, "until": "08:30"})
check("没带就是 None", got.get("sent"), None)
echofarm.start = real_start


class Eng:
    def scripts_running(self):
        return False


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, kw.get("alert", False)))
        return False


class Log:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def exception(self, *a, **k): pass


print("\n[开机读到的 echo_farm：发出时刻按 ntfy 收到的时间带进去，回执失败不报警]")
bodies = []
real_apply = commands.apply_command
commands.apply_command = lambda body: (bodies.append(dict(body)), (False, "过期了"))[1]
notes = Notes()
fn = boot_stages._make_phone_cmd(Eng(), notes, Log(), types.SimpleNamespace(watch=lambda: None),
                                 lambda *_: None, tmpdir())
fn({"action": "echo_farm", "boss": 1, "until": "08:30",
    "_meta": {"sent": 1759672800, "ntfy_time": 1759672805, "via": "backlog"}})
fn({"action": "echo_farm", "boss": 1, "until": "08:30", "_meta": {"sent": 1759672800, "via": "backlog"}})
fn({"action": "set_stage", "value": "1-7", "_meta": {"sent": 1759672800, "ntfy_time": 1759672805}})
commands.apply_command = real_apply
check("ntfy 的时间优先（手机钟可能快几分钟）", bodies[0].get("sent"), 1759672805)
check("没有 ntfy 时间就用手机的", bodies[1].get("sent"), 1759672800)
check("别的指令不加这个字段", "sent" in bodies[2], False)
check("失败回执不报警（不进群）", [a for _, a in notes.sent], [False, False, False])

print("\n[刷声骸进行中按「停止一切」：刷声骸一起结束，tick 不再把它开起来]")
c, launched[:] = fresh(), []
os.environ["ARK_OKWW_DIR"] = str(c.okww_dir)
echofarm.start(c, 1, "23:00", "天傀劫煞", now=at(5, 20, 0))
commands._estop_stop_via_mas = lambda: ["早班"]
commands._estop_kill = lambda: None
commands._estop_alive = lambda: []
commands._estop_live_tasks = lambda: []
launched[:] = []
ok, msg = commands.estop(sleep=lambda n: None, state_dir=c.state_dir)
check("说停了", ok)
check("回执写了刷声骸也停了", "刷声骸也停了：刷天傀劫煞结束" in msg)
check("刷声骸记录没了", echofarm.current(c.state_dir), {})
check("配置还原了", json.loads(echofarm._cfg_path(c.okww_dir).read_text(encoding="utf-8")), ORIGINAL)
check("之后的 tick 不再开 OK-WW", (echofarm.tick(c, now=at(5, 20, 30)), launched), ("", ["stop"]))

print("\n[没在刷声骸：回执和以前一样]")
ok, msg = commands.estop(sleep=lambda n: None, state_dir=c.state_dir)
check("没提刷声骸", (ok, "刷声骸" in msg), (True, False))

print("\n[结束刷声骸出错：不说「已停一切」]")
real_finish = echofarm.finish
echofarm.finish = lambda cfg, why: (_ for _ in ()).throw(OSError("磁盘满"))
ok, msg = commands.estop(sleep=lambda n: None, state_dir=c.state_dir)
echofarm.finish = real_finish
check("算没停干净", ok, False)
check("说了刷声骸没结束、怎么办", "刷声骸没结束" in msg and "结束刷声骸" in msg)

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
