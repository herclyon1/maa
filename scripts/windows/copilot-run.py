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

Usage:
  copilot-run.py <log-path> startup            # 把游戏开到主界面，什么都不打
  copilot-run.py <log-path> fight <关卡> [次数] # 直接刷关卡（验证 MAA 认不认这个关卡号）
  copilot-run.py <log-path> <stage> [<stage>…] # 按关卡跑作业（本地 JSON）

`startup` 是打活动关的第一步：MAA 自己处理开屏、公告和登录，
把游戏摆到主界面。**不要手动掐时间等开机**，见
docs/MAA-打活动关与保全派驻.md「走通一次活动 EX 的配方」。
"""
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

MAA = Path(r"D:\ark\maa")
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


STARTUP = len(STAGES) == 1 and STAGES[0] == "startup"
FIGHT = len(STAGES) >= 2 and STAGES[0] == "fight"


def main() -> int:
    say("=== StartUp：把游戏开到主界面 ===" if STARTUP
        else f"=== Fight：验证关卡 {STAGES[1]} ===" if FIGHT
        else f"=== copilot 启动，关卡: {', '.join(STAGES)} ===")
    if not Asst.load(path=MAA):
        say("!! 资源加载失败"); return 1
    say("资源已加载")

    asst = Asst(callback=callback)
    if not asst.set_instance_option(InstanceOptionType.touch_type, TOUCH):
        say(f"!! 触控模式设置失败: {TOUCH}"); return 1
    say(f"触控模式 = {TOUCH}")

    # LDPlayer 的 adb 连接会自己掉，掉了之后 MaaCore 直接报 ConnectFailed。
    # connect 是幂等的，白连一次不花钱；模拟器刚起来时 Android 侧还没听端口，
    # 所以要给它几轮重试而不是一次就放弃。
    for attempt in range(1, 11):
        subprocess.run([ADB, "connect", ADDRESS],
                       capture_output=True, timeout=30)
        if asst.connect(ADB, ADDRESS):
            say(f"已连接 {ADDRESS}（第 {attempt} 次）")
            break
        say(f"连接失败，5 秒后重试（{attempt}/10）")
        time.sleep(5)
    else:
        say(f"!! 连不上 {ADDRESS}，模拟器起来了吗？"); return 1

    if FIGHT:
        # 只为验证 MAA 认不认这个关卡号。**药量写死 0**：验证不该顺手吃药。
        stage = STAGES[1]
        times = int(STAGES[2]) if len(STAGES) > 2 else 1
        tid = asst.append_task("Fight", {
            "enable": True, "stage": stage, "medicine": 0,
            "stone": 0, "times": times, "series": 0,
        })
        say(f"Fight 已下发 id={tid} 关卡={stage} 次数={times} 药=0")
        if not tid:
            say("!! append_task 被拒，看 debug/asst.log"); return 1
        if not asst.start():
            say("!! start 失败"); return 1
        last = time.time()
        while asst.running():
            time.sleep(2)
            if time.time() - last > 60:
                last = time.time(); say("… 仍在跑")
        say("=== Fight 结束 ===")
        return 0

    if STARTUP:
        tid = asst.append_task("StartUp", {
            "enable": True,
            "client_type": "Official",
            "start_game_enabled": True,
        })
        say(f"StartUp 已下发 id={tid}")
        if not asst.start():
            say("!! start 失败"); return 1
        last = time.time()
        while asst.running():
            time.sleep(2)
            if time.time() - last > 60:
                last = time.time(); say("… 仍在开游戏")
        say("=== StartUp 结束 ===")
        return 0

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
        # 练度要求是作业作者的偏好，不是游戏的限制。关着的话干员明明有，
        # 也会被判 Unavailable 而凑不齐六人（2026-08-23 三个干员全栽在这）。
        "ignore_requirements": True,
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
