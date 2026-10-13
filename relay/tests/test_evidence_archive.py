"""失败证据要存对：AUTO-MAS 那一轮的记录必须带上，日志对不上要出声。

2026-09-05：MaaEnd 基质刷取第一次失败、重试成功。中继 10:00:45 才落账，
那时 MaaEnd 已经重启过、debug 目录被它自己清空重写，于是存下来的
maafw.log 只覆盖 09:57–09:59——**那是重试成功那次**，证据目录名却是失败那次
（MaaEnd-05-27-42）。查了半天才发现拿错了日志。

两条修复：
1. 同时存 AUTO-MAS `history/<run_id>.log/.json`——它按 run_id 取，必然对得上，
   当天正是靠那份 .json 才看出失败的是「基质刷取」。
2. 存下来的 debug 日志若最后写入时刻早于这一轮开始时刻，就是别轮的，出警告。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

fails = []


import logging  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.alarm import handle  # noqa: E402


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _stale_warnings(started, mtime, name="2026-10-12-3.log"):
    """Warnings _warn_if_evidence_stale gives for one debug log last written at `mtime`."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="arktest-stale-"))
    f = d / name
    f.write_text("x", encoding="utf-8")
    os.utime(f, (mtime.timestamp(), mtime.timestamp()))
    grab = _Grab()
    handle.log.addHandler(grab)
    try:
        rec = SimpleNamespace(run_id="2026-10-12/endfield/MaaEnd-06-58-38", started=started)
        handle._warn_if_evidence_stale(None, rec, d)
    finally:
        handle.log.removeHandler(grab)
        f.unlink()
        d.rmdir()
    return grab.lines


# The run_id stem is AUTO-MAS's clock (UTC+4: collector.AUTOMAS_NAME_TZ), not the
# server's: MaaEnd-06-58-38 started 2026-10-12 10:59:40 Beijing (ledger-2026-10-12).
# A debug log last written 10:58:09 - the round before - must be flagged. Until
# 2026-10-13 the check compared the stem's 06:58:38 with 10:58:09 and said nothing
# (audit s7 #3).
START = datetime(2026, 10, 12, 10, 59, 40, tzinfo=SERVER_TZ)
got = _stale_warnings(START, datetime(2026, 10, 12, 10, 58, 9, tzinfo=SERVER_TZ))
if not any("别的轮次" in x for x in got):
    fails.append(f"上一轮写的 debug 日志没被标出来：{got}")
# Written during the round: no warning.
got = _stale_warnings(START, START + timedelta(minutes=3))
if got:
    fails.append(f"这一轮写的 debug 日志被误标：{got}")
# The previous day's log, written later in the day than this round's start: flagged.
got = _stale_warnings(START, datetime(2026, 10, 11, 21, 0, tzinfo=SERVER_TZ))
if not any("别的轮次" in x for x in got):
    fails.append(f"前一天的 debug 日志没被标出来：{got}")
# AUTO-MAS's own copy is taken by run_id: never flagged.
got = _stale_warnings(START, datetime(2026, 10, 12, 10, 58, 9, tzinfo=SERVER_TZ), "automas-MaaEnd-06-58-38.log")
if got:
    fails.append(f"按 run_id 取的 AUTO-MAS 日志被误标：{got}")

# 存档函数必须把 history 的两个后缀都带上
src = (pathlib.Path(__file__).resolve().parents[1]
       / "ark_relay" / "features" / "alarm" / "handle.py").read_text(encoding="utf-8")
body = src[src.index("def _archive_maaend_evidence"):]
body = body[:body.index("\ndef ", 10)] if "\ndef " in body[10:] else body
if 'history_dir' not in body:
    fails.append("存档没有带上 AUTO-MAS 的 history 记录")
for suffix in ('".log"', '".json"'):
    if suffix not in body:
        fails.append(f"存档没带 {suffix}")
if "automas-" not in body:
    fails.append("AUTO-MAS 的文件没加前缀，会和 MaaEnd 自己的日志重名")
if "_warn_if_evidence_stale" not in body:
    fails.append("存档后没有做日志时间范围检查")

# 检查函数要跳过自己按 run_id 取的那份，否则会自己警告自己
warn = src[src.index("def _warn_if_evidence_stale"):]
warn = warn[:warn.index("\ndef ", 10)]
if 'startswith("automas-")' not in warn:
    fails.append("时间检查没跳过 automas- 那几份（它们必然对得上）")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
