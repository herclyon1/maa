#!/opt/homebrew/bin/python3
"""Hardlock-gated AUTO-MAS MAA config switcher: OS-4 + MedicineNumb=999.

Sets the Arknights (MAA) user in AUTO-MAS to farm the SideStory rerun stage
OS-4 (「雪山降临1101」复刻第 4 关「并蒂生」, open until 2026-12-02 03:59 CST)
with unlimited sanity-potion consumption (MedicineNumb=999):

    Stage.StageMode       = "Fixed"
    Stage.Stage           = "OS-4"
    Stage.Stage_1         = "-"
    Stage.Stage_2         = "-"
    Stage.Stage_3         = "-"
    Stage.MedicineNumb    = 999
    Task.IfFight          = true
    Task.IfActivityFirst  = false

Modes:
    --check   (default, read-only) Compare current AUTO-MAS values against target.
              Exit 0 = already aligned, 2 = diff found (needs apply), 1 = error.
    --apply   Check HARDLOCK.json first (exit 4 on lock, zero API/write calls).
              When unlocked, write an atomic JSON backup, update through
              AUTO-MAS API (/api/scripts/user/update), and read back all 8
              fields to verify exact equality (exit 0 = verified, 1 = failure).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SERVER_TZ = timezone(timedelta(hours=8))

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_DRIFT = 2
EXIT_HARDLOCKED = 4

TARGET_FIELDS: dict[str, Any] = {
    "Stage.StageMode": "Fixed",
    "Stage.Stage": "OS-4",
    "Stage.Stage_1": "-",
    "Stage.Stage_2": "-",
    "Stage.Stage_3": "-",
    "Stage.MedicineNumb": 999,
    "Task.IfFight": True,
    "Task.IfActivityFirst": False,
}

_MAC_HARDLOCK_SCRIPT = Path("/Users/herclyon/Money/审批记录/硬锁/hardlock.py")


def _default_state_dir() -> Path:
    env = os.environ.get("ARK_STATE_DIR", "").strip()
    if env:
        return Path(env)
    if os.name == "nt":
        return Path(os.path.join(r"C:\ProgramData", "ark-relay", "state"))
    return Path("./ark-state")


def _default_mas_url() -> str:
    env_url = os.environ.get("ARK_MAS_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    host = os.environ.get("ARK_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.environ.get("ARK_MAS_PORT", "36163").strip() or "36163"
    return f"http://{host}:{port}"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _check_mac_hardlock() -> str:
    if os.name == "nt" or not _MAC_HARDLOCK_SCRIPT.is_file():
        return ""
    try:
        spec = importlib.util.spec_from_file_location("hardlock_1126", str(_MAC_HARDLOCK_SCRIPT))
        if spec is None or spec.loader is None:
            return "Mac 硬锁模块无法加载，按锁定处理"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        locked, msg = mod.check("relay")
        return str(msg or "Mac 硬锁中") if locked else ""
    except Exception as exc:  # noqa: BLE001 - fail-closed on hardlock check error
        return f"Mac 硬锁检查异常（{type(exc).__name__}），按锁定处理"


def check_hardlock(hardlock_path: Path | None = None, *, explicit: bool = False) -> str:
    """Return non-empty lock reason if writes are forbidden; '' when unlocked.

    Delegates directly to `ark_relay.features.hardlock.active(state_dir, "relay")`
    so sticky state.json locks, corrupt files, and forged `locked:false`/`unlocked:true`
    files are all refused fail-closed. Also enforces `LOCKED_UNAVAILABLE.flag` and
    (unless `explicit` overrides the path for isolated tests) the Mac hardlock module.
    """
    path = hardlock_path or (_default_state_dir() / "HARDLOCK.json")
    state_dir = path.parent
    flag = state_dir.parent / "LOCKED_UNAVAILABLE.flag"
    if flag.exists():
        return f"不可用标记 {flag} 存在，禁止写入"
    try:
        relay_root = Path(__file__).resolve().parents[2] / "relay"
        if str(relay_root) not in sys.path:
            sys.path.insert(0, str(relay_root))
        from ark_relay.features import hardlock as _hl  # noqa: PLC0415
        if _hl.active(state_dir, "relay"):
            return f"中继硬锁生效中（{state_dir}），拒绝写入"
        if path.name != _hl.LOCK_FILE and path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not (isinstance(data, dict) and _hl.released_ok(data.get("release"), "relay")):
                return f"硬锁文件 {path} 未含合规解锁记录，拒绝写入"
    except Exception as exc:  # noqa: BLE001 - fail-closed on any hardlock check error
        return f"硬锁检查异常（{type(exc).__name__}），按锁定处理"
    if not explicit:
        if mac_why := _check_mac_hardlock():
            return mac_why
    return ""


def _post_mas(base_url: str, path: str, body: dict[str, Any] | None = None,
              timeout: float = 15.0) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"AUTO-MAS {path} 返回非对象 JSON")
    return parsed


def _api_refused(resp: dict[str, Any]) -> str:
    if "code" in resp and resp.get("code") != 200:
        return str(resp.get("message") or f"code={resp.get('code')}")
    return ""


def _is_maa_script(sc: dict[str, Any]) -> bool:
    info = sc.get("Info") if isinstance(sc, dict) else None
    if not isinstance(info, dict):
        return False
    name = str(info.get("Name") or "").strip().lower()
    if name == "maa":
        return True
    p = str(info.get("Path") or info.get("RootPath") or "").lower()
    return "maa" in p and "maaend" not in p


def _pick_active_user(users: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    candidates = [
        (str(uid), user)
        for uid, user in users.items()
        if uid != "instances" and isinstance(user, dict)
    ]
    if not candidates:
        raise KeyError("MAA 脚本下没有配置用户")
    for uid, user in candidates:
        info = user.get("Info") if isinstance(user.get("Info"), dict) else {}
        if bool(info.get("Status", True)) and info.get("RemainedDay", -1) != 0:
            return uid, user
    return candidates[0]


def _find_maa_user(base_url: str, *, post=_post_mas) -> tuple[str, str, dict[str, Any]]:
    scripts_resp = post(base_url, "/api/scripts/get", {})
    if why := _api_refused(scripts_resp):
        raise RuntimeError(f"/api/scripts/get 被拒绝: {why}")
    scripts = scripts_resp.get("data")
    if not isinstance(scripts, dict):
        raise RuntimeError("/api/scripts/get 缺少 data 字典")
    for sid, sc in scripts.items():
        if not isinstance(sc, dict) or not _is_maa_script(sc):
            continue
        users_resp = post(base_url, "/api/scripts/user/get", {"scriptId": sid})
        if why := _api_refused(users_resp):
            raise RuntimeError(f"/api/scripts/user/get 被拒绝: {why}")
        users = users_resp.get("data")
        if not isinstance(users, dict):
            raise RuntimeError("/api/scripts/user/get 缺少 data 字典")
        uid, user = _pick_active_user(users)
        return str(sid), uid, user
    raise KeyError("AUTO-MAS 中找不到 MAA 脚本")


def _read_field(user: dict[str, Any], dotted: str) -> tuple[bool, Any]:
    group, _, key = dotted.partition(".")
    grp = user.get(group)
    if isinstance(grp, dict) and key in grp:
        return True, grp[key]
    return False, None


def _exact_match(got: Any, want: Any) -> bool:
    if isinstance(want, bool):
        return isinstance(got, bool) and got is want
    if isinstance(want, int):
        return isinstance(got, int) and not isinstance(got, bool) and got == want
    return got == want


def diff_target(user: dict[str, Any],
                targets: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Return {dotted_field: {'actual': ..., 'target': ..., 'present': bool}} for every mismatch."""
    want_map = targets or TARGET_FIELDS
    diffs: dict[str, dict[str, Any]] = {}
    for dotted, want in want_map.items():
        present, got = _read_field(user, dotted)
        if not present or not _exact_match(got, want):
            diffs[dotted] = {"present": present, "actual": got, "target": want}
    return diffs


