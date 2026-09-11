"""Re-run only the gathering routes that failed, once, after the queue is done.

MaaEnd runs its 17 rare routes in one task; one failed route fails the task,
and AUTO-MAS answers a failed task by running the whole script again. On
2026-09-11 that meant 15 good routes walked twice for the sake of routes 15
and 16. The maintainer declined to add a per-route retry upstream
(MaaEnd/MaaEnd#5660: 「建议让上层加入针对指定路线重试」), and AUTO-MAS has no
idea what a route is - so it lives here.

How it works, all from files MXU writes anyway:

* Which routes failed: the AUTO-MAS history log carries MXU's focus lines,
  「路线15：红矛叶采集失败」. The route id behind each label comes from MaaEnd's
  own locale file (`option.AutoCollectRoute15.failed`), never from a table of
  our own.
* What to send: MXU logs the exact pipeline override it built for the run
  (`entry=AutoCollectSchedule, pipelineOverride=[...]` in its app log). That
  override, with every other route's Start/Dispatch keys dropped and today's
  weekday attached, is the retry. Nothing is invented; if that line cannot be
  found the retry is refused with a reason.
* Did it work: MaaFW's log names the node that ran - `AutoCollectRoute15End`
  or `AutoCollectRoute15Failed`.

A route that fails the retry too is recorded per day; two days in a row is
「复发性」, and the notice asks for a person to file it upstream (with the
evidence bundle) instead of retrying forever.

The retry itself needs the game and MaaEnd on the interactive desktop; the
relay is a session-0 service, so it launches them the way the pre-update does
(`preupdate_common._spawn_interactive`) and drives MXU over its local HTTP
API. It runs at most once per day, only when the queue is idle, and blocks
the automatic shutdown while it runs.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ark.collect_retry")

MXU = "http://127.0.0.1:12701/api"
ENTRY = "AutoCollectSchedule"
_ROUTE_KEY = re.compile(r"^(AutoCollect(?:Common)?Route\d+)(Start|Dispatch)$")
_FAILED_LINE = re.compile(r"^\[[^\]]+\]\s*(.+?采集失败)\s*$")
_OVERRIDE_LINE = re.compile(r"entry=" + ENTRY + r", pipelineOverride=(\[.*\])\s*$")
_NODE = re.compile(r"\[msg=Node\.Action\.Starting\].*?\"name\":\"(AutoCollect(?:Common)?Route\d+)(End|Failed)\"")
_TAG = re.compile(r"<[^>]+>")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# Two consecutive days of the same route failing its retry: stop retrying and
# ask for a person (the user's order of 2026-09-12: mark it recurrent, 申请人工去提issue).
RECURRENT_DAYS = 2


# ----------------------------------------------------------------- parsing

def failed_labels_from_locale(zh_cn: dict) -> dict[str, str]:
    """{stripped failed text: route id} from MaaEnd's zh_cn locale.

    `option.AutoCollectRoute15.failed` holds
    `<span ...>路线15：红矛叶采集失败</span>`; the log line is the same text
    without the tags. The route id is the key's middle segment.
    """
    out: dict[str, str] = {}
    for key, val in zh_cn.items():
        m = re.fullmatch(r"option\.(AutoCollect(?:Common)?Route\d+)\.failed", key)
        if m and isinstance(val, str):
            out[_TAG.sub("", val).strip()] = m.group(1)
    return out


def failed_routes(automas_log: str, labels: dict[str, str]) -> list[str]:
    """Route ids whose 「…采集失败」 line appears in the run's AUTO-MAS log, in order."""
    found: list[str] = []
    for line in automas_log.splitlines():
        m = _FAILED_LINE.match(line.strip())
        if not m:
            continue
        rid = labels.get(m.group(1).strip())
        if rid and rid not in found:
            found.append(rid)
    return found


def logged_override(app_log: str) -> list[dict] | None:
    """The pipeline override MXU logged for the last AutoCollectSchedule run, as MXU sent it (a list)."""
    last = None
    for line in app_log.splitlines():
        m = _OVERRIDE_LINE.search(line.strip())
        if m:
            last = m.group(1)
    if last is None:
        return None
    try:
        arr = json.loads(last)
    except json.JSONDecodeError:
        return None
    return arr if isinstance(arr, list) else None


def _merge(parts: list[dict]) -> dict:
    """Fold MXU's list of override objects into one, merging `attach` maps instead of replacing them."""
    out: dict = {}
    for part in parts:
        for node, spec in part.items():
            if (isinstance(spec, dict) and isinstance(spec.get("attach"), dict)
                    and isinstance(out.get(node), dict) and isinstance(out[node].get("attach"), dict)):
                out[node]["attach"].update(spec["attach"])
            else:
                out[node] = spec
    return out


