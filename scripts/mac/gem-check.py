#!/usr/bin/env python3
"""武器基质核对：实际词条 vs 武器自己要的 vs CEP 记的。

    python3 scripts/mac/gem-check.py            # 只看 6★
    python3 scripts/mac/gem-check.py --all

**「推荐词条」这四个字有歧义，先说清楚**（2026-08-28 查证）：

基质词条不是攻略口味问题。武器在森空岛接口里**自己声明**了它要哪三条——
`weaponData.skillInfos[].gemTagId` 配 `maxLevel`，例如熔铸火焰要
智识提升(9) / 攻击提升(9) / 夜幕(4)。装错词条那一条就是白给。

CEP 的 `src/data/weapons.ts` 里每把武器的 `primaryStat` /
`elementalDamage` / `specialAbility` 三个字段，就是同一份数据的转录，
不是它自己的推荐。所以这里同时打三列，**如果 CEP 和武器声明对不上，
以武器声明为准**——那说明 CEP 的数据过期了。

对照全部走中文名，不做 id 推导：森空岛给的武器技能和基质词条都自带中文，
CEP 的 id 用 `idmap` 里登记过的 gemStats 表翻译。见 [[idmap-no-guessing]]。

满配 = 三条齐全且 cost 6/6/3 = 15。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from snapshot import load  # noqa: E402

CEP_WEAPONS = ("https://raw.githubusercontent.com/cmyyx/cep/main/"
               "src/data/weapons.ts")
CEP_GEMSTATS = ("https://raw.githubusercontent.com/cmyyx/cep/main/"
                "src/generated/i18n/gemStats/zh-CN.json")

# 满配基质的三条 cost。来源：森空岛接口里实际返回的 terms[].cost。
FULL_COST = 15


def cep_data() -> tuple[dict, dict]:
    """拉 CEP 的武器表和词条中文表。"""
    def fetch(url: str) -> str:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read().decode("utf-8")

    names = json.loads(fetch(CEP_GEMSTATS))
    src = fetch(CEP_WEAPONS)
    out = {}
    for m in re.finditer(r"\{\s*id:.*?\}", src, re.S):
        row = m.group(0)
        def f(key: str) -> str:
            # 低星武器只有两个词条位，CEP 用 null 表示——不能当成空字符串，
            # 否则会误报「CEP 和武器声明不一致」（2026-08-28 就误报过奥佩罗77）。
            mm = re.search(rf"{key}:\s*(?:'([^']*)'|null)", row)
            return mm.group(1) or "" if mm else ""
        n = f("name")
        if n:
            out[n] = [x for x in (f("primaryStat"), f("elementalDamage"),
                                  f("specialAbility")) if x]
    return out, names


def strip_grade(s: str) -> str:
    """「智识提升·大」→「智识提升」；「夜幕·嘶鸣烈火」→「夜幕」。"""
    return s.split("·")[0]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="不限 6★")
    ns = ap.parse_args(argv[1:])

    card = load("card")
    cep_w, cep_zh = cep_data()

    rows, problems = [], []
    for c in card["detail"]["chars"]:
        cd = c["charData"]
        if not ns.all and cd["rarity"]["value"] != "6":
            continue
        w = c.get("weapon")
        if not w:
            rows.append((cd["name"], "—", "没有装武器", "", ""))
            continue
        wd = w["weaponData"]
        wname = wd["name"]

        want = [strip_grade(si["skill"]["value"]) for si in wd["skillInfos"]]
        gem = w.get("gem")
        have = [t["name"] for t in gem["terms"]] if gem else []
        cost = sum(t["cost"] for t in gem["terms"]) if gem else 0

        cep_ids = cep_w.get(wname)
        cep = [cep_zh.get(i, f"?{i}") for i in cep_ids] if cep_ids else None

        if cep and sorted(cep) != sorted(want):
            problems.append(f"CEP 记的和武器自己声明的不一致：{wname}　"
                            f"CEP={'/'.join(cep)}　武器={'/'.join(want)}")

        if not gem:
            verdict = "❌ 没有基质"
        elif sorted(have) != sorted(want):
            miss = [x for x in want if x not in have]
            extra = [x for x in have if x not in want]
            verdict = "❌ 词条不符"
            if miss:
                verdict += f"（缺 {'/'.join(miss)}"
                verdict += f"，多 {'/'.join(extra)}）" if extra else "）"
        elif cost < FULL_COST:
            verdict = f"⚠️ 词条对但没满级（{cost}/{FULL_COST}）"
        else:
            verdict = "✅ 满配"

        rows.append((cd["name"], wname, verdict,
                     "/".join(want), "/".join(have) or "无"))

    w1 = max(len(r[0]) for r in rows)
    print(f"\n{'干员':<{w1}}  {'武器':<10}  结论")
    print("─" * 78)
    for name, wname, verdict, want, have in sorted(
            rows, key=lambda r: (r[2].startswith("✅"), r[0])):
        print(f"{name:<{w1}}  {wname:<10}  {verdict}")
        if not verdict.startswith("✅"):
            print(f"{'':<{w1}}  {'':<10}  武器要：{want}")
            print(f"{'':<{w1}}  {'':<10}  实际装：{have}")

    ok = sum(1 for r in rows if r[2].startswith("✅"))
    print(f"\n{ok}/{len(rows)} 满配")
    if problems:
        print("\nCEP 数据与武器声明不一致（以武器声明为准）：")
        for p in problems:
            print("  · " + p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
