"""daysim W5: the day replay runs end to end (design.md section 6, W5's row).

Without the recorded corpus (CI) it checks the World's own pieces:
* the boot plan of 2026-10-12: 18 relay lives, 4 of them before 09:13, each ending at
  its recorded stop, the first one counted from the estimated power-on;
* the inputs rebuilt from the record: phone orders as the phone page sends them
  (debug_mode off is {"off": true}: a body {"on": false} would turn it ON), inbox
  files as scripts/mac/order.sh writes them;
* at one recorded second the AUTO-MAS task opens before its run starts;
* the scheduler adapter files W2's "sim_errors" and W3's "sim_error" as one kind;
* a boot refuses to start the relay unless every network door is the fake's.

With the corpus (the owner's Mac; a missing corpus fails there) it replays the
morning of 2026-10-12 up to 09:20 - four boots, each its own process - and checks
the two MAA verdicts (both runs ok, handled after AUTO-MAS wrote their files at
09:18:45), that every boot ended by its own stop, that pushes were captured as
outputs, and that no sim error happened (no unrouted command, URL or socket).
"""
import json
from datetime import datetime
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "daysim"))
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


check("daysim world.py, boot.py and run.py exist",
      all((HERE / "daysim" / f).is_file() for f in ("world.py", "boot.py", "run.py")))
if fails:
    print(f"\n{len(fails)} failed: {fails}")
    sys.exit(1)

import world as W  # noqa: E402

# ---- the boot plan
events, seed = W.load_day("2026-10-12")
boots = W.plan_boots(events, seed)
check("10-12: 18 relay lives", len(boots), 18)
check("10-12: 4 of them before 09:13",
      sum(b["start"] < W.epoch("2026-10-12T09:13:00+08:00") for b in boots), 4)
check("10-12: the first starts at 08:45:26, after the estimated power-on 08:44:26",
      (W.iso(boots[0]["start"]), W.iso(boots[0]["power_on"]), boots[0]["after"]),
      ("2026-10-12T08:45:26+08:00", "2026-10-12T08:44:26+08:00", "power_on"))
check("10-12: the 12:00:27 life ends at the relay's own power-off 12:11:36",
      (W.iso(boots[7]["end"]), boots[7]["relay_poweroff"]), ("2026-10-12T12:11:36+08:00", True))
check("10-12: the last life ends at the outside shutdown 22:13:33",
      (W.iso(boots[-1]["end"]), boots[-1]["how"]), ("2026-10-12T22:13:33+08:00", "windows_shutdown"))
cut = W.plan_boots(events, seed, W.epoch("2026-10-12T09:20:00+08:00"))
check("10-12 until 09:20: 4 lives, the last cut at 09:20 (day_end)",
      (len(cut), W.iso(cut[-1]["end"]), cut[-1]["how"]), (4, "2026-10-12T09:20:00+08:00", "day_end"))
s13, e13 = W.load_day("2026-10-13")[1], W.load_day("2026-10-13")[0]
b13 = W.plan_boots(e13, s13)
check("10-13: the last life has no recorded stop and ends at the pull 15:26:37",
      (W.iso(b13[-1]["end"]), b13[-1]["how"]), ("2026-10-13T15:26:37+08:00", "day_end"))
e06, s06 = W.load_day("2026-10-06")
check("10-06: the relay was running at 00:00, so the first life starts at t0",
      (W.iso(W.plan_boots(e06, s06)[0]["start"]), W.plan_boots(e06, s06)[0]["after"]),
      ("2026-10-06T00:00:00+08:00", "running_at_t0"))

# ---- inputs rebuilt from the record
check("phone debug_mode off -> {off: true}",
      W.phone_body({"action": "debug_mode", "args": {"on": False}}),
      {"action": "debug_mode", "off": True, "confirmed": True})
check("phone debug_mode on -> the page's 90-minute body",
      W.phone_body({"action": "debug_mode", "args": {"on": True}}),
      {"action": "debug_mode", "minutes": 90, "confirmed": True})
check("phone skip_shutdown on", W.phone_body({"action": "skip_shutdown", "args": {"on": True}}),
      {"action": "skip_shutdown"})
check("inbox 「调试模式」 -> one debug_mode command",
      W.inbox_doc({"version": "2026101201", "title": "从电脑发来的指令：调试模式"})["commands"],
      [{"action": "debug_mode"}])
