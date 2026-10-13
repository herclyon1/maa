#!/usr/bin/env python3
"""Turn one machine pull ("daydata") into the replay input of one Beijing day.

    ~/.local/bin/python3.14 -I relay/tests/daysim/slice.py 2026-10-12 --daydata <pull dir>

<pull dir> mirrors the machine (C/ProgramData/ark-relay/..., D/ark/...) with the
files' true mtimes (tar keeps them) and _pull/MANIFEST.json; scripts/mac/pull-day.sh
makes one. Writes (design: daysim design.md section 2, "Input feed for Beijing day D"):

  ~/Claude/daysim-corpus/<D>/files/<machine path>  redacted copies, true mtimes
  ~/Claude/daysim-corpus/<D>/derived/<machine path> files rebuilt for the seed
  ~/Claude/daysim-corpus/<D>/manifest.json          sha256 / size / mtime / source of each
  ~/Claude/daysim-corpus/<D>/events.jsonl           same bytes as the repo copy
  relay/tests/daysim/days/<D>/events.jsonl          time-sorted input events
  relay/tests/daysim/days/<D>/seed.json             the machine at D 00:00 (seed.py)

Every event is {"t": ISO+08:00, "kind": <contract kind>, "src": "<daydata path>:<line>", ...}
and names corpus files by path + sha256, so the repo copy stays small. Nothing secret
goes in: COS signed links and the other patterns in SECRET_PATTERNS are masked on the
way into the corpus, AUTO-MAS/MAA config JSON also goes through scripts/mac/redact.py.

Rules that decide what a recorded line means are kept next to the code that applies
them; each names the relay or AUTO-MAS line it reads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DAYS_DIR = HERE / "days"
CORPUS_ROOT = Path.home() / "Claude" / "daysim-corpus"

BJ = timezone(timedelta(hours=8))          # the machine's clock
UTC4 = timezone(timedelta(hours=4))        # AUTO-MAS history names (collector.AUTOMAS_NAME_TZ)

# The contract (design.md section 2, "Interfaces fixed now").
KINDS = ("power_on", "power_off", "relay_start", "relay_stop", "run", "file", "log_chunk",
         "log_rotate", "proc", "mas_backend", "mas_config", "phone_order", "inbox",
         "net_fault", "web", "desktop")

# Log lines are appended in chunks of this many seconds of their own stamps.
# collect_watch tails maafw.log live and judges "no new line for N minutes"; a minute
# per chunk keeps that judgement exact to the minute.
CHUNK_S = 60
# maafw.log is cut to MaaEnd run windows widened by this much (design.md table row
# "Game logs": "maafw trimmed to run windows +-10 min").
TRIM_MARGIN_S = 600
# Rotated log parts younger than this at D 00:00 are put in the seed under their
# rotated name (asst.bak.log, ok-script.<D-1>.log); older ones are left out.
KEEP_ROTATED_S = 48 * 3600
# History folders looked at for the seed: D-7 .. D.
SEED_HISTORY_DAYS = 7

HIST = "D/ark/automas/history"
RELAY_HOME = "C/ProgramData/ark-relay"
STATE = f"{RELAY_HOME}/state"
RELAY_LOG = f"{RELAY_HOME}/relay.log"
MAS_CONFIG = "D/ark/automas/config"
# Recorded but never read by the relay, and big: not copied (MANIFEST "d3" archive).
SKIP_PREFIXES = ("D/ark/maaend/debug/cpp-algo/", "D/ark/automas/debug/frontend.log",
                 "D/ark/automas/logs/", "_pull/")

# Secret shapes masked on the way into the corpus and refused anywhere under relay/
# (test_daysim_slice.py). (name, pattern, replacement); the lookahead keeps an already
# masked value from matching again; values are token characters only, so a code
# placeholder like {self.cfg.wecom_secret} is not one.
SECRET_PATTERNS = (
    ("cos-akid", rb"AKID(?!REDACTED)[0-9A-Za-z]{12,}", rb"AKIDREDACTED"),
    ("cos-signature", rb"(q-signature=)(?!REDACTED)[0-9a-fA-F]{16,}", rb"\1REDACTED"),
    ("wecom-webhook-key", rb"(webhook/send\?key=)(?!REDACTED)[0-9A-Za-z-]{16,}", rb"\1REDACTED"),
    ("wecom-corpsecret", rb"(corpsecret=)(?!REDACTED)[0-9A-Za-z_-]{16,}", rb"\1REDACTED"),
    ("access-token", rb"(access_token=)(?!REDACTED)[0-9A-Za-z_-]{16,}", rb"\1REDACTED"),
    ("serverchan-key", rb"\bSCT(?!REDACTED)[0-9A-Za-z]{16,}", rb"SCTREDACTED"),
    ("github-token", rb"\bgh[pousr]_[0-9A-Za-z]{30,}", rb"ghx_REDACTED"),
    ("api-key", rb"\bsk-(?!REDACTED)[0-9A-Za-z_-]{30,}", rb"sk-REDACTED"),
    ("cdk", rb"(?i)(cdk[\"']?\s*[:=]\s*[\"']?)(?!REDACTED)[0-9A-Za-z]{16,}", rb"\1REDACTED"),
)
_SECRET_RES = [(n, re.compile(p), r) for n, p, r in SECRET_PATTERNS]
# A COS signature is masked too, but alone it opens nothing: the repo's rule is that the
# key id goes (q-ak=AKIDREDACTED, worker rules 10-13) and committed fixtures keep the
# signature. So secret_hits does not count it.
NOT_SCANNED = ("cos-signature",)
# Cheap pre-filter: a line without any of these bytes cannot match a pattern above.
_SECRET_HINT = re.compile(rb"AKID|q-signature|webhook|corpsecret|access_token|SCT|gh[pousr]_|sk-|(?i:cdk)")

sys.path.insert(0, str(REPO / "scripts" / "mac"))
sys.path.insert(0, str(HERE))          # seed.py; -I leaves the script dir off the path
import redact  # noqa: E402  scripts/mac/redact.py, key-name masking for JSON configs


def redact_bytes(data: bytes) -> bytes:
    """Mask every SECRET_PATTERNS hit; the byte count of a line may change, its line count not."""
    if not _SECRET_HINT.search(data):
        return data
    out = data
    for _name, rx, rep in _SECRET_RES:
        out = rx.sub(rep, out)
    return data if out == data else out     # the same object when nothing was masked


# A literal each pattern's match contains: `in` is a memchr-speed scan, so whole files
# (hundreds of MB in a corpus) only meet a regex when the literal is there.
_SECRET_GUARD = {"cos-akid": (b"AKID",), "cos-signature": (b"q-signature=",),
                 "wecom-webhook-key": (b"webhook/send?key=",), "wecom-corpsecret": (b"corpsecret=",),
                 "access-token": (b"access_token=",), "serverchan-key": (b"SCT",),
                 "github-token": (b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_"), "api-key": (b"sk-",),
                 "cdk": (b"cdk", b"CDK", b"Cdk")}


def secret_hits(data: bytes) -> list[str]:
    """Names of the secret patterns found in `data` (the test runs this over relay/)."""
    return [n for n, rx, _rep in _SECRET_RES
            if n not in NOT_SCANNED and any(g in data for g in _SECRET_GUARD[n]) and rx.search(data)]


def clone(src: Path, dst: Path) -> None:
    """An unchanged copy: an APFS copy-on-write clone on the Mac (no new disk space;
    the same file in three days' corpora costs nothing), a plain copy elsewhere."""
    if dst.exists():
        dst.unlink()
    if sys.platform == "darwin" and subprocess.run(["/bin/cp", "-c", str(src), str(dst)],
                                                   capture_output=True, check=False).returncode == 0:
        return
    shutil.copyfile(src, dst)


# ------------------------------------------------------------------ time helpers
def iso(ts: float) -> str:
    """Beijing ISO time; microseconds only when the value has them (file mtimes)."""
    dt = datetime.fromtimestamp(ts, BJ)
    return dt.isoformat(timespec="microseconds" if dt.microsecond else "seconds")


def day_start(day: str) -> float:
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=BJ).timestamp()


