"""A channel that refuses a send is announced every time it refuses one.

From 2026-08-22 until 2026-10-06 the same fault was announced once (a record on
disk, keyed by the error with 企业微信's hint and egress IP stripped, so that a
day of relay restarts did not repeat it). The user's order of 2026-10-06, every
error to the group, every time (「不论多少次什么错误都要发」), ended that.
Pinned: each refused send is announced over the channels still
working; the per-channel log line comes with it, marked as already in the group
only when the group robot took the notice (errwatch does not push it twice).
"""
import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP),
                  SERVERCHAN_KEY="", WECOM_CORPID="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.config import Config      # noqa: E402
from ark_relay.notify import Notifier    # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

ERR1 = ("企业微信发送失败: 60020 not allow to access from your ip, "
        "hint: [1787373915609110759172198], from ip: 112.43.40.209")
ERR2 = ("企业微信发送失败: 60020 not allow to access from your ip, "
        "hint: [9999999999999999999999999], from ip: 112.43.40.77")
ERR3 = "企业微信发送失败: 40014 invalid access_token"

cfg = Config()

import logging  # noqa: E402
from ark_relay import errwatch  # noqa: E402

lines = []
class _Lines(logging.Handler):
    def emit(self, record):
        lines.append((record.getMessage(), getattr(record, errwatch.PUSHED, False)))
logging.getLogger("ark.notify").addHandler(_Lines())

print("[every refused send is announced - the same fault again included]")
sent = []
class Cap(Notifier):
    # Keyword names must match the real signature, or a routing change goes astray here silently.
    def _fan_out(self, title, body, *, order=None, stop_on_first=False):
        sent.append(title)
        return list(self.took), {}

n = Cap(cfg)
n.took = ["Server酱"]
n._announce_outage({"企业微信": ERR1}, ["Server酱"])
check("first refusal announced", len(sent), 1)
n._announce_outage({"企业微信": ERR2}, ["Server酱"])
check("the same fault again: announced again", len(sent), 2)
n2 = Cap(cfg)
n2.took = ["Server酱"]
n2._announce_outage({"企业微信": ERR1}, ["Server酱"])
check("after a restart too", len(sent), 3)
check("nothing kept on disk to stay quiet with",
      "channels_down" in json.loads((TMP / "state.json").read_text(encoding="utf-8")).get("queues", {})
      if (TMP / "state.json").exists() else False, False)
check("the title names the channel", sent[-1], "🔌 推送通道故障：企业微信")

print("\n[the log line for each refusal]")
lines.clear()
n._announce_outage({"企业微信机器人": "boom"}, ["Server酱"])
check("one line per refusal", [m for m, _ in lines], ["企业微信机器人推送失败: boom"])
check("the notice went by Server酱 only: errwatch still pushes the line", lines[0][1], False)
lines.clear()
n.took = ["企业微信机器人"]
n._announce_outage({"Server酱": "boom"}, ["企业微信机器人"])
check("the group robot took the notice: the line is marked as already in the group", lines[0][1], True)

print("\n[60020 的提示要把机器的地址写出来，他照着加就行（2026-09-12）]")
from ark_relay.notify import _hint  # noqa: E402
check("提示里有地址", "112.43.40.209" in _hint("企业微信", ERR1), True)
check("说清去哪加", "企业可信IP" in _hint("企业微信", ERR1), True)
check("别的错误没有提示", _hint("企业微信", ERR3), "")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
