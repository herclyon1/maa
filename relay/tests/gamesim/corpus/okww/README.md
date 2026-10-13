# OK-WW verdict corpus (gamesim T8, unit U13a)

Real OK-WW runs from the game machine, each with what the relay must say about it, where that
answer comes from evidence outside the relay's code. `relay/tests/test_gl_corpus_okww.py`
runs the relay's own verdict path on every run and compares; it is part of the relay tests
(Mac gate 0 and `scripts/mac/lint-repo.sh`). This corpus is separate from
`relay/tests/replay/` and follows its conventions: real records, redacted, and the expected
values say **how a run should be judged, not how today's code judges it**. When a case goes red
after a change to the verdict code, decide whether the code or the case is wrong from the
case's evidence; never edit `expect` to match the new output.

## Layout

- `runs/<date>/wuwa/OK-WW-HH-MM-SS.json` - AUTO-MAS's history record, as on the machine
  (`D:\ark\automas\history`).
- `runs/<date>/wuwa/OK-WW-HH-MM-SS.log.gz` - the record's log, gzipped (`*.log` is ignored by
  the repository's `.gitignore`, and gzip keeps the corpus small). Read one with `gzip -dc`.
  The player UID that OK-WW's OCR dumps read from the screen (the digits after 特征码) is
  replaced by `REDACTED`; the test fails if a log carries one, an `AKID` key or a webhook URL.
