# -*- coding: utf-8 -*-
"""reg-from-status.py [<board-dir>] [<remote-ref-dir>] — registry rows from the four session status files (T6, BOARD WORKLIST).
Every status line that says 完成 yields one row: 编号 · 谁 · 类型（接 = has a commit sha / 读 = names a .md § / 核 = a probe
file / 文档）· 产物 · 状态. Rows whose 编号 already appears in a hand-written table of index.md are skipped; the rest are
written into ONE generated section at the end of index.md and of RENDER-PIPELINE.md (between the markers below), which is
replaced on every run — the hand-written sections are never touched. A row that lands in RENDER-PIPELINE's generated
section still needs a human to move it into its control group (the script cannot know the control)."""
import re, sys, pathlib, datetime
board = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path.home() / "Money/styl-work/BOARD")
ref = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else pathlib.Path.home() / "Money/styl-work/remote-ref")
ID = re.compile(r'^[-*\s]*\**\s*((?:R|A|B|G|T|#)\d*[a-z]?[′″‴⁗]*(?:[①-⑨]|[a-z])?[′″‴⁗]*)\b')
SHA = re.compile(r'\b(?:ui2|ui|data|night|commit|night-老网页)\s+([0-9a-f]{7})\b')
MD = re.compile(r'([\w./-]+\.md)(?:\s*(§[\w.①-⑨′″‴⁗ ]+?))?(?=[，；、：:）(\s]|$)')
JSON = re.compile(r'([\w./-]+\.(?:json|png|mov))')
rows = {}
for f in sorted(board.glob("status-*.md")):
    who = f.stem.replace("status-", "")
    for line in f.read_text(encoding="utf-8").splitlines():
        if "完成" not in line: continue
        m = ID.match(line)
        if not m: continue
        rid = m.group(1)
        if rid in ("R", "A", "B", "G", "T", "#"): continue
        sha = SHA.search(line); md = MD.search(line); js = JSON.search(line)
        kind = "接" if sha else ("读" if md and who == "老网页" else ("核" if (js or md) and who == "数据" else ("读 / 接" if md else "文档")))
        prod = (f"{who.replace('2号', 'ui2') if False else ''}" + (f"{sha.group(0)}" if sha else "")) + ((" · " if sha and md else "") + (md.group(1) + (" " + md.group(2).strip() if md.group(2) else "") if md else ""))
        if not prod: prod = line.split("完成", 1)[1].strip()[:80]
        state = "部分" if "部分" in line or "未定位" in line or "停" in line.split("完成", 1)[1][:60] else ("已合" if sha else "完成")
        rows.setdefault(rid, {"who": set(), "kind": set(), "prod": [], "state": state})
        r = rows[rid]; r["who"].add(who); r["kind"].add(kind)
        if prod not in r["prod"]: r["prod"].append(prod)
def key(rid):
    n = re.search(r'\d+', rid); return (int(n.group()) if n else 0, rid)
def gen(path, title, skip_present, only_wired=False):
    s = path.read_text(encoding="utf-8")
    marker = f"\n## {title}（reg-from-status.py"
    i = s.find(marker); hand = s[:i] if i >= 0 else s          # the hand-written part only: the generated block never counts as "present"
    present = set(re.findall(r'^\|\s*([^|]+?)\s*\|', hand, re.M)) if skip_present else set()
    present_ids = set()
    for cell in present:
        for tok in re.split(r'\s*/\s*', cell): present_ids.add(tok.strip().strip("*"))
    out = [f"\n## {title}（reg-from-status.py，{datetime.datetime.now():%Y-%m-%d %H:%M} 自动生成，勿手改；手写节里已有的编号不重复）\n",
           "| # | 谁 | 类型 | 产物（文件 § / commit） | 状态 |", "|---|---|---|---|---|"]
    n = 0
    for rid in sorted(rows, key=key):
        if rid in present_ids: continue
        r = rows[rid]
        if only_wired and '接' not in r['kind']: continue
        n += 1
        out.append(f"| {rid} | {' / '.join(sorted(r['who']))} | {' / '.join(sorted(r['kind']))} | {'；'.join(r['prod'])[:220]} | {r['state']} |")
    block = "\n".join(out) + "\n"
    s = (hand if i >= 0 else s.rstrip("\n") + "\n") + block
    path.write_text(s, encoding="utf-8"); return n
a = gen(ref / "index.md", "脚本登记：status 里完成而手写节未登的件", True)
b = gen(ref / "RENDER-PIPELINE.md", "13 脚本补（接线件，未归组，等人挪进控件组）", True, only_wired=True)
print(f"status 完成行 {len(rows)} 件 → index.md 补 {a} 行、RENDER-PIPELINE.md 补 {b} 行")
