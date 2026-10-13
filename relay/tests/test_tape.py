"""The relay's day tape (ark_relay/features/selfcheck/tape.py, daysim W8).

* the hooks: mas_client.mas_post, engine._automas_snapshot, shutdown.shutdown_event_xml,
  maintenance._get, efstatus.update_hint and banners._json / _text each put what they
  received on the tape, and still return / raise exactly as before;
* recording never gets in the way: a broken tape folder or a failing write changes
  nothing the caller sees; before install() nothing is written at all;
* masking: the secret shapes, key-name masking and the game UID label never reach the
  file (the lists are the ones scripts/mac/redact.py and slice.py use);
* the day cap (one `truncated` line, then nothing, also after a restart), pruning of old
  day files, the Beijing day boundary, and repeats written once (also across a restart);
* round trip: the 2026-10-09 maintenance notice, hand-written in days/2026-10-09/
  outside.jsonl, is served to the real maintenance reader with the tape on; slice.py
  turns that tape into `web` events at the same times with the same answers, and the
  World's own handler (World.state_effect) replays both into the same window. The
  config read at boot becomes the t0 `mas_config` in place of the reconstructed one.

Sizes behind DAY_CAP_BYTES / BODY_CAP, measured 2026-10-14 by replaying every recorded
day (relay/tests/daysim/run.py --all --keep) with the hooks in place: 0.45 MB per day
(10-06 453 804 B, 10-07 450 817, 10-08 450 194, 10-09 455 531, 10-11 457 539, 10-12
451 810, 10-13 448 000 bytes), 94 % of it web answers; the biggest single answer
210 425 bytes (a banner source); 14-28 AUTO-MAS lines a day after repeats are dropped.
"""
import hashlib
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "relay"), str(HERE), str(HERE / "daysim"), str(ROOT / "scripts" / "mac")]
from _tmp import tmpdir  # noqa: E402

os.environ["ARK_STATE_DIR"] = str(tmpdir())
os.environ["ARK_MAS_PORT"] = "36163"

try:
    from ark_relay.features.selfcheck import tape
except ImportError:          # the code before W8: every check below fails at its assertion
    tape = None

BJ = timezone(timedelta(hours=8))
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


def require(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok else f": {detail}"))
    if not ok:
        fails.append(name)


def bj(*a) -> datetime:
    return datetime(*a, tzinfo=BJ)


class Clock:
    """tape's `datetime`, with now() pinned to `at` (Beijing)."""
    at = bj(2026, 10, 9, 8, 48, 56)

    class DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return Clock.at.astimezone(tz) if tz else Clock.at.replace(tzinfo=None)


def lines(state: Path, day: str) -> list[dict]:
    p = state / "tape" / f"{day}.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


