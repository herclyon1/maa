"""lint-repo.sh item 22 and the parts check: our tools point at the new relay, our parts are current.

On 10-11 eight tools still imported the ark_relay frozen in C:\\ProgramData\\ark-relay at the
switch-over, docs and memory named module paths that had moved, and the shared top-level
checkout sat 359 commits behind; and two of the relay's three bundled parts were a release
behind. Checked here, on temporary trees (no network, nothing on the gaming machine):
  - scripts/mac/lib/tool_refs.py: a tool putting the old folder on sys.path (literal,
    Python variable, .bat variable) fails; the same tool resolving the installed relay's
    code folder (the relay_code / current.txt shape the fixed tools use) passes; data paths
    under the old folder pass; an import of a module or name the new relay does not have
    fails, an old module name the relay aliases passes; a rule file naming a missing path
    fails, with the moved module's new place as the hint; a top-level checkout behind
    origin/main fails;
  - the hook check: a hook file registered in settings.json or hooks/registry.json, run by a
    registered hook, or paused passes; one that is none of these fails, as does a rule file
    naming a hook file that is not there; helpers and hook tools are not hooks;
  - the paused-list reasons: a reason with a measured time or a dated 被指出.txt / 报错台账.txt
    entry passes; the 10-11 quote-only reason, a reason with only his date, no reason, and
    "msgs" for "ms" fail; a running hook's entry and a listed pre-10-11 entry are not judged;
  - scripts/mac/lib/ff-toplevel.sh: fast-forwards a clean top-level checkout on main,
    leaves a dirty one and one on another branch alone;
  - scripts/mac/lib/parts_latest.py: the same-line rule for python.org and PyPI listings;
  - deploy-relay.sh runs both new steps and cannot be stopped by them.
"""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tr = load("tool_refs", ROOT / "scripts/mac/lib/tool_refs.py")
pl = load("parts_latest", ROOT / "scripts/mac/lib/parts_latest.py")
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def write(base: Path, rel: str, text: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def fake_relay(base: Path) -> None:
    """A new-layout ark_relay: core/notify.py, features/phone/snapshot.py, one old alias each."""
    write(base, "relay/ark_relay/__init__.py", "from ark_relay import _aliases\n")
    write(base, "relay/ark_relay/_aliases.py",
          'MOVED = {\n    "notify": "core.notify",\n    "snapshot": "features.phone.snapshot",\n}\n')
    write(base, "relay/ark_relay/core/__init__.py", "")
    write(base, "relay/ark_relay/core/notify.py", "def send(t):\n    return t\nLEVEL = 1\n")
    write(base, "relay/ark_relay/features/__init__.py", "")
    write(base, "relay/ark_relay/features/phone/__init__.py", "")
    write(base, "relay/ark_relay/features/phone/snapshot.py", "def load():\n    return {}\n")
    write(base, "relay/ark_relay/features/okww_patch/okww_files/a.py", "")


def run(base: Path, docs=None) -> "tuple[int, list[str]]":
    buf = io.StringIO()
    args = ["--root", str(base), "--no-git", "--hooks", "none"]
    for d in docs or [str(base / "none.md")]:
        args += ["--doc", d]
    with contextlib.redirect_stdout(buf):
        rc = tr.main(args)
    return rc, [ln for ln in buf.getvalue().splitlines() if not ln.startswith("  note:")]


def findings(lines):
    """The `file:line` of each finding (summary line dropped)."""
    return sorted(ln.split(": ", 1)[0] for ln in lines[:-1])


OLD_PY = '''import sys
sys.path.insert(0, r"C:\\ProgramData\\ark-relay")
from ark_relay.features.phone import snapshot
print(snapshot.load())
'''
OLD_VAR_PY = '''import sys
from pathlib import Path
R = Path(r"C:\\ProgramData\\ark-relay")
sys.path.insert(0, str(R))
from ark_relay.core.notify import send
send((R / ".env").read_text())
'''
OLD_BAT = '''@echo off
set RELAY=C:\\ProgramData\\ark-relay
"%PY%" -c "import sys; sys.path.insert(0, r'%RELAY%'); from ark_relay.core.notify import send; send(1)"
'''
# The fixed shape (pkg-gaps-b, 10-11): the code folder comes from the installed relay's
# current.txt; the data folder is still C:\\ProgramData\\ark-relay.
FIXED_PY = '''import sys
from pathlib import Path
APP = Path(r"C:\\Program Files\\ArkRelay")
DATA = Path(r"C:\\ProgramData\\ark-relay")
LEGACY_CODE = Path(r"C:\\ProgramData\\ark-relay")
name = (APP / "current.txt").read_text(encoding="ascii").strip()
folder = APP / "versions" / name if name else LEGACY_CODE
sys.path.insert(0, str(folder))
from ark_relay.features.phone import snapshot
from ark_relay.core.notify import send, LEVEL
send((DATA / ".env").read_text() + str(LEVEL) + str(snapshot.load()))
'''
FIXED_BAT = '''@echo off
set "APP=C:\\Program Files\\ArkRelay"
set "DATA=C:\\ProgramData\\ark-relay"
if exist "%APP%\\current.txt" for /f "usebackq delims=" %%v in ("%APP%\\current.txt") do set "CODE=%APP%\\versions\\%%v"
if not defined CODE set "CODE=%DATA%"
"%PY%" -c "import sys; sys.path.insert(0, r'%CODE%'); from ark_relay.core.notify import send; send(r'%DATA%\\state')"
'''
DATA_ONLY_PY = '''from pathlib import Path
LOG = Path(r"C:\\ProgramData\\ark-relay\\relay.log")
ENV = r"C:\\\\ProgramData\\\\ark-relay\\\\.env"
print(LOG, ENV)
'''

with tempfile.TemporaryDirectory() as t:
    base = Path(t)
    fake_relay(base)

    write(base, "scripts/mac/lib/old.py", OLD_PY)
    write(base, "scripts/mac/lib/old_var.py", OLD_VAR_PY)
    write(base, "scripts/windows/old.bat", OLD_BAT)
    rc, out = run(base)
    check("old code folder on sys.path: literal, Python variable, .bat variable",
          (rc, findings(out)),
          (1, ["scripts/mac/lib/old.py:2", "scripts/mac/lib/old_var.py:3",
               "scripts/mac/lib/old_var.py:4", "scripts/windows/old.bat:2",
               "scripts/windows/old.bat:3"]))

    for rel in ("scripts/mac/lib/old.py", "scripts/mac/lib/old_var.py", "scripts/windows/old.bat"):
        (base / rel).unlink()
    write(base, "scripts/mac/lib/fixed.py", FIXED_PY)
    write(base, "scripts/windows/fixed.bat", FIXED_BAT)
    write(base, "scripts/mac/lib/data_only.py", DATA_ONLY_PY)
    rc, out = run(base)
    check("fixed tools (installed relay's folder, data still in ProgramData) pass",
          (rc, findings(out)), (0, []))
    check("the summary counts the tools and imports", out[-1].split("; ", 1)[1],
          "3 tools with 3 ark_relay imports and 0 ark_relay paths)")

    write(base, "scripts/mac/lib/gone.py",
          "from ark_relay import weeklyboss\nfrom ark_relay.core.notify import shout\n"
          "import ark_relay.core.ledger\n"
          "p = 'ark_relay/okww_files/a.py'\nq = 'ark_relay/features/okww_patch/okww_files/a.py'\n")
    rc, out = run(base)
    check("deleted module, renamed name, missing module, old flat path: each fails",
          (rc, findings(out)),
          (1, ["scripts/mac/lib/gone.py:1", "scripts/mac/lib/gone.py:2",
               "scripts/mac/lib/gone.py:3", "scripts/mac/lib/gone.py:4"]))
    check("an old path moved without an alias gets the same-named file as the hint",
          any("(now relay/ark_relay/features/okww_patch/okww_files/a.py)" in ln for ln in out), True)
    (base / "scripts/mac/lib/gone.py").unlink()

    write(base, "doc.md", "use `scripts/mac/lib/fixed.py`, see `relay/ark_relay/notify.py`\n"
          "and `scripts/mac/gone.sh`; bare winrun.sh is not checked here; "
          "`ark_relay/core/notify.py` is fine\n")
    rc, out = run(base, [str(base / "doc.md")])
    check("rule file: missing paths fail, a moved module gets its new place",
          (rc, findings(out), "(now relay/ark_relay/core/notify.py)" in out[0]),
          (1, ["doc.md:1", "doc.md:2"], True))

    write(base, "CLAUDE.md", "| run | `winrun.sh --py <local.py>` and `scripts/mac/lib/fixed.py` |\n")
    rc, out = run(base, ["CLAUDE.md"])
    check("repo's own doc: a bare script name not in the repo fails, a <placeholder> does not",
          (rc, findings(out)), (1, ["CLAUDE.md:1"]))
    write(base, "scripts/mac/winrun.sh", "#!/bin/sh\n")
    rc, out = run(base, ["CLAUDE.md"])
    check("repo's own doc: the bare name exists", (rc, findings(out)), (0, []))

    # The top-level checkout: a bare origin, the top-level clone, a worktree; a push from
    # the worktree leaves the top-level behind.
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]

    def git(*a, cwd):
        return subprocess.run([*g, *a], cwd=cwd, capture_output=True, text=True, check=True).stdout

    origin, top, wt = base / "origin.git", base / "top", base / "wt"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(top)], check=True, capture_output=True)
    git("checkout", "-q", "-b", "main", cwd=top)
    (top / "a.txt").write_text("1\n")
    git("add", "a.txt", cwd=top)
    git("commit", "-qm", "one", cwd=top)
    git("push", "-q", "origin", "main", cwd=top)
    git("worktree", "add", "-q", "-b", "work", str(wt), cwd=top)
    bad = tr.Finding()
    check("top-level at origin/main: nothing", (tr.check_toplevel(wt, bad), list(bad)),
          ("top-level checkout (main) at origin/main", []))
    (wt / "a.txt").write_text("2\n")
    git("commit", "-qam", "two", cwd=wt)
    git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=wt)
    bad = tr.Finding()
    tr.check_toplevel(wt, bad)
    check("top-level behind origin/main: one finding naming the fix",
          (len(bad), "1 commits behind origin/main" in bad[0][1], "merge --ff-only" in bad[0][1]),
          (1, True, True))

    ff = str(ROOT / "scripts/mac/lib/ff-toplevel.sh")
    (top / "a.txt").write_text("dirty\n")
    r = subprocess.run([ff, str(wt)], capture_output=True, text=True)
    check("ff-toplevel: dirty top-level left alone, exit 0",
          (r.returncode, "uncommitted changes" in r.stdout, (top / "a.txt").read_text()),
          (0, True, "dirty\n"))
    git("checkout", "-q", "--", "a.txt", cwd=top)
    git("checkout", "-q", "-b", "side", cwd=top)
    r = subprocess.run([ff, str(wt)], capture_output=True, text=True)
    check("ff-toplevel: top-level on another branch left alone",
          (r.returncode, "not main" in r.stdout, git("rev-parse", "--abbrev-ref", "HEAD", cwd=top).strip()),
          (0, True, "side"))
    git("checkout", "-q", "main", cwd=top)
    r = subprocess.run([ff, str(wt)], capture_output=True, text=True)
    check("ff-toplevel: clean top-level on main fast-forwarded",
          (r.returncode, "fast-forwarded 1 commits" in r.stdout, (top / "a.txt").read_text()),
          (0, True, "2\n"))
    bad = tr.Finding()
    tr.check_toplevel(wt, bad)
    check("after the fast-forward the check is clean", list(bad), [])

