"""The deploy's "only the relevant tests" selector never skips a test that could
catch the change (the user's condition, 2026-09-18: allowed only if not a
single bug slips through).

* a test that executes a changed module is picked;
* a test that maps to no module (source scan / subprocess) is always picked;
* a test file that itself changed is always picked;
* a change outside the relay modules, a missing or stale map, or a test the map
  does not know -> empty pick, meaning the deploy runs everything.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "mac" / "lib"))
import changed_covered as cc

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


orig = (cc._sh, cc.changed_modules, cc.TEST_MAP, cc.REPO)
with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    (t / "relay" / "tests").mkdir(parents=True)
    for n in ("test_a.py", "test_b.py", "test_scan.py", "test_new.py"):
        (t / "relay" / "tests" / n).write_text("", encoding="utf-8")
    cc.REPO = t
    cc.TEST_MAP = t / "relay" / "tests" / "test-map.json"
    cc.TEST_MAP.write_text(json.dumps({"test_a.py": ["phone", "config"], "test_b.py": ["engine"],
                                       "test_scan.py": [], "test_new.py": ["phone"]}), encoding="utf-8")
    state = {"diff": ["relay/ark_relay/phone.py"], "status": []}
    cc._sh = lambda *a: "\n".join(state["status"] if a[1] == "status" else state["diff"])
    cc.changed_modules = lambda base: ({"phone"}, set())

    print("[改了 phone.py：跑碰到 phone 的测试 + 不走 import 的测试]")
    picked, why = cc.tests_for("HEAD")
    check("选中 a、new（碰 phone）和 scan（不映射）", picked, ["test_a.py", "test_new.py", "test_scan.py"])
    check("b 不跑（只碰 engine）", "test_b.py" not in picked)

    print("\n[测试文件自己改了：一定跑]")
    state["status"] = [" M relay/tests/test_b.py"]
    picked, _ = cc.tests_for("HEAD")
    check("b 也进来了", "test_b.py" in picked)
    state["status"] = []

    print("\n[改动不在中继模块范围：全量]")
    state["diff"] = ["relay/ark_relay/phone.py", "web/app.js"]
    picked, why = cc.tests_for("HEAD")
    check("空选择 = 全量", picked, [])
    check("说了原因", "全量" in why)
    state["diff"] = ["relay/ark_relay/phone.py"]

    print("\n[映射表不认识某个测试：全量]")
    (t / "relay" / "tests" / "test_unknown.py").write_text("", encoding="utf-8")
    picked, why = cc.tests_for("HEAD")
    check("空选择", picked, [])
    check("点名不认识的测试", "test_unknown" in why)
    (t / "relay" / "tests" / "test_unknown.py").unlink()

    print("\n[没有映射表：全量]")
    cc.TEST_MAP.unlink()
    picked, why = cc.tests_for("HEAD")
    check("空选择", picked, [])

cc._sh, cc.changed_modules, cc.TEST_MAP, cc.REPO = orig
print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("all checks passed")
