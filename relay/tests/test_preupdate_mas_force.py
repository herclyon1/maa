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

from ark_relay import preupdate as P  # noqa: E402

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

    orig_post, orig_ver = P._mas_post, P._automas_version
    P._mas_post = fake_post
    P._automas_version = lambda _root: "v5.4.0"
    try:
        P.run_automas(Path("."), budget_s=1)
    finally:
        P._mas_post, P._automas_version = orig_post, orig_ver

    checks = [b for p, b in calls if p == "/api/update/check"]
    print("=== 查更新的调用 ===")
    for c in checks:
        print("  ", c)
    check("确实调了 /api/update/check", bool(checks), True)
    check("带了当前版本号",
          all(c.get("current_version") == "v5.4.0" for c in checks), True)
    check("带了 if_force=True（不带就会拿到过期令牌）",
          all(c.get("if_force") is True for c in checks), True)

    print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
