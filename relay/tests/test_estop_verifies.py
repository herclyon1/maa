"""The red button on the phone must not say 「已停一切」 unless it checked.

The conclusion of 2026-08-26, in the user's own words, was 「你没有进行任何有效的停止
行为，全是我手动关的」. The phone button kept that shape: stop through the AUTO-MAS
API, run taskkill twice, then return a hard-coded success - no look at what was
actually left, and the message went straight out as a push.

Two things make that worse than doing nothing. AUTO-MAS retries the whole queue when
one of its members is killed under it, so "killed it twice" says nothing about the
state half a minute later; and the process list it did surface never contained
Wuthering Waves' real process names, which is exactly how the 08-26 check passed
while the game was running.

So: verify, retry once, and tell the truth either way.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import commands

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


print("[要杀要查的名单里必须有鸣潮的三个真名——08-26 的假确认就漏在这里]")
for exe in ("Wuthering Waves.exe", "Client-Win64-Shipping.exe", "KRSDKExternal.exe",
            "ok-ww.exe", "MAA.exe", "MaaEnd.exe", "Endfield.exe", "dnplayer.exe"):
    check(f"名单含 {exe}", exe in commands._ESTOP_EXES, True)
print("  ✓ 终末地启动器 Games.exe 也在" if "Games.exe" in commands._ESTOP_EXES else "")
check("终末地启动器也在", "Games.exe" in commands._ESTOP_EXES, True)


class Rig:
    """替掉三个动作：接口停、杀进程、查还活着谁。"""

    def __init__(self, alive_rounds):
        self.alive_rounds = list(alive_rounds)
        self.kills = 0
        self.stops = 0
        self.slept = 0

    def install(self):
        commands._estop_stop_via_mas = lambda: (setattr(self, "stops", self.stops + 1),
                                                ["早班"])[1]
        commands._estop_kill = lambda: setattr(self, "kills", self.kills + 1)
        commands._estop_alive = lambda: (self.alive_rounds.pop(0)
                                         if self.alive_rounds else [])
        return self

    def sleep(self, n):
        self.slept += n


real = (commands._estop_stop_via_mas, commands._estop_kill, commands._estop_alive)

print("\n[一轮就干净：说成功，而且说的是「确认没了」不是「已经杀过了」]")
r = Rig([[]]).install()
ok, msg = commands.estop(sleep=r.sleep)
check("返回成功", ok, True)
check("话里说了确认", "确认没了" in msg, True)
check("只停了一轮接口", r.stops, 1)

print("\n[第一次查还有残留：必须再停一轮，然后才许说成功]")
r = Rig([["MAA.exe"], []]).install()
ok, msg = commands.estop(sleep=r.sleep)
check("返回成功", ok, True)
check("停了两轮接口", r.stops, 2)

print("\n[两轮都停不住：不许说成功，要点名还活着谁，并指到 estop.sh]")
r = Rig([["Client-Win64-Shipping.exe"], ["Client-Win64-Shipping.exe"]]).install()
ok, msg = commands.estop(sleep=r.sleep)
check("返回失败", ok, False)
check("不含「已停一切」", "已停一切" in msg, False)
check("点名了还活着的（用中文说游戏名）", "鸣潮" in msg, True)
check("指到电脑上的紧急停止脚本", "紧急停止" in msg, True)
check("说清为什么中继自己停不住", "整队重试" in msg, True)
check("不许在推送里出现进程名", "Client-Win64-Shipping" in msg, False)

print("\n[进程表读不到时按「还活着」算——不知道不许说成全清]")
r = Rig([["进程表读不到"], ["进程表读不到"]]).install()
ok, msg = commands.estop(sleep=r.sleep)
check("返回失败", ok, False)
check("话里说了读不到", "进程表读不到" in msg, True)

commands._estop_stop_via_mas, commands._estop_kill, commands._estop_alive = real

print("\n[查活着谁：认名字不分大小写，一个不落]")
import subprocess as _sp                                          # noqa: E402
import os as _os                                                  # noqa: E402
real_run, real_name = _sp.run, _os.name
_os.name = "nt"


class Out:
    def __init__(self, text):
        self.stdout = text.encode("utf-8")


_sp.run = lambda *a, **k: Out('"MAA.exe","1","Console"\n"client-win64-shipping.exe","2","C"\n')
check("大小写不同也认得出", set(commands._estop_alive()),
      {"MAA.exe", "Client-Win64-Shipping.exe"})
_sp.run = lambda *a, **k: Out('"explorer.exe","1","Console"\n')
check("干净时是空的", commands._estop_alive(), [])


def _boom(*a, **k):
    raise OSError("tasklist 挂了")


_sp.run = _boom
check("读不到时不许返回空", commands._estop_alive(), ["进程表读不到"])
_sp.run, _os.name = real_run, real_name

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
