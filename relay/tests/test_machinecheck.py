"""The machine check; and its wait.

One part per former file, each run on its own (tests/_parts.py): test_machinecheck.py, test_machinecheck_wait.py.
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


def _part_main():
    """Machine checks: the machine confirms deployed changes by itself (machinecheck.py).

The user, 2026-10-06 04:59: the machine must check the open ledger items by itself
after a deploy, instead of a person reading logs. Every FAIL goes to the group,
every time it is judged; PASS and still-waiting go to the daily report only.

    Formerly test_machinecheck.py.
    """
    import logging
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.selfcheck import machinecheck as mc
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.notify import route_of


    class N:
        def __init__(self):
            self.sent = []

        def send(self, title, body, alert=False, **kw):
            self.sent.append((title, body, alert))
            return []


    mc.load()
    real = dict(mc.CHECKS), dict(mc.CANNOT)
    mc.CHECKS.clear()
    mc.CANNOT.clear()
    try:
        seen = {}

        @mc.check("#901", "样例：跑完看日志里有没有那一行", "A", "run")
        def _a(ctx):
            line = ctx.get("line")
            if line is None:
                return None
            return mc.Result(mc.PASS if "已领到" in line else mc.FAIL, line)

        @mc.check("#902", "样例：等手机指令", "B", "phone_cmd")
        def _b(ctx):
            seen["ctx"] = ctx
            return mc.Result(mc.PASS, f"回执：{ctx.get('msg')}")

        @mc.check("#903", "样例：自己会出错的核对", "A", "run")
        def _c(ctx):
            raise RuntimeError("boom")

        mc.cannot("#904", "样例：核不了的", "要人在电脑上跑一个工具")
        d = tmpdir()
        now = datetime(2026, 10, 6, 21, 40, tzinfo=SERVER_TZ)
        n = N()
        print("[没被触发：什么都不记]")
        check("run 事件但没给那一行：#901 不判", [c for c, _ in mc.judge(d, "run", {}, notifier=n, now=now)], [])
        check("没推", n.sent, [])
        print("[过了：只记，不推]")
        got = mc.judge(d, "run", {"line": "周本领奖：已领到"}, version="v1", notifier=n, now=now)
        check("判了 #901 过了", [(c, r.status) for c, r in got], [("#901", mc.PASS)])
        check("过了不推", n.sent, [])
        check("记进状态：结论、依据、版本", {k: mc.read(d)["#901"][k] for k in ("status", "evidence", "version")},
              {"status": "PASS", "evidence": "周本领奖：已领到", "version": "v1"})
        print("[没过：每次都推，进群]")
        mc.judge(d, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n, now=now)
        mc.judge(d, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n, now=now)
        check("没过两次，推两次", len(n.sent), 2)
        check("都带 alert=True", [a for _, _, a in n.sent], [True, True])
        check("标题走群", route_of(n.sent[0][0], alert=True) if n.sent else None, "group")
        check("正文带依据", "没认出领奖弹窗" in n.sent[0][1] if n.sent else False, True)
        check("记了没过的次数", mc.read(d)["#901"]["fails"], 2)
        print("[核对自己出错：记 ERROR（会进群），不当成过了]")
        errs = []
        h = type("H", (logging.Handler,), {"emit": lambda self, r: errs.append(r.levelno)})()
        mc.log.addHandler(h)
        mc.judge(d, "run", {"line": "x"}, notifier=n, now=now)
        mc.log.removeHandler(h)
        check("有一条 ERROR", logging.ERROR in errs, True)
        check("#903 没有结论", "#903" in mc.read(d), False)
        print("[B 类：触发时拿到事件内容]")
        mc.judge(d, "phone_cmd", {"action": "skip_today", "msg": "调度程序已确认"}, notifier=n, now=now)
        check("看到了指令", (seen["ctx"]["action"], seen["ctx"]["event"]), ("skip_today", "phone_cmd"))
        print("[日报一段]")
        sec = mc.daily_section(d)
        check("有标题", sec.startswith("上机核对"), True)
        check("没过的打 ❌", "❌ #901" in sec, True)
        check("过了的打 ✅", "✅ #902" in sec, True)
        check("没判的写在等", "⏳ #903" in sec, True)
        check("核不了的写明原因", "✋ #904 样例：核不了的：机器核不了，要人在电脑上跑一个工具" in sec, True)
        print("[登记写错就拒绝]")
        for label, args in (("类别只能 A/B", ("#905", "x", "C", "run")), ("事件要认识", ("#906", "x", "A", "nope")),
                            ("至少一个事件", ("#907", "x", "A"))):
            try:
                mc.check(*args)(lambda c: None)
                check(label, "registered", "refused")
            except ValueError:
                check(label, "refused", "refused")
        try:
            mc.judge(d, "nope", {})
            check("不认识的事件拒绝", "judged", "refused")
        except ValueError:
            check("不认识的事件拒绝", "refused", "refused")
        print("[state file exists but cannot be read: said once, not overwritten, FAILs still pushed]")
        d2 = tmpdir()
        sf = d2 / mc.STATE_FILE
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text("{corrupt", encoding="utf-8")
        getattr(mc, "_last_error", {}).clear()
        warned = []
        wh = type("W", (logging.Handler,), {"emit": lambda self, r: warned.append(r.levelno)})(level=logging.WARNING)
        mc.log.addHandler(wh)
        n2 = N()
        mc.judge(d2, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n2, now=now)
        check("one WARNING", warned.count(logging.WARNING), 1)
        check("the unreadable file is left as it was (no other check's history overwritten)",
              sf.read_text(encoding="utf-8"), "{corrupt")
        check("the FAIL is still pushed", len(n2.sent), 1)
        mc.judge(d2, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n2, now=now)
        check("same condition again -> no second WARNING", warned.count(logging.WARNING), 1)
        sf.write_text("{}", encoding="utf-8")
        mc.judge(d2, "run", {"line": "周本领奖：已领到"}, notifier=n2, now=now)
        check("readable again -> written, no WARNING", (mc.read(d2).get("#901", {}).get("status"),
                                                        warned.count(logging.WARNING)), ("PASS", 1))
        sf.write_text("{corrupt", encoding="utf-8")
        mc.judge(d2, "run", {"line": "周本领奖：已领到"}, notifier=n2, now=now)
        check("broken again after a good read -> WARNING again", warned.count(logging.WARNING), 2)
        d3 = tmpdir()
        mc.judge(d3, "run", {"line": "周本领奖：已领到"}, notifier=n2, now=now)
        check("no state file yet is not an error -> written, no WARNING",
              (mc.read(d3).get("#901", {}).get("status"), warned.count(logging.WARNING)), ("PASS", 2))
        mc.log.removeHandler(wh)
    finally:
        mc.CHECKS.clear()
        mc.CHECKS.update(real[0])
        mc.CANNOT.clear()
        mc.CANNOT.update(real[1])


def _part_machinecheck_wait():
    """E2 of the deploy: machinecheck_wait.py decides boot-judged-and-quiet / alarm / wait.

