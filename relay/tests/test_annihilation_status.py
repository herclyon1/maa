"""Annihilation (剿灭) weekly status, read from AUTO-MAS (hand-over item 13, 2026-10-11).

Running annihilation once a week is AUTO-MAS's job since the switch-over: with
the MAA account's Info.IfQuickConfig on it records the completed game-week in
Data.AnnihilationCompletedWeek and skips annihilation until the Monday 04:00
reset. The relay only reads. Here the gate is the real class against a fake
AUTO-MAS at the HTTP layer (urllib.request.urlopen, the transport under
commands._mas), and ScriptConfig.json is a real file.

Sources for the shapes used:
* the week marker: AUTO-MAS AutoProxy._current_week_marker,
  f"{iso_year:04d}-W{iso_week:02d}" on the UTC+4 game day; the machine held
  Data.AnnihilationCompletedWeek = "2026-W41" on 2026-10-11
  (BOARD/新中继-重叠可撤核对.md, settings table).
* API: every endpoint is POST; /api/scripts/get, /api/scripts/user/get
  {"scriptId"}; only the `data` member is read (docs/TOOLING.md "AUTO-MAS API").
* ScriptConfig.json: instances[] + <uid>/{Info, SubConfigsInfo/UserData/<uid>/...}
  (docs/CONFIG.md); MAA's install path D:\\ark\\maa.
"""
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
os.environ["ARK_MAS_PORT"] = "36163"   # config.mas_base(); the fake below answers only there
from ark_relay.features.weekly import annihilation as A
from ark_relay.features.alarm import errwatch
from ark_relay.core.config import SERVER_TZ

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append((record.levelname, record.getMessage()))


CAP = Capture()
logging.getLogger(errwatch.ARK).addHandler(CAP)
logging.getLogger(errwatch.ARK).setLevel(logging.DEBUG)

MAA_SID, MAA_UID = "8e4f0b4a-maa-script", "c2d1a0f3-maa-user"
END_SID, END_UID = "59da8762-maaend-script", "a7b6c5d4-maaend-user"

# Monday 2026-10-05 is game-week 2026-W41; the reset is 04:00 server time.
MON_0846 = datetime(2026, 10, 5, 8, 46, 3, tzinfo=SERVER_TZ)
MON_0300 = datetime(2026, 10, 5, 3, 0, tzinfo=SERVER_TZ)
print("[week marker: the one AUTO-MAS writes]")
check("10-05 08:46 is W41", A.week_key(MON_0846), "2026-W41")
check("10-05 03:00 still belongs to W40 (reset is 04:00)", A.week_key(MON_0300), "2026-W40")
check("single-digit week is zero-padded like AUTO-MAS's",
      A.week_key(datetime(2026, 1, 7, 12, 0, tzinfo=SERVER_TZ)), "2026-W02")


