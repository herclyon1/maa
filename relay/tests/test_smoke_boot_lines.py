"""The deploy smoke reads every relay.log line written since the relay's start.

scripts/windows/smoke.py looked for the start line, and for errors after it, only in
the last 60 lines of relay.log. A boot that wrote more than 60 lines before the smoke
ran had its first errors cut off: 09-09 12:57:24 (relay.log 15852 on the machine copy)
logged 「启动时贴 OK-WW 补丁失败」 one line after the start, then 108 more lines; the
smoke would have seen none of the start-time failure. The fixture is those real lines,
plus the previous process's last error, which must not count.

The script runs as it does on the machine (a subprocess, read-only); --data points its
data folder (`C:\\ProgramData\\ark-relay` on the machine) at a temporary one, and --root
at an empty package, so the import / state / inbox parts fail on their own and touch
no network. Only the relay.log part is asserted.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "scripts" / "windows" / "smoke.py"
FIX = Path(__file__).resolve().parent / "fixtures" / "relay-0909-boot-smoke.log"

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def run(log_text: str) -> str:
    work = tmpdir()
    # The script's DATA, given with --data. Until 10-13 it was a relative folder named
    # C:\ProgramData\ark-relay under the cwd, which on Windows is the real absolute
    # folder: the first run wrote the runner's own ProgramData, the second failed with
    # FileExistsError (run 38360295330).
    data = work / "data"
    data.mkdir()
    (data / "relay.log").write_text(log_text, encoding="utf-8")
    code = work / "code"
    (code / "ark_relay").mkdir(parents=True)
    (code / "ark_relay" / "__init__.py").write_text("", encoding="utf-8")
    r = subprocess.run([sys.executable, "-X", "utf8", str(SMOKE), f"--root={code}", f"--data={data}"],
                       cwd=work, capture_output=True, text=True, encoding="utf-8", timeout=60)
    return r.stdout


lines = FIX.read_text(encoding="utf-8").splitlines()
boot = next(i for i, ln in enumerate(lines) if "服务模式启动" in ln)
since_boot = len(lines) - boot

print("[09-09 12:57:24: more than 60 lines since the start]")
check("the fixture has more than 60 lines from the start on", since_boot > 60, True)
out = run(FIX.read_text(encoding="utf-8"))
check("every line from the start on is read", f"SMOKE 启动后日志 {since_boot} 行" in out, True)
check("the start-time failure one line after the start is reported",
      "启动后日志里有报错：09-09 12:57:24 ERROR   ark.service  启动时贴 OK-WW 补丁失败" in out, True)
check("the previous process's error (12:57:20, before the start) is not",
      "09-09 12:57:20" in out, False)
check("so the smoke fails", "SMOKE_FAIL" in out, True)

print("\n[no start line in the file: the last 60 lines, as before]")
out = run("\n".join(ln for ln in lines if "服务模式启动" not in ln) + "\n")
check("60 lines read", "SMOKE 启动后日志 60 行" in out, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
