# Evidence bundles and the per-route gathering retry

Written 2026-09-12. Two things the relay does after a run, both born from the
09-10/09-11 gathering failures.

## Evidence bundles (`relay/ark_relay/evidence.py`)

When a run fails (and AUTO-MAS retries it) or finishes but did not do the
work, the relay builds the bundle each upstream project's own export button
would produce, uploads it, and puts the download page in the notification:

| script | what upstream asks for | how it is built |
|---|---|---|
| MaaEnd | 🗄️ export: `MaaEnd-logs-<version>-<stamp>-partNNN.zip` | mirror of MXU `file_ops.rs::export_logs_blocking` (file order, subfolders, 24.5 MB volumes by compressed size, part-number width), **selection cut to the time window** |
| MAA | 设置 → 问题反馈 → 生成日志压缩包: `report_<stamp>_partNN.zip` | mirror of `IssueReportUserControlModel.GenerateSupportPayload` (config + resource `_custom` + cache + debug root in part01, debug subfolders **in the window** in 20 MB parts) |
| OK-WW | Export Logs: `<gui_title>-log.zip` | mirror of ok-script `StartTab.export_logs` (`screenshots/` + `logs/` **in the window**) |

**Every bundle is cut by a time window - there is no full export** (the user,
2026-09-18: 「证据包永远按时间窗取」). The relay's automatic bundle for a failed run
uses that run's start and end widened by `evidence.WINDOW_SLACK` (5 minutes each
side). Inside the window MaaEnd's error screenshots are de-duplicated by content and
capped at `evidence.MAAEND_MAX_IMAGES` (12). Why: MXU's own export takes every log
the debug folder ever kept - on 2026-09-17 that was 130 logs / 2.7 GB, 221 MB
compressed, and the upload failed four times; the same failed run cut to its window
is 11 MB.

None of the three exports is callable from outside its UI (Tauri command,
WPF button, Qt button), so the mirror is the only headless route. The three
source files are pinned in `evidence.PINS` (commit + sha256); every boot
`boot_stages._stage_evidence_sources` fetches them via jsDelivr and sends
「上游改了导出日志的代码」 when a hash moved. Re-verify the mirror, then renew
the pin.

Storage: Tencent Cloud COS only (2026-09-18, the user pays for the bucket:
「上传只走 COS」); the gofile / WeCom fallbacks below are switched off in
`evidence.uploaders` and kept as code. Local copies under
`state/evidence/<run>/bundle` are pruned after 30 days.

Reading from the Mac: `scripts/mac/evidence.sh list` (mirrors the machine's
index when it is on, otherwise shows the last mirror) and
`scripts/mac/evidence.sh open <run>` (opens the download page). gofile's API
refuses guest listing/downloads without a token its web page generates in
obfuscated JS (measured 2026-09-12: `error-notPremium`, and direct links serve
the HTML shell), so fetching a file is a browser action - open the page, click
the file; with the Chrome tool that is scriptable too. Manual build on the
machine (run via winrun with cwd `C:\ProgramData\ark-relay`), always with a window:

    python -m ark_relay evidence --script MaaEnd                 # the latest MaaEnd run in the ledger, its own window
    python -m ark_relay evidence --script MaaEnd --run-id 2026-09-17/endfield/MaaEnd-06-28-53
    python -m ark_relay evidence --script MaaEnd --hours 2       # everything of the last two hours
    python -m ark_relay evidence --script OK-WW --since 2026-09-17T10:20

Measured 2026-09-18 on the machine: `--hours 2` after a MAA make-up run, see the
number in the commit that introduced the window.

## Per-route retry (`relay/ark_relay/collect_retry.py`)

