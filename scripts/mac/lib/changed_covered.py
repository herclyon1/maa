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

import io
import json
import os
import subprocess
import tokenize
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
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


def _code_only(text: str) -> str:
    """把源码里的注释和 docstring 剥掉，只留会执行的部分。

    改注释不可能改变行为，所以不该要求为它举证。判据要精确：
    「这次改动动没动会跑的字节」，而不是「这个文件的字节变没变」。
    """
    out = []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text                      # 读不了就按「变了」算，宁可多问一句
    prev_type = tokenize.INDENT
    for tok in toks:
        if tok.type == tokenize.COMMENT:
            continue
        # 独立成句的字符串（docstring）：前一个有意义的 token 是换行/缩进
        if tok.type == tokenize.STRING and prev_type in (
                tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT):
            continue
        if tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                            tokenize.DEDENT, tokenize.ENCODING):
            out.append(tok.string)
        if tok.type not in (tokenize.COMMENT,):
            prev_type = tok.type
    return " ".join(out)


def comment_only(base: str, rel: str) -> bool:
    """这个文件相对 base 是不是只改了注释/docstring。"""
    old = subprocess.run(["git", "show", f"{base}:{rel}"], cwd=REPO,
                         capture_output=True, text=True)
    if old.returncode != 0:
        return False                     # 新文件：要举证
    now = (REPO / rel).read_text(encoding="utf-8")
    return _code_only(old.stdout) == _code_only(now)


def changed_modules(base: str) -> tuple[set[str], set[str]]:
    """(行为可能变了的模块, 只改了注释的模块)。"""
    out = _sh("git", "diff", "--name-only", base, "--", "relay/ark_relay", "relay/service.py")
    real, cosmetic = set(), set()
    for line in out.splitlines():
        p = Path(line)
        if p.suffix != ".py" or "okww_files" in p.parts or p.name == "__init__.py":
            continue
        (cosmetic if comment_only(base, line) else real).add(p.stem)
    return real, cosmetic


def executed_modules(want_replay: bool) -> tuple[set[str], set[str]]:
    """(所有测试跑到的模块, 只算回放那一个测试跑到的模块)。

    回放那一趟只在**判定类模块被改过**时才跑——它要多花十几秒，而没改判定逻辑时
    这个数字没人会看。部署要快是死命令，这道闸门自己不能变成拖累。

    用 `sys.settrace` 只收「哪个文件里有函数被调用过」，不收行号。
    2026-09-08 之前这里是 `uvx coverage run` + `uvx coverage json` 跑两趟，
    36 秒——其中一大半是 uvx 每次解析包的开销和 coverage 逐行记账，
    而我们只需要知道「这个文件有没有被执行」这一个比特。
    """
    driver = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
    driver.write(
        "import json, pathlib, runpy, sys\n"
        "only = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "out = sys.argv[2]\n"
        "hit = set()\n"
        "def tracer(frame, event, arg):\n"
        "    hit.add(frame.f_code.co_filename)\n"
        "    return None          # 只要 call 事件，不逐行跟\n"
        "tests = sorted(pathlib.Path('tests').glob('test_*.py'))\n"
        "if only.startswith('shard:'):\n"
        "    i, n = (int(x) for x in only.split(':')[1].split('/'))\n"
        "    tests = tests[i::n]\n"
        "    only = ''\n"
        "sys.settrace(tracer)\n"
        "for t in tests:\n"
        "    if only and t.name != only:\n"
        "        continue\n"
        "    try:\n"
        "        runpy.run_path(str(t), run_name='__main__')\n"
        "    except BaseException:\n"
        "        pass          # 这一趟只为收覆盖，成败由真正的测试闸门去判\n"
        "sys.settrace(None)\n"
        "pathlib.Path(out).write_text(json.dumps(sorted(hit)), encoding='utf-8')\n")
    driver.close()

    def _one(args: tuple[str, str]) -> set[str]:
        shard, out = args
        subprocess.run([sys.executable, driver.name, shard, out],
                       cwd=RELAY, capture_output=True, text=True)
        if not Path(out).exists():
            return set()
        files = json.loads(Path(out).read_text(encoding="utf-8"))
        return {Path(f).stem for f in files
                if "ark_relay" in f or Path(f).name == "service.py"}

    def run(only: str = "") -> set[str]:
        """跑一遍收覆盖。整套 90 个测试**分片并行**跑。

        2026-09-08：串行带 settrace 要 37 秒，而部署总共才三分钟出头，
        这道闸门自己就占五分之一。分成 CPU 核数那么多片，各跑各的，
        结果取并集——判据一个字没松，只是不再排队。
        """
        if only:
            d = Path(tempfile.mkdtemp())
            return _one((only, str(d / "hit.json")))
        n = max(2, min(8, (os.cpu_count() or 4)))
        d = Path(tempfile.mkdtemp())
        jobs = [(f"shard:{i}/{n}", str(d / f"hit{i}.json")) for i in range(n)]
        with ThreadPoolExecutor(max_workers=n) as pool:
            return set().union(*pool.map(_one, jobs))

    return run(), (run("test_replay.py") if want_replay else set())


def main(argv: list[str]) -> int:
    base = base_ref(argv)
    changed, cosmetic = changed_modules(base)
    if cosmetic:
        print(f"改动覆盖：{len(cosmetic)} 个模块只改了注释/docstring，不要求举证"
              f"（会执行的字节一个都没变）")
    if not changed:
        print(f"改动覆盖：自 {base[:8]} 起没有会改变行为的改动，无需证明")
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
