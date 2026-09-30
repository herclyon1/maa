#!/usr/bin/env python3
"""The 2026-09-30 evening boot check (docs/NEXT-BOOT.md, top section) as one read-only command.

    scripts/mac/boot-check.py                   # every read-only item
    scripts/mac/boot-check.py --since 30m       # ntfy window in ntfy's own syntax (also 12h, 21:00, unix ts)
    scripts/mac/boot-check.py --wtest           # ALSO the MaaEnd WaitTime +1 / back round trip -
                                                # the only item that changes config; off by default

Each item prints one line `[过] / [不过] / [读不到] name — the line or value it read`;
item 3 (why the machine vanished at 10:12) prints `[读数]` lines, it has no verdict.
The last line counts them. Exit: 0 all passed, 1 something did not, 2 machine offline.

Nothing here writes to the machine, pushes a notification, calls `report --again`
(that pushes a real 🔎 report), shuts anything down or edits config - except --wtest.
The machine side is scripts/mac/lib/boot_check_remote.py, sent once through
`winrun.sh --py`; see its docstring for how it stays read-only. The ntfy topic
name and the PIN are never printed.

Test hooks: --local-relay DIR runs the reader locally against a fake relay dir
(relay.log / .env / state) with the repo's relay/ code; --remote-json FILE judges
a saved reader output. Both skip the machine and the online check.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BJ = timezone(timedelta(hours=8))
PUSH_ENV = Path.home() / ".config/ark/push.env"
PY314 = Path.home() / ".local/bin/python3.14"

LOOKBACK = 900        # ntfy history fetched before the window, to see what preceded the first set
QUIET = 600           # silence before a state set that makes it a start rather than a mid-run push
BYE_AFTER = 15        # SvcStop: its last state is followed by bye within seconds (boot_stages / phone.py)
HB_AFTER = 180        # a starting process beats once on entry (phone.Heartbeat.loop), after the boot backlog

COUNTS = {"过": 0, "不过": 0, "读不到": 0, "读数": 0, "说明": 0}


def say(tag: str, name: str, text: str = "") -> None:
    COUNTS[tag] = COUNTS.get(tag, 0) + 1
    text = " ".join(str(text).split())
    if len(text) > 200:
        text = text[:199] + "…"
    print(f"[{tag}] {name}" + (f" — {text}" if text else ""), flush=True)


def detail(text: str) -> None:
    text = " ".join(str(text).split())
    print("      " + (text[:199] + "…" if len(text) > 200 else text), flush=True)


# ---------------------------------------------------------------- 0. online
def online(host: str) -> bool:
    try:
        r = subprocess.run(["nc", "-z", "-G", "8", host, "22"], capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


# ---------------------------------------------------------------- 1. ntfy
def _topic() -> str:
    if os.environ.get("ARK_PHONE_TOPIC"):
        return os.environ["ARK_PHONE_TOPIC"].strip()
    try:
        for ln in PUSH_ENV.read_text(encoding="utf-8").splitlines():
            k, _, v = ln.partition("=")
            if k.strip() == "ARK_PHONE_TOPIC":
                return v.split("#")[0].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def since_ts(spec: str, now: float) -> int:
    """'21:00' (Beijing, today), '30m' / '12h' / '2d' / '90s' (ntfy style), or a unix timestamp."""
    spec = spec.strip()
    if spec.isdigit():
        return int(spec)
    if spec[:-1].isdigit() and spec[-1:] in "smhd":
        return int(now - int(spec[:-1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[spec[-1]])
    hh, _, mm = spec.partition(":")
    d = datetime.fromtimestamp(now, BJ)
    return int(d.replace(hour=int(hh), minute=int(mm or 0), second=0, microsecond=0).timestamp())


def _poll(topic: str, since: int) -> list[dict]:
    req = urllib.request.Request(f"https://ntfy.sh/{topic}/json?poll=1&since={since}",
                                 headers={"User-Agent": "ark-boot-check"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = [json.loads(x) for x in r.read().decode("utf-8").splitlines() if x.strip()]
    return [m for m in rows if m.get("event") == "message"]


def _bj(ts: float) -> str:
    return datetime.fromtimestamp(ts, BJ).strftime("%m-%d %H:%M:%S")


def state_sets(state_msgs: list[dict]) -> list[dict]:
    """The relay's state pushes, one per publish: chunked ones share a sid (phone.pack_chunks)."""
    sets: dict = {}
    for m in state_msgs:
        try:
            env = json.loads(m.get("message") or "")
        except ValueError:
            continue
        if not isinstance(env, dict) or env.get("kind") != "state":
            continue                                   # phone commands share this topic
        key = env.get("sid") or m.get("id")
        s = sets.setdefault(key, {"t": m["time"], "n": int(env.get("n") or 1), "got": 0})
        s["t"] = min(s["t"], m["time"])
        s["got"] += 1
    return sorted(sets.values(), key=lambda s: s["t"])


