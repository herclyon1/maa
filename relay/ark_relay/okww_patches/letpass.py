"""OK-WW patch: letpass. Split out of okww_patch.py (2026-09-06, moved verbatim)."""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- Let the "deliberate skip" signal pass through the catch-all ----------
# 来龙去脉见 docs/CODE-HISTORY.md「letpass.py:(模块级)」
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
    # Stacking detection counts only our own marker: upstream v3.6.7 also writes a line
    # `except TaskDisabledException:` elsewhere, so counting the generic line would report
    # our patch as stacked (that was the 09-06 false alarm).
    unique="这是「主动跳过」的信号",
)
