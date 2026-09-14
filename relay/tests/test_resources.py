"""resources: the phone's stamina numbers - parsed from real samples, cached, and
a failing source never sinks the block."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import resources

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


print("[鸣潮 baseData（2026-09-15 01:15 真实样本）]")
base = {"energy": 232, "maxEnergy": 240, "storeEnergy": 44, "storeEnergyLimit": 480,
        "weeklyInstCount": 0, "weeklyInstCountLimit": 3, "liveness": 0, "livenessMaxCount": 100}
check("波片 232/240，备用 44/480，周本 0/3", resources.wuwa_from_base(base),
      {"波片": 232, "上限": 240, "备用": 44, "备用上限": 480, "周本": 0, "周本上限": 3, "活跃": 0, "活跃上限": 100})

print("\n[终末地 dungeon：按含义认字段，不猜死名字]")
check("ap/maxAp/apRecoverTime", resources.endfield_from_dungeon({"ap": 86, "maxAp": 160, "apRecoverTime": 1789467867}),
      {"理智": 86, "上限": 160, "回满": resources._stamp(1789467867)})
check("sanity/sanityMax", resources.endfield_from_dungeon({"curSanity": 12, "sanityMax": 160}), {"理智": 12, "上限": 160})
check("空的说明白", resources.endfield_from_dungeon({}), {"错误": "森空岛没给终末地的理智"})
check("认不出就把名字列出来", resources.endfield_from_dungeon({"foo": 1, "bar": 2})["错误"].startswith("终末地的理智没认出来"), True)

print("\n[fetch：一处失败不拖累别处，结果缓存]")


class Cfg:
    skland_token = ""
    kurobbs_token = ""
    kurobbs_did = ""


resources._cache["at"], resources._cache["data"] = 0.0, {}
out = resources.fetch(Cfg)
check("没配 token 就是说明，不是异常", out["明日方舟"], {"错误": "没配森空岛 token"})
check("鸣潮同理", out["鸣潮"], {"错误": "没配库街区 token/did"})
check("有取自时刻", bool(out.get("取自")), True)
calls = {"n": 0}
orig = resources._wuwa
resources._wuwa = lambda cfg: calls.__setitem__("n", calls["n"] + 1) or {"波片": 1}
resources.fetch(Cfg)
check("十分钟内不再请求", calls["n"], 0)
resources._cache["at"] = time.time() - resources.TTL_SECONDS - 1
resources.fetch(Cfg)
check("过期才再请求", calls["n"], 1)
resources._wuwa = orig

print("\n[今天：从账目数]")


class St:
    def read_ledger(self, day):
        return [{"script": "MAA", "ok": True}, {"script": "OK-WW", "ok": False}, {"script": "MaaEnd", "ok": True}]


check("跑了 3 失败 1 最近 MaaEnd", resources.today(St(), "2026-09-15"), {"跑了": 3, "失败": 1, "最近": "MaaEnd"})

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
