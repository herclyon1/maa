"""The pipe between the phone and the machine. Zero polling.

The shape the user settled on, 2026-08-31:

* every boot fetches commands once and reports state once
* state is reported once more before shutdown
* pressing "refresh" on the phone gets live state - **only while the machine is
  powered on**
* an online/offline indicator, with no polling

**Why this is not polling**: the machine holds one long-lived connection to ntfy
and then sits still; the server pushes only when there is a message (measured
latency 0.90 s). It is the same shape as the two mechanisms the relay already
uses: the WMI subscription on process start, and directory-change notifications.
A dropped connection is reconnected, and reconnecting is not polling.

**How online is decided**: the phone sends a ping and the machine answers with
state. An answer within a few seconds means it is up; no answer means it is down.
No heartbeat is needed, so no polling is needed.

**The only credential is a PIN** (the user, 2026-08-31:
「留一个 pin 就行了，那那么多事」). The mailbox name itself is a random string
(32 characters in the Mac copy, measured 2026-09-23) kept in the user's phone, the machine's .env and the Mac's
~/.config/ark/push.env (ARK_PHONE_TOPIC / ARK_PHONE_PIN; docs/CONFIG.md
"Relay environment" names the index of every key's location).
State carries game config only, never credentials.

A command pressed on the phone has to survive in the mailbox until the next boot
(the machine powers on twice a day), and ntfy.sh keeps a message 12 hours
(NTFY_CACHE_SEC). A machine off for longer cannot read what was pressed in
between: the window it could not read is recorded at boot (Mailbox.blind) and
carried in the state as relay.信箱空窗, so the phone can tell an order that
never arrived from one still waiting. Commands already handled are remembered
by ntfy's own message id, so nothing runs twice.
"""
from __future__ import annotations

import contextlib
from datetime import datetime
import logging
import threading
import time
from pathlib import Path

from ark_relay.features.phone.mas_labels import SHOWN, _options
# The rest of the phone channel lives in sibling modules (wire, quota, cos_store,
# mailbox, heartbeat, cmdqueue); callers and tests say phone.<name>, so every
# name stays importable from here. A test that rebinds a module global such as
# urllib, time, NTFY or cos_put has to rebind it in the module whose code reads it.
from ark_relay.features.phone.wire import (
    BLIND_KEEP, MARK_SAVE_SEC, MAX_AGE, NTFY, NTFY_CACHE_SEC, SEEN_KEEP, _QUIET_ACTIONS, _UA, _bj,
    pack, pack_chunks, stamp, unpack,
)
from ark_relay.features.phone.quota import (
    HB_CRAWL_SEC, HB_FAST_UNTIL, HB_KICK_GAP, HB_SLOW_SEC, HB_SLOW_UNTIL, HB_STOP_AT, HEARTBEAT_SEC,
    NOTICE_STOP_AT, NTFY_ACCOUNT, NTFY_DAILY_LIMIT, QUOTA_SYNC_SEC, WATCH_LEASE_SEC, Quota,
    _idle_timeout, _ntfy_code, _retry_after, _why, ntfy_account,
)
from ark_relay.features.phone.cos_store import (
    STATE_PREFIX, cos_get, cos_put, hb_key, state_cos, state_key,
)
from ark_relay.features.phone.mailbox import (
    Mailbox,
)
from ark_relay.features.phone.heartbeat import (
    HB_COS_SEC, Heartbeat,
)
from ark_relay.features.phone.cmdqueue import (
    CMD_QUEUE_DONE_KEEP, CMD_QUEUE_FILE, DISPATCHING_ACTIONS, QUEUED, RESENT, SAME, _CMD_QUEUE_LOCK,
    _content, _item_keys, CmdQueue, cmd_expired, cmd_key, item_sent,
)

