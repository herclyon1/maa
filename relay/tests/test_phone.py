"""Phone remote state, commands, heartbeat, resources, runtime snapshot, and inbox polling."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


def _part_phone_main():
    """手机通道：PIN 对不上、太老的指令、状态和指令别混。

凭证就一个 PIN（用户 2026-08-31：「留一个 pin 就行了，那那么多事」）。
这里钉住的是「不该被执行的消息有没有被挡住」，以及机器一天只开两趟
带来的那个时效窗——指令要能在信箱里等到下次开机。

    Formerly test_phone.py.
    """
    import json
    import time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.phone import MAX_AGE, pack, unpack

    PIN = "8964"
    FAILED: list[str] = []


    def check(what, got, want):
        if got != want:
            FAILED.append(f"{what}: 得到 {got!r}，应为 {want!r}")


    def main() -> int:
        raw = pack(PIN, {"action": "skip_shutdown"})
        msg = unpack(PIN, raw)
        check("自己发自己收", msg and msg["body"], {"action": "skip_shutdown"})
        check("带上类型", msg and msg["kind"], "cmd")

        check("PIN 不对，丢弃", unpack("1234", raw), None)
        check("没有 PIN 字段，丢弃", unpack(PIN, '{"kind":"cmd","body":{}}'), None)
        check("根本不是 JSON，丢弃", unpack(PIN, "hello"), None)
        check("是 JSON 但不是对象，丢弃", unpack(PIN, "[1,2,3]"), None)

        def stamped(age_s):
            d = json.loads(raw)
            d["ts"] = int(time.time()) - age_s
            return json.dumps(d, ensure_ascii=False)

        check("超过 24 小时的指令，丢弃", unpack(PIN, stamped(MAX_AGE + 60)), None)
        check("等了 11 小时还算数（机器一天只开两趟）",
              bool(unpack(PIN, stamped(11 * 3600))), True)
        check("时间戳不是整数，丢弃",
              unpack(PIN, json.dumps({**json.loads(raw), "ts": "刚刚"})), None)

        st = unpack(PIN, pack(PIN, {"stage": "1-7"}, kind="state"))
        check("状态消息的类型是 state，取指令时不会被当指令执行",
              st and st["kind"], "state")

        print("all checks passed" if not FAILED else "FAILED: " + "; ".join(FAILED))
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_phone_channel_boot():
    """phone_channel._start_phone_channel: the one state WARNING says why, a missed boot read is read again.

Two lines of the 10-06 sweep came from here:
* #42 #47 #48 「状态没能上报到手机（开机；今天 ntfy 已发 0 条）」 - no reason, and a
  count that disagreed with ntfy's own 42908. Now the line is written only
  when the phone cannot see the state at all (phone.Mailbox.publish) and
  carries Mailbox.last_error;
* #41 a boot mailbox read that timed out lost the presses made while the
  machine was off. The listener now reads it again (on_backlog), through the
  same boot_backlog filter and the same single folded state push as at boot.
Every WARNING is pushed to the group now (2026-10-06). Fakes for the mailbox,
the heartbeat and win32; no network, no thread left running.

    Formerly test_phone_channel_boot.py.
    """
    import logging
    import time
    import types
    from datetime import datetime, timezone

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                 "win32com", "win32com.client"):
        sys.modules.setdefault(name, _Stub(name))

    import boot_stages
    from ark_relay.features import phone as phone_channel
    from ark_relay.features import phone


    class Logs(logging.Handler):
        def __init__(self):
            super().__init__()
            self.recs: list[tuple[int, str]] = []

        def emit(self, record):
            self.recs.append((record.levelno, record.getMessage()))


    WHY = "腾讯云 COS 没存上（回 403），ntfy 也没发出去（ntfy 回 502（试了 2 次））"
    boxes: list = []


    class FakeBox:
        def __init__(self, topic, pin, state_dir, cos=None):
            self.topic, self.cos, self.enabled = topic, cos, True
            self.quota = phone.Quota(state_dir)
            self.last_error = WHY
            self.listened: dict = {}
            boxes.append(self)

        def publish(self, body):
            return False

        def fetch(self):
            return []

        def listen(self, on_cmd, stop, **kw):
            self.listened = {"on_cmd": on_cmd, **kw}


    class FakeHb:
        def __init__(self, *a, **k):
            pass

        def loop(self, stop):
            return None

        def watch(self):
            pass


    ran: list = []


    def fake_make_phone_cmd(*a, **k):
        def run(body):
            ran.append(body)
        run.drain = lambda: None
        return run


    saved = (phone.Mailbox, phone.Heartbeat, phone.state_payload, boot_stages.ensure_automas,
             phone_channel._make_phone_cmd)
    phone.Mailbox, phone.Heartbeat = FakeBox, FakeHb
    phone_channel._make_phone_cmd = fake_make_phone_cmd
    phone.state_payload = lambda cfg, state_dir: {"at": 1}
    boot_stages.ensure_automas = lambda *a, **k: True
    logs = Logs()
    log = logging.getLogger("ark.test_phone")
    log.addHandler(logs)
    log.setLevel(logging.DEBUG)
    log.propagate = False
    try:
        sd = tmpdir()
        cfg = types.SimpleNamespace(phone_topic="topic-abc", phone_pin="8964", state_dir=sd,
                                    cos_secret_id="", cos_secret_key="", cos_bucket="", cos_region="")
        svc = types.SimpleNamespace(stop_event=None)
        started = datetime.now(timezone.utc)
        engine = types.SimpleNamespace(scripts_running=lambda: False, _started_at=started)
        notifier = types.SimpleNamespace(send=lambda *a, **k: True)
        phone_channel._start_phone_channel(svc, cfg, engine, notifier, log)
        for _ in range(100):           # the listener thread records its call at once
            if boxes and boxes[0].listened:
                break
            time.sleep(0.01)
        box = boxes[0]

        print("[开机那份状态没送到：一条 WARNING，带原因]")
        warns = [m for lv, m in logs.recs if lv >= logging.WARNING]
        check("一条", len(warns), 1)
        check("……写了是哪一份、为什么", ("（开机）" in (warns or [""])[0], WHY in (warns or [""])[0]), (True, True))

        print("\n[开机读信箱没成：手机通道连上后补读，走开机积压那条路]")
        on_backlog = box.listened.get("on_backlog")
        check("监听线程拿到了 on_backlog", callable(on_backlog), True)
        logs.recs.clear()
        if callable(on_backlog):
            on_backlog([{"action": "estop", "_meta": {"via": "backlog"}}])
        check("补读到的红按钮同样不执行（boot_backlog 的规矩）",
              any("开机不执行" in m for _, m in logs.recs), True)
        check("……and is not run", ran, [])

        print("\n[late backlog: a red button pressed after this process started runs (audit A2)]")
        # The boot read timed out, the phone reached ntfy from another network while a
        # queue ran; the press came back through the late backlog and was dropped.
        logs.recs.clear()
        t0 = started.timestamp()
        if callable(on_backlog):
            on_backlog([{"action": "estop", "_meta": {"via": "backlog", "ntfy_time": int(t0) - 60}},
                        {"action": "estop", "_meta": {"via": "backlog", "ntfy_time": int(t0) + 60}}])
        check("the press made while on is run", [b["_meta"]["ntfy_time"] for b in ran], [int(t0) + 60])
        check("the press made before the start is still dropped",
              sum("开机不执行" in m for _, m in logs.recs), 1)
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ {type(exc).__name__}: {exc}")
        fails.append(type(exc).__name__)
    finally:
        (phone.Mailbox, phone.Heartbeat, phone.state_payload, boot_stages.ensure_automas,
         phone_channel._make_phone_cmd) = saved

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_phone_cmd_gate():
    """The one button that is only ever pressed while a run is going must not be gated.

Everything the phone can change goes through one gate: 「a script is running, so
writing config now would be clobbered by AUTO-MAS's in-memory copy」. That is
correct for the settings AUTO-MAS owns, and wrong for the two switches that live
in the relay's own StateStore - 「下次跑完不关机」 above all, which is pressed
*because* a run is going. It was refused every time it mattered, and the message
said to press it again after the run, by which time the machine has powered off.

Every other order pressed during a run waits on disk for the run to end
(phone.CmdQueue; test_phone_cmd_queue.py pins the queue itself). Until
2026-10-05 it was dropped with a 「等这一趟跑完再按一次」 push instead.

    Formerly test_phone_cmd_gate.py.
    """
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    # service.py imports pywin32 at module scope; stub what is missing so the
    # module-level helpers can be imported on any machine.
    class _Any:
        """Stands in for any pywin32 attribute: callable, subclassable, truthy."""
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    import os
    # cfg_state_dir is None below, so the queue falls back to ARK_STATE_DIR.
    os.environ["ARK_STATE_DIR"] = str(tmpdir())
    import ark_relay.features.commands as C
    import boot_stages
    from ark_relay.features import phone as phone_channel
    from ark_relay.core import texts


    class Eng:
        def __init__(self, busy):
            self.busy = busy

        def scripts_running(self):
            return self.busy


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return False


    class Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def exception(self, *a, **k): pass


    class HB:
        def watch(self): pass


    def run(action, busy, applied):
        notes = Notes()
        real = C.apply_command
        # _make_phone_cmd binds apply_command into its closure, so the module
        # attribute has to be swapped before the closure is built.
        C.apply_command = lambda body: (applied.append(body["action"]), (True, "改好了"))[1]
        try:
            fn = phone_channel._make_phone_cmd(Eng(busy), notes, Log(), HB(), lambda *_: None)
            fn({"action": action, "confirmed": True})
        finally:
            C.apply_command = real
        return notes


    print("[跑着的时候：改 AUTO-MAS 的设置先排队，不当场改]")
    applied = []
    n = run("set_config", busy=True, applied=applied)
    check("没有真去改", applied, [])
    check("什么也没推（不再叫他「跑完再按一次」）", n.sent, [])
    from ark_relay.features import phone as _ph
    _q = _ph.CmdQueue(os.environ["ARK_STATE_DIR"])
    check("排进了队列", [i["body"]["action"] for i in _q._read()["items"]], ["set_config"])
    _q.path.unlink()

    print("\n[跑着的时候：「下次跑完不关机」必须放行——它只有这时候按才有意义]")
    applied = []
    n = run("skip_shutdown", busy=True, applied=applied)
    check("真的执行了", applied, ["skip_shutdown"])
    check("没有排队", len(_q), 0)

    print("\n[调试模式同理：它写的也是中继自己的状态]")
    applied = []
    run("debug_mode", busy=True, applied=applied)
    check("真的执行了", applied, ["debug_mode"])

    print("\n[没在跑的时候，什么都照常]")
    applied = []
    run("set_config", busy=False, applied=applied)
    check("改设置执行了", applied, ["set_config"])

    print("\n[开机读信箱积压：关机期间按的红按钮不执行，其余照常]")
    # 2026-09-19 17:5x the red button was pressed on the phone page while the machine
    # had been off since 14:47; the 21:20 boot would have read it back and fired it
    # against nothing, minutes before the 21:30 queue.
    _recorded = []
    class _Log:
        def warning(self, fmt, *a): _recorded.append(fmt % a)
        def info(self, fmt, *a): pass
    backlog = [{"action": "estop"}, {"action": "skip_shutdown", "on": True}, {"action": "estop"}, {"action": "refresh"}]
    kept = phone_channel.boot_backlog(backlog, _Log())
    check("红按钮全部丢掉，别的按原顺序留下", [b["action"] for b in kept], ["skip_shutdown", "refresh"])
    check("每丢一条记一行", len(_recorded), 2)
    check("说清是关机期间按的、开机不执行", "关机期间" in _recorded[0] and "开机不执行" in _recorded[0], True)
    check("空积压照样是空的", phone_channel.boot_backlog([], _Log()), [])
    check("红按钮是唯一的 live-only 动作（活着时照旧立刻执行）", phone_channel.LIVE_ONLY_ACTIONS, ("estop",))

    print("\n[刷新：一份状态已经答过就不再发（ntfy 每天 250 条，一份状态 4 条）]")
    # 2026-10-02 19:19 the quota ran out: the App re-asks 4 s after every refresh and
    # each ask bought a whole state (17:02:23 / 17:02:31, 18:30:05 / 18:30:12); the
    # refreshes pressed while the machine was off replayed one by one at boot
    # (09-30 08:46:03-08:47:44, eleven states).
    import time as _time
    from ark_relay.features import phone as _phone
    _pushed = []
    _pusher = _phone.StatePusher(lambda why: _pushed.append(why) or True)
    _real_ensure = boot_stages.ensure_automas
    _ensured = []
    boot_stages.ensure_automas = lambda *a, **k: _ensured.append(1) or True
    try:
        _fn = phone_channel._make_phone_cmd(Eng(False), Notes(), Log(), HB(), _pusher)
        _fn({"action": "refresh", "_meta": {"ntfy_time": int(_time.time())}})
        check("第一次刷新照常答一份", _pushed, ["手机请求"])
        _fn({"action": "refresh", "_meta": {"ntfy_time": int(_time.time()) + 4}})
        check("4 秒后补问的那次：刚发的那份答了，不再发", _pushed, ["手机请求"])
        check("没再发也就不用去拉 AUTO-MAS", len(_ensured), 1)
        _fn({"action": "refresh", "_meta": {"ntfy_time": int(_time.time()) - 5 * 3600}})
        check("关机时按的（开机才读到）：开机那份已经答了", _pushed, ["手机请求"])
        _pusher._done -= _phone.REFRESH_ANSWERED_SEC + 5
        _fn({"action": "refresh", "_meta": {"ntfy_time": int(_time.time())}})
        check("隔久了再按：照常答", _pushed, ["手机请求", "手机请求"])
        # A plain push_state (a lambda, no `answered`) still answers every time
        _plain = []
        phone_channel._make_phone_cmd(Eng(False), Notes(), Log(), HB(),
                                    lambda why: _plain.append(why))({"action": "refresh"})
        check("普通的 push_state 照旧能用", _plain, ["手机请求"])

        print("\n[开机积压：几条改配置合成一份状态]")
        _pushed.clear()
        real = C.apply_command
        C.apply_command = lambda body: (True, "改好了")
        try:
            _fn = phone_channel._make_phone_cmd(Eng(False), Notes(), Log(), HB(), _pusher)
            with _pusher.held():
                for _b in ({"action": "set_config"}, {"action": "skip_shutdown", "on": True},
                           {"action": "refresh", "_meta": {"ntfy_time": 0}}):
                    _fn(_b)
        finally:
            C.apply_command = real
        check("两条改配置 + 一条旧刷新 = 一份状态", _pushed, ["改完配置（2 次合成一次）"])
    finally:
        boot_stages.ensure_automas = _real_ensure

    print("\n[每一个能按的按钮都有中文名字]")
    missing = [a for a in ("set_stage", "set_medicine", "set_wait_time", "toggle_task",
                           "run_now", "skip_today", "debug_mode", "set_config",
                           "set_master", "weekly_boss", "skip_shutdown",
                           "refresh", "watch", "queue", "sanity_plan")
               if texts.action_name(a) == "这条设置"]
    check("没有漏掉的", missing, [])


def _part_phone_cmd_queue():
    """A phone order pressed while a script runs waits for the run to end - it is not dropped.

Until 2026-10-05 every order but 「下次跑完不关机」 / 调试模式 that arrived during a
run got a 「等这一趟跑完再按一次」 push and nothing else: no receipt, and its
message id was already recorded as handled (phone.Mailbox.listen), so no later
boot ever ran it - while the App told the user the change was
「推迟到跑完再生效」. Pinned here:

* during a run the order goes to disk (phone.CmdQueue), is not applied, and
  nothing is pushed to the group or Server酱;
* once nothing runs, the queue is applied in arrival order through the same
  apply_command, each with its receipt, and one state is pushed;
* the queue survives a relay restart;
* the existing expiry rules hold at drain time (24 h from the send; skip_today's
  own `day`), an expired order gets a failure receipt and is not applied;
* the same message id is queued and run once;
* D207: the moment an order is queued a receipt {queued: true, ok: true,
  「排队中，这一趟跑完执行」} is written and one state pushed; the final receipt
  after the run has no "queued"; pressing the same order (same action and
  content) again while it waits does not queue it twice but gets its own
  queued receipt, and the final receipt carries the latest send time;
  a different content queues on its own; 「开 → 关 → 开」 still ends on 开;
* skip_shutdown / debug_mode still act at once;
* Engine.tick drains before its shutdown decision;
* an order that starts a run (「现在跑」, 开始刷声骸) is never queued: pressed
  during a run it is answered at once - 「这时正在跑，这一趟就是」 - because applied
  after the run it would start the whole queue once more (2026-09-01, MAA ran
  twice and ate sanity potions); no push;
* applying any order drops engine's 3-second 「is anything running」 cache.

    Formerly test_phone_cmd_queue.py.
    """
    import os
    import time
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))


    os.environ.update(ARK_STATE_DIR=str(tmpdir()), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    import ark_relay.features.commands as C
    from ark_relay.features import phone as phone_channel
    from ark_relay.features import modes
    from ark_relay.features import phone
    from ark_relay.core.config import SERVER_TZ


    class Eng:
        def __init__(self, busy):
            self.busy = busy

        def scripts_running(self):
            return self.busy


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return False


    class Log:
        def __init__(self):
            self.lines = []

        def _rec(self, fmt, *a, **k):
            self.lines.append(fmt % a if a else fmt)

        info = warning = debug = _rec

        def exception(self, fmt, *a, **k):
            self.lines.append("EXC " + (fmt % a if a else fmt))


    class HB:
        def watch(self): pass


    APPLIED: list = []


    def fake_apply(body):
        APPLIED.append(body["action"] + (f":{body['value']}" if "value" in body else ""))
        assert "_meta" not in body, "apply_command must never see _meta"
        return True, f"改好了 {body.get('value', '')}".strip()


    def order(action, mid, sent=None, **kw):
        """An order as phone.stamp hands it over."""
        body = {"action": action, "confirmed": True, **kw}
        body["_meta"] = {"sent": int(time.time()) if sent is None else sent,
                         "ntfy_time": int(time.time()), "ntfy_id": mid, "via": "live"}
        return body


    def make(engine, state_dir, notes=None, pushed=None, log=None):
        """A fresh run_phone_cmd: building it again on the same dir is a relay restart."""
        pusher = phone.StatePusher(lambda why: (pushed.append(why) if pushed is not None else None) or True)
        return phone_channel._make_phone_cmd(engine, notes or Notes(), log or Log(), HB(), pusher, state_dir)


    REAL_APPLY = C.apply_command
    C.apply_command = fake_apply      # bound into the closure when _make_phone_cmd runs

    print("[跑着的时候：改设置落盘排队，不当场改，什么都不推]")
    d = tmpdir()
    eng = Eng(busy=True)
    notes, pushed, lg = Notes(), [], Log()
    fn = make(eng, d, notes, pushed, lg)
    APPLIED.clear()
    fn(order("set_config", "m1", value="1-7"))
    fn(order("skip_today", "m2", queue="晚班", day="2026-10-05"))
    fn(order("toggle_task", "m3", name="基建", on=True))
    check("一条也没执行", APPLIED, [])
    check("群 / Server酱 什么都没推", notes.sent, [])
    rq = modes.receipts(d)
    check("每条一张「排队中」回执（D207）", [(r["action"], r["ok"], r.get("queued")) for r in rq],
          [("set_config", True, True), ("skip_today", True, True), ("toggle_task", True, True)])
    check("排队回执的话", {r["text"] for r in rq}, {"排队中，这一趟跑完执行"})
    check("排队回执带发出时间（App 按它对上是哪一次按的）", all("sent" in r for r in rq), True)
    check("每次排队推一次状态，App 马上看到", pushed, ["指令排队"] * 3)
    q = phone.CmdQueue(d)
    check("三条按到达顺序落在盘上", [i["body"]["action"] for i in q._read()["items"]],
          ["set_config", "skip_today", "toggle_task"])
    check("落盘的带着 _meta（回执要 sent，去重要 id）",
          q._read()["items"][0]["body"]["_meta"]["ntfy_id"], "m1")
    check("日志说了排队", any("排队" in x for x in lg.lines), True)

    print("\n[同一条消息 id 只排一次]")
    fn(order("set_config", "m1", value="1-7"))
    check("还是三条", len(q), 3)
    check("同一条消息再到不再写排队回执", len(modes.receipts(d)), 3)

    print("\n[还在跑时到了 tick：不动]")
    check("drain 一条没跑", fn.drain(), 0)
    check("还是三条", len(q), 3)

    print("\n[中继重启：队列还在，跑完后按顺序执行]")
    eng2 = Eng(busy=False)
    notes2, pushed2 = Notes(), []
    fn2 = make(eng2, d, notes2, pushed2)
    APPLIED.clear()
    check("跑了三条", fn2.drain(), 3)
    check("按到达顺序走同一个 apply_command", APPLIED, ["set_config:1-7", "skip_today", "toggle_task"])
    rc = [r for r in modes.receipts(d) if not r.get("queued")]
    check("每条一张最终回执", [(r["action"], r["ok"]) for r in rc],
          [("set_config", True), ("skip_today", True), ("toggle_task", True)])
    check("最终回执不带 queued", any("queued" in r for r in rc), False)
    check("最终回执排在排队回执后面", [r.get("queued", False) for r in modes.receipts(d)],
          [True, True, True, False, False, False])
    check("回执带发出时间", all("sent" in r for r in rc), True)
    check("三条合成一份状态", pushed2, ["改完配置（3 次合成一次）"])
    check("群 / Server酱 什么都没推", notes2.sent, [])
    check("队列空了", len(q), 0)

    print("\n[执行过的 id 再来一次：不再排、不再跑]")
    eng2.busy = True
    APPLIED.clear()
    fn2(order("set_config", "m1", value="1-7"))
    check("没排进去", len(q), 0)
    eng2.busy = False
    fn2.drain()
    check("没再执行", APPLIED, [])

    print("\n[过期：发出超过 24 小时才轮到它——不执行，回执写明]")
    d3 = tmpdir()
    eng3 = Eng(busy=True)
    fn3 = make(eng3, d3)
    old = int(time.time()) - phone.MAX_AGE - 60
    fn3(order("set_config", "x1", sent=old, value="TO-5"))
    eng3.busy = False
    APPLIED.clear()
    fn3.drain()
    check("没执行", APPLIED, [])
    rc3 = [r for r in modes.receipts(d3) if not r.get("queued")]   # after its 「排队中」 one
    check("一张失败回执", [(r["action"], r["ok"]) for r in rc3], [("set_config", False)])
    check("回执用人话说过期了", "过期没执行" in rc3[0]["text"] and "24 小时" in rc3[0]["text"], True)

    print("\n[skip_today 指定的那天已过：走它自己原有的过期判断，失败回执]")
    C.apply_command = REAL_APPLY            # the real one: its own `day` check decides
    d4 = tmpdir()
    os.environ["ARK_STATE_DIR"] = str(d4)
    eng4 = Eng(busy=True)
    fn4 = make(eng4, d4)
    yesterday = (datetime.now(tz=SERVER_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    fn4(order("skip_today", "y1", queue="晚班", day=yesterday))
    eng4.busy = False
    fn4.drain()
    rc4 = [r for r in modes.receipts(d4) if not r.get("queued")]
    check("一张失败回执", [(r["action"], r["ok"]) for r in rc4], [("skip_today", False)])
    check("说的是那天已过", "过期" in rc4[0]["text"], True)
    check("没跳过任何队列", list(modes.skipped_today_all(d4)), [])
    C.apply_command = fake_apply

    print("\n[跑着的时候：下次跑完不关机 / 调试模式照旧当场执行]")
    d5 = tmpdir()
    eng5 = Eng(busy=True)
    fn5 = make(eng5, d5)
    APPLIED.clear()
    fn5(order("skip_shutdown", "s1", on=True))
    fn5(order("debug_mode", "s2"))
    check("两条都当场执行了", APPLIED, ["skip_shutdown", "debug_mode"])
    check("没有排队", len(phone.CmdQueue(d5)), 0)

    print("\n[没在跑但前面还有排着的：新来的排在后面，一起按顺序跑]")
    d6 = tmpdir()
    eng6 = Eng(busy=True)
    fn6 = make(eng6, d6)
    APPLIED.clear()
    fn6(order("set_config", "a1", value="A"))
    eng6.busy = False
    # Scripts stopped but no tick has drained yet; a new order arrives first.
    fn6(order("set_config", "a2", value="B"))
    check("先 A 后 B", APPLIED, ["set_config:A", "set_config:B"])
    check("队列空了", len(phone.CmdQueue(d6)), 0)

    print("\n[跑到一半又开跑：剩下的继续等]")
    d7 = tmpdir()
    eng7 = Eng(busy=True)
    fn7 = make(eng7, d7)
    for i in range(3):
        fn7(order("set_config", f"b{i}", value=str(i)))
    APPLIED.clear()
    def _apply_then_busy(body):
        out = fake_apply(body)
        eng7.busy = True          # a queue started right after the first order
        return out


    eng7.busy = False
    C.apply_command = _apply_then_busy
    fn7 = make(eng7, d7)
    fn7.drain()
    C.apply_command = fake_apply
    check("只跑了第一条", APPLIED, ["set_config:0"])
    check("剩两条还在盘上", len(phone.CmdQueue(d7)), 2)

    print("\n[Engine.tick：先跑排队的手机指令，再做模式和关机判断]")
    from ark_relay.core import engine as engmod
    from ark_relay.core.config import Config
    from ark_relay.core.ledger import State

    cfg = Config()
    cfg.state_dir = tmpdir()
    E = engmod.Engine(cfg, source=types.SimpleNamespace(fetch=lambda seen: []),
                      state=State(cfg.state_dir), notifier=Notes())
    E._scripts_running = lambda: False
    calls = []
    STEPS = ("_echo_farm_deadline", "_run_watch", "_flush_pending",
             "_weekly_gates", "_monthcard_notice", "_check_missed_runs",
             "_maybe_interim_report", "_maybe_deferred_update", "_maybe_daily_report")
    for name in STEPS:
        setattr(E, name, lambda *a, **k: None)
    E._observe_modes = lambda: calls.append("modes")

    # The real drain, wired the way boot_stages wires it.
    d8 = tmpdir()
    eng8 = Eng(busy=True)
    fn8 = make(eng8, d8)
    fn8(order("set_config", "r1", value="1-7"))
    eng8.busy = False
    E._phone_drain = lambda: calls.append("drain:" + str(fn8.drain()))
    seen_at_shutdown = []
    E._maybe_shutdown = lambda *a, **k: (calls.append("shutdown"), seen_at_shutdown.append(list(APPLIED)))
    APPLIED.clear()
    E.tick()
    check("顺序：排队指令 → 模式 → 关机判断", calls, ["drain:1", "modes", "shutdown"])
    check("关机判断时那条设置已经改了", seen_at_shutdown, [["set_config:1-7"]])

    print("\n[跑着的时候按「现在跑」/「开始刷声骸」：不排队，当场回「这时正在跑」，不推群]")
    d10 = tmpdir()
    eng10 = Eng(busy=True)
    notes10, pushed10, lg10 = Notes(), [], Log()
    fn10 = make(eng10, d10, notes10, pushed10, lg10)
    APPLIED.clear()
    fn10(order("run_now", "n1", queue="早班"))
    fn10(order("echo_farm", "n2", boss=3, until="08:30"))
    check("一条也没执行", APPLIED, [])
    check("没排队", len(phone.CmdQueue(d10)), 0)
    rc10 = modes.receipts(d10)
    check("两张失败回执", [(r["action"], r["ok"]) for r in rc10], [("run_now", False), ("echo_farm", False)])
    check("「现在跑」的回执：这时正在跑，这一趟就是",
          rc10[0]["text"], "「现在就跑一趟」没执行：这时正在跑，这一趟就是")
    check("「开始刷声骸」的回执说跑完不会接着开", "跑完不会接着开" in rc10[1]["text"], True)
    check("群 / Server酱 什么都没推", notes10.sent, [])
    check("推了状态，页面看得到回执", len(pushed10) >= 1, True)
    eng10.busy = False
    check("跑完了也不会再补一趟", (fn10.drain(), APPLIED), (0, []))

    print("\n[没在跑、前面还有排着的设置：先改设置，再当场跑「现在跑」]")
    d11 = tmpdir()
    eng11 = Eng(busy=True)
    fn11 = make(eng11, d11)
    APPLIED.clear()
    fn11(order("set_config", "p1", value="1-7"))
    eng11.busy = False
    fn11(order("run_now", "p2", queue="早班"))
    check("先设置后开跑", APPLIED, ["set_config:1-7", "run_now"])
    check("队列空了", len(phone.CmdQueue(d11)), 0)

    print("\n[盘上留着一条旧的「现在跑」（规则改之前排的）：跑完时不执行，回执说明]")
    d12 = tmpdir()
    phone.CmdQueue(d12).add(order("run_now", "q1", queue="早班"))
    fn12 = make(Eng(busy=False), d12)
    APPLIED.clear()
    check("算处理了一条", fn12.drain(), 1)
    check("没开跑", APPLIED, [])
    check("失败回执", [(r["action"], r["ok"]) for r in modes.receipts(d12)], [("run_now", False)])

    print("\n[执行了指令就让「有没有在跑」的三秒缓存作废，同一轮的关机判断重新问]")
    d13 = tmpdir()
    eng13 = Eng(busy=True)
    fn13 = make(eng13, d13)
    fn13(order("set_config", "c1", value="1-7"))
    eng13.busy = False
    engmod._SCRIPTS_CACHE.update(at=time.monotonic(), val=False)
    fn13.drain()
    check("排队的执行后缓存作废", engmod._SCRIPTS_CACHE["at"] < 0, True)
    engmod._SCRIPTS_CACHE.update(at=time.monotonic(), val=False)
    fn13(order("set_config", "c2", value="1-8"))
    check("当场执行的也一样", engmod._SCRIPTS_CACHE["at"] < 0, True)

    print("\n[排队那段炸了，也不许带走整轮]")
    calls.clear()
    E._phone_drain = lambda: (_ for _ in ()).throw(RuntimeError("队列文件读坏了"))
    try:
        E.tick()
        check("tick 没把异常抛出去", True, True)
    except Exception as exc:  # noqa: BLE001
        check(f"tick 没把异常抛出去（抛了 {exc}）", False, True)
    check("后面照样到了关机判断", calls, ["modes", "shutdown"])

    print("\n[没接手机通道（单测 / 没配 topic）：tick 照旧]")
    calls.clear()
    E._phone_drain = None
    E.tick()
    check("照旧", calls, ["modes", "shutdown"])

    print("\n[坏掉的队列文件：当空的，不抛]")
    d9 = tmpdir()
    (d9 / phone.CMD_QUEUE_FILE).write_text("{坏的", encoding="utf-8")
    check("读成空", len(phone.CmdQueue(d9)), 0)
    check("还能接着排", phone.CmdQueue(d9).add(order("set_config", "z1", value="1")), phone.QUEUED)
    check("排进去了", len(phone.CmdQueue(d9)), 1)


    print("\n[D207：排着的时候同一条（action + 内容一样）又按一次：不重复排，这次也有排队回执]")
    d14 = tmpdir()
    eng14 = Eng(busy=True)
    pushed14 = []
    fn14 = make(eng14, d14, pushed=pushed14)
    t0 = int(time.time()) - 600
    fn14(order("set_config", "e1", sent=t0, value="1-7"))
    fn14(order("set_config", "e2", sent=t0 + 300, value="1-7"))
    q14 = phone.CmdQueue(d14)
    check("只排了一条", len(q14), 1)
    rq14 = modes.receipts(d14)
    check("两次按各有一张排队回执", [(r.get("queued"), r["sent"]) for r in rq14],
          [(True, datetime.fromtimestamp(t0, tz=SERVER_TZ).strftime("%m-%d %H:%M")),
           (True, datetime.fromtimestamp(t0 + 300, tz=SERVER_TZ).strftime("%m-%d %H:%M"))])
    check("两次都推了状态", pushed14, ["指令排队", "指令排队"])
    fn14(order("set_config", "e3", value="TO-5"))
    check("内容不同的另排一条", len(q14), 2)
    eng14.busy = False
    APPLIED.clear()
    fn14.drain()
    check("执行两条，同一条只执行一次", APPLIED, ["set_config:1-7", "set_config:TO-5"])
    fin14 = [r for r in modes.receipts(d14) if not r.get("queued")]
    check("最终回执两张、都不带 queued", [(r["action"], r["ok"], "queued" in r) for r in fin14],
          [("set_config", True, False), ("set_config", True, False)])
    check("第一张最终回执带最后一次按的发出时间（两次按都对得上）", fin14[0]["sent"],
          datetime.fromtimestamp(t0 + 300, tz=SERVER_TZ).strftime("%m-%d %H:%M"))
    eng14.busy = True
    APPLIED.clear()
    fn14(order("set_config", "e2", sent=t0 + 300, value="1-7"))
    eng14.busy = False
    fn14.drain()
    check("折进去的那次按，消息再到也不再执行", APPLIED, [])

    print("\n[D207：只和同一动作最近排着的那条比：开 → 关 → 开 最后是开]")
    d15 = tmpdir()
    fn15 = make(Eng(busy=True), d15)
    fn15(order("toggle_task", "f1", name="基建", on=True))
    fn15(order("toggle_task", "f2", name="基建", on=False))
    fn15(order("toggle_task", "f3", name="基建", on=True))
    check("三条都排上", [i["body"]["on"] for i in phone.CmdQueue(d15)._read()["items"]], [True, False, True])
    fn15(order("toggle_task", "f4", name="基建", on=True))
    check("紧接着又按一次开：不再排", len(phone.CmdQueue(d15)), 3)

    print("\n[D207：没在跑、前面有排着的：直接执行，不写排队回执]")
    d16 = tmpdir()
    eng16 = Eng(busy=True)
    fn16 = make(eng16, d16)
    fn16(order("set_config", "g1", value="A"))
    eng16.busy = False
    fn16(order("set_config", "g2", value="B"))
    check("只有第一条有排队回执", [(r.get("queued", False), r["text"][:3]) for r in modes.receipts(d16)],
          [(True, "排队中"), (False, "改好了"), (False, "改好了")])


    print("\n[D207：排队回执原样进推给 App 的状态（relay.最近指令），queued 跟着出去]")
    from ark_relay.core import plan as _plan
    from ark_relay.features import snapshot as _snap
    _saved = (_snap.read, _plan.next_plan)
    _snap.read, _plan.next_plan = (lambda: {}), (lambda automas_dir: "")
    try:
        st = phone.state_payload(types.SimpleNamespace(automas_dir=str(tmpdir()), maaend_dir=str(tmpdir()),
                                                       okww_dir=str(tmpdir())), d14)
    finally:
        _snap.read, _plan.next_plan = _saved
    recent = st["relay"]["最近指令"]
    check("状态里的回执和盘上一样", recent, modes.receipts(d14))
    check("排队回执带 queued: true 出去", [r.get("queued") for r in recent if r.get("queued")], [True, True, True])


def _part_phone_drained_failure_pushed():
    """A phone order that waited for the run and then failed goes to the group too.

