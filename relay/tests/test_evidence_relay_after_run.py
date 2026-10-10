"""A failure bundle carries what the relay did about the run, and its link reaches the ledger.

Replayed from the 2026-09-24 morning (bucket ark-evidence, 2026-09-24_arknights_MAA-05-00-02):
MAA failed 09:03:08, the record's window is 08:58:06-09:08:08, and the relay
handled it at 09:20 (bundle upload 01:20 UTC) - AUTO-MAS writes the record at the
end of the whole script. The relay.log slice held two lines, both 09:02:01, and
two MaaEnd bundles that day held no relay.log at all; the relay's own handling
was never in any of them. And the link was set on rec.raw after the run was on
the ledger and never written back, so the daily report's 证据包 row was always empty.
"""
import json
import os
import sys
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import ledger, evidence, handle, texts
from ark_relay.config import SERVER_TZ, RunRecord

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def at(h, m, s):
    """09-24 h:m:s on the machine's clock (Beijing), the moment the real bundle names."""
    return datetime(2026, 9, 24, h, m, s, tzinfo=SERVER_TZ)


def at_(h, m, s):
    """That moment as relay.log stamps it: in the local time of the computer running
    the test (logging's asctime; evidence._line_ts reads it back as local). On the
    machine that is Beijing and this is the real bundle's 「09-24 h:m:s」; on the
    Windows CI runner (UTC, run 37519943859) literal Beijing stamps read back eight
    hours late, and 09:03 started a 晚班 round."""
    return at(h, m, s).astimezone().strftime("%m-%d %H:%M:%S")


T = tmpdir()
relay_log = T / "relay.log"
relay_log.write_text(
    # the two lines the real bundle held, both 09-24 09:02:01
    f"{at_(9, 2, 1)} INFO    ark.shutdown  不关机：本次开机还没有跑完任何队列\n"
    f"{at_(9, 2, 1)} INFO    ark.service  下一个闹钟 09:25 核对队列「早班」09:00 是否漏跑\n"
    # what the relay did once the record landed (09:20:03, 09:20:04)
    f"{at_(9, 20, 3)} INFO    ark.handle  ⏳ MAA 失败，暂不推送，等重试结果\n"
    f"{at_(9, 20, 4)} INFO    ark.notify  不推送（日报或手机页已有）：⚠️ MAA 中途失败过，重试后成功\n"
    # after the cut (09:40:00)
    f"{at_(9, 40, 0)} INFO    ark.service  下一个闹钟 12:00\n", encoding="utf-8")
os.environ["ARK_LOG_FILE"] = str(relay_log)
started = at(9, 3, 6).astimezone()     # the machine stamps its own local time
finished = at(9, 3, 8).astimezone()
handled = at(9, 20, 5).timestamp()
win = evidence.run_window(started, finished)

print("[复现：只按那趟自己的时间窗切，中继日志只剩 09:02:01 两行]")
out = evidence.context_files(types.SimpleNamespace(automas_dir=None), win, T / "old")
rl = (T / "old" / "relay.log").read_text(encoding="utf-8")
check("两行，都是 09:02:01", [ln[:14] for ln in rl.splitlines()], [at_(9, 2, 1), at_(9, 2, 1)])
check("中继自己怎么处理的一行都没有", at_(9, 20, 3) in rl, False)

print("\n[切到处理那一刻：处理行在，之后的不在]")
evidence.context_files(types.SimpleNamespace(automas_dir=None), win, T / "new", relay_until=handled)
rl = (T / "new" / "relay.log").read_text(encoding="utf-8")
check("09:02:01 两行还在", rl.count(at_(9, 2, 1)), 2)
check("处理那几行在", at_(9, 20, 3) in rl and at_(9, 20, 4) in rl)
check("切之后的不在", at_(9, 40, 0) in rl, False)

print("\n[手工导出不传截止时刻：照旧只切那趟的窗]")
evidence.context_files(types.SimpleNamespace(automas_dir=None), win, T / "cli")
check("手工导出不多带", at_(9, 20, 3) in (T / "cli" / "relay.log").read_text(encoding="utf-8"), False)


class Up:
    def upload(self, p):
        return {"name": p.name, "size": p.stat().st_size, "store": "cos", "page": "https://cos.example/MAA.zip"}


class Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, body, alert=False):
        self.sent.append((title, body, alert))
        return []


evidence.uploaders = lambda cfg, run_id="": [Up()]
handle.time = types.SimpleNamespace(time=lambda: handled)


def engine(d: Path):
    cfg = types.SimpleNamespace(state_dir=d, history_dir=None, automas_dir=None,
                                maa_dir=None, maaend_dir=None, okww_dir=None)
    eng = types.SimpleNamespace(cfg=cfg, state=ledger.State(d), notifier=Notifier(), _pending={}, _recovered={})
    eng.persisted = []
    eng._persist_pending = lambda: eng.persisted.append(dict(eng._pending))
    return eng