check("inbox 「空（安全状态）」 -> no command",
      W.inbox_doc({"version": "2026101202", "title": "从电脑发来的指令：空（安全状态）"})["commands"], [])
tl = W.timeline(events)
at1141 = [(x["kind"], x["ev"].get("op")) for x in tl if W.iso(x["t"]) == "2026-10-12T11:41:07+08:00"]
check("11:41:07: the AUTO-MAS task opens before the hand-started run starts",
      at1141.index(("mas_backend", "task_start")) < at1141.index(("run_start", None)), True)
inbox = [x for x in tl if x["kind"] == "inbox"]
check("inbox files are in place a minute before the relay's recorded reads",
      [W.iso(x["t"]) for x in inbox], ["2026-10-12T08:45:00+08:00", "2026-10-12T12:09:00+08:00"])


class _Net:
    """FakeNet's two members World._phone uses: phone_order takes its id from next_id."""

    def __init__(self):
        self.ids = []

    def next_id(self):
        return "sim000000001"

    def phone_order(self, t, body, pin, topic, ts=None):
        self.ids.append(self.next_id())


net = _Net()
host = type("H", (), {"net": net, "note": lambda self, *a, **k: None})()
W.World._phone(host, {"t": "2026-10-13T08:46:37+08:00", "action": "skip_shutdown", "id": "zXr0rD3dId01",
                      "args": {"on": True}})
W.World._phone(host, {"t": "2026-10-13T08:47:00+08:00", "action": "skip_shutdown", "args": {"on": True}})
check("a phone order carries its recorded ntfy id, and the fake's own numbering comes back after it",
      (net.ids, "next_id" in net.__dict__), (["zXr0rD3dId01", "sim000000001"], False))


class _SC:
    def __init__(self):
        self.got = []
        self.now = self.at = self.park = self.advance = self.poke = lambda *a, **k: None

    def out(self, kind, **f):
        self.got.append(kind)


sc = _SC()
W.Sched(sc).out("sim_errors", what="x")
W.Sched(sc).out("sim_error", what="y")
check("W2's sim_errors and W3's sim_error are one kind", sc.got, ["sim_error", "sim_error"])
try:
    W.assert_offline(object())
    refused = False
except SystemExit:
    refused = True
check("a boot without the network fakes refuses to start the relay", refused)

# ---- the programs' own files and the outside services (triage 10-13)
# Without them a replayed day was full of WARNINGs the machine never logged (none of
# 「母本配置文件不在」, 「找不到 app.asar」, 「MAA 的关卡资料读不了」 is in the 10-06/12/13 record).
import os  # noqa: E402

import install  # noqa: E402

man = install.load()
paths = {f["path"] for f in man["files"]}
check("install.json lists MaaEnd's interface, zh_cn locale, nodes.json and config",
      {"D/ark/maaend/interface.json", "D/ark/maaend/locales/interface/zh_cn.json",
       "D/ark/maaend/resource/pipeline/nodes.json", "D/ark/maaend/config/mxu-MaaEnd.json"} <= paths, True)
check("install.json lists OK-WW's configs and app.json, MAA's gui.new.json and YW.json",
      {"D/ark/okww/data/apps/ok-ww/working/configs/DailyTask.json", "D/ark/okww/data/apps/ok-ww/app.json",
       "D/ark/maa/config/gui.new.json", "D/ark/maa/resource/tasks/Stages/YW.json"} <= paths, True)
check("every install copy has a sha256 and a source", all(len(f["sha256"]) == 64 and f["src"] for f in man["files"]),
      True)

tree = tmpdir("daysim-install-")
root = tmpdir("daysim-install-root-")
T0 = W.epoch("2026-10-13T00:00:00+08:00")
(tree / W.AUTOMAS_REL / "config").mkdir(parents=True)
(tree / W.AUTOMAS_REL / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": [
    {"uid": "u-maa", "type": "MaaConfig"}, {"uid": "u-end", "type": "MaaEndConfig"},
    {"uid": "u-okww", "type": "OkwwConfig"}]}), encoding="utf-8")
