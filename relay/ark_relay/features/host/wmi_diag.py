"""What the relay says when the WMI process-start listener drops: uptime, winmgmt's PID and hosts, the SCM events and the HRESULT behind the failure, and durations in words.

Split out of relay/service.py (2026-10-11); behaviour unchanged.
"""
from __future__ import annotations

import subprocess

import win32api
import win32service


def _span(seconds: float) -> str:
    """A duration in words: 「45 秒」 under two minutes, 「12 分钟」 after."""
    seconds = max(0.0, float(seconds))
    return f"{seconds:.0f} 秒" if seconds < 120 else f"{seconds / 60:.0f} 分钟"


def _uptime() -> str:
    """Time since Windows booted, h:mm:ss, or '?' where it cannot be read."""
    try:
        import ctypes  # noqa: PLC0415
        k = ctypes.windll.kernel32
        k.GetTickCount64.restype = ctypes.c_ulonglong   # 64-bit; do not truncate
        s = int(k.GetTickCount64()) // 1000
    except Exception:  # noqa: BLE001 - not Windows
        return "?"
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def _winmgmt_pid() -> "int | None":
    """The WMI service's process id, as the SCM reports it; None when it cannot be read (0 when it is not running)."""
    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            h = win32service.OpenService(scm, "winmgmt", win32service.SERVICE_QUERY_STATUS)
            try:
                return int(win32service.QueryServiceStatusEx(h)["ProcessId"])
            finally:
                win32service.CloseServiceHandle(h)
        finally:
            win32service.CloseServiceHandle(scm)
    except Exception:  # noqa: BLE001 - diagnostics and an optional wait handle only
        return None


def _wmi_hosts() -> str:
    """The WMI service's process id and every WmiPrvSE.exe provider host's, right now.

    Taken when the listener subscribes and again when it drops: a changed
    winmgmt pid means the WMI service itself restarted, a WmiPrvSE pid that is
    gone means a provider host died under the subscription. Neither is read
    through WMI, which may be the very thing that just broke.
    """
    parts = []
    pid = _winmgmt_pid()
    parts.append(f"winmgmt pid {pid}" if pid is not None else "winmgmt pid ?")
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WmiPrvSE.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, timeout=25).stdout.decode("ascii", "replace")
        pids = sorted(int(row.split('","')[1]) for row in out.splitlines()
                      if row.lower().startswith('"wmiprvse.exe"'))
        parts.append("WmiPrvSE pids " + (",".join(map(str, pids)) or "none"))
    except Exception:  # noqa: BLE001 - diagnostics only
        parts.append("WmiPrvSE pids ?")
    return "; ".join(parts)


def _wmi_pids(hosts: str) -> "tuple[str | None, set[str] | None]":
    """(winmgmt pid, WmiPrvSE pids) out of a _wmi_hosts() string; None for a part it could not read."""
    import re  # noqa: PLC0415
    m = re.search(r"winmgmt pid (\d+)", hosts or "")
    svc = m.group(1) if m else None
    m = re.search(r"WmiPrvSE pids ([\d,]+|none)", hosts or "")
    prv = None if not m else (set() if m.group(1) == "none" else set(m.group(1).split(",")))
    return svc, prv


def _wmi_hypothesis(at_subscribe: str, now: str) -> str:
    """Which of the causes _wmi_hosts tells apart fits a dropped subscription.

    H1: the WMI service itself restarted (its winmgmt pid changed); H2: a
    WmiPrvSE provider host that was there at subscribe is gone; H3: neither
    changed. 'unknown' when either reading could not be taken. The diag line
    carries it, so the log names the case without a person comparing pids.
    """
    svc0, prv0 = _wmi_pids(at_subscribe)
    svc1, prv1 = _wmi_pids(now)
    if svc0 is None or svc1 is None or prv0 is None or prv1 is None:
        return "unknown (WMI hosts unreadable)"
    if svc0 != svc1:
        return f"H1 WMI service restarted (winmgmt pid {svc0} -> {svc1})"
    if gone := sorted(prv0 - prv1, key=int):
        return f"H2 WMI provider host gone (WmiPrvSE pid {','.join(gone)})"
    return "H3 WMI service and provider hosts unchanged"


# How far back the System log is read when the subscription drops. The two drops
# of 10-06 (16:16:59, 18:08:22) came 18-19 s after subscribing; five minutes
# covers whatever stopped or crashed winmgmt before that.
SCM_LOOKBACK_MS = 300_000


# Service Control Manager events that say what happened to a service:
# 7031/7034 it terminated unexpectedly, 7036 it entered running/stopped,
# 7040 its start type was changed, 7009/7011 a start or a control timed out.
SCM_EVENT_IDS = {"7009", "7011", "7031", "7034", "7036", "7040"}


