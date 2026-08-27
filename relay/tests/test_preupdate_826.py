"""826 那天三条预更新报错里，有两条是判据写错了，不是真的没更新。

早上 08:51 中继报了「预更新没能确认（3 项）」，可机器上的日志显示：

  * MAA 08:45:33 就从 MirrorChyan 发现了 v6.17.0-beta.6 并把 zip 下到了根目录；
  * MaaEnd 08:48:37 已经装好 v2.26.0-beta.6 并在日志里写了「检测到刚更新完成」。

两边都动过了，中继却各等满 180 秒然后报「没有确认过是否有更新」。原因：

  1. `maa_update_pending()` 只看 `NewVersion/` 目录——那是 GitHub 通道的形状。
     MirrorChyan 通道把更新下成 **MAA 根目录里的一个 zip**，永远不建 NewVersion。
  2. `_run_maaend()` 只认「更新检查完成: ... 有更新=false」。可 MaaEnd 刚装完更新
     重启那一次**根本不再检查**（刚装完再问一遍没意义），所以那行永远不会来。

这两条都是「等一个不会出现的信号」。这个文件把它们钉住。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import preupdate                       # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def test_maa_pending(tmp: Path) -> None:
    """MirrorChyan 的 zip 也是「已下好、等重启装上」，不能只认 NewVersion。"""
    print("MAA：暂存更新的两种形状")

    empty = tmp / "maa-empty"
    empty.mkdir()
    check("干净目录 → 没有待装更新", preupdate.maa_update_pending(empty), False)

    newver = tmp / "maa-newversion"
    (newver / "NewVersion").mkdir(parents=True)
    check("有 NewVersion 目录 → 有待装更新（GitHub 通道）",
          preupdate.maa_update_pending(newver), True)

    mc = tmp / "maa-mirrorchyan"
    mc.mkdir()
    (mc / "MirrorChyanAppv6.17.0-beta.6.zip").write_bytes(b"PK\x03\x04")
    check("根目录有 MirrorChyanApp*.zip → 有待装更新（826 漏掉的就是这个）",
          preupdate.maa_update_pending(mc), True)

    # 下载中的临时文件不算数，否则会把「正在下」误报成「已下好」。
    tmpf = tmp / "maa-downloading"
    tmpf.mkdir()
    (tmpf / "MirrorChyanAppv6.17.0-beta.6.zip.temp").write_bytes(b"partial")
    check("只有 .zip.temp（还在下）→ 不算已下好",
          preupdate.maa_update_pending(tmpf), False)

    check("目录不存在 → False（不炸）", preupdate.maa_update_pending(tmp / "nope"), False)
    check("传 None → False", preupdate.maa_update_pending(None), False)


def test_maaend_just_updated() -> None:
    """「检测到刚更新完成: vX」本身就是结论，不能再等「更新检查完成」。"""
    print("MaaEnd：刚更新完成 = 终态")

    # 08:48:37 那份日志的真实形状：装完了，然后就只有调度器轮询。
    just_updated = (
        "2026-08-26 08:48:37 INFO  [App] 已清除待安装更新信息\n"
        "2026-08-26 08:48:37 INFO  [App] 已读取更新完成信息: v2.26.0-beta.6\n"
        "2026-08-26 08:48:37 INFO  [App] 检测到刚更新完成: v2.26.0-beta.6\n"
        "2026-08-26 08:49:07 INFO  [Task] [调度器] 扫描 2 个时间槽\n"
        "2026-08-26 08:50:07 INFO  [Task] [调度器] 扫描 2 个时间槽\n"
    )
    m = preupdate._UPDATED.search(just_updated)
    check("能认出「刚更新完成」", m is not None, True)
    check("取到的版本号", m.group(1) if m else None, "v2.26.0-beta.6")
    check("这份日志里确实没有「更新检查完成」（所以等它必然超时）",
          preupdate._DONE.search(just_updated) is None, True)

    # 常规一轮：没更新，正常报「有更新=false」。这条路不能被上面的改动带坏。
    nothing_to_do = (
        "2026-08-26 12:37:12 INFO  [App] 开始检查更新\n"
        "2026-08-26 12:37:13 INFO  [App] 更新检查完成: 最新版本=v2.26.0-beta.6, 有更新=false\n"
    )
    d = preupdate._DONE.search(nothing_to_do)
    check("常规一轮仍能认出「有更新=false」", d is not None, True)
    check("  版本", d.group(1) if d else None, "v2.26.0-beta.6")
    check("  有更新", d.group(2) if d else None, "false")
    check("常规一轮里没有「刚更新完成」",
          preupdate._UPDATED.search(nothing_to_do) is None, True)


def test_byte_offset_read(tmp: Path) -> None:
    """按字节偏移续读，不能用字节数去切字符串。

    MAA 的 gui.log 全是中文。`stat().st_size` 是字节数，
    拿它去切 `read_text()` 得到的字符串，会一刀切过头把新增内容全跳掉——
    判据于是永远匹配不到，每次白等满 180 秒报「没给出更新结论」。
    """
    print("MAA：日志续读要按字节，不是按字符")
    f = tmp / "gui.log"
    head = "[2026-08-26 09:19:12][INF] 完成任务: 开始唤醒\n"      # 含中文
    f.write_text(head, encoding="utf-8")
    before = f.stat().st_size
    check("中文让字节数大于字符数（这就是 bug 的成因）",
          before > len(head), True)

    tail = '{"code":0,"msg":"current version is latest"}\n'
    with f.open("a", encoding="utf-8") as fh:
        fh.write(tail)

    got = preupdate._read_from(f, before)
    check("按字节续读拿到的正是新增那段", got, tail)
    check("新增段里能匹配到「已是最新」",
          preupdate._MAA_LATEST.search(got) is not None, True)

    # 老写法留在这里当反例：同样的输入，它匹配不到。
    wrong = preupdate._read(f)[before:]
    check("旧写法（字节数切字符串）匹配不到——所以才会超时",
          preupdate._MAA_LATEST.search(wrong) is None, True)



def main(tmp: Path) -> int:
    test_maa_pending(tmp)
    test_maaend_just_updated()
    test_byte_offset_read(tmp)
    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as t:
        raise SystemExit(main(Path(t)))
