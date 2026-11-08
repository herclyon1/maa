"""An AUTO-MAS install the first try could not see land, found landed by the second try
(audit 11-08 A-20; dispatch relay-opt-round4-1108 R4-04; preupdate_automas.run_automas `carry`).

Before: the first try clicked install, the backend took longer than MAS_INSTALL_WAIT_SECONDS
to come back on the new version, so it left a note and returned 「…（安装已启动，还没确认装成）」.
boot_stages._once_more ran it again; the backend now said the new version, the check said
nothing to update, the try returned "" - and `step(problems) or out` kept the first try's
「还没确认装成」, and after_update (the settings check after an update) never ran.

Pinned here, through the real _once_more with AUTO-MAS's HTTP faked:
* second try finds the first try's version running: 「AUTO-MAS 已更新：旧 → 新」, after_update
  called once with the new version, no note left, one recovered WARNING (daily report only);
* second try finds the old version still running: the first try's text and note stand, no
  after_update;
* without `carry` (any other caller): as before.
"""
import logging
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boot_stages
from ark_relay.features.alarm import errwatch
from ark_relay.features.preupdate import preupdate_automas as P

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


class Rows(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.rows = []

    def emit(self, record):
        self.rows.append((record.levelname, bool(getattr(record, errwatch.RECOVERED, False)), record.getMessage()))


class Machine:
    """AUTO-MAS v1 with v2 on offer. The install's own wait never sees v2; when `lands`, the
    backend reports v2 from the end of that wait on (the 155 s case), else stays on v1."""

    def __init__(self, lands):
        self.lands, self.installed, self.waited = lands, False, False

    def live(self):
        return "v2" if self.lands and self.installed and self.waited else "v1"

    def wait(self, want, deadline, stopping=None):
        self.waited = self.installed
        return "v1"

    def post(self, path, body=None):
        if path == "/api/update/install":
            self.installed = True
        if path == "/api/update/check":
            return {"code": 200, "if_need_update": self.live() != "v2", "latest_version": "v2"}
        return {"code": 200}


saved = (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version,
         boot_stages._seconds_to_next_queue, boot_stages._stop_requested)
rows = Rows()
lg = logging.getLogger("ark.test_preupdate_automas_carry")
lg.handlers[:] = [rows]
lg.setLevel(logging.DEBUG)
lg.propagate = False


def run(lands, carry=True):
    m = Machine(lands)
    P._mas_post, P._live_version = m.post, m.live
    P._automas_version = lambda root: "v1"
    P._wait_for_package = lambda root, deadline, stopping=None: Path("AUTO-MAS-v2.zip")
    P._wait_for_version = m.wait
    boot_stages._seconds_to_next_queue = lambda d, now: 3600.0
    boot_stages._stop_requested = lambda: False
    rows.rows.clear()
    problems, after = [], []
    box: dict = {}
    out = boot_stages._once_more(types.SimpleNamespace(automas_dir="x"), lg, "AUTO-MAS", 1.0, problems,
                                 lambda problems: P.run_automas(Path("x"), budget_s=1.0, problems=problems,
                                                                after_update=after.append,
                                                                **({"carry": box} if carry else {})))
    return out, problems, after, [(lv, r) for lv, r, _ in rows.rows if lv != "INFO"]


try:
    print("[第一次点了安装、没等到新版；第二次看到已经是新版：说已更新，补做更新后的核对]")
    out, problems, after, logged = run(lands=True)
    check("说已更新（旧 → 新）", out, "AUTO-MAS 已更新：v1 → v2")
    check("更新后的核对补做了一次，用的是新版本号", after, ["v2"])
    check("没有留下「没确认装成」的问题", problems, [])
    check("一条标自己好了的 WARNING（只进日报）", logged, [("WARNING", True)])

    print("\n[第二次还是旧版：第一次的话照旧，不做核对]")
    out, problems, after, _ = run(lands=False)
    check("照旧说「还没确认装成」", out.endswith("（安装已启动，还没确认装成）"), True)
    check("没做核对", after, [])
    check("留着没确认的问题", len(problems), 1)

    print("\n[不带 carry 的调用：和以前一样]")
    out, problems, after, _ = run(lands=True, carry=False)
    check("第二次没东西可说，第一次的话留着", out.endswith("（安装已启动，还没确认装成）"), True)
    check("不补核对", after, [])
finally:
    (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version,
     boot_stages._seconds_to_next_queue, boot_stages._stop_requested) = saved

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
