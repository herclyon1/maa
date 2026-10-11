"""An upstream export change is announced once, not on every boot.

boot_stages._stage_evidence_sources compared the pinned upstream files on each
boot and pushed 「上游导出代码变了」 each time, so one upstream commit reached the
user again every morning and evening until the pin was updated. The stage now
records the fingerprint it announced in state/evidence-source-notified.json;
the same fingerprint stays quiet, a new one is announced again.

Since 2026-10-11 the announcement is a red item in the technical log (our work: the
evidence bundling has to be re-checked), not a Server酱 notice to him; the stage's
WARNING still reaches the group on every boot until the pin is renewed. The user,
2026-10-11 17:44: 「报警的东西第一时间交到你们这边去修，不是甩给人去看」.
"""
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for name in ("win32serviceutil", "win32service", "win32event", "win32api",
             "win32con", "win32file", "servicemanager", "win32process",
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(name, _Stub(name))

import boot_stages  # noqa: E402
from ark_relay import evidence  # noqa: E402


class _Log:
    def __init__(self): self.lines = []
    def warning(self, *a): self.lines.append(a[0] % a[1:])
    def info(self, *a): self.lines.append(a[0] % a[1:] if len(a) > 1 else a[0])
    def exception(self, *a): self.lines.append(a[0])


class _Notifier:
    def __init__(self): self.sent = []
    def send(self, title, body, *a, **k): self.sent.append((title, body))


def run(state, upstream):
    def fake_check():
        evidence.LAST_SEEN.clear()
        evidence.LAST_SEEN.update(upstream)
        return list(upstream), []
    evidence.check_sources, saved = fake_check, evidence.check_sources
    try:
        cfg = types.SimpleNamespace(state_dir=state)
        n, log = _Notifier(), _Log()
        boot_stages._stage_evidence_sources(cfg, n, log)
        return n, log
    finally:
        evidence.check_sources = saved


from ark_relay.core import techlog  # noqa: E402


def new_reds(d, before):
    import glob  # noqa: PLC0415
    text = "".join(Path(f).read_text(encoding="utf-8") for f in sorted(glob.glob(str(techlog.tech_dir(d) / "*.md"))))
    got = techlog.unhandled(text)
    return got[len(before):], got


with tempfile.TemporaryDirectory() as root:
    d = str(Path(root) / "state")
    Path(d).mkdir()
    n, log = run(d, {"MAA": "aaa"})
    fresh, seen = new_reds(d, [])
    assert n.sent == [], n.sent                                   # nothing to him
    assert len(fresh) == 1 and "MAA" in fresh[0][1], fresh        # one red item for us
    assert any("上游导出代码变了" in x for x in log.lines), log.lines   # the WARNING for the group
    n, log = run(d, {"MAA": "aaa"})
    fresh, seen = new_reds(d, seen)
    assert n.sent == [] and fresh == [], (n.sent, fresh)
    assert any("都已报过" in x for x in log.lines), log.lines
    n, _ = run(d, {"MAA": "bbb"})
    fresh, seen = new_reds(d, seen)
    assert len(fresh) == 1 and "MAA" in fresh[0][1], fresh
    n, _ = run(d, {"MAA": "bbb", "MaaEnd": "ccc"})
    fresh, seen = new_reds(d, seen)
    assert len(fresh) == 1 and "MaaEnd" in fresh[0][1] and "MAA、" not in fresh[0][1], fresh
    n, _ = run(d, {})
    fresh, seen = new_reds(d, seen)
    assert n.sent == [] and fresh == []

print("all checks passed")
