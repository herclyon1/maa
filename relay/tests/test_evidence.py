"""Diagnostic evidence bundles, screenshots, static attribute/name checks, and module table."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


class _Any:
    """Stands in for any pywin32 attribute: callable, subclassable, truthy."""
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


def _stub_pywin32():
    """boot_stages imports pywin32 at module scope; stub what is missing."""
    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))


class _Log:
    """A logger that keeps each line as it would read."""
    def __init__(self): self.lines = []
    def warning(self, *a): self.lines.append(a[0] % a[1:])
    def info(self, *a): self.lines.append(a[0] % a[1:] if len(a) > 1 else a[0])
    def exception(self, *a): self.lines.append(a[0])


class _NoSource:
    """A record source with nothing new."""
    def fetch(self, seen):
        return []


class _EmptyAnswer:
    """What urlopen hands back for a request that went through with no body."""
    def read(self): return b""
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _part_evidence_main():  # noqa: C901
    """Evidence bundles must match what the projects' own export buttons produce."""
    import json
    import os
    import random
    import zipfile
    from datetime import datetime as _dt

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import evidence as ev

    FX = fx_dir(Path(__file__), "fixtures") / "collect-retry-2026-09-11"
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
    FXP = fx_dir(Path(__file__), "fixtures") / "source-pins"
    files = {"IssueReportUserControlModel.cs": "MAA 生成日志压缩包（IssueReportUserControlModel.cs）",
             "file_ops.rs": "MaaEnd 导出（MXU file_ops.rs）",
             "diagnostics.py": "OK-WW 导出日志（diagnostics.py）"}
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
    # #180: MXU 04ad07ba moved the body into export_logs_from_dir and added the gzip-log and
    # screencap helpers; every one of them is pinned and found whole in the stored copy.
    mxu = ev.PINS[0]
    check("MXU 钉在 04ad07ba", mxu.commit, "04ad07ba056b0198d38b9438c4cdee6a25d251f1")
    check("MXU 钉的函数：新旧打包函数、压缩日志、截图收集都在",
          mxu.regions,
          ("export_logs_blocking", "export_logs_from_dir", "is_gzip_log", "write_redacted_text",
           "prepare_gzip_logs", "collect_files_recursively", "collect_debug_subdir_files",
           "collect_debug_images", "encode_image_archive_path", "add_file_to_zip",
           "normalize_archive_path", "is_image_file", "has_extension",
           "estimate_compressed_upper_bound", "pre_compress_measure"))
    segs = {n: ev.region_text(rs, "file_ops.rs", (n,)) for n in mxu.regions}
    check("每个钉的函数都从函数头截到收尾的花括号",
          [n for n, s in segs.items() if not (__import__("re").match(rf"(?:pub )?fn {n}\b", s) and s.endswith("\n}"))], [])
    check("截出来的是新版的内容：压缩日志、三组图片、图片名转义",
          ('ends_with(".log.gz")' in segs["is_gzip_log"],
           'collect_debug_images(&debug_dir.join("screencap"), "screencap", true)' in segs["export_logs_from_dir"],
           "|| is_gzip_log(&export.source_path)" in segs["collect_debug_subdir_files"],
           "recursive: bool" in segs["collect_debug_images"],
           '.replace(\'%\', "%25")' in segs["encode_image_archive_path"]),
          (True, True, True, True, True))
    check("存的副本的哈希就是钉的哈希", __import__("hashlib").sha256(ev.pinned_text(mxu, rs.encode("utf-8"))).hexdigest(), mxu.sha256)
    changed, _ = ev.check_sources(fetch=lambda url: rs.replace('"screencap", true', '"screencap", false').encode()
                                  if url.endswith(".rs") else from_fixtures(url))
    check("截图收集那一行一变就报", changed, [files["file_ops.rs"]])

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

    print("\n[MXU 04ad07ba：压缩过的旧日志（.log.gz）和 screencap 截图也进包（#180）]")
    gz = tmpdir() / "gz"
    for sub_ in ("debug/on_error/deep", "debug/vision", "debug/screencap/sub", "debug/cpp-algo", "config"):
        (gz / sub_).mkdir(parents=True)
    def _gk(rel, mtime, content=None):
        p = gz / rel
        p.write_bytes(content if content is not None else rel.encode())
        os.utime(p, (mtime, mtime)); return p
    _gk("config/mxu-MaaEnd.json", T - 86400 * 30)
    _gk("debug/maa.log", T + 50)
    _gk("debug/maa.bak.1.log.gz", T + 40)                 # rotated inside the run: in
    _gk("debug/maa.bak.2.LOG.GZ", T + 41)                 # case-insensitive, as is_gzip_log
    _gk("debug/maa.bak.0.log.gz", T - 86400)              # rotated yesterday: out
    _gk("debug/notes.gz", T + 42)                         # a .gz that is not a log: never in
    _gk("debug/crash.dmp", T + 43)
    _gk("debug/cpp-algo/algo.log.gz", T + 44)
    _gk("debug/cpp-algo/algo.json", T + 45)
    _gk("debug/cpp-algo/algo.txt", T + 46)                # not an exported extension
    _gk("debug/on_error/e1.png", T + 10)
    _gk("debug/on_error/deep/e2.png", T + 99)             # on_error is not recursive
    _gk("debug/vision/v1.jpg", T + 20)
    _gk("debug/screencap/a.png", T + 30)
    _gk("debug/screencap/sub/s.png", T + 60)              # newest: first of its group
    _gk("debug/screencap/sub/b.png", T + 30)              # same mtime as a.png: by archive name
    _gk("debug/screencap/50%.png", T + 5)                 # `%` is encoded in the archive name
    _gk("debug/screencap/old.png", T - 86400)             # out of the window
    gwin = (T - ev.WINDOW_SLACK, T + 240 + ev.WINDOW_SLACK)
    got = [n for _, n in ev.maaend_entries(gz, gwin, max_images=None)]
    check("顺序照 MXU：日志（含 .log.gz）→ 配置 → 子文件夹 → on_error → vision → screencap（新的在前，同时间按名字）", got,
          ["crash.dmp", "maa.bak.1.log.gz", "maa.bak.2.LOG.GZ", "maa.log", "config/mxu-MaaEnd.json",
           "cpp-algo/algo.json", "cpp-algo/algo.log.gz",
           "on_error/e1.png", "vision/v1.jpg",
           "screencap/sub/s.png", "screencap/a.png", "screencap/sub/b.png", "screencap/50%25.png"])
    capped = [n for _, n in ev.maaend_entries(gz, gwin, max_images=3) if n.endswith((".png", ".jpg"))]
    check("截图封顶时先留 on_error、vision，剩下的名额才给 screencap 最新的", capped,
          ["on_error/e1.png", "vision/v1.jpg", "screencap/sub/s.png"])
    _gk("debug/screencap/sub/dup.png", T + 70, b"debug/on_error/e1.png")   # same bytes, another group: both kept
    _gk("debug/screencap/sub/dup2.png", T + 65, b"debug/on_error/e1.png")  # same bytes, same group: dropped
    shots = [n for _, n in ev.maaend_entries(gz, gwin, max_images=None) if n.startswith("screencap/")]
    check("screencap 里内容相同的只留最新一张", shots[:2] + ["screencap/sub/dup2.png" in shots], ["screencap/sub/dup.png", "screencap/sub/s.png", False])
    gparts = ev.bundle_maaend(gz, tmpdir() / "gzout", "v1", gwin)
    with zipfile.ZipFile(gparts[0]) as z:
        check("包里真有压缩日志和子文件夹里的截图，压缩日志原样没被改",
              ("maa.bak.1.log.gz" in z.namelist() and "screencap/sub/s.png" in z.namelist(), z.read("maa.bak.1.log.gz")),
              (True, b"debug/maa.bak.1.log.gz"))

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
        check("探的时候连接就断：不传大文件，抛给外面再试（不算永久被拒）", (got, opened), ("raised: wobble", ["HEAD"]))
        opened.clear()
        heads = iter([urllib.error.URLError("wobble"), None])
        def _head_once(req, timeout=0):
            opened.append(req.get_method())
            if req.get_method() == "HEAD" and (exc := next(heads, None)) is not None:
                raise exc
            return _EmptyAnswer()
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
                return _EmptyAnswer()
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        urllib.request.urlopen = _put_403
        try:
            up.upload(zf); got = "no error"
        except ev.PermanentUploadError as exc:
            got = str(exc)
        check("探通了照传；传的时候被拒也换路不重试", (got, opened), ("COS 回了 403：密钥不对或没有这个桶的权限", ["HEAD", "PUT"]))
    finally:
        urllib.request.urlopen = _real_open
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


def _part_evidence_archive():  # noqa: C901
    """失败证据要存对：AUTO-MAS 那一轮的记录必须带上，日志对不上要出声。"""
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

    import logging
    import os
    import tempfile
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import errwatch, handle

    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.INFO)
            self.lines = []           # (levelno, message)

        def emit(self, record):
            self.lines.append((record.levelno, record.getMessage()))

    def _run_check(started, files, ew=None):
        """Records _warn_if_evidence_stale logs for debug logs {name: mtime}, captured from INFO up.
        """
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
           / "ark_relay" / "features" / "handle.py").read_text(encoding="utf-8")
    body = src[src.index("def _archive_maaend_evidence"):]
    body = body[:body.index("\ndef ", 10)] if "\ndef " in body[10:] else body
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



