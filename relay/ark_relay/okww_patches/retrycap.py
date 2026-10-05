"""OK-WW patch: retrycap. Split out of okww_patch.py (2026-09-06, moved verbatim)."""
from __future__ import annotations


# ---- Cap on catch-all retries: bail out after three failures in a row, never spin forever ----
# 来龙去脉见 docs/CODE-HISTORY.md「retrycap.py:(模块级)」
_RETRYCAP_OLD = """            logger.error('farm 4c error, try handle monthly card', e)
            if self.handle_claim_button() or self.handle_monthly_card():"""

# Revert-only since the behaviour moved into okww_files/ark_overrides.tasks.py:
# okww_patch._REVERTS finds this text in an upstream file and puts upstream's back.
# It is not applied anywhere (okww_patch._APPLIES), so there is no _Patch for it;
# the overlay's copy is the code that runs.
_RETRYCAP_NEW = """            logger.error('farm 4c error, try handle monthly card', e)
            # 本地补丁：退出机制。连败 3 次就停，不许无限重试。
            self._farm_fail_count = getattr(self, '_farm_fail_count', 0) + 1
            if self._farm_fail_count >= 3:
                self.log_info('连续 3 次失败，退出本次周本任务，不再重试')
                raise TaskDisabledException()
            if self.handle_claim_button() or self.handle_monthly_card():"""
