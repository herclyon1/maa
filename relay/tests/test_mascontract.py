"""The relay notices at once when an AUTO-MAS update moves a setting it reads.

10-14: AUTO-MAS v5.7.0-beta.3, installed by the relay's own pre-update at 08:46 Beijing, moved
the MAA user's stage items from Info to a new Stage group. The relay read Info, got nothing,
treated it as "no stage set" (stage gate placeholder at 08:55:27), and nothing reached the
group for 13 hours: the boot self-check had run at 08:45, on the old version.

* ark_relay/core/mascontract.py lists every AUTO-MAS setting the relay reads, and check()
  finds each one in the config files (through masuser for the moved keys);
* the boot self-check has it as one item, and a miss reaches the group with the self-check;
* right after the pre-update installs a new AUTO-MAS (and only then) the check runs again and
  a miss goes to the group under its own title.
Each part fails on the code before it (no list, no item, no hook).
"""
import inspect
import json
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
import _stagegate_fx as fx

os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import texts
from ark_relay.features.phone import commands
from ark_relay.features.preupdate import preupdate_automas as P
from ark_relay.features.selfcheck import selfcheck
try:
    from ark_relay.core import mascontract
except ImportError:          # the code before this change
    mascontract = None

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


def edit_user(root: Path, fn) -> Path:
    """Apply fn to the MAA user of the fixture's ScriptConfig.json."""
    f = root / "config" / "ScriptConfig.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    fn(data["S-MAA"]["SubConfigsInfo"]["UserData"]["U1"])
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return root


def drop_stage(user):
    """A later AUTO-MAS that keeps the main stage neither in Stage nor in Info."""
    user["Stage"].pop("Stage")
    user["Info"].pop("Stage", None)


print("[the list of AUTO-MAS settings the relay reads]")
check("ark_relay/core/mascontract.py exists", mascontract is not None)
if mascontract is not None:
    items = mascontract.CONTRACT
    check("it lists the moved stage items at their new group",
          {("Stage", k) for k in ("Stage", "StageMode", "MedicineNumb")} <= {(i.group, i.key) for i in items})
    check("each item names its reader and a feature with plain words",
          [i.path for i in items if not i.source or i.use not in texts.MAS_SETTING_WHAT
           or i.use not in texts.MAS_SETTING_BREAKS], [])
    check("every script kind, the queue and the plan table are covered",
          {i.kind for i in items}, {"MAA", "MaaEnd", "OK-WW", "queue", "plan"})

print("\n[the check on AUTO-MAS v5.7.0-beta.3's layout]")
if mascontract is not None:
    beta3 = fx.automas_dir(tmpdir(), beta3=True)
    res = mascontract.check(beta3)
    check("beta.3 layout: nothing missing", [i.path for i in res.missing], [])
    check("beta.3 layout: the items were judged, not skipped", res.judged >= 30)
    check("beta.3 layout: no file unreadable", res.unreadable, [])

    def to_info(user):
        """The same user as an AUTO-MAS before beta.3 keeps it: the moved items in Info."""
        for k, g in mascontract.masuser.MOVED.items():
            if k in (user.get(g) or {}):
                user["Info"][k] = user[g].pop(k)
    old = edit_user(fx.automas_dir(tmpdir(), beta3=True), to_info)
    check("the same items kept in Info (before beta.3) also pass", [i.path for i in mascontract.check(old).missing], [])

    gone = edit_user(fx.automas_dir(tmpdir(), beta3=True), drop_stage)
    res = mascontract.check(gone)
    check("a stage kept in neither Stage nor Info fails and names it",
          [(i.kind, i.path) for i in res.missing], [("MAA", "Stage.Stage")])
    lines = texts.mas_contract_lines(res.missing)
    check("the plain line says which setting and which column",
          lines, ["中继读不到方舟的关卡设置（关卡一栏里找不到），开跑前查关卡、明日安排、手机上显示和修改关卡都不对了"])
    check("that line is plain words", [p for x in lines for p in texts.plain(x)], [])

