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
