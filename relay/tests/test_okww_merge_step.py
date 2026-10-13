"""The step list does not claim 「声骸五合一」 from the line logged before the merge.

collector_okww._okww_steps added 「声骸五合一」 whenever 「check discarded echo」 was in
the log - a line upstream writes before merging. When MergeEchoTask then fails,
upstream logs 「… Failed」 and carries on; the failure reaches the group through
gamelog_errors.check_round, while the report listed the merge as done beside that
alarm (audit 2026-10-13 item 16). The label is gone; the garden's 「不算完成」 stays.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify import collector_okww as co  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


T = "2026-10-12 10:{:02d}:00,000 {} TaskExecutor {}"
MERGE_FAILED = "\n".join([
    T.format(1, "INFO", "MergeEchoTask:check discarded echo"),
    T.format(2, "ERROR", "MergeEchoTask:MergeEchoTask Failed"),
])
GARDEN = T.format(3, "INFO", "GardenTask:garden counter 2/3")

print("[merge started and failed: not listed as done]")
steps = co._okww_steps(MERGE_FAILED, 0)
check("no 声骸五合一", any("五合一" in s for s in steps), False)

print("\n[the garden's 「不算完成」 marking is unchanged]")
check("garden ran, not read as done", co._okww_steps(GARDEN, 0), ["周常乐园（没读到做完，不算完成）"])

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
