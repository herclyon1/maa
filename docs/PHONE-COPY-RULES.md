# Rules for the phone page copy

**Read this before changing any `hint` / `label` in `web/app.js`.**

Why this file exists: on 2026-09-04 the explanatory text on the page read like this —

> 上游 beta.5 那阵它是坏的（弹窗出来不点确认，重试三次全失败），
> v2.27.0-rc.1 已修好，中继在 09-04 开机时自动开了回来

The user's words were 「太私人措辞了」, and he asked for a rule modelled on
`UPSTREAM-ISSUE-RULES.md`. The problem with that text is not that it is inaccurate — it is that
**it describes my work process, not what the switch does**. The page is a remote control for a
person to use, not my construction log.

---

## One criterion

> **Write only what this switch does and what changes if you flip it.**
> Nothing else.

If one sentence is enough to decide whether to touch it, the copy is good.

## What must never appear

| Must not be written | Why |
|---|---|
| Upstream, the community, issue numbers, version numbers, PRs | That is the software's provenance, not what the setting does |
| Internal jargon: 中继, 脚本, 母本, 账本 | The user is facing a game, not my code |
| Dates, 「那次」, 「那阵」, 「实录」 | A chronicle of incidents belongs in `docs/`, not under a button |
| 「我」, 「用户」, 「他说」 | The page has no first person and does not relay conversations |
| 「已修好」, 「先关着」, 「等上游」 | State changes; freeze it into the copy and it expires into a lie |
| Exclamation marks, interjections, jokes | |
| **What is currently checked, what the current value is** | The control already shows it; say it again in the copy and one change makes it false. On 2026-09-04 the copy said 「路线 3 和 13 已取消勾选」, and the moment the user checked all 16 that sentence was a lie |

## What it should look like

* **The subject is the setting itself** — not me, and not some program.
* **Present tense, declarative.** State its behaviour, not its history.
* **Spell out any precondition**: 「只在上面选 X 时才有用」.
* **Spell out any cost**: numbers, consumption, caps — e.g. 「单倍每轮 80 理智，双倍 160」.
* **One or two sentences.** Anything that does not fit goes in `docs/`; the page keeps only the conclusion.

Side by side:

| Before | After |
|---|---|
| 上游 beta.5 那阵它是坏的……rc.1 已修好，中继开机时自动开了回来 | 理智不足时自动使用应急理智加强剂 |
| 勾上的才会去采。3、13 两条上游寻路走不到，先摘掉了；rc.1 说修了寻路，想验证就勾回来 | 勾上的路线才会去采。路线 3 和 13 目前寻路走不到，已取消勾选 |
| 哪几天采。没勾的日子它会立刻结束，日报里看着像秒完成，其实是没排班 | 只在勾选的星期执行。没勾的日子这个任务会立即结束 |
| 开着＝有活动就去刷活动关……826 那次刷错关就是它开着 | 开着＝有活动就刷活动关，活动结束后自动回到上面那个固定关 |

Look at rows two and three: **not one of the facts that mattered was dropped** (which two routes
are not farmed; that the task ends immediately on unchecked days). What was removed is the
provenance and my voice. **The rule is not about making the copy shorter — it is about making it
talk only about the setting.**

## This rule is enforced by a gate

`scripts/mac/lint-repo.sh` scans the `hint` and `label` strings in `web/app.js` and rejects the
commit when it hits a word from the table above. **Documentation cannot stop anything; only the
gate can** — so a newly discovered bad word goes into the gate, not just into this file.

## Do not forget to publish

After changing any file under `web/`, you must run `scripts/mac/deploy-web.sh`, otherwise the
phone still gets the old version — and the moment you are holding a freshly fixed app.js is
exactly the moment this is easiest to forget.

---

## Layout and controls (2026-09-14) - one shape for everything

The user, 2026-09-14: 「太长了……找某一个功能要滑到最底下」「设计不统一……每一项好像各做
各的」「学一下苹果的设计逻辑，抄人家就行了，统一设计内容都是最基本的」.

The page copies iOS Settings and nothing else:

