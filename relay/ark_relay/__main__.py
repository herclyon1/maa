"""Entry point.

    python -m ark_relay local     跑在游戏机器上，直接读 history，自己判定自己推送

    python -m ark_relay check     自检：配置、目录、推送渠道
    python -m ark_relay test      发一条测试消息
    python -m ark_relay report    立刻推一次今天的日报

There is no server mode any more. The 7×24 half of the system - "did the
machine ever power on" - is GitHub Actions asking the Tailscale API for the
machine's lastSeen (.github/workflows/watchdog.yml), and queued config changes
already travel through the repo (inbox.py). The game machine cannot reach any
GitHub write endpoint (api.github.com is TCP-blocked from there, measured
2026-08-20), so nothing on it uploads anything; the watchdog reads a signal
that tailscaled emits anyway, just by being connected.
"""
from __future__ import annotations

import argparse
import atexit
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import watch

from .config import SERVER_TZ, Config, both_clocks
from .core import State
from .engine import Engine
from .notify import Notifier
from .transport import LocalSource


def _force_utf8_console() -> None:
    """Make stdout/stderr accept the emoji this program prints everywhere.

    The console on this machine runs the GBK codepage, and every status line
    here carries a ✅ / ❌ / 📋. Printing one raises UnicodeEncodeError, which
    killed `check` and `test` on their final success line - reporting failure
    for work that had in fact succeeded. Logging survives it (handlers swallow
    their own errors) but silently drops the line from the stream, which is
    exactly the wrong thing to lose while debugging.

    The UTF-8 log file is written separately and was never affected.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass  # redirected to something that cannot be reconfigured - fine


def _setup_logging(verbose: bool) -> None:
    """Log to stderr, and to a UTF-8 file when ARK_LOG_FILE is set.

    Python writes the file itself rather than going through a shell redirect:
    PowerShell's `*>>` produces UTF-16 and mixes its own error stream in, which
    left the log unreadable exactly when it was needed for debugging.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if path := os.environ.get("ARK_LOG_FILE"):
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(path, encoding="utf-8"))
        except OSError:
            pass  # a missing log file must not stop the relay
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%m-%d %H:%M:%S",
        handlers=handlers,
    )


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader - avoids a dependency for six variables."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.split("#")[0].strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


# ---------- commands ----------

