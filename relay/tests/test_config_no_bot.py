"""A config with Server酱 but no group robot must start, with a warning.

Audit s6 #2 (2026-10-13): Config.validate reported a missing WECOM_BOT_URL as a
problem (「没有它一条都送不到」), and a problem stops the relay at boot
(boot_stages / cmd_local). Group alarms fall back to Server酱
(notify._GROUP_ORDER), so that setup works; it is a warning now.
"""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

HIST = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(HIST), WECOM_BOT_URL="", SERVERCHAN_KEY="SCT-test",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_AGENTID="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core.config import Config  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


said: list = []
h = logging.Handler()
h.emit = lambda r: said.append((r.levelname, r.getMessage()))
logging.getLogger("ark").addHandler(h)

print("[Server酱 only: starts, warns that alarms go to Server酱]")
cfg = Config()
check("no blocking problem", cfg.validate(), [])
check("one WARNING line naming the fallback",
      [lvl for lvl, m in said if "WECOM_BOT_URL" in m and "Server酱" in m], ["WARNING"])

print("\n[WeCom app only: group alarms have no channel at all -> still a problem]")
os.environ.update(SERVERCHAN_KEY="", WECOM_CORPID="c", WECOM_SECRET="s", WECOM_AGENTID="1")
check("blocked", len(Config().validate()), 1)

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")
sys.exit(1 if fails else 0)
