<title>Headless operation</title>

# Operating all three without a UI

> **When something here is unclear, or an attempt fails: read the official docs
> first - `faq.md` before anything else. Do not start experimenting.**

The desktop is only composited while something consumes frames. With nobody
watching the machine, a screen grab returns the last frame drawn: on
2026-08-23 the taskbar clock in a fresh screenshot was 25 minutes stale and
MAA's window came back as a blank white rectangle while the process was
perfectly healthy. Anything that depends on seeing the screen is therefore
unreliable by default, and every one of these three programs can be driven
without it.

Screenshots of the *emulator* are not affected - those come over ADB and are
independent of the Windows desktop.

## AUTO-MAS - a REST API

Its Electron window is a shell over a FastAPI backend, so the machine
publishes its own contract.

```bash
# the client
export ARK_HOST=100.65.39.119
scripts/mac/mas-api.py paths                      # all 126 endpoints + required fields
scripts/mac/mas-api.py get /api/info/get/overview
scripts/mac/mas-api.py get /api/history/search '{"mode":"DAILY","start_date":"2026-08-23","end_date":"2026-08-23"}'
```

Measured 2026-08-23: `http://<tailscale-ip>:36163`, **no authentication**, port
unchanged across a reboot. It binds `0.0.0.0`, so anything that can route to
the machine can drive it - acceptable on Tailscale, and the first thing to
close if the box ever leaves that network.

### Three traps, all of which cost time before they were written down

1. **Mutating endpoints wrap the payload in `data`.** Sending the inner object
   alone returns something that is not the usual envelope and changes nothing -
   a silent no-op.
   ```jsonc
   {"data": {"Function": {"IfBlockAd": true}}}                       // setting/update
   {"queueId": "<uid>", "data": {"Info": {"TimeEnabled": false}}}    // queue/update
   {"scriptId": "<uid>", "userId": "<uid>", "data": {...}}           // scripts/user/update
   ```
2. **Enum values are not guessable.** `history/search` wants `DAILY` / `WEEKLY`
   / `MONTHLY`, not `day`. The API says so itself in a 422 body - which is why
   `mas-api.py` prints the rejection instead of raising on it.
3. **`/openapi.json` is the authority.** Read the schema before composing a
   request; do not infer the shape from a summary.

### What each endpoint is for

| Endpoint | Use |
|---|---|
| `/api/info/get/overview` | current event stages with drops and expiry; **`Proxy`** carries each user's `LastProxyDate` / `ProxyTimes` / `ErrorTimes` |
| `/api/history/search` `{mode,start_date,end_date}` | runs for a date range, already parsed: real start time, `DONE` status, drops, recruit stats, error info |
| `/api/history/data` `{jsonPath}` | one record in full |
| `/api/queue/*` | queues, their times and items |
| `/api/scripts/get` · `/api/scripts/user/update` | script and per-user settings (stage, medicine, tasks) |
| `/api/setting/get` · `/api/setting/update` | global settings |
| `/api/dispatch/start` `{taskId, mode}` · `/stop` `{taskId}` | run or abort a task; mode `AutoProxy` |
| `/api/dispatch/set/power` `{signal}` · `get` · `cancel` | the power-off decision |
| `/api/emulator/status` · `/operate` | emulator, instead of `ldconsole` |
| `/api/ocr/screenshot/adb` · `/click/text` · `/click/image` | see and click without coordinates |
| `/api/scripts/maa/depot/items` `{scriptId}` | items selectable for 库存保持 |

## MAA - MaaCore through the binding it ships

MAA installs its own Python binding at `<MAA>/Python/asst/`. Use that one: it
matches the installed core exactly.

```python
sys.path.insert(0, str(MAA / "Python"))
from asst.asst import Asst
from asst.utils import InstanceOptionType, Message
Asst.load(path=MAA)                       # loads MaaCore.dll + resources
a = Asst(callback=cb)
a.set_instance_option(InstanceOptionType.touch_type, "minitouch")
a.connect(r"D:\LD-MRFZ\LDPlayer9\adb.exe", "127.0.0.1:7555")
a.append_task("StartUp", {...}); a.append_task("Copilot", {...})
a.start()
while a.running(): time.sleep(2)
```

