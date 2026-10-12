"""Are the tools we run on the Mac and the game machine the newest of their line? Prints, never blocks.

The user, 10-12 08:34, asked whether every tool used on the Mac or the game machine is the
newest, and whether anything checks.
Until then only the relay's three bundled parts were checked (parts_latest.py, D-1011 tools
current) and the Mac's Python sat at 3.14.7 with 3.14.8 out. This lists every other tool our
scripts, hooks and remote-ref tools actually invoke (inventory by grep, 10-12), with the
version it reports itself, the newest from the official source, and that source's URL:

  Mac       Python 3.14 / 3.13 (uv-managed, ~/.local/bin; python.org/ftp, same 3.N, the source
            tarball must be there), uv, ruff and pyflakes as uvx resolves them (PyPI),
            shellcheck, gh, swiftly, Hammerspoon, jq (GitHub releases of the official repo),
            git (/usr/bin, Apple's; compared with Homebrew's git - the way to a newer one),
            Homebrew itself (GitHub), the Homebrew formulae installed on request plus gradle
            and openjdk that ark-release.sh runs (formulae.brew.sh), Xcode and macOS (Apple's
            developer releases feed, betas and RCs skipped; a Mac on a beta build - in a beta
            entry of the feed, or ahead of the newest final - is compared with the newest entry of its major,
            betas included, by build), Swift via swiftly (swift.org),
            Tailscale (pkgs.tailscale.com), adb (Google's platform-tools repository).
  machine   pwsh 7 (GitHub PowerShell), the running sshd (GitHub Win32-OpenSSH; the Windows
            capability in System32 updates through Windows Update), Tailscale, LDPlayer (no
            machine-readable feed: manual) and the adb it bundles (follows LDPlayer: a newer
            adb than the emulator's own server makes them restart each other), and the
            installed relay runtime's Python / Pillow / pywin32 (newest of line by
            parts_latest's own rules - the repo pins are parts_latest.py's job).
Not here: the four game programs (they update themselves, D-1011), Claude Code's own ripgrep
(a shell function of Claude Code, not ours), AUTO-MAS's Python (part of AUTO-MAS).

Rows: `✓ name have → newest (url)`, `⬆` = behind, `?` = could not ask (why), `·` = no
machine-readable source or follows another row (url to look at). Behind rows go into the
relay's technical log on the machine as red items (scripts/mac/techlog.py red reads them; we
upgrade, mark handled with the commit) - not the group, not the daily report. One item per
tool and installed version: a row already open there is not written again.

deploy-relay.sh runs this right after parts_latest.py and ignores the exit code; it needs the
network (about 8 unauthenticated GitHub API calls of the 60 an hour allows), so it is not part
of lint-repo.sh.

    python3 scripts/mac/lib/tools_latest.py [--no-techlog]
Exit 0 always.
"""
from __future__ import annotations

import importlib.util
import json
import plistlib
import re
import subprocess
import sys
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pl = _load("parts_latest", HERE / "parts_latest.py")
tl = _load("techlog", ROOT / "scripts/mac/techlog.py")

HOME = Path.home()
GH = "https://api.github.com/repos/{}/releases/latest"
GH_PAGE = "https://github.com/{}/releases/latest"
PYPI_PAGE = "https://pypi.org/project/{}/"
BREW_F = "https://formulae.brew.sh/api/formula/{}.json"
BREW_C = "https://formulae.brew.sh/api/cask/{}.json"
APPLE_RSS = "https://developer.apple.com/news/releases/rss/releases.rss"
SWIFT_JSON = "https://www.swift.org/api/v1/install/releases.json"
TAILSCALE_JSON = "https://pkgs.tailscale.com/stable/?mode=json"
ANDROID_REPO = "https://dl.google.com/android/repository/repository2-3.xml"
LDPLAYER_PAGE = "https://www.ldmnq.com/"
APP = r"C:\Program Files\ArkRelay"          # packaging/ark-relay.iss DefaultDirName={autopf}\ArkRelay
LD_DIR = r"D:\LD-MRFZ\LDPlayer9"           # scripts/windows/emu-start.py LD, adbdo.sh ADB
TECH_HEADING = "tools behind (scripts/mac/lib/tools_latest.py)"
SERVER_TZ = "Asia/Shanghai"                # the tech log's days and ids are Beijing time
NUM = re.compile(r"\d+(?:\.\d+)+|\d+")


