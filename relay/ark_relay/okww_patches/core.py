"""OK-WW 补丁：core。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations

import logging
import os
import py_compile
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("ark.okww_patch")



_SRC = ("data", "apps", "ok-ww", "working", "src", "task")


@dataclass(frozen=True)
class _Patch:
    name: str               # 人话名字，进通知
    parts: tuple            # 相对 okww_dir 的路径
    old: str                # 上游原样那段
    new: str                # 我们要的那段
    present: Callable[[str], bool]      # 已经在位了吗
    breaks: str             # 贴不上会怎样，写给人看
    upstream: str = ""      # 提给上游之后填 PR 链接；合并了就删掉这条补丁
    # 这条补丁**跨版本不变**的特征串（比如那句日志）。贴完之后它必须只出现
    # 为什么不能拿 new 的头一行当判据：叠加是「旧版本 + 新版本」并存，
    # 来龙去脉见 docs/CODE-HISTORY.md「core.py:_Patch」
    unique: str = ""


def _atomic_write(f: Path, text: str) -> Path | None:
    """备份 → 原子替换。返回备份路径，写不进去返回 None。"""
    bak = f.with_name(f"{f.stem}.py.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.copy2(f, bak)
        tmp = f.with_suffix(".py.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, f)      # 原子替换，别让半截文件被 OK-WW 读到
    except OSError:
        log.warning("OK-WW 补丁：写不进去 %s", f.name, exc_info=True)
        return None
    return bak


def _atomic_write_bytes(f: Path, data: bytes) -> Path | None:
    """原样写字节。整份替换不能经过 write_text——它会按平台改写行尾。"""
    bak = f.with_name(f"{f.stem}.py.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.copy2(f, bak)
        tmp = f.with_suffix(".py.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, f)
    except OSError:
        log.warning("OK-WW 补丁：写不进去 %s", f.name, exc_info=True)
        return None
    return bak


def _verify_or_revert(f: Path, bak: Path, present: Callable[[str], bool],
                      label: str) -> str:
    """回读 + 编译。写进去不等于对，语法坏了整个日常任务都起不来。"""
    back = f.read_text(encoding="utf-8", errors="replace")
    if not present(back):
        shutil.copy2(bak, f)
        log.error("OK-WW 补丁：%s 回读不对，已还原", label)
        return f"OK-WW 补丁：{label} 回读不对，已还原成上游版"
    try:
        py_compile.compile(str(f), doraise=True)
    except (py_compile.PyCompileError, OSError):
        shutil.copy2(bak, f)
        log.error("OK-WW 补丁：%s 语法检查没过，已还原", label, exc_info=True)
        return f"OK-WW 补丁：{label} 改完语法不对，已还原成上游版"
    return ""


def _stacked(f: Path, p: _Patch) -> "str | None":
    """贴完之后自查有没有叠加。返回告警文字，正常时 None。

    来龙去脉见 docs/CODE-HISTORY.md「core.py:_stacked」。
    """
    head = p.unique or next((ln for ln in p.new.splitlines() if ln.strip()), "")
    if not head:
        return None
    try:
        n = f.read_text(encoding="utf-8").count(head)
    except OSError:
        return None
    if n <= 1:
        return None
    log.error("OK-WW 补丁：%s 叠了 %d 层，需要人工看一眼", p.name, n)
    return (f"OK-WW 补丁：{p.name}**叠了 {n} 层**——旧版本没还原干净，"
            f"旧那段会先跑。{p.breaks}")


def _apply_one(root: Path, p: _Patch) -> list[str]:
    # 注意 present() 的判据必须跟着 new 一起改。
    # 来龙去脉见 docs/CODE-HISTORY.md「core.py:_apply_one」
    f = root.joinpath(*p.parts)
    if not f.exists():
        log.warning("OK-WW 补丁：找不到 %s，跳过", f)
        return [f"OK-WW 补丁：找不到 {f.name}，{p.name} 没能检查"]
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        log.warning("OK-WW 补丁：读不了 %s", f, exc_info=True)
        return [f"OK-WW 补丁：读不了 {f.name}"]

    if p.present(text):
        return []                      # 幂等：在位就不留痕迹也不报噪音
    if p.old not in text:
        # 上游改了结构。硬替换只会把文件改坏，所以停手并出声。
        log.warning("OK-WW 补丁：认不出上游 %s 那段，结构可能变了，不动它", p.name)
        return [f"OK-WW 补丁：{p.name}**贴不上了**（上游结构变了），"
                f"{p.breaks}，需要人工看一眼"]

    bak = _atomic_write(f, text.replace(p.old, p.new, 1))
    if bak is None:
        return [f"OK-WW 补丁：{p.name} 写不进去，{p.breaks}"]
    if err := _verify_or_revert(f, bak, p.present, p.name):
        return [err]
    if (dup := _stacked(f, p)) is not None:
        return [dup]
    log.info("OK-WW 补丁：%s 已重新贴上", p.name)
    return [f"OK-WW 补丁：{p.name} 已重新贴上（上次更新把它覆盖了）"]

def _revert_text(root: Path, parts: tuple, new: str, old: str,
                 label: str) -> list[str]:
    """把一段本地改动还原回上游原样。找不到就当已经还原了，不出声。

    **只停止重打是不够的**：`ensure_patches` 只会打不会撤，
    从清单里删掉一条补丁，已经贴在机器上的那份还在，
    要等 OK-WW 下次更新覆盖文件才会消失。所以要主动撤。
    """
    f = root.joinpath(*parts)
    if not f.exists():
        return []
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return [f"OK-WW 补丁：读不了 {f.name}，{label} 没能撤销"]
    if new not in text:
        return []                       # 幂等：已经是上游原样
    bak = _atomic_write(f, text.replace(new, old, 1))
    if bak is None:
        return [f"OK-WW 补丁：{label} 撤销失败，写不进去"]
    log.info("OK-WW 补丁：%s 已撤销，还原成上游原样", label)
    return [f"OK-WW 补丁：{label} 已撤销（证据不足，见 2026-08-30 的结论）"]
