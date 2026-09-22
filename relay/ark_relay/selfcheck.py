"""Boot self-check: every assumption the relay stands on, verified once per boot.

2026-09-17: the keeper had been unable to read the process table for three
weeks (`wmic` removed by a Windows upgrade) and nobody knew until a queue was
lost. Each of the checks below is something the relay silently assumed that
day or on an earlier incident. They run once, right after AUTO-MAS has been
brought up; a failed check goes to the group at once - the point is to learn
of a broken assumption at boot, not from the shift that did not run.

The same module gives the daily report its 「中继体检」 lines, so the sign-off
check no longer depends on a person running healthcheck.py.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import texts

log = logging.getLogger("ark.selfcheck")

AUTOMAS_TASK = "AUTO-MAS_AutoStart"


@dataclass
class Check:
    name: str      # plain language, shown in the alarm
    ok: bool
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


def run(cfg, *, procs=None, mas_up=None, schedule=None, channels=None,
        run_ok=_run_ok) -> list[Check]:
    """All checks, in the order they are reported. Dependencies are injectable for tests."""
    from . import commands, plan, procs as _procs  # noqa: PLC0415
    procs = procs or _procs.python_processes
    mas_up = mas_up or commands.mas_up
    schedule = schedule or (lambda: plan.schedule(getattr(cfg, "automas_dir", None)))
    out: list[Check] = []

    ok, why = run_ok(["tasklist", "/NH"])
    out.append(Check("看得到机器上在跑哪些程序", ok, why))
    rows = procs()
    out.append(Check("读得到每个程序是怎么启动的（系统自带的那条路）", rows is not None,
                     "" if rows is not None else "读不到——看门狗只能靠调度程序有没有应答来判断，它退出时不会立刻察觉"))
    out.append(Check("调度程序有应答", bool(mas_up()), "开机后中继叫过它一次，仍然没有应答"))
    out.append(Check("调度程序的后台程序在跑", bool(rows) and any("main.py" in c for _, c in rows),
                     "" if rows is None else "在跑的程序里没有它的后台"))
    ok, why = run_ok(["schtasks", "/query", "/tn", AUTOMAS_TASK])
    out.append(Check("调度程序的开机任务计划还在", ok, why))
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
    return out


def report(cfg, notifier, log_=None) -> list[Check]:
    """Run, log every line, push the failures to the group. Returns the checks."""
    lg = log_ or log
    try:
        checks = run(cfg, channels=lambda: list(getattr(notifier, "channels", []) or []))
    except Exception:  # noqa: BLE001 - the self-check itself must not take the boot down
        lg.exception("开机自检自己出错")
        return []
    bad = [c for c in checks if not c.ok]
    for c in checks:
        lg.log(logging.WARNING if not c.ok else logging.INFO, "开机自检 %s %s%s",
               "✗" if not c.ok else "✓", c.name, f"：{c.detail}" if (c.detail and not c.ok) else "")
    if bad:
        notifier.send(texts.SELFCHECK_FAILED, texts.selfcheck_failed_body(
            len(checks), [(c.name, c.detail) for c in bad]), alert=True)
    else:
        lg.info("开机自检 %d 项全部成立", len(checks))
    return checks


# ---------- the daily report's 「中继体检」 lines ----------

_TS = re.compile(r"^(\d\d-\d\d) (\d\d:\d\d):\d\d (\w+)\s+(\S+)\s+(.*)$")


def daily_lines(day: str, log_text: str) -> list[str]:
    """What the sign-off check used to need a person for, from the day's relay.log.

    `day` is YYYY-MM-DD; the log carries MM-DD stamps. ERROR lines are counted
    and the first one quoted (when it reads as plain language); every boot's
    AUTO-MAS start-up is summarised: came up by itself, had to be killed and
    relaunched, or never came up.
    """
    md = day[5:]
    errors: list[tuple[str, str, str]] = []
    boots: list[str] = []
    # A boot where AUTO-MAS answered at once logs none of the four lines
    # below, and was left out of the list: 09-22's report showed only the
    # morning though the relay started again at 21:20:19 and ran the evening
    # queue (relay.log 21367-21392). Each service start opens a boot; one that
    # closes without an outcome line is "already up".
    pending = ""
    for line in log_text.splitlines():
        m = _TS.match(line)
        if not m or m.group(1) != md:
            continue
        hhmm, level, name, msg = m.group(2), m.group(3), m.group(4), m.group(5)
        if level == "ERROR":
            errors.append((hhmm, name, msg))
        if msg.startswith("服务模式启动"):
            if pending:
                boots.append(f"{pending} 开机时已经在")
            pending = hhmm
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
    return out


def daily_section(day: str, log_file: "str | None" = None) -> str:
    """The section appended to the daily report; '' when the log cannot be read."""
    path = log_file or os.environ.get("ARK_LOG_FILE", "")
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")[-2_000_000:]
    except OSError:
        return ""
    return "中继体检\n" + "\n".join(daily_lines(day, text))
