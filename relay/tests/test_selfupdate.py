"""The self-update: atomic sha256 writes, COS, its doors, the exit.

One part per former file, each run on its own (tests/_parts.py): test_selfupdate_atomic_sha256.py, test_selfupdate_cos.py, test_selfupdate_doors.py, test_selfupdate_exit.py.
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


def _part_selfupdate_atomic_sha256():
    """Self-update lands all files or none, and checks them by SHA-256 (review of 2026-10-07, item 4).

Two gaps were left after the download-everything-first rule:

* _write_staged wrote the targets one by one. A disk or permission error on the
  second file left the first one new and the rest old - and check() then
  cleared the failure it had just recorded and announced an update, and
  service.py restarted into the mixed version. Now every file is written to a
  staging directory first, and only when all of them are there are they swapped
  in; a failure while swapping puts back the ones already swapped. Either way
  the originals are what is on disk after a failure, and the failure stays
  recorded.
* Files were checked by SHA-1 only, which hashlib lists as a legacy algorithm.
  make-manifest.py now writes a `sha256` map next to `files`; the relay checks
  by it when it is there. `files` stays SHA-1 for one version, so a machine
  still on the old code (which only reads `files`) updates normally onto this
  one; a manifest with no `sha256` (one made before this change) is still
  checked by SHA-1.

    Formerly test_selfupdate_atomic_sha256.py.
    """
    import hashlib
    import json
    import shutil
    import subprocess
    import tempfile
    import time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import os
    from ark_relay.features.selfupdate import selfupdate as su
    from ark_relay.core.statestore import StateStore

    os.environ[su.GITHUB_FALLBACK_ENV] = "1"     # the GitHub doors, as in test_selfupdate_doors.py
    RELAY = Path(__file__).resolve().parents[1]


    class _NoSleep:
        monotonic = staticmethod(time.monotonic)

        @staticmethod
        def sleep(_s):
            return None


    su.time = _NoSleep
    su._cos = lambda: None
    sha1 = lambda b: hashlib.sha1(b).hexdigest()      # noqa: E731
    sha256 = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
    OLD_A, OLD_B = b"print('a old')\n", b"print('b old')\n"
    NEW_A, NEW_B = b"print('a new')\n", b"print('b new')\n"


    def serve(man: dict, bodies: dict):
        """Every door answers with this manifest and these files."""
        data = json.dumps(man).encode("utf-8")

        def get(url, timeout=20):
            rel = url.split("/relay/", 1)[-1]
            if "/relay-" in url and rel == "manifest.json":
                return None
            return data if rel == "manifest.json" else bodies.get(rel)
        su._get_once = get
        su._last_good = ""


    def machine():
        root = tmpdir()
        (root / "state").mkdir()
        (root / "a.py").write_bytes(OLD_A)
        (root / "b.py").write_bytes(OLD_B)
        StateStore(root / "state").set("versions", "code", "20261001000000")
        return root


    def leftovers(root: Path) -> list:
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                      if p.name not in ("a.py", "b.py") and not p.relative_to(root).as_posix().startswith("state"))


    BASE = "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"
    NEW = {"version": 20261007000000,
           "files": {"a.py": sha1(NEW_A), "b.py": sha1(NEW_B)},
           "sha256": {"a.py": sha256(NEW_A), "b.py": sha256(NEW_B)}}
    BODIES = {"a.py": NEW_A, "b.py": NEW_B}


    def failed_round(root, label):
        check(f"{label}：返回空", su.check(root, BASE), [])
        check(f"{label}：a.py 还是原来的", (root / "a.py").read_bytes(), OLD_A)
        check(f"{label}：b.py 还是原来的", (root / "b.py").read_bytes(), OLD_B)
        check(f"{label}：版本号没前进", StateStore(root / "state").get("versions", "code"), "20261001000000")
        check(f"{label}：没留下「已更新」的播报", su.take_announcement(root), None)
        check(f"{label}：失败记下了（下次开机重来、会报出来）", bool(su.take_failure(root)), True)
        check(f"{label}：没留下暂存文件", leftovers(root), [])


    print("[写到第二个文件时磁盘出错：两个原文件都不许动]")
    root = machine()
    serve(NEW, BODIES)
    real_write = su._atomic_write
    n = [0]


    def write_fails_second(target, data):
        n[0] += 1
        if n[0] == 2:
            raise OSError(28, "No space left on device")
        real_write(target, data)


    su._atomic_write = write_fails_second
    try:
        failed_round(root, "写入失败")
    finally:
        su._atomic_write = real_write

    print("\n[换到第二个文件时出错（文件被占用）：已换上的那个要改回原样]")
    root = machine()
    serve(NEW, BODIES)
    real_swap = getattr(su, "_swap_in", None)
    real_replace = os.replace
    m = [0]


    def swap_fails_second(src, dst):
        m[0] += 1
        if m[0] == 2:
            raise PermissionError(32, "being used by another process")
        real_replace(src, dst)


    su._swap_in = swap_fails_second
    try:
        failed_round(root, "替换失败")
    finally:
        if real_swap is None:
            del su._swap_in
        else:
            su._swap_in = real_swap

    print("\n[一切正常：两个都换上，版本号前进，没有暂存残留]")
    root = machine()
    serve(NEW, BODIES)
    check("两个都更新了", su.check(root, BASE), ["a.py", "b.py"])
    check("a.py 是新的", (root / "a.py").read_bytes(), NEW_A)
    check("b.py 是新的", (root / "b.py").read_bytes(), NEW_B)
    check("版本号前进", StateStore(root / "state").get("versions", "code"), "20261007000000")
    check("没留下暂存文件", leftovers(root), [])

    print("\n[SHA-256 对不上（SHA-1 却对得上）：按 SHA-256 判，不更新]")
    root = machine()
    bad = dict(NEW, sha256={"a.py": sha256(b"something else"), "b.py": sha256(NEW_B)})
    serve(bad, BODIES)
    check("不更新", su.check(root, BASE), [])
    check("a.py 原封不动", (root / "a.py").read_bytes(), OLD_A)
    check("b.py 也没动（整轮放弃）", (root / "b.py").read_bytes(), OLD_B)

    print("\n[SHA-256 表缺一个文件：这份清单不可信，整轮不更新]")
    root = machine()
    serve(dict(NEW, sha256={"a.py": sha256(NEW_A)}), BODIES)
    check("不更新", su.check(root, BASE), [])
    check("a.py 原封不动", (root / "a.py").read_bytes(), OLD_A)

    print("\n[旧格式清单（只有 SHA-1）：照旧能更新——兼容这一版之前做的清单]")
    root = machine()
    serve({"version": 20261007000000, "files": {"a.py": sha1(NEW_A), "b.py": sha1(NEW_B)}}, BODIES)
    check("两个都更新了", su.check(root, BASE), ["a.py", "b.py"])

    print("\n[本机已是新的：按 SHA-256 判出不用动]")
    root = machine()
    (root / "a.py").write_bytes(NEW_A)
    (root / "b.py").write_bytes(NEW_B)
    serve(NEW, BODIES)
    check("没有要改的", su.check(root, BASE), [])
    check("版本号记下", StateStore(root / "state").get("versions", "code"), "20261007000000")

    print("\n[make-manifest.py：files 仍是 SHA-1（给旧机器），另有一张一一对应的 sha256 表]")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "relay"
        shutil.copytree(RELAY, copy, ignore=shutil.ignore_patterns("tests", "state", "__pycache__"))
        out = subprocess.run([sys.executable, "make-manifest.py"], cwd=copy, capture_output=True, text=True)
        check("生成器跑得起来", out.returncode, 0)
        man = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
        files, s256 = man.get("files") or {}, man.get("sha256") or {}
        check("有 sha256 表", bool(s256), True)
        check("两张表文件一样", sorted(s256) == sorted(files), True)
        check("files 每一项都是那个文件的 SHA-1",
              [f for f, h in files.items() if h != sha1((copy / f).read_bytes())], [])
        check("sha256 每一项都是那个文件的 SHA-256",
              [f for f, h in s256.items() if h != sha256((copy / f).read_bytes())], [])


def _part_selfupdate_cos():
    """selfupdate.py's first door is the COS bucket; GitHub's four stay as the fallback.

