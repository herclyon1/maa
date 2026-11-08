"""A receipt says when its order was sent to the second and which setting or queue it was about
(audit 11-08 D-07, relay side; dispatch relay-opt-round6-1108 R6-04; modes.add_receipt,
phone_channel.receipt_target).

Before: "sent" was 「MM-dd HH:mm」 and "action" the only other key, so a save of several
settings at once - set_master / set_config pressed within one minute - gave receipts the App
could not tell apart. Pinned here:

* "ts" is the send time in seconds beside the old "sent"; "target" names
  set_master game:path, set_config script:path, skip_today / unskip_today the queue;
* neither key is written when there is nothing to say, and every older key is unchanged;
* _phone_execute hands its receipt the target of the order it ran.
"""
import json
import logging
import sys
import types
from pathlib import Path

# phone_channel imports win32event at module level (Windows only); nothing here calls it.
sys.modules.setdefault("win32event", types.ModuleType("win32event"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

from ark_relay.features.modes import modes  # noqa: E402
from ark_relay.features.phone import phone_channel  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


T = 1762570800     # 2026-11-08 11:00:00 Beijing

print("[一次保存两项：同一分钟、同一个动作，靠 ts 和 target 分得开]")
sd = tmpdir()
modes.add_receipt(sd, "set_master", True, "刷取关卡：TO-5", sent=T, target="终末地:AutoEssence/AutoEssenceMenu")
modes.add_receipt(sd, "set_master", True, "领取方式：单倍领取", sent=T + 1, target="终末地:AutoEssence/AutoEssenceObtainMode")
got = json.loads((sd / modes._RECEIPTS).read_text(encoding="utf-8"))
check("同一分钟", [r["sent"] for r in got], [got[0]["sent"]] * 2)
check("秒戳分得开", [r["ts"] for r in got], [T, T + 1])
check("目标分得开", [r["target"] for r in got], ["终末地:AutoEssence/AutoEssenceMenu",
                                               "终末地:AutoEssence/AutoEssenceObtainMode"])
check("原来的键都还在", sorted(got[0]), sorted(["at", "action", "ok", "text", "sent", "ts", "target"]))

print("\n[没有发送时间、没有目标：不写这两项（形状和以前一样）]")
sd = tmpdir()
modes.add_receipt(sd, "refresh", True, "已刷新")
check("只有原来的键", sorted(json.loads((sd / modes._RECEIPTS).read_text(encoding="utf-8"))[0]),
      sorted(["at", "action", "ok", "text"]))

print("\n[哪种指令的目标是什么]")
rt = phone_channel.receipt_target
check("set_master", rt({"action": "set_master", "game": "终末地", "path": "AutoEssence/AutoEssenceMenu"}),
      "终末地:AutoEssence/AutoEssenceMenu")
check("set_config", rt({"action": "set_config", "script": "MaaEnd", "path": "Task.IfSanity"}), "MaaEnd:Task.IfSanity")
check("skip_today", rt({"action": "skip_today", "queue": "晚班"}), "晚班")
check("unskip_today", rt({"action": "unskip_today", "queue": "早班"}), "早班")
check("别的指令：没有", rt({"action": "run_now", "queue": "早班"}), "")

print("\n[_phone_execute 把它跑的那条指令的目标交给回执]")
seen = []
phone_channel._phone_execute(lambda body: (True, "改好了"), type("N", (), {"send": lambda *a, **k: []})(),
                             logging.getLogger("ark.test_receipt_target_1108"), lambda *a, **k: None,
                             lambda a, s, ok, msg, **k: seen.append((a, s, k.get("target"))),
                             {"action": "set_config", "script": "MAA", "path": "Stage.Stage", "value": "1-7"},
                             "set_config", T, True)
check("回执带上了目标", seen, [("set_config", T, "MAA:Stage.Stage")])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
