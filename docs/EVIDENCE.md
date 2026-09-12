# Evidence bundles and the per-route gathering retry

Written 2026-09-12. Two things the relay does after a run, both born from the
09-10/09-11 gathering failures.

## Evidence bundles (`relay/ark_relay/evidence.py`)

When a run fails (and AUTO-MAS retries it) or finishes but did not do the
work, the relay builds the bundle each upstream project's own export button
would produce, uploads it, and puts the download page in the notification:

| script | what upstream asks for | how it is built |
|---|---|---|
| MaaEnd | 🗄️ export: `MaaEnd-logs-<version>-<stamp>-partNNN.zip` | mirror of MXU `file_ops.rs::export_logs_blocking` (file order, subfolders, 24.5 MB volumes by compressed size, part-number width) |
| MAA | 设置 → 问题反馈 → 生成日志压缩包: `report_<stamp>_partNN.zip` | mirror of `IssueReportUserControlModel.GenerateSupportPayload` (config + resource `_custom` + cache + debug root in part01, debug subfolders ≤3 days old in 20 MB parts) |
| OK-WW | Export Logs: `<gui_title>-log.zip` | mirror of ok-script `StartTab.export_logs` (`screenshots/` + `logs/`) |

None of the three exports is callable from outside its UI (Tauri command,
WPF button, Qt button), so the mirror is the only headless route. The three
source files are pinned in `evidence.PINS` (commit + sha256); every boot
`boot_stages._stage_evidence_sources` fetches them via jsDelivr and sends
「上游改了导出日志的代码」 when a hash moved. Re-verify the mirror, then renew
the pin.

Storage: gofile.io guest folder (free, reachable from the machine; GitHub,
R2, pixeldrain, 0x0.st are not - measured 2026-09-12). Guest files last ten
days after the last download. Local copies under `state/evidence/<run>/bundle`
are pruned after 30 days.

Reading from the Mac: `scripts/mac/evidence.sh list` (mirrors the machine's
index when it is on, otherwise shows the last mirror) and
`scripts/mac/evidence.sh open <run>` (opens the download page). gofile's API
refuses guest listing/downloads without a token its web page generates in
obfuscated JS (measured 2026-09-12: `error-notPremium`, and direct links serve
the HTML shell), so fetching a file is a browser action - open the page, click
the file; with the Chrome tool that is scriptable too. Manual build for one
run on the machine: `python -m ark_relay evidence --script MaaEnd --run-id <run_id>`
(run via winrun with cwd `C:\ProgramData\ark-relay`). A paid-but-trivial S3
bucket (腾讯云 COS / 阿里云 OSS, ≈1 元/月) would make this scriptable; the
uploader is one class (`Gofile`) to swap.

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


## Where bundles go (2026-09-12 evening) - `evidence.pick_uploader`

The user: 「gofile换成能脚本取的cos」. Three stores, the first configured one wins:

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
