"""The busy gate must not mistake itself for a running script.

2026-09-09: `run-one.sh OK-WW` refused every dispatch with 「ok-ww 还在跑」 while
`run-one.sh status` reported the machine idle. The gate looked for 「ok-ww」 anywhere
in a python process's command line, PowerShell's -like is case-insensitive, and the
gate's own argument is the string OK-WW. It was seeing itself. A gate that blocks
everything is as broken as one that blocks nothing.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SRC = (Path(__file__).resolve().parents[2] / "scripts" / "windows"
       / "dispatch_guard.py").read_text(encoding="utf-8")

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


pattern = re.search(r"CommandLine -like '([^']+)'", SRC)
print("[判据必须是安装路径，不是一个能出现在参数里的词]")
check("找得到那条匹配", bool(pattern))
like = pattern.group(1) if pattern else ""
check(f"带路径分隔符（{like}）", "\\" in like)


def matches(cmdline: str) -> bool:
    """PowerShell -like, case-insensitive, * only."""
    body = re.escape(like).replace(r"\*", ".*")
    return re.fullmatch(body, cmdline, re.IGNORECASE) is not None


print("[真在跑的两种起法都要认出来]")
check("AUTO-MAS 起的 pythonw",
      matches(r"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe D:\ark\okww\data\apps\ok-ww\working\main.py -t 1 -e"))
check("手动起的 python",
      matches(r"D:\ark\okww\data\apps\ok-ww\python\python.exe main.py -t 2"))

print("[闸门自己和别的脚本不许被算进去]")
check("闸门自己（参数里带 OK-WW）",
      matches(r"C:\Python314\python.exe C:\ProgramData\winrun-run-123.py OK-WW"), False)
check("参数里带小写 ok-ww 的别的命令",
      matches(r"C:\Python314\python.exe something.py --script ok-ww"), False)
check("中继自己",
      matches(r"C:\Program Files\Python314\pythonservice.exe"), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
