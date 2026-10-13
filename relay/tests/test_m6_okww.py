"""M6 OK-WW report fixes, replayed on the machine's own logs (slices under
fixtures/m6-okww, cut from the 09-21 and 09-22 runs pulled back on 09-23).

- 09-21 weekly boss: the Teleport-to-Boss key is logged before the book opens;
  the run never got in (no start-challenge button, then Teleport to boss
  failed) and used to be reported as fought-but-unclaimed.
- 09-22 weekly boss: read 0/3 before entering and skipped - full, but not by
  this run.
- 09-21 tacet: the reward dialog showed 180 left, OK-WW read 0 (reserve 240)
  and stopped. The correction from the dialog's 「剩余 N」 was deleted on
  2026-10-13 (audit item 13): none of the real dialog lines the override logs
  carries 「剩余」, so it never applied; the last reading is reported as such.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify import collector_okww as c, outcome as o

FX = Path(__file__).resolve().parent / "fixtures" / "m6-okww"
bad = []


def check(label, got, want):
    print(("  ✓ " if got == want else "  ✗ ") + label + ("" if got == want else f": got {got!r}, want {want!r}"))
    if got != want:
        bad.append(label)


r = c.parse_okww_log(FX / "0921-weekly.log")
t = (FX / "0921-weekly.log").read_text(encoding="utf-8")
# 「等了 10 秒」: the timeout line is 0.6 s before the header but more than 600
# characters back (collector_okww._wait_before, audit 2026-10-13 item 8).
check("09-21 失败原因不再说「没能退出副本」", r.get("okww_error"), "周本：选了等级后没等到「开启挑战」，没进本，一次没打（等了 10 秒）")
check("09-21 步骤：没进本", [s for s in r.get("okww_steps", []) if "周本" in s], ["周本（没进本，一次没打，原因见失败于）"])
check("09-21 核对：没进本不说「打了」",
      [(k.label, k.ok, k.detail) for k in o.okww_checks(t, expect_nest=False) if "周本" in k.label],
      [("周本", False, "没进本，一次没打：选了等级后没等到「开启挑战」")])

r = c.parse_okww_log(FX / "0922-weekly.log")
t = (FX / "0922-weekly.log").read_text(encoding="utf-8")
check("09-22 0/3：说清不是这一趟领的", [s for s in r.get("okww_steps", []) if "周本" in s],
      ["周本（已完成：进本前读到本周 0/3，早已领满，这一趟没领）"])
check("09-22 0/3 仍算本周已完成（每周记账看「已完成」）", "已完成" in r["okww_steps"][0], True)
check("09-22 核对不报错", all(k.ok for k in o.okww_checks(t, expect_nest=False) if "周本" in k.label), True)

tacet = (FX / "0921-tacet.log").read_text(encoding="utf-8")
p = FX.parent.parent / "_m6_tacet_tmp.log"
try:
    p.write_text(tacet, encoding="utf-8")
    r = c.parse_okww_log(p)
    check("没有领奖框原文时照旧：最后一次读数 0", (r.get("okww_stamina_left"), r.get("okww_stamina_left_exact")), (0, False))
finally:
    p.unlink(missing_ok=True)

if bad:
    print("FAILED: " + ", ".join(bad))
    sys.exit(1)
print("all checks passed")