def parse_when(s: str, year: int) -> "float | None":
    """'MM-DD HH:MM[:SS]' as the relay logs it (no year) -> unix time, None if not that shape."""
    m = re.fullmatch(r"(\d\d)-(\d\d) (\d\d):(\d\d)(?::(\d\d))?", s.strip())
    if not m:
        return None
    mo, d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return datetime(year, mo, d, h, mi, se, tzinfo=BJ).timestamp()


# ------------------------------------------------------------------ relay.log
# "10-12 08:45:26 INFO    ark.service  服务模式启动，..." - relay/ark_relay/core/config.py
# log format: month-day, time, level padded to 8, logger, two spaces, message.
RELAY_LINE = re.compile(r"^(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d) (\w+)\s+(\S+)\s+(.*)$")


@dataclass
class Rec:
    n: int          # 1-based line number in relay.log
    off: int        # byte offset of the line
    t: float
    level: str
    logger: str
    msg: str


def read_relay_log(path: Path, year: int, month: int) -> "tuple[list[Rec], int]":
    """Every stamped relay.log line, plus the file's byte size. Continuation lines
    (tracebacks, multi-line pushes) carry no stamp and are skipped."""
    recs: list[Rec] = []
    off = 0
    with path.open("rb") as f:
        for n, raw in enumerate(f, 1):
            m = RELAY_LINE.match(raw.decode("utf-8", "replace").rstrip("\r\n"))
            if m:
                mo, d, h, mi, se = (int(x) for x in m.groups()[:5])
                y = year - 1 if mo - month > 6 else year + 1 if month - mo > 6 else year
                t = datetime(y, mo, d, h, mi, se, tzinfo=BJ).timestamp()
                recs.append(Rec(n, off, t, m.group(6), m.group(7), m.group(8)))
            off += len(raw)
    return recs, off


# ------------------------------------------------------------------ corpus + day context
@dataclass
class Day:
    day: str
    t0: float
    t1: float
    dd: Path                       # daydata root
    corpus: Path                   # ~/Claude/daysim-corpus/<D>
    manifest: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    seq: int = 0
    notes: list = field(default_factory=list)
    claimed: set = field(default_factory=set)        # daydata paths some handler owns
    log_seed: list = field(default_factory=list)     # seed entries for logs at t0
    runs: list = field(default_factory=list)
    recs: list = field(default_factory=list)
    relay_size: int = 0

    @property
    def year(self) -> int:
        return int(self.day[:4])

    def within(self, t: "float | None") -> bool:
        return t is not None and self.t0 <= t < self.t1

    def emit(self, t: float, kind: str, src: str, **f) -> dict:
        assert kind in KINDS, kind
        ev = {"t": iso(t), "kind": kind, "src": src, **f}
        self.seq += 1
        self.events.append((t, self.seq, ev))
        return ev

    def record(self, rel: str, data_sha: str, size: int, mtime: float, source: str, how: str) -> None:
        self.manifest[rel] = {"sha256": data_sha, "size": size, "mtime": iso(mtime),
                              "source": source, "transform": how}

    def put(self, rel: str, how: str = "redact", *, member: "str | None" = None) -> dict:
        """Copy one daydata file into the corpus; returns {"file", "sha256", "mtime"}.

        how: "redact" (SECRET_PATTERNS), "json" (also scripts/mac/redact.py walk),
        "raw" (binary, copied as is)."""
        src = self.dd / rel
        if member:
            with zipfile.ZipFile(src) as z:
                data = z.read(member)
            out_rel = "files/" + str(Path(rel).parent / member)
        else:
            data = src.read_bytes()
            out_rel = "files/" + rel
        original = data
        if how == "json":
            try:
                data = (json.dumps(redact.walk(json.loads(data.decode("utf-8-sig"))),
                                   ensure_ascii=False, indent=1) + "\n").encode("utf-8")
            except ValueError:
                data = redact_bytes(data)
        elif how == "redact":
            data = redact_bytes(data)
        mtime = src.stat().st_mtime
        return self.write(out_rel, data, mtime, rel + (f"!{member}" if member else ""), how,
                          same_as=src if data is original and not member else None)

    def write(self, out_rel: str, data: bytes, mtime: float, source: str, how: str,
              same_as: "Path | None" = None) -> dict:
        out = self.corpus / out_rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if same_as is not None:
            clone(same_as, out)
        elif not out.exists() or out.read_bytes() != data:
            out.write_bytes(data)
        os.utime(out, (mtime, mtime))
        sha = hashlib.sha256(data).hexdigest()
        self.record(out_rel, sha, len(data), mtime, source, how)
        return {"file": out_rel, "sha256": sha, "mtime": iso(mtime)}