2026-09-18: a manifest pushed at 02:31 was still the old one on the machine's
jsDelivr node at 08:45 (per-node caches), and the fix only landed by a hand
deploy. COS has no cache layer. What this file pins:

* latest.json is read first; when its version is not newer, no manifest and no
  bundle are fetched (one tiny request per boot).
* A newer version on COS: manifest + bundle from COS, every wanted file
  verified against the manifest's SHA-1, nothing asked of GitHub.
* Anything wrong on COS (missing object - the lifecycle rule -, bad hash in the
  bundle, latest/manifest disagreeing, the client itself failing) falls back to
  the GitHub doors silently - never an abandoned round because of COS.
* Without COS credentials nothing changes: the GitHub path as before.
* The GitHub fallback fetches files concurrently and still lands all-or-nothing.
No network: _get_once and _cos_get are replaced.

    Formerly test_selfupdate_cos.py.
    """
    import hashlib
    import io
    import json
    import os
    import threading
    import time
    import zipfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.selfupdate import selfupdate as su
    from ark_relay.core.statestore import StateStore


    class _NoSleep:
        monotonic = staticmethod(time.monotonic)

        @staticmethod
        def sleep(_s):
            return None


    su.time = _NoSleep
    sha = lambda b: hashlib.sha1(b).hexdigest()  # noqa: E731


    class FakeCos:
        prefix = "relay"
        host = "bucket.cos.ap-shanghai.myqcloud.com"

        def __init__(self, objects):
            self.objects = objects      # {key: bytes}
            self.got = []

        def authorization(self, *a, **k):
            return "sig"


    class Net:
        def __init__(self, doors):
            self.doors, self.tried = doors, []

        def get(self, url, timeout=20):
            host = su._netloc(url); rel = url.split("/relay/", 1)[-1]
            self.tried.append((host, rel))
            return self.doors.get(host, {}).get(rel)


    def fake_cos_get(cos, key, timeout=20):
        cos.got.append(key)
        return cos.objects.get(key)


    def workdir(files, code_version=""):
        root = tmpdir(); (root / "state").mkdir()
        for rel, body in files.items():
            p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(body)
        if code_version:
            StateStore(root / "state").set("versions", "code", str(code_version))
        return root


    def bundle(files: dict) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for rel, body in files.items():
                z.writestr(rel, body)
        return buf.getvalue()


    def setup(cos_objects, doors, local_files, local_ver):
        su._cos_get = fake_cos_get
        net = Net(doors); su._get_once = net.get; su._last_good = ""
        cos = FakeCos(cos_objects) if cos_objects is not None else None
        su._cos = lambda: cos
        return net, cos, workdir(local_files, local_ver)


    OLD_A, NEW_A, NEW_B = b"a v1\n", b"a v2\n", b"b v2\n"
    FILES_V2 = {"ark_relay/a.py": sha(NEW_A), "ark_relay/b.py": sha(NEW_B)}
    MAN_V2 = json.dumps({"version": 20260918020000, "files": FILES_V2}).encode()

    os.environ.pop(su.GITHUB_FALLBACK_ENV, None)      # the default: GitHub doors off
    print("[COS 上是新版：只碰 COS，文件全部来自 bundle，GitHub 一次都不问]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000, "uploaded": "2026-09-18T02:00:00+00:00"}',
         "20260918020000/manifest.json": MAN_V2,
         "20260918020000/bundle.zip": bundle({"ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B})},
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("两个文件都更新了", sorted(updated), ["ark_relay/a.py", "ark_relay/b.py"])
    check("落盘内容对", (root / "ark_relay/a.py").read_bytes(), NEW_A)
    check("COS 请求顺序：latest → manifest → bundle", cos.got, ["latest.json", "20260918020000/manifest.json", "20260918020000/bundle.zip"])
    check("GitHub 一扇门都没问", net.tried, [])
    check("版本号记下了", StateStore(root / "state").get("versions", "code"), "20260918020000")

    print("\n[COS 上不比本机新：只读一次 latest.json，到此为止——GitHub 一扇门都不问]")
    # 2026-09-18 19:14, right after a deploy: COS said "this very version", yet the old
    # logic went on to GitHub, waited 20 s on a reset from raw, then warned "manifest
    # older than local, cache probably stale" about a manifest that was simply the
    # previous one. Every deploy writes COS last, so GitHub can never be ahead of it.
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260917000000}'},
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    su._record_failure(root, "上次的失败", 1, 1, [])
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("COS 只碰了 latest.json", cos.got, ["latest.json"])
    check("不更新", updated, [])
    check("GitHub 一扇门都没问", net.tried, [])
    check("磁盘没动", (root / "ark_relay/a.py").read_bytes(), OLD_A)
    check("已是最新 = 没有未完成的事，旧的失败报告清掉", su.take_failure(root), None)

    # ---- GitHub doors off by default (operator decision 2026-09-18 evening) ----
    print("\n[默认不开备用线路：COS 的清单拿不到 → 记失败、一扇 GitHub 门都不问、磁盘不动]")
    os.environ.pop(su.GITHUB_FALLBACK_ENV, None)
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000}'},          # manifest / bundle missing
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("不更新", updated, [])
    check("GitHub 一扇门都没问", net.tried, [])
    check("磁盘没动", (root / "ark_relay/a.py").read_bytes(), OLD_A)
    fail = su.take_failure(root)
    check("失败记下了、开机会报", bool(fail) and "备用线路已关" in fail["reason"], True)
    check("失败记录里本机版本对", fail and fail["local"], 20260917000000)

    print("\n[默认不开备用线路：bundle 哈希不对 → 记失败，不去 GitHub 补]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000}', "20260918020000/manifest.json": MAN_V2,
         "20260918020000/bundle.zip": bundle({"ark_relay/a.py": b"tampered\n", "ark_relay/b.py": NEW_B})},
        {"fastly.jsdelivr.net": {"ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("不更新", updated, [])
    check("GitHub 一扇门都没问", net.tried, [])
    check("b.py 虽然在包里是对的也不落盘（全有或全无）", (root / "ark_relay/b.py").read_bytes(), b"b v1\n")
    fail = su.take_failure(root)
    check("失败记下了，带着本来要更新的文件", fail and sorted(fail["files"]), ["ark_relay/a.py", "ark_relay/b.py"])

    print("\n[默认不开备用线路：没配 COS → 一条警告 + 失败记录，不更新]")
    net, cos, root = setup(None,
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    check("不更新", su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"), [])
    check("GitHub 一扇门都没问", net.tried, [])
    check("失败记下了", bool(su.take_failure(root)), True)

    print("\n[默认不开备用线路：COS 正常时和开着一样——两个文件从 bundle 落地]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000, "uploaded": "2026-09-18T02:00:00+00:00"}',
         "20260918020000/manifest.json": MAN_V2,
         "20260918020000/bundle.zip": bundle({"ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B})},
        {}, {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    check("两个文件都更新了", sorted(su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")),
          ["ark_relay/a.py", "ark_relay/b.py"])
    check("没有失败记录", su.take_failure(root), None)

    # ---- the same situations with the switch on: every old expectation still holds ----
    print("\n[开关打开（" + su.GITHUB_FALLBACK_ENV + "=1）：以下全是备用线路的老行为]")
    os.environ[su.GITHUB_FALLBACK_ENV] = "1"

    print("\n[COS 的对象被生命周期规则删了（404）：静默退回 GitHub，整轮照常完成]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000}'},          # manifest / bundle missing
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("更新照常落地", sorted(updated), ["ark_relay/a.py", "ark_relay/b.py"])
    check("问过 COS 的 manifest 没拿到就走 GitHub", "20260918020000/manifest.json" in cos.got and any(h == "fastly.jsdelivr.net" for h, _ in net.tried))

    print("\n[COS 的 bundle 里哈希不对：一个字节都不用它，退回 GitHub]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000}', "20260918020000/manifest.json": MAN_V2,
         "20260918020000/bundle.zip": bundle({"ark_relay/a.py": b"tampered\n", "ark_relay/b.py": NEW_B})},
        {"fastly.jsdelivr.net": {"ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("结果仍然正确", (root / "ark_relay/a.py").read_bytes(), NEW_A)
    check("两个文件都从 GitHub 取（bundle 整体弃用）", sorted(r for _, r in net.tried), ["ark_relay/a.py", "ark_relay/b.py"])

    print("\n[latest.json 和 manifest 版本对不上：不信 COS]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000}',
         "20260918020000/manifest.json": json.dumps({"version": 20260918010000, "files": FILES_V2}).encode()},
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("走 GitHub 完成", sorted(updated), ["ark_relay/a.py", "ark_relay/b.py"])
    check("bundle 没有被请求", "20260918020000/bundle.zip" not in cos.got)

    print("\n[没配 COS：和以前一模一样]")
    net, cos, root = setup(None,
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("GitHub 更新", sorted(updated), ["ark_relay/a.py", "ark_relay/b.py"])

    print("\n[COS 客户端自己抛异常：不影响 GitHub 路]")
    def boom():
        raise RuntimeError("no keys")
    su._cos = boom
    net = Net({"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}}); su._get_once = net.get; su._last_good = ""
    root = workdir({"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    check("照常更新", sorted(su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")), ["ark_relay/a.py", "ark_relay/b.py"])

    print("\n[GitHub 回退是并发的，而且仍然全有或全无]")
    many = {f"ark_relay/m{i}.py": f"m{i} v2\n".encode() for i in range(12)}
    man = json.dumps({"version": 20260918030000, "files": {k: sha(v) for k, v in many.items()}}).encode()
    class SlowNet(Net):
        lock = threading.Lock()
        def __init__(self, doors):
            super().__init__(doors); self.active = 0; self.peak = 0
        def get(self, url, timeout=20):
            with self.lock:
                self.active += 1; self.peak = max(self.peak, self.active)
            try:
                time.sleep(0.05)
                return super().get(url, timeout)
            finally:
                with self.lock:
                    self.active -= 1
    su._cos = lambda: None
    net = SlowNet({"fastly.jsdelivr.net": {"manifest.json": man, **many}}); su._get_once = net.get; su._last_good = ""
    root = workdir({k: b"old\n" for k in many}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("12 个文件全更新", len(updated), 12)
    check("确实并发了（峰值 >1）", net.peak > 1)
    # Width, not wall time: a 50 ms time.sleep on this Mac measured 130-150 ms on
    # 2026-09-23 06:06 (OS timer slack), which turned the old "under 0.45 s" into a
    # test of the clock. Full pool width is what makes the fallback faster.
    check(f"并发宽度用满（峰值 = PARALLEL_FETCHES = {su.PARALLEL_FETCHES}）", net.peak, min(su.PARALLEL_FETCHES, 12))
    missing_one = dict(many); missing_one.pop("ark_relay/m7.py")
    net = SlowNet({"fastly.jsdelivr.net": {"manifest.json": man, **missing_one}}); su._get_once = net.get; su._last_good = ""
    root = workdir({k: b"old\n" for k in many}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("一个文件拿不到 → 一个都不落盘", (updated, (root / "ark_relay/m0.py").read_bytes()), ([], b"old\n"))

    print()
    if fails:
        print("FAILED:", fails); sys.exit(1)
    print("all checks passed")


def _part_selfupdate_doors():
    """selfupdate.py 的四扇门、粘性、拒绝旧清单、对不上哈希就一个字节都不落盘。

