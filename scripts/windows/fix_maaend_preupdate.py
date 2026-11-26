"""Check (read-only by default) and fix MaaEnd pre-update settings on AUTO-MAS v5.8+ (R-02).

On AUTO-MAS v5.8+, `MaaEndConfig.Update` defaults to `TakeoverEnabled: false` and
`Channel: stable`. With those defaults, AUTO-MAS never pre-updates MaaEnd before the
morning shift, breaking the pre-update handover.

Usage:
  python fix_maaend_preupdate.py [--file PATH] [--api] [--json]
      Read-only audit (default). Exit 0 = compliant, 2 = broken, 3 = unreadable/missing.

  python fix_maaend_preupdate.py --apply [--file PATH | --api] [--hardlock-file PATH]
      Apply `Update.TakeoverEnabled=true` and `Update.Channel=beta` after the machine
      is unlocked. Refuses with exit 4 while HARDLOCK.json is present.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_RELAY = _REPO / "relay"
if str(_RELAY) not in sys.path:
    sys.path.insert(0, str(_RELAY))

from ark_relay.core import mastercfg  # noqa: E402

DEFAULT_SCRIPTS_YAML = Path(r"D:\ark\automas\config\scripts.yaml")
DEFAULT_HARDLOCK = Path(r"C:\ProgramData\ark-relay\state\HARDLOCK.json")
WANT_TAKEOVER = True
WANT_CHANNEL = mastercfg.MAAEND_PREUPDATE_WANT_CHANNEL


def _mas_base() -> str:
    return f"http://127.0.0.1:{os.environ.get('ARK_MAS_PORT', '36163')}"


def _mas_post(path: str, body: dict | None = None, timeout: int = 15) -> dict:
    req = urllib.request.Request(
        _mas_base() + path,
        data=json.dumps(body or {}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        reply = json.loads(resp.read().decode("utf-8", "replace"))
    if isinstance(reply, dict) and "code" in reply and reply.get("code") != 200:
        raise RuntimeError(f"{path}: code={reply.get('code')} {reply.get('message') or ''}".strip())
    return reply


def inspect_yaml_text(text: str, *, name: str = "scripts.yaml") -> dict:
    """Parse `scripts.yaml` text and return structured MaaEnd pre-update audit info."""
    parsed = mastercfg.parse_text(Path(name), text)
    maaend_id, maaend_node = None, None
    for inst, node in mastercfg._nodes(parsed):
        if mastercfg._script_kind(inst, node) == "MaaEnd":
            maaend_id = str(inst.get("uid") or "")
            maaend_node = node
            break
    if maaend_node is None:
        return {
            "found": False, "script_id": "", "takeover": None, "channel": None,
            "ok": False, "gaps": ["终末地开跑前由调度程序接管更新：调度程序里没有 MaaEnd 这个脚本"],
        }
    upd = maaend_node.get("Update") if isinstance(maaend_node.get("Update"), dict) else {}
    gaps = mastercfg.check_maaend_preupdate(scripts={maaend_id or "maaend": maaend_node}, version="v5.8.0")
    return {
        "found": True,
        "script_id": maaend_id,
        "takeover": upd.get("TakeoverEnabled"),
        "channel": upd.get("Channel"),
        "ok": not gaps,
        "gaps": gaps,
    }


def inspect_scripts_dict(scripts: dict) -> dict:
    """Audit live `/api/scripts/get` data dict without writing anything."""
    maaend_id, maaend_node = None, None
    for sid, node in (scripts or {}).items():
        if not isinstance(node, dict):
            continue
        name = str((node.get("Info") or {}).get("Name") or "")
        if name.lower() == "maaend":
            maaend_id, maaend_node = str(sid), node
            break
    if maaend_node is None:
        return {
            "found": False, "script_id": "", "takeover": None, "channel": None,
            "ok": False, "gaps": ["终末地开跑前由调度程序接管更新：调度程序里没有 MaaEnd 这个脚本"],
        }
    upd = maaend_node.get("Update") if isinstance(maaend_node.get("Update"), dict) else {}
    gaps = mastercfg.check_maaend_preupdate(scripts=scripts, version="v5.8.0")
    return {
        "found": True,
        "script_id": maaend_id,
        "takeover": upd.get("TakeoverEnabled"),
        "channel": upd.get("Channel"),
        "ok": not gaps,
        "gaps": gaps,
    }


def _block_end(lines: list[str], start_idx: int, base_indent: int) -> int:
    i = start_idx + 1
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            ind = len(raw) - len(raw.lstrip(" "))
            if ind <= base_indent:
                return i
        i += 1
    return len(lines)


def patch_yaml_text(text: str) -> str:
    """Surgically update MaaEnd's `Update.TakeoverEnabled` -> true and `Update.Channel` -> beta.

    Preserves all unrelated scripts, comments and formatting, then verifies round-trip
    equivalence on every non-Update field via `mastercfg.parse_text`.
    """
    before_parsed = mastercfg.parse_text(Path("scripts.yaml"), text)
    info = inspect_yaml_text(text)
    if not info["found"] or not info["script_id"]:
        raise ValueError("scripts.yaml 里找不到 MaaEnd 脚本")
    sid = info["script_id"]
    lines = text.splitlines(keepends=True)
    nl = "\r\n" if "\r\n" in text else "\n"

    # Locate `data:` mapping -> `<sid>:` block.
    data_idx = next((i for i, ln in enumerate(lines) if re.match(r"^data:\s*$", ln)), None)
    if data_idx is None:
        raise ValueError("scripts.yaml 缺少顶层 data: 块")
    data_end = _block_end(lines, data_idx, 0)
    sid_pat = re.compile(rf"^(\s+)(?:['\"])?{re.escape(sid)}(?:['\"])?:\s*$")
    sid_idx = next((i for i in range(data_idx + 1, data_end) if sid_pat.match(lines[i])), None)
    if sid_idx is None:
        raise ValueError(f"scripts.yaml data 块里找不到 MaaEnd 条目 {sid}")
    sid_indent = len(lines[sid_idx]) - len(lines[sid_idx].lstrip(" "))
    sid_end = _block_end(lines, sid_idx, sid_indent)

    upd_pat = re.compile(rf"^(\s{{{sid_indent + 1},}})Update:\s*(\{{\}})?\s*$")
    upd_idx = next((i for i in range(sid_idx + 1, sid_end) if upd_pat.match(lines[i])), None)

    if upd_idx is None:
        # Infer child indent under <sid>:
        child_indent = sid_indent + 2
        for i in range(sid_idx + 1, sid_end):
            st = lines[i].strip()
            if st and not st.startswith("#"):
                child_indent = len(lines[i]) - len(lines[i].lstrip(" "))
                break
        pad = " " * child_indent
        sub = " " * (child_indent + 2)
        insert_lines = [
            f"{pad}Update:{nl}",
            f"{sub}TakeoverEnabled: true{nl}",
            f"{sub}Channel: {WANT_CHANNEL}{nl}",
        ]
        lines[sid_end:sid_end] = insert_lines
    else:
        upd_indent = len(lines[upd_idx]) - len(lines[upd_idx].lstrip(" "))
        upd_end = _block_end(lines, upd_idx, upd_indent)
        if lines[upd_idx].rstrip().endswith("{}"):
            lines[upd_idx] = " " * upd_indent + f"Update:{nl}"
        sub_indent = upd_indent + 2
        for i in range(upd_idx + 1, upd_end):
            st = lines[i].strip()
            if st and not st.startswith("#"):
                sub_indent = len(lines[i]) - len(lines[i].lstrip(" "))
                break
        sub = " " * sub_indent
        found_tk = False
        found_ch = False
        for i in range(upd_idx + 1, upd_end):
            if re.match(rf"^\s{{{sub_indent}}}TakeoverEnabled\s*:", lines[i]):
                lines[i] = f"{sub}TakeoverEnabled: true{nl}"
                found_tk = True
            elif re.match(rf"^\s{{{sub_indent}}}Channel\s*:", lines[i]):
                lines[i] = f"{sub}Channel: {WANT_CHANNEL}{nl}"
                found_ch = True
        add: list[str] = []
        if not found_tk:
            add.append(f"{sub}TakeoverEnabled: true{nl}")
        if not found_ch:
            add.append(f"{sub}Channel: {WANT_CHANNEL}{nl}")
        if add:
            lines[upd_end:upd_end] = add

    patched = "".join(lines)
    after_parsed = mastercfg.parse_text(Path("scripts.yaml"), patched)
    expected = copy.deepcopy(before_parsed)
    expected[sid].setdefault("Update", {})
    expected[sid]["Update"]["TakeoverEnabled"] = WANT_TAKEOVER
    expected[sid]["Update"]["Channel"] = WANT_CHANNEL
    if after_parsed != expected:
        raise ValueError("修改后的 scripts.yaml 校验发现非 Update 字段发生意外变化，已中止写入")
    return patched


def apply_yaml_file(path: Path, *, hardlock_file: Path = DEFAULT_HARDLOCK) -> dict:
    """Backup and atomically patch `scripts.yaml` (refuses while hardlocked)."""
    if hardlock_file.exists():
        raise PermissionError(f"硬锁文件存在（{hardlock_file}），禁止写入 {path}")
    raw = path.read_text(encoding="utf-8")
    before = inspect_yaml_text(raw, name=path.name)
    if before["ok"]:
        return {**before, "changed": False, "backup": ""}
    patched = patch_yaml_text(raw)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-maaend-preupdate-{stamp}")
    backup.write_bytes(path.read_bytes())
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(patched)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    after = inspect_yaml_text(path.read_text(encoding="utf-8"), name=path.name)
    if not after["ok"]:
        raise RuntimeError(f"写入后回读校验未通过：{after['gaps']}")
    return {**after, "changed": True, "backup": str(backup)}


def apply_via_api(*, hardlock_file: Path = DEFAULT_HARDLOCK, post=None) -> dict:
    """Update MaaEnd's Update.TakeoverEnabled/Channel through live AUTO-MAS API."""
    if hardlock_file.exists():
        raise PermissionError(f"硬锁文件存在（{hardlock_file}），禁止修改运行中的 AUTO-MAS")
    post = post or _mas_post
    scripts = post("/api/scripts/get").get("data") or {}
    before = inspect_scripts_dict(scripts)
    if not before["found"]:
        raise RuntimeError("AUTO-MAS 里找不到 MaaEnd 脚本")
    if before["ok"]:
        return {**before, "changed": False}
    post("/api/scripts/update", {
        "scriptId": before["script_id"],
        "data": {"Update": {"TakeoverEnabled": WANT_TAKEOVER, "Channel": WANT_CHANNEL}},
    })
    after = inspect_scripts_dict(post("/api/scripts/get").get("data") or {})
    if not after["ok"]:
        raise RuntimeError(f"API 写入后回读未生效：{after['gaps']}")
    return {**after, "changed": True}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check or fix MaaEnd Update.TakeoverEnabled / Channel (R-02).")
    ap.add_argument("--file", type=Path, default=DEFAULT_SCRIPTS_YAML, help="Path to scripts.yaml")
    ap.add_argument("--api", action="store_true", help="Read/write through live AUTO-MAS HTTP API")
    ap.add_argument("--apply", action="store_true", help="Apply the fix (default is read-only check)")
    ap.add_argument("--hardlock-file", type=Path, default=DEFAULT_HARDLOCK, help="Refuse --apply if this file exists")
    ap.add_argument("--json", action="store_true", help="Print JSON result")
    args = ap.parse_args(argv)

    try:
        if args.apply:
            res = apply_via_api(hardlock_file=args.hardlock_file) if args.api else apply_yaml_file(
                args.file, hardlock_file=args.hardlock_file
            )
        elif args.api:
            res = inspect_scripts_dict(_mas_post("/api/scripts/get").get("data") or {})
        else:
            res = inspect_yaml_text(args.file.read_text(encoding="utf-8"), name=args.file.name)
    except PermissionError as exc:
        print(f"LOCKED: {exc}", file=sys.stderr)
        return 4
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        status = "OK" if res["ok"] else "BROKEN"
        print(
            f"[{status}] MaaEnd({res.get('script_id') or '?'}) "
            f"Update.TakeoverEnabled={res.get('takeover')!r} Channel={res.get('channel')!r}"
        )
        for g in res.get("gaps") or []:
            print(f"  - {g}")
        if res.get("backup"):
            print(f"  backup: {res['backup']}")
    return 0 if res["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