def machine(rel: str) -> str:
    """'D/ark/maa/debug/asst.log' -> 'D:/ark/maa/debug/asst.log'."""
    return f"{rel[0]}:/{rel[2:]}"


# ------------------------------------------------------------------ runs (AUTO-MAS history)
@dataclass
class Run:
    dirdate: str
    user: str
    stem: str
    script: str
    start: float
    end: float
    json_rel: "str | None"
    log_rel: "str | None"


def history_runs(dd: Path, dirdates: list[str]) -> list[Run]:
    """Every json/log pair under history/<dirdate>/<user>/. AUTO-MAS names both the folder
    and the file on a UTC+4 clock (collector.AUTOMAS_NAME_TZ): <script>-HH-MM-SS. The run
    starts at the name and ends when the .json was written (design.md: "end = .json mtime")."""
    out = []
    for dirdate in dirdates:
        base = dd / HIST / dirdate
        if not base.is_dir():
            continue
        for user_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            stems = sorted({p.stem for p in user_dir.iterdir() if p.suffix in (".json", ".log")})
            for stem in stems:
                try:
                    script, hh, mi, ss = stem.rsplit("-", 3)
                    start = datetime.strptime(f"{dirdate} {hh}:{mi}:{ss}", "%Y-%m-%d %H:%M:%S") \
                        .replace(tzinfo=UTC4).timestamp()
                except ValueError:
                    continue
                js, lg = user_dir / f"{stem}.json", user_dir / f"{stem}.log"
                end = (js if js.exists() else lg).stat().st_mtime
                rel = f"{HIST}/{dirdate}/{user_dir.name}/{stem}"
                out.append(Run(dirdate, user_dir.name, stem, script, start, end,
                               f"{rel}.json" if js.exists() else None,
                               f"{rel}.log" if lg.exists() else None))
    return out


def dirdates_around(day: str, before: int, after: int) -> list[str]:
    d = datetime.strptime(day, "%Y-%m-%d")
    return [(d + timedelta(days=k)).strftime("%Y-%m-%d") for k in range(-before, after + 1)]


def do_runs(ctx: Day) -> None:
    for r in history_runs(ctx.dd, dirdates_around(ctx.day, SEED_HISTORY_DAYS, 1)):
        for rel in (r.json_rel, r.log_rel):
            if rel:
                ctx.claimed.add(rel)
        if r.start < ctx.t1 and r.end >= ctx.t0:
            ctx.runs.append(r)
            files = {k: ctx.put(rel) for k, rel in (("json", r.json_rel), ("log", r.log_rel)) if rel}
            ctx.emit(max(r.start, ctx.t0), "run", f"{r.json_rel or r.log_rel}:1",
                     user=r.user, script=r.script, stem=r.stem, dir=r.dirdate,
                     path=machine(f"{HIST}/{r.dirdate}/{r.user}"),
                     start=iso(r.start), end=iso(r.end), **files)


# ------------------------------------------------------------------ boots and power (relay.log)
@dataclass
class Boot:
    start: Rec
    after: str                      # how the previous boot ended
    version: str = ""
    fresh: bool = False             # 「刚开机，DNS 还没起来」 seen in this boot
    boot_line: "float | None" = None
    stop: "Rec | None" = None
    stop_how: str = ""
    poweroff_cmd: "Rec | None" = None
    last: "Rec | None" = None
    unlogged: bool = False          # the end left no line; stop is the boot's last line


# relay/ark_relay/service.py and boot_stages.py write these; each is matched on the
# ark.service / ark.engine logger only, because machinecheck quotes them inside its own lines.
START = "服务模式启动"
# 「收到停止通知（Windows 关机 | 停止中继 | 停止服务）」 since 10-06; before that only
# 「收到停止信号，退出」, and a power-off often left no line at all.
STOP_NOTICE = re.compile(r"^收到停止通知（([^）]*)）")
STOP_SIGNAL = "收到停止信号，退出"
# The self-update restart, worded 「代码已更新，切到新版本文件夹并重启」 now and
# 「代码已更新，重启以立即生效」 in the builds until 10-05.
SELF_UPDATE = re.compile(r"^代码已更新，.*重启")
FRESH = "刚开机，DNS 还没起来"
POWEROFF_CMD = re.compile(r"^本轮已处理完毕，\d+ 秒后关机")
BOOT_AT = re.compile(r"这次是 (\d\d-\d\d \d\d:\d\d) 开的机")
VERSION = re.compile(r"^中继代码版本 v(\S+)")
# A relay power-off and the Windows stop notice it causes: the command says "60 秒后",
# the notice arrives a minute later (10-12 12:10:36 -> 12:11:36).
POWEROFF_TO_STOP_S = 300


def boots_of(recs: list[Rec], year: int) -> list[Boot]:
    """One Boot per 「服务模式启动」, with how it ended. A boot whose end left no notice
    is resolved by the next one: if that is a fresh power-on (「刚开机」) the machine went
    off (stop_how windows_shutdown, at the last line when nothing was logged)."""
    boots: list[Boot] = []
    cur: "Boot | None" = None
    for r in recs:
        svc = r.logger == "ark.service"
        if svc and r.msg.startswith(START):
            cur = Boot(r, "unknown")
            boots.append(cur)
            continue
        if cur is None:
            continue
        cur.last = r
        if svc and cur.stop is None and (m := STOP_NOTICE.match(r.msg)):
            cur.stop, cur.stop_how = r, "windows_shutdown" if m.group(1) == "Windows 关机" else "stop"
        elif svc and cur.stop is None and r.msg.startswith(STOP_SIGNAL):
            cur.stop, cur.stop_how = r, "signal"
        elif svc and cur.stop is None and SELF_UPDATE.match(r.msg):
            cur.stop, cur.stop_how = r, "self_update"
        elif r.logger == "ark.engine" and POWEROFF_CMD.match(r.msg):
            cur.poweroff_cmd = r
        elif svc and r.msg.startswith(FRESH):
            cur.fresh = True
        elif svc and not cur.version and (m := VERSION.match(r.msg)):
            cur.version = m.group(1)
        if cur.boot_line is None and r.logger == "ark.shutdown" and (m := BOOT_AT.search(r.msg)):
            cur.boot_line = parse_when(m.group(1), year)
    for b, nxt in zip(boots, boots[1:] + [None], strict=True):
        if b.stop is None and nxt is not None:
            b.stop, b.stop_how = b.last or b.start, "windows_shutdown" if nxt.fresh else "unrecorded"
            b.unlogged = True
        elif b.stop_how == "signal":
            b.stop_how = "windows_shutdown" if nxt is not None and nxt.fresh else "stop"
        if nxt is not None:
            nxt.after = b.stop_how
    return boots


