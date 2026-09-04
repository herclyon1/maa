"""把明日方舟那台雷电实例拉起来，并确认 adb 连得上。

为什么需要这个脚本：这台机器上有**两个**雷电实例。

    0     雷电模拟器        adb 端口 5555
    1000  雷电模拟器-1000   adb 端口 7555   ← 明日方舟装在这个里面

雷电的规则是 `adb 端口 = 5555 + index * 2`，所以 1000 号实例落在 7555，
正是 AUTO-MAS 和 scripts/mac/adbdo.sh 一直用的那个地址。

2026-09-04 踩过一次：直接双击 `dnplayer.exe` 起的是 **0 号**实例，
它里面没装方舟，7555 也不会有人听——表现是 MaaCore 一直报
`ConnectFailed / Connection command did not report "connected"`，
看着像 adb 坏了，其实是**开错了实例**。要指定实例只能走 ldconsole：

    ldconsole.exe launch --index 1000

用法：  emu-start.py [--index 1000]
"""
import subprocess
import sys
import time

LD = r"D:\LD-MRFZ\LDPlayer9"
CONSOLE = LD + r"\ldconsole.exe"
ADB = LD + r"\adb.exe"

index = 1000
if "--index" in sys.argv:
    index = int(sys.argv[sys.argv.index("--index") + 1])
port = 5555 + index * 2
addr = f"127.0.0.1:{port}"


def run(*args, **kw):
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60, **kw)


def adb_ok() -> bool:
    run(ADB, "connect", addr)
    out = run(ADB, "-s", addr, "shell", "getprop", "sys.boot_completed").stdout
    return out.strip() == "1"


print(f"目标实例 index={index}，adb {addr}", flush=True)

if adb_ok():
    print("实例已经在跑，adb 也通了", flush=True)
else:
    print("拉起实例…", flush=True)
    run(CONSOLE, "launch", "--index", str(index))
    for i in range(1, 41):          # 最多等 200 秒
        time.sleep(5)
        if adb_ok():
            print(f"起来了，等了约 {i * 5} 秒", flush=True)
            break
        if i % 4 == 0:
            print(f"… 还在开机（{i * 5} 秒）", flush=True)
    else:
        print("!! 等了 200 秒还没开机完成", flush=True)
        raise SystemExit(1)

pkgs = run(ADB, "-s", addr, "shell", "pm", "list", "packages").stdout
ark = [l for l in pkgs.splitlines() if "hypergryph" in l or "arknights" in l.lower()]
print("方舟包：", ark or "!! 这个实例里没有明日方舟", flush=True)
top = run(ADB, "-s", addr, "shell", "dumpsys", "window").stdout
for line in top.splitlines():
    if "mCurrentFocus" in line:
        print("当前前台：", line.strip(), flush=True)
        break
raise SystemExit(0 if ark else 2)
