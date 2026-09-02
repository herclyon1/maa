"""四个程序的预更新通知统一成「程序 已更新：旧 → 新」。

2026-08-30 实证：MaaEnd 08:46:23 启动、08:46:33 就「刚更新完成」，通知只有
「已更新：v2.27.0-beta.1」——旧版本号靠日志正则没捞到。用户 2026-09-01
要求四个程序样式统一，都带老版本号 → 新版本号。
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import preupdate  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

print("[_span：旧 → 新，缺旧版明说]")
check("正常", preupdate._span("v1", "v2"), "v1 → v2")
check("同版只报一次", preupdate._span("v2", "v2"), "v2")
check("旧版没读到要明说", preupdate._span("", "v2"), "（旧版本没读到）→ v2")
check("旧名字仍可用", preupdate._maaend_span("v1", "v2"), "v1 → v2")

TMP = Path(tempfile.mkdtemp())
print("[MaaEnd：从 interface.json 读版本，不依赖日志时机]")
(TMP / "interface.json").write_text(json.dumps({"version": "v2.26.0-beta.9"}), encoding="utf-8")
check("读到", preupdate._maaend_file_version(TMP), "v2.26.0-beta.9")
check("没文件→空串", preupdate._maaend_file_version(TMP / "nope"), "")
(TMP / "bad").mkdir(); (TMP / "bad" / "interface.json").write_text("{", encoding="utf-8")
check("坏 JSON→空串", preupdate._maaend_file_version(TMP / "bad"), "")

print("[MAA：待装包名里的目标版本]")
maa = TMP / "maa"; maa.mkdir()
check("没包→空串", preupdate._maa_pending_version(maa), "")
(maa / "MirrorChyanAppv6.17.0-beta.8.zip").write_bytes(b"")
check("从包名读", preupdate._maa_pending_version(maa), "v6.17.0-beta.8")
(maa / "MirrorChyanAppv6.17.0-beta.9.zip.temp").write_bytes(b"")
check("下载中的 .temp 不算", preupdate._maa_pending_version(maa), "v6.17.0-beta.8")

print("[四段文案同一种形状]")
import re
shape = re.compile(r"^(MAA|MaaEnd|AUTO-MAS|OK-WW) (已|有)更新：\S+ → \S+")
for msg in [f"MAA 已更新：{preupdate._span('v6.17.0-beta.7', 'v6.17.0-beta.8')}",
            f"MaaEnd 已更新：{preupdate._span('v2.26.0', 'v2.27.0-beta.1')}",
            f"AUTO-MAS 有更新：{preupdate._span('v5.5.0-beta.1', 'v5.5.0')}（安装中，装完自动重启）",
            f"OK-WW 已更新：{preupdate._span('v3.6.6-beta.1', 'v3.6.6')}"]:
    check(msg, bool(shape.match(msg)), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
