"""鸣潮的运行结果要能进日报——即使它给不出掉落物。

OK-WW 是纯图像识别的战斗脚本，从不读结算界面，所以没有 MAA 那种
`drop_statistics` 可抄。它唯一公布的数字来自 ok-script 的 `info_set`
（该函数每次调用都会写日志），能拿到的是：投进去多少波片、换来几次进本、
日常任务停在哪里。运营 2026-08-25 的原话是「虽然它没有掉落物的显示，
但只能说够用了」。

另一处要点：AUTO-MAS 把 OK-WW 归在 `general_result` 这个通用键下，
和「通用脚本」共用，**光看键名认不出是哪个脚本**——只能靠文件名前缀。
"""
import json, os, sys, tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector, core      # noqa: E402

fails = []
def check(label, got, want=True):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


LOG = """\
2026-08-25 21:31:02 INFO ok.task.task DailyTask:info_set Chars 清宵, 折枝, 维里奈
2026-08-25 21:31:10 INFO ok.task.task DailyTask:info_set current daily progress 0
2026-08-25 21:31:11 INFO ok.task.task DailyTask:info_set total daily points 20
2026-08-25 21:31:30 INFO ok.task.task ForgeryTask:info_set current_stamina 240
2026-08-25 21:33:00 INFO ok.task.task BaseWWTask:使用单倍体力
2026-08-25 21:35:00 INFO ok.task.task ForgeryTask:info_set current_stamina 200
2026-08-25 21:35:01 INFO ok.task.task BaseWWTask:使用单倍体力
2026-08-25 21:37:00 INFO ok.task.task ForgeryTask:info_set current_stamina 160
2026-08-25 21:37:01 INFO ok.task.task BaseWWTask:当前体力大于等于双倍, 160 >= 80
2026-08-25 21:40:00 INFO ok.task.task ForgeryTask:info_set current_stamina 80
2026-08-25 21:40:01 INFO ok.task.task BaseWWTask:使用单倍体力
2026-08-25 21:42:00 INFO ok.task.task ForgeryTask:info_set current_stamina 40
2026-08-25 21:42:01 INFO ok.task.task BaseWWTask:使用单倍体力
2026-08-25 21:44:00 INFO ok.task.task ForgeryTask:info_set current_stamina 0
2026-08-25 21:44:01 INFO ok.task.task DomainTask:used all stamina
2026-08-25 21:44:30 INFO ok.task.task DailyTask:info_set current daily progress 180
2026-08-25 21:44:31 INFO ok.task.task DailyTask:info_set total daily points 100
2026-08-25 21:44:40 INFO ok.task.task DailyTask:info_set current task claim daily
2026-08-25 21:45:00 INFO ok.task.task DailyTask:info_set current task claim mail
2026-08-25 21:45:20 INFO ok.task.task DailyTask:battle pass
2026-08-25 21:45:40 INFO ok.task.task DailyTask:info_set current task check weekly garden
2026-08-25 21:46:00 INFO ok.task.task DailyTask:Daily Task Completed
"""

log = TMP / "sample.log"
log.write_text(LOG, encoding="utf-8")
got = collector.parse_okww_log(log)

print("[从日志里还原出来的数字]")
# 240→200→160→80→40→0，逐段下降相加 = 240。首尾相减在有储备回补时会算少。
check("消耗波片按逐段下降累加", got.get("okww_stamina_spent"), 240)
check("进本次数 = 每次消耗体力各一条", got.get("okww_runs"), 5)
check("日常波片进度取最大值", got.get("okww_daily"), "180/180")
check("活跃度带上限、满了要标出来", got.get("okww_points"), "100/100（已满）")
# 2026-08-29 改口径：OK-WW 的 used all stamina 不是「剩 0」，是**剩下的不够
# 再开一局**（凝素领域单次 40，剩 37 就进不去）。用户点名「用尽不是零吗？
# 还剩 20 多」——原来那句直译是事实错误。
check("为什么停下", got.get("okww_stopped"), "体力不够再开一局")
# 只报有信息量的项，而且按实际成败标注——出现在日志里不等于做成了。
check("跑完还剩多少波片", got.get("okww_stamina_left"), 0)
check("任务按成败标注", got.get("okww_steps"), ["凝素领域 ×5"])

print("\n[储备回补不能被算成没花]")
refill = TMP / "refill.log"
refill.write_text("info_set current_stamina 100\ninfo_set current_stamina 60\n"
                  "info_set current_stamina 240\ninfo_set current_stamina 200\n",
                  encoding="utf-8")
