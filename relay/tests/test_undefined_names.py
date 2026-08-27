"""任何一个裸名字被读取之前，必须在某个作用域里绑定过。

2026-08-26：`engine.py` 的周常乐园那一支写的是 `notes.append(msg)`，
可那个作用域里根本没有 `notes`——它是从剿灭那支抄过来时改了一半。
Python 直到那一行真的跑起来才会报 NameError，而它只在
「OK-WW 跑完 + 步骤里出现『周常乐园（本周已完成）』」时才跑到，
于是一路潜伏到当天下午，把整条运行记录的处理打断：

    ERROR ark.engine  处理运行记录失败: 2026-08-26/wuwa/OK-WW-12-50-57
    NameError: name 'notes' is not defined. Did you mean: 'modes'?

`test_self_attrs.py` 防的是 `self.x` 那一类，防不住裸名字。
这个文件补上另一半：**未定义的裸名字是源码的静态事实**，
不该靠某一天的运行路径来发现。

做法是 pyflakes 那套的最小版：按作用域栈收集所有绑定
（参数、赋值、for、with as、except as、import、推导式、walrus、
函数/类定义、global/nonlocal 声明），再看每一处读取是否落在
「本作用域 ∪ 外层作用域 ∪ 模块级 ∪ builtins」里。
"""
import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILTINS = set(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__package__", "__spec__", "__debug__",
}

FAILED = []


def _bound_by(node: ast.AST) -> set[str]:
    """这个节点直接绑定了哪些名字（不下钻到子作用域）。"""
    out: set[str] = set()

    def targets(t):
        if isinstance(t, ast.Name):
            out.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                targets(e)
        elif isinstance(t, ast.Starred):
            targets(t.value)
        # Attribute / Subscript 赋值不产生新名字

    if isinstance(node, (ast.Assign,)):
        for t in node.targets:
            targets(t)
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        targets(node.target)
    elif isinstance(node, ast.NamedExpr):          # walrus
        targets(node.target)
    elif isinstance(node, (ast.For, ast.AsyncFor)):
        targets(node.target)
    elif isinstance(node, (ast.With, ast.AsyncWith)):
        for it in node.items:
            if it.optional_vars is not None:
                targets(it.optional_vars)
    elif isinstance(node, ast.ExceptHandler):
        if node.name:
            out.add(node.name)
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        for a in node.names:
            out.add((a.asname or a.name).split(".")[0])
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        out.add(node.name)
    elif isinstance(node, (ast.Global, ast.Nonlocal)):
        out.update(node.names)
    elif isinstance(node, ast.comprehension):
        targets(node.target)
    return out


def _scope_binds(scope: ast.AST) -> set[str]:
    """一个作用域里绑定的全部名字。子作用域的函数体不算，但它们的**名字**算。"""
    out: set[str] = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = scope.args
        for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs):
            out.add(arg.arg)
        for arg in (a.vararg, a.kwarg):
            if arg is not None:
                out.add(arg.arg)

    body = [scope] if isinstance(scope, ast.Lambda) else list(
        ast.iter_child_nodes(scope))

    def walk(n, top=False):
        out.update(_bound_by(n))
        # 不下钻进子作用域的函数体——那是它自己的事
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.Lambda, ast.ClassDef)) and not top:
            return
        for c in ast.iter_child_nodes(n):
            walk(c)

    for n in body:
        walk(n, top=True)
    return out


def _check_scope(scope: ast.AST, visible: set[str], path: Path) -> None:
    here = visible | _scope_binds(scope)

    # 推导式在 Python 3 里自成作用域，但它的目标名字对内部可见。
    def loads(n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                          ast.ClassDef)) and n is not scope:
            _check_scope(n, here, path)
            # 装饰器和默认值在**外层**求值
            for d in getattr(n, "decorator_list", []):
                loads(d)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if n.id not in here:
                FAILED.append(f"{path.name}:{n.lineno} 读取了未定义的名字 `{n.id}`")
        for c in ast.iter_child_nodes(n):
            loads(c)

    for c in ast.iter_child_nodes(scope):
        loads(c)


def main() -> int:
    files = sorted(ROOT.glob("ark_relay/*.py")) + [ROOT / "service.py", ROOT / "run.py"]
    files = [f for f in files if f.exists()]
    print(f"[裸名字检查] {len(files)} 个文件")
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        _check_scope(tree, BUILTINS, f)

    if FAILED:
        for m in FAILED:
            print("  FAIL", m)
        print(f"FAILED: {len(FAILED)} 处")
        return 1
    print("  ok   没有未定义的裸名字")
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
