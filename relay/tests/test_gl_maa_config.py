"""T12 for MAA: what our code writes into MAA's and AUTO-MAS's configs is what they read.

Every expected verdict below comes from a machine record or from the pinned upstream
sources (gamesim/upstream/maa-v6.19.0-beta.1, SOURCE.txt), never from the relay code
under test. Upstream rules that are code are executed from the pinned files
(gamesim/lib/maa_schema.py); the one fake, the AUTO-MAS backend, is pinned by the body
hashes of the handlers it stands in for.

Cases (a name on the command line runs only those cases):

  pin         the pinned files are byte-identical to SOURCE.txt; the upstream functions
              the relay imitates (stagegate: FightTask::set_params,
              StageNavigationTask::set_stage_name) or this test fakes (the backend
              handlers, ConfigItem.setValue) still have the bodies they were checked
              against.
  yw4         2026-10-10: the phone set the stage to YW-4 at 04:25 and MAA refused the
              Fight task at 09:01 (序列化失败), stopping the whole run. With MAA's task
              tree as on the machine that morning (v6.19.0-beta.1 resource/tasks plus
              Stages/YW.json at MAA dev c09d3fe7) set_stage must refuse YW-4 and send
              nothing; with YW.json at cc780293 (YW-4 added; MAA took YW-4 on 10-11) it
              must go through. Red at 3fce7262~1, green at 3fce7262.
  annihilation 2026-08-31: the weekly switch restored by editing ScriptConfig.json while
              AUTO-MAS ran was washed back to Close from its memory copy and the week
              went unplayed. The writer of Info.Annihilation must go through the
              backend and leave the file alone. The writer is whatever this tree has:
              annihilation.WeeklyGate.maybe_reopen before the 10-11 switch-over,
              relay/handover step 13 since. Red at 2a6ff6da~1, green at 2a6ff6da.
  user        set_stage / set_medicine through the backend: each field written is
              declared on AUTO-MAS's MaaUserConfig, its value passes AUTO-MAS's own
              validator, AutoProxy reads it, and ScriptConfig.json is not touched.
  handover    the values relay/handover writes for MAA (steps 13 and 10a) pass
              AUTO-MAS's validators and are read; the week marker it writes into
              Data.AnnihilationCompletedWeek equals AUTO-MAS's own
              (_current_week_marker on game_now), across the Monday 04:00 reset and the
              ISO year turn.
  guinew      gui.new.json: our drone values are MAA's UsesOfDronesList, our Award
              switches are AwardTask properties MaaCore reads; write_maa into a copy of
              the machine's tree, then AUTO-MAS's own _copy_source_config and
              _find_task_source hand MAA a task carrying the value, under a $type MAA
              can deserialise, with nothing else changed.
"""
from __future__ import annotations

import contextlib
import copy
import importlib
import io
import json
import logging
import os
import shutil
import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "handover"))
sys.path.insert(0, str(HERE))


class _Any:
    """Stands in for any pywin32 attribute (the phone commands pull in service helpers)."""
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
              "win32con", "win32file", "servicemanager", "win32process",
              "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(_name, _Stub(_name))

from _tmp import tmpdir  # noqa: E402
from gamesim.lib import maa_schema as S  # noqa: E402

MACHINE = HERE / "gamesim" / "maa" / "machine"
SCRIPT_CONFIG = json.loads((MACHINE / "ScriptConfig.json").read_text(encoding="utf-8"))
GUI_NEW = (MACHINE / "gui.new.json").read_bytes()
MAA_SID = next(i["uid"] for i in SCRIPT_CONFIG["instances"] if i["type"] == "MaaConfig")

