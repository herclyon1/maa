"""Every piece of copy pushed to the user, in this one module and nowhere else.

Three rules, fixed by the user on 2026-09-07 after calling this out twice:
1. **Plain language only**: the only English allowed is product names and
   「Boss」; task class names, exception names and raw log text never reach a
   notification.
2. **Nothing vague**: 「出错」「异常」「有问题」「这一步」「未知」 must not stand
   alone as a verdict - if it can be translated, write the specific thing; if it
   cannot, say so outright with 「中继还不认识，原文已记日志」.
3. **Same kind, same phrasing**: the three weeklies read alike, and so do the
   update notifications for the four programs.

`tests/test_texts_gate.py` enforces this: every notifier.send title in the code
must come from here, and every sentence here - along with the Chinese lookup
tables elsewhere - has to pass `plain()`.
"""
from __future__ import annotations

import re

# English that is allowed: product names, common in-game terms, and commands a
# person has to copy verbatim.
ALLOWED_WORDS = {
    "MAA", "MaaEnd", "OK-WW", "AUTO-MAS", "MXU", "Boss", "Annihilation", "F2",
    "PIN", "net", "stop", "start", "ark-relay", "deploy-relay.sh", "scripts/mac/deploy-relay.sh",
    "MuMu", "APK", "v",
}
# Hedges are vagueness too (the user, 2026-09-12, on 「多半是反作弊组件刷新」:
# 「不允许存在任何不清不楚的句子」). A sentence either states what was measured
# or says outright what could not be read - it never guesses.
VAGUE = ("未知错误", "这一步", "有问题", "出错",
         "多半", "可能", "大概", "大约", "应该是", "似乎", "疑似", "也许", "或许",
         "估计", "差不多", "左右", "好像", "不确定", "貌似", "大致", "约 ", "约一", "不一定")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9./\-]*")
# A link is something the reader taps or copies whole; it is not English prose.
# Neither is a file path (the user asked, 2026-09-12, for 「文件位于
# AntiCheatExpert\\pld.dat」 in the report) - anything with a separator and an
# extension, or a Windows drive.
_URL = re.compile(r"https?://\S+")
# An error code is copied whole and searched for, like a link; 0xc0000005 is a
# definite fact about a crash (2026-10-01 MaaEnd plugin), not English prose.
_HEX = re.compile(r"(?<![A-Za-z0-9])0x[0-9A-Fa-f]+(?![A-Za-z0-9])")
_PATH = re.compile(r"[A-Za-z]:\\\S+|(?<![A-Za-z0-9_/:.])[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+")


# Engineering words that mean nothing to the reader (the user, 2026-09-12, on
# 「会按刷声骸的目标打」: 「我都没看懂」). A sentence has to say what happens in
# the game or on the phone, not what the code did.
JARGON = ("落盘", "回读", "兜底", "字段", "判据", "判定点", "监听", "句柄", "进程", "线程",
          "缓存", "重放", "拉起", "收窄", "节点", "实例", "退避", "调度器", "死键", "标记文件",
          "时间窗", "任务链", "冲掉", "结构化", "白名单", "凭空造", "原子", "幂等", "接口")


def plain(text: str) -> list[str]:
    """Where one piece of copy fails to read as plain language. An empty list means it passes."""
    problems = []
    for w in _WORD.findall(_HEX.sub(" ", _PATH.sub(" ", _URL.sub(" ", text)))):
        if w not in ALLOWED_WORDS and not re.fullmatch(r"v?\d[\d.]*(?:-beta\.\d+)?", w):
            problems.append(f"英文「{w}」")
    for v in VAGUE:
        if v in text:
            problems.append(f"模糊词「{v}」")
    # Names the programs themselves use are not our jargon: 「结束进程」 is a MaaEnd task.
    scrubbed = text
    for term in _THEIR_TERMS:
        scrubbed = scrubbed.replace(term, " ")
    for j in JARGON:
        if j in scrubbed:
            problems.append(f"术语「{j}」")
    return problems


# Quoted verbatim from logs, matched but never said to a person: upstream's
# 「结束进程」, and the overlay's weekly read-back lines (outcome.WEEKLY_CLAIM_*).
_THEIR_TERMS = ("结束进程", "周本领奖：回读")


