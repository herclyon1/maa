"""MAA 的结果核对——2026-08-30 之前这里是个洞，第一版判据又太吵。

洞：`_verify_outcome` 走到 MAA 直接 return None（=全干成），
所以 MAA 只要进程正常退出就恒为绿。

太吵：第一版按错误字符串计数判，拿真实日志空跑时 08-29 晚和 08-30 早
**两趟都会被推送**，推的还是已确认无害的噪音。换成结构化判据：
每条任务链都该有一对 TaskChainStart / TaskChainCompleted。
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.handle import _maa_app_log  # noqa: E402
from ark_relay.outcome import maa_checks, summarize  # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


CHAINS = ["StartUp", "Fight", "Infrast", "Recruit", "Mall", "Award", "CloseDown"]


def run(chains=CHAINS, *, drop_end=(), error=(), stopped=(), extra=""):
    """造一段 asst.log：每条链一对 Start/Completed，可指定谁不收尾/谁报错。"""
    out = []
    for c in chains:
        out.append(f'[2026-08-30 09:00:00][INF] TaskChainStart '
                   f'{{"taskchain":"{c}","taskid":1}}')
        if c in error:
            out.append(f'[2026-08-30 09:10:00][INF] TaskChainError '
                       f'{{"taskchain":"{c}","taskid":1}}')
        elif c in stopped:
            out.append(f'[2026-08-30 09:10:00][INF] TaskChainStopped '
                       f'{{"taskchain":"{c}","taskid":1}}')
        elif c not in drop_end:
            out.append(f'[2026-08-30 09:10:00][INF] TaskChainCompleted '
                       f'{{"taskchain":"{c}","taskid":1}}')
    return "\n".join(out) + extra


def main():
    print("正常一轮：七条链各一对，不许推送")
    check("全绿", summarize(maa_checks(run()), "MAA"), None)

    print("已确认无害的噪音不许把它变成告警")
    noisy = run(extra="\n[2026-08-30 09:05:00][ERR] skill has no recognition result" * 21
                      + "\n[2026-08-30 09:05:00][ERR] Unknown task: FightSeries-OldMethodFlag" * 10
                      + "\n[2026-08-30 09:06:00][TRC] asst::InfrastAbstractTask::on_run_fails | enter")
    check("噪音再多也全绿", summarize(maa_checks(noisy), "MAA"), None)

    print("开了没收尾——这才是「队列卡死、自己不吭声」的形状")
    got = maa_checks(run(drop_end=("Infrast",)))
    check("判失败", any(c.label == "每条任务链都收了尾" and not c.ok for c in got), True)
    check("说出是哪条链",
          any("Infrast" in c.detail for c in got if not c.ok), True)

    print("任务链报错 / 被中止")
    check("Error 判失败",
          any(not c.ok for c in maa_checks(run(error=("Fight",)))), True)
    check("Stopped 判失败",
          any(not c.ok for c in maa_checks(run(stopped=("Mall",)))), True)

    print("一条任务链事件都没有 = 窗口切错，不许当成没问题")
    got2 = maa_checks("随便什么日志，没有 TaskChain")
    check("判失败", any(not c.ok for c in got2), True)
    check("空文本同样不许全绿", summarize(maa_checks(""), "MAA") is not None, True)

    print("_maa_app_log 的切窗：起点和终点都要管")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        dbg = Path(d) / "debug"
        dbg.mkdir()
        (dbg / "asst.log").write_text(
            "[2026-08-29 21:42:19][TRC] 上一趟\n"
            "  上一趟的续行\n"
            "[2026-08-30 09:09:41][INF] 本趟\n"
            "  本趟的续行\n"
            "[2026-08-30 23:00:00][INF] 下一趟\n",
            encoding="utf-8")
        got3 = _maa_app_log(d, datetime(2026, 8, 30, 9, 0),
                            datetime(2026, 8, 30, 10, 0))
        check("上一趟不带进来", "上一趟" in got3, False)
        check("上一趟的续行也不带", "上一趟的续行" in got3, False)
        check("本趟带进来", "本趟" in got3, True)
        check("本趟的续行带进来", "本趟的续行" in got3, True)
        check("下一趟不带进来（这就是没有上界时的 bug）", "下一趟" in got3, False)

        no_top = _maa_app_log(d, datetime(2026, 8, 30, 9, 0))
        check("不给上界时下一趟会进来（duration_known=False 时的取舍）",
              "下一趟" in no_top, True)

        check("目录没配返回 None（不是空串——空串会被判据当成全绿）",
              _maa_app_log(None, datetime(2026, 1, 1)), None)
        check("窗口内一行都没有也返回 None",
              _maa_app_log(d, datetime(2030, 1, 1)), None)

    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
