"""Boot self-check: every broken assumption is named and pushed to the group at
once; the daily report gets the two relay lines a person used to run by hand.

2026-09-17: the process table had been unreadable for three weeks (wmic gone)
and the relay found out from a lost queue. The self-check exists so a boot
tells on itself instead.
"""
import copy
import json
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.selfcheck import selfcheck
from ark_relay.core import texts
from ark_relay.core.notify import route_of
from ark_relay.features.phone import commands

fails = []

# The machine's AUTO-MAS as /api/scripts/get answers it: the script ids and names of
# fixtures/automas-config-2026-10-11 (the machine's own config), with the update
# settings the switch-over handed it (relay/handover/automas_handover.py): 10a read back
# True in switch.log 10-11 10:04:30; 10b set and read back 10-12 (commit a0a7b7f2:
# Game.Enabled true, Game.Path D:\Wuthering Waves\launcher.exe; Game.IfAutoUpdate is
# AUTO-MAS's default true, fixtures/automas-models/config.py.txt OkwwConfig).
_CFG = json.loads((Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11" / "config"
                   / "ScriptConfig.json").read_text(encoding="utf-8"))
MACHINE_SCRIPTS = {sid: {"Info": dict(sc["Info"])} for sid, sc in _CFG.items() if sid != "instances"}
for _sc in MACHINE_SCRIPTS.values():
    if _sc["Info"]["Name"] == "MAA":
        _sc["Run"] = {"IfCheckGameUpdate": True, "IfAutoInstallGameApk": True, "HardTimeLimit": 120}
    if _sc["Info"]["Name"] == "OK-WW":
        _sc["Game"] = {"Enabled": True, "Type": "Client", "Path": "D:\\Wuthering Waves\\launcher.exe",
                       "IfAutoUpdate": True}
mas_scripts = {"data": MACHINE_SCRIPTS}


def _fake_mas(path, body=None, timeout=20):
    if path != "/api/scripts/get":
        raise AssertionError(f"endpoint not prepared by this test: {path}")
    if isinstance(mas_scripts, Exception):
        raise mas_scripts
    return {"code": 200, **mas_scripts}


commands._mas = _fake_mas
launchers = {"D:\\Wuthering Waves\\launcher.exe"}      # the files that exist on the fake machine
selfcheck._is_file = lambda p: p in launchers


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class _Notifier:
    channels = ["企业微信机器人"]

    def __init__(self):
        self.sent = []

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body, alert))
        return []


