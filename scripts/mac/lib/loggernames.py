"""每个模块的日志名必须等于 ark.<模块名>。

2026-09-08 审出来的：selfupdate.py 打的日志叫 `ark.update`、statestore.py 叫 `ark.state`、
sanity_plan.py 叫 `ark.sanity`。出事时按模块名去 grep 日志，一条都搜不到，
很容易得出「这个模块根本没跑」的错误结论。docs/PITFALLS.md 里那条 WinError 10054
当年就是这么被多找了一阵子。

故意共用一个名字的几家写在 ALLOW 里：okww_patches 四个模块算一家补丁、
preupdate_common 跟着 preupdate 一家、
gameupdate_games 跟着 gameupdate 一家（三家游戏的更新流程从它拆出来，日志还是同一件事）、
__main__ 用根名 ark。
"""
import re
import sys
from pathlib import Path

ALLOW = {
    "relay/ark_relay/__main__.py": "ark",
    "relay/ark_relay/features/gameupdate/gameupdate_games.py": "ark.gameupdate",
    "relay/ark_relay/features/gameupdate/gameupdate_maaend.py": "ark.gameupdate",
    "relay/ark_relay/features/okww_patch/okww_patches/core.py": "ark.okww_patch",
    "relay/ark_relay/features/okww_patch/okww_patches/domain.py": "ark.okww_patch",
    "relay/ark_relay/features/okww_patch/okww_patches/nest.py": "ark.okww_patch",
    "relay/ark_relay/features/okww_patch/okww_patches/starve.py": "ark.okww_patch",
    "relay/ark_relay/features/preupdate/preupdate_common.py": "ark.preupdate",
    "relay/tests/test_okww_patch.py": "ark.okww_patch",
    # 2026-09-08 按接缝拆出来的几块，沿用母模块的日志名——翻日志时它们本来就该
    # 和母模块混在一起看，分开反而要记住去 grep 两个名字。
    "relay/ark_relay/features/verify/collector_okww.py": "ark.collector",
    "relay/ark_relay/features/verify/collector_maa.py": "ark.collector",
    "relay/ark_relay/features/verify/collector_maaend.py": "ark.collector",
    "relay/boot_stages.py": "ark.service",
    # Split out of service.py / boot_stages.py (2026-10-11): their lines were always ark.service,
    # and the machine checks and tests read them there.
    "relay/ark_relay/features/host/automas_keeper.py": "ark.service",
    "relay/ark_relay/features/host/day_roll.py": "ark.service",
    "relay/ark_relay/features/host/dirwatch.py": "ark.service",
    "relay/ark_relay/features/host/mainloop.py": "ark.service",
    "relay/ark_relay/features/host/procwatch.py": "ark.service",
    "relay/ark_relay/features/phone/phone_channel.py": "ark.service",
    # The ledger was the module ark_relay.core until 2026-10-11 and its log name stays ark.core.
    "relay/ark_relay/core/ledger.py": "ark.core",
    # Split out of mastercfg.py by game; same log name as mastercfg.
    "relay/ark_relay/core/mastercfg_maa.py": "ark.mastercfg",
    "relay/ark_relay/core/mastercfg_okww.py": "ark.mastercfg",
    # Split out of alarm/handle.py (2026-10-11). The run handler keeps one log name, and
    # tests listen on it: test_every_failure_pushed.py and test_recovered_daily_only.py
    # attach to "ark.handle", so a split-out module logging elsewhere would go unheard.
    "relay/ark_relay/features/alarm/gamelogs.py": "ark.handle",
    "relay/ark_relay/features/alarm/manualstops.py": "ark.handle",
    "relay/ark_relay/features/alarm/pushes.py": "ark.handle",
    "relay/ark_relay/features/alarm/records.py": "ark.handle",
    "relay/ark_relay/features/alarm/runchecks.py": "ark.handle",
    "relay/ark_relay/features/alarm/verdict.py": "ark.handle",
    # Split out of makeup.py; test_every_failure_pushed.py listens on "ark.makeup".
    "relay/ark_relay/features/makeup/marker.py": "ark.makeup",
    # Split out of phone.py (ee422d65): the phone channel keeps its one log name.
    "relay/ark_relay/features/phone/cmdqueue.py": "ark.phone",
    "relay/ark_relay/features/phone/heartbeat.py": "ark.phone",
    "relay/ark_relay/features/phone/mailbox.py": "ark.phone",
    "relay/ark_relay/features/phone/mas_labels.py": "ark.phone",
    "relay/ark_relay/features/phone/quota.py": "ark.phone",
    "relay/ark_relay/features/phone/wire.py": "ark.phone",
    # Split out of phone/commands.py (bd4b4812); same log name as commands.
    "relay/ark_relay/features/phone/redbutton.py": "ark.commands",
    # The packaged install (packaging/): the app host logs as ark.app, its stop path as
    # ark.app.stop, the watchdog's shutdown push (stop-push) as ark.app.stop_push, and the
    # version-folder layout as ark.pkg.
    "relay/app_main.py": ("ark.app", "ark.app.stop", "ark.app.stop_push"),
    "relay/pkg_layout.py": "ark.pkg",
    # Throwaway loggers a test builds for itself; nothing outside the test reads them.
    "relay/tests/test_stop_during_boot.py": ("ark.test", "ark.test.stopwake"),
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
