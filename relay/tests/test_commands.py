"""Phone and command-line commands: a channel down, the CLI, test channels, the command table, the gates, the mailbox's close windows, payload round trips, test windows, the web shell.

One part per former file, each run on its own (tests/_parts.py): test_channel_down.py, test_cli_commands.py, test_cmd_test_channels.py, test_command_table.py, test_commands_gates.py, test_mailbox_close_windows.py, test_payload_roundtrip.py, test_test_windows.py, test_web_shell.py.
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


def _part_channel_down():
    """A channel that refuses a send is announced every time it refuses one.

From 2026-08-22 until 2026-10-06 the same fault was announced once (a record on
disk, keyed by the error with 企业微信's hint and egress IP stripped, so that a
day of relay restarts did not repeat it). The user's order of 2026-10-06, every
error to the group, every time (「不论多少次什么错误都要发」), ended that.
Pinned: each refused send is announced over the channels still
working; the per-channel log line comes with it, marked as already in the group
only when the group robot took the notice (errwatch does not push it twice).

    Formerly test_channel_down.py.
    """
    import json, os, sys

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP),
                      SERVERCHAN_KEY="", WECOM_CORPID="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import Config
    from ark_relay.core.notify import Notifier


    ERR1 = ("企业微信发送失败: 60020 not allow to access from your ip, "
            "hint: [1787373915609110759172198], from ip: 112.43.40.209")
    ERR2 = ("企业微信发送失败: 60020 not allow to access from your ip, "
            "hint: [9999999999999999999999999], from ip: 112.43.40.77")

    cfg = Config()

    import logging
    from ark_relay.features.alarm import errwatch
    from ark_relay.core import notify as _notify_mod

    lines = []
    class _Lines(logging.Handler):
        def emit(self, record):
            lines.append((record.getMessage(), getattr(record, errwatch.PUSHED, False)))
    _notify_mod.log.addHandler(_Lines())

    print("[every refused send is announced - the same fault again included]")
    sent = []
    class Cap(Notifier):
        # Keyword names must match the real signature, or a routing change goes astray here silently.
        def _fan_out(self, title, body, *, order=None, stop_on_first=False):
            sent.append(title)
            return list(self.took), {}

    n = Cap(cfg)
    n.took = ["Server酱"]
    n._announce_outage({"企业微信": ERR1}, ["Server酱"])
    check("first refusal announced", len(sent), 1)
    n._announce_outage({"企业微信": ERR2}, ["Server酱"])
    check("the same fault again: announced again", len(sent), 2)
    n2 = Cap(cfg)
    n2.took = ["Server酱"]
    n2._announce_outage({"企业微信": ERR1}, ["Server酱"])
    check("after a restart too", len(sent), 3)
    check("nothing kept on disk to stay quiet with",
          "channels_down" in json.loads((TMP / "state.json").read_text(encoding="utf-8")).get("queues", {})
          if (TMP / "state.json").exists() else False, False)
    check("the title names the channel", sent[-1], "🔌 推送通道故障：企业微信")

    print("\n[the log line for each refusal]")
    lines.clear()
    n._announce_outage({"企业微信机器人": "boom"}, ["Server酱"])
    check("one line per refusal", [m for m, _ in lines], ["企业微信机器人推送失败: boom"])
    check("the notice went by Server酱 only: errwatch still pushes the line", lines[0][1], False)
    lines.clear()
    n.took = ["企业微信机器人"]
    n._announce_outage({"Server酱": "boom"}, ["企业微信机器人"])
    check("the group robot took the notice: the line is marked as already in the group", lines[0][1], True)


def _part_cli_commands():
    """The two new CLI commands exist, parse, and hand off to the right code.

`collect-retry` and `evidence` are what I run by hand to verify the relay's
new work on the machine; if the parser or the dispatch breaks, the manual
verification path is gone and nobody notices until the next incident.

    Formerly test_cli_commands.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay import __main__ as cli
    from ark_relay.features.makeup import collect_retry
    import argparse


    print("[evidence 命令：没配置的脚本什么也传不了，退出码 1，但不炸]")
    class Cfg:
        state_dir = tmpdir() / "state"; maaend_dir = None; maa_dir = None; okww_dir = None; history_dir = None
    Cfg.state_dir.mkdir(parents=True)
    rc = cli.cmd_evidence(Cfg, "MaaEnd", "", hours=2)     # a window is mandatory: the last two hours
    check("没东西可传就是 1", rc, 1)
    try:
        cli.cmd_evidence(Cfg, "MaaEnd", "2026-09-11/endfield/MaaEnd-06-17-17"); no_run = "accepted"
    except SystemExit as exc:
        no_run = str(exc)
    check("账本里没有那趟就拒绝，不悄悄全量", "--hours" in no_run)
    check("索引仍然写了一行", (Cfg.state_dir / "evidence" / "index.jsonl").exists())

    print("\n[collect-retry 命令：走的是 maybe_run，没有失败路线就说没有]")
    calls = []
    class FakeEng:
        pass
    cli._build_local_engine = lambda cfg: FakeEng()
    orig = collect_retry.maybe_run
    collect_retry.maybe_run = lambda eng, day=None: calls.append((eng, day)) or False
    try:
        rc = cli.cmd_collect_retry(Cfg, "2026-09-11")
    finally:
        collect_retry.maybe_run = orig
    check("调用了一次 maybe_run，带指定的日期", calls and calls[0][1] == "2026-09-11" and len(calls) == 1)
    check("退出码 0", rc, 0)

    print("\n[banners 命令：打印那一段、来源和核对，扣下的行让退出码变 1]")
    from ark_relay.features.banners import banners as _bn
    from datetime import datetime, timedelta
    import io, contextlib
    def fake_collect(now, *, skland_token="", failed=None, notes=None, trace=None, **_):
        # The end is relative: a fixed 09-29 11:59:59 made this fail from that noon on,
        # when the pool was no longer current (2026-09-29).
        b = _bn.Banner("鸣潮", "身赴三途", ("景燃",), datetime(2026, 9, 10, 10, 0),
                       datetime.now().replace(microsecond=0) + timedelta(days=10))
        trace.ends |= _bn._stamps(b.end)
        trace.src("鸣潮", "当期", "库街区", "身赴三途 景燃")
        trace.checks.append("鸣潮：库街区=游戏公告 ✓")
        trace.problems.append("鸣潮｜版本资讯｜B 站｜BiliFeedProblem: page 1 listed nothing")
        notes["明日方舟"] = "09-18 03:59 之后开（还有 5 天）　下一池官方还没公告"
        return [b], {}
    orig_collect = _bn.collect
    _bn.collect = fake_collect
    Cfg.skland_token = ""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = cli.cmd_banners(Cfg)
    finally:
        _bn.collect = orig_collect
    out = buf.getvalue()
    check("打印了当期行", "身赴三途 · 景燃" in out)
    check("打印了来源", "库街区｜身赴三途 景燃" in out)
    check("编出来的预告被扣下并列出", "扣下的行" in out and "09-18 03:59 之后开" in out)
    check("有扣下的行时退出码 1", rc, 1)
    check("来源问题单列出来", "--- source problems" in out and "BiliFeedProblem: page 1 listed nothing" in out)

    print("\n[参数表认得这几个命令]")
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["local", "check", "test", "report", "collect-retry", "evidence", "banners"])
    check("choices 里有", set(p._actions[1].choices) >= {"collect-retry", "evidence", "banners"})


