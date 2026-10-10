"""Failures the relay used to keep out of the group now reach it, each time.

The user, 2026-10-06, on errors: report every one to the group robot at once,
however often (「不论多少次什么错误都要发」; his full words are in
docs/NOTIFICATIONS.md, the 🩺 row). Until that day each of these
stayed out of the group: a pushed 「⚠️ OK-WW 补丁有 N 条没贴上」 and a game update
that could not confirm went to Server酱 only; the make-up's log said 「只进日报」
for a MAA failure that is pushed. Pinned here (the other paths are pinned where
they live: test_unresolved, test_makeup, test_unreachable_evidence,
test_maaend_update_after_done, test_maaend_update_restart, test_preupdate_not_alarm,
test_notify_routing, test_channel_down). The self-heal and the attempt AUTO-MAS
restarted at once were pinned here as pushed too, until the user took what
recovered back out of the group at 05:07 that day (「报错后自己好了的，只进日报、不进群。」):
they are pinned in test_recovered_daily_only.

* 「⚠️ OK-WW 补丁有 N 条没贴上」 is sent with alert=True from the engine and from
  both boot stages, and routes to the group; the healthy 「🩹 OK-WW 补丁」 stays log-only;
* the game update after the queue that could not confirm is sent with alert=True;
* the make-up's log no longer says 「只进日报」 for a MAA failure it does not make
  up, and that failure does reach the group.
"""
import json
import logging
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for _name in ("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
              "servicemanager", "win32process", "win32security", "win32ts", "win32profile", "wmi",
              "pythoncom", "win32com", "win32com.client"):
    sys.modules.setdefault(_name, _Stub(_name))