def build_override(parts: list[dict], routes: list[str], weekday: str) -> dict:
    """Keep the logged override but only the wanted routes, and make today a gathering day."""
    if weekday not in WEEKDAYS:
        raise ValueError(f"not a weekday: {weekday}")
    merged = _merge(parts)
    wanted = set(routes)
    out: dict = {}
    for node, spec in merged.items():
        m = _ROUTE_KEY.match(node)
        if m and m.group(1) not in wanted:
            continue
        out[node] = spec
    for rid in routes:
        out.setdefault(f"{rid}Start", {"enabled": True})
        out.setdefault(f"{rid}Dispatch", {"enabled": True})
    sched = out.setdefault("AutoCollectScheduleEnabled", {})
    attach = sched.setdefault("attach", {}) if isinstance(sched, dict) else {}
    attach[weekday] = True
    return out


def judge(maafw_log: str, routes: list[str], since: str) -> dict[str, bool | None]:
    """{route: True passed / False failed / None no verdict} from MaaFW node events after `since` (HH:MM:SS)."""
    verdict: dict[str, bool | None] = {r: None for r in routes}
    for line in maafw_log.splitlines():
        if len(line) < 20 or line[12:20] < since:
            continue
        m = _NODE.search(line)
        if not m or m.group(1) not in verdict:
            continue
        verdict[m.group(1)] = m.group(2) == "End"
    return verdict


# --------------------------------------------------------- recurrence store

