"""回放：tests/replay 下每一条真实记录的判定必须和 expected.json 一致。

用户 2026-09-07 批准的根治第 2 项：判断函数只许对着真实样本改；改坏了这里先红。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ark_relay import collector  # noqa: E402

REPLAY = ROOT / "tests" / "replay"
FLOOR = 40          # 语料下限，见 main() 里的说明
# 2026-09-08 从 10 抬到 40：语料库从 1 天（10 条）扩到 4 天（42 条），
# 覆盖到 09-01 周本卡在结算页那一串、09-04/09-05 基质刷取刷错地区那两趟、
# 以及 09-01 终末地「赠送干员礼物」失败。下限的作用是**防止语料悄悄消失**
# ——`.gitignore` 的 `*.log` 就曾经把整个语料库挡在库外，而这个测试当时
# 一条样本都没有也照样打印 all checks passed。
FIELDS = ("okww_steps", "okww_unreachable", "okww_error", "okww_farm", "okww_runs",
          "okww_stamina_spent", "okww_stamina_left", "maaend_name_mismatch", "tasks_failed",
          "tasks_done", "okww_exit_race", "maaend_unreachable")


def snapshot(rec) -> dict:
    out = {"script": rec.script, "ok": rec.ok, "failed_tasks": rec.failed_tasks,
           "duration_known": rec.duration_known}
    for k in FIELDS:
        if k in rec.raw:
            out[k] = rec.raw[k]
    return out


def main() -> int:
    fails = []
    n = 0
    for exp_file in sorted(REPLAY.glob("*/*/expected.json")):
        expected = json.loads(exp_file.read_text(encoding="utf-8"))
        day_root = exp_file.parents[2]
        for stem, want in expected.items():
            js = exp_file.parent / f"{stem}.json"
            rec = collector.parse_record(js, day_root)
            got = snapshot(rec) if rec else None
            n += 1
            if got != want:
                fails.append(f"{exp_file.parent.relative_to(REPLAY)}/{stem}")
                print(f"  ✗ {exp_file.parent.relative_to(REPLAY)}/{stem}")
                for k in sorted(set(want or {}) | set(got or {})):
                    if (got or {}).get(k) != (want or {}).get(k):
                        print(f"      {k}: 期望 {(want or {}).get(k)!r} 实际 {(got or {}).get(k)!r}")
            else:
                print(f"  ✓ {exp_file.parent.relative_to(REPLAY)}/{stem}")
    # 地板：语料一条都没找到时**不许判绿**。两道闸门都只看最后一行有没有
    # "passed"，所以「回放 0 条，all checks passed」会让 collector 的全部判定
    # 函数失去保护，而且一声不吭。2026-09-08 实测：语料被 .gitignore 吃掉之后
    # 正是这个输出。
    if n < FLOOR:
        fails.append(f"回放样本只找到 {n} 条（至少要有 {FLOOR} 条）"
                     "——语料库丢了、被 .gitignore 挡了，或者目录层级变了")
        print(f"  ✗ 语料库只找到 {n} 条，期望至少 {FLOOR} 条")
    print(f"\n回放 {n} 条，" + (f"FAILED: {len(fails)}" if fails else "all checks passed"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
