"""daysim: the World - everything outside the relay, replayed from one day's record.

Design: design.md sections 1-2. The World lives inside each boot process
(boot.py): the fakes of W2/W3 call its hooks and it drives them from
`days/<D>/events.jsonl`. run.py only orchestrates (plan_boots, materialize).

Design notes - where the units' interfaces meet, decided once here
------------------------------------------------------------------
* Scheduler adapter (`Sched`). W1's simclock is the scheduler. W2 calls
  `sched.kick()` and W3 `sched.wake()` after a signal: both are simclock.poke.
  W2 writes `out("sim_errors", ...)` and W3 `out("sim_error", ...)`: both become
  kind "sim_error" (simclock.sim_errors() filters that one). W3's extra kinds
  `sim_note` and `mas_backend` are kept and land in outputs.json under
  `sim_notes` / `mas_backend` (the oracle ignores keys it does not read). Every
  fake passes its own `t=`; simclock's out() lets a passed `t` win.
* Fakes are built before simclock.install() (boot.py). W1's park(ready) runs
  `ready()` under the scheduler's own lock and forbids blocking there; W3's
  NtfyStream ready() takes FakeNet._lock. Built before install, that lock is a
  real (non-sim) RLock, held only for a list copy, never across a scheduler call.
* Directory watches: nothing watches the disk (W2 point 4); every World file
  drop, append or rename calls FakeWin.files_changed(path).
* sys.path: fake_win imports fake_proc as a sibling (W2 point 5); boot.py puts
  this folder on sys.path first.
* The PowerShell 7 check (W2 point 6): preupdate_common._PWSH7 is
  Path(r"C:\\Program Files\\PowerShell\\7\\pwsh.exe"); on POSIX that is a
  relative file name with backslashes in it, resolved against the working
  directory. The World plants that file in the relay's working directory (the
  data folder, as app_main.run chdirs there), so "PowerShell 7 is installed",
  as it is on the machine. No relay code is changed for it.
* ARK_PROGRAMDATA is in the boot process's environment before the relay is
  imported (W0: the ProgramData constants are built at import).
* simclock.stop() (W1): boot.py writes its outputs and leaves with os._exit;
  the relay's own 15 s hard exit (service.SvcStop's Timer, sim time) is routed
  through the same writer, so outputs are never lost to it.
* Code under test: a copy of relay/ (no tests/, no .env) in the sim tree, with
  `state` linked to the sim state folder, as app_main links the version folder's
  state on the machine. selfupdate reads versions.code from <code>/state, and
  nothing writes into the worktree.
* Frozen code (design.md section 1): FakeNet's COS latest.json carries the
  seeded state's versions.code, so the self-update finds the machine current.
* Phone orders: the relay log only keeps the result line, so W4's `args` are
  read back from it. The body sent is the phone page's own (web/schema.js:254-259:
  debug_mode on {minutes:90, confirmed}, off {off:true, confirmed}; skip_shutdown
  on {}, off {off:true}); echo_farm's boss and end time are read from its
  result line. Inbox files are rebuilt the way scripts/mac/order.sh writes them
  (version, name, note 「从电脑发来的指令：<name>」, commands from its ZH table).
* Power: a recorded relay power-off (relay_stop.relay_poweroff) is the relay's
  own output. When the relay's countdown runs out the World shuts Windows down
  (FakeMas killed, SvcShutdown). When the relay does not power off where the
  record did, the World still powers off at the recorded time (the machine was
  off until the next power_on) and writes a sim_note. A relay power-off the
  record does not have is an output only: the machine stays on as it really
  did (design.md "Divergence").
* Boot 0 of a day the machine was already on at 00:00 (10-06): the relay is
  started fresh at t0, so its boot stages run once more than on the machine.
* The programs' own files (install.py): AUTO-MAS's master copies under data/<uid>/,
  MaaEnd's install, OK-WW's configs and app.json, MAA's resource/tasks and a stub
  app.asar are planted after the seed, from the corpus's `_install/` (a day refuses to
  start without it). They are the machine's as of 10-13; the master's 「Only Farm These
  Nests」 is the day's (MASTER_NESTS).
* Outside services the relay reads once a Skland token is set (web_routes): Skland
  answers in the shapes skland.py reads with the record's stamina, the Endfield banner
  sources from the repo's recorded copies.
* OK-WW's own doings the record shows: its pre-update launch rewrites app.json
  (_okww_preupdate) and its start writes the overrides' report (_overlay_report).
* Inputs the pull cannot show (days/<D>/outside.jsonl, hand-written, each with a
  checkable `src` and a `why`): `state_edit` - a person or a session changing the
  relay's state.json directly (the 「下次跑完不关机」 mark or debug mode set with no
  relay.log line); `web` - an official site's answer from `t` on (a maintenance
  bulletin; design.md section 2: "hand-written per-day answers for known events").
  load_day merges them into the day's events; the slicer never writes this file.
* A recorded WMI drop is delivered as OnCompleted(0x800706BE) with the WMI service
  restarted inside the same pump (fake_win.drop_wmi `before`), the order the record's
  drop line and #59's diag show.
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.util
import json
import os
import re
import shutil
import sys
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import install

HERE = Path(__file__).resolve().parent
RELAY = HERE.parents[1]
DAYS = HERE / "days"
# DAYSIM_CORPUS: another corpus root (CI unpacks the light packs there; pack.py).
CORPUS_ROOT = install.CORPUS_ROOT
BJ = timezone(timedelta(hours=8))

DATA_REL = "C/ProgramData/ark-relay"         # the relay's data folder on the machine
AUTOMAS_REL = "D/ark/automas"
PHONE_TOPIC = "daysim-never-published-topic"
PHONE_PIN = "daysim-pin"
# Placeholders that cannot reach anything even if a guard failed: the .invalid TLD
# never resolves (RFC 2606), and fake_net answers these in process.
ALERT_URL = "http://daysim.invalid:8931/alert"
INBOX_URL = "https://raw.githubusercontent.com/herclyon1/maa/main/queue/config.json"
BACKEND_CMD = r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"
SHELL_EXE = r"D:\ark\automas\AUTO-MAS.exe"
PWSH7_NAME = r"C:\Program Files\PowerShell\7\pwsh.exe"
# A recorded relay power-off (relay_stop.relay_poweroff) counts as the one the relay's
# own countdown ends in when the two are this close: the countdown is 60 s
# (engine._power_off), the record's stop line follows it within a minute or two.
POWEROFF_MATCH_S = 600
# Program files the pull does not carry, from the repo's recorded copies (each fixture
# says where and when it was copied): AUTO-MAS's app/models/config.py, copied from the
# machine 2026-10-12 (tests/test_mas_labels.py docstring), which mas_labels reads.
INSTALL_COPIES = {
    "D:/ark/automas/app/models/config.py": RELAY / "tests" / "fixtures" / "automas-models" / "config.py.txt",
}
# Program files whose content the record states in words: relay.log 10-12 08:46:08
# 「res/version.json 还写着 v5.5.0-beta.2，新版不再改那个文件」 (preupdate_automas reads it
# before it asks the backend).
INSTALL_TEXTS = {
    "D:/ark/automas/res/version.json": json.dumps({"version": "v5.5.0-beta.2"}) + "\n",
}
# How long before the relay's recorded read an inbox file is put in place. The relay
# reads it at boot (boot_stages._make_collect) and before a power-off; the record's
# 「待办」 line stamps the read to the second and order.sh writes before it, at an
# unknown earlier time. A minute keeps a read at the start of the next minute from
# missing it without moving it into an earlier boot (10-12 08:46:07, 12:10:31).
INBOX_LEAD_S = 60
# maaend_watchdog.PLUGINS's comment: both plugins start "~16 s after MaaEnd".
MAAEND_PLUGIN_DELAY_S = 16
# scripts/mac/order.sh ZH: the inbox file's "name" from its commands.
ORDER_ZH = {"set_master": "改脚本自己的设置", "set_config": "改设置", "debug_mode": "调试模式",
            "skip_shutdown": "下次跑完不关机", "run_now": "现在跑一趟", "skip_today": "跳过一趟",
            "weekly_boss": "改打第几个周本", "estop": "停止一切",
            "echo_farm": "开始刷 4C 声骸", "echo_farm_stop": "刷声骸收工",
            "echo_farm_until": "改刷声骸的收工时刻", "monthcard": "登记月卡"}
ZH_ORDER = {v: k for k, v in ORDER_ZH.items()}
# The master's 「Only Farm These Nests」 at the day's start (install.set_nests), as the
# overrides logged it 「（设置来自母本）」 in the day's #26 line. It was changed from the
# Mac 10-12 11:2x (mastercfg_okww.OKWW_READONLY), which no day records as an input.
MASTER_NESTS = {
    "2026-10-06": ("落渊南丘", "relay.log 10-06 09:28:13 #26: 只刷 ['落渊南丘']（设置来自母本）"),
    "2026-10-12": ("落渊南丘", "relay.log 10-12 10:04:11 #26: 只刷 ['落渊南丘']（设置来自母本）"),
    "2026-10-13": ("梦枢天罗,落渊南丘", "relay.log 10-13 09:36:59 #26: 只刷 ['梦枢天罗', '落渊南丘']（设置来自母本）"),
}
# When OK-WW rewrites app.json after it is launched. Measured on the machine's own copy
# (install.py's u0 read, 2026-10-13): app.json's last_start 03:07:04.9Z (11:07:04.9
# Beijing) and its mtime 11:07:42, so 38 s. The relay's verdict waits
# preupdate_okww.OKWW_MIN_WAIT_SECONDS (45) anyway: the record has the launch
# (10-12 08:46:17) and 「无需更新（v3.7.4）」 45 s later (08:47:02).
OKWW_APPJSON_REWRITE_S = 38
# mailbox.Mailbox.POST_TIMEOUT: an ntfy publish that timed out began this long before
# its 「发到信箱没成」 line.
NTFY_POST_TIMEOUT_S = 20
# OK-WW loads the relay's overrides at start (ok-script log 「task_manager:Found tasks:
# [...ark_overrides.py]」) and they write C:\ProgramData\ark-okww-overlay.json then
# (ark_overrides.tasks.py _write_report): 10-12 09:19:07.833 in the log, 「覆盖层报告
# （09:19:07 写）」 in the relay's #26 line.
OVERRIDES_LOADED = re.compile(rb"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO \S+ task_manager:Found tasks: "
                              rb".*ark_overrides\.py", re.M)


def epoch(s) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    return datetime.fromisoformat(s).timestamp()


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, BJ).isoformat(timespec="seconds")


# ------------------------------------------------------------------ the day's plan

def load_day(day: str) -> tuple[list[dict], dict]:
    d = DAYS / day
    events = [json.loads(x) for x in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    events += load_outside(day)          # timeline() puts them in time order
    seed = json.loads((d / "seed.json").read_text(encoding="utf-8"))
    return events, seed


OUTSIDE_KINDS = ("state_edit", "web")


def load_outside(day: str) -> list[dict]:
    """days/<D>/outside.jsonl: the inputs the pull cannot show (module docstring)."""
    f = DAYS / day / "outside.jsonl"
    if not f.is_file():
        return []
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


def timeline(events: list[dict]) -> list[dict]:
    """Every input as one item at its time; a run becomes run_start and run_end.
    Each item has a stable index `i` (applied-set key across boot processes)."""
    items = []
    for n, ev in enumerate(events):
        if ev["kind"] == "run":
            items.append({"t": epoch(ev["start"]), "n": n, "sub": 0, "kind": "run_start", "ev": ev})
            items.append({"t": epoch(ev["end"]), "n": n, "sub": 1, "kind": "run_end", "ev": ev})
        elif ev["kind"] == "inbox":
            # The record holds when the relay read the inbox file (its 「待办」 lines), not
            # when scripts/mac/order.sh wrote it, which was earlier: the file is put in
            # place INBOX_LEAD_S before the read, so the relay's own read finds it.
            t = min(epoch(ev["t"]), epoch(ev.get("received") or ev["t"])) - INBOX_LEAD_S
            items.append({"t": t, "n": n, "sub": 0, "kind": "inbox", "ev": ev})
        elif ev["kind"] not in ("relay_start", "relay_stop"):
            items.append({"t": epoch(ev["t"]), "n": n, "sub": 0, "kind": ev["kind"], "ev": ev})
    items.sort(key=lambda x: (x["t"], _order(x), x["n"], x["sub"]))
    for i, it in enumerate(items):
        it["i"] = i
    return items


# At one recorded second: the AUTO-MAS task opens, then programs start, then the run
# starts; the run ends, then programs exit, then the task closes (app.log order).
_ORDER = {("mas_backend", "up"): 0, ("mas_backend", "task_start"): 1, ("proc", "start"): 2, ("run_start", None): 3,
          ("run_end", None): 5, ("proc", "exit"): 6, ("mas_backend", "task_end"): 7, ("mas_backend", "down"): 8}


def _order(it: dict) -> int:
    return _ORDER.get((it["kind"], it["ev"].get("op") if it["kind"] in ("mas_backend", "proc") else None), 4)


def plan_boots(events: list[dict], seed: dict, until: "float | None" = None) -> list[dict]:
    """The relay's lives this day: each relay_start up to its relay_stop."""
    t1 = epoch(seed["t1"])
    end_of_day = min(t1, until) if until else t1
    starts = sorted((e for e in events if e["kind"] == "relay_start"), key=lambda e: epoch(e["t"]))
    stops = sorted((e for e in events if e["kind"] == "relay_stop"), key=lambda e: epoch(e["t"]))
    ons = sorted(epoch(e["t"]) for e in events if e["kind"] == "power_on")
    machine = seed.get("machine") or {}
    starts = [{"t": seed["t0"], "after": "running_at_t0", "version": machine.get("relay_version", ""),
               "src": machine.get("src", "")}] * (machine.get("relay") == "running") + starts
    boots = []
    for i, s in enumerate(starts):
        ts = epoch(s["t"])
        if ts >= end_of_day:
            break
        nxt = epoch(starts[i + 1]["t"]) if i + 1 < len(starts) else end_of_day
        stop = next((e for e in stops if ts <= epoch(e["t"]) <= nxt), None)
        end, how = (epoch(stop["t"]), stop["how"]) if stop else (min(nxt, end_of_day), "day_end")
        if end > end_of_day:
            end, how = end_of_day, "day_end"
        on = max((x for x in ons if x <= ts), default=None)
        if on is None:
            on = epoch(machine["relay_started"]) - 60 if machine.get("relay_started") else ts - 60
        boots.append({"i": len(boots), "start": ts, "end": end, "how": how, "power_on": on,
                      "after": s.get("after", ""), "version": s.get("version", ""),
                      "relay_poweroff": bool(stop and stop.get("relay_poweroff")),
                      "src_start": s.get("src", ""), "src_stop": (stop or {}).get("src", "")})
    return boots