mini = {"files": []}
for rel, body, mt in (("D/ark/okww/data/apps/ok-ww/working/configs/DailyTask.json", '{"Which to Farm": "x"}',
                       "2026-09-07T14:19:32"),
                      ("D/ark/okww/data/apps/ok-ww/working/configs/NightmareNestTask.json", '{"_enabled": true}',
                       "2026-09-09T14:22:25"),
                      ("D/ark/maaend/config/mxu-MaaEnd.json", '{"instances": []}', "2026-10-13T09:59:15"),
                      ("D/ark/maa/config/gui.new.json", '{"Current": "Default"}', "2026-10-11T08:46:15")):
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(body, encoding="utf-8")
    mini["files"].append({"path": rel, "sha256": "0" * 64, "len": len(body.encode()), "mtime": mt, "src": "test"})
(tree / "D/ark/maaend/config").mkdir(parents=True)
(tree / "D/ark/maaend/config/mxu-MaaEnd.json").write_text('{"seed": 1}', encoding="utf-8")
missing = install.plant(tree, T0, automas_rel=W.AUTOMAS_REL, clone=W.clone, nests="梦枢天罗,落渊南丘",
                        root=root, man=mini)
check("every copy planted", missing, [])
sys.path.append(str(W.RELAY))      # appended: relay/run.py must not shadow daysim's run.py
from ark_relay.core.config import master_config_dir  # noqa: E402
from ark_relay.core.mastercfg_maa import maa_master  # noqa: E402
am = tree / W.AUTOMAS_REL
check("OK-WW's master dir is found by its marker (config.master_config_dir)",
      master_config_dir(am, "DailyTask.json"), am / "data" / "u-okww" / "Default" / "ConfigFile")
check("MaaEnd's master dir is found by mxu-MaaEnd.json",
      master_config_dir(am, "mxu-MaaEnd.json"), am / "data" / "u-end" / "Default" / "ConfigFile")
check("MAA's master gui.new.json is found (mastercfg_maa.maa_master)",
      maa_master(am), am / "data" / "u-maa" / "Default" / "ConfigFile" / "gui.new.json")
check("a file the seed carries is not overwritten",
      (tree / "D/ark/maaend/config/mxu-MaaEnd.json").read_text(encoding="utf-8"), '{"seed": 1}')
nest = json.loads((am / "data/u-okww/Default/ConfigFile/NightmareNestTask.json").read_text(encoding="utf-8"))
check("the master's 「Only Farm These Nests」 is the day's", nest.get("Only Farm These Nests"), "梦枢天罗,落渊南丘")
check("the script-side copy keeps OK-WW's own keys only",
      "Only Farm These Nests" in (tree / "D/ark/okww/data/apps/ok-ww/working/configs/NightmareNestTask.json")
      .read_text(encoding="utf-8"), False)
check("a 10-13 09:59 copy is not newer than the day's start",
      os.stat(am / "data/u-end/Default/ConfigFile/mxu-MaaEnd.json").st_mtime <= T0 - 1, True)
check("an older copy keeps its machine mtime (2026-09-07 14:19:32 Beijing)",
      os.stat(am / "data/u-okww/Default/ConfigFile/DailyTask.json").st_mtime,
      W.epoch("2026-09-07T14:19:32+08:00"))
check("ok-ww.exe, pythonw.exe and main.py exist (preupdate_okww / echofarm check for them)",
      all((tree / x).is_file() for x in install.PLACEHOLDERS), True)
(tree / W.DATA_REL / "state").mkdir(parents=True)
(tree / W.DATA_REL / "state" / "asar-labels.json").write_text(
    json.dumps({"stamp": "71537389-1791608162", "map": {}}), encoding="utf-8")
check("app.asar: the stamp of the relay's own label cache", install.asar_stub(tree, W.AUTOMAS_REL, W.DATA_REL + "/state"),
      "71537389-1791608162")
st = os.stat(am / "resources" / "app.asar")
check("app.asar has that size and mtime, so plan._asar_value_labels takes its cache",
      f"{st.st_size}-{int(st.st_mtime)}", "71537389-1791608162")

# Skland, from the record's #10 lines (the session handed to the phone, check #10).
corp = tmpdir("daysim-sk-")
rl = corp / "files" / "C" / "ProgramData" / "ark-relay" / "relay.log"
rl.parent.mkdir(parents=True)
rl.write_text("10-12 23:59:00 INFO    ark.machinecheck  上机核对 #10 过了：x curStamina=1 maxStamina=360 maxTs=5\n"
              "10-13 08:46:02 INFO    ark.machinecheck  上机核对 #10 过了：08:46:00 森空岛会话交给手机（6 项都在）；"
              "森空岛给的终末地体力：curStamina=188 maxStamina=360 maxTs=1791926664\n"
              "10-13 11:03:56 INFO    ark.machinecheck  上机核对 #10 过了：11:03:54 森空岛会话交给手机（6 项都在）；"
              "森空岛给的终末地体力：curStamina=48 maxStamina=360 maxTs=1791995418\n", encoding="utf-8")