def _part_evidence_cli_window():
    """`python -m ark_relay evidence` never builds without a window: --hours, --since,
--run-id (that run's own window) or, with nothing given, the latest run of the
script in the ledger. The user, 2026-09-18: 「证据包永远按时间窗取」.
    """
    import json
    import tempfile
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay import __main__ as cli
    from ark_relay.features import evidence
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



def _part_evidence_daily_silent():
    """evidence_daily.py must exit non-zero when a day log could not be fetched."""
    import contextlib
    import io

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay" / "tests"))
    sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
    import evidence_pull as ed

    def run(missing):
        def cos_get(e, u, dest):
            if any(u["key"].startswith(f"daily/{m}-") for m in missing):
                raise RuntimeError("HTTP 404 NoSuchKey")
            (dest / u["name"]).write_text("10-10 01:00:00 INFO x\n", encoding="utf-8")

        ed.DAILY_DEST_ROOT = tmpdir() / "daily"
        ed.env = lambda _p: {"COS_SECRET_ID": "i", "COS_SECRET_KEY": "k",
                                           "COS_BUCKET": "b-1", "COS_REGION": "ap-shanghai"}
        ed.cos_get = cos_get
        old = sys.argv
        sys.argv = ["evidence_pull.py", "--daily", "2026-10-10"]
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
    """A MaaEnd bundle keeps the logs that were still being written at the end of its window."""
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
    from ark_relay.features import evidence as ev

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



def _part_evidence_notify_once():
    """An upstream export change is announced once, not on every boot."""
    import tempfile
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    _stub_pywin32()

    import boot_stages
    from ark_relay.features import evidence

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

    from ark_relay.core import statestore as techlog

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
    """
    import json
    import os
    import types
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import evidence
    from ark_relay.features import handle
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



def _part_evidence_saved_count():
    """The 🗂️ evidence line counts the files inside the bundle, not the uploads."""
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
    from ark_relay.features import handle
    from ark_relay.features import evidence

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return []

    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.history_dir = None
    e = eng_mod.Engine(cfg, source=_NoSource(), state=State(cfg.state_dir), notifier=Notes())
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
    """The upstream-source check says why it could not fetch, and when it tries again."""
    import tempfile
    import types
    import urllib.error
    import urllib.request

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    _stub_pywin32()

    import boot_stages

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



def _part_error_evidence():
    """The 2026-10-06 fix bill L: today's relay.log to COS, one object per day."""
    import json
    import logging
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import errwatch
    from ark_relay.features import evidence as error_evidence
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
    from ark_relay.features.evidence import Cos
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

    print("\n[past days COS lacks, or holds shorter than the machine does, are sent again (11-11 / 11-13 answered 404)]")
    import urllib.error
    from ark_relay.features.evidence import PermanentUploadError

    class FakeCos:
        """A COS store that knows what it holds: `held` is key -> bytes."""

        def __init__(self, held=None, size_fail=None, upload_fail=None):
            self.held = dict(held or {})
            self.asked, self.puts = [], []
            self.size_fail, self.upload_fail = size_fail, upload_fail

        def object_key(self, path):
            return f"daily/{path.name}"

        def size(self, key, timeout=20):
            self.asked.append(key)
            if self.size_fail is not None:
                raise self.size_fail(key) if callable(self.size_fail) else self.size_fail
            return len(self.held[key]) if key in self.held else None

        def upload(self, path, timeout=900):
            if self.upload_fail is not None:
                raise self.upload_fail
            key = self.object_key(path)
            self.held[key] = path.read_bytes()
            self.puts.append(key)
            return {"name": path.name, "url": f"https://host/{key}", "store": "cos", "key": key}

    def key_of(day, kind="relay"):
        return f"daily/{kind}-{day:%Y-%m-%d}.log"

    D1, D2, D3, D4 = (DAY - timedelta(days=n) for n in (1, 2, 3, 4))
    bf_log = tmpdir() / "relay.log"
    bf_log.write_bytes("".join(f"{stamp(d, hh, mm)} INFO    ark.test  {text}\n" for d, hh, mm, text in (
        (D4, 9, 0, "four days back"), (D3, 9, 0, "d3 morning"), (D3, 21, 40, "d3 evening"),
        (D2, 9, 0, "d2 morning"), (D2, 14, 7, "d2 afternoon"), (D1, 9, 0, "d1 morning"),
        (D1, 23, 59, "d1 last minute"), (DAY, 0, 0, "today midnight"), (DAY, 9, 0, "today"))).encode("utf-8"))
    d3_bytes = "".join(f"{stamp(D3, hh, mm)} INFO    ark.test  {t}\n" for hh, mm, t in ((9, 0, "d3 morning"), (21, 40, "d3 evening"))).encode("utf-8")
    d2_morning = f"{stamp(D2, 9, 0)} INFO    ark.test  d2 morning\n".encode("utf-8")
    cos = FakeCos({key_of(D3): d3_bytes, key_of(D2): d2_morning})
    before = (error_evidence._last_attempt[0], dict(error_evidence._last_ok), list(error_evidence._last_errors))
    check("default look-back covers a full week (7 days)", error_evidence.BACKFILL_DAYS, 7)
    got = error_evidence.backfill_past_days(cfg_with(bf_log, None, tmpdir()), now=NOW, uploader=cos, days=3)
    check("yesterday (no object) and the day before (a shorter object) are sent; three days back is whole and stays",
          (cos.puts, got["kept"], got["errors"]), ([key_of(D1), key_of(D2)], 1, []))
    check("what was sent says what COS held before", [(d, k, h) for d, k, h, _n in got["sent"]],
          [(f"{D1:%Y-%m-%d}", "relay", None), (f"{D2:%Y-%m-%d}", "relay", len(d2_morning))])
    check("yesterday's object is that day's lines to its last minute, nothing of today or the day before",
          (b"d1 morning" in cos.held[key_of(D1)], b"d1 last minute" in cos.held[key_of(D1)],
           b"today" in cos.held[key_of(D1)], b"d2" in cos.held[key_of(D1)]), (True, True, False, False))
    check("the shorter object is now the machine's whole day", b"d2 afternoon" in cos.held[key_of(D2)], True)
    check("four days back is outside the look-back, today is the daily upload's: neither is asked about",
          (key_of(D4) in cos.asked, key_of(DAY) in cos.asked), (False, False))
    check("the error path's throttle and last link are untouched",
          (error_evidence._last_attempt[0], dict(error_evidence._last_ok), list(error_evidence._last_errors)), before)
    again_bf = error_evidence.backfill_past_days(cfg_with(bf_log, None, tmpdir()), now=NOW, uploader=cos, days=3)
    check("a second pass finds every object as long as the machine's part: nothing sent", (again_bf["sent"], again_bf["kept"]), ([], 3))
    longer = FakeCos({key_of(D1): b"x" * 5000})
    error_evidence.backfill_past_days(cfg_with(bf_log, None, tmpdir()), now=NOW, uploader=longer, days=1)
    check("an object longer than the machine's part is never replaced", (longer.puts, len(longer.held[key_of(D1)])), ([], 5000))
    week = FakeCos({key_of(D3): d3_bytes})
    got = error_evidence.backfill_past_days(cfg_with(bf_log, None, tmpdir()), now=NOW, uploader=week)
    check("the default week reaches the day four days back; days the log holds nothing of are not asked about",
          (week.puts, got["kept"], sorted(week.asked)), ([key_of(D1), key_of(D2), key_of(D4)], 1, sorted(key_of(d) for d in (D1, D2, D3, D4))))

    empty_log = tmpdir() / "relay.log"
    write_day_log(empty_log, DAY, [(9, 0, "only today")])
    none = FakeCos()
    got = error_evidence.backfill_past_days(cfg_with(empty_log, None, tmpdir()), now=NOW, uploader=none)
    check("days the machine holds nothing of: not asked about, nothing sent", (none.asked, none.puts, got["errors"]), ([], [], []))

    down = FakeCos(size_fail=OSError("getaddrinfo failed"))
    got = error_evidence.backfill_past_days(cfg_with(bf_log, None, tmpdir()), now=NOW, uploader=down)
    check("the line is down: one error, and the other objects are not waited for", (len(got["errors"]), len(down.asked)), (1, 1))
    http = FakeCos(size_fail=lambda key: urllib.error.HTTPError("u", 500, "x", None, None) if key == key_of(D1) else None)
    http.size = lambda key, timeout=20, _f=http.size_fail: (_ for _ in ()).throw(_f(key)) if _f(key) else None
    got = error_evidence.backfill_past_days(cfg_with(bf_log, None, tmpdir()), now=NOW, uploader=http, days=3)
    check("one object answered 500: said, and the other days still go up", (len(got["errors"]), http.puts), (1, [key_of(D2), key_of(D3)]))
    refused = FakeCos(upload_fail=PermanentUploadError("COS 回了 403：密钥不对或没有这个桶的权限"))
    got = error_evidence.backfill_past_days(cfg_with(bf_log, None, tmpdir()), now=NOW, uploader=refused)
    check("the bucket refuses: one error and it stops there", (len(got["errors"]), len(refused.asked)), (1, 1))
    no_cos = Config()
    no_cos.state_dir, no_cos.automas_dir = tmpdir(), None
    no_cos.cos_secret_id = no_cos.cos_secret_key = no_cos.cos_bucket = no_cos.cos_region = ""
    check("no COS configured: nothing to do, no error", error_evidence.backfill_past_days(no_cos, now=NOW),
          {"sent": [], "kept": 0, "errors": []})

    print("\n[the back-fill runs once after the relay starts and once on each new day, on a thread of its own]")
    started = []
    error_evidence._backfill.update(day=None, thread=None)
    cfg_bf = cfg_with(bf_log, None, tmpdir())
    check("the first round after the start: started", error_evidence.backfill_step(cfg_bf, NOW, start=started.append), True)
    check("later rounds of the same day: not again", error_evidence.backfill_step(cfg_bf, NOW + timedelta(hours=3), start=started.append), False)
    check("the first round of the next day: started", error_evidence.backfill_step(cfg_bf, NOW + timedelta(days=1), start=started.append), True)
    check("two passes were handed to the thread", len(started), 2)

    seen = []

    class Catch(logging.Handler):
        def emit(self, record):
            seen.append((record.levelname, record.getMessage()))

    catch = Catch()
    error_evidence._log_error_evidence.addHandler(catch)
    level_was = error_evidence._log_error_evidence.level
    error_evidence._log_error_evidence.setLevel(logging.INFO)
    real_uploader = error_evidence._daily_uploader
    try:
        ok_cos = FakeCos()
        error_evidence._daily_uploader = lambda cfg: ok_cos
        error_evidence._run_backfill(cfg_bf, NOW)
        check("each object sent is one INFO line saying what COS lacked", [(lv, "没有" in m and "补传上去" in m) for lv, m in seen],
              [("INFO", True)] * 4)       # D1..D4: every day bf_log holds, inside the default week
        del seen[:]
        error_evidence._daily_uploader = lambda cfg: FakeCos(size_fail=OSError("getaddrinfo failed"))
        error_evidence._run_backfill(cfg_bf, NOW)
        check("a pass that could not finish is one WARNING (the group hears it)", [lv for lv, _m in seen], ["WARNING"])
        check("……and its push names the cause in plain words", "域名解析失败" in texts.relay_error_body("ark.error_evidence", seen[0][1], "09:52"), True)
    finally:
        error_evidence._daily_uploader = real_uploader
        error_evidence._log_error_evidence.removeHandler(catch)
        error_evidence._log_error_evidence.setLevel(level_was)
        error_evidence._backfill.update(day=None, thread=None)


