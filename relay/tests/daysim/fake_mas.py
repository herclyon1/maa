"""daysim: the AUTO-MAS backend API, in process.

Every relay call to http://127.0.0.1:<ARK_MAS_PORT>/api/... (mas_client.mas_post,
engine._automas_snapshot, redbutton, queues, snapshot, preupdate_automas) reaches
`FakeMas.handle` through fake_net. The script and setting endpoints are
scripts/ci/fake_automas.answer() (never its serve(): no ports on the shared Mac);
this adds the queue, dispatch, runtime-snapshot, health and update endpoints and
the behaviours a day replay needs (design.md section 1, seam table):

* **memory (R11).** The backend reads its config files when it starts and
  then works from memory. Here memory is a private shadow tree: copied from
  the real AUTO-MAS dir at `start()`, answered from by every read, written by
  every accepted update and then written through to the real files, as
  AUTO-MAS saves. A file the relay edits directly while the backend is up is
  never seen by the API, and the next save puts memory back over it
  (2026-09-30: "skip today" edited QueueConfig.json, the queue ran anyway).
  Each such edit is an output (`mas_write` with how="file").
* **running guard.** While a task runs, script/user updates are refused the
  way AUTO-MAS v5.6.0 refuses them (HTTP 200, code 500, 「正在运行, 无法更新配置项」;
  commands._refused); a queue or queue-item update is refused only when it
  changes `Info` of a running queue (commands._write_item_days relies on a
  Schedule-only write passing).
* **shutdown (R04/R05).** `shutdown_started()` - the World calls it when
  Windows begins to close - kills the backend: from then on every call fails
  as a refused connection (annihilation._backend_unreachable), optionally after
  `reset_s` seconds of connection resets (10-11 21:46: ConnectionReset).

The World supplies what runs: `set_tasks(...)` with runtime-snapshot tasks
({"taskId", "mode", "task_info": [{"name", "status"}]}); `dispatch/start` calls
the World's `on_dispatch(task_id, mode)` hook and is an output either way.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "ci"))
import fake_automas

UTC8 = timezone(timedelta(hours=8))
REFUSED_RUNNING = "正在运行, 无法更新配置项"
# engine._SNAPSHOT_DONE: the statuses that end a runtime-snapshot item.
DONE = {"完成", "异常", "失败", "跳过", "中止", "取消"}
CONFIG_FILES = ("ScriptConfig.json", "Config.json", "QueueConfig.json")


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC8).isoformat(timespec="seconds")


def _unfinished(task: dict) -> bool:
    info = task.get("task_info") or []
    return not info or any(str(i.get("status") or "") not in DONE for i in info)


class FakeMas:
    def __init__(self, sched, automas_dir, shadow_dir, *, version: str = "", up: bool = True,
                 on_dispatch=None):
        self.sched = sched
        self.dir = Path(automas_dir)          # what the relay reads and writes directly
        self.shadow = Path(shadow_dir)        # the backend's memory
        self.version = version
        self.on_dispatch = on_dispatch
        self.tasks: "list[dict]" = []
        self.up = False
        self.dead_at: "float | None" = None   # when Windows' shutdown killed it
        self.reset_s = 0.0
        self._disk: "dict[str, bytes]" = {}   # each config file as the backend last read or wrote it
        if up:
            self.start()

    # ---------- the backend process ----------

    def start(self) -> None:
        """The backend starts: it reads its config files into memory."""
        cfg = self.shadow / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        for name in CONFIG_FILES:
            src = self.dir / "config" / name
            if src.is_file():
                shutil.copyfile(src, cfg / name)
                self._disk[name] = src.read_bytes()
        if not (cfg / "Config.json").is_file():
            (cfg / "Config.json").write_text("{}", encoding="utf-8")
        (self.shadow / "calls.log").touch()
        self.up, self.dead_at = True, None
        self._mode()

    def stop(self) -> None:
        """The backend exits (a recorded stop, the relay's own taskkill)."""
        self.up = False

    def shutdown_started(self, reset_s: float = 0.0) -> None:
        """Windows has begun to shut down: the backend is killed with everything
        else, while the relay still runs its stop path (R04/R05)."""
        self.up = False
        self.dead_at = float(self.sched.now())
        self.reset_s = reset_s
        self._out("mas_backend", state="killed by shutdown")

    def apply_event(self, ev: dict) -> None:
        """events.jsonl kinds mas_backend {"state": up|down} and mas_config
        {"file", "data"}: a recorded config change made outside the relay."""
        kind = ev.get("kind")
        if kind == "mas_backend":
            self.start() if ev.get("state") == "up" else self.stop()
        elif kind == "mas_config":
            name = str(ev["file"])
            data = json.dumps(ev["data"], ensure_ascii=False, indent=1).encode("utf-8")
            (self.dir / "config" / name).write_bytes(data)
            self._disk[name] = data
            if self.up:
                # Made through AUTO-MAS's own window: memory has it too.
                (self.shadow / "config" / name).write_bytes(data)
        else:
            raise ValueError(f"FakeMas cannot apply {kind!r}")

    def set_tasks(self, tasks: "list[dict]") -> None:
        self.tasks = [dict(t) for t in tasks]
        self._mode()

    def memory(self, name: str = "QueueConfig.json") -> dict:
        """One config file as the backend holds it (what a timed queue runs with)."""
        return json.loads((self.shadow / "config" / name).read_text(encoding="utf-8"))

    # ---------- plumbing ----------

    def _out(self, kind: str, **f) -> None:
        self.sched.out(kind, t=iso(float(self.sched.now())), **f)

    def _mode(self) -> None:
        running = any(_unfinished(t) for t in self.tasks)
        self.shadow.mkdir(parents=True, exist_ok=True)     # before the backend's first start too
        (self.shadow / "mode.txt").write_text("running" if running else "up", encoding="utf-8")

    def _running_names(self) -> "set[str]":
        out = set()
        for t in self.tasks:
            if _unfinished(t):
                # A queue run names its queue in taskId or, as AUTO-MAS lists a queue
                # task, in mode (tests/test_estop_verifies.py: {"taskId": ..., "mode": "早班"}).
                out.add(str(t.get("taskId") or ""))
                out.add(str(t.get("mode") or ""))
                out.update(str(i.get("name") or "") for i in t.get("task_info") or []
                           if str(i.get("status") or "") not in DONE)
        return out

    def _down(self) -> None:
        if self.dead_at is not None and float(self.sched.now()) < self.dead_at + self.reset_s:
            raise ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")
        raise urllib.error.URLError(ConnectionRefusedError(
            10061, "No connection could be made because the target machine actively refused it"))

    def _check_files(self) -> None:
        """A config file that changed on disk since the backend last read or wrote
        it was edited behind its back: memory does not have it (R11)."""
        for name in CONFIG_FILES:
            f = self.dir / "config" / name
            try:
                now = f.read_bytes()
            except OSError:
                continue
            if name in self._disk and now != self._disk[name]:
                self._out("mas_write", how="file", file=name, seen_by_backend=False)
                self._disk[name] = now

    def _save(self) -> None:
        """AUTO-MAS writes memory back to its files (after an update, at a run start)."""
        self._check_files()
        for name in CONFIG_FILES:
            src = self.shadow / "config" / name
            if src.is_file():
                data = src.read_bytes()
                dst = self.dir / "config" / name
                if dst.is_file() and dst.read_bytes() != data:
                    dst.write_bytes(data)
                self._disk[name] = data

    def run_started(self) -> None:
        """A queue started: AUTO-MAS stamps it and saves memory over the files."""
        if self.up:
            self._save()

    # ---------- the API ----------

    def handle(self, method: str, path: str, body) -> dict:
        if not self.up:
            self._down()
        self._check_files()
        body = body if isinstance(body, dict) else {}
        if path == "/api/dispatch/runtime-snapshot":
            return {"code": 200, "status": "success", "tasks": json.loads(json.dumps(self.tasks))}
        if path == "/api/core/health":
            return {"code": 200, "status": "success", "version": self.version}
        if path == "/api/update/check":
            return {"code": 200, "status": "success", "if_need_update": False,
                    "latest_version": self.version}
        if path.startswith("/api/queue/"):
            return self._queue(path, body)
        if path.startswith("/api/dispatch/"):
            return self._dispatch(path, body)
        if path.startswith("/api/update/"):
            self._out("mas_write", how="api", path=path, body=body, accepted=True)
            return {"code": 200, "status": "success"}
        before = _read(self.shadow / "config" / "ScriptConfig.json")
        try:
            reply = fake_automas.answer(self.shadow, path, body)
        except (KeyError, TypeError, OSError, ValueError) as exc:
            # A body the model cannot place (an unknown scriptId, no ScriptConfig.json):
            # AUTO-MAS would answer its validation error; here it is also a sim gap.
            self._out("sim_error", what="AUTO-MAS call not answerable", path=path,
                      why=f"{type(exc).__name__}: {exc}")
            raise _http_error(path, 422) from exc
        if reply is None:
            self._out("sim_error", what="AUTO-MAS endpoint not modelled", path=path)
            raise _http_error(path, 404)
        if path.endswith("/update"):
            ok = reply.get("code") == 200
            self._out("mas_write", how="api", path=path, body=body, accepted=ok,
                      refused=reply.get("message", "") if not ok else "")
            if ok:
                self._save()
            elif _read(self.shadow / "config" / "ScriptConfig.json") != before:
                raise AssertionError("a refused update changed memory")
        return reply

    def _queues(self) -> dict:
        return self.memory("QueueConfig.json")

    def _queue(self, path: str, body: dict) -> dict:
        q = self._queues()
        if path == "/api/queue/get":
            return {"code": 200, "status": "success", "index": q.get("instances", []),
                    "data": {i["uid"]: _strip(q[i["uid"]]) for i in q.get("instances", [])}}
        qid = str(body.get("queueId") or "")
        if qid not in q:
            return {"code": 500, "status": "error", "message": f"队列 {qid} 不存在"}
        items = q[qid].setdefault("SubConfigsInfo", {}).setdefault("QueueItem", {"instances": []})
        if path == "/api/queue/item/get":
            return {"code": 200, "status": "success", "index": items.get("instances", []),
                    "data": {i["uid"]: items[i["uid"]] for i in items.get("instances", [])}}
        data = body.get("data") or {}
        if path == "/api/queue/update":
            node = q[qid]
        elif path == "/api/queue/item/update":
            iid = str(body.get("queueItemId") or "")
            if iid not in items:
                return {"code": 500, "status": "error", "message": f"队列项 {iid} 不存在"}
            node = items[iid]
        else:
            self._out("sim_error", what="AUTO-MAS endpoint not modelled", path=path)
            raise _http_error(path, 404)
        running = self._running_names()
        if "Info" in data and (qid in running or str((q[qid].get("Info") or {}).get("Name") or "") in running):
            self._out("mas_write", how="api", path=path, body=body, accepted=False, refused=REFUSED_RUNNING)
            return {"code": 500, "status": "error", "message": REFUSED_RUNNING}
        fake_automas._merge(node, data)
        (self.shadow / "config" / "QueueConfig.json").write_text(
            json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
        self._out("mas_write", how="api", path=path, body=body, accepted=True)
        self._save()
        return {"code": 200, "status": "success"}

    def _dispatch(self, path: str, body: dict) -> dict:
        tid = str(body.get("taskId") or "")
        if path == "/api/dispatch/start":
            self._out("mas_write", how="api", path=path, body=body, accepted=True)
            if self.on_dispatch is not None:
                self.on_dispatch(tid, str(body.get("mode") or ""))
            else:
                self._out("sim_note", what="dispatch/start not modelled by the World", taskId=tid)
            return {"code": 200, "status": "success", "message": "操作成功"}
        if path == "/api/dispatch/stop":
            self._out("mas_write", how="api", path=path, body=body, accepted=True)
            # A live task stops; any other id is answered 操作成功 and stops nothing
            # (redbutton._estop_stop_by_config_ids, measured 2026-09-14).
            for t in self.tasks:
                if str(t.get("taskId") or "") == tid and _unfinished(t):
                    for i in t.get("task_info") or []:
                        if str(i.get("status") or "") not in DONE:
                            i["status"] = "中止"
                    t.setdefault("task_info", [])
                    if not t["task_info"]:
                        t["task_info"].append({"name": "", "status": "中止"})
            self._mode()
            return {"code": 200, "status": "success", "message": "操作成功"}
        self._out("sim_error", what="AUTO-MAS endpoint not modelled", path=path)
        raise _http_error(path, 404)


def _strip(node: dict) -> dict:
    return {k: v for k, v in node.items() if k != "SubConfigsInfo"}


def _read(f: Path) -> bytes:
    try:
        return f.read_bytes()
    except OSError:
        return b""


def _http_error(path: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(path, code, "sim", None, io.BytesIO(b'{"detail":"sim"}'))
