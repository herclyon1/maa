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
import subprocess
import sys
import time
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
         "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
         "Where-Object { $_.CommandLine -like '*ok-ww*' } | "
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


def stop_all():
    # ① 全部经 API 停——队列和脚本都停，AUTO-MAS 才不会视作异常去重试
    for name, tid in {**qids(), **ids()}.items():
        r = post("/api/dispatch/stop", {"taskId": tid})
        print(f"  API 停「{name}」: {r.get('message', r)}")
    time.sleep(12)
    # ② 还有残留才动刀
    busy, _ = running()
    if busy:
        print("  残留:", busy, "→ taskkill")
        for exe in SCRIPT_EXES:
            subprocess.run(["taskkill", "/IM", exe, "/T", "/F"], capture_output=True)
        for pid in okww_pids():
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        time.sleep(8)
    # ③ 复查有没有被重新拉起——拉起就再停一轮，并且出声
    busy, _ = running()
    if busy:
        print("  ⚠️ 被 AUTO-MAS 重新拉起:", busy, "→ 再停一轮")
        for name, tid in {**qids(), **ids()}.items():
            post("/api/dispatch/stop", {"taskId": tid})
        time.sleep(8)
        busy, _ = running()
    print("停干净:" if not busy else "❌ 还没停干净:", busy or "是")
    return not busy


def start(name):
    busy = status()
    if busy:
        print(f"❌ 拒绝派发：{busy} 还在跑。先 stop 或等它完——"
              "带病派发就是上午三个游戏同时在线的起点。")
        return
    table = ids()
    if name not in table:
        print(f"❌ 没有叫「{name}」的脚本。有：{'、'.join(table)}")
        return
    r = post("/api/dispatch/start", {"taskId": table[name], "mode": "AutoProxy"})
    print(f"派发「{name}」:", r.get("status"), r.get("message", ""))


def start_queue(name):
    print("⚠️ 你在派**整条队列**。队列成员失败时 AUTO-MAS 会整队从头重试，"
          "中途 taskkill 任何成员都会引发连锁——2026-09-01 上午就是这么乱的。")
    busy = status()
    if busy:
        print(f"❌ 拒绝：{busy} 在跑。")
        return
    table = qids()
    if name not in table:
        print(f"❌ 没有叫「{name}」的队列。有：{'、'.join(table)}")
        return
    r = post("/api/dispatch/start", {"taskId": table[name], "mode": "AutoProxy"})
    print(f"派发队列「{name}」:", r.get("status"), r.get("message", ""))


if __name__ == "__main__":
    a = sys.argv[1:] or ["status"]
    if a[0] == "status":
        status()
    elif a[0] == "start" and len(a) > 1:
        start(a[1])
    elif a[0] == "start-queue" and len(a) > 1:
        start_queue(a[1])
    elif a[0] == "stop":
        stop_all()
    else:
        print(__doc__)
