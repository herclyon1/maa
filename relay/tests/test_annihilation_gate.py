"""The real annihilation (剿灭) WeeklyGate against a fake AUTO-MAS at the HTTP layer.

Before this file every test of the weekly reopen/enforce path used a fake gate
(test_weeklyboss_reopen.py's `Gate`), so `WeeklyGate.maybe_reopen`, `enforce`
and `annihilation._write_via_api` had never run under a test (audit
BOARD/补丁审查-1005.md, item E). Here the gate is the real class, the state is a
real state.json in a temp dir, ScriptConfig.json is a real file, and the only
thing replaced is `urllib.request.urlopen` - the transport under
`commands._mas`. Everything above it (`_find_user`, `_write_via_api`,
`_write_setting`, `read_setting`) is the production code.

Sources for the shapes used:
* state: `weekly.annihilation = {"done_week": "2026-W39", "restore_to": "Annihilation"}`
  (~/Claude/ark-evidence/M5-0923/state/state.json, pulled off the machine 09-23).
* ScriptConfig.json: `instances[] + <uid>/{Info, SubConfigsInfo/UserData/<uid>/Info/Annihilation}`
  (docs/CONFIG.md "config/ScriptConfig.json", the check directives there, and
  test_shutdown.py's "real config shape"); MAA's install path D:\\ark\\maa
  (docs/CONFIG.md).
* API: every endpoint is POST; /api/scripts/get, /api/scripts/user/get
  {"scriptId"}, /api/scripts/user/update {"scriptId","userId","data"}
  (docs/TOOLING.md "AUTO-MAS API"). The relay reads only the `data` member of
  a response, so only `data` is modelled; no real response envelope was
  captured anywhere in the evidence. The script is named "MAA": the machine
  logged 「已通过 AUTO-MAS 后端改写」, which _write_via_api only returns after
  _find_user("MAA") resolved (relay.log 10-05 11:30:44, below).
* The status code AUTO-MAS answers a refused write with is not captured; the
  refusal text 「配置已锁定, 无法修改」 is (docs/TOOLING.md, docs/ESTOP.md). Any
  HTTPError exercises the same branch - "the backend answered, and said no".
* The happy-path timeline mirrors the machine's own week, relay.log 10-05
  (~/Claude/ark-evidence/relay-log-1006/relay.log):
      08:46:03 新的一周，剿灭已恢复为 Annihilation
      09:39:28 本周剿灭已完成，待脚本停下后关闭（周一 04:00 后恢复为 Annihilation）
      11:30:44 剿灭开关被冲回「Annihilation」，已重新关闭（已通过 AUTO-MAS 后端改写）
"""
import io
import json
import logging
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402
from ark_relay import annihilation as A  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402
from ark_relay.statestore import StateStore  # noqa: E402

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
logging.getLogger("ark").addHandler(CAP)
logging.getLogger("ark").setLevel(logging.DEBUG)

MAA_SID, MAA_UID = "8e4f0b4a-maa-script", "c2d1a0f3-maa-user"
END_SID, END_UID = "59da8762-maaend-script", "a7b6c5d4-maaend-user"

# Monday 2026-10-05 is game-week 2026-W41; the reset is 04:00 server time.
MON_0846 = datetime(2026, 10, 5, 8, 46, 3, tzinfo=SERVER_TZ)
MON_0300 = datetime(2026, 10, 5, 3, 0, tzinfo=SERVER_TZ)
MON_1130 = datetime(2026, 10, 5, 11, 30, 44, tzinfo=SERVER_TZ)
SUN_2100 = datetime(2026, 10, 4, 21, 0, tzinfo=SERVER_TZ)
check("10-05 08:46 is W41", A.week_key(MON_0846), "2026-W41")
check("10-05 03:00 still belongs to W40 (reset is 04:00)", A.week_key(MON_0300), "2026-W40")


# ---------------------------------------------------------------- fake AUTO-MAS