def relay_poweroff(b: Boot) -> bool:
    return bool(b.stop and b.stop_how == "windows_shutdown" and b.poweroff_cmd
                and 0 <= b.stop.t - b.poweroff_cmd.t <= POWEROFF_TO_STOP_S)


def power_on_time(boots: list[Boot], i: int) -> "tuple[float, str]":
    """When the machine came on before boot i: the minute the relay itself logged
    (「这次是 MM-DD HH:MM 开的机」, from GetTickCount64) in this or a later boot of the
    same power-on, else a minute before the relay started."""
    b = boots[i]
    for later in boots[i:]:
        if later is not b and later.after == "windows_shutdown":
            break
        if later.boot_line is not None and later.boot_line <= b.start.t:
            return later.boot_line, "boot_line"
    return b.start.t - 60, "estimated"


def do_power(ctx: Day) -> list[Boot]:
    boots = boots_of(ctx.recs, ctx.year)
    src = lambda r: f"{RELAY_LOG}:{r.n}"  # noqa: E731
    for i, b in enumerate(boots):
        powered = b.fresh or b.after == "windows_shutdown"
        if powered:
            t, how = power_on_time(boots, i)
            if ctx.within(t):
                ctx.emit(t, "power_on", src(b.start), how=how)
        if ctx.within(b.start.t):
            ctx.emit(b.start.t, "relay_start", src(b.start), version=b.version,
                     after="power_on" if powered else b.after)
        if b.stop and ctx.within(b.stop.t):
            mine = relay_poweroff(b)
            ctx.emit(b.stop.t, "relay_stop", src(b.stop), how=b.stop_how, relay_poweroff=mine,
                     **({"poweroff_cmd": f"{RELAY_LOG}:{b.poweroff_cmd.n}"} if mine else {}),
                     **({"unlogged": True} if b.unlogged else {}))
            if b.stop_how == "windows_shutdown" and not mine:
                # Shut down from outside the relay (a person, Windows Update): an input.
                ctx.emit(b.stop.t, "power_off", src(b.stop), by="outside")
    return boots


# ------------------------------------------------------------------ orders, inbox, network faults
# wire.py stamp(): 「📱 收到手机指令 %s：%s 发出（北京），ntfy %s 收到，id %s，%s」
PHONE = re.compile(r"^📱 收到手机指令 (\S+)：(\S+ \S+|\?) 发出（北京），ntfy (\S+ \S+|\?) 收到，id (\S+)，(.*)$")
INBOX = re.compile(r"^收到待办 v(\d+)（当前 v(\d*)）：(.*)$")
INBOX_POSTED = re.compile(r"^待办: (\d\d-\d\d \d\d:\d\d)（东京 \d\d:\d\d） · ")


def phone_args(action: str, result: str) -> "dict | None":
    """The order's body is not logged; what it asked for is read back from the result line."""
    if action == "debug_mode":
        return {"on": "已开启" in result} if ("已开启" in result or "已关闭" in result) else None
    if action == "skip_shutdown":
        return {"on": "已取消" not in result} if result else None
    return None


def do_orders(ctx: Day) -> None:
    recs = ctx.recs
    for i, r in enumerate(recs):
        if r.logger == "ark.phone" and (m := PHONE.match(r.msg)):
            action, sent, ntime, mid, via = m.groups()
            result = next((x.msg.split("：", 1)[1] for x in recs[i + 1:i + 8]
                           if x.logger == "ark.service" and x.msg.startswith(f"📱 手机指令 {action}：")), "")
            t = parse_when(sent, ctx.year) or r.t
            if ctx.within(t) or ctx.within(r.t):
                ctx.emit(max(t, ctx.t0), "phone_order", f"{RELAY_LOG}:{r.n}", action=action,
                         id=mid, sent=iso(t), ntfy=ntime, received=iso(r.t),
                         via="live" if via.startswith("在线") else "backlog",
                         args=phone_args(action, result), result=result)
        elif r.logger == "ark.inbox" and (m := INBOX.match(r.msg)):
            block = []
            for x in recs[i + 1:i + 40]:
                if x.logger != "ark.service" or not x.msg.startswith("待办:"):
                    break
                block.append(x)
            posted = next((parse_when(p.group(1), ctx.year) for x in block
                           if (p := INBOX_POSTED.match(x.msg))), None)
            t = min(posted, r.t) if posted else r.t
            if ctx.within(r.t) or ctx.within(t):
                ctx.emit(max(t, ctx.t0), "inbox", f"{RELAY_LOG}:{r.n}", version=m.group(1),
                         prev=m.group(2), title=m.group(3),
                         posted=iso(posted) if posted else None, received=iso(r.t),
                         lines=[x.msg[len("待办:"):].strip() for x in block if x.msg[len("待办:"):].strip()])


# Which call failed, read from the relay.log line that reported it. (logger, message
# pattern, channel). Recoveries (「又连上了」) are not faults.
NET_RULES = (
    ("ark.phone", re.compile(r"^手机通道断了（(.*?)）"), "ntfy_stream"),
    ("ark.phone", re.compile(r"^开机读手机信箱没成（(.*?)）"), "ntfy_backlog"),
    ("ark.macpush", re.compile(r"^报警直送 Mac 没送到（(.*?)）"), "mac"),
    ("ark.service", re.compile(r"^上游导出代码核对：\d+ 个文件这次拉不到.*?：(.*?)）?$"), "web"),
)
NET_ERR = re.compile(r"TimeoutError|timed out|URLError|HTTPError|HTTP Error|\b429\b|ConnectionResetError|"
                     r"ConnectionAbortedError|RemoteDisconnected|SSLError|WinError 100\d\d")
