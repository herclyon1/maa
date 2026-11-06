"""The upstream source evidence.py mirrors, pinned by hash.

Each Pin names an upstream file, the commit it was read at and the sha256 of
the function bodies the bundlers in bundles.py copy. `check_sources()` fetches
the same files from the upstream default branch through jsDelivr and reports
which pins no longer match. Fixture copies live in tests/fixtures/source-pins/;
renew both when re-verifying.
"""
from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Pin:
    name: str
    repo: str
    branch: str
    path: str
    commit: str
    sha256: str
    # The functions whose bodies are what this relay mirrors. Only their text is
    # hashed, so a change elsewhere in the upstream file does not count.
    regions: tuple[str, ...] = ()


_HEADER = {
    ".cs": r"^\s*(?:public|private|internal|protected|static|async|override|virtual|sealed|\s)*[\w<>\[\]?]+\s+{name}\s*(?:<[^>]*>)?\s*\(",
    ".rs": r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+{name}\b",
    ".py": r"^\s*def\s+{name}\s*\(",
}


def region_text(raw: str, path: str, names: tuple[str, ...]) -> str:
    """The bodies of `names` in `raw`, joined, in the given order.

    Brace languages: from the header to the brace that closes the one opened after
    it. Python: from the header to the last line indented deeper than it. A name
    that is not found contributes the marker `<missing NAME>`, so a renamed function
    changes the hash instead of silently shrinking the pinned text.
    """
    ext = path[path.rfind("."):]
    lines = raw.splitlines()
    out = []
    for name in names:
        pat = re.compile(_HEADER[ext].format(name=re.escape(name)))
        start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
        if start is None:
            out.append(f"<missing {name}>")
            continue
        if ext == ".py":
            indent = len(lines[start]) - len(lines[start].lstrip())
            end = start
            for i in range(start + 1, len(lines)):
                ln = lines[i]
                if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
                    break
                end = i
            out.append("\n".join(lines[start:end + 1]))
            continue
        depth, seen, end = 0, False, start
        for i in range(start, len(lines)):
            for ch in lines[i]:
                if ch == "{":
                    depth += 1; seen = True
                elif ch == "}":
                    depth -= 1
            if seen and depth == 0:
                end = i
                break
        out.append("\n".join(lines[start:end + 1]))
    return "\n\n".join(out)


def pinned_text(pin: "Pin", raw: bytes) -> bytes:
    """What gets hashed for `pin`: the named regions when it has any, else the file."""
    if not pin.regions:
        return raw
    return region_text(raw.decode("utf-8", "replace"), pin.path, pin.regions).encode("utf-8")


PINS = (
    Pin("MaaEnd 导出（MXU file_ops.rs）", "MistEO/MXU", "main",
        "src-tauri/src/commands/file_ops.rs",
        "316ac0f6fb0ba7dd1187f8667c4a50b1b159db35",
        "1573c2683360d9056d3eb39ca7fdaae4afe1e822134cdb00ca264fa4f0cff849",
        ("export_logs_blocking", "collect_files_recursively", "collect_debug_subdir_files",
         "add_file_to_zip", "normalize_archive_path", "is_image_file", "has_extension",
         "estimate_compressed_upper_bound", "pre_compress_measure")),
    Pin("MAA 生成日志压缩包（IssueReportUserControlModel.cs）",
        "MaaAssistantArknights/MaaAssistantArknights", "dev-v2",
        "src/MaaWpfGui/ViewModels/UserControl/Settings/IssueReportUserControlModel.cs",
        # GenerateSupportPayload is `public async Task`: the C# header pattern in
        # _HEADER accepts `async` for it.
        "53870a7a5214c04ae25abd5a02f0bcfb8ad99507",
        "c392771bccda4f98eb1caa22404d37491c8c8c8414e94e001198c6357c2dafaa",
        ("GenerateSupportPayload", "CopyDirectoryIfExists")),
    Pin("OK-WW Export Logs（ok-script diagnostics.py）", "ok-oldking/ok-script", "master",
        "ok/ui/qt/shell/diagnostics.py",
        "f90444e11713496bd41de389a886501673531bad",
        "d43f0e28ce473e881945ede50ee7aaa8a9c73bcbc3ff4a9e788189b24804230c",
        ("export_logs",)),
)


JSDELIVR = "https://cdn.jsdelivr.net/gh/{repo}@{branch}/{path}"


def check_sources(fetch=None, timeout: int = 30) -> tuple[list[str], list[str]]:
    """(changed pin names, unreachable pin names) against the upstream default branches."""
    def _get(url: str) -> bytes:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    fetch = fetch or _get
    changed, unreachable = [], []
    LAST_SEEN.clear()
    LAST_ERRORS.clear()
    for pin in PINS:
        try:
            raw = fetch(JSDELIVR.format(repo=pin.repo, branch=pin.branch, path=pin.path))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            unreachable.append(pin.name)
            LAST_ERRORS[pin.name] = f"{type(exc).__name__}: {getattr(exc, 'reason', None) or exc}"
            continue
        seen = hashlib.sha256(pinned_text(pin, raw)).hexdigest()
        LAST_SEEN[pin.name] = seen
        if seen != pin.sha256:
            changed.append(pin.name)
    return changed, unreachable


# Fingerprint of each pin as last fetched by check_sources(), so the boot stage
# can tell "the same change as yesterday" from a new one.
LAST_SEEN: dict[str, str] = {}

# Why each unreachable pin could not be fetched in the last check_sources(),
# for the boot log line (audit s17 F5: the reason was swallowed).
LAST_ERRORS: dict[str, str] = {}
