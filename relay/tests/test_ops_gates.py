"""Mac repository gates, techlog CLI, estop layout, background-priority guard, and ff-toplevel."""
from __future__ import annotations

# ruff: noqa: PLC0415
import os as _os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, stage_mac_script, tmpdir

# Prefer the active latest Python (4x faster startup than macOS /usr/bin/python3 stub) for bash sub-scripts.
_PY_BIN = Path(sys.executable).parent
if (_PY_BIN / "python3").exists():
    _os.environ["PATH"] = f"{_PY_BIN}:{_os.environ.get('PATH', '')}"

_SHARED = (check, fails, fx_dir, require, tmpdir)


def _part_techlog_tool():
    import importlib.util
    import json
    import os
    import re
    import socket
    import subprocess
    import threading
    import time
    from datetime import datetime, timedelta

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay" / "tests"))

    TOOL = ROOT / "scripts" / "mac" / "techlog.py"
    spec = importlib.util.spec_from_file_location("techlog_tool", TOOL)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)


    FAKE = r'''
import json, sys, time
from pathlib import Path
cfg = json.loads(Path(__file__).with_name("fake.json").read_text(encoding="utf-8"))
mode = cfg["mode"]
with open(cfg["log"], "a", encoding="utf-8") as fh:
    fh.write(repr(sys.argv[1:]) + "\n")
if mode == "down":
    sys.stderr.write("winrun: remote produced no output (script never ran, or machine unreachable)\n")
    sys.exit(4)
if mode == "hang":
    time.sleep(60)
if sys.argv[1] != "--py":
    sys.exit(9)
reading = "TECHLOG_DONE" in Path(sys.argv[2]).read_text(encoding="utf-8")
if mode == "pyfail" and not reading:
    sys.stderr.write("winrun: remote produced no output\n")
    sys.exit(4)
print("[机器时间] 10-10 23:00:00")
# The --py script runs in this process, as its own __main__ with the arklog shim first
# on the path: one interpreter fewer per call (each call started three; under a load of
# 8 the file took up to 13.7 s, 10-16). Its exit code and output are the process's.
import runpy
sys.path.insert(0, cfg["shim"])
sys.argv = [sys.argv[2]]
runpy.run_path(sys.argv[0], run_name="__main__")
'''

    base = tmpdir()
    fake = base / "fake_winrun.py"
    fake.write_text(FAKE, encoding="utf-8")
    tech = base / "tech"
    tech.mkdir()
    log = base / "calls.log"
    relay_log = base / "relay.log"
    relay_log.write_text("", encoding="utf-8")
    shim = base / "shim"
    shim.mkdir()
    (shim / "arklog.py").write_text(
        "import importlib.util\nfrom datetime import date\n"
    f"spec = importlib.util.spec_from_file_location('_arklog', {str(ROOT / 'scripts' / 'mac' / 'lib' / 'arklog.py')!r})\n"
    "m = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(m)\n"
    "since_minutes = m.since_minutes\n"
    "def server_today():\n    return date(2026, 10, 10)\n"
    f"RELAY_LOG = {str(relay_log)!r}\n", encoding="utf-8")
    BOOT = "服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）"
    STOP = "收到停止信号，退出"
    RET = "主流程已返回，向 SCM 报告已停止；还活着的线程：MainThread、phone-mailbox"


    def relay_lines(events):
        """relay.log lines, [(seconds ago, message)], in the relay's own format, on this clock (arklog's)."""
        now = datetime.now()
        out = [(now - timedelta(seconds=150 * 60)).strftime("%m-%d %H:%M:%S") + " INFO    ark.service  next alarm"]
        for ago, msg in sorted(events, key=lambda e: -e[0]):
            out.append((now - timedelta(seconds=ago)).strftime("%m-%d %H:%M:%S") + f" INFO    ark.service  {msg}")
        relay_log.write_text("\n".join(out) + "\n", encoding="utf-8")


    # The reachability probe connects here; a thread accepts and drops each connection.
    listener = socket.create_server(("127.0.0.1", 0))
    listener_stop = threading.Event()

    def _accept_loop() -> None:
        while not listener_stop.is_set():
            try:
                listener.accept()[0].close()
            except OSError:
                return

    threading.Thread(target=_accept_loop, daemon=True).start()
    REACHABLE = f"127.0.0.1:{listener.getsockname()[1]}"
    with socket.create_server(("127.0.0.1", 0)) as _s:
        CLOSED = f"127.0.0.1:{_s.getsockname()[1]}"   # nothing listens here once it is closed


    # The probe's and a hung read's limits, short so the two waits that run them out cost
    # 0.2 s each. A probe to the local listener connects in the kernel whatever the load,
    # and a hung read is killed at its limit however late it started.
    SHORT_S = "0.2"


    def run(*args, mode="ok", timeout="15", probe=REACHABLE, cli=False):
        (base / "fake.json").write_text(json.dumps({"mode": mode, "log": str(log), "shim": str(shim)}),
                                        encoding="utf-8")
        use_real_run = cli or (mode == "hang" and probe == REACHABLE)
        import contextlib
        import io
        import runpy
        saved_env = os.environ.get("TECHLOG_WINRUN")
        saved_attrs = (tool.REMOTE_DIR, tool.FETCH_TIMEOUT, tool.PROBE, tool.PROBE_TIMEOUT, tool.run)
        os.environ["TECHLOG_WINRUN"] = f"{sys.executable} {fake}"
        tool.REMOTE_DIR = str(tech)
        tool.FETCH_TIMEOUT = float(timeout)
        tool.PROBE = probe
        tool.PROBE_TIMEOUT = float(SHORT_S)

        def inproc_winrun(wargs: list[str], _timeout: float) -> tuple[int, bytes, bytes]:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(repr(wargs) + "\n")
            if mode == "down":
                return 4, b"", b"winrun: remote produced no output (script never ran, or machine unreachable)\n"
            if not wargs or wargs[0] != "--py":
                return 9, b"", b""
            reading = "TECHLOG_DONE" in Path(wargs[1]).read_text(encoding="utf-8")
            if mode == "pyfail" and not reading:
                return 4, b"", b"winrun: remote produced no output\n"
            w_out, w_err = io.StringIO(), io.StringIO()
            w_out.write("[机器时间] 10-10 23:00:00\n")
            old_path, old_argv = list(sys.path), list(sys.argv)
            sys.path.insert(0, str(shim))
            sys.modules.pop("arklog", None)
            sys.argv = [wargs[1]]
            w_rc = 0
            try:
                with contextlib.redirect_stdout(w_out), contextlib.redirect_stderr(w_err):
                    runpy.run_path(wargs[1], run_name="__main__")
            except SystemExit as exc:
                w_rc = exc.code if isinstance(exc.code, int) else 1
            finally:
                sys.path[:] = old_path
                sys.argv[:] = old_argv
                sys.modules.pop("arklog", None)
            return w_rc, w_out.getvalue().encode("utf-8"), w_err.getvalue().encode("utf-8")

        if not use_real_run:
            tool.run = inproc_winrun
        out_buf, err_buf = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                rc = tool.main(list(args))
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        finally:
            tool.REMOTE_DIR, tool.FETCH_TIMEOUT, tool.PROBE, tool.PROBE_TIMEOUT, tool.run = saved_attrs
            if saved_env is None:
                os.environ.pop("TECHLOG_WINRUN", None)
            else:
                os.environ["TECHLOG_WINRUN"] = saved_env
        return rc, out_buf.getvalue(), err_buf.getvalue()


    relay_lines([])   # a quiet hour: one line, older than the window

    print("[no file on any of the three days: the relay has not written one yet]")
    log.write_text("")
    rc, out, err = run("red", cli=True)
    check("exit code", rc, 0)
    check("says there is no technical log yet", out.splitlines(),
          [f"{tool.NO_LOG}（2026-10-08..2026-10-10 机器上都没有文件）"])
    check("one round trip", len(log.read_text().splitlines()), 1)

    print("[red items over two days, one handled in the later day's file]")
    (tech / "2026-10-09.md").write_text(
        "\n## 23:00 收工体检\n🔴 R-20261009-2300-1 自检没过：补丁不在\n🔴 R-20261009-2300-2 关机没成功\n",
        encoding="utf-8")
    (tech / "2026-10-10.md").write_text(
        "\n## 09:00 处理\n✅ R-20261009-2300-1 已处理（abc1234）\n"
    "\n## 23:00 收工体检\n🔴 R-20261010-2300-1 relay.log 有 ERROR\n", encoding="utf-8")
    rc, out, err = run("red")
    check("exit code", rc, 0)
    check("only the unhandled items, with the day of their red line", out.splitlines(),
          ["R-20261009-2300-2\t2026-10-09\t关机没成功", "R-20261010-2300-1\t2026-10-10\trelay.log 有 ERROR"])
    rc, out, err = run("red", "--days", "1")
    check("--days 1 reads the machine's today only", out.splitlines(),
          ["R-20261010-2300-1\t2026-10-10\trelay.log 有 ERROR"])
    rc, out, err = run("red", "--days", "0")
    check("--days 0 is refused", rc, 1)

    print("[read failure]")
    rc, out, err = run("red", mode="down")
    check("exit code", rc, 2)
    check("one 没读到 line naming why", out.splitlines(),
          ["技术日志没读到：最近 3 天（winrun: remote produced no output (script never ran, or machine unreachable)）"])
    rc, out, err = run("red", "--days", "1", mode="hang", timeout=SHORT_S)
    check("a hung read: exit code", rc, 2)
    check("a hung read: says it timed out", out.splitlines(), [f"技术日志没读到：最近 1 天（超过 {SHORT_S} 秒没回来）"])
    locked = tech / "2026-10-08.md"
    locked.write_text("x\n", encoding="utf-8")
    locked.chmod(0)
    try:
        rc, out, err = run("red")
        check("a day the machine cannot open: exit code", rc, 2)
        check("a day the machine cannot open: named", out.splitlines(),
              ["技术日志没读到：最近 3 天（2026-10-08（PermissionError））"])
    finally:
        locked.chmod(0o644)
        locked.unlink()

    print("[machine unreachable: one fast line, exit 3, nothing else tried]")
    for label, probe in (("refused", CLOSED), ("no answer", "127.0.0.2:22")):
        log.write_text("")
        t0 = time.monotonic()
        rc, out, err = run("red", mode="hang", probe=probe)
        took = time.monotonic() - t0
        check(f"{label}: exit code", rc, 3)
        check(f"{label}: the one line", out.startswith("游戏机现在连不上（关机或断网）：") and len(out.splitlines()) == 1, True)
        check(f"{label}: fast (the hanging read was never started)", (took < 5, log.read_text()), (True, ""))
    rc, out, err = run("handled", "R-20261010-2300-1", "def5678", probe=CLOSED)
    check("handled while unreachable: exit code", rc, 3)

    print("[show]")
    rc, out, err = run("show", "2026-10-09")
    check("show prints the file", out, (tech / "2026-10-09.md").read_text(encoding="utf-8"))
    rc, out, err = run("show", "2026-10-01")
    check("show of a missing day: exit code", rc, 0)
    check("show of a missing day: says so", out.strip(), f"{tool.NO_LOG}（2026-10-01 机器上没有这天的文件）")
    rc, out, err = run("show", "2026-10-11")
    check("show of a day after the machine's today: exit code", rc, 1)
    rc, out, err = run("show", "2026-13-01")
    check("show of an impossible date: exit code", rc, 1)
    rc, out, err = run("show", "2026-10-09", mode="down")
    check("show when the read fails: exit code", rc, 2)

    print("[handled]")
    log.write_text("")
    before = (tech / "2026-10-10.md").read_text(encoding="utf-8")
    rc, out, err = run("handled", "R-20261010-2300-1", "def5678")
    check("exit code", rc, 0)
    check("confirmed", out.strip(), "已标处理：R-20261010-2300-1（def5678），复查确认")
    after = (tech / "2026-10-10.md").read_text(encoding="utf-8")
    check("exactly the handled line was appended", after[len(before):],
          tool.handled_line("R-20261010-2300-1", "def5678") + "\n")
    check("no command line carried Chinese", all(ln.isascii() for ln in log.read_text(encoding="utf-8").splitlines()), True)
    check("read, write, re-read: three round trips", len(log.read_text().splitlines()), 3)
    rc, out, err = run("red")
    check("red no longer lists it", out.splitlines(), ["R-20261009-2300-2\t2026-10-09\t关机没成功"])

    rc, out, err = run("handled", "R-20261010-2300-1", "def5678")
    check("marking it again: exit code", rc, 0)
    check("marking it again: nothing appended", (tech / "2026-10-10.md").read_text(encoding="utf-8"), after)

    rc, out, err = run("handled", "R-20261010-0000-9", "def5678")
    check("an id that is not in the log: exit code", rc, 1)
    check("an id that is not in the log: file untouched", (tech / "2026-10-10.md").read_text(encoding="utf-8"), after)
    rc, out, err = run("handled", "R-20261011-0000-1", "def5678")
    check("an id dated after the machine's today: exit code", rc, 1)
    rc, out, err = run("handled", "R-20261010-2300-1", "bad commit")
    check("a malformed commit: exit code", rc, 1)

    rc, out, err = run("handled", "R-20261009-2300-2", "def5678", mode="pyfail")
    check("a write that fails: exit code", rc, 1)
    check("a write that fails: says the re-check did not pass", "复查没过" in err, True)

    rc, out, err = run("handled", "R-20261009-2300-2", "def5678", mode="down")
    check("handled while the read fails: exit code", rc, 2)

    rc, out, err = run("handled", "R-20261009-2300-2", "def5678")
    check("handled into the red line's file: exit code", rc, 0)
    check("the line landed in 2026-10-09.md", (tech / "2026-10-09.md").read_text(encoding="utf-8").splitlines()[-1],
          tool.handled_line("R-20261009-2300-2", "def5678"))
    rc, out, err = run("red")
    check("nothing red left: files exist, stdout empty", (rc, out), (0, ""))

    print("[relay crash-restart loop, read live from relay.log]")
    for f in tech.glob("*.md"):
        f.unlink()
    gaps = [18, 19, 20, 22, 19, 18, 18, 20, 18, 17, 19, 19, 19, 18, 19]
    t, loop = 20 * 60, [(20 * 60 + 4, STOP), (20 * 60 + 4, RET), (20 * 60, BOOT)]
    for g in gaps:
        t -= g
        loop.append((t, BOOT))
    loop += [(t - 17, STOP), (t - 17, RET), (t - 17.5, BOOT)]
    relay_lines(loop)
    rc, out, err = run("red")
    check("exit code", rc, 0)
    check("a live red item, and no 'no log yet' line beside it", out.splitlines(),
          ["R-LIVE-restarts\t2026-10-10\t中继最近 60 分钟重启了 17 次，其中 15 次不是正常停止"])

    # Deploy restarts: stop lines before each boot. One of them shaped like 16:59:15-16:59:30 (a second boot 12 s later).
    relay_lines([(50 * 60, STOP), (50 * 60, RET), (50 * 60 - 3, BOOT),
                 (40 * 60, STOP), (40 * 60, RET), (40 * 60 - 3, BOOT), (40 * 60 - 15, BOOT),
                 (30 * 60, STOP), (30 * 60, RET), (30 * 60 - 3, BOOT),
                 (10 * 60, STOP), (10 * 60, RET), (10 * 60 - 5, BOOT)])
    rc, out, err = run("red")
    check("deploy restarts: nothing red", (rc, out.startswith(tool.NO_LOG)), (0, True))
    check("deploy restarts: the summary counts them", "restarts in the last 60 min: 5 (1 without a stop)" in err, True)

    relay_lines([(80 * 60 - 20 * i, BOOT) for i in range(10)])
    rc, out, err = run("red")
    check("a loop that ended before the window: nothing red", (rc, out.startswith(tool.NO_LOG)), (0, True))
    rc, out, err = run("handled", "R-LIVE-restarts", "def5678")
    check("a live item cannot be marked handled", rc, 1)

    print("[the generated scripts pass winrun's send gates]")
    gens = {
        "techlog_read.py": tool.READ_SCRIPT.format(tech_dir=tool.REMOTE_DIR, first=None, back=2, max_days=tool.MAX_DAYS,
                                                   live=True, wide=75, narrow=60),
        "techlog_handled.py": tool.WRITE_SCRIPT.format(tech_dir=tool.REMOTE_DIR, day="2026-10-10",
                                                       line=tool.handled_line("R-20261010-2300-1", "def5678")),
    }
    winrun_staged = stage_mac_script(ROOT, "winrun.sh")
    for name, text in gens.items():
        gen = base / name
        gen.write_text(text, encoding="utf-8")
        compile(text, str(gen), "exec")
        r = subprocess.run([str(winrun_staged), "--py", str(gen)], capture_output=True, text=True,
                           env=dict(os.environ, WINRUN_DRY_RUN="1"), timeout=30)
        check(f"{name}: winrun dry run lets it through", (r.returncode, "dry-run" in r.stdout), (0, True))

    print("[the format matches the relay's writer, when it is on this branch]")
    writer = ROOT / "relay" / "ark_relay" / "core" / "statestore.py"
    if writer.is_file():
        src = writer.read_text(encoding="utf-8")
        check("RED_LINE", f'RED_LINE = re.compile(r"{tool.RED_LINE.pattern}")' in src, True)
        check("DONE_LINE", f'DONE_LINE = re.compile(r"{tool.DONE_LINE.pattern}")' in src, True)
        m = re.search(r'return f"\{DONE\} \{item_id\} (.*)"', src)
        check("handled_line", m and tool.handled_line("X", "Y") == f"✅ X {m.group(1)}".replace("{commit}", "Y"), True)
    else:
        print("  - relay/ark_relay/core/statestore.py is not on this branch yet; compared once it lands")

    listener_stop.set()
    try:
        socket.create_connection(listener.getsockname(), timeout=0.5).close()
    except OSError:
        pass
    listener.close()
    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_build_notes_at_deploy_tip():
    """packaging/build.py builds at a deploy commit, whose RELEASE-NOTES.md is emptied."""
    import hashlib
    import json
    import subprocess
    import tempfile

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY.parent / "packaging"))

    import build


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


