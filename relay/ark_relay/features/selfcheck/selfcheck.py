"""Boot self-check: the conditions the relay depends on, checked once per boot.

The checks run right after AUTO-MAS has been brought up; a failed check is pushed
to the group at once, so a broken condition is known at boot rather than from a
shift that did not run.

The same module gives the daily report its 「中继体检」 lines.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from ark_relay.core import texts

log = logging.getLogger("ark.selfcheck")

AUTOMAS_TASK = "AUTO-MAS_AutoStart"
_is_file = os.path.isfile      # tests replace it: the launcher path is a Windows path


def _launcher_ok(value) -> bool:
    """Game.Path as automas_handover.py step 10b sets it: the Kuro launcher.exe that
    wuwa_launcher found, a file that exists (AUTO-MAS updates WuWa through it)."""
    return (isinstance(value, str) and PureWindowsPath(value).name.lower() == "launcher.exe"
            and _is_file(value))


# The update settings the switch-over handed AUTO-MAS (relay/handover/automas_handover.py
# steps 10a and 10b; the relay's own client updates were removed, da65e68d and a0a7b7f2):
# (script name, setting path, what it does in plain words, holds when).
HANDED_UPDATES = (
    ("MAA", "Run.IfCheckGameUpdate", "明日方舟开跑前查客户端有没有新版", lambda v: v is True),
    ("MAA", "Run.IfAutoInstallGameApk", "明日方舟有新版就自己装上", lambda v: v is True),
    ("OK-WW", "Game.Enabled", "鸣潮由调度程序开关游戏", lambda v: v is True),
    ("OK-WW", "Game.Path", "鸣潮官方启动器的位置", _launcher_ok),
    ("OK-WW", "Game.IfAutoUpdate", "鸣潮开跑前更新客户端", lambda v: v is True),
)
UPDATES_NAME = "调度程序还管着两个游戏客户端的更新（明日方舟、鸣潮）"


def _handed_updates_gaps(scripts: dict) -> list[str]:
    """The HANDED_UPDATES settings that are not as handed over, in plain words; [] when
    all hold. `scripts` is /api/scripts/get's data: {script id: {Info, Run, Game, ...}}."""
    by_name = {str((sc.get("Info") or {}).get("Name") or "").lower(): sc
               for sc in scripts.values() if isinstance(sc, dict)}
    gaps = []
    for script, path, words, holds in HANDED_UPDATES:
        sc = by_name.get(script.lower())
        if sc is None:
            gaps.append(f"{words}：调度程序里没有 {script} 这个脚本")
            continue
        value = sc
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if holds(value):
            continue
        if value is None:
            now = "读不到这一项"
        elif isinstance(value, bool):
            now = "开着" if value else "关着"
        elif path.endswith(".Path"):
            # The path itself is left out: a folder name like 「Wuthering Waves」 is English.
            now = "指的不是官方启动器，或者那个文件已经不在了" if value else "空着"
        else:
            now = f"现在是「{value}」"
        gaps.append(f"{words}：{now}")
    return gaps


def _is_backend(cmd: str) -> bool:
    """True if a python.exe command line is AUTO-MAS's backend: main.py run from under
    the install root's \\automas\\ directory (the host keeper's rule, 083ebcef).

    "main.py" alone also matched OK-WW (`D:\\ark\\okww\\data\\apps\\ok-ww\\working\\main.py`,
    which may run as python.exe): a dead backend then passed this check while OK-WW ran."""
    low = (cmd or "").lower().replace("/", "\\")
    return "main.py" in low and "\\automas\\" in low


@dataclass
class Check:
    name: str      # plain language, shown in the alarm
    ok: "bool | None"   # None: cannot be judged because a check it depends on failed
    detail: str = ""


def _run_ok(cmd: list[str]) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=25)
        return r.returncode == 0, f"退出码 {r.returncode}"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}"


def _writable(d: "Path | None") -> tuple[bool, str]:
    if not d:
        return False, "没配置"
    try:
        Path(d).mkdir(parents=True, exist_ok=True)
        probe = Path(d) / ".selfcheck-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, ""
    except OSError as exc:
        return False, f"{type(exc).__name__}"


def _has_module(name: str) -> bool:
    import importlib.util  # noqa: PLC0415
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# Python packages the relay imports lazily, so a missing one fails only when the
# code that needs it runs: (import name, pip package, what it is used for).
NEEDED_MODULES = (("PIL", "Pillow", "读官方长图（卡池几点几分）、压缩报警截图"),)


def _why(procs_mod) -> str:
    why = procs_mod.last_failure()
    return f"（{why}）" if why else ""


