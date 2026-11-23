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
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.error
import urllib.request

# winrun.sh --py ships scripts/mac/lib/relay_code.py and arklog.py next to this script
# (imports at column 0); relay_code finds the installed relay's code for debug mode.
# Run from the repo (tests), they are found in scripts/mac/lib.
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mac", "lib"))
import arklog
import relay_code

API = "http://127.0.0.1:36163"
PWSH = r"C:\Program Files\PowerShell\7\pwsh.exe"
# 游戏进程留给 AUTO-MAS/脚本自己关；这里只认「脚本在不在跑」
SCRIPT_EXES = ("MAA.exe", "MaaEnd.exe")
GAME_EXES = ("dnplayer.exe", "Client-Win64-Shipping.exe", "Endfield.exe")
TZ_BJ = timezone(timedelta(hours=8))
TZ_AUTOMAS = timezone(timedelta(hours=4))
HISTORY_DIR = r"D:\ark\automas\history"
RELAY_LOG = arklog.RELAY_LOG
SCRIPT_LOGS = (
    ("ok-ww", "ok-script.log", arklog.OKWW_LOG),
    ("MAA", "asst.log", r"D:\ark\maa\debug\asst.log"),
    ("MAA", "gui.log", arklog.MAA_GUI_LOG),
    ("MaaEnd", "maafw.log", r"D:\ark\maaend\debug\maafw.log"),
)
_HEARTBEAT_RE = re.compile(r"下一个闹钟\s+\d{2}:\d{2}\s+在跑巡查")
_TAIL_BYTES = 65536
_RECENT_LOG_SECS = 900


# AUTO-MAS's /api/dispatch/start body since its update of 2026-11-16 21:21 (Beijing): the old
# {"taskId", "mode"} gets 422. The relay builds the same bodies (ark_relay/features/commands.py
# dispatch_body, where the upstream sources are named); relay/tests/test_schedule.py checks the two
# agree. Kept here as well: this script runs on its own over winrun.
def start_body(*, script_id="", queue_id=""):
    node = {"uid": queue_id} if queue_id else {"uid": "-", "children": {"0": {"uid": script_id}}}
    return {"mode": "AutoProxy", "tasks": {"0": node}}


def _said(r) -> str:
    """The start's answer in words: a 422 is AUTO-MAS not taking the body's shape."""
    if r.get("HTTP") == 422:
        return "调度程序不认这次派发的写法（它回 422），它升级后改过派发的格式，这个脚本要跟着改：" + str(r.get("msg", ""))
    return f"{r.get('status')} {r.get('message', '')}"


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


def _proc_start_times() -> list[str]:
    """Single pwsh CIM query returning ['label(pid) HH:MM:SS 起', ...] for active scripts/games."""
    exes = ",".join(f"'{e}'" for e in SCRIPT_EXES + GAME_EXES)
    ps = (
        f"$exes = @({exes}); "
        "Get-CimInstance Win32_Process | ForEach-Object { "
        "$n = $_.Name; $c = $_.CommandLine; $st = if ($_.CreationDate) { $_.CreationDate.ToString('HH:mm:ss') } else { '?' }; "
        "if ($exes -contains $n) { Write-Output ($n.Substring(0, $n.Length - 4) + '|' + $_.ProcessId + '|' + $st) } "
        r"elseif (($n -eq 'pythonw.exe' -or $n -eq 'python.exe') -and $c -like '*\ok-ww\*') "
        "{ Write-Output ('ok-ww|' + $_.ProcessId + '|' + $st) } }"
    )
    out = subprocess.run([PWSH, "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, errors="replace", timeout=15).stdout
    rows = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3 and parts[0]:
            rows.append(f"{parts[0]}(pid {parts[1]}, {parts[2]} 起)")
    return rows


def _tail_ts_lines(path: str | Path, *, limit: int = 5, skip_re=None) -> tuple[str | None, list[str]]:
    """Read last 64KB of a log file (never whole multi-MB log) and return (mtime_str, last timestamped lines)."""
    p = Path(path)
    if not p.is_file():
        return None, []
    st = p.stat()
    mt = datetime.fromtimestamp(st.st_mtime, TZ_BJ).strftime("%m-%d %H:%M:%S")
    with p.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        sz = fh.tell()
        fh.seek(max(0, sz - _TAIL_BYTES))
        raw = fh.read().decode("utf-8", errors="replace")
    kept: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if skip_re is not None and skip_re.search(s):
            continue
        if arklog.parse_ts(s) is None:
            continue
        kept.append(s[:140])
    return mt, kept[-limit:]


def _recent_history_db(history_root: Path, day: str, limit: int) -> list[str]:
    """Read latest AUTO-MAS v5.8.0-beta.2+ rows from data/history.db (read-only)."""
    db = history_root.parent / "data" / "history.db"
    if not db.is_file():
        return []
    con = None
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2)
        rows = con.execute(
            "SELECT time, script_name, message FROM records ORDER BY timestamp DESC LIMIT 30"
        ).fetchall()
    except (sqlite3.Error, OSError):
        return []
    finally:
        if con is not None:
            con.close()
    picked: list[str] = []
    for time_s, script_name, message in rows:
        try:
            at = datetime.fromisoformat(str(time_s))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=TZ_AUTOMAS)
        at_bj = at.astimezone(TZ_BJ)
        if at_bj.strftime("%Y-%m-%d") != day:
            continue
        msg = str(message or "?").replace("\n", " ").strip() or "?"
        picked.append(f"{at_bj:%H:%M:%S} | {script_name or '?'} | {msg[:80]}")
        if len(picked) >= limit:
            break
    picked.reverse()
    return picked


