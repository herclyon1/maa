#!/usr/bin/env python3
"""A diagnostic record (the phone's 诊断记录 JSON, web/seg-frames-logger.js) → a per-frame table in Markdown (BOARD DECISIONS D28).

  scripts/mac/diag-frames.py <record.json | directory> [...] [--all] [--out <file.md>]

Input, any of (several paths are read in order; a directory is read file by file, *.json sorted by name):
  · one record as the page writes it: window.__segFrames / localStorage["ark-segframes"] / the 诊断记录 sheet's copy / share text /
    the object PUT to the diagnostic bucket (diag/<time>-<id>.json);
  · several of them pasted one after another into one file (a chat paste of two shares), a JSON list of them, or {"records": [...]};
  · the phone's local queue localStorage["ark-diag-queue"]: a list of {key, body, why, at} whose `body` is the record as a JSON string.
Four kinds, told apart by the `kind` the recorder writes (seg-frames-logger.js finish() :277, finishLight() :299, __diagMark :372):
  · gesture (segmented control / tab bar) — frames carry lens rect / scale, index, lift / drag / spring, tab, vp, marks;
  · kbd     (a text field's focus, T7) — the gesture frame shape, no pointer;
  · light   (any other control, 件 A) — frames carry the control's rect / alpha / scale / transform / cls, and `scene` only on the frames where
            the scene changed (the recorder reads the background colour per frame but does not write it out, so there is no colour column);
  · mark    (the 「就是这里」 button pressed with no record to attach to) — no frames, only the mark.
Every value in the table is copied from the record. The only derived things are the ones the recorder itself defines:
  · frame gap = sample_t − the previous frame's sample_t (light frames have no sample_t; pts − pts is the same gap); `missed` =
    round(gap / frame_interval) − 1 when > 0 (a frame the page did not get);
  · a row is a "change" row when any tracked field differs from the previous frame (rect by > 0.5 pt = the recorder's own SETTLE_PT);
  · a pointer event goes on the first frame sampled at or after it: frame sampling moment = t_since_down − frame_interval (pts =
    sample moment + frame_interval, finish() :258 / finishLight() :290); pointer t is since down on the same clock.
A record received more than once (same record_id: re-sent with a mark added) is printed once, the last copy.
Without --all only the change rows, the rows with a pointer event / mark / missed frame, and the first and last frame are printed.
Exit status: 0 when every record read gave a table, 1 when a file held no record or a record could not be read (each one is named).
"""
import json
import os
import sys

SETTLE_PT = 0.5   # web/seg-frames-logger.js SETTLE_PT: the recorder's own "the rect did not move" tolerance


def split_json(text):
    """one or more JSON values written one after another (a paste of two shares); raises ValueError on anything else"""
    dec, i, out = json.JSONDecoder(), 0, []
    while True:
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text):
            return out
        v, i = dec.raw_decode(text, i)
        out.append(v)


def records_of(doc):
    if isinstance(doc, list):
        return [r for d in doc for r in records_of(d)]
    if isinstance(doc, dict):
        if isinstance(doc.get("records"), list):
            return records_of(doc["records"])
        if isinstance(doc.get("body"), str) and "key" in doc:    # an ark-diag-queue entry: the record is the body string
            return records_of(json.loads(doc["body"]))
        return [doc]
    raise ValueError(f"not a record: {type(doc).__name__}")


def kind_of(r):
    return r.get("kind") or "gesture"


def ms(v):
    return "" if v is None else f"{v * 1000:.0f}"


def rect_of(f):
    if f.get("lens"):
        return f["lens"][0].get("rect")
    return f.get("rect")


def moved(a, b):
    if a is None or b is None:
        return a != b
    return any(abs(x - y) > SETTLE_PT for x, y in zip(a, b))


def fmt_rect(r):
    return "—" if r is None else ",".join(f"{v:g}" for v in r)


def tab_cell(t):
    if not t:
        return ""
    s = f"top {t.get('top')} {t.get('display')}"
    if t.get("opacity", 1) != 1:
        s += f" α{t['opacity']}"
    if t.get("transform") not in (None, "none"):
        s += " tf"
    if t.get("plat_same") is False:
        s += " 重建"
    if t.get("kbd"):
        s += " kbd"
    return s


def vp_cell(v):
    if not v:
        return ""
    return f"vv {v.get('vvh')}/{v.get('vvt')} ih {v.get('ih')} {v.get('ae') or ''}".strip()


def scene_cell(s):
    if not s:
        return ""
    bits = [f"标签 {s.get('tab')}"]
    for k in ("sheets", "alert", "subpage", "diagsheet", "toast", "html"):
        if s.get(k):
            bits.append(f"{k} {s[k]}")
    bits.append(f"scroll {s.get('scroll')}")
    return " · ".join(str(b) for b in bits)