# ---------------- titles ----------------
PREUPDATE = "🆕 预更新"
GAME_UPDATE = "🆕 游戏更新"
RERUN_AFTER_UPDATE = "🔁 更新后重跑"
WEEKLY = "🗓️ 周常"                 # one title for annihilation / weekly garden / weekly boss finishing
NEW_WEEK = "🗓️ 新的一周"           # Monday boot: one line of state for each of the three
SKIP_MODE = "⏭️ 跳过模式"
ESTOP = "🛑 已停一切"
ESTOP_FAILED = "🛑 没能停干净，需要你动手"
NO_SHUTDOWN = "🌙 今晚不关机"
CONFIG_CHANGED = "📱 配置已修改"
CONFIG_FAILED = "📱 配置没改成"
SELFUPDATE_FAILED = "⚠️ 中继自更新没成功"
WATCH_LOST = "⚠️ 中继暂时不能在脚本跑完时马上处理结果"
RELAY_ERROR = "🩺 中继自己报错了"
SELFCHECK_FAILED = "🩺 开机自检没过"
AUTOMAS_DOWN = "🔌 AUTO-MAS 启动不起来"
ROUND_INCOMPLETE = "⚠️ 这一轮没干完"
MAAEND_REENABLED = "🔓 终末地日常已开回"
# The make-up (makeup.py) switched Endfield's tasks off for one run and can put
# neither the saved switches nor the full copy back: a real alarm, someone has
# to look.
MAKEUP_RESTORE_FAILED = "⚠️ 终末地设置没能自动改回"
MAAEND_PRUNED = "🧹 终末地配置清掉了死条目"
MAAEND_MIGRATED = "🧩 终末地新版本改了设置格式，已按原意换写"
COLLECT_RETRY_START = "🔁 自动采集：只补跑失败的路线"
COLLECT_RETRY_OK = "✅ 自动采集：补跑后全部走完"
COLLECT_RETRY_FAILED = "⚠️ 自动采集：补跑仍有路线没走通"
COLLECT_RECURRENT = "🚩 自动采集：有路线连续两天补跑失败，是复发性问题"
COLLECT_NARROWED = "🔁 自动采集：这一轮重跑只走没走通的路线"
EVIDENCE_SAVED = "🗂️ 证据包已送出机器"
# One line in a group alarm whose evidence bundle could not be uploaded.
EVIDENCE_NOT_SHIPPED = "证据包没传上去（原因见 relay.log）"
EVIDENCE_SOURCE_CHANGED = "🧷 上游改了导出日志的代码，证据包的打法要重新核对"
# The annihilation weekly switch (annihilation.WeeklyGate) could not be closed
# after the week's pass, or put back on Monday: pushed every time (errwatch).
ANNIHILATION_CLOSE_FAILED = "⚠️ 剿灭开关没能关上"
ANNIHILATION_REOPEN_FAILED = "⚠️ 剿灭开关没能恢复"
# Skland answered with more than one Endfield role; nothing was read (resources.py).
SKLAND_MULTI_ROLE = "⚠️ 森空岛给了不止一个终末地角色，没有读"
MAAEND_STUCK_KILLED = "⚠️ 终末地 MaaEnd 卡住，已结束它让 AUTO-MAS 接着走"
MAAEND_STUCK_KILL_FAILED = "⚠️ 终末地 MaaEnd 卡死，没能结束，需要人工看一眼"
MAAEND_WATCH_BLIND = "⚠️ 终末地看门狗读不到 MaaEnd 的运行日志"


def collect_retry_start_body(names: str) -> str:
    return f"这一趟没走通的：{names}。队列已经空了，现在只补跑这几条，别的不动。"


def collect_retry_body(passed: list[str], failed: list[str], unknown: list[str], note: str) -> str:
    lines = []
    if passed:
        lines.append("补跑走通：" + "、".join(passed))
    if failed:
        lines.append("补跑仍失败：" + "、".join(failed))
    if unknown:
        lines.append("没拿到结果：" + "、".join(unknown))
    if note:
        lines.append(note)
    return "\n".join(lines) or "没有要补跑的路线"


def collect_narrowed_body(names: list[str]) -> str:
    return ("没走通的：" + "、".join(names)
            + "。AUTO-MAS 马上重跑自动采集这一项，中继已把路线改成只有这几条；重跑一开始就改回原来的路线。")


def maaend_crash_reason(code: str) -> str:
    """The plugin wrote a crash to its stderr; `code` is the 0x... exception code, or ""."""
    what = f"（错误码 {code}）" if code else "（原文在 debug\\go-service.stderr.log）"
    return f"判定原因：MaaEnd 的插件 agent\\go-service.exe 崩溃了{what}，之后 MaaEnd 不会再往下走。"


def maaend_plugin_gone_reason(seconds: int) -> str:
    return (f"判定原因：MaaEnd 还开着，它的插件 agent\\go-service.exe 已经不在了"
            f"（隔 {seconds} 秒查了两次都不在），MaaEnd 不会再往下走。")


def maaend_no_exit_reason(done_at: str, waited_s: int) -> str:
    return (f"判定原因：MaaEnd 所有任务 {done_at} 已完成，{waited_s} 秒后仍没有自己退出"
            "（正常 4 秒内退出）。")