class Row:
    def __init__(self, name: str, have: str, newest: str, source: str, mark: str = "",
                 why: str = "", hint: str = ""):
        self.name, self.have, self.newest, self.source = name, have, newest, source
        self.why, self.hint = why, hint
        self.mark = mark or ("✓" if is_current(have, newest) else "⬆")

    def line(self) -> str:
        if self.mark == "?":
            return f"  ? {self.name} {self.have or '-'}: could not ask ({self.why}) ({self.source})"
        if self.mark == "·":
            return f"  · {self.name} {self.have or '-'}: {self.why} ({self.source})"
        tail = f" - {self.hint}" if self.mark == "⬆" and self.hint else ""
        return f"  {self.mark} {self.name} {self.have} → {self.newest} ({self.source}){tail}"


# ---- pure parsing (tested with canned input in relay/tests/test_tool_refs.py) ----

def clean(text: str) -> str:
    """The first dotted version in a tool's output: 'git version 2.54.0 (Apple Git-157)' -> 2.54.0."""
    m = NUM.search(text or "")
    return m.group(0) if m else ""


def vtuple(v: str) -> "tuple[int, ...]":
    t = [int(x) for x in re.findall(r"\d+", v)]
    while len(t) > 1 and t[-1] == 0:
        t.pop()
    return tuple(t)


def is_current(have: str, newest: str) -> bool:
    """have >= newest, numerically ('27.0' == '27'); a release candidate we run counts as current."""
    if not have or not newest:
        return False
    return vtuple(have) >= vtuple(newest)


def gh_tag(data: dict) -> str:
    """'v2.97.0' / 'jq-1.8.2' / '10.0.0.0p2-Preview' -> the version numbers."""
    return clean(re.sub(r"^[A-Za-z_-]*", "", data.get("tag_name", "")))


def apple_latest(rss: str, product: str) -> str:
    """Newest final '<product> X.Y' in Apple's releases feed (betas and RCs skipped; newest first)."""
    for title in re.findall(r"<title>([^<]*)</title>", rss):
        m = re.match(rf"^{re.escape(product)} (\d+(?:\.\d+)*)(.*)$", title.strip())
        if m and not re.search(r"\b(beta|RC|Release Candidate)\b", m.group(2), re.I):
            return m.group(1)
    return ""


def apple_newest_seed(rss: str, product: str, major: str) -> "tuple[str, str]":
    """Newest '<product> <major>.x' entry of any kind (final, RC or beta) in Apple's releases feed,
    as (label, build): ('27.2 beta 3', '26B5101f'). For a Mac on a beta build, whose Software
    Update offers the next seed: what it should be on is the newest entry of its own major."""
    for title in re.findall(r"<title>([^<]*)</title>", rss):
        m = re.match(rf"^{re.escape(product)} ({re.escape(major)}(?:\.\d+)*(?: [^()]*?)?)\s*\(([0-9A-Za-z]+)\)$",
                     title.strip())
        if m:
            return m.group(1).strip(), m.group(2)
    return "", ""


def on_seed(rss: str, product: str, have: str, build: str) -> bool:
    """Is this a beta / RC install? Its build is in a beta or RC entry of the feed, or its version is
    ahead of the newest final one (an older seed that has left the feed). Not judged from the build's
    shape: final builds can end in a letter too (Xcode 27 is 27A266a)."""
    for title in re.findall(r"<title>([^<]*)</title>", rss):
        if build and f"({build})" in title and title.strip().startswith(product + " "):
            return bool(re.search(r"\b(beta|RC|Release Candidate)\b", title, re.I))
    final = apple_latest(rss, product)
    return bool(final) and vtuple(have) > vtuple(final)


def swift_latest(data: list) -> str:
    """swift.org releases.json -> the highest final release name."""
    names = [r.get("name", "") for r in data]
    return max((n for n in names if pl.FINAL.match(n)), key=vtuple, default="")


def brew_stable(data: dict, revision: bool = True) -> str:
    """formulae.brew.sh formula JSON -> 'stable', with Homebrew's _revision when there is one
    (brew's installed version carries it too); revision=False for comparing with a non-brew build."""
    v = data.get("versions", {}).get("stable", "")
    rev = data.get("revision", 0)
    return f"{v}_{rev}" if v and rev and revision else v


def android_platform_tools(xml: str) -> str:
    m = re.search(r'path="platform-tools".*?<major>(\d+)</major>\s*<minor>(\d+)</minor>\s*'
                  r"<micro>(\d+)</micro>", xml, re.S)
    return ".".join(m.groups()) if m else ""


