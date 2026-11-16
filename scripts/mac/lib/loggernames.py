"""每个模块的日志名必须等于 ark.<模块名>（或显式登记在 ALLOW 中保留历史报警部件名）。"""
import re
import sys
from pathlib import Path

ALLOW = {
    "relay/app_main.py": ("ark.app", "ark.app.stop", "ark.app.stop_push"),
    "relay/ark_relay/__main__.py": "ark",
    "relay/ark_relay/core/desktop.py": "ark.procs",
    "relay/ark_relay/core/ledger.py": "ark.core",
    "relay/ark_relay/core/notify.py": "ark.netretry",
    "relay/ark_relay/core/statestore.py": ("ark.logfile", "ark.techlog"),
    "relay/ark_relay/features/annihilation.py": ("ark.weekgate", "ark.garden"),
    "relay/ark_relay/features/automas_keeper.py": "ark.service",
    "relay/ark_relay/features/efstart.py": "ark.efstart_setup",
    "relay/ark_relay/features/errwatch.py": "ark.alertlog",
    "relay/ark_relay/features/evidence.py": "ark.error_evidence",
    "relay/ark_relay/features/gameupdate_games.py": "ark.gameupdate",
    "relay/ark_relay/features/handle.py": ("ark.missed", "ark.unresolved"),
    "relay/ark_relay/features/machinechecks.py": ("ark.system", "ark.phone_banners", "ark.runs"),
    "relay/ark_relay/features/outcome.py": ("ark.gamelog_errors", "ark.collector"),
    "relay/ark_relay/features/phone.py": ("ark.monthcard", "ark.inbox", "ark.service"),
    "relay/ark_relay/features/procwatch.py": "ark.service",
    "relay/ark_relay/features/redbutton.py": "ark.commands",
    "relay/ark_relay/features/selfcheck.py": ("ark.shiftcheck", "ark.tape"),
    "relay/boot_stages.py": "ark.service",
    "relay/pkg_layout.py": "ark.pkg",
    "relay/tests/test_boot.py": ("ark.test", "ark.test.stopwake"),
}
PAT = re.compile(r'getLogger\("([^"]+)"\)')


def main(root: str = "relay") -> int:
    bad = []
    for f in sorted(Path(root).rglob("*.py")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not (m := PAT.search(line)):
                continue
            got, want = m.group(1), "ark." + f.stem
            allowed = ALLOW.get(str(f), ())
            if got == want or got in ((allowed,) if isinstance(allowed, str) else allowed):
                continue
            bad.append(f"{f}:{i} 日志名 {got}，模块叫 {f.stem}，应该是 {want}")
    print("\n".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