def classify(sets: list[dict], hb_msgs: list[dict]) -> None:
    """Mark each set boot / restart / stop / other from the heartbeat topic around it.

    A process start publishes its state, then its heartbeat thread beats once
    (boot_stages._start_phone_channel, phone.Heartbeat.loop). SvcStop publishes a
    last state and then says bye. Evidence 2026-09-30: 10:10:37 state -> 10:10:40
    bye (old process stopped), 10:10:49 state -> 10:10:55 hb (new process).
    """
    hbs = sorted(((m["time"], "bye" if (m.get("message") or "").startswith("bye") else "hb")
                  for m in hb_msgs), key=lambda x: x[0])
    relay_msgs = sorted([(s["t"], "state") for s in sets] + hbs, key=lambda x: x[0])
    for s in sets:
        t = s["t"]
        bye = any(k == "bye" and t <= ht <= t + BYE_AFTER for ht, k in hbs)
        beat = next((ht for ht, k in hbs if k == "hb" and t < ht <= t + HB_AFTER), None)
        prev = [x for x in relay_msgs if x[0] < t]
        cold = not prev or t - prev[-1][0] >= QUIET        # machine was silent: a boot
        restart = bool(prev) and prev[-1][1] == "bye"      # a stop just before: service restart
        s["beat"] = beat
        s["kind"] = ("stop" if bye else "boot" if (beat and cold)
                     else "restart" if (beat and restart) else "other")


def check_ntfy(spec: str) -> None:
    name = "开机推送（ntfy 状态话题）"
    topic = _topic()
    if not topic:
        say("读不到", name, f"{PUSH_ENV} 里没有 ARK_PHONE_TOPIC")
        return
    now = time.time()
    try:
        start = since_ts(spec, now)
    except ValueError:
        say("读不到", name, f"--since {spec!r} 看不懂（用 21:00 / 30m / 12h / unix 时间戳）")
        return
    if start > now:
        say("不过", name, f"窗口起点北京 {_bj(start)} 还没到（现在北京 {_bj(now)}）")
        return
    try:
        state_msgs = _poll(topic, start - LOOKBACK)
        hb_msgs = _poll(topic + "-hb", start - LOOKBACK)
    except Exception as exc:  # noqa: BLE001 - any fetch failure is 读不到
        say("读不到", name, f"拉 ntfy 失败：{type(exc).__name__}: {str(exc).replace(topic, '<话题>')}")
        return
    sets = state_sets(state_msgs)
    classify(sets, hb_msgs)
    inwin = [s for s in sets if s["t"] >= start]
    starts = [s for s in inwin if s["kind"] in ("boot", "restart")]
    byes = sum(1 for m in hb_msgs if m["time"] >= start and (m.get("message") or "").startswith("bye"))
    tail = f"窗口北京 {_bj(start)} 起：状态推送 {len(inwin)} 组，下线心跳 bye {byes} 次"
    if starts:
        s = starts[0]
        what = "开机推送" if s["kind"] == "boot" else "进程重启推送（前面刚有 bye）"
        more = (f"；之后又有 {len(starts) - 1} 次进程启动（{', '.join(_bj(x['t'])[6:] for x in starts[1:4])}）"
                if starts[1:] else "")
        say("过", name, f"{what} 北京 {_bj(s['t'])}（{s['got']}/{s['n']} 片），"
                         f"其后 {int(s['beat'] - s['t'])} 秒首拍心跳{more}；{tail}")
    elif inwin:
        last = inwin[-1]
        say("不过", name, f"有推送但没有一组像开机（最后一组北京 {_bj(last['t'])} 判为"
                           f"{'停服务前的最后状态' if last['kind'] == 'stop' else '运行中推送'}）；{tail}")
    else:
        say("不过", name, f"{tail}——没有任何状态推送")
    for s in inwin[-8:]:
        detail(f"北京 {_bj(s['t'])} {s['got']}/{s['n']} 片 → "
               + {"boot": "开机（之前静默，其后首拍心跳）", "restart": "进程重启（之前 bye，其后首拍心跳）",
                  "stop": "停服务（其后 bye）", "other": "运行中推送"}[s["kind"]])


