"""deploy_watch.py: watching after a deploy restart until it has stayed up past the measured crash gap, and the way back.

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


def j(text, since, *, elapsed=120, total=120, pids=(4242,), states=("RUNNING",), events=(), mode="deploy", version="",
      cap=None):
    lines = dw.lines_since(text, datetime.strptime(since, "%Y-%m-%d %H:%M:%S"))
    kw = {} if cap is None else {"preupdate_cap": cap}
    return dw.judge(lines, pids=list(pids), states=list(states), events=list(events),
                    elapsed=elapsed, total=total, mode=mode, version=version, **kw)


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
check("没满实测崩溃间隔：继续盯", j(GOOD, "2026-10-10 16:05:29", elapsed=20)[0], "wait")
check("满了实测崩溃间隔、三项都齐：通过，不再干等两分钟", j(GOOD, "2026-10-10 16:05:29", elapsed=25)[0], "ok")
check("满两分钟：通过", j(GOOD, "2026-10-10 16:05:29")[0], "ok")
check("一行都没有：两分钟到了算失败", j("", "2026-10-10 16:05:29")[0], "fail")

print("\n[10-16 02:33 部署重启正好是当天第一次开机：预更新在跑，句柄要等它跑完才挂]")
# relay.log 10-16 02:33:29-02:35:07 as written (v20261015183310): boot, version, self-check all
# green, then the pre-update - AUTO-MAS really updated (72 s), OK-WW launched with its 45 s
# minimum - and no handle line yet. The 120 s watch failed here, the rollback's stop came
# while the pre-update could not hear it, and the 15 s hard exit fired (the 02:35 「主程序」 alarm).
PREUPDATE_1016 = r"""10-16 02:33:29 INFO    ark.service  服务模式启动，监视 D:\ark\automas\history（变更即处理，兜底 30 秒）
10-16 02:33:29 INFO    ark.service  中继代码版本 v20261015183310
10-16 02:33:30 INFO    ark.selfupdate  COS 上最新一次部署是 v20261015101332，本机 v20261015183310，已是最新，不再问 GitHub
10-16 02:33:30 INFO    ark.notify  不推送（日报或手机页已有）：🔄 中继已更新 ｜ 刚刚生效 版本 v20261015101332 → v20261015183310  - 中继读终末地（MaaEnd）任务说明文件变快了：这些文件九成以上本来就是标准格式，现在直接读，只有带注释的那几个才逐字清理。在 Mac 上量：以前每次开机要把 4.7 MB 逐字过五遍，约 1.5 秒白白耗在这上面，现在不到 0.2 秒。读出来的内容和以前一字不差，手机上看到的选项、写配置的校验都不变。  更
10-16 02:33:30 INFO    ark.service  更新说明已记入当天日报（v20261015183310）
10-16 02:33:33 INFO    ark.macpush  报警直送 Mac 没送到（URLError: <urlopen error [WinError 10061] 由于目标计算机积极拒绝，无法连接。>），13 条留着，下一条报警或下次开机再补
10-16 02:33:35 INFO    ark.service  上游导出代码核对：三处都和登记的一致
10-16 02:33:39 INFO    ark.phone  状态 44167 字节，压缩到 13023 字节
10-16 02:33:41 INFO    ark.service  📱 已上报状态到手机（开机；今天 ntfy 已用 148 条）
10-16 02:33:41 INFO    ark.machinecheck  上机核对 #10 过了：02:33:39 森空岛会话交给手机（6 项都在）；森空岛给的终末地体力：curStamina=134 maxStamina=360 maxTs=1792186851
10-16 02:33:43 INFO    ark.phone  📱 手机通道已连上（长连接，不轮询）
10-16 02:33:43 INFO    ark.phone  📱 ntfy 今天这个 IP 已用 148 条（中继自己发的 143 条）
10-16 02:33:46 INFO    ark.service  开机：终末地开游戏：开游戏助手的入口已指向 C:\Program Files\ArkRelay\versions\20261015183310
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 看得到机器上在跑哪些程序
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 读得到每个程序是怎么启动的（系统自带的那条路）
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 调度程序有应答
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 调度程序的后台程序在跑
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 调度程序的开机任务计划还在
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 调度程序还管着两个游戏客户端的更新（明日方舟、鸣潮）
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 队列的排期读得到、至少一条开着定时
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 中继要读的调度程序设置都在原处
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 日志文件所在目录能写
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 状态目录能写
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 调度程序的历史目录在
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 至少一条通知通道配好了
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 手机通道配好了
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 中继装了读图组件（读官方长图（卡池几点几分）、压缩报警截图）
10-16 02:33:46 INFO    ark.service  开机自检 14 项全部成立
10-16 02:33:46 INFO    ark.preupdate  预更新：AUTO-MAS 后端自报 v5.7.0-beta.3（res/version.json 还写着 v5.5.0-beta.2，新版不再改那个文件）
10-16 02:33:46 INFO    ark.preupdate  预更新：AUTO-MAS 有更新 v5.7.0-beta.3 → v5.7.0-beta.4，开始下载
10-16 02:34:10 INFO    ark.preupdate  预更新：更新包就绪（UpdatePack_v5.7.0-beta.4.zip），开始安装
10-16 02:34:58 INFO    ark.preupdate  预更新：AUTO-MAS 已更新到 v5.7.0-beta.4（后端重启后自报）
10-16 02:34:58 INFO    ark.service  调度程序升级到 v5.7.0-beta.4 后，中继要读的调度程序设置都在原处：成立
10-16 02:34:58 INFO    ark.notify  推送已送到：info 路，Server酱 收下 ｜ 🆕 预更新
10-16 02:35:02 INFO    ark.preupdate  预更新：中继服务没有拿控制台令牌的权限（这台机器上一直如此），直接用计划任务启动 ok-ww.exe
10-16 02:35:07 INFO    ark.preupdate  预更新：已通过计划任务在交互会话启动 ok-ww.exe
10-16 02:35:07 INFO    ark.preupdate  预更新：已启动 OK-WW（已临时关掉自动开游戏），最多 240 秒
"""
# Before anything imports ark_relay: once imported, a later root would read the cached module.
_bad = dw.preupdate_cap_s(ROOT / "no-such-dir")
check("读不到中继代码：上限 0，说清原因", (_bad[0], "ModuleNotFoundError" in _bad[1]), (0.0, True))
CAP, CAP_WHY = dw.preupdate_cap_s(ROOT / "relay")
sys.path.insert(0, str(ROOT / "relay"))
from ark_relay.features.preupdate import preupdate as _pre  # noqa: E402
check("预更新时长上限读的是中继自己的 worst_case_seconds()", (CAP, CAP_WHY), (_pre.worst_case_seconds(), ""))
check("上限比两分钟长得多（AUTO-MAS 下载 600 秒、OK-WW 240 秒都在里面）", CAP > 600 + 240, True)
S1016 = "2026-10-16 02:33:28"
v, why = j(PREUPDATE_1016, S1016, elapsed=125, total=120, cap=CAP)
check("(i) 只缺句柄、预更新在跑：两分钟过了继续等，不退回", v, "wait")
check("(i) 说明在等预更新", "预更新" in why, True)
check("没给上限（读不到中继代码）：照旧两分钟判失败", j(PREUPDATE_1016, S1016, elapsed=125, total=120)[0], "fail")
check("(ii) 预更新期间又重启：马上失败",
      j(PREUPDATE_1016 + PREUPDATE_1016.splitlines()[0] + "\n", S1016, elapsed=125, total=120, cap=CAP)[0], "fail")
check("预更新期间进程号变了：马上失败",
      j(PREUPDATE_1016, S1016, elapsed=125, total=120, cap=CAP, pids=(4242, 5120))[0], "fail")
check("预更新期间系统日志记下意外退出：马上失败",
      j(PREUPDATE_1016, S1016, elapsed=125, total=120, cap=CAP, events=("事件 7031（2026-10-15T18:34:00 UTC）",))[0], "fail")
red = PREUPDATE_1016.replace("INFO    ark.service  开机自检 ✓ 调度程序有应答",
                             "WARNING ark.service  开机自检 ✗ 调度程序有应答")
check("预更新在跑但自检有 ✗：马上失败", j(red, S1016, elapsed=30, total=120, cap=CAP)[0], "fail")
v, why = j(PREUPDATE_1016, S1016, elapsed=120 + CAP + 1, total=120, cap=CAP)
check("(iii) 超过预更新最长时长还没句柄：失败", v, "fail")
check("(iii) 说清超过了预更新最长时长", "预更新最长" in why and "已挂上 AUTO-MAS 进程句柄" in why, True)
no_selfcheck = "\n".join(ln for ln in PREUPDATE_1016.splitlines() if "全部成立" not in ln)
check("还缺「全部成立」时不因预更新多等", j(no_selfcheck, S1016, elapsed=125, total=120, cap=CAP)[0], "fail")
check("句柄挂上了：通过", j(PREUPDATE_1016 + "10-16 02:37:08 INFO    ark.service  已挂上 AUTO-MAS 进程句柄，它一退出立即拉起\n",
                          S1016, elapsed=220, total=120, cap=CAP)[0], "ok")
check("没给代码目录：上限 0", dw.preupdate_cap_s(None), (0.0, "没给中继代码目录"))

got = []
real_watch = dw.watch
dw.watch = lambda *a: got.append(a) or 0
try:
    dw.main(["deploy_watch.py", "watch", "relay.log", S1016, "120", "deploy", "--pkg", "--root", "C:\\A B\\versions\\9"])
finally:
    dw.watch, dw.PKG = real_watch, False
check("--root 传到 watch，其余参数位置不变", got, [("relay.log", S1016, 120.0, "deploy", "", "C:\\A B\\versions\\9")])
pkg_sh = (ROOT / "scripts/mac/lib/deploy-pkg.sh").read_text(encoding="utf-8")
check("安装版部署把刚起来的版本文件夹交给盯梢", '"$WATCH_S" deploy --pkg \\\n      --root "$APP_WIN\\\\versions\\\\$NEW"' in pkg_sh, True)
check("老服务部署也交代码目录", "$WATCH_S deploy --root ${REMOTE_DIR" in (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8"), True)

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
print("[deploy-relay.sh sets WATCH_S before the installed-relay steps read it]")
# 10-11 13:24: lib/deploy-pkg.sh used WATCH_S, set only further down for the old layout;
# under `set -u` the deploy died right after the restart, so no watch and no COS.
_sh = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
check("WATCH_S default comes before lib/deploy-pkg.sh is sourced",
      0 <= _sh.find('WATCH_S="${WATCH_S:-') < _sh.find('lib/deploy-pkg.sh"'), True)

if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
