"""state.json: the store, reads a Windows lock refuses, and reads put off with nothing to bring them back; atomic writes, pending state, threads.

One part per former file, each run on its own (tests/_parts.py): test_statestore.py, test_atomic_write.py, test_state_pending.py, test_statestore_threads.py.
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
    """state.json：一个文件、登记过的字段才能写、原子落盘、旧文件自动迁入。

    Formerly test_statestore.py.
    """
    import json, logging, sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.statestore import StateStore


    class Warns(logging.Handler):
        """Collects the WARNING lines of one logger (each one is a group message)."""

        def __init__(self, name):
            super().__init__(logging.WARNING)
            self.lines = []
            logging.getLogger(name).addHandler(self)

        def emit(self, record):
            self.lines.append(record.getMessage())


    d = tmpdir()
    s = StateStore(d)
    print("[空目录：读到空段，不落盘]")
    check("weekly 空", s.section("weekly"), {})
    check("还没有文件", (d / "state.json").exists(), False)

    print("[登记过的能写，没登记的拒绝]")
    s.set("weekly", "garden", {"done_week": "2026-W37"})
    check("写进去", s.get("weekly", "garden"), {"done_week": "2026-W37"})
    check("落盘了", json.loads((d / "state.json").read_text(encoding="utf-8"))["weekly"]["garden"], {"done_week": "2026-W37"})
    try:
        s.set("weekly", "made_up", 1); check("未登记键被拒", False, True)
    except KeyError as e:
        check("未登记键被拒", "没在字段表里登记" in str(e), True)
    s.set("marks", "report:2026-09-07", "2026-09-07T22:00:00")
    check("通配键", s.get("marks", "report:2026-09-07"), "2026-09-07T22:00:00")
    s.pop("weekly", "garden")
    check("pop", s.get("weekly", "garden"), None)

    print("[另一个实例看到同一份（按 mtime 重读）]")
    s2 = StateStore(d)
    check("读到", s2.get("marks", "report:2026-09-07"), "2026-09-07T22:00:00")
    s2.set("versions", "okww", "v3.6.7")
    check("第一个实例也看到", s.get("versions", "okww"), "v3.6.7")

    print("[旧文件迁入]")
    d2 = tmpdir()
    (d2 / "garden.json").write_text(json.dumps({"done_week": "2026-W36"}), encoding="utf-8")
    (d2 / "weeklyboss.json").write_text(json.dumps({"index": 1, "name": "千傀重楼", "done_week": "2026-W37"}), encoding="utf-8")
    (d2 / "okww-version.txt").write_text("v3.6.7", encoding="utf-8")
    (d2 / "annihilation.json").write_text("{}", encoding="utf-8")   # 空的不迁
    t = StateStore(d2)
    check("garden 迁入", t.get("weekly", "garden"), {"done_week": "2026-W36"})
    check("boss 迁入", t.get("weekly", "boss")["name"], "千傀重楼")
    check("版本迁入", t.get("versions", "okww"), "v3.6.7")
    check("空文件不迁", t.get("weekly", "annihilation"), None)
    check("旧文件改名保留", (d2 / "garden.json.migrated").exists() and not (d2 / "garden.json").exists(), True)
    check("再来一个实例不重复迁", StateStore(d2).get("weekly", "garden"), {"done_week": "2026-W36"})

    print("[按天/按卡池的旧标记也迁：一次全搬]")
    d3 = tmpdir()
    (d3 / "report-2026-09-06.sent").write_text("", encoding="utf-8")
    (d3 / "interim-2026-09-06.sent").write_text("7", encoding="utf-8")
    (d3 / "interim-2026-09-05.sent").write_text("", encoding="utf-8")     # 旧空标记
    (d3 / "banner-明日方舟-202609041200.sent").write_text("", encoding="utf-8")
    (d3 / "skip-next-shutdown.flag").write_text("skip", encoding="utf-8")
    (d3 / "shutdown-skipped.txt").write_text("2026-09-06:1", encoding="utf-8")
    (d3 / "pending.json").write_text(json.dumps({"MaaEnd|endfield": {"run_id": "x"}}), encoding="utf-8")
    u = StateStore(d3)
    check("日报标记", u.get("marks", "report:2026-09-06"), True)
    check("临时日报带条数", u.get("marks", "interim:2026-09-06"), "7")
    check("旧空标记原样保留（条数不详）", u.get("marks", "interim:2026-09-05"), "")
    check("卡池标记", u.get("marks", "banner:明日方舟-202609041200"), True)
    check("别关机开关", u.get("modes", "skip_next_shutdown"), True)
    check("被吃掉的关机机会", u.get("modes", "shutdown_skipped"), "2026-09-06:1")
    check("告警队列", u.get("queues", "pending"), {"MaaEnd|endfield": {"run_id": "x"}})
    check("旧文件都改名了", sorted(p.name for p in d3.glob("*.sent")), [])

    print("[State 读回来的语义没变]")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.ledger import State
    st = State(d3)
    check("report_sent", st.report_sent("2026-09-06"), True)
    check("没发过的那天", st.report_sent("2026-09-07"), False)
    check("interim_covered 带条数", st.interim_covered("2026-09-06"), 7)
    check("旧空标记 → 不再重播", st.interim_covered("2026-09-05"), 10**6)
    check("没发过 → 0", st.interim_covered("2026-09-07"), 0)
    # A non-numeric marker for a day still being judged is a bug (writes are atomic):
    # it silently suppresses every further interim that day, so it is said - once,
    # since the interim check runs every tick.
    cw = Warns("ark.core")
    st.store.set("marks", "interim:2026-09-08", "abc")
    check("非数字标记仍按「已发、条数不详」", [st.interim_covered("2026-09-08") for _ in range(3)], [10**6] * 3)
    check("非数字标记说一声，只说一次", len([ln for ln in cw.lines if "interim:2026-09-08" in ln]), 1)
    st.store.set("marks", "interim:2026-09-08", "3")
    check("改好后照常", st.interim_covered("2026-09-08"), 3)
    st.store.set("marks", "interim:2026-09-08", "")
    st.interim_covered("2026-09-08")
    check("又坏了再说一次", len([ln for ln in cw.lines if "interim:2026-09-08" in ln]), 2)
    check("卡池", st.banner_announced("明日方舟-202609041200"), True)
    check("告警队列", st.load_pending(), {"MaaEnd|endfield": {"run_id": "x"}})
    st.mark_report_sent("2026-09-07")
    check("写完能读回", st.report_sent("2026-09-07"), True)

    print("[state.json 已存在时，后来才补的旧文件也要迁——不能只在首次建档时迁]")
    d4 = tmpdir()
    import ark_relay.core.statestore as SS
    SS._SWEPT.clear()
    first = StateStore(d4)
    first.set("weekly", "garden", {"done_week": "2026-W37"})    # 先有了 state.json
    (d4 / "report-2026-09-07.sent").write_text("", encoding="utf-8")
    (d4 / "pending.json").write_text(json.dumps({"MaaEnd|endfield": {"run_id": "y"}}), encoding="utf-8")
    (d4 / "gameupdate-pending.json").write_text(json.dumps({"鸣潮": "客户端待更新"}), encoding="utf-8")
    SS._SWEPT.clear()                                            # 模拟下一次进程启动
    later = StateStore(d4)
    check("后补的日报标记迁进来了", later.get("marks", "report:2026-09-07"), True)
    check("后补的告警队列迁进来了", later.get("queues", "pending"), {"MaaEnd|endfield": {"run_id": "y"}})
    check("后补的待更新登记迁进来了", later.get("updates", "gameupdate_pending"), {"鸣潮": "客户端待更新"})
    check("原有的值没被动", later.get("weekly", "garden"), {"done_week": "2026-W37"})
    check("旧文件收走了", sorted(p.name for p in d4.glob("*.sent")), [])

    print("[state.json 里已有值时，旧文件不许覆盖它]")
    d5 = tmpdir()
    SS._SWEPT.clear()
    s5 = StateStore(d5)
    s5.set("versions", "okww", "v3.6.7")
    (d5 / "okww-version.txt").write_text("v3.6.5", encoding="utf-8")   # 陈旧的遗留
    SS._SWEPT.clear()
    check("以 state.json 为准", StateStore(d5).get("versions", "okww"), "v3.6.7")
    check("陈旧文件也收走", (d5 / "okww-version.txt").exists(), False)

    print("[state.json unreadable: copied aside before anything overwrites it, said once per mtime]")
    # Until 2026-10-10 the WARNING said the old content was untouched on disk, and the
    # next set() overwrote state.json with the near-empty dict it fell back to.
    import os
    d6 = tmpdir()
    SS._SWEPT.clear()
    SS._CORRUPT_SAID.clear()
    (d6 / "state.json").write_text('{"weekly": {"garden": {"done_week": "2026-W4', encoding="utf-8")
    os.utime(d6 / "state.json", (1_790_000_000, 1_790_000_000))
    sw = Warns("ark.statestore")
    check("读不出来按空", StateStore(d6).section("weekly"), {})
    check("别的实例再读不再说", [StateStore(d6).get("modes", "debug_until") for _ in range(3)], [None] * 3)
    copies = sorted(d6.glob("state.json.corrupt-*"))
    check("另存了一份", len(copies), 1)
    check("另存的是原样", copies and copies[0].read_text(encoding="utf-8"), '{"weekly": {"garden": {"done_week": "2026-W4')
    check("只说一次，说出另存的文件名", [copies[0].name in ln for ln in sw.lines] if copies else sw.lines, [True])
    StateStore(d6).set("versions", "okww", "v3.6.7")
    check("写入后另存的还在", copies and copies[0].exists(), True)
    (d6 / "state.json").write_text("{bad", encoding="utf-8")
    os.utime(d6 / "state.json", (1_790_000_100, 1_790_000_100))
    StateStore(d6).get("versions", "okww")
    check("又坏了（新的 mtime）再说一次、再存一份", (len(sw.lines), len(list(d6.glob("state.json.corrupt-*")))), (2, 2))

    print("\n[清单-1108 A-07：同一进程里另一个实例刚写过，mtime 碰巧一样也不读旧缓存；写的副本是深拷贝]")
    d7 = tmpdir()
    a, b = StateStore(d7), StateStore(d7)
    a.set("updates", "queue_skips", [{"script": "MAA"}])
    check("b 先读一遍", b.get("updates", "queue_skips"), [{"script": "MAA"}])
    st = (d7 / "state.json").stat()
    a.set("updates", "queue_skips", [])
    os.utime(d7 / "state.json", ns=(st.st_atime_ns, st.st_mtime_ns))     # the same mtime as b's copy
    check("a 写过之后，b 读到的是新的（不是 mtime 相同的旧缓存）", b.get("updates", "queue_skips"), [])
    c = StateStore(d7)
    c.set("updates", "queue_skips", [{"script": "OK-WW"}])
    data = c._writable()
    data["updates"]["queue_skips"].append({"script": "MaaEnd"})
    check("改写副本里的列表，不动缓存", c.get("updates", "queue_skips"), [{"script": "OK-WW"}])


def _part_state_read_lock():  # noqa: C901 - the whole body of the file this part was
    """state.json reads that a Windows lock refuses, and alarm day marks written by two
