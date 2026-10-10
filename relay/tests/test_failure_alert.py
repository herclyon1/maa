"""The immediate failure alert, and the three marks nobody ever read back.

`core.format_failure` builds the message the user gets on his phone the moment
a run fails - the single most-read thing the relay produces - and no test had
ever called it. Neither had `State.interim_sent` nor
`State.mark_banner_announced`, both of which are one half of a writer/reader
pair: a mark written under one key and read back under another silently means
"never sent", and the symptom is not an error but a missing report, or the
same banner announced every hour.

What is pinned here:

* A run whose duration came from the filename must not print a duration as
  fact. That fallback is hours wrong on this install, and it is exactly the
  class of run (「未捕获到日志」) most likely to end up in a failure alert.
* Which step broke has to be visible. The daily report of 2026-08-27 lost the
  words 「失败于」 and became unreadable - a bare list of task names that could
  equally have been the list of things that ran.
* Every mark survives a restart, because the machine is hard power-cut twice a
  day and an in-memory mark is not a mark.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import texts
from ark_relay.config import SERVER_TZ, RunRecord
from ark_relay.core import State, format_failure
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


def rec(**kw):
    now = datetime(2026, 9, 8, 9, 18, tzinfo=SERVER_TZ)
    base = dict(run_id="2026-09-08/wuwa/OK-WW-09-00-00", script="OK-WW", user="wuwa",
                started=now - timedelta(minutes=18), finished=now, ok=False,
                failed_tasks=["任务执行：残象聚落"], raw={})
    base.update(kw)
    return RunRecord(**base)


print("[标题就是失败标题，脚本名原样带出去]")
title, body = format_failure(rec())
check("标题", title, texts.failed("OK-WW"))
check("正文带账号", "账号 wuwa" in body, True)

print("\n[时间可信时才写用时]")
check("写了用时 18 分钟", "用时 18 分钟" in body, True)
check("不带偏差提示", "可能有偏差" in body, False)
check("起止都在", ("09:00" in body and "09:18" in body), True)

print("\n[时间不可信时一个字都不许写成事实——文件名时间在这台机器上差好几小时]")
_, body2 = format_failure(rec(duration_known=False))
check("不写用时", "用时 18 分钟" in body2, False)
check("明说时长未知", "时长未知" in body2, True)
check("明说时间取自文件名", "时间取自文件名，不是日志" in body2, True)

print("\n[哪一步坏了必须一眼看见（08-27 丢过「失败于」三个字）]")
check("单项带「失败于」", "失败于：任务执行：残象聚落" in body, True)
_, many = format_failure(rec(failed_tasks=["一", "二", "三", "四", "五"]))
check("多项写清共几项", "失败于 5 项：" in many, True)
check("多项只列前三个", many.count("、") >= 2 and "四" not in many, True)
_, none = format_failure(rec(failed_tasks=[]))
check("一项都没有时不留空", "失败于：未知" in none, True)

print("\n[理智有就写，没有就不许凭空出现]")
_, with_sanity = format_failure(rec(raw={"sanity": 42, "sanity_full_at": "今天 21:30 回满"}))
check("写了剩余理智", "剩余理智 42" in with_sanity, True)
check("写了回满时刻", "今天 21:30 回满" in with_sanity, True)
check("没有理智就不写这行", "剩余理智" in body, False)

print("\n[诊断接在正文后面，没诊断就不加分隔线]")
_, diag = format_failure(rec(), diagnosis="游戏没到主界面")
check("诊断在正文里", diag.endswith("游戏没到主界面"), True)
check("有诊断才有分隔线", "─" in diag and "─" not in body, True)

print("\n[三个标记：写进去，换一个实例读回来还在（机器一天硬断电两次）]")
d = tmpdir()
st = State(d)
check("没写过时临时日报没发过", st.interim_sent("2026-09-08"), False)
st.mark_interim_sent("2026-09-08", covered=7)
check("写完读回来算发过", State(d).interim_sent("2026-09-08"), True)
check("覆盖条数读得回来", State(d).interim_covered("2026-09-08"), 7)
check("别的日子不受影响", State(d).interim_sent("2026-09-07"), False)

check("没写过时卡池没播报过", st.banner_announced("鸣潮|2026-09-10 10:00"), False)
st.mark_banner_announced("鸣潮|2026-09-10 10:00")
check("写完读回来算播报过", State(d).banner_announced("鸣潮|2026-09-10 10:00"), True)
check("另一个游戏同一天不算", State(d).banner_announced("终末地|2026-09-10 10:00"), False)

st.mark_report_sent("2026-09-08")
check("日报标记独立于临时日报", (State(d).report_sent("2026-09-08"),
                                State(d).report_sent("2026-09-09")), (True, False))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