# ------------------------------------------------------------------ the sim tree

def tpath(tree: Path, machine_path: str) -> Path:
    """C:/ProgramData/x or D:\\ark\\x -> <tree>/C/ProgramData/x."""
    p = machine_path.replace("\\", "/")
    drive, _, rest = p.partition(":")
    return tree / drive.upper() / rest.lstrip("/")


_LIBC: list = []


def clone(src: Path, dst: Path) -> None:
    """APFS clonefile (no data copied: the disk is nearly full); a plain copy elsewhere."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if sys.platform != "darwin":         # clonefile is macOS's; Windows CI has no libc to load
        shutil.copyfile(src, dst)
        return
    if not _LIBC:
        _LIBC.append(ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True))
    fn = getattr(_LIBC[0], "clonefile", None)
    if fn is None or fn(os.fsencode(src), os.fsencode(dst), 0) != 0:
        shutil.copyfile(src, dst)


def corpus_file(corpus: Path, entry: dict) -> Path:
    rel = entry.get("file") or "files/" + entry["path"].replace(":", "", 1)
    return corpus / rel


def assert_offline(net) -> None:
    """Refuse to go on unless every network door is FakeNet's (a boot that ran
    without it once reached ntfy.sh, WeCom and Server酱 for real)."""
    import socket  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415
    doors = (urllib.request.urlopen, urllib.request.build_opener, socket.socket.connect, socket.create_connection)
    if not all(getattr(d, "__self__", None) is net for d in doors):
        raise SystemExit("daysim: the network fakes are not installed; refusing to start the relay")


def env_for(tree: Path) -> dict:
    data = tree / DATA_REL
    am = tree / AUTOMAS_REL
    return {
        "TZ": "Asia/Shanghai",
        "ARK_HOME": str(data), "ARK_LOG_FILE": str(data / "relay.log"), "ARK_STATE_DIR": str(data / "state"),
        "ARK_PROGRAMDATA": str(tree / "C" / "ProgramData"),
        "ARK_AUTOMAS_DIR": str(am), "ARK_HISTORY_DIR": str(am / "history"),
        "ARK_MAA_DIR": str(tree / "D/ark/maa"), "ARK_MAAEND_DIR": str(tree / "D/ark/maaend"),
        "ARK_OKWW_DIR": str(tree / "D/ark/okww"),
        "ARK_POLL_SECONDS": "30",                 # relay.log 10-12 09:12:43 「兜底 30 秒」
        "ARK_SHUTDOWN_AFTER_RUN": "1",
        "ARK_PHONE_TOPIC": PHONE_TOPIC, "ARK_PHONE_PIN": PHONE_PIN,
        "ARK_INBOX_URL": INBOX_URL, "ARK_ALERT_PUSH_URL": ALERT_URL,
        # Placeholders: every request is answered in process (fake_net); nothing real.
        "WECOM_BOT_URL": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=DAYSIM",
        "SERVERCHAN_KEY": "SCTdaysim",
        "COS_SECRET_ID": "daysim", "COS_SECRET_KEY": "daysim", "COS_BUCKET": "daysim-1250000000",
        "COS_REGION": "ap-shanghai",
        "SKLAND_TOKEN": "daysim",                 # answered by the World's Skland (skland_routes)
    }


def materialize(day: str, tree: Path, corpus: Path, code_src: Path) -> dict:
    """The machine at D 00:00 (seed.json), plus the code under test, in `tree`."""
    events, seed = load_day(day)
    if tree.exists():
        shutil.rmtree(tree)
    for f in seed["files"]:
        src, dst = corpus_file(corpus, f), tpath(tree, f["path"])
        clone(src, dst)
        if "len" in f:
            os.truncate(dst, int(f["len"]))
        mt = epoch(f["mtime"])
        os.utime(dst, (mt, mt))
    for sub in ("D/ark/automas/history", "D/ark/automas/config", "D/ark/maa/debug", "D/ark/maaend/debug",
                "D/ark/okww", DATA_REL + "/state"):
        (tree / sub).mkdir(parents=True, exist_ok=True)
    install_code(tree, code_src)
    for rel, src in INSTALL_COPIES.items():
        dst = tpath(tree, rel)
        if not dst.exists() and src.is_file():
            clone(src, dst)
    for rel, data in INSTALL_TEXTS.items():
        dst = tpath(tree, rel)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(data, encoding="utf-8")
    t0 = epoch(seed["t0"])
    if (lines := t0_stop_lines(seed)) and (log := tpath(tree, DATA_REL + "/relay.log")).is_file():
        with open(log, "ab") as f:
            f.write(lines.encode("utf-8"))
        os.utime(log, (t0, t0))
    missing = install.plant(tree, t0, automas_rel=AUTOMAS_REL, clone=clone, nests=MASTER_NESTS.get(day, ("", ""))[0])
    if missing:
        raise SystemExit(f"daysim: {len(missing)} install copies missing under {install.ROOT} "
                         f"(install.py build), e.g. {missing[0]}")
    install.asar_stub(tree, AUTOMAS_REL, DATA_REL + "/state")
    sim = tree / "_sim"
    sim.mkdir(exist_ok=True)
    (sim / "world.json").write_text(json.dumps({"applied": []}), encoding="utf-8")
    return seed


def t0_stop_lines(seed: dict) -> str:
    """relay.log lines for the stop at 00:00 the sim makes when the relay was running
    then: the sim cannot carry a process over midnight, so the day's first boot starts a
    new one, and the one before it must end as a stop does (service.SvcStop's notice,
    then the state push the stop sends, as relay.log 10-11 12:26:42 / :44 have them).
    Chain mode gets the same from the previous day's own day_end SvcStop. Without them
    #11 judges the session before as one that vanished with no stop notice (10-11
    00:00:49: the record's relay ran from 10-10 23:38:46 to 04:08:17)."""
    machine = seed.get("machine") or {}
    if machine.get("relay") != "running":
        return ""
    at = datetime.fromisoformat(seed["t0"]).astimezone(BJ).strftime("%m-%d %H:%M:%S")
    return (f"{at} INFO    ark.service  收到停止通知（停止中继）\n"
            f"{at} INFO    ark.service  📱 已上报状态到手机（停止前；daysim 在 00:00 把中继停下再开）\n")


