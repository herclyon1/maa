"""测试用的临时目录：进程退出时自己收拾干净。

2026-09-08 量到的：39 个测试各自 `tempfile.mkdtemp()` 且从不清理，Mac 的 TMPDIR
里堆了 29753 个目录、710 MB。每跑一次全套就多几十个，macOS 只在重启时才清。

用法和 mkdtemp 一样，返回 Path：

    from _tmp import tmpdir
    d = tmpdir()

要留下现场看的时候（排查失败），设环境变量 `ARK_KEEP_TMP=1`，就不删了。
"""
from __future__ import annotations

import atexit
import gzip
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

_MADE: list[str] = []
_FX_CACHE: dict[str, Path] = {}
_TESTS_DIR = Path(__file__).resolve().parent

# Config.alert_push_url defaults to the real Mac (macpush.py): a test alarm must
# never be POSTed there. A test that exercises the push sets its own URL.
os.environ.setdefault("ARK_ALERT_PUSH_URL", "")


def tmpdir(prefix: str = "arktest-") -> Path:
    d = tempfile.mkdtemp(prefix=prefix)
    _MADE.append(d)
    return Path(d)


def fx_dir(anchor: object, kind: str) -> Path:
    """Materialize the test sample catalog `fx_<kind>.json` once per process and return its root."""
    _ = anchor
    if kind in _FX_CACHE:
        return _FX_CACHE[kind]
    out = tmpdir(f"arkfx-{kind}-")
    cat_file = _TESTS_DIR / f"fx_{kind}.json"
    if cat_file.exists():
        data: dict[str, str] = json.loads(cat_file.read_text(encoding="utf-8"))
        for rel, content in data.items():
            dest = out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith(".gz"):
                dest.write_bytes(gzip.compress(content.encode("utf-8"), mtime=0))
            else:
                dest.write_bytes(content.encode("utf-8"))
    native_dir = _TESTS_DIR / kind
    if native_dir.is_dir():
        for src in native_dir.rglob("*"):
            if src.is_file():
                dest = out / src.relative_to(native_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
    _FX_CACHE[kind] = out
    return out


@atexit.register
def _cleanup() -> None:
    """Remove the test's directories once the test is over.

    Logging is switched off first. A test that started a directory watcher
    (watch.start, through collect_watch.start) leaves its daemon thread holding
    a directory removed here; on Windows the change notification then fails and
    the watcher logs 「目录监听掉了，5 秒后重建」, as it should in service. That
    line landed after the test's result line (Windows CI, 2026-10-07: runs
    37519943859 test_collect.py and 37525386830 test_maaend_watchdog.py),
    and the test gate reads the last line. Nothing the test checks runs here.
    """
    logging.disable(logging.CRITICAL)
    if os.environ.get("ARK_KEEP_TMP"):
        return
    for d in _MADE:
        shutil.rmtree(d, ignore_errors=True)
