#!/opt/homebrew/bin/python3
"""Shared Mac-side shutdown guard (Layer 3 of the no-delay deploy & no-early-shutdown architecture).

Used by scripts/mac/lib/shutdown-guard.sh (sourced by winps.sh, winrun.sh, and wingui.sh launch).
Detects shutdown/reboot commands in PowerShell, cmd, Python AST, and GUI launch targets;
blocks manual shutdown when there are blocking open ledger items, dirty runtime files,
pending_deploy versions, or unshipped runtime commits ahead of the machine's running relay tag.
"""
from __future__ import annotations

import ast
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RUNTIME_PATHS = (
    ":(glob)relay/ark_relay/**/*.py",
    ":(glob)relay/ark_relay/**/*.txt",
    ":(glob)relay/*.py",
    ":(exclude)relay/make-manifest.py",
    "relay/requirements.txt",
    "packaging/build.py",
    "packaging/launch.py",
    "packaging/switch.py",
    "packaging/legacy.py",
    "packaging/watchdog/ark_watchdog.py",
    ":(glob)relay/handover/**",
)

_MULTILINE_RE = re.compile(r"(?i)\bStart-Process\b[\s\S]*?(?:shutdown|logoff)")
_ABORT_ONLY_RE = re.compile(r"(?i)^\s*shutdown(?:\.exe)?\s+[/-](?:a|\?)\s*$")
_SHUTDOWN_PATTERNS = (
    re.compile(
        r"""(?i)(?<![a-z0-9_])shutdown(?:\.exe)?(?=$|[\s'"/)])(?:[^\r\n]*?(?:[\s'",)]|/[a-z0-9:]+|\d))?[/-](?:s|r|p|g|h|sg|l)\b"""
    ),
    re.compile(r"(?i)(?<![a-z0-9_])logoff(?:\.exe)?\b"),
    re.compile(
        r"(?i)\b(?:Stop-Computer|Restart-Computer|Win32Shutdown|ExitWindowsEx|"
        r"InitiateSystemShutdown|InitiateShutdown|NtShutdownSystem|SetSuspendState)\b"
    ),
    re.compile(r"(?i)\bWin32_OperatingSystem\b[^\r\n]*\.(?:Shutdown|Reboot)\b"),
    re.compile(r"(?i)\bInvoke-(?:Cim|Wmi)Method\b[^\r\n]*(?:Shutdown|Reboot|Win32Shutdown)\b"),
    re.compile(r"(?i)\brundll32(?:\.exe)?\b[^\r\n]*\bpowrprof\b"),
    re.compile(r"(?i)\bwmic(?:\.exe)?\b[^\r\n]*\bcall\s+(?:shutdown|reboot|Win32Shutdown)\b"),
    re.compile(
        r"(?i)\b(?:pwsh|powershell)(?:\.exe)?\b[^\r\n]*(?:^|\s)"
        r"-(?:ec|e(?:n(?:c(?:o(?:d(?:e(?:d(?:c(?:o(?:m(?:m(?:a(?:n(?:d)?)?)?)?)?)?)?)?)?)?)?)?)?)\b"
    ),
)
_WIN_API_MARKERS = (
    "ExitWindowsEx",
    "InitiateSystemShutdown",
    "InitiateShutdown",
    "NtShutdownSystem",
    "SetSuspendState",
    "Win32Shutdown",
)
_WINGUI_BLOCKED_EXE = re.compile(
    r"(?i)(?:^|[\\/])(?:shutdown|logoff|cmd|pwsh|powershell|wmic|rundll32)(?:\.exe)?$"
)


def _strip_comments(text: str) -> str:
    out_lines = []
    for ln in text.splitlines():
        s = ln.lstrip()
        if s.startswith("#") or re.match(r"(?i)^rem\b", s):
            continue
        out_lines.append(ln)
    return "\n".join(out_lines)


def _normalize_shell(text: str) -> str:
    # Merge PowerShell backtick line continuations, then remove inline backtick & cmd ^ escapes.
    s = re.sub(r"`\r?\n", " ", text)
    s = s.replace("`", "")
    s = re.sub(r"\^([^\r\n])", r"\1", s)
    return _strip_comments(s)


