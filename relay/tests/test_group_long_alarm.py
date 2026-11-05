"""One alarm must never flood the group (2026-11-05 北京 10:56).

runwatch's overrun alarm took runtime-snapshot's task `log` as 「AUTO-MAS 最后一句」, but that field
is the task's whole log (38151 characters in 343 lines that morning). WeComBot split the text into
44 messages and sent 20 before the robot's 20-a-minute cap refused the 21st (45009); the user saw
20 pieces of log in the group, and every other alarm of that minute failed.

Checked here: runwatch.last_log_line keeps only the last non-empty line, cut to 200 characters;
the overrun text built from such a log stays one message; WeComBot sends at most MAX_PARTS
messages for any text (many lines or one huge line), the last ending with a plain note, and
leaves short and two-part texts exactly as before.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import notify, texts  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.run import runwatch  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


# A task log shaped like the 11-05 one: 343 lines, about 38000 characters, mostly Chinese.
LOG = "\n".join(f"[2026-11-05 11:{i // 60:02d}:{i % 60:02d}.212] 正在识别画面并点击开始唤醒按钮第 {i} 次，等待游戏响应中……" * 2
                for i in range(343)) + "\n[2026-11-05 11:26:30.212] 正在连接窗口... Endfield\n\n"

print("[runwatch.last_log_line]")
check("the last non-empty line", runwatch.last_log_line(LOG), "[2026-11-05 11:26:30.212] 正在连接窗口... Endfield")
check("nothing: empty", runwatch.last_log_line(None), "")
long_line = "x" * 500
check("a long last line is cut to 200", len(runwatch.last_log_line("a\n" + long_line)), 200)

print("[the overrun alarm text]")
due, now = datetime(2026, 11, 5, 9, 0, tzinfo=SERVER_TZ), datetime(2026, 11, 5, 10, 57, tzinfo=SERVER_TZ)
body = texts.shift_overrun_body("早班", due, now, 87, 30, "MAA 完成、MaaEnd 运行", runwatch.last_log_line(LOG), 7)
check("built from the whole log it is still one robot message", len(notify.WeCom._split(body, notify.WeComBot._LIMIT)), 1)
check("it quotes the last line", "AUTO-MAS 最后一句：[2026-11-05 11:26:30.212] 正在连接窗口... Endfield" in body, True)

print("[WeComBot: at most MAX_PARTS messages]")
posts = []
notify._post_json = lambda url, payload: posts.append(payload["text"]["content"]) or {"errcode": 0}
bot = notify.WeComBot.__new__(notify.WeComBot)
bot.url = "https://fake.test/robot"
huge = "⏰ 早班还没跑完\n早班 09:00 开跑……\nAUTO-MAS 最后一句：" + LOG
check("the 11-05 text would have been many messages", len(notify.WeCom._split(huge, notify.WeComBot._LIMIT)) > 20, True)
bot.send_text(huge)
check("now at most MAX_PARTS messages", len(posts) <= notify.WeComBot.MAX_PARTS, True)
check("the first message starts with the title", posts[0].split("\n", 1)[1].startswith("⏰ 早班还没跑完"), True)
check("the last message ends with the plain note", posts[-1].endswith("（后面还有很长一段没发，免得刷屏）"), True)
check("every message within the robot's 2048 bytes", all(len(p.encode("utf-8")) <= 2048 for p in posts), True)
check("numbering says the real count", posts[-1].startswith(f"（{len(posts)}/{len(posts)}）"), True)
posts.clear()
bot.send_text("一" * 20000)
check("one huge line without breaks: also at most MAX_PARTS", len(posts) <= notify.WeComBot.MAX_PARTS, True)
posts.clear()
bot.send_text("短消息")
check("a short text: one message, unchanged", posts, ["短消息"])
posts.clear()
two = "甲" * 500 + "\n" + "乙" * 500
bot.send_text(two)
check("a two-part text: two messages as before, no note", (len(posts), any("免得刷屏" in p for p in posts)), (2, False))

print("all checks passed" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
