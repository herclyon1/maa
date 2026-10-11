#!/usr/bin/env python3
"""Read the relay's technical log on the game machine; mark its red items handled.

    scripts/mac/techlog.py red [--days N]          unhandled red items, last N Beijing days (default 3)
    scripts/mac/techlog.py show <YYYY-MM-DD>        one day's file
    scripts/mac/techlog.py handled <id> <commit>    mark a red item handled, then re-read to confirm

The log is ours, not the user's: after the daily report was slimmed down the technical
findings live only there (the user, 2026-10-10 22:47, relayed by the acceptance session:
「报错那些什么东西自己看去，我们不看的」), and a red item nobody reads is a red item
nobody fixes.

File format (written on the machine by relay/ark_relay/core/techlog.py, commit ac38f466;
the three patterns below must stay identical to that module's RED_LINE / DONE_LINE /
handled_line - relay/tests/test_techlog_tool.py compares them):

    C:\\ProgramData\\ark-relay\\tech\\YYYY-MM-DD.md       one file per Beijing day
    ## HH:MM <heading>                                    a section
    🔴 R-YYYYMMDD-HHMM-n <text>                           a red item
    ✅ R-YYYYMMDD-HHMM-n 已处理（<commit>）               it is handled (in any later file)

Every read is one `winrun.sh --py` run of a generated script (READ_SCRIPT) that takes
the date from arklog.server_today() - the machine's own clock, never the Mac's - and
returns each day's file base64-encoded, plus relay.log's last 60 minutes read through
arklog.since_minutes. One round trip: 1.1 s measured 2026-10-11, where the earlier
draft's three scp fetches plus a --py cost four.

`red` prints one line per unhandled red item, `<id>\\t<day>\\t<text>`, and exits 0.
When none of the days has a file it prints NO_LOG instead (the relay has not written
one yet - not an error). Nothing at all on stdout means the files exist and nothing is
red. A day the machine could not read (permission, decode) or a run that did not come
back prints 「技术日志没读到：<what>（<why>）」 and exits 2: a log that could not be read
must never look like a clean one.

Every command first checks, within PROBE_TIMEOUT (3 s), that the machine accepts a TCP
connection on its ssh port. When it does not (off for the night, or the network is
down) it prints 「游戏机现在连不上（关机或断网）：<why>」 and exits 3 without trying
anything else.

`red` also counts relay boots in the last 60 minutes: three or more boots without a
normal stop before each add the live item `R-LIVE-restarts` for today - a crash-looping
relay cannot be relied on to write its own red item. It needs no `handled`; it goes
once the window is clean.

`handled` appends the handled line on the machine through `winrun.sh --py` (the line
travels inside the generated file, never on a command line - winrun.sh rule), then
re-reads and exits 0 only when the item no longer shows as unhandled.

Environment (tests):
    TECHLOG_WINRUN         command used instead of scripts/mac/winrun.sh
    TECHLOG_REMOTE_DIR     the tech directory on the machine
    TECHLOG_FETCH_TIMEOUT  seconds one read may take (default 15)
    TECHLOG_PROBE          host:port the reachability probe connects to (default ARK_HOST:22)
    TECHLOG_PROBE_TIMEOUT  seconds the probe may take (default 3)
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The format - identical to relay/ark_relay/core/techlog.py (ac38f466).
RED_LINE = re.compile(r"^🔴 (R-\d{8}-\d{4}-\d+) (.*)$")
DONE_LINE = re.compile(r"^✅ (R-\d{8}-\d{4}-\d+) 已处理（(.+?)）")


def handled_line(item_id: str, commit: str) -> str:
    return f"✅ {item_id} 已处理（{commit}）"


REMOTE_DIR = os.environ.get("TECHLOG_REMOTE_DIR", r"C:\ProgramData\ark-relay\tech")
FETCH_TIMEOUT = float(os.environ.get("TECHLOG_FETCH_TIMEOUT", "15"))
WRITE_TIMEOUT = 90
PROBE = os.environ.get("TECHLOG_PROBE") or f"{os.environ.get('ARK_HOST', '100.65.39.119')}:22"
PROBE_TIMEOUT = float(os.environ.get("TECHLOG_PROBE_TIMEOUT", "3"))
UNREACHABLE = 3
READ_FAILED = 2
NO_LOG = "还没有技术日志"
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_RE = re.compile(r"^R-(\d{4})(\d{2})(\d{2})-\d{4}-\d+$")
COMMIT_RE = re.compile(r"^[0-9A-Za-z._/-]{4,64}$")
MAX_DAYS = 62

LIVE_ID = "R-LIVE-restarts"
LIVE_WINDOW_MIN = 60
LIVE_MARGIN_MIN = 15
LIVE_THRESHOLD = 3


class ReadFailed(Exception):
    """The machine answered the probe but the log could not be read."""


def winrun_cmd() -> list[str]:
    fake = os.environ.get("TECHLOG_WINRUN")
    return shlex.split(fake) if fake else [str(ROOT / "scripts" / "mac" / "winrun.sh")]


def run(args: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    """Run winrun in its own process group, so a timeout takes its ssh down too."""
    try:
        p = subprocess.Popen(winrun_cmd() + args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
    except OSError as exc:
        raise ReadFailed(f"winrun 起不来：{type(exc).__name__}") from exc
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        p.communicate()
        raise ReadFailed(f"超过 {timeout:g} 秒没回来") from None
    return p.returncode, out, err


def why_failed(out: bytes, err: bytes, rc: int) -> str:
    """The last meaningful line of a failed --py run's stdout and of its stderr."""
    def tail(b: bytes) -> "str | None":
        lines = [ln.strip() for ln in b.decode("utf-8", "replace").splitlines()
                 if ln.strip() and not ln.startswith("[机器时间]")]
        return lines[-1] if lines else None
    parts = [p for p in (tail(out), tail(err)) if p]
    return " / ".join(parts) or f"winrun 退出码 {rc}"


