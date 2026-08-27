#!/usr/bin/env python3
"""武器基质核对：实装词条 vs 武器自己要的。**按 id 比，不按中文比。**

    python3 scripts/mac/gem-check.py            # 限定 6★ + 管理员（默认）
    python3 scripts/mac/gem-check.py --six       # 全部 6★（含常驻）
    python3 scripts/mac/gem-check.py --all       # 全部干员

## 一、「推荐词条」这四个字有歧义

基质词条不是攻略口味。武器在森空岛接口里**自己声明**要哪三条——
`weaponData.skillInfos[].gemTagId` 配 `maxLevel`（熔铸火焰要
attr_wisd(9) / attr_atk(9) / ult(4)）。装错那一条就是白给。

CEP 的 `src/data/weapons.ts` 里 `primaryStat` / `elementalDamage` /
`specialAbility` 三个字段是同一份数据的转录，不是它自己的推荐——
本账号 25 把武器 71 个词条位逐位核对，去掉 `gat_passive_`/`gst_passive_`
前缀后与森空岛 `gemTagId` **71/71 相等，顺序也一一对应**。

## 二、为什么不能按中文比（2026-08-28 差点又栽在这）

森空岛**自己两处命名就不一致**：

    tagId              武器技能栏          基质词条栏
    attr_magicdam      法术提升            法术伤害提升
    attr_physpell      源石技艺强度提升     源石技艺提升

按中文比会把**装对了的**判成「词条不符」。所以这里：

* 武器要什么 → 直接读 `gemTagId`，不翻译；
* 实装了什么 → 基质词条只有中文和 hash id，用 CEP 的 gemStats 中文表
  反查成 CEP id（账号内 25/25 全覆盖，且 CEP 中文→id 唯一），再剥前缀成 tagId；
* 然后 **tagId 比 tagId**。

**显示也一律用 CEP 的中文**，两栏同一套叫法，森空岛那两个异名不出现在输出里。

中文字段的确切位置和出处（`scripts/lib/generate-stat-i18n.ts` 里写着）：

    src/generated/i18n/gemStats/zh-CN.json      ← 就是这个文件，31 条
      ↑ 由 sync-game-data 生成，来源是游戏本体：
        TableCfg/GemTable.json  取 /"(g[as]t_\w+)":/ 作 key
        再用该条的 tagName.id 去 TextTable 查中文

也就是说这张表的 key 是**游戏自己的 GemTable 键名**、值是**游戏自己的文本表**，
不是 CEP 写的译名。`weapons.ts` 行内只有 id（三个词条字段 31 个取值全是 id
加 null），中文分离在 i18n 表里，是正常的 i18n 结构，不是它没有中文。

三处「查不到」全部当场报错，不许静默跳过——静默跳过会让「没报不一致」
退化成「压根没比」。见 [[idmap-no-guessing]]、[[known-issue-is-not-an-excuse]]。

## 三、`cost` 是什么（2026-08-28 查证，此前是我自己认定的）

`terms[].cost` 是**该词条的加成级数**，不是固定属性——同一词条在不同基质上
取值不同（攻击提升在本账号出现过 1 / 2 / 6）。上限两套：

    属性词条（CEP id 以 gat_ 开头）  最高 6 级
    技能词条（CEP id 以 gst_ 开头）  最高 3 级
    → 满配 6 + 6 + 3 = 15

出处：游民星空《明日方舟终末地 武器基质系统详解》原文「基质的技能属性至多
加成 3 级，而其余两个词条可以至多加成 6 级」
<https://www.gamersky.com/handbook/202602/2092299.shtml>；
并经本账号 19 个基质 57 条词条实例交叉验证，无一越界。

别和 `skillInfos[].maxLevel`（9/9/4）混：那是蚀刻强化后武器上单个词条能到的
总级数，基质只贡献其中的 6/6/3 部分。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from snapshot import load  # noqa: E402

CEP = "https://raw.githubusercontent.com/cmyyx/cep/main/src/"
# 单条词条的级数上限，按词条类型分。见上面「三、cost 是什么」。
CAP = {"gat": 6, "gst": 3}
PROTAGONIST = "管理员"              # 主角不走卡池，既非限定也非常驻，单独放行


def _fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8")


def _cap(cep_id: str) -> int:
    """这条词条最高能到几级。"""
    return CAP[cep_id.split("_", 1)[0]]


def _tag(cep_id: str) -> str:
    """CEP id → 森空岛 gemTagId。前缀关系在 verify() 里每次跑都重新验证。"""
    return re.sub(r"^(gat|gst)_passive_", "", cep_id)


def cep_tables() -> tuple[dict[str, list[str]], dict[str, str], dict[str, str]]:
    """(武器名 → 三个 CEP id, 中文 → CEP id, tagId → 中文)。"""
    zh = json.loads(_fetch(CEP + "generated/i18n/gemStats/zh-CN.json"))
    rev: dict[str, str] = {}
    for cid, name in zh.items():
        if name in rev:
            raise SystemExit(f"CEP gemStats 里「{name}」对应多个 id "
                             f"（{rev[name]} 和 {cid}），中文反查不再唯一，"
                             f"这个脚本的前提塌了，先去看数据。")
        rev[name] = cid
    tag2zh = {_tag(cid): name for cid, name in zh.items()}

    src = _fetch(CEP + "data/weapons.ts")
    wt: dict[str, list[str]] = {}
    for m in re.finditer(r"\{\s*id:.*?\}", src, re.S):
        row = m.group(0)

        def f(key: str) -> str:
            # 低星武器只有两个词条位，CEP 写 null——不能当空字符串，
            # 否则会误报「CEP 和武器声明不一致」（2026-08-28 误报过奥佩罗77）。
            mm = re.search(rf"{key}:\s*(?:'([^']*)'|null)", row)
            return (mm.group(1) or "") if mm else ""

        n = f("name")
        if n:
            wt[n] = [x for x in (f("primaryStat"), f("elementalDamage"),
                                 f("specialAbility")) if x]
    return wt, rev, tag2zh


def standard_chars() -> set[str]:
    """常驻 6★ 名单。**现拉，不写死**——池子会变。"""
    m = re.search(r"STANDARD_CHARS\s*=\s*\[([^\]]*)\]",
                  _fetch(CEP + "data/banner.ts"))
    if not m:
        raise SystemExit("CEP 的 banner.ts 里找不到 STANDARD_CHARS 了，"
                         "格式变了——去看一眼再改这里，别猜。")
    return set(re.findall(r"'([^']+)'", m.group(1)))


def verify(chars: list[dict], cep_w: dict[str, list[str]]) -> str:
    """每次运行都重新证明「CEP id 剥前缀 == 森空岛 gemTagId」。

    这个等式是整个脚本的地基。它哪天不成立了必须当场炸，
    而不是安安静静地给出错误结论。
    """
    n = ok = 0
    seen = set()
    for c in chars:
        w = c.get("weapon")
        if not w:
            continue
        wd = w["weaponData"]
        if wd["name"] in seen:
            continue
        seen.add(wd["name"])
        ce = cep_w.get(wd["name"])
        if ce is None:
            raise SystemExit(f"CEP 的武器表里没有「{wd['name']}」——"
                             f"无法核对。去 cmyyx/cep 看是不是还没收录。")
        sk = wd["skillInfos"]
        if len(sk) != len(ce):
            raise SystemExit(f"「{wd['name']}」词条位数对不上："
                             f"森空岛 {len(sk)} 个，CEP {len(ce)} 个。")
        for si, cid in zip(sk, ce):
            n += 1
            ok += _tag(cid) == si["gemTagId"]
    if ok != n:
        raise SystemExit(f"地基塌了：{n} 个词条位里只有 {ok} 个满足"
                         f"「CEP id 剥前缀 == gemTagId」。这个脚本的比对方式"
                         f"不再可靠，先查数据，别信下面任何结论。")
    return f"（已验证 {len(seen)} 把武器 {n} 个词条位：CEP id 与森空岛 tagId 全等）"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--six", action="store_true", help="全部 6★（含常驻）")
    ap.add_argument("--all", action="store_true", help="全部干员")
    ns = ap.parse_args(argv[1:])

    card = load("card")
    chars = card["detail"]["chars"]
    cep_w, zh2id, tag2zh = cep_tables()
    print(verify(chars, cep_w))

    std = set() if (ns.all or ns.six) else standard_chars()
    if std:
        print(f"（只看限定 6★ + {PROTAGONIST}；已排除常驻 "
              f"{'、'.join(sorted(std))}）")

    rows = []
    for c in chars:
        cd = c["charData"]
        name = cd["name"]
        if not ns.all and cd["rarity"]["value"] != "6":
            continue
        if std and name in std and not name.startswith(PROTAGONIST):
            continue

        w = c.get("weapon")
        if not w:
            rows.append((name, "—", "❌ 没有装武器", "", ""))
            continue
        wd = w["weaponData"]

        want = [si["gemTagId"] for si in wd["skillInfos"]]
        # 显示用 CEP 的中文，不用森空岛武器栏的——后者和基质栏不是一套叫法。
        want_zh = [tag2zh.get(t, f"?{t}") for t in want]

        gem = w.get("gem")
        if gem:
            have_zh = [t["name"] for t in gem["terms"]]
            unknown = [t for t in have_zh if t not in zh2id]
            if unknown:
                raise SystemExit(
                    f"「{name} / {wd['name']}」的基质词条 {unknown} 在 CEP 的"
                    f" gemStats 中文表里查不到，翻不成 id。**不许按字面猜**——"
                    f"去 cmyyx/cep 更新 gemStats，或找别的权威对照表。")
            have = [_tag(zh2id[t]) for t in have_zh]
            lv = {_tag(zh2id[t["name"]]): t["cost"] for t in gem["terms"]}
            have_zh = [tag2zh[t] for t in have]      # 统一成 CEP 的叫法
            caps = {t: _cap(zh2id[n]) for t, n in zip(have, have_zh)}
        else:
            have, have_zh, lv, caps = [], [], {}, {}

        if not gem:
            verdict = "❌ 没有基质"
        elif sorted(have) != sorted(want):
            miss = [tag2zh.get(t, t) for t in want if t not in have]
            verdict = f"❌ 词条不符（缺 {'/'.join(miss)}）"
        else:
            low = [f"{tag2zh[t]} {lv[t]}/{caps[t]}"
                   for t in have if lv[t] < caps[t]]
            verdict = ("✅ 三条齐全且全部满级"
                       if not low else "⚠️ 词条对但没满级：" + "、".join(low))

        detail = "/".join(f"{tag2zh[t]}{lv[t]}" for t in have) or "无"
        rows.append((name, wd["name"], verdict, "/".join(want_zh), detail))

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
    print(f"\n{ok}/{len(rows)} 三条齐全且全部满级")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
