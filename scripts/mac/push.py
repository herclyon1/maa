#!/usr/bin/env python3
"""Push a message to the phone from this Mac.

    push.py "标题"                    # 正文从 stdin 读 → Server酱
    push.py "标题" 正文.md
    push.py --group "标题" 正文.md    # 企业微信群机器人：只放日报和真报警
    push.py --private "标题" 正文.md  # 企业微信私聊：只发用户本人口述要发的内容
    push.py --decree N "text"         # decree number N: group robot only, N = last one + 1
    push.py --decree --check          # probe the robot key (nothing is posted), print the next N

Three channels, three jobs (the user, 2026-09-14): the group robot carries the
daily report and real alarms and nothing else; Server酱 carries every other
notification that means something; the self-built app's private chat is never
written to on my own initiative. The group falls back to Server酱 when the
robot refuses; nothing ever falls back into the private chat. The relay
(`relay/ark_relay/notify.py`) follows the same split.

`--decree` is the one exception to "the group carries real alarms only" (BOARD
A45 (3), the user 2026-09-23 05:30: when the sessions still disagree at the end
of a meeting the decision is his, 「并且通过群机器人发送，标注总统令第几条」). It
goes to the group robot and nowhere else - no fallback channel, a failure
exits 1 and says why. The numbering is mechanical: every decree that went out is
a line in ~/.config/ark/decrees.jsonl, and the next one must be the last N + 1,
so a decree can be neither skipped nor sent twice by hand.

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

import json
import os
import time
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "relay"))

ENV_FILE = Path.home() / ".config" / "ark" / "push.env"
DECREES = Path.home() / ".config" / "ark" / "decrees.jsonl"


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


def decree(argv: list[str]) -> int:
    """总统令 through the group robot only; see the module docstring."""
    load_env(ENV_FILE)
    from ark_relay.config import Config                # noqa: PLC0415 - after env is loaded
    from ark_relay.notify import WeComBot, _post_json  # noqa: PLC0415
    bot = WeComBot(Config())
    if not bot.enabled:
        print(f"✗ {ENV_FILE} 里没有 WECOM_BOT_URL，总统令发不出去", file=sys.stderr)
        return 1
    sent = ([json.loads(ln) for ln in DECREES.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if DECREES.exists() else [])
    nxt = sent[-1]["n"] + 1 if sent else 1
    if argv[:1] == ["--check"]:
        # An unknown msgtype is refused before anything is posted: 40008 (invalid
        # message type) means the key is live, 93000 (invalid webhook url) means it
        # is not (both measured 2026-09-23 against the real key and a zero key).
        data = _post_json(bot.url, {"msgtype": "nosuchtype"})
        live = data.get("errcode") == 40008
        print(f"{'✅' if live else '✗'} 群机器人钥匙{'有效' if live else '不可用'}"
              f"（errcode {data.get('errcode')}，群里没有收到任何消息）；已发 {len(sent)} 条，下一条是第 {nxt} 条")
        return 0 if live else 1
    if len(argv) < 2 or not argv[0].isdigit():
        sys.exit(__doc__)
    n = int(argv[0])
    text = (sys.stdin.read() if argv[1] == "-" else " ".join(argv[1:])).strip()
    if n != nxt:
        print(f"✗ 下一条应是第 {nxt} 条（已发 {len(sent)} 条，记在 {DECREES}），这里给的是第 {n} 条，没发",
              file=sys.stderr)
        return 1
    if not text:
        sys.exit(__doc__)
    msg = f"总统令第{n}条：{text}"
    try:
        bot.send_text(msg)
    except Exception as exc:  # noqa: BLE001 - reported, never rerouted
        print(f"✗ 群机器人没收：{exc}（没有改走别的渠道）", file=sys.stderr)
        return 1
    with DECREES.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"n": n, "sent": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "text": text},
                           ensure_ascii=False) + "\n")
    print(f"✅ 总统令第{n}条 已发到群（{len(msg.encode())} 字节），记进 {DECREES}")
    return 0


def main(argv: list[str]) -> int:
    # `push.py --help` once went out as a real message titled 「--help」 with
    # body 「.」 (2026-09-11 01:25, the user: 「你把谁关禁闭了，他给我发help呢」).
    # Anything starting with "-" is a flag, never a title.
    if not argv or argv[0] in ("-h", "--help") or (
            argv[0].startswith("-") and argv[0] not in ("--group", "--private", "--decree")):
        sys.exit(__doc__)
    if argv[0] == "--decree":
        return decree(argv[1:])
    # Channels (the user, 2026-09-14): default Server酱 (information); --group is
    # the group robot (daily report / real alarms only); --private is the
    # self-built app's private chat, only for text the user dictated himself.
    mode = "info"
    if argv[0] in ("--group", "--private"):
        mode, argv = argv[0][2:], argv[1:]
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
    joined = f"{title}\n\n{body}" if body else title
    if mode == "private":
        try:
            notifier.wecom.send_text(joined)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ 企业微信私聊: {exc}", file=sys.stderr)
            return 1
        print("✅ 已发到企业微信私聊（用户口述的内容）")
        return 0
    if mode == "group":
        order = (("企业微信机器人", notifier.wecom_bot, lambda: notifier.wecom_bot.send_text(joined)),
                 ("Server酱", notifier.serverchan, lambda: notifier.serverchan.send_text(title, body)))
    else:
        order = (("Server酱", notifier.serverchan, lambda: notifier.serverchan.send_text(title, body)),)
    tried: list[str] = []
    for name, channel, call in order:
        if not channel.enabled:
            # Until 2026-09-23 push.env had no WECOM_BOT_URL, and --group went to
            # the fallback with nothing saying the group had been skipped.
            print(f"  ✗ {name}: {ENV_FILE} 里没配，跳过", file=sys.stderr)
            tried.append(name)
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
