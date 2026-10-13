"""Tomorrow's sanity line honours MaaEnd's weekday ticks for the sanity tasks.

Audit 2026-10-13 (weekly block, finding 2): sanity_plan.read() took every
enabled ProtocolSpace / AutoEssence as "runs tomorrow", and plan.py printed
「理智用于 …」 for it, though MaaEnd runs a task only on the weekdays ticked in
its f"{task}Schedule" option (the master holds ProtocolSpaceSchedule /
AutoEssenceSchedule; with none saved MaaEnd uses the option's default_case).
plan._maaend_extra_bits already applies that rule to AutoCollect.

Input is the machine's own master (fixtures/maaend-2026-09-10/master-before.json:
AutoEssence on, ProtocolSpace off, all seven days ticked), with MaaEnd's
definitions from the same day's install fixture (AutoEssenceSchedule default_case
is all seven days). Checked through next_plan (the 「明日安排」 text), with the
machine's AUTO-MAS config (fixtures/automas-config-2026-10-11) pointing MaaEnd at
a temp install.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import plan
from ark_relay.core.config import SERVER_TZ
from ark_relay.core.names import GAME_ZH

FX = Path(__file__).resolve().parent / "fixtures"
MASTER = FX / "maaend-2026-09-10" / "master-before.json"
MAAEND_FX = FX / "maaend-2026-09-10"
AUTOMAS_FX = FX / "automas-config-2026-10-11" / "config"
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

FAILED: list[str] = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}")
    if not ok:
        FAILED.append(name)


def setup(name: str, edit) -> Path:
    root = tmpdir() / name
    automas = root / "automas"
    cfg = automas / "data" / "59da8762" / "Default" / "ConfigFile"
    cfg.mkdir(parents=True)
    data = json.loads(MASTER.read_text(encoding="utf-8"))
    for t in data["instances"][0]["tasks"]:
        if t["taskName"] == "AutoCollect":
            t["enabled"] = False         # keeps the gathering line out of the way
        edit(t)
    (cfg / "mxu-MaaEnd.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    maaend = root / "maaend"
    maaend.mkdir()
    shutil.copy(MAAEND_FX / "interface.json", maaend / "interface.json")
    shutil.copytree(MAAEND_FX / "tasks", maaend / "tasks")
    shutil.copytree(AUTOMAS_FX, automas / "config")
    sc = automas / "config" / "ScriptConfig.json"
    d = json.loads(sc.read_text(encoding="utf-8"))
    for inst in d["instances"]:
        info = d[inst["uid"]]["Info"]
        if "maaend" in str(info.get("Path", "")).lower():
            info["Path"] = str(maaend)
    sc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return automas


def sanity_lines(automas: Path, tomorrow: datetime) -> list[str]:
    """The sanity line(s) of the Endfield (MaaEnd) block in next_plan."""
    plan._tomorrow = lambda: tomorrow
    out, inside = [], False
    for ln in plan.next_plan(automas).splitlines():
        if ln.startswith("▸"):
            inside = ln == f"▸ {GAME_ZH['MaaEnd']}"
        elif inside and "理智" in ln:
            out.append(ln.strip())
    return out


def days_but(task: str, skip: str):
    def edit(t):
        if t["taskName"] == task:
            t["optionValues"][f"{task}Schedule"]["caseNames"] = [
                f"{task}Schedule{d}" for d in DAYS if d != skip]
    return edit


def both_on(t):
    if t["taskName"] == "ProtocolSpace":
        t["enabled"] = True


TUESDAY = datetime(2026, 10, 13, 12, tzinfo=SERVER_TZ)
WEDNESDAY = datetime(2026, 10, 14, 12, tzinfo=SERVER_TZ)

print("[the machine's master as is: AutoEssence on every day]")
am = setup("as-is", lambda t: None)
check("Tuesday names essence farming", sanity_lines(am, TUESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])

print("\n[AutoEssence not ticked for Tuesday]")
am = setup("no-tue", days_but("AutoEssence", "Tuesday"))
got = sanity_lines(am, TUESDAY)
check("Tuesday: not 「理智用于 基质刷取」", any(ln.startswith("理智用于") for ln in got), False)
check("Tuesday: says the sanity task sits the day out", len(got) == 1 and "不跑" in got[0], True)
check("Wednesday: still runs", sanity_lines(am, WEDNESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])

print("\n[both on, ProtocolSpace not ticked for Tuesday: only essence farming]")
def both_no_tue_ps(t):
    both_on(t)
    days_but("ProtocolSpace", "Tuesday")(t)
am = setup("both-no-tue", both_no_tue_ps)
check("Tuesday: essence farming only", sanity_lines(am, TUESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])
got = sanity_lines(am, WEDNESDAY)
check("Wednesday: both, ProtocolSpace first",
      len(got) == 1 and got[0].startswith("理智用于 干员养成") and "基质刷取" in got[0], True)

print("\n[no AutoEssenceSchedule saved: MaaEnd's default_case (all seven days)]")
am = setup("default", lambda t: t["optionValues"].pop("AutoEssenceSchedule", None)
           if t["taskName"] == "AutoEssence" else None)
check("Tuesday names essence farming", sanity_lines(am, TUESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])

print("\n[the default_case itself comes from MaaEnd's definition]")
from ark_relay.features.weekly import sanity_plan  # noqa: E402
bare = {"taskName": "AutoEssence", "optionValues": {}}
check("all seven days from tasks/AutoEssence", sanity_plan._ticked_days(bare, MAAEND_FX), list(range(7)))
check("no definition -> unknown (kept by read)", sanity_plan._ticked_days(bare, None), None)
am = setup("say", days_but("AutoEssence", "Tuesday"))
check("the sit-out line", sanity_lines(am, TUESDAY),
      ["理智任务明天（周二）不跑（基质刷取仅周一、三、四、五、六、日 跑）"])

print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
sys.exit(1 if FAILED else 0)
