"""A broken channel must be reported once, not once per relay restart.

On 2026-08-22 the same 企业微信 60020 notice reached the operator's phone
repeatedly through a day of deployments: the "already announced" record lived
in memory, and every self-update restarts the process. The message also carries
a fresh request hint and the current egress IP each time, so it never repeats
byte for byte.
"""
import json, os, sys, tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
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

print("[the hint and the IP change every time - same fault]")
check("same fingerprint",
      Notifier._fingerprint(ERR1) == Notifier._fingerprint(ERR2), True)
check("a different error code is a different fault",
      Notifier._fingerprint(ERR1) == Notifier._fingerprint(ERR3), False)
check("no hint left", "hint" in Notifier._fingerprint(ERR1), False)
check("no ip left", "112.43" in Notifier._fingerprint(ERR1), False)

print("\n[announced once, and the record survives a restart]")
sent = []
class Cap(Notifier):
    def _fan_out(self, title, body):
        sent.append(title)
        return ["Server酱"], {}          # delivered by one channel

n = Cap(cfg)
n._announce_outage({"企业微信": ERR1}, ["Server酱"])
check("first fault announced", len(sent), 1)
n._announce_outage({"企业微信": ERR1}, ["Server酱"])
check("same fault stays quiet", len(sent), 1)

# A restart: brand new object, same state directory.
n2 = Cap(cfg)
n2._announce_outage({"企业微信": ERR2}, ["Server酱"])
check("restart does not re-announce", len(sent), 1)
check("record is on disk", (TMP / "channels-down.json").exists(), True)

print("\n[a different fault on the same channel is news again]")
n2._announce_outage({"企业微信": ERR3}, ["Server酱"])
check("announced", len(sent), 2)

print("\n[recovery clears it, so the next failure is news]")
# What send() does when the channel starts working again: drop its record.
n3 = Cap(cfg)
n3._announced_down.pop("企业微信", None)
n3._save_down()
n4 = Cap(cfg)
n4._announce_outage({"企业微信": ERR1}, ["Server酱"])
check("announced after recovery", len(sent), 3)

print("\n[a channel that never broke is not in the file]")
check("only the broken one recorded",
      list(json.loads((TMP / "channels-down.json").read_text(encoding="utf-8")).keys()),
      ["企业微信"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
