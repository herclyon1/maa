"""inbox.Inbox：从仓库信箱取指令、判要不要执行、执行完记账。

**为什么补这一个**（2026-09-08 审出来）：手机之外唯一的下指令通道，
决定「这批指令要不要跑、跑几遍」，而它**一行测试都没有**。
这里最要命的三条判断都不出声：

* 版本号**必须严格变大**才执行。CDN 会发几分钟的旧副本，按「不一样就执行」
  会把旧方案再放一遍，机器来回翻。
* 取不到文件和取到了但没有新东西，poll() 都是安静返回——调用方要靠
  `last_fetch_ok` 分辨，才知道该不该重试。「暂停」的指令没下载下来，
  就等于没有这条指令。
* 应用到一半炸了也要**记下版本号**。不记的话，下次开机整批重放：
  skip_today 落到没人指定的那一天，改动重复执行一遍。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import inbox
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


class FakeInbox(inbox.Inbox):
    """不联网：把「取回来的那份 JSON」直接塞进来。"""

    payload = None

    def _fetch_or_none(self):
        return self.payload


def box(payload):
    b = FakeInbox(tmpdir())
    b.payload = payload
    return b


print("[版本号严格变大才执行]")
b = box({"version": 5, "name": "第一批", "commands": []})
ver, msgs = b.poll()
check("第一次收到就执行", ver, 5)
check("推送里带了名字", "第一批" in msgs[0], True)

b.payload = {"version": 5, "name": "同一版", "commands": []}
ver, msgs = b.poll()
check("同一个版本号不重放", msgs, [])
check("版本号没退回去", ver, 5)

b.payload = {"version": 4, "name": "更旧的（CDN 发的旧副本）", "commands": []}
ver, msgs = b.poll()
check("更旧的版本不执行", msgs, [])
check("版本号还是 5", ver, 5)

b.payload = {"version": 6, "name": "第二批", "commands": []}
ver, msgs = b.poll()
check("更新的版本才执行", ver, 6)

print("\n[取不到 ≠ 没有新东西：调用方要能分辨]")
b = box({"version": 9, "commands": []})
b.poll()
check("取到了", b.last_fetch_ok, True)
b.payload = None
ver, msgs = b.poll()
check("取不到时说取不到", b.last_fetch_ok, False)
check("取不到时不动版本号", ver, 9)
check("取不到时不推送", msgs, [])

print("\n[文件本身不成形要拒绝，而且不能记账]")
b = box({"version": "不是整数", "commands": []})
ver, msgs = b.poll()
check("版本号不是整数 → 忽略", (ver, msgs), (0, []))
b.payload = {"version": 3, "commands": "不是数组"}
ver, msgs = b.poll()
check("commands 不是数组 → 忽略", (ver, msgs), (0, []))
check("忽略之后版本号仍是 0（没记账）", b.applied_version, 0)

print("\n[应用中途炸了：要说清楚，而且必须记账，不许下次开机整批重放]")
b = box({"version": 11, "name": "会炸的一批", "commands": [{"action": "queue"}]})
b._apply = lambda cmds: (_ for _ in ()).throw(OSError("盘满了"))
ver, msgs = b.poll()
check("版本号照样记下", b.applied_version, 11)
check("说了是中途出错", any("应用中途出错" in m for m in msgs), True)
check("说了本批不会重放", any("不会重放" in m for m in msgs), True)

print("\n[记账落在 state.json 里，换一个实例也读得到]")
d = tmpdir()
b1 = FakeInbox(d)
b1.payload = {"version": 21, "commands": []}
b1.poll()
b2 = FakeInbox(d)
check("另一个实例读到同一个版本号", b2.applied_version, 21)
saved = json.loads((d / "state.json").read_text(encoding="utf-8"))
check("存在 queues/inbox_version 里", saved["queues"]["inbox_version"], "21")

print("\n[用户写的 note 要原样出现在推送正文里]")
b = box({"version": 31, "name": "改基质地点", "note": "换成清波寨，VFTheHub 刷不出来",
         "commands": []})
_, msgs = b.poll()
body = "\n".join(msgs)
check("note 在正文里", "换成清波寨" in body, True)
check("名字在标题里", "改基质地点" in msgs[0], True)

print("\n[没有 maaend/automas 路径时，明说跳过而不是假装做了]")
b = box({"version": 41, "commands": [
    {"action": "maaend_option", "task": "T", "option": "O", "value": True},
    {"action": "queue", "name": "早班", "enabled": True},
    {"action": "sanity_plan", "tab": "x"},
]})
_, msgs = b.poll()
body = "\n".join(msgs)
check("终末地那条说了跳过", "✗ 终末地：找不到安装路径" in body, True)
check("队列那条说了跳过", "✗ 队列：找不到 AUTO-MAS 目录" in body, True)
check("理智方案那条说了跳过", "✗ 理智方案：找不到 AUTO-MAS 目录" in body, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