writers: no alarm pushed twice, no mark lost, no relay state lost.

Review of 99999b8e (10-17), one scenario per finding:
  1. A plain read of state.json that hit a lock (PermissionError, or any OSError)
     copied the healthy file aside as state.json.corrupt-* and cached {} until the
     file's mtime changed: every alarm day mark answered "not sent", so an alarm going
     through unresolved.send was pushed a second time. A write that met an OSError
     other than a lock on its read put the near-empty fallback over the file; the
     legacy sweep did the same after a plain read that a lock refused; a state.json
     holding JSON that is not a table crashed every read.
  2. daymarks._mark_alerted built the day's list from a read outside the write lock
     (served from the cached copy) and set() wrote it whole: a mark another writer
     made in between was dropped.

    Formerly test_state_read_lock_1017.py.
    """
    import json
    import logging
    import os
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import statestore
    from ark_relay.core.statestore import StateStore
    from ark_relay.features.alarm import handle, unresolved

    DAY = "2026-10-08"
    MARK = f"alerted:{DAY}"
    REAL_READ_TEXT = Path.read_text
    NO_WAITS = (0.0, 0.0, 0.0)


    class Lines(logging.Handler):
        """WARNING and up on ark.statestore: each such line is a group message."""

        def __init__(self, logger):
            super().__init__(logging.WARNING)
            self.lines = []
            logger.addHandler(self)

        def emit(self, record):
            self.lines.append(record.getMessage())


    LINES = Lines(statestore.log)


    class read_fails:
        """Path.read_text of state.json raises `exc` (default: the PermissionError a
    Windows sharing violation becomes) while inside, every time."""

        def __init__(self, exc=None):
            self.exc = exc or PermissionError(13, "state.json being scanned (test)")
            self.tries = 0

        def __enter__(self):
            self.waits = statestore.LOCK_WAITS
            statestore.LOCK_WAITS = NO_WAITS

            def _read(path, *a, **kw):
                if Path(path).name == statestore.FILE:
                    self.tries += 1
                    raise self.exc
                return REAL_READ_TEXT(path, *a, **kw)
            Path.read_text = _read
            return self

        def __exit__(self, *a):
            Path.read_text = REAL_READ_TEXT
            statestore.LOCK_WAITS = self.waits


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", alert=False, **kw):
            self.sent.append(title)
            return []


    class Eng:
        """What unresolved.send and daymarks use of the engine: one long-lived store."""

        def __init__(self, d):
            self.state = types.SimpleNamespace(dir=d, store=StateStore(d))
            self.notifier = Notes()

        def _already_alerted(self, day, key):
            return handle._already_alerted(self, day, key)

        def _mark_alerted(self, day, key):
            return handle._mark_alerted(self, day, key)


    def folder(data=None):
        d = tmpdir()
        if data is not None:
            (d / statestore.FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return d


    def bump(d, by=5):
        """Move state.json's mtime on, as a write by another writer does."""
        st = (d / statestore.FILE).stat()
        os.utime(d / statestore.FILE, (st.st_atime, st.st_mtime + by))


    def on_disk(d):
        return json.loads(REAL_READ_TEXT(d / statestore.FILE, encoding="utf-8"))


    def corrupt_copies(d):
        return sorted(p.name for p in d.glob(statestore.FILE + ".corrupt-*"))


    def forget(d):
        """This process has read nothing of `d` yet (a relay just started)."""
        getattr(statestore, "_LAST_GOOD", {}).pop(str(d / statestore.FILE), None)


    def section(title, fn):
        print(f"\n[{title}]")
        LINES.lines.clear()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a crash is this item failing; the others still run
            check(f"{title}: ran to the end", f"{type(exc).__name__}: {exc}", "")
        finally:
            Path.read_text = REAL_READ_TEXT


    def item1a():
        d = folder()
        eng = Eng(d)
        title = "明日方舟 没跑成（test）"
        check("first push goes out", unresolved.send(eng, DAY, "未解决", "run-1", title, "body"), True)
        StateStore(d).set("versions", "okww", "v9")     # another writer: the file's mtime moves on
        bump(d)
        with read_fails():
            again = unresolved.send(eng, DAY, "未解决", "run-1", title, "body")
            marked = handle._already_alerted(eng, DAY, unresolved._key("未解决", "run-1"))
        check("state.json locked: the replayed record is not pushed again",
              (again, eng.notifier.sent.count(title)), (True, 1))
        check("state.json locked: its day mark still reads as sent", marked, True)
        check("a healthy file a lock refused is not copied aside", corrupt_copies(d), [])
        check("no WARNING / ERROR (group message) for a lock on a plain read", LINES.lines, [])
        check("the lock gone, the next read sees what the other writer wrote",
              eng.state.store.get("versions", "okww"), "v9")


    def item1b():
        d = folder({"marks": {MARK: ["k"]}, "modes": {"debug_until": "2026-10-08 23:00"}})
        before = (d / statestore.FILE).read_bytes()
        forget(d)
        cold = StateStore(d)
        with read_fails() as lock:
            cold.get("marks", MARK)
        check("a first read waits the lock out before giving up", lock.tries, len(NO_WAITS) + 1)
        check("the lock gone, the same instance reads the file (nothing cached from the lock)",
              cold.get("marks", MARK), ["k"])
        check("the file is left as it was", (d / statestore.FILE).read_bytes(), before)
        check("and not copied aside", corrupt_copies(d), [])
        check("no WARNING / ERROR", LINES.lines, [])


    def item1c():
        d = folder({"marks": {MARK: ["k"]}, "modes": {"skip_next_shutdown": True}})
        StateStore(d).get("marks", MARK)                # read once in this process
        bump(d)
        with read_fails() as lock:
            got = (StateStore(d).get("marks", MARK), StateStore(d).get("modes", "skip_next_shutdown"))
        check("a store built per call answers with what this process read last", got, (["k"], True))
        check("and does not sleep through the lock waits for it", lock.tries, 2)


    def item1d():
        d = folder({"marks": {MARK: ["k"]}, "weekly": {"garden": {"done_week": "2026-W41"}}})
        store = StateStore(d)
        store.get("marks", MARK)
        bump(d)
        try:
            with read_fails(OSError(5, "Input/output error (test)")):
                store.set("versions", "okww", "v9")
            raised = ""
        except OSError as exc:
            raised = type(exc).__name__
        check("a write whose read meets another OSError raises", raised, "OSError")
        check("and leaves everything on file", on_disk(d),
              {"marks": {MARK: ["k"]}, "weekly": {"garden": {"done_week": "2026-W41"}}})
        check("not copied aside", corrupt_copies(d), [])


    def item1e():
        d = folder()
        (d / statestore.FILE).write_text("[1, 2]", encoding="utf-8")
        try:
            got = StateStore(d).get("marks", MARK)
        except Exception as exc:  # noqa: BLE001
            got = f"{type(exc).__name__}: {exc}"
        check("state.json holding a list (not a table) reads as empty", got, None)
        check("and is copied aside before anything overwrites it", len(corrupt_copies(d)), 1)


    def item1f():
        d = folder({"versions": {"code": "20261017"}, "marks": {MARK: ["k"]}})
        (d / "okww-version.txt").write_text("v3.6.5", encoding="utf-8")
        forget(d)
        statestore._SWEPT.discard(str(d))
        with read_fails():
            StateStore(d)
        check("legacy sweep with state.json locked leaves it as it was", on_disk(d),
              {"versions": {"code": "20261017"}, "marks": {MARK: ["k"]}})
        check("and moves no legacy file", (d / "okww-version.txt").exists(), True)
        StateStore(d)
        check("the lock gone, the next StateStore sweeps it in",
              (on_disk(d)["versions"].get("okww"), on_disk(d)["marks"].get(MARK)), ("v3.6.5", ["k"]))


    def item2():
        d = folder({"marks": {}})
        one, two = Eng(d), Eng(d)
        one.state.store.get("marks", MARK)              # one's cached copy: no marks yet
        m0 = (d / statestore.FILE).stat().st_mtime
        two._mark_alerted(DAY, "b")
        # The second write lands within the clock's resolution: the mtime reads as it
        # did when `one` cached the file (put back by hand here).
        os.utime(d / statestore.FILE, (m0, m0))
        one._mark_alerted(DAY, "a")
        check("two writers marking the same day: both marks are on file",
              sorted(on_disk(d)["marks"].get(MARK) or []), ["a", "b"])
        check("and each reads both back", (one._already_alerted(DAY, "b"), two._already_alerted(DAY, "a")),
              (True, True))


    for title, fn in (("1a: state.json locked after an alarm went out: not pushed again", item1a),
                      ("1b: the first read of state.json locked", item1b),
                      ("1c: a store built per call while state.json is locked", item1c),
                      ("1d: a write whose read meets an OSError other than a lock", item1d),
                      ("1e: state.json that is JSON but not a table", item1e),
                      ("1f: the legacy sweep while state.json is locked", item1f),
                      ("2: two writers marking one day's alarms", item2)):
        section(title, fn)

    print()
    if fails:
        print(f"✗ {len(fails)} 条没过：{fails}")
        sys.exit(1)
    print("all checks passed")


