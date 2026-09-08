"""测试文件的两条形状规矩。

一、`check()` 只准有一个意思：`check(说明, 实际, 期望)`。

2026-09-08 审出来的：66 个测试文件各写各的 `check()`，其中
test_mastercfg.py 和 test_preupdate_session.py 写成了 `check(名字, 成立与否, 补充说明)`——
名字一样、第二第三个参数的意思却是反的。在这两个文件里顺手写一句
`check("读到的关卡", got, "AT-4")`，第三个参数会被当成「补充说明」打出来，
断言退化成「got 是不是真值」，**永远通过**。一个字都不会报错。

所以规矩定死：比较相等的叫 `check(label, got, want)`；
判断真假的叫 `require(name, ok, detail="")`。名字不同，就不可能记混。

二、测试不许依赖当前工作目录。同一天审出来的：test_preupdate_problems.py 里写了
`Path("ark_relay/texts.py")`，只有在 relay/ 底下跑才找得到。部署脚本恰好是在
relay/ 底下跑的，所以一直没暴露；换个地方跑就报 FileNotFoundError，
而那正是「我随手跑一下这个测试」的场景。仓库里的文件一律从 `__file__` 起算。
"""
import ast
import sys
from pathlib import Path

EQ = ("label", "got", "want")
TRUTH = ("name", "ok", "detail")


def main(root: str = "relay/tests") -> int:
    bad = []
    for f in sorted(Path(root).glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as e:
            bad.append(f"{f}: 语法错误 {e}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in ("check", "require"):
                continue
            args = [a.arg for a in node.args.args]
            if node.name == "check" and tuple(args[:3]) not in (EQ, ("name", "got", "want"), ("what", "got", "want"), ("label", "got")):
                bad.append(f"{f}:{node.lineno} check() 的参数是 {args}，"
                           f"应该是 (label, got, want)——判真假的请改叫 require")
            if node.name == "require" and tuple(args[:3]) != TRUTH:
                bad.append(f"{f}:{node.lineno} require() 的参数是 {args}，"
                           f"应该是 (name, ok, detail='')")
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Path" and node.args):
                continue
            a = node.args[0]
            if not (isinstance(a, ast.Constant) and isinstance(a.value, str)):
                continue
            v = a.value
            if v.startswith(("/", "~")) or not v or "/" not in v:
                continue
            bad.append(f"{f}:{node.lineno} Path({v!r}) 是相对当前工作目录的，"
                       f"换个地方跑就找不到——仓库里的文件请从 __file__ 起算")
    print("\n".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