NET_CHANNEL_OF_LOGGER = {"ark.phone": "ntfy", "ark.notify": "wecom", "ark.alertlog": "cos",
                         "ark.error_evidence": "cos", "ark.evidence": "cos", "ark.selfupdate": "cos",
                         "ark.macpush": "mac", "ark.inbox": "cos", "ark.serverchan": "serverchan"}
WMI_LOST = re.compile(r"^系统的程序启动通知断了（(.*?)）")


def do_net(ctx: Day) -> None:
    for r in ctx.recs:
        if not ctx.within(r.t):
            continue
        src = f"{RELAY_LOG}:{r.n}"
        if r.logger == "ark.service" and (m := WMI_LOST.match(r.msg)):
            # The WMI process-start subscription broke (service.py); W2's fake_win replays it.
            ctx.emit(r.t, "proc", src, op="wmi_subscription_lost", error=m.group(1)[:160])
            continue
        hit = next(((ch, m) for lg, rx, ch in NET_RULES if r.logger == lg and (m := rx.match(r.msg))), None)
        if hit:
            ctx.emit(r.t, "net_fault", src, channel=hit[0], error=clean(hit[1].group(1)))
        elif r.level in ("WARNING", "ERROR") and NET_ERR.search(r.msg):
            ch = NET_CHANNEL_OF_LOGGER.get(r.logger, "other")
            if ch == "wecom" and "Server酱" in r.msg:
                ch = "serverchan"
            ctx.emit(r.t, "net_fault", src, channel=ch, logger=r.logger, error=clean(r.msg))


def clean(s: str) -> str:
    return redact_bytes(s.encode("utf-8")).decode("utf-8", "replace")[:200]


# ------------------------------------------------------------------ logs: families of rotating files
PLAIN = re.compile(rb"^(?:\xef\xbb\xbf)?(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)")
BRACKET = re.compile(rb"^(?:\xef\xbb\xbf)?\[(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)")
TAURI = re.compile(rb"^(?:\xef\xbb\xbf)?\[(\d{4})-(\d\d)-(\d\d)\]\[(\d\d):(\d\d):(\d\d)")
GOJSON = re.compile(rb'"time":"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)')


@dataclass
class Part:
    rel: str                 # daydata path ("x.zip!member" for a zip member)
    name: str                # machine path it has after rotation (live part: the live path)
    first: "float | None" = None
    life_end: "float | None" = None   # rotation time; None for the live part

    @property
    def src_path(self) -> str:
        return self.rel.split("!")[0]

    @property
    def member(self) -> "str | None":
        return self.rel.split("!", 1)[1] if "!" in self.rel else None


@dataclass
class Family:
    fid: str
    live: str                # machine path appended to while a part is live
    parts: list
    stamp: re.Pattern
    trim: bool = False       # cut to MaaEnd run windows (maafw)
    on_line: object = None   # hook(ctx, t, text, src) for in-window lines


class Stamper:
    """Stamp regex -> unix seconds, cached per distinct second (millions of lines share few)."""

    def __init__(self, rx: re.Pattern):
        self.rx, self.cache = rx, {}

    def __call__(self, line: bytes) -> "float | None":
        m = self.rx.search(line) if self.rx is GOJSON else self.rx.match(line)
        if not m:
            return None
        key = m.group(0)
        t = self.cache.get(key)
        if t is None:
            y, mo, d, h, mi, s = (int(x) for x in m.groups())
            try:
                t = datetime(y, mo, d, h, mi, s, tzinfo=BJ).timestamp()
            except ValueError:
                return None
            self.cache[key] = t
        return t


def open_part(dd: Path, part: Part):
    if part.member:
        z = zipfile.ZipFile(dd / part.src_path)
        return z.open(part.member)
    return (dd / part.rel).open("rb")


def first_stamp(dd: Path, part: Part, stamp: Stamper) -> "float | None":
    with open_part(dd, part) as f:
        for i, line in enumerate(f):
            if i > 500:
                return None
            if (t := stamp(line)) is not None:
                return t
    return None


def family_list(dd: Path) -> list[Family]:
    def ex(rel):
        return (dd / rel).exists()

    def glob(d, pat):
        return sorted(f"{d}/{p.name}" for p in (dd / d).glob(pat)) if (dd / d).is_dir() else []

    fams = []
    maa, mend = "D/ark/maa/debug", "D/ark/maaend/debug"
    okww, mas = "D/ark/okww/data/apps/ok-ww/working/logs", "D/ark/automas/debug"
    # MAA rotates asst.log -> asst.bak.log (and gui.log -> gui.bak.log) by size.
    for name in ("asst", "gui"):
        parts = [Part(r, machine(r)) for r in (f"{maa}/{name}.bak.log", f"{maa}/{name}.log") if ex(r)]
        fams.append(Family(f"maa-{name}", machine(f"{maa}/{name}.log"), parts, BRACKET))
    # MaaEnd's framework renames maafw.log -> maafw.bak.<rotation time>.log at each start.
    fams.append(Family("maaend-fw", machine(f"{mend}/maafw.log"),
                       [Part(r, machine(r)) for r in glob(mend, "maafw.bak.*.log") + glob(mend, "maafw.log")],
                       BRACKET, trim=True))
    fams.append(Family("maaend-tauri", machine(f"{mend}/mxu-tauri.log"),
                       [Part(r, machine(r)) for r in glob(mend, "mxu-tauri_*.log") + glob(mend, "mxu-tauri.log")],
                       TAURI))
    fams.append(Family("maaend-go", machine(f"{mend}/go-service.log"),
                       [Part(r, machine(r)) for r in glob(mend, "go-service.log")], GOJSON))
    # One MaaEnd app log per launch: <date>-<n>.log, never rotated.
    for r in glob(mend, "20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.log"):
        fams.append(Family("maaend-app:" + Path(r).name, machine(r), [Part(r, machine(r))], PLAIN))
    # OK-WW (Python TimedRotatingFileHandler): ok-script.log -> ok-script.<day>.log at the
    # first write of a new day.
    fams.append(Family("okww", machine(f"{okww}/ok-script.log"),
                       [Part(r, machine(r)) for r in glob(okww, "ok-script.20*.log") + glob(okww, "ok-script.log")],
                       PLAIN))
    # AUTO-MAS (loguru): app.log weekly -> app.<stamp>.log, then zipped.
    zparts = []
    for r in glob(mas, "app.*.log.zip"):
        with zipfile.ZipFile(dd / r) as z:
            zparts += [Part(f"{r}!{n}", machine(f"{mas}/{n}")) for n in z.namelist()]
    fams.append(Family("automas-app", machine(f"{mas}/app.log"),
                       zparts + [Part(r, machine(r)) for r in glob(mas, "app.log")], PLAIN, on_line=app_line))
    # The watchdog service's own logs next to relay.log (written by watchdog_guard, not the relay).
    for n in ("watchdog.log", "switch.log"):
        r = f"{RELAY_HOME}/{n}"
        if ex(r):
            fams.append(Family("relay-" + n, machine(r), [Part(r, machine(r))], PLAIN))
    return fams


