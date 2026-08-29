"""补丁必须能更新自己贴过的旧版本。

2026-08-29：我改了 `NightmareNestTask.patched.py`（把三义合一的
「指定点位都已打满」拆成三种），部署跑完显示成功，但补丁**根本没贴上去**——
护栏只认「上游原版」和「当前这份」，现场那份是我们的**旧版**补丁，
两边都不是，于是被判成「有人手改过」而拒绝覆盖。
部署脚本照常报成功，只在服务日志里留了一行 warning。

原有的 `_NEST_KNOWN_OURS` 哈希表能解决，但它要求**每次改补丁都手动补一条**，
这次就是忘了。所以改成认「我方标记」：上游源码里绝不会出现
`Only Farm These Nests`（我们自己造的配置常量），见到它就说明是我们贴的。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import okww_patch as P  # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def _root(tmp: Path, content: bytes) -> Path:
    f = tmp.joinpath(*P._SRC, "NightmareNestTask.py")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(content)
    return tmp


def main() -> int:
    patched = P._NEST_PATCHED.read_bytes()
    upstream = P._NEST_UPSTREAM.read_bytes()

    print("=== 我方标记 ===")
    check("标记在我们那份里", P._NEST_MARKER in patched, True)
    check("标记不在上游那份里", P._NEST_MARKER in upstream, False)

    print("\n=== 贴补丁的三种局面 ===")
    with tempfile.TemporaryDirectory() as td:
        r = _root(Path(td), patched)
        check("已经是最新版 → 什么都不做", P._apply_nest(r), [])

    with tempfile.TemporaryDirectory() as td:
        r = _root(Path(td), upstream)
        P._apply_nest(r)
        got = r.joinpath(*P._SRC, "NightmareNestTask.py").read_bytes()
        check("上游原版 → 贴成我们这份", got == patched, True)

    with tempfile.TemporaryDirectory() as td:
        # 我们的旧版：带标记，但内容和最新版不同
        old_ours = patched.replace(b"seen_blacklisted", b"seen_blacklisted_OLD")
        assert old_ours != patched
        r = _root(Path(td), old_ours)
        P._apply_nest(r)
        got = r.joinpath(*P._SRC, "NightmareNestTask.py").read_bytes()
        check("我们的旧版 → 覆盖成最新版（这次就是这里卡住的）",
              got == patched, True)

    with tempfile.TemporaryDirectory() as td:
        # 既没有标记、也不是上游 → 有人手改过，必须停手
        stranger = upstream + b"\n# somebody else edited this\n"
        r = _root(Path(td), stranger)
        msgs = P._apply_nest(r)
        got = r.joinpath(*P._SRC, "NightmareNestTask.py").read_bytes()
        check("陌生内容 → 不覆盖", got == stranger, True)
        check("陌生内容 → 要报出来", bool(msgs), True)

    print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
