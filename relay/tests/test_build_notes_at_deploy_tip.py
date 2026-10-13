"""packaging/build.py builds at a deploy commit, whose RELEASE-NOTES.md is emptied.

2026-10-13 (audit of the install / switch-over block, item 3): deploy-relay.sh builds the
manifest with the notes filled in, then empties relay/RELEASE-NOTES.md and commits both
in the commit it tags with the manifest's `ref`. build.py compared every listed file with
the tree, so at each deploy tip (7ce92679, d6fb8004, 45584225) it stopped with "hash
differs: RELEASE-NOTES.md". Now the notes come from the first of the tree, `<ref>^` and
`<ref>` whose hashes match the manifest. Run on a throwaway git repo shaped like that.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY.parent / "packaging"))

import build  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                    "-c", "tag.gpgsign=false", *args], cwd=repo, check=True, capture_output=True)


FILLED = "- 这次改了什么\n".encode("utf-8")


def make_repo(root: Path) -> Path:
    """A repo whose tip is a deploy commit: manifest of the filled notes, notes emptied,
    tag relay-1 on that commit; the filled notes in its parent."""
    repo = root / "repo"
    relay = repo / "relay"
    (relay / "ark_relay").mkdir(parents=True)
    (relay / "ark_relay" / "core.py").write_text("X = 1\n", encoding="utf-8")
    (relay / "app_main.py").write_text("print('main')\n", encoding="utf-8")
    (relay / "RELEASE-NOTES.md").write_bytes(FILLED)
    names = ["ark_relay/core.py", "app_main.py", "RELEASE-NOTES.md"]
    data = {n: (relay / n).read_bytes() for n in names}
    manifest = {"version": 1, "ref": "relay-1",
                "files": {n: hashlib.sha1(b).hexdigest() for n, b in data.items()},
                "sha256": {n: hashlib.sha256(b).hexdigest() for n, b in data.items()}}
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "notes written")
    (relay / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (relay / "RELEASE-NOTES.md").write_bytes(b"")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "deploy: manifest 1")
    git(repo, "tag", "relay-1", "HEAD")
    return repo


def stage_in(repo: Path, stage: Path):
    saved = build.REPO, build.RELAY
    build.REPO, build.RELAY = repo, repo / "relay"
    try:
        return build.stage_code(stage)
    except SystemExit as exc:
        return f"stopped: {str(exc).splitlines()[-1].strip()}"
    finally:
        build.REPO, build.RELAY = saved


with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    repo = make_repo(t)
    print("[a deploy tip: notes empty in the tree and at the tag, filled at the tag's parent]")
    got = stage_in(repo, t / "stage")
    check("stage_code passes", got, "1")
    staged = t / "stage" / "versions" / "1" / "RELEASE-NOTES.md"
    check("the staged notes are the deployed ones",
          staged.read_bytes() if staged.exists() else None, FILLED)
    main = t / "stage" / "versions" / "1" / "app_main.py"
    check("the other files staged as in the tree",
          main.read_text(encoding="utf-8") if main.exists() else None, "print('main')\n")

    print("[notes for the next deploy written in the tree: still the deployed ones staged]")
    (repo / "relay" / "RELEASE-NOTES.md").write_text("- 下一次的说明\n", encoding="utf-8")
    got = stage_in(repo, t / "stage2")
    check("stage_code passes", got, "1")
    staged = t / "stage2" / "versions" / "1" / "RELEASE-NOTES.md"
    check("the staged notes are the deployed ones",
          staged.read_bytes() if staged.exists() else None, FILLED)

    print("[no copy matches the manifest: stops as before]")
    m = json.loads((repo / "relay" / "manifest.json").read_text(encoding="utf-8"))
    m["sha256"]["RELEASE-NOTES.md"] = "0" * 64
    (repo / "relay" / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    got = stage_in(repo, t / "stage3")
    check("stopped on the notes", str(got).startswith("stopped: hash differs: RELEASE-NOTES.md"), True)

    print("[a code file that differs still stops it]")
    repo2 = make_repo(t / "b")
    (repo2 / "relay" / "app_main.py").write_text("print('changed')\n", encoding="utf-8")
    check("stopped on app_main.py", stage_in(repo2, t / "stage4"), "stopped: hash differs: app_main.py")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