class Backend:
    """AUTO-MAS's backend as seen through urlopen.

    mode:
      "up"       - answers everything
      "down"     - connection refused on every call (AUTO-MAS not running)
      "refuse"   - answers reads, update raises HTTP 500 「配置已锁定, 无法修改」
      "ignore"   - update returns normally but the value does not change
      "refuse_then_down" - update raises HTTP 500, every later call is refused
      "hung"     - the connection is accepted but nothing comes back (timeout)
      "no_maa"   - answers, but has no script named "MAA"
    """

    def __init__(self, annihilation, mode="up"):
        self.mode = mode
        self.calls = []
        self.dead = mode == "down"
        self.scripts = {
            MAA_SID: {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"}},
            END_SID: {"Info": {"Name": "MaaEnd", "Path": "D:\\ark\\maaend"}},
        }
        self.users = {
            MAA_SID: {MAA_UID: {"Info": {"Name": "arknights", "Stage": "1-7",
                                         "StageMode": "Fixed", "MedicineNumb": 0,
                                         "Annihilation": annihilation}}},
            END_SID: {END_UID: {"Info": {"Name": "endfield"}}},
        }

    def value(self):
        return self.users[MAA_SID][MAA_UID]["Info"]["Annihilation"]

    def updates(self):
        return [b for p, b in self.calls if p == "/api/scripts/user/update"]

    def urlopen(self, req, timeout=None):
        url = req.full_url
        assert url.startswith("http://127.0.0.1:36163/"), url
        path = url[len("http://127.0.0.1:36163"):]
        body = json.loads((req.data or b"{}").decode())
        self.calls.append((path, body))
        if self.dead:
            raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        if self.mode == "hung":
            raise TimeoutError("timed out")
        if path == "/api/scripts/get":
            if self.mode == "no_maa":
                return _Resp({"data": {END_SID: self.scripts[END_SID]}})
            return _Resp({"data": self.scripts})
        if path == "/api/scripts/user/get":
            return _Resp({"data": self.users.get(body["scriptId"], {})})
        if path == "/api/scripts/user/update":
            if self.mode in ("refuse", "refuse_then_down"):
                if self.mode == "refuse_then_down":
                    self.dead = True
                raise urllib.error.HTTPError(
                    url, 500, "Internal Server Error", {},
                    io.BytesIO('{"detail":"ValueError: 配置已锁定, 无法修改"}'.encode()))
            if self.mode == "up":
                info = self.users[body["scriptId"]][body["userId"]]["Info"]
                info.update(body["data"]["Info"])
            return _Resp({"status": "success"})
        raise AssertionError(f"endpoint not prepared by this test: {path}")


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


def world(file_value, backend_value=None, mode="up", state=None):
    """A fresh state dir, AUTO-MAS dir with ScriptConfig.json, and backend."""
    root = tmpdir()
    automas = root / "automas"
    (automas / "config").mkdir(parents=True)
    cfg = {
        "instances": [{"uid": MAA_SID, "type": "MAA"}, {"uid": END_SID, "type": "MaaEnd"}],
        MAA_SID: {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"},
                  "SubConfigsInfo": {"UserData": {
                      "instances": [{"uid": MAA_UID}],
                      MAA_UID: {"Info": {"Name": "arknights", "Stage": "1-7",
                                         "Annihilation": file_value}}}}},
        END_SID: {"Info": {"Name": "MaaEnd", "Path": "D:\\ark\\maaend"},
                  "SubConfigsInfo": {"UserData": {
                      END_UID: {"Info": {"Name": "endfield"}}}}},
    }
    (automas / "config" / "ScriptConfig.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    sd = root / "state"
    sd.mkdir()
    if state is not None:
        StateStore(sd).set("weekly", "annihilation", state)
    be = Backend(file_value if backend_value is None else backend_value, mode)
    urllib.request.urlopen = be.urlopen
    return A.WeeklyGate(sd, automas), be, automas / "config" / "ScriptConfig.json"


def file_value(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data[MAA_SID]["SubConfigsInfo"]["UserData"][MAA_UID]["Info"].get("Annihilation")


def backups(path):
    return sorted(p.name for p in path.parent.glob("ScriptConfig.bak-*"))


def saved(gate):
    return StateStore(gate._store.dir).get("weekly", "annihilation")


REAL_STATE_W40 = {"done_week": "2026-W40", "restore_to": "Annihilation"}

try:
    # ============================================================ maybe_reopen
    print("\n[maybe_reopen: first boot of a new game-week, backend up (relay.log 10-05 08:46:03)]")
    g, be, path = world("Close", state=dict(REAL_STATE_W40))
    CAP.lines.clear()
    msg = g.maybe_reopen(MON_0846)
    check("tells the user it reopened", msg, "明日方舟 · 剿灭：新的一周，已重新开启（Annihilation）")
    check("exactly one write, to the MAA user, through the backend", be.updates(),
          [{"scriptId": MAA_SID, "userId": MAA_UID, "data": {"Info": {"Annihilation": "Annihilation"}}}])
    check("the running backend now holds Annihilation", be.value(), "Annihilation")
    check("the file was not edited behind the backend's back", (file_value(path), backups(path)), ("Close", []))
    check("bookkeeping cleared only after the read-back agreed", saved(g), {})
    check("log line as on the machine", ("INFO", "新的一周，剿灭已恢复为 Annihilation") in CAP.lines, True)
    check("asked again in the same boot: says nothing", g.maybe_reopen(MON_0846), "")
    check("and writes nothing", len(be.updates()), 1)

    print("\n[maybe_reopen: same game-week - nothing to do]")
    g, be, path = world("Close", state={"done_week": "2026-W41", "restore_to": "Annihilation"})
    check("returns nothing", g.maybe_reopen(MON_1130), "")
    check("no request at all", be.calls, [])
    check("state kept", saved(g), {"done_week": "2026-W41", "restore_to": "Annihilation"})

    print("\n[maybe_reopen: Monday 03:00 is still last week (reset is 04:00)]")
    g, be, path = world("Close", state={"done_week": "2026-W40", "restore_to": "Annihilation"})
    check("returns nothing", g.maybe_reopen(MON_0300), "")
    check("no request at all", be.calls, [])

    print("\n[maybe_reopen: no record (switch closed by hand) - never reopened by the gate]")
    g, be, path = world("Close", state=None)
    check("returns nothing", g.maybe_reopen(MON_0846), "")
    check("no write", be.updates(), [])

    print("\n[maybe_reopen: remembered map is restored, not the generic default]")
    g, be, path = world("Close", state={"done_week": "2026-W40",
                                        "restore_to": "Chernobog@Annihilation"})
    check("message names the map", g.maybe_reopen(MON_0846),
          "明日方舟 · 剿灭：新的一周，已重新开启（Chernobog@Annihilation）")
    check("backend holds the map", be.value(), "Chernobog@Annihilation")

    print("\n[maybe_reopen: backend accepts the call but the value does not change]")
    g, be, path = world("Close", mode="ignore", state=dict(REAL_STATE_W40))
    CAP.lines.clear()
    check("does not claim it reopened", g.maybe_reopen(MON_0846), "")
    check("keeps the week so the next boot retries", saved(g), REAL_STATE_W40)
    check("says why in the log", ("WARNING", "剿灭恢复失败: 写了但没生效：现在是 'Close'") in CAP.lines, True)
    check("file untouched", (file_value(path), backups(path)), ("Close", []))

    print("\n[maybe_reopen: AUTO-MAS not running (connection refused) - the file is the only copy]")
    g, be, path = world("Close", mode="down", state=dict(REAL_STATE_W40))
    msg = g.maybe_reopen(MON_0846)
    check("reopened through the file", msg, "明日方舟 · 剿灭：新的一周，已重新开启（Annihilation）")
    check("file now Annihilation", file_value(path), "Annihilation")
    check("one backup taken before the edit", len(backups(path)), 1)
    data = json.loads(path.read_text(encoding="utf-8"))
    check("MaaEnd's user left alone", data[END_SID]["SubConfigsInfo"]["UserData"][END_UID]["Info"],
          {"Name": "endfield"})
    check("bookkeeping cleared", saved(g), {})

    print("\n[maybe_reopen: backend answers but refuses the write, then stops answering]")
    # The 2026-08-31 04:01 failure in a new costume (see _write_via_api's
    # docstring): the switch must not be reported as reopened, and the week
    # must be kept for a retry, unless the copy AUTO-MAS is running really
    # changed. Writing the file while the backend is up is the write that
    # gets wiped.
    g, be, path = world("Close", mode="refuse_then_down", state=dict(REAL_STATE_W40))
    msg = g.maybe_reopen(MON_0846)
    check("does not claim it reopened", msg, "")
    check("keeps the week so the next boot retries", saved(g), REAL_STATE_W40)
    check("did not edit the file behind a running backend", (file_value(path), backups(path)), ("Close", []))

    # ============================================================ enforce
    print("\n[enforce: done this week, AUTO-MAS wiped the switch back open (relay.log 10-05 11:30:44)]")
    g, be, path = world("Annihilation", state={"done_week": "2026-W41", "restore_to": "Annihilation"})
    CAP.lines.clear()
    check("reports a change", g.enforce(MON_1130), True)
    check("one write of Close to the MAA user", be.updates(),
          [{"scriptId": MAA_SID, "userId": MAA_UID, "data": {"Info": {"Annihilation": "Close"}}}])
    check("backend now Close", be.value(), "Close")
    check("log line as on the machine",
          ("INFO", "剿灭开关被冲回「Annihilation」，已重新关闭（已通过 AUTO-MAS 后端改写）") in CAP.lines, True)
    check("second call: already Close, no write", (g.enforce(MON_1130), len(be.updates())), (False, 1))
    check("state untouched by enforce", saved(g), {"done_week": "2026-W41", "restore_to": "Annihilation"})

    print("\n[enforce: not done this week - the switch must stay open]")
    g, be, path = world("Annihilation", state=dict(REAL_STATE_W40))
    check("no change", g.enforce(MON_1130), False)
    check("no request at all", be.calls, [])
    check("backend still open", be.value(), "Annihilation")

    print("\n[enforce: the switch cannot be read (backend down, no ScriptConfig)]")
    g, be, path = world("Annihilation", mode="down", state={"done_week": "2026-W41"})
    path.unlink()
    check("no change claimed", g.enforce(MON_1130), False)
    check("no write attempted", be.updates(), [])

    print("\n[enforce: AUTO-MAS not running - closes through the file]")
    g, be, path = world("Annihilation", mode="down", state={"done_week": "2026-W41", "restore_to": "Annihilation"})
    check("reports a change", g.enforce(MON_1130), True)
    check("file now Close", file_value(path), "Close")

    print("\n[enforce: backend ignores the write]")
    g, be, path = world("Annihilation", mode="ignore", state={"done_week": "2026-W41"})
    CAP.lines.clear()
    check("no change claimed", g.enforce(MON_1130), False)
    check("warning says it did not take",
          ("WARNING", "剿灭开关重新关闭失败: 写了但没生效：现在是 'Annihilation'") in CAP.lines, True)

    print("\n[enforce: backend answers but refuses the write (配置已锁定)]")
    g, be, path = world("Annihilation", mode="refuse", state={"done_week": "2026-W41"})
    CAP.lines.clear()
    check("no change claimed", g.enforce(MON_1130), False)
    check("backend still open", be.value(), "Annihilation")
    check("did not edit the file behind a running backend", (file_value(path), backups(path)),
          ("Annihilation", []))
    check("no 「已重新关闭」 line", any("已重新关闭" in m for _, m in CAP.lines), False)
    check("a warning names the refusal",
          any(lv == "WARNING" and "剿灭开关重新关闭失败" in m for lv, m in CAP.lines), True)

    print("\n[enforce: backend accepts the connection but never answers (AUTO-MAS alive, hung)]")
    # read_setting falls back to the file for reading, which is harmless; the
    # write must not, because the hung process still holds its own copy.
    g, be, path = world("Annihilation", mode="hung", state={"done_week": "2026-W41"})
    check("no change claimed", g.enforce(MON_1130), False)
    check("file not edited", (file_value(path), backups(path)), ("Annihilation", []))

    print("\n[enforce: backend answers but has no script called MAA]")
    g, be, path = world("Annihilation", mode="no_maa", state={"done_week": "2026-W41"})
    check("no change claimed", g.enforce(MON_1130), False)
    check("file not edited", (file_value(path), backups(path)), ("Annihilation", []))

    # ============================================================ _write_via_api
    print("\n[_write_via_api directly]")
    g, be, path = world("Close")
    check("already the value: no update sent", (A._write_via_api("Close"), be.updates()), ((True, ""), []))
    check("written and read back", A._write_via_api("Annihilation"), (True, "已通过 AUTO-MAS 后端改写"))
    check("read-back came from user/get after the update",
          [p for p, _ in be.calls][-2:], ["/api/scripts/user/update", "/api/scripts/user/get"])
    g, be, path = world("Close", mode="ignore")
    check("ignored write is a failure, with the value it found", A._write_via_api("Annihilation"),
          (False, "写了但没生效：现在是 'Close'"))
    g, be, path = world("Close", mode="down")
    try:
        A._write_via_api("Annihilation")
        check("unreachable backend raises (caller falls back to the file)", "returned", "raised")
    except urllib.error.URLError:
        check("unreachable backend raises (caller falls back to the file)", "raised", "raised")
    g, be, path = world("Close", mode="refuse")
    try:
        got = A._write_via_api("Annihilation")
    except Exception as exc:  # noqa: BLE001
        got = ("raised", type(exc).__name__)
    check("refused write is reported as not written", got[0], False)
    check("refused write: the switch is unchanged", be.value(), "Close")

    # ============================================================ full week
    print("\n[a whole week through the real gate: Sunday close, Monday reopen, Monday close]")
    g, be, path = world("Annihilation", state=None)
    check("Sunday pass recorded", g.on_success(SUN_2100),
          "明日方舟 · 剿灭：本周已打满，暂停到下周一（届时恢复为 Annihilation）")
    check("on_success does not write (queue still running)", be.updates(), [])
    check("enforce after the queue closes it", (g.enforce(SUN_2100), be.value()), (True, "Close"))
    check("week_line", g.week_line(SUN_2100), "明日方舟 · 剿灭：本周已打满，暂停到下周一")
    check("Monday reopens", g.maybe_reopen(MON_0846), "明日方舟 · 剿灭：新的一周，已重新开启（Annihilation）")
    check("Monday: enforce leaves it open", (g.enforce(MON_0846), be.value()), (False, "Annihilation"))
    check("week_line shows it open", g.week_line(MON_0846), "明日方舟 · 剿灭：本周还没打满，开关开着（Annihilation）")
finally:
    urllib.request.urlopen = _real_urlopen

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
