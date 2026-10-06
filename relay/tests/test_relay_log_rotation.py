"""relay.log is rotated by size, and every reader still sees across the rotation (review of 2026-10-07, item 3).

relay.log was a plain FileHandler and only ever grew. Pinned here:

* _setup_logging gives relay.log a rotating handler with a size limit.
* A rotation that Windows refuses (another handle holds relay.log open) loses no
  record: the handler keeps writing to the current file, says so, and rotates
  on a later try.
* The five readers that seek to the tail of relay.log (daily upload, evidence
  slice, the two machine-check readers, the daily self-check) still find lines
  that a rotation just moved into relay.log.1 - the boot checks' "previous
  session" is exactly the part a rotation at boot would cut off.
"""
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import __main__ as relay_main
from ark_relay import error_evidence, evidence, selfcheck
from ark_relay.config import SERVER_TZ
from ark_relay.machinechecks import runs as mc_runs, system as mc_system

try:
    from ark_relay import logfile
except ImportError:          # before the fix: there is no rotating handler at all
    logfile = None

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}（要 {want!r}）" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


print("[_setup_logging：relay.log 用带大小上限的轮转 handler]")
d = tmpdir()
root = logging.getLogger()
saved_handlers = root.handlers[:]
root.handlers.clear()
os.environ["ARK_LOG_FILE"] = str(d / "relay.log")
try:
    relay_main._setup_logging(verbose=False)
    files = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
    check("有一个写文件的 handler", len(files), 1)
    h = files[0] if files else None
    check("它会轮转", isinstance(h, logging.handlers.RotatingFileHandler), True)
    check("有大小上限", getattr(h, "maxBytes", 0) > 0, True)
    check("留了旧文件", getattr(h, "backupCount", 0) > 0, True)
    check("上限至少 8 MB（日志一天约 46 KB，轮转要很少见）", getattr(h, "maxBytes", 0) >= 8 * 1024 * 1024, True)
finally:
    for h in root.handlers:
        h.close()
    root.handlers[:] = saved_handlers

print("\n[真的会轮转：超过上限就挪到 relay.log.1，新内容写进新的 relay.log]")
if logfile is None:
    check("有 ark_relay.logfile", False, True)
else:
    d = tmpdir()
    lg = logging.getLogger("ark.test_relay_log_rotation")
    lg.propagate = False
    h = logfile.RelayLogHandler(d / "relay.log", max_bytes=2000, backups=2)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s", "%m-%d %H:%M:%S"))
    lg.addHandler(h)
    for i in range(60):
        lg.warning("line %03d %s", i, "x" * 40)
    check("relay.log.1 出现了", (d / "relay.log.1").exists(), True)
    check("relay.log 没超过上限太多", (d / "relay.log").stat().st_size < 2000 + 200, True)
    check("最后一行在 relay.log 里", "line 059" in (d / "relay.log").read_text(encoding="utf-8"), True)
    check("只留两份旧的", (d / "relay.log.3").exists(), False)

    print("\n[Windows 不让改名（有人开着 relay.log）：一行都不许丢，过后再轮转]")
    lg.removeHandler(h)
    h.close()
    d = tmpdir()
    h = logfile.RelayLogHandler(d / "relay.log", max_bytes=2000, backups=2)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s", "%m-%d %H:%M:%S"))
    lg.addHandler(h)
    real_rotate = h.rotate

    def locked(src, dst):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")
    h.rotate = locked
    for i in range(60):
        lg.warning("held %03d %s", i, "y" * 40)
    text = (d / "relay.log").read_text(encoding="utf-8")
    check("60 行全在 relay.log 里", sum(f"held {i:03d}" in text for i in range(60)), 60)
    check("说了轮转没成", "轮转没成" in text, True)
    check("没有 relay.log.1（确实没改成名）", (d / "relay.log.1").exists(), False)
    h.rotate = real_rotate
    h._retry_at = time.monotonic() - 1          # the retry is due
    lg.warning("after the lock")
    check("锁放开后轮转成了", (d / "relay.log.1").exists(), True)
    check("轮转后新行在新文件里", "after the lock" in (d / "relay.log").read_text(encoding="utf-8"), True)
    lg.removeHandler(h)
    h.close()

print("\n[刚轮转过：读日志的五处都还读得到 relay.log.1 里的那一段]")
# Midday stamps: relay.log has no zone and _line_ts reads it on this computer's
# clock (Beijing on the machine, Tokyo here), so stamps near midnight would land
# on another day here.
now = datetime.now(tz=SERVER_TZ)
md = now.strftime("%m-%d")
d = tmpdir()
log_path = d / "relay.log"
older = (f"{md} 12:10:00 INFO    ark.service  中继代码版本 v1\n"
         f"{md} 12:20:00 INFO    ark.engine  本轮已处理完毕，60 秒后关机\n"
         f"{md} 12:20:30 INFO    ark.service  服务停止\n")
newer = f"{md} 12:30:00 INFO    ark.service  服务模式启动，监视 x\n"
Path(f"{log_path}.1").write_text(older, encoding="utf-8")
log_path.write_text(newer, encoding="utf-8")
os.environ["ARK_LOG_FILE"] = str(log_path)

day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
data, _ = error_evidence._day_tail(log_path, day_start, now.replace(hour=23, minute=59, second=59), 10_000)
check("每日上传带上了轮转前的那一段", "本轮已处理完毕" in data.decode("utf-8"), True)
check("每日上传也带上了新的", "服务模式启动" in data.decode("utf-8"), True)

win = (day_start.timestamp(), now.replace(hour=23, minute=59, second=59).timestamp())
out = evidence.slice_log(log_path, win, d / "slice" / "relay.log")
check("证据切片带上了轮转前的那一段", out is not None and "本轮已处理完毕" in out.read_text(encoding="utf-8"), True)

check("上机核对读得到轮转前的那一段", "本轮已处理完毕" in mc_system.read_tail(str(log_path)), True)
check("上机核对（跑次）读得到轮转前的那一段",
      any("本轮已处理完毕" in ln for ln in mc_runs._relay_today(now)), True)

calls = []
real_lines = selfcheck.daily_lines
selfcheck.daily_lines = lambda day, text: calls.append(text) or []
try:
    selfcheck.daily_section(now.strftime("%Y-%m-%d"), str(log_path))
finally:
    selfcheck.daily_lines = real_lines
check("每日体检读得到轮转前的那一段", bool(calls) and "本轮已处理完毕" in calls[0], True)

print("\n[没轮转过：照旧只读 relay.log，不多也不少]")
d = tmpdir()
only = d / "relay.log"
# Bytes, not text: tail_bytes returns the file's bytes as they are, and a text-mode
# write translates each "\n" to os.linesep (docs.python.org/3/library/io.html#io.TextIOWrapper),
# \r\n on Windows - both checks below failed there (Windows CI 2026-10-07, run 37519943859).
only.write_bytes(newer.encode("utf-8"))
if logfile is not None:
    got, cut = logfile.tail_bytes(only, 10_000)
    check("内容不变", got.decode("utf-8"), newer)
    check("没有被截", cut, False)
    got, cut = logfile.tail_bytes(only, 10)
    check("只要尾巴时只给尾巴", got, newer.encode("utf-8")[-10:])
    check("说了前面还有", cut, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
