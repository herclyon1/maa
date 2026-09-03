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

import base64
import gzip
import json
import logging
import re
import threading
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


def pack(pin: str, body: dict, kind: str = "cmd", *, gz: bool = False) -> str:
    """信封。`gz=True` 时 body 换成 gzip+base64 的字符串，字段名叫 `gz`。

    为什么要压：状态里 `options`（那一堆中文下拉候选）占 57%，
    2026-08-31 量到整包 3783 字节、离上限只剩 117。再加一个字段就会触发
    降级——先砍「明日安排」，再砍「选项表」，而选项表正是手机上那些
    中文下拉，砍掉等于功能没了，而且**不出声地没了**。
    压完 2464 字节，余量一下子回到一千多。

    发的那头只在**明文会超限**时才压，所以平时还是明文；
    收的那头两种都认。这样手机上就算跑的是旧页面也不会突然读不懂。
    """
    env = {"v": 1, "kind": kind, "pin": pin, "ts": int(time.time())}
    if gz:
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        env["gz"] = base64.b64encode(gzip.compress(raw.encode("utf-8"))).decode("ascii")
    else:
        env["body"] = body
    return json.dumps(env, ensure_ascii=False, separators=(",", ":"))


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
    if "gz" in msg and "body" not in msg:
        try:
            msg["body"] = json.loads(
                gzip.decompress(base64.b64decode(msg["gz"])).decode("utf-8"))
        except Exception:  # noqa: BLE001 - 坏包当没看见，和 JSON 解不开一个待遇
            log.warning("信箱里那条消息解压失败，丢弃", exc_info=True)
            return None
    return msg


# ---------- 心跳（ToDesk 式在线状态） ----------
#
# 用户 2026-09-02：「像 ToDesk 一样，打开就是在线或离线，不用手动刷新，
# 能不能不用轮询实现？手动刷新作为兜底选项而不是经常行为。」
#
# 做法：页面打开时发一条「我在看」(watch)，机器在这 10 分钟租约内每 30 秒
# 往 <topic>-hb 跳一次；没人看就一跳不跳。页面挂 SSE 实时收，心跳一到
# 翻「开机」，收到 bye（服务优雅停止）秒翻「关机」，硬断电靠 90 秒超时。
# 页面自己不轮询——只有一条长连接和本地计时。
#
# 为什么不能盲跳：ntfy.sh 匿名档**每个 IP 每天 250 条**（2026-09-02 查
# /v1/account 证实）。60 秒盲跳一天 270 条，会把状态推送和指令应答一起
# 挡在门外。所以：有人看才跳，且一天最多 HB_DAILY_CAP 跳，超过退到 5 分钟。

HEARTBEAT_SEC = 30       # 有人看时的间隔
WATCH_LEASE_SEC = 600    # 一条「我在看」管 10 分钟；页面在前台会续
HB_DAILY_CAP = 150       # 一天最多这么多跳，给状态/指令留足额度
HB_SLOW_SEC = 300        # 超过上限后的间隔