# ---------------------------------------------------------------- machine readings
def run_reader(args) -> "tuple[dict | None, str]":
    reader = HERE / "lib" / "boot_check_remote.py"
    rargs = ["--day", args.day, "--runs", args.runs]
    if args.remote_json:
        text = Path(args.remote_json).read_text(encoding="utf-8")
        cmd = None
    elif args.local_relay:
        cmd = [str(PY314), str(reader), "--root", args.local_relay,
               "--code-dir", str(REPO / "relay")] + rargs
    else:
        cmd = [str(HERE / "winrun.sh"), "--py", str(reader)] + rargs
    if cmd:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=200)
        except (OSError, subprocess.SubprocessError) as exc:
            return None, f"{type(exc).__name__}: {exc}"
        text = r.stdout.decode("utf-8", "replace")
        errs = r.stderr.decode("utf-8", "replace").strip().splitlines()
    else:
        errs = []
    for ln in text.splitlines():
        if ln.startswith("BOOTCHECK_JSON="):
            return json.loads(ln[len("BOOTCHECK_JSON="):]), ""
    return None, errs[-1] if errs else (text.strip().splitlines() or ["没有输出"])[-1]


def check_version(res: dict, want: str) -> None:
    name = f"自更新版本 {want}"
    log, relay = res.get("log") or {}, res.get("relay") or {}
    upd = (log.get("updated") or [None])[-1]
    cos = [x for x in log.get("cos_version") or [] if f"v{want}" in x]
    code = relay.get("code_version")
    said = "；".join(x for x in (upd, cos[-1] if cos else None) if x) or "当天没有「代码已更新」行"
    if code is None and "code_version_err" not in relay and relay.get("err"):
        say("读不到", name, relay["err"])
    elif code is None:
        say("读不到", name, f"state versions.code 读不到（{relay.get('code_version_err', '空')}）；{said}")
    elif str(code) == want:
        say("过", name, f"state versions.code = {code}；{said}")
    else:
        say("不过", name, f"state versions.code = {code}，不是 {want}；{said}")