Upstream declined a per-route retry (MaaEnd/MaaEnd#5660). The relay does it
after the queue is idle, once per day, from the shutdown decision
(`shutdown._maybe_shutdown`): failed routes are read from the AUTO-MAS log
(「路线15：红矛叶采集失败」, ids from MaaEnd's zh_cn locale), the override MXU
logged for the run is reused with only those routes and today's weekday, the
game and MaaEnd are launched on the interactive desktop and driven over the
MXU API, and the verdict comes from MaaFW's `RouteNEnd` / `RouteNFailed`
events. Two consecutive days of the same route failing its retry is reported
as 「疑似复发性问题」 with a request for a person to file it upstream.

Manual: `python -m ark_relay collect-retry [--day YYYY-MM-DD]`. State under
`state/collect-retry/` (one stamp per day, `failures.json` per route).

### AUTO-MAS's own retry round (`relay/ark_relay/collect_watch.py`, 2026-09-14)

AUTO-MAS answers a failed 自动采集 by re-running the whole script up to
`RunTimesLimit` times, copying the master `mxu-MaaEnd.json` into MaaEnd's config
dir before **each** attempt (`AutoProxy.set_maaend`, inside the retry loop). The
relay makes that retry per-route by narrowing the master's `AutoCollect*Routes`
lists to the failed routes while the failing attempt is still ending.

Why the first version (narrow when the failing *record* lands, 09-12) never
fired: AUTO-MAS writes all attempts' records of one task at the end of the whole
task - on 09-14 four attempts were all stamped 11:49:18, and the relay narrowed
at 11:54:56 and restored the same second. The live source is MaaFW's own log,
`<MaaEnd>/debug/maafw.log`: `[msg=Node.Action.Starting] ... "name":"AutoCollectRoute10Failed"`
is logged at the end of the schedule (09-14: 11:20:22, retry launched 11:21:43),
`[msg=Tasker.Task.Starting] ... "entry":"AutoCollectSchedule"` marks the next
attempt. The watcher sleeps on a directory-change notification for `debug/`
(watch.py), reads the appended bytes only, follows the rotation into
`maafw.bak.<stamp>.log` (MaaFW rotates on process start, i.e. two seconds after
the Failed line), narrows on each Failed node (`collect_retry.narrow_master`,
which now accumulates a second route instead of intersecting), and restores at
the retry's Task.Starting. The record-time restore, the shutdown-time restore
and the boot-time restore stay as backstops.

Drill on the machine: `scripts/mac/collect-watch-drill.sh` (feeds the real
09-14 lines into the live log, asserts narrow + restore, truncates the log back,
restarts the relay). Passed twice on 2026-09-14 (12:32, 12:36); the relay logs
`ark.collect_watch` lines for every step.

Proven in a real AUTO-MAS retry, 2026-09-14 13:09-13:47 (gathering-only run via
`scripts/mac/lib/maaend_only_task.py`): attempt 1 walked 17 routes, Route16
failed 13:37:53 → master narrowed 13:37:56; retry started 13:39:16 → master
restored 13:39:17; the retry walked **only Route16** (13:39:45-13:43:27, failed
again → narrowed 13:43:30); attempt 3 walked only Route16 and passed (13:44-13:47).
First run 28 min, retries 4 and 3 min.


## Where bundles go (2026-09-12 evening) - `evidence.pick_uploader`

The user: 「gofile换成能脚本取的cos」, and on 2026-09-18 「上传只走 COS」 - stores 2-4
below are no longer tried (commented out in `uploaders()`, classes kept):

1. **Tencent Cloud COS** (`Cos`): signed PUT of each file to
   `https://<bucket>.cos.<region>.myqcloud.com/<run_id>/<name>` using the XML API
   signature (q-sign-algorithm=sha1; verified step by step against the official recipe
   in `tests/test_evidence.py`). Needs, in the machine's `.env` **and** in the Mac's
   `~/.config/ark/push.env`: `COS_SECRET_ID`, `COS_SECRET_KEY`, `COS_BUCKET`
   (`name-appid`, e.g. `ark-evidence-1250000000`), `COS_REGION` (e.g. `ap-shanghai`).
   Only the account owner can produce these (实名 account, a bucket, an API key); the
   relay switches to COS the moment they are there - nothing else to change.
2. **WeCom app file messages** (`WeComFiles`): the credentials the relay already pushes
   with. The archive is sent to him as one file message when it is under 20 MB; the Mac
   fetches it back with `media/get` within WeCom's three-day window (`evidence.sh pull`).
   Refuses anything bigger - the next store takes it. (2026-09-12 20:04 the app API
   answered 60020: the machine's IP is not on the app's trusted list.)
3. **WeCom group robot** (`WeComBotFiles`): same 20 MB cap, no trusted-IP list, no
   fetch-back API - for his eyes in the group.
4. **gofile** (`Gofile`): last resort, any size, web page only.

**One file per run** (the user, 2026-09-12: 「一个游戏脚本我只允许一个文件。不分卷，不切段」):
`save_and_upload` packs the upstream export (its own volumes untouched inside) plus the
AUTO-MAS record into a single stored zip `<script>-<run_id>.zip` and ships only that.
Unzip it to hand upstream exactly the files their export button would have produced.

`state/evidence/index.jsonl` carries `store`, and per file the COS key or the WeCom
media ids with `expires`. `scripts/mac/evidence.sh list | pull | open`.

Setting COS up once the account owner has an API key: `scripts/mac/cos-setup.py`
(reads COS_SECRET_ID / COS_SECRET_KEY / COS_APPID from `~/.config/ark/push.env`, creates
`ark-evidence-<appid>` in ap-shanghai with a 90-day expiry rule, probes it, writes the
COS_* lines into both .env files and restarts the relay). Measured 2026-09-12 20:04: the
WeCom **app** API refuses the machine (60020, IP 112.43.41.80 not on the trusted list),
so the chain skipped to the group robot in one step and delivered 6 files / 9 messages
in 60 s. 21:45 the same day the IP was added in the admin console (`scripts/mac/wecom-trust-ip.sh`
does that from the Mac; the list held 4 entries afterwards, and a message sent from the machine
through the app went out) - the app store is back. The IP still rotates (dial-up line), so the
next 60020 means: run that script again. Verified 21:25: a real failure bundle went to COS as
one 84 MB archive in 18 s, pulled back with `evidence.sh pull` and unpacked to the 6 files.
Also: the group robot is store 「wecom-bot」 - human-readable only, no fetch-back API.

## OK-WW bundles carry a desktop screenshot (since 2026-09-19)

OK-WW's own export is its log plus whatever screenshots it chose to save. On
2026-09-19 the log stopped at 09:34:40 (characters loaded, then nothing) and
AUTO-MAS killed the run two hours later; the export held one file and nothing
showed what the game had been displaying. `evidence.save_and_upload` now adds
`desktop-<YYYYmmdd-HHMMSS>.png` to every OK-WW bundle - one picture of the real
desktop through `desktop.Desktop.screenshot()` (the interactive-session agent
that the launcher OCR already uses). Caveat in the filename: the picture is
taken when the record lands, and AUTO-MAS writes records at the end of the
whole script run, so after a retry it shows the state after the retry, not the
failure. A picture that cannot be taken (no interactive session, a Mac, a
test) is simply absent; the bundle is otherwise unchanged.

## The diagnostics bucket (since 2026-09-23)

A **second, separate** bucket, `ark-diag-<appid>` (ap-shanghai, built and measured
2026-09-23 04:0x by `scripts/mac/cos-setup.py --diag`). It holds the records the
phone page writes when he taps 诊断记录 while he is out: one JSON object per tap,
PUT from the browser with **no credentials at all** under the `diag/` prefix.

It is not the evidence bucket, and the reason is the machine: the evidence bucket
is the first door of the relay's self-update (`relay/ark_relay/selfupdate.py:117`
`COS_PREFIX = "relay"`, `:129-134` the same `COS_SECRET_ID/KEY/BUCKET/REGION`
client; the GitHub fallbacks are off by default), so it decides what code the game
machine installs. Anonymous writes never go near it.

Three settings, and nothing else (readbacks measured 2026-09-23):

| setting | body | readback |
|---|---|---|
| lifecycle | one rule, whole bucket (`<Prefix/>` empty), `<Days>7</Days>` | `GET /?lifecycle` 200, rule `diag-expire-7d` |
| policy | `qcs::cam::anyone:anyone` → `name/cos:PutObject` on `qcs::cos:ap-shanghai:uid/<appid>:ark-diag-<appid>/diag/*` | `GET /?policy` 200, COS added its own `Sid` |
| cors | `https://herclyon1.github.io`, method `PUT`, `ExposeHeader` ETag, `MaxAgeSeconds` 600 | `GET /?cors` 200 (COS appends `<ResponseVary>false</ResponseVary>`) |

`OPTIONS` is not a CORS `AllowedMethod`: the enum is 「PUT、GET、POST、DELETE、HEAD」
(https://cloud.tencent.com/document/product/436/8279). COS answers the preflight
itself once a rule matches - measured below. `PUT Bucket policy` answers **204 No
Content** on success, not 200 (官方响应示例「HTTP/1.1 204 No Content」,
https://cloud.tencent.com/document/product/436/8282); lifecycle and cors answer 200.

The six anonymous measurements `cos-setup.py --diag [--check]` runs every time
(2026-09-23 04:0x, all six as expected):

| measurement | reading |
|---|---|
| anonymous PUT into `diag/` | 200, `Access-Control-Allow-Origin: https://herclyon1.github.io` |
| anonymous PUT outside `diag/` | 403 AccessDenied |
| anonymous GET of the object just written | 403 AccessDenied |
| anonymous list of the bucket | 403 AccessDenied |
| preflight OPTIONS from our origin | 200, allow-methods `PUT`, max-age 600 |
| preflight OPTIONS from another origin | 403 AccessForbidden |

Only `cos:PutObject` is granted, so **a browser `<form>` upload would be refused**
(that is `cos:PostObject`, which is deliberately not in the policy) - the page has
to PUT. The page side must also give every key a long random suffix
(`diag/<date>-<random>.json`): anyone can write into that prefix, and a guessable
key can be overwritten.

**Pulling the records: `scripts/mac/diag-pull.py`** (lists `diag/` with the signed
key, downloads everything not already on disk into `~/Claude/ark-diag/`, `--list`
to look without downloading). End-to-end measured 2026-09-23 04:06: an anonymous
PUT of a 54-byte record, then `diag-pull.py` fetched it to
`~/Claude/ark-diag/2026-09-23-endtoendprobe01.json` byte-for-byte; the probe was
then deleted with a signed DELETE (204).

**A record that is not pulled within 7 days is gone** - the lifecycle rule deletes
every object 7 days after it was written, and nobody but us can read them back.
The owner set that number on 2026-09-23 (「正常来说你们第一天就该修复了」): a record
is worth pulling the day he reports it, and one that has sat untouched for a week
has already failed its purpose. Pull as soon as he reports anything.

Deliberately **not** configured on this bucket (the owner's 2026-09-23 instruction:
the only threat we defend against is tampering with what the game machine installs,
which lives in the other bucket): no hotlink/Referer whitelist, no cloud-monitor
alarms, no request-rate cap, no content-length cap. `COS_DIAG_BUCKET` in
`~/.config/ark/push.env` is what both scripts read.