def python_same_line_newer(listing: str, current: str) -> "list[str]":
    return pl.python_candidates(listing, current)


def parse_kv(text: str) -> "dict[str, str]":
    """key=value lines from the machine script; later keys win, other lines ignored."""
    out = {}
    for line in (text or "").splitlines():
        k, sep, v = line.partition("=")
        if sep and re.fullmatch(r"[a-z_0-9]+", k.strip()):
            out[k.strip()] = v.strip()
    return out


def tech_texts(rows: "list[Row]") -> "list[str]":
    return [f"tool behind: {r.name} {r.have} → {r.newest} ({r.source})"
            + (f" - {r.hint}" if r.hint else "") for r in rows if r.mark == "⬆"]


def new_tech_texts(texts: "list[str]", open_items: "list[str]") -> "list[str]":
    """Leave out a tool whose same installed version already has an open red item."""
    def key(t: str) -> str:
        return t.split(" → ", 1)[0]
    have = {key(t) for t in open_items}
    return [t for t in texts if key(t) not in have]


# ---- fetchers ----

def get(url: str) -> bytes:
    return pl._get(url)


def get_json(url: str):
    return json.loads(get(url))


def gh_latest(repo: str) -> str:
    try:
        return gh_tag(get_json(GH.format(repo)))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise OSError("GitHub API rate limit (60 an hour unauthenticated)") from e
        raise


def pypi_latest(name: str) -> str:
    data = get_json(pl.PYPI.format(name))
    return data.get("info", {}).get("version", "")


def python_latest(current: str) -> str:
    listing = get(pl.FTP).decode("utf-8", "replace")
    for v in python_same_line_newer(listing, current):
        if pl._exists(f"{pl.FTP}{v}/Python-{v}.tgz"):
            return v
    return current