def report_vanish(res: dict) -> None:
    log, relay, win = res.get("log") or {}, res.get("relay") or {}, res.get("windows") or {}
    day, (w0, w1) = res.get("day", ""), res.get("win") or ["", ""]
    boot = win.get("boot")
    starts = log.get("starts_after") or []
    vanish = f"{day} {w0}"
    if boot and boot < vanish and not starts:
        say("读数", "10:12 失踪·开机记录", f"机器没关过（本次开机 {boot}，早于 {w0}；"
                                           f"{w1} 后 relay.log 没有「服务模式启动」）")
    elif boot or starts:
        say("读数", "10:12 失踪·开机记录", f"本次开机 {boot or '读不到'}（机器现在 {win.get('now', '?')}）；"
                                           f"{w1} 后第一次「服务模式启动」：{starts[0] if starts else '没有'}")
    else:
        say("读数", "10:12 失踪·开机记录", f"读不到（{win.get('boot_err') or win.get('err') or log.get('err')}）")
    if log.get("err"):
        say("读数", "10:12 失踪·relay.log", f"读不到 {log.get('file')}：{log['err']}")
    else:
        gu = log.get("window_gameupdate") or []
        say("读数", "10:12 失踪·relay.log", f"{w0}–{w1} 共 {log.get('window_count')} 行，"
                                            f"「游戏更新：」{len(gu)} 行；{w1} 前最后一行：{log.get('last_before_end')}")
        for ln in gu:
            detail(ln)
        detail(f"{w1} 后第一行：{log.get('first_after_end')}")
    if "pending" in relay:
        say("读数", "10:12 失踪·gameupdate_pending",
            json.dumps(relay["pending"], ensure_ascii=False) + ("（旧文件 gameupdate-pending.json 还在）"
                                                                if relay.get("pending_legacy_file") else ""))
    else:
        say("读数", "10:12 失踪·gameupdate_pending",
            f"读不到（{relay.get('pending_err') or relay.get('err')}）")
    if "events" not in win:
        say("读数", "10:12 失踪·系统事件", f"读不到（{win.get('events_err') or win.get('err')}）")
        return
    evs = win["events"]
    key = [e for e in evs if e.get("id") in (6008, 41, 1074)]
    cnt = "、".join(f"{i} ×{sum(1 for e in key if e.get('id') == i)}" for i in (6008, 41, 1074))
    say("读数", "10:12 失踪·系统事件", f"{day} 10:10 起：{cnt}；开机/停机标记 "
                                       f"{sum(1 for e in evs if e.get('id') in (12, 13, 6005, 6006))} 条")
    for e in sorted(evs, key=lambda e: e.get("t") or ""):
        props = e.get("props") or []
        who = ""
        if e.get("id") == 1074 and props:
            who = f"请求方 {props[0]}，用户 {props[6] if len(props) > 6 else '?'}，"
        detail(f"{e.get('t')} {e.get('id')} {e.get('provider')} {who}{e.get('msg')}")


def check_backfill(res: dict, runs: list, stop_label: str) -> None:
    log, relay = res.get("log") or {}, res.get("relay") or {}
    for script, rid in runs:
        name = f"补记·日志 {rid}"
        if log.get("err"):
            say("读不到", name, log["err"])
            continue
        b = (log.get("backfill") or {}).get(rid) or {}
        n = b.get("count", 0)
        first = (b.get("lines") or [""])[0]
        if n == 1:
            say("过", name, f"出现 1 次：{first}")
        elif n == 0:
            say("不过", name, "relay.log 里没有这行")
        else:
            say("不过", name, f"出现 {n} 次（该恰好一次，重复 = 幂等坏了）：{first}")
    for script, rid in runs:
        name = f"补记·账本 {rid}"
        if relay.get("err"):
            say("读不到", name, relay["err"])
            continue
        if not relay.get("ledger_exists"):
            say("读不到", name, f"{relay.get('ledger_file')} 不存在")
            continue
        e = (relay.get("ledger") or {}).get(rid)
        if e is None:
            say("不过", name, f"账本里没有这趟（共 {relay.get('ledger_entries')} 条）")
        elif stop_label in str(e.get("manual_stop") or ""):
            say("过", name, f"raw.manual_stop = {e['manual_stop']}")
        else:
            say("不过", name, f"raw.manual_stop = {e.get('manual_stop')!r}，没有「{stop_label}」")
    name = "补记·日报渲染 ⏹"
    if relay.get("err") or relay.get("compose_err"):
        say("读不到", name, relay.get("err") or relay["compose_err"])
        return
    if relay.get("compose_blocked"):
        say("读不到", name, "渲染途中有动作被拦下（没执行）："
            + "、".join(relay["compose_blocked"]))
        return
    rows = relay.get("compose_rows") or {}
    anyrow = relay.get("compose_any_rows") or {}
    ok = all(rows.get(rid) for _, rid in runs)
    shown = "；".join(rows.get(rid) or f"{rid} 没有 ⏹ 行（实际：{anyrow.get(rid) or '找不到这趟'}）"
                     for _, rid in runs)
    say("过" if ok else "不过", name, f"{relay.get('compose_title')}：{shown}")


