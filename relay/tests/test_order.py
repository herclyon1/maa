"""Orders from the Mac: order-now confirmed, the push to main.

One part per former file, each run on its own (tests/_parts.py): test_order_now_confirmed.py, test_order_push_main.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_order_now_confirmed():
    """scripts/mac/order-now.sh refuses a changing order without "confirmed": true.

2026-10-10 04:16:12 a set_master sent with order-now.sh carried no "confirmed";
the relay refused it (commands.py gate 2) and pushed 「📱 配置没改成」 to the
group. The script now stops before
sending such an order. The list of changing actions is read from the relay
(commands.MUTATING).

Nothing here reaches ntfy: HOME holds a made-up push.env and PATH starts with a
fake curl that only records that it was called and answers 200.

    Formerly test_order_now_confirmed.py.
    """
    import json
    import os
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts" / "mac" / "order-now.sh"
    sys.path.insert(0, str(ROOT / "relay"))
    from ark_relay.features.phone.commands import MUTATING


    def run(body: dict, home: str) -> tuple[int, str, bool]:
        """(exit code, output, whether the fake curl was called)."""
        sent = Path(home) / "curl-called"
        sent.unlink(missing_ok=True)
        env = {**os.environ, "HOME": home, "PATH": f"{home}/bin:{os.environ['PATH']}"}
        r = subprocess.run(["bash", str(SCRIPT), json.dumps(body, ensure_ascii=False)],
                           capture_output=True, env=env, timeout=30)
        return r.returncode, (r.stderr + r.stdout).decode("utf-8", "replace"), sent.exists()


    def fake_home(home: str) -> None:
        cfg = Path(home) / ".config" / "ark"
        cfg.mkdir(parents=True)
        (cfg / "push.env").write_text("ARK_PHONE_TOPIC=test-topic-not-real\nARK_PHONE_PIN=0000\n", encoding="utf-8")
        curl = Path(home) / "bin" / "curl"
        curl.parent.mkdir()
        curl.write_text(f"#!/bin/sh\ntouch '{home}/curl-called'\nprintf 200\n", encoding="utf-8")
        curl.chmod(0o755)


    with tempfile.TemporaryDirectory() as home:
        fake_home(home)
        print("[a changing order without confirmed: stopped here, not sent]")
        code, out, sent = run({"action": "set_master", "game": "鸣潮", "path": "x", "value": 2}, home)
        check("exit code non-zero", code != 0, True)
        check("says confirmed is needed", '"confirmed": true' in out, True)
        check("not sent", sent, False)

        code, out, sent = run({"action": "set_stage", "value": "1-7", "confirmed": False}, home)
        check("confirmed false is stopped too", (code != 0, sent), (True, False))

        print("\n[confirmed, or not a changing order: sent as before]")
        code, out, sent = run({"action": "set_master", "confirmed": True, "game": "鸣潮", "path": "x", "value": 2}, home)
        check("confirmed set_master is sent", (code, sent), (0, True))
        code, out, sent = run({"action": "tacet_shots", "on": False}, home)
        check("a non-changing order needs no confirmed", (code, sent), (0, True))

        print("\n[the list is the relay's own]")
        check("set_master, set_config and run_now are changing orders", {"set_master", "set_config", "run_now"} <= MUTATING, True)


def _part_order_push_main():
    """scripts/mac/order.sh writes the inbox to main only.

2026-10-10 03:0x a ``--clear`` run from a worktree on branch acc-yw-manual-1009
ended in ``git push -q origin HEAD``: the inbox commit (d47c1998) went to that
branch, and main - the one the relay reads - never got it. The script now stops
before writing anything unless the checkout sits exactly on origin/main, commits
only queue/config.json, and pushes ``HEAD:main``.

