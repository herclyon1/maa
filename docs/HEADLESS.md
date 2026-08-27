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

## MaaEnd 扫库：要用 /tasks/start，不是 /tasks/run

2026-08-24 全量扫库跑通了，`IMS.json` 从 44 项长到 **63 项**、`ret=true`。
根因和之前记的完全不一样，**下面这段是实测结论，不是推测**。

### 真正的原因：自定义动作没注册

MXU 的 web API 有两个提交入口：

| 端点 | 载荷 | 会不会拉起 agent |
|---|---|---|
| `POST /api/maa/instances/:id/tasks/run` | `[{entry, pipeline_override, selected_task_id}]` | **不会** |
| `POST /api/maa/instances/:id/tasks/start` | `{tasks, agent_configs, cwd, tcp_compat_mode, pi_envs, reset_state, controller_info}` | **会** |

MaaEnd 的 resource 里绝大多数动作是自定义动作，由 `interface.json` 的 `agent`
段声明的两个子进程注册：

```json
"agent": [{"child_exec": "agent/go-service"},
          {"child_exec": "agent/cpp-algo", "child_args": []}]
```

用 `/tasks/run` 建的实例**没有这两个子进程**，于是 `maafw.log` 里出现：

```
[ERR] Action is null [node_name=__ScenePrivateWorldEnterMenuList] [param.name=RepeatUntilFoundAction]
[ERR] Action is null [node_name=__ScenePrivateMenuListEnterMenuValuables] [param.name=SceneManagerMenuListClickItemAction]
```

**识别全程是好的**——`InMenuList` 命中、OCR 在 `box=[1172,456,78,28]` 找到了
「贵重品库」——只要轮到"点一下"就必然 `Node.Action.Failed`。改用 `/tasks/start`
后一次注册了 **174 个**自定义动作（`AutoAltClickAction`、`RepeatUntilFoundAction`、
`SceneManagerMenuListClickItemAction`…），扫库 30 秒内就开始写盘。

### 可跑的调用

```python
POST http://127.0.0.1:12701/api/maa/instances/<id>/tasks/start
{
  "tasks": [{"entry": "SyncItemData", "pipeline_override": "{}"}],
  "agent_configs": [{"child_exec": "agent/go-service"},
                    {"child_exec": "agent/cpp-algo", "child_args": []}],
  "cwd": "D:\\ark\\maaend",
  "tcp_compat_mode": false, "pi_envs": null,
  "reset_state": true, "controller_info": null
}
```

跑完记得 `POST /api/maa/instances/<id>/agent/stop`，否则两个子进程会一直挂着。

### 之前记错的两处，留着当教训

1. **"一次任务只准扫一次"**——[MaaEnd#5180](https://github.com/MaaEnd/MaaEnd/issues/5180)
   里维护者 overflow65537 说的配额限制**确有其事**，但它不是当时的拦路虎。我把它
   当成定论写进文档，而实测里**全新实例照样失败**，证据当时就摆在那儿，是我没看。
2. **"游戏用 RawInput 过滤了注入键盘"**——查到过这类案例就往上套。实际上
   MaaEnd 的 `Key` 动作按 ESC 完全能开菜单，用 `DirectHit + action:Key + key:[27]`
   的内联 override 当场验证过。键盘从来没有问题。

共同的毛病：拿一个**能自圆其说**的外部解释顶替了"再看一眼日志"。
`Action is null` 这行从第一次失败起就在 `maafw.log` 里。


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
- IMS living **in go-service** is the whole story of why an API-driven scan
  fails: go-service is one of the two `agent` children, and only
  `/tasks/start` spawns them. Verified 2026-08-24 - see the Chinese section
  "MaaEnd 扫库" above for the exact payload.
- The chain is `SyncItemData -> SyncItemDataBegin -> SyncItemDataInProgressionTab
  -> SyncItemDataRunFull`. **"RunFull" means "scan that tab exhaustively", NOT
  "scan the whole depot".** The chain enters the **progression tab** and never
  leaves it, which is why the 63 results only ever cover `valuableTabType`
  4 / 6 / 7 / 10 and why 基质 (tab 2, 156 `gem_*` entries) never appears.
  Do not repeat the mistake of reading "Full" as "whole inventory" - I did, and
  then wrongly blamed MaaEnd for not scanning 基质.
  **Open question (needs the machine):** does `resource/pipeline/nodes.json`
  define sibling nodes for the other tabs, or is the tab switch parameterised so
  `pipeline_override` can retarget it? The task files cached under
  `automas/data/cache/maaend_resource_loader/` do **not** include
  `resource/pipeline/nodes.json`, so this cannot be answered offline.
- Of MaaEnd's task entries only `ProtocolSpace.json` (协议空间) reaches it - and
  协议空间 is in the nightly run, so **the file is refreshed every day with no
  extra work**. To force a refresh, run the MaaEnd script and re-read it.
- **Chinese names: `locales/interface/zh_cn.json`.** Flatten it to
  `{last key segment: string}` and look the id up by exact last segment - all 49
  `item_*` / `ap_*` depot ids resolve that way (`item_gold` -> 折金票,
  `item_expcard_stage2_high` -> 高级认知载体). Match on the **last segment only**;
  a substring match also hits `task.ProtocolSpace.focus.supply_plan.*` status
  templates and returns things like "折金票 未达标，准备刷取协议空间".
  `assets/data/IconRecognition/recognition_items.json` carries category, rarity
  and icon, but its `name` is a hash - it is not the name source.
- The 14 uppercase ids (`T_CREDS`, `OROBERYL`, `VALLEY_STOCK_BILL`, ...) are
  per-task fixed-point OCR nodes, not catalog entries: they appear in **no file
  but `IMS.json` itself**, and their counts do not match the `item_*` entry of
  the same name. Only three are named anywhere - `T_CREDS` 折金票,
  `PROTOPRISM` 协议棱柱, `PROTOHEDRON` 协议棱柱组, via the supply_plan templates.
  Treat the `item_*` set as the depot; ignore the uppercase set.

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