def _scm_winmgmt(xml: str, limit: int = 8) -> str:
    """The winmgmt lines out of `wevtutil qe System /f:xml` output, oldest first.

    An SCM event names the service in its EventData (the display name, or the key
    name in 7040) and, for 7036, in <Binary> as UTF-16LE hex of 「winmgmt/N」 - so
    both are looked at, and the display name is not trusted alone on a Chinese
    Windows. Returns 「SCM winmgmt: none in 5 min」 when nothing matched.
    """
    import re  # noqa: PLC0415
    rows = []
    for ev in re.findall(r"<Event[ >].*?</Event>", xml or "", re.S):
        eid = re.search(r"<EventID[^>]*>(\d+)</EventID>", ev)
        if not eid or eid.group(1) not in SCM_EVENT_IDS:
            continue
        data = [d.strip() for d in re.findall(r"<Data[^>]*>([^<]*)</Data>", ev)]
        names = " ".join(data).lower()
        b = re.search(r"<Binary>([0-9A-Fa-f]+)</Binary>", ev)
        if b:
            try:
                names += " " + bytes.fromhex(b.group(1)).decode("utf-16-le", "replace").lower()
            except ValueError:
                pass
        if "winmgmt" not in names and "windows management instrumentation" not in names:
            continue
        t = re.search(r"SystemTime=['\"]([^'\"]+)['\"]", ev)
        rows.append(f"{eid.group(1)} {t.group(1)[11:19] if t else '?'}Z {'|'.join(d for d in data if d)}")
    if not rows:
        return "SCM winmgmt: none in 5 min"
    return "SCM winmgmt: " + "; ".join(rows[-limit:])


def _wmi_scm_events() -> str:
    """What the System log says happened to winmgmt in the last SCM_LOOKBACK_MS.

    The diag's H1 (winmgmt pid changed) says the WMI service restarted but not
    why - stopped by someone, crashed (7031/7034), or a start type change. Read
    with wevtutil, not through WMI, for the same reason as _wmi_hosts.
    """
    q = ("*[System[Provider[@Name='Service Control Manager'] and "
         f"TimeCreated[timediff(@SystemTime) <= {SCM_LOOKBACK_MS}]]]")
    try:
        raw = subprocess.run(["wevtutil", "qe", "System", f"/q:{q}", "/f:xml"],
                             capture_output=True, timeout=10).stdout
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        return f"SCM winmgmt: unreadable ({type(exc).__name__})"
    # What the match needs (EventID, 「winmgmt」, the Binary hex) is ASCII, so any
    # byte-for-byte codec reads it; only a UTF-16 pipe would hide it behind NULs.
    # The Chinese in Data may come in the console code page (936) rather than UTF-8.
    if b"\x00" in raw[:200]:
        text = raw.decode("utf-16-le", "replace")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("gbk", "replace")
    return _scm_winmgmt(text)


def _wmi_error(exc: BaseException) -> "tuple[str, str]":
    """(what the user is told, the full record for relay.log) for one listener failure.

    A COM error carries two codes: the outer one is DISP_E_EXCEPTION
    (0x80020009, 「发生意外」); the one that says what happened is the scode in
    its excepinfo - 0x800706BE 「远程过程调用失败」 in every case on record
    (docs/PITFALLS.md). Windows' own Chinese text for it is quoted; English text
    (another locale, or a Python error) stays in relay.log only.
    """
    import traceback  # noqa: PLC0415
    if type(exc).__name__ != "com_error":
        return ("不是系统返回的错误，原文见中继日志",
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)[-3:]).strip())
    args = tuple(exc.args) + (None,) * 4
    hresult, outer, info = args[0], args[1], args[2]
    info = tuple(info) + (None,) * 6 if isinstance(info, (tuple, list)) else (None,) * 6
    scode = info[5] if isinstance(info[5], int) and info[5] else hresult
    text = str(info[2] or outer or "").strip()
    code = f"0x{int(scode or 0) & 0xFFFFFFFF:08X}"
    detail = (f"hresult 0x{int(hresult or 0) & 0xFFFFFFFF:08X}, scode {code}, "
              f"source {info[1] or '-'}, text {text or '-'}")
    return _said_with_code(text, code), detail


def _said_with_code(text: str, code: str) -> str:
    """Windows' own Chinese words for an error with its code, or the code alone when the words are not plain Chinese."""
    said = text.strip().rstrip("。. ")
    plain = said and not any(c.isascii() and c.isalpha() for c in said)
    return f"{said}，{code}" if plain else f"错误码 {code}"


def _hresult_failure(hresult) -> "tuple[str, str]":
    """(what the user is told, the full record) for an asynchronous call that ended with `hresult`.

    The asynchronous subscription reports its end through SWbemSink.OnCompleted
    (iHResult: "If the asynchronous call fails, this parameter contains an error
    code", https://learn.microsoft.com/en-us/windows/win32/wmisdk/swbemsink-oncompleted)
    rather than as a com_error, so there is no excepinfo text: the system
    message table supplies it (FormatMessage knows 0x800706BE, 「远程过程调用失败。」,
    on this machine's Chinese Windows; WMI's own 0x8004xxxx codes are not in it
    and are said as the code alone). Same shape as _wmi_error, so the drop
    lines and their diag read as before.
    """
    raw = int(hresult or 0) & 0xFFFFFFFF
    code = f"0x{raw:08X}"
    try:
        # pywin32 takes the code as a signed 32-bit int, the way COM hands iHResult over.
        text = str(win32api.FormatMessage(raw - (1 << 32) if raw >= 1 << 31 else raw)).strip()
    except Exception:  # noqa: BLE001 - not in the system message table
        text = ""
    return _said_with_code(text, code), f"hresult {code}, scode {code}, source SWbemSink.OnCompleted, text {text or '-'}"
