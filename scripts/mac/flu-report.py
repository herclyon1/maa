#!/usr/bin/env python3
"""Pull the phone's fluency records (web/fluency-rec.js) off COS and print the table.

    scripts/mac/flu-report.py                      # pull new records, table over everything pulled
    scripts/mac/flu-report.py --at 04:21           # only gestures within 5 min of 04:21 Tokyo (today; --date 20260926 for another day)
    scripts/mac/flu-report.py --ctl 开关 --mode test  # a control name substring; only 流畅度实测 records (or auto)
    scripts/mac/flu-report.py --no-pull --dir DIR  # read DIR/*.json instead of pulling (the simulator proof)

Every gesture is one summary line (D79 K11); frames come only within 10 s of a rule hit. Pulling is scripts/mac/diag-pull.py (the same bucket, signed reader); the records land in ~/Claude/ark-diag/flu/.
Grades are Apple's Hitches metric lines (developer.apple.com/documentation/xcode/understanding-hitches-in-your-app,
read 2026-09-26): hitch rate <= 10 ms/s good, <= 25 warning, <= 50 critical, > 50 immediate attention. A phone's
number is a real device's; the simulator's is not graded anywhere else (D78 §4).
"""
import argparse
import importlib.util
import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKYO = timezone(timedelta(hours=9))
DEST = Path.home() / "Claude" / "ark-diag" / "flu"


def grade(h: float) -> str:
    return "好" if h <= 10 else "警告" if h <= 25 else "严重" if h <= 50 else "马上处理"


def hms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TOKYO).strftime("%m-%d %H:%M:%S.%f")[:-3]


def load(d: Path) -> list:
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if rec.get("kind") != "flu":
            continue
        for ln in rec.get("lines", []):
            ln["_mode"], ln["_file"] = rec.get("mode"), f.name
            out.append(ln)
    seen, uniq = set(), []                                  # overlapping anomaly segments carry the same line twice
    for ln in sorted(out, key=lambda x: x["at"]):
        k = (ln["at"], ln.get("ctl"), ln.get("pn"))
        if k not in seen:
            seen.add(k)
            uniq.append(ln)
    return uniq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", help="HH:MM Tokyo; keeps gestures within 5 min")
    ap.add_argument("--date", help="YYYYMMDD for --at (default today, Tokyo)")
    ap.add_argument("--ctl", help="control name substring")
    ap.add_argument("--mode", choices=["auto", "test"])
    ap.add_argument("--dir", type=Path, default=DEST)
    ap.add_argument("--no-pull", action="store_true")
    a = ap.parse_args()
    if not a.no_pull:
        spec = importlib.util.spec_from_file_location("diag_pull", HERE / "diag-pull.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()
    ls = load(a.dir)
    if a.at:
        day = a.date or datetime.now(TOKYO).strftime("%Y%m%d")
        t0 = datetime.strptime(day + a.at, "%Y%m%d%H:%M").replace(tzinfo=TOKYO).timestamp() * 1000
        ls = [x for x in ls if abs(x["at"] - t0) <= 5 * 60e3]
    if a.ctl:
        ls = [x for x in ls if a.ctl in (x.get("ctl") or "")]
    if a.mode:
        ls = [x for x in ls if x["_mode"] == a.mode]
    if not ls:
        print("没有符合条件的记录。")
        return 0
    print(f"共 {len(ls)} 个手势，{hms(ls[0]['at'])} – {hms(ls[-1]['at'])}（东京），版本 {sorted({x.get('v') for x in ls})}")

    print("\n按手势（卡顿率 = 卡顿毫秒合计 ÷ 动的时长合计；苹果线 ≤10 好 / ≤25 警告 / ≤50 严重 / >50 马上处理）")
    print(f"{'控件':<16}{'种类':<8}{'次数':>4}{'卡顿率ms/s':>11}  {'等级':<6}{'最长帧':>6}{'>50ms帧':>8}{'首变中位ms':>11}")
    groups = {}
    for x in ls:
        groups.setdefault((x.get("ctl") or "（空白处）", x.get("kind")), []).append(x)
    rows = []
    for (ctl, kind), xs in groups.items():
        span = sum(x["span"] for x in xs)
        rate = sum(x["hitch"] * x["span"] for x in xs) / span if span else 0
        firsts = [x["first"] for x in xs if x.get("first") is not None]
        rows.append((rate, ctl, kind, len(xs), max((x.get("max") or 0) for x in xs), sum(x.get("n50", 0) for x in xs),
                     statistics.median(firsts) if firsts else None))
    for rate, ctl, kind, n, mx, n50, fm in sorted(rows, reverse=True):
        print(f"{ctl:<16}{kind:<8}{n:>4}{rate:>11.1f}  {grade(rate):<6}{mx:>6}{n50:>8}{'' if fm is None else round(fm):>11}")

    print("\n最慢的 5 次（按卡顿率，再按最长帧）")
    for x in sorted(ls, key=lambda x: (x["hitch"], x.get("max") or 0), reverse=True)[:5]:
        print(f"  {hms(x['at'])}  {x.get('ctl') or '（空白处）'}·{x.get('kind')}  标签 {x.get('tab')} 班次 {x.get('shift')}  "
              f"首变 {x.get('first')} ms  最长帧 {x.get('max')}  >50ms {x.get('n50')} 帧  卡顿率 {x['hitch']} ms/s  {'异常 ' + ','.join(x['bad']) if x.get('bad') else ''}")

    bad = [x for x in ls if x.get("bad")]
    print(f"\n命中规则 {len(bad)} 行，按「规则 + 控件」合并、按次数排，前 10（D79 K12）")
    print("  规则：err 报错 / dead 点了 1 秒没反应 / rage 2 秒连点 3 次 / undo 马上改回 / reopen 点完或回前台就下拉刷新 / long 帧>100ms / "
          "slow 首变>200ms / late 弹层抬手后>100ms / noanim 开关没动画 / stall 弹层没动画就出现 / tabfix tabmiss swdraw blocked 页面自检 / "
          "flash 某层一帧变白又回来 / dot 可见层缩到 0.2 以下 / scrimlate 暗幕比面板晚 2 帧以上 / hlshort 行高亮不到原生一半 / tabsel 按住时选中了别的标签（逐帧）/ 其余为外观的显示规则")
    groups = {}
    for x in bad:
        rules = set(x["bad"])
        for p in (x.get("page") or []) + (x.get("frm") or []):
            groups.setdefault((p["rule"], p.get("ctl") or x.get("ctl") or "（空白处）"), []).append(x)
            rules.discard(p["rule"])
        for r in rules:
            groups.setdefault((r, x.get("ctl") or "（空白处）"), []).append(x)
    for (rule, ctl), xs in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:10]:
        x = xs[-1]
        extra = f"  报错 {x['err']}" if x.get("err") else ""
        extra += "  " + "；".join(f"{p['rule']} {p.get('ctl')} {p.get('note')}" for p in (x.get("page") or []) + (x.get("frm") or []) if p["rule"] == rule)
        print(f"  {len(xs):>3} 次  {rule:<14}{ctl}  最近 {hms(x['at'])}  标签 {x.get('tab')} 班次 {x.get('shift')}  首变 {x.get('first')} / 区域 {x.get('near')} ms  "
              f"弹层抬手后 {x.get('scene_up')}  最长帧 {x.get('max')}  开关 {x.get('sw')}  {'带逐帧' if any(y.get('fi') for y in xs) else ''}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
