"""Offline replay of the outcome / errwatch judgements - the deploy gate E1.

Before a deploy, the recent relay.log and the evidence-package logs are run
through *this* version's outcome and errwatch offline, and every group push the
current code would have sent is counted. Any push refuses the deploy. The point
is the 2026-10-06 false alarms: the OK-WW weekly waveplate shortage (an update
note matched 「结晶波片不足」), the banner calendar #2 machine check, and the
shutdown snapshot read. Replaying those logs with the old code pushes; with
this code it does not.

Two judgements, two replayers:

* ``okww_pushes(text)`` replays outcome over one OK-WW run log - the real code
  (``outcome.okww_checks`` + ``outcome.summarize``), exactly what
  ``engine._verify_outcome`` runs. Faithful by construction.
* ``errwatch_pushes(text)`` replays a relay.log through the real errwatch
  handler (``errwatch.ErrorKindAlert``; a push is a record that reaches its
  ``_take``). The log text alone cannot be fed to it: whether a line was
  recovered, or is logged at all, is decided by the code that wrote it, not by
  its words. So each WARNING / ERROR line of a known 10-06 false alarm is routed
  to the producer that wrote it, and that producer runs again, now, with the
  inputs of that moment (``_PRODUCERS``): the WuWa calendar reader
  (``wuwa._wuwa_calendar_start`` with the time already given by another source,
  as ``_wuwa_second_half`` passes it), machine check #2 through
  ``machinecheck.judge`` on the trace it left, and ``snapshot.read`` while the
  relay's own power-off is under way. What the handler takes is what this
  version would push. Every other WARNING / ERROR line is a push as written:
  nothing in this version is known to keep it quiet. Until 2026-10-13 the
  quiet lines were a hand list of wordings (``_QUIET``), so a change that
  brought those false alarms back still passed the gate.

The deploy script (``scripts/mac/deploy-relay.sh``) runs the module's ``main``
over the checked-in false-alarm fixtures (and any ``$REPLAY_LOGS`` the deployer
adds) before it pushes; any push stops the deploy.
"""
from __future__ import annotations

