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
    if os.environ.get("ARK_KEEP_TMP"):
        return
    for d in _MADE:
        shutil.rmtree(d, ignore_errors=True)