# Hooks: a hook file must be registered (settings.json or registry.json), run by a
# registered hook, or in a paused list; helpers and tools are not hooks.
HOOK = 'import json, sys\n"""PreToolUse on Bash."""\nd = json.load(sys.stdin)\n'
with tempfile.TemporaryDirectory() as t:
    h = Path(t) / "hooks"
    write(h, "dispatch.py", HOOK)
    write(h, "in-settings.py", HOOK)
    write(h, "in-registry.py", HOOK + "HARD = ('sub-guard.py',)\n")
    write(h, "sub-guard.py", HOOK)
    write(h, "via-mod.py", HOOK)
    write(h, "paused-guard.py", HOOK)
    write(h, "lost-hook.py", HOOK)
    write(h, "_helper.py", HOOK)
    write(h, "replay-tool.py", '"""Replay a PreToolUse hook over old calls."""\nimport sys\n')
    write(h, "registry.json", json.dumps({"PreToolUse": [
        {"matcher": "Bash", "command": "python3 ~/.claude/hooks/in-registry.py", "timeout": 5},
        {"matcher": "*", "command": "python3 ~/.claude/hooks/soft.py in-registry2.py"}]}))
    write(h, "gate.py", HOOK + "x = mod('via-mod')\n")
    write(h, "paused.json", json.dumps([{"event": "PreToolUse", "matcher": None,
                                         "hook": {"command": "python3 ~/.claude/hooks/paused-guard.py"},
                                         "paused": "量得：PreToolUse 每次 24 ms；定：继续暂停"}]))
    write(Path(t), "settings.json", json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": "python3 ~/.claude/hooks/dispatch.py PreToolUse"},
        {"type": "command", "command": "python3 ~/.claude/hooks/in-settings.py"},
        {"type": "command", "command": "python3 ~/.claude/hooks/gate.py"}]}]}}))
    write(Path(t), "rules.md", "the guard `~/.claude/hooks/gone-guard.py` blocks it\n")
    bad = tr.Finding()
    summary = tr.check_hooks(h, Path(t) / "settings.json", [(Path(t) / "rules.md", "rules.md")], bad)
    check("hooks: only the unregistered hook and the missing named hook fail",
          sorted(w.rsplit("/", 1)[-1] for w, _ in bad), ["lost-hook.py", "rules.md:1"])
    check("hooks: the counts", summary, "8 hook files: 6 registered or run by one, 1 paused")

