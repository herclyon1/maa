"""deploy_watch.py: two minutes of watching after a deploy restart, and the way back.

2026-10-10 16:27 v20261010082756 crashed a few seconds after every start (17
restarts in five minutes) while deploy-relay.sh printed green; from 16:14 the
boot self-check had been red and the keeper had no handle on AUTO-MAS, also
unnoticed by the deploy. The log lines below are relay.log of that afternoon.
"""
import importlib.util
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("deploy_watch", ROOT / "scripts/windows/deploy_watch.py")
dw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dw)

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


CRASH_LOOP = """10-10 16:27:59 INFO    ark.service  系统的程序启动通知已取消订阅（用了 0.0 秒），中继停下时不留订阅
10-10 16:28:03 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）
10-10 16:28:03 INFO    ark.service  中继代码版本 v20261010082756
10-10 16:28:12 INFO    ark.service  📱 已上报状态到手机（开机；今天 ntfy 已用 44 条）
10-10 16:28:14 INFO    ark.phone  📱 ntfy 今天这个 IP 已用 44 条（中继自己发的 43 条）
10-10 16:28:21 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）
10-10 16:28:21 INFO    ark.service  中继代码版本 v20261010082756
"""

SELFCHECK_RED = """10-10 16:33:03 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）
10-10 16:33:03 INFO    ark.service  中继代码版本 v20261010083249
10-10 16:33:17 INFO    ark.service  开机自检 ✓ 看得到机器上在跑哪些程序
10-10 16:33:17 WARNING ark.service  开机自检 ✗ 读得到每个程序是怎么启动的（系统自带的那条路）：读不到——看门狗只能靠调度程序有没有应答来判断，它退出时不会立刻察觉
10-10 16:33:17 INFO    ark.service  开机自检 ✓ 调度程序有应答
10-10 16:33:19 INFO    ark.service  已订阅进程启动事件（WMI 内核 trace），AUTO-MAS 一启动立即挂句柄
"""

GOOD = """10-10 16:05:30 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）
10-10 16:05:30 INFO    ark.service  中继代码版本 v20261010080447
10-10 16:05:44 INFO    ark.service  开机自检 12 项全部成立
10-10 16:05:46 INFO    ark.service  已订阅进程启动事件（WMI 内核 trace），AUTO-MAS 一启动立即挂句柄
10-10 16:05:46 INFO    ark.service  已挂上 AUTO-MAS 进程句柄，它一退出立即拉起
"""


def j(text, since, *, elapsed=120, total=120, pids=(4242,), states=("RUNNING",), events=(), mode="deploy", version=""):
    lines = dw.lines_since(text, datetime.strptime(since, "%Y-%m-%d %H:%M:%S"))
    return dw.judge(lines, pids=list(pids), states=list(states), events=list(events),
                    elapsed=elapsed, total=total, mode=mode, version=version)


print("[16:28 那一版：启动几秒就崩、又起来]")
v, why = j(CRASH_LOOP, "2026-10-10 16:28:02", elapsed=20)
check("不等满两分钟就判失败", v, "fail")
check("说是重启了", "又重启" in why)
check("上一个进程停下前的行不算", j(CRASH_LOOP, "2026-10-10 16:28:02", elapsed=10)[0], "fail")
check("只看到第一次启动时还在等", j(CRASH_LOOP.split("10-10 16:28:21")[0], "2026-10-10 16:28:02", elapsed=10)[0], "wait")
check("进程号变了也算重启", j(GOOD, "2026-10-10 16:05:29", elapsed=30, pids=(4242, 4242, 5120))[0], "fail")
check("系统日志 7031 也算", j(GOOD, "2026-10-10 16:05:29", elapsed=30, events=("事件 7031（2026-10-10T07:05:50 UTC）",))[0], "fail")
unread = j(GOOD, "2026-10-10 16:05:29", events=("系统日志读不到（OSError），判不了中继有没有意外退出",))
check("系统日志读不到：判失败，不当没崩", unread, ("fail", "系统日志读不到（OSError），判不了中继有没有意外退出"))
check("服务停了算", j(GOOD, "2026-10-10 16:05:29", elapsed=30, states=("RUNNING", "STOPPED"))[0], "fail")

print("\n[16:33 那一版：起来了，但自检有 ✗、没挂上句柄]")
v, why = j(SELFCHECK_RED, "2026-10-10 16:33:02", elapsed=20)
check("自检一出 ✗ 就判失败", v, "fail")
check("说出是哪一项", why.startswith("开机自检有项不成立：读得到每个程序是怎么启动的"))
v, why = j(SELFCHECK_RED.replace("WARNING ark.service  开机自检 ✗", "INFO    ark.service  开机自检 ✓"),
           "2026-10-10 16:33:02")