def run(cmd: "list[str]") -> str:
    """stdout+stderr of a local command, '' when it is not there."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=pl.TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (p.stdout + p.stderr).strip()


def app_version(app: str) -> str:
    try:
        with open(f"/Applications/{app}.app/Contents/Info.plist", "rb") as fh:
            return plistlib.load(fh).get("CFBundleShortVersionString", "")
    except OSError:
        return ""


def brew_installed() -> "dict[str, tuple[str, str]]":
    """{name: (version, 'formula'|'cask')} for formulae installed on request, the casks, and
    gradle / openjdk (ark-release.sh and ark-try.sh run gradle)."""
    out = run(["brew", "info", "--json=v2", "--installed"])
    try:
        d = json.loads(out)
    except ValueError:
        return {}
    res = {}
    for f in d.get("formulae", []):
        inst = f.get("installed", [])
        if inst and (any(i.get("installed_on_request") for i in inst) or f["name"] in ("gradle", "openjdk")):
            res[f["name"]] = (inst[-1].get("version", ""), "formula")
    for c in d.get("casks", []):
        res[c["token"]] = (c.get("installed") or "", "cask")
    return res


# ---- Mac ----

def mac_jobs() -> "list[tuple[str, object]]":
    """(name, fn) - fn returns a Row; it runs in a thread and may raise."""
    jobs = []

    def py_row(minor: str):
        exe = HOME / ".local/bin" / f"python{minor}"
        def fn():
            have = clean(run([str(exe), "-V"]))
            if not have:
                return None
            return Row(f"Python {minor} (Mac, uv)", have, python_latest(have), pl.FTP,
                       hint=f"uv python upgrade {minor}")
        return fn

    for minor in ("3.14", "3.13"):
        if (HOME / ".local/bin" / f"python{minor}").exists():
            jobs.append((f"Python {minor}", py_row(minor)))

    def pypi_row(label: str, cmd: "list[str]", pkg: str, hint: str):
        def fn():
            have = clean(run(cmd))
            return Row(label, have, pypi_latest(pkg), PYPI_PAGE.format(pkg), hint=hint) if have else None
        return fn

    jobs += [
        ("uv", pypi_row("uv", ["uv", "--version"], "uv", "uv self update")),
        ("ruff", pypi_row("ruff (uvx)", ["uvx", "-q", "ruff", "--version"], "ruff", "uv cache clean ruff")),
        ("pyflakes", pypi_row("pyflakes (uvx)", ["uvx", "-q", "pyflakes", "--version"], "pyflakes",
                              "uv cache clean pyflakes")),
    ]

    def gh_row(label: str, have_fn, repo: str, hint: str = ""):
        def fn():
            have = have_fn()
            return Row(label, have, gh_latest(repo), GH_PAGE.format(repo), hint=hint) if have else None
        return fn

    def sc_have():
        m = re.search(r"version:\s*(\S+)", run(["shellcheck", "--version"]))
        return m.group(1) if m else ""

    jobs += [
        ("shellcheck", gh_row("shellcheck", sc_have, "koalaman/shellcheck",
                              "gh release download --repo koalaman/shellcheck into ~/.local/bin")),
        ("gh", gh_row("gh", lambda: clean(run(["gh", "--version"])), "cli/cli",
                      "gh release download --repo cli/cli into ~/.local/bin")),
        ("Homebrew", gh_row("Homebrew", lambda: clean(run(["brew", "--version"])), "Homebrew/brew",
                            "brew update")),
        ("swiftly", gh_row("swiftly", lambda: clean(run(["swiftly", "--version"])), "swiftlang/swiftly",
                           "swiftly self-update")),
        ("Hammerspoon", gh_row("Hammerspoon", lambda: app_version("Hammerspoon"),
                               "Hammerspoon/hammerspoon", "Hammerspoon > Check for Updates")),
        ("jq", gh_row("jq (/usr/bin, Apple's)", lambda: clean(run(["/usr/bin/jq", "--version"])),
                      "jqlang/jq", "brew install jq")),
    ]

    def git_row():
        have = clean(run(["/usr/bin/git", "--version"]))
        return Row("git (/usr/bin, Apple's)", have, brew_stable(get_json(BREW_F.format("git")), revision=False),
                   BREW_F.format("git"), hint="brew install git") if have else None

    def xcode_row():
        have = clean(run(["xcodebuild", "-version"]))
        return Row("Xcode", have, apple_latest(get(APPLE_RSS).decode("utf-8", "replace"), "Xcode"),
                   APPLE_RSS, hint="App Store / developer.apple.com/download") if have else None

    def macos_row():
        have = run(["sw_vers", "-productVersion"])
        if not have:
            return None
        rss = get(APPLE_RSS).decode("utf-8", "replace")
        hint = "System Settings > General > Software Update"
        build = run(["sw_vers", "-buildVersion"])
        if on_seed(rss, "macOS", have, build):
            # A beta Mac is ahead of the newest final release; it is current only on the newest seed.
            label, newest_build = apple_newest_seed(rss, "macOS", have.split(".")[0])
            if not label:
                return Row("macOS (beta)", f"{have} ({build})", "", APPLE_RSS, mark="?",
                           why=f"no macOS {have.split('.')[0]} entry in the feed")
            return Row("macOS (beta)", f"{have} ({build})", f"{label} ({newest_build})", APPLE_RSS,
                       mark="✓" if newest_build == build else "⬆", hint=hint)
        return Row("macOS", have, apple_latest(rss, "macOS"), APPLE_RSS, hint=hint)

    def swift_row():
        have = clean(run(["swift", "--version"]))
        return Row("Swift (swiftly)", have, swift_latest(get_json(SWIFT_JSON)), SWIFT_JSON,
                   hint="swiftly install latest") if have else None

    def tailscale_row():
        have = clean((run(["tailscale", "version"]).splitlines() or [""])[0])
        if not have:
            return None
        mas = Path("/Applications/Tailscale.app/Contents/_MASReceipt").exists()
        return Row("Tailscale (Mac)", have, get_json(TAILSCALE_JSON).get("MacZipsVersion", ""),
                   TAILSCALE_JSON, hint="App Store update" if mas else "Tailscale menu > Update")

    def adb_row():
        exe = HOME / "Library/Android/sdk/platform-tools/adb"
        m = re.search(r"^Version (\S+)", run([str(exe), "version"]), re.M)
        if not m:
            return None
        return Row("adb (Mac, platform-tools)", m.group(1).split("-")[0],
                   android_platform_tools(get(ANDROID_REPO).decode("utf-8", "replace")), ANDROID_REPO,
                   hint="sdkmanager platform-tools")

    jobs += [("git", git_row), ("Xcode", xcode_row), ("macOS", macos_row), ("Swift", swift_row),
             ("Tailscale", tailscale_row), ("adb", adb_row)]

    for name, (have, kind) in sorted(brew_installed().items()):
        def fn(name=name, have=have, kind=kind):
            url = (BREW_F if kind == "formula" else BREW_C).format(name)
            d = get_json(url)
            newest = brew_stable(d) if kind == "formula" else d.get("version", "")
            r = Row(f"brew {name}", have, newest, url, hint=f"brew upgrade {name}")
            if kind == "cask" or not NUM.fullmatch(have.split("_")[0]):
                r.mark = "✓" if have == newest else "⬆"      # opaque version strings: equal or not
            return r
        jobs.append((f"brew {name}", fn))
    return jobs


# ---- game machine ----

# Runs in pwsh 7 through winps.sh (one round trip). key=value lines, nothing else parsed.
WIN_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
"pwsh=" + $PSVersionTable.PSVersion.ToString()
$d = Get-Process sshd | Where-Object { $_.Path } | Select-Object -First 1
if ($d) { "sshd_path=" + $d.Path; "sshd_ver=" + (Get-Item $d.Path).VersionInfo.ProductVersion }
$ts = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
if (Test-Path $ts) { "tailscale=" + ((& $ts version) | Select-Object -First 1) }
$ld = '__LD__\dnplayer.exe'
if (Test-Path $ld) { "ldplayer=" + (Get-Item $ld).VersionInfo.ProductVersion }
$adb = '__LD__\adb.exe'
if (Test-Path $adb) { "ld_adb=" + (((& $adb version) | Out-String) -replace "`r?`n", ' ') }
$py = '__APP__\runtime\python\python.exe'
if (Test-Path $py) {
  & $py -c "import sys, importlib.metadata as m; print('relay_python=' + sys.version.split()[0]); print('relay_pillow=' + m.version('Pillow')); print('relay_pywin32=' + m.version('pywin32'))"
}
"done=1"
""".replace("__LD__", LD_DIR).replace("__APP__", APP)


