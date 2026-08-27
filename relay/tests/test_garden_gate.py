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


class FakeGate(garden.GardenGate):
    """把 API 换成内存里的一份配置，好在本地验行为。"""

    def __init__(self, state_dir, tasks):
        super().__init__(state_dir, host="127.0.0.1")
        # `Info.IfUseMasConfig: None` 不是摆设：AUTO-MAS 的 /user/get 真的会
        # 吐出这个字段，而 /user/update **不接受**它，原样回写就报
        # `AttributeError: 配置项 'Info.IfUseMasConfig' 不存在`。
        # 2026-08-26 这条错每 30 秒刷一次日志，刷了一下午没人发现，
        # 就是因为原来的假后端照单全收，比真后端宽容。
        self.cfg = {"Task": {"AdditionalTasks": list(tasks)},
                    "Info": {"Name": "ok-ww", "IfUseMasConfig": None}}
        self.locked = False
        self.writes = 0

    def _find(self):
        # 生产里每次都从 API 取一份新的，写失败不会污染下一次。
        # 假环境必须照这个语义给副本，否则「锁着时没改动」根本测不出来。
        import copy
        return ("sid", "uid", copy.deepcopy(self.cfg))

    def _write(self, cfg):
        self.writes += 1
        if self.locked:
            return False
        # 真后端会拒绝值为 None 的字段。假后端也必须拒绝，否则测出来的
        # 「写成功」在机器上是假的。
        for section, body in cfg.items():
            if isinstance(body, dict):
                for k, v in body.items():
                    if v is None:
                        raise _NullField(f"{section}.{k}")
        return True


class _NullField(Exception):
    """后端拒收 None 字段，照它的原话报。"""


def _patch(gate):
    garden._okww_user = lambda host: gate._find()          # noqa: SLF001

    def fake_post(host, path, body):
        if path.endswith("/user/update"):
            try:
                ok = gate._write(body["data"])            # noqa: SLF001
            except _NullField as exc:
                return {"status": "error",
                        "message": f"AttributeError: 配置项 '{exc}' 不存在"}
            if not ok:
                return {"status": "error", "message": "ValueError: 配置已锁定, 无法修改"}
            gate.cfg = body["data"]
            return {"status": "success"}
        return {}
    garden._post = fake_post                               # noqa: SLF001


def test_gate(tmp: Path) -> None:
    print("[记账 → 落盘 → 周一恢复]")
    now = datetime(2026, 8, 26, 12, 0, tzinfo=SERVER_TZ)   # 周三
    g = FakeGate(tmp, [garden.TASK_NAME, "Other Task"])
    _patch(g)

    msg = g.on_success(now)
    check("第一次记账有回话", bool(msg), True)
    check("记账**不碰配置**（这一刻配置多半是锁的）",
          garden.TASK_NAME in g.cfg["Task"]["AdditionalTasks"], True)
    check("状态文件记下了本周", json.loads((tmp / "garden.json").read_text())["done_week"],
          week_key(now))
    check("同一周重复记账不再啰嗦", g.on_success(now), "")

    g.locked = True
    check("配置锁着时 enforce 不算成功", g.enforce(now), False)
    check("锁着也不会把检查删掉",
          garden.TASK_NAME in g.cfg["Task"]["AdditionalTasks"], True)

    g.locked = False
    check("解锁后 enforce 生效", g.enforce(now), True)
    check("检查已关掉", garden.TASK_NAME in g.cfg["Task"]["AdditionalTasks"], False)
    check("同组别的任务没被误伤", "Other Task" in g.cfg["Task"]["AdditionalTasks"], True)
    check("已经关掉了就不再重复写", g.enforce(now), False)

    nxt = now + timedelta(days=7)
    check("新的一周会把检查放回去", g.enforce(nxt), True)
    check("检查回来了", garden.TASK_NAME in g.cfg["Task"]["AdditionalTasks"], True)
    check("过期记账已清掉", json.loads((tmp / "garden.json").read_text()), {})


def main(tmp: Path) -> int:
    test_week_boundary()
    test_gate(tmp)
    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as t:
        raise SystemExit(main(Path(t)))