def maaend_stall_reason(minutes: int, last: str) -> str:
    tail = f"（最后一行 {last}）" if last else ""
    return f"判定原因：MaaEnd 的运行日志 debug\\maafw.log 已 {minutes} 分钟没有新行{tail}；正常运行时两行最多隔 65 秒。"


def maaend_watch_blind_body(minutes: int) -> str:
    return (f"MaaEnd 已经跑了 {minutes} 分钟，看门狗一行运行日志（debug\\maafw.log）都没读到。\n"
            "读不到日志说明不了 MaaEnd 卡没卡，所以这次不结束它；要人看一眼这个日志还在不在原处。")


def maaend_stuck_body(reason: str, killed: bool, why: str) -> str:
    if killed:
        return (reason + "\n已结束 MaaEnd 和它还开着的插件，游戏本身没动。"
                "AUTO-MAS 接着按 MaaEnd 的日志判这一趟：没干完的、还有重试次数就马上重跑，"
                "已经干完的直接收尾——不用再等它的时限（MaaEnd 日志 40 分钟不动才结束）。")
    return (reason + f"\n结束 MaaEnd 没成功（{why}），它还卡着，"
            "要等到 AUTO-MAS 给 MaaEnd 的时限才会被结束。")


def collect_recurrent_body(names: list[str]) -> str:
    return ("连续两天补跑都失败的：" + "、".join(names)
            + "。这不像偶发，中继不再自动重试这几条；请人工带上证据包去上游报问题。")


_SCRIPT_ZH = {"MAA": "明日方舟", "MaaEnd": "终末地", "OK-WW": "鸣潮"}


def evidence_saved_body(script: str, started: str, files: int, page: str) -> str:
    """`started` is the run's start as 「09-11 10:18」, not its run_id (that is a path)."""
    head = f"{_SCRIPT_ZH.get(script, script)} {started} 那趟：一个压缩包，里面 {files} 个文件"
    if page == "企业微信":
        return head + "\n已作为文件发到你的企业微信（上面那条就是）。"
    if page == "企业微信群":
        return head + "\n已作为文件发到企业微信群（上面那条就是）。"
    return head + f"\n下载页：{page}"


def evidence_source_changed_body(names: list[str]) -> str:
    return ("变了的：" + "、".join(names)
            + "。只盯打包那几个函数，别处改动不会触发这条；所以这是打包代码本身变了。"
            "在重新核对之前，中继打的证据包不保证和官方按钮导出的一样。")
ECHO_FARM = "🥚 开始刷声骸"
ECHO_FARM_DONE = "🥚 刷声骸收工"
TACET_DROPS = "🖼️ 无音区产出"


# A patch that could not be applied shared this title with a patch that went on
# cleanly, so the phone banner looked the same either way - and a refused nest patch
# means the machine farms every nest all night while the plan still says 「只打落渊
# 南丘」. The lines themselves already say 「贴不上了」/「写不进去」; the title has to.
_PATCH_TROUBLE = ("贴不上", "写不进", "叠了", "没能检查", "对不上")


def patches(n: int, notes: "list[str] | None" = None) -> str:
    bad = sum(1 for x in (notes or []) if any(k in x for k in _PATCH_TROUBLE))
    if bad:
        return f"⚠️ OK-WW 补丁有 {bad} 条没贴上（共 {n} 条）"
    return f"🩹 OK-WW 补丁（{n} 条）"


def unconfirmed(what: str, n: int) -> str:
    """How many items the pre-update / game update could not confirm."""
    return f"⚠️ {what}没能确认（{n} 项）"


def failed(script: str) -> str:
    return f"❌ {script} 失败"


def unresolved(game: str, shift: str) -> str:
    """A MAA / MaaEnd shift that failed and that the make-up did not fix (unresolved.py)."""
    return f"❌ {game}{shift}没跑成"


def unresolved_undone(game: str, shift: str) -> str:
    """A MAA / MaaEnd shift that ended with work left undone (unresolved.py)."""
    return f"⚠️ {game}{shift}没干完"


def unresolved_head(game: str, shift: str, makeup: str, stuck: str, page: str) -> str:
    """The alarm's first line: the game, the shift, what came of the make-up, where it
    failed and the evidence link (see samples() for the copy)."""
    head = f"{game}{shift}没跑成，{makeup}"
    if stuck:
        head += ("；" if "：" in makeup else "：") + f"卡在 {stuck}"
    if page:
        head += f"（证据包 {page}）"
    return head + "\n"


def unresolved_undone_head(game: str, shift: str, items: str, page: str) -> str:
    """The first line of a 「没干完」 alarm; no make-up is run for these."""
    head = f"{game}{shift}跑完了但没干完" + (f"：{items}" if items else "") + "，这一类不补跑"
    if page:
        head += f"（证据包 {page}）"
    return head + "\n"


