# Red button — stop everything on the game machine in one shot

```bash
scripts/mac/estop.sh              # stop everything: kill processes + disable the queue timers
scripts/mac/estop.sh --list       # only show what is running, change nothing
scripts/mac/estop.sh --keep-queue # kill processes only, leave the queue timers alone
scripts/mac/estop.sh --restore    # after a stop, set the queue timers back to True
```

**When the user says 「中止」, run this. Do not improvise a command on the spot.**

---

## Why this exists

In the 2026-08-26 incident, the problem itself (a wrong config edit) burned only 2 sanity
potions. **What actually went out of control was the "stop" step:**

| What I did | Result |
|---|---|
| `dispatch/stop` | MAA stopped, but AUTO-MAS immediately brought Endfield back up under a **new PID** |
| Killed MAA/MaaEnd/Endfield/AUTO-MAS, then ran `tasklist` for those four names | Saw "no running tasks" and declared "everything stopped, confirmed" |
| **But 鸣潮 was still running** | It was not on my checklist — that was a **false confirmation** |
| Went to kill 鸣潮 | Quote escaping blew up (`'Wuthering' 不是内部或外部命令`) |
| Retried | ssh timed out |
| In the end | **The user shut the machine down himself; that is what actually stopped it** |

The user's verdict: 「出现问题后你没有进行任何有效的停止行为，全是我手动关的」

So every design decision in this script maps to one of the failure rows above.

## Design points (read before changing it)

1. **Kill twice**, not once. AUTO-MAS may have just launched a new process at the moment it was killed.
2. **AUTO-MAS must be killed too.** Killing only the games is useless — the orchestrator will relaunch them.
3. **Kill processes first; the MAS API is only a supplement.** On the day of the incident the MAS
   config endpoint kept returning `配置已锁定, 无法修改` — 18 attempts, none of them wrote.
   A process, by contrast, can always be killed.
4. **Use `pwsh` 7, not `powershell` 5.1.** 5.1 mangles UTF-8 on read.
5. **Send commands over ssh as base64 `-EncodedCommand`**, never by stitching quotes together —
   that is exactly what blew up that day.
6. **Always verify afterwards**, with a complete list. One missed process name = the stop did not work.

## Process names covered

```
AUTO-MAS  MaaEnd  MAA  Endfield
Client-Win64  Wuthering  wuwa        ← 鸣潮 client (UE; real name still to be verified on the machine)
ok-ww  okww  ok_ww  KRSDK  KRLauncher ← OK-WW and the Kuro launcher
```

To add a name, edit `PATTERN` at the top of the script.

## Side effect: the queue timers get disabled

The default mode sets `TimeEnabled` to `False` on both queues, so the queues do not start on
their own if MAS is reopened. **Without `--restore`, the next morning run will not happen.**
The script prints a reminder about this when it finishes.

To kill processes only and leave the timers untouched, use `--keep-queue`.

## What is left alone

The `ark-relay` service keeps running — it only handles notifications and the boot-time
pre-update, and it never launches a game while running. To stop it as well:

```bash
ssh Administrator@100.65.39.119 'sc stop ark-relay'
```

With it stopped there are no notifications at all, including "the machine is in trouble"
notifications. **Not recommended as a default.**

## Test status

| Item | Status |
|---|---|
| bash syntax (`bash -n`) | ✅ passes |
| Graceful error when the target machine is offline | ✅ passes |
| **Tested against the real machine (kill / verify / restore)** | ⏳ **not done** — the machine was already off on the day of the incident |
| **Real process name of the 鸣潮 client verified** | ⏳ **not done** — requires running `--list` with 鸣潮 open |

**Doing these two is the first thing to do after the next boot.** Until they pass on the real
machine, do not assume this script works.