def _part_cmd_test_channels():
    """`python -m ark_relay test` must try every channel and name only the ones that took it.

Audit s5 #3 (2026-10-13): cmd_test called send(alert=True), which stops at the first
channel that accepts, yet printed 「✅ 已通过 <every configured channel> 发出」; and it
filed the test as a real group alarm (alerts/ copy). Channels are faked here.

    Formerly test_cmd_test_channels.py.
    """
    import contextlib
    import io
    import os


    os.environ.update(ARK_STATE_DIR=str(tmpdir()), ARK_HISTORY_DIR=str(tmpdir()))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay import __main__ as relay_main
    from ark_relay.core import notify
    from ark_relay.core.config import Config


    class Chan:
        def __init__(self, ok):
            self.enabled, self.ok, self.got = True, ok, []

        def send_text(self, *a):
            if not self.ok:
                raise RuntimeError("refused")
            self.got.append(a)


    bot, sc = Chan(True), Chan(False)
    copied: list = []
    real_init = notify.Notifier.__init__


    def fake_init(self, cfg):
        real_init(self, cfg)
        self.wecom_bot, self.serverchan = bot, sc
        self.wecom = Chan(True)
        self.wecom.enabled = False


    notify.Notifier.__init__ = fake_init
    notify.Notifier._copy_alarm = lambda self, t, b: copied.append(t)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = relay_main.cmd_test(Config())
    text = out.getvalue()
    print(text)

    print("[the robot takes it, Server酱 refuses]")
    check("Server酱 was tried too", (len(bot.got), "Server酱: refused" in text), (1, True))
    check("success names only the robot", "✅ 已通过 企业微信机器人 发出" in text, True)
    check("Server酱 is not named as delivered", "企业微信机器人、Server酱" in text, False)
    check("a refused channel fails the self-test", rc, 1)
    check("not filed as a group alarm", copied, [])

    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")


