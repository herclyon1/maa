"""Evidence bundles must match what the projects' own export buttons produce.

The MaaEnd check replays the real export of 2026-09-11 12:23 (108 files in
three volumes, made with MXU's 🗄️ button on v2.28.0-rc.1): the same tree,
rebuilt from the export's file list with the recorded sizes and mtimes, has
to come out in the same order and split into the same volumes. MAA and OK-WW
are checked against the rules read from their source.
"""
import json
import os
import random
import sys
import zipfile
from datetime import datetime as _dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import evidence as ev
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


FX = Path(__file__).resolve().parent / "fixtures" / "collect-retry-2026-09-11"
official = json.loads((FX / "mxu-export-namelist.json").read_text(encoding="utf-8"))

print("[MaaEnd：和 🗄️ 按钮导出的 108 个文件同序同分卷]")
root = tmpdir() / "maaend"
# The zip keeps mtimes at 2-second resolution, so ties would make the image
# order (newest first) undefined; give each image a distinct mtime that keeps
# the official order, which is what the sort is being checked against.
img_rank = {e["name"]: k for k, e in enumerate(e for e in official if e["name"].startswith(("on_error/", "vision/")))}
for e in official:
    name = e["name"]
    rel = Path("config") / name[len("config/"):] if name.startswith("config/") else Path("debug") / name
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as f:
        if name in img_rank:
            f.write(name.encode())     # images must differ in content: identical ones are dropped on purpose
        else:
            f.truncate(e["size"])      # sparse: same size, no disk cost
    mt = 1_800_000_000 - img_rank[name] if name in img_rank else e["mtime"]
    os.utime(p, (mt, mt))
ALL = (0.0, 4_000_000_000.0)          # a window covering every fixture mtime
entries = ev.maaend_entries(root, ALL, max_images=None)
check("文件数一样", len(entries), len(official))
check("顺序完全一样", [n for _, n in entries], [e["name"] for e in official])
check("三位数编号（条目 ≥100）", 3 if len(entries) >= 100 else 2, 3)

print("\n[分卷按压缩后大小，规则照 MXU：估算触线才真压一次]")
vd = tmpdir() / "vol"
vd.mkdir()
rnd = random.Random(7)
big = []
for k in range(4):
    p = vd / f"blob{k}.dmp"                      # .dmp: estimated as-is, incompressible content
    p.write_bytes(rnd.randbytes(10_000_000))
    big.append((p, p.name))
vols = ev._volumes(big, ev.MAAEND_MAX_VOLUME)
check("4 个 10MB 不可压缩文件 → 两卷各两个", [len(v) for v in vols], [2, 2])
txt = vd / "zeros.log"                            # .log: estimate /4 says it fits, exact says so too
txt.write_bytes(b"0" * 60_000_000)
vols = ev._volumes(big[:2] + [(txt, txt.name)], ev.MAAEND_MAX_VOLUME)
check("60MB 全零日志压完很小，跟在同一卷", [len(v) for v in vols], [3])
rndlog = vd / "random.log"                        # .log but incompressible: estimate lies, exact measure catches it
rndlog.write_bytes(rnd.randbytes(20_000_000))
small = vd / "small.dmp"
small.write_bytes(rnd.randbytes(1_000_000))
vols = ev._volumes(big[:1] + [(rndlog, rndlog.name), (small, small.name)], ev.MAAEND_MAX_VOLUME)
check("估算太乐观的那个文件仍进本卷（MXU 也是），但之后按真实字节切卷", [len(v) for v in vols], [2, 1])

print("\n[bundle_maaend 真的打包：名字、编号宽度、文件都进去]")
small = tmpdir() / "mx"
(small / "debug" / "on_error").mkdir(parents=True)
(small / "config").mkdir()
(small / "debug" / "maafw.log").write_bytes(b"log\n" * 1000)
(small / "config" / "mxu-MaaEnd.json").write_text("{}", encoding="utf-8")
(small / "debug" / "on_error" / "a.png").write_bytes(b"\x89PNG" + b"\0" * 100)
out = ev.bundle_maaend(small, tmpdir() / "mxout", "v2.28.0-rc.1", ALL, _dt(2026, 9, 11, 12, 23, 50))
check("一卷，两位编号", [p.name for p in out], ["MaaEnd-logs-v2.28.0-rc.1-20260911-122350-part01.zip"])
with zipfile.ZipFile(out[0]) as z:
    check("三个文件都在，顺序对", z.namelist(), ["maafw.log", "config/mxu-MaaEnd.json", "on_error/a.png"])