def run_script(name: str, text: str, timeout: float) -> tuple[int, bytes, bytes]:
    d = Path(tempfile.mkdtemp(prefix="techlog-"))
    try:
        script = d / name
        script.write_text(text, encoding="utf-8")
        return run(["--py", str(script)], timeout)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# Runs on the machine. Exact paths only (no directory walk: winrun's scan gate), the
# date from arklog (winrun's time-filter gate refuses a script's own clock reads).
READ_SCRIPT = '''\
import base64
from datetime import date, timedelta
from pathlib import Path

from arklog import RELAY_LOG, server_today, since_minutes

TECH_DIR = {tech_dir!r}
FIRST = {first!r}
BACK = {back!r}
MAX_DAYS = {max_days!r}
LIVE = {live!r}

today = server_today()
first = date.fromisoformat(FIRST) if FIRST else today - timedelta(days=BACK)
first = max(first, today - timedelta(days=MAX_DAYS - 1))
print("TECHLOG_TODAY", today.isoformat())
day = first
while day <= today:
    p = Path(TECH_DIR) / (day.isoformat() + ".md")
    try:
        if not p.is_file():
            print("TECHLOG_DAY", day.isoformat(), "-")
        else:
            print("TECHLOG_DAY", day.isoformat(), base64.b64encode(p.read_bytes()).decode("ascii"))
    except OSError as exc:
        print("TECHLOG_DAYERR", day.isoformat(), type(exc).__name__)
    day += timedelta(days=1)
if LIVE:
    keys = (("boot", "服务模式启动"), ("stop", "收到停止信号"), ("stop", "主流程已返回"))
    wide = since_minutes(RELAY_LOG, {wide}, allow_empty=True, keep_continuations=False)
    narrow = since_minutes(RELAY_LOG, {narrow}, allow_empty=True, keep_continuations=False)
    cut = len(wide) - len(narrow)
    for i, line in enumerate(wide):
        for kind, key in keys:
            if key in line:
                print("TECHLOG_EV", "in" if i >= cut else "pre", kind)
                break
print("TECHLOG_DONE")
'''


class Snapshot:
    """What one read brought back: the machine's date, each day's text (None = no file), live events."""

    def __init__(self, today: date, texts: "dict[str, str | None]", events: "list[tuple[str, str]]"):
        self.today = today
        self.texts = texts
        self.events = events