def _part_command_table():
    """relay/README.md 的命令表必须和代码里的白名单一一对上。

2026-09-08 审出来的：表里说 `run_now` 是「没实现、会明确拒绝」，代码里它真会调
`/api/dispatch/start` 派发一趟队列；`skip_shutdown`、`weekly_boss`、`set_config`、
`set_master` 四个命令干脆不在表里——其中 skip_shutdown 就是「吃掉下一次关机机会
且不带时效」的那个开关，已经让机器白开两夜，而唯一一张说明表里找不到它。

文档和代码分头维护，早晚会分家。这条测试让它们分不了家。

    Formerly test_command_table.py.
    """
    import re

    ROOT = Path(__file__).resolve().parents[1]
    code = (ROOT / "ark_relay" / "features" / "phone" / "commands.py").read_text(encoding="utf-8")
    doc = (ROOT / "README.md").read_text(encoding="utf-8")

    allowed = set()
    for m in re.finditer(r"^(REVERSIBLE|MUTATING) = \{([^}]*)\}", code, re.M | re.S):
        allowed |= {x.strip().strip('"') for x in m.group(2).split(",") if x.strip()}
    listed = set(re.findall(r"^\| `(\w+)` \|", doc, re.M))

    if not allowed:
        fails.append("没从 commands.py 里读出白名单——正则该跟着代码改")
    missing = sorted(allowed - listed)
    extra = sorted(listed - allowed)
    if missing:
        fails.append(f"命令表漏了：{missing}（代码认，文档没写）")
    if extra:
        fails.append(f"命令表多了：{extra}（文档写了，代码不认）")

    print(f"  代码白名单 {len(allowed)} 个，文档表 {len(listed)} 个")
    for f in fails:
        print(f"  ✗ {f}")
    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_commands_gates():  # noqa: C901 - the whole body of the file this part was
    """往生产配置里写东西的那条路——四道闸门一道都不许塌。

这个文件防的是**一类损失：配置被写坏，于是刷错关卡、烧掉理智药**。
826 就是这么来的：凭空造了一个字段、编了一个下标的含义，写进去，第二天早班
按错的配置跑了一整趟。`commands.py` 25 个函数里 19 个从来没有被任何测试调用过，
包括「结构化 diff 不符预期就回滚」这道唯一能拦住 826 的闸门本身。

四道闸门（relay/README.md「命令的四道闸门」）：
  ① 白名单——不在表里的动作直接拒，模型不许自己发 JSON patch
  ② 人工确认——会写盘的动作没确认不动手
  ③ 落地校验——备份→改→解析→结构化 diff，多改一个字段就整个放弃并回滚
  ④ 回报——成功、失败、拒绝都要说出来，而且要说人话

外加一条同样致命的：白名单里有名字、apply_command 里却没有分支，
手机上按下去什么也不会发生，而屏幕上一片绿。

全程用临时目录里的假配置，`_mas` 换成假的，不碰网络、不碰真机。

    Formerly test_commands_gates.py.
    """
    import json
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    STATE = tmpdir()
    AUTOMAS = tmpdir()
    os.environ["ARK_STATE_DIR"] = str(STATE)
    os.environ["ARK_AUTOMAS_DIR"] = str(AUTOMAS)

    from datetime import datetime
    from ark_relay.features.phone import commands
    from ark_relay.features.modes import modes
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore


    # The real config's shape, cut down to what these gates touch: one script uuid,
    # one user uuid, Info/* per user and Game/WaitTime per script (docs/CONFIG.md).
    SID = "59da8762-8fa7-4f2b-9c1e-000000000001"
    UID = "b0c1d2e3-0000-0000-0000-000000000002"


    def sample() -> dict:
        return {SID: {
            "Info": {"Name": "MAA"},
            "Game": {"WaitTime": 60},
            "SubConfigsInfo": {"UserData": {UID: {"Info": {
                "Stage": "AT-4", "StageMode": "Fixed", "MedicineNumb": 0,
                "Annihilation": "Close", "RunTimesLimit": 3}}}}}}


    CFG = AUTOMAS / "config" / "ScriptConfig.json"


    def reset_cfg(data: "dict | None" = None) -> str:
        CFG.parent.mkdir(parents=True, exist_ok=True)
        for old in CFG.parent.glob("ScriptConfig.json.bak-*"):
            old.unlink()
        raw = json.dumps(data if data is not None else sample(),
                         ensure_ascii=False, indent=2)
        CFG.write_text(raw, encoding="utf-8")
        return raw


    def cfg_raw() -> str:
        return CFG.read_text(encoding="utf-8")


    def backups() -> list[Path]:
        return sorted(CFG.parent.glob("ScriptConfig.json.bak-*"))


    # ---------------------------------------------------------------- 闸门 ①

    print("[闸门① 白名单：不在表里的动作一律拒绝]")
    for bad in ("format_disk", "poweroff_now", "", "SET_STAGE", "set stage",
                "run_now; rm -rf", "set_config2", None, 123):
        ok, msg = commands.apply_command({"action": bad, "confirmed": True})
        check(f"拒绝 {bad!r}", (ok, "不在允许的清单里" in msg), (False, True))
        check(f"拒绝 {bad!r} 的话里不带原样的输入", bool(bad) and isinstance(bad, str) and bad in msg, False)
    check("完全没有 action 字段也拒绝",
          commands.apply_command({"confirmed": True})[0], False)
    # Trimmed, not rejected: a name with stray whitespace is still that action.
    check("前后空格会被去掉，不当成陌生动作",
          "不在允许的清单里" in commands.apply_command({"action": " set_stage "})[1], False)

    check("ALLOWED 就是两张表的并集",
          commands.ALLOWED, commands.REVERSIBLE | commands.MUTATING)
    # An action in both tables would take the reversible path and skip gate ②.
    check("两张表不许有交集（同名会绕过人工确认）",
          commands.REVERSIBLE & commands.MUTATING, set())

    print("\n[白名单里有名字，apply_command 里就必须有分支]")
    # Otherwise the button exists on the phone, does nothing, and reports nothing.


    def offline_mas(path, body=None, timeout=20):
        # What urlopen raises when nothing listens: the one shape that means "AUTO-MAS
        # is down" (annihilation._backend_unreachable); any other error means it is up.
        raise __import__("urllib.error").error.URLError(ConnectionRefusedError(61, "Connection refused"))


    commands._mas = offline_mas
    minimal = {
        "set_stage": {"value": ""}, "set_medicine": {"value": None},
        "set_wait_time": {"value": None}, "toggle_task": {"name": "x"},
        "set_config": {}, "set_master": {}, "run_now": {},
        "skip_today": {}, "unskip_today": {}, "debug_mode": {"off": True}, "weekly_boss": {},
        "echo_farm": {"boss": 1, "until": "08:30"}, "echo_farm_stop": {},
        "echo_farm_until": {"until": "21:00"},
        "skip_shutdown": {"off": True},
        "tacet_shots": {"on": False},
        "monthcard": {"game": "明日方舟", "left": 3},
    }
    check("每个白名单动作都准备了样例指令",
          sorted(minimal), sorted(commands.ALLOWED))
    for action in sorted(commands.ALLOWED):
        reset_cfg()
        _, msg = commands.apply_command({"action": action, "confirmed": True,
                                         **minimal[action]})
        check(f"{action} 有人接手（不是「未处理的动作」）",
              msg.startswith("未处理的动作"), False)
    # Left installed on purpose: set_stage / set_medicine / set_wait_time now ask the
    # backend first and edit the file only when it does not answer. The file-path
    # checks below must test that branch deliberately, not because nothing happens
    # to listen on 127.0.0.1:36163. Sections that want a backend use with_mas().

    # ---------------------------------------------------------------- 闸门 ②

    print("\n[闸门② 会写盘的动作，没有人工确认就不许动]")
    for action in sorted(commands.MUTATING):
        before = reset_cfg()
        ok, msg = commands.apply_command({"action": action, "value": "1-7",
                                          "queue": "早班", "script": "MAA",
                                          "path": "Info.Stage", "game": "MAA"})
        check(f"{action} 未确认被拒", (ok, "人工确认" in msg), (False, True))
        # alerts 20261010 04:16:13: 「📱 配置没改成」 reached the group as 「动作 set_master 需要人工确认…」.
        check(f"{action} 拒绝的话里不带动作原名", action in msg, False)
        check(f"{action} 未确认时配置文件一个字节没动", cfg_raw(), before)
        check(f"{action} 未确认时不留备份", backups(), [])

    reset_cfg()
    ok, msg = commands.apply_command({"action": "skip_shutdown"})
    check("可逆动作不需要确认，直接放行", ok, True)

    # ---------------------------------------------------------------- _STAGE_RE

    print("\n[关卡号形状：不认识就拒，绝不「猜一个」]")
    for good in ("TO-5", "CE-6", "1-7", "LS-6", "AT-4", "S4-1", "H8-4"):
        check(f"{good} 是合法形状", bool(commands._STAGE_RE.match(good)), True)
    for bad in ("", "TO5", "TO-", "-5", "1-7-3", "TO-5 ", " TO-5",
                "ANNIHILATION-1", "1-7; rm -rf /", "剿灭-1", "TOOOO-5",
                'AT-4","MedicineNumb":99'):
        check(f"{bad!r} 不是合法形状", bool(commands._STAGE_RE.match(bad)), False)

    before = reset_cfg()
    ok, msg = commands._set_stage('AT-4","MedicineNumb":99')
    check("注入形状的关卡号被拒", (ok, "不合法" in msg), (False, True))
    check("被拒时配置没动", cfg_raw(), before)

    ok, msg = commands._set_stage("to-5")
    check("小写自动转大写后写入", ok, True)
    check("写进去的是大写",
          json.loads(cfg_raw())[SID]["SubConfigsInfo"]["UserData"][UID]["Info"]["Stage"],
          "TO-5")
    check("回报是人话，不是路径", msg, "刷取关卡：AT-4 → TO-5")
    check("写之前留了备份", len(backups()), 1)
    check("备份里是原来的内容", backups()[0].read_text(encoding="utf-8"), before)

    reset_cfg()
    ok, msg = commands._set_stage("AT-4")
    check("写成和现在一样的值算成功，不算 diff 报警", (ok, msg),
          (True, "已经是这个状态，无需改动"))
    check("没改动就不留备份", backups(), [])

    # Two users in the file: which one did the operator mean? The regex would hit
    # the first one silently.
    two = sample()
    two[SID]["SubConfigsInfo"]["UserData"]["another-uid"] = {"Info": {"Stage": "1-7"}}
    before = reset_cfg(two)
    ok, msg = commands._set_stage("CE-6")
    check("文件里有两处 Stage 时拒绝改，不挑一个下手",
          (ok, "预期恰好 1 处" in msg), (False, True))
    check("拒绝时文件没动", cfg_raw(), before)

    CFG.unlink()
    check("配置文件不存在时拒绝", commands._set_stage("1-7")[0], False)

    # ---------------------------------------------------------------- 数值范围

    print("\n[理智药和等待秒数的范围：越界必须拒，不许写进去让别人改回来]")
    for bad in (None, "很多", "3.5", [3]):
        check(f"理智药 {bad!r} 不是整数",
              (commands._set_medicine(bad)[0], "不是整数" in commands._set_medicine(bad)[1]),
              (False, True))
    for bad in (-1, 1000, 99999):
        check(f"理智药 {bad} 越界", commands._set_medicine(bad)[0], False)
    reset_cfg()
    check("理智药 0 合法（本来就是 0，报「无需改动」）",
          commands._set_medicine(0), (True, "已经是这个状态，无需改动"))
    reset_cfg()
    ok, msg = commands._set_medicine(3)
    check("理智药 3 写得进去", (ok, msg), (True, "理智药上限：0 个 → 3 个"))

    # AUTO-MAS's own schema declares ge=60 and silently clamps anything smaller.
    for bad in (0, 30, 59, 601, "六十"):
        check(f"等待秒数 {bad!r} 被拒", commands._set_wait_time(bad)[0], False)
    check("拒 59 秒时说清楚是 AUTO-MAS 的下限",
          "60" in commands._set_wait_time(59)[1], True)
    reset_cfg()
    check("等待 60 秒合法", commands._set_wait_time(60)[0], True)
    reset_cfg()
    ok, msg = commands._set_wait_time(600)
    check("等待 600 秒合法且回报是人话", (ok, msg),
          (True, "终末地启动后等待：60 秒 → 600 秒"))

    # docs/SILENT-FAILURES-AUDIT.md commands.py:315 - a backend that times out or errors
    # is up: editing the file then is undone from its memory while the phone hears success.
    print("\n[backend slow or erroring: stage / medicine / wait-time are refused, file untouched]")
    for label, exc in (("timeout", TimeoutError("timed out")),
                       ("HTTP 500", __import__("urllib.error").error.HTTPError("http://x", 500, "err", {}, None))):
        def broken(path, body=None, timeout=20, exc=exc):
            raise exc
        commands._mas = broken
        for what, call in (("stage", lambda: commands._set_stage("CE-6")),
                           ("medicine", lambda: commands._set_medicine(3)),
                           ("wait time", lambda: commands._set_wait_time(120))):
            before = reset_cfg()
            ok, msg = call()
            check(f"{label}: {what} not claimed", ok, False)
            check(f"{label}: {what} says the scheduler did not answer", "调度程序没应答" in msg, True)
            check(f"{label}: {what} file untouched, no backup", (cfg_raw() == before, backups()), (True, []))
    commands._mas = offline_mas

    print("\n[toggle_task 明确拒绝，不猜任务名]")
    ok, msg = commands._toggle_task("自动战斗", True)
    check("toggle_task 一律拒绝", (ok, "set_config" in msg), (False, True))

    # ---------------------------------------------------------------- 闸门 ③

    print("\n[闸门③ 结构化 diff：多改一个字段就整个放弃——826 唯一能被拦住的地方]")
    before = reset_cfg()

    ok, msg = commands._safe_rewrite(CFG, lambda raw: raw.replace('"Fixed"', '"Auto"'),
                                     expect_changed=2)
    check("只改了 1 处但预期 2 处，放弃", (ok, "和预期不符" in msg), (False, True))
    check("放弃时文件没动", cfg_raw(), before)

    ok, msg = commands._safe_rewrite(
        CFG, lambda raw: raw.replace('"AT-4"', '"1-7"').replace('"MedicineNumb": 0',
                                                                '"MedicineNumb": 99'),
        expect_changed=1)
    check("正则误伤了第二个字段，放弃", (ok, "改动 2" in msg), (False, True))
    check("误伤时理智药没被烧", cfg_raw(), before)

    def add_key(raw: str) -> str:
        d = json.loads(raw)
        d[SID]["Info"]["凭空造的"] = 1
        return json.dumps(d, ensure_ascii=False, indent=2)


    ok, msg = commands._safe_rewrite(CFG, add_key, expect_changed=1)
    check("凭空多出一个字段，放弃", (ok, "新增 1" in msg), (False, True))
    check("多字段时文件没动", cfg_raw(), before)


    def drop_key(raw: str) -> str:
        d = json.loads(raw)
        del d[SID]["Game"]["WaitTime"]
        return json.dumps(d, ensure_ascii=False, indent=2)


    ok, msg = commands._safe_rewrite(CFG, drop_key, expect_changed=0)
    check("少了一个字段，放弃", (ok, "删除 1" in msg), (False, True))
    check("少字段时文件没动", cfg_raw(), before)


    def boom(raw: str) -> str:
        raise ValueError("正则没匹配上")


    ok, msg = commands._safe_rewrite(CFG, boom, expect_changed=1)
    check("生成改动时抛异常，不碰盘", (ok, "生成改动失败" in msg), (False, True))
    check("抛异常时文件没动", cfg_raw(), before)

    ok, msg = commands._safe_rewrite(CFG, lambda raw: raw[:-3], expect_changed=1)
    check("改完不是合法 JSON，放弃", (ok, "JSON 非法" in msg), (False, True))
    check("非法 JSON 时文件没动", cfg_raw(), before)

    CFG.write_text("{这不是 JSON", encoding="utf-8")
    ok, msg = commands._safe_rewrite(CFG, lambda raw: raw, expect_changed=1)
    check("原文件就不是 JSON 时拒绝改（不许在坏文件上叠改动）",
          (ok, "不是合法 JSON" in msg), (False, True))

    before = reset_cfg()
    saved_write = commands.atomic_write_text


    def cannot_write(path, text, newline=None):
        raise OSError("磁盘满了")


    commands.atomic_write_text = cannot_write
    ok, msg = commands._safe_rewrite(CFG, lambda raw: raw.replace('"Fixed"', '"Auto"'),
                                     expect_changed=1)
    commands.atomic_write_text = saved_write
    check("写盘失败要回滚并说出来", (ok, "已回滚" in msg), (False, True))
    check("回滚后内容和原来一模一样", cfg_raw(), before)

    # ---------------------------------------------------------------- _flatten

    print("\n[_flatten：diff 的地基，漏掉一层就等于那一层没有闸门]")
    check("嵌套字典摊平成路径",
          commands._flatten({"a": {"b": 1}}), {"/a/b": 1})
    check("列表按下标摊平（两个下标互换必须被看见）",
          commands._flatten({"a": [10, 20]}), {"/a[0]": 10, "/a[1]": 20})
    check("列表里的字典也摊得到底",
          commands._flatten({"a": [{"b": True}]}), {"/a[0]/b": True})
    check("空字典摊出来是空", commands._flatten({}), {})
    check("None 也是一个值，不许被吞", commands._flatten({"a": None}), {"/a": None})
    a = commands._flatten({"x": [1, 2]})
    b = commands._flatten({"x": [2, 1]})
    check("列表顺序变了会被 diff 看见",
          {k for k in a.keys() & b.keys() if a[k] != b[k]}, {"/x[0]", "/x[1]"})

    # ---------------------------------------------------------------- 闸门 ④

    print("\n[闸门④ 回报要说人话：路径里的 uuid 不许出现在推送里]")
    # The operator reads this on a phone; `/59da8762-.../Game/WaitTime` says nothing
    # (operator feedback, 2026-08-20).
    check("等待秒数带单位",
          commands._humanize(f"/{SID}/Game/WaitTime", 60, 120),
          "终末地启动后等待：60 秒 → 120 秒")
    check("理智药带单位",
          commands._humanize(f"/{SID}/Info/MedicineNumb", 0, 3),
          "理智药上限：0 个 → 3 个")
    check("关卡不带单位",
          commands._humanize(f"/{SID}/Info/Stage", "AT-4", "TO-5"),
          "刷取关卡：AT-4 → TO-5")
    check("布尔值说开关，不说 True/False",
          commands._humanize("/x/TimeEnabled", True, False), "队列定时：开 → 关")
    check("没登记的字段退回字段名，不吐整条路径",
          commands._humanize(f"/{SID}/Info/SomethingNew", 1, 2),
          "SomethingNew：1 → 2")
    for field in ("Stage", "MedicineNumb", "WaitTime", "Annihilation",
                  "TimeEnabled", "Enabled", "RunTimesLimit", "StageMode"):
        line = commands._humanize(f"/{SID}/Info/{field}", 1, 2)
        check(f"{field} 的回报里没有 uuid", SID in line, False)

    # ---------------------------------------------------------------- set_config

    print("\n[set_config：读现值、路径必须已存在、写完回读——826 缺的就是这三条]")


    class FakeMas:
        """The AUTO-MAS backend, in memory. Records every call so «没写盘» is provable."""

        def __init__(self, *, honour_writes=True):
            self.calls: list[tuple[str, dict]] = []
            self.honour_writes = honour_writes
            self.scripts = {SID: {"Info": {"Name": "MAA"}}}
            self.users = {SID: {UID: {"Info": {"Stage": "AT-4", "MedicineNumb": 0}}}}

        def __call__(self, path, body=None, timeout=20):
            body = body or {}
            self.calls.append((path, body))
            if path == "/api/scripts/get":
                return {"data": self.scripts}
            if path == "/api/scripts/user/get":
                return {"data": self.users.get(body["scriptId"], {})}
            if path == "/api/scripts/user/update":
                if self.honour_writes:
                    self._merge(self.users[body["scriptId"]][body["userId"]],
                                body["data"])
                return {"status": "success"}
            if path == "/api/dispatch/start":
                return {"status": "success"}
            raise AssertionError(f"测试没准备这个端点: {path}")

        def _merge(self, dst, src):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    self._merge(dst[k], v)
                else:
                    dst[k] = v

        def wrote(self):
            return [c for c in self.calls if c[0] == "/api/scripts/user/update"]


    def with_mas(fake, fn):
        saved, commands._mas = commands._mas, fake
        try:
            return fn()
        finally:
            commands._mas = saved


    check("缺 script/path 就拒",
          with_mas(FakeMas(), lambda: commands._set_config({"script": "MAA"}))[0],
          False)
    check("缺 value 就拒（不许把「没给」当成 None 写进去）",
          with_mas(FakeMas(),
                   lambda: commands._set_config({"script": "MAA", "path": "Info.Stage"}))[1],
          "set_config 需要 value")

    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "MAA", "path": "Info.凭空造的", "value": 1}))
    check("路径不存在就拒（说清中继不会自己新建）", (ok, "已拒绝" in msg and "不会自己新建" in msg), (False, True))
    check("拒绝时一次写请求都没发出去", f.wrote(), [])

    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "没这个脚本", "path": "Info.Stage", "value": "1-7"}))
    check("脚本不存在就拒", (ok, "找不到脚本" in msg), (False, True))
    check("找不到脚本时不写", f.wrote(), [])

    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "MAA", "path": "Info.Stage", "value": "AT-4"}))
    check("值本来就一样：算成功且不写", (ok, f.wrote()), (True, []))

    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "maa", "path": "Info.Stage", "value": "1-7"}))
    check("脚本名大小写不敏感，改得动", ok, True)
    check("回报带上「原值 → 新值」", msg, "maa 的 Info.Stage：'AT-4' → '1-7'")
    check("确实只写了一次", len(f.wrote()), 1)
    check("写的是嵌套结构，不是拍平的键",
          f.wrote()[0][1]["data"], {"Info": {"Stage": "1-7"}})

    f = FakeMas(honour_writes=False)
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "MAA", "path": "Info.Stage", "value": "1-7"}))
    check("写了但回读还是老值：必须报失败，不许报绿",
          (ok, "写了但没生效" in msg), (False, True))

    print("\n[后端在：关卡 / 理智药 / 等待秒数走调度程序，不碰文件（2026-09-30 早班停用被内存写回盖掉的同一个坑）]")
    MAAEND_SID = "3e5d0000-0000-0000-0000-0000000maaend"


    class BackendMas(FakeMas):
        """FakeMas plus the script-level endpoints and AUTO-MAS's failure shape."""

        def __init__(self, *, honour_writes=True, refuse=None):
            super().__init__(honour_writes=honour_writes)
            self.refuse = refuse          # a message: updates answer HTTP 200 + code 500
            self.scripts[MAAEND_SID] = {"Info": {"Name": "MaaEnd"},
                                        "Game": {"WaitTime": 60, "Path": "D:/x"},
                                        "Run": {"RunTimesLimit": 3}}

        def __call__(self, path, body=None, timeout=20):
            if self.refuse and path in ("/api/scripts/update", "/api/scripts/user/update"):
                self.calls.append((path, body or {}))
                return {"code": 500, "status": "error", "message": self.refuse}
            if path == "/api/scripts/get":
                self.calls.append((path, body or {}))
                return {"code": 200, "data": json.loads(json.dumps(self.scripts))}
            if path == "/api/scripts/update":
                self.calls.append((path, body))
                if self.honour_writes:
                    self._merge(self.scripts[body["scriptId"]], body["data"])
                return {"code": 200, "status": "success"}
            return super().__call__(path, body, timeout)

        def script_writes(self):
            return [c for c in self.calls if c[0] == "/api/scripts/update"]


    before = reset_cfg()
    b = BackendMas()
    ok, msg = with_mas(b, lambda: commands._set_stage("to-5"))
    check("关卡：后端在时成功", ok, True)
    check("关卡：写的是 MAA 用户的 Info.Stage",
          [c[1] for c in b.wrote()],
          [{"scriptId": SID, "userId": UID, "data": {"Info": {"Stage": "TO-5"}}}])
    check("关卡：调度程序里现在是 TO-5", b.users[SID][UID]["Info"]["Stage"], "TO-5")
    check("关卡：回报是人话并说调度程序已确认", msg, "刷取关卡：AT-4 → TO-5（调度程序已确认）")
    check("关卡：配置文件一个字节没动", cfg_raw(), before)
    check("关卡：没留 ScriptConfig 备份", backups(), [])

    b = BackendMas()
    ok, msg = with_mas(b, lambda: commands._set_stage("AT-4"))
    check("关卡：和现在一样 → 成功且一次都不写", (ok, msg, b.wrote()),
          (True, "已经是这个状态，无需改动", []))

    before = reset_cfg()
    b = BackendMas()
    ok, msg = with_mas(b, lambda: commands._set_medicine(3))
    check("理智药：后端在时成功", (ok, msg), (True, "理智药上限：0 个 → 3 个（调度程序已确认）"))
    check("理智药：写的是 Info.MedicineNumb",
          [c[1]["data"] for c in b.wrote()], [{"Info": {"MedicineNumb": 3}}])
    check("理智药：配置文件没动、没备份", (cfg_raw(), backups()), (before, []))

    before = reset_cfg()
    b = BackendMas()
    ok, msg = with_mas(b, lambda: commands._set_wait_time(120))
    check("等待秒数：后端在时成功", (ok, msg), (True, "终末地启动后等待：60 秒 → 120 秒（调度程序已确认）"))
    check("等待秒数：只发 MaaEnd 脚本的 Game.WaitTime 这一叶",
          [c[1] for c in b.script_writes()],
          [{"scriptId": MAAEND_SID, "data": {"Game": {"WaitTime": 120}}}])
    check("等待秒数：Game 其余的键还在（合并，不是整组替换）",
          b.scripts[MAAEND_SID]["Game"], {"WaitTime": 120, "Path": "D:/x"})
    check("等待秒数：没碰用户那一层", b.wrote(), [])
    check("等待秒数：配置文件没动、没备份", (cfg_raw(), backups()), (before, []))

    b = BackendMas()
    ok, msg = with_mas(b, lambda: commands._set_wait_time(60))
    check("等待秒数：和现在一样 → 成功且不写", (ok, msg, b.script_writes()),
          (True, "已经是这个状态，无需改动", []))

    b = BackendMas()
    del b.scripts[MAAEND_SID]["Game"]["WaitTime"]
    ok, msg = with_mas(b, lambda: commands._set_wait_time(120))
    check("等待秒数：调度程序里没有这一项 → 拒绝，不新建",
          (ok, "已拒绝" in msg and "不会自己新建" in msg, b.script_writes()), (False, True, []))

    b = BackendMas()
    del b.scripts[MAAEND_SID]
    ok, msg = with_mas(b, lambda: commands._set_wait_time(120))
    check("等待秒数：没有 MaaEnd 脚本 → 失败，不退回写文件",
          (ok, "MaaEnd" in msg, cfg_raw() == before, backups()), (False, True, True, []))

    print("\n[后端在但没生效 / 拒收：报失败，绝不退回去写文件]")
    for label, fn in (("关卡", lambda: commands._set_stage("TO-5")),
                      ("理智药", lambda: commands._set_medicine(5)),
                      ("等待秒数", lambda: commands._set_wait_time(200))):
        before = reset_cfg()
        ok, msg = with_mas(BackendMas(honour_writes=False), fn)
        check(f"{label}：写了读出来还是老值 → 失败", (ok, "写了但没生效" in msg), (False, True))
        check(f"{label}：没生效时配置文件没动、没备份", (cfg_raw(), backups()), (before, []))
        busy = "脚本 MaaEnd 正在运行, 无法更新配置项"
        ok, msg = with_mas(BackendMas(refuse=busy), fn)
        check(f"{label}：回复体 code=500 → 失败且原话带回", (ok, busy in msg), (False, True))
        check(f"{label}：拒收时配置文件没动、没备份", (cfg_raw(), backups()), (before, []))

    before = reset_cfg()
    b = BackendMas()
    b.scripts = {}
    ok, msg = with_mas(b, lambda: commands._set_stage("TO-5"))
    check("关卡：后端在但找不到 MAA → 失败，不退回写文件",
          (ok, "找不到脚本" in msg, cfg_raw(), backups()), (False, True, before, []))

    print("\n[后端不在（连不上）：走原来的文件路]")
    from urllib.error import URLError


    def refused(path, body=None, timeout=20):
        raise URLError(ConnectionRefusedError(61, "Connection refused"))


    reset_cfg()
    ok, msg = with_mas(refused, lambda: commands._set_stage("TO-5"))
    check("关卡：连不上 → 改文件", (ok, msg, len(backups())), (True, "刷取关卡：AT-4 → TO-5", 1))
    reset_cfg()
    ok, msg = with_mas(refused, lambda: commands._set_wait_time(90))
    check("等待秒数：连不上 → 改文件", (ok, msg), (True, "终末地启动后等待：60 秒 → 90 秒"))
    check("等待秒数：文件里真的是 90", json.loads(cfg_raw())[SID]["Game"]["WaitTime"], 90)

    print("\n[set_config 同样认回复体里的 code]")
    f = BackendMas(refuse="配置被锁")
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "MAA", "path": "Info.Stage", "value": "1-7"}))
    check("set_config：code=500 → 失败且带原话", (ok, "配置被锁" in msg), (False, True))

    print("\n[_dig / _nest：路径解析本身]")
    check("_dig 取得到嵌套值",
          commands._dig({"Info": {"Stage": "AT-4"}}, "Info.Stage"), "AT-4")
    for bad in ("Info.Nope", "Nope.Stage", "Info.Stage.More"):
        try:
            commands._dig({"Info": {"Stage": "AT-4"}}, bad)
            check(f"_dig 对 {bad} 应该抛 KeyError", "没抛", "KeyError")
        except KeyError:
            check(f"_dig 对不存在的 {bad} 抛 KeyError", True, True)
    check("_nest 造出嵌套写入体",
          commands._nest("Task.IfFight", True), {"Task": {"IfFight": True}})
    check("_nest 单层也行", commands._nest("Stage", "1-7"), {"Stage": "1-7"})

    # ---------------------------------------------------------------- skip_today

    print("\n[skip_today：过期的指令不许生效，老队列名要认得]")
    today = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    # The dispatch sweep above already ran skip_today once; start from a clean slate.
    StateStore(STATE).pop("queues", f"skip_day:{today}")
    ok, msg = commands._skip_today("早班", "2020-01-01")
    check("指定日期已经过去：拒绝，别跳掉没人要跳的那天",
          (ok, "过期" in msg), (False, True))
    check("过期指令没写进状态",
          StateStore(STATE).get("queues", f"skip_day:{today}"), None)

    ok, msg = commands._skip_today("新队列")
    check("老队列名映射成现名", ok, True)
    check("状态里存的是现名",
          StateStore(STATE).get("queues", f"skip_day:{today}"), "早班")
    ok, msg = commands._skip_today("晚班", today)
    check("今天已跳过别的队列：两个都存下，原来的不许被换掉（2026-09-30）",
          (ok, StateStore(STATE).get("queues", f"skip_day:{today}")),
          (True, ["早班", "晚班"]))
    ok, msg = commands._skip_today("早班", today)
    check("同一个队列再跳一次照样成功，不重复存",
          (ok, "已经" in msg, StateStore(STATE).get("queues", f"skip_day:{today}")),
          (True, True, ["早班", "晚班"]))
    ok, msg = modes.unskip(STATE, None, "早班")
    check("取消其中一个：只删它，另一个还在",
          (ok, StateStore(STATE).get("queues", f"skip_day:{today}")), (True, "晚班"))
    StateStore(STATE).pop("queues", f"skip_day:{today}")
    ok, _ = commands._skip_today("晚班", today)
    check("带上今天的日期照样生效",
          StateStore(STATE).get("queues", f"skip_day:{today}"), "晚班")
    ok, msg = modes.unskip(STATE, None, "早班")
    check("取消没跳过的队列：说出今天跳过的是哪个", (ok, "晚班" in msg), (False, True))
    StateStore(STATE).pop("queues", f"skip_day:{today}")

    # ---------------------------------------------------------------- 队列进出

    print("\n[skip a script in a queue for today: only Schedule.Days changes, and it goes back verbatim]")
    # Since the 2026-10-11 hand-over (item 16) the item stays in the queue; today's
    # weekday leaves its Schedule.Days (AUTO-MAS schema.py QueueItem_Schedule.Days,
    # task_manager.py _is_script_scheduled_today) and the saved list is written back.
    ALL_DAYS = list(commands.WEEKDAYS)
    TODAY = commands.WEEKDAYS[datetime.now(tz=SERVER_TZ).weekday()]


    class FakeQueueMas(FakeMas):
        def __init__(self):
            super().__init__()
            self.qid = "queue-0001"
            # OK-WW exists as a script but is not in this queue - the "nothing to
            # skip" case.
            self.scripts["s-okww"] = {"Info": {"Name": "OK-WW"}}
            self.queues = {self.qid: {"Info": {"Name": "早班"}}}
            self.items = {"u1": {"Info": {"ScriptId": "s-endfield"}, "Schedule": {"Days": list(ALL_DAYS)}},
                          "u2": {"Info": {"ScriptId": SID}, "Schedule": {"Days": list(ALL_DAYS)}},
                          "u3": {"Info": {"ScriptId": "s-wuwa"}}}
            self.order = ["u1", "u2", "u3"]
            self.writes = []

        def __call__(self, path, body=None, timeout=20):
            body = body or {}
            if path == "/api/queue/get":
                self.calls.append((path, body))
                return {"data": self.queues}
            if path == "/api/queue/item/get":
                self.calls.append((path, body))
                return {"index": [{"uid": u} for u in self.order], "data": json.loads(json.dumps(self.items))}
            if path in ("/api/queue/item/delete", "/api/queue/item/add", "/api/queue/item/order"):
                raise AssertionError(f"a today-only skip must not call {path}")
            if path == "/api/queue/item/update":
                self.writes.append(body["data"])
                item = self.items[body["queueItemId"]]
                for sec, val in body["data"].items():
                    item.setdefault(sec, {}).update(val)
                return {"status": "success"}
            return super().__call__(path, body, timeout)


    q = FakeQueueMas()
    rec = with_mas(q, lambda: commands.skip_script_in_queue("早班", "MAA"))
    check("the record keeps the item, its position and its original days",
          rec and (rec["queueItemId"], rec["position"], rec["days"]), ("u2", 1, ALL_DAYS))
    check("the item is still in the queue", q.order, ["u1", "u2", "u3"])
    check("only today left its days", q.items["u2"]["Schedule"]["Days"], [d for d in ALL_DAYS if d != TODAY])
    check("only Schedule was sent (no Info, so AUTO-MAS's running-queue guard does not refuse it)",
          [list(w) for w in q.writes], [["Schedule"]])
    check("the other items are untouched", q.items["u1"]["Schedule"]["Days"], ALL_DAYS)
    check("the record says which server day it was made on",
          rec and rec.get("day"), datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
    check("a second skip the same day: None, so the trimmed list is never saved as the original",
          with_mas(q, lambda: commands.skip_script_in_queue("早班", "MAA")), None)
    ok = with_mas(q, lambda: commands.restore_script_in_queue(rec))
    check("restore succeeds", ok, True)
    check("the original days are back verbatim", q.items["u2"]["Schedule"]["Days"], ALL_DAYS)
    check("restoring again is a no-op success", with_mas(q, lambda: commands.restore_script_in_queue(rec)), True)
    check("…and writes nothing more", len(q.writes), 2)

    q4 = FakeQueueMas()
    q4.items["u3"]["Info"]["ScriptId"] = "s-okww"      # an item that never set Schedule.Days runs every day
    rec4 = with_mas(q4, lambda: commands.skip_script_in_queue("早班", "OK-WW"))
    check("no Schedule.Days means every day; today is dropped from all seven",
          (rec4 and rec4["days"], q4.items["u3"]["Schedule"]["Days"]), (ALL_DAYS, [d for d in ALL_DAYS if d != TODAY]))

    q5 = FakeQueueMas()
    q5.items["u2"]["Schedule"]["Days"] = [d for d in ALL_DAYS if d != TODAY]
    check("the user's own days already leave out today: None, nothing written",
          (with_mas(q5, lambda: commands.skip_script_in_queue("早班", "MAA")), q5.writes), (None, []))


    class StuckQueueMas(FakeQueueMas):
        """AUTO-MAS accepts item/update but the days never change."""

        def __call__(self, path, body=None, timeout=20):
            if path == "/api/queue/item/update":
                self.writes.append(body["data"])
                return {"status": "success"}            # accepted, not applied
            return super().__call__(path, body, timeout)


    import logging
    _warned = []


    class _Grab(logging.Handler):
        def emit(self, record):
            _warned.append((record.levelno, record.getMessage()))


    _h = _Grab()
    commands.log.addHandler(_h)
    q3 = StuckQueueMas()
    try:
        with_mas(q3, lambda: commands.skip_script_in_queue("早班", "MAA"))
        raised = ""
    except RuntimeError as exc:
        raised = str(exc)
    check("skip not applied on read-back: raises, so the caller reports it", TODAY in raised, True)
    q3.items["u2"]["Schedule"]["Days"] = [d for d in ALL_DAYS if d != TODAY]
    ok3 = with_mas(q3, lambda: commands.restore_script_in_queue(rec))
    check("restore not applied on read-back: False (record kept, retried)", ok3, False)
    check("…and a WARNING (to the group) naming the queue and the script",
          [lv for lv, m in _warned if "没能把 MAA 的运行日改回去" in m and "早班" in m], [logging.WARNING])
    _warned.clear()
    legacy = {"queue": "早班", "queueId": "queue-0001", "script": "MAA", "scriptId": SID, "position": 1, "day": "2026-10-10"}
    check("a record from the item/delete days: dropped (True) ...",
          with_mas(FakeQueueMas(), lambda: commands.restore_script_in_queue(legacy)), True)
    check("... with a WARNING saying our side adds the item back",
          [lv for lv, m in _warned if "把它加回" in m and "整项删掉" in m], [logging.WARNING])
    _warned.clear()
    q6 = FakeQueueMas()
    q6.order.remove("u2")
    check("the item is gone from the queue: False, with a WARNING",
          (with_mas(q6, lambda: commands.restore_script_in_queue(rec)),
           [lv for lv, m in _warned if "找不到 MAA" in m]), (False, [logging.WARNING]))
    commands.log.removeHandler(_h)

    q2 = FakeQueueMas()
    check("the script is not in the queue at all: None, no raise",
          with_mas(q2, lambda: commands.skip_script_in_queue("早班", "OK-WW")), None)
    check("None leaves the queue untouched", q2.writes, [])

    print("\n[单跑一个脚本：不许因为找不到就去派发整条队列]")
    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands.run_script("MAA"))
    check("找得到就单独派发", (ok, "单独开跑" in msg), (True, True))
    check("派发的是脚本 id、模式 AutoProxy",
          [c[1] for c in f.calls if c[0] == "/api/dispatch/start"],
          [{"taskId": SID, "mode": "AutoProxy"}])
    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands.run_script("终末地"))
    check("找不到脚本就明说，且什么也不派发",
          (ok, [c for c in f.calls if c[0] == "/api/dispatch/start"]), (False, []))

    print("\n[run_now：接口挂了要说人话，不许静默]")
    ok, msg = with_mas(offline_mas, lambda: commands._run_now("早班"))
    check("拿不到队列列表时明确失败", (ok, "取不到队列列表" in msg), (False, True))


    class NoSuchQueueMas(FakeMas):
        def __call__(self, path, body=None, timeout=20):
            if path == "/api/queue/get":
                return {"data": {"q1": {"Info": {"Name": "早班"}}}}
            return super().__call__(path, body, timeout)


    ok, msg = with_mas(NoSuchQueueMas(), lambda: commands._run_now("不存在的班"))
    check("队列名不存在时把现有的列出来（人才知道该按哪个）",
          (ok, "早班" in msg), (False, True))

    print("\n[apply_command 永远不抛：抛出去就没人回报了]")


    def explode(*a, **k):
        raise RuntimeError("底下炸了")


    saved, commands._set_stage = commands._set_stage, explode
    ok, msg = commands.apply_command({"action": "set_stage", "value": "1-7",
                                      "confirmed": True})
    commands._set_stage = saved
    check("底层抛异常也被兜住并回报", (ok, "执行出错" in msg), (False, True))

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_mailbox_close_windows():
    """Mailbox.close() cuts the held stream at once, on macOS and on Windows.

The service stop (SvcStop) calls Mailbox.close() while the listener thread is
blocked reading the ntfy stream. Until 2026-10-07 close() returned only with
the next line the server sent - a keepalive, 45 s apart on ntfy.sh - because
r.close() waits for the read the listener holds; the fix shuts the socket down
first (see Mailbox.close). test_phone_mailbox_e2e.py checks this against a
real ntfy; this file checks the same thing with nothing but the standard
library, so it runs wherever Python runs (the Windows CI job included, the
machine the relay really lives on being Windows).

The server below holds a GET open and writes one ntfy-shaped keepalive line
every KEEPALIVE seconds. KEEPALIVE is well over the 1 s limit, so a close()
that waits for the next line cannot pass by luck.

Basis: "If you want to close the connection in a timely fashion, call
shutdown() before close()." (https://docs.python.org/3/library/socket.html#socket.socket.close)

    Formerly test_mailbox_close_windows.py.
    """
    import json
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.phone import phone
    from ark_relay.features.phone import mailbox as phone_mailbox

    KEEPALIVE = 5.0          # seconds between keepalive lines (ntfy.sh: 45 s)
    LIMIT = 1.0              # close() and the listener's exit must each take less


    stopping = threading.Event()
    held = threading.Event()           # the server has sent the headers and the open line


    class Stream(BaseHTTPRequestHandler):
        """GET /<topic>/json?...: what ntfy sends a subscriber - an open line, then a
    keepalive every KEEPALIVE seconds - until the client goes away."""

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.end_headers()
            try:
                self._line("open")
                held.set()
                while not stopping.wait(KEEPALIVE):
                    self._line("keepalive")
            except OSError:          # the client shut the socket down: done
                return

        def _line(self, event):
            body = {"id": f"k{time.time_ns()}", "time": int(time.time()), "event": event,
                    "topic": self.path.split("/")[1]}
            self.wfile.write((json.dumps(body) + "\n").encode("utf-8"))
            self.wfile.flush()

        def log_message(self, *a):   # no per-request lines on stderr
            pass


    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stream)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # Mailbox reads NTFY from mailbox.py; phone keeps the re-exported name in step.
    phone.NTFY = phone_mailbox.NTFY = f"http://127.0.0.1:{srv.server_address[1]}"

    t0 = time.time()
    try:
        print(f"[a local stream server on {phone.NTFY}, keepalive every {KEEPALIVE:.0f} s]")
        box = phone.Mailbox("close-test", "8964", tmpdir())
        stop = threading.Event()
        listener = threading.Thread(target=box.listen, args=(lambda body: None, stop.is_set),
                                    daemon=True)
        listener.start()
        check("the server holds the stream", held.wait(5), True)
        until = time.time() + 5
        while not box.connected and time.time() < until:
            time.sleep(0.01)
        check("the mailbox says it is connected", box.connected, True)
        time.sleep(0.3)              # the listener is now blocked reading the next line

        # SvcStop: the stop flag first, then close().
        stop.set()
        t = time.time()
        box.close()
        took = time.time() - t
        check(f"Mailbox.close() returned in under {LIMIT:.0f} s (keepalive every {KEEPALIVE:.0f} s)",
              took < LIMIT or round(took, 2), True)
        listener.join(LIMIT)
        check(f"the listener thread ended within {LIMIT:.0f} s after it", listener.is_alive(), False)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        fails.append(type(exc).__name__)
    finally:
        stopping.set()
        srv.shutdown()
        srv.server_close()
        print(f"  ({time.time() - t0:.1f} s)")

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_payload_roundtrip():
    """A held failure survives a relay restart through pending.json. Everything the
alert wording depends on has to survive with it - the relay now restarts itself
for every selfupdate, so this path runs far more often than it used to.

    Formerly test_payload_roundtrip.py.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import RunRecord, SERVER_TZ
    from ark_relay.core.transport import record_to_payload, payload_to_record


    T0 = datetime(2026, 8, 21, 21, 30, tzinfo=SERVER_TZ)
    T1 = datetime(2026, 8, 21, 22, 15, tzinfo=SERVER_TZ)

    def rec(**kw):
        base = dict(run_id="2026-08-21/arknights/21-30-00", script="MAA",
                    user="arknights", started=T0, finished=T1, ok=False,
                    failed_tasks=["协议空间"], raw={"sanity": 6})
        base.update(kw)
        return RunRecord(**base)

    print("[an untrustworthy duration must stay untrustworthy]")
    # The filename is on a UTC+4 clock, so a run with no timestamped log has times
    # that are hours off. duration_known=False is what stops the alert presenting
    # that as fact - and it used to be dropped on the way to disk.
    back = payload_to_record(record_to_payload(rec(duration_known=False)))
    check("duration_known", back.duration_known, False)

    print("\n[a trustworthy one stays trustworthy]")
    check("duration_known", payload_to_record(record_to_payload(rec())).duration_known, True)

    print("\n[payloads written before this field existed]")
    check("defaults to True", payload_to_record({
        "run_id": "z", "script": "MAA", "started": T0.isoformat(),
        "finished": T1.isoformat(), "ok": False}).duration_known, True)

    print("\n[everything else the alert needs]")
    back = payload_to_record(record_to_payload(rec()))
    for field in ("run_id", "script", "user", "started", "finished", "ok",
                  "failed_tasks", "raw"):
        check(field, getattr(back, field), getattr(rec(), field))
    check("duration_min", back.duration_min, 45)
    check("sanity", back.sanity, 6)


def _part_test_windows():
    """Records inside a marked test window stay out of the daily report's rows.