def run(cfg, *, procs=None, mas_up=None, schedule=None, channels=None,
        run_ok=_run_ok, has_module=_has_module) -> list[Check]:
    """All checks, in the order they are reported. Dependencies are injectable for tests."""
    from ark_relay.features.phone import commands  # noqa: PLC0415
    from ark_relay.core import plan, procs as _procs  # noqa: PLC0415
    procs = procs or (lambda: _procs.python_processes(warn=False))
    mas_up = mas_up or commands.mas_up
    schedule = schedule or (lambda: plan.schedule(getattr(cfg, "automas_dir", None)))
    out: list[Check] = []

    ok, why = run_ok(["tasklist", "/NH"])
    out.append(Check("看得到机器上在跑哪些程序", ok, why))
    rows = procs()
    out.append(Check("读得到每个程序是怎么启动的（系统自带的那条路）", rows is not None,
                     "" if rows is not None else f"读不到{_why(_procs)}——看门狗只能靠调度程序有没有应答来判断，它退出时不会立刻察觉；"
                     "调度程序的后台程序在不在跑也就判不了"))
    up = bool(mas_up())
    out.append(Check("调度程序有应答", up, "开机后中继叫过它一次，仍然没有应答"))
    # Without the process table this cannot be judged (None), so an unreadable
    # table is one failure, not two.
    out.append(Check("调度程序的后台程序在跑", None if rows is None else any(_is_backend(c) for _, c in rows),
                     "判不了：程序列表读不到" if rows is None else "在跑的程序里没有它的后台"))
    ok, why = run_ok(["schtasks", "/query", "/tn", AUTOMAS_TASK])
    out.append(Check("调度程序的开机任务计划还在", ok, why))
    # Not answering is the line above's failure: this one cannot be judged then (None).
    if not up:
        out.append(Check(UPDATES_NAME, None, "判不了：调度程序没应答"))
    else:
        try:
            gaps = _handed_updates_gaps(commands._mas("/api/scripts/get")["data"])
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            out.append(Check(UPDATES_NAME, False, f"读不到调度程序的脚本设置（{type(exc).__name__}）"))
        else:
            out.append(Check(UPDATES_NAME, not gaps, "；".join(gaps) + (
                "——这个游戏出新版时没人更新客户端" if gaps else "")))
    try:
        sched = schedule()
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        sched = None
        why = f"{type(exc).__name__}"
    else:
        why = "" if sched else "没有一条开着定时的队列"
    out.append(Check("队列的排期读得到、至少一条开着定时", bool(sched), why))
    log_file = os.environ.get("ARK_LOG_FILE", "")
    ok, why = (False, "没配置") if not log_file else _writable(Path(log_file).parent)
    out.append(Check("日志文件所在目录能写", ok, why))
    ok, why = _writable(getattr(cfg, "state_dir", None))
    out.append(Check("状态目录能写", ok, why))
    hist = getattr(cfg, "history_dir", None)
    out.append(Check("调度程序的历史目录在", bool(hist) and Path(hist).is_dir(),
                     "" if hist else "没配置"))
    chans = channels() if channels else []
    out.append(Check("至少一条通知通道配好了", bool(chans), "一条都没配，报警发不出去"))
    out.append(Check("手机通道配好了", bool(getattr(cfg, "phone_topic", "") and getattr(cfg, "phone_pin", "")),
                     "手机页会一直显示关机"))
    for mod, pkg, used in NEEDED_MODULES:
        out.append(Check(f"中继装了读图组件（{used}）", bool(has_module(mod)),
                         f"没装：用中继那份 python.exe 跑 pip install {pkg}"))
    return out


def report(cfg, notifier, log_=None) -> list[Check]:
    """Run, log every line, push the failures to the group. Returns the checks."""
    lg = log_ or log
    try:
        checks = run(cfg, channels=lambda: list(getattr(notifier, "channels", []) or []))
    except Exception:  # noqa: BLE001 - the self-check itself must not take the boot down
        lg.exception("开机自检自己出错")
        return []
    bad = [c for c in checks if c.ok is False]
    pushed = {}
    if bad:
        errs = notifier.send(texts.SELFCHECK_FAILED, texts.selfcheck_failed_body(
            len(checks), [(c.name, c.detail) for c in bad]), alert=True)
        # The ✗ lines logged below repeat this alarm; when it reached the group,
        # `pushed` marks them as delivered so errwatch does not push them again.
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        pushed = errwatch.group_pushed(texts.SELFCHECK_FAILED, errs, notifier)
    for c in checks:
        mark = "✓" if c.ok else "✗" if c.ok is False else "？"
        lg.log(logging.WARNING if c.ok is False else logging.INFO, "开机自检 %s %s%s",
               mark, c.name, f"：{c.detail}" if (c.detail and not c.ok) else "",
               extra=pushed if c.ok is False else None)
    if not bad and all(c.ok for c in checks):
        lg.info("开机自检 %d 项全部成立", len(checks))
    return checks


# ---------- the daily report's 「中继体检」 lines ----------

_TS = re.compile(r"^(\d\d-\d\d) (\d\d:\d\d):\d\d (\w+)\s+(\S+)\s+(.*)$")
# A start that ends on purpose before the AUTO-MAS step: the self-update restart
# (boot_stages._stage_selfupdate / app_main.SELF_UPDATE_LINE) and a stop that came
# in mid-boot (service.ArkRelayService._stop_in_boot).
_SELF_UPDATE = ("代码已更新，重启以立即生效", "代码已更新，切到新版本文件夹并重启")
_BOOT_STOP = "开机还没走完就收到停止"


