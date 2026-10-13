"""The alarm copy (alertlog row) names the channel that actually delivered it.

Review 2026-10-13 s5 #4: an alarm the group robot refused and Server酱 took left a
row that looked like any group alarm, so the Mac could not tell where it went.
The channel comes from what Notifier._fan_out reports as delivered; "" when not
known. Rows written before the field existed (a real machine row, fixture
alerts-20261013-old-row.jsonl) must still read and merge fine.
"""
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                  COS_SECRET_ID="", COS_SECRET_KEY="", COS_BUCKET="", COS_REGION="",
                  ARK_ALERT_PUSH_URL="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core.config import Config  # noqa: E402
from ark_relay.core.notify import Notifier  # noqa: E402
from ark_relay.features.alarm import alertlog  # noqa: E402
from ark_relay.features.selfcheck import machinecheck as mc  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "alerts-20261013-old-row.jsonl"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ok   {label}" if ok else f"  FAIL {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Fake:
    def __init__(self, name, broken=False):
        self.name, self.broken, self.enabled = name, broken, True

    def send_text(self, *a):
        if self.broken:
            raise RuntimeError(f"{self.name} down")


class Pushes:
    """Stands in for macpush: keeps the rows instead of POSTing them."""

    def __init__(self):
        self.rows = []

    def push(self, row):
        self.rows.append(row)


def build(name, broken=()):
    cfg = Config()
    cfg.state_dir = TMP / name
    n = Notifier(cfg)
    n.serverchan = Fake("Server酱", "Server酱" in broken)
    n.wecom_bot = Fake("企业微信机器人", "企业微信机器人" in broken)
    n.wecom = Fake("企业微信", "企业微信" in broken)
    n._alerts = alertlog.AlertLog(cfg.state_dir)       # local only, no COS
    n._mac = Pushes()
    return n


def rows(n):
    day = alertlog.beijing().strftime("%Y%m%d")
    return mc.alert_rows(n._cfg.state_dir, day)


print("[group robot takes the alarm: channel 企业微信机器人]")
n = build("ok")
check("delivered", n.send("⚠️ 出错了", "正文", alert=True), [])
got = rows(n)
check("one row", len(got), 1)
check("channel", got and got[0].get("channel"), "企业微信机器人")
check("the Mac gets the same row", n._mac.rows, got)

print("\n[group robot refuses, Server酱 takes it: channel Server酱]")
n = build("fallback", broken=("企业微信机器人",))
n._announcing = True          # no outage notice in this case
check("delivered", n.send("⚠️ 出错了", "正文", alert=True), [])
got = rows(n)
check("channel is the fallback", [r.get("channel") for r in got], ["Server酱"])

print("\n[with the outage notice: each row names its own channel]")
n = build("outage", broken=("企业微信机器人",))
n.send("⚠️ 出错了", "正文", alert=True)
got = rows(n)
check("alarm and notice copied", [r["title"].startswith(("⚠️ 出错了", "🔌")) for r in got], [True, True])
check("both went by Server酱", [r.get("channel") for r in got], ["Server酱", "Server酱"])

print("\n[send_group: 企业微信机器人]")
n = build("group")
n.send_group("📣 明天开卡池", "正文")
check("channel", [r.get("channel") for r in rows(n)], ["企业微信机器人"])

print("\n[unknown channel: empty]")
check("row() default", alertlog.row("t", "x").get("channel"), "")
check("FIELDS ends with channel", alertlog.FIELDS[-1], "channel")

print("\n[a day file with a pre-channel machine row still reads and merges]")
old = FIX.read_bytes()
check("fixture row has no channel field", "channel" in json.loads(old), False)


class Cos:
    def __init__(self):
        self.objects = {}

    def put(self, key, data):
        self.objects[key] = data

    def get(self, key):
        return self.objects.get(key), ""


cos = Cos()
day = alertlog.beijing().strftime("%Y%m%d")
cos.objects[alertlog.key_for(day)] = old
n = build("merge", broken=("企业微信机器人",))
n._announcing = True
n._alerts = alertlog.AlertLog(TMP / "merge", put=cos.put, get=cos.get)
n.send("⚠️ 新的", "正文", alert=True)
for th in threading.enumerate():
    if th.name == "alarm-copy":
        th.join(5)
merged = [json.loads(x) for x in cos.objects[alertlog.key_for(day)].decode("utf-8").splitlines()]
check("old row kept first, new row after", [r["title"] for r in merged], ["🖼️ 无音区产出", "⚠️ 新的"])
check("old row reads as unknown channel", merged[0].get("channel", ""), "")
check("new row has it", merged[1]["channel"], "Server酱")
check("machinecheck reads both", len(mc.alert_rows(TMP / "merge", day)), 2)

for th in threading.enumerate():
    if th.name in ("alarm-copy", "alarm-mac"):
        th.join(5)
print(f"\n{'FAIL: ' + ', '.join(fails) if fails else 'all passed'}")
sys.exit(1 if fails else 0)
