#!/opt/homebrew/bin/python3
"""Fetch one run's evidence files back to the Mac.

    evidence_pull.py <index.jsonl> <run-id fragment> <dest root>

Reads the mirrored index the relay wrote (evidence.sh keeps it), takes the
newest entry matching the fragment, and fetches its files:

* store "cos"   - signed GET against Tencent COS (COS_SECRET_ID/KEY/BUCKET/REGION
                  in ~/.config/ark/push.env), same signature recipe as the relay's
                  `evidence.Cos`.
* store "wecom" - `media/get` by media id with the WeCom app credentials in
                  push.env. WeCom keeps media three days; after that the entry's
                  `expires` says so and the file lives only in his WeCom chat.
* store "wecom-bot" - the group robot's media has no download API; prints that.
* store "gofile" - nothing to fetch by script; prints the page.

Files land in <dest root>/<run_id with / as _>/.
"""
from __future__ import annotations

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
    url = f"https://qyapi.weixin.qq.com/cgi-bin/media/get?access_token={token}&media_id={u['media_id']}"
    with urllib.request.urlopen(url, timeout=600) as r:
        data = r.read()
    if data[:1] == b"{":
        d = json.loads(data.decode("utf-8", "replace"))
        raise SystemExit(f"  ✗ {u['name']}：企业微信没给文件（{d.get('errcode')} {d.get('errmsg')}）"
                         f"——媒体只保留 3 天，这一趟登记的到期时间是 {u.get('expires')}")
    (dest / u["name"]).write_bytes(data)
    print(f"  ✓ {u['name']}（企业微信）")




DAILY_DEST_ROOT = Path.home() / "Claude" / "ark-evidence" / "daily"
_DAILY_TS = __import__("re").compile(r"^(?:(\d{4})-)?(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)")


def _hhmm(s: str):
    from datetime import timedelta  # noqa: PLC0415
    try:
        h, m = s.split(":")
        return timedelta(hours=int(h), minutes=int(m))
    except ValueError:
        raise SystemExit(f"时刻写错了：{s}（要 HH:MM）")


def parse_window(date: str, span: list[str]) -> tuple[float, float]:
    from datetime import datetime, timedelta  # noqa: PLC0415
    year = int(date[:4])
    start = datetime(year, int(date[5:7]), int(date[8:10]))
    end = start + timedelta(days=1)
    if span:
        if len(span) != 2:
            raise SystemExit("时间窗要给两个时刻：HH:MM HH:MM")
        return (start + _hhmm(span[0])).timestamp(), (start + _hhmm(span[1])).timestamp()
    return start.timestamp(), end.timestamp()


def slice_lines(path: Path, window: tuple[float, float]) -> str:
    from datetime import datetime  # noqa: PLC0415
    year = datetime.fromtimestamp(window[0]).year
    keep = False
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _DAILY_TS.match(line)
        if m:
            y = int(m.group(1)) if m.group(1) else year
            try:
                ts = datetime(y, int(m.group(2)), int(m.group(3)),
                              int(m.group(4)), int(m.group(5)), int(m.group(6))).timestamp()
            except ValueError:
                ts = None
            if ts is not None:
                keep = window[0] <= ts <= window[1]
        if keep:
            out.append(line)
    return "\n".join(out) + ("\n" if out else "")


def daily_main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        raise SystemExit("usage: evidence_pull.py --daily <YYYY-MM-DD> [HH:MM HH:MM]")
    date = args[0]
    window = parse_window(date, args[1:])
    e = env(Path.home() / ".config" / "ark" / "push.env")
    if not all(e.get(k) for k in ("COS_SECRET_ID", "COS_SECRET_KEY", "COS_BUCKET", "COS_REGION")):
        raise SystemExit("push.env 里缺 COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET / COS_REGION")
    dest = DAILY_DEST_ROOT / date
    dest.mkdir(parents=True, exist_ok=True)
    failed = 0
    for key, name in (("relay", "relay"), ("automas-app", "automas-app")):
        u = {"key": f"daily/{key}-{date}.log", "name": f"{name}-{date}.log"}
        try:
            cos_get(e, u, dest)
        except Exception as exc:  # noqa: BLE001 - one missing object must not lose the other
            print(f"  ✗ {u['name']}：取不到（{exc}）")
            failed += 1
            continue
        sliced = slice_lines(dest / u["name"], window)
        if not sliced.strip():
            print(f"  {u['name']}：这一天在窗口里没有行")
        else:
            print(f"  {u['name']}：窗口里 {len(sliced.splitlines())} 行 → {dest / ('window-' + u['name'])}")
            (dest / f"window-{u['name']}").write_text(sliced, encoding="utf-8")
    print(f"文件在 {dest}/")
    return 1 if failed else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--daily":
        return daily_main(sys.argv[2:])
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
    if store == "wecom-bot":
        print("  群机器人发的文件没有取回接口，去企业微信群里下载")
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