The gate reads the two files the relay keeps - state/machinecheck.json and
state/alerts/<day>.jsonl - and answers whether this deploy's version has had
its boot batch judged and whether the group was quiet since. These checks pin
the three verdicts on realistic rows, including the traps: an old version's row
must not count, a non-boot event is not the boot batch, and an alarm wins over
a judged boot.

    Formerly test_machinecheck_wait.py.
    """
    import contextlib
    import io
    import json
    import os

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT.parent / "scripts" / "windows"))
    from machinecheck_wait import alerts_with_version, boot_judged, main, read_rows, verdict


    def mc_row(**kw):
        base = {"status": "PASS", "evidence": "x", "at": "2026-10-06 06:20:00",
                "version": "", "event": "", "passes": 1}
        base.update(kw)
        return base


    def alert_row(**kw):
        base = {"ts": "2026-10-06 06:20:00", "game": "鸣潮", "title": "t",
                "text": "x", "version": "", "evidence_run": ""}
        base.update(kw)
        return base


    d = tmpdir()

    print("[an empty state dir waits]")
    check("read_rows on a missing file is {}", read_rows(str(d), "missing.json"), {})
    check("no boot row", boot_judged(str(d), "v1"), False)
    check("no alarms", alerts_with_version(str(d), "v1"), [])
    check("verdict wait", verdict(str(d), "v1"), ("wait", []))

    print("[a boot row of this version means the batch judged]")
    (d / "machinecheck.json").write_text(json.dumps({"#63": mc_row(version="v1", event="boot")},
                                                    ensure_ascii=False), encoding="utf-8")
    check("boot judged", boot_judged(str(d), "v1"), True)
    check("verdict boot", verdict(str(d), "v1"), ("boot", []))
    check("an older version's row does not count", boot_judged(str(d), "v0"), False)

    print("[a non-boot event is not the boot batch]")
    (d / "machinecheck.json").write_text(json.dumps({"#21": mc_row(version="v1", event="unresolved")},
                                                    ensure_ascii=False), encoding="utf-8")
    check("unresolved row is not boot", boot_judged(str(d), "v1"), False)
    check("so it still waits", verdict(str(d), "v1"), ("wait", []))

    print("[a group push of this version is an alarm, and beats a judged boot]")
    (d / "machinecheck.json").write_text(json.dumps({"#63": mc_row(version="v1", event="boot")},
                                                    ensure_ascii=False), encoding="utf-8")
    ad = d / "alerts"
    ad.mkdir()
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v1", title="上机核对 #2 没过"), ensure_ascii=False) + "\n",
        encoding="utf-8")
    st, alarms = verdict(str(d), "v1")
    check("alarm wins over a judged boot", st, "alarm")
    check("the push is listed", [a["title"] for a in alarms], ["上机核对 #2 没过"])

    print("[an older version's push does not alarm this deploy]")
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n",
        encoding="utf-8")
    check("old version is quiet, boot still judged", verdict(str(d), "v1"), ("boot", []))

    print("[a malformed alerts line is skipped, a good one read]")
    (ad / "20261006.jsonl").write_text(
        "not json\n" + json.dumps(alert_row(version="v1", title="good"), ensure_ascii=False) + "\n",
        encoding="utf-8")
    check("one good row survives the junk",
          [a["title"] for a in alerts_with_version(str(d), "v1")], ["good"])


    def run_main(state_dir, version):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = main([state_dir, version, "0"])
        return rc, out.getvalue()


    print("[a torn last line (a push being appended) is not read as quiet]")
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n"
        + '{"ts": "2026-10-06 06:21:00", "game": "鸣潮", "ti', encoding="utf-8")
    check("boot judged but the alerts are torn: wait", verdict(str(d), "v1"), ("wait", []))
    rc, out = run_main(str(d), "v1")
    check("main does not print MCWAIT_OK", "MCWAIT_OK" in out, False)
    check("main exits 2 at the timeout (torn line)", rc, 2)
    check("the timeout line names the file", "20261006.jsonl" in out, True)
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n"
        + json.dumps(alert_row(version="v1", title="torn one"), ensure_ascii=False) + "\n",
        encoding="utf-8")
    check("once the line is whole the next poll sees the alarm", verdict(str(d), "v1")[0], "alarm")

    print("[an old file's torn last line (a past crash) is skipped with one note, not waited on]")
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n"
        + '{"ts": "2026-10-03 06:21:00", "game": "鸣潮", "ti', encoding="utf-8")
    old = os.stat(ad / "20261006.jsonl").st_mtime - 3 * 86400
    os.utime(ad / "20261006.jsonl", (old, old))
    notes = io.StringIO()
    with contextlib.redirect_stdout(notes):
        first = verdict(str(d), "v1")
        second = verdict(str(d), "v1")
    check("boot judged and the torn file is days old: boot", first, ("boot", []))
    check("still boot on the next poll", second, ("boot", []))
    check("the note names the file", "20261006.jsonl" in notes.getvalue(), True)
    check("the note is printed once over two polls", notes.getvalue().count("20261006.jsonl"), 1)
    rc, out = run_main(str(d), "v1")
    check("main passes over an old torn line", (rc, "MCWAIT_OK" in out), (0, True))

    print("[an unreadable alerts file is not read as quiet]")
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n", encoding="utf-8")
    check("readable and quiet: boot", verdict(str(d), "v1"), ("boot", []))
    # chmod 0 makes a file unreadable on POSIX only; on Windows it only sets the read-only
    # flag (docs.python.org/3/library/os.html#os.chmod). There a byte-range lock over the
    # whole file makes reads of it fail, in this process and in run_main's.
    _lock = None
    if os.name == "nt":
        import msvcrt
        _lock = open(ad / "20261006.jsonl", "r+b")
        msvcrt.locking(_lock.fileno(), msvcrt.LK_NBLCK, max(1, (ad / "20261006.jsonl").stat().st_size))
    else:
        os.chmod(ad / "20261006.jsonl", 0)
    try:
        check("unreadable: wait", verdict(str(d), "v1"), ("wait", []))
        rc, out = run_main(str(d), "v1")
        check("main exits 2 at the timeout (unreadable file)", rc, 2)
        check("the timeout line says it could not read the file", "20261006.jsonl" in out, True)
    finally:
        if _lock is not None:
            _lock.seek(0)
            msvcrt.locking(_lock.fileno(), msvcrt.LK_UNLCK, max(1, (ad / "20261006.jsonl").stat().st_size))
            _lock.close()
        else:
            os.chmod(ad / "20261006.jsonl", 0o644)

    print("[pushes docs/NOTIFICATIONS.md routes `group (report)` are not alarms]")
    # The real rows: 10-13 10:00 the 🖼️ 无音区产出 the owner asked for (version 20261012131940;
    # the old gate printed MCWAIT_ALARM 1 on it), and 10-12 08:46 a 🩺 中继自己报错了 alarm.
    DOC = str(ROOT.parent / "docs" / "NOTIFICATIONS.md")
    real = [json.loads(ln) for ln in (ROOT / "tests" / "fixtures" / "alerts-e2-report-push.jsonl")
            .read_text(encoding="utf-8").splitlines() if ln.strip()]
    tacet, fault = real
    e = tmpdir()
    (e / "alerts").mkdir()
    (e / "machinecheck.json").write_text(json.dumps({"#63": mc_row(version="20261012131940", event="boot")}),
                                         encoding="utf-8")


    def run_doc(state_dir, version, *rows):
        (Path(state_dir) / "alerts" / "20261013.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = main([state_dir, version, "0", DOC])
        return rc, out.getvalue()


    rc, out = run_doc(str(e), "20261012131940", tacet)
    check("无音区产出 only: exit 0", rc, 0)
    check("it is listed as INFO, not ALARM", ("INFO" in out and "无音区产出" in out, "ALARM" in out), (True, False))
    banner = dict(tacet, title="🎴 明天开新卡池：鸣潮", text="明天 10:00 开新卡池")
    rc, out = run_doc(str(e), "20261012131940", banner)
    check("明天开新卡池：<games> (title cut at the placeholder): exit 0", rc, 0)
    rc, out = run_doc(str(e), "20261012131940", tacet, dict(fault, version="20261012131940"))
    check("a real alarm next to it still fails: exit 1", rc, 1)
    check("only the alarm is an ALARM line", (out.count("ALARM 2026"), "MCWAIT_ALARM 1" in out), (1, True))
    rc, out = run_doc(str(e), "20261012131940", dict(fault, title="🌙 关机被取消", version="20261012131940"))
    check("🌙 关机被取消 is routed `group` in the page, so it counts", rc, 1)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = main([str(e), "20261012131940", "0", str(e / "no-such-page.md")])
    check("page missing: every group push counts again (exit 1, with a NOTE)",
          (rc, "NOTE" in out.getvalue()), (1, True))


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_machinecheck_wait]))