Fixture: the real ledger of 2026-09-14 - the 09:00 queue (rows 0-9, retries
included, running until 11:49) and then my test dispatches from 12:57 (two
killed runs, one gathering-only run with two retries).

    Formerly test_test_windows.py.
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger as core


    FIX = Path(__file__).resolve().parent / "fixtures" / "ledger-2026-09-14" / "ledger.jsonl"
    entries = [json.loads(x) for x in FIX.read_text(encoding="utf-8").splitlines() if x.strip()]
    check("样本 16 条", len(entries), 16)

    print("[真实账本 + 标记的测试窗口：窗口里的六条收起，其余全是正常行]")
    windows = [{"since": "2026-09-14T12:50:00+08:00", "until": "2026-09-14T13:50:00+08:00", "what": "MaaEnd"}]
    queue, tests = core.split_test(entries, windows)
    check("正常 10 条", len(queue), 10)
    check("测试 6 条", [m["run_id"].rsplit("/", 1)[-1] for m in tests],
          ["MaaEnd-08-57-04", "MaaEnd-09-03-54", "MaaEnd-09-06-20", "MaaEnd-09-08-10", "MaaEnd-09-37-59", "MaaEnd-09-43-32"])
    check("队列里的重试照旧是正常行", any(e["run_id"].endswith("MaaEnd-07-20-27") for e in queue), True)

    print("\n[没有标记窗口：手动跑的也是正常行（版本更新后的手动重跑必须进日报）]")
    q2, t2 = core.split_test(entries, [])
    check("全部是正常行", (len(q2), t2), (16, []))
    q3, t3 = core.split_test(entries, [{"since": "bad"}])
    check("坏窗口当没有", (len(q3), t3), (16, []))

    print("\n[窗口没关（until 为空）：从 since 起全算测试——所以测完必须 test-off]")
    q4, t4 = core.split_test(entries, [{"since": "2026-09-14T12:50:00+08:00", "until": None}])
    check("12:50 以后的全收起", len(t4), 6)

    print("\n[日报只列正常的，测试那几趟不成行]")
    title, body = core.format_daily("2026-09-14", queue)
    check("没有 12:57 那趟", "12:58→13:03" in body, False)
    check("早班的终末地还在", "终末地" in body, True)
    t_all, b_all = core.format_daily("2026-09-14", entries)
    check("不标记的话它们本来会出现", "12:58→13:03" in b_all, True)

    print("\n[AUTO-MAS 自己没拉起模拟器的那一秒不成行（10:51 那条）]")
    check("旧记录里 transitional 还是 False", next(e for e in entries if e["run_id"].endswith("06-51-56"))["transitional"], False)
    check("日报里没有「模拟器启动失败」", "模拟器启动失败" in body, False)
    check("也没有那条 10:51 时长未知", "10:51　时长未知" in body, False)
    check("标题不因它算失败", "失败" in title, False)