check("空目录不出包", ev.bundle_maaend(tmpdir() / "nothing", tmpdir() / "o2", "v", ALL), [])

print("\n[30 天前的本地证据目录会被清掉]")
st = tmpdir() / "st"
old_dir = st / "evidence" / "old"; old_dir.mkdir(parents=True)
new_dir = st / "evidence" / "new"; new_dir.mkdir()
os.utime(old_dir, (1_600_000_000, 1_600_000_000))
check("清掉一个", ev.prune(st, 30), 1)
check("新的留着", new_dir.exists() and not old_dir.exists())

print("\n[MAA：config + resource(_custom) + cache + debug 根文件进 part01，子目录按 20MB 分卷]")
maa = tmpdir() / "maa"
for rel in ("config/gui.json", "resource/version.json", "resource/foo_custom.json", "cache/x.png",
            "debug/gui.log", "debug/asst.log", "debug/report_old.zip", "debug/interface/a.png", "debug/interface/b.png"):
    p = maa / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * 10)
out = ev.bundle_maa(maa, tmpdir() / "out", ALL)
names = [p.name for p in out]
check("有 part01 和 part02", [n.endswith("_part01.zip") for n in names] == [True, False] and len(out) == 2)
with zipfile.ZipFile(out[0]) as z:
    n1 = sorted(z.namelist())
check("part01 的内容", n1, ["cache/x.png", "config/gui.json", "debug/asst.log", "debug/gui.log", "resource/foo_custom.json"])
with zipfile.ZipFile(out[1]) as z:
    n2 = sorted(z.namelist())
check("part02 是 debug 子目录", n2, ["debug/interface/a.png", "debug/interface/b.png"])
check("名字是 report_月-日_时-分-秒_partNN", bool(__import__("re").fullmatch(r"report_\d\d-\d\d_\d\d-\d\d-\d\d_part01\.zip", names[0])))

print("\n[OK-WW：screenshots + logs 打一个 <title>-log.zip，路径相对工作目录]")
ww = tmpdir() / "working"
for rel in ("logs/ok-script.log", "screenshots/a.png", "src/task/x.py"):
    p = ww / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"y")
out = ev.bundle_okww(ww, tmpdir() / "out2", ALL)
check("一个包，名字对", [p.name for p in out], ["ok-ww-log.zip"])
with zipfile.ZipFile(out[0]) as z:
    check("只有那两个目录", sorted(z.namelist()), ["logs/ok-script.log", "screenshots/a.png"])
check("空目录不出包", ev.bundle_okww(tmpdir() / "empty", tmpdir() / "out3", ALL), [])
old_shot = ww / "screenshots" / "old.png"; old_shot.write_bytes(b"z"); os.utime(old_shot, (1_600_000_000, 1_600_000_000))
with zipfile.ZipFile(ev.bundle_okww(ww, tmpdir() / "out4", (1_700_000_000, 4_000_000_000))[0]) as z:
    check("OK-WW 也按时间窗：窗外的截图不带", "screenshots/old.png" not in z.namelist())

print("\n[上游源码钉住了：一变就报]")
pinned = {p.path: p for p in ev.PINS}
def same(url):
    for p in ev.PINS:
        if p.path in url:
            return b"same-as-pinned"
    raise OSError
changed, unreachable = ev.check_sources(fetch=lambda url: b"not the pinned bytes")
check("内容不一样＝三处都报变了", len(changed), 3)
changed, unreachable = ev.check_sources(fetch=lambda url: (_ for _ in ()).throw(OSError("down")))
check("拉不到只算「够不着」，不算变了", (changed, len(unreachable)), ([], 3))
check("三处钉的都有提交号和哈希", all(len(p.commit) == 40 and len(p.sha256) == 64 for p in ev.PINS))

print("\n[只钉打包那几个函数：别处改一行日志不报，函数体改一个字才报]")
# Fixture copies of the three upstream files as pinned (MAA at 4f144457, 09-12).
FXP = Path(__file__).resolve().parent / "fixtures" / "source-pins"
files = {"IssueReportUserControlModel.cs": "MAA 生成日志压缩包（IssueReportUserControlModel.cs）",
         "file_ops.rs": "MaaEnd 导出（MXU file_ops.rs）",
         "StartTab.py": "OK-WW Export Logs（ok-script StartTab.py）"}
