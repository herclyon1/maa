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


print("[三个通道各司其职：真报警进群，日报和其余走 Server酱，私聊永远不自动发]")
n, log = build()
check("日报发出去了", n.send("📋 日报", "正文", daily=True), [])
check("日报只走 Server酱（群机器人 2048 字节就截断成好几条）", [c for c, _ in log], ["Server酱"])
n, log = build()
check("报警发出去了", n.send("⚠️ 出错了", "正文", alert=True), [])
check("报警只进群机器人", [c for c, _ in log], ["企业微信机器人"])
n, log = build()
check("其余通知发出去了", n.send("🆕 游戏更新", "正文"), [])
check("其余通知只走 Server酱", [c for c, _ in log], ["Server酱"])

print("\n[Server酱 挂了：日报回退到群机器人（分条也比没有强），绝不落到私聊]")
n, log = build(broken=("Server酱",))
n._announcing = True
check("日报仍算送达", n.send("📋 日报", "正文", daily=True), [])
check("先试 Server酱，回退到群机器人", [c for c, t in log if t == "📋 日报"], ["Server酱", "企业微信机器人"])

print("\n[群机器人挂了：报警回退到 Server酱，绝不落到私聊]")
n, log = build(broken=("企业微信机器人",))
n._announcing = True
check("仍算送达", n.send("⚠️ 出错了", "正文", alert=True), [])
check("试了群机器人，回退到 Server酱", [c for c, t in log if t == "⚠️ 出错了"], ["企业微信机器人", "Server酱"])
check("企业微信私聊没被惊动", any(c == "企业微信" for c, _ in log), False)

print("\n[这条报警到底进没进群（errwatch 据此决定那行日志要不要再推）]")
n, log = build()
n.send("⚠️ 出错了", "正文", alert=True)
check("群机器人收了：进了群", n.went_to_group(), True)
n, log = build(broken=("企业微信机器人",))
n._announcing = True
n.send("⚠️ 出错了", "正文", alert=True)
check("群机器人没收、Server酱 收了：没进群", n.went_to_group(), False)
n, log = build()
n.send("🆕 游戏更新", "正文")
check("普通通知：没进群", n.went_to_group(), False)
check("只发群机器人的：进了群", (n.send_group("⚠️ 出错了", "正文"), n.went_to_group()), ([], True))

print("\n[Server酱 挂了：普通通知不往群里塞，也不进私聊，返回没送到]")
n, log = build(broken=("Server酱",))
n._announcing = True
check("返回失败", bool(n.send("🆕 游戏更新", "正文")), True)
check("只试了 Server酱", sorted({c for c, _ in log}), ["Server酱"])

print("\n[日报或手机页已经有的不再推：只记日志，算送达]")
from ark_relay.notify import route_of  # noqa: E402
for t in ("🔄 中继已更新（3 个文件）", "🗓️ 周常", "⏭️ 跳过模式", "🛑 已停一切", "📱 配置已修改",
          "🗂️ 证据包已送出机器", "✅ 自动采集：补跑后全部走完",
          "🩹 OK-WW 补丁（18 条）", "🥚 开始刷声骸", "✅ 无音区结算截图：不发了"):
    check(f"只记日志：{t}", route_of(t, alert=t.startswith("⚠️")), "log")
# Success and acknowledgements only: a healthy patch round is log-only even when
# the caller sends texts.patches() with alert=True for its failure variant.
check("补丁全贴上（alert=True 也只记日志）", route_of("🩹 OK-WW 补丁（18 条）", alert=True), "log")
n, log = build()
check("只记日志的返回空（调用方不再重推）", n.send("🔄 中继已更新", "正文"), [])
check("一个通道都没碰", log, [])

print("\n[还会推的：报警进群，其余进 Server酱]")
for t in ("❌ OK-WW 失败", "⚠️ 这一轮没干完", "早班 没有运行", "🔌 AUTO-MAS 启动不起来", "⚠️ 中继自更新没成功",
          "🛑 没能停干净，需要你动手",
          "⚠️ 终末地 MaaEnd 卡住，已结束它让 AUTO-MAS 接着走", "⚠️ 终末地 MaaEnd 卡死，没能结束，需要人工看一眼",
          "⏱️ 鸣潮（OK-WW）跑超时，AUTO-MAS 正在重试", "⏰ 早班超时还没跑完",
          "❌ 明日方舟早班没跑成", "⚠️ 终末地晚班没干完",
          # failures, so the group (the user, 2026-10-06: every error, every time)
          "⚠️ 自动采集：补跑仍有路线没走通", "🚩 自动采集：有路线连续两天补跑失败，是复发性问题",
          "⚠️ 剿灭开关没能关上", "⚠️ 剿灭开关没能恢复", "⚠️ 森空岛给了不止一个终末地角色，没有读",
          "🩺 中继自己报错了（3 条）",
          # 2026-10-06 (「不论多少次什么错误都要发」): these left the log list / the
          # Server酱 demotion, or are new
          "⚠️ MaaEnd 中途失败过，重试后成功", "⚠️ OK-WW 更新时失败过，重跑后成功",
          "⚠️ OK-WW 中途重启了一次，AUTO-MAS 接着重试", "⚠️ 明日方舟早班失败过，补跑后走通了",
          "⚠️ 明日方舟理智不够，这一趟没打", "⚠️ 终末地装新版重启了这一趟（前面那趟已做完）",
          "⏸ MaaEnd 进不了游戏，稍后补跑", "⚠️ 预更新没能确认（1 项）", "⚠️ 游戏更新没能确认（2 项）",
          "⚠️ OK-WW 补丁有 1 条没贴上（共 18 条）", "🔌 推送通道故障：企业微信机器人",
          "🔁 自动采集：只补跑失败的路线"):
    check(f"进群：{t}", route_of(t, alert=True), "group")
