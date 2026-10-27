"""A nest given up after two failed travels is 「not done」 in the verdict and the report, even when another nest was fought.

10-27 the 快速旅行 click on 梦枢天罗 took no effect (someone was connected over
TeamViewer at 09:22:44-09:23:51), the nest was cached as unreachable, 落渊南丘 was
fought, and nest_state read the fight and booked the run 「fought」: the report said
鸣潮 ran fine while one of the two nests he asked for was never farmed
(fixtures/okww-1027-nest-unreachable.log, the real task lines 09:22:58-09:25:32).

The overlay now retries a failed travel once and logs NEST_GAVE_UP_LINE only when the
second try fails too (test_okww_nest_v373.py); this is the relay reading that line.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.okww_patch import okww_overlay
from ark_relay.features.verify import collector_okww as co, outcome

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


REAL = (Path(__file__).resolve().parent / "fixtures" / "okww-1027-nest-unreachable.log").read_text(encoding="utf-8")
ns = {}
exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
GAVE_UP = ns["NEST_GAVE_UP_LINE"]


def verdict(text):
    got = [c for c in outcome.okww_checks(text, expect_nest=True, expect_daily=False, expect_stamina=False)
           if c.label == "残象聚落"]
    return (got[0].ok, got[0].detail) if got else None


def after(text, at, msg):
    """`text` with one NightmareNestTask line inserted before the line stamped `at`."""
    line = f"2026-10-27 {at},000 INFO TaskExecutor NightmareNestTask:{msg}\n"
    i = text.index(f"2026-10-27 {at}")
    return text[:i] + line + text[i:]


print("[the real 10-27 log, before the overlay retried: booked 「fought」 - the gap]")
check("nest_state", outcome.nest_state(REAL), "fought")
check("no nest given up (the line did not exist yet)", outcome.nests_given_up(REAL), [])

print("\n[retried and travelled: still 「fought」, nothing named]")
retried = after(REAL, "09:25:05,676", "nightmare nest: 传送不过去，马上再试一次 go_nest:48:18")
check("nest_state", outcome.nest_state(retried), "fought")
check("verdict ok", verdict(retried), (True, "有进本/战斗记录"))
check("step is the bare name", co._nest_step(retried), "残象聚落")

print("\n[the second try failed too: 「partly」, red, the nest named]")
both = after(retried, "09:25:18,365", f"{GAVE_UP}go_nest:48:18（梦枢天罗残象聚落）")
check("the relay's pattern reads the overlay's own line", outcome.nests_given_up(both), ["梦枢天罗残象聚落"])
check("nest_state", outcome.nest_state(both), "partly")
check("verdict red, names the nest", verdict(both),
      (False, "有一处点位传送两次都不过去，那一处没打（梦枢天罗残象聚落）"))
check("step says which one was not farmed", co._nest_step(both), "残象聚落（有一处传送两次都不过去，那一处没打）（梦枢天罗残象聚落）")

print("\n[given up and nothing else fought: 「unreachable」 as before]")
alone = REAL[:REAL.index("2026-10-27 09:25:05,676")] + f"2026-10-27 09:25:05,700 INFO TaskExecutor NightmareNestTask:{GAVE_UP}go_nest:48:18（梦枢天罗残象聚落）\n"
check("nest_state", outcome.nest_state(alone), "unreachable")
check("verdict red", verdict(alone)[0], False)

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