def _part_web_shell():
    """web/sw.js SHELL holds every file the page needs to open offline (V1 独核 09-23 ④).

Static src / href in index.html (accept.js excepted: it loads only with ?accept), the
manifest's icons, and the tab bar lens family tab-lens.js fetches at run time together
with the map images its lens-filter.svg names and the worker it starts (lens-worker.js).

    Formerly test_web_shell.py.
    """
    import json
    import re

    WEB = Path(__file__).resolve().parents[2] / "web"
    LOCAL = re.compile(r'(?:src|href)\s*=\s*"(?!https?:|//|data:|mailto:|#)([^"?#]+)')


    def shell() -> set[str]:
        js = (WEB / "sw.js").read_text(encoding="utf-8")
        body = re.search(r"const SHELL = \[(.*?)\];", js, re.S).group(1)
        return set(re.findall(r'"([^"]+)"', body))


    def needed() -> set[str]:
        refs = set(LOCAL.findall((WEB / "index.html").read_text(encoding="utf-8")))
        refs.discard("accept.js")
        manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
        refs |= {i["src"].split("?")[0] for i in manifest["icons"]}
        tab = "assets/lens/tab5/"
        refs |= {tab + "lens-filter.svg", tab + "lens-field.json"}
        refs |= set(LOCAL.findall((WEB / tab / "lens-filter.svg").read_text(encoding="utf-8")))
        # the workers tab-lens.js starts (new Worker(new URL("lens-worker.js" + …, its own src))): a sibling of the script
        lens = (WEB / "assets/lens/tab-lens.js").read_text(encoding="utf-8")
        refs |= {"assets/lens/" + w for w in re.findall(r'new Worker\(new URL\("([^"?]+)"', lens)}
        return {r[2:] if r.startswith("./") else r for r in refs}


    check("SHELL covers every file the page opens with", sorted(needed() - shell()), [])
    check("every SHELL entry exists under web/", sorted(f for f in shell() if f != "./" and not (WEB / f).exists()), [])

    print()
    if fails:
        print(f"✗ {len(fails)} failed: {fails}")
        sys.exit(1)
    print(f"all checks passed ({len(shell())} SHELL entries)")


if __name__ == "__main__":
    sys.exit(run_parts([_part_channel_down, _part_cli_commands, _part_cmd_test_channels, _part_command_table, _part_commands_gates, _part_mailbox_close_windows, _part_payload_roundtrip, _part_test_windows, _part_web_shell]))