check("只补跑失败的路线：没带 alert 也进群", route_of("🔁 自动采集：只补跑失败的路线"), "group")
for t in ("🆕 预更新", "🆕 游戏更新", "🔁 更新后重跑", "🥚 刷声骸收工", "⏸ MaaEnd 进不了游戏，稍后补跑", "🌙 今晚不关机",
          "📱 配置没改成", "✗ set_stage: 找不到", "🔓 终末地日常已开回", "🗓️ 新的一周", "⚠️ OK-WW 补丁有 1 条没贴上（共 18 条）",
          "🔌 推送通道故障：企业微信", "💳 月卡快到期"):
    check(f"Server酱：{t}", route_of(t), "info")
check("预更新没能确认：带 alert 就进群，不再降到 Server酱", route_of("⚠️ 预更新没能确认（1 项）", alert=True), "group")
check("日报走 Server酱", route_of("📋 09-14 · 全绿 ✅", daily=True), "daily")

print("\n[docs/NOTIFICATIONS.md 的表和代码一致]")
import re  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_doc = (_P(__file__).resolve().parents[2] / "docs" / "NOTIFICATIONS.md").read_text(encoding="utf-8")
_rows = re.findall(r"^\| (.+?) \| (group|daily|info|log) \| ", _doc, flags=re.M)
check("表里至少 25 行", len(_rows) >= 25, True)
_probe = {"📋 日报 / 🔎 临时查看 / （补发）": ("📋 09-14 · 全绿", True, False),
          "❌ <script> 失败": ("❌ OK-WW 失败", False, True),
          "<队列> 没有运行 / 机器没开机": ("早班 没有运行", False, True),
          "⏸ <script> 进不了游戏，稍后补跑": ("⏸ MaaEnd 进不了游戏，稍后补跑", False, True),
          "⚠️ <script> 中途失败过，重试后成功": ("⚠️ MaaEnd 中途失败过，重试后成功", False, True),
          "📱 配置没改成 / ✗ …": ("✗ set_stage: 没有这个字段", False, False),
          "⏭️ 跳过模式 / 🛑 已停一切 / 📱 配置已修改 / ✅ …": ("✅ 刷取关卡：TO-5 → 1-7", False, False),
          "🩹 OK-WW 补丁（N 条）": ("🩹 OK-WW 补丁（18 条）", False, False),
          "⚠️ OK-WW 补丁有 N 条没贴上": ("⚠️ OK-WW 补丁有 1 条没贴上（共 18 条）", False, True),
          "⚠️ 预更新没能确认 / ⚠️ 游戏更新没能确认": ("⚠️ 预更新没能确认（1 项）", False, True)}
for cell, want in _rows:
    if cell in _probe:
        title, daily, alert = _probe[cell]
    else:
        title, daily, alert = cell.split(" / ")[0], False, want == "group"
    check(f"表：{cell} → {want}", route_of(title, alert=alert, daily=daily), want)

print("\n[通道坏了：每一次被拒都报，不是每种故障报一次（2026-10-06）]")
n, log = build(broken=("企业微信机器人",))
check("第一条报警送到了（Server酱）", n.send("⚠️ 出错了", "正文", alert=True), [])
check("第二条报警送到了（Server酱）", n.send("⚠️ 又出错了", "正文", alert=True), [])
check("两次被拒，两条通道故障", len([t for c, t in log if t.startswith("🔌") and c == "Server酱"]), 2)
check("故障通知试的也是群的顺序：先群机器人，再 Server酱",
      [c for c, t in log if t.startswith("🔌")][:2], ["企业微信机器人", "Server酱"])

print("\n[默认就是日常，不是报警]")
n, log = build()
n.send("🆕 预更新", "")
check("预更新只走一处", [c for c, _ in log], ["Server酱"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
