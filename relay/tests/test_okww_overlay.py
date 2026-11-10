"""OK-WW's overlay: the overlay, its faults, the install guard, pending.

One part per former file, each run on its own (tests/_parts.py): test_okww_overlay.py, test_okww_overlay_faults.py, test_okww_overlay_install_guard.py, test_okww_overlay_pending.py.
Added 2026-11-10: the command-line task at start-up (_part_okww_overlay_param_start).
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_main():
    """Ark's OK-WW changes live in OK-WW's own extension point, not in its source.

ok-script executes every .py under `<working>/ok_tasks/` at startup, so our changes
can rebind methods on upstream's classes without a single upstream file being
edited. That removes the whole family of failures the text patches kept producing:
half-applied, applied twice, or reverted to the wrong previous version - all silent.

What must not become silent in exchange: an override that did not take because
upstream renamed the method. The file writes a report; this pins that the relay
reads it and says so.

    Formerly test_okww_overlay.py.
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.okww_patch import okww_overlay


    print("[装到 OK-WW 自己的扩展目录里，不碰它的源文件]")
    root = tmpdir()
    dest = okww_overlay.target(root)
    check("路径在 ok_tasks 下", dest.parent.name, "ok_tasks")
    check("装之前没有", dest.is_file(), False)
    line = okww_overlay.install(root)
    check("装上了", dest.is_file())
    check("说了装到哪", "ok_tasks" in line)
    check("内容一字不差", dest.read_text(encoding="utf-8"), okww_overlay.source_text())
    check("再装一次什么都不做", okww_overlay.install(root), "")
    try:
        okww_overlay.install(None)
        check("目录是 None 时直说", False)
    except okww_overlay.OverlayTrouble as exc:     # a failure by construction (the _part_okww_overlay_faults part)
        check("目录是 None 时直说", "找不到" in str(exc))

    print("[没有目录也要自己建，不能因为缺个文件夹就装不上]")
    root2 = tmpdir()
    okww_overlay.install(root2)
    check("建好了目录并写进去", okww_overlay.target(root2).is_file())

    print("[ok-script 只执行「文件里有类」的 .py，所以那个类必须在]")
    src = okww_overlay.source_text()
    check("文件里有顶层类", "\nclass " in src)
    check("重绑之前先检查方法还在不在", "上游没有这个方法了" in src)
    check("抄整段的要比对上游正文", "expect_sha" in src)
    # 2026-09-09 pilot: the tacet teleport's team screen arrived just after upstream's
    # 10-second wait ran out. 19 runs across five days had already died there.
    check("传送界面等不到时会多等一次", "多等 15 秒" in src)
    check("多等那次不许自己抛，找不到才抛", "raise_if_not_found=False" in src)
    # 2026-09-09, the user asked the right question: if we replace a method outright and
    # upstream later changes theirs, we would never know. Only a pin catches that, so
    # every whole-method replacement must carry one.
    whole = [l for l in src.splitlines() if "@override(" in l]
    pinned = [l for l in whole if "expect_sha=" in l]
    check("整段替换的都钉住了上游哈希", len(pinned) >= 1)
    # revive_action is no longer overridden at all (2026-10-13, upstream v3.7.4 handles
    # the realm death); the whole-method replacements are the pinned ones below.
    check("被替换的是那两个小方法", any("click_team_challenge" in l or "find_nest" in l
                                        for l in pinned))

    print("[没贴上必须报出来，不许闷着]")
    real = okww_overlay.REPORT
    try:
        okww_overlay.REPORT = tmpdir() / "report.json"
        check("没有报告时不说话", okww_overlay.report_line(), "")
        okww_overlay.REPORT.write_text(json.dumps({"applied": ["A.b"], "skipped": []}),
                                       encoding="utf-8")
        check("全贴上了也不说话", okww_overlay.report_line(), "")
        okww_overlay.REPORT.write_text(json.dumps(
            {"applied": [], "skipped": [{"what": "FarmEchoTask.revive_action",
                                         "why": "上游没有这个方法了（改名或删了）"}]}),
            encoding="utf-8")
        line = okww_overlay.report_line()
        check("点名是哪一条没贴上", "revive_action" in line)
        check("说了为什么", "改名" in line)
        okww_overlay.REPORT.write_text(json.dumps({"error": "Traceback ... ImportError"}),
                                       encoding="utf-8")
        check("整个文件炸了也要说", "一条都没生效" in okww_overlay.report_line())
        # Raised part-way (audit 2026-10-13, A5): the overrides are applied one by
        # one, so the ones before the error are live - say which.
        okww_overlay.REPORT.write_text(json.dumps(
            {"applied": ["FarmEchoTask.revive_action", "FarmEchoTask.handle_claim_button"],
             "skipped": [], "error": "Traceback ... KeyError"}), encoding="utf-8")
        line = okww_overlay.report_line()
        check("part-way: not 「一条都没生效」", "一条都没生效" in line, False)
        check("part-way: names what applied", "已生效 2 条" in line and "handle_claim_button" in line, True)
        check("part-way: names what did not", "没生效" in line and "NightmareNestTask.find_nest" in line, True)
        check("part-way: an applied one is not listed as not applied",
              "revive_action" not in line.split("没生效")[1], True)
        check("part-way: still the error and its trouble words", "KeyError" in line and "自己报错了" in line, True)
    finally:
        okww_overlay.REPORT = real

    print("[闸门本身：拿坏样本喂它，必须拦住]")
    # The gate is the whole reason this is safer than editing upstream's files. A gate
    # that does not fire is worse than none, so it is fed known-bad input here.
    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    ns["_applied"].clear()
    ns["_skipped"].clear()


    class Upstream:
        def still_here(self):
            return "上游的"


    @ns["override"](Upstream, "still_here")
    def _mine(self):
        return "我们的"


    check("方法在就换掉", Upstream().still_here(), "我们的")
    check("记到已贴上里", ns["_applied"], ["Upstream.still_here"])

    ns["_applied"].clear()
    ns["_skipped"].clear()


    @ns["override"](Upstream, "上游改名之后就没有的方法")
    def _orphan(self):
        return "不该生效"


    check("上游没这个方法就不贴", ns["_applied"], [])
    check("而且要记下来", len(ns["_skipped"]), 1)
    check("说清了原因", "上游没有这个方法了" in ns["_skipped"][0]["why"])

    ns["_applied"].clear()
    ns["_skipped"].clear()


    @ns["override"](Upstream, "still_here", expect_sha="0123456789ab")
    def _stale(self):
        return "照着旧正文抄的"


    check("上游正文变了就不贴", ns["_applied"], [])
    check("并且说明是正文对不上", "正文变了" in ns["_skipped"][0]["why"])
    check("原来那份没被换掉", Upstream().still_here(), "我们的")

    real_sha = ns["_src_sha"](Upstream.still_here)
    ns["_applied"].clear()
    ns["_skipped"].clear()


    @ns["override"](Upstream, "still_here", expect_sha=real_sha)
    def _fresh(self):
        return "对得上就贴"


    check("正文对得上就照贴", Upstream().still_here(), "对得上就贴")
    check("没有被跳过的", ns["_skipped"], [])

    print("\n[the gate compares call shapes: a copy that does not take upstream's parameters is not bound]")


    class Up2:
        def run(self, retries=3):
            return f"upstream {retries}"

        def pick(self, box, *, near=None):
            return "upstream pick"

        def free(self, *a, **kw):  # how the test fakes look: no constraint from upstream
            return "upstream free"


    def gate(name, fn):
        ns["_applied"].clear()
        ns["_skipped"].clear()
        ns["override"](Up2, name)(fn)
        return list(ns["_applied"]), [x["why"] for x in ns["_skipped"]]


    # The 10-13 case: v3.7.4 retries with self.run(retries - 1); a run(self) copy made that a TypeError.
    applied, why = gate("run", lambda self: "ours")
    check("ours run(self) vs upstream run(self, retries=3): not bound", applied, [])
    check("listed as skipped, naming the parameter", len(why) == 1 and "参数变了" in why[0] and "retries" in why[0], True)
    check("upstream's own run left in place", Up2().run(2), "upstream 2")
    applied, _ = gate("run", lambda self, *a, **kw: "wrapper")
    check("a (self, *a, **kw) wrapper is bound", applied, ["Up2.run"])
    applied, _ = gate("run", lambda self, retries=3: "same")
    check("the same shape is bound", applied, ["Up2.run"])
    applied, why = gate("pick", lambda self, b, *, near=None: "renamed")
    check("a renamed parameter (box -> b) is not bound: callers may pass box=", applied, [])
    applied, why = gate("pick", lambda self, box: "no near")
    check("a dropped keyword-only parameter is not bound", applied, [])
    applied, why = gate("pick", lambda self, box, extra, *, near=None: "needs more")
    check("ours requiring a parameter upstream lacks is not bound", applied, [])
    applied, _ = gate("run", lambda self, retries: "required")
    check("ours requiring what upstream leaves optional is not bound", applied, [])
    applied, _ = gate("free", lambda self: "plain")
    check("upstream *a/**kw constrains nothing (the fakes' shape)", applied, ["Up2.free"])

    print("\n[体力读数：数/数 没读到是「没读到」，不是 0]")
    parse = ns["_parse_stamina"]
    # The strip as OCR reads it on the 2026-09-21 screenshots (10-20-43.029 and two more):
    check("09-21 截图原样", parse(["55", "240/240", "+"]), (240, 55))
    check("240/240 拆成两块也拼得回", parse(["55", "240", "/240"]), (240, 55))
    check("拆成三块也拼得回", parse(["55", "240", "/", "240"]), (240, 55))
    check("备用只取数/数左边那块，右边的数不覆盖", parse(["55", "240/240", "120"]), (240, 55))
    check("左边不是纯数字就没有备用", parse(["+", "120/240"]), (120, 0))
    check("一块数/数都拼不出来 = 没读到（上游这里当 0）", parse(["240", "55"]), None)
    check("什么都没读到", parse([]), None)
    check("真读到 0/240 就是 0", parse(["0/240"]), (0, 0))


    class _Box:
        def __init__(self, name, x=0, y=0, width=10, height=10):
            self.name, self.x, self.y, self.width, self.height = name, x, y, width, height

        def __str__(self):
            return f"Box(name='{self.name}')"


    class FakeTask:
        """Plays back a script of screens; records what the override does."""

        def __init__(self, frames, start_after=None, strip=None):
            self.frames, self.start_after, self.strip = frames, start_after, strip or []
            self.clicks, self.logs, self.shots, self.slept = [], [], [], 0

        def wait_feature(self, name, **kw):
            return self.start_after is not None and len(self.clicks) >= self.start_after

        def box_of_screen(self, *xy):
            return xy

        def ocr(self, box=None):
            return self.frames(box)

        def wait_ocr(self, *box, **kw):
            return self.strip.pop(0) if self.strip else []

        def click_box(self, b, after_sleep=0):
            self.clicks.append((b.x + b.width // 2, b.y + b.height // 2))

        def screenshot(self, name):
            self.shots.append(name)

        def log_info(self, msg):
            self.logs.append(msg)

        def sleep(self, s):
            self.slept += s


    solo_btn = _Box("单人挑战", 1474, 965, 124, 36)
    still_solo = lambda box: [solo_btn]  # noqa: E731
    confirm = ns["_confirm_solo"]
    t = FakeTask(still_solo, start_after=0)
    check("开启挑战已经在：一下都不补", (confirm(t), t.clicks), (0, []))
    t = FakeTask(still_solo, start_after=1)
    check("09-21 那种：仍是单人挑战就点它读到的位置", (confirm(t), t.clicks), (1, [(1536, 983)]))
    check("补点前截图", t.shots, ["solo_retry_1"])
    check("补点写日志", any("补点第 1 次 (1536,983)" in m for m in t.logs), True)
    t = FakeTask(still_solo)
    check("最多补 3 次", (confirm(t), len(t.clicks)), (3, 3))
    check("3 次都没进要说", any("3 次都没进开启挑战" in m for m in t.logs), True)
    t = FakeTask(lambda box: [_Box("结晶波片不足，无法获取奖励")])
    check("波片不足弹窗不补点，交给原来那段", (confirm(t), t.clicks), (0, []))
    t = FakeTask(lambda box: [_Box("别的画面")] if box == (0.0, 0.0, 1.0, 1.0) else [])
    check("屏上没有单人挑战不乱点", (confirm(t), t.clicks), (0, []))

    read = ns["_read_stamina"]
    t = FakeTask(None, strip=[[_Box("55", 1351), _Box("/240", 1600), _Box("240", 1551)]])
    check("按横坐标排好再拼", read(t, False), (240, 55))
    check("读字原文进日志", any("['55', '240', '/240']" in m for m in t.logs), True)
    t = FakeTask(None, strip=[[_Box("240")], [_Box("55"), _Box("240/240", 5)]])
    check("领奖框没读到隔 1 秒再读", (read(t, True), t.slept), ((240, 55), 1))
    t = FakeTask(None, strip=[[_Box("240")]])
    check("F2 书页只读一次，没读到交回上游（-1 分支）", (read(t, False), t.slept), (None, 0))
    t = FakeTask(None, strip=[])
    check("领奖框读 5 次都没有就算没读到", (read(t, True), t.slept, t.shots), (None, 4, ["stamina_error"]))

    print("\n[母本指路文件：改动文件靠它读「只刷落渊南丘」]")
    # ok-script rewrites configs/ at load and drops the key (09-10..09-13 farmed all
    # four nests), so the value is only ever readable from AUTO-MAS's master.
    automas = tmpdir()
    mdir = automas / "data" / "c5e9-okww" / "Default" / "ConfigFile"
    mdir.mkdir(parents=True)
    (mdir / "DailyTask.json").write_text("{}", encoding="utf-8")
    pointer = tmpdir() / "ark-okww-master.txt"
    okww_overlay.MASTER_POINTER = pointer
    try:
        okww_overlay.write_master_pointer(tmpdir())
        check("母本找不到就说清楚", False)
    except okww_overlay.OverlayTrouble as exc:     # a failure by construction (the _part_okww_overlay_faults part)
        check("母本找不到就说清楚", "找不到" in str(exc))
    check("写好了不吭声", okww_overlay.write_master_pointer(automas), "")
    check("指向母本目录", pointer.read_text(encoding="utf-8"), str(mdir))
    check("已是这个值就不重写", okww_overlay.write_master_pointer(automas), "")
    check("改动文件里读的是同一个路径", 'r"C:\\ProgramData\\ark-okww-master.txt"' in okww_overlay.source_text())

    print("\n[最新一趟 OK-WW 日志：按修改时间取最新，一周内]")
    from ark_relay.features.verify import outcome
    hist = tmpdir()
    check("没有历史目录", outcome.latest_okww_run_log(hist / "nope"), None)
    check("目录空着", outcome.latest_okww_run_log(hist), None)
    d1 = hist / "2026-09-12" / "wuwa"; d1.mkdir(parents=True)
    d2 = hist / "2026-09-13" / "wuwa"; d2.mkdir(parents=True)
    (d1 / "OK-WW-05-20-09.log").write_text("old\n", encoding="utf-8")
    (d2 / "OK-WW-05-19-22.log").write_text("new NightmareNestTask\n", encoding="utf-8")
    import os as _os
    import time as _time
    _os.utime(d1 / "OK-WW-05-20-09.log", (_time.time() - 86400, _time.time() - 86400))
    got = outcome.latest_okww_run_log(hist)
    check("取到最新那趟", got[0].name if got else None, "OK-WW-05-19-22.log")
    check("连正文一起给", got[1] if got else None, "new NightmareNestTask\n")

    print("\n[the launch argument is OK-WW's own since v3.7.4: no hook on start_controller.execute]")
    src_now = okww_overlay.source_text()
    # 2026-11-10: the file does name start_controller now (StartController._do_start, the command-line task,
    # _part_okww_overlay_param_start), so this looks for what it is about - a hook on its `execute`.
    import re as _re
    hooked = _re.search(r"""start_controller\w*\s*\.\s*execute\b|override\([^)]*["']execute["']""",
                        src_now.split("# The launch-argument hook")[0])
    check("no execute override", bool(hooked), False)
    check("that check still fires on a hook", bool(_re.search(
        r"""start_controller\w*\s*\.\s*execute\b|override\([^)]*["']execute["']""",
        "import ok.core.start_controller\nok.core.start_controller.execute = mine\n")), True)
    check("no _install_launch", "_install_launch" in src_now, False)


def _part_okww_overlay_faults():
    """An overlay that is not in place reaches the group, whatever its words.

Audit 2026-10-13 (A1): when the overrides could not be installed, or the master
pointer could not be written, the lines said 没装上 / 装不上 / 写不了 / 找不到 -
none of them in texts._PATCH_TROUBLE - so the push title was the healthy
「🩹 OK-WW 补丁」, which notify.route_of keeps in the log. OK-WW ran as plain
upstream while every report stayed green.

install() and write_master_pointer() now raise OverlayTrouble on each failure path,
and boot_stages._stage_patch_okww counts those as failures by construction. Each
path is driven through the boot stage here and must end with the ⚠️ title routed
to the group; the healthy install stays 🩹 / log.

    Formerly test_okww_overlay_faults.py.
    """
    import os
    import types


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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

    import boot_stages
    from ark_relay.core import texts
    from ark_relay.core.notify import route_of
    from ark_relay.features.okww_patch import okww_overlay as ov


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []


    REAL = {k: getattr(ov, k) for k in ("atomic_write_text", "master_config_dir", "MASTER_POINTER", "REPORT")}
    MASTER = TMP / "master"
    MASTER.mkdir()


    def boot(okww_dir, *, write=None, master="ok"):
        """Run the boot stage once with a fresh pointer and no report; ([(title, alert)], [body])."""
        ov.MASTER_POINTER = tmpdir() / "pointer.txt"
        ov.REPORT = tmpdir() / "report.json"           # absent: report_line says nothing
        ov.master_config_dir = lambda automas_dir, marker: MASTER if master == "ok" else None
        ov.atomic_write_text = write or REAL["atomic_write_text"]
        cfg = types.SimpleNamespace(okww_dir=okww_dir, automas_dir=None, state_dir=tmpdir())
        notes = Notes()
        try:
            boot_stages._stage_patch_okww(cfg, notes, boot_stages.log)
        finally:
            for k, v in REAL.items():
                setattr(ov, k, v)
        return [(t, a) for t, _, a in notes.sent], [b for _, b, _ in notes.sent]


    def is_alarm(label, sent):
        check(f"{label}: one push", len(sent), 1)
        title, alert = sent[0] if sent else ("", False)
        check(f"{label}: ⚠️ title", title.startswith("⚠️"), True)
        check(f"{label}: routed to the group", route_of(title, alert=alert), "group")


    def raising(name):
        """atomic_write_text that raises OSError for the file called `name`."""
        def w(path, text, newline=None):
            if Path(path).name == name:
                raise OSError(13, "Access is denied")
            return REAL["atomic_write_text"](path, text, newline)
        return w


    def garbling(name):
        """atomic_write_text that writes something else into the file called `name`."""
        def w(path, text, newline=None):
            return REAL["atomic_write_text"](path, text + "x" if Path(path).name == name else text, newline)
        return w


    print("[healthy: installed once -> 🩹, log only]")
    sent, bodies = boot(tmpdir())
    check("one push", len(sent), 1)
    check("🩹 title", sent[0][0].startswith("🩹") if sent else False, True)
    check("log only", route_of(sent[0][0], alert=sent[0][1]) if sent else "", "log")
    check("says where it went", "ok_tasks" in (bodies[0] if bodies else ""), True)

    print("\n[every failure path: ⚠️, group]")
    sent, _ = boot(None)
    is_alarm("no OK-WW directory", sent)
    sent, _ = boot(tmpdir(), write=garbling(ov.FILE_NAME))
    is_alarm("overrides read back different", sent)
    sent, _ = boot(tmpdir(), write=raising(ov.FILE_NAME))
    is_alarm("overrides cannot be written", sent)
    sent, _ = boot(tmpdir(), master=None)
    is_alarm("no master directory", sent)
    sent, _ = boot(tmpdir(), write=raising("pointer.txt"))
    is_alarm("pointer cannot be written", sent)
    sent, _ = boot(tmpdir(), write=garbling("pointer.txt"))
    is_alarm("pointer reads back different", sent)

    print("\n[the raise itself, not the words, makes it a failure]")
    try:
        ov.install(None)
        check("install(None) raises", False, True)
    except ov.OverlayTrouble as exc:
        check("install(None) raises OverlayTrouble with a plain line", "OK-WW" in str(exc), True)
    check("a fault counts even when no trouble word matches",
          texts.patches(1, ["随便什么话"], ["随便什么话"]).startswith("⚠️"), True)
    check("a fault that also has a trouble word is counted once",
          "1 条没贴上" in texts.patches(1, ["OK-WW 有改动没贴上"], ["OK-WW 有改动没贴上"]), True)
    check("the old two-argument call is unchanged", texts.patches(2, ["a", "b"]), "🩹 OK-WW 补丁（2 条）")

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_overlay_install_guard():
    """install() leaves ok_tasks/ark_overrides.py alone unless it must change, and never
rewrites it under a running OK-WW (audit 2026-10-13, A2).

ok-script watches ok_tasks/ while OK-WW runs and executes again any .py there that
changes (ok-script task_manager.py _on_debug_dir_changed, which hands a file it has
not recorded as a task to load_single_user_task). Executing the overrides twice
wraps our wrappers again. So:

* identical bytes -> nothing is written and no process list is asked for;
* different bytes while OK-WW runs -> not written, a logged line says so;
* different bytes and OK-WW not running, or no way to tell -> written.

    Formerly test_okww_overlay_install_guard.py.
    """
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import procs, texts
    from ark_relay.core import config as C
    from ark_relay.features.okww_patch import okww_overlay as ov


    REAL_RUNNING = getattr(ov, "okww_running", None)
    asked = []


    def running(answer):
        def f():
            asked.append(answer)
            return answer
        return f


    WANT = ov.source_text().encode("utf-8")

    print("[CRLF copy on disk (same text, other bytes): rewritten to the exact bytes]")
    root = tmpdir()
    dest = ov.target(root)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(WANT.replace(b"\n", b"\r\n"))
    ov.okww_running = running(False)
    try:
        line = ov.install(root)
        check("rewritten", dest.read_bytes(), WANT)
        check("says where", "ok_tasks" in line)

        print("\n[identical bytes: nothing written, no process list asked for]")
        asked.clear()
        os.utime(dest, (1_000_000_000, 1_000_000_000))
        check("returns ''", ov.install(root), "")
        check("process list not asked", asked, [])
        check("file not touched (mtime kept)", int(dest.stat().st_mtime), 1_000_000_000)

        print("\n[different bytes while OK-WW runs: left alone, a logged line]")
        dest.write_bytes(b"# an older overlay\n")
        ov.okww_running = running(True)
        line = ov.install(root)
        check("file unchanged", dest.read_bytes(), b"# an older overlay\n")
        check("says OK-WW is running", "正在运行" in line)
        check("not a fault: 🩹 title", texts.patches(1, [line]).startswith("🩹"))

        print("\n[different bytes, cannot tell whether OK-WW runs: written]")
        ov.okww_running = running(None)
        ov.install(root)
        check("written", dest.read_bytes(), WANT)
    finally:
        ov.okww_running = REAL_RUNNING

    print("\n[okww_running: pythonw.exe with ok-ww on its command line is OK-WW]")
    real_pp, real_win = procs.python_processes, C.IS_WINDOWS
    seen = {}


    def pp(rows):
        def f(**kw):
            seen.update(kw)
            return rows
        return f


    try:
        C.IS_WINDOWS = True
        procs.python_processes = pp([(1, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"),
                                     (2, r"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe "
                                         r"D:\ark\okww\data\apps\ok-ww\working\main.py -t 1 -e")])
        check("OK-WW up", ov.okww_running(), True)
        check("asks for python.exe and pythonw.exe", seen.get("hosts"), C.PYTHON_HOSTS)
        check("leaves the outage alarm to the boot self-check", seen.get("warn"), False)
        procs.python_processes = pp([(1, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py")])
        check("only AUTO-MAS: not up", ov.okww_running(), False)
        procs.python_processes = pp(None)
        check("list unreadable: cannot tell", ov.okww_running(), None)
    finally:
        C.IS_WINDOWS = real_win
        procs.python_processes = real_pp
    check("not Windows: cannot tell", ov.okww_running(), None)

    print("\n[procs.python_processes(hosts=...) queries every host name]")
    queries = []
    real_q = procs._query_once
    procs._query_once = lambda query=procs._QUERY: (queries.append(query), ([], ""))[1]
    try:
        procs.python_processes(hosts=C.PYTHON_HOSTS)
        procs.python_processes()
    finally:
        procs._query_once = real_q
    check("pythonw.exe and python.exe both in the query",
          bool(queries) and "Name='pythonw.exe'" in queries[0] and "Name='python.exe'" in queries[0])
    check("the default query is unchanged", queries[1:], [procs._QUERY])

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_overlay_pending():
    """An overlay install skipped because OK-WW was running is tried again before the
relay next starts a run itself, and is said to the group if it still cannot be done.

Review 2026-10-13 item 20: install() skips while OK-WW runs (a relay restart
mid-run, e.g. a deploy). Until then the old overlay stayed until the next relay
start - normally the next boot - with one 🩹 log line. Now okww_overlay.retry_pending
runs after the pre-update closed OK-WW and right before phone.commands dispatches a
script or a queue; still running there -> a WARNING (errwatch pushes every WARNING
to the group).

    Formerly test_okww_overlay_pending.py.
    """
    import logging
    import os
    import types


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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

    import boot_stages
    from ark_relay.features.okww_patch import okww_overlay as ov
    from ark_relay.features.phone import commands
    from ark_relay.features.preupdate import preupdate
    from ark_relay.features.alarm import errwatch

    # The stubbed win32api would make GetSystemMetrics read as "Windows is going down", and the
    # boot pre-update stops at once for a stopping relay (boot_stages._stage_preupdate, 10-16).
    errwatch.system_shutting_down = lambda: False


    class Warnings(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.WARNING)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())


    W = Warnings()
    ov.log.addHandler(W)
    REAL_RUNNING = ov.okww_running
    running = {"now": True}
    ov.okww_running = lambda: running["now"]
    WANT = ov.source_text().encode("utf-8")

    try:
        print("[skipped at boot while OK-WW runs: pending]")
        root = tmpdir()
        dest = ov.target(root)
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"# old overlay\n")
        ov.install(root)
        check("file left alone", dest.read_bytes(), b"# old overlay\n")
        check("pending", ov._pending.get("dir"), root)

        print("\n[tried again while OK-WW still runs: a WARNING (to the group), file left alone]")
        W.lines.clear()
        line = ov.retry_pending("单独开跑「OK-WW」前")
        check("one warning", len(W.lines), 1)
        check("says where and that the old overlay runs", "单独开跑「OK-WW」前" in line and "旧" in line, True)
        check("file still the old one", dest.read_bytes(), b"# old overlay\n")

        print("\n[tried again once OK-WW stopped: installed, no warning, nothing pending]")
        running["now"] = False
        W.lines.clear()
        ov.retry_pending("预更新后")
        check("installed", dest.read_bytes(), WANT)
        check("no warning", W.lines, [])
        check("nothing pending", ov._pending, {})
        check("nothing pending: no-op", ov.retry_pending("x"), "")

        print("\n[the relay's own dispatch tries it before starting]")
        order = []
        real = (ov.retry_pending, commands._mas, commands._note_dispatch)
        ov.retry_pending = lambda where: order.append(("retry", where)) or ""
        commands._note_dispatch = lambda what: None

        def mas(path, body=None):
            if path == "/api/scripts/get":
                return {"data": {"s1": {"Info": {"Name": "OK-WW"}}}}
            if path == "/api/queue/get":
                return {"data": {"q1": {"Info": {"Name": "早班"}}}}
            order.append(("dispatch", body["taskId"]))
            return {"status": "success"}
        commands._mas = mas
        try:
            commands.run_script("OK-WW")
            check("script: retry before dispatch", [k for k, _ in order], ["retry", "dispatch"])
            order.clear()
            commands._run_now("早班")
            check("queue: retry before dispatch", [k for k, _ in order], ["retry", "dispatch"])
            print("\n[the pre-update tries it after closing OK-WW]")
            order.clear()
            real_pre = (preupdate.run_okww, ov.drift_line)
            preupdate.run_okww = lambda okww, problems=None, **_k: order.append(("preupdate", "")) or ""
            ov.drift_line = lambda okww, state_dir: ""
            try:
                notes = types.SimpleNamespace(send=lambda *a, **k: [])
                cfg = types.SimpleNamespace(okww_dir=root, automas_dir=None, state_dir=tmpdir())
                boot_stages._preupdate_okww(cfg, notes, boot_stages.log, [])
            finally:
                preupdate.run_okww, ov.drift_line = real_pre
            check("pre-update, then retry", [k for k, _ in order], ["preupdate", "retry"])
        finally:
            ov.retry_pending, commands._mas, commands._note_dispatch = real
    finally:
        ov.okww_running = REAL_RUNNING
        ov._pending.clear()

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_overlay_param_start():
    """The task AUTO-MAS names on OK-WW's command line (`-t 1 -e`) is started, not dropped.

2026-11-10 (ledger #158): OK-WW updated itself to v3.7.20-beta.3 at 08:48 and both starts of
the morning shift logged 「<DailyTask> was cancelled while the game was starting」 (09:21:04,
09:22:39); the game was up, no task ran, OK-WW never exited, the shift stood still until
the 10:51 overtime alarm. Upstream's new pending list exempts an index, but _do_start has
turned the index into the task object before it looks.

Upstream is run, not imitated: fixtures/okww-v3.7.20-beta.3-start_controller.py.txt is
ok/core/start_controller.py as it stood on the game PC that morning (sha256 3c4eb217…6d6521),
executed here with stand-ins only for what it imports.
    """
    import threading
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.okww_patch import okww_overlay

    FIXTURE = Path(__file__).resolve().parent / "fixtures" / "okww-v3.7.20-beta.3-start_controller.py.txt"
    CANCELLED = "was cancelled while the game was starting"
    NAMES = ("ok", "ok.device", "ok.device.capture", "ok.core", "ok.core.events", "ok.core.notifications",
             "ok.util", "ok.util.process", "ok.core.start_controller")
    saved = {n: sys.modules.get(n) for n in NAMES}

    class Signal:
        def __init__(self):
            self.sent = []

        def emit(self, *a):
            self.sent.append(a)

    class Log:
        def __init__(self, lines):
            self.lines = lines

        def info(self, msg, *a):
            self.lines.append(str(msg))

        error = warning = debug = info

    class Task:
        def __init__(self, name, executor):
            self.name, self.executor = name, executor
            self._enabled = False
            self.paused = False
            self.exit_after_task = False

        @property
        def enabled(self):
            return self._enabled

        def info_clear(self):
            pass

        def __repr__(self):
            return f"<{self.name}>"

    class Executor:
        def __init__(self):
            self.onetime_tasks = [Task("DailyTask", self), Task("Other", self)]
            self.current_task = None
            self.paused = False
            self.queued = []
            self.started = 0

        def get_all_tasks(self):
            return list(self.onetime_tasks)

        def enqueue_onetime_task(self, task):
            self.queued.append(task)

        def start(self):
            self.started += 1

    def world(fixture_text):
        """Fresh stand-ins, the upstream file executed on them. -> (StartController, og, log lines)."""
        lines = []
        og = types.SimpleNamespace(executor=Executor(), app=None,
                                   device_manager=types.SimpleNamespace(do_refresh=lambda *a: None))
        ok = types.ModuleType("ok")
        ok.og = og
        ok.Handler = type("Handler", (), {"__init__": lambda self, *a: None, "post": lambda self, fn: fn()})
        ok.Logger = type("Logger", (), {"get_logger": staticmethod(lambda name: Log(lines))})
        mods = {"ok": ok}
        for name, attrs in (("ok.device", {}), ("ok.core", {}), ("ok.util", {}),
                            ("ok.device.capture", {"BaseWindowsCaptureMethod": object, "BrowserCaptureMethod": object}),
                            ("ok.core.events", {"communicate": types.SimpleNamespace(starting_emulator=Signal(), task=Signal())}),
                            ("ok.core.notifications", {"alert_error": lambda *a, **k: None, "alert_info": lambda *a, **k: None}),
                            ("ok.util.process", {"is_admin": lambda: True, "execute": lambda *a, **k: None,
                                                 "WINDOWS_START_METHOD_START": "start"})):
            m = types.ModuleType(name)
            m.__dict__.update(attrs)
            mods[name] = m
        sys.modules.update(mods)
        sc = types.ModuleType("ok.core.start_controller")
        sys.modules["ok.core.start_controller"] = sc
        exec(compile(fixture_text, "start_controller.py", "exec"), sc.__dict__)
        return sc.StartController, og, lines

    def controller(cls, start_exe=False, device_ok=True):
        sub = type("C", (cls,), {"check_auto_hdr": lambda self: None,
                                 "check_gpu_driver_post_processing": lambda self: None,
                                 "start_device": lambda self, initial_refresh_done=False: device_ok})
        return sub({"windows": {"start_exe": start_exe}}, threading.Event())

    def install():
        """The overrides file executed in this world, as ok-script does at start-up."""
        ns = {"__name__": "ark_overrides_test"}
        exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
        return ns

    text = FIXTURE.read_text(encoding="utf-8")
    try:
        print("[上游 v3.7.20-beta.3 自己：命令行带起的任务被它当成已取消]")
        cls, og, lines = world(text)
        c = controller(cls)
        daily = og.executor.onetime_tasks[0]
        check("upstream alone: do_start returns True all the same", c.do_start(0, True), True)
        check("upstream alone: says it was cancelled", any(CANCELLED in x for x in lines), True)
        check("upstream alone: the daily task is not enabled", (daily.enabled, og.executor.queued), (False, []))

        print("[装上我们的改动：照常起跑]")
        cls, og, lines = world(text)
        ns = install()
        check("listed as applied", "StartController._do_start" in ns["_applied"], True)
        check("not listed as skipped", [x for x in ns["_skipped"] if "StartController" in x["what"]], [])
        c = controller(cls)
        daily, other = og.executor.onetime_tasks
        check("do_start(0, exit_after)", c.do_start(0, True), True)
        check("no 'was cancelled' line", [x for x in lines if CANCELLED in x], [])
        check("the daily task is enabled and queued once", (daily.enabled, og.executor.queued), (True, [daily]))
        check("exit after the task (-e) is kept", daily.exit_after_task, True)
        check("the executor is started", og.executor.started, 1)
        check("nothing left waiting", c._pending[1], [])
        check("the other task is untouched", (other.enabled, other.exit_after_task), (False, False))
        check("our line names the task", any(ns["PARAM_START"] in x and "DailyTask" in x for x in lines), True)

        print("[上游自己的取消逻辑不受影响]")
        cls, og, lines = world(text)
        install()
        c = controller(cls)
        daily, other = og.executor.onetime_tasks
        c._add_pending(other)
        check("a task asked for in the window can still be cancelled", c.cancel_task(other), True)
        check("its queued start is skipped", c.do_start(other, False, from_queue=True), False)
        check("and it stays disabled", other.enabled, False)
        c._do_start(other, False)                # reached directly, without being pending: upstream drops it
        check("a non-pending task object is still dropped by upstream", (other.enabled, any(CANCELLED in x for x in lines)),
              (False, True))
        c._add_pending(other)
        check("a pending one is started", (c.do_start(other, False, from_queue=True), other.enabled), (True, True))

        print("[游戏没起来：不留一个「等着」的任务]")
        cls, og, lines = world(text)
        install()
        c = controller(cls, start_exe=True, device_ok=False)
        daily = og.executor.onetime_tasks[0]
        check("a failed launch returns False", c.do_start(0, True), False)
        check("the daily task is not left on the pending list", c._pending[1], [])
        check("and is not enabled", daily.enabled, False)

        print("[下标不对：照上游自己的报法]")
        cls, og, lines = world(text)
        install()
        c = controller(cls)
        check("a bad index is upstream's own failure", c.do_start(9, True), False)
        check("nothing waiting, nothing queued", (c._pending[1], og.executor.queued), ([], []))

        print("[没有待启动名单的旧版：不动它]")
        old = text.replace("    def _pending(self):", "    def _pending_gone(self):")
        cls, og, lines = world(old)
        before = cls._do_start
        ns = install()
        check("not applied, not skipped", ("StartController._do_start" in ns["_applied"],
                                           [x for x in ns["_skipped"] if "StartController" in x["what"]]), (False, []))
        check("upstream's _do_start is still upstream's", cls._do_start is before, True)

        print("[上游把 _do_start 改名或改了参数：不贴，记进没贴上]")
        cls, og, lines = world(text.replace("    def _do_start(self, task=None, exit_after=False):",
                                            "    def _do_start2(self, task=None, exit_after=False):")
                               .replace("self._do_start(task, exit_after)", "self._do_start2(task, exit_after)"))
        ns = install()
        why = [x["why"] for x in ns["_skipped"] if "StartController" in x["what"]]
        check("renamed away: skipped with the reason", ("StartController._do_start" in ns["_applied"], len(why),
                                                        "没有这个方法" in (why or [""])[0]), (False, 1, True))
        cls, og, lines = world(text.replace("    def _do_start(self, task=None, exit_after=False):",
                                            "    def _do_start(self, task=None, exit_after=False, *, reason):"))
        before = cls._do_start
        ns = install()
        why = [x["why"] for x in ns["_skipped"] if "StartController" in x["what"]]
        check("a parameter ours cannot pass on: skipped, upstream's left in place",
              ("StartController._do_start" in ns["_applied"], len(why), cls._do_start is before), (False, 1, True))

        print("[param_task_pending 本身]")
        ns = install()
        fn = ns["param_task_pending"]
        holder = types.SimpleNamespace(_pending=(threading.Lock(), []))
        check("an index puts the task on the list", (fn(holder, 1, ["a", "b"]), holder._pending[1]), ("b", ["b"]))
        check("twice is once", (fn(holder, 1, ["a", "b"]), holder._pending[1]), ("b", ["b"]))
        for junk in (None, True, "1", object()):
            check(f"{junk!r} is not an index", fn(holder, junk, ["a", "b"]), None)
        check("no list on this upstream", fn(types.SimpleNamespace(), 0, ["a"]), None)
    finally:
        for n, m in saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_okww_overlay_faults, _part_okww_overlay_install_guard, _part_okww_overlay_pending,
                        _part_okww_overlay_param_start]))
