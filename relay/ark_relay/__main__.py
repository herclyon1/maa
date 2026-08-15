"""Entry point.

    python -m ark_relay local     跑在游戏机器上，直接读 history，自己判定自己推送
    python -m ark_relay agent     跑在游戏机器上（服务器模式）：上报事件 + 发心跳
    python -m ark_relay server    跑在云服务器上：收事件、判定、推送、心跳超时告警

    python -m ark_relay check     自检：配置、目录、推送渠道
    python -m ark_relay test      发一条测试消息
    python -m ark_relay report    立刻推一次今天的日报
"""
from __future__ import annotations

import argparse
import atexit
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from .config import SERVER_TZ, Config, both_clocks
from .core import State
from .engine import Engine
from .notify import Notifier
from .transport import LocalSource, Uploader


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
    print(f"模式          {cfg.mode}")
    print(f"history 目录  {cfg.history_dir or '(未设置)'}")
    print(f"状态目录      {cfg.state_dir}")
    print(f"轮询间隔      {cfg.poll_seconds} 秒")
    print(f"日报触发      {cfg.last_run_after} 之后（服务器时间）")
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
    errors = n.send("🔧 中继自检", f"这是一条测试消息。\n当前 {both_clocks(now)}")
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
    log.info("本机模式启动，监视 %s（每 %d 秒）", cfg.history_dir, cfg.poll_seconds)
    engine.bootstrap()  # never replay pre-existing history as fresh alerts
    log.info("注意：本机模式无法监督「机器没开机」——它自己也在这台机器上")
    while True:
        try:
            engine.tick()
        except KeyboardInterrupt:
            log.info("退出")
            return 0
        except Exception:  # noqa: BLE001 - the loop must survive anything
            log.exception("本轮处理出错，继续")
        time.sleep(cfg.poll_seconds)


def cmd_agent(cfg: Config, base_url: str, token: str) -> int:
    """Server mode, machine side: ship events and heartbeats, apply commands."""
    if not cfg.history_dir:
        print("✗ ARK_HISTORY_DIR 未设置", file=sys.stderr)
        return 1
    log = logging.getLogger("ark.agent")
    up = Uploader(base_url, token)
    state = State(cfg.state_dir / "agent")
    source = LocalSource(cfg)
    log.info("采集端启动 → %s（每 %d 秒）", base_url, cfg.poll_seconds)
    while True:
        try:
            up.heartbeat()
            for rec in source.fetch(state.seen):
                # Only mark it done once the relay has acknowledged it; the
                # machine is awake ~3h/day and must re-send after a reboot.
                if up.send_event(rec):
                    state.mark_seen(rec.run_id)
                    log.info("已上报 %s", rec.run_id)
                else:
                    log.warning("上报失败，下轮重试: %s", rec.run_id)
            for cmd in up.pull_commands():
                from .commands import apply_command  # local import: optional feature
                ok, detail = apply_command(cmd)
                up.report_command(str(cmd.get("id", "")), ok, detail)
                log.info("指令 %s -> %s %s", cmd.get("action"), ok, detail)
        except KeyboardInterrupt:
            return 0
        except Exception:  # noqa: BLE001
            log.exception("采集端本轮出错，继续")
        time.sleep(cfg.poll_seconds)


def cmd_server(cfg: Config, host: str, port: int) -> int:
    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:
        print("✗ 服务器模式需要: pip install fastapi uvicorn", file=sys.stderr)
        return 1
    from .server import build_app  # noqa: PLC0415
    uvicorn.run(build_app(cfg), host=host, port=port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ark_relay", description="MAA 通知中继")
    p.add_argument("command",
                   choices=["local", "agent", "server", "check", "test", "report"])
    p.add_argument("--env", type=Path, default=Path(".env"), help="配置文件（默认 ./.env）")
    p.add_argument("--url", default=os.environ.get("ARK_RELAY_URL", ""),
                   help="agent 模式：中继地址，如 http://100.x.x.x:8787")
    p.add_argument("--token", default=os.environ.get("ARK_TOKEN", ""))
    p.add_argument("--host", default="0.0.0.0")  # noqa: S104 - bound inside the tailnet
    p.add_argument("--port", type=int, default=int(os.environ.get("ARK_PORT", "8787")))
    p.add_argument("--again", action="store_true",
                   help="report 模式：只看一眼当天进度，不占用当天的日报名额")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    _force_utf8_console()   # before anything prints or logs
    _setup_logging(args.verbose)
    _load_dotenv(args.env)

    cfg = Config()
    cfg.mode = "server" if args.command == "server" else "local"

    if args.command == "check":
        return cmd_check(cfg)
    if args.command == "test":
        return cmd_test(cfg)
    if args.command == "report":
        return cmd_report(cfg, mark=not args.again)
    if args.command == "local":
        return cmd_local(cfg)
    if args.command == "agent":
        if not args.url:
            print("✗ agent 模式需要 --url 或 ARK_RELAY_URL", file=sys.stderr)
            return 1
        return cmd_agent(cfg, args.url, args.token)
    return cmd_server(cfg, args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
