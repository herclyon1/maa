"""Keep AUTO-MAS's job-object fallback in AUTO-MAS's own Python (Gemini's 中继-晚班补跑误报超时与Job钩子自愈-1109).

From 2026-11-08 21:30 AUTO-MAS's starts of MAA, MAA's updater and the game update check each
failed with (5, 'AssignProcessToJobObject', '拒绝访问。'). Session 2499's fallback wraps win32job
inside AUTO-MAS's Python: a refused assignment goes to a fresh job, and when that is refused
too the child runs outside any job instead of failing. Editing AUTO-MAS's
repo/app/utils/windows/process.py does not hold - auto-mas-runtime puts D:\\ark\\automas\\repo
back to upstream at every start (2026-11-09 00:35) - so the fallback lives in the venv's
site-packages: a module, and a .pth that imports it when the interpreter starts. An AUTO-MAS
update that rebuilds the venv drops both; the relay puts them back at every boot and after
it installs a new AUTO-MAS (boot_stages._automas_jobfix).

The two files ship byte for byte as session 2499 installed and tried them on the machine on
2026-11-09 (automas_files/*.txt, .txt so the linters do not compile AUTO-MAS-side code). That
try showed the hook loads; it did not reproduce the refusal (without the hook the re-assignment
into a terminated job also succeeded), so whether it cures the 21:30 failure is still open. A
.pth is read at interpreter start: a file put back takes effect at AUTO-MAS's next backend
start, not in the one already running.
"""
from __future__ import annotations

from pathlib import Path

from ark_relay.core.config import atomic_write_bytes

# AUTO-MAS's own interpreter, under its install folder (cfg.automas_dir, D:\ark\automas).
SITE_PACKAGES = ("runtime", "environment", "venv", "Lib", "site-packages")
FILES = ("zz_automas_job_fix.py", "zz_automas_job_fix.pth")
_PAYLOAD = Path(__file__).with_name("automas_files")


def payload(name: str) -> bytes:
    """The bytes the relay keeps for one of FILES."""
    return (_PAYLOAD / f"{name}.txt").read_bytes()


def site_dir(automas_dir) -> Path | None:
    """AUTO-MAS's venv site-packages; None with no AUTO-MAS folder or no such directory."""
    if not automas_dir:
        return None
    p = Path(automas_dir).joinpath(*SITE_PACKAGES)
    return p if p.is_dir() else None


def heal(automas_dir) -> list[str]:
    """Put back each of FILES that is missing or differs; the names put back, [] when both
    were right or there is no site-packages to put them in.

    A file already right is not written (not even its mtime touched). Raises OSError when a
    write fails or the file read back differs from the payload: the fallback is then not in
    place and the caller says so."""
    site = site_dir(automas_dir)
    if site is None:
        return []
    put: list[str] = []
    for name in FILES:
        want, dest = payload(name), site / name
        try:
            if dest.read_bytes() == want:
                continue
        except OSError:
            pass          # missing (or unreadable): written below
        atomic_write_bytes(dest, want)
        if dest.read_bytes() != want:
            raise OSError(f"{dest} 写进去读回来不一样")
        put.append(name)
    return put
