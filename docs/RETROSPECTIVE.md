# The mistakes made, and what stops them now

The reason for writing this down is blunt: making the same kind of mistake a
second time means the first time produced nothing but "be more careful next
time" - no mechanism that remembers on my behalf. So every row has to answer one
question - **next time, who calls a halt first?**

Rows marked "no automated guard" are the honest admissions: nothing catches
them, only the rule does. Not dressed up.

## 1. Stating something unverified as if it were a fact

The most expensive kind, because a wrong conclusion gets used as the basis of a
decision.

| What happened | What stops it now |
|---|---|
| Read two drop names, 家具零件 and 沿途的点滴, out of mojibaked GBK bytes - **neither of them exists** - and reported them as real data | `winrun.sh` is UTF-8 end to end in all three modes, and files come back as bytes; `--py` keeps a script out of any console |
| Said materials had only six conversion lines (there are eight) - because the filter went by name and dropped 碳 and 技巧概要 | Rule: **filter by structure, and print what got dropped**. No automated guard |
| Said MaaEnd "has no inventory readout" - IMS was there the whole time | Standing order: read the official docs before experimenting. `docs/HEADLESS.md` records where IMS lives |
| Called 43 items "the whole depot" - it was a cache accumulated over past runs | No automated guard. Rule: before saying "whole", find the log of the scan that actually covered everything |
| Said an inventory scan "costs sanity" | No automated guard |
| Read `Missing` as "the account does not own that operator" - the real cause was the training-level requirement | Callbacks are no longer truncated; `ignore_requirements` is written down |
| Called MaaEnd's UI layer "closed source" - it is `MistEO/MXU`, AGPL | No automated guard. Rule: before saying "closed source", search the log text and read `.gitmodules` |
| Carried the "updates every day" conclusion from MaaEnd over to MAA without measuring anything | No automated guard. Rule: if you state a frequency, go and count it. MAA, measured: 8 times in 7 weeks |
| Said the AUTO-MAS auto-install "might fail", with zero evidence, to push the decision back onto the user | See the `no-unfounded-risk-hedging` memory. Rule: find the failure mechanism first; if there is none, finish the feature |

**What they share**: all of these are "something I inferred" told as "something
I looked up". The only real defence is a re-checkable source behind every
conclusion.

## 2. Encoding and quoting

| What happened | What stops it now |
|---|---|
| The Windows console's CP936 shredded UTF-8 output, which produced the hallucination above | `winrun.sh` in all three modes; `.ps1` written with a BOM; `PYTHONUTF8=1` |
| A PowerShell escaped single quote `''` written inside a bash single-quoted string ended the string early, so the command never ran at all | **`winrun.sh --py`**: the script is pushed as a file, and no layer parses it |
| `set PYTHONUTF8=1 && cmd` counted the trailing space as part of the value and Python refused to start | Same as above; `--py` already writes it internally as `set X=1&&` |
| Not clearing `winrun.out` before each run, so a failure read back the previous run's stale output | `winrun.sh` deletes it before every run |

## 3. Leaks

| What happened | What stops it now |
|---|---|
| A broad grep printed `WECOM_SECRET` into the transcript | **`scripts/mac/redact.py`**, and `winrun.sh --get` goes through it **by default** |
| Printing a whole config carried out the first few dozen characters of `cdkEncrypted` | Same as above. Raw bytes require an explicit `--get-raw` |

The safe one has to be the default - once something is in the transcript it
cannot be taken back.

## 4. Acting before looking properly

| What happened | What stops it now |
|---|---|
| `vclick` took a mouse-hover highlight for a successful click | Changed to compare an independent check region after the click |
| Compared only one of the three colour channels (white and the theme blue both have B = 255) | All three channels are compared |
| `$i.mi.dx = …` mutated a copy, so the input was never sent | No automated guard (PowerShell value-type semantics) |
| An automatic retry flipped a switch that had already been set back again, then reported failure | The automatic retry was deleted |
| Blind ADB coordinates, repeatedly clicking into 采购中心 and 生息演算 | Rule: screenshot before the click, screenshot after |
| Tried `--help` on `MAA.Updater.exe` without having read anything about it; it hung in session 0 | Standing order: read the source or the docs first. The correct usage came from the comment at the top of `main.cpp` |
| A path-rewriting script edited 12 `.bak-*` backups along with the real files | No automated guard. Rule: a bulk rewrite prints the list of what it is about to change first |

## 5. Process

| What happened | What stops it now |
|---|---|
| **Deployed with tests red** | **`deploy-relay.sh` step 0 runs the whole test suite and exits unless everything is green** (measured: it has blocked a deploy) |
| The `_boot_time` method did not exist at all, and the service crashed in the middle of the night | `tests/test_self_attrs.py`: an AST scan of every `self.x` |
| The collector stopped recognising record files after they were renamed | `tests/test_record_names.py` tests both naming schemes |
| Fixing a bug also released a previously suppressed shutdown | `tests/test_debug_window.py`; `docs/PITFALLS.md` has a section on it |
| Polled in the background for 8 hours 54 minutes, roughly 1600 SSH calls | Standing order: polling needs approval. No automated guard |
| Abandoned a task before it was done (EX-8, the `Missing` investigation) | Standing order: when stuck, change method; narrowing the scope has to be asked |
| After the directory move, Windows quietly created a Block firewall rule and every API went down | `check-docs.py` has remote checks; ports must be re-verified after a move |
| `Invoke-WebRequest` took 24 minutes to download 19MB | `docs/OPERATIONS.md` states it plainly: large files always go through `curl.exe` |
| Assumed Python 3.13 without looking (3.14 was already out) | Rule: look up the current version number before installing |

## How to use this

After something goes wrong, look here for the same kind first. If it is here,
the guard either failed or was never there - fix the guard before the bug. Only
if it is not here is it a new kind; deal with it, then add a row.
