"""Print one ASCII-safe line per run record for a given day.

Runs on the game machine, called by scripts/mac/watch-run.sh. Everything is
decoded here and re-emitted as ASCII so no Chinese path, user directory or
failure string ever has to survive the machine's GBK console on its way out
over SSH - that round trip is what turned earlier watch loops into mojibake.

    python run-probe.py 2026-08-21

Lines are `REC|stem|kind|ok|result`, or `UPD|stem|MaaEnd|1|result` for AUTO-MAS
installing a MaaEnd update (「[更新] Success!」 / 「[更新] 跳过更新」): not a run,
the same rule as the relay's collector (_judge_result, _UPDATE_FINE). A failed
update stays a REC with ok 0, as the relay books it.
"""
import glob
import json
import os
import re
import sys

HISTORY = r"D:\ark\automas\history"
# Mirrors relay/ark_relay/core/collector.py (_STAGE_PREFIX, _STAGE_LABELS,
# _UPDATE_LABEL, _UPDATE_FINE); this script runs alone on the machine, so it
# cannot import the relay.
STAGE_PREFIX = re.compile(r"^\[([^\]]*)\]\s*")
STAGE_LABELS = ("送货", "日常", "自动采集")
UPDATE_LABEL = "更新"
UPDATE_FINE = ("Success!", "跳过更新")


def judge(kind: str, result: str) -> "tuple[str, str]":
    """(tag, ok) for one record: tag REC or UPD, ok "1" / "0"."""
    text = result.strip()
    if kind == "MaaEnd" and (m := STAGE_PREFIX.match(text)):
        label, rest = m.group(1).strip(), text[m.end():].strip()
        if label == UPDATE_LABEL:
            return ("UPD", "1") if rest in UPDATE_FINE else ("REC", "0")
        if label in STAGE_LABELS:
            text = rest
    return "REC", "1" if text == "Success!" else "0"


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else ""
    for path in sorted(glob.glob(os.path.join(HISTORY, day, "*", "*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        # OK-WW records carry neither: AUTO-MAS writes them under general_result
        # (collector.py reads the same key). Without this every Wuthering Waves
        # run, successful or not, printed as `FAIL ... MaaEnd ?`.
        if "maa_result" in data:
            kind, result = "MAA", data.get("maa_result") or "?"
        elif "maaend_result" in data:
            kind, result = "MaaEnd", data.get("maaend_result") or "?"
        elif "general_result" in data:
            kind, result = "OK-WW", data.get("general_result") or "?"
        else:
            kind, result = "?", "?"
        tag, ok = judge(kind, result)
        # json.dumps with ensure_ascii escapes every non-ASCII character.
        print("%s|%s|%s|%s|%s" % (tag, os.path.basename(path)[:-5], kind, ok,
                                  json.dumps(result, ensure_ascii=True)))


if __name__ == "__main__":
    main()