def self_healed(script: str) -> str:
    # This used to read 「出错（本次自愈，问题未解决）」 - 「出错」 is one of the
    # vague words, so it now says what actually happened.
    return f"⚠️ {script} 中途失败过，重试后成功"


def cant_enter(script: str) -> str:
    return f"⏸ {script} 进不了游戏，稍后补跑"


# Appended to the final alarm when a MaaEnd round had the "never got into the
# game" shape but no official maintenance or update notice backs it
# (handle._confirm_unreachable): it is alarmed on as a fault.
UNREACHABLE_SHAPE_NOTE = ("每个任务都在 30 秒内失败、一个没完成，看着像没进游戏；"
                          "但今天没有官方维护或更新公告，所以按故障报（游戏窗口、分辨率、游戏是否闪退要看）。")


# A run a person started at AUTO-MAS itself (trigger.py): alarmed like any
# other, with this line so the reader knows whose run it was.
HAND_STARTED_NOTE = "这一趟是有人在 AUTO-MAS 上手动开的，不是定时开的。"
# A MAA failure on a day with a registered Arknights version update.
UPDATE_DAY_NOTE = "今天登记了明日方舟的版本更新。"


def annihilation_value(v: str) -> str:
    """The annihilation switch as the reader says it: 「Close」 is 关着; anything else is the map setting."""
    return {"Close": "关着", "": "读不到"}.get(str(v or ""), str(v))


def annihilation_close_failed_body(current: str, detail: str) -> str:
    """WeeklyGate.enforce: this week's pass is done but the switch could not be set to Close."""
    return (f"本周剿灭已经打满，开关该关上，但没关成。开关现在是「{annihilation_value(current)}」。{_said(detail)}\n"
            "关上之前，每一趟明日方舟都会先进一次剿灭再出来。中继每一轮都会再试着关。")


def annihilation_reopen_failed_body(restore: str, detail: str, now: "str | None" = None) -> str:
    """WeeklyGate.maybe_reopen: the new week's restore did not take - the write was
    refused (`detail`), or it went in and reads back as `now` ('' = unreadable)."""
    if now is not None:
        what = f"写进去之后再读，开关是「{annihilation_value(now)}」。"
    else:
        what = f"没写进去。{_said(detail)}"
    return (f"新的一周，剿灭开关该恢复成「{annihilation_value(restore)}」，{what}\n"
            "恢复之前这一周的剿灭不会按原来的设置打。下次开机中继再试。")


def skland_multi_role_body(roles: list) -> str:
    """resources.skland_session: Skland listed several Endfield roles for the account."""
    ids = "、".join(str(r) for r in roles) or "（没给编号）"
    return (f"森空岛这次给了 {len(roles)} 个终末地角色（角色编号 {ids}），中继不知道该读哪一个，一个都没读。\n"
            "手机页上终末地的数字这次读不出来。要人看一眼森空岛账号绑的角色。")


def missing(what: str) -> str:
    return f"🔌 {what}"


def not_run(queue: str) -> str:
    return f"{queue} 没有运行"


def not_run_in(kind: str, queue: str) -> str:
    return f"{kind} 没有运行（{queue}）"


# ---------------- bodies ----------------
def self_healed_body(attempts: int) -> str:
    return f"第 1 次失败，第 {attempts} 次才成功。这次自己缓过来了，原因还在，见下。\n"


# What to do about a failure whose cause is known (collector_maaend
# _maaend_fail_causes). Said plainly instead of asking the model to guess.
_CAUSE_ADVICE = {
    "背包满了": "背包满了，领到的奖励放不下。清出背包空间后再跑。",
    # collector_maaend.CLAIM_UNCONFIRMED: the claim click then the failure, with
    # no storage-full notice seen. Stated as what was seen, not as a full bag.
    "点了确认领取后失败，没看到仓储已满的提示":
        "点了确认领取后任务失败了，但没看到仓储已满的提示，所以没按背包满了处理，补跑也不会先清背包。"
        "背包满了时也是这个样子，请看一眼背包。",
}


def known_cause(causes: dict) -> str:
    """「基质刷取：背包满了，…」 for each failure with a known cause; "" if none."""
    return "\n".join(f"{name}：{_CAUSE_ADVICE.get(c, c)}" for name, c in (causes or {}).items())


def failed_body_head(attempts: int) -> str:
    return f"重试 {attempts} 次全部失败，需要处理。\n" if attempts > 1 else "需要处理。\n"