def check_wtest(args) -> None:
    name = "WaitTime 往返（--wtest）"
    script = HERE / "lib" / "waittime_roundtrip.py"
    try:
        r = subprocess.run([str(HERE / "winrun.sh"), "--py", str(script)],
                           capture_output=True, timeout=200)
    except (OSError, subprocess.SubprocessError) as exc:
        say("读不到", name, f"{type(exc).__name__}: {exc}")
        return
    got = None
    for ln in r.stdout.decode("utf-8", "replace").splitlines():
        if ln.startswith("WTEST_JSON="):
            got = json.loads(ln[len("WTEST_JSON="):])
    if got is None:
        err = (r.stderr.decode("utf-8", "replace").strip().splitlines() or ["没有输出"])[-1]
        say("读不到", name, err)
        return
    if got.get("busy"):
        say("读不到", name, "有脚本或游戏在跑，没测：" + "、".join(got["busy"]))
        return
    up, back = got.get("up") or [False], got.get("back") or [False]
    du, de, nb = got.get("diff_up") or {}, got.get("diff_end") or {}, got.get("new_bak") or []
    sid = got.get("sid", "")
    ok = bool(up[0] and back[0] and list(du) == [f"/{sid}/Game/WaitTime"] and not de and not nb)
    say("过" if ok else "不过", name,
        f"up={up} back={back} diff_up={json.dumps(du, ensure_ascii=False)} "
        f"diff_end={json.dumps(de, ensure_ascii=False)} new_bak={nb}")


def main() -> int:
    p = argparse.ArgumentParser(description="09-30 晚开机检查（只读；--wtest 除外）")
    p.add_argument("--since", default="21:00",
                   help="ntfy 窗口起点：21:00（北京今天）/ 30m / 12h / unix 时间戳；默认 21:00")
    p.add_argument("--want-version", default="20260930024646")
    p.add_argument("--day", default="2026-09-30", help="账本与日志那一天（北京）")
    p.add_argument("--runs", default="OK-WW:OK-WW-05-40-56,MaaEnd:MaaEnd-05-46-45",
                   help="要看 ⏹ 补记的趟：脚本:run_id,…")
    p.add_argument("--stop-label", default="09:46 停一切")
    p.add_argument("--wtest", action="store_true",
                   help="另跑 MaaEnd WaitTime +1 再改回（唯一会改配置的一项，默认不跑）")
    p.add_argument("--host", default=os.environ.get("ARK_HOST", "100.65.39.119"))
    p.add_argument("--local-relay", default="", help=argparse.SUPPRESS)
    p.add_argument("--remote-json", default="", help=argparse.SUPPRESS)
    args = p.parse_args()
    runs = [tuple(x.split(":", 1)) for x in args.runs.split(",") if ":" in x]
    offline_test = bool(args.local_relay or args.remote_json)

    up = True
    if not offline_test:
        up = online(args.host)
        say("过" if up else "不过", "机器在线", f"{args.host}:22 " + ("通" if up else "8 秒内连不上"))
    check_ntfy(args.since)
    if not up:
        print("机器不在线：上机各项没跑")
        print(f"汇总：过 {COUNTS['过']} · 不过 {COUNTS['不过']} · 读不到 {COUNTS['读不到']}")
        return 2

    res, err = run_reader(args)
    if res is None:
        for n in (f"自更新版本 {args.want_version}", "10:12 失踪", "补记"):
            say("读不到", n, f"机器上的读数没拿到：{err}")
    else:
        print(f"（机器读数：{res.get('root')}；日志 {(res.get('log') or {}).get('file')}；"
              f"状态 {(res.get('relay') or {}).get('state_dir')}；被拦动作 {len(res.get('blocked') or [])}）")
        check_version(res, args.want_version)
        report_vanish(res)
        check_backfill(res, runs, args.stop_label)
    say("说明", "跳过回执", "没按跳过就没什么可看；逻辑由 relay/tests/test_skip_receipts.py 覆盖")
    if args.wtest and not offline_test:
        check_wtest(args)
    else:
        say("说明", "WaitTime 往返", "没跑（加 --wtest 才跑：把 MaaEnd 的 WaitTime 改 +1 再改回）")
    print(f"汇总：过 {COUNTS['过']} · 不过 {COUNTS['不过']} · 读不到 {COUNTS['读不到']}"
          f"（另有读数 {COUNTS['读数']} 行、说明 {COUNTS['说明']} 行）")
    return 0 if COUNTS["不过"] == 0 and COUNTS["读不到"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