def _part_dead_helpers_gone():
    """Helpers nothing called are gone and stay gone (review 2026-10-13, s5 #10)."""
    import re

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.core import desktop, notify, statestore as techlog


    print("[没人调用的辅助已删掉]")
    check("Notifier.send_image", hasattr(notify.Notifier, "send_image"), False)
    check("WeCom.send_image", hasattr(notify.WeCom, "send_image"), False)
    check("WeCom._upload", hasattr(notify.WeCom, "_upload"), False)
    check("notify._hint", hasattr(notify, "_hint"), False)
    check("techlog.red_items", hasattr(techlog, "red_items"), False)
    check("群机器人发图还在", hasattr(notify.Notifier, "send_group_image"), True)
    check("按字点击还在", hasattr(desktop.Desktop, "click_text"), True)

    print("\n[也没有哪里再调用它们]")
    srcs = [p for p in (ROOT / "ark_relay").rglob("*.py") if "okww_files" not in p.parts]
    srcs += [ROOT / "service.py", ROOT / "boot_stages.py"] + list((ROOT.parent / "scripts").rglob("*.py"))
    # WeComBot.send_image (the group image) stays; scripts/mac/techlog.py has its own red_items.
    pat = re.compile(r"(?<!wecom_bot)\.send_image\(|\._upload\(|\b_hint\(|\bcore\.techlog\b.*red_items|"
                     r"\btechlog\.red_items\(")
    hits = [f"{p.name}:{i}" for p in srcs for i, ln in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
            if pat.search(ln)]
    check("没有调用处", hits, [])


