#!/usr/bin/env python3
"""Build the need table by hand (the relay rebuilds it once a server day on its own;
see relay/ark_relay/features/needtable/). Live reads SKLAND_TOKEN from ~/.config/ark/.env.

    python3 scripts/mac/build-need-tables.py                          # live -> web/data/need.json
    python3 scripts/mac/build-need-tables.py --save-fixtures DIR      # live, and keep the (trimmed) responses
    python3 scripts/mac/build-need-tables.py --offline DIR -o FILE    # rebuild from the saved responses
    python3 scripts/mac/build-need-tables.py --rarity 5               # the newest five-star instead
    python3 scripts/mac/build-need-tables.py --char 莱万汀 --weapon 熔铸火焰   # a named pair instead
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "relay"))

from ark_relay.features.needtable import build  # noqa: E402

ENV = Path.home() / ".config/ark/.env"
OUT_DEFAULT = REPO / "web" / "data" / "need.json"


def env_token() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("SKLAND_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the newest six-star's need table")
    ap.add_argument("--offline", type=Path, help="directory of saved responses; no network")
    ap.add_argument("--save-fixtures", type=Path, help="keep the (trimmed) responses in this directory")
    ap.add_argument("--char", default="", help="build for this operator instead of the newest")
    ap.add_argument("--weapon", default="", help="weapon name (must be in the calculator); default: her signature weapon")
    ap.add_argument("--rarity", default="6", choices=("6", "5", "4"), help="which rarity the newest operator is taken from (default 6)")
    ap.add_argument("--today", default="", help="server date YYYY-MM-DD for the 已实装/未实装 label (default: now, UTC+8)")
    ap.add_argument("-o", "--out", type=Path, default=OUT_DEFAULT)
    a = ap.parse_args(argv)
    src = build.RulesSource(a.offline, a.save_fixtures, "" if a.offline is not None else env_token())
    table = build.make(src, today=a.today, char_name=a.char, weapon_name=a.weapon, rarity=a.rarity)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"✅ {a.out}: {build.summary(table)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
