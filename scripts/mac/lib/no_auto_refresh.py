"""断言 snapshot.py 里没有任何「读取时自动去拉」的调用。

grep 会被文档字符串里的 `refresh_snapshot.refresh()` 骗到，所以用 AST
只看真正的函数调用。
"""
import ast, sys
src = open("scripts/mac/lib/snapshot.py", encoding="utf-8").read()
bad = []
for n in ast.walk(ast.parse(src)):
    if not isinstance(n, ast.Call):
        continue
    f = n.func
    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
    if "refresh" in name:
        bad.append(f"第 {n.lineno} 行调用了 {name}()")
if bad:
    print("snapshot 在读取路径上自动刷新 = 轮询：" + "；".join(bad))
    sys.exit(1)