def _part_diag_pull_silent():
    """diag-pull.py must not exit 0 when a record could not be fetched."""
    import contextlib
    import importlib.util
    import io

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay" / "tests"))

    spec = importlib.util.spec_from_file_location("diag_pull", ROOT / "scripts" / "mac" / "diag-pull.py")
    dp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dp)


    def run(get):
        d = tmpdir()
        dp.DEST = d / "ark-diag"
        dp.env = lambda _p: {"COS_SECRET_ID": "i", "COS_SECRET_KEY": "k", "COS_DIAG_BUCKET": "b-1"}
        dp.listing = lambda _cos: [("diag/a.json", 3, "2026-10-10T01:00:00"),
                                   ("diag/b.json", 3, "2026-10-10T02:00:00")]
        dp.get = get
        old = sys.argv
        sys.argv = ["diag-pull.py"]
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = dp.main()
        finally:
            sys.argv = old
        return rc, out.getvalue(), err.getvalue(), d


    print("[one of two records fails to fetch]")
    rc, out, err, d = run(lambda _cos, key, params="": (500, b"boom") if key == "diag/b.json" else (200, b"{}"))
    check("exit code is non-zero", rc, 1)
    check("the good record is on disk", (d / "ark-diag" / "a.json").exists(), True)
    check("the summary names the failure count", "失败 1 条" in out, True)
    check("the per-record error is still on stderr", "取回失败 500" in err, True)

    print("[every record fetched]")
    rc, out, err, d = run(lambda _cos, key, params="": (200, b"{}"))
    check("exit code is 0", rc, 0)
    check("no failure count in the summary", "失败" in out, False)


def _part_release_notes():
    """更新播报要说「修好了什么毛病」，不是列一串文件名。"""
    import re
    import tempfile

    HERE = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(HERE))


    def render(notes_dir: Path, files: list[str]) -> str:
        """service.py 里组装播报正文的那几行，原样复刻。"""
        lines = ["刚刚生效", "版本 v1 → v2"]
        notes = ""
        nf = notes_dir / "RELEASE-NOTES.md"
        if nf.exists():
            notes = nf.read_text(encoding="utf-8").strip()
        if notes:
            lines += ["", notes]
        else:
            lines.append("改动文件：" + "、".join(files) if files
                         else "（改动清单由上一版代码写入，本次没有）")
        lines += ["", "更新在开机后、队列开跑前落地，本轮直接使用新代码。"]
        return "\n".join(lines)


    def test_switch(tmp: Path) -> None:
        print("[有说明文件时念说明，没有时列文件名]")

        empty = tmp / "no-notes"
        empty.mkdir()
        body = render(empty, ["service.py", "preupdate.py"])
        check("没有说明文件 → 退回列文件名（老行为不退化）",
              "改动文件：service.py、preupdate.py" in body, True)

        withn = tmp / "with-notes"
        withn.mkdir()
        (withn / "RELEASE-NOTES.md").write_text(
            "开机预更新的两处误报修好了\n\n· MAA 明明已经下载好了，中继却说没确认到\n",
            encoding="utf-8")
        body = render(withn, ["service.py", "preupdate.py"])
        check("有说明文件 → 正文里有说明", "开机预更新的两处误报修好了" in body, True)
        check("有说明文件 → 不再列文件名", "改动文件：" in body, False)

        blank = tmp / "blank-notes"
        blank.mkdir()
        (blank / "RELEASE-NOTES.md").write_text("   \n\n  \n", encoding="utf-8")
        body = render(blank, ["service.py"])
        check("说明文件是空白 → 当作没有，退回列文件名",
              "改动文件：service.py" in body, True)


    def test_is_plain_language() -> None:
        """随仓库的那份说明本身要是人话。"""
        print("[RELEASE-NOTES.md 是不是人话]")
        nf = HERE / "RELEASE-NOTES.md"
        check("说明文件存在", nf.exists(), True)
        if not nf.exists():
            return
        text = nf.read_text(encoding="utf-8")
        if not text.strip():
            # 空是**合法状态**：部署成功后脚本会把它清零，逼下一次写新的。
            # 拦「空着就部署」是部署脚本的闸（`[ ! -s "$NOTES" ]`），不是这里的事；
            # 这里只负责「有内容的时候，内容得是人话」。
            print("  ok   文件是空的——刚部署完的正常状态，人话检查跳过")
            return

        jargon = {
            "下划线函数名": r"\b[a-z]+_[a-z_]+\(",
            "函数调用括号": r"\w+\(\)",
            "代码文件名":   r"\b\w+\.(py|json|sh|md)\b",
            "驼峰标识符":   r"\b[a-z]+[A-Z]\w+\b",
        }
        for label, rx in jargon.items():
            hit = re.search(rx, text)
            check(f"不含{label}", hit.group(0) if hit else None, None)


    def main(tmp: Path) -> int:
        test_switch(tmp)
        test_is_plain_language()
        print("all checks passed" if not fails else f"FAILED: {fails}")
        return 0 if not fails else 1


    if __name__ == "__main__":
        with tempfile.TemporaryDirectory() as t:
            raise SystemExit(main(Path(t)))


