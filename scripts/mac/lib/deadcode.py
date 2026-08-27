#!/usr/bin/env python3
"""揪出「写了但永远不会被执行」的函数。

    scripts/mac/lib/deadcode.py <目录或文件> [...]

**为什么存在**（2026-08-27，同一类错的第三次）：

`relay/tests/*.py` 的约定是「裸脚本 + `check()` + `main()`」，不是 pytest。
我按 pytest 的习惯写 `def test_xxx(...)` 追加到文件末尾——那些函数
**永远不会被调用**，测试照样打印 "all checks passed"，闸门照样放行。
错的不是那一次，是「定义了却没人调用」这一整类：它不报错、不报警、
不留痕迹，只是安静地什么都不做。用户的原话是
「今天第三次你踩同一个坑，永远杜绝不完吗？」

所以这里不针对 pytest，也不针对测试文件，而是针对**这一类**：
全仓扫一遍，凡是顶层 `def`／`class` 的名字在**整个仓库**里
（包括自己文件内）除了定义处之外一次都没被提到，就判失败。

跨文件引用算数（`ark_relay` 里的函数被 `service.py` 调用是正常的），
所以先把所有文件的「被提到的名字」收成一个集合，再逐个比对。

放行的写法：名字以 `_` 开头的私有辅助（可能只是暂时没用上）不算，
以及显式加 `# deadcode: allow` 的那一行。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "build", "dist"}
# 上游的源码原样存在这里作参照，里面的方法由 OK-WW 自己调用，不归我们管。
SKIP_PARTS = {"okww_files"}
# 「定义了没人调用」只在这些地方算铁案：测试里的孤立函数一定是漏跑的，
# 脚本里的孤立函数一定是忘了接。库模块对外提供 API，不适用。
UNUSED_SCOPE = ("relay/tests/", "scripts/")
# 这些名字由外部约定调用，不会在仓库里被显式提到。
CONVENTION = {"main", "__init__", "__repr__", "__str__", "__enter__", "__exit__"}


def py_files(roots: list[str]) -> list[Path]:
    out: list[Path] = []
    for r in roots:
        p = Path(r)
        if p.is_file() and p.suffix == ".py":
            out.append(p)
        elif p.is_dir():
            out += [f for f in p.rglob("*.py")
                    if not (SKIP_DIRS & set(f.parts))
                    and not (SKIP_PARTS & set(f.parts))]
    return sorted(set(out))


def defined_names(tree: ast.AST) -> list[tuple[str, int, str]]:
    """所有函数定义：(名字, 行号, 所属作用域)。

    作用域要带上，否则两个类各自的 `__init__` 会被当成重名——
    第一版就是这么误报了一屏。
    """
    found: list[tuple[str, int, str]] = []

    def walk(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.append((child.name, child.lineno, scope))
                walk(child, f"{scope}.{child.name}")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{scope}.{child.name}")
            else:
                walk(child, scope)

    walk(tree, "")
    return found


def mentioned_names(text: str, tree: ast.AST) -> set[str]:
    """这个文件里「提到过」的名字：调用、属性、装饰器、字符串里出现的都算。

    宁可放过也不误杀——目的是抓住「一次都没提过」这种铁案。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    return names


def main(argv: list[str]) -> int:
    roots = argv[1:] or ["relay", "scripts"]
    files = py_files(roots)
    if not files:
        print("deadcode: 没有可检查的 .py")
        return 0

    parsed: dict[Path, ast.AST] = {}
    all_mentions: set[str] = set()
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
        except SyntaxError as e:
            print(f"deadcode: {f} 语法错误，跳过：{e}")
            continue
        parsed[f] = tree
        all_mentions |= mentioned_names(text, tree)

    bad: list[str] = []
    for f, tree in parsed.items():
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        rel = f.as_posix()
        check_unused = any(k in rel for k in UNUSED_SCOPE)
        # 重名只在**同一个作用域**里才算覆盖：两个类各自的 __init__ 不是重名。
        seen: dict[tuple[str, str], int] = {}
        for name, lineno, scope in defined_names(tree):
            row = lines[lineno - 1] if lineno <= len(lines) else ""
            if "deadcode: allow" in row:
                continue
            key = (scope, name)
            if key in seen:
                where = scope or "模块顶层"
                bad.append(f"  {f}:{lineno}  `{name}`（{where}）重名——"
                           f"第 {seen[key]} 行那个被这个盖掉了，永远不会被执行")
            seen[key] = lineno
            if not check_unused or scope or name.startswith("_") \
                    or name in CONVENTION:
                continue
            if name not in all_mentions:
                bad.append(f"  {f}:{lineno}  `{name}` 定义了，"
                           f"但全仓库没有任何地方调用它——写了等于没写")

    if bad:
        print("deadcode: 发现永远不会被执行的代码")
        for b in bad:
            print(b)
        print("\n  要么把它接进调用链，要么删掉；")
        print("  确实是留给外部调用的，在 def 那行加 `# deadcode: allow`。")
        return 1
    print(f"deadcode: {len(parsed)} 个文件，没有孤立函数")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
