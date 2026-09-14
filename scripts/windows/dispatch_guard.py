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
import urllib.error
import urllib.request

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
    what /api/dispatch/stop wants - a dispatch id, not a script or queue id."""
    try:
        d = json.loads(urllib.request.urlopen(API + "/api/dispatch/runtime-snapshot",
                                              timeout=10).read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return []
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
    live = live_tasks()
    if not live:
        print("  AUTO-MAS 没有在跑的任务")
    for tid, label in live:
        r = post("/api/dispatch/stop", {"taskId": tid})
        print(f"  API 停「{label}」({tid[:8]}): {r.get('message', r)}")
    return bool(live)


def stop_all():
    # ① 全部经 API 停——AUTO-MAS 才不会视作异常去重试
    _api_stop()
    time.sleep(12)
    if live_tasks():
        print("  ⚠️ API 停了 12 秒后 AUTO-MAS 还说在跑，再停一次")
        _api_stop()
        time.sleep(8)
    # ② 还有残留才动刀。A game left open counts as residue: the relay's
    # _scripts_running() sees Endfield.exe and holds every retry and the
    # shutdown, so 「停干净」 with the game still up (2026-09-12 02:17) was a lie.
    busy, games = running()
    if busy or games:
        print("  残留:", busy + games, "→ taskkill")
        for exe in SCRIPT_EXES + GAME_EXES:
            subprocess.run(["taskkill", "/IM", exe, "/T", "/F"], capture_output=True)
        for pid in okww_pids():
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        time.sleep(8)
    # ③ 复查有没有被重新拉起——拉起就再停一轮，并且出声
    busy, games = running()
    if busy:
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
    try:
        with open(TEST_WINDOWS, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def _save_windows(w):
    os.makedirs(os.path.dirname(TEST_WINDOWS), exist_ok=True)
    tmp = TEST_WINDOWS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(w, fh, ensure_ascii=False)
    os.replace(tmp, TEST_WINDOWS)


def _now_iso():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def test_on(what):
    w = _windows()
    if w and w[-1].get("until") is None:
        print(f"  测试窗口已经开着（{w[-1]['since']} 起），这趟算在里面")
        return
    w.append({"since": _now_iso(), "until": None, "what": what})
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
    return 0


def test_status() -> int:
    w = _windows()
    if w and w[-1].get("until") is None:
        print(f"  ⚠️ 测试窗口开着：{w[-1]['since']} 起（{w[-1].get('what', '')}）——这期间的记录不进日报正文")
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
        test_on(name)
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
