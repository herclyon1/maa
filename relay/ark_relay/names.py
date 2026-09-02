"""队列的名字，以及改名后对旧名字的兼容。

2026-09-01 用户要求：队列名改成「早班」「晚班」，一目了然。原来叫
「新队列」（AUTO-MAS 新建时的默认名）和「Evening-MAA」。

旧名字还可能出现在：手机页面排队中的指令、跳过标记文件、
恢复标记里。改名不能让它们变成「没有这个队列」——统一走 canonical()。
这个模块不 import 任何东西，谁都能引用，没有循环。
"""

MORNING = "早班"
EVENING = "晚班"

ALIASES = {
    "新队列": MORNING,
    "Evening-MAA": EVENING,
}


def canonical(name: str) -> str:
    """把旧名字换成现在的名字；本来就是现名或未知名原样返回。"""
    return ALIASES.get((name or "").strip(), (name or "").strip())
