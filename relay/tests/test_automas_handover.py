"""relay/handover/automas_handover.py against a fake AUTO-MAS at the HTTP layer.

Only `urllib.request.urlopen` is replaced. The config shapes are the ones the
handover reads on the machine (BOARD/新中继-重叠可撤核对.md, values read
2026-10-11 02:45-02:55 Beijing): MAA user Info.Annihilation "Close",
Info.IfQuickConfig true, Info.Server "Official"; MAA script
Run.IfCheckGameUpdate / Run.IfAutoInstallGameApk false; Start.IfSelfStart true.
Endpoints and bodies as relay/ark_relay/commands.py and annihilation.py use them
(every endpoint POST; /api/scripts/update {"scriptId","data"},
/api/scripts/user/update {"scriptId","userId","data"}); /api/setting/get and
/update {"data"} as AUTO-MAS app/api/setting.py (v5.7.0 line, 699de5a).
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "handover"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
os.environ["ARK_MAS_PORT"] = "36163"
import automas_handover as H

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


MAA, END, OKWW, UID = "s-maa", "s-end", "s-okww", "u-1"


def merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        else:
            dst[k] = v


class Backend:
    """mode: "up" | "down" (connection refused) | "running" (updates answer
    code 500 「正在运行, 无法更新配置项」, the message commands._refused cites)."""

    def __init__(self, mode="up", annihilation="Close", quick=True, server="Official", selfstart=True):
        self.mode = mode
        self.calls = []
        self.scripts = {
            MAA: {"Info": {"Name": "MAA"}, "Run": {"IfCheckGameUpdate": False, "IfAutoInstallGameApk": False,
                                                  "HardTimeLimit": 120}},
            END: {"Info": {"Name": "MaaEnd"}, "Run": {"HardTimeLimit": 120}},
            OKWW: {"Info": {"Name": "OK-WW"}, "Run": {"HardTimeLimit": 120, "RunTimeLimit": 120},
                   "Game": {"Enabled": False, "Path": "", "IfAutoUpdate": True}},
        }
        self.users = {
            MAA: {UID: {"Info": {"Annihilation": annihilation, "IfQuickConfig": quick, "Server": server,
                                 "AnnihilationStartWeekday": "Monday"},
                        "Data": {"AnnihilationCompletedWeek": "2026-W41"}}},
            END: {UID: {"Info": {}}},
            OKWW: {UID: {"Info": {}}},
        }
        self.setting = {"Start": {"IfSelfStart": selfstart}}

    def urlopen(self, req, timeout=None):
        path = req.full_url[len("http://127.0.0.1:36163"):]
        body = json.loads((req.data or b"{}").decode())
        self.calls.append((path, body))
        if self.mode == "down":
            raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        if path.endswith("/update") and self.mode == "running":
            return _Resp({"code": 500, "status": "error", "message": "正在运行, 无法更新配置项"})
        if path == "/api/scripts/get":
            return _Resp({"code": 200, "data": self.scripts})
        if path == "/api/scripts/user/get":
            return _Resp({"code": 200, "data": self.users[body["scriptId"]]})
        if path == "/api/setting/get":
            return _Resp({"code": 200, "data": self.setting})
        if path == "/api/scripts/update":
            merge(self.scripts[body["scriptId"]], body["data"])
            return _Resp({"code": 200})
        if path == "/api/scripts/user/update":
            merge(self.users[body["scriptId"]][body["userId"]], body["data"])
            return _Resp({"code": 200})
        if path == "/api/setting/update":
            merge(self.setting, body["data"])
            return _Resp({"code": 200})
        raise AssertionError(f"endpoint not prepared by this test: {path}")

    def updates(self):
        return [p for p, _ in self.calls if p.endswith("/update")]


class _Resp:
    def __init__(self, obj):
        self._raw = json.dumps(obj, ensure_ascii=False).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_real = urllib.request.urlopen


def run(be, *argv):
    urllib.request.urlopen = be.urlopen
    out = io.StringIO()
    old, sys.stdout = sys.stdout, out
    try:
        code = H.main(list(argv))
    finally:
        sys.stdout = old
    return code, out.getvalue()


try:
    with tmpdir() as d:
        state = Path(d) / "state"
        state.mkdir()
        (state / "state.json").write_text(json.dumps(
            {"weekly": {"annihilation": {"done_week": "2026-W41", "restore_to": "Chernobog@Annihilation"}}}),
            encoding="utf-8")
        sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]

        print("plan reads only")
        be = Backend()
        code, out = run(be, "plan", *sd)
        check("plan exit 0", code, 0)
        check("plan sends no update", be.updates(), [])
        check("plan shows the annihilation map it would restore",
              "'Close' -> 'Chernobog@Annihilation'" in out, True)
        check("plan prints the hard limit fact", "Run.HardTimeLimit = 120" in out, True)

        print("apply changes, reads back, saves the old values")
        code, out = run(be, "apply", *sd)
        check("apply exit 0", code, 0)
        check("annihilation restored to the saved map",
              be.users[MAA][UID]["Info"]["Annihilation"], "Chernobog@Annihilation")
        check("arknights client update on", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], True)
        check("arknights apk install on", be.scripts[MAA]["Run"]["IfAutoInstallGameApk"], True)
        check("wuwa untouched without --with-wuwa-update", be.scripts[OKWW]["Game"]["Enabled"], False)
        saved = json.loads((state / H.BACKUP_FILE).read_text(encoding="utf-8"))["old"]
        check("old annihilation value saved", saved.get("user:MAA:Info.Annihilation"), "Close")
        check("old update switch saved", saved.get("script:MAA:Run.IfCheckGameUpdate"), False)

        print("apply again is a no-op and keeps the first old values")
        n = len(be.updates())
        code, _ = run(be, "apply", *sd)
        check("second apply exit 0", code, 0)
        check("second apply sends no update", len(be.updates()), n)
        saved2 = json.loads((state / H.BACKUP_FILE).read_text(encoding="utf-8"))["old"]
        check("backup still holds the pre-handover values", saved2, saved)

        print("rollback puts exactly the old values back")
        code, out = run(be, "rollback", "--state-dir", str(state))
        check("rollback exit 0", code, 0)
        check("annihilation back to Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
        check("update switch back off", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], False)
        check("backup removed after a full rollback", (state / H.BACKUP_FILE).exists(), False)

    with tmpdir() as d:
        state = Path(d)
        sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]

        print("no saved map: AUTO-MAS's own default")
        be = Backend()
        code, _ = run(be, "apply", *sd)
        check("restored to the default map", be.users[MAA][UID]["Info"]["Annihilation"], "Annihilation")

        print("quick config off: annihilation is not handed over")
        be = Backend(quick=False)
        code, out = run(be, "apply", *sd)
        check("exit 1", code, 1)
        check("annihilation left Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
        check("says why", "Info.IfQuickConfig" in out, True)

        print("not the official server: client update not handed over")
        be = Backend(server="Bilibili")
        code, out = run(be, "apply", *sd)
        check("exit 1", code, 1)
        check("update switch left off", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], False)

        print("a task running: the backend refuses, nothing reported as done")
        be = Backend(mode="running")
        code, out = run(be, "apply", *sd)
        check("exit 1", code, 1)
        check("refusal reported", "正在运行" in out, True)

        print("backend down")
        be = Backend(mode="down")
        code, out = run(be, "apply", *sd)
        check("exit 2", code, 2)

        print("self start off is switched on")
        be = Backend(selfstart=False)
        code, _ = run(be, "apply", *sd)
        check("IfSelfStart true", be.setting["Start"]["IfSelfStart"], True)

        print("--with-wuwa-update without a launcher: refuses, does not enable")
        be = Backend()
        code, out = run(be, "apply", "--with-wuwa-update", *sd)
        check("exit 1", code, 1)
        check("Game.Enabled still off", be.scripts[OKWW]["Game"]["Enabled"], False)
        check("says the launcher was not found", "launcher.exe not found" in out, True)

        print("--with-wuwa-update with the launcher next to the game folder")
        game = Path(d) / "Wuthering Waves Game" / "Wuthering Waves.exe"
        game.parent.mkdir()
        game.write_text("")
        launcher = Path(d) / "Wuthering Waves" / "launcher.exe"
        launcher.parent.mkdir()
        launcher.write_text("")
        cfg = Path(d) / "okww" / "data" / "apps" / "ok-ww" / "working" / "configs"
        cfg.mkdir(parents=True)
        (cfg / "Game.json").write_text(json.dumps({"path": str(game)}), encoding="utf-8")
        be = Backend()
        code, out = run(be, "apply", "--with-wuwa-update", *sd)
        check("exit 0", code, 0)
        check("launcher path set", be.scripts[OKWW]["Game"]["Path"], str(launcher))
        check("game start handed over", be.scripts[OKWW]["Game"]["Enabled"], True)
finally:
    urllib.request.urlopen = _real

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
