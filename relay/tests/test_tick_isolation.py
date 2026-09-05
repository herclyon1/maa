"""tick 里一段出错，后面的段（尤其日报和关机）照样要跑。

2026-09-04：明日安排那段一个 ImportError，把它后面的补更新、日报、自动关机
全带走，整整一上午没人发现。每一段各自兜住，一段坏了不许连累下一段。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
AUTOMAS = TMP / "AUTO-MAS"; (AUTOMAS / "config").mkdir(parents=True)
STATE = TMP / "state"; STATE.mkdir()
HIST = TMP / "history"; HIST.mkdir()
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(STATE), SERVERCHAN_KEY="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import engine as eng               # noqa: E402
from ark_relay.config import Config               # noqa: E402
from ark_relay.core import State                  # noqa: E402
from ark_relay.notify import Notifier             # noqa: E402

fails = []
cfg = Config()
E = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notifier(cfg))
E._scripts_running = lambda: False

class Src:
    def fetch(self, seen):
        return []
E.source = Src()

ran = []
def boom(*a, **k):
    raise RuntimeError("这一段坏了")
E._check_missed_runs = boom                      # 漏跑检查炸了
E._maybe_interim_report = lambda *a, **k: ran.append("interim")
E._maybe_daily_report = lambda *a, **k: ran.append("daily")
E._maybe_shutdown = lambda *a, **k: ran.append("shutdown")

try:
    E.tick()
except Exception as exc:  # noqa: BLE001
    fails.append(f"tick 把一段的异常抛出来了：{exc}")
for want in ("interim", "daily", "shutdown"):
    if want not in ran:
        fails.append(f"前面一段出错后「{want}」没跑")

# 读记录本身炸了也一样：时钟类的段照做
ran.clear()
class BadSrc:
    def fetch(self, seen):
        raise OSError("history 目录读不了")
E.source = BadSrc()
E._check_missed_runs = lambda *a, **k: ran.append("missed")
try:
    E.tick()
except Exception as exc:  # noqa: BLE001
    fails.append(f"读记录失败被抛出来了：{exc}")
if "shutdown" not in ran or "missed" not in ran:
    fails.append(f"读记录失败后其余段没跑：{ran}")

# 从源码上钉死：五个时钟段必须在同一个逐段兜底的循环里
src = (Path(__file__).resolve().parents[1] / "ark_relay" / "engine.py").read_text(encoding="utf-8")
body = src[src.index("    def tick(self)"):]
body = body[:body.index("\n    def ", 10)]
for name in ("_check_missed_runs", "_maybe_interim_report", "_maybe_deferred_update",
             "_maybe_daily_report", "_maybe_shutdown", "_flush_pending"):
    if f"self.{name})" not in body and f"self.{name}," not in body:
        fails.append(f"tick 里 {name} 没有走逐段兜底的循环")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