Found while writing the machine check #23 (machinechecks/phone_banners.py): an
order pressed during a run waits in phone.CmdQueue and is applied by drain()
with notify=False, and phone_channel._phone_execute pushed nothing at all then -
a failure after the run was only a red receipt on the phone page. The user's
rule of 2026-10-06 is every error to the group, every time (「不论多少次什么错误都要发」;
docs/NOTIFICATIONS.md, the 「📱 配置没改成」 row: his phone order failed - the
group). A drained order that went through still pushes nothing: the receipt is
the answer.

    Formerly test_phone_drained_failure_pushed.py.
    """
    import os
    import time
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(_name, _Stub(_name))


    os.environ.update(ARK_STATE_DIR=str(tmpdir()), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    import ark_relay.features.commands as C
    from ark_relay.features import phone as phone_channel
    from ark_relay.features import modes
    from ark_relay.features import phone
    from ark_relay.core import texts
    from ark_relay.core.notify import route_of


    class Eng:
        def __init__(self, busy):
            self.busy = busy

        def scripts_running(self):
            return self.busy


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", alert=False, **kw):
            self.sent.append((title, body, alert))
            return []


    class Log:
        def _rec(self, *a, **k):
            pass

        info = warning = debug = exception = _rec


    class HB:
        def watch(self):
            pass


    def order(action, mid, **kw):
        body = {"action": action, "confirmed": True, **kw}
        body["_meta"] = {"sent": int(time.time()), "ntfy_time": int(time.time()), "ntfy_id": mid, "via": "live"}
        return body


    real = C.apply_command
    C.apply_command = lambda body: ((False, "刷取关卡：找不到 TO-9") if body.get("value") == "TO-9"
                                    else (True, f"刷取关卡：{body.get('value')}"))
    try:
        d = tmpdir()
        eng, notes = Eng(True), Notes()
        fn = phone_channel._make_phone_cmd(eng, notes, Log(), HB(), phone.StatePusher(lambda why: True), d)
        fn(order("set_config", "m1", value="TO-9"))
        fn(order("set_config", "m2", value="1-7"))
        print("[跑着的时候：排队，什么都不推]")
        check("没推", notes.sent, [])
        eng.busy = False
        fn.drain()
        print("\n[跑完执行：没改成的那条进群，改成的那条不推]")
        check("推了一条「配置没改成」", [t for t, _b, _a in notes.sent], [texts.CONFIG_FAILED])
        check("带 alert=True，走群", [(a, route_of(t, alert=a)) for t, _b, a in notes.sent], [(True, "group")])
        check("正文是那条指令自己的回答", [b for _t, b, _a in notes.sent], ["刷取关卡：找不到 TO-9"])
        check("两张最终回执照旧", [(r["action"], r["ok"]) for r in modes.receipts(d) if not r.get("queued")],
              [("set_config", False), ("set_config", True)])
    finally:
        C.apply_command = real

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_phone_gzip():
    """状态包超限时压缩，而不是砍字段。

2026-08-31 量到整包 3783 字节，上限 3900，**只剩 117 字节余量**。
超线时原来的处理是先砍「明日安排」、再砍「选项表」——而选项表正是手机上
那一堆中文下拉候选，占了整包 57%。砍掉等于功能没了，而且不出声地没了。
压缩后 2464 字节，余量回到一千多。

发的那头只在明文会超限时才压，收的那头两种都认，
所以手机上就算跑的是旧页面也不会突然读不懂。

    Formerly test_phone_gzip.py.
    """
    import json, sys, time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import phone


    PIN = "8964"
    BODY = {"options": {f"键{i}": ["候选甲", "候选乙", "候选丙"] for i in range(60)},
            "plan": "明日安排" * 30, "at": 1}

    print("\n[往返]")
    # 断言只印真假——BODY 有六十个键，整份印出来把日志淹了
    check("明文解得回来",
          phone.unpack(PIN, phone.pack(PIN, BODY, "state"))["body"] == BODY, True)
    check("压缩解得回来",
          phone.unpack(PIN, phone.pack(PIN, BODY, "state", gz=True))["body"] == BODY, True)

    print("\n[压缩确实更小]")
    plain = len(phone.pack(PIN, BODY, "state").encode())
    gz = len(phone.pack(PIN, BODY, "state", gz=True).encode())
    check("压完不到明文一半", gz * 2 < plain, True)
    print(f"       明文 {plain} 字节 → 压缩 {gz} 字节")

    print("\n[坏包不许当好包]")
    bad = json.dumps({"v": 1, "kind": "state", "pin": PIN,
                      "ts": int(time.time()), "gz": "这不是 base64"})
    check("解不开就丢弃", phone.unpack(PIN, bad), None)
    check("PIN 不对照旧拒", phone.unpack("0000", phone.pack(PIN, BODY, "state", gz=True)), None)

    print("\n[发的那头：不超限就别压]")
    small = phone.pack(PIN, {"at": 1}, "state").encode()
    check("小包保持明文（body 在、gz 不在）",
          ("body" in json.loads(small)) and ("gz" not in json.loads(small)), True)


def _part_phone_order_failed_pushed():
    """A phone order that did not take is an error, so it goes to the group (2026-10-06).

The user's order of 2026-10-06: every error goes to the group (「不论多少次什么错误都要发」).
Until then phone_channel._phone_execute sent 「📱 配置没改成」 without alert=True,
so it went to Server酱 only.

    Formerly test_phone_order_failed_pushed.py.
    """
    import logging

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import types


    class _Any:
        """Stands in for any pywin32 attribute (boot_stages pulls in service helpers)."""
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(_name, _Stub(_name))

    import os
    os.environ["ARK_STATE_DIR"] = str(tmpdir())
    from ark_relay.features import phone as phone_channel
    from ark_relay.core import texts
    from ark_relay.core.notify import route_of


    class FakeNotifier:
        def __init__(self):
            self.sent = []

        def send(self, title, body, alert=False, **kw):
            self.sent.append((title, body, alert))
            return []


    def run(ok):
        n = FakeNotifier()
        phone_channel._phone_execute(lambda body: (ok, "刷取关卡：找不到 TO-9" if not ok else "刷取关卡：TO-5"),
                                   n, logging.getLogger("ark.test_phone"), lambda *a, **k: None, lambda *a, **k: None,
                                   {"action": "set_stage"}, "set_stage", None, True)
        return n.sent


    print("[手机指令没改成：进群]")
    bad = run(False)
    check("推了一条「配置没改成」", [t for t, _, _ in bad], [texts.CONFIG_FAILED])
    check("带 alert=True", [a for _, _, a in bad], [True])
    check("走群", route_of(texts.CONFIG_FAILED, alert=bad[0][2]) if bad else None, "group")
    print("[改成了：只是回执，不进群]")
    good = run(True)
    check("推的是「配置已修改」", [t for t, _, _ in good], [texts.CONFIG_CHANGED])
    check("不带 alert", [a for _, _, a in good], [False])


def _part_phone_quiet():  # noqa: C901
    """The phone channel says WARNING only when something is wrong (2026-10-06).

Every WARNING the relay logs is now pushed to the group. The user, 10-06:
「你正常情况应该一条都不发的」. The 10-06 sweep of relay.log found the phone
channel behind most of them; each check below is one of those lines:

* #40 #52 #54 ntfy's 42908 (the day's 250 used up) was logged by every beat,
  every state, every piece and every restart's bye: now once per UTC day, and
  nothing is posted into a refused day;
* #42 #47 #48 a state stored on COS was logged 「状态没能上报到手机」 because the
  one-line notice after it was refused: stored on COS is delivered;
* #44 a timed-out post was a WARNING per try: one reason in last_error, the
  caller writes the one line, and only when the phone cannot see the state;
* #39 #49 a 429 (42901) or a 5xx was not retried, or retried without a pause:
  one more try after a pause, Retry-After honoured; 42908 / other 4xx never;
* #51 a lost piece dropped the rest with a WARNING: the piece is retried
  first, a set that still breaks is the caller's one line;
* #41 a boot mailbox read that timed out lost the presses made while the
  machine was off: read again by listen() once ntfy answers;
* #45 #49 #57 every dropped stream was a WARNING and the reconnect only
  replayed 10 minutes: drops are INFO and replay from the last line read; ten
  minutes down is one WARNING;
* #56 one COS heartbeat timeout was a WARNING: INFO (ntfy still beats);
* the ledger said 「今天 ntfy 已发 0 条」 beside ntfy's 42908: ntfy's own count
  (GET /v1/account) is taken in, and the relay stops itself short of 250.

