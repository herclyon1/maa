"""A periodic tick after Monday 04:00 must not eat the weekly garden's roll-over.

Audit 2026-10-13 (weekly block, finding 3). GardenGate.enforce() popped a
done_week from an earlier week itself (garden.py:113-114, :132-133), so the
boot-time WeekGate.maybe_reopen found nothing to roll over and the garden never
joined the new-week notice. The machine's record of Monday 2026-10-05 (Beijing
time, relay.log of the 10-13 copy):

    10-05 04:43:37 INFO    ark.garden  周常乐园检查已恢复
    10-05 08:45:19 INFO    ark.service  服务模式启动 ...
    10-05 08:46:03 INFO    ark.weeklyboss  新的一周，周本记账已清（上周 2026-W40）

No 「新的一周，周常乐园记账已清」 line: the 04:43 tick had already cleared it.
That day's new-week notice went out only because the weekly boss rolled over;
with only the garden done the week before, none would have gone out.

Replayed here: garden done in 2026-W40, switch off; ticks at 04:43:37 and 05:00
on Monday 10-05; boot at 08:46:03.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
import boot_stages
from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.weekly import garden as G
from ark_relay.features.weekly.annihilation import week_key

FAILED: list[str] = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}")
    if not ok:
        FAILED.append(name)


SAT = datetime(2026, 10, 3, 20, 0, tzinfo=SERVER_TZ)
TICK = datetime(2026, 10, 5, 4, 43, 37, tzinfo=SERVER_TZ)
TICK2 = datetime(2026, 10, 5, 5, 0, 0, tzinfo=SERVER_TZ)
BOOT = datetime(2026, 10, 5, 8, 46, 3, tzinfo=SERVER_TZ)


class AtBoot(G.GardenGate):
    """The gate as the boot stage calls it (no `now`), pinned to 10-05 08:46:03."""

    def maybe_reopen(self, now=None):
        return super().maybe_reopen(now or BOOT)

    def enforce(self, now=None):
        return super().enforce(now or BOOT)

    def week_line(self, now=None):
        return super().week_line(now or BOOT)


class Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, body, **kw):
        self.sent.append((title, body))
        return []


class Log:
    def exception(self, *a, **k):
        FAILED.append("boot stage logged an exception")

    def warning(self, *a, **k):
        pass


def master(tmp: Path) -> Path:
    cfg = tmp / "automas" / "data" / "sid" / "Default" / "ConfigFile"
    cfg.mkdir(parents=True)
    (cfg / "DailyTask.json").write_text(json.dumps({G.KEY: [G.TASK_NAME]}), encoding="utf-8")
    return cfg / "DailyTask.json"


def switch_on(f: Path) -> bool:
    return G.TASK_NAME in json.loads(f.read_text(encoding="utf-8"))[G.KEY]


check("10-03 is game-week 2026-W40", week_key(SAT), "2026-W40")
check("10-05 04:43 is the new week 2026-W41", week_key(TICK), "2026-W41")

print("\n[garden done in W40, switched off]")
tmp = tmpdir()
f = master(tmp)
g = AtBoot(tmp / "state", tmp / "automas")
g.on_success(SAT)
check("switched off in W40", (g.enforce(SAT), switch_on(f)), (True, False))

print("\n[Monday 04:43:37 tick puts the switch back; 05:00 tick finds nothing to do]")
check("04:43:37 switch back on", (g.enforce(TICK), switch_on(f)), (True, True))
check("05:00 no change", g.enforce(TICK2), False)
check("not done this week", g.settings(TICK2), {"本周已完成": False})

print("\n[08:46:03 boot: the garden still rolls over into the new week]")
n = Notifier()
engine = type("E", (), {"_garden": g, "_weeklyboss": None, "_annihilation": None})()
boot_stages._stage_annihilation(engine, n, Log())
check("a new-week notice goes out", [t for t, _ in n.sent], [texts.NEW_WEEK])
check("it carries the garden's line", [b for _, b in n.sent], ["鸣潮 · 周常乐园：本周还没做，每趟都会去检查"])
check("asked again: nothing more", g.maybe_reopen(), "")
check("switch stays on", switch_on(f), True)

print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
sys.exit(1 if FAILED else 0)