print("\n[settings new in AUTO-MAS v5.7.0-beta.4: MaaEnd's launcher start (10-16)]")
# 10-16: beta.4 (PR #1394) brought Game.LaunchMode / Game.LauncherPath, and its pre-run check
# found no launcher from the relay's .cmd in Game.Path; the 早班 MaaEnd never ran. The relay
# now reads and writes all three (efstart_setup). The two new ones are judged only on beta.4
# or later: the recorded days of the day simulator run v5.6.2 to beta.3.
if mascontract is not None:
    launch = {(i.kind, i.path) for i in mascontract.CONTRACT if i.use == "maaend_launch"}
    check("MaaEnd Game.Path, Game.LaunchMode, Game.LauncherPath, Game.ControllerType are listed",
          launch, {("MaaEnd", "Game.Path"), ("MaaEnd", "Game.LaunchMode"), ("MaaEnd", "Game.LauncherPath"),
                   ("MaaEnd", "Game.ControllerType")})
    check("version order: beta.4 after beta.3, the release after its betas",
          (mascontract.version_key("v5.7.0-beta.3") < mascontract.version_key("v5.7.0-beta.4")
           < mascontract.version_key("v5.7.0") < mascontract.version_key("v5.7.1-beta.1"),
           mascontract.version_key("nonsense")), (True, None))
    b3 = fx.automas_dir(tmpdir(), beta3=True)
    new_keys = [("MaaEnd", "Game.LaunchMode"), ("MaaEnd", "Game.LauncherPath")]
    check("beta.4 installed, the two new keys absent: both named",
          [(i.kind, i.path) for i in mascontract.check(b3, "v5.7.0-beta.4").missing], new_keys)
    check("beta.3 installed: they are not judged", mascontract.check(b3, "v5.7.0-beta.3").missing, [])
    check("version unknown: not judged either", mascontract.check(b3, "").missing, [])

    def add_launch(root):
        f = root / "config" / "ScriptConfig.json"
        data = json.loads(f.read_text(encoding="utf-8"))
        data["S-END"]["Game"].update(LaunchMode="Launcher", LauncherPath="")
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return root
    check("beta.4 with them in place: nothing missing",
          mascontract.check(add_launch(fx.automas_dir(tmpdir(), beta3=True)), "v5.7.0-beta.4").missing, [])

    def drop_path(root):
        f = root / "config" / "ScriptConfig.json"
        data = json.loads(f.read_text(encoding="utf-8"))
        data["S-END"]["Game"].pop("Path")
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return root
    check("Game.Path is judged on every version",
          [(i.kind, i.path) for i in mascontract.check(drop_path(fx.automas_dir(tmpdir(), beta3=True))).missing],
          [("MaaEnd", "Game.Path")])

print("\n[「MaaEnd 启动」's window settings, written by the relay since 10-17]")
# efstart_setup sets Game.SetResolution / CloseOnFinish / RestoreDisplayType / RestoreResolution
# and reads Game.ControllerType (maaend_launch.check). An AUTO-MAS that drops one must be
# reported: listed, judged on every version (MaaEndConfig has them since v5.7.0-beta.2 at
# least), and a missing one named in one plain line.
if mascontract is not None:
    WINDOW_KEYS = ("SetResolution", "CloseOnFinish", "RestoreDisplayType", "RestoreResolution")
    window = [(i.kind, i.path, i.since) for i in mascontract.CONTRACT if i.use == "maaend_window"]
    check("the four window settings are listed, judged on every version",
          window, [("MaaEnd", f"Game.{k}", "") for k in WINDOW_KEYS])

    def drop_window(root):
        f = root / "config" / "ScriptConfig.json"
        data = json.loads(f.read_text(encoding="utf-8"))
        for k in (*WINDOW_KEYS, "ControllerType"):
            data["S-END"]["Game"].pop(k)
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return root
    gone = mascontract.check(drop_window(fx.automas_dir(tmpdir(), beta3=True)))
    check("an AUTO-MAS that drops them: all five named",
          sorted((i.kind, i.path) for i in gone.missing),
          sorted([("MaaEnd", f"Game.{k}") for k in (*WINDOW_KEYS, "ControllerType")]))
    lines = texts.mas_contract_lines(gone.missing)
    check("plain lines for them, one per feature", (len(lines), [p for x in lines for p in texts.plain(x)]), (2, []))
    check("the fixture as on the machine: nothing missing",
          mascontract.check(fx.automas_dir(tmpdir(), beta3=True)).missing, [])

print("\n[the boot self-check has it as one item, routed like the others]")
SELF_GOOD = dict(procs=lambda: [(1, r"D:\ark\automas\repo\main.py")], mas_up=lambda: True,
                 schedule=lambda: [{"name": "早班", "times": ["09:00"]}], channels=lambda: ["群"],
                 run_ok=lambda cmd: (True, ""), has_module=lambda m: True)


class _Notifier:
    channels = ["企业微信机器人"]

    def __init__(self):
        self.sent = []

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body, alert))
        return []


def self_items(root):
    cfg = types.SimpleNamespace(automas_dir=str(root), state_dir=Path(root) / "state", history_dir=str(root),
                                phone_topic="ark-x", phone_pin="1234")
    # The update settings are read from the backend; it is not asked in this test.
    orig = selfcheck._handed_updates_gaps
    orig_mas = commands._mas
    commands._mas = lambda *a, **k: {"data": {}}
    selfcheck._handed_updates_gaps = lambda scripts: []
    try:
        return selfcheck.run(cfg, **SELF_GOOD)
    finally:
        selfcheck._handed_updates_gaps, commands._mas = orig, orig_mas


