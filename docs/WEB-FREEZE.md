# Web freeze (2026-09-19)

The phone page (web/) stops here: bug fixes only from now on, batched (never one fix per release; a live-blocking failure is the
only reason for a single rollback or hot fix). The project's future UI is a native iOS app (not compiled yet); the plan is in
`~/Money/styl-work/remote-ref/ios-native-plan.md` (outside the repo).

## Live

- Version: `v=20260920122207` (main `c33d341` = night `e470332` content + runner housekeeping, deployed 2026-09-20 12:22 JST at the user's request;
  verify with `curl -s https://herclyon1.github.io/maa/ | grep -o 'view.js?v=[0-9]*' | sort -u`).
- Content = the 20260919202020 release + the overnight batch of 2026-09-19 23:45 → 2026-09-20 11:23 (90 items on the `night` branch, headless
  acceptance 707 rows light and dark green at `e470332`; the ledger is `~/Money/styl-work/BOARD.md` sections B/B2/E, outside the repo):
  - the two phone bugs: a quick tap on the selected segment no longer blanks the platter (canvas clear at lift < .001) and the fall is created at
    down + 220 ms (lensHangTime, decompiled and confirmed by a timer hook); a shift change no longer drops the bottom tab bar (the lens canvases painted
    past the right edge and widened the layout viewport — canvases are now clipped to the viewport and `html{overflow-x:clip}`);
  - per control (each from decompiled UIKit / QuartzCore values, sources in `~/Money/styl-work/remote-ref/RENDER-PIPELINE.md`): segmented control,
    tab-bar lens (lift on the next tick, flex while dragging, drop within 8 pt, up rules), top bar (large title, pocket blur by the read mask),
    navigation push/pop (parallax, back chevron, large-title scale, edge-back recognizer), value-row menu and alert (glass from the 70 dumped keys,
    KeyFill stroke, ring shadow, soft shadow, ovalization), pull-to-refresh (arms, placement under the small-title bar), glass round buttons
    (probe frame tables), switch (own file, in the release by the user's decision), tile / capsule press states, reduce-motion branches;
  - runner: `scripts/mac/accept-run.py` waits for `__viewReady`, kernel-assigned DevTools port, sweeps stale Chrome profiles and code-sign clones.
- Not verified on a device yet: the morning simulator sweep ran against a stale service-worker shell (the night shell scripts were `?v=0`), so its
  seven "bad" items are void until re-run on a stamped build; three page defects found by reading are pending in the next batch (a row with a
  status suffix mis-lays its switch; the ✓/✕ buttons lack user-select / touch-callout; the top-bar ✓/✕ glyph never fades when held).
- Rollback point: `v=20260919202020` (main `17b5d3e`: the 181053 content plus the diagnostics pieces).
- How to roll back: `git checkout <release commit> -- web/ && git commit && bash scripts/mac/deploy-web.sh && git push`.

## Known issues (device-measured on the iOS simulator, standalone; records in `~/Money/styl-work/remote-ref/tools/touch/`)

- First lens gesture after load: once, ≥ 127 ms of unmarked main-thread time before the down was dispatched (`seg-final-181053.md` ①, host load 3–4);
  not reproduced with the instrumented logger (down lag 36 ms, `ark-segframes-tap-6dbd2f9-first.json`, load 3.8); cause unknown (lens README §0.8.11).
  Tonight removes only the 30 ms layer build from the press. Still on the tap path: the package's deferred backdrop redraw (two 2D backdrops, label
  alpha, two uploads, one prewarm — unmarked, ≈ 40 ms in that record by ui2's reading) runs in the press's next task; per-selection label textures
  prepared at idle (`prepareLabels` / `useLabels`) are not done.
- Drag: B-segment centre error max 18.5 / 21.3 pt (mean −1.9; threshold rms ≤ 2 / max ≤ 5 never met); fall 380 / 383 ms vs native 403.
- Colour fringe stronger than native (share 1.42–1.55 % vs 1.36 %, saturation ≈ 84 vs 69; order correct) — the §3b.8 "source comparison" item.
- Label ink under the glass heavier than native (left 「早」 659 vs 569; native loses ink by geometric tearing the maps do not reproduce) —
  `label-end-tear-closed-vs-map.md`.
- Platter fade starts with the growth instead of 13 ms before it (native `beginTime` unread); right end of the lens 1 pt left of native; dark left
  label residue dimmer.
- List-row press (B14): highlight starts +170…187 ms after the down (native +150…167), fade about ⅓ faster than native (`b14-cell-65850cb.md`).
- Batch check on the exact sha 28fb83c (`seg-batch-28fb83c.md`, host load 3.4–3.9 from system processes: mediaanalysisd, diskimagesiod,
  ANECompilerService): keyboard capsule hides / returns to 905 pt — pass; invalid `08:930` rolls back to `08:30` and stays out of the pending bar —
  pass (the toast was missed by the +0.6 s / +2 s screenshots; on the live version the video `seg-web-toast-live-190821.mov` shows it ≈ 50 ms after
  the keyboard's ✓, above the tab capsule, for 3.0 s with a 65 ms fade, and the value rolling back); `09:30` → 「开始刷」 dialog carries the
  value — pass (the send itself cannot be proved without the relay); theme switches (foreground and background) leave no ghost — pass; first lens
  gesture #1: down lag 8 ms, layer build 1 ms (was 30), first tick +8 — pass; #2 (value change) down lag 77 ms and the drag's down lag 98 ms were
  measured under that host load and are not characterised (page vs host); the time field is not scrolled into view on its first focus under the
  keyboard (second focus fine) — next batch.

## Left on branches, not merged

- controls `51bf2d2`: B13 switch (small-variant springs, `3008bf5`) — not shipped.
- ui2 `73a6132` / `287482e` (tab-bar lens wiring and drag), `258b874` test pages, baked engine-fix maps (`--engine-fix-sets`, `lens-map-dpr.js`),
  `?ab=ends` end-element dispersion trial.
- WebGL open items: fringe saturation source comparison, label tearing intensity term, the 1 pt right-end offset, platter fade start.
- Branch tips at the freeze: ui `5d71467`, ui2 `145ddc1`, b14-fix `7d3ea7a`, controls `51bf2d2`, data `38129f4`.

## Tools that still run against the frozen page

Bug fixes are batched, so these four are the whole loop from a branch to a phone; each one is named here because nothing else documents it.

- `scripts/mac/accept-batch.sh` — merge several branches/shas into the current worktree one at a time (a conflict aborts that merge only), then ONE headless
  acceptance run (light and dark in one Chrome), then attribute every red row: a red in a control nobody touched is recorded, not re-run.
- `scripts/mac/export-web.sh <sha> <outdir>` — export a commit's `web/` for a local phone test through the same shell-stamp step a release uses, so the phone
  never loads an unstamped `?v=0` shell (the HTTP cache would keep it forever).
- `scripts/mac/check-shell.sh <url|port>` — the stamp check itself: every `?v=` in index.html is the same non-zero stamp, `sw.js`'s CACHE name carries it,
  its SHELL list holds every css/js index.html loads, and each shell URL answers 200.
- `scripts/mac/webclip-serve.sh <sha> [port]` — serve a commit's `web/` to the resident home-screen web clip on simulator A the way a deploy would (stamped,
  no gh-pages push); `webclip-serve.sh done [port]` ends the run (stops that port's server, then runs sim-webclean.sh). The simulator freeze
  was lifted by the user on 2026-09-23 08:40.
- `scripts/mac/sim-webclean.sh [UDID|A|B|C|D] [--dry]` — close every leftover web process on one simulator after a run (Safari, clips, in-app Safari,
  and the WebKit content / GPU / networking children of that simulator only), then print the memory freed; webclip-serve.sh calls it before each serve.

## Direction

Web: bug fixes only, batched; no new controls. iOS native: see `remote-ref/ios-native-plan.md` (which system controls replace which page functions,
which decoded documents stay useful as acceptance baselines, which are archived).
