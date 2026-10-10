"""Evidence bundles in the form each upstream project asks for, kept off the machine.

Each of the three issue templates wants its own program's log export:

* MaaEnd: the 🗄️ button - `MaaEnd-logs-<version>-<stamp>-partNN.zip`.
* MAA: 「设置 → 问题反馈 → 生成日志压缩包」 - `report_<stamp>_partNN.zip`.
* OK-WW: 「Export Logs」 - `<gui_title>-log.zip` of `screenshots/` + `logs/`.

None of the three can be triggered from outside its UI, so bundles.py does what
those buttons do, file for file, and sources.py pins the upstream code it
mirrors (`check_sources()` reports a change upstream).

A bundle keeps each upstream's layout and volume rules but always selects by a
time window (`window=(t0, t1)`, epoch seconds): the run widened by WINDOW_SLACK
when the relay reports a failure, or what the operator asks for on the command
line (`python -m ark_relay evidence --hours 2` / `--since` / `--run-id`; with
nothing given, the latest run in the ledger). The bundle, the AUTO-MAS record,
the relay.log / app.log slices (logslice.py) and, for OK-WW, a desktop picture
are packed into one archive per run and uploaded to Tencent Cloud COS only
(`uploaders()`; stores.py). The WeCom app (`WeComFiles`), the WeCom group robot
(`WeComBotFiles`) and gofile.io (`Gofile`) are not in `uploaders()`; their code
stays for a hand-run upload.

The local copy under `state/evidence/` is deleted after thirty days (`prune`).
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.features.evidence.bundles import (  # noqa: F401 - re-exported: evidence.<name> keeps working
    MAA_PART, MAAEND_MAX_IMAGES, MAAEND_MAX_VOLUME, ZIP_CENTRAL_DIR_FIXED_BYTES, ZIP_EOCD_BYTES,
    ZIP_LOCAL_HEADER_OVERHEAD, _IMAGE_EXT, _TEXT_EXT, _dedup, _estimate_compressed, _in_window,
    _measure_compressed, _volumes, _walk_sorted, bundle_for, bundle_maa, bundle_maaend, bundle_okww,
    maaend_entries, pack_one, require_window)
from ark_relay.features.evidence.logslice import (  # noqa: F401 - re-exported
    _CTX_TS, _line_ts, context_files, slice_log)
from ark_relay.features.evidence.sources import (  # noqa: F401 - re-exported
    JSDELIVR, LAST_SEEN, PINS, Pin, _HEADER, check_sources, pinned_text, region_text)
from ark_relay.features.evidence.stores import (  # noqa: F401 - re-exported
    GOFILE, Cos, Gofile, PermanentUploadError)

log = logging.getLogger("ark.evidence")

# A run's window is widened by this on both ends: MaaEnd's last lines land after
# AUTO-MAS has recorded the run, and the framework log rotates a little before.
WINDOW_SLACK = 300


# ------------------------------------------------- WeCom stores (not in uploaders())
# WeCom error codes a retry cannot change.
_WECOM_PERMANENT = {40001, 40013, 40014, 41001, 42001, 60020, 60011, 81013, 93000}


class WeComFiles:
    """Evidence as WeCom file messages to the same person the relay already pushes to.

    WeCom caps a file at 20 MB and keeps uploaded media for three days. The
    message reaches his phone the moment it is sent, so the evidence is readable
    with the machine off; the media id in the index lets the Mac fetch the bytes
    back within the three days. Bigger archives are refused here and go to the
    next store - never cut into pieces.
    """

    LIMIT = 20 * 1024 * 1024

    def __init__(self, cfg):
        self.cfg = cfg
        self._token = ""
        self._until = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._until:
            return self._token
        url = ("https://qyapi.weixin.qq.com/cgi-bin/gettoken"
               f"?corpid={self.cfg.wecom_corpid}&corpsecret={self.cfg.wecom_secret}")
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("errcode") != 0:
            raise RuntimeError(f"企业微信 gettoken: {d.get('errcode')} {d.get('errmsg')}")
        self._token, self._until = d["access_token"], time.time() + int(d.get("expires_in", 7200)) - 300
        return self._token

    def _post(self, url: str, data: bytes, ctype: str, timeout: int) -> dict:
        return _wecom_post(url, data, ctype, timeout)

    def _upload_piece(self, name: str, data: bytes, timeout: int) -> str:
        boundary = "----ark" + uuid.uuid4().hex
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="media"; filename="{name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n", data, f"\r\n--{boundary}--\r\n".encode()])
        d = self._post("https://qyapi.weixin.qq.com/cgi-bin/media/upload"
                       f"?access_token={self.token()}&type=file", body,
                       f"multipart/form-data; boundary={boundary}", timeout)
        return d["media_id"]

    def _send_file(self, media_id: str) -> None:
        self._post(f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={self.token()}",
                   json.dumps({"touser": self.cfg.wecom_touser, "msgtype": "file",
                               "agentid": int(self.cfg.wecom_agentid), "file": {"media_id": media_id}}).encode(),
                   "application/json", 60)

    def upload(self, path: Path, timeout: int = 600) -> dict:
        data = path.read_bytes()
        # One file per run, never cut into pieces: over WeCom's cap the file goes
        # to the next store instead.
        if len(data) > self.LIMIT:
            raise PermanentUploadError(f"企业微信文件上限 20 MB，这份 {len(data) // 1_000_000} MB")
        mid = self._upload_piece(path.name, data, timeout)
        self._send_file(mid)
        return {"name": path.name, "size": len(data), "store": "wecom", "media_id": mid,
                "expires": (datetime.now() + timedelta(days=3)).isoformat(timespec="seconds"),
                "page": "企业微信"}


def _wecom_post(url: str, data: bytes, ctype: str, timeout: int) -> dict:
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("errcode") != 0:
        msg = f"企业微信: {d.get('errcode')} {str(d.get('errmsg'))[:80]}"
        # 60020 = the machine's dial-up IP is not on the app's trusted list; only
        # the WeCom admin console can change that.
        if d.get("errcode") in _WECOM_PERMANENT:
            raise PermanentUploadError(msg)
        raise RuntimeError(msg)
    return d


class WeComBotFiles:
    """The same, through the group robot's webhook: no trusted-IP list, so it
    works from the dial-up line when the app API answers 60020. The file lands
    in the group he reads; nothing fetches it back by script (webhook media
    has no download API), so this is for his eyes, and the local copy stays
    under state/evidence/.
    """

    LIMIT = 20 * 1024 * 1024

    def __init__(self, webhook: str):
        self.webhook = webhook
        q = urllib.parse.parse_qs(urllib.parse.urlparse(webhook).query)
        self.key = (q.get("key") or [""])[0]

    def upload(self, path: Path, timeout: int = 600) -> dict:
        data = path.read_bytes()
        if len(data) > self.LIMIT:
            raise PermanentUploadError(f"企业微信文件上限 20 MB，这份 {len(data) // 1_000_000} MB")
        boundary = "----ark" + uuid.uuid4().hex
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="media"; filename="{path.name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n", data, f"\r\n--{boundary}--\r\n".encode()])
        d = _wecom_post(f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={self.key}&type=file",
                        body, f"multipart/form-data; boundary={boundary}", timeout)
        mid = d["media_id"]
        _wecom_post(self.webhook, json.dumps({"msgtype": "file", "file": {"media_id": mid}}).encode(),
                    "application/json", 60)
        return {"name": path.name, "size": len(data), "store": "wecom-bot", "media_id": mid, "page": "企业微信群"}


def pick_uploader(cfg, run_id: str = ""):
    """The first store in `uploaders(cfg)`, or None when COS is not configured."""
    ups = uploaders(cfg, run_id)
    return ups[0] if ups else None


def uploaders(cfg, run_id: str = "") -> list:
    """The configured stores, best first: COS alone (WeComFiles, WeComBotFiles and
    Gofile are not returned). An empty list means "COS not configured", and
    save_and_upload says so."""
    out: list = []
    if all(getattr(cfg, k, "") for k in ("cos_secret_id", "cos_secret_key", "cos_bucket", "cos_region")):
        out.append(Cos(cfg.cos_secret_id, cfg.cos_secret_key, cfg.cos_bucket, cfg.cos_region,
                       prefix=run_id.replace("/", "_")))
    return out


# ------------------------------------------------------------------ driver


def run_window(started: datetime, finished: "datetime | None") -> tuple[float, float]:
    """One run's window: its start and end widened by WINDOW_SLACK; an unknown end means now."""
    t0 = started.timestamp() - WINDOW_SLACK
    t1 = (finished.timestamp() if finished else time.time()) + WINDOW_SLACK
    return t0, t1