def run_windows(ctx: Day) -> list[tuple[float, float]]:
    """The day's MaaEnd run windows (endfield history pairs) widened by TRIM_MARGIN_S."""
    return [(r.start - TRIM_MARGIN_S, r.end + TRIM_MARGIN_S)
            for r in history_runs(ctx.dd, dirdates_around(ctx.day, 1, 1))
            if r.user == "endfield" and r.end >= ctx.t0 and r.start < ctx.t1]


def do_logs(ctx: Day) -> None:
    windows = run_windows(ctx)
    for fam in family_list(ctx.dd):
        st = Stamper(fam.stamp)
        for p in fam.parts:
            ctx.claimed.add(p.src_path)
            p.first = first_stamp(ctx.dd, p, st)
        live = fam.parts[-1:] if fam.parts and fam.parts[-1].name == fam.live else []
        rotated = sorted((p for p in fam.parts if p not in live and p.first is not None), key=lambda p: p.first)
        parts = rotated + live
        for i, p in enumerate(parts[:-1]):
            p.life_end = parts[i + 1].first
        if not parts:
            continue
        if len(fam.parts) > 1 and parts[0].first is not None and parts[0].first > ctx.t0:
            ctx.notes.append(f"{fam.live}: recorded only from {iso(parts[0].first)}")
        last_t = None
        for p in parts:
            start = p.first if p.first is not None else (ctx.dd / p.src_path).stat().st_mtime
            end = p.life_end if p.life_end is not None else float("inf")
            if fam.fid.startswith("maaend-app:"):
                end = (ctx.dd / p.src_path).stat().st_mtime   # one file per launch; done when last written
            if end < ctx.t0 - KEEP_ROTATED_S or start >= ctx.t1:
                continue
            last_t = do_part(ctx, fam, p, st, windows, start, last_t)
            if p.life_end is not None and ctx.within(p.life_end):
                t = max(p.life_end, last_t or p.life_end)
                ctx.emit(t, "log_rotate", f"{p.rel}:1", path=fam.live, to=p.name, family=fam.fid,
                         **({"compressed": True} if p.member else {}))
                last_t = t


def in_windows(t: float, windows) -> bool:
    return any(a <= t <= b for a, b in windows)


