"""Helpers nothing called are gone and stay gone (review 2026-10-13, s5 #10).

* Notifier.send_image / WeCom.send_image / WeCom._upload: the self-built app is in
  no automatic order (push.py --private sends text only); group images go through
  Notifier.send_group_image.
* notify._hint: advice for the self-built app's errcode 60020 inside the outage
  notice; that app is never in an automatic order, so it could never fire.
* techlog.red_items: numbered from 1 on every call (duplicate ids); add_red is the
  one writer.
* Desktop.click(x, y): clicks go by text (click_text).

Checked two ways: the names are not defined, and no relay or scripts source calls them.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ark_relay.core import desktop, notify, techlog  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


print("[没人调用的辅助已删掉]")
check("Notifier.send_image", hasattr(notify.Notifier, "send_image"), False)
check("WeCom.send_image", hasattr(notify.WeCom, "send_image"), False)
check("WeCom._upload", hasattr(notify.WeCom, "_upload"), False)
check("notify._hint", hasattr(notify, "_hint"), False)
check("techlog.red_items", hasattr(techlog, "red_items"), False)
check("Desktop.click", hasattr(desktop.Desktop, "click"), False)
check("群机器人发图还在", hasattr(notify.Notifier, "send_group_image"), True)
check("按字点击还在", hasattr(desktop.Desktop, "click_text"), True)

print("\n[也没有哪里再调用它们]")
srcs = [p for p in (ROOT / "ark_relay").rglob("*.py") if "okww_files" not in p.parts]
srcs += [ROOT / "service.py", ROOT / "boot_stages.py"] + list((ROOT.parent / "scripts").rglob("*.py"))
# WeComBot.send_image (the group image) stays; scripts/mac/techlog.py has its own red_items.
pat = re.compile(r"(?<!wecom_bot)\.send_image\(|\._upload\(|\b_hint\(|\bcore\.techlog\b.*red_items|"
                 r"\btechlog\.red_items\(|\bdesk\w*\.click\(")
hits = [f"{p.name}:{i}" for p in srcs for i, ln in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
        if pat.search(ln)]
check("没有调用处", hits, [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
