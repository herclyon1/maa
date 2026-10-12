"""scripts/mac/estop.sh stops the installed relay unless the machine says it runs the old one.

The red button stops the relay first (step 0), because the relay brings AUTO-MAS back.
Which relay is asked first; until 2026-10-12 a question that got no answer (ssh timed
out, pwsh printed something else) fell into the old-service branch and sent only
`sc stop ark-relay`. That service was deleted on 2026-10-11 (scripts/windows/retire_legacy.py),
so the stop did nothing: the installed relay (task \\ArkRelay\\main, watchdog service
ArkRelayWatchdog) kept running and revived AUTO-MAS right after the script killed it.
Now only a positive "legacy" answer takes the old path, for the stop and for --restore.

Nothing here reaches the game machine: PATH starts with a fake ssh that decodes the
-EncodedCommand, records it and answers by its content, and a fake curl that answers 0;
ARK_HOST is 127.0.0.1 and stop runs use --keep-queue, so the queue API is never called.
ESTOP_SH points the test at another copy of the script (to show it fails on the old one).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("ESTOP_SH") or ROOT / "scripts" / "mac" / "estop.sh")

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


FAKE_SSH = r'''#!PYTHON
import base64, os, sys
cmd = sys.argv[-1]
log = os.environ["FAKE_LOG"]
if cmd.startswith("pwsh ") and "-EncodedCommand" in cmd:
    body = base64.b64decode(cmd.split()[-1]).decode("utf-16-le")
    kind = "PS"
else:
    body = cmd
    kind = "RAW"
with open(log, "a", encoding="utf-8") as f:
    f.write(f"=== {kind}\n{body}\n")
out = ""
if kind == "PS":
    if "'LAYOUT=pkg'" in body:
        ans = os.environ["FAKE_LAYOUT"]
        if ans == "timeout":
            sys.stderr.write("ssh: connect to host 127.0.0.1 port 22: Operation timed out\n")
            sys.exit(255)
        out = {"pkg": "LAYOUT=pkg", "legacy": "LAYOUT=legacy",
               "garbage": "pwsh : The term 'pwsh' is not recognized"}[ans]
    elif "sc.exe stop ArkRelayWatchdog" in body:
        out = "WATCHDOG=Stopped\r\nSTOP_RC=0\r\nMAIN=STOPPED"
    elif "sc.exe start ArkRelayWatchdog" in body:
        out = "WATCHDOG=Running\r\nMAIN=RUNNING"
    elif "Write-Output 'NONE'" in body:          # a kill tier
        out = "NONE\r\nGONE"
else:
    if cmd == "sc query ark-relay":
        started = "sc start ark-relay" in open(log, encoding="utf-8").read()
        out = "        STATE              : " + ("4  RUNNING" if started else "1  STOPPED")
if out:
    print(out)
'''


def rig(d: Path) -> dict:
    b = d / "bin"
    b.mkdir()
    ssh = b / "ssh"
    ssh.write_text(FAKE_SSH.replace("PYTHON", sys.executable, 1), encoding="utf-8")
    ssh.chmod(0o755)
    curl = b / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    curl.chmod(0o755)
    return {**os.environ, "PATH": f"{b}:{os.environ['PATH']}", "ARK_HOST": "127.0.0.1"}


def run(d: Path, env: dict, layout: str, *args: str) -> tuple[str, list[tuple[str, str]]]:
    """(output, [(kind, command)] the script sent over ssh, in order)."""
    log = d / f"ssh-{layout}-{'-'.join(a.strip('-') for a in args)}.log"
    log.unlink(missing_ok=True)
    r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, timeout=90,
                       env={**env, "FAKE_LOG": str(log), "FAKE_LAYOUT": layout})
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    sent = []
    if log.exists():
        for chunk in log.read_text(encoding="utf-8").split("=== ")[1:]:
            kind, _, body = chunk.partition("\n")
            sent.append((kind, body.strip()))
    return out, sent


def pkg_stop(sent):
    return [i for i, (k, b) in enumerate(sent) if k == "PS" and "sc.exe stop ArkRelayWatchdog" in b]


def pkg_start(sent):
    return [i for i, (k, b) in enumerate(sent) if k == "PS" and "sc.exe start ArkRelayWatchdog" in b]


def raw(sent, cmd):
    return [i for i, (k, b) in enumerate(sent) if k == "RAW" and b == cmd]


def first_kill(sent):
    """Index of the first kill tier (mk_kill_tier; PS_PKG_STOP has a Stop-Process of its own)."""
    return next((i for i, (k, b) in enumerate(sent) if k == "PS" and "Write-Output 'NONE'" in b), None)


with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    env = rig(d)

    for layout, why in (("timeout", "the layout question timed out"),
                        ("garbage", "the layout question came back without a LAYOUT line")):
        print(f"\n[{why}: stop the installed relay (watchdog, then the task), before AUTO-MAS is killed]")
        out, sent = run(d, env, layout, "--keep-queue")
        stops = pkg_stop(sent)
        check("installed-relay stop was sent", len(stops), 1)
        kill = first_kill(sent)
        check("it went before the first kill", bool(stops) and kill is not None and stops[0] < kill, True)
        check("no bare sc stop ark-relay", raw(sent, "sc stop ark-relay"), [])
        check("says the layout was not known", "没问到机器上是哪种中继" in out, True)
        check("says it stopped the installed one", "按安装版停" in out, True)
        check("does not say it stops the old service", "按老服务停" in out, False)
        check("reports the relay stopped", "[中继] 已确认停止" in out, True)

        print(f"\n[{why}, --restore: start the installed relay, not the old service]")
        out, sent = run(d, env, layout, "--restore")
        check("installed-relay start was sent", len(pkg_start(sent)), 1)
        check("no sc start ark-relay", raw(sent, "sc start ark-relay"), [])
        check("reports the relay running", "中继（安装版）已在运行" in out, True)

    print("\n[installed layout: as before]")
    out, sent = run(d, env, "pkg", "--keep-queue")
    check("installed-relay stop was sent", len(pkg_stop(sent)), 1)
    check("no bare sc stop ark-relay", raw(sent, "sc stop ark-relay"), [])
    check("no unknown-layout warning", "没问到机器上是哪种中继" in out, False)
    out, sent = run(d, env, "pkg", "--restore")
    check("--restore starts the installed relay", len(pkg_start(sent)), 1)
    check("--restore does not start the old service", raw(sent, "sc start ark-relay"), [])

    print("\n[the machine says legacy: the old service, and only it]")
    out, sent = run(d, env, "legacy", "--keep-queue")
    check("sc stop ark-relay was sent", len(raw(sent, "sc stop ark-relay")), 1)
    check("no installed-relay stop", pkg_stop(sent), [])
    check("reports the old service stopped", "[中继] 已确认停止" in out, True)
    out, sent = run(d, env, "legacy", "--restore")
    check("--restore sends sc start ark-relay", len(raw(sent, "sc start ark-relay")), 1)
    check("--restore does not start the installed relay", pkg_start(sent), [])
    check("--restore reports ark-relay running", "ark-relay 已在运行" in out, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
