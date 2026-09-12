#!/usr/bin/env python3
"""Fetch one run's evidence files back to the Mac.

    evidence_pull.py <index.jsonl> <run-id fragment> <dest root>

Reads the mirrored index the relay wrote (evidence.sh keeps it), takes the
newest entry matching the fragment, and fetches its files:

* store "cos"   - signed GET against Tencent COS (COS_SECRET_ID/KEY/BUCKET/REGION
                  in ~/.config/ark/push.env), same signature recipe as the relay's
                  `evidence.Cos`.
* store "wecom" - `media/get` by media id with the WeCom app credentials in
                  push.env; pieces named `<file>.p01of03` are joined back into
                  `<file>`. WeCom keeps media three days; after that the entry's
                  `expires` says so and the files live only in his WeCom chat.
* store "gofile" - nothing to fetch by script; prints the page.

Files land in <dest root>/<run_id with / as _>/.
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


def env(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def cos_get(e: dict, u: dict, dest: Path) -> None:
    sid, skey = e["COS_SECRET_ID"], e["COS_SECRET_KEY"]
    bucket, region = e["COS_BUCKET"], e["COS_REGION"]
    host = f"{bucket}.cos.{region}.myqcloud.com"
    key = u["key"]
    start = int(time.time()) - 60
    kt = f"{start};{start + 3600}"
    sign_key = hmac.new(skey.encode(), kt.encode(), hashlib.sha1).hexdigest()
    path = "/" + urllib.parse.quote(key, safe="/")
    http_string = f"get\n{path}\n\nhost={host}\n"
    sts = f"sha1\n{kt}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
    sig = hmac.new(sign_key.encode(), sts.encode(), hashlib.sha1).hexdigest()
    auth = (f"q-sign-algorithm=sha1&q-ak={sid}&q-sign-time={kt}&q-key-time={kt}"
            f"&q-header-list=host&q-url-param-list=&q-signature={sig}")
    req = urllib.request.Request(f"https://{host}{path}", headers={"Authorization": auth})
    with urllib.request.urlopen(req, timeout=600) as r:
        (dest / u["name"]).write_bytes(r.read())
    print(f"  ✓ {u['name']}（腾讯云）")


def wecom_token(e: dict) -> str:
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={e['WECOM_CORPID']}&corpsecret={e['WECOM_SECRET']}"
    with urllib.request.urlopen(url, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("errcode") != 0:
        raise SystemExit(f"企业微信 gettoken 失败：{d}")
    return d["access_token"]


def wecom_get(e: dict, u: dict, dest: Path, token: str) -> None:
    parts = []
    for piece in u.get("pieces") or []:
        url = f"https://qyapi.weixin.qq.com/cgi-bin/media/get?access_token={token}&media_id={piece['media_id']}"
        with urllib.request.urlopen(url, timeout=600) as r:
            data = r.read()
        if data[:1] == b"{":
            d = json.loads(data.decode("utf-8", "replace"))
            raise SystemExit(f"  ✗ {piece['name']}：企业微信没给文件（{d.get('errcode')} {d.get('errmsg')}）"
                             f"——媒体只保留 3 天，这一趟登记的到期时间是 {u.get('expires')}")
        parts.append(data)
    (dest / u["name"]).write_bytes(b"".join(parts))
    print(f"  ✓ {u['name']}（企业微信，{len(parts)} 段拼回）")


def main() -> int:
    idx, frag, root = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    entries = [json.loads(ln) for ln in idx.read_text(encoding="utf-8").splitlines() if ln.strip()]
    hit = [e for e in entries if frag in str(e.get("run_id", ""))]
    if not hit:
        print(f"索引里没有 {frag}", file=sys.stderr)
        return 1
    e = hit[-1]
    dest = root / str(e["run_id"]).replace("/", "_")
    dest.mkdir(parents=True, exist_ok=True)
    creds = env(Path(os.path.expanduser("~/.config/ark/push.env")))
    store = e.get("store") or "gofile"
    print(f"{e['run_id']}  {store}  → {dest}")
    if store == "gofile":
        print(f"  gofile 只能人点网页下载：{e.get('page')}")
        return 0
    token = wecom_token(creds) if store == "wecom" else ""
    for u in e.get("uploaded") or []:
        if store == "cos":
            cos_get(creds, u, dest)
        else:
            wecom_get(creds, u, dest, token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