def do_part(ctx: Day, fam: Family, p: Part, st: Stamper, windows, start: float, last_t):
    """Copy one physical log into the corpus (redacted, maafw trimmed) and cut the lines
    stamped inside the day into log_chunk events appended to the family's live path."""
    out_rel = "files/" + (str(Path(p.src_path).parent / p.member) if p.member else p.rel)
    out_path = ctx.corpus / out_rel
    out_path.parent.mkdir(parents=True, exist_ok=True)
    whole, pre = hashlib.sha256(), hashlib.sha256()
    off = pre_len = 0
    phase = "pre" if start < ctx.t0 else "in"
    cur = None                      # open chunk
    chunks = []
    t = start
    pre_last = None
    keep = True
    changed = False                  # any line masked or cut: the copy differs from the source
    with open_part(ctx.dd, p) as f, out_path.open("wb") as out:
        for n, raw in enumerate(f, 1):
            s = st(raw)
            if s is not None:
                t = s
                if fam.trim:
                    keep = in_windows(t, windows)
                if phase == "pre" and t >= ctx.t0:
                    phase = "in"
                if phase == "in" and t >= ctx.t1:
                    phase = "post"
            if phase == "pre":
                pre_last = t
            if not keep:
                changed = True
                continue
            line = redact_bytes(raw)
            changed = changed or line is not raw
            out.write(line)
            whole.update(line)
            if phase == "pre":
                pre.update(line)
                pre_len += len(line)
            elif phase == "in":
                bucket = int(t // CHUNK_S)
                if cur is None or bucket > cur["bucket"]:
                    ct = max(t, last_t or t)
                    cur = {"bucket": bucket, "t": ct, "off": off, "len": 0, "n": n, "lines": 0,
                           "h": hashlib.sha256()}
                    chunks.append(cur)
                    last_t = ct
                cur["len"] += len(line)
                cur["lines"] += 1
                cur["h"].update(line)
            off += len(line)
    src_mtime = (ctx.dd / p.src_path).stat().st_mtime
    if not changed and not p.member:
        clone(ctx.dd / p.rel, out_path)
    os.utime(out_path, (src_mtime, src_mtime))
    sha = whole.hexdigest()
    ctx.record(out_rel, sha, off, src_mtime, p.rel, "trim+redact" if fam.trim else "redact")
    for c in chunks:
        ctx.emit(c["t"], "log_chunk", f"{p.rel}:{c['n']}", path=fam.live, file=out_rel,
                 off=c["off"], len=c["len"], sha256=c["h"].hexdigest(), lines=c["lines"])
    if fam.on_line is not None and chunks:
        fam.on_line(ctx, p, out_path, chunks[0]["off"], sum(c["len"] for c in chunks))
    # The seed: what this part looked like at t0 (and under which name).
    life_end = p.life_end if p.life_end is not None else float("inf")
    if start < ctx.t0 <= life_end and start < ctx.t0:
        mt = src_mtime if src_mtime < ctx.t0 else (pre_last or start)
        ctx.log_seed.append({"path": fam.live, "file": out_rel, "len": pre_len,
                             "sha256": pre.hexdigest(), "mtime": iso(mt), "family": fam.fid})
    elif life_end < ctx.t0 and off:
        ctx.log_seed.append({"path": p.name, "file": out_rel, "len": off, "sha256": sha,
                             "mtime": iso(src_mtime), "family": fam.fid})
    return last_t


# ------------------------------------------------------------------ AUTO-MAS app.log -> processes, backend
# app.log: "2026-10-12 09:00:26.569 | INFO     | MAA 自动代理 | 启动MAA进程: D:\ark\maa\MAA.exe"
APP_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ \| (\w+)\s*\| ([^|]+?) \| (.*)$")
PROC_START = (
    re.compile(r"^启动MAA进程: (.+)$"),
    re.compile(r"^启动 OK-WW 进程: (\S+\.exe)(?: (.*))?$"),
    re.compile(r"^启动终末地: (.+\.exe)$"),
    re.compile(r"^运行脚本任务: (.+\.exe)$"),
)
PROC_EXIT = re.compile(r"^进程已中止: (.+\.exe)$")
EMU_START = re.compile(r"^开始启动模拟器 (\d+)")
EMU_STOP = re.compile(r"^模拟器已关闭: (\S+) - 实例 (\d+)")
BACKEND_UP = re.compile(r"^Uvicorn running on \S+:(\d+)")
BACKEND_DOWN = re.compile(r"^Shutting down$")
TASK_START = re.compile(r"^创建任务: (\S+), 模式: (\S+), 触发来源: (\S+)$")
TASK_END = re.compile(r"^任务结束: (\S+)$")


def app_line(ctx: Day, p: Part, out_path: Path, off: int, length: int) -> None:
    """proc / mas_backend events from AUTO-MAS's own app.log lines inside the day."""
    with out_path.open("rb") as f:
        f.seek(off)
        data = f.read(length)
    # Line numbers in src are the source file's: count the lines before `off`.
    with out_path.open("rb") as f:
        n0 = f.read(off).count(b"\n") + 1
    for k, raw in enumerate(data.split(b"\n")):
        m = APP_LINE.match(raw.decode("utf-8", "replace").rstrip("\r"))
        if not m:
            continue
        t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ).timestamp()
        if not ctx.within(t):
            continue
        src, msg = f"{p.rel}:{n0 + k}", m.group(4).strip()
        for rx in PROC_START:
            if mm := rx.match(msg):
                path = mm.group(1).strip()
                ctx.emit(t, "proc", src, op="start", image=path.rsplit("\\", 1)[-1], path=path,
                         by="automas")
                break
        else:
            if mm := PROC_EXIT.match(msg):
                path = mm.group(1).strip()
                ctx.emit(t, "proc", src, op="exit", image=path.rsplit("\\", 1)[-1], path=path, by="automas")
            elif mm := EMU_START.match(msg):
                ctx.emit(t, "proc", src, op="start", image="dnplayer.exe", emulator=mm.group(1), by="automas")
            elif mm := EMU_STOP.match(msg):
                ctx.emit(t, "proc", src, op="exit", image="dnplayer.exe", emulator=mm.group(2), by="automas")
            elif mm := BACKEND_UP.match(msg):
                ctx.emit(t, "mas_backend", src, op="up", port=int(mm.group(1)))
            elif BACKEND_DOWN.match(msg):
                ctx.emit(t, "mas_backend", src, op="down")
            elif mm := TASK_START.match(msg):
                ctx.emit(t, "mas_backend", src, op="task_start", task=mm.group(1), mode=mm.group(2),
                         trigger=mm.group(3))
            elif mm := TASK_END.match(msg):
                ctx.emit(t, "mas_backend", src, op="task_end", task=mm.group(1))


# ------------------------------------------------------------------ AUTO-MAS config, desktop, test windows, other files
def do_mas_config(ctx: Day) -> dict:
    """The config tree at t0 is today's pull (only the pull exists), marked reconstructed;
    a file whose mtime falls inside the day is also written at that moment."""
    cfg = {}
    base = ctx.dd / MAS_CONFIG
    try:
        # Files the pull redacted on the machine: their mtime is the pull's, not AUTO-MAS's.
        man = json.loads((ctx.dd / "_pull" / "MANIFEST.json").read_text(encoding="utf-8"))
        rewritten = set(man.get("redacted_on_machine") or [])
    except (OSError, ValueError):
        rewritten = set()
    if not base.is_dir():
        return cfg
    names = sorted(p.name for p in base.iterdir() if p.is_file())
    backups = [n for n in names if re.match(r"QueueConfig\.(bak|pre)-", n)]
    for n in names:
        rel = f"{MAS_CONFIG}/{n}"
        ctx.claimed.add(rel)
        ref = ctx.put(rel, "json")
        cfg[rel] = ref
        if n in backups:
            continue
        ctx.emit(ctx.t0, "mas_config", f"{rel}:1", path=machine(rel), reconstructed=True,
                 as_of=ref["mtime"], **ref, **({"mtime_is_pull": True} if rel in rewritten else {}),
                 **({"backups": [machine(f"{MAS_CONFIG}/{b}") for b in backups]} if n == "QueueConfig.json" else {}))
        mt = (ctx.dd / rel).stat().st_mtime
        if ctx.within(mt) and rel not in rewritten:
            ctx.emit(mt, "mas_config", f"{rel}:1", path=machine(rel), op="written", **ref)
    return cfg


def do_desktop(ctx: Day) -> None:
    """state/desktop/req-<id>.json (relay -> desktop agent) and res-<id>.json (answer):
    fake_desktop answers from the recorded res files (design.md section 1, "Fakes per seam")."""
    d = ctx.dd / STATE / "desktop"
    if not d.is_dir():
        return
    files = {p.name: p for p in d.iterdir() if p.is_file()}
    for name, p in sorted(files.items()):
        rel = f"{STATE}/desktop/{name}"
        ctx.claimed.add(rel)
        m = re.fullmatch(r"res-([0-9a-f]+)\.json", name)
        mt = p.stat().st_mtime
        if not m or not ctx.within(mt):
            continue
        req = f"req-{m.group(1)}.json"
        ev = {"id": m.group(1), "res": ctx.put(rel)}
        if req in files:
            ev["req"] = ctx.put(f"{STATE}/desktop/{req}")
        ctx.emit(mt, "desktop", f"{rel}:1", **ev)


