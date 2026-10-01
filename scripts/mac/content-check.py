#!/usr/bin/env python3
"""Content assertions for the phone remote page, run in headless Chrome through the whole-page walk's runner (数据 10-01).

    scripts/mac/content-check.py <BASE_URL> <out_prefix>
    e.g. scripts/mac/content-check.py http://127.0.0.1:9318/ /tmp/cc/r-now

BASE_URL serves a web/ tree (index.html at its root) — serve it with scripts/mac/serve.py (backlog 256), not `python3 -m http.server`
(backlog 5: under a parallel walk the page's connections are reset and a script never runs). The script:
  1. reads the expectation from THIS repo, never from the tree under test (an old tree's schema.js and relay table are stale together):
     relay/ark_relay/wuwa_tacet.py TACET -> window.__ccExpect = {tacet: [[[set1, set2], index], ...]};
  2. writes one injection file: that expectation + a prelude (window.__sw with every key sweep-chrome.py merges, error capture, and the
     outbound fetch / XHR / sendBeacon block of sweep.js 11-27, so nothing reaches the real relay) + content-check.js + an epilogue that
     runs window.__contentCheck, stores it in window.__sw.content and sets done;
  3. runs ~/Money/styl-work/remote-ref/tools/sweep/sweep-chrome.py on it (SWEEP_JS, SHARDS=1, SCHEME=light, CDP port env CC_CDP_PORT,
     default 9319) under `timeout 300`;
  4. reads shards[0].sw.content from <out_prefix>.json (sweep-chrome.py merges only its fixed keys into the top-level sw; each shard's raw
     window.__sw is kept whole) and prints one line per assertion.
Exit 0 all green, 1 any red, 2 the walk did not produce results.
"""
import importlib.util, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SWEEP = os.path.expanduser("~/Money/styl-work/remote-ref/tools/sweep/sweep-chrome.py")

PRELUDE = r"""
(() => {
  const R = window.__sw = { running: true, started: Date.now(), steps: [], errors: [], net: [], clipped: {}, offscreen: {}, overlap: {},
    selectable: {}, stuck: [], log: [], done: false, maxGap: 0, content: null };
  const here = location.origin;
  addEventListener("error", (e) => R.errors.push({ at: "content", msg: String(e.message || e.error), src: (e.filename || "").split("/").pop() + ":" + e.lineno }));
  addEventListener("unhandledrejection", (e) => R.errors.push({ at: "content", msg: "rejection: " + String(e.reason && (e.reason.stack || e.reason.message) || e.reason).slice(0, 300) }));
  const f0 = window.fetch;
  window.fetch = (u, o) => { const abs = new URL(String(u && u.url || u), location.href);
    if (abs.origin !== here) { R.net.push({ at: "content", url: abs.origin + abs.pathname, m: (o && o.method) || "GET" }); return Promise.resolve(new Response("{}", { status: 200 })); }
    return f0(u, o); };
  const xo = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, u, ...r) { const abs = new URL(u, location.href);
    if (abs.origin !== here) { R.net.push({ at: "content", url: abs.origin + abs.pathname, m, xhr: 1 }); u = here + "/__blocked"; } return xo.call(this, m, u, ...r); };
  if (navigator.sendBeacon) { const sb = navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = (u, d) => { const abs = new URL(u, location.href); if (abs.origin !== here) { R.net.push({ at: "content", url: abs.origin + abs.pathname, beacon: 1 }); return true; } return sb(u, d); }; }
})();
"""

EPILOGUE = r"""
(async () => {
  const R = window.__sw;
  try {
    R.content = await window.__contentCheck(window.__ccExpect);
    R.log.push({ at: "content", msg: "content " + R.content.ms + " ms: " + R.content.results.map((r) => r.id + " " + (r.pass ? "green" : "red")).join(", ") });
  } catch (e) { R.fatal = String(e && e.stack || e); }
  finally { R.running = false; R.ms = Date.now() - R.started; R.done = true; }
})();
"""


def expectation():
    """TACET of the current repo's relay table, as the page's TACET shape: [[[set1, set2], index], ...] by index."""
    path = os.path.join(REPO, "relay", "ark_relay", "wuwa_tacet.py")
    spec = importlib.util.spec_from_file_location("wuwa_tacet_current", path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return {"tacet": [[list(sets), i] for i, (_name, sets) in sorted(mod.TACET.items())]}


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip().split("\n\n")[1]); return 2
    base, out = sys.argv[1], sys.argv[2]
    if not base.endswith("/"): base += "/"
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    exp = expectation()
    js = open(os.path.join(HERE, "content-check.js"), encoding="utf-8").read()
    inj = f"window.__ccExpect = {json.dumps(exp, ensure_ascii=False)};\n{PRELUDE}\n{js}\n{EPILOGUE}"
    fd, tmp = tempfile.mkstemp(prefix="content-check-", suffix=".js"); os.close(fd)
    open(tmp, "w", encoding="utf-8").write(inj)
    env = dict(os.environ, SWEEP_JS=tmp, SHARDS="1", SCHEME="light", BASE=base, PORT=os.environ.get("CC_CDP_PORT", "9319"),
               MODE="sweep", NATIVE="0", GESTURES="0")
    t0 = time.time()
    try:
        p = subprocess.run(["timeout", "300", sys.executable, SWEEP, out, "280"], env=env, capture_output=True, text=True)
    finally:
        os.unlink(tmp)
    wall = time.time() - t0
    try:
        res = json.load(open(out + ".json", encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"no result file ({e!r}); sweep-chrome exit {p.returncode}: {(p.stdout + p.stderr).strip()[-600:]}"); return 2
    sh = (res.get("shards") or [{}])[0]
    sw = sh.get("sw") or {}
    c = sw.get("content")
    if not c or not c.get("results"):
        print(f"no content results; sweep-chrome exit {p.returncode}; aborts {res.get('aborts')}; fatal {sw.get('fatal')}"); return 2
    red = 0
    for r in c["results"]:
        red += not r["pass"]
        print(f"{'GREEN' if r['pass'] else 'RED  '} {r['id']} ({r['ms']} ms)\n  got:  {r['got']}\n  want: {r['want']}")
    rs = c.get("restored") or {}
    print(f"page state put back: {'yes' if rs.get('ok') else 'NO ' + '; '.join(rs.get('changed') or [])}")
    extra = {"version": res.get("version"), "errors": len(sw.get("errors") or []), "net": len(sw.get("net") or []),
             "dialogs": len(res.get("dialogs") or []), "cdp_exceptions": len(res.get("cdp_exceptions") or [])}
    print(f"content {c['ms']} ms · walk {sh.get('elapsed_s')} s after injection · total {wall:.1f} s · {len(c['results']) - red} green {red} red · {json.dumps(extra, ensure_ascii=False)}")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