def _part_state_unread():
    """Reads put off with nothing to bring them back (dispatch relay-audit-round2-1108 N-02 / N-05).

N-02, the running half of 08635a7b (its boot half stays shelved, BOARD D-1017): state.json
refusing reads (a lock outlasting LOCK_WAITS, any OSError) was one INFO line per refused read
and nothing else - a lock that never let go kept every write failing, the relay silent and the
machine on. Pinned here:

* a refused read starts a run: one INFO line, statestore.refused_since names when; a plain
  read still answers with the last good copy, a write still raises;
* while the run lasts every read tries the file again (the cached copy is not served);
* UNREAD_WARN_S (600 s, the relay's other outage marks) after the first refusal: one WARNING
  (the group), not repeated while the same run lasts; a read that gets through ends the run
  with one INFO line, and a later lock is a new run;
* engine.next_deadline wakes the loop UNREAD_RETRY_S (45 s) later while the run lasts.

N-05: the need table's same-day second try (「过半小时再试一次」) and AUTO-MAS records the
last scan put off (a missing log, a history.db read that failed) had no moment either; the
loop slept to the hour backstop. needtable.next_moment / collector.next_moment and their
place in next_deadline are pinned here too.

    Formerly test_state_unread_1108.py.
    """
    import json
    import logging
    import os
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE))

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (TMP / "history").mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(HERE.parent))

    from ark_relay.core import collector, statestore
    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.needtable import needtable


    class Rows(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, record.getMessage(), bool(getattr(record, errwatch.RECOVERED, False))))


    rows = Rows()
    statestore.log.addHandler(rows)
    statestore.log.setLevel(logging.DEBUG)
    # errwatch's handler sits on the "ark" logger (errwatch.install): what reaches it there is
    # what the group hears. It writes errkinds/ and the technical log, never state.json, so the
    # push does not die in the outage it reports.
    at_errwatch = []
    _ark = logging.getLogger(errwatch.ARK)
    _ark_rows = Rows()
    _ark_rows.emit = lambda r: at_errwatch.append(r.levelname) if r.name == statestore.log.name else None
    _ark.addHandler(_ark_rows)

    clock = [1000.0]
    import time as _time
    statestore.time = SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda s: None, time=_time.time)
    REAL_READ = Path.read_text
    lock = {"on": False, "tries": 0}


    def read_text(self, *a, **kw):
        if lock["on"] and self.name == statestore.FILE:
            lock["tries"] += 1
            raise PermissionError(13, "being used by another process (test)")
        return REAL_READ(self, *a, **kw)


    Path.read_text = read_text


    def levels():
        return [lv for lv, _, _ in rows.rows]


    d = tmpdir() / "state"
    st = statestore.StateStore(d)
    st.update("weekly", "garden", lambda _: {"done_week": "2026-W45"})
    path = d / statestore.FILE

    print("[读不出来：一条 INFO，接着用上次读到的，写照样报错]")
    rows.rows.clear()
    lock["on"] = True
    lock["tries"] = 0
    check("同一个实例、文件没变：直接用它手上那份，不去读", (st.get("weekly", "garden"), lock["tries"]),
          ({"done_week": "2026-W45"}, 0))
    check("…不算读不出来", statestore.refused_since(path), None)
    # Most call sites build a StateStore per call: that one reads the file.
    check("新建的实例读不出来：拿到的是上次读到的那份", statestore.StateStore(d).get("weekly", "garden"),
          {"done_week": "2026-W45"})
    check("记下了从什么时候开始读不出来", statestore.refused_since(path), 1000.0)
    check("一条 INFO", levels(), ["INFO"])
    raised = ""
    try:
        st.update("weekly", "garden", lambda _: {"done_week": "2026-W46"})
    except OSError as exc:
        raised = type(exc).__name__
    check("写不进去就报错（不拿空的盖上去）", raised, "PermissionError")
    lock["tries"] = 0
    st.get("weekly", "garden")
    check("读不出来期间每次读都再去读文件（不用缓存）", lock["tries"], 1)
    check("还是只有那一条 INFO", levels(), ["INFO"])

    print("\n[连着 10 分钟读不出来：一条进群的 WARNING，同一段里不再重复]")
    check("和别的中断报警同一个时长", (statestore.UNREAD_WARN_S, statestore.UNREAD_RETRY_S), (600, 45))
    from ark_relay.features.phone.mailbox import Mailbox
    check("就是 Mailbox.OUTAGE_SEC", float(statestore.UNREAD_WARN_S), float(Mailbox.OUTAGE_SEC))
    clock[0] = 1000.0 + 599
    st.get("weekly", "garden")
    check("599 秒：还没有 WARNING", "WARNING" in levels(), False)
    clock[0] = 1000.0 + 600
    st.get("weekly", "garden")
    w = [(m, r) for lv, m, r in rows.rows if lv == "WARNING"]
    check("600 秒：一条 WARNING，没标自己好了，说 10 分钟、带原因",
          [(r, "10 分钟" in m, "PermissionError" in m) for m, r in w], [(False, True, True)])
    check("这条 WARNING 到了 errwatch 挂的那个 logger（会进群）", at_errwatch.count("WARNING"), 1)
    clock[0] = 1000.0 + 1800
    st.get("weekly", "garden")
    check("再过 20 分钟：不再发第二条", levels().count("WARNING"), 1)

    print("\n[读回来了：一条 INFO，说之前报过；再锁住是新的一段]")
    lock["on"] = False
    rows.rows.clear()
    check("读得到", st.get("weekly", "garden"), {"done_week": "2026-W45"})
    check("不再记着读不出来", statestore.refused_since(path), None)
    check("一条 INFO，说持续了多久、之前报过",
          [(lv, "30 分钟" in m and "已报过" in m) for lv, m, _ in rows.rows], [("INFO", True)])
    st.update("weekly", "garden", lambda _: {"done_week": "2026-W46"})
    check("又写得进去", json.loads(REAL_READ(path, encoding="utf-8"))["weekly"]["garden"], {"done_week": "2026-W46"})
    lock["on"] = True
    clock[0] = 5000.0
    rows.rows.clear()
    statestore.StateStore(d).get("weekly", "garden")
    check("再锁住：新的一段从这次算起", statestore.refused_since(path), 5000.0)
    clock[0] = 5000.0 + 600
    st.get("weekly", "garden")
    check("新的一段到 10 分钟：又一条 WARNING", levels().count("WARNING"), 1)
    lock["on"] = False
    st.get("weekly", "garden")

    print("\n[主循环：读不出来时 45 秒后再醒一次]")


    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng.Engine(cfg, source=SimpleNamespace(fetch=lambda seen: []), state=State(cfg.state_dir),
                       notifier=SimpleNamespace(send=lambda *a, **k: False))
        e._scripts_running = lambda: False
        return e


    NOW = datetime(2026, 11, 8, 10, 0, tzinfo=SERVER_TZ)
    e = build()
    got = e.next_deadline(NOW)
    check("读得到时：没有重读的闹钟", "重读 state.json" in (got[1] if got else ""), False)
    e.state.store.update("weekly", "garden", lambda _: {"done_week": "2026-W45"})
    lock["on"] = True
    statestore.StateStore(e.cfg.state_dir).get("weekly", "garden")
    got = e.next_deadline(NOW)
    check("读不出来时：45 秒后重读", got, (NOW + timedelta(seconds=45), "重读 state.json"))
    lock["on"] = False
    e.state.store.get("weekly", "garden")
    check("读回来后闹钟就没了", "重读 state.json" in (e.next_deadline(NOW) or (None, ""))[1], False)
    Path.read_text = REAL_READ

    print("\n[需求表：当天第一次没成，半小时后叫醒主循环去试第二次]")
    needtable._running.clear()
    nd = tmpdir()
    check("今天还没建过：没有这个闹钟", needtable.next_moment(nd, NOW), None)
    (nd / needtable.MARK).write_text(json.dumps({"day": "2026-11-08", "ok": False, "skip": False, "tries": 1,
                                                 "last_at": (NOW - timedelta(minutes=5)).isoformat()}),
                                     encoding="utf-8")
    check("第一次没成：失败后 30 分钟", needtable.next_moment(nd, NOW),
          (NOW + timedelta(minutes=25), "终末地需求表当天第二次重算"))
    check("到点之后不再给过去的时刻（这一轮就会去试）", needtable.next_moment(nd, NOW + timedelta(minutes=26)), None)
    e2 = build()
    e2.cfg.state_dir = nd
    check("next_deadline 里有这个闹钟", e2.next_deadline(NOW), (NOW + timedelta(minutes=25), "终末地需求表当天第二次重算"))
    for done in ({"ok": True}, {"skip": True}, {"tries": 2}, {"day": "2026-11-07"}):
        m = {"day": "2026-11-08", "ok": False, "skip": False, "tries": 1,
             "last_at": (NOW - timedelta(minutes=5)).isoformat(), **done}
        (nd / needtable.MARK).write_text(json.dumps(m), encoding="utf-8")
        check(f"不用再试（{done}）：没有闹钟", needtable.next_moment(nd, NOW), None)


    class Alive:
        def is_alive(self):
            return True


    needtable._running.update(thread=Alive(), day="2026-11-08", count=1)
    check("正在建：最晚 30 分钟后看一眼", needtable.next_moment(nd, NOW), (NOW + timedelta(minutes=30), "看终末地需求表重算完没有"))
    needtable._running.clear()

    print("\n[AUTO-MAS 记录：缺日志等着补记、history.db 读不了，都要叫醒主循环]")
    collector._put_off.clear()
    collector._db_fail_streak[0] = 0
    check("没有等着的：没有闹钟", collector.next_moment(NOW), None)
    collector._put_off.extend([(NOW + timedelta(seconds=90)).timestamp(), (NOW + timedelta(seconds=30)).timestamp(),
                               (NOW - timedelta(seconds=5)).timestamp()])
    check("缺日志的：最早那条到点时（过去的不算）", collector.next_moment(NOW), (NOW + timedelta(seconds=30), "补记缺日志的运行记录"))
    collector._put_off.clear()
    collector._db_fail_streak[0] = 1
    check("history.db 读不了：45 秒后再读", collector.next_moment(NOW), (NOW + timedelta(seconds=45), "重读 AUTO-MAS 的 history.db"))
    e3 = build()
    check("next_deadline 里有它", e3.next_deadline(NOW), (NOW + timedelta(seconds=45), "重读 AUTO-MAS 的 history.db"))
    collector._db_fail_streak[0] = 0

    hist = TMP / "history2"
    young = hist / "2026-11-08" / "MAA" / "10-00-00.json"
    young.parent.mkdir(parents=True)
    young.write_text("{}", encoding="utf-8")
    collector.scan(hist, set())
    check("扫到一条没日志的新记录：记下它 120 秒后补记", len(collector._put_off), 1)
    check("…时刻就是它写下后 120 秒", round(collector._put_off[0] - young.stat().st_mtime), 120)
    (young.with_suffix(".log")).write_text("", encoding="utf-8")
    collector.scan(hist, set())
    check("日志来了：不再等", collector._put_off, [])