# Body hashes of the upstream functions the relay imitates or this test fakes. A new pin
# whose bodies differ turns `pin` red before anything else: re-check stagegate.py against
# the new set_params / set_stage_name, and _Backend against the new handlers.
PINNED_BODIES = {
    ("maa", "src/MaaCore/Assistant.cpp", "asst::Assistant::append_task"):
        "753ff4dfa408bd0be33caca33e862b6ebdd87cd5d7d93e3994db06d3352d7770",
    ("maa", "src/MaaCore/Task/Interface/FightTask.cpp", "asst::FightTask::set_params"):
        "eeaa4158b47e3c3e20fc93607a69dc750dfddf4bff50b82b2b4b95ae61edc815",
    ("maa", "src/MaaCore/Task/Fight/StageNavigationTask.cpp", "asst::StageNavigationTask::set_stage_name"):
        "ee2eedbfaf848191db38e1da587079d15e38783c9de2081bf8ab9ef86d02ef5c",
    ("automas", "app/api/scripts.py", "get_script"):
        "33a4fe52689e4e1e0bc22992d5df219db014621d670ad78c754358134dadcc6c",
    ("automas", "app/api/scripts.py", "update_script"):
        "31263dc778a616530ad2bfeb901c608e05725f48583ee3c3927a6efd9f2b964a",
    ("automas", "app/api/scripts.py", "get_user"):
        "aaab65fcbea758118252bf46aa44b9316dfce1e75230b7e659b3186e48d9988d",
    ("automas", "app/api/scripts.py", "update_user"):
        "adf5b637f3accf6d28d60fab98035c35f57c2a6331f71a3cc373f3f40d56137d",
    ("automas", "app/models/ConfigBase.py", "ConfigItem.setValue"):
        "a95cd9a53c4841022301c48e3c42aab3441971da2820a170e7c5175229bc6d85",
}

EVIDENCE = {
    "yw4_set": "relay.log 10-10 04:25:27 ark.service 「📱 手机指令 set_stage：刷取关卡：1-7 → YW-4（调度程序已确认）」",
    "yw4_refused": ("MAA asst.log 2026-10-10 09:01:10.060-.061 (COS bundle 2026-10-10_arknights_MAA-05-00-01): "
                    "'Unknown task: YW-4' / 'The stage name is not in invalid, or is not main line stage YW-4' / "
                    "'Cannot set stage YW-4' / 'append_task | invalid params'; gui.log 09:01:10.061 "
                    "「理智作战: 理智作战 序列化失败」 then 「已停止」, three times (09:01, 09:02, 09:03)"),
    "yw4_taken": ("MAA asst.log 2026-10-11 21:30:43.511 append_task Fight {\"stage\":\"YW-4\",...} -> "
                  "'directly task YW-4', set_params leave (no error)"),
    "maa_tree": ("MAA gui.log 2026-10-10 09:01:08 'Resource Time: 2026/10/10 07:31:13' (MaaResource 8d949986, "
                 "version.json last_updated 2026-10-09 23:31:13 UTC); MAA dev c09d3fe7 2026-10-09 10:06Z added "
                 "Stages/YW.json without YW-4, cc780293 2026-10-10 02:22Z added YW-4"),
    "one_seven": "MAA asst.log 2026-10-06 21:31:12.189 append_task Fight {\"stage\":\"1-7\",...} -> 'directly task 1-7', task_id 2",
    "washout": ("2a6ff6da message: 2026-08-31 04:01 「新的一周，剿灭已恢复为 Annihilation」 was written to the file and read "
                "back, AUTO-MAS was running and rewrote the file from memory, the value went back to Close and the "
                "week's annihilation never ran"),
}

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


def require(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok else f": {detail}"))
    if not ok:
        fails.append(name)


# ---------- the AUTO-MAS backend (fake; handlers pinned in PINNED_BODIES) ----------

