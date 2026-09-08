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
    "relay/ark_relay/gameupdate_games.py": "ark.gameupdate",
    "relay/ark_relay/okww_patches/core.py": "ark.okww_patch",
    "relay/ark_relay/okww_patches/domain.py": "ark.okww_patch",
    "relay/ark_relay/okww_patches/nest.py": "ark.okww_patch",
    "relay/ark_relay/okww_patches/starve.py": "ark.okww_patch",
    "relay/ark_relay/preupdate_common.py": "ark.preupdate",
    "relay/tests/test_okww_patch.py": "ark.okww_patch",
    # 2026-09-08 按接缝拆出来的几块，沿用母模块的日志名——翻日志时它们本来就该
    # 和母模块混在一起看，分开反而要记住去 grep 两个名字。
    "relay/ark_relay/collector_okww.py": "ark.collector",
    "relay/ark_relay/collector_maa.py": "ark.collector",
    "relay/ark_relay/collector_maaend.py": "ark.collector",
    "relay/boot_stages.py": "ark.service",
}
PAT = re.compile(r'getLogger\("([^"]+)"\)')


def main(root: str = "relay") -> int:
    bad = []
    for f in sorted(Path(root).rglob("*.py")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not (m := PAT.search(line)):
                continue
            got, want = m.group(1), "ark." + f.stem
            if got in (ALLOW.get(str(f)), want):
                continue
            bad.append(f"{f}:{i} 日志名 {got}，模块叫 {f.stem}，应该是 {want}")
    print("\n".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