# Paused-list reasons (10-11): every entry of a hook that is not running needs a measured time or a
# dated entry of the error ledgers. The first reason is the one all sixteen entries carried on 10-11.
QUOTE_1011 = ("10-11 他 10-10 17:12 说钩子影响速度先暂时关上（BOARD/OPEN.md:8 记），开着那份在 "
              "~/.claude/hooks/registry.json.slim-enabled-*")
REASONS = {
    "quote-1011": QUOTE_1011,
    "his-date-only": "他 10-10 17:12 说过先关上（待核）",
    "no-reason": None,
    "msgs-not-ms": "看了 3 msgs，没问题",
    "measured": "量得：Stop 每条回复 66 ms（31 MB 转录）；定：撤，因为和 reason-guard 重复",
    "measured-zh": "量得：每次 30 毫秒；定：继续暂停",
    "caught-date": "防的错：被指出.txt 10-10 18:27、18:44 命中 2 次；定：开",
    "ledger-date": "防的错：报错台账.txt 10-11 12:54（lint-repo 8 项红）；定：改快再开",
    "running-quoted": QUOTE_1011,
    "decision-guard": "09-25 23:58 user: fixed-phrase check on our own wording, passed by rewording",
}
with tempfile.TemporaryDirectory() as t:
    h = Path(t) / "hooks"
    for name in REASONS:
        write(h, f"{name}.py", HOOK)
    write(h, "registry.json", json.dumps({"Stop": [{"command": "python3 ~/.claude/hooks/running-quoted.py"}]}))
    rows = []
    for name, why in REASONS.items():
        e = {"event": "Stop", "matcher": None, "hook": {"type": "command",
             "command": f"python3 ~/.claude/hooks/soft.py {name}.py"}}
        if why is not None:
            e["paused"] = why
        rows.append(e)
    write(h, "暂停中-待优化.json", json.dumps(rows, ensure_ascii=False))
    write(Path(t), "settings.json", json.dumps({"hooks": {}}))
    bad = tr.Finding()
    summary = tr.check_hooks(h, Path(t) / "settings.json", [], bad)
    check("paused reasons: the quote, his date alone, no reason and msgs fail",
          sorted(w.rsplit(": ", 1)[-1] for w, _ in bad),
          ["his-date-only", "msgs-not-ms", "no-reason", "quote-1011"])
    check("paused reasons: the finding says a quote is not a reason",
          all("a quote of the user is not a reason" in why for _, why in bad), True)
    check("paused reasons: the listed pre-10-11 entry shows as unmeasured, not red",
          summary.endswith("(1 paused before 10-11 still unmeasured: decision-guard)"), True)

