"""MAA's pre-update pass must not start a farming run, and must put the switch back.

MAA applies a pending update in its Bootstrapper at startup. Moving that into
the boot window is harmless - unless launching MAA also starts a round, which
is exactly what 启动后直接运行 (Gui/StartUpSettings/RunDirectly) does. AUTO-MAS
sets that flag True before every proxy run, so it is True whenever the relay
looks at it.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import preupdate
from ark_relay import preupdate_maa

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def make_maa(root: Path, run_directly: bool) -> Path:
    d = root / "maa"
    (d / "config").mkdir(parents=True, exist_ok=True)
    (d / "debug").mkdir(parents=True, exist_ok=True)
    (d / "config" / "gui.new.json").write_text(json.dumps({
        "Configurations": {"Default": {"Gui": {"StartUpSettings": {
            "RunDirectly": run_directly, "StartEmulator": False}}}}
    }, ensure_ascii=False), encoding="utf-8")
    return d


def read_flag(d: Path):
    data = json.loads((d / "config" / "gui.new.json").read_text(encoding="utf-8"))
    return data["Configurations"]["Default"]["Gui"]["StartUpSettings"]["RunDirectly"]


def main(root: Path) -> int:
    d = make_maa(root, True)
    was = preupdate_maa._maa_run_directly(d, False)
    check("读到原值 True", was, True)
    check("已关掉自动开跑", read_flag(d), False)
    preupdate_maa._maa_run_directly(d, True)
    check("能原样放回去", read_flag(d), True)

    # Nothing else in the file may move.
    data = json.loads((d / "config" / "gui.new.json").read_text(encoding="utf-8"))
    check("其他设置没被动到",
          data["Configurations"]["Default"]["Gui"]["StartUpSettings"]["StartEmulator"],
          False)

    # A config it cannot understand must be declined, not guessed at.
    bad = root / "bad"
    (bad / "config").mkdir(parents=True, exist_ok=True)
    (bad / "config" / "gui.new.json").write_text("{}", encoding="utf-8")
    check("配置读不懂时返回 None（跳过而非乱改）",
          preupdate_maa._maa_run_directly(bad, False), None)

    # The pending-update gate: no NewVersion directory means MAA has nothing
    # waiting, so the pre-update must not start it at all. This is the common
    # case - most boots have no update - and it is what keeps the pre-update
    # from putting a window on screen every single morning.
    check("没有待装更新时不认为有", preupdate.maa_update_pending(d), False)
    check("没有待装更新就不启动", preupdate.run_maa(d, budget_s=1), "")
    check("跳过后开关仍是原值", read_flag(d), True)
    (d / "NewVersion").mkdir()
    check("有 NewVersion 就认为有待装更新", preupdate.maa_update_pending(d), True)
    # With an update pending but no MAA.exe, it still must not blow up.
    check("有待装更新但找不到 MAA.exe 时安全退出",
          preupdate.run_maa(d, budget_s=1), "")
    check("退出后开关仍是原值", read_flag(d), True)
    check("目录为 None 时也安全", preupdate.run_maa(None), "")
    check("None 目录不算有待装更新", preupdate.maa_update_pending(None), False)

    launch_and_restore(root)
    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


def launch_and_restore(root: Path) -> None:
    """run_maa end to end with the machine-touching steps recorded: MAA's own
    no-autorun argument is passed, and the switch goes back on every path."""
    import logging  # noqa: PLC0415
    m = preupdate_maa
    d = make_maa(root / "e2e", True)
    (d / "MAA.exe").write_text("", encoding="utf-8")
    saved = {k: getattr(m, k) for k in ("_spawn_interactive", "_close", "_maa_await_verdict", "_maa_run_directly")}
    order, spawned = [], []
    real_set = m._maa_run_directly

    def _set(dir_, value):
        order.append(f"set {value}")
        return real_set(dir_, value)
    try:
        m._close = lambda exe: order.append("close")
        m._maa_run_directly = _set
        m._spawn_interactive = lambda exe, cwd, args=(), **kw: (spawned.append(tuple(args)), order.append("spawn"), True)[2]
        m._maa_await_verdict = lambda *a, **kw: ("", True)
        m.run_maa(d, budget_s=1, problems=[])
        check("带 MAA 自己的不自动开跑参数启动", spawned, [("--skip-startup-auto-run",)])
        check("关掉、启动、关 MAA、再放回原值", order, ["set False", "close", "spawn", "close", "set True"])
        check("开关是原值", read_flag(d), True)

        order.clear()
        m._maa_await_verdict = lambda *a, **kw: 1 / 0
        try:
            m.run_maa(d, budget_s=1, problems=[])
            check("中途出错照样往外抛", False, True)
        except ZeroDivisionError:
            check("中途出错照样往外抛", True, True)
        check("中途出错：先关 MAA，再放回原值", order[-2:], ["close", "set True"])
        check("中途出错：开关是原值", read_flag(d), True)

        grabbed = []

        class _Grab(logging.Handler):
            def emit(self, record):
                grabbed.append((record.levelno, record.getMessage()))
        h = _Grab()
        preupdate_maa.log.addHandler(h)
        calls = []
        # First call turns it off (it was on); the one putting it back fails.
        m._maa_run_directly = lambda dir_, value: (calls.append(value), True if len(calls) == 1 else None)[1]
        m._maa_await_verdict = lambda *a, **kw: ("", True)
        try:
            m.run_maa(d, budget_s=1, problems=[])
        finally:
            preupdate_maa.log.removeHandler(h)
        check("改不回去：WARNING，说清是哪个开关",
              [lv for lv, msg in grabbed if "启动后直接运行" in msg and "没能改回" in msg], [logging.WARNING])
    finally:
        for k, v in saved.items():
            setattr(m, k, v)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        raise SystemExit(main(Path(tmp)))
