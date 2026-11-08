"""publish-cos.py: its arguments, its notes.

One part per former file, each run on its own (tests/_parts.py): test_publish_cos_args.py, test_publish_cos_notes.py.
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


def _part_publish_cos_args():
    """publish-cos.py: only a bare call publishes.

2026-10-10 18:04 `publish-cos.py --help` was run to read the usage; the script took
every argument but --check as "publish" and put a branch on COS as the machine's
next version.

    Formerly test_publish_cos_args.py.
    """
    import importlib.util

    ROOT = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("publish_cos", ROOT / "scripts/mac/publish-cos.py")
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)


    reached = []


    class _Stop(Exception):
        pass


    def _client():
        reached.append(True)
        raise _Stop


    pc._client = _client
    for args, rc in ((["--help"], 0), (["-h"], 0), (["--dry-run"], 2), (["--check", "x"], 2)):
        reached.clear()
        check(f"{' '.join(args)}：不连 COS、退出码 {rc}", (pc.main(list(args)), reached), (rc, []))
    for args in ([], ["--check"]):
        reached.clear()
        try:
            pc.main(list(args))
        except _Stop:
            pass
        check(f"{' '.join(args) or '不带参数'}：照常连 COS", reached, [True])

    print()
    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_publish_cos_notes():
    """The COS bundle must hold the bytes the manifest names.

deploy-relay.sh emptied RELEASE-NOTES.md before calling publish-cos.py, so the
bundle carried an empty file under the filled file's hash (v20260929013233 on
COS: 0 bytes). The machine drops the whole bundle when one file it needs is
off (selfupdate._cos_bundle): harmless while it gets the code over ssh, fatal
for a machine that was off and has to fetch it.

    Formerly test_publish_cos_notes.py.
    """
    import hashlib
    import importlib.util

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay"))


    spec = importlib.util.spec_from_file_location("publish_cos", ROOT / "scripts" / "mac" / "publish-cos.py")
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)

    print("[发之前逐个核哈希]")
    d = tmpdir()
    notes = "这次改了什么\n".encode("utf-8")
    (d / "RELEASE-NOTES.md").write_bytes(notes)
    (d / "a.py").write_bytes(b"x = 1\n")
    manifest = {"files": {"RELEASE-NOTES.md": hashlib.sha1(notes).hexdigest(),
                          "a.py": hashlib.sha1(b"x = 1\n").hexdigest()}}
    pc.RELAY = d
    check("文件和清单一致：放行", pc.stale_files(manifest), [])
    (d / "RELEASE-NOTES.md").write_bytes(b"")
    check("说明被清空：拦下并点名", pc.stale_files(manifest), ["RELEASE-NOTES.md"])
    (d / "a.py").unlink()
    check("文件没了也拦", pc.stale_files(manifest), ["RELEASE-NOTES.md", "a.py"])

    print("\n[部署脚本：先发 COS，再清空说明]")
    sh = (ROOT / "scripts" / "mac" / "deploy-relay.sh").read_text(encoding="utf-8")
    pub = sh.index('python3 "$HERE/../scripts/mac/publish-cos.py"')
    clear = sh.index('\n: > "$NOTES"\n')          # the command, not a comment quoting it
    check("发 COS 在清空之前", pub < clear, True)
    check("只发一次", sh.count('python3 "$HERE/../scripts/mac/publish-cos.py"'), 1)

    print("\n[上传失败重试：10-05 两次部署都被链路打断（SSL EOF、HTTP 400），手动重发都成]")
    import io as _io
    import ssl
    import urllib.error


    class FakeCos:
        prefix, host = "relay", "bucket.cos.example"

        def __init__(self):
            self.signed = 0

        def authorization(self, method, key):
            self.signed += 1
            return f"sig{self.signed}"


    tries, slept = [], []
    real_urlopen, real_sleep = pc.urllib.request.urlopen, pc.time.sleep


    class Ok:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""


    def flaky(outcomes):
        def urlopen(req, timeout=0):
            tries.append(req.get_header("Authorization"))
            o = outcomes.pop(0)
            if o == "ok":
                return Ok()
            raise o
        return urlopen


    pc.time.sleep = slept.append
    try:
        eof = urllib.error.URLError(ssl.SSLEOFError(8, "EOF occurred in violation of protocol (_ssl.c:1129)"))
        bad = urllib.error.HTTPError("u", 400, "Bad Request", {}, _io.BytesIO(b"<Code>RequestTimeout</Code>"))
        pc.urllib.request.urlopen = flaky([eof, bad, "ok"])
        cos = FakeCos()
        pc._put(cos, "1/bundle.zip", b"x", "application/zip")
        check("SSL EOF、400 之后第三次成了", len(tries), 3)
        check("每次重新签名", tries, ["sig1", "sig2", "sig3"])
        check("中间等了 5、15 秒", slept, [5, 15])
        tries[:], slept[:] = [], []
        pc.urllib.request.urlopen = flaky([eof, eof, eof, eof])
        try:
            pc._put(FakeCos(), "1/bundle.zip", b"x", "application/zip")
            raised = ""
        except RuntimeError as exc:
            raised = str(exc)
        check("四次都不成：报错带原因", ("上传失败" in raised and "EOF" in raised, len(tries)), (True, 4))
        tries[:] = []
        denied = urllib.error.HTTPError("u", 403, "Forbidden", {}, _io.BytesIO(b"<Code>AccessDenied</Code>"))
        pc.urllib.request.urlopen = flaky([denied])
        try:
            pc._put(FakeCos(), "1/bundle.zip", b"x", "application/zip")
            raised = ""
        except RuntimeError as exc:
            raised = str(exc)
        check("403 不重试、原样报出", ("AccessDenied" in raised, len(tries)), (True, 1))
    finally:
        pc.urllib.request.urlopen, pc.time.sleep = real_urlopen, real_sleep


if __name__ == "__main__":
    sys.exit(run_parts([_part_publish_cos_args, _part_publish_cos_notes]))