with tempfile.TemporaryDirectory() as td:
    import os
    os.environ["ARK_LOG_FILE"] = str(Path(td) / "log" / "relay.log")
    cfg = types.SimpleNamespace(automas_dir=td, state_dir=Path(td) / "state", history_dir=td,
                                phone_topic="ark-x", phone_pin="1234")
    good = dict(procs=lambda: [(1, r"D:\ark\automas\repo\main.py")], mas_up=lambda: True,
                schedule=lambda: [{"name": "早班", "times": ["09:00"]}], channels=lambda: ["群"],
                run_ok=lambda cmd: (True, ""), has_module=lambda m: True)

    print("[一切正常：全部成立、不报警]")
    cs = selfcheck.run(cfg, **good)
    check("13 项", len(cs), 13)
    check("全部成立", [c.name for c in cs if not c.ok], [])
    check("每一项的名字都是人话", [texts.plain(c.name) for c in cs if texts.plain(c.name)], [])

    print("\n[09-17 那种机器：进程表读不到、调度程序没应答、任务计划没了]")
    bad = dict(good, procs=lambda: None, mas_up=lambda: False,
               run_ok=lambda cmd: (False, "退出码 1") if cmd[0] == "schtasks" else (True, ""))
    cs = selfcheck.run(cfg, **bad)
    names = [c.name for c in cs if c.ok is False]
    check("点名进程表", any("怎么启动" in n for n in names))
    check("点名调度程序没应答", "调度程序有应答" in names)
    check("点名任务计划", "调度程序的开机任务计划还在" in names)
    check("别的项照常成立", len(names), 3)
    # 2026-10-10 16:14:07: one unreadable process table showed as two failures.
    dep = [c for c in cs if c.name == "调度程序的后台程序在跑"][0]
    check("后台程序那项判不了，不算不成立", dep.ok, None)
    check("进程表那项说明后台程序判不了", any("判不了" in c.detail for c in cs if c.ok is False))
    rows_ok = [(1, "python.exe other.py")]
    cs = selfcheck.run(cfg, **dict(good, procs=lambda: rows_ok))
    check("读得到进程表、后台不在才算不成立", [c.name for c in cs if c.ok is False], ["调度程序的后台程序在跑"])
    # OK-WW's script is a main.py too (preupdate_okww.py); it is not the AUTO-MAS backend.
    okww = [(7, r"D:\ark\okww\data\apps\ok-ww\python\python.exe D:\ark\okww\data\apps\ok-ww\working\main.py -t 2 -e")]
    cs = selfcheck.run(cfg, **dict(good, procs=lambda: okww))
    check("OK-WW's main.py is not taken for the backend", [c.name for c in cs if c.ok is False], ["调度程序的后台程序在跑"])
    machine = [(5088, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py")]  # test_procs_wmi.py
    cs = selfcheck.run(cfg, **dict(good, procs=lambda: machine))
    check("the machine's backend line (10-10) still counts", [c.name for c in cs if c.ok is False], [])
    cs = selfcheck.run(cfg, **dict(good, procs=lambda: [(9, "d:/ARK/AutoMAS/repo/MAIN.PY")]))
    check("/ and case do not matter", [c.name for c in cs if c.ok is False], [])

    print("\n[10-01..10-05 那种机器：没装 Pillow，读长图每次都 ModuleNotFoundError]")
    cs = selfcheck.run(cfg, **dict(good, has_module=lambda m: m != "PIL"))
    miss = [c for c in cs if not c.ok]
    check("只点名读图组件", [c.name for c in miss], ["中继装了读图组件（读官方长图（卡池几点几分）、压缩报警截图）"])
    check("说怎么补", miss and "pip install Pillow" in miss[0].detail)
    check("真查：本机查得到标准库、查不到不存在的包",
          (selfcheck._has_module("json"), selfcheck._has_module("no_such_pkg_ark")), (True, False))

    print("\n[AUTO-MAS 还管着两个游戏客户端的更新（交接 10a、10b）：被改掉了就点名]")
    # s26 audit 2026-10-13: the handover runs once; an AUTO-MAS upgrade or a click in its
    # window could turn these off again and nobody would update the client.
    UPD = "调度程序还管着两个游戏客户端的更新（明日方舟、鸣潮）"
    cs = selfcheck.run(cfg, **good)
    check("the machine's values: the line holds", [(c.name, c.ok) for c in cs if c.name == UPD], [(UPD, True)])
    for script, field, value in (("MAA", ("Run", "IfCheckGameUpdate"), False),
                                 ("MAA", ("Run", "IfAutoInstallGameApk"), False),
                                 ("OK-WW", ("Game", "Enabled"), False),
                                 ("OK-WW", ("Game", "IfAutoUpdate"), False),
                                 ("OK-WW", ("Game", "Path"), ""),
                                 ("OK-WW", ("Game", "Path"), "D:\\Wuthering Waves Game\\Wuthering Waves.exe"),
                                 ("OK-WW", ("Game", "Path"), "D:\\Gone\\launcher.exe")):
        changed = copy.deepcopy(MACHINE_SCRIPTS)
        sc = next(v for v in changed.values() if v["Info"]["Name"] == script)
        sc[field[0]][field[1]] = value
        mas_scripts = {"data": changed}
        cs = selfcheck.run(cfg, **good)
        bad_lines = [c for c in cs if c.ok is False]
        check(f"{script} {'.'.join(field)} = {value!r}: only this line fails",
              [c.name for c in bad_lines], [UPD])
        check(f"{script} {'.'.join(field)} = {value!r}: the detail is plain words",
              [texts.plain(c.detail) for c in bad_lines if texts.plain(c.detail)], [])
    changed = copy.deepcopy(MACHINE_SCRIPTS)
    del next(v for v in changed.values() if v["Info"]["Name"] == "OK-WW")["Game"]["IfAutoUpdate"]
    mas_scripts = {"data": changed}
    cs = selfcheck.run(cfg, **good)
    check("a setting missing from the answer fails too", [c.name for c in cs if c.ok is False], [UPD])
    mas_scripts = {"data": {k: v for k, v in MACHINE_SCRIPTS.items() if v["Info"]["Name"] != "OK-WW"}}
    cs = selfcheck.run(cfg, **good)
    check("no OK-WW script: fails", [c.name for c in cs if c.ok is False], [UPD])
    mas_scripts = ConnectionRefusedError(61, "Connection refused")
    cs = selfcheck.run(cfg, **dict(good, mas_up=lambda: False))
    check("AUTO-MAS not answering: one failure (its own line), this one cannot be judged",
          ([c.name for c in cs if c.ok is False], [c.ok for c in cs if c.name == UPD]), (["调度程序有应答"], [None]))
    mas_scripts = TimeoutError("timed out")
    cs = selfcheck.run(cfg, **good)
    check("answers the probe but not this read: fails", [c.name for c in cs if c.ok is False], [UPD])
    mas_scripts = {"data": MACHINE_SCRIPTS}

    print("\n[report：不成立就群报一条，全成立不报]")
    import logging
    from ark_relay.features.alarm import errwatch

    class _Rec(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)
    rec = _Rec()
    selfcheck.log.addHandler(rec)
    selfcheck.log.setLevel(logging.INFO)
    n = _Notifier()
    selfcheck.run = (lambda _run: lambda cfg, **kw: _run(cfg, **dict(bad, channels=kw.get("channels"))))(selfcheck.run)
    selfcheck.report(cfg, n)
    check("报了一条", len(n.sent), 1)
    check("标题", n.sent and n.sent[0][0] == texts.SELFCHECK_FAILED)
    check("是报警", n.sent and n.sent[0][2] is True)
    check("正文列出不成立的项", n.sent and "任务计划" in n.sent[0][1] and "3 项不成立" in n.sent[0][1])
    check("正文是人话", n.sent and texts.plain(n.sent[0][1]), [])
    check("走群", route_of(texts.SELFCHECK_FAILED, alert=True), "group")
    # Each ✗ line repeats that one alarm: errwatch must not push it again.
    crosses = [r for r in rec.records if "✗" in r.getMessage()]
    check("✗ 行有 3 条", len(crosses), 3)
    check("✗ 行都标了「已进群」，不再单独推", all(getattr(r, errwatch.PUSHED, False) for r in crosses))
    check("判不了那项记成 ？、不是警告",
          [(r.levelno, "？" in r.getMessage()) for r in rec.records if "后台程序在跑" in r.getMessage()],
          [(logging.INFO, True)])
    n2 = _Notifier()
    n2.send = lambda *a, **k: ["企业微信机器人：超时"]
    rec.records.clear()
    selfcheck.report(cfg, n2)
    check("没发出去就不标，照常由报错转发推",
          [getattr(r, errwatch.PUSHED, False) for r in rec.records if "✗" in r.getMessage()], [False] * 3)

print("\n[进程表读取：没有系统 WMI 的机器上返回「读不到」，不假装活着]")
from ark_relay.core import procs  # noqa: E402
check("这台没有 pywin32 的 Mac 上返回 None", procs.python_processes(), None)

print("\n[日报两行：从当天 relay.log 来]")
log = """09-17 08:45:28 WARNING ark.service  AUTO-MAS 接口不在，拉起它
09-17 08:46:46 INFO    ark.service  AUTO-MAS 已拉起（24 秒）
09-17 10:48:40 ERROR   ark.service  进程启动事件监听中断，改用 120 秒活性检查，5 秒后重订阅
09-17 21:20:39 WARNING ark.service  AUTO-MAS 接口不在，拉起它
09-17 21:21:28 ERROR   ark.service  AUTO-MAS 拉起后 45 秒内接口仍不通
09-16 21:21:00 ERROR   ark.service  昨天的，不算
09-18 08:45:50 INFO    ark.service  AUTO-MAS 自己起来了（等了 21 秒）
"""
lines = selfcheck.daily_lines("2026-09-17", log)
check("两行", len(lines), 2)
check("错误计数 2、第一条 10:48、出在主程序", "报错 2 条" in lines[0] and "10:48" in lines[0] and "主程序" in lines[0])
check("原话有术语就不照抄", "留在" in lines[0] or "见中继日志" in lines[0])
check("开机两次：重开后起来了 24 秒；重开后还是没应答", "24 秒" in lines[1] and "还是没应答" in lines[1])
lines2 = selfcheck.daily_lines("2026-09-18", log)
check("没报错就说没报错", lines2[0], "· 中继今天没有报错")
check("自己起来了 21 秒", "自己起来了（等了 21 秒）" in lines2[1])
check("两行都是人话", [texts.plain(x) for x in lines + lines2 if texts.plain(x)], [])
# relay.log unreadable: the section says so instead of vanishing (audit row selfcheck.py:207).
missing = selfcheck.daily_section("2026-09-18", "/nonexistent/relay.log")
check("missing log -> the section says it is missing", missing, "中继体检\n· 中继日志读不到（文件不在）")
import unittest.mock as _mock  # noqa: E402
with _mock.patch("ark_relay.core.logfile.tail_bytes", side_effect=PermissionError(13, "locked")):
    check("locked log -> the section says it cannot be opened",
          selfcheck.daily_section("2026-09-18", "/locked/relay.log"),
          "中继体检\n· 中继日志读不到（被占用或没有权限）")
check("the unreadable line is plain words", texts.plain(missing), [])

print("\n[a start that died before the self-check is not 「开机时已经在」 (real 10-10 16:28-17:22)]")
# relay.log 10-10 16:28-16:32: 15 starts about 18 s apart, none reaching the boot
# self-check (the AUTO-MAS step runs before it), then boots that did reach it.
crash = (Path(__file__).resolve().parent / "fixtures" / "relay-1010-crashloop-boots.log").read_text(encoding="utf-8")
boots = selfcheck.daily_lines("2026-10-10", crash)[1].removeprefix("· 调度程序开机：").split("；")
check("22 starts", len(boots), 22)
check("the 15 crash-loop starts read as stopped before the AUTO-MAS step",
      [b for b in boots[:15] if not b.endswith("中继刚启动就停了，还没看调度程序在不在")], [])
check("16:32:46, 16:33, 16:59:30, 17:02:25 and 17:21 reached the self-check: already up",
      [b for b in boots if b.endswith("开机时已经在")],
      ["16:32 开机时已经在", "16:33 开机时已经在", "16:59 开机时已经在", "17:02 开机时已经在", "17:21 开机时已经在"])
check("the line is plain words", texts.plain("；".join(boots)), [])

print("\n[a self-update restart is not a crash (real 10-05 21:20, 10-07 08:45 / 21:20, 10-08 20:05)]")
# Each of these starts fetched a new version and restarted before the boot
# self-check; the restarted start that follows reached it.
upd = (Path(__file__).resolve().parent / "fixtures" / "relay-selfupdate-restart-boots.log").read_text(encoding="utf-8")
got = {d: selfcheck.daily_lines(d, upd)[1] for d in ("2026-10-05", "2026-10-07", "2026-10-08")}
check("10-05", got["2026-10-05"], "· 调度程序开机：21:20 装新版后自己重启了；21:20 开机时已经在")
check("10-07", got["2026-10-07"], "· 调度程序开机：08:45 装新版后自己重启了；08:45 自己起来了（等了 19 秒）；"
      "21:20 装新版后自己重启了；21:20 自己起来了（等了 13 秒）")
check("10-08", got["2026-10-08"], "· 调度程序开机：20:05 装新版后自己重启了；20:06 自己起来了（等了 3 秒）")
check("the 10-10 crash loop still reads as a crash",
      [b for b in boots[:15] if not b.endswith("中继刚启动就停了，还没看调度程序在不在")], [])
# A stop mid-boot (service._stop_in_boot) - not in the real log yet; the line is the one service.py writes.
stop = ("10-10 22:30:11 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）\n"
        "10-10 22:30:12 INFO    ark.service  开机还没走完就收到停止，后面几步不做了，直接退出\n")
check("a stop mid-boot", selfcheck.daily_lines("2026-10-10", stop)[1], "· 调度程序开机：22:30 开机还没走完就被叫停了")
check("the new words are plain", texts.plain("；".join(got.values()) + "开机还没走完就被叫停了"), [])

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("all checks passed")
