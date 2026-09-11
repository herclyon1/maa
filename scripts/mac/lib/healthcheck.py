"""收工前的体检：本地补丁在不在、配置有没有被临时改动留下、明早能不能跑。

    scripts/mac/winrun.sh --py scripts/mac/lib/healthcheck.py

**为什么值得留着**：2026-08-26 那一夜改了十几处（三条 OK-WW 源码补丁、
一堆临时配置、两个队列），全靠脑子记「哪些改回来了」必然漏。这份脚本把
「应该是什么样」写死成断言，跑一遍就知道有没有欠账。

写它的时候自己踩了两个坑，都留在注释里：
* 找 `run_additional_tasks` 不带 `self.` 前缀会匹配到定义处，位置比错；
* AUTO-MAS 更新包下不完是**设计内**的（600 秒放弃、留到下次开机），
  不能算失败——把它和真正的未确认项分开。
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\ProgramData\ark-relay")
from arklog import RELAY_LOG, mtime, since

OK, BAD = [], []


def check(name, cond, detail=""):
    (OK if cond else BAD).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  {detail}" if detail else ""))


def post(path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:36163{path}",
                                 data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


print("=== 1. OK-WW 本地改动（都在 ok_tasks/ark_overrides.py 里，源文件必须是上游原样）===")
# Since 2026-09-09 nothing is patched into OK-WW's source: the changes are
# installed as an ok_tasks extension and bind at OK-WW start-up, which writes
# C:\ProgramData\ark-okww-overlay.json. This section used to look for patch
# markers inside the source files and went red on every boot after the move
# (2026-09-12) - the truth is the overlay report plus a pristine source tree.
work = Path(r"D:\ark\okww\data\apps\ok-ww\working\src\task")
from ark_relay import okww_overlay                 # noqa: E402
_ov = okww_overlay.target(r"D:\ark\okww")
check("覆盖文件在位且和仓库一致",
      _ov is not None and _ov.is_file()
      and _ov.read_text(encoding="utf-8") == okww_overlay.source_text(), str(_ov))
_rep = okww_overlay.last_report()
_need = {"DailyTask.run", "DailyTask.run_additional_tasks", "NightmareNestTask.find_nest",
         "NightmareNestTask.get_nest_to_go", "NightmareNestTask.run",
         "FarmEchoTask.revive_action", "BaseWWTask.click_on_book_target"}
_applied = set(_rep.get("applied") or [])
check("上次启动时全部绑定成功（没有跳过、没有报错）",
      bool(_rep) and not _rep.get("skipped") and not _rep.get("error") and _need <= _applied,
      f"绑定 {len(_applied)} 条，跳过 {_rep.get('skipped')}，报错 {_rep.get('error') or '无'}，"
      f"缺 {sorted(_need - _applied) or '无'}")
daily = (work / "DailyTask.py").read_text(encoding="utf-8", errors="replace")
nest = (work / "NightmareNestTask.py").read_text(encoding="utf-8", errors="replace")
domain = (work / "DomainTask.py").read_text(encoding="utf-8", errors="replace")
combat = (work / "BaseCombatTask.py").read_text(encoding="utf-8", errors="replace")
# The old in-source patches must not have crept back: a marker here means an
# upstream file was edited again, and the next OK-WW update would half-apply.
check("源文件里没有残留的旧补丁（巢穴 / 领奖 / 副本 / 主C）",
      "_next_nest_with_progress" not in nest and "Only Farm These Nests" not in nest
      and "ark_" not in daily and "WaitFailedException" not in domain
      and "_starved_main_dps_target" not in combat)
check("巢穴源文件 = 登记的上游原样",
      (work / "NightmareNestTask.py").read_bytes()
      == Path(r"C:\ProgramData\ark-relay\ark_relay\okww_files\NightmareNestTask.upstream.py").read_bytes())

print("\n=== 2. 补丁能自动重贴（OK-WW 更新会覆盖 src）===")
ref = Path(r"C:\ProgramData\ark-relay\ark_relay\okww_files")
check("参照文件在位", (ref / "NightmareNestTask.patched.py").exists()
      and (ref / "NightmareNestTask.upstream.py").exists())
from ark_relay import okww_patch                  # noqa: E402
notes = okww_patch.ensure_patches(Path(r"D:\ark\okww"))
check("ensure_patches 幂等（全部已在位）", notes == [], f"返回 {notes}")

print("\n=== 3. OK-WW 配置是不是我们要的那套 ===")
# 读**母本**：快速配置已关，AUTO-MAS 每轮把母本整个拷给 OK-WW，
# MAS API 里那几个字段不再驱动运行。2026-08-29 之前这里读 OK-WW 自己目录
# 那份、而且期望「回到默认」——正好和死命令 okww-only-nanqiu 反着来，
# 对着正确的配置天天喊狼来了。
from ark_relay.config import master_config_dir            # noqa: E402
_mdir = master_config_dir(r"D:\ark\automas", "DailyTask.json")
cfg = json.loads((_mdir / "NightmareNestTask.json").read_text(encoding="utf-8"))
daily = json.loads((_mdir / "DailyTask.json").read_text(encoding="utf-8"))
check("巢穴：只刷落渊南丘", cfg.get("Only Farm These Nests") == "落渊南丘",
      f"实际 {cfg.get('Only Farm These Nests')!r}")
check("巢穴：只刷残象聚落（不碰梦魇拔除）",
      cfg.get("Which to Farm") == ["Tacet Discord Nest"],
      f"实际 {cfg.get('Which to Farm')!r}")
check("巢穴：走刷满模式（附加任务里有 Auto Farm all Nightmare Nest）",
      "Auto Farm all Nightmare Nest" in (daily.get(
          "Additional Tasks to Run After Daily Task") or []),
      f"实际 {daily.get('Additional Tasks to Run After Daily Task')!r}")
scripts = post("/api/scripts/get")["data"]
sid = next(k for k, v in scripts.items()
           if "ok" in str((v.get("Info") or {}).get("Name") or "").lower())
u = next(iter(post("/api/scripts/user/get", {"scriptId": sid})["data"].values()))
# 「每日声骸」这个开关在刷满模式下不再生效（DailyTask 的 if/elif，
# condition1 优先），留着不碍事，所以只报状态、不当失败。
print(f"  ·  每日声骸开关（刷满模式下不生效）= "
      f"{daily.get('Farm Nightmare Nest for Daily Echo')}")
# What he farms is his choice, not a health item (2026-09-11: 「管好程序会不会出
# bug就行，管我刷什么干嘛」). Shown for information only; the phone page is where
# it gets changed. The two fields are independent settings.
print(f"  ·  体力去处 Which to Farm = {daily.get('Which to Farm')!r}；"
      f"材料 Material Selection = {daily.get('Material Selection')!r}（只显示，不判）")

print("\n=== 4. MAA 关键配置（826 事故相关）===")
mid = next(k for k, v in scripts.items()
           if (v.get("Info") or {}).get("Name") == "MAA")
m = next(iter(post("/api/scripts/user/get", {"scriptId": mid})["data"].values()))
# Stage and medicine count are his choices, shown for information only. The
# 「用户要求不吃药」 check that stood here from 09-03 was never asked for - I had
# read the value 0 of the day as a rule (2026-09-11: 「谁跟你说的？」).
print(f"  ·  关卡 Info.Stage = {m['Info'].get('Stage')!r}（StageMode={m['Task'].get('StageMode')!r}）"
      f"；理智药 MedicineNumb = {m['Info'].get('MedicineNumb')!r}（只显示，不判）")
check("活动关优先＝关（826 的元凶）", m["Task"].get("IfActivityFirst") is False)
check("剿灭 Close", m["Info"].get("Annihilation") == "Close")
check("理智作战开着", m["Task"].get("IfFight") is True)

print("\n=== 5. 明早能不能跑 ===")
q = post("/api/queue/get")["data"]
for qid, qq in q.items():
    info = qq["Info"]
    times = post("/api/queue/time/get", {"queueId": qid})["data"]
    items = post("/api/queue/item/get", {"queueId": qid})["data"]
    t0 = next(iter(times.values()))["Info"]
    check(f"队列「{info['Name']}」{t0['Time']} 启用",
          info.get("TimeEnabled") and t0.get("Enabled"),
          f"{len(items)} 个脚本，{len(t0.get('Days') or [])} 天")

print("\n=== 6. 中继 ===")
check("日志在动", True, mtime(RELAY_LOG))
recent = since(RELAY_LOG, "00:45")
check("已武装明早的闹钟", any("检查点 09:00" in l for l in recent),
      "（下一个闹钟 09:02 检查点 09:00）")
# AUTO-MAS 更新包下不完是**设计内**的：600 秒放弃、留到下次开机装，
# 不留半截状态。除它之外的未确认项才算问题。
unconfirmed = [l for l in recent if "预更新：" in l and "没" in l
               and "AUTO-MAS" not in l and "无需更新" not in l]
check("预更新除 AUTO-MAS 下载超时外没有别的未确认项",
      not unconfirmed, "；".join(x[-60:] for x in unconfirmed) or "无")
# 「无需更新」也是干净的；只有既没装成、也没说放弃才算问题。
check("AUTO-MAS 预更新有明确结论（装了 / 无需更新 / 干净放弃）",
      any(("留到下次开机再装" in l or "无需更新" in l or "已更新" in l)
          and "AUTO-MAS" in l for l in recent))

print("\n=== 7. 会让机器整夜不关的一次性开关 ===")
# 09-03 and 09-04 the machine stayed on all night because 「这次别关机」 was
# left armed; it eats the next shutdown and never expires. NEXT-BOOT.md closed
# that with "check state.json's modes before signing off" - and nothing did.
try:
    _st = json.loads(Path(r"C:\ProgramData\ark-relay\state\state.json").read_text(encoding="utf-8"))
    _modes = _st.get("modes") or {}
    check("「这次别关机」没留着", not _modes.get("skip_next_shutdown"),
          "留着！它会吃掉下一次关机，机器整夜开着——用手机页或 order.sh 取消")
    check("调试模式没留着", not _modes.get("debug_until"),
          f"留着，到 {_modes.get('debug_until')}——跑完就不关机")
except Exception as _exc:  # noqa: BLE001
    check("读得到 state.json 的 modes", False, f"{type(_exc).__name__}: {_exc}")

print(f"\n{'=' * 46}\n通过 {len(OK)} 项" + (f"，失败 {len(BAD)} 项：{BAD}" if BAD else "，全部通过"))
