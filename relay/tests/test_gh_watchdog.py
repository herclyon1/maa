"""The GitHub Actions boot watchdog (scripts/watchdog.py; queue/watchdog.json has it off since
08-20): a daytime run by hand judges tonight's checks as not due, and a watchdog that cannot
ask Tailscale says so (audit 11-08 A-25; dispatch relay-opt-round5-1108 R5-02).

Pinned here:
* today_at: 00:30 (a 23:10 check run late past midnight) still means last night's 23:10;
  10:00 by hand means tonight's 23:10 (until 11-08: last night's, so 「还在线」 was judged);
* main(): Tailscale's API failing is one 「🔌 开机监督自身异常」 alert and exit 1 on a
  scheduled run, a print only on a run by hand (no CHECK_CRON).
"""
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("gh_watchdog", ROOT / "scripts" / "watchdog.py")
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


def srv(d, hh, mm):
    return datetime(2026, 11, d, hh, mm, tzinfo=wd.SERVER_TZ)


print("[today_at：凌晨迟到的检查算前一晚，白天手动跑算今晚]")
check("11-09 00:30 查 23:10：是 11-08 那晚的", wd.today_at("23:10", srv(9, 0, 30)), srv(8, 23, 10))
check("11-08 10:00 查 23:10：是今晚的（还没到点）", wd.today_at("23:10", srv(8, 10, 0)), srv(8, 23, 10))
check("11-08 10:00 查 08:40：今天早上的", wd.today_at("08:40", srv(8, 10, 0)), srv(8, 8, 40))
check("UTC 时间传进来也按北京时间算（11-08 02:00 UTC = 10:00 北京）",
      wd.today_at("23:10", datetime(2026, 11, 8, 2, 0, tzinfo=wd.timezone.utc)), srv(8, 23, 10))
last = srv(8, 9, 50)
check("白天手动跑：晚上收工那项不判（之前会说「该关机了还在线」）",
      wd.run_check("shutdown", {"label": "晚上收工", "boot_since": "21:15", "min_off": "21:50", "off_by": "22:35"},
                   last, srv(8, 10, 0).astimezone(wd.timezone.utc)), None)

print("\n[问不到 Tailscale：报一条「开机监督自身异常」，退出码 1；手动跑只打印]")
cfg = tmpdir() / "watchdog.json"
cfg.write_text(json.dumps({"enabled": True, "pause_until": "2000-01-01", "device": "ins",
                           "checks": {"20 1 * * *": {"kind": "boot", "label": "早上开机", "since": "08:40"}}}),
               encoding="utf-8")
sent = []
saved = (wd.CONFIG, wd.alert, wd.tailscale_last_seen, dict(wd.os.environ))


def broken(device):
    raise RuntimeError("缺 TS_OAUTH_CLIENT_ID / TS_OAUTH_SECRET secrets")


wd.CONFIG, wd.alert, wd.tailscale_last_seen = cfg, (lambda t, b: sent.append((t, b)) or True), broken
try:
    wd.os.environ["CHECK_CRON"] = "20 1 * * *"
    rc = wd.main()
    check("定时跑：退出码 1", rc, 1)
    check("……推了一条，标题是开机监督自身异常", [t for t, _b in sent], ["🔌 开机监督自身异常"])
    check("……正文说了原因", "TS_OAUTH" in sent[0][1], True)
    sent.clear()
    wd.os.environ.pop("CHECK_CRON")
    check("手动跑：退出码 1", wd.main(), 1)
    check("……不推送", sent, [])
finally:
    wd.CONFIG, wd.alert, wd.tailscale_last_seen = saved[:3]
    wd.os.environ.clear()
    wd.os.environ.update(saved[3])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
