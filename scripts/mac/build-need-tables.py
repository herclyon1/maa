#!/usr/bin/env python3
"""Build `web/data/need.json`: what one operator's full build needs, per material.

The phone page's 库存 tab shows, per material, 库存 | 单个角色满练所需 | 人份
(stock / need). The stock is live (the page asks Skland itself, see
`web/inventory.js`); the need is static and comes from this file, regenerated only
when a new operator or weapon appears on the account. Nothing here runs on a timer.

    python3 scripts/mac/build-need-tables.py                     # live pull -> web/data/need.json
    python3 scripts/mac/build-need-tables.py --save-fixtures DIR # live pull, and keep the raw responses
    python3 scripts/mac/build-need-tables.py --offline DIR -o F  # rebuild from saved responses, no network

Endfield only for now. The `games[]` layer is where 明日方舟 / 鸣潮 go later; the
schema does not change when they arrive.

## Where the numbers come from (all official, `docs/SKLAND-API.md` §3)

* `calculate/rules?charIds=<id>`, one operator per call (comma-joined ids return
  nothing): `breakthroughs[].materials` + `skills[].levels[].materials` up to
  target level 12, plus `charLevelRules` (gold and exp per level, 1 -> 90).
* `calculate/rules?weaponIds=<id>`: `weapons[].breakthroughs[].materials` plus
  `weaponLevelRules`.
* `calculate/material-list`: the 40 materials (id, name, rarity, icon, exp value).
* `card/detail`: which operators and weapons the account owns - the rules are asked
  for every owned operator and every equipped weapon.

Caliber = the official 完美 template (`docs/SKLAND-API.md` §7): level 90, four
skills to 12, weapon 1 -> 90, every breakthrough. **Talents are excluded**, the same
scope as `docs/ENDFIELD-STOCKPILE.md` and `docs/ENDFIELD-SANITY-YIELD.md` §B.

## Three things the raw data does that a reader must know

* `charLevelRules[89]` (level 90) is `gold: "-1", exp: "-1"` - a "no next level"
  sentinel, not a cost. Summing it blindly gives 385,419 / 1,792,289; the real
  totals are 385,420 / 1,792,290. `weaponLevelRules` ends in `0 / 0` instead.
* `material-list` names carried a trailing newline on 2026-08-28 (`"D96钢样品四\\n"`)
  and did not on 2026-09-18. Always `strip()`.
* A material the account holds none of is **absent** from `itemCount`, not zero
  (2026-09-18: 38 of 40 present). The page treats absent as 0.

## What "need" means per row

* 通用: the count is identical for every owned operator (or every weapon) - the
  number is exact for any build.
* Variable groups (high-tier materials, leaves, mushrooms, ores): one build uses one
  option of the group. `need` is the **largest** count any single operator or weapon
  uses (e.g. a high-tier material is 116 when it is one of the operator's two mains,
  20 as the third, 16 on a weapon; `need` = 116) and `note` spells the options out.
  人份 computed from it is therefore the conservative reading.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "relay"))

ZONAI = "https://zonai.skland.com"
ENV = Path.home() / ".config/ark/.env"
OUT_DEFAULT = REPO / "web" / "data" / "need.json"

GAME = "终末地"
GAME_ID = "endfield"
CALIBER = "一个干员：1→90 级、全部突破、四个技能到 12 级、武器 1→90 级；不含天赋"
SOURCE = ("森空岛 calculate/rules?charIds= 与 ?weaponIds= 逐个求和，"
          "material-list 取名字和图标；方法见 docs/ENDFIELD-SANITY-YIELD.md §B")
MAX_SKILL_LEVEL = 12
EXP_CHAR, EXP_WEAPON = "exp:char", "exp:weapon"

# Which sanity stage drops it. Read off MaaEnd's own item -> stage mapping
# (`SupplyPlanMain.json` `SupplyPlanOverride_*`) and `ItemTable.obtainWayIds`, as
# tabulated in docs/ENDFIELD-SANITY-YIELD.md §A. A material with no entry gets
# `stage: null` - unknown is written as unknown, never guessed.
STAGE = {
    "协议棱柱组": "技能提升 A", "协议棱柱": "技能提升 B",
    "协议圆盘组": "干员进阶 A", "协议圆盘": "干员进阶 B",
    "折金票": "钱币收集",
    "重型强固模具": "武器进阶 A", "强固模具": "武器进阶 B",
    "D96钢样品四": "高阶培养Ⅰ", "超距辉映管": "高阶培养Ⅱ", "快子遴捡晶格": "高阶培养Ⅲ",
    "象限拟合液": "高阶培养Ⅳ", "三相纳米片": "高阶培养Ⅴ",
    "存续的痕迹": "通行证 / 黄票商店 / 活动（不耗理智）",
    "高阶培养自选箱Ⅰ": "通行证（不耗理智）",
}
GATHER = "采集 / 帝江号仓库（不耗理智）"
# `ItemTable.obtainWayIds` = item_obtain_gather_* for every leaf, mushroom and stone
# (2026-06-22 dump; 协议纹石 is newer than the dump and stays unknown).
GATHERED = {"纯晶多齿叶", "至晶多齿叶", "晶化多齿叶", "受蚀玉化叶", "岩天使叶", "红矛叶",
            "重红柱状菌", "中红柱状菌", "轻红柱状菌", "星门菌", "血菌", "塔罗斯菌",
            "中黯石", "重黯石", "轻黯石", "武陵石", "燎石"}
HIGH_TIER = {"D96钢样品四", "超距辉映管", "快子遴捡晶格", "象限拟合液", "三相纳米片"}


def variable_group(name: str, op_used: list[int], w_used: list[int]) -> str:
    """Display name of the choice a build makes. High-tier materials: an operator
    takes two of the five at 116 and one at 20 (诀 takes 三相纳米片 as both, 136),
    a weapon takes one at 16. Leaves 84 / mushrooms 8 are the operator's choice of
    three, ores 8 the weapon's. Anything else is just 因人而异."""
    if name in HIGH_TIER:
        return "高阶素材（因人而异）"
    if op_used and not w_used:
        return {84: "叶（三选一）", 8: "菌（三选一）"}.get(max(op_used), "因人而异")
    if w_used and not op_used:
        return {8: "矿石（三选一）"}.get(max(w_used), "因人而异")
    return "因人而异"


