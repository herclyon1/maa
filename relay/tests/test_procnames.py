"""Every "is anything running" list has to be able to see the same things.

There were five of them and no two agreed. Three could not see Wuthering Waves'
own process or the emulator, and one was still looking for MuMuPlayer, gone from
this machine since 2026-08-24. A blind list does not raise an error - it answers
"nothing is running", which is the answer that gets acted on: the phone page reads
idle while the game is playing, and a script gets dispatched on top of a running
one. Two false alarms on 2026-09-07 came from this same blindness.

This does not merge the five (they live in bash, python, and on two machines); it
pins them to one list so a name can never again be added to only some of them.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import config as C

ROOT = Path(__file__).resolve().parents[2]
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


def text(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


print("[名单本身：三个游戏、模拟器、三个脚本，一个都不能少]")
for name in ("Endfield.exe", "Client-Win64-Shipping.exe", "dnplayer.exe",
             "MAA.exe", "MaaEnd.exe", "ok-ww.exe"):
    check(f"名单里有 {name}", name in C.BUSY_PROCS, True)
check("OK-WW 真身按命令行认", (C.OKWW_CMDLINE, "pythonw.exe" in C.PYTHON_HOSTS),
      ("ok-ww", True))

print("\n[已经从这台机器上删掉的东西，不许还留在任何一份名单里]")
# Only a quoted occurrence counts, i.e. the name actually being matched on.
# Mentioning it in prose is allowed and useful: saying why it was removed beats
# erasing every trace of it.
for rel in ("relay/ark_relay/config.py", "scripts/mac/lib/queue_events.py",
            "scripts/mac/watch-run.sh", "scripts/mac/estop.sh"):
    body = text(rel)
    check(f"{rel} 不再拿 MuMuPlayer 当判据",
          ('"MuMuPlayer' in body or "'MuMuPlayer" in body), False)

print("\n[各处的名单都看得见鸣潮本体和模拟器——看不见就等于报「闲着」]")
must = ("Client-Win64-Shipping", "dnplayer")
for rel in ("scripts/mac/lib/queue_events.py", "scripts/mac/watch-run.sh"):
    body = text(rel)
    for m in must:
        check(f"{rel} 认得 {m}", m in body, True)

est = text("scripts/mac/estop.sh")
check("急停脚本认得雷电", "dnplayer" in est, True)
check("急停脚本按命令行找 OK-WW 真身", "ok-ww" in est and "CommandLine" in est, True)

print("\n[手机页那份进程表由同一个名单生成]")
snap = text("relay/ark_relay/snapshot.py")
check("snapshot 用的是 config 里那一份", "BUSY_PROCS" in snap, True)
check("snapshot 不再自己写死名字",
      re.search(r'for n in \("AUTO-MAS", "MAA"', snap) is None, True)

print("\n[派发闸门那份也得看得见鸣潮和模拟器]")
dg = text("scripts/windows/dispatch_guard.py")
check("派发闸门认得鸣潮本体", "Client-Win64-Shipping.exe" in dg, True)
check("派发闸门认得雷电", "dnplayer.exe" in dg, True)
check("派发闸门按命令行找 OK-WW", "pythonw.exe" in dg, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
