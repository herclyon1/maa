"""Print one ASCII-safe line per run record for a given day.

Runs on the game machine, called by scripts/mac/watch-run.sh. Everything is
decoded here and re-emitted as ASCII so no Chinese path, user directory or
failure string ever has to survive the machine's GBK console on its way out
over SSH - that round trip is what turned earlier watch loops into mojibake.

    python run-probe.py 2026-08-21
"""
import glob
import json
import os
import sys

HISTORY = r"D:\ark\automas\history"


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else ""
    for path in sorted(glob.glob(os.path.join(HISTORY, day, "*", "*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        result = data.get("maa_result") or data.get("maaend_result") or "?"
        kind = "MAA" if "maa_result" in data else "MaaEnd"
        ok = "1" if result.strip() == "Success!" else "0"
        # json.dumps with ensure_ascii escapes every non-ASCII character.
        print("REC|%s|%s|%s|%s" % (os.path.basename(path)[:-5], kind, ok,
                                   json.dumps(result, ensure_ascii=True)))


if __name__ == "__main__":
    main()