class RulesSource:
    """Where the raw responses come from: Skland live, or a directory of saved ones."""

    def __init__(self, offline: Path | None, save: Path | None, subset: bool = False):
        self.offline, self.save, self.subset = offline, save, subset
        self.cred = None
        if offline is None:
            from ark_relay import skland  # noqa: PLC0415 - only the live path needs it
            self.skland = skland
            tok = next(line.split("=", 1)[1].strip()
                       for line in ENV.read_text(encoding="utf-8").splitlines()
                       if line.startswith("SKLAND_TOKEN="))
            self.cred = _retry(lambda: skland.refresh(skland.login(tok)))
            self.role = skland.endfield_role(self.cred)

    def get(self, name: str, path: str, query: str = "") -> dict:
        if self.offline is not None:
            return json.loads((self.offline / f"{name}.json").read_text(encoding="utf-8"))
        url = f"{ZONAI}{path}" + (f"?{query}" if query else "")

        def once():
            req = urllib.request.Request(url, headers=self.skland.sign_headers(self.cred, url))
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))

        d = _retry(once)
        if d.get("code") not in (0, None):
            raise RuntimeError(f"{path} → code {d.get('code')} {d.get('message')}")
        return d["data"]

    def keep(self, name: str, data: dict) -> None:
        """Save a response for `--offline`. Only what `build()` reads is kept: the
        card is cut down to id / name / rarity / equipped weapon (the full card is
        780 KB of talent trees and picture links), and a rules response loses its
        `talents` and its 90-row level tables - those two tables are identical in
        every response and are kept once as `level-rules.json`."""
        if self.save is None:
            return
        self.save.mkdir(parents=True, exist_ok=True)
        if name == "card":
            data = {"detail": {"chars": [
                {"id": c["id"],
                 "charData": {"name": c["charData"]["name"], "rarity": c["charData"]["rarity"]},
                 "weapon": {"weaponData": {k: v for k, v in ((c.get("weapon") or {}).get("weaponData") or {}).items()
                                           if k in ("id", "name")}}}
                for c in data["detail"]["chars"]]}}
        elif name.startswith("rules-"):
            lv = self.save / "level-rules.json"
            if not lv.exists():
                lv.write_text(json.dumps({k: data[k] for k in ("charLevelRules", "weaponLevelRules")},
                                         ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            data = {k: v for k, v in data.items() if k not in ("charLevelRules", "weaponLevelRules")}
            data["chars"] = [{k: v for k, v in c.items() if k != "talents"} for c in data.get("chars", [])]
        (self.save / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _retry(fn, tries=4, wait=2):
    """Tokyo -> Shanghai wobbles; a first TLS handshake timing out is routine."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - whatever it was, the next try may pass
            last = e
            if i < tries - 1:
                time.sleep(wait)
    raise last


def material_table(mat: dict) -> dict[str, dict]:
    """id -> {name, rarity, icon, exp, kind} for all 40 materials, names stripped."""
    out = {}
    for kind in ("charExpMaterials", "weaponExpMaterials", "materials"):
        for mid, m in mat[kind].items():
            out[mid] = {"name": str(m.get("name", "")).strip(),
                        "rarity": int(m["rarity"]["value"]) if m.get("rarity") else None,
                        "icon": m.get("icon", ""),
                        "exp": int(m.get("exp") or 0), "kind": kind}
    return out


def char_need(rule: dict) -> tuple[Counter, int]:
    """Materials and gold for every breakthrough plus every skill level up to 12."""
    c = rule["chars"][0]
    need, gold = Counter(), 0
    for b in c["breakthroughs"]:
        gold += int(b["gold"])
        for m in b["materials"]:
            need[m["resourceId"]] += int(m["count"])
    for s in c["skills"]:
        for lv in s["levels"]:
            if int(lv["targetLevel"]) <= MAX_SKILL_LEVEL:
                gold += int(lv["gold"])
                for m in lv["materials"]:
                    need[m["resourceId"]] += int(m["count"])
    return need, gold


def weapon_need(rule: dict) -> tuple[Counter, int]:
    w = rule["weapons"][0]
    need, gold = Counter(), 0
    for b in w["breakthroughs"]:
        gold += int(b["gold"])
        for m in b["materials"]:
            need[m["resourceId"]] += int(m["count"])
    return need, gold


def level_totals(rows: list[dict]) -> tuple[int, int]:
    """Gold and exp for 1 -> 90. Negative entries are the level-90 sentinel, skipped."""
    gold = sum(int(r["gold"]) for r in rows if int(r["gold"]) >= 0)
    exp = sum(int(r["exp"]) for r in rows if int(r["exp"]) >= 0)
    return gold, exp


def build(src: RulesSource, pulled_at: str) -> dict:
    card = src.get("card", "/api/v1/game/endfield/card/detail",
                   f"roleId={src.role[0]}&serverId={src.role[1]}" if src.cred else "")
    chars = card["detail"]["chars"]
    if src.subset:
        # The fixture set: every five-star plus one six-star (enough to reproduce
        # docs/ENDFIELD-SANITY-YIELD.md §B and to show six equals five), and the
        # weapons those operators wear.
        fives = [c for c in chars if c["charData"]["rarity"]["value"] == "5"]
        six = [c for c in chars if c["charData"]["rarity"]["value"] == "6"][:1]
        chars = fives + six
        card = {"detail": {"chars": chars}}
    src.keep("card", card)
    mat_raw = src.get("material-list", "/web/v1/game/endfield/calculate/material-list")
    src.keep("material-list", mat_raw)
    mat = material_table(mat_raw)
    ops = [(c["id"], c["charData"]["name"], int(c["charData"]["rarity"]["value"])) for c in chars]
    weapons: dict[str, str] = {}
    for c in chars:
        wd = (c.get("weapon") or {}).get("weaponData") or {}
        if wd.get("id"):
            weapons[wd["id"]] = wd.get("name", "")

    per_op: dict[str, tuple[Counter, int]] = {}
    level_rows = None
    for cid, name, _ in ops:
        rule = src.get(f"rules-char-{cid}", "/web/v1/game/endfield/calculate/rules", f"charIds={cid}")
        src.keep(f"rules-char-{cid}", rule)
        per_op[name] = char_need(rule)
        if level_rows is None and "charLevelRules" in rule:
            level_rows = (rule["charLevelRules"], rule["weaponLevelRules"])
    per_w: dict[str, tuple[Counter, int]] = {}
    for wid, wname in weapons.items():
        rule = src.get(f"rules-weapon-{wid}", "/web/v1/game/endfield/calculate/rules", f"weaponIds={wid}")
        src.keep(f"rules-weapon-{wid}", rule)
        per_w[wname] = weapon_need(rule)
    if level_rows is None and src.offline is not None:
        lv = json.loads((src.offline / "level-rules.json").read_text(encoding="utf-8"))
        level_rows = (lv["charLevelRules"], lv["weaponLevelRules"])
    if not per_op or not per_w or level_rows is None:
        raise RuntimeError("no operators or weapons on the card; nothing to build from")

    char_gold, char_exp = level_totals(level_rows[0])
    weap_gold, weap_exp = level_totals(level_rows[1])
    op_golds = {g for _, g in per_op.values()}
    w_golds = {g for _, g in per_w.values()}
    if len(op_golds) != 1 or len(w_golds) != 1:
        raise RuntimeError(f"breakthrough/skill gold differs between operators or weapons: {op_golds} {w_golds}")
    op_side = op_golds.pop() + char_gold        # breakthroughs + skills, then levels 1 -> 90
    w_side = w_golds.pop() + weap_gold
    gold_total = op_side + w_side

    rows = []
    for mid, m in mat.items():
        op_counts = [n.get(mid, 0) for n, _ in per_op.values()]
        w_counts = [n.get(mid, 0) for n, _ in per_w.values()]
        op_set, w_set = sorted(set(op_counts)), sorted(set(w_counts))
        row = {"id": mid, "name": m["name"], "rarity": m["rarity"], "icon": m["icon"],
               "need": None, "group": None, "stage": STAGE.get(m["name"]) or (GATHER if m["name"] in GATHERED else None),
               "note": None}
        if m["kind"] != "materials":
            row["exp"] = m["exp"]
            row["sumInto"] = EXP_CHAR if m["kind"] == "charExpMaterials" else EXP_WEAPON
            row["stage"] = "干员经验" if m["kind"] == "charExpMaterials" else "武器经验"
        elif m["name"] == "折金票":
            row.update(need=gold_total, group="通用", note=f"干员 {op_side:,} + 武器 {w_side:,}")
        elif op_set == [op_counts[0]] and op_counts[0] and not any(w_counts):
            row.update(need=op_counts[0], group="通用")
        elif w_set == [w_counts[0]] and w_counts[0] and not any(op_counts):
            row.update(need=w_counts[0], group="通用")
        elif any(op_counts) or any(w_counts):
            op_used = [x for x in op_set if x]
            w_used = [x for x in w_set if x]
            top = max(op_used + w_used)
            parts = []
            if op_used:
                parts.append("干员 " + " 或 ".join(str(x) for x in reversed(op_used)))
            if w_used:
                parts.append("武器 " + " 或 ".join(str(x) for x in reversed(w_used)))
            users = sum(1 for x in op_counts if x) + sum(1 for x in w_counts if x)
            row.update(need=top, group=variable_group(m["name"], op_used, w_used),
                       note=f"因人而异：{'，'.join(parts)}（{users} 个在用；人份按 {top} 算）")
        elif m["name"] == "高阶培养自选箱Ⅰ":
            row["note"] = "开出任意一种高阶素材，不计入人份"
        rows.append(row)
    rows.append({"id": EXP_CHAR, "name": "干员经验", "rarity": None, "icon": "", "need": char_exp,
                 "group": "通用", "stage": "干员经验", "virtual": True,
                 "note": "五种作战记录 / 认知载体按经验值折算"})
    rows.append({"id": EXP_WEAPON, "name": "武器经验", "rarity": None, "icon": "", "need": weap_exp,
                 "group": "通用", "stage": "武器经验", "virtual": True,
                 "note": "武器检查套组 / 装置 / 单元按经验值折算"})
    # 通用 first (the two exp rows among them), then the variable groups, then the
    # rows with no need of their own (the exp materials fold into exp:*, the box).
    rows.sort(key=lambda r: (0 if r["group"] == "通用" else 1 if r["need"] else 2,
                             -(r["need"] or 0), r["name"]))
    return {
        "built": pulled_at,
        "games": [{
            "game": GAME, "gameId": GAME_ID, "caliber": CALIBER, "source": SOURCE,
            "coverage": {"operators": [n for _, n, _ in ops], "weapons": sorted(weapons.values())},
            "rows": rows,
        }],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--offline", type=Path, help="directory of saved responses; no network")
    ap.add_argument("--save-fixtures", type=Path, help="keep the raw responses (trimmed, see RulesSource.keep) in this directory")
    ap.add_argument("--subset", action="store_true",
                    help="only the five-stars plus one six-star and their weapons (the test fixture set)")
    ap.add_argument("-o", "--out", type=Path, default=OUT_DEFAULT)
    a = ap.parse_args(argv)
    src = RulesSource(a.offline, a.save_fixtures, a.subset)
    stamp = time.strftime("%Y-%m-%d %H:%M %Z")
    if a.offline is not None:
        meta = a.offline / "pulled-at.txt"
        stamp = meta.read_text(encoding="utf-8").strip() if meta.exists() else stamp
    elif a.save_fixtures is not None:
        a.save_fixtures.mkdir(parents=True, exist_ok=True)
        (a.save_fixtures / "pulled-at.txt").write_text(stamp + "\n", encoding="utf-8")
    table = build(src, stamp)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    g = table["games"][0]
    uni = sum(1 for r in g["rows"] if r["group"] == "通用")
    print(f"✅ {a.out}: {len(g['rows'])} rows ({uni} 通用), "
          f"{len(g['coverage']['operators'])} operators, {len(g['coverage']['weapons'])} weapons, built {table['built']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
