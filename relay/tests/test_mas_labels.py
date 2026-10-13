"""AUTO-MAS field labels: every labelled ConfigItem is read (audit 11 #4, 2026-10-13).

mas_labels matched `## 中文名` + `self.X = ConfigItem(` lazily up to a `\n)`. A
one-line ConfigItem(...) has no such line of its own, so the match swallowed
the next field and its label went to the wrong key or nowhere; the MaaEnd
sanity-task fields are declared as `config.X = ConfigItem` in the module-level
init_maaend_task_config(config), which MaaEndUserConfig calls with itself, and
were not read at all. Of the 19 SHOWN fields 7 had no label.

The fixture is the AUTO-MAS app/models/config.py audit 11 ran on (copied
2026-10-12, unchanged; fixtures/automas-models/config.py.txt). Of the 7, Task.TaskIndex (OK-WW) carries only a `#`
comment and Task.IfSanity / Task.IfAutoUseSpMedication are no ConfigItem in
this file (only schema.py Field descriptions): no `##` label exists for them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay.features.phone import mas_labels

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        fails.append(label)


# Kept as .txt so the repo's Python tools (ruff, the comment ratchet) do not read
# upstream code as ours; laid out as AUTO-MAS's app/models for the run.
SRC = Path(__file__).resolve().parent / "fixtures" / "automas-models" / "config.py.txt"
AM = tmpdir()
(AM / "app" / "models").mkdir(parents=True)
(AM / "app" / "models" / "config.py").write_bytes(SRC.read_bytes())
out = mas_labels._mas_labels(AM)


def label(game, path):
    return (out[game].get(path) or {}).get("label")


print("[the AUTO-MAS source audit 11 ran on]")
check("MAA Info.MedicineNumb (one-line ConfigItem before it)", label("MAA", "Info.MedicineNumb"), "理智药数量")
check("MAA Task.IfFight (one-line ConfigItem)", label("MAA", "Task.IfFight"), "是否理智作战")
check("MAA Task.IfStartUp keeps its own label (not swallowed)", label("MAA", "Task.IfStartUp"), "是否自动唤醒")
check("MAA Info.Notes (one line) keeps its own label", label("MAA", "Info.Notes"), "备注")
check("MaaEnd Task.SanityTaskType (config. in init_maaend_task_config)",
      label("MaaEnd", "Task.SanityTaskType"), "理智任务类型")
check("MaaEnd Task.AutoEssenceSpecifiedLocation", label("MaaEnd", "Task.AutoEssenceSpecifiedLocation"), "基质刷取地点")
check("multi-line items still read: MAA Info.Annihilation options",
      (label("MAA", "Info.Annihilation"), (out["MAA"].get("Info.Annihilation") or {}).get("options", [])[:2]),
      ("剿灭模式", ["Close", "Annihilation"]))
check("OK-WW Task.WhichToFarm", label("OK-WW", "Task.WhichToFarm"), "每日任务体力用途")
shown = sorted(f"{g}|{p}" for g in out for p in mas_labels.SHOWN if p in out[g])
check("SHOWN fields labelled: 16 of 19 (TaskIndex, IfSanity, IfAutoUseSpMedication have none)", len(shown), 16)
# No label may land on a field other than its own: each `##` line is the line
# right above its ConfigItem in the source.
src = SRC.read_text(encoding="utf-8")
wrong = [f"{g}|{p}" for g, items in out.items() for p, info in items.items()
         if f'## {info["label"]}\n' not in src]
check("every label is a `## ` line of the source", wrong, [])

print("\n[a wrapped one-line call and a comment with a parenthesis]")
d = tmpdir()
(d / "app" / "models").mkdir(parents=True)
(d / "app" / "models" / "config.py").write_text('''
def init_x(config) -> None:
    ## 甲
    config.Task_A = ConfigItem("Task", "A", 0)  # a (comment
    ## 乙
    config.Task_B = ConfigItem(
        "Task",
        "B",
        "x)",  # a ) in a string and a comment
        OptionsValidator(["p", "q"]),
    )


class MaaEndUserConfig(ConfigBase):
    def __init__(self):
        ## 丙
        self.Info_C = ConfigItem("Info", "C", f(1, 2))
        ## 丁
        self.Info_D = ConfigItem("Info", "D", 1)
        init_x(self)
''', encoding="utf-8")
got = mas_labels._mas_labels(d)["MaaEnd"]
check("labels", {k: v["label"] for k, v in got.items()},
      {"Info.C": "丙", "Info.D": "丁", "Task.A": "甲", "Task.B": "乙"})
check("options inside a wrapped call", got.get("Task.B", {}).get("options"), ["p", "q"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
