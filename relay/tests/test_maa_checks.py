"""MAA 的结果核对——2026-08-30 之前这里是个洞。

`_verify_outcome` 走到 MAA 直接 return None，也就是「全干成」。
于是 MAA 只要进程正常退出就恒为绿，里面基建整个跪掉也照样报全绿。
用户 08-29 到 08-30 连着两天在通知里看到的「全绿」就是这么来的。

样本取自 08-29 晚班和 08-30 早班的真实 asst.log。
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.engine import _maa_app_log  # noqa: E402
from ark_relay.outcome import maa_checks, summarize  # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


# 08-29 晚班真实片段（时间戳和进程号保留原样）
REAL_FAIL = """\
[2026-08-29 21:36:20.513][INF][Px17480][Tx23596] InfrastInfoTask | zoom gesture sent
[2026-08-29 21:38:59.770][INF][Px17480][Tx23596] SubTaskError {"first":["Infrast
[2026-08-29 21:42:02.957][ERR][Px17480][Tx23596] asst::InfrastAbstractTask::click_clear_button clear failed
[2026-08-29 21:42:19.383][TRC][Px17480][Tx23596] asst::InfrastAbstractTask::on_run_fails | enter
[2026-08-29 21:42:21.389][TRC][Px17480][Tx23596] asst::InfrastAbstractTask::on_run_fails | leave, 2006 ms
[2026-08-29 21:43:00.000][ERR][Px17480][Tx23596] Unknown task: FightSeries-OldMethodFlag
"""

CLEAN = """\
[2026-08-30 09:09:41.495][INF][Px9556][Tx53843] InfrastInfoTask | zoom gesture sent
[2026-08-30 09:12:00.000][INF][Px9556][Tx53843] Task Infrast completed
"""


def main():
    print("基建失败必须报出来（这是全绿的根因）")
    got = maa_checks(REAL_FAIL)
    check("基建掉进恢复流程要报出来",
          any(c.label.startswith("基建") and not c.ok for c in got), True)
    check("summarize 不再返回 None", summarize(got, "MAA") is not None, True)
    check("找不到的任务定义也报",
          any("任务定义" in c.label and not c.ok for c in got), True)

    print("干净的一轮不许误报")
    got2 = maa_checks(CLEAN)
    check("全绿", summarize(got2, "MAA"), None)

    print("技能识别大量失败要单独说，但少量不报")
    blind_many = CLEAN + "skill has no recognition result\n" * 20
    got3 = maa_checks(blind_many)
    check("20 次判失败",
          any("技能" in c.label and not c.ok for c in got3), True)
    blind_few = CLEAN + "skill has no recognition result\n" * 2
    check("2 次不报", summarize(maa_checks(blind_few), "MAA"), None)

    print("基建失败时把识别次数一起带上，不另开一条")
    got4 = maa_checks(REAL_FAIL + "skill has no recognition result\n" * 20)
    infra = [c for c in got4 if c.label.startswith("基建")][0]
    check("detail 里带识别次数", "20 次" in infra.detail, True)
    check("detail 说清不是整条链死掉", "不是整条链死掉" in infra.detail, True)
    check("不重复开一条技能项",
          sum(1 for c in got4 if "技能" in c.label), 0)

    print("_maa_app_log 只取本轮时间窗内的行")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        dbg = Path(d) / "debug"
        dbg.mkdir()
        (dbg / "asst.log").write_text(
            "[2026-08-29 21:42:19.383][TRC] asst::InfrastAbstractTask::on_run_fails | enter\n"
            "[2026-08-30 09:09:41.495][INF] InfrastInfoTask | zoom gesture sent\n",
            encoding="utf-8")
        got5 = _maa_app_log(d, datetime(2026, 8, 30, 9, 0, 0))
        check("上一轮的失败不会算到这一轮头上",
              "on_run_fails" in got5, False)
        check("本轮的行留下了", "zoom gesture sent" in got5, True)
        check("目录没配就返回空", _maa_app_log(None, datetime.now()), "")

    print("续行跟着上一条时间戳走，不单独判断")
    with tempfile.TemporaryDirectory() as d:
        dbg = Path(d) / "debug"
        dbg.mkdir()
        (dbg / "asst.log").write_text(
            "[2026-08-29 21:42:19.383][TRC] old\n"
            "  Traceback 续行属于上面那条\n"
            "[2026-08-30 09:09:41.495][INF] new\n"
            "  这条续行属于本轮\n",
            encoding="utf-8")
        got6 = _maa_app_log(d, datetime(2026, 8, 30, 9, 0, 0))
        check("旧的续行不带进来", "属于上面那条" in got6, False)
        check("新的续行带进来", "属于本轮" in got6, True)

    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
