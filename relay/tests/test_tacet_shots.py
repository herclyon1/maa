"""日报后面跟两张无音区截图（群机器人发图），每张只发一次。

用户 2026-09-07：「我想确认一下是不是刷的是我想要的无音区种类，因为我不放心。
刷完之后能不能贴一张截图在日报通知里面？」
"""
import io, json, os, sys, tempfile, types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import report, notify  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

TMP = Path(tempfile.mkdtemp())
shots = TMP / "okww" / "data" / "apps" / "ok-ww" / "working" / "screenshots"; shots.mkdir(parents=True)
state = TMP / "state"; state.mkdir()
cfgdir = TMP / "automas" / "data" / "sid" / "Default" / "ConfigFile"; cfgdir.mkdir(parents=True)
(cfgdir / "DailyTask.json").write_text(json.dumps({"Which Tacet Suppression to Farm": 2}), encoding="utf-8")

from PIL import Image  # noqa: E402
def png(path, w=1920, h=1080, noisy=False):
    im = Image.new("RGB", (w, h), (30, 40, 50))
    if noisy:
        im = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
    im.save(path, format="PNG")

png(shots / "10-58-35.184_tacet_list_original.png")
png(shots / "11-02-10.000_tacet_arrived_original.png")
png(shots / "09-58-35.184_weekly_remaining_original.png")   # 别的截图不发

class N:
    def __init__(self): self.groups, self.images = [], []
    def send(self, title, body, **k): return []
    def send_group(self, title, body): self.groups.append((title, body)); return []
    def send_group_image(self, p): self.images.append(Path(p).name); return []
class St:
    def __init__(self): self.dir = state
class Eng:
    def __init__(self):
        self.cfg = types.SimpleNamespace(okww_dir=TMP / "okww", automas_dir=TMP / "automas")
        self.state = St(); self.notifier = N()

day = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
e = Eng()
print("[两张都发，带说明]")
done = report._attach_tacet_shots(e, day)
check("发了两张", sorted(done), ["10-58-35.184_tacet_list_original.png", "11-02-10.000_tacet_arrived_original.png"])
check("先发一条说明", e.notifier.groups[0][0], "🖼️ 无音区截图")
check("说明里有序号、名字、套装", all(k in e.notifier.groups[0][1] for k in ("第 2 个", "玄幽东岳", "羽落空尘之歌", "清邪荡煞之心")), True)
check("说明写清两张是什么", "F2 列表页、到达后" in e.notifier.groups[0][1], True)
check("别的截图不发", "09-58-35.184_weekly_remaining_original.png" in e.notifier.images, False)

print("[同一天再发日报：已发过的不重复]")
e2 = Eng()
check("第二次什么都不发", report._attach_tacet_shots(e2, day), [])
check("也不发说明", e2.notifier.groups, [])
png(shots / "12-30-00.000_tacet_list_original.png")
check("新拍的那张会发", report._attach_tacet_shots(e2, day), ["12-30-00.000_tacet_list_original.png"])

print("[没配 OK-WW 目录：安静]")
e3 = Eng(); e3.cfg.okww_dir = None
check("不发", report._attach_tacet_shots(e3, day), [])

print("[大图缩到群机器人上限以内]")
big = TMP / "big.png"; png(big, noisy=True)
raw = big.stat().st_size
out = notify._image_bytes_for_wecom(big)
check("原图确实超限", raw > notify._WECOM_IMAGE_LIMIT, True)
check("缩后在上限内", len(out) <= notify._WECOM_IMAGE_LIMIT, True)
check("缩后是 JPEG", out[:2] == b"\xff\xd8", True)
small = TMP / "small.png"; png(small, 200, 100)
check("小图原样发", notify._image_bytes_for_wecom(small) == small.read_bytes(), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
