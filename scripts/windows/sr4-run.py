"""在游戏机本地打完月行水上 SR-4：自己盯剧情、自己部署。

为什么要整个搬到游戏机上跑：这一关**战斗中会反复弹关内对话**（每来一辆
告解车播一次），而部署必须在没有对话遮挡的那几秒里完成。从 Mac 这头一步步
遥控做不到——每发一条命令要跨境一趟 ssh，往返就两三秒，等看到剧情、点掉、
再发部署，时机早过了。放在本地循环，一次检测到一次处理，延迟以毫秒计。

MAA 打不了这一关：它进入 `Copilot@WaitUntilEndOfAction` 之后，剧情一挡就
再也不会恢复，固定 58 秒后抛 TaskChainError（三种时序都试过，pre_delay 无效）。
所以部署由这个脚本用 MaaTouch 自己做，坐标由 scripts/mac/lib/tilepos.py
按 MAA 的算法从关卡格子表算出来。

用法：sr4-run.py <日志路径>
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ADB = r"D:\LD-MRFZ\LDPlayer9\adb.exe"
DEV = "127.0.0.1:7555"
TOUCH_SRC = r"D:\ark\maa\resource\minitouch\maatouch\minitouch"
TOUCH_DST = "/data/local/tmp/maatouch"
SHOT = "/sdcard/sr4.png"
LOCAL_SHOT = r"C:\ProgramData\sr4-shot.png"

LOG = Path(sys.argv[1])


def say(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def adb(*args, timeout=60):
    return subprocess.run([ADB, "-s", DEV, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def tap(x, y):
    adb("shell", "input", "tap", str(x), str(y))


class Frame:
    """一帧原始像素。游戏机上没有 PIL，所以用 screencap 的**原始格式**
    （不加 -p）：头部是 width/height/format 三个小端 int32（Android 8+ 还多
    一个 colorspace），后面是逐像素 RGBA。纯标准库就能取像素。"""

    def __init__(self, raw):
        w = int.from_bytes(raw[0:4], "little")
        h = int.from_bytes(raw[4:8], "little")
        for head in (12, 16):                 # 有没有 colorspace 字段，按长度反推
            if len(raw) - head == w * h * 4:
                break
        else:
            raise ValueError(f"截图格式对不上: {w}x{h}, {len(raw)} 字节")
        self.w, self.h, self.data, self.head = w, h, raw, head

    def getpixel(self, xy):
        x, y = xy
        i = self.head + (y * self.w + x) * 4
        return (self.data[i], self.data[i + 1], self.data[i + 2])


def grab():
    adb("shell", "screencap", SHOT)
    adb("pull", SHOT, LOCAL_SHOT)
    return Frame(Path(LOCAL_SHOT).read_bytes())


def has_choice(im):
    """右侧出现「往左 / 往右」两个横条时，那一片是均匀的深灰。"""
    pts = [(1300, 470), (1450, 470), (1300, 560), (1450, 560)]
    vals = [im.getpixel(p) for p in pts]
    return all(abs(v[0] - v[1]) < 12 and abs(v[1] - v[2]) < 12 and 40 < v[0] < 110
               for v in vals)


def has_dialog(im):
    """底部对话条：左下角有立绘方块 + 底部一条深色横幅。"""
    a = im.getpixel((360, 730))
    b = im.getpixel((900, 720))
    return (sum(a) > 180) and (sum(b) < 210)


def battle_ready(im):
    """右下角费用数字区是亮的，且没有对话/选项 —— 说明能操作了。"""
    return not has_choice(im) and not has_dialog(im)


def clear_plot(max_rounds=14):
    for _ in range(max_rounds):
        im = grab()
        if has_choice(im):
            say("看到选项，选「往左」")
            tap(1350, 470)
            time.sleep(1.2)
            continue
        if has_dialog(im):
            tap(1290, 845)
            time.sleep(0.9)
            continue
        return True
    return False


class Touch:
    """MaaTouch 的一个会话。节奏用 Python 控制，不用 minitouch 的 w。"""

    def __init__(self):
        adb("push", TOUCH_SRC, TOUCH_DST)
        self.p = subprocess.Popen(
            [ADB, "-s", DEV, "shell",
             f"CLASSPATH={TOUCH_DST} app_process / com.shxyke.MaaTouch.App"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1)
        time.sleep(1.5)

    def _send(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def act(self, kind, x=0, y=0, pause=0.05):
        self._send("u 0" if kind == "u" else f"{kind} 0 {x} {y} 100")
        self._send("c")
        time.sleep(pause)

    def close(self):
        time.sleep(2)
        try:
            self.p.stdin.close()
            self.p.wait(timeout=8)
        except Exception:
            self.p.terminate()


def deploy(card_xy, cell_xy, facing):
    """把干员从卡片放到格子上。

    三个要点，都是 2026-09-04 实测出来的：
    1. 起手要**竖直向上**把干员从卡槽里拉出来，直接斜着拖会被当成滑列表；
    2. 一次连续触摸走完，中途松手再按第二次＝取消部署；
    3. 松手后游戏停在「选朝向」，那一下用普通 adb swipe 补完就行。
    """
    cx, cy = card_xy
    gx, gy = cell_xy
    t = Touch()
    t.act("d", cx, cy, 0.25)
    for i in range(1, 5):
        t.act("m", cx, cy - 30 * i, 0.05)
    lift = cy - 120
    for i in range(1, 13):
        t.act("m", cx + (gx - cx) * i // 12, lift + (gy - lift) * i // 12, 0.05)
    time.sleep(0.6)
    t.act("u", pause=0.6)
    t.close()

    time.sleep(0.8)
    # 高台上的干员显示得比格子中心高约 115px，朝向从那里往外甩
    sx, sy = gx, gy - 115
    dx, dy = {"up": (0, -150), "down": (0, 150),
              "left": (-150, 0), "right": (150, 0)}[facing]
    adb("shell", "input", "swipe", str(sx), str(sy),
        str(sx + dx), str(sy + dy), "500")
    time.sleep(1.0)


def cost(im):
    """右下角费用。读不出来就返回 None。"""
    return None  # 数字 OCR 不做了，改用「卡片还在不在」判断部署是否成功


def card_present(im, x=1500, y=820):
    px = im.getpixel((x, y))
    return sum(px) > 150


def main():
    say("=== SR-4 本地流程开始 ===")
    if not clear_plot():
        say("!! 剧情清不掉"); return 1
    say("战场干净")

    plan = [((1500, 820), (501, 347), "right", "圣聆初雪"),
            ((1500, 820), (1099, 347), "down", "娜仁图亚")]
    for card, cell, facing, who in plan:
        for attempt in range(1, 5):
            im = grab()
            if has_choice(im) or has_dialog(im):
                say("部署前又弹剧情，先清掉")
                clear_plot()
            say(f"部署 {who} → {cell} 朝{facing}（第 {attempt} 次）")
            deploy(card, cell, facing)
            time.sleep(1.0)
            im = grab()
            if not card_present(im):
                say(f"{who} 已就位")
                break
            say(f"{who} 没放上去，重试")
        else:
            say(f"!! {who} 四次都没放上去"); return 1
        time.sleep(2)

    say("两人就位，加速挂机")
    tap(1380, 65)          # 切 2 倍速
    # 之后每隔几秒清一次可能冒出来的剧情，直到战斗结束
    for _ in range(150):
        time.sleep(4)
        im = grab()
        if has_choice(im) or has_dialog(im):
            clear_plot()
    say("=== 结束 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
