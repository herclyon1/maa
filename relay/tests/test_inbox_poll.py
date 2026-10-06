"""inbox.Inbox：从仓库信箱取指令、判要不要执行、执行完记账。

**为什么补这一个**（2026-09-08 审出来）：手机之外唯一的下指令通道，
决定「这批指令要不要跑、跑几遍」，而它**一行测试都没有**。
这里最要命的三条判断都不出声：

* 版本号**必须严格变大**才执行。CDN 会发几分钟的旧副本，按「不一样就执行」
  会把旧方案再放一遍，机器来回翻。
* 取不到文件和取到了但没有新东西，poll() 都是安静返回——调用方要靠
  `last_fetch_ok` 分辨，才知道该不该重试。「暂停」的指令没下载下来，
  就等于没有这条指令。
* 应用到一半炸了也要**记下版本号**。不记的话，下次开机整批重放：
  skip_today 落到没人指定的那一天，改动重复执行一遍。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import inbox
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


class FakeInbox(inbox.Inbox):
    """不联网：把「取回来的那份 JSON」直接塞进来。"""

    payload = None

    def _fetch_or_none(self):
        return self.payload


def box(payload):
    b = FakeInbox(tmpdir())
    b.payload = payload
    return b


print("[版本号严格变大才执行]")
b = box({"version": 5, "name": "第一批", "commands": []})
ver, msgs = b.poll()
check("第一次收到就执行", ver, 5)
check("推送里带了名字", "第一批" in msgs[0], True)

b.payload = {"version": 5, "name": "同一版", "commands": []}
ver, msgs = b.poll()
check("同一个版本号不重放", msgs, [])
check("版本号没退回去", ver, 5)

b.payload = {"version": 4, "name": "更旧的（CDN 发的旧副本）", "commands": []}
ver, msgs = b.poll()
check("更旧的版本不执行", msgs, [])
check("版本号还是 5", ver, 5)

b.payload = {"version": 6, "name": "第二批", "commands": []}
ver, msgs = b.poll()
check("更新的版本才执行", ver, 6)

print("\n[取不到 ≠ 没有新东西：调用方要能分辨]")
b = box({"version": 9, "commands": []})
b.poll()
check("取到了", b.last_fetch_ok, True)
b.payload = None
ver, msgs = b.poll()
check("取不到时说取不到", b.last_fetch_ok, False)
check("取不到时不动版本号", ver, 9)
check("取不到时不推送", msgs, [])

print("\n[文件本身不成形要拒绝，而且不能记账]")
b = box({"version": "不是整数", "commands": []})
ver, msgs = b.poll()
check("版本号不是整数 → 忽略", (ver, msgs), (0, []))
b.payload = {"version": 3, "commands": "不是数组"}
ver, msgs = b.poll()
check("commands 不是数组 → 忽略", (ver, msgs), (0, []))
check("忽略之后版本号仍是 0（没记账）", b.applied_version, 0)

print("\n[应用中途炸了：要说清楚，而且必须记账，不许下次开机整批重放]")
b = box({"version": 11, "name": "会炸的一批", "commands": [{"action": "queue"}]})
b._apply = lambda cmds: (_ for _ in ()).throw(OSError("盘满了"))
ver, msgs = b.poll()
check("版本号照样记下", b.applied_version, 11)
check("说了是中途出错", any("应用中途出错" in m for m in msgs), True)
check("说了这批指令不会再执行一遍", any("不会再执行一遍" in m for m in msgs), True)

print("\n[记账落在 state.json 里，换一个实例也读得到]")
d = tmpdir()
b1 = FakeInbox(d)
b1.payload = {"version": 21, "commands": []}
b1.poll()
b2 = FakeInbox(d)
check("另一个实例读到同一个版本号", b2.applied_version, 21)
saved = json.loads((d / "state.json").read_text(encoding="utf-8"))
check("存在 queues/inbox_version 里", saved["queues"]["inbox_version"], "21")

print("\n[用户写的 note 要原样出现在推送正文里]")
b = box({"version": 31, "name": "改基质地点", "note": "换成清波寨，VFTheHub 刷不出来",
         "commands": []})
_, msgs = b.poll()
body = "\n".join(msgs)
check("note 在正文里", "换成清波寨" in body, True)
check("名字在标题里", "改基质地点" in msgs[0], True)

print("\n[没有 maaend/automas 路径时，明说跳过而不是假装做了]")
b = box({"version": 41, "commands": [
    {"action": "maaend_option", "task": "T", "option": "O", "value": True},
    {"action": "queue", "name": "早班", "enabled": True},
    {"action": "sanity_plan", "tab": "x"},
]})
_, msgs = b.poll()
body = "\n".join(msgs)
check("终末地那条说了跳过", "✗ 终末地：找不到安装路径" in body, True)
check("队列那条说了跳过", "✗ 队列：找不到 AUTO-MAS 目录" in body, True)
check("理智方案那条说了跳过", "✗ 理智方案：找不到 AUTO-MAS 目录" in body, True)

print("\n[终末地选项写 AUTO-MAS 母本：有安装路径没有 AUTO-MAS 目录也要明说跳过]")
# 2026-09-30: MaaEnd's own config/mxu-MaaEnd.json is overwritten from the
# master before every run, so the batch must go to the master or nowhere.
d = tmpdir()
b = FakeInbox(d, maaend_dir=d / "maaend")
b.payload = {"version": 42, "commands": [
    {"action": "maaend_option", "task": "T", "option": "O", "value": True}]}
_, msgs = b.poll()
check("没有 AUTO-MAS 目录 → 终末地那条说了跳过",
      "✗ 终末地：找不到 AUTO-MAS 目录" in "\n".join(msgs), True)

d = tmpdir()
mae = d / "maaend"
(mae / "tasks").mkdir(parents=True)
(mae / "config").mkdir()
(mae / "config" / "mxu-MaaEnd.json").write_text('{"own": true}', encoding="utf-8")
mfile = d / "automas" / "data" / "sid1" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
mfile.parent.mkdir(parents=True)
mfile.write_text(json.dumps({"instances": [{"tasks": [{"taskName": "T", "optionValues": {
    "O": {"type": "switch", "value": False}}}]}]}), encoding="utf-8")
b = FakeInbox(d / "state", maaend_dir=mae, automas_dir=d / "automas")
b.payload = {"version": 43, "commands": [
    {"action": "maaend_option", "task": "T", "option": "O", "value": True}]}
_, msgs = b.poll()
got = json.loads(mfile.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["optionValues"]["O"]
check("改的是母本", got["value"], True)
check("MaaEnd 自己那份没动",
      (mae / "config" / "mxu-MaaEnd.json").read_text(encoding="utf-8"), '{"own": true}')
check("备份放在中继自己的状态目录", len(list((d / "state" / "maaend-backups").glob("*.bak-*"))), 1)
check("回报是成功", any(m.startswith("✅ 终末地：") for m in msgs), True)

# ---- A stale configured address must fall back to the built-in one ----
# 2026-09-08 I deleted inbox/todo.json while the machine's .env still pointed at
# it. Every order after that 404-ed on all four doors and only the relay's own
# log knew. The command channel must not die over one stale line in .env.
_calls = []
def _fake_fetch(url, *a, **k):
    _calls.append(url)
    return None if "todo.json" in url else {"version": 5, "commands": [], "name": "x"}
_real_fetch = inbox._fetch
inbox._fetch = _fake_fetch
try:
    _ib = inbox.Inbox(tmpdir(), "https://raw.githubusercontent.com/herclyon1/maa/main/inbox/todo.json")
    _got = _ib._fetch_or_none()
    check("过期地址取不到时退回内置地址", _got is not None and _got.get("version"), 5)
    check("先试了配置的，再试内置的", [("todo.json" in u) for u in _calls], [True, False])
    check("之后直接用内置地址", _ib.url, inbox.DEFAULT_URL)
    _calls.clear()
    _ib2 = inbox.Inbox(tmpdir(), inbox.DEFAULT_URL)
    _ib2._fetch_or_none()
    check("本来就是内置地址时不重复试", len(_calls), 1)
finally:
    inbox._fetch = _real_fetch

# ---- A round in which no door answered, then a later round that got it ----
# The user, 2026-10-06 05:07: 「报错后自己好了的，只进日报、不进群」 - recovered on the
# retry: one WARNING marked errwatch.recovered() (daily report only); every
# round failing: a plain WARNING (pushed).
import logging  # noqa: E402
from ark_relay import errwatch  # noqa: E402


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.got = []

    def emit(self, record):
        if record.levelno >= logging.WARNING:
            self.got.append((record.getMessage(), bool(getattr(record, errwatch.RECOVERED, False))))


_lines = _Lines()
inbox.log.addHandler(_lines)
_real_once, _real_sleep = inbox._fetch_once, inbox.time.sleep
inbox.time.sleep = lambda s: None
_answers: list = []


def _fake_once(url, timeout=20, errors=None):
    got = _answers.pop(0) if _answers else None
    if got is None and errors is not None:
        errors.append(f"{inbox._netloc(url)}: timed out")
    return got


print("\n[a round with no door answering, then a later round got it: daily report only]")
inbox._fetch_once = _fake_once
_real_cos_client = inbox._cos_client
inbox._cos_client = lambda: None     # GitHub doors only in this section
try:
    doors = len(inbox._alternates(inbox.DEFAULT_URL))
    _answers[:] = [None] * doors + [{"version": 7, "commands": []}] + [None] * (doors - 1)
    _lines.got.clear()
    got = inbox._fetch(inbox.DEFAULT_URL)
    check("round 1 no door, round 2 got it", (got or {}).get("version"), 7)
    check("one WARNING, marked recovered (daily report only)", [r for _, r in _lines.got], [True])
    check("it says which round got it, plain first line",
          [m.splitlines()[0] for m, _ in _lines.got], ["待办文件前 1 轮一扇门都没取到，第 2 轮取到了"])
    _answers[:] = []
    _lines.got.clear()
    check("every round fails: None", inbox._fetch(inbox.DEFAULT_URL), None)
    check("a plain WARNING (pushed), nothing marked recovered",
          [("一扇门都没取到（试了" in m, r) for m, r in _lines.got], [(True, False)])
    _answers[:] = [{"version": 8, "commands": []}] + [None] * (doors - 1)
    _lines.got.clear()
    inbox._fetch(inbox.DEFAULT_URL)
    check("first round got it (other doors failing is not a fault): nothing said", _lines.got, [])
finally:
    inbox._fetch_once, inbox.time.sleep = _real_once, _real_sleep
    inbox._cos_client = _real_cos_client
    inbox.log.removeHandler(_lines)

# ---- The COS door (2026-10-07) ----
# order.sh writes the file to GitHub and then to COS; jsDelivr caches a branch
# file for up to 12 hours, COS has no cache. COS is asked first, but every door
# is still asked and the highest version wins: a COS that missed a write, or a
# file edited on GitHub by hand, must not hold back a newer copy elsewhere.


class _FakeCos:
    prefix = "relay"
    host = "bucket.cos.ap-shanghai.myqcloud.com"

    def authorization(self, method, key):
        return f"sig {method} {key}"


_cos_answer: list = []
_order: list = []


def _fake_cos_once(cos, timeout=20, errors=None):
    _order.append("cos")
    got = _cos_answer[0] if _cos_answer else None
    if got is None and errors is not None:
        errors.append("cos: timed out")
    return got


def _gh_once(url, timeout=20, errors=None):
    _order.append(inbox._netloc(url))
    return _gh_answer[0]


_gh_answer: list = [None]
inbox.log.addHandler(_lines)
_real_cos_once = inbox._fetch_cos_once
inbox._fetch_cos_once, inbox._fetch_once = _fake_cos_once, _gh_once
inbox._cos_client = lambda: _FakeCos()
inbox.time.sleep = lambda s: None
print("\n[COS door: asked first, highest version of all doors wins]")
try:
    _cos_answer[:], _gh_answer[:], _order[:] = [{"version": 12, "commands": []}], [{"version": 11, "commands": []}], []
    _lines.got.clear()
    check("COS newer than the CDN copies: COS's copy", (inbox._fetch(inbox.DEFAULT_URL) or {}).get("version"), 12)
    check("COS was asked first", _order[:1], ["cos"])
    check("the GitHub doors were still asked", len(_order), 1 + len(inbox._alternates(inbox.DEFAULT_URL)))
    _cos_answer[:], _gh_answer[:] = [{"version": 10, "commands": []}], [{"version": 11, "commands": []}]
    check("GitHub newer (edited by hand, COS never saw it): GitHub's copy",
          (inbox._fetch(inbox.DEFAULT_URL) or {}).get("version"), 11)
    _cos_answer[:], _order[:] = [], []
    check("COS down: the GitHub doors still deliver", (inbox._fetch(inbox.DEFAULT_URL) or {}).get("version"), 11)
    check("COS down while another door answered: nothing said", _lines.got, [])
    _gh_answer[:] = [None]
    _lines.got.clear()
    check("COS and every GitHub door down: None", inbox._fetch(inbox.DEFAULT_URL), None)
    check("the WARNING names the COS door too", any("cos: timed out" in m for m, _ in _lines.got), True)
    inbox._cos_client = lambda: None
    _gh_answer[:], _order[:] = [{"version": 11, "commands": []}], []
    inbox._fetch(inbox.DEFAULT_URL)
    check("COS not configured on the machine: COS not asked", "cos" in _order, False)
finally:
    inbox._fetch_cos_once, inbox._fetch_once = _real_cos_once, _real_once
    inbox._cos_client, inbox.time.sleep = _real_cos_client, _real_sleep
    inbox.log.removeHandler(_lines)

print("\n[COS not configured (no COS_* in the environment): no COS door]")
import os  # noqa: E402

_saved = {k: os.environ.pop(k) for k in ("COS_SECRET_ID", "COS_SECRET_KEY", "COS_BUCKET", "COS_REGION")
          if k in os.environ}
try:
    check("no client", inbox._cos_client(), None)
finally:
    os.environ.update(_saved)

print("\n[the COS door's own request: signed GET of relay/queue/config.json]")
import io  # noqa: E402
import urllib.error  # noqa: E402

_seen: list = []


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen_ok(req, timeout=None):
    _seen.append((req.full_url, req.get_header("Authorization")))
    return _Resp(json.dumps({"version": 2026100701, "commands": []}).encode())


def _urlopen_404(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)


_real_urlopen = inbox.urllib.request.urlopen
try:
    inbox.urllib.request.urlopen = _urlopen_ok
    got = inbox._fetch_cos_once(_FakeCos())
    check("reads the version", (got or {}).get("version"), 2026100701)
    check("object key under relay/ (kept by the lifecycle rule)",
          _seen[0][0], "https://bucket.cos.ap-shanghai.myqcloud.com/relay/queue/config.json")
    check("signed for that key", _seen[0][1], "sig GET relay/queue/config.json")
    inbox.urllib.request.urlopen = _urlopen_404
    errs: list = []
    _lines.got.clear()
    inbox.log.addHandler(_lines)
    check("no object yet: None", inbox._fetch_cos_once(_FakeCos(), errors=errs), None)
    check("noted for the all-doors warning", len(errs) == 1 and errs[0].startswith("cos:"), True)
    check("one door failing logs nothing above debug", _lines.got, [])
finally:
    inbox.urllib.request.urlopen = _real_urlopen
    inbox.log.removeHandler(_lines)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