def is_shutdown_cmd(text: str) -> bool:
    if not text or not text.strip():
        return False
    if _MULTILINE_RE.search(text):
        return True
    norm = _normalize_shell(text)
    if _MULTILINE_RE.search(norm):
        return True
    for stmt in re.split(r";|&&|\|\||\||&|\r?\n", norm):
        st = stmt.strip()
        if not st or _ABORT_ONLY_RE.match(st):
            continue
        for pat in _SHUTDOWN_PATTERNS:
            if pat.search(st):
                return True
    return False


def _eval_str(node: ast.AST, env: dict[str, object]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and isinstance(env.get(node.id), str):
        return str(env[node.id])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_str(node.left, env)
        right = _eval_str(node.right, env)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            elif isinstance(v, ast.FormattedValue):
                ev = _eval_str(v.value, env)
                parts.append(ev if ev is not None else " ")
        return "".join(parts)
    return None


def _eval_seq(node: ast.AST, env: dict[str, object]) -> list[str] | None:
    if isinstance(node, ast.Name) and isinstance(env.get(node.id), list):
        return list(env[node.id])  # type: ignore[arg-type]
    if isinstance(node, (ast.List, ast.Tuple)):
        items: list[str] = []
        for elt in node.elts:
            s = _eval_str(elt, env)
            if s is not None:
                items.append(s)
        return items if items else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_seq(node.left, env)
        right = _eval_seq(node.right, env)
        if left is not None and right is not None:
            return left + right
    return None


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                ids.add(id(first.value))
    return ids


def _has_win_api_marker(name: str) -> bool:
    return any(name.startswith(m) or m in name for m in _WIN_API_MARKERS)


def _collect_py_env(tree: ast.AST) -> dict[str, object]:
    env: dict[str, object] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            val = _eval_str(node.value, env)
            if val is not None:
                env[node.targets[0].id] = val
            elif (seq := _eval_seq(node.value, env)) is not None:
                env[node.targets[0].id] = seq
    return env


def _call_arg_text(call: ast.Call, env: dict[str, object]) -> str:
    parts: list[str] = []
    for arg in call.args:
        s = _eval_str(arg, env)
        if s is not None:
            parts.append(s)
        elif seq := _eval_seq(arg, env):
            parts.extend(seq)
    return " ".join(parts)


def is_shutdown_py_source(src: str, extra_args: str = "") -> bool:
    if extra_args and is_shutdown_cmd(extra_args):
        return True
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return is_shutdown_cmd(src)
    docs = _docstring_ids(tree)
    env = _collect_py_env(tree)
    candidates: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            candidates.append(node.value)
        elif isinstance(node, ast.Name) and _has_win_api_marker(node.id):
            return True
        elif isinstance(node, ast.Attribute) and _has_win_api_marker(node.attr):
            return True
        elif isinstance(node, (ast.BinOp, ast.JoinedStr)) and (s := _eval_str(node, env)) is not None:
            candidates.append(s)
        elif isinstance(node, (ast.List, ast.Tuple)) and (seq := _eval_seq(node, env)):
            candidates.append(" ".join(seq))
        elif isinstance(node, ast.Call) and (txt := _call_arg_text(node, env)):
            candidates.append(txt)
    return any(any(m in c for m in _WIN_API_MARKERS) or is_shutdown_cmd(c) for c in candidates)


def is_wingui_launch_blocked(cmd_line: str) -> bool:
    s = (cmd_line or "").strip()
    if not s:
        return False
    if is_shutdown_cmd(s):
        return True
    exe = s.split(" -- ", 1)[0].strip().strip('"').strip("'")
    if _WINGUI_BLOCKED_EXE.search(exe):
        return True
    first = s.split(None, 1)[0].strip('"').strip("'")
    if _WINGUI_BLOCKED_EXE.search(first):
        return True
    return False


def _ver_int(raw: str) -> int:
    s = re.sub(r"^v", "", str(raw or "").strip())
    s = re.sub(r"-\d+$", "", s)
    return int(s) if s.isdigit() else 0


def pending_deploy_path() -> Path:
    return Path(os.environ.get("ARK_PENDING_DEPLOY") or (Path.home() / ".cache/ark-relay/pending_deploy.json"))


def ledger_path() -> Path:
    return Path(os.environ.get("ARK_LEDGER") or (Path.home() / "Money/styl-work/BOARD/verify-ledger.jsonl"))


def is_blocking_ledger_item(item: dict, now_local: dt.datetime | None = None) -> bool:
    if item.get("status") != "open":
        return False
    kind = str(item.get("kind") or "")
    what = str(item.get("what") or "")
    if kind in ("pending_deploy", "alert") or "群报警" in what:
        return True
    opened = str(item.get("opened") or "").strip()
    if opened:
        try:
            op_dt = dt.datetime.strptime(opened[:16], "%Y-%m-%d %H:%M")
            cur = now_local or dt.datetime.now()
            if (cur - op_dt).total_seconds() <= 48 * 3600:
                return True
        except ValueError:
            pass
    return False


def reconcile_pending_file(cur_ver: int) -> list[dict]:
    p = pending_deploy_path()
    if not p.exists():
        return []
    lock_p = p.with_name(p.name + ".lock")
    lock_p.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_p, "a+", encoding="utf-8") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            raw = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
            items = raw if isinstance(raw, list) else []
        except (OSError, ValueError):
            return [{"version": "corrupt"}]
        kept = [x for x in items if _ver_int(x.get("version", "")) > cur_ver]
        if len(kept) != len(items):
            tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, p)
        return kept


