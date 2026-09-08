"""推送通道自己那一层：一个挂了不能拖垮其余，失败原因必须回到调用方手里。

`tests/test_notify_routing.py` 钉的是 `Notifier` 的**路由**（日常只走一处、报警全发），
它底下挂的是假通道。这个文件钉的是**真通道类和它们的 HTTP 契约**——notify.py 的
35 个函数里 22 个从来没被执行过，而这条路是「出了事你会不会知道」的唯一通道。

这里防的损失，每一条都实际发生过（docs/PITFALLS.md）：

* 企业微信因 60020（家宽公网 IP 一转就不在可信 IP 名单里）长期不可用。那天
  `send()` 只要有一个通道报错就算失败，于是告警每 30 秒重推一次、`mark_report_sent`
  永远不被调用、日报整夜重发，而关机要等日报——**机器一夜没关**。
* 从日本连 sctapi.ftqq.com 偶尔在 TLS 握手中超时，下一次一秒就通。告警是一次性的、
  没人补发，所以**传输失败必须重试**；而 HTTP 状态码是服务器的回答，403 问一百遍还是
  403，必须立刻抛出去换下一个端点或通道，不许干等退避。
* 企业微信文本上限是 2048 **字节**不是字数：自建应用悄悄截断（日报尾巴没了），群机器人
  直接整条拒收——而正文是原样重试的，于是模型写出的一个超长段落能让日报每一次重试都
  失败，关机路径就在那儿等一整夜。
* 通道报错时把原因吞掉，调用方就没法判断要不要重试、更没法把「这条通道坏了」说给人听。

所有 HTTP 都是假的：`urllib.request.urlopen` 在本进程里被换掉，没挂假响应的 URL 直接
断言失败，任何一次真的联网都会当场变红。
"""
import json
import os
import sys
import types
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP),
                  SERVERCHAN_KEY="", WECOM_CORPID="", WECOM_BOT_URL="",
                  ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import notify                 # noqa: E402
from ark_relay.config import Config          # noqa: E402
from ark_relay.notify import (               # noqa: E402
    Notifier, ServerChan, WeCom, WeComBot, _hint, _image_bytes_for_wecom,
)

fails = []


def _short(v):
    # 这个文件里有整段日报那么长的值，原样打出来会把屏幕刷满，反而看不见哪条红了。
    text = repr(v)
    return text if len(text) <= 120 else text[:117] + "..."


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}"
          + ("" if ok else f": got {_short(got)}, want {_short(want)}"))
    if not ok:
        fails.append(label)


# ---------------------------------------------------------------- fake HTTP
# Replaces urlopen for this process only. An unrouted URL is a hard failure:
# a test that quietly reaches the real sctapi.ftqq.com is worse than no test.

class _Resp:
    def __init__(self, text: str):
        self._b = text.encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


ROUTES: list = []       # [(url fragment, handler)]
CALLS: list = []        # [(url, decoded request body)]


def route(fragment, handler):
    ROUTES.append((fragment, handler))


def reset(*routes):
    ROUTES.clear()
    CALLS.clear()
    for frag, handler in routes:
        route(frag, handler)


def once(*results):
    """A handler that hands back one result per call, then repeats the last."""
    box = list(results)

    def handler(_req):
        return box.pop(0) if len(box) > 1 else box[0]
    return handler


def fake_urlopen(req, timeout=None):
    url = req if isinstance(req, str) else req.full_url
    body = ""
    if not isinstance(req, str) and req.data:
        body = req.data.decode("utf-8", "replace")
    CALLS.append((url, body))
    for frag, handler in ROUTES:
        if frag in url:
            out = handler(req)
            if isinstance(out, BaseException):
                raise out
            return _Resp(json.dumps(out) if isinstance(out, dict) else out)
    raise AssertionError(f"没挂假响应的 URL，测试差点真的联网: {url}")


urllib.request.urlopen = fake_urlopen


class _Clock:
    """Stand-in for the `time` module inside notify: records the backoff sleeps
    instead of actually waiting, so a 3-attempt retry test stays instant."""

    def __init__(self):
        self.slept: list = []
        self.now = 1_000_000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)


CLOCK = _Clock()
notify.time = CLOCK


def posted(fragment):
    return [b for u, b in CALLS if fragment in u]


def urls(fragment=""):
    return [u for u, _ in CALLS if fragment in u]


OK = {"errcode": 0, "errmsg": "ok"}
TOKEN = {"errcode": 0, "access_token": "tok-1", "expires_in": 7200}


def transport_error(_req):
    return urllib.error.URLError("TLS handshake timed out")


def http_403(_req):
    return urllib.error.HTTPError("https://x/", 403, "Forbidden", {}, None)