| Rule | What it means in `web/` |
|---|---|
| **One page per game** | Five tabs 状态 / 方舟 / 终末地 / 鸣潮 / 手机 (`layoutTabs`; the HIG asks for as few as the app needs - weekly rows live in their game's tab; more games than fit become a 游戏 list tab with detail pages) in a floating glass tab bar at the bottom (iOS 26/27 Liquid Glass: translucent capsule, blur, specular edge); one tab visible at a time; the last tab is remembered. Nothing is ever added outside a tab |
| **One row shape** | iOS Settings grouped list: small grey header above a white inset card (22px radius), `.row` = name on the left (hint in small grey under it), control on the right, hairline separator inset to the text. Only a row of icons/pills or a long text field may stack. Palette and metrics are Apple's (`:root` tokens in index.html) - no element carries its own colour |
| **A setting is a control, never a button** | on/off → `.sw` toggle (config booleans and relay switches alike, `RELAY_SWITCHES`); a choice → select or pills; a number → number field. Buttons are only for actions (刷新, 现在跑一趟, 停止, 开始刷) and live in `.acts` |
| **Every control answers immediately** | a relay toggle flips at once, the row shows 「已寄出 … 等回执」, and the receipt clears it when the machine reports the new state - the same receipt flow as config edits. A control whose state only changes on the next snapshot is a bug (the 09-14 「点一下」 button was pressed four times) |
| **No new control style** | before adding anything, find the existing row/control that fits; if none fits, change the shared style, not one row |

**Guarantee (2026-09-14):** these five rules are what 「统一」 means on this page. A change
that adds a second way to do the same thing, or a control outside a tab, or a button
where a toggle belongs, is a regression and gets reverted, not argued about.

The rule-by-rule check against Apple's guidelines is `HIG-CHECKLIST.md`; change that file together with the page.

---

## Acceptance runs on the simulator, not on the Mac (2026-09-19)

Supervisor ruling, 2026-09-19 08:3x. The trigger was a measurement mistake, recorded here as it
happened: a static check of commit c3b2b00 on the simulator was run against a stale home-screen
clip (an older port, served from the service-worker cache; the server log for the new port showed
no request), and its numbers were read as an iOS-vs-macOS renderer difference for half an hour.
The rerun on the right clip matched the macOS snapshot on geometry and area and differed only in
line strengths. The rule below still stands: only the simulator decides, and every capture must
prove which commit it measured.

| Rule | What it means |
|---|---|
| **The simulator is the only judge** | Every commit that is a candidate for `main` gets the data session's static check on the iOS simulator, as the home-screen standalone web app, at 3x, same coordinates as the native capture. Release is decided on those numbers only. |
| **`wksnap` is a pre-check** | The macOS offscreen WebKit snapshot is run before a commit is handed over, to catch what is obviously wrong. A commit that passes `wksnap` has passed nothing yet. |
| **iOS/macOS differences are settled on the simulator** | When the two renderers disagree, the cause is found with switch experiments on the simulator (one URL switch per layer or per hypothesis, one 3x screenshot and one number table each). Nothing about the cause is inferred from `wksnap`, and a hypothesis stays in the experiment list until a simulator measurement confirms it. |
| **A capture proves its commit** | Before recording, the server log must show the new clip requesting the commit's files (`tokens.css` / `seg-keys.css` with the new version); a capture without that line is not a check. |
| **Instruments are fixed, numbers are not** | A recorder or comparison script that is found to be biased is fixed and rerun; results are never corrected by shifting frames or columns in a table. |

**Simulator A belongs to the data session only (监督局 2026-09-19 14:4x).** While the data session records on the simulator, the host stays quiet: no xcodebuild, no swift-frontend or swift interpreters, simulator B shut down, and no other session opens Safari on simulator A (four accept runs served into A's Safari on 2026-09-19 pushed the standalone clip to the background and voided two recordings; a background frame-dump interpreter plus a second booted simulator made a tap segment read as a 114 ms stall). Every other session self-checks with headless Chrome (`accept_run.py`, kill the headless process between the light and dark runs) and offscreen WebKit snapshots (`wksnap`); device images are requested from the data session, never captured on A without asking it first.
