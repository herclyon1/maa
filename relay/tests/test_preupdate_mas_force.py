"""AUTO-MAS 查更新必须带 if_force，否则下载地址是过期的一次性令牌。

2026-08-29 查实：AUTO-MAS 从 08-27 起反复打「开始下载」却始终装不上，
版本一直停在 v5.4.0。真因不在 CDK（CDK 有效，版本检查一直是成功的），
在于两件事凑一起：

* `app/services/update.py:178-184` 把检查结果缓存四小时；
* MirrorChyan 的下载地址是**一次性令牌**，随检查响应带回来存进
  `mirror_chyan_download_url`，下载时直接用它。

于是走缓存 = 拿早就过期的令牌去下载 → 三次重试全 404 → 更新包一个字节都不落地
→ 中继在 `_wait_for_package` 里干等 600 秒超时。日志里只有「开始下载」，
没有任何失败行，看上去像网络慢，其实压根没在下。

机器上实测：不强制 → 404；`if_force=True` → 换到新令牌，状态码 200。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import preupdate_automas as P  # run_automas 住在这个模块里，猴子补丁要打在它身上

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def main() -> int:
    calls = []

    def fake_post(path, body=None):
        calls.append((path, dict(body or {})))
        if path == "/api/update/check":
            return {"if_need_update": False, "latest_version": "v5.4.0"}
        return {}

    orig_post, orig_ver, orig_live = P._mas_post, P._automas_version, P._live_version
    P._mas_post = fake_post
    P._automas_version = lambda _root: "v5.4.0"
    P._live_version = lambda: ""
    try:
        P.run_automas(Path("."), budget_s=1)
    finally:
        P._mas_post, P._automas_version, P._live_version = orig_post, orig_ver, orig_live

    checks = [b for p, b in calls if p == "/api/update/check"]
    print("=== 查更新的调用 ===")
    for c in checks:
        print("  ", c)
    check("确实调了 /api/update/check", bool(checks), True)
    check("带了当前版本号",
          all(c.get("current_version") == "v5.4.0" for c in checks), True)
    check("带了 if_force=True（不带就会拿到过期令牌）",
          all(c.get("if_force") is True for c in checks), True)

    # res/version.json is stale since the Electron build; the backend's own
    # /api/core/health answer must be what the update check is asked with.
    calls.clear()
    P._mas_post, P._automas_version, P._live_version = fake_post, (lambda _root: "v5.5.0-beta.2"), (lambda: "v5.5.0-beta.4")
    try:
        P.run_automas(Path("."), budget_s=1)
    finally:
        P._mas_post, P._automas_version, P._live_version = orig_post, orig_ver, orig_live
    checks = [b for p, b in calls if p == "/api/update/check"]
    check("后端自报的版本压过 res/version.json 里的旧值",
          bool(checks) and all(c.get("current_version") == "v5.5.0-beta.4" for c in checks), True)
    # And when the backend cannot be asked, the file value still goes out.
    P._live_version = lambda: ""
    calls.clear()
    P._mas_post, P._automas_version = fake_post, (lambda _root: "v5.5.0-beta.2")
    try:
        P.run_automas(Path("."), budget_s=1)
    finally:
        P._mas_post, P._automas_version, P._live_version = orig_post, orig_ver, orig_live
    checks = [b for p, b in calls if p == "/api/update/check"]
    check("问不到后端时退回文件里的版本号",
          bool(checks) and all(c.get("current_version") == "v5.5.0-beta.2" for c in checks), True)

    # The install path must end with a verdict: the backend came back on the new
    # version (note says 已更新) or it did not (a problem is recorded).
    def post_with_update(path, body=None):
        calls.append((path, dict(body or {})))
        if path == "/api/update/check":
            return {"if_need_update": True, "latest_version": "v5.5.0-beta.4"}
        return {}
    orig_pack, orig_wait = P._wait_for_package, P._wait_for_version
    P._mas_post, P._automas_version = post_with_update, (lambda _root: "v5.5.0-beta.2")
    P._live_version = lambda: "v5.5.0-beta.2"
    P._wait_for_package = lambda _root, _deadline: Path("UpdatePack_v5.5.0-beta.4.zip")
    P._wait_for_version = lambda want, deadline: want
    problems = []
    note = P.run_automas(Path("."), budget_s=1, problems=problems)
    check("装成后通知说「已更新」", "已更新" in note and not problems, True)
    P._wait_for_version = lambda want, deadline: "v5.5.0-beta.2"
    try:
        problems = []
        note = P.run_automas(Path("."), budget_s=1, problems=problems)
    finally:
        P._mas_post, P._automas_version, P._live_version = orig_post, orig_ver, orig_live
        P._wait_for_package, P._wait_for_version = orig_pack, orig_wait
    check("没确认装成时记为未确认项", bool(problems) and "还没确认" in note, True)

    print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
