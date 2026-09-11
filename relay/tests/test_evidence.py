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
        f.truncate(e["size"])          # sparse: same size, no disk cost
    mt = 1_800_000_000 - img_rank[name] if name in img_rank else e["mtime"]
    os.utime(p, (mt, mt))
entries = ev.maaend_entries(root)
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
out = ev.bundle_maaend(small, tmpdir() / "mxout", "v2.28.0-rc.1", _dt(2026, 9, 11, 12, 23, 50))
check("一卷，两位编号", [p.name for p in out], ["MaaEnd-logs-v2.28.0-rc.1-20260911-122350-part01.zip"])
with zipfile.ZipFile(out[0]) as z:
    check("三个文件都在，顺序对", z.namelist(), ["maafw.log", "config/mxu-MaaEnd.json", "on_error/a.png"])
check("空目录不出包", ev.bundle_maaend(tmpdir() / "nothing", tmpdir() / "o2", "v"), [])

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
out = ev.bundle_maa(maa, tmpdir() / "out")
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
out = ev.bundle_okww(ww, tmpdir() / "out2")
check("一个包，名字对", [p.name for p in out], ["ok-ww-log.zip"])
with zipfile.ZipFile(out[0]) as z:
    check("只有那两个目录", sorted(z.namelist()), ["logs/ok-script.log", "screenshots/a.png"])
check("空目录不出包", ev.bundle_okww(tmpdir() / "empty", tmpdir() / "out3"), [])

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

print("\n[上传：索引里记下每一趟，失败也记]")
class FakeUp:
    def __init__(self): self.n = 0
    def upload(self, path):
        self.n += 1
        if path.name.endswith("_part02.zip"):
            raise RuntimeError("boom")            # fails all three tries
        return {"id": str(self.n), "name": path.name, "page": "https://gofile.io/d/x", "size": path.stat().st_size}
ev.time.sleep = lambda s: None                     # no waiting between the retries in a test
class Cfg:
    state_dir = tmpdir() / "state"; maaend_dir = None; maa_dir = maa; okww_dir = None; history_dir = None
res = ev.save_and_upload(Cfg, "MAA", "2026-09-11/arknights/MAA-17-30-00", uploader=FakeUp())
check("两个包，一个传上去一个三次都失败", (len(res["files"]), len(res["uploaded"]), len(res["errors"])), (2, 1, 1))
check("有下载页", res.get("page"), "https://gofile.io/d/x")
idx = (Cfg.state_dir / "evidence" / "index.jsonl").read_text(encoding="utf-8").strip().splitlines()
check("索引写了一行", len(idx), 1)
check("没配置的脚本不出包", ev.bundle_for("OK-WW", Cfg, tmpdir() / "o"), [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
