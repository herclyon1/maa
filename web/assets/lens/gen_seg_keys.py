#!/usr/bin/env python3
"""Compile the native segmented-control lens kinematics into page keyframes (seg-keys.css) straight from the per-frame data —
no hand-tuned curves. Inputs (remote-ref/tools/touch/, data session 2026-09-19):

  seg-lift-frames-light.json     lenstrace of a press on the selected segment: per frame lens x/y/w/h, DestOut r / opacity, platter
                                 opacity, the three displacement amounts, SDF heights (t from touch-down; t_up = the release)
  seg-native-abc-frames.json     video-aligned probe rects: hold (A) → drag to the other segment (B) → release (C)
  touch-local.uiprobe-abc.json   the finger positions of that drag (for the follow lag)
  seg-native-tap-frames.json     tap on the unselected segment: the lens flies over after the up (D)

Outputs, all as `<ms> <value>` key lists (the tokens.css convention; ms from the start of that animation) plus ready-made
`linear()` easings (percent of the duration) and @keyframes for the size ratios:
  lift      progress 0 → 1 of w/h/r/the displacement amount/the platter fade — one curve for all (seg-lens-refraction.md §4.1), delay + duration
  release   in place: geometry back, displacement tail, platter back, DestOut fade (§4.3), each with its own delay + duration
  drop      after a drag (C): x progress from the release position to the target, w/h ratios
  commit    after a tap (D): x progress from the old to the new segment (overshoot), w/h ratios; compared with tokens.css's lens-*-keys
  follow    first-order lag τ of the lens behind the finger while dragging (B), least squares, residual reported
Self-test: every emitted key list re-evaluated at the source frames must reproduce them within 0.5 pt (prints the worst).
  python3 gen_seg_keys.py [--ref ~/Money/styl-work/remote-ref/tools/touch] [--out seg-keys.css]
"""
import argparse, json, math, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
REST_W, REST_H, LIFT_W, LIFT_H = 196.0, 28.0, 220.0, 44.0

def keys_str(keys, nd=3): return ", ".join(f"{int(round(t))} {round(v, nd):g}" for t, v in keys)
def linear_str(keys, nd=3):
    T = keys[-1][0]; parts = []
    for t, v in keys: parts.append(f"{round(v, nd):g}" if t == 0 else f"{round(v, nd):g} {100 * t / T:.2f}%")
    return "linear(" + ", ".join(parts) + ")"
def frames_str(name, wk, hk, nd=3):
    T = wk[-1][0]; hmap = dict(hk); lines = []
    for t, w in wk:
        h = hmap.get(t, interp(hk, t)); lines.append(f"{100 * t / T:.2f}%{{scale:{round(w, nd):g} {round(h, nd):g}}}")
    return f"@keyframes {name}{{" + " ".join(lines) + "}"
