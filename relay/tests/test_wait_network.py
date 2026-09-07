"""On a cold boot the relay starts before Windows has DNS. Measured
2026-08-21 21:20:19 - one second after service start, all four update doors
answered `[Errno 11001] getaddrinfo failed`, and the boot-window update was
abandoned before the doors were ever reachable.

2026-09-08：这个测试原来真去解析 raw.githubusercontent.com、真 sleep，跑一次 12 秒，
是全套里最慢的一个（第二名的两倍），而且没网就挂。现在用假时钟和假解析器——
不碰网络、瞬间跑完，等待时长也变成可精确断言的。
"""
import socket, sys, time, types
from pathlib import Path

# service.py imports pywin32, which does not exist on this machine. Load just
# the function under test by exec'ing its source in a namespace of its own.
SRC = (Path(__file__).resolve().parents[1] / "service.py").read_text(encoding="utf-8")
start = SRC.index("def _wait_for_network")
end = SRC.index("def _start_process_watch")


class Clock:
    """假时钟：sleep 只是把指针往前拨，不真等。"""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def load(clock):
    """按给定时钟装一份被测函数。它自己 `import socket`，所以解析器要打真模块。"""
    ns = {"time": types.SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep)}
    exec(compile(SRC[start:end], "service.py", "exec"), ns)   # noqa: S102
    return ns["_wait_for_network"]


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
FAKE_OK = [(2, 1, 6, "", ("140.82.114.4", 443))]

try:
    print("[network already up: returns at once, says nothing]")
    socket.getaddrinfo = lambda *a, **kw: FAKE_OK
    clock, lg = Clock(), Log()
    check("returns True", load(clock)(lg, timeout=5), True)
    check("immediate", clock.slept, [])
    check("silent", lg.lines, [])

    print("\n[DNS down at first, up on the third try]")
    calls = []
    def flaky(*a, **kw):
        calls.append(1)
        if len(calls) < 3:
            raise OSError(11001, "getaddrinfo failed")
        return FAKE_OK
    socket.getaddrinfo = flaky
    clock, lg = Clock(), Log()
    check("returns True", load(clock)(lg, timeout=30), True)
    check("kept trying", len(calls), 3)
    check("退避是 2 秒然后 4 秒", clock.slept, [2.0, 4.0])
    check("said it waited", any("DNS 还没起来" in m for _, m in lg.lines), True)
    check("said it recovered", any("网络已就绪" in m for _, m in lg.lines), True)

    print("\n[DNS never comes up: gives up inside the budget]")
    socket.getaddrinfo = lambda *a, **kw: (_ for _ in ()).throw(OSError(11001, "getaddrinfo failed"))
    clock, lg = Clock(), Log()
    check("returns False", load(clock)(lg, timeout=6), False)
    check("一秒都没超出预算", sum(clock.slept) <= 6.0, True)
    check("最后一次等待被预算截断，不是整轮翻倍", clock.slept, [2.0, 4.0])
    check("warned", any(lv == "warn" for lv, _ in lg.lines), True)
finally:
    socket.getaddrinfo = real

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