# parts_latest: the same-line rule on canned listings.
listing = ('<a href="3.13.9/">3.13.9/</a><a href="3.14.7/">3.14.7/</a><a href="3.14.8/">'
           '3.14.8/</a><a href="3.14.10/">3.14.10/</a><a href="3.15.0/">3.15.0/</a>')
check("python: newer same-line candidates, newest first, 3.15 not counted",
      pl.python_candidates(listing, "3.14.7"), ["3.14.10", "3.14.8"])
check("python: nothing newer", pl.python_candidates(listing, "3.14.10"), [])


def wheel(name, v, cp="cp314", yanked=False):
    return {"filename": f"{name}-{v}-{cp}-{cp}-win_amd64.whl", "yanked": yanked}


pillow = {"releases": {
    "12.3.0": [wheel("pillow", "12.3.0")],
    "12.4.0": [wheel("pillow", "12.4.0")],
    "12.5.0": [wheel("pillow", "12.5.0", yanked=True)],
    "12.6.0rc1": [wheel("pillow", "12.6.0rc1")],
    "12.7.0": [wheel("pillow", "12.7.0", cp="cp313")],
    "13.0.0": [wheel("pillow", "13.0.0")],
}}
check("pillow: same major, final, unyanked, with a cp314 win_amd64 wheel",
      pl.newest_pypi(pillow, "12.3.0", 1, "cp314"), "12.4.0")
