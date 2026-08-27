#!/usr/bin/env python3
"""Push a message to the phone from this Mac.

    push.py "标题"                  # 正文从 stdin 读
    push.py "标题" 正文.md
    echo 正文 | push.py "标题"
    push.py --all "标题" 正文.md    # 强制所有渠道都发

**默认只发一个渠道**，按 Server酱 → 企业微信机器人 → 企业微信 的顺序，
第一个成功的就停。这是手动汇报工具，同一份报告同时落到微信和 Server酱
只会让人烦，而不是更可靠（2026-08-24 用户当场提的）。

回退不是可有可无：家宽公网 IP 一转，企业微信就 60020 全拒；Server酱 没有
IP 名单，所以把它排在第一位。只有第一个渠道**报错**才试下一个，所以正常
情况下永远只到一处。

中继（`relay/ark_relay/notify.py`）的行为**不一样，也不该一样**：它发的是
自动告警，一个渠道挂了就得靠别的顶上，那边保持全渠道扇出。

Why this exists: the game machine is powered on roughly three hours a day, and
when it is off there is no way to get a message out - which is exactly when you
most want one.

**This Mac is already in 企业微信's trusted IP list** and sends fine, images
included (verified 2026-08-26, text + `send_image`). Do not assume the game
machine is the only host that can reach 企业微信 - that used to be true and is
not any more. What remains true is that consumer broadband rotates the public
IP, so a 60020 can still show up one day; Server酱 has no IP restriction and is
the reason the fallback chain exists.

Credentials are read from ~/.config/ark/push.env, never from this repository -
the repository is public. Same file format as the relay's .env:

    SERVERCHAN_KEY=...
    # 企业微信 also works from here, but only if this Mac's public IP is in the
    # app's trusted list. Consumer broadband rotates it, so treat it as a bonus
    # channel and never the only one.

Exit code is 0 when at least one channel accepted the message.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "relay"))

ENV_FILE = Path.home() / ".config" / "ark" / "push.env"


def load_env(path: Path) -> None:
    """Same minimal parser the relay uses - no dependency for three variables."""
    if not path.exists():
        sys.exit(f"✗ 找不到凭据文件 {path}\n"
                 f"  建一个，写入 SERVERCHAN_KEY=你的key")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.split("#")[0].strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def main(argv: list[str]) -> int:
    if not argv:
        sys.exit(__doc__)
    send_all = False
    if argv[0] == "--all":
        send_all, argv = True, argv[1:]
    if not argv:
        sys.exit(__doc__)
    title = argv[0]
    if len(argv) > 1 and argv[1] != "-":
        body = Path(argv[1]).read_text(encoding="utf-8")
    elif sys.stdin.isatty():
        body = ""              # title-only push is legitimate
    else:
        body = sys.stdin.read()

    load_env(ENV_FILE)

    from ark_relay.config import Config      # noqa: PLC0415 - after env is loaded
    from ark_relay.notify import Notifier    # noqa: PLC0415

    notifier = Notifier(Config())
    if not notifier.channels:
        sys.exit(f"✗ {ENV_FILE} 里没有任何可用渠道")

    body = body.rstrip()
    if send_all:
        errors = notifier.send(title, body)
        if errors:
            for e in errors:
                print(f"  ✗ {e}", file=sys.stderr)
            return 1
        print(f"✅ 已发出（渠道：{'、'.join(notifier.channels)}）")
        return 0

    # 单渠道 + 回退。顺序见模块开头。
    order = (
        ("Server酱", notifier.serverchan,
         lambda: notifier.serverchan.send_text(title, body)),
        ("企业微信机器人", notifier.wecom_bot,
         lambda: notifier.wecom_bot.send_text(f"{title}\n\n{body}" if body else title)),
        ("企业微信", notifier.wecom,
         lambda: notifier.wecom.send_text(f"{title}\n\n{body}" if body else title)),
    )
    tried: list[str] = []
    for name, channel, call in order:
        if not channel.enabled:
            continue
        try:
            call()
        except Exception as exc:  # noqa: BLE001 - 这就是要回退的那一刻
            tried.append(name)
            print(f"  ✗ {name}: {exc}", file=sys.stderr)
            continue
        note = f"（{'、'.join(tried)} 失败后回退）" if tried else ""
        print(f"✅ 已发出（渠道：{name}）{note}")
        return 0
    print("✗ 所有渠道都失败了", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
