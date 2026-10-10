"""Is the machine clean? A read-only check of what the package and the old relay left behind.

    python leftovers.py installed     every package item (package-items.json) is present
    python leftovers.py uninstalled   every package item is gone (data_dir only when
                                      data_kept_on_uninstall is false), and every legacy
                                      item marked remove or takeover is gone
    python leftovers.py legacy        list which legacy items (legacy-items.json) are
                                      still on this machine - the "要上机核" column

Reads only: `sc query` / `sc qfailure`, `schtasks /query`, file system, the
registry's uninstall key. Exit 0 = as expected, 1 = something unexpected,
printed one line each. Windows only; standard library only (runs on the
package's own Python and on a GitHub Windows runner).
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=60)


def service_exists(name: str) -> bool:
    return _run(["sc", "query", name]).returncode == 0


def service_restarts(name: str) -> bool:
    """`sc qfailure` lists a restart action (the text is localised; RESTART / 重新启动 / 重启动)."""
    r = _run(["sc", "qfailure", name])
    out = r.stdout.decode("utf-8", "replace") + r.stdout.decode("gbk", "replace")
    return r.returncode == 0 and any(w in out for w in ("RESTART", "重新启动", "重启动"))


def task_exists(name: str) -> bool:
    return _run(["schtasks", "/query", "/tn", name]).returncode == 0


def tasks_with_prefix(prefix: str) -> list[str]:
    r = _run(["schtasks", "/query", "/fo", "csv", "/nh"])
    names = []
    for raw in (r.stdout.decode("utf-8", "replace"), r.stdout.decode("gbk", "replace")):
        for line in raw.splitlines():
            name = line.split(",", 1)[0].strip('"').lstrip("\\")
            if name.startswith(prefix):
                names.append(name)
        if names:
            break
    return sorted(set(names))


def path_hits(path: str) -> list[str]:
    path = os.path.expandvars(path)
    if any(c in path for c in "*?["):
        return sorted(glob.glob(path))
    return [path] if os.path.exists(path) else []


def uninstall_key_exists(app_id: str) -> bool:
    import winreg  # noqa: PLC0415 - Windows only
    sub = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{{{app_id}}}_is1"
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub, 0, winreg.KEY_READ | view))
            return True
        except OSError:
            continue
    return False


def unconfirmed(pkg: dict) -> list[str]:
    """Placeholders the installer owner has not replaced yet (values starting with CONFIRM)."""
    out = []

    def walk(v, where):
        if isinstance(v, str) and v.startswith("CONFIRM"):
            out.append(where)
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{where}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{where}[{i}]")
    walk({k: v for k, v in pkg.items() if k != "about"}, "package-items")
    return out


def check_package(pkg: dict, want_present: bool) -> list[str]:
    bad = []

    def expect(what: str, present: bool):
        if present != want_present:
            bad.append(f"{what}: {'present' if present else 'missing'}, expected "
                       f"{'present' if want_present else 'gone'}")

    for svc in pkg["services"]:
        there = service_exists(svc["name"])
        expect(f"service {svc['name']}", there)
        if want_present and there and svc.get("failure_restart") and not service_restarts(svc["name"]):
            bad.append(f"service {svc['name']}: no restart-on-failure action")
    for task in pkg["tasks"]:
        expect(f"task {task}", task_exists(task))
    expect(f"install dir {pkg['install_dir']}", bool(path_hits(pkg["install_dir"])))
    if want_present or not pkg.get("data_kept_on_uninstall", True):
        expect(f"data dir {pkg['data_dir']}", bool(path_hits(pkg["data_dir"])))
    expect(f"Apps entry {pkg['app_id']}", uninstall_key_exists(pkg["app_id"]))
    return bad


def legacy_present(item: dict) -> list[str]:
    kind, name = item["kind"], item.get("name") or item.get("path") or ""
    if kind == "service":
        return [name] if service_exists(name) else []
    if kind == "task":
        return [name] if " / " not in name and task_exists(name) else []
    if kind == "task-prefix":
        return tasks_with_prefix(name)
    if kind in ("file", "dir", "glob", "software"):
        return path_hits(name)
    return []  # settings inside other programs: not checkable from here


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    if mode not in ("installed", "uninstalled", "legacy"):
        print(__doc__)
        return 2
    legacy = load("legacy-items.json")["items"]
    if mode == "legacy":
        for item in legacy:
            hits = legacy_present(item)
            mark = "present" if hits else ("not checkable here" if item["kind"] in ("other-config", "service-setting") else "gone")
            print(f"{item['action']:9} {mark:18} {item.get('name') or item.get('path')}" + (f"  {hits}" if len(hits) > 1 else ""))
        return 0
    pkg = load("package-items.json")
    if todo := unconfirmed(pkg):
        print("package-items.json still has placeholders: " + ", ".join(todo))
        return 1
    bad = check_package(pkg, want_present=(mode == "installed"))
    if mode == "uninstalled":
        for item in legacy:
            if item["action"] in ("remove", "takeover"):
                bad += [f"legacy {item['kind']} left: {h}" for h in legacy_present(item)]
    for line in bad:
        print(line)
    print("clean" if mode == "uninstalled" and not bad else ("as expected" if not bad else f"{len(bad)} unexpected"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