Since the user's rule of 2026-10-06 05:07 (「报错后自己好了的，只进日报、不进群」)
a fault the relay got over is not silent either: ONE WARNING marked
errwatch.recovered() - not pushed, in the daily report's 「中继自己记下的报错」
- for a post that went through on its retry, a state one route refused and
the other carried, the boot mailbox read done late, a stream that dropped on a
fault (502, reset, no connection) and reconnected, a COS heartbeat written
again. An open stream that only timed out reading (idle) stays INFO. What did
not recover stays a plain WARNING, pushed: the day's quota, a state the phone
cannot get from anywhere (the caller's line), the channel or the COS
heartbeat down for 10 minutes. A real errwatch handler on the phone logger
shows what is pushed and what the daily report lists.
Fake network throughout; nothing waits for real.

    Formerly test_phone_quiet.py.
    """
    import io
    import json
    import logging
    import os
    import tempfile
    import time
    import types
    import urllib.error
    import urllib.request

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import errwatch
    from ark_relay.features import phone
    from ark_relay.core import texts
    from ark_relay.features import phone as phone_cos_store, phone as phone_heartbeat, phone as phone_mailbox, phone as phone_quota
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core import notify as netretry
    from ark_relay.features.evidence import Cos
    from datetime import datetime

    # A COS write or read the network cut short is tried again inside its own 8 s (netretry,
    # dispatch relay-opt-round3-1108 O-03): COS that is down answers every one of those attempts.
    netretry._sleep = lambda s: None
    DOWN = netretry.ATTEMPTS

    PIN = "8964"
    TOPIC = "topic-abc"
    COS = Cos("AKIDtest", "secret", "ark-evidence-1", "ap-shanghai")


    def section(title, fn):
        """Run one block; an exception (old code without the new names) is a failure, not an abort."""
        print(f"\n[{title}]")
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {title}: {type(exc).__name__}: {exc}")
            fails.append(title)


    class FakeResp:
        def __init__(self, body: bytes = b"", status: int = 200):
            self.status = status
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(io.BytesIO(self._body))

        def read(self):
            return self._body

        def close(self):
            pass


    class FakeNet:
        """Records every request (url, method, body); canned answers in order, then 200."""

        def __init__(self, *answers):
            self.sent: list[tuple[str, str, bytes]] = []
            self.queue = list(answers)

        def urlopen(self, req, timeout=None):
            self.sent.append((req.full_url, req.get_method(), req.data or b""))
            if not self.queue:
                return FakeResp()
            nxt = self.queue.pop(0)
            if isinstance(nxt, BaseException):
                raise nxt
            return nxt

        def posts(self):
            return [(u, b) for u, m, b in self.sent if m == "POST"]


    def use(net):
        fake_urllib = types.SimpleNamespace(
            request=types.SimpleNamespace(Request=urllib.request.Request, urlopen=net.urlopen),
            error=urllib.error)
        # phone.py's network code lives in these sibling modules; each reads its own urllib.
        for m in (phone_quota, phone_cos_store, phone_mailbox, phone_heartbeat):
            m.urllib = fake_urllib


    class Logs(logging.Handler):
        def __init__(self):
            super().__init__()
            self.recs: list[tuple[int, str]] = []
            self.marks: list[tuple[str, bool]] = []

        def emit(self, record):
            self.recs.append((record.levelno, record.getMessage()))
            if record.levelno >= logging.WARNING:
                self.marks.append((record.getMessage(), bool(getattr(record, errwatch.RECOVERED, False))))

        def warnings(self):
            return [m for lv, m in self.recs if lv >= logging.WARNING]

        def loud(self):
            """WARNING / ERROR records errwatch pushes to the group (not marked recovered)."""
            return [m for m, rec in self.marks if not rec]

        def recovered(self):
            """WARNINGs marked recovered: the daily report only."""
            return [m for m, rec in self.marks if rec]

        def infos(self, word):
            return [m for lv, m in self.recs if lv == logging.INFO and word in m]

        def clear(self):
            self.recs.clear()
            self.marks.clear()


    class Pushes:
        def __init__(self):
            self.sent = []

        def send(self, title, body, **k):
            self.sent.append((title, body))
            return []


    STATE = Path(tempfile.mkdtemp(prefix="phone-quiet-"))
    PUSHES = Pushes()
    WATCH = errwatch.ErrorKindAlert(PUSHES, state_dir=STATE, known={}, pace=0, retry=(0.05,))


    def pushed(want=0, secs=3.0):
        """What errwatch pushed to the group from the phone logger's records so far."""
        end = time.time() + secs
        while time.time() < end and (WATCH.pending() or len(PUSHES.sent) < want):
            time.sleep(0.02)
        time.sleep(0.1)
        return [b for _, b in PUSHES.sent]


    def settled(secs=10.0):
        """The group's push count once errwatch's queue is empty: the baseline a block
    counts its own pushes from. errwatch pushes on its own thread, so the plain
    WARNINGs an earlier block logged (the 42908 quota line, pushed as it should be)
    can still be queued when the next block starts; under load (8 tests at once in
    the deploy) they landed after a bare len(PUSHES.sent) and were counted as this
    block's push (10-07: 「得到 (1, [], 1, True)」)."""
        WATCH.drain(timeout=secs)
        left = WATCH.pending()
        if left:
            raise AssertionError(f"errwatch still holds {len(left)} push(es) after {secs:.0f} s")
        return len(PUSHES.sent)


    def daily():
        return errwatch.daily_section(STATE, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))


    def recovered_ok(word):
        """One recovered WARNING containing `word`, its first line plain (the daily report
    quotes it), nothing new pushed, and the day's report rows holding it as recovered
    (texts.relay_faults_section prints those rows tagged 自己好了，只进日报)."""
        rec = [m for m in logs.recovered() if word in m]
        first = rec[0].splitlines()[0] if rec else ""
        # Earlier plain WARNINGs may still be on their way to the group: count from after
        # them. Had this record been queued instead, settled() pushes it too and errwatch
        # counts that push on its day row, which is read below with the queue empty.
        before = settled()
        # errwatch writes the day row on the logging thread (_note_recovered, atomic write).
        rows = errwatch.day_faults(STATE, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
        row = next((r for r in rows if r.get("line") == first[:200]), {}) if rec else {}
        new_pushes = len(pushed()) - before + int(row.get("pushed") or 0)
        return (len(rec), texts.plain(first), new_pushes, bool(row.get("recovered")))


    logs = Logs()
    phone.log.addHandler(logs)
    phone.log.addHandler(WATCH)
    phone.log.setLevel(logging.DEBUG)
    phone.log.propagate = False
    # The COS retry logs on its own logger (netretry.call).
    netretry._log_netretry.addHandler(logs)
    netretry._log_netretry.addHandler(WATCH)
    netretry._log_netretry.setLevel(logging.DEBUG)
    netretry._log_netretry.propagate = False


    def ntfy_error(http: int, code: int = 0, text: str = "", headers=None):
        body = json.dumps({"code": code, "http": http, "error": text}).encode() if code else b""
        return urllib.error.HTTPError("https://ntfy.sh/x", http, "err", headers or {}, io.BytesIO(body))


    def quota_full():
        return ntfy_error(429, 42908, "limit reached: daily message quota reached")


    def mailbox(cos=None, state_dir=None):
        mb = phone.Mailbox(TOPIC, PIN, state_dir or tmpdir(), cos=cos)
        mb.RETRY_AFTER = 1
        mb.slept = []
        mb._sleep = mb.slept.append
        return mb


    # 43 KB raw, ~13 KB gzipped on 10-02: incompressible, so it is pieces or COS.
    BIG = {"at": 1, "options": {"x": __import__("base64").b64encode(os.urandom(9600)).decode()}}


    def a_quota_once():
        logs.clear()
        d = tmpdir()
        mb = mailbox(state_dir=d)
        net = FakeNet(quota_full())
        use(net)
        check("ntfy 回 42908：这份状态没发出去", mb.publish({"at": 1}), False)
        check("……记一条 WARNING，说额度用完了",
              [("额度用完" in m) for m in logs.warnings()], [True])
        mb.publish({"at": 2})
        mb.publish({"at": 3})
        check("之后的状态不再去撞 ntfy（一个请求都不多发）", len(net.sent), 1)
        check("……也不再多记 WARNING（10-02 晚 ×47 + ×14）", len(logs.warnings()), 1)
        beats = []
        hb = phone.Heartbeat(TOPIC, d, post=lambda p, t: beats.append(t))
        hb.beat()
        hb.bye()
        check("同一天：心跳和 bye 都不发（10-02 23:29:36 重启时的 bye 又报了一次）", beats, [])
        check("……还是只有那一条 WARNING", len(logs.warnings()), 1)
        logs.clear()
        d2 = tmpdir()
        raw = phone.Heartbeat(TOPIC, d2, account=lambda: {})
        raw.url = "https://ntfy.sh/x-hb"
        use(FakeNet(quota_full()))
        raw.beat()
        use(FakeNet())
        mailbox(state_dir=d2).publish({"at": 1})
        check("心跳先撞到 42908、状态后到：一天一共一条 WARNING", len(logs.warnings()), 1)


    def b_cos_is_delivered():
        logs.clear()
        mb = mailbox(cos=COS)
        net = FakeNet(FakeResp(), TimeoutError("The read operation timed out"),
                      TimeoutError("The read operation timed out"))
        use(net)
        check("COS 存上了、ntfy 通知超时两次：手机读得到，算送到了", mb.publish(BIG), True)
        check("……nothing for the group", logs.loud(), [])
        check("……one recovered WARNING: the notice missed ntfy, COS carried the state (daily only)",
              recovered_ok("没发到手机信箱，状态已存到腾讯云"), (1, [], 0, True))
        check("……the daily report prints it tagged 「自己好了，只进日报」",
              "状态的通知没发到手机信箱" in daily() and "自己好了，只进日报" in daily(), True)
        logs.clear()
        mb = mailbox(cos=COS)
        use(FakeNet(*[urllib.error.HTTPError("https://cos", 503, "busy", {}, None)] * DOWN, FakeResp()))
        check("COS 一直回 503、ntfy 发到了：算送到了", mb.publish({"at": 1}), True)
        check("……nothing for the group", logs.loud(), [])
        check("……one recovered WARNING: COS refused, ntfy carried it (daily only)",
              recovered_ok("状态没存上腾讯云，这一份改走手机信箱发到了"), (1, [], 0, True))
        logs.clear()
        mb = mailbox(cos=COS)
        net = FakeNet(urllib.error.HTTPError("https://cos", 503, "busy", {}, None), FakeResp(), FakeResp())
        use(net)
        check("COS 回一次 503、再写一次存上了：算送到了", mb.publish({"at": 1}), True)
        check("……两次 PUT，存上了就只发一条 ntfy 通知", [m for _, m, _ in net.sent], ["PUT", "PUT", "POST"])
        check("……nothing for the group", logs.loud(), [])
        check("……one recovered WARNING: written on the second try (daily only)",
              recovered_ok("第一次没成，第 2 次成了"), (1, [], 0, True))
        logs.clear()
        d = tmpdir()
        mb = mailbox(cos=COS, state_dir=d)
        mb.quota.mark_full("测试")
        logs.clear()
        net = FakeNet()
        use(net)
        check("额度已满时 COS 照存：算送到了（10-02 22:56 起这里被记成没上报）", mb.publish(BIG), True)
        check("……只有 COS 的 PUT，ntfy 一个请求都没有", [m for _, m, _ in net.sent], ["PUT"])
        check("……不记 WARNING (the quota's own WARNING is once a day)", logs.warnings(), [])


    def c_timeout_one_reason():
        logs.clear()
        mb = mailbox()
        net = FakeNet(TimeoutError("The read operation timed out"), TimeoutError("The read operation timed out"))
        use(net)
        check("没配 COS、ntfy 连超时两次：没送到", mb.publish({"at": 1}), False)
        check("……phone 自己不记 WARNING（调用方记那一条）", logs.warnings(), [])
        why = getattr(mb, "last_error", "")
        check("……原因写进 last_error：超时、试了 2 次",
              ("timed out" in why, "试了 2 次" in why), (True, True))
        check("……两次之间停了一下", mb.slept, [1])
        logs.clear()
        mb = mailbox(cos=COS)
        use(FakeNet(*[urllib.error.URLError("timed out")] * DOWN, TimeoutError("t1"), TimeoutError("t2")))
        check("COS 和 ntfy 都不通：没送到", mb.publish({"at": 1}), False)
        check("……原因两边都说", ("腾讯云 COS" in mb.last_error, "ntfy" in mb.last_error), (True, True))


    def d_retry_rules():
        mb = mailbox()
        net = FakeNet(ntfy_error(429, 42901, "limit reached: too many requests", {"Retry-After": "7"}), FakeResp())
        use(net)
        logs.clear()
        check("42901（请求太密）：等一会儿再试一次就送到", mb.publish({"at": 1}), True)
        check("……一共两次请求", len(net.sent), 2)
        check("……按 Retry-After 等了 7 秒", mb.slept, [7])
        check("……the retry got it through: one recovered WARNING, daily only, nothing pushed",
              recovered_ok("发到手机信箱第一次没成"), (1, [], 0, True))
        check("……nothing for the group", logs.loud(), [])
        mb = mailbox()
        net = FakeNet(ntfy_error(502), FakeResp())
        use(net)
        check("502（ntfy 前面的网关，09-23 / 10-05 见过）：再试一次", (mb.publish({"at": 1}), len(net.sent)), (True, 2))
        check("……先停 RETRY_AFTER 秒", mb.slept, [1])
        mb = mailbox()
        net = FakeNet(ntfy_error(400, 40001, "bad"))
        use(net)
        check("400：同样的内容再发也是 400，不重试", (mb.publish({"at": 1}), len(net.sent)), (False, 1))
        mb = mailbox()
        net = FakeNet(quota_full())
        use(net)
        check("42908：不重试", (mb.publish({"at": 1}), len(net.sent)), (False, 1))


    def e_pieces():
        logs.clear()
        mb = mailbox()
        net = FakeNet(FakeResp(), ntfy_error(502), FakeResp(), FakeResp(), FakeResp())
        use(net)
        check("第 2 片碰上一次 502：这一片重试，整份送到", mb.publish(BIG), True)
        check("……the piece's retry worked: one recovered WARNING, nothing for the group",
              (len(logs.recovered()), logs.loud()), (1, []))
        pieces = [json.loads(b) for _, b in net.posts()]
        check("……四片都到了 ntfy（同一个 sid，序号 0-3 各一次）",
              (len({p["sid"] for p in pieces}), sorted({p["i"] for p in pieces})), (1, [0, 1, 2, 3]))
        logs.clear()
        mb = mailbox()
        net = FakeNet(FakeResp(), TimeoutError("t1"), TimeoutError("t2"))
        use(net)
        check("第 2 片两次都超时：这份没送到", mb.publish(BIG), False)
        check("……剩下的片不发（拼不起来）", len(net.sent), 3)
        check("……不记 WARNING（调用方记那一条）", logs.warnings(), [])
        check("……last_error 说是第 2 片", "第 2 片" in getattr(mb, "last_error", ""), True)


    def ntfy_lines(*events):
        return ("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n").encode("utf-8")


    def f_backlog_read_again():
        logs.clear()
        mb = mailbox()
        use(FakeNet(TimeoutError("The read operation timed out")))
        check("开机读信箱超时：先给空的", mb.fetch(), [])
        check("……不记 WARNING（#41，08-31 到 10-02 共 11 次）", logs.warnings(), [])
        check("……记下要补读", getattr(mb, "backlog_missed", False), True)
        now = int(time.time())
        skip = phone.pack(PIN, {"action": "skip_today", "queue": "早班"})
        later = phone.pack(PIN, {"action": "debug_mode", "days": 1})
        net = FakeNet(FakeResp(ntfy_lines({"id": "b1", "time": now - 3600, "event": "message", "message": skip})),
                      FakeResp(ntfy_lines({"id": "o", "time": now, "event": "open"},
                                          {"id": "s1", "time": now, "event": "message", "message": later})))
        use(net)
        backlog, live = [], []
        mb.listen(live.append, lambda: not net.queue and len(live) >= 1, on_backlog=backlog.extend)
        check("手机通道连上后补读到关机期间按的那条",
              [(b.get("action"), b["_meta"]["via"]) for b in backlog], [("skip_today", "backlog")])
        check("……补读的那条走开机积压那条路（on_backlog），不当成在线按的", [b.get("action") for b in live], ["debug_mode"])
        check("……先补读、再订阅", ("poll=1" in net.sent[0][0], "poll=1" in net.sent[1][0]), (True, False))
        check("……补读完就不再补", mb.backlog_missed, False)
        check("……the late read: one recovered WARNING with the boot read's reason, daily only",
              recovered_ok("开机时没读到手机信箱"), (1, [], 0, True))
        check("……that line carries why the boot read failed",
              any("timed out" in m for m in logs.recovered() if "开机时没读到" in m), True)
        check("……nothing for the group", logs.loud(), [])


    class Idle(FakeResp):
        """An open stream that times out reading after its lines (ntfy sent nothing more)."""

        def __iter__(self):
            yield from io.BytesIO(self._body)
            raise TimeoutError("The read operation timed out")


    def g_stream_drops():
        logs.clear()
        mb = mailbox()
        t = int(time.time()) - 100
        net = FakeNet(FakeResp(ntfy_lines({"id": "o", "time": t, "event": "open"},
                                          {"id": "k", "time": t + 45, "event": "keepalive"})),
                      TimeoutError("The read operation timed out"),
                      ntfy_error(502),
                      urllib.error.URLError(ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。")),
                      FakeResp(ntfy_lines({"id": "o2", "time": t + 90, "event": "open"})),
                      TimeoutError("again"))
        use(net)
        mb.listen(lambda b: None, lambda: len(net.sent) >= 6)
        check("连不上、502、对方重置，几秒内又连上：nothing for the group (#45 #49 #57)", logs.loud(), [])
        check("……每次断开记一行 INFO", len(logs.infos("手机通道断了")), 3)
        check("……重连从读到的最后一行接着要（不是固定的 10 分钟）",
              [u.split("since=")[1] for u, _, _ in net.sent[1:4]], [str(t + 45 - 30)] * 3)
        check("……reconnected: one recovered WARNING saying how long, daily only",
              recovered_ok("手机通道断过"), (1, [], 0, True))
        logs.clear()
        mb = mailbox()
        net = FakeNet(Idle(ntfy_lines({"id": "o", "time": t, "event": "open"})),
                      FakeResp(ntfy_lines({"id": "o2", "time": t + 90, "event": "open"})), TimeoutError("again"))
        use(net)
        mb.listen(lambda b: None, lambda: len(net.sent) >= 3)
        check("an open stream that only timed out reading (idle) and came back: no WARNING at all",
              logs.warnings(), [])
        check("……INFO for the drop and the reconnect",
              (len(logs.infos("手机通道断了")), bool(logs.infos("又连上了"))), (1, True))
        logs.clear()
        mb = mailbox()
        mb.OUTAGE_SEC = 0                  # "ten minutes" without waiting ten minutes
        net = FakeNet(TimeoutError("t1"), ntfy_error(502), TimeoutError("t3"), FakeResp(b""), TimeoutError("t5"))
        use(net)
        before = settled()
        mb.listen(lambda b: None, lambda: len(net.sent) >= 4)
        check("一直连不上到时限：一次断线只记一条 WARNING for the group", len(logs.loud()), 1)
        check("……说清连不上多久、手机发的指令到不了", "手机通道连不上 ntfy" in (logs.loud() or [""])[0], True)
        check("……it reached the group", len(pushed(before + 1)) - before, 1)
        check("……back at last: one recovered WARNING that says it was pushed meanwhile",
              [("期间报过群" in m) for m in logs.recovered()], [True])


    def h_cos_beat_info():
        logs.clear()
        net = FakeNet(urllib.error.URLError("timed out"))
        use(net)
        hb = phone.Heartbeat(TOPIC, tmpdir(), post=lambda p, t: None, cos=COS)
        check("COS 心跳超时一次、ntfy 心跳照发", hb.beat(), True)
        # Between beats a COS heartbeat is one try: the next beat is the retry (dispatch
        # relay-opt-round3b-1108), so a flaky link writes no red item per beat.
        check("……这一跳只写了一次（不在这一跳里重试）", sum(1 for _, m, _ in net.sent if m == "PUT"), 1)
        check("……不记 WARNING（10-03 00:16:44 那条）", logs.warnings(), [])
        check("……记一行 INFO", bool(logs.infos("腾讯云 COS")), True)
        use(FakeNet())
        check("the next COS beat works", hb.cos_beat(), True)
        check("……one recovered WARNING: written again, daily only",
              recovered_ok("心跳又写得进腾讯云了"), (1, [], 0, True))
        check("……nothing for the group", logs.loud(), [])
        logs.clear()
        hb2 = phone.Heartbeat(TOPIC, tmpdir(), post=lambda p, t: None, cos=COS)
        use(FakeNet(*[urllib.error.URLError("timed out")] * 3))
        hb2.cos_beat()
        hb2._cos_down -= hb2.COS_OUTAGE_SEC          # "ten minutes ago" without waiting
        before = settled()
        hb2.cos_beat()
        hb2.cos_beat()
        check("still failing 10 minutes on: one WARNING for the group", len(logs.loud()), 1)
        check("……it says since when and that the App reads an old beat",
              "一直写不进腾讯云" in (logs.loud() or [""])[0], True)
        check("……it reached the group", len(pushed(before + 1)) - before, 1)
        use(FakeNet())
        hb2.cos_beat()
        check("……back at last: one recovered WARNING that says it was pushed meanwhile",
              [("期间报过群" in m) for m in logs.recovered()], [True])


    def i_ntfy_count():
        logs.clear()
        q = phone.Quota(tmpdir())
        q.add("hb", 5)
        check("ntfy 自己的计数读进来", q.sync({"stats": {"messages": 240, "messages_remaining": 10}}), 240)
        check("……今天用了多少按 ntfy 的算（不是本机账本的 5）", q.total(), 240)
        q.add("state")
        check("……之后中继再发的照加", (q.total(), q.own()), (241, 6))
        check("……过了停跳线，心跳只走 COS", q.stops_beats(), True)
        check("没有 stats 的回答不算数，账本照旧", phone.Quota(tmpdir()).sync({"error": "x"}), None)
        q2 = phone.Quota(tmpdir())
        q2.sync({"stats": {"messages": 250, "messages_remaining": 0}})
        check("ntfy 说剩 0 条：记成今天满了，一条 WARNING", (q2.full(), len(logs.warnings())), (True, 1))
        hb = phone.Heartbeat(TOPIC, tmpdir(), post=lambda p, t: None,
                             account=lambda: {"stats": {"messages": 150, "messages_remaining": 100}})
        hb.sync_quota()
        check("心跳的节奏跟着 ntfy 的计数走（150 条 → 5 分钟一跳）", hb.interval(), phone.HB_SLOW_SEC)
        net = FakeNet(FakeResp(json.dumps({"limits": {"messages": 250},
                                           "stats": {"messages": 12, "messages_remaining": 238}}).encode()))
        use(net)
        check("ntfy_account：GET /v1/account，解出 stats", phone.ntfy_account()["stats"]["messages"], 12)
        check("……问的是 ntfy.sh/v1/account", net.sent[0][:2], ("https://ntfy.sh/v1/account", "GET"))
        plain = phone.Heartbeat(TOPIC, tmpdir(), post=lambda p, t: None)
        check("测试里给了假心跳就不去问 ntfy 的计数", plain._account, None)
        check("线上（不给 post）才问", phone.Heartbeat(TOPIC, tmpdir())._account, phone.ntfy_account)


    def j_budget():
        d = tmpdir()
        mb = mailbox(cos=COS, state_dir=d)
        mb.quota.add("hb", phone.NOTICE_STOP_AT)
        net = FakeNet()
        use(net)
        check("今天已用到 230：状态照存 COS、算送到", mb.publish(BIG), True)
        check("……ntfy 的通知不发了（留给 bye 和手机的指令）", [m for _, m, _ in net.sent], ["PUT"])
        beats = []
        hb = phone.Heartbeat(TOPIC, tmpdir(), post=lambda p, t: beats.append(t), cos=COS)
        hb.quota.add("state", phone.HB_STOP_AT)
        net = FakeNet()
        use(net)
        check("今天已用到 200：ntfy 不再跳", (hb.beat(), beats), (False, []))
        check("……COS 心跳照写，App 照样看得到开机", [m for _, m, _ in net.sent], ["PUT"])
        check("……COS 上告诉 App 节奏放宽了", json.loads(net.sent[0][2])["every"] >= phone.HB_SLOW_SEC, True)


    for title, fn in (("#40 #52 #54：额度用完一天只说一次，之后不再去撞", a_quota_once),
                      ("#42 #47 #48：存进 COS 就算送到", b_cos_is_delivered),
                      ("#44：超时只给一个原因，不在每次尝试时报", c_timeout_one_reason),
                      ("#39 #49：429/5xx 停一下再试，42908 和其他 4xx 不试", d_retry_rules),
                      ("#51：切片先重试那一片，断了也只由调用方报一次", e_pieces),
                      ("#41：开机读信箱超时，等通道连上补读", f_backlog_read_again),
                      ("#45 #49 #57：断线重连是 INFO，连不上十分钟才 WARNING", g_stream_drops),
                      ("#56：COS 心跳一次超时是 INFO", h_cos_beat_info),
                      ("「今天 ntfy 已发 0 条」：用 ntfy 自己的计数", i_ntfy_count),
                      ("中继自己停在 250 之前", j_budget)):
        section(title, fn)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_phone_receipts():
    """Phone-order receipts: the relay's answer to each order shows on the phone page.

    Formerly test_phone_receipts.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import modes


    print("[回执：记下来、最新在后、只留最近几条]")
    d = tmpdir()
    check("一开始是空的", modes.receipts(d), [])
    modes.add_receipt(d, "skip_shutdown", True, "已撤回还没用上的「下次跑完不关机」：下一趟早班/晚班跑完照常关机")
    modes.add_receipt(d, "set_stage", False, "没有这个字段")
    r = modes.receipts(d)
    check("两条", [(x["action"], x["ok"]) for x in r], [("skip_shutdown", True), ("set_stage", False)])
    check("带时间", all(len(x["at"]) == 11 for x in r), True)
    for i in range(20):
        modes.add_receipt(d, "x", True, str(i))
    check(f"最多 {modes.RECEIPTS_KEEP} 条", len(modes.receipts(d)), modes.RECEIPTS_KEEP)
    check("留的是最新的", modes.receipts(d)[-1]["text"], "19")


def _part_phone_sent():
    """A phone order keeps the time it was sent: in relay.log and on its receipt.

2026-09-30: three skip orders were found in the mailbox at 08:46 and nobody could
say when they had been sent - relay.log and the receipts held only the moment the
relay acted, and ntfy drops a message after 12 hours. The user asked 「谁干的？」
and there was no answer. Pinned here: the log line names the envelope's ts, ntfy's
time and id; the receipt stores "sent" and keeps its text plain (the page shows
「HH:MM 发出 · HH:MM 执行」 from sent / at); no command body ever sees "_meta".

    Formerly test_phone_sent.py.
    """
    import json
    import logging
    import types
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    import ark_relay.features.commands as C
    from ark_relay.features import phone as phone_channel
    from ark_relay.features import modes
    from ark_relay.features import phone
    from ark_relay.core.config import SERVER_TZ


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())


    grab = Grab()
    phone.log.addHandler(grab)
    phone.log.setLevel(logging.INFO)

    T = int(datetime(2026, 9, 30, 8, 46, 23, tzinfo=SERVER_TZ).timestamp())
    ENV = {"id": "rkCjnh9nJkyU", "time": T + 2, "event": "message"}

    print("[收到指令：relay.log 记发出时刻、ntfy 收到时刻和 id]")
    body = phone.stamp({"ts": T, "body": {"action": "skip_today", "queue": "晚班"}}, ENV, "live")
    line = grab.lines[-1] if grab.lines else ""
    check("记了一行", line.startswith("📱 收到手机指令 skip_today："), True)
    check("行里有信封 ts 的北京时刻", "09-30 08:46:23 发出" in line, True)
    check("行里有 ntfy 收到时刻", "ntfy 09-30 08:46:25 收到" in line, True)
    check("行里有 ntfy id", "rkCjnh9nJkyU" in line, True)
    check("说明是在线收到", line.endswith("在线收到"), True)
    check("_meta 带上 sent / id / via", (body["_meta"]["sent"], body["_meta"]["ntfy_id"], body["_meta"]["via"]),
          (T, "rkCjnh9nJkyU", "live"))
    check("原指令键不动", {k: v for k, v in body.items() if k != "_meta"}, {"action": "skip_today", "queue": "晚班"})

    print("\n[页面自己的刷新 / 看着 不记行（每次开页面都发，会淹掉指令）]")
    n = len(grab.lines)
    phone.stamp({"ts": T, "body": {"action": "refresh"}}, ENV, "live")
    phone.stamp({"ts": T, "body": {"action": "watch"}}, ENV, "live")
    check("没多出行", len(grab.lines), n)


    class Eng:
        def scripts_running(self):
            return False


    class Notes:
        def send(self, *a, **k):
            return False


    class Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def exception(self, *a, **k): pass


    class HB:
        def watch(self): pass


    def run(stamped):
        d = tmpdir()
        got = []
        real = C.apply_command
        C.apply_command = lambda b: (got.append(dict(b)), (True, "今天（2026-09-30）将跳过队列「晚班」"))[1]
        try:
            phone_channel._make_phone_cmd(Eng(), Notes(), Log(), HB(), lambda *_: None, d)(stamped)
        finally:
            C.apply_command = real
        return got, modes.receipts(d)


    print("\n[在线指令：回执多存 sent，文字不变，指令体里没有 _meta]")
    got, rec = run(phone.stamp({"ts": T, "body": {"action": "skip_today", "queue": "晚班"}}, ENV, "live"))
    check("apply_command 收到的就是原指令", got, [{"action": "skip_today", "queue": "晚班"}])
    check("回执 sent = 发出的 月-日 时:分", rec[-1].get("sent"), "09-30 08:46")
    check("回执文字照原样", rec[-1]["text"], "今天（2026-09-30）将跳过队列「晚班」")

    print("\n[开机读积压：回执存 sent，文字不加前缀（页面按 sent / at 自己显示两个时刻）]")
    got, rec = run(phone.stamp({"ts": T, "body": {"action": "skip_today", "queue": "晚班"}}, ENV, "backlog"))
    check("apply_command 收到的就是原指令", got, [{"action": "skip_today", "queue": "晚班"}])
    check("回执文字照原样，不加「发出 / 执行」前缀", rec[-1]["text"], "今天（2026-09-30）将跳过队列「晚班」")
    check("sent 照样存", rec[-1].get("sent"), "09-30 08:46")
    check("积压那一行说是开机读的", grab.lines[-1].endswith("开机读信箱积压"), True)

    print("\n[没有 _meta 的老调用：照旧，不带 sent]")
    got, rec = run({"action": "skip_today", "queue": "晚班"})
    check("照旧执行", got, [{"action": "skip_today", "queue": "晚班"}])
    check("没有 sent 键", "sent" in rec[-1], False)

    print("\n[add_receipt 直接调用：sent 可选]")
    d = tmpdir()
    modes.add_receipt(d, "debug_mode", True, "开了", sent=T)
    modes.add_receipt(d, "debug_mode", True, "开了")
    r = modes.receipts(d)
    check("给了就存", r[0].get("sent"), "09-30 08:46")
    check("没给就没有", "sent" in r[1], False)

    print("\n[太老丢弃时也记发出时刻]")
    old = json.dumps({"v": 1, "kind": "cmd", "pin": "p", "ts": T, "body": {"action": "x"}})
    check("丢掉", phone.unpack("p", old, now=T + 30 * 3600), None)
    check("那一行有发出时刻", "09-30 08:46:23 发出" in grab.lines[-1], True)

    print("\n[月卡没带 at：按发出时刻记，不按机器收到的时刻（11-08 [D-07]）]")
    _b = {"action": "monthcard"}
    phone_channel._monthcard_stamp_at(_b, None, {"ntfy_time": 1762560000})
    check("用 ntfy 的发出时刻", _b.get("at"), "2025-11-08T00:00:00+00:00")
    _b = {"action": "monthcard"}
    phone_channel._monthcard_stamp_at(_b, None, None)
    check("什么时刻都没有：不编一个", "at" in _b, False)


def _part_phone_silent():
    """phone.state_payload says when the relay block or tomorrow's plan could not be
built (audit docs/SILENT-FAILURES-AUDIT.md, phone.py:1862 and :1884).

state_payload runs on every phone-state publish and a WARNING is a group
message, so each is said once per condition; the payload keeps its shape
(relay = {}, plan = "").

    Formerly test_phone_silent.py.
    """
    import logging
    import types
    from unittest import mock

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import modes
    from ark_relay.features import phone, snapshot
    from ark_relay.core import plan


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def said(self, words):
            out = [r for r in self.records if r.levelno >= logging.WARNING and words in r.getMessage()]
            self.records.clear()
            return len(out)


    grab = Grab()
    phone.log.addHandler(grab)
    cfg = types.SimpleNamespace(automas_dir=str(tmpdir()), maaend_dir=str(tmpdir()), okww_dir=str(tmpdir()))
    sd = tmpdir()


    def payload():
        with mock.patch.object(snapshot, "read_runtime", lambda: {}):
            return phone.state_payload(cfg, sd)


    print("[relay block raising]")
    getattr(phone, "_last_error", {}).clear()
    with mock.patch.object(modes, "debug_active", side_effect=RuntimeError("state broke")):
        st = payload()
        check("relay carries only _错误 (audit A3; was {})", st.get("relay"), {"_错误": "RuntimeError: state broke"})
        check("one WARNING", grab.said("中继那一段"), 1)
        payload()
        check("same condition again -> no second WARNING", grab.said("中继那一段"), 0)
    st = payload()
    check("works -> a dict with its keys", isinstance(st["relay"], dict) and "调试模式" in st["relay"], True)
    check("works -> no WARNING", grab.said("中继那一段"), 0)
    with mock.patch.object(modes, "debug_active", side_effect=RuntimeError("state broke")):
        payload()
        check("broken again after it worked -> WARNING again", grab.said("中继那一段"), 1)

    print("[plan.next_plan raising]")
    getattr(phone, "_last_error", {}).clear()
    with mock.patch.object(plan, "next_plan", side_effect=ValueError("bad queue")):
        st = payload()
        check("plan stays \"\" (type unchanged)", st.get("plan"), "")
        check("one WARNING", grab.said("明日安排"), 1)
        payload()
        check("same condition again -> no second WARNING", grab.said("明日安排"), 0)
    with mock.patch.object(plan, "next_plan", return_value="📅 明日安排"):
        check("works -> the plan text", payload().get("plan"), "📅 明日安排")
        check("works -> no WARNING", grab.said("明日安排"), 0)
    with mock.patch.object(plan, "next_plan", side_effect=ValueError("bad queue")):
        payload()
        check("broken again after it worked -> WARNING again", grab.said("明日安排"), 1)


def _part_phone_stale_cmd():
    """A phone command dropped as too old is marked handled (audit 9 A3, 2026-10-13).

wire.unpack returns None for a command older than MAX_AGE, and the mailbox
skipped it without adding its ntfy id to the handled list. While ntfy kept the
message, every boot and every reconnect re-read it and logged 「信箱里那条指令太老了」
again: relay.log 2026-10-05 logged the same two messages 11 times (the cause, a
phone clock a day off, was fixed in the App, ark-remote 745e96e).

Both read paths are checked: the boot read (Mailbox.fetch / _read_backlog) and
the held stream (Mailbox.listen). Fake network; nothing waits for real.

    Formerly test_phone_stale_cmd.py.
    """
    import io
    import json
    import logging
    import time
    import types
    import urllib.error
    import urllib.request

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import phone as phone_mailbox
    from ark_relay.features import phone

    PIN = "8964"
    TOPIC = "topic-abc"


    class FakeResp:
        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(io.BytesIO(self._body))

        def read(self):
            return self._body

        def close(self):
            pass


    def ntfy_lines(*msgs):
        """ntfy's JSON stream: one `message` event per (id, raw message)."""
        now = int(time.time())
        return "\n".join(json.dumps({"id": mid, "time": now, "event": "message", "message": raw})
                         for mid, raw in msgs).encode() + b"\n"


    def cmd(body, ts):
        return json.dumps({"v": 1, "kind": "cmd", "pin": PIN, "ts": ts, "body": body})


    def use(body):
        fake = types.SimpleNamespace(
            request=types.SimpleNamespace(Request=urllib.request.Request,
                                          urlopen=lambda req, timeout=None: FakeResp(body)),
            error=urllib.error)
        phone_mailbox.urllib = fake


    class Logs(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines: list[str] = []

        def emit(self, record):
            self.lines.append(record.getMessage())


    logs = Logs()
    phone.log.addHandler(logs)
    phone.log.setLevel(logging.INFO)

    now = int(time.time())
    OLD = cmd({"action": "refresh"}, now - phone.MAX_AGE - 3600)
    NEW = cmd({"action": "refresh"}, now - 60)
    FOREIGN = json.dumps({"v": 1, "kind": "cmd", "pin": "0000", "ts": now - phone.MAX_AGE - 3600, "body": {}})
    STATE = json.dumps({"v": 1, "kind": "state", "pin": PIN, "ts": now - 60, "body": {}})
    BACKLOG = ntfy_lines(("m-old", OLD), ("m-new", NEW), ("m-foreign", FOREIGN), ("m-state", STATE))


    def too_old_lines():
        return sum("太老了" in line for line in logs.lines)


    print("[boot read: a too-old command is marked handled, and logged once]")
    state = tmpdir()
    use(BACKLOG)
    mb = phone.Mailbox(TOPIC, PIN, state)
    got = mb._read_backlog()
    check("only the fresh command runs", [c["_meta"]["ntfy_id"] for c in got], ["m-new"])
    check("the too-old command's id is marked handled (not a wrong PIN, not a state)",
          sorted(mb._seen), ["m-new", "m-old"])
    mb2 = phone.Mailbox(TOPIC, PIN, state)          # the next boot
    check("the mark survives a restart", "m-old" in mb2._seen, True)
    before = too_old_lines()
    check("the next boot does not run anything again", mb2._read_backlog(), [])
    check("and does not log the too-old command again", too_old_lines() - before, 0)

    print("\n[held stream: a too-old command is marked handled]")
    state = tmpdir()
    use(ntfy_lines(("s-old", OLD)))
    mb = phone.Mailbox(TOPIC, PIN, state)
    calls = []


    def stop():
        """False for the loop check and the one line; True once the stream ends."""
        calls.append(1)
        return len(calls) > 2


    mb.listen(lambda c: None, stop)
    check("the stream marks it handled", mb._seen, ["s-old"])
    check("on disk too", phone.Mailbox(TOPIC, PIN, state)._seen, ["s-old"])


def _part_phone_state():  # noqa: C901
    """手机页那一份状态包：形状、大小、去重、额度。全程注入假网络。

这个文件防的是**一类损失：用户唯一的日常操作界面变成一张白纸**，
而机器这头一片绿——它以为自己发出去了。

具体的坏法都出过：
* `state_payload` 少一个键，页面那一段就整块不渲染（2026-09-02 晚 AUTO-MAS 没开着，
  页面把空配置当成真配置显示，用户的评价是「一坨屎」）；
* 单条消息超过 ntfy 上限会被**截断**，手机上 JSON.parse 直接失败，
  表现成「状态永远不更新」，于是被判成关机中（2026-08-31 真发生过）；
* 已经执行过的指令再执行一遍——同一条「现在跑一趟」跑两趟，烧掉一趟的理智；
* PIN 不对的消息被当成指令执行；
* 心跳盲发：匿名 ntfy 每 IP 每天 250 条，闷头跳就把状态推送和指令应答一起挤掉。

`phone.py` 25 个函数里 16 个从来没被执行过，上面这些没有一条被钉住过。
已有的 test_phone.py（PIN/时效）、test_phone_gzip.py（pack/unpack 压缩往返）、
test_heartbeat.py（有人看才跳）覆盖的部分这里不重复。

    Formerly test_phone_state.py.
    """
    import io
    import json
    import time
    import types
    import urllib.error

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import phone
    from ark_relay.features import phone as phone_cos_store, phone as phone_heartbeat, phone as phone_mailbox, phone as phone_quota

    PIN = "8964"


    def bare(bodies):
        """The command bodies without phone.stamp's "_meta" (when / how it arrived)."""
        return [{k: v for k, v in b.items() if k != "_meta"} for b in bodies]


    # ---------------------------------------------------------------- 假网络
    #
    # phone.py 里所有网络都走 `urllib.request.*`。整块换掉，测试进程绝不出网。

    class FakeResp:
        def __init__(self, body: bytes = b"", status: int = 200):
            self.status = status
            self._body = body
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(io.BytesIO(self._body))

        def read(self):
            return self._body

        def close(self):
            self.closed = True


    class FakeNet:
        """Records every request; hands back canned responses."""

        def __init__(self):
            self.sent: list[tuple[str, bytes, dict]] = []
            self.queue: list = []

        def urlopen(self, req, timeout=None):
            self.sent.append((req.full_url, req.data or b"", dict(req.headers)))
            if not self.queue:
                return FakeResp(b"")
            nxt = self.queue.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt


    # phone.py's network code lives in these sibling modules; each reads its own urllib.
    NET_MODULES = (phone_quota, phone_cos_store, phone_mailbox, phone_heartbeat)


    def with_net(net, fn):
        saved = [m.urllib for m in NET_MODULES]
        fake = types.SimpleNamespace(
            request=types.SimpleNamespace(Request=saved[0].request.Request, urlopen=net.urlopen),
            error=urllib.error)
        for m in NET_MODULES:
            m.urllib = fake
        try:
            return fn()
        finally:
            for m, s in zip(NET_MODULES, saved, strict=True):
                m.urllib = s


    # ---------------------------------------------------------------- state_payload

    print("[state_payload 的形状：手机页靠这几个键渲染，少一个就是一块空白]")

    FULL = {
        # Not the config any more: config.MAA comes from ScriptConfig.json below
        # (the 10-07 10:55 push had none of this and sent `config: {}`).
        "MAA": {"关卡": "1-7", "理智药": 9},
        "MaaEnd": {"Stage": "藏剑谷", "MedicineNumb": 2},
        "OK-WW": {"WhichToFarm": "残象聚落"},
        "ark-relay": "跑着",
        "程序": {"MAA.exe": True, "Endfield.exe": False, "MaaEnd.exe": True},
        # The 10-07 10:55 state (the service-stop push): snapshot.read() had no queue
        # section, the plan text had both shifts. The queues come from the config
        # files below now, the ones the plan reads.
        "OK-WW配置": {"一大坨": "不该出现在手机包里"},
    }

    STATE = tmpdir()
    AUTOMAS = tmpdir()

    # A stand-in for AUTO-MAS's own models file: this is where the Chinese labels on
    # the phone come from (the user, 2026-08-31: the UI is all Chinese, the labels
    # must be read from upstream, never invented here).
    models = AUTOMAS / "app" / "models"
    models.mkdir(parents=True)
    (models / "user_config.py").write_text('''
class MaaUserConfig(ConfigBase):
    def __init__(self):
        ## 刷取关卡
        self.Stage = ConfigItem(
            "Info", "Stage", "AT-4"
        )
        ## 选关模式
        self.StageMode = ConfigItem(
            "Info", "StageMode", "Fixed", OptionsValidator(["Fixed", "Auto"])
        )
        ## 失败重试上限
        self.RunTimesLimit = ConfigItem(
            "Info", "RunTimesLimit", 3
        )


class OkwwUserConfig(ConfigBase):
    def __init__(self):
        ## 刷什么
        self.WhichToFarm = ConfigItem(
            "Task", "WhichToFarm", "", OptionsValidator(["残象聚落", "无音区"])
        )
''', encoding="utf-8")

    # QueueConfig.json / ScriptConfig.json shaped the way AUTO-MAS writes them
    # (as in test_next_deadline.py): the same two shifts the 10-07 plan text listed.
    (AUTOMAS / "config").mkdir()
    SCRIPTS = {"s1": "MAA", "s2": "MaaEnd", "s3": "OK-WW"}
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(
        {"instances": [{"uid": u} for u in SCRIPTS],
         **{u: {"Info": {"Name": n}} for u, n in SCRIPTS.items()},
         # The MAA user, Info / Task as AUTO-MAS saves them (snapshot._mas reads the
         # same two groups from the backend).
         "s1": {"Info": {"Name": "MAA"}, "SubConfigsInfo": {"UserData": {
             "instances": [{"uid": "u1"}],
             "u1": {"Info": {"Stage": "AT-4", "MedicineNumb": 0, "StageMode": "Fixed",
                             "SeriesNumb": "6", "Annihilation": "Close"},
                    "Task": {"IfFight": True, "IfActivityFirst": False,
                             "ActivityStageIndex": 2}}}}}}), encoding="utf-8")
    QUEUES = {"早班": ("09:00", ["s1", "s2", "s3"]), "晚班": ("21:30", ["s1"])}
    qdoc: dict = {"instances": []}
    for i, (name, (at, sids)) in enumerate(QUEUES.items()):
        qdoc["instances"].append({"uid": f"q{i}"})
        qdoc[f"q{i}"] = {"Info": {"Name": name, "TimeEnabled": True, "StartUpEnabled": False},
                         "SubConfigsInfo": {
                             "TimeSet": {"instances": [], "t0": {"Info": {"Enabled": True, "Time": at}}},
                             "QueueItem": {"instances": [], **{f"i{n}": {"Info": {"ScriptId": sid}}
                                                               for n, sid in enumerate(sids)}}}}
    (AUTOMAS / "config" / "QueueConfig.json").write_text(
        json.dumps(qdoc, ensure_ascii=False), encoding="utf-8")

    cfg = types.SimpleNamespace(automas_dir=str(AUTOMAS),
                                maaend_dir=str(tmpdir()),
                                okww_dir=str(tmpdir()))

    from ark_relay.core import plan
    from ark_relay.features import snapshot

    saved_read, saved_plan = snapshot.read_runtime, plan.next_plan
    snapshot.read_runtime = lambda: dict(FULL)
    plan.next_plan = lambda automas_dir: "明天：早班 MAA/MaaEnd/OK-WW"
    try:
        out = phone.state_payload(cfg, STATE)
    finally:
        snapshot.read_runtime, plan.next_plan = saved_read, saved_plan

    for key in ("at", "config", "run", "queues", "relay", "options", "master", "plan"):
        check(f"有 {key} 这个键", key in out, True)
    check("at 是秒级时间戳（页面靠它算「多久以前」和挑最新的一份）",
          isinstance(out["at"], int) and abs(out["at"] - time.time()) < 5, True)

    check("只发明日方舟那一段（另两个游戏走母本，发 MAS 的值会误导人）",
          sorted(out["config"]), ["MAA"])
    check("手机上要显示的字段留下（从 ScriptConfig.json 读，不用快照里的旧值）",
          out["config"]["MAA"],
          {"关卡": "AT-4", "理智药": 0, "剿灭": "Close", "作战开关": True,
           "活动关优先": False, "活动关序号": 2})
    check("手机上不显示的字段不发（整包塞不下）",
          [k for k in ("关卡链", "连战", "关卡模式") if k in out["config"]["MAA"]], [])
    check("快照里的大块头没混进来（OK-WW配置/进程原文）",
          [k for k in out if k in ("OK-WW配置", "程序")], [])

    check("run 里给出服务状态", out["run"]["服务"], "跑着")
    check("run 里只列真在跑的进程", sorted(out["run"]["在跑的"]), ["MAA.exe", "MaaEnd.exe"])

    check("queues 是列表，每项带「名」（页面用它做班次下拉）",
          [q["名"] for q in out["queues"]], ["早班", "晚班"])
    check("queues 每项保留原有字段", out["queues"][0]["脚本"],
          ["MAA", "MaaEnd", "OK-WW"])
    check("快照里没有队列那一段（关机前那一推）：名单照样从配置文件读出",
          [(q["名"], q["定时"], q["脚本"]) for q in out["queues"]],
          [("早班", True, ["MAA", "MaaEnd", "OK-WW"]), ("晚班", True, ["MAA"])])
    # The real plan text, minus the maintenance notices it fetches from the web.
    saved_maint = plan.maintenance_lines
    snapshot.read_runtime, plan.maintenance_lines = (lambda: {}), (lambda day: [])
    try:
        both = phone.state_payload(cfg, STATE)
    finally:
        snapshot.read_runtime, plan.maintenance_lines = saved_read, saved_maint
    check("名单和排班文字说的是同一组班次（10-07 10:55 名单空、文字两班）",
          ["09:00" in both["plan"], "21:30" in both["plan"], [q["名"] for q in both["queues"]]],
          [True, True, ["早班", "晚班"]])

    from ark_relay.features import modes as _modes
    _modes._store(STATE).set("modes", "debug_until", "2000-01-01 00:00")
    snapshot.read_runtime, plan.next_plan = (lambda: dict(FULL)), (lambda automas_dir: "")
    try:
        check("调试模式过了结束时间就发空串（手机上不再显示「开着」）",
              phone.state_payload(cfg, STATE)["relay"]["调试模式"], "")
        _modes._store(STATE).set("modes", "debug_until", "2999-01-01 00:00")
        check("调试模式还在期内照发结束时间",
              phone.state_payload(cfg, STATE)["relay"]["调试模式"], "2999-01-01 00:00")
    finally:
        snapshot.read_runtime, plan.next_plan = saved_read, saved_plan
        _modes._store(STATE).pop("modes", "debug_until")

    for key in ("调试模式", "下次别关机", "周本", "周常"):
        check(f"relay 里有「{key}」", key in out["relay"], True)
    check("relay.周常 三件套齐全（页面读的是这三个）",
          sorted(out["relay"]["周常"]), sorted(["剿灭", "周常乐园", "周本"]))
    check("「下次别关机」是布尔，页面拿它决定按钮文案",
          isinstance(out["relay"]["下次别关机"], bool), True)

    check("中文标注按「脚本|路径」发过去，正是页面查表用的键",
          out["options"]["_labels"].get("MAA|Info.Stage"), "刷取关卡")
    check("另一个脚本的标注也读得到",
          out["options"]["_labels"].get("OK-WW|Task.WhichToFarm"), "刷什么")
    check("不在 SHOWN 里的标注不发（154 条全发会撑爆单条消息）",
          "MAA|Info.RunTimesLimit" in out["options"]["_labels"], False)

    check("plan 发出去了", out["plan"].startswith("明天："), True)
    for game in ("MAA", "MaaEnd", "OK-WW"):
        check(f"master 里有 {game} 这一段", game in out["master"], True)

    print("\n[快照读不到时：明说读不到，其余照发——页面才能标「这是上次的」]")
    snapshot.read_runtime = lambda: (_ for _ in ()).throw(ConnectionError("AUTO-MAS 没开"))
    plan.next_plan = lambda automas_dir: (_ for _ in ()).throw(OSError("读不了"))
    try:
        broken = phone.state_payload(cfg, STATE)
    finally:
        snapshot.read_runtime, plan.next_plan = saved_read, saved_plan

    check("AUTO-MAS 没开（关机那一推）：config 照样从配置文件读出",
          broken["config"]["MAA"]["关卡"], "AT-4")
    nofile = types.SimpleNamespace(automas_dir=str(tmpdir()), maaend_dir=cfg.maaend_dir,
                                   okww_dir=cfg.okww_dir)
    snapshot.read_runtime = lambda: {}
    try:
        blind = phone.state_payload(nofile, STATE)
    finally:
        snapshot.read_runtime = saved_read
    check("配置文件读不到：config 里留一条 _错误，页面据此弹警告",
          list(blind["config"]), ["_错误"])
    check("_错误 里带上异常类型，不是干巴巴一句「出错」",
          blind["config"]["_错误"].startswith("FileNotFoundError:"), True)
    check("配置文件读不到：班次名单是空列表，不是缺键", blind["queues"], [])
    check("plan 读不到时给空串，不是缺键", broken["plan"], "")

    print("\n[queues / relay that cannot be built carry `_错误`, not [] / {} (status-channel audit A3)]")
    # [] read on the App as "every game in the shift", {} as switches off, weekly not
    # done, no month cards - as if real.
    from ark_relay.features import weeklyboss
    saved_rows, saved_wb = plan.queue_rows, weeklyboss.WeeklyBossGate.settings
    plan.queue_rows = lambda automas_dir: (_ for _ in ()).throw(OSError("ScriptConfig 读不了"))
    weeklyboss.WeeklyBossGate.settings = lambda self: (_ for _ in ()).throw(ValueError("坏了"))
    # The real plan runs here too: keep its maintenance notices off the web, as above. Run
    # 38363145659 (Windows) sat in those official-site fetches until the 180 s limit.
    plan.maintenance_lines = lambda day: []
    phone._last_error.pop("relay", None)
    try:
        marked = phone.state_payload(cfg, STATE)
    finally:
        plan.queue_rows, weeklyboss.WeeklyBossGate.settings = saved_rows, saved_wb
        plan.maintenance_lines = saved_maint
    check("queues: one row holding only _错误",
          marked["queues"], [{"_错误": "OSError: ScriptConfig 读不了"}])
    check("relay: _错误 with the exception", marked["relay"], {"_错误": "ValueError: 坏了"})
    check("AUTO-MAS 没开：班次名单照样从配置文件读出",
          [q["名"] for q in broken["queues"]], ["早班", "晚班"])
    # 快照那一段全靠 AUTO-MAS，它没开着就什么都读不到；页面对 run/queues 缺失是
    # 容错的（`(snap && snap.queues) || []`），但下面这几个键页面直接取值，必须还在。
    for key in ("at", "config", "relay", "options", "master", "plan"):
        check(f"快照炸了，{key} 还在", key in broken, True)
    check("relay 那一段和快照无关，照样有内容",
          "下次别关机" in broken["relay"], True)

    # ---------------------------------------------------------------- publish

    print("\n[publish：什么都不砍。通道不是 4096，那只是「转成附件」的分界]")
    # Measured 2026-09-09: a 9046-byte body posts fine, ntfy stores it as an attachment
    # and hands back a URL that returns it byte-for-byte. 4096 was treated as a hard
    # ceiling here and the state was trimmed section by section to fit - features thrown
    # away for a problem that did not exist, and when trimming was not enough the message
    # went out unparseable and the page kept showing values almost an hour old.

    mb = phone.Mailbox("topic-abc", PIN, tmpdir())
    check("有 topic 有 pin 才算启用", mb.enabled, True)
    check("没配 topic 就是没启用", phone.Mailbox("", PIN, tmpdir()).enabled, False)
    check("没配 pin 就是没启用", phone.Mailbox("t", "", tmpdir()).enabled, False)

    net = FakeNet()
    off = phone.Mailbox("", "", tmpdir())
    check("没启用时 publish 直接返回 False", with_net(net, lambda: off.publish({"at": 1})), False)
    check("没启用时一个网络请求都没发", net.sent, [])

    net = FakeNet()
    net.queue.append(FakeResp(b"ok"))
    check("小状态包发得出去", with_net(net, lambda: mb.publish({"at": 1, "x": "y"})), True)
    url, body, headers = net.sent[0]
    check("发到自己的 topic", url, f"{phone.NTFY}/topic-abc")
    check("标题标明是 state（页面靠 kind 区分状态和指令）",
          headers.get("Title"), "state")
    check("小包保持明文", "body" in json.loads(body.decode()), True)
    check("收回来解得开且内容一致",
          phone.unpack(PIN, body.decode())["body"], {"at": 1, "x": "y"})

    big = {"at": 1,
           "options": {"_labels": {f"MAA|Info.键{i}": f"中文标注{i}" for i in range(150)}},
           "plan": "明天早班要跑的东西" * 40}
    check("这份状态明文确实超过内联分界",
          len(phone.pack(PIN, big, "state").encode()) > phone.Mailbox.INLINE_MAX, True)

    net = FakeNet()
    net.queue.append(FakeResp(b"ok"))
    check("超线的状态照样发得出去", with_net(net, lambda: mb.publish(big)), True)
    wire = net.sent[0][1]
    check("能压进内联就压，省手机一次取附件", "gz" in json.loads(wire.decode()), True)
    check("压缩没丢东西：options 和 plan 都还在",
          phone.unpack(PIN, wire.decode())["body"], big)

    # Random text does not compress. This used to be the path where fields got dropped;
    # now it simply goes out whole and ntfy turns it into an attachment.
    import random

    random.seed(826)
    noise = "".join(random.choice("0123456789abcdef") for _ in range(20000))


    payload = {"at": 1, "plan": noise[:5000], "options": {"x": noise[5000:15000]},
               "config": {"MAA": {"关卡": "AT-4"}}}
    net = FakeNet()
    for _ in range(10):
        net.queue.append(FakeResp(b"ok"))
    with_net(net, lambda: mb.publish(payload))
    wires = [s[1] for s in net.sent]
    check("压不下去就切成多条，而不是走附件", len(wires) > 1, True)
    # Attachments expire after three hours; the state pushed before the machine shuts
    # down at night is exactly the one read the next morning. Ordinary messages last
    # twelve hours, so oversized states are split into those.
    check("每一条都在内联分界之内（不会被转成附件）",
          max(len(w) for w in wires) <= phone.Mailbox.INLINE_MAX, True)
    parts = [json.loads(w.decode()) for w in wires]
    check("每条都带同一个 sid", len({p["sid"] for p in parts}), 1)
    check("序号从 0 连到 n-1", [p["i"] for p in parts], list(range(len(parts))))
    check("每条都写明总共几条", {p["n"] for p in parts}, {len(parts)})
    check("每条的 pin 都在（半路截获也认不出内容）", {p["pin"] for p in parts}, {PIN})

    import base64 as _b64, gzip as _gz

    blob = "".join(p["gzp"] for p in sorted(parts, key=lambda x: x["i"]))
    back = json.loads(_gz.decompress(_b64.b64decode(blob)).decode("utf-8"))
    check("拼起来一个字段都不少", back, payload)
    check("明日安排还在", "plan" in back, True)
    check("选项表还在", "options" in back, True)

    print("\n[少一片就当没有：绝不把半份状态当完整的显示]")
    short = parts[:-1]
    blob2 = "".join(p["gzp"] for p in sorted(short, key=lambda x: x["i"]))
    broke = False
    try:
        _gz.decompress(_b64.b64decode(blob2 + "=" * (-len(blob2) % 4)))
    except Exception:  # noqa: BLE001
        broke = True
    check("缺一片就解不开，不会解出半份", broke, True)
    check("总数写在每一片上，凑没凑齐一看便知", short[0]["n"] > len(short), True)

    # One retry after a network exception (2026-09-18 19:27: the second of two boot
    # pieces hit a read timeout once, and the phone showed a 13-minute-old state until
    # shutdown). No wait in tests.
    mb.RETRY_AFTER = 0
    net = FakeNet()
    net.queue.append(urllib.error.URLError("网断了"))
    check("断一次、第二次通了：算发出去了",
          with_net(net, lambda: mb.publish({"at": 1})), True)
    check("确实发了两次", len(net.sent), 2)
    net = FakeNet()
    net.queue += [TimeoutError("读超时"), urllib.error.URLError("网断了")]
    check("连断两次返回 False，不抛（调用方才能去别的渠道)",
          with_net(net, lambda: mb.publish({"at": 1})), False)
    check("只试两次，不无限重试", len(net.sent), 2)
    net = FakeNet()
    net.queue.append(FakeResp(b"", status=500))
    check("服务器 500 也算没发出去",
          with_net(net, lambda: mb.publish({"at": 1})), False)
    check("服务器答了话就不重复发", len(net.sent), 1)

    # ---------------------------------------------------------------- fetch

    print("\n[fetch：PIN 不对的不执行、状态回音不当指令、执行过的不再执行一遍]")


    def ntfy_lines(*items) -> bytes:
        out = []
        for mid, msg in items:
            out.append(json.dumps({"id": mid, "event": "message", "message": msg},
                                  ensure_ascii=False))
        return ("\n".join(out) + "\n").encode()


    MB_STATE = tmpdir()
    mb2 = phone.Mailbox("topic-abc", PIN, MB_STATE)
    lines = ntfy_lines(
        ("m1", phone.pack(PIN, {"action": "run_now", "queue": "早班"})),
        ("m2", phone.pack("0000", {"action": "run_now", "queue": "晚班"})),
        ("m3", phone.pack(PIN, {"at": 1}, "state")),
        ("m4", "这不是 JSON"),
        ("m5", phone.pack(PIN, {"action": "skip_shutdown"})),
    )
    lines += json.dumps({"event": "keepalive"}).encode() + b"\n"
    net = FakeNet()
    net.queue.append(FakeResp(lines))
    got = with_net(net, lambda: mb2.fetch())
    check("只把 PIN 对的、kind=cmd 的当指令",
          bare(got), [{"action": "run_now", "queue": "早班"}, {"action": "skip_shutdown"}])
    check("每条带上从哪来（_meta：信封 ts、ntfy id、开机积压）",
          [(b["_meta"]["ntfy_id"], b["_meta"]["via"], isinstance(b["_meta"]["sent"], int)) for b in got],
          [("m1", "backlog", True), ("m5", "backlog", True)])
    check("请求里带上 poll=1（一次取完，不是轮询）",
          "poll=1" in net.sent[0][0], True)

    net = FakeNet()
    net.queue.append(FakeResp(lines))
    check("同一批消息第二次取：一条都不再执行（否则同一条指令跑两趟）",
          with_net(net, lambda: mb2.fetch()), [])
    check("记住的只有指令的 id，状态和坏消息不占名额（2026-09-15 名额被 watch 和状态挤满，旧指令重放）",
          sorted(mb2._seen), ["m1", "m5"])
    check("名额够一个早上的 watch 续租（8 分钟一条）用两周", phone.SEEN_KEEP >= 2000, True)

    net = FakeNet()
    net.queue.append(FakeResp(lines))
    check("换个新实例（下次开机）照样记得已经执行过",
          with_net(net, lambda: phone.Mailbox("topic-abc", PIN, MB_STATE).fetch()), [])

    net = FakeNet()
    net.queue.append(FakeResp(lines + ntfy_lines(
        ("m9", phone.pack(PIN, {"action": "debug_mode"})))))
    check("同一批里新来的那条要执行",
          bare(with_net(net, lambda: mb2.fetch())), [{"action": "debug_mode"}])

    net = FakeNet()
    net.queue.append(urllib.error.URLError("取不到"))
    check("取不到就返回空表，不抛", with_net(net, lambda: mb2.fetch()), [])

    net = FakeNet()
    check("没启用的信箱不取也不联网",
          (with_net(net, lambda: off.fetch()), net.sent), ([], []))

    # ---------------------------------------------------------------- listen

    print("\n[listen：长连接上收到的指令，同样要过 PIN 和去重]")

    got: list[dict] = []
    mb3 = phone.Mailbox("topic-abc", PIN, tmpdir())
    stream = ntfy_lines(
        ("s1", phone.pack("9999", {"action": "run_now"})),
        ("s2", phone.pack(PIN, {"at": 1}, "state")),
        ("s3", phone.pack(PIN, {"action": "run_now", "queue": "早班"})),
        ("s3", phone.pack(PIN, {"action": "run_now", "queue": "早班"})),
    )
    net = FakeNet()
    net.queue.append(FakeResp(stream))
    rounds = {"n": 0}


    def stop_after_first():
        # False while the stream is being consumed, True once it is exhausted.
        return rounds["n"] > 0 and not net.queue


    def on_cmd(body):
        got.append(body)
        rounds["n"] += 1


    with_net(net, lambda: mb3.listen(on_cmd, stop_after_first))
    check("PIN 不对的没被执行，状态回音没被执行，重复 id 只执行一次",
          bare(got), [{"action": "run_now", "queue": "早班"}])
    check("长连接收到的标 live", [b["_meta"]["via"] for b in got], ["live"])
    check("订阅带 since，重连时补得回漏掉的（不带就永远丢）",
          "since=" in net.sent[0][0], True)

    print("\n[close：停服务时要能立刻掐断连接，不然 STOP_PENDING 卡满 30 秒]")
    r = FakeResp(b"")
    mb3._resp = r
    mb3.close()
    check("连接被关掉", r.closed, True)
    check("关完把引用清掉", mb3._resp, None)
    mb3.close()
    check("重复关不抛", True, True)

    # ---------------------------------------------------------------- 心跳额度

    print("\n[心跳额度：ntfy 每 IP 每天 250 条，超了要放慢而不是继续闷头跳]")

    HB_STATE = tmpdir()
    posts: list[bytes] = []
    hb = phone.Heartbeat("topic-abc", HB_STATE, post=lambda p, t: posts.append(p))

    check("没人看的时候不算在线（租约没开）", hb.watched(), False)
    hb.watch()
    check("说了「我在看」就在租约内", hb.watched(), True)
    hb._lease = time.time() - 1
    check("租约过期就不再跳（没人看时一条都不发）", hb.watched(), False)

    check("没跳过时今天是 0", hb.sent_today(), 0)
    for _ in range(3):
        hb.beat()
    check("跳一次记一次", hb.sent_today(), 3)
    check("没到快档线用 30 秒间隔", hb.interval(), phone.HEARTBEAT_SEC)

    # The tiers follow everything sent today, not beats alone: on 10-02 the beat
    # counter said 196, nobody counted the 4-piece states, and 248 hit the 250.
    hb.quota.add("state", phone.HB_FAST_UNTIL - 3 - 1)
    check("差一条到快档线，还是快的", hb.interval(), phone.HEARTBEAT_SEC)
    hb.quota.add("state")
    check("状态片也算进去：到快档线就放慢到 5 分钟", hb.interval(), phone.HB_SLOW_SEC)
    hb.quota.add("state", phone.HB_SLOW_UNTIL - phone.HB_FAST_UNTIL)
    check("到慢档线再放慢到 30 分钟", hb.interval(), phone.HB_CRAWL_SEC)
    check("三档线都在 250 之内、从快到慢", 0 < phone.HB_FAST_UNTIL < phone.HB_SLOW_UNTIL < phone.NTFY_DAILY_LIMIT, True)
    check("慢档之后至少给状态留 60 条（15 份 4 片的状态）",
          phone.NTFY_DAILY_LIMIT - phone.HB_SLOW_UNTIL >= 60, True)
    check("放慢档确实慢一个量级",
          phone.HB_SLOW_SEC >= 10 * phone.HEARTBEAT_SEC, True)

    qf = hb.quota._file()
    qf.write_text("这不是 JSON", encoding="utf-8")
    check("账本坏了当 0，不抛（抛了整个心跳线程就死了）", (hb.sent_today(), hb.quota.total()), (0, 0))
    qf.unlink()
    check("账本没了当 0", hb.quota.total(), 0)
    # ntfy's day resets at midnight UTC (docs.ntfy.sh/config,
    # visitor-message-daily-limit) = 08:00 Beijing; keyed by the local date, 00-08
    # would land on the wrong day.
    from datetime import datetime as _dt, timezone as _tz
    _bj8 = _dt(2026, 10, 2, tzinfo=_tz.utc).timestamp()   # 2026-10-02 08:00 Beijing = 00:00 UTC
    check("北京 07:59 还算前一个 ntfy 日", phone.Quota.day(_bj8 - 60), "2026-10-01")
    check("北京 08:00 起算新的一天", phone.Quota.day(_bj8), "2026-10-02")
    check("账本按 UTC 日期分文件", phone.Quota.day() in qf.name, True)
    hb.quota.add("hb", 2)
    hb.quota.mark_full()
    check("full 标记不算进条数", hb.quota.total(), 2)

    dead = phone.Heartbeat("topic-abc", tmpdir(),
                           post=lambda *_: (_ for _ in ()).throw(OSError("网断了")))
    check("发失败返回 False", dead.beat(), False)
    check("发失败不许记数（否则网一断就自己把额度耗光）", dead.sent_today(), 0)

    full_posts = []
    fullhb = phone.Heartbeat("t", tmpdir(), post=lambda p, t: full_posts.append(p))
    fullhb.quota.mark_full()
    check("ntfy 说过今天额度用完（42908）：心跳不再去撞", (fullhb.beat(), full_posts), (False, []))

    # ---- The beat has to carry the cadence it is beating at ----
    # The page decides "no heartbeat for a while = powered off" from a fixed window.
    # Once the relay drops to one beat every 5 minutes, that verdict is wrong for
    # three and a half minutes out of every five - a red 「关机中」 while the queue
    # is running. The page cannot guess the cadence; this message is the only
    # place it can learn it.
    _sent = []
    _hb = phone.Heartbeat("t", tmpdir(), post=lambda payload, title: _sent.append(payload))
    check("正常节奏报 30", (_hb.beat(), _sent[-1]), (True, b"hb 30"))
    _hb.quota.add("state", phone.HB_FAST_UNTIL)
    check("过了快档线报 300", (_hb.beat(), _sent[-1]), (True, b"hb 300"))
    _hb.quota.add("state", phone.HB_SLOW_UNTIL - _hb.quota.total())
    check("过了慢档线报 1800", (_hb.beat(), _sent[-1]), (True, b"hb 1800"))
    check("报的就是 interval() 说的那个",
          _sent[-1].decode(), f"hb {_hb.interval()}")
    # 2026-10-06: past HB_STOP_AT the beat stops on ntfy altogether (COS only), so
    # the relay alone can never spend the 250 - the old crawl beat had no end.
    _hb.quota.add("state", phone.HB_STOP_AT - _hb.quota.total())
    _n = len(_sent)
    check("到停跳线（200）：ntfy 一跳都不发了", (_hb.beat(), len(_sent)), (False, _n))
    check("停跳线在慢档线之后、250 之前，给状态和手机留着",
          phone.HB_SLOW_UNTIL < phone.HB_STOP_AT < phone.NOTICE_STOP_AT < phone.NTFY_DAILY_LIMIT, True)

    # ---------------------------------------------------------------- state pieces in the ledger, no retry on 429

    print("\n[状态每一片都记进今天的账；429 不重试，一片失败剩下的不发]")


    def http_error(code: int, ntfy_code: int, text: str):
        body = json.dumps({"code": ntfy_code, "http": code, "error": text}).encode()
        return urllib.error.HTTPError("https://ntfy.sh/x", code, "Too Many Requests", {}, io.BytesIO(body))


    QSTATE = tmpdir()
    qmb = phone.Mailbox("topic-abc", PIN, QSTATE)
    qmb.RETRY_AFTER = 0
    net = FakeNet()
    with_net(net, lambda: qmb.publish(payload))      # the incompressible multi-piece state from above
    n_pieces = len(net.sent)
    check("每一片都记进今天的账", qmb.quota.count("state"), n_pieces)
    check("心跳和状态共用一本账（同一个 state 目录）",
          phone.Heartbeat("topic-abc", QSTATE).quota.total(), n_pieces)

    net = FakeNet()
    net.queue.append(http_error(429, 42908, "limit reached: daily message quota reached"))
    check("今天额度满：这份状态算没发出去", with_net(net, lambda: qmb.publish(payload)), False)
    check("第一片被拒，剩下的片不再发（缺一片手机也拼不起来）", len(net.sent), 1)
    check("429 不重试（10-02 晚上 52 片每片都白试了两次）", len(net.sent), 1)
    check("42908 记成「今天满了」，心跳就不去撞", qmb.quota.full(), True)
    check("被拒的不记账", qmb.quota.count("state"), n_pieces)

    RSTATE = tmpdir()
    rmb = phone.Mailbox("topic-abc", PIN, RSTATE)
    rmb.RETRY_AFTER = 0          # 42901 is retried after a pause now; no real wait in tests
    net = FakeNet()
    net.queue.append(http_error(429, 42901, "limit reached: too many requests"))
    with_net(net, lambda: rmb.publish({"at": 1}))
    check("请求太密（42901，几秒就回来）不当成今天满了", rmb.quota.full(), False)

    # ---------------------------------------------------------------- refreshes already answered

    print("\n[刷新：已经有一份状态答过它，就不再发一份（一份 4 条）]")

    pushed: list[str] = []
    pusher = phone.StatePusher(lambda why: pushed.append(why) or True)
    check("还没发过状态：刷新照常答", pusher.answered(time.time()), False)
    pusher("开机")
    t_done = pusher._done
    check("开机那份发出去了", pushed, ["开机"])
    check("关机期间按的刷新（开机读积压时才到）：开机那份已经答了",
          pusher.answered(t_done - 3 * 3600), True)
    check("App 4 秒后补的那次刷新：刚发完的那份答了",
          pusher.answered(t_done + 4), True)
    check("窗口之内不重发", pusher.answered(t_done + phone.REFRESH_ANSWERED_SEC), True)
    check("窗口之外照常答", pusher.answered(t_done + phone.REFRESH_ANSWERED_SEC + 1), False)
    check("不知道什么时候问的：按现在算", pusher.answered(None), True)
    check("窗口比页面和 App 订阅时回看的 30 秒短（since=30s），发过的那份一定回放得到",
          phone.REFRESH_ANSWERED_SEC < 30, True)
    pusher("改完配置")
    check("改完配置从不省：它带着页面要看的改动", pushed, ["开机", "改完配置"])

    failed = phone.StatePusher(lambda why: False)
    failed("开机")
    check("没发出去的那份不算答过", failed.answered(time.time()), False)

    print("\n[开机读积压：每条指令不再各发一份状态，读完合成一份]")
    pushed.clear()
    with pusher.held():
        pusher("改完配置")
        pusher("改完配置")
        pusher("红按钮")
        check("积压读着的时候一份都不发", pushed, [])
    check("读完合成一份", len(pushed), 1)
    check("合成的那份写清是哪几种、几次", pushed[0], "改完配置、红按钮（3 次合成一次）")
    pushed.clear()
    with pusher.held():
        pass
    check("积压里没有要发的：一份都不多发", pushed, [])

    print("\n[停止前 / 关机前 never wait inside a held batch (status-channel audit A1)]")
    # SvcStop runs on its own thread while the engine's drain or the late backlog holds;
    # folded in, the stop push lost its exact label and went out after the kill timer.
    import threading
    pushed.clear()
    inside, release = threading.Event(), threading.Event()


    def _holder():
        with pusher.held():
            pusher("改完配置")
            inside.set()
            release.wait(5)


    th = threading.Thread(target=_holder)
    th.start()
    inside.wait(5)
    check("停止前 sent at once while another thread holds", pusher(phone.STOP_WHY), True)
    check("关机前 sent at once while another thread holds", pusher("关机前"), True)
    check("both went out under their own label", pushed, [phone.STOP_WHY, "关机前"])
    release.set()
    th.join(5)
    check("the held batch keeps only its own push", pushed, [phone.STOP_WHY, "关机前", "改完配置"])

    # ---------------------------------------------------------------- what the mailbox could not read

    print("\n[关机超过 ntfy 的 12 小时：读不到的那一段要记下来、带进状态，不能悄悄丢]")
    from ark_relay.core.statestore import StateStore


    def mark_on_disk(d):
        return StateStore(Path(d)).get("queues", "phone_mark")


    check("ntfy 只留 12 小时（https://docs.ntfy.sh/config/ cache-duration 默认 12h）",
          phone.NTFY_CACHE_SEC, 12 * 3600)

    B0 = tmpdir()
    fresh = phone.Mailbox("topic-abc", PIN, B0)
    check("头一次开机（盘上没记过读到哪儿）：不报空窗", fresh.blind, None)
    check("没有空窗时状态里是空表", phone.mailbox_status(B0), [])

    B1 = tmpdir()
    now = int(time.time())
    StateStore(B1).set("queues", "phone_mark", now - 13 * 3600)
    mb_gap = phone.Mailbox("topic-abc", PIN, B1)
    check("上次读到 13 小时前：记下一段读不到的",
          bool(mb_gap.blind) and mb_gap.blind["from"] == now - 13 * 3600, True)
    check("空窗止于开机读的时刻往前 12 小时",
          bool(mb_gap.blind) and abs(mb_gap.blind["to"] - (now - 12 * 3600)) <= 5, True)
    st = phone.mailbox_status(B1)
    check("状态里带着这一段（从 / 到 / 开机，unix 秒）",
          [(g["从"], abs(g["到"] - (now - 12 * 3600)) <= 5, abs(g["开机"] - now) <= 5) for g in st],
          [(now - 13 * 3600, True, True)])
    check("机器核对也看得到（report 带 blind）", mb_gap.report()["blind"], mb_gap.blind)
    snapshot.read_runtime, plan.next_plan = (lambda: dict(FULL)), (lambda automas_dir: "")
    try:
        check("state_payload 的 relay 里有「信箱空窗」",
              phone.state_payload(cfg, B1)["relay"].get("信箱空窗"), st)
    finally:
        snapshot.read_runtime, plan.next_plan = saved_read, saved_plan

    mb_gap._note_blind(now + 3600)
    kept = StateStore(B1).get("queues", "phone_blind")
    check("开机读没成、补读时更晚：同一次开机的空窗变长，只留一段",
          [(g["from"], abs(g["to"] - (now - 11 * 3600)) <= 5) for g in kept], [(now - 13 * 3600, True)])

    B2 = tmpdir()
    StateStore(B2).set("queues", "phone_mark", now - 11 * 3600)
    check("上次读到 11 小时前：ntfy 还留着，不报空窗", phone.Mailbox("topic-abc", PIN, B2).blind, None)

    check("没启用的信箱不判断空窗",
          phone.Mailbox("", "", B1).blind, None)

    B3 = tmpdir()
    StateStore(B3).set("queues", "phone_blind",
                       [{"from": i, "to": i + 1, "boot": i + 2} for i in range(phone.BLIND_KEEP)])
    StateStore(B3).set("queues", "phone_mark", now - 20 * 3600)
    phone.Mailbox("topic-abc", PIN, B3)
    kept = StateStore(B3).get("queues", "phone_blind")
    check(f"最多留 {phone.BLIND_KEEP} 段，新的那段在最后",
          (len(kept), kept[-1]["from"]), (phone.BLIND_KEEP, now - 20 * 3600))

    print("\n[读到哪儿要落盘：开机读完、长连接每 10 分钟、关通道时]")
    B4 = tmpdir()
    mb_mark = phone.Mailbox("topic-abc", PIN, B4)
    net = FakeNet()
    net.queue.append(FakeResp(json.dumps({"event": "message", "id": "x1", "time": now - 3 * 3600,
                                          "message": phone.pack(PIN, {"at": 1}, "state")}).encode() + b"\n"))
    with_net(net, lambda: mb_mark.fetch())
    check("开机读完：落盘的是问的那一刻（最新一条更早也一样）",
          abs((mark_on_disk(B4) or 0) - (now - 300)) <= 5, True)
    saved = mark_on_disk(B4)
    mb_mark._mark = saved + 60
    mb_mark._save_mark()
    check("长连接上 10 分钟内的 keepalive 不写盘", mark_on_disk(B4), saved)
    mb_mark._mark = saved + phone.MARK_SAVE_SEC
    mb_mark._save_mark()
    check("满 10 分钟写一次", mark_on_disk(B4), saved + phone.MARK_SAVE_SEC)
    mb_mark._mark = saved + phone.MARK_SAVE_SEC + 30
    mb_mark.close()
    check("关通道（停服务）时把最新读到的写下", mark_on_disk(B4), saved + phone.MARK_SAVE_SEC + 30)
    check("下次开机读到的是上次写下的",
          phone.Mailbox("topic-abc", PIN, B4)._prev_mark, saved + phone.MARK_SAVE_SEC + 30)

    net = FakeNet()
    net.queue.append(urllib.error.URLError("取不到"))
    B5 = tmpdir()
    with_net(net, lambda: phone.Mailbox("topic-abc", PIN, B5).fetch())
    check("开机读没成：不写读到哪儿（不然下次会把没读的当读过）", mark_on_disk(B5), None)

    # ---------------------------------------------------------------- a whole day's count

    print("\n[一天的账：照 10-02 那样开着 App 测一晚上，也落在 250 以内]")
    # The real state size: 43 KB on 10-02, 13003 bytes gzipped, 4 pieces
    # (relay.log 10-02 17:02:18, 「状态 43465 字节，压缩到 13003 字节」 / 「切成 4 条」).
    import os as _os
    _big = {"at": 1, "options": {"x": _b64.b64encode(_os.urandom(9600)).decode()}}   # incompressible; ~13 KB as gzip+base64
    _net = FakeNet()
    with_net(_net, lambda: phone.Mailbox("t", PIN, tmpdir()).publish(_big))
    PIECES = len(_net.sent)
    check("一份 13 KB 的状态是 4 片（和线上一样）", PIECES, 4)

    day = phone.Heartbeat("t", tmpdir(), post=lambda p, t: None)
    states = [0]


    def push_state_sim():
        states[0] += 1
        day.quota.add("state", PIECES)


    # 10-02's day: two boots and one shutdown state; from 17:00 the App stays open
    # for 4 hours (a watch every 8 minutes); 21 refresh presses, each re-asked by
    # the App 4 s later (answered once); 5 config changes.
    for _ in range(3):
        push_state_sim()
    OPEN_S = 4 * 3600
    refresh_at = {int(i * OPEN_S / 21) for i in range(21)}
    config_at = {int((i + 0.5) * OPEN_S / 5) for i in range(5)}
    last_beat = -10 ** 9
    for t in range(OPEN_S):
        if t in refresh_at or t in config_at:
            push_state_sim()
        if t - last_beat >= day.interval():
            day.quota.add("hb")
            last_beat = t
    push_state_sim()          # before shutdown
    total = day.quota.total()
    print(f"    （模拟：{states[0]} 份状态 × {PIECES} 片 + {day.quota.count('hb')} 跳 = {total} 条）")
    check("整天落在 250 以内，还留着至少 20 条余量", total <= phone.NTFY_DAILY_LIMIT - 20, True)

    print("\n[state folder not writable: the quota WARNING still goes once (status-channel audit A4)]")
    # _write swallows OSError, so the day's `full` flag never reached the disk and every
    # later 42908 sent another group WARNING.
    import logging
    _warns: list = []


    class _Count(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING:
                _warns.append(record.getMessage())


    _qlog = phone.log
    _qh = _Count()
    _qlog.addHandler(_qh)
    try:
        nowrite = tmpdir() / "file-not-folder"
        nowrite.write_text("x", encoding="utf-8")       # mkdir under a file fails
        qa, qb = phone.Quota(nowrite / "state"), phone.Quota(nowrite / "state")
        first, second, other = qa.mark_full("a"), qa.mark_full("b"), qb.mark_full("c")
    finally:
        _qlog.removeHandler(_qh)
    check("the first call notes it", first, True)
    check("a second call does not", second, False)
    check("nor the other Quota on the same folder (mailbox / heartbeat)", other, False)
    check("one WARNING", sum("额度用完" in m for m in _warns), 1)
    check("full() holds for the day", (qa.full(), qb.full(), qa.stops_beats()), (True, True, True))

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_phone_state_cos():
    """The whole state on Tencent COS, one notice on ntfy (the user, 2026-10-02 22:22).

The loss this guards against: states eating ntfy's 250 a day (10-02: a state
was 4 pieces; 13 states + 196 beats = 248, and from 19:19 the phone could not
see the machine). Now the envelope is PUT to COS whole and the topic only gets
one line, `state <ts> <bytes>`.

Pinned here:
* what is stored is the envelope that would have gone to ntfy (PIN inside, the
  App decodes it as before);
* the object is public-read, never cached, named from the topic the same way
  the App names it (lower-case, first 32 hex of sha256);
* stored -> one short notice on ntfy, one message on the ledger;
* not stored (refused / no network) -> the old pieces, nothing lost;
* a machine without COS -> exactly the old path.
Fake network throughout.

    Formerly test_phone_state_cos.py.
    """
    import hashlib
    import io
    import json
    import time
    import types
    import urllib.error

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import phone
    from ark_relay.features import phone as phone_cos_store, phone as phone_heartbeat, phone as phone_mailbox, phone as phone_quota
    from ark_relay.features.evidence import Cos

    PIN = "8964"
    TOPIC = "topic-abc"


    class FakeResp:
        def __init__(self, body: bytes = b"", status: int = 200):
            self.status = status
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self._body


    class FakeNet:
        """Records every request (url, method, body, headers); canned answers in order."""

        def __init__(self, *answers):
            self.sent: list[tuple[str, str, bytes, dict]] = []
            self.queue = list(answers)

        def urlopen(self, req, timeout=None):
            self.sent.append((req.full_url, req.get_method(), req.data or b"",
                              {k.lower(): v for k, v in req.header_items()}))
            if not self.queue:
                return FakeResp()
            nxt = self.queue.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt


    # phone.py's network code lives in these sibling modules; each reads its own urllib.
    NET_MODULES = (phone_quota, phone_cos_store, phone_mailbox, phone_heartbeat)


    def with_net(net, fn):
        saved = [m.urllib for m in NET_MODULES]
        fake = types.SimpleNamespace(
            request=types.SimpleNamespace(Request=saved[0].request.Request, urlopen=net.urlopen),
            error=urllib.error)
        for m in NET_MODULES:
            m.urllib = fake
        try:
            return fn()
        finally:
            for m, s in zip(NET_MODULES, saved, strict=True):
                m.urllib = s


    COS = Cos("AKIDtest", "secret", "ark-evidence-1", "ap-shanghai")
    # A state the size of 10-02's (43 KB raw): random text so gzip cannot fold it
    # under the 4096-byte inline limit.
    import random

    random.seed(7)
    BIG = {"at": 1790000000, "options": {f"k{i}": "".join(random.choice("abcdefghijk甲乙丙丁")
                                                          for _ in range(40)) for i in range(400)}}

    print("[对象名：由 topic 推出，App 算的是同一个]")
    key = phone.state_key(TOPIC)
    check("state/ 下、sha256(topic) 前 32 位、.json",
          key, "state/" + hashlib.sha256(TOPIC.encode()).hexdigest()[:32] + ".json")
    check("大小写、首尾空格不影响（App 存 topic 时转小写、去空格）",
          phone.state_key("  TOPIC-ABC \n"), key)
    check("名字里看不出 topic", TOPIC in key, False)

    print("\n[state_cos：机器没配 COS 就是老路子]")
    cfg_none = types.SimpleNamespace(cos_secret_id="", cos_secret_key="", cos_bucket="", cos_region="")
    check("缺 COS_* 时返回 None", phone.state_cos(cfg_none), None)
    cfg_all = types.SimpleNamespace(cos_secret_id="a", cos_secret_key="b",
                                    cos_bucket="ark-evidence-1", cos_region="ap-shanghai")
    c = phone.state_cos(cfg_all)
    check("配齐了给出这个桶的客户端", (c.host, c.prefix), ("ark-evidence-1.cos.ap-shanghai.myqcloud.com", ""))

    print("\n[大状态：整份进 COS，ntfy 只发一条通知]")
    mb = phone.Mailbox(TOPIC, PIN, tmpdir(), cos=COS)
    net = FakeNet()
    t0 = int(time.time())
    check("发出去了", with_net(net, lambda: mb.publish(BIG)), True)
    check("一共两次请求：一次 PUT 到 COS，一次 POST 到 ntfy",
          [(m, u.split("/")[2]) for u, m, _, _ in net.sent],
          [("PUT", COS.host), ("POST", "ntfy.sh")])
    url, _, put_body, put_h = net.sent[0]
    check("PUT 到 state_key", url, f"https://{COS.host}/{key}")
    check("对象公开读（App 没有 COS 密钥）", put_h.get("x-cos-acl"), "public-read")
    check("不许缓存（不然 App 读到旧状态）", put_h.get("cache-control"), "no-store")
    check("带签名", put_h.get("authorization", "").startswith("q-sign-algorithm=sha1&q-ak=AKIDtest"), True)
    back = phone.unpack(PIN, put_body.decode("utf-8"))
    check("存上去的就是 ntfy 那份信封：PIN 对得上、kind=state、解出来一字不差",
          (back or {}).get("kind"), "state")
    check("……body 原样", (back or {}).get("body"), BIG)
    def no_ts(raw):
        d = json.loads(raw)
        d.pop("ts", None)
        return d


    check("……就是 pack(gz=True) 那一份（除了时间戳，一字节不差）",
          no_ts(put_body), no_ts(phone.pack(PIN, BIG, "state", gz=True)))
    check("确实压了（gz 字段）", "gz" in json.loads(put_body), True)
    _, _, note, note_h = net.sent[1]
    parts = note.decode("ascii").split(" ")
    check("通知格式 `state <ts> <字节数>`", (parts[0], len(parts)), ("state", 3))
    check("通知里的时间是这次发的", abs(int(parts[1]) - t0) <= 2, True)
    check("通知里的字节数就是对象的大小", int(parts[2]), len(put_body))
    check("通知很短（远在 4096 之内）", len(note) < 64, True)
    check("通知的 Title 还是 state", note_h.get("title"), "state")
    check("通知不是 JSON：老页面、老中继 unpack 都当没看见", phone.unpack(PIN, note.decode()), None)
    check("ntfy 额度只记了一条", mb.quota.count("state"), 1)

    print("\n[小状态：也存 COS（开 App 时读得到最新的），ntfy 照旧发整条，老 App 不受影响]")
    mb_s = phone.Mailbox(TOPIC, PIN, tmpdir(), cos=COS)
    net = FakeNet()
    check("发出去了", with_net(net, lambda: mb_s.publish({"at": 1})), True)
    check("PUT 一次 + 整条状态一次", [m for _, m, _, _ in net.sent], ["PUT", "POST"])
    check("ntfy 上那条就是对象本身", net.sent[1][2], net.sent[0][2])

    print("\n[COS 存不上：照旧切片发，什么都不丢]")
    # A connection that is down is tried again inside the 8 s (netretry, dispatch
    # relay-opt-round3-1108 O-03); COS's own answers (403, 302) are not.
    from ark_relay.core import notify as netretry
    netretry._sleep = lambda s: None
    for label, errs, puts in (("COS 拒绝（403）", [urllib.error.HTTPError(
            f"https://{COS.host}/{key}", 403, "Forbidden", {}, io.BytesIO(b""))], 1),
            ("连不上 COS", [urllib.error.URLError("网断了")] * netretry.ATTEMPTS, netretry.ATTEMPTS),
            ("COS 回的不是 2xx（302）", [FakeResp(status=302)], 1)):
        mb_f = phone.Mailbox(TOPIC, PIN, tmpdir(), cos=COS)
        net = FakeNet(*errs)
        ok = with_net(net, lambda: mb_f.publish(BIG))
        posts = [b for u, m, b, _ in net.sent if m == "POST"]
        check(f"{label}：还是发出去了", ok, True)
        check(f"{label}：PUT 试了 {puts} 次", sum(1 for _, m, _, _ in net.sent if m == "PUT"), puts)
        check(f"{label}：退回切片（多条，每条带 gzp）",
              len(posts) > 1 and all("gzp" in json.loads(p) for p in posts), True)

    print("\n[没配 COS 的机器：完全是老路子，不碰 COS]")
    mb_n = phone.Mailbox(TOPIC, PIN, tmpdir())
    net = FakeNet()
    with_net(net, lambda: mb_n.publish(BIG))
    check("一次 PUT 都没有", [m for _, m, _, _ in net.sent if m == "PUT"], [])
    check("照旧切片", len(net.sent) > 1, True)

    print("\n[只有状态进 COS：指令、bye 之类不碰]")
    net = FakeNet()
    with_net(net, lambda: mb.publish({"action": "x"}, kind="cmd"))
    check("kind=cmd 不 PUT", [m for _, m, _, _ in net.sent], ["POST"])

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_receipt_target():
    """A receipt says when its order was sent to the second and which setting or queue it was about
(audit 11-08 D-07, relay side; dispatch relay-opt-round6-1108 R6-04; modes.add_receipt,
phone_channel.receipt_target).

Before: "sent" was 「MM-dd HH:mm」 and "action" the only other key, so a save of several
settings at once - set_master / set_config pressed within one minute - gave receipts the App
could not tell apart. Pinned here:

* "ts" is the send time in seconds beside the old "sent"; "target" names
  set_master game:path, set_config script:path, skip_today / unskip_today the queue;
* neither key is written when there is nothing to say, and every older key is unchanged;
* _phone_execute hands its receipt the target of the order it ran.

    Formerly test_receipt_target.py.
    """
    import json
    import logging
    import types

    # phone_channel imports win32event at module level (Windows only); nothing here calls it.
    sys.modules.setdefault("win32event", types.ModuleType("win32event"))

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import modes
    from ark_relay.features import phone as phone_channel


    T = 1762570800     # 2026-11-08 11:00:00 Beijing

    print("[一次保存两项：同一分钟、同一个动作，靠 ts 和 target 分得开]")
    sd = tmpdir()
    modes.add_receipt(sd, "set_master", True, "刷取关卡：TO-5", sent=T, target="终末地:AutoEssence/AutoEssenceMenu")
    modes.add_receipt(sd, "set_master", True, "领取方式：单倍领取", sent=T + 1, target="终末地:AutoEssence/AutoEssenceObtainMode")
    got = json.loads((sd / modes._RECEIPTS).read_text(encoding="utf-8"))
    check("同一分钟", [r["sent"] for r in got], [got[0]["sent"]] * 2)
    check("秒戳分得开", [r["ts"] for r in got], [T, T + 1])
    check("目标分得开", [r["target"] for r in got], ["终末地:AutoEssence/AutoEssenceMenu",
                                                   "终末地:AutoEssence/AutoEssenceObtainMode"])
    check("原来的键都还在", sorted(got[0]), sorted(["at", "action", "ok", "text", "sent", "ts", "target"]))

    print("\n[没有发送时间、没有目标：不写这两项（形状和以前一样）]")
    sd = tmpdir()
    modes.add_receipt(sd, "refresh", True, "已刷新")
    check("只有原来的键", sorted(json.loads((sd / modes._RECEIPTS).read_text(encoding="utf-8"))[0]),
          sorted(["at", "action", "ok", "text"]))

    print("\n[哪种指令的目标是什么]")
    rt = phone_channel.receipt_target
    check("set_master", rt({"action": "set_master", "game": "终末地", "path": "AutoEssence/AutoEssenceMenu"}),
          "终末地:AutoEssence/AutoEssenceMenu")
    check("set_config", rt({"action": "set_config", "script": "MaaEnd", "path": "Task.IfSanity"}), "MaaEnd:Task.IfSanity")
    check("skip_today", rt({"action": "skip_today", "queue": "晚班"}), "晚班")
    check("unskip_today", rt({"action": "unskip_today", "queue": "早班"}), "早班")
    check("别的指令：没有", rt({"action": "run_now", "queue": "早班"}), "")

    print("\n[_phone_execute 把它跑的那条指令的目标交给回执]")
    seen = []
    phone_channel._phone_execute(lambda body: (True, "改好了"), type("N", (), {"send": lambda *a, **k: []})(),
                                 logging.getLogger("ark.test_phone"), lambda *a, **k: None,
                                 lambda a, s, ok, msg, **k: seen.append((a, s, k.get("target"))),
                                 {"action": "set_config", "script": "MAA", "path": "Stage.Stage", "value": "1-7"},
                                 "set_config", T, True)
    check("回执带上了目标", seen, [("set_config", T, "MAA:Stage.Stage")])


def _part_channel_down():
    """A channel that refuses a send is announced every time it refuses one.

From 2026-08-22 until 2026-10-06 the same fault was announced once (a record on
disk, keyed by the error with 企业微信's hint and egress IP stripped, so that a
day of relay restarts did not repeat it). The user's order of 2026-10-06, every
error to the group, every time (「不论多少次什么错误都要发」), ended that.
Pinned: each refused send is announced over the channels still
working; the per-channel log line comes with it, marked as already in the group
only when the group robot took the notice (errwatch does not push it twice).

    Formerly test_channel_down.py.
    """
    import json, os, sys

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP),
                      SERVERCHAN_KEY="", WECOM_CORPID="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import Config
    from ark_relay.core.notify import Notifier


    ERR1 = ("企业微信发送失败: 60020 not allow to access from your ip, "
            "hint: [1787373915609110759172198], from ip: 112.43.40.209")
    ERR2 = ("企业微信发送失败: 60020 not allow to access from your ip, "
            "hint: [9999999999999999999999999], from ip: 112.43.40.77")

    cfg = Config()

    import logging
    from ark_relay.features import errwatch
    from ark_relay.core import notify as _notify_mod

    lines = []
    class _Lines(logging.Handler):
        def emit(self, record):
            lines.append((record.getMessage(), getattr(record, errwatch.PUSHED, False)))
    _notify_mod.log.addHandler(_Lines())

    print("[every refused send is announced - the same fault again included]")
    sent = []
    class Cap(Notifier):
        # Keyword names must match the real signature, or a routing change goes astray here silently.
        def _fan_out(self, title, body, *, order=None, stop_on_first=False):
            sent.append(title)
            return list(self.took), {}

    n = Cap(cfg)
    n.took = ["Server酱"]
    n._announce_outage({"企业微信": ERR1}, ["Server酱"])
    check("first refusal announced", len(sent), 1)
    n._announce_outage({"企业微信": ERR2}, ["Server酱"])
    check("the same fault again: announced again", len(sent), 2)
    n2 = Cap(cfg)
    n2.took = ["Server酱"]
    n2._announce_outage({"企业微信": ERR1}, ["Server酱"])
    check("after a restart too", len(sent), 3)
    check("nothing kept on disk to stay quiet with",
          "channels_down" in json.loads((TMP / "state.json").read_text(encoding="utf-8")).get("queues", {})
          if (TMP / "state.json").exists() else False, False)
    check("the title names the channel", sent[-1], "🔌 推送通道故障：企业微信")

    print("\n[the log line for each refusal]")
    lines.clear()
    n._announce_outage({"企业微信机器人": "boom"}, ["Server酱"])
    check("one line per refusal", [m for m, _ in lines], ["企业微信机器人推送失败: boom"])
    check("the notice went by Server酱 only: errwatch still pushes the line", lines[0][1], False)
    lines.clear()
    n.took = ["企业微信机器人"]
    n._announce_outage({"Server酱": "boom"}, ["企业微信机器人"])
    check("the group robot took the notice: the line is marked as already in the group", lines[0][1], True)


def _part_cli_commands():
    """The two new CLI commands exist, parse, and hand off to the right code.

`collect-retry` and `evidence` are what I run by hand to verify the relay's
new work on the machine; if the parser or the dispatch breaks, the manual
verification path is gone and nobody notices until the next incident.

    Formerly test_cli_commands.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay import __main__ as cli
    from ark_relay.features import collect_retry
    import argparse


    print("[evidence 命令：没配置的脚本什么也传不了，退出码 1，但不炸]")
    class Cfg:
        state_dir = tmpdir() / "state"; maaend_dir = None; maa_dir = None; okww_dir = None; history_dir = None
    Cfg.state_dir.mkdir(parents=True)
    rc = cli.cmd_evidence(Cfg, "MaaEnd", "", hours=2)     # a window is mandatory: the last two hours
    check("没东西可传就是 1", rc, 1)
    try:
        cli.cmd_evidence(Cfg, "MaaEnd", "2026-09-11/endfield/MaaEnd-06-17-17"); no_run = "accepted"
    except SystemExit as exc:
        no_run = str(exc)
    check("账本里没有那趟就拒绝，不悄悄全量", "--hours" in no_run)
    check("索引仍然写了一行", (Cfg.state_dir / "evidence" / "index.jsonl").exists())

    print("\n[collect-retry 命令：走的是 maybe_run，没有失败路线就说没有]")
    calls = []
    class FakeEng:
        pass
    cli._build_local_engine = lambda cfg: FakeEng()
    orig = collect_retry.maybe_run
    collect_retry.maybe_run = lambda eng, day=None: calls.append((eng, day)) or False
    try:
        rc = cli.cmd_collect_retry(Cfg, "2026-09-11")
    finally:
        collect_retry.maybe_run = orig
    check("调用了一次 maybe_run，带指定的日期", calls and calls[0][1] == "2026-09-11" and len(calls) == 1)
    check("退出码 0", rc, 0)

    print("\n[banners 命令：打印那一段、来源和核对，扣下的行让退出码变 1]")
    from ark_relay.features import banners as _bn
    from datetime import datetime, timedelta
    import io, contextlib
    def fake_collect(now, *, skland_token="", failed=None, notes=None, trace=None, **_):
        # The end is relative: a fixed 09-29 11:59:59 made this fail from that noon on,
        # when the pool was no longer current (2026-09-29).
        b = _bn.Banner("鸣潮", "身赴三途", ("景燃",), datetime(2026, 9, 10, 10, 0),
                       datetime.now().replace(microsecond=0) + timedelta(days=10))
        trace.ends |= _bn._stamps(b.end)
        trace.src("鸣潮", "当期", "库街区", "身赴三途 景燃")
        trace.checks.append("鸣潮：库街区=游戏公告 ✓")
        trace.problems.append("鸣潮｜版本资讯｜B 站｜BiliFeedProblem: page 1 listed nothing")
        notes["明日方舟"] = "09-18 03:59 之后开（还有 5 天）　下一池官方还没公告"
        return [b], {}
    orig_collect = _bn.collect
    _bn.collect = fake_collect
    Cfg.skland_token = ""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = cli.cmd_banners(Cfg)
    finally:
        _bn.collect = orig_collect
    out = buf.getvalue()
    check("打印了当期行", "身赴三途 · 景燃" in out)
    check("打印了来源", "库街区｜身赴三途 景燃" in out)
    check("编出来的预告被扣下并列出", "扣下的行" in out and "09-18 03:59 之后开" in out)
    check("有扣下的行时退出码 1", rc, 1)
    check("来源问题单列出来", "--- source problems" in out and "BiliFeedProblem: page 1 listed nothing" in out)

    print("\n[参数表认得这几个命令]")
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["local", "check", "test", "report", "collect-retry", "evidence", "banners"])
    check("choices 里有", set(p._actions[1].choices) >= {"collect-retry", "evidence", "banners"})


def _part_cmd_test_channels():
    """`python -m ark_relay test` must try every channel and name only the ones that took it.

Audit s5 #3 (2026-10-13): cmd_test called send(alert=True), which stops at the first
channel that accepts, yet printed 「✅ 已通过 <every configured channel> 发出」; and it
filed the test as a real group alarm (alerts/ copy). Channels are faked here.

    Formerly test_cmd_test_channels.py.
    """
    import contextlib
    import io
    import os


    os.environ.update(ARK_STATE_DIR=str(tmpdir()), ARK_HISTORY_DIR=str(tmpdir()))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay import __main__ as relay_main
    from ark_relay.core import notify
    from ark_relay.core.config import Config


    class Chan:
        def __init__(self, ok):
            self.enabled, self.ok, self.got = True, ok, []

        def send_text(self, *a):
            if not self.ok:
                raise RuntimeError("refused")
            self.got.append(a)


    bot, sc = Chan(True), Chan(False)
    copied: list = []
    real_init = notify.Notifier.__init__


    def fake_init(self, cfg):
        real_init(self, cfg)
        self.wecom_bot, self.serverchan = bot, sc
        self.wecom = Chan(True)
        self.wecom.enabled = False


    notify.Notifier.__init__ = fake_init
    notify.Notifier._copy_alarm = lambda self, t, b: copied.append(t)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = relay_main.cmd_test(Config())
    text = out.getvalue()
    print(text)

    print("[the robot takes it, Server酱 refuses]")
    check("Server酱 was tried too", (len(bot.got), "Server酱: refused" in text), (1, True))
    check("success names only the robot", "✅ 已通过 企业微信机器人 发出" in text, True)
    check("Server酱 is not named as delivered", "企业微信机器人、Server酱" in text, False)
    check("a refused channel fails the self-test", rc, 1)
    check("not filed as a group alarm", copied, [])

    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")


def _part_command_table():
    """relay/README.md 的命令表必须和代码里的白名单一一对上。

2026-09-08 审出来的：表里说 `run_now` 是「没实现、会明确拒绝」，代码里它真会调
`/api/dispatch/start` 派发一趟队列；`skip_shutdown`、`weekly_boss`、`set_config`、
`set_master` 四个命令干脆不在表里——其中 skip_shutdown 就是「吃掉下一次关机机会
且不带时效」的那个开关，已经让机器白开两夜，而唯一一张说明表里找不到它。

文档和代码分头维护，早晚会分家。这条测试让它们分不了家。

    Formerly test_command_table.py.
    """
    import re

    ROOT = Path(__file__).resolve().parents[1]
    code = (ROOT / "ark_relay" / "features" / "commands.py").read_text(encoding="utf-8")
    doc = (ROOT / "README.md").read_text(encoding="utf-8")

    allowed = set()
    for m in re.finditer(r"^(REVERSIBLE|MUTATING) = \{([^}]*)\}", code, re.M | re.S):
        allowed |= {x.strip().strip('"') for x in m.group(2).split(",") if x.strip()}
    listed = set(re.findall(r"^\| `(\w+)` \|", doc, re.M))

    if not allowed:
        fails.append("没从 commands.py 里读出白名单——正则该跟着代码改")
    missing = sorted(allowed - listed)
    extra = sorted(listed - allowed)
    if missing:
        fails.append(f"命令表漏了：{missing}（代码认，文档没写）")
    if extra:
        fails.append(f"命令表多了：{extra}（文档写了，代码不认）")

    print(f"  代码白名单 {len(allowed)} 个，文档表 {len(listed)} 个")
    for f in fails:
        print(f"  ✗ {f}")
    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_commands_gates():  # noqa: C901
    """往生产配置里写东西的那条路——四道闸门一道都不许塌。

这个文件防的是**一类损失：配置被写坏，于是刷错关卡、烧掉理智药**。
826 就是这么来的：凭空造了一个字段、编了一个下标的含义，写进去，第二天早班
按错的配置跑了一整趟。`commands.py` 25 个函数里 19 个从来没有被任何测试调用过，
包括「结构化 diff 不符预期就回滚」这道唯一能拦住 826 的闸门本身。

四道闸门（relay/README.md「命令的四道闸门」）：
  ① 白名单——不在表里的动作直接拒，模型不许自己发 JSON patch
  ② 人工确认——会写盘的动作没确认不动手
  ③ 落地校验——备份→改→解析→结构化 diff，多改一个字段就整个放弃并回滚
  ④ 回报——成功、失败、拒绝都要说出来，而且要说人话

外加一条同样致命的：白名单里有名字、apply_command 里却没有分支，
手机上按下去什么也不会发生，而屏幕上一片绿。

全程用临时目录里的假配置，`_mas` 换成假的，不碰网络、不碰真机。

    Formerly test_commands_gates.py.
    """
    import json
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    STATE = tmpdir()
    AUTOMAS = tmpdir()
    os.environ["ARK_STATE_DIR"] = str(STATE)
    os.environ["ARK_AUTOMAS_DIR"] = str(AUTOMAS)

    from datetime import datetime
    from ark_relay.features import commands
    from ark_relay.features import modes
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore


    # The real config's shape, cut down to what these gates touch: one script uuid,
    # one user uuid, Info/* per user and Game/WaitTime per script (docs/CONFIG.md).
    SID = "59da8762-8fa7-4f2b-9c1e-000000000001"
    UID = "b0c1d2e3-0000-0000-0000-000000000002"


    def sample() -> dict:
        return {SID: {
            "Info": {"Name": "MAA"},
            "Game": {"WaitTime": 60},
            "SubConfigsInfo": {"UserData": {UID: {"Info": {
                "Stage": "AT-4", "StageMode": "Fixed", "MedicineNumb": 0,
                "Annihilation": "Close", "RunTimesLimit": 3}}}}}}


    CFG = AUTOMAS / "config" / "ScriptConfig.json"


    def reset_cfg(data: "dict | None" = None) -> str:
        CFG.parent.mkdir(parents=True, exist_ok=True)
        for old in CFG.parent.glob("ScriptConfig.json.bak-*"):
            old.unlink()
        raw = json.dumps(data if data is not None else sample(),
                         ensure_ascii=False, indent=2)
        CFG.write_text(raw, encoding="utf-8")
        return raw


    def cfg_raw() -> str:
        return CFG.read_text(encoding="utf-8")


    def backups() -> list[Path]:
        return sorted(CFG.parent.glob("ScriptConfig.json.bak-*"))


    # ---------------------------------------------------------------- 闸门 ①

    print("[闸门① 白名单：不在表里的动作一律拒绝]")
    for bad in ("format_disk", "poweroff_now", "", "SET_STAGE", "set stage",
                "run_now; rm -rf", "set_config2", None, 123):
        ok, msg = commands.apply_command({"action": bad, "confirmed": True})
        check(f"拒绝 {bad!r}", (ok, "不在允许的清单里" in msg), (False, True))
        check(f"拒绝 {bad!r} 的话里不带原样的输入", bool(bad) and isinstance(bad, str) and bad in msg, False)
    check("完全没有 action 字段也拒绝",
          commands.apply_command({"confirmed": True})[0], False)
    # Trimmed, not rejected: a name with stray whitespace is still that action.
    check("前后空格会被去掉，不当成陌生动作",
          "不在允许的清单里" in commands.apply_command({"action": " set_stage "})[1], False)

    check("ALLOWED 就是两张表的并集",
          commands.ALLOWED, commands.REVERSIBLE | commands.MUTATING)
    # An action in both tables would take the reversible path and skip gate ②.
    check("两张表不许有交集（同名会绕过人工确认）",
          commands.REVERSIBLE & commands.MUTATING, set())

    print("\n[白名单里有名字，apply_command 里就必须有分支]")
    # Otherwise the button exists on the phone, does nothing, and reports nothing.


    def offline_mas(path, body=None, timeout=20):
        # What urlopen raises when nothing listens: the one shape that means "AUTO-MAS
        # is down" (annihilation._backend_unreachable); any other error means it is up.
        raise __import__("urllib.error").error.URLError(ConnectionRefusedError(61, "Connection refused"))


    commands._mas = offline_mas
    minimal = {
        "set_stage": {"value": ""}, "set_medicine": {"value": None},
        "set_wait_time": {"value": None}, "toggle_task": {"name": "x"},
        "set_config": {}, "set_master": {}, "run_now": {},
        "skip_today": {}, "unskip_today": {}, "debug_mode": {"off": True}, "weekly_boss": {},
        "echo_farm": {"boss": 1, "until": "08:30"}, "echo_farm_stop": {},
        "echo_farm_until": {"until": "21:00"},
        "skip_shutdown": {"off": True},
        "tacet_shots": {"on": False},
        "monthcard": {"game": "明日方舟", "left": 3},
    }
    check("每个白名单动作都准备了样例指令",
          sorted(minimal), sorted(commands.ALLOWED))
    for action in sorted(commands.ALLOWED):
        reset_cfg()
        _, msg = commands.apply_command({"action": action, "confirmed": True,
                                         **minimal[action]})
        check(f"{action} 有人接手（不是「未处理的动作」）",
              msg.startswith("未处理的动作"), False)
    # Left installed on purpose: set_stage / set_medicine / set_wait_time now ask the
    # backend first and edit the file only when it does not answer. The file-path
    # checks below must test that branch deliberately, not because nothing happens
    # to listen on 127.0.0.1:36163. Sections that want a backend use with_mas().

    # ---------------------------------------------------------------- 闸门 ②

    print("\n[闸门② 会写盘的动作，没有人工确认就不许动]")
    for action in sorted(commands.MUTATING):
        before = reset_cfg()
        ok, msg = commands.apply_command({"action": action, "value": "1-7",
                                          "queue": "早班", "script": "MAA",
                                          "path": "Info.Stage", "game": "MAA"})
        check(f"{action} 未确认被拒", (ok, "人工确认" in msg), (False, True))
        # alerts 20261010 04:16:13: 「📱 配置没改成」 reached the group as 「动作 set_master 需要人工确认…」.
        check(f"{action} 拒绝的话里不带动作原名", action in msg, False)
        check(f"{action} 未确认时配置文件一个字节没动", cfg_raw(), before)
        check(f"{action} 未确认时不留备份", backups(), [])

    reset_cfg()
    ok, msg = commands.apply_command({"action": "skip_shutdown"})
    check("可逆动作不需要确认，直接放行", ok, True)

    # ---------------------------------------------------------------- _STAGE_RE

    print("\n[关卡号形状：不认识就拒，绝不「猜一个」]")
    for good in ("TO-5", "CE-6", "1-7", "LS-6", "AT-4", "S4-1", "H8-4"):
        check(f"{good} 是合法形状", bool(commands._STAGE_RE.match(good)), True)
    for bad in ("", "TO5", "TO-", "-5", "1-7-3", "TO-5 ", " TO-5",
                "ANNIHILATION-1", "1-7; rm -rf /", "剿灭-1", "TOOOO-5",
                'AT-4","MedicineNumb":99'):
        check(f"{bad!r} 不是合法形状", bool(commands._STAGE_RE.match(bad)), False)

    before = reset_cfg()
    ok, msg = commands._set_stage('AT-4","MedicineNumb":99')
    check("注入形状的关卡号被拒", (ok, "不合法" in msg), (False, True))
    check("被拒时配置没动", cfg_raw(), before)

    ok, msg = commands._set_stage("to-5")
    check("小写自动转大写后写入", ok, True)
    check("写进去的是大写",
          json.loads(cfg_raw())[SID]["SubConfigsInfo"]["UserData"][UID]["Info"]["Stage"],
          "TO-5")
    check("回报是人话，不是路径", msg, "刷取关卡：AT-4 → TO-5")
    check("写之前留了备份", len(backups()), 1)
    check("备份里是原来的内容", backups()[0].read_text(encoding="utf-8"), before)

    reset_cfg()
    ok, msg = commands._set_stage("AT-4")
    check("写成和现在一样的值算成功，不算 diff 报警", (ok, msg),
          (True, "已经是这个状态，无需改动"))
    check("没改动就不留备份", backups(), [])

    # Two users in the file: which one did the operator mean? The regex would hit
    # the first one silently.
    two = sample()
    two[SID]["SubConfigsInfo"]["UserData"]["another-uid"] = {"Info": {"Stage": "1-7"}}
    before = reset_cfg(two)
    ok, msg = commands._set_stage("CE-6")
    check("文件里有两处 Stage 时拒绝改，不挑一个下手",
          (ok, "预期恰好 1 处" in msg), (False, True))
    check("拒绝时文件没动", cfg_raw(), before)

    CFG.unlink()
    check("配置文件不存在时拒绝", commands._set_stage("1-7")[0], False)

    # ---------------------------------------------------------------- 数值范围

    print("\n[理智药和等待秒数的范围：越界必须拒，不许写进去让别人改回来]")
    for bad in (None, "很多", "3.5", [3]):
        check(f"理智药 {bad!r} 不是整数",
              (commands._set_medicine(bad)[0], "不是整数" in commands._set_medicine(bad)[1]),
              (False, True))
    for bad in (-1, 1000, 99999):
        check(f"理智药 {bad} 越界", commands._set_medicine(bad)[0], False)
    reset_cfg()
    check("理智药 0 合法（本来就是 0，报「无需改动」）",
          commands._set_medicine(0), (True, "已经是这个状态，无需改动"))
    reset_cfg()
    ok, msg = commands._set_medicine(3)
    check("理智药 3 写得进去", (ok, msg), (True, "理智药上限：0 个 → 3 个"))

    # AUTO-MAS's own schema declares ge=60 and silently clamps anything smaller.
    for bad in (0, 30, 59, 601, "六十"):
        check(f"等待秒数 {bad!r} 被拒", commands._set_wait_time(bad)[0], False)
    check("拒 59 秒时说清楚是 AUTO-MAS 的下限",
          "60" in commands._set_wait_time(59)[1], True)
    reset_cfg()
    check("等待 60 秒合法", commands._set_wait_time(60)[0], True)
    reset_cfg()
    ok, msg = commands._set_wait_time(600)
    check("等待 600 秒合法且回报是人话", (ok, msg),
          (True, "终末地启动后等待：60 秒 → 600 秒"))

    # docs/SILENT-FAILURES-AUDIT.md commands.py:315 - a backend that times out or errors
    # is up: editing the file then is undone from its memory while the phone hears success.
    print("\n[backend slow or erroring: stage / medicine / wait-time are refused, file untouched]")
    for label, exc in (("timeout", TimeoutError("timed out")),
                       ("HTTP 500", __import__("urllib.error").error.HTTPError("http://x", 500, "err", {}, None))):
        def broken(path, body=None, timeout=20, exc=exc):
            raise exc
        commands._mas = broken
        for what, call in (("stage", lambda: commands._set_stage("CE-6")),
                           ("medicine", lambda: commands._set_medicine(3)),
                           ("wait time", lambda: commands._set_wait_time(120))):
            before = reset_cfg()
            ok, msg = call()
            check(f"{label}: {what} not claimed", ok, False)
            check(f"{label}: {what} says the scheduler did not answer", "调度程序没应答" in msg, True)
            check(f"{label}: {what} file untouched, no backup", (cfg_raw() == before, backups()), (True, []))
    commands._mas = offline_mas

    print("\n[toggle_task 明确拒绝，不猜任务名]")
    ok, msg = commands._toggle_task("自动战斗", True)
    check("toggle_task 一律拒绝", (ok, "set_config" in msg), (False, True))

    # ---------------------------------------------------------------- 闸门 ③

    print("\n[闸门③ 结构化 diff：多改一个字段就整个放弃——826 唯一能被拦住的地方]")
    before = reset_cfg()

    ok, msg = commands._safe_rewrite(CFG, lambda raw: raw.replace('"Fixed"', '"Auto"'),
                                     expect_changed=2)
    check("只改了 1 处但预期 2 处，放弃", (ok, "和预期不符" in msg), (False, True))
    check("放弃时文件没动", cfg_raw(), before)

    ok, msg = commands._safe_rewrite(
        CFG, lambda raw: raw.replace('"AT-4"', '"1-7"').replace('"MedicineNumb": 0',
                                                                '"MedicineNumb": 99'),
        expect_changed=1)
    check("正则误伤了第二个字段，放弃", (ok, "改动 2" in msg), (False, True))
    check("误伤时理智药没被烧", cfg_raw(), before)

    def add_key(raw: str) -> str:
        d = json.loads(raw)
        d[SID]["Info"]["凭空造的"] = 1
        return json.dumps(d, ensure_ascii=False, indent=2)


    ok, msg = commands._safe_rewrite(CFG, add_key, expect_changed=1)
    check("凭空多出一个字段，放弃", (ok, "新增 1" in msg), (False, True))
    check("多字段时文件没动", cfg_raw(), before)


    def drop_key(raw: str) -> str:
        d = json.loads(raw)
        del d[SID]["Game"]["WaitTime"]
        return json.dumps(d, ensure_ascii=False, indent=2)


    ok, msg = commands._safe_rewrite(CFG, drop_key, expect_changed=0)
    check("少了一个字段，放弃", (ok, "删除 1" in msg), (False, True))
    check("少字段时文件没动", cfg_raw(), before)


    def boom(raw: str) -> str:
        raise ValueError("正则没匹配上")


    ok, msg = commands._safe_rewrite(CFG, boom, expect_changed=1)
    check("生成改动时抛异常，不碰盘", (ok, "生成改动失败" in msg), (False, True))
    check("抛异常时文件没动", cfg_raw(), before)

    ok, msg = commands._safe_rewrite(CFG, lambda raw: raw[:-3], expect_changed=1)
    check("改完不是合法 JSON，放弃", (ok, "JSON 非法" in msg), (False, True))
    check("非法 JSON 时文件没动", cfg_raw(), before)

    CFG.write_text("{这不是 JSON", encoding="utf-8")
    ok, msg = commands._safe_rewrite(CFG, lambda raw: raw, expect_changed=1)
    check("原文件就不是 JSON 时拒绝改（不许在坏文件上叠改动）",
          (ok, "不是合法 JSON" in msg), (False, True))

    before = reset_cfg()
    saved_write = commands.atomic_write_text


    def cannot_write(path, text, newline=None):
        raise OSError("磁盘满了")


    commands.atomic_write_text = cannot_write
    ok, msg = commands._safe_rewrite(CFG, lambda raw: raw.replace('"Fixed"', '"Auto"'),
                                     expect_changed=1)
    commands.atomic_write_text = saved_write
    check("写盘失败要回滚并说出来", (ok, "已回滚" in msg), (False, True))
    check("回滚后内容和原来一模一样", cfg_raw(), before)

    # ---------------------------------------------------------------- _flatten

    print("\n[_flatten：diff 的地基，漏掉一层就等于那一层没有闸门]")
    check("嵌套字典摊平成路径",
          commands._flatten({"a": {"b": 1}}), {"/a/b": 1})
    check("列表按下标摊平（两个下标互换必须被看见）",
          commands._flatten({"a": [10, 20]}), {"/a[0]": 10, "/a[1]": 20})
    check("列表里的字典也摊得到底",
          commands._flatten({"a": [{"b": True}]}), {"/a[0]/b": True})
    check("空字典摊出来是空", commands._flatten({}), {})
    check("None 也是一个值，不许被吞", commands._flatten({"a": None}), {"/a": None})
    a = commands._flatten({"x": [1, 2]})
    b = commands._flatten({"x": [2, 1]})
    check("列表顺序变了会被 diff 看见",
          {k for k in a.keys() & b.keys() if a[k] != b[k]}, {"/x[0]", "/x[1]"})

    # ---------------------------------------------------------------- 闸门 ④

    print("\n[闸门④ 回报要说人话：路径里的 uuid 不许出现在推送里]")
    # The operator reads this on a phone; `/59da8762-.../Game/WaitTime` says nothing
    # (operator feedback, 2026-08-20).
    check("等待秒数带单位",
          commands._humanize(f"/{SID}/Game/WaitTime", 60, 120),
          "终末地启动后等待：60 秒 → 120 秒")
    check("理智药带单位",
          commands._humanize(f"/{SID}/Info/MedicineNumb", 0, 3),
          "理智药上限：0 个 → 3 个")
    check("关卡不带单位",
          commands._humanize(f"/{SID}/Info/Stage", "AT-4", "TO-5"),
          "刷取关卡：AT-4 → TO-5")
    check("布尔值说开关，不说 True/False",
          commands._humanize("/x/TimeEnabled", True, False), "队列定时：开 → 关")
    check("没登记的字段退回字段名，不吐整条路径",
          commands._humanize(f"/{SID}/Info/SomethingNew", 1, 2),
          "SomethingNew：1 → 2")
    for field in ("Stage", "MedicineNumb", "WaitTime", "Annihilation",
                  "TimeEnabled", "Enabled", "RunTimesLimit", "StageMode"):
        line = commands._humanize(f"/{SID}/Info/{field}", 1, 2)
        check(f"{field} 的回报里没有 uuid", SID in line, False)

    # ---------------------------------------------------------------- set_config

    print("\n[set_config：读现值、路径必须已存在、写完回读——826 缺的就是这三条]")


    class FakeMas:
        """The AUTO-MAS backend, in memory. Records every call so «没写盘» is provable."""

        def __init__(self, *, honour_writes=True):
            self.calls: list[tuple[str, dict]] = []
            self.honour_writes = honour_writes
            self.scripts = {SID: {"Info": {"Name": "MAA"}}}
            self.users = {SID: {UID: {"Info": {"Stage": "AT-4", "MedicineNumb": 0}}}}

        def __call__(self, path, body=None, timeout=20):
            body = body or {}
            self.calls.append((path, body))
            if path == "/api/scripts/get":
                return {"data": self.scripts}
            if path == "/api/scripts/user/get":
                return {"data": self.users.get(body["scriptId"], {})}
            if path == "/api/scripts/user/update":
                if self.honour_writes:
                    self._merge(self.users[body["scriptId"]][body["userId"]],
                                body["data"])
                return {"status": "success"}
            if path == "/api/dispatch/start":
                return {"status": "success"}
            raise AssertionError(f"测试没准备这个端点: {path}")

        def _merge(self, dst, src):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    self._merge(dst[k], v)
                else:
                    dst[k] = v

        def wrote(self):
            return [c for c in self.calls if c[0] == "/api/scripts/user/update"]


    def with_mas(fake, fn):
        saved, commands._mas = commands._mas, fake
        try:
            return fn()
        finally:
            commands._mas = saved


    check("缺 script/path 就拒",
          with_mas(FakeMas(), lambda: commands._set_config({"script": "MAA"}))[0],
          False)
    check("缺 value 就拒（不许把「没给」当成 None 写进去）",
          with_mas(FakeMas(),
                   lambda: commands._set_config({"script": "MAA", "path": "Info.Stage"}))[1],
          "set_config 需要 value")

    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "MAA", "path": "Info.凭空造的", "value": 1}))
    check("路径不存在就拒（说清中继不会自己新建）", (ok, "已拒绝" in msg and "不会自己新建" in msg), (False, True))
    check("拒绝时一次写请求都没发出去", f.wrote(), [])

    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "没这个脚本", "path": "Info.Stage", "value": "1-7"}))
    check("脚本不存在就拒", (ok, "找不到脚本" in msg), (False, True))
    check("找不到脚本时不写", f.wrote(), [])

    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "MAA", "path": "Info.Stage", "value": "AT-4"}))
    check("值本来就一样：算成功且不写", (ok, f.wrote()), (True, []))

    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "maa", "path": "Info.Stage", "value": "1-7"}))
    check("脚本名大小写不敏感，改得动", ok, True)
    check("回报带上「原值 → 新值」", msg, "maa 的 Info.Stage：'AT-4' → '1-7'")
    check("确实只写了一次", len(f.wrote()), 1)
    check("写的是嵌套结构，不是拍平的键",
          f.wrote()[0][1]["data"], {"Info": {"Stage": "1-7"}})

    f = FakeMas(honour_writes=False)
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "MAA", "path": "Info.Stage", "value": "1-7"}))
    check("写了但回读还是老值：必须报失败，不许报绿",
          (ok, "写了但没生效" in msg), (False, True))

    print("\n[后端在：关卡 / 理智药 / 等待秒数走调度程序，不碰文件（2026-09-30 早班停用被内存写回盖掉的同一个坑）]")
    MAAEND_SID = "3e5d0000-0000-0000-0000-0000000maaend"


    class BackendMas(FakeMas):
        """FakeMas plus the script-level endpoints and AUTO-MAS's failure shape."""

        def __init__(self, *, honour_writes=True, refuse=None):
            super().__init__(honour_writes=honour_writes)
            self.refuse = refuse          # a message: updates answer HTTP 200 + code 500
            self.scripts[MAAEND_SID] = {"Info": {"Name": "MaaEnd"},
                                        "Game": {"WaitTime": 60, "Path": "D:/x"},
                                        "Run": {"RunTimesLimit": 3}}

        def __call__(self, path, body=None, timeout=20):
            if self.refuse and path in ("/api/scripts/update", "/api/scripts/user/update"):
                self.calls.append((path, body or {}))
                return {"code": 500, "status": "error", "message": self.refuse}
            if path == "/api/scripts/get":
                self.calls.append((path, body or {}))
                return {"code": 200, "data": json.loads(json.dumps(self.scripts))}
            if path == "/api/scripts/update":
                self.calls.append((path, body))
                if self.honour_writes:
                    self._merge(self.scripts[body["scriptId"]], body["data"])
                return {"code": 200, "status": "success"}
            return super().__call__(path, body, timeout)

        def script_writes(self):
            return [c for c in self.calls if c[0] == "/api/scripts/update"]


    before = reset_cfg()
    b = BackendMas()
    ok, msg = with_mas(b, lambda: commands._set_stage("to-5"))
    check("关卡：后端在时成功", ok, True)
    check("关卡：写的是 MAA 用户的 Info.Stage",
          [c[1] for c in b.wrote()],
          [{"scriptId": SID, "userId": UID, "data": {"Info": {"Stage": "TO-5"}}}])
    check("关卡：调度程序里现在是 TO-5", b.users[SID][UID]["Info"]["Stage"], "TO-5")
    check("关卡：回报是人话并说调度程序已确认", msg, "刷取关卡：AT-4 → TO-5（调度程序已确认）")
    check("关卡：配置文件一个字节没动", cfg_raw(), before)
    check("关卡：没留 ScriptConfig 备份", backups(), [])

    b = BackendMas()
    ok, msg = with_mas(b, lambda: commands._set_stage("AT-4"))
    check("关卡：和现在一样 → 成功且一次都不写", (ok, msg, b.wrote()),
          (True, "已经是这个状态，无需改动", []))

    before = reset_cfg()
    b = BackendMas()
    ok, msg = with_mas(b, lambda: commands._set_medicine(3))
    check("理智药：后端在时成功", (ok, msg), (True, "理智药上限：0 个 → 3 个（调度程序已确认）"))
    check("理智药：写的是 Info.MedicineNumb",
          [c[1]["data"] for c in b.wrote()], [{"Info": {"MedicineNumb": 3}}])
    check("理智药：配置文件没动、没备份", (cfg_raw(), backups()), (before, []))

    before = reset_cfg()
    b = BackendMas()
    ok, msg = with_mas(b, lambda: commands._set_wait_time(120))
    check("等待秒数：后端在时成功", (ok, msg), (True, "终末地启动后等待：60 秒 → 120 秒（调度程序已确认）"))
    check("等待秒数：只发 MaaEnd 脚本的 Game.WaitTime 这一叶",
          [c[1] for c in b.script_writes()],
          [{"scriptId": MAAEND_SID, "data": {"Game": {"WaitTime": 120}}}])
    check("等待秒数：Game 其余的键还在（合并，不是整组替换）",
          b.scripts[MAAEND_SID]["Game"], {"WaitTime": 120, "Path": "D:/x"})
    check("等待秒数：没碰用户那一层", b.wrote(), [])
    check("等待秒数：配置文件没动、没备份", (cfg_raw(), backups()), (before, []))

    b = BackendMas()
    ok, msg = with_mas(b, lambda: commands._set_wait_time(60))
    check("等待秒数：和现在一样 → 成功且不写", (ok, msg, b.script_writes()),
          (True, "已经是这个状态，无需改动", []))

    b = BackendMas()
    del b.scripts[MAAEND_SID]["Game"]["WaitTime"]
    ok, msg = with_mas(b, lambda: commands._set_wait_time(120))
    check("等待秒数：调度程序里没有这一项 → 拒绝，不新建",
          (ok, "已拒绝" in msg and "不会自己新建" in msg, b.script_writes()), (False, True, []))

    b = BackendMas()
    del b.scripts[MAAEND_SID]
    ok, msg = with_mas(b, lambda: commands._set_wait_time(120))
    check("等待秒数：没有 MaaEnd 脚本 → 失败，不退回写文件",
          (ok, "MaaEnd" in msg, cfg_raw() == before, backups()), (False, True, True, []))

    print("\n[后端在但没生效 / 拒收：报失败，绝不退回去写文件]")
    for label, fn in (("关卡", lambda: commands._set_stage("TO-5")),
                      ("理智药", lambda: commands._set_medicine(5)),
                      ("等待秒数", lambda: commands._set_wait_time(200))):
        before = reset_cfg()
        ok, msg = with_mas(BackendMas(honour_writes=False), fn)
        check(f"{label}：写了读出来还是老值 → 失败", (ok, "写了但没生效" in msg), (False, True))
        check(f"{label}：没生效时配置文件没动、没备份", (cfg_raw(), backups()), (before, []))
        busy = "脚本 MaaEnd 正在运行, 无法更新配置项"
        ok, msg = with_mas(BackendMas(refuse=busy), fn)
        check(f"{label}：回复体 code=500 → 失败且原话带回", (ok, busy in msg), (False, True))
        check(f"{label}：拒收时配置文件没动、没备份", (cfg_raw(), backups()), (before, []))

    before = reset_cfg()
    b = BackendMas()
    b.scripts = {}
    ok, msg = with_mas(b, lambda: commands._set_stage("TO-5"))
    check("关卡：后端在但找不到 MAA → 失败，不退回写文件",
          (ok, "找不到脚本" in msg, cfg_raw(), backups()), (False, True, before, []))

    print("\n[后端不在（连不上）：走原来的文件路]")
    from urllib.error import URLError


    def refused(path, body=None, timeout=20):
        raise URLError(ConnectionRefusedError(61, "Connection refused"))


    reset_cfg()
    ok, msg = with_mas(refused, lambda: commands._set_stage("TO-5"))
    check("关卡：连不上 → 改文件", (ok, msg, len(backups())), (True, "刷取关卡：AT-4 → TO-5", 1))
    reset_cfg()
    ok, msg = with_mas(refused, lambda: commands._set_wait_time(90))
    check("等待秒数：连不上 → 改文件", (ok, msg), (True, "终末地启动后等待：60 秒 → 90 秒"))
    check("等待秒数：文件里真的是 90", json.loads(cfg_raw())[SID]["Game"]["WaitTime"], 90)

    print("\n[set_config 同样认回复体里的 code]")
    f = BackendMas(refuse="配置被锁")
    ok, msg = with_mas(f, lambda: commands._set_config(
        {"script": "MAA", "path": "Info.Stage", "value": "1-7"}))
    check("set_config：code=500 → 失败且带原话", (ok, "配置被锁" in msg), (False, True))

    print("\n[_dig / _nest：路径解析本身]")
    check("_dig 取得到嵌套值",
          commands._dig({"Info": {"Stage": "AT-4"}}, "Info.Stage"), "AT-4")
    for bad in ("Info.Nope", "Nope.Stage", "Info.Stage.More"):
        try:
            commands._dig({"Info": {"Stage": "AT-4"}}, bad)
            check(f"_dig 对 {bad} 应该抛 KeyError", "没抛", "KeyError")
        except KeyError:
            check(f"_dig 对不存在的 {bad} 抛 KeyError", True, True)
    check("_nest 造出嵌套写入体",
          commands._nest("Task.IfFight", True), {"Task": {"IfFight": True}})
    check("_nest 单层也行", commands._nest("Stage", "1-7"), {"Stage": "1-7"})

    # ---------------------------------------------------------------- skip_today

    print("\n[skip_today：过期的指令不许生效，老队列名要认得]")
    today = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    # The dispatch sweep above already ran skip_today once; start from a clean slate.
    StateStore(STATE).pop("queues", f"skip_day:{today}")
    ok, msg = commands._skip_today("早班", "2020-01-01")
    check("指定日期已经过去：拒绝，别跳掉没人要跳的那天",
          (ok, "过期" in msg), (False, True))
    check("过期指令没写进状态",
          StateStore(STATE).get("queues", f"skip_day:{today}"), None)

    ok, msg = commands._skip_today("新队列")
    check("老队列名映射成现名", ok, True)
    check("状态里存的是现名",
          StateStore(STATE).get("queues", f"skip_day:{today}"), "早班")
    ok, msg = commands._skip_today("晚班", today)
    check("今天已跳过别的队列：两个都存下，原来的不许被换掉（2026-09-30）",
          (ok, StateStore(STATE).get("queues", f"skip_day:{today}")),
          (True, ["早班", "晚班"]))
    ok, msg = commands._skip_today("早班", today)
    check("同一个队列再跳一次照样成功，不重复存",
          (ok, "已经" in msg, StateStore(STATE).get("queues", f"skip_day:{today}")),
          (True, True, ["早班", "晚班"]))
    ok, msg = modes.unskip(STATE, None, "早班")
    check("取消其中一个：只删它，另一个还在",
          (ok, StateStore(STATE).get("queues", f"skip_day:{today}")), (True, "晚班"))
    StateStore(STATE).pop("queues", f"skip_day:{today}")
    ok, _ = commands._skip_today("晚班", today)
    check("带上今天的日期照样生效",
          StateStore(STATE).get("queues", f"skip_day:{today}"), "晚班")
    ok, msg = modes.unskip(STATE, None, "早班")
    check("取消没跳过的队列：说出今天跳过的是哪个", (ok, "晚班" in msg), (False, True))
    StateStore(STATE).pop("queues", f"skip_day:{today}")

    # ---------------------------------------------------------------- 队列进出

    print("\n[skip a script in a queue for today: only Schedule.Days changes, and it goes back verbatim]")
    # Since the 2026-10-11 hand-over (item 16) the item stays in the queue; today's
    # weekday leaves its Schedule.Days (AUTO-MAS schema.py QueueItem_Schedule.Days,
    # task_manager.py _is_script_scheduled_today) and the saved list is written back.
    ALL_DAYS = list(commands.WEEKDAYS)
    TODAY = commands.WEEKDAYS[datetime.now(tz=SERVER_TZ).weekday()]


    class FakeQueueMas(FakeMas):
        def __init__(self):
            super().__init__()
            self.qid = "queue-0001"
            # OK-WW exists as a script but is not in this queue - the "nothing to
            # skip" case.
            self.scripts["s-okww"] = {"Info": {"Name": "OK-WW"}}
            self.queues = {self.qid: {"Info": {"Name": "早班"}}}
            self.items = {"u1": {"Info": {"ScriptId": "s-endfield"}, "Schedule": {"Days": list(ALL_DAYS)}},
                          "u2": {"Info": {"ScriptId": SID}, "Schedule": {"Days": list(ALL_DAYS)}},
                          "u3": {"Info": {"ScriptId": "s-wuwa"}}}
            self.order = ["u1", "u2", "u3"]
            self.writes = []

        def __call__(self, path, body=None, timeout=20):
            body = body or {}
            if path == "/api/queue/get":
                self.calls.append((path, body))
                return {"data": self.queues}
            if path == "/api/queue/item/get":
                self.calls.append((path, body))
                return {"index": [{"uid": u} for u in self.order], "data": json.loads(json.dumps(self.items))}
            if path in ("/api/queue/item/delete", "/api/queue/item/add", "/api/queue/item/order"):
                raise AssertionError(f"a today-only skip must not call {path}")
            if path == "/api/queue/item/update":
                self.writes.append(body["data"])
                item = self.items[body["queueItemId"]]
                for sec, val in body["data"].items():
                    item.setdefault(sec, {}).update(val)
                return {"status": "success"}
            return super().__call__(path, body, timeout)


    q = FakeQueueMas()
    rec = with_mas(q, lambda: commands.skip_script_in_queue("早班", "MAA"))
    check("the record keeps the item, its position and its original days",
          rec and (rec["queueItemId"], rec["position"], rec["days"]), ("u2", 1, ALL_DAYS))
    check("the item is still in the queue", q.order, ["u1", "u2", "u3"])
    check("only today left its days", q.items["u2"]["Schedule"]["Days"], [d for d in ALL_DAYS if d != TODAY])
    check("only Schedule was sent (no Info, so AUTO-MAS's running-queue guard does not refuse it)",
          [list(w) for w in q.writes], [["Schedule"]])
    check("the other items are untouched", q.items["u1"]["Schedule"]["Days"], ALL_DAYS)
    check("the record says which server day it was made on",
          rec and rec.get("day"), datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
    check("a second skip the same day: None, so the trimmed list is never saved as the original",
          with_mas(q, lambda: commands.skip_script_in_queue("早班", "MAA")), None)
    ok = with_mas(q, lambda: commands.restore_script_in_queue(rec))
    check("restore succeeds", ok, True)
    check("the original days are back verbatim", q.items["u2"]["Schedule"]["Days"], ALL_DAYS)
    check("restoring again is a no-op success", with_mas(q, lambda: commands.restore_script_in_queue(rec)), True)
    check("…and writes nothing more", len(q.writes), 2)

    q4 = FakeQueueMas()
    q4.items["u3"]["Info"]["ScriptId"] = "s-okww"      # an item that never set Schedule.Days runs every day
    rec4 = with_mas(q4, lambda: commands.skip_script_in_queue("早班", "OK-WW"))
    check("no Schedule.Days means every day; today is dropped from all seven",
          (rec4 and rec4["days"], q4.items["u3"]["Schedule"]["Days"]), (ALL_DAYS, [d for d in ALL_DAYS if d != TODAY]))

    q5 = FakeQueueMas()
    q5.items["u2"]["Schedule"]["Days"] = [d for d in ALL_DAYS if d != TODAY]
    check("the user's own days already leave out today: None, nothing written",
          (with_mas(q5, lambda: commands.skip_script_in_queue("早班", "MAA")), q5.writes), (None, []))


    class StuckQueueMas(FakeQueueMas):
        """AUTO-MAS accepts item/update but the days never change."""

        def __call__(self, path, body=None, timeout=20):
            if path == "/api/queue/item/update":
                self.writes.append(body["data"])
                return {"status": "success"}            # accepted, not applied
            return super().__call__(path, body, timeout)


    import logging
    _warned = []


    class _Grab(logging.Handler):
        def emit(self, record):
            _warned.append((record.levelno, record.getMessage()))


    _h = _Grab()
    commands.log.addHandler(_h)
    q3 = StuckQueueMas()
    try:
        with_mas(q3, lambda: commands.skip_script_in_queue("早班", "MAA"))
        raised = ""
    except RuntimeError as exc:
        raised = str(exc)
    check("skip not applied on read-back: raises, so the caller reports it", TODAY in raised, True)
    q3.items["u2"]["Schedule"]["Days"] = [d for d in ALL_DAYS if d != TODAY]
    ok3 = with_mas(q3, lambda: commands.restore_script_in_queue(rec))
    check("restore not applied on read-back: False (record kept, retried)", ok3, False)
    check("…and a WARNING (to the group) naming the queue and the script",
          [lv for lv, m in _warned if "没能把 MAA 的运行日改回去" in m and "早班" in m], [logging.WARNING])
    _warned.clear()
    legacy = {"queue": "早班", "queueId": "queue-0001", "script": "MAA", "scriptId": SID, "position": 1, "day": "2026-10-10"}
    check("a record from the item/delete days: dropped (True) ...",
          with_mas(FakeQueueMas(), lambda: commands.restore_script_in_queue(legacy)), True)
    check("... with a WARNING saying our side adds the item back",
          [lv for lv, m in _warned if "把它加回" in m and "整项删掉" in m], [logging.WARNING])
    _warned.clear()
    q6 = FakeQueueMas()
    q6.order.remove("u2")
    check("the item is gone from the queue: False, with a WARNING",
          (with_mas(q6, lambda: commands.restore_script_in_queue(rec)),
           [lv for lv, m in _warned if "找不到 MAA" in m]), (False, [logging.WARNING]))
    commands.log.removeHandler(_h)

    q2 = FakeQueueMas()
    check("the script is not in the queue at all: None, no raise",
          with_mas(q2, lambda: commands.skip_script_in_queue("早班", "OK-WW")), None)
    check("None leaves the queue untouched", q2.writes, [])

    print("\n[单跑一个脚本：不许因为找不到就去派发整条队列]")
    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands.run_script("MAA"))
    check("找得到就单独派发", (ok, "单独开跑" in msg), (True, True))
    check("派发的是脚本 id、模式 AutoProxy",
          [c[1] for c in f.calls if c[0] == "/api/dispatch/start"],
          [{"taskId": SID, "mode": "AutoProxy"}])
    f = FakeMas()
    ok, msg = with_mas(f, lambda: commands.run_script("终末地"))
    check("找不到脚本就明说，且什么也不派发",
          (ok, [c for c in f.calls if c[0] == "/api/dispatch/start"]), (False, []))

    print("\n[run_now：接口挂了要说人话，不许静默]")
    ok, msg = with_mas(offline_mas, lambda: commands._run_now("早班"))
    check("拿不到队列列表时明确失败", (ok, "取不到队列列表" in msg), (False, True))


    class NoSuchQueueMas(FakeMas):
        def __call__(self, path, body=None, timeout=20):
            if path == "/api/queue/get":
                return {"data": {"q1": {"Info": {"Name": "早班"}}}}
            return super().__call__(path, body, timeout)


    ok, msg = with_mas(NoSuchQueueMas(), lambda: commands._run_now("不存在的班"))
    check("队列名不存在时把现有的列出来（人才知道该按哪个）",
          (ok, "早班" in msg), (False, True))

    print("\n[apply_command 永远不抛：抛出去就没人回报了]")


    def explode(*a, **k):
        raise RuntimeError("底下炸了")


    saved, commands._set_stage = commands._set_stage, explode
    ok, msg = commands.apply_command({"action": "set_stage", "value": "1-7",
                                      "confirmed": True})
    commands._set_stage = saved
    check("底层抛异常也被兜住并回报", (ok, "执行出错" in msg), (False, True))

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_mailbox_close_windows():
    """Mailbox.close() cuts the held stream at once, on macOS and on Windows.

The service stop (SvcStop) calls Mailbox.close() while the listener thread is
blocked reading the ntfy stream. Until 2026-10-07 close() returned only with
the next line the server sent - a keepalive, 45 s apart on ntfy.sh - because
r.close() waits for the read the listener holds; the fix shuts the socket down
first (see Mailbox.close). test_phone_mailbox_e2e.py checks this against a
real ntfy; this file checks the same thing with nothing but the standard
library, so it runs wherever Python runs (the Windows CI job included, the
machine the relay really lives on being Windows).

The server below holds a GET open and writes one ntfy-shaped keepalive line
every KEEPALIVE seconds. KEEPALIVE is well over the 1 s limit, so a close()
that waits for the next line cannot pass by luck.

Basis: "If you want to close the connection in a timely fashion, call
shutdown() before close()." (https://docs.python.org/3/library/socket.html#socket.socket.close)

    Formerly test_mailbox_close_windows.py.
    """
    import json
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import phone
    from ark_relay.features import phone as phone_mailbox

    KEEPALIVE = 5.0          # seconds between keepalive lines (ntfy.sh: 45 s)
    LIMIT = 1.0              # close() and the listener's exit must each take less


    stopping = threading.Event()
    held = threading.Event()           # the server has sent the headers and the open line


    class Stream(BaseHTTPRequestHandler):
        """GET /<topic>/json?...: what ntfy sends a subscriber - an open line, then a
    keepalive every KEEPALIVE seconds - until the client goes away."""

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.end_headers()
            try:
                self._line("open")
                held.set()
                while not stopping.wait(KEEPALIVE):
                    self._line("keepalive")
            except OSError:          # the client shut the socket down: done
                return

        def _line(self, event):
            body = {"id": f"k{time.time_ns()}", "time": int(time.time()), "event": event,
                    "topic": self.path.split("/")[1]}
            self.wfile.write((json.dumps(body) + "\n").encode("utf-8"))
            self.wfile.flush()

        def log_message(self, *a):   # no per-request lines on stderr
            pass


    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stream)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # Mailbox reads NTFY from mailbox.py; phone keeps the re-exported name in step.
    phone.NTFY = phone_mailbox.NTFY = f"http://127.0.0.1:{srv.server_address[1]}"

    t0 = time.time()
    try:
        print(f"[a local stream server on {phone.NTFY}, keepalive every {KEEPALIVE:.0f} s]")
        box = phone.Mailbox("close-test", "8964", tmpdir())
        stop = threading.Event()
        listener = threading.Thread(target=box.listen, args=(lambda body: None, stop.is_set),
                                    daemon=True)
        listener.start()
        check("the server holds the stream", held.wait(5), True)
        until = time.time() + 5
        while not box.connected and time.time() < until:
            time.sleep(0.01)
        check("the mailbox says it is connected", box.connected, True)
        time.sleep(0.3)              # the listener is now blocked reading the next line

        # SvcStop: the stop flag first, then close().
        stop.set()
        t = time.time()
        box.close()
        took = time.time() - t
        check(f"Mailbox.close() returned in under {LIMIT:.0f} s (keepalive every {KEEPALIVE:.0f} s)",
              took < LIMIT or round(took, 2), True)
        listener.join(LIMIT)
        check(f"the listener thread ended within {LIMIT:.0f} s after it", listener.is_alive(), False)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        fails.append(type(exc).__name__)
    finally:
        stopping.set()
        srv.shutdown()
        srv.server_close()
        print(f"  ({time.time() - t0:.1f} s)")

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_payload_roundtrip():
    """A held failure survives a relay restart through pending.json. Everything the
alert wording depends on has to survive with it - the relay now restarts itself
for every selfupdate, so this path runs far more often than it used to.

    Formerly test_payload_roundtrip.py.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import RunRecord, SERVER_TZ
    from ark_relay.core.collector import record_to_payload, payload_to_record


    T0 = datetime(2026, 8, 21, 21, 30, tzinfo=SERVER_TZ)
    T1 = datetime(2026, 8, 21, 22, 15, tzinfo=SERVER_TZ)

    def rec(**kw):
        base = dict(run_id="2026-08-21/arknights/21-30-00", script="MAA",
                    user="arknights", started=T0, finished=T1, ok=False,
                    failed_tasks=["协议空间"], raw={"sanity": 6})
        base.update(kw)
        return RunRecord(**base)

    print("[an untrustworthy duration must stay untrustworthy]")
    # The filename is on a UTC+4 clock, so a run with no timestamped log has times
    # that are hours off. duration_known=False is what stops the alert presenting
    # that as fact - and it used to be dropped on the way to disk.
    back = payload_to_record(record_to_payload(rec(duration_known=False)))
    check("duration_known", back.duration_known, False)

    print("\n[a trustworthy one stays trustworthy]")
    check("duration_known", payload_to_record(record_to_payload(rec())).duration_known, True)

    print("\n[payloads written before this field existed]")
    check("defaults to True", payload_to_record({
        "run_id": "z", "script": "MAA", "started": T0.isoformat(),
        "finished": T1.isoformat(), "ok": False}).duration_known, True)

    print("\n[everything else the alert needs]")
    back = payload_to_record(record_to_payload(rec()))
    for field in ("run_id", "script", "user", "started", "finished", "ok",
                  "failed_tasks", "raw"):
        check(field, getattr(back, field), getattr(rec(), field))
    check("duration_min", back.duration_min, 45)
    check("sanity", back.sanity, 6)


def _part_test_windows():
    """Records inside a marked test window stay out of the daily report's rows.

Fixture: the real ledger of 2026-09-14 - the 09:00 queue (rows 0-9, retries
included, running until 11:49) and then my test dispatches from 12:57 (two
killed runs, one gathering-only run with two retries).

    Formerly test_test_windows.py.
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger as core


    FIX = fx_dir(Path(__file__), "fixtures") / "ledger-2026-09-14" / "ledger.jsonl"
    entries = [json.loads(x) for x in FIX.read_text(encoding="utf-8").splitlines() if x.strip()]
    check("样本 16 条", len(entries), 16)

    print("[真实账本 + 标记的测试窗口：窗口里的六条收起，其余全是正常行]")
    windows = [{"since": "2026-09-14T12:50:00+08:00", "until": "2026-09-14T13:50:00+08:00", "what": "MaaEnd"}]
    queue, tests = core.split_test(entries, windows)
    check("正常 10 条", len(queue), 10)
    check("测试 6 条", [m["run_id"].rsplit("/", 1)[-1] for m in tests],
          ["MaaEnd-08-57-04", "MaaEnd-09-03-54", "MaaEnd-09-06-20", "MaaEnd-09-08-10", "MaaEnd-09-37-59", "MaaEnd-09-43-32"])
    check("队列里的重试照旧是正常行", any(e["run_id"].endswith("MaaEnd-07-20-27") for e in queue), True)

    print("\n[没有标记窗口：手动跑的也是正常行（版本更新后的手动重跑必须进日报）]")
    q2, t2 = core.split_test(entries, [])
    check("全部是正常行", (len(q2), t2), (16, []))
    q3, t3 = core.split_test(entries, [{"since": "bad"}])
    check("坏窗口当没有", (len(q3), t3), (16, []))

    print("\n[窗口没关（until 为空）：从 since 起全算测试——所以测完必须 test-off]")
    q4, t4 = core.split_test(entries, [{"since": "2026-09-14T12:50:00+08:00", "until": None}])
    check("12:50 以后的全收起", len(t4), 6)

    print("\n[日报只列正常的，测试那几趟不成行]")
    title, body = core.format_daily("2026-09-14", queue)
    check("没有 12:57 那趟", "12:58→13:03" in body, False)
    check("早班的终末地还在", "终末地" in body, True)
    t_all, b_all = core.format_daily("2026-09-14", entries)
    check("不标记的话它们本来会出现", "12:58→13:03" in b_all, True)

    print("\n[AUTO-MAS 自己没拉起模拟器的那一秒不成行（10:51 那条）]")
    check("旧记录里 transitional 还是 False", next(e for e in entries if e["run_id"].endswith("06-51-56"))["transitional"], False)
    check("日报里没有「模拟器启动失败」", "模拟器启动失败" in body, False)
    check("也没有那条 10:51 时长未知", "10:51　时长未知" in body, False)
    check("标题不因它算失败", "失败" in title, False)


def _part_heartbeat_main():
    """心跳：有人看才跳、看了立刻跳（刚跳过就不重跳）、停服务发 bye、今天发得多了就放慢。不碰网络。

    Formerly test_heartbeat.py.
    """
    import threading
    import time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import phone


    def wait_for(pred, limit=10.0):
        """Poll until pred() holds or `limit` seconds pass. A fixed 0.2 s sleep went red on a
    loaded Windows runner (relay-windows runs 38391031443 and 38409766185, 2026-10-13: the
    beat thread had not woken yet); a beat that is due still lands at once here."""
        end = time.monotonic() + limit
        while not pred() and time.monotonic() < end:
            time.sleep(0.01)


    sent = []
    STATE = tmpdir()
    hb = phone.Heartbeat("t", STATE, post=lambda payload, title: sent.append(title))
    # 把等待切片缩到 20 毫秒：这个测试验的是「有人看才跳」的逻辑，不是真的计时。
    # 2026-09-08 之前它真等 4 秒，而部署每次都跑整套测试。
    hb._slice_s = 0.02
    stop = {"v": False}
    th = threading.Thread(target=hb.loop, args=(lambda: stop["v"],), daemon=True)
    th.start()

    wait_for(lambda: sent)
    check("刚起来先报一次在线", sent, ["hb"])
    sent.clear()
    check("之后没人看就不跳了", sent, [])
    hb.watch()
    time.sleep(0.2)
    # On open the page reads the last 90 s of beats itself (probeHb since=90s), so a
    # beat that just went out already answers a watch; no extra message for it
    # (10-02 the quota ran out and 196 of the messages were beats).
    check("刚跳过（不到 HB_KICK_GAP）：说「我在看」不再多跳", sent, [])
    hb._last = time.time() - phone.HB_KICK_GAP - 1
    hb.watch()
    wait_for(lambda: sent)
    check("上一跳已经旧了：说「我在看」立刻跳", sent, ["hb"])
    check("计数落盘", hb.sent_today(), 2)
    check("有人看时的间隔", hb.interval(), phone.HEARTBEAT_SEC)

    hb.quota.add("state", phone.HB_FAST_UNTIL)
    check("今天发的总数过了快档线就放慢", hb.interval(), phone.HB_SLOW_SEC)

    stop["v"] = True
    th.join(5)
    check("线程 5 秒内退出", th.is_alive(), False)
    check("退出发 bye", sent[-1], "bye")

    # 发不出去不炸
    bad = phone.Heartbeat("t", STATE, post=lambda *_: (_ for _ in ()).throw(OSError("net")))
    check("post 失败返回 False 不抛", bad.beat(), False)

    # loop() run on this thread as well: the coverage gate (changed_covered.py) does
    # not trace the thread above, so without this it counts loop() as never run.
    direct_sent = []
    direct = phone.Heartbeat("t", tmpdir(), post=lambda payload, title: direct_sent.append(title))
    direct.loop(lambda: True)
    check("loop() on the caller's thread: one beat in, bye out", direct_sent, ["hb", "bye"])


def _part_heartbeat_cos():
    """The heartbeat on COS too (the user, 10-03 00:12: the online verdict must not
rest on the mailbox's heartbeat alone).

The loss this guards against: 2026-10-02 19:19 ntfy's 250 a day ran out, every
beat after that was refused, and at 23:58 the App showed
「关机 · 最后心跳 22:34」 while the machine was running and writing its state to
COS. Now every beat also PUTs `state/<hash>.hb.json`.

Pinned here:
* the object sits next to the state (same hash, `.hb.json`), public-read,
  never cached, {"at", "every", "cos_every"};
* written whether or not the ntfy beat went out, and while the quota has
  stopped the ntfy beats (then `every` is at least HB_SLOW_SEC);
* a COS failure is one log line and the ntfy beat still goes out;
* a service stop writes it once more with "bye": true, after the ntfy bye;
* while watched, the loop rewrites it every HB_COS_SEC and at once on a watch,
  even when the ntfy beat is not due or the quota stopped it;
* no COS -> exactly the old ntfy beat, no request.
Fake network throughout.

    Formerly test_heartbeat_cos.py.
    """
    import json
    import logging
    import threading
    import time
    import types
    import urllib.error

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import phone
    from ark_relay.features import phone as phone_cos_store, phone as phone_heartbeat, phone as phone_mailbox, phone as phone_quota
    from ark_relay.features.evidence import Cos

    TOPIC = "topic-abc"
    COS = Cos("AKIDtest", "secret", "ark-evidence-1", "ap-shanghai")


    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""


    class FakeNet:
        """Records every COS request (url, method, body, headers); `fail` makes them raise."""

        def __init__(self):
            self.sent: list[tuple[str, str, bytes, dict]] = []
            self.fail: "Exception | None" = None

        def urlopen(self, req, timeout=None):
            self.sent.append((req.full_url, req.get_method(), req.data or b"",
                              {k.lower(): v for k, v in req.header_items()}))
            if self.fail is not None:
                raise self.fail
            return FakeResp()

        def bodies(self):
            return [json.loads(b) for _, _, b, _ in self.sent]


    net = FakeNet()
    fake_urllib = types.SimpleNamespace(
        request=types.SimpleNamespace(Request=urllib.request.Request, urlopen=net.urlopen),
        error=urllib.error)
    # phone.py's network code lives in these sibling modules; each reads its own urllib.
    for _m in (phone_quota, phone_cos_store, phone_mailbox, phone_heartbeat):
        _m.urllib = fake_urllib


    class Logs(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines: list[str] = []
            self.recovered: list[bool] = []

        def emit(self, record):
            if record.levelno >= logging.INFO:
                self.lines.append(record.getMessage())
            if record.levelno >= logging.WARNING:
                self.recovered.append(bool(getattr(record, "ark_recovered", False)))


    logs = Logs()
    phone.log.addHandler(logs)
    phone.log.setLevel(logging.DEBUG)

    print("[对象名：和状态对象同一个哈希，后缀 .hb.json]")
    key = phone.hb_key(TOPIC)
    check("state_key 去掉 .json 换成 .hb.json", key, phone.state_key(TOPIC)[:-5] + ".hb.json")
    check("大小写、首尾空格不影响（和 state_key 一样）", phone.hb_key("  TOPIC-ABC \n"), key)

    print("\n[一跳：COS 和 ntfy 各一次]")
    posted: list[str] = []
    hb = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: posted.append(title), cos=COS)
    t0 = int(time.time())
    check("ntfy 心跳照旧发出", hb.beat(), True)
    check("ntfy 收到一条 hb", posted, ["hb"])
    check("COS 一次 PUT", [m for _, m, _, _ in net.sent], ["PUT"])
    url, _, body, h = net.sent[0]
    check("PUT 到 hb_key", url, f"https://{COS.host}/{key}")
    check("公开读（App 没有 COS 密钥）", h.get("x-cos-acl"), "public-read")
    check("不许缓存（不然 App 读到旧心跳）", h.get("cache-control"), "no-store")
    check("带签名", h.get("authorization", "").startswith("q-sign-algorithm=sha1&q-ak=AKIDtest"), True)
    b = json.loads(body)
    check("at 是现在（秒）", t0 <= b["at"] <= int(time.time()), True)
    check("every = 当前 ntfy 心跳间隔", b["every"], phone.HEARTBEAT_SEC)
    check("cos_every = COS 心跳间隔 30 秒", b["cos_every"], phone.HB_COS_SEC)
    check("平时不带 bye", "bye" in b, False)

    print("\n[ntfy 发不出去：COS 照写]")
    net.sent.clear()
    bad = phone.Heartbeat(TOPIC, tmpdir(), post=lambda *_: (_ for _ in ()).throw(OSError("net")), cos=COS)
    check("ntfy 失败返回 False 不抛", bad.beat(), False)
    check("COS 还是写了一次", len(net.sent), 1)

    print("\n[ntfy 额度用完（42908）：ntfy 不再发，COS 照写，every 至少 5 分钟]")
    net.sent.clear()
    posted.clear()
    full = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: posted.append(title), cos=COS)
    full.quota.mark_full()
    check("ntfy 不发（发了也是 429）", full.beat(), False)
    check("ntfy 一条没发", posted, [])
    check("COS 写了", len(net.sent), 1)
    check("every 至少 HB_SLOW_SEC（App 下次读在 8 分钟的续看）", net.bodies()[0]["every"], phone.HB_SLOW_SEC)
    full.quota.add("hb", phone.HB_SLOW_UNTIL)
    net.sent.clear()
    full.beat()
    check("额度用完且总数过了慢档线：every = HB_CRAWL_SEC", net.bodies()[0]["every"], phone.HB_CRAWL_SEC)

    print("\n[COS 失败：一行日志，ntfy 照发，不抛]")
    net.sent.clear()
    posted.clear()
    logs.lines.clear()
    net.fail = urllib.error.URLError("网断了")
    flaky = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: posted.append(title), cos=COS)
    check("ntfy 心跳照旧发出", flaky.beat(), True)
    check("ntfy 收到 hb", posted, ["hb"])
    flaky.beat()
    flaky.beat()
    cos_lines = [l for l in logs.lines if "腾讯云 COS" in l]
    check("连失败三次只记一行", len(cos_lines), 1)
    check("那一行说了原因", "网断了" in (cos_lines or [""])[0], True)
    net.fail = urllib.error.HTTPError(f"https://{COS.host}/{key}", 403, "Forbidden", None, None)
    check("COS 回 403 也不抛", flaky.cos_beat(), False)
    net.fail = None
    logs.lines.clear()
    logs.recovered.clear()
    check("恢复后写得进", flaky.cos_beat(), True)
    # Since 2026-10-06 the recovery is one WARNING marked errwatch.recovered()
    # (daily report only), saying how long it was down and the first reason.
    check("恢复记一行", [l.splitlines()[0].split("（")[0] for l in logs.lines if "腾讯云" in l],
          ["心跳又写得进腾讯云了"])
    check("……marked recovered (not pushed)", logs.recovered, [True])
    check("……the first reason on its second line", "网断了" in (logs.lines or [""])[-1], True)

    print("\n[停服务：ntfy 发 bye 之后，COS 写一次带 bye 的]")
    order: list[str] = []
    net.sent.clear()
    stopper = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: order.append("ntfy:" + title), cos=COS)
    orig = net.urlopen
    net.urlopen = lambda req, timeout=None: (order.append("cos"), orig(req, timeout))[1]
    fake_urllib.request.urlopen = net.urlopen
    stopper.bye()
    check("先 ntfy bye，再 COS", order, ["ntfy:bye", "cos"])
    check("COS 的心跳带 bye", net.bodies()[-1].get("bye"), True)
    net.urlopen = orig
    fake_urllib.request.urlopen = orig
    net.sent.clear()
    broke = phone.Heartbeat(TOPIC, tmpdir(), post=lambda *_: (_ for _ in ()).throw(OSError("net")), cos=COS)
    broke.bye()
    check("ntfy bye 失败也照写 COS bye", net.bodies()[-1].get("bye"), True)

    print("\n[循环：有人看时每 30 秒写一次 COS；说「我在看」立刻写，哪怕 ntfy 不到点或额度停了]")
    net.sent.clear()
    posted.clear()
    lp = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: posted.append(title), cos=COS)
    lp._slice_s = 0.01
    stop = {"v": False}
    th = threading.Thread(target=lp.loop, args=(lambda: stop["v"],), daemon=True)
    th.start()
    time.sleep(0.15)
    check("起来先跳一次：ntfy 一条、COS 一次", (posted, len(net.sent)), (["hb"], 1))
    lp.watch()
    time.sleep(0.15)
    check("刚跳过：ntfy 不重跳", posted, ["hb"])
    check("但 COS 立刻再写一次（App 几秒后来读）", len(net.sent), 2)
    # The loop sleeps up to HB_COS_SEC slices (0.3 s here) before it looks again.
    lp._cos_last = time.time() - phone.HB_COS_SEC - 1
    # Wait for the write rather than a fixed 0.5 s: 30 slices of time.sleep(0.01) ran
    # past 0.5 s on a loaded Mac (load 10-29, 2026-10-10 00:45) and the check failed.
    _until = time.time() + 5
    while len(net.sent) < 3 and time.time() < _until:
        time.sleep(0.05)
    check("COS 到 30 秒就再写，ntfy 不到点不发", (posted, len(net.sent) >= 3), (["hb"], True))
    lp.quota.mark_full()
    n = len(net.sent)
    lp.watch()
    time.sleep(0.15)
    check("额度停了：说「我在看」COS 照写，ntfy 不发", (posted, len(net.sent) > n), (["hb"], True))
    stop["v"] = True
    th.join(5)
    check("线程 5 秒内退出", th.is_alive(), False)
    check("退出时 COS 写 bye", net.bodies()[-1].get("bye"), True)

    print("\n[没配 COS：老样子，一个 COS 请求都没有]")
    net.sent.clear()
    posted.clear()
    plain = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: posted.append(title))
    plain.beat()
    plain.bye()
    check("ntfy 照旧 hb、bye", posted, ["hb", "bye"])
    check("不碰 COS", net.sent, [])
    check("cos_beat 直接 False", plain.cos_beat(), False)