stam = W.recorded_stamina(corp, {"files": [{"path": "C:/ProgramData/ark-relay/relay.log"}]}, "2026-10-13")
check("the day's #10 lines only, at the time each session was made",
      [(W.iso(t), s["curStamina"]) for t, s in stam],
      [("2026-10-13T08:46:00+08:00", 188), ("2026-10-13T11:03:54+08:00", 48)])
clock = [W.epoch("2026-10-13T10:00:00+08:00")]
routes = W.web_routes(lambda: clock[0], stam)


class _Resp:
    def __init__(self, body):
        self.body = json.dumps(body).encode() if not isinstance(body, (bytes, str)) else (
            body.encode() if isinstance(body, str) else body)
        self.headers = {}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen(req, timeout=None, **kw):
    import urllib.parse  # noqa: PLC0415
    url = req.full_url if hasattr(req, "full_url") else str(req)
    for prefix, answer in routes.items():
        if url.startswith(prefix):
            call = type("C", (), {"query": dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))})()
            return _Resp(answer(call) if callable(answer) else answer)
    raise AssertionError(f"unrouted {url}")


import urllib.request  # noqa: E402
from ark_relay.features.phone import resources  # noqa: E402
real_urlopen, urllib.request.urlopen = urllib.request.urlopen, _urlopen
try:
    sk = resources.skland_session(type("Cfg", (), {"skland_token": "daysim"})())
    probe = resources.probe()
finally:
    urllib.request.urlopen = real_urlopen
check("the session the phone gets has the six keys check #10 asks for",
      [k for k in ("cred", "token", "dId", "uid", "efRole", "efServer") if not sk.get(k)], [])
check("Skland's stamina at 10:00 is the record's 08:46 reading",
      probe.get("dungeon"), {"curStamina": 188, "maxStamina": 360, "maxTs": 1791926664})

# OK-WW's own doings the record shows: the overrides' report, and its update check.
line = (b"2026-10-12 09:19:07,833 INFO MainThread task_manager:Found tasks: "
        b"['D:\\\\ark\\\\okww\\\\data\\\\apps\\\\ok-ww\\\\working\\\\ok_tasks\\\\ark_overrides.py']\n")
m = W.OVERRIDES_LOADED.search(b"2026-10-12 09:19:05,140 INFO MainThread DeviceManager:__init__ start\n" + line)
check("the overrides' load line is found, with its second", m and m.group(1).decode(), "2026-10-12 09:19:07")
otree = tmpdir("daysim-overlay-")
src = otree / "_sim" / "code" / "ark_relay" / "features" / "okww_patch" / "okww_files"
src.mkdir(parents=True)
shutil_src = W.RELAY / "ark_relay" / "features" / "okww_patch" / "okww_files" / "ark_overrides.tasks.py"
(src / "ark_overrides.tasks.py").write_bytes(shutil_src.read_bytes())
host = type("H", (), {"tree": otree, "stamp": W.World.stamp, "error": lambda self, *a, **k: None})()
at = W.epoch("2026-10-12T09:19:07+08:00")
W.World._overlay_report(host, at)
rep = otree / "C" / "ProgramData" / "ark-okww-overlay.json"
got = json.loads(rep.read_text(encoding="utf-8")) if rep.is_file() else {}
check("the report names find_nest applied, nothing skipped (the record's #26: 「装上」)",
      ("NightmareNestTask.find_nest" in got.get("applied", []), got.get("skipped"), got.get("error")),
      (True, [], ""))
check("written at the load line's second", os.stat(rep).st_mtime if rep.is_file() else 0, at)

