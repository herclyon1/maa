"""OK-WW 补丁：letpass。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 让「主动跳过」这个信号穿过兜底 ----------------------------------------
#
# teleport_to_configured_boss_and_prepare 的兜底把**所有**异常包成 RuntimeError：
#     except Exception as e:
#         raise RuntimeError('Teleport to boss failed') from e
# 于是我们主动抛的 TaskDisabledException 也被包住，run() 那句
# `except TaskDisabledException: pass` 永远看不到它，落进后面的通用兜底，
# 打一条 farm 4c error 再递归重试。
#
# 2026-08-31 实测：波片不足时确实跳过了、Boss 一轮都没白打，但日志里
# 仍有 3 条 farm 4c error、跳过也重复了 3 次——就是被这层包装挡的。
# 放行 TaskDisabledException，其余照旧包成 RuntimeError。
_LETPASS_OLD = """        except Exception as e:
            raise RuntimeError('Teleport to boss failed') from e"""

_LETPASS_NEW = """        except TaskDisabledException:
            # 本地补丁：这是「主动跳过」的信号，不是失败，不许包成 RuntimeError，
            # 否则 run() 的 except TaskDisabledException 收不到，会当成错误重试。
            raise
        except Exception as e:
            raise RuntimeError('Teleport to boss failed') from e"""


def _letpass_present(text: str) -> bool:
    return "这是「主动跳过」的信号" in text


_LETPASS = _Patch(
    name="放行主动跳过的信号",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_LETPASS_OLD,
    new=_LETPASS_NEW,
    present=_letpass_present,
    breaks="波片不足时虽然会跳过，但每次都留一条 farm 4c error 并重试三遍",
)
