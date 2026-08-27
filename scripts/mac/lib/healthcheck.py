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
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\ProgramData\ark-relay")
from arklog import RELAY_LOG, mtime, since        # noqa: E402

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


print("=== 1. OK-WW 三条本地补丁 ===")
work = Path(r"D:\ark\okww\data\apps\ok-ww\working\src\task")
daily = (work / "DailyTask.py").read_text(encoding="utf-8", errors="replace")
# 必须带 self. 前缀：不带的话会匹配到定义/注释里的名字，比出来的位置是错的。
check("领奖顺序（附加任务在领奖前）",
      daily.find("self.run_additional_tasks()") < daily.find("self.claim_daily()"),
      f"{daily.find('self.run_additional_tasks()')} < {daily.find('self.claim_daily()')}")
domain = (work / "DomainTask.py").read_text(encoding="utf-8", errors="replace")
check("副本失败不拖垮每日任务",
      "NotInCombatException, CharDeadException, WaitFailedException" in domain)
nest = (work / "NightmareNestTask.py").read_text(encoding="utf-8", errors="replace")
check("巢穴：允许续刷",
      any(l.lstrip().startswith("if numerator != denominator") for l in nest.splitlines()))
check("巢穴：打完没进展就跳过", "_next_nest_with_progress" in nest)
check("巢穴：可指定点位", "Only Farm These Nests" in nest)
combat = (work / "BaseCombatTask.py").read_text(encoding="utf-8", errors="replace")
check("主C饿死兜底（保险，平时休眠）", "_starved_main_dps_target" in combat)

print("\n=== 2. 补丁能自动重贴（OK-WW 更新会覆盖 src）===")
ref = Path(r"C:\ProgramData\ark-relay\ark_relay\okww_files")
check("参照文件在位", (ref / "NightmareNestTask.patched.py").exists()
      and (ref / "NightmareNestTask.upstream.py").exists())
from ark_relay import okww_patch                  # noqa: E402
notes = okww_patch.ensure_patches(Path(r"D:\ark\okww"))
check("ensure_patches 幂等（全部已在位）", notes == [], f"返回 {notes}")

print("\n=== 3. OK-WW 配置回到默认 ===")
cfg = json.loads((Path(r"D:\ark\okww\data\apps\ok-ww\working\configs")
                  / "NightmareNestTask.json").read_text(encoding="utf-8"))
check("巢穴：刷全部（没留指定点位）", cfg.get("Only Farm These Nests") == "")
check("巢穴：梦魇+残象都刷", len(cfg.get("Which to Farm") or []) == 2)
scripts = post("/api/scripts/get")["data"]
sid = next(k for k, v in scripts.items()
           if "ok" in str((v.get("Info") or {}).get("Name") or "").lower())
u = next(iter(post("/api/scripts/user/get", {"scriptId": sid})["data"].values()))
check("每日声骸开着", u["Task"].get("FarmNightmareNestForDailyEcho") is True)
check("附加任务已清空（没留临时的全刷）", u["Task"].get("AdditionalTasks") == [])
check("体力去处＝凝素领域第1个",
      u["Task"].get("WhichToFarm") == "Forgery Challenge"
      and u["Task"].get("WhichForgeryChallengeToFarm") == 1)

print("\n=== 4. MAA 关键配置（826 事故相关）===")
mid = next(k for k, v in scripts.items()
           if (v.get("Info") or {}).get("Name") == "MAA")
m = next(iter(post("/api/scripts/user/get", {"scriptId": mid})["data"].values()))
check("关卡 AT-4", m["Info"].get("Stage") == "AT-4")
check("理智药 999（无限吃）", str(m["Info"].get("MedicineNumb")) == "999")
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
check("AUTO-MAS 更新是干净放弃（留到下次开机）",
      any("留到下次开机再装" in l for l in recent))

print(f"\n{'=' * 46}\n通过 {len(OK)} 项" + (f"，失败 {len(BAD)} 项：{BAD}" if BAD else "，全部通过"))
