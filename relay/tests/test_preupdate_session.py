"""The pre-update must not launch a GUI program from session 0.

The relay runs as LocalSystem, so its processes land in session 0, which has
no desktop. MaaEnd and MAA are both GUI programs: started there they touch
their own log file and die. That failed silently for three nightly runs - the
pre-update simply timed out at its full budget every time and reported
"本轮照旧". Only _spawn_interactive, which hands the child the console user's
token, may start them.
"""
import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "ark_relay" / "preupdate.py"
# The functions that actually start a program. run() delegates its body to
# _run_maaend so the auto-run disarm can wrap it in a try/finally.
LAUNCHERS = {"_run_maaend", "run_maa"}
ALLOWED = {"_spawn_detached"}   # the fallback is the one place Popen belongs

FAILED = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{'' if ok else ': ' + detail}")
    if not ok:
        FAILED.append(name)


def popen_calls(fn):
    out = []
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Popen"):
            out.append(node.lineno)
    return out


def calls_named(fn, name):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == name for n in ast.walk(fn))


def main() -> int:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    fns_node = fns

    check("_spawn_interactive 存在", "_spawn_interactive" in fns)
    for name in sorted(LAUNCHERS):
        fn = fns.get(name)
        if fn is None:
            check(f"{name} 存在", False, "函数不见了")
            continue
        lines = popen_calls(fn)
        check(f"{name} 不直接 Popen", not lines, f"第 {lines} 行仍在直接启动")
        check(f"{name} 走 _spawn_interactive", calls_named(fn, "_spawn_interactive"))

    for name, fn in fns.items():
        if name in ALLOWED or name in LAUNCHERS:
            continue
        lines = popen_calls(fn)
        if lines:
            check(f"{name} 不应直接 Popen", False, f"第 {lines} 行")

    # The desktop is the whole point; losing this string re-breaks it silently.
    src = SRC.read_text(encoding="utf-8")
    check("指定了 winsta0\\default 桌面", "winsta0" in src)
    # MAA must never be opened in a way that lets it start a round at boot.
    # --skip-startup-auto-run is MAA's own argument for that; losing it here
    # would turn the pre-update into an unscheduled farming run at 08:40.
    check("MAA 用官方的 --skip-startup-auto-run",
          "--skip-startup-auto-run" in src)
    check("并保留改配置这道二重锁", "_maa_run_directly" in src)
    check("拿的是控制台会话令牌", "WTSQueryUserToken" in src)
    # AUTO-MAS is the one of the three that must never be launched by the
    # pre-update: it is already running, and its update is an HTTP question.
    fns = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    check("有 run_automas", "run_automas" in fns)
    if "run_automas" in fns:
        check("run_automas 不启动任何进程",
              not popen_calls(fns_node["run_automas"]) and
              not calls_named(fns_node["run_automas"], "_spawn_interactive"))
    # AUTO-MAS installs by extracting UpdatePack_*.zip and launching
    # AUTO-MAS-Setup.exe, and install_update() refuses outright when the package
    # is not on disk. So the order matters: check, download, wait for the
    # package to settle, only then install. Calling install straight after
    # download returns would just get "未检测到更新包, 请先下载更新".
    if "run_automas" in fns_node:
        literals = [n.value for n in ast.walk(fns_node["run_automas"])
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        joined = " ".join(literals)
        for ep in ("/api/update/check", "/api/update/download",
                   "/api/update/install"):
            check(f"run_automas 会调 {ep}", ep in joined)
        check("安装前先等更新包落地",
              calls_named(fns_node["run_automas"], "_wait_for_package"))
        # AUTO-MAS's backend is not listening the moment the relay wakes at
        # boot. Asking once and giving up is what actually happened on
        # 2026-08-24 08:45:33, nine minutes before its backend answered.
        has_loop = any(isinstance(n, (ast.While, ast.For))
                       for n in ast.walk(fns_node["run_automas"]))
        check("等 AUTO-MAS 后端起来（不是问一次就放弃）", has_loop)
        check("等待时长有上限", "MAS_WAIT_SECONDS" in src)
    src_all = src
    check("等包的实现在", "def _wait_for_package" in src_all)
    # The gate that makes this safe lives in service.py, not here.
    svc = (Path(__file__).resolve().parents[1] / "service.py").read_text(
        encoding="utf-8")
    check("中继在安装器运行时不抢着拉起 AUTO-MAS",
          "auto-mas-setup" in svc and "_installer_running" in svc)

    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
