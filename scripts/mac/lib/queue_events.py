"""只吐「上次之后」的新事件。状态存机器上，不重复刷屏。"""
import json, re, subprocess, sys, urllib.request
from pathlib import Path

# 必须用 winrun.sh --py 调这个脚本，不能用 winps.sh：
# winps 走 936(GBK) 控制台，UTF-8 中文会被二次编码成「杩涚▼」这种乱码
# （2026-08-28 实测，监视器整整瞎了一轮）。winrun 有干净的字节通道。
# ▶ ✅ 这类字符仍要强制 UTF-8，否则 print 直接抛 UnicodeEncodeError。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STATE = Path(r"C:\ProgramData\ark-queue-watch.json")
FILES = {"MAA": r"D:\ark\maa\debug\gui.log",
         "OK-WW": r"D:\ark\okww\data\apps\ok-ww\working\logs\ok-script.log"}
KEEP = re.compile(r"开始任务|完成任务|任务出错|已停止|停止任务|理智不足|体力不足|"
                  r"指定点位|Daily Task Completed|not enough stamina|"
                  r"Traceback|Failed|失败|超时|异常|连接失败|error")
NOISE = re.compile(r"GameDataReportService|HttpResponseLogging|penguin-stats|yituliu|"
                   r"ConfigurationHelper|TaskQueueViewModel]     <\d> Index")

def load():
    try: return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception: return {}

def procs():
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace").stdout
    s = {l.split('","')[0].lstrip('"') for l in out.splitlines() if l}
    return sorted(p for p in s if any(k in p for k in
        ("MaaEnd.exe", "Endfield.exe", "ok-ww.exe", "MAA.exe", "MuMuPlayer", "Client-Win64")))

st = load(); out = []
now = procs()
if st.get("procs") != now:
    out.append(f"[进程] {'、'.join(now) or '（都没在跑）'}")
    st["procs"] = now

for name, path in FILES.items():
    p = Path(path)
    if not p.is_file():
        continue
    size = p.stat().st_size
    prev = int(st.get(f"pos_{name}") or 0)
    if size < prev:
        prev = 0
    if size > prev:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(prev); chunk = f.read()
        for line in chunk.splitlines():
            if KEEP.search(line) and not NOISE.search(line):
                out.append(f"[{name}] {line.strip()[:160]}")
    st[f"pos_{name}"] = size

# MaaEnd 走 MXU 的人话日志（maafw.log 全是 trace，没法看）
try:
    raw = urllib.request.urlopen("http://127.0.0.1:12701/api/logs", timeout=10).read().decode()
    d = json.loads(raw)
    rows = d if isinstance(d, list) else sum((v for v in d.values() if isinstance(v, list)), [])
    seen = set(st.get("mxu_ids") or [])
    strip = lambda h: re.sub(r"<[^>]+>", "", str(h)).replace("\n", " ").strip()
    fresh = []
    for r in rows:
        rid = r.get("id")
        if rid in seen:
            continue
        seen.add(rid)
        m = strip(r.get("message", ""))
        if not m:
            continue
        if re.search(r"未匹配到目标技能组合|已确认上锁|初始化完成", m):
            continue
        fresh.append(f"[MaaEnd] {m[:170]}")
    if fresh:
        out += fresh[-15:]
    st["mxu_ids"] = list(seen)[-4000:]
except Exception:
    pass

STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
for l in out[-20:]:
    print(l)