def check_local(repo: Path) -> str | None:
    lp = ledger_path()
    if lp.exists():
        try:
            now_local = dt.datetime.now()
            blockers = []
            for ln in lp.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                item = json.loads(ln)
                if is_blocking_ledger_item(item, now_local):
                    blockers.append(f"#{item.get('id')}({str(item.get('what', ''))[:30]})")
            if blockers:
                return f"账本仍有阻断型未结案项：{'、'.join(blockers[:4])}"
        except (OSError, ValueError) as exc:
            return f"账本读取失败（{type(exc).__name__}）"
    r = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "-uall", "--", *RUNTIME_PATHS],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        return f"本地 git status 失败（rc={r.returncode}）"
    dirty = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    if dirty:
        return f"本地中继运行文件有未提交改动（{len(dirty)} 项，如 {dirty[0]}）"
    return None


def _probe_remote_version(user_at: str) -> tuple[int, str]:
    # 第 1 层北京时间断电硬锁：08:40–08:45 严禁通过 SSH 探活游戏机（RC=78）
    _lib_dir = str(Path(__file__).resolve().parent)
    if _lib_dir not in sys.path:
        sys.path.insert(0, _lib_dir)
    import powercut_guard as _pcg  # noqa: PLC0415
    _pcg.guard_or_exit(1, "shutdown_guard.py")
    # One read-only SSH probe: current.txt first, fallback to legacy state.json versions.code.
    cmd = (
        'if exist "C:\\Program Files\\ArkRelay\\current.txt" '
        '(type "C:\\Program Files\\ArkRelay\\current.txt") '
        'else (type "C:\\ProgramData\\ark-relay\\state\\state.json")'
    )
    try:
        r = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=15", "-o", "BatchMode=yes", user_at, cmd],
            capture_output=True, text=True, timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 0, f"SSH 核验远端版本失败（{type(exc).__name__}）"
    out = (r.stdout or "").strip()
    if not out:
        return 0, f"远端版本读不到（SSH rc={r.returncode}）"
    if out.startswith("{"):
        try:
            ver = _ver_int(str((json.loads(out).get("versions") or {}).get("code") or ""))
            return (ver, "") if ver else (0, "state.json 里没有有效的 versions.code")
        except ValueError:
            return 0, "state.json 无法解析"
    first = out.splitlines()[0].strip()
    ver = _ver_int(first)
    return (ver, "") if ver else (0, f"current.txt 内容异常：{first!r}")


