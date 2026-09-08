# Maintenance manual

For my own use: how to deploy, how to change config, what to run before
committing.
(The README is the human-facing introduction to the project; anything
operational belongs here.)

## Deploying

The relay deploys to the game machine. It runs the full test suite itself,
rebuilds the manifest, checks every hash one by one, restarts the service and
confirms it came up:

```bash
export ARK_HOST=100.65.39.119
scripts/mac/deploy-relay.sh
```

部署脚本最后一步会把 `scripts/windows/smoke.py` 推到机器上跑一遍冒烟：导入全部模块、读状态表、读通知文案表、读启动之后写下的日志。**冒烟不过就不许打印「部署完成」**（用户 2026-09-06 的死命令）——哈希对得上只证明字节到了，不证明代码跑得起来：坏 import、模块级常量写错、只有机器那版 Python 3.14 才报的问题，三种都能通过哈希核对，然后在第一次 tick 才炸，而服务全程显示 RUNNING。

Before running it you must write `relay/RELEASE-NOTES.md` - that text is the
release note pushed to the phone, and without it the deploy is refused
(`lint-repo.sh` item 5). On a successful deploy it is emptied automatically, so
**it is normal for RELEASE-NOTES.md's hash in the manifest not to match the
file on disk**; gate 14 excludes it.

If you push code without deploying, the machine never gets it - when the
manifest and the code disagree, the boot-time self-update decides "this machine
matches the manifest", downloads nothing and reports nothing. Gate 14 exists to
catch exactly that.

## Publishing the phone page

```bash
scripts/mac/deploy-web.sh
```

After changing any file under `web/` you **must** run this; without it the
phone still has the old version. It does three things: stamps a new version
number onto every link carrying `?v=` (without which the browser, and any PWA
already added to the home screen, keeps serving cache), pushes to `gh-pages`,
and then **measures** - it repeatedly fetches
`https://herclyon1.github.io/maa/index.html` until the version number inside
equals this one, waiting at most 100 seconds; if it never arrives it says so
plainly: 「代码推上去了，但手机上此刻拿到的还是上一版」.
Before 2026-09-08 it printed 「✅ 已发布」 as soon as the push finished, which
made it the last path in this deployment setup that was never measured.

## Changing config

**Do not edit the config files on the machine directly.** Each of the three
games has a master copy and a working copy, and editing the wrong one is the
same as editing nothing; quick config is off for 终末地 and 鸣潮, so changing
them from the AUTO-MAS side has no effect.

* Procedure: [CHANGE-CONFIG.md](CHANGE-CONFIG.md)
* Config inventory: [CONFIG.md](CONFIG.md)
* Read the values actually in effect: `scripts/mac/winrun.sh --py scripts/mac/lib/effective_config.py`

Day-to-day setting changes go through the phone page; from the command line they
go through `scripts/mac/order.sh`:

```bash
scripts/mac/order.sh '{"action":"debug_mode","minutes":90}'   # the next order
scripts/mac/order.sh --clear                                   # clear it once done
```

**Never hand-edit `queue/config.json`.** It is replayed in full: whatever is
left in there from last time gets executed again the next time the version
number is bumped for something else. On top of that the relay fetches it over
jsDelivr, so without a cache purge the order never reaches the machine even
though the screen and GitHub both look correct. `order.sh` handles both -
it overwrites rather than appends, and after pushing it purges the cache and
waits until each door really serves the new version.

## Before committing

Two hard gates, both must be green:

```bash
scripts/mac/lint-repo.sh
```

```bash
scripts/mac/guardcheck.sh
```

The second verifies that the gates themselves are still alive - **a gate that
breaks without saying so is worse than no gate at all** - so it feeds each gate
a known-bad sample and asserts that it must be rejected.

### What the 19 items of `lint-repo.sh` are

| # | What it checks | What is underneath |
|---|---|---|
| 1 | shell script static analysis | `shellcheck -S warning` |
| 2 | PowerShell 5.1 is not allowed (must be pwsh 7) | regex |
| 3 | PowerShell sent over ssh must go as base64 | regex |
| 4 | the script directory must be resolved before any `cd` | regex |
| 5 | the deploy manifest must contain a release note | regex |
| 6 | relay tests all green | `relay/tests/*.py`, run in parallel |
| 7 | no code that can never be reached | `scripts/mac/lib/deadcode.py` |
| 8 | no private wording in the phone page copy | regex; the rules are in `PHONE-COPY-RULES.md` |
| 9 | static analysis | `pyflakes` + a strict compile with the machine's Python 3.14 |
| 10 | test corpora must be committed | counts files, so `.gitignore` cannot keep fixtures out of the repo |
| 11 | the relay's state may only be written by the relay itself | regex |
| 12 | no other people's identifying information in a public repo | regex |
| 13 | every document and script must have an entry point | walks each `docs/*.md` and `scripts/**` back to a reference |
| 14 | the deploy manifest must match the code | compares the hashes in `relay/manifest.json` |
| 15 | what the docs say matches what the code does | `scripts/mac/check-docs.py --local` |
| 16 | logger names must equal `ark.<module name>` | `scripts/mac/lib/loggernames.py` |
| 17 | `check()` in tests may only mean one thing | `scripts/mac/lib/checkshape.py` |
| 18 | anchors pointing at CODE-HISTORY are unique and complete | `scripts/mac/lib/history-anchors.py` |
| 19 | every `# noqa` really suppresses a rule | `ruff check --config ruff.toml` (RUF100) |

Which rules were chosen, and why SLF001/S310/S603 were not, is written in the
comments of `ruff.toml`.

## Running one round by hand

```bash
scripts/mac/run-one.sh MAA|MaaEnd|OK-WW
```

The only front door; the busy/idle gate is built into it. Calling
`/api/dispatch/start` bare is forbidden, and so is `taskkill`.