class _Backend:
    """AUTO-MAS's /api/scripts endpoints over a copy of the machine's ScriptConfig.

    Like app/api/scripts.py: get returns {code, index, data}; update merges the posted
    groups key by key, each value through the item's own upstream validator
    (ConfigItem.setValue: validate, else correct). It never writes ScriptConfig.json:
    the running AUTO-MAS keeps its copy in memory, so the file on disk is exactly what
    the writer under test left there.
    """

    def __init__(self) -> None:
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"] or 0)) or b"{}")
                reply = json.dumps(backend.answer(self.path, body)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
        self.cfg: dict = {}
        self.calls: list[tuple[str, dict]] = []

    def reset(self, cfg: dict) -> None:
        self.cfg, self.calls = copy.deepcopy(cfg), []

    def updates(self) -> list[tuple[str, dict]]:
        return [(p, b) for p, b in self.calls if p.endswith("/update")]

    def user(self) -> dict:
        ud = self.cfg[MAA_SID]["SubConfigsInfo"]["UserData"]
        return ud[ud["instances"][0]["uid"]]

    def answer(self, path: str, body: dict) -> dict:
        self.calls.append((path, body))
        scripts = {k: v for k, v in self.cfg.items() if k != "instances"}
        sid = body.get("scriptId")
        if path == "/api/scripts/get":
            return {"code": 200, "status": "success", "message": "",
                    "index": [i for i in self.cfg["instances"] if not sid or i["uid"] == sid],
                    "data": {k: {g: v for g, v in sc.items() if g != "SubConfigsInfo"}
                             for k, sc in scripts.items() if not sid or k == sid}}
        if path == "/api/scripts/user/get":
            ud = scripts[sid]["SubConfigsInfo"]["UserData"]
            return {"code": 200, "status": "success", "message": "", "index": ud["instances"],
                    "data": {k: v for k, v in ud.items() if k != "instances"
                             and (not body.get("userId") or k == body["userId"])}}
        if path == "/api/scripts/update":
            self._merge(scripts[sid], body.get("data") or {}, "MaaConfig")
            return {"code": 200, "status": "success", "message": ""}
        if path == "/api/scripts/user/update":
            user = scripts[sid]["SubConfigsInfo"]["UserData"][body["userId"]]
            self._merge(user, body.get("data") or {}, "MaaUserConfig")
            return {"code": 200, "status": "success", "message": ""}
        return {"code": 500, "status": "error", "message": f"not in the fake: {path}"}

    @staticmethod
    def _merge(node: dict, data: dict, cls: str) -> None:
        for group, items in data.items():
            for key, value in items.items():
                try:
                    v = S.validator_for(cls, f"{group}.{key}")
                except (KeyError, ValueError):
                    v = None
                node.setdefault(group, {})[key] = value if v is None or v.validate(value) else v.correct(value)


# ---------- the tree the relay sees ----------

TMP = tmpdir()
BACKEND = _Backend()
AUTOMAS = TMP / "AUTO-MAS"
STATE = TMP / "state"
os.environ.update(ARK_STATE_DIR=str(STATE), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_MAS_PORT=str(BACKEND.port), SERVERCHAN_KEY="", ARK_LLM_KEY="")
MAA_TREES = {name: S.make_maa_install(TMP / f"maa-{name}", yw)
             for name, yw in (("tag", None), ("morning", "c09d3fe7"), ("evening", "cc780293"))}


def _script_config_file() -> Path:
    return AUTOMAS / "config" / "ScriptConfig.json"


def _start(cfg: dict, maa: str = "tag") -> bytes:
    """Backend and file both hold `cfg`; MAA is the named tree. Returns the file's bytes."""
    BACKEND.reset(cfg)
    f = _script_config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(cfg, ensure_ascii=False, indent=4), encoding="utf-8")
    os.environ["ARK_MAA_DIR"] = str(MAA_TREES[maa])
    return f.read_bytes()


def _file(before: bytes) -> str:
    return "untouched" if _script_config_file().read_bytes() == before else "rewritten"


def _with_user(**info) -> dict:
    cfg = copy.deepcopy(SCRIPT_CONFIG)
    ud = cfg[MAA_SID]["SubConfigsInfo"]["UserData"]
    ud[ud["instances"][0]["uid"]]["Info"].update(info)
    return cfg


def _module(*names: str):
    """The first of `names` this tree has (modules moved on 2026-10-11)."""
    for name in names:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name and name.startswith(exc.name):
                continue
            raise
        if hasattr(mod, "MAS_API"):   # trees before config.mas_base() read a constant
            mod.MAS_API = f"http://127.0.0.1:{BACKEND.port}"
        return mod
    return None


def _commands():
    return _module("ark_relay.features.phone.commands", "ark_relay.commands")


def _quiet(fn, *a, **k):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn(*a, **k)
    return result, out.getvalue()


# ---------- cases ----------

def case_pin() -> None:
    check("pinned files match SOURCE.txt", S.pin_problems(), [])
    for (repo, path, fn), want in PINNED_BODIES.items():
        body = S.cpp_body(path, fn) if repo == "maa" else S.py_body(path, fn)
        check(f"upstream body unchanged: {path} {fn}", S.body_sha(body), want)


