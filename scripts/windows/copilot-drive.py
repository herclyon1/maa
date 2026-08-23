"""Clear a list of stages with MAA copilots, swapping jobs when one will not work.

Runs entirely on the machine as a scheduled task, so nothing depends on an SSH
session staying up. Three things it must survive on its own, because there is
nobody watching:

  * a job that needs an operator the account does not own - MAA reports
    ``BattleFormationTask`` with ``reason: Missing`` before spending any
    sanity, and the answer is simply the next job for that stage;
  * a run that stops making progress - the core can sit in a screen it does
    not recognise, and a copilot that has emitted nothing for a while is
    finished whether or not it says so;
  * any single attempt running long, which is capped outright.

State is written after every step, so progress can be read at a glance instead
of reconstructed from a log.
"""
import json
import re
import sys
import time
from pathlib import Path

MAA = Path(r"D:\ark\maa")
COP = MAA / "config" / "copilot"
ADB = r"D:\LD-MRFZ\LDPlayer9\adb.exe"
ADDRESS = "127.0.0.1:7555"
TOUCH = "minitouch"

QUIET_LIMIT = 180        # no callback for this long -> the attempt is dead
ATTEMPT_LIMIT = 12 * 60  # hard cap on one stage attempt
REPEAT_LIMIT = 30        # same subtask this many times in a row -> going nowhere

sys.path.insert(0, str(MAA / "Python"))
from asst.asst import Asst                              # noqa: E402
from asst.utils import InstanceOptionType, Message      # noqa: E402

LOG = Path(sys.argv[1])
STATE = LOG.with_suffix(".state.json")
STAGES = sys.argv[2:]

state = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "stages": {}, "note": ""}
last_event = [time.time()]
seen = {"stars3": False, "failed": False, "missing": [], "unsupported": False,
        "last_task": "", "repeat": 0, "looping": False}


