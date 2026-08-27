"""读游戏机上的日志——把今晚反复踩的三个坑变成不可能。

这个文件会被 `winrun.sh --py` 自动送到机器上并加进 sys.path，
临时脚本直接 `from arklog import since` 就能用，不用自己拼过滤。

**为什么存在**（2026-08-26 一晚上的账）：

1. **时钟错**：我在东京（UTC+9），机器在北京（UTC+8）。
   用 `datetime.now()` 或自己写死日期去过滤，永远差一小时、
   跨零点还会差一整天。当晚因此三次「查不到任何日志」，
   两次被误判成「任务没起来」。→ `server_today()` / `since()` 一律用机器的钟。

2. **字典序比时间戳**：`[l for l in lines if l[:19] > "2026-08-26 16:40"]`
   看着对，其实 traceback 那些**没有时间戳**的续行（`Traceback...`、
   `  File "..."`）字典序全都大于 `"2026-..."`，于是无论怎么过滤都会漏出来，
   而且看不出它们是哪一刻的。当晚因此把凌晨的旧报错当成了刚发生的。
   → `since()` 只认真正解析出来的时间，续行跟随它上一条带时间戳的行。

3. **日志格式不止一种**：中继写 `08-26 17:04:04`（没有年份），
   OK-WW 写 `2026-08-26 17:04:04`，两种都得认。自己写正则必漏一种。

用法：

    from arklog import since, count, server_today
    for line in since(r"D:\\ark\\okww\\...\\ok-script.log", "21:06"):
        ...
    print(count(lines, r"target_enemy failed"))
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

# 三种格式都要认，自己写正则必漏一种：
#   中继   08-26 17:04:04            （没有年份）
#   OK-WW  2026-08-26 17:04:04
#   MAA    [2026-08-26 17:04:04.665] （方括号 + 毫秒）
_TS_FULL = re.compile(r"^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)")
_TS_SHORT = re.compile(r"^(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)")
_TS_BRACKET = re.compile(r"^\[(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)")


def server_today() -> date:
    """机器自己的日期。

    别用本机的：东京比北京早一小时，跨零点那一小时里两边日期不同，
    拿东京的日期去过滤北京的日志会一条都匹配不上。
    这个模块跑在机器上，所以 `date.today()` 就是机器的日期。
    """
    return date.today()


def parse_ts(line: str, default_year: int | None = None) -> datetime | None:
    """一行日志的时间；不是以时间戳开头就返回 None（续行、空行都算）。"""
    if m := (_TS_FULL.match(line) or _TS_BRACKET.match(line)):
        y, mo, d, h, mi, s = (int(x) for x in m.groups())
        return datetime(y, mo, d, h, mi, s)
    if m := _TS_SHORT.match(line):
        mo, d, h, mi, s = (int(x) for x in m.groups())
        return datetime(default_year or server_today().year, mo, d, h, mi, s)
    return None


def read_lines(path: str | Path) -> list[str]:
    return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()


def since(path: str | Path, hhmm: str, *, on: date | None = None,
          keep_continuations: bool = True, allow_empty: bool = False) -> list[str]:
    """从机器当天的 hhmm（"21:06" 或 "21:06:30"）起的日志行。

    没有时间戳的续行跟随它上面那条带时间戳的行——traceback 才不会
    因为字典序比较而整段漏出来，也不会被错认成另一个时刻的东西。

    两种「看着成功、其实查了个寂寞」的情况一律抛异常，不许静默返回空表：

    * **起点在未来**：手机（东京）比机器（北京）快一小时，抄手机上的
      时刻当窗口起点，等于问「07:39 的机器，08:20 之后发生了什么」。
      2026-08-27 就是这么把「四个程序的预更新结果」查成 0 行的。
    * **窗口整个落在日志末尾之后**：返回 0 行时无法区分「真没事发生」
      和「窗口取错了」。真想问「这之后还有没有动静」就显式传
      `allow_empty=True`，把这个判断写出来，别让它默认发生。
    """
    parts = [int(x) for x in hhmm.split(":")]
    while len(parts) < 3:
        parts.append(0)
    day = on or server_today()
    start = datetime(day.year, day.month, day.day, *parts[:3])

    now = datetime.now()                       # 这个模块跑在机器上 = 北京时间
    if start > now:
        raise ValueError(
            f"起点 {start:%m-%d %H:%M:%S} 还没到（机器现在 {now:%m-%d %H:%M:%S}）。"
            "是不是抄了手机/东京的时间？东京比机器快一小时。"
        )

    out: list[str] = []
    inside = False
    last_ts: datetime | None = None
    for line in read_lines(path):
        ts = parse_ts(line)
        if ts is not None:
            last_ts = ts
            inside = ts >= start
        elif not keep_continuations:
            inside = False
        if inside:
            out.append(line)

    if last_ts is None:
        # 一个时间戳都解析不出来 = 这个文件的格式 arklog 不认识。
        # 这永远不是「没事发生」，`allow_empty` 也不许压掉它——
        # 2026-08-27 就是这么把 MAA 的 gui.log（方括号格式）读成 0 行的。
        raise ValueError(
            f"{Path(path).name} 里一条时间戳都没解析出来——多半是 arklog 不认识"
            f"它的格式。去 arklog.py 补一条正则，别当成「没有日志」。"
        )
    if not out and not allow_empty:
        raise ValueError(
            f"{Path(path).name} 在 {start:%m-%d %H:%M:%S} 之后一行都没有；"
            f"它最后一条带时间戳的记录是 {last_ts:%m-%d %H:%M:%S}。"
            "窗口取早一点，或者确实是要问「这之后还有没有动静」就传 allow_empty=True。"
        )
    return out


def since_minutes(path: str | Path, minutes: int, **kw) -> list[str]:  # deadcode: allow —— 给临时脚本用的库函数
    """最近 N 分钟的日志——不用手打时刻，也就不可能打成东京时间。

    能用相对窗口就别用 `since()` 的绝对时刻。
    """
    start = datetime.now() - timedelta(minutes=minutes)
    return since(path, f"{start:%H:%M:%S}", on=start.date(), **kw)


def count(lines: list[str], pattern: str) -> int:
    rx = re.compile(pattern)
    return sum(1 for l in lines if rx.search(l))


def last(lines: list[str], pattern: str) -> str | None:
    rx = re.compile(pattern)
    hits = [l for l in lines if rx.search(l)]
    return hits[-1] if hits else None


def summarise(lines: list[str], marks: dict[str, str], *, width: int = 22) -> None:  # deadcode: allow —— 给临时脚本用的库函数
    """一组「名字 → 正则」的统计，附最后一次出现的时间和内容。"""
    for name, pat in marks.items():
        rx = re.compile(pat)
        hits = [l for l in lines if rx.search(l)]
        tail = ""
        if hits:
            ts = parse_ts(hits[-1])
            body = re.sub(r"^\S+ \S+ ", "", hits[-1])[:70]
            tail = f"   最后 {ts.strftime('%H:%M:%S') if ts else '??'}  {body}"
        print(f"  {name:<{width}} {len(hits):>4}{tail}")


def mtime(path: str | Path) -> str:
    """文件最后写入时刻（机器的钟）。判断「有没有在动」用它，别猜。"""
    import time
    return time.strftime("%m-%d %H:%M:%S",
                         time.localtime(Path(path).stat().st_mtime))


# 常用路径，省得每次现拼、拼错。
OKWW_LOG = r"D:\ark\okww\data\apps\ok-ww\working\logs\ok-script.log"
RELAY_LOG = r"C:\ProgramData\ark-relay\relay.log"
MAA_GUI_LOG = r"D:\ark\maa\debug\gui.log"
