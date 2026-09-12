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
    for w in _WORD.findall(_PATH.sub(" ", _URL.sub(" ", text))):
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


_THEIR_TERMS = ("结束进程",)


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
PHONE_DEFERRED = "📱 手机指令暂缓"
CONFIG_CHANGED = "📱 配置已修改"
CONFIG_FAILED = "📱 配置没改成"
SELFUPDATE_FAILED = "⚠️ 中继自更新没成功"
WATCH_LOST = "⚠️ 中继暂时不能在脚本跑完时马上处理结果"
AUTOMAS_DOWN = "🔌 AUTO-MAS 启动不起来"
ROUND_INCOMPLETE = "⚠️ 这一轮没干完"
MAAEND_REENABLED = "🔓 终末地日常已开回"
MAAEND_PRUNED = "🧹 终末地配置清掉了死条目"
MAAEND_MIGRATED = "🧩 终末地新版本改了设置格式，已按原意换写"
COLLECT_RETRY_START = "🔁 自动采集：只补跑失败的路线"
COLLECT_RETRY_OK = "✅ 自动采集：补跑后全部走完"
COLLECT_RETRY_FAILED = "⚠️ 自动采集：补跑仍有路线没走通"
COLLECT_RECURRENT = "🚩 自动采集：有路线连续两天补跑失败，是复发性问题"
COLLECT_NARROWED = "🔁 自动采集：这一轮重跑只走没走通的路线"
EVIDENCE_SAVED = "🗂️ 证据包已存到云端"
EVIDENCE_SOURCE_CHANGED = "🧷 上游改了导出日志的代码，证据包的打法要重新核对"


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
            + "。AUTO-MAS 马上重跑自动采集这一项，中继已把路线改成只有这几条；这一轮跑完自动改回原来的路线。")


def collect_recurrent_body(names: list[str]) -> str:
    return ("连续两天补跑都失败的：" + "、".join(names)
            + "。这不像偶发，中继不再自动重试这几条；请人工带上证据包去上游报问题。")


_SCRIPT_ZH = {"MAA": "明日方舟", "MaaEnd": "终末地", "OK-WW": "鸣潮"}


def evidence_saved_body(script: str, started: str, files: int, page: str) -> str:
    """`started` is the run's start as 「09-11 10:18」, not its run_id (that is a path)."""
    return f"{_SCRIPT_ZH.get(script, script)} {started} 那趟：{files} 个文件\n下载页：{page}"


def evidence_source_changed_body(names: list[str]) -> str:
    return ("变了的：" + "、".join(names)
            + "。在重新核对之前，中继打的证据包不保证和官方按钮导出的一样。")
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


def self_healed(script: str) -> str:
    # This used to read 「出错（本次自愈，问题未解决）」 - 「出错」 is one of the
    # vague words, so it now says what actually happened.
    return f"⚠️ {script} 中途失败过，重试后成功"


def cant_enter(script: str) -> str:
    return f"⏸ {script} 进不了游戏，稍后补跑"


def missing(what: str) -> str:
    return f"🔌 {what}"


def not_run(queue: str) -> str:
    return f"{queue} 没有运行"


def not_run_in(kind: str, queue: str) -> str:
    return f"{kind} 没有运行（{queue}）"


# ---------------- bodies ----------------
def self_healed_body(attempts: int) -> str:
    return f"第 1 次失败，第 {attempts} 次才成功。这次自己缓过来了，原因还在，见下。\n"


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
    "debug_mode": "调试模式",
    "set_config": "改设置",
    "set_master": "改设置",
    "weekly_boss": "改打第几个周本",
    "skip_shutdown": "下次跑完不关机",
}


def action_name(action: str) -> str:
    return _ACTION_ZH.get(action, "这条设置")


def phone_deferred_body(action: str) -> str:
    return (f"「{action}」现在不能执行：脚本正在运行，现在改设置会被正在跑的脚本覆盖掉。"
            "等这一趟跑完再按一次。")


def rerun_body(reran: list[str]) -> str:
    return "、".join(reran) + " 已单独开跑"


def watch_lost_body() -> str:
    return ("脚本跑完的结果暂时要等到下一次定时检查才处理（最长一小时），不再是一跑完就处理。"
            "中继会自己反复尝试恢复，恢复了就不用管；\n"
            "如果这条之后一直没恢复，重启中继：\nnet stop ark-relay & net start ark-relay")


def automas_down_body(tries: int) -> str:
    return f"已连续 {tries} 次启动 AUTO-MAS，都没起来，需要人工看一眼。中继会继续试，间隔每次翻倍。"


def preupdate_unconfirmed_tail() -> str:
    return "\n\n这不是「无需更新」——是这一轮没能确认有没有更新。在确认之前，机器跑的还是原来的版本。"


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


# For the gate: every constant in this module, plus sample copy
def samples() -> list[str]:
    return [
        PREUPDATE, GAME_UPDATE, RERUN_AFTER_UPDATE, WEEKLY, NEW_WEEK, SKIP_MODE, ESTOP,
        ESTOP_FAILED, NO_SHUTDOWN, MAAEND_PRUNED, ECHO_FARM, ECHO_FARM_DONE,
        PHONE_DEFERRED, CONFIG_CHANGED, CONFIG_FAILED, SELFUPDATE_FAILED, WATCH_LOST,
        AUTOMAS_DOWN, ROUND_INCOMPLETE, MAAEND_REENABLED, MAAEND_MIGRATED, TACET_DROPS,
        COLLECT_RETRY_START, COLLECT_RETRY_OK, COLLECT_RETRY_FAILED, COLLECT_RECURRENT, COLLECT_NARROWED,
        collect_narrowed_body(["路线15：红矛叶"]),
        EVIDENCE_SAVED, EVIDENCE_SOURCE_CHANGED,
        collect_retry_start_body("路线15：红矛叶"), collect_retry_body(["路线16"], ["路线15"], [], ""),
        collect_recurrent_body(["路线15：红矛叶"]), evidence_saved_body("MaaEnd", "09-11 10:18", 3, "https://gofile.io/d/xxxx"),
        evidence_source_changed_body(["MaaEnd 导出"]),
        patches(3), unconfirmed("预更新", 2), failed("MaaEnd"), self_healed("OK-WW"),
        cant_enter("MaaEnd"), missing(not_run("早班")), missing(not_run_in("OK-WW", "早班")),
        self_healed_body(3), failed_body_head(3), phone_deferred_body("跳过它下一趟"),
        rerun_body(["OK-WW"]), watch_lost_body(), automas_down_body(4),
        preupdate_unconfirmed_tail(), cant_enter_body("MaaEnd", 3, True, ""),
        missed_queue_body(30), missed_item_body(["MAA"], "OK-WW", 75),
    ]