def say(line: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {line}\n")


def save() -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


@Asst.CallBackType
def callback(msg, details, arg):
    last_event[0] = time.time()
    try:
        m = Message(msg)
        d = json.loads(details.decode("utf-8"))
    except Exception:                       # noqa: BLE001
        return
    txt = json.dumps(d, ensure_ascii=False)
    if m is Message.SubTaskStart:
        name = (d.get("details") or {}).get("task", "")
        if "StageDrops-Stars-3" in name:
            seen["stars3"] = True
            say("  >>> 三星通关")
        elif name:
            # Detect a busy loop, not just silence. A navigation that cannot
            # find its stage keeps emitting callbacks forever, so a quiet-timer
            # never fires - it swiped 224 times before a human noticed.
            if name == seen["last_task"]:
                seen["repeat"] += 1
            else:
                seen["last_task"] = name
                seen["repeat"] = 1
            if seen["repeat"] == REPEAT_LIMIT:
                say(f"  !! 「{name}」连续重复 {REPEAT_LIMIT} 次，判定原地打转")
                seen["looping"] = True
            if seen["repeat"] <= 3 or seen["repeat"] % 20 == 0:
                say(f"  · {name}" + (f" x{seen['repeat']}" if seen["repeat"] > 1 else ""))
        return
    if m in (Message.SubTaskError, Message.TaskChainError):
        for who in re.findall(r'"name":\s*"([^"]+)",\s*"reason":\s*"Missing"', txt):
            if who not in seen["missing"]:
                seen["missing"].append(who)
        if m is Message.TaskChainError:
            seen["failed"] = True
        say(f"  !! {m.name}: {txt[:300]}")
        return
    if m is Message.TaskChainCompleted:
        say("  链路完成")
        return
    if "UnsupportedLevel" in txt:
        seen["unsupported"] = True
        say(f"  !! 关卡不支持: {txt[:200]}")


def adb(*args) -> None:
    import subprocess
    try:
        subprocess.run([ADB, "-s", ADDRESS, *args], capture_output=True, timeout=25)
    except Exception:                        # noqa: BLE001
        pass


# Where the event lives on screen, measured on this 1600x900 device.
EVENT_BANNER = (1452, 190)      # the 墟 banner on the main screen
HUB_MAIN = (1330, 541)          # 不夜街区 on the event hub - AT-1..AT-8
# The EX stages are NOT reachable from the hub at the position below 不夜街区:
# tapping there on 2026-08-23 opened 特典中古市场, the event shop. They are a
# tab on the map itself, bottom right, next to the section name.
MAP_TAB_EX = (1370, 810)        # 锻冶旧迹 tab, once the main map is open


def goto_event_map(section: str = "main") -> None:
    """Nothing to do - MAA's own StartUp task handles this, see attempt()."""
    return


def back_to_neutral() -> None:
    goto_event_map("main")


def attempt(stage: str, job: Path) -> str:
    """Return 'ok' | 'missing' | 'failed' | 'stalled'."""
    seen.update({"stars3": False, "failed": False, "missing": [], "unsupported": False,
                 "last_task": "", "repeat": 0, "looping": False})
    last_event[0] = time.time()
    asst = Asst(callback=callback)
    asst.set_instance_option(InstanceOptionType.touch_type, TOUCH)
    if not asst.connect(ADB, ADDRESS):
        say("  !! 连接失败")
        return "failed"
    # Phase 1: let MAA wake the game. Hand-timed taps on the splash and the
    # login button failed twice tonight; StartUp waits on what it sees.
    asst.append_task("StartUp", {
        "enable": True, "client_type": "Official", "start_game_enabled": True,
    })
    if not asst.start():
        say("  !! StartUp 启动失败")
        return "failed"
    while asst.running():
        time.sleep(2)
        if time.time() - last_event[0] > QUIET_LIMIT:
            asst.stop(); time.sleep(4)
            say("  !! StartUp 卡住")
            return "stalled"
    say("  唤醒完成，进入活动地图")

    # Phase 2: walk to the event map. Copilot navigation is relative to where
    # the game already is: from the main screen it hunts through main-story
    # chapters and never finds an event stage. From the event map it finds it.
    # These three taps are only safe because StartUp guarantees the screen they
    # start from - the earlier BACK-based version guessed, and twice landed in
    # the event shop.
    adb("shell", "input", "tap", str(EVENT_BANNER[0]), str(EVENT_BANNER[1]))
    time.sleep(10)
    adb("shell", "input", "tap", str(HUB_MAIN[0]), str(HUB_MAIN[1]))
    time.sleep(9)
    if "EX" in stage:
        adb("shell", "input", "tap", str(MAP_TAB_EX[0]), str(MAP_TAB_EX[1]))
        time.sleep(8)
    last_event[0] = time.time()

    # Phase 3: the copilot itself.
    asst.append_task("Copilot", {
        "enable": True,
        # A one-entry copilot_list, not "filename". Single-copilot mode does no
        # navigation at all - it expects the game to be sitting on the
        # formation screen with 开始行动 already showing, and errors out on
        # BattleStartAll from anywhere else. The list form navigates to the
        # stage itself, which is the only workable shape when nobody is there
        # to put the game on the right screen first.
        "copilot_list": [{"filename": str(job), "is_raid": False}],
        "formation": True,
        "formation_index": 0,
        "use_sanity_potion": False,
        "add_trust": False,
        # Jobs declare 练度要求 (skill level, elite, module...) per operator, and
        # MAA enforces them: an operator whose skill is not specialised enough
        # comes back as reason "Unavailable" and the whole formation aborts.
        # Measured 2026-08-23: three operators the account owns were rejected on
        # skill_level alone, and the same job formed up and fought with this on.
        # The requirement is the job author's preference, not a hard constraint.
        "ignore_requirements": True,
        # 1 = borrow a support unit only when exactly one operator is missing.
        # Costs nothing when the roster is complete and saves a whole swap when
        # it is not.
        "support_unit_usage": 1,
    })
    if not asst.start():
        say("  !! start 失败")
        return "failed"
    began = time.time()
    while asst.running():
        time.sleep(2)
        if time.time() - last_event[0] > QUIET_LIMIT:
            say(f"  !! {QUIET_LIMIT}s 没有任何回调，判定卡死，中止本次")
            asst.stop(); time.sleep(5)
            return "stalled"
        if seen["looping"]:
            asst.stop(); time.sleep(5)
            return "stalled"
        if time.time() - began > ATTEMPT_LIMIT:
            say("  !! 单次超时，中止本次")
            asst.stop(); time.sleep(5)
            return "stalled"
    if seen["stars3"]:
        return "ok"
    if seen["missing"]:
        return "missing"
    return "failed"


def main() -> int:
    index = json.loads((COP / "index.json").read_text(encoding="utf-8"))
    say(f"=== 开始，关卡: {', '.join(STAGES)} ===")
    if not Asst.load(path=MAA):
        say("!! 资源加载失败"); return 1

    for stage in STAGES:
        cands = index.get(stage, [])
        state["stages"][stage] = {"result": "进行中", "tried": []}
        save()
        done = False
        for c in cands:
            job = COP / f"{stage}__{c['id']}.json"
            if not job.is_file():
                continue
            say(f"[{stage}] 作业 {c['id']}  干员={c['opers'] or c['groups']}")
            goto_event_map("ex" if "EX" in stage else "main")
            r = attempt(stage, job)
            state["stages"][stage]["tried"].append(
                {"id": c["id"], "result": r, "missing": list(seen["missing"])})
            save()
            say(f"[{stage}] 作业 {c['id']} -> {r}"
                + (f"（缺 {'、'.join(seen['missing'])}）" if seen["missing"] else ""))
            if r == "ok":
                state["stages"][stage]["result"] = "通关"
                done = True
                save()
                break
            back_to_neutral()
        if not done:
            state["stages"][stage]["result"] = "全部候选失败"
            save()
            say(f"[{stage}] !! 五份作业都没成，跳过")
    state["note"] = "全部关卡处理完毕"
    state["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save()
    say("=== 全部结束 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
