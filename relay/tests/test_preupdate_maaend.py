"""MaaEnd's pre-update must skip the update-completed modal without arming a run.

Two things have to be true at once. --autostart is the only branch in MXU's
App.tsx that skips the "更新完成" modal, and without it the code returns before
the update check ever runs - the pre-update then waits out its whole budget for
a line nobody will write. But --autostart also feeds `shouldAutoRun`, and the
instance it would run is `cliInstanceId || autoStartInstanceId`. Clearing that
field is what keeps a boot-time update check from becoming a farming round.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import preupdate
from ark_relay import preupdate_common
from ark_relay import preupdate_maaend

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def make(root: Path, instance: str) -> Path:
    d = root / "maaend"
    (d / "config").mkdir(parents=True, exist_ok=True)
    (d / "debug").mkdir(parents=True, exist_ok=True)
    (d / "config" / "mxu-MaaEnd.json").write_text(json.dumps({
        "version": "1.0",
        "settings": {"autoStartInstanceId": instance, "autoRunOnLaunch": True,
                     "webServerPort": 12701, "theme": "light"},
        "instances": [{"id": "automas", "name": "AUTO-MAS", "tasks": [1, 2, 3]}],
    }, ensure_ascii=False), encoding="utf-8")
    return d


def settings(d: Path) -> dict:
    return json.loads((d / "config" / "mxu-MaaEnd.json").read_text(
        encoding="utf-8"))["settings"]


def main(root: Path) -> int:
    d = make(root, "automas")

    was = preupdate_maaend._maaend_autostart_instance(d, "")
    check("读到原值", was, "automas")
    check("已清空自动执行实例", settings(d)["autoStartInstanceId"], "")
    check("autoRunOnLaunch 没被动", settings(d)["autoRunOnLaunch"], True)
    check("其他设置没被动", settings(d)["webServerPort"], 12701)

    preupdate_maaend._maaend_autostart_instance(d, was)
    check("能原样还回去", settings(d)["autoStartInstanceId"], "automas")

    # The instances list is what the operator sees in the UI - never touch it.
    data = json.loads((d / "config" / "mxu-MaaEnd.json").read_text(encoding="utf-8"))
    check("实例列表没被改", [i["name"] for i in data["instances"]], ["AUTO-MAS"])

    bad = root / "bad"
    (bad / "config").mkdir(parents=True, exist_ok=True)
    (bad / "config" / "mxu-MaaEnd.json").write_text("{}", encoding="utf-8")
    probs: list[str] = []
    check("配置读不懂时返回 None", preupdate_maaend._maaend_autostart_instance(bad, "", probs), None)
    check("配置读不懂进问题清单（不许当无需更新）", len(probs) == 1 and "没有确认过是否有更新" in probs[0], True)

    # No MaaEnd.exe: bail out before touching anything, and say so.
    probs = []
    check("找不到 MaaEnd.exe 时不启动", preupdate.run(d, budget_s=1, problems=probs), "")
    check("找不到 MaaEnd.exe 进问题清单", len(probs) == 1 and "MaaEnd.exe" in probs[0], True)
    check("跳过后实例设置仍是原值",
          settings(d)["autoStartInstanceId"], "automas")
    probs = []
    check("目录为 None 时也安全", preupdate.run(None, problems=probs), "")
    check("没配 MaaEnd 目录不算问题", probs, [])

    # MaaEnd would not launch: the update check never ran -> a problem, and the
    # auto-start instance is restored.
    (d / "MaaEnd.exe").write_text("", encoding="utf-8")
    orig_spawn = preupdate_maaend._spawn_interactive
    preupdate_maaend._spawn_interactive = lambda *a, **k: False
    try:
        probs = []
        check("启动失败时返回空", preupdate.run(d, budget_s=1, problems=probs, sleep=lambda s: None), "")
        check("启动失败进问题清单", len(probs) == 1 and "没能启动" in probs[0], True)
        check("启动失败后实例设置还回原值", settings(d)["autoStartInstanceId"], "automas")
    finally:
        preupdate_maaend._spawn_interactive = orig_spawn
        (d / "MaaEnd.exe").unlink()

    # Counter-example: MaaEnd launches and reports 「有更新=false」 -> no problem.
    (d / "MaaEnd.exe").write_text("", encoding="utf-8")
    logdir = preupdate_common._log_dir(d)
    logdir.mkdir(parents=True, exist_ok=True)

    def fake_spawn(*a, **k):
        (logdir / "2026-10-05-9.log").write_text(
            "08:46:23 INFO  [App] 检查更新: MaaEnd, 当前版本: v2.31.0, 频道: beta\n"
            "08:46:24 INFO  [App] 更新检查完成: 最新版本=v2.31.0, 有更新=false\n", encoding="utf-8")
        return True
    preupdate_maaend._spawn_interactive = fake_spawn
    orig_close = preupdate_maaend._close
    preupdate_maaend._close = lambda exe: None
    try:
        probs = []
        check("正常启动、无需更新时返回空", preupdate.run(d, budget_s=3, problems=probs, sleep=lambda s: None), "")
        check("正常启动、无需更新时问题清单为空（反例）", probs, [])
    finally:
        preupdate_maaend._spawn_interactive = orig_spawn
        preupdate_maaend._close = orig_close
        (d / "MaaEnd.exe").unlink()

    src = "".join(q.read_text(encoding="utf-8") for q in sorted((Path(__file__).resolve().parents[1] / "ark_relay").glob("preupdate*.py")))  # 预更新拆成了五个文件，一起看
    check("用了 --autostart", "--autostart" in src, True)
    check("清空的是 autoStartInstanceId", "autoStartInstanceId" in src, True)

    # 更新通知必须带上老版本号——只报新版本号看不出发生了什么。
    # 2026-08-27 用户指出：OK-WW 报「v3.6.6-beta.1 → v3.6.6」，MaaEnd 只报新版。
    check("带老版本号",
          preupdate_maaend._maaend_span("v2.26.0-beta.6", "v2.26.0-beta.7"),
          "v2.26.0-beta.6 → v2.26.0-beta.7")
    check("老版本号没拿到要明说（不许编）",
          preupdate_maaend._maaend_span("", "v2.26.0-beta.7"), "（旧版本没读到）→ v2.26.0-beta.7")
    check("同版本=旧版号读错了，明说", preupdate_maaend._maaend_span("v1", "v1"), "（旧版本没读到）→ v1")

    vlog = root / "20260827-1.log"
    vlog.write_text("12:37:12 INFO  [App] 检查更新: MaaEnd, "
                    "当前版本: v2.26.0-beta.1, 频道: beta\n", encoding="utf-8")
    check("从日志认出当前版本", preupdate_maaend._maaend_version_in(vlog), "v2.26.0-beta.1")
    check("没有日志就返回空串", preupdate_maaend._maaend_version_in(None), "")

    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        raise SystemExit(main(Path(tmp)))