import logging
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# A relay.log line: 「MM-DD HH:MM:SS LEVEL  ark.name  message」. LEVEL is padded
# with spaces to the width of WARNING; the name is always an ark.* logger. The
# bare 「diag:」 and traceback lines have no leading timestamp and are skipped.
_LINE = re.compile(r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+(WARNING|ERROR)\s+(ark\.[\w.]+)\s+(.*)$")

# The 10-06 lines of the WuWa calendar read (all three come out of one
# _wuwa_calendar_start call, and the #2 machine check judges its trace).
_CAL_MISS = re.compile(r"^鸣潮 (\S+) 版本活动日历读了 \d+ 行，没找到「(.+?)」的日期：(.*)$")
_CAL_IMG = re.compile(r"^这条公告只有图，没读到字：.*activity id=(\d+)「(\S+?)版本活动日历」(\S+)")
_CAL_FAIL = re.compile(r"^鸣潮版本活动日历读图失败")
_MC2 = re.compile(r"^🔬 上机核对没过：#2\b")
# The 10-06 06:21 shutdown snapshot lines, written after the relay's own power-off.
_SNAP = re.compile(r"^快照的 (_MAS错误|_队列错误) 这一段读不到")


class _Taken(list):
    """The records the real errwatch handler would queue for the group."""


def _handler(state_dir: Path):
    """A real ErrorKindAlert whose queue is this list: a record that reaches _take is a push."""
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415

    class _NoSend:
        def send(self, *_a, **_k):
            return []

    h = errwatch.ErrorKindAlert(_NoSend(), state_dir=state_dir, known={})
    taken = _Taken()
    h._take = lambda record: taken.append(record)
    return h, taken


def _replay_calendar(miss: "re.Match | None", img: "re.Match | None") -> None:
    """The 10-06 06:20:17 calendar read again, as this version runs it: another source
    (the first banner's end + 1 min) had already given the second half's time, so
    _wuwa_second_half passes notes=None. The image reader returns the 78 OCR lines
    the log quoted. Then machine check #2 judges the trace through judge()."""
    from types import SimpleNamespace  # noqa: PLC0415

    from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
    from ark_relay.features.banners import banners as hub  # noqa: PLC0415
    from ark_relay.features.selfcheck import machinecheck as mc  # noqa: PLC0415

    ver = (miss and miss.group(1)) or (img and img.group(2)) or "3.7"
    pool = (miss and miss.group(2)) or "余心所向九死未悔"
    nid = (img and img.group(1)) or "50868"
    url = (img and img.group(3)) or "https://example.invalid/cal.png"
    words = (miss.group(3).split(" / ") if miss else [])
    ocr = [SimpleNamespace(text=w, x=0, y=40 * i, w=10 * len(w), h=30) for i, w in enumerate(words)]
    notice = {"activity": [{"id": nid, "tabTitle": f"{ver}版本活动日历", "startTimeMs": "1790712000000",
                            "content": f'<p><img src="{url}" alt="" width="1080" height="2159"></p>'}]}
    now = datetime(2026, 10, 6, 6, 20, 17, tzinfo=SERVER_TZ).replace(tzinfo=None)
    end = datetime(2026, 10, 22, 9, 59)
    tr = hub.Trace.new()
    hub._wuwa_calendar_start(notice, pool, now, end, lambda _url: ocr, None, tr)
    mc.load()
    only = {"#2": mc.CHECKS["#2"]}
    saved = dict(mc.CHECKS)
    mc.CHECKS.clear()
    mc.CHECKS.update(only)
    try:
        with tempfile.TemporaryDirectory() as td:
            mc.judge(td, "banners", {"trace": tr, "now": now}, notifier=None)
    finally:
        mc.CHECKS.clear()
        mc.CHECKS.update(saved)


def _replay_snapshot(labels: "set[str]") -> None:
    """The 10-06 06:21 snapshot read again, as this version runs it: the relay's own
    power-off is under way (what boot_stages wires into errwatch), and the AUTO-MAS
    sections that failed then fail the same way (its backend being torn down)."""
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    from ark_relay.features.phone import snapshot  # noqa: PLC0415

    def refused(_out):
        raise ConnectionRefusedError("AUTO-MAS backend going away")

    names = {"_MAS错误": "_mas", "_队列错误": "_queues"}
    saved = {n: getattr(snapshot, n) for n in ("_mas", "_queues", "_okww", "_runtime")}
    probe = errwatch._relay_poweroff[0]
    try:
        for label, n in names.items():
            setattr(snapshot, n, refused if label in labels else (lambda _out: None))
        snapshot._okww = snapshot._runtime = lambda _out: None
        errwatch._relay_poweroff[0] = lambda: True
        snapshot.read()
    finally:
        errwatch._relay_poweroff[0] = probe
        for n, fn in saved.items():
            setattr(snapshot, n, fn)


def okww_pushes(text: str, *, expect_nest: bool = False, expect_daily: bool = True,
                expect_stamina: bool = True, only_nest: str = "") -> list[str]:
    """The group pushes ``outcome.okww_checks`` would send for one OK-WW run log.

    Defaults match ``okww_checks``: daily and stamina are expected, no nest
    filter. Each entry is the paragraph ``outcome.summarize`` would push (which
    starts 「OK-WW 这一轮有 … 项没干成」); an empty list means the run is green."""
    from ark_relay.features.verify.outcome import okww_checks, summarize  # noqa: PLC0415

    msg = summarize(okww_checks(text, expect_nest=expect_nest, expect_daily=expect_daily,
                                expect_stamina=expect_stamina, only_nest=only_nest), "OK-WW")
    return [msg] if msg else []


def errwatch_pushes(text: str) -> list[dict]:
    """The group pushes errwatch would send for the WARNING / ERROR lines of a relay.log.

    Each entry is ``{where, line, lineno}``. A line of a known 10-06 false alarm
    is replaced by what its producer, run again now under the real errwatch
    handler, pushes (lineno = the first source line of that producer, line =
    what this version would log); every other line pushes as written."""
    out: list[dict] = []
    cal: dict[str, "re.Match"] = {}
    cal_at = 0
    snap: set[str] = set()
    snap_at = 0
    for i, line in enumerate(text.splitlines(), 1):
        m = _LINE.match(line)
        if m is None:
            continue
        name, msg = m.group(2), m.group(3)
        if name == "ark.banners" and (hit := _CAL_MISS.match(msg) or _CAL_IMG.match(msg) or _CAL_FAIL.match(msg)):
            cal.setdefault(hit.re.pattern, hit)
            cal_at = cal_at or i
        elif name == "ark.phone_banners" and _MC2.match(msg):
            cal_at = cal_at or i
        elif name == "ark.snapshot" and (hit := _SNAP.match(msg)):
            snap.add(hit.group(1))
            snap_at = snap_at or i
        else:
            out.append({"where": name, "line": msg, "lineno": i})
    runs = []
    if cal_at:
        runs.append((cal_at, lambda: _replay_calendar(cal.get(_CAL_MISS.pattern), cal.get(_CAL_IMG.pattern))))
    if snap_at:
        runs.append((snap_at, lambda: _replay_snapshot(snap)))
    if runs:
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        ark = logging.getLogger(errwatch.ARK)   # where boot_stages installs the handler
        with tempfile.TemporaryDirectory() as td:
            h, taken = _handler(Path(td) / "state")
            ark.addHandler(h)
            try:
                for at, run in runs:
                    before = len(taken)
                    run()
                    out += [{"where": r.name, "line": r.getMessage().splitlines()[0] if r.getMessage() else "",
                             "lineno": at} for r in taken[before:]]
            finally:
                ark.removeHandler(h)
    return sorted(out, key=lambda p: p["lineno"])


def _is_okww(path: str) -> bool:
    # The checked-in fixture is 「okww-1006-run.log」 and the evidence package's own
    # name is 「OK-WW-…」: both are OK-WW run logs (an exact 「OK-WW」 test missed the
    # fixture, so the deploy gate replayed it as a relay.log and found nothing).
    return re.search(r"ok-?ww", Path(path).name, re.I) is not None


def _pushed(path: str) -> list[str]:
    """The pushes replaying one file would send, as printable lines with their source."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"{path}: 读不了：{exc}"]
    if _is_okww(path):
        return [f"{path} → {push.splitlines()[0]}" for push in okww_pushes(text)]
    return [f"{path}:{p['lineno']} {p['where']}: {p['line'][:160]}" for p in errwatch_pushes(text)]


def main(argv: list[str]) -> int:
    """Replay the given log files; print every push with its source; 1 when any push."""
    pushed: list[str] = []
    for path in argv:
        pushed += _pushed(path)
    if pushed:
        for line in pushed:
            print(line)
        print(f"{len(pushed)} 条会推进群", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