def daily_lines(day: str, log_text: str) -> list[str]:
    """What the sign-off check used to need a person for, from the day's relay.log.

    The after-shift check's line for each shift that day (shiftcheck.py) is quoted
    after the two lines below.

    `day` is YYYY-MM-DD; the log carries MM-DD stamps. ERROR lines are counted
    and the first one quoted (when it reads as plain language); every boot's
    AUTO-MAS start-up is summarised: came up by itself, had to be killed and
    relaunched, or never came up.
    """
    md = day[5:]
    errors: list[tuple[str, str, str]] = []
    boots: list[str] = []
    shifts: list[str] = []      # the after-shift check's one line per shift (shiftcheck.py)
    # Each service start opens a boot. A boot where AUTO-MAS answered at once logs
    # none of the four outcome lines below; one that closes without an outcome
    # line is reported as "already up" - when it got that far. The AUTO-MAS step
    # runs before the boot self-check (phone_channel, then _stage_selfcheck), so a
    # start followed by the next start with no 「开机自检」 line in between died
    # before it: 10-10 16:28-16:32 a crash loop of 15 starts, each gone after
    # about 18 s, read as 15 「开机时已经在」 until 2026-10-13.
    pending = ""
    reached = False
    for line in log_text.splitlines():
        m = _TS.match(line)
        if not m or m.group(1) != md:
            continue
        hhmm, level, name, msg = m.group(2), m.group(3), m.group(4), m.group(5)
        if level == "ERROR":
            errors.append((hhmm, name, msg))
        if name == "ark.shiftcheck" and msg.startswith(texts.SHIFTCHECK_HEAD):
            shifts.append(msg)
            continue
        if msg.startswith("服务模式启动"):
            if pending:
                boots.append(f"{pending} " + ("开机时已经在" if reached else "中继刚启动就停了，还没看调度程序在不在"))
            pending = hhmm
            reached = False
            continue
        if msg.startswith("开机自检"):
            reached = True
        # Neither of these reaches the self-check either, but it is no crash:
        # 10-05 21:20, 10-07 08:45 and 21:20, 10-08 20:05 each installed a new
        # version and restarted, and read as a crash until 2026-10-13.
        if pending and not reached and msg.startswith(_SELF_UPDATE):
            boots.append(f"{pending} 装新版后自己重启了")
            pending = ""
            continue
        if pending and not reached and msg.startswith(_BOOT_STOP):
            boots.append(f"{pending} 开机还没走完就被叫停了")
            pending = ""
            continue
        n_before = len(boots)
        # The four outcomes ensure_automas logs (boot_stages.py), matched on
        # the parts of each line that are not engineering words.
        if "自己起来了（等了" in msg:
            boots.append(f"{hhmm} 自己起来了{msg[msg.index('（'):]}")
        elif "杀掉重" in msg:
            boots.append(f"{hhmm} 等不到，杀掉重开")
        elif "秒内" in msg and "仍不通" in msg:
            boots.append(f"{hhmm} 重开后还是没应答")
        elif msg.startswith("AUTO-MAS 已") and msg.endswith("秒）"):
            boots.append(f"{hhmm} 重开后起来了{msg[msg.index('（'):]}")
        if len(boots) > n_before:
            pending = ""
    if pending:
        boots.append(f"{pending} 开机时已经在")
    out = []
    if errors:
        hhmm, name, msg = errors[0]
        part = texts.relay_part(name)
        said = f"{msg[:80]}" if not texts.plain(msg[:80]) else "原话有术语，见中继日志"
        out.append(f"· 中继今天报错 {len(errors)} 条，第一条 {hhmm} 出在「{part}」：{said}")
    else:
        out.append("· 中继今天没有报错")
    out.append("· 调度程序开机：" + ("；".join(boots) if boots else "开机时已经在"))
    out += [f"· {x}" for x in shifts]
    return out


def daily_section(day: str, log_file: "str | None" = None) -> str:
    """The section appended to the daily report; '' when no log is configured.

    An unreadable log still gives the section, saying so (left out, it would read
    as "nothing to say")."""
    path = log_file or os.environ.get("ARK_LOG_FILE", "")
    if not path:
        return ""
    from ark_relay.core.logfile import tail_bytes  # noqa: PLC0415
    try:
        # 8 MB of bytes always holds the last 2 M characters (UTF-8 is at most 4
        # bytes each), and reaches into relay.log.1 after a rotation (logfile.py).
        text = tail_bytes(path, 8_000_000)[0].decode("utf-8", errors="replace")[-2_000_000:]
    except OSError as exc:
        # The report line is plain words; the exception stays in the log.
        log.warning("日报的中继体检读不了 %s：%s: %s", path, type(exc).__name__, exc)
        why = ("文件不在" if isinstance(exc, FileNotFoundError)
               else "被占用或没有权限" if isinstance(exc, PermissionError) else "打不开")
        return f"中继体检\n· 中继日志读不到（{why}）"
    return "中继体检\n" + "\n".join(daily_lines(day, text))
