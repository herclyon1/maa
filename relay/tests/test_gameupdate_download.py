"""gameupdate_games.download: the resumable APK download update_arknights uses.

No network: urllib.request.urlopen is replaced by a fake server. What matters is
that True means "dest is the complete file" - update_arknights skips the download
whenever dest exists and installs it as is - and that no .part is left in a state
that no later boot can finish.

Cases (HTTP behaviour, not a recorded sample: the Arknights CDN's real headers were
never logged):
* fresh 200 with Content-Length, and a body cut short
* resume: 206 with Content-Range appends
* resume, server ignores Range (200 + whole body): main added the old .part size to
  the total, so the restarted file never matched and failed on every boot
* no size at all: main accepted the file unchecked
* 416 on a .part that is already whole (the budget ran out on the last chunk) /
  one that is not: main raised on every boot
* the budget running out exactly on the last chunk still finishes
"""
import io
import sys
import types
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import gameupdate_games as gug
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Resp:
    def __init__(self, status, headers, body, chunk=4):
        self.status, self.headers = status, headers
        self._b, self._chunk = io.BytesIO(body), chunk

    def read(self, n=-1):
        return self._b.read(min(n, self._chunk) if n and n > 0 else self._chunk)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


seen = []


def serve(answer):
    """answer(range_header) -> Resp, or raises HTTPError."""
    def urlopen(req, timeout=None):
        rng = req.get_header("Range")
        seen.append(rng)
        return answer(rng)
    gug.urllib.request.urlopen = urlopen


_real_urlopen = gug.urllib.request.urlopen
BODY = b"0123456789"


def fresh():
    seen.clear()
    d = tmpdir() / "apk"
    d.mkdir(parents=True, exist_ok=True)
    return d / "arknights-1.0.apk"


def part_of(dest):
    return dest.with_suffix(dest.suffix + ".part")


try:
    print("[新下：200 带 Content-Length，下完 → True，dest 是整份，.part 没了]")
    dest = fresh()
    serve(lambda rng: Resp(200, {"Content-Length": "10"}, BODY))
    check("返回 True", gug.download("http://x/a.apk", dest), True)
    check("请求从 0 开始", seen, ["bytes=0-"])
    check("dest 内容完整", dest.exists() and dest.read_bytes(), BODY)
    check(".part 没了", part_of(dest).exists(), False)

    print("\n[新下：body 比 Content-Length 短 → False，没有 dest]")
    dest = fresh()
    serve(lambda rng: Resp(200, {"Content-Length": "10"}, BODY[:6]))
    check("返回 False", gug.download("http://x/a.apk", dest), False)
    check("没有 dest", dest.exists(), False)
    check(".part 留着下次接着下", part_of(dest).exists() and part_of(dest).read_bytes(), BODY[:6])

    print("\n[续传：已有 4 字节，206 + Content-Range → 接在后面]")
    dest = fresh()
    part_of(dest).write_bytes(BODY[:4])
    serve(lambda rng: Resp(206, {"Content-Range": "bytes 4-9/10", "Content-Length": "6"}, BODY[4:]))
    check("返回 True", gug.download("http://x/a.apk", dest), True)
    check("请求从 4 开始", seen, ["bytes=4-"])
    check("dest 内容完整", dest.exists() and dest.read_bytes(), BODY)

    print("\n[续传但服务器不认 Range：200 + 整份 → 从头写，大小按这一份算]")
    dest = fresh()
    part_of(dest).write_bytes(BODY[:4])
    serve(lambda rng: Resp(200, {"Content-Length": "10"}, BODY))
    check("返回 True（旧代码把旧的 4 字节算进总数，永远对不上）", gug.download("http://x/a.apk", dest), True)
    check("dest 内容是整份，没有重复", dest.exists() and dest.read_bytes(), BODY)

    print("\n[服务器没给大小 → 核不了，不算下完，不生成 dest]")
    dest = fresh()
    serve(lambda rng: Resp(200, {}, BODY))
    check("返回 False（旧代码不核就当完成）", gug.download("http://x/a.apk", dest), False)
    check("没有 dest", dest.exists(), False)

    print("\n[416，.part 已经是整份（上次预算刚好在最后一块用完）→ 收下]")
    dest = fresh()
    part_of(dest).write_bytes(BODY)

    def full416(rng):
        raise urllib.error.HTTPError("http://x/a.apk", 416, "Range Not Satisfiable",
                                     {"Content-Range": "bytes */10"}, io.BytesIO(b""))
    serve(full416)
    try:
        got = gug.download("http://x/a.apk", dest)
    except urllib.error.HTTPError as e:
        got = f"raised {e.code}"
    check("返回 True（旧代码每次开机都抛 416）", got, True)
    check("dest 内容完整", dest.exists() and dest.read_bytes(), BODY)

    print("\n[416，大小对不上 → False，删掉 .part 让下次从头下]")
    dest = fresh()
    part_of(dest).write_bytes(BODY + b"xx")
    serve(full416)
    try:
        got = gug.download("http://x/a.apk", dest)
    except urllib.error.HTTPError as e:
        got = f"raised {e.code}"
    check("返回 False", got, False)
    check("没有 dest", dest.exists(), False)
    check(".part 删了", part_of(dest).exists(), False)

    print("\n[别的 HTTP 错误照样抛给 update_arknights（它记成问题）]")
    dest = fresh()

    def e500(rng):
        raise urllib.error.HTTPError("http://x/a.apk", 500, "boom", {}, io.BytesIO(b""))
    serve(e500)
    try:
        gug.download("http://x/a.apk", dest)
        got = "no raise"
    except urllib.error.HTTPError as e:
        got = e.code
    check("500 抛出", got, 500)

    print("\n[body 比说的大小还长 → False，.part 删了（它不可能再变回对的大小）]")
    dest = fresh()
    serve(lambda rng: Resp(206, {"Content-Range": "bytes 0-6/7"}, BODY))
    check("返回 False", gug.download("http://x/a.apk", dest), False)
    check("没有 dest", dest.exists(), False)
    check(".part 删了", part_of(dest).exists(), False)

    print("\n[预算刚好在最后一块用完 → 照样算下完]")
    dest = fresh()
    clock = {"t": 0.0}

    def tick():
        clock["t"] += 1.0
        return clock["t"]
    real_time = gug.time
    gug.time = types.SimpleNamespace(monotonic=tick, sleep=lambda s: None)
    try:
        # deadline = 1 + 2.5; the clock reads 2 and 3 after chunks 1 and 2, and
        # would read 4 (past it) after chunk 3 - the last one, which completes the file
        serve(lambda rng: Resp(200, {"Content-Length": "10"}, BODY, chunk=4))
        got = gug.download("http://x/a.apk", dest, timeout=2.5)
    finally:
        gug.time = real_time
    check("返回 True", got, True)
    check("dest 内容完整", dest.exists() and dest.read_bytes(), BODY)

    print("\n[预算在中途用完 → False，.part 留着下次接着下]")
    dest = fresh()
    clock["t"] = 0.0
    gug.time = types.SimpleNamespace(monotonic=tick, sleep=lambda s: None)
    try:
        serve(lambda rng: Resp(200, {"Content-Length": "10"}, BODY, chunk=4))
        got = gug.download("http://x/a.apk", dest, timeout=0.5)
    finally:
        gug.time = real_time
    check("返回 False", got, False)
    check(".part 留着", part_of(dest).exists() and part_of(dest).read_bytes(), BODY[:4])
    check("没有 dest", dest.exists(), False)
finally:
    gug.urllib.request.urlopen = _real_urlopen

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
