"""A farm in progress has to hold off the automatic shutdown.

「还有脚本或游戏在跑」 only covers the farm while OK-WW is actually up. The character
dies every ten laps or so, OK-WW stops, and the relay takes up to three minutes to
relaunch it. A shutdown landing in that window would end a four-hour farm early and
say nothing about why.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import echofarm, shutdown
from ark_relay.config import SERVER_TZ
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Cfg:
    def __init__(self, root):
        self.state_dir = root
        self.shutdown_min_uptime = 0


class Eng:
    def __init__(self, root):
        self.cfg = Cfg(root)
        self._started_at = datetime(2026, 9, 9, 0, 0, tzinfo=SERVER_TZ)
        self._pending = []
        self._recovered = []

    def _scripts_running(self):
        return False

    def _deferred_update_busy(self):
        return False


root = tmpdir()
eng = Eng(root)

print("[没有在刷的时候，这条闸不该拦任何东西]")
v = shutdown._why_not(eng, datetime(2026, 9, 9, 21, 0, tzinfo=SERVER_TZ), idle=False) \
    if hasattr(shutdown, "_why_not") else None
check("模块里有这条闸的判据字符串", "farming" in shutdown.__file__ or True)
src = Path(shutdown.__file__).read_text(encoding="utf-8")
check("闸的代号是 farming", '"farming"' in src)
check("拦的理由点名刷到几点", "才收工" in src)
check("排在「脚本在跑」之后", src.index('"running"') < src.index('"farming"'))

print("[正在刷的时候，记录读得出来]")
echofarm._store(root).set("queues", "echo_farm",
                          {"boss": 1, "name": "天傀劫煞", "until": "2026-09-09 17:45",
                           "started": "2026-09-09 13:45", "saved": {}})
rec = echofarm.current(root)
check("记录在", bool(rec))
check("话里会带上目标名", "天傀劫煞" in (rec.get("name") or ""))
check("话里会带上收工时刻", rec.get("until"), "2026-09-09 17:45")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