# --------------------------------------------------- _post: 什么该重试什么不该
print("[传输失败要重试：告警是一次性的，没人补发]")
reset(("fake.test", once(transport_error(None), transport_error(None), OK)))
CLOCK.slept.clear()
check("第三次通了就算成功", notify._post_json("https://fake.test/send", {}), OK)
check("一共试了 3 次", len(CALLS), 3)
check("退避了 2 次", CLOCK.slept, [1.5, 3.0])

print("\n[三次都失败：把传输失败的原因抛给调用方，不许悄悄返回空]")
reset(("fake.test", once(transport_error(None))))
try:
    notify._post_json("https://fake.test/send", {})
    check("必须抛异常", "没抛", "抛了")
except Exception as exc:                      # noqa: BLE001
    check("抛的是传输失败本身", "TLS handshake timed out" in str(exc), True)
check("试满 3 次才放弃", len(CALLS), 3)

print("\n[HTTP 状态码是服务器的回答，不是传输失败：立刻抛，不许干等退避]")
reset(("fake.test", once(http_403(None))))
CLOCK.slept.clear()
try:
    notify._post_form("https://fake.test/send", {"a": "b"})
    check("必须抛异常", "没抛", "抛了")
except urllib.error.HTTPError as exc:
    check("原样把状态码抛出去", exc.code, 403)
check("只试了 1 次", len(CALLS), 1)
check("一秒都没等", CLOCK.slept, [])

# ------------------------------------------------------------- Server酱
print("\n[Server酱：sctp 是三代，多一个 uid 端点；SCT 是 Turbo，只有一个]")
check("SCT 只有一个端点",
      ServerChan(types.SimpleNamespace(serverchan_key="SCTabc"))._endpoints(),
      ["https://sctapi.ftqq.com/SCTabc.send"])
sctp = ServerChan(types.SimpleNamespace(serverchan_key="sctp123t456"))
check("sctp 两个端点，sctapi 在前",
      [u.split("/")[2] for u in sctp._endpoints()],
      ["sctapi.ftqq.com", "123.push.ft07.com"])

print("\n[第一个端点挂了就换第二个，一样算送达]")
reset(("sctapi.ftqq.com", once(http_403(None))),
      ("push.ft07.com", once({"code": 0})))
sctp.send_text("⚠️ OK-WW 失败", "正文")
check("两个端点都试过", len(CALLS), 2)

print("\n[两个都失败：抛出来的原因里两个主机、两条理由都在]")
reset(("sctapi.ftqq.com", once(http_403(None))),
      ("push.ft07.com", once({"code": 40001, "message": "bad pushkey"})))
try:
    sctp.send_text("⚠️ 失败", "正文")
    check("必须抛异常", "没抛", "抛了")
except RuntimeError as exc:
    msg = str(exc)
    check("第一个主机在里面", "sctapi.ftqq.com" in msg, True)
    check("第二个主机也在", "123.push.ft07.com" in msg, True)
    check("403 这条理由没被吞", "403" in msg, True)
    check("40001 这条理由也没被吞", "40001" in msg, True)

print("\n[code 非 0 不许当成功：0 只代表 API 收下了，本来就不保证送达]")
reset(("sctapi.ftqq.com", once({"code": 40001, "message": "bad pushkey"})))
sct = ServerChan(types.SimpleNamespace(serverchan_key="SCTabc"))
try:
    sct.send_text("标题", "正文")
    check("必须抛异常", "没抛", "抛了")
except RuntimeError as exc:
    check("原因里带着返回码", "40001" in str(exc), True)

print("\n[正文换行要加倍：Server酱 按 Markdown 渲染，单换行会被吃掉，日报糊成一坨]")
reset(("sctapi.ftqq.com", once({"code": 0})))
sct.send_text("标" * 200, "第一行\n第二行")
form = urllib.parse.parse_qs(posted("sctapi.ftqq.com")[0])
check("换行变成空行", form["desp"][0], "第一行\n\n第二行")
check("标题截到 100 字", len(form["title"][0]), 100)

# ------------------------------------------- 企业微信 2048 字节上限的切分
print("\n[短消息原样一条，不加「（1/1）」这种噪声]")
check("原样返回", WeCom._split("今天全绿"), ["今天全绿"])

# 企业微信 text 消息的真实硬上限。`_LIMIT` 比它小，留出「（1/3）」那个序号的位置——
# 序号是**打包之后**才贴上去的，所以要验的是成品，不是打包时用的那个数。
API_CAP = 2048


def widest(parts):
    return max(len(p.encode("utf-8")) for p in parts)


