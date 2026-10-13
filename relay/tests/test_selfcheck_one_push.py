"""A failing boot self-check reaches the group once, through the real errwatch handler.

alerts/20261010.jsonl 16:14:08-16:14:14 (and again at 16:33, 16:59, 17:02): each
「🩺 开机自检没过」 was followed by one 「🩺 中继自己报错了」 per failing ✗ line,
because errwatch pushed the ✗ WARNINGs the self-check had already put in its own
alarm. 38246899 (10-10 17:44) marks those lines `errwatch.group_pushed`; no
self-check line has failed on the machine since, so this is where the fix is run:
selfcheck.report with one forced failing check, under a real
errwatch.ErrorKindAlert on the "ark" logger (a push = a record reaching its
_take), counts the pushes. When the self-check's own send fails, the ✗ line is
not marked and errwatch carries it instead (still one push).
"""
import logging
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ark_relay.core import texts  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402
from ark_relay.features.selfcheck import selfcheck  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class _Notifier:
    channels = ["企业微信机器人"]

    def __init__(self, errs=()):
        self.sent, self._errs = [], list(errs)

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append(title)
        return self._errs


CHECKS = [selfcheck.Check("看得到机器上在跑哪些程序", True),
          selfcheck.Check("调度程序的后台程序在跑", False, "没找到 AUTO-MAS 的后台进程"),
          selfcheck.Check("状态目录能写", True)]
selfcheck.run = lambda cfg, **kw: list(CHECKS)


def pushes(notifier):
    """(what the self-check sent itself, what errwatch took) for one report()."""
    with tempfile.TemporaryDirectory() as td:
        h = errwatch.ErrorKindAlert(_Notifier(), state_dir=Path(td) / "state", known={})
        taken = []
        h._take = taken.append
        ark = logging.getLogger("ark")
        ark.addHandler(h)
        try:
            selfcheck.report(None, notifier)
        finally:
            ark.removeHandler(h)
    return notifier.sent, [r.getMessage() for r in taken]


print("[one failing check, the alarm went out: one push in all]")
sent, taken = pushes(_Notifier())
check("the self-check sent its alarm once", sent, [texts.SELFCHECK_FAILED])
check("errwatch takes nothing more (the ✗ line is marked as delivered)", taken, [])

print("[the self-check's own send failed: errwatch carries the ✗ line instead]")
sent, taken = pushes(_Notifier(errs=["企业微信机器人：超时"]))
check("the send was tried once", sent, [texts.SELFCHECK_FAILED])
check("errwatch takes the one ✗ line", [m.split("：")[0] for m in taken], ["开机自检 ✗ 调度程序的后台程序在跑"])

print("[all checks pass: nothing at all]")
CHECKS[1] = selfcheck.Check("调度程序的后台程序在跑", True)
check("no push", pushes(_Notifier()), ([], []))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