这个文件防的损失只有一种，但它是最难发现的一种：**推上去的修复到不了机器，
而屏幕上一片绿**。中继自己不会喊「我没更新成」，日志照常打「已更新 N 个文件」，
人在另一个国家，只能等下一次事故才发现机器还在跑旧代码。

具体钉四件事：

* **四扇门的顺序**（fastly → cdn → gcore → raw）。2026-08-21 在机器上量过 8 轮：
  fastly 8/8 平均 426ms，raw 2/8 平均 38 秒。顺序被人「顺手整理」一下，
  开机那 8 分钟的窗口就全耗在最慢的门上，更新赶不上 09:00 的队列。
* **粘性**：上次哪扇门成了，下次先问它。raw 整晚整晚地黑（08-17、08-20 各一次），
  没有粘性的话，一次多文件更新的每个文件都要先在死门上耗满超时。
* **拿到的清单比本机旧就必须拒绝**。2026-08-21 出过一次：CDN 缓存着上一版的
  「旧清单 + 旧 .py」，两者自洽、哈希也对得上，机器被静默降级回旧代码，
  日志写着「已更新 1 个文件」，一切正常。判据不许写成 `remote and local and ...`
  ——没有版本号的旧清单 remote_ver 是 0，那种写法会直接放行。
* **哈希对不上，一个字节都不许落盘**。半个更新比不更新危险得多：service.py
  一看到文件变了就重启，于是重启进一个「新 engine.py + 旧 core.py」的中继。

