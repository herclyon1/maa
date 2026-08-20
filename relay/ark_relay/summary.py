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

from .config import Config

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

_DAILY_PROMPT = """你在给一个人写他游戏自动化脚本的当天日报。他人在东京，机器在中国，两地差 1 小时。

下面是 AUTO-MAS 今天写下的**原始运行记录**，一条一条给你，没有经过任何加工。
你自己读，自己判断哪些值得说。

写作要求：
- 手机上看，行要短，不要多级缩进（全角空格在不同字体下对不齐）
- 时间一律写成「服务器时刻（东京 时刻）」，服务器时间加 1 小时就是东京时间
- 关卡、掉落数量、理智这些数字**必须逐字照抄原始记录**，一个字都不许改，也不许自己算
- 原始记录里没有的东西不要写，不确定就说不确定
- 有失败的，说清楚是哪个脚本的哪一项
- 不要写「总结」「报告」这种标题词，直接讲内容
- 末尾原样附上「明日安排」那段，不要改写

今天的原始记录（JSON）：
{records}

明日安排（原样附在末尾）：
{plan}
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


def _ask(cfg: Config, prompt: str, max_tokens: int = 400) -> str:
    if not cfg.llm_key:
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
        log.warning("%s 调用失败，跳过措辞生成: %s", cfg.llm_provider, exc)
        return ""
    try:
        return _extract(cfg, data)
    except (AttributeError, TypeError, IndexError, KeyError):
        log.warning("模型返回格式看不懂，跳过: %s", str(data)[:200])
        return ""


def check(cfg: Config) -> tuple[bool, str]:
    """Verify the model endpoint actually answers. Used by `ark_relay check`."""
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


def daily_report(cfg: Config, entries: list[dict], plan: str = "") -> str:
    """The whole daily report, written by the model from the raw records.

    Deliberately not pre-digested: earlier versions parsed every field with
    regexes and handed the model a finished table to garnish. That approach
    produced three separate wrong-fact bugs (a 42-minute run reported as
    4h45m, a mis-split failure list, a timestamp source that was off by
    hours) - each one a wrong guess about the format. A model reading the
    original text does not have to guess.

    Returns "" when unavailable; the caller then falls back to the
    deterministic layout, which is never wrong but never explains anything.
    """
    if not entries:
        return ""
    material = [{
        "脚本": e["script"],
        "账号": e.get("user"),
        "开始": e["started"],
        "结束": e["finished"],
        "时长可信": e.get("duration_known", True),
        "AUTO-MAS原始输出": e.get("raw") or {
            "ok": e["ok"], "failed_tasks": e.get("failed_tasks") or []},
    } for e in entries]
    return _ask(cfg, _DAILY_PROMPT.format(
        records=json.dumps(material, ensure_ascii=False, indent=2),
        plan=plan or "（读不到）",
    ), max_tokens=1500)
