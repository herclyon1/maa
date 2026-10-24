"""派发闸门——手动跑任务的唯一入口。杜绝 2026-09-01 上午那种乱象。

那天的连锁：我派了**整条队列** → 队列成员被 taskkill → AUTO-MAS 判失败
**整队从头重试** → 我再手动派发 → 两个指挥官打架 → MAA 重复吃药、
三个游戏同时在线、用户被迫拔电重启。

三条铁规，全部由这个工具强制：
1. 只派单脚本。派队列必须显式 --queue，且会打印整队重试的警告。
2. 派发前查忙闲：有任何脚本/游戏在跑就拒绝派发，先 stop 或等完。
3. stop 走正确顺序：先 API 停（队列+脚本都停）→ 等收干净 → 还有残留
   才 taskkill → 最后**复查有没有被 AUTO-MAS 重新拉起**，拉起就再停一轮。
   （直接 taskkill 正是连锁的导火索。）

用法（经 winrun --py 在游戏机上跑）：
    dispatch_guard.py status
    dispatch_guard.py start MAA|MaaEnd|OK-WW
    dispatch_guard.py start-queue 早班        # 明知故犯才用
    dispatch_guard.py stop                      # 停干净所有
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.error
import urllib.request

# winrun.sh --py ships scripts/mac/lib/relay_code.py next to this script (an import
# at column 0); it finds the installed relay's code for the debug-mode switch below.
# Run from the repo (tests), it is found in scripts/mac/lib.
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mac", "lib"))
import relay_code

API = "http://127.0.0.1:36163"
PWSH = r"C:\Program Files\PowerShell\7\pwsh.exe"
# 游戏进程留给 AUTO-MAS/脚本自己关；这里只认「脚本在不在跑」
SCRIPT_EXES = ("MAA.exe", "MaaEnd.exe")
GAME_EXES = ("dnplayer.exe", "Client-Win64-Shipping.exe", "Endfield.exe")


def post(path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, "msg": e.read().decode()[:120]}


def okww_pids():
    out = subprocess.run(
        [PWSH, "-NoProfile", "-Command",
         # Both hosts: AUTO-MAS runs OK-WW under pythonw.exe, okww-task.sh under
         # python.exe. Watching only the first left the manual path invisible
         # to this gate and to the red button alike.
         #
         # Match the install path, not a bare 「ok-ww」. PowerShell's -like is
         # case-insensitive, so 「*ok-ww*」 also matched this very script's own
         # command line whenever it was called as `run-one.sh OK-WW` - the gate saw
         # itself, reported 「ok-ww 还在跑」 and refused every manual dispatch, while
         # `run-one.sh status` (no such argument) said the machine was idle.
         # A path fragment cannot appear in an argument: it carries separators.
         "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | "
         r"Where-Object { $_.CommandLine -like '*\ok-ww\*' } | "
         "Select-Object -ExpandProperty ProcessId"],
        capture_output=True, text=True, errors="replace").stdout.split()
    return out


def running():
    tl = subprocess.run(["tasklist"], capture_output=True, text=True,
                        errors="replace").stdout
    busy = [e[:-4] for e in SCRIPT_EXES if e in tl]
    if okww_pids():
        busy.append("ok-ww")
    games = [e[:-4] for e in GAME_EXES if e in tl]
    return busy, games


def ids():
    sc = post("/api/scripts/get")["data"]
    return {(v.get("Info") or {}).get("Name", ""): sid for sid, v in sc.items()}


def qids():
    qs = post("/api/queue/get")["data"]
    return {(q.get("Info") or {}).get("Name", ""): qid for qid, q in qs.items()}


def status():
    busy, games = running()
    print("脚本在跑:", busy or "无", "｜游戏在跑:", games or "无")
    return busy


def live_tasks():
    """AUTO-MAS's running dispatch tasks: [(taskId, label)]. The taskId here is
    what /api/dispatch/stop wants - a dispatch id, not a script or queue id.

    None when AUTO-MAS cannot be asked (unreachable, timed out, not JSON). That
    is not [] = "nothing running": until 2026-10-10 it was, and stop went
    straight to taskkill on an unknown state."""
    try:
        d = json.loads(urllib.request.urlopen(API + "/api/dispatch/runtime-snapshot",
                                              timeout=10).read().decode())
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"  ❌ 问不到 AUTO-MAS 在跑什么（{e}）")
        return None
    out = []
    for t in d.get("tasks") or []:
        names = [i.get("name", "") for i in (t.get("task_info") or [])]
        out.append((t.get("taskId", ""), "、".join(names) or t.get("mode", "?")))
    return out


def _api_stop():
    # 2026-09-14: this used to post the *script* and *queue* ids. AUTO-MAS answered
    # 操作成功 to every one of them and stopped nothing; the taskkill that followed
    # then read as a crashed attempt and AUTO-MAS retried the script - twice in a
    # row, the same chain as 2026-09-01. The running task's own id is the one to send.
    # Returns False when AUTO-MAS could not be asked, True otherwise.
    live = live_tasks()
    if live is None:
        return False
    if not live:
        print("  AUTO-MAS 没有在跑的任务")
    for tid, label in live:
        r = post("/api/dispatch/stop", {"taskId": tid})
        print(f"  API 停「{label}」({tid[:8]}): {r.get('message', r)}")
    return True


def stop_all():
    # ① 全部经 API 停——AUTO-MAS 才不会视作异常去重试
    api_ok = _api_stop()
    if api_ok:
        time.sleep(12)
        again = live_tasks()
        if again is None:
            api_ok = False
        elif again:
            print("  ⚠️ API 停了 12 秒后 AUTO-MAS 还说在跑，再停一次")
            api_ok = _api_stop()
            time.sleep(8)
    # ② 还有残留才动刀。A game left open counts as residue: the relay's
    # _scripts_running() sees Endfield.exe and holds every retry and the
    # shutdown, so 「停干净」 with the game still up (2026-09-12 02:17) was a lie.
    busy, games = running()
    if (busy or games) and not api_ok:
        # Without AUTO-MAS's answer a kill may hit a task it is still running, which it
        # reads as a crash and retries: the 2026-09-01 chain. Refuse and say so.
        print("  残留:", busy + games, "→ 问不到 AUTO-MAS，不 taskkill：直接杀会被它当成崩溃、"
              "整队重试（2026-09-01 那条连锁）。等 AUTO-MAS 接口能连上再 stop")
    elif busy or games:
        print("  残留:", busy + games, "→ taskkill")
        for exe in SCRIPT_EXES + GAME_EXES:
            subprocess.run(["taskkill", "/IM", exe, "/T", "/F"], capture_output=True)
        for pid in okww_pids():
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        time.sleep(8)
    # ③ 复查有没有被重新拉起——拉起就再停一轮，并且出声
    busy, games = running()
    if busy and api_ok:
        print("  ⚠️ 被 AUTO-MAS 重新拉起:", busy, "→ 再停一轮")
        _api_stop()
        time.sleep(8)
        busy, games = running()
    left = busy + games
    print("停干净:" if not left else "❌ 还没停干净:", left or "是")
    return not left


# A test dispatch is marked as such, on purpose, by the person dispatching it -
# never inferred. Everything not inside a marked window is real work (a rerun
# after a game update, a run started from the phone) and belongs in the daily
# report as a normal row. The user, 2026-09-14: 「手动趟不进日报的话，如果有一天版本
# 更新了，必须要手动重跑一次，你不进日报怎么办？」
TEST_WINDOWS = r"C:\ProgramData\ark-relay\state\test-windows.json"


def _windows():
    # Only a missing file means "no window ever opened". An unreadable or corrupt one
    # must not read as "closed" (test-status would say 没开) or be overwritten by
    # test_on, which would erase the window history.
    try:
        with open(TEST_WINDOWS, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        print(f"  ❌ 读不了测试窗口记录 {TEST_WINDOWS}（{e}）——不当成「没开」，也不覆盖它；先看一眼这个文件")
        raise SystemExit(5) from e


def _save_windows(w):
    os.makedirs(os.path.dirname(TEST_WINDOWS), exist_ok=True)
    tmp = TEST_WINDOWS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(w, fh, ensure_ascii=False)
    os.replace(tmp, TEST_WINDOWS)


def _now_iso():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


# The relay's state folder: debug mode lives in its state.json (modes.debug_until).
STATE_DIR = os.path.dirname(TEST_WINDOWS)


def _modes():
    """The installed relay's modes module (relay_code picks the code the relay runs).

    A test run is maintenance: the house rule is 「临时跑不改排班；维护先开调试模式」.
    2026-10-13 11:05 a `run-one.sh OK-WW --test` ran after the morning shift had spent
    the one-shot 「下次跑完不关机」 mark, and at 11:13:55 the relay powered the machine
    off (「本轮已处理完毕，60 秒后关机」) - a powered-off machine cannot be started
    remotely. So the test dispatch turns debug mode on itself, before dispatching."""
    relay_code.use_relay_code()
    from ark_relay.features.modes import modes  # noqa: PLC0415 - the machine's relay code
    return modes


def _debug_for_test():
    """Debug mode on before a test dispatch: (ok, debug_until this window wrote or '', line)."""
    try:
        m = _modes()
        sd = Path(STATE_DIR)
        if m.debug_active(sd):
            return True, "", f"  调试模式本来就开着（到 {m.debug_until(sd)}），这趟测试不动它，test-off 也不关它"
        ok, msg = m.set_debug(sd, 1)
        until = m.debug_until(sd)
        if not ok or not m.debug_active(sd):
            return False, "", f"写了但读回来不是开着（{msg}；debug_until={until!r}）"
        return True, until, f"  {msg}（测试窗口开的，test-off 时关）"
    except Exception as e:  # noqa: BLE001 - any failure refuses the dispatch below
        return False, "", f"{type(e).__name__}: {e}"


def test_on(what, debug_set=""):
    w = _windows()
    if w and w[-1].get("until") is None:
        if debug_set:
            w[-1]["debug_set"] = debug_set
            _save_windows(w)
        print(f"  测试窗口已经开着（{w[-1]['since']} 起），这趟算在里面")
        return
    entry = {"since": _now_iso(), "until": None, "what": what}
    if debug_set:
        # This window turned debug mode on (the debug_until it wrote): test-off turns
        # it off again, and only while that is still the value.
        entry["debug_set"] = debug_set
    w.append(entry)
    _save_windows(w)
    print(f"  测试窗口已开（{w[-1]['since']}）——这之后落盘的记录日报只记一句，不成行。跑完记得 run-one.sh test-off")


def test_off() -> int:
    w = _windows()
    if not w or w[-1].get("until") is not None:
        print("  没有开着的测试窗口")
        return 0
    w[-1]["until"] = _now_iso()
    _save_windows(w)
    print(f"  测试窗口已关（{w[-1]['since']} → {w[-1]['until']}）")
    mine = w[-1].get("debug_set")
    if not mine:
        print("  调试模式不是这个测试窗口开的，不动它")
        return 0
    try:
        m = _modes()
        sd = Path(STATE_DIR)
        now = m.debug_until(sd)
        if now != mine:
            # Someone changed it during the window (turned it off, or extended it from
            # the phone): theirs now, left alone.
            print(f"  调试模式测试期间被改过（现在是 {now or '关着'}，测试开的是 {mine}），不动它")
            return 0
        ok, msg = m.set_debug(sd, off=True)
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {e}"
    if not ok:
        print(f"  ❌ 调试模式没关掉（{msg}）——机器跑完不会关机，手机页或 order.sh 关调试模式")
        return 7
    print(f"  测试窗口开的调试模式已关：{msg}")
    return 0


def test_status() -> int:
    w = _windows()
    if w and w[-1].get("until") is None:
        mine = w[-1].get("debug_set")
        debug = (f"调试模式是这个窗口开的（到 {mine}），test-off 时关" if mine
                 else "调试模式不是这个窗口开的")
        print(f"  ⚠️ 测试窗口开着：{w[-1]['since']} 起（{w[-1].get('what', '')}）——这期间的记录不进日报正文；{debug}")
        return 1
    print("  测试窗口：没开")
    return 0


def start(name, test=False) -> int:
    """派发一个脚本。返回退出码：0 成功，非 0 被拒。

    **拒绝必须是非零退出。** 2026-09-08 之前这里只 print 一行 ❌ 然后 return，
    退出码还是 0——调用方（run-one.sh、以及以后任何自动化）分辨不出「拒绝了」
    和「派发成功了」，闸门等于只对人生效。
    """
    busy = status()
    if busy:
        print(f"❌ 拒绝派发：{busy} 还在跑。先 stop 或等它完——"
              "带病派发就是上午三个游戏同时在线的起点。")
        return 2
    table = ids()
    if name not in table:
        print(f"❌ 没有叫「{name}」的脚本。有：{'、'.join(table)}")
        return 3
    if test:
        # Read the window file first: a corrupt one exits here (SystemExit 5). Read
        # after debug mode was switched on, it left debug on with no window holding
        # debug_set, so test-off never turned it off again.
        _windows()
        ok, debug_set, line = _debug_for_test()
        if not ok:
            print(f"❌ 拒绝测试派发：调试模式开不了（{line}）。不开它，跑完中继会照常关机，"
                  "关了的机器远程开不回来")
            return 6
        print(line)
        test_on(name, debug_set)
    r = post("/api/dispatch/start", {"taskId": table[name], "mode": "AutoProxy"})
    print(f"派发「{name}」:", r.get("status"), r.get("message", ""))
    return 0 if str(r.get("status", "")).lower() == "success" else 4


def start_queue(name) -> int:
    print("⚠️ 你在派**整条队列**。队列成员失败时 AUTO-MAS 会整队从头重试，"
          "中途 taskkill 任何成员都会引发连锁——2026-09-01 上午就是这么乱的。")
    busy = status()
    if busy:
        print(f"❌ 拒绝：{busy} 在跑。")
        return 2
    table = qids()
    if name not in table:
        print(f"❌ 没有叫「{name}」的队列。有：{'、'.join(table)}")
        return 3
    r = post("/api/dispatch/start", {"taskId": table[name], "mode": "AutoProxy"})
    print(f"派发队列「{name}」:", r.get("status"), r.get("message", ""))
    return 0 if str(r.get("status", "")).lower() == "success" else 4


if __name__ == "__main__":
    a = sys.argv[1:] or ["status"]
    if a[0] == "status":
        status()
    elif a[0] == "idle":
        # Exit 0 only when no script and no game runs: run-one.sh wait-idle loops on the
        # exit code, not on the wording of the status line (2026-10-24 a hand-written wait
        # grepped 「脚本在跑: []」 while the line says 「脚本在跑: 无」 and waited past the end).
        sys.exit(0 if not any(running()) else 3)
    elif a[0] == "start" and len(a) > 1:
        sys.exit(start(a[1], test="--test" in a[2:]))
    elif a[0] == "test-off":
        sys.exit(test_off())
    elif a[0] == "test-status":
        sys.exit(test_status())
    elif a[0] == "start-queue" and len(a) > 1:
        sys.exit(start_queue(a[1]) or 0)
    elif a[0] == "stop":
        # Failing to stop cleanly has to exit non-zero, for the same reason start
        # does: on 2026-09-08 start got its exit code and stop was overlooked, so
        # 「停干净了」 and 「AUTO-MAS 又把它拉起来了」 reached the caller as the
        # same 0 - and that is the one answer run-one.sh acts on.
        sys.exit(0 if stop_all() else 1)
    else:
        print(__doc__)
        sys.exit(64)
