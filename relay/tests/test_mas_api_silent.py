"""mas-api.py must exit non-zero when AUTO-MAS answered with an HTTP error.

Silent-failure audit rows scripts/mac/mas-api.py:50 and :58: an HTTP 4xx/5xx
came back as {"__status", "__detail"} or {"__status", "__body"}, was printed,
and the tool exited 0.
"""
import contextlib
import importlib.util
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("mas_api", ROOT / "scripts" / "mac" / "mas-api.py")
mas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mas)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def run(answer):
    mas.call = lambda path, body=None, method="POST": answer
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = mas.main(["post", "/api/scripts/get"])
    return rc, out.getvalue()


print("[HTTP error with a JSON body]")
rc, out = run({"__status": 422, "__detail": {"detail": "field required"}})
check("the detail is printed", "field required" in out, True)
check("exit 1", rc, 1)

print("[HTTP error with a non-JSON body]")
rc, out = run({"__status": 500, "__body": "Internal Server Error"})
check("the body is printed", "Internal Server Error" in out, True)
check("exit 1 (non-JSON body)", rc, 1)

print("[normal answers stay 0]")
check("a dict answer exits 0", run({"code": 200, "data": {}})[0], 0)
check("a list answer exits 0", run([{"a": 1}])[0], 0)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
