"""Before the run, the relay knows whether OK-WW's update broke a pinned copy.

10-03 OK-WW went to v3.7.3 and changed find_nest. Nothing looked until the morning
run's result check, which pushed 「这一轮没干完」 to the group on 10-04 and 10-05.
okww_overlay.drift() reads the source on disk after the pre-update (and at boot) and
hashes each pinned method the way the overrides do (inspect.getsource), so the
mismatch is a line at boot, said once - not an alarm after the run.
"""
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


V373 = (Path(__file__).resolve().parent / "fixtures"
        / "okww-NightmareNestTask-v3.7.3.py.txt").read_text(encoding="utf-8")
# v3.7.2's find_nest differs from v3.7.3's in the box top only (diff of the two releases).
V372 = V373.replace("counts = self.ocr(0.35, 0.25, 1, 0.96, match=self.count_re)",
                    "counts = self.ocr(0.35, 0.13, 1, 0.96, match=self.count_re)")


def okww(nest_text, extra=None):
    root = tmpdir()
    src = root.joinpath(*okww_overlay._SRC)
    src.mkdir(parents=True)
    # Windows line ends, as on the machine: the hash must not depend on them.
    (src / "NightmareNestTask.py").write_bytes(nest_text.replace("\n", "\r\n").encode("utf-8"))
    for name, text in (extra or {}).items():
        (src / name).write_text(text, encoding="utf-8")
    return root


print("\n[钉住的三处都从覆盖文件里读出来]")
got = {f"{c}.{m}": (sha, a) for c, m, sha, a in okww_overlay.pins()}
check("find_nest 钉 v3.7.3，且会适配", got.get("NightmareNestTask.find_nest"), ("12d040afa102", True))
check("周本开启挑战钉住，不适配", got.get("FarmEchoTask.click_team_challenge", ("", None))[1], False)
check("体力读数钉住", "BaseWWTask.get_stamina" in got)

print("\n[v3.7.3 在盘上：对得上，不出声]")
check("没有对不上的", okww_overlay.drift(okww(V373)), [])
check("一句话都不说", okww_overlay.drift_line(okww(V373), tmpdir()), "")

print("\n[盘上是旧版（或下一版）：开跑前就说，且只说一次]")
d = okww_overlay.drift(okww(V372))
check("找出 find_nest", [x["what"] for x in d], ["NightmareNestTask.find_nest"])
check("算出来的就是旧版哈希", d[0]["got"] if d else "", "3b0271924cac")
state = tmpdir()
line = okww_overlay.drift_line(okww(V372), state)
check("说了对不上", "和新版对不上" in line)
check("说了会适配", "按新版适配" in line)
check("同一处第二次开机不再说", okww_overlay.drift_line(okww(V372), state), "")

print("\n[方法在父类里：顺着父类找]")
base = "class BaseWWTask:\n    def get_stamina(self):\n        return 1\n"
child = "from x import BaseWWTask\n\n\nclass FarmEchoTask(BaseWWTask):\n    def other(self):\n        pass\n"
classes = okww_overlay._classes(okww(V373, {"BaseWWTask.py": base, "FarmEchoTask.py": child}).joinpath(*okww_overlay._SRC))
check("子类没有就找到父类的", okww_overlay._method_sha(classes, "FarmEchoTask", "get_stamina")
      == okww_overlay._method_sha(classes, "BaseWWTask", "get_stamina") != "")

print("\n[读不出来的不算对不上]")
check("文件不在就不报", okww_overlay.drift(tmpdir()), [])
check("没给目录也不报", okww_overlay.drift(None), [])

print("\n[运行时报告里的「已适配」也说成人话]")
okww_overlay.REPORT = tmpdir() / "r.json"
okww_overlay.REPORT.write_text('{"applied": [], "skipped": [], "adapted": [{"what": "NightmareNestTask.find_nest", "why": "x"}], "error": ""}', encoding="utf-8")
check("说了已按新版适配", "已按新版适配：NightmareNestTask.find_nest" in okww_overlay.report_line())

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
