"""手机 ↔ 机器的那根管道。零轮询。

用户 2026-08-31 定的形状：

* 开机必取一次指令、必上报一次状态
* 关机前必上报一次状态
* 手机上按「刷新」能实时拿到状态——**仅限机器开着的时候**
* 在线/离线显示，不许轮询

**为什么不是轮询**：机器挂一条长连接在 ntfy 上，连上之后就不动了，
有消息服务端才推过来（实测延迟 0.90 秒）。这跟中继里已有的两处是同一类
写法：进程启动的 WMI 订阅、目录变更通知。断了就重连，重连不是轮询。

**在线判定怎么做的**：手机发一条 ping，机器收到就回一条状态。
几秒内收到回话＝开着，收不到＝关着。不需要心跳，也就不需要轮询。

**凭证就一个 PIN**（用户 2026-08-31：「留一个 pin 就行了，那那么多事」）。
信箱名本身是 28 位随机串，只存在用户手机和机器的 .env 里。
状态里只有游戏配置，没有凭证。

指令窗口开到 24 小时：机器一天只开两趟，手机上按的指令要能在信箱里
等到下次开机。已经处理过的靠 ntfy 自己的消息 id 记住，不会重复执行。
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import atomic_write_text

log = logging.getLogger("ark.phone")

NTFY = "https://ntfy.sh"
# 指令能在信箱里等多久。机器一天开两趟，最长间隔约 11 小时半。
MAX_AGE = 24 * 3600
# 记住多少条处理过的消息 id。一天几条指令，200 个够用好几个月。
SEEN_KEEP = 200
_UA = "ark-relay"


def pack(pin: str, body: dict, kind: str = "cmd") -> str:
    return json.dumps({"v": 1, "kind": kind, "pin": pin,
                       "ts": int(time.time()), "body": body},
                      ensure_ascii=False, separators=(",", ":"))


def unpack(pin: str, raw: str, *, now: "float | None" = None) -> "dict | None":
    """PIN 对不上、或者太老，就当没看见。"""
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(msg, dict):
        return None
    if str(msg.get("pin") or "") != pin:
        return None
    ts = msg.get("ts")
    if not isinstance(ts, int):
        return None
    age = (now if now is not None else time.time()) - ts
    if abs(age) > MAX_AGE:
        log.info("信箱里那条指令太老了（%.1f 小时前），丢弃", age / 3600)
        return None
    return msg


class Mailbox:
    """一个信箱。取指令、发状态、挂长连接。"""

    def __init__(self, topic: str, pin: str, state_dir: Path):
        self.topic = (topic or "").strip()
        self.pin = (pin or "").strip()
        self.state_dir = Path(state_dir)
        self._seen = self._load_seen()

    @property
    def enabled(self) -> bool:
        return bool(self.topic and self.pin)

    # ---------- 记住处理过哪些消息 ----------
    # 开机时会把 24 小时内的消息一次取回，其中大半是上次开机就已经执行过的。
    # 用 ntfy 自己给的消息 id 记一下，免得同一条指令执行两遍。

    def _seen_file(self) -> Path:
        return self.state_dir / "phone-seen.json"

    def _load_seen(self) -> "list[str]":
        try:
            data = json.loads(self._seen_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [str(x) for x in data] if isinstance(data, list) else []

    def _save_seen(self) -> None:
        try:
            atomic_write_text(self._seen_file(),
                              json.dumps(self._seen[-SEEN_KEEP:]))
        except OSError:
            log.warning("处理过的消息 id 存不下来，同一条指令可能被执行两次",
                        exc_info=True)

    # ---------- 发 ----------

    def publish(self, body: dict, kind: str = "state") -> bool:
        if not self.enabled:
            return False
        data = pack(self.pin, body, kind).encode("utf-8")
        req = urllib.request.Request(f"{NTFY}/{self.topic}", data=data,
                                     method="POST",
                                     headers={"User-Agent": _UA,
                                              "Title": kind})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return 200 <= r.status < 300
        except Exception:  # noqa: BLE001
            log.warning("状态没能发到信箱", exc_info=True)
            return False

    # ---------- 取（开机时一次） ----------

    def fetch(self, since: str = "24h") -> "list[dict]":
        """一次性把信箱里等着的指令取回来。不是轮询——只在开机时调一次。"""
        if not self.enabled:
            return []
        url = f"{NTFY}/{self.topic}/json?poll=1&since={since}"
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            log.warning("取不到信箱里的指令", exc_info=True)
            return []
        out: list[dict] = []
        seen = set(self._seen)
        fresh: list[str] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                env = json.loads(line)
            except json.JSONDecodeError:
                continue
            if env.get("event") != "message":
                continue
            mid = str(env.get("id") or "")
            if mid and mid in seen:
                continue          # 上次开机就执行过了
            msg = unpack(self.pin, str(env.get("message") or ""))
            if msg and msg.get("kind") == "cmd":
                out.append(msg["body"])
            if mid:
                fresh.append(mid)
        if fresh:
            self._seen = [*self._seen, *fresh]
            self._save_seen()
        return out

    # ---------- 挂着听（长连接，零轮询） ----------

    def listen(self, on_cmd, stop) -> None:
        """连上就挂着，服务端有消息才推过来。`stop()` 返回真就退出。

        断线重连的退避和 service.py 里 WMI 订阅那段是同一套思路：
        断了要自己接回来，但不能把断线变成密集重试。
        """
        if not self.enabled:
            return
        delay = 5
        while not stop():
            try:
                url = f"{NTFY}/{self.topic}/json"
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                # **不许用 timeout=None**：读会无限期阻塞，停服务时这个线程
                # 挂住，服务卡在 STOP_PENDING 起不来——2026-08-31 撞过一次，
                # 只能强杀进程。ntfy 每 45 秒会发一次 keepalive，
                # 90 秒的读超时永远不会误伤，超时了外层重连就是。
                with urllib.request.urlopen(req, timeout=90) as r:
                    log.info("📱 手机通道已连上（长连接，不轮询）")
                    delay = 5
                    for line in r:
                        if stop():
                            return
                        line = line.decode("utf-8", "replace").strip()
                        if not line:
                            continue
                        try:
                            env = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if env.get("event") != "message":
                            continue
                        mid = str(env.get("id") or "")
                        if mid and mid in set(self._seen):
                            continue
                        msg = unpack(self.pin, str(env.get("message") or ""))
                        if not msg or msg.get("kind") != "cmd":
                            continue
                        if mid:
                            self._seen = [*self._seen, mid]
                            self._save_seen()
                        try:
                            on_cmd(msg["body"])
                        except Exception:  # noqa: BLE001
                            log.exception("手机指令处理出错，连接继续")
            except Exception:  # noqa: BLE001
                if stop():
                    return
                log.warning("手机通道断了，%d 秒后重连", delay, exc_info=True)
            # 断线重连的等待。sleep 在这里不是轮询——它等的是「把连接接回来」，
            # 不是「去问有没有新消息」。
            for _ in range(delay):
                if stop():
                    return
                time.sleep(1)
            delay = min(delay * 2, 60)


def _okww_options(cfg) -> dict:
    """OK-WW 的下拉选项，从它**自己的源码**里读，不自己编。

    用户 2026-08-31：「人家脚本那边根本都不是填东西，而是选择树。」
    OK-WW 在 DailyTask.py 里明确声明了 `type: drop_down` 和 options，
    还有 `sub_configs`——选了哪个才出现哪些子项。照抄它的声明，
    上游改了这里跟着变；硬编码就会有一天悄悄对不上。
    """
    import re  # noqa: PLC0415
    out: dict = {}
    root = getattr(cfg, "okww_dir", None)
    if not root:
        return out
    f = (Path(root) / "data" / "apps" / "ok-ww" / "working" / "src"
         / "task" / "DailyTask.py")
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        log.warning("读不到 OK-WW 的 DailyTask.py，鸣潮那几项只能当文本填")
        return out
    for key, pat in (("Task.WhichToFarm", r"support_tasks\s*=\s*\[([^\]]*)\]"),
                     ("Task.MaterialSelection",
                      r"material_option_list\s*=\s*\[([^\]]*)\]")):
        m = re.search(pat, text, re.S)
        if not m:
            continue
        vals = re.findall(r"""['"]([^'"]+)['"]""", m.group(1))
        if vals:
            out[key] = vals
    return out


# 选了「刷什么」里的哪一项，才显示哪些子项。抄自 OK-WW 的 sub_configs。
OKWW_SUBS = {
    "Tacet Suppression": ["Task.WhichTacetSuppressionToFarm"],
    "Forgery Challenge": ["Task.WhichForgeryChallengeToFarm"],
    "Simulation Challenge": ["Task.MaterialSelection"],
}


def _options(cfg) -> dict:
    """各游戏可选项。取不到就不给，页面那一项退回文本框。"""
    out: dict = {"MAA": {}, "MaaEnd": {}, "OK-WW": {}}
    try:
        from .commands import _find_user, _mas  # noqa: PLC0415
        sid = _find_user("MaaEnd")[0]
        d = _mas("/api/scripts/maaend/options", {"scriptId": sid})
        locs = [[o.get("label"), o.get("value")]
                for o in (d.get("essenceLocations") or [])
                if o.get("value")]
        if locs:
            out["MaaEnd"]["Task.AutoEssenceSpecifiedLocation"] = locs
    except Exception:  # noqa: BLE001
        log.warning("终末地的地点选项取不到", exc_info=True)

    try:
        from . import plan  # noqa: PLC0415
        zh = plan._okww_zh(getattr(cfg, "okww_dir", None))  # noqa: SLF001
        for key, vals in _okww_options(cfg).items():
            # 用 OK-WW 自己的语言包给中文名，不自己译
            out["OK-WW"][key] = [[zh.get(v, v), v] for v in vals]
    except Exception:  # noqa: BLE001
        log.warning("鸣潮的选项取不到", exc_info=True)
    return out


def state_payload(cfg, state_dir: Path) -> dict:
    """手机上显示的那一份。和 config-check 读的是同一份代码（snapshot.py）。"""
    from . import modes, plan, snapshot  # noqa: PLC0415 - 避免导入环
    out: dict = {"at": int(time.time())}
    try:
        out["config"] = snapshot.read()
    except Exception as exc:  # noqa: BLE001
        out["config"] = {"_错误": f"{type(exc).__name__}: {exc}"}
    try:
        out["relay"] = {
            "调试模式": modes.debug_until(state_dir) or "",
            "下次别关机": modes.skip_armed(state_dir),
            "已跳过的关机": modes.shutdown_skipped(state_dir) or "",
        }
    except Exception:  # noqa: BLE001
        out["relay"] = {}
    try:
        out["options"] = _options(cfg)
        out["subs"] = OKWW_SUBS
    except Exception:  # noqa: BLE001
        out["options"] = {}
    try:
        out["plan"] = plan.next_plan(cfg.automas_dir)
    except Exception:  # noqa: BLE001
        out["plan"] = ""
    return out
