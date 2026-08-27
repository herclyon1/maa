"""周常乐园：本周做完就把检查关掉，周一 04:00 自动开回来。

和 `annihilation.py` 是同一个形状——「一周只需要做一次的事，别每天都去看一眼」。
剿灭那边关的是 MAA 的 `Info.Annihilation`，这边关的是 OK-WW 的
`Task.AdditionalTasks` 里那项 `Check Weekly Garden`。

为什么值得做：上游的 `check_weekly_garden()` 每轮都要导航到乐园页面、截图、
判断有没有完成。一周里后六天全是白跑，纯粹的时间浪费。

**为什么走配置层而不是改 OK-WW 源码**：OK-WW 的自动更新会整段覆盖 `src`
（2026-08-26 实测，v3.6.5 → v3.6.6-beta.1 之后本地补丁连备份一起消失）。
配置不在覆盖范围内，所以同样的效果，配置层做就天然免疫。
非改源码不可的那些放 `okww_patch.py`，能在配置层做的一律别去改源码。

**为什么用 AUTO-MAS 的 API 而不是直接写配置文件**：`annihilation.py` 写文件，
于是撞上「AUTO-MAS 运行期间会用内存里的副本覆盖配置文件」——它写进去的
Close 被静静冲掉，整整一周每轮都在跑空剿灭（2026-08-20 实测）。API 是穿过
运行中的后端写的，改完就是它内存里的值，不存在这个问题。
代价是任务运行期间 API 会回 `配置已锁定`，所以照样要挑没任务在跑的时候落盘。
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from .annihilation import week_key          # 周界口径必须和剿灭完全一致
from .config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.garden")

TASK_NAME = "Check Weekly Garden"
_TIMEOUT = 10


def _post(host: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"http://{host}:36163{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def _strip_nulls(obj):
    """把值为 None 的字段全部摘掉，再往回写。

    2026-08-26 实测：`/api/scripts/user/get` 会吐出后端**自己不接受**的字段，
    原样回写就报 `AttributeError: 配置项 'Info.IfUseMasConfig' 不存在`。
    读得到、写不回，是 AUTO-MAS 那边读写两套 schema 不一致。
    它们的值都是 null，摘掉即可，不会丢任何真实设置。

    不摘的后果不是「写不进去」这么简单：`enforce()` 每轮都会重来，
    于是每 30 秒往日志里刷一条同样的失败，一直刷到有人去看。
    """
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nulls(v) for v in obj]
    return obj


def _okww_user(host: str) -> tuple[str, str, dict] | None:
    """(scriptId, userId, 完整用户配置)。找不到 OK-WW 就返回 None。"""
    try:
        scripts = _post(host, "/api/scripts/get", {})["data"]
    except (urllib.error.URLError, OSError, KeyError, ValueError):
        return None
    for sid, sc in scripts.items():
        info = sc.get("Info") or {}
        name = str(info.get("Name") or info.get("RootPath") or "")
        if "ok-ww" not in name.lower() and "okww" not in name.lower():
            continue
        try:
            users = _post(host, "/api/scripts/user/get", {"scriptId": sid}).get("data") or {}
        except (urllib.error.URLError, OSError, ValueError):
            return None
        for uid, cfg in users.items():
            return sid, uid, cfg
    return None


class GardenGate:
    """记住哪一个游戏周的周常乐园已经做完了。"""

    def __init__(self, state_dir: Path, host: str = "127.0.0.1"):
        self.path = Path(state_dir) / "garden.json"
        self.host = host
        self._last_write_error = ""     # 同一条写失败只说一次，见 enforce()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=1))

    def on_success(self, now: datetime | None = None) -> str:
        """报告里出现「周常乐园（本周已完成）」时调用。只记账，不落盘。

        落盘交给 `enforce()`：这一刻队列多半还在跑下一个脚本，
        而配置在任务运行期间是锁的，现在写必然失败。
        """
        now = now or datetime.now(tz=SERVER_TZ)
        week = week_key(now)
        state = self._load()
        if state.get("done_week") == week:
            return ""
        self._save({"done_week": week})
        log.info("本周周常乐园已完成，待脚本停下后关闭检查（周一 04:00 后恢复）")
        return "本周周常乐园已完成，稍后暂停检查到下周一"

    def enforce(self, now: datetime | None = None) -> bool:
        """把开关推到该在的位置。返回是否真的改了东西。

        必须可以反复跑：一次关掉不代表一直关着，而且周一到了要开回来。
        """
        now = now or datetime.now(tz=SERVER_TZ)
        week = week_key(now)
        state = self._load()
        want_off = state.get("done_week") == week

        found = _okww_user(self.host)
        if not found:
            return False
        sid, uid, cfg = found
        task = cfg.setdefault("Task", {})
        tasks = list(task.get("AdditionalTasks") or [])
        has = TASK_NAME in tasks

        if want_off and has:
            tasks.remove(TASK_NAME)
        elif not want_off and not has and state:
            # 周翻篇了：把检查放回去，并清掉记账。
            tasks.append(TASK_NAME)
        else:
            if not want_off and state:
                self._save({})          # 过期的记账，顺手清掉
            return False

        task["AdditionalTasks"] = tasks
        try:
            r = _post(self.host, "/api/scripts/user/update",
                      {"scriptId": sid, "userId": uid, "data": _strip_nulls(cfg)})
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.warning("周常乐园开关写不进去：%s", exc)
            return False
        if r.get("status") != "success":
            # `配置已锁定` 是预期内的——有任务在跑，下一轮再来，幂等，不必出声。
            # 其余的都是真问题：同一条错会每轮复现，全打出来就是每 30 秒刷一屏。
            # 所以只在**错误内容变了**的时候说一次。
            msg = str(r.get("message") or "")
            if "配置已锁定" in msg:
                log.debug("周常乐园开关：配置锁着（有任务在跑），下轮再来")
            elif msg != self._last_write_error:
                log.warning("周常乐园开关写不进去：%s（会继续重试，"
                            "但这条不是「锁着」，多半得人去看）", msg)
            self._last_write_error = msg
            return False
        self._last_write_error = ""

        if want_off:
            log.info("已关闭周常乐园检查（周一 04:00 后自动恢复）")
        else:
            self._save({})
            log.info("新的一周，周常乐园检查已恢复")
        return True