check("只累加下降段", collector.parse_okww_log(refill).get("okww_stamina_spent"), 80)

print("\n[体力不够时说得出原因]")
short = TMP / "short.log"
short.write_text("info_set current_stamina 18\nnot enough stamina\n", encoding="utf-8")
check("报「体力不够」", collector.parse_okww_log(short).get("okww_stopped"),
      "体力不够，一局都没开成")

print("\n[凝素领域要报人话名字，不是序号]")
# 用户 2026-08-26：「他那个凝素领域第一个机器看得懂，人看不懂是什么啊」。
# 序号→名字的表是实拍游戏内列表抄的，认不出的序号必须退回「第 N 个」，
# 宁可少说也不能报错名字——列表顺序会随筛选和版本变。
fl = collector._forgery_label                                  # noqa: SLF001
check("0 → 陨翼云渊", fl("info_set Teleport to Forgery Challenge 0"),
      "凝素领域·陨翼云渊（迅刀）")
check("3 → 碎蚀云渊", fl("info_set Teleport to Forgery Challenge 3"),
      "凝素领域·碎蚀云渊（臂铠）")
check("表里没有的序号退回「第 N 个」（1 起算）",
      fl("info_set Teleport to Forgery Challenge 9"), "凝素领域（第 10 个）")
check("日志里根本没这行就只说「凝素领域」", fl("什么都没有"), "凝素领域")

named = TMP / "named.log"
named.write_text(
    "info_set current_stamina 240\n"
    "ForgeryTask:info_set Teleport to Forgery Challenge 0\n使用单倍体力\n"
    "ForgeryTask:info_set Teleport to Forgery Challenge 0\n使用单倍体力\n"
    "info_set current_stamina 80\n", encoding="utf-8")
check("步骤里带上了副本名",
      collector.parse_okww_log(named).get("okww_steps"),
      ["凝素领域·陨翼云渊（迅刀） ×2"])

print("\n[记录能被认出来是 OK-WW，而不是「通用脚本」]")
root = TMP / "history"
d = root / "2026-08-25" / "wuwa"
d.mkdir(parents=True, exist_ok=True)
j = d / "OK-WW-21-31-02.json"
j.write_text(json.dumps({"general_result": "Success!"}), encoding="utf-8")
(d / "OK-WW-21-31-02.log").write_text(LOG, encoding="utf-8")
rec = collector.parse_record(j, root)
check("解析出来了", rec is not None)
if rec:
    check("脚本名来自文件名前缀", rec.script, "OK-WW")
    check("Success! 算成功", rec.ok, True)
    check("日志里的数字挂到了 raw 上", rec.raw.get("okww_runs"), 5)

print("\n[日报里真的会写出来]")
entry = {"script": "OK-WW", "user": "wuwa", "ok": True, "raw": got,
         "started": "2026-08-25 21:31", "finished": "2026-08-25 21:46",
         "duration_min": 15, "failed": [], "drops": {}, "recruits": {}}
body = "\n".join(core._render_entries([entry])) if hasattr(core, "_render_entries") else ""
if not body:                      # 渲染函数名不同就退回源码检查
    src = (Path(__file__).resolve().parents[1] / "ark_relay" / "core.py").read_text(encoding="utf-8")
    # 2026-08-29 用户要求删掉的两项：
    #   消耗量——「我不需要啊，不要再塞进去了」
    #   活跃度/日常进度——读数被实测证伪（活跃度实际 160 报成 40，
    #   日常进度读成 0/180 而这一轮明明刷了）。错的数字比没有数字更糟，
    #   在把屏幕和日志对上之前不报。
    # 只看代码不看注释：注释里正写着「为什么不再报消耗量」，
    # 连注释一起搜必然误报。（同一个坑今天踩过第二次了。）
    src_code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    check("不再渲染消耗量", "消耗波片" in src_code, False)
    check("不再渲染活跃度/日常进度",
          "活跃度" in src_code or "日常波片" in src_code, False)
    check("渲染了备用体力（游戏里是两个数）", "备用" in src)
    check("渲染了任务列表", "okww_steps" in src)
    check("渲染了剩余波片", "波片" in src)
else:
    check("写出了波片消耗", "消耗波片 240" in body)
    check("写出了进本次数", "进本 5 次" in body)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