def _part_resources():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ark_relay.features import resources

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
        if not ok:
            fails.append(label)


    print("[森空岛会话：没配 token 就是一句说明]")


    class NoTok:
        skland_token = ""


    check("没配", resources.skland_session(NoTok), {"错误": "没配森空岛 token"})

    print("\n[有 token：登录一次、找出两个游戏的账号，第二次直接复用]")
    from ark_relay.core import skland

    calls = {"login": 0}


    class Cred:
        cred, token = "c1", "t1"


    def fake_login(token, did=""):
        calls["login"] += 1
        return Cred()


    # Put the real functions back at the end: the coverage pass runs many test files in one
    # process, and a later file (test_skland, its part skland_api) must reach the real skland functions.
    _REAL = (skland.get_did, skland.login, skland.refresh, skland.bindings)
    skland.get_did, skland.login, skland.refresh = (lambda: "Bdev"), fake_login, (lambda c: c)
    skland.bindings = lambda c: [
        {"appCode": "endfield", "bindingList": [{"uid": "247481631", "channelMasterId": "1",
                                                  "roles": [{"roleId": "1234567890", "serverId": "1"}]}]},
        {"appCode": "arknights", "bindingList": [{"uid": "19237299", "channelMasterId": "1"}]},
    ]


    class Tok:
        skland_token = "sk-token"


    resources._session["sk"] = None
    got = resources.skland_session(Tok)
    check("会话齐全（终末地用 roles[] 的 roleId，不是 uid）", got, {"cred": "c1", "token": "t1", "dId": "Bdev", "uid": "19237299", "efRole": "1234567890", "efServer": "1"})
    resources.skland_session(Tok)
    check("只登录一次", calls["login"], 1)


    def boom(c):
        raise RuntimeError("HTTP Error 401")


    resources._session["sk"] = None
    skland.bindings = boom
    check("失败给原因", resources.skland_session(Tok)["错误"].startswith("RuntimeError: HTTP Error 401"), True)
    check("失败后不留半个会话", resources._session["sk"], None)


    print("\n[终末地角色这次没读到：过一阵重做会话，不一直缺（11-08 [D-04]）]")
    _saved_role, _saved_bind = skland.endfield_role, skland.bindings
    skland.bindings = lambda c: []
    def _ef_timeout(c):
        raise TimeoutError("timed out")
    skland.endfield_role = _ef_timeout
    resources._session["sk"] = None; resources._session.pop("ef_retry_at", None)
    got = resources.skland_session(Tok)
    check("先给缺角色的会话", "efRole" in got, False)
    skland.endfield_role = lambda c: ("999", "1")
    check("没到重试时间：还用旧的", "efRole" in resources.skland_session(Tok), False)
    resources._session["ef_retry_at"] = 0
    check("到点了重做：角色补上", resources.skland_session(Tok).get("efRole"), "999")
    skland.endfield_role, skland.bindings = _saved_role, _saved_bind
    resources._session["sk"] = None

    print("\n[森空岛给了不止一个终末地角色：不读，报群]")
    # The account has exactly one Endfield role (checked 2026-10-06); more than one
    # in an answer is a refusal (skland.endfield_role) the group has to hear of.
    import inspect
    import logging
    import time
    from _tmp import fx_dir, tmpdir
    from ark_relay.features import errwatch
    from ark_relay.core import texts


    class Group:
        def __init__(self):
            self.sent = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body, alert))
            return []


    grp = Group()
    takes = inspect.signature(errwatch.ErrorKindAlert.__init__).parameters
    hw = errwatch.ErrorKindAlert(grp, lambda: False, tmpdir(),
                                 **{k: v for k, v in {"known": {}, "pace": 0}.items() if k in takes})
    logging.getLogger(errwatch.ARK).addHandler(hw)
    skland.bindings = lambda c: [
        {"appCode": "endfield", "bindingList": [{"uid": "1", "roles": [{"roleId": "1001", "serverId": "1"},
                                                                        {"roleId": "2002", "serverId": "2"}]}]},
        {"appCode": "arknights", "bindingList": [{"uid": "19237299"}]},
    ]
    resources._session["sk"] = None
    got = resources.skland_session(Tok)
    t0 = time.monotonic()
    while not grp.sent and time.monotonic() - t0 < 3:
        time.sleep(0.02)
    time.sleep(0.1)
    logging.getLogger(errwatch.ARK).removeHandler(hw)
    hw.close()
    check("没猜：会话里没有终末地角色", ("efRole" in got, got.get("uid")), (False, "19237299"))
    MULTI = getattr(texts, "SKLAND_MULTI_ROLE", "⚠️ 森空岛给了不止一个终末地角色，没有读")
    check("报群一条，标题是它自己的", [(t, a) for t, _, a in grp.sent], [(MULTI, True)])
    check("正文说几个、编号，没读", bool(grp.sent) and "森空岛这次给了 2 个终末地角色（角色编号 1001、2002）" in grp.sent[0][1], True)
    check("正文不说「服务器」", bool(grp.sent) and "服务器" in grp.sent[0][1], False)
    check("正文是人话", [texts.plain(b) for _, b, _ in grp.sent], [[]])
    check("拒绝是单独的一类（按类型认，不按字）", issubclass(getattr(skland, "SklandMultiRole", RuntimeError),
                                                    skland.SklandError), True)

    print("\n[今天：从账目数]")


    class St:
        def read_ledger(self, day):
            return [{"run_id": "a", "script": "MAA", "ok": True}, {"run_id": "b", "script": "OK-WW", "ok": False},
                    {"run_id": "c", "script": "MaaEnd", "ok": True}]


    check("跑了 3 失败 1 最近 MaaEnd", resources.today(St(), "2026-09-15"), {"跑了": 3, "失败": 1, "最近": "MaaEnd"})


    class StStop:
        """2026-09-30: the 停一切 press stopped MaaEnd (ok=False) - not a failure."""

        def read_ledger(self, day):
            return [{"run_id": "a", "script": "OK-WW", "ok": False, "raw": {"okww_error": "x"}},
                    {"run_id": "b", "script": "OK-WW", "ok": True, "raw": {"manual_stop": "09:46 停一切"}},
                    {"run_id": "c", "script": "MaaEnd", "ok": False, "raw": {"manual_stop": "09:46 停一切"}}]


    check("停一切停掉的不算失败（跑了 3 失败 1）", resources.today(StStop(), "2026-09-30"),
          {"跑了": 3, "失败": 1, "最近": "MaaEnd"})

    print("\n[today: failures by the daily headline's rule, on the machine's ledgers]")
    # Audit 11 (2026-10-13): the App showed 「失败 1 趟」 on 10-06 and 10-07 for a MaaEnd
    # self-update restart (transitional; episode_kinds 「update」) while the daily
    # report said all green. Ledgers copied from the machine's state/ on 10-13.
    import json
    import shutil

    from _tmp import tmpdir
    from ark_relay.core.ledger import State

    LEDGERS = fx_dir(Path(__file__), "fixtures") / "phone-ledgers"
    real_dir = tmpdir()
    for f in LEDGERS.glob("ledger-*.jsonl"):
        shutil.copy(f, real_dir / f.name)
    check("10-06: 5 runs, the update restart is not a failure",
          resources.today(State(real_dir), "2026-10-06"), {"跑了": 5, "失败": 0, "最近": "MAA"})
    check("10-07: 5 runs, the update restart is not a failure",
          resources.today(State(real_dir), "2026-10-07"), {"跑了": 5, "失败": 0, "最近": "MAA"})
    # A real failure on the same day is still counted.
    day06 = [json.loads(x) for x in (LEDGERS / "ledger-2026-10-06.jsonl").read_text(encoding="utf-8").splitlines()]
    bad = dict(day06[1], run_id="2026-10-06/wuwa/OK-WW-12-00-00", started="2026-10-06T12:00:00+08:00",
               ok=False, failed_tasks=["每日任务"])
    (real_dir / "ledger-2026-10-06.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in [*day06, bad]), encoding="utf-8")
    check("a real failure still counts", resources.today(State(real_dir), "2026-10-06")["失败"], 1)
    # The same failure inside a run-one.sh --test window is not the day's failure.
    (real_dir / "test-windows.json").write_text(json.dumps(
        [{"since": "2026-10-06T11:55:00+08:00", "until": "2026-10-06T12:30:00+08:00", "what": "OK-WW"}]),
        encoding="utf-8")
    check("a failure inside a test window does not count",
          resources.today(State(real_dir), "2026-10-06")["失败"], 0)

    print("\n[开机推送和停止前推送同时要会话：#10 不会读到做了一半的体力]")
    # 2026-10-10 16:32:53 the stop notice came 7 s after boot: the boot state and the
    # 停止前 state both asked for the session while none existed yet, both logged in and
    # both ran _probe_stamina; check #10 read probe() between one call's 「at」 and its
    # dungeon and pushed 「终末地体力没读到：没读」 (relay.log 16:32:55-16:32:58).
    import threading

    calls["login"] = 0
    reads = {"n": 0}
    skland.bindings = lambda c: [
        {"appCode": "endfield", "bindingList": [{"uid": "1", "roles": [{"roleId": "1001", "serverId": "1"}]}]},
        {"appCode": "arknights", "bindingList": [{"uid": "19237299"}]},
    ]
    _REAL_CARD = getattr(skland, "endfield_card", None)


    def slow_card(cred, role, server):
        reads["n"] += 1
        time.sleep(0.3)
        return {"detail": {"dungeon": {"curStamina": 1, "maxStamina": 360, "maxTs": 2}}}


    skland.endfield_card = slow_card
    resources._session["sk"] = None
    seen = []


    def watch():
        t_end = time.monotonic() + 1.5
        while time.monotonic() < t_end:
            p = resources.probe()
            if p.get("at") and "dungeon" not in p and "错误" not in p:
                seen.append(p)
            time.sleep(0.005)


    w = threading.Thread(target=watch)
    w.start()
    ts = [threading.Thread(target=resources.skland_session, args=(Tok,)) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    w.join()
    check("没有哪一刻是「有时间、没体力也没原因」", seen[:1], [])
    check("读完 probe 里有体力", "dungeon" in resources.probe(), True)
    if _REAL_CARD is not None:
        skland.endfield_card = _REAL_CARD

    skland.get_did, skland.login, skland.refresh, skland.bindings = _REAL

    print("[today: the ledger cannot be read]")
    import logging


    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.n = 0

        def emit(self, record):
            self.n += 1


    class StBroken:
        def read_ledger(self, day):
            raise OSError("ledger locked")


    _g = _Grab()
    resources.log.addHandler(_g)
    getattr(resources, "_last_error", {}).clear()
    got = resources.today(StBroken(), "2026-10-10")
    check("unreadable -> no counts (no fake 0 failures), an error key", (got.get("失败"), "错误" in got), (None, True))
    check("unreadable -> one WARNING", _g.n, 1)
    resources.today(StBroken(), "2026-10-10")
    check("same condition again -> no second WARNING", _g.n, 1)
    resources.today(St(), "2026-09-15")
    resources.today(StBroken(), "2026-10-10")
    check("broken again after a good read -> WARNING again", _g.n, 2)
    resources.log.removeHandler(_g)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_snapshot():
    import logging
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import errwatch
    from ark_relay.features import snapshot

    fails: list[str] = []


    def check(label, got, want):
        ok = got == want
        print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
        if not ok:
            fails.append(label)


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__()
            self.warned: list[str] = []

        def emit(self, record):
            if record.levelno >= logging.WARNING:
                self.warned.append(record.getMessage())


    grab = Grab()
    snapshot.log.addHandler(grab)
    snapshot.log.propagate = False

    calls: list[str] = []


    def fake(label):
        def f(out):
            calls.append(label)
            out[label] = "ok"
        return f


    saved = (snapshot._mas, snapshot._queues, snapshot._okww, snapshot._runtime,
             errwatch.relay_shutdown_issued, errwatch.os_shutdown)
    errwatch.os_shutdown = lambda: False

    snapshot._mas, snapshot._queues = fake("_mas"), fake("_queues")
    snapshot._okww, snapshot._runtime = fake("_okww"), fake("_runtime")

    errwatch.relay_shutdown_issued = lambda: False
    calls.clear()
    out = snapshot.read()
    check("没关机：四个都读", calls, ["_mas", "_queues", "_okww", "_runtime"])
    check("没关机：无 WARNING", grab.warned, [])

    errwatch.relay_shutdown_issued = lambda: True
    calls.clear()
    grab.warned.clear()
    out = snapshot.read()
    check("关机令已发：只读 _okww/_runtime，不碰 _mas/_queues", calls, ["_okww", "_runtime"])
    check("关机令已发：无 WARNING", grab.warned, [])
    check("_mas/_queues 不再写进结果", all(k not in out for k in ("_mas", "_queues")), True)
    check("_okww/_runtime 还在", ("_okww" in out, "_runtime" in out), (True, True))

    print("[10-10 04:28:47: Windows shutdown by hand, not the relay's own (SvcShutdown ran)]")
    errwatch.relay_shutdown_issued = lambda: False
    errwatch.os_shutdown = lambda: True
    calls.clear()
    grab.warned.clear()
    out = snapshot.read()
    check("手动关机：不碰 _mas/_queues", calls, ["_okww", "_runtime"])
    check("手动关机：无 WARNING", grab.warned, [])

    print("[a plain service stop (sc stop, the self-update restart): the machine stays up, so it is read]")
    errwatch.os_shutdown = lambda: False
    errwatch.mark_stopping()
    try:
        calls.clear()
        grab.warned.clear()
        out = snapshot.read()
        check("service stop only: all four read", calls, ["_mas", "_queues", "_okww", "_runtime"])
        snapshot._mas = lambda out: (_ for _ in ()).throw(ConnectionRefusedError("x"))
        grab.warned.clear()
        snapshot.read()
        check("service stop only: a section that fails still warns (pushed)", len(grab.warned), 1)
        snapshot._mas = fake("_mas")
    finally:
        errwatch.clear_stopping()

    print("[the shutdown begins while a section is being read]")
    state = {"down": False}
    errwatch.os_shutdown = lambda: state["down"]


    def gone(out):
        state["down"] = True
        raise ConnectionRefusedError("AUTO-MAS backend gone")


    snapshot._mas = gone
    grab.warned.clear()
    out = snapshot.read()
    check("读到一半开始关机：无 WARNING", grab.warned, [])
    check("读到一半开始关机：错误仍记进结果", "_MAS错误" in out, True)

    print("[not shutting down: a failing section still warns]")
    state["down"] = False


    def refused(out):
        raise ConnectionRefusedError("x")


    snapshot._mas = refused
    grab.warned.clear()
    out = snapshot.read()
    check("没关机时读不到：照样 WARNING", len(grab.warned), 1)

    print("[a phone publish reads only the runtime section (audit 11 #2)]")
    # relay.log 10-06 / 10-10: every phone publish ran _mas / _queues / _okww, kept only
    # 「ark-relay」 and 「程序」 (from _runtime), and an AUTO-MAS hiccup reached the group.
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir
    from ark_relay.features import phone


    def runtime(out):
        calls.append("_runtime")
        out["ark-relay"], out["程序"] = "RUNNING", {"MAA": True}


    snapshot._runtime = runtime
    calls.clear()
    grab.warned.clear()
    pcfg = types.SimpleNamespace(automas_dir=str(tmpdir()), maaend_dir=str(tmpdir()), okww_dir=str(tmpdir()))
    st = phone.state_payload(pcfg, tmpdir())
    check("the publish calls only _runtime", calls, ["_runtime"])
    check("an AUTO-MAS that does not answer is not a WARNING from the publish", grab.warned, [])
    check("the phone still gets the runtime", st.get("run"), {"服务": "RUNNING", "在跑的": ["MAA"]})
    calls.clear()
    snapshot.read()
    check("config-check's full read still reads every section", calls, ["_queues", "_okww", "_runtime"])

    (snapshot._mas, snapshot._queues, snapshot._okww, snapshot._runtime,
     errwatch.relay_shutdown_issued, errwatch.os_shutdown) = saved
    snapshot.log.removeHandler(grab)

    print("[_queues: one queue's item list unreadable]")
    import urllib.error
    from unittest import mock

    item_err = {"exc": None}
    queue_info = {"q1": {"Info": {"Name": "早班", "TimeEnabled": True, "StartUpEnabled": False}}}


    def fake_post(path, body=None, timeout=15):
        if path == "/api/scripts/get":
            return {"data": {"s1": {"Info": {"Name": "MAA"}}}}
        if path == "/api/queue/get":
            return {"data": queue_info}
        if item_err["exc"] is not None:
            raise item_err["exc"]
        return {"data": {"i1": {"Info": {"ScriptId": "s1"}}}}


    class Grab2(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.warned = []

        def emit(self, record):
            if record.levelno >= logging.WARNING:
                self.warned.append(record)


    g2 = Grab2()
    snapshot.log.addHandler(g2)
    getattr(snapshot, "_last_error", {}).clear()
    with mock.patch.object(snapshot, "_post", fake_post), \
            mock.patch.object(errwatch, "relay_shutdown_issued", lambda: False), \
            mock.patch.object(errwatch, "os_shutdown", lambda: False):
        item_err["exc"] = urllib.error.HTTPError("u", 500, "boom", {}, None)
        out = {}
        snapshot._queues(out)
        q = out["队列"]["早班"]
        check("unreadable -> 脚本 stays [] (shape) and is marked", (q["脚本"], "脚本读不到" in q), ([], True))
        check("unreadable -> one WARNING", len(g2.warned), 1)
        snapshot._queues({})
        check("same condition again -> no second WARNING", len(g2.warned), 1)
        item_err["exc"] = None
        out = {}
        snapshot._queues(out)
        check("readable -> the list, no mark", (out["队列"]["早班"]["脚本"], "脚本读不到" in out["队列"]["早班"]),
              (["MAA"], False))
        item_err["exc"] = urllib.error.HTTPError("u", 500, "boom", {}, None)
        snapshot._queues({})
        check("broken again after a good read -> WARNING again", len(g2.warned), 2)
        item_err["exc"] = urllib.error.URLError(ConnectionRefusedError(61, "refused"))
        raised = False
        try:
            snapshot._queues({})
        except Exception:  # noqa: BLE001
            raised = True
        check("backend gone (connection refused) -> the section fails as before", raised, True)
        # AUTO-MAS v5.7 replaced the bool StartUpEnabled with StartUpMode (Never / Always /
        # DailyFirst; app/models/config.py, tests/fixtures/automas-models/config.py.txt).
        item_err["exc"] = None
        got = {}
        for mode in ("Never", "Always", "DailyFirst"):
            queue_info["q1"]["Info"] = {"Name": "早班", "TimeEnabled": True, "StartUpMode": mode}
            out = {}
            snapshot._queues(out)
            got[mode] = out["队列"]["早班"]["开机跑"]
        check("v5.7 StartUpMode -> 开机跑", got, {"Never": False, "Always": True, "DailyFirst": True})
    snapshot.log.removeHandler(g2)

    print("\n[_mas: one script's user unreadable is marked, not dropped (audit 11 #5)]")


    def users_post(path, body=None, timeout=15):
        if path == "/api/scripts/get":
            return {"data": {"s1": {"Info": {"Name": "MAA"}}, "s2": {"Info": {"Name": "MaaEnd"}},
                             "s3": {"Info": {"Name": "OK-WW"}}}}
        if path == "/api/scripts/user/get" and body["scriptId"] == "s2":
            raise TimeoutError("timed out")
        if path == "/api/scripts/user/get" and body["scriptId"] == "s3":
            raise urllib.error.URLError("refused")
        return {"data": {"u1": {"Info": {"Stage": "1-7"}, "Task": {}}}}


    o = {}
    with mock.patch.object(snapshot, "_post", users_post):
        snapshot._mas(o)
    check("the readable script is there", (o.get("MAA") or {}).get("关卡"), "1-7")
    check("MaaEnd's section says its user could not be read", o.get("MaaEnd"), {"用户读不到": "TimeoutError: timed out"})
    check("OK-WW's too, under its usual key", sorted(o.get("OK-WW(MAS侧)") or {}), ["用户读不到"])

    print("\n[the phone page's relay state looks for the mutex the packaged main program holds]")
    import re
    _relay = Path(__file__).resolve().parents[1]
    _held = re.search(r'^MUTEX = "([^"]+)"', (_relay / "app_main.py").read_text(encoding="utf-8"), re.M)
    _watched = re.search(r'^MUTEX = "([^"]+)"',
                         (_relay.parent / "packaging" / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), re.M)
    check("snapshot, app_main and the watchdog name the same mutex",
          (snapshot._MAIN_LOCK_NAME, _held and _held.group(1).replace("\\\\", "\\"),
           _watched and _watched.group(1).replace("\\\\", "\\")),
          (snapshot._MAIN_LOCK_NAME,) * 3)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_inbox_poll():  # noqa: C901
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ark_relay.features import phone as inbox
    from _tmp import tmpdir

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
        if not ok:
            fails.append(label)


    class FakeInbox(inbox.Inbox):
        """不联网：把「取回来的那份 JSON」直接塞进来。"""

        payload = None

        def _fetch_or_none(self):
            return self.payload


    def box(payload):
        b = FakeInbox(tmpdir())
        b.payload = payload
        return b


    print("[版本号严格变大才执行]")
    b = box({"version": 5, "name": "第一批", "commands": []})
    ver, msgs = b.poll()
    check("第一次收到就执行", ver, 5)
    check("推送里带了名字", "第一批" in msgs[0], True)

    b.payload = {"version": 5, "name": "同一版", "commands": []}
    ver, msgs = b.poll()
    check("同一个版本号不重放", msgs, [])
    check("版本号没退回去", ver, 5)

    b.payload = {"version": 4, "name": "更旧的（CDN 发的旧副本）", "commands": []}
    ver, msgs = b.poll()
    check("更旧的版本不执行", msgs, [])
    check("版本号还是 5", ver, 5)

    b.payload = {"version": 6, "name": "第二批", "commands": []}
    ver, msgs = b.poll()
    check("更新的版本才执行", ver, 6)

    print("\n[取不到 ≠ 没有新东西：调用方要能分辨]")
    b = box({"version": 9, "commands": []})
    b.poll()
    check("取到了", b.last_fetch_ok, True)
    b.payload = None
    ver, msgs = b.poll()
    check("取不到时说取不到", b.last_fetch_ok, False)
    check("取不到时不动版本号", ver, 9)
    check("取不到时不推送", msgs, [])

    print("\n[文件本身不成形要拒绝，而且不能记账]")
    b = box({"version": "不是整数", "commands": []})
    ver, msgs = b.poll()
    check("版本号不是整数 → 忽略", (ver, msgs), (0, []))
    b.payload = {"version": 3, "commands": "不是数组"}
    ver, msgs = b.poll()
    check("commands 不是数组 → 忽略", (ver, msgs), (0, []))
    check("忽略之后版本号仍是 0（没记账）", b.applied_version, 0)

    print("\n[应用中途炸了：要说清楚，而且必须记账，不许下次开机整批重放]")
    b = box({"version": 11, "name": "会炸的一批", "commands": [{"action": "queue"}]})
    b._apply = lambda cmds: (_ for _ in ()).throw(OSError("盘满了"))
    ver, msgs = b.poll()
    check("版本号照样记下", b.applied_version, 11)
    check("说了是中途出错", any("应用中途出错" in m for m in msgs), True)
    check("说了这批指令不会再执行一遍", any("不会再执行一遍" in m for m in msgs), True)

    print("\n[记账落在 state.json 里，换一个实例也读得到]")
    d = tmpdir()
    b1 = FakeInbox(d)
    b1.payload = {"version": 21, "commands": []}
    b1.poll()
    b2 = FakeInbox(d)
    check("另一个实例读到同一个版本号", b2.applied_version, 21)
    saved = json.loads((d / "state.json").read_text(encoding="utf-8"))
    check("存在 queues/inbox_version 里", saved["queues"]["inbox_version"], "21")

    print("\n[用户写的 note 要原样出现在推送正文里]")
    b = box({"version": 31, "name": "改基质地点", "note": "换成清波寨，VFTheHub 刷不出来",
             "commands": []})
    _, msgs = b.poll()
    body = "\n".join(msgs)
    check("note 在正文里", "换成清波寨" in body, True)
    check("名字在标题里", "改基质地点" in msgs[0], True)

    print("\n[没有 automas 路径时，明说跳过而不是假装做了]")
    b = box({"version": 41, "commands": [
        {"action": "queue", "name": "早班", "enabled": True},
        {"action": "sanity_plan", "tab": "x"},
    ]})
    _, msgs = b.poll()
    body = "\n".join(msgs)
    check("队列那条说了跳过", "✗ 队列：找不到 AUTO-MAS 目录" in body, True)
    check("理智方案那条说了跳过", "✗ 理智方案：找不到 AUTO-MAS 目录" in body, True)

    print("\n[maaend_option is gone (audit 11 #8): refused, nothing written]")
    # Nothing sends it since 08-20 (order.sh refuses an action outside commands.ALLOWED,
    # the App never had it); maaend.apply_changes and its inbox branch are deleted.
    d = tmpdir()
    mfile = d / "automas" / "data" / "sid1" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
    mfile.parent.mkdir(parents=True)
    mfile.write_text(json.dumps({"instances": [{"tasks": [{"taskName": "T", "optionValues": {
        "O": {"type": "switch", "value": False}}}]}]}), encoding="utf-8")
    before = mfile.read_text(encoding="utf-8")
    b = FakeInbox(d / "state", automas_dir=d / "automas")
    b.payload = {"version": 43, "commands": [
        {"action": "maaend_option", "task": "T", "option": "O", "value": "false"}]}
    _, msgs = b.poll()
    check("refused by the whitelist", any(m.startswith("✗ maaend_option") for m in msgs), True)
    check("the master copy is untouched", mfile.read_text(encoding="utf-8"), before)
    check("the writer module is gone", (Path(inbox.__file__).parent / "maaend.py").exists(), False)

    # ---- A stale configured address must fall back to the built-in one ----
    # 2026-09-08 I deleted inbox/todo.json while the machine's .env still pointed at
    # it. Every order after that 404-ed on all four doors and only the relay's own
    # log knew. The command channel must not die over one stale line in .env.
    _calls = []
    def _fake_fetch(url, *a, **k):
        _calls.append(url)
        return None if "todo.json" in url else {"version": 5, "commands": [], "name": "x"}
    _real_fetch = inbox._fetch
    inbox._fetch = _fake_fetch
    try:
        _ib = inbox.Inbox(tmpdir(), "https://raw.githubusercontent.com/herclyon1/maa/main/inbox/todo.json")
        _got = _ib._fetch_or_none()
        check("过期地址取不到时退回内置地址", _got is not None and _got.get("version"), 5)
        check("先试了配置的，再试内置的", [("todo.json" in u) for u in _calls], [True, False])
        check("之后直接用内置地址", _ib.url, inbox.DEFAULT_URL)
        _calls.clear()
        _ib2 = inbox.Inbox(tmpdir(), inbox.DEFAULT_URL)
        _ib2._fetch_or_none()
        check("本来就是内置地址时不重复试", len(_calls), 1)
    finally:
        inbox._fetch = _real_fetch

    # ---- A round in which no door answered, then a later round that got it ----
    # The user, 2026-10-06 05:07: 「报错后自己好了的，只进日报、不进群」 - recovered on the
    # retry: one WARNING marked errwatch.recovered() (daily report only); every
    # round failing: a plain WARNING (pushed).
    import logging
    from ark_relay.features import errwatch


    class _Lines(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.got = []

        def emit(self, record):
            if record.levelno >= logging.WARNING:
                self.got.append((record.getMessage(), bool(getattr(record, errwatch.RECOVERED, False))))


    _lines = _Lines()
    inbox._log_inbox.addHandler(_lines)
    _real_once, _real_sleep = inbox._fetch_once, inbox.time.sleep
    inbox.time.sleep = lambda s: None
    _answers: list = []


    def _fake_once(url, timeout=20, errors=None):
        got = _answers.pop(0) if _answers else None
        if got is None and errors is not None:
            errors.append(f"{inbox._netloc(url)}: timed out")
        return got


    print("\n[a round with no door answering, then a later round got it: daily report only]")
    inbox._fetch_once = _fake_once
    _real_cos_client = inbox._cos_client
    inbox._cos_client = lambda: None     # GitHub doors only in this section
    try:
        doors = len(inbox._alternates(inbox.DEFAULT_URL))
        _answers[:] = [None] * doors + [{"version": 7, "commands": []}] + [None] * (doors - 1)
        _lines.got.clear()
        got = inbox._fetch(inbox.DEFAULT_URL)
        check("round 1 no door, round 2 got it", (got or {}).get("version"), 7)
        check("one WARNING, marked recovered (daily report only)", [r for _, r in _lines.got], [True])
        check("it says which round got it, plain first line",
              [m.splitlines()[0] for m, _ in _lines.got], ["待办文件前 1 轮一扇门都没取到，第 2 轮取到了"])
        _answers[:] = []
        _lines.got.clear()
        check("every round fails: None", inbox._fetch(inbox.DEFAULT_URL), None)
        check("a plain WARNING (pushed), nothing marked recovered",
              [("一扇门都没取到（试了" in m, r) for m, r in _lines.got], [(True, False)])
        _answers[:] = [{"version": 8, "commands": []}] + [None] * (doors - 1)
        _lines.got.clear()
        inbox._fetch(inbox.DEFAULT_URL)
        check("first round got it (other doors failing is not a fault): nothing said", _lines.got, [])
    finally:
        inbox._fetch_once, inbox.time.sleep = _real_once, _real_sleep
        inbox._cos_client = _real_cos_client
        inbox._log_inbox.removeHandler(_lines)

    # ---- The COS door (2026-10-07) ----
    # order.sh writes the file to GitHub and then to COS; jsDelivr caches a branch
    # file for up to 12 hours, COS has no cache. COS is asked first, but every door
    # is still asked and the highest version wins: a COS that missed a write, or a
    # file edited on GitHub by hand, must not hold back a newer copy elsewhere.


    class _FakeCos:
        prefix = "relay"
        host = "bucket.cos.ap-shanghai.myqcloud.com"

        def authorization(self, method, key):
            return f"sig {method} {key}"


    _cos_answer: list = []
    _order: list = []


    def _fake_cos_once(cos, timeout=20, errors=None):
        _order.append("cos")
        got = _cos_answer[0] if _cos_answer else None
        if got is None and errors is not None:
            errors.append("cos: timed out")
        return got


    def _gh_once(url, timeout=20, errors=None):
        _order.append(inbox._netloc(url))
        return _gh_answer[0]


    _gh_answer: list = [None]
    inbox._log_inbox.addHandler(_lines)
    _real_cos_once = inbox._fetch_cos_once
    inbox._fetch_cos_once, inbox._fetch_once = _fake_cos_once, _gh_once
    inbox._cos_client = lambda: _FakeCos()
    inbox.time.sleep = lambda s: None
    print("\n[COS door: asked first, highest version of all doors wins]")
    try:
        _cos_answer[:], _gh_answer[:], _order[:] = [{"version": 12, "commands": []}], [{"version": 11, "commands": []}], []
        _lines.got.clear()
        check("COS newer than the CDN copies: COS's copy", (inbox._fetch(inbox.DEFAULT_URL) or {}).get("version"), 12)
        check("COS was asked first", _order[:1], ["cos"])
        check("the GitHub doors were still asked", len(_order), 1 + len(inbox._alternates(inbox.DEFAULT_URL)))
        _cos_answer[:], _gh_answer[:] = [{"version": 10, "commands": []}], [{"version": 11, "commands": []}]
        check("GitHub newer (edited by hand, COS never saw it): GitHub's copy",
              (inbox._fetch(inbox.DEFAULT_URL) or {}).get("version"), 11)
        _cos_answer[:], _order[:] = [], []
        check("COS down: the GitHub doors still deliver", (inbox._fetch(inbox.DEFAULT_URL) or {}).get("version"), 11)
        check("COS down while another door answered: nothing said", _lines.got, [])
        _gh_answer[:] = [None]
        _lines.got.clear()
        check("COS and every GitHub door down: None", inbox._fetch(inbox.DEFAULT_URL), None)
        check("the WARNING names the COS door too", any("cos: timed out" in m for m, _ in _lines.got), True)
        inbox._cos_client = lambda: None
        _gh_answer[:], _order[:] = [{"version": 11, "commands": []}], []
        inbox._fetch(inbox.DEFAULT_URL)
        check("COS not configured on the machine: COS not asked", "cos" in _order, False)
    finally:
        inbox._fetch_cos_once, inbox._fetch_once = _real_cos_once, _real_once
        inbox._cos_client, inbox.time.sleep = _real_cos_client, _real_sleep
        inbox._log_inbox.removeHandler(_lines)

    print("\n[COS not configured (no COS_* in the environment): no COS door]")
    import os

    _saved = {k: os.environ.pop(k) for k in ("COS_SECRET_ID", "COS_SECRET_KEY", "COS_BUCKET", "COS_REGION")
              if k in os.environ}
    try:
        check("no client", inbox._cos_client(), None)
    finally:
        os.environ.update(_saved)

    print("\n[the COS door's own request: signed GET of relay/queue/config.json]")
    import io
    import urllib.error

    _seen: list = []


    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


    def _urlopen_ok(req, timeout=None):
        _seen.append((req.full_url, req.get_header("Authorization")))
        return _Resp(json.dumps({"version": 2026100701, "commands": []}).encode())


    def _urlopen_404(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)


    _real_urlopen = inbox.urllib.request.urlopen
    try:
        inbox.urllib.request.urlopen = _urlopen_ok
        got = inbox._fetch_cos_once(_FakeCos())
        check("reads the version", (got or {}).get("version"), 2026100701)
        check("object key under relay/ (kept by the lifecycle rule)",
              _seen[0][0], "https://bucket.cos.ap-shanghai.myqcloud.com/relay/queue/config.json")
        check("signed for that key", _seen[0][1], "sig GET relay/queue/config.json")
        inbox.urllib.request.urlopen = _urlopen_404
        errs: list = []
        _lines.got.clear()
        inbox._log_inbox.addHandler(_lines)
        check("no object yet: None", inbox._fetch_cos_once(_FakeCos(), errors=errs), None)
        check("noted for the all-doors warning", len(errs) == 1 and errs[0].startswith("cos:"), True)
        check("one door failing logs nothing above debug", _lines.got, [])
    finally:
        inbox.urllib.request.urlopen = _real_urlopen
        inbox._log_inbox.removeHandler(_lines)

    print("\n[the receipt of an order.sh batch: all through -> log only; any ✗ -> the group, with the ✗ lines]")
    # CLAUDE.md 「测试不进他眼」 and docs/NOTIFICATIONS.md (the 「Config command applied」 row, de038830):
    # our own order.sh orders are not his business when they went through. Until 2026-10-13 every
    # receipt went to his Server酱 (route info; day replay 2026-10-12 / 10-13, BACKLOG daysim-R2).
    # A failed one takes the phone's failure route (texts.CONFIG_FAILED, alert=True, the group),
    # never the log list's 「⚙️ 配置已更新」 title, which route_of would keep out of the group.
    import types as _types


    class _Stub(_types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return lambda *a, **k: None


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
                  "servicemanager", "win32process", "pythoncom"):
        sys.modules.setdefault(_name, _Stub(_name))
    import logging

    import boot_stages
    from ark_relay.core import texts
    from ark_relay.core.notify import route_of


    class _Note:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", alert=False, **_k):
            self.sent.append((title, body, alert))
            return []


    def collected(payload, lines):
        """One collect('boot') over a batch whose commands answer `lines` (None: _apply raises)."""
        b = box(payload)
        if lines is None:
            b._apply = lambda cmds: (_ for _ in ()).throw(OSError("盘满了"))
        else:
            b._apply = lambda cmds: list(lines)
        n = _Note()
        engine = _types.SimpleNamespace(scripts_running=lambda: False)
        boot_stages._make_collect(b, engine, n, logging.getLogger("ark.test_phone"), [False])("boot")
        check("one send", len(n.sent), 1)
        return n.sent[0] if n.sent else ("", "", False)


    # relay.log 10-12 08:46 (day replay 2026-10-12 events.jsonl line 15): the debug-mode order, through.
    DEBUG_OK = ("✅ 🔧 调试模式已开启，至 10-12 21:10（下次预定开机 10-12 21:20 前 10 分钟）：不关机。"
            "注意：要让机器什么都不刷，还需停用相应队列。")
    title, body, alert = collected({"version": 2026101201, "name": "调试模式", "note": "从电脑发来的指令：调试模式",
                                    "commands": [{"action": "debug_mode"}]}, [DEBUG_OK])
    check("all through: the title is the receipt", title, "⚙️ 配置已更新：调试模式")
    check("all through: log only, not his Server酱", route_of(title, alert=alert), "log")
    # relay.log 10-12 12:10 (events.jsonl line 461): an empty batch, the safe state.
    title, body, alert = collected({"version": 2026101202, "name": "空（安全状态）", "commands": []}, [])
    check("an empty batch: log only", route_of(title, alert=alert), "log")
    FAILED = "✗ set_stage: 「YW-4」MAA 走不到，修改失败"
    title, body, alert = collected({"version": 2026101203, "name": "改关卡", "commands": [{}, {}]}, [DEBUG_OK, FAILED])
    check("a ✗ line: the phone's failure title, with the batch name", title, f"{texts.CONFIG_FAILED}：改关卡")
    check("a ✗ line: the group", route_of(title, alert=alert), "group")
    check("the push carries the failed line", FAILED in body, True)
    title, body, alert = collected({"version": 2026101204, "name": "会炸的一批", "commands": [{}]}, None)
    check("broken mid-batch: the group", route_of(title, alert=alert), "group")
    check("broken mid-batch: says so", "应用中途出错" in body, True)
    check("the receipt title is log only even with alert=True, so a failure must not use it",
          route_of("⚙️ 配置已更新：x", alert=True), "log")

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_phone_main, _part_phone_channel_boot, _part_phone_cmd_gate, _part_phone_cmd_queue, _part_phone_drained_failure_pushed, _part_phone_gzip, _part_phone_order_failed_pushed, _part_phone_quiet, _part_phone_receipts, _part_phone_sent, _part_phone_silent, _part_phone_stale_cmd, _part_phone_state, _part_phone_state_cos, _part_receipt_target, _part_channel_down, _part_cli_commands, _part_cmd_test_channels, _part_command_table, _part_commands_gates, _part_mailbox_close_windows, _part_payload_roundtrip, _part_test_windows, _part_heartbeat_main, _part_heartbeat_cos, _part_resources, _part_snapshot, _part_inbox_poll]))