pywin32 = {"releases": {"311": [wheel("pywin32", "311")], "312": [wheel("pywin32", "312")]}}
check("pywin32: any higher build", pl.newest_pypi(pywin32, "311", 0, "cp314"), "312")
check("pywin32: current when nothing is newer", pl.newest_pypi(pywin32, "312", 0, "cp314"), "312")
pins = pl.pinned(ROOT)
check("pins read from build.py and requirements.txt", sorted(pins), ["Pillow", "Python", "pywin32"])
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rcs = (pl.report({"Python": "3.14.7"}, {"Python": "3.14.7"}),
           pl.report({"Python": "3.14.7"}, {"Python": "3.14.8"}),
           pl.report({"Python": "3.14.7"}, {"Python": OSError("offline")}))
check("report: current 0, behind 1, unreachable 2", rcs, (0, 1, 2))

# deploy-relay.sh: the parts check runs before anything else touches the machine, the
# top-level fast-forward after the push; neither can stop the deploy.
dr = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
check("deploy runs parts_latest.py first and ignores its exit",
      ('lib/parts_latest.py" || true' in dr,
       dr.find("parts_latest.py") < dr.find('\ncd "$HERE"')),
      (True, True))
check("deploy fast-forwards the top-level checkout after the push",
      ('lib/ff-toplevel.sh" "$HERE/.." || true' in dr,
       dr.find("push -q origin HEAD:refs/heads/main") < dr.find("ff-toplevel.sh")),
      (True, True))

if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