全程不联网：`_get_once` 被换成假的，重试之间的等待也跳过。

    Formerly test_selfupdate_doors.py.
    """
    import json
    import time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.selfupdate import selfupdate as su
    from ark_relay.core.statestore import StateStore

    # Everything here is the GitHub fallback, which is off by default since
    # 2026-09-18 (see selfupdate.GITHUB_FALLBACK_ENV); switch it on for this file.
    # The default-off behaviour is pinned in test_selfupdate_cos.py.
    import os
    os.environ[su.GITHUB_FALLBACK_ENV] = "1"


    BASE = "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"
    FASTLY, CDN, GCORE, RAW = ("fastly.jsdelivr.net", "cdn.jsdelivr.net",
                               "gcore.jsdelivr.net", "raw.githubusercontent.com")


    class _NoSleep:
        """重试之间的等待与测试无关，跳过它；单调时钟保持真的，预算判断还要用。"""

        monotonic = staticmethod(time.monotonic)

        @staticmethod
        def sleep(_seconds):
            return None


    su.time = _NoSleep


    class Net:
        """假网络。doors: {域名: {文件相对路径: bytes}}；没有的键就是这扇门取不到。"""

        def __init__(self, doors):
            self.doors = doors
            self.tried = []

        def get(self, url, timeout=20):
            host = su._netloc(url)
            rel = url.split("/relay/", 1)[-1]
            self.tried.append((host, rel))
            return self.doors.get(host, {}).get(rel)

        @property
        def hosts(self):
            return [h for h, _ in self.tried]


    def use(net):
        su._get_once = net.get
        su._last_good = ""          # 每个用例从「没有粘性」开始
        return net


    def manifest(version, files):
        return json.dumps({"version": version, "files": files}).encode("utf-8")


    def workdir(files, code_version=""):
        """一台机器：root 下摆好现有文件，state 里记好本机代码版本。"""
        root = tmpdir()
        (root / "state").mkdir()
        for rel, body in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body)
        if code_version:
            StateStore(root / "state").set("versions", "code", str(code_version))
        return root


    # ------------------------------------------------------------------ 门的顺序

    print("[四扇门的顺序：fastly → cdn → gcore → raw，raw 永远垫底]")
    alts = su._alternates(BASE + "manifest.json")
    check("四扇门都在", len(alts), 4)
    check("顺序", [su._netloc(u) for u in alts], [FASTLY, CDN, GCORE, RAW])
    check("jsDelivr 走的是同一个仓库同一个分支", alts[0],
          "https://fastly.jsdelivr.net/gh/herclyon1/maa@main/relay/manifest.json")
    check("raw 原样保留在最后", alts[-1], BASE + "manifest.json")

    print("\n[不是 raw.githubusercontent 的地址，不许自作主张换门]")
    check("别的域名原样返回", su._alternates("https://example.com/relay/a.py"),
          ["https://example.com/relay/a.py"])
    check("raw 但路径不成形（没有 owner/repo/branch/path）",
          su._alternates("https://raw.githubusercontent.com/herclyon1/maa"),
          ["https://raw.githubusercontent.com/herclyon1/maa"])

    print("\n[_pinned_base：文件按清单自己的标签取，不按分支——标签不会动，哪扇门答都是对的字节]")
    # Evening of 2026-09-18: eight hours after the push and the purge, cdn and gcore still
    # served the previous RELEASE-NOTES.md, raw and fastly were reset or timed out, one
    # file ate the whole 240 s budget, the round was abandoned, the machine ran old code.
    check("有 ref 就换成标签", su._pinned_base(BASE, {"ref": "relay-20260918111328"}),
          "https://raw.githubusercontent.com/herclyon1/maa/relay-20260918111328/relay/")
    check("四扇门都跟着标签走",
          [u.split("/relay/")[0].rsplit("/", 1)[-1] for u in
           su._alternates(su._pinned_base(BASE, {"ref": "relay-20260918111328"}) + "a.py")],
          ["maa@relay-20260918111328", "maa@relay-20260918111328", "maa@relay-20260918111328",
           "relay-20260918111328"])
    check("没有 ref（09-18 之前的清单）照旧走分支", su._pinned_base(BASE, {}), BASE)
    check("ref 不是纯标签名（清单是网上来的）就不拼进地址",
          su._pinned_base(BASE, {"ref": "../../evil"}), BASE)
    check("ref 不是字符串也不拼", su._pinned_base(BASE, {"ref": 20260918}), BASE)
    check("不是 raw 的地址不动", su._pinned_base("https://example.com/relay/", {"ref": "relay-1"}),
          "https://example.com/relay/")

    print("\n[_netloc：取主机名，取不到就原样返回，任何输入都不许抛异常]")
    check("普通地址", su._netloc("https://fastly.jsdelivr.net/gh/a/b@c/d.py"), FASTLY)
    check("raw", su._netloc(BASE + "a.py"), RAW)
    check("没有主机名就返回原串", su._netloc("这不是地址"), "这不是地址")
    check("空串", su._netloc(""), "")


    # -------------------------------------------------------------------- 粘性

    print("\n[粘性：上次哪扇门成了，下次先问它]")
    body = b"print('new')\n"
    sha = su._sha1(body)
    net = use(Net({GCORE: {"a.py": body}}))     # 只有 gcore 有货
    got = su._get_with_retry(BASE + "a.py", expect_sha=sha)
    check("第三扇门拿到了", got, body)
    check("按顺序一扇扇试过来", net.hosts[:3], [FASTLY, CDN, GCORE])
    check("记住了这扇门", su._last_good, GCORE)

    net = Net({GCORE: {"a.py": body}, FASTLY: {"a.py": body}})
    su._get_once = net.get                       # 不清粘性：这次要先问 gcore
    su._get_with_retry(BASE + "a.py", expect_sha=sha)
    check("下一个文件先问上次成的那扇门", net.hosts[0], GCORE)
    check("一扇就够了，没白等前两扇", len(net.tried), 1)

    print("\n[粘的那扇门黑了，其余三扇还是要试——粘性不许变成独门]")
    net = Net({RAW: {"a.py": body}})
    su._get_once = net.get                       # 粘的还是 gcore，但 gcore 这次没货
    check("最后还是拿到了", su._get_with_retry(BASE + "a.py", expect_sha=sha), body)
    check("四扇门一扇不落", sorted(set(net.hosts[:4])), sorted([FASTLY, CDN, GCORE, RAW]))
    check("粘性改判到真正成的那扇", su._last_good, RAW)


    # ------------------------------------------------------- 缓存发旧副本换下一扇门

    print("\n[某扇门发的是旧副本：换下一扇，不是整轮放弃]")
    old = b"print('old')\n"
    net = use(Net({FASTLY: {"a.py": old}, CDN: {"a.py": old},
                   GCORE: {"a.py": old}, RAW: {"a.py": body}}))
    check("最终拿到的是对得上哈希的那份", su._get_with_retry(BASE + "a.py", expect_sha=sha), body)
    check("四扇门都问过", net.hosts[:4], [FASTLY, CDN, GCORE, RAW])

    print("\n[四扇门都只有旧副本：宁可拿不到，也不许把旧的当新的用]")
    net = use(Net({h: {"a.py": old} for h in (FASTLY, CDN, GCORE, RAW)}))
    check("拿不到就是拿不到", su._get_with_retry(BASE + "a.py", expect_sha=sha), None)


    # --------------------------------------------------------------- 清单版本判定

    print("\n[比本机旧的清单必须拒绝（2026-08-21 静默降级就是这一格）]")
    check("没有版本号的旧清单也要拦（remote=0，本机有版本）", su._is_downgrade(0, 20260821110000), True)
    check("确实更旧", su._is_downgrade(20260820, 20260821), True)
    check("一样新就不算降级", su._is_downgrade(20260821, 20260821), False)
    check("更新的当然放行", su._is_downgrade(20260822, 20260821), False)
    check("本机没有版本号时不拦（全新机器要能装上）", su._is_downgrade(0, 0), False)
    check("本机没有版本号、清单有", su._is_downgrade(20260821, 0), False)

    print("\n[_manifest_version：读不出来算 0，这个 0 是要参与比较的]")
    check("正常", su._manifest_version({"version": 20260821}), 20260821)
    check("字符串数字也认", su._manifest_version({"version": "20260821"}), 20260821)
    check("没有这个字段", su._manifest_version({}), 0)
    check("不是数字", su._manifest_version({"version": "v2"}), 0)

    print("\n[_best_manifest：挑版本号最高的那一份，绕开还没刷新的门]")
    stale, fresh = manifest(20260821, {"a.py": "x"}), manifest(20260908, {"a.py": "y"})
    net = use(Net({FASTLY: {"manifest.json": stale}, CDN: {"manifest.json": stale},
                   GCORE: {"manifest.json": stale}, RAW: {"manifest.json": fresh}}))
    m = su._best_manifest(BASE)
    check("选了最新的那份", su._manifest_version(m or {}), 20260908)
    check("四扇门都问了，不是谁先答用谁", len(net.tried), 4)

    print("\n[有一扇门返回的不是 JSON：跳过它，不许拖垮整轮]")
    net = use(Net({FASTLY: {"manifest.json": b"<html>502</html>"},
                   RAW: {"manifest.json": fresh}}))
    check("照样拿到清单", su._manifest_version(su._best_manifest(BASE) or {}), 20260908)

    print("\n[四扇门全黑：老实说没有，不许瞎编一份]")
    net = use(Net({}))
    check("没有清单", su._best_manifest(BASE), None)
    check("没有清单就不更新", su.check(workdir({"a.py": old}), BASE), [])


    # ------------------------------------------------------------------ 整轮更新

    print("\n[清单更旧：整轮拒绝，磁盘上一个字节都不动]")
    root = workdir({"a.py": old}, code_version=20260908090000)
    net = use(Net({h: {"manifest.json": manifest(20260821110000, {"a.py": sha}),
                       "a.py": body} for h in (FASTLY, CDN, GCORE, RAW)}))
    check("不更新", su.check(root, BASE), [])
    check("文件原封不动", (root / "a.py").read_bytes(), old)
    check("本机版本号没被改回去",
          StateStore(root / "state").get("versions", "code"), "20260908090000")

    print("\n[一切正常：文件落盘、版本号记下、留下给下一个进程播报的记号]")
    root = workdir({"a.py": old}, code_version=20260821110000)
    use(Net({h: {"manifest.json": manifest(20260908090000, {"a.py": sha}), "a.py": body}
             for h in (FASTLY, CDN, GCORE, RAW)}))
    check("更新了 a.py", su.check(root, BASE), ["a.py"])
    check("内容是新的", (root / "a.py").read_bytes(), body)
    check("版本号记下了",
          StateStore(root / "state").get("versions", "code"), "20260908090000")
    note = su.take_announcement(root)
    check("留了播报记号", note and note["files"], ["a.py"])

    print("\n[清单带 ref：清单从分支取，文件从标签取；分支上的旧副本碰不到这一轮]")
    # The branch doors still hold last version's a.py (cdn/gcore on the evening of
    # 2026-09-18); only the tag has the right one.
    class RefNet(Net):
        def get(self, url, timeout=20):
            host = su._netloc(url)
            at_tag = "relay-20260918111328/" in url
            rel = url.split("/relay/", 1)[-1]
            self.tried.append((host, rel, "tag" if at_tag else "main"))
            if rel == "manifest.json":
                return manifest_ref if not at_tag else None
            return self.doors.get(host, {}).get(("tag" if at_tag else "main", rel))
    manifest_ref = json.dumps({"version": 20260918111328, "ref": "relay-20260918111328",
                               "files": {"a.py": sha}}).encode("utf-8")
    root = workdir({"a.py": old}, code_version=20260821110000)
    net = use(RefNet({h: {("main", "a.py"): b"stale copy\n", ("tag", "a.py"): body}
                      for h in (FASTLY, CDN, GCORE, RAW)}))
    check("更新了 a.py", su.check(root, BASE), ["a.py"])
    check("落盘的是标签下的内容", (root / "a.py").read_bytes(), body)
    check("文件只在标签下取过", [t for t in net.tried if t[1] == "a.py"], [(FASTLY, "a.py", "tag")])
    check("清单只在分支上取", {t[2] for t in net.tried if t[1] == "manifest.json"}, {"main"})

    print("\n[内容和清单对不上：一个字节都不许落盘，而且必须留下失败的原因]")
    root = workdir({"a.py": old}, code_version=20260821110000)
    use(Net({h: {"manifest.json": manifest(20260908090000, {"a.py": sha}), "a.py": old}
             for h in (FASTLY, CDN, GCORE, RAW)}))     # 四扇门发的都是旧副本
    check("不更新", su.check(root, BASE), [])
    check("文件原封不动", (root / "a.py").read_bytes(), old)
    check("版本号不许提前记（记了下次开机就不再重试）",
          StateStore(root / "state").get("versions", "code"), "20260821110000")
    f = su.take_failure(root)
    check("失败被记下来了，不是静默的", bool(f), True)
    check("说清了是哪个文件", f and f["files"], ["a.py"])

    print("\n[两个文件只取到一个：两个都不许写——半个更新比不更新更危险]")
    b_body = b"print('b new')\n"
    root = workdir({"a.py": old, "b.py": old}, code_version=20260821110000)
    use(Net({h: {"manifest.json": manifest(20260908090000,
                                           {"a.py": sha, "b.py": su._sha1(b_body)}),
                 "a.py": body}                      # b.py 哪扇门都没有
             for h in (FASTLY, CDN, GCORE, RAW)}))
    check("整轮放弃", su.check(root, BASE), [])
    check("取到的那个也不许落盘", (root / "a.py").read_bytes(), old)
    check("另一个当然也没动", (root / "b.py").read_bytes(), old)
    check("失败报告列出了这一轮本来要改的两个文件",
          sorted((su.take_failure(root) or {}).get("files") or []), ["a.py", "b.py"])

    print("\n[本机已经是新的：什么都不做，也不许把旧的失败报告留在那里吓人]")
    root = workdir({"a.py": body}, code_version=20260821110000)
    su._record_failure(root, "上一轮没成", 1, 2, ["a.py"])
    use(Net({h: {"manifest.json": manifest(20260908090000, {"a.py": sha})}
             for h in (FASTLY, CDN, GCORE, RAW)}))
    check("没有文件要改", su.check(root, BASE), [])
    check("旧的失败报告清掉了", su.take_failure(root), None)
    check("版本号照样记（本机确实就是这一版）",
          StateStore(root / "state").get("versions", "code"), "20260908090000")


    # --------------------------------------------------------------- 清单里的路径

    print("\n[清单是从网上取的：越界路径必须在结构上不可能，而不是靠信任]")
    root = tmpdir()
    for bad in ("../evil.py", "a/../../evil.py", "/etc/passwd", "\\windows\\system32\\x"):
        check(f"拦下 {bad}", su._safe_target(root, bad), None)
    check("正常路径落在 root 里面",
          su._safe_target(root, "ark_relay/core/engine.py"),
          (root / "ark_relay" / "core" / "engine.py").resolve())

    print("\n[越界路径走完整一轮：root 外面不许多出任何东西]")
    root = workdir({"a.py": old}, code_version=20260821110000)
    outside = root.parent / "evil.py"
    use(Net({h: {"manifest.json": manifest(20260908090000,
                                           {"../evil.py": sha, "a.py": sha}),
                 "a.py": body, "../evil.py": body}
             for h in (FASTLY, CDN, GCORE, RAW)}))
    check("正常那个还是更新了", su.check(root, BASE), ["a.py"])
    check("root 外面什么都没写出来", outside.exists(), False)

    print("\n[清单里的新源码文件跟着一轮一起创建：2026-09-15 起，模块拆分不再卡住整个更新]")
    root = workdir({"a.py": body}, code_version=20260821110000)
    use(Net({h: {"manifest.json": manifest(20260908090000,
                                           {"a.py": sha, "brand_new.py": sha, "pkg/deep.py": sha}),
                 "brand_new.py": body, "pkg/deep.py": body} for h in (FASTLY, CDN, GCORE, RAW)}))
    check("新文件算进这一轮", su.check(root, BASE), ["brand_new.py", "pkg/deep.py"])
    check("新文件造出来了，内容对哈希", (root / "brand_new.py").read_bytes(), body)
    check("新目录也建了", (root / "pkg" / "deep.py").read_bytes(), body)

    print("\n[不是源码的新文件还是不许造：门只开给 .py/.md/.txt/.json]")
    root = workdir({"a.py": old}, code_version=20260821110000)
    use(Net({h: {"manifest.json": manifest(20260908090000,
                                           {"a.py": sha, "tool.exe": sha}),
                 "a.py": body, "tool.exe": body} for h in (FASTLY, CDN, GCORE, RAW)}))
    check("整轮放弃", su.check(root, BASE), [])
    check("a.py 也没动", (root / "a.py").read_bytes(), old)
    check("没有造出 exe", (root / "tool.exe").exists(), False)

    print("\n[_wanted_files：这一轮打算改哪些——失败报告要靠它说人话]")
    root = workdir({"same.py": body, "diff.py": old})
    check("哈希一样的不算",
          su._wanted_files(root, {"same.py": sha}), [])
    check("哈希不一样的才算",
          su._wanted_files(root, {"diff.py": sha, "same.py": sha}), ["diff.py"])
    check("本机没有的源码文件算（这一轮会创建它）",
          su._wanted_files(root, {"nope.py": sha}), ["nope.py"])
    check("本机没有的非源码文件不算（它不会被创建）",
          su._wanted_files(root, {"nope.exe": sha}), [])

    # ---- A manifest file this machine does not have ----
    # 2026-09-08: banners.py was split into five files and pushed to main. The old
    # behaviour was to write the edited banners.py, skip the four new modules it
    # imports, stamp the version as up to date, and restart the process - which then
    # died on ModuleNotFoundError, and because the version was already stamped it
    # would never try again. Half an update is far more dangerous than none - so a
    # new source file is staged with the rest (all or nothing), and a new file that
    # is not source still abandons the round.
    import ark_relay.features.selfupdate.selfupdate as SU

    _root = tmpdir()
    (_root / "state").mkdir()          # 失败记录写在 state/ 下，机器上一直有这个目录
    (_root / "old.py").write_bytes(b"x = 1\n")
    _files = {"old.py": SU._sha1(b"x = 2\n"), "a_tool.exe": SU._sha1(b"y = 1\n")}   # sorts before old.py: refused before any download
    _got = SU._stage_files(_root, "https://example.invalid/", _files, None, 7, 6, ["old.py"])
    check("有非源码新文件时整轮放弃", _got, None)
    check("一个字节都没落盘", (_root / "old.py").read_bytes(), b"x = 1\n")
    check("那个文件也没被创建", (_root / "a_tool.exe").exists(), False)
    _fail = (SU.take_failure(_root) or {}).get("reason", "")
    check("留了话说清要人工部署", "部署脚本" in _fail, True)
    check("话里点名了是哪个文件", "a_tool.exe" in _fail, True)


def _part_selfupdate_exit():
    """A self-update restart must stop the old process before the boot stages run.

