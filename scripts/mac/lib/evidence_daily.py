#!/usr/bin/env python3
"""Fetch one day's relay.log (and AUTO-MAS app.log) from COS, slice to a window.

    evidence_daily.py <YYYY-MM-DD> [HH:MM HH:MM]

The relay uploads today's whole relay.log to COS once a day, one object each,
name carrying the date (fix bill L, ark_relay/error_evidence.py):

    daily/relay-YYYY-MM-DD.log          - the relay's own log
    daily/automas-app-YYYY-MM-DD.log    - AUTO-MAS's app.log

This fetches them with the machine off - no winrun, no Windows - and prints the
slice inside the window (the whole day when none is given). Files land in
~/Claude/ark-evidence/daily/<date>/.

The COS signature is the same recipe as the relay's evidence.Cos and
evidence_pull.cos_get (COS_* in ~/.config/ark/push.env), which is reused here.
"""
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_pull  # env() and cos_get() from the run-bundle puller

DEST_ROOT = Path.home() / "Claude" / "ark-evidence" / "daily"

# relay.log stamps MM-DD HH:MM:SS (no year); AUTO-MAS app.log stamps the full date.
_TS = re.compile(r"^(?:(\d{4})-)?(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)")


def parse_window(date: str, span: list[str]) -> tuple[float, float]:
    """(t0, t1) epoch seconds for the day, narrowed by [HH:MM HH:MM] when given."""
    year = int(date[:4])
    start = datetime(year, int(date[5:7]), int(date[8:10]))
    end = start + timedelta(days=1)
    if span:
        if len(span) != 2:
            raise SystemExit("时间窗要给两个时刻：HH:MM HH:MM")
        t0 = start + _hhmm(span[0])
        t1 = start + _hhmm(span[1])
        return t0.timestamp(), t1.timestamp()
    return start.timestamp(), end.timestamp()


def _hhmm(s: str) -> timedelta:
    try:
        h, m = s.split(":")
        return timedelta(hours=int(h), minutes=int(m))
    except ValueError:
        raise SystemExit(f"时刻写错了：{s}（要 HH:MM）")


def slice_lines(path: Path, window: tuple[float, float]) -> str:
    """The lines of `path` stamped inside `window` (continuation lines follow)."""
    year = datetime.fromtimestamp(window[0]).year
    keep = False
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _TS.match(line)
        if m:
            y = int(m.group(1)) if m.group(1) else year
            try:
                ts = datetime(y, int(m.group(2)), int(m.group(3)),
                              int(m.group(4)), int(m.group(5)), int(m.group(6))).timestamp()
            except ValueError:
                ts = None
            if ts is not None:
                keep = window[0] <= ts <= window[1]
        if keep:
            out.append(line)
    return "\n".join(out) + ("\n" if out else "")


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    date = sys.argv[1]
    window = parse_window(date, sys.argv[2:])
    e = evidence_pull.env(Path.home() / ".config" / "ark" / "push.env")
    if not all(e.get(k) for k in ("COS_SECRET_ID", "COS_SECRET_KEY", "COS_BUCKET", "COS_REGION")):
        raise SystemExit("push.env 里缺 COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET / COS_REGION")
    dest = DEST_ROOT / date
    dest.mkdir(parents=True, exist_ok=True)
    failed = 0
    for key, name in (("relay", "relay"), ("automas-app", "automas-app")):
        u = {"key": f"daily/{key}-{date}.log", "name": f"{name}-{date}.log"}
        try:
            evidence_pull.cos_get(e, u, dest)
        except Exception as exc:  # noqa: BLE001 - one missing object must not lose the other
            print(f"  ✗ {u['name']}：取不到（{exc}）")
            failed += 1
            continue
        sliced = slice_lines(dest / u["name"], window)
        if not sliced.strip():
            print(f"  {u['name']}：这一天在窗口里没有行")
        else:
            print(f"  {u['name']}：窗口里 {len(sliced.splitlines())} 行 → {dest / ('window-' + u['name'])}")
            (dest / f"window-{u['name']}").write_text(sliced, encoding="utf-8")
    print(f"文件在 {dest}/")
    # A caller that checks only the exit code must not read a missing log as success.
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