def _part_replay_gate():
    """Deploy gate E1: the offline replay of outcome / errwatch over the real 2026-10-06 logs."""
    import importlib.util

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.features import outcome
    from ark_relay.features import selfcheck as replay

    FIX = fx_dir(Path(__file__), "fixtures")
    OKWW = (FIX / "okww-1006-run.log").read_text(encoding="utf-8")
    RELAY = (FIX / "relay-1006-false-alarms.log").read_text(encoding="utf-8")


    print("[OK-WW: the update note once matched 「结晶波片不足」]")
    check("this code pushes nothing", replay.okww_pushes(OKWW), [])

    orig = outcome.okww_checks


    def pre_fix_checks(text, **kw):
        """The weekly judgement before 12edfb0b, reproduced: a substring match of
    「结晶波片不足」 over every line of the log, update note included, read as an
    unclaimed week. Since 2026-10-07 a real shortage is green and is read only from
    the overlay's own skip line (outcome.WEEKLY_SHORT), so no data patch of the
    current code brings the old alarm back; the old rule is stubbed in instead."""
        out = orig(text, **kw)
        if "Teleport to Boss Weekly Challenge" in text and "结晶波片不足" in text:
            out = [c for c in out if not c.label.startswith("周本")]
            out.append(outcome.Check("周本领到了奖励", False, "结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」）"))
        return out


    outcome.okww_checks = pre_fix_checks
    try:
        old = replay.okww_pushes(OKWW)
        check("pre-fix code pushes exactly one", len(old), 1)
        check("it is the waveplate-shortage false alarm", "结晶波片不足" in (old[0] if old else ""), True)
    finally:
        outcome.okww_checks = orig

    print("[relay.log: the banner calendar #2 and shutdown snapshot false alarms]")
    check("this code pushes nothing", replay.errwatch_pushes(RELAY), [])

    from ark_relay.features import banners as _hub
    from ark_relay.features import annihilation as _ann

    _cal = _hub._wuwa_calendar_start
    _hub._wuwa_calendar_start = lambda n, p, now, end, ri, notes, tr: _cal(n, p, now, end, ri, {} if notes is None else notes, tr)
    try:
        got = replay.errwatch_pushes(RELAY)
        check("the calendar read even though another source gave the time: the 10-06 pushes are back",
              sorted({p["where"] for p in got}), ["ark.banners", "ark.machinecheck"])
        check("……among them 「没找到…的日期」 and 「只有图，没读到字」",
              (any("没找到「余心所向九死未悔」的日期" in p["line"] for p in got),
               any(p["line"].startswith("这条公告只有图，没读到字") for p in got)), (True, True))
        check("……and the #2 machine check FAIL", any("#2" in p["line"] for p in got), True)
    finally:
        _hub._wuwa_calendar_start = _cal

    _down = _ann._going_down
    _ann._going_down = lambda: False
    try:
        got = replay.errwatch_pushes(RELAY)
        check("the snapshot read during the relay's own power-off: both AUTO-MAS sections push",
              [p["line"] for p in got], ["快照的 _MAS错误 这一段读不到", "快照的 _队列错误 这一段读不到"])
    finally:
        _ann._going_down = _down
    check("……and with the fixes in place it is quiet again", replay.errwatch_pushes(RELAY), [])
    check("main() stops a deploy whose snapshot fix is gone", (
        setattr(_ann, "_going_down", lambda: False),
        replay.main([str(FIX / "relay-1006-false-alarms.log")]),
        setattr(_ann, "_going_down", _down))[1], 1)
    check("the replay leaves no handler on the ark logger",
          [type(h).__name__ for h in __import__("logging").getLogger(__import__("ark_relay.features.errwatch", fromlist=["ARK"]).ARK).handlers], [])

    print("[a genuine ERROR still pushes; INFO / diag / traceback lines do not]")
    check("a real ERROR line pushes",
          replay.errwatch_pushes("10-06 06:20:17 ERROR   ark.engine  采集超时：残象聚落"),
          [{"where": "ark.engine", "line": "采集超时：残象聚落", "lineno": 1}])
    check("INFO and bare diag / traceback lines are skipped",
          replay.errwatch_pushes('10-06 06:20:17 INFO    ark.machinecheck  ok\ndiag: x\n  File "x"\nTraceback (most recent call last):\n'),
          [])

    print("[the deploy script's entry point over both fixtures]")
    check("main exits 0, deploy may proceed",
          replay.main([str(FIX / "okww-1006-run.log"), str(FIX / "relay-1006-false-alarms.log")]), 0)

    print("[the deploy script passes file paths: the OK-WW fixture must be replayed as an OK-WW run log]")
    check("the fixture path is read as an OK-WW run log", replay._is_okww(str(FIX / "okww-1006-run.log")), True)
    check("an evidence-package log name is too", replay._is_okww("OK-WW-05-19-08.log"), True)
    check("the relay.log fixture is not", replay._is_okww(str(FIX / "relay-1006-false-alarms.log")), False)
    outcome.okww_checks = pre_fix_checks
    try:
        check("main() over the fixtures stops the pre-fix code (the gate really blocks)",
              replay.main([str(FIX / "okww-1006-run.log")]), 1)
    finally:
        outcome.okww_checks = orig

    print("[the deploy script's `python3 -m` target can be run by runpy]")
    import re as _re
    _deploy = (Path(__file__).resolve().parents[2] / "scripts" / "mac" / "deploy-relay.sh").read_text(encoding="utf-8")
    for _mod in _re.findall(r"python3 -m (ark_relay[\w.]*)", _deploy):
        _spec = importlib.util.find_spec(_mod)
        check(f"{_mod} has a loader runpy can use", bool(_spec and hasattr(_spec.loader, "get_code")), True)