check("没有 ✗、但两分钟内没等到「全部成立」和句柄：失败", v, "fail")
check("说缺哪两行", "全部成立" in why and "已挂上 AUTO-MAS 进程句柄" in why)

print("\n[正常的一次：两分钟里一次启动、自检全过、挂上句柄]")
check("还没满两分钟：继续盯", j(GOOD, "2026-10-10 16:05:29", elapsed=40)[0], "wait")
check("满两分钟：通过", j(GOOD, "2026-10-10 16:05:29")[0], "ok")
check("一行都没有：两分钟到了算失败", j("", "2026-10-10 16:05:29")[0], "fail")

print("\n[退回之后：一次启动、版本是上一版]")
check("版本对：通过", j(GOOD, "2026-10-10 16:05:29", total=60, mode="rollback", version="v20261010080447")[0], "ok")
check("状态表里的版本号不带 v、日志里带 v：算对上（10-10 演练）",
      j(GOOD, "2026-10-10 16:05:29", total=60, mode="rollback", version="20261010080447")[0], "ok")
check("版本不对：失败", j(GOOD, "2026-10-10 16:05:29", total=60, mode="rollback", version="v20261010083249")[0], "fail")
check("退回后又重启：失败", j(CRASH_LOOP, "2026-10-10 16:28:02", elapsed=20, total=60, mode="rollback",
                          version="v20261010082756")[0], "fail")

print("\n[存一份、放回去]")
with tempfile.TemporaryDirectory() as td:
    root, backup = Path(td) / "ark-relay", Path(td) / "prev"
    (root / "ark_relay" / "__pycache__").mkdir(parents=True)
    (root / "ark_relay" / "core").mkdir()
    (root / "ark_relay" / "core" / "procs.py").write_text("old procs", encoding="utf-8")
    (root / "service.py").write_text("old service", encoding="utf-8")
    (root / "ark_relay" / "__pycache__" / "procs.cpython-314.pyc").write_bytes(b"x")
    (root / ".env").write_text("secret", encoding="utf-8")
    info = dw.snapshot(root, backup, ["ark_relay/core/procs.py", "service.py", "ark_relay/brand_new.py"], "v1")
    check("存下两份旧文件、记下一份新文件", (sorted(info["kept"]), info["new"]),
          (["ark_relay/core/procs.py", "service.py"], ["ark_relay/brand_new.py"]))
    (root / "ark_relay" / "core" / "procs.py").write_text("new procs", encoding="utf-8")
    (root / "service.py").write_text("crashing service", encoding="utf-8")
    (root / "ark_relay" / "brand_new.py").write_text("new file", encoding="utf-8")
    info = dw.restore(root, backup)
    check("旧文件放回", ((root / "ark_relay" / "core" / "procs.py").read_text(encoding="utf-8"),
                       (root / "service.py").read_text(encoding="utf-8")), ("old procs", "old service"))
    check("新加的文件删掉", (root / "ark_relay" / "brand_new.py").exists(), False)
    check("旧的 .pyc 清掉", (root / "ark_relay" / "__pycache__").exists(), False)
    check("没碰别的文件", (root / ".env").read_text(encoding="utf-8"), "secret")
    check("记得上一版的版本号", info["code_version"], "v1")
    dw.snapshot(root, backup, ["service.py"], "v2")
    check("再存一次是新的一份，不叠旧的", sorted(p.name for p in (backup / "files").rglob("*") if p.is_file()), ["service.py"])

print("\n[部署脚本的顺序：先存再推；盯完才发 COS、才说部署完成；失败退回]")
sh = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
pos = {k: sh.find(k) for k in ("snapshot ${REMOTE_DIR", "tar --no-mac-metadata -czf - $CHANGED", "\nrestart_service\n",
                                "$WATCH_S deploy", "publish-cos.py\"", "echo \"✅ 部署完成", "restore ${REMOTE_DIR", "\n    exit 12", "\n  exit 13")}
check("每一段都在", [k for k, v in pos.items() if v < 0], [])
check("存档在推文件之前", pos["snapshot ${REMOTE_DIR"] < pos["tar --no-mac-metadata -czf - $CHANGED"])
check("盯梢在重启之后、发 COS 之前", pos["\nrestart_service\n"] < pos["$WATCH_S deploy"] < pos["publish-cos.py\""])
check("盯梢在「部署完成」之前", pos["$WATCH_S deploy"] < pos["echo \"✅ 部署完成"])
check("没稳住就退回，退回后报失败", pos["$WATCH_S deploy"] < pos["restore ${REMOTE_DIR"] < pos["\n    exit 12"] < pos["\n  exit 13"])
check("默认盯 120 秒", 'WATCH_S="${WATCH_S:-120}"' in sh)

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
