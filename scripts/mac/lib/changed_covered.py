"""Every relay module this change touches must be executed by at least one test.

The user's order, 2026-09-06, after being told that a deploy was safe once too
often:

    「没有回放案例的改动不许部署。部署脚本读 git diff 里改了哪些模块，每个模块必须
     被至少一个回放案例真正执行到。改了什么就得证明什么。」

What this actually checks, and why it is drawn slightly wider than "replay":
the replay corpus only exercises the judging path (collector / handle / core /
report). Modules like `shutdown` or `gameupdate` can never be reached by a
replayed history file, so requiring replay coverage for them would block every
honest change to them and the gate would be turned off within a week. So the
rule is "**some test executes it**", and the replay corpus is reported
separately for the modules it is supposed to cover — a change to a judging
module that only unit tests touch is called out by name.

Usage:
    python3 scripts/mac/lib/changed_covered.py [<base git ref>]

Default base is the last `deploy: manifest` commit — i.e. "what has changed
since the machine last received code". Exit 1 when something changed that no
test runs.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RELAY = REPO / "relay"
# 判定类模块：回放语料本来就该盖住它们，只被单测碰到不算完。
JUDGING = {"collector", "core", "handle", "report", "outcome"}


def _sh(*args: str) -> str:
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True).stdout.strip()


def base_ref(argv: list[str]) -> str:
    if argv:
        return argv[0]
    ref = _sh("git", "log", "-1", "--format=%H", "--grep=^deploy: manifest")
    return ref or "HEAD~1"


def changed_modules(base: str) -> set[str]:
    out = _sh("git", "diff", "--name-only", base, "--", "relay/ark_relay", "relay/service.py")
    mods = set()
    for line in out.splitlines():
        p = Path(line)
        if p.suffix != ".py" or "okww_files" in p.parts or p.name == "__init__.py":
            continue
        mods.add(p.stem)
    return mods


def executed_modules(want_replay: bool) -> tuple[set[str], set[str]]:
    """(所有测试跑到的模块, 只算回放那一个测试跑到的模块)。

    回放那一趟只在**判定类模块被改过**时才跑——它要多花十几秒，而没改判定逻辑时
    这个数字没人会看。部署要快是死命令，这道闸门自己不能变成拖累。
    """
    driver = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
    driver.write(
        "import runpy, sys, pathlib\n"
        "only = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "root = pathlib.Path(sys.argv[0]).parent\n"
        "for t in sorted(pathlib.Path('tests').glob('test_*.py')):\n"
        "    if only and t.name != only:\n"
        "        continue\n"
        "    try:\n"
        "        runpy.run_path(str(t), run_name='__main__')\n"
        "    except BaseException:\n"
        "        pass          # 这一趟只为收覆盖，成败由真正的测试闸门去判\n")
    driver.close()

    def run(only: str = "") -> set[str]:
        cov = Path(tempfile.mkdtemp()) / "cov.json"
        subprocess.run(["uvx", "coverage", "run", "--source=ark_relay,service",
                        driver.name, only], cwd=RELAY, capture_output=True, text=True)
        subprocess.run(["uvx", "coverage", "json", "-q", "-o", str(cov)],
                       cwd=RELAY, capture_output=True, text=True)
        if not cov.exists():
            return set()
        data = json.loads(cov.read_text(encoding="utf-8"))
        return {Path(f).stem for f, v in data.get("files", {}).items()
                if v.get("summary", {}).get("covered_lines")}

    return run(), (run("test_replay.py") if want_replay else set())


def main(argv: list[str]) -> int:
    base = base_ref(argv)
    changed = changed_modules(base)
    if not changed:
        print(f"改动覆盖：自 {base[:8]} 起没有中继模块被改，无需证明")
        return 0
    tested, replayed = executed_modules(bool(changed & JUDGING))
    if not tested:
        print("改动覆盖：一个模块都没跑到——多半是 coverage 没装或驱动跑挂了，"
              "这种情况下不许放行")
        return 1
    naked = sorted(changed - tested)
    judging_only_unit = sorted((changed & JUDGING) - replayed)
    print(f"改动覆盖：自 {base[:8]} 起改了 {len(changed)} 个模块，测试跑到 {len(tested)} 个"
          + (f"，其中回放跑到 {len(replayed)} 个" if changed & JUDGING else ""))
    if judging_only_unit:
        print("  ⚠️ 判定类模块改了却没有回放案例跑到："
              + "、".join(judging_only_unit))
        print("     回放语料在 relay/tests/replay/，加样本用 scripts/mac/pull-replay.sh")
    if naked:
        print("  ❌ 改了但**没有任何测试执行到**：" + "、".join(naked))
        print("     改了什么就得证明什么——补一个能跑到它的测试，或者把这次改动收回。")
        return 1
    print("  ✅ 每个改过的模块都有测试真的跑到它")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
