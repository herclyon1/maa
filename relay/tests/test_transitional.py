"""「中途重启」不是失败。

2026-08-28：中继在日报里列了四项失败，其中一项是鸣潮客户端更新后
正常重启。根因在 AUTO-MAS：`task/Okww/AutoProxy.py:50-54` 把
「游戏更新成功, 游戏即将重启」和「未连接游戏客户端」「流程产生错误」
一起放进 `_OKWW_BUILTIN_FATAL`，于是它写出一条非成功结果、标记 ERROR。

中继照单全收就是假警报。这组用例把新口径钉住：这类记录既不算成功、
也不进失败清单，而且这个标记必须能穿过 payload 往返（重启后重放会用到）。
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import collector, transport  # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def write(root: Path, stem: str, result: str) -> Path:
    d = root / "2026-08-28" / "wuwa"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{stem}.json"
    f.write_text(json.dumps({"general_result": result}, ensure_ascii=False),
                 encoding="utf-8")
    return f


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)

        print("[客户端更新后重启：不是失败]")
        f = write(root, "OK-WW-05-32-24", "游戏更新成功，即将重启任务")
        rec = collector.parse_record(f, root)
        check("解析出来了", rec is not None, True)
        check("不算成功", rec.ok, False)
        check("标为中途重启", rec.transitional, True)
        check("失败清单是空的", rec.failed_tasks, [])

        print("\n[真故障：照旧算失败]")
        f2 = write(root, "OK-WW-05-40-00", "OK-WW 流程产生错误，请检查游戏状态")
        r2 = collector.parse_record(f2, root)
        check("不算成功", r2.ok, False)
        check("不是中途重启", r2.transitional, False)
        check("失败清单有内容", bool(r2.failed_tasks), True)

        print("\n[正常成功]")
        f3 = write(root, "OK-WW-05-50-00", "Success!")
        r3 = collector.parse_record(f3, root)
        check("算成功", r3.ok, True)
        check("不是中途重启", r3.transitional, False)

        print("\n[标记必须穿过 payload 往返]")
        p = transport.record_to_payload(rec)
        check("payload 带着这个键", p.get("transitional"), True)
        check("中途重启不附日志尾巴", p.get("log_tail"), "")
        back = transport.payload_to_record(p)
        check("读回来还是中途重启", back.transitional, True)
        old = {k: v for k, v in p.items() if k != "transitional"}
        check("老 payload 没这个键时默认 False（不改判历史）",
              transport.payload_to_record(old).transitional, False)

    print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
