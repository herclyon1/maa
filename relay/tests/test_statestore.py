"""state.json：一个文件、登记过的字段才能写、原子落盘、旧文件自动迁入。"""
import json, logging, sys
from pathlib import Path


class Warns(logging.Handler):
    """Collects the WARNING lines of one logger (each one is a group message)."""

    def __init__(self, name):
        super().__init__(logging.WARNING)
        self.lines = []
        logging.getLogger(name).addHandler(self)

    def emit(self, record):
        self.lines.append(record.getMessage())


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.statestore import StateStore

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402
d = tmpdir()
s = StateStore(d)
print("[空目录：读到空段，不落盘]")
check("weekly 空", s.section("weekly"), {})
check("还没有文件", (d / "state.json").exists(), False)

print("[登记过的能写，没登记的拒绝]")
s.set("weekly", "garden", {"done_week": "2026-W37"})
check("写进去", s.get("weekly", "garden"), {"done_week": "2026-W37"})
check("落盘了", json.loads((d / "state.json").read_text(encoding="utf-8"))["weekly"]["garden"], {"done_week": "2026-W37"})
try:
    s.set("weekly", "made_up", 1); check("未登记键被拒", False, True)
except KeyError as e:
    check("未登记键被拒", "没在字段表里登记" in str(e), True)
s.set("marks", "report:2026-09-07", "2026-09-07T22:00:00")
check("通配键", s.get("marks", "report:2026-09-07"), "2026-09-07T22:00:00")
s.pop("weekly", "garden")
check("pop", s.get("weekly", "garden"), None)

print("[另一个实例看到同一份（按 mtime 重读）]")
s2 = StateStore(d)
check("读到", s2.get("marks", "report:2026-09-07"), "2026-09-07T22:00:00")
s2.set("versions", "okww", "v3.6.7")
check("第一个实例也看到", s.get("versions", "okww"), "v3.6.7")

print("[旧文件迁入]")
d2 = tmpdir()
(d2 / "garden.json").write_text(json.dumps({"done_week": "2026-W36"}), encoding="utf-8")
(d2 / "weeklyboss.json").write_text(json.dumps({"index": 1, "name": "千傀重楼", "done_week": "2026-W37"}), encoding="utf-8")
(d2 / "okww-version.txt").write_text("v3.6.7", encoding="utf-8")
(d2 / "annihilation.json").write_text("{}", encoding="utf-8")   # 空的不迁
t = StateStore(d2)
check("garden 迁入", t.get("weekly", "garden"), {"done_week": "2026-W36"})
check("boss 迁入", t.get("weekly", "boss")["name"], "千傀重楼")
check("版本迁入", t.get("versions", "okww"), "v3.6.7")
check("空文件不迁", t.get("weekly", "annihilation"), None)
check("旧文件改名保留", (d2 / "garden.json.migrated").exists() and not (d2 / "garden.json").exists(), True)
check("再来一个实例不重复迁", StateStore(d2).get("weekly", "garden"), {"done_week": "2026-W36"})

print("[按天/按卡池的旧标记也迁：一次全搬]")
d3 = tmpdir()
(d3 / "report-2026-09-06.sent").write_text("", encoding="utf-8")
(d3 / "interim-2026-09-06.sent").write_text("7", encoding="utf-8")
(d3 / "interim-2026-09-05.sent").write_text("", encoding="utf-8")     # 旧空标记
(d3 / "banner-明日方舟-202609041200.sent").write_text("", encoding="utf-8")
(d3 / "skip-next-shutdown.flag").write_text("skip", encoding="utf-8")
(d3 / "shutdown-skipped.txt").write_text("2026-09-06:1", encoding="utf-8")
(d3 / "pending.json").write_text(json.dumps({"MaaEnd|endfield": {"run_id": "x"}}), encoding="utf-8")
u = StateStore(d3)
check("日报标记", u.get("marks", "report:2026-09-06"), True)
check("临时日报带条数", u.get("marks", "interim:2026-09-06"), "7")
check("旧空标记原样保留（条数不详）", u.get("marks", "interim:2026-09-05"), "")
check("卡池标记", u.get("marks", "banner:明日方舟-202609041200"), True)
check("别关机开关", u.get("modes", "skip_next_shutdown"), True)
check("被吃掉的关机机会", u.get("modes", "shutdown_skipped"), "2026-09-06:1")
check("告警队列", u.get("queues", "pending"), {"MaaEnd|endfield": {"run_id": "x"}})
check("旧文件都改名了", sorted(p.name for p in d3.glob("*.sent")), [])

