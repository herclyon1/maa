"""app_main.AppHost has every attribute the code it runs reads off it.

2026-10-11: 971a1a27 made service.main call self._stop_in_boot, which AppHost did not
borrow; the installed relay died at every start with "'AppHost' object has no attribute
'_stop_in_boot'" and every switch-over went back to the old relay (cloud run
38094295924). Read from the source (pywin32 is not on the Mac).

Review round 8 #24: the first version of this test read only the borrowed methods'
own `self.xxx`. The host also travels as an argument - service.main passes it to
service._loop(svc, ...) and boot_stages._stage_inbox_and_phone(svc, ...), which hands it
on to _start_phone_channel; app_main gives it to two threads - and a `svc.xxx` there
that AppHost lacks fails the same way. The walk below follows the host through those
calls (a plain or module-qualified call, or threading.Thread(target=f, args=(...)))
into any function of app_main, service or boot_stages, as deep as it goes.
"""
import ast
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
MODULES = ("app_main", "service", "boot_stages")

fails = []


def require(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def cls(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise SystemExit(f"FAIL no class {name}")


def host_has(tree: ast.Module) -> "tuple[set[str], dict[str, str]]":
    """What AppHost defines, and which ArkRelayService methods it borrows (name -> source)."""
    host = cls(tree, "AppHost")
    has = {t.id for n in host.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    has |= {n.name for n in host.body if isinstance(n, ast.FunctionDef)}
    has |= {n.attr for n in ast.walk(host) if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
            and isinstance(n.value, ast.Name) and n.value.id == "self"}
    borrowed = {t.id: n.value.attr for n in host.body if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)
                and isinstance(n.value, ast.Attribute) and isinstance(n.value.value, ast.Attribute)
                and n.value.value.attr == "ArkRelayService"}
    return has, borrowed


def _params(fn) -> "list[str]":
    return [a.arg for a in fn.args.posonlyargs + fn.args.args]


def _is(node, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def walk_host(trees: "dict[str, ast.Module]") -> "tuple[dict[str, str], set[str], set[str]]":
    """Every attribute read off the host, with the call path that reaches it; every one
    stored on it; and the functions the walk went through."""
    funcs = {m: {n.name: n for n in t.body if isinstance(n, ast.FunctionDef)} for m, t in trees.items()}
    methods = {n.name: n for n in cls(trees["service"], "ArkRelayService").body
               if isinstance(n, ast.FunctionDef)}
    has, borrowed = host_has(trees["app_main"])
    used: "dict[str, str]" = {}
    stored: "set[str]" = set()
    seen: "set[tuple]" = set()

    def callee(mod: str, ref) -> "tuple[str, ast.FunctionDef] | None":
        if isinstance(ref, ast.Name) and ref.id in funcs[mod]:
            return mod, funcs[mod][ref.id]
        if (isinstance(ref, ast.Attribute) and isinstance(ref.value, ast.Name)
                and ref.value.id in funcs and ref.attr in funcs[ref.value.id]):
            return ref.value.id, funcs[ref.value.id][ref.attr]
        return None

    def visit(mod: str, fn, param: str, path: str) -> None:
        if (mod, fn.name, param) in seen:
            return
        seen.add((mod, fn.name, param))
        for n in ast.walk(fn):
            if isinstance(n, ast.Attribute) and _is(n.value, param):
                if isinstance(n.ctx, ast.Store):
                    stored.add(n.attr)
                else:
                    used.setdefault(n.attr, path)
            if not isinstance(n, ast.Call):
                continue
            # host.method(...): a borrowed service method runs with self = the host.
            if (isinstance(n.func, ast.Attribute) and _is(n.func.value, param)
                    and borrowed.get(n.func.attr) in methods):
                src = borrowed[n.func.attr]
                visit("service", methods[src], "self", f"{path} > {src}")
            # f(..., host, ...) / mod.f(..., host, ...)
            hit = callee(mod, n.func)
            if hit:
                cmod, cfn = hit
                names = _params(cfn)
                for i, a in enumerate(n.args):
                    if _is(a, param) and i < len(names):
                        visit(cmod, cfn, names[i], f"{path} > {cmod}.{cfn.name}")
                for kw in n.keywords:
                    if _is(kw.value, param) and kw.arg:
                        visit(cmod, cfn, kw.arg, f"{path} > {cmod}.{cfn.name}")
            # threading.Thread(target=f, args=(..., host, ...))
            kws = {kw.arg: kw.value for kw in n.keywords}
            target = callee(mod, kws.get("target"))
            if target and isinstance(kws.get("args"), ast.Tuple):
                cmod, cfn = target
                names = _params(cfn)
                for i, a in enumerate(kws["args"].elts):
                    if _is(a, param) and i < len(names):
                        visit(cmod, cfn, names[i], f"{path} > thread {cmod}.{cfn.name}")

    for name, src in sorted(borrowed.items()):
        if src in methods:                         # not a class attribute such as _svc_name_
            visit("service", methods[src], "self", f"AppHost.{name}")
    # Where app_main makes the host: `host = _host_class()()`.
    for fn in funcs["app_main"].values():
        if any(isinstance(n, ast.Assign) and any(_is(t, "host") for t in n.targets) for n in ast.walk(fn)):
            visit("app_main", fn, "host", f"app_main.{fn.name}")
    return used, stored, {f"{m}.{f}" for m, f, _ in seen}


def missing(trees) -> "dict[str, str]":
    has, _ = host_has(trees["app_main"])
    used, stored, _ = walk_host(trees)
    return {a: p for a, p in used.items() if a not in has and a not in stored}


def parse() -> "dict[str, ast.Module]":
    return {m: ast.parse((RELAY / f"{m}.py").read_text(encoding="utf-8")) for m in MODULES}


def plant(trees, mod: str, fn: str, param: str, attr: str):
    """A read of `<param>.<attr>` at the top of mod.fn, in a fresh copy of the trees."""
    out = parse()
    for n in ast.walk(out[mod]):                 # module functions and methods alike
        if isinstance(n, ast.FunctionDef) and n.name == fn:
            n.body.insert(0, ast.Expr(ast.Attribute(ast.Name(param, ast.Load()), attr, ast.Load())))
            return out
    raise SystemExit(f"FAIL no {mod}.{fn}")


def borrowed_only(trees) -> "set[str]":
    """The first version's reading: the borrowed methods' own self.xxx, nothing else."""
    has, borrowed = host_has(trees["app_main"])
    methods = {n.name: n for n in cls(trees["service"], "ArkRelayService").body
               if isinstance(n, ast.FunctionDef)}
    used = {n.attr for src in borrowed.values() if src in methods for n in ast.walk(methods[src])
            if isinstance(n, ast.Attribute) and _is(n.value, "self")}
    return used - has


trees = parse()

print("[the real AppHost covers everything the host reaches]")
_, _, reached = walk_host(trees)
for fn in ("service.main", "service._loop", "boot_stages._stage_inbox_and_phone",
           "boot_stages._start_phone_channel", "app_main._end_session_window", "app_main._stop_requests"):
    require(f"walk reaches {fn}", fn in reached)
gaps = missing(trees)
require("AppHost lacks nothing", not gaps, "; ".join(f"{a} (via {p})" for a, p in sorted(gaps.items())))
has, borrowed = host_has(trees["app_main"])
require("AppHost borrows ArkRelayService.main (else this test reads the wrong thing)", "main" in borrowed)

print("[a host attribute AppHost lacks is caught wherever the host travels]")
for mod, fn, param in (("service", "_loop", "svc"),
                       ("boot_stages", "_start_phone_channel", "svc"),
                       ("app_main", "_stop_requests", "host"),
                       ("service", "main", "self")):
    planted = plant(trees, mod, fn, param, "_not_on_host")
    got = missing(planted)
    require(f"{mod}.{fn}: {param}._not_on_host is reported", "_not_on_host" in got,
          got.get("_not_on_host", "not reported"))

print("[971a1a27's own case: AppHost without _stop_in_boot]")
t = parse()
host = cls(t["app_main"], "AppHost")
host.body = [n for n in host.body if not (isinstance(n, ast.Assign) and any(_is(x, "_stop_in_boot") for x in n.targets))]
got = missing(t)
require("_stop_in_boot is reported", "_stop_in_boot" in got, got.get("_stop_in_boot", "not reported"))

print("[the first version missed the round-8 case: service._loop(svc) reading svc.xxx]")
require("borrowed-methods-only reading misses it",
      "_not_on_host" not in borrowed_only(plant(trees, "service", "_loop", "svc", "_not_on_host")))

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
