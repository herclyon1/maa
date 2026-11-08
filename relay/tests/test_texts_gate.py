"""The texts gate; and the wording.

One part per former file, each run on its own (tests/_parts.py): test_texts_gate.py, test_texts_wording.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_main():  # noqa: C901 - the whole body of the file this part was
    """通知文案的闸门：标题只能来自 texts.py，文案必须是人话、不模糊。

用户 2026-09-07：「你写进通知的任何东西都要是人话」「描述模糊是第一大禁止」。

    Formerly test_texts_gate.py.
    """
    import re

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.core import texts
    from ark_relay.features.verify import collector_okww
    from ark_relay.features.weekly import garden, annihilation, weeklyboss
    from ark_relay.core import ledger as core


    print("[texts.py 里每一句都是人话]")
    for s in texts.samples():
        check(s[:40], texts.plain(s), [])

    print("[texts.py 里每一个常量也都是人话：不只是 samples() 列到的（审查 10-13 s1 #6）]")
    # EVIDENCE_NOT_SHIPPED said 「relay.log」 in group alarm bodies, and the gate never
    # saw it because samples() did not list it. Every module-level string, and every
    # string inside a module-level tuple / list / set / dict, is checked here; only the
    # word lists the checker itself uses are left out.
    _WORD_LISTS = {"VAGUE", "JARGON", "ALLOWED_WORDS", "_THEIR_TERMS"}
    _const_bad, _const_n = [], 0
    for _name, _val in vars(texts).items():
        if _name.startswith("__") or _name in _WORD_LISTS:
            continue
        if isinstance(_val, str):
            _vals = [_val]
        elif isinstance(_val, (tuple, list, set, frozenset)):
            _vals = [x for x in _val if isinstance(x, str)]
        elif isinstance(_val, dict):
            _vals = [x for x in _val.values() if isinstance(x, str)]
        else:
            continue
        for _v in _vals:
            _const_n += 1
            if texts.plain(_v):
                _const_bad.append(f"{_name}: {_v[:30]!r} {texts.plain(_v)}")
    check("每个常量都过 plain()", _const_bad, [])
    check("确实扫到了很多常量（至少 150）", _const_n >= 150, True)

    print("[中继里每个记日志的部分在报错推送里都有名字（审查 10-13 s1 #8）]")
    # A WARNING from a logger missing in _RELAY_PARTS was pushed as 「出在「一个不常见的部分」」.
    _loggers = set()
    for _f in sorted((ROOT / "ark_relay").rglob("*.py")) + [ROOT / "service.py", ROOT / "boot_stages.py"]:
        if "okww_files" in _f.parts:
            continue                            # runs inside OK-WW, not in the relay
        _loggers |= set(re.findall(r"""getLogger\(\s*["'](ark(?:\.[\w.]+)?)["']""", _f.read_text(encoding="utf-8")))
    check("扫到了很多记日志的部分（至少 40）", len(_loggers) >= 40, True)
    check("每一个都有名字", sorted(_loggers - set(texts._RELAY_PARTS)), [])

    print("[各处中文对照表也是人话]")
    for table in (core._KIND_NOTE.values(), collector_okww._OKWW_TASK_ZH.values(),
                  collector_okww._OKWW_EXC_ZH.values(), (zh for _, zh in collector_okww._OKWW_MSG_ZH),
                  (garden.GardenGate.NAME, annihilation.WeeklyGate.NAME, weeklyboss.WeeklyBossGate.NAME)):
        for s in table:
            check(s[:40], texts.plain(s), [])

    print("[每个模块里所有会送到人眼前的中文句子都过 plain()：不只是 texts.py]")
    # The user, 2026-09-12: 「你不是有工具在拦截吗，搞毛呢？」 - a hedged sentence sat in
    # core.py, which this gate never read. Now every Chinese string literal in every
    # module is checked, except log calls (they are for me) and docstrings.
    import ast
    _HAN = re.compile(r"[\u4e00-\u9fff]")
    def _user_facing_literals(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = set()
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("info", "warning", "error", "exception", "debug", "critical")):
                for c in ast.walk(n):
                    skip.add(id(c))
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
                skip.add(id(n.value))          # docstrings
        for n in ast.walk(tree):
            if id(n) in skip or not isinstance(n, ast.Constant) or not isinstance(n.value, str):
                continue
            if _HAN.search(n.value):
                yield n.lineno, n.value
    _HEDGE_ONLY = [v for v in texts.VAGUE if v not in ("未知错误", "这一步", "有问题", "出错")] + list(texts.JARGON)
    vague_hits = []
    _scanned_literals = 0
    for f in sorted([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files", "machinechecks"} & set(p.parts)]) + [ROOT / "service.py", ROOT / "boot_stages.py"]:
        if f.name == "summary.py":
            continue                            # the model prompt, abandoned path; not a notification
        for ln, val in _user_facing_literals(f):
            _scanned_literals += 1
            if f.name == "texts.py" and (val in texts.VAGUE or val in texts.JARGON):
                continue                        # the word lists themselves
            if f.name in ("statestore.py", "desktop.py"):
                continue                        # state-file field docs / an embedded PowerShell script, never sent
            for term in texts._THEIR_TERMS:
                val = val.replace(term, " ")
            for v in _HEDGE_ONLY:
                if v in val:
                    vague_hits.append(f"{f.name}:{ln} 「{v}」 {val[:50]!r}")
    check("没有一句含糊话或术语（多半/可能/疑似/约…、落盘/回读/字段/进程…）", vague_hits, [])
    check("确实扫到了很多句子（至少 300）", _scanned_literals >= 300, True)

    print("[代码里不许再出现写死的通知标题]")
    bad = []
    pat = re.compile(r"notifier\.send(?:_group)?\(\s*f?\"")
    for f in list([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files", "machinechecks"} & set(p.parts)]) + [ROOT / "service.py", ROOT / "boot_stages.py"]:
        if f.name == "texts.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line) and not line.strip().startswith("#"):
                bad.append(f"{f.name}:{i}: {line.strip()[:80]}")
    check("写死的标题为零", bad, [])
    # 地板：glob 扫到 0 个文件也会「零违规」，闸门成摆设。2026-09-08 回放测试栽过一次。
    _scanned = len(list([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files", "machinechecks"} & set(p.parts)])) + 2
    check("确实扫到了文件（至少 20 个）", _scanned >= 20, True)

    print("[plain() 本身认得出问题]")
    check("英文类名", texts.plain("FarmEchoTask 抛 WaitFailedException"), ["英文「FarmEchoTask」", "英文「WaitFailedException」"])
    check("模糊词", texts.plain("周本：这一步出错"), ["模糊词「这一步」", "模糊词「出错」"])
    check("产品名放行", texts.plain("MaaEnd 已更新：v2.28.0-beta.1 → v2.28.0-beta.2"), [])
    check("文件路径放行（他要看到是哪个文件）", texts.plain("只更新了反作弊组件，文件位于 AntiCheatExpert\\pld.dat"), [])


def _part_texts_wording():
    """Copy that said more than the code does (review 2026-10-13, s1).

Each block pins one sentence against the code it describes; the reason is in the
block's header.

    Formerly test_texts_wording.py.
    """
    import ast

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.core import texts

    # automas_keeper imports win32api at module level, so read its constants from source.
    _KEEPER = ast.parse((ROOT / "ark_relay/features/host/automas_keeper.py").read_text(encoding="utf-8"))
    KEEPER = {t.id: n.value.value for n in _KEEPER.body if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}


    print("[AUTO-MAS 开机没起来：重拉的间隔写的是翻倍，不是每 3 分钟（s1 #9）]")
    # automas_keeper: the first wait is REVIVE_FIRST_WAIT (180 s), then it doubles up to
    # REVIVE_MAX_WAIT; relay.log 08-22 23:12:56 -> 23:16:06 -> 23:22:16 shows the doubling.
    body = texts.automas_boot_down_body()
    check("第一次等 3 分钟（代码里也是 180 秒）", (KEEPER["REVIVE_FIRST_WAIT"], "3 分钟后" in body), (180, True))
    check("说了之后翻倍", "翻倍" in body, True)
    check("不再说每 3 分钟", "每 3 分钟" in body, False)
    check("连拉几次再报，和代码一致", f"连拉 {KEEPER['REVIVE_ALERT_AFTER']} 次" in body, True)

    print("\n[中继报错推送的结尾不再说「这不代表脚本没跑」（s1 #10）]")
    # relay.log 2026-10-10 16:14:14: the push for 「开机自检 ✗ 调度程序的后台程序在跑」 (AUTO-MAS
    # backend down, so the shift cannot run) ended with 「这不代表脚本没跑…」.
    body = texts.relay_error_body("ark.selfcheck", "开机自检 ✗ 调度程序的后台程序在跑", "16:14")
    check("结尾不打包票说脚本照跑", "不代表脚本没跑" in body, False)
    check("仍说交给我们修", body.endswith("已交给我们这边去修。"), True)

    print("\n[MaaEnd 卡死：有插件没结束掉时不说「插件都结束了」（s1 #11）]")
    # maaend_watchdog._end skips a plugin outside the agent directory and only logs a
    # WARNING when its taskkill fails; the push must name what is still running.
    try:
        body = texts.maaend_stuck_body(texts.maaend_plugin_gone_reason(60), True, "", ["agent\\go-service.exe"])
    except TypeError as e:
        body = f"TypeError: {e}"
    check("不说插件都结束了", "和它还开着的插件" in body, False)
    check("点名没结束的插件", "agent\\go-service.exe" in body and "没结束掉" in body, True)
    body = texts.maaend_stuck_body(texts.maaend_plugin_gone_reason(60), True, "")
    check("全结束时照旧", "已结束 MaaEnd 和它还开着的插件" in body, True)

    print("\n[证据包推送：只剩 COS 下载页一种写法（s1 cosmetic）]")
    # evidence.uploaders() returns COS alone and handle.py passes no other uploader, so the
    # 「已作为文件发到企业微信」 branches could never be reached.
    src = Path(texts.__file__).read_text(encoding="utf-8")
    check("没有发到企业微信的死分支", "已作为文件发到" in src, False)
    check("下载页照写", texts.evidence_saved_body("MaaEnd", "09-11 10:18", 3, "https://x/i.html").endswith("下载页：https://x/i.html"), True)

    print("\n[NOTIFICATIONS.md 每条终末地标题都有一行，写的是代码里的标题（s1 cosmetic）]")
    doc = (ROOT.parent / "docs" / "NOTIFICATIONS.md").read_text(encoding="utf-8")
    for name in ("MAAEND_MIGRATED", "MAAEND_WATCH_BLIND"):
        check(f"{name} 有一行", f"\n| {getattr(texts, name)} | " in doc, True)

    print("\n[开机自检报警不再一律说「这一班跑不了」（s1 cosmetic）]")
    body = texts.selfcheck_failed_body(11, [("调度程序的开机任务计划还在", "退出码 1")])
    check("不一口咬定这一班跑不了", "后果：这一班跑不了" in body, False)
    check("分轻重说", "重的" in body and "轻的" in body, True)


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_texts_wording]))