def record(run_id):
    return RunRecord(run_id=run_id, script="MAA", user="u", started=started, finished=finished,
                     ok=False, failed_tasks=["StartUp"], raw={"maa_result": "MAA 未能正确登录 PRTS"})


day = started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")

print("\n[首败：证据包里有处理行，链接写回账本，日报那一行带链接]")
eng = engine(tmpdir())
rec = record(f"{day}/arknights/MAA-05-00-02")
eng.state.append_ledger(rec)
handle._hold_for_retry(eng, rec, ("MAA", "u"))
entry = eng.state.read_ledger(day)[0]
check("账本里有链接", (entry.get("raw") or {}).get("evidence_page"), "https://cos.example/MAA.zip")
check("待推记录带着链接又存了一次", (eng.persisted[-1][("MAA", "u")].raw or {}).get("evidence_page"), "https://cos.example/MAA.zip")
daily = ledger.format_daily(day, eng.state.read_ledger(day))
daily = daily if isinstance(daily, str) else json.dumps(daily, ensure_ascii=False)
check("日报「证据包」一行有链接", "https://cos.example/MAA.zip" in daily)
bundle = next((eng.cfg.state_dir / "evidence").glob("*/bundle/relay.log"))
check("证据包里的中继日志带着处理行", at_(9, 20, 3) in bundle.read_text(encoding="utf-8"))
check("首败没有任何报警推送", [t for t, _, a in eng.notifier.sent if a], [])

print("\n[重试后成功：自己好了，不推，只进日报（用户 2026-10-06 05:07），日志这么说]")
import logging  # noqa: E402
seen = []
h = logging.Handler(); h.emit = lambda r: seen.append(r.getMessage())
handle.log.addHandler(h); handle.log.setLevel(logging.INFO)
eng._recovered[("MAA", "u")] = eng._pending.pop(("MAA", "u"))
eng._scripts_running = lambda: False
eng._script_running = lambda name: False
eng._alert_key = lambda r: "StartUp"
eng._already_alerted = lambda d, k: handle._already_alerted(eng, d, k)
eng._mark_alerted = lambda d, k: handle._mark_alerted(eng, d, k)
before = len(eng.notifier.sent)
handle._flush_pending(eng)
check("自愈那条没发（群、Server酱都没有）", [t for t, _, _ in eng.notifier.sent[before:]], [])
check("日志写的是只进日报", any(m.startswith(texts.self_healed("MAA")) and "只进日报" in m for m in seen))
check("放下了", eng._recovered, {})

print("\n[这一轮没干完（鸣潮）：报警本身带证据链接]")
eng = engine(tmpdir())
rec = record(f"{day}/wuwa/OK-WW-17-30-02")
rec.script, rec.ok = "OK-WW", True
eng.state.append_ledger(rec)
eng._verify_outcome = lambda r: "OK-WW 这一轮有 1 项没干成"
handle._weekly_gates = lambda eng, rec: None
handle._handle_success(eng, rec, ("OK-WW", "u"))
alarm = [b for t, b, a in eng.notifier.sent if t == texts.ROUND_INCOMPLETE]
check("报警发了一条", len(alarm), 1)
check("报警正文带证据链接", bool(alarm) and "证据包：https://cos.example/MAA.zip" in alarm[0])
check("账本里也有链接", (eng.state.read_ledger(day)[0].get("raw") or {}).get("evidence_page"), "https://cos.example/MAA.zip")

print("\n[这一轮没干完（MAA）：这一班进群一次，报警头一行带证据链接；账本带「没干完」和链接进日报]")
eng = engine(tmpdir())
eng._already_alerted = lambda d, k: handle._already_alerted(eng, d, k)
eng._mark_alerted = lambda d, k: handle._mark_alerted(eng, d, k)
eng._unsent_unresolved = []
eng.SOFT_FAILS = {"应急理智加强剂", "自动采集"}
rec = record(f"{day}/arknights/MAA-17-30-02")
rec.ok = True
eng.state.append_ledger(rec)
eng._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：没换上"
handle._handle_success(eng, rec, ("MAA", "u"))
check("没有推鸣潮那条「这一轮没干完」", [t for t, b, a in eng.notifier.sent if t == texts.ROUND_INCOMPLETE], [])
pushed = [(t, b) for t, b, a in eng.notifier.sent if a]
check("进群一条「明日方舟早班没干完」", [t for t, _ in pushed], [texts.unresolved_undone("明日方舟", "早班")])
check("头一行带项目和证据链接", bool(pushed) and pushed[0][1].splitlines()[0],
      "明日方舟早班跑完了但没干完：基建换班，这一类不补跑（证据包 https://cos.example/MAA.zip）")
entry = eng.state.read_ledger(day)[0]
check("账本记了没干完", entry.get("incomplete"), "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：没换上")
check("账本里也有链接", (entry.get("raw") or {}).get("evidence_page"), "https://cos.example/MAA.zip")

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("all checks passed")