print("\n[中文长日报：按 utf-8 **字节**算上限（按字数算，中文会整段漏过去）]")
# 这一段是专门挑的：字数**没到**上限，字节数早就超了。判据写成 len(text) 的话，
# 它会被原样当成一条发出去——自建应用悄悄截断尾巴，群机器人整条拒收。
long_zh = "\n".join(f"第 {i} 行：明日方舟今天刷了理智，掉落记在账上" for i in range(40))
check("字数没到 1800，字节数超过 2048",
      (len(long_zh) <= WeCom._LIMIT, len(long_zh.encode("utf-8")) > API_CAP),
      (True, True))
parts = WeCom._split(long_zh)
check("确实切开了", len(parts) > 1, True)
check("每段都进得了 2048 字节", widest(parts) <= API_CAP, True)
check("带序号", parts[0].startswith(f"（1/{len(parts)}）"), True)
rejoined = "\n".join(p.split("\n", 1)[1] for p in parts)
check("一行不丢、一行不改", rejoined, long_zh)

print("\n[没有换行的超长单行也必须切得开——群机器人是整条拒收，重试一万次也过不去]")
one_line = "刷" * 3000
parts = WeCom._split(one_line)
check("切开了", len(parts) > 1, True)
check("每段都进得了 2048 字节", widest(parts) <= API_CAP, True)
check("一个字都没丢",
      "".join(p.split("\n", 1)[1].replace("\n", "") for p in parts), one_line)
check("_hard_wrap 按字节切，不按字数",
      max(len(c.encode("utf-8")) for c in WeCom._hard_wrap(one_line, 50)) <= 50,
      True)

# ------------------------------------------------------ 企业微信自建应用
WECOM_CFG = types.SimpleNamespace(
    wecom_corpid="cid", wecom_secret="sec", wecom_agentid="1000002",
    wecom_touser="@all")

print("\n[发送要带上 token；errcode 非 0 抛出，错误码必须留在原因里]")
reset(("gettoken", once(TOKEN)),
      ("message/send", once({"errcode": 60020,
                             "errmsg": "not allow to access from your ip"})))
w = WeCom(WECOM_CFG)
try:
    w.send_text("⚠️ 失败")
    check("必须抛异常", "没抛", "抛了")
except RuntimeError as exc:
    check("原因里有 60020", "60020" in str(exc), True)
check("请求带上了 token", "access_token=tok-1" in urls("message/send")[0], True)

print("\n[token 缓存住：连发两条只换一次 token]")
reset(("gettoken", once(TOKEN)), ("message/send", once(OK)))
w2 = WeCom(WECOM_CFG)
w2.send_text("第一条")
w2.send_text("第二条")
check("只取了一次 token", len(urls("gettoken")), 1)
check("两条都发出去了", len(urls("message/send")), 2)

print("\n[取 token 本身失败就抛，不许拿着空 token 去发]")
# message/send 也挂上假响应：万一真的被调用了，要红在「没有硬着头皮去发」这条上，
# 而不是红成一个看不懂的「URL 没挂假响应」。
reset(("gettoken", once({"errcode": 40001, "errmsg": "invalid secret",
                         "access_token": ""})),
      ("message/send", once(OK)))
try:
    WeCom(WECOM_CFG).send_text("正文")
    check("必须抛异常", "没抛", "抛了")
except RuntimeError as exc:
    check("说清是 gettoken 失败", "gettoken" in str(exc) and "40001" in str(exc), True)
check("没有硬着头皮去发", urls("message/send"), [])

print("\n[60020 要给出手机上照做就能修好的一句话，别的错误不瞎给建议]")
tip = _hint("企业微信", "企业微信发送失败: 60020 not allow to access from your ip")
check("指到企业可信IP", "企业可信IP" in tip, True)
check("别的错误码不编建议", _hint("企业微信", "40014 invalid access_token"), "")
check("别的通道不套用", _hint("Server酱", "60020 whatever"), "")

# ------------------------------------------------------------ 群机器人
print("\n[群机器人：errcode 非 0 抛出；它的字节上限比自建应用更严]")
check("上限 1800", WeComBot._LIMIT, 1800)
reset(("qyapi.weixin.qq.com/cgi-bin/webhook",
       once({"errcode": 93000, "errmsg": "invalid webhook url"})))
