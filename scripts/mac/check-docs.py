#!/usr/bin/env python3
"""Verify that the documentation still matches reality.

The docs make claims. Claims rot. This turns the checkable ones into assertions
that fail loudly instead of quietly misleading whoever reads them next.

Three kinds of check:

  1. Automatic - every markdown link pointing at a file in this repo resolves,
     and the command whitelist in relay/README.md matches commands.py.
  2. Local directives - `<!-- check: repo <path> -->` in any markdown file.
  3. Remote directives - everything that needs the game machine. Skipped, not
     passed, when the host does not answer; a skip is reported as a skip.

Directives live in HTML comments next to the prose they back up:

    <!-- check: repo relay/manifest.json -->
    <!-- check: win D:\\ark\\automas -->
    <!-- check: svc ark-relay -->
    <!-- check: task AUTO-MAS_AutoStart -->
    <!-- check: json <windows json path> <key/path> <expected> -->

In a json key path, `*` matches every key at that level and they must all agree
(AUTO-MAS keys its users by uuid, and both users are supposed to match).

Usage:  ARK_HOST=<tailscale ip> scripts/mac/check-docs.py [--local]
Exit 0 only when nothing failed.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOST = os.environ.get("ARK_HOST", "")
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6"]

DIRECTIVE = re.compile(r"<!--\s*check:\s*(\w+)\s+(.*?)\s*-->")
# A markdown link whose target is a repo file: not http(s):, not an anchor.
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)#]+?)(?:#[^)]*)?\)")

fails: list[str] = []
passes = 0
skips: list[str] = []


def ok(msg: str) -> None:
    global passes  # noqa: PLW0603
    passes += 1
    print(f"  ok    {msg}")


def bad(msg: str) -> None:
    fails.append(msg)
    print(f"  FAIL  {msg}")


def skip(msg: str) -> None:
    skips.append(msg)
    print(f"  skip  {msg}")


def markdown_files() -> list[Path]:
    out = [REPO / "README.md"]
    out += sorted((REPO / "docs").glob("*.md"))
    out += [REPO / "queue" / "README.md", REPO / "relay" / "README.md"]
    return [p for p in out if p.exists()]


# ---------- 1. automatic ----------

def check_links() -> None:
    print("\n[links] markdown links that point into this repo")
    for md in markdown_files():
        for target in MD_LINK.findall(md.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("mailto:"):
                continue
            resolved = (md.parent / target).resolve()
            rel = md.relative_to(REPO)
            if resolved.exists():
                ok(f"{rel} -> {target}")
            else:
                bad(f"{rel} links to {target}, which does not exist")


def _slug(heading: str) -> str:
    """GitHub 给标题生成锚点的规则（够用的那一部分）。"""
    h = re.sub(r"`([^`]*)`", r"\1", heading)
    h = re.sub(r"\*\*|\*|~~", "", h).strip().lower()
    out = []
    for ch in h:
        if ch.isalnum() or ch in "-_" or unicodedata.category(ch).startswith("L"):
            out.append(ch)
        elif ch in " \t":
            out.append("-")
    return "".join(out)


def check_anchors() -> None:
    """`[文字](别的文件.md#小节)` 里的小节必须真的存在。

    2026-09-08 加的：那天把 docs 全部转成英文，标题一改，两条跨文件锚点就指空了
    （ENDFIELD-ITEMS → HEADLESS 的扫库那节、PITFALLS → AUTOMAS 的选剑演武那节）。
    [links] 那一节只查文件在不在，`#` 后面被它剥掉了，所以这类断链一声不吭。
    点过去落在文件开头，读的人还以为自己读的就是那一节。
    """
    print("\n[anchors] 跨文件链接里的小节要真的存在")
    heads: dict[str, set[str]] = {}
    for md in markdown_files():
        heads[md.name] = {_slug(m.group(1)) for m in
                          re.finditer(r"^#{1,6}\s+(.+?)\s*$", md.read_text(encoding="utf-8"), re.M)}
    n = 0
    for md in markdown_files():
        for m in re.finditer(r"\[[^\]]*\]\(([^)\s#]*)#([^)\s]+)\)",
                             md.read_text(encoding="utf-8")):
            target, anchor = m.group(1), m.group(2)
            name = Path(target).name or md.name
            if name not in heads:
                continue                       # 站外或非 md，[links] 那节管
            n += 1
            if anchor.lower() in heads[name]:
                ok(f"{md.relative_to(REPO)} -> {target}#{anchor}")
            else:
                bad(f"{md.relative_to(REPO)} 指向 {name} 的 #{anchor}，那里没有这个小节")
    if not n:
        ok("没有跨文件的小节链接")


def check_command_whitelist() -> None:
    print("\n[commands] relay/README.md action table vs commands.py")
    src = (REPO / "relay" / "ark_relay" / "commands.py").read_text(encoding="utf-8")
    code: set[str] = set()
    for name in ("REVERSIBLE", "MUTATING"):
        m = re.search(rf"^{name}\s*=\s*\{{(.*?)\}}", src, re.S | re.M)
        if not m:
            bad(f"commands.py no longer defines {name}")
            return
        code |= set(re.findall(r'"([a-z_]+)"', m.group(1)))
    doc_text = (REPO / "relay" / "README.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\|\s*`([a-z_]+)`", doc_text, re.M))
    for action in sorted(code - documented):
        bad(f"commands.py allows `{action}` but relay/README.md does not list it")
    for action in sorted(documented - code):
        bad(f"relay/README.md lists `{action}` but commands.py does not allow it")
    if code and code == documented:
        ok(f"{len(code)} actions match: {', '.join(sorted(code))}")


def check_env_vars() -> None:
    print("\n[env] 代码读的环境变量 vs docs/CONFIG.md")
    # 2026-09-08 这道闸门本身有三个洞，13 个变量从缝里漏了过去，
    # 而 CONFIG.md 上还写着「这张表由 check-docs 的 [env] 一节盯着，漏一个闸门就红」：
    #   ① 只认 ARK_ 前缀 —— SKLAND_TOKEN、WECOM_TOUSER、TS_OAUTH_* 一个都不查；
    #   ② 只扫 relay/ —— scripts/ 里的 watchdog、idmap、upstream-post 全在视野外；
    #   ③ 只认 environ("X") 双引号写法 —— 而 config.py 里绝大多数是 _env("X", 默认值)。
    used: set[str] = set()
    for py in list((REPO / "relay").rglob("*.py")) + list((REPO / "scripts").rglob("*.py")):
        if "okww_files" in py.parts:
            continue                      # 上游原样文件，不归我们管
        text = py.read_text(encoding="utf-8")
        used |= set(re.findall(r"""environ(?:\.get)?[(\[]\s*["']([A-Z][A-Z0-9_]+)["']""", text))
        used |= set(re.findall(r"""_env\(\s*["']([A-Z][A-Z0-9_]+)["']""", text))
    doc = (REPO / "docs" / "CONFIG.md").read_text(encoding="utf-8")
    missing = sorted(v for v in used if v not in doc)
    if missing:
        bad("代码读了但 docs/CONFIG.md 没写：" + ", ".join(missing))
    else:
        ok(f"代码读的 {len(used)} 个环境变量都在 docs/CONFIG.md 里")


# ---------- 2. local directives ----------

def collect_directives() -> list[tuple[Path, str, str]]:
    found = []
    for md in markdown_files():
        for kind, arg in DIRECTIVE.findall(md.read_text(encoding="utf-8")):
            found.append((md, kind, arg))
    return found


def check_repo_paths(directives) -> None:
    items = [(md, a) for md, k, a in directives if k == "repo"]
    if not items:
        return
    print("\n[repo] paths the docs promise exist")
    for md, arg in items:
        if (REPO / arg).exists():
            ok(arg)
        else:
            bad(f"{md.relative_to(REPO)} claims {arg} exists; it does not")


# ---------- 3. remote directives ----------

def host_reachable() -> bool:
    if not HOST:
        return False
    return subprocess.run([*SSH, f"Administrator@{HOST}", "cd ."],
                          capture_output=True).returncode == 0


_PWSH7 = r"C:\Program Files\PowerShell\7\pwsh.exe"
_pwsh_cache: dict[str, bool] = {}


def _has_pwsh() -> bool:
    """游戏机上有没有 pwsh 7。只问一次。

    这个名字被引用了却从来没定义——2026-09-06 pyflakes 一跑就报。走到
    json 指令那一步必然 NameError。
    """
    if "v" not in _pwsh_cache:
        rc, _ = remote(f'if exist "{_PWSH7}" (exit 0) else (exit 1)')
        _pwsh_cache["v"] = rc == 0
    return _pwsh_cache["v"]


def remote(cmd: str) -> tuple[int, str]:
    # Bytes, not text=True. The Windows console is GBK, so `schtasks` and
    # friends answer in GBK and Python's UTF-8 decode raises - which killed
    # this checker on its first run against a live machine. Decoding is done
    # here, tolerantly: the checks look for ASCII markers, and a mangled
    # Chinese word in an error message is better than a crash.
    r = subprocess.run([*SSH, f"Administrator@{HOST}", cmd], capture_output=True)
    raw = (r.stdout or b"") + (r.stderr or b"")
    for enc in ("utf-8", "gbk"):
        try:
            return r.returncode, raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return r.returncode, raw.decode("utf-8", errors="replace")


def check_win_paths(directives) -> None:
    items = [(md, a) for md, k, a in directives if k == "win"]
    if not items:
        return
    print("\n[paths] paths on the game machine")
    for md, arg in items:
        rc, _ = remote(f'if exist "{arg}" (echo YES) else (echo NO)')
        if rc == 0 and "YES" in _:
            ok(arg)
        else:
            bad(f"{md.relative_to(REPO)} claims {arg} exists on the machine; it does not")


def check_services(directives) -> None:
    for kind, label, cmd, needle in (
        ("svc", "services", 'sc query "{}"', "SERVICE_NAME"),
        ("task", "scheduled tasks", 'schtasks /query /tn "{}"', None),
    ):
        items = [(md, a) for md, k, a in directives if k == kind]
        if not items:
            continue
        print(f"\n[{kind}] {label} on the game machine")
        for md, arg in items:
            rc, out = remote(cmd.format(arg))
            if rc == 0 and (needle is None or needle in out):
                ok(arg)
            else:
                bad(f"{md.relative_to(REPO)} names {kind} '{arg}'; the machine does not have it")


def _dig(node, parts: list[str]) -> list:
    if not parts:
        return [node]
    head, rest = parts[0], parts[1:]
    if head == "*":
        if not isinstance(node, dict):
            return []
        return [v for child in node.values() for v in _dig(child, rest)]
    if isinstance(node, dict) and head in node:
        return _dig(node[head], rest)
    return []


def check_json_values(directives) -> None:
    items = [(md, a) for md, k, a in directives if k == "json"]
    if not items:
        return
    print("\n[json] configuration values on the game machine")
    cache: dict[str, object] = {}
    for md, arg in items:
        try:
            path, keypath, expected = arg.split(None, 2)
        except ValueError:
            bad(f"{md.relative_to(REPO)}: malformed json directive: {arg!r}")
            continue
        if path not in cache:
            # 只用 pwsh 7：5.1 默认不是 UTF-8，路径含中文时会被 ANSI 解码毁掉。
            # 没有就直接判 FAIL，不退回 5.1（退回去读到的是乱码，比失败更坏）。
            if not _has_pwsh():
                bad(f"{md.relative_to(REPO)}: 游戏机上没有 pwsh 7（{_PWSH7}），json 指令没法核对")
                cache[path] = None
                continue
            _pw = f'"{_PWSH7}"'
            rc, out = remote(
                f'{_pw} -NoProfile -Command '
                f'"[Convert]::ToBase64String([IO.File]::ReadAllBytes(\'{path}\'))"')
            if rc != 0:
                cache[path] = None
            else:
                import base64  # noqa: PLC0415
                try:
                    cache[path] = json.loads(
                        base64.b64decode(out.strip()).decode("utf-8"))
                except Exception:  # noqa: BLE001
                    cache[path] = None
        doc = cache[path]
        if doc is None:
            bad(f"cannot read {path} on the machine")
            continue
        found = _dig(doc, [p for p in keypath.split("/") if p])
        if not found:
            bad(f"{keypath} not present in {path}")
        elif all(str(v) == expected for v in found):
            ok(f"{keypath} == {expected}" + (f" (x{len(found)})" if len(found) > 1 else ""))
        else:
            bad(f"docs say {keypath} is {expected}; machine says "
                + ", ".join(sorted({str(v) for v in found})))


def main() -> int:
    local_only = "--local" in sys.argv
    directives = collect_directives()

    check_links()
    check_anchors()
    check_command_whitelist()
    check_env_vars()
    check_repo_paths(directives)

    remote_kinds = {k for _, k, _ in directives} & {"win", "svc", "task", "json"}
    if local_only:
        skip("remote checks: --local")
    elif not HOST:
        skip("remote checks: ARK_HOST is not set")
    elif not remote_kinds:
        pass
    elif not host_reachable():
        skip(f"remote checks: {HOST} did not answer (the machine is off most of the day)")
    else:
        check_win_paths(directives)
        check_services(directives)
        check_json_values(directives)

    print(f"\n{passes} ok, {len(fails)} failed, {len(skips)} skipped")
    for f in fails:
        print(f"  FAIL  {f}")
    for s in skips:
        print(f"  skip  {s}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
