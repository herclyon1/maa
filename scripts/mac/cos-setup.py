#!/usr/bin/env python3
"""One-shot setup of the Tencent Cloud COS bucket the relay ships evidence to.

    scripts/mac/cos-setup.py            # create + verify + configure both ends
    scripts/mac/cos-setup.py --check    # only verify the bucket answers a signed PUT/GET

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

Signature recipe shared with relay/ark_relay/evidence.py (`Cos.authorization`).
"""
import os
import subprocess
import sys
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


def env(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def request(cos: Cos, method: str, key: str, body: bytes = b"", params: str = "") -> tuple[int, bytes]:
    url = f"https://{cos.host}/{urllib.parse.quote(key, safe='/')}" + (f"?{params}" if params else "")
    req = urllib.request.Request(url, data=body if body else None, method=method,
                                 headers={"Authorization": cos.authorization(method, key),
                                          "Content-Type": "application/xml" if params else "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main() -> int:
    e = env(PUSH_ENV)
    sid, skey, appid = e.get("COS_SECRET_ID", ""), e.get("COS_SECRET_KEY", ""), e.get("COS_APPID", "")
    region = e.get("COS_REGION", "ap-shanghai")
    if not (sid and skey and appid):
        print("push.env 里还没有 COS_SECRET_ID / COS_SECRET_KEY / COS_APPID——这三样只有账号主人能拿到：", file=sys.stderr)
        print("  https://console.cloud.tencent.com/cam/capi 新建密钥，APPID 在右上角账号信息里。", file=sys.stderr)
        return 2
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
    text = PUSH_ENV.read_text(encoding="utf-8")
    for k, v in lines.items():
        if f"{k}=" not in text:
            text += f"\n{k}={v}"
    PUSH_ENV.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
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
