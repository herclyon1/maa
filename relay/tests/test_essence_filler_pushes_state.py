"""After essence.step switches MaaEnd to filler mode, the phone page is told (11-08 [D-08])."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.essence import essence

FAILED = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(label)


class Store:
    def __init__(self):
        self.d = {(essence.SECTION, essence.PENDING): {"run_id": "r1", "day": "2026-11-08"}}

    def get(self, s, k):
        return self.d.get((s, k))

    def set(self, s, k, v):
        self.d[(s, k)] = v

    def pop(self, s, k):
        self.d.pop((s, k), None)


pushed = []
eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=None), _scripts_running=lambda: False,
                            state=types.SimpleNamespace(mark_raw=lambda *a: None),
                            _push_state=pushed.append)
store = Store()
essence._store = lambda e: store
essence.busy = lambda cfg, running: ""
essence.apply = lambda cfg, fn, label: types.SimpleNamespace(changed=True, names=[], before="a", after="b", note="")
essence.weapon_names = lambda d, n: []
essence.step(eng)
check("switched: phone state pushed once", pushed, ["基质切刷垫子"])

print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
sys.exit(1 if FAILED else 0)
