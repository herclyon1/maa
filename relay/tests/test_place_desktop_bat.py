"""modes.set_skip_shutdown writes state.json through StateStore and survives concurrent relay writes."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay"))
from ark_relay.core.statestore import StateStore  # noqa: E402
from ark_relay.features.modes import modes  # noqa: E402

fails = []


def require(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok or not detail else f": {detail}"))
    if not ok:
        fails.append(name)


with tempfile.TemporaryDirectory() as tmp:
    st = Path(tmp)
    relay_store = StateStore(st)
    relay_store.set("versions", "code", "1")
    ok, msg = modes.set_skip_shutdown(st, True)
    require("switch receipt is the relay's own wording",
            ok and msg.startswith("已记下「下次跑完不关机」"), msg)
    require("a running relay sees the mark at once (skip_armed, fresh store)", modes.skip_armed(st))
    require("... and through its long-lived store", relay_store.get("modes", "skip_next_shutdown") is True)
    relay_store.set("versions", "code", "2")
    require("the relay's next write keeps the mark", modes.skip_armed(st)
            and StateStore(st).get("versions", "code") == "2")
    modes.set_skip_shutdown(st, False)
    require("pulling it back is seen at once too", not modes.skip_armed(st)
            and relay_store.get("modes", "skip_next_shutdown") is None)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
