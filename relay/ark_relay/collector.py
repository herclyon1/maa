"""Read AUTO-MAS run records off disk.

AUTO-MAS writes, per run:
    history/<YYYY-MM-DD>/<username>/<HH-MM-SS>.json   result
    history/<YYYY-MM-DD>/<username>/<HH-MM-SS>.log    full log

The JSON tells us which script ran and whether it succeeded:
    MAA     -> {"maa_result": "Success!", "drop_statistics": {...}, "sanity": 1, ...}
    MaaEnd  -> {"maaend_result": "MaaEnd 部分任务执行失败: ⚔️协议空间"}

Filename = start time. File mtime = finish time.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import SERVER_TZ, RunRecord

# AUTO-MAS names history folders and files on the game's day-boundary clock,
# not the machine's: `self.curdate = datetime.now(tz=UTC4)` in its AutoProxy.
# The machine runs on UTC+8, so every filename reads four hours early. It only
# shows when a run produced no timestamped log to prefer - a login failure, for
# instance - and then the report claimed 05:17 for something that happened at
# 09:17, at an hour the machine is not even powered on.
AUTOMAS_NAME_TZ = timezone(timedelta(hours=4))

# "MaaEnd 部分任务执行失败: 🚚转交委托、⚔️协议空间"
_FAILED_LIST = re.compile(r"失败[:：]\s*(.+)$")

# "[2026-08-14 06:45:11.432] 任务开始: ..."
# MAA/MaaEnd 写 "[2026-08-25 09:37:25.186]"，OK-WW 写
# "2026-08-25 12:31:32,941 INFO ..."——没有方括号、毫秒用逗号。
# 只认前者会让 OK-WW 的每条记录都显示"时长未知"。
_LOG_TS = re.compile(r"^\[?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_MAA_SUCCESS = "Success!"

# AUTO-MAS 会把"这一轮被打断、马上重来"也写成非成功结果，于是中继照单
# 报成失败。字符串抄自 AUTO-MAS 源码，不是我编的：
#   task/Okww/AutoProxy.py:52
#       ("游戏更新成功, 游戏即将重启", "游戏更新成功，即将重启任务")
#   —— 它和「未连接游戏客户端」「流程产生错误」一起放在 _OKWW_BUILTIN_FATAL 里。
# 这类记录后面一定跟着一条真正的结果，所以既不算成功也不算失败。
_TRANSITIONAL = (
    "游戏更新成功，即将重启任务",
    "游戏更新成功, 游戏即将重启",
)


def _is_transitional(result: str) -> bool:
    r = result.strip()
    return any(t in r for t in _TRANSITIONAL)


def _split_failed(text: str) -> list[str]:
    """Pull the per-task names out of MaaEnd's failure sentence."""
    m = _FAILED_LIST.search(text)
    if not m:
        return []
    # Names are separated by the Chinese enumeration comma; strip leading emoji.
    parts = [p.strip() for p in m.group(1).split("、") if p.strip()]
    return [re.sub(r"^[^\w一-鿿]+", "", p) for p in parts]