def desktop_shot(cfg, out_dir: Path, screenshot=None, *, name: str = "", move: bool = False,
                 quiet: bool = False) -> "Path | None":
    """A picture of the real desktop, named by the moment it was taken, for an
    OK-WW failure bundle: OK-WW's own export is only its log plus the
    screenshots it chose to save, which can say nothing about the screen. The
    picture is taken when the record lands, which AUTO-MAS writes at the
    end of the whole script run - so it may show the state after a retry; the
    filename says when. None when the desktop cannot be reached (a Mac, a test,
    no interactive session).

    `name` (no extension) replaces the time-stamped default; `move` takes the
    agent's file instead of copying it, so state/desktop/ does not fill up with
    one copy of every picture (task_shots.py takes ~16 a round); `quiet` leaves
    the warning to the caller."""
    try:
        if screenshot is None:
            from ark_relay.core.desktop import Desktop  # noqa: PLC0415 - Windows-only helper
            screenshot = Desktop(Path(cfg.state_dir)).screenshot
        shot = screenshot()
        if not shot:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{name or 'desktop-' + datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        if move:
            shutil.move(str(shot), str(target))
        else:
            shutil.copy2(shot, target)
        return target
    except Exception:  # a missing picture must not cost the bundle
        if quiet:
            log.debug("桌面截图没拿到", exc_info=True)
        else:
            log.warning("桌面截图没拿到，证据包不带它", exc_info=True)
        return None


def save_and_upload(cfg, script: str, run_id: str, extra: list[Path] = (), *,
                    window: "tuple[float, float]", uploader=None, screenshot=None,
                    relay_until: "float | None" = None) -> dict:
    """Build the bundle into state/evidence/<run_id>/bundle, upload it, append to the index. Never raises past the bundle step.

    `relay_until`: see context_files."""
    require_window(window)
    state_dir = Path(cfg.state_dir)
    dst = state_dir / "evidence" / run_id.replace("/", "_") / "bundle"
    result: dict = {"script": script, "run_id": run_id, "when": datetime.now().isoformat(timespec="seconds"),
                    "files": [], "uploaded": [], "errors": []}
    try:
        paths = bundle_for(script, cfg, dst, window)
        # bundle_for makes the folder only when it found files of its own; the
        # extras (AUTO-MAS's record, task pictures) go in even when it did not.
        dst.mkdir(parents=True, exist_ok=True)
        for p in extra:
            try:
                shutil.copy2(p, dst / p.name)
                paths.append(dst / p.name)
            except OSError as exc:
                result["errors"].append(f"copy {p.name}: {exc}")
        for p in context_files(cfg, window, dst, relay_until=relay_until):
            paths.append(p)
        if script == "OK-WW":
            if shot := desktop_shot(cfg, dst, screenshot):
                paths.append(shot)
        result["files"] = [p.name for p in paths]
    except Exception as exc:  # evidence must never block bookkeeping
        log.exception("证据包打不出来")
        result["errors"].append(f"bundle: {type(exc).__name__}: {exc}")
        paths = []
    # One file per run: the upstream export and the
    # AUTO-MAS record go into a single archive, stored uncompressed (the parts
    # inside are already deflated). Unpack it to hand the parts to upstream.
    one: list[Path] = []
    if paths:
        try:
            one = [pack_one(dst.parent / f"{script}-{run_id.replace('/', '_')}.zip", paths)]
        except OSError as exc:
            result["errors"].append(f"pack: {exc}")
    result["archive"] = one[0].name if one else ""
    stores = [uploader] if uploader else uploaders(cfg, run_id)
    if one and not stores:
        result["errors"].append("没有配置 COS（.env 里缺 COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET / COS_REGION），证据包只留在机器上")
    dead: set[int] = set()          # stores that refused permanently this round
    for p in one:
        ok = False
        for i, up in enumerate(stores):
            if i in dead:
                continue
            # Three tries with a pause between them cover a store's passing
            # error. A permanent refusal (wrong key, IP not allowed) skips the
            # tries and the store.
            for attempt in range(1, 4):
                try:
                    result["uploaded"].append(up.upload(p))
                    ok = True
                    break
                except PermanentUploadError as exc:
                    log.warning("证据上传被拒 %s（%s，换下一条路）: %s", p.name, type(up).__name__, exc)
                    result["errors"].append(f"{type(up).__name__} {p.name}: {exc}")
                    dead.add(i)
                    break
                except Exception as exc:  # noqa: BLE001 - one failed upload must not lose the rest
                    log.warning("证据上传失败 %s（%s 第 %d 次）: %s", p.name, type(up).__name__, attempt, exc)
                    if attempt == 3:
                        result["errors"].append(f"{type(up).__name__} {p.name}: {type(exc).__name__}: {exc}")
                    else:
                        time.sleep(15 * attempt)
            if ok:
                break
    if result["uploaded"]:
        result["page"] = result["uploaded"][0].get("page", "")
        result["store"] = result["uploaded"][0].get("store", "gofile")
    idx = state_dir / "evidence" / "index.jsonl"
    idx.parent.mkdir(parents=True, exist_ok=True)
    with idx.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result


def prune(state_dir: Path, days: int = 30) -> int:
    """Delete local evidence folders older than `days`. Returns how many went."""
    root = state_dir / "evidence"
    if not root.is_dir():
        return 0
    cutoff = time.time() - days * 86400
    n = 0
    for d in root.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n

