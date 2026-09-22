"""M6 (2026-09-23): run counts and sanity spent against the real 09-20..22 logs.

* MAA: a drop block line with no "(+N)" ("酯原料 : 2") ended the block, so the
  "当前次数" after it was lost - 1-7 farmed 19 times was reported x10.
  The count now comes from MAA's own "开始行动 a~b 次" numbering.
* MaaEnd: five runs read 237/158/78/38/38/39; median step 79 gave "395"
  for 5 x 80 = 400.
"""
import sys, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay import collector_maa, collector_maaend

fails = []

def chk(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")

# history/2026-09-20/arknights/MAA-05-00-01.log lines 86-114 (report headers dropped)
maa = """[2026-09-20 09:02:43.459][INF][TaskQueueViewModel]     <2> 开始行动 1~10 次, -60理智
理智: 117/210
[2026-09-20 09:04:10.692][INF][TaskQueueViewModel]     <2> 1-7 掉落统计: 
龙门币 : 720 (+720)
固源岩 : 14 (+14)
基础作战记录 : 13 (+13)
酯原料 : 2 (+2)
破损装置 : 2 (+2)
当前次数 : 10
[2026-09-20 09:04:26.536][INF][TaskQueueViewModel]     <2> 开始行动 11~19 次, -54理智
理智: 57/210
[2026-09-20 09:05:53.031][INF][TaskQueueViewModel]     <2> 1-7 掉落统计: 
龙门币 : 1368 (+648)
基础作战记录 : 26 (+13)
固源岩 : 23 (+9)
破损装置 : 3 (+1)
双酮 : 1 (+1)
赤金 : 1 (+1)
酯原料 : 2
当前次数 : 9
[2026-09-20 09:06:15.563][INF][TaskQueueViewModel]     <2> 完成任务: 理智作战
"""
with tempfile.TemporaryDirectory() as d:
    f = pathlib.Path(d) / "maa.log"
    f.write_text(maa, encoding="utf-8")
    r = collector_maa.parse_maa_log(f)
    chk("方舟 09-20 早 次数", r.get("run_times"), 19)
    chk("方舟 09-20 早 理智", r.get("sanity_spent"), 114)
    chk("方舟 09-20 早 酯原料", r.get("drop_statistics", {}).get("酯原料"), 2)
    chk("方舟 09-20 早 龙门币", r.get("drop_statistics", {}).get("龙门币"), 1368)
    # "开始行动 21 次" (single run) counts too - 09-20 21:36:28
    f.write_text(maa + "[2026-09-20 21:36:28.217][INF][TaskQueueViewModel]     <2> 开始行动 20~21 次, -12理智\n", encoding="utf-8")
    chk("方舟 单趟编号", collector_maa.parse_maa_log(f).get("run_times"), 21)

end = "\n".join([
    "[2026-09-22 09:47:29.620] 任务开始: 🎱基质刷取",
    *[f"[2026-09-22 09:4{i}:00.000] 当前理智 {v}/360" for i, v in enumerate([237, 158, 78, 38, 38, 39])],
    *["[2026-09-22 09:50:42.245] ✅已完成一次基质刷取"] * 5,
    "[2026-09-22 09:58:39.769] 任务完成: 🎱基质刷取",
])
chk("终末地 09-22 理智", collector_maaend._maaend_farm(end).get("maaend_sanity_spent"), 400)

if fails:
    print("\n".join(fails)); sys.exit(1)
print("all checks passed")