def case_yw4() -> None:
    commands = _commands()
    before = _start(_with_user(Stage="1-7"), "morning")
    ok, msg = commands._set_stage("YW-4")
    check("YW-4 on the 10-10 morning tree: refused (" + EVIDENCE["yw4_refused"][:60] + "...)", ok, False)
    check("YW-4 on the 10-10 morning tree: nothing sent to AUTO-MAS", BACKEND.updates(), [])
    check("YW-4 on the 10-10 morning tree: AUTO-MAS still has 1-7", BACKEND.user()["Info"]["Stage"], "1-7")
    check("YW-4 on the 10-10 morning tree: ScriptConfig.json untouched", _file(before), "untouched")
    if ok:
        print(f"      reply: {msg}")

    _start(_with_user(Stage="1-7"), "evening")
    ok, msg = commands._set_stage("YW-4")
    require("YW-4 once YW.json has it (10-11): accepted", ok, msg)
    check("YW-4 once YW.json has it (10-11): AUTO-MAS now has YW-4", BACKEND.user()["Info"]["Stage"], "YW-4")


def case_annihilation() -> None:
    _commands()   # the backend client the old annihilation module borrows
    old = _module("ark_relay.annihilation")
    STATE.mkdir(parents=True, exist_ok=True)
    before = _start(_with_user(Annihilation="Close"))
    if old is not None and hasattr(old, "WeeklyGate") and hasattr(old.WeeklyGate, "maybe_reopen"):
        (STATE / "annihilation.json").write_text(json.dumps(
            {"done_week": "2026-W35", "restore_to": "Annihilation"}), encoding="utf-8")
        sh = timezone(timedelta(hours=8))
        writer = "annihilation.WeeklyGate.maybe_reopen at 2026-08-31 04:01"
        _quiet(old.WeeklyGate(STATE, AUTOMAS).maybe_reopen, datetime(2026, 8, 31, 4, 1, tzinfo=sh))
    else:
        handover = importlib.import_module("automas_handover")
        (STATE / "state.json").write_text(json.dumps({"weekly": {"annihilation": {
            "done_week": "2026-W35", "restore_to": "Annihilation"}}}), encoding="utf-8")
        writer = "relay/handover step 13"
        _quiet(handover.plan, STATE, TMP / "okww", False, True, ["13"])
    sent = [b.get("data") for p, b in BACKEND.updates() if p == "/api/scripts/user/update"]
    check(f"{writer}: Info.Annihilation sent to the running AUTO-MAS ({EVIDENCE['washout'][:50]}...)",
          sent, [{"Info": {"Annihilation": "Annihilation"}}])
    check(f"{writer}: ScriptConfig.json untouched while AUTO-MAS runs", _file(before), "untouched")
    check(f"{writer}: AUTO-MAS holds Annihilation", BACKEND.user()["Info"]["Annihilation"], "Annihilation")


def _field_ok(label: str, cls: str, field: str, value, reads: dict) -> None:
    try:
        v = S.validator_for(cls, field)
    except KeyError:
        require(f"{label}: {field} is declared on AUTO-MAS {cls}", False, "not declared")
        return
    require(f"{label}: {field}={value!r} passes AUTO-MAS's {type(v).__name__}", v.validate(value))
    require(f"{label}: {field} is read by AUTO-MAS", field in reads, "no reader in " + ", ".join(S.READERS))


def _sent_fields(path_suffix: str) -> list[tuple[str, object]]:
    out = []
    for p, b in BACKEND.updates():
        if p.endswith(path_suffix):
            for group, items in (b.get("data") or {}).items():
                out += [(f"{group}.{k}", v) for k, v in items.items()]
    return out


def case_user() -> None:
    commands = _commands()
    reads = S.automas_reads()
    for label, call in (("set_stage 1-7 (" + EVIDENCE["one_seven"][:40] + "...)", lambda: commands._set_stage("1-7")),
                        ("set_medicine 0", lambda: commands._set_medicine(0)),
                        ("set_medicine 999", lambda: commands._set_medicine(999))):
        before = _start(_with_user(Stage="YW-4", MedicineNumb=5), "tag")
        ok, msg = call()
        require(f"{label}: accepted", ok, msg)
        fields = _sent_fields("/user/update")
        require(f"{label}: one field sent", len(fields) == 1, repr(fields))
        for field, value in fields:
            _field_ok(label, "MaaUserConfig", field, value, reads)
        check(f"{label}: ScriptConfig.json untouched", _file(before), "untouched")

    # Probes at AUTO-MAS's own range ends: whatever set_medicine lets through must be a
    # value AUTO-MAS keeps (out of range it would quietly clamp it: RangeValidator.correct).
    v = S.validator_for("MaaUserConfig", "Info.MedicineNumb")
    for n in (v.min - 1, v.min, v.max, v.max + 1):
        _start(_with_user(MedicineNumb=5), "tag")
        ok, _ = commands._set_medicine(n)
        sent = [value for field, value in _sent_fields("/user/update") if field == "Info.MedicineNumb"]
        require(f"set_medicine {n}: sends only what AUTO-MAS keeps", all(v.validate(x) for x in sent),
                f"sent {sent}")


