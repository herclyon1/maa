"""代码里指向 docs/CODE-HISTORY.md 的两条规矩。

一、**锚点必须存在，而且只能有一处**。2026-09-08 审出来：那份文档里有 5 组同名章节
（`handle.py:_handle` 一个名字下挂着四段互不相干的事），代码里写「见 handle.py:_handle」
的人会落在第一段上，读到的是**另一件事的**来龙去脉。同名章节已合并，这道闸门防它回来。

二、**指针上面那句话必须说完**。当初把注释搬进文档时，代码里只留了原注释的头一两行，
于是留下二十来处半截话：「Endfield.exe is on this list because MaaEnd has NO process of its」
后面直接是指针；「用户 2026-08-31：「中继服务卡在 STOP_PENDING 这个不要再出现了，」也是。
半截话比没有更糟——读的人以为自己读到了理由。所以指针前一行必须是个完整句子的收尾。
"""
import re
import sys
from pathlib import Path

POINTER = re.compile(r"来龙去脉见 docs/CODE-HISTORY\.md「(.+?)」")
# 一句话说完的收尾：句号、问号、叹号、右括号/引号、分号、冒号（冒号后面接的是下文列表）
ENDS = ("。", "！", "？", "；", "：", "」", "』", "）", ")", ".", "!", "?", ":", ";", "──", "—")


def main(root: str = "relay") -> int:
    doc = Path("docs/CODE-HISTORY.md")
    names = re.findall(r"^## (.+)$", doc.read_text(encoding="utf-8"), re.M)
    dupes = {n for n in names if names.count(n) > 1}
    bad = [f"docs/CODE-HISTORY.md 有同名章节：{n}——指过去的人会落在第一段上" for n in sorted(dupes)]
    have = set(names)

    for f in sorted(Path(root).rglob("*.py")):
        if "okww_files" in f.parts:
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = POINTER.search(line)
            if not m:
                continue
            if m.group(1) not in have:
                bad.append(f"{f}:{i+1} 指向的章节不存在：{m.group(1)}")
            prev = lines[i - 1].strip() if i else ""
            if not prev.startswith("#"):
                continue                      # 指针是这段注释的第一行，没有半截问题
            txt = prev.lstrip("#").strip()
            if txt and not txt.endswith(ENDS) and "---" not in txt and "──" not in txt:
                bad.append(f"{f}:{i} 指针上面那句话没说完：{txt[-30:]}")
    print("\n".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
