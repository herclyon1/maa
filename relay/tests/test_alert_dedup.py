"""The alerted-today marks (state.json marks.alerted:<day>), and what still uses them.

2026-09-01 the group got the same OK-WW failure three times (17:00/08:29/11:54), and
the user said 「赶紧去修，报了三次了。」 From then until 2026-10-06 the key script +
failed step kept a second final alarm for the same step off the group that day. The
user's order of 2026-10-06, 「不论多少次什么错误都要发」, replaced that: every final
failure is pushed, the same step again included (checked at the end). The marks
stay for what is one event checked again and again (a queue overrun, a timeout
line, the same record handled twice) and for the self-heal notice.
"""
import sys, types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.engine import Engine
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok: fails.append(label)

E = object.__new__(Engine)


def _fake_state(d):
    """替身 state：带上真的 StateStore，记账走 state.json（2026-09-08 收口后）。"""
    from ark_relay.statestore import StateStore  # noqa: PLC0415
    return types.SimpleNamespace(dir=d, store=StateStore(d))

E.state = _fake_state(tmpdir())
rec = types.SimpleNamespace(script="OK-WW", user="wuwa", failed_tasks=["流程产生错误"])

k = E._alert_key(rec)
check("第一次：没报过", E._already_alerted("2026-09-01", k), False)
E._mark_alerted("2026-09-01", k)
check("第二次：同键当天挡住", E._already_alerted("2026-09-01", k), True)
rec2 = types.SimpleNamespace(script="OK-WW", user="wuwa", failed_tasks=["在完成任务前退出"])
check("换一步失败：是新事，放行", E._already_alerted("2026-09-01", E._alert_key(rec2)), False)
check("跨天重置", E._already_alerted("2026-09-02", k), False)
E._mark_alerted("2026-09-01", E._alert_key(rec2))
check("两键共存互不干扰", E._already_alerted("2026-09-01", k), True)
rec3 = types.SimpleNamespace(script="OK-WW", user="wuwa", failed_tasks=None)
check("failed_tasks 为空不炸", isinstance(E._alert_key(rec3), str), True)

print("\n[OK-WW fails twice on the same step the same day: two alarms]")
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from ark_relay import engine as eng_mod, handle  # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.ledger import State  # noqa: E402


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, kw.get("alert", False)))
        return []


class Src:
    def fetch(self, seen):
        return []


os.environ.setdefault("ARK_LLM_KEY", "")
cfg = Config()
cfg.state_dir, cfg.automas_dir, cfg.okww_dir = tmpdir(), None, None
eng = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
eng._scripts_running = lambda: False
eng._script_running = lambda name: False
eng._verify_outcome = lambda r: None
handle._ship_evidence = lambda e, r: ""
handle._archive_okww_evidence = lambda e, r: None
now = datetime.now(tz=SERVER_TZ).replace(hour=9, minute=0, second=0, microsecond=0)
for i, run in enumerate(("09-00-00", "21-30-00")):
    t = now + timedelta(hours=12 * i, minutes=30 * i)
    eng._handle(RunRecord(run_id=f"{t:%Y-%m-%d}/wuwa/OK-WW-{run}", script="OK-WW", user="wuwa", started=t,
                          finished=t + timedelta(minutes=20), ok=False, failed_tasks=["流程产生错误"], raw={}))
    eng._flush_pending()
check("two final alarms, same step", [x for x in eng.notifier.sent if x[1]], [("❌ OK-WW 失败", True)] * 2)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
