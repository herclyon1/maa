"""The 2026-10-06 fix bill L: today's relay.log to COS, one object per day.

Four things pinned here, per the bill:
* a relay-error push ends with 「日志：<链接>，出事时刻 HH:MM」 when the upload
  landed; a failed upload does not block the push and is noted daily-report-only;
* the shutdown moment uploads the final copy before the power-off command;
* the error path uploads at most once a minute (the same key overwrites anyway);
* the whole-day log is capped: a bigger day uploads its last part and says so.

The uploader is a fake; nothing here touches the real COS bucket.
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import errwatch, error_evidence, texts          # noqa: E402
from ark_relay.config import SERVER_TZ, Config                 # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class FakeUp:
    """One COS store that records what was PUT, in order, and answers with a URL."""

    def __init__(self, fail=None):
        self.uploads = []          # (key, bytes)
        self.fail = fail           # Exception to raise on upload, or None
        self.timeouts = []         # the timeout each PUT was given

    def upload(self, path, timeout=900):
        self.timeouts.append(timeout)
        data = path.read_bytes()
        key = f"daily/{path.name}"
        if self.fail is not None:
            raise self.fail
        self.uploads.append((key, data))
        return {"name": path.name, "url": f"https://host/{key}", "store": "cos", "key": key}


def cfg_with(relay_log: "Path | None", automas: "Path | None", state: Path) -> Config:
    cfg = Config()
    cfg.state_dir = state
    cfg.automas_dir = automas
    cfg.cos_secret_id = cfg.cos_secret_key = cfg.cos_bucket = cfg.cos_region = "x"
    if relay_log is not None:
        os.environ["ARK_LOG_FILE"] = str(relay_log)
    else:
        os.environ.pop("ARK_LOG_FILE", None)
    return cfg


DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
NOW = DAY.replace(hour=9, minute=52)


def stamp(day: datetime, hh: int, mm: int, fmt: str = "%m-%d %H:%M:%S") -> str:
    """The server-clock moment day hh:mm as the machine stamps it: in its own local
    time (relay.log: logging's asctime, time.localtime; AUTO-MAS's app.log the
    same), which evidence._line_ts reads back as local time. On the machine local
    time is Beijing; the Mac (Tokyo) was an hour off, the Windows CI runner (UTC)
    eight - 09:00 written as Beijing read back as 17:00 and fell outside the
    00:00-09:52 day (run 37519943859)."""
    return day.replace(hour=hh, minute=mm).astimezone().strftime(fmt)


def write_day_log(p: Path, day: datetime, lines):
    p.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for hh, mm, text in lines:
        out.append(f"{stamp(day, hh, mm)} INFO    ark.test  {text}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


print("[whole-day relay.log + app.log go up as one dated object each, same key all day]")
st = tmpdir()
relay = tmpdir() / "relay.log"
automas = tmpdir() / "AUTO-MAS"
write_day_log(relay, DAY, [(9, 0, "first"), (9, 52, "second")])
(automas / "debug").mkdir(parents=True)
app = automas / "debug" / "app.log"
app.write_text(f"{stamp(DAY, 9, 50, '%Y-%m-%d %H:%M:%S')} INFO first\n", encoding="utf-8")
up = FakeUp()
error_evidence._last_attempt[0] = 0.0
got = error_evidence.upload_daily_logs(cfg_with(relay, automas, st), force=True, now=NOW,
                                       clock=lambda: 1000.0, uploader=up)
check("both objects went up", sorted(k.split("/")[1] for k, _ in up.uploads),
      [f"automas-app-{DAY:%Y-%m-%d}.log", f"relay-{DAY:%Y-%m-%d}.log"])
check("the relay object's URL is returned",
      got["url"], f"https://host/daily/relay-{DAY:%Y-%m-%d}.log")
check("the relay object holds both lines", b"second" in dict(up.uploads)[f"daily/relay-{DAY:%Y-%m-%d}.log"])
check("not truncated", got["truncated"], False)

print("\n[the push link is the signed GET: the bucket is private, the plain URL answers 403]")


class SignedUp(FakeUp):
    def upload(self, path, timeout=900):
        got = super().upload(path, timeout)
        return dict(got, page=got["url"] + "?q-signature=abc")


error_evidence._last_attempt[0] = 0.0
got = error_evidence.upload_daily_logs(cfg_with(relay, None, st), force=True, now=NOW,
                                       clock=lambda: 1000.0, uploader=SignedUp())
check("the signed page is what the push carries",
      got["url"], f"https://host/daily/relay-{DAY:%Y-%m-%d}.log?q-signature=abc")
from ark_relay.evidence import Cos  # noqa: E402
cos = Cos("AKID", "secret", "b-1", "ap-shanghai")
link = cos.signed_get("daily/relay-x.log", ttl=60)
check("Cos.signed_get: same object URL plus a GET signature",
      link.split("?")[0] == "https://b-1.cos.ap-shanghai.myqcloud.com/daily/relay-x.log"
      and "q-signature=" in link and cos.authorization("GET", "daily/relay-x.log", ttl=60) in link)
span = cos.signed_get("k").split("q-sign-time=")[1].split("&")[0].split(";")
check("Cos.signed_get lasts a week by default", int(span[1]) - int(span[0]), 7 * 86400)
check("a log goes up as text (opens in the phone's browser)", Cos._content_type(Path("relay-x.log")),
      "text/plain; charset=utf-8")
check("anything else stays octet-stream", Cos._content_type(Path("x.zip")), "application/octet-stream")

print("\n[the poster OCR cache goes up as a sample, once per change, and never breaks the push]")
st_ocr = tmpdir()
(st_ocr / "desktop").mkdir()
(st_ocr / "desktop" / "image-ocr.json").write_text('{"https://x/poster.jpg#2x": []}', encoding="utf-8")
up = FakeUp()
error_evidence._last_attempt[0] = 0.0
error_evidence._ocr_sent[0] = 0.0
error_evidence.upload_daily_logs(cfg_with(relay, None, st_ocr), force=True, now=NOW, clock=lambda: 1000.0, uploader=up)
check("the OCR cache went up next to the relay log",
      sorted(k.split("/")[1] for k, _ in up.uploads), [f"image-ocr-{DAY:%Y-%m-%d}.json", f"relay-{DAY:%Y-%m-%d}.log"])
error_evidence.upload_daily_logs(cfg_with(relay, None, st_ocr), force=True, now=NOW, clock=lambda: 1000.0, uploader=up)
check("an unchanged cache is not sent again", sum(k.endswith(".json") for k, _ in up.uploads), 1)
(st_ocr / "desktop" / "image-ocr.json").write_text('{"https://x/poster2.jpg#2x": []}', encoding="utf-8")
os.utime(st_ocr / "desktop" / "image-ocr.json", (error_evidence._ocr_sent[0] + 5, error_evidence._ocr_sent[0] + 5))
error_evidence.upload_daily_logs(cfg_with(relay, None, st_ocr), force=True, now=NOW, clock=lambda: 1000.0, uploader=up)
check("a changed cache is sent again", sum(k.endswith(".json") for k, _ in up.uploads), 2)
error_evidence._ocr_sent[0] = 0.0
got = error_evidence.upload_daily_logs(cfg_with(relay, None, st_ocr), force=True, now=NOW, clock=lambda: 1000.0,
                                       uploader=FakeUp(fail=RuntimeError("boom")))
check("a failed upload of the samples is not an error of the push", [e for e in got["errors"] if "image-ocr" in e], [])

print("\n[error path: one upload a minute at most; force bypasses the throttle]")
up = FakeUp()
error_evidence._last_attempt[0] = 0.0
error_evidence.upload_daily_logs(cfg_with(relay, None, st), force=False, now=NOW, clock=lambda: 1000.0, uploader=up)
got = error_evidence.upload_daily_logs(cfg_with(relay, None, st), force=False, now=NOW, clock=lambda: 1005.0, uploader=up)
check("second call inside the minute was skipped", got["skipped"], True)
check("so only the first went up", len(up.uploads), 1)
check("the skipped call still carries the link of the object already there",
      got["url"], f"https://host/daily/relay-{DAY:%Y-%m-%d}.log")
check("a PUT gets a 60 s timeout, not Cos.upload's 900 s default (a stalled line must not hold a push or the power-off)",
      set(up.timeouts), {error_evidence.UPLOAD_TIMEOUT_S})
error_evidence.upload_daily_logs(cfg_with(relay, None, st), force=True, now=NOW, clock=lambda: 1005.0, uploader=up)
check("force uploaded anyway (the shutdown final copy)", len(up.uploads), 2)

print("\n[a failed upload is reported in the result, never raised]")
error_evidence._last_attempt[0] = 0.0
got = error_evidence.upload_daily_logs(cfg_with(relay, None, st), force=True, now=NOW,
                                       clock=lambda: 1000.0, uploader=FakeUp(fail=RuntimeError("boom")))
check("errors carry the reason", got["errors"], ["relay: RuntimeError: boom"])

print("\n[the whole-day log is capped: the last part goes up and says so]")
big = tmpdir() / "big-relay.log"
big.write_bytes(f"{stamp(DAY, 9, 0)} INFO    ark.test  keepme\n".encode())
# Fake a day bigger than the cap by shrinking the cap for the test.
error_evidence._last_attempt[0] = 0.0
small_up = FakeUp()
old_cap = error_evidence.DAY_MAX_BYTES
error_evidence.DAY_MAX_BYTES = 40
try:
    body = "".join(f"{stamp(DAY, 9, i)} INFO    ark.test  line{i}\n" for i in range(10))
    big.write_text(body, encoding="utf-8")
    got = error_evidence.upload_daily_logs(cfg_with(big, None, st), force=True, now=NOW,
                                           clock=lambda: 1000.0, uploader=small_up)
    data = dict(small_up.uploads)[f"daily/relay-{DAY:%Y-%m-%d}.log"]
    check("the cap was applied", got["truncated"], True)
    check("the tail survived", b"line9" in data, True)
    check("the head was cut", b"line0" in data, False)
finally:
    error_evidence.DAY_MAX_BYTES = old_cap


print("\n[a relay-error push ends with 「日志：…」 when the upload landed]")
ARK_LOGGER = logging.getLogger(errwatch.ARK)


class Captures:
    """errwatch's notifier: records what reached the group, accepts everything."""

    def __init__(self):
        self.sent = []

    def send_group(self, title, body):
        self.sent.append((title, body))
        return []

    def send(self, title, body, **kw):
        self.sent.append((title, body))
        return []


