#!/usr/bin/env python3
"""Fetch the phone page's diagnostic records off COS and keep them on the Mac.

    scripts/mac/diag-pull.py           # list what is in the bucket, download the new ones
    scripts/mac/diag-pull.py --list    # only list, download nothing

The records are what `web/view.js` writes when he taps 诊断记录 on the phone: one
JSON object per tap, PUT with no credentials at all into `diag/` of the
diagnostics bucket (COS_DIAG_BUCKET in ~/.config/ark/push.env, built by
`cos-setup.py --diag`). Nobody can read or list that bucket anonymously - this
script is the reader, and it signs with the COS key the same way
relay/ark_relay/evidence.py does.

**The bucket deletes every object 14 days after it is written** (one lifecycle
rule over the whole bucket). So a record that is not pulled within 14 days is
gone for good; files that land here stay forever.

Files land in ~/Claude/ark-diag/<the object key under diag/>. A key already on
disk is never fetched twice.
"""
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay"))
from ark_relay.evidence import Cos  # noqa: E402

PUSH_ENV = Path(os.path.expanduser("~/.config/ark/push.env"))
DEST = Path(os.path.expanduser("~/Claude/ark-diag"))
NS = "{http://www.qcloud.com/document/product/436/7751}"


def env(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def get(cos: Cos, key: str, params: str = "") -> tuple[int, bytes]:
    url = f"https://{cos.host}/{urllib.parse.quote(key, safe='/')}" + (f"?{params}" if params else "")
    req = urllib.request.Request(url, method="GET", headers={"Authorization": cos.authorization("GET", key)})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def listing(cos: Cos) -> list:
    """Every object under diag/, following the truncation marker."""
    out, marker = [], ""
    while True:
        params = "prefix=diag/&max-keys=1000" + (f"&marker={urllib.parse.quote(marker)}" if marker else "")
        status, body = get(cos, "", params)
        if status != 200:
            print(f"列桶失败 {status}：{body[:300].decode('utf-8', 'replace')}", file=sys.stderr)
            raise SystemExit(1)
        root = ET.fromstring(body)
        # COS answers GET Bucket with a namespace on some accounts and without it on
        # others; strip whatever the tag carries instead of guessing (measured 09-23).
        def text(node: ET.Element, name: str) -> str:
            for child in node:
                if child.tag.rsplit("}", 1)[-1] == name:
                    return child.text or ""
            return ""
        for node in root:
            if node.tag.rsplit("}", 1)[-1] != "Contents":
                continue
            out.append((text(node, "Key"), int(text(node, "Size") or 0), text(node, "LastModified")))
        if text(root, "IsTruncated") != "true":
            return out
        marker = text(root, "NextMarker") or (out[-1][0] if out else "")
        if not marker:
            return out


def main() -> int:
    e = env(PUSH_ENV)
    sid, skey = e.get("COS_SECRET_ID", ""), e.get("COS_SECRET_KEY", "")
    bucket, region = e.get("COS_DIAG_BUCKET", ""), e.get("COS_REGION", "ap-shanghai")
    if not (sid and skey and bucket):
        print("push.env 里缺 COS_SECRET_ID / COS_SECRET_KEY / COS_DIAG_BUCKET；"
              "先跑 scripts/mac/cos-setup.py --diag。", file=sys.stderr)
        return 2
    cos = Cos(sid, skey, bucket, region)
    items = listing(cos)
    if not items:
        print(f"{bucket} 的 diag/ 下现在一条记录都没有。")
        return 0
    got = new = 0
    for key, size, when in sorted(items, key=lambda i: i[2]):
        dest = DEST / key[len("diag/"):]
        mark = "已在本机" if dest.exists() else "新"
        print(f"{when[:19]}  {size:>8} 字节  {key}  {mark}")
        if dest.exists() or "--list" in sys.argv:
            continue
        status, body = get(cos, key)
        if status != 200:
            print(f"  取回失败 {status}：{body[:200].decode('utf-8', 'replace')}", file=sys.stderr)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        got += len(body)
        new += 1
    if "--list" not in sys.argv:
        print(f"新取回 {new} 条、{got} 字节，存在 {DEST}/。桶里的原件写入满 14 天就会被自动删掉。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