class Heartbeat:
    """有人看才跳。post 可注入，测试不碰网络。"""

    def __init__(self, topic: str, state_dir: Path, post=None):
        self.topic = (topic or "").strip()
        self.url = f"{NTFY}/{self.topic}-hb"
        self.state_dir = Path(state_dir)
        self._lease = 0.0
        self._kick = threading.Event()
        self._post = post or self._http_post

    def _http_post(self, payload: bytes, title: str) -> None:
        req = urllib.request.Request(self.url, data=payload, method="POST",
                                     headers={"User-Agent": _UA, "Title": title})
        urllib.request.urlopen(req, timeout=10).read()

    # -- 租约 --
    def watch(self) -> None:
        """页面说「我在看」：续 10 分钟，并立刻跳一次让它秒知道在线。"""
        self._lease = time.time() + WATCH_LEASE_SEC
        self._kick.set()

    def watched(self) -> bool:
        return time.time() < self._lease

    # -- 当天计数（防吃光 ntfy 额度） --
    def _count_file(self) -> Path:
        return self.state_dir / f"hb-{time.strftime('%Y-%m-%d')}.txt"

    def sent_today(self) -> int:
        try:
            return int(self._count_file().read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return 0

    def _bump(self) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self._count_file().write_text(str(self.sent_today() + 1), encoding="utf-8")
        except OSError:
            pass

    def interval(self) -> int:
        return HEARTBEAT_SEC if self.sent_today() < HB_DAILY_CAP else HB_SLOW_SEC

    def beat(self) -> bool:
        try:
            self._post(b"hb", "hb")
        except Exception:  # noqa: BLE001 - 心跳失败本身就是信息，不告警
            log.debug("心跳没发出去", exc_info=True)
            return False
        self._bump()
        return True

    def bye(self) -> None:
        try:
            self._post(b"bye", "bye")
            log.info("📱 已发下线心跳（bye）")
        except Exception:  # noqa: BLE001
            pass

    def loop(self, stop) -> None:
        """后台线程主体。stop() 返回真就退出，退出前发 bye。"""
        while not stop():
            wait = 5
            if self.watched():
                self.beat()
                wait = self.interval()
            # 1 秒一片地等：停服务要能马上退出，watch() 到了要能马上跳
            for _ in range(wait):
                if stop() or self._kick.is_set():
                    break
                time.sleep(1)
            self._kick.clear()
        self.bye()


class Mailbox:
    """一个信箱。取指令、发状态、挂长连接。"""

    def __init__(self, topic: str, pin: str, state_dir: Path):
        self.topic = (topic or "").strip()
        self.pin = (pin or "").strip()
        self.state_dir = Path(state_dir)
        self._seen = self._load_seen()
        # 停服务时要能立刻把这条连接掐断。光靠读超时不行：最坏要等满一个
        # 超时周期，而 Windows 的服务停止只给 30 秒宽限——2026-08-31 因此
        # 连着几次卡在 STOP_PENDING，每次白等十分钟。
        self._resp = None

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

    # ntfy 单条消息有大小上限，超了会被**截断**——截断的 JSON 在手机上
    # 解析失败，表现是「永远读不到最新状态、判成关机中」，而发送这头
    # 一切正常。所以发之前自己量，超了就砍掉可有可无的部分并出声。
    # ntfy 的真实上限是 4096 字节。留 200 字节余量够了——3600 太保守，
    # 2026-08-31 加了队列和周本之后就超线，把「明日安排」砍掉了。
    MAX_BODY = 3900

    def publish(self, body: dict, kind: str = "state") -> bool:
        if not self.enabled:
            return False
        data = pack(self.pin, body, kind).encode("utf-8")
        if len(data) > self.MAX_BODY:
            # 先试压缩。砍字段是**功能没了**，压缩只是多花几毫秒。
            packed = pack(self.pin, body, kind, gz=True).encode("utf-8")
            if len(packed) <= self.MAX_BODY:
                log.info("状态 %d 字节超线，压缩后 %d 字节，照发",
                         len(data), len(packed))
                data = packed
        for drop in ("plan", "options"):
            if len(data) <= self.MAX_BODY:
                break
            if drop in body:
                log.warning("状态太大（%d 字节），砍掉「%s」再发", len(data), drop)
                body = {k: v for k, v in body.items() if k != drop}
                data = pack(self.pin, body, kind).encode("utf-8")
        if len(data) > self.MAX_BODY:
            log.error("状态还是太大（%d 字节），手机上会解析失败", len(data))
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

    def close(self) -> None:
        """把挂着的那条连接掐断，让 listen 立刻从阻塞里出来。"""
        r, self._resp = self._resp, None
        if r is not None:
            try:
                r.close()
            except Exception:  # noqa: BLE001 - 关不掉也不能拖住停止流程
                log.debug("手机通道关不掉，忽略", exc_info=True)

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
                # **必须带 since**：流式订阅只送「连着的时候」到达的消息，
                # 断线重连那几秒里手机发的刷新会永久丢失——2026-08-31 实测：
                # 机器 03:34:31 之后就再没收到过任何刷新，人在手机上按了没反应。
                # 带上 since，重连时把漏掉的补上；已处理过的靠消息 id 去重，
                # 不会重复执行。
                url = f"{NTFY}/{self.topic}/json?since=10m"
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                # **不许用 timeout=None**：读会无限期阻塞，停服务时这个线程
                # 挂住，服务卡在 STOP_PENDING 起不来——2026-08-31 撞过一次，
                # 只能强杀进程。ntfy 每 45 秒会发一次 keepalive，
                # 90 秒的读超时永远不会误伤，超时了外层重连就是。
                with urllib.request.urlopen(req, timeout=90) as r:
                    self._resp = r
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


# AUTO-MAS 自己的界面是全中文的，标注就在它的 models 里：每个 ConfigItem
# 上面一行 `## 中文名`，合法取值在 OptionsValidator([...]) 里。
# 用户 2026-08-31：「一定是有中文解释的因为 ui 界面就是全中文，
# 只不过你没找到在哪里标注的而已。」——他是对的，我先前搜漏了。
# 从这里读，不自己译：上游改了名字这边跟着变，硬编码早晚对不上。
_CFG_ITEM = re.compile(
    r'##\s*(?P<label>[^\n]+)\n\s*self\.\w+\s*=\s*ConfigItem\(\s*'
    r'"(?P<sec>\w+)"\s*,\s*"(?P<key>\w+)"\s*,(?P<rest>.*?)\n\s*\)',
    re.S)
_OPTS = re.compile(r"OptionsValidator\(\s*\[(.*?)\]", re.S)
_QUOTED = re.compile(r"""["']([^"']+)["']""")


# 一个脚本一个 class：MaaUserConfig / MaaEndUserConfig / OkwwUserConfig。
# 按「节.键」全局匹配会让同名字段串标签，所以按 class 分开。
_CLASS = re.compile(r"^class\s+(\w+)", re.M)
_CLASS_OF = {"MaaUserConfig": "MAA", "MaaEndUserConfig": "MaaEnd",
             "OkwwUserConfig": "OK-WW"}


def _mas_labels(automas_dir) -> dict:
    """各脚本的中文名和合法取值。`{"MAA": {"Info.Stage": {...}}}`"""
    out: dict = {"MAA": {}, "MaaEnd": {}, "OK-WW": {}}
    if not automas_dir:
        return out
    models = Path(automas_dir) / "app" / "models"
    if not models.is_dir():
        log.warning("找不到 AUTO-MAS 的 models 目录，手机上只能显示英文字段名")
        return out
    for f in sorted(models.glob("*.py")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        marks = list(_CLASS.finditer(text))
        for i, cm in enumerate(marks):
            game = _CLASS_OF.get(cm.group(1))
            if not game:
                continue
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            for m in _CFG_ITEM.finditer(text[cm.end():end]):
                o = _OPTS.search(m.group("rest"))
                out[game][f'{m.group("sec")}.{m.group("key")}'] = {
                    "label": m.group("label").strip(),
                    "options": _QUOTED.findall(o.group(1)) if o else None,
                }
    return out


# 手机上真正会显示的那些项。**只发这些**：把 154 条标注全塞进去，
# 单条消息会超过 ntfy 的大小上限被截断，页面 JSON.parse 直接失败，
# 于是永远读不到最新状态、判成「关机中」——2026-08-31 就是这么坏的。
SHOWN = (
    "Info.Stage", "Info.StageMode", "Info.MedicineNumb", "Info.SeriesNumb",
    "Info.Annihilation", "Task.IfFight", "Task.IfActivityFirst",
    "Task.ActivityStageIndex", "Task.ActivityMedicineNumb",
    "Task.IfSanity", "Task.IfAutoUseSpMedication", "Task.SanityTaskType",
    "Task.AutoEssenceSpecifiedLocation",
    "Task.WhichToFarm", "Task.WhichTacetSuppressionToFarm",
    "Task.WhichForgeryChallengeToFarm", "Task.MaterialSelection",
    "Task.FarmNightmareNestForDailyEcho", "Task.TaskIndex",
)


def _options(cfg) -> dict:
    """各游戏可选项。取不到就不给，页面那一项退回文本框。"""
    out: dict = {"MAA": {}, "MaaEnd": {}, "OK-WW": {}}
    try:
        names: dict = {}
        for game, items in _mas_labels(getattr(cfg, "automas_dir", None)).items():
            for path, info in items.items():
                if path not in SHOWN:
                    continue
                names[f"{game}|{path}"] = info["label"]
                # 2026-09-04 起只带中文字段名，不带候选列表：留下的六项里
                # 只有「剿灭」是选择题，而它已经改成只读显示（每周自己开关，
                # 不该在手机上点）。那张关卡表一个人就占一千多字节，
                # 整包会顶到 ntfy 的上限去。
        out["_labels"] = names
    except Exception:  # noqa: BLE001
        log.warning("AUTO-MAS 的中文标注读不到", exc_info=True)
    return out


def state_payload(cfg, state_dir: Path) -> dict:
    """手机上显示的那一份。和 config-check 读的是同一份代码（snapshot.py）。"""
    from . import modes, plan, snapshot  # noqa: PLC0415 - 避免导入环
    out: dict = {"at": int(time.time())}
    # 只发手机上会显示的那三段。整份快照还带着 OK-WW 的四个配置文件、
    # 队列表和进程列表，加起来会把单条消息顶过 ntfy 的大小上限，
    # 截断之后手机那头解析失败——表现是「永远显示关机中」。
    # 只发手机上会显示的那些键。整份快照塞不进单条消息（见 Mailbox.MAX_BODY）。
    keep = {k.split(".", 1)[1] for k in SHOWN} | {"关卡", "理智药", "剿灭",
            "作战开关", "活动关优先", "活动关序号"}
    try:
        full = snapshot.read()
        # 只剩明日方舟：另外两个游戏的 MAS 字段不下发，见 mastercfg
        out["config"] = {
            sec: {k: v for k, v in (vals or {}).items() if k in keep}
            for sec, vals in full.items() if sec == "MAA"}
        out["run"] = {"服务": full.get("ark-relay"),
                      "在跑的": [n for n, on in (full.get("进程") or {}).items() if on]}
        out["queues"] = [{"名": n, **v} for n, v in (full.get("队列") or {}).items()]
    except Exception as exc:  # noqa: BLE001
        out["config"] = {"_错误": f"{type(exc).__name__}: {exc}"}
    try:
        from . import weeklyboss  # noqa: PLC0415
        out["relay"] = {
            "调试模式": modes.debug_until(state_dir) or "",
            "下次别关机": modes.skip_armed(state_dir),
            "周本": weeklyboss.WeeklyBossGate(state_dir,
                                              getattr(cfg, "automas_dir", None)
                                              ).settings(),
        }
    except Exception:  # noqa: BLE001
        out["relay"] = {}
    try:
        out["options"] = _options(cfg)
    except Exception:  # noqa: BLE001
        out["options"] = {}
    # 终末地和鸣潮改的是脚本自己那份配置，不是 MAS——那边改了不生效。
    try:
        from . import mastercfg  # noqa: PLC0415
        out["master"] = {
            "MaaEnd": mastercfg.read_maaend(getattr(cfg, "automas_dir", None),
                                            getattr(cfg, "maaend_dir", None)),
            "OK-WW": mastercfg.read_okww(getattr(cfg, "automas_dir", None),
                                         getattr(cfg, "okww_dir", None)),
        }
    except Exception:  # noqa: BLE001
        log.warning("母本配置读不到", exc_info=True)
        out["master"] = {}
    try:
        out["plan"] = plan.next_plan(cfg.automas_dir)
    except Exception:  # noqa: BLE001
        out["plan"] = ""
    return out