# An action id must never reach a push as it is: `set_config` is written for
# the program, and 「set_config」現在不能执行 answers nothing.
_ACTION_ZH = {
    "set_stage": "改关卡",
    "set_medicine": "改吃几瓶理智药",
    "set_wait_time": "改等待时间",
    "toggle_task": "开关某个任务",
    "run_now": "现在就跑一趟",
    "skip_today": "今天这趟跳过",
    "unskip_today": "取消今天的跳过",
    "debug_mode": "调试模式",
    "set_config": "改设置",
    "set_master": "改设置",
    "weekly_boss": "改打第几个周本",
    "skip_shutdown": "下次跑完不关机",
    "echo_farm": "开始刷声骸",
    "echo_farm_until": "改刷声骸的收工时刻",
    "echo_farm_stop": "刷声骸提前收工",
    "tacet_shots": "无音区结算截图",
    "monthcard": "登记月卡",
    "estop": "停止一切",
}


def action_name(action: str) -> str:
    return _ACTION_ZH.get(action, "这条设置")


# D207: the receipt written the moment an order is queued behind a running script.
PHONE_QUEUED = "排队中，这一趟跑完执行"


def phone_busy_reason(action: str) -> str:
    """Why an order that starts a run was not carried out while a run was going."""
    if action == "run_now":
        return "这时正在跑，这一趟就是"
    return "这时正在跑，跑完不会接着开；要的话等跑完再发一次"


def makeup_restore_failed_body(master: str, record: str) -> str:
    return ("终末地设置被临时改过，自动改回失败，需要人看一下。\n"
            f"终末地设置文件：{master}\n"
            f"临时改动前的开关记录（读不出来）：{record}\n"
            "设置改好后删掉这份记录，补跑才会再用；在那之前补跑不再改终末地的设置。")


def rerun_body(reran: list[str]) -> str:
    return "、".join(reran) + " 已单独开跑"


# Logger name -> what that part of the relay is called in a notification.
_RELAY_PARTS = {
    "ark.service": "主程序", "ark.engine": "核心", "ark.handle": "记账与告警", "ark.report": "日报",
    "ark.shutdown": "关机判定", "ark.missed": "漏跑核对", "ark.preupdate": "预更新", "ark.gameupdate": "游戏更新",
    "ark.selfupdate": "自更新", "ark.phone": "手机通道", "ark.evidence": "证据外送", "ark.collect_watch": "采集看守",
    "ark.collect_retry": "采集补跑", "ark.inbox": "待办信箱", "ark.snapshot": "状态快照", "ark.notify": "推送",
    "ark.banners": "卡池信息", "ark.desktop": "桌面读屏", "ark.alertlog": "报警抄送",
    # Every WARNING reaches the group since 2026-10-06 (errwatch), so the rest are named too.
    "ark.annihilation": "剿灭开关", "ark.garden": "周常乐园开关", "ark.weeklyboss": "周本开关",
    "ark.unresolved": "没处理好的报警", "ark.runwatch": "在跑巡查", "ark.trigger": "认手动开的趟",
    "ark.resources": "手机页的数字", "ark.skland": "森空岛", "ark.makeup": "补跑", "ark.core": "记账",
    "ark.collector": "读运行记录", "ark.selfcheck": "开机自检", "ark.maaend_watchdog": "终末地看门狗",
    "ark.commands": "执行命令", "ark.task_shots": "任务截图", "ark.statestore": "状态档案",
    "ark.monthcard": "月卡提醒", "ark.echofarm": "刷声骸", "ark.maintenance": "停服维护公告",
    "ark.okww_patch": "鸣潮补丁", "ark.okww_overlay": "鸣潮补丁", "ark.mastercfg": "脚本设置",
    "ark.maaend": "终末地设置", "ark.queues": "队列设置", "ark.modes": "跳过开关", "ark.plan": "排期",
    "ark.sanity_plan": "理智安排", "ark.summary": "文字撰写", "ark.watch": "盯运行记录目录",
    "ark.procs": "程序列表",
}


def relay_part(where: str) -> str:
    """The plain name of the part of the relay a logger name stands for."""
    return _RELAY_PARTS.get(where, "一个不常见的部分")


def selfcheck_failed_body(total: int, bad: list) -> str:
    """`bad` is [(name, detail)] of the checks that did not hold."""
    lines = "\n".join(f"· {n}" + (f"：{d}" if d else "") for n, d in bad)
    return (f"开机自检 {total} 项里有 {len(bad)} 项不成立：\n{lines}\n"
            "这些不成立的后果：这一班跑不了，或者跑了中继也看不见。请人看一眼。")


# The last line of every 「🩺 中继自己报错了」 push (errwatch.py).
RELAY_ERROR_TAIL = "这不代表脚本没跑，是中继自己有一处出了错，需要人看一眼。"


def relay_error_body(where: str, what: str, at: str = "") -> str:
    """`where` is the logger name, `what` the first line of the WARNING / ERROR record,
    `at` when it was logged (errwatch.span).

    The record's own words are quoted only when they read as plain language;
    a line full of class names or English is left in relay.log and said so -
    「翻不出就明说」 (the user, 2026-09-13), never a bare 「出错」.
    """
    part = relay_part(where)
    when = f"（{at}）" if at else ""
    return f"中继自己报错了{when}，出在「{part}」。{_said(what)}\n" + RELAY_ERROR_TAIL


