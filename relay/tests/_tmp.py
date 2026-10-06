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
import logging
import os
import shutil
import tempfile
from pathlib import Path

_MADE: list[str] = []


def tmpdir(prefix: str = "arktest-") -> Path:
    d = tempfile.mkdtemp(prefix=prefix)
    _MADE.append(d)
    return Path(d)


@atexit.register
def _cleanup() -> None:
    """Remove the test's directories once the test is over.

    Logging is switched off first. A test that started a directory watcher
    (watch.start, through collect_watch.start) leaves its daemon thread holding
    a directory removed here; on Windows the change notification then fails and
    the watcher logs 「目录监听掉了，5 秒后重建」, as it should in service. That
    line landed after the test's result line (Windows CI, 2026-10-07: runs
    37519943859 test_collect_watch.py and 37525386830 test_maaend_watchdog.py),
    and the test gate reads the last line. Nothing the test checks runs here.
    """
    logging.disable(logging.CRITICAL)
    if os.environ.get("ARK_KEEP_TMP"):
        return
    for d in _MADE:
        shutil.rmtree(d, ignore_errors=True)
