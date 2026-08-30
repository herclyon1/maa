"""前置条件不满足时，绝不许静默变成「全绿」。

2026-08-30 一次排查里同一个形状的 bug 出现了三次：
  1. `_verify_outcome` 压根没有 MAA 分支，走到就 return None（=全干成）
  2. `_okww_nest_expected` 读不到配置返回 False，和「配置说不用打」不可区分，
     残象聚落那一项**整个消失**
  3. 我给 MAA 加核对时，`_maa_app_log` 读不到日志返回 ""，
     空文本喂给 `maa_checks` 全部判过——又一次假全绿
外加 `_verify_outcome` 的 except 分支直接 return None：核对自己崩了也报全绿。

这个文件把这四条钉死。
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import outcome  # noqa: E402
from ark_relay.engine import _maa_app_log, _okww_nest_expected  # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def main():
    print("1) MAA 日志读不到 → 必须 None，不能是空串")
    check("没配目录", _maa_app_log(None, datetime.now()), None)
    check("目录不存在", _maa_app_log("/no/such/dir", datetime.now()), None)

    print("2) 空文本喂给 maa_checks 会全绿——所以上面那步必须拦住")
    check("空串确实会被判成全绿（这就是为什么不能返回空串）",
          outcome.summarize(outcome.maa_checks(""), "MAA"), None)

    print("3) OK-WW 配置读不到 → 必须 None，不能是 False")
    check("没配 automas_dir", _okww_nest_expected(None), None)
    check("目录不存在", _okww_nest_expected("/no/such/dir"), None)

    print("4) 读不到配置时，残象聚落不许悄悄消失")
    # 直接验判据本身：expect_nest=False 时确实没有这一项，
    # 所以 engine 必须自己补一条「读不到配置」，否则整项蒸发。
    got = outcome.okww_checks("Daily Task Completed", expect_nest=False)
    check("expect_nest=False 时残象聚落这一项确实不存在（故必须另行补报）",
          any("残象" in c.label for c in got), False)

    print("5) 补报的那一条必须是「没干成」，会被 summarize 报出去")
    checks = outcome.okww_checks("Daily Task Completed", expect_nest=False)
    checks.append(outcome.Check("能读到 OK-WW 生效中的配置", False, "读不到"))
    check("summarize 会把它报出来", outcome.summarize(checks, "OK-WW") is not None,
          True)

    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
