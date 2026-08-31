"""补丁的替换文本里带着自己的锚点时，改了 present() 就会再贴一层。

2026-09-01 实测踩到：波片检查 v1 的替换文本末尾自带
`self.click_team_challenge()`，我把 present() 改成认 v3 之后，
_apply_one 在 v1 上面又贴了一层——两段检查同时存在，旧那段先跑，
而它正是会误判的那版：波片 91（>60）也被判成「不足」跳过本次周本。

**这种叠加是看不出来的**：文件语法没错、present() 也为真、
_verify_or_revert 照样过。所以要有一道专门的自查。
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import okww_patch as P

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

TMP = Path(tempfile.mkdtemp())
F = TMP / "x.py"

# 一条会自我叠加的补丁：new 里带着 old
# 两个版本的替换文本不同，但都打同一句日志——那句就是跨版本的特征串。
V1 = '    # 第一版\n    log("跳过")\n    call()'
V3 = '    # 第三版\n    step1()\n    log("跳过")\n    call2()'
BAD = P._Patch(name="会叠加的", parts=("x.py",), old="    call()", new=V1,
               present=lambda t: "# 第一版" in t,
               breaks="旧那段会先跑", unique='log("跳过")')

print("\n[干净地贴一次]")
F.write_text("def f():\n    call()\n", encoding="utf-8")
msgs = P._apply_one(TMP, BAD)
check("贴上了", "已重新贴上" in " ".join(msgs), True)
check("特征串只出现一次", F.read_text(encoding="utf-8").count('log("跳过")'), 1)

print("\n[present 变了之后再贴一次 —— 必须被自查抓住]")
BAD2 = P._Patch(name="会叠加的", parts=("x.py",), old=BAD.old, new=V3,
                present=lambda t: "# 第三版" in t,   # 只认新版本，认不出 v1
                breaks="旧那段会先跑", unique='log("跳过")')
msgs = P._apply_one(TMP, BAD2)
t = F.read_text(encoding="utf-8")
check("确实叠成两层了", t.count('log("跳过")'), 2)
check("自查报出来了", any("叠了 2 层" in m for m in msgs), True)

print("\n[没叠就不许乱报]")
F.write_text("def f():\n    call()\n", encoding="utf-8")
msgs = P._apply_one(TMP, BAD)
check("不报叠加", any("叠了" in m for m in msgs), False)

print("\n[真实那条：v1 的原文留着，用来还原]")
check("v1 常量在", hasattr(P, "_NOWAVE_V1"), True)
check("v1 是带误判的那版（判定在点击之前）",
      "0.25, 0.40, 0.75, 0.56" in P._NOWAVE_V1, True)
check("v3 的判定在点击之后",
      P._NOWAVE_NEW.index("team_start_challenge") < P._NOWAVE_NEW.index("结晶波片"), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
