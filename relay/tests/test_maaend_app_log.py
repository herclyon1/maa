"""核对 MaaEnd 时必须连它自己的 app 日志一起看。

2026-08-29 早班：中继推了一条「MaaEnd 这一轮有 2 项没干成」的告警，两条都是误报。

第一条「日志里没有『自动执行任务完成』」——这句收尾标记只写在 MaaEnd 自己的
`<maaend>/debug/YYYY-MM-DD-N.log` 里（`INFO [App] 自动执行任务完成，关闭自身`），
而核对时只喂了 AUTO-MAS 的 history 日志，那里面永远没有这句。翻 10 天 22 份
history 日志，出现 0 次——也就是这条判据恒为假。当天 MaaEnd 其实 09:54:38
打了那句，16 个任务全部收尾。**判据没错，错在没给它该看的文件。**

第二条「有 6 张出错截图」——那 6 张是 ScenePrivateMapZoomOut，重试后恢复，
环境监测和基质刷取都报了「任务完成」。万能跳转失败（SceneAnyEnterWorld）
仍然一律算故障，那是 2026-08-27 真事故的判据，不放宽。
"""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import engine, outcome  # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


HISTORY = "\n".join(
    f"[2026-08-29 09:3{i}:00.000] 任务开始: 任务{i}\n"
    f"[2026-08-29 09:3{i}:30.000] 任务完成: 任务{i}" for i in range(3))
APP = "2026-08-29 09:54:38 INFO  [App] 自动执行任务完成，关闭自身\n"
SHOTS = [f"2026.08.29-09.39.5{i}___ScenePrivateMapZoomOut.png" for i in range(3)]
STUCK = ["2026.08.27-09.44.59_SceneAnyEnterWorld.png"]


def _bad(checks):
    return [c.label for c in checks if not c.ok]


def main() -> int:
    print("=== 只看 history 日志（早班那次的错误做法）===")
    got = outcome.maaend_checks(HISTORY, SHOTS)
    check("会误判成没跑完", "MaaEnd 跑完" in _bad(got), True)

    print("\n=== 连 app 日志一起看（修好之后）===")
    got2 = outcome.maaend_checks(HISTORY + "\n" + APP, SHOTS)
    check("不再误判没跑完", "MaaEnd 跑完" in _bad(got2), False)
    check("任务都收了尾", "每个任务都收了尾" in _bad(got2), False)
    check("已恢复的截图不算故障", _bad(got2), [])
    check("但截图仍如实列出",
          any("出错截图" in c.label for c in got2), True)

    print("\n=== 万能跳转失败：跑完了也照样算故障 ===")
    got3 = outcome.maaend_checks(HISTORY + "\n" + APP, STUCK)
    check("SceneAnyEnterWorld 一律算故障", "界面没卡住" in _bad(got3), True)
    check("告警里带截图名",
          "SceneAnyEnterWorld" in (outcome.summarize(got3, "MaaEnd") or ""), True)

    print("\n=== 有任务开了没收尾 → 要报 ===")
    got4 = outcome.maaend_checks(
        "[x] 任务开始: 基质刷取\n" + APP, [])
    check("悬空任务被抓出来", "每个任务都收了尾" in _bad(got4), True)

    print("\n=== _maaend_app_log 真的能读到那句 ===")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "debug"
        d.mkdir(parents=True)
        (d / "2026-08-29-7.log").write_text(APP, encoding="utf-8")
        (d / "maafw.log").write_text("框架日志，不该被读进来\n", encoding="utf-8")
        started = datetime.now() - timedelta(hours=1)
        txt = engine._maaend_app_log(Path(td), started)
        check("读到了收尾标记", "自动执行任务完成" in txt, True)
        check("没把框架日志混进来", "框架日志" in txt, False)

    print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
