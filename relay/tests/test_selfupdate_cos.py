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
"""
import hashlib
import io
import json
import sys
import threading
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import selfupdate as su
from ark_relay.statestore import StateStore
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}（要 {want!r}）" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


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
t0 = time.time(); updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"); dt = time.time() - t0
check("12 个文件全更新", len(updated), 12)
check("确实并发了（峰值 >1）", net.peak > 1)
check("12 × 50 ms 串行要 0.6 秒，并发后明显更快", dt < 0.45)
missing_one = dict(many); missing_one.pop("ark_relay/m7.py")
net = SlowNet({"fastly.jsdelivr.net": {"manifest.json": man, **missing_one}}); su._get_once = net.get; su._last_good = ""
root = workdir({k: b"old\n" for k in many}, 20260917000000)
updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
check("一个文件拿不到 → 一个都不落盘", (updated, (root / "ark_relay/m0.py").read_bytes()), ([], b"old\n"))

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("all checks passed")