def _part_atomic_write():
    """落盘只能走 config.atomic_write_*，不许自己手抄「临时文件 + replace」。

2026-09-08 数出来的：仓库里有 5 处手抄的原子写，各写各的——有的漏 fsync、有的
失败了不清理临时文件、报错方式还各不相同。同一件事五种写法，改一处别处不会跟着改，
而它们写的都是 AUTO-MAS / OK-WW / MaaEnd 没有就起不来的配置。

（当初我给的理由是「机器每天硬断电两次」，操作者纠正：一天只有一次，而且那一刻
机器已经关着。这条测试守的是「实现只有一份」，不是防断电。）

这条测试盯两件事：实现只有一份、别处不许再抄。

Section 4 (added 2026-10-12) is about power cuts after all, for state files
the relay reads back: the 08:40 socket cut takes the machine down whether
it is on or off (memory queue-schedule-what-runs.md), and a forced shutdown
or kill can land mid-write too.

    Formerly test_atomic_write.py.
    """
    import re

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))


    # 1. 唯一的实现在 config.py，而且带 fsync
    cfg = (ROOT / "ark_relay" / "core" / "config.py").read_text(encoding="utf-8")
    check("config.atomic_write_bytes 存在", "def atomic_write_bytes" in cfg, True)
    body = cfg[cfg.index("def atomic_write_bytes"):]
    body = body[:body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    check("它 fsync 了", "os.fsync" in body, True)
    check("它用 os.replace", "os.replace" in body, True)

    # 2. 别处不许再出现「.tmp 然后 replace」这一对
    offenders = []
    for p in sorted([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files"} & set(p.parts)]) + [ROOT / "service.py", ROOT / "boot_stages.py"]:
        if p.name == "config.py":
            continue
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r'^\s*(\w+)\s*=\s*.*with_suffix\([^\n]*\.tmp', src, re.M):
            var = m.group(1)
            after = src[m.end():m.end() + 600]
            if re.search(rf"\b(os\.replace\(\s*{var}|{var}\.replace\()", after):
                line = src[:m.start()].count("\n") + 1
                offenders.append(f"{p.name}:{line}")
    check("没有别处再手抄原子写", offenders, [])

    # 3. 写配置的模块都在用它（抽查那五个改过的）
    # (paths after ark_relay/ was split into core/ and features/<name>/)
    for name in ("features/weekly/garden.py", "features/weekly/weeklyboss.py",
                 "features/preupdate/preupdate_okww.py", "core/desktop.py"):
        src = (ROOT / "ark_relay" / name).read_text(encoding="utf-8")
        check(f"{name} 走的是共用实现",
              bool(re.search(r"atomic_write_(text|bytes)\(", src)), True)

    # 4. State files the relay reads back must not be written in place.
    # The game PC can lose power or be killed mid-write (the 08:40 socket cut when
    # the machine was left on, a forced shutdown). A half-written state file is
    # read as empty: retry failure streaks reset, sent markers are lost (the tacet
    # shot / upstream-change notice goes out again), the ntfy day count drops to
    # zero. These modules write such files and must go through atomic_write_*;
    # a direct write_text / write_bytes / open("w") in them fails here.
    # Appends (open "a" / "ab") are allowed: a cut loses at most the last line.
    DIRECT_OVERWRITE = re.compile(
        r"\.write_text\(|\.write_bytes\(|\bopen\([^)\n]*[\"'](?:w|wb|w\+|wb\+|x|xb)[\"']")
    STATE_WRITERS = (
        "ark_relay/features/makeup/collect_retry.py",   # collect-retry/failures.json, <day>.json
        "ark_relay/features/report/report.py",          # tacet-shots-<day>.sent
        "boot_stages.py",                               # evidence-source-notified.json
        "ark_relay/features/phone/quota.py",            # ntfy-<utc day>.json
        "ark_relay/features/alarm/alertlog.py",         # alert day file re-seeded from COS
        "ark_relay/features/evidence/stores.py",        # evidence/gofile.json
        "ark_relay/features/banners/banners.py",        # banners/<day>.json
    )
    for name in STATE_WRITERS:
        src = (ROOT / name).read_text(encoding="utf-8")
        direct = [f"{name}:{src[:m.start()].count(chr(10)) + 1}"
                  for m in DIRECT_OVERWRITE.finditer(src)]
        check(f"{name} has no direct state-file overwrite", direct, [])
        check(f"{name} writes via atomic_write_*",
              bool(re.search(r"atomic_write_(text|bytes)\(", src)), True)


def _part_state_pending():
    """待推告警的存/取。**这条路没有测试过，结果炸在生产上。**

2026-09-08 上午：`core.State.save_pending` 上面被贴了一行多余的 `@property`。
后果不是「保存失败」这么轻——属性访问本身就抛 TypeError（getter 缺 payload），
于是 `_persist_pending` 每一轮都炸，三条鸣潮失败记录永远落不了账；
中继下一轮扫到它们，当成**新**失败又推一遍，每十几秒一条，把用户的群轰炸了半小时。

88 个测试里没有任何一个调用过 save_pending，静态检查也没有「@property 带参数」
这条规则，所以这行改动一路绿灯上了机器。这个文件补的就是那条路。

    Formerly test_state_pending.py.
    """
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.core.transport import record_to_payload, payload_to_record


    def rec(run_id="2026-09-08/wuwa/OK-WW-05-22-26"):
        now = datetime.now(tz=SERVER_TZ)
        return RunRecord(run_id=run_id, script="OK-WW", user="wuwa",
                         started=now - timedelta(minutes=10), finished=now,
                         ok=False, failed_tasks=["任务执行：某个错"], raw={})


    print("[save_pending 是方法，不是属性——这正是 09-08 那次的原形]")
    check("是普通函数", type(State.__dict__["save_pending"]).__name__, "function")
    check("不是 property", isinstance(State.__dict__["save_pending"], property), False)

    print("\n[存进去、另起一个实例读回来，内容一样]")
    d = tmpdir()
    st = State(d)
    payload = {"pending": [record_to_payload(rec())], "recovered": []}
    st.save_pending(payload)
    back = State(d).load_pending()
    check("pending 条数", len(back.get("pending") or []), 1)
    check("run_id 对得上", back["pending"][0]["run_id"], "2026-09-08/wuwa/OK-WW-05-22-26")
    check("recovered 空", back.get("recovered"), [])

    print("\n[读回来能还原成记录，告警才发得出去]")
    r2 = payload_to_record(back["pending"][0])
    check("脚本名", r2.script, "OK-WW")
    check("失败任务", r2.failed_tasks, ["任务执行：某个错"])
    check("不是成功", r2.ok, False)

    print("\n[空的也存得下：清空待推队列走的就是这条路]")
    st.save_pending({"pending": [], "recovered": []})
    check("清空后读回来是空的", State(d).load_pending(), {"pending": [], "recovered": []})

    print("\n[没存过时读回空字典，不抛异常]")
    check("空目录", State(tmpdir()).load_pending(), {})


def _part_statestore_threads():
    """Two threads writing state.json must not lose each other's key.

Audit s9 A2 (2026-10-13): the phone listen thread writes queues.phone_seen and,
through live commands, modes.* (set_debug, set_skip_shutdown ...), while the
engine thread writes the same file. StateStore.set/pop did load-modify-write with
no lock, and config.atomic_write_bytes always used the same temp name
(state.json.tmp). Run with two threads: 200/200 trials lost one update, 199 raised
FileNotFoundError on the rename. A lost modes.skip_next_shutdown means the reply
says 「已记下」 and the machine powers off anyway.

Both halves are made deterministic here: the first writer is held between its read
and its write while the second writer runs.

    Formerly test_statestore_threads.py.
    """
    import os
    import threading
    import time


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import config, statestore
    from ark_relay.core.statestore import StateStore


    print("[a second writer runs while the first is between its read and its write]")
    d = tmpdir()
    StateStore(d).set("queues", "phone_seen", [])
    real_write = statestore.atomic_write_text
    errors: list = []
    other: list = []


    def slow_first_write(path, text, *a, **k):
        # Only the first write is slowed down: the engine-thread writer below.
        if not other:
            def phone_thread():
                try:
                    StateStore(d).set("queues", "phone_seen", ["ntfy-1"])
                except Exception as exc:  # noqa: BLE001 - recorded for the check
                    errors.append(exc)
            t = threading.Thread(target=phone_thread)
            other.append(t)
            t.start()
            time.sleep(0.3)          # the phone thread gets every chance to write now
        return real_write(path, text, *a, **k)


    statestore.atomic_write_text = slow_first_write
    try:
        StateStore(d).set("modes", "debug_until", "2026-10-13 21:10")
    finally:
        statestore.atomic_write_text = real_write
    other[0].join(5)
    s = StateStore(d)
    check("the engine thread's key is there", s.get("modes", "debug_until"), "2026-10-13 21:10")
    check("the phone thread's key is there", s.get("queues", "phone_seen"), ["ntfy-1"])
    check("no writer raised", errors, [])

    print("\n[pop is under the same lock]")
    other.clear()


    def slow_first_write2(path, text, *a, **k):
        if not other:
            t = threading.Thread(target=lambda: StateStore(d).set("queues", "phone_seen", ["ntfy-2"]))
            other.append(t)
            t.start()
            time.sleep(0.3)
        return real_write(path, text, *a, **k)


    statestore.atomic_write_text = slow_first_write2
    try:
        StateStore(d).pop("modes", "debug_until")
    finally:
        statestore.atomic_write_text = real_write
    other[0].join(5)
    s = StateStore(d)
    check("the popped key is gone", s.get("modes", "debug_until"), None)
    check("the other thread's write survived the pop", s.get("queues", "phone_seen"), ["ntfy-2"])

    print("\n[two writes of the same file never share a temp file]")
    d2 = tmpdir()
    target = d2 / "state.json"
    real_fsync = config.os.fsync
    inner_err: list = []
    nested = []


    def fsync_then_second_write(fd):
        real_fsync(fd)
        if not nested:
            nested.append(1)
            # A second writer of the same path while the first one's temp file is open.
            try:
                config.atomic_write_bytes(target, b'{"b": 1}')
            except OSError as exc:
                inner_err.append(exc)


    config.os.fsync = fsync_then_second_write
    outer_err = None
    try:
        config.atomic_write_bytes(target, b'{"a": 1}')
    except OSError as exc:
        outer_err = exc
    finally:
        config.os.fsync = real_fsync
    check("the inner write did not fail", inner_err, [])
    check("the outer write did not fail", repr(outer_err) if outer_err else None, None)
    check("the last write wins, whole", target.read_bytes(), b'{"a": 1}')
    check("no temp file left behind", sorted(p.name for p in d2.iterdir()), ["state.json"])

    print("\n[a temp file a power cut left behind is removed at the next start once it is a day old]")
    d3 = tmpdir()
    (d3 / "state.json").write_text("{}", encoding="utf-8")
    old_tmp = d3 / "state.json.abc123.tmp"
    fresh_tmp = d3 / "state.json.def456.tmp"
    legacy_tmp = d3 / "state.json.tmp"
    other_tmp = d3 / "ledger-2026-10-13.jsonl.xyz.tmp"
    for f in (old_tmp, fresh_tmp, legacy_tmp, other_tmp):
        f.write_text("{", encoding="utf-8")
    two_days_ago = time.time() - 2 * 86400
    for f in (old_tmp, legacy_tmp, other_tmp):
        os.utime(f, (two_days_ago, two_days_ago))
    statestore._SWEPT.discard(str(d3))
    statestore.StateStore(d3)
    check("old state.json temp files are gone, a fresh one (a live write) and other files stay",
          sorted(p.name for p in d3.iterdir()),
          sorted(["state.json", fresh_tmp.name, other_tmp.name]))


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_state_read_lock, _part_state_unread, _part_atomic_write, _part_state_pending, _part_statestore_threads]))
