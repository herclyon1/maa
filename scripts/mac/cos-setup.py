#!/usr/bin/env python3
"""One-shot setup of the Tencent Cloud COS bucket the relay ships evidence to.

    scripts/mac/cos-setup.py              # create + verify + configure both ends
    scripts/mac/cos-setup.py --check      # only verify the bucket answers a signed PUT/GET
    scripts/mac/cos-setup.py --diag       # the SEPARATE diagnostics bucket (see below)
    scripts/mac/cos-setup.py --diag --check   # only re-measure that bucket, change nothing

What the account owner has to have done first (nobody else can): a Tencent Cloud
account with 实名认证 and a payment method, and an API key pair from
https://console.cloud.tencent.com/cam/capi. Put those two values in
~/.config/ark/push.env as COS_SECRET_ID / COS_SECRET_KEY (never in chat), plus
COS_APPID (the number after the dash in any bucket name / the account page). The
rest is this script:

1. picks the bucket name `ark-evidence-<appid>` in COS_REGION (default ap-shanghai,
   closest to the user in Tokyo among the mainland regions the machine reaches);
2. creates it (private ACL) if it is not there, sets a lifecycle rule that deletes
   objects after 90 days so the bill stays at cents;
3. PUTs, GETs and DELETEs a probe object to prove the key works;
4. writes COS_* into ~/.config/ark/push.env (for evidence.sh pull) and into the
   machine's C:\\ProgramData\\ark-relay\\.env, then restarts the relay service so
   evidence.pick_uploader switches to COS on its next bundle.

`--diag` builds a second, separate bucket `ark-diag-<appid>` that the phone page
(https://herclyon1.github.io) PUTs diagnostic records into with NO credentials at
all. It is a different bucket from the evidence one on purpose: the evidence
bucket is the first door of the machine's self-update (relay/ark_relay/selfupdate.py
:117 `COS_PREFIX = "relay"`, :129-134 the same COS_* client), so nothing anonymous
may be allowed to write there. The diagnostics bucket carries three settings and
nothing else:

* lifecycle - one rule over the whole bucket, objects deleted after 14 days;
* policy    - anonymous identity (`qcs::cam::anyone:anyone`) may call
              `name/cos:PutObject` and only under the `diag/` prefix. No read, no
              list, no delete, no form upload (`cos:PostObject` is NOT granted -
              a browser <form> upload would be refused; the page must PUT);
* cors      - only https://herclyon1.github.io, only PUT. OPTIONS is not an
              AllowedMethod value (the enum is "PUT、GET、POST、DELETE、HEAD",
              https://cloud.tencent.com/document/product/436/8279); COS answers
              the preflight itself once a rule matches, which `--diag --check`
              measures.

Nothing else is configured on it: no hotlink protection, no alarms, no rate cap,
no content-length cap (the owner's 2026-09-23 instruction - the only threat we
defend against is tampering with what the game machine installs, and that lives
in the other bucket).

Signature recipe shared with relay/ark_relay/evidence.py (`Cos.authorization`).
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay"))
from ark_relay.evidence import Cos  # noqa: E402

PUSH_ENV = Path(os.path.expanduser("~/.config/ark/push.env"))
LIFECYCLE = """<LifecycleConfiguration>
  <Rule><ID>expire-90d</ID><Filter><Prefix></Prefix></Filter><Status>Enabled</Status>
    <Expiration><Days>90</Days></Expiration></Rule>
</LifecycleConfiguration>"""


DIAG_LIFECYCLE = """<LifecycleConfiguration>
  <Rule><ID>diag-expire-14d</ID><Filter><Prefix></Prefix></Filter><Status>Enabled</Status>
    <Expiration><Days>14</Days></Expiration></Rule>
</LifecycleConfiguration>"""

DIAG_CORS = """<CORSConfiguration>
  <CORSRule>
    <ID>diag-from-pages</ID>
    <AllowedOrigin>https://herclyon1.github.io</AllowedOrigin>
    <AllowedMethod>PUT</AllowedMethod>
    <AllowedHeader>*</AllowedHeader>
    <ExposeHeader>ETag</ExposeHeader>
    <MaxAgeSeconds>600</MaxAgeSeconds>
  </CORSRule>