class Backend:
    """AUTO-MAS's backend as seen through urlopen.

    mode: "up" answers; "down" refuses every connection (AUTO-MAS not running);
    "hung" accepts and never answers (timeout); "no_maa" answers without "MAA".
    """

    def __init__(self, user, mode="up"):
        self.mode = mode
        self.calls = []
        self.scripts = {MAA_SID: {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"}},
                        END_SID: {"Info": {"Name": "MaaEnd", "Path": "D:\\ark\\maaend"}}}
        self.users = {MAA_SID: {MAA_UID: user}, END_SID: {END_UID: {"Info": {"Name": "endfield"}}}}

    def urlopen(self, req, timeout=None):
        url = req.full_url
        assert url.startswith("http://127.0.0.1:36163/"), url
        path = url[len("http://127.0.0.1:36163"):]
        body = json.loads((req.data or b"{}").decode())
        self.calls.append(path)
        if self.mode == "down":
            raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        if self.mode == "hung":
            raise TimeoutError("timed out")
        if path == "/api/scripts/get":
            if self.mode == "no_maa":
                return _Resp({"data": {END_SID: self.scripts[END_SID]}})
            return _Resp({"data": self.scripts})
        if path == "/api/scripts/user/get":
            return _Resp({"data": self.users.get(body["scriptId"], {})})
        raise AssertionError(f"the status read must not call {path}")


class _Resp:
    def __init__(self, obj):
        self._raw = json.dumps(obj, ensure_ascii=False).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_real_urlopen = urllib.request.urlopen


def user(week, switch="Annihilation"):
    return {"Info": {"Name": "arknights", "Annihilation": switch, "IfQuickConfig": True},
            "Data": {"AnnihilationCompletedWeek": week}}


def world(backend_user, file_user=None, mode="up"):
    root = tmpdir()
    automas = root / "automas"
    (automas / "config").mkdir(parents=True)
    cfg = {
        "instances": [{"uid": MAA_SID}, {"uid": END_SID}],
        MAA_SID: {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"},
                  "SubConfigsInfo": {"UserData": {"instances": [{"uid": MAA_UID}],
                                                  MAA_UID: file_user or backend_user}}},
        END_SID: {"Info": {"Name": "MaaEnd", "Path": "D:\\ark\\maaend"},
                  "SubConfigsInfo": {"UserData": {END_UID: {"Info": {"Name": "endfield"}}}}},
    }
    (automas / "config" / "ScriptConfig.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    be = Backend(backend_user, mode)
    urllib.request.urlopen = be.urlopen
    return A.WeeklyGate(root / "state", automas), be


try:
    print("\n[AUTO-MAS recorded this week: done, and the line says so]")
    g, be = world(user("2026-W41"))
    check("settings", g.settings(MON_0846), {"本周已完成": True, "当前": "Annihilation"})
    check("week_line", g.week_line(MON_0846), "明日方舟 · 剿灭：本周已打满，暂停到下周一")
    check("reads only (no update call)", [c for c in be.calls if "update" in c], [])

    print("\n[recorded last week: not done, the switch is named]")
    g, be = world(user("2026-W40", "Chernobog@Annihilation"))
    check("settings", g.settings(MON_0846), {"本周已完成": False, "当前": "Chernobog@Annihilation"})
    check("week_line", g.week_line(MON_0846), "明日方舟 · 剿灭：本周还没打满，开关开着（Chernobog@Annihilation）")
    check("Monday 03:00 still counts W40 as this week", g.settings(MON_0300)["本周已完成"], True)

    print("\n[switch off (Close), week not done: the line says off, and the boot alarms]")
    g, be = world(user("2026-W40", "Close"))
    check("week_line says the switch is off, not on",
          g.week_line(MON_0846), "明日方舟 · 剿灭：本周还没打满，开关关着，这周不会打")
    line = g.switch_off_line(MON_0846)
    check("switch_off_line names it", ("开关是关闭" in line, "不会把它打开" in line), (True, True))
    check("…in plain words (texts gate)", A.texts.plain(line), [])

    class Engine:
        _annihilation, _garden, _weeklyboss = g, None, None

    class Notifier:
        def __init__(self):
            self.sent = []

        def send(self, title, body, **kw):
            self.sent.append((title, body, kw.get("alert")))
            return []

    import types
    for name in ("win32event", "win32api", "win32con", "win32file", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, types.ModuleType(name))
    import boot_stages
    blog = logging.getLogger(errwatch.ARK + ".boot")
    CAP.lines.clear()
    n = Notifier()
    g._status = lambda now=None, _s=g._status: _s(MON_0846)
    boot_stages._stage_annihilation(Engine(), n, blog)
    check("one group alarm at boot", [(t, a) for t, _b, a in n.sent], [(A.texts.ANNIHILATION_OFF, True)])
    check("one WARNING logged", len([m for lv, m in CAP.lines if lv == "WARNING" and "剿灭" in m]), 1)
    check("the setting is not written", [c for c in be.calls if "update" in c], [])

    print("\n[switch off but this week done (AUTO-MAS's own skip): no alarm]")
    g, be = world(user("2026-W41", "Close"))
    check("no alarm line", g.switch_off_line(MON_0846), "")
    print("\n[switch on, not done: no alarm]")
    g, be = world(user("2026-W40", "Annihilation"))
    check("no alarm line", g.switch_off_line(MON_0846), "")
    print("\n[unreadable: not this alarm]")
    g, be = world(user("2026-W40", "Close"), mode="hung")
    check("no alarm line", g.switch_off_line(MON_0846), "")

    print("\n[never recorded: not done]")
    g, be = world({"Info": {"Name": "arknights", "Annihilation": "Annihilation"}})
    check("no Data section -> not done", g.settings(MON_0846)["本周已完成"], False)

    print("\n[backend down: the file is safe and read]")
    g, be = world(user("2026-W40"), file_user=user("2026-W41"), mode="down")
    check("refused connection -> ScriptConfig.json", g.settings(MON_0846), {"本周已完成": True, "当前": "Annihilation"})

    print("\n[backend up but not answering properly: no stale file value, said once]")
    A._READ_SAID.clear()
    CAP.lines.clear()
    g, be = world(user("2026-W40"), file_user=user("2026-W41"), mode="hung")
    check("hung backend: not the file's stale week (unknown)", g.settings(MON_0846), {"本周已完成": None, "当前": ""})
    check("…and the line says it could not read", g.week_line(MON_0846), "明日方舟 · 剿灭：读不到调度程序记的本周进度")
    warns = [m for lv, m in CAP.lines if lv == "WARNING" and "读不出方舟账号的设置" in m]
    check("one WARNING for two reads", len(warns), 1)
    g, be = world(user("2026-W41"), mode="no_maa")
    check("backend answers without MAA: not the file either", g.settings(MON_0846)["本周已完成"], None)

    print("\n[machine going down: the backend is not asked, the file is read, nothing warned]")
    # 10-11 21:46:43 (relay.log): SvcStop's last state push asked the backend while Windows
    # was killing AUTO-MAS -> ConnectionResetError 10054 -> WARNING -> group push.
    from ark_relay.features.alarm import errwatch
    A._READ_SAID.clear()
    CAP.lines.clear()
    g, be = world(user("2026-W40"), file_user=user("2026-W41"), mode="up")
    def reset(req, timeout=None):
        be.calls.append(req.full_url)
        raise ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。")
    urllib.request.urlopen = reset
    errwatch.mark_os_shutdown()     # SvcShutdown: Windows is going down
    try:
        check("stopping: settings from ScriptConfig.json", g.settings(MON_0846), {"本周已完成": True, "当前": "Annihilation"})
        check("stopping: backend not asked", be.calls, [])
        check("stopping: no WARNING", [m for lv, m in CAP.lines if lv == "WARNING"], [])
    finally:
        errwatch._os_shutdown.clear()
    A._READ_SAID.clear()
    # Mute audit 10-12 item 10: a plain service stop (sc stop, the self-update restart) is
    # not the machine going down - AUTO-MAS stays up, so it is asked, and failing is said.
    be.calls.clear()
    CAP.lines.clear()
    errwatch.mark_stopping()
    try:
        g.settings(MON_0846)
        check("service stop only: the backend is asked", len(be.calls) >= 1, True)
        check("service stop only: the reset warns (pushed)",
              len([m for lv, m in CAP.lines if lv == "WARNING" and "读不出方舟账号的设置" in m]), 1)
    finally:
        errwatch.clear_stopping()
    A._READ_SAID.clear()
    CAP.lines.clear()
    check("not stopping: the same reset still warns (a live backend failing is a fault)",
          (g.settings(MON_0846)["当前"], len([m for lv, m in CAP.lines if lv == "WARNING" and "读不出方舟账号的设置" in m])),
          ("", 1))

    print("\n[no AUTO-MAS dir: nothing asked]")
    g = A.WeeklyGate(tmpdir(), None)
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked"))
    check("unknown, nothing read", g.settings(MON_0846), {"本周已完成": None, "当前": ""})
finally:
    urllib.request.urlopen = _real_urlopen

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
