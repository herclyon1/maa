#!/usr/bin/env python3
"""id → 含义 的唯一查询入口。查不到就报错，**绝不允许自己填**。

    idmap.py get gst_passive_ult                 # 查一个
    idmap.py get gst_passive_ult gst_passive_crit
    idmap.py add <key> <中文> --source <URL或文件路径> --note <一句话>
    idmap.py list [前缀]
    idmap.py check                               # 自检：每条都有来源吗

**为什么存在**（2026-08-28，同一类错的第二次，第一次是 826 事故）：

我在没有任何映射表的情况下，把 cep 的 `gst_passive_tactic` 和用户账号里的
「压制」**按位置对齐**，然后写成「所以内部 id 到中文名的对应是……」。
那个「所以」是伪装成推理的猜测。三条全蒙对了——**这比猜错更危险**，
因为没人会发现，我也不会反省，下次照样干。

而这套 id 从字面根本推不出来：

    gst_passive_keyword  → 效益      （不是「关键词」）
    gst_passive_crit     → 切骨      （不是「暴击」）
    gst_passive_phyabn   → 巧技      （不是「物理异常」）
    gst_passive_tacafter → 流转      （和 tactic 只差五个字母，含义完全不同）

用户的原话：「你对密码、cdk 这种东西这么上心，对我真正的财产瞎几把搞」。
角色练度、材料、配装是真实资产，翻错一个 id 就可能刷错东西、烧错材料。

## 规矩

1. **要翻译 id，只能走这里。** `get` 查不到会以非零退出并报错。
2. **每条都必须有 `source`。** 没有来源的条目 `check` 会判失败。
3. **禁止「看起来对得上」就登记。** 来源必须是权威映射文件／官方接口，
   不是「我把两个列表按位置对齐了」。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 登记表跟着仓库走，别放临时目录——它是长期资产。
# IDMAP_STORE 只给 guardcheck 用（自检要往表里写坏样本，不能污染真表）。
STORE = Path(os.environ.get("IDMAP_STORE")
             or Path(__file__).resolve().parents[3] / "data" / "idmap.json")


def _load() -> dict:
    if not STORE.is_file():
        return {}
    return json.loads(STORE.read_text(encoding="utf-8"))


def _save(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True),
                     encoding="utf-8")


def get(keys: list[str]) -> int:
    """查。任何一个查不到就整体失败——宁可停下，也不许半懂半猜地往下走。"""
    d = _load()
    missing = []
    for k in keys:
        e = d.get(k)
        if e is None:
            missing.append(k)
            continue
        print(f"{k}\t{e['value']}\t（来源：{e['source']}）")
    if missing:
        print(f"\n❌ 这 {len(missing)} 个 id 没有登记：" + "、".join(missing),
              file=sys.stderr)
        print("   **不许自己猜含义。**先找到权威映射表（官方接口的 enums、"
              "项目的 i18n 文件、locale/po），再用 add 登记：", file=sys.stderr)
        print(f"   idmap.py add {missing[0]} <中文> --source <URL或文件路径>",
              file=sys.stderr)
        return 1
    return 0


def add(key: str, value: str, source: str, note: str = "") -> int:
    if not source.strip():
        print("❌ 必须给 --source。没有来源的登记就是猜。", file=sys.stderr)
        return 2
    d = _load()
    old = d.get(key)
    if old and old["value"] != value:
        print(f"⚠️ {key} 已登记为「{old['value']}」（来源 {old['source']}），"
              f"现在要改成「{value}」。确认无误再改。", file=sys.stderr)
    d[key] = {"value": value, "source": source.strip(),
              **({"note": note} if note else {})}
    _save(d)
    print(f"✅ {key} → {value}　来源 {source}")
    return 0


def lst(prefix: str = "") -> int:
    d = _load()
    hits = {k: v for k, v in d.items() if k.startswith(prefix)}
    print(f"共 {len(hits)} 条" + (f"（前缀 {prefix}）" if prefix else ""))
    for k, v in sorted(hits.items()):
        print(f"  {k:<32} {v['value']:<12} {v['source'][:52]}")
    return 0


def check() -> int:
    """每条都得有来源；来源不能是「推断」「对齐」这类词。"""
    d = _load()
    bad = []
    FORBIDDEN = ("推断", "对齐", "猜", "看起来", "应该是", "guess", "infer")
    for k, v in d.items():
        s = (v.get("source") or "").strip()
        if not s:
            bad.append(f"  {k}：没有来源")
        elif any(w in s for w in FORBIDDEN):
            bad.append(f"  {k}：来源写的是「{s}」——这不是来源，是猜")
    if bad:
        print(f"❌ {len(bad)} 条不合格：")
        print("\n".join(bad))
        return 1
    print(f"idmap: {len(d)} 条，全部有来源")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get"); g.add_argument("keys", nargs="+")
    a = sub.add_parser("add")
    a.add_argument("key"); a.add_argument("value")
    a.add_argument("--source", required=True)
    a.add_argument("--note", default="")
    l = sub.add_parser("list"); l.add_argument("prefix", nargs="?", default="")
    sub.add_parser("check")
    ns = p.parse_args(argv[1:])
    if ns.cmd == "get":
        return get(ns.keys)
    if ns.cmd == "add":
        return add(ns.key, ns.value, ns.source, ns.note)
    if ns.cmd == "list":
        return lst(ns.prefix)
    return check()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
