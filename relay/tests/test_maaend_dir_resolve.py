"""MaaEnd 路径必须自己解析出来，解析不出来必须喊。

2026-08-28 查实：机器上的 `.env` 从来没设过 `ARK_MAAEND_DIR`
（`ARK_OKWW_DIR`、`ARK_AUTOMAS_DIR` 都设了，唯独漏了它）。
于是 `cfg.maaend_dir` 一直是 None，`Engine._archive_maaend_evidence`
在第一行 `if not src.is_dir(): return` 静默退出——**从写出来那天起一次都没跑成**。

代价是真的：MaaEnd 启动时会「Auto-cleared log files and debug artifacts」，
当天早上三轮选剑演武失败的 on_error 截图，在中午重试的瞬间就被清空了，
而本该抢救它们的代码从没执行过，还一个字都没打。

`plan.script_dir` 的文档字符串本来就写着「省得把 MaaEnd 路径配第二遍：
AUTO-MAS 已经知道了」——只是 `service.py` 用了，`Engine` 没用。
现在提到 `Config.__post_init__`，一次修好所有调用方。
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.config import Config  # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def _automas(tmp: Path, path_value: str) -> Path:
    """造一个最小的 AUTO-MAS 配置目录，只够 plan.script_dir 认出 MaaEnd。"""
    cfg = tmp / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "u1"}],
        "u1": {"Info": {"Name": "终末地", "Path": path_value}},
    }, ensure_ascii=False), encoding="utf-8")
    return tmp


def main() -> int:
    print("=== maaend_dir 解析 ===")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        want = tmp / "maaend"
        (want / "debug").mkdir(parents=True)
        _automas(tmp, str(want))

        # 1) 环境变量没设 → 从 AUTO-MAS 记录里解析出来
        c = Config(automas_dir=tmp, maaend_dir=None)
        check("环境变量没设时能从 AUTO-MAS 解析出来",
              c.maaend_dir is not None and Path(c.maaend_dir) == want, True)

        # 2) 显式给了就不许被覆盖
        explicit = tmp / "elsewhere"
        c2 = Config(automas_dir=tmp, maaend_dir=explicit)
        check("显式配置优先，不被解析覆盖", Path(c2.maaend_dir), explicit)

        # 3) 没有 automas_dir 时不炸、保持 None
        c3 = Config(automas_dir=None, maaend_dir=None)
        check("没有 automas_dir 时保持 None 且不抛异常", c3.maaend_dir, None)

    # 4) AUTO-MAS 里查不到 MaaEnd → None，不许瞎编一个路径
    with tempfile.TemporaryDirectory() as td:
        tmp = _automas(Path(td), "")          # Path 为空 = 查不到
        c4 = Config(automas_dir=tmp, maaend_dir=None)
        check("AUTO-MAS 里查不到就是 None，不许编路径", c4.maaend_dir, None)

    print("\n=== 解析不出来时必须喊，不许静默 return ===")
    import logging
    from ark_relay import engine as E

    class _Rec:
        run_id = "r/1"
        script = "MaaEnd"

    class _Eng:
        cfg = Config(automas_dir=None, maaend_dir=None)
        _archive_maaend_evidence = E.Engine._archive_maaend_evidence

    seen = []

    class _Cap(logging.Handler):
        def emit(self, r):
            seen.append((r.levelno, r.getMessage()))

    h = _Cap()
    E.log.addHandler(h)
    try:
        _Eng()._archive_maaend_evidence(_Rec())
    finally:
        E.log.removeHandler(h)

    check("maaend_dir 缺失时打了 ERROR",
          any(lv >= logging.ERROR for lv, _ in seen), True)
    check("ERROR 里点名 maaend_dir",
          any("maaend_dir" in m for _, m in seen), True)

    print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