print("[State 读回来的语义没变]")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import State  # noqa: E402
st = State(d3)
check("report_sent", st.report_sent("2026-09-06"), True)
check("没发过的那天", st.report_sent("2026-09-07"), False)
check("interim_covered 带条数", st.interim_covered("2026-09-06"), 7)
check("旧空标记 → 不再重播", st.interim_covered("2026-09-05"), 10**6)
check("没发过 → 0", st.interim_covered("2026-09-07"), 0)
# A non-numeric marker for a day still being judged is a bug (writes are atomic):
# it silently suppresses every further interim that day, so it is said - once,
# since the interim check runs every tick.
cw = Warns("ark.core")
st.store.set("marks", "interim:2026-09-08", "abc")
check("非数字标记仍按「已发、条数不详」", [st.interim_covered("2026-09-08") for _ in range(3)], [10**6] * 3)
check("非数字标记说一声，只说一次", len([ln for ln in cw.lines if "interim:2026-09-08" in ln]), 1)
st.store.set("marks", "interim:2026-09-08", "3")
check("改好后照常", st.interim_covered("2026-09-08"), 3)
st.store.set("marks", "interim:2026-09-08", "")
st.interim_covered("2026-09-08")
check("又坏了再说一次", len([ln for ln in cw.lines if "interim:2026-09-08" in ln]), 2)
check("卡池", st.banner_announced("明日方舟-202609041200"), True)
check("告警队列", st.load_pending(), {"MaaEnd|endfield": {"run_id": "x"}})
st.mark_report_sent("2026-09-07")
check("写完能读回", st.report_sent("2026-09-07"), True)

print("[state.json 已存在时，后来才补的旧文件也要迁——不能只在首次建档时迁]")
d4 = tmpdir()
import ark_relay.statestore as SS  # noqa: E402
SS._SWEPT.clear()
first = StateStore(d4)
first.set("weekly", "garden", {"done_week": "2026-W37"})    # 先有了 state.json
(d4 / "report-2026-09-07.sent").write_text("", encoding="utf-8")
(d4 / "pending.json").write_text(json.dumps({"MaaEnd|endfield": {"run_id": "y"}}), encoding="utf-8")
(d4 / "gameupdate-pending.json").write_text(json.dumps({"鸣潮": "客户端待更新"}), encoding="utf-8")
SS._SWEPT.clear()                                            # 模拟下一次进程启动
later = StateStore(d4)
check("后补的日报标记迁进来了", later.get("marks", "report:2026-09-07"), True)
check("后补的告警队列迁进来了", later.get("queues", "pending"), {"MaaEnd|endfield": {"run_id": "y"}})
check("后补的待更新登记迁进来了", later.get("updates", "gameupdate_pending"), {"鸣潮": "客户端待更新"})
check("原有的值没被动", later.get("weekly", "garden"), {"done_week": "2026-W37"})
check("旧文件收走了", sorted(p.name for p in d4.glob("*.sent")), [])

print("[state.json 里已有值时，旧文件不许覆盖它]")
d5 = tmpdir()
SS._SWEPT.clear()
s5 = StateStore(d5)
s5.set("versions", "okww", "v3.6.7")
(d5 / "okww-version.txt").write_text("v3.6.5", encoding="utf-8")   # 陈旧的遗留
SS._SWEPT.clear()
check("以 state.json 为准", StateStore(d5).get("versions", "okww"), "v3.6.7")
check("陈旧文件也收走", (d5 / "okww-version.txt").exists(), False)

print("[state.json unreadable: copied aside before anything overwrites it, said once per mtime]")
# Until 2026-10-10 the WARNING said the old content was untouched on disk, and the
# next set() overwrote state.json with the near-empty dict it fell back to.
import os  # noqa: E402
d6 = tmpdir()
SS._SWEPT.clear()
SS._CORRUPT_SAID.clear()
(d6 / "state.json").write_text('{"weekly": {"garden": {"done_week": "2026-W4', encoding="utf-8")
os.utime(d6 / "state.json", (1_790_000_000, 1_790_000_000))
sw = Warns("ark.statestore")
check("读不出来按空", StateStore(d6).section("weekly"), {})
check("别的实例再读不再说", [StateStore(d6).get("modes", "debug_until") for _ in range(3)], [None] * 3)
copies = sorted(d6.glob("state.json.corrupt-*"))
check("另存了一份", len(copies), 1)
check("另存的是原样", copies and copies[0].read_text(encoding="utf-8"), '{"weekly": {"garden": {"done_week": "2026-W4')
check("只说一次，说出另存的文件名", [copies[0].name in ln for ln in sw.lines] if copies else sw.lines, [True])
StateStore(d6).set("versions", "okww", "v3.6.7")
check("写入后另存的还在", copies and copies[0].exists(), True)
(d6 / "state.json").write_text("{bad", encoding="utf-8")
os.utime(d6 / "state.json", (1_790_000_100, 1_790_000_100))
StateStore(d6).get("versions", "okww")
check("又坏了（新的 mtime）再说一次、再存一份", (len(sw.lines), len(list(d6.glob("state.json.corrupt-*")))), (2, 2))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
