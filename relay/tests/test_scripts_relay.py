"""The relay's scripts: their attributes, a running one that asks AUTO-MAS.

One part per former file, each run on its own (tests/_parts.py): test_scripts_relay_attrs.py, test_scripts_running_asks_automas.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_scripts_relay_attrs():
    """Every name the helper scripts read off an ark_relay module still exists there.

The scripts under scripts/windows/ and scripts/mac/lib/ are shipped to the game
machine by winrun and import ark_relay at run time, so no relay test ever imports
them. On 2026-10-10 05:26 okww-check.sh died with

    AttributeError: module 'ark_relay.weeklyboss' has no attribute '_okww_file'

because 7425eff4 (2026-09-08) removed that helper and okww-landed.py still called
it. This walks each script's AST, resolves `from ark_relay import m as x`,
`import ark_relay.m as x` and `from ark_relay.m import a`, and requires every
`x.attr` / imported name to exist on the real module.

    Formerly test_scripts_relay_attrs.py.
    """
    import ast
    import importlib
    import inspect

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    ROOT = Path(__file__).resolve().parents[2]
    DIRS = [ROOT / "scripts" / "windows", ROOT / "scripts" / "mac" / "lib"]


    def missing_names(src: str) -> list:
        tree = ast.parse(src)
        alias = {}
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "ark_relay":
                for a in node.names:
                    alias[a.asname or a.name] = f"ark_relay.{a.name}"
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("ark_relay."):
                mod = importlib.import_module(node.module)
                for a in node.names:
                    if not hasattr(mod, a.name):
                        try:     # a submodule not imported yet: `from ark_relay.core import notify`
                            importlib.import_module(f"{node.module}.{a.name}")
                        except ModuleNotFoundError:
                            out.append(f"{node.module}.{a.name}")
                            continue
                    if inspect.ismodule(getattr(mod, a.name, None)):
                        alias[a.asname or a.name] = f"{node.module}.{a.name}"
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("ark_relay.") and a.asname:
                        alias[a.asname] = a.name
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in alias):
                mod = importlib.import_module(alias[node.value.id])
                if not hasattr(mod, node.attr):
                    out.append(f"{alias[node.value.id]}.{node.attr}")
        return out


    bad = {}
    for d in DIRS:
        for f in sorted(d.glob("*.py")):
            miss = missing_names(f.read_text(encoding="utf-8"))
            if miss:
                bad[str(f.relative_to(ROOT))] = miss
    check("every ark_relay name the scripts use exists", bad, {})

    # The 05:26 crash, from the pre-fix okww-landed.py:7 and :14 (import path moved to the new name).
    old = ("from ark_relay.features.weekly import weeklyboss as W  # noqa: E402\n"
           'o = json.loads(W._okww_file(name).read_text(encoding="utf-8"))\n')
    check("the 10-10 okww-check line is caught", missing_names(old), ["ark_relay.features.weekly.weeklyboss._okww_file"])
    check("names that exist pass",
          missing_names("from ark_relay.features.weekly import weeklyboss as W\nW.DAILY\nW._file\nW.name_from_log\n"), [])
    check("a missing from-import is caught",
          missing_names("from ark_relay.features.weekly.weeklyboss import nope\n"), ["ark_relay.features.weekly.weeklyboss.nope"])


def _part_scripts_running_asks_automas():
    """「有脚本在跑吗」先问 AUTO-MAS，不只看进程名。

2026-09-07 10:15：OK-WW 09:19 起跑了三趟（AUTO-MAS 整段结束 10:16 才写记录），
_scripts_running 的进程名单里没有 OK-WW，中继以为什么都没在跑，
75 分钟一到就发了「OK-WW 没有运行」「MaaEnd 没有运行」两条假报警。
runtime-snapshot 是 AUTO-MAS 自己的口径：每个脚本 完成/异常/运行/等待。

    Formerly test_scripts_running_asks_automas.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import engine


    # 2026-09-07 10:18 机器上拿到的真实样本（MAA 完成、OK-WW 异常、MaaEnd 运行）
    REAL = {"tasks": [{"taskId": "8cebb1be", "mode": "AutoProxy", "stopping": False,
                       "task_info": [
                           {"name": "MAA", "status": "完成", "userList": [{"name": "arknights", "status": "完成"}]},
                           {"name": "OK-WW", "status": "异常", "userList": [{"name": "wuwa", "status": "异常"}]},
                           {"name": "MaaEnd", "status": "运行", "userList": [{"name": "endfield", "status": "运行"}]}]}],
            "scheduledScripts": []}
    check("MaaEnd 运行中 → 在跑", engine._judge_snapshot(REAL), True)

    waiting = {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"}, {"name": "OK-WW", "status": "等待"}]}]}
    check("OK-WW 还在等待 → 在跑（假报警就是这一格）", engine._judge_snapshot(waiting), True)
    check("刚派下去、还没有状态 → 在跑", engine._judge_snapshot({"tasks": [{"task_info": []}]}), True)
    done = {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"}, {"name": "OK-WW", "status": "异常"}]}]}
    check("全部终态 → 没在跑", engine._judge_snapshot(done), False)
    check("没有任务 → 没在跑", engine._judge_snapshot({"tasks": []}), False)
    check("空回复 → 没在跑", engine._judge_snapshot(None), False)
    check("没见过的状态 → 当作在跑", engine._judge_snapshot({"tasks": [{"task_info": [{"status": "重试中"}]}]}), True)


if __name__ == "__main__":
    sys.exit(run_parts([_part_scripts_relay_attrs, _part_scripts_running_asks_automas]))
