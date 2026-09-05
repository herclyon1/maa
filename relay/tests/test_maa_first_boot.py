"""MAA 刚更新过之后的第一次启动会跳过更新检查，别把它当成故障。

2026-09-05：昨天手动把 MAA 从 v6.17.0 升到 v6.17.1，今早 08:46:07 预更新
启动它，日志里 `IsFirstBoot has been set: `true` -> `false``，
**整段一次 mirrorchyan 请求都没有** —— 那句 `current version is latest`
永远等不到，中继白等满 180 秒，再报一条「预更新没能确认」的假警报。
同一天 09:00:50 那次启动 IsFirstBoot 已是 false，09:00:56 就正常问了，
所以更新并不会漏掉，只是晚十几分钟。

判据要认出首次启动这行，并且**不能误伤**正常那条 latest。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay.preupdate import _MAA_FIRST_BOOT, _MAA_LATEST  # noqa: E402

fails = []

# 09-05 08:46 那次的原文（首次启动，没有任何更新检查）
first_boot = (
    "[2026-09-05 08:46:07.382][INF][Bootstrapper]           <2> Version v6.17.1\n"
    "[2026-09-05 08:46:12.977][INF][ConfigurationHelper]    <2> Configuration "
    "Root.Update..IsFirstBoot has been set: `true` -> `false`, save scheduled\n"
)
if not _MAA_FIRST_BOOT.search(first_boot):
    fails.append("认不出首次启动那行，还是会白等满 180 秒")
if _MAA_LATEST.search(first_boot):
    fails.append("首次启动的日志里不该匹配到 latest")

# 09-05 09:00 那次的原文（正常检查，答了已是最新）
normal = (
    "[2026-09-05 09:00:56.097][INF][HttpResponseLoggingExtension] <2> HTTP: OK GET "
    "https://mirrorchyan.com/api/resources/MAA/latest null null 250.595ms\n"
    "[2026-09-05 09:00:56.138][INF][VersionUpdateDialogViewModel] <2> MirrorChyan "
    'response: {"code":0,"msg":"current version is latest","data":{}}\n'
)
if not _MAA_LATEST.search(normal):
    fails.append("正常的『已是最新』判据被带坏了")
if _MAA_FIRST_BOOT.search(normal):
    fails.append("正常启动被误判成首次启动")

# 反引号是这条日志的一部分，别写成普通引号
if not _MAA_FIRST_BOOT.search("IsFirstBoot has been set: `true` -> `false`"):
    fails.append("反引号形式匹配不上")
if _MAA_FIRST_BOOT.search("IsFirstBoot has been set: `false` -> `true`"):
    fails.append("方向反了也匹配，判据太松")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
