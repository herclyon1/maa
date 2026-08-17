"""Server mode: the 7x24 half.

This is the only place that can answer "the machine never woke up", because it
is the only part that keeps running while the game box is powered off.

Endpoints
    POST /api/event           采集端上报一次运行结果
    POST /api/heartbeat       采集端心跳（开机期间每 N 秒一次）
    GET  /api/commands        采集端拉取待执行指令
    POST /api/command-result  采集端回报执行结果
    GET  /api/status          给网页看的状态
    POST /api/say             人话进来 -> 解析成指令 -> 等确认
    POST /api/confirm         确认某条待确认指令
    GET  /                    PWA 页面
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta

from .config import SERVER_TZ, Config, both_clocks
from .core import State, format_missing, stale_seconds
from .engine import Engine
from .notify import Notifier
from .transport import QueueSource, payload_to_record

log = logging.getLogger("ark.server")

# How long without a heartbeat before we consider the machine down, while it
# is supposed to be awake. Generous: a run can pin the CPU for a while.
HEARTBEAT_GRACE = timedelta(minutes=12)


class Hub:
    """Shared mutable state for the web layer and the watchdog."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.source = QueueSource()
        self.state = State(cfg.state_dir)
        self.notifier = Notifier(cfg)
        self.engine = Engine(cfg, self.source, self.state, self.notifier)
        self.last_heartbeat: datetime | None = None
        self.pending: dict[str, dict] = {}   # 待确认
        self.queued: list[dict] = []         # 已确认，等机器上线
        self.results: list[dict] = []        # 最近的执行回报
        self.alerted: set[str] = set()       # 每个窗口只告警一次

    # ---- expectations: when the machine should be alive ----

    def windows(self, now: datetime) -> list[tuple[str, datetime, datetime]]:
        """(名称, 应开机时间, 应完成时间) on the server clock."""
        d = now.astimezone(SERVER_TZ).replace(second=0, microsecond=0)
        def at(h: int, m: int) -> datetime:
            return d.replace(hour=h, minute=m)
        return [
            ("早上那轮", at(8, 45), at(10, 40)),
            ("晚上那轮", at(21, 20), at(22, 30)),
        ]

    async def watchdog(self) -> None:
        """The alert only an off-machine relay can produce."""
        while True:
            try:
                now = datetime.now(tz=SERVER_TZ)
                for name, wake, done in self.windows(now):
                    key = f"{now:%Y-%m-%d}/{name}"
                    if key in self.alerted:
                        continue
                    # Only judge once the wake window has clearly passed.
                    if now < wake + HEARTBEAT_GRACE:
                        continue
                    if now > done:
                        continue
                    if stale_seconds(self.last_heartbeat, now) > HEARTBEAT_GRACE.total_seconds():
                        last = (both_clocks(self.last_heartbeat)
                                if self.last_heartbeat else "从未收到")
                        title, body = format_missing(
                            f"{name}：机器没起来", wake,
                            f"最后一次心跳：{last}\n"
                            "可能原因：插座没通电 / BIOS 唤醒失效 / 没进桌面 / 采集端没启动",
                        )
                        self.notifier.send(title, body)
                        self.alerted.add(key)
                        log.warning("已告警: %s", key)
                self.engine.tick()
            except Exception:  # noqa: BLE001 - watchdog must never die
                log.exception("watchdog 本轮出错")
            await asyncio.sleep(self._next_wake_seconds())

    def _next_wake_seconds(self, cap: float = 3600.0) -> float:
        """Sleep to the next judgment moment instead of a fixed minute beat.

        The watchdog's only clock-based decisions are "did the machine wake up
        by wake+grace" for each window, plus whatever moments the engine
        enumerates itself. Each has an exact time; there is nothing a fixed
        60-second wake could notice that these alarms do not.
        """
        now = datetime.now(tz=SERVER_TZ)
        moments: list[datetime] = []
        try:
            for base in (now, now + timedelta(days=1)):
                for name, wake, done in self.windows(base):
                    key = f"{base:%Y-%m-%d}/{name}"
                    judge = wake + HEARTBEAT_GRACE
                    if key not in self.alerted and now < judge <= done:
                        moments.append(judge)
            if alarm := self.engine.next_deadline(now):
                moments.append(alarm[0])
        except Exception:  # noqa: BLE001 - a broken alarm degrades into lateness
            log.exception("计算下一个时刻出错，退回备用间隔")
            return 60.0
        if not moments:
            return cap
        return max(1.0, min((min(moments) - now).total_seconds() + 1, cap))


