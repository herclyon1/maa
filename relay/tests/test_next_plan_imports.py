"""next_plan 能不能被调起来——2026-09-04 就是这里断的。

那天 phone.py 瘦身删掉了 plan.py 还在 import 的一个函数，
`next_plan` 一调就 ImportError，把 tick() 里排在它后面的补更新、日报、
自动关机全带走，一上午没人发现。**当时没有任何测试调过 next_plan。**

这个测试不断言排版，只断言「调得起来、不抛异常」——跨模块引用断掉、
少个 import、名字改了，都会在这里红。
"""
import sys, tempfile, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay import plan  # noqa: E402

with tempfile.TemporaryDirectory() as d:
    # 没有 AUTO-MAS 目录也必须能返回，不能抛
    out = plan.next_plan(d)
    assert isinstance(out, str), f"next_plan 应返回字符串，得到 {type(out)}"
    out2 = plan.next_plan(None)
    assert isinstance(out2, str)
    # 那个被搬过来的辅助函数也得在，且对空输入安全
    assert plan._asar_value_labels(None, d) == {}
    assert plan._asar_value_labels(d, d) == {}
print("✅ next_plan 调得起来 — all checks passed")
