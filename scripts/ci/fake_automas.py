"""A stand-in AUTO-MAS backend for the cloud switch-over test (package_switch_smoke.py).

relay/handover/automas_handover.py changes AUTO-MAS only through its backend
(POST http://127.0.0.1:<port>/api/...), so the test needs something answering there.
This serves the endpoints the handover uses, with the shapes it reads
(relay/tests/test_automas_handover.py Backend), and keeps the settings in a folder
laid out as AUTO-MAS keeps them:

    <dir>/config/ScriptConfig.json   {"instances": [{"uid": ...}], "<uid>": {"Info": ...,
                                     "Run": ..., "SubConfigsInfo": {"UserData": {"instances":
                                     [...], "<user uid>": {"Info": ..., "Data": ...}}}}}
                                     (the walk in relay/ark_relay/core/plan.py _scripts)
    <dir>/config/Config.json         the global settings (Start.IfSelfStart)

Every request is appended to <dir>/calls.log (one "path<TAB>body" line), so the test
can tell whether a step wrote anything. <dir>/mode.txt, read on every request:
"running" answers every update with AUTO-MAS's refusal while a task runs (HTTP 200,
code 500 「正在运行, 无法更新配置项」, the message relay/ark_relay commands cite);
anything else is normal. "Down" is this process not running.

    python fake_automas.py serve <dir> <port>
    python fake_automas.py seed  <dir> <json of overrides>   write a fresh config
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAA, END, OKWW, UID = "11111111-maa", "22222222-maaend", "33333333-okww", "aaaaaaaa-user"


def default_config(over: dict) -> tuple[dict, dict]:
    """(ScriptConfig.json, Config.json). `over` keys: annihilation, quick, server,
    selfstart, completed_week."""
    def user(info: dict, data: dict | None = None) -> dict:
        return {"Info": info, "Data": data or {}}

    def script(name: str, path: str, run: dict, users: dict, extra: dict | None = None) -> dict:
        node = {"Info": {"Name": name, "Path": path}, "Run": run,
                "SubConfigsInfo": {"UserData": {"instances": [{"uid": u, "type": "UserConfig"} for u in users],
                                                **users}}}
        node.update(extra or {})
        return node

    scripts = {
        "instances": [{"uid": MAA, "type": "MaaConfig"}, {"uid": END, "type": "GeneralConfig"},
                      {"uid": OKWW, "type": "GeneralConfig"}],
        MAA: script("MAA", "D:\\ark\\maa", {"IfCheckGameUpdate": False, "IfAutoInstallGameApk": False,
                                            "HardTimeLimit": 120},
                    {UID: user({"Annihilation": over.get("annihilation", "Close"),
                                "IfQuickConfig": over.get("quick", True),
                                "Server": over.get("server", "Official"),
                                "AnnihilationStartWeekday": "Monday"},
                               {"AnnihilationCompletedWeek": over.get("completed_week", "2026-W40")})}),
        END: script("MaaEnd", "D:\\ark\\maaend", {"HardTimeLimit": 120}, {UID: user({})}),
        OKWW: script("OK-WW", "D:\\ark\\okww", {"HardTimeLimit": 120, "RunTimeLimit": 120},
                     {UID: user({})}, {"Game": {"Enabled": False, "Path": "", "IfAutoUpdate": True}}),
    }
    setting = {"Start": {"IfSelfStart": over.get("selfstart", False)}}
    return scripts, setting


def seed(d: Path, over: dict) -> None:
    (d / "config").mkdir(parents=True, exist_ok=True)
    scripts, setting = default_config(over)
    _save(d, scripts, setting)
    (d / "calls.log").write_text("", encoding="utf-8")
    (d / "mode.txt").write_text("up", encoding="utf-8")


def _load(d: Path) -> tuple[dict, dict]:
    return (json.loads((d / "config" / "ScriptConfig.json").read_text(encoding="utf-8")),
            json.loads((d / "config" / "Config.json").read_text(encoding="utf-8")))


def _save(d: Path, scripts: dict, setting: dict) -> None:
    (d / "config" / "ScriptConfig.json").write_text(json.dumps(scripts, ensure_ascii=False, indent=1),
                                                    encoding="utf-8")
    (d / "config" / "Config.json").write_text(json.dumps(setting, ensure_ascii=False, indent=1),
                                              encoding="utf-8")


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


def _strip(node: dict) -> dict:
    return {k: v for k, v in node.items() if k != "SubConfigsInfo"}


def answer(d: Path, path: str, body: dict) -> dict | None:
    """The reply for one request; None = no such endpoint (HTTP 404)."""
    with (d / "calls.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{path}\t{json.dumps(body, ensure_ascii=False)}\n")
    try:
        mode = (d / "mode.txt").read_text(encoding="utf-8").strip()
    except OSError:
        mode = "up"
    if path.endswith("/update") and mode == "running":
        return {"code": 500, "status": "error", "message": "正在运行, 无法更新配置项"}
    scripts, setting = _load(d)
    if path == "/api/scripts/get":
        return {"code": 200, "data": {i["uid"]: _strip(scripts[i["uid"]]) for i in scripts["instances"]}}
    if path == "/api/scripts/user/get":
        users = scripts[body["scriptId"]]["SubConfigsInfo"]["UserData"]
        return {"code": 200, "data": {i["uid"]: users[i["uid"]] for i in users["instances"]}}
    if path == "/api/setting/get":
        return {"code": 200, "data": setting}
    if path == "/api/scripts/update":
        _merge(scripts[body["scriptId"]], body["data"])
    elif path == "/api/scripts/user/update":
        _merge(scripts[body["scriptId"]]["SubConfigsInfo"]["UserData"][body["userId"]], body["data"])
    elif path == "/api/setting/update":
        _merge(setting, body["data"])
    else:
        return None
    _save(d, scripts, setting)
    return {"code": 200, "status": "success"}


def serve(d: Path, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server's name
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                body = {}
            reply = answer(d, self.path, body)
            out = json.dumps(reply if reply is not None else {"detail": "Not Found"},
                             ensure_ascii=False).encode("utf-8")
            self.send_response(200 if reply is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a) -> None:
            pass

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    if sys.argv[1] == "serve":
        serve(Path(sys.argv[2]), int(sys.argv[3]))
    else:
        seed(Path(sys.argv[2]), json.loads(sys.argv[3]) if len(sys.argv) > 3 else {})
