"""A Skland 4xx must keep the {"code", "message"} body it came with.

Audit s6 #5 (2026-10-13): _get / _post let urllib raise a bare HTTPError, so
Skland's own reason (10001 「操作失败，请稍后重试」 on a 403, measured 2026-08-27,
docs/SKLAND-API.md) never reached the log or the phone tile, which showed only
「HTTP Error 403」. Network is faked; no request leaves.
"""
import email.message
import io
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import skland  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def refusing(code: int, body: bytes):
    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "Forbidden", email.message.Message(), io.BytesIO(body))
    return urlopen


real = skland.urllib.request.urlopen
url = "https://zonai.skland.com/web/v1/game/endfield/card/detail?roleId=1&serverId=1"

print("[403 with Skland's body: the code and message are in the error]")
skland.urllib.request.urlopen = refusing(403, '{"code":10001,"message":"操作失败，请稍后重试"}'.encode())
try:
    skland._get(url, {})
    said = ""
except Exception as e:  # noqa: BLE001 - the text is what is checked
    said = str(e)
check("Skland's code is kept", "10001" in said, True)
check("Skland's message is kept", "操作失败，请稍后重试" in said, True)
check("the HTTP status is kept", "403" in said, True)

print("\n[403 with no readable body: the plain HTTP error, as before]")
skland.urllib.request.urlopen = refusing(403, b"<html>nope</html>")
try:
    skland._get(url, {})
    got = None
except Exception as e:  # noqa: BLE001
    got = type(e).__name__
check("bare HTTPError", got, "HTTPError")
skland.urllib.request.urlopen = real

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")
sys.exit(1 if fails else 0)
