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
