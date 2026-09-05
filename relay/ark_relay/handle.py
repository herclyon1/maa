"""记账与告警：一条运行记录落盘之后，判它、记它、存证据、决定推不推。

从 engine.py 拆出来（2026-09-06，只搬不改）。这里的每个函数第一个参数都是
Engine 实例，读它的 cfg / state / notifier / _pending。
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from . import collector, core, efstatus, outcome, summary
from .config import SERVER_TZ, RunRecord, atomic_write_text

log = logging.getLogger("ark.handle")



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


# ---------- per record ----------

def _warn_if_evidence_stale(eng, rec: RunRecord, dst: Path) -> None:
    """存下来的 debug 日志未必是失败那次的——对不上就明说，别让人被误导。

    中继是靠监视 AUTO-MAS 的 history 才知道失败的，而 AUTO-MAS 整轮跑完
    才写记录。等消息到手，MaaEnd 往往已经重试成功、启动时把 debug 清空了，
    于是存下来的是**重试成功那次**的日志。

    2026-09-05 就这么绕了一圈：证据目录名是失败那次（MaaEnd-05-27-42），
    里面的 maafw.log 却只覆盖 09:57–09:59，那是成功那次（MaaEnd-05-56-35）。
    真正定位问题靠的是同时存下来的 AUTO-MAS 那份 .json。

    run_id 形如 `<日期>/<用户>/MaaEnd-HH-MM-SS`，末段就是这一轮的开始时刻。
    """
    try:
        stamp = rec.run_id.rsplit("-", 3)[-3:]
        if len(stamp) != 3 or not all(x.isdigit() for x in stamp):
            return
        hh, mm, ss = (int(x) for x in stamp)
        started = hh * 3600 + mm * 60 + ss
        for f in dst.glob("*.log"):
            if f.name.startswith("automas-"):
                continue          # 这份按 run_id 取的，必然对得上
            mt = datetime.fromtimestamp(f.stat().st_mtime, tz=SERVER_TZ)
            ended = mt.hour * 3600 + mt.minute * 60 + mt.second
            if ended < started:
                log.warning("⚠️ 证据里的 %s 最后写于 %s，早于这一轮开始的 %s，"
                            "多半是**别的轮次**的日志，别拿它当这次失败的依据",
                            f.name, mt.strftime("%H:%M:%S"),
                            f"{hh:02d}:{mm:02d}:{ss:02d}")
    except Exception:  # noqa: BLE001 - 只是提示，坏了也不许影响存档
        log.debug("证据时间范围检查失败", exc_info=True)


def _archive_maaend_evidence(eng, rec: RunRecord) -> None:
    """把这一轮的 on_error 截图和 debug 日志抢救到中继自己的目录。

    存到 state/evidence/<run_id>/，绝不能挡住记账，所以整段包 try。
    """
    try:
        if not eng.cfg.maaend_dir:
            log.error("❌ 存不了 MaaEnd 失败证据：maaend_dir 没解析出来"
                      "（ARK_MAAEND_DIR 未设，且 AUTO-MAS 里也没查到）。"
                      "MaaEnd 下次启动就会清空 debug 目录，证据即将丢失")
            return
        src = Path(eng.cfg.maaend_dir) / "debug"
        if not src.is_dir():
            log.error("❌ 存不了 MaaEnd 失败证据：%s 不是目录", src)
            return
        dst = Path(eng.cfg.state_dir) / "evidence" / rec.run_id.replace("/", "_")
        dst.mkdir(parents=True, exist_ok=True)
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
        # AUTO-MAS 自己那一轮的 .log/.json **一定对得上这次失败**，
        # 而 MaaEnd 的 debug 日志未必——见下面那条时间范围检查。
        # 2026-09-05 就是靠 history 里的 .json 才看出失败的是「基质刷取」的。
        if eng.cfg.history_dir:
            for suffix in (".log", ".json"):
                src_f = Path(eng.cfg.history_dir) / (rec.run_id + suffix)
                if src_f.is_file():
                    shutil.copy2(src_f, dst / ("automas-" + src_f.name))
                    n += 1
        log.info("📦 MaaEnd 失败证据已存档 %d 个文件 → %s", n, dst)
        eng._warn_if_evidence_stale(rec, dst)
    except Exception:  # noqa: BLE001 - 存档失败不许影响记账
        log.exception("MaaEnd 证据存档失败（不影响记账）")
    # 根本没进游戏 = 客户端待更新的信号：登记，队列跑完后去更新再重跑
    if (rec.raw or {}).get("maaend_unreachable"):
        from . import gameupdate  # noqa: PLC0415
        gameupdate.mark_pending(eng.cfg.state_dir, "终末地", "今天 MaaEnd 进不了游戏（客户端待更新）")
    if rec.script == "OK-WW" and not rec.ok and (rec.raw or {}).get("okww_unreachable"):
        from . import gameupdate  # noqa: PLC0415
        gameupdate.mark_pending(eng.cfg.state_dir, "鸣潮", "今天 OK-WW 等不到游戏窗口（客户端待更新）")
    if not rec.ok:
        # 撞上官方停服维护的失败：标上，日报画 ⏸、不报警，队列后等开服再补跑
        from . import gameupdate  # noqa: PLC0415
        if why := gameupdate.in_maintenance(eng.cfg.state_dir, rec.script, rec.started):
            rec.raw["maintenance"] = why


def _verify_outcome(eng, rec: RunRecord) -> str | None:
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
            expect_nest = _okww_nest_expected(eng.cfg.automas_dir)
            if expect_nest is None:
                # 读不到配置就说读不到，不许悄悄把残象聚落那一项去掉。
                checks = outcome.okww_checks(text, expect_nest=False)
                checks.append(outcome.Check(
                    "能读到 OK-WW 生效中的配置", False,
                    f"{eng.cfg.automas_dir}/data/*/Default/ConfigFile/ "
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
            maa_log = _maa_app_log(eng.cfg.maa_dir, rec.started, until)
            if maa_log is None:
                # 空文本喂给 maa_checks 会全部判过 = 又一次假全绿。
                return outcome.summarize([outcome.Check(
                    "能读到 MAA 自己的日志", False,
                    f"maa_dir={eng.cfg.maa_dir}，"
                    "asst.log 里没有这一轮时间窗内的行，基建成败无从核对")],
                    "MAA")
            return outcome.summarize(outcome.maa_checks(maa_log), "MAA")
        if rec.script == "MaaEnd":
            shots = _maaend_new_shots(eng.cfg.maaend_dir, rec.started)
            # AUTO-MAS 的 history 日志 + MaaEnd 自己的 app 日志一起看：
            # 收尾标记只在后者里，任务开始/完成只在前者里，缺一条就误判。
            both = text + "\n" + _maaend_app_log(eng.cfg.maaend_dir, rec.started)
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


def _handle(eng, rec: RunRecord) -> None:
    # mark_seen only happens after _handle returns, so a crash later in
    # this method (disk full during save_pending, annihilation copy2)
    # replays the record on every retry tick - and each replay used to
    # append the same run to the ledger again, inflating the daily report
    # and the "重试 N 次" counts. The ledger append itself must be
    # idempotent.
    day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
    if any(e.get("run_id") == rec.run_id for e in eng.state.read_ledger(day)):
        log.info("记录 %s 已在账上（上次处理中途出错的重试），跳过重记", rec.run_id)
    else:
        eng.state.append_ledger(rec)
    key = (rec.script, rec.user)

    if rec.ok:
        # A later success means AUTO-MAS got past it on its own. Report it
        # anyway - once for the whole event, not once per failed attempt.
        if (bad := eng._pending.pop(key, None)) is not None:
            eng._recovered[key] = bad
            eng._persist_pending()
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
            if msg := eng._weeklyboss.on_success(rec.finished):
                eng.notifier.send("⚔️ 鸣潮周本", msg)
        if any("周常乐园" in s and "已完成" in s for s in steps) and eng._garden:
            if msg := eng._garden.on_success(rec.finished):
                # 2026-08-26：这里原本写的是 `notes.append(msg)`，可这个作用域里
                # 根本没有 notes——一路 NameError 把整个 _handle 打断，那条
                # OK-WW 记录当场「处理运行记录失败」。照 🗓️ 剿灭 那支写，
                # 两条周门本来就该是一个形状。
                eng.notifier.send("🌳 周常乐园", msg)
        if (rec.raw.get("annihilation") and rec.raw.get("annihilation_done")
                and eng._annihilation):
            if msg := eng._annihilation.on_success(rec.finished):
                eng.notifier.send("🗓️ 剿灭", msg)
        # AUTO-MAS 说「这个脚本正常退出了」，不等于它把活干成了。
        # 2026-08-27：OK-WW 连着三轮没打残象聚落、MaaEnd 卡在弹窗上
        # 把失败当做完自己关掉——两边一个 ERROR 都没报，而这里照样
        # 记 ✅、照样静默。用户的原话是「他不报错，他直接把自己关掉了」。
        # 所以退出之前先按证据核对一遍，没干成的必须出声。
        if msg := eng._verify_outcome(rec):
            log.warning("⚠️ %s %s 有项目没干成：\n%s",
                        rec.script, rec.run_id, msg)
            eng.notifier.send("⚠️ 这一轮没干完", msg, alert=True)
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

    if rec.script == "MAA" and not rec.ok and eng._maintenance_today("明日方舟"):
        # 大版本更新日：包体/资源没就绪时跑失败不是要人处理的事，晚班再试
        log.warning("🟡 更新日 MAA 没跑成，晚班再试，不拉警报")
        rec.raw["maintenance_day"] = True
        return
    if rec.script == "MaaEnd" and rec.failed_tasks and set(rec.failed_tasks) <= eng.SOFT_FAILS:
        log.warning("🟡 %s 只是 %s 没做成（上游问题），记日报不拉警报",
                    rec.script, "、".join(rec.failed_tasks))
        return
    # Hold it. Only alert once the script has stopped retrying entirely.
    eng._pending[key] = rec
    eng._persist_pending()   # queued to disk before anything else can go wrong
    # MaaEnd 启动时会「Auto-cleared log files and debug artifacts」——
    # 上一轮的 on_error 截图和日志在**下一次启动的瞬间**就被它自己删光。
    # 2026-08-27 早上卡弹窗那三张截图就是这么没的：中午一重试，证据全无，
    # 事后只能凭当时抄下的文件名说话。所以失败一落账就立刻把证据搬走。
    if rec.script == "MaaEnd":
        eng._archive_maaend_evidence(rec)
    log.info("⏳ %s 失败，暂不推送，等重试结果", rec.script)


def _maintenance_today(eng, game: str) -> bool:
    try:
        from . import gameupdate  # noqa: PLC0415
        return game in gameupdate.windows(eng.state.dir)
    except Exception:  # noqa: BLE001
        return False


# 同一件事当天只报一次。2026-09-01 群里同一个 OK-WW 失败连推三条
# （17:00 / 08:29 / 11:54），用户：「赶紧去修，报了三次了。」
# 键 = 脚本 + 失败在哪一步：同一步反复失败是同一件事，不许反复推；
# 换了一步失败就是新事，照报。当天记账在 state/alerted-<日期>.json，
# 日报仍会汇总全部失败趟数，静默的只是重复的即时推送。
def _alert_key(eng, rec) -> str:
    return f"{rec.script}|{rec.user}|{','.join(sorted(rec.failed_tasks or ['?']))}"


def _alerted_file(eng, day: str) -> Path:
    return Path(eng.state.dir) / f"alerted-{day}.json"


def _already_alerted(eng, day: str, key: str) -> bool:
    try:
        return key in json.loads(eng._alerted_file(day).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def _mark_alerted(eng, day: str, key: str) -> None:
    f = eng._alerted_file(day)
    try:
        cur = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = []
    if key not in cur:
        cur.append(key)
    atomic_write_text(f, json.dumps(cur, ensure_ascii=False))


def _flush_pending(eng) -> None:
    if not (eng._pending or eng._recovered) or eng._scripts_running():
        return

    for rec in list(eng._recovered.values()):
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        attempts = sum(1 for e in eng.state.read_ledger(day)
                       if e["script"] == rec.script and e["user"] == rec.user)
        # 鸣潮客户端更新→重启→重跑成功：这是插曲不是故障。2026-09-02 早班
        # 因此推了一条 ⚠️「本次自愈，问题未解决」，用户点名是假报警。
        if core.episode_kinds(eng.state.read_ledger(day)).get(rec.run_id) == "update":
            eng._recovered.pop((rec.script, rec.user), None)
            eng._persist_pending()
            log.info("↪️ %s 游戏更新后重跑成功，不算故障，不报警", rec.script)
            continue
        key = "自愈|" + eng._alert_key(rec)
        if eng._already_alerted(day, key):
            eng._recovered.pop((rec.script, rec.user), None)
            eng._persist_pending()
            log.info("⚠️ %s 同一步的自愈今天已报过，只记日志", rec.script)
            continue
        _, body = core.format_failure(rec)
        # Self-healed is not the same as fine: the fault happened and will
        # happen again. Report it as an unresolved problem that this run
        # got past, never as "nothing to do".
        body = (f"第 1 次失败，第 {attempts} 次才成功。"
                f"这次自己缓过来了，但问题依然存在。\n") + body
        if eng.notifier.send(f"⚠️ {rec.script} 出错（本次自愈，问题未解决）",
                              body, alert=True):
            return  # keep it on disk; retry next tick
        eng._recovered.pop((rec.script, rec.user), None)
        eng._persist_pending()   # only now is it safe to forget
        eng._mark_alerted(day, key)
        log.info("⚠️ %s 自愈通知已推送", rec.script)

    for rec in list(eng._pending.values()):
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        attempts = sum(1 for e in eng.state.read_ledger(day)
                       if e["script"] == rec.script and e["user"] == rec.user)
        # 终末地根本没进游戏（服务器维护／客户端待更新）：不是要人处理的
        # 故障。当天只发一条说明，不拉警报。用户 2026-09-02：「检测到
        # 服务器在维护时候就跳过，不报警」。
        maint = (rec.raw or {}).get("maintenance")
        if maint or (rec.script == "MaaEnd" and (rec.raw or {}).get("maaend_unreachable")):
            mkey = f"维护|{rec.script}"
            if not eng._already_alerted(day, mkey):
                hint = maint or efstatus.update_hint()
                body = (f"{rec.script} 连试 {attempts} 次都没进游戏（{'官方停服维护中' if maint else '每个任务 20 秒内失败、一个没完成'}），"
                        "不是配置问题。队列跑完后中继会等开服、更新客户端、再单独补跑它。"
                        + (f"\n{hint}" if hint else ""))
                if eng.notifier.send(f"⏸ {rec.script} 进不了游戏，稍后补跑", body):
                    return  # 发不出去就下个 tick 再来
                eng._mark_alerted(day, mkey)
            eng._pending.pop((rec.script, rec.user), None)
            eng._persist_pending()
            eng.log_tails.pop(rec.run_id, None)
            log.info("⏸ %s 进不了游戏（尝试 %d 次），按维护处理，不报警", rec.script, attempts)
            continue
        key = eng._alert_key(rec)
        if eng._already_alerted(day, key):
            eng._pending.pop((rec.script, rec.user), None)
            eng._persist_pending()
            log.info("❌ %s 又在同一步失败（今天已告警过），只记日志不再推", rec.script)
            continue
        tail = eng.log_tails.pop(rec.run_id, "") or collector.log_tail(rec)
        diagnosis = summary.diagnose(eng.cfg, rec.script, rec.failed_tasks, tail)
        title, body = core.format_failure(rec, diagnosis)
        body = (f"重试 {attempts} 次全部失败，需要处理。\n" if attempts > 1
                else "需要处理。\n") + body
        errors = eng.notifier.send(title, body, alert=True)
        if errors:
            log.error("告警推送出错，保留待重发: %s", "；".join(errors))
            return  # still on disk, retry next tick
        eng._pending.pop((rec.script, rec.user), None)
        eng._persist_pending()   # only now is it safe to forget
        eng._mark_alerted(day, key)
        log.info("❌ %s 最终失败，告警已推送（尝试 %d 次）", rec.script, attempts)
