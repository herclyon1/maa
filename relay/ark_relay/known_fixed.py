"""Fault kinds recorded as fixed, for errwatch to tag when they come back.

Key: errwatch.signature() of the record (logger | message with the variable
parts blanked | exception type). Value: `fixed_in`, the first deployed relay
version (deploy tag relay-<N>) carrying the fix, and `what`, the fault in plain
words for the alarm and the daily report.

Add an entry only for a fix that is in a deploy tag (`git tag --contains
<fix commit>`), never on a guess - a recurrence alarm names the version.

A Python module rather than a JSON file next to it: make-manifest picks up
every ark_relay/*.py, so the registry cannot be left off the machine.
"""

KNOWN: dict[str, dict] = {
    # 9960c184 (first in relay-20261005151027): the boot self-check alarms when
    # Pillow is missing (selfcheck.NEEDED_MODULES); relay3.log 10-05 21:47 had
    # this WARNING with a ModuleNotFoundError for PIL.
    "ark.banners|官方图转 PNG 失败，原样交给系统 OCR|ModuleNotFoundError": {
        "fixed_in": "20261005151027",
        "what": "游戏机缺读图组件，官方长图读不了",
    },
    # Same commit: the 库街区 version-news post was past pageSize 50, now 200
    # (banners._kuro_poster). The message names the version or 「当期」.
    "ark.banners|库街区官方资讯里没找到 # 版本资讯帖": {
        "fixed_in": "20261005151027",
        "what": "库街区官方资讯翻得不够多页，找不到当期版本资讯帖",
    },
    "ark.banners|库街区官方资讯里没找到 当期 版本资讯帖": {
        "fixed_in": "20261005151027",
        "what": "库街区官方资讯翻得不够多页，找不到当期版本资讯帖",
    },
}