def do_test_windows(ctx: Day) -> None:
    """dispatch_guard.py (run-one.sh --test / test-off) writes state/test-windows.json from
    outside the relay: one entry opened at `since`, closed at `until`."""
    rel = f"{STATE}/test-windows.json"
    try:
        wins = json.loads((ctx.dd / rel).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return
    for w in wins if isinstance(wins, list) else []:
        for key, op in (("since", "test_window_open"), ("until", "test_window_close")):
            try:
                t = datetime.fromisoformat(w[key]).timestamp() if w.get(key) else None
            except (KeyError, ValueError):
                t = None
            if ctx.within(t):
                entry = dict(w) if op == "test_window_close" else {**w, "until": None}
                ctx.emit(t, "file", f"{rel}:1", path=machine(rel), op=op, entry=entry)


def do_other_files(ctx: Day, seed_files: list) -> None:
    """Files no handler above owns (MaaEnd on_error pictures and record/, mxu-agent logs,
    AUTO-MAS runtime logs, ...): written at their mtime inside the day, present at t0
    when older. State files are seed.py's."""
    for dirpath, _dirs, names in os.walk(ctx.dd):
        for name in names:
            rel = str((Path(dirpath) / name).relative_to(ctx.dd))
            if rel in ctx.claimed or rel.startswith(SKIP_PREFIXES + (RELAY_HOME + "/", HIST + "/")):
                continue
            mt = (ctx.dd / rel).stat().st_mtime
            how = ("raw" if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".zip"))
                   else "json" if "/config/" in rel and name.endswith(".json") else "redact")
            if ctx.within(mt):
                ctx.emit(mt, "file", f"{rel}:1", path=machine(rel), op="write", **ctx.put(rel, how))
            elif mt < ctx.t0:
                ref = ctx.put(rel, how)
                seed_files.append({"path": machine(rel), **ref})


# ------------------------------------------------------------------ main
def pulled_at(dd: Path) -> "float | None":
    """The moment the pull was packed: the earliest archive's "packed" stamp in MANIFEST.json."""
    try:
        man = json.loads((dd / "_pull" / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ts = [datetime.strptime(v["packed"], "%Y-%m-%d %H:%M:%S %z").timestamp()
          for v in (man.get("archives") or {}).values() if isinstance(v, dict) and v.get("packed")]
    return min(ts) if ts else None


def dump_seed(sd: dict) -> str:
    """seed.json: indented, except `files`, one compact entry per line. An entry's
    corpus file is files/<path without the drive colon> unless it names another."""
    sd = dict(sd)
    files = sd.pop("files")
    rows = []
    for f in files:
        f = dict(f)
        if f.get("file") == "files/" + f["path"].replace(":", "", 1):
            f.pop("file")
        rows.append("  " + json.dumps(f, ensure_ascii=False, separators=(",", ":")))
    head = json.dumps(sd, ensure_ascii=False, indent=1)
    return head[:-2] + ',\n "files": [\n' + ",\n".join(rows) + "\n ]\n}\n"


def build(day: str, dd: Path, corpus_root: Path, days_dir: Path, until: "str | None") -> Day:
    import seed  # noqa: PLC0415  sibling module; imports this one

    t0 = day_start(day)
    t1 = t0 + 86400
    pull = pulled_at(dd)
    if until:
        t1 = min(t1, datetime.fromisoformat(until).timestamp())
    if pull is not None and t1 > pull:
        t1 = pull                      # the record ends at the pull (10-13: 15:26:37)
    ctx = Day(day, t0, t1, dd, corpus_root / day)
    ctx.corpus.mkdir(parents=True, exist_ok=True)
    ctx.recs, ctx.relay_size = read_relay_log(dd / RELAY_LOG, int(day[:4]), int(day[5:7]))
    ctx.claimed.add(RELAY_LOG)
    relay_ref = ctx.put(RELAY_LOG)
    do_runs(ctx)
    boots = do_power(ctx)
    do_orders(ctx)
    do_net(ctx)
    do_logs(ctx)
    cfg = do_mas_config(ctx)
    do_desktop(ctx)
    do_test_windows(ctx)
    other: list = []
    do_other_files(ctx, other)
    sd = seed.build(ctx, boots=boots, relay_ref=relay_ref, mas_config=cfg, other_files=other)

    ctx.events.sort(key=lambda e: (e[0], e[1]))
    lines = [json.dumps(ev, ensure_ascii=False, separators=(",", ":")) for _t, _s, ev in ctx.events]
    text = "\n".join(lines) + "\n"
    out = days_dir / day
    out.mkdir(parents=True, exist_ok=True)
    (out / "events.jsonl").write_text(text, encoding="utf-8")
    (out / "seed.json").write_text(dump_seed(sd), encoding="utf-8")
    (ctx.corpus / "events.jsonl").write_text(text, encoding="utf-8")
    man = {"day": day, "t0": iso(t0), "t1": iso(t1), "daydata": str(dd),
           "pulled_at": iso(pull) if pull else None, "files": dict(sorted(ctx.manifest.items()))}
    (ctx.corpus / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n",
                                              encoding="utf-8")
    return ctx


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("day", help="Beijing day, YYYY-MM-DD")
    ap.add_argument("--daydata", required=True, type=Path, help="pull dir (scripts/mac/pull-day.sh)")
    ap.add_argument("--corpus", type=Path, default=CORPUS_ROOT)
    ap.add_argument("--days", type=Path, default=DAYS_DIR, help="where days/<D>/ go (repo)")
    ap.add_argument("--until", help="ISO time to stop at; default D+1 00:00, or the pull when it is earlier")
    a = ap.parse_args(argv)
    ctx = build(a.day, a.daydata.expanduser().resolve(), a.corpus.expanduser(), a.days, a.until)
    kinds = {}
    for _t, _s, ev in ctx.events:
        kinds[ev["kind"]] = kinds.get(ev["kind"], 0) + 1
    print(f"{a.day}: {len(ctx.events)} events {dict(sorted(kinds.items()))}; "
          f"corpus {ctx.corpus} ({len(ctx.manifest)} files)")
    for n in ctx.notes:
        print("  note:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
