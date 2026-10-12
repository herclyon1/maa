"""落盘只能走 config.atomic_write_*，不许自己手抄「临时文件 + replace」。

2026-09-08 数出来的：仓库里有 5 处手抄的原子写，各写各的——有的漏 fsync、有的
失败了不清理临时文件、报错方式还各不相同。同一件事五种写法，改一处别处不会跟着改，
而它们写的都是 AUTO-MAS / OK-WW / MaaEnd 没有就起不来的配置。

（当初我给的理由是「机器每天硬断电两次」，操作者纠正：一天只有一次，而且那一刻
机器已经关着。这条测试守的是「实现只有一份」，不是防断电。）

这条测试盯两件事：实现只有一份、别处不许再抄。

Section 4 (added 2026-10-12) is about power cuts after all, for state files
the relay reads back: the 08:40 socket cut takes the machine down whether
it is on or off (memory queue-schedule-what-runs.md), and a forced shutdown
or kill can land mid-write too.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

# 1. 唯一的实现在 config.py，而且带 fsync
cfg = (ROOT / "ark_relay" / "core" / "config.py").read_text(encoding="utf-8")
check("config.atomic_write_bytes 存在", "def atomic_write_bytes" in cfg, True)
body = cfg[cfg.index("def atomic_write_bytes"):]
body = body[:body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
check("它 fsync 了", "os.fsync" in body, True)
check("它用 os.replace", "os.replace" in body, True)

# 2. 别处不许再出现「.tmp 然后 replace」这一对
offenders = []
for p in sorted([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files"} & set(p.parts)]) + [ROOT / "service.py", ROOT / "boot_stages.py"]:
    if p.name == "config.py":
        continue
    src = p.read_text(encoding="utf-8")
    for m in re.finditer(r'^\s*(\w+)\s*=\s*.*with_suffix\([^\n]*\.tmp', src, re.M):
        var = m.group(1)
        after = src[m.end():m.end() + 600]
        if re.search(rf"\b(os\.replace\(\s*{var}|{var}\.replace\()", after):
            line = src[:m.start()].count("\n") + 1
            offenders.append(f"{p.name}:{line}")
check("没有别处再手抄原子写", offenders, [])

# 3. 写配置的模块都在用它（抽查那五个改过的）
# (paths after ark_relay/ was split into core/ and features/<name>/)
for name in ("features/weekly/garden.py", "features/weekly/weeklyboss.py",
             "features/preupdate/preupdate_okww.py", "core/desktop.py"):
    src = (ROOT / "ark_relay" / name).read_text(encoding="utf-8")
    check(f"{name} 走的是共用实现",
          bool(re.search(r"atomic_write_(text|bytes)\(", src)), True)

# 4. State files the relay reads back must not be written in place.
# The game PC can lose power or be killed mid-write (the 08:40 socket cut when
# the machine was left on, a forced shutdown). A half-written state file is
# read as empty: retry failure streaks reset, sent markers are lost (the tacet
# shot / upstream-change notice goes out again), the ntfy day count drops to
# zero. These modules write such files and must go through atomic_write_*;
# a direct write_text / write_bytes / open("w") in them fails here.
# Appends (open "a" / "ab") are allowed: a cut loses at most the last line.
DIRECT_OVERWRITE = re.compile(
    r"\.write_text\(|\.write_bytes\(|\bopen\([^)\n]*[\"'](?:w|wb|w\+|wb\+|x|xb)[\"']")
STATE_WRITERS = (
    "ark_relay/features/makeup/collect_retry.py",   # collect-retry/failures.json, <day>.json
    "ark_relay/features/report/report.py",          # tacet-shots-<day>.sent
    "boot_stages.py",                               # evidence-source-notified.json
    "ark_relay/features/phone/quota.py",            # ntfy-<utc day>.json
    "ark_relay/features/alarm/alertlog.py",         # alert day file re-seeded from COS
    "ark_relay/features/evidence/stores.py",        # evidence/gofile.json
    "ark_relay/features/banners/banners.py",        # banners/<day>.json
)
for name in STATE_WRITERS:
    src = (ROOT / name).read_text(encoding="utf-8")
    direct = [f"{name}:{src[:m.start()].count(chr(10)) + 1}"
              for m in DIRECT_OVERWRITE.finditer(src)]
    check(f"{name} has no direct state-file overwrite", direct, [])
    check(f"{name} writes via atomic_write_*",
          bool(re.search(r"atomic_write_(text|bytes)\(", src)), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
