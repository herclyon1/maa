"""AUTO-MAS renamed its history records; the relay must read both forms.

Until v5.4.0-beta.7 a record was "<HH-MM-SS>.json". From that version it is
"<Script>-<HH-MM-SS>.json". The relay derived the run's start time from the
whole stem, so on the morning after that update every record was rejected:
an empty ledger, no daily report, no power-off, and a "该跑没跑" alarm for a
queue that had in fact succeeded.

Nothing about the file's *contents* changed - only its name.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector
from ark_relay.config import SERVER_TZ

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


BODY = {"recruit_statistics": {}, "drop_statistics": {"AT-4": {"龙门币": 1008}},
        "sanity": 1, "maa_result": "Success!"}


def one(root: Path, day: str, user: str, stem: str):
    d = root / day / user
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{stem}.json"
    p.write_text(json.dumps(BODY, ensure_ascii=False), encoding="utf-8")
    # scan() deliberately skips a fresh .json with no .log beside it - that is
    # a run still being written. Give it the pair a finished run would have.
    p.with_suffix(".log").write_text("", encoding="utf-8")
    return collector.parse_record(p, root)


def main(root: Path) -> int:
    old = one(root, "2026-08-22", "arknights", "05-00-01")
    check("旧命名能解析", old is not None, True)
    new = one(root, "2026-08-23", "arknights", "MAA-05-00-00")
    check("新命名能解析", new is not None, True)
    end = one(root, "2026-08-23", "endfield", "MaaEnd-05-17-35")
    check("MaaEnd 新命名能解析", end is not None, True)

    if new:
        # 05:00 on AUTO-MAS's UTC+4 clock is 09:00 server time.
        check("新命名解析出的时刻正确",
              new.started.astimezone(SERVER_TZ).strftime("%H:%M"), "09:00")
        check("脚本识别正确", new.script, "MAA")
        check("成功状态正确", new.ok, True)

    junk = one(root, "2026-08-23", "arknights", "readme")
    check("非记录文件仍被拒绝", junk is None, True)

    # scan() must see both days
    recs = collector.scan(root, set())
    days = {r.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d") for r in recs}
    check("scan 同时看到两天", "2026-08-23" in days and "2026-08-22" in days, True)

    print("[a run record whose name no longer parses is said, once per file]")
    import logging  # noqa: PLC0415
    warned = []
    h = type("W", (logging.Handler,), {"emit": lambda self, r: warned.append(r.getMessage())})(level=logging.WARNING)
    collector.log.addHandler(h)
    try:
        getattr(collector, "_unparsed_warned", set()).clear()
        renamed = one(root, "2026-10-10", "arknights", "MAA_05h00m00s")
        check("renamed record -> still not booked", renamed is None, True)
        check("renamed record -> one WARNING naming the file",
              len(warned) == 1 and "MAA_05h00m00s" in warned[0], True)
        collector.scan(root, set())
        collector.scan(root, set())
        check("rescans -> no second WARNING for the same file", [w for w in warned if "MAA_05h00m00s" in w],
              warned[:1])
        other = root / "2026-10-10" / "arknights" / "notes.json"
        other.write_text(json.dumps({"something": 1}), encoding="utf-8")
        n = len(warned)
        collector.parse_record(other, root)
        check("a JSON with no result key -> not a run record, no WARNING", len(warned), n)
        check("the earlier junk record named 'readme' carries maa_result, so a scan said it too",
              any("readme" in w for w in warned), True)
    finally:
        collector.log.removeHandler(h)

    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        raise SystemExit(main(Path(d)))