def read(*, first: "date | None" = None, back: int = 0, live: bool = False) -> Snapshot:
    """One --py run. Raises ReadFailed with every reason it saw."""
    text = READ_SCRIPT.format(tech_dir=REMOTE_DIR, first=first.isoformat() if first else None, back=back,
                              max_days=MAX_DAYS, live=live, wide=LIVE_WINDOW_MIN + LIVE_MARGIN_MIN,
                              narrow=LIVE_WINDOW_MIN)
    rc, out, err = run_script("techlog_read.py", text, FETCH_TIMEOUT)
    try:
        body = out.decode("utf-8")
    except UnicodeDecodeError:
        raise ReadFailed("输出解码失败") from None
    if rc != 0 or "TECHLOG_DONE" not in body.splitlines():
        raise ReadFailed(why_failed(out, err, rc))
    today = None
    texts: dict[str, str | None] = {}
    events: list[tuple[str, str]] = []
    bad: list[str] = []
    for line in body.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "TECHLOG_TODAY" and DAY_RE.match(parts[1]):
            today = date.fromisoformat(parts[1])
        elif len(parts) == 3 and parts[0] == "TECHLOG_DAY" and DAY_RE.match(parts[1]):
            if parts[2] == "-":
                texts[parts[1]] = None
                continue
            try:
                texts[parts[1]] = base64.b64decode(parts[2], validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                bad.append(f"{parts[1]}（内容解码失败）")
        elif len(parts) == 3 and parts[0] == "TECHLOG_DAYERR":
            bad.append(f"{parts[1]}（{parts[2]}）")
        elif len(parts) == 3 and parts[0] == "TECHLOG_EV" and parts[1] in ("in", "pre") \
                and parts[2] in ("boot", "stop"):
            events.append((parts[1], parts[2]))
    if today is None:
        bad.append("机器没报日期")
    if bad:
        raise ReadFailed("；".join(bad))
    return Snapshot(today, texts, events)


def unhandled(text: str) -> list[tuple[str, str]]:
    """(id, text) of every red item in `text` without a handled line for it (as techlog.unhandled)."""
    reds: dict[str, str] = {}
    done: set[str] = set()
    for line in text.splitlines():
        if m := RED_LINE.match(line.strip()):
            reds.setdefault(m.group(1), m.group(2))
        elif m := DONE_LINE.match(line.strip()):
            done.add(m.group(1))
    return [(i, t) for i, t in reds.items() if i not in done]


def red_ids(texts: "dict[str, str | None]") -> dict[str, str]:
    """{id: day of its red line} of every red item, handled or not."""
    where: dict[str, str] = {}
    for day in sorted(texts):
        for line in (texts[day] or "").splitlines():
            if m := RED_LINE.match(line.strip()):
                where.setdefault(m.group(1), day)
    return where


def red_items(texts: "dict[str, str | None]") -> list[tuple[str, str, str]]:
    """(id, day of its red line, text) of every unhandled red item; a handled line may sit in a later day."""
    where = red_ids(texts)
    joined = "\n".join(texts[d] or "" for d in sorted(texts))
    return [(i, where[i], t) for i, t in unhandled(joined)]


def restart_counts(events: "list[tuple[str, str]]") -> "tuple[int, int]":
    """(boots inside the window, those of them not preceded by a stop since the boot before).

    A deploy or a power-off stops the service first (「收到停止信号」, 「主流程已返回」);
    a crash does not. A boot with nothing before it in the margin gets the benefit of the doubt.
    """
    boots = unclean = 0
    stopped = True
    for where, kind in events:
        if kind == "stop":
            stopped = True
            continue
        if where == "in":
            boots += 1
            unclean += not stopped
        stopped = False
    return boots, unclean


def failed(what: str, why: str) -> int:
    print(f"技术日志没读到：{what}（{why}）")
    return READ_FAILED


def cmd_red(n_days: int) -> int:
    if not 1 <= n_days <= MAX_DAYS:
        print(f"--days 要在 1 到 {MAX_DAYS} 之间", file=sys.stderr)
        return 1
    try:
        snap = read(back=n_days - 1, live=True)
    except ReadFailed as exc:
        return failed(f"最近 {n_days} 天", str(exc))
    items = red_items(snap.texts)
    boots, unclean = restart_counts(snap.events)
    if unclean >= LIVE_THRESHOLD:
        items.append((LIVE_ID, snap.today.isoformat(),
                      f"中继最近 {LIVE_WINDOW_MIN} 分钟重启了 {boots} 次，其中 {unclean} 次不是正常停止"))
    for item_id, day, text in items:
        print(f"{item_id}\t{day}\t{text}")
    days = sorted(snap.texts)
    if not items and all(snap.texts[d] is None for d in days):
        print(f"{NO_LOG}（{days[0]}..{days[-1]} 机器上都没有文件）" if days else NO_LOG)
    if not items:
        print(f"{days[0] if days else '-'}..{days[-1] if days else '-'}: no unhandled red items; relay restarts in "
              f"the last {LIVE_WINDOW_MIN} min: {boots} ({unclean} without a stop)", file=sys.stderr)
    return 0


def cmd_show(day: str) -> int:
    if not DAY_RE.match(day):
        print("日期要写成 YYYY-MM-DD", file=sys.stderr)
        return 1
    try:
        d = date.fromisoformat(day)
    except ValueError:
        print("日期要写成 YYYY-MM-DD", file=sys.stderr)
        return 1
    try:
        snap = read(first=d, back=0)
    except ReadFailed as exc:
        return failed(day, str(exc))
    if d > snap.today:
        print(f"{day} 在机器的今天（{snap.today}）之后", file=sys.stderr)
        return 1
    if day not in snap.texts:
        print(f"{day} 比机器的今天早 {MAX_DAYS} 天以上，不读", file=sys.stderr)
        return 1
    text = snap.texts[day]
    if text is None:
        print(f"{NO_LOG}（{day} 机器上没有这天的文件）")
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


WRITE_SCRIPT = '''\
import sys
from pathlib import Path

TECH_DIR = {tech_dir!r}
DAY = {day!r}
LINE = {line!r}

p = Path(TECH_DIR) / (DAY + ".md")
if not p.is_file():
    print("TECHLOG_NO_FILE " + str(p))
    sys.exit(3)
with open(p, "rb") as fh:
    fh.seek(0, 2)
    if fh.tell():
        fh.seek(-1, 2)
        last = fh.read(1)
    else:
        last = b"\\n"
with open(p, "a", encoding="utf-8") as fh:
    fh.write(("" if last == b"\\n" else "\\n") + LINE + "\\n")
print("TECHLOG_APPENDED " + str(p))
'''


def write_handled(day: str, item_id: str, commit: str) -> "str | None":
    """Append the handled line on the machine. None when it says it did; otherwise why not."""
    text = WRITE_SCRIPT.format(tech_dir=REMOTE_DIR, day=day, line=handled_line(item_id, commit))
    try:
        rc, out, err = run_script("techlog_handled.py", text, WRITE_TIMEOUT)
    except ReadFailed as exc:
        return str(exc)
    if rc == 0 and b"TECHLOG_APPENDED" in out:
        return None
    return why_failed(out, err, rc)


def cmd_handled(item_id: str, commit: str) -> int:
    if item_id.startswith("R-LIVE-"):
        print(f"{item_id} 是从中继日志现场判的，窗口干净了自己消失，不用标", file=sys.stderr)
        return 1
    m = ID_RE.match(item_id)
    if not m:
        print(f"编号格式不对：{item_id}（应为 R-YYYYMMDD-HHMM-n）", file=sys.stderr)
        return 1
    if not COMMIT_RE.match(commit):
        print(f"提交号格式不对：{commit}", file=sys.stderr)
        return 1
    try:
        id_day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        print(f"编号里的日期不存在：{item_id}", file=sys.stderr)
        return 1
    # A check that ran just after midnight for the day before writes into that day's
    # file while its id carries the new date, so the window starts one day earlier.
    first = id_day - timedelta(days=1)
    try:
        snap = read(first=first)
    except ReadFailed as exc:
        return failed(f"{first}..", str(exc))
    if not (snap.today - timedelta(days=MAX_DAYS - 2) <= id_day <= snap.today):
        print(f"编号日期不在机器最近 {MAX_DAYS - 2} 天内：{item_id}（机器今天 {snap.today}）", file=sys.stderr)
        return 1
    open_items = {i: d for i, d, _ in red_items(snap.texts)}
    if item_id not in open_items:
        if item_id in red_ids(snap.texts):
            print(f"{item_id} 早已标过处理")
            return 0
        print(f"技术日志里没有这个红项：{item_id}", file=sys.stderr)
        return 1
    why = write_handled(open_items[item_id], item_id, commit)
    if why:
        print(f"写的时候出了问题：{why}；下面复查", file=sys.stderr)
    try:
        snap = read(first=first)
    except ReadFailed as exc:
        return failed(f"{first}..（复查）", str(exc))
    if item_id in {i for i, _, _ in red_items(snap.texts)}:
        print(f"复查没过：{item_id} 还是未处理", file=sys.stderr)
        return 1
    print(f"已标处理：{item_id}（{commit}），复查确认")
    return 0


def unreachable() -> "str | None":
    """None when the machine accepts a TCP connection on PROBE within PROBE_TIMEOUT; otherwise why not."""
    host, _, port = PROBE.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=PROBE_TIMEOUT):
            return None
    except socket.timeout:  # the Mac python3 is 3.9, where this is not yet TimeoutError
        return f"{PROBE_TIMEOUT:g} 秒内连不上 {PROBE}"
    except (OSError, ValueError) as exc:
        return f"{PROBE}：{exc.strerror if isinstance(exc, OSError) and exc.strerror else type(exc).__name__}"


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Read / mark the relay's technical log on the game machine.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("red", help="unhandled red items of the last N Beijing days")
    r.add_argument("--days", type=int, default=3)
    s = sub.add_parser("show", help="print one day's file")
    s.add_argument("day")
    h = sub.add_parser("handled", help="mark a red item handled")
    h.add_argument("id")
    h.add_argument("commit")
    a = ap.parse_args(argv)
    why = unreachable()
    if why:
        print(f"游戏机现在连不上（关机或断网）：{why}")
        return UNREACHABLE
    if a.cmd == "red":
        return cmd_red(a.days)
    if a.cmd == "show":
        return cmd_show(a.day)
    return cmd_handled(a.id, a.commit)


if __name__ == "__main__":
    sys.exit(main())
