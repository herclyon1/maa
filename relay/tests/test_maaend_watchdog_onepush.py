"""One MaaEnd hang the watchdog ends, one group message (验收 2026-10-11 22:5x).

Watchdog._end sent the ⚠️ group alarm for a crash / stall / plugin-gone, or a kill
that did not take, and logged the 「MaaEnd 卡死」 WARNING right before it, which
errwatch pushed to the group too: one event, two group messages (three for a crash: the crash line itself was a
WARNING too). The crash line is INFO now (the kill's push names the crash and
its code), and the 「卡死」 WARNING now
follows the send and carries errwatch.group_pushed, so it stays out of the group
only when the ⚠️ really reached the group robot; a refused send, or one that fell
back to Server酱, leaves the WARNING to errwatch and the fault still reaches the
group once.

Replayed with test_maaend_watchdog.py's shapes (the 2026-10-01 15:30:03 go-service
crash, maafw.log standing still 10 minutes, go-service gone twice 60 s apart) and
errwatch attached (its group robot refuses, so what it would push stays readable
in pending()). Group messages per event, before -> after (A/B of the code before
and after this change on these shapes): crash 3 -> 1, stall 2 -> 1, plugin gone
2 -> 1, kill that did not take 4 -> 2 - the second is machine check #31's FAIL, a
check of its own pushed every time it is judged (docs/NOTIFICATIONS.md 🔬 row).
"""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import texts  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402
from ark_relay.features.run import maaend_watchdog  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


CRASH_LINE = "Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456"
RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
MAAEND_PID = 21260
ALL_UP = [("System", 4), ("Endfield.exe", 18800), ("MaaEnd.exe", MAAEND_PID),
          ("go-service.exe", 21932), ("cpp-algo.exe", 21940)]
NO_GO = [p for p in ALL_UP if p[0] != "go-service.exe"]
ROBOT = "企业微信机器人"


class Notes:
    """The relay's notifier: `refuse` returns errors, `fallback` delivers by Server酱 instead of the robot."""

    def __init__(self, refuse=False, fallback=False):
        self.sent, self.refuse, self.fallback = [], refuse, fallback

    def send(self, title, body="", **kw):
        self.sent.append(title)
        return ["企业微信机器人：拒收", "Server酱：拒收"] if self.refuse else []

    def went_to_group(self):
        return not self.fallback


class Refuses:
    """errwatch's own notifier: the group refuses, so what it queues stays queued (readable)."""

    def send_group(self, title, body):
        return [f"{ROBOT}：拒收"]

    def send(self, title, body, **kw):
        return ["拒收"]


ARK_LOGGER = logging.getLogger(errwatch.ARK)


class Rig:
    def __init__(self, notes, kill_ok=True, state_dir=None):
        self.t, self.lines, self.stamp = 1000.0, 0, "2026-10-01 15:20:00"
        self.procs, self.kill_ok, self.killed, self.notes = list(ALL_UP), kill_ok, [], notes
        self.debug = tmpdir() / "debug"
        self.debug.mkdir()
        self.stderr = self.debug / "go-service.stderr.log"
        self.stderr.write_text("", encoding="utf-8")
        agent = str(self.debug.parent / "agent")
        paths = {21932: os.path.join(agent, "go-service.exe"), 21940: os.path.join(agent, "cpp-algo.exe")}
        self.dog = maaend_watchdog.Watchdog(
            notes, self.debug, clock=lambda: self.t, snapshot=lambda: RUNNING,
            processes=lambda: list(self.procs), kill=self._kill, plugin_paths=lambda: paths,
            active=True, state_dir=state_dir)
        self.h = errwatch.ErrorKindAlert(Refuses(), state_dir=tmpdir() / "ew", known={}, retry=(3600.0,),
                                         fallback_after=1e9)
        ARK_LOGGER.addHandler(self.h)

    def _kill(self, pid, image):
        self.killed.append(pid)
        if not self.kill_ok:
            return False, "退出码 128"
        self.procs = [p for p in self.procs if p[1] != pid]
        return True, ""

    def step(self, seconds, new_lines=0, stamp=None):
        self.t += seconds
        self.lines += new_lines
        self.stamp = stamp or self.stamp
        return self.dog.tick(self.lines, self.stamp)

    def run_for(self, seconds, every=60, **kw):
        for _ in range(int(seconds // every)):
            self.step(every, **kw)

    def group(self):
        """Everything that went or would go to the group: the watchdog's own sends, then errwatch's queue."""
        return list(self.notes.sent) + [str(x.get("line"))[:40] for x in self.h.pending()]

    def done(self):
        ARK_LOGGER.removeHandler(self.h)
        self.h.close()


def crash(r):
    r.run_for(240, new_lines=40)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60)


print("[2026-10-01 go-service crash -> MaaEnd ended: one group message, the ⚠️]")
r = Rig(Notes())
crash(r)
check("ended MaaEnd and its plugins", r.killed, [MAAEND_PID, 21932, 21940])
check("group: the ⚠️ only", r.group(), [texts.MAAEND_STUCK_KILLED])
r.run_for(600)
check("nothing more for the same PID", r.group(), [texts.MAAEND_STUCK_KILLED])
r.done()

print("\n[maafw.log stood still 10 minutes -> ended: one group message]")
r = Rig(Notes())
r.run_for(300, new_lines=50, stamp="2026-10-01 15:30:03")
r.run_for(600)
check("ended", r.killed[:1], [MAAEND_PID])
check("group: the ⚠️ only", r.group(), [texts.MAAEND_STUCK_KILLED])
r.done()

print("\n[go-service gone twice 60 s apart -> ended: one group message]")
r = Rig(Notes())
r.run_for(240, new_lines=20)
r.procs = NO_GO
r.step(60, new_lines=5)
r.step(60, new_lines=5)
check("ended MaaEnd and cpp-algo", r.killed, [MAAEND_PID, 21940])
check("group: the ⚠️ only", r.group(), [texts.MAAEND_STUCK_KILLED])
r.done()

print("\n[the kill did not take -> the ⚠️, plus machine check #31's FAIL (a check of its own)]")
r = Rig(Notes(), kill_ok=False, state_dir=tmpdir() / "relaystate")
crash(r)
check("group: ⚠️ 没能结束 and 🔬 #31, no 「卡死」 WARNING",
      [t[:12] for t in r.group()], [texts.MAAEND_STUCK_KILL_FAILED[:12], "🔬 上机核对没过：#31"])
r.done()

print("\n[the ⚠️ send was refused -> the WARNING is pushed instead: the fault still reaches the group once]")
r = Rig(Notes(refuse=True))
crash(r)
check("errwatch queues the 「卡死」 WARNING", [x[:9] for x in r.group()[1:]], ["MaaEnd 卡死"])
r.done()

print("\n[the ⚠️ fell back to Server酱 -> the WARNING goes to the group]")
r = Rig(Notes(fallback=True))
crash(r)
check("errwatch queues the 「卡死」 WARNING", [x[:9] for x in r.group()[1:]], ["MaaEnd 卡死"])
r.done()

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
