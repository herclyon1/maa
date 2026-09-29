"""The COS bundle must hold the bytes the manifest names.

deploy-relay.sh emptied RELEASE-NOTES.md before calling publish-cos.py, so the
bundle carried an empty file under the filled file's hash (v20260929013233 on
COS: 0 bytes). The machine drops the whole bundle when one file it needs is
off (selfupdate._cos_bundle): harmless while it gets the code over ssh, fatal
for a machine that was off and has to fetch it.
"""
import hashlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
