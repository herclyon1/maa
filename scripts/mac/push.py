#!/usr/bin/env python3
"""Push a message to the phone from this Mac.

    push.py "标题"                  # 正文从 stdin 读
    push.py "标题" 正文.md
    echo 正文 | push.py "标题"

Why this exists: the game machine is powered on roughly three hours a day, and
it is the only host whose IP sits in 企业微信's trusted list. When it is off,
there is no way to get a message out - which is exactly when you most want one.
Server酱 has no IP restriction, so this Mac can always reach the phone.

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

    errors = notifier.send(title, body.rstrip())
    if errors:
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1
    print(f"✅ 已发出（可用渠道：{'、'.join(notifier.channels)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