</CORSConfiguration>"""

DIAG_ORIGIN = "https://herclyon1.github.io"
DIAG_PREFIX = "diag/"


def diag_policy(appid: str, region: str, bucket: str) -> str:
    """Anonymous PutObject, that prefix only. Shape per the official examples:
    https://cloud.tencent.com/document/product/436/18031 (`qcs::cam::anyone:anyone`)
    and .../436/31923 (`name/cos:PutObject`, `.../<bucket>/doc/*` for one prefix)."""
    return json.dumps({
        "statement": [{
            "principal": {"qcs": ["qcs::cam::anyone:anyone"]},
            "effect": "allow",
            "action": ["name/cos:PutObject"],
            "resource": [f"qcs::cos:{region}:uid/{appid}:{bucket}/{DIAG_PREFIX}*"],
        }],
        "version": "2.0",
    }, indent=2)


def env(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def request(cos: Cos, method: str, key: str, body: bytes = b"", params: str = "",
            ctype: str = "") -> tuple[int, bytes]:
    import base64  # noqa: PLC0415
    import hashlib  # noqa: PLC0415
    url = f"https://{cos.host}/{urllib.parse.quote(key, safe='/')}" + (f"?{params}" if params else "")
    headers = {"Authorization": cos.authorization(method, key),
               "Content-Type": ctype or ("application/xml" if params else "application/octet-stream")}
    if params:
        # bucket sub-resource writes (lifecycle, ...) require Content-MD5 (measured 2026-09-12)
        headers["Content-MD5"] = base64.b64encode(hashlib.md5(body).digest()).decode()
    req = urllib.request.Request(url, data=body if body else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def anon(host: str, method: str, key: str, body: bytes = b"", params: str = "",
         headers: "dict | None" = None) -> tuple[int, dict, bytes]:
    """The same request a stranger's browser would send: no Authorization header."""
    url = f"https://{host}/{urllib.parse.quote(key, safe='/')}" + (f"?{params}" if params else "")
    req = urllib.request.Request(url, data=body or None, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def diag_measure(cos: Cos) -> int:
    """Six anonymous measurements against the live bucket; prints every reading."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    inside, outside = f"{DIAG_PREFIX}_probe-{stamp}.json", f"_probe-outside-{stamp}.json"
    probe = b'{"probe":"anonymous put"}'
    pre = {"Origin": DIAG_ORIGIN, "Access-Control-Request-Method": "PUT"}
    rows = []
    s, h, b = anon(cos.host, "PUT", inside, probe, headers={"Content-Type": "application/json",
                                                            "Origin": DIAG_ORIGIN})
    rows.append(("匿名 PUT 到 diag/（要成）", s, 200, h.get("ETag", "") + " allow-origin=" + h.get("Access-Control-Allow-Origin", "无")))
    s2, _, b2 = anon(cos.host, "PUT", outside, probe)
    rows.append(("匿名 PUT 到 diag/ 之外（要 403）", s2, 403, code_of(b2)))
    s3, _, b3 = anon(cos.host, "GET", inside)
    rows.append(("匿名 GET 刚写的那条（要 403）", s3, 403, code_of(b3)))
    s4, _, b4 = anon(cos.host, "GET", "", params="prefix=diag/&max-keys=5")
    rows.append(("匿名 List 整个桶（要 403）", s4, 403, code_of(b4)))
    s5, h5, _ = anon(cos.host, "OPTIONS", inside, headers=pre)
    rows.append(("预检 OPTIONS · 我们的来源（要 200）", s5, 200,
                 "allow-origin=" + h5.get("Access-Control-Allow-Origin", "无")
                 + " allow-methods=" + h5.get("Access-Control-Allow-Methods", "无")
                 + " max-age=" + h5.get("Access-Control-Max-Age", "无")))
    s6, _, b6 = anon(cos.host, "OPTIONS", inside, headers={**pre, "Origin": "https://example.com"})
    rows.append(("预检 OPTIONS · 别的来源（要 403）", s6, 403, code_of(b6)))
    bad = 0
    for name, got, want, extra in rows:
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'✓' if ok else '✗'} {name}：{got} {extra}".rstrip())
    if s == 200:
        d, _ = request(cos, "DELETE", inside)
        print(f"  （签名 DELETE 清掉这条探针：{d}）")
    return bad


def code_of(body: bytes) -> str:
    text = body.decode("utf-8", "replace")
    start, end = text.find("<Code>"), text.find("</Code>")
    return text[start + 6:end] if 0 <= start < end else text[:80].replace("\n", " ")


def diag(sid: str, skey: str, appid: str, region: str, e: dict, check_only: bool) -> int:
    bucket = e.get("COS_DIAG_BUCKET") or f"ark-diag-{appid}"
    if bucket == e.get("COS_BUCKET"):
        print("诊断桶不能和证据桶是同一个（证据桶是游戏机自更新的第一道门）。", file=sys.stderr)
        return 1
    cos = Cos(sid, skey, bucket, region)
    print(f"诊断桶：{bucket}（{region}）")
    if not check_only:
        status, body = request(cos, "HEAD", "")
        if status == 404:
            status, body = request(cos, "PUT", "")
            print("建桶：", status, body[:200].decode("utf-8", "replace"))
            if status not in (200, 201):
                return 1
        elif status != 200:
            print("桶查不到也建不了：", status, body[:300].decode("utf-8", "replace"))
            return 1
        else:
            print("建桶：桶已经在了")
        for name, params, payload, ctype in (
                ("生命周期（全桶一条，14 天）", "lifecycle", DIAG_LIFECYCLE.encode(), ""),
                ("桶策略（匿名只能 PUT diag/）", "policy", diag_policy(appid, region, bucket).encode(),
                 "application/json"),
                ("CORS（只放手机页那个来源的 PUT）", "cors", DIAG_CORS.encode(), ""),
        ):
            status, body = request(cos, "PUT", "", payload, params=params, ctype=ctype)
            # PUT Bucket policy answers 204 No Content on success (官方响应示例
            # 「HTTP/1.1 204 No Content」, https://cloud.tencent.com/document/product/436/8282),
            # lifecycle and cors answer 200 (measured 2026-09-23).
            ok = status in (200, 204)
            print(f"{name}：", status, "已设" if ok else body[:300].decode("utf-8", "replace"))
            if not ok:
                return 1
    for params in ("lifecycle", "policy", "cors"):
        status, body = request(cos, "GET", "", params=params)
        print(f"回读 ?{params}：{status}")
        print("  " + body.decode("utf-8", "replace").strip().replace("\n", "\n  "))
    print("无凭据实测：")
    bad = diag_measure(cos)
    if not check_only:
        write_env({"COS_DIAG_BUCKET": bucket})
        print(f"push.env 已写 COS_DIAG_BUCKET={bucket}。")
    if bad:
        print(f"{bad} 条实测不是预期值，先修这个。", file=sys.stderr)
    return 1 if bad else 0


def write_env(lines: dict) -> None:
    text = PUSH_ENV.read_text(encoding="utf-8") if PUSH_ENV.exists() else ""
    for k, v in lines.items():
        if f"{k}=" not in text:
            text += f"\n{k}={v}"
    PUSH_ENV.write_text(text.rstrip("\n") + "\n", encoding="utf-8")


def main() -> int:
    e = env(PUSH_ENV)
    sid, skey, appid = e.get("COS_SECRET_ID", ""), e.get("COS_SECRET_KEY", ""), e.get("COS_APPID", "")
    region = e.get("COS_REGION", "ap-shanghai")
    if not (sid and skey and appid):
        print("push.env 里还没有 COS_SECRET_ID / COS_SECRET_KEY / COS_APPID——这三样只有账号主人能拿到：", file=sys.stderr)
        print("  https://console.cloud.tencent.com/cam/capi 新建密钥，APPID 在右上角账号信息里。", file=sys.stderr)
        return 2
    if "--diag" in sys.argv:
        return diag(sid, skey, appid, region, e, check_only="--check" in sys.argv)
    bucket = e.get("COS_BUCKET") or f"ark-evidence-{appid}"
    cos = Cos(sid, skey, bucket, region)
    check_only = "--check" in sys.argv
    if not check_only:
        status, body = request(cos, "HEAD", "")
        if status == 404:
            status, body = request(cos, "PUT", "")
            print("建桶：", status, body[:200].decode("utf-8", "replace"))
            if status not in (200, 201):
                return 1
        elif status != 200:
            print("桶查不到也建不了：", status, body[:300].decode("utf-8", "replace"))
            return 1
        status, body = request(cos, "PUT", "", LIFECYCLE.encode(), params="lifecycle")
        print("90 天自动删除规则：", status, body[:200].decode("utf-8", "replace") if status != 200 else "已设")
    status, _ = request(cos, "PUT", "_probe.txt", b"ark evidence probe")
    status2, got = request(cos, "GET", "_probe.txt")
    status3, _ = request(cos, "DELETE", "_probe.txt")
    print(f"探针：写 {status}，读 {status2}（{got[:20]!r}），删 {status3}")
    if not (status == 200 and status2 == 200 and got == b"ark evidence probe"):
        print("密钥或桶不对，先修这个。", file=sys.stderr)
        return 1
    if check_only:
        return 0
    lines = {"COS_SECRET_ID": sid, "COS_SECRET_KEY": skey, "COS_BUCKET": bucket, "COS_REGION": region}
    write_env(lines)
    print("Mac 端 push.env 已写好。")
    add = "; ".join(f'Add-Content "C:\\ProgramData\\ark-relay\\.env" "{k}={v}"' for k, v in lines.items())
    ps = (f'$t = Get-Content "C:\\ProgramData\\ark-relay\\.env" -Raw; if ($t -notmatch "COS_BUCKET=") {{ {add} }}; '
          'net stop ark-relay | Out-Null; net start ark-relay | Out-Null; "relay restarted"')
    r = subprocess.run([str(ROOT / "scripts/mac/winps.sh"), ps], capture_output=True, text=True)
    print(r.stdout.strip()[-200:] or r.stderr.strip()[-200:])
    print("机器端 .env 已写、中继已重启；下一份证据包走 COS。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
