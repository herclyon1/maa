"""The relay loop, shared by local mode and server mode.

Given a Source of run records, this decides what to say and when to say it:

    failure       push immediately
    success       book it silently, no push
    end of day    push one daily report (日报)

Judgment happens here in plain Python. The model is asked for wording only,
after the verdict is already fixed.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from . import banners, collector, core, modes, outcome, plan, summary
from .config import SERVER_TZ, Config, RunRecord
from .core import State
from .notify import Notifier
from .transport import Source

log = logging.getLogger("ark.engine")

# How long past a queue's time before "it produced nothing" becomes a fault.
MISSED_GRACE_MIN = 25
# A wake-up checkpoint is judged once, in this window past the hour: open two
# minutes late (a queue may start a moment behind), closed five minutes later.
CHECK_OPEN_MIN, CHECK_CLOSE_MIN = 2, 7
# How far a round's FIRST record may sit from a scheduled time and still count
# as that scheduled round. Only the first record is tested: a queue's later
# scripts legitimately land 40+ minutes in (MAA then MaaEnd), so testing every
# record against this window would call every healthy morning "manual".
MANUAL_WINDOW_MIN = 30


def _okww_master_config(automas_dir: str | Path | None, name: str) -> dict:
    """读 OK-WW **真正生效**的那份配置。

    OK-WW 自己目录里那份跑之前会被 AUTO-MAS 整个换掉、跑完再还原，
    所以事后去读它读到的是「假的」。真正生效的在
    `<automas>/data/<脚本id>/Default/ConfigFile/`。
    脚本 id 不固定，扫一遍即可——这台机器上只有 OK-WW 有这个目录结构。
    """
    if not automas_dir:
        return {}
    root = Path(automas_dir) / "data"
    if not root.is_dir():
        return {}
    for sid in root.iterdir():
        f = sid / "Default" / "ConfigFile" / f"{name}.json"
        if f.is_file():
            try:
                d = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and d:
                return d
    return {}


def _okww_nest_expected(automas_dir: str | Path | None) -> bool | None:
    """这一轮本来该不该打残象聚落。**读不到配置返回 None，不是 False。**

    原来读不到就返回 False，于是「配置说不用打」和「我根本没读到配置」
    长得一模一样——后者会让残象聚落那一项**整个消失**，OK-WW 照报全绿。
    `_okww_master_config` 在没有 automas_dir、没有 data 目录、JSON 读坏
    这三种情况下都返回 `{}`，任何一种都会走到这里。
    这就是 2026-08-30 排查出的那一类 bug：前置不满足 → 静默什么都不做 → 看着像成功。
    """
    nest = _okww_master_config(automas_dir, "NightmareNestTask")
    daily = _okww_master_config(automas_dir, "DailyTask")
    if not nest and not daily:
        return None
    if (nest.get("Only Farm These Nests") or "").strip():
        return True
    if daily.get("Farm Nightmare Nest for Daily Echo"):
        return True
    adds = daily.get("Additional Tasks to Run After Daily Task") or []
    return "Auto Farm all Nightmare Nest" in adds


# MAA 的行首时间戳：[2026-08-30 09:09:41.495][INF]...
_MAA_TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
# 尾巴取多少。一轮约三万行 / 六七 MB，留 16 MB 足够覆盖一整轮。
_MAA_LOG_TAIL = 16 * 1024 * 1024


def _maaend_app_log(maaend_dir: "str | Path | None",
                    started: datetime) -> str:
    """这一轮 MaaEnd **自己**写的 app 日志。

    收尾标记「INFO [App] 自动执行任务完成，关闭自身」只出现在
    `<maaend>/debug/YYYY-MM-DD-N.log` 里，**不在 AUTO-MAS 的 history 日志里**。
    2026-08-29 早班就是只核对了后者，于是「MaaEnd 跑完」这条恒为假，
    推了一条「这一轮没干完」的假告警——而 MaaEnd 当时 09:54:38 明明打了那句。
    判据没错，错在没把它该看的文件给它。
    """
    if not maaend_dir:
        return ""
    d = Path(maaend_dir) / "debug"
    if not d.is_dir():
        return ""
    cut = started.timestamp()
    out: list[str] = []
    # 文件名形如 2026-08-29-7.log；maafw*/go-service 是框架日志，不看。
    for f in sorted(d.glob("20??-??-??-*.log")):
        try:
            if f.stat().st_mtime < cut:
                continue
            out.append(f.read_text(encoding="utf-8", errors="replace")[-200_000:])
        except OSError:
            continue
    return "\n".join(out)


def _maa_app_log(maa_dir: "str | Path | None", started: datetime,
                 until: "datetime | None" = None) -> "str | None":
    """这一轮 MAA **自己**写的 asst.log，只保留本轮时间窗内的行。

    AUTO-MAS 的 history 日志只记「脚本跑完了没有」，**没有子任务级别的成败**。
    所以在 2026-08-30 之前，基建整个失败（`InfrastAbstractTask::on_run_fails`）
    也照样被记成全绿——用户连着两天看到的「全绿」就是这么来的。

    和 MaaEnd 不一样的地方：MaaEnd 每轮一个新文件，可以按 mtime 挑；
    MAA 是**一个滚动的 asst.log**，只能按行首时间戳切。
    """
    if not maa_dir:
        return None
    f = Path(maa_dir) / "debug" / "asst.log"
    if not f.is_file():
        return None
    try:
        # 一轮就有三万多行，整文件读没必要；取尾巴再按时间切。
        size = f.stat().st_size
        with f.open("rb") as fh:
            if size > _MAA_LOG_TAIL:
                fh.seek(size - _MAA_LOG_TAIL)
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    # 只有起点没有终点会把**后面几趟**也扫进来。2026-08-30 空跑时
    # 08-29 晚班读到 72810 行（今早那趟的两倍），技能失败数变成 20+21=41，
    # 等于把今早的错算到了昨晚头上。所以必须有上界。
    # `until` 给 None 时不设上界——`duration_known=False` 的记录时间不可信，
    # 那种情况宁可多取也不要把整趟切没了。
    cut = started.strftime("%Y-%m-%d %H:%M:%S")
    top = until.strftime("%Y-%m-%d %H:%M:%S") if until else None
    out: list[str] = []
    keep = False
    for line in raw.splitlines():
        m = _MAA_TS.match(line)
        if m:
            # 时间戳是定宽的，字典序等于时间序，这里可以直接比。
            ts = m.group(1)
            keep = ts >= cut and (top is None or ts <= top)
        # 没有时间戳的是上一条的续行，跟着上一条走——不要单独判断，
        # 否则 traceback 那些行会被无条件带进来（arklog.py 里记过这个坑）。
        if keep:
            out.append(line)
    # 一行都没落在窗口里 = 这一轮的日志没找到，和「读不到文件」一样无从核对。
    # 返回 "" 会被判据当成「什么错都没有」，那又是一次假全绿。
    return "\n".join(out) if out else None


def _maaend_new_shots(maaend_dir: str | Path | None,
                      started: datetime) -> list[str]:
    """这一轮新出现的 on_error 截图文件名。

    MaaEnd 卡住时不报错，但万能跳转失败会存图——那是唯一的证据。
    """
    if not maaend_dir:
        return []
    d = Path(maaend_dir) / "debug" / "on_error"
    if not d.is_dir():
        return []
    cut = started.timestamp()
    return sorted(p.name for p in d.glob("*.png")
                  if p.stat().st_mtime >= cut)


class Engine:
    def __init__(self, cfg: Config, source: Source, state: State, notifier: Notifier):
        self.cfg = cfg
        self.source = source
        self.state = state
        self.notifier = notifier
        # 关机前最后拉一次待办用的钩子，由 service 接上（见 _maybe_shutdown）。
        # 单机跑测试时是 None，那就不拉。
        self._before_shutdown = None
        # Populated by the HTTP layer in server mode, where the log tail
        # arrives with the payload instead of being read off local disk.
        self.log_tails: dict[str, str] = {}
        # Failures held back until we know whether a retry rescued them.
        # AUTO-MAS retries a failed script up to RunTimesLimit times; alerting
        # on the first attempt turns a self-healing hiccup into a false alarm.
        self._pending: dict[tuple[str, str], RunRecord] = {}
        # Failures that a later retry got past. Still reported, and reported as
        # an unresolved fault - the run survived, the bug did not go away.
        self._recovered: dict[tuple[str, str], RunRecord] = {}
        self._restore_pending()
        self._missed_alerted: set[str] = set()
        self._started_at = datetime.now(tz=SERVER_TZ)
        self._handled_any = False   # nothing ran this session -> nothing to shut down for
        self._shutdown_issued = False  # a countdown is already running; never twice
        self._last_wait_note = ""  # so the guard does not repeat itself every poll
        self._mode_notified: set[str] = set()  # skip-mode messages already pushed
        self._debug_last: bool | None = None  # log mode transitions, not every tick
        from .annihilation import WeeklyGate  # noqa: PLC0415 - optional feature
        self._annihilation = WeeklyGate(state.dir, cfg.automas_dir)
        # 周常乐园和剿灭是同一个形状的问题：一周只需要做一次的事，
        # 别每天都跑去看一眼。区别只在剿灭关的是 MAA 的开关、
        # 这个关的是 OK-WW 的「Check Weekly Garden」附加任务。
        from .garden import GardenGate     # noqa: PLC0415 - optional feature
        # 2026-08-28 起直接写母本，不再走 MAS 的接口——那条路要求快速配置
        # 开着，而快速配置已经废掉了。
        self._garden = GardenGate(state.dir, cfg.automas_dir)
        from .weeklyboss import WeeklyBossGate  # noqa: PLC0415 - 避免导入环
        self._weeklyboss = WeeklyBossGate(state.dir, cfg.automas_dir)

    # ---------- operator modes ----------

    def _observe_modes(self) -> None:
        """Advance skip-mode and make debug-mode transitions visible.

        Runs at the top of every tick: the skip flag must engage before the
        queue it targets comes due, and a mode change should announce itself
        once in the log rather than being discovered from what did not happen.
        """
        # Skip mode (跳过模式) edits AUTO-MAS's queue config, so like every
        # other config write it has to stay clear of a running script -
        # otherwise AUTO-MAS's in-memory copy wipes it, and "skip today"
        # quietly fails while the queue runs anyway.
        # Deferring costs nothing: a script is already running, so this round
        # was never going to be stopped; engage on the next tick.
        if self._scripts_running():
            return
        try:
            for msg in modes.process_skip(self.state.dir, self.cfg.automas_dir):
                log.info("⏭️ %s", msg)
                # A *persistent* failure (queue renamed while a restore marker
                # is pending) returns the identical message on every tick, and
                # ticks fire on every directory event - dedup per process, or
                # the operator gets the same push dozens of times a boot.
                if msg not in self._mode_notified:
                    self._mode_notified.add(msg)
                    self.notifier.send("⏭️ 跳过模式", msg)
        except Exception:  # noqa: BLE001 - modes must never stop the loop
            log.exception("跳过模式处理出错")
        active = modes.debug_active(self.state.dir)
        if active != self._debug_last:
            if active:
                log.info("🔧 调试模式生效（至 %s）：不关机、不报漏跑",
                         modes.debug_until(self.state.dir))
            elif self._debug_last is not None:
                log.info("🔧 调试模式已结束，恢复正常判定")
            self._debug_last = active

    # ---------- survive restarts ----------

    def _restore_pending(self) -> None:
        """Reload alerts that were queued but never delivered."""
        from .transport import payload_to_record  # noqa: PLC0415 - avoid cycle
        data = self.state.load_pending()
        for bucket, target in (("pending", self._pending), ("recovered", self._recovered)):
            for item in data.get(bucket, []):
                try:
                    rec = payload_to_record(item)
                except (KeyError, ValueError, TypeError):
                    continue
                target[(rec.script, rec.user)] = rec
        if self._pending or self._recovered:
            log.info("从磁盘恢复了 %d 条未送达的告警",
                     len(self._pending) + len(self._recovered))

    def _persist_pending(self) -> None:
        from .transport import record_to_payload  # noqa: PLC0415 - avoid cycle
        self.state.save_pending({
            "pending": [record_to_payload(r) for r in self._pending.values()],
            "recovered": [record_to_payload(r) for r in self._recovered.values()],
        })

    # ---------- first ever start ----------

    def bootstrap(self) -> int:
        """Adopt whatever history already exists as already-handled.

        A fresh install must not replay past runs as new alerts. Those records
        describe problems that were either already dealt with or are simply
        old news; pushing them looks like a flood of failures that just
        happened. Only runs produced after the relay starts are news.
        """
        if self.state.seen_path.exists():
            return 0
        adopted = 0
        for rec in self.source.fetch(set()):
            self.state.mark_seen(rec.run_id)
            adopted += 1
        # Touch the file even when there is nothing, so the next start is not
        # treated as a first start.
        self.state.seen_path.touch(exist_ok=True)
        if adopted:
            log.info("首次启动：已把 %d 条历史记录标记为已处理，不会重复告警", adopted)
        return adopted

    # ---------- one pass ----------

    def tick(self) -> int:
        """Process whatever is new. Returns how many records were handled."""
        self._observe_modes()
        records = self.source.fetch(self.state.seen)
        for rec in records:
            try:
                self._handle(rec)
            except Exception:  # noqa: BLE001 - one bad record must not stop the loop
                log.exception("处理运行记录失败: %s", rec.run_id)
                continue
            self.state.mark_seen(rec.run_id)
            self._handled_any = True
        self._flush_pending()
        self._enforce_annihilation()
        try:
            self._garden.enforce()
            self._weeklyboss.enforce()
        except Exception:  # noqa: BLE001 - 一道省时间的门，不许拖垮主流程
            log.warning("周常乐园开关没能落盘，下轮再试", exc_info=True)
        self._check_missed_runs()
        self._maybe_interim_report()
        self._maybe_daily_report()
        self._maybe_shutdown()
        return len(records)

    # ---------- per record ----------

    def _archive_maaend_evidence(self, rec: RunRecord) -> None:
        """把这一轮的 on_error 截图和 debug 日志抢救到中继自己的目录。

        存到 state/evidence/<run_id>/，绝不能挡住记账，所以整段包 try。
        """
        try:
            if not self.cfg.maaend_dir:
                log.error("❌ 存不了 MaaEnd 失败证据：maaend_dir 没解析出来"
                          "（ARK_MAAEND_DIR 未设，且 AUTO-MAS 里也没查到）。"
                          "MaaEnd 下次启动就会清空 debug 目录，证据即将丢失")
                return
            src = Path(self.cfg.maaend_dir) / "debug"
            if not src.is_dir():
                log.error("❌ 存不了 MaaEnd 失败证据：%s 不是目录", src)
                return
            dst = Path(self.cfg.state_dir) / "evidence" / rec.run_id.replace("/", "_")
            dst.mkdir(parents=True, exist_ok=True)
            import shutil  # noqa: PLC0415
            n = 0
            oe = src / "on_error"
            if oe.is_dir():
                for png in sorted(oe.glob("*.png"))[:20]:
                    shutil.copy2(png, dst / png.name)
                    n += 1
            logs = sorted(src.glob("*.log"), key=lambda f: f.stat().st_mtime)
            for f in logs[-2:]:
                shutil.copy2(f, dst / f.name)
                n += 1
            log.info("📦 MaaEnd 失败证据已存档 %d 个文件 → %s", n, dst)
        except Exception:  # noqa: BLE001 - 存档失败不许影响记账
            log.exception("MaaEnd 证据存档失败（不影响记账）")

    def _verify_outcome(self, rec: RunRecord) -> str | None:
        """按证据核对这一轮到底干成了什么；全干成返回 None。

        判据在 `outcome.py`，样本取自真实日志。这里只负责把日志文本
        和「本来该干什么」凑齐——**核对失败绝不能挡住记账**，
        所以整段包在 try 里：核对本身出错只写日志，不改变原有行为。
        """
        try:
            text = ""
            if rec.log_path and rec.log_path.exists():
                text = rec.log_path.read_text(encoding="utf-8", errors="replace")
            if not text:
                return None                     # 没日志就没法核对，别瞎报
            if rec.script == "OK-WW":
                expect_nest = _okww_nest_expected(self.cfg.automas_dir)
                if expect_nest is None:
                    # 读不到配置就说读不到，不许悄悄把残象聚落那一项去掉。
                    checks = outcome.okww_checks(text, expect_nest=False)
                    checks.append(outcome.Check(
                        "能读到 OK-WW 生效中的配置", False,
                        f"{self.cfg.automas_dir}/data/*/Default/ConfigFile/ "
                        "下没读到 NightmareNestTask.json 和 DailyTask.json，"
                        "所以这一轮该不该打残象聚落无从判断"))
                else:
                    checks = outcome.okww_checks(text, expect_nest=expect_nest)
                return outcome.summarize(checks, "OK-WW")
            if rec.script == "MAA":
                # 只看 MAA 自己的日志：AUTO-MAS 的 history 里没有子任务成败。
                # 结束时刻只在它可信时才当上界用（见 RunRecord.duration_known）。
                # 留 5 分钟余量：MAA 收尾那几行可能落在 AUTO-MAS 记完之后。
                until = (rec.finished + timedelta(minutes=5)
                         if rec.duration_known else None)
                maa_log = _maa_app_log(self.cfg.maa_dir, rec.started, until)
                if maa_log is None:
                    # 空文本喂给 maa_checks 会全部判过 = 又一次假全绿。
                    return outcome.summarize([outcome.Check(
                        "能读到 MAA 自己的日志", False,
                        f"maa_dir={self.cfg.maa_dir}，"
                        "asst.log 里没有这一轮时间窗内的行，基建成败无从核对")],
                        "MAA")
                return outcome.summarize(outcome.maa_checks(maa_log), "MAA")
            if rec.script == "MaaEnd":
                shots = _maaend_new_shots(self.cfg.maaend_dir, rec.started)
                # AUTO-MAS 的 history 日志 + MaaEnd 自己的 app 日志一起看：
                # 收尾标记只在后者里，任务开始/完成只在前者里，缺一条就误判。
                both = text + "\n" + _maaend_app_log(self.cfg.maaend_dir, rec.started)
                return outcome.summarize(
                    outcome.maaend_checks(both, shots), "MaaEnd")
        except Exception as exc:  # noqa: BLE001 - 核对出错不许影响记账
            log.exception("结果核对本身出错")
            # 原来这里直接 return None，也就是「全干成」。核对崩了却报全绿，
            # 是这一类 bug 里最坏的一种：出问题的时候恰恰最不该说没问题。
            # 记账照旧不受影响（本函数只决定要不要额外报一句）。
            return (f"{rec.script} 这一轮的结果核对没跑成（{type(exc).__name__}: "
                    f"{exc}），所以「干成了没有」这次没人验过。")
        return None

    def _handle(self, rec: RunRecord) -> None:
        # mark_seen only happens after _handle returns, so a crash later in
        # this method (disk full during save_pending, annihilation copy2)
        # replays the record on every retry tick - and each replay used to
        # append the same run to the ledger again, inflating the daily report
        # and the "重试 N 次" counts. The ledger append itself must be
        # idempotent.
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        if any(e.get("run_id") == rec.run_id for e in self.state.read_ledger(day)):
            log.info("记录 %s 已在账上（上次处理中途出错的重试），跳过重记", rec.run_id)
        else:
            self.state.append_ledger(rec)
        key = (rec.script, rec.user)

        if rec.ok:
            # A later success means AUTO-MAS got past it on its own. Report it
            # anyway - once for the whole event, not once per failed attempt.
            if (bad := self._pending.pop(key, None)) is not None:
                self._recovered[key] = bad
                self._persist_pending()
                log.info("↩️ %s 重试后成功，改为自愈通知", rec.script)
            # Only a pass that actually reached the weekly cap counts. MAA
            # reports Success! even when it stops early for want of sanity, and
            # closing 剿灭 on that would skip the rest of the week with the cap
            # unmet - the run on 2026-08-17 needed five sorties and 125 sanity
            # to get from 0 to 1800.
            steps = rec.raw.get("okww_steps") or []
            # 周本：任务名译作「传送并刷取4C声骸」，任务本身显示「刷4C(大世界/副本)」，
            # 两种都认。判据和周常乐园一致——只有真跑完那一步才算数。
            if any(("4C声骸" in s or "刷4C" in s) and "已完成" in s for s in steps):
                if msg := self._weeklyboss.on_success(rec.finished):
                    self.notifier.send("⚔️ 鸣潮周本", msg)
            if any("周常乐园" in s and "已完成" in s for s in steps) and self._garden:
                if msg := self._garden.on_success(rec.finished):
                    # 2026-08-26：这里原本写的是 `notes.append(msg)`，可这个作用域里
                    # 根本没有 notes——一路 NameError 把整个 _handle 打断，那条
                    # OK-WW 记录当场「处理运行记录失败」。照 🗓️ 剿灭 那支写，
                    # 两条周门本来就该是一个形状。
                    self.notifier.send("🌳 周常乐园", msg)
            if (rec.raw.get("annihilation") and rec.raw.get("annihilation_done")
                    and self._annihilation):
                if msg := self._annihilation.on_success(rec.finished):
                    self.notifier.send("🗓️ 剿灭", msg)
            # AUTO-MAS 说「这个脚本正常退出了」，不等于它把活干成了。
            # 2026-08-27：OK-WW 连着三轮没打残象聚落、MaaEnd 卡在弹窗上
            # 把失败当做完自己关掉——两边一个 ERROR 都没报，而这里照样
            # 记 ✅、照样静默。用户的原话是「他不报错，他直接把自己关掉了」。
            # 所以退出之前先按证据核对一遍，没干成的必须出声。
            if msg := self._verify_outcome(rec):
                log.warning("⚠️ %s %s 有项目没干成：\n%s",
                            rec.script, rec.run_id, msg)
                self.notifier.send("⚠️ 这一轮没干完", msg, alert=True)
                return
            log.info("✅ %s %s（%d 分钟）静默记账",
                     rec.script, rec.run_id, rec.duration_min)
            return

        # "被下一轮取代"不是失败，不进待推队列。AUTO-MAS 把「游戏更新成功，
        # 即将重启任务」和真故障一起放进 _OKWW_BUILTIN_FATAL，于是鸣潮客户端
        # 每更新一次就报一次假失败（2026-08-28 用户点名要修的那条）。
        if rec.transitional:
            log.info("↪️ %s %s 是中途重启（%s），不算失败",
                     rec.script, rec.run_id,
                     str(rec.raw.get("general_result")
                         or rec.raw.get("maa_result")
                         or rec.raw.get("maaend_result") or "").strip())
            return

        # Hold it. Only alert once the script has stopped retrying entirely.
        self._pending[key] = rec
        self._persist_pending()   # queued to disk before anything else can go wrong
        # MaaEnd 启动时会「Auto-cleared log files and debug artifacts」——
        # 上一轮的 on_error 截图和日志在**下一次启动的瞬间**就被它自己删光。
        # 2026-08-27 早上卡弹窗那三张截图就是这么没的：中午一重试，证据全无，
        # 事后只能凭当时抄下的文件名说话。所以失败一落账就立刻把证据搬走。
        if rec.script == "MaaEnd":
            self._archive_maaend_evidence(rec)
        log.info("⏳ %s 失败，暂不推送，等重试结果", rec.script)

    # ---------- a run that should have happened and did not ----------

    def _check_missed_runs(self, now: datetime | None = None,
                           grace_min: int = MISSED_GRACE_MIN) -> None:
        """Alert when a scheduled queue produced nothing.

        "Did not run" is as much a fault as "ran and failed", and it is the
        one the operator is least likely to notice on their own - silence
        looks exactly like everything being fine.

        Only covers windows while the relay itself is up. A machine that never
        powered on cannot be caught from inside it; that is the GitHub Actions
        watchdog's job (scripts/watchdog.py, reading Tailscale lastSeen).
        """
        # Debug mode: the operator is deliberately making the machine do
        # nothing; "it produced nothing" is the plan, not a fault.
        if modes.debug_active(self.state.dir):
            return
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        entries = self._recent_entries(now)
        for q in plan.schedule(self.cfg.automas_dir):
            for hhmm in q.get("times", []):
                try:
                    hh, mm = (int(x) for x in hhmm.split(":"))
                except ValueError:
                    continue
                due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if now < due + timedelta(minutes=grace_min):
                    continue  # not late yet
                key = f"{day}/{q['name']}/{hhmm}"
                if key in self._missed_alerted:
                    continue
                # Anything recorded after the scheduled time counts as "it ran".
                ran = any(datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                          >= due - timedelta(minutes=5) for e in entries)
                if ran:
                    self._missed_alerted.add(key)   # settled, stop checking
                    continue
                # Was this machine even awake when the queue was due? If it
                # was off, "nothing ran" is not something this relay can
                # observe from the inside, and claiming it would be a false
                # alarm every single morning - that is the GitHub Actions
                # watchdog's job instead.
                #
                # Uptime, not the relay's own start time. Those differ every
                # time the relay restarts itself for a selfupdate, and an
                # update that runs long enough to cross the queue's time used
                # to make the new process disqualify itself - swallowing a
                # genuine missed run on precisely the boot where something had
                # already gone slowly enough to be worth knowing about.
                watching_since = self._boot_time(now) or self._started_at
                if watching_since > due:
                    self._missed_alerted.add(key)
                    continue
                late = int((now - due).total_seconds() // 60)
                title, body = core.format_missing(
                    f"{q['name']} 没有运行", due,
                    f"已经晚了 {late} 分钟，今天没有任何该时段的运行记录。\n"
                    "可能原因：AUTO-MAS 没启动、定时没触发、模拟器或游戏起不来。")
                if not self.notifier.send(title, body, alert=True):
                    self._missed_alerted.add(key)
                    log.warning("🔌 %s 该跑没跑，已告警", q["name"])
        self._check_partial_queues(now, day, entries)

    def _check_partial_queues(self, now: datetime, day: str,
                              entries: list[dict]) -> None:
        """Alert when a queue ran but one of its scripts never did.

        The check above only asks "did this queue produce anything", and on
        2026-08-16 that was not enough: MAA ran, so the queue counted as having
        run, while 终末地 never started at all and nobody was told. A queue that
        delivers half of what it promised is a fault, and it is invisible from
        the outside - the day looks green.

        Two things make this safe to alert on:

        Grace is generous. The morning queue runs MAA (~20 min) and only then
        MaaEnd (~25 min), so MaaEnd's record can legitimately be 45+ minutes
        late. Alerting at the same 25-minute mark as "nothing ran" would fire
        on every single healthy morning.

        Records are matched to their own queue by start time, so the morning's
        MaaEnd can never be mistaken for the evening's.
        """
        for q in plan.recent_due_queues(self.cfg.automas_dir, now,
                                        window_minutes=self.cfg.partial_window):
            due = q["due"]
            if now < due + timedelta(minutes=self.cfg.partial_grace):
                continue  # still legitimately in progress
            ran = {e["script"] for e in entries
                   if datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                   >= due - timedelta(minutes=5)}
            if not ran:
                continue  # nothing at all - already covered by the check above
            for kind in q["kinds"]:
                if kind in ran:
                    continue
                key = f"{day}/{q['name']}/{due:%H:%M}/{kind}"
                if key in self._missed_alerted:
                    continue
                # Was the machine awake when this queue was due? Same test,
                # and the same reason, as in _check_missed_runs: uptime rather
                # than the relay's start time, so a selfupdate restart cannot
                # make the relay disqualify itself from reporting a script that
                # never started.
                watching_since = self._boot_time(now) or self._started_at
                if watching_since > due:
                    self._missed_alerted.add(key)
                    continue
                late = int((now - due).total_seconds() // 60)
                title, body = core.format_missing(
                    f"{kind} 没有运行（{q['name']}）", due,
                    f"这一轮跑了 {'、'.join(sorted(ran))}，但 {kind} 一次记录都没有，"
                    f"已经晚了 {late} 分钟。\n"
                    "队列本身是跑了的，所以不是没开机——是这一项自己没起来。")
                if not self.notifier.send(title, body, alert=True):
                    self._missed_alerted.add(key)
                    log.warning("🔌 %s 缺项：%s 没跑，已告警", q["name"], kind)

    # ---------- decide held-back failures ----------

    def scripts_running(self) -> bool:
        """Public view of the same check the shutdown path uses.

        The service needs it to decide when a config edit is safe: AUTO-MAS
        reads its config as it launches each script, so writing during a run
        would land somewhere between two scripts and take effect for only half
        the queue.
        """
        return self._scripts_running()

    @staticmethod
    def _scripts_running() -> bool:
        """True while any managed script is still working.

        A failure is only worth reporting once nothing is still trying. This is
        deliberately a process check rather than a timer: a retry run can take
        20+ minutes, so any fixed grace period would either fire early or delay
        real alerts past usefulness.
        """
        if os.name != "nt":
            return False
        try:
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                                 capture_output=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return True  # cannot tell -> wait rather than cry wolf
        # Endfield.exe is on this list because MaaEnd has NO process of its
        # own - AUTO-MAS's python drives it in-process (verified 2026-08-20:
        # during a MaaEnd run tasklist shows only the game). Watching for
        # "MaaEnd.exe" alone made this check blind through the entire 终末地
        # phase; the game binary is the only visible sign that phase is live.
        return any(n in out for n in (b"MAA.exe", b"MaaEnd.exe", b"Endfield.exe"))

    def _flush_pending(self) -> None:
        if not (self._pending or self._recovered) or self._scripts_running():
            return

        for rec in list(self._recovered.values()):
            day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
            attempts = sum(1 for e in self.state.read_ledger(day)
                           if e["script"] == rec.script and e["user"] == rec.user)
            _, body = core.format_failure(rec)
            # Self-healed is not the same as fine: the fault happened and will
            # happen again. Report it as an unresolved problem that this run
            # got past, never as "nothing to do".
            body = (f"第 1 次失败，第 {attempts} 次才成功。"
                    f"这次自己缓过来了，但问题依然存在。\n") + body
            if self.notifier.send(f"⚠️ {rec.script} 出错（本次自愈，问题未解决）",
                                  body, alert=True):
                return  # keep it on disk; retry next tick
            self._recovered.pop((rec.script, rec.user), None)
            self._persist_pending()   # only now is it safe to forget
            log.info("⚠️ %s 自愈通知已推送", rec.script)

        for rec in list(self._pending.values()):
            day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
            attempts = sum(1 for e in self.state.read_ledger(day)
                           if e["script"] == rec.script and e["user"] == rec.user)
            tail = self.log_tails.pop(rec.run_id, "") or collector.log_tail(rec)
            diagnosis = summary.diagnose(self.cfg, rec.script, rec.failed_tasks, tail)
            title, body = core.format_failure(rec, diagnosis)
            body = (f"重试 {attempts} 次全部失败，需要处理。\n" if attempts > 1
                    else "需要处理。\n") + body
            errors = self.notifier.send(title, body, alert=True)
            if errors:
                log.error("告警推送出错，保留待重发: %s", "；".join(errors))
                return  # still on disk, retry next tick
            self._pending.pop((rec.script, rec.user), None)
            self._persist_pending()   # only now is it safe to forget
            log.info("❌ %s 最终失败，告警已推送（尝试 %d 次）", rec.script, attempts)

    # ---------- daily wrap-up ----------

    def next_deadline(self, now: datetime | None = None) -> tuple[datetime, str] | None:
        """The next moment any purely time-based decision can change.

        Everything event-driven already wakes the loop by itself - a record
        landing on disk, the backend dying, the service being stopped. What
        remains is clock work, and each piece of it has an exact next moment:

          - a queue that produced nothing becomes reportable at due+grace
          - the daily report becomes due at the cutoff
          - a wake-up checkpoint is asked once, shortly past its time

        So the loop can sleep until the earliest of these instead of waking
        every few minutes to ask the clock whether anything is due yet. The
        opposite of polling is not "wait longer" - it is knowing exactly which
        moment you are waiting for.
        """
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        if self._shutdown_issued:
            return None
        cands: list[tuple[datetime, str]] = []

        def today_and_tomorrow(hh: int, mm: int):
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            return due, due + timedelta(days=1)

        for q in plan.schedule(self.cfg.automas_dir):
            for hhmm in q.get("times", []):
                try:
                    hh, mm = (int(x) for x in hhmm.split(":"))
                except ValueError:
                    continue
                for due in today_and_tomorrow(hh, mm):
                    key = f"{due:%Y-%m-%d}/{q['name']}/{hhmm}"
                    moment = due + timedelta(minutes=MISSED_GRACE_MIN)
                    if moment > now and key not in self._missed_alerted:
                        cands.append((moment, f"核对队列「{q['name']}」{hhmm} 是否漏跑"))

        if not self.state.report_sent(now.strftime("%Y-%m-%d")):
            cutoff = self._report_cutoff(now)
            if cutoff > now:
                cands.append((cutoff, "日报截止"))

        for raw in self.cfg.check_times.split(","):
            raw = raw.strip()
            try:
                hh, mm = (int(x) for x in raw.split(":"))
            except ValueError:
                continue
            for due in today_and_tomorrow(hh, mm):
                moment = due + timedelta(minutes=CHECK_OPEN_MIN)
                if moment > now:
                    cands.append((moment, f"检查点 {raw}"))

        return min(cands) if cands else None

    def _report_cutoff(self, now: datetime) -> datetime:
        """The time of day after which the report is due.

        Taken from AUTO-MAS's own last scheduled queue time whenever that can
        be read, so moving a queue inside AUTO-MAS moves the report with it.
        ARK_LAST_RUN_AFTER is only the fallback.

        Both this method's callers used to compute the cutoff themselves, from
        two different starting points - one of them from the *finish time of
        the last run* rather than from the clock. That made the report
        undeliverable whenever the evening queue finished earlier than the
        configured hour: the condition could never become true, so the report
        was never sent, and because shutdown waits for the report, the machine
        never powered off either.
        """
        times = sorted(t for q in plan.schedule(self.cfg.automas_dir)
                       for t in q.get("times", []))
        hhmm = times[-1] if times else self.cfg.last_run_after
        try:
            hh, mm = (int(x) for x in hhmm.split(":"))
        except ValueError:
            hh, mm = 21, 30
        return now.replace(hour=hh, minute=mm, second=0, microsecond=0)

    def _idle_checkpoint(self, now: datetime | None = None) -> bool:
        """True when a wake-up time has passed with nothing scheduled for it.

        The machine is woken at fixed times - 09:00 and 21:30 here - and each
        wake exists to serve the queues at that time. So the morning check asks
        only about 09:00 and the evening check only about 21:30. With 明日方舟
        paused there is no 21:30 queue any more, but the wake still fires; that
        boot has no purpose and should end.

        Two earlier attempts got this wrong and are worth remembering. Keying
        off "up for 25 minutes with every queue time past" would also have
        powered off a machine booted at three in the afternoon to work on. And
        vetoing on an open SSH or ToDesk session was worse than useless: both
        start automatically at boot, so the veto always held and the feature
        never fired at all.
        """
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        if self._handled_any:
            return False
        scheduled: set[str] = {t for q in plan.schedule(self.cfg.automas_dir)
                               for t in q.get("times", [])}
        for raw in self.cfg.check_times.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                hh, mm = (int(x) for x in raw.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            # A checkpoint is a moment, not a state. The window opens two
            # minutes after the time - long enough for a queue that starts a
            # little late - and closes five minutes later. Without the closing
            # edge the condition stayed true all evening, so 21:33 and 22:00
            # were still "checking 21:30", and a machine someone had been
            # working on since the afternoon would be powered off the moment
            # the loop next ran.
            if not (due + timedelta(minutes=CHECK_OPEN_MIN)
                    <= now <= due + timedelta(minutes=CHECK_CLOSE_MIN)):
                continue
            if due < self._started_at:
                continue        # this boot was not up for that checkpoint
            if raw in scheduled:
                return False        # this wake has work; the normal path decides
            log.info("%s 这个时间点没有任何排期，本次开机无事可做", raw)
            return True
        return False

    def _boot_time(self, now: datetime | None = None) -> datetime | None:
        """When this machine last booted, or None when it cannot be told.

        Uptime, not the relay's own start time. The relay restarts itself for
        every selfupdate, so `self._started_at` moves - and an update that ran
        past a queue's time made the new process disqualify itself from
        reporting the missed run, on precisely the boot where something had
        already gone slowly enough to be worth knowing about.

        `GetTickCount64` is milliseconds since boot and never needs a clock
        that agrees with anything. It is Windows-only; anywhere else this
        returns None and the callers fall back to their own start time, which
        is the conservative direction - a missed-run alarm that is skipped
        beats one invented out of a wrong boot time.

        This method was referenced from three places since 2026-08-21 and never
        actually written. It raised AttributeError inside `_check_missed_runs`,
        which the service loop caught and logged, so the relay stayed up while
        silently doing none of the work that follows: no missed-run alarms, no
        daily report, no power-off. See PITFALLS.
        """
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        try:
            import ctypes  # noqa: PLC0415 - Windows only, imported where used
            ms = ctypes.windll.kernel32.GetTickCount64()
        except (AttributeError, OSError):
            return None
        if not ms or ms < 0:
            return None
        return now - timedelta(milliseconds=int(ms))

    def _recent_entries(self, now: datetime) -> list[dict]:
        """Today's ledger plus yesterday's, for queue-completion checks.

        The ledger is keyed by each run's *start* date, so an evening queue
        checked just after midnight has its records in yesterday's file; a
        today-only read makes a finished queue look like it never ran.
        """
        return (self.state.read_ledger(now.strftime("%Y-%m-%d"))
                + self.state.read_ledger((now - timedelta(days=1)).strftime("%Y-%m-%d")))

    def _unfinished_queues(self, now: datetime, entries: list[dict]) -> list[str]:
        """Queues that came due recently and are still missing one of their scripts.

        "No game process" is not the same as "the queue is finished". Between
        two scripts in one queue there is a window - MAA has exited, MaaEnd's
        game is still launching - where neither process exists, and the same
        window exists at the very start before the first game comes up. Acting
        in it costs a run: it cost 终末地 the morning of 2026-08-16.
        """
        out: list[str] = []
        for q in plan.recent_due_queues(self.cfg.automas_dir, now):
            # Only runs started at or after this queue's own time count -
            # otherwise the morning's MaaEnd would satisfy the evening queue.
            ran = {e["script"] for e in entries
                   if datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                   >= q["due"] - timedelta(minutes=5)}
            if missing := [k for k in q["kinds"] if k not in ran]:
                out.append(f"队列「{q['name']}」还差 {'、'.join(missing)}")
        return out

    def _work_is_done(self, now: datetime, entries: list[dict]) -> bool:
        """True when this boot's queue has come due and produced all its records.

        The durable version of `_handled_any`, which only knows what *this
        process* watched land. A relay restart after the last run - a
        selfupdate is exactly that - cleared the flag, so nothing was left to
        trigger the shutdown and the machine stayed awake all night. It cost
        2026-08-20 a manual power-off.

        Two requirements, and dropping either one costs a run:

        A queue must actually have come due. "Nothing is unfinished" is
        vacuously true at 08:50 with the 09:00 queue still ahead, and acting on
        it would power the machine off minutes before its own run.

        And the machine must have booted *before* that queue was due - this
        boot has to be the one the queue was scheduled for. Without that test
        the rule reaches a machine somebody powered on at 10:35 to work on: the
        09:00 queue is still inside its two-hour window and its records are
        already in the ledger from the morning, so "everything is finished"
        reads true and the machine switches off under them ten minutes later.
        Uptime is what distinguishes the two, not the relay's start time, which
        every selfupdate resets.

        Residual, deliberately not widened: `recent_due_queues` forgets a queue
        two hours after it was due, so a restart later than that still leaves
        no one to shut down. Widening the window here would also widen the
        "wait for a script that never ran" hold that shares it.
        """
        due = plan.recent_due_queues(self.cfg.automas_dir, now)
        if not due:
            return False
        booted = self._boot_time(now)
        if booted is None:
            return False        # cannot prove this boot belongs to the queue
        if booted > min(q["due"] for q in due):
            return False        # somebody powered this on after the queue ran
        return not self._unfinished_queues(now, entries)

    def _enforce_annihilation(self) -> None:
        """Once this week's annihilation (剿灭) is done, make sure the switch
        is off - but only write while no script is running.

        AUTO-MAS overwrites ScriptConfig while it runs, so a write made then
        is a write thrown away (see the note on annihilation.enforce).
        """
        if self._scripts_running():
            return
        try:
            self._annihilation.enforce()
        except Exception:  # noqa: BLE001 - a failed fix must not break the tick
            log.exception("剿灭开关校正出错")

    def _round_is_manual(self, new_entries: list[dict]) -> bool:
        """Whether this round was triggered by hand rather than by the schedule.

        Manual rounds have to be labelled separately (operator order,
        2026-08-20): a scheduled round and a hand-triggered make-up run must
        be distinguishable at a glance, or the operator cannot judge whether
        a given message was supposed to appear at all.

        The test looks only at how far this round's earliest record sits from
        a scheduled time - and the scheduled times are read straight from
        AUTO-MAS's queue config, so changing the schedule needs no matching
        change here. If no schedule can be read it returns False: better to
        leave a round unlabelled than to mislabel a scheduled one as manual.
        """
        times = [t for q in plan.schedule(self.cfg.automas_dir)
                 for t in q.get("times", [])]
        if not times or not new_entries:
            return False
        try:
            first = min(datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                        for e in new_entries)
        except (KeyError, ValueError):
            return False
        for hhmm in times:
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = first.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if abs((first - due).total_seconds()) <= MANUAL_WINDOW_MIN * 60:
                return False
        return True

    def _last_round_manual(self, now: datetime, entries: list[dict]) -> bool:
        """True when the day's most recent round was triggered by hand.

        A manual round must not count as "the day's work is done". On
        2026-08-21 a hand-triggered MaaEnd test finished at 12:29 and the
        relay promptly powered the machine off - while the operator was in
        the middle of working on it, and hours before the evening queue.

        The round is the group of records that finished close together; two
        hours is comfortably wider than a full queue (MAA then MaaEnd) and
        far narrower than the gap between the morning and evening queues.
        """
        if not entries:
            return False
        try:
            starts = [datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                      for e in entries]
        except (KeyError, ValueError):
            return False
        newest = max(starts)
        group = [e for e, t in zip(entries, starts)
                 if newest - t <= timedelta(hours=2)]
        return self._round_is_manual(group)

    def _maybe_interim_report(self, now: datetime | None = None) -> None:
        """Report once the day's earlier queues are done, hours before the
        daily summary is due.

        This used to live inside the shutdown path, which coupled two unrelated
        things: turning shutdown off for an afternoon of maintenance also
        silently turned off the morning report, and the operator was left with
        a machine that had run and said nothing. What decides this is "the
        morning queue finished", not "I am about to power off".
        """
        if not self.cfg.interim_report:
            return
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        if self.state.report_sent(day):
            return
        if now >= self._report_cutoff(now):
            return          # the real daily report is due; let it do the talking
        entries = self.state.read_ledger(day)
        if not entries or self._scripts_running():
            return
        if self._unfinished_queues(now, entries):
            return
        # Once per finished daytime ROUND, not once per day: a make-up run
        # adds entries past the covered mark and deserves its own interim
        # (operator order 2026-08-20 - the silent afternoon rerun taught us).
        covered = self.state.interim_covered(day)
        if len(entries) <= covered:
            return
        # Judge manual-vs-scheduled from this round's new entries only; the
        # earlier rounds have each already been reported on their own.
        label = "手动执行" if self._round_is_manual(entries[covered:]) else "临时查看"
        if self.send_daily_now(mark=False, label=label):
            self.state.mark_interim_sent(day, len(entries))
            log.info("🔎 %s 已推送「%s」（覆盖 %d 条记录）", day, label, len(entries))

    def _maybe_daily_report(self, now: datetime | None = None) -> None:
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        # Yesterday first. Everything below keys off "today", so a report that
        # could not be delivered before midnight (channel outage - it has
        # happened: 60020 all day on 2026-08-20) used to be abandoned the
        # moment the date rolled: today's ledger is a different file, and no
        # code path ever looked back. The runs are still in yesterday's
        # ledger; send their report late rather than never.
        yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        if not self.state.report_sent(yday) and (
                y_entries := self.state.read_ledger(yday)):
            title, body = self._compose_daily(yday, y_entries)
            if errors := self.notifier.send(title + "（补发）", body):
                log.error("昨日日报补发失败，稍后重试: %s", "；".join(errors))
            else:
                self.state.mark_report_sent(yday)
                log.info("📋 %s 日报已补发（%d 条记录）", yday, len(y_entries))
        if self.state.report_sent(day):
            return
        entries = self.state.read_ledger(day)
        if not entries:
            return
        # Due once the clock is past the day's last queue and nothing is still
        # working - never based on when a run happened to finish.
        if now < self._report_cutoff(now) or self._scripts_running():
            return
        # The cutoff *is* the last queue's start time, so this check first comes
        # true in the seconds after that queue fires - while its game is still
        # launching and no process exists yet. With earlier runs already in the
        # ledger the report looked complete, so it went out describing only the
        # morning and marked the day done; the evening run would then never be
        # reported at all. Same guard the shutdown path already uses.
        if unfinished := self._unfinished_queues(now, self.state.read_ledger(day)):
            log.info("日报再等等：%s", "；".join(unfinished))
            return

        title, body = self._compose_daily(day, entries)
        errors = self.notifier.send(title, body)
        if errors:
            # Do not mark it sent - retry on the next tick rather than lose the day.
            log.error("日报推送失败，稍后重试: %s", "；".join(errors))
            return
        self.state.mark_report_sent(day)
        log.info("📋 %s 日报已推送（%d 条记录）", day, len(entries))

    # ---------- power off, once everything has actually been delivered ----------

    def _shutdown_key(self, now: datetime) -> str:
        """这一次「该关机了」的机会标识。

        用当天流水的条数：一趟队列跑完就会增加，所以「晚班跑完那一次」和
        「早班跑完那一次」是两个不同的机会。调试模式吃掉的是其中一次，
        不是从此不关机。
        """
        day = now.strftime("%Y-%m-%d")
        return f"{day}:{len(self.state.read_ledger(day))}"

    def _maybe_shutdown(self, now: datetime | None = None) -> bool:
        """Power the machine off after a run, but only when nothing is pending.

        Every guard here exists so a bug cannot cost a day's run:
          - the feature is off unless explicitly enabled
          - nothing ran this session -> never
          - a script is still working -> never
          - a failure alert is still queued -> never
          - it is late enough for the daily report -> wait until it is sent
          - too soon after start -> never (no boot/shutdown loop)
        """
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        if not self.cfg.shutdown_after_run:
            return False
        key = self._shutdown_key(now)
        # Debug mode outranks everything below, the idle checkpoint included:
        # a boot with nothing scheduled is exactly what debugging looks like,
        # and powering it off is exactly what the operator asked not to happen.
        #
        # 2026-08-31 改判（用户原话：「我开了调试模式是指把一次队列的中继关机
        # 指令跳过，而不是中继一直尝试关机，要不然人类没办法使用这个电脑」）：
        # 调试模式不再只是「这一次判定返回 False」——判定每 30 秒重来一次，
        # 那样等于把关机推迟到到期时刻，人一走开机器就自己关了。
        # 现在它**吃掉这一次关机机会**：记下机会标识，到期后只要没有新队列
        # 跑完（标识没变）就不补关；新队列一跑完标识就变，恢复正常关机。
        if modes.debug_active(self.state.dir):
            if modes.shutdown_skipped(self.state.dir) != key:
                modes.mark_shutdown_skipped(self.state.dir, key)
                log.info("🔧 调试模式：这一次关机已跳过（%s）；"
                         "到期后不会补关，等下一趟队列跑完再判", key)
            return False
        if modes.shutdown_skipped(self.state.dir) == key:
            # 调试模式已经吃掉这一次了。人可能正在用这台电脑。
            return False
        # `shutdown /s /t 60` only starts a countdown; the loop keeps ticking
        # through it. Without this flag the whole block ran again every poll -
        # on 2026-08-16 that sent the pre-shutdown report three times in 60
        # seconds and re-issued the shutdown twice.
        if self._shutdown_issued:
            return False
        idle = self._idle_checkpoint(now)
        entries = self._recent_entries(now)
        # `_handled_any` is the fast path for the ordinary case; `_work_is_done`
        # is what survives a restart between the last run and the shutdown.
        if not (self._handled_any or self._work_is_done(now, entries)) and not idle:
            return False
        # The uptime floor guards against a boot -> immediate-shutdown loop.
        # The idle checkpoint is exempt: it *is* a deliberate quick power-off
        # of a purposeless boot, its window is only five minutes wide, and it
        # cannot loop (the next wake is the machine's own timer, hours away).
        # Held to the floor, it was unreachable whenever the service came up
        # less than shutdown_min_uptime before the checkpoint - the 2026-08-19
        # all-night wake.
        if (not idle and (now - self._started_at).total_seconds()
                < self.cfg.shutdown_min_uptime):
            return False
        if self._scripts_running() or self._pending or self._recovered:
            return False
        # "No game process" is not the same as "the queue is finished". Between
        # two scripts in one queue there is a window - MAA has exited, MaaEnd's
        # game is still launching - where neither process exists. Powering off
        # in that window costs a whole run, so also require that every script
        # today's due queues contain has actually produced a record.
        day = now.strftime("%Y-%m-%d")
        if self._last_round_manual(now, entries):
            note = "最近一轮是手动触发的，不当作当天收工，不关机"
            if note != self._last_wait_note:
                self._last_wait_note = note
                log.info(note)
            return False
        if unfinished := self._unfinished_queues(now, entries):
            # Log only when the answer changes. Repeating the same line every
            # poll buries the lines that matter under forty identical ones.
            note = "；".join(unfinished)
            if note != self._last_wait_note:
                self._last_wait_note = note
                log.info("不关机：%s", note)
            return False
        self._last_wait_note = ""
        cutoff = self._report_cutoff(now)   # same source as the report itself
        # An empty ledger means the day had nothing scheduled at all - queues
        # disabled, or a boot with no work. There is no report to wait for and
        # _maybe_daily_report returns early without ever marking one sent, so
        # waiting here waits forever: on 2026-08-19 the evening boot sat awake
        # all night on exactly this. Only hold the machine open when the day
        # actually produced runs that still owe a report.
        if (now >= cutoff and not self.state.report_sent(day)
                and self.state.read_ledger(day)):
            log.info("到点该关机了，但日报还没发出去，继续等")
            return False
        # Never power off in silence. If the day's real report has not gone out
        # yet - which is the case after the morning queue - send an interim one
        # first, so the machine is never dark without the operator knowing what
        # it did. A timed task cannot do this job: it would have to fire in the
        # gap between "run finished" and "machine off", and that gap moves.
        # Normally already sent by _maybe_interim_report; this is the backstop
        # for the case where that failed to deliver.
        if (self.cfg.report_before_shutdown and not self.state.report_sent(day)
                and not self.state.interim_sent(day)):
            log.info("关机前补发一份当前进度")
            if self.send_daily_now(mark=False):
                self.state.mark_interim_sent(
                    day, len(self.state.read_ledger(day)))

        # 关机前最后拉一次待办：人可能刚在手机上按了「今晚别关机」。
        # 这不是轮询——只在真的要关机这一刻拉一次，一天两回。
        # 拉不到就按原计划关机：拉不到不等于有人喊停。
        if self._before_shutdown is not None:
            try:
                self._before_shutdown()
            except Exception:  # noqa: BLE001
                log.warning("关机前的待办检查失败，按原计划关机", exc_info=True)
        # 人按过开关（手机下的指令，或游戏机桌面那个 .bat）：
        # 把这一次关机吃掉，用完即失效。
        # 位置必须在这里——所有别的门都过了、马上就要真关了才算数，
        # 放在前面会被一次「其实还没到该关机的时候」白白消耗掉。
        if modes.take_skip(self.state.dir):
            modes.mark_shutdown_skipped(self.state.dir, key)
            log.info("⏸ 有人按了「这次别关机」，本次关机已跳过；"
                     "下一趟队列跑完会正常关机")
            return False
        log.info("本轮已处理完毕，60 秒后关机")
        try:
            subprocess.run(["shutdown", "/s", "/t", "60",
                            "/c", "ark-relay: run complete"], timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            log.exception("关机命令执行失败")
            return False
        self._shutdown_issued = True
        return True

    def _compose_daily(self, day: str, entries: list[dict]) -> tuple[str, str]:
        """Model writes the report from the raw records; code only decides the
        headline (green / how many failed), which must never be a guess."""
        tomorrow = plan.next_plan(self.cfg.automas_dir)
        failed = [e for e in entries if not e["ok"]]
        head = "全绿 ✅" if not failed else f"{len(failed)} 项出错 ⚠️"
        title = f"📋 {day[5:]} · {head}"
        # Event countdown rides on every report (operator order, 2026-08-20):
        # a fixed-stage config plus an event ending overnight is a silent
        # next-morning failure. Appended outside the model's text so a model
        # outage can never drop it.
        act = plan.activity_countdown(self.cfg.automas_dir)
        # 卡池倒计时同理，挂在最后（用户 2026-08-30 的要求：放在通知末尾）。
        # 三个游戏各自 try 住，一个源挂了不影响其余，全挂了就少这一段。
        try:
            bnow = datetime.now(tz=SERVER_TZ).replace(tzinfo=None)
            rows, nxt = banners.collect(bnow, skland_token=self.cfg.skland_token)
            pool = banners.render(rows, bnow, nxt)
            self._announce_banners(bnow, nxt)
        except Exception:  # noqa: BLE001
            log.warning("卡池那一段整体失败", exc_info=True)
            pool = ""
        tail = "".join(f"\n\n{x}" for x in (act, pool) if x)
        written = summary.daily_report(self.cfg, entries, tomorrow)
        if written:
            log.info("📋 日报由模型撰写（%d 条记录）", len(entries))
            return title, written + tail
        # 用户 2026-08-30 定的：模型写日报是**废除的规划**（太贵），
        # 结构化模板就是最终形态、目前够用。所以走到这里不是故障，
        # 是常态路径——原来打 WARNING 会让人以为坏了，天天在日志里留一条假伤。
        log.info("日报用结构化模板（模型撰写已废弃，这是正常路径）")
        title2, body = core.format_daily(day, entries, "", tomorrow)
        return title2, body + tail

    def _announce_banners(self, now: datetime,
                          nxt: "dict[str, tuple[datetime, str]]") -> None:
        """开服前一天在企业微信群里说一声。

        用户 2026-08-31 定的：只有「任意游戏的新卡池开放的前一天」才发群，
        其余时间他自己看 Server酱。所以走 send_group 而不是 send——
        后者 Server酱 优先且第一个成功就停，永远到不了群里。

        按「游戏+开始时刻」打标记：同一天两个游戏换池要各播一条，
        而同一期不许因为日报补发就播第二遍。
        """
        due = banners.opening_tomorrow(now, nxt)
        fresh = [d for d in due
                 if not self.state.banner_announced(f"{d[0]}-{d[1]:%Y%m%d%H%M}")]
        if not fresh:
            return
        title, body = banners.group_notice(fresh)
        if not title:
            return
        if self.notifier.send_group(title, body):
            return                      # 没送到就不打标记，下一轮再试
        for game, when, _ in fresh:
            self.state.mark_banner_announced(f"{game}-{when:%Y%m%d%H%M}")
        log.info("📣 已在群里播报明天开的卡池：%s",
                 "、".join(g for g, _, _ in fresh))

    def send_daily_now(self, mark: bool = True, label: str = "临时查看") -> bool:
        """Force today's report out (used by the `report` command and tests).

        `mark=False` sends an interim look at the day so far without consuming
        the day's report - the evening summary still goes out on schedule.
        Marking it would silently cancel that summary, which is the opposite of
        what someone asking for a mid-day check wants.

        `label` distinguishes the two non-consuming kinds: 「临时查看」for a
        scheduled daytime round, 「手动执行」for a round someone triggered by
        hand. See docs/NOTIFICATIONS.md - that distinction is required, not
        cosmetic: the operator has to be able to tell why a summary appeared.
        """
        now = datetime.now(tz=SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        entries = self.state.read_ledger(day)
        title, body = self._compose_daily(day, entries)
        if not mark:
            title = title.replace("📋", "🔎", 1) + f"（{label}）"
        errors = self.notifier.send(title, body)
        if errors:
            log.error("日报推送失败: %s", "；".join(errors))
            return False
        if mark:
            self.state.mark_report_sent(day)
        return True
