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
from ark_relay import collect_retry
from _tmp import tmpdir
import argparse

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
orig = collect_retry.maybe_run
collect_retry.maybe_run = lambda eng, day=None: calls.append((eng, day)) or False
try:
    rc = cli.cmd_collect_retry(Cfg, "2026-09-11")
finally:
    collect_retry.maybe_run = orig
check("调用了一次 maybe_run，带指定的日期", calls and calls[0][1] == "2026-09-11" and len(calls) == 1)
check("退出码 0", rc, 0)

print("\n[banners 命令：打印那一段、来源和核对，扣下的行让退出码变 1]")
from ark_relay import banners as _bn  # noqa: E402
from datetime import datetime  # noqa: E402
import io, contextlib  # noqa: E402
def fake_collect(now, *, skland_token="", failed=None, notes=None, trace=None, **_):
    b = _bn.Banner("鸣潮", "身赴三途", ("景燃",), datetime(2026, 9, 10, 10, 0), datetime(2026, 9, 29, 11, 59, 59))
    trace.ends |= _bn._stamps(b.end)
    trace.src("鸣潮", "当期", "库街区", "身赴三途 景燃")
    trace.checks.append("鸣潮：库街区=游戏公告 ✓")
    notes["明日方舟"] = "09-18 03:59 之后开（还有 5 天）　下一池官方还没公告"
    return [b], {}
orig_collect = _bn.collect
_bn.collect = fake_collect
Cfg.skland_token = ""
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_banners(Cfg)
finally:
    _bn.collect = orig_collect
out = buf.getvalue()
check("打印了当期行", "「身赴三途」景燃" in out)
check("打印了来源", "库街区｜身赴三途 景燃" in out)
check("编出来的预告被扣下并列出", "扣下的行" in out and "09-18 03:59 之后开" in out)
check("有扣下的行时退出码 1", rc, 1)

print("\n[参数表认得这几个命令]")
p = argparse.ArgumentParser()
p.add_argument("command", choices=["local", "check", "test", "report", "collect-retry", "evidence", "banners"])
check("choices 里有", set(p._actions[1].choices) >= {"collect-retry", "evidence", "banners"})

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
