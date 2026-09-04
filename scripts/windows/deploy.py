"""用 MaaTouch 在明日方舟里部署干员——adb 自己做不到的那一步。

为什么需要它：部署是「按住干员卡 → 拖到格子 → 松开 → 再朝一个方向甩 → 松开」。
`adb shell input swipe` 只能画一条匀速直线，游戏根本不认；
`input motionevent` 要 Android 11+，这台雷电是 Android 9，没有。
能做出真实触摸时序的只有 minitouch / MaaTouch —— MAA 自己用的也是它，
就放在 `D:\ark\maa\resource\minitouch\maatouch\minitouch`。

MaaTouch 是个 dex，用 app_process 跑起来之后从 stdin 读 minitouch 协议：

    d <触点> <x> <y> <压力>   按下
    m <触点> <x> <y> <压力>   移动
    u <触点>                  抬起
    c                         提交（每组动作后都要）
    w <毫秒>                  等待

用法：
    deploy.py <干员卡x> <干员卡y> <格子x> <格子y> <朝向>
    deploy.py --probe <干员卡x> <干员卡y> <输出.png>   # 按住看高亮，不真的放下
    朝向 = up | down | left | right

坐标直接用截图上的像素（模拟器 1600x900）。
"""
import subprocess
import sys
import time

ADB = r"D:\LD-MRFZ\LDPlayer9\adb.exe"
DEV = "127.0.0.1:7555"
SRC = r"D:\ark\maa\resource\minitouch\maatouch\minitouch"
DST = "/data/local/tmp/maatouch"

DIRS = {"up": (0, -140), "down": (0, 140), "left": (-140, 0), "right": (140, 0)}


def adb(*args, **kw):
    return subprocess.run([ADB, "-s", DEV, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=60, **kw)


def probe(send, cx, cy, out_png):
    """按住干员卡不放，游戏会把所有可部署格子高亮出来——趁这时候截一张图。
    比对着背景猜格子坐标可靠得多。"""
    send(f"d 0 {cx} {cy} 100"); send("c"); send("w 150")
    for i in range(1, 9):
        send(f"m 0 {cx + (800 - cx) * i // 8} {cy + (450 - cy) * i // 8} 100")
        send("c"); send("w 50")
    send("w 400")
    time.sleep(1.2)
    adb("shell", "screencap", "-p", "/sdcard/probe.png")
    adb("pull", "/sdcard/probe.png", out_png)
    # 拖回卡片原处再松手 = 取消这次部署，不会真的放下去
    for i in range(1, 9):
        send(f"m 0 {800 + (cx - 800) * i // 8} {450 + (cy - 450) * i // 8} 100")
        send("c"); send("w 50")
    send("u 0"); send("c")
    print("高亮图已存到", out_png, flush=True)


def main() -> int:
    if sys.argv[1] in ("--probe", "--hold"):
        cx, cy = int(sys.argv[2]), int(sys.argv[3])
        out_png = sys.argv[4]
        gx = gy = 0; facing = "up"
    else:
        cx, cy, gx, gy = (int(v) for v in sys.argv[1:5])
        facing = sys.argv[5]
    dx, dy = DIRS[facing]

    adb("connect", DEV)
    out = adb("push", SRC, DST)
    print("push:", out.stdout.strip() or out.stderr.strip(), flush=True)

    proc = subprocess.Popen(
        [ADB, "-s", DEV, "shell",
         f"CLASSPATH={DST} app_process / com.shxyke.MaaTouch.App"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1)
    time.sleep(1.5)

    def send(line: str) -> None:
        proc.stdin.write(line + "\n")
        proc.stdin.flush()

    def touch(kind: str, x: int = 0, y: int = 0, pause: float = 0.05) -> None:
        """一组动作 + 提交 + 真实停顿。节奏由 Python 控制，不用 minitouch 的 w。"""
        send(f"u 0" if kind == "u" else f"{kind} 0 {x} {y} 100")
        send("c")
        time.sleep(pause)

    if sys.argv[1] == "--probe":
        probe(send, cx, cy, out_png)
        time.sleep(2)
        proc.stdin.close()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.terminate()
        return 0

    if sys.argv[1] == "--hold":
        # 按住不放 → 截图 → 等指令文件 → 移过去松手。
        # 分两次调用不行：**按住干员卡的瞬间画面会平移**（左边弹出干员详情），
        # 静态截图上的格子坐标在拖拽状态下是错的。所以必须一次按住走完。
        touch("d", cx, cy, 0.30)
        for i in range(1, 13):
            touch("m", cx + (800 - cx) * i // 12, cy + (450 - cy) * i // 12, 0.06)
        time.sleep(1.0)
        adb("shell", "screencap", "-p", "/sdcard/hold.png")
        adb("pull", "/sdcard/hold.png", out_png)
        print("HOLD_SHOT_READY", out_png, flush=True)

        import os
        target = r"C:\ProgramData\deploy-target.txt"
        if os.path.exists(target):
            os.remove(target)
        for _ in range(120):          # 最多等 120 秒
            if os.path.exists(target):
                break
            time.sleep(1)
        else:
            send("u 0"); send("c")
            print("等不到目标坐标，已取消", flush=True)
            proc.stdin.close(); time.sleep(1); proc.terminate()
            return 1

        with open(target, encoding="utf-8") as fh:
            tx, ty, facing = fh.read().split()
        tx, ty = int(tx), int(ty)
        ddx, ddy = DIRS[facing]
        for i in range(1, 13):
            touch("m", 800 + (tx - 800) * i // 12, 450 + (ty - 450) * i // 12, 0.06)
        time.sleep(0.5)
        touch("u", pause=1.0)          # 松手 → 进入选朝向
        touch("d", tx, ty, 0.30)
        for i in range(1, 9):
            touch("m", tx + ddx * i // 8, ty + ddy * i // 8, 0.05)
        time.sleep(0.4)
        touch("u", pause=0.5)
        time.sleep(3)                     # 让 MaaTouch 把队列里的事件真正打完
        proc.stdin.close()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.terminate()
        print(f"已放到 ({tx},{ty}) 朝 {facing}", flush=True)
        return 0

    # **一次连续的触摸走完**，而且第一步要**竖直向上**把干员从卡槽里拉出来。
    # 直接从卡片斜着拖向格子是不行的：起手就滑出了卡片区域，游戏会当成
    # 在滑干员列表，不会进入部署态（2026-09-04 实测，卡一直在手里、费用不扣）。
    # 分两段（拖到格子松手、再按一次选朝向）同样不行，第二次按下＝取消部署。
    touch("d", cx, cy, 0.25)
    for i in range(1, 5):                      # 先竖直拉出 120px
        touch("m", cx, cy - 30 * i, 0.05)
    lift_y = cy - 120
    for i in range(1, 13):                     # 再走向目标格
        touch("m", cx + (gx - cx) * i // 12, lift_y + (gy - lift_y) * i // 12, 0.05)
    time.sleep(0.6)                            # 停在格子上，让落点判定生效
    for i in range(1, 9):                      # 不松手，朝方向甩
        touch("m", gx + dx * i // 8, gy + dy * i // 8, 0.05)
    time.sleep(0.4)
    touch("u", pause=0.6)

    time.sleep(3)
    proc.stdin.close()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.terminate()
    print(f"已发出部署：卡({cx},{cy}) → 格({gx},{gy}) 朝{facing}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
