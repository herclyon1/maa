"""日志被轮转之后，按偏移读还能不能读到新内容。

2026-09-04：MAA 每次启动把 gui.log 挪成 gui.bak.log 再新开一份。
预更新记的是启动**前**那份的大小，拿去 seek 新的小文件，永远读到空，
于是 MAA 明明 7 秒就答了「current version is latest」，我们白等 180 秒
报「没能确认」，还把 tick 里排在后面的补更新、日报、关机全耽误了。
"""
import sys, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay.preupdate import _read_from, _MAA_LATEST  # noqa: E402

fails = []
with tempfile.TemporaryDirectory() as d:
    p = pathlib.Path(d) / "gui.log"
    p.write_text("旧日志" * 5000, encoding="utf-8")     # 一份大文件
    before = p.stat().st_size
    # MAA 启动：轮转，新开一份小的，里面写了「已是最新」
    p.write_text('MirrorChyan response: {"code":0,"msg":"current version is latest"}\n',
                 encoding="utf-8")
    got = _read_from(p, before)
    if not _MAA_LATEST.search(got):
        fails.append(f"轮转后读不到新内容：读到 {got[:60]!r}")

    # 正常追加的情况不能被这条修复带坏
    p2 = pathlib.Path(d) / "b.log"
    p2.write_text("头部\n", encoding="utf-8")
    off = p2.stat().st_size
    with p2.open("a", encoding="utf-8") as fh:
        fh.write("新增一行\n")
    tail = _read_from(p2, off)
    if "头部" in tail or "新增一行" not in tail:
        fails.append(f"正常追加被读坏了：{tail!r}")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