def machine_kv() -> "tuple[dict[str, str] | None, str]":
    """(values, '') when the machine answered; (None, why) when not."""
    why = tl.unreachable()
    if why:
        return None, why
    try:
        p = subprocess.run([str(ROOT / "scripts/mac/winps.sh"), "--stdin"], input=WIN_PS,
                           capture_output=True, text=True, timeout=tl.WRITE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"winps: {type(e).__name__}"
    kv = parse_kv(p.stdout)
    if kv.get("done") != "1":
        return None, f"winps exit {p.returncode}: {(p.stderr or p.stdout).strip()[:200]}"
    return kv, ""


def machine_jobs(kv: "dict[str, str]") -> "list[tuple[str, object]]":
    jobs = []
    if kv.get("pwsh"):
        jobs.append(("pwsh", lambda: Row("pwsh (machine)", clean(kv["pwsh"]), gh_latest("PowerShell/PowerShell"),
                                         GH_PAGE.format("PowerShell/PowerShell"),
                                         hint="winget upgrade Microsoft.PowerShell")))
    if kv.get("sshd_path"):
        def sshd():
            have = clean(kv.get("sshd_ver", ""))
            if "\\system32\\" in kv["sshd_path"].lower():
                return Row("OpenSSH server (machine)", have, "", "Windows Update", mark="·",
                           why=f"Windows capability {kv['sshd_path']}, updates with Windows Update")
            return Row("OpenSSH server (machine)", have, gh_latest("PowerShell/Win32-OpenSSH"),
                       GH_PAGE.format("PowerShell/Win32-OpenSSH"))
        jobs.append(("sshd", sshd))
    if kv.get("tailscale"):
        jobs.append(("tailscale-win", lambda: Row("Tailscale (machine)", clean(kv["tailscale"]),
                                                  get_json(TAILSCALE_JSON).get("ExesVersion", ""), TAILSCALE_JSON,
                                                  hint="Tailscale tray > Update")))
    if kv.get("ldplayer"):
        jobs.append(("ldplayer", lambda: Row("LDPlayer (machine)", clean(kv["ldplayer"]), "", LDPLAYER_PAGE,
                                             mark="·", why="no machine-readable release feed: look by hand; "
                                             "it has its own updater")))
    if kv.get("ld_adb"):
        m = re.search(r"Version (\S+)", kv["ld_adb"])
        jobs.append(("ld-adb", lambda: Row("adb (machine, LDPlayer's)", (m.group(1) if m else clean(kv["ld_adb"])),
                                           "", LDPLAYER_PAGE, mark="·",
                                           why="bundled with LDPlayer, follows the LDPlayer row")))
    py = kv.get("relay_python", "")
    if py:
        cp = "cp" + "".join(py.split(".")[:2])
        jobs.append(("relay-python", lambda: Row("relay runtime Python (machine)", py, pl.latest_python(py), pl.FTP,
                                                 hint="bump PY_VERSION in packaging/build.py, deploy")))
        for key, pkg in (("relay_pillow", "Pillow"), ("relay_pywin32", "pywin32")):
            have = kv.get(key, "")
            if have:
                jobs.append((pkg, lambda pkg=pkg, have=have: Row(
                    f"relay runtime {pkg} (machine)", have, pl.latest_wheel(pkg, have, cp), PYPI_PAGE.format(pkg),
                    hint="bump relay/requirements.txt, deploy")))
    return jobs


# ---- run ----

def collect(jobs: "list[tuple[str, object]]") -> "list[Row]":
    rows = []
    if not jobs:
        return rows
    with ThreadPoolExecutor(min(16, len(jobs))) as ex:
        futures = [(name, ex.submit(fn)) for name, fn in jobs]
        for name, fut in futures:
            try:
                r = fut.result()
            except (OSError, ValueError, KeyError) as e:      # URLError and timeouts are OSError
                r = Row(name, "", "", "", mark="?", why=f"{type(e).__name__}: {e}"[:160])
            if r is not None:
                rows.append(r)
    return rows


def write_techlog(texts: "list[str]") -> str:
    """Append the behind rows as red items to today's (Beijing) tech log on the machine."""
    try:
        # The window `techlog.py red` reads by default (--days 3): an item older than that is
        # not shown to anyone any more, so it is written again.
        snap = tl.read(back=2)
        open_items = [t for _, _, t in tl.red_items(snap.texts)]
    except tl.ReadFailed as e:
        return f"tech log not read: {e}"
    texts = new_tech_texts(texts, open_items)
    if not texts:
        return "tech log: every behind tool already has an open red item"
    from zoneinfo import ZoneInfo  # noqa: PLC0415 - only needed when writing
    now = datetime.now(ZoneInfo(SERVER_TZ))
    script = WRITE_RED.format(tech_dir=tl.REMOTE_DIR, day=now.date().isoformat(), hm=now.strftime("%H:%M"),
                              stamp=now.strftime("%Y%m%d-%H%M"), heading=TECH_HEADING, texts=texts)
    try:
        rc, out, err = tl.run_script("tools_latest_red.py", script, tl.WRITE_TIMEOUT)
    except tl.ReadFailed as e:
        return f"tech log not written: {e}"
    if rc == 0 and b"TOOLS_RED_WRITTEN" in out:
        return f"tech log: {len(texts)} red item(s) written ({out.decode('utf-8', 'replace').split()[-1]})"
    return f"tech log not written: {tl.why_failed(out, err, rc)}"


# Runs on the machine (winrun --py). Same format as relay/ark_relay/core/techlog.add_red:
# ids continue after the highest number already used in that minute.
WRITE_RED = '''\
import re
from pathlib import Path

p = Path({tech_dir!r}) / ({day!r} + ".md")
STAMP = {stamp!r}
try:
    old = p.read_text(encoding="utf-8")
except OSError:
    old = ""
used = [int(m.group(1)) for m in re.finditer(r"^\\U0001f534 R-" + STAMP + r"-(\\d+) ", old, re.M)]
start = max(used, default=0)
lines = ["\\U0001f534 R-%s-%d %s" % (STAMP, start + i, t) for i, t in enumerate({texts!r}, 1)]
p.parent.mkdir(parents=True, exist_ok=True)
with open(p, "a", encoding="utf-8") as fh:
    fh.write("\\n## {hm} {heading}\\n" + "\\n".join(lines) + "\\n")
print("TOOLS_RED_WRITTEN", p)
'''


def main(argv: "list[str] | None" = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print("▶ tools on the Mac against their official sources (newest of their line)")
    mac = collect(mac_jobs())
    for r in mac:
        print(r.line())
    print("▶ tools on the game machine")
    kv, why = machine_kv()
    rows = list(mac)
    if kv is None:
        print(f"  machine off, not checked ({why if why.isascii() else tl.PROBE + ' not reachable'})")
    else:
        win = collect(machine_jobs(kv))
        for r in win:
            print(r.line())
        rows += win
    behind = tech_texts(rows)
    if not behind:
        print("  nothing behind")
    elif "--no-techlog" in argv:
        print(f"  {len(behind)} behind; tech log not written (--no-techlog)")
    elif kv is None:
        print(f"  {len(behind)} behind; tech log not written: machine off")
    else:
        print("  " + write_techlog(behind))
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 - this check must never stop a deploy
        print(f"  tools_latest failed: {type(e).__name__}: {e}")
    sys.exit(0)
