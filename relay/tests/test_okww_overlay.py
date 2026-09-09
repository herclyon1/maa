"""Ark's OK-WW changes live in OK-WW's own extension point, not in its source.

ok-script executes every .py under `<working>/ok_tasks/` at startup, so our changes
can rebind methods on upstream's classes without a single upstream file being
edited. That removes the whole family of failures the text patches kept producing:
half-applied, applied twice, or reverted to the wrong previous version - all silent.

What must not become silent in exchange: an override that did not take because
upstream renamed the method. The file writes a report; this pins that the relay
reads it and says so.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import okww_overlay
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


print("[装到 OK-WW 自己的扩展目录里，不碰它的源文件]")
root = tmpdir()
dest = okww_overlay.target(root)
check("路径在 ok_tasks 下", dest.parent.name, "ok_tasks")
check("装之前没有", dest.is_file(), False)
line = okww_overlay.install(root)
check("装上了", dest.is_file())
check("说了装到哪", "ok_tasks" in line)
check("内容一字不差", dest.read_text(encoding="utf-8"), okww_overlay.source_text())
check("再装一次什么都不做", okww_overlay.install(root), "")
check("目录是 None 时直说", "找不到" in okww_overlay.install(None))

print("[没有目录也要自己建，不能因为缺个文件夹就装不上]")
root2 = tmpdir()
okww_overlay.install(root2)
check("建好了目录并写进去", okww_overlay.target(root2).is_file())

print("[ok-script 只执行「文件里有类」的 .py，所以那个类必须在]")
src = okww_overlay.source_text()
check("文件里有顶层类", "\nclass " in src)
check("重绑之前先检查方法还在不在", "上游没有这个方法了" in src)
check("抄整段的要比对上游正文", "expect_sha" in src)
# 2026-09-09 pilot: the tacet teleport's team screen arrived just after upstream's
# 10-second wait ran out. 19 runs across five days had already died there.
check("传送界面等不到时会多等一次", "多等 15 秒" in src)
check("多等那次不许自己抛，找不到才抛", "raise_if_not_found=False" in src)
# 2026-09-09, the user asked the right question: if we replace a method outright and
# upstream later changes theirs, we would never know. Only a pin catches that, so
# every whole-method replacement must carry one.
whole = [l for l in src.splitlines() if "@override(" in l]
pinned = [l for l in whole if "expect_sha=" in l]
check("整段替换的都钉住了上游哈希", len(pinned) >= 1)
# revive_action stopped being a replacement on 2026-09-09: only the case upstream
# refuses (inside a realm) is ours now, and their body still runs for the rest.
check("被替换的是那两个小方法", any("click_team_challenge" in l or "find_nest" in l
                                    for l in pinned))

print("[没贴上必须报出来，不许闷着]")
real = okww_overlay.REPORT
try:
    okww_overlay.REPORT = tmpdir() / "report.json"
    check("没有报告时不说话", okww_overlay.report_line(), "")
    okww_overlay.REPORT.write_text(json.dumps({"applied": ["A.b"], "skipped": []}),
                                   encoding="utf-8")
    check("全贴上了也不说话", okww_overlay.report_line(), "")
    okww_overlay.REPORT.write_text(json.dumps(
        {"applied": [], "skipped": [{"what": "FarmEchoTask.revive_action",
                                     "why": "上游没有这个方法了（改名或删了）"}]}),
        encoding="utf-8")
    line = okww_overlay.report_line()
    check("点名是哪一条没贴上", "revive_action" in line)
    check("说了为什么", "改名" in line)
    okww_overlay.REPORT.write_text(json.dumps({"error": "Traceback ... ImportError"}),
                                   encoding="utf-8")
    check("整个文件炸了也要说", "一条都没生效" in okww_overlay.report_line())
finally:
    okww_overlay.REPORT = real

print("[闸门本身：拿坏样本喂它，必须拦住]")
# The gate is the whole reason this is safer than editing upstream's files. A gate
# that does not fire is worse than none, so it is fed known-bad input here.
ns = {}
exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
ns["_applied"].clear()
ns["_skipped"].clear()


class Upstream:
    def still_here(self):
        return "上游的"


@ns["override"](Upstream, "still_here")
def _mine(self):
    return "我们的"


check("方法在就换掉", Upstream().still_here(), "我们的")
check("记到已贴上里", ns["_applied"], ["Upstream.still_here"])

ns["_applied"].clear()
ns["_skipped"].clear()


@ns["override"](Upstream, "上游改名之后就没有的方法")
def _orphan(self):
    return "不该生效"


check("上游没这个方法就不贴", ns["_applied"], [])
check("而且要记下来", len(ns["_skipped"]), 1)
check("说清了原因", "上游没有这个方法了" in ns["_skipped"][0]["why"])

ns["_applied"].clear()
ns["_skipped"].clear()


@ns["override"](Upstream, "still_here", expect_sha="0123456789ab")
def _stale(self):
    return "照着旧正文抄的"


check("上游正文变了就不贴", ns["_applied"], [])
check("并且说明是正文对不上", "正文变了" in ns["_skipped"][0]["why"])
check("原来那份没被换掉", Upstream().still_here(), "我们的")

real_sha = ns["_src_sha"](Upstream.still_here)
ns["_applied"].clear()
ns["_skipped"].clear()


@ns["override"](Upstream, "still_here", expect_sha=real_sha)
def _fresh(self):
    return "对得上就贴"


check("正文对得上就照贴", Upstream().still_here(), "对得上就贴")
check("没有被跳过的", ns["_skipped"], [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
