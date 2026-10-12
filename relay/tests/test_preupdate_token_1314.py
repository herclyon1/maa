"""The service host's expected token failure (winerror 1314) is not a WARNING.

2026-10-12 08:46:12 the relay logged 「预更新：拿控制台令牌失败，改用计划任务方式」 as a WARNING with
the traceback ``pywintypes.error: (1314, 'WTSQueryUserToken', '客户端没有所需的特权。')``; the
scheduled task then started ok-ww.exe at 08:46:17, yet the WARNING went to the group as
「中继自己报错了」. 1314 is the normal case for a LocalSystem service (the code's own
comment). Other failures stay WARNINGs, and the fallback is still taken in both cases.
"""
import logging
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
FAILED = []


def require(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{'' if ok else ': ' + detail}")
    if not ok:
        FAILED.append(name)


class WinErr(Exception):
    def __init__(self, code):
        super().__init__(code, "WTSQueryUserToken", "客户端没有所需的特权。")
        self.winerror = code


def run(code, tcb=True):
    fake = {n: types.ModuleType(n) for n in ("win32con", "win32process", "win32profile", "win32ts")}
    fake["win32ts"].WTSGetActiveConsoleSessionId = lambda: 1
    saved = {n: sys.modules.get(n) for n in fake}
    sys.modules.update(fake)
    from ark_relay.features.preupdate import preupdate_common as pc  # noqa: PLC0415

    def boom(session):
        raise WinErr(code)

    took = []
    old_tok, old_fb, old_tcb = pc._console_primary_token, pc._spawn_fallback, pc._tcb_enabled
    pc._console_primary_token = boom
    pc._tcb_enabled = lambda: tcb
    pc._spawn_fallback = lambda *a, **k: took.append(True) or True
    records = []
    h = logging.Handler()
    h.emit = records.append
    pc.log.addHandler(h)
    try:
        ok = pc._spawn_interactive(Path("C:/ok-ww/ok-ww.exe"), Path("C:/ok-ww"), ())
    finally:
        pc.log.removeHandler(h)
        pc._console_primary_token, pc._spawn_fallback, pc._tcb_enabled = old_tok, old_fb, old_tcb
        for n, m in saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m
    return ok, took, records


# The machine's real case: the service host holds no SE_TCB_NAME - the token route is not tried at all.
tried = []
import ark_relay.features.preupdate.preupdate_common as _pc  # noqa: E402
ok, took, recs = run(1314, tcb=False)
require("没有权限：直接走计划任务", ok and took == [True])
require("没有权限：没有 WARNING", not [r for r in recs if r.levelno >= logging.WARNING],
        str([(r.levelname, r.getMessage()) for r in recs]))
ok, took, recs = run(1314)
require("1314：走计划任务", ok and took == [True])
require("1314：没有 WARNING", not [r for r in recs if r.levelno >= logging.WARNING],
        str([(r.levelname, r.getMessage()) for r in recs]))
ok, took, recs = run(5)
require("别的错：照样走计划任务", ok and took == [True])
require("别的错：仍是 WARNING", any(r.levelno == logging.WARNING for r in recs))
if FAILED:
    print("FAILED:", FAILED)
    sys.exit(1)
print("all checks passed")
