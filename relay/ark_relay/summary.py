"""Claude API - wording only.

The model never decides whether a run failed, which task failed, or what any
number is. Those are settled in core.py before it is ever called. It receives
already-decided facts and turns them into a readable sentence.

If the call fails, times out, or is not configured, the caller still has a
complete message from core.py. Prose is an enhancement, never a dependency.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from .config import Config

log = logging.getLogger("ark.summary")

_API = "https://api.anthropic.com/v1/messages"
_TIMEOUT = 45

_DIAGNOSIS_PROMPT = """你在帮一个人看游戏自动化脚本的失败日志。

已经确定的事实（不要质疑、不要重新判断）：
- 脚本：{script}
- 失败的任务：{failed}

下面是日志末尾。请**只**用两三句中文说清楚：直接原因是什么，需不需要人工介入。
不要复述日志，不要列 emoji 标题，不要给无关建议。如果日志看不出原因，就直说看不出。

日志：
{log}
"""

_DAILY_PROMPT = """下面是某人游戏自动化脚本今天的运行记录（JSON，已经整理好）。

请用**一两句**中文说一下今天整体怎么样。要点：
- 如果全部成功，说得轻松一点，不用复述数字（数字已经单独列出来了）
- 如果有失败，指出是哪一项、要不要管
- 不要重复 JSON 里的数字，不要编造任何数字
- 不要用 emoji 标题，不要分点，就是一两句话

记录：
{ledger}
"""


def _ask(cfg: Config, prompt: str, max_tokens: int = 400) -> str:
    if not cfg.anthropic_key:
        return ""
    body = json.dumps({
        "model": cfg.model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(_API, data=body, headers={
        "content-type": "application/json",
        "x-api-key": cfg.anthropic_key,
        "anthropic-version": "2023-06-01",
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        log.warning("Claude 调用失败，跳过措辞生成: %s", exc)
        return ""
    try:
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return "".join(parts).strip()
    except (AttributeError, TypeError):
        return ""


def diagnose(cfg: Config, script: str, failed: list[str], log_tail: str) -> str:
    """One or two sentences explaining a failure. Empty string if unavailable."""
    if not log_tail.strip():
        return ""
    return _ask(cfg, _DIAGNOSIS_PROMPT.format(
        script=script,
        failed="、".join(failed) or "未知",
        # Keep the payload small; the tail is where the cause lives.
        log=log_tail[-6000:],
    ), max_tokens=300)


def daily_prose(cfg: Config, entries: list[dict]) -> str:
    """A short human line for the daily report. Empty string if unavailable."""
    if not entries:
        return ""
    # Drop the raw blobs - the model only needs the shape of the day.
    slim = [{
        "script": e["script"],
        "ok": e["ok"],
        "failed_tasks": e.get("failed_tasks") or [],
        "started": e["started"],
        "finished": e["finished"],
    } for e in entries]
    return _ask(cfg, _DAILY_PROMPT.format(
        ledger=json.dumps(slim, ensure_ascii=False, indent=2)
    ), max_tokens=300)
