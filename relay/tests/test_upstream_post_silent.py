"""upstream-post.py must tell "the repo has no template" from "gh failed".

Silent-failure audit rows scripts/mac/upstream-post.py:60 and :76: any gh
failure on the ISSUE_TEMPLATE listing or on PULL_REQUEST_TEMPLATE.md read as
"the repo has none". The empty result was written to _parsed.json (which
UPSTREAM_POST_OFFLINE reuses) and `lint <repo> - <draft>` then passed a draft
against no template at all. A real 404 still means "none"; anything else has
to stop the gate and leave the cache alone.
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay" / "tests"))
from _tmp import tmpdir  # noqa: E402

spec = importlib.util.spec_from_file_location("upstream_post", ROOT / "scripts" / "mac" / "upstream-post.py")
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)
os.environ.pop("UPSTREAM_POST_OFFLINE", None)

REPO = "owner/repo"
NOT_FOUND = "gh: Not Found (HTTP 404)\n"
SEEDED = {"bug.md": {"kind": "md", "title": "[Bug]", "labels": [], "fields": [["复现步骤", True]],
                     "route": "issue", "notes": []}}

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def fake_gh(issue_list_err, pr_err):
    """gh that fails the two template reads with the given stderr; issue search returns nothing."""
    def gh(*args):
        path = args[1] if len(args) > 1 else ""
        if path.endswith("/ISSUE_TEMPLATE") and issue_list_err:
            raise subprocess.CalledProcessError(1, ["gh", *args], output="", stderr=issue_list_err)
        if path.endswith("PULL_REQUEST_TEMPLATE.md") and pr_err:
            raise subprocess.CalledProcessError(1, ["gh", *args], output="", stderr=pr_err)
        if "/issues?" in path:
            return ""
        raise AssertionError(f"unexpected gh call {args}")
    return gh


def run(argv, issue_list_err, pr_err):
    d = tmpdir()
    up.CACHE = d / "cache"
    cached = up.CACHE / REPO.replace("/", "__") / "_parsed.json"
    cached.parent.mkdir(parents=True)
    cached.write_text(json.dumps(SEEDED, ensure_ascii=False), encoding="utf-8")
    before = cached.read_bytes()
    draft = d / "draft.md"
    draft.write_text("# 一个标题\n正文一句话。\n", encoding="utf-8")
    up._gh = fake_gh(issue_list_err, pr_err)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = up.main([a if a != "DRAFT" else str(draft) for a in argv])
    return rc, out.getvalue(), cached.read_bytes() == before, cached


print("[a real 404 on both still means: the repo has no templates]")
rc, out, same, cached = run(["lint", REPO, "-", "DRAFT"], NOT_FOUND, NOT_FOUND)
check("lint with - passes", rc, 0)
check("the cache now says no templates", json.loads(cached.read_text(encoding="utf-8")), {})

print("[the issue template listing fails for another reason]")
rc, out, same, _ = run(["lint", REPO, "-", "DRAFT"], "error connecting to api.github.com\n", NOT_FOUND)
check("lint refuses (non-zero)", rc != 0, True)
check("the gh error is printed", "error connecting to api.github.com" in out, True)
check("the cached templates are untouched", same, True)

print("[the PR template read fails for another reason]")
rc, out, same, _ = run(["rules", REPO], NOT_FOUND, "HTTP 502: Bad Gateway\n")
check("rules exits non-zero", rc != 0, True)
check("the gh error is printed", "HTTP 502" in out, True)
check("the cached templates are untouched", same, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
