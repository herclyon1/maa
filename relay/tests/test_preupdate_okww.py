"""OK-WW's pre-update must not start 鸣潮, and must put the switch back.

OK-WW updates through pyappify from a CNB git mirror, and that only happens
when ok-ww.exe - the pyappify shell - is the thing launched. But ok-ww.exe
honours "Auto Start Game When App Starts", which is on for unattended running.
Launching it at boot without disarming that would start the game itself, which
is the same hazard MAA's RunDirectly and MaaEnd's autostart already taught us.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import preupdate                       # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def make(root: Path, autostart: bool) -> Path:
    d = root / "okww"
    cfgdir = d / "data" / "apps" / "ok-ww" / "working" / "configs"
    cfgdir.mkdir(parents=True, exist_ok=True)
    (cfgdir / "Basic Options.json").write_text(json.dumps({
        "Auto Start Game When App Starts": autostart,
        "Mute Game while in Background": True,
        "Use DirectML": "Yes",
    }, ensure_ascii=False), encoding="utf-8")
    (d / "data" / "apps" / "ok-ww").mkdir(parents=True, exist_ok=True)
    (d / "data" / "apps" / "ok-ww" / "app.json").write_text(json.dumps({
        "current_version": "v3.6.4", "update_state": "idle", "update_error": None,
    }), encoding="utf-8")
    return d


def basic(d: Path) -> dict:
    return json.loads((d / "data" / "apps" / "ok-ww" / "working" / "configs"
                       / "Basic Options.json").read_text(encoding="utf-8"))


def main(root: Path) -> int:
    d = make(root, autostart=True)

    was = preupdate._okww_autostart(d, False)
    check("读到原值 True", was, True)
    check("已关掉自动开游戏", basic(d)["Auto Start Game When App Starts"], False)
    check("其他设置没被动到", basic(d)["Mute Game while in Background"], True)
    check("非布尔项也完好", basic(d)["Use DirectML"], "Yes")
    preupdate._okww_autostart(d, True)
    check("能原样放回去", basic(d)["Auto Start Game When App Starts"], True)

    check("读得到 app.json 状态", preupdate._okww_state(d)[:3],
          ("v3.6.4", "idle", ""))
    # 第四项是判断"到底检查过没有"的唯一依据，见 _okww_state 的注释。
    check("状态里带得出可用版本列表",
          isinstance(preupdate._okww_state(d)[3], tuple), True)

    bad = root / "bad"
    (bad / "data" / "apps" / "ok-ww" / "working" / "configs").mkdir(parents=True)
    check("配置读不懂时返回 None", preupdate._okww_autostart(bad, False), None)

    # No ok-ww.exe -> do nothing, and never leave the switch flipped.
    check("找不到 ok-ww.exe 时什么都不做", preupdate.run_okww(d, budget_s=1), "")
    check("跳过后开关仍是原值",
          basic(d)["Auto Start Game When App Starts"], True)
    check("目录为 None 时也安全", preupdate.run_okww(None), "")

    src = (Path(__file__).resolve().parents[1] / "ark_relay"
           / "preupdate.py").read_text(encoding="utf-8")
    # 2026-08-25：控制台令牌拿不到时退回 session 0，OK-WW 的更新流程根本不跑，
    # 而未变的版本文件被读成"无需更新"——那天 v3.6.5 已经发布十四小时。
    # 拿不到桌面就必须拒绝启动，并把这件事报上去。
    check("拒绝在 session 0 启动",
          "_spawn_interactive(exe, root, require_console=True, minimized=True)" in src, True)
    check("拿不到控制台会话要上报",
          "拿不到控制台会话" in src, True)
    check("安静不等于没有更新",
          "无法确认是否检查过更新" in src, True)
    check("在 finally 里还原开关", "finally:\n        _okww_autostart(root, was)" in src, True)
    # 2026-08-24: flipping the JSON was not enough - a leftover `ok web` held the
    # settings in memory and wrote them back, so ok-ww.exe read True and started
    # 鸣潮 during a check that was meant to open nothing.
    check("改配置前先停掉在跑的实例", "_okww_quiesce()\n    was = _okww_autostart" in src, True)
    check("收尾也清一次，不留游戏在后台",
          src.count("_okww_quiesce()") >= 3, True)

    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        raise SystemExit(main(Path(tmp)))