def mark_line(m):
    return f"- 用户标记 {m.get('at')} {m.get('word')!r} 控件 {m.get('control')} 点 {m.get('point')}" + (f" 挂到 {m['into']}" if m.get("into") else "")


def bg_cell(c):
    """the control's computed background-color as the logger read it (seg-frames-logger.js cs.backgroundColor); a record from a page
    before the logger wrote bg (light frames had no bg before 63940f5) shows 未记"""
    if c is None:
        return "未记"
    return "透明" if c in ("transparent", "rgba(0, 0, 0, 0)") else c


def watched(k, f):
    """the fields whose change makes a row a change row"""
    if k == "light":
        return (f.get("alpha"), tuple(f.get("scale") or ()), f.get("transform"), f.get("cls"), f.get("gone"), f.get("bg"), f.get("anims"),
                json.dumps(f.get("scene")) if "scene" in f else None)
    t, v = f.get("tab") or {}, f.get("vp") or {}
    lens = (f.get("lens") or [{}])[0]
    return (lens.get("alpha"), tuple(lens.get("scale") or ()), f.get("index"), f.get("lift"), f.get("drag"), f.get("spring"),
            t.get("top"), t.get("display"), t.get("opacity"), t.get("plat_same") is False, t.get("kbd"), v.get("vvh"), v.get("ih"), v.get("ae"))


def header(r, k):
    fi = r.get("frame_interval") or (1 / 60)
    out = [f"## {r.get('name') or '（无名）'}（{k}）· 记录号 {r.get('record_id')}",
           f"- 页面版本 {r.get('page_version')} · 触发 {r.get('trigger')} · 独立窗口 {r.get('standalone')} · 视口 {r.get('viewport')} · 帧距中位 {fi * 1000:.1f} ms · 记录于 {r.get('at')}",
           f"- 设备 {r.get('ua')}"]
    if fi > 0.05:   # > 3 frames at 60 Hz: the median itself is a stall, so the 掉帧 column (gap ÷ median − 1) undercounts
        out.append(f"- 注意：帧距中位 {fi * 1000:.0f} ms——这份记录里页面大多数时候没拿到帧，掉帧列按这个中位数算，会少算；看「按下后 ms」列的间隔")
    up = r.get("upload")
    if up:
        out.append(f"- 上传 {up.get('state')} · {up.get('detail')} · {up.get('key')}")
    return out


def event_text(e):
    s = f"{ms(e.get('t_since_down'))} ms {e.get('events')}"
    if e.get("index", -1) != -1:
        s += f" → {e.get('index')}"
    if e.get("field"):
        s += f" {e['field']}"
    if e.get("scene"):
        s += f"（{scene_cell(e['scene'])}）"
    return s