def _part_game_evidence():
    """The daily report counts a task as done only with evidence from the game."""
    import os
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector, texts
    from ark_relay.features import collector_maaend, outcome as collector_okww, outcome
    from ark_relay.features import handle
    from ark_relay.core import ledger as core
    from ark_relay.core.config import SERVER_TZ, RunRecord

    FX = fx_dir(Path(__file__), "fixtures")
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
    stop = collector.parse_maaend_log(FX / "maaend_stop_task_2026-10-08.log")
    check("日志里解析出了停止任务", "停止任务" in (stop.get("tasks_done") or []), True)
    stop["tasks_shot"] = ["赠送干员礼物", "装备制造"]   # 103411 / 103416 in that bundle
    check("两项都有任务结束截图：这一趟没有没证据的项", core.maaend_unverified(stop), [])
    check("日报整天不算没证据", core.day_unverified([{"script": "MaaEnd", "ok": False, "raw": stop}]), [])
    check("日常清单里也不列停止任务", "停止任务" in core._maaend_listed(stop), False)

    print("\n[the stop task after the closing task does not change whether the round closed]")
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



def _part_held_push_keeps_evidence():
    """A held failure pushed later is pushed with the evidence captured when it was held."""
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

    from ark_relay.features import handle, handle as manualstops
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
        e = eng_mod.Engine(cfg, source=_NoSource(), state=State(cfg.state_dir), notifier=Notes())
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



def _part_task_shots():
    """MaaEnd task-end screenshots, and the evidence bundle every MAA / MaaEnd alarm carries."""
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

    from ark_relay.features import collect_retry
    from ark_relay.features import collect_watch
    from ark_relay.features import evidence, task_shots
    from ark_relay.features import handle
    from ark_relay.core import texts
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State

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

    class Up:
        def __init__(self):
            self.files = []

        def upload(self, p):
            self.files.append(p)
            return {"page": "https://cos.example/ev/MaaEnd.zip", "store": "cos"}

    def at(hh, mm, ss=0):
        return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)

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
        e = eng_mod.Engine(cfg, source=_NoSource(), state=State(cfg.state_dir), notifier=notes or Notes())
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


def _part_tacet_shots():
    import json, os, types
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import report
    from ark_relay.core import notify
    from ark_relay.core.config import SERVER_TZ

    TMP = tmpdir()
    shots = TMP / "okww" / "data" / "apps" / "ok-ww" / "working" / "screenshots"; shots.mkdir(parents=True)
    state = TMP / "state"; state.mkdir()
    cfgdir = TMP / "automas" / "data" / "sid" / "Default" / "ConfigFile"; cfgdir.mkdir(parents=True)
    (cfgdir / "DailyTask.json").write_text(json.dumps({"Which Tacet Suppression to Farm": 2}), encoding="utf-8")

    from PIL import Image
    def png(path, w=1920, h=1080, noisy=False):
        im = Image.new("RGB", (w, h), (30, 40, 50))
        if noisy:
            im = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
        im.save(path, format="PNG")

    png(shots / "10-58-35.184_tacet_drops_original.png")
    png(shots / "11-02-10.000_tacet_drops_original.png")
    png(shots / "09-58-35.184_weekly_remaining_original.png")   # 别的截图不发

    class N:
        def __init__(self): self.groups, self.images = [], []
        def send(self, title, body, **k): return []
        def send_group(self, title, body): self.groups.append((title, body)); return []
        def send_group_image(self, p): self.images.append(Path(p).name); return []
    class St:
        def __init__(self, ledger=None): self.dir = state; self._ledger = ledger or []
        def read_ledger(self, day): return self._ledger
    class Eng:
        def __init__(self):
            self.cfg = types.SimpleNamespace(okww_dir=TMP / "okww", automas_dir=TMP / "automas")
            self.state = St(LEDGER); self.notifier = N()

    day = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    # 账本里带着 OK-WW 自己报的「实际传送到第 3 个（0 起算）」= 第 4 个无音区（3.7 起的玄幽东岳，wuwa_tacet.NEW_LIST_FROM）
    LEDGER = [{"script": "OK-WW", "raw": {"okww_info": {"Teleport to Tacet Suppression": 3}}}]
    e = Eng()
    print("[开关默认关：一张都不发（用户 2026-09-14：先关掉）]")
    check("默认不发", report._attach_tacet_shots(e, day), [])
    check("默认没发说明", e.notifier.groups, [])
    from ark_relay.features import modes
    check("打开的回话", modes.set_tacet_shots(state, True), "无音区结算截图：以后日报后面会带上")
    check("读回是开", modes.tacet_shots_on(state), True)
    print("[只发最新那一张，带说明]")
    done = report._attach_tacet_shots(e, day)
    check("只发最新一张", done, ["11-02-10.000_tacet_drops_original.png"])
    check("先发一条说明", e.notifier.groups[0][0], "🖼️ 无音区产出")
    check("说明里有实际序号、名字、套装", all(k in e.notifier.groups[0][1] for k in ("实际刷了第 4 个", "玄幽东岳", "羽落空尘之歌", "清邪荡煞之心")), True)
    check("说明写清是结算页", "刷完的结算页" in e.notifier.groups[0][1], True)
    check("别的截图不发", "09-58-35.184_weekly_remaining_original.png" in e.notifier.images, False)

    print("[同一天再发日报：已发过的不重复]")
    e2 = Eng()
    check("第二次什么都不发", report._attach_tacet_shots(e2, day), [])
    check("也不发说明", e2.notifier.groups, [])
    png(shots / "12-30-00.000_tacet_drops_original.png")
    check("新拍的那张会发", report._attach_tacet_shots(e2, day), ["12-30-00.000_tacet_drops_original.png"])

    print("[说明没送到：图也不发、不记已发，下一次两样一起再发]")
    png(shots / "13-00-00.000_tacet_drops_original.png")
    e6 = Eng()
    e6.notifier.send_group = lambda title, body: (e6.notifier.groups.append((title, body)), ["群机器人: 假装挂了"])[1]
    check("说明失败时不发图", report._attach_tacet_shots(e6, day), [])
    check("图一张没发", e6.notifier.images, [])
    e7 = Eng()
    check("下一次说明和图一起发", report._attach_tacet_shots(e7, day), ["13-00-00.000_tacet_drops_original.png"])
    check("下一次先发了说明", [t for t, _ in e7.notifier.groups], ["🖼️ 无音区产出"])

    print("[没配 OK-WW 目录：安静]")
    e3 = Eng(); e3.cfg.okww_dir = None
    check("不发", report._attach_tacet_shots(e3, day), [])

    print("[大图缩到群机器人上限以内]")
    big = TMP / "big.png"; png(big, noisy=True)
    raw = big.stat().st_size
    out = notify._image_bytes_for_wecom(big)
    check("原图确实超限", raw > notify._WECOM_IMAGE_LIMIT, True)
    check("缩后在上限内", len(out) <= notify._WECOM_IMAGE_LIMIT, True)
    check("缩后是 JPEG", out[:2] == b"\xff\xd8", True)
    small = TMP / "small.png"; png(small, 200, 100)
    check("小图原样发", notify._image_bytes_for_wecom(small) == small.read_bytes(), True)

    print("[设置和实际不一样时，两个都说出来]")
    e4 = Eng(); e4.state._ledger = [{"raw": {"okww_info": {"Teleport to Tacet Suppression": 4}}}]
    cap = report._tacet_caption(e4, day)
    check("说实际刷的是第 5 个", "实际刷了第 5 个" in cap, True)
    check("并指出设置写的是第 2 个", "设置里写的是第 2 个" in cap, True)

    print("[读不到实际序号时，明说那是设置值]")
    e5 = Eng(); e5.state._ledger = []
    check("明说", "（实际序号没读到）" in report._tacet_caption(e5, day), True)

    print("[关掉之后又不发了]")
    check("关的回话", modes.set_tacet_shots(state, False), "无音区结算截图：不发了")
    check("读回是关", modes.tacet_shots_on(state), False)


