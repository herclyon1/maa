"""`python -m ark_relay test` must try every channel and name only the ones that took it.

Audit s5 #3 (2026-10-13): cmd_test called send(alert=True), which stops at the first
channel that accepts, yet printed 「✅ 已通过 <every configured channel> 发出」; and it
filed the test as a real group alarm (alerts/ copy). Channels are faked here.
"""
import contextlib
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

os.environ.update(ARK_STATE_DIR=str(tmpdir()), ARK_HISTORY_DIR=str(tmpdir()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import __main__ as relay_main
from ark_relay.core import notify
from ark_relay.core.config import Config

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


class Chan:
    def __init__(self, ok):
        self.enabled, self.ok, self.got = True, ok, []

    def send_text(self, *a):
        if not self.ok:
            raise RuntimeError("refused")
        self.got.append(a)


bot, sc = Chan(True), Chan(False)
copied: list = []
real_init = notify.Notifier.__init__


def fake_init(self, cfg):
    real_init(self, cfg)
    self.wecom_bot, self.serverchan = bot, sc
    self.wecom = Chan(True)
    self.wecom.enabled = False


notify.Notifier.__init__ = fake_init
notify.Notifier._copy_alarm = lambda self, t, b: copied.append(t)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = relay_main.cmd_test(Config())
text = out.getvalue()
print(text)

print("[the robot takes it, Server酱 refuses]")
check("Server酱 was tried too", (len(bot.got), "Server酱: refused" in text), (1, True))
check("success names only the robot", "✅ 已通过 企业微信机器人 发出" in text, True)
check("Server酱 is not named as delivered", "企业微信机器人、Server酱" in text, False)
check("a refused channel fails the self-test", rc, 1)
check("not filed as a group alarm", copied, [])

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")
sys.exit(1 if fails else 0)
