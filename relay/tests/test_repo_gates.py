"""The repository's own gates and tools: build notes at the deploy tip, dead helpers gone, a silent diag pull, release notes, the replay gate, tools importing the installed relay, unmerged fixes.

One part per former file, each run on its own (tests/_parts.py): test_build_notes_at_deploy_tip.py, test_dead_helpers_gone.py, test_diag_pull_silent.py, test_release_notes.py, test_replay_gate.py, test_tools_import_installed_relay.py, test_unmerged_fixes.py.
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


def _part_build_notes_at_deploy_tip():
    """packaging/build.py builds at a deploy commit, whose RELEASE-NOTES.md is emptied.

2026-10-13 (audit of the install / switch-over block, item 3): deploy-relay.sh builds the
manifest with the notes filled in, then empties relay/RELEASE-NOTES.md and commits both
in the commit it tags with the manifest's `ref`. build.py compared every listed file with
the tree, so at each deploy tip (7ce92679, d6fb8004, 45584225) it stopped with "hash
differs: RELEASE-NOTES.md". Now the notes come from the first of the tree, `<ref>^` and
`<ref>` whose hashes match the manifest. Run on a throwaway git repo shaped like that.

    Formerly test_build_notes_at_deploy_tip.py.
    """
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
    """Helpers nothing called are gone and stay gone (review 2026-10-13, s5 #10).

* Notifier.send_image / WeCom.send_image / WeCom._upload: the self-built app is in
  no automatic order (push.py --private sends text only); group images go through
  Notifier.send_group_image.
* notify._hint: advice for the self-built app's errcode 60020 inside the outage
  notice; that app is never in an automatic order, so it could never fire.
* techlog.red_items: numbered from 1 on every call (duplicate ids); add_red is the
  one writer.
* Desktop.click(x, y) was here too; it came back on 2026-10-15 with a caller: the
  launcher's 「确认」 button that no OCR pass reads (gameupdate_games._confirm_space).

Checked two ways: the names are not defined, and no relay or scripts source calls them.

    Formerly test_dead_helpers_gone.py.
    """
    import re

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.core import desktop, notify, techlog


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
    """diag-pull.py must not exit 0 when a record could not be fetched.

Silent-failure audit row scripts/mac/diag-pull.py:54: a per-object GET that
failed was printed to stderr, then the summary said 「新取回 N 条」 and the tool
exited 0, so a session that checks only the exit code believed every record
was on disk. The bucket deletes records after 7 days, so a missed one is lost.

    Formerly test_diag_pull_silent.py.
    """
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
    """更新播报要说「修好了什么毛病」，不是列一串文件名。

2026-08-26 用户看到的播报是「改动文件：service.py、preupdate.py……」，
对着不看代码的人等于什么都没说。原话：「**更新内容用人话写**」。

所以 `relay/RELEASE-NOTES.md` 跟代码一起部署，播报优先念它；
没有这个文件时才退回列文件名（老行为，不能退化）。

这里测的是「说明文件在不在决定播报内容」，以及那份说明本身够不够人话——
后者用一条粗但有效的判据：**不许出现代码符号**。

    Formerly test_release_notes.py.
    """
    import re
    import tempfile

    HERE = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(HERE))

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


    def render(notes_dir: Path, files: list[str]) -> str:
        """service.py 里组装播报正文的那几行，原样复刻。

    复刻而不是 import：那段逻辑埋在服务主循环里，拆出来单测要动生产代码，
    而这里真正要钉住的是「有说明文件就念说明、没有就列文件名」这个取舍。
    """
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
        """随仓库的那份说明本身要是人话。

    判据故意粗：**不许出现代码符号**（下划线函数名、括号调用、驼峰、路径后缀）。
    这拦不住所有术语，但拦得住「修复 `maa_update_pending()` 未识别 MirrorChyan
    zip 制品」这种——而那正是当天被点名的写法。
    """
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
        print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        with tempfile.TemporaryDirectory() as t:
            raise SystemExit(main(Path(t)))


def _part_replay_gate():
    """Deploy gate E1: the offline replay of outcome / errwatch over the real 2026-10-06 logs.

Before a deploy, ``scripts/mac/deploy-relay.sh`` runs ``ark_relay.features.selfcheck.replay`` over
the two checked-in fixtures - the OK-WW weekly-boss run whose update note once
matched 「结晶波片不足」, and the relay.log fragment holding the banner calendar
#2 and shutdown snapshot false alarms. This test pins what the replay must see:
the current code pushes nothing, the code with one of the fixes undone pushes that
false alarm again (the producers run under the real errwatch handler), and a
genuine ERROR still pushes.

    Formerly test_replay_gate.py.
    """
    import importlib.util

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.features.verify import outcome
    from ark_relay.features.selfcheck import replay

    FIX = Path(__file__).resolve().parent / "fixtures"
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

    # The producers run again under the real errwatch handler, so breaking one of the
    # fixes brings its false alarm back into the replay (until 2026-10-13 the quiet lines
    # were a hand list of wordings and every one of these still passed).
    from ark_relay.features.banners import banners as _hub
    from ark_relay.features.weekly import annihilation as _ann

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
          [type(h).__name__ for h in __import__("logging").getLogger(__import__("ark_relay.features.alarm.errwatch", fromlist=["ARK"]).ARK).handlers], [])

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
    # 2026-10-11: deploy-relay.sh still ran `-m ark_relay.replay`, an old name served by
    # _aliases; runpy needs the loader's get_code, which the alias loader lacks, so the
    # gate died with a traceback and the deploy was refused.
    import re as _re
    _deploy = (Path(__file__).resolve().parents[2] / "scripts" / "mac" / "deploy-relay.sh").read_text(encoding="utf-8")
    for _mod in _re.findall(r"python3 -m (ark_relay[\w.]*)", _deploy):
        _spec = importlib.util.find_spec(_mod)
        check(f"{_mod} has a loader runpy can use", bool(_spec and hasattr(_spec.loader, "get_code")), True)


def _part_tools_import_installed_relay():
    """Tools that import ark_relay on the gaming machine import the installed relay's code.

Since the switch-over (packaging/switch.py install) the relay runs
C:\\Program Files\\ArkRelay\\versions\\<current.txt>\\ (relay/pkg_layout.py), and
C:\\ProgramData\\ark-relay holds only its data. The ark_relay folder still lying there is
the old relay's, frozen at the switch-over. Until 2026-10-11 healthcheck.py,
okww_effective.py, config-check.py, okww-landed.py, maaend_only_task.py,
waittime_roundtrip.py, boot_check_remote.py, the desktop switch skip-shutdown.bat and the
commands in docs/OPERATIONS.md all put that folder on sys.path: every check judged the
machine by the old code, and healthcheck.py's ensure_patches wrote the old OK-WW patches
over newer fixes. They now take the folder from scripts/mac/lib/relay_code.py (the .bat,
which sits alone on his desktop, reads current.txt itself).

Checked here:
  1. nothing under scripts/ or docs/ puts C:\\ProgramData\\ark-relay itself (literally, or
     through a name or %VAR% bound to it in the same file) on sys.path, or reads a file
     under C:\\ProgramData\\ark-relay\\ark_relay - except the listed files that are about
     the old relay on purpose;
  2. each of those tools imports relay_code on a line winrun.sh's module shipping sees;
  3. relay_code.code_root() picks versions\\<current.txt>, and the old folder (saying so)
     only when there is no installed relay;
  4. skip-shutdown.bat reads current.txt, has CRLF line endings, and does not start a
     for /f command with a quote (cmd /c then drops the first and last quote and the
     Python path no longer parses: its menu read 「读不出来」 every time, seen on the machine
     2026-10-11; with LF line endings cmd.exe ran fragments of its lines as commands).

    Formerly test_tools_import_installed_relay.py.
    """
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

    # The scan has to recognise each shape the tools used before 2026-10-11.
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
        "scripts/mac/lib/waittime_roundtrip.py": "use_relay_code()",
        "scripts/mac/lib/boot_check_remote.py": "code_root()",
        "scripts/windows/okww-landed.py": "use_relay_code()",
        "scripts/mac/config-check.py": "use_relay_code()",   # inside PROBE, shipped as its own file
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
    """deploy-relay.sh step 0.6: a finished relay fix may not sit on a branch, unreviewed.

On 10-11 23 local branches held relay changes that never reached main (one was the
10-10 Endfield-hang fix a4be51cb). Checked here on a temporary git repo whose
origin/main is the baseline commit:
  - a branch commit touching relay/ that is not in main and not listed blocks (exit 1),
    and the output names its branch, hash and subject;
  - the same commit listed in the review file passes;
  - a docs-only commit on a branch is ignored, and so is one that touches only files
    that never reach the machine: relay/tests/ and relay/make-manifest.py (make-manifest.py
    ships relay/ark_relay/**/*.py|*.txt, relay/*.py and RELEASE-NOTES.md); a top-level
    relay/*.py commit still blocks (2026-10-13: the daysim test commits were counted);
  - a commit whose patch is already in main (cherry-picked: `git cherry` says "-") is
    ignored, and so is a commit on HEAD (the deploy pushes HEAD to main);
  - a malformed review line (unknown verdict) fails closed;
  - all of it under diff.noprefix / diff.mnemonicPrefix / diff.renames=false;
  - deploy-relay.sh runs the gate before the pre-deploy replay.

    Formerly test_unmerged_fixes.py.
    """
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
          0 < gate < deploy.find("ark_relay.features.selfcheck.replay"), True)
    check("a failed gate exits the deploy", "exit 1" in deploy[gate:gate + 600], True)

    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_winps_shutdown_guard():
    """winps.sh refuses to power the machine off while a game or automation process is up.

2026-11-16 10:4x a Claude session told the user it would shut the machine down after a deploy while the
morning shift was still running OK-WW / MaaEnd; the relay powers the machine off itself once the shift
is done (debug mode skips only that one shutdown). Gemini's fix: the entry point checks first. Here
`ssh` is a fake on PATH that decodes the PowerShell winps.sh would send and answers as the machine would.
    """
    import os
    import re
    import stat
    import subprocess

    root = Path(__file__).resolve().parents[2]
    winps = root / "scripts" / "mac" / "winps.sh"
    tmp = tmpdir()
    sent = tmp / "sent.ps1"
    fake = tmp / "ssh"
    fake.write_text("""#!/usr/bin/env python3
import base64, os, re, sys
here = os.path.dirname(os.path.abspath(__file__))
cmd = sys.argv[-1]
ps = base64.b64decode(re.search(r"-EncodedCommand (\\S+)", cmd).group(1)).decode("utf-16-le")
open(os.path.join(here, "sent.ps1"), "w", encoding="utf-8").write(ps)
busy = open(os.path.join(here, "busy.txt"), encoding="utf-8").read().strip()
out = ("WINPS_REFUSED: " + busy) if busy and "WINPS_REFUSED" in ps else "ran"
print("WINPS_B64=" + base64.b64encode(out.encode()).decode())
""", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    def run(script, busy="", override=""):
        (tmp / "busy.txt").write_text(busy, encoding="utf-8")
        env = dict(os.environ, PATH=f"{tmp}:{os.environ['PATH']}", ARK_HOST="127.0.0.1")
        env.pop("ARK_SHUTDOWN_OVERRIDE", None)
        if override:
            env["ARK_SHUTDOWN_OVERRIDE"] = override
        p = subprocess.run(["bash", str(winps), script], capture_output=True, text=True, env=env, timeout=30)
        return p.returncode, sent.read_text(encoding="utf-8") if sent.exists() else ""

    print("[a shutdown while OK-WW runs: refused, exit 5]")
    code, ps = run("shutdown /s /t 60", busy="Client-Win64-Shipping")
    check("exit 5", code, 5)
    check("the check went first", ps.index("WINPS_REFUSED") < ps.index("shutdown /s /t 60"), True)
    for script in ("Stop-Computer -Force", "Restart-Computer", "shutdown.exe -r -t 0"):
        check(f"{script}: checked too", "WINPS_REFUSED" in run(script, busy="MAA")[1], True)
    print("\n[nothing running: the shutdown goes through]")
    check("exit 0", run("shutdown /s /t 60")[0], 0)
    print("\n[never in the way]")
    code, ps = run("shutdown /a")
    check("abort not checked", (code, "WINPS_REFUSED" in ps), (0, False))
    check("an ordinary script not checked", "WINPS_REFUSED" in run("Get-Date")[1], False)
    code, ps = run("shutdown /s /t 60", busy="MAA", override="他 11-16 说现在关")
    check("his own words override", (code, "WINPS_REFUSED" in ps), (0, False))
    check("the names checked are the relay's game processes",
          sorted(re.search(r"BUSY_NAMES='([^']+)'", winps.read_text(encoding="utf-8")).group(1).split(",")),
          sorted(["MAA", "MaaEnd", "Endfield", "ok-ww", "Client-Win64-Shipping", "dnplayer"]))


if __name__ == "__main__":
    sys.exit(run_parts([_part_build_notes_at_deploy_tip, _part_dead_helpers_gone, _part_diag_pull_silent, _part_release_notes, _part_replay_gate, _part_tools_import_installed_relay, _part_unmerged_fixes, _part_winps_shutdown_guard]))