def _part_self_attrs_main():  # noqa: C901
    """Every `self.x` used in the relay must actually exist."""
    import ast

    ROOT = Path(__file__).resolve().parents[1]

    # Names that genuinely come from somewhere this file cannot see.
    INHERITED = {
        "ArkRelayService": {
            # win32serviceutil.ServiceFramework
            "ReportServiceStatus", "SvcStop", "SvcDoRun", "stop_event",
        },
        "RelayLogHandler": {
            # logging.handlers.RotatingFileHandler (logfile.py doRollover)
            "stream", "_open", "backupCount", "baseFilename", "delay", "rotate",
        },
        "_WordsOut": {
            # ast.NodeTransformer (okww_overlay.py, the shape of an OK-WW method)
            "generic_visit",
        },
    }

    def defined_names(cls: ast.ClassDef) -> set[str]:
        out = set()
        for node in ast.walk(cls):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.add(node.name)
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    for t in (tgt.elts if isinstance(tgt, (ast.Tuple, ast.List)) else [tgt]):
                        if (isinstance(t, ast.Attribute)
                                and isinstance(t.value, ast.Name) and t.value.id == "self"):
                            out.add(t.attr)
                        elif isinstance(t, ast.Name):
                            out.add(t.id)        # class-level attribute
            elif isinstance(node, ast.AnnAssign):
                tgt = node.target
                if (isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"):
                    out.add(tgt.attr)
                elif isinstance(tgt, ast.Name):
                    out.add(tgt.id)
            elif isinstance(node, ast.For):
                tgt = node.target
                if (isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"):
                    out.add(tgt.attr)
        return out

    def used_names(cls: ast.ClassDef) -> dict[str, int]:
        out: dict[str, int] = {}
        for node in ast.walk(cls):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name) and node.value.id == "self"
                    and isinstance(node.ctx, ast.Load)):
                out.setdefault(node.attr, node.lineno)
        return out

    def module_name(f: Path) -> str:
        """Dotted import name of a scanned file: ark_relay/core/config.py -> ark_relay.core.config."""
        parts = list(f.relative_to(ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    class Index:
        """Top-level classes and `from ... import` bindings of every scanned module."""

        def __init__(self, trees: dict[str, tuple[ast.Module, bool]]):
            self.classes: dict[str, dict[str, ast.ClassDef]] = {}
            self.imports: dict[str, dict[str, tuple[str, str]]] = {}
            for mod, (tree, is_pkg) in trees.items():
                self.classes[mod] = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
                imps: dict[str, tuple[str, str]] = {}
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        src = node.module or ""
                        if node.level:
                            pkg = mod.split(".") if is_pkg else mod.split(".")[:-1]
                            pkg = pkg[:len(pkg) - (node.level - 1)]
                            src = ".".join(pkg + ([src] if src else []))
                        for a in node.names:
                            imps[a.asname or a.name] = (src, a.name)
                self.imports[mod] = imps

        def lookup(self, mod: str, name: str, depth: int = 0) -> "tuple[str, ast.ClassDef] | None":
            if depth > 10:
                return None
            if name in self.classes.get(mod, {}):
                return mod, self.classes[mod][name]
            src = self.imports.get(mod, {}).get(name)
            if src is None:
                return None
            return self.lookup(src[0], src[1], depth + 1)

        def inherited(self, mod: str, cls: ast.ClassDef, seen=None) -> set[str]:
            """Names defined on every base class reachable in the scanned source."""
            seen = set() if seen is None else seen
            out: set[str] = set()
            for b in cls.bases:
                if not isinstance(b, ast.Name):
                    continue
                hit = self.lookup(mod, b.id)
                if hit is None or id(hit[1]) in seen:
                    continue
                seen.add(id(hit[1]))
                out |= defined_names(hit[1]) | INHERITED.get(hit[1].name, set())
                out |= self.inherited(hit[0], hit[1], seen)
            return out

    def main() -> int:
        files = sorted(list([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files"} & set(p.parts)])
                       + [ROOT / "service.py", ROOT / "boot_stages.py"])
        if len(files) < 20:
            print(f"  ✗ 只扫到 {len(files)} 个文件，至少该有 20 个——路径不对或目录改名了")
            return 1
        problems = []
        checked = 0
        trees = {module_name(f): (ast.parse(f.read_text(encoding="utf-8"), filename=str(f)),
                                  f.name == "__init__.py")
                 for f in files}
        index = Index(trees)
        for f in files:
            mod = module_name(f)
            tree = trees[mod][0]
            for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                checked += 1
                known = (defined_names(cls) | INHERITED.get(cls.name, set())
                         | index.inherited(mod, cls))
                for attr, line in sorted(used_names(cls).items()):
                    if attr.startswith("__") or attr in known:
                        continue
                    problems.append(f"{f.relative_to(ROOT)}:{line} {cls.name}.{attr} 用了但没定义")
        print(f"  检查了 {len(files)} 个文件、{checked} 个类")
        for p in problems:
            print(f"  FAIL {p}")
        if problems:
            print("FAILED")
            return 1
        print("all checks passed")
        return 0

    if __name__ == "__main__":
        raise SystemExit(main())


def _part_self_heal_red():
    """Every fault that fixed itself, and so stays out of the group, leaves a red item in the technical log.
    """
    import ast
    import importlib.util
    import logging
    import os
    import types
    from datetime import datetime

    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="", ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))
    from ark_relay.core import statestore as techlog
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import errwatch, handle

    def reds(state_dir, day):
        try:
            text = techlog.path_for(day, state_dir).read_text(encoding="utf-8")
        except OSError:
            return []
        return techlog.unhandled(text)

    print("[add_red: ids stay unique within a day, across calls in the same minute]")
    d = TMP / "a" / "state"
    when = datetime(2026, 10, 11, 17, 50, tzinfo=SERVER_TZ)
    first = techlog.add_red("2026-10-11", "x", ["one", "two"], state_dir=d, now=when)
    second = techlog.add_red("2026-10-11", "y", ["three"], state_dir=d, now=when)
    check("first call", first, ["R-20261011-1750-1", "R-20261011-1750-2"])
    check("second call in the same minute goes on after them", second, ["R-20261011-1750-3"])
    check("all three unhandled", [i for i, _ in reds(d, "2026-10-11")], first + second)
    check("nothing to write writes nothing", techlog.add_red("2026-10-11", "z", ["  "], state_dir=d, now=when), [])
    check("a text over several lines stays one red line",
          techlog.add_red("2026-10-11", "z", ["a\nb"], state_dir=TMP / "a2" / "state", now=when) != []
          and [t for _, t in reds(TMP / "a2" / "state", "2026-10-11")] == ["a b"], True)

    print("[the Mac reader sees them, and `handled` clears exactly one]")
    spec = importlib.util.spec_from_file_location("techlog_tool", RELAY.parent / "scripts" / "mac" / "techlog.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    text = techlog.path_for("2026-10-11", d).read_text(encoding="utf-8")
    check("the reader's red pattern matches every red line",
          sum(1 for ln in text.splitlines() if tool.RED_LINE.match(ln)), 3)
    text += "\n" + tool.handled_line("R-20261011-1750-2", "abc1234") + "\n"
    check("one handled line clears that one only", [i for i, _ in techlog.unhandled(text)],
          ["R-20261011-1750-1", "R-20261011-1750-3"])

    print("[errwatch: a recovered record writes one 「自愈待查」 red item, a plain WARNING none]")

    class _N:
        channels = ()

        def __init__(self):
            self.sent = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body))
            return []

    ARK = logging.getLogger(errwatch.ARK)
    ARK.setLevel(logging.INFO)
    sd = TMP / "b" / "state"
    sd.mkdir(parents=True)
    n = _N()
    h = errwatch.ErrorKindAlert(n, state_dir=sd, known={}, pace=0, retry=(0.05,))
    ARK.addHandler(h)
    try:
        lg = logging.getLogger("ark.test_evidence")
        lg.warning("手机通道断了 20 秒，自己重新连上了", extra=errwatch.recovered())
        lg.warning("手机通道断了 30 秒，自己重新连上了", extra=errwatch.recovered())
        lg.warning("这个没好")
        h.drain(timeout=5.0)
    finally:
        ARK.removeHandler(h)
        h.close()
    today = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    got = reds(sd, today)
    check("two recovered records, two red items", len(got), 2)
    check("each says 自愈待查, where, and what it said",
          [(t.startswith(techlog.SELF_HEAL), "ark.test_evidence" in t, "自己重新连上了" in t) for _, t in got],
          [(True, True, True)] * 2)
    check("their ids differ", len({i for i, _ in got}), 2)
    check("the plain WARNING went to the group and wrote no red item",
          (len(n.sent), any("这个没好" in t for _, t in got)), (1, False))

    print("[handle's heals write one too]")
    eng = types.SimpleNamespace(cfg=types.SimpleNamespace(state_dir=str(TMP / "c" / "state")))
    handle._self_heal_red(eng, "MaaEnd 2026-10-11/endfield/MaaEnd-05-30-34 中途失败过，重试后成功", "自动采集")
    got = reds(TMP / "c" / "state", today)
    check("one red item naming the run and the first failure",
          [("MaaEnd-05-30-34" in t, "自动采集" in t) for _, t in got], [(True, True)])

    print("[every errwatch.recovered() in the relay is the extra= of a log call]")
    LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
    bad, seen = [], 0
    for path in sorted(RELAY.rglob("*.py")):
        if "tests" in path.relative_to(RELAY).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "recovered" and not node.args and not node.keywords):
                continue
            seen += 1
            up, ok = node, False
            while up in parents:
                par = parents[up]
                if isinstance(par, ast.keyword) and par.arg == "extra":
                    call = parents.get(par)
                    ok = (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                          and call.func.attr in LOG_METHODS)
                    break
                if isinstance(par, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                    break
                up = par
            if not ok and path.name != "errwatch.py":
                bad.append(f"{path.relative_to(RELAY)}:{node.lineno}")
    check("found the calls", seen > 10, True)
    check("none outside a log call's extra=", bad, [])
    src = (RELAY / "ark_relay" / "features" / "errwatch.py").read_text(encoding="utf-8")
    check("errwatch has no daily-only door any more", "def note_daily" in src, False)



def _part_undefined_names():  # noqa: C901
    import ast
    import builtins
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[1]
    BUILTINS = set(dir(builtins)) | {
        "__file__", "__name__", "__doc__", "__package__", "__spec__", "__debug__",
    }

    FAILED = []

    def _bound_by(node: ast.AST) -> set[str]:
        """这个节点直接绑定了哪些名字（不下钻到子作用域）。"""
        out: set[str] = set()

        def targets(t):
            if isinstance(t, ast.Name):
                out.add(t.id)
            elif isinstance(t, (ast.Tuple, ast.List)):
                for e in t.elts:
                    targets(e)
            elif isinstance(t, ast.Starred):
                targets(t.value)
            # Attribute / Subscript 赋值不产生新名字

        if isinstance(node, (ast.Assign,)):
            for t in node.targets:
                targets(t)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets(node.target)
        elif isinstance(node, ast.NamedExpr):          # walrus
            targets(node.target)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            targets(node.target)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for it in node.items:
                if it.optional_vars is not None:
                    targets(it.optional_vars)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                out.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
        elif isinstance(node, ast.comprehension):
            targets(node.target)
        return out

    def _scope_binds(scope: ast.AST) -> set[str]:
        """一个作用域里绑定的全部名字。子作用域的函数体不算，但它们的**名字**算。"""
        out: set[str] = set()
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = scope.args
            for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs):
                out.add(arg.arg)
            for arg in (a.vararg, a.kwarg):
                if arg is not None:
                    out.add(arg.arg)

        body = [scope] if isinstance(scope, ast.Lambda) else list(
            ast.iter_child_nodes(scope))

        def walk(n, top=False):
            out.update(_bound_by(n))
            # 不下钻进子作用域的函数体——那是它自己的事
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.Lambda, ast.ClassDef)) and not top:
                return
            for c in ast.iter_child_nodes(n):
                walk(c)

        for n in body:
            walk(n, top=True)
        return out

    def _check_scope(scope: ast.AST, visible: set[str], path: Path) -> None:
        here = visible | _scope_binds(scope)

        # 推导式在 Python 3 里自成作用域，但它的目标名字对内部可见。
        def loads(n):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                              ast.ClassDef)) and n is not scope:
                _check_scope(n, here, path)
                # 装饰器和默认值在**外层**求值
                for d in getattr(n, "decorator_list", []):
                    loads(d)
                return
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                if n.id not in here:
                    FAILED.append(f"{path.relative_to(ROOT)}:{n.lineno} 读取了未定义的名字 `{n.id}`")
            for c in ast.iter_child_nodes(n):
                loads(c)

        for c in ast.iter_child_nodes(scope):
            loads(c)

    def main() -> int:
        # ark_relay/ was split into core/ and features/<name>/ packages, so scan it
        # recursively. Same exclusion as test_self_attrs.py: the OK-WW payload
        # (okww_files), which runs inside OK-WW.
        files = sorted(p for p in (ROOT / "ark_relay").rglob("*.py")
                       if not {"okww_files"} & set(p.parts))
        files += [ROOT / "service.py", ROOT / "boot_stages.py", ROOT / "run.py"]
        if len(files) < 20:
            print(f"  ✗ 只扫到 {len(files)} 个文件，至少该有 20 个——路径不对或目录改名了")
            return 1
        files = [f for f in files if f.exists()]
        print(f"[裸名字检查] {len(files)} 个文件")
        for f in files:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            _check_scope(tree, BUILTINS, f)

        if FAILED:
            for m in FAILED:
                print("  FAIL", m)
            print(f"FAILED: {len(FAILED)} 处")
            return 1
        print("  ok   没有未定义的裸名字")
        print("all checks passed")
        return 0

    if __name__ == "__main__":
        sys.exit(main())


