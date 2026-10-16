"""失败证据要存对：AUTO-MAS 那一轮的记录必须带上，日志对不上要出声。

2026-09-05：MaaEnd 基质刷取第一次失败、重试成功。中继 10:00:45 才落账，
那时 MaaEnd 已经重启过、debug 目录被它自己清空重写，于是存下来的
maafw.log 只覆盖 09:57–09:59——**那是重试成功那次**，证据目录名却是失败那次
（MaaEnd-05-27-42）。查了半天才发现拿错了日志。

两条修复：
1. 同时存 AUTO-MAS `history/<run_id>.log/.json`——它按 run_id 取，必然对得上，
   当天正是靠那份 .json 才看出失败的是「基质刷取」。
2. 存下来的 debug 日志若最后写入时刻早于这一轮开始时刻，就是别轮的，记一行说明。

2026-10-15 16:34 / 18:18: that note was a WARNING, and errwatch pushes every ark.*
WARNING to the group as 「🩺 中继自己报错了」 - two pushes per failed run that wrote
no debug log of its own (handle.py archives the two newest debug logs, both from
an earlier round). The note is correct and not a relay fault; the failure itself
reaches the group as ❌. So it is INFO now, and only a crashed check stays WARNING.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _tmp import tmpdir

fails = []


import logging  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.alarm import errwatch, handle  # noqa: E402


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []           # (levelno, message)

    def emit(self, record):
        self.lines.append((record.levelno, record.getMessage()))


def _run_check(started, files, ew=None):
    """Records _warn_if_evidence_stale logs for debug logs {name: mtime}, captured from INFO up.

    `ew`, when given, is an errwatch handler attached to the "ark" logger for the call,
    as the relay attaches it (errwatch.install)."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="arktest-stale-"))
    for name, mtime in files.items():
        f = d / name
        f.write_text("x", encoding="utf-8")
        os.utime(f, (mtime.timestamp(), mtime.timestamp()))
    grab = _Grab()
    ark = logging.getLogger(errwatch.ARK)
    level = ark.level
    ark.setLevel(logging.INFO)    # the relay logs at INFO (__main__.py basicConfig)
    handle.log.addHandler(grab)
    if ew is not None:
        ark.addHandler(ew)
    try:
        rec = SimpleNamespace(run_id="2026-10-12/endfield/MaaEnd-06-58-38", started=started)
        handle._warn_if_evidence_stale(None, rec, d)
    finally:
        if ew is not None:
            ark.removeHandler(ew)
        handle.log.removeHandler(grab)
        ark.setLevel(level)
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
    return grab.lines


def _stale_notes(started, mtime, name="2026-10-12-3.log"):
    """Messages for one debug log last written at `mtime`; also checks nothing reached WARNING."""
    got = _run_check(started, {name: mtime})
    loud = [m for lv, m in got if lv >= logging.WARNING]
    if loud:
        fails.append(f"别轮日志的说明不是中继故障，不该到 WARNING（errwatch 会推进群）：{loud}")
    return [m for _, m in got]


# The run_id stem is AUTO-MAS's clock (UTC+4: collector.AUTOMAS_NAME_TZ), not the
# server's: MaaEnd-06-58-38 started 2026-10-12 10:59:40 Beijing (ledger-2026-10-12).
# A debug log last written 10:58:09 - the round before - must be flagged. Until
# 2026-10-13 the check compared the stem's 06:58:38 with 10:58:09 and said nothing
# (audit s7 #3).
START = datetime(2026, 10, 12, 10, 59, 40, tzinfo=SERVER_TZ)
got = _stale_notes(START, datetime(2026, 10, 12, 10, 58, 9, tzinfo=SERVER_TZ))
if not any("别的轮次" in x for x in got):
    fails.append(f"上一轮写的 debug 日志没被标出来：{got}")
# Written during the round: nothing logged.
got = _stale_notes(START, START + timedelta(minutes=3))
if got:
    fails.append(f"这一轮写的 debug 日志被误标：{got}")
# The previous day's log, written later in the day than this round's start: flagged.
got = _stale_notes(START, datetime(2026, 10, 11, 21, 0, tzinfo=SERVER_TZ))
if not any("别的轮次" in x for x in got):
    fails.append(f"前一天的 debug 日志没被标出来：{got}")
# AUTO-MAS's own copy is taken by run_id: never flagged.
got = _stale_notes(START, datetime(2026, 10, 12, 10, 58, 9, tzinfo=SERVER_TZ), "automas-MaaEnd-06-58-38.log")
if got:
    fails.append(f"按 run_id 取的 AUTO-MAS 日志被误标：{got}")

# The 2026-10-15 16:34 shape (COS daily/relay-2026-10-15.log:1204-1205): MaaEnd found
# no task and wrote no debug log, so both archived debug logs were the previous
# round's. Two INFO notes, nothing at WARNING - before this, two WARNINGs and two
# 「🩺 中继自己报错了」 pushes 3 s apart.
START_1015 = datetime(2026, 10, 15, 16, 34, 25, tzinfo=SERVER_TZ)
SHAPE_1015 = {"go-service.log": datetime(2026, 10, 15, 16, 28, 30, tzinfo=SERVER_TZ),
              "maafw.log": datetime(2026, 10, 15, 16, 28, 29, tzinfo=SERVER_TZ),
              "automas-MaaEnd-12-34-25.log": datetime(2026, 10, 15, 16, 34, 26, tzinfo=SERVER_TZ)}
got = _run_check(START_1015, SHAPE_1015)
info = [m for lv, m in got if lv == logging.INFO and "别的轮次" in m]
loud = [m for lv, m in got if lv >= logging.WARNING]
if len(info) != 2 or loud:
    fails.append(f"10-15 那种两份别轮日志：要 2 行 INFO、0 行 WARNING，实际 INFO {len(info)} 行、WARNING {loud}")
if any("多半" in m for _, m in got):
    fails.append(f"说明里还有「多半」（时间比过了，就是别轮的）：{got}")


# End to end with errwatch attached the way the relay attaches it: the 10-15 shape
# queues nothing for the group; a crashed check (still a WARNING) is queued - the
# positive control that shows this harness would see a push.
class _Refuses:
    """errwatch's notifier: the group refuses, so whatever it queues stays readable in pending()."""

    def send_group(self, title, body):
        return ["企业微信机器人：拒收"]

    def send(self, title, body, **kw):
        return ["拒收"]


def _errwatch():
    return errwatch.ErrorKindAlert(_Refuses(), state_dir=tmpdir("arktest-ew-"),
                                   known={}, retry=(3600.0,), fallback_after=3600.0)


ew = _errwatch()
try:
    _run_check(START_1015, SHAPE_1015, ew)
    queued = [x.get("line") for x in ew.pending()]
    if queued:
        fails.append(f"10-15 那种别轮日志说明被 errwatch 排进群（🩺 中继自己报错了）：{queued}")
finally:
    ew.close()
ew = _errwatch()
try:
    got = _run_check(None, SHAPE_1015, ew)      # started=None: the check itself crashes
    queued = [str(x.get("line")) for x in ew.pending()]
    if not any(lv == logging.WARNING and "证据时间范围检查失败" in m for lv, m in got):
        fails.append(f"检查本身出错时要留 WARNING：{got}")
    if not any("证据时间范围检查失败" in q for q in queued):
        fails.append(f"检查本身出错时 errwatch 要排进群：{queued}")
finally:
    ew.close()

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
