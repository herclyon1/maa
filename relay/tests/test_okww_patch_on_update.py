"""OK-WW 运行时自己更新 → 版本号一变就把补丁贴回去；预更新至少等它 30 秒后的检查。

2026-09-06：预更新 08:46:43 启动 OK-WW、08:46:46 就判「无需更新」关掉（它的更新检查
是窗口显示 30 秒后才排的）；09:20 那趟启动时它自己装了 v3.6.7-beta.2，src 被整段换掉，
八条补丁全没了，那趟裸跑；直到 11:30 重启服务才贴回去。
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay import okww_patch, preupdate  # noqa: E402

fails = []
tmp = pathlib.Path(tempfile.mkdtemp())
okww = tmp / "okww"; (okww / "data" / "apps" / "ok-ww").mkdir(parents=True)
state = tmp / "state"; state.mkdir()
app = okww / "data" / "apps" / "ok-ww" / "app.json"

calls = []
okww_patch.ensure_patches = lambda d: calls.append(d) or ["贴了一条"]   # 不碰真补丁

app.write_text(json.dumps({"current_version": "v3.6.6"}), encoding="utf-8")
n1 = okww_patch.ensure_if_updated(state, okww)
if len(calls) != 1:
    fails.append("第一次见到版本号就该贴一遍")
n2 = okww_patch.ensure_if_updated(state, okww)
if len(calls) != 1 or n2:
    fails.append("版本没变不该再贴")
app.write_text(json.dumps({"current_version": "v3.6.7-beta.2"}), encoding="utf-8")
n3 = okww_patch.ensure_if_updated(state, okww)
if len(calls) != 2 or not any("v3.6.6" in x and "v3.6.7-beta.2" in x for x in n3):
    fails.append(f"版本变了要贴并说明从哪换到哪：{n3}")
if okww_patch.ensure_if_updated(state, None):
    fails.append("没有目录时应安静返回空")

# 预更新：不许在 30 秒内就下「查过了」的结论
src = "".join(q.read_text(encoding="utf-8") for q in sorted((pathlib.Path(__file__).resolve().parents[1] / "ark_relay").glob("preupdate*.py")))  # 预更新拆成了五个文件，一起看
if preupdate.OKWW_MIN_WAIT_SECONDS < 40:
    fails.append("最少等待要覆盖 OK-WW 30 秒后的那次检查")
if "time.monotonic() - launched >= OKWW_MIN_WAIT_SECONDS" not in src:
    fails.append("「查过了」的判据没有带最少等待")

# engine.tick 里有这一段
eng = (pathlib.Path(__file__).resolve().parents[1] / "ark_relay" / "engine.py").read_text(encoding="utf-8")
if "self._patch_okww_if_updated)" not in eng:
    fails.append("tick 里没有按版本变化重贴补丁那一段")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