__all__ = [
    "log",
    "_last_error",
    "REFRESH_ANSWERED_SEC",
    "StatePusher",
    "mailbox_status",
    "state_payload",
    "BLIND_KEEP",
    "MARK_SAVE_SEC",
    "MAX_AGE",
    "NTFY",
    "NTFY_CACHE_SEC",
    "SEEN_KEEP",
    "_QUIET_ACTIONS",
    "_UA",
    "_bj",
    "pack",
    "pack_chunks",
    "stamp",
    "unpack",
    "HB_CRAWL_SEC",
    "HB_FAST_UNTIL",
    "HB_KICK_GAP",
    "HB_SLOW_SEC",
    "HB_SLOW_UNTIL",
    "HB_STOP_AT",
    "HEARTBEAT_SEC",
    "NOTICE_STOP_AT",
    "NTFY_ACCOUNT",
    "NTFY_DAILY_LIMIT",
    "QUOTA_SYNC_SEC",
    "WATCH_LEASE_SEC",
    "Quota",
    "_idle_timeout",
    "_ntfy_code",
    "_retry_after",
    "_why",
    "ntfy_account",
    "STATE_PREFIX",
    "cos_get",
    "cos_put",
    "hb_key",
    "state_cos",
    "state_key",
    "Mailbox",
    "HB_COS_SEC",
    "Heartbeat",
    "CMD_QUEUE_DONE_KEEP",
    "CMD_QUEUE_FILE",
    "DISPATCHING_ACTIONS",
    "QUEUED",
    "RESENT",
    "SAME",
    "_CMD_QUEUE_LOCK",
    "_content",
    "_item_keys",
    "CmdQueue",
    "cmd_expired",
    "cmd_key",
    "item_sent",
]

log = logging.getLogger("ark.phone")

# state_payload runs on every phone-state publish and a WARNING is a group
# message: a block it cannot build is said once per condition (block -> the
# error last said, as WeeklyBossGate._last_error), forgotten once it builds again.
_last_error: dict[str, str] = {}


# ---------- one push_state for the whole relay ----------
#
# A refresh is answered by any state that reaches the mailbox shortly before or
# after it was asked: the page and the App open their stream with since=30s
# before sending "refresh" (web/live.js _ping, ark-remote Live.swift
# pingInner), so a state posted up to 30 s before the press is replayed to
# them. 20 s leaves room for the few seconds a four-piece post takes.
REFRESH_ANSWERED_SEC = 20


class StatePusher:
    """push_state for the whole relay, with two savings on ntfy's 250 a day.

    * A refresh that a state already answers is not answered again. The App
      sends a second refresh 4 s after the first if no state is back yet
      (Live.swift pingInner `resent`), and a state takes ~5-20 s to read and
      post, so without this nearly every press would cost two states. And the
      refreshes pressed while the machine was off all come back out of the
      mailbox at boot, right after the boot state already answered them.
    * While held (the boot backlog), every push is put off and sent once at the
      end, rather than one state per config order in the backlog.

    `publish(why)` builds and sends one state and returns whether it got out.
    Pushes that are not refreshes (改完配置, 红按钮, 关机前, 跳过队列) are never
    skipped - they carry a change the page has to see.
    """

    def __init__(self, publish):
        self._publish = publish
        self._lock = threading.Lock()
        self._done = 0.0               # when the last state that got out finished
        self._held = 0
        self._pending: list[str] = []

    def answered(self, asked_at=None) -> bool:
        """True when a state that got out answers a refresh asked at `asked_at`
        (ntfy's receive time, unix seconds; now when unknown) - logged once."""
        try:
            asked = float(asked_at)
        except (TypeError, ValueError):
            asked = time.time()
        with self._lock:
            done = self._done
        if done and asked <= done + REFRESH_ANSWERED_SEC:
            log.info("📱 手机要刷新（%s 收到）：%s 已发完一份状态，它收得到，不再重发（省 ntfy 额度）",
                     _bj(asked, "%H:%M:%S"), _bj(done, "%H:%M:%S"))
            return True
        return False

    # Never put off: the last state before a stop or a power-off. Folded into a held
    # batch it lost its exact label (the stop marker, machinecheck #11 and the
    # watchdog's 关机前 test match it) and went out later on the holding thread,
    # inside SvcStop's 15 s kill timer (audit status-channel A1).
    NEVER_HELD = ("停止前", "关机前")

    def __call__(self, why: str) -> bool:
        with self._lock:
            if self._held and why not in self.NEVER_HELD:
                self._pending.append(why)
                return False
        ok = bool(self._publish(why))
        if ok:
            with self._lock:
                self._done = time.time()
        return ok

    @contextlib.contextmanager
    def held(self):
        """`with pusher.held():` - pushes inside are put off and sent once at the end."""
        with self._lock:
            self._held += 1
        try:
            yield self
        finally:
            with self._lock:
                self._held -= 1
                whys = self._pending if self._held == 0 else []
                if self._held == 0:
                    self._pending = []
            if whys:
                names = list(dict.fromkeys(whys))
                self("、".join(names) + (f"（{len(whys)} 次合成一次）" if len(whys) > 1 else ""))