def from_fixtures(url):
    for fname in files:
        if url.endswith("/" + fname):
            return (FXP / fname).read_bytes()
    raise OSError(url)
changed, unreachable = ev.check_sources(fetch=from_fixtures)
check("和库里存的副本一致＝一处都不报", (changed, unreachable), ([], []))
check("三处都钉了函数名", all(p.regions for p in ev.PINS))
check("每个函数名都在文件里找得到",
      all("<missing" not in ev.region_text((FXP / f).read_text(encoding="utf-8"), f, pinned[next(p.path for p in ev.PINS if p.path.endswith(f))].regions)
          for f in files))
cs = (FXP / "IssueReportUserControlModel.cs").read_text(encoding="utf-8")
# The 09-12 upstream change, replayed: a logging call outside the packaging code.
elsewhere = cs.replace('_logger.Error(ex, "Failed to open debug folder");', 'Log.Error(ex, "Failed to open debug folder");', 1)
check("改了别处的日志调用", elsewhere != cs)
changed, _ = ev.check_sources(fetch=lambda url: elsewhere.encode() if url.endswith(".cs") else from_fixtures(url))
check("打包函数没变就不报", changed, [])
inside = cs.replace("const int PartSize = 20 * 1024 * 1024;", "const int PartSize = 10 * 1024 * 1024;", 1)
check("分卷大小改了（在函数体里）", inside != cs)
changed, _ = ev.check_sources(fetch=lambda url: inside.encode() if url.endswith(".cs") else from_fixtures(url))
check("函数体一变就报", changed, [files["IssueReportUserControlModel.cs"]])
renamed = cs.replace("public void GenerateSupportPayload()", "public void GenerateSupportPayload2()", 1)
changed, _ = ev.check_sources(fetch=lambda url: renamed.encode() if url.endswith(".cs") else from_fixtures(url))
check("函数被改名也报（缺失标记进哈希）", changed, [files["IssueReportUserControlModel.cs"]])
py = (FXP / "StartTab.py").read_text(encoding="utf-8")
seg = ev.region_text(py, "StartTab.py", ("export_logs",))
check("Python 按缩进截到函数结尾", seg.splitlines()[0].strip().startswith("def export_logs") and "export_logs exception" in seg and "def ocr_log_bg" not in seg)
rs = (FXP / "file_ops.rs").read_text(encoding="utf-8")
seg = ev.region_text(rs, "file_ops.rs", ("export_logs_blocking",))
check("Rust 按花括号截到函数结尾", seg.startswith("fn export_logs_blocking(") and seg.rstrip().endswith("}") and "pub async fn export_logs" not in seg)

print("\n[一趟的时间窗：只带这一趟的日志，截图去重、封顶；不给窗就是 MXU 全量]")
wt = tmpdir() / "win"
(wt / "debug" / "on_error").mkdir(parents=True); (wt / "debug" / "cpp-algo").mkdir(); (wt / "config").mkdir()
T = 1_800_000_000
def _mk(rel, size, mtime, content=None):
    p = wt / rel
    p.write_bytes(content if content is not None else os.urandom(size))
    os.utime(p, (mtime, mtime)); return p
_mk("config/mxu-MaaEnd.json", 100, T - 86400 * 30)                  # config: always in
_mk("debug/2026-09-10-1.log", 1000, T - 86400 * 7)                    # a week old: out
_mk("debug/maafw.bak.old.log", 1000, T - 3600 * 3)                    # 3 h before the run: out
_mk("debug/2026-09-17-6.log", 1000, T + 60)                           # this run: in
_mk("debug/maafw.log", 1000, T + 200)                                 # this run: in
_mk("debug/cpp-algo/maafw.bak.run.log", 1000, T + 100)                # this run: in
_mk("debug/cpp-algo/maafw.bak.yesterday.log", 1000, T - 86400)        # out
same_bytes = os.urandom(500)
_mk("debug/on_error/a.png", 0, T + 10, same_bytes)                          # this run
_mk("debug/on_error/b.png", 0, T + 20, same_bytes)                          # identical bytes: dropped
for k in range(15):
    _mk(f"debug/on_error/c{k:02d}.png", 300, T + 30 + k)              # 15 distinct: capped
