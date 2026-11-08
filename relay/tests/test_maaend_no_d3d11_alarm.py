"""A game started without Direct3D 11 is normal now: no group alarm after a MaaEnd record or at boot.

Until 10-17 the official launcher's 「DirectX 11 启动」 box was ticked so MaaEnd could read the
fullscreen game, and the launcher remembers it, so the owner's own play started in DX11 too. Since
10-17 the game runs windowed below the desktop for script runs (AUTO-MAS v5.7.0-beta.5
「MaaEnd 启动」, set by efstart_setup; the relay's own retry starts it the same way), which MaaEnd
reads on any graphics API, and the box is to be unticked (DECISIONS D-1016-终末地等AUTO-MAS新版).

Until then the relay read line 6 of the game's Player.log after every MaaEnd record
(handle._book) and at boot (boot_stages._stage_endfield_start), and logged a WARNING when it was
not 「Forcing GfxDevice: Direct3D 11」. errwatch pushes every WARNING to the group, so with the box
unticked that would have been a false alarm every day. Pinned here with a Player.log whose line 6
names another device (the Vulkan line has never been seen on the machine; any line that is not
Direct3D 11 made the old check warn):

* a MaaEnd record booked through handle._handle: no WARNING, nothing to the group;
* the boot stage: no WARNING either.
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
MAAEND = TMP / "maaend"
(MAAEND / "debug").mkdir(parents=True)
(TMP / "history").mkdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_MAAEND_DIR=str(MAAEND),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))

import boot_stages                                                    # noqa: E402
from ark_relay.features.makeup import collect_retry                   # noqa: E402
from ark_relay.features.alarm import handle                           # noqa: E402
from ark_relay.features.gameupdate import efstart_setup               # noqa: E402
from ark_relay.core import engine as eng_mod                          # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config, RunRecord        # noqa: E402
from ark_relay.core.ledger import State                               # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Warned(logging.Handler):
    """What errwatch.ErrorKindAlert would take: every WARNING or worse (it sits on the relay's top logger)."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(f"{record.name}: {record.getMessage()}")


WARNED = Warned()
logging.getLogger().addHandler(WARNED)

# The game's own log, line 6 not Direct3D 11 (the first five lines as on the machine 10-16).
player = TMP / "Administrator" / "Player.log"
player.parent.mkdir()
player.write_text("\n".join([
    "Mono path[0] = 'D:/endfield/Hypergryph Launcher/games/Endfield Game/Endfield_Data/Managed'",
    "Mono config path = 'D:/endfield/Hypergryph Launcher/games/Endfield Game/MonoBleedingEdge/etc'",
    "[Physics::Module] Initialized MultithreadedJobDispatcher with 15 workers.",
    "Initialize engine version: 2021.3.34f1",
    "[Subsystems] Discovering subsystems at path D:/endfield/x/UnitySubsystems",
    "Forcing GfxDevice: Direct3D 12",
    "Direct3D:",
]) + "\n", encoding="utf-8")
# Before this change the relay found Player.log through this function; patched so that code
# would read the file above. Code without the function never reads it.
efstart_setup._player_logs = lambda: [str(player)]


def automas_dir() -> Path:
    root = tmpdir()
    (root / "config").mkdir()
    paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
    sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
    for k, p in paths.items():
        sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
    qc = {"instances": [{"uid": "q0"}],
          "q0": {"Info": {"Name": "早班", "TimeEnabled": True},
                 "SubConfigsInfo": {"TimeSet": {"instances": [], "t0": {"Info": {"Enabled": True, "Time": "09:00"}}},
                                    "QueueItem": {"instances": [],
                                                  **{f"i{i}": {"Info": {"ScriptId": f"s-{k}"}}
                                                     for i, k in enumerate(paths)}}}}}
    (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
    (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
    return root


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return False


class Src:
    def fetch(self, seen):
        return []


handle._ship_evidence = lambda eng, rec: ""
handle._weekly_gates = lambda eng, rec: None
collect_retry.restore_master = lambda cfg: ""


def build():
    cfg = Config()
    cfg.state_dir = tmpdir() / "state"
    cfg.automas_dir = automas_dir()
    cfg.maaend_dir = MAAEND
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._verify_outcome = lambda r: None
    e._archive_maaend_evidence = lambda r: None
    e._alert_key = lambda r: handle._alert_key(e, r)
    return e


print("[the capture sees a WARNING from the relay's loggers at all]")
efstart_setup.log.warning("probe")
check("a WARNING from efstart_setup's logger is caught", WARNED.lines, ["ark.efstart_setup: probe"])
WARNED.lines.clear()

print("\n[a MaaEnd record lands, Player.log line 6 is not Direct3D 11]")
start = datetime(2026, 10, 16, 13, 26, 0, tzinfo=SERVER_TZ)
rec = RunRecord(run_id="2026-10-16/endfield/MaaEnd-09-26-00", script="MaaEnd", user="endfield",
                started=start, finished=start + timedelta(minutes=30), ok=True, failed_tasks=[],
                raw={"maaend_result": "Success!"})
e = build()
handle._handle(e, rec)
e._flush_pending()
check("no WARNING (errwatch would push each one to the group)", WARNED.lines, [])
check("nothing to the group", [s for s in e.notifier.sent if s[2]], [])

print("\n[boot: the Endfield start stage with the same Player.log]")
WARNED.lines.clear()
# A later start of the game (the log written again), so the boot reads it afresh.
_t = player.stat().st_mtime + 60
os.utime(player, (_t, _t))
boot_stages._endfield_launch = lambda cfg, log, when: None
boot_stages._stage_endfield_start(Config(), Notes(), efstart_setup.log)
check("no WARNING at boot", WARNED.lines, [])

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