class _Clock(datetime):
    """datetime whose now() is AT (a virtual clock for both sides)."""
    AT = datetime(2026, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.AT.astimezone(tz) if tz else cls.AT


def case_handover() -> None:
    handover = importlib.import_module("automas_handover")
    reads = S.automas_reads()
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "state.json").write_text(json.dumps({"weekly": {"annihilation": {
        "done_week": "2026-W35", "restore_to": "Annihilation"}}}), encoding="utf-8")
    _start(_with_user(Annihilation="Close"))
    BACKEND.cfg[MAA_SID]["Run"].update(IfCheckGameUpdate=False, IfAutoInstallGameApk=False)
    _quiet(handover.plan, STATE, TMP / "okww", False, True, ["13", "10a"])
    user_fields = _sent_fields("/user/update")
    script_fields = _sent_fields("/scripts/update")
    check("handover: user fields written", sorted(f for f, _ in user_fields), ["Info.Annihilation"])
    check("handover: script fields written", sorted(f for f, _ in script_fields),
          ["Run.IfAutoInstallGameApk", "Run.IfCheckGameUpdate"])
    for field, value in user_fields:
        _field_ok("handover", "MaaUserConfig", field, value, reads)
    for field, value in script_fields:
        _field_ok("handover", "MaaConfig", field, value, reads)
    _field_ok("handover", "MaaUserConfig", "Data.AnnihilationCompletedWeek", handover.this_week(), reads)

    proxy = S.load_upstream("app/task/MAA/AutoProxy.py", ["_current_week_marker"], {"datetime": datetime})
    const = S.load_upstream("app/utils/constants.py", ["UTC4", "ARKNIGHTS_GAME_DAY_TZ", "get_game_day_tz", "game_now"],
                            {"timezone": timezone, "timedelta": timedelta, "datetime": _Clock})
    weekly = _module("ark_relay.features.weekly.annihilation", "ark_relay.annihilation")
    sh = timezone(timedelta(hours=8))
    real = handover.datetime
    handover.datetime = _Clock
    try:
        for at in (datetime(2026, 8, 31, 3, 59, tzinfo=sh), datetime(2026, 8, 31, 4, 0, tzinfo=sh),
                   datetime(2026, 10, 18, 23, 59, tzinfo=sh), datetime(2026, 12, 28, 4, 0, tzinfo=sh),
                   datetime(2027, 1, 4, 3, 59, tzinfo=sh), datetime(2027, 1, 4, 4, 0, tzinfo=sh)):
            _Clock.AT = at
            want = proxy["_current_week_marker"](const["game_now"]("Official"))
            check(f"week marker {at:%Y-%m-%d %H:%M} Beijing: handover writes AUTO-MAS's", handover.this_week(), want)
            check(f"week marker {at:%Y-%m-%d %H:%M} Beijing: the relay's reader agrees", weekly.week_key(at), want)
    finally:
        handover.datetime = real