_mk("debug/on_error/old.png", 300, T - 86400 * 5)                     # out
win = (T - ev.WINDOW_SLACK, T + 240 + ev.WINDOW_SLACK)
got = [n for _, n in ev.maaend_entries(wt, win, ev.MAAEND_MAX_IMAGES)]
check("日志只有这一趟的三个 + 配置", [n for n in got if not n.startswith("on_error/")],
      ["2026-09-17-6.log", "maafw.log", "config/mxu-MaaEnd.json", "cpp-algo/maafw.bak.run.log"])
imgs = [n for n in got if n.startswith("on_error/")]
check("截图封顶 12 张、最新在前", (len(imgs), imgs[0]), (ev.MAAEND_MAX_IMAGES, "on_error/c14.png"))
check("内容相同的只留一张（a 与 b 二选一）、老的不带", ("on_error/b.png" in imgs) + ("on_error/a.png" in imgs) <= 1 and "on_error/old.png" not in imgs)
try:
    ev.maaend_entries(wt, None); no_window = "accepted"
except (ValueError, TypeError) as exc:
    no_window = type(exc).__name__
check("不给时间窗就拒绝（没有全量导出这条路了）", no_window in ("ValueError", "TypeError"))
full = [n for _, n in ev.maaend_entries(wt, (0.0, 4_000_000_000.0), max_images=None)]
check("窗覆盖全部时才等于 MXU 全量（去重后少一张）", (len(full), "2026-09-10-1.log" in full, "on_error/old.png" in full), (7 + 17, True, True))
parts = ev.bundle_maaend(wt, tmpdir() / "wout", "v1", win)
check("按窗打的包只有一卷", len(parts), 1)

print("\n[上传：索引里记下每一趟，失败也记]")
class FakeUp:
    def __init__(self): self.n = 0
    def upload(self, path):
        self.n += 1
        return {"id": str(self.n), "name": path.name, "page": "https://gofile.io/d/x", "size": path.stat().st_size}
ev.time.sleep = lambda s: None                     # no waiting between the retries in a test
class Cfg:
    state_dir = tmpdir() / "state"; maaend_dir = None; maa_dir = maa; okww_dir = None; history_dir = None
res = ev.save_and_upload(Cfg, "MAA", "2026-09-11/arknights/MAA-17-30-00", window=ALL, uploader=FakeUp())
check("两个分卷进一个压缩包，传的只有这一个文件", (len(res["files"]), len(res["uploaded"]), res["archive"]),
      (2, 1, "MAA-2026-09-11_arknights_MAA-17-30-00.zip"))
import zipfile as _zf  # noqa: E402
inner = _zf.ZipFile(Cfg.state_dir / "evidence" / "2026-09-11_arknights_MAA-17-30-00" / res["archive"]).namelist()
check("压缩包里就是上游格式的那几个文件，原样不动", sorted(inner), sorted(res["files"]))
check("有下载页", res.get("page"), "https://gofile.io/d/x")
idx = (Cfg.state_dir / "evidence" / "index.jsonl").read_text(encoding="utf-8").strip().splitlines()
check("索引写了一行", len(idx), 1)
check("没配置的脚本不出包", ev.bundle_for("OK-WW", Cfg, tmpdir() / "o", ALL), [])

print("\n[送出去只有一条路：COS（2026-09-18 起，付费的那个桶）；没配就明说、不走别的]")
class C0:
    state_dir = tmpdir(); cos_secret_id = ""; cos_secret_key = ""; cos_bucket = ""; cos_region = ""
    wecom_corpid = ""; wecom_secret = ""; wecom_agentid = ""; wecom_touser = "@all"
    wecom_bot_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x"
    maaend_dir = None; maa_dir = maa; okww_dir = None; history_dir = None
check("什么都没配 → 没有上传路", ev.pick_uploader(C0, "x"), None)
class C1(C0):
    wecom_corpid = "ww1"; wecom_secret = "s"; wecom_agentid = "1000002"
check("只有企业微信 → 也不走（备用路已关）", ev.uploaders(C1, "x"), [])
res0 = ev.save_and_upload(C1, "MAA", "2026-09-11/arknights/MAA-17-31-00", window=ALL)
check("没配 COS 的话包照打、索引里写明没配 COS", (bool(res0["archive"]), res0["uploaded"], any("没有配置 COS" in e for e in res0["errors"])), (True, [], True))
class C2(C1):
    cos_secret_id = "AKID"; cos_secret_key = "SK"; cos_bucket = "ark-evidence-1250000000"; cos_region = "ap-shanghai"
