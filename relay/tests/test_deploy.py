"""Deploying from the Mac: deploy-pkg.sh under bash 3.2, deploy-relay.sh's smoke gate. Both run only on the
Mac (.github/workflows/relay-windows.yml excludes this file); test_deploy_watch.py, which runs on Windows
too, stays a file of its own.

One part per former file, each run on its own (tests/_parts.py): test_deploy_pkg_bash32.py, test_deploy_smoke_gate.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_deploy_pkg_bash32():
    """deploy-pkg.sh under macOS /bin/bash 3.2, a UTF-8 locale and set -u.

bash 3.2 reads the bytes of a full-width character right after `$NAME` (for example
`$PREV（`) as part of the variable name, so under set -u the line dies with
"PREVï: unbound variable" (exit 127). Until 2026-10-13 seven lines of
scripts/mac/lib/deploy-pkg.sh were written that way, one of them on the way back
after a failed deploy. Every variable touching a non-ASCII character is ${NAME} now.

No deploy runs here: the way-back block is run in /bin/bash with ssh, scp and the
script's helpers (pkg_py, pkg_py_at, pkg_restart) stood in, and every other echo line
that names a variable next to a non-ASCII character is run on its own.

    Formerly test_deploy_pkg_bash32.py.
    """
    import os
    import re
    import subprocess

    ROOT = Path(__file__).resolve().parents[2]
    SH = (ROOT / "scripts" / "mac" / "lib" / "deploy-pkg.sh").read_text(encoding="utf-8")
    BASH = "/bin/bash"
    ENV = {**os.environ, "LC_ALL": "en_US.UTF-8"}


    def bash(script: str):
        r = subprocess.run([BASH, "-c", script], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=ENV)
        return r.returncode, r.stdout + r.stderr


    if not Path(BASH).exists():
        print("  - no /bin/bash here, nothing to check")
        sys.exit(0)

    print("[this bash is the one that trips]")
    rc, out = bash('set -u; PREV=41; echo "a $PREV（b"')
    print(f"    {Path(BASH)} on $PREV（: exit {rc}")

    print("[no $NAME right before a non-ASCII character]")
    bare = [ln.strip() for ln in SH.splitlines() if re.search(r"\$[A-Za-z_][A-Za-z_0-9]*[^\x00-\x7F]", ln)]
    check("lines with a bare $NAME before a non-ASCII character", bare, [])

    STUBS = r"""
set -euo pipefail
SSH_OPTS=(-o ConnectTimeout=15); USER_AT=Administrator@host
APP_WIN='C:\Program Files\ArkRelay'; PKG_DEPLOY='C:\x\ark-pkg-deploy.py'; WATCH_PY='C:\x\w.py'
PREV=41; NEW=42; VER=20261013000000; T0='2026-10-13 11:00:00'; INC='C:\x\.incoming'
APPFILES_WHY=boom; RUNTIME_WHY=boom; MC_STATE='C:\Program Data\ark'; RUNTIME_PY_EXE='C:\x\python.exe'
FAILED_WHY="上线后没稳住：test"; RUNTIME_TOUCHED=0; APPFILES_SWAPPED=0
STATE=Stopped; CURRENT=42; WATCH_OUT=$(mktemp)
ssh() { :; }
scp() { :; }
pkg_py() { case "$*" in *" watch "*) echo "WATCH_OK" ;; *" back "*) echo "BACK to 41" ;; esac; }
pkg_py_at() { :; }
pkg_restart() { STATE=Running; CURRENT=$PREV; }
"""

    print("[the way back runs to its end]")
    start = SH.find('if [ -n "$FAILED_WHY" ]; then\n  echo "❌❌ $FAILED_WHY"')
    end = SH.find("  exit 13\nfi\n", start)
    check("way-back block found", start >= 0 and end > start, True)
    block = SH[start:end + len("  exit 13\nfi\n")]
    rc, out = bash(STUBS + block)
    check("way back exits 12 (previous version holds)", rc, 12)
    check("way back names the previous version", "自动退回上一版 41（" in out, True)
    check("way back reports it held", "已自动退回上一版 41，" in out, True)

    print("[every other echo naming a variable next to a non-ASCII character]")
    lines = [ln.strip() for ln in SH.splitlines()
             if ln.strip().startswith("echo ") and re.search(r"\$\{?[A-Za-z_][A-Za-z_0-9]*\}?[^\x00-\x7F]", ln)]
    check("found the echo lines", len(lines) >= 7, True)
    for ln in lines:
        rc, out = bash(STUBS + ln + "\n")
        check(f"exit 0: {ln[:60]}", rc, 0)

    print("FAIL" if fails else "all checks passed")


def _part_deploy_smoke_gate():
    """deploy-relay.sh: the smoke runs before COS, and a failed smoke takes the way back.