def cmd_check(cfg: Config) -> int:
    print(f"history 目录  {cfg.history_dir or '(未设置)'}")
    print(f"状态目录      {cfg.state_dir}")
    print(f"兜底扫描      {cfg.poll_seconds} 秒（仅当目录监听挂不上时才用）")
    print(f"日报触发      {cfg.last_run_after} 之后（服务器时间，实际以 AUTO-MAS "
          f"最后一个队列时刻为准）")
    # The switches that decide behaviour, printed together. "Why did no interim
    # report arrive" and "why did it not power off" are both one line each, and
    # answering them by reading .env over SSH is how a wrong guess gets made.
    def _sw(on: bool) -> str:
        return "开" if on else "关"
    print(f"跑完关机      {_sw(cfg.shutdown_after_run)}"
          f"（ARK_SHUTDOWN_AFTER_RUN）")
    print(f"临时查看      {_sw(cfg.interim_report)}"
          f"（ARK_INTERIM_REPORT，白天每轮收尾各一条，不占日报名额）")
    print(f"关机前补发    {_sw(cfg.report_before_shutdown)}"
          f"（ARK_REPORT_BEFORE_SHUTDOWN，临时查看没送出去时的兜底）")
    n = Notifier(cfg)
    print(f"推送渠道      {'、'.join(n.channels) or '(无)'}")
    if cfg.llm_key:
        from . import summary  # noqa: PLC0415
        ok, detail = summary.check(cfg)
        print(f"措辞模型      {'✅' if ok else '✗'} {detail}")
    else:
        print("措辞模型      (未配置，将只发结构化内容——不影响告警和日报)")
    problems = cfg.validate()
    if problems:
        print("\n有问题：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("\n✅ 配置可用")
    return 0


def cmd_test(cfg: Config) -> int:
    from datetime import datetime
    n = Notifier(cfg)
    if not n.channels:
        print("✗ 没有配置任何推送渠道")
        return 1
    now = datetime.now(tz=SERVER_TZ)
    # 自检就是要把每条通道都打一遍，所以这里显式全发。
    errors = n.send("🔧 中继自检",
                    f"这是一条测试消息。\n当前 {both_clocks(now)}", alert=True)
    for e in errors:
        print(f"  ✗ {e}")
    if not errors:
        print(f"✅ 已通过 {'、'.join(n.channels)} 发出")
    return 1 if errors else 0


def _build_local_engine(cfg: Config) -> Engine:
    return Engine(cfg, LocalSource(cfg), State(cfg.state_dir), Notifier(cfg))


def cmd_report(cfg: Config, mark: bool = True) -> int:
    return 0 if _build_local_engine(cfg).send_daily_now(mark=mark) else 1


def _acquire_singleton(cfg: Config) -> object | None:  # noqa: C901
    """Refuse to start twice.

    Two relays watching the same directory means every alert and every daily
    report goes out twice. Restarting via the scheduler is easy to do
    accidentally, so guard it here rather than relying on discipline.
    """
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    lock = cfg.state_dir / "relay.lock"
    try:  # noqa: PLR1702
        # Exclusive create: fails if another instance already holds it.
        fh = lock.open("x")
    except FileExistsError:
        try:
            pid = int(lock.read_text().strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if pid and _pid_alive(pid):
            print(f"✗ 已有中继在运行（pid {pid}），本次不启动", file=sys.stderr)
            return None
        # Stale lock from a machine that was powered off mid-run.
        lock.unlink(missing_ok=True)
        fh = lock.open("x")
    fh.write(str(os.getpid()))
    fh.flush()
    atexit.register(lambda: lock.unlink(missing_ok=True))
    return fh


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        # tasklist prints in the console's ANSI codepage (GBK on this machine),
        # not UTF-8. Decoding it crashed the relay on every boot, so compare
        # raw bytes and never decode at all.
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, timeout=15,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return False  # cannot tell -> treat the lock as stale
        return str(pid).encode("ascii") in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cmd_local(cfg: Config) -> int:
    problems = cfg.validate()
    if problems:
        for p in problems:
            print(f"✗ {p}", file=sys.stderr)
        return 1
    try:
        if _acquire_singleton(cfg) is None:
            return 1
    except Exception:  # noqa: BLE001
        # The lock is a convenience, not a precondition. A relay that refuses
        # to start because its own guard misbehaved is worse than two relays.
        logging.getLogger("ark").exception("单实例锁异常，忽略并继续启动")
    engine = _build_local_engine(cfg)
    log = logging.getLogger("ark")
    log.info("本机模式启动，监视 %s", cfg.history_dir)
    engine.bootstrap()  # never replay pre-existing history as fresh alerts
    log.info("注意：本机模式无法监督「机器没开机」——它自己也在这台机器上")
    # A new game-week means last week's 剿灭 no longer counts. The service
    # path does this at startup; without it here, running local mode across a
    # Monday rollover left Annihilation stuck at Close indefinitely.
    try:
        if msg := engine._annihilation.maybe_reopen():  # noqa: SLF001
            engine.notifier.send("🗓️ 剿灭", msg)
    except Exception:  # noqa: BLE001
        log.exception("剿灭周期检查出错，跳过")
    # Deployed Windows machines run service.py, where new records arrive as
    # directory-change events through pywin32. This mode gets the same shape
    # from watch.py (ctypes / kqueue, zero dependencies): a record landing on
    # disk wakes the loop at once, and the clock-based work still sleeps to
    # its exact moment. Only when no watcher can be started does record
    # pickup fall back to the scan interval.
    wake = threading.Event()
    watching = watch.start(cfg.history_dir, wake)
    log.info("已挂上目录变更通知，记录一落盘立即处理" if watching
             else f"本平台没有目录监听，退回 {cfg.poll_seconds} 秒兜底扫描")
    backstop = 3600.0 if watching else float(cfg.poll_seconds)
    while True:
        try:
            engine.tick()
        except KeyboardInterrupt:
            log.info("退出")
            return 0
        except Exception:  # noqa: BLE001 - the loop must survive anything
            log.exception("本轮处理出错，继续")
        try:
            if wake.wait(timeout=_sleep_until_alarm(engine, backstop)):
                wake.clear()
                time.sleep(2)  # AUTO-MAS writes the .json and .log separately
        except KeyboardInterrupt:
            log.info("退出")
            return 0


def _sleep_until_alarm(engine, cap: float) -> float:
    """Seconds until the engine's next clock moment, bounded by the backstop."""
    from .config import SERVER_TZ  # noqa: PLC0415
    from datetime import datetime  # noqa: PLC0415
    try:
        if alarm := engine.next_deadline():
            due, _why = alarm
            return max(1.0, min((due - datetime.now(tz=SERVER_TZ)).total_seconds() + 1, cap))
    except Exception:  # noqa: BLE001 - a broken alarm degrades into lateness
        logging.getLogger("ark").exception("计算下一个时刻出错，退回备用间隔")
    return cap


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ark_relay", description="MAA 通知中继")
    p.add_argument("command", choices=["local", "check", "test", "report"])
    p.add_argument("--env", type=Path, default=Path(".env"), help="配置文件（默认 ./.env）")
    p.add_argument("--again", action="store_true",
                   help="report 模式：只看一眼当天进度，不占用当天的日报名额")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    _force_utf8_console()   # before anything prints or logs
    _setup_logging(args.verbose)
    _load_dotenv(args.env)

    cfg = Config()

    if args.command == "check":
        return cmd_check(cfg)
    if args.command == "test":
        return cmd_test(cfg)
    if args.command == "report":
        return cmd_report(cfg, mark=not args.again)
    return cmd_local(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
