"""日报里鸣潮刷的本和产出必须是人话，不许只有序号或一句笼统的类别。

用户 2026-09-06 看到「刷 无音区 #2 ×2 / 产出 声骸与角色突破材料」：
「井号二是什么玩意儿？产出也是一坨屎」。08-26 凝素领域那一支已经改成写名字，
无音区这一支当时漏了。这条测试把两支一起钉死，以后再加第三种本也得过它。
"""
import pathlib
import re
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay import collector, wuwa_tacet  # noqa: E402

fails = []
BAD = re.compile(r"#\s*\d|声骸与角色突破材料|武器突破材料$|副本奖励")

def run(log_text):
    p = pathlib.Path(tempfile.mkdtemp()) / "x.log"
    p.write_text(log_text, encoding="utf-8")
    return collector.parse_okww_log(p)

# 无音区：已登记的序号要写名字和两个套装
raw = run("2026-09-05 09:20:00,000 INFO TacetTask: start\n"
          "2026-09-05 09:20:01,000 INFO info_set Teleport to Tacet Suppression 1\n"
          "2026-09-05 09:21:00,000 INFO 使用双倍体力\n")
farm, rew = raw.get("okww_farm", ""), raw.get("okww_farm_reward", "")
if "玄幽东岳" not in farm:
    fails.append(f"无音区 2 号应写玄幽东岳，得到 {farm!r}")
if not ("羽落空尘之歌" in rew and "清邪荡煞之心" in rew):
    fails.append(f"产出应写两个套装名，得到 {rew!r}")
for s in (farm, rew):
    if BAD.search(s):
        fails.append(f"还是笼统写法：{s!r}")

# 没登记的序号：明说没登记，不许编名字
farm2, rew2 = wuwa_tacet.label(17), wuwa_tacet.reward(17)
if "没登记" not in farm2 or "没登记" not in rew2:
    fails.append(f"未登记序号要明说：{farm2!r} / {rew2!r}")

# 凝素领域那一支同样不许退化回序号
raw3 = run("2026-09-05 09:20:00,000 INFO ForgeryTask: start\n"
           "2026-09-05 09:20:01,000 INFO info_set Teleport to Forgery Challenge 0\n"
           "2026-09-05 09:21:00,000 INFO 使用双倍体力\n")
if "陨翼云渊" not in raw3.get("okww_farm", ""):
    fails.append(f"凝素领域应写副本名，得到 {raw3.get('okww_farm')!r}")

# 表和手机页同源：app.js 里 TACET 的每一行都要和这里一致
js = (pathlib.Path(__file__).resolve().parents[2] / "web" / "app.js").read_text(encoding="utf-8")
for idx, (_, sets) in wuwa_tacet.TACET.items():
    if f'[["{sets[0]}", "{sets[1]}"], {idx}]' not in js:
        fails.append(f"手机页 TACET 里第 {idx} 项和 wuwa_tacet 对不上")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