def _log_span(log_path: Path) -> tuple[datetime, datetime] | None:
    """First and last timestamp inside a run log.

    This is the only trustworthy source for how long a script actually ran.
    The record's filename and mtime are not: the filename disagrees with the
    log by hours on this install, and the mtime is when the whole *queue*
    finished, not this one script - together they reported a 42-minute run as
    4h45m.
    """
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    stamps = [m.group(1) for ln in text.splitlines() if (m := _LOG_TS.match(ln))]
    if not stamps:
        return None
    try:
        first = datetime.strptime(stamps[0], "%Y-%m-%d %H:%M:%S")
        last = datetime.strptime(stamps[-1], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return first.replace(tzinfo=SERVER_TZ), last.replace(tzinfo=SERVER_TZ)


# MAA writes what it actually farmed into its own log, but AUTO-MAS does not
# copy any of it into the result JSON - `drop_statistics` and
# `recruit_statistics` arrive as empty dicts on every single run. The numbers
# the operator most wants ("what did tonight's sanity actually buy") are
# therefore only in the log, and only the relay can put them back.
#
#   [.. 09:04:12 ..] <2> 开始行动 1~6 次, -72理智
#   [.. 09:04:03 ..] <2> 已使用理智药 1(+1)
#   [.. 09:06:29 ..] <2> TO-5 掉落统计:
#   龙门币 : 864 (+864)
#
_STAGE_DROPS = re.compile(r"(\S+)\s*掉落统计[:：]")
# Real drops always carry the "(+N)" delta; the block's trailing
# "当前次数 : 6" (how many times the stage was run) does not. That suffix is
# the only thing separating an item from the run counter, so it is required.
_DROP_ITEM = re.compile(r"^\s*(\S[^:：]*?)\s*[:：]\s*(\d+)\s*\(\+\d+\)\s*$")
_RUN_TIMES = re.compile(r"^\s*当前次数\s*[:：]\s*(\d+)\s*$")
_SANITY_SPENT = re.compile(r"开始行动.*?-\s*(\d+)\s*理智")
# AUTO-MAS runs 剿灭 as a separate pass before the day's farming, so every queue
# produces two records. The short one farms nothing and ends on 0 sanity, which
# unlabelled reads as a run that inexplicably did nothing.
_ANNIHILATION = re.compile(r'GetFightStage: from \["Annihilation"\]')
# "剿灭模式 : 1480 / 1800" - the weekly cap and how far into it this run got.
# Whether the pass *finished* is this comparison, not whether MAA exited
# cleanly: a run that stops early for want of sanity still reports Success!,
# and treating that as done would skip the rest of the week's 剿灭 entirely.
_ANNI_PROGRESS = re.compile(r"剿灭模式\s*[:：]\s*(\d+)\s*/\s*(\d+)")
_MEDICINE = re.compile(r"已使用理智药\s*(\d+)")
# Lines inside a drop block are bare "name : count"; anything with a log
# timestamp has left the block.
_HAS_TS = re.compile(r"^\[\d{4}-\d{2}-\d{2}")


def parse_maa_log(log_path: Path) -> dict:
    """Recover stage / drops / sanity spend from a MAA log. {} when unreadable.

    Deliberately forgiving: a log line that does not match is skipped rather
    than aborting the parse. A daily report missing one item is a small loss;
    a report that fails to render because of one odd line is a large one.
    """
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    out: dict = {}
    # Per stage, because the running total below is per stage. One round can
    # farm more than one - annihilation then the daily stage, or an event
    # stage alongside a permanent one - and each keeps its own running total.
    per_stage: dict[str, dict[str, int]] = {}
    stages: list[str] = []
    spent = 0
    medicine = 0

    times = 0
    current = ""
    in_block = False
    for line in text.splitlines():
        if m := _STAGE_DROPS.search(line):
            current = m.group(1)
            stages.append(current)
            per_stage.setdefault(current, {})
            in_block = True
            continue
        if in_block:
            # The block ends at the next timestamped line.
            if _HAS_TS.match(line):
                in_block = False
            elif m := _RUN_TIMES.match(line):
                times += int(m.group(1))
                continue
            elif m := _DROP_ITEM.match(line):
                # MAA prints a RUNNING TOTAL in every drop block, not the
                # gain since the last one: farming TO-5 twice logs
                # "龙门币 : 1440 (+1440)" and then "龙门币 : 2448 (+1008)".
                # Adding those gave 3888 for a run that dropped 2448 - the
                # last block already is the answer, so overwrite, never sum.
                # (Verified against 2026-08-20's real log, where AUTO-MAS's
                # own figure agrees with the last block.)
                #
                # But the total only runs within one stage. Overwriting across
                # stages made a second stage's total erase the first one's
                # instead of adding to it - annihilation's 龙门币 vanished the
                # moment the daily stage logged its own. Hence per stage here,
                # summed across stages below.
                name, total = m.group(1), int(m.group(2))
                per_stage.setdefault(current, {})[name] = total
                continue
            elif not line.strip():
                continue
            else:
                in_block = False
        if m := _SANITY_SPENT.search(line):
            spent += int(m.group(1))
        if m := _MEDICINE.search(line):
            medicine = max(medicine, int(m.group(1)))

    drops: dict[str, int] = {}
    for stage_drops in per_stage.values():
        for name, total in stage_drops.items():
            drops[name] = drops.get(name, 0) + total
    if drops:
        out["drop_statistics"] = drops
    if stages:
        # Keep order, drop repeats: one stage farmed ten times is still one stage.
        out["stages"] = list(dict.fromkeys(stages))
    if spent:
        out["sanity_spent"] = spent
    if medicine:
        out["medicine_used"] = medicine
    if times:
        out["run_times"] = times
    if _ANNIHILATION.search(text):
        out["annihilation"] = True
        if hits := _ANNI_PROGRESS.findall(text):
            got, cap = (int(x) for x in hits[-1])   # last line = final state
            out["annihilation_progress"] = [got, cap]
            out["annihilation_done"] = got >= cap
        else:
            # No progress line at all means MAA saw the cap was already met and
            # left without fighting - which is also "done for this week".
            out["annihilation_done"] = not spent
    return out



def _full_at_sentence(current: int, cap: int, sec_per_point: int,
                      ref: datetime) -> str:
    """写成 MAA 那句话的形状，好让 core._sanity_full 原样接手。

    复用它是为了不把"本日/次日"和东京时间的换算再写第二遍——那两处一旦走样，
    报告里就会出现两种不同的时间说法。
    """
    if current >= cap:
        return ""
    when = ref + timedelta(seconds=(cap - current) * sec_per_point)
    return f"理智将在 {when.astimezone(SERVER_TZ):%Y-%m-%d %H:%M} 回满。"


def flatten_drops(raw: dict) -> dict:
    """把按关卡嵌套的掉落压平成 {物品: 数量}。

    AUTO-MAS 早先把 `drop_statistics` 留空，所以这里一直是自己解析 MAA 日志再
    填进去。本项目给 AUTO-MAS 提的 PR 让它从 v5.4.0-beta.8 起真的填了这个字段
    ——形状是按关卡嵌套的 `{"AT-4": {"龙门币": 1296, ...}}`，比这里自己解析出来
    的多一层。而合并逻辑是"raw 里没有才填"，于是嵌套那份原样进了报告，渲染成
    `产出 AT-4×{'龙门币': 1296, ...}`。2026-08-25 实测到。

    换句话说这是自己的上游改动打到自己身上：加字段时只想着 AUTO-MAS 那边，
    没回头看这边的消费代码假设了什么形状。
    """
    src = raw.get("drop_statistics")
    if not isinstance(src, dict) or not src:
        return {}
    if all(isinstance(v, dict) for v in src.values()):
        flat: dict[str, int] = {}
        for per_stage in src.values():
            for name, count in per_stage.items():
                try:
                    flat[name] = flat.get(name, 0) + int(count)
                except (TypeError, ValueError):
                    continue
        return flat
    return {}


# MaaEnd writes what it collected in a different shape from MAA - no stage, no
# drop table, just a running list of "获得 <item> ×<n>" as it works through the
# day's chores, plus one line per finished task. AUTO-MAS records none of it
# either (its result JSON is a bare "Success!"), so the same recovery applies.
#
#   任务完成: 🎁赠送干员礼物
#   获得 高级认知载体 ×3
#   获得 嵌晶玉 ×25
#
_END_GAIN = re.compile(r"获得\s+(\S.*?)\s*[×x]\s*(\d+)")
# Endfield's sanity figure. MaaEnd did not print it before; it was added after
# this project's 2026-08-15 suggestion (MaaEnd#5053) was accepted, in the form
# 「当前理智 920/360」 - note that it can go above the cap.
# Take the last occurrence = the state when the tasks ended.
_END_SANITY = re.compile(r"当前理智\s*(\d+)\s*/\s*(\d+)")
# MaaEnd also says whether it knocked off because sanity ran out, and that
# decides whether anything needs attention more directly than the number does.
_END_SANITY_OUT = re.compile(r"理智不足[，,]\s*结束任务")
# 协议空间一次结算扣多少理智。优先从日志里的读数差自己标定；只有当整份日志
# 里看不到一次下降时才用这个数（例如 2026-08-24：两条读数都是 201，扣费发生在
# 最后一次结算，之后就没有读数了）。160 是 2026-08-25 实测出来的：241 → 81。
# 关卡等级变了这个数会变，但只要那天的日志里出现过一次下降，就会用实测值覆盖。
_END_PS_COST = 160
# 理智/波片的恢复速率，用来算"几点回满"。MAA 自己会把这句话写进结果 JSON，
# 另外两个不写，所以这里自己算。
#   终末地：每 7 分 12 秒回 1 点，24 小时共 200 点（官方口径）。
#           与实测吻合：2026-08-24 收工 41 → 08-25 开跑 241，隔 24 小时正好 +200。
#   鸣潮：  每 6 分钟回 1 点，上限 240，空到满正好 24 小时。
_END_SANITY_SEC_PER_POINT = 432
_OKWW_STAMINA_CAP = 240
_OKWW_SEC_PER_POINT = 360
_END_SANITY_SPENT = re.compile(r"尝试使用理智消耗许可")
_END_SANITY_REFUSED = re.compile(r"理智不足[，,]\s*尝试不使用理智消耗许可")
_END_PS_ENTER = re.compile(r"进入协议空间成功")
_END_TASK_DONE = re.compile(r"任务完成[:：]\s*(\S.+?)\s*$")


def parse_maaend_log(log_path: Path) -> dict:
    """Recover items gained and tasks finished from a MaaEnd log. {} if unreadable."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    gains: dict[str, int] = {}
    tasks: list[str] = []
    for line in text.splitlines():
        if m := _END_GAIN.search(line):
            name = m.group(1).strip()
            gains[name] = gains.get(name, 0) + int(m.group(2))
        elif m := _END_TASK_DONE.search(line):
            # Strip the leading emoji AUTO-MAS puts on every task name; it adds
            # nothing once the names are already in a list.
            name = re.sub(r"^[^\w一-鿿]+", "", m.group(1)).strip()
            if name and name not in tasks:
                tasks.append(name)

    out: dict = {}
    if gains:
        out["drop_statistics"] = gains
    if tasks:
        out["tasks_done"] = tasks
    if runs := len(_END_PS_ENTER.findall(text)):
        out["protocol_runs"] = runs
    if hits := _END_SANITY.findall(text):
        got, cap = (int(x) for x in hits[-1])
        # 「当前理智」是在协议空间的**奖励结算界面**读的，而扣费发生在紧随其后的
        # 「确认领取奖励」。所以最后一条读数是**扣费之前**的数字：只要最后一次
        # 真的扣成了，直接报它就会高出整整一次的量。
        #
        # 单次消耗从读数差自己标定——实测 2026-08-25：241 → 81，一次 160。
        # 写死数字会在关卡等级变化时失准，而这个差值本身就是当次的真实消耗。
        readings = [int(a) for a, _ in hits]
        drops = [a - b for a, b in zip(readings, readings[1:]) if a > b]
        # 只看**最后一次**结算扣没扣：整段里扣过几次不作数。实测 2026-08-25，
        # 最后一次是 "理智不足，尝试不使用理智消耗许可"，没扣，所以 81 就是终值；
        # 若按"扣费次数 > 拒绝次数"来判断，会把 81 再减 160 变成 0。
        tail = text[text.rfind("当前理智"):]
        last_claim_spent = (_END_SANITY_SPENT.search(tail)
                            and not _END_SANITY_REFUSED.search(tail))
        if last_claim_spent:
            got = max(0, got - (max(drops) if drops else _END_PS_COST))
        # AUTO-MAS always records sanity as 0 for MaaEnd, so whatever is filled
        # in here gets used (parse_record only fills in fields that are empty
        # in raw).
        out["sanity"] = got
        out["sanity_cap"] = cap
    if _END_SANITY_OUT.search(text):
        out["sanity_exhausted"] = True
    return out


# OK-WW is the third shape. It never reads the reward screen, so there is no
# drop list to recover - it is a pure image-recognition combat script and the
# only numbers it ever knows are its own. What it *does* publish, through
# ok-script's `info_set` (which logs every call), is enough for a useful line:
# how much stamina went in, how many domain entries that bought, and where the
# daily quest ended up. Asked for on 2026-08-25 with "虽然它没有掉落物的显示，
# 但只能说够用了".
_OKWW_STAMINA = re.compile(r"info_set current_stamina (\d+)")
# 绿色那个备用值。get_stamina() 一直分开存两个字段，我们只用了一个。
_OKWW_BACKUP = re.compile(r"info_set back_up_stamina (\d+)")
# 结束时的真实余量：OK-WW 停手时自己会打这一行。
# `info_set current_stamina` 是**每轮开打前**记的，拿最后一条当「剩余」会
# 永远多算一轮——2026-08-28 实际刷到 0，报告却写「剩余波片 80/240」，
# 用户当场指出是误报。单次消耗还会在 40/80 之间自动切换，靠外部推算也不可靠，
# 所以只认它自己报的这个数。
_OKWW_STAMINA_END = re.compile(r"current stamina:\s*(\d+)\s*not enough to continue")
_OKWW_DAILY = re.compile(r"info_set current daily progress (\d+)")
_OKWW_POINTS = re.compile(r"info_set total daily points (\d+)")
# One of these is logged per domain entry, so counting them counts the runs.
_OKWW_ENTRY = re.compile(r"使用单倍体力|当前体力大于等于双倍|使用双倍")
# 残象聚落的真实进度。用户 2026-08-29：「能不能给一下残像聚落的真实刷取结果，
# xx/41 这种」。日志里每次开图鉴都会打一行 `已击败残象：N/M`，取最后一条。
# ⚠️ 这个数是 OCR 出来的，前导数字可能被吞（10/41 读成 0/41），所以只做参考、
# 不拿它下「刷没刷动」的结论——那个看 nest_cleared。
_OKWW_NEST = re.compile(r"已击败残象[：:]\s*(\d+)\s*/\s*(\d+)")
_OKWW_NEST_FULL = re.compile(r"指定点位都已打满")
_OKWW_DAILY_TARGET = 180
# 游戏内日常活跃度满值。会超出（周常乐园等还会继续加），所以报出来时
# 要带上限，否则「活跃度 110」看着像出错了。
_OKWW_POINTS_TARGET = 100

# 凝素领域刷的是第几个。OK-WW 的配置只存序号，日志也只写序号
# （`Teleport to Forgery Challenge 0`，0 起算），报告里写「凝素领域 ×3」
# 机器看得懂、人看不懂。用户 2026-08-26：「他那个凝素领域第一个机器看得懂，
# 人看不懂是什么啊」。
#
# 下面这张表是 2026-08-26 在游戏里实拍 F2 →「素材获取」→「凝素领域」列表抄的
# （瑝珑·梦州，武器类型筛选＝全部）。
#
# **它不是永久有效的**：列表顺序由游戏决定，加了武器类型筛选、
# 或者版本更新加了新副本，序号就会错位。所以查不到的序号一律退回
# 「第 N 个」，宁可少说也不要报一个错名字。
_FORGERY_NAMES = {
    0: "陨翼云渊（迅刀）",
    1: "静灭云渊（音感仪）",
    2: "裂斩云渊（长刃）",
    3: "碎蚀云渊（臂铠）",
}
_OKWW_FORGERY_INDEX = re.compile(r"info_set Teleport to Forgery Challenge (\d+)")


def _forgery_label(text: str) -> str:
    """「凝素领域」后面跟哪个副本。认不出就只说序号。"""
    hits = _OKWW_FORGERY_INDEX.findall(text)
    if not hits:
        return "凝素领域"
    idx = int(hits[-1])
    if name := _FORGERY_NAMES.get(idx):
        return f"凝素领域·{name}"
    return f"凝素领域（第 {idx + 1} 个）"


def parse_okww_log(log_path: Path) -> dict:
    """Recover stamina spend / entry count / daily progress from an OK-WW log.

    Stamina is summed from the *drops* between consecutive readings rather than
    from first-minus-last: the reserve tops the bar back up mid-run, and a
    naive subtraction reads that refill as if it had never been spent.
    """
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    out: dict = {}
    readings = [int(m.group(1)) for m in _OKWW_STAMINA.finditer(text)]
    spent = sum(a - b for a, b in zip(readings, readings[1:]) if a > b)
    if spent:
        out["okww_stamina_spent"] = spent
    entries = len(_OKWW_ENTRY.findall(text))
    if entries:
        out["okww_runs"] = entries
    if back := _OKWW_BACKUP.findall(text):
        out["okww_backup_stamina"] = int(back[-1])
    if end := _OKWW_STAMINA_END.findall(text):
        out["okww_stamina_left"] = int(end[-1])
        out["okww_stamina_left_exact"] = True
    elif readings:
        # 没抓到收尾那行时才退回开打前的读数，并标明它不是结束余量。
        out["okww_stamina_left"] = readings[-1]
        out["okww_stamina_left_exact"] = False
    if nest := _OKWW_NEST.findall(text):
        out["okww_nest"] = f"{nest[-1][0]}/{nest[-1][1]}"
    if _OKWW_NEST_FULL.search(text):
        out["okww_nest_full"] = True
    if daily := _OKWW_DAILY.findall(text):
        out["okww_daily"] = f"{max(int(x) for x in daily)}/{_OKWW_DAILY_TARGET}"
    if points := _OKWW_POINTS.findall(text):
        top = max(int(x) for x in points)
        out["okww_points"] = f"{top}/{_OKWW_POINTS_TARGET}"
        if top >= _OKWW_POINTS_TARGET:
            out["okww_points"] += "（已满）"
        # 第一次读到的活跃度就 ≥ 目标 = 这一轮开始前日常已经做完了
        # （当天的第二次运行）。这轮不刷任何东西是**正确行为**，
        # 下游的渲染和结果核对都要用这个标志，别把「无事可做」判成「没干成」。
        if int(points[0]) >= _OKWW_POINTS_TARGET:
            out["okww_daily_done_at_start"] = True
    # Why it stopped, in its own words. "used all stamina" is the good ending.
    if "used all stamina" in text:
        # 「用尽」是错的：OK-WW 的 used all stamina 意思是
        # **剩下的不够再开一局**（凝素领域单次 40，剩 37 就进不去），
        # 不是剩 0。2026-08-29 用户点名：「用尽不是零吗？还剩 20 多」。
        out["okww_stopped"] = "体力不够再开一局"
    elif "not enough stamina" in text:
        out["okww_stopped"] = "体力不够，一局都没开成"
    # 只报有信息量的：领邮件、领电台、领每日奖励每轮都会做，写进报告只是噪音。
    # 运营 2026-08-25：「除了周常乐园、刷取的关卡、残像聚落之外也别写上去了」。
    # 出现在日志里 != 做成了。凝素领域可能因为体力不够而根本没进本，梦魇任务
    # 可能抛异常被 DailyTask 吞掉——把这两种都写成"完成"就是假的。所以每一项
    # 都按它自己的成败标注。
    steps = []
    for needle, name in (
        ("ForgeryTask:", _forgery_label(text)),
        ("TacetTask:", "无音区"),
        ("SimulationTask:", "模拟领域"),
    ):
        if needle not in text:
            continue
        if entries:
            steps.append(f"{name} ×{entries}")
        else:
            steps.append(f"{name}（未进本）")
    if "NightmareNestTask:" in text:
        nest = "残象聚落" if "canxiang" in text else "梦魇巢穴"
        # 出现在日志里 != 打过。2026-08-27 连着三轮走到 `open_boss_book canxiang`
        # 却一场没打，而这里照样写成「残象聚落」，日报因此报了全绿。
        # 判据换成「有没有真的进本」，并且把「已满跳过」和「找不到点位」分开说。
        if "NightmareNestTask Failed" in text:
            steps.append(f"{nest}（失败）")
        elif "列表里没找到指定的点位" in text:
            steps.append(f"{nest}（点位名对不上，一次没打）")
        elif "指定点位都已打满" in text:
            # 「跳过」是 find_nest 内部的说法，不该漏进给人看的报告：
            # 打满了是**干完了**，不是没干。
            steps.append(f"{nest}（已刷满）")
        elif re.search(r"is not complete|click_team_challenge|echo captured", text):
            steps.append(nest)
        else:
            steps.append(f"{nest}（开了界面就退出，一次没打）")
    if "weekly garden already completed" in text:
        steps.append("周常乐园（本周已完成）")
    elif "GardenTask:" in text:
        steps.append("周常乐园")
    if "check discarded echo" in text:
        steps.append("声骸五合一")
    if steps:
        out["okww_steps"] = steps
    return out


def parse_record(json_path: Path, history_root: Path) -> RunRecord | None:
    """Parse one result JSON. Returns None if it is not a run record."""
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None

    try:
        rel = json_path.relative_to(history_root)
        date_str, user, stem = rel.parts[0], rel.parts[1], json_path.stem
    except (ValueError, IndexError):
        return None

    # AUTO-MAS names these files by the run's start time on a UTC+4 clock.
    # v5.4.0-beta.7 started prefixing them with the script name, so the same
    # record is "05-00-01.json" on 2026-08-22 and "MAA-05-00-00.json" on
    # 2026-08-23. Parsing only the bare form silently dropped every record the
    # morning after that update: an empty ledger, no report, no power-off, and
    # a "该跑没跑" alarm for a queue that had in fact succeeded.
    stem_time = stem.rsplit("-", 3)[-3:]
    stem_time = "-".join(stem_time) if len(stem_time) == 3 else stem
    try:
        started = datetime.strptime(f"{date_str} {stem_time}", "%Y-%m-%d %H-%M-%S")
    except ValueError:
        return None
    started = started.replace(tzinfo=AUTOMAS_NAME_TZ).astimezone(SERVER_TZ)
    finished = datetime.fromtimestamp(json_path.stat().st_mtime, tz=SERVER_TZ)
    if finished < started:  # clock skew or a copied file; don't produce negatives
        finished = started

    # Which script produced this record, and did it succeed?
    if "maa_result" in raw:
        script = "MAA"
        result = str(raw.get("maa_result") or "")
        ok = result.strip() == _MAA_SUCCESS
        failed = [] if ok else ([result] if result else ["未知错误"])
    elif "maaend_result" in raw:
        script = "MaaEnd"
        result = str(raw.get("maaend_result") or "")
        # "未捕获到日志" means AUTO-MAS could not tell - treat as failure, not success.
        ok = "失败" not in result and "未捕获" not in result and bool(result)
        failed = _split_failed(result) if not ok else []
        if not ok and not failed:
            failed = [result or "未知错误"]
    elif "general_result" in raw:
        # AUTO-MAS files OK-WW under the generic key it uses for 通用脚本, so the
        # key alone cannot name the script - the filename prefix can. Records
        # are "<script>-HH-MM-SS.json" since v5.4.0-beta.7.
        prefix = stem.rsplit("-", 3)[0] if len(stem.rsplit("-", 3)) == 4 else ""
        script = prefix or "通用脚本"
        result = str(raw.get("general_result") or "")
        ok = result.strip() == _MAA_SUCCESS
        failed = [] if ok else ([result] if result else ["未知错误"])
    else:
        return None

    transitional = _is_transitional(result)
    if transitional:
        # 不是故障，是被下一轮取代。别让它出现在失败清单里。
        failed = []

    log_path = json_path.with_suffix(".log")
    # Prefer the log's own timestamps; fall back to filename/mtime only when
    # the log is missing or has none (e.g. "未捕获到日志" runs).
    duration_known = False
    if log_path.exists() and (span := _log_span(log_path)):
        started, finished = span
        duration_known = True

    # AUTO-MAS always hands us empty drop/recruit stats, so recover them from
    # the log. Only fill what is genuinely missing - if a future AUTO-MAS
    # version starts populating these, its numbers win over our parsing.
    if log_path.exists():
        if script == "MAA":
            parsed = parse_maa_log(log_path)
        elif script == "MaaEnd":
            parsed = parse_maaend_log(log_path)
        else:
            parsed = parse_okww_log(log_path)
        for key, value in parsed.items():
            if not raw.get(key):
                raw[key] = value
    if flat := flatten_drops(raw):
        raw["drop_statistics"] = flat
    # 回满时间：MAA 自己写在结果 JSON 里，另外两个得算。用这条记录的结束时刻
    # 当起点——那正是最后一次读数的时刻。
    if not raw.get("sanity_full_at"):
        if script == "MaaEnd" and raw.get("sanity") is not None:
            raw["sanity_full_at"] = _full_at_sentence(
                int(raw["sanity"]), int(raw.get("sanity_cap") or 360),
                _END_SANITY_SEC_PER_POINT, finished)
        elif raw.get("okww_stamina_left") is not None:
            raw["sanity_full_at"] = _full_at_sentence(
                int(raw["okww_stamina_left"]), _OKWW_STAMINA_CAP,
                _OKWW_SEC_PER_POINT, finished)

    return RunRecord(
        run_id=f"{date_str}/{user}/{stem}",
        script=script,
        user=user,
        started=started,
        finished=finished,
        ok=ok,
        failed_tasks=failed,
        transitional=transitional,
        raw=raw,
        log_path=log_path if log_path.exists() else None,
        duration_known=duration_known,
    )


def scan(history_root: Path, seen: set[str]) -> list[RunRecord]:
    """Return records not in `seen`, oldest first.

    Only files that have stopped changing are returned: a run still being
    written would otherwise be reported as finished.
    """
    out: list[RunRecord] = []
    now = datetime.now(tz=SERVER_TZ).timestamp()
    for path in sorted(history_root.rglob("*.json")):
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        # Wait only for an incomplete pair: AUTO-MAS writes the .json first and
        # its .log moments later, and a log-less parse is frozen wrong forever
        # once the engine marks it seen (filename/mtime times, no drops, no
        # annihilation flags). The .log's own write fires the next directory
        # event, so the record is processed seconds later with full data. A
        # flat "younger than 20s" gate here used to skip every record on the
        # very event its own write triggered, deferring "失败立刻推" to the
        # next unrelated wake - up to an hour at night. Past 120s assume the
        # run genuinely produced no log and take the record as it is. Negative
        # age means clock skew (mtime in the future); never skip those forever.
        if 0 <= age < 120 and not path.with_suffix(".log").exists():
            continue
        rec = parse_record(path, history_root)
        if rec and rec.run_id not in seen:
            out.append(rec)
    out.sort(key=lambda r: r.started)
    return out


def log_tail(rec: RunRecord, lines: int = 60) -> str:
    """Last N meaningful log lines, for failure diagnosis.

    MaaFramework spams template-matcher errors that are noise, not causes.
    """
    if not rec.log_path:
        return ""
    try:
        text = rec.log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    keep = [
        ln for ln in text.splitlines()
        if ln.strip() and "TemplateMatcher.cpp" not in ln
    ]
    return "\n".join(keep[-lines:])