- `cases.json` - one entry per run:
  - `id`, `run` (path under `runs/` without suffix), `incident` (the failure-table row it
    stands for);
  - `config` - the OK-WW config in effect (`DailyTask`, `NightmareNestTask`), laid out where
    `gamelogs._okww_master_config` reads it; `_source` says where each value comes from (the
    run's own 「只刷」 line, relay.log's sync and set_master lines);
  - `expect` - what must hold: `ok`, `raw` (exact `okww_*` fields, `null` = absent),
    `raw_has` / `raw_lacks` (substrings), `failed_tasks` (`has` / `lacks` / `any_of`),
    `verdict` (`clean`, and `has` / `lacks` over the undone items, the 「· …」 lines of the
    outcome message), `group.any_of` (what reaches the group for a successful round: the
    undone items plus the ERROR lines `gamelog_errors` has not registered);
  - `evidence` - `[{kind, ref}]`, kinds `ledger` (BOARD/报错台账.txt), `owner` (his words, with
    where they are written), `commit`, `alarm` (state/alerts copy of what was pushed), `frame`,
    `log` (line numbers in this run's log), `relay` (relay.log / ledger lines);
  - `proof` - `red_at` (commits whose relay judges this run wrong) and `green_at` (the fix).
- `prove.py` - runs the test against `git archive <commit> relay` for every `red_at` and
  `green_at` and checks red-then-green; a red must be an assertion of this case, not an import
  or harness error.

Assertions are substrings tied to a cited line, frame or ledger entry, never a whole label of
today's wording, so a reworded message does not turn a case red while a wrong verdict does.

## Adding a case

1. Copy the record and its log from the machine's history (or the scratch pull), redact the
   UID, gzip the log with mtime 0.
2. Write `expect` from the evidence and cite it. Labels may be drafted from today's output,
   but every incident run's expectation must be what the evidence says.
3. Name the fix in `proof` and run `python3.14 relay/tests/gamesim/corpus/okww/prove.py
   --case <id>`: red at the fix's parent, green at the fix. Paste its row below.

## Proof (prove.py, 2026-10-13, on c54d9537's history)

| case | red at | green at | first red assertion |
| --- | --- | --- | --- |
| 0907-05-19-17-entered-not-unreachable | 3287c40d~1 red | 3287c40d green | raw okww_unreachable: want None, got True; failed_tasks has '流程产生错误': ['OK-WW 流程产生错误，请检查游戏状态']; failed_tasks has none of ['FarmEchoTask', '周本']: ['OK-WW 流程产生错误，… |
| 0907-06-00-55-entered-not-unreachable | 3287c40d~1 red | 3287c40d green | raw okww_unreachable: want None, got True; failed_tasks has '流程产生错误': ['OK-WW 流程产生错误，请检查游戏状态']; failed_tasks has none of ['FarmEchoTask', '周本']: ['OK-WW 流程产生错误，… |
| 0907-06-08-44-entered-not-unreachable | 3287c40d~1 red | 3287c40d green | raw okww_unreachable: want None, got True; failed_tasks has '流程产生错误': ['OK-WW 流程产生错误，请检查游戏状态']; failed_tasks has none of ['FarmEchoTask', '周本']: ['OK-WW 流程产生错误，… |
| 0921-weekly-never-entered | 4fb720e6~1 red | 4fb720e6 green | raw okww_steps lacks '没进本': '["无音区 ×1", "残象聚落（已刷满）", "周本（没做完，原因见失败于）", "周常乐园（本周已完成）"]'; raw okww_error has '退出副本': '周本：打完 Boss 领完奖之后没能退出副本'; undone items lack '… |
| 0922-weekly-full-before-entry | 4fb720e6~1 red | 4fb720e6 green | raw okww_steps lacks '0/3': '["无音区 ×1", "残象聚落（已刷满）", "周本（已完成，本周已领满）"]'; raw okww_steps lacks '这一趟没领': '["无音区 ×1", "残象聚落（已刷满）", "周本（已完成，本周已领满）"]' |
| 0929-battle-pass-error-heard | a6fdd68b~1 red | a6fdd68b green | the group hears none of ['战令', 'can not battle pass']: '· 周本领到了奖励：点了确认 1 次、领完没再读次数，没核实领到' |
| 1006-full-week-no-shortage-alarm | b799746e~1 red, 12edfb0b~1 red | 12edfb0b green | verdict clean: want True, got 'OK-WW 这一轮有 1 项没干成，但它自己没报错：\n· 周本领到了奖励：结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」）\n干成的：残象聚落只刷指定点位（过滤生效）、残象聚落没进别的点位、每日任务跑完、残象聚落（已满，跳过）、刷体力' |
| 0901-shortage-at-start-said-as-shortage | 3f6b2fbe~1 red, 5ef071e7~1 red | 5ef071e7 green | undone items lack '结晶波片不足': ['· 周本：没进本，一次没打：传送去 Boss 没成']; undone items have '传送去 Boss 没成': ['· 周本：没进本，一次没打：传送去 Boss 没成'] |
| 0831-shortage-before-fight-said-as-shortage | 3f6b2fbe~1 red, 5ef071e7~1 red, f912c1f0~1 red | f912c1f0 green | verdict clean: want False, got None; undone items lack '结晶波片不足': [] |
| 1005-additional-task-error-heard | 5fddd375~1 red | 5fddd375 green | undone items lack '附加任务出错': ['· 残象聚落：点了点位，但传送不过去，一次没打', '· 周本：进了本，但日志里没有开打的记录：一次没打'] |
| 1012-second-run-weekly-stop-heard | f912c1f0~1 red | f912c1f0 green | verdict clean: want False, got None; undone items lack '周本': []; undone items lack '没等到结算页': [] |

## Listed failures with no case, and why

- **09-08 3d5c7001** (refused nest patch, every report said 「只打落渊南丘」): the fix changed the
  tomorrow-plan text (`plan.py`, `texts.py`, `nest_patch_present()` reading the install
  directory), not a run verdict; across all 131 recorded OK-WW runs the verdict path gives
  the same output at 3d5c7001~1 and 3d5c7001, and no run of that time shows a refused patch
  (the 09-07 and 09-09 logs show the filter at work; 09-08's three runs stopped before the
  nest task).
- **10-07 9749f7f4** (partial claim + shortage label order): no recorded run claimed and then
  ran short; all six real shortages (08-31/09-01 hand-runs) claimed nothing. 3f6b2fbe says
  the same ("there is no real shortage sample yet").
- **10-07 3f6b2fbe / 4c1b58aa as fixes**: 3f6b2fbe made a shortage a green item and 5ef071e7
  (10-11) reversed that; a case green at 3f6b2fbe would assert the reversed verdict. The two
  real shortage cases are red at 3f6b2fbe~1 and green from 5ef071e7 / f912c1f0. 4c1b58aa
  changed mainly the overlay (game layer) and seven lines of outcome.py; no recorded run's
  verdict differs across it.
- **10-12 c1ae107b** (nests not farmed because the nest patch did not apply): its input line
  「只刷指定点位的改动没装上，这一轮不刷巢穴」 is in none of the 131 recorded logs (the shape exists
  only in the fix's synthetic test).
- **10-12 5fddd375 on its own run**: the 11:41 run that motivated it (OK-WW-07-41-07) is
  already red at 5fddd375~1, because f912c1f0 fixed it first; 5fddd375's catch-all is shown on
  the 10-05 run instead.
- **09-23 4fb720e6, settlement stamina part**: the reward-dialog line it reads was not in any
  log yet when it was fixed (the commit says so); the 09-21 log has only the plain reading.
