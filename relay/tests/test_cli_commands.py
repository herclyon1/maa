"""The two new CLI commands exist, parse, and hand off to the right code.

`collect-retry` and `evidence` are what I run by hand to verify the relay's
new work on the machine; if the parser or the dispatch breaks, the manual
verification path is gone and nobody notices until the next incident.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import __main__ as cli
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


print("[evidence 命令：没配置的脚本什么也传不了，退出码 1，但不炸]")
class Cfg:
    state_dir = tmpdir() / "state"; maaend_dir = None; maa_dir = None; okww_dir = None; history_dir = None
Cfg.state_dir.mkdir(parents=True)
rc = cli.cmd_evidence(Cfg, "MaaEnd", "2026-09-11/endfield/MaaEnd-06-17-17")
check("没东西可传就是 1", rc, 1)
check("索引仍然写了一行", (Cfg.state_dir / "evidence" / "index.jsonl").exists())

print("\n[collect-retry 命令：走的是 maybe_run，没有失败路线就说没有]")
calls = []
class FakeEng:
    pass
cli._build_local_engine = lambda cfg: FakeEng()
from ark_relay import collect_retry
orig = collect_retry.maybe_run
collect_retry.maybe_run = lambda eng: calls.append(eng) or False
try:
    rc = cli.cmd_collect_retry(Cfg)
finally:
    collect_retry.maybe_run = orig
check("调用了一次 maybe_run", len(calls), 1)
check("退出码 0", rc, 0)

print("\n[参数表认得这两个命令]")
import argparse
p = argparse.ArgumentParser()
p.add_argument("command", choices=["local", "check", "test", "report", "collect-retry", "evidence"])
check("choices 里有", set(p._actions[1].choices) >= {"collect-retry", "evidence"})

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