def _manifest_stale_non_notes(repo: Path, cur_ver: int) -> str | None:
    mp = repo / "relay" / "manifest.json"
    if not mp.is_file():
        return "找不到 relay/manifest.json"
    try:
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        mver = _ver_int(str(manifest.get("version") or ""))
    except (OSError, ValueError) as exc:
        return f"manifest.json 读不出（{type(exc).__name__}）"
    if mver > cur_ver:
        return f"本地 manifest v{mver} 新于机上 v{cur_ver}"
    relay_dir = repo / "relay"
    stale = [
        rel for rel, sha in sorted((manifest.get("files") or {}).items())
        if rel != "RELEASE-NOTES.md"
        and (not (relay_dir / rel).is_file()
             or hashlib.sha1((relay_dir / rel).read_bytes()).hexdigest() != sha)
    ]
    if stale:
        return f"本地有未打进 manifest 的运行文件改动：{', '.join(stale[:4])}"
    return None


def check_ssh1(repo: Path, user_at: str) -> str | None:
    cur_ver, err = _probe_remote_version(user_at)
    if err or cur_ver <= 0:
        return err or "远端版本未知"
    rem = reconcile_pending_file(cur_ver)
    if rem:
        vers = "、".join(f"v{x.get('version', '?')}" for x in rem[:4])
        return f"仍有待上机实装版本未核销：{vers}（机上当前 v{cur_ver}）"
    tag = f"relay-{cur_ver}"
    has_tag = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
        capture_output=True, text=True, timeout=10,
    ).returncode == 0
    if not has_tag:
        return _manifest_stale_non_notes(repo, cur_ver)
    for ref in ("HEAD", "main", "origin/main"):
        exists = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "-q", "--verify", ref],
            capture_output=True, text=True, timeout=10,
        ).returncode == 0
        if not exists:
            continue
        is_anc = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", ref, tag],
            capture_output=True, text=True, timeout=10,
        ).returncode == 0
        if is_anc:
            continue
        diff = subprocess.run(
            ["git", "-C", str(repo), "diff", "--quiet", f"{tag}...{ref}", "--", *RUNTIME_PATHS],
            capture_output=True, text=True, timeout=15,
        )
        if diff.returncode != 0:
            return f"分支 {ref} 领先于机上 {tag} 且包含未上机部署的中继运行改动"
    return None


def ps_atomic_guard_snippet(busy_names: str, out_file: str = "") -> str:
    tail = (
        f"if ($__refused) {{ [IO.File]::WriteAllText('{out_file}', 'WINPS_REFUSED: ' + $__refused, "
        "(New-Object Text.UTF8Encoding($false))); exit 0 }"
        if out_file
        else "if ($__refused) { 'WINPS_REFUSED: ' + $__refused; return }"
    )
    return (
        "$__refused = & { $ErrorActionPreference = 'Stop'; try { "
        f"$__busy = @(Get-Process -Name {busy_names} -ErrorAction SilentlyContinue "
        "| ForEach-Object { $_.ProcessName } | Sort-Object -Unique); "
        "if ($__busy.Count) { return ('任务在跑: ' + ($__busy -join ', ')) }; "
        "$__sf = 'C:\\ProgramData\\ark-relay\\state\\state.json'; "
        "if (Test-Path -LiteralPath $__sf) { "
        "$__st = Get-Content -LiteralPath $__sf -Raw -Encoding UTF8 | ConvertFrom-Json; "
        "$__ah = $null; "
        "if ($null -ne $__st -and $null -ne $__st.modes) { $__ah = $__st.modes.alarm_hold }; "
        "if ($null -ne $__ah) { "
        "$__u = $__ah.until; "
        "if ($null -eq $__u -or ([string]$__u).Trim() -eq '') { return '故障留机锁状态损坏(缺少 until)' }; "
        "if ($__u -is [DateTime]) { "
        "$__end = if ($__u.Kind -ne 'Unspecified') { $__u.ToUniversalTime().AddHours(8) } else { $__u } "
        "} else { "
        "$__end = [DateTime]::ParseExact(([string]$__u).Trim(), 'yyyy-MM-dd HH:mm', [Globalization.CultureInfo]::InvariantCulture) "
        "}; "
        "if ([DateTime]::UtcNow.AddHours(8) -lt $__end) { "
        "$__why = if ($__ah.reason) { [string]$__ah.reason } else { '有未修完的故障报警' }; "
        "return ('故障留机锁生效至 ' + $__end.ToString('yyyy-MM-dd HH:mm') + ' (' + $__why + ')') "
        "} } }; return $null "
        "} catch { return ('状态文件读不出或损坏: ' + $_.Exception.Message) } }; "
        + tail
    )


