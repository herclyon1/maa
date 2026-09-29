"""A self-update restart must stop the old process before the boot stages run.

Real sequence, 2026-09-29 (machine clock, Beijing):
08:45:23 「代码已更新，重启以立即生效」 - the detached restarter is started, but
_stage_selfupdate returned None (a bare return since 25b76dd4 on 09-08), so
service.py carried on; 08:45:51 the dying process launched MAA for the
pre-update; 08:45:57 the stop hard guard force-exited it, with MAA still open;
08:46:00 that MAA logged "current version is latest"; 08:46:14 the new process
launched MAA again, got "Existing instance window activated by a secondary
launch" and no further gui.log line; 08:49:14 「180 秒内没给出更新结论」.
"""
import ast
import sys
import tempfile
import types
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for name in ("win32serviceutil", "win32service", "win32event", "win32api",
             "win32con", "win32file", "servicemanager", "win32process",
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
             "win32com", "win32com.client"):
    sys.modules.setdefault(name, _Stub(name))

import boot_stages  # noqa: E402
from ark_relay import preupdate, preupdate_maa, selfupdate  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


class _Log:
    def info(self, *a, **k): pass
    def exception(self, *a, **k): pass
    warning = info


def test_selfupdate_returns_true():
    print("自更新拉到新代码：返回 True，让 service.py 立刻退出")
    real_check, real_popen = selfupdate.check, boot_stages.subprocess.Popen
    spawned = []
    selfupdate.check = lambda here: ["ark_relay/report.py"]
    boot_stages.subprocess.Popen = lambda *a, **k: spawned.append(a)
    for flag in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS"):   # Windows-only
        if not hasattr(boot_stages.subprocess, flag):
            setattr(boot_stages.subprocess, flag, 0)
    try:
        check("有更新时返回", boot_stages._stage_selfupdate(_Log()), True)
        check("起了重启器", len(spawned), 1)
        selfupdate.check = lambda here: []
        check("没更新时返回", boot_stages._stage_selfupdate(_Log()), False)
    finally:
        selfupdate.check, boot_stages.subprocess.Popen = real_check, real_popen


def test_no_bare_return_in_bool_functions():
    print("声明返回 bool 的函数里没有裸 return（None 会被当成 False）")
    bad = []
    for p in sorted(RELAY.rglob("*.py")):
        if "tests" in p.parts:
            continue
        for f in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if (isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and isinstance(f.returns, ast.Name) and f.returns.id == "bool"):
                bad += [f"{p.relative_to(RELAY)}:{n.lineno} {f.name}"
                        for n in ast.walk(f)
                        if isinstance(n, ast.Return) and n.value is None]
    check("裸 return", bad, [])


def test_preupdate_skipped_while_stopping():
    print("服务正在停止：不做预更新，不起任何程序")
    asked = []
    real = boot_stages._stop_requested, preupdate.wanted_today
    boot_stages._stop_requested = lambda: True
    preupdate.wanted_today = lambda *a, **k: asked.append(1) or False
    try:
        boot_stages._stage_preupdate(types.SimpleNamespace(automas_dir=None), None, _Log())
        check("停止时连「今天要不要做」都不问", asked, [])
    finally:
        boot_stages._stop_requested, preupdate.wanted_today = real


def test_run_maa_closes_leftover_first(tmp: Path):
    print("MAA 预更新：起 MAA 之前先关掉上一个进程留下的实例")
    (tmp / "MAA.exe").write_bytes(b"")
    (tmp / "debug").mkdir()
    (tmp / "debug" / "gui.log").write_text("", encoding="utf-8")
    calls = []
    saved = (preupdate_maa._close, preupdate_maa._spawn_interactive,
             preupdate_maa._maa_run_directly, preupdate_maa._maa_await_verdict)
    preupdate_maa._close = lambda exe: calls.append("close")
    preupdate_maa._spawn_interactive = lambda *a, **k: calls.append("spawn") or True
    preupdate_maa._maa_run_directly = lambda d, v: False
    preupdate_maa._maa_await_verdict = lambda *a, **k: ("", True)
    try:
        preupdate_maa.run_maa(tmp, budget_s=1, problems=[])
    finally:
        (preupdate_maa._close, preupdate_maa._spawn_interactive,
         preupdate_maa._maa_run_directly, preupdate_maa._maa_await_verdict) = saved
    check("先关再起、结束再关", calls, ["close", "spawn", "close"])


if __name__ == "__main__":
    test_selfupdate_returns_true()
    test_no_bare_return_in_bool_functions()
    test_preupdate_skipped_while_stopping()
    with tempfile.TemporaryDirectory() as t:
        test_run_maa_closes_leftover_first(Path(t))
    print("all checks passed" if not fails else f"FAILED: {fails}")
    raise SystemExit(1 if fails else 0)