ptree = tmpdir("daysim-okww-pre-")
app = ptree / "D/ark/okww/data/apps/ok-ww/app.json"
app.parent.mkdir(parents=True)
app.write_text('{"current_version": "v3.7.4"}', encoding="utf-8")
os.utime(app, (T0, T0))
started, timers, changed = [], [], []
procs_ = type("P", (), {"start": lambda self, image, *a, **k: started.append(image)})()
host = type("H", (), {"tree": ptree, "tp": lambda self, p: W.tpath(ptree, p), "note": lambda self, *a, **k: None,
                      "changed": lambda self, p: changed.append(p),
                      "win": type("Win", (), {"procs": procs_})(),
                      "sched": type("S", (), {"now": lambda self: T0 + 100,
                                              "at": lambda self, t, fn, tag: timers.append((t, fn))})()})()
W.World._okww_preupdate(host, r"D:\ark\okww\ok-ww.exe", "")
check("ok-ww.exe starts for its update check", started, ["ok-ww.exe"])
check("app.json is rewritten a few seconds after the launch",
      [t - (T0 + 100) for t, _fn in timers], [W.OKWW_APPJSON_REWRITE_S])
for _t, fn in timers:
    fn()
check("the rewrite moves app.json's mtime (preupdate_okww reads that as 「checked」)",
      (os.stat(app).st_mtime > T0, changed), (True, [app]))

# ---- World.prepare: inputs of an earlier power cycle do not reach this one's processes
import fake_proc  # noqa: E402


class _Mas:
    def __init__(self):
        self.calls = []
        self.shadow = Path("/nonexistent-daysim-shadow")

    def stop(self):
        self.calls.append("stop")

    def start(self):
        self.calls.append("start")

    def set_tasks(self, tasks):
        pass


def bare_world(boot: dict, events: list, seed=None) -> "W.World":
    """A World with its process table and the given inputs, no relay and no fakes beyond
    the process table: enough for prepare()."""
    w = W.World.__new__(W.World)
    w.boot, w.events, w.seed = boot, events, seed or {"t0": W.iso(T0)}
    w.items, w.applied, w.tasks = W.timeline(events), set(), []
    w.win = fake_proc.WinState(None, power_on=boot["power_on"])
    w.mas = _Mas()
    w.notes = []
    w.note = lambda what, **f: w.notes.append(what)
    w.error = lambda what, **f: w.notes.append("ERROR " + what)
    return w


def ev(hhmmss: str, kind: str, **f) -> dict:
    return {"t": f"2026-10-13T{hhmmss}+08:00", "kind": kind, "src": "test", **f}


w = bare_world({"start": T0 + 8 * 3600 + 120, "power_on": T0 + 8 * 3600, "end": T0 + 9 * 3600},
               [ev("03:00:00", "proc", op="start", image="MAA.exe", path=r"D:\ark\maa\MAA.exe"),
                ev("04:08:17", "power_off", by="outside")])
w.prepare()
check("a power-off before this power-on leaves the AUTO-MAS window this power-on starts (10-11 08:45)",
      [p.image for p in w.win.procs.named("AUTO-MAS.exe")], ["AUTO-MAS.exe"])
w = bare_world({"start": T0 + 13 * 3600 + 60, "power_on": T0 + 13 * 3600, "end": T0 + 14 * 3600},
               [ev("12:05:00", "proc", op="start", image="MAA.exe", path=r"D:\ark\maa\MAA.exe")])
w.prepare()
check("a program from before a relay power-off (no power_off input) is gone after the next power-on",
      [p.image for p in w.win.procs.named("MAA.exe")], [])
w = bare_world({"start": T0 + 13 * 3600 + 60, "power_on": T0 + 13 * 3600, "end": T0 + 14 * 3600},
               [ev("13:00:30", "proc", op="start", image="MAA.exe", path=r"D:\ark\maa\MAA.exe")])
w.prepare()
check("a program started after this power-on is still running at the relay's start",
      [p.image for p in w.win.procs.named("MAA.exe")], ["MAA.exe"])

faults = []
host = type("H", (), {"net": type("N", (), {"fault": lambda self, m, k, **f: faults.append((m, k, f))})(),
                      "note": lambda self, *a, **k: None})()
fev = {"t": "2026-10-08T21:49:04+08:00", "kind": "net_fault", "src": "x:1", "channel": "ntfy_publish",
       "error": "TimeoutError: The read operation timed out"}
item = W.timeline([fev])[0]
# mailbox.Mailbox.POST_TIMEOUT 20 s, and one: the fault is in place when that publish begins
check("an ntfy publish timeout is applied when the publish began, not at its line",
      item["t"], W.epoch(fev["t"]) - 21)
