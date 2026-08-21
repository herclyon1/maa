"""On a cold boot the relay starts before Windows has DNS. Measured
2026-08-21 21:20:19 - one second after service start, all four update doors
answered `[Errno 11001] getaddrinfo failed`, and the boot-window update was
abandoned before the doors were ever reachable.
"""
import importlib.util, socket, sys, time, types
from pathlib import Path

# service.py imports pywin32, which does not exist on this machine. Load just
# the function under test by exec'ing its source in a namespace of its own.
SRC = (Path(__file__).resolve().parents[1] / "service.py").read_text(encoding="utf-8")
start = SRC.index("def _wait_for_network")
end = SRC.index("def _start_process_watch")
ns = {"time": time, "socket": socket}
exec(compile(SRC[start:end], "service.py", "exec"), ns)   # noqa: S102
wait = ns["_wait_for_network"]

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

class Log:
    def __init__(self): self.lines = []
    def info(self, msg, *a): self.lines.append(("info", msg % a if a else msg))
    def warning(self, msg, *a): self.lines.append(("warn", msg % a if a else msg))

real = socket.getaddrinfo

print("[network already up: returns at once, says nothing]")
lg = Log()
t0 = time.monotonic()
check("returns True", wait(lg, timeout=5), True)
check("immediate", time.monotonic() - t0 < 0.5, True)
check("silent", lg.lines, [])

print("\n[DNS down at first, up on the third try]")
calls = []
def flaky(*a, **kw):
    calls.append(1)
    if len(calls) < 3:
        raise OSError(11001, "getaddrinfo failed")
    return real(*a, **kw)
socket.getaddrinfo = flaky
ns["socket"] = socket
lg = Log()
check("returns True", wait(lg, timeout=30), True)
check("kept trying", len(calls) >= 3, True)
check("said it waited", any("DNS 还没起来" in m for _, m in lg.lines), True)
check("said it recovered", any("网络已就绪" in m for _, m in lg.lines), True)

print("\n[DNS never comes up: gives up inside the budget]")
socket.getaddrinfo = lambda *a, **kw: (_ for _ in ()).throw(OSError(11001, "getaddrinfo failed"))
ns["socket"] = socket
lg = Log()
t0 = time.monotonic()
check("returns False", wait(lg, timeout=6), False)
spent = time.monotonic() - t0
check("respected the budget", 5.0 <= spent <= 9.0, True)
check("warned", any(lv == "warn" for lv, _ in lg.lines), True)

socket.getaddrinfo = real
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
