"""A MaaEnd task that failed because the account was logged in elsewhere names that as its cause.

2026-11-05 11:43:57 (Beijing) the account was logged in on another device (his brother). The game put
「登录认证已失效，请重新登录」 over everything; MaaFW's batch OCR logged it in maafw.log
(fixtures/maaend-2026-11-05/maafw-logged-out-ocr.log, one real line), every route after it failed, and
AUTO-MAS booked 「任务失败: 🧺自动采集」 at 11:54:57 (fixtures/.../history-MaaEnd-07-24-54-gathering.log,
real lines). The alarm said gathering failed and nothing more. Checked, on those real lines:
* the failed task gets the logged-out cause and the record the dialog's time;
* the alarm's 卡在 part carries it (ledger_rows._with_causes);
* no dialog in the framework log, or no framework log: no cause;
* a task that failed before the dialog: no cause.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core.ledger_rows import _with_causes
from ark_relay.features.verify import collector_maaend as C

FIX = Path(__file__).resolve().parent / "fixtures" / "maaend-2026-11-05"
HISTORY = (FIX / "history-MaaEnd-07-24-54-gathering.log").read_text(encoding="utf-8")
FW_LINE = (FIX / "maafw-logged-out-ocr.log").read_text(encoding="utf-8")
TMP = tmpdir()
fails = []


def check(label, got, want=True):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + label + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


def maaend_dir(name, fw_text):
    d = TMP / name
    (d / "debug").mkdir(parents=True, exist_ok=True)
    if fw_text is not None:
        (d / "debug" / "maafw.log").write_text(fw_text, encoding="utf-8")
    return d


def parse(name, history, fw_text):
    log = TMP / f"{name}.log"
    log.write_text(history, encoding="utf-8")
    return C.parse_maaend_log(log, maaend_dir(name, fw_text))


print("[11-05 原样：11:43:57 弹「登录认证已失效」，11:54:57 自动采集失败]")
out = parse("real", HISTORY, FW_LINE)
check("记下弹框的时刻", out.get("maaend_logged_out_at"), "11:43:57")
check("自动采集的原因是被挤下线", (out.get("maaend_fail_causes") or {}).get("自动采集"), C.LOGGED_OUT)
check("报警「卡在」那一段带上原因", _with_causes(out.get("tasks_failed") or [], out.get("maaend_fail_causes")),
      ["自动采集（" + C.LOGGED_OUT + "）"])

print("\n[框架日志里没有那句话、或者没有框架日志：不写原因]")
out = parse("no-dialog", HISTORY, FW_LINE.replace(C.LOGGED_OUT_TEXT, "资源完整性"))
check("没有那句话：不记时刻", "maaend_logged_out_at" in out, False)
check("没有那句话：不写原因", (out.get("maaend_fail_causes") or {}).get("自动采集"), None)
out = parse("no-fw", HISTORY, None)
check("没有框架日志：不写原因", (out.get("maaend_fail_causes") or {}).get("自动采集"), None)

print("\n[弹框之前就失败的任务：不算被挤下线]")
early = "\n".join(line for line in HISTORY.splitlines() if line < "[2026-11-05 11:43:5")
early += "\n[2026-11-05 11:43:00.000] 任务失败: 🧺自动采集\n"
out = parse("early", early, FW_LINE)
check("弹框前失败：不写原因", (out.get("maaend_fail_causes") or {}).get("自动采集"), None)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
