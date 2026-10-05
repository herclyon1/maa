"""Pre-update: "could not tell" must reach the problem list, never read as fine.

2026-10-06 audit (BOARD/补丁审查-1005.md, MAA/启动器/更新):

1. preupdate_common._spawn_interactive: when pywin32 failed to import it went
   straight to a plain session-0 launch, ignoring require_console - the exact
   path of 08-25. Real lines (ark-evidence/relay-log-1006/relay.log:1338-1347):
       08-25 08:48:55 WARNING ark.preupdate  预更新：拿控制台令牌失败，退回普通启动
       08-25 08:49:40 INFO    ark.preupdate  预更新：OK-WW 无需更新（v3.6.4）
   (v3.6.5 had been out for fourteen hours.)

2. preupdate_automas.run_automas:
   (a) AUTO-MAS answers a failed check with HTTP 200 and this body
       (upstream AUTO-MAS-Project/AUTO-MAS c6ca4fb, app/api/update.py:57-75):
           UpdateCheckOut(code=500, status="error", message=..., if_need_update=False,
                          latest_version="", update_info={})
       which the relay logged as 「AUTO-MAS 已是 …（无需更新）」.
   (b) a failed install only went to the log, never to the problem list.

Run: python3 relay/tests/test_preupdate_unknown_not_fine.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402
TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import preupdate_common as C   # noqa: E402
from ark_relay import preupdate_okww as O     # noqa: E402
from ark_relay import preupdate_automas as A  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


# ── 1. pywin32 import failure must not bypass require_console ──────────────
# Force the ImportError even if this ever runs on Windows with pywin32 present.
WIN32 = ("win32con", "win32process", "win32profile", "win32ts")
saved_mods = {m: sys.modules.get(m) for m in WIN32}
for m in WIN32:
    sys.modules[m] = None   # `import m` now raises ImportError

calls = []
orig_task, orig_detached = C._spawn_via_task, C._spawn_detached
C._spawn_detached = lambda exe, cwd, args=(): calls.append("detached") or True
exe = TMP / "ok-ww.exe"
exe.write_bytes(b"")
try:
    print("[pywin32 missing, scheduled task also fails, require_console=True]")
    C._spawn_via_task = lambda exe, cwd, args=(): calls.append("task") or False
    got = C._spawn_interactive(exe, TMP, require_console=True, minimized=True)
    check("refuses instead of launching into session 0", got, False)
    check("tried the scheduled task, never the plain launch", calls, ["task"])

    print("\n[pywin32 missing, scheduled task works]")
    calls.clear()
    C._spawn_via_task = lambda exe, cwd, args=(): calls.append("task") or True
    got = C._spawn_interactive(exe, TMP, require_console=True)
    check("launched through the scheduled task", (got, calls), (True, ["task"]))

    print("\n[pywin32 missing, require_console=False (MaaEnd) keeps its fallback]")
    calls.clear()
    C._spawn_via_task = lambda exe, cwd, args=(): calls.append("task") or False
    got = C._spawn_interactive(exe, TMP)
    check("task first, then plain launch", (got, calls), (True, ["task", "detached"]))

    print("\n[OK-WW pre-update with pywin32 missing: the 08-25 morning]")
    calls.clear()
    patched = {"_okww_state": lambda root: ("v3.6.4", "", "", ()),
               "_okww_stamp": lambda root: 0.0,
               "_okww_quiesce": lambda *a, **k: None,
               "_okww_autostart": lambda root, value: True,
               "_okww_await_update": lambda *a, **k: ("", False, False),
               "_okww_report": lambda *a, **k: None,
               "_close": lambda *a, **k: None}
    saved_o = {k: getattr(O, k) for k in patched}
    for k, v in patched.items():
        setattr(O, k, v)
    try:
        problems = []
        note = O.run_okww(TMP, budget_s=1, problems=problems)
    finally:
        for k, v in saved_o.items():
            setattr(O, k, v)
    check("nothing reported as updated", note, "")
    check("never launched into session 0", "detached" in calls, False)
    check("problem list says the check did not happen",
          any("没有检查更新" in p for p in problems), True)
finally:
    C._spawn_via_task, C._spawn_detached = orig_task, orig_detached
    for m, v in saved_mods.items():
        if v is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = v


# ── 2. AUTO-MAS answers that are not a verdict ─────────────────────────────
# Upstream error body for a failed check (app/api/update.py:63-72, c6ca4fb).
# Field set and the message format f"{type(e).__name__}: {e}" are upstream's;
# the message text is illustrative - no real error body has been captured
# (relay.log only logs our verdict, not AUTO-MAS's answer).
CHECK_ERROR = {"code": 500, "status": "error",
               "message": "ConnectError: All connection attempts failed",
               "if_need_update": False, "latest_version": "", "update_info": {}}
# Upstream OutBase on a failed download/install (update.py:100-102, 177-179).
OUT_ERROR = {"code": 500, "status": "error", "message": "RuntimeError: boom"}
CHECK_UPDATE = {"code": 200, "status": "success", "message": "操作成功",
                "if_need_update": True, "latest_version": "v5.5.0-beta.5",
                "update_info": {}}


def run_mas(answers, *, pack=Path("UpdatePack_v5.5.0-beta.5.zip")):
    """Run run_automas against scripted answers; returns (note, problems, paths posted, waits)."""
    posted, waits = [], []

    def fake_post(path, body=None):
        posted.append(path)
        a = answers.get(path, {})
        if isinstance(a, Exception):
            raise a
        return a

    saved = (A._mas_post, A._automas_version, A._live_version,
             A._wait_for_package, A._wait_for_version)
    A._mas_post = fake_post
    A._automas_version = lambda _root: "v5.5.0-beta.4"
    A._live_version = lambda: ""
    A._wait_for_package = lambda _root, _deadline: waits.append("package") or pack
    A._wait_for_version = lambda want, deadline: waits.append("version") or "v5.5.0-beta.4"
    try:
        problems = []
        note = A.run_automas(TMP, budget_s=1, problems=problems)
    finally:
        (A._mas_post, A._automas_version, A._live_version,
         A._wait_for_package, A._wait_for_version) = saved
    return note, problems, posted, waits


print("\n[AUTO-MAS check fails: HTTP 200, code 500, if_need_update=False]")
note, problems, posted, _ = run_mas({"/api/update/check": CHECK_ERROR})
check("not reported as 无需更新 - one problem recorded", len(problems), 1)
check("problem says the check did not happen",
      bool(problems) and "没有检查更新" in problems[0], True)
check("problem carries AUTO-MAS's own message",
      bool(problems) and "ConnectError" in problems[0], True)
check("no download attempted", "/api/update/download" in posted, False)

print("\n[AUTO-MAS check answer without if_need_update]")
_, problems, _, _ = run_mas({"/api/update/check": {"latest_version": "v5.5.0"}})
check("missing field is a problem, not 无需更新",
      len(problems) == 1 and "if_need_update" in problems[0], True)

print("\n[AUTO-MAS genuinely current]")
note, problems, posted, _ = run_mas({"/api/update/check": {
    "code": 200, "status": "success", "message": "操作成功",
    "if_need_update": False, "latest_version": "v5.5.0-beta.4", "update_info": {}}})
check("no problem, no note, no download",
      (note, problems, "/api/update/download" in posted), ("", [], False))

print("\n[AUTO-MAS download refused (code 409 in HTTP 200)]")
_, problems, _, waits = run_mas({
    "/api/update/check": CHECK_UPDATE,
    # update.py:91-94, verbatim
    "/api/update/download": {"code": 409, "status": "error",
                             "message": "已有更新任务在进行中, 请勿重复操作"}})
check("recorded as 下载没能启动", len(problems) == 1 and "下载没能启动" in problems[0], True)
check("did not wait out the download budget", "package" in waits, False)

print("\n[AUTO-MAS install request raises]")
note, problems, _, waits = run_mas({
    "/api/update/check": CHECK_UPDATE,
    "/api/update/install": OSError("connection reset")})
check("install failure is in the problem list",
      len(problems) == 1 and "安装没能启动" in problems[0], True)
check("nothing reported as updated", note, "")

print("\n[AUTO-MAS install answers code 500 in HTTP 200]")
note, problems, _, waits = run_mas({
    "/api/update/check": CHECK_UPDATE, "/api/update/install": OUT_ERROR})
check("install error body is in the problem list",
      len(problems) == 1 and "安装没能启动" in problems[0], True)
check("did not wait for a restart that was never started", "version" in waits, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
