"""OK-WW's pre-update must not start 鸣潮, and must put the switch back.

OK-WW updates through pyappify from a CNB git mirror, and that only happens
when ok-ww.exe - the pyappify shell - is the thing launched. But ok-ww.exe
honours "Auto Start Game When App Starts", which is on for unattended running.
Launching it at boot without disarming that would start the game itself, which
is the same hazard MAA's RunDirectly and MaaEnd's autostart already taught us.
"""
import ast
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import preupdate
from ark_relay import preupdate_okww

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

    was = preupdate_okww._okww_autostart(d, False)
    check("读到原值 True", was, True)
    check("已关掉自动开游戏", basic(d)["Auto Start Game When App Starts"], False)
    check("其他设置没被动到", basic(d)["Mute Game while in Background"], True)
    check("非布尔项也完好", basic(d)["Use DirectML"], "Yes")
    preupdate_okww._okww_autostart(d, True)
    check("能原样放回去", basic(d)["Auto Start Game When App Starts"], True)

    check("读得到 app.json 状态", preupdate_okww._okww_state(d)[:3],
          ("v3.6.4", "idle", ""))
    # 第四项是判断"到底检查过没有"的唯一依据，见 _okww_state 的注释。
    check("状态里带得出可用版本列表",
          isinstance(preupdate_okww._okww_state(d)[3], tuple), True)

    bad = root / "bad"
    (bad / "data" / "apps" / "ok-ww" / "working" / "configs").mkdir(parents=True)
    check("配置读不懂时返回 None", preupdate_okww._okww_autostart(bad, False), None)

    # No ok-ww.exe -> do nothing, and never leave the switch flipped.
    check("找不到 ok-ww.exe 时什么都不做", preupdate.run_okww(d, budget_s=1), "")
    check("跳过后开关仍是原值",
          basic(d)["Auto Start Game When App Starts"], True)
    check("目录为 None 时也安全", preupdate.run_okww(None), "")

    src = "".join(q.read_text(encoding="utf-8") for q in sorted((Path(__file__).resolve().parents[1] / "ark_relay").glob("preupdate*.py")))  # 预更新拆成了五个文件，一起看
    # 2026-08-25：控制台令牌拿不到时退回 session 0，OK-WW 的更新流程根本不跑，
    # 而未变的版本文件被读成"无需更新"——那天 v3.6.5 已经发布十四小时。
    # 拿不到桌面就必须拒绝启动，并把这件事报上去。
    check("拒绝在 session 0 启动",
          "_spawn_interactive(exe, root, require_console=True, minimized=True)" in src, True)
    check("拿不到控制台会话要上报",
          "拿不到控制台会话" in src, True)
    check("安静不等于没有更新",
          "无法确认是否检查过更新" in src, True)
    # The shape the user-switches guard accepts: the setter's old value goes back
    # through the same setter inside a `finally` of run_okww.
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "run_okww")
    restores = [c for t in ast.walk(fn) if isinstance(t, ast.Try) for st in t.finalbody for c in ast.walk(st)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_okww_autostart"
                and any(isinstance(a, ast.Name) and a.id == "was" for a in c.args)]
    check("在 finally 里还原开关", len({id(c) for c in restores}), 1)
    # 2026-08-24: flipping the JSON was not enough - a leftover `ok web` held the
    # settings in memory and wrote them back, so ok-ww.exe read True and started
    # 鸣潮 during a check that was meant to open nothing.
    check("改配置前先停掉在跑的实例", "_okww_quiesce(" in src
          and src.index("_okww_quiesce(", src.index("def run_okww"))
          < src.index("was = _okww_autostart"), True)
    # 数的是**真正的调用点**，不是字面量出现次数。2026-09-08 栽过一次：
    # 给 _okww_quiesce 加了个可注入的 sleep 参数（为了测试不真等两秒），
    # 定义那一行就不再长得像 `_okww_quiesce()`，字面量计数少了一个，测试当场变红——
    # 而调用点一个没少。按字面量数等于让断言依赖签名的写法。
    calls = sum(1 for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_okww_quiesce")
    check("收尾也清一次，不留游戏在后台", calls >= 2, True)

    timeout_mid_download(root)
    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


def timeout_mid_download(root: Path) -> None:
    """Out of time while app.json still says downloading: a failure, never 「无需更新」."""
    m = preupdate_okww
    d = make(root / "dl", autostart=True)
    appjson = d / "data" / "apps" / "ok-ww" / "app.json"
    appjson.write_text(json.dumps({"current_version": "v3.7.3", "update_state": "downloading",
                                   "update_error": None, "available_versions": ["v3.7.4", "v3.7.3"]}),
                       encoding="utf-8")
    now = [0.0]
    out = m._okww_await_update(d, 240, "v3.7.3", ("v3.7.3",), m._okww_stamp(d),
                               sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    check("超时仍在下载：带回卡住的状态", out, ("", True, "", "downloading"))
    check("等满了预算才算超时", now[0] >= 240, True)

    appjson.write_text(json.dumps({"current_version": "v3.7.3", "update_state": "idle",
                                   "update_error": None}), encoding="utf-8")
    now[0] = 0.0
    out = m._okww_await_update(d, 240, "v3.7.3", (), m._okww_stamp(d) - 10,
                               sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    check("空闲且检查过：照旧算查完，不算卡住", out, ("", True, "", ""))
    check("至少等过上游那 30 秒检查", now[0] >= m.OKWW_MIN_WAIT_SECONDS, True)

    probs = []
    m._okww_report(probs, 240, "v3.7.3", ("v3.7.4",), "", True, "", "downloading", Path("shot.png"))
    check("超时下载中：记成问题", len(probs), 1)
    check("问题里写了还在下载、没更新完", "还在「downloading」" in probs[0] and "没更新完" in probs[0], True)
    check("问题里明说不是无需更新", "不是「无需更新」" in probs[0], True)
    check("问题里带截图", "shot.png" in probs[0], True)
    probs = []
    m._okww_report(probs, 240, "v3.7.3", ("v3.7.3",), "", True, "", "", None)
    check("真没有新版：不记问题", probs, [])

    os.environ["ARK_STATE_DIR"] = str(root / "state")
    try:
        taken = []
        shot = m._okww_timeout_shot(lambda out: taken.append(out) or True)
        check("截图存进状态目录的 preupdate/", shot is not None and shot.parent == root / "state" / "preupdate", True)
        check("截图就是截下来的那张", taken, [shot])
        check("截不到时返回 None", m._okww_timeout_shot(lambda out: False), None)
        check("截图出错也不抛", m._okww_timeout_shot(lambda out: 1 / 0), None)
    finally:
        os.environ.pop("ARK_STATE_DIR", None)

    # run_okww end to end, with the machine-touching steps recorded instead of run.
    (d / "ok-ww.exe").write_text("", encoding="utf-8")
    saved = {k: getattr(m, k) for k in ("_spawn_interactive", "_okww_quiesce", "_close",
                                        "_okww_await_update", "_okww_timeout_shot")}
    order = []
    try:
        m._okww_quiesce = lambda *a, **kw: order.append("quiesce")
        m._close = lambda exe: order.append("close")
        m._okww_timeout_shot = lambda: order.append("shot") or Path("t.png")
        m._okww_await_update = lambda *a, **kw: ("", True, "", "downloading")
        m._spawn_interactive = lambda *a, **kw: order.append("spawn") or True
        probs = []
        check("超时下载中：不报已更新", m.run_okww(d, budget_s=240, problems=probs), "")
        check("超时下载中：问题里是没更新完", ["没更新完" in p for p in probs], [True])
        check("先停掉所有实例再启动我们自己的，截图在关之前，关的是我们启动的",
              order, ["quiesce", "spawn", "shot", "close", "quiesce"])
        check("开关放回原值", basic(d)["Auto Start Game When App Starts"], True)

        order.clear()
        m._spawn_interactive = lambda *a, **kw: order.append("spawn") or False
        probs = []
        m.run_okww(d, budget_s=240, problems=probs)
        check("没启动成功就不去关 OK-WW", "close" in order, False)

        order.clear()
        m._spawn_interactive = lambda *a, **kw: order.append("spawn") or True
        m._okww_await_update = lambda *a, **kw: ("", True, "", "")
        probs = []
        m.run_okww(d, budget_s=240, problems=probs)
        check("没卡住就不截图", "shot" in order, False)

        # Something raises after the launch: OK-WW is still closed, then the switch goes back.
        order.clear()
        saved_set = m._okww_autostart

        def _set(root_, value):
            order.append(f"set {value}")
            return saved_set(root_, value)
        m._okww_autostart = _set
        m._okww_await_update = lambda *a, **kw: 1 / 0
        try:
            m.run_okww(d, budget_s=240, problems=[])
            check("中途出错照样往外抛", False, True)
        except ZeroDivisionError:
            check("中途出错照样往外抛", True, True)
        check("中途出错：先关 OK-WW，再把开关放回原值",
              order, ["quiesce", "set False", "spawn", "close", "quiesce", "set True"])
        check("中途出错：开关是原值", basic(d)["Auto Start Game When App Starts"], True)

        # The switch cannot be put back: a WARNING (pushed to the group), naming it.
        import logging  # noqa: PLC0415
        grabbed = []

        class _Grab(logging.Handler):
            def emit(self, record):
                grabbed.append((record.levelno, record.getMessage()))
        h = _Grab()
        preupdate_okww.log.addHandler(h)
        calls = []
        # First call turns it off (it was on); the one putting it back fails.
        m._okww_autostart = lambda root_, value: (calls.append(value), True if len(calls) == 1 else None)[1]
        m._okww_await_update = lambda *a, **kw: ("", True, "", "")
        try:
            m.run_okww(d, budget_s=240, problems=[])
        finally:
            preupdate_okww.log.removeHandler(h)
            m._okww_autostart = saved_set
        check("改不回去：WARNING，说清是哪个开关",
              [lv for lv, msg in grabbed if "自动开游戏" in msg and "没能改回" in msg], [logging.WARNING])
    finally:
        for k, v in saved.items():
            setattr(m, k, v)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        raise SystemExit(main(Path(tmp)))