def table(r, show_all):
    k = kind_of(r)
    out = header(r, k)
    if k == "mark":
        out += [mark_line(m) for m in r.get("marks") or []]
        return "\n".join(out) + "\n"
    frames = r.get("frames") or []
    fi = r.get("frame_interval") or (1 / 60)
    if k == "light":
        c = r.get("control") or {}
        out.append(f"- 控件 {c.get('label')!r} {c.get('path')} · 停因 {r.get('stopped_by')} · 首次变化 {ms(r.get('first_change_since_down')) + ' ms' if r.get('first_change_since_down') is not None else '无（框没动过）'} · 起始场景 {scene_cell(r.get('scene0'))}")
    else:
        out.append(f"- 透镜模式 {r.get('gl_mode')} · 首次透镜变化 {ms(r.get('first_lens_change_since_down')) + ' ms' if r.get('first_lens_change_since_down') is not None else '无（透镜没动过）'}")
    out += [mark_line(m) for m in r.get("marks") or [] if isinstance(m, dict) and "word" in m]
    ev = [event_text(e) for e in r.get("control_events") or []]
    if ev:
        out.append("- 控件事件：" + "；".join(ev))
    vpe = r.get("vp_events") or []
    if vpe:
        out.append("- 视口事件：" + "；".join(f"{ms(e.get('t'))} ms {e.get('type')} vv {e.get('vvh')}/{e.get('vvt')} ih {e.get('ih')}" for e in vpe))
    ptr = sorted(r.get("pointer") or [], key=lambda p: p["t"])
    lags = [p.get("lag") for p in ptr if p.get("lag") is not None]
    if lags:
        out.append(f"- 指针等主线程（lag，ms）：最大 {max(lags)} · 超过一帧 {sum(1 for x in lags if x > fi * 1000)} / {len(lags)}")
    if k == "light":
        head = "| 帧 | 按下后 ms | 阶段 | 指针 | 框 x,y,w,h | α | 缩放 | 底色 | 动画数 | 类 | 场景（变了才有） | 掉帧 |"   # 底色 / 动画数: 界面 via 验收 18:1x (数据-串7)
    else:
        head = "| 帧 | 按下后 ms | 阶段 | 指针 | 框 x,y,w,h | 缩放 | 选中 | 抬/拖/弹 | 标签栏 | 视口 | 标记 | 掉帧 |"
    ncol = head.count("|") - 1
    out += ["", head, "|" + "---|" * ncol]
    prev, prev_st, shown, missed_total, pi = None, None, 0, 0, 0
    for i, f in enumerate(frames):
        st = f.get("sample_t", f.get("pts"))
        miss = 0
        if prev_st is not None and st is not None:
            miss = max(0, round((st - prev_st) / fi) - 1)
            missed_total += miss
        sampled = (f.get("t_since_down") or 0) - fi          # this frame's sampling moment, since down
        here = []
        while pi < len(ptr) and ptr[pi]["t"] <= sampled:
            p = ptr[pi]
            here.append(f"{p['type']} {p.get('x', '')},{p.get('y', '')}" + (f" lag {p['lag']}" if p.get("lag") is not None else ""))
            pi += 1
        marks = [f"{m['name']} {ms(m.get('dur'))}ms" for m in f.get("marks") or []]
        rc = rect_of(f)
        change = prev is None or moved(rc, rect_of(prev)) or watched(k, f) != watched(k, prev)
        if show_all or change or here or marks or miss or i == len(frames) - 1:
            if k == "light":
                row = [f.get("frame"), ms(f.get("t_since_down")), f.get("phase"), "；".join(here), fmt_rect(rc) + (" 已移除" if f.get("gone") else ""),
                       f.get("alpha"), f.get("scale"), bg_cell(f.get("bg")), "未记" if f.get("anims") is None else f["anims"], f.get("cls") or "", scene_cell(f.get("scene")), miss or ""]
            else:
                lens = (f.get("lens") or [{}])[0]
                flags = "/".join(x for x, y in (("抬", f.get("lift")), ("拖", f.get("drag")), ("弹", f.get("spring"))) if y)
                row = [f.get("frame"), ms(f.get("t_since_down")), f.get("phase"), "；".join(here), fmt_rect(rc), lens.get("scale"), f.get("index"), flags,
                       tab_cell(f.get("tab")), vp_cell(f.get("vp")), "；".join(marks), miss or ""]
            out.append("| " + " | ".join("" if v is None else str(v).replace("|", "/") for v in row) + " |")
            shown += 1
        prev, prev_st = f, st
    for p in ptr[pi:]:
        out.append("| 记录结束后 | " + ms(p["t"]) + " | | " + f"{p['type']} {p.get('x', '')},{p.get('y', '')}" + " |" * (ncol - 3))
    out.append(f"\n共 {len(frames)} 帧，列出 {shown}；掉帧合计 {missed_total}（帧距 ÷ 中位帧距 − 1）。\n")
    return "\n".join(out)


def dedupe(parts):
    """「就是这里」 pressed after a record re-sends that record with the mark added and the same record_id (seg-frames-logger.js :365–368):
    the later copy replaces the earlier one in place, and its heading says so"""
    last = {}
    for i, (r, _) in enumerate(parts):
        if r.get("record_id"):
            last[r["record_id"]] = i
    out = []
    for i, (r, t) in enumerate(parts):
        rid = r.get("record_id")
        if rid and last[rid] != i:
            continue
        n = sum(1 for q, _ in parts if rid and q.get("record_id") == rid)
        out.append((r, t.replace("\n", f"\n- 同一记录共收到 {n} 份（补标记后重送），这里是最后一份\n", 1) if n > 1 else t))
    return out


def files_of(paths):
    for p in paths:
        if os.path.isdir(p):
            for n in sorted(os.listdir(p)):
                if n.endswith(".json"):
                    yield os.path.join(p, n)
        else:
            yield p


def main(argv):
    args = argv[1:]
    show_all = "--all" in args
    outp = args[args.index("--out") + 1] if "--out" in args else None
    paths = [a for a in args if not a.startswith("--") and a != outp]
    if not paths:
        print(__doc__)
        return 2
    parts, bad = [], []
    for path in files_of(paths):
        try:
            with open(path, encoding="utf-8") as fh:
                recs = [r for v in split_json(fh.read()) for r in records_of(v)]
        except (OSError, ValueError) as e:
            bad.append(f"{path}: {e}")
            continue
        if not recs:
            bad.append(f"{path}: no record in it")
        for r in recs:
            try:
                parts.append((r, table(r, show_all)))
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                bad.append(f"{path}: record {r.get('record_id') if isinstance(r, dict) else '?'} unreadable: {type(e).__name__} {e}")
    md = "\n".join(t for _, t in dedupe(parts))
    if outp:
        with open(outp, "w", encoding="utf-8") as fh:
            fh.write(md)
    else:
        sys.stdout.write(md)
    for b in bad:
        print("diag-frames: " + b, file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
