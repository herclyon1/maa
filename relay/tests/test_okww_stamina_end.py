"""结束时的剩余波片要认 OK-WW 自己报的那个数。

2026-08-28 那轮实际把体力刷到 0，报告却写「剩余波片 80/240」。
原因是我们取 `info_set current_stamina` 的最后一条，而那是**每轮开打前**
记的；之后又刷了一轮但不再记数，所以永远多算一轮。

用户当场指出两件事：一是这轮其实刷干净了、是我们误报；二是「用尽」并不等于 0，
OK-WW 的判定是「剩余不足以再开一次」，而单次消耗还会在 40/80 之间自动切换，
外部根本推算不出来。

好在 OK-WW 停手时自己会打一行 `current stamina: N not enough to continue`，
那才是结束时的真实余量。下面这段日志是 2026-08-28 的原文。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import collector  # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


REAL = """
2026-08-28 13:40:57,971 INFO TaskExecutor ForgeryTask:info_set current_stamina 240
2026-08-28 13:41:59,293 INFO TaskExecutor BaseWWTask:当前体力大于等于双倍, 240 >= 80
2026-08-28 13:42:49,641 INFO TaskExecutor ForgeryTask:info_set current_stamina 160
2026-08-28 13:42:49,641 INFO TaskExecutor BaseWWTask:当前体力大于等于双倍, 160 >= 80
2026-08-28 13:43:40,617 INFO TaskExecutor ForgeryTask:info_set current_stamina 80
2026-08-28 13:43:40,618 INFO TaskExecutor BaseWWTask:当前体力大于等于双倍, 80 >= 80
2026-08-28 13:43:44,857 INFO TaskExecutor BaseWWTask:current stamina: 0 not enough to continue
2026-08-28 13:43:48,859 INFO TaskExecutor ForgeryTask:used all stamina
2026-08-28 13:44:57,176 INFO TaskExecutor DailyTask:Daily Task Completed
"""

NO_END_LINE = "\n".join(
    l for l in REAL.splitlines() if "not enough to continue" not in l)

NEST = """
2026-08-29 00:21:27,418 INFO TaskExecutor NightmareNestTask:Box(name='已击败残象：26/41', x=890) is not complete
2026-08-29 00:23:27,182 INFO TaskExecutor NightmareNestTask:nightmare nest: 指定点位都已打满，跳过
"""


def _parse(text):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "OK-WW.log"
        f.write_text(text, encoding="utf-8")
        return collector.parse_okww_log(f)


def main() -> int:
    print("=== 08-28 的真实日志 ===")
    out = _parse(REAL)
    check("剩余取 OK-WW 自己报的 0，不是开打前的 80",
          out.get("okww_stamina_left"), 0)
    check("标明这是精确值", out.get("okww_stamina_left_exact"), True)

    print("\n=== 没有收尾那行时，退回旧读数但要标明不精确 ===")
    out2 = _parse(NO_END_LINE)
    check("退回最后一条开打前读数", out2.get("okww_stamina_left"), 80)
    check("标明不是结束余量", out2.get("okww_stamina_left_exact"), False)

    print("\n=== 残象聚落进度 ===")
    out3 = _parse(NEST)
    check("抓到 26/41", out3.get("okww_nest"), "26/41")
    check("抓到已打满", out3.get("okww_nest_full"), True)

    print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
