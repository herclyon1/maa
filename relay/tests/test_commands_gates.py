"""往生产配置里写东西的那条路——四道闸门一道都不许塌。

这个文件防的是**一类损失：配置被写坏，于是刷错关卡、烧掉理智药**。
826 就是这么来的：凭空造了一个字段、编了一个下标的含义，写进去，第二天早班
按错的配置跑了一整趟。`commands.py` 25 个函数里 19 个从来没有被任何测试调用过，
包括「结构化 diff 不符预期就回滚」这道唯一能拦住 826 的闸门本身。

四道闸门（relay/README.md「命令的四道闸门」）：
  ① 白名单——不在表里的动作直接拒，模型不许自己发 JSON patch
  ② 人工确认——会写盘的动作没确认不动手
  ③ 落地校验——备份→改→解析→结构化 diff，多改一个字段就整个放弃并回滚
  ④ 回报——成功、失败、拒绝都要说出来，而且要说人话

外加一条同样致命的：白名单里有名字、apply_command 里却没有分支，
手机上按下去什么也不会发生，而屏幕上一片绿。

全程用临时目录里的假配置，`_mas` 换成假的，不碰网络、不碰真机。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

STATE = tmpdir()
AUTOMAS = tmpdir()
os.environ["ARK_STATE_DIR"] = str(STATE)
os.environ["ARK_AUTOMAS_DIR"] = str(AUTOMAS)

from datetime import datetime                       # noqa: E402
from ark_relay import commands                      # noqa: E402
from ark_relay.config import SERVER_TZ              # noqa: E402
from ark_relay.statestore import StateStore         # noqa: E402

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
    if not ok:
        fails.append(label)


# The real config's shape, cut down to what these gates touch: one script uuid,
# one user uuid, Info/* per user and Game/WaitTime per script (docs/CONFIG.md).
SID = "59da8762-8fa7-4f2b-9c1e-000000000001"
UID = "b0c1d2e3-0000-0000-0000-000000000002"


def sample() -> dict:
    return {SID: {
        "Info": {"Name": "MAA"},
        "Game": {"WaitTime": 60},
        "SubConfigsInfo": {"UserData": {UID: {"Info": {
            "Stage": "AT-4", "StageMode": "Fixed", "MedicineNumb": 0,
            "Annihilation": "Close", "RunTimesLimit": 3}}}}}}


CFG = AUTOMAS / "config" / "ScriptConfig.json"


def reset_cfg(data: "dict | None" = None) -> str:
    CFG.parent.mkdir(parents=True, exist_ok=True)
    for old in CFG.parent.glob("ScriptConfig.json.bak-*"):
        old.unlink()
    raw = json.dumps(data if data is not None else sample(),
                     ensure_ascii=False, indent=2)
    CFG.write_text(raw, encoding="utf-8")
    return raw


def cfg_raw() -> str:
    return CFG.read_text(encoding="utf-8")


def backups() -> list[Path]:
    return sorted(CFG.parent.glob("ScriptConfig.json.bak-*"))


# ---------------------------------------------------------------- 闸门 ①

print("[闸门① 白名单：不在表里的动作一律拒绝]")
for bad in ("format_disk", "poweroff_now", "", "SET_STAGE", "set stage",
            "run_now; rm -rf", "set_config2", None, 123):
    ok, msg = commands.apply_command({"action": bad, "confirmed": True})
    check(f"拒绝 {bad!r}", (ok, "不在允许的清单里" in msg), (False, True))
check("完全没有 action 字段也拒绝",
      commands.apply_command({"confirmed": True})[0], False)
# Trimmed, not rejected: a name with stray whitespace is still that action.
check("前后空格会被去掉，不当成陌生动作",
      "不在允许的清单里" in commands.apply_command({"action": " set_stage "})[1], False)

check("ALLOWED 就是两张表的并集",
      commands.ALLOWED, commands.REVERSIBLE | commands.MUTATING)
# An action in both tables would take the reversible path and skip gate ②.
check("两张表不许有交集（同名会绕过人工确认）",
      commands.REVERSIBLE & commands.MUTATING, set())

print("\n[白名单里有名字，apply_command 里就必须有分支]")
# Otherwise the button exists on the phone, does nothing, and reports nothing.
saved_mas = commands._mas


def offline_mas(path, body=None, timeout=20):
    raise RuntimeError("测试里不联网")


commands._mas = offline_mas
minimal = {
    "set_stage": {"value": ""}, "set_medicine": {"value": None},
    "set_wait_time": {"value": None}, "toggle_task": {"name": "x"},
    "set_config": {}, "set_master": {}, "run_now": {},
    "skip_today": {}, "debug_mode": {"off": True}, "weekly_boss": {},
    "echo_farm": {"boss": 1, "until": "08:30"}, "echo_farm_stop": {},
    "echo_farm_until": {"until": "21:00"},
    "skip_shutdown": {"off": True},
}
check("每个白名单动作都准备了样例指令",
      sorted(minimal), sorted(commands.ALLOWED))
for action in sorted(commands.ALLOWED):
    reset_cfg()
    _, msg = commands.apply_command({"action": action, "confirmed": True,
                                     **minimal[action]})
    check(f"{action} 有人接手（不是「未处理的动作」）",
          msg.startswith("未处理的动作"), False)
commands._mas = saved_mas

# ---------------------------------------------------------------- 闸门 ②

print("\n[闸门② 会写盘的动作，没有人工确认就不许动]")
for action in sorted(commands.MUTATING):
    before = reset_cfg()
    ok, msg = commands.apply_command({"action": action, "value": "1-7",
                                      "queue": "早班", "script": "MAA",
                                      "path": "Info.Stage", "game": "MAA"})
    check(f"{action} 未确认被拒", (ok, "人工确认" in msg), (False, True))
    check(f"{action} 未确认时配置文件一个字节没动", cfg_raw(), before)
    check(f"{action} 未确认时不留备份", backups(), [])

reset_cfg()
ok, msg = commands.apply_command({"action": "skip_shutdown"})
check("可逆动作不需要确认，直接放行", ok, True)

# ---------------------------------------------------------------- _STAGE_RE

print("\n[关卡号形状：不认识就拒，绝不「猜一个」]")
for good in ("TO-5", "CE-6", "1-7", "LS-6", "AT-4", "S4-1", "H8-4"):
    check(f"{good} 是合法形状", bool(commands._STAGE_RE.match(good)), True)
for bad in ("", "TO5", "TO-", "-5", "1-7-3", "TO-5 ", " TO-5",
            "ANNIHILATION-1", "1-7; rm -rf /", "剿灭-1", "TOOOO-5",
            'AT-4","MedicineNumb":99'):
    check(f"{bad!r} 不是合法形状", bool(commands._STAGE_RE.match(bad)), False)

before = reset_cfg()
ok, msg = commands._set_stage('AT-4","MedicineNumb":99')
check("注入形状的关卡号被拒", (ok, "不合法" in msg), (False, True))
check("被拒时配置没动", cfg_raw(), before)

ok, msg = commands._set_stage("to-5")
check("小写自动转大写后写入", ok, True)
check("写进去的是大写",
      json.loads(cfg_raw())[SID]["SubConfigsInfo"]["UserData"][UID]["Info"]["Stage"],
      "TO-5")
check("回报是人话，不是路径", msg, "刷取关卡：AT-4 → TO-5")
check("写之前留了备份", len(backups()), 1)
check("备份里是原来的内容", backups()[0].read_text(encoding="utf-8"), before)

reset_cfg()
ok, msg = commands._set_stage("AT-4")
check("写成和现在一样的值算成功，不算 diff 报警", (ok, msg),
      (True, "已经是这个状态，无需改动"))
check("没改动就不留备份", backups(), [])

# Two users in the file: which one did the operator mean? The regex would hit
# the first one silently.
two = sample()
two[SID]["SubConfigsInfo"]["UserData"]["another-uid"] = {"Info": {"Stage": "1-7"}}
before = reset_cfg(two)
ok, msg = commands._set_stage("CE-6")
check("文件里有两处 Stage 时拒绝改，不挑一个下手",
      (ok, "预期恰好 1 处" in msg), (False, True))
check("拒绝时文件没动", cfg_raw(), before)

CFG.unlink()
check("配置文件不存在时拒绝", commands._set_stage("1-7")[0], False)

# ---------------------------------------------------------------- 数值范围

print("\n[理智药和等待秒数的范围：越界必须拒，不许写进去让别人改回来]")
for bad in (None, "很多", "3.5", [3]):
    check(f"理智药 {bad!r} 不是整数",
          (commands._set_medicine(bad)[0], "不是整数" in commands._set_medicine(bad)[1]),
          (False, True))
for bad in (-1, 1000, 99999):
    check(f"理智药 {bad} 越界", commands._set_medicine(bad)[0], False)
reset_cfg()
check("理智药 0 合法（本来就是 0，报「无需改动」）",
      commands._set_medicine(0), (True, "已经是这个状态，无需改动"))
reset_cfg()
ok, msg = commands._set_medicine(3)
check("理智药 3 写得进去", (ok, msg), (True, "理智药上限：0 个 → 3 个"))

# AUTO-MAS's own schema declares ge=60 and silently clamps anything smaller.
for bad in (0, 30, 59, 601, "六十"):
    check(f"等待秒数 {bad!r} 被拒", commands._set_wait_time(bad)[0], False)
check("拒 59 秒时说清楚是 AUTO-MAS 的下限",
      "60" in commands._set_wait_time(59)[1], True)
reset_cfg()
check("等待 60 秒合法", commands._set_wait_time(60)[0], True)
reset_cfg()
ok, msg = commands._set_wait_time(600)
check("等待 600 秒合法且回报是人话", (ok, msg),
      (True, "终末地启动后等待：60 秒 → 600 秒"))

print("\n[toggle_task 明确拒绝，不猜任务名]")
ok, msg = commands._toggle_task("自动战斗", True)
check("toggle_task 一律拒绝", (ok, "set_config" in msg), (False, True))

# ---------------------------------------------------------------- 闸门 ③

print("\n[闸门③ 结构化 diff：多改一个字段就整个放弃——826 唯一能被拦住的地方]")
before = reset_cfg()

ok, msg = commands._safe_rewrite(CFG, lambda raw: raw.replace('"Fixed"', '"Auto"'),
                                 expect_changed=2)
check("只改了 1 处但预期 2 处，放弃", (ok, "和预期不符" in msg), (False, True))
check("放弃时文件没动", cfg_raw(), before)

ok, msg = commands._safe_rewrite(
    CFG, lambda raw: raw.replace('"AT-4"', '"1-7"').replace('"MedicineNumb": 0',
                                                            '"MedicineNumb": 99'),
    expect_changed=1)
check("正则误伤了第二个字段，放弃", (ok, "改动 2" in msg), (False, True))
check("误伤时理智药没被烧", cfg_raw(), before)

def add_key(raw: str) -> str:
    d = json.loads(raw)
    d[SID]["Info"]["凭空造的"] = 1
    return json.dumps(d, ensure_ascii=False, indent=2)


ok, msg = commands._safe_rewrite(CFG, add_key, expect_changed=1)
check("凭空多出一个字段，放弃", (ok, "新增 1" in msg), (False, True))
check("多字段时文件没动", cfg_raw(), before)


def drop_key(raw: str) -> str:
    d = json.loads(raw)
    del d[SID]["Game"]["WaitTime"]
    return json.dumps(d, ensure_ascii=False, indent=2)


ok, msg = commands._safe_rewrite(CFG, drop_key, expect_changed=0)
check("少了一个字段，放弃", (ok, "删除 1" in msg), (False, True))
check("少字段时文件没动", cfg_raw(), before)


def boom(raw: str) -> str:
    raise ValueError("正则没匹配上")


ok, msg = commands._safe_rewrite(CFG, boom, expect_changed=1)
check("生成改动时抛异常，不碰盘", (ok, "生成改动失败" in msg), (False, True))
check("抛异常时文件没动", cfg_raw(), before)

ok, msg = commands._safe_rewrite(CFG, lambda raw: raw[:-3], expect_changed=1)
check("改完不是合法 JSON，放弃", (ok, "JSON 非法" in msg), (False, True))
check("非法 JSON 时文件没动", cfg_raw(), before)

CFG.write_text("{这不是 JSON", encoding="utf-8")
ok, msg = commands._safe_rewrite(CFG, lambda raw: raw, expect_changed=1)
check("原文件就不是 JSON 时拒绝改（不许在坏文件上叠改动）",
      (ok, "不是合法 JSON" in msg), (False, True))

before = reset_cfg()
saved_write = commands.atomic_write_text


def cannot_write(path, text, newline=None):
    raise OSError("磁盘满了")


commands.atomic_write_text = cannot_write
ok, msg = commands._safe_rewrite(CFG, lambda raw: raw.replace('"Fixed"', '"Auto"'),
                                 expect_changed=1)
commands.atomic_write_text = saved_write
check("写盘失败要回滚并说出来", (ok, "已回滚" in msg), (False, True))
check("回滚后内容和原来一模一样", cfg_raw(), before)

# ---------------------------------------------------------------- _flatten

print("\n[_flatten：diff 的地基，漏掉一层就等于那一层没有闸门]")
check("嵌套字典摊平成路径",
      commands._flatten({"a": {"b": 1}}), {"/a/b": 1})
check("列表按下标摊平（两个下标互换必须被看见）",
      commands._flatten({"a": [10, 20]}), {"/a[0]": 10, "/a[1]": 20})
check("列表里的字典也摊得到底",
      commands._flatten({"a": [{"b": True}]}), {"/a[0]/b": True})
check("空字典摊出来是空", commands._flatten({}), {})
check("None 也是一个值，不许被吞", commands._flatten({"a": None}), {"/a": None})
a = commands._flatten({"x": [1, 2]})
b = commands._flatten({"x": [2, 1]})
check("列表顺序变了会被 diff 看见",
      {k for k in a.keys() & b.keys() if a[k] != b[k]}, {"/x[0]", "/x[1]"})

# ---------------------------------------------------------------- 闸门 ④

print("\n[闸门④ 回报要说人话：路径里的 uuid 不许出现在推送里]")
# The operator reads this on a phone; `/59da8762-.../Game/WaitTime` says nothing
# (operator feedback, 2026-08-20).
check("等待秒数带单位",
      commands._humanize(f"/{SID}/Game/WaitTime", 60, 120),
      "终末地启动后等待：60 秒 → 120 秒")
check("理智药带单位",
      commands._humanize(f"/{SID}/Info/MedicineNumb", 0, 3),
      "理智药上限：0 个 → 3 个")
check("关卡不带单位",
      commands._humanize(f"/{SID}/Info/Stage", "AT-4", "TO-5"),
      "刷取关卡：AT-4 → TO-5")
check("布尔值说开关，不说 True/False",
      commands._humanize("/x/TimeEnabled", True, False), "队列定时：开 → 关")
check("没登记的字段退回字段名，不吐整条路径",
      commands._humanize(f"/{SID}/Info/SomethingNew", 1, 2),
      "SomethingNew：1 → 2")
for field in ("Stage", "MedicineNumb", "WaitTime", "Annihilation",
              "TimeEnabled", "Enabled", "RunTimesLimit", "StageMode"):
    line = commands._humanize(f"/{SID}/Info/{field}", 1, 2)
    check(f"{field} 的回报里没有 uuid", SID in line, False)

# ---------------------------------------------------------------- set_config

print("\n[set_config：读现值、路径必须已存在、写完回读——826 缺的就是这三条]")


class FakeMas:
    """The AUTO-MAS backend, in memory. Records every call so «没写盘» is provable."""

    def __init__(self, *, honour_writes=True):
        self.calls: list[tuple[str, dict]] = []
        self.honour_writes = honour_writes
        self.scripts = {SID: {"Info": {"Name": "MAA"}}}
        self.users = {SID: {UID: {"Info": {"Stage": "AT-4", "MedicineNumb": 0}}}}

    def __call__(self, path, body=None, timeout=20):
        body = body or {}
        self.calls.append((path, body))
        if path == "/api/scripts/get":
            return {"data": self.scripts}
        if path == "/api/scripts/user/get":
            return {"data": self.users.get(body["scriptId"], {})}
        if path == "/api/scripts/user/update":
            if self.honour_writes:
                self._merge(self.users[body["scriptId"]][body["userId"]],
                            body["data"])
            return {"status": "success"}
        if path == "/api/dispatch/start":
            return {"status": "success"}
        raise AssertionError(f"测试没准备这个端点: {path}")

    def _merge(self, dst, src):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                self._merge(dst[k], v)
            else:
                dst[k] = v

    def wrote(self):
        return [c for c in self.calls if c[0] == "/api/scripts/user/update"]


def with_mas(fake, fn):
    saved, commands._mas = commands._mas, fake
    try:
        return fn()
    finally:
        commands._mas = saved


check("缺 script/path 就拒",
      with_mas(FakeMas(), lambda: commands._set_config({"script": "MAA"}))[0],
      False)
check("缺 value 就拒（不许把「没给」当成 None 写进去）",
      with_mas(FakeMas(),
               lambda: commands._set_config({"script": "MAA", "path": "Info.Stage"}))[1],
      "set_config 需要 value")

f = FakeMas()
ok, msg = with_mas(f, lambda: commands._set_config(
    {"script": "MAA", "path": "Info.凭空造的", "value": 1}))
check("路径不存在就拒（说清中继不会自己新建）", (ok, "已拒绝" in msg and "不会自己新建" in msg), (False, True))
check("拒绝时一次写请求都没发出去", f.wrote(), [])

f = FakeMas()
ok, msg = with_mas(f, lambda: commands._set_config(
    {"script": "没这个脚本", "path": "Info.Stage", "value": "1-7"}))
check("脚本不存在就拒", (ok, "找不到脚本" in msg), (False, True))
check("找不到脚本时不写", f.wrote(), [])

f = FakeMas()
ok, msg = with_mas(f, lambda: commands._set_config(
    {"script": "MAA", "path": "Info.Stage", "value": "AT-4"}))
check("值本来就一样：算成功且不写", (ok, f.wrote()), (True, []))

f = FakeMas()
ok, msg = with_mas(f, lambda: commands._set_config(
    {"script": "maa", "path": "Info.Stage", "value": "1-7"}))
check("脚本名大小写不敏感，改得动", ok, True)
check("回报带上「原值 → 新值」", msg, "maa 的 Info.Stage：'AT-4' → '1-7'")
check("确实只写了一次", len(f.wrote()), 1)
check("写的是嵌套结构，不是拍平的键",
      f.wrote()[0][1]["data"], {"Info": {"Stage": "1-7"}})

f = FakeMas(honour_writes=False)
ok, msg = with_mas(f, lambda: commands._set_config(
    {"script": "MAA", "path": "Info.Stage", "value": "1-7"}))
check("写了但回读还是老值：必须报失败，不许报绿",
      (ok, "写了但没生效" in msg), (False, True))

print("\n[_dig / _nest：路径解析本身]")
check("_dig 取得到嵌套值",
      commands._dig({"Info": {"Stage": "AT-4"}}, "Info.Stage"), "AT-4")
for bad in ("Info.Nope", "Nope.Stage", "Info.Stage.More"):
    try:
        commands._dig({"Info": {"Stage": "AT-4"}}, bad)
        check(f"_dig 对 {bad} 应该抛 KeyError", "没抛", "KeyError")
    except KeyError:
        check(f"_dig 对不存在的 {bad} 抛 KeyError", True, True)
check("_nest 造出嵌套写入体",
      commands._nest("Task.IfFight", True), {"Task": {"IfFight": True}})
check("_nest 单层也行", commands._nest("Stage", "1-7"), {"Stage": "1-7"})

# ---------------------------------------------------------------- skip_today

print("\n[skip_today：过期的指令不许生效，老队列名要认得]")
today = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
# The dispatch sweep above already ran skip_today once; start from a clean slate.
StateStore(STATE).pop("queues", f"skip_day:{today}")
ok, msg = commands._skip_today("早班", "2020-01-01")
check("指定日期已经过去：拒绝，别跳掉没人要跳的那天",
      (ok, "过期" in msg), (False, True))
check("过期指令没写进状态",
      StateStore(STATE).get("queues", f"skip_day:{today}"), None)

ok, msg = commands._skip_today("新队列")
check("老队列名映射成现名", ok, True)
check("状态里存的是现名",
      StateStore(STATE).get("queues", f"skip_day:{today}"), "早班")
ok, _ = commands._skip_today("晚班", today)
check("带上今天的日期照样生效",
      StateStore(STATE).get("queues", f"skip_day:{today}"), "晚班")

# ---------------------------------------------------------------- 队列进出

print("\n[从队列里摘掉一个脚本，必须能原位加回来——加不回去=那个游戏从此不跑了]")


class FakeQueueMas(FakeMas):
    def __init__(self):
        super().__init__()
        self.qid = "queue-0001"
        # OK-WW exists as a script but is not in this queue - the "nothing to
        # take out" case.
        self.scripts["s-okww"] = {"Info": {"Name": "OK-WW"}}
        self.queues = {self.qid: {"Info": {"Name": "早班"}}}
        self.items = {"u1": {"Info": {"ScriptId": "s-endfield"}},
                      "u2": {"Info": {"ScriptId": SID}},
                      "u3": {"Info": {"ScriptId": "s-wuwa"}}}
        self.order = ["u1", "u2", "u3"]
        self._next = 4

    def __call__(self, path, body=None, timeout=20):
        body = body or {}
        if path == "/api/queue/get":
            self.calls.append((path, body))
            return {"data": self.queues}
        if path == "/api/queue/item/get":
            self.calls.append((path, body))
            return {"index": [{"uid": u} for u in self.order], "data": self.items}
        if path == "/api/queue/item/delete":
            self.order.remove(body["queueItemId"])
            self.items.pop(body["queueItemId"])
            return {"status": "success"}
        if path == "/api/queue/item/add":
            uid = f"u{self._next}"
            self._next += 1
            self.items[uid] = {"Info": {}}
            self.order.append(uid)
            return {"queueItemId": uid}
        if path == "/api/queue/item/update":
            self.items[body["queueItemId"]]["Info"].update(
                body["data"]["Info"])
            return {"status": "success"}
        if path == "/api/queue/item/order":
            self.order = list(body["indexList"])
            return {"status": "success"}
        return super().__call__(path, body, timeout)


q = FakeQueueMas()
rec = with_mas(q, lambda: commands.skip_script_in_queue("早班", "MAA"))
check("摘出来的记录记住了原位置", rec and rec["position"], 1)
check("队列里真的少了一个", q.order, ["u1", "u3"])
ok = with_mas(q, lambda: commands.restore_script_in_queue(rec))
check("加得回来", ok, True)
check("加回的是原来那一位（中间）",
      [q.items[u]["Info"].get("ScriptId") for u in q.order],
      ["s-endfield", SID, "s-wuwa"])
check("再加一次不会加重复（已在队列里就直接返回成功）",
      with_mas(q, lambda: commands.restore_script_in_queue(rec)), True)
check("重复调用后队列长度不变", len(q.order), 3)

q2 = FakeQueueMas()
check("这个脚本本来就不在队列里：返回 None，不抛",
      with_mas(q2, lambda: commands.skip_script_in_queue("早班", "OK-WW")), None)
check("返回 None 时没动过队列", q2.order, ["u1", "u2", "u3"])

print("\n[单跑一个脚本：不许因为找不到就去派发整条队列]")
f = FakeMas()
ok, msg = with_mas(f, lambda: commands.run_script("MAA"))
check("找得到就单独派发", (ok, "单独开跑" in msg), (True, True))
check("派发的是脚本 id、模式 AutoProxy",
      [c[1] for c in f.calls if c[0] == "/api/dispatch/start"],
      [{"taskId": SID, "mode": "AutoProxy"}])
f = FakeMas()
ok, msg = with_mas(f, lambda: commands.run_script("终末地"))
check("找不到脚本就明说，且什么也不派发",
      (ok, [c for c in f.calls if c[0] == "/api/dispatch/start"]), (False, []))

print("\n[run_now：接口挂了要说人话，不许静默]")
ok, msg = with_mas(offline_mas, lambda: commands._run_now("早班"))
check("拿不到队列列表时明确失败", (ok, "取不到队列列表" in msg), (False, True))


class NoSuchQueueMas(FakeMas):
    def __call__(self, path, body=None, timeout=20):
        if path == "/api/queue/get":
            return {"data": {"q1": {"Info": {"Name": "早班"}}}}
        return super().__call__(path, body, timeout)


ok, msg = with_mas(NoSuchQueueMas(), lambda: commands._run_now("不存在的班"))
check("队列名不存在时把现有的列出来（人才知道该按哪个）",
      (ok, "早班" in msg), (False, True))

print("\n[apply_command 永远不抛：抛出去就没人回报了]")


def explode(*a, **k):
    raise RuntimeError("底下炸了")


saved, commands._set_stage = commands._set_stage, explode
ok, msg = commands.apply_command({"action": "set_stage", "value": "1-7",
                                  "confirmed": True})
commands._set_stage = saved
check("底层抛异常也被兜住并回报", (ok, "执行出错" in msg), (False, True))

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