def _part_module_table():
    import re

    ROOT = Path(__file__).resolve().parents[1]
    doc = (ROOT / "README.md").read_text(encoding="utf-8")
    mods = {p.stem for p in [p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files", "machinechecks", "machinechecks.py"} & set(p.parts)]
            if not p.stem.startswith("_")} | {"service"}

    listed = set(re.findall(r"`(\w+)\.py`", doc))
    missing = sorted(mods - listed)
    extra = sorted(n for n in listed - mods if n not in ("run", "make-manifest") and not n.startswith("_"))

    print(f"  模块 {len(mods)} 个，表里提到 {len(listed & mods)} 个")
    if missing:
        fails.append(f"表里没提到：{missing}")
        print(f"  ✗ 表里没提到：{missing}")
    if extra:
        fails.append(f"表里提到了不存在的：{extra}")
        print(f"  ✗ 表里提到了不存在的：{extra}")

    # 拆出去的四块不许还写成在 engine 里
    for name in ("shutdown", "report", "missed", "handle"):
        if re.search(rf"engine\.py[^|\n]*{name}", doc):
            fails.append(f"{name} 已经从 engine 拆出来了，表里还说在 engine 里")


def _part_parts():
    import logging
    import os
    import sys
    import urllib.request
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _parts
    from _parts import run_parts
    from _parts import tmpdir

    fails = []

    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
        if not ok:
            fails.append(label)

    REAL = urllib.request.urlopen
    # A variable of this test only (not a setting of the relay, so not in docs/CONFIG.md).
    VAR = "PARTS_TEST_VARIABLE"
    CWD = os.getcwd()
    seen = {}

    def _part_changes_everything():
        os.environ[VAR] = "1"
        urllib.request.urlopen = lambda *a, **k: None
        logging.getLogger("ark.test_evidence").propagate = False
        import colorsys
        colorsys.rgb_to_hsv(0, 0, 0)
        os.chdir(tmpdir())
        sys.exit(1)

    def _part_sees_nothing_of_it():
        seen["env"] = VAR in os.environ
        seen["urlopen"] = urllib.request.urlopen is REAL
        seen["propagate"] = logging.getLogger("ark.test_evidence").propagate
        seen["module"] = "colorsys" in sys.modules
        seen["cwd"] = os.getcwd()

    def _part_raises():
        raise RuntimeError("a part that crashes")

    print("[three parts: one exits 1, one checks, one raises]")
    check("the run fails", run_parts([_part_changes_everything, _part_sees_nothing_of_it, _part_raises]), 1)
    check("……and every part ran", "cwd" in seen, True)
    check("the next part does not see the first one's environment variable", seen.get("env"), False)
    check("……nor its fake urlopen", seen.get("urlopen"), True)
    check("……nor its logger flag", seen.get("propagate"), True)
    check("……nor the module it imported", seen.get("module"), False)
    check("……nor its working directory", seen.get("cwd"), CWD)
    check("all passing parts: 0", run_parts([_part_sees_nothing_of_it]), 0)

    print("\n[the shared check (_parts.check): a failed one fails its part only]")
    later = {}

    def _part_fails_a_shared_check():
        _parts.check("one equals two", 1, 2)

    def _part_after_it():
        later["fails"] = list(_parts.fails)
        _parts.require("still true", True)

    check("a part with a failed shared check fails the run", run_parts([_part_fails_a_shared_check, _part_after_it]), 1)
    check("……the next part starts with no failed check", later.get("fails"), [])
    check("passing shared checks: 0", run_parts([_part_after_it]), 0)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_scripts_relay_attrs():
    """Every name the helper scripts read off an ark_relay module still exists there."""
    import ast
    import importlib
    import inspect

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    ROOT = Path(__file__).resolve().parents[2]
    DIRS = [ROOT / "scripts" / "windows", ROOT / "scripts" / "mac" / "lib"]

    def missing_names(src: str) -> list:
        tree = ast.parse(src)
        alias = {}
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "ark_relay":
                for a in node.names:
                    alias[a.asname or a.name] = f"ark_relay.{a.name}"
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("ark_relay."):
                mod = importlib.import_module(node.module)
                for a in node.names:
                    if not hasattr(mod, a.name):
                        try:     # a submodule not imported yet: `from ark_relay.core import notify`
                            importlib.import_module(f"{node.module}.{a.name}")
                        except ModuleNotFoundError:
                            out.append(f"{node.module}.{a.name}")
                            continue
                    if inspect.ismodule(getattr(mod, a.name, None)):
                        alias[a.asname or a.name] = f"{node.module}.{a.name}"
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("ark_relay.") and a.asname:
                        alias[a.asname] = a.name
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in alias):
                mod = importlib.import_module(alias[node.value.id])
                if not hasattr(mod, node.attr):
                    out.append(f"{alias[node.value.id]}.{node.attr}")
        return out

    bad = {}
    for d in DIRS:
        for f in sorted(d.glob("*.py")):
            miss = missing_names(f.read_text(encoding="utf-8"))
            if miss:
                bad[str(f.relative_to(ROOT))] = miss
    check("every ark_relay name the scripts use exists", bad, {})

    # The 05:26 crash, from the pre-fix okww-landed.py:7 and :14 (import path moved to the new name).
    old = ("from ark_relay.features import weeklyboss as W  # noqa: E402\n"
           'o = json.loads(W._okww_file(name).read_text(encoding="utf-8"))\n')
    check("the 10-10 okww-check line is caught", missing_names(old), ["ark_relay.features.weeklyboss._okww_file"])
    check("names that exist pass",
          missing_names("from ark_relay.features import weeklyboss as W\nW.DAILY\nW._file\nW.name_from_log\n"), [])
    check("a missing from-import is caught",
          missing_names("from ark_relay.features.weeklyboss import nope\n"), ["ark_relay.features.weeklyboss.nope"])