def install_code(tree: Path, code_src: Path) -> Path:
    code = tree / "_sim" / "code"
    if code.exists():
        shutil.rmtree(code)
    shutil.copytree(code_src, code, ignore=shutil.ignore_patterns(
        "tests", "state", ".env", "__pycache__", "*.pyc", "relay.log"))
    (code / "state").symlink_to(tree / DATA_REL / "state", target_is_directory=True)
    data = tree / DATA_REL
    data.mkdir(parents=True, exist_ok=True)
    for name in windows_programs(tree):
        (data / name).write_bytes(b"")            # see the module docstring
    return code


def windows_programs(tree: Path) -> list[str]:
    """Program files the relay checks by their Windows path (module docstring, "The
    PowerShell 7 check"): PowerShell 7, and every .exe the recorded AUTO-MAS
    ScriptConfig.json names (AUTO-MAS starts them from there, so they exist)."""
    names = [PWSH7_NAME]
    cfg = tree / AUTOMAS_REL / "config" / "ScriptConfig.json"
    try:
        text = cfg.read_text(encoding="utf-8-sig")
    except OSError:
        return names
    for m in re.finditer(r'"Path":\s*"((?:[^"\\]|\\.)*\.exe)"', text, re.I):
        names.append(json.loads(f'"{m.group(1)}"'))
    return names


