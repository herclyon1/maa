"""Post-deploy smoke test, run on the game machine by deploy-relay.sh.

Why this exists (user's order, 2026-09-06): 「『部署完成』这四个字只能由脚本打印。」

Hash-matching every file proves the bytes arrived. It does not prove the code
*runs*: a bad import, a typo in a module-level constant, a syntax error under
the machine's Python 3.14 (not the Mac's) all pass a hash check and then break
at the first tick - hours later, with the service showing RUNNING the whole
time. So before the script is allowed to say "deployed", it imports every
module in the tree with the machine's own interpreter and reads back the log
the service wrote after its restart.

Read-only by design: importing is enough to catch what needs catching, and
nothing here may dispatch a queue or spend the user's stamina.
"""
import importlib
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(r"C:\ProgramData\ark-relay")
sys.path.insert(0, str(ROOT))

bad = []

# 1. Every module must import under the machine's Python.
pys = [p for p in (ROOT / "ark_relay").rglob("*.py") if "okww_files" not in p.parts]
# macOS 的 tar 会把扩展属性打成 `._文件名` 一起送过来（2026-09-08 撞过）。
# 那不是模块，别去 import 它——但也**别当没看见**：多出来的文件说明推送方式有问题。
junk = [p for p in pys if p.name.startswith("._")]
if junk:
    bad.append(f"目录里混进了 {len(junk)} 个不该有的文件，例如 {junk[0].name}"
               f"（macOS 打包时带上了扩展属性，推送方式要修）")
mods = sorted(p.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
              for p in pys if p.name != "__init__.py" and not p.name.startswith("._"))
# Incremental since 2026-09-18: importing all eighty modules took 20-25 s of a
# 77-101 s deploy. With `--changed a.py,b.py` only the changed modules and every
# module that imports them (by a plain text scan of `from .x import` /
# `import ark_relay.x`) are imported; a module-level error in an unchanged
# module cannot have been introduced by this deploy. No argument = all, as before.
changed_arg = next((a for a in sys.argv if a.startswith("--changed=")), "")
if changed_arg:
    changed = {c.strip() for c in changed_arg.split("=", 1)[1].split(",") if c.strip()}
    stems = {pathlib.Path(c).stem for c in changed if c.endswith(".py")}
    pick: set[str] = set()
    for m in mods:
        stem = m.rsplit(".", 1)[-1]
        if stem in stems:
            pick.add(m)
            continue
        try:
            txt = (ROOT / (m.replace(".", "/") + ".py")).read_text(encoding="utf-8", errors="replace")
        except OSError:
            pick.add(m)
            continue
        if any(re.search(rf"(from \.+\s*import\s+[^\n]*\b{re.escape(st)}\b|from \.{re.escape(st)}\b|import ark_relay\.{re.escape(st)}\b|from ark_relay import [^\n]*\b{re.escape(st)}\b)", txt) for st in stems):
            pick.add(m)
    if any(not c.endswith(".py") or "/" not in c and c.endswith(".py") and pathlib.Path(c).stem in ("service", "boot_stages") for c in changed):
        pick = set(mods)          # a top-level file (service.py / boot_stages.py) or a non-py file: import everything
    mods_to_import = sorted(pick) if pick else []
else:
    mods_to_import = mods
for m in mods_to_import:
    try:
        importlib.import_module(m)
    except Exception as e:   # noqa: BLE001 - 冒烟就是要接住所有导入失败
        bad.append(f"import {m} 失败：{type(e).__name__}: {e}")
print(f"SMOKE 导入 {len(mods_to_import)} 个模块（共 {len(mods)} 个），失败 {sum(1 for b in bad if b.startswith('import'))} 个")

# 2. The registry that every state write is checked against must still parse,
#    and the sections it declares must be the ones the store actually has.
try:
    from ark_relay import statestore
    store = statestore.StateStore(ROOT / "state")
    for sec in statestore.SECTIONS:
        store.section(sec)
    print(f"SMOKE 状态表 {len(statestore.SECTIONS)} 段全部可读")
except Exception as e:       # noqa: BLE001 - 同上
    bad.append(f"状态表读不了：{type(e).__name__}: {e}")

# 3. The notification wording gate is a module-level table; if it fails to
#    build, every push this machine sends is broken and nothing else notices.
try:
    from ark_relay import texts
    assert texts.failed("MAA")
    print("SMOKE 通知文案表可用")
except Exception as e:       # noqa: BLE001 - 同上
    bad.append(f"通知文案表坏了：{type(e).__name__}: {e}")

# 4. What the service itself wrote since it came back up.
log = ROOT / "relay.log"
since = time.time() - 180
lines = []
try:
    for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]:
        lines.append(ln)
except OSError as e:
    bad.append(f"读不到 relay.log：{e}")
tail = lines[-60:]
start = max((i for i, l in enumerate(tail) if "服务模式启动" in l), default=0)
after = tail[start:]
hits = [l for l in after
        if re.search(r"\bERROR\b|Traceback|这一段出错|贴不上|叠了|写不进", l)]
if hits:
    bad += ["启动后日志里有报错：" + h.strip()[:160] for h in hits[:5]]
print(f"SMOKE 启动后日志 {len(after)} 行，报错 {len(hits)} 行")

# The command channel. On 2026-09-08 the machine's .env pointed the inbox at a
# file I had deleted from the repo that day; every order after that 404-ed on all
# four doors and nothing but the relay's own log said so. A deploy must not be
# called complete while the machine cannot reach the address the service uses.
try:
    import re as _re
    from pathlib import Path as _P
    from ark_relay import inbox as _inbox
    _env = _P(r"C:\ProgramData\ark-relay\.env").read_text(encoding="utf-8", errors="replace")
    _m = _re.search(r"^ARK_INBOX_URL=(.*)$", _env, _re.M)
    _url = (_m.group(1).strip().strip('"') if _m else "") or _inbox.DEFAULT_URL
    if _inbox._fetch(_url) is None:
        bad.append(f"待办通道取不到：{_url}（服务用的就是这个地址；.env 的 ARK_INBOX_URL 是不是指着已删掉的文件？）")
    else:
        print(f"  ✓ 待办通道能取到：{_url}")
except Exception as _exc:  # noqa: BLE001
    bad.append(f"待办通道检查本身出错：{type(_exc).__name__}: {_exc}")

if bad:
    print("SMOKE_FAIL")
    for b in bad:
        print("  " + b)
    sys.exit(1)
print("SMOKE_OK")