def _build_update_payload(targets: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nested: dict[str, dict[str, Any]] = {}
    for dotted, val in targets.items():
        group, _, key = dotted.partition(".")
        nested.setdefault(group, {})[key] = val
    return nested


def run_check(base_url: str, *, post=_post_mas) -> tuple[int, dict[str, Any]]:
    """Read-only comparison against AUTO-MAS MAA user config."""
    try:
        sid, uid, user = _find_maa_user(base_url, post=post)
    except (OSError, urllib.error.URLError, ValueError, KeyError, RuntimeError) as exc:
        return EXIT_ERROR, {"mode": "check", "ok": False, "error": str(exc)}
    diffs = diff_target(user)
    ok = not diffs
    return (EXIT_OK if ok else EXIT_DRIFT), {
        "mode": "check",
        "ok": ok,
        "scriptId": sid,
        "userId": uid,
        "checked_fields": len(TARGET_FIELDS),
        "diffs": diffs,
    }


def run_apply(base_url: str, *, hardlock_path: Path | None = None, explicit_hardlock: bool = False,
              backup_dir: Path | None = None, post=_post_mas) -> tuple[int, dict[str, Any]]:
    """Hardlock-gated backup + AUTO-MAS API update + full read-back verification."""
    if why := check_hardlock(hardlock_path, explicit=explicit_hardlock):
        return EXIT_HARDLOCKED, {
            "mode": "apply",
            "ok": False,
            "locked": True,
            "error": why,
        }
    try:
        sid, uid, before_user = _find_maa_user(base_url, post=post)
    except (OSError, urllib.error.URLError, ValueError, KeyError, RuntimeError) as exc:
        return EXIT_ERROR, {"mode": "apply", "ok": False, "error": f"读取现状失败: {exc}"}

    missing = [k for k in TARGET_FIELDS if not _read_field(before_user, k)[0]]
    if missing:
        return EXIT_ERROR, {
            "mode": "apply",
            "ok": False,
            "scriptId": sid,
            "userId": uid,
            "error": f"MAA 用户配置缺少目标字段，拒绝盲写: {', '.join(missing)}",
        }

    now = datetime.now(tz=SERVER_TZ)
    bdir = backup_dir or (_default_state_dir() / "backups")
    bpath = bdir / f"maa_os4_medicine999_{now:%Y%m%d-%H%M%S}.json"
    _atomic_write_json(bpath, {
        "backed_up_at": now.isoformat(timespec="seconds"),
        "mas_url": base_url,
        "scriptId": sid,
        "userId": uid,
        "before": before_user,
        "target": TARGET_FIELDS,
    })

    payload = _build_update_payload(TARGET_FIELDS)
    try:
        upd_resp = post(base_url, "/api/scripts/user/update", {
            "scriptId": sid,
            "userId": uid,
            "data": payload,
        })
    except (OSError, urllib.error.URLError, ValueError, RuntimeError) as exc:
        return EXIT_ERROR, {
            "mode": "apply",
            "ok": False,
            "backup": str(bpath),
            "error": f"写入 AUTO-MAS API 失败: {exc}",
        }
    if why := _api_refused(upd_resp):
        return EXIT_ERROR, {
            "mode": "apply",
            "ok": False,
            "backup": str(bpath),
            "error": f"AUTO-MAS 拒绝修改: {why}",
        }

    try:
        after_resp = post(base_url, "/api/scripts/user/get", {"scriptId": sid})
        if why := _api_refused(after_resp):
            raise RuntimeError(f"/api/scripts/user/get 被拒绝: {why}")
        after_users = after_resp.get("data") or {}
        if uid not in after_users or not isinstance(after_users[uid], dict):
            raise KeyError(f"回读找不到用户 {uid}")
        after_user = after_users[uid]
    except (OSError, urllib.error.URLError, ValueError, KeyError, RuntimeError) as exc:
        return EXIT_ERROR, {
            "mode": "apply",
            "ok": False,
            "backup": str(bpath),
            "error": f"回读核验失败: {exc}",
        }

    remaining = diff_target(after_user)
    if remaining:
        return EXIT_ERROR, {
            "mode": "apply",
            "ok": False,
            "backup": str(bpath),
            "scriptId": sid,
            "userId": uid,
            "error": "写入后回读仍有字段未生效",
            "diffs": remaining,
        }

    return EXIT_OK, {
        "mode": "apply",
        "ok": True,
        "backup": str(bpath),
        "scriptId": sid,
        "userId": uid,
        "verified_fields": len(TARGET_FIELDS),
        "values": {k: _read_field(after_user, k)[1] for k in TARGET_FIELDS},
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AUTO-MAS MAA OS-4 + MedicineNumb=999 硬锁控制脚本")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只读检查现状与目标值差异（默认）")
    mode.add_argument("--apply", action="store_true", help="检查硬锁后备份并通过 AUTO-MAS API 写入并回读核验")
    p.add_argument("--mas-url", default="", help="AUTO-MAS 后端地址（默认取 ARK_MAS_URL 或 ARK_HOST:ARK_MAS_PORT）")
    p.add_argument("--hardlock", default="", help="HARDLOCK.json 路径（默认取 ARK_HARDLOCK_FILE 或 state/HARDLOCK.json）")
    p.add_argument("--backup-dir", default="", help="写入前备份目录（默认 state/backups）")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    base_url = args.mas_url.strip() or _default_mas_url()
    env_hl = os.environ.get("ARK_HARDLOCK_FILE", "").strip()
    explicit_hl = bool(args.hardlock.strip() or env_hl)
    hl_path = Path(args.hardlock.strip() or env_hl) if explicit_hl else None
    backup_dir = Path(args.backup_dir.strip()) if args.backup_dir.strip() else None

    if args.apply:
        rc, result = run_apply(
            base_url,
            hardlock_path=hl_path,
            explicit_hardlock=explicit_hl,
            backup_dir=backup_dir,
        )
    else:
        rc, result = run_check(base_url)

    out_stream = sys.stdout if rc in (EXIT_OK, EXIT_DRIFT) else sys.stderr
    print(json.dumps(result, ensure_ascii=False, indent=2), file=out_stream)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