import boot_stages  # noqa: E402
from ark_relay import gameupdate, handle, makeup, okww_overlay, okww_patch, preupdate, texts  # noqa: E402
from ark_relay import engine as eng_mod                                                       # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord                                    # noqa: E402
from ark_relay.ledger import State                                                             # noqa: E402
from ark_relay.notify import route_of                                                        # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def automas_dir(queues) -> Path:
    """An AUTO-MAS config dir: queues = [(name, [times], [script kinds])]."""
    root = tmpdir()
    (root / "config").mkdir()
    paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
    sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
    for k, p in paths.items():
        sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
    qc = {"instances": []}
    for n, (name, times, kinds) in enumerate(queues):
        uid = f"q{n}"
        qc["instances"].append({"uid": uid})
        ts = {"instances": [], **{f"t{i}": {"Info": {"Enabled": True, "Time": t}} for i, t in enumerate(times)}}
        items = {"instances": [], **{f"i{i}": {"Info": {"ScriptId": f"s-{k}"}} for i, k in enumerate(kinds)}}
        qc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                   "SubConfigsInfo": {"TimeSet": ts, "QueueItem": items}}
    (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
    (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
    return root


AUTOMAS = automas_dir([("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]), ("晚班", ["21:30"], ["MAA"])])
DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
D = f"{DAY:%Y-%m-%d}"


def at(hh, mm=0):
    return DAY.replace(hour=hh, minute=mm)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []

    def went_to_group(self):
        return True


class Src:
    def fetch(self, seen):
        return []


def build():
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.automas_dir = AUTOMAS
    cfg.maa_dir = None
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._unfinished_queues = lambda now, entries: []
    e._deferred_update_busy = lambda: False
    e._verify_outcome = lambda r: None
    e._archive_maaend_evidence = lambda r: None
    e._maintenance_today = lambda game: False
    return e


def rec(script, started, ok=False, failed=None, raw=None, transitional=False):
    user = {"MAA": "arknights", "MaaEnd": "endfield", "OK-WW": "wuwa"}[script]
    return RunRecord(run_id=f"{started:%Y-%m-%d}/{user}/{script}-{started:%H-%M-%S}", script=script, user=user,
                     started=started, finished=started + timedelta(minutes=20), ok=ok,
                     failed_tasks=list(failed if failed is not None else ([] if ok or transitional else ["日常"])),
                     raw=dict(raw or {}), transitional=transitional)


def alarms(e):
    return [t for t, _, a in e.notifier.sent if a]


handle._ship_evidence = lambda eng, r: ""
handle._archive_okww_evidence = lambda eng, r: None
handle._weekly_gates = lambda eng, r: None


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


LINES = Lines()
for name in ("ark.handle", "ark.makeup", "ark.engine"):
    logging.getLogger(name).addHandler(LINES)
    logging.getLogger(name).setLevel(logging.DEBUG)


print("[OK-WW patches that did not bind: alert=True from the engine and both boot stages]")
BAD = ["补丁 nowave 贴不上了（OK-WW 改了这段代码）"]
GOOD = ["补丁 nowave 已贴上"]
e = build()
e._scripts_running = lambda: False
real_if_updated = okww_patch.ensure_if_updated
okww_patch.ensure_if_updated = lambda state_dir, okww: list(BAD)
e._patch_okww_if_updated()
okww_patch.ensure_if_updated = real_if_updated
check("engine: sent as an alarm", [(t, a) for t, _, a in e.notifier.sent], [(texts.patches(1, BAD), True)])
check("…the title routes to the group", route_of(texts.patches(1, BAD), alert=True), "group")
check("the healthy title stays log-only even with alert=True", route_of(texts.patches(1, GOOD), alert=True), "log")

LOG = boot_stages.log
CFG = types.SimpleNamespace(automas_dir=None, maaend_dir=Path("maaend"), okww_dir=Path("okww"), state_dir=TMP)
real = (okww_patch.ensure_patches, okww_overlay.install, okww_overlay.write_master_pointer,
        okww_overlay.report_line, okww_overlay.drift_line, preupdate.run_okww)
okww_patch.ensure_patches = lambda okww: list(BAD)
okww_overlay.install = lambda okww: ""
okww_overlay.write_master_pointer = lambda automas_dir: ""
okww_overlay.report_line = lambda: ""
okww_overlay.drift_line = lambda okww, state_dir: ""
preupdate.run_okww = lambda okww, problems=None: ""
notes = Notes()
boot_stages._stage_patch_okww(CFG, notes, LOG)
check("boot: sent as an alarm", [(t, a) for t, _, a in notes.sent], [(texts.patches(1, BAD), True)])
notes = Notes()
boot_stages._preupdate_okww(CFG, notes, LOG, [])
check("pre-update: sent as an alarm", [(t, a) for t, _, a in notes.sent], [(texts.patches(1, BAD), True)])
(okww_patch.ensure_patches, okww_overlay.install, okww_overlay.write_master_pointer,
 okww_overlay.report_line, okww_overlay.drift_line, preupdate.run_okww) = real

print("\n[the game update after the queue could not confirm: alert=True]")
e = build()
e.state.append_ledger(rec("OK-WW", datetime.now(tz=SERVER_TZ), ok=True))
real_gu = (gameupdate.pending, gameupdate.run_deferred)
gameupdate.pending = lambda state_dir: {"终末地": "今天 MaaEnd 进不了游戏"}
gameupdate.run_deferred = lambda cfg, now, dispatch: ([], ["终末地：启动器没响应，没能确认有没有新版本"], [])
e._maybe_deferred_update()
e._gu_thread.join(10)
gameupdate.pending, gameupdate.run_deferred = real_gu
check("sent as an alarm", [(t, a) for t, _, a in e.notifier.sent], [(texts.unconfirmed("游戏更新", 1), True)])
check("…the title routes to the group", route_of(texts.unconfirmed("游戏更新", 1), alert=True), "group")

print("\n[a MAA failure that had fought gets no make-up: the log does not say 「只进日报」, the group hears it]")
e = build()
LINES.lines.clear()
handle._handle(e, rec("MAA", at(9, 5), raw={"sanity_spent": 120}))
e._flush_pending()
makeup.maybe_run(e, at(10, 5))
check("no make-up", makeup.read_marker(e.cfg.state_dir, D)["MAA"]["result"], makeup.GAVE_UP)
check("the log line does not say 「只进日报」", any("只进日报" in ln for ln in LINES.lines), False)
check("…it says the failure goes to the group", any("明日方舟这次不补" in ln and "进群" in ln for ln in LINES.lines))
e._flush_pending()
check("the failure reached the group", alarms(e), [texts.unresolved("明日方舟", "早班")])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
