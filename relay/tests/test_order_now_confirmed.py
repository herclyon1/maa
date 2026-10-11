"""scripts/mac/order-now.sh refuses a changing order without "confirmed": true.

2026-10-10 04:16:12 a set_master sent with order-now.sh carried no "confirmed";
the relay refused it (commands.py gate 2) and pushed 「📱 配置没改成」 to the
group. The script now stops before
sending such an order. The list of changing actions is read from the relay
(commands.MUTATING).

Nothing here reaches ntfy: HOME holds a made-up push.env and PATH starts with a
fake curl that only records that it was called and answers 200.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "mac" / "order-now.sh"
sys.path.insert(0, str(ROOT / "relay"))
from ark_relay.features.phone.commands import MUTATING  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def run(body: dict, home: str) -> tuple[int, str, bool]:
    """(exit code, output, whether the fake curl was called)."""
    sent = Path(home) / "curl-called"
    sent.unlink(missing_ok=True)
    env = {**os.environ, "HOME": home, "PATH": f"{home}/bin:{os.environ['PATH']}"}
    r = subprocess.run(["bash", str(SCRIPT), json.dumps(body, ensure_ascii=False)],
                       capture_output=True, env=env, timeout=30)
    return r.returncode, (r.stderr + r.stdout).decode("utf-8", "replace"), sent.exists()


def fake_home(home: str) -> None:
    cfg = Path(home) / ".config" / "ark"
    cfg.mkdir(parents=True)
    (cfg / "push.env").write_text("ARK_PHONE_TOPIC=test-topic-not-real\nARK_PHONE_PIN=0000\n", encoding="utf-8")
    curl = Path(home) / "bin" / "curl"
    curl.parent.mkdir()
    curl.write_text(f"#!/bin/sh\ntouch '{home}/curl-called'\nprintf 200\n", encoding="utf-8")
    curl.chmod(0o755)


with tempfile.TemporaryDirectory() as home:
    fake_home(home)
    print("[a changing order without confirmed: stopped here, not sent]")
    code, out, sent = run({"action": "set_master", "game": "鸣潮", "path": "x", "value": 2}, home)
    check("exit code non-zero", code != 0, True)
    check("says confirmed is needed", '"confirmed": true' in out, True)
    check("not sent", sent, False)

    code, out, sent = run({"action": "set_stage", "value": "1-7", "confirmed": False}, home)
    check("confirmed false is stopped too", (code != 0, sent), (True, False))

    print("\n[confirmed, or not a changing order: sent as before]")
    code, out, sent = run({"action": "set_master", "confirmed": True, "game": "鸣潮", "path": "x", "value": 2}, home)
    check("confirmed set_master is sent", (code, sent), (0, True))
    code, out, sent = run({"action": "tacet_shots", "on": False}, home)
    check("a non-changing order needs no confirmed", (code, sent), (0, True))

    print("\n[the list is the relay's own]")
    check("set_master, set_config and run_now are changing orders", {"set_master", "set_config", "run_now"} <= MUTATING, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
