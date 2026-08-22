"""Run a MAA copilot battle list through MaaCore directly - no GUI at all.

Why this exists: MAA's window cannot be seen from here. The desktop is only
composited while something is consuming frames (a ToDesk viewer), so with
nobody watching, every screen grab returns the last frame drawn - which is how
MAA's window came back as a blank white rectangle while the process was
perfectly healthy. Clicking a button you cannot see is not an option.

MaaCore is the engine the GUI is a shell around, and MAA ships the official
Python binding next to it. Driving the core directly needs no window, no
coordinates and no screenshots: the task is a JSON document, and progress
arrives as callbacks.

Only one core may own the emulator at a time - close the MAA GUI first.

Usage:  copilot-run.py <log-path> <stage> [<stage> ...]
"""
import ctypes
import json
import sys
import time
from pathlib import Path

MAA = Path(r"D:\Users\Administrator\Desktop\MAA-v5.1.0-win-x64")
ADB = r"D:\LD-MRFZ\LDPlayer9\adb.exe"
ADDRESS = "127.0.0.1:7555"          # what the GUI itself connects to
TOUCH = "minitouch"                  # copilot requires minitouch or maatouch

sys.path.insert(0, str(MAA / "Python"))
from asst.asst import Asst                     # noqa: E402
from asst.utils import InstanceOptionType, Message   # noqa: E402

LOG = Path(sys.argv[1])
STAGES = sys.argv[2:]


def say(line: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {line}\n")
    print(f"[{stamp}] {line}", flush=True)


@Asst.CallBackType
def callback(msg, details, arg):
    try:
        m = Message(msg)
        d = json.loads(details.decode("utf-8"))
    except Exception:                       # noqa: BLE001 - never kill the run
        say(f"callback raw msg={msg}")
        return
    # Keep the noisy per-frame messages out; keep everything that says what
    # happened, so a failed stage is legible afterwards without a screen.
    if m in (Message.SubTaskExtraInfo,):
        what = d.get("what", "")
        if what in ("StageDrops", "CopilotAction", "BattleFormationSelected",
                    "UnsupportedLevel", "CopilotListLoadTaskFileError"):
            say(f"{m.name}/{what}: {json.dumps(d.get('details', {}), ensure_ascii=False)[:400]}")
        return
    if m in (Message.SubTaskStart, Message.SubTaskCompleted):
        name = (d.get("details") or {}).get("task", "")
        if name:
            say(f"{m.name}: {name}")
        return
    say(f"{m.name}: {json.dumps(d, ensure_ascii=False)[:500]}")


def main() -> int:
    say(f"=== copilot 启动，关卡: {', '.join(STAGES)} ===")
    if not Asst.load(path=MAA):
        say("!! 资源加载失败"); return 1
    say("资源已加载")

    asst = Asst(callback=callback)
    if not asst.set_instance_option(InstanceOptionType.touch_type, TOUCH):
        say(f"!! 触控模式设置失败: {TOUCH}"); return 1
    say(f"触控模式 = {TOUCH}")

    if not asst.connect(ADB, ADDRESS):
        say(f"!! 连接失败: {ADDRESS}"); return 1
    say(f"已连接 {ADDRESS}")

    task = {
        "enable": True,
        "copilot_list": [
            {"filename": str(MAA / "config" / "copilot" / f"{s}.json"),
             "is_raid": False}
            for s in STAGES
        ],
        "formation": True,          # 自动编队，按作业需要重建编队
        "formation_index": 0,       # 0 = 当前编队栏位
        "use_sanity_potion": False, # 绝不吃药
        "add_trust": False,
        "ignore_requirements": False,
        "support_unit_usage": 0,    # 不借助战
    }
    tid = asst.append_task("Copilot", task)
    say(f"任务已下发 id={tid}")
    if not asst.start():
        say("!! start 失败"); return 1
    say("已开始运行")

    last = time.time()
    while asst.running():
        time.sleep(2)
        if time.time() - last > 300:
            last = time.time()
            say("… 仍在运行")
    say("=== 运行结束 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
