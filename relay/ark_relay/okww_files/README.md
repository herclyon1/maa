# 这个目录里是上游 OK-WW 的源码

两份文件都来自 [ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves)，
**许可证是 AGPL-3.0**，版权归上游作者。

| 文件 | 是什么 |
|---|---|
| `NightmareNestTask.upstream.py` | 上游原样的那一份，作参照用。补丁贴之前先和它比对 |
| `NightmareNestTask.patched.py` | 我们改过的那一份，中继按哈希把它整个换上去 |

为什么整文件替换而不是打补丁：这个任务要改的地方太散，逐处替换的补丁在上游
一改就贴不上，而且贴不上是静默的。改了什么、为什么，见
[../../../docs/OKWW-PATCHES.md](../../../docs/OKWW-PATCHES.md)。

改动同样受 AGPL-3.0 约束。本仓库其余部分的许可见根目录 [LICENSE](../../../LICENSE)。
