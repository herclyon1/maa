"""Config warnings and a bad-config exit at boot reach the group (audit s23 F1, 10-13).

Until 10-13 boot_stages._stage_bootstrap ran cfg.validate() - which logs
「配置提醒: …」 (config.py) and whose problems were logged as 「配置有问题」 before the
early return - before errwatch.install. Nothing buffers records logged before the
handler exists, so both reached relay.log only: a relay that would not start said
why to nobody, and the 「没有配置群机器人」 warning added 10-13 (0cd624e2) was never
pushed. Now errwatch is installed first, and the bad-config exit waits for its push.

Runs the real _stage_bootstrap with the real Config (from environment variables) and
a recording notifier in place of the real channels.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _tmp import tmpdir
import boot_stages
from ark_relay.core import notify
from ark_relay.features.alarm import errwatch
from ark_relay.features.evidence import error_evidence

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Recorder:
    """Stands in for notify.Notifier: takes every push, sends nothing."""

    made: list["Recorder"] = []

    def __init__(self, cfg):
        self._state_dir = Path(cfg.state_dir)
        self.sent: list[tuple[str, str]] = []
        Recorder.made.append(self)

    def send_group(self, title, body):
        self.sent.append((title, body))
        return []

    def send(self, title, body, **_k):
        self.sent.append((title, body))
        return []

    def went_to_group(self):
        return True


def boot(env: dict) -> tuple[object, list, list]:
    """_stage_bootstrap under `env`; returns what it returned, the pushes made by the
    time it returned, and every push made once errwatch has drained."""
    keys = ("ARK_HISTORY_DIR", "ARK_STATE_DIR", "ARK_LOG_FILE", "SERVERCHAN_KEY",
            "WECOM_BOT_URL", "WECOM_CORPID", "WECOM_SECRET", "WECOM_AGENTID", "ARK_AUTOMAS_DIR")
    saved_env = {k: os.environ.get(k) for k in keys}
    real_notifier, real_upload = notify.Notifier, error_evidence.upload_daily_logs
    ark = logging.getLogger(errwatch.ARK)
    before = list(ark.handlers)
    # errwatch globals _stage_bootstrap sets: put back, so a later test in the same
    # process (the deploy gate runs them in one) does not push through this one's cfg.
    saved_errwatch = (errwatch._handler[0], errwatch._relay_poweroff[0], errwatch._evidence_uploader[0])
    Recorder.made.clear()
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update(env)
    notify.Notifier = Recorder
    error_evidence.upload_daily_logs = lambda cfg: {}
    try:
        out = boot_stages._stage_bootstrap()
        at_return = [x for r in Recorder.made for x in r.sent]
        errwatch.drain(5.0)
    finally:
        for h in [h for h in ark.handlers if h not in before]:
            ark.removeHandler(h)
            h.close()
        errwatch._handler[0], errwatch._relay_poweroff[0], errwatch._evidence_uploader[0] = saved_errwatch
        notify.Notifier, error_evidence.upload_daily_logs = real_notifier, real_upload
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    sent = [x for r in Recorder.made for x in r.sent]
    return out, at_return, sent


def said(sent, words: str) -> bool:
    return any(words in title + body for title, body in sent)


print("[bad config (no history folder) plus a config warning (no group robot)]")
state = tmpdir()
out, at_return, sent = boot({"ARK_STATE_DIR": str(state), "ARK_LOG_FILE": str(state / "relay.log"),
                             "ARK_HISTORY_DIR": str(state / "no-such-folder"), "SERVERCHAN_KEY": "test-key"})
check("the relay does not start", out, None)
# The push quotes the record's first line, which is plain words; the setting names
# stay in relay.log (texts.plain would not quote them).
check("the exit reached the group before it", said(at_return, "中继没有启动"), True)
check("the warning reached the group too", said(sent, "读设置"), True)
check("one push each, not one per problem", len(sent), 2)

print("[good config with the same warning: the relay starts and the warning is pushed]")
state = tmpdir()
history = state / "history"
history.mkdir()
out, _, sent = boot({"ARK_STATE_DIR": str(state), "ARK_LOG_FILE": str(state / "relay.log"),
                     "ARK_HISTORY_DIR": str(history), "SERVERCHAN_KEY": "test-key"})
check("the relay starts", out is not None, True)
check("the 配置提醒 warning reached the group (from 「读设置」, ark.config)", said(sent, "读设置"), True)
check("nothing about not starting", said(sent, "没有启动"), False)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
