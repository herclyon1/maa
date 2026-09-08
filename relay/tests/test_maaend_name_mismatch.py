"""AUTO-MAS 认不出改了显示名的任务时，中继按 MaaEnd 自己的日志判。

2026-09-06 早班：MaaEnd v2.28.0-beta.1 把 SellProduct 显示名改成「据点交易」。
日志里 17 个任务全部「任务完成」，AUTO-MAS 却记「部分任务执行失败: SellProduct」，
又白跑两趟重试。全部任务都有始有终、没有一条失败 → 这趟是做完的。
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay import collector  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

fails = []
root = tmpdir()
d = root / "2026-09-06" / "endfield"; d.mkdir(parents=True)
good = ("[2026-09-06 09:41:39.529] 任务开始: 🎁赠送干员礼物\n[2026-09-06 09:44:06.485] 任务完成: 🎁赠送干员礼物\n"
        "[2026-09-06 09:51:43.971] 任务开始: 🛒据点交易\n[2026-09-06 09:53:39.232] 任务完成: 🛒据点交易\n"
        "[2026-09-06 10:03:29.939] 任务开始: 🎱基质刷取\n[2026-09-06 10:09:20.303] 任务完成: 🎱基质刷取\n")
(d / "MaaEnd-05-40-21.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: SellProduct"}, ensure_ascii=False), encoding="utf-8")
(d / "MaaEnd-05-40-21.log").write_text(good, encoding="utf-8")
rec = collector.parse_record(d / "MaaEnd-05-40-21.json", root)
if rec is None or not rec.ok or rec.failed_tasks:
    fails.append(f"全部任务完成却判失败：{rec and rec.failed_tasks}")
if rec is not None and rec.raw.get("maaend_name_mismatch") != ["SellProduct"]:
    fails.append(f"没记下 AUTO-MAS 认不出的那个名字：{rec and rec.raw.get('maaend_name_mismatch')}")

# 真失败的（有「任务失败」）照样是失败
bad = good + "[2026-09-06 10:10:00.000] 任务开始: 🧺自动采集\n[2026-09-06 10:12:00.000] 任务失败: 🧺自动采集\n"
(d / "MaaEnd-06-11-14.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: 自动采集"}, ensure_ascii=False), encoding="utf-8")
(d / "MaaEnd-06-11-14.log").write_text(bad, encoding="utf-8")
rec2 = collector.parse_record(d / "MaaEnd-06-11-14.json", root)
if rec2 is None or rec2.ok or rec2.failed_tasks != ["自动采集"]:
    fails.append(f"有任务失败的应仍判失败：{rec2 and (rec2.ok, rec2.failed_tasks)}")

# 开了没收尾的（卡住）也不许洗白
stuck = good + "[2026-09-06 10:10:00.000] 任务开始: 🧺自动采集\n"
(d / "MaaEnd-06-14-25.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: SellProduct"}, ensure_ascii=False), encoding="utf-8")
(d / "MaaEnd-06-14-25.log").write_text(stuck, encoding="utf-8")
rec3 = collector.parse_record(d / "MaaEnd-06-14-25.json", root)
if rec3 is None or rec3.ok:
    fails.append("开了没收尾的任务不该被洗白")

# 旧账重判：记账时是 ❌，判据升级后出报告前要改成 ✅（只往做完的方向改）
old_entry = {"run_id": "2026-09-06/endfield/MaaEnd-05-40-21", "script": "MaaEnd", "ok": False,
             "failed_tasks": ["SellProduct"], "raw": {}}
fresh = collector.refresh_raw(old_entry, root)
if not fresh.get("ok") or fresh.get("failed_tasks"):
    fails.append(f"旧账没按新判据改成做完：{fresh.get('ok')} {fresh.get('failed_tasks')}")
old_bad = {"run_id": "2026-09-06/endfield/MaaEnd-06-11-14", "script": "MaaEnd", "ok": False,
           "failed_tasks": ["自动采集"], "raw": {}}
if collector.refresh_raw(old_bad, root).get("ok"):
    fails.append("真失败的旧账不该被改成做完")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