def relay_error_line(where: str, what: str, at: str, fixed_in: str = "", fixed_what: str = "") -> str:
    """One record in a merged push (errwatch.merge): when, where, what it said."""
    again = ""
    if fixed_in:
        again = f"，v{fixed_in} 修过的又出现了" + (f"（当时修的是：{fixed_what}）" if fixed_what else "")
    return f"· {at}，出在「{relay_part(where)}」{again}。{_said(what)}"


def relay_errors_merged(title: str, n: int) -> str:
    """Title of one push carrying `n` records that waited together (errwatch.merge)."""
    return f"{title}（{n} 条）"


def _said(what: str) -> str:
    return f"它说：{what}" if what and not plain(what) else "原话有术语没翻译，留在中继日志里"


def relay_error_recurred(fixed_in: str) -> str:
    """Title: a fault known_fixed.py records as fixed in `fixed_in` is back (an ERROR)."""
    return f"{RELAY_ERROR}（v{fixed_in} 修过的又出现了）" if fixed_in else f"{RELAY_ERROR}（修过的又出现了）"


def relay_error_recurred_body(where: str, what: str, at: str = "", fixed_what: str = "") -> str:
    when = f"（{at}）" if at else ""
    fixed = f"当时修的是：{fixed_what}。" if fixed_what else ""
    return (f"一种已经修过的错又出现了{when}，出在「{relay_part(where)}」。{fixed}{_said(what)}\n"
            "修过的毛病又犯了，要查为什么没修住。")


def relay_faults_section(rows: list) -> str:
    """The daily report's lines on the relay's own faults of the day (errwatch.day_faults), '' when none.

    One line per kind, at most 10: where, how often, what it said (when plain),
    and whether every occurrence has reached the group yet."""
    if not rows:
        return ""
    lines = []
    for r in rows[:10]:
        n = int(r.get("count") or 1)
        tags = []
        if r.get("fixed_in"):
            tags.append(f"复发：v{r['fixed_in']} 修过的又出现了")
        pushed = int(r.get("pushed") or 0)
        if pushed >= n:
            tags.append("已报群")
        elif pushed:
            tags.append(f"已报群 {pushed} 次，还有 {n - pushed} 次在排队等着报")
        else:
            tags.append("还在排队等着报群")
        said = str(r.get("line") or "")
        said = said if said and not plain(said) else "原话有术语，见中继日志"
        lines.append(f"· {relay_part(str(r.get('where') or ''))}：{said}"
                     + (f"（{n} 次）" if n > 1 else "") + f"｜{'；'.join(tags)}")
    if len(rows) > 10:
        lines.append(f"· 另外还有 {len(rows) - 10} 种，见中继日志")
    return "中继自己记下的报错\n" + "\n".join(lines)


def watch_lost_body() -> str:
    return ("脚本跑完的结果暂时要等到下一次定时检查才处理（最长一小时），不再是一跑完就处理。"
            "中继会自己反复尝试恢复，恢复了就不用管；\n"
            "如果这条之后一直没恢复，重启中继：\nnet stop ark-relay & net start ark-relay")


def automas_down_body(tries: int) -> str:
    return f"已连续 {tries} 次启动 AUTO-MAS，都没起来，需要人工看一眼。中继会继续试，间隔每次翻倍。"


def automas_boot_down_body() -> str:
    return ("开机后 AUTO-MAS 没起来，中继拉了一次也没起来。它不起来，接下来这一班就不会跑。"
            "中继会每 3 分钟再拉一次，连拉 3 次还不行会再报一次。")


def preupdate_unconfirmed_tail() -> str:
    # Not an alarm since 10-05 (boot_stages._stage_preupdate): nobody has to act.
    return "\n\n这次没确认到有没有更新，不用管：队列照常跑，明日方舟、终末地、鸣潮开跑时自己会查；AUTO-MAS 留到下次开机再查。"


def cant_enter_body(script: str, attempts: int, maint: bool, hint: str) -> str:
    why = "官方停服维护中" if maint else "每个任务 20 秒内失败、一个没完成"
    return (f"{script} 连试 {attempts} 次都没进游戏（{why}），不是配置问题。"
            "队列跑完后中继会等开服、更新客户端、再单独补跑它。"
            + (f"\n{hint}" if hint else ""))


def missed_queue_body(late_min: int) -> str:
    return (f"已经晚了 {late_min} 分钟，今天没有任何该时段的运行记录。\n"
            "需要人工看三处：AUTO-MAS 有没有在跑、定时有没有触发、模拟器或游戏起没起来。")


