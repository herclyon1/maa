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
mods = sorted(p.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
              for p in (ROOT / "ark_relay").rglob("*.py")
              if "okww_files" not in p.parts and p.name != "__init__.py")
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:   # noqa: BLE001 - 冒烟就是要接住所有导入失败
        bad.append(f"import {m} 失败：{type(e).__name__}: {e}")
print(f"SMOKE 导入 {len(mods)} 个模块，失败 {sum(1 for b in bad if b.startswith('import'))} 个")

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

if bad:
    print("SMOKE_FAIL")
    for b in bad:
        print("  " + b)
    sys.exit(1)
print("SMOKE_OK")