def log_override(caller: str, reason: str) -> None:
    log_env = os.environ.get("ARK_ACTION_LOG", "")
    if log_env == "/dev/null":
        return
    path = Path(log_env) if log_env else (Path.home() / ".cache/ark-relay/mac_actions.log")
    try:
        old_umask = os.umask(0o077)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            ts = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
            clean = re.sub(r"[\r\n\t]+", " ", reason)[:200]
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{ts}\t{caller}\tOVERRIDE {clean}\n")
            os.chmod(path, 0o600)
        finally:
            os.umask(old_umask)
    except OSError:
        pass


def _run_preflight(argv: list[str]) -> int:
    kind, caller, repo_s, user_at, busy, out_file = argv[1:7]
    if kind in ("ps", "cmd"):
        is_sd = is_shutdown_cmd(sys.stdin.read())
    elif kind in ("py", "py1"):
        py_path = Path(argv[7])
        extra = argv[8] if len(argv) > 8 else ""
        is_sd = is_shutdown_py_source(py_path.read_text(encoding="utf-8", errors="replace"), extra)
    elif kind == "launch":
        is_sd = is_wingui_launch_blocked(argv[7] if len(argv) > 7 else "")
    else:
        return 2
    if not is_sd:
        return 0
    override = os.environ.get("ARK_SHUTDOWN_OVERRIDE", "")
    if override:
        log_override(caller, override)
        print(f"{caller}: shutdown guard overridden: {override}", file=sys.stderr)
        return 0
    if kind == "launch":
        print(f"{caller}: 拒绝通过 launch 启动高危或关机相关程序：{argv[7] if len(argv) > 7 else ''}。", file=sys.stderr)
        return 5
    repo = Path(repo_s)
    if why := check_local(repo):
        print(f"{caller}: 拒绝关机——{why}。请先修完、上机部署并通过核验。", file=sys.stderr)
        return 5
    if os.environ.get("WINRUN_DRY_RUN") and kind == "py":
        return 0
    if why := check_ssh1(repo, user_at):
        print(f"{caller}: 拒绝关机——{why}。禁止先关机再等下次开机自更新。", file=sys.stderr)
        return 5
    if busy:
        sys.stdout.write(ps_atomic_guard_snippet(busy, out_file))
    return 10


def main(argv: list[str]) -> int:
    if not argv:
        return 2
    cmd = argv[0]
    if cmd == "preflight":
        return _run_preflight(argv)
    if cmd == "detect":
        kind = argv[1]
        if kind in ("ps", "cmd"):
            text = sys.stdin.read() if len(argv) < 3 else argv[2]
            return 0 if is_shutdown_cmd(text) else 1
        if kind in ("py", "py1"):
            p = Path(argv[2])
            extra = argv[3] if len(argv) > 3 else ""
            return 0 if is_shutdown_py_source(p.read_text(encoding="utf-8", errors="replace"), extra) else 1
        if kind == "launch":
            text = argv[2] if len(argv) > 2 else ""
            return 0 if is_wingui_launch_blocked(text) else 1
        return 2
    if cmd == "check-local":
        repo = Path(argv[1])
        why = check_local(repo)
        if why:
            print(why, file=sys.stderr)
            return 5
        return 0
    if cmd == "check-ssh1":
        repo = Path(argv[1])
        user_at = argv[2]
        why = check_ssh1(repo, user_at)
        if why:
            print(why, file=sys.stderr)
            return 5
        return 0
    if cmd == "ps-snippet":
        busy = argv[1]
        out_file = argv[2] if len(argv) > 2 else ""
        sys.stdout.write(ps_atomic_guard_snippet(busy, out_file))
        return 0
    if cmd == "log-override":
        log_override(argv[1], argv[2] if len(argv) > 2 else "")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
