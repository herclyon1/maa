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

print("\n[体力读数：数/数 没读到是「没读到」，不是 0]")
parse = ns["_parse_stamina"]
# The strip as OCR reads it on the 2026-09-21 screenshots (10-20-43.029 and two more):
check("09-21 截图原样", parse(["55", "240/240", "+"]), (240, 55))
check("240/240 拆成两块也拼得回", parse(["55", "240", "/240"]), (240, 55))
check("拆成三块也拼得回", parse(["55", "240", "/", "240"]), (240, 55))
check("备用只取数/数左边那块，右边的数不覆盖", parse(["55", "240/240", "120"]), (240, 55))
check("左边不是纯数字就没有备用", parse(["+", "120/240"]), (120, 0))
check("一块数/数都拼不出来 = 没读到（上游这里当 0）", parse(["240", "55"]), None)
check("什么都没读到", parse([]), None)
check("真读到 0/240 就是 0", parse(["0/240"]), (0, 0))


class _Box:
    def __init__(self, name, x=0, y=0, width=10, height=10):
        self.name, self.x, self.y, self.width, self.height = name, x, y, width, height

    def __str__(self):
        return f"Box(name='{self.name}')"


class FakeTask:
    """Plays back a script of screens; records what the override does."""

    def __init__(self, frames, start_after=None, strip=None):
        self.frames, self.start_after, self.strip = frames, start_after, strip or []
        self.clicks, self.logs, self.shots, self.slept = [], [], [], 0

    def wait_feature(self, name, **kw):
        return self.start_after is not None and len(self.clicks) >= self.start_after

    def box_of_screen(self, *xy):
        return xy

    def ocr(self, box=None):
        return self.frames(box)

    def wait_ocr(self, *box, **kw):
        return self.strip.pop(0) if self.strip else []

    def click_box(self, b, after_sleep=0):
        self.clicks.append((b.x + b.width // 2, b.y + b.height // 2))

    def screenshot(self, name):
        self.shots.append(name)

    def log_info(self, msg):
        self.logs.append(msg)

    def sleep(self, s):
        self.slept += s


solo_btn = _Box("单人挑战", 1474, 965, 124, 36)
still_solo = lambda box: [solo_btn]  # noqa: E731
confirm = ns["_confirm_solo"]
t = FakeTask(still_solo, start_after=0)
check("开启挑战已经在：一下都不补", (confirm(t), t.clicks), (0, []))
t = FakeTask(still_solo, start_after=1)
check("09-21 那种：仍是单人挑战就点它读到的位置", (confirm(t), t.clicks), (1, [(1536, 983)]))
check("补点前截图", t.shots, ["solo_retry_1"])
check("补点写日志", any("补点第 1 次 (1536,983)" in m for m in t.logs), True)
t = FakeTask(still_solo)
check("最多补 3 次", (confirm(t), len(t.clicks)), (3, 3))
check("3 次都没进要说", any("3 次都没进开启挑战" in m for m in t.logs), True)
t = FakeTask(lambda box: [_Box("结晶波片不足，无法获取奖励")])
check("波片不足弹窗不补点，交给原来那段", (confirm(t), t.clicks), (0, []))
t = FakeTask(lambda box: [_Box("别的画面")] if box == (0.0, 0.0, 1.0, 1.0) else [])
check("屏上没有单人挑战不乱点", (confirm(t), t.clicks), (0, []))

read = ns["_read_stamina"]
t = FakeTask(None, strip=[[_Box("55", 1351), _Box("/240", 1600), _Box("240", 1551)]])
check("按横坐标排好再拼", read(t, False), (240, 55))
check("读字原文进日志", any("['55', '240', '/240']" in m for m in t.logs), True)
t = FakeTask(None, strip=[[_Box("240")], [_Box("55"), _Box("240/240", 5)]])
check("领奖框没读到隔 1 秒再读", (read(t, True), t.slept), ((240, 55), 1))
t = FakeTask(None, strip=[[_Box("240")]])
check("F2 书页只读一次，没读到交回上游（-1 分支）", (read(t, False), t.slept), (None, 0))
t = FakeTask(None, strip=[])
check("领奖框读 5 次都没有就算没读到", (read(t, True), t.slept, t.shots), (None, 4, ["stamina_error"]))

print("\n[母本指路文件：改动文件靠它读「只刷落渊南丘」]")
# ok-script rewrites configs/ at load and drops the key (09-10..09-13 farmed all
# four nests), so the value is only ever readable from AUTO-MAS's master.
automas = tmpdir()
mdir = automas / "data" / "c5e9-okww" / "Default" / "ConfigFile"
mdir.mkdir(parents=True)
(mdir / "DailyTask.json").write_text("{}", encoding="utf-8")
pointer = tmpdir() / "ark-okww-master.txt"
okww_overlay.MASTER_POINTER = pointer
check("母本找不到就说清楚", "找不到" in okww_overlay.write_master_pointer(tmpdir()))
check("写好了不吭声", okww_overlay.write_master_pointer(automas), "")
check("指向母本目录", pointer.read_text(encoding="utf-8"), str(mdir))
check("已是这个值就不重写", okww_overlay.write_master_pointer(automas), "")
check("改动文件里读的是同一个路径", 'r"C:\\ProgramData\\ark-okww-master.txt"' in okww_overlay.source_text())

print("\n[最新一趟 OK-WW 日志：按修改时间取最新，一周内]")
from ark_relay import outcome  # noqa: E402
hist = tmpdir()
check("没有历史目录", outcome.latest_okww_run_log(hist / "nope"), None)
check("目录空着", outcome.latest_okww_run_log(hist), None)
d1 = hist / "2026-09-12" / "wuwa"; d1.mkdir(parents=True)
d2 = hist / "2026-09-13" / "wuwa"; d2.mkdir(parents=True)
(d1 / "OK-WW-05-20-09.log").write_text("old\n", encoding="utf-8")
(d2 / "OK-WW-05-19-22.log").write_text("new NightmareNestTask\n", encoding="utf-8")
import os as _os  # noqa: E402
import time as _time  # noqa: E402
_os.utime(d1 / "OK-WW-05-20-09.log", (_time.time() - 86400, _time.time() - 86400))
got = outcome.latest_okww_run_log(hist)
check("取到最新那趟", got[0].name if got else None, "OK-WW-05-19-22.log")
check("连正文一起给", got[1] if got else None, "new NightmareNestTask\n")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
