"""M6 OK-WW report fixes, replayed on the machine's own logs (slices under
fixtures/m6-okww, cut from the 09-21 and 09-22 runs pulled back on 09-23).

- 09-21 weekly boss: the Teleport-to-Boss key is logged before the book opens;
  the run never got in (no start-challenge button, then Teleport to boss
  failed) and used to be reported as fought-but-unclaimed.
- 09-22 weekly boss: read 0/3 before entering and skipped - full, but not by
  this run.
- 09-21 tacet: the reward dialog showed 180 left, OK-WW read 0 (reserve 240)
  and stopped. With the M7 override's raw dialog text in the log, the
  settlement's remainder wins and the mismatch is reported.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector_okww as c, core, outcome as o  # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures" / "m6-okww"
bad = []


def check(label, got, want):
    print(("  ✓ " if got == want else "  ✗ ") + label + ("" if got == want else f": got {got!r}, want {want!r}"))
    if got != want:
        bad.append(label)


r = c.parse_okww_log(FX / "0921-weekly.log")
t = (FX / "0921-weekly.log").read_text(encoding="utf-8")
check("09-21 失败原因不再说「没能退出副本」", r.get("okww_error"), "周本：选了等级后没等到「开启挑战」，没进本，一次没打")
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
    key = "2026-09-21 10:25:49,146 INFO TaskExecutor TacetTask:info_set current_stamina 0"
    check("夹具里有 09-21 那条读成 0 的读数", tacet.count(key), 1)
    dialog = "2026-09-21 10:25:49,100 INFO TaskExecutor TacetTask:体力读字原文领奖框（第 1 次）: [挑战成功_1.00, 剩余180_0.99]\n"
    p.write_text(tacet.replace(key, dialog + key), encoding="utf-8")
    r = c.parse_okww_log(p)
    check("按结算页剩余 180", (r.get("okww_stamina_left"), r.get("okww_stamina_left_exact")), (180, True))
    check("消耗按 240→180 算 60", r.get("okww_stamina_spent"), 60)
    check("记下对不上", tuple(r.get("okww_stamina_mismatch")), (0, 180))
    from datetime import datetime
    left = core._block_okww(r, datetime(2026, 9, 21, 10, 26))[3]
    check("剩余行写明对不上", any("体力读数对不上：脚本读成 0，结算页写剩余 180，按结算页" in x for x in left), True)
finally:
    p.unlink(missing_ok=True)

if bad:
    print("FAILED: " + ", ".join(bad))
    sys.exit(1)
print("all checks passed")
