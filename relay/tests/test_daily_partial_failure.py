"""A run that failed one task still has to report the nineteen it finished.

Real data, 2026-09-09. Endfield ran for 1h20m: it farmed 基质 18 times, spent 1422
sanity, collected the whole daily and the pass rewards, and 据点交易 failed. AUTO-MAS
retried that one step two minutes later and it worked.

What the user received was a red run carrying one line, 「失败于：据点交易」, and a
green two-minute run with four 「—」 rows and 「日常 1-1 项完成」. Everything the long
run did was thrown away by the renderer, and there was no way to tell the day had
in fact gone fine. His words: 「这终末地通知就是一坨屎吧」.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import core

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


entries = json.loads((Path(__file__).parent / "fixtures" / "daily-2026-09-09.json")
                     .read_text(encoding="utf-8"))
title, body = core.format_daily("2026-09-09", entries)
blocks = body.split("\n\n")
long_run = next(b for b in blocks if "1h20m" in b)
retry_run = next(b for b in blocks if "2m" in b and "MaaEnd" in b)

print("[跑了 80 分钟的那趟：做过的事必须都在]")
check("说了刷什么刷了几次", "基质刷取" in long_run and "×18" in long_run)
check("说了花掉的理智", "1422" in long_run)
check("说了产出", "无暇基质" in long_run and "高纯基质" in long_run)
check("说了剩余理智", "6/360" in long_run)
check("不再只剩一行「失败于」", long_run.count("· ") >= 5)

print("[重试成功要说清楚，而且只说一次]")
check("点名是哪一项", "据点交易" in long_run)
check("说了后来做成了", "重试里做成了" in long_run)
check("没有自相矛盾的「失败」二字", "；失败" not in long_run)
check("整天判成全绿", "全绿" in title)
check("标题里点明有重试", "重试" in title)

print("[两分钟的重试那趟：一行说完，不摆四个破折号]")
check("只有一行", retry_run.count("· "), 1)
check("那一行说了做的是什么", "据点交易" in retry_run)
check("没有空占位", "—" not in retry_run)

print("[脚注取的是真正做了日常的那趟，不是两分钟那趟]")
foot = core.daily_footnote(entries)
check("列出了完整日常", foot.count(".") >= 13)
check("不是只有一项", "日常：1.据点交易" not in foot)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
