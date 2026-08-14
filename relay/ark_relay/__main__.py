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
import logging
import os
import sys
import time
from pathlib import Path

from .config import SERVER_TZ, Config, both_clocks
from .core import State
from .engine import Engine
from .notify import Notifier
from .transport import LocalSource, Uploader


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%m-%d %H:%M:%S",
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
    print(f"措辞模型      {cfg.model if cfg.anthropic_key else '(未配置，将只发结构化内容)'}")
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


def cmd_report(cfg: Config) -> int:
    return 0 if _build_local_engine(cfg).send_daily_now() else 1


def cmd_local(cfg: Config) -> int:
    problems = cfg.validate()
    if problems:
        for p in problems:
            print(f"✗ {p}", file=sys.stderr)
        return 1
    engine = _build_local_engine(cfg)
    log = logging.getLogger("ark")
    log.info("本机模式启动，监视 %s（每 %d 秒）", cfg.history_dir, cfg.poll_seconds)
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
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    _setup_logging(args.verbose)
    _load_dotenv(args.env)

    cfg = Config()
    cfg.mode = "server" if args.command == "server" else "local"

    if args.command == "check":
        return cmd_check(cfg)
    if args.command == "test":
        return cmd_test(cfg)
    if args.command == "report":
        return cmd_report(cfg)
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