def _part_tools_import_installed_relay():
    """Tools that import ark_relay on the gaming machine import the installed relay's code."""
    import contextlib
    import io
    import re
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
    import relay_code


    # Files that address the old relay's folder on purpose.
    ALLOW = {
        "scripts/mac/lib/relay_code.py": "the fallback for a machine without the installed relay",
        "scripts/windows/skip-shutdown.bat": "the same fallback, inline (checked in section 4)",
        "scripts/mac/deploy-relay.sh": "its old-layout branch deploys the old relay into that folder",
        "scripts/windows/smoke.py": "deploy smoke; deploy-pkg.sh passes --pkg-version, the default is the old layout",
    }

    # The old folder itself: backslashes as written in .py / .md / .bat / .sh (one, or doubled
    # inside a string literal), optionally a trailing one, then the end of the literal.
    OLD = r"ProgramData(?:\\{1,2}|/)ark-relay(?:\\{1,2}|/)?"
    OLD_END = OLD + r"""\\?["')%]"""
    SYSPATH = re.compile(r"sys\.path\.(?:insert|append)\(([^)\n]*)\)")
    BIND_PY = re.compile(r"""(?:^|[;\s])([A-Za-z_]\w*)\s*=\s*[^;\n]*?""" + OLD_END, re.M)
    BIND_BAT = re.compile(r"""^\s*set\s+"?([A-Za-z_]\w*)=[^\n"]*""" + OLD + r"""\s*"?\s*$""", re.M | re.I)
    OLD_CODE_FILE = re.compile(OLD + r"(?:\\{1,2}|/)ark_relay\b")


    def offences(text: str) -> list:
        out = []
        names = set(BIND_PY.findall(text)) | set(BIND_BAT.findall(text))
        for m in SYSPATH.finditer(text):
            arg = m.group(1) + ")"
            if re.search(OLD_END, arg) or re.search(OLD + r"\\?\\?\"", arg):
                out.append(m.group(0)[:120])
                continue
            for n in names:
                if re.search(rf"\b{n}\b|%{n}%", m.group(1)):
                    out.append(f"{m.group(0)[:100]} ({n} = the old folder)")
        out += [f"reads old code: {m.group(0)}" for m in OLD_CODE_FILE.finditer(text)]
        return out


    def scan(paths) -> dict:
        found = {}
        for p in paths:
            rel = p.relative_to(ROOT).as_posix()
            if rel in ALLOW:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "ark-relay" not in text:
                continue
            hits = offences(text)
            if hits:
                found[rel] = hits
        return found


    print("[1. nothing puts the old folder on sys.path]")
    files = [p for d in ("scripts", "docs") for p in (ROOT / d).rglob("*")
             if p.is_file() and p.suffix in (".py", ".sh", ".md", ".bat", ".ps1", ".txt")]
    found = scan(files)
    require(f"{len(files)} files under scripts/ and docs/", not found,
          "; ".join(f"{k}: {v[0]}" for k, v in sorted(found.items())))

    SHAPES = {
        "literal": 'import sys\nsys.path.insert(0, r"C:\\ProgramData\\ark-relay")\n',
        "named": 'R = Path(r"C:\\ProgramData\\ark-relay")\nsys.path.insert(0, str(R))\n',
        "one line": 'root = pathlib.Path(r"C:\\ProgramData\\ark-relay"); sys.path.insert(0, str(root))\n',
        "bat": "set RELAY=C:\\ProgramData\\ark-relay\n\"%PY%\" -c \"import sys; sys.path.insert(0, r'%RELAY%')\"\n",
        "doc": 'winps.sh \'& py -c "import sys; sys.path.insert(0, r\\"C:\\ProgramData\\ark-relay\\"); x"\'\n',
        "old code file": 'ref = Path(r"C:\\ProgramData\\ark-relay\\ark_relay\\okww_files")\n',
    }
    for name, text in SHAPES.items():
        require(f"scan catches the {name} shape", bool(offences(text)), text)
    DATA_ONLY = ('_load_dotenv(Path(r"C:\\ProgramData\\ark-relay\\.env"))\n'
                 'st = Path(r"C:\\ProgramData\\ark-relay\\state")\n'
                 'set DATA=C:\\ProgramData\\ark-relay\nPath(r\'%DATA%\\state\')\n')
    require("scan leaves data paths alone", not offences(DATA_ONLY), str(offences(DATA_ONLY)))

    print("\n[2. the tools import relay_code where winrun ships it]")
    winrun = (ROOT / "scripts" / "mac" / "winrun.sh").read_text(encoding="utf-8")
    m = re.search(r"grep -oE '(\^\(from\|import\) \+\[a-z_\]\[a-z0-9_\]\*)'", winrun)
    require("winrun.sh still ships same-folder modules by their import line", bool(m))
    SHIP = re.compile(m.group(1) if m else r"^(from|import) +[a-z_][a-z0-9_]*", re.M)
    TOOLS = {
        "scripts/mac/lib/healthcheck.py": "use_relay_code()",
        "scripts/mac/lib/okww_effective.py": "use_relay_code()",
        "scripts/mac/lib/maaend_only_task.py": "use_relay_code()",
        "scripts/windows/okww-landed.py": "use_relay_code()",
    }
    for rel, call in TOOLS.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        shipped = any(s.split()[-1] == "relay_code" for s in SHIP.findall(text)) or \
            any(line.split()[1] == "relay_code" for line in text.splitlines()
                if SHIP.match(line) and len(line.split()) > 1)
        require(f"{rel}: imports relay_code at column 0 and calls {call}", shipped and call in text)

    print("\n[3. relay_code.code_root]")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        app, legacy = t / "ArkRelay", t / "ark-relay"
        (app / "versions" / "20261011073720" / "ark_relay").mkdir(parents=True)
        (app / "versions" / "20261011073720" / "ark_relay" / "__init__.py").write_text("")
        (app / "current.txt").write_text("20261011073720\n", encoding="ascii")
        got = relay_code.code_root(app, legacy)
        require("installed: versions\\<current.txt>", got == (app / "versions" / "20261011073720", True), str(got))
        (app / "current.txt").write_text("20261011999999\n", encoding="ascii")
        require("current.txt naming a folder without ark_relay: the old folder",
              relay_code.code_root(app, legacy) == (legacy, False))
        err = io.StringIO()
        saved = list(sys.path)
        with contextlib.redirect_stderr(err):
            got = relay_code.use_relay_code(t / "nothing", legacy)
        first = sys.path[0]
        sys.path[:] = saved
        require("no installed relay: the old folder, first on sys.path", got == legacy and first == str(legacy))
        require("... and one line on stderr saying so", "no installed relay" in err.getvalue()
              and "{" not in err.getvalue(), err.getvalue())

    print("\n[4. skip-shutdown.bat]")
    raw = (ROOT / "scripts" / "windows" / "skip-shutdown.bat").read_bytes()
    lines = raw.split(b"\n")[:-1] if raw.endswith(b"\n") else raw.split(b"\n")
    lf_only = sum(not l.endswith(b"\r") for l in lines)
    require("CRLF on every line", lf_only == 0, f"{lf_only} LF-only lines")
    bat = raw.decode("utf-8")
    require("reads current.txt for the code folder",
          '"%APP%\\current.txt"' in bat and "%APP%\\versions\\%%v" in bat)
    require("puts the code folder (not the data folder) on sys.path",
          bat.count("sys.path.insert(0, r'%CODE%')") == 3 and "sys.path.insert(0, r'%DATA%')" not in bat)
    quoted = re.findall(r"""for /f [^\n]*?in \('"[^\n]*""", bat)
    require("no for /f command starts with a quote", not quoted, quoted[0][:80] if quoted else "")
    require("says when it falls back to the old code", "if defined OLDCODE echo" in bat)
    require("runs the installed relay's own Python, never AUTO-MAS's",
            'set "PY=%APP%\\runtime\\python\\python.exe"' in bat and "automas" not in bat.lower())

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_unmerged_fixes():
    """deploy-relay.sh step 0.6: a finished relay fix may not sit on a branch, unreviewed."""
    import contextlib
    import importlib.util
    import io
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]


    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


    uf = load("unmerged_fixes", ROOT / "scripts/mac/lib/unmerged_fixes.py")


    G = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


    def git(*a, cwd):
        return subprocess.run([*G, *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


    def commit(base, path, text, msg):
        p = base / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        git("add", "-A", cwd=base)
        git("commit", "-qm", msg, cwd=base)
        return git("rev-parse", "HEAD", cwd=base).strip()


    def run(base, reviewed):
        (base / "docs").mkdir(exist_ok=True)
        (base / "docs/UNMERGED-REVIEWED.txt").write_text(reviewed, encoding="utf-8")
        out = io.StringIO()
        argv = sys.argv
        sys.argv = ["unmerged_fixes.py", "--root", str(base)]
        try:
            with contextlib.redirect_stdout(out):
                rc = uf.main()
        finally:
            sys.argv = argv
        return rc, out.getvalue()


    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        git("init", "-q", "-b", "main", cwd=base)
        for k, v in (("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"),
                     ("diff.renames", "false")):
            git("config", k, v, cwd=base)
        commit(base, "relay/ark_relay/x.py", "A = 1\n", "base")
        git("update-ref", "refs/remotes/origin/main", "main", cwd=base)

        git("checkout", "-qb", "fix-branch", cwd=base)
        fix = commit(base, "relay/ark_relay/x.py", "A = 2\n", "relay: the fix nobody merged")
        git("checkout", "-qb", "docs-branch", "main", cwd=base)
        commit(base, "docs/NOTE.md", "note\n", "docs only")
        git("checkout", "-qb", "tests-branch", "main", cwd=base)
        commit(base, "relay/tests/daysim/test_day.py", "T = 1\n", "tests only")
        commit(base, "relay/make-manifest.py", "M = 1\n", "manifest tool only")
        git("checkout", "-qb", "top-branch", "main", cwd=base)
        top = commit(base, "relay/boot_x.py", "D = 1\n", "relay: a top-level module fix")
        git("checkout", "-qb", "picked-branch", "main", cwd=base)
        picked = commit(base, "scripts/windows/w.py", "B = 1\n", "windows: picked into main")
        git("checkout", "-q", "main", cwd=base)
        # main moves first, so the pick gets a new parent and a new hash (same second,
        # same parent would reproduce the very same commit).
        commit(base, "relay/ark_relay/y.py", "C = 1\n", "main moves on")
        git("cherry-pick", picked, cwd=base)
        git("update-ref", "refs/remotes/origin/main", "main", cwd=base)
        check("git cherry marks the picked commit '-'",
              git("cherry", "origin/main", "picked-branch", cwd=base).split()[0], "-")

        rc, out = run(base, "# nothing reviewed yet\n")
        check("an unlisted relay commit blocks", rc, 1)
        check("the output names branch, hash and subject",
              f"fix-branch  {fix[:8]}  relay: the fix nobody merged" in out, True)
        check("the docs-only commit is not listed", "docs only" in out, False)
        check("commits touching only relay/tests/ or make-manifest.py are not listed",
              ("tests only" in out, "manifest tool only" in out), (False, False))
        check("a top-level relay/*.py commit is listed", f"top-branch  {top[:8]}" in out, True)
        check("the cherry-equivalent commit is not listed", picked[:8] in out, False)
        check("exactly two commits block", "2 relay commit(s)" in out, True)

        rc, out = run(base, f"# reviewed\n{fix[:8]} declined DECISIONS D-1011 test\n"
                            f"{top[:8]} declined DECISIONS D-1011 test\n")
        check("the same commit, listed, passes", rc, 0)

        rc, out = run(base, f"{fix[:8]} maybe not sure\n")
        check("an unknown verdict fails closed", (rc, "unreadable lines" in out), (1, True))
        rc, out = run(base, f"{fix[:8]} a\n")
        check("a verdict without a reason fails closed", rc, 1)

        git("checkout", "-q", "fix-branch", cwd=base)
        rc, out = run(base, f"{top[:8]} declined DECISIONS D-1011 test\n")
        check("a commit on HEAD (pushed to main by this deploy) does not block", rc, 0)

    deploy = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
    gate = deploy.find("lib/unmerged_fixes.py")
    check("deploy-relay.sh runs the gate before the pre-deploy replay",
          0 < gate < deploy.find("ark_relay.features.selfcheck"), True)
    check("a failed gate exits the deploy", "exit 1" in deploy[gate:gate + 600], True)

    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_winps_shutdown_guard():
    """winps.sh / winrun.sh / wingui.sh launch refuse shutdowns on busy procs, open blockers, dirty code, or pending deploys."""
    import json as _json
    import os
    import re
    import stat
    import subprocess

    root = Path(__file__).resolve().parents[2]
    winps = stage_mac_script(root, "winps.sh")
    wingui = stage_mac_script(root, "wingui.sh")
    winrun = stage_mac_script(root, "winrun.sh")
    tmp = tmpdir()
    sent = tmp / "sent.ps1"
    # Clean temporary git repo with tag relay-20261124000000 so host dirty tree / HEAD never interferes.
    fake_repo = tmp / "repo"
    (fake_repo / "relay" / "ark_relay").mkdir(parents=True)
    (fake_repo / "relay" / "ark_relay" / "dummy.py").write_text("x = 1\n", encoding="utf-8")
    git_env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "-C", str(fake_repo), "init", "-q"], check=True, env=git_env)
    subprocess.run(["git", "-C", str(fake_repo), "add", "."], check=True, env=git_env)
    subprocess.run(["git", "-C", str(fake_repo), "commit", "-q", "-m", "init"], check=True, env=git_env)
    subprocess.run(["git", "-C", str(fake_repo), "tag", "relay-20261124000000"], check=True, env=git_env)

    empty_ledger = tmp / "ledger.jsonl"
    empty_ledger.write_text("", encoding="utf-8")
    empty_pending = tmp / "pending.json"
    empty_pending.write_text("[]\n", encoding="utf-8")

    fake = tmp / "ssh"
    fake.write_text("""#!/usr/bin/env python3
import base64, os, re, sys
here = os.path.dirname(os.path.abspath(__file__))
cmd = sys.argv[-1]
if "current.txt" in cmd:
    print(open(os.path.join(here, "cur.txt"), encoding="utf-8").read().strip())
    sys.exit(0)
m = re.search(r"-EncodedCommand (\\S+)", cmd)
if not m:
    sys.exit(0)
ps = base64.b64decode(m.group(1)).decode("utf-16-le")
open(os.path.join(here, "sent.ps1"), "w", encoding="utf-8").write(ps)
busy = open(os.path.join(here, "busy.txt"), encoding="utf-8").read().strip()
out = ("WINPS_REFUSED: " + busy) if busy and "WINPS_REFUSED" in ps else "ran"
print("WINPS_B64=" + base64.b64encode(out.encode()).decode())
""", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    (tmp / "cur.txt").write_text("20261124000000\n", encoding="utf-8")

    def run(script, busy="", override="", ledger=None, pending=None, repo=None):
        sent.unlink(missing_ok=True)
        (tmp / "busy.txt").write_text(busy, encoding="utf-8")
        env = dict(
            os.environ,
            PATH=f"{tmp}:{os.environ['PATH']}",
            ARK_HOST="127.0.0.1",
            ARK_LEDGER=str(ledger or empty_ledger),
            ARK_PENDING_DEPLOY=str(pending or empty_pending),
            ARK_SHUTDOWN_GUARD_REPO=str(repo or fake_repo),
            ARK_ACTION_LOG="/dev/null",
        )
        env.pop("ARK_SHUTDOWN_OVERRIDE", None)
        if override:
            env["ARK_SHUTDOWN_OVERRIDE"] = override
        p = subprocess.run(["bash", str(winps), script], capture_output=True, text=True, env=env, timeout=30)
        return p.returncode, sent.read_text(encoding="utf-8") if sent.exists() else ""

    print("[a shutdown while OK-WW runs: refused, exit 5]")
    code, ps = run("shutdown /s /t 60", busy="Client-Win64-Shipping")
    check("exit 5", code, 5)
    check("the check went first", ps.index("WINPS_REFUSED") < ps.index("shutdown /s /t 60"), True)
    check("PS7 layered DateTime check present", "$__u -is [DateTime]" in ps and "Test-Path -LiteralPath" in ps, True)
    check("Stop-Computer -Force: checked end-to-end", "WINPS_REFUSED" in run("Stop-Computer -Force", busy="MAA")[1], True)
    # Cover additional bypass syntaxes in-process (same detector winps/winrun call) to stay fast.
    sys.path.insert(0, str(root / "scripts" / "mac" / "lib"))
    import shutdown_guard as _sg
    for sample in ("Restart-Computer", "shutdown.exe -r -t 0", "shut`down /s /t 0",
                   "Start-Process\nshutdown /s", "s^hutdown /s", "logoff", "rundll32 powrprof,SetSuspendState"):
        check(f"detect {sample!r}", _sg.is_shutdown_cmd(sample), True)
    check("in-process AST ExitWindowsEx detected", _sg.is_shutdown_py_source("ctypes.windll.user32.ExitWindowsEx(1, 0)"), True)
    print("\n[nothing running & clean repo: the shutdown goes through]")
    check("exit 0", run("shutdown /s /t 60")[0], 0)
    print("\n[local ledger blocker / pending_deploy / dirty runtime / ahead commit -> exit 5 before SSH #2]")
    blk_ledger = tmp / "blk.jsonl"
    blk_ledger.write_text(_json.dumps({"id": 1, "status": "open", "kind": "pending_deploy", "what": "未上机"}) + "\n",
                          encoding="utf-8")
    code, ps = run("shutdown /s /t 60", ledger=blk_ledger)
    check("blocking ledger -> exit 5", (code, ps == ""), (5, True))
    pend_newer = tmp / "pend_newer.json"
    pend_newer.write_text(_json.dumps([{"version": "20261124999999"}]) + "\n", encoding="utf-8")
    code, ps = run("shutdown /s /t 60", pending=pend_newer)
    check("pending_deploy newer -> exit 5", (code, ps == ""), (5, True))
    (fake_repo / "relay" / "ark_relay" / "dummy.py").write_text("x = 2\n", encoding="utf-8")
    code, ps = run("shutdown /s /t 60")
    check("dirty runtime file -> exit 5", (code, ps == ""), (5, True))
    subprocess.run(["git", "-C", str(fake_repo), "add", "."], check=True, env=git_env)
    subprocess.run(["git", "-C", str(fake_repo), "commit", "-q", "-m", "ahead"], check=True, env=git_env)
    code, ps = run("shutdown /s /t 60")
    check("ahead runtime commit -> exit 5", (code, ps == ""), (5, True))
    subprocess.run(["git", "-C", str(fake_repo), "reset", "--hard", "-q", "relay-20261124000000"],
                   check=True, env=git_env)
    print("\n[wingui launch blocked executable & winrun --py AST detector]")
    wg_env = dict(os.environ, ARK_HOST="127.0.0.1", ARK_ACTION_LOG="/dev/null")
    wg_env.pop("ARK_SHUTDOWN_OVERRIDE", None)
    r_wg = subprocess.run(["bash", str(wingui), "launch", r"C:\Windows\System32\shutdown.exe -- /s /t 0"],
                          capture_output=True, text=True, env=wg_env, timeout=20)
    check("wingui launch shutdown.exe -> exit 5", r_wg.returncode, 5)
    py_bad = tmp / "bad_shut.py"
    py_bad.write_text('import subprocess\ncmd = ["shut" + "down", "/s", "/t", "0"]\nsubprocess.run(cmd)\n',
                      encoding="utf-8")
    wr_env = dict(os.environ, ARK_HOST="127.0.0.1", ARK_LEDGER=str(blk_ledger),
                  ARK_PENDING_DEPLOY=str(empty_pending), ARK_SHUTDOWN_GUARD_REPO=str(fake_repo),
                  ARK_ACTION_LOG="/dev/null", WINRUN_DRY_RUN="1")
    wr_env.pop("ARK_SHUTDOWN_OVERRIDE", None)
    r_wr = subprocess.run(["bash", str(winrun), "--py", str(py_bad)], capture_output=True, text=True,
                          env=wr_env, timeout=20)
    check("winrun --py AST shutdown + blocker -> exit 5", r_wr.returncode, 5)
    print("\n[never in the way]")
    code, ps = run("shutdown /a")
    check("abort not checked", (code, "WINPS_REFUSED" in ps), (0, False))
    check("an ordinary script not checked", "WINPS_REFUSED" in run("Get-Date")[1], False)
    code, ps = run("shutdown /s /t 60", busy="MAA", override="他 11-16 说现在关")
    check("his own words override", (code, "WINPS_REFUSED" in ps), (0, False))
    check("the names checked are the relay's game processes",
          sorted(re.search(r"BUSY_NAMES='([^']+)'", winps.read_text(encoding="utf-8")).group(1).split(",")),
          sorted(["MAA", "MaaEnd", "Endfield", "ok-ww", "Client-Win64-Shipping", "dnplayer"]))


def _part_estop_layout():
    import os
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = Path(os.environ["ESTOP_SH"]) if os.environ.get("ESTOP_SH") else stage_mac_script(ROOT, "estop.sh")


    FAKE_SSH = r'''#!PYTHON
import base64, os, sys
cmd = sys.argv[-1]
log = os.environ["FAKE_LOG"]
if cmd.startswith("pwsh ") and "-EncodedCommand" in cmd:
    body = base64.b64decode(cmd.split()[-1]).decode("utf-16-le")
    kind = "PS"
else:
    body = cmd
    kind = "RAW"
with open(log, "a", encoding="utf-8") as f:
    f.write(f"=== {kind}\n{body}\n")
out = ""
if kind == "PS":
    if "'LAYOUT=pkg'" in body:
        ans = os.environ["FAKE_LAYOUT"]
        if ans == "timeout":
            sys.stderr.write("ssh: connect to host 127.0.0.1 port 22: Operation timed out\n")
            sys.exit(255)
        out = {"pkg": "LAYOUT=pkg", "legacy": "LAYOUT=legacy",
               "garbage": "pwsh : The term 'pwsh' is not recognized"}[ans]
    elif "sc.exe stop ArkRelayWatchdog" in body:
        fail_lock = os.environ.get("FAKE_LOCK_FAIL", "")
        wd_start = "Automatic" if fail_lock == "wd" else "Disabled"
        main_task = "Ready" if fail_lock == "main" else "Disabled"
        mas_task = "Ready" if fail_lock == "mas" else "Disabled"
        out = (f"WATCHDOG=Stopped\r\nWATCHDOG_START={wd_start}\r\nSTOP_RC=0\r\n"
               f"MAIN_TASK={main_task}\r\nMAIN=STOPPED\r\nMAS_TASK={mas_task}")
    elif "sc.exe start ArkRelayWatchdog" in body:
        out = "MAS_TASK=Ready\r\nWATCHDOG=Running\r\nWATCHDOG_START=Automatic\r\nMAIN_TASK=Ready\r\nMAIN=RUNNING"
    elif "Write-Output 'NONE'" in body:          # a kill tier
        out = "NONE\r\nGONE"
else:
    if cmd == "sc query ark-relay":
        started = "sc start ark-relay" in open(log, encoding="utf-8").read()
        out = "        STATE              : " + ("4  RUNNING" if started else "1  STOPPED")
if out:
    print(out)
'''


    def rig(d: Path) -> dict:
        b = d / "bin"
        b.mkdir()
        ssh = b / "ssh"
        ssh.write_text(FAKE_SSH.replace("PYTHON", f"{sys.executable} -S", 1), encoding="utf-8")
        ssh.chmod(0o755)
        curl = b / "curl"
        curl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        curl.chmod(0o755)
        return {**os.environ, "PATH": f"{b}:{os.environ['PATH']}", "ARK_HOST": "127.0.0.1",
                "ARK_ACTION_LOG": os.devnull}


    def run(d: Path, env: dict, layout: str, *args: str, extra_env: dict | None = None) -> tuple[int, str, list[tuple[str, str]]]:
        """(rc, output, [(kind, command)] the script sent over ssh, in order)."""
        log = d / f"ssh-{layout}-{'-'.join(a.strip('-') for a in args)}.log"
        log.unlink(missing_ok=True)
        r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, timeout=90,
                           env={**env, "FAKE_LOG": str(log), "FAKE_LAYOUT": layout, **(extra_env or {})})
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        sent = []
        if log.exists():
            for chunk in log.read_text(encoding="utf-8").split("=== ")[1:]:
                kind, _, body = chunk.partition("\n")
                sent.append((kind, body.strip()))
        return r.returncode, out, sent


    def pkg_stop(sent):
        return [i for i, (k, b) in enumerate(sent) if k == "PS" and "sc.exe stop ArkRelayWatchdog" in b]


    def pkg_start(sent):
        return [i for i, (k, b) in enumerate(sent) if k == "PS" and "sc.exe start ArkRelayWatchdog" in b]


    def raw(sent, cmd):
        return [i for i, (k, b) in enumerate(sent) if k == "RAW" and b == cmd]


    def first_kill(sent):
        """Index of the first kill tier (mk_kill_tier; PS_PKG_STOP has a Stop-Process of its own)."""
        return next((i for i, (k, b) in enumerate(sent) if k == "PS" and "Write-Output 'NONE'" in b), None)


    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        env = rig(d)

        for layout, why in (("timeout", "the layout question timed out"),
                            ("garbage", "the layout question came back without a LAYOUT line")):
            print(f"\n[{why}: stop the installed relay (watchdog, then the task), before AUTO-MAS is killed]")
            rc, out, sent = run(d, env, layout, "--keep-queue")
            check("stop exits 0", rc, 0)
            stops = pkg_stop(sent)
            check("installed-relay stop was sent", len(stops), 1)
            kill = first_kill(sent)
            check("it went before the first kill", bool(stops) and kill is not None and stops[0] < kill, True)
            check("no bare sc stop ark-relay", raw(sent, "sc stop ark-relay"), [])
            check("says the layout was not known", "没问到机器上是哪种中继" in out, True)
            check("says it stopped the installed one", "按安装版停" in out, True)
            check("does not say it stops the old service", "按老服务停" in out, False)
            check("reports the relay stopped", "[中继] 已确认停止" in out, True)

            print(f"\n[{why}, --restore: start the installed relay, not the old service]")
            rc, out, sent = run(d, env, layout, "--restore")
            check("installed-relay start was sent", len(pkg_start(sent)), 1)
            check("no sc start ark-relay", raw(sent, "sc start ark-relay"), [])
            check("reports the relay running", "中继（安装版）已在运行" in out, True)

        print("\n[installed layout: cross-reboot hardlock on stop & full restore]")
        rc, out, sent = run(d, env, "pkg", "--keep-queue")
        check("pkg stop exits 0", rc, 0)
        stops = pkg_stop(sent)
        check("installed-relay stop was sent", len(stops), 1)
        stop_ps = sent[stops[0]][1]
        check("stop disables ArkRelayWatchdog StartType",
              "Set-Service -Name ArkRelayWatchdog -StartupType Disabled" in stop_ps, True)
        check("stop disables \\ArkRelay\\main scheduled task",
              "Disable-ScheduledTask -TaskPath '\\ArkRelay\\' -TaskName 'main'" in stop_ps, True)
        check("stop disables AUTO-MAS_AutoStart scheduled task",
              "Disable-ScheduledTask -TaskName 'AUTO-MAS_AutoStart'" in stop_ps, True)
        check("stop writes watchdog-stopped.txt estop marker",
              "watchdog-stopped.txt" in stop_ps and "'estop '" in stop_ps, True)
        check("PS_PKG layout check preserves LAYOUT=pkg when estop disabled both service and task",
              "$estopLocked" in sent[0][1] and "($task -or $wd) -and ($estopLocked -or -not $legacyOn)" in sent[0][1],
              True)
        check("no bare sc stop ark-relay", raw(sent, "sc stop ark-relay"), [])
        check("no unknown-layout warning", "没问到机器上是哪种中继" in out, False)

        # Partial cross-reboot lock failure must exit non-zero and never silently succeed
        for which in ("wd", "main", "mas"):
            rc_f, out_f, _ = run(d, env, "pkg", "--keep-queue", extra_env={"FAKE_LOCK_FAIL": which})
            check(f"lock failure ({which}) exits non-zero", rc_f != 0, True)
            check(f"lock failure ({which}) reports incomplete lock", "跨重启硬锁未完全生效" in out_f, True)

        rc, out, sent = run(d, env, "pkg", "--restore")
        starts = pkg_start(sent)
        check("--restore starts the installed relay", len(starts), 1)
        start_ps = sent[starts[0]][1]
        check("--restore removes estop marker",
              "Remove-Item -Path 'C:\\ProgramData\\ark-relay\\watchdog-stopped.txt'" in start_ps, True)
        check("--restore sets ArkRelayWatchdog Automatic BEFORE sc.exe start",
              (0 <= start_ps.find("Set-Service -Name ArkRelayWatchdog -StartupType Automatic")
               < start_ps.find("sc.exe start ArkRelayWatchdog")), True)
        check("--restore re-enables \\ArkRelay\\main BEFORE schtasks /run",
              (0 <= start_ps.find("Enable-ScheduledTask -TaskPath '\\ArkRelay\\' -TaskName 'main'")
               < start_ps.find("schtasks.exe /run /tn '\\ArkRelay\\main'")), True)
        check("--restore re-enables AUTO-MAS_AutoStart inside PS_PKG_START before bash runs it",
              "Enable-ScheduledTask -TaskName 'AUTO-MAS_AutoStart'" in start_ps, True)
        check("--restore does not start the old service", raw(sent, "sc start ark-relay"), [])

        print("\n[the machine says legacy: the old service, and only it]")
        rc, out, sent = run(d, env, "legacy", "--keep-queue")
        check("legacy stop exits 0", rc, 0)
        check("legacy stop disables ark-relay autostart",
              len(raw(sent, "sc config ark-relay start= disabled")), 1)
        check("sc stop ark-relay was sent", len(raw(sent, "sc stop ark-relay")), 1)
        check("legacy stop disables AUTO-MAS_AutoStart",
              len(raw(sent, "schtasks /change /tn AUTO-MAS_AutoStart /disable")), 1)
        check("no installed-relay stop", pkg_stop(sent), [])
        check("reports the old service stopped", "[中继] 已确认停止" in out, True)
        rc, out, sent = run(d, env, "legacy", "--restore")
        check("legacy restore re-enables ark-relay before start",
              (raw(sent, "sc config ark-relay start= auto")[0] < raw(sent, "sc start ark-relay")[0]), True)
        check("legacy restore re-enables AUTO-MAS_AutoStart before run",
              (raw(sent, "schtasks /change /tn AUTO-MAS_AutoStart /enable")[0]
               < raw(sent, "schtasks /run /tn AUTO-MAS_AutoStart")[0]), True)
        check("--restore sends sc start ark-relay", len(raw(sent, "sc start ark-relay")), 1)
        check("--restore does not start the installed relay", pkg_start(sent), [])
        check("--restore reports ark-relay running", "ark-relay 已在运行" in out, True)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_mac_one_at_a_time_main():
    """Nothing we run on the Mac starts programs in bulk while macOS runs it at background priority.
    """
    import os
    import re
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]


    # Pools whose workers are forked copies that never exec (no new program is started), and pools whose
    # tasks start no program at all (the file starts programs elsewhere, one at a time). Each entry is
    # the text that shows it; the check fails if that text goes away.
    FORK_ONLY: dict[str, str] = {}

    # 1. shell: every xargs -P <n> above 1 under scripts/mac/ runs a function that waits first
    FUNC = re.compile(r"^(\w+)\(\) \{\n(.*?)^\}", re.S | re.M)
    bad_sh = []
    for p in sorted((ROOT / "scripts/mac").rglob("*.sh")):
        text = p.read_text(errors="replace").replace("\r\n", "\n")
        funcs = {m.group(1): m.group(2) for m in FUNC.finditer(text)}
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for m in re.finditer(r"xargs\b[^|;&]*?-P\s*(\d+)[^|;&]*?bash -c '(\w+)", line):
                body = funcs.get(m.group(2), "")
                first = next((ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith(("local ", "#"))), "")
                if int(m.group(1)) > 1 and first != "wait_not_background":
                    bad_sh.append(f"{p.relative_to(ROOT)}:{i} ({m.group(2)})")
            if re.search(r"xargs\b[^|;&]*?-P\s*([2-9]|\d\d)", line) and "bash -c '" not in line:
                bad_sh.append(f"{p.relative_to(ROOT)}:{i} (not a waiting function)")
    check("every `xargs -P <n>` above 1 in scripts/mac starts a function that waits first", bad_sh, [])

    # 2. deploy-relay.sh: the wait is inside the test timing block CI sources, and is exported
    dep = (ROOT / "scripts/mac/deploy-relay.sh").read_text().replace("\r\n", "\n")
    block = re.search(r"^# >>> test timing$(.*?)^# <<< test timing$", dep, re.S | re.M).group(1)
    check("wait_not_background is defined in the block CI sources",
          bool(re.search(r"^wait_not_background\(\) \{", block, re.M)) and "export -f wait_not_background" in block, True)

    # 3. python: pools in files that start programs wait before each start
    POOL = re.compile(r"(ThreadPoolExecutor|ProcessPoolExecutor)\(")
    STARTS = re.compile(r"subprocess\.|os\.system\(|Popen\(")
    bad_py = []
    files = [*sorted((ROOT / "scripts/mac").rglob("*.py")), *sorted((ROOT / "relay/tests").glob("test_*.py"))]
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if p.name == Path(__file__).name:
            continue
        text = p.read_text(errors="replace").replace("\r\n", "\n")
        if not POOL.search(text):
            continue
        if rel in FORK_ONLY:
            check(f"{rel} still forks without exec", FORK_ONLY[rel] in text, True)
            continue
        # test_replay.py's judges are spawned Python processes: a spawn is an exec.
        starts = STARTS.search(text) or "ProcessPoolExecutor(" in text
        if starts and not ("os.getpriority(PRIO_DARWIN_PROCESS, 0)" in text and text.count("_wait_not_background()") >= 1):
            bad_py.append(rel)
    check("pools that start programs wait while at background priority", bad_py, [])

    bare = [p.relative_to(ROOT).as_posix() for p in files if p.name != Path(__file__).name
            and "os.PRIO_DARWIN_PROCESS" in p.read_text(errors="replace").replace('getattr(os, "PRIO_DARWIN_PROCESS"', "")]
    check("no bare os.PRIO_DARWIN_PROCESS (missing before Python 3.12)", bare, [])
    sys_py = Path("/usr/bin/python3")
    if sys.platform == "darwin" and sys_py.exists():
        import ast
        for p in files:
            if p.name == Path(__file__).name:
                continue
            text = p.read_text(errors="replace")
            if "def _wait_not_background()" not in text:
                continue
            tree = ast.parse(text)
            parts = [ast.get_source_segment(text, n) for n in tree.body
                     if (isinstance(n, ast.FunctionDef) and n.name == "_wait_not_background")
                     or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "PRIO_DARWIN_PROCESS" for t in n.targets))]
            prog = ("import os, sys\nclass _T:\n    @staticmethod\n    def sleep(s): sys.exit(0)\ntime = _T()\n"
                    + "\n".join(parts) + "\n_wait_not_background()\n")
            r = subprocess.run([str(sys_py), "-c", prog], capture_output=True, text=True, timeout=30)
            check(f"{p.relative_to(ROOT).as_posix()} _wait_not_background runs under {sys_py}",
                  (r.returncode, r.stderr.strip().splitlines()[-1:] if r.returncode else []), (0, []))

    # 3b. live, without starting any program: what the Python waits key on. This process puts itself at
    #     background priority, reads it back, and puts itself back.
    if sys.platform == "darwin":
        before = os.getpriority(os.PRIO_DARWIN_PROCESS, 0)
        os.setpriority(os.PRIO_DARWIN_PROCESS, 0, os.PRIO_DARWIN_BG)
        during = os.getpriority(os.PRIO_DARWIN_PROCESS, 0)
        os.setpriority(os.PRIO_DARWIN_PROCESS, 0, 0)
        after = os.getpriority(os.PRIO_DARWIN_PROCESS, 0)
        check("getpriority(PRIO_DARWIN_PROCESS) reads 0 / 1 / 0 around background priority", (before, during, after), (0, 1, 0))

    # 4. wait_not_background: waits while ps shows priority 4 (background), returns when it rises,
    #    returns at once when not background or not macOS. Driven with a fake ps / uname on PATH.

    def run_wait(src, pri_seq, uname="Darwin"):
        with tempfile.TemporaryDirectory() as d:
            state = os.path.join(d, "n")
            open(state, "w").write("0")
            seq = " ".join(str(x) for x in pri_seq)
            with open(os.path.join(d, "ps"), "w") as fh:
                fh.write(f"""#!/bin/bash
n=$(cat {state}); set -- {seq}; shift $n 2>/dev/null; echo "${{1:-31}}"; echo $((n+1)) > {state}
""")
            with open(os.path.join(d, "uname"), "w") as fh:
                fh.write(f"#!/bin/bash\necho {uname}\n")
            for x in ("ps", "uname"):
                os.chmod(os.path.join(d, x), 0o755)
            env = {**os.environ, "PATH": d + ":" + os.environ["PATH"], "WAIT_BG_POLL_S": "0"}
            r = subprocess.run(["bash", "-c", src + "\nwait_not_background; echo done"], capture_output=True,
                               text=True, env=env, timeout=20)
            calls = int(open(state).read())
            return r.stdout.strip(), ("waiting" in r.stderr), calls


    # The wait only matters on the Mac, and the fake ps / uname need a POSIX shell; on a CI runner
    # (Windows / Linux) the text checks above still run, this section does not.
    lib = (ROOT / "scripts/mac/lib/wait-not-background.sh").read_text().replace("\r\n", "\n")
    fn = re.search(r"^wait_not_background\(\) \{.*?^\}", dep, re.S | re.M).group(0)
    for label, src in ((("lib", lib), ("deploy block", fn)) if sys.platform == "darwin" else ()):
        check(f"{label}: background (4, 4, 31) waits, says so once, then returns", run_wait(src, [4, 4, 31]), ("done", True, 3))
        check(f"{label}: foreground (31) returns at once, silent", run_wait(src, [31]), ("done", False, 1))
        check(f"{label}: not macOS returns without asking ps", run_wait(src, [4], uname="Linux"), ("done", False, 0))
    lint = (ROOT / "scripts/mac/lint-repo.sh").read_text().replace("\r\n", "\n")
    check("lint-repo.sh lint_one_test waits first",
          bool(re.search(r"lint_one_test\(\) \{\n\s+local name out\n\s+wait_not_background\n", lint)), True)
    check("deploy-relay.sh run_one_test waits first",
          bool(re.search(r"run_one_test\(\) \{\n[^\n]*\n\s+wait_not_background\n", dep)), True)

    # 5. launchd jobs we install run at Standard, not Background (darwin background priority).
    for p in sorted((ROOT / "scripts/mac/launchd").glob("*.plist")):
        t = p.read_text().replace("\r\n", "\n")
        m = re.search(r"<key>ProcessType</key>\s*<string>(\w+)</string>", t)
        check(f"{p.name} is not a Background job", (m.group(1) if m else "unset") != "Background", True)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_ff_toplevel():
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]


    with tempfile.TemporaryDirectory() as t:
        base = Path(t)
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
        (wt / "a.txt").write_text("2\n")
        git("commit", "-qam", "two", cwd=wt)
        git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=wt)
        ff = str(ROOT / "scripts/mac/lib/ff-toplevel.sh")
        (top / "a.txt").write_text("dirty\n")
        r = subprocess.run([ff, str(wt)], capture_output=True, text=True)
        check("dirty top-level left alone, exit 0",
              (r.returncode, "uncommitted changes" in r.stdout, (top / "a.txt").read_text()),
              (0, True, "dirty\n"))
        git("checkout", "-q", "--", "a.txt", cwd=top)
        git("checkout", "-q", "-b", "side", cwd=top)
        r = subprocess.run([ff, str(wt)], capture_output=True, text=True)
        check("top-level on another branch left alone",
              (r.returncode, "not main" in r.stdout, git("rev-parse", "--abbrev-ref", "HEAD", cwd=top).strip()),
              (0, True, "side"))
        git("checkout", "-q", "main", cwd=top)
        r = subprocess.run([ff, str(wt)], capture_output=True, text=True)
        check("clean top-level on main fast-forwarded",
              (r.returncode, "fast-forwarded 1 commits" in r.stdout, (top / "a.txt").read_text()),
              (0, True, "2\n"))

    dr = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
    check("deploy fast-forwards the top-level checkout after the push, and ignores its exit",
          ('lib/ff-toplevel.sh" "$HERE/.." || true' in dr,
           dr.find("push -q origin HEAD:refs/heads/main") < dr.find("ff-toplevel.sh")),
          (True, True))

    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    sys.exit(run_parts([_part_techlog_tool, _part_build_notes_at_deploy_tip, _part_dead_helpers_gone, _part_diag_pull_silent, _part_release_notes, _part_replay_gate, _part_tools_import_installed_relay, _part_unmerged_fixes, _part_winps_shutdown_guard, _part_estop_layout, _part_mac_one_at_a_time_main, _part_ff_toplevel]))