def pillow_site(tree: Path) -> "Path | None":
    """The relay's runtime has Pillow (relay/requirements.txt). `python3.14 -I` hides the
    user site where this Mac has it, so a folder holding only a link to PIL is put on
    the path; nothing else from that site becomes importable. None when it is absent
    (the boot self-check then says Pillow is missing, as it would on the machine)."""
    import site  # noqa: PLC0415
    user = Path(site.getusersitepackages())
    if not (user / "PIL" / "__init__.py").is_file():
        return None
    d = tree / "_sim" / "pil-site"
    if not (d / "PIL").exists():
        d.mkdir(parents=True, exist_ok=True)
        (d / "PIL").symlink_to(user / "PIL", target_is_directory=True)
    return d


# ------------------------------------------------------------------ the World in a boot process

class Sched:
    """W1's simclock with the names W2 and W3 call (module docstring)."""

    def __init__(self, sc):
        self.sc = sc
        self.now, self.at, self.park, self.advance = sc.now, sc.at, sc.park, sc.advance

    def out(self, kind: str, **f):
        kind = {"sim_errors": "sim_error"}.get(kind, kind)
        return self.sc.out(kind, **f)

    def kick(self) -> None:
        self.sc.poke()

    wake = poke = kick


class World:
    def __init__(self, sched, *, day: str, tree: Path, corpus: Path, boot: dict, fakes):
        self.sched = sched
        self.day, self.tree, self.corpus, self.boot = day, tree, corpus, boot
        self.win, self.fw, self.router, self.net, self.mas, self.desk = fakes
        self.events, self.seed = load_day(day)
        self.items = timeline(self.events)
        self.state_file = tree / "_sim" / "world.json"
        st = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.applied = set(st.get("applied") or [])
        self.net.ntfy_count.update(st.get("ntfy_count") or {})
        self.cos_dir = tree / "_sim" / "cos"
        for f in self.cos_dir.glob("*") if self.cos_dir.is_dir() else []:
            self.net.cos[urllib.parse.unquote(f.name)] = f.read_bytes()
        # FakeNet numbers ids from 1 in every process; the relay keeps the ids it has
        # handled across boots and days, so each boot process starts its own range.
        self.net._ids = int(boot["start"]) % 10**8 * 10
        self.tasks: list[dict] = []
        self._versions: "list[tuple[float, str]] | None" = None
        self.host = None
        self.stopping = False
        self.powered_off = False
        self.lock = threading.Lock()       # built before simclock.install: a real lock
        self.win.on_task_run = self._task_run
        self.win.on_spawn = self._spawn
        self.win.on_power_off = self._power_off
        self.stamina = recorded_stamina(self.corpus, self.seed, day)
        for prefix, answer in web_routes(self.sched.now, self.stamina).items():
            self.net.set_web(prefix, answer)

    # -------- helpers
    def note(self, what: str, **f) -> None:
        self.sched.out("sim_note", t=iso(self.sched.now()), what=what, **f)

    def error(self, what: str, **f) -> None:
        self.sched.out("sim_error", t=iso(self.sched.now()), what=what, **f)

    def tp(self, p: str) -> Path:
        return tpath(self.tree, p)

    def changed(self, p: Path) -> None:
        self.fw.files_changed(p)

    def stamp(self, p: Path, t: float) -> None:
        os.utime(p, (t, t))

    # -------- set-up before the relay starts
    def prepare(self) -> None:
        """Power-on baseline, then every input up to the boot's start: state for all of
        them (process table, AUTO-MAS, ntfy), disk effects for those no earlier boot
        process applied.

        Inputs from before this boot's power-on are replayed first: they belong to an
        earlier power cycle, and a recorded power-off among them would otherwise end
        the AUTO-MAS window this power-on starts (10-11 08:45: the 04:08 shutdown left
        the relay finding no AUTO-MAS.exe, where the machine said 「窗口已在、接口还没开」).
        Whatever they left running is gone at power-on, also after a relay power-off
        (an output, so no power_off input ends it)."""
        b = self.boot
        past = [it for it in self.items if it["t"] <= b["start"]]
        earlier = [it for it in past if it["t"] < b["power_on"]]
        self._replay(earlier)
        if earlier:
            self._all_down(b["power_on"])
        self.win.add_baseline(b["power_on"])
        self._shell_up(b["power_on"])
        machine = self.seed.get("machine") or {}
        if machine.get("power") == "on" and b["start"] <= epoch(self.seed["t0"]) + 1:
            self._backend_up(b["power_on"], restore=False)
            self.note("machine on at 00:00: AUTO-MAS backend assumed up", src=machine.get("src", ""))
        self._replay(past[len(earlier):])

    def _replay(self, items: list) -> None:
        for it in items:
            self.state_effect(it, live=False)
            if it["i"] not in self.applied:
                self.disk_effect(it)
                self.applied.add(it["i"])

    def automas_version(self, at: float) -> str:
        """AUTO-MAS's own version at `at`, as its app.log names it (the backend's start
        banner 「版本号:  v5.6.2」, the update check's current_version=...): the last one
        stamped by then; before the day's first, the seeded app.log's last, else the
        day's first; "" when there is none. 10-09: v5.6.2 until AUTO-MAS installed
        v5.7.0-beta.1 and its backend came back at 08:47:54."""
        if self._versions is None:
            self._versions = []
            for ev in self.events:
                if ev["kind"] == "log_chunk" and ev["path"].endswith("/automas/debug/app.log"):
                    with open(self.corpus / ev["file"], "rb") as f:
                        f.seek(int(ev["off"]))
                        self._versions += _app_versions(f.read(int(ev["len"])))
            self._versions.sort(key=lambda x: x[0])
        got = [v for t, v in self._versions if t <= at]
        if got:
            return got[-1]
        app = self.tp("D:/ark/automas/debug/app.log")
        seeded = _app_versions(app.read_bytes()[-(4 << 20):]) if app.is_file() else []
        seeded = [v for t, v in seeded if t <= at]
        return seeded[-1] if seeded else self._versions[0][1] if self._versions else ""

    def desktop_spawn(self, orig):
        """FakeDesktop's agent start, plus the picture a "shot" request asks for. The
        machine's agent wrote one for every such request (state/shots/<day>/ holds the
        day's run folders); the pull has no pixels, so the picture is a 1x1 PNG."""
        def spawn(exe, cwd, args):
            ok = orig(exe, cwd, args)
            try:
                req = json.loads(Path(args[-2]).read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return ok
            shot = req.get("shot")
            if shot and any(a.get("act") == "shot" for a in req.get("actions") or []):
                dst = Path(shot) if not shot[1:3] == ":\\" else self.tp(shot)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(PNG_1X1)
                self.note("desktop shot answered with a placeholder picture", shot=str(dst.name))
            return ok
        return spawn

    def schedule(self, host) -> None:
        self.host = host
        b = self.boot
        for it in self.items:
            if b["start"] < it["t"] <= b["end"]:
                self.sched.at(it["t"], lambda it=it: self._live(it), it["kind"])
        self.sched.at(b["end"], self._end_boot, "boot-end")

    def _live(self, it) -> None:
        if self.stopping:
            return
        self.state_effect(it, live=True)
        self.disk_effect(it)
        self.applied.add(it["i"])

    # -------- state: what lives only in this process (rebuilt each boot)
    def state_effect(self, it, *, live: bool) -> None:
        k, ev, t = it["kind"], it["ev"], it["t"]
        if k == "proc":
            op = ev.get("op")
            if op == "start":
                path = ev.get("path") or ev["image"]
                p = self.win.procs.start(ev["image"], f'"{path}"', exe=ev.get("path", ""), t=t)
                if ev["image"].lower() == "maaend.exe":
                    self._maaend_plugins(p, t, live)
            elif op == "exit":
                alive = [p for p in self.win.procs.named(ev["image"])]
                if alive:
                    for c in self.win.procs.children(alive[-1].pid):
                        self.win.procs.end(c.pid, 0, t)
                    self.win.procs.end(alive[-1].pid, 0, t)
            elif op == "wmi_subscription_lost" and live:
                # The sink hears 0x800706BE (OnCompleted) with the WMI service already
                # restarted, as the record has it: the drop line says 「远程过程调用失败，
                # 0x800706BE」 (relay.log 10-06 16:16:59) and its diag the restart (#59 at
                # 16:43:45: 「原因：WMI 服务自己重启过」). Restarting winmgmt first instead
                # would end the wait on the old host's handle (「系统里发这项通知的服务停了」).
                if not self.fw.drop_wmi(before=lambda t=t: self._winmgmt_restart(t)):
                    self._winmgmt_restart(t)
        elif k == "mas_backend":
            op = ev.get("op")
            if op == "up":
                self._backend_up(t, restore=not live)
            elif op == "down":
                self._backend_down(t)
            elif op == "task_start":
                self.tasks.append({"taskId": ev.get("task", ""), "mode": ev.get("mode", ""), "task_info": []})
                self.mas.set_tasks(self.tasks)
                if live:
                    self.mas.run_started()
            elif op == "task_end":
                self.tasks = [x for x in self.tasks if x["taskId"] != ev.get("task")]
                self.mas.set_tasks(self.tasks)
            else:
                self.note("mas_backend op not modelled", op=op, src=ev.get("src"))
        elif k in ("run_start", "run_end"):
            self._run_status(ev, "运行" if k == "run_start" else "完成")
        elif k == "power_off":
            # Live, the boot's end shuts Windows down (SvcShutdown first, as Windows tells
            # services before it ends processes); here only a past power-off is replayed.
            if not live:
                self._all_down(t)
        elif k == "power_on":
            pass        # boot.power_on already set GetTickCount64's origin
        elif k == "phone_order":
            self._phone(ev)
        elif k == "web":
            self.net.set_web(ev["prefix"], ev["answer"])
        elif k == "inbox":
            self._inbox(ev, live)

    def _winmgmt_restart(self, t: float) -> None:
        """The recorded drop (0x800706BE, RPC failed) as the machine had it: the WMI
        service restarted itself - the relay's own diagnosis in the record, 10-06
        16:43:45 / 18:23:38 「原因：WMI 服务自己重启过」. winmgmt gets a new process (a new
        PID, wmi_diag's H1) and the System log the SCM's two 7036 lines (the service
        named in <Binary> as UTF-16LE 「winmgmt/N」, wmi_diag._scm_winmgmt)."""
        svc = self.win.services.get("winmgmt")
        if svc is None:
            return
        self.win.procs.end(svc["pid"], 0, t)
        host = self.win.procs.start("svchost.exe", r"C:\WINDOWS\system32\svchost.exe -k netsvcs -p -s Winmgmt",
                                    exe=r"C:\WINDOWS\system32\svchost.exe", session=0, t=t)
        svc["pid"] = host.pid
        for dt, state, n in ((-1, "已停止", 1), (0, "正在运行", 4)):
            self.win.log_event(t + dt, 7036, "Service Control Manager",
                               {"param1": "Windows Management Instrumentation", "param2": state},
                               binary_hex=f"winmgmt/{n}".encode("utf-16-le").hex().upper())
        self.note("WMI service restarted (recorded drop)", winmgmt_pid=host.pid)

    def _maaend_plugins(self, parent, t: float, live: bool) -> None:
        """MaaEnd's two agent plugins (maaend_watchdog.PLUGINS: <maaend>\\agent\\, started
        about 16 s after MaaEnd). app.log does not record them; without them the relay's
        watchdog reads every MaaEnd run as hung."""
        agent = self.tree / "D/ark/maaend/agent"

        def start() -> None:
            if parent.alive:
                for name in ("go-service.exe", "cpp-algo.exe"):
                    self.win.procs.start(name, f'"{agent / name}"', exe=str(agent / name), parent=parent.pid,
                                         t=self.sched.now())
        when = t + MAAEND_PLUGIN_DELAY_S
        if live and when > self.sched.now():
            self.sched.at(when, start, "maaend-plugins")
        elif self.sched.now() >= when or not live:
            start()

    def _shell_up(self, t: float) -> None:
        if not self.win.procs.named("AUTO-MAS.exe"):
            self.win.procs.start("AUTO-MAS.exe", f'"{SHELL_EXE}"', exe=SHELL_EXE, t=t)

    def _backend_up(self, t: float, *, restore: bool) -> None:
        self._shell_up(t)
        self.mas.version = self.automas_version(t) or self.mas.version
        if restore and (self.mas.shadow / "config" / "QueueConfig.json").is_file():
            # The backend started in an earlier boot process: its memory is the shadow tree.
            self.mas.up, self.mas.dead_at = True, None
            for name in ("ScriptConfig.json", "Config.json", "QueueConfig.json"):
                f = self.mas.shadow / "config" / name
                if f.is_file():
                    self.mas._disk[name] = f.read_bytes()
            self.mas._mode()
        else:
            self.mas.start()
        if not any("main.py" in p.cmdline for p in self.win.procs.named("python.exe")):
            self.win.procs.start("python.exe", BACKEND_CMD, exe=BACKEND_CMD.split(" ")[0], t=t)

    def _backend_down(self, t: float) -> None:
        self.mas.stop()
        for p in self.win.procs.named("python.exe"):
            if "main.py" in p.cmdline:
                self.win.procs.end(p.pid, 0, t)

    def _all_down(self, t: float) -> None:
        self.mas.stop()
        self.tasks = []
        self.mas.set_tasks([])
        for p in self.win.procs.alive():
            self.win.procs.end(p.pid, 0, t)

    def _run_status(self, ev: dict, status: str) -> None:
        script = ev.get("script", "")
        task = self.tasks[-1] if self.tasks else None
        if task is None:
            if status == "运行":
                self.note("run outside any AUTO-MAS task", run=ev.get("stem"))
            return
        info = task["task_info"]
        item = next((x for x in info if x.get("name") == script and x.get("status") != "完成"), None)
        if item is None:
            info.append({"name": script, "status": status})
        else:
            item["status"] = status
        self.mas.set_tasks(self.tasks)

    def _phone(self, ev: dict) -> None:
        body = phone_body(ev)
        if body is None:
            self.note("phone order not rebuilt", action=ev.get("action"), src=ev.get("src"))
            return
        sent = int(epoch(ev.get("sent") or ev["t"]))
        # The recorded ntfy id: the same message in every boot process and across days,
        # as on ntfy, so the relay's own seen-list (mailbox.py) recognises it.
        if ev.get("id"):
            self.net.next_id = lambda: str(ev["id"])
        try:
            self.net.phone_order(epoch(ev["t"]), body, PHONE_PIN, PHONE_TOPIC, ts=sent)
        finally:
            self.net.__dict__.pop("next_id", None)

    def _inbox(self, ev: dict, live: bool) -> None:
        doc = inbox_doc(ev)
        self.net.set_inbox(doc)

    # -------- disk: what persists (applied once, by whichever boot process sees it first)
    def disk_effect(self, it) -> None:
        k, ev, t = it["kind"], it["ev"], it["t"]
        try:
            if k == "run_end":
                self._drop_run(ev)
            elif k == "log_chunk":
                self._append(ev, t)
            elif k == "log_rotate":
                src, dst = self.tp(ev["path"]), self.tp(ev["to"])
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(src, dst)
                    self.changed(dst)
                else:
                    self.note("log_rotate: nothing to rotate", path=ev["path"])
            elif k == "file":
                self._file(ev, t)
            elif k == "mas_config":
                dst = self.tp(ev["path"])
                clone(corpus_file(self.corpus, ev), dst)
                mt = epoch(ev.get("mtime") or ev["t"])
                self.stamp(dst, min(mt, t) if ev.get("mtime_is_pull") else mt)
                if self.mas.up and dst.name in ("ScriptConfig.json", "Config.json", "QueueConfig.json"):
                    shutil.copyfile(dst, self.mas.shadow / "config" / dst.name)
                    self.mas._disk[dst.name] = dst.read_bytes()
            elif k == "net_fault":
                if t >= self.boot["start"]:
                    self._fault(ev, t)
            elif k == "desktop":
                pass        # loaded into FakeDesktop at start
            elif k == "state_edit":
                self._state_edit(ev, t)
        except OSError as exc:
            self.error("input not applied", kind=k, src=ev.get("src"), why=f"{type(exc).__name__}: {exc}")

    def _drop_run(self, ev: dict) -> None:
        d = self.tp(ev["path"])
        d.mkdir(parents=True, exist_ok=True)
        for part in ("log", "json"):          # the .json last: it is what the relay waits for
            ref = ev.get(part)
            if not ref:
                continue
            dst = d / Path(ref["file"]).name
            clone(self.corpus / ref["file"], dst)
            mt = epoch(ref["mtime"])
            self.stamp(dst, mt)
        self.changed(d / "x")

    def _append(self, ev: dict, t: float) -> None:
        dst = self.tp(ev["path"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(self.corpus / ev["file"], "rb") as f:
            f.seek(int(ev["off"]))
            data = f.read(int(ev["len"]))
        size = dst.stat().st_size if dst.exists() else 0
        off = int(ev["off"])
        if size != off:
            self.note("log chunk offset differs from the file", path=ev["path"], size=size, off=off)
        with open(dst, "r+b" if dst.exists() else "wb") as f:
            f.seek(off)
            f.write(data)
            f.truncate()
        self.stamp(dst, t)
        self.changed(dst)
        if "/ok-ww/working/logs/ok-script" in ev["path"]:
            for m in OVERRIDES_LOADED.finditer(data):
                self._overlay_report(datetime.strptime(m.group(1).decode(), "%Y-%m-%d %H:%M:%S")
                                     .replace(tzinfo=BJ).timestamp())

    def _overlay_report(self, at: float) -> None:
        """What the relay's overrides write when OK-WW loads them (OVERRIDES_LOADED): every
        override site applied. The record backs "all applied": the boot's patch push said
        only that the file was installed (no 「没贴上」 / 「按新版适配」 line) and #26 read
        find_nest 「装上」 on 10-06, 10-12 and 10-13."""
        src = self.tree / "_sim" / "code" / "ark_relay" / "features" / "okww_patch" / "okww_files" / "ark_overrides.tasks.py"
        try:
            text = src.read_text(encoding="utf-8")
        except OSError as exc:
            self.error("overlay report not written", why=str(exc))
            return
        sites = list(dict.fromkeys(f"{c}.{n}" for c, n in re.findall(r'(?:@override|_farm_hook)\((\w+), "(\w+)"', text)))
        dst = self.tree / "C" / "ProgramData" / "ark-okww-overlay.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps({"applied": sites, "skipped": [], "adapted": [], "error": ""},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        self.stamp(dst, at)

    def _file(self, ev: dict, t: float) -> None:
        op = ev.get("op")
        dst = self.tp(ev["path"])
        if op == "write":
            clone(corpus_file(self.corpus, ev), dst)
            self.stamp(dst, epoch(ev.get("mtime") or ev["t"]))
            self.changed(dst)
        elif op in ("test_window_open", "test_window_close"):
            # Written from the Mac (scripts/mac test runs), not by the relay: an input.
            try:
                rows = json.loads(dst.read_text(encoding="utf-8-sig")) if dst.exists() else []
            except ValueError:
                rows = []
            ent = ev["entry"]
            if op == "test_window_open":
                rows.append(dict(ent))
            else:
                for r in rows:
                    if r.get("since") == ent.get("since"):
                        r["until"] = ent.get("until")
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".tmp")
            tmp.write_text(json.dumps(rows, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, dst)
            self.stamp(dst, t)
            self.changed(dst)
        else:
            self.note("file op not modelled", op=op, src=ev.get("src"))

    def _state_edit(self, ev: dict, t: float) -> None:
        """An outside edit of state.json (outside.jsonl): written the way StateStore
        writes it (whole file, replaced), stamped at its time; StateStore rereads on
        a new mtime and modes.py builds a fresh store per call."""
        p = self.tp(DATA_REL + "/state/state.json")
        data = json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
        sec = data.setdefault(ev["section"], {})
        sec.update(ev.get("set") or {})
        for key in ev.get("pop") or []:
            sec.pop(key, None)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".daysim-tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
        self.stamp(p, t)
        self.changed(p)
        self.note("outside state.json edit", section=ev["section"], set=ev.get("set"), pop=ev.get("pop"),
                  src=ev.get("src"))

    def _fault(self, ev: dict, t: float) -> None:
        ch, err = ev.get("channel"), str(ev.get("error") or "")
        kind = "timeout" if ("timed out" in err or "TimeoutError" in err) else "refused"
        match = {"mac": urllib.parse.urlsplit(ALERT_URL).netloc, "ntfy_backlog": "poll=1", "cos": ".myqcloud.com",
                 "wecom": "qyapi.weixin.qq.com", "serverchan": "ftqq.com"}.get(ch)
        if ch == "ntfy_stream":
            self.net.fault(PHONE_TOPIC, "stall", start=t)
        elif ch == "ntfy_publish":
            # The line comes when the call has failed; a timeout began POST_TIMEOUT before it.
            self.net.fault(f"ntfy.sh/{PHONE_TOPIC}", kind, method="POST",
                           start=t - NTFY_POST_TIMEOUT_S - 1 if kind == "timeout" else t)
        elif match:
            self.net.fault(match, kind, start=t)
        else:
            self.note("net fault not replayed", channel=ch, src=ev.get("src"))

    # -------- hooks the fakes call
    def _task_run(self, name: str, task: dict) -> None:
        task["running"] = True
        self.note("schtasks /run: the World starts nothing the record does not show", task=name)

    def _spawn(self, exe, args, cwd, task) -> None:
        if exe.replace("\\", "/").rsplit("/", 1)[-1].lower() == "ok-ww.exe":
            self._okww_preupdate(exe, args)
            return
        self.note("scheduled-task launch: the World starts nothing the record does not show",
                  exe=exe, args=args, task=task)

    def _okww_preupdate(self, exe: str, args: str) -> None:
        """The relay's pre-update launch of ok-ww.exe (preupdate_okww.run_okww), as the
        record has it: OK-WW starts, rewrites app.json, finds nothing newer (10-12 08:46:17
        launched, 08:47:02 「无需更新（v3.7.4）」; the same on 10-13). The relay ends it."""
        now = self.sched.now()
        self.win.procs.start("ok-ww.exe", f'"{exe}" {args}'.strip(), exe=exe, t=now)
        app = self.tp("D:/ark/okww/data/apps/ok-ww/app.json")

        def rewrite() -> None:
            if app.is_file():
                app.write_bytes(app.read_bytes())
                self.changed(app)
        self.sched.at(now + OKWW_APPJSON_REWRITE_S, rewrite, "okww-appjson")
        self.note("ok-ww.exe launched for its update check: app.json rewritten, no newer version")

    def _power_off(self, t: float) -> None:
        b = self.boot
        expected = b["relay_poweroff"] and abs(b["end"] - t) <= POWEROFF_MATCH_S
        if not expected:
            self.note("the relay powered off where the record did not: the machine stays on, as it did")
            self.win.power, self.win.shutdown_at = "on", None
            return
        self.powered_off = True
        self._windows_shutdown("the relay's own power-off")

    def _windows_shutdown(self, why: str) -> None:
        if self.stopping:
            return
        self.stopping = True
        self.mas.shutdown_started()
        self.win.power = "going_down"
        self._call_host("SvcShutdown", why)

    def _call_host(self, method: str, why: str) -> None:
        host = self.host
        if host is None:
            return
        # The SCM / WM_ENDSESSION call SvcStop on a thread of their own, not the main loop's.
        threading.Thread(target=getattr(host, method), name=f"world-{method}", daemon=True).start()
        self.note("boot ends", how=method, why=why)

    def _end_boot(self) -> None:
        b = self.boot
        if self.stopping:
            return
        if b["relay_poweroff"]:
            if not self.powered_off:
                self.note("recorded relay power-off not reproduced: the World powers off at the recorded time")
            self._windows_shutdown("recorded power-off")
            return
        if b["how"] == "windows_shutdown":
            self._windows_shutdown("recorded Windows shutdown")
            return
        self.stopping = True
        self._call_host("SvcStop", b["how"])

    # -------- end of the process
    def save(self) -> None:
        st = {"applied": sorted(self.applied), "ntfy_count": dict(self.net.ntfy_count)}
        tmp = self.state_file.with_name("world.json.tmp")
        tmp.write_text(json.dumps(st), encoding="utf-8")
        os.replace(tmp, self.state_file)
        self.cos_dir.mkdir(exist_ok=True)
        for key, data in list(self.net.cos.items()):
            if len(data) <= 1 << 20:
                (self.cos_dir / urllib.parse.quote(key, safe="")).write_bytes(data)


_APP_VERSION = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ \|[^\n]*?(?:版本号:\s+|current_version=)(v[\w.-]+)", re.M)


def _app_versions(data: bytes) -> list[tuple[float, str]]:
    """(time, version) of every app.log line that names AUTO-MAS's version."""
    return [(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ).timestamp(), m.group(2))
            for m in _APP_VERSION.finditer(data.decode("utf-8", "replace"))]


def recorded_stamina(corpus: Path, seed: dict, day: str) -> list[tuple[float, dict]]:
    """The day's Endfield stamina as Skland gave it, from the record's #10 lines
    (「上机核对 #10 过了：08:46:01 ...curStamina=228 maxStamina=360 maxTs=1791822985」)."""
    ent = next((f for f in seed["files"] if f["path"].endswith("ark-relay/relay.log")), None)
    if ent is None:
        return []
    out = []
    pat = re.compile("^" + day[5:] + r" \S+ INFO +ark\.machinecheck +上机核对 #10 过了：(\d\d:\d\d:\d\d)"
                     r".*?curStamina=(\d+) maxStamina=(\d+) maxTs=(\d+)", re.M)
    try:
        data = corpus_file(corpus, ent).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for m in pat.finditer(data):
        t = datetime.fromisoformat(f"{day}T{m.group(1)}+08:00").timestamp()
        out.append((t, {"curStamina": int(m.group(2)), "maxStamina": int(m.group(3)), "maxTs": int(m.group(4))}))
    return out


def web_routes(now, stamina: list) -> dict:
    """Skland as the relay's session code walks it (skland.get_did, login, refresh,
    bindings, endfield_card) and as banners reads it (wiki char-pool, item/info), and
    the Endfield sources banners reads once it has a Skland session (bulletin, version
    briefing, the yituliu pool table). Answers are placeholders in the shapes skland.py
    reads; the stamina is the record's (recorded_stamina); the banner sources are the
    repo's recorded copies, as tests/test_banners.py reads them: endfield_pools.json
    (the 「晨星于此闪耀」 pool, UP operator entry 1683 梨诺), ef_bulletin_full_2026-09-03.json
    (on 10-13 the live list still carried the 09-02 version notes, banners/endfield.py),
    ef-briefing-v1d6/ (the version briefing from 10-06 20:00) and
    ef_pool_info_table_2026-10-01.json. No credential is real or kept."""
    fx = RELAY / "tests" / "fixtures"
    yituliu = "Arknights-yituliu/ef-frontend-v1"
    pool_table = lambda c: json.loads((fx / "ef_pool_info_table_2026-10-01.json").read_text(encoding="utf-8"))  # noqa: E731

    def card(_c):
        t = now()
        got = [s for at, s in stamina if at <= t] or [s for _at, s in stamina[:1]]
        if not got:
            return {"code": 0, "data": {"detail": {}}}
        return {"code": 0, "data": {"detail": {"dungeon": dict(got[-1])}}}

    zonai = "https://zonai.skland.com"
    return {
        "https://fp-it.portal101.cn/deviceprofile/v4": {"code": 1100, "detail": {"deviceId": "daysim"}},
        "https://as.hypergryph.com/user/oauth2/v2/grant": {"status": 0, "data": {"code": "daysim"}},
        zonai + "/api/v1/user/auth/generate_cred_by_code":
            {"code": 0, "data": {"cred": "daysim", "token": "daysim", "userId": "0"}},
        zonai + "/web/v1/auth/refresh": lambda c: {"code": 0, "data": {"token": "daysim"}, "timestamp": int(now())},
        zonai + "/api/v1/game/player/binding": {"code": 0, "data": {"list": [
            {"appCode": "arknights", "bindingList": [{"uid": "0"}]},
            {"appCode": "endfield", "bindingList": [{"roles": [{"roleId": "0", "serverId": "1"}]}]}]}},
        zonai + "/api/v1/game/endfield/card/detail": card,
        zonai + "/web/v1/wiki/char-pool":
            lambda c: {"code": 0, "data": {"list": json.loads((fx / "endfield_pools.json").read_text(encoding="utf-8"))}},
        zonai + "/web/v1/wiki/item/info":
            lambda c: {"code": 0, "data": {"item": {"name": {"1683": "梨诺"}.get(c.query.get("id", ""), "")}}},
        "https://game-hub.hypergryph.com/bulletin/v2/aggregate":
            lambda c: json.loads((fx / "ef_bulletin_full_2026-09-03.json").read_text(encoding="utf-8")),
        "https://endfield.hypergryph.com/version_briefing/latest":
            lambda c: (fx / "ef-briefing-v1d6" / "latest.html").read_text(encoding="utf-8"),
        "https://web.hycdn.cn/endfield/webview/_version_briefing/":
            lambda c: (fx / "ef-briefing-v1d6" / "bundle.js").read_text(encoding="utf-8"),
        f"https://fastly.jsdelivr.net/gh/{yituliu}@": pool_table,
        f"https://cdn.jsdelivr.net/gh/{yituliu}@": pool_table,
        f"https://gh-proxy.com/https://raw.githubusercontent.com/{yituliu}/": pool_table,
        f"https://raw.githubusercontent.com/{yituliu}/": pool_table,
    }


def _png_1x1() -> bytes:
    import struct  # noqa: PLC0415
    import zlib  # noqa: PLC0415

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x80")) + chunk(b"IEND", b""))


PNG_1X1 = _png_1x1()


def phone_body(ev: dict) -> "dict | None":
    """The phone page's body for a recorded order (module docstring, web/schema.js)."""
    a, args, res = ev.get("action"), ev.get("args") or {}, str(ev.get("result") or "")
    if a == "debug_mode":
        if args.get("on") is False:
            return {"action": "debug_mode", "off": True, "confirmed": True}
        return {"action": "debug_mode", "minutes": 90, "confirmed": True}
    if a == "skip_shutdown":
        return {"action": "skip_shutdown"} if args.get("on", True) else {"action": "skip_shutdown", "off": True}
    if a == "echo_farm":
        m = re.search(r"开始刷(.+?)，刷到 (\d\d:\d\d) 为止", res)
        if not m:
            return None
        try:
            from ark_relay.core.wuwa_boss import BOSSES  # noqa: PLC0415 - the relay is imported by now
        except ImportError:
            return None
        idx = next((i for i, row in BOSSES.items() if row[0] == m.group(1)), None)
        if idx is None:
            return None
        return {"action": "echo_farm", "boss": idx, "until": m.group(2), "name": m.group(1), "confirmed": True}
    if a == "echo_farm_stop":
        return {"action": "echo_farm_stop"}
    return None


def inbox_doc(ev: dict) -> dict:
    """The inbox file as scripts/mac/order.sh writes it, rebuilt from the relay's lines."""
    title = str(ev.get("title") or "")
    name = title.split("：", 1)[1] if "：" in title else title
    cmds = [] if name == "空（安全状态）" else [{"action": ZH_ORDER[x]} for x in name.split("、") if x in ZH_ORDER]
    return {"version": int(ev["version"]), "name": name, "note": title, "commands": cmds}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
