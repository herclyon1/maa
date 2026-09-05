"""OK-WW 补丁：nest。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations

import logging
import hashlib
from pathlib import Path

from .core import _SRC, _atomic_write_bytes, _verify_or_revert

log = logging.getLogger("ark.okww_patch")




# ── 补丁三：巢穴任务（整文件替换）──────────────────────────────
# 这条补丁改了三处、还加了一个方法和一个配置项，用文本替换拼太脆。
# 改成**整文件替换 + 哈希守卫**：只有当机器上那份和我们记录的上游版
# 一字不差时才替换；上游一改动哈希就对不上，我们停手并出声，
# 绝不拿旧补丁去盖新代码。
#
# 三处改动：
#   1. 允许续刷未打满的点位（原来只认「已击败 0/N」，刷过一只就永久放弃）
#      —— 上游 PR ok-oldking/ok-wuthering-waves#1629
#   2. 同一点位打完没进展就跳过，别无限重进（队伍打不过时游戏弹「挑战失败」）
#   3. 新增「只刷指定点位」配置（对应 issue #1622，上游还没有这个能力）
_NEST_DIR = Path(__file__).resolve().parent.parent / "okww_files"   # 拆成子包后多了一层
_NEST_UPSTREAM = _NEST_DIR / "NightmareNestTask.upstream.py"
_NEST_PATCHED = _NEST_DIR / "NightmareNestTask.patched.py"


def _sha(data: bytes) -> str:
    """按**内容**算哈希，不算行尾符。

    Windows 上 `write_text` 会把 \n 换成 \r\n，于是同一份内容在两台机器上
    字节不同、哈希不同。2026-08-26 就因此把「已经贴好的补丁」误判成
    「和上游对不上」。统一成 \n 再算，比的就是内容本身。
    """
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


# 我们自己发布过的历次 NightmareNestTask 版本的哈希。
# 为什么需要：护栏原本只认「上游那份」和「当前这份」，一旦我们自己改了补丁，
# 机器上那份就两边都不是，于是被判成「有人手改过」而拒绝覆盖——
# 结果是自己的修复永远推不上去。历史版本记在这里，见到就照常覆盖。
# 我方标记：上游源码里绝不会出现的、我们自己造的配置常量。
# 见到它 = 现场那份出自我们之手，可以放心覆盖成最新版。
_NEST_MARKER = b"Only Farm These Nests"

_NEST_KNOWN_OURS = {
    "6b27d6f03f7210f80cb5da823a55c5732f26935f16ab775196aee80376b2ff7e",   # 2026-08-27 12:05：hit_wanted 版（与最终版只差 docstring，漏记了哈希）
    "788a8b633498b44f33dbd56d96b971cc95265e88719f6dc0a9f47fe2b4897916",   # 2026-08-27 11:35：临时的几何日志版
    "fc7207ff2047999241cd1ce44996b54b13f2a9d1d0169e344615490bf57e85d5",   # 2026-08-27 11:26：包含匹配，但行匹配容差只有一倍行高
    "48ec36c8c117854dfdd86d160a89bc76ce6e26a9b1c445c7605935b69f044726",   # 2026-08-27 上午：指定点位用了精确匹配，对不上「落渊南丘残象聚落」
    "72cf1da2e840918fe62656acfb5b9434e84b1f320829ccf256d7f9aa9c9fcc34",   # 2026-08-27 之前：指定点位只 OCR 一次，不等列表渲染
}


def _apply_nest(root: Path) -> list[str]:
    f = root.joinpath(*_SRC, "NightmareNestTask.py")
    label = "巢穴任务（续刷 / 不空转 / 可指定点位）"
    if not f.exists():
        return [f"OK-WW 补丁：找不到 NightmareNestTask.py，{label} 没能检查"]
    if not (_NEST_UPSTREAM.exists() and _NEST_PATCHED.exists()):
        log.warning("OK-WW 补丁：缺少 okww_files 里的参照文件")
        return [f"OK-WW 补丁：{label} 缺少参照文件，没能检查"]

    try:
        cur = f.read_bytes()
    except OSError:
        return ["OK-WW 补丁：读不了 NightmareNestTask.py"]

    patched = _NEST_PATCHED.read_bytes()
    if _sha(cur) == _sha(patched):
        return []                       # 幂等：已经是我们这份
    # 上游永远不会包含我们自己造的这个配置常量，所以见到它就说明现场那份
    # 是我们贴过的某个版本，照常覆盖。
    # 为什么不只靠 _NEST_KNOWN_OURS：那张表要求**每次改补丁都手动补一条哈希**，
    # 2026-08-29 我改了补丁却忘了补，于是修复推不上去，部署还照常报成功
    # （只在日志里留了一行 warning）。靠人记的步骤迟早会漏，标记不会。
    ours_by_marker = _NEST_MARKER in cur
    if not ours_by_marker and _sha(cur) not in _NEST_KNOWN_OURS and \
            _sha(cur) != _sha(_NEST_UPSTREAM.read_bytes()):
        # 既不是上游那份、也不是我们那份——上游改过了，或者有人手改过。
        # 这时候硬盖会把别人的改动抹掉，所以停手。
        log.warning("OK-WW 补丁：NightmareNestTask.py 和记录的上游版对不上，不动它")
        return [f"OK-WW 补丁：{label}**贴不上了**——文件和记录的上游版不一致，"
                "多半是上游更新了，需要人工重做这份补丁"]

    bak = _atomic_write_bytes(f, patched)
    if bak is None:
        return [f"OK-WW 补丁：{label} 写不进去"]
    if err := _verify_or_revert(f, bak, lambda s: _sha(s.encode("utf-8")) == _sha(patched), label):
        return [err]
    log.info("OK-WW 补丁：%s 已重新贴上", label)
    return [f"OK-WW 补丁：{label} 已重新贴上（上次更新把它覆盖了）"]