Until 2026-10-13 the order was watch, publish-cos.py, smoke: on SMOKE_FAIL the relay
kept running code that failed the import check and COS already carried it as the
newest version; only a watch failure put the previous version back. Now the smoke
sits right after the watch, before the notes stamp and COS, and SMOKE_FAIL runs the
same way back as a watch failure (exit 7 when the previous version holds, 13 when not).

No deploy runs here. The `# >>> smoke gate` block is run in bash with ssh, scp and the
installed relay's helpers (pkg_py, pkg_restart) and the old service's restart_service
stood in; what the machine would answer is given per case. The position of the block
in the script is checked on the text.

    Formerly test_deploy_smoke_gate.py.
    """
    import os
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]
    SH = (ROOT / "scripts" / "mac" / "deploy-relay.sh").read_text(encoding="utf-8")


    print("[where the smoke sits]")
    pos = {k: SH.find(k) for k in ("# <<< deploy watch: watch\nfi\n", "# >>> smoke gate", "grep -q '^SMOKE_OK$'",
                                   "# <<< smoke gate", 'printf \'%s\' "$NOTES_SHA" > "$NOTES_STAMP"',
                                   'publish-cos.py"', 'echo "✅ 部署完成')}
    check("every anchor is there", [k for k, v in pos.items() if v < 0], [])
    order = list(pos.values())
    check("watch, then the smoke, then the notes stamp, then COS, then 部署完成", order == sorted(order), True)
    check("one smoke only", SH.count("ark-smoke.py $SMOKE_ARGS"), 1)

    start, end = SH.find("# >>> smoke gate"), SH.find("# <<< smoke gate")
    block = SH[start:end] if 0 <= start < end else "exit 99\n"


    def run(layout: str, smoke_out: str, *, back_holds: bool = True, appfiles: int = 0):
        """(exit code, stdout, calls) of the smoke gate block for one case."""
        with tempfile.TemporaryDirectory() as td:
            calls = Path(td) / "calls"
            script = f"""