`scripts/windows/copilot-drive.py` is the working example. The recipe, the
per-mode differences and the failure modes are in OPERATIONS.md under
"MAA's auto-battle"; the short version:

- **Never truncate a callback.** The field that separates "operator not owned"
  from "operator under-trained" sits past 260 characters.
- **`ignore_requirements: true`**, always. A job's 练度要求 is the author's
  preference, not a game constraint, and enforcing it aborts whole formations.
- **Detect a stall by repetition, not silence.** A navigation that cannot find
  its stage emits callbacks forever.

## MaaEnd - through AUTO-MAS, and its inventory file

MaaEnd is a MaaFramework project. It ships `maafw/MaaPiCli.exe`, the official
headless runner - but **it resolves `interface.json` next to its own
executable**, which in MaaEnd's layout is `maafw/`, not the project root, and
`-d` does not change that. Running it in place fails to parse. So the practical
headless route for MaaEnd is AUTO-MAS: `/api/dispatch/start` with the MaaEnd
script id and mode `AutoProxy`.

### Inventory: IMS

MaaEnd *does* have an inventory readout. It is called IMS (Item Management
System), lives in the go-service process, and is documented at
`docs/zh_cn/developers/components/ims.md` in MaaEnd's repo.

- `SyncItemData` scans the current screen and writes **the whole table** to
  `<MaaEnd>/debug/record/IMS.json` as `{updated_at, items: {<id>: <count>}}`.
- The chain is `SyncItemData -> SyncItemDataBegin -> SyncItemDataInProgressionTab
  -> SyncItemDataRunFull`, so that pass **is** the full scan.
- Of MaaEnd's task entries only `ProtocolSpace.json` (协议空间) reaches it - and
  协议空间 is in the nightly run, so **the file is refreshed every day with no
  extra work**. To force a refresh, run the MaaEnd script and re-read it.
- Ids resolve through `assets/data/IconRecognition/recognition_items.json` for
  category, rarity and icon - but its `name` is a hash, so readable names are
  not in MaaEnd's data. The uppercase ids (`T_CREDS`, `OROBERYL`,
  `VALLEY_STOCK_BILL`) are per-task fixed-point OCR nodes, not catalog entries.

## Can the relay move entirely to this? No - and here is the line

Everything the relay does that touches the outside world, and whether the API
can take it over:

| What the relay does | Today | Can the API do it |
|---|---|---|
| Read run records | scans `history/` and parses filenames | **Yes, better** - `history/search` returns real times, status and drops already parsed. Today's outage was a filename-format change that this would not have noticed |
| Know whether a user ran, and failed | derived from records | **Yes** - `overview.Proxy` has `LastProxyDate` / `ProxyTimes` / `ErrorTimes` per user |
| Change the farming stage, medicine, tasks | rewrites `ScriptConfig.json` | **Yes** - `scripts/user/update`, and no stop-restart needed |
| Enable/disable a queue (skip mode) | rewrites `QueueConfig.json` | **Yes** - `queue/update` |
| Power the machine off | `shutdown /s /t 60` | **Yes** - `dispatch/set/power`; needs its signal values checked before use |
| Tell whether a script is running | `tasklist` | **Probably** - via `dispatch` state; not yet confirmed |
| **Revive a dead AUTO-MAS** | `taskkill` + `schtasks /run` | **No.** The API dies with the backend it belongs to. This must stay local |
| **Kill MaaEnd for the pre-update** | `taskkill` | **No** - it is not AUTO-MAS's process |
| Its own state, ledger, notifications | local files, Server酱 | **No, by design** - the relay is the only notifier, and its state must survive AUTO-MAS being down |

**So the honest answer is: most of it, not all.** The parts that cannot move are
exactly the parts whose job is to survive AUTO-MAS failing - which is the whole
reason the relay exists as a separate service. Migrating the rest removes the
stop-edit-restart procedure and the fragile filename parsing, and that is worth
doing; migrating the watchdog would make it useless.
