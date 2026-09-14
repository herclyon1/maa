"""日常消息只发一个渠道，报警才全发。

2026-08-24 用户的原话："中继也不要同时发两边通知，只允许在一侧不通的时候采用
另一侧……除了报警之外（报警的时候用双通道全发），其他时候都默认走一个通知。"

同一份日报落到微信和 Server酱 两处只是烦，不会更可靠；冗余的价值在报警。把两者
混为一谈的代价是真告警被日常噪声淹掉。

Server酱 排在第一位不是随手定的：它没有 IP 白名单，用户实测"长期稳定，从来没出过
问题"；企业微信在家宽后面，公网 IP 一转就 60020 全拒。
"""
import os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP),
                  SERVERCHAN_KEY="", WECOM_CORPID="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.config import Config      # noqa: E402
from ark_relay.notify import Notifier    # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


class Fake:
    """一个够用的假通道：记下被调用过、可以被设成必然失败。"""
    def __init__(self, log, name, broken=False):
        self.log, self.name, self.broken = log, name, broken
        self.enabled = True
    def send_text(self, *a):
        # 企业微信收的是 "标题\n\n正文" 拼好的一串，Server酱 收的是分开的两段。
        # 只记标题那一段，调用方才好按标题筛。
        self.log.append((self.name, a[0].split("\n")[0]))
        if self.broken:
            raise RuntimeError(f"{self.name} 挂了")


def build(broken=()):
    log = []
    n = Notifier(Config())
    n.serverchan = Fake(log, "Server酱", "Server酱" in broken)
    n.wecom_bot = Fake(log, "企业微信机器人", "企业微信机器人" in broken)
    n.wecom = Fake(log, "企业微信", "企业微信" in broken)
    return n, log


print("[三个通道各司其职：日报和真报警进群，其余走 Server酱，私聊永远不自动发]")
n, log = build()
check("日报发出去了", n.send("📋 日报", "正文", daily=True), [])
check("日报只进群机器人", [c for c, _ in log], ["企业微信机器人"])
n, log = build()
check("报警发出去了", n.send("⚠️ 出错了", "正文", alert=True), [])
check("报警只进群机器人", [c for c, _ in log], ["企业微信机器人"])
n, log = build()
check("其余通知发出去了", n.send("🔄 中继已更新", "正文"), [])
check("其余通知只走 Server酱", [c for c, _ in log], ["Server酱"])

print("\n[群机器人挂了：日报/报警回退到 Server酱，绝不落到私聊]")
n, log = build(broken=("企业微信机器人",))
n._announcing = True
check("仍算送达", n.send("⚠️ 出错了", "正文", alert=True), [])
check("试了群机器人，回退到 Server酱", [c for c, t in log if t == "⚠️ 出错了"], ["企业微信机器人", "Server酱"])
check("企业微信私聊没被惊动", any(c == "企业微信" for c, _ in log), False)

print("\n[Server酱 挂了：普通通知不往群里塞，也不进私聊，返回没送到]")
n, log = build(broken=("Server酱",))
n._announcing = True
check("返回失败", bool(n.send("🔄 中继已更新", "正文")), True)
check("只试了 Server酱", sorted({c for c, _ in log}), ["Server酱"])

print("\n[默认就是日常，不是报警]")
n, log = build()
n.send("🆕 预更新", "")
check("预更新只走一处", [c for c, _ in log], ["Server酱"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
