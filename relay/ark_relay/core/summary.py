"""LLM calls - wording only.

The model never decides whether a run failed, which task failed, or what any
number is. Those are settled in core.py before it is ever called. It receives
already-decided facts and turns them into a readable sentence.

If the call fails, times out, or is not configured, the caller still has a
complete message from core.py. Prose is an enhancement, never a dependency.

Two wire formats are supported so the relay can run either side of the Great
Firewall without touching business logic:

    anthropic   api.anthropic.com          (blocked from mainland China)
    openai      DeepSeek and anything else speaking the OpenAI chat API
"""
from __future__ import annotations

import http.client
import json
import logging
import time
import urllib.error
import urllib.request

from ark_relay.core.config import Config

log = logging.getLogger("ark.summary")

_TIMEOUT = 60

_DIAGNOSIS_PROMPT = """你在帮一个人看游戏自动化脚本的失败日志。

已经确定的事实（不要质疑、不要重新判断）：
- 脚本：{script}
- 失败的任务：{failed}

下面是日志末尾。请**只**用两三句中文说清楚：直接原因是什么，需不需要人工介入。
不要复述日志，不要列 emoji 标题，不要给无关建议。如果日志看不出原因，就直说看不出。

日志：
{log}
"""

def _request(cfg: Config, prompt: str, max_tokens: int):
    """Build the provider-specific request."""
    if cfg.llm_provider == "anthropic":
        url = cfg.llm_base_url.rstrip("/") + "/v1/messages"
        body = {
            "model": cfg.llm_model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "content-type": "application/json",
            "x-api-key": cfg.llm_key,
            "anthropic-version": "2023-06-01",
        }
    else:  # openai-compatible: DeepSeek, and most domestic providers
        url = cfg.llm_base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": cfg.llm_model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {cfg.llm_key}",
        }
    return urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers
    )


def _extract(cfg: Config, data: dict) -> str:
    if cfg.llm_provider == "anthropic":
        parts = [b.get("text", "") for b in data.get("content", [])
                 if b.get("type") == "text"]
        return "".join(parts).strip()
    choices = data.get("choices") or []
    if not choices:
        return ""
    return str((choices[0].get("message") or {}).get("content") or "").strip()


# When the endpoint last failed (time.monotonic), None while it answers. Calls within
# REST_S of that skip it: the wording is optional (the alert and the report are complete
# without it), and each attempt against a dead endpoint can cost the full _TIMEOUT inside
# the path that must finish before power-off. Until 11-08 one failure closed it for the
# whole process, so one blip at boot left a boot's alerts and its daily report without
# wording (audit 11-08 B-D7).
_endpoint_dead: "float | None" = None
# Not measured: the number is Gemini's (dispatch relay-opt-round4-1108 R4-06, 11-08:
# 「将 _endpoint_dead 改为带冷却时间（如 600 秒）的时间戳」). Ten _TIMEOUTs: a dead endpoint
# costs at most one timeout in ten minutes.
REST_S = 600
_clock = time.monotonic
# The group hears of a failing endpoint once per process, as before (every WARNING is a
# push, errwatch): a try after the rest that fails again is INFO.
_warned = [False]


def _resting() -> bool:
    return _endpoint_dead is not None and _clock() - _endpoint_dead < REST_S


def _failed(msg: str, *args) -> None:
    global _endpoint_dead  # noqa: PLW0603 - the breaker's state
    if _warned[0]:
        log.info(msg + "（之前已经报过，%d 分钟后再试）", *args, REST_S // 60)
    else:
        _warned[0] = True
        log.warning(msg + "（%d 分钟内不再尝试措辞生成）", *args, REST_S // 60)
    _endpoint_dead = _clock()


def _ask(cfg: Config, prompt: str, max_tokens: int = 400) -> str:
    global _endpoint_dead  # noqa: PLW0603 - the breaker's state
    if not cfg.llm_key or _resting():
        return ""
    try:
        with urllib.request.urlopen(_request(cfg, prompt, max_tokens),
                                    timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError,
            http.client.HTTPException, ValueError) as exc:
        # HTTPException (IncompleteRead mid-response) and ValueError
        # (UnicodeDecodeError) are answers a flaky LLM endpoint really gives;
        # letting them escape aborted the whole tick that asked for wording -
        # deferring the very failure alert the wording was decorating.
        # Never let a flaky model call break the notification path.
        _failed("%s 调用失败: %s", cfg.llm_provider, exc)
        return ""
    try:
        out = _extract(cfg, data)
    except (AttributeError, TypeError, IndexError, KeyError):
        # A shape we cannot read is as unusable as no answer. An error body (a rejected
        # key, a model that no longer exists) arrives here with HTTP 200 and lands in
        # this branch, so the breaker belongs here too.
        _failed("模型返回格式看不懂: %s", str(data)[:200])
        return ""
    if _endpoint_dead is not None:
        log.info("%s 又能用了，措辞生成照常", cfg.llm_provider)
        _endpoint_dead = None
    return out


def check(cfg: Config) -> tuple[bool, str]:
    """Verify the model endpoint actually answers. Used by `ark_relay check`."""
    global _endpoint_dead  # noqa: PLW0603 - an explicit check must really ask
    _endpoint_dead = None
    if not cfg.llm_key:
        return False, "未配置 API key（不影响运行，只是收不到人话解读）"
    out = _ask(cfg, "回复两个字：正常", max_tokens=20)
    return (True, f"{cfg.llm_provider}/{cfg.llm_model} 返回: {out}") if out \
        else (False, f"{cfg.llm_provider}/{cfg.llm_model} 没有返回内容")


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
