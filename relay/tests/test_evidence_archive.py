"""失败证据要存对：AUTO-MAS 那一轮的记录必须带上，日志对不上要出声。

2026-09-05：MaaEnd 基质刷取第一次失败、重试成功。中继 10:00:45 才落账，
那时 MaaEnd 已经重启过、debug 目录被它自己清空重写，于是存下来的
maafw.log 只覆盖 09:57–09:59——**那是重试成功那次**，证据目录名却是失败那次
（MaaEnd-05-27-42）。查了半天才发现拿错了日志。

两条修复：
1. 同时存 AUTO-MAS `history/<run_id>.log/.json`——它按 run_id 取，必然对得上，
   当天正是靠那份 .json 才看出失败的是「基质刷取」。
2. 存下来的 debug 日志若最后写入时刻早于这一轮开始时刻，就是别轮的，出警告。
"""
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

fails = []


def _run_id_stamp(run_id):
    """复刻 _warn_if_evidence_stale 里解析 run_id 末段时刻的那几行。"""
    stamp = run_id.rsplit("-", 3)[-3:]
    if len(stamp) != 3 or not all(x.isdigit() for x in stamp):
        return None
    hh, mm, ss = (int(x) for x in stamp)
    return hh * 3600 + mm * 60 + ss


# run_id 的末段就是这一轮的开始时刻，解析不能错
got = _run_id_stamp("2026-09-05/endfield/MaaEnd-05-27-42")
if got != 5 * 3600 + 27 * 60 + 42:
    fails.append(f"run_id 时刻解析错了：{got}")

# 用户名或脚本名里带横杠也不能把解析带偏
got2 = _run_id_stamp("2026-09-05/end-field/Maa-End-09-57-01")
if got2 != 9 * 3600 + 57 * 60 + 1:
    fails.append(f"带横杠的 run_id 解析错了：{got2}")

# 形状不对时要安静地放弃，不能抛
if _run_id_stamp("2026-09-05/endfield/MaaEnd") is not None:
    fails.append("形状不对的 run_id 应该返回 None")

# 存档函数必须把 history 的两个后缀都带上
src = (pathlib.Path(__file__).resolve().parents[1]
       / "ark_relay" / "handle.py").read_text(encoding="utf-8")
body = src[src.index("def _archive_maaend_evidence"):]
body = body[:body.index("\ndef ", 10)] if "\ndef " in body[10:] else body
if 'history_dir' not in body:
    fails.append("存档没有带上 AUTO-MAS 的 history 记录")
for suffix in ('".log"', '".json"'):
    if suffix not in body:
        fails.append(f"存档没带 {suffix}")
if "automas-" not in body:
    fails.append("AUTO-MAS 的文件没加前缀，会和 MaaEnd 自己的日志重名")
if "_warn_if_evidence_stale" not in body:
    fails.append("存档后没有做日志时间范围检查")

# 检查函数要跳过自己按 run_id 取的那份，否则会自己警告自己
warn = src[src.index("def _warn_if_evidence_stale"):]
warn = warn[:warn.index("\ndef ", 10)]
if 'startswith("automas-")' not in warn:
    fails.append("时间检查没跳过 automas- 那几份（它们必然对得上）")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
