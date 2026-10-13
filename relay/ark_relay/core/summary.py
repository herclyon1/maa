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


# Set once the endpoint has failed in this process, so later calls skip it. The
# wording is optional (the alert and the report are complete without it), and
# each attempt against a dead endpoint can cost the full _TIMEOUT inside the path
# that must finish before power-off. Process-lifetime only: the next boot tries
# again.
_endpoint_dead = False


def _ask(cfg: Config, prompt: str, max_tokens: int = 400) -> str:
    global _endpoint_dead  # noqa: PLW0603 - process-lifetime circuit breaker
    if not cfg.llm_key or _endpoint_dead:
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
        log.warning("%s 调用失败，本次启动不再尝试措辞生成: %s",
                    cfg.llm_provider, exc)
        _endpoint_dead = True
        return ""
    try:
        return _extract(cfg, data)
    except (AttributeError, TypeError, IndexError, KeyError):
        # A shape we cannot read is as unusable as no answer, and it will be
        # the same shape next time. An error body (a rejected key, a model
        # that no longer exists) arrives here with HTTP 200 and lands in this
        # branch, so the breaker belongs here too.
        log.warning("模型返回格式看不懂，本次启动不再尝试: %s", str(data)[:200])
        _endpoint_dead = True
        return ""


def check(cfg: Config) -> tuple[bool, str]:
    """Verify the model endpoint actually answers. Used by `ark_relay check`."""
    global _endpoint_dead  # noqa: PLW0603 - an explicit check must really ask
    _endpoint_dead = False
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