class Resp:
    """What urlopen hands back: a context manager with read() and a status."""
    def __init__(self, body: bytes, status: int = 200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self.body


def serve(table: dict):
    """A urlopen answering by URL prefix: bytes -> 200, an exception -> raised."""
    calls = []

    def urlopen(req, timeout=None, **k):
        url = req if isinstance(req, str) else req.full_url
        calls.append(url)
        for prefix, ans in table.items():
            if url.startswith(prefix):
                if isinstance(ans, BaseException):
                    raise ans
                return Resp(ans)
        raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
    urlopen.calls = calls
    return urlopen


def fresh(day_at: datetime, automas: "Path | None" = None) -> Path:
    Clock.at = day_at
    st = tmpdir()
    tape.install(st, automas)
    return st


# ---------------------------------------------------------------------------------
def check_noop_before_install() -> None:
    print("\n[nothing is written before install()]")
    tape.uninstall()
    st = Path(os.environ["ARK_STATE_DIR"])
    tape.answer("mas", "/api/queue/get", body=b"{}")
    tape.syslog((1074,), 60, [])
    require("no tape folder appears", not (st / "tape").exists(), list(st.iterdir()))


def check_hooks() -> None:
    print("\n[each hook puts what it received on the tape and behaves as before]")
    from ark_relay.core import engine  # noqa: PLC0415
    from ark_relay.features.banners import banners  # noqa: PLC0415
    from ark_relay.features.maintenance import efstatus, maintenance  # noqa: PLC0415
    from ark_relay.features.phone import mas_client  # noqa: PLC0415
    from ark_relay.features.shutdown import shutdown  # noqa: PLC0415

    st = fresh(bj(2026, 10, 12, 10, 0, 0))
    base = "http://127.0.0.1:36163"
    real = urllib.request.urlopen
    snap = {"tasks": [{"taskId": "t1", "task_info": [{"name": "MAA", "status": "运行"}]}]}
    urllib.request.urlopen = serve({
        base + "/api/queue/get": json.dumps({"code": 200, "data": {"q": 1}}).encode(),
        base + "/api/dispatch/runtime-snapshot": json.dumps(snap).encode(),
        base + "/api/dispatch/start": urllib.error.HTTPError(base + "/api/dispatch/start", 500, "boom", {}, None),
        efstatus._URL: json.dumps({"code": 0, "data": {}}).encode(),
        "https://prts.wiki/": json.dumps({"parse": {"wikitext": {"*": "x"}}}).encode(),
        "https://endfield.hypergryph.com/": "<html>ef</html>".encode(),
        "https://ak.hypergryph.com/api/news": json.dumps({"code": 0, "data": {"list": [], "end": True}}).encode(),
    })
    try:
        check("mas_post returns the decoded answer", mas_client.mas_post("/api/queue/get", {"queueId": "q"}),
              {"code": 200, "data": {"q": 1}})
        mas_client.mas_post("/api/queue/get", {"queueId": "q"})             # same answer: not written again
        try:
            mas_client.mas_post("/api/dispatch/start", {"mode": "x"})
            raised = None
        except urllib.error.HTTPError as exc:
            raised = exc.code
        check("mas_post still raises the HTTP error", raised, 500)
        check("runtime-snapshot still parsed", engine._automas_snapshot(), snap)
        check("efstatus reads as before (no update today)", efstatus.update_hint(now=bj(2026, 10, 12, 10)), "")
        check("banners._json returns the answer", banners._json("https://prts.wiki/api.php?page=x", "ua"),
              {"parse": {"wikitext": {"*": "x"}}})
        check("banners._text returns the page", banners._text("https://endfield.hypergryph.com/v", "ua"),
              "<html>ef</html>")
        check("maintenance._get returns the page",
              json.loads(maintenance._get("https://ak.hypergryph.com/api/news?category=NEWS&page=1"))["code"], 0)
        try:
            maintenance._get("https://nowhere.invalid/x", timeout=1)
            raised = None
        except Exception as exc:  # noqa: BLE001
            raised = type(exc).__name__
        check("maintenance._get still raises what urlopen raised", raised, "URLError")
    finally:
        urllib.request.urlopen = real

    # The System log: the real reader through a stand-in win32evtlog.
    from fake_proc import SysEvent  # noqa: PLC0415
    ev = SysEvent(bj(2026, 10, 12, 9, 59, 1).timestamp(), 1074, "User32",
                  {"param1": r"C:\WINDOWS\system32\shutdown.exe (INS)", "param7": "NT AUTHORITY\\SYSTEM"})
    evtlog = SimpleNamespace(EvtQueryChannelPath=1, EvtQueryReverseDirection=0x200, EvtRenderEventXml=1,
                             EvtQuery=lambda *a: iter([ev]), EvtRender=lambda e, flag: e.xml())
    evtlog.EvtNext = lambda q, n: tuple(x for _, x in zip(range(n), q, strict=False))
    sys.modules["win32evtlog"] = evtlog
    try:
        check("shutdown_event_xml returns the event", shutdown.shutdown_event_xml(600), [ev.xml()])
        shutdown.shutdown_event_xml(600)                                    # the same event: not again
    finally:
        del sys.modules["win32evtlog"]
    check("unreadable System log: still None", shutdown.shutdown_event_xml(600), None)

    recs = lines(st, "20261012")
    kinds = [(r["kind"], r.get("path") or r.get("url") or "") for r in recs]
    check("the tape's lines, in order", kinds, [
        ("boot", ""), ("mas", "/api/queue/get"), ("mas", "/api/dispatch/start"),
        ("mas", "/api/dispatch/runtime-snapshot"), ("web", efstatus._URL),
        ("web", "https://prts.wiki/api.php?page=x"), ("web", "https://endfield.hypergryph.com/v"),
        ("web", "https://ak.hypergryph.com/api/news?category=NEWS&page=1"), ("web", "https://nowhere.invalid/x"),
        ("syslog", ""), ("syslog", "")])
    q = recs[1]
    check("an AUTO-MAS answer: request, status, length, hash, body",
          (q["req"], q["status"], q["len"], q["json"]),
          ({"queueId": "q"}, 200, len(json.dumps({"code": 200, "data": {"q": 1}})), {"code": 200, "data": {"q": 1}}))
    check("its hash is the received bytes'", q["sha256"],
          hashlib.sha256(json.dumps({"code": 200, "data": {"q": 1}}).encode()).hexdigest())
    check("a failed call: status and error", (recs[2]["status"], recs[2]["error"].split(":")[0]), (500, "HTTPError"))
    check("a page that is not JSON is kept as text", recs[6]["text"], "<html>ef</html>")
    check("maintenance's answer carries the real status", recs[7]["status"], 200)
    check("the System log event as read", recs[9]["events"], [ev.xml()])
    check("the unreadable read", recs[10]["error"].split(":")[0], "ModuleNotFoundError")


def check_never_in_the_way() -> None:
    print("\n[a broken tape changes nothing the relay sees]")
    from ark_relay.features.phone import mas_client  # noqa: PLC0415
    blocker = tmpdir() / "state-is-a-file"
    blocker.write_text("x")
    Clock.at = bj(2026, 10, 12, 11)
    tape.install(blocker)                              # <file>/tape cannot be made
    real = urllib.request.urlopen
    urllib.request.urlopen = serve({"http://127.0.0.1:36163/api/queue/get": b'{"code": 200}'})
    try:
        check("mas_post with an unwritable tape folder", mas_client.mas_post("/api/queue/get"), {"code": 200})
        st = fresh(bj(2026, 10, 12, 11))
        broken = tape._append
        tape._append = lambda *a: (_ for _ in ()).throw(OSError(28, "No space left on device"))
        try:
            check("mas_post with a write that fails", mas_client.mas_post("/api/queue/get"), {"code": 200})
            tape.syslog((1074,), 60, ["<Event/>"])
            tape.answer("web", "https://x.invalid/", body=b"\xff\xfe broken")
        finally:
            tape._append = broken
        require("no exception left any entry point", True)
        require("nothing half-written", not (st / "tape" / "20261012.jsonl").exists()
                or all(json.loads(x) for x in (st / "tape" / "20261012.jsonl").read_text().splitlines()))
    finally:
        urllib.request.urlopen = real


def check_masking() -> None:
    print("\n[secrets never reach the file]")
    import redact  # noqa: PLC0415
    import slice as sl  # noqa: PLC0415
    from pack import identity_pattern  # noqa: PLC0415
    check("key-name hints are scripts/mac/redact.py's", tape.KEY_HINTS, redact.SECRET_KEY_HINTS)
    check("key-name exceptions are scripts/mac/redact.py's", tape.KEY_ALLOW, redact.SECRET_KEY_ALLOW)
    check("slice.py masks the tape's shapes", sl.SECRET_PATTERNS, tape.SECRET_PATTERNS)
    check("tape's mask is redact.py's", tape.MASK, redact.MASK)
    st = fresh(bj(2026, 10, 12, 12))
    akid = "AK" + "ID" + "Ab1" * 11                        # built here so this file holds no key shape
    hook = "https://qyapi.weixin.qq.com/cgi-bin/" + "webhook/send?key=" + "1a2b3c4d-" * 4
    uid = "\u7279\u5f81\u7801" + "\uff1a" + "123456789"        # the UID label, built here (lint item 12)
    body = json.dumps({"link": f"x.zip?q-ak={akid}&q-signature={'ab' * 20}", "hook": hook,
                       "Password": "hunter2hunter2", "MirrorChyanCDK": "x" * 20, "ocr": f"id {uid}",
                       "keyword": "kept"}).encode()
    tape.answer("web", hook, req={"SendKey": "SCT" + "q" * 20}, body=body)
    tape.answer("mas", "/api/x", body=("plain " + uid).encode())
    raw = (st / "tape" / "20261012.jsonl").read_bytes()
    check("no secret shape left (slice.secret_hits)", sl.secret_hits(raw), [])
    require("no game UID left (lint item 12's pattern)", not identity_pattern().search(raw))
    rec = [json.loads(x) for x in raw.decode().splitlines()][1]
    check("secret-named values masked, others kept",
          (rec["json"]["Password"], rec["json"]["MirrorChyanCDK"], rec["json"]["keyword"], rec["req"]["SendKey"]),
          (redact.MASK, redact.MASK, "kept", redact.MASK))
    require("the URL's webhook key masked", rec["url"].endswith("key=REDACTED"), rec["url"])
    require("UID digits masked to their length", "UIDREDACT" in rec["json"]["ocr"], rec["json"]["ocr"])
    check("hash is of the received bytes", rec["sha256"], hashlib.sha256(body).hexdigest())


def check_cap_and_prune() -> None:
    print("\n[day cap, restart after it, old days pruned]")
    cap = tape.DAY_CAP_BYTES
    tape.DAY_CAP_BYTES = 2000
    try:
        st = fresh(bj(2026, 10, 12, 13))
        for i in range(40):
            tape.answer("mas", "/api/dispatch/runtime-snapshot", body=json.dumps({"i": i, "pad": "x" * 50}).encode())
        p = st / "tape" / "20261012.jsonl"
        recs = lines(st, "20261012")
        check("exactly one truncated line, the last", [r["kind"] for r in recs].count("truncated"), 1)
        check("... and it is the last line", recs[-1]["kind"], "truncated")
        size = p.stat().st_size
        require("the file stays near the cap", size <= 2000 + 200, size)
        tape.install(st)                                  # a restart the same day
        tape.answer("mas", "/api/other", body=b"{}")
        check("nothing more after a restart", p.stat().st_size, size)
    finally:
        tape.DAY_CAP_BYTES = cap
    st = tmpdir()
    d = st / "tape"
    d.mkdir()
    for name in ("20260920.jsonl", "20260929.jsonl", "20260930.jsonl", "20261011.jsonl", "notes.txt"):
        (d / name).write_text("{}\n")
    Clock.at = bj(2026, 10, 13, 0, 5)
    tape.install(st)
    check("days before the 14 kept are deleted, other files kept", sorted(p.name for p in d.iterdir()),
          ["20260930.jsonl", "20261011.jsonl", "20261013.jsonl", "notes.txt"])


def check_day_boundary_and_repeats() -> None:
    print("\n[Beijing day boundary; a repeat is written once, also across a restart]")
    automas = tmpdir()
    (automas / "config").mkdir()
    (automas / "config" / "QueueConfig.json").write_text('{"Queue": 1, "Token": "abc"}', encoding="utf-8")
    st = fresh(bj(2026, 10, 12, 23, 59, 50), automas)
    tape.answer("mas", "/api/queue/get", body=b'{"a": 1}')
    Clock.at = bj(2026, 10, 12, 23, 59, 58)
    tape.answer("mas", "/api/queue/get", body=b'{"a": 1}')
    Clock.at = bj(2026, 10, 13, 0, 0, 1)                 # 2026-10-12 16:00:01 UTC
    tape.answer("mas", "/api/queue/get", body=b'{"a": 1}')
    Clock.at = bj(2026, 10, 13, 0, 5)
    tape.answer("mas", "/api/queue/get", body=b'{"a": 1}')
    Clock.at = bj(2026, 10, 13, 0, 9)
    tape.answer("mas", "/api/queue/get", body=b'{"a": 2}')
    tape.install(st, automas)                           # a restart
    Clock.at = bj(2026, 10, 13, 0, 10)
    tape.answer("mas", "/api/queue/get", body=b'{"a": 2}')
    d12, d13 = lines(st, "20261012"), lines(st, "20261013")
    cfg3 = ["config"] * len(tape.CONFIG_FILES)
    check("10-12: boot, the config files, the answer once", [r["kind"] for r in d12], ["boot", *cfg3, "mas"])
    check("10-13 opens with the config read at midnight, then the answer again",
          [r["kind"] for r in d13], ["mas", *cfg3, "mas", "boot"])
    check("config: masked by key name; a missing file says so",
          [(r["file"], r.get("json") or r["error"].split(":")[0]) for r in d12[1:4]],
          [("QueueConfig.json", {"Queue": 1, "Token": tape.MASK}), ("ScriptConfig.json", "FileNotFoundError"),
           ("PlanConfig.json", "FileNotFoundError")])
    changed = d13[1 + len(cfg3)]
    check("a changed answer says when the old one was last seen, and how often",
          (changed["json"], changed["prev_seen"], changed["repeats"]), ({"a": 2}, "2026-10-13T00:05:00.000+08:00", 1))
    check("10-13 has one config snapshot (the restart found it)", [r["kind"] for r in d13].count("config"), len(cfg3))


def check_round_trip() -> None:
    print("\n[round trip: 10-09's maintenance notice, recorded by the real reader, replays as hand-written]")
    import fake_net  # noqa: PLC0415
    import slice as sl  # noqa: PLC0415
    import world as W  # noqa: PLC0415
    from ark_relay.features.maintenance import maintenance  # noqa: PLC0415

    day = "2026-10-09"
    hand = [e for e in W.load_outside(day) if e["kind"] == "web"]
    check("10-09 has the two hand-written web answers", len(hand), 2)
    t_read = bj(2026, 10, 9, 8, 48, 56)                   # relay.log:29955, the relay's first look

    class Sched:
        def __init__(self, t):
            self.t, self.outs = t, []

        def now(self):
            return self.t

        def park(self, timeout, ready):
            return ready()

        def out(self, kind, **f):
            self.outs.append((kind, f))

        wake = kick = lambda self: None

    def world_net(events):
        """A FakeNet given `events` through the World's own handler (state_effect)."""
        net = fake_net.FakeNet(Sched(t_read.timestamp())).install()
        stand_in = SimpleNamespace(net=net)
        for it in W.timeline(events):
            W.World.state_effect(stand_in, it, live=True)
        return net

    def window():
        win = maintenance.arknights_window(now=t_read, get=maintenance._get)
        return (win[0].isoformat(), win[1].isoformat(), win[2]) if win else None

    # 1. Record: the hand-written answers served, the real reader runs with the tape on.
    automas = tmpdir()
    (automas / "config").mkdir()
    qc = automas / "config" / "QueueConfig.json"
    qc.write_text(json.dumps({"QueueConfig": {"Name": "q"}, "SecretKey": "s3cr3t-value"}), encoding="utf-8")
    os.utime(qc, (bj(2026, 10, 8, 22).timestamp(),) * 2)
    st = fresh(bj(2026, 10, 9, 8, 30), automas)         # the day's first boot
    Clock.at = t_read
    try:
        world_net(hand)
        got_hand = window()
    finally:
        fake_net.FakeNet.uninstall()
    check("the hand-written answers give the logged window", got_hand,
          ("2026-10-09T06:00:00+08:00", "2026-10-09T12:00:00+08:00", got_hand and got_hand[2]))

    # 2. Slice the tape as the pull would hold it.
    dd = tmpdir()
    (dd / sl.TAPE).mkdir(parents=True)
    (dd / sl.TAPE / "20261009.jsonl").write_bytes((st / "tape" / "20261009.jsonl").read_bytes())
    t0 = sl.day_start(day)
    ctx = sl.Day(day, t0, t0 + 86400, dd, tmpdir())
    taped = sl.do_tape(ctx)
    evs = [ev for _t, _s, ev in sorted(ctx.events, key=lambda e: (e[0], e[1]))]
    web = [e for e in evs if e["kind"] == "web"]
    check("the tape gives as many web answers as were hand-written", len(web), len(hand))
    check("same times (from 00:00) and same answers", [(e["t"], e["answer"]) for e in web],
          [(e["t"], e["answer"]) for e in hand])
    require("each tape URL starts with the hand-written prefix",
            all(w["prefix"].startswith(h["prefix"]) for w, h in zip(web, hand, strict=True)),
            [(w["prefix"], h["prefix"]) for w, h in zip(web, hand, strict=False)])

    # 3. Replay: the World's handler with the tape's events gives the same window.
    try:
        world_net(web)
        got_tape = window()
    finally:
        fake_net.FakeNet.uninstall()
    check("replayed from the tape: the same window", got_tape, got_hand)

    # 4. The config the relay found at boot is the day's t0 config.
    cfg = [e for e in evs if e["kind"] == "mas_config"]
    check("one t0 mas_config from the tape", [(e["t"], e["path"], e.get("from_tape")) for e in cfg],
          [("2026-10-09T00:00:00+08:00", "D:/ark/automas/config/QueueConfig.json", True)])
    check("... which replaces the reconstructed one", taped, {"QueueConfig.json"})
    data = json.loads((ctx.corpus / cfg[0]["file"]).read_text(encoding="utf-8"))
    check("... with the recorded content, secret masked", data,
          {"QueueConfig": {"Name": "q"}, "SecretKey": tape.MASK})


def check_syslog_slice() -> None:
    print("\n[a System log event on the tape becomes a syslog event at its own time]")
    import slice as sl  # noqa: PLC0415
    from fake_proc import SysEvent  # noqa: PLC0415
    ev = SysEvent(bj(2026, 10, 12, 21, 31, 5).timestamp(), 1075, "User32",
                  {"param1": "INS", "param2": "INS\\Administrator"})
    st = fresh(bj(2026, 10, 12, 21, 32))
    tape.syslog((1074, 1075), 600, [ev.xml()])
    dd = tmpdir()
    (dd / sl.TAPE).mkdir(parents=True)
    (dd / sl.TAPE / "20261012.jsonl").write_bytes((st / "tape" / "20261012.jsonl").read_bytes())
    t0 = sl.day_start("2026-10-12")
    ctx = sl.Day("2026-10-12", t0, t0 + 86400, dd, tmpdir())
    sl.do_tape(ctx)
    got = [(e["t"], e["event_id"], e["provider"], e["data"]) for _t, _s, e in ctx.events if e["kind"] == "syslog"]
    check("event id, provider, data and time as logged", got,
          [("2026-10-12T21:31:05+08:00", 1075, "User32", {"param1": "INS", "param2": "INS\\Administrator"})])


if tape is None:
    require("ark_relay.features.selfcheck.tape exists", False, "no tape module")
else:
    tape.datetime = Clock.DT
    check_noop_before_install()
    check_hooks()
    check_never_in_the_way()
    check_masking()
    check_cap_and_prune()
    check_day_boundary_and_repeats()
    check_round_trip()
    check_syslog_slice()
    tape.uninstall()
    require("no thread left behind", threading.active_count() <= 2, threading.enumerate())

print(f"\n{'all checks passed' if not fails else f'{len(fails)} failed: {fails}'}")
sys.exit(1 if fails else 0)