def missed_item_body(ran: list[str], kind: str, late_min: int) -> str:
    return (f"这一轮跑了 {'、'.join(sorted(ran))}，但 {kind} 一次记录都没有，"
            f"已经晚了 {late_min} 分钟。\n"
            "队列本身是跑了的，所以不是没开机——是这一项自己没起来。")


def attempt_timeout(game: str, script: str) -> str:
    return f"⏱️ {game}（{script}）跑超时，AUTO-MAS 正在重试"


def attempt_timeout_body(attempt: int, of: int, began, at) -> str:
    """A timeout of a script, pushed while AUTO-MAS still retries (runwatch); every one is pushed."""
    nth = f"第 {attempt}/{of} 次" if attempt and of else "这一次"
    span = (f"{began:%H:%M} 开跑，{at:%H:%M} 被 AUTO-MAS 结束（{int((at - began).total_seconds() // 60)} 分钟）"
            if began else f"{at:%H:%M} 被 AUTO-MAS 结束")
    if attempt and of and attempt < of:
        nxt = f"它还会再试 {of - attempt} 次；全部失败才会再来一条最终失败报警。"
    elif attempt and of:
        nxt = "这已是最后一次，最终结果出来再报。"
    else:
        nxt = "最终结果出来再报。"
    return f"{nth}跑超时：{span}。\n{nxt}"


def shift_overrun(queue: str) -> str:
    return f"⏰ {queue}超时还没跑完"


