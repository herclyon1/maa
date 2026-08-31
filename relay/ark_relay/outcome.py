"""跑完之后核对「到底干成了什么」——没干成就必须出声。

**为什么存在**（2026-08-27 全天的账）：

那天 OK-WW 连着三轮没打残象聚落、MaaEnd 卡在一个弹窗上把「失败」当「做完」
自己关掉、AUTO-MAS 队列停住不推进——**三件事都没有任何报错**，
而中继照样给用户报「全绿」。用户的原话是：

> 他不报错，他直接把自己关掉了，他不说自己被卡在某个地方，他不提醒，
> 直接把整个队列都给卡死了。

根子在 `collector.py`：它当时的判据是「日志里提到过这个任务名」就算做了。
**出现在日志里 ≠ 做成了。**一个任务可以打开界面、找不到目标、原地退出，
全程一个 ERROR 都不打。

所以这里换一种判据：**要证据，不要痕迹。**
每一项都问「有没有它真的发生过的证据」，没有就列进「没干成」，
由 engine 发通知，而不是静默记账。

判据全部来自实测日志，不是猜的；每条都注明出处。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


@dataclass
class Check:
    """一项核对结果。`ok=False` 就会被报出去。"""

    label: str          # 人话，直接进通知
    ok: bool
    detail: str = ""    # 为什么这么判，给排查用


# ── OK-WW ──────────────────────────────────────────────────────────
# 真的进过战斗的证据。开界面、传送、找目标都不算——2026-08-27 三轮
# 全都走到了 `open_boss_book canxiang` 却一场没打。
_NEST_ENGAGED = re.compile(r"is not complete|click_team_challenge|"
                           r"wait_in_team_and_world|echo captured")
# 我们自己补丁打出来的两句，用来区分「正常跳过」和「故障」。
_NEST_ALL_FULL = "指定点位都已打满，跳过"
_NEST_NOT_FOUND = "列表里没找到指定的点位"
# DailyTask 跑完的标志（上游自己打的）。
_DAILY_DONE = "Daily Task Completed"
# 体力真的花掉的证据 vs 明说没花。
_STAMINA_SPENT = re.compile(r"enter combat|walk_to_treasure|used all stamina")
_STAMINA_SHORT = "not enough stamina"


# open_daily 打开日常页后读到的活跃度。第一次读数就 ≥ 100 说明这一轮
# 开始前日常已经完成——OK-WW 会正确地只领奖退出，什么都不刷。
_DAILY_POINTS = re.compile(r"info_set total daily points (\d+)")
_DAILY_POINTS_TARGET = 100


def okww_checks(text: str, *, expect_nest: bool, expect_daily: bool = True,
                expect_stamina: bool = True) -> list[Check]:
    """核对一轮 OK-WW。`text` 是这一轮的日志全文。

    `expect_nest` 由配置决定（配了「只刷指定点位」或开了每日声骸就该打）。
    """
    out: list[Check] = []

    # 2026-08-27 13:24 的误报：当天第二轮运行时日常早已完成，OK-WW 只领奖
    # 退出——完全正确，这里却报了「残象聚落没干成」「刷体力没干成」。
    # 「本来就无事可做」和「该做没做成」必须分开。
    m = _DAILY_POINTS.search(text)
    if m and int(m.group(1)) >= _DAILY_POINTS_TARGET:
        done = _DAILY_DONE in text
        out.append(Check("今日日常此前已完成，本轮仅领奖", done,
                         "" if done else "但连领奖收尾都没跑完"))
        return out

    if expect_daily:
        done = _DAILY_DONE in text
        out.append(Check("每日任务跑完", done,
                         "" if done else f"日志里没有「{_DAILY_DONE}」"))

    if expect_nest:
        if _NEST_NOT_FOUND in text:
            out.append(Check("残象聚落", False,
                             "配置里的点位名在游戏列表里没找到——多半是名字写错了，"
                             "或者界面变了"))
        elif _NEST_ALL_FULL in text:
            out.append(Check("残象聚落（已满，跳过）", True, "指定点位都打满了"))
        elif _NEST_ENGAGED.search(text):
            out.append(Check("残象聚落", True, "有进本/战斗记录"))
        elif "NightmareNestTask" in text:
            out.append(Check("残象聚落", False,
                             "任务起来了，但既没打、也没说点位已满——"
                             "开了界面就原地退出了"))
        else:
            out.append(Check("残象聚落", False, "这一轮根本没跑到这个任务"))

    if expect_stamina:
        if _STAMINA_SHORT in text and not _STAMINA_SPENT.search(text):
            out.append(Check("刷体力", True, "体力不足，本来就没得刷"))
        elif _STAMINA_SPENT.search(text):
            out.append(Check("刷体力", True, ""))
        else:
            out.append(Check("刷体力", False, "既没进本，也没说体力不足"))

    return out


# ── MaaEnd ─────────────────────────────────────────────────────────
# 万能跳转失败会存一张 on_error 截图。2026-08-27 那次卡弹窗，
# 20 分钟里存了三张，而 MaaEnd 自己一个 ERROR 都没报。
# MaaEnd 收尾标记。**它写在 MaaEnd 自己的 app 日志里**
# （`<maaend>/debug/YYYY-MM-DD-N.log`：`INFO [App] 自动执行任务完成，关闭自身`），
# 不在 AUTO-MAS 的 history 日志里。2026-08-29 只喂了后者，于是这条恒为假、
# 天天误报「MaaEnd 没跑完」。修的是数据源，不是判据。
_MAAEND_DONE = "自动执行任务完成"
_MAAEND_STUCK = re.compile(r"SceneAnyEnterWorld|PipelineTask bad next")


def maaend_checks(text: str, on_error_names: list[str]) -> list[Check]:
    """核对一轮 MaaEnd。`on_error_names` 是这一轮新增的截图文件名。"""
    out: list[Check] = []
    done = _MAAEND_DONE in text
    out.append(Check("MaaEnd 跑完", done,
                     "" if done else "日志里没有「自动执行任务完成」"))

    # 附加的结构性判据：每个「任务开始」都该有对应的「任务完成／任务失败」。
    # 它不依赖任何一句固定文案，收尾标记那条万一又被改名也还有这道兜底。
    started = re.findall(r"任务开始[:：]\s*(\S+)", text)
    ended = re.findall(r"任务(?:完成|失败)[:：]\s*(\S+)", text)
    dangling = Counter(started) - Counter(ended)
    if started:
        out.append(Check("每个任务都收了尾", not dangling,
                         "" if not dangling else
                         "开了没收尾：" + "、".join(sorted(dangling))))

    # 万能跳转失败（SceneAnyEnterWorld / PipelineTask bad next）永远算故障——
    # 2026-08-27 那次就是「卡弹窗、自己不报错，只有截图能抓出来」，不能放宽。
    # 其余节点的截图不一样：MaaEnd 会重试，重试成功任务照常完成。
    # 2026-08-29 早班存了 6 张 ScenePrivateMapZoomOut，而环境监测和基质刷取
    # 都报了「任务完成」——把它写成「没干成」是误报。所以只在**确实没跑完**时
    # 才判故障，否则如实列出来但不算故障。
    stuck = [n for n in on_error_names if _MAAEND_STUCK.search(n)]
    if stuck:
        out.append(Check("界面没卡住", False,
                         f"万能跳转失败 {len(stuck)} 次，存了截图："
                         + "、".join(stuck[:3])))
    elif on_error_names and not done:
        out.append(Check("界面没卡住", False,
                         f"有 {len(on_error_names)} 张出错截图："
                         + "、".join(on_error_names[:3])))
    elif on_error_names:
        out.append(Check(f"出错截图 {len(on_error_names)} 张（已重试恢复）", True))
    else:
        out.append(Check("界面没卡住", True))
    return out


# ── MAA ────────────────────────────────────────────────────────────
# 2026-08-30 之前这里**什么都没有**：`_verify_outcome` 走到 MAA 直接
# return None（=全干成），所以 MAA 只要进程正常退出就恒为绿。
#
# 第一版我按「错误字符串出现次数」判，空跑真实日志立刻打脸：08-29 晚和
# 08-30 早**两趟都会被推送**，而推的正是 `skill has no recognition result`
# 和 `Unknown task` 这两条已经确认无害的噪音。把「全绿」换成「每轮误报两条」
# 比原来更糟——狼来了喊多了，真出事那次就没人看了。
#
# 换成结构化判据：MAA 每条任务链都会打一对
#   TaskChainStart  {"taskchain":"Infrast", ...}
#   TaskChainCompleted {"taskchain":"Infrast", ...}
# 实测两趟都是 StartUp/Fight/Infrast/Recruit/Mall/Award/CloseDown 各一对，
# 零 Error、零 Stopped、零悬挂。**开了没收尾**才是真出事——
# 那正是「队列卡死、脚本自己不吭声」的形状。
_MAA_CHAIN = re.compile(
    r'TaskChain(Start|Completed|Error|Stopped)\b.*?"taskchain":"(\w+)"')


_MAA_STARTUP = re.compile(
    r'TaskChainStart\b.*?"taskchain":"StartUp"')


def _one_run_only(text: str) -> str:
    """只留这一轮。第二个 StartUp 之后的都是下一轮的，砍掉。

    时间窗是 [开始, 结束+5分钟]，那 5 分钟是给收尾行留的余量。两趟挨得近时
    余量会伸进下一趟：2026-08-31 晚上第一趟 21:30:50→21:33:38（窗口到
    21:38:38），第二趟 21:33:43 就开跑，`Infrast` 21:35 开始、21:43 完成——
    于是第一趟的窗口捞到了下一趟的「Infrast 开始」却够不到它的「完成」，
    报了一条「开了没收尾：Infrast」。基建其实好好干完了，纯误报。

    MAA 每轮都以 StartUp 开头，所以第二个 StartUp 就是越界的标志。
    只有一个 StartUp（或一个都没有）时原样返回，不做任何事。
    """
    hits = list(_MAA_STARTUP.finditer(text))
    if len(hits) < 2:
        return text
    cut = text.rfind("\n", 0, hits[1].start())
    return text[:cut] if cut > 0 else text


def maa_checks(text: str) -> list[Check]:
    """核对一轮 MAA。`text` 是这一轮时间窗内的 asst.log。"""
    text = _one_run_only(text)
    started: Counter = Counter()
    ended: Counter = Counter()
    bad: list[str] = []
    for kind, chain in _MAA_CHAIN.findall(text):
        if kind == "Start":
            started[chain] += 1
        else:
            ended[chain] += 1
            if kind in ("Error", "Stopped"):
                bad.append(f"{chain}({'报错' if kind == 'Error' else '被中止'})")

    out: list[Check] = []
    if not started:
        # 一条任务链事件都没有 = 窗口切错了或日志不对，绝不能当成「没问题」。
        out.append(Check("读到了这一轮的任务链事件", False,
                         "asst.log 里没有 TaskChainStart，这一轮无从核对"))
        return out

    dangling = started - ended
    out.append(Check("每条任务链都收了尾", not dangling,
                     "" if not dangling else
                     "开了没收尾：" + "、".join(sorted(dangling))))
    out.append(Check("没有任务链报错或被中止", not bad,
                     "" if not bad else "、".join(sorted(set(bad)))))
    return out


def summarize(checks: list[Check], who: str) -> str | None:
    """有没干成的就返回一段人话；全都干成了返回 None。"""
    bad = [c for c in checks if not c.ok]
    if not bad:
        return None
    lines = [f"{who} 这一轮有 {len(bad)} 项没干成，但它自己没报错："]
    lines += [f"· {c.label}：{c.detail}" if c.detail else f"· {c.label}"
              for c in bad]
    ok = [c.label for c in checks if c.ok]
    if ok:
        lines.append("干成的：" + "、".join(ok))
    return "\n".join(lines)