Real sequence, 2026-09-29 (machine clock, Beijing):
08:45:23 「代码已更新，重启以立即生效」 - the detached restarter is started, but
_stage_selfupdate returned None (a bare return since 25b76dd4 on 09-08), so
service.py carried on; 08:45:51 the dying process launched MAA for the
pre-update; 08:45:57 the stop hard guard force-exited it, with MAA still open;
08:46:00 that MAA logged "current version is latest"; 08:46:14 the new process
launched MAA again, got "Existing instance window activated by a secondary
launch" and no further gui.log line; 08:49:14 「180 秒内没给出更新结论」.

    Formerly test_selfupdate_exit.py.
    """
    import ast
    import types

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))


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
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                 "win32com", "win32com.client"):
        sys.modules.setdefault(name, _Stub(name))

    import boot_stages
    from ark_relay.features.preupdate import preupdate
    from ark_relay.features.selfupdate import selfupdate


    class _Log:
        def info(self, *a, **k): pass
        def exception(self, *a, **k): pass
        warning = info


    def test_selfupdate_returns_true():
        print("自更新拉到新代码：返回 True，让 service.py 立刻退出")
        real_check, real_popen = selfupdate.check, boot_stages.subprocess.Popen
        spawned = []
        selfupdate.check = lambda here: ["ark_relay/features/report/report.py"]
        boot_stages.subprocess.Popen = lambda *a, **k: spawned.append(a)
        for flag in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS"):   # Windows-only
            if not hasattr(boot_stages.subprocess, flag):
                setattr(boot_stages.subprocess, flag, 0)
        try:
            check("有更新时返回", boot_stages._stage_selfupdate(_Log()), True)
            check("起了重启器", len(spawned), 1)
            selfupdate.check = lambda here: []
            check("没更新时返回", boot_stages._stage_selfupdate(_Log()), False)
        finally:
            selfupdate.check, boot_stages.subprocess.Popen = real_check, real_popen


    def test_no_bare_return_in_bool_functions():
        print("声明返回 bool 的函数里没有裸 return（None 会被当成 False）")
        bad = []
        for p in sorted(RELAY.rglob("*.py")):
            if "tests" in p.parts:
                continue
            for f in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if (isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and isinstance(f.returns, ast.Name) and f.returns.id == "bool"):
                    bad += [f"{p.relative_to(RELAY)}:{n.lineno} {f.name}"
                            for n in ast.walk(f)
                            if isinstance(n, ast.Return) and n.value is None]
        check("裸 return", bad, [])


    def test_preupdate_skipped_while_stopping():
        print("服务正在停止：不做预更新，不起任何程序")
        asked = []
        real = boot_stages._stop_requested, preupdate.wanted_today
        boot_stages._stop_requested = lambda: True
        preupdate.wanted_today = lambda *a, **k: asked.append(1) or False
        try:
            boot_stages._stage_preupdate(types.SimpleNamespace(automas_dir=None), None, _Log())
            check("停止时连「今天要不要做」都不问", asked, [])
        finally:
            boot_stages._stop_requested, preupdate.wanted_today = real


    def test_preupdate_automas_without_okww():
        print("清单-1108 A-07：今天只剩 MAA / MaaEnd 的队列：AUTO-MAS 的更新照查，OK-WW 不动")
        ran = []
        names = ("_stop_requested", "await_backend", "_once_more", "_preupdate_okww")
        real = [getattr(boot_stages, n) for n in names] + [preupdate.wanted_today, preupdate.should_run, preupdate.mark_run]
        boot_stages._stop_requested = lambda: False
        boot_stages.await_backend = lambda log, why, cfg: (True, 0)
        boot_stages._once_more = lambda cfg, log, what, budget, problems, fn: ran.append(what) or None
        boot_stages._preupdate_okww = lambda *a: ran.append("OK-WW")
        preupdate.wanted_today = lambda d, now=None, kind="OK-WW": kind == "MAA"
        preupdate.should_run = lambda *a: True
        preupdate.mark_run = lambda *a, **k: ran.append("marked")
        try:
            boot_stages._stage_preupdate(types.SimpleNamespace(automas_dir=None, state_dir=None), None, _Log())
            check("AUTO-MAS 查了、OK-WW 没动、今天记为做过", ran, ["AUTO-MAS", "marked"])
        finally:
            for n, v in zip(names, real[:len(names)], strict=True):
                setattr(boot_stages, n, v)
            preupdate.wanted_today, preupdate.should_run, preupdate.mark_run = real[len(names):]


    if __name__ == "__main__":
        test_selfupdate_returns_true()
        test_no_bare_return_in_bool_functions()
        test_preupdate_skipped_while_stopping()
        test_preupdate_automas_without_okww()
        print("all checks passed" if not fails else f"FAILED: {fails}")
        raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_selfupdate_atomic_sha256, _part_selfupdate_cos, _part_selfupdate_doors, _part_selfupdate_exit]))
