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

## 安全

信箱是公开的（ntfy.sh 上一个谁都能读写的主题），所以：

* **指令必须验签**：HMAC-SHA256(PIN)，签名不对直接丢
* **防重放**：每条带时间戳和随机串，超窗或重复的随机串一律丢
* **状态不加密**：机器上没有 cryptography 库，而状态里只有游戏配置
  （刷哪一关、吃几个药），没有任何凭证。真正的防线是信箱名——
  28 位随机串，只存在用户手机里和机器的 .env 里，**不进仓库、不进网页源码**。

指令窗口特意开到 24 小时：机器一天只开两趟，手机上按的指令要能在信箱里
等到下次开机。防重放靠随机串，不靠窗口。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import atomic_write_text

log = logging.getLogger("ark.phone")

NTFY = "https://ntfy.sh"
# 指令能在信箱里等多久。机器一天开两趟，最长间隔约 11 小时半。
MAX_AGE = 24 * 3600
# 记住多少个用过的随机串。一天几条指令，200 个够用好几个月。
NONCE_KEEP = 200
_UA = "ark-relay"


def canon(obj: dict) -> str:
    """签名和验签必须对同一串字节做，所以序列化方式要钉死。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sign(pin: str, payload: dict) -> str:
    return hmac.new(pin.encode("utf-8"), canon(payload).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def pack(pin: str, body: dict, kind: str = "cmd") -> str:
    payload = {"v": 1, "kind": kind, "ts": int(time.time()),
               "nonce": secrets.token_hex(8), "body": body}
    return canon({**payload, "sig": sign(pin, payload)})


def unpack(pin: str, raw: str, *, now: float | None = None,
           seen: "set[str] | None" = None) -> "dict | None":
    """验签＋验时效＋验重放。任何一关不过都返回 None，并说明理由。"""
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log.debug("信箱里有条不是 JSON 的消息，丢弃")
        return None
    if not isinstance(msg, dict) or "sig" not in msg:
        return None
    got = str(msg.pop("sig"))
    want = sign(pin, msg)
    # compare_digest：别用 == 比签名，那会泄漏比较用了多久。
    if not hmac.compare_digest(got, want):
        log.warning("信箱里有条签名不对的消息，已丢弃（有人知道信箱名但不知道 PIN）")
        return None
    ts = msg.get("ts")
    if not isinstance(ts, int):
        return None
    age = (now if now is not None else time.time()) - ts
    if abs(age) > MAX_AGE:
        log.info("信箱里那条指令太老了（%.1f 小时前），丢弃", age / 3600)
        return None
    nonce = str(msg.get("nonce") or "")
    if seen is not None and nonce in seen:
        log.warning("重复的指令随机串，按重放丢弃")
        return None
    if seen is not None:
        seen.add(nonce)
    return msg


class Mailbox:
    """一个信箱。取指令、发状态、挂长连接。"""

    def __init__(self, topic: str, pin: str, state_dir: Path):
        self.topic = (topic or "").strip()
        self.pin = (pin or "").strip()
        self.state_dir = Path(state_dir)
        self._nonces = self._load_nonces()

    @property
    def enabled(self) -> bool:
        return bool(self.topic and self.pin)

    # ---------- 防重放的随机串 ----------

    def _nonce_file(self) -> Path:
        return self.state_dir / "phone-nonces.json"

    def _load_nonces(self) -> "list[str]":
        try:
            data = json.loads(self._nonce_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [str(x) for x in data] if isinstance(data, list) else []

    def _save_nonces(self) -> None:
        try:
            atomic_write_text(self._nonce_file(),
                              json.dumps(self._nonces[-NONCE_KEEP:]))
        except OSError:
            # 记不住随机串最坏是同一条指令被执行两次。指令本身都是幂等或可逆的，
            # 但还是要出声——静默失败是这个项目最高优先级的 bug。
            log.warning("用过的指令随机串存不下来，重放保护可能失效", exc_info=True)

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
        seen = set(self._nonces)
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                env = json.loads(line)
            except json.JSONDecodeError:
                continue
            if env.get("event") != "message":
                continue
            msg = unpack(self.pin, str(env.get("message") or ""), seen=seen)
            if msg and msg.get("kind") == "cmd":
                out.append(msg["body"])
        self._nonces = sorted(seen)
        self._save_nonces()
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
                with urllib.request.urlopen(req, timeout=None) as r:
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
                        seen = set(self._nonces)
                        msg = unpack(self.pin, str(env.get("message") or ""),
                                     seen=seen)
                        if not msg or msg.get("kind") != "cmd":
                            continue
                        self._nonces = sorted(seen)
                        self._save_nonces()
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