set -euo pipefail
LOG={str(calls)!r}
HERE={str(ROOT / "relay")!r}
SSH_OPTS=(-o ConnectTimeout=15)
USER_AT=Administrator@host
LAYOUT={layout}
CHANGED="ark_relay/core/texts.py"
SMOKE_PY='"C:\\py\\python.exe"'; SMOKE_ARGS=""
PY='D:\\ark\\automas\\environment\\python\\python.exe'
REMOTE_DIR='C:/ProgramData/ark-relay'
BACKUP_DIR='C:\\ProgramData\\ark-relay-deploy-prev'
WATCH_PY='C:\\Users\\Administrator\\ark-deploy-watch.py'
PKG_DEPLOY='C:\\Users\\Administrator\\ark-pkg-deploy.py'
APP_WIN='C:\\Program Files\\ArkRelay'
PREV=41; PREV_VER=20261012000000; T0='2026-10-13 11:00:00'
APPFILES_SWAPPED={appfiles}; RUNTIME_TOUCHED=0
STATE=Running; CURRENT=42
WATCH_OUT=$(mktemp)
ssh() {{
  echo "ssh $*" >>"$LOG"
  case "$*" in
    *ark-smoke.py*) printf '%s\\n' "$SMOKE_OUT" ;;
    *" restore "*) echo "RESTORED 2 files" ;;
    *" watch "*) echo "WATCH_OK" ;;
  esac
}}
scp() {{ echo "scp $*" >>"$LOG"; }}
pkg_py() {{
  echo "pkg_py $*" >>"$LOG"
  case "$*" in *" watch "*) echo "WATCH_OK" ;; *" back "*) echo "BACK to 41" ;; esac
}}
pkg_restart() {{ echo "pkg_restart" >>"$LOG"; STATE=$BACK_STATE; CURRENT=$PREV; }}
restart_service() {{ echo "restart_service" >>"$LOG"; STATE=$BACK_STATE; }}
{block}
echo "GATE_PASSED"
"""
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env={**os.environ, "SMOKE_OUT": smoke_out, "LC_ALL": "en_US.UTF-8",
                                    "BACK_STATE": "Running" if back_holds else "Stopped"})
            if r.stderr.strip():
                print("    bash stderr:", r.stderr.strip()[-300:])
            got = calls.read_text().splitlines() if calls.exists() else []
            return r.returncode, r.stdout, got


    def kinds(calls):
        out = []
        for c in calls:
            w = c.split()
            if w[0] == "pkg_py":
                out.append("pkg_py " + w[2] if len(w) > 2 else c)
            elif w[0] == "ssh":
                out.append("ssh " + next((k for k in ("ark-smoke.py", "del", "restore", "watch") if k in c), "?"))
            else:
                out.append(w[0])
        return out


    OK = "SMOKE 导入 3 个模块（共 90 个），失败 0 个\nSMOKE_OK"
    BAD = "SMOKE 导入 3 个模块（共 90 个），失败 1 个\nSMOKE_FAIL\n  import ark_relay.core.texts 失败：SyntaxError"

    print("\n[installed relay, smoke passes: on to COS, nothing put back]")
    rc, out, calls = run("pkg", OK)
    check("the block falls through", (rc, "GATE_PASSED" in out), (0, True))
    check("no way back", [k for k in kinds(calls) if k not in ("scp", "ssh ark-smoke.py", "ssh del")], [])

    print("\n[installed relay, smoke fails: the previous version back, restarted, watched]")
    rc, out, calls = run("pkg", BAD, appfiles=1)
    check("exit 7, never reaches COS", (rc, "GATE_PASSED" in out), (7, False))
    check("back to the previous folder, the swapped files back, restart, 60 s rollback watch",
          [k for k in kinds(calls) if k not in ("scp", "ssh ark-smoke.py", "ssh del")],
          ["pkg_py back", "pkg_py appfiles-back", "pkg_restart", "pkg_py watch"])
    check("back names the previous folder", any(c.endswith("back C:\\Program Files\\ArkRelay 41") for c in calls), True)
    check("the rollback watch expects the previous folder",
          any(" watch " in c and "60 rollback 41 --pkg" in c for c in calls), True)
    check("the reason and the way back are printed", ("SyntaxError" in out, "已自动退回上一版" in out), (True, True))

    print("\n[installed relay, smoke fails and the previous version does not come back up]")
    rc, out, calls = run("pkg", BAD, back_holds=False)
    check("exit 13", (rc, "必须立刻有人处理" in out), (13, True))
    check("no appfiles-back when this deploy swapped none", "pkg_py appfiles-back" in kinds(calls), False)

    print("\n[old service layout, smoke fails: the snapshot restored, restart, watched]")
    rc, out, calls = run("legacy", BAD)
    check("exit 7", rc, 7)
    check("restore, restart_service, rollback watch",
          [k for k in kinds(calls) if k not in ("scp", "ssh ark-smoke.py", "ssh del")],
          ["ssh restore", "restart_service", "ssh watch"])

    print("\n[a smoke that answers nothing is a failure too]")
    rc, out, calls = run("pkg", "")
    check("exit 7 and the way back ran", (rc, "pkg_py back" in kinds(calls)), (7, True))


if __name__ == "__main__":
    sys.exit(run_parts([_part_deploy_pkg_bash32, _part_deploy_smoke_gate]))
