"""Old module paths keep importing after the 2026-10-11 move into core/ and features/.

`import ark_relay.notify` (and `ark_relay.machinechecks.system`, any depth) resolves to the
module now at its new path - the same module object, so a test that patches `notify._rng`
patches the module the relay uses. The old `ark_relay.core` (the ledger) is the exception:
`ark_relay.core` is now the shared-parts package, so the ledger is `ark_relay.core.ledger`.
"""
import importlib
import importlib.abc
import importlib.util
import sys

MOVED = {
    "alertlog": "features.alarm.alertlog",
    "annihilation": "features.weekly.annihilation",
    "banners": "features.banners.banners",
    "collect_retry": "features.makeup.collect_retry",
    "collect_watch": "features.run.collect_watch",
    "collector": "core.collector",
    "collector_maa": "features.verify.collector_maa",
    "collector_maaend": "features.verify.collector_maaend",
    "collector_okww": "features.verify.collector_okww",
    "commands": "features.phone.commands",
    "config": "core.config",
    "desktop": "core.desktop",
    "echofarm": "features.echofarm.echofarm",
    "efstatus": "features.maintenance.efstatus",
    "engine": "core.engine",
    "error_evidence": "features.evidence.error_evidence",
    "errwatch": "features.alarm.errwatch",
    "evidence": "features.evidence.evidence",
    "gameupdate": "features.gameupdate.gameupdate",
    "gameupdate_games": "features.gameupdate.gameupdate_games",
    "garden": "features.weekly.garden",
    "handle": "features.alarm.handle",
    "inbox": "features.phone.inbox",
    "known_fixed": "features.alarm.known_fixed",
    "logfile": "core.logfile",
    "maaend": "features.phone.maaend",
    "maaend_watchdog": "features.run.maaend_watchdog",
    "machinecheck": "features.selfcheck.machinecheck",
    "machinechecks": "features.selfcheck.machinechecks",
    "maintenance": "features.maintenance.maintenance",
    "makeup": "features.makeup.makeup",
    "mastercfg": "core.mastercfg",
    "missed": "features.alarm.missed",
    "modes": "features.modes.modes",
    "monthcard": "features.phone.monthcard",
    "names": "core.names",
    "notify": "core.notify",
    "okww_overlay": "features.okww_patch.okww_overlay",
    "okww_patch": "features.okww_patch.okww_patch",
    "okww_patches": "features.okww_patch.okww_patches",
    "outcome": "features.verify.outcome",
    "phone": "features.phone.phone",
    "plan": "core.plan",
    "preupdate": "features.preupdate.preupdate",
    "preupdate_automas": "features.preupdate.preupdate_automas",
    "preupdate_common": "features.preupdate.preupdate_common",
    "preupdate_maa": "features.preupdate.preupdate_maa",
    "preupdate_maaend": "features.preupdate.preupdate_maaend",
    "preupdate_okww": "features.preupdate.preupdate_okww",
    "procs": "core.procs",
    "queues": "features.schedule.queues",
    "replay": "features.selfcheck.replay",
    "report": "features.report.report",
    "resources": "features.phone.resources",
    "runwatch": "features.run.runwatch",
    "sanity_plan": "features.weekly.sanity_plan",
    "scoreboard": "features.report.scoreboard",
    "selfcheck": "features.selfcheck.selfcheck",
    "selfupdate": "features.selfupdate.selfupdate",
    "shutdown": "features.shutdown.shutdown",
    "skland": "core.skland",
    "snapshot": "features.phone.snapshot",
    "stagegate": "features.schedule.stagegate",
    "statestore": "core.statestore",
    "summary": "core.summary",
    "task_shots": "features.evidence.task_shots",
    "texts": "core.texts",
    "transport": "core.transport",
    "trigger": "features.guard.trigger",
    "unresolved": "features.alarm.unresolved",
    "watch": "core.watch",
    "weeklyboss": "features.weekly.weeklyboss",
    "wuwa_boss": "core.wuwa_boss",
    "wuwa_forgery": "core.wuwa_forgery",
    "wuwa_tacet": "core.wuwa_tacet",
}


def new_name(name: str) -> "str | None":
    """The module's new dotted name, or None when `name` was not moved."""
    parts = name.split(".")
    if len(parts) < 2 or parts[0] != "ark_relay" or parts[1] not in MOVED:
        return None
    return ".".join(["ark_relay", *MOVED[parts[1]].split("."), *parts[2:]])


class _OldPath(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, name, path=None, target=None):
        new = new_name(name)
        if new is None:
            return None
        return importlib.util.spec_from_loader(name, self, origin=new)

    def create_module(self, spec):
        return importlib.import_module(spec.origin)

    def exec_module(self, module):
        pass


def install() -> None:
    if not any(isinstance(f, _OldPath) for f in sys.meta_path):
        sys.meta_path.insert(0, _OldPath())