def watch():
    sd = tmpdir()
    h = errwatch.ErrorKindAlert(Captures(), state_dir=sd, known={}, retry=(3600.0,),
                                fallback_after=1e9)
    ARK_LOGGER.addHandler(h)
    return h, sd


def unwatch(h):
    ARK_LOGGER.removeHandler(h)
    h.close()


real_up = error_evidence._last_attempt[0]
try:
    h, sd = watch()
    errwatch.set_evidence_uploader(lambda: {"url": "https://host/daily/relay-x.log", "at": "09:52",
                                            "truncated": False, "errors": []})
    logging.getLogger("ark.test_error_evidence").warning("something broke")
    h.drain(timeout=5.0)
    bodies = [b for t, b in h._notifier.sent]
    check("the push carries the log link",
          any("日志：https://host/daily/relay-x.log，出事时刻 " in b for b in bodies), True)
    check("the push itself went out", len(bodies), 1)
    unwatch(h)

    print("  …a failed upload does not block the push and is daily-report-only")
    h, sd = watch()
    errwatch.set_evidence_uploader(lambda: {"url": "", "at": "09:52", "truncated": False,
                                            "errors": ["relay: RuntimeError: boom"]})
    logging.getLogger("ark.test_error_evidence").warning("something broke again")
    h.drain(timeout=5.0)
    bodies = [b for t, b in h._notifier.sent]
    check("the push still went out", len(bodies), 1)
    check("it has no log link", any("日志：" in b for b in bodies), False)
    rows = errwatch.day_faults(sd, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
    daily = [r for r in rows if r.get("daily_only")]
    check("the failed upload is noted daily-only",
          [(r.get("daily_only"), "证据上传失败" in r.get("line", "")) for r in daily], [(True, True)])
    unwatch(h)

    # The deploy gate's coverage trace follows the main thread only; these two run on the
    # push thread above, so call them here too, directly, and check what they return.
    print("  …the link text and the daily-only note, called directly")
    check("link text: url and moment", texts.evidence_link("https://host/x.log", "09:52"),
          "日志：https://host/x.log，出事时刻 09:52")
    check("link text: says so when the day was cut", "只传了最后一部分" in texts.evidence_link("u", "09:52", True), True)
    h, sd = watch()
    h.note_daily("ark.evidence", "证据上传失败：direct")
    h.note_daily("ark.evidence", "证据上传失败：direct")
    rows = [r for r in errwatch.day_faults(sd, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
            if r.get("daily_only")]
    check("note_daily: one row, counted twice, daily-only", [(r.get("count"), r.get("daily_only")) for r in rows], [(2, True)])
    unwatch(h)
finally:
    errwatch.set_evidence_uploader(None)
    error_evidence._last_attempt[0] = real_up

print("\n[the shutdown moment uploads the final copy before the power-off command]")
from ark_relay.core import State                                      # noqa: E402
from ark_relay.notify import Notifier                                 # noqa: E402
from ark_relay import engine as eng_mod                               # noqa: E402

AUTOMAS2 = tmpdir() / "AUTO-MAS2"
(AUTOMAS2 / "config").mkdir(parents=True)
(AUTOMAS2 / "config" / "QueueConfig.json").write_text(json.dumps({
    "instances": [{"uid": "q1"}],
    "q1": {"Info": {"Name": "Evening-MAA", "TimeEnabled": True, "AfterAccomplish": "NoAction"},
           "SubConfigsInfo": {"TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "21:30"}}},
                              "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}}}}}), encoding="utf-8")
(AUTOMAS2 / "config" / "ScriptConfig.json").write_text(json.dumps({
    "instances": [{"uid": "s1"}],
    "s1": {"Info": {"Name": "arknights", "Path": "D:\\MAA"},
           "SubConfigsInfo": {"UserData": {"u1": {"Info": {"Name": "arknights"}}}}}}), encoding="utf-8")

cfg2 = Config()
cfg2.state_dir = tmpdir()
cfg2.automas_dir = AUTOMAS2
cfg2.shutdown_after_run = True
cfg2.shutdown_min_uptime = 0
E = eng_mod.Engine(cfg2, source=None, state=State(cfg2.state_dir), notifier=Notifier(cfg2))
E._scripts_running = lambda: False
E._idle_checkpoint = lambda now=None: False
E._handled_any = True
E._started_at = datetime(2026, 8, 21, 22, 20, tzinfo=SERVER_TZ)
E._last_round_manual = lambda now, entries: False
E._unfinished_queues = lambda now, entries: []
E._verify_outcome = lambda r: None
E._deferred_update_busy = lambda: False
E._report_cutoff = lambda now: now - timedelta(hours=1)
E.state.report_sent = lambda d: True
# The queue already ran: one done record in the ledger makes the gate pass.
day = "2026-08-21"
(E.state.dir / f"ledger-{day}.jsonl").write_text(json.dumps({
    "script": "MAA", "started": f"{day}T21:31:00+08:00", "finished": f"{day}T22:15:00+08:00",
    "ok": True, "run_id": "x"}) + "\n", encoding="utf-8")
E._shutdown_key = lambda now: day
E._boot_time = lambda now: datetime(2026, 8, 21, 21, 20, tzinfo=SERVER_TZ)

order = []
real_upload = error_evidence.upload_daily_logs
error_evidence.upload_daily_logs = lambda cfg, **kw: order.append("upload") or {"url": "", "at": "", "errors": []}
E._power_off = lambda: order.append("poweroff") or True
try:
    E._maybe_shutdown(datetime(2026, 8, 21, 23, 0, tzinfo=SERVER_TZ))
    check("the final upload runs before the power-off command", order, ["upload", "poweroff"])
finally:
    error_evidence.upload_daily_logs = real_upload

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