def mailbox_status(state_dir) -> list[dict]:
    """relay.信箱空窗 in the state: the windows the mailbox could not read
    (Mailbox._note_blind), oldest first, each {"从", "到", "开机"} in unix
    seconds. A press sent inside one never reached the machine: ntfy had
    dropped it before the boot read. The App compares an order's send time
    with them (its sent time is on ntfy's clock, Net.send; "从" is ntfy's time
    of the last line read, "到" the machine's boot read minus NTFY_CACHE_SEC)."""
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415
    kept = StateStore(Path(state_dir)).get("queues", "phone_blind")
    out = []
    for g in kept if isinstance(kept, list) else []:
        if isinstance(g, dict) and all(isinstance(g.get(k), int) for k in ("from", "to", "boot")):
            out.append({"从": g["from"], "到": g["to"], "开机": g["boot"]})
    return out


def state_payload(cfg, state_dir: Path) -> dict:
    """The payload the phone displays. Same code config-check reads (snapshot.py)."""
    from ark_relay.features.modes import modes  # noqa: PLC0415
    from ark_relay.features.phone import monthcard, snapshot  # noqa: PLC0415
    from ark_relay.core import plan  # noqa: PLC0415 - avoids an import cycle
    out: dict = {"at": int(time.time())}
    # Only the keys the phone displays. The full snapshot is not sent: of it the
    # phone gets only the service state and the running scripts ("run"); the
    # queues come from plan.queue_rows and the config from maa_from_files below.
    keep = {k.split(".", 1)[1] for k in SHOWN} | {"关卡", "理智药", "剿灭",
            "作战开关", "活动关优先", "活动关序号"}
    try:
        full = snapshot.read_runtime()
        # The orchestrator is always up while the machine is; listing it made
        # 「现在没有脚本在跑」 impossible to ever show, and 「在跑：AUTO-MAS」 tells him
        # nothing. Only scripts and games count as running.
        from ark_relay.core.config import ORCHESTRATOR_PROC  # noqa: PLC0415
        orch = ORCHESTRATOR_PROC[:-4]
        out["run"] = {"服务": full.get("ark-relay"),
                      "在跑的": [n for n, on in (full.get("程序") or {}).items() if on and n != orch]}
    except Exception:
        log.warning("快照读不到，服务和在跑的程序这次不报", exc_info=True)
    # Arknights only: the MAS fields for the other two games are not sent, see
    # mastercfg. From ScriptConfig.json, like the queues and the plan below
    # (snapshot.maa_from_files): the backend is gone at the service-stop push.
    try:
        maa = snapshot.maa_from_files(getattr(cfg, "automas_dir", None))
        out["config"] = {"MAA": {k: v for k, v in maa.items() if k in keep}}
    except Exception as exc:  # noqa: BLE001
        out["config"] = {"_错误": f"{type(exc).__name__}: {exc}"}
    # The queues from AUTO-MAS's config files, the source "plan" below reads too
    # (plan.queue_rows), not from the snapshot: its queue section needs the
    # backend, which is gone at the service-stop push.
    try:
        out["queues"] = plan.queue_rows(getattr(cfg, "automas_dir", None))
    except Exception as exc:
        log.warning("班次名单读不到", exc_info=True)
        # [] read on the App as "no shift", i.e. every game in the shift - as if
        # real. A row with only `_错误`, like config's marker (audit A3).
        out["queues"] = [{"_错误": f"{type(exc).__name__}: {exc}"}]
    try:
        from ark_relay.features.weekly import annihilation, garden, weeklyboss  # noqa: PLC0415
        automas = getattr(cfg, "automas_dir", None)
        wb = weeklyboss.WeeklyBossGate(state_dir, automas).settings()
        out["relay"] = {
            # only while it holds: an expired end time would read as "on" on the phone; shutdown also goes by
            # debug_active
            "调试模式": modes.debug_until(state_dir) if modes.debug_active(state_dir) else "",
            "刷声骸": (lambda r: {"名字": r.get("name"), "到": r.get("until"),
                                  "从": r.get("started")} if r else {})(
                __import__("ark_relay.features.echofarm.echofarm", fromlist=["x"]).current(state_dir)),
            "下次别关机": modes.skip_armed(state_dir),
            # Which queues sit out today: the page shows each as its queue
            # row's switch. "今天跳过" is the first one ("" = none) for pages
            # that read a single name; "今天跳过队列" lists them all (two
            # queues can sit out the same day).
            "今天跳过": modes.skipped_today(state_dir) or "",
            "今天跳过队列": modes.skipped_today_all(state_dir),
            "无音区截图": modes.tacet_shots_on(state_dir),
            # Monthly cards the user registered (monthcard.py, spec 月卡到期提示-规格.md).
            "月卡": monthcard.status(state_dir),
            "最近指令": modes.receipts(state_dir),
            # Windows the mailbox could not read: presses sent in one never
            # arrived (mailbox_status).
            "信箱空窗": mailbox_status(state_dir),
            "周本": wb,
            # The three "once a week" things share one shape: done this week /
            # the switch / their own settings
            "周常": {
                "剿灭": annihilation.WeeklyGate(state_dir, automas).settings(),
                "周常乐园": garden.GardenGate(state_dir, automas).settings(),
                "周本": wb,
            },
        }
        _last_error.pop("relay", None)
    except Exception as exc:
        # {} read on the phone as switches off, weekly not done, no month
        # cards - as if real. `_错误` marks it, like config (audit A3).
        if _last_error.get("relay") != (key := f"{type(exc).__name__}: {exc}"):
            log.warning("手机状态里中继那一段读不到，App 上的开关、周常和月卡这次是空的", exc_info=True)
            _last_error["relay"] = key
        out["relay"] = {"_错误": key}
    try:
        out["options"] = _options(cfg)
    except Exception:  # noqa: BLE001
        out["options"] = {}
    # Endfield and Wuthering Waves are configured through the scripts' own config,
    # not through MAS - changing it on the MAS side has no effect.
    try:
        from ark_relay.core import mastercfg  # noqa: PLC0415
        out["master"] = {
            "MAA": mastercfg.read_maa(getattr(cfg, "automas_dir", None)),
            "MaaEnd": mastercfg.read_maaend(getattr(cfg, "automas_dir", None),
                                            getattr(cfg, "maaend_dir", None)),
            "OK-WW": mastercfg.read_okww(getattr(cfg, "automas_dir", None),
                                         getattr(cfg, "okww_dir", None)),
        }
    except Exception:
        log.warning("母本配置读不到", exc_info=True)
        out["master"] = {}
    try:
        out["plan"] = plan.next_plan(cfg.automas_dir)
        _last_error.pop("plan", None)
    except Exception as exc:
        if _last_error.get("plan") != (key := f"{type(exc).__name__}: {exc}"):
            log.warning("明日安排算不出来，App 上那一段这次是空的", exc_info=True)
            _last_error["plan"] = key
        out["plan"] = ""
    # The number tiles on the 状态 tab: the page reads the games' stamina itself
    # (web/stamina.js); it only needs the Skland session from here, plus today's
    # run count from the ledger.
    try:
        from ark_relay.features.phone import resources  # noqa: PLC0415
        from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
        from ark_relay.core.ledger import State  # noqa: PLC0415
        out["密钥"] = {"sk": resources.skland_session(cfg)}
        out["今天"] = resources.today(State(Path(state_dir)), datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
    except Exception:
        log.warning("森空岛会话和今天的统计读不到", exc_info=True)
    return out


# ---------- one state to the phone, and the last one before a stop ----------

STOP_WHY = "停止前"
# Written into the state folder when a 「停止前」 state reached the phone, deleted when
# the phone channel comes up (boot_stages._start_phone_channel). The watchdog service's
# shutdown push (app_main.py stop-push) reads it: present = the relay's own last push
# already got out, so it does not send a second one.
STOP_PUSHED_FILE = "stop-pushed.txt"


def stop_pushed(state_dir) -> bool:
    """True when this relay process's 「停止前」 state reached the phone (STOP_PUSHED_FILE)."""
    return (Path(state_dir) / STOP_PUSHED_FILE).is_file()


def clear_stop_pushed(state_dir) -> None:
    try:
        (Path(state_dir) / STOP_PUSHED_FILE).unlink(missing_ok=True)
    except OSError:
        # INFO: in the relay every WARNING goes to the group, and this needs no person.
        log.info("上次停止前那份的记号删不掉，这次关机时看门服务可能不补发", exc_info=True)


def send_state(box, cfg, why: str, log=log) -> "tuple[bool, dict | None, str]":
    """Build the state and send it through `box`: (reached the phone, payload, why not).

    The one place a state goes out and the two lines saying how it went are written:
    the relay's own pushes (boot_stages publish_state) and the watchdog's push at a
    Windows shutdown (app_main.py stop-push) both come here, and the machine checks
    match these exact words (machinechecks/system.py PUSHED / NOT_PUSHED, #11).
    The day's count rides along: on 2026-10-02 nobody could see the 250 running out
    until it had (phone.Quota; ntfy's own count once synced)."""
    payload = None
    from ark_relay.features.phone import snapshot  # noqa: PLC0415
    # The last state before a stop / power-off must not wait on the process list.
    quiet = snapshot.no_process_query() if why in StatePusher.NEVER_HELD else contextlib.nullcontext()
    try:
        with quiet:
            payload = state_payload(cfg, cfg.state_dir)
        ok = box.publish(payload)
    except Exception as exc:
        log.warning("状态没能上报到手机（%s）", why, exc_info=True)
        return False, payload, f"{type(exc).__name__}: {exc}"[:160]
    if ok:
        log.info("📱 已上报状态到手机（%s；今天 ntfy 已用 %d 条）", why, box.quota.total())
        if why == STOP_WHY:
            try:
                (Path(cfg.state_dir) / STOP_PUSHED_FILE).write_text(
                    time.strftime("%Y-%m-%d %H:%M:%S\n"), encoding="utf-8")
            except OSError:
                log.warning("停止前那份送到了，记号没写下，关机时看门服务会再发一次", exc_info=True)
        return True, payload, ""
    # Only when the phone cannot see this state at all: neither COS nor ntfy carried
    # it (a state on COS is delivered even when the ntfy notice is refused - 10-02
    # 22:56 that was logged here as a failure, with 「今天 ntfy 已发 0 条」 beside
    # ntfy's own 42908).
    log.warning("状态没能上报到手机（%s）：%s；手机上留着上一份状态", why, box.last_error or "原因没说")
    return False, payload, box.last_error or "原因没说"