bot = WeComBot(types.SimpleNamespace(
    wecom_bot_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k"))
try:
    bot.send_text("正文")
    check("必须抛异常", "没抛", "抛了")
except RuntimeError as exc:
    check("原因里有 93000", "93000" in str(exc), True)

print("\n[超长日报按段发出去，不是一整条撞上限被拒]")
reset(("webhook", once(OK)))
bot.send_text("刷" * 3000)
check("拆成了多条", len(posted("webhook")) > 1, True)
check("每条正文都进得了 2048 字节",
      max(len(json.loads(b)["text"]["content"].encode("utf-8"))
          for b in posted("webhook")) <= API_CAP, True)

# ------------------------------------ Notifier：一个挂了不能拖垮其余
print("\n[企业微信长期 60020，Server酱 照发——真通道走完整条 HTTP 路径]")
cfg = Config()
cfg.serverchan_key = "SCTabc"
cfg.wecom_corpid, cfg.wecom_secret = "cid", "sec"
cfg.wecom_agentid, cfg.wecom_touser = "1000002", "@all"
cfg.wecom_bot_url = ""
reset(("gettoken", once(TOKEN)),
      ("message/send", once({"errcode": 60020, "errmsg": "not allow from ip"})),
      ("sctapi.ftqq.com", once({"code": 0})))
n = Notifier(cfg)
check("两个通道都算配好了", n.channels, ["企业微信", "Server酱"])
check("算送达（返回空 = 调用方可以不再重推）", n.send("⚠️ OK-WW 失败", "正文", alert=True), [])
titles = [urllib.parse.parse_qs(b)["title"][0] for b in posted("sctapi.ftqq.com")]
check("Server酱 真的收到了那条告警", "⚠️ OK-WW 失败" in titles, True)
check("坏掉的通道被单独通报出去",
      any("推送通道故障" in t for t in titles), True)

print("\n[全挂：返回的每一项是「通道名: 原因」，调用方靠它决定要不要重试]")
reset(("gettoken", once(TOKEN)),
      ("message/send", once({"errcode": 60020, "errmsg": "not allow from ip"})),
      ("sctapi.ftqq.com", once({"code": 40001, "message": "bad pushkey"})))
n2 = Notifier(cfg)
errs = n2.send("⚠️ OK-WW 失败", "正文", alert=True)
check("两个通道各有一条原因", len(errs), 2)
check("企业微信那条带着 60020",
      any(e.startswith("企业微信: ") and "60020" in e for e in errs), True)
check("Server酱 那条带着 40001",
      any(e.startswith("Server酱: ") and "40001" in e for e in errs), True)

print("\n[群通知没配机器人时必须报错，不能返回空当作发过了]")
# 卡池播报靠这个非空返回值决定「先别落记号，下轮再播」；返回空的话明天开的卡池就永远
# 不会有人知道。
cfg_nobot = Config()
cfg_nobot.serverchan_key = "SCTabc"
reset(("sctapi.ftqq.com", once({"code": 0})))
check("说清是机器人没开", Notifier(cfg_nobot).send_group("📣 明天开卡池", "正文"),
      ["企业微信机器人没开"])
check("绝不偷偷改走 Server酱", posted("sctapi.ftqq.com"), [])

print("\n[发图出错要把原因返回，不许抛——它跑在日报发出之后，抛出去会把那一轮带走]")
check("没配自建应用时说清楚", Notifier(cfg_nobot).send_image(Path("/nonexistent.png")),
      ["企业微信未配置，无法发图"])
check("没配机器人时说清楚",
      Notifier(cfg_nobot).send_group_image(Path("/nonexistent.png")),
      ["群机器人未配置"])
cfg_bot = Config()
cfg_bot.wecom_bot_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k"
reset(("webhook", once({"errcode": 40006, "errmsg": "invalid media size"})))
got = Notifier(cfg_bot).send_group_image(TMP / "shot.png")
check("发图失败返回原因而不是抛出", len(got), 1)
check("原因里有真东西", got[0] != "", True)

print("\n[一个通道都没配：配置闸门挡在启动之前，send 自己也不许报绿]")
blank = Config()
check("闸门认得出「没有任何推送渠道」",
      any("推送渠道" in p for p in blank.validate()), True)
# 2026-09-08 补测试时发现的不对称：send_group 早就兜住了这一格，send 没有——
# 一个通道都没配时 failed 是空的，返回空列表就等于告诉调用方「送到了」。
# 生产上这条路够不到（上面那道配置闸门先拦），但「够不到所以无所谓」错一次就够了。
got = Notifier(blank).send("标题", "正文")
check("没有通道时 send() 必须报「没送到」，不许返回空", got != [], True)
check("原因说的是没配渠道", any("渠道" in x for x in got), True)

# ---------------------------------------------------- 发图前的体积处理
print("\n[超过 2MB 的截图要压下去，否则无音区结算截图整张发不出去]")
from PIL import Image                                        # noqa: E402
big = TMP / "big.png"
Image.frombytes("RGB", (1920, 1080), os.urandom(1920 * 1080 * 3)).save(big, "PNG")
check("原图确实超限", big.stat().st_size > 1_800_000, True)
check("压完在限内", len(_image_bytes_for_wecom(big)) <= 1_800_000, True)
small = TMP / "small.png"
Image.new("RGB", (64, 64), (10, 20, 30)).save(small, "PNG")
check("没超限的原样返回（重编码会让 md5 对不上）",
      _image_bytes_for_wecom(small), small.read_bytes())

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
