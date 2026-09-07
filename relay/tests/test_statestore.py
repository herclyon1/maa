"""state.json：一个文件、登记过的字段才能写、原子落盘、旧文件自动迁入。"""
import json, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.statestore import StateStore  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

d = Path(tempfile.mkdtemp())
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
d2 = Path(tempfile.mkdtemp())
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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
