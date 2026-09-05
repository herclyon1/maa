"""OK-WW 补丁：farmerr。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 周本活锁：把被吞掉的异常打出来 ----------------------------------------
#
# 2026-08-31 实测：12:35:53→12:47:44 之间「传送 → found a claim reward → 传送」
# 转了 21 圈、35 秒一圈，白烧 12 分钟才真打上 Boss。上游那段是：
#
#     except Exception as e:
#         logger.error('farm 4c error, try handle monthly card', e)
#         if self.handle_claim_button() or self.handle_monthly_card():
#             self.run()
#
# logging 把第二个位置参数当成 msg 的 printf 参数，而 msg 里没有 %s，
# 于是**异常内容整个丢掉**——日志里只剩一句没有信息量的 'farm 4c error'，
# 真因查不到。这条补丁只把它改成 exc_info=True，**不动任何控制流**：
# 递归、重试次数、判定全部原样。下一次周本一跑，真因就会自己写在日志里。
#
# 递归没有上限这件事是上游的设计问题，已提 issue，本地不擅自改控制流——
# 改了就等于在没有证据的情况下动生产脚本。
_FARMERR_OLD = """            logger.error('farm 4c error, try handle monthly card', e)"""

_FARMERR_NEW = """            # 本地补丁：上游把异常当成 printf 参数传进去了，内容会被丢掉。
            logger.error(f'farm 4c error, try handle monthly card: {e!r}',
                         exc_info=True)"""


def _farmerr_present(text: str) -> bool:
    return "farm 4c error, try handle monthly card: {e!r}" in text


_FARMERR = _Patch(
    name="周本活锁：打出被吞掉的异常",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_FARMERR_OLD,
    new=_FARMERR_NEW,
    present=_farmerr_present,
    breaks="周本活锁的真因继续查不到，日志里只有一句没信息量的 farm 4c error",
)
