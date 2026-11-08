"""Evidence: bundles and uploads, the archive, the CLI window, a quiet daily upload, MaaEnd's live logs, one notice, the relay log after a run, saved counts, unreachable sources; error and game evidence, a held push keeps its evidence, task shots.

One part per former file, each run on its own (tests/_parts.py): test_evidence.py, test_error_evidence.py, test_game_evidence.py, test_held_push_keeps_evidence.py, test_task_shots.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_main():  # noqa: C901 - the whole body of the file this part was
    """Evidence bundles must match what the projects' own export buttons produce.

The MaaEnd check replays the real export of 2026-09-11 12:23 (108 files in
three volumes, made with MXU's 🗄️ button on v2.28.0-rc.1): the same tree,
rebuilt from the export's file list with the recorded sizes and mtimes, has
to come out in the same order and split into the same volumes. MAA and OK-WW
are checked against the rules read from their source.

    Formerly test_evidence.py.
    """
    import json
    import os
    import random
    import zipfile
    from datetime import datetime as _dt

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.evidence import evidence as ev


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

    print("\n[daily/: old files go even though the folder itself is refreshed daily (s17 F4)]")
    daily = st / "evidence" / "daily"; daily.mkdir()
    old_f = daily / "relay-2026-08-01.log"; old_f.write_text("x", encoding="utf-8")
    os.utime(old_f, (1_600_000_000, 1_600_000_000))
    new_f = daily / "relay-2026-10-13.log"; new_f.write_text("x", encoding="utf-8")
    ev.prune(st, 30)
    check("daily/: the old file went, today's and the folder stay",
          (old_f.exists(), new_f.exists(), daily.is_dir()), (False, True, True))

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
    # Fixture copies of the three upstream files as pinned (MAA at 7c4edb83, 09-20).
    FXP = Path(__file__).resolve().parent / "fixtures" / "source-pins"
    files = {"IssueReportUserControlModel.cs": "MAA 生成日志压缩包（IssueReportUserControlModel.cs）",
             "file_ops.rs": "MaaEnd 导出（MXU file_ops.rs）",
             "diagnostics.py": "OK-WW Export Logs（ok-script diagnostics.py）"}
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
    check("async 签名也认得出（09-20 起是 public async Task）", "<missing" not in ev.region_text(cs, "x.cs", ("GenerateSupportPayload",)))
    renamed = cs.replace("public async Task GenerateSupportPayload()", "public async Task GenerateSupportPayload2()", 1)
    check("改名替换生效", renamed != cs)
    changed, _ = ev.check_sources(fetch=lambda url: renamed.encode() if url.endswith(".cs") else from_fixtures(url))
    check("函数被改名也报（缺失标记进哈希）", changed, [files["IssueReportUserControlModel.cs"]])
    py = (FXP / "diagnostics.py").read_text(encoding="utf-8")
    seg = ev.region_text(py, "diagnostics.py", ("export_logs",))
    check("Python 按缩进截到函数结尾", seg.splitlines()[0].strip().startswith("def export_logs") and "export_logs exception" in seg and "def _ocr_log" not in seg)
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
    import zipfile as _zf
    inner = _zf.ZipFile(Cfg.state_dir / "evidence" / "2026-09-11_arknights_MAA-17-30-00" / res["archive"]).namelist()
    check("压缩包里就是上游格式的那几个文件，原样不动", sorted(inner), sorted(res["files"]))
    check("有下载页", res.get("page"), "https://gofile.io/d/x")
    idx = (Cfg.state_dir / "evidence" / "index.jsonl").read_text(encoding="utf-8").strip().splitlines()
    check("索引写了一行", len(idx), 1)
    check("没配置的脚本不出包", ev.bundle_for("OK-WW", Cfg, tmpdir() / "o", ALL), [])

    print("\n[OK-WW 的证据包带一张桌面截图（2026-09-19：日志 09:34 就断了，游戏画面无人知道）]")
    okroot = tmpdir()
    okw = okroot / "data" / "apps" / "ok-ww" / "working"
    (okw / "logs").mkdir(parents=True)
    (okw / "logs" / "ok-script.log").write_text("2026-09-19 09:34:40 INFO stuck\n", encoding="utf-8")
    os.utime(okw / "logs" / "ok-script.log", (T + 60, T + 60))
    fake_png = tmpdir() / "shot-abc.png"; fake_png.write_bytes(b"\x89PNG fake")
    class CfgOk:
        state_dir = tmpdir() / "state"; maaend_dir = None; maa_dir = None; okww_dir = okroot; history_dir = None
    res_ok = ev.save_and_upload(CfgOk, "OK-WW", "2026-09-19/wuwa/OK-WW-05-16-07", window=win, uploader=FakeUp(),
                                screenshot=lambda: fake_png)
    shots = [n for n in res_ok["files"] if n.startswith("desktop-") and n.endswith(".png")]
    check("包里有一张 desktop-<时刻>.png", len(shots), 1)
    check("日志包也在", any(n.endswith("-log.zip") for n in res_ok["files"]), True)
    res_none = ev.save_and_upload(CfgOk, "OK-WW", "2026-09-19/wuwa/OK-WW-05-16-08", window=win, uploader=FakeUp(),
                                  screenshot=lambda: None)
    check("截不到图就不带、其余照常", ([n for n in res_none["files"] if n.startswith("desktop-")], len(res_none["files"]) >= 1), ([], True))
    res_boom = ev.save_and_upload(CfgOk, "OK-WW", "2026-09-19/wuwa/OK-WW-05-16-09", window=win, uploader=FakeUp(),
                                  screenshot=lambda: (_ for _ in ()).throw(RuntimeError("no desktop")))
    check("截图那步炸了也不影响出包", len(res_boom["files"]) >= 1 and not res_boom["errors"], True)
    res_maa = ev.save_and_upload(Cfg, "MAA", "2026-09-11/arknights/MAA-17-30-01", window=ALL, uploader=FakeUp(),
                                 screenshot=lambda: fake_png)
    check("MAA 的包不截桌面（模拟器画面走 ADB，桌面无意义）", [n for n in res_maa["files"] if n.startswith("desktop-")], [])

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
    import hashlib, hmac
    kt = "1757699940;1757703540"
    sk = hmac.new(b"SK", kt.encode(), hashlib.sha1).hexdigest()
    hs = "put\n/2026-09-12_endfield_MaaEnd-10-05-40/a.zip\n\nhost=ark-evidence-1250000000.cos.ap-shanghai.myqcloud.com\n"
    sts = f"sha1\n{kt}\n{hashlib.sha1(hs.encode()).hexdigest()}\n"
    check("和官方算法逐步算出来的一致", auth.rsplit("=", 1)[-1], hmac.new(sk.encode(), sts.encode(), hashlib.sha1).hexdigest())
    # An account in arrears answers 451 (2026-09-13); on 09-14 the 132 MB PUT was cut
    # off three times before the chain moved on. The bucket is asked first.
    import urllib.error, urllib.request
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
            got = "permanent: " + str(exc)
        except urllib.error.URLError as exc:
            got = "raised: " + str(exc.reason)
        # Audit 11-08 C-18: until then this was a refusal for the round (「连不上 COS…这一轮不传」),
        # so one dropped HEAD lost the round's evidence. Now it is raised for the caller's tries.
        check("探的时候连接就断：不传大文件，抛给外面再试（不算永久被拒）", (got, opened), ("raised: wobble", ["HEAD"]))
        opened.clear()
        heads = iter([urllib.error.URLError("wobble"), None])
        def _head_once(req, timeout=0):
            opened.append(req.get_method())
            if req.get_method() == "HEAD" and (exc := next(heads, None)) is not None:
                raise exc
            class _R:
                def read(self): return b""
                def __enter__(self): return self
                def __exit__(self, *a): return False
            return _R()
        urllib.request.urlopen = _head_once
        _real_sleep = ev.time.sleep
        ev.time.sleep = lambda s: None
        try:
            res_blip = ev.save_and_upload(C2, "MAA", "2026-11-08/arknights/MAA-09-00-00", window=ALL,
                                          uploader=up, extra=[zf])
        finally:
            ev.time.sleep = _real_sleep
        check("……证据包走一遍：第一次探断了，第二次探通、传上去了", ([u.get("store") for u in res_blip["uploaded"]],
                                                        opened), (["cos"], ["HEAD", "HEAD", "PUT"]))
        no_key = ev.Cos("", "", "b", "r")
        check("COS 设置不全：不连网，说缺什么", no_key.probe().startswith("COS 设置不全"), True)
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


def _part_evidence_archive():  # noqa: C901 - the whole body of the file this part was
    """失败证据要存对：AUTO-MAS 那一轮的记录必须带上，日志对不上要出声。

2026-09-05：MaaEnd 基质刷取第一次失败、重试成功。中继 10:00:45 才落账，
那时 MaaEnd 已经重启过、debug 目录被它自己清空重写，于是存下来的
maafw.log 只覆盖 09:57–09:59——**那是重试成功那次**，证据目录名却是失败那次
（MaaEnd-05-27-42）。查了半天才发现拿错了日志。

两条修复：
1. 同时存 AUTO-MAS `history/<run_id>.log/.json`——它按 run_id 取，必然对得上，
   当天正是靠那份 .json 才看出失败的是「基质刷取」。
2. 存下来的 debug 日志若最后写入时刻早于这一轮开始时刻，就是别轮的，记一行说明。

2026-10-15 16:34 / 18:18: that note was a WARNING, and errwatch pushes every ark.*
WARNING to the group as 「🩺 中继自己报错了」 - two pushes per failed run that wrote
no debug log of its own (handle.py archives the two newest debug logs, both from
an earlier round). The note is correct and not a relay fault; the failure itself
reaches the group as ❌. So it is INFO now, and only a crashed check stays WARNING.

    Formerly test_evidence_archive.py.
    """
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


    import logging
    import os
    import tempfile
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.alarm import errwatch, handle


    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.INFO)
            self.lines = []           # (levelno, message)

        def emit(self, record):
            self.lines.append((record.levelno, record.getMessage()))


    def _run_check(started, files, ew=None):
        """Records _warn_if_evidence_stale logs for debug logs {name: mtime}, captured from INFO up.

    `ew`, when given, is an errwatch handler attached to the "ark" logger for the call,
    as the relay attaches it (errwatch.install)."""
        d = pathlib.Path(tempfile.mkdtemp(prefix="arktest-stale-"))
        for name, mtime in files.items():
            f = d / name
            f.write_text("x", encoding="utf-8")
            os.utime(f, (mtime.timestamp(), mtime.timestamp()))
        grab = _Grab()
        ark = logging.getLogger(errwatch.ARK)
        level = ark.level
        ark.setLevel(logging.INFO)    # the relay logs at INFO (__main__.py basicConfig)
        handle.log.addHandler(grab)
        if ew is not None:
            ark.addHandler(ew)
        try:
            rec = SimpleNamespace(run_id="2026-10-12/endfield/MaaEnd-06-58-38", started=started)
            handle._warn_if_evidence_stale(None, rec, d)
        finally:
            if ew is not None:
                ark.removeHandler(ew)
            handle.log.removeHandler(grab)
            ark.setLevel(level)
            for f in d.iterdir():
                f.unlink()
            d.rmdir()
        return grab.lines


    def _stale_notes(started, mtime, name="2026-10-12-3.log"):
        """Messages for one debug log last written at `mtime`; also checks nothing reached WARNING."""
        got = _run_check(started, {name: mtime})
        loud = [m for lv, m in got if lv >= logging.WARNING]
        if loud:
            fails.append(f"别轮日志的说明不是中继故障，不该到 WARNING（errwatch 会推进群）：{loud}")
        return [m for _, m in got]


    # The run_id stem is AUTO-MAS's clock (UTC+4: collector.AUTOMAS_NAME_TZ), not the
    # server's: MaaEnd-06-58-38 started 2026-10-12 10:59:40 Beijing (ledger-2026-10-12).
    # A debug log last written 10:58:09 - the round before - must be flagged. Until
    # 2026-10-13 the check compared the stem's 06:58:38 with 10:58:09 and said nothing
    # (audit s7 #3).
    START = datetime(2026, 10, 12, 10, 59, 40, tzinfo=SERVER_TZ)
    got = _stale_notes(START, datetime(2026, 10, 12, 10, 58, 9, tzinfo=SERVER_TZ))
    if not any("别的轮次" in x for x in got):
        fails.append(f"上一轮写的 debug 日志没被标出来：{got}")
    # Written during the round: nothing logged.
    got = _stale_notes(START, START + timedelta(minutes=3))
    if got:
        fails.append(f"这一轮写的 debug 日志被误标：{got}")
    # The previous day's log, written later in the day than this round's start: flagged.
    got = _stale_notes(START, datetime(2026, 10, 11, 21, 0, tzinfo=SERVER_TZ))
    if not any("别的轮次" in x for x in got):
        fails.append(f"前一天的 debug 日志没被标出来：{got}")
    # AUTO-MAS's own copy is taken by run_id: never flagged.
    got = _stale_notes(START, datetime(2026, 10, 12, 10, 58, 9, tzinfo=SERVER_TZ), "automas-MaaEnd-06-58-38.log")
    if got:
        fails.append(f"按 run_id 取的 AUTO-MAS 日志被误标：{got}")

    # The 2026-10-15 16:34 shape (COS daily/relay-2026-10-15.log:1204-1205): MaaEnd found
    # no task and wrote no debug log, so both archived debug logs were the previous
    # round's. Two INFO notes, nothing at WARNING - before this, two WARNINGs and two
    # 「🩺 中继自己报错了」 pushes 3 s apart.
    START_1015 = datetime(2026, 10, 15, 16, 34, 25, tzinfo=SERVER_TZ)
    SHAPE_1015 = {"go-service.log": datetime(2026, 10, 15, 16, 28, 30, tzinfo=SERVER_TZ),
                  "maafw.log": datetime(2026, 10, 15, 16, 28, 29, tzinfo=SERVER_TZ),
                  "automas-MaaEnd-12-34-25.log": datetime(2026, 10, 15, 16, 34, 26, tzinfo=SERVER_TZ)}
    got = _run_check(START_1015, SHAPE_1015)
    info = [m for lv, m in got if lv == logging.INFO and "别的轮次" in m]
    loud = [m for lv, m in got if lv >= logging.WARNING]
    if len(info) != 2 or loud:
        fails.append(f"10-15 那种两份别轮日志：要 2 行 INFO、0 行 WARNING，实际 INFO {len(info)} 行、WARNING {loud}")
    if any("多半" in m for _, m in got):
        fails.append(f"说明里还有「多半」（时间比过了，就是别轮的）：{got}")


    # End to end with errwatch attached the way the relay attaches it: the 10-15 shape
    # queues nothing for the group; a crashed check (still a WARNING) is queued - the
    # positive control that shows this harness would see a push.
    class _Refuses:
        """errwatch's notifier: the group refuses, so whatever it queues stays readable in pending()."""

        def send_group(self, title, body):
            return ["企业微信机器人：拒收"]

        def send(self, title, body, **kw):
            return ["拒收"]


    def _errwatch():
        return errwatch.ErrorKindAlert(_Refuses(), state_dir=tmpdir("arktest-ew-"),
                                       known={}, retry=(3600.0,), fallback_after=3600.0)


    ew = _errwatch()
    try:
        _run_check(START_1015, SHAPE_1015, ew)
        queued = [x.get("line") for x in ew.pending()]
        if queued:
            fails.append(f"10-15 那种别轮日志说明被 errwatch 排进群（🩺 中继自己报错了）：{queued}")
    finally:
        ew.close()
    ew = _errwatch()
    try:
        got = _run_check(None, SHAPE_1015, ew)      # started=None: the check itself crashes
        queued = [str(x.get("line")) for x in ew.pending()]
        if not any(lv == logging.WARNING and "证据时间范围检查失败" in m for lv, m in got):
            fails.append(f"检查本身出错时要留 WARNING：{got}")
        if not any("证据时间范围检查失败" in q for q in queued):
            fails.append(f"检查本身出错时 errwatch 要排进群：{queued}")
    finally:
        ew.close()

    # 存档函数必须把 history 的两个后缀都带上
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "ark_relay" / "features" / "alarm" / "handle.py").read_text(encoding="utf-8")
    body = src[src.index("def _archive_maaend_evidence"):]
    body = body[:body.index("\ndef ", 10)] if "\ndef " in body[10:] else body
    # Since audit 11-08 C-08 the history files come from _history_files (old <run_id>.log/.json,
    # else v5.8's 0.log); the archive must call it, and it must read both suffixes.
    if "_history_files(" in body:
        hf = src[src.index("def _history_files"):]
        body += hf[:hf.index("\ndef ", 10)]
    if 'history_dir' not in body:
        fails.append("存档没有带上 AUTO-MAS 的 history 记录")
    for suffix in ('".log"', '".json"'):
        if suffix not in body:
            fails.append(f"存档没带 {suffix}")
    if "automas-" not in body:
        fails.append("AUTO-MAS 的文件没加前缀，会和 MaaEnd 自己的日志重名")
    if "_warn_if_evidence_stale" not in body:
        fails.append("存档后没有做日志时间范围检查")

    # 检查函数要跳过自己按 run_id 取的那份，否则会自己警告自己
    warn = src[src.index("def _warn_if_evidence_stale"):]
    warn = warn[:warn.index("\ndef ", 10)]
    if 'startswith("automas-")' not in warn:
        fails.append("时间检查没跳过 automas- 那几份（它们必然对得上）")

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_evidence_cli_window():
    """`python -m ark_relay evidence` never builds without a window: --hours, --since,
--run-id (that run's own window) or, with nothing given, the latest run of the
script in the ledger. The user, 2026-09-18: 「证据包永远按时间窗取」.

    Formerly test_evidence_cli_window.py.
    """
    import json
    import tempfile
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay import __main__ as cli
    from ark_relay.features.evidence import evidence
    from ark_relay.core.config import SERVER_TZ


    now = datetime.now(tz=SERVER_TZ)
    with tempfile.TemporaryDirectory() as td:
        cfg = types.SimpleNamespace(state_dir=Path(td))
        day = now.strftime("%Y-%m-%d")
        t_start = (now - timedelta(hours=3)).replace(microsecond=0)
        t_end = t_start + timedelta(minutes=20)
        older = t_start - timedelta(hours=5)
        ledger = Path(td) / f"ledger-{day}.jsonl"
        ledger.write_text("\n".join(json.dumps(e) for e in [
            {"run_id": f"{day}/endfield/MaaEnd-A", "script": "MaaEnd", "started": older.isoformat(), "finished": (older + timedelta(minutes=9)).isoformat(), "duration_known": True, "ok": True, "user": "u"},
            {"run_id": f"{day}/endfield/MaaEnd-B", "script": "MaaEnd", "started": t_start.isoformat(), "finished": t_end.isoformat(), "duration_known": True, "ok": True, "user": "u"},
            {"run_id": f"{day}/arknights/MAA-C", "script": "MAA", "started": t_start.isoformat(), "finished": t_end.isoformat(), "duration_known": True, "ok": True, "user": "u"},
        ]) + "\n", encoding="utf-8")

        print("[什么都不给：最近一趟，它自己的时间窗（前后各放宽 5 分钟）]")
        rid, (t0, t1) = cli.evidence_window(cfg, "MaaEnd")
        check("挑的是最近的 B", rid, f"{day}/endfield/MaaEnd-B")
        check("窗 = 开始-5 分钟 .. 结束+5 分钟", (t0, t1), (t_start.timestamp() - evidence.WINDOW_SLACK, t_end.timestamp() + evidence.WINDOW_SLACK))

        print("\n[--run-id：那一趟的窗]")
        rid, (t0, t1) = cli.evidence_window(cfg, "MaaEnd", run_id=f"{day}/endfield/MaaEnd-A")
        check("是 A", rid.endswith("MaaEnd-A") and t0 == older.timestamp() - evidence.WINDOW_SLACK)
        try:
            cli.evidence_window(cfg, "MaaEnd", run_id="nope"); missing = "accepted"
        except SystemExit as exc:
            missing = str(exc)
        check("账本里没有的 run_id 明说", "没有 nope" in missing)
        stub = {"run_id": f"{day}/endfield/MaaEnd-S", "script": "MaaEnd", "started": (now - timedelta(hours=1)).isoformat(),
                "finished": (now - timedelta(hours=1)).isoformat(), "duration_known": False, "ok": True, "user": "u"}
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(stub) + "\n")
        rid, (t0, t1) = cli.evidence_window(cfg, "MaaEnd")
        check("结束时间不可信的记录：窗封在开始 + 3 小时，不拉到现在", rid.endswith("MaaEnd-S") and abs((t1 - t0) - (cli.UNKNOWN_END_SECONDS + 2 * evidence.WINDOW_SLACK)) < 1)

        print("\n[--hours N：最近 N 小时到现在]")
        rid, (t0, t1) = cli.evidence_window(cfg, "MaaEnd", hours=2)
        check("窗宽约 2 小时", 7190 <= t1 - t0 <= 7210)
        check("run_id 是手动标记", rid.startswith("manual/MaaEnd-"))

        print("\n[--since 时刻：从那时到现在]")
        since = (now - timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M")
        rid, (t0, t1) = cli.evidence_window(cfg, "OK-WW", since=since)
        check("起点是给的时刻（服务器时区）", abs(t0 - datetime.fromisoformat(since).replace(tzinfo=SERVER_TZ).timestamp()) < 1)
        check("终点是现在附近", t1 - now.timestamp() < 5)

        print("\n[没有这个脚本的运行、也没给窗：拒绝，不悄悄全量]")
        try:
            cli.evidence_window(cfg, "OK-WW"); got = "accepted"
        except SystemExit as exc:
            got = str(exc)
        check("明说要 --hours 或 --since", "--hours" in got)

    print("\n[打包函数不给窗就拒绝]")
    for fn in (lambda: evidence.bundle_for("MaaEnd", types.SimpleNamespace(maaend_dir="/x"), Path("/tmp"), None),
               lambda: evidence.save_and_upload(types.SimpleNamespace(state_dir="/tmp"), "MaaEnd", "r", window=None)):
        try:
            fn(); got = "accepted"
        except (ValueError, TypeError) as exc:
            got = type(exc).__name__
        check("拒绝", got in ("ValueError", "TypeError"))

    print()
    if fails:
        print("FAILED:", fails); sys.exit(1)
    print("all checks passed")


def _part_evidence_daily_silent():
    """evidence_daily.py must exit non-zero when a day log could not be fetched.

Silent-failure audit row scripts/mac/lib/evidence_daily.py:90: a failed COS
fetch printed 「✗ … 取不到」 and main still returned 0, so a session that checks
the exit code saw success even with both logs missing.

    Formerly test_evidence_daily_silent.py.
    """
    import contextlib
    import io

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay" / "tests"))
    sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
    import evidence_daily as ed


    def run(missing):
        def cos_get(e, u, dest):
            if any(u["key"].startswith(f"daily/{m}-") for m in missing):
                raise RuntimeError("HTTP 404 NoSuchKey")
            (dest / u["name"]).write_text("10-10 01:00:00 INFO x\n", encoding="utf-8")

        ed.DEST_ROOT = tmpdir() / "daily"
        ed.evidence_pull.env = lambda _p: {"COS_SECRET_ID": "i", "COS_SECRET_KEY": "k",
                                           "COS_BUCKET": "b-1", "COS_REGION": "ap-shanghai"}
        ed.evidence_pull.cos_get = cos_get
        old = sys.argv
        sys.argv = ["evidence_daily.py", "2026-10-10"]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = ed.main()
        finally:
            sys.argv = old
        return rc, out.getvalue()


    print("[both logs fetched]")
    rc, out = run(missing=[])
    check("exit 0 when both are there", rc, 0)

    print("[the AUTO-MAS log is missing]")
    rc, out = run(missing=["automas-app"])
    check("the miss is printed", "automas-app-2026-10-10.log：取不到" in out, True)
    check("the relay log is still sliced", "relay-2026-10-10.log：窗口里 1 行" in out, True)
    check("exit non-zero when one is missing", rc, 1)

    print("[both missing]")
    check("exit non-zero when both are missing", run(missing=["relay", "automas-app"])[0], 1)


def _part_evidence_maaend_live_logs():
    """A MaaEnd bundle keeps the logs that were still being written at the end of its window.

The case is 2026-10-12 (ledger-2026-10-12.jsonl): MaaEnd-06-04-00 failed, run
10:05:05-10:58:09 (+08:00); its retry MaaEnd-06-58-38 ran 10:59:40-11:38:12 and
kept writing the same logs, so when the bundle was built at 11:38:15 maafw.log,
the MXU day log, go-service.log and mxu-tauri.log all had mtimes near 11:38,
past t1 = 11:03:09. The old rule (mtime inside the window) dropped every one of
them and shipped only the config and the screenshot (audit s17 F1).

The file layout below mirrors the real debug/ tree of 2026-10-11 (staged copy
of MaaEnd-05-30-34): maafw rotates into maafw.bak.<time>.log, cpp-algo/debug
has its own maafw, go-service.log is JSON lines, mxu-tauri.log stamps
`[YYYY-MM-DD][HH:MM:SS]`. The first lines below are in those formats.

    Formerly test_evidence_maaend_live_logs.py.
    """
    import os
    import time
    import zipfile
    from datetime import datetime

    # The machine's clock where it can be set: MaaEnd stamps local Beijing time. time.tzset is
    # Unix only ("Availability: Unix", docs.python.org/3/library/time.html#time.tzset); every
    # stamp below is written through loc(), in the local time the relay reads it back in
    # (logslice._line_ts), so the test holds in any zone (the Windows runner: UTC).
    if hasattr(time, "tzset"):
        os.environ["TZ"] = "Asia/Shanghai"
        time.tzset()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.evidence import evidence as ev


    def at(hms: str, day: str = "2026-10-12") -> float:
        return datetime.fromisoformat(f"{day}T{hms}+08:00").timestamp()


    def loc(hms: str, day: str = "2026-10-12", fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        """The Beijing moment day hms as the machine stamps it: in its local time."""
        return datetime.fromtimestamp(at(hms, day)).strftime(fmt)


    def go_time(hms: str, day: str = "2026-10-12") -> str:
        """go-service.log's "time": local time with the local offset (+08:00 on the machine)."""
        return datetime.fromtimestamp(at(hms, day)).astimezone().isoformat(timespec="seconds")


    def tauri(hms: str, day: str = "2026-10-12") -> str:
        """mxu-tauri.log's `[YYYY-MM-DD][HH:MM:SS]`, local time."""
        return loc(hms, day, "[%Y-%m-%d][%H:%M:%S]")


    def maafw_lines(start: str, end: str, step_s: int = 60) -> str:
        out, t = [], at(start)
        while t <= at(end):
            s = datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
            out.append(f"[{s}.000][DBG][Px9200][Tx16448][Logger] line {s}")
            t += step_s
        return "\n".join(out) + "\n"


    root = tmpdir() / "maaend"
    dbg = root / "debug"
    (dbg / "on_error").mkdir(parents=True)
    (dbg / "cpp-algo" / "debug").mkdir(parents=True)
    (root / "config").mkdir()


    def mk(rel: str, text: str, mtime: float) -> Path:
        # Bytes, not write_text: in text mode Windows writes "\n" as "\r\n" (run 38363145659), and the
        # bundle copies bytes, so the expected texts below would not match the archive there.
        p = root / rel
        p.write_bytes(text.encode("utf-8"))
        os.utime(p, (mtime, mtime))
        return p


    window = ev.run_window(datetime.fromisoformat("2026-10-12T10:05:05+08:00"),
                           datetime.fromisoformat("2026-10-12T10:58:09+08:00"))
    check("t1 is the run's end plus the slack (11:03:09)", window[1], at("11:03:09"))

    mk("config/mxu-MaaEnd.json", "{}", at("08:00:00", "2026-09-30"))
    mk("debug/maafw.bak.2026.10.12-09.40.00.000.log", maafw_lines("09:20:00", "09:40:00"), at("09:40:00"))  # before t0: out
    mk("debug/maafw.bak.2026.10.12-10.10.00.000.log", maafw_lines("09:40:00", "10:10:00"), at("10:10:00"))  # holds t0
    mk("debug/maafw.bak.2026.10.12-10.30.00.000.log", maafw_lines("10:10:00", "10:30:00"), at("10:30:00"))  # in window
    mk("debug/maafw.bak.2026.10.12-11.10.00.000.log", maafw_lines("10:30:00", "11:10:00"), at("11:10:00"))  # holds t1
    mk("debug/maafw.bak.2026.10.12-11.25.00.000.log", maafw_lines("11:10:00", "11:25:00"), at("11:25:00"))  # retry only: out
    mk("debug/maafw.log", maafw_lines("11:25:00", "11:38:00"), at("11:38:12"))                               # retry only: out
    mk("debug/2026-10-12-3.log",
       f"{loc('09:58:00')} INFO  [App] start\n{loc('10:40:00')} INFO  [App] mid\n"
       f"{loc('11:30:00')} INFO  [App] retry\n", at("11:38:12"))                                          # still open: in
    mk("debug/go-service.log",
       f'{{"level":"info","time":"{go_time("16:56:39", "2026-09-10")}","message":"MaaEnd Agent Service"}}\n'
       f'{{"level":"info","time":"{go_time("10:40:00")}","message":"in the run"}}\n'
       f'{{"level":"info","time":"{go_time("11:38:00")}","message":"Agent server shutdown"}}\n',
       at("11:38:12"))                                                                                      # still open: in
    mk("debug/mxu-tauri.log",
       f"{tauri('09:14:23', '2026-10-10')}[DEBUG][mxu_lib] old\n{tauri('10:40:00')}[INFO][mxu_lib] in the run\n"
       f"{tauri('11:38:00')}[INFO][mxu_lib] retry\n", at("11:38:12"))                                     # still open: in
    mk("debug/odd.log", "no stamps at all\njust text\n", at("11:38:12"))                                   # unreadable stamps: whole
    mk("debug/cpp-algo/debug/maafw.log", maafw_lines("10:20:00", "11:38:00"), at("11:38:12"))               # subdir, still open: in
    mk("debug/on_error/e.png", "png", at("10:50:00"))

    print("[10-12 MaaEnd-06-04-00: the logs the retry kept writing stay in the bundle]")
    got = [n for _, n in ev.maaend_entries(root, window)]
    check("logs: the in-window bak, the bak holding t1, the open logs; not the retry-only ones",
          [n for n in got if n.endswith(".log")],
          ["2026-10-12-3.log", "go-service.log", "maafw.bak.2026.10.12-10.10.00.000.log",
           "maafw.bak.2026.10.12-10.30.00.000.log",
           "maafw.bak.2026.10.12-11.10.00.000.log", "mxu-tauri.log", "odd.log", "cpp-algo/debug/maafw.log"])
    check("config and the screenshot still in", ("config/mxu-MaaEnd.json" in got, "on_error/e.png" in got), (True, True))

    print("\n[the long ones are cut to the window when packed]")
    parts = ev.bundle_maaend(root, tmpdir() / "out", "v2.28.0", window, datetime.fromtimestamp(at("11:38:15")))
    check("one volume", len(parts), 1)
    with zipfile.ZipFile(parts[0]) as z:
        names = z.namelist()
        body = {n: z.read(n).decode("utf-8") for n in names if n.endswith(".log")}
    check("same names in the archive", [n for n in names if n.endswith(".log")],
          [n for n in got if n.endswith(".log")])
    gs = body.get("go-service.log", "")
    check("go-service.log: the run's line kept, last month's and the retry's cut",
          ("in the run" in gs, "MaaEnd Agent Service" in gs, "shutdown" in gs), (True, False, False))
    tauri = body.get("mxu-tauri.log", "")
    check("mxu-tauri.log cut to the window", ("in the run" in tauri, "old" in tauri, "retry" in tauri), (True, False, False))
    bak = body.get("maafw.bak.2026.10.12-11.10.00.000.log", "")
    check("the bak holding t1 ends at t1", (loc("11:03:00") in bak, loc("11:04:00") in bak), (True, False))
    check("the bak holding t1 keeps the run's part", loc("10:30:00") in bak)
    check("a log with no readable stamps goes in whole", body.get("odd.log"), "no stamps at all\njust text\n")
    b0 = body.get("maafw.bak.2026.10.12-10.10.00.000.log", "")
    check("the bak holding t0 starts at t0", (loc("10:00:00") in b0, loc("10:01:00") in b0), (False, True))
    check("an in-window log goes in untouched",
          body.get("maafw.bak.2026.10.12-10.30.00.000.log"),
          (dbg / "maafw.bak.2026.10.12-10.30.00.000.log").read_bytes().decode("utf-8"))
    check("no slice files left beside the volumes", sorted(p.name for p in parts[0].parent.iterdir()),
          [parts[0].name])
    src_size = (dbg / "go-service.log").stat().st_size
    check("the source logs are not touched", ("MaaEnd Agent Service" in (dbg / "go-service.log").read_text(encoding="utf-8"),
                                              src_size > len(gs.encode())), (True, True))

    if fails:
        print(f"\n{len(fails)} failed")
        sys.exit(1)
    print("\nall passed")


def _part_evidence_notify_once():
    """An upstream export change is announced once, not on every boot.

boot_stages._stage_evidence_sources compared the pinned upstream files on each
boot and pushed 「上游导出代码变了」 each time, so one upstream commit reached the
user again every morning and evening until the pin was updated. The stage now
records the fingerprint it announced in state/evidence-source-notified.json;
the same fingerprint stays quiet, a new one is announced again.

Since 2026-10-11 the announcement is a red item in the technical log (our work: the
evidence bundling has to be re-checked), not a Server酱 notice to him; the stage's
WARNING still reaches the group on every boot until the pin is renewed (the user,
2026-10-11 17:44; his words are in relay/USER-SWITCHES.txt's header).

    Formerly test_evidence_notify_once.py.
    """
    import tempfile
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    import boot_stages
    from ark_relay.features.evidence import evidence


    class _Log:
        def __init__(self): self.lines = []
        def warning(self, *a): self.lines.append(a[0] % a[1:])
        def info(self, *a): self.lines.append(a[0] % a[1:] if len(a) > 1 else a[0])
        def exception(self, *a): self.lines.append(a[0])


    class _Notifier:
        def __init__(self): self.sent = []
        def send(self, title, body, *a, **k): self.sent.append((title, body))


    def run(state, upstream):
        def fake_check():
            evidence.LAST_SEEN.clear()
            evidence.LAST_SEEN.update(upstream)
            return list(upstream), []
        evidence.check_sources, saved = fake_check, evidence.check_sources
        try:
            cfg = types.SimpleNamespace(state_dir=state)
            n, log = _Notifier(), _Log()
            boot_stages._stage_evidence_sources(cfg, n, log)
            return n, log
        finally:
            evidence.check_sources = saved


    from ark_relay.core import techlog


    def new_reds(d, before):
        import glob
        text = "".join(Path(f).read_text(encoding="utf-8") for f in sorted(glob.glob(str(techlog.tech_dir(d) / "*.md"))))
        got = techlog.unhandled(text)
        return got[len(before):], got


    with tempfile.TemporaryDirectory() as root:
        d = str(Path(root) / "state")
        Path(d).mkdir()
        n, log = run(d, {"MAA": "aaa"})
        fresh, seen = new_reds(d, [])
        assert n.sent == [], n.sent                                   # nothing to him
        assert len(fresh) == 1 and "MAA" in fresh[0][1], fresh        # one red item for us
        assert any("上游导出代码变了" in x for x in log.lines), log.lines   # the WARNING for the group
        n, log = run(d, {"MAA": "aaa"})
        fresh, seen = new_reds(d, seen)
        assert n.sent == [] and fresh == [], (n.sent, fresh)
        assert any("都已报过" in x for x in log.lines), log.lines
        n, _ = run(d, {"MAA": "bbb"})
        fresh, seen = new_reds(d, seen)
        assert len(fresh) == 1 and "MAA" in fresh[0][1], fresh
        n, _ = run(d, {"MAA": "bbb", "MaaEnd": "ccc"})
        fresh, seen = new_reds(d, seen)
        assert len(fresh) == 1 and "MaaEnd" in fresh[0][1] and "MAA、" not in fresh[0][1], fresh
        n, _ = run(d, {})
        fresh, seen = new_reds(d, seen)
        assert n.sent == [] and fresh == []

    print("all checks passed")


def _part_evidence_relay_after_run():
    """A failure bundle carries what the relay did about the run, and its link reaches the ledger.

Replayed from the 2026-09-24 morning (bucket ark-evidence, 2026-09-24_arknights_MAA-05-00-02):
MAA failed 09:03:08, the record's window is 08:58:06-09:08:08, and the relay
handled it at 09:20 (bundle upload 01:20 UTC) - AUTO-MAS writes the record at the
end of the whole script. The relay.log slice held two lines, both 09:02:01, and
two MaaEnd bundles that day held no relay.log at all; the relay's own handling
was never in any of them. And the link was set on rec.raw after the run was on
the ledger and never written back, so the daily report's 证据包 row was always empty.

    Formerly test_evidence_relay_after_run.py.
    """
    import json
    import os
    import types
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.evidence import evidence
    from ark_relay.features.alarm import handle
    from ark_relay.core import texts
    from ark_relay.core import ledger as core
    from ark_relay.core.config import SERVER_TZ, RunRecord


    def at(h, m, s):
        """09-24 h:m:s on the machine's clock (Beijing), the moment the real bundle names."""
        return datetime(2026, 9, 24, h, m, s, tzinfo=SERVER_TZ)


    def at_(h, m, s):
        """That moment as relay.log stamps it: in the local time of the computer running
    the test (logging's asctime; evidence._line_ts reads it back as local). On the
    machine that is Beijing and this is the real bundle's 「09-24 h:m:s」; on the
    Windows CI runner (UTC, run 37519943859) literal Beijing stamps read back eight
    hours late, and 09:03 started a 晚班 round."""
        return at(h, m, s).astimezone().strftime("%m-%d %H:%M:%S")


    T = tmpdir()
    relay_log = T / "relay.log"
    relay_log.write_text(
        # the two lines the real bundle held, both 09-24 09:02:01
        f"{at_(9, 2, 1)} INFO    ark.shutdown  不关机：本次开机还没有跑完任何队列\n"
        f"{at_(9, 2, 1)} INFO    ark.service  下一个闹钟 09:25 核对队列「早班」09:00 是否漏跑\n"
        # what the relay did once the record landed (09:20:03, 09:20:04)
        f"{at_(9, 20, 3)} INFO    ark.handle  ⏳ MAA 失败，暂不推送，等重试结果\n"
        f"{at_(9, 20, 4)} INFO    ark.notify  不推送（日报或手机页已有）：⚠️ MAA 中途失败过，重试后成功\n"
        # after the cut (09:40:00)
        f"{at_(9, 40, 0)} INFO    ark.service  下一个闹钟 12:00\n", encoding="utf-8")
    os.environ["ARK_LOG_FILE"] = str(relay_log)
    started = at(9, 3, 6).astimezone()     # the machine stamps its own local time
    finished = at(9, 3, 8).astimezone()
    handled = at(9, 20, 5).timestamp()
    win = evidence.run_window(started, finished)

    print("[复现：只按那趟自己的时间窗切，中继日志只剩 09:02:01 两行]")
    evidence.context_files(types.SimpleNamespace(automas_dir=None), win, T / "old")
    rl = (T / "old" / "relay.log").read_text(encoding="utf-8")
    check("两行，都是 09:02:01", [ln[:14] for ln in rl.splitlines()], [at_(9, 2, 1), at_(9, 2, 1)])
    check("中继自己怎么处理的一行都没有", at_(9, 20, 3) in rl, False)

    print("\n[切到处理那一刻：处理行在，之后的不在]")
    evidence.context_files(types.SimpleNamespace(automas_dir=None), win, T / "new", relay_until=handled)
    rl = (T / "new" / "relay.log").read_text(encoding="utf-8")
    check("09:02:01 两行还在", rl.count(at_(9, 2, 1)), 2)
    check("处理那几行在", at_(9, 20, 3) in rl and at_(9, 20, 4) in rl)
    check("切之后的不在", at_(9, 40, 0) in rl, False)

    print("\n[手工导出不传截止时刻：照旧只切那趟的窗]")
    evidence.context_files(types.SimpleNamespace(automas_dir=None), win, T / "cli")
    check("手工导出不多带", at_(9, 20, 3) in (T / "cli" / "relay.log").read_text(encoding="utf-8"), False)


    class Up:
        def upload(self, p):
            return {"name": p.name, "size": p.stat().st_size, "store": "cos", "page": "https://cos.example/MAA.zip"}


    class Notifier:
        def __init__(self):
            self.sent = []

        def send(self, title, body, alert=False):
            self.sent.append((title, body, alert))
            return []


    evidence.uploaders = lambda cfg, run_id="": [Up()]
    handle.time = types.SimpleNamespace(time=lambda: handled)


    def engine(d: Path):
        cfg = types.SimpleNamespace(state_dir=d, history_dir=None, automas_dir=None,
                                    maa_dir=None, maaend_dir=None, okww_dir=None)
        eng = types.SimpleNamespace(cfg=cfg, state=core.State(d), notifier=Notifier(), _pending={}, _recovered={})
        eng.persisted = []
        eng._persist_pending = lambda: eng.persisted.append(dict(eng._pending))
        return eng


    def record(run_id):
        return RunRecord(run_id=run_id, script="MAA", user="u", started=started, finished=finished,
                         ok=False, failed_tasks=["StartUp"], raw={"maa_result": "MAA 未能正确登录 PRTS"})


    day = started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")

    print("\n[首败：证据包里有处理行，链接写回账本，链接进技术日志那一行（D-1010：不进日报）]")
    eng = engine(tmpdir())
    rec = record(f"{day}/arknights/MAA-05-00-02")
    eng.state.append_ledger(rec)
    handle._hold_for_retry(eng, rec, ("MAA", "u"))
    entry = eng.state.read_ledger(day)[0]
    check("账本里有链接", (entry.get("raw") or {}).get("evidence_page"), "https://cos.example/MAA.zip")
    check("待推记录带着链接又存了一次", (eng.persisted[-1][("MAA", "u")].raw or {}).get("evidence_page"), "https://cos.example/MAA.zip")
    tech: list = []
    daily = core.format_daily(day, eng.state.read_ledger(day), tech=tech)
    daily = daily if isinstance(daily, str) else json.dumps(daily, ensure_ascii=False)
    check("证据包链接进技术日志那一行", any("证据包 https://cos.example/MAA.zip" in t for t in tech), True)
    check("日报里不再有证据包链接", "https://cos.example/MAA.zip" in daily, False)
    bundle = next((eng.cfg.state_dir / "evidence").glob("*/bundle/relay.log"))
    check("证据包里的中继日志带着处理行", at_(9, 20, 3) in bundle.read_text(encoding="utf-8"))
    check("首败没有任何报警推送", [t for t, _, a in eng.notifier.sent if a], [])

    print("\n[重试后成功：自己好了，不推，只进日报（用户 2026-10-06 05:07），日志这么说]")
    import logging
    seen = []
    h = logging.Handler(); h.emit = lambda r: seen.append(r.getMessage())
    handle.log.addHandler(h); handle.log.setLevel(logging.INFO)
    eng._recovered[("MAA", "u")] = eng._pending.pop(("MAA", "u"))
    eng._scripts_running = lambda: False
    eng._script_running = lambda name: False
    eng._alert_key = lambda r: "StartUp"
    eng._already_alerted = lambda d, k: handle._already_alerted(eng, d, k)
    eng._mark_alerted = lambda d, k: handle._mark_alerted(eng, d, k)
    before = len(eng.notifier.sent)
    handle._flush_pending(eng)
    check("自愈那条没发（群、Server酱都没有）", [t for t, _, _ in eng.notifier.sent[before:]], [])
    check("日志写的是只进日报", any(m.startswith(texts.self_healed("MAA")) and "只进日报" in m for m in seen))
    check("放下了", eng._recovered, {})

    print("\n[这一轮没干完（鸣潮）：报警本身带证据链接]")
    eng = engine(tmpdir())
    rec = record(f"{day}/wuwa/OK-WW-17-30-02")
    rec.script, rec.ok = "OK-WW", True
    eng.state.append_ledger(rec)
    eng._verify_outcome = lambda r: "OK-WW 这一轮有 1 项没干成"
    handle._weekly_gates = lambda eng, rec: None
    handle._handle_success(eng, rec, ("OK-WW", "u"))
    alarm = [b for t, b, a in eng.notifier.sent if t == texts.ROUND_INCOMPLETE]
    check("报警发了一条", len(alarm), 1)
    check("报警正文带证据链接", bool(alarm) and "证据包：https://cos.example/MAA.zip" in alarm[0])
    check("账本里也有链接", (eng.state.read_ledger(day)[0].get("raw") or {}).get("evidence_page"), "https://cos.example/MAA.zip")

    print("\n[这一轮没干完（MAA）：这一班进群一次，报警头一行带证据链接；账本带「没干完」和链接进日报]")
    eng = engine(tmpdir())
    eng._already_alerted = lambda d, k: handle._already_alerted(eng, d, k)
    eng._mark_alerted = lambda d, k: handle._mark_alerted(eng, d, k)
    eng._unsent_unresolved = []
    eng.SOFT_FAILS = {"应急理智加强剂", "自动采集"}
    rec = record(f"{day}/arknights/MAA-17-30-02")
    rec.ok = True
    eng.state.append_ledger(rec)
    eng._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：没换上"
    handle._handle_success(eng, rec, ("MAA", "u"))
    check("没有推鸣潮那条「这一轮没干完」", [t for t, b, a in eng.notifier.sent if t == texts.ROUND_INCOMPLETE], [])
    pushed = [(t, b) for t, b, a in eng.notifier.sent if a]
    check("进群一条「明日方舟早班没干完」", [t for t, _ in pushed], [texts.unresolved_undone("明日方舟", "早班")])
    check("头一行带项目和证据链接", bool(pushed) and pushed[0][1].splitlines()[0],
          "明日方舟早班跑完了但没干完：基建换班，这一类不补跑（证据包 https://cos.example/MAA.zip）")
    entry = eng.state.read_ledger(day)[0]
    check("账本记了没干完", entry.get("incomplete"), "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：没换上")
    check("账本里也有链接", (entry.get("raw") or {}).get("evidence_page"), "https://cos.example/MAA.zip")

    print()
    if fails:
        print("FAILED:", fails); sys.exit(1)
    print("all checks passed")


def _part_evidence_saved_count():
    """The 🗂️ evidence line counts the files inside the bundle, not the uploads.

The bundle goes up as one archive (evidence.save_and_upload packs every file into
one zip), so res["uploaded"] always holds one link. relay.log 2026-10-12 11:38:15
archived 14 files for MaaEnd-06-04-00, and the 11:38:26 line plus the 🗂️ message
said 「里面 1 个文件」 (audit s17 F2). The count is res["files"].

    Formerly test_evidence_saved_count.py.
    """
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng_mod
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.features.alarm import handle
    from ark_relay.features.evidence import evidence


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return []


    class Src:
        def fetch(self, seen):
            return []


    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.history_dir = None
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    start = datetime(2026, 10, 12, 10, 5, tzinfo=SERVER_TZ)
    rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-06-04-00", script="MaaEnd", user="endfield",
                    started=start, finished=start + timedelta(minutes=30), ok=False, failed_tasks=["x"], raw={})
    names = [f"f{i}.log" for i in range(14)]
    evidence.save_and_upload = lambda *a, **k: {"files": names, "uploaded": ["https://cos/one.zip"],
                                                "page": "https://cos/page.html", "errors": []}
    page = handle._ship_evidence(e, rec)
    check("link returned", page, "https://cos/page.html")
    saved = [b for t, b in e.notifier.sent if t == texts.EVIDENCE_SAVED]
    check("one 🗂️ line", len(saved), 1)
    check("it counts the 14 files in the bundle", bool(saved) and "里面 14 个文件" in saved[0], True)
    check("not the one upload", bool(saved) and "里面 1 个文件" in saved[0], False)

    print("\n" + (f"✗ {len(fails)} failed" if fails else "all checks passed"))


def _part_evidence_sources_unreachable():
    """The upstream-source check says why it could not fetch, and when it tries again.

relay.log since 2026-10-11 10:04 has the boot line 「上游导出代码核对：3 个文件今天拉不到，
明天再比」 on almost every boot: sources.check_sources swallowed the exception, so
nobody could tell a DNS failure from a timeout or a jsDelivr refusal, and 「明天再比」
was wrong - the stage runs on every boot (audit s17 F5).

    Formerly test_evidence_sources_unreachable.py.
    """
    import tempfile
    import types
    import urllib.error
    import urllib.request

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    import boot_stages


    class _Log:
        def __init__(self): self.lines = []
        def warning(self, *a): self.lines.append(a[0] % a[1:])
        def info(self, *a): self.lines.append(a[0] % a[1:] if len(a) > 1 else a[0])
        def exception(self, *a): self.lines.append(a[0])


    def down(*a, **k):
        raise urllib.error.URLError(TimeoutError("timed out"))


    print("[jsDelivr unreachable on boot: the log line carries the reason]")
    saved, urllib.request.urlopen = urllib.request.urlopen, down
    try:
        log = _Log()
        boot_stages._stage_evidence_sources(types.SimpleNamespace(state_dir=Path(tempfile.mkdtemp())), None, log)
    finally:
        urllib.request.urlopen = saved
    line = next((ln for ln in log.lines if ln.startswith("上游导出代码核对")), "")
    print("   ", line)
    check("one line about the unreachable files", line.startswith("上游导出代码核对：3 个文件"))
    check("it names the exception", "timed out" in line and "URLError" in line)
    check("it says the next boot compares again, not tomorrow", ("下次开机再比" in line, "明天" in line), (True, False))

    if fails:
        print(f"\n{len(fails)} failed")
        sys.exit(1)
    print("\nall passed")


def _part_error_evidence():
    """The 2026-10-06 fix bill L: today's relay.log to COS, one object per day.

Four things pinned here, per the bill:
* a relay-error push ends with 「日志：<链接>，出事时刻 HH:MM」 when the upload
  landed; a failed upload does not block the push and is noted daily-report-only;
* the shutdown moment uploads the final copy before the power-off command;
* the error path uploads at most once a minute (the same key overwrites anyway);
* the whole-day log is capped: a bigger day uploads its last part and says so.

The uploader is a fake; nothing here touches the real COS bucket.

    Formerly test_error_evidence.py.
    """
    import json
    import logging
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.alarm import errwatch
    from ark_relay.features.evidence import error_evidence
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ, Config


    class FakeUp:
        """One COS store that records what was PUT, in order, and answers with a URL."""

        def __init__(self, fail=None):
            self.uploads = []          # (key, bytes)
            self.fail = fail           # Exception to raise on upload, or None
            self.timeouts = []         # the timeout each PUT was given

        def upload(self, path, timeout=900):
            self.timeouts.append(timeout)
            data = path.read_bytes()
            key = f"daily/{path.name}"
            if self.fail is not None:
                raise self.fail
            self.uploads.append((key, data))
            return {"name": path.name, "url": f"https://host/{key}", "store": "cos", "key": key}


    def cfg_with(relay_log: "Path | None", automas: "Path | None", state: Path) -> Config:
        cfg = Config()
        cfg.state_dir = state
        cfg.automas_dir = automas
        cfg.cos_secret_id = cfg.cos_secret_key = cfg.cos_bucket = cfg.cos_region = "x"
        if relay_log is not None:
            os.environ["ARK_LOG_FILE"] = str(relay_log)
        else:
            os.environ.pop("ARK_LOG_FILE", None)
        return cfg


    DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    NOW = DAY.replace(hour=9, minute=52)


    def stamp(day: datetime, hh: int, mm: int, fmt: str = "%m-%d %H:%M:%S") -> str:
        """The server-clock moment day hh:mm as the machine stamps it: in its own local
    time (relay.log: logging's asctime, time.localtime; AUTO-MAS's app.log the
    same), which evidence._line_ts reads back as local time. On the machine local
    time is Beijing; the Mac (Tokyo) was an hour off, the Windows CI runner (UTC)
    eight - 09:00 written as Beijing read back as 17:00 and fell outside the
    00:00-09:52 day (run 37519943859)."""
        return day.replace(hour=hh, minute=mm).astimezone().strftime(fmt)


    def write_day_log(p: Path, day: datetime, lines):
        p.parent.mkdir(parents=True, exist_ok=True)
        out = []
        for hh, mm, text in lines:
            out.append(f"{stamp(day, hh, mm)} INFO    ark.test  {text}")
        p.write_text("\n".join(out) + "\n", encoding="utf-8")


    print("[whole-day relay.log + app.log go up as one dated object each, same key all day]")
    st = tmpdir()
    relay = tmpdir() / "relay.log"
    automas = tmpdir() / "AUTO-MAS"
    write_day_log(relay, DAY, [(9, 0, "first"), (9, 52, "second")])
    (automas / "debug").mkdir(parents=True)
    app = automas / "debug" / "app.log"
    app.write_text(f"{stamp(DAY, 9, 50, '%Y-%m-%d %H:%M:%S')} INFO first\n", encoding="utf-8")
    up = FakeUp()
    error_evidence._last_attempt[0] = 0.0
    got = error_evidence.upload_daily_logs(cfg_with(relay, automas, st), force=True, now=NOW,
                                           clock=lambda: 1000.0, uploader=up)
    check("both objects went up", sorted(k.split("/")[1] for k, _ in up.uploads),
          [f"automas-app-{DAY:%Y-%m-%d}.log", f"relay-{DAY:%Y-%m-%d}.log"])
    check("the relay object's URL is returned",
          got["url"], f"https://host/daily/relay-{DAY:%Y-%m-%d}.log")
    check("the relay object holds both lines", b"second" in dict(up.uploads)[f"daily/relay-{DAY:%Y-%m-%d}.log"])
    check("not truncated", got["truncated"], False)

    print("\n[the push link is the signed GET: the bucket is private, the plain URL answers 403]")


    class SignedUp(FakeUp):
        def upload(self, path, timeout=900):
            got = super().upload(path, timeout)
            return dict(got, page=got["url"] + "?q-signature=abc")


    error_evidence._last_attempt[0] = 0.0
    got = error_evidence.upload_daily_logs(cfg_with(relay, None, st), force=True, now=NOW,
                                           clock=lambda: 1000.0, uploader=SignedUp())
    check("the signed page is what the push carries",
          got["url"], f"https://host/daily/relay-{DAY:%Y-%m-%d}.log?q-signature=abc")
    from ark_relay.features.evidence.evidence import Cos
    cos = Cos("AKID", "secret", "b-1", "ap-shanghai")
    link = cos.signed_get("daily/relay-x.log", ttl=60)
    check("Cos.signed_get: same object URL plus a GET signature",
          link.split("?")[0] == "https://b-1.cos.ap-shanghai.myqcloud.com/daily/relay-x.log"
          and "q-signature=" in link and cos.authorization("GET", "daily/relay-x.log", ttl=60) in link)
    span = cos.signed_get("k").split("q-sign-time=")[1].split("&")[0].split(";")
    check("Cos.signed_get lasts as long as the 30-day bucket keeps the object (s17 F3)",
          int(span[1]) - int(span[0]) >= 30 * 86400, True)
    check("a log goes up as text (opens in the phone's browser)", Cos._content_type(Path("relay-x.log")),
          "text/plain; charset=utf-8")
    check("anything else stays octet-stream", Cos._content_type(Path("x.zip")), "application/octet-stream")

    print("\n[the poster OCR cache goes up as a sample, once per change, and never breaks the push]")
    st_ocr = tmpdir()
    (st_ocr / "desktop").mkdir()
    (st_ocr / "desktop" / "image-ocr.json").write_text('{"https://x/poster.jpg#2x": []}', encoding="utf-8")
    up = FakeUp()
    error_evidence._last_attempt[0] = 0.0
    error_evidence._ocr_sent[0] = 0.0
    error_evidence.upload_daily_logs(cfg_with(relay, None, st_ocr), force=True, now=NOW, clock=lambda: 1000.0, uploader=up)
    check("the OCR cache went up next to the relay log",
          sorted(k.split("/")[1] for k, _ in up.uploads), [f"image-ocr-{DAY:%Y-%m-%d}.json", f"relay-{DAY:%Y-%m-%d}.log"])
    error_evidence.upload_daily_logs(cfg_with(relay, None, st_ocr), force=True, now=NOW, clock=lambda: 1000.0, uploader=up)
    check("an unchanged cache is not sent again", sum(k.endswith(".json") for k, _ in up.uploads), 1)
    (st_ocr / "desktop" / "image-ocr.json").write_text('{"https://x/poster2.jpg#2x": []}', encoding="utf-8")
    os.utime(st_ocr / "desktop" / "image-ocr.json", (error_evidence._ocr_sent[0] + 5, error_evidence._ocr_sent[0] + 5))
    error_evidence.upload_daily_logs(cfg_with(relay, None, st_ocr), force=True, now=NOW, clock=lambda: 1000.0, uploader=up)
    check("a changed cache is sent again", sum(k.endswith(".json") for k, _ in up.uploads), 2)
    error_evidence._ocr_sent[0] = 0.0
    got = error_evidence.upload_daily_logs(cfg_with(relay, None, st_ocr), force=True, now=NOW, clock=lambda: 1000.0,
                                           uploader=FakeUp(fail=RuntimeError("boom")))
    check("a failed upload of the samples is not an error of the push", [e for e in got["errors"] if "image-ocr" in e], [])

    print("\n[error path: one upload a minute at most; force bypasses the throttle]")
    up = FakeUp()
    error_evidence._last_attempt[0] = 0.0
    error_evidence.upload_daily_logs(cfg_with(relay, None, st), force=False, now=NOW, clock=lambda: 1000.0, uploader=up)
    got = error_evidence.upload_daily_logs(cfg_with(relay, None, st), force=False, now=NOW, clock=lambda: 1005.0, uploader=up)
    check("second call inside the minute was skipped", got["skipped"], True)
    check("so only the first went up", len(up.uploads), 1)
    check("the skipped call still carries the link of the object already there",
          got["url"], f"https://host/daily/relay-{DAY:%Y-%m-%d}.log")
    check("a PUT gets a 60 s timeout, not Cos.upload's 900 s default (a stalled line must not hold a push or the power-off)",
          set(up.timeouts), {error_evidence.UPLOAD_TIMEOUT_S})
    error_evidence.upload_daily_logs(cfg_with(relay, None, st), force=True, now=NOW, clock=lambda: 1005.0, uploader=up)
    check("force uploaded anyway (the shutdown final copy)", len(up.uploads), 2)

    print("\n[a failed upload is reported in the result, never raised]")
    error_evidence._last_attempt[0] = 0.0
    got = error_evidence.upload_daily_logs(cfg_with(relay, None, st), force=True, now=NOW,
                                           clock=lambda: 1000.0, uploader=FakeUp(fail=RuntimeError("boom")))
    check("errors carry the reason", got["errors"], ["relay: RuntimeError: boom"])

    print("\n[the whole-day log is capped: the last part goes up and says so]")
    big = tmpdir() / "big-relay.log"
    big.write_bytes(f"{stamp(DAY, 9, 0)} INFO    ark.test  keepme\n".encode())
    # Fake a day bigger than the cap by shrinking the cap for the test.
    error_evidence._last_attempt[0] = 0.0
    small_up = FakeUp()
    old_cap = error_evidence.DAY_MAX_BYTES
    error_evidence.DAY_MAX_BYTES = 40
    try:
        body = "".join(f"{stamp(DAY, 9, i)} INFO    ark.test  line{i}\n" for i in range(10))
        big.write_text(body, encoding="utf-8")
        got = error_evidence.upload_daily_logs(cfg_with(big, None, st), force=True, now=NOW,
                                               clock=lambda: 1000.0, uploader=small_up)
        data = dict(small_up.uploads)[f"daily/relay-{DAY:%Y-%m-%d}.log"]
        check("the cap was applied", got["truncated"], True)
        check("the tail survived", b"line9" in data, True)
        check("the head was cut", b"line0" in data, False)

        # The cut right at the start of a line keeps that line (Windows CI 2026-10-07:
        # \r\n lines exactly as long as the cap left nothing, and nothing went up).
        # Bytes, so every platform sees the same lengths.
        lines = [f"{stamp(DAY, 9, i)} INFO    ark.test  line{i}\n".encode() for i in range(10)]
        big.write_bytes(b"".join(lines))
        error_evidence.DAY_MAX_BYTES = len(lines[-1])
        error_evidence._last_attempt[0] = 0.0
        edge_up = FakeUp()
        got = error_evidence.upload_daily_logs(cfg_with(big, None, st), force=True, now=NOW,
                                               clock=lambda: 1000.0, uploader=edge_up)
        check("a cut on a line start: the day still went up and is truncated",
              (sorted(k for k, _ in edge_up.uploads), got["truncated"]),
              ([f"daily/relay-{DAY:%Y-%m-%d}.log"], True))
        check("a cut on a line start keeps that whole line, nothing else",
              dict(edge_up.uploads).get(f"daily/relay-{DAY:%Y-%m-%d}.log"), lines[-1])
    finally:
        error_evidence.DAY_MAX_BYTES = old_cap


    print("\n[a relay-error push ends with 「日志：…」 when the upload landed]")
    ARK_LOGGER = logging.getLogger(errwatch.ARK)


    class Captures:
        """errwatch's notifier: records what reached the group, accepts everything."""

        def __init__(self):
            self.sent = []

        def send_group(self, title, body):
            self.sent.append((title, body))
            return []

        def send(self, title, body, **kw):
            self.sent.append((title, body))
            return []


    def watch():
        sd = tmpdir()
        h = errwatch.ErrorKindAlert(Captures(), state_dir=sd, known={}, retry=(3600.0,),
                                    fallback_after=1e9)
        ARK_LOGGER.addHandler(h)
        return h, sd


    def unwatch(h):
        ARK_LOGGER.removeHandler(h)
        h.close()


    real_up = error_evidence._last_attempt[0]
    try:
        h, sd = watch()
        errwatch.set_evidence_uploader(lambda: {"url": "https://host/daily/relay-x.log", "at": "09:52",
                                                "truncated": False, "errors": []})
        logging.getLogger("ark.test_evidence").warning("something broke")
        h.drain(timeout=5.0)
        bodies = [b for t, b in h._notifier.sent]
        check("the push carries the log link",
              any("日志：https://host/daily/relay-x.log，出事时刻 " in b for b in bodies), True)
        check("the push itself went out", len(bodies), 1)
        unwatch(h)

        print("  …a failed upload does not block the push, and the push says it (not the daily report)")
        # Until 2026-10-11 the failure was a daily-only row; the user, 17:43: 「如果不是自己好了禁止只进日报」.
        h, sd = watch()
        errwatch.set_evidence_uploader(lambda: {"url": "", "at": "09:52", "truncated": False,
                                                "errors": ["relay: RuntimeError: boom"]})
        logging.getLogger("ark.test_evidence").warning("something broke again")
        h.drain(timeout=5.0)
        bodies = [b for t, b in h._notifier.sent]
        check("the push still went out", len(bodies), 1)
        check("it has no log link", any("日志：" in b for b in bodies), False)
        check("it says the day's log did not go up", [texts.EVIDENCE_UPLOAD_FAILED in b for b in bodies], [True])
        rows = errwatch.day_faults(sd, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
        check("no daily-only row any more", [r for r in rows if r.get("daily_only")], [])
        unwatch(h)

        # The deploy gate's coverage trace follows the main thread only; these run on the
        # push thread above, so check the texts here too, directly.
        print("  …the link text and the upload-failed text, checked directly")
        check("link text: url and moment", texts.evidence_link("https://host/x.log", "09:52"),
              "日志：https://host/x.log，出事时刻 09:52")
        check("link text: says so when the day was cut", "只传了最后一部分" in texts.evidence_link("u", "09:52", True), True)
        check("upload-failed text reads as plain words", texts.plain(texts.EVIDENCE_UPLOAD_FAILED), [])
        check("errwatch has no daily-only door any more", hasattr(errwatch.ErrorKindAlert, "note_daily"), False)
    finally:
        errwatch.set_evidence_uploader(None)
        error_evidence._last_attempt[0] = real_up

    print("\n[the shutdown moment uploads the final copy before the power-off command]")
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import Notifier
    from ark_relay.core import engine as eng_mod

    AUTOMAS2 = tmpdir() / "AUTO-MAS2"
    (AUTOMAS2 / "config").mkdir(parents=True)
    (AUTOMAS2 / "config" / "QueueConfig.json").write_text(json.dumps({
        "instances": [{"uid": "q1"}],
        "q1": {"Info": {"Name": "Evening-MAA", "TimeEnabled": True, "AfterAccomplish": "NoAction"},
               "SubConfigsInfo": {"TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "21:30"}}},
                                  "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}}}}}), encoding="utf-8")
    (AUTOMAS2 / "config" / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "s1"}],
        "s1": {"Info": {"Name": "arknights", "Path": "D:\\MAA"},
               "SubConfigsInfo": {"UserData": {"u1": {"Info": {"Name": "arknights"}}}}}}), encoding="utf-8")

    cfg2 = Config()
    cfg2.state_dir = tmpdir()
    cfg2.automas_dir = AUTOMAS2
    cfg2.shutdown_after_run = True
    cfg2.shutdown_min_uptime = 0
    E = eng_mod.Engine(cfg2, source=None, state=State(cfg2.state_dir), notifier=Notifier(cfg2))
    E._scripts_running = lambda: False
    E._idle_checkpoint = lambda now=None: False
    E._handled_any = True
    E._started_at = datetime(2026, 8, 21, 22, 20, tzinfo=SERVER_TZ)
    E._last_round_manual = lambda now, entries: False
    E._unfinished_queues = lambda now, entries: []
    E._verify_outcome = lambda r: None
    E._deferred_update_busy = lambda: False
    E._report_cutoff = lambda now: now - timedelta(hours=1)
    E.state.report_sent = lambda d: True
    # The queue already ran: one done record in the ledger makes the gate pass.
    day = "2026-08-21"
    (E.state.dir / f"ledger-{day}.jsonl").write_text(json.dumps({
        "script": "MAA", "started": f"{day}T21:31:00+08:00", "finished": f"{day}T22:15:00+08:00",
        "ok": True, "run_id": "x"}) + "\n", encoding="utf-8")
    E._shutdown_key = lambda now: day
    E._boot_time = lambda now: datetime(2026, 8, 21, 21, 20, tzinfo=SERVER_TZ)

    order = []
    real_upload = error_evidence.upload_daily_logs
    error_evidence.upload_daily_logs = lambda cfg, **kw: order.append("upload") or {"url": "", "at": "", "errors": []}
    E._power_off = lambda: order.append("poweroff") or True
    try:
        E._maybe_shutdown(datetime(2026, 8, 21, 23, 0, tzinfo=SERVER_TZ))
        check("the final upload runs before the power-off command", order, ["upload", "poweroff"])
    finally:
        error_evidence.upload_daily_logs = real_upload

    print("\n[audit 11-08 C-08: a throttled call after a failed upload carries that failure]")


    class DownUp:
        def upload(self, path, timeout=0):
            raise OSError("connection reset")


    error_evidence._last_attempt[0] = 0.0
    first = error_evidence.upload_daily_logs(cfg_with(relay, None, st), force=True, now=NOW,
                                             clock=lambda: 2000.0, uploader=DownUp())
    check("the real attempt failed", bool(first["errors"]), True)
    again = error_evidence.upload_daily_logs(cfg_with(relay, None, st), now=NOW, clock=lambda: 2010.0, uploader=DownUp())
    check("10 s later: throttled, and it says the last one failed", (again["skipped"], again["errors"]),
          (True, first["errors"]))
    error_evidence._last_attempt[0] = 0.0


def _part_game_evidence():
    """The daily report counts a task as done only with evidence from the game.

2026-10-05: four MaaEnd tasks (gifts, gear assembly, delivery jobs, environment
monitoring) had nothing in the log but 「任务开始」 / 「任务完成」 and were counted
as done - the program's own word. Evidence is a line the run wrote between a
task's start and its finish (an item gained, a sanity reading, ...), a
task-end picture (task_shots.py), or for the weekly items the game's own
counter. A task without any is named 「没证据，不算完成」: neither done nor failed,
and the day's title is no longer 全绿 for it. No alarm is raised for it.

    Formerly test_game_evidence.py.
    """
    import os
    from datetime import datetime, timedelta
    from types import SimpleNamespace


    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector, texts
    from ark_relay.features.verify import collector_maaend, collector_okww, outcome
    from ark_relay.features.alarm import handle
    from ark_relay.core import ledger as core
    from ark_relay.core.config import SERVER_TZ, RunRecord


    FX = Path(__file__).parent / "fixtures"
    FULL = (FX / "maaend_full_2026-09-01.log").read_text(encoding="utf-8")

    print("[每一项的证据：开始和完成之间 MaaEnd 自己写的别的行]")
    ev = collector_maaend.task_evidence(FULL)
    check("只有开始/完成两行的：没证据", (ev["赠送干员礼物"], ev["装备制造"], ev["拜访好友"]), ("", "", ""))
    check("有「获得」行的：那一行", ev["基建任务"], "获得 燎石子簇 ×1")
    check("读到身上没有加强剂也是游戏里的读数", ev["应急理智加强剂"], "没有应急理智加强剂，结束任务")
    retry = ("[2026-10-05 10:41:05.000] 任务开始: 🎁赠送干员礼物\n[2026-10-05 10:41:09.000] 任务完成: 🎁赠送干员礼物\n"
             "[2026-10-05 11:00:00.000] 任务开始: 🎁赠送干员礼物\n[2026-10-05 11:00:03.000] 获得 信用 ×400\n"
             "[2026-10-05 11:00:05.000] 任务完成: 🎁赠送干员礼物\n"
             "[2026-10-05 11:01:00.000] 任务开始: 🔧装备制造\n[2026-10-05 11:01:01.000] 获得 嵌晶玉 ×25\n"
             "[2026-10-05 11:01:02.000] 任务失败: 🔧装备制造\n")
    ev2 = collector_maaend.task_evidence(retry)
    check("同一项跑两次：有证据的那次算", ev2.get("赠送干员礼物"), "获得 信用 ×400")
    check("失败的那项不进证据表", "装备制造" in ev2, False)
    check("每项的起止时间（最后一次）", collector_maaend.task_times(retry)["赠送干员礼物"],
          (datetime(2026, 10, 5, 11, 0, 0), datetime(2026, 10, 5, 11, 0, 5)))
    log_path = TMP / "MaaEnd.log"
    log_path.write_text(FULL, encoding="utf-8")
    parsed = collector.parse_maaend_log(log_path)
    check("解析结果带证据表", parsed.get("tasks_evidence", {}).get("信用点购物"), "获得 折金票 ×2000")

    print("\n[任务结束截图也算证据（task_shots 存的图，按名字和完成时刻对上）]")
    ROUND = ("[2026-10-05 10:41:05.000] 任务开始: 🎁赠送干员礼物\n[2026-10-05 10:42:10.000] 任务完成: 🎁赠送干员礼物\n"
             "[2026-10-05 10:42:11.000] 任务开始: 🔧装备制造\n[2026-10-05 10:43:20.000] 任务完成: 🔧装备制造\n"
             "[2026-10-05 10:43:21.000] 任务开始: 🚚转交委托\n[2026-10-05 10:44:30.000] 任务完成: 🚚转交委托\n")
    hist = TMP / "MaaEnd-06-39-48.log"
    hist.write_text(ROUND, encoding="utf-8")
    STATE = TMP / "state"
    run_dir = STATE / "shots" / "2026-10-05" / "MaaEnd-10-41-05"
    run_dir.mkdir(parents=True)


    def picture(name, at):
        p = run_dir / f"{name}.png"
        p.write_bytes(b"png")
        ts = datetime.strptime(f"2026-10-05 {at}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=SERVER_TZ).timestamp()
        os.utime(p, (ts, ts))


    picture("104105-赠送干员礼物", "10:41:08")     # the launch's first-start picture: not an end picture
    picture("104213-赠送干员礼物", "10:42:15")     # its end picture
    picture("104322-装备制造", "10:43:25")         # end picture of 装备制造
    started = datetime(2026, 10, 5, 10, 41, 0, tzinfo=SERVER_TZ)
    rec = RunRecord(run_id="2026-10-05/endfield/MaaEnd-06-39-48", script="MaaEnd", user="endfield",
                    started=started, finished=started + timedelta(minutes=4), ok=True,
                    raw={"tasks_done": ["赠送干员礼物", "装备制造", "转交委托"]}, log_path=hist)
    eng = SimpleNamespace(cfg=SimpleNamespace(state_dir=STATE))
    handle._mark_task_shots(eng, rec)
    check("有结束截图的两项记下", rec.raw.get("tasks_shot"), ["赠送干员礼物", "装备制造"])
    rec.raw["tasks_evidence"] = collector_maaend.task_evidence(ROUND)
    check("没截图也没读数的那项没证据", core.maaend_unverified(rec.raw), ["转交委托"])
    only_start = RunRecord(run_id="x", script="MaaEnd", user="endfield", started=started,
                           finished=started + timedelta(minutes=4), ok=True, raw={}, log_path=hist)
    (run_dir / "104213-赠送干员礼物.png").unlink()
    (run_dir / "104322-装备制造.png").unlink()
    handle._mark_task_shots(eng, only_start)
    check("只有开跑前那张（离完成一分多钟）不算", only_start.raw.get("tasks_shot"), None)
    # refresh_raw re-parses only the log; the picture list must survive it.
    hdir = TMP / "history" / "2026-10-05" / "endfield"
    hdir.mkdir(parents=True)
    (hdir / "MaaEnd-06-39-48.log").write_text(ROUND, encoding="utf-8")
    entry = {"run_id": rec.run_id, "script": "MaaEnd", "ok": True, "raw": dict(rec.raw)}
    fresh = collector.refresh_raw(entry, TMP / "history")
    check("重算 raw 不丢截图证据", fresh["raw"].get("tasks_shot"), ["赠送干员礼物", "装备制造"])
    check("重算后证据表还在", core.maaend_unverified(fresh["raw"]), ["转交委托"])

    print("\n[日报：只把有证据的算做了，没证据的点名；标题不再是全绿]")


    def ent(run_id, script, hh, mm, dur, ok=True, **kw):
        st = datetime(2026, 10, 5, hh, mm, tzinfo=SERVER_TZ)
        e = {"run_id": run_id, "script": script, "user": "u", "ok": ok,
             "started": st.isoformat(), "finished": (st + timedelta(minutes=dur)).isoformat(),
             "duration_known": True, "transitional": False, "failed_tasks": [] if ok else ["x"],
             "raw": {}, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}
        e.update(kw)
        return e


    end = ent("2026-10-05/endfield/MaaEnd-06-39-48", "MaaEnd", 10, 41, 4, raw=fresh["raw"])
    title, body = core.format_daily("2026-10-05", [end])
    check("做了只列有证据的", "做了 赠送干员礼物、装备制造" in body)
    check("没证据的点名，不算完成", f"{core.UNVERIFIED}：转交委托" in body)
    check("标题：没证据，不是全绿", title, "📋 10-05 · 终末地 1 项没证据，不算完成 ❔")
    check("脚注只列有证据的", core.daily_footnote([end]), "———————\n日常：1.赠送干员礼物 2.装备制造")
    all_ok = ent("2026-10-05/endfield/MaaEnd-06-39-48", "MaaEnd", 10, 41, 4,
                 raw=dict(fresh["raw"], tasks_shot=["赠送干员礼物", "装备制造", "转交委托"]))
    check("三项都有证据：全绿", core.format_daily("2026-10-05", [all_ok])[0], "📋 10-05 · 全绿 ✅")
    old = ent("2026-10-05/endfield/MaaEnd-1", "MaaEnd", 9, 0, 4, raw={"tasks_done": ["赠送干员礼物"]})
    check("账上没有证据表（日志找不到了）：按没证据", core.maaend_unverified(old["raw"]), ["赠送干员礼物"])
    later = ent("2026-10-05/endfield/MaaEnd-2", "MaaEnd", 11, 0, 4,
                raw={"tasks_done": ["赠送干员礼物"], "tasks_evidence": {"赠送干员礼物": "获得 信用 ×400"}})
    check("同一天另一趟有证据：整天不算没证据", core.day_unverified([old, later]), [])
    check("红按钮停掉的那趟不算", core.day_unverified([dict(old, raw=dict(old["raw"], manual_stop="09:01 停一切"))]), [])

    print("\n[重试里「做成了」也要证据]")
    failed = ent("2026-10-05/endfield/MaaEnd-0", "MaaEnd", 8, 0, 4, ok=False, failed_tasks=["转交委托"])
    retry_bare = ent("2026-10-05/endfield/MaaEnd-3", "MaaEnd", 8, 10, 2,
                     raw={"tasks_done": ["转交委托"], "tasks_evidence": {"转交委托": ""}})
    check("重试只有「任务完成」：不说做成了", core.retried_notes([failed, retry_bare])[failed["run_id"]],
          "转交委托　后来在 08:10（东京 09:10）开始的那趟重试里程序说做完了，但没证据，不算完成")
    retry_ev = dict(retry_bare, raw={"tasks_done": ["转交委托"], "tasks_evidence": {"转交委托": "获得 信用 ×100"}})
    check("重试有读数：做成了", core.retried_notes([failed, retry_ev])[failed["run_id"]], "转交委托　后来在 08:10（东京 09:10）开始的那趟重试里做成了")

    print("\n[明日方舟剿灭：没读到「剿灭模式 x/y」不算打满]")
    anni = ent("2026-10-05/arknights/MAA-1", "MAA", 21, 30, 20, raw={"annihilation": True, "annihilation_done": True})
    t, b = core.format_daily("2026-10-05", [anni])
    check("不再说「本周剿灭此前已完成」", "此前已完成" in b, False)
    check("说没读到进度、不算打满", "没读到剿灭进度，本周按没打满算" in b)
    check("标题点名", t, "📋 10-05 · 明日方舟 1 项没证据，不算完成 ❔")
    fought = ent("2026-10-05/arknights/MAA-2", "MAA", 21, 30, 20, raw={"annihilation": True, "sanity_spent": 25})
    check("打了但没进度：也不说「已打剿灭」", "已打剿灭" in core.format_daily("2026-10-05", [fought])[1], False)
    full = ent("2026-10-05/arknights/MAA-3", "MAA", 21, 30, 20,
               raw={"annihilation": True, "annihilation_progress": [1800, 1800], "annihilation_done": True})
    check("读到 1800/1800：打满，全绿", core.format_daily("2026-10-05", [full])[0], "📋 10-05 · 全绿 ✅")
    short = ent("2026-10-05/arknights/MAA-4", "MAA", 9, 0, 2, ok=False, failed_tasks=["MAA 部分任务执行失败"],
                raw={"annihilation": True, "maa_sanity_short": {"have": 17, "cost": 25}})
    check("理智不够没打的：不算没证据（另有说法）", core.day_unverified([short]), [])

    print("\n[鸣潮周常乐园：只跑了没读到做完，不算完成]")
    G = "2026-09-14 10:02:11,001 INFO TaskExecutor GardenTask:Garden current: [Box(name='2000/2000')]\n"
    steps = collector_okww._okww_steps(G, 0)
    check("步骤写不算完成", steps, ["周常乐园（没读到做完，不算完成）"])
    ww = ent("2026-10-05/wuwa/OK-WW-1", "OK-WW", 9, 0, 20, raw={"okww_steps": steps})
    check("标题点名", core.format_daily("2026-10-05", [ww])[0], "📋 10-05 · 鸣潮 1 项没证据，不算完成 ❔")
    done_g = collector_okww._okww_steps(G + "2026-09-14 10:02:12,001 INFO TaskExecutor GardenTask:乐园任务完成, 已达到上限\n", 0)
    check("读到「乐园任务完成」：做完", done_g, ["周常乐园（本周已完成）"])

    print("\n[只进日报，不报警：结果核对不因没证据而判没干完]")
    check("MaaEnd 结果核对不变（没证据不是失败）",
          [c.label for c in outcome.maaend_checks(ROUND, [], own_log=False) if not c.ok and "转交委托" in c.label], [])

    print("\n[文案是人话]")
    check("没证据那句", texts.plain(core.UNVERIFIED), [])
    check("标题那句", texts.plain("终末地 1 项没证据，不算完成 ❔"), [])

    print("\n[MaaEnd 自己的「停止任务」不是游戏里的任务（10-08 日报「终末地 1 项没证据」就是它）]")
    # The 10:32 attempt of 2026-10-08 (evidence bundle MaaEnd-06-31-06): two tasks, then
    # MaaEnd stopped itself after its failed scene check (__SceneCheckAbortPipeline) and
    # the log says 「任务完成: 停止任务」. A record booked before raw['tasks_trail'] (no such
    # key, as here) keeps the picture rule; the trail rule is in test_mc28.py.
    stop = collector.parse_maaend_log(FX / "maaend_stop_task_2026-10-08.log")
    check("日志里解析出了停止任务", "停止任务" in (stop.get("tasks_done") or []), True)
    stop["tasks_shot"] = ["赠送干员礼物", "装备制造"]   # 103411 / 103416 in that bundle
    check("两项都有任务结束截图：这一趟没有没证据的项", core.maaend_unverified(stop), [])
    check("日报整天不算没证据", core.day_unverified([{"script": "MaaEnd", "ok": False, "raw": stop}]), [])
    check("日常清单里也不列停止任务", "停止任务" in core._maaend_listed(stop), False)

    print("\n[the stop task after the closing task does not change whether the round closed]")
    # MaaTaskerPostStop is an EmptyTask whose run() returns true (MaaFramework
    # v5.14.2 Task/EmptyTask.h), so MXU prints 「任务开始/任务完成: 停止任务」 whenever
    # MaaEnd is asked to stop (shape: fixtures/maaend_stop_task_2026-10-08.log lines 20-21).
    base = (FX / "maaend-farm-drops" / "2026-09-28a.log").read_text(encoding="utf-8")
    check("the 09-28 round as it is: all done", collector_maaend._maaend_all_done(base), True)
    stopped = base.rstrip("\n") + ("\n[2026-09-28 11:22:40.413] 任务开始: 停止任务"
                                   "\n[2026-09-28 11:22:40.513] 任务完成: 停止任务\n")
    check("with the stop task after 关闭游戏: still all done", collector_maaend._maaend_all_done(stopped), True)
    cut = base[:base.rindex("[2026-09-28 11:22:07.978]")] + ("[2026-09-28 11:22:40.413] 任务开始: 停止任务\n"
                                                             "[2026-09-28 11:22:40.513] 任务完成: 停止任务\n")
    check("the stop task does not stand in for a missing 关闭游戏", collector_maaend._maaend_all_done(cut), False)

    print()
    print("\n[audit 11-08 B-07: a scene check or a warning is no evidence]")
    _stop = (FX / "maaend_stop_task_2026-10-08.log").read_text(encoding="utf-8")
    check("10-08 10:34 装备制造: its scene-check lines are not evidence",
          collector_maaend.task_evidence(_stop).get("装备制造"), "")
    _w = ("[2026-11-08 10:00:00.000] 任务开始: 🚚转交委托\n[2026-11-08 10:00:01.000] [WRN] something\n"
          "[2026-11-08 10:00:02.000] FailureCollector dump\n[2026-11-08 10:00:03.000] 任务完成: 🚚转交委托\n")
    check("[WRN] and FailureCollector lines are not evidence", collector_maaend.task_evidence(_w).get("转交委托"), "")

    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_held_push_keeps_evidence():
    """A held failure pushed later is pushed with the evidence captured when it was held.

Audit 2026-10-13 review of s7 #2 (fdc53123): a held OK-WW / MaaEnd failure pushed
after a person's hand-started success went through handle._failure_alarm, which
captured evidence again into the held run's folder - the person's screen, log tail
and MaaEnd debug logs over the real ones. manualstops._push_before_stop (a held
failure a 停一切 cut off) had the same flaw. Each capture is counted per run here.

    Formerly test_held_push_keeps_evidence.py.
    """
    import json
    import os
    from collections import Counter
    from datetime import datetime, timedelta


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "debug").mkdir()
    for name in ("QueueConfig.json", "ScriptConfig.json"):
        (AUTOMAS / "config" / name).write_text(json.dumps({"instances": []}), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.alarm import handle, manualstops
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    class Notes:
        def __init__(self):
            self.sent, self.bodies = [], []

        def send(self, title, body="", **kw):
            self.sent.append((title, kw.get("alert", False)))
            self.bodies.append(body)
            return []      # no errors: sent


    class Src:
        def fetch(self, seen):
            return []


    captures = Counter()
    handle._archive_okww_evidence = lambda eng, r: captures.update([r.run_id])
    handle._weekly_gates = lambda eng, r: None
    handle._ship_evidence = lambda eng, r: ""
    HAND = {"OK-WW-ok", "MaaEnd-ok"}
    handle._hand_started = lambda eng, r: "task-1" if r.run_id in HAND else ""


    def build():
        cfg = Config()
        cfg.state_dir = TMP / "state"
        cfg.state_dir.mkdir(exist_ok=True)
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: captures.update([r.run_id])
        return e


    def rec(run_id, started, ok=False, script="OK-WW", user="wuthering"):
        return RunRecord(run_id=run_id, script=script, user=user, started=started,
                         finished=started + timedelta(minutes=5), ok=ok,
                         failed_tasks=[] if ok else ["日常任务"], raw={})


    T0 = datetime(2026, 10, 12, 6, 0, tzinfo=SERVER_TZ)

    for script, user in (("OK-WW", "wuthering"), ("MaaEnd", "endfield")):
        print(f"\n[{script}：定时那趟失败压着，后来有人手动跑成 → 照报，不再取证]")
        captures.clear()
        e = build()
        e._handle(rec(f"{script}-fail", T0, script=script, user=user))
        check("压着了", (script, user) in e._pending)
        check("压着时取了一次证", captures[f"{script}-fail"], 1)
        e._handle(rec(f"{script}-ok", T0 + timedelta(hours=1), ok=True, script=script, user=user))
        check("压着的那条报出去了", (script, user) in e._pending, False)
        check("报的时候没再往它的证据夹里取证（还是 1 次）", captures[f"{script}-fail"], 1)

        print(f"\n[{script}：停一切前压着的失败 → 照报，不再取证]")
        captures.clear()
        e = build()
        held = rec(f"{script}-fail2", T0, script=script, user=user)
        e._handle(held)
        manualstops._push_before_stop(e, held, "06:30 停一切")
        check("停一切那条报出去了", bool(e.notifier.sent))
        check("报的时候没再取证（还是 1 次）", captures[f"{script}-fail2"], 1)

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_task_shots():
    """MaaEnd task-end screenshots, and the evidence bundle every MAA / MaaEnd alarm carries.

2026-10-05: four MaaEnd tasks (gifts, gear assembly, delivery jobs, environment
monitoring) leave only 「任务开始」 / 「任务完成」 in the AUTO-MAS log, so whether they did anything could not be
checked; and the 12:30 MaaEnd alarm (an update restart, MaaEnd-07-30-14) went
out without a bundle, because the update-restart branch held the record before
_hold_for_retry could ship one.

The maafw.log lines are built in the shape of the real ones
(fixtures/collect-watch-2026-09-14/maafw-attempt3.log, each event once from the
dispatcher and once echoed by the agent); entries, task numbers and times are
2026-10-05's: entries and task_ids from MXU's debug/2026-10-05-2.log (10:41:05 /
10:41:07), times from AUTO-MAS history MaaEnd-06-39-48.log.

    Formerly test_task_shots.py.
    """
    import json
    import logging
    import os
    import zipfile
    from datetime import date, datetime


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (TMP / "history").mkdir()
    MAAEND = TMP / "maaend"
    (MAAEND / "debug").mkdir(parents=True)
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_MAAEND_DIR=str(MAAEND), ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="", COS_SECRET_ID="", COS_SECRET_KEY="",
                      COS_BUCKET="", COS_REGION="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.makeup import collect_retry
    from ark_relay.features.run import collect_watch
    from ark_relay.features.evidence import evidence, task_shots
    from ark_relay.features.alarm import handle
    from ark_relay.core import texts
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    # --------------------------------------------------------------- 10-05's round
    # (start time, end time, label as AUTO-MAS prints it, MaaFW entry)
    ROUND = [
        ("10:41:07", "10:43:33", "🎁赠送干员礼物", "GiftOperatorMain"),
        ("10:43:33", "10:43:53", "🔧装备制造", "GearAssemblyStart"),
        ("10:43:53", "10:45:58", "🤝拜访好友", "VisitFriendsMain"),
        ("10:45:59", "10:46:43", "🎁基建任务", "DijiangRewards"),
        ("10:46:43", "10:49:09", "🛍️信用点购物", "CreditShoppingMain"),
        ("10:49:09", "10:50:55", "🚚转交委托", "DeliveryJobsMain"),
        ("10:50:55", "10:52:16", "🛒据点交易", "OutpostTradingSchedule"),
        ("10:52:16", "10:52:22", "🌿环境监测", "EnvironmentMonitoringMain"),
        ("10:52:22", "10:52:43", "📦自动囤货", "AutoStockpileMain"),
        ("10:52:43", "10:53:07", "💰售卖弹性物资", "AutoSellMain"),
        ("10:53:08", "10:54:48", "🏪购买稳定物资", "AutoStockStapleSchedule"),
        ("10:54:48", "10:58:00", "⚔️协议空间", "ProtocolSpaceSchedule"),
        ("10:58:00", "11:01:54", "🗡️选剑演武", "TrialOfSwordmancyMain"),
        ("11:01:54", "11:28:22", "🧺自动采集", "AutoCollectSchedule"),
        ("11:28:22", "11:30:10", "📅日常奖励领取", "DailyRewardStart"),
        ("11:30:10", "11:30:13", "❌关闭游戏（PC）", "CloseGamePC"),
    ]
    LABELS = {entry: label for _, _, label, entry in ROUND}


    def ev(day, hms, kind, entry, task_id, px="7172"):
        details = json.dumps({"entry": entry, "hash": "1dd55aee6e9ac409", "task_id": task_id,
                              "uuid": "00000000001E0236"}, separators=(",", ":"))
        return (f"[{day} {hms}.264][INF][Px{px}][Tx32558][Utils/EventDispatcher.hpp][L65]"
                f"[MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] "
                f"[msg=Tasker.Task.{kind}] [details={details}] ")


    def round_lines(day="2026-10-05", first_id=200000001, rows=ROUND):
        out = []
        for i, (t0, t1, _, entry) in enumerate(rows):
            tid = first_id + i
            for kind, hms in (("Starting", t0), ("Succeeded", t1)):
                out.append(ev(day, hms, kind, entry, tid))
                out.append(ev(day, hms, kind, entry, tid, px="18500"))   # the agent's echo
        return out


    class Cam:
        """A fake desktop: writes a file, or raises on the calls listed in `bad`."""

        def __init__(self, bad=()):
            self.calls, self.bad = [], set(bad)

        def __call__(self, out_dir, name):
            self.calls.append(name)
            if len(self.calls) in self.bad:
                raise OSError("desktop agent did not come up")
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / f"{name}.png"
            p.write_bytes(b"\x89PNG fake " + name.encode())
            return p


    class Cfg:
        automas_dir = AUTOMAS
        maaend_dir = MAAEND
        state_dir = TMP / "watch-state"


    print("[10-05's round: one picture per 任务完成, plus the first 任务开始]")
    cam = Cam()
    shooter = task_shots.Shooter(Cfg.state_dir, LABELS, cam)
    w = collect_watch.Watcher(Cfg, None, shooter)
    w.feed("\n".join(round_lines()))
    check("nothing taken on the watcher's thread", cam.calls, [])
    check("17 queued (16 ends + the first start)", shooter.queue.qsize(), 17)
    check("all 17 taken", shooter.drain(), 17)
    run = Cfg.state_dir / "shots" / "2026-10-05" / "MaaEnd-10-41-07"
    names = sorted(p.name for p in run.iterdir())
    check("first: the 'before' picture", names[0], "104107-赠送干员礼物.png")
    check("the four that read nothing are all there",
          all(f in names for f in ("104333-赠送干员礼物.png", "104353-装备制造.png",
                                   "105055-转交委托.png", "105222-环境监测.png")), True)
    check("last: 关闭游戏（PC）, emoji gone", names[-1], "113013-关闭游戏（PC）.png")
    check("the echo does not double anything", len(names), 17)

    print("\n[a picture that fails does not stop the next ones; one warning per run]")
    cam = Cam(bad={2, 3})
    shooter = task_shots.Shooter(TMP / "s2", LABELS, cam)
    w = collect_watch.Watcher(Cfg, None, shooter)
    w.feed("\n".join(round_lines()[:12]))        # first three tasks: 1 start + 3 ends
    class Grab(logging.Handler):
        def __init__(self):
            super().__init__()
            self.msgs = []

        def emit(self, record):
            self.msgs.append(record.getMessage())


    grab = Grab()
    task_shots.log.addHandler(grab)
    check("4 tried, 2 saved", (shooter.drain(), len(cam.calls)), (2, 4))
    check("one warning for the run", sum("任务截图没拿到" in m for m in grab.msgs), 1)
    check("the ones after the failures still saved",
          sorted(p.name for p in (TMP / "s2" / "shots" / "2026-10-05" / "MaaEnd-10-41-07").iterdir()),
          ["104107-赠送干员礼物.png", "104558-拜访好友.png"])

    print("\n[a relaunch (MaaFW numbers from 200000001 again) is a new run with its own 'before' picture]")
    cam = Cam()
    shooter = task_shots.Shooter(TMP / "s3", LABELS, cam)
    w = collect_watch.Watcher(Cfg, None, shooter)
    w.feed("\n".join(round_lines()[:8]))
    w.feed("\n".join(round_lines(rows=[("11:35:00", "11:36:00", "🤝拜访好友", "VisitFriendsMain")])))
    shooter.drain()
    check("two run folders", sorted(p.name for p in (TMP / "s3" / "shots" / "2026-10-05").iterdir()),
          ["MaaEnd-10-41-07", "MaaEnd-11-35-00"])
    check("the relaunch's first start and its end",
          sorted(p.name for p in (TMP / "s3" / "shots" / "2026-10-05" / "MaaEnd-11-35-00").iterdir()),
          ["113500-拜访好友.png", "113600-拜访好友.png"])
    print("    自动采集 runs 26 minutes without a task event; that is not a new run")
    cam = Cam()
    shooter = task_shots.Shooter(TMP / "s4", LABELS, cam)
    for ln in round_lines():
        shooter.on_line(ln)
    shooter.drain()
    check("one folder for the whole round", [p.name for p in (TMP / "s4" / "shots" / "2026-10-05").iterdir()],
          ["MaaEnd-10-41-07"])

    print("\n[entry -> name comes from MaaEnd's own task declarations and zh_cn locale]")
    (MAAEND / "tasks").mkdir()
    (MAAEND / "interface.json").write_text(json.dumps({"version": "v2.32.0-beta.1",
                                                        "import": ["tasks/GiftOperator.json"]}), encoding="utf-8")
    (MAAEND / "tasks" / "GiftOperator.json").write_text(json.dumps({"task": [
        {"name": "GiftOperator", "label": "$task.GiftOperator.label", "entry": "GiftOperatorMain"}]}), encoding="utf-8")
    (MAAEND / "locales" / "interface").mkdir(parents=True)
    (MAAEND / "locales" / "interface" / "zh_cn.json").write_text(json.dumps(
        {"task.GiftOperator.label": "🎁赠送干员礼物"}, ensure_ascii=False), encoding="utf-8")
    check("GiftOperatorMain", task_shots.entry_labels(MAAEND), {"GiftOperatorMain": "🎁赠送干员礼物"})
    check("no MaaEnd dir", task_shots.entry_labels(None), {})
    cam = Cam()
    shooter = task_shots.Shooter(TMP / "s5", {}, cam)
    shooter.on_line(ev("2026-10-05", "10:43:33", "Succeeded", "GiftOperatorMain", 200000001))
    shooter.drain()
    check("unknown entry -> named by the entry", cam.calls, ["104333-GiftOperatorMain"])

    print("\n[off Windows nothing is started]")
    check("start() is None here", task_shots.start(Cfg) if os.name != "nt" else None, None)

    print("\n[evidence.desktop_shot: name it, move the agent's file]")
    src = TMP / "agent-shot.png"
    src.write_bytes(b"png")
    got = evidence.desktop_shot(Cfg, TMP / "out", lambda: src, name="104333-赠送干员礼物", move=True, quiet=True)
    check("named", got and got.name, "104333-赠送干员礼物.png")
    check("moved, not copied", (src.exists(), got.read_bytes() if got else b""), (False, b"png"))


    def boom():
        raise OSError("no desktop")


    check("a failing agent -> None", evidence.desktop_shot(Cfg, TMP / "out", boom, quiet=True), None)

    print("\n[retention: 3 days; only day folders under state/shots/]")
    st = TMP / "ret"
    for d in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"):
        (st / "shots" / d / "MaaEnd-10-00-00").mkdir(parents=True)
        (st / "shots" / d / "MaaEnd-10-00-00" / "x.png").write_bytes(b"x")
    (st / "shots" / "notes").mkdir()
    (st / "evidence").mkdir()
    gone = task_shots.prune(st, today=date(2026, 10, 5))
    check("removed", gone, ["2026-10-01", "2026-10-02"])
    check("kept", sorted(p.name for p in (st / "shots").iterdir()), ["2026-10-03", "2026-10-04", "2026-10-05", "notes"])
    check("nothing else touched", (st / "evidence").is_dir(), True)
    check("no shots folder -> nothing", task_shots.prune(TMP / "none"), [])

    # ---------------------------------------------------------------- Part B
    print("\n[the update-restart record that is held ships its bundle at once, with the task pictures]")


    class Notes:
        def __init__(self, fail_first=0):
            self.sent, self.fail_first = [], fail_first

        def send(self, title, body="", **kw):
            if kw.get("alert") and self.fail_first:
                self.fail_first -= 1
                return ["push down"]
            self.sent.append((title, body, kw.get("alert", False)))
            return []


    class Src:
        def fetch(self, seen):
            return []


    class Up:
        def __init__(self):
            self.files = []

        def upload(self, p):
            self.files.append(p)
            return {"page": "https://cos.example/ev/MaaEnd.zip", "store": "cos"}


    def at(hh, mm, ss=0):
        return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)


    # MXU's own log of the attempt that installed v2.31.0-beta.6 (verbatim, 2026-10-01-4.log)
    (MAAEND / "debug" / "2026-10-01-4.log").write_text("\n".join([
        "2026-10-01 16:11:06 INFO  [App] 检测到待安装更新: v2.31.0-beta.6",
        "2026-10-01 16:11:06 INFO  [App] 开始安装更新: D:/ark/maaend/cache\\10697.zip -> D:\\ark\\maaend",
        "2026-10-01 16:11:07 INFO  [App] 更新安装完成",
    ]) + "\n", encoding="utf-8")
    collect_retry.restore_master = lambda cfg: ""
    handle._weekly_gates = lambda eng, rec: None
    up = Up()
    evidence.uploaders = lambda cfg, run_id: [up]
    evidence.context_files = lambda cfg, window, dst, relay_until=None: []


    def build(notes=None):
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=notes or Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: None
        e._alert_key = lambda r: handle._alert_key(e, r)
        return e


    e = build()
    shot_dir = Path(e.cfg.state_dir) / "shots" / "2026-10-01" / "MaaEnd-16-11-06"
    shot_dir.mkdir(parents=True)
    inside = shot_dir / "161130-赠送干员礼物.png"
    inside.write_bytes(b"\x89PNG in window")
    os.utime(inside, (at(16, 11, 30).timestamp(),) * 2)
    outside = shot_dir / "090000-装备制造.png"
    outside.write_bytes(b"\x89PNG other run")
    os.utime(outside, (at(9, 0).timestamp(),) * 2)
    rec = RunRecord(run_id="2026-10-01/endfield/MaaEnd-12-10-02", script="MaaEnd", user="endfield",
                    started=at(16, 11, 6), finished=at(16, 11, 6), ok=False, failed_tasks=["赠送干员礼物"],
                    raw={"maaend_result": "MaaEnd 部分任务执行失败: 🎁赠送干员礼物"})
    handle._handle(e, rec)
    held = e._pending.get(("MaaEnd", "endfield"))
    check("held as an update restart", bool(held and held.raw.get("maaend_update_restart")), True)
    check("one bundle uploaded", len(up.files), 1)
    check("page on rec.raw", held and held.raw.get("evidence_page"), "https://cos.example/ev/MaaEnd.zip")
    inner = zipfile.ZipFile(up.files[0]).namelist() if up.files else []
    check("the run's task picture is in the bundle", "161130-赠送干员礼物.png" in inner, True)
    check("another run's picture is not", "090000-装备制造.png" in inner, False)
    e._flush_pending()
    got = [(t, b) for t, b, a in e.notifier.sent if a]
    check("the final alarm went out", len(got), 1)
    check("it carries the link", bool(got) and "https://cos.example/ev/MaaEnd.zip" in got[0][1], True)
    check("no 'not shipped' line", bool(got) and texts.EVIDENCE_NOT_SHIPPED in got[0][1], False)
    check("no second upload at alarm time", len(up.files), 1)

    print("\n[final alarm with no link: _ship_evidence once before the send; still nothing -> one line in the body]")
    calls = []
    real_ship = handle._ship_evidence


    def ship_fails(eng, r):
        calls.append(r.run_id)
        return ""


    handle._ship_evidence = ship_fails
    e = build(Notes(fail_first=1))
    bare = RunRecord(run_id="2026-10-01/endfield/MaaEnd-12-30-00", script="MaaEnd", user="endfield",
                     started=at(12, 30), finished=at(12, 40), ok=False, failed_tasks=["自动采集"],
                     raw={"maaend_result": "MaaEnd 部分任务执行失败: 🧺自动采集"})
    e._pending[("MaaEnd", "endfield")] = bare
    e._flush_pending()
    check("tried once before the send", calls, [bare.run_id])
    check("push failed -> still held", ("MaaEnd", "endfield") in e._pending, True)
    e._flush_pending()
    check("the retry of the push does not upload again", calls, [bare.run_id])
    got = [(t, b) for t, b, a in e.notifier.sent if a]
    check("alarm sent on the second tick", len(got), 1)
    check("body has the one line", bool(got) and got[0][1].count(texts.EVIDENCE_NOT_SHIPPED), 1)
    print("    " + (got[0][1].replace("\n", "\n    ")[:400] if got else ""))

    print("\n[same, but the late upload works -> the alarm carries the link and no extra line]")
    calls.clear()


    def ship_works(eng, r):
        calls.append(r.run_id)
        r.raw["evidence_page"] = "https://cos.example/late.zip"
        return "https://cos.example/late.zip"


    handle._ship_evidence = ship_works
    e = build()
    e._pending[("MaaEnd", "endfield")] = RunRecord(
        run_id="2026-10-01/endfield/MaaEnd-12-31-00", script="MaaEnd", user="endfield",
        started=at(12, 31), finished=at(12, 40), ok=False, failed_tasks=["自动采集"],
        raw={"maaend_result": "MaaEnd 部分任务执行失败: 🧺自动采集"})
    e._flush_pending()
    got = [(t, b) for t, b, a in e.notifier.sent if a]
    check("shipped once", len(calls), 1)
    check("link in the alarm", bool(got) and "https://cos.example/late.zip" in got[0][1], True)
    check("no 'not shipped' line", bool(got) and texts.EVIDENCE_NOT_SHIPPED in got[0][1], False)

    print("\n[an OK-WW final alarm (the generic path) gets the same treatment]")
    calls.clear()
    handle._ship_evidence = ship_fails
    e = build()
    e._pending[("OK-WW", "wuwa")] = RunRecord(
        run_id="2026-10-01/wuwa/OK-WW-09-00-00", script="OK-WW", user="wuwa",
        started=at(9, 0), finished=at(9, 30), ok=False, failed_tasks=["周本"], raw={"general_result": "周本失败"})
    e._flush_pending()
    got = [(t, b) for t, b, a in e.notifier.sent if a]
    check("tried once", len(calls), 1)
    check("line in the body", bool(got) and texts.EVIDENCE_NOT_SHIPPED in got[0][1], True)
    handle._ship_evidence = real_ship


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_evidence_archive, _part_evidence_cli_window, _part_evidence_daily_silent, _part_evidence_maaend_live_logs, _part_evidence_notify_once, _part_evidence_relay_after_run, _part_evidence_saved_count, _part_evidence_sources_unreachable, _part_error_evidence, _part_game_evidence, _part_held_push_keeps_evidence, _part_task_shots]))