W.World._fault(host, fev, item["t"])
check("it fails the next POST to the phone topic from then on",
      faults, [(f"ntfy.sh/{W.PHONE_TOPIC}", "timeout", {"method": "POST", "start": W.epoch(fev["t"]) - 21,
                                                         "title": None})])
sev = {**fev, "what": "state"}
item = W.timeline([sev])[0]
faults.clear()
W.World._fault(host, sev, item["t"])
check("a failed state publish: the next state publish from two minutes before the machine's (10-08: the sim's "
      "关机前 state went out at 21:48:00, the machine's at 21:48:42)",
      faults, [(f"ntfy.sh/{W.PHONE_TOPIC}", "timeout", {"method": "POST", "start": W.epoch(fev["t"]) - 21 - 120,
                                                         "title": "state"})])

# ---- outside inputs (days/<D>/outside.jsonl): state.json edits and web answers
evs11, _seed = W.load_day("2026-10-11")
check("10-11: the four outside state.json edits are inputs (skip mark x2, its removal, debug mode)",
      [(e["t"][11:19], sorted(e.get("set") or e.get("pop"))) for e in evs11 if e["kind"] == "state_edit"],
      [("09:12:00", ["skip_next_shutdown"]), ("10:05:00", ["skip_next_shutdown"]), ("12:30:00", ["skip_next_shutdown"]),
       ("14:24:50", ["debug_until"])])
stree = tmpdir("daysim-state-edit-")
st = stree / W.DATA_REL / "state" / "state.json"
st.parent.mkdir(parents=True)
st.write_text(json.dumps({"marks": {"a": 1}, "modes": {"shutdown_skipped": "x"}}), encoding="utf-8")
w = bare_world({"start": T0, "power_on": T0 - 60, "end": T0 + 3600}, [])
w.tree, w.fw = stree, type("FW", (), {"files_changed": lambda self, p: None})()
edit = {"t": "2026-10-13T09:12:00+08:00", "kind": "state_edit", "section": "modes", "set": {"skip_next_shutdown": True},
        "src": "BOARD/x.txt:1", "why": "w"}
w.disk_effect({"kind": "state_edit", "ev": edit, "t": W.epoch(edit["t"])})
got = json.loads(st.read_text(encoding="utf-8"))
check("an outside edit sets its key and keeps the rest of state.json",
      (got.get("modes"), got.get("marks")), ({"shutdown_skipped": "x", "skip_next_shutdown": True}, {"a": 1}))
check("stamped at its time (StateStore rereads on a new mtime)", os.stat(st).st_mtime, W.epoch(edit["t"]))
w.disk_effect({"kind": "state_edit", "ev": {**edit, "set": None, "pop": ["skip_next_shutdown"]}, "t": W.epoch(edit["t"]) + 60})
check("a pop removes it", json.loads(st.read_text(encoding="utf-8")).get("modes"), {"shutdown_skipped": "x"})
webs = []
w.net = type("N", (), {"set_web": lambda self, p, a: webs.append(p)})()
evs09, _seed = W.load_day("2026-10-09")
for it in W.timeline(evs09):
    if it["kind"] == "web":
        w.state_effect(it, live=False)
check("10-09: the maintenance notice is served (list and post)", webs,
      ["https://ak.hypergryph.com/api/news?category=ANNOUNCEMENT",
       "https://web-news.hypergryph.com/api/bulletin/daysim-1009-maint"])

# ---- AUTO-MAS's version as its app.log has it at each moment (10-09: v5.6.2 until 08:47:54)
vc = tmpdir("daysim-masver-")
part = ("2026-10-09 08:46:40.813 | INFO     | 配置管理 | 版本号:  v5.6.2\n"
        "2026-10-09 08:46:46.304 | INFO     | 主程序 | HTTP Request: GET https://mirrorchyan.com/api/resources/AUTO_MAS/latest"
        "?os=win&current_version=v5.6.2&channel=beta \"HTTP/1.1 200 OK\"\n"
        "2026-10-09 08:47:13.373 | INFO     | 更新服务 | 启动更新程序\n"
        "2026-10-09 08:47:54.990 | INFO     | 配置管理 | 版本号:  v5.7.0-beta.1\n").encode("utf-8")