up = ev.pick_uploader(C2, "2026-09-12/endfield/MaaEnd-10-05-40")
check("四项 COS 设置齐了 → COS，而且只有它", (type(up).__name__, len(ev.uploaders(C2, "x"))), ("Cos", 1))
check("对象放在 run_id 目录下", up.object_key(Path("a.zip")), "2026-09-12_endfield_MaaEnd-10-05-40/a.zip")
auth = up.authorization("PUT", "2026-09-12_endfield_MaaEnd-10-05-40/a.zip", now=1_757_700_000)
check("签名串按腾讯云的格式", auth.startswith("q-sign-algorithm=sha1&q-ak=AKID&q-sign-time=1757699940;1757703540&q-key-time=1757699940;1757703540&q-header-list=host&q-url-param-list=&q-signature="), True)
check("同样输入同样签名（可复现）", auth, up.authorization("PUT", "2026-09-12_endfield_MaaEnd-10-05-40/a.zip", now=1_757_700_000))
check("签名是 40 位十六进制", len(auth.rsplit("=", 1)[-1]), 40)
# the reference recipe from the COS docs, computed independently
import hashlib, hmac  # noqa: E402
kt = "1757699940;1757703540"
sk = hmac.new(b"SK", kt.encode(), hashlib.sha1).hexdigest()
hs = "put\n/2026-09-12_endfield_MaaEnd-10-05-40/a.zip\n\nhost=ark-evidence-1250000000.cos.ap-shanghai.myqcloud.com\n"
sts = f"sha1\n{kt}\n{hashlib.sha1(hs.encode()).hexdigest()}\n"
check("和官方算法逐步算出来的一致", auth.rsplit("=", 1)[-1], hmac.new(sk.encode(), sts.encode(), hashlib.sha1).hexdigest())
# An account in arrears answers 451 (2026-09-13); on 09-14 the 132 MB PUT was cut
# off three times before the chain moved on. The bucket is asked first.
import urllib.error, urllib.request  # noqa: E402
_real_open = urllib.request.urlopen
opened = []
def _refuse(req, timeout=0):
    opened.append((req.get_method(), req.full_url))
    raise urllib.error.HTTPError(req.full_url, 451, "Unavailable For Legal Reasons", {}, None)
urllib.request.urlopen = _refuse
try:
    zf = tmpdir() / "MaaEnd-x.zip"; zf.write_bytes(b"z" * 1000)
    try:
        up.upload(zf); got = "no error"
    except ev.PermanentUploadError as exc:
        got = str(exc)
    check("欠费：探一下就换路，不传大文件", (got, [m for m, _ in opened]), ("COS 回了 451：腾讯云账号欠费，要充值", ["HEAD"]))
    opened.clear()
    def _put_refused(req, timeout=0):
        opened.append(req.get_method())
        if req.get_method() == "HEAD":
            raise urllib.error.URLError("wobble")
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
    urllib.request.urlopen = _put_refused
    try:
        up.upload(zf); got = "no error"
    except ev.PermanentUploadError as exc:
        got = str(exc)
    check("探的时候连接就断：这一轮不传大文件，换路", (got.startswith("连不上 COS"), opened), (True, ["HEAD"]))
    opened.clear()
    def _put_403(req, timeout=0):
        opened.append(req.get_method())
        if req.get_method() == "HEAD":
            class _R:
                def read(self): return b""
                def __enter__(self): return self
                def __exit__(self, *a): return False
            return _R()
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
    urllib.request.urlopen = _put_403
    try:
        up.upload(zf); got = "no error"
    except ev.PermanentUploadError as exc:
        got = str(exc)
    check("探通了照传；传的时候被拒也换路不重试", (got, opened), ("COS 回了 403：密钥不对或没有这个桶的权限", ["HEAD", "PUT"]))
finally:
    urllib.request.urlopen = _real_open
# One file per run, never pieces (the user, 2026-09-12): over WeCom's cap the store
# refuses and the chain moves on.
big = b"x" * (ev.WeComFiles.LIMIT + 5)
f = tmpdir() / "MaaEnd-logs-part001.zip"; f.write_bytes(big)
calls = []
class FakeWe(ev.WeComFiles):
    def token(self): return "T"
    def _upload_piece(self, name, data, timeout): calls.append(("up", name, len(data))); return "MID" + str(len(calls))
    def _send_file(self, media_id): calls.append(("send", media_id))
