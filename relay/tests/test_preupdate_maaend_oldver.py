"""MaaEnd 更新通知必须带旧版本号：「v2.28.0-beta.1 → v2.28.0-beta.2」。

2026-09-06、09-07 两天的通知都只有一个版本号。机器上的证据
（debug/2026-09-07-2.log）：

    08:47:05 [App] 检测到刚更新完成: v2.28.0-beta.2
    08:47:05 [App] 检查更新: MaaEnd, 当前版本: v2.28.0-beta.2, 频道: beta

更新后的进程自己也写「当前版本」，写的是新版号；老代码把它当旧版号
覆盖掉，_span 又把「旧==新」吞成一个版本号。更新还把 debug 目录的旧日志
一起换掉了，所以中继得自己记住上一次确认过的版本。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import preupdate_maaend
from ark_relay import preupdate_maaend as PM  # 实现在这个模块里，猴子补丁要打在它身上
from ark_relay.statestore import StateStore
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

NEW = "v2.28.0-beta.2"
OLD = "v2.28.0-beta.1"
POST_UPDATE_LOG = (
    "2026-09-07 08:47:05 INFO  [App] 已清除待安装更新信息\n"
    f"2026-09-07 08:47:05 INFO  [App] 检测到刚更新完成: {NEW}\n"
    f"2026-09-07 08:47:05 INFO  [App] 检查更新: MaaEnd, 当前版本: {NEW}, 频道: beta\n")

# 不真的拉起 MaaEnd
PM._spawn_interactive = lambda *a, **k: True
PM._close = lambda exe: None


def run_case(label, *, file_ver, prev_log, kept, logs):
    """logs：按时间顺序出现的 (文件名, 内容)；第一份是启动前就有的。"""
    d = tmpdir(); (d / "debug").mkdir()
    state = d / "state"
    if file_ver:
        (d / "interface.json").write_text(json.dumps({"version": file_ver}), encoding="utf-8")
    if kept:
        StateStore(state).set("versions", "maaend", kept)   # 版本记在 state.json 的 versions 段
    seq = list(logs)
    if prev_log is not None:
        (d / "debug" / "2026-09-06-1.log").write_text(prev_log, encoding="utf-8")
    calls = {"n": 0}
    def newest(_dir):
        # 第一次是启动前看一眼；之后每次轮询多出一份新日志
        i = calls["n"]; calls["n"] += 1
        if i == 0:
            return (d / "debug" / "2026-09-06-1.log") if prev_log is not None else None
        name, text = seq[min(i - 1, len(seq) - 1)]
        f = d / "debug" / name
        f.write_text(text, encoding="utf-8")
        return f
    PM._newest_log = newest
    # 不真等：这个用例本来就是拿现成的日志文件喂进去，轮询间隔一秒纯属空耗。
    # 2026-09-08 之前这一个测试要跑 6 秒，而部署每次都要跑整套测试。
    got = preupdate_maaend._run_maaend(d, d / "MaaEnd.exe", 6, [], state,
                                       sleep=lambda _s: None)
    return got, state


print("[今天的形状：文件已是新版、旧日志被清、只有中继记得昨天的版本]")
got, state = run_case("kept", file_ver=NEW, prev_log=None, kept=OLD,
                      logs=[("2026-09-07-2.log", POST_UPDATE_LOG)])
check("旧 → 新", got, f"{OLD} → {NEW}")
check("确认后记下新版本", StateStore(state).get("versions", "maaend"), NEW)

print("[启动前 interface.json 还是旧版：以它为准，不被新进程的「当前版本」覆盖]")
got, _ = run_case("file", file_ver=OLD, prev_log=None, kept="",
                  logs=[("2026-09-07-2.log", POST_UPDATE_LOG)])
check("旧 → 新", got, f"{OLD} → {NEW}")

print("[本次启动先由旧进程自报版本，再重启成新进程]")
pre = f"2026-09-07 08:46:55 INFO  [App] 检查更新: MaaEnd, 当前版本: {OLD}, 频道: beta\n" \
      "2026-09-07 08:46:56 INFO  [App] 更新检查完成: MaaEnd, 有更新=true\n"
got, _ = run_case("launch", file_ver=NEW, prev_log=None, kept="",
                  logs=[("2026-09-07-1.log", pre), ("2026-09-07-2.log", POST_UPDATE_LOG)])
check("旧 → 新", got, f"{OLD} → {NEW}")

print("[什么都没有：明说没读到，不许只剩一个版本号]")
got, _ = run_case("none", file_ver=NEW, prev_log=None, kept="",
                  logs=[("2026-09-07-2.log", POST_UPDATE_LOG)])
check("明说", got, f"（旧版本没读到）→ {NEW}")

print("[没更新也要记版本，明天才有旧版号可用]")
done = f"2026-09-08 08:47:05 INFO  [App] 检查更新: MaaEnd, 当前版本: {NEW}, 频道: beta\n" \
       f"2026-09-08 08:47:06 INFO  [App] 更新检查完成: 最新版本={NEW}, 有更新=false\n"
got, state = run_case("nochange", file_ver=NEW, prev_log=None, kept="",
                      logs=[("2026-09-08-1.log", done)])
check("无更新不发通知", got, "")
check("但版本记下了", StateStore(state).get("versions", "maaend"), NEW)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
