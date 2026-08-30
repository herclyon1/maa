"""预更新一天只跑一遍。

2026-08-31：`wanted_today()` 只看「今天还有没有要跑 MaaEnd 的队列」，
没有记「今天已经跑过了」——于是**每次服务重启都重跑一整轮**，把
MAA / MaaEnd / OK-WW 挨个拉起来查更新。那天上午部署了三次，它跑了三次，
第三次 MAA 没在 180 秒内给出结论，推了一条「预更新没能确认」。
那条告警本身没说错，只是根本不该有第三次。

留出重试的口子：这一轮真有没确认的项时，隔 RETRY_MIN 分钟还能再试一次——
早上 08:45 查失败、09:00 队列就要开跑，那一次重试是有价值的。
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.config import SERVER_TZ                    # noqa: E402
from ark_relay.preupdate import RETRY_MIN, mark_run, should_run  # noqa: E402

FAILED: list[str] = []


def check(what, got, want):
    if got != want:
        FAILED.append(f"{what}: 得到 {got!r}，应为 {want!r}")


def main() -> int:
    d = Path(tempfile.mkdtemp())
    now = datetime(2026, 8, 31, 8, 45, tzinfo=SERVER_TZ)

    check("没记账过 → 跑", should_run(d, now), True)
    check("没有 state 目录 → 跑（不因为记不住就不干活）",
          should_run(None, now), True)

    mark_run(d, now, clean=True)
    check("今天干净地跑过 → 服务重启不重跑",
          should_run(d, now + timedelta(minutes=1)), False)
    check("过一整天 → 再跑",
          should_run(d, now + timedelta(days=1)), True)

    mark_run(d, now, clean=False)
    check("这轮有没确认的项，刚过一分钟 → 先别急着重试",
          should_run(d, now + timedelta(minutes=1)), False)
    check(f"隔了 {RETRY_MIN} 分钟 → 允许重试一次",
          should_run(d, now + timedelta(minutes=RETRY_MIN)), True)

    # 记账文件坏掉不能变成「从此不跑」
    (d / "preupdate.json").write_text("{坏的", encoding="utf-8")
    check("记账文件损坏 → 照跑", should_run(d, now), True)
    (d / "preupdate.json").write_text(json.dumps({"day": "2026-08-31"}),
                                      encoding="utf-8")
    check("记账缺时间戳 → 照跑", should_run(d, now), True)

    print("all checks passed" if not FAILED else "FAILED: " + "; ".join(FAILED))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