name = getattr(texts, "MAS_CONTRACT_CHECK", "中继要读的调度程序设置都在原处")
os.environ["ARK_LOG_FILE"] = str(tmpdir() / "log" / "relay.log")
good = [c for c in self_items(fx.automas_dir(tmpdir(), beta3=True)) if c.name == name]
check("the self-check has the item", len(good), 1)
check("it holds on the beta.3 layout", [c.ok for c in good], [True])
bad = [c for c in self_items(edit_user(fx.automas_dir(tmpdir(), beta3=True), drop_stage)) if c.name == name]
check("it fails when the stage cannot be found", [c.ok for c in bad], [False])
check("its detail names the setting", bool(bad) and "方舟的关卡设置" in bad[0].detail)
empty = [c for c in self_items(tmpdir()) if c.name == name]
check("no settings folder: not judged (the queue line says it), not a second failure",
      [c.ok for c in empty], [None])

print("\n[right after the pre-update installed a new AUTO-MAS, and only then]")
has_hook = "after_update" in inspect.signature(P.run_automas).parameters
check("run_automas takes an after_update hook", has_hook)


def update_run(*, need: bool, confirmed: bool) -> list:
    """run_automas against a fake backend; the versions after_update was called with."""
    seen: list = []
    orig = (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version)

    def post(path, body=None):
        if path == "/api/update/check":
            return {"if_need_update": need, "latest_version": "v5.7.0-beta.3"}
        return {}
    P._mas_post, P._automas_version, P._live_version = post, (lambda _r: "v5.7.0-beta.2"), (lambda: "v5.7.0-beta.2")
    P._wait_for_package = lambda _root, _deadline, *_a: Path("UpdatePack_v5.7.0-beta.3.zip")
    P._wait_for_version = (lambda want, _d, *_a: want) if confirmed else (lambda want, _d, *_a: "v5.7.0-beta.2")
    try:
        kw = {"after_update": seen.append} if has_hook else {}
        P.run_automas(Path("."), budget_s=1, problems=[], **kw)
    finally:
        (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version) = orig
    return seen


check("a new version came up: the check runs once, with it", update_run(need=True, confirmed=True), ["v5.7.0-beta.3"])
check("no update: no check", update_run(need=False, confirmed=False), [])
check("install not confirmed (version unchanged): no check", update_run(need=True, confirmed=False), [])
boot = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
check("the boot's pre-update passes the hook", "after_update=" in boot and "report_contract" in boot)

print("\n[the post-update check pushes a miss to the group, under its own title]")
report = getattr(selfcheck, "report_contract", None)
check("selfcheck.report_contract exists", report is not None)
if report is not None:
    n = _Notifier()
    cfg = types.SimpleNamespace(automas_dir=str(edit_user(fx.automas_dir(tmpdir(), beta3=True), drop_stage)))
    c = report(cfg, n, "v5.7.0-beta.3")
    check("a miss: one alarm", [(t, a) for t, _, a in n.sent], [(texts.AUTOMAS_CONTRACT, True)])
    body = n.sent[0][1] if n.sent else ""
    check("it says the version and what stops working",
          "v5.7.0-beta.3" in body and "方舟的关卡设置" in body and "开跑前查关卡" in body)
    check("the alarm is plain words", texts.plain(texts.AUTOMAS_CONTRACT + body), [])
    check("returns the failed check", c.ok, False)
    n = _Notifier()
    report(types.SimpleNamespace(automas_dir=str(fx.automas_dir(tmpdir(), beta3=True))), n, "v5.7.0-beta.3")
    check("nothing missing: nothing pushed", n.sent, [])
    n = _Notifier()
    report(types.SimpleNamespace(automas_dir=str(fx.automas_dir(tmpdir(), beta3=True))), n, "v5.7.0-beta.4")
    check("just updated to beta.4 and its launcher settings are not there: the alarm names them",
          bool(n.sent) and "终末地的游戏位置和开游戏方式" in n.sent[0][1])
    check("that alarm is plain words", texts.plain(n.sent[0][1] if n.sent else ""), [])

    class _Log:
        def __init__(self):
            self.warned = []

        def warning(self, msg, *args, **kw):
            self.warned.append(msg % args)

        def info(self, msg, *args, **kw):
            pass
    lg = _Log()
    c = report(types.SimpleNamespace(automas_dir=str(tmpdir())), _Notifier(), "v5.7.0-beta.3", lg)
    check("files unreadable after an update: not judged, and said as a WARNING (errwatch pushes it)",
          (c.ok, len(lg.warned)), (None, 1))

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