def _part_scripts_running_asks_automas():
    """「有脚本在跑吗」先问 AUTO-MAS，不只看进程名。"""

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import engine

    REAL = {"tasks": [{"taskId": "8cebb1be", "mode": "AutoProxy", "stopping": False,
                       "task_info": [
                           {"name": "MAA", "status": "完成", "userList": [{"name": "arknights", "status": "完成"}]},
                           {"name": "OK-WW", "status": "异常", "userList": [{"name": "wuwa", "status": "异常"}]},
                           {"name": "MaaEnd", "status": "运行", "userList": [{"name": "endfield", "status": "运行"}]}]}],
            "scheduledScripts": []}
    check("MaaEnd 运行中 → 在跑", engine._judge_snapshot(REAL), True)

    waiting = {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"}, {"name": "OK-WW", "status": "等待"}]}]}
    check("OK-WW 还在等待 → 在跑（假报警就是这一格）", engine._judge_snapshot(waiting), True)
    check("刚派下去、还没有状态 → 在跑", engine._judge_snapshot({"tasks": [{"task_info": []}]}), True)
    done = {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"}, {"name": "OK-WW", "status": "异常"}]}]}
    check("全部终态 → 没在跑", engine._judge_snapshot(done), False)
    check("没有任务 → 没在跑", engine._judge_snapshot({"tasks": []}), False)
    check("空回复 → 没在跑", engine._judge_snapshot(None), False)
    check("没见过的状态 → 当作在跑", engine._judge_snapshot({"tasks": [{"task_info": [{"status": "重试中"}]}]}), True)

    print("\n[AUTO-MAS v5.9 新版快照（无 task_info，改放 task.scripts）以及接口超时不误判空闲（#190）]")
    import json
    import time
    import urllib.error
    import urllib.request
    from ark_relay.features import maa_start_watchdog, maaend_watchdog, redbutton, runwatch

    V59 = {"tasks": [{
        "taskId": "41453325-c293-4d0d-a6a2-779b58d52477",
        "mode": "AutoProxy",
        "trigger": "timed",
        "stopping": False,
        "task": {
            "info": {"name": "早班", "mode": "AutoProxy", "status": "running", "trigger": "timed"},
            "scripts": {
                "order": [
                    {"uid": "s1", "type": "TaskScriptItem"},
                    {"uid": "s2", "type": "TaskScriptItem"},
                    {"uid": "s3", "type": "TaskScriptItem"},
                ],
                "data": {
                    "s1": {"info": {"name": "MAA", "status": "完成", "script_type": "MAA"}},
                    "s2": {"info": {"name": "OK-WW", "status": "完成", "script_type": "Okww"}},
                    "s3": {"info": {"name": "MaaEnd", "status": "运行", "script_type": "MaaEnd"}},
                },
            },
        },
    }]}
    check("v5.9 拆出顺序正确的 3 项", [(i["name"], i["status"]) for i in engine._task_items(V59["tasks"][0])],
          [("MAA", "完成"), ("OK-WW", "完成"), ("MaaEnd", "运行")])
    check("v5.9 MaaEnd 运行中 → 整体在跑", engine._judge_snapshot(V59), True)
    check("v5.9 MAA 已完成 → MAA 不在跑", engine._script_unfinished(V59, "MAA"), False)
    check("v5.9 OK-WW 已完成 → OK-WW 不在跑", engine._script_unfinished(V59, "OK-WW"), False)
    check("v5.9 MaaEnd 运行中 → MaaEnd 在跑", engine._script_unfinished(V59, "MaaEnd"), True)
    check("v5.9 maaend_watchdog 认出 MaaEnd 在跑", maaend_watchdog._maaend_running(V59), True)
    check("v5.9 maa_start_watchdog 认出 MAA 不在跑", maa_start_watchdog._maa_running(V59), False)
    check("v5.9 runwatch 按队列名匹配到早班",
          runwatch._queue_task(V59, "missing-uid", "早班") is V59["tasks"][0], True)

    V59_DONE = {"tasks": [{
        "taskId": "41453325",
        "mode": "AutoProxy",
        "task": {
            "info": {"name": "早班", "status": "running"},
            "scripts": {
                "order": [{"uid": "s1"}, {"uid": "s2"}, {"uid": "s3"}],
                "data": {
                    "s1": {"info": {"name": "MAA", "status": "完成"}},
                    "s2": {"info": {"name": "OK-WW", "status": "异常"}},
                    "s3": {"info": {"name": "MaaEnd", "status": "完成"}},
                },
            },
        },
    }]}
    check("v5.9 全部终态 → 没在跑", engine._judge_snapshot(V59_DONE), False)
    check("v5.9 全部终态 → MaaEnd 不在跑", engine._script_unfinished(V59_DONE, "MaaEnd"), False)

    # Redbutton reads v5.9 task labels too
    real_open = urllib.request.urlopen

    class _Resp:
        def __init__(self, body: bytes):
            self._body = body
            self.status = 200

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    try:
        urllib.request.urlopen = lambda *a, **k: _Resp(json.dumps(V59).encode("utf-8"))
        check("v5.9 红按钮读出任务名称", redbutton._estop_live_tasks(),
              [("41453325-c293-4d0d-a6a2-779b58d52477", "MAA、OK-WW、MaaEnd")])

        # Timeout talking to AUTO-MAS -> alive & busy within 3 min cap, falls back after cap
        calls = []

        def _timeout(*a, **k):
            calls.append(1)
            raise TimeoutError("timed out")

        engine._SNAP_TIMEOUT.update(since=None, capped_logged=False)
        urllib.request.urlopen = _timeout
        check("超时（直抛 TimeoutError）→ 判在跑", engine._automas_busy(), True)

        def _url_timeout(*a, **k):
            calls.append(1)
            raise urllib.error.URLError(TimeoutError("timed out"))

        urllib.request.urlopen = _url_timeout
        check("超时（URLError 包 TimeoutError）→ 判在跑", engine._automas_busy(), True)

        # _script_running returns True on timeout in ONE call without paying a second timeout
        real_win = engine.config.IS_WINDOWS
        try:
            engine.config.IS_WINDOWS = True
            calls.clear()
            dummy = object.__new__(engine.Engine)
            dummy._scripts_running = lambda: (_ for _ in ()).throw(AssertionError("should not fall back on timeout"))
            check("单脚本超时直接判在跑且不重问", (dummy._script_running("MaaEnd"), len(calls)), (True, 1))

            # Consecutive timeouts past 3 min (e.g. 4 min) -> stop claiming busy and fall back
            engine._SNAP_TIMEOUT["since"] = time.monotonic() - 240.0
            check("连续超时 4 分钟 → _automas_busy 返回 None 退回进程表", engine._automas_busy(), None)
            fallback_hit = []
            dummy._scripts_running = lambda: (fallback_hit.append(1) or False)
            check("连续超时 4 分钟 → _script_running 退回查进程表",
                  (dummy._script_running("MaaEnd"), len(fallback_hit)), (False, 1))

            # Once AUTO-MAS answers 200 OK again, timeout streak resets cleanly
            urllib.request.urlopen = lambda *a, **k: _Resp(json.dumps(V59).encode("utf-8"))
            check("接口恢复正常 → 重置连续超时计时", engine._automas_busy(), True)
            check("连续超时起点已清空", engine._SNAP_TIMEOUT["since"], None)
            urllib.request.urlopen = _timeout
            check("恢复后再次短暂超时 → 重新判在跑", engine._automas_busy(), True)
        finally:
            engine.config.IS_WINDOWS = real_win

        # Connection refused (AUTO-MAS down) -> None (falls back to tasklist)
        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            urllib.error.URLError(ConnectionRefusedError("refused")))
        check("连接被拒（后端没起）→ 返回 None 退回进程表", engine._automas_busy(), None)
    finally:
        urllib.request.urlopen = real_open
        engine._SCRIPTS_CACHE.update(at=-1e9, val=False)
        engine._SNAP_TIMEOUT.update(since=None, capped_logged=False)


def _part_scripts_cache_toctou():
    """_SCRIPTS_CACHE lock + generation counter blocks stale write-back after forget_scripts_cache."""
    import threading
    import urllib.request

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import engine

    print("[_scripts_running 执行 tasklist 期间被 forget_scripts_cache 打断：不回写过期 False]")
    real_win = engine.config.IS_WINDOWS
    real_busy = engine._automas_busy
    real_sub = engine.subprocess
    real_okww = engine._okww_up
    in_tasklist = threading.Event()
    allow_finish = threading.Event()
    busy_state = {"val": False, "calls": 0}
    first_result: list[bool] = []
    errors: list[BaseException] = []

    def fake_busy():
        busy_state["calls"] += 1
        return busy_state["val"]

    def slow_tasklist(*a, **k):
        in_tasklist.set()
        allow_finish.wait(timeout=5.0)
        return types.SimpleNamespace(stdout=b"")

    def worker_scripts_running():
        try:
            first_result.append(engine.Engine._scripts_running())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    try:
        engine.config.IS_WINDOWS = True
        engine._automas_busy = fake_busy
        engine._okww_up = lambda: False
        engine.subprocess = types.SimpleNamespace(
            run=slow_tasklist,
            SubprocessError=real_sub.SubprocessError,
        )
        engine.forget_scripts_cache()

        t = threading.Thread(target=worker_scripts_running)
        t.start()
        check("主线程已进入 tasklist", in_tasklist.wait(timeout=5.0), True)
        # Another thread (game-update / phone command) dispatches a task and invalidates cache.
        busy_state["val"] = True
        engine.forget_scripts_cache()
        allow_finish.set()
        t.join(timeout=5.0)

        check("并发线程无异常", errors, [])
        check("主线程本轮读到旧快照 False", first_result, [False])
        check("缓存没被过期 False 覆盖（仍作废）", engine._SCRIPTS_CACHE["at"] < 0, True)
        check("紧接着 3 秒内再问：重新问 AUTO-MAS 并判在跑",
              (engine.Engine._scripts_running(), busy_state["calls"]), (True, 2))
    finally:
        engine.config.IS_WINDOWS = real_win
        engine._automas_busy = real_busy
        engine.subprocess = real_sub
        engine._okww_up = real_okww
        engine.forget_scripts_cache()

    print("\n[_script_running 超时期间被 forget_scripts_cache 打断：不把旧超时写进缓存]")
    real_open = urllib.request.urlopen
    in_snap = threading.Event()
    allow_snap = threading.Event()
    sr_result: list[bool] = []
    sr_errors: list[BaseException] = []

    def slow_timeout(*a, **k):
        in_snap.set()
        allow_snap.wait(timeout=5.0)
        raise TimeoutError("timed out")

    def worker_script_running():
        try:
            dummy = object.__new__(engine.Engine)
            sr_result.append(dummy._script_running("MaaEnd"))
        except BaseException as exc:  # noqa: BLE001
            sr_errors.append(exc)

    try:
        engine.config.IS_WINDOWS = True
        urllib.request.urlopen = slow_timeout
        engine._SNAP_TIMEOUT.update(since=None, capped_logged=False)
        engine.forget_scripts_cache()

        t2 = threading.Thread(target=worker_script_running)
        t2.start()
        check("单脚本查快照已挂起", in_snap.wait(timeout=5.0), True)
        engine.forget_scripts_cache()
        allow_snap.set()
        t2.join(timeout=5.0)

        check("单脚本超时线程无异常", sr_errors, [])
        check("单脚本超时仍保守返回 True", sr_result, [True])
        check("代际已变，不把旧超时回写进缓存", engine._SCRIPTS_CACHE["at"] < 0, True)
    finally:
        engine.config.IS_WINDOWS = real_win
        urllib.request.urlopen = real_open
        engine._SNAP_TIMEOUT.update(since=None, capped_logged=False)
        engine.forget_scripts_cache()


def _part_snap_timeout_thread_safety():
    """_SNAP_TIMEOUT concurrent timeout/recovery has no float-None TypeError and logs cap once."""
    import logging
    import threading
    import time
    import urllib.error
    import urllib.request

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import engine

    print("[_SNAP_TIMEOUT 跨线程并发超时/恢复：无 TypeError，封顶日志只记一次]")
    real_open = urllib.request.urlopen

    class _OkResp:
        status = 200
        def read(self): return b'{"tasks": []}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.INFO)
            self.lines: list[str] = []

        def emit(self, record):
            self.lines.append(record.getMessage())

    race_errors: list[BaseException] = []
    barrier = threading.Barrier(6)

    def _race_open(url, timeout=3):
        idx = int(threading.current_thread().name.rsplit("-", 1)[-1])
        if idx % 2 == 0:
            raise TimeoutError("timed out")
        if idx == 1:
            raise urllib.error.URLError(ConnectionRefusedError("refused"))
        return _OkResp()

    def _race_worker():
        barrier.wait(timeout=5.0)
        try:
            for _ in range(40):
                engine._automas_snapshot()
        except BaseException as exc:  # noqa: BLE001
            race_errors.append(exc)

    grab = _Grab()
    prev_level = engine.log.level
    engine.log.setLevel(logging.INFO)
    engine.log.addHandler(grab)
    try:
        urllib.request.urlopen = _race_open
        engine._SNAP_TIMEOUT.update(since=None, capped_logged=False)
        threads = [threading.Thread(target=_race_worker, name=f"snap-race-{i}") for i in range(6)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=5.0)
        check("并发读写 _SNAP_TIMEOUT 零异常（无 float - None TypeError）", race_errors, [])

        # Capped log fires exactly once under concurrent timeouts past _SNAP_TIMEOUT_CAP_S
        grab.lines.clear()
        cap_barrier = threading.Barrier(6)
        cap_errors: list[BaseException] = []

        def _always_timeout(*a, **k):
            cap_barrier.wait(timeout=5.0)
            raise TimeoutError("still stuck")

        def _cap_worker():
            try:
                engine._automas_snapshot()
            except BaseException as exc:  # noqa: BLE001
                cap_errors.append(exc)

        urllib.request.urlopen = _always_timeout
        engine._SNAP_TIMEOUT.update(since=time.monotonic() - 240.0, capped_logged=False)
        cap_threads = [threading.Thread(target=_cap_worker) for _ in range(6)]
        for th in cap_threads:
            th.start()
        for th in cap_threads:
            th.join(timeout=5.0)
        capped_lines = [ln for ln in grab.lines if "连续超时超过" in ln]
        check("并发封顶无异常", cap_errors, [])
        check("6 线程同时触发连续超时封顶，只记 1 条日志", len(capped_lines), 1)
    finally:
        engine.log.removeHandler(grab)
        engine.log.setLevel(prev_level)
        urllib.request.urlopen = real_open
        engine._SNAP_TIMEOUT.update(since=None, capped_logged=False)
        engine.forget_scripts_cache()


def _part_daily_upload_concurrency_and_midnight():
    """Concurrent daily uploads (errwatch-push + engine) and midnight _last_ok day isolation."""
    import http.client
    import os
    import threading
    import time
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.features import evidence as ev

    def stamp(dt: datetime) -> str:
        return dt.astimezone().strftime("%m-%d %H:%M:%S")

    def make_cfg(relay_log: Path, state: Path) -> Config:
        cfg = Config()
        cfg.state_dir = state
        cfg.automas_dir = None
        cfg.cos_secret_id = cfg.cos_secret_key = cfg.cos_bucket = cfg.cos_region = "x"
        os.environ["ARK_LOG_FILE"] = str(relay_log)
        return cfg

    saved_state = (
        ev._last_attempt[0],
        ev._last_day[0],
        dict(ev._last_ok),
        list(ev._last_errors),
        ev._ocr_sent[0],
        os.environ.get("ARK_LOG_FILE"),
    )
    try:
        d1 = datetime(2026, 11, 26, 23, 59, 30, tzinfo=SERVER_TZ)
        d2 = datetime(2026, 11, 27, 0, 0, 10, tzinfo=SERVER_TZ)
        d2_later = datetime(2026, 11, 27, 0, 0, 20, tzinfo=SERVER_TZ)

        st = tmpdir()
        relay = tmpdir() / "relay.log"
        relay.write_text(
            f"{stamp(d1)} INFO    ark.test  day1-line\n"
            f"{stamp(d2)} INFO    ark.test  day2-line\n",
            encoding="utf-8",
        )
        cfg = make_cfg(relay, st)

        print("[并发上传：加锁串行化 + 独立临时目录，不共享固定路径，事后清理]")
        active = [0]
        max_active = [0]
        seen_paths: list[Path] = []
        guard = threading.Lock()
        entered = threading.Event()
        release = threading.Event()

        class SlowUp:
            def __init__(self, gate: bool = False):
                self.gate = gate

            def upload(self, path: Path, timeout: int = 60) -> dict:
                with guard:
                    active[0] += 1
                    max_active[0] = max(max_active[0], active[0])
                    seen_paths.append(path)
                    first_in = len(seen_paths) == 1
                try:
                    if self.gate and first_in:
                        entered.set()
                        release.wait(5)
                    else:
                        time.sleep(0.02)
                    data = path.read_bytes()
                    assert data, "staged file must be readable"
                    key = f"daily/{path.name}"
                    return {"name": path.name, "url": f"https://host/{key}", "page": f"https://host/{key}?sig=1"}
                finally:
                    with guard:
                        active[0] -= 1

        ev._last_attempt[0] = 0.0
        ev._last_day[0] = ""
        ev._last_ok.clear()
        ev._last_errors.clear()

        up = SlowUp(gate=True)
        outs: list[dict] = []
        errs: list[Exception] = []

        def worker(force: bool, t_val: float):
            try:
                outs.append(ev.upload_daily_logs(cfg, force=force, now=d1, clock=lambda: t_val, uploader=up))
            except Exception as exc:  # noqa: BLE001
                errs.append(exc)

        t_err = threading.Thread(target=worker, args=(False, 1000.0), name="errwatch-push")
        t_eng = threading.Thread(target=worker, args=(True, 1001.0), name="engine-shutdown")
        t_err.start()
        check("首线程进入上传", entered.wait(5), True)
        t_eng.start()
        time.sleep(0.05)
        check("第二线程等待锁，未并发进入上传", max_active[0], 1)
        release.set()
        t_err.join(5)
        t_eng.join(5)
        check("双线程并发无异常", errs, [])
        check("双线程均完成且全程串行（并发峰值=1）", (len(outs), max_active[0]), (2, 1))
        daily_dir = st / "evidence" / "daily"
        check("上传文件基名保持 relay-YYYY-MM-DD.log",
              [p.name for p in seen_paths], ["relay-2026-11-26.log", "relay-2026-11-26.log"])
        check("每次上传使用独立临时目录（非共享 daily/ 固定路径）",
              (all(p.parent != daily_dir for p in seen_paths), len({p.parent for p in seen_paths}) == 2),
              (True, True))
        check("上传后临时目录已清理", list(daily_dir.iterdir()), [])

        print("\n[双线程同时 force=False：前者完成、后者命调节流并拿到链接]")
        ev._last_attempt[0] = 0.0
        ev._last_day[0] = ""
        ev._last_ok.clear()
        seen_paths.clear()
        entered.clear()
        release.clear()
        outs.clear()
        up2 = SlowUp(gate=True)

        def worker2(t_val: float):
            outs.append(ev.upload_daily_logs(cfg, force=False, now=d1, clock=lambda: t_val, uploader=up2))

        t1 = threading.Thread(target=worker2, args=(2000.0,))
        t2 = threading.Thread(target=worker2, args=(2002.0,))
        t1.start()
        check("线程 1 进入上传", entered.wait(5), True)
        t2.start()
        time.sleep(0.05)
        release.set()
        t1.join(5)
        t2.join(5)
        check("仅真正上传 1 次", len(seen_paths), 1)
        check("一次上传、一次节流跳过，两者都带当天链接",
              (sorted(o["skipped"] for o in outs), all("relay-2026-11-26.log" in o["url"] for o in outs)),
              ([False, True], True))

        print("\n[跨零点隔离：23:59:30 上传后 00:00:10 不返回前一天链接]")
        ev._last_attempt[0] = 0.0
        ev._last_day[0] = ""
        ev._last_ok.clear()
        ev._last_errors.clear()
        up3 = SlowUp(gate=False)
        r_d1 = ev.upload_daily_logs(cfg, force=False, now=d1, clock=lambda: 3000.0, uploader=up3)
        check("23:59:30 返回前一天链接", "relay-2026-11-26.log" in r_d1["url"], True)
        r_d2 = ev.upload_daily_logs(cfg, force=False, now=d2, clock=lambda: 3040.0, uploader=up3)
        check("00:00:10 跨日不被前一天节流，直接上传新一天日志",
              (r_d2["skipped"], "relay-2026-11-27.log" in r_d2["url"]), (False, True))

        class FailUp:
            def upload(self, path: Path, timeout: int = 60) -> dict:
                raise OSError("cos down")

        ev._last_attempt[0] = 0.0
        ev._last_day[0] = ""
        ev._last_ok.clear()
        ev._last_errors.clear()
        r_prev = ev.upload_daily_logs(cfg, force=False, now=d1, clock=lambda: 4000.0, uploader=up3)
        check("前一天上传成功", "relay-2026-11-26.log" in r_prev["url"], True)
        r_fail = ev.upload_daily_logs(cfg, force=False, now=d2, clock=lambda: 4040.0, uploader=FailUp())
        check("新一天首次上传失败", (r_fail["skipped"], bool(r_fail["errors"]), r_fail["url"]), (False, True, ""))
        r_throt = ev.upload_daily_logs(cfg, force=False, now=d2_later, clock=lambda: 4050.0, uploader=FailUp())
        check("新一天失败后 10s 命调节流：不泄露前一天链接，保留当天错误",
              (r_throt["skipped"], r_throt["url"], r_throt["truncated"], r_throt["errors"]),
              (True, "", False, r_fail["errors"]))

        print("\n[check_sources 捕获 HTTPException，prune 清理崩溃残留临时目录]")
        def cut_fetch(_url: str) -> bytes:
            raise http.client.IncompleteRead(b"partial")

        changed, unreach = ev.check_sources(fetch=cut_fetch)
        check("IncompleteRead 记为不可达而不崩溃", (changed, len(unreach)), ([], len(ev.PINS)))

        stale = daily_dir / ".upload-stale"
        stale.mkdir(parents=True, exist_ok=True)
        (stale / "relay-2026-08-01.log").write_text("x", encoding="utf-8")
        old_ts = (datetime.now() - timedelta(days=40)).timestamp()
        os.utime(stale, (old_ts, old_ts))
        ev.prune(st, 30)
        check("prune 清掉超期临时目录", stale.exists(), False)
    finally:
        ev._last_attempt[0] = saved_state[0]
        ev._last_day[0] = saved_state[1]
        ev._last_ok.clear()
        ev._last_ok.update(saved_state[2])
        ev._last_errors[:] = saved_state[3]
        ev._ocr_sent[0] = saved_state[4]
        if saved_state[5] is None:
            os.environ.pop("ARK_LOG_FILE", None)
        else:
            os.environ["ARK_LOG_FILE"] = saved_state[5]


if __name__ == "__main__":
    sys.exit(run_parts([_part_evidence_main, _part_evidence_archive, _part_evidence_cli_window, _part_evidence_daily_silent, _part_evidence_maaend_live_logs, _part_evidence_notify_once, _part_evidence_relay_after_run, _part_evidence_saved_count, _part_evidence_sources_unreachable, _part_error_evidence, _part_game_evidence, _part_held_push_keeps_evidence, _part_task_shots, _part_tacet_shots, _part_self_attrs_main, _part_self_heal_red, _part_undefined_names, _part_module_table, _part_parts, _part_scripts_relay_attrs, _part_scripts_running_asks_automas, _part_scripts_cache_toctou, _part_snap_timeout_thread_safety, _part_daily_upload_concurrency_and_midnight]))
