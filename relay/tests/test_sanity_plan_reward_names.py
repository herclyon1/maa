"""The sanity plan speaks MaaEnd's own reward-set names, not AUTO-MAS's A / B.

Audit 2026-10-13 (weekly block, finding 1): sanity_plan keyed its reward table by
"RewardsSetA" / "RewardsSetB" - the names of AUTO-MAS's quick-config field
(fixtures/automas-models/config.py.txt:286-288), which this module does not use.
MaaEnd's master copy holds one case per line, defined in ProtocolSpace.json as
f"{line}RewardsSetOption" (fixtures/maaend-protocolspace-v2.30.0-rc.1,
tasks/ProtocolSpace.json:898-1010; Chinese labels in locales/interface/zh_cn.json).
On the machine's own master (fixtures/maaend-2026-09-10/master-before.json:
OperatorEXPRewardsSetOption = CognitiveCarriers) the old code:
- named no reward item (read()["item"] == ""),
- refused every value MaaEnd defines ("只能 RewardsSetA / RewardsSetB"),
- accepted "RewardsSetA", wrote a case MaaEnd does not define, and the phone's
  answer said ✅ (phone/inbox.py _apply).

MaaEnd's install is found the way production finds it: AUTO-MAS's own config
(fixtures/automas-config-2026-10-11) with the MaaEnd script's path pointed at
the v2.30.0-rc.1 definition fixture.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import mastercfg
from ark_relay.features.phone import inbox
from ark_relay.features.weekly import sanity_plan

FX = Path(__file__).resolve().parent / "fixtures"
MASTER = FX / "maaend-2026-09-10" / "master-before.json"
MAAEND = FX / "maaend-protocolspace-v2.30.0-rc.1"
AUTOMAS_FX = FX / "automas-config-2026-10-11" / "config"

FAILED: list[str] = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}")
    if not ok:
        FAILED.append(name)


def setup(name: str) -> Path:
    """The real master with ProtocolSpace on, under an AUTO-MAS dir whose
    ScriptConfig points the MaaEnd script at the definition fixture."""
    automas = tmpdir() / name / "automas"
    cfg = automas / "data" / "59da8762" / "Default" / "ConfigFile"
    cfg.mkdir(parents=True)
    data = json.loads(MASTER.read_text(encoding="utf-8"))
    for t in data["instances"][0]["tasks"]:
        if t["taskName"] == "ProtocolSpace":
            t["enabled"] = True
    (cfg / "mxu-MaaEnd.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    shutil.copytree(AUTOMAS_FX, automas / "config")
    sc = automas / "config" / "ScriptConfig.json"
    d = json.loads(sc.read_text(encoding="utf-8"))
    for inst in d["instances"]:
        info = d[inst["uid"]]["Info"]
        if "maaend" in str(info.get("Path", "")).lower():
            info["Path"] = str(MAAEND)
    sc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return automas


def protocolspace(automas: Path) -> dict:
    f = next((automas / "data").glob("*/Default/ConfigFile/mxu-MaaEnd.json"))
    d = json.loads(f.read_text(encoding="utf-8"))
    return next(t for t in d["instances"][0]["tasks"] if t["taskName"] == "ProtocolSpace")["optionValues"]


print("[the reward table names exactly MaaEnd's cases, with MaaEnd's own Chinese]")
opts, _ = mastercfg._maaend_defs(MAAEND)
zh = json.loads((MAAEND / "locales" / "interface" / "zh_cn.json").read_text(encoding="utf-8"))
want_table = {}
for key, opt in opts.items():
    if key.endswith("RewardsSetOption"):
        line = key[: -len("RewardsSetOption")]
        for c in opt["cases"]:
            label = zh[c["label"][1:]]
            want_table[(line, c["name"])] = label.split(".", 1)[1]   # drop the "A." / "B." prefix
check("REWARD == MaaEnd's cases and labels", sanity_plan.REWARD, want_table)

print("\n[read(): the machine's master names the item that drops]")
am = setup("read")
r = sanity_plan.read(am)
check("line", r.get("line"), "OperatorEXP")
check("rewards_set is MaaEnd's case", r.get("rewards_set"), "CognitiveCarriers")
check("item named", r.get("item"), "高级认知载体、初级认知载体")
check("label ends with the item",
      r.get("label", "").split("，用完再 ")[0], "干员养成 → 干员经验 → 高级认知载体、初级认知载体")

print("\n[set_plan(): a case MaaEnd defines is accepted and written]")
ok, msg = sanity_plan.set_plan(am, "OperatorProgression", "OperatorEXP", "AdvancedCombatRecord")
check("accepted", ok, True)
check("written as MaaEnd's case",
      protocolspace(am).get("OperatorEXPRewardsSetOption"), {"type": "select", "caseName": "AdvancedCombatRecord"})
check("read() now names B", sanity_plan.read(am).get("item"), "高级作战记录")
ok, msg = sanity_plan.set_plan(am, "OperatorProgression", "Promotions", "Protodisk")
check("Promotions + Protodisk accepted", ok, True)
check("written", protocolspace(am).get("PromotionsRewardsSetOption", {}).get("caseName"), "Protodisk")

print("\n[set_plan(): a value MaaEnd does not define is refused, nothing written]")
am2 = setup("refuse")
before = protocolspace(am2)
ok, msg = sanity_plan.set_plan(am2, "OperatorProgression", "OperatorEXP", "RewardsSetA")
check("AUTO-MAS's RewardsSetA refused", ok, False)
check("refusal names MaaEnd's cases", "AdvancedCombatRecord" in msg and "CognitiveCarriers" in msg, True)
check("master untouched", protocolspace(am2), before)
ok, msg = sanity_plan.set_plan(am2, "OperatorProgression", "OperatorEXP", "Protodisk")
check("another line's case refused", ok, False)
ok, msg = sanity_plan.set_plan(am2, "OperatorProgression", "T-Creds", "CognitiveCarriers")
check("a line with no reward set refuses any", ok, False)
check("master still untouched", protocolspace(am2), before)

print("\n[set_plan(): MaaEnd's definition unreadable -> refuse rather than guess]")
am3 = setup("nodefs")
sc = am3 / "config" / "ScriptConfig.json"
d = json.loads(sc.read_text(encoding="utf-8"))
for inst in d["instances"]:
    info = d[inst["uid"]]["Info"]
    if str(info.get("Path", "")) == str(MAAEND):
        info["Path"] = str(tmpdir() / "no-maaend-here")
sc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
ok, msg = sanity_plan.set_plan(am3, "OperatorProgression", "OperatorEXP", "CognitiveCarriers")
check("refused", ok, False)
check("says the definition could not be read", "读不到" in msg, True)

print("\n[the phone's answer: no ✅ for a value MaaEnd does not define]")
am4 = setup("phone")
box = inbox.Inbox(tmpdir() / "state", automas_dir=am4)
out = box._apply([{"action": "sanity_plan", "tab": "OperatorProgression",
                   "line": "OperatorEXP", "rewards_set": "RewardsSetA"}])
check("answer is a refusal", [o.startswith("✗ 理智方案") for o in out], [True])
out = box._apply([{"action": "sanity_plan", "tab": "OperatorProgression",
                   "line": "OperatorEXP", "rewards_set": "AdvancedCombatRecord"}])
check("a real case gets ✅", [o.startswith("✅ 理智方案") for o in out], [True])

print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
sys.exit(1 if FAILED else 0)