def _parse_json_stem_bj(date_str: str, stem: str) -> datetime | None:
    """Parse legacy AUTO-MAS '<script>-HH-MM-SS' or 'HH-MM-SS' stem on UTC+4 into Beijing time."""
    parts = stem.rsplit("-", 3)[-3:]
    stem_time = "-".join(parts) if len(parts) == 3 else stem
    try:
        dt = datetime.strptime(f"{date_str} {stem_time}", "%Y-%m-%d %H-%M-%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=TZ_AUTOMAS).astimezone(TZ_BJ)


def _recent_history_today(limit: int = 3, *, today_str: str | None = None) -> list[str]:
    """Latest AUTO-MAS history records for today (Beijing date), zero rglob/os.walk.

    Tries live SQLite data/history.db first (AUTO-MAS v5.8.0-beta.2+); falls back to
    legacy JSON files sorted by mtime (scanning yesterday's UTC+4 folder for Beijing
    00:00-03:59 runs) and skips corrupt JSON without consuming limit slots."""
    history_root = Path(HISTORY_DIR)
    day = today_str or datetime.now(TZ_BJ).strftime("%Y-%m-%d")
    db_rows = _recent_history_db(history_root, day, limit)
    if db_rows:
        return db_rows

    try:
        prev_day = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        prev_day = ""

    candidates: list[tuple[float, float, Path]] = []
    for d_str in (prev_day, day):
        if not d_str:
            continue
        day_dir = history_root / d_str
        if not day_dir.is_dir():
            continue
        for sub in day_dir.iterdir():
            if not sub.is_dir():
                continue
            for jf in sub.iterdir():
                if not (jf.is_file() and jf.suffix.lower() == ".json"):
                    continue
                try:
                    mtime = jf.stat().st_mtime
                except OSError:
                    continue
                at_bj = _parse_json_stem_bj(d_str, jf.stem)
                if d_str == prev_day:
                    bj_day = (at_bj or datetime.fromtimestamp(mtime, TZ_BJ)).strftime("%Y-%m-%d")
                    if bj_day != day:
                        continue
                parsed_ts = at_bj.timestamp() if at_bj is not None else 0.0
                candidates.append((mtime, parsed_ts, jf))

    candidates.sort(key=lambda item: (item[0], item[1], item[2].name))
    out: list[str] = []
    for _, _, jf in reversed(candidates):
        try:
            with jf.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if "maa_result" in data:
            kind, res = "MAA", str(data.get("maa_result") or "?")
        elif "maaend_result" in data:
            kind, res = "MaaEnd", str(data.get("maaend_result") or "?")
        elif "general_result" in data:
            kind, res = "OK-WW", str(data.get("general_result") or "?")
        else:
            kind, res = "?", "?"
        res = res.replace("\n", " ").strip() or "?"
        out.append(f"{jf.stem} | {kind} | {res[:80]}")
        if len(out) >= limit:
            break
    out.reverse()
    return out


def _status_details(busy, games, *, now_epoch: float | None = None, today_str: str | None = None):
    """Best-effort atomic live context for `status`: start times, AUTO-MAS live tasks,
    today's latest history, heartbeat-filtered relay.log tail, and active/recent script logs.
    Every block is isolated so missing files or unreachable APIs never break `status`."""
    if busy or games:
        try:
            starts = _proc_start_times()
            if starts:
                print("进程启动:", "；".join(starts))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    try:
        live = live_tasks(timeout=3, quiet=True)
        if live is None:
            print("AUTO-MAS 在跑: 连不上")
        elif live:
            print("AUTO-MAS 在跑:", "；".join(f"{lbl}({tid[:8]})" for tid, lbl in live))
        else:
            print("AUTO-MAS 在跑: 无")
    except (OSError, ValueError, urllib.error.URLError):
        pass
    try:
        hist = _recent_history_today(limit=3, today_str=today_str)
        if hist:
            print("今日最近记录:")
            for row in hist:
                print(" ", row)
    except (OSError, ValueError, sqlite3.Error):
        pass
    try:
        mt, lines = _tail_ts_lines(RELAY_LOG, limit=5, skip_re=_HEARTBEAT_RE)
        if mt is not None:
            print(f"relay.log（写入 {mt}，已过滤心跳）:")
            if lines:
                for ln in lines:
                    print(" ", ln)
            else:
                print("  (最近 64KB 无非心跳记录)")
    except (OSError, ValueError):
        pass
    now_ts = now_epoch if now_epoch is not None else time.time()
    busy_set = set(busy or ())
    for script_name, label, log_path in SCRIPT_LOGS:
        try:
            p = Path(log_path)
            if not p.is_file():
                continue
            age = now_ts - p.stat().st_mtime
            if script_name not in busy_set and age > _RECENT_LOG_SECS:
                continue
            mt, lines = _tail_ts_lines(p, limit=5)
            if mt is not None and lines:
                tag = "活跃" if script_name in busy_set else f"{max(0, int(age))}秒前更新"
                print(f"{script_name}/{label}（写入 {mt}，{tag}）:")
                for ln in lines:
                    print(" ", ln)
        except (OSError, ValueError):
            continue


def status(detail: bool = False):
    busy, games = running()
    print("脚本在跑:", busy or "无", "｜游戏在跑:", games or "无")
    if detail:
        _status_details(busy, games)
    return busy


def live_tasks(timeout: int = 10, quiet: bool = False):
    """AUTO-MAS's running dispatch tasks: [(taskId, label)]. The taskId here is
    what /api/dispatch/stop wants - a dispatch id, not a script or queue id.

    None when AUTO-MAS cannot be asked (unreachable, timed out, not JSON). That
    is not [] = "nothing running": until 2026-10-10 it was, and stop went
    straight to taskkill on an unknown state."""
    try:
        d = json.loads(urllib.request.urlopen(API + "/api/dispatch/runtime-snapshot",
                                              timeout=timeout).read().decode())
    except (urllib.error.URLError, OSError, ValueError) as e:
        if not quiet:
            print(f"  ❌ 问不到 AUTO-MAS 在跑什么（{e}）")
        return None
    out = []
    for t in d.get("tasks") or []:
        if "task_info" in t:
            items = t.get("task_info") or []
        else:
            scripts = (t.get("task") or {}).get("scripts") or {}
            data = scripts.get("data") or {}
            order = [r.get("uid") for r in (scripts.get("order") or []) if isinstance(r, dict)]
            uids = [u for u in order if u in data] + [u for u in data if u not in order]
            items = [(data[u] or {}).get("info") or {} for u in uids if isinstance(data[u], dict)]
        names = [i.get("name", "") for i in items if isinstance(i, dict) and i.get("name")]
        out.append((t.get("taskId", ""), "、".join(names) or t.get("mode", "?")))
    return out


def _api_stop():
    # The running task's own id is the one to send: AUTO-MAS answers 操作成功 to the script and queue
    # ids and stops nothing. Returns False when AUTO-MAS could not be asked, True otherwise.
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
    from ark_relay.features import modes  # noqa: PLC0415 - the machine's relay code
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
        _status_details(busy, [])
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
    r = post("/api/dispatch/start", start_body(script_id=table[name]))
    print(f"派发「{name}」:", _said(r))
    return 0 if str(r.get("status", "")).lower() == "success" else 4


def start_queue(name) -> int:
    print("⚠️ 你在派**整条队列**。队列成员失败时 AUTO-MAS 会整队从头重试，"
          "中途 taskkill 任何成员都会引发连锁——2026-09-01 上午就是这么乱的。")
    busy = status()
    if busy:
        _status_details(busy, [])
        print(f"❌ 拒绝：{busy} 在跑。")
        return 2
    table = qids()
    if name not in table:
        print(f"❌ 没有叫「{name}」的队列。有：{'、'.join(table)}")
        return 3
    r = post("/api/dispatch/start", start_body(queue_id=table[name]))
    print(f"派发队列「{name}」:", _said(r))
    return 0 if str(r.get("status", "")).lower() == "success" else 4


if __name__ == "__main__":
    a = sys.argv[1:] or ["status"]
    if a[0] == "status":
        status(detail=True)
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