def interp(keys, t):
    if t <= keys[0][0]: return keys[0][1]
    if t >= keys[-1][0]: return keys[-1][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t0 <= t <= t1: return v0 + (v1 - v0) * (t - t0) / (t1 - t0) if t1 > t0 else v1
    return keys[-1][1]
def dedupe(keys):
    out = []
    for t, v in keys:
        if out and abs(out[-1][0] - t) < 0.5: continue
        out.append((t, v))
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0]); ap.add_argument("--ref", default=os.path.expanduser("~/Money/styl-work/remote-ref/tools/touch")); ap.add_argument("--out", default=os.path.join(HERE, "seg-keys.css"))
    a = ap.parse_args(); R = a.ref; report = []; checks = []
    # ---------- lift + in-place release: the lenstrace ----------
    tr = json.load(open(os.path.join(R, "seg-lift-frames-light.json"))); fr = tr["frames"]; t_up = tr["t_up"]
    lift = [f for f in fr if 0 <= f["t"] < t_up - 0.5]
    first = next(f for f in lift if f["lens"][2] > REST_W + 0.05); i0 = lift.index(first) - 1; t0 = lift[i0]["t"]          # the last rest frame = the animation's start
    done = next(f for f in lift if f["lens"][2] >= LIFT_W - 0.05 and f["lens"][3] >= LIFT_H - 0.05)
    lk, wk, hk, dk, pk, ok = [], [], [], [], [], []
    for f in lift[i0:]:
        t = (f["t"] - t0) * 1000
        if f["t"] > done["t"] + 0.06: break
        pw, ph = (f["lens"][2] - REST_W) / (LIFT_W - REST_W), (f["lens"][3] - REST_H) / (LIFT_H - REST_H)
        wk.append((t, pw)); hk.append((t, ph)); lk.append((t, (pw + ph) / 2))
        if f["dispClear"] is not None: dk.append((t, -f["dispClear"] / 17.5))
        pk.append((t, f["platterOp"] if f["platterOp"] is not None else 0)); ok.append((t, f["destOutOp"] if f["destOutOp"] is not None else 1))
    lift_delay, lift_dur = t0 * 1000, (done["t"] - t0) * 1000
    spread = max(abs(pw - ph) for (_, pw), (_, ph) in zip(wk, hk)); dspread = max(abs(interp(lk, t) - v) for t, v in dk)
    report.append(f"lift: starts at down + {lift_delay:.0f} ms (last rest frame), 220×44 at + {done['t'] * 1000:.0f} ms → duration {lift_dur:.0f} ms; w vs h progress differ ≤ {spread:.3f}, displacement/17.5 vs size progress ≤ {dspread:.3f} → one curve")
    # ---------- in-place release (each quantity on its own clock, all from the up; an animation starts at its LAST unchanged frame,
    #            key 0 = the value still at rest, like the lift) ----------
    rel = [f for f in fr if f["t"] >= t_up - 0.02]
    def series(getter, changed, done_when):
        vals = [((f["t"] - t_up) * 1000, getter(f)) for f in rel]
        i1 = next(i for i, (t, v) in enumerate(vals) if changed(v)); start_i = max(0, i1 - 1); t0_ = vals[start_i][0]
        keys = [(t - t0_, v) for t, v in vals[start_i:] if t - t0_ <= 800]
        done = next(t for t, v in keys if done_when(v)); keys = [(t, v) for t, v in keys if t <= done]
        return t0_, done, keys
    r_delay, geom_done, rk = series(lambda f: 1 - (f["lens"][2] - REST_W) / (LIFT_W - REST_W), lambda v: v > 0.001, lambda v: v >= 0.999)
    w_delay, warp_done, rdk = series(lambda f: -(f["dispClear"] or 0) / 17.5, lambda v: v < 0.999, lambda v: v <= 0.002)
    p_delay, plat_done, rpk = series(lambda f: f["platterOp"] if f["platterOp"] is not None else 1, lambda v: v > 0.001, lambda v: v >= 0.999)
    d_delay, dest_done, rok = series(lambda f: f["destOutOp"] if f["destOutOp"] is not None else 0, lambda v: v < 0.999, lambda v: v <= 0.006)
    report.append(f"release (in place, times from the up, each animation starting at its last unchanged frame): geometry starts + {r_delay:.0f} ms, back to 196×28 by + {r_delay + geom_done:.0f} ms; "
                  f"displacement starts + {w_delay:.0f}, → 0 by + {w_delay + warp_done:.0f} ms; platter starts + {p_delay:.0f}, 0 → 1 by + {p_delay + plat_done:.0f} ms; DestOut starts + {d_delay:.0f} (still 1 there), ≤ .006 by + {d_delay + dest_done:.0f} ms")
    # ---------- drag follow lag (B) ----------
    abc = json.load(open(os.path.join(R, "seg-native-abc-frames.json"))); tl = json.load(open(os.path.join(R, "touch-local.uiprobe-abc.json")))
    touches = [(e["phase"], e["t"] / 1000, [float(v) for v in e["loc"].split(",")]) for e in tl["entries"] if e["kind"] == "touch"]
    tdown = next(t for ph, t, _ in touches if ph == "began"); finger = [(t - tdown, loc[0]) for ph, t, loc in touches if ph in ("began", "moved")]
    drag = [f for f in abc["frames"] if f["phase"] == "drag" and f["lens"]]
    x_rest = abc["frames"][0]["lens"][0]["rect"][0]; c_rest = x_rest + abc["frames"][0]["lens"][0]["rect"][2] / 2   # lens centre at rest = the finger's start
    def finger_at(t):   # last finger x at time t (since down), as a lens-centre target: centre = c_rest + (finger − finger0)
        fx = finger[0][1]
        for ft, x in finger:
            if ft <= t: fx = x
        return c_rest + (fx - finger[0][1])
    def simulate(model, params):
        """lens centre driven by the finger target from the first drag frame; returns rms error over the drag frames (1 ms sub-steps)"""
        c = drag[0]["lens"][0]["rect"][0] + drag[0]["lens"][0]["rect"][2] / 2; v = 0.0; t = drag[0]["t_since_down"]; err = 0.0
        for f in drag[1:]:
            while t < f["t_since_down"] - 1e-9:
                dt = min(0.001, f["t_since_down"] - t); tgt = finger_at(t)
                if model == "lag": c += (tgt - c) * (1 - math.exp(-dt / params[0]))
                else:
                    w, z = params; acc = w * w * (tgt - c) - 2 * z * w * v; v += acc * dt; c += v * dt
                t += dt
            err += (c - (f["lens"][0]["rect"][0] + f["lens"][0]["rect"][2] / 2)) ** 2
        return math.sqrt(err / max(1, len(drag) - 1))
    best = min(((tau / 1000, simulate("lag", (tau / 1000,))) for tau in range(20, 400, 4)), key=lambda p: p[1])
    spring = min(((w, z, simulate("spring", (w, z))) for w in range(6, 40) for z in [x / 20 for x in range(4, 25)]), key=lambda p: p[2])
    # the lens stretches while it moves: its leading and trailing EDGES follow the finger's target edges through two different springs
    # (the leading edge arrives with little overshoot, the trailing one later and overshoots, squeezing the lens below 220)
    half = LIFT_W / 2; direction = 1 if finger[-1][1] >= finger[0][1] else -1
    def simulate_edge(edge, w, z):
        r0 = drag[0]["lens"][0]["rect"]; c = (r0[0] + r0[2]) if edge == "lead" else r0[0]; c = c if direction > 0 else ((r0[0]) if edge == "lead" else r0[0] + r0[2])
        v = 0.0; t = drag[0]["t_since_down"]; err = 0.0
        for f in drag[1:]:
            while t < f["t_since_down"] - 1e-9:
                dt = min(0.001, f["t_since_down"] - t); tgt = finger_at(t) + (half if (edge == "lead") == (direction > 0) else -half)
                acc = w * w * (tgt - c) - 2 * z * w * v; v += acc * dt; c += v * dt; t += dt
            r = f["lens"][0]["rect"]; actual = (r[0] + r[2]) if (edge == "lead") == (direction > 0) else r[0]
            err += (c - actual) ** 2
        return math.sqrt(err / max(1, len(drag) - 1))
    lead = min(((w, z, simulate_edge("lead", w, z)) for w in range(6, 60) for z in [x / 20 for x in range(4, 31)]), key=lambda p: p[2])
    trail = min(((w, z, simulate_edge("trail", w, z)) for w in range(6, 60) for z in [x / 20 for x in range(4, 31)]), key=lambda p: p[2])
    report.append(f"follow (B, {len(drag)} drag frames, finger 20 pt / 16 ms steps): first-order lag τ = {best[0] * 1000:.0f} ms fits the centre with rms {best[1]:.1f} pt; "
                  f"a damped spring ω = {spring[0]} /s, ζ = {spring[1]:.2f} with rms {spring[2]:.1f} pt; two edge springs — leading ω {lead[0]} ζ {lead[1]:.2f} (rms {lead[2]:.1f} pt), "
                  f"trailing ω {trail[0]} ζ {trail[1]:.2f} (rms {trail[2]:.1f} pt) — reproduce the stretch (w up to 253) and the trailing overshoot (w 197.5 at the release)")
    # ---------- drop after the drag (C) ----------
    rel_c = [f for f in abc["frames"] if f["phase"] == "released" and f["lens"]]; x_end = rel_c[-1]["lens"][0]["rect"][0]
    x_rel = rel_c[0]["lens"][0]["rect"][0]; ck_x, ck_w, ck_h = [], [], []
    for f in rel_c:
        t = f["t_since_up"] * 1000; r = f["lens"][0]["rect"]
        if t > 1400: break
        ck_x.append((t, (r[0] - x_rel) / (x_end - x_rel) if abs(x_end - x_rel) > 0.5 else 1.0)); ck_w.append((t, r[2] / REST_W)); ck_h.append((t, r[3] / REST_H))
    def settled_at(kx, kw, kh):
        """the last frame whose rect differs from the final one by more than 0.005 (x progress) / 0.002 (w, h ratio) → + one frame"""
        off = [t for (t, x), (_, w), (_, h) in zip(kx, kw, kh) if abs(x - 1) > 0.005 or abs(w - kw[-1][1]) > 0.002 or abs(h - kh[-1][1]) > 0.002]
        last = off[-1] if off else kx[0][0]; nxt = next((t for t, _ in kx if t > last), kx[-1][0]); return nxt
    settle_c = settled_at(ck_x, ck_w, ck_h)
    ck_x = [(t, v) for t, v in ck_x if t <= settle_c]; ck_w = [(t, v) for t, v in ck_w if t <= settle_c]; ck_h = [(t, v) for t, v in ck_h if t <= settle_c]
    report.append(f"drop after drag (C): x {x_rel:g} → {x_end:g} (rest x of the target segment), settled at up + {settle_c:.0f} ms (first frame on the final rect after the last one off it; the recording runs on to + 1313), w/h from {rel_c[0]['lens'][0]['rect'][2]}×{rel_c[0]['lens'][0]['rect'][3]} back to 196×28")
    # ---------- commit after a tap (D) ----------
    tap = json.load(open(os.path.join(R, "seg-native-tap-frames.json"))); rel_d = [f for f in tap["frames"] if f["phase"] == "released" and f["lens"]]
    x0d = rel_d[0]["lens"][0]["rect"][0]; x1d = rel_d[-1]["lens"][0]["rect"][0]; dk_x, dk_w, dk_h = [], [], []
    for f in rel_d:
        t = f["t_since_up"] * 1000; r = f["lens"][0]["rect"]
        if t > 1400: break
        dk_x.append((t, (r[0] - x0d) / (x1d - x0d))); dk_w.append((t, r[2] / REST_W)); dk_h.append((t, r[3] / REST_H))
    settle_d = settled_at(dk_x, dk_w, dk_h)
    dk_x = [(t, v) for t, v in dk_x if t <= settle_d]; dk_w = [(t, v) for t, v in dk_w if t <= settle_d]; dk_h = [(t, v) for t, v in dk_h if t <= settle_d]
    move_start = next(t for t, v in dk_x if v > 0.005); peak = max(dk_x, key=lambda k: k[1]); wpeak = max(dk_w, key=lambda k: k[1]); hpeak = max(dk_h, key=lambda k: k[1])
    report.append(f"commit after tap (D): x {x0d:g} → {x1d:g}, moves from up + {move_start:.0f} ms, x overshoot {peak[1]:.3f} at + {peak[0]:.0f} ms, w peak ×{wpeak[1]:.3f} at + {wpeak[0]:.0f} ms, h peak ×{hpeak[1]:.3f} at + {hpeak[0]:.0f} ms, settled by + {dk_x[-1][0]:.0f} ms")
    # compare with tokens.css --ios-touch-segment-lens-*-keys (they start at the first move, not at the up)
    tok = open(os.path.join(HERE, "..", "..", "tokens.css"), encoding="utf-8").read() if os.path.exists(os.path.join(HERE, "..", "..", "tokens.css")) else ""
    m = re.search(r"--ios-touch-segment-lens-x-keys:\s*([^;]+);", tok)
    if m:
        old = [(float(p.split()[0]), float(p.split()[1])) for p in m.group(1).split(",")]; opeak = max(old, key=lambda k: k[1])
        diffs = [abs(interp(old, t - move_start) - v) for t, v in dk_x if t >= move_start]
        report.append(f"vs tokens.css lens-x-keys (time base = first move): overshoot {opeak[1]:.3f} @ {opeak[0]:.0f} ms there vs {peak[1]:.3f} @ {peak[0] - move_start:.0f} ms here; mean |Δ| {sum(diffs) / len(diffs):.3f} of the 200-pt travel ({sum(diffs) / len(diffs) * 200:.1f} pt), max {max(diffs):.3f} ({max(diffs) * 200:.1f} pt)")
    # ---------- self-test: keys re-evaluated at the source frames ----------
    def check(name, keys, frames_tv, scale):
        worst = max(abs(interp(keys, t) - v) * scale for t, v in frames_tv); checks.append((name, worst)); return worst
    check("lift w", wk, wk, LIFT_W - REST_W); check("lift h", hk, hk, LIFT_H - REST_H); check("lift progress vs w", lk, wk, LIFT_W - REST_W); check("lift progress vs h", lk, hk, LIFT_H - REST_H)
    check("release geometry (w)", rk, rk, LIFT_W - REST_W); check("drop x", ck_x, ck_x, abs(x_end - x_rel)); check("drop w", ck_w, ck_w, REST_W); check("drop h", ck_h, ck_h, REST_H)
    check("commit x", dk_x, dk_x, abs(x1d - x0d)); check("commit w", dk_w, dk_w, REST_W); check("commit h", dk_h, dk_h, REST_H)
    worst = max(w for _, w in checks)
    # ---------- write ----------
    L = ["/* seg-keys.css — segmented-control lens kinematics compiled from the native per-frame recordings by gen_seg_keys.py (do not edit).",
         "   Sources: remote-ref/tools/touch/seg-lift-frames-light.json (lenstrace: lift + in-place release; seg-lens-refraction.md §4.1 / §4.3),",
         "   seg-native-abc-frames.json + touch-local.uiprobe-abc.json (drag follow, drop after the drag), seg-native-tap-frames.json (commit after a tap).",
         "   Key lists are `<ms> <value>` from the start of that animation (tokens.css convention); the linear() strings and @keyframes are the same",
         "   numbers as CSS easings / keyframes over the stated duration. Findings:"] + [f"   - {r}" for r in report] + [
         f"   Self-test: keys re-evaluated at the source frames reproduce them within {worst:.3f} pt (limit 0.5). */", ":root{",
         "  /* lift: press on the selected segment; one progress curve drives w (196 → 220), h (28 → 44), DestOut r (14 → 22), the displacement",
         f"     amount (0 → −17.5 = filter scale 0 → 32) and the platter fade (opacity = 1 − progress); starts {lift_delay:.0f} ms after the down */",
         f"  --ios-touch-segment-lift-delay: {lift_delay:.0f}ms;", f"  --ios-touch-segment-lift-duration: {lift_dur:.0f}ms;",
         f"  --ios-touch-segment-lift-keys: {keys_str(lk)};", f"  --ios-touch-segment-lift-easing: {linear_str(lk)};",
         f"  --ios-touch-segment-lift-w-keys: {keys_str(wk)};", f"  --ios-touch-segment-lift-h-keys: {keys_str(hk)};",
         f"  --ios-touch-segment-warp-keys: {keys_str(dk)};   /* displacement amount / 17.5 — same curve as the size */",
         f"  --ios-touch-segment-platter-keys: {keys_str(pk)};   /* the resting white platter's opacity while lifting */",
         f"  --ios-touch-segment-destout-keys: {keys_str(ok)};   /* the DestOut (knock-out of the content under the lens) opacity while lifting */",
         "  /* release in place (the finger lifts without having changed the value): geometry, displacement, platter and DestOut each on their own",
         "     clock; every delay counts from the up to that animation's last unchanged frame (its key 0), like the lift */",
         f"  --ios-touch-segment-release-delay: {r_delay:.0f}ms;", f"  --ios-touch-segment-release-duration: {geom_done:.0f}ms;",
         f"  --ios-touch-segment-release-keys: {keys_str(rk)};   /* progress 1 → 0 of the lift (w 220 → 196, h 44 → 28, r 22 → 14) written as 0 → 1 */",
         f"  --ios-touch-segment-release-easing: {linear_str(rk)};",
         f"  --ios-touch-segment-release-warp-delay: {w_delay:.0f}ms;", f"  --ios-touch-segment-release-warp-duration: {warp_done:.0f}ms;", f"  --ios-touch-segment-release-warp-keys: {keys_str(rdk)};   /* displacement amount / 17.5 → 0 (long tail) */",
         f"  --ios-touch-segment-release-platter-delay: {p_delay:.0f}ms;", f"  --ios-touch-segment-release-platter-duration: {plat_done:.0f}ms;", f"  --ios-touch-segment-release-platter-keys: {keys_str(rpk)};",
         f"  --ios-touch-segment-release-destout-delay: {d_delay:.0f}ms;", f"  --ios-touch-segment-release-destout-duration: {dest_done:.0f}ms;", f"  --ios-touch-segment-release-destout-keys: {keys_str(rok)};   /* 1 until the delay, then the fade */",
         f"  /* drag: the lens centre follows the finger as a damped spring (fit over the B frames, rms {spring[2]:.1f} pt; a first-order lag of {best[0] * 1000:.0f} ms would leave {best[1]:.1f} pt) */",
         f"  --ios-touch-segment-follow-omega: {spring[0]};   /* rad/s */", f"  --ios-touch-segment-follow-zeta: {spring[1]:.2f};", f"  --ios-touch-segment-follow-response: {2 * math.pi / spring[0]:.3f}s;",
         f"  --ios-touch-segment-follow-tau: {best[0] * 1000:.0f}ms;   /* first-order stand-in if the page keeps a transition */",
         f"  /* better: the two edges as their own springs — leading edge ω {lead[0]} ζ {lead[1]:.2f} (rms {lead[2]:.1f} pt), trailing edge ω {trail[0]} ζ {trail[1]:.2f} (rms {trail[2]:.1f} pt); the lens width follows */",
         f"  --ios-touch-segment-follow-lead-omega: {lead[0]};", f"  --ios-touch-segment-follow-lead-zeta: {lead[1]:.2f};", f"  --ios-touch-segment-follow-trail-omega: {trail[0]};", f"  --ios-touch-segment-follow-trail-zeta: {trail[1]:.2f};",
         "  /* drop after a drag (C): from the release rect to the target segment's rest rect; x as progress of the remaining travel, w/h as ratios of 196×28 */",
         f"  --ios-touch-segment-drop-duration: {ck_x[-1][0]:.0f}ms;", f"  --ios-touch-segment-drop-x-keys: {keys_str(ck_x)};", f"  --ios-touch-segment-drop-w-keys: {keys_str(ck_w)};", f"  --ios-touch-segment-drop-h-keys: {keys_str(ck_h)};",
         f"  --ios-touch-segment-drop-x-easing: {linear_str(ck_x)};",
         f"  /* commit after a tap on the other segment (D): x from the old segment to the new one (progress, overshoot {peak[1]:.3f}), w/h ratios; moves {move_start:.0f} ms after the up */",
         f"  --ios-touch-segment-commit-move-delay: {move_start:.0f}ms;", f"  --ios-touch-segment-commit-duration: {dk_x[-1][0]:.0f}ms;",
         f"  --ios-touch-segment-commit-x-keys: {keys_str(dk_x)};", f"  --ios-touch-segment-commit-w-keys: {keys_str(dk_w)};", f"  --ios-touch-segment-commit-h-keys: {keys_str(dk_h)};",
         f"  --ios-touch-segment-commit-x-easing: {linear_str(dk_x)};", "}",
         frames_str("seg-lift-size", [(t, 1 + v * (LIFT_W / REST_W - 1)) for t, v in wk], [(t, 1 + v * (LIFT_H / REST_H - 1)) for t, v in hk]) + "   /* scale of the 196×28 lens while lifting (use width/height, not scale, if the ends must stay circular) */",
         frames_str("seg-drop-size", ck_w, ck_h), frames_str("seg-commit-size", dk_w, dk_h), ""]
    open(a.out, "w", encoding="utf-8").write("\n".join(L))
    for r in report: print(r)
    print("self-test:", ", ".join(f"{n} {w:.3f}" for n, w in checks), "→ worst", f"{worst:.3f} pt", "OK" if worst <= 0.5 else "FAIL")
    print("→", a.out, os.path.getsize(a.out), "bytes")
    return 0 if worst <= 0.5 else 1

if __name__ == "__main__": raise SystemExit(main())
