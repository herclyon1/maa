# Web freeze (2026-09-19)

The phone page (web/) stops here: bug fixes only from now on, batched (never one fix per release; a live-blocking failure is the
only reason for a single rollback or hot fix). The project's future UI is a native iOS app (not compiled yet); the plan is in
`~/Money/styl-work/remote-ref/ios-native-plan.md` (outside the repo).

## Live

- Version: `v=20260919190821` (main `8be9d7a (batch 28fb83c + stamp)`, deployed 2026-09-19 19:08 JST; verify with `curl -s https://herclyon1.github.io/maa/ | grep -o 'view.js?v=[0-9]*'`,
  which must print the stamp twice: the inline view.js loader and the accept row both carry it).
- Content = the 181053 release + tonight's bug batch:
  - segmented-control lens drawn in WebGL (`web/assets/lens/lens-webgl.js`, ui2 `145ddc1`: rest bound .001 = the page's own settle bound, prewarm to an
    offscreen framebuffer, `?gl=0` falls back to the SVG stack, `?gltrace=1` per-step timing) and the page side of the ghost-lens fix (ui `7deefe6`);
  - keyboard: the tab-bar capsule hides on focusin of any keyboard field and on a visualViewport height drop > 120, returns 60 ms after blur
    (`html.kbd`, ui `654d4a8` / `5d71467`); HH:MM inputs accept only `H:MM` / `HH:MM`, anything else rolls back to the last value with a toast;
  - first lens gesture after load: the lens layers and the GL instance are built at the first idle after load (ui `5d71467`; was 30 ms on the first
    press); live.js's timers wait for view.js (`window.__viewReady`, ui `68c6f15`); dialogs no longer scroll their title out (`overflow: clip`);
  - list-row press (B14, `web/controls.js` / `web/controls.css`, b14-fix `7d3ea7a`): +150 ms highlight, .5 s fade, page `ask()` dialog instead of `confirm()`;
  - accept harness (`scripts/mac/accept-run.py`, main `dc126d3`): starts only after `window.__viewReady`, 60 s windows, reloads once on a lost script.
- Rollback point: `v=20260919181053` (main `fceb5de`: the same WebGL lens without tonight's keyboard / time / first-idle-build fixes).
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
  no gh-pages push). The simulator itself is frozen by the user's order; the script is kept for when it is unfrozen.

## Direction

Web: bug fixes only, batched; no new controls. iOS native: see `remote-ref/ios-native-plan.md` (which system controls replace which page functions,
which decoded documents stay useful as acceptance baselines, which are archived).
