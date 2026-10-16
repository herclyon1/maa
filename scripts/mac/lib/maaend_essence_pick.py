"""Set which weapons MaaEnd's essence farming (基质刷取) farms toward in target mode.

    scripts/mac/winrun.sh --py scripts/mac/lib/maaend_essence_pick.py              # 玉中身 + 唤月
    scripts/mac/winrun.sh --py scripts/mac/lib/maaend_essence_pick.py <weapon id>...

Writes the AUTO-MAS MaaEnd master only (AUTO-MAS copies it into each run). Refuses while
an AUTO-MAS task runs or a make-up / collect retry holds a temporary change in the master,
and when 基质刷取 is not in target mode (目标选择): the relay switches it to filler mode
by itself once every ticked weapon is satisfied, and ticking weapons then would mean
nothing. The weapon selection becomes exactly the given ids (each weapon type on when one
of its weapons is given, off otherwise); the target mode and everything else stay. The
original is backed up beside the master (mxu-MaaEnd.json.bak-essence-pick-<time>), the
written file is read back whole. Running it again changes nothing.

Default ids (owner, 2026-10-16 16:29 Tokyo, confirmed 17:01): wpn_claym_0018 (玉中身,
already complete) and wpn_sword_0025 (唤月, ★6 one-handed sword), names from MaaEnd
v2.33.0-rc.1 locales/interface/zh_cn.json.
"""
import sys
from relay_code import DATA, use_relay_code
use_relay_code()
from ark_relay.__main__ import _load_dotenv  # noqa: E402
_load_dotenv(DATA / ".env")
from ark_relay.core.config import Config  # noqa: E402
from ark_relay.core.engine import Engine  # noqa: E402
from ark_relay.features.essence import essence  # noqa: E402

DEFAULT = ["wpn_claym_0018", "wpn_sword_0025"]


def main(argv: list[str]) -> int:
    ids = argv or DEFAULT
    cfg = Config()
    if why := essence.busy(cfg, Engine._scripts_running):
        print(f"REFUSED: {why} - nothing written; run again when it is idle")
        return 2
    try:
        res = essence.apply(cfg, essence.pick_weapons, "pick", ids)
    except essence.Refused as exc:
        print(f"REFUSED: {exc} - nothing written")
        return 2
    print("weapons asked:", ids, essence.weapon_names(cfg.maaend_dir, ids))
    print("before:", res.before)
    print("after: ", res.after)
    print("written, read back whole; backup:" if res.changed else "unchanged:", res.note)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