def case_guinew() -> None:
    mcfg = _module("ark_relay.core.mastercfg_maa", "ark_relay.mastercfg")
    infrast_cs = "src/MaaWpfGui/Configuration/Single/MaaTask/InfrastTask.cs"
    award_cs = "src/MaaWpfGui/Configuration/Single/MaaTask/AwardTask.cs"
    check("drone values = MAA's UsesOfDronesList", [k for k, _ in mcfg.MAA_DRONES], S.drone_keys())
    check("UsesOfDrones is a string property of InfrastTask", S.cs_properties(infrast_cs).get("UsesOfDrones"), "string")
    drones = S.core_param("src/MaaWpfGui/Models/AsstTasks/AsstInfrastTask.cs", "UsesOfDrones")
    require(f"MaaCore's Infrast reads {drones!r}",
            drones in S.core_reads("src/MaaCore/Task/Interface/InfrastTask.cpp"), "not read")
    award_reads = S.core_reads("src/MaaCore/Task/Interface/AwardTask.cpp")
    for key, _ in mcfg.MAA_AWARD:
        check(f"Award/{key} is a bool property of AwardTask", S.cs_properties(award_cs).get(key), "bool")
        param = S.core_param("src/MaaWpfGui/Models/AsstTasks/AsstAwardTask.cs", key)
        require(f"Award/{key} reaches MaaCore as {param!r}", param in award_reads, "not read")

    const = S.load_upstream("app/utils/constants.py", ["MAA_TASKS", "MAA_TASKS_ZH"], {})
    zh = dict(zip(const["MAA_TASKS"], const["MAA_TASKS_ZH"], strict=True))
    preset = S.load_upstream("app/task/MAA/base_preset.py", ["maa_task_identity"], {})
    proxy = S.load_upstream("app/task/MAA/AutoProxy.py", ["_find_task_source"],
                            {"deepcopy": copy.deepcopy, "maa_task_identity": preset["maa_task_identity"]})
    copy_source = S.load_method("app/task/MAA/AutoProxy.py", "AutoProxyTask._copy_source_config",
                                {"shutil": shutil, "Path": Path,
                                 "logger": types.SimpleNamespace(info=lambda *a, **k: None)})
    user = SCRIPT_CONFIG[MAA_SID]["SubConfigsInfo"]["UserData"]
    mode = user[user["instances"][0]["uid"]]["Info"]["Mode"]
    require("the machine's MAA user takes its config from the script folder (Info.Mode 脚本)",
            mode == "脚本" and 'f"data/{self.script_info.script_id}/Default/ConfigFile"'
            in S.automas_text("app/task/MAA/AutoProxy.py"), mode)
    derived = S.derived_types()

    writes = [("Infrast/UsesOfDrones", "Infrast", "UsesOfDrones", v) for v in S.drone_keys()]
    writes += [(f"Award/{k}", "Award", k, flip) for k, _ in mcfg.MAA_AWARD for flip in (False, True)]
    for path, task_type, key, value in writes:
        root = TMP / "guinew" / f"{path.replace('/', '-')}-{value}"
        master = root / "AUTO-MAS" / "data" / MAA_SID / "Default" / "ConfigFile"
        maa_config = root / "MAA" / "config"
        for d in (master, maa_config):
            d.mkdir(parents=True)
            (d / "gui.new.json").write_bytes(GUI_NEW)
        ok, msg = mcfg.write_maa(root / "AUTO-MAS", root / "MAA", path, value)
        require(f"write_maa {path}={value!r}: accepted", ok, msg)
        (maa_config / "gui.new.json").write_bytes(GUI_NEW)   # AUTO-MAS overwrites MAA's own copy anyway
        copy_source(types.SimpleNamespace(maa_set_path=maa_config), master)
        doc = json.loads((maa_config / "gui.new.json").read_text(encoding="utf-8"))
        queue = doc["Configurations"][doc["Current"]]["TaskQueue"]
        task = proxy["_find_task_source"](queue, zh[task_type], task_type) or {}
        check(f"{path}={value!r}: AUTO-MAS hands MAA the value", task.get(key), value)
        require(f"{path}={value!r}: under a $type MAA deserialises", task.get("$type") in derived, task.get("$type"))
        want = json.loads(GUI_NEW)
        for t in want["Configurations"][want["Current"]]["TaskQueue"]:
            if t.get("TaskType") == task_type:
                t[key] = value
        check(f"{path}={value!r}: nothing else in gui.new.json changed", doc, want)


CASES = {"pin": case_pin, "yw4": case_yw4, "annihilation": case_annihilation,
         "user": case_user, "handover": case_handover, "guinew": case_guinew}


def main() -> int:
    logging.disable(logging.WARNING)
    for name in sys.argv[1:] or list(CASES):
        print(f"[{name}]")
        CASES[name]()
    BACKEND.srv.shutdown()
    if fails:
        print(f"FAIL: {len(fails)} check(s): " + "; ".join(fails[:6]))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
