"""OK-WW **真正生效**的配置——别再去读那份会被换掉的。

用法（在游戏机上，通过 winrun）：

    winrun.sh --py scripts/mac/lib/okww_effective.py

**为什么存在**（2026-08-27 的账）：

OK-WW 自己的 `data/apps/ok-ww/working/configs/*.json` 看着像配置，
但 AUTO-MAS 在跑之前会把整个目录**备份走、换成它自己那份**、跑完再还原
（`app/task/Okww/manager.py` 的 `_restore_script_config_from_temp`）。
所以在 OK-WW 目录里改的东西，跑的时候一个都不算数。

我因此连续多次告诉用户「已经设成只刷落渊南丘了」，而真正生效的那份里写的是
`["Nightmare Purification","Tacet Discord Nest"]` 且没有点位限制，
外加 `Additional Tasks` 里挂着 `Auto Farm all Nightmare Nest`——全量刷。
用户的原话是「我跟你强调多少遍了，我只刷那个东西」。

生效顺序（`app/task/Okww/AutoProxy.py`）：

1. `Info.Mode` 不是「直控」→ 用 MAS 那份全量目录
   `<automas>/data/<脚本id>/<owner>/ConfigFile`，`owner` 在「脚本」模式下是 `Default`
2. `Info.IfQuickConfig` 为真 → 再用 MAS 用户配置里的 `Task.*` 覆盖若干键
3. 启动参数 `-t <Task.TaskIndex> -e`
"""
from __future__ import annotations

import json
from pathlib import Path

AUTOMAS = Path(r"D:\ark\automas")
OKWW_ROOT = Path(r"D:\ark\okww")
DECOY_DIR = OKWW_ROOT / "data" / "apps" / "ok-ww" / "working" / "configs"

# MAS 用户配置里的 Task.* → OK-WW 配置文件里的键。
# 抄自 AutoProxy.py 的 `_apply_quick_config`，改那边时这里要跟着改。
QUICK = {
    "WhichToFarm": ("DailyTask", "Which to Farm"),
    "WhichTacetSuppressionToFarm": ("DailyTask", "Which Tacet Suppression to Farm"),
    "WhichForgeryChallengeToFarm": ("DailyTask", "Which Forgery Challenge to Farm"),
    "MaterialSelection": ("DailyTask", "Material Selection"),
    "FarmNightmareNestForDailyEcho": ("DailyTask", "Farm Nightmare Nest for Daily Echo"),
    "AdditionalTasks": ("DailyTask", "Additional Tasks to Run After Daily Task"),
}


def script_ids() -> list[str]:
    d = AUTOMAS / "data"
    return [p.name for p in d.iterdir() if p.is_dir()] if d.exists() else []


def master_dir(script_id: str, owner: str = "Default") -> Path:
    return AUTOMAS / "data" / script_id / owner / "ConfigFile"


def load(d: Path, name: str) -> dict:
    f = d / f"{name}.json"
    return json.loads(f.read_text(encoding="utf-8", errors="replace")) if f.is_file() else {}


def effective(script_id: str, user_task: dict | None = None) -> dict[str, dict]:
    """母本 + 快速配置覆盖之后的样子。"""
    d = master_dir(script_id)
    out = {n: load(d, n) for n in ("DailyTask", "NightmareNestTask", "Game Hotkey")}
    for src, (fname, key) in QUICK.items():
        if user_task and src in user_task:
            out.setdefault(fname, {})[key] = user_task[src]
    return out


def main() -> int:
    ids = [s for s in script_ids() if master_dir(s).exists()]
    if not ids:
        print("❌ 找不到任何 MAS 侧配置目录")
        return 1
    bad = 0
    for sid in ids:
        print(f"=== 脚本 {sid} 的母本 {master_dir(sid)} ===")
        eff = effective(sid)
        for name, cfg in eff.items():
            if cfg:
                print(f"  {name}: {json.dumps(cfg, ensure_ascii=False)[:150]}")
        nest = eff.get("NightmareNestTask") or {}
        daily = eff.get("DailyTask") or {}
        if nest:
            only = nest.get("Only Farm These Nests", "")
            adds = daily.get("Additional Tasks to Run After Daily Task") or []
            if only != "落渊南丘":
                print(f"  ❌ 只刷落渊南丘没设上：Only Farm These Nests = {only!r}")
                bad += 1
            if "Auto Farm all Nightmare Nest" in adds:
                print("  ❌ 附加任务里挂着「Auto Farm all Nightmare Nest」= 全量刷")
                bad += 1
            if bad == 0:
                print("  ✅ 只刷落渊南丘，没有全量刷")
    print(f"\n对照：OK-WW 自己目录 {DECOY_DIR} 里那份**跑的时候会被换掉**，不作数。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