def record_failures(store: Path, day: str, routes: list[str]) -> dict[str, list[str]]:
    """Append today's still-failing routes; returns {route: [days]} for all routes."""
    data: dict[str, list[str]] = {}
    if store.exists():
        try:
            data = json.loads(store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    for rid in routes:
        days = data.setdefault(rid, [])
        if day not in days:
            days.append(day)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def clear_failures(store: Path, routes: list[str]) -> None:
    """A route that passed its retry starts its streak over."""
    if not store.exists():
        return
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for rid in routes:
        data.pop(rid, None)
    store.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def recurrent(data: dict[str, list[str]], days: int = RECURRENT_DAYS) -> list[str]:
    """Routes whose last `days` recorded failures fall on consecutive calendar days."""
    out = []
    for rid, dates in data.items():
        if len(dates) < days:
            continue
        tail = sorted(dates)[-days:]
        d = [datetime.strptime(x, "%Y-%m-%d").date() for x in tail]
        if all((d[i + 1] - d[i]).days == 1 for i in range(len(d) - 1)):
            out.append(rid)
    return out


# ------------------------------------------------------------- the run itself

_LISTEN = re.compile(r"Web server listening on http://127\.0\.0\.1:(\d+)")


def mxu_port(maaend_dir: Path, default: int = 12701) -> int:
    """The port MXU's web server really bound - it falls back to 12702 when 12701 is held (its own log says so)."""
    p = maaend_dir / "debug" / "mxu-tauri.log"
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError:
        return default
    port = default
    for line in lines:
        if m := _LISTEN.search(line):
            port = int(m.group(1))
    return port


def api(path: str, body: dict | None = None, timeout: int = 30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(MXU + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def _running(names: tuple[str, ...]) -> set[str]:
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    have = {ln.split('","')[0].lstrip('"').lower() for ln in out.splitlines() if ln}
    return {n for n in names if n.lower() in have}


def _kill(name: str) -> None:
    subprocess.run(["taskkill", "/f", "/im", name], capture_output=True, timeout=30, check=False)


def _game_exe(maaend_dir: Path) -> Path | None:
    """The game path MXU itself has saved (`savedDevice.connectedProgramPath`), never a guess."""
    try:
        doc = json.loads((maaend_dir / "config" / "mxu-MaaEnd.json").read_text(encoding="utf-8"))
        for inst in doc.get("instances") or []:
            p = (inst.get("savedDevice") or {}).get("connectedProgramPath")
            if p:
                return Path(p)
    except (OSError, ValueError):
        pass
    return None


def _wait(pred, seconds: int, step: float = 3.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            if pred():
                return True
        except Exception:  # noqa: BLE001 - polling, the failure mode is "not yet"
            pass
        time.sleep(step)
    return False


def run_retry(maaend_dir: Path, routes: list[str], weekday: str, *, spawn, timeout: int = 1200) -> tuple[dict[str, bool | None], str]:
    """Bring up MXU and the game, send the override, wait, judge. Returns (verdict, note).

    `spawn(exe: Path, cwd: Path, args: tuple)` launches on the interactive
    desktop (the pre-update's helper in production, a stub in tests).
    """
    debug = maaend_dir / "debug"
    app_logs = sorted(debug.glob("20??-??-??-*.log"), key=lambda p: p.stat().st_mtime)
    parts = None
    for p in reversed(app_logs):
        parts = logged_override(p.read_text(encoding="utf-8", errors="replace"))
        if parts:
            break
    if not parts:
        return {r: None for r in routes}, "MaaEnd 的日志里找不到上一趟采集的参数，不敢自己编，这次不补跑"
    override = build_override(parts, routes, weekday)

    global MXU  # noqa: PLW0603 - the port is discovered per launch
    if "MaaEnd.exe" in _running(("MaaEnd.exe",)):
        MXU = f"http://127.0.0.1:{mxu_port(maaend_dir)}/api"
        if not _wait(lambda: api("/maa/state", timeout=5) is not None, 10, step=2):
            # Running but deaf: a leftover instance whose port is gone. Start over.
            _kill("MaaEnd.exe")
            time.sleep(3)
    if "MaaEnd.exe" not in _running(("MaaEnd.exe",)):
        spawn(maaend_dir / "MaaEnd.exe", maaend_dir, ())
        time.sleep(8)
    MXU = f"http://127.0.0.1:{mxu_port(maaend_dir)}/api"
    if not _wait(lambda: api("/maa/state", timeout=5) is not None, 60):
        return {r: None for r in routes}, "MaaEnd 的接口 60 秒没起来"
    game = _game_exe(maaend_dir)
    if game is None:
        return {r: None for r in routes}, "MaaEnd 配置里没有游戏路径"
    if "Endfield.exe" not in _running(("Endfield.exe",)):
        spawn(game, game.parent, ())
    hwnd = {}

    def _window():
        wins = api("/maa/windows?class_regex=UnityWndClass&window_regex=Endfield")
        wins = wins if isinstance(wins, list) else (wins or {}).get("windows") or []
        if wins:
            hwnd["h"] = wins[0].get("handle") or wins[0].get("hwnd")
        return bool(hwnd)
    if not _wait(_window, 180):
        return {r: None for r in routes}, "游戏窗口 3 分钟没出现"
    time.sleep(10)
    inst = next(iter((api("/maa/state").get("instances") or {}).keys()), "automas")
    api(f"/maa/instances/{inst}/connect", {"type": "Win32", "handle": int(hwnd["h"]),
                                         "screencap_method": 32, "mouse_method": 1, "keyboard_method": 1}, timeout=60)
    if not _wait(lambda: (api("/maa/state").get("instances") or {}).get(inst, {}).get("connected"), 60):
        return {r: None for r in routes}, "控制器没连上游戏窗口"
    if not (api("/maa/state").get("instances") or {}).get(inst, {}).get("resource_loaded"):
        api(f"/maa/instances/{inst}/resource/load", {"paths": [str(maaend_dir / "resource")]}, timeout=120)
        _wait(lambda: (api("/maa/state").get("instances") or {}).get(inst, {}).get("resource_loaded"), 120)
    since = time.strftime("%H:%M:%S")
    api(f"/maa/instances/{inst}/tasks/start", {
        "tasks": [{"entry": ENTRY, "pipeline_override": json.dumps(override, ensure_ascii=False)}],
        "agent_configs": [{"child_exec": "agent/go-service"}, {"child_exec": "agent/cpp-algo", "child_args": []}],
        "cwd": str(maaend_dir), "tcp_compat_mode": False, "pi_envs": None,
        "reset_state": True, "controller_info": None}, timeout=120)
    done = _wait(lambda: not (api("/maa/state").get("instances") or {}).get(inst, {}).get("is_running"), timeout, step=15)
    if not done:
        try:
            api(f"/maa/instances/{inst}/tasks/stop", {})
        except (urllib.error.URLError, OSError):
            pass
    try:
        api(f"/maa/instances/{inst}/agent/stop", {})
    except (urllib.error.URLError, OSError):
        pass
    text = ""
    for p in sorted(debug.glob("maafw*.log"), key=lambda q: q.stat().st_mtime)[-2:]:
        text += p.read_text(encoding="utf-8", errors="replace")
    verdict = judge(text, routes, since)
    _kill("MaaEnd.exe")
    _kill("Endfield.exe")
    return verdict, ("补跑超时，已停掉" if not done else "")


# ------------------------------------------------------------------ glue

_VERDICT = re.compile(r"任务(完成|失败)[:：]\s*\S*自动采集")


def latest_gathering_run(ledger_entries: list[dict], history_dir: Path, labels: dict[str, str]) -> tuple[dict | None, list[str]]:
    """Walk the day's MaaEnd records from the last one back to the first whose log reached a gathering verdict.

    AUTO-MAS's own retries come later in the ledger, and a retry that was
    stopped by hand leaves a log with 「任务开始」 and no verdict (2026-09-11
    10:46 and 10:48). Such a run says nothing about the routes, so the one
    before it is the one that counts. Returns (record, failed route ids).
    """
    runs = [e for e in ledger_entries if e.get("script") == "MaaEnd" and e.get("run_id")]
    for rec in reversed(runs):
        p = Path(history_dir) / (str(rec["run_id"]) + ".log")
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if not _VERDICT.search(text):
            continue
        return rec, failed_routes(text, labels)
    return None, []


def route_label(rid: str, zh_cn: dict) -> str:
    return _TAG.sub("", str(zh_cn.get(f"option.{rid}.label") or rid)).strip()


def _locale(maaend_dir: Path) -> dict:
    p = maaend_dir / "locales" / "interface" / "zh_cn.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def maybe_run(eng, now: datetime | None = None, day: str | None = None) -> bool:
    """Once per day, after the queue is idle: retry that day's failed routes. True if a retry ran.

    Called from the shutdown decision so a power-off waits for it. It reads
    only files the run already produced and refuses (with a logged reason)
    rather than guess when any of them is missing. `day` names the ledger to
    read (default today); the weekday attached to the retry is always the
    real one, since that is the game's clock.
    """
    from . import texts  # noqa: PLC0415
    from .config import SERVER_TZ  # noqa: PLC0415
    from .preupdate_common import _spawn_interactive  # noqa: PLC0415

    cfg = eng.cfg
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    day = day or now.strftime("%Y-%m-%d")
    state_dir = Path(cfg.state_dir)
    stamp = state_dir / "collect-retry" / f"{day}.json"
    if stamp.exists():
        log.info("自动采集补跑：%s 已经跑过（%s）", day, stamp)
        return False
    if not cfg.maaend_dir or not cfg.history_dir:
        log.info("自动采集补跑：没配 MaaEnd 目录或历史目录，不跑")
        return False
    entries = eng.state.read_ledger(day)
    zh = _locale(Path(cfg.maaend_dir))
    last, routes = latest_gathering_run(entries, Path(cfg.history_dir), failed_labels_from_locale(zh))
    if not last:
        log.info("自动采集补跑：%s 没有带采集结论的终末地记录", day)
        return False
    if not routes:
        log.info("自动采集补跑：%s 全部路线走通，没有要补的", last["run_id"])
        return False
    if eng._scripts_running():
        log.info("自动采集补跑：脚本或游戏还在跑，这次不补（%s）", "、".join(routes))
        return False
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps({"run_id": last["run_id"], "routes": routes, "started": now.isoformat()}),
                     encoding="utf-8")
    names = "、".join(route_label(r, zh) for r in routes)
    log.info("🔁 自动采集补跑 %s（来自 %s）", names, last["run_id"])
    eng.notifier.send(texts.COLLECT_RETRY_START, texts.collect_retry_start_body(names))
    try:
        verdict, note = run_retry(Path(cfg.maaend_dir), routes, WEEKDAYS[now.weekday()],
                                  spawn=_spawn_interactive)
    except Exception as exc:  # the retry must never take the service down
        log.exception("补跑本身出错")
        verdict, note = {r: None for r in routes}, f"补跑没跑起来：{type(exc).__name__}"
    passed = [r for r, v in verdict.items() if v is True]
    failed = [r for r, v in verdict.items() if v is False]
    unknown = [r for r, v in verdict.items() if v is None]
    store = state_dir / "collect-retry" / "failures.json"
    clear_failures(store, passed)
    data = record_failures(store, day, failed) if failed else {}
    rec = recurrent(data) if failed else []
    stamp.write_text(json.dumps({"run_id": last["run_id"], "routes": routes, "passed": passed,
                                 "failed": failed, "unknown": unknown, "recurrent": rec,
                                 "note": note, "finished": datetime.now(tz=SERVER_TZ).isoformat()},
                                ensure_ascii=False), encoding="utf-8")
    body = texts.collect_retry_body([route_label(r, zh) for r in passed],
                                    [route_label(r, zh) for r in failed],
                                    [route_label(r, zh) for r in unknown], note)
    if not failed and not unknown:
        eng.state.mark_incomplete(day, last["run_id"], "")
        eng.notifier.send(texts.COLLECT_RETRY_OK, body)
    elif rec:
        eng.notifier.send(texts.COLLECT_RECURRENT,
                          body + "\n" + texts.collect_recurrent_body([route_label(r, zh) for r in rec]), alert=True)
    else:
        eng.notifier.send(texts.COLLECT_RETRY_FAILED, body, alert=True)
    return True