def _parse_intent(cfg: Config, text: str) -> dict:
    """人话 -> 白名单动作. Returns {} when nothing safe could be extracted."""
    from . import summary  # noqa: PLC0415

    prompt = (
        "把下面这句中文指令翻译成一个 JSON 对象，只能从这些动作里选：\n"
        '  {"action":"set_stage","value":"关卡号"}      改刷哪一关\n'
        '  {"action":"set_medicine","value":整数}        理智药上限\n'
        '  {"action":"run_now","queue":"队列名"}         立刻跑一轮\n'
        '  {"action":"skip_today","queue":"队列名"}      今天跳过\n'
        "如果这句话不属于以上任何一种，返回 {}。\n"
        "只输出 JSON，不要解释、不要代码块。\n\n"
        f"指令：{text}"
    )
    raw = summary._ask(cfg, prompt, max_tokens=200).strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) and obj.get("action") else {}


def build_app(cfg: Config):  # noqa: C901 - a flat router reads better than helpers
    from fastapi import FastAPI, Request  # noqa: PLC0415
    from fastapi.responses import HTMLResponse, JSONResponse  # noqa: PLC0415

    hub = Hub(cfg)
    app = FastAPI(title="ark-relay")

    @app.on_event("startup")
    async def _start() -> None:
        asyncio.create_task(hub.watchdog())
        log.info("中继已启动，推送渠道：%s", "、".join(hub.notifier.channels) or "(无)")

    @app.post("/api/heartbeat")
    async def heartbeat() -> dict:
        hub.last_heartbeat = datetime.now(tz=SERVER_TZ)
        return {"ok": True}

    @app.post("/api/event")
    async def event(req: Request) -> dict:
        payload = await req.json()
        try:
            rec = payload_to_record(payload)
        except (KeyError, ValueError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        if tail := payload.get("log_tail"):
            hub.engine.log_tails[rec.run_id] = str(tail)
        hub.source.offer(rec)
        hub.engine.tick()
        return {"ok": True}

    @app.get("/api/commands")
    async def commands() -> dict:
        out, hub.queued = hub.queued, []
        return {"commands": out}

    @app.post("/api/command-result")
    async def command_result(req: Request) -> dict:
        body = await req.json()
        body["at"] = datetime.now(tz=SERVER_TZ).isoformat()
        hub.results.insert(0, body)
        del hub.results[20:]
        mark = "✅" if body.get("ok") else "❌"
        hub.notifier.send(f"{mark} 指令执行回报", str(body.get("detail") or ""))
        return {"ok": True}

    @app.post("/api/say")
    async def say(req: Request) -> dict:
        text = str((await req.json()).get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "空指令"}
        intent = _parse_intent(cfg, text)
        if not intent:
            return {"ok": False, "error": "没看懂，或者这件事超出了我能改的范围"}
        from .commands import MUTATING  # noqa: PLC0415
        cid = uuid.uuid4().hex[:8]
        intent["id"] = cid
        if intent["action"] in MUTATING:
            hub.pending[cid] = intent          # gate ②: wait for a human
            return {"ok": True, "need_confirm": True, "command": intent}
        intent["confirmed"] = True             # reversible: straight through
        hub.queued.append(intent)
        return {"ok": True, "need_confirm": False, "command": intent}

    @app.post("/api/confirm")
    async def confirm(req: Request) -> dict:
        cid = str((await req.json()).get("id") or "")
        cmd = hub.pending.pop(cid, None)
        if not cmd:
            return {"ok": False, "error": "没有这条待确认指令"}
        cmd["confirmed"] = True
        hub.queued.append(cmd)
        return {"ok": True, "command": cmd}

    @app.get("/api/status")
    async def status() -> dict:
        now = datetime.now(tz=SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        alive = stale_seconds(hub.last_heartbeat, now) <= HEARTBEAT_GRACE.total_seconds()
        return {
            "now": now.isoformat(),
            "machine_alive": alive,
            "last_heartbeat": hub.last_heartbeat.isoformat() if hub.last_heartbeat else None,
            "today": hub.state.read_ledger(day),
            "pending": list(hub.pending.values()),
            "queued": hub.queued,
            "results": hub.results,
            "channels": hub.notifier.channels,
        }

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _PAGE

    return app


# A single self-contained page: add to home screen on iOS/Android and it
# behaves like an app. One codebase covers Android, iOS, Windows and macOS.
_PAGE = """<!doctype html>
<html lang="zh"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>方舟中继</title>
<style>
  :root{--bg:#f6f7f9;--card:#fff;--fg:#1a1a1a;--dim:#888;--ok:#1a8a3f;--bad:#c8342b;--line:#e3e6ea}
  @media(prefers-color-scheme:dark){:root{--bg:#14161a;--card:#1e2228;--fg:#e8eaed;--dim:#9aa0a6;--line:#2c313a}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:16px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
       padding:16px;max-width:680px;margin:0 auto}
  h1{font-size:20px;margin:8px 0 16px}
  .card{background:var(--card);border-radius:12px;padding:14px 16px;margin-bottom:12px}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px}
  .up{background:var(--ok)} .down{background:var(--bad)}
  .dim{color:var(--dim);font-size:14px}
  .row{display:flex;gap:8px}
  input{flex:1;padding:11px 13px;border:1px solid var(--line);border-radius:9px;
        background:var(--card);color:var(--fg);font-size:16px}
  button{padding:11px 16px;border:0;border-radius:9px;background:#2f6fed;color:#fff;
         font-size:15px;cursor:pointer}
  button.ghost{background:transparent;color:var(--dim);border:1px solid var(--line)}
  .run{border-top:1px solid var(--line);padding-top:9px;margin-top:9px;font-size:14.5px}
  .run:first-child{border:0;padding-top:0;margin-top:0}
</style></head><body>
<h1>方舟中继</h1>
<div class="card" id="machine">读取中…</div>
<div class="card">
  <div class="row">
    <input id="say" placeholder="说人话，比如「今天换 CE-6」" autocomplete="off">
    <button onclick="say()">发送</button>
  </div>
  <div id="reply" class="dim" style="margin-top:9px"></div>
</div>
<div class="card"><b>今天</b><div id="today" class="dim">读取中…</div></div>
<script>
const $ = id => document.getElementById(id);
let pendingId = null;

async function load(){
  try{
    const s = await (await fetch('/api/status')).json();
    $('machine').innerHTML =
      `<span class="dot ${s.machine_alive?'up':'down'}"></span>`
      + (s.machine_alive ? '机器在线' : '机器不在线')
      + `<div class="dim">最后心跳 ${s.last_heartbeat ? new Date(s.last_heartbeat).toLocaleString('zh-CN') : '从未收到'}`
      + `<br>推送渠道 ${s.channels.join('、') || '无'}</div>`;
    $('today').innerHTML = s.today.length ? s.today.map(e =>
      `<div class="run">${e.ok?'✅':'❌'} ${e.script}
       ${new Date(e.started).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}
       → ${new Date(e.finished).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}
       ${e.ok?'':'<br>失败：'+(e.failed_tasks||[]).join('、')}</div>`).join('')
      : '还没有运行记录';
  }catch(err){ $('machine').textContent = '连不上中继：' + err; }
}

async function say(){
  const text = $('say').value.trim(); if(!text) return;
  $('reply').textContent = '解析中…';
  const r = await (await fetch('/api/say',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({text})})).json();
  if(!r.ok){ $('reply').textContent = '✗ ' + r.error; return; }
  $('say').value = '';
  if(r.need_confirm){
    pendingId = r.command.id;
    $('reply').innerHTML = `要执行：<b>${r.command.action}</b> `
      + `${r.command.value ?? r.command.queue ?? ''}<br>`
      + `<button onclick="confirmCmd()" style="margin-top:8px">确认</button> `
      + `<button class="ghost" onclick="pendingId=null;reply.textContent='已取消'">取消</button>`;
  } else {
    $('reply').textContent = '✅ 已入队，机器上线后执行';
  }
}

async function confirmCmd(){
  const r = await (await fetch('/api/confirm',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({id:pendingId})})).json();
  $('reply').textContent = r.ok ? '✅ 已确认，机器上线后执行' : ('✗ ' + r.error);
  pendingId = null;
}

$('say').addEventListener('keydown', e => { if(e.key === 'Enter') say(); });
load(); setInterval(load, 30000);
</script></body></html>"""