try:
    FakeWe(C1).upload(f); got = "no error"
except ev.PermanentUploadError as exc:
    got = str(exc)
check("超过 20 MB：不切段，直接说太大让下一条路接手", "20 MB" in got and calls == [], True)
small = tmpdir() / "MaaEnd-06-05-40.log"; small.write_bytes(b"log")
r = FakeWe(C1).upload(small)
check("装得下就一个文件一条消息", [c[0] for c in calls], ["up", "send"])
check("结果记下 media_id 和 3 天有效期", (r["store"], "expires" in r, r["page"], r["media_id"]), ("wecom", True, "企业微信", "MID1"))
# token(): cached until near expiry, and a refusal from WeCom is an error, not a silent ""
class _Resp:
    def __init__(self, body): self.body = body
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False
orig_open = ev.urllib.request.urlopen
ev.urllib.request.urlopen = lambda url, timeout=0: _Resp(b'{"errcode":0,"access_token":"TOK","expires_in":7200}')
w = ev.WeComFiles(C1)
try:
    check("取到 access_token", w.token(), "TOK")
    ev.urllib.request.urlopen = lambda url, timeout=0: _Resp(b'{"errcode":40001,"errmsg":"invalid credential"}')
    check("没过期就用缓存的，不再请求", w.token(), "TOK")
    w._until = 0
    try:
        w.token(); got = "no error"
    except RuntimeError as exc:
        got = str(exc)
    check("企业微信拒绝时报错说明", "40001" in got, True)
finally:
    ev.urllib.request.urlopen = orig_open

print("\n[一条路被拒就换下一条：60020（机器 IP 不在企业微信可信名单）不重试三次，直接换路]")
class Refuse:
    n = 0
    def upload(self, path):
        Refuse.n += 1
        raise ev.PermanentUploadError("企业微信: 60020 not allow to access from your ip")
class Flaky:
    n = 0
    def upload(self, path):
        Flaky.n += 1
        if Flaky.n == 1:
            raise RuntimeError("500")
        return {"name": path.name, "size": 1, "store": "gofile", "page": "https://gofile.io/d/y"}
orig_uploaders = ev.uploaders
ev.uploaders = lambda cfg, run_id="": [Refuse(), Flaky()]
try:
    class Cfg3:
        state_dir = tmpdir() / "state"; maaend_dir = None; maa_dir = maa; okww_dir = None; history_dir = None
    res3 = ev.save_and_upload(Cfg3, "MAA", "2026-09-11/arknights/MAA-17-30-00", window=ALL)
finally:
    ev.uploaders = orig_uploaders
check("被拒的那条路只碰一次", Refuse.n, 1)
check("第二条路接手，那一个文件传上了", (len(res3["uploaded"]), res3.get("store")), (1, "gofile"))
check("被拒记在错误里但不算传输失败", any("60020" in e for e in res3["errors"]) and len(res3["errors"]) == 1, True)
class C3(C1):
    wecom_bot_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY123"
check("备用路全关：配了企业微信应用和群机器人也不排进去", [type(u).__name__ for u in ev.uploaders(C3)], [])
check("备用路的代码还在（手动用）", all(hasattr(ev, k) for k in ("WeComFiles", "WeComBotFiles", "Gofile")))
check("群机器人从网址里取 key", ev.WeComBotFiles(C3.wecom_bot_url).key, "KEY123")
posts = []
def fake_post(url, data, ctype, timeout):
    posts.append(url.split("?")[0].rsplit("/", 1)[-1])
    return {"errcode": 0, "media_id": "M" + str(len(posts))}
orig_post = ev._wecom_post
ev._wecom_post = fake_post
try:
    r3 = ev.WeComBotFiles(C3.wecom_bot_url).upload(small)
    try:
        ev.WeComBotFiles(C3.wecom_bot_url).upload(f); big_got = "no error"
    except ev.PermanentUploadError as exc:
        big_got = str(exc)
finally:
    ev._wecom_post = orig_post
check("群机器人：先 upload_media 再 send，一个文件一条", posts, ["upload_media", "send"])
check("群机器人的结果标 wecom-bot", (r3["store"], r3["media_id"]), ("wecom-bot", "M1"))
check("群机器人也不切段", "20 MB" in big_got, True)
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
