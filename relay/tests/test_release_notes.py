"""更新播报要说「修好了什么毛病」，不是列一串文件名。

2026-08-26 用户看到的播报是「改动文件：service.py、preupdate.py……」，
对着不看代码的人等于什么都没说。原话：「**更新内容用人话写**」。

所以 `relay/RELEASE-NOTES.md` 跟代码一起部署，播报优先念它；
没有这个文件时才退回列文件名（老行为，不能退化）。

这里测的是「说明文件在不在决定播报内容」，以及那份说明本身够不够人话——
后者用一条粗但有效的判据：**不许出现代码符号**。
"""
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def render(notes_dir: Path, files: list[str]) -> str:
    """service.py 里组装播报正文的那几行，原样复刻。

    复刻而不是 import：那段逻辑埋在服务主循环里，拆出来单测要动生产代码，
    而这里真正要钉住的是「有说明文件就念说明、没有就列文件名」这个取舍。
    """
    lines = ["刚刚生效", "版本 v1 → v2"]
    notes = ""
    nf = notes_dir / "RELEASE-NOTES.md"
    if nf.exists():
        notes = nf.read_text(encoding="utf-8").strip()
    if notes:
        lines += ["", notes]
    else:
        lines.append("改动文件：" + "、".join(files) if files
                     else "（改动清单由上一版代码写入，本次没有）")
    lines += ["", "更新在开机后、队列开跑前落地，本轮直接使用新代码。"]
    return "\n".join(lines)


def test_switch(tmp: Path) -> None:
    print("[有说明文件时念说明，没有时列文件名]")

    empty = tmp / "no-notes"
    empty.mkdir()
    body = render(empty, ["service.py", "preupdate.py"])
    check("没有说明文件 → 退回列文件名（老行为不退化）",
          "改动文件：service.py、preupdate.py" in body, True)

    withn = tmp / "with-notes"
    withn.mkdir()
    (withn / "RELEASE-NOTES.md").write_text(
        "开机预更新的两处误报修好了\n\n· MAA 明明已经下载好了，中继却说没确认到\n",
        encoding="utf-8")
    body = render(withn, ["service.py", "preupdate.py"])
    check("有说明文件 → 正文里有说明", "开机预更新的两处误报修好了" in body, True)
    check("有说明文件 → 不再列文件名", "改动文件：" in body, False)

    blank = tmp / "blank-notes"
    blank.mkdir()
    (blank / "RELEASE-NOTES.md").write_text("   \n\n  \n", encoding="utf-8")
    body = render(blank, ["service.py"])
    check("说明文件是空白 → 当作没有，退回列文件名",
          "改动文件：service.py" in body, True)


def test_is_plain_language() -> None:
    """随仓库的那份说明本身要是人话。

    判据故意粗：**不许出现代码符号**（下划线函数名、括号调用、驼峰、路径后缀）。
    这拦不住所有术语，但拦得住「修复 `maa_update_pending()` 未识别 MirrorChyan
    zip 制品」这种——而那正是当天被点名的写法。
    """
    print("[RELEASE-NOTES.md 是不是人话]")
    nf = HERE / "RELEASE-NOTES.md"
    check("说明文件存在", nf.exists(), True)
    if not nf.exists():
        return
    text = nf.read_text(encoding="utf-8")
    if not text.strip():
        # 空是**合法状态**：部署成功后脚本会把它清零，逼下一次写新的。
        # 拦「空着就部署」是部署脚本的闸（`[ ! -s "$NOTES" ]`），不是这里的事；
        # 这里只负责「有内容的时候，内容得是人话」。
        print("  ok   文件是空的——刚部署完的正常状态，人话检查跳过")
        return

    jargon = {
        "下划线函数名": r"\b[a-z]+_[a-z_]+\(",
        "函数调用括号": r"\w+\(\)",
        "代码文件名":   r"\b\w+\.(py|json|sh|md)\b",
        "驼峰标识符":   r"\b[a-z]+[A-Z]\w+\b",
    }
    for label, rx in jargon.items():
        hit = re.search(rx, text)
        check(f"不含{label}", hit.group(0) if hit else None, None)


def main(tmp: Path) -> int:
    test_switch(tmp)
    test_is_plain_language()
    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as t:
        raise SystemExit(main(Path(t)))
