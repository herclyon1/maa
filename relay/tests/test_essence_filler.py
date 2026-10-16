#!/usr/bin/env python3
"""基质刷取: tick 唤月 next to 玉中身 (target mode), and once every ticked weapon's
essence is owned, switch to filler mode (刷垫子) by itself.

The owner's order, 2026-10-16 16:29 Tokyo (confirmed 17:01; quoted in full in
relay/USER-SWITCHES.txt): farm 唤月 next to 玉中身, and once both are complete switch to
filler mode (刷垫子) with engraving off and any region - the upstream note naming the best
regions is outdated.

Real data only: the 2026-10-16 record MaaEnd-09-53-33 (replay/2026-10-16/endfield, read
from the game PC unchanged; target mode ended with 「勾选武器的基质均已满足，结束任务」), the
AUTO-MAS MaaEnd master as it was that day (fixtures/maaend-v2.33-essence/master-1016.json,
cut down, see SOURCE.txt) and MaaEnd v2.33.0-rc.1's own AutoEssence definitions. The
record goes through Engine._handle and the switch through the engine's tick step, as on
the machine.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)
(AUTOMAS / "debug").mkdir()
for name in ("QueueConfig.json", "ScriptConfig.json"):
    (AUTOMAS / "config" / name).write_text(json.dumps({"instances": []}), encoding="utf-8")
CONF = AUTOMAS / "data" / "59da8762-8fa7-4260-8aee-10f9ca00097a" / "Default" / "ConfigFile"
CONF.mkdir(parents=True)
MASTER = CONF / "mxu-MaaEnd.json"
HIST = TMP / "history"
HIST.mkdir()
os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import engine as eng_mod  # noqa: E402
from ark_relay.core import ledger as core  # noqa: E402
from ark_relay.core import texts  # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.core.ledger import State  # noqa: E402
from ark_relay.features.alarm import errwatch, handle  # noqa: E402
from ark_relay.features.verify.collector_maaend import parse_maaend_log  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.33-essence"
REC = Path(__file__).resolve().parent / "replay" / "2026-10-16" / "endfield"
HIST_LOG = (REC / "MaaEnd-09-53-33.log").read_text(encoding="utf-8")
MET_LINE = "勾选武器的基质均已满足"
GENERIC = "基质目标已满足或任务结束"
DAY = "2026-10-16"
ESS = "AutoEssence"
FAILED: list[str] = []


def require(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
    if not ok:
        FAILED.append(name)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, kw.get("alert", False)))
        return False


class Src:
    def fetch(self, seen):
        return []


class Catch(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)

    def alarms(self) -> list[tuple]:
        return [getattr(r, errwatch.ALARM) for r in self.records
                if r.levelno >= logging.WARNING and hasattr(r, errwatch.ALARM)]


CATCH = Catch()
logging.getLogger(errwatch.ARK).addHandler(CATCH)
logging.getLogger(errwatch.ARK).setLevel(logging.INFO)
handle._weekly_gates = lambda eng, r: None
handle._ship_evidence = lambda eng, r: ""      # no bundle upload in a test


def build(maaend_dir: Path = FIX):
    cfg = Config()
    cfg.state_dir = TMP / "state"
    cfg.state_dir.mkdir(exist_ok=True)
    cfg.automas_dir = AUTOMAS
    cfg.maaend_dir = maaend_dir
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._verify_outcome = lambda r: None
    return e


def record(run_id: str, log_text: str) -> RunRecord:
    from datetime import datetime  # noqa: PLC0415
    f = TMP / f"{run_id.replace('/', '_')}.log"
    f.write_text(log_text, encoding="utf-8")
    return RunRecord(run_id=run_id, script="MaaEnd", user="endfield",
                     started=datetime(2026, 10, 16, 13, 54, 57, tzinfo=SERVER_TZ),
                     finished=datetime(2026, 10, 16, 14, 11, 39, tzinfo=SERVER_TZ),
                     ok=True, raw=parse_maaend_log(f))


def master() -> dict:
    return json.loads(MASTER.read_text(encoding="utf-8"))


def ov(doc: dict) -> dict:
    return next(t for t in doc["instances"][0]["tasks"] if t["taskName"] == ESS)["optionValues"]


def others(doc: dict) -> list:
    return [t for t in doc["instances"][0]["tasks"] if t["taskName"] != ESS]


def backups(tag: str) -> list[Path]:
    return sorted(CONF.glob(f"mxu-MaaEnd.json.bak-essence-{tag}-*"))


def put_master(doc: dict) -> None:
    MASTER.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def without_met(text: str) -> str:
    return "\n".join(x for x in text.splitlines() if MET_LINE not in x) + "\n"


def main() -> int:
    from ark_relay.features.essence import essence  # noqa: PLC0415 - missing before this change
    shutil.copyfile(FIX / "master-1016.json", MASTER)
    real = master()
    cfg = build().cfg
    regions = json.loads((FIX / "tasks/AutoEssence/Location/ChooseLocation.json").read_text(encoding="utf-8"))
    all_regions = [c["name"] for c in regions["option"]["AutoEssenceChooseLocation"]["cases"]]
    require("real master: target mode, only 玉中身 ticked, 刻写券 on, one region",
            ov(real)["AutoEssenceMenu"]["caseName"] == "Target"
            and ov(real)["AutoEssenceWeaponsClaymore"]["caseNames"] == ["wpn_claym_0018"]
            and "AutoEssenceWeaponsSword" not in ov(real)
            and ov(real)["AutoEssenceDoOverride"]["value"] is True
            and ov(real)["AutoEssenceChooseLocation"]["caseNames"] == ["WLSwordVaultDale"], repr(ov(real)))

    print("[A: 勾上唤月（玉中身留着），只在没有任务在跑时]")
    require("refused while an AUTO-MAS task runs", essence.busy(cfg, lambda: True) == "AUTO-MAS 还有任务在跑")
    require("free when nothing runs", essence.busy(cfg, lambda: False) == "")
    res = essence.apply(cfg, essence.pick_weapons, "pick", ["wpn_claym_0018", "wpn_sword_0025"])
    after = master()
    a = ov(after)
    require("written, backup is the original bytes",
            res.changed and len(backups("pick")) == 1
            and backups("pick")[0].read_bytes() == (FIX / "master-1016.json").read_bytes(), res.note)
    require("单手剑 on with exactly 唤月 (not the default: every ★6 sword)",
            a["AutoEssenceWeaponTypeSword"] == {"type": "switch", "value": True}
            and a["AutoEssenceWeaponsSword"] == {"type": "checkbox", "caseNames": ["wpn_sword_0025"]}, repr(a))
    require("双手剑 still exactly 玉中身", a["AutoEssenceWeaponTypeClaymore"]["value"] is True
            and a["AutoEssenceWeaponsClaymore"]["caseNames"] == ["wpn_claym_0018"])
    require("手铳 / 施术单元 / 长柄武器 off", all(a[f"AutoEssenceWeaponType{t}"] == {"type": "switch", "value": False}
                                        for t in ("Pistol", "Wand", "Lance")))
    require("before/after printed", res.before == {"weapons": {"AutoEssenceWeaponsClaymore": ["wpn_claym_0018"]}}
            and res.after == {"weapons": {"AutoEssenceWeaponsClaymore": ["wpn_claym_0018"],
                                          "AutoEssenceWeaponsSword": ["wpn_sword_0025"]}}, f"{res.before} {res.after}")
    changed = {"AutoEssenceWeaponTypeSword", "AutoEssenceWeaponsSword"}
    require("nothing else in 基质刷取 changed (target mode kept)",
            {k: v for k, v in a.items() if k not in changed} == {k: v for k, v in ov(real).items() if k not in changed})
    require("the other tasks unchanged", others(after) == others(real))
    require("names from MaaEnd's language pack",
            essence.weapon_names(FIX, ["wpn_claym_0018", "wpn_sword_0025"]) == ["玉中身", "唤月"])
    again = essence.apply(cfg, essence.pick_weapons, "pick", ["wpn_claym_0018", "wpn_sword_0025"])
    require("run again: nothing written, no second backup", not again.changed and len(backups("pick")) == 1, again.note)
    picked = master()

    print("[B: 只有通用那句「基质目标已满足或任务结束」：不切]")
    e = build()
    generic = without_met(HIST_LOG)
    require("negative fixture keeps the generic line only", GENERIC in generic and MET_LINE not in generic)
    e._handle(record(f"{DAY}/endfield/MaaEnd-generic", generic))
    e._essence_filler()
    require("master untouched, no backup", master() == picked and not backups("filler"))
    require("nothing pending", e.state.store.get(essence.SECTION, essence.PENDING) is None)

    print("[B: 10-16 那趟（勾选的都齐了）：有任务在跑就等，空了切成刷垫子]")
    rec = record(f"{DAY}/endfield/MaaEnd-09-53-33", HIST_LOG)
    require("real record parsed as target met", rec.raw.get("maaend_essence_met") is True)
    e._handle(rec)
    require("pending after the record", (e.state.store.get(essence.SECTION, essence.PENDING) or {}).get("run_id")
            == rec.run_id)
    e._scripts_running = lambda: True
    e._essence_filler()
    require("busy: master untouched, still pending", master() == picked and not backups("filler")
            and e.state.store.get(essence.SECTION, essence.PENDING) is not None)
    e._scripts_running = lambda: False
    e._essence_filler()
    f = ov(master())
    require("random mode", f["AutoEssenceMenu"] == {"type": "select", "caseName": "Random"}, repr(f["AutoEssenceMenu"]))
    require("使用刻写券 off", f["AutoEssenceDoOverride"] == {"type": "switch", "value": False})
    require("every region, in MaaEnd's order", f["AutoEssenceChooseLocation"]["caseNames"] == all_regions
            and len(all_regions) == 12, repr(f["AutoEssenceChooseLocation"]))
    sw = {"AutoEssenceMenu", "AutoEssenceDoOverride", "AutoEssenceChooseLocation"}
    require("领取方式 / 循环 / 应急理智加强剂 / weapons untouched",
            {k: v for k, v in f.items() if k not in sw} == {k: v for k, v in ov(picked).items() if k not in sw})
    require("the other tasks unchanged", others(master()) == others(real))
    require("one backup, the master before the switch", len(backups("filler")) == 1
            and json.loads(backups("filler")[0].read_text(encoding="utf-8")) == picked)
    require("no group alarm", CATCH.alarms() == [], repr(CATCH.alarms()))
    require("pending cleared", e.state.store.get(essence.SECTION, essence.PENDING) is None)
    line = next((x for x in e.state.read_ledger(DAY) if x["run_id"] == rec.run_id), {})
    sw_raw = (line.get("raw") or {}).get(essence.RAW_KEY) or {}
    require("ledger line marked with the weapons' names", sorted(sw_raw.get("weapons") or []) == sorted(["玉中身", "唤月"]),
            repr(sw_raw))
    _t, body = core.format_daily(DAY, [line])
    want = texts.essence_filler_on(sw_raw.get("weapons") or [])
    require("daily report says it once, plainly", body.count(want) == 1 and texts.ESSENCE_TARGET_MET not in body, body)
    require("plain language", texts.plain(want) == [] and texts.plain(texts.ESSENCE_FILLER_FAILED) == []
            and texts.plain(texts.essence_filler_failed("写进去之后读出来和写的不一样")) == [], repr(texts.plain(want)))

    print("[B: 再来一趟同样的记录 / 已经是刷垫子：什么都不动]")
    e._handle(rec)                       # the same record handled again
    require("a record already acted on is not armed again",
            e.state.store.get(essence.SECTION, essence.PENDING) is None)
    filler = master()
    rec2 = record(f"{DAY}/endfield/MaaEnd-later", HIST_LOG)
    e._handle(rec2)
    e._essence_filler()
    require("already filler mode: no write, no new backup", master() == filler and len(backups("filler")) == 1)
    line2 = next((x for x in e.state.read_ledger(DAY) if x["run_id"] == rec2.run_id), {})
    require("... and no switch line for it", essence.RAW_KEY not in (line2.get("raw") or {}))

    print("[他自己改回目标选择：不跟他拧，等下一次「都齐了」才再切]")
    put_master(picked)
    for _ in range(3):
        e._essence_filler()
    require("no record, no switch", master() == picked)
    rec3 = record(f"{DAY}/endfield/MaaEnd-next", HIST_LOG)
    e._handle(rec3)
    e._essence_filler()
    require("the next target-met run switches again", ov(master())["AutoEssenceMenu"]["caseName"] == "Random")

    print("[A 在刷垫子模式下拒绝（勾武器没意义）]")
    try:
        essence.apply(cfg, essence.pick_weapons, "pick", ["wpn_sword_0025"])
        require("refused outside target mode", False)
    except essence.Refused as exc:
        require("refused outside target mode", "不是「目标选择」" in str(exc), str(exc))

    print("[写不成：进群一次，不重试]")
    put_master(picked)
    empty = TMP / "no-maaend"
    empty.mkdir()
    e2 = build(empty)
    e2._handle(record(f"{DAY}/endfield/MaaEnd-nodefs", HIST_LOG))
    e2._essence_filler()
    e2._essence_filler()
    require("master untouched", master() == picked)
    require("one group alarm under its own title", [t for t, _ in CATCH.alarms()] == [texts.ESSENCE_FILLER_FAILED],
            repr(CATCH.alarms()))

    print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