(vc / "app.part").write_bytes(part)
w = bare_world({"start": T0, "power_on": T0 - 60, "end": T0 + 3600},
               [{"t": "2026-10-09T08:46:40+08:00", "kind": "log_chunk", "src": "x:1", "path": "D:/ark/automas/debug/app.log",
                 "file": "app.part", "off": 0, "len": len(part)}])
w.corpus, w.tree, w._versions = vc, vc, None


def mas_version(hms: str) -> str:
    at = W.epoch(f"2026-10-09T{hms}+08:00")
    try:
        return w.automas_version(at)
    except TypeError:                     # a World that knows one version for the whole day
        return w.automas_version()


check("AUTO-MAS's version: v5.6.2 at the boot (08:45), still at 08:47:30, v5.7.0-beta.1 once back (08:48)",
      [mas_version(x) for x in ("08:45:21", "08:47:30", "08:48:00")], ["v5.6.2", "v5.6.2", "v5.7.0-beta.1"])

# ---- the relay running at 00:00: the sim's stop then reads as a stop to #11
from ark_relay.features.selfcheck.machinechecks import system as sysmc  # noqa: E402

seed11 = {"t0": "2026-10-11T00:00:00+08:00", "machine": {"power": "on", "relay": "running"}}
logdir = tmpdir("daysim-t0stop-")
prev = ("10-10 23:38:46 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）\n"
        "10-10 23:38:46 INFO    ark.service  中继代码版本 v20261010143151\n"
        "10-10 23:39:30 INFO    ark.service  📱 已上报状态到手机（开机；今天 ntfy 已用 30 条）\n")
now = "10-11 00:00:00 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）\n"
(logdir / "relay.log").write_text(prev + getattr(W, "t0_stop_lines", lambda s: "")(seed11) + now, encoding="utf-8")
(logdir / "state").mkdir()
res = sysmc._stop_push({"log_file": str(logdir / "relay.log"), "state_dir": str(logdir / "state"),
                        "now": datetime.fromisoformat("2026-10-11T00:00:49+08:00")})
check("relay running at 00:00: #11 reads the sim's stop as a stop with its push (10-11 00:00:49)",
      getattr(res, "status", None), "PASS")
check("relay off at 00:00: no stop lines", getattr(W, "t0_stop_lines", lambda s: "")({**seed11, "machine": {"relay": "stopped"}}), "")

# ---- the morning of 10-12, end to end
corpus = W.CORPUS_ROOT / "2026-10-12"
owner_mac = sys.platform == "darwin" and (Path.home() / "Claude" / "maa-automation").is_dir()
if (corpus / "manifest.json").exists():
    import run
    out = tmpdir("daysim-smoke-")
    r = run.run_day("2026-10-12", code=W.RELAY, until="09:20", out_root=out)
    o = json.loads((out / "2026-10-12" / "outputs.json").read_text(encoding="utf-8"))
    rows = {x["run_id"]: x for x in o["ledger"]}
    for stem in ("MAA-05-00-26", "MAA-05-03-42"):
        row = rows.get(f"2026-10-12/arknights/{stem}") or {}
        check(f"verdict {stem}: ok, no failed item", (row.get("ok"), row.get("failed_tasks")), (True, []))
    check("4 boots, each ended by its own stop", [b["exit"] for b in o["boots"]], ["returned"] * 4)
    check("no sim error", o["sim_errors"], [])
    check("pushes captured as outputs (ntfy: the boots' state and heartbeat)",
          "ntfy" in {p["ch"] for p in o["pushes"]}, True)
    # The record's only group push before 09:20 is 08:46:15 「中继自己报错了（预更新）」, R30,
    # whose route 6bf43317 removed; with the programs' own files planted (install.py) the
    # morning is otherwise as quiet as the machine's.
    check("no group push in the morning", [(p["t"], p["title"]) for p in o["pushes"] if p["ch"] == "group"], [])
    check("the morning stays within the day's budget (CPU seconds; this Mac is shared)",
          r["cpu_s"] < run.DAY_CAP_S, True)
elif owner_mac:
    check(f"10-12 corpus present on the owner's Mac ({corpus})", False)
else:
    print(f"  - no corpus on this machine ({corpus}); the end-to-end morning is skipped")

print(f"\n{'all checks passed' if not fails else f'{len(fails)} failed: {fails}'}")
sys.exit(1 if fails else 0)