Each case runs the real script in a throwaway clone of a throwaway bare repo.
The stub ``ark_relay`` there has no ``evidence`` module and there is no
purge-cdn.py, so nothing after the push can reach COS or the CDN; the script
ends non-zero there, after the part under test.

    Formerly test_order_push_main.py.
    """
    import json
    import os
    import shutil
    import subprocess
    import tempfile

    SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "mac" / "order.sh"


    def git(cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


    def setup(tmp):
        origin, work = tmp / "origin.git", tmp / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
        git(work, "config", "user.email", "t@example.com")
        git(work, "config", "user.name", "t")
        (work / "scripts" / "mac").mkdir(parents=True)
        shutil.copy(SCRIPT, work / "scripts" / "mac" / "order.sh")
        # scripts/mac/order.sh imports ark_relay.features.phone.commands
        phone = work / "relay" / "ark_relay" / "features" / "phone"
        phone.mkdir(parents=True)
        for pkg in (phone.parents[1], phone.parent, phone):
            (pkg / "__init__.py").write_text("")
        (phone / "commands.py").write_text("ALLOWED = {'skip_shutdown': None}\n")
        (work / "queue").mkdir()
        (work / "queue" / "config.json").write_text(json.dumps(
            {"version": 1, "name": "空（安全状态）", "note": "", "commands": []}, ensure_ascii=False) + "\n")
        git(work, "symbolic-ref", "HEAD", "refs/heads/main")
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "init")
        git(work, "push", "-q", "origin", "main")
        return origin, work


    def run(work, tmp, *args):
        env = dict(os.environ, HOME=str(tmp / "home"))
        (tmp / "home").mkdir(exist_ok=True)
        return subprocess.run(["bash", str(work / "scripts" / "mac" / "order.sh"), *args],
                              capture_output=True, text=True, env=env, timeout=60)


    def origin_branches(origin):
        return sorted(git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())


    print("[a branch with commits of its own: the 10-10 03:0x case]")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        origin, work = setup(tmp)
        main_before = git(origin, "rev-parse", "main")
        git(work, "checkout", "-q", "-b", "acc-yw-manual-1009")
        (work / "notes.txt").write_text("side work\n")
        git(work, "add", "notes.txt")
        git(work, "commit", "-q", "-m", "side work")
        box_before = (work / "queue" / "config.json").read_text()
        r = run(work, tmp, "--clear")
        check("exits non-zero", r.returncode != 0, True)
        check("says why", "not at origin/main" in r.stderr, True)
        check("inbox file untouched", (work / "queue" / "config.json").read_text() == box_before, True)
        check("origin main unchanged", git(origin, "rev-parse", "main"), main_before)
        check("no branch pushed to origin", origin_branches(origin), ["main"])

    print("[a branch sitting on origin/main, with another file staged]")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        origin, work = setup(tmp)
        git(work, "checkout", "-q", "-b", "acc-other")
        (work / "staged-by-someone.txt").write_text("not mine\n")
        git(work, "add", "staged-by-someone.txt")
        r = run(work, tmp, "--clear")
        check("got past the guard", "not at origin/main" in r.stderr, False)
        check("pushed", "已推上 GitHub" in r.stdout, True)
        check("only main on origin", origin_branches(origin), ["main"])
        files = git(origin, "show", "--name-only", "--format=", "main").split()
        check("the commit holds the inbox only", files, ["queue/config.json"])
        check("origin main has the new version", json.loads(git(origin, "show", "main:queue/config.json"))["version"] > 1, True)
        check("the staged file stays staged, not committed", git(work, "diff", "--cached", "--name-only"), "staged-by-someone.txt")

    print("[--show reads without a fetch or a check]")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        origin, work = setup(tmp)
        git(work, "checkout", "-q", "-b", "elsewhere")
        (work / "x.txt").write_text("x\n")
        git(work, "add", "x.txt")
        git(work, "commit", "-q", "-m", "x")
        r = run(work, tmp, "--show")
        check("--show still works off main", r.returncode, 0)

    if fails:
        print(f"✗ {len(fails)} failed: {fails}")
        sys.exit(1)
    print("✓ all passed")


if __name__ == "__main__":
    sys.exit(run_parts([_part_order_now_confirmed, _part_order_push_main]))