def shift_overrun_body(queue: str, due, now, limit_min: int, slack_min: int,
                       states: str, last_log: str) -> str:
    """A queue still unfinished past its planned end (runwatch)."""
    from datetime import timedelta as _td  # noqa: PLC0415
    ran = int((now - due).total_seconds() // 60)
    body = (f"{queue} {due:%H:%M} 开跑，到现在 {now:%H:%M} 还没跑完，已跑 {ran} 分钟。\n"
            f"近 7 天最长 {limit_min} 分钟跑完，按 {limit_min} + {slack_min} 分钟算，"
            f"该在 {due + _td(minutes=limit_min + slack_min):%H:%M} 前结束。")
    if states:
        body += f"\n现在各脚本：{states}"
    if last_log:
        body += f"\nAUTO-MAS 最后一句：{last_log}"
    return body


# For the gate: every constant in this module, plus sample copy
def samples() -> list[str]:
    from datetime import datetime as _dt  # noqa: PLC0415
    t0, t1, t2 = _dt(2026, 10, 1, 9, 0), _dt(2026, 10, 1, 9, 18), _dt(2026, 10, 1, 11, 20)
    return [
        attempt_timeout_body(1, 3, t1, t2), attempt_timeout_body(3, 3, t1, t2),
        attempt_timeout_body(0, 0, None, t2),
        shift_overrun_body("早班", t0, _dt(2026, 10, 1, 13, 10), 220, 30,
                           "MAA 完成、OK-WW 运行、MaaEnd 等待", "正在启动游戏..."),
        UNREACHABLE_SHAPE_NOTE, PREUPDATE, GAME_UPDATE, RERUN_AFTER_UPDATE, WEEKLY, NEW_WEEK, SKIP_MODE, ESTOP,
        ESTOP_FAILED, NO_SHUTDOWN, MAAEND_PRUNED, ECHO_FARM, ECHO_FARM_DONE,
        CONFIG_CHANGED, CONFIG_FAILED, SELFUPDATE_FAILED, WATCH_LOST,
        AUTOMAS_DOWN, ROUND_INCOMPLETE, MAAEND_REENABLED, MAAEND_MIGRATED, TACET_DROPS, RELAY_ERROR,
        MAKEUP_RESTORE_FAILED, PHONE_QUEUED, phone_busy_reason("run_now"),
        unresolved("明日方舟", "早班"), unresolved_undone("终末地", "早班"),
        unresolved_head("明日方舟", "早班", "补跑也没成", "开始唤醒", "https://gofile.io/d/xxxx"),
        unresolved_head("明日方舟", "晚班", "没补跑：这一轮已经开始干活（打过关），再跑一遍会再吃一份理智药",
                        "开始唤醒", ""),
        unresolved_head("终末地", "早班", "补跑没能开跑（找不到终末地的母本）", "基质刷取（背包满了）", ""),
        unresolved_head("明日方舟", "晚班", "没补跑：补跑一天只有一次，今天的已经用过了", "", ""),
        unresolved_head("终末地", "早班", "没补跑：没等到补跑就过了零点，补跑只补当天的", "送礼", ""),
        unresolved_undone_head("明日方舟", "早班", "基建换班", "https://gofile.io/d/xxxx"),
        phone_busy_reason("echo_farm"),
        makeup_restore_failed_body(r"D:\ark\automas\data\x\Default\ConfigFile\mxu-MaaEnd.json",
                                   r"C:\ProgramData\ark-relay\state\makeup\narrow.json"),
        relay_error_body("ark.service", "ConnectionRefusedError: [WinError 10061]", "21:21"),
        relay_error_body("ark.report", "日报没发出去", "10:47"),
        relay_error_recurred("20261005151027"), relay_error_recurred(""),
        relay_error_recurred_body("ark.banners", "库街区官方资讯里没找到 3.7 版本资讯帖", "21:47",
                                  "库街区官方资讯翻得不够多页，找不到当期版本资讯帖"),
        relay_faults_section([{"where": "ark.banners", "line": "官方图转 PNG 失败，原样交给系统 OCR", "count": 3,
                               "level": "WARNING", "fixed_in": "20261005151027", "pushed": 3},
                              {"where": "ark.report", "line": "日报没发出去", "count": 1,
                               "level": "ERROR", "pushed": 1},
                              {"where": "ark.engine", "line": "处理运行记录失败", "count": 2, "level": "ERROR",
                               "pushed": 1},
                              {"where": "ark.notify", "line": "x", "count": 1, "level": "ERROR"}]),
        RELAY_ERROR_TAIL, relay_errors_merged(RELAY_ERROR, 3), *_RELAY_PARTS.values(),
        ANNIHILATION_CLOSE_FAILED, ANNIHILATION_REOPEN_FAILED, SKLAND_MULTI_ROLE, HAND_STARTED_NOTE, UPDATE_DAY_NOTE,
        annihilation_close_failed_body("Annihilation", "写入失败，已回滚"),
        annihilation_close_failed_body("Annihilation", "AUTO-MAS 后端有回应但没法改（HTTPError: 500），不改文件"),
        annihilation_reopen_failed_body("Annihilation", "写入失败，已回滚"),
        annihilation_reopen_failed_body("Annihilation", "", "Close"),
        annihilation_reopen_failed_body("Annihilation", "", ""),
        skland_multi_role_body(["1234567", "7654321"]),
        relay_error_line("ark.report", "日报没发出去", "21:21:05 起共 3 次，最后一次 21:25:10"),
        relay_error_line("ark.banners", "官方图转 PNG 失败，原样交给系统 OCR", "21:47:01", "20261005151027",
                         "游戏机缺读图组件，官方长图读不了"),
        SELFCHECK_FAILED, selfcheck_failed_body(11, [("读得到每个程序是怎么启动的（系统自带的那条路）", "读不到"), ("调度程序的开机任务计划还在", "退出码 1")]),
        COLLECT_RETRY_START, COLLECT_RETRY_OK, COLLECT_RETRY_FAILED, COLLECT_RECURRENT, COLLECT_NARROWED,
        collect_narrowed_body(["路线15：红矛叶"]),
        EVIDENCE_SAVED, EVIDENCE_SOURCE_CHANGED,
        collect_retry_start_body("路线15：红矛叶"), collect_retry_body(["路线16"], ["路线15"], [], ""),
        collect_recurrent_body(["路线15：红矛叶"]), evidence_saved_body("MaaEnd", "09-11 10:18", 3, "https://gofile.io/d/xxxx"),
        evidence_saved_body("MaaEnd", "09-11 10:18", 3, "企业微信"), evidence_saved_body("MaaEnd", "09-11 10:18", 3, "企业微信群"),
        evidence_source_changed_body(["MaaEnd 导出"]),
        patches(3), unconfirmed("预更新", 2), failed("MaaEnd"), self_healed("OK-WW"),
        cant_enter("MaaEnd"), missing(not_run("早班")), missing(not_run_in("OK-WW", "早班")),
        self_healed_body(3), failed_body_head(3),
        rerun_body(["OK-WW"]), watch_lost_body(), automas_down_body(4), automas_boot_down_body(),
        preupdate_unconfirmed_tail(), cant_enter_body("MaaEnd", 3, True, ""),
        missed_queue_body(30), missed_item_body(["MAA"], "OK-WW", 75),
        attempt_timeout("鸣潮", "OK-WW"), shift_overrun("早班"),
        MAAEND_STUCK_KILLED, MAAEND_STUCK_KILL_FAILED, MAAEND_WATCH_BLIND, maaend_watch_blind_body(10),
        maaend_stuck_body(maaend_crash_reason("0xc0000005"), True, ""),
        maaend_stuck_body(maaend_crash_reason(""), False, "退出码 128"),
        maaend_stuck_body(maaend_plugin_gone_reason(60), True, ""),
        maaend_stuck_body(maaend_no_exit_reason("16:58:22", 31), True, ""),
        maaend_stuck_body(maaend_stall_reason(10, "15:30:03"), False, "结束命令 30 秒没返回"),
    ]
