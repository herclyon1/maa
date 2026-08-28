"""周常乐园的周门：本周做完就关掉检查，周一 04:00 开回来。

和剿灭那道门是同一个形状，所以周界口径必须一致——直接复用
`annihilation.week_key`，不许自己再算一遍。这个文件把三件事钉住：

  1. 周界就是周一 04:00（周一 03:59 还算上一周）；
  2. 记账只写状态文件，不碰配置（落盘交给 enforce）；
  3. enforce 幂等，而且新的一周会把检查放回去。
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import garden                             # noqa: E402
from ark_relay.annihilation import week_key              # noqa: E402
from ark_relay.config import SERVER_TZ                   # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def test_week_boundary() -> None:
    """周一 04:00 才翻篇。03:59 跑的那轮必须还算上一周。"""
    print("[周界：周一 04:00]")
    mon = datetime(2026, 8, 24, 3, 59, tzinfo=SERVER_TZ)      # 周一 03:59
    check("周一 03:59 和上周日同一周",
          week_key(mon) == week_key(mon - timedelta(hours=6)), True)
    check("周一 04:01 已经是新的一周",
          week_key(mon + timedelta(minutes=2)) != week_key(mon), True)


def _make_master(root: Path, tasks: list[str]) -> Path:
    """造一份和机器上一样的母本：<automas>/data/<sid>/Default/ConfigFile/DailyTask.json"""
    d = root / "automas" / "data" / "c5e96ddc" / "Default" / "ConfigFile"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "DailyTask.json"
    f.write_text(json.dumps({
        "Which to Farm": "Forgery Challenge",
        garden.KEY: list(tasks),
        "Exit After Task": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return root / "automas"


def _read(automas: Path) -> list[str]:
    f = automas / "data" / "c5e96ddc" / "Default" / "ConfigFile" / "DailyTask.json"
    return json.loads(f.read_text(encoding="utf-8"))[garden.KEY]


def _other_keys(automas: Path) -> dict:
    f = automas / "data" / "c5e96ddc" / "Default" / "ConfigFile" / "DailyTask.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    return {k: v for k, v in d.items() if k != garden.KEY}


def test_gate(tmp: Path) -> None:
    print("[记账 → 落盘 → 周一恢复]")
    now = datetime(2026, 8, 26, 12, 0, tzinfo=SERVER_TZ)   # 周三
    automas = _make_master(tmp, [garden.TASK_NAME, "Other Task"])
    g = garden.GardenGate(tmp, automas)
    before_other = _other_keys(automas)

    msg = g.on_success(now)
    check("第一次记账有回话", bool(msg), True)
    check("记账**不碰配置**（落盘留给 enforce）",
          garden.TASK_NAME in _read(automas), True)
    check("状态文件记下了本周", json.loads((tmp / "garden.json").read_text())["done_week"],
          week_key(now))
    check("同一周重复记账不再啰嗦", g.on_success(now), "")

    check("enforce 生效", g.enforce(now), True)
    check("检查已关掉", garden.TASK_NAME in _read(automas), False)
    check("同组别的任务没被误伤", "Other Task" in _read(automas), True)
    check("DailyTask 其余键原样保留", _other_keys(automas), before_other)
    check("已经关掉了就不再重复写", g.enforce(now), False)

    nxt = now + timedelta(days=7)
    check("新的一周会把检查放回去", g.enforce(nxt), True)
    check("检查回来了", garden.TASK_NAME in _read(automas), True)
    check("过期记账已清掉", json.loads((tmp / "garden.json").read_text()), {})

    # 找不到母本时必须安静地不动手，而不是抛异常把中继带崩
    g2 = garden.GardenGate(tmp, tmp / "nowhere")
    g2._save({"done_week": week_key(now)})                    # noqa: SLF001
    check("母本找不到时 enforce 返回 False 而不炸", g2.enforce(now), False)


def main(tmp: Path) -> int:
    test_week_boundary()
    test_gate(tmp)
    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as t:
        raise SystemExit(main(Path(t)))
