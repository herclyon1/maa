"""selfupdate.py 的四扇门、粘性、拒绝旧清单、对不上哈希就一个字节都不落盘。

这个文件防的损失只有一种，但它是最难发现的一种：**推上去的修复到不了机器，
而屏幕上一片绿**。中继自己不会喊「我没更新成」，日志照常打「已更新 N 个文件」，
人在另一个国家，只能等下一次事故才发现机器还在跑旧代码。

具体钉四件事：

* **四扇门的顺序**（fastly → cdn → gcore → raw）。2026-08-21 在机器上量过 8 轮：
  fastly 8/8 平均 426ms，raw 2/8 平均 38 秒。顺序被人「顺手整理」一下，
  开机那 8 分钟的窗口就全耗在最慢的门上，更新赶不上 09:00 的队列。
* **粘性**：上次哪扇门成了，下次先问它。raw 整晚整晚地黑（08-17、08-20 各一次），
  没有粘性的话，一次多文件更新的每个文件都要先在死门上耗满超时。
* **拿到的清单比本机旧就必须拒绝**。2026-08-21 出过一次：CDN 缓存着上一版的
  「旧清单 + 旧 .py」，两者自洽、哈希也对得上，机器被静默降级回旧代码，
  日志写着「已更新 1 个文件」，一切正常。判据不许写成 `remote and local and ...`
  ——没有版本号的旧清单 remote_ver 是 0，那种写法会直接放行。
* **哈希对不上，一个字节都不许落盘**。半个更新比不更新危险得多：service.py
  一看到文件变了就重启，于是重启进一个「新 engine.py + 旧 core.py」的中继。

全程不联网：`_get_once` 被换成假的，重试之间的等待也跳过。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import selfupdate as su
from ark_relay.statestore import StateStore
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}（要 {want!r}）" if not ok
          else f"  ✓ {label}")
    if not ok:
        fails.append(label)


BASE = "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"
FASTLY, CDN, GCORE, RAW = ("fastly.jsdelivr.net", "cdn.jsdelivr.net",
                           "gcore.jsdelivr.net", "raw.githubusercontent.com")


class _NoSleep:
    """重试之间的等待与测试无关，跳过它；单调时钟保持真的，预算判断还要用。"""

    monotonic = staticmethod(time.monotonic)

    @staticmethod
    def sleep(_seconds):
        return None


su.time = _NoSleep


class Net:
    """假网络。doors: {域名: {文件相对路径: bytes}}；没有的键就是这扇门取不到。"""

    def __init__(self, doors):
        self.doors = doors
        self.tried = []

    def get(self, url, timeout=20):
        host = su._netloc(url)
        rel = url.split("/relay/", 1)[-1]
        self.tried.append((host, rel))
        return self.doors.get(host, {}).get(rel)

    @property
    def hosts(self):
        return [h for h, _ in self.tried]


def use(net):
    su._get_once = net.get
    su._last_good = ""          # 每个用例从「没有粘性」开始
    return net


def manifest(version, files):
    return json.dumps({"version": version, "files": files}).encode("utf-8")


def workdir(files, code_version=""):
    """一台机器：root 下摆好现有文件，state 里记好本机代码版本。"""
    root = tmpdir()
    (root / "state").mkdir()
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    if code_version:
        StateStore(root / "state").set("versions", "code", str(code_version))
    return root


# ------------------------------------------------------------------ 门的顺序

print("[四扇门的顺序：fastly → cdn → gcore → raw，raw 永远垫底]")
alts = su._alternates(BASE + "manifest.json")
check("四扇门都在", len(alts), 4)
check("顺序", [su._netloc(u) for u in alts], [FASTLY, CDN, GCORE, RAW])
check("jsDelivr 走的是同一个仓库同一个分支", alts[0],
      "https://fastly.jsdelivr.net/gh/herclyon1/maa@main/relay/manifest.json")
check("raw 原样保留在最后", alts[-1], BASE + "manifest.json")

print("\n[不是 raw.githubusercontent 的地址，不许自作主张换门]")
check("别的域名原样返回", su._alternates("https://example.com/relay/a.py"),
      ["https://example.com/relay/a.py"])
check("raw 但路径不成形（没有 owner/repo/branch/path）",
      su._alternates("https://raw.githubusercontent.com/herclyon1/maa"),
      ["https://raw.githubusercontent.com/herclyon1/maa"])

print("\n[_netloc：取主机名，取不到就原样返回，任何输入都不许抛异常]")
check("普通地址", su._netloc("https://fastly.jsdelivr.net/gh/a/b@c/d.py"), FASTLY)
check("raw", su._netloc(BASE + "a.py"), RAW)
check("没有主机名就返回原串", su._netloc("这不是地址"), "这不是地址")
check("空串", su._netloc(""), "")


# -------------------------------------------------------------------- 粘性

print("\n[粘性：上次哪扇门成了，下次先问它]")
body = b"print('new')\n"
sha = su._sha1(body)
net = use(Net({GCORE: {"a.py": body}}))     # 只有 gcore 有货
got = su._get_with_retry(BASE + "a.py", expect_sha=sha)
check("第三扇门拿到了", got, body)
check("按顺序一扇扇试过来", net.hosts[:3], [FASTLY, CDN, GCORE])
check("记住了这扇门", su._last_good, GCORE)

net = Net({GCORE: {"a.py": body}, FASTLY: {"a.py": body}})
su._get_once = net.get                       # 不清粘性：这次要先问 gcore
su._get_with_retry(BASE + "a.py", expect_sha=sha)
check("下一个文件先问上次成的那扇门", net.hosts[0], GCORE)
check("一扇就够了，没白等前两扇", len(net.tried), 1)

print("\n[粘的那扇门黑了，其余三扇还是要试——粘性不许变成独门]")
net = Net({RAW: {"a.py": body}})
su._get_once = net.get                       # 粘的还是 gcore，但 gcore 这次没货
check("最后还是拿到了", su._get_with_retry(BASE + "a.py", expect_sha=sha), body)
check("四扇门一扇不落", sorted(set(net.hosts[:4])), sorted([FASTLY, CDN, GCORE, RAW]))
check("粘性改判到真正成的那扇", su._last_good, RAW)


# ------------------------------------------------------- 缓存发旧副本换下一扇门

print("\n[某扇门发的是旧副本：换下一扇，不是整轮放弃]")
old = b"print('old')\n"
net = use(Net({FASTLY: {"a.py": old}, CDN: {"a.py": old},
               GCORE: {"a.py": old}, RAW: {"a.py": body}}))
check("最终拿到的是对得上哈希的那份", su._get_with_retry(BASE + "a.py", expect_sha=sha), body)
check("四扇门都问过", net.hosts[:4], [FASTLY, CDN, GCORE, RAW])

print("\n[四扇门都只有旧副本：宁可拿不到，也不许把旧的当新的用]")
net = use(Net({h: {"a.py": old} for h in (FASTLY, CDN, GCORE, RAW)}))
check("拿不到就是拿不到", su._get_with_retry(BASE + "a.py", expect_sha=sha), None)


# --------------------------------------------------------------- 清单版本判定

print("\n[比本机旧的清单必须拒绝（2026-08-21 静默降级就是这一格）]")
check("没有版本号的旧清单也要拦（remote=0，本机有版本）", su._is_downgrade(0, 20260821110000), True)
check("确实更旧", su._is_downgrade(20260820, 20260821), True)
check("一样新就不算降级", su._is_downgrade(20260821, 20260821), False)
check("更新的当然放行", su._is_downgrade(20260822, 20260821), False)
check("本机没有版本号时不拦（全新机器要能装上）", su._is_downgrade(0, 0), False)
check("本机没有版本号、清单有", su._is_downgrade(20260821, 0), False)

print("\n[_manifest_version：读不出来算 0，这个 0 是要参与比较的]")
check("正常", su._manifest_version({"version": 20260821}), 20260821)
check("字符串数字也认", su._manifest_version({"version": "20260821"}), 20260821)
check("没有这个字段", su._manifest_version({}), 0)
check("不是数字", su._manifest_version({"version": "v2"}), 0)

print("\n[_best_manifest：挑版本号最高的那一份，绕开还没刷新的门]")
stale, fresh = manifest(20260821, {"a.py": "x"}), manifest(20260908, {"a.py": "y"})
net = use(Net({FASTLY: {"manifest.json": stale}, CDN: {"manifest.json": stale},
               GCORE: {"manifest.json": stale}, RAW: {"manifest.json": fresh}}))
m = su._best_manifest(BASE)
check("选了最新的那份", su._manifest_version(m or {}), 20260908)
check("四扇门都问了，不是谁先答用谁", len(net.tried), 4)

print("\n[有一扇门返回的不是 JSON：跳过它，不许拖垮整轮]")
net = use(Net({FASTLY: {"manifest.json": b"<html>502</html>"},
               RAW: {"manifest.json": fresh}}))
check("照样拿到清单", su._manifest_version(su._best_manifest(BASE) or {}), 20260908)

print("\n[四扇门全黑：老实说没有，不许瞎编一份]")
net = use(Net({}))
check("没有清单", su._best_manifest(BASE), None)
check("没有清单就不更新", su.check(workdir({"a.py": old}), BASE), [])


# ------------------------------------------------------------------ 整轮更新

print("\n[清单更旧：整轮拒绝，磁盘上一个字节都不动]")
root = workdir({"a.py": old}, code_version=20260908090000)
net = use(Net({h: {"manifest.json": manifest(20260821110000, {"a.py": sha}),
                   "a.py": body} for h in (FASTLY, CDN, GCORE, RAW)}))
check("不更新", su.check(root, BASE), [])
check("文件原封不动", (root / "a.py").read_bytes(), old)
check("本机版本号没被改回去",
      StateStore(root / "state").get("versions", "code"), "20260908090000")

print("\n[一切正常：文件落盘、版本号记下、留下给下一个进程播报的记号]")
root = workdir({"a.py": old}, code_version=20260821110000)
use(Net({h: {"manifest.json": manifest(20260908090000, {"a.py": sha}), "a.py": body}
         for h in (FASTLY, CDN, GCORE, RAW)}))
check("更新了 a.py", su.check(root, BASE), ["a.py"])
check("内容是新的", (root / "a.py").read_bytes(), body)
check("版本号记下了",
      StateStore(root / "state").get("versions", "code"), "20260908090000")
note = su.take_announcement(root)
check("留了播报记号", note and note["files"], ["a.py"])

print("\n[内容和清单对不上：一个字节都不许落盘，而且必须留下失败的原因]")
root = workdir({"a.py": old}, code_version=20260821110000)
use(Net({h: {"manifest.json": manifest(20260908090000, {"a.py": sha}), "a.py": old}
         for h in (FASTLY, CDN, GCORE, RAW)}))     # 四扇门发的都是旧副本
check("不更新", su.check(root, BASE), [])
check("文件原封不动", (root / "a.py").read_bytes(), old)
check("版本号不许提前记（记了下次开机就不再重试）",
      StateStore(root / "state").get("versions", "code"), "20260821110000")
f = su.take_failure(root)
check("失败被记下来了，不是静默的", bool(f), True)
check("说清了是哪个文件", f and f["files"], ["a.py"])

print("\n[两个文件只取到一个：两个都不许写——半个更新比不更新更危险]")
b_body = b"print('b new')\n"
root = workdir({"a.py": old, "b.py": old}, code_version=20260821110000)
use(Net({h: {"manifest.json": manifest(20260908090000,
                                       {"a.py": sha, "b.py": su._sha1(b_body)}),
             "a.py": body}                      # b.py 哪扇门都没有
         for h in (FASTLY, CDN, GCORE, RAW)}))
check("整轮放弃", su.check(root, BASE), [])
check("取到的那个也不许落盘", (root / "a.py").read_bytes(), old)
check("另一个当然也没动", (root / "b.py").read_bytes(), old)
check("失败报告列出了这一轮本来要改的两个文件",
      sorted((su.take_failure(root) or {}).get("files") or []), ["a.py", "b.py"])

print("\n[本机已经是新的：什么都不做，也不许把旧的失败报告留在那里吓人]")
root = workdir({"a.py": body}, code_version=20260821110000)
su._record_failure(root, "上一轮没成", 1, 2, ["a.py"])
use(Net({h: {"manifest.json": manifest(20260908090000, {"a.py": sha})}
         for h in (FASTLY, CDN, GCORE, RAW)}))
check("没有文件要改", su.check(root, BASE), [])
check("旧的失败报告清掉了", su.take_failure(root), None)
check("版本号照样记（本机确实就是这一版）",
      StateStore(root / "state").get("versions", "code"), "20260908090000")


# --------------------------------------------------------------- 清单里的路径

print("\n[清单是从网上取的：越界路径必须在结构上不可能，而不是靠信任]")
root = tmpdir()
for bad in ("../evil.py", "a/../../evil.py", "/etc/passwd", "\\windows\\system32\\x"):
    check(f"拦下 {bad}", su._safe_target(root, bad), None)
check("正常路径落在 root 里面",
      su._safe_target(root, "ark_relay/engine.py"),
      (root / "ark_relay" / "engine.py").resolve())

print("\n[越界路径走完整一轮：root 外面不许多出任何东西]")
root = workdir({"a.py": old}, code_version=20260821110000)
outside = root.parent / "evil.py"
use(Net({h: {"manifest.json": manifest(20260908090000,
                                       {"../evil.py": sha, "a.py": sha}),
             "a.py": body, "../evil.py": body}
         for h in (FASTLY, CDN, GCORE, RAW)}))
check("正常那个还是更新了", su.check(root, BASE), ["a.py"])
check("root 外面什么都没写出来", outside.exists(), False)

print("\n[清单里的新文件不许自己创建：中继能凭网上一份清单造文件，门就开得太大了]")
root = workdir({"a.py": body}, code_version=20260821110000)
use(Net({h: {"manifest.json": manifest(20260908090000,
                                       {"a.py": sha, "brand_new.py": sha}),
             "brand_new.py": body} for h in (FASTLY, CDN, GCORE, RAW)}))
check("不当成更新", su.check(root, BASE), [])
check("没有造出新文件", (root / "brand_new.py").exists(), False)

print("\n[_wanted_files：这一轮打算改哪些——失败报告要靠它说人话]")
root = workdir({"same.py": body, "diff.py": old})
check("哈希一样的不算",
      su._wanted_files(root, {"same.py": sha}), [])
check("哈希不一样的才算",
      su._wanted_files(root, {"diff.py": sha, "same.py": sha}), ["diff.py"])
check("本机没有的文件不算（它根本不会被创建）",
      su._wanted_files(root, {"nope.py": sha}), [])

# ---- A manifest file this machine does not have: abandon the round ----
# 2026-09-08: banners.py was split into five files and pushed to main. The old
# behaviour was to write the edited banners.py, skip the four new modules it
# imports, stamp the version as up to date, and restart the process - which then
# died on ModuleNotFoundError, and because the version was already stamped it
# would never try again. Half an update is far more dangerous than none.
import ark_relay.selfupdate as SU                                  # noqa: E402
from _tmp import tmpdir                                            # noqa: E402

_root = tmpdir()
(_root / "state").mkdir()          # 失败记录写在 state/ 下，机器上一直有这个目录
(_root / "old.py").write_bytes(b"x = 1\n")
_files = {"old.py": SU._sha1(b"x = 2\n"), "brand_new.py": SU._sha1(b"y = 1\n")}
_got = SU._stage_files(_root, "https://example.invalid/", _files, None, 7, 6, ["old.py"])
check("有新文件时整轮放弃", _got, None)
check("一个字节都没落盘", (_root / "old.py").read_bytes(), b"x = 1\n")
check("新文件也没被创建", (_root / "brand_new.py").exists(), False)
_fail = (SU.take_failure(_root) or {}).get("reason", "")
check("留了话说清要人工部署", "部署脚本" in _fail, True)
check("话里点名了是哪个文件", "brand_new.py" in _fail, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
