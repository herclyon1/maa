"""Plain-Chinese notification wording, USER-SWITCHES verdicts, daily ledger report, and engine core."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)
# relay/ first for every part, as each part used to put it (run_parts restores sys.path after one)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _part_texts_gate_main():  # noqa: C901
    """通知文案的闸门：标题只能来自 texts.py，文案必须是人话、不模糊。"""
    import re

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.core import texts
    from ark_relay.features import outcome as collector_okww
    from ark_relay.features import annihilation as garden, annihilation, weeklyboss
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
    for f in sorted([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files", "machinechecks", "machinechecks.py"} & set(p.parts)]) + [ROOT / "service.py", ROOT / "boot_stages.py"]:
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
    for f in list([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files", "machinechecks", "machinechecks.py"} & set(p.parts)]) + [ROOT / "service.py", ROOT / "boot_stages.py"]:
        if f.name == "texts.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line) and not line.strip().startswith("#"):
                bad.append(f"{f.name}:{i}: {line.strip()[:80]}")
    check("写死的标题为零", bad, [])
    _scanned = len(list([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files", "machinechecks", "machinechecks.py"} & set(p.parts)])) + 2
    check("确实扫到了文件（至少 20 个）", _scanned >= 20, True)

    print("[plain() 本身认得出问题]")
    check("英文类名", texts.plain("FarmEchoTask 抛 WaitFailedException"), ["英文「FarmEchoTask」", "英文「WaitFailedException」"])
    check("模糊词", texts.plain("周本：这一步出错"), ["模糊词「这一步」", "模糊词「出错」"])
    check("产品名放行", texts.plain("MaaEnd 已更新：v2.28.0-beta.1 → v2.28.0-beta.2"), [])
    check("文件路径放行（他要看到是哪个文件）", texts.plain("只更新了反作弊组件，文件位于 AntiCheatExpert\\pld.dat"), [])


def _part_texts_wording():
    """Copy that said more than the code does (review 2026-10-13, s1)."""
    import ast

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.core import texts

    # automas_keeper imports win32api at module level, so read its constants from source.
    _KEEPER = ast.parse((ROOT / "ark_relay/features/automas_keeper.py").read_text(encoding="utf-8"))
    KEEPER = {t.id: n.value.value for n in _KEEPER.body if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}

    print("[AUTO-MAS 开机没起来：重拉的间隔写的是翻倍，不是每 3 分钟（s1 #9）]")
    body = texts.automas_boot_down_body()
    check("第一次等 3 分钟（代码里也是 180 秒）", (KEEPER["REVIVE_FIRST_WAIT"], "3 分钟后" in body), (180, True))
    check("说了之后翻倍", "翻倍" in body, True)
    check("不再说每 3 分钟", "每 3 分钟" in body, False)
    check("连拉几次再报，和代码一致", f"连拉 {KEEPER['REVIVE_ALERT_AFTER']} 次" in body, True)

    print("\n[中继报错推送的结尾不再说「这不代表脚本没跑」（s1 #10）]")
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

    print("\n[中继自己报错：原话里有英文时说它讲的原因，认不出就照规矩说还不认识（账本 #162）]")
    cases = [
        ("维护公告：终末地 官方公告取不到（官网：<urlopen error [Errno 11001] getaddrinfo failed>），这次不知道它有没有停服维护",
         "域名解析失败"),
        ("卡池信息这次没取到 ｜ TimeoutError: The read operation timed out", "连接或读写超时"),
        ("发到手机信箱没成 ｜ ConnectionResetError: [WinError 10054] An existing connection was forcibly closed",
         "中途断开"),
        ("调度程序的设置没写进去 ｜ PermissionError: [WinError 32] The process cannot access the file because it is "
         "being used by another process", "文件正被其他程序占用"),
        ("状态没存上 ｜ PermissionError: [Errno 13] Permission denied: 'state.json'", "没有权限读写"),
        ("公告取不到（HTTP Error 503: Service Unavailable）", "状态码 503"),
        ("读不到脚本设置 ｜ FileNotFoundError: [WinError 2] The system cannot find the file specified", "找不到要用的文件"),
        ("森空岛的回答读不出 ｜ JSONDecodeError: Expecting value: line 1 column 1 (char 0)", "数据格式是坏的"),
        ("官网取不到 ｜ SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", "加密连接没建立起来"),
        ("公告取不到 ｜ URLError: <urlopen error [WinError 10065] A socket operation was attempted>", "网络请求没发出去"),
    ]
    for what, want in cases:
        body = texts.relay_error_body("ark.maintenance", what, "05:20:16")
        check(f"说出原因：{want}", (want in body, texts.plain(body)), (True, []))
        check(f"不抄带英文的原话：{want}", any(w in body for w in ("urlopen", "Error", "WinError", "Errno")), False)
    check("同时占用和权限两种说法时，说占用", "没有权限" in texts.relay_error_body("ark.config", cases[3][0], ""), False)
    # 无「｜」分隔符的混合英文散文不抄半截话，只出封闭中文诊断；带「｜」且左半段纯中文时保留前缀
    body0 = texts.relay_error_body("ark.maintenance", cases[0][0], "")
    check("无分隔符混合英文不抄半句，直出封闭中文原因",
          ("官方公告取不到" in body0, "域名解析失败" in body0, texts.plain(body0)), (False, True, []))
    body1 = texts.relay_error_body("ark.banners", cases[1][0], "")
    check("带「｜」且左半段为纯中文时保留业务前缀",
          ("卡池信息这次没取到" in body1, "连接或读写超时" in body1, texts.plain(body1)), (True, True, []))
    unknown = texts.relay_error_body("ark.service", "Traceback: KeyError 'x'", "09:00:01")
    check("去盲盒：KeyError 输出直白中文原因，无盲盒话术",
          ("读取数据时缺少必要内容" in unknown, not hasattr(texts, "RELAY_ERROR_UNREAD"),
           "这种报错中继还不认识" not in unknown, texts.plain(unknown)),
          (True, True, True, []))
    # #180: the relay's own warning names the upstream file it pins; a file name standing alone
    # is not English prose, so the line is quoted directly in plain Chinese.
    from ark_relay.features import evidence as _ev
    check("三处钉的上游名字", [p.name for p in _ev.PINS],
          ["MaaEnd 导出（MXU file_ops.rs）", "MAA 生成日志压缩包（IssueReportUserControlModel.cs）", "OK-WW 导出日志（diagnostics.py）"])
    for pin in _ev.PINS:
        said = f"上游导出代码变了：{pin.name}"
        check(f"带文件名的中文原话过得了检查：{pin.name}", texts.plain(said), [])
        body = texts.relay_error_body("ark.service", said, "09:09:46")
        check(f"群里照抄原话，不说还不认识：{pin.name}",
              (f"它说：{said}" in body, "这种报错中继还不认识" in body, texts.plain(body)),
              (True, False, []))
    all3 = "上游导出代码变了：" + "、".join(p.name for p in _ev.PINS) + "（都已报过，不再重发）"
    check("三处一起变、已报过的那句也照抄", "它说：" + all3[:20] in texts.relay_error_body("ark.service", all3, ""), True)
    check("文件名后面紧跟中文、带两段后缀也认得", texts.plain("旧日志 maafw.bak.log.gz变成压缩的了，file_ops.rs也改了"), [])
    for line in ("PermissionError: [Errno 13] Permission denied: 'state.json'", "Traceback: KeyError 'x'",
                 "can't open file 'run.py': [Errno 2] No such file or directory"):
        check(f"英文报错里带文件名的照旧算英文：{line[:24]}", any(p.startswith("英文") for p in texts.plain(line)), True)
        check(f"也照旧不抄原话：{line[:24]}", "它说" in texts.relay_error_body("ark.service", line, ""), False)
    check("不是文件后缀的英文照旧拦（file.ops、e.g）", [bool(texts.plain(x)) for x in ("看 file.ops", "参见 readme.rst")], [True, True])
    check("原话是人话时照抄", "它说：日报没发出去" in texts.relay_error_body("ark.report", "日报没发出去", "10:47"), True)
    jargon_body = texts.relay_error_body("ark.service", "AUTO-MAS 拉起后 45 秒内接口仍不通", "21:21")
    check("原话全是中文但带工程术语：统一转为白话并过 plain()",
          ("它说：AUTO-MAS 启动后 45 秒内数据入口仍不通" in jargon_body, texts.plain(jargon_body)),
          (True, []))
    merged = texts.relay_error_line("ark.maintenance", cases[0][0], "05:20:16 起共 5 次，最后一次 05:20:31")
    check("合并推送里的每一行也说原因", ("域名解析失败" in merged, texts.plain(merged)), (True, []))
    again = texts.relay_error_recurred_body("ark.banners", cases[1][0], "21:47:01", "游戏机缺读图组件")
    check("修过又出现的那种也说原因", ("连接或读写超时" in again, texts.plain(again)), (True, []))
    old = "原话有术语" + "没翻译"
    hits = [f.relative_to(ROOT).as_posix() for f in sorted((ROOT / "ark_relay").rglob("*.py")) if old in f.read_text(encoding="utf-8")]
    check("代码里不再有那句半截话（全仓彻底清零）", hits, [])


def _part_texts_structured_faults():
    """源头活异常采集（fault_from_exc）+ errwatch 透传 + ErrorCode 分类器 + 封闭中文模板回归。"""
    import json
    import logging
    import socket
    import subprocess
    import urllib.error

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.core import texts
    from ark_relay.features import errwatch

    print("\n[1. 源头活异常采集 fault_from_exc 与 errwatch 队列透传（含旧队列 JSON 兼容）]")
    class _FakeResp:
        def __init__(self, code):
            self.status_code = code

    class _FakeReqHTTP(Exception):
        def __init__(self, code):
            super().__init__(f"{code} Bad Gateway")
            self.response = _FakeResp(code)

    class _FakeAioHTTP(Exception):
        def __init__(self, status):
            super().__init__(f"{status}, message='Internal Server Error'")
            self.status = status

    pe32 = PermissionError(13, "locked", "state.json")
    pe32.winerror = 32
    exc_cases = [
        (urllib.error.HTTPError("https://cos.example.com/a", 503, "Service Unavailable", {}, None), "http_error", "状态码 503"),
        (_FakeReqHTTP(502), "http_error", "状态码 502"),
        (_FakeAioHTTP(500), "http_error", "状态码 500"),
        (pe32, "file_locked", "文件正被其他程序占用"),
        (PermissionError(13, "denied", "cfg.json"), "permission_denied", "没有权限读写"),
        (FileNotFoundError(2, "missing", "QueueConfig.json"), "file_not_found", "QueueConfig.json"),
        (subprocess.CalledProcessError(128, ["git", "pull"]), "process_exit", "退出码 128"),
        (subprocess.TimeoutExpired(["pwsh"], 30), "timeout", "连接或读写超时"),
        (urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")), "dns_failed", "域名解析失败"),
        (ConnectionResetError(10054, "reset"), "conn_reset", "中途断开"),
        (json.JSONDecodeError("Expecting value", "", 0), "bad_json", "数据格式是坏的"),
        (KeyError("stage"), "key_error", "读取数据时缺少必要内容"),
        (ValueError("bad"), "value_error", "数据数值或格式不对"),
    ]
    for exc, want_code, want_sub in exc_cases:
        f = texts.fault_from_exc(exc)
        out = texts.format_fault_reason("拉取配置失败", fault=f)
        check(f"fault_from_exc({type(exc).__name__}) -> {want_code}",
              (f["code"], want_sub in out, "拉取配置失败——" in out, texts.plain(out)),
              (want_code, True, True, []))
    check("WinError 32 优先于 PermissionError，不说没有权限",
          "没有权限" in texts.format_fault_reason("写配置失败", fault=texts.fault_from_exc(pe32)), False)

    # errwatch._item 直接采集活 exc_info 落入 item["fault"] 并经 render / merge 透传
    h = errwatch.ErrorKindAlert(None, state_dir=tmpdir("ew-fault-"), known={})
    try:
        try:
            raise _FakeReqHTTP(502)
        except _FakeReqHTTP:
            rec_http = logging.LogRecord("ark.banners", logging.ERROR, __file__, 1, "拉取活动失败", None, sys.exc_info())
        item_http = h._item(rec_http, "sig-http", "2026-11-28 09:05:00")
        _, body_http = errwatch.render(item_http)
        check("errwatch._item 源头提取活异常 HTTP 502 并透传 render()",
              (item_http.get("fault"), "拉取活动失败——对方服务器返回了状态码 502" in body_http, texts.plain(body_http)),
              ({"code": "http_error", "http": 502}, True, []))

        try:
            raise subprocess.CalledProcessError(128, ["git", "pull"])
        except subprocess.CalledProcessError:
            rec_cmd = logging.LogRecord("ark.service", logging.ERROR, __file__, 1, "同步仓库失败", None, sys.exc_info())
        item_cmd = h._item(rec_cmd, "sig-cmd", "2026-11-28 09:05:05")
        _, merged_body = errwatch.merge([item_http, item_cmd])
        check("errwatch.merge 透传两条结构化 fault 且全过 plain()",
              ("状态码 502" in merged_body, "退出码 128" in merged_body, texts.plain(merged_body)),
              (True, True, []))

        # 向后兼容：旧队列 JSON 不含 fault 字段时自动回退文本分类
        legacy_item = {"title": texts.RELAY_ERROR, "where": "ark.banners",
                       "line": "拉取失败 ｜ HTTP Error 503: Service Unavailable",
                       "first": "2026-11-28 09:00:00", "last": "2026-11-28 09:00:00", "n": 1}
        _, legacy_body = errwatch.render(legacy_item)
        check("旧队列 JSON 缺省 fault 100% 兼容",
              ("拉取失败——对方服务器返回了状态码 503" in legacy_body, texts.plain(legacy_body)),
              (True, []))
    finally:
        h.close()

    print("\n[2. 主流 HTTP 客户端报错（requests/pwsh/curl/httpx/aiohttp）与 HTTP < 400 隔离]")
    http_cases = [
        ("拉取活动失败 ｜ requests.exceptions.HTTPError: 502 Server Error: Bad Gateway for url: https://cos.example.com/api/v1", 502, True),
        ("下载更新失败：HTTPError: 403 Client Error: Forbidden for url: https://cos.example.com/manifest.json", 403, False),
        ("requests.exceptions.HTTPError: 503 Server Error: Service Unavailable for url: https://cos.example.com/api", 503, False),
        ("拉取失败：HTTPError(504, 'Gateway Timeout')", 504, False),
        ("pwsh 调接口失败 ｜ System.Net.Http.HttpRequestException: Response status code does not indicate success: 502 (Bad Gateway).", 502, False),
        ("拉取失败 ｜ Invoke-RestMethod: Response status code does not indicate success: 503 (Service Unavailable).", 503, True),
        ("curl 下载失败 ｜ curl: (22) The requested URL returned error: 503", 503, False),
        ("拉取失败 ｜ httpx.HTTPStatusError: Server error '502 Bad Gateway' for url 'https://cos.example.com/api'", 502, True),
        ("拉取失败 ｜ aiohttp.client_exceptions.ClientResponseError: 500, message='Internal Server Error', url='https://cos.example.com/api'", 500, True),
        ("pwsh 调接口失败 ｜ status_code=502 Bad Gateway", 502, False),
        ("git 调接口失败 ｜ status_code=503 Service Unavailable", 503, False),
        ("ssh 代理返回 ｜ statusCode=504 Gateway Timeout", 504, False),
        ("git 调接口失败 ｜ status-code=502", 502, False),
        ("拉取失败 ｜ {\"httpStatus\": 502}", 502, True),
        ("拉取数据失败 ｜ {\"status_code\": 503}", 503, True),
        ("拉取失败 ｜ {\"status\": 502}", 502, True),
        ("拉取超时 ｜ status_code=524 Cloudflare", 524, True),
        ("拉取失败 ｜ HTTP/2 429 Too Many Requests", 429, True),
    ]
    for raw, code, keep_prefix in http_cases:
        rec = texts.classify_fault(raw)
        out = texts.format_fault_reason(raw)
        check(f"HTTP {code} 准确分类：{raw[:38]}",
              (rec.code, rec.http, rec.exit_code, f"对方服务器返回了状态码 {code}" in out,
               "退出码" in out, "——" in out, texts.plain(out)),
              (texts.ErrorCode.HTTP_ERROR, code, None, True, False, keep_prefix, []))

    # HTTP < 400（200/302）不抢占真实异常；200 与 503 共存时取 503
    h200_json = "解析接口数据失败 ｜ HTTP/1.1 200 OK, Content-Type: text/html, JSONDecodeError: Expecting value"
    h200_key = "解析失败 ｜ HTTP/1.1 200 OK KeyError: 'data'"
    h200_503 = "上游转发失败 ｜ HTTP/1.1 200 OK -> HTTP/1.1 503 Service Unavailable"
    out_j, out_k, out_m = (texts.format_fault_reason(x) for x in (h200_json, h200_key, h200_503))
    check("HTTP 200 不抢占 JSONDecodeError/KeyError，200+503 优先 503",
          (texts.classify_fault(h200_json).code, "状态码 200" in out_j, "解析返回数据失败——" in out_j, texts.plain(out_j),
           texts.classify_fault(h200_key).code, "状态码 200" in out_k, texts.plain(out_k),
           texts.classify_fault(h200_503).http, "状态码 503" in out_m, texts.plain(out_m)),
          (texts.ErrorCode.BAD_JSON, False, True, [], texts.ErrorCode.KEY_ERROR, False, [], 503, True, []))

    print("\n[3. 非零退出码与系统码：隔离 0/0x0/DATE/TIME/FLOAT/SEMVER/byte 0xff]")
    exit_cases = [
        ("CalledProcessError: Command '['git', 'pull']' returned non-zero exit status 128.", 128),
        ("CalledProcessError(127, 'adb')", 127),
        ("任务执行失败 ｜ exit status 128", 128),
        ("任务执行失败 ｜ returncode=255", 255),
        ("脚本失败 退出码-1073741819 RuntimeError: crash", -1073741819),
        ("脚本失败 返回码-1 RuntimeError: crash", -1),
        ("同步脚本失败 exit-status-500", 500),
        ("同步脚本失败 exit-code-127", 127),
        ("同步失败 ｜ exit_status-127", 127),
        ("helper.exe exited with code 128", 128),
        ("process exited 127", 127),
        ("exit status 0xc0000005", "0xc0000005"),
        ("waitpid failed: status=127", 127),
        ("process ended with status 500", 500),
        ("ssh host failed, status=255", 255),
        ("PowerShell script failed with EXIT\tSTATUS 255", 255),
    ]
    for raw, code in exit_cases:
        rec = texts.classify_fault(raw)
        out = texts.format_fault_reason(raw)
        check(f"退出码 {code} 归 PROCESS_EXIT：{raw[:36]}",
              (rec.code, rec.exit_code, rec.http, f"退出码 {code}" in out, "状态码" in out, texts.plain(out)),
              (texts.ErrorCode.PROCESS_EXIT, code, None, True, False, []))

    non_exit_cases = [
        ("任务记录 MaaEnd exited 2026-11-28 ValueError: parse failed", texts.ErrorCode.VALUE_ERROR),
        ("同步状态失败 ｜ exited 09:30:00 ValueError: bad", texts.ErrorCode.VALUE_ERROR),
        ("脚本失败 rc=1.5 ValueError: bad", texts.ErrorCode.VALUE_ERROR),
        ("终末地版本校验失败 ｜ MaaEnd v2.34.0-rc-2 ValueError: bad manifest", texts.ErrorCode.VALUE_ERROR),
        ("RuntimeError: src=128 failed", texts.ErrorCode.RUNTIME_ERROR),
        ("exit status 0 ValueError: bad", texts.ErrorCode.VALUE_ERROR),
        ("运行结束 exit_code=0x0 ValueError: bad payload", texts.ErrorCode.VALUE_ERROR),
        ("pwsh 运行完成 ｜ exit_code=0x00000000 JSONDecodeError: Expecting value", texts.ErrorCode.BAD_JSON),
        ("ValueError: invalid status=999", texts.ErrorCode.VALUE_ERROR),
        ("ValueError: invalid status=128", texts.ErrorCode.VALUE_ERROR),
    ]
    for raw, want_code in non_exit_cases:
        rec = texts.classify_fault(raw)
        out = texts.format_fault_reason(raw)
        check(f"不误判退出码/0x0：{raw[:36]}",
              (rec.code, rec.exit_code, rec.hex_code, "退出码" in out, "错误码 0x0" in out, texts.plain(out)),
              (want_code, None, "", False, False, []))

    te_out = texts.format_fault_reason("TimeoutError: command timed out, exit status 128")
    w128_out = texts.format_fault_reason("OSError: [WinError 128] There are no child processes to wait for")
    ff_out = texts.format_fault_reason("拉取页面失败 ｜ HTTP/1.1 302 Found UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff")
    check("超时伴退出码 / WinError 128 / byte 0xff 精准收口",
          ("连接或读写超时" in te_out, "退出码 128" in te_out, "状态码" in te_out, texts.plain(te_out),
           "系统调用失败（系统错误码 128）" in w128_out, "状态码" in w128_out, texts.plain(w128_out),
           "拉取页面失败——收到的数据格式是坏的" in ff_out, "0xff" in ff_out, texts.plain(ff_out)),
          (True, True, False, [], True, False, [], True, False, []))
    check("纯中文模糊词与术语规整不留孤立逗号",
          (texts.format_fault_reason("可能，大概，落盘失败"),
           texts.format_fault_reason("中继更新出错"),
           texts.plain(texts.format_fault_reason("这一步可能有问题，不确定是否落盘"))),
          ("保存失败", "中继更新失败", []))

    print("\n[4. P1-3 & P1-4 回归：HTTPError(response=None) 优先级 / 兜底 winerror+file / RC 1 / URL 内 0x]")
    class _RequestException(Exception):
        pass

    class _ReqHTTPError(_RequestException):
        def __init__(self, msg, response=None):
            super().__init__(msg)
            self.response = response

    class _CustomBrandNewError(Exception):
        pass

    f_req502 = texts.fault_from_exc(_ReqHTTPError("502 Server Error: Bad Gateway", response=None))
    f_req302 = texts.fault_from_exc(urllib.error.HTTPError("https://x", 302, "Found", {}, None))
    f_w193 = texts.fault_from_exc(_CustomBrandNewError("WinError 193: %1 is not a valid Win32 application"))
    f_e13_zh = texts.fault_from_exc(_CustomBrandNewError("[Errno 13] Permission denied: '/Library/Logs/ark-relay/relay.log'"))
    out_w193 = texts.format_fault_reason("启动脚本失败", fault=f_w193)
    check("fault_from_exc：HTTPError(response=None) 优先归 HTTP 502，302 仍落 net_error，兜底完整透传 winerror/errno/file",
          (f_req502, f_req302, f_w193, f_e13_zh, "系统错误码 193" in out_w193, texts.plain(out_w193)),
          ({"code": "http_error", "http": 502}, {"code": "net_error"},
           {"code": "os_error", "winerror": 193},
           {"code": "permission_denied", "errno": 13, "file": "/Library/Logs/ark-relay/relay.log"},
           True, []))

    rc1_rec = texts.classify_fault("测试版本 RC 1 校验失败 ｜ KeyError: 'x'")
    url_hex_raw = "拉取 https://cos.example.com/obj/0x12345678.bin 失败 ｜ TimeoutError: timed out"
    url_hex_rec = texts.classify_fault(url_hex_raw)
    url_hex_out = texts.format_fault_reason(url_hex_raw)
    check("RC 1 不误判退出码 1（小写 rc=1/rc: 1/rc 1 照常保留），NTSTATUS 不扫 URL 里的 0x",
          (rc1_rec.code, rc1_rec.exit_code,
           texts.classify_fault("命令失败 rc=1").exit_code,
           texts.classify_fault("命令失败 rc: 1").exit_code,
           texts.classify_fault("命令失败 rc 1").exit_code,
           url_hex_rec.code, url_hex_rec.hex_code, "错误码 0x12345678" in url_hex_out, texts.plain(url_hex_out)),
          (texts.ErrorCode.KEY_ERROR, None, 1, 1, 1, texts.ErrorCode.TIMEOUT, "", False, []))


def _part_texts_plain_strict():
    """极简严格 plain() 门禁与 v4 报告五类真实生产场景全覆盖回归。"""
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.core import texts

    print("\n[1. 场景 1：腾讯 COS 预签名 URL / B站 REST 查询 URL / IPv6 / 维基括号 完整放行 + 异常硬停]")
    cos_url = "https://bucket-123.cos.ap-shanghai.myqcloud.com/a.json?q-header-list=host;x-cos-date&q-sign-algorithm=sha1"
    bili_url = "https://api.bilibili.com/x/web-interface/view?bvid=BV1xx&fields=title,pubdate"
    cos_raw = f"拉取 {cos_url} 失败 ｜ TimeoutError"
    cos_out = texts.format_fault_reason(cos_raw)
    check("腾讯 COS 预签名 URL 完整保留不腰斩、零 ; & 乱码",
          (cos_url in cos_out, "; &" in cos_out, "连接或读写超时" in cos_out, texts.plain(cos_out)),
          (True, False, True, []))
    for ok_url_msg in (
        f"查看 {bili_url} 失败",
        "拉取 https://api.example.com/v1/items?fields=id,name&limit=10 失败",
        "请求 https://api.example.com/v1/a;jsessionid=abc123 失败",
        "拉取 https://proxy.example.com/fetch?url=https://cos.example.com/a.json&t=1 失败",
        "拉取 https://cos.example.com/logs?since=2026-11-28T09:00:00+08:00 失败",
        "查看 https://en.wikipedia.org/wiki/Python_(programming_language)",
        "查看 https://prts.wiki/w/Arknights_(game)",
        "查看 https://wiki.example.com/w/File:Logo.png",
        "访问 http://[::]:8080/api 失败",
        "访问 http://[::1]:36163/api 失败",
    ):
        check(f"合法 URL 纯中文句原样放行：{ok_url_msg[:42]}",
              (texts.plain(ok_url_msg), texts.format_fault_reason(ok_url_msg)), ([], ok_url_msg))
    for bad_url_msg, want_code in (
        ("拉取 https://cos.example.com/a.json:PermissionError", texts.ErrorCode.PERMISSION_DENIED),
        ("拉取 https://cos.example.com/api/v1:ReadTimeout", texts.ErrorCode.TIMEOUT),
        ("拉取 https://cos.example.com/api/v1:status=503", texts.ErrorCode.HTTP_ERROR),
        ("拉取 https://cos.example.com/a.json,HTTP/1.1 503 Service Unavailable", texts.ErrorCode.HTTP_ERROR),
        ("拉取 https://cos.example.com/a.json;RuntimeError: bad", texts.ErrorCode.RUNTIME_ERROR),
        ("拉取 https://cos.example.com/a.json!KeyError: 'items'", texts.ErrorCode.KEY_ERROR),
        ("拉取 https://cos.example.com/a.json,[KeyError]", texts.ErrorCode.KEY_ERROR),
        ("拉取 https://cos.example.com/a.json(TimeoutError)", texts.ErrorCode.TIMEOUT),
        ("拉取 https://cos.example.com/api_(ConnectionReset)", texts.ErrorCode.CONN_RESET),
    ):
        out = texts.format_fault_reason(bad_url_msg)
        check(f"URL 尾随异常硬停拦截：{bad_url_msg[:40]}",
              (bool(texts.plain(bad_url_msg)), texts.classify_fault(bad_url_msg).code, texts.plain(out)),
              (True, want_code, []))

    print("\n[2. 场景 2：Homebrew Python 与 Unix 系统路径整条放行，绝不凭空造 python.exe]")
    for unix_ok in (
        "检查 /opt/homebrew/Cellar/python@3.15/3.15.2/bin/python3 失败",
        "读取 /etc/ssl/certs/ca-bundle.crt 失败",
        "读取 /var/log/http/access.log 失败",
        "读取 /usr/lib/python3.15/http/client.py 失败",
        "读取 ./run 与 ../cfg/a 与 ~/app 失败",
        "读取 releases/3.15.2/manifest.json 失败",
        "读取 logs/error/2026-11-28.log 失败",
    ):
        out = texts.format_fault_reason(unix_ok)
        check(f"Unix/合规相对路径整条放行：{unix_ok[:40]}",
              (texts.plain(unix_ok), out, "python.exe" in out), ([], unix_ok, False))
    tb_py = ('拉取失败\n  File "/opt/homebrew/Cellar/python@3.15/3.15.2/Frameworks/Python.framework/Versions/3.15/lib/python3.15/http/client.py", '
             'line 429, in _read_status\nhttp.client.RemoteDisconnected: Remote end closed connection')
    tb_out = texts.format_fault_reason(tb_py)
    log_err = texts.format_fault_reason("读取 logs/error/2026-11-28.log 失败：PermissionError")
    check("Python 标准库堆栈不凭空捏造 python.exe，相对路径保留全路径不碎成 11-28.log",
          ("中途断开" in tb_out, "python.exe" in tb_out, texts.plain(tb_out),
           "logs/error/2026-11-28.log" in log_err, "文件 11-28.log" in log_err, texts.plain(log_err)),
          (True, False, [], True, False, []))

    print("\n[3. 场景 3：原生英文异常与未知空格词 100% 被 plain() 拦截，零裸推穿透]")
    for leak, want_code in (
        (r"打开 C:\ark\readme ConnectionReset logs\a.log", texts.ErrorCode.CONN_RESET),
        (r"打开 C:\ark\readme ConnectionRefused logs\a.log", texts.ErrorCode.CONN_RESET),
        (r"打开 C:\ark\readme ConnectionAborted logs\a.log", texts.ErrorCode.CONN_RESET),
        (r"打开 C:\ark\readme AccessDenied logs\a.log", texts.ErrorCode.PERMISSION_DENIED),
        (r"打开 C:\ark\pkg BadZipFile logs\a.log", texts.ErrorCode.BAD_JSON),
        (r"读取 C:\ark\data StopIteration logs\a.log", texts.ErrorCode.RUNTIME_ERROR),
        (r"拉取 C:\ark\cache TooManyRedirects logs\a.log", texts.ErrorCode.NET_ERROR),
        (r"写入 C:\ark\target FileExists logs\a.log", texts.ErrorCode.OS_ERROR),
        (r"打开 C:\ark\readme locked logs\a.log", texts.ErrorCode.UNKNOWN),
        (r"打开 C:\ark\dir(ReadTimeout)", texts.ErrorCode.TIMEOUT),
        ("抛出 ConnectionReset/state.json", texts.ErrorCode.CONN_RESET),
        ("抛出 AccessDenied/config.json", texts.ErrorCode.PERMISSION_DENIED),
        ("抛出 BadZipFile/a.zip", texts.ErrorCode.BAD_JSON),
        ("抛出 StopIteration/data.json", texts.ErrorCode.RUNTIME_ERROR),
        ("抛出 PermissionError/state.json", texts.ErrorCode.PERMISSION_DENIED),
        ("返回 HTTP/1.1/a.json", texts.ErrorCode.UNKNOWN),
        ("返回 gRPC/1.0/a.json", texts.ErrorCode.UNKNOWN),
        ("返回 TLS/1.3/a.json", texts.ErrorCode.UNKNOWN),
        ("返回 QUIC/v1/a.json", texts.ErrorCode.UNKNOWN),
        ("返回 2.0/a.json", texts.ErrorCode.UNKNOWN),
        ("程序抛出 ValueError/KeyError", texts.ErrorCode.KEY_ERROR),
        ("类型 application/json 失败", texts.ErrorCode.UNKNOWN),
    ):
        body = texts.relay_error_body("ark.service", leak, "09:00:00")
        check(f"穿透拦截零裸推：{leak[:42]}",
              (bool(texts.plain(leak)), "它说：" in body, texts.classify_fault(leak).code, texts.plain(body)),
              (True, False, want_code, []))

    print("\n[4. 场景 5 & 原子格式：引号/正斜杠/中文空格 Windows/UNC 路径 + ISO 时间 + SEMVER]")
    for ok_win in (
        r"打开 'C:\Program Files\Node.js Runtime\node.exe' 失败",
        r"启动 'C:/Program Files/My App/run.exe' 失败",
        r"启动 C:/Program Files/AUTO-MAS/run.exe 失败",
        r"启动 C:\Program Files (x86)\AUTO-MAS\AUTO-MAS.exe 失败",
        r"打开 C:\Users\Default User\AppData\a.log 失败",
        r"磁盘 C:\ 空间不足",
        r"读取 C:/ 失败",
        r"打开 D:\游戏\终末地\config.json 失败",
        r"读取 D:\我的 游戏\配置\state.json 失败",
        r"读取 D:\游戏\鸣潮 2.0\config.json 失败",
        r"读取 \\fileserver\共享 文件夹\日志\err.log 失败",
        "任务于 2026-11-28T20:45:00+08:00 失败",
        "任务于 2026-11-28T20:45:00.123Z 失败",
        "升级 v2.28.0-beta.1 到 v3.15.2-RC1 与 v2.34.0-rc-1",
        "程序崩溃 0xc0000005",
    ):
        check(f"合法路径/时间/版本号放行：{ok_win[:40]}", texts.plain(ok_win), [])
    node_unquoted = texts.format_fault_reason(r"打开 C:\Program Files\Node.js Runtime\node.exe 失败：PermissionError")
    check("无引号 Node.js Runtime 不劈成顿号假路径也不抠半截 Files\\Node.js",
          ("Node.js、" in node_unquoted, r"Files\Node.js" in node_unquoted,
           "没有权限读写" in node_unquoted, texts.plain(node_unquoted)),
          (False, False, True, []))
    for expr in ("调用 ptr->value 失败", "执行 cmdA && cmdB 失败", "校验 verA != verB 失败", "程序崩溃 0xZZZ"):
        out = texts.format_fault_reason(expr)
        check(f"含英文运算符/非法十六进制无残渣：{expr}",
              (bool(texts.plain(expr)), any(op in out for op in ("->", "&&", "!=", "0xZZZ")), texts.plain(out)),
              (True, False, []))

    print("\n[5. P0-1 & P0-2 回归：缩写/多段驼峰 EXC_RE、无 ? URL 分隔符、引号/Semver/WIN 尾段防穿透、macOS 根路径与中文目录]")
    for leak, want_code, want_http in (
        ("拉取 https://cos.example.com/a.json,HTTPError: 502", texts.ErrorCode.HTTP_ERROR, 502),
        ("拉取 https://cos.example.com/a.json,status=503", texts.ErrorCode.HTTP_ERROR, 503),
        ("拉取 https://cos.example.com/a.json,JSONDecodeError", texts.ErrorCode.BAD_JSON, None),
        ("拉取 https://cos.example.com/a.json;SSLError", texts.ErrorCode.SSL_ERROR, None),
        ("拉取 https://cos.example.com/a.json,URLError", texts.ErrorCode.NET_ERROR, None),
        ("拉取 https://cos.example.com/a.json,OSError", texts.ErrorCode.OS_ERROR, None),
        ("拉取 https://cos.example.com/a.json,HTTPStatusError", texts.ErrorCode.UNKNOWN, None),
        ("拉取 https://cos.example.com/a.json,SSLCertVerificationError", texts.ErrorCode.SSL_ERROR, None),
        ("拉取 https://cos.example.com/a.json,failed", texts.ErrorCode.UNKNOWN, None),
        ("拉取 https://cos.example.com/a.json;timeout", texts.ErrorCode.UNKNOWN, None),
        ("拉取 https://cos.example.com/a.json,Forbidden", texts.ErrorCode.UNKNOWN, None),
        ("拉取 https://cos.example.com/a.json?k=v,JSONDecodeError", texts.ErrorCode.BAD_JSON, None),
        ("抛出 JSONDecodeError/config.json", texts.ErrorCode.BAD_JSON, None),
        ("抛出 UnicodeDecodeError/a.txt", texts.ErrorCode.BAD_JSON, None),
        ("抛出 HTTPError/a.json", texts.ErrorCode.UNKNOWN, None),
        ("抛出 SSLError/a.json", texts.ErrorCode.SSL_ERROR, None),
        ("抛出 URLError/a.json", texts.ErrorCode.NET_ERROR, None),
        ("抛出 OSError/a.json", texts.ErrorCode.OS_ERROR, None),
        ("抛出 ReadTimeoutError/a.json", texts.ErrorCode.TIMEOUT, None),
        ("抛出 NameResolutionError/a.json", texts.ErrorCode.DNS_FAILED, None),
        ("抛出 ClientResponseError/a.json", texts.ErrorCode.UNKNOWN, None),
        ("抛出 ModuleNotFoundError/a.py", texts.ErrorCode.UNKNOWN, None),
        ("抛出 CustomBrandNewError/a.json", texts.ErrorCode.UNKNOWN, None),
        (r"读取 'C:\ark\a.json JSONDecodeError' 失败", texts.ErrorCode.BAD_JSON, None),
        (r"读取 'C:\ark\a.json UnicodeDecodeError' 失败", texts.ErrorCode.BAD_JSON, None),
        (r"读取 'C:\ark\a.json HTTPError' 失败", texts.ErrorCode.UNKNOWN, None),
        (r"读取 'C:\ark\a.json failed to open' 失败", texts.ErrorCode.UNKNOWN, None),
        ("升级到 v1.2.3-JSONDecodeError 失败", texts.ErrorCode.BAD_JSON, None),
        ("升级到 v1.2.3-ReadTimeoutError 失败", texts.ErrorCode.TIMEOUT, None),
        (r"读取 C:\ark\TimeoutError 失败", texts.ErrorCode.TIMEOUT, None),
        (r"读取 C:\ark\JSONDecodeError 失败", texts.ErrorCode.BAD_JSON, None),
    ):
        rec = texts.classify_fault(leak)
        body = texts.relay_error_body("ark.service", leak, "09:00:00")
        check(f"P0-1 防穿透拦截：{leak[:42]}",
              (bool(texts.plain(leak)), "它说：" in body, rec.code, rec.http, texts.plain(body)),
              (True, False, want_code, want_http, []))

    for path_ok in (
        "/Users/herclyon/Money/手机迁移/dsh_web/redmi_adb.py",
        "/Library/Logs/ark-relay/relay.log",
        "/private/tmp/ark.log",
        "/Applications/Python/bin/python3",
        "/System/Library/CoreServices/SystemVersion.plist",
        "/Volumes/Backup/日志/state.json",
        "手机迁移/dsh_web/redmi_adb.py",
    ):
        sent = f"检查 {path_ok} 失败"
        err_sent = f"检查 {path_ok} 失败：FileNotFoundError"
        out = texts.format_fault_reason(err_sent)
        check(f"P0-2 Unix/中文路径完整保留：{path_ok[:40]}",
              (texts.plain(sent), texts._FaultSpec.norm_file(path_ok),
               texts.classify_fault(err_sent).file_ref, f"文件 {path_ok}" in out, texts.plain(out)),
              ([], path_ok, path_ok, True, []))
    fnf_zh = FileNotFoundError(2, "missing", "/Users/herclyon/Money/手机迁移/dsh_web/redmi_adb.py")
    check("活异常中文 Mac 路径完整保留不丢 file",
          texts.fault_from_exc(fnf_zh),
          {"code": "file_not_found", "errno": 2, "file": "/Users/herclyon/Money/手机迁移/dsh_web/redmi_adb.py"})


def _part_user_switches():  # noqa: C901

    import ast
    import re
    import sys
    from pathlib import Path
    from textwrap import dedent

    RELAY = Path(__file__).resolve().parents[1]
    LIST_FILE = RELAY / "USER-SWITCHES.txt"

    COMMAND_RECORDS = {
        "skip_today": "ark_relay/features/modes.py:_day_queues",
    }

    # R3: the marker, and the names that make a dedupe key one occurrence.
    ONE_PUSH = re.compile(r"#\s*one fault, one push:\s*(\S.*)$")
    IDENTITY = re.compile(r"(?:^|_)(?:run_?id|rid|record_?id|rec_?id|pid|due|slot|hhmm|at|line|text)(?:_|$)", re.I)

    R4_FILES = {"service.py", "ark_relay/features/automas_keeper.py", "ark_relay/features/procwatch.py"}
    RELAY_POWER_OFF = "ark_relay/features/errwatch.py:relay_shutdown_issued"
    R4_WRAPPER = "ark_relay/features/procwatch.py:_going_down_soon"
    WRAPPER_PLAIN_CALLS = {"monotonic", "sleep", "min"}

    # R7: the one log line of the log route, and the function that picks the route.
    LOG_ROUTE_SITE = "ark_relay/core/notify.py:Notifier.send"
    LOG_ROUTER = "ark_relay/core/notify.py:route_of"
    LOG_ROUTE = "log"

    # R8: OK-WW's read of the game screen, and its task log methods.
    SCREEN_READ = "ocr"
    TASK_LOGS = {"log_info", "log_debug", "log_warning", "log_error"}

    # OFF-flag: an existence test, and the calls that build a constant path.
    EXISTS_FUNCS = {"exists", "isfile", "lexists"}           # os.path.<f>(p)
    EXISTS_METHODS = {"exists", "is_file"}                   # Path(p).<m>()
    PATH_BUILDERS = {"Path", "PurePath", "PureWindowsPath", "WindowsPath", "join"}

    # ----------------------------------------------------------------- vocabulary

    SWITCH_KEY = re.compile(r"^(?:\w*[Ee]nabled\w*|[Ee]nable|[Cc]hecked|[Ii]s[Cc]hecked|If[A-Z]\w*)$")
    OFF_STRINGS = {"false", "False", "FALSE", "0", "Close", "Off", "关闭", "禁用", "停用"}
    CLOSE_STRINGS = {"Close", "Off", "关闭", "禁用", "停用"}
    # "days": a queue item's Schedule.Days (the weekdays it runs); dropping one skips the item that day.
    TASKY = re.compile(r"task|casenames|(?:^|_)days$", re.I)
    WRITE_CALL = re.compile(r"^(?:atomic_write\w*|write_text|write_bytes|dump|_?write\w*|_mas|_?save\w*|_?put\w*|_?post\w*)$")
    API_REMOVE = re.compile(r"^/api/.*/(?:delete|remove|disable)\b")
    KEEP_LOG = re.compile(r"继续关着|继续关闭|保持关闭|先关着|一直关着|不开回|keeps? (?:it |them |the task )?off", re.I)
    MUTE_NAME = re.compile(r"soft_?fail|soft_only|(?:^|_)SOFT(?:_|$)|SKIP_TASKS|NO_?ALARM|NOT_?ALARM|LOG_?ONLY|"
                       r"REPORT_?ONLY|DAILY_?ONLY|SUPPRESS|(?:^|_)MUTE|DEMOTE", re.I)
    CAP_NAME = re.compile(r"^_?(?:MAX_PER\w*|\w*PER_HOUR\w*|\w*PER_DAY\w*|HOURLY\w*|RATE_LIMIT\w*|MAX_(?:PUSH|ALERT|ALARM|SEND)\w*)$")
    MUTE_LOG = re.compile(r"只进日报|记日报|只记日报|只记日志|不报警|不拉警报|(?<!暂)不推送|不进群|不报群|不发群|"
                      r"不算失败|不算故障|不报漏跑|daily report only|not an alarm|no alarm|not pushed|never pushed", re.I)
    FAIL_TITLE = re.compile(r"⚠️|❌|🚩|失败|没能|没走通|没成|进不了|报错|超时|故障|没跑|没干完|卡住|卡死")
    DEDUPE = re.compile(r"already|alerted|announced|(?:^|_)sent(?:_|$)|(?:^|_)seen$|(?:^|_)once|dedup|notified|"
                    r"(?:^|_)rung|_pushed|_room", re.I)
    FAILKIND = re.compile(r"soft|maint|sanity|manual|by_?hand|hand_started|trigger|failed_tasks|cause|debug|skip|"
                      r"unreachable|episode_kind|known_fixed|recur|is_test|test_window|is_fault|going_down|"
                      r"shutting_down|shutdown_issued|levelno", re.I)
    LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}
    SKIP_SIGNAL = "TaskDisabledException"
    PATCH_OFF = re.compile(r"raise TaskDisabledException|已禁用")
    DERIVING_CALLS = {"bool", "str", "int", "list", "set", "frozenset", "tuple", "sorted", "len"}
    # methods that only reshape the value they are called on (rule 1 follows them)
    VALUE_METHODS = {"get", "lower", "upper", "strip", "lstrip", "rstrip", "casefold", "startswith", "endswith",
                     "split", "replace", "items", "keys", "values"}

    OFF, DECISION, CARRIED, ON = "off", "decision", "carried", "on"

    class _Missing:
        pass

    MISSING = _Missing()

    def _is_off(v) -> bool:
        if isinstance(v, bool):
            return v is False
        if isinstance(v, (int, float)):
            return v == 0
        return isinstance(v, str) and v in OFF_STRINGS

    def _call_name(call: ast.Call) -> str:
        f = call.func
        return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""

    # ----------------------------------------------------------------- per function

    class Fn:
        """One function: its parameters and every local binding, for the value judge."""

        def __init__(self, node, qual: str, cls: "str | None"):
            self.node, self.qual, self.cls = node, qual, cls
            self.name = node.name
            a = node.args
            self.params = [x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs)]
            self.params += [x.arg for x in (a.vararg, a.kwarg) if x is not None]
            self.free = {p for p in self.params if p not in ("self", "cls")}
            self.nodes: list = []          # every node in the body, not those of nested functions (Module._walk)
            self.assigned: dict[str, list] = {}       # name -> [("=", value) | ("for", iter) | ("other", None)]
            self.writes = False

        def finish(self):
            self.calls = [n for n in self.nodes if isinstance(n, ast.Call)]
            self.writes = any(WRITE_CALL.match(_call_name(n)) for n in self.calls)
            for n in self.nodes:
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        self._bind(t, n.value)
                elif isinstance(n, ast.AnnAssign) and n.value is not None:
                    self._bind(n.target, n.value)
                elif isinstance(n, ast.AugAssign):
                    self._bind(n.target, None)
                elif isinstance(n, ast.NamedExpr):
                    self._bind(n.target, n.value)
                elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
                    self._bind(n.target, None, it=n.iter)
                elif isinstance(n, (ast.With, ast.AsyncWith)):
                    for it in n.items:
                        if it.optional_vars is not None:
                            self._bind(it.optional_vars, None)
                elif isinstance(n, ast.ExceptHandler) and n.name:
                    self.assigned.setdefault(n.name, []).append(("other", None))
                elif isinstance(n, (ast.Import, ast.ImportFrom)):
                    for al in n.names:
                        self.assigned.setdefault((al.asname or al.name).split(".")[0], []).append(("other", None))

        def _bind(self, target, value, it=None):
            if isinstance(target, ast.Name):
                entry = ("for", it) if it is not None else ("=", value) if value is not None else ("other", None)
                self.assigned.setdefault(target.id, []).append(entry)
            elif isinstance(target, (ast.Tuple, ast.List)):
                vals = value.elts if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts) else None
                for i, t in enumerate(target.elts):
                    self._bind(t, vals[i] if vals is not None else None, it=None if vals is not None else it)
            elif isinstance(target, ast.Starred):
                self._bind(target.value, None)

        def method_params(self) -> list[str]:
            return self.params[1:] if self.cls and self.params[:1] in (["self"], ["cls"]) else self.params

    # ----------------------------------------------------------------- per module

    class Hit:
        def __init__(self, rel, line, key, rule, text, node=None, fn=None):
            self.rel, self.line, self.key, self.rule, self.text = rel, line, key, rule, text
            self.node, self.fn = node, fn

        def __repr__(self):
            return f"{self.rel}:{self.line}  {self.key}  [{self.rule}]  {self.text}"

    class Module:
        def __init__(self, rel: str, src: str):
            self.rel, self.stem = rel, Path(rel).stem
            self.tree = ast.parse(src)
            self.lines = src.splitlines()
            self.parent: dict = {}
            self.scope: dict = {}                  # node -> enclosing Fn (None at module/class level)
            self.fns: dict[str, Fn] = {}           # qualname -> Fn
            self.consts: dict[str, ast.AST] = {}   # NAME / Class.NAME -> value node (module/class level)
            self.imports: dict[str, str] = {}      # alias -> relay module stem
            self.from_imports: dict[str, tuple[str, str]] = {}
            self.top_nodes: list = []              # nodes outside any function
            self.new_names: set[str] = set()       # names passed as a patch's `new=` text
            self.docstrings: set[int] = set()
            self._walk(self.tree, None, None, "")
            for f in self.fns.values():
                f.finish()
            self.fn_of_node = {f.node: f for f in self.fns.values()}

        def _walk(self, node, fn, cls, prefix):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                self.docstrings.add(id(body[0].value))
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node
                self.scope[child] = fn
                (fn.nodes if fn is not None else self.top_nodes).append(child)
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    f = Fn(child, f"{prefix}{child.name}", cls if fn is None else None)
                    self.fns[f.qual] = f
                    self._walk(child, f, None, f.qual + ".")
                    continue
                if isinstance(child, ast.ClassDef):
                    self._walk(child, fn, child.name if fn is None else None, f"{prefix}{child.name}.")
                    continue
                if fn is None and isinstance(child, (ast.Assign, ast.AnnAssign)) and child.value is not None:
                    for t in (child.targets if isinstance(child, ast.Assign) else [child.target]):
                        if isinstance(t, ast.Name):
                            self.consts[f"{prefix}{t.id}"] = child.value
                elif isinstance(child, ast.ImportFrom):
                    self._import(child)
                elif isinstance(child, ast.keyword) and child.arg == "new" and isinstance(child.value, ast.Name):
                    self.new_names.add(child.value.id)
                self._walk(child, fn, cls, prefix)

        def _import(self, n: ast.ImportFrom):
            relative = (n.level or 0) >= 1
            pkg = n.module or ""
            if not relative and not pkg.startswith("ark_relay"):
                return
            for a in n.names:
                if relative and not pkg or pkg == "ark_relay":
                    self.imports[a.asname or a.name] = a.name
                else:
                    self.from_imports[a.asname or a.name] = (pkg.split(".")[-1], a.name)

        def where(self, node) -> str:
            """The key part after 'file:' for a node outside any function."""
            names, stmt, n = [], None, node
            while n in self.parent:
                p = self.parent[n]
                if stmt is None and isinstance(n, ast.stmt):
                    stmt = n
                if isinstance(p, ast.ClassDef):
                    names.insert(0, p.name)
                n = p
            target = None
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                t = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
                target = t.id if isinstance(t, ast.Name) else None
            return ".".join([*names, target or f"<line {getattr(stmt or node, 'lineno', 0)}>"])

        def const_node(self, name: str, fn: "Fn | None"):
            if fn is not None and (name in fn.assigned or name in fn.params):
                return None
            if fn is not None and fn.cls and f"{fn.cls}.{name}" in self.consts:
                return self.consts[f"{fn.cls}.{name}"]
            return self.consts.get(name)

        def const_value(self, e, fn: "Fn | None"):
            """The literal behind a Constant or a module/class constant, else MISSING."""
            if isinstance(e, ast.Constant):
                return e.value
            v = None
            if isinstance(e, ast.Name):
                v = self.const_node(e.id, fn)
            elif isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id in ("self", "cls") \
                    and fn is not None and fn.cls:
                v = self.consts.get(f"{fn.cls}.{e.attr}")
            return v.value if isinstance(v, ast.Constant) else MISSING

        def const_collection(self, e, fn):
            if isinstance(e, (ast.Tuple, ast.List, ast.Set)):
                return e
            if isinstance(e, ast.Name):
                v = self.const_node(e.id, fn)
                if isinstance(v, ast.Call) and v.args and _call_name(v) in ("frozenset", "set", "tuple", "list"):
                    v = v.args[0]
                if isinstance(v, (ast.Tuple, ast.List, ast.Set)):
                    return v
            return None

        def strings_of(self, e, fn) -> set[str]:
            """Strings a key can be: a literal, a constant, or a loop variable over a
        constant collection (`for k in _FLAG_KEYS: t[k] = ...`)."""
            v = self.const_value(e, fn)
            if isinstance(v, str):
                return {v}
            out: set[str] = set()
            if isinstance(e, ast.Name) and fn is not None:
                for kind, x in fn.assigned.get(e.id, []):
                    coll = self.const_collection(x, fn) if kind == "for" else None
                    if coll is not None:
                        out |= {c.value for c in coll.elts if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            return out

        # parameters and decisions ---------------------------------------------
        def derived(self, e, fn: "Fn | None", seen: frozenset = frozenset()):
            """The parameters `e` is computed from (rule 1), or None when it uses
        anything else: an attribute, a call other than bool()/.get()/..., a
        local bound from such a thing."""
            if fn is None:
                return None
            if isinstance(e, ast.Constant):
                return set()
            if isinstance(e, ast.Name):
                if e.id in fn.free:
                    return {e.id}
                if e.id in ("True", "False", "None") or self.const_node(e.id, fn) is not None:
                    return set()
                if e.id in seen or e.id not in fn.assigned:
                    return set() if e.id in seen else None
                out: set[str] = set()
                for kind, x in fn.assigned[e.id]:
                    if kind == "other":
                        return None
                    if kind == "for" and self.const_collection(x, fn) is not None:
                        continue
                    sub = self.derived(x, fn, seen | {e.id})
                    if sub is None:
                        return None
                    out |= sub
                return out
            if isinstance(e, ast.Call):
                f = e.func
                if isinstance(f, ast.Name) and f.id in DERIVING_CALLS:
                    parts = [*e.args, *(k.value for k in e.keywords)]
                elif isinstance(f, ast.Attribute) and f.attr in VALUE_METHODS:
                    parts = [f.value, *e.args]
                else:
                    return None
            elif isinstance(e, (ast.Compare, ast.BoolOp, ast.UnaryOp, ast.IfExp, ast.Subscript, ast.Tuple, ast.List,
                                ast.Set, ast.Dict, ast.JoinedStr, ast.FormattedValue, ast.BinOp, ast.Starred, ast.Slice,
                                ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp, ast.comprehension)):
                parts = [c for c in ast.iter_child_nodes(e) if isinstance(c, (ast.expr, ast.comprehension))]
            else:
                return None
            out = set()
            bound = {t.id for c in ast.walk(e) if isinstance(c, ast.comprehension)
                     for t in ast.walk(c.target) if isinstance(t, ast.Name)}
            for p in parts:
                sub = self.derived(p, fn, seen | bound)
                if sub is None:
                    return None
                out |= sub
            return out

        def judge(self, e, fn: "Fn | None", seen: frozenset = frozenset()):
            """OFF / DECISION / ("param", names) / CARRIED / ON for a value written to a switch."""
            v = self.const_value(e, fn)
            if v is not MISSING:
                return OFF if _is_off(v) else ON
            if isinstance(e, ast.Name):
                if fn is not None and e.id in fn.free:
                    return ("param", {e.id})
                if fn is None or e.id not in fn.assigned or e.id in seen:
                    return CARRIED
                results = []
                for kind, x in fn.assigned[e.id]:
                    if kind == "=":
                        results.append(self.judge(x, fn, seen | {e.id}))
                    elif kind == "for":
                        coll = self.const_collection(x, fn)
                        if coll is not None:
                            results += [self.judge(c, fn, seen | {e.id}) for c in coll.elts]
                        else:
                            ps = self.derived(x, fn)
                            results.append(("param", ps) if ps else CARRIED)
                    else:
                        results.append(CARRIED)
                return _combine(results)
            ps = self.derived(e, fn)
            if ps:
                return ("param", ps)
            if isinstance(e, ast.Call) and _call_name(e) in ("bool", "str", "int") and len(e.args) == 1:
                return self.judge(e.args[0], fn, seen)
            if isinstance(e, ast.IfExp):
                parts = [self.judge(e.body, fn, seen), self.judge(e.orelse, fn, seen)]
                return DECISION if any(p in (OFF, DECISION) for p in parts) else _combine(parts)
            if isinstance(e, ast.BoolOp):
                # `x or ""` hands on one of its operands; `a in b and c` is a decision
                # because its operands are
                parts = [self.judge(v, fn, seen) for v in e.values]
                last = parts[-1]
                if isinstance(e.op, ast.Or) and last == OFF and all(p in (CARRIED, ON) for p in parts[:-1]):
                    return CARRIED      # `x or False`: a default, not a decision
                return _combine(parts)
            if isinstance(e, ast.Compare) or (isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not)):
                return DECISION
            return CARRIED

    def _combine(results):
        for level in (OFF, DECISION):
            if level in results:
                return level
        ps = [r for r in results if isinstance(r, tuple)]
        if ps:
            return ("param", set().union(*(p[1] for p in ps)))
        return CARRIED if CARRIED in results else ON

    # ----------------------------------------------------------------- the scan

    class Scan:
        def __init__(self, sources: dict[str, str]):
            self.mods = {rel: Module(rel, src) for rel, src in sources.items()}
            self.by_stem = {m.stem: m for m in self.mods.values()}
            self.hits: list[Hit] = []
            self._seen: set = set()
            self.defs_by_name: dict[str, list] = {}
            for m in self.mods.values():
                for q, f in m.fns.items():
                    self.defs_by_name.setdefault(f.name, []).append((m.rel, q))
            self.setters: dict[tuple[str, str], set[str]] = {}    # (rel, qual) -> params that reach a switch
            self.alarms: dict[tuple[str, str], int] = {}          # (rel, qual) -> title param index, -1 if none
            self.resolved: dict[int, "tuple[str, str] | None"] = {}
            self.new_names = set().union(*(m.new_names for m in self.mods.values()))
            self._static: dict[int, list] = {}
            self.log_route_used = False                            # a hit relied on R7
            self.wrapper_used = False                              # a hit relied on R4's wrapper
            self._log_route_problems: "list[str] | None" = None
            for _ in range(8):     # setters calling setters, wrappers of wrappers
                size = (sum(len(v) for v in self.setters.values()), len(self.alarms))
                for m in self.mods.values():
                    for q, f in m.fns.items():
                        self._learn(m, f)
                if (sum(len(v) for v in self.setters.values()), len(self.alarms)) == size:
                    break
            for m in self.mods.values():
                self._scan(m)

        # resolution ----------------------------------------------------------
        def resolve(self, m: Module, call: ast.Call, fn: "Fn | None"):
            key = id(call)
            if key not in self.resolved:
                self.resolved[key] = self._resolve(m, call, fn)
            return self.resolved[key]

        def _resolve(self, m, call, fn):
            f = call.func
            if isinstance(f, ast.Name):
                if f.id in m.fns:
                    return (m.rel, f.id)
                if f.id in m.from_imports:
                    stem, name = m.from_imports[f.id]
                    tm = self.by_stem.get(stem)
                    return (tm.rel, name) if tm and name in tm.fns else None
                return None
            if not isinstance(f, ast.Attribute):
                return None
            base = f.value
            if not hasattr(m, "_self_aliases"):
                m._self_aliases = {t.id for x in ast.walk(m.tree) if isinstance(x, ast.Assign)
                                   and isinstance(x.value, ast.Subscript) and _ref(x.value.value) == "modules"
                                   for t in x.targets if isinstance(t, ast.Name)}
            if isinstance(base, ast.Name) and base.id in m._self_aliases:
                return (m.rel, f.attr) if f.attr in m.fns else None
            if isinstance(base, ast.Name) and base.id in m.imports:
                tm = self.by_stem.get(m.imports[base.id])
                return (tm.rel, f.attr) if tm and f.attr in tm.fns else None
            if isinstance(base, ast.Name) and base.id in m.from_imports:
                tm = self.by_stem.get(m.from_imports[base.id][1])
                if tm and f.attr in tm.fns:
                    return (tm.rel, f.attr)
            if isinstance(base, ast.Name) and base.id in ("self", "cls") and fn is not None:
                owner = fn.cls or fn.qual.split(".")[0]
                if f"{owner}.{f.attr}" in m.fns:
                    return (m.rel, f"{owner}.{f.attr}")
            cands = self.defs_by_name.get(f.attr, [])
            return cands[0] if len(cands) == 1 else None

        def _arg(self, call: ast.Call, target, param: str):
            f = self.mods[target[0]].fns[target[1]]
            for kw in call.keywords:
                if kw.arg == param:
                    return kw.value
            ps = f.method_params()
            if param in ps:
                i = ps.index(param)
                if i < len(call.args) and not any(isinstance(a, ast.Starred) for a in call.args[:i + 1]):
                    return call.args[i]
            return None

        # what the scan looks for -----------------------------------------------
        def _switch_containers(self, m, fn) -> set[str]:
            """Locals taken from a switch key: `ctl = task.get("enabledByController")`."""
            out = set()
            for name, binds in (fn.assigned.items() if fn else []):
                for kind, x in binds:
                    if kind != "=":
                        continue
                    if isinstance(x, ast.Subscript) and _switch_strings(m.strings_of(x.slice, fn)):
                        out.add(name)
                    elif isinstance(x, ast.Call) and _call_name(x) == "get" and x.args \
                            and _switch_strings(m.strings_of(x.args[0], fn)):
                        out.add(name)
            return out

        @staticmethod
        def _bool_keys(m, fn, nodes) -> set[str]:
            """Keys this function reads as on/off: `bool(x.get(K))`, `x.get(K, False)`."""
            out = set()
            for n in nodes:
                if not (isinstance(n, ast.Call) and _call_name(n) == "get" and n.args):
                    continue
                p = m.parent.get(n)
                as_bool = isinstance(p, ast.Call) and _call_name(p) == "bool" and p.args and p.args[0] is n
                bool_default = len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, bool)
                if as_bool or bool_default:
                    out |= m.strings_of(n.args[0], fn)
            return out

        def switch_writes(self, m: Module, fn: "Fn | None", nodes):
            """(node, value, what) for each value written to a switch or passed to a setter."""
            key = id(fn) if fn is not None else id(m)
            if key not in self._static:
                self._static[key] = list(self._static_writes(m, fn, nodes))
            yield from self._static[key]
            for n in (fn.calls if fn is not None else [x for x in nodes if isinstance(x, ast.Call)]):
                target = self.resolve(m, n, fn)
                for param in sorted(self.setters.get(target, ())):
                    a = self._arg(n, target, param)
                    if a is not None:
                        yield n, a, f"setter {target[1]}({param}=)"

        def _static_writes(self, m: Module, fn: "Fn | None", nodes):
            holders = self._switch_containers(m, fn)
            bool_keys = self._bool_keys(m, fn, nodes)
            for n in nodes:
                if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                    for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                        if isinstance(t, ast.Attribute) and SWITCH_KEY.match(t.attr):
                            yield n, n.value, f"sets .{t.attr}"
                        elif isinstance(t, ast.Subscript):
                            chain, root = [], t
                            while isinstance(root, ast.Subscript):
                                chain.append(root.slice)
                                root = root.value
                            keys = set().union(*(m.strings_of(s, fn) for s in chain))
                            if _switch_strings(keys) or (isinstance(root, ast.Name) and root.id in holders):
                                yield n, n.value, f"sets [{'/'.join(sorted(_switch_strings(keys))) or root.id}]"
                            elif m.strings_of(t.slice, fn) & bool_keys:
                                yield n, n.value, f"sets on/off option [{'/'.join(sorted(m.strings_of(t.slice, fn)))}]"
                            elif "value" in m.strings_of(t.slice, fn) and m.judge(n.value, fn) == OFF:
                                yield n, n.value, "sets a switch option's value"
                elif isinstance(n, ast.Dict):
                    p = m.parent.get(n)
                    if isinstance(p, ast.Return) or (isinstance(p, ast.Call) and _call_name(p) == "get"):
                        continue
                    keys = [m.strings_of(k, fn) if k is not None else set() for k in n.keys]
                    is_switch_option = any("type" in k and m.const_value(v, fn) == "switch" for k, v in zip(keys, n.values, strict=True))
                    for k, v in zip(keys, n.values, strict=True):
                        if _switch_strings(k) or (is_switch_option and "value" in k):
                            yield n, v, f"dict {{{'/'.join(sorted(k))}: ...}}"
                elif isinstance(n, ast.Call):
                    for kw in n.keywords:
                        if kw.arg and SWITCH_KEY.match(kw.arg):
                            yield n, kw.value, f"{kw.arg}="
                    if _call_name(n) == "setdefault" and len(n.args) == 2 and _switch_strings(m.strings_of(n.args[0], fn)):
                        yield n, n.args[1], "setdefault"

        def is_alarm_call(self, m, n, fn) -> bool:
            """A group send: `.send(..., alert=True)`, `.send_group()`, a wrapper of either, or
        a thread started on one (`Thread(target=self._push)`)."""
            if not isinstance(n, ast.Call):
                return False
            name = _call_name(n)
            if name == "send_group":      # the group also carries banner and drop notices: only failures count
                return bool(n.args) and bool(FAIL_TITLE.search(self._title_text(m, n.args[0], fn)))
            if name == "send" and any(kw.arg == "alert" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                                      for kw in n.keywords):
                return True
            target = self.resolve(m, n, fn)
            if target is not None and self.alarms.get(target, -1) >= 0:
                return True
            for kw in n.keywords:
                if kw.arg == "target":
                    ref = self._resolve(m, ast.Call(func=kw.value, args=[], keywords=[]), fn)
                    if ref in self.alarms:       # the thread runs a function that alarms
                        return True
            return False

        def on_alarm_path(self, m, fn) -> bool:
            """Sends an alarm itself, or calls a function that does (one level up)."""
            if (m.rel, fn.qual) in self.alarms:
                return True
            return any(self.resolve(m, n, fn) in self.alarms for n in fn.calls)

        def _learn(self, m: Module, f: Fn):
            for _, value, _ in self.switch_writes(m, f, f.nodes):
                j = m.judge(value, f)
                if isinstance(j, tuple):
                    self.setters.setdefault((m.rel, f.qual), set()).update(j[1])
            for n in f.calls:
                if self.is_alarm_call(m, n, f):
                    target = self.resolve(m, n, f)
                    pos = self.alarms.get(target, 0) if target in self.alarms else 0
                    title = n.args[pos] if len(n.args) > pos else None
                    ps = f.method_params()
                    idx = ps.index(title.id) if isinstance(title, ast.Name) and title.id in ps else -1
                    self.alarms[(m.rel, f.qual)] = max(self.alarms.get((m.rel, f.qual), -2), idx)

        # hits ----------------------------------------------------------------
        def add(self, m: Module, node, rule: str, what: str, key: "str | None" = None, fn: "Fn | None" = None):
            if key is None:
                key = fn.qual if fn is not None else m.where(node)
            line = getattr(node, "lineno", 0)
            sig = (m.rel, line, key, rule)
            if sig in self._seen:
                return
            self._seen.add(sig)
            src = m.lines[line - 1].strip() if 0 < line <= len(m.lines) else ""
            self.hits.append(Hit(m.rel, line, f"{m.rel}:{key}", rule, f"{what} :: {src[:120]}", node, fn))

        def _scan(self, m: Module):
            routed = self._route_collections(m)
            units = [(f, f.nodes) for f in m.fns.values()] + [(None, m.top_nodes)]
            for fn, nodes in units:
                self._scan_switches(m, fn, nodes)
                self._scan_removals(m, fn, nodes)
                self._scan_names(m, fn, nodes, routed)
                self._scan_logs(m, fn, nodes)
                self._scan_info_sends(m, fn, nodes)
                self._scan_skips(m, fn, nodes)
                self._scan_flags(m, fn, nodes)
                if fn is not None and self.on_alarm_path(m, fn):
                    self._scan_guards(m, fn)
            for name in sorted(routed):
                for e in m.consts[name].elts:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str) and FAIL_TITLE.search(e.value):
                        self.add(m, e, "MUTE-route", f"route_of keeps {e.value!r} from the group", key=f"{name}[{e.value}]")

        def _scan_switches(self, m, fn, nodes):
            for n, value, what in self.switch_writes(m, fn, nodes):
                j = m.judge(value, fn)
                if j in (OFF, DECISION):
                    self.add(m, value if hasattr(value, "lineno") else n, "OFF-literal" if j == OFF else "OFF-decision",
                             what, fn=fn)
            for n in nodes:
                if not isinstance(n, (ast.Constant, ast.Name)):
                    continue
                v = m.const_value(n, fn)
                if not (isinstance(v, str) and v in CLOSE_STRINGS):
                    continue
                if self._close_written(m, fn, n):
                    self.add(m, n, "OFF-close", f"writes {v!r}", fn=fn)

        def _close_written(self, m, fn, n, seen: frozenset = frozenset()) -> bool:
            """Whether the value `n` reaches a write (see OFF-close in the docstring). A
        local it is assigned to is followed to where that local is used."""
            x, p = n, m.parent.get(n)
            while (isinstance(p, ast.IfExp) and x is not p.test) or isinstance(p, (ast.BoolOp, ast.Tuple, ast.List,
                                                                                    ast.Set, ast.Starred, ast.keyword)) \
                    or (isinstance(p, ast.Dict) and x in p.values):
                x, p = p, m.parent.get(p)
            if isinstance(p, (ast.Assign, ast.AnnAssign)) and p.value is x:
                targets = p.targets if isinstance(p, ast.Assign) else [p.target]
                if any(isinstance(t, (ast.Subscript, ast.Attribute)) for t in targets):
                    return True
                if fn is None:
                    return False            # a module constant: judged where it is used
                names = {t.id for t in targets if isinstance(t, ast.Name)} - seen
                return any(isinstance(u, ast.Name) and u.id in names and isinstance(u.ctx, ast.Load)
                           and self._close_written(m, fn, u, seen | names) for u in fn.nodes)
            if isinstance(p, ast.Return):
                return True
            if not isinstance(p, ast.Call) or x is p.func or _is_log(p):
                return False
            if WRITE_CALL.match(_call_name(p)) or _call_name(p) == "setdefault":
                return True
            target = self.resolve(m, p, fn)
            return target is not None and (target in self.setters or self.mods[target[0]].fns[target[1]].writes)

        def _scan_removals(self, m, fn, nodes):
            def tasky(e) -> bool:
                if isinstance(e, ast.Name):
                    return bool(TASKY.search(e.id))
                if isinstance(e, ast.Attribute):
                    return bool(TASKY.search(e.attr))
                if isinstance(e, ast.Subscript):
                    return any(TASKY.search(s) for s in m.strings_of(e.slice, fn)) or tasky(e.value)
                if isinstance(e, ast.Call) and _call_name(e) in ("get", "list"):
                    inner = e.func.value if isinstance(e.func, ast.Attribute) else (e.args[0] if e.args else None)
                    return any(isinstance(a, ast.Constant) and isinstance(a.value, str) and TASKY.search(a.value)
                               for a in e.args) or (inner is not None and tasky(inner))
                return False

            def filtered(e, seen=frozenset()) -> bool:
                """A filtering comprehension, or a local list rebuilt by conditional appends."""
                if any(isinstance(c, ast.comprehension) and c.ifs for c in ast.walk(e)):
                    return True
                for name in {x.id for x in ast.walk(e) if isinstance(x, ast.Name)} - seen:
                    binds = fn.assigned.get(name, [])
                    if any(x is not None and filtered(x, seen | {name}) for _, x in binds):
                        return True
                    if any(kind == "=" and isinstance(x, ast.List) and not x.elts for kind, x in binds):
                        for c in nodes:
                            if isinstance(c, ast.Call) and _call_name(c) == "append" and isinstance(c.func, ast.Attribute):
                                recv = c.func.value
                                if name in {x.id for x in ast.walk(recv) if isinstance(x, ast.Name)} \
                                        and (isinstance(recv, ast.IfExp) or _inside_if(m, c, fn)):
                                    return True
                return False

            if fn is None:
                return
            put_back = {(ast.dump(n.func.value), ast.dump(n.args[-1])) for n in nodes
                        if isinstance(n, ast.Call) and _call_name(n) in ("insert", "append") and n.args
                        and isinstance(n.func, ast.Attribute)}
            for n in nodes:
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and API_REMOVE.match(n.value) \
                        and isinstance(m.parent.get(n), ast.Call):
                    self.add(m, n, "OFF-remove", f"calls {n.value}", fn=fn)
                elif isinstance(n, ast.Call) and _call_name(n) == "get" and any(
                        isinstance(a, ast.Constant) and isinstance(a.value, str) and "disabled" in a.value.lower()
                        for a in n.args) and not self._reenable_only(m, fn):
                    self.add(m, n, "OFF-keep", "reads a record of tasks kept off", fn=fn)
                if not fn.writes:
                    continue
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                        and n.func.attr in ("remove", "discard", "pop") and tasky(n.func.value):
                    if not (n.args and (ast.dump(n.func.value), ast.dump(n.args[0])) in put_back):
                        self.add(m, n, "OFF-remove", f"{n.func.attr}() on a task list", fn=fn)
                elif isinstance(n, ast.Delete) and any(isinstance(t, ast.Subscript) and tasky(t.value) for t in n.targets):
                    self.add(m, n, "OFF-remove", "del on a task list", fn=fn)
                elif isinstance(n, ast.Assign) and any(tasky(t) for t in n.targets) and filtered(n.value):
                    self.add(m, n, "OFF-remove", "task list rebuilt without some of its entries", fn=fn)

        def switch_profile(self, target) -> set:
            """How a function sets switches: the judgment of each of its writes (ON, OFF,
        DECISION, CARRIED, or "param" when it is a setter)."""
            m = self.mods[target[0]]
            f = m.fns[target[1]]
            return {"param" if isinstance(j, tuple) else j
                    for j in (m.judge(value, f) for _, value, _ in self.switch_writes(m, f, f.nodes))}

        def _reenable_only(self, m, fn) -> bool:
            """R6: `fn` switches tasks back on and nothing else - it calls a writer whose
        every switch write is ON, and no switch write of its own or of anything it
        calls is anything but ON (a setter's own write is judged at fn's call)."""
            if self.switch_profile((m.rel, fn.qual)) - {ON}:
                return False
            enables = False
            for c in fn.calls:
                t = self.resolve(m, c, fn)
                if t is None or t == (m.rel, fn.qual) or t in self.setters:
                    continue
                prof = self.switch_profile(t)
                if prof - {ON}:
                    return False
                enables = enables or (bool(prof) and self.mods[t[0]].fns[t[1]].writes)
            return enables

        def _scan_names(self, m, fn, nodes, routed):
            for n in nodes:
                if isinstance(n, ast.Name):
                    name = n.id
                elif isinstance(n, ast.Attribute):
                    name = n.attr
                elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = n.name
                else:
                    continue
                if name in routed:
                    continue
                rule = "MUTE-name" if MUTE_NAME.search(name) else "MUTE-cap" if CAP_NAME.match(name) else None
                if rule is None:
                    continue
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.add(m, n, rule, f"def {name}", key=m.fn_of_node[n].qual)
                    continue
                p = m.parent.get(n)
                if fn is None and isinstance(p, (ast.Assign, ast.AnnAssign)) and isinstance(n, ast.Name) \
                        and p.value is not None and n is not p.value:
                    coll = p.value
                    if isinstance(coll, ast.Call) and coll.args and _call_name(coll) in ("frozenset", "set", "tuple", "list"):
                        coll = coll.args[0]
                    coll = coll if isinstance(coll, (ast.Tuple, ast.List, ast.Set)) else None
                    elts = [e for e in (coll.elts if coll is not None else []) if isinstance(e, ast.Constant)]
                    if elts:
                        for e in elts:
                            self.add(m, e, rule, f"{name} lists {e.value!r}", key=f"{m.where(e)}[{e.value}]")
                        continue
                self.add(m, n, rule, name, fn=fn)
            for n in nodes:
                if isinstance(n, ast.Compare) and self._fixed_filter(m, fn, n):
                    self.add(m, n, "MUTE-filter", "failed tasks tested against a fixed list", fn=fn)

        def _fixed_filter(self, m, fn, n: ast.Compare) -> bool:
            if not any(isinstance(o, (ast.LtE, ast.Lt, ast.In, ast.NotIn)) for o in n.ops):
                return False

            def failish(e):
                return any((isinstance(x, ast.Name) and "fail" in x.id.lower())
                           or (isinstance(x, ast.Attribute) and "fail" in x.attr.lower())
                           or (isinstance(x, ast.Constant) and isinstance(x.value, str) and "fail" in x.value.lower())
                           for x in ast.walk(e))

            def fixed(e):
                if isinstance(e, (ast.Set, ast.Tuple, ast.List)):
                    return bool(e.elts) and all(isinstance(x, ast.Constant) for x in e.elts)
                if isinstance(e, ast.Name):
                    return m.const_collection(e, fn) is not None
                return isinstance(e, ast.Attribute) and e.attr.isupper()

            if not any(fixed(s) for s in n.comparators):
                return False
            if failish(n.left):
                return True
            # `for f in failed: if f in SKIP: continue`
            if isinstance(n.left, ast.Name) and fn is not None:
                sources = [x for k, x in fn.assigned.get(n.left.id, []) if k == "for"]
                parent = m.parent.get(n)
                return any(failish(x) for x in sources) and isinstance(parent, ast.If) \
                    and any(isinstance(s, (ast.Continue, ast.Return)) for s in parent.body)
            return False

        def _scan_logs(self, m, fn, nodes):
            for n in nodes:
                if not _is_log(n):
                    continue
                text = " ".join(c.value for a in n.args for c in ast.walk(a)
                                if isinstance(c, ast.Constant) and isinstance(c.value, str))
                if hit := MUTE_LOG.search(text):
                    self.add(m, n, "MUTE-log", hit.group(0), fn=fn)
                for kw in n.keywords:
                    if kw.arg == "extra" and any(isinstance(c, ast.Call) and _call_name(c).split(".")[-1] == "recovered"
                                                 for c in ast.walk(kw.value)):
                        self.add(m, n, "MUTE-recovered", "recovered by itself: daily report only, not the group", fn=fn)
                if hit := KEEP_LOG.search(text):
                    self.add(m, n, "OFF-keep", hit.group(0), fn=fn)

        def _title_text(self, m, e, fn) -> str:
            """The literal text of a title: a string, a texts.* constant, or a texts.* function's returns."""
            v = m.const_value(e, fn)
            if isinstance(v, str):
                return v
            if isinstance(e, ast.JoinedStr):
                return "".join(c.value for c in e.values if isinstance(c, ast.Constant))
            target = None
            if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id in m.imports:
                tm = self.by_stem.get(m.imports[e.value.id])
                c = tm.consts.get(e.attr) if tm else None
                return c.value if isinstance(c, ast.Constant) and isinstance(c.value, str) else ""
            if isinstance(e, ast.Call):
                target = self.resolve(m, e, fn)
            if target is None:
                return ""
            tf = self.mods[target[0]].fns[target[1]]
            return " ".join(c.value for r in tf.nodes if isinstance(r, ast.Return) and r.value is not None
                            for c in ast.walk(r.value) if isinstance(c, ast.Constant) and isinstance(c.value, str))

        def _scan_skips(self, m, fn, nodes):
            """OK-WW's own "skipped, not failed" stop, in code or in code the relay patches into OK-WW."""
            base, subs = self.skip_classes(m)
            for n in nodes:
                if isinstance(n, ast.Raise) and n.exc is not None and _words(n.exc) & base:
                    self.add(m, n, "OFF-skip", f"raise {SKIP_SIGNAL}: OK-WW ends the task as skipped, not failed", fn=fn)
                elif isinstance(n, ast.Raise) and n.exc is not None and (sub := _words(n.exc) & subs):
                    self.add(m, n, "OFF-skip", f"raise {'/'.join(sorted(sub))}, a subclass of {SKIP_SIGNAL}: "
                                           "skipped, not failed, unless the relay turns it into a failure", fn=fn)
                elif isinstance(n, ast.Constant) and isinstance(n.value, str) and (hit := PATCH_OFF.search(n.value)) \
                        and id(n) not in m.docstrings and self._injected(m, n):
                    self.add(m, n, "OFF-skip", f"code patched into OK-WW: {hit.group(0)}", fn=fn)

        @staticmethod
        def skip_classes(m) -> tuple[set[str], set[str]]:
            """(names of TaskDisabledException in `m` - itself and its import aliases,
        names of its subclasses - `class S(TDE)` or `S = type("S", (TDE,), {})`)."""
            if hasattr(m, "_skip_classes"):
                return m._skip_classes
            base = {SKIP_SIGNAL} | {a.asname or a.name for x in ast.walk(m.tree) if isinstance(x, ast.ImportFrom)
                                    for a in x.names if a.name == SKIP_SIGNAL}
            subs: set[str] = set()
            while True:
                known, found = base | subs, set()
                for x in ast.walk(m.tree):
                    if isinstance(x, ast.ClassDef) and any(_words(b) & known for b in x.bases):
                        found.add(x.name)
                    elif isinstance(x, (ast.Assign, ast.AnnAssign)) and isinstance(x.value, ast.Call) \
                            and _call_name(x.value) == "type" and len(x.value.args) >= 2 and _words(x.value.args[1]) & known:
                        targets = x.targets if isinstance(x, ast.Assign) else [x.target]
                        found |= {t.id for t in targets if isinstance(t, ast.Name)}
                if not found - known:
                    break
                subs |= found - base
            m._skip_classes = (base, subs)
            return m._skip_classes

        def _scan_flags(self, m, fn, nodes):
            """OFF-flag: a step skipped while a marker file at a constant path exists."""
            if fn is None:
                return
            for n in nodes:
                if not isinstance(n, ast.If) or not n.body \
                        or not isinstance(n.body[-1], (ast.Return, ast.Continue, ast.Break, ast.Raise)):
                    continue
                for c in _unnegated_calls(n.test):
                    path = _exists_target(c)
                    if path is None or not self._constant_path(m, fn, path):
                        continue
                    if any(isinstance(r, ast.Call) and _call_name(r) in ("read_text", "read_bytes", "open")
                           and any(ast.dump(x) == ast.dump(path) for x in (getattr(r.func, "value", None), *r.args)
                                   if x is not None) for r in ast.walk(n.test)):
                        continue     # `F.is_file() and F.read_text() == x`: what the file says, not that it is there
                    self.add(m, n, "OFF-flag", f"skips the step while the marker file {ast.unparse(path)} exists", fn=fn)
                    break

        def _constant_path(self, m, fn, e, depth: int = 0) -> bool:
            """`e` is a fixed path: a string, a module constant, a local bound only to
        such, or Path() / os.path.join() / `/` / an f-string of those."""
            if depth > 4:
                return False
            if isinstance(e, ast.Constant):
                return isinstance(e.value, str)
            if isinstance(e, ast.Name):
                if fn is not None and e.id in fn.free:
                    return False
                if fn is not None and e.id in fn.assigned:
                    binds = fn.assigned[e.id]
                    return all(k == "=" and self._constant_path(m, fn, x, depth + 1) for k, x in binds)
                v = m.const_node(e.id, fn)
                return v is not None and self._constant_path(m, None, v, depth + 1)
            if isinstance(e, ast.Call) and _call_name(e) in PATH_BUILDERS and e.args and not e.keywords:
                return all(self._constant_path(m, fn, a, depth + 1) for a in e.args)
            if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Div):
                return self._constant_path(m, fn, e.left, depth + 1) and self._constant_path(m, fn, e.right, depth + 1)
            if isinstance(e, ast.JoinedStr):
                return all(isinstance(v, ast.Constant) for v in e.values)
            return False

        def _injected(self, m, n) -> bool:
            """A string that is the `new=` text of a patch (old versions kept only to be found and removed are not)."""
            p = m.parent.get(n)
            if isinstance(p, ast.keyword) and p.arg == "new":
                return True
            return isinstance(p, ast.Assign) and m.scope.get(n) is None and m.where(n) in self.new_names

        def failure_info_send(self, m, n, fn) -> str:
            """The title text when `n` is a notifier .send() of a failure-shaped title without alert=True."""
            if not (isinstance(n, ast.Call) and _call_name(n) == "send" and n.args and isinstance(n.func, ast.Attribute)):
                return ""
            recv = n.func.value
            recv_name = recv.attr if isinstance(recv, ast.Attribute) else recv.id if isinstance(recv, ast.Name) else ""
            if "notifier" not in recv_name.lower():
                return ""
            kws = {kw.arg: kw.value for kw in n.keywords}
            if any(isinstance(kws.get(k), ast.Constant) and kws[k].value is True for k in ("alert", "daily")):
                return ""
            text = self._title_text(m, n.args[0], fn)
            return text if text and FAIL_TITLE.search(text) else ""

        def _scan_info_sends(self, m, fn, nodes):
            for n in nodes:
                if text := self.failure_info_send(m, n, fn):
                    self.add(m, n, "MUTE-info", f"failure-shaped title sent without alert=True: {text[:40]!r}", fn=fn)

        def _scan_guards(self, m, fn):
            def leads(x) -> bool:
                return self.is_alarm_call(m, x, fn) or (isinstance(x, ast.Call) and self.resolve(m, x, fn) in self.alarms) \
                    or bool(self.failure_info_send(m, x, fn))
            sends = [n.lineno for n in fn.nodes if leads(n)]
            if not sends:
                return
            last = max(sends)
            for n in fn.nodes:
                if not isinstance(n, ast.If) or n.lineno >= last or not n.body \
                        or not isinstance(n.body[-1], (ast.Return, ast.Continue, ast.Break)):
                    continue
                if any(self.is_alarm_call(m, x, fn) or (isinstance(x, ast.Call) and self.resolve(m, x, fn) in self.alarms) for b in n.body for x in ast.walk(b)):
                    continue      # it alarms on its own way out (an info send there is a demotion: still a hit)
                if isinstance(n.body[-1], (ast.Continue, ast.Break)):
                    # skipping an item only matters when the alarm is inside that loop
                    loop = m.parent.get(n)
                    while loop is not None and loop is not fn.node and not isinstance(loop, (ast.For, ast.While)):
                        loop = m.parent.get(loop)
                    if not isinstance(loop, (ast.For, ast.While)) or not any(
                            leads(x) and x.lineno > n.lineno for x in ast.walk(loop)):
                        continue
                if any(isinstance(x, ast.Call) and _call_name(x).startswith("send") for x in ast.walk(n.test)):
                    continue      # `if notifier.send(...): return` - the send failed, retry later
                # Back through locals too: `if push not in (...)` where push = ..., and
                # `if "no-shutdown" in done` where done = store.get("marks", f"alerted:{day}").
                words, todo, seen = _words(n.test), [(n.test, 0)], set()
                while todo:
                    expr, depth = todo.pop()
                    for name in {x.id for x in ast.walk(expr) if isinstance(x, ast.Name)} - seen:
                        seen.add(name)
                        for _, x in fn.assigned.get(name, []):
                            if x is not None and depth < 2:
                                words |= _words(x)
                                todo.append((x, depth + 1))
                once = sorted(w for w in words if DEDUPE.search(w))
                kind = sorted(w for w in words if FAILKIND.search(w))
                # `if pid in self._handled: return` where the module adds to _handled: once per key
                once += [f"{_ref(c.comparators[0])} (added to elsewhere)" for c in ast.walk(n.test)
                         if isinstance(c, ast.Compare) and isinstance(c.ops[0], ast.In)
                         and _ref(c.comparators[0]) in self._grown(m)]
                # `if v.code not in _STUCK_CODES: return`: a fixed list decides which kinds alarm
                kind += [f"{c.comparators[0].id} (fixed list)" for c in ast.walk(n.test)
                         if isinstance(c, ast.Compare) and isinstance(c.ops[0], (ast.In, ast.NotIn))
                         and isinstance(c.comparators[0], ast.Name) and m.const_collection(c.comparators[0], fn) is not None]
                if once:
                    self.add(m, n, "MUTE-once", "early exit before the alarm on " + ", ".join(sorted(set(once))), fn=fn)
                elif kind:
                    self.add(m, n, "MUTE-guard", "early exit before the alarm on " + ", ".join(sorted(set(kind))), fn=fn)

        def _grown(self, m: Module) -> set[str]:
            """Containers the module adds keys to (`x.add(k)`, `x.append(k)`, `x[k] = v`)."""
            if not hasattr(m, "_grown"):
                out = set()
                for n in ast.walk(m.tree):
                    if isinstance(n, ast.Call) and _call_name(n) in ("add", "append") and isinstance(n.func, ast.Attribute):
                        out.add(_ref(n.func.value))
                    elif isinstance(n, ast.Assign):
                        out |= {_ref(t.value) for t in n.targets if isinstance(t, ast.Subscript)}
                m._grown = out - {""}
            return m._grown

        @staticmethod
        def _route_collections(m) -> set[str]:
            f = m.fns.get("route_of")
            if f is None:
                return set()
            return {n.id for n in f.nodes if isinstance(n, ast.Name) and m.const_collection(n, None) is not None}

        # rule 2: a stored command applied --------------------------------------
        def user_command(self, hit: Hit) -> str:
            """The user's action a hit applies (rule 2), or ''."""
            m, fn, node = self.mods[hit.rel], hit.fn, hit.node
            if fn is None or node is None:
                return ""
            control = None
            if isinstance(node, ast.If) and hit.rule in ("MUTE-once", "MUTE-guard"):
                control = node.test
            else:
                n = node
                while n in m.parent and n is not fn.node:
                    p = m.parent[n]
                    if isinstance(p, ast.If) and n is not p.test:
                        control = p.test
                        break
                    if isinstance(p, (ast.For, ast.AsyncFor)) and n is not p.iter and n is not p.target:
                        control = p.iter
                        break
                    n = p
            if control is None:
                return ""
            return self._reader_action(m, fn, control)

        def _reader_action(self, m, fn, test) -> str:
            """The stored command whose reader `test` calls, directly or through a local."""
            readers = {v: k for k, v in COMMAND_RECORDS.items()}
            for c in self._reader_calls(m, fn, test, frozenset()):
                target = self.resolve(m, c, fn)
                if target and f"{target[0]}:{target[1]}" in readers:
                    return readers[f"{target[0]}:{target[1]}"]
            return ""

        # R3 - R8b ----------------------------------------------------------------
        def allowed(self, hit: Hit) -> str:
            """The narrow rule a hit passes by, or ''."""
            return (self._one_push(hit) or self._relay_power_off(hit) or self._restored(hit) or self._log_route(hit)
                    or self._game_counter(hit) or self._ends_failed(hit))

        def _one_push(self, hit: Hit) -> str:
            m, fn, n = self.mods[hit.rel], hit.fn, hit.node
            if hit.rule != "MUTE-once" or fn is None or not isinstance(n, ast.If):
                return ""
            mark = ""
            for ln in (n.lineno, n.lineno - 1):
                if 0 < ln <= len(m.lines) and (mt := ONE_PUSH.search(m.lines[ln - 1])):
                    mark = mt.group(1).strip()
                    break
            if not mark:
                return ""
            keys = []
            for c in ast.walk(n.test):
                if isinstance(c, ast.Compare) and isinstance(c.ops[0], (ast.In, ast.NotIn)):
                    keys.append(c.left)
                elif isinstance(c, ast.Call) and DEDUPE.search(_call_name(c)):
                    keys += [*c.args, *(k.value for k in c.keywords)]
            return f"R3 one fault, one push: {mark}" if any(self._identity(fn, k) for k in keys) else ""

        def _identity(self, fn, e, depth: int = 0) -> bool:
            """R3 (b): `e` names a per-occurrence identity, through simple local assignments."""
            def counts(name) -> bool:
                binds = fn.assigned.get(name, [])
                return bool(IDENTITY.search(name)) and not (
                    binds and all(k == "=" and _constant_only(x) for k, x in binds))
            if isinstance(e, ast.Name):
                binds = fn.assigned.get(e.id, [])
                if counts(e.id):
                    return True
                if depth == 0 and binds and all(k == "=" for k, _ in binds):
                    return all(self._identity(fn, x, 1) for _, x in binds)
                return False
            for x in ast.walk(e):
                if isinstance(x, ast.Name) and counts(x.id):
                    return True
                if isinstance(x, ast.Attribute) and IDENTITY.search(x.attr):
                    return True
                if isinstance(x, ast.Subscript) and isinstance(x.slice, ast.Constant) \
                        and isinstance(x.slice.value, str) and IDENTITY.search(x.slice.value):
                    return True
            return False

        def _relay_power_off(self, hit: Hit) -> str:
            """R4: in service.py, under errwatch.relay_shutdown_issued() and nothing else."""
            m, fn, n = self.mods[hit.rel], hit.fn, hit.node
            if hit.rel not in R4_FILES or fn is None or n is None:
                return ""
            if hit.rule in ("MUTE-guard", "MUTE-once") and isinstance(n, ast.If):
                tests = [n.test]
            elif hit.rule == "MUTE-log" and _is_log(n) and n.func.attr in ("info", "debug"):
                tests, x = [], n
                while x in m.parent and x is not fn.node:
                    p = m.parent[x]
                    if isinstance(p, ast.If) and x in p.body:
                        tests.append(p.test)
                    x = p
            else:
                return ""
            signal, wrapper = tuple(RELAY_POWER_OFF.split(":")), tuple(R4_WRAPPER.split(":"))
            for t in tests:
                for c in _positive_calls(t):
                    target = self.resolve(m, c, fn)
                    if target == wrapper:
                        self.wrapper_used = True
                    if (target == signal and not c.args and not c.keywords) \
                            or (target == wrapper and not self.wrapper_problems()):
                        return f"R4 the relay itself issued the power-off ({_call_name(c)})"
            return ""

        def wrapper_problems(self) -> list[str]:
            """R4: R4_WRAPPER waits for relay_shutdown_issued() and asks nothing else."""
            rel, qual = R4_WRAPPER.split(":")
            wm = self.mods.get(rel)
            wf = wm.fns.get(qual) if wm is not None else None
            if wf is None:
                return [f"R4: {R4_WRAPPER} does not exist"]
            out, asked = [], False
            for c in wf.calls:
                target = self.resolve(wm, c, wf)
                if target == tuple(RELAY_POWER_OFF.split(":")) and not c.args and not c.keywords:
                    asked = True
                elif _call_name(c) not in WRAPPER_PLAIN_CALLS:
                    out.append(f"R4: {R4_WRAPPER} line {c.lineno} calls {_call_name(c)}(): "
                           "not the relay's own power-off signal")
            if not asked:
                out.append(f"R4: {R4_WRAPPER} does not ask errwatch.relay_shutdown_issued()")
            return out

        def _restored(self, hit: Hit) -> str:
            """R5: `old = setter(x, False)` given back in a `finally:` of the same function."""
            m, fn, v = self.mods[hit.rel], hit.fn, hit.node
            if hit.rule != "OFF-literal" or fn is None:
                return ""
            p = m.parent.get(v)
            call = m.parent.get(p) if isinstance(p, ast.keyword) else p
            if not isinstance(call, ast.Call):
                return ""
            slot = ("kw", p.arg) if isinstance(p, ast.keyword) else ("pos", next(
                (i for i, a in enumerate(call.args) if a is v), -1))
            target = self.resolve(m, call, fn)
            asg = m.parent.get(call)
            if target not in self.setters or slot == ("pos", -1) or not (
                    isinstance(asg, ast.Assign) and asg.value is call and len(asg.targets) == 1
                    and isinstance(asg.targets[0], ast.Name)):
                return ""
            old = asg.targets[0].id

            def value_at(c):
                if slot[0] == "pos":
                    return c.args[slot[1]] if slot[1] < len(c.args) else None
                return next((k.value for k in c.keywords if k.arg == slot[1]), None)

            def rest(c):
                args = [ast.dump(a) for i, a in enumerate(c.args) if slot != ("pos", i)]
                return args, sorted(ast.dump(k) for k in c.keywords if slot != ("kw", k.arg))

            for t in fn.nodes:
                if not isinstance(t, ast.Try) or not t.finalbody or not (
                        t.lineno > asg.lineno or any(asg is x for b in t.body for x in ast.walk(b))):
                    continue
                for b in t.finalbody:
                    for r in ast.walk(b):
                        if not isinstance(r, ast.Call) or self.resolve(m, r, fn) != target or rest(r) != rest(call):
                            continue
                        back = value_at(r)
                        if isinstance(back, ast.Name) and back.id == old:
                            return f"R5 put back in finally ({old})"
                        under = _body_if(m, r, fn)
                        if isinstance(back, ast.Constant) and back.value is True and under is not None \
                                and isinstance(under.test, ast.Name) and under.test.id == old \
                                and any(under is x for x in ast.walk(b)):
                            return f"R5 put back in finally (if {old})"
            return ""

        def _log_route(self, hit: Hit) -> str:
            """R7: notify's 「不推送」 line, in `if route == "log"`, route from route_of alone."""
            m, fn, n = self.mods[hit.rel], hit.fn, hit.node
            if hit.rule != "MUTE-log" or fn is None or f"{hit.rel}:{fn.qual}" != LOG_ROUTE_SITE or not _is_log(n):
                return ""
            guard, in_body = _nearest_if(m, n, fn)
            t = guard.test if guard is not None and in_body else None
            if not (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)):
                return ""
            sides = [t.left, t.comparators[0]]
            name = next((x.id for x in sides if isinstance(x, ast.Name)), None)
            if name is None or not any(isinstance(x, ast.Constant) and x.value == LOG_ROUTE for x in sides):
                return ""
            binds = fn.assigned.get(name, [])
            if len(binds) != 1 or binds[0][0] != "=" or not isinstance(binds[0][1], ast.Call) \
                    or self.resolve(m, binds[0][1], fn) != tuple(LOG_ROUTER.split(":")):
                return ""
            self.log_route_used = True
            return "" if self.log_route_problems() else "R7 the log route is route_of's routed collections alone"

        def log_route_problems(self) -> list[str]:
            """R7 on route_of: "log" only under a test of the title against its routed
        collections, and no failure-shaped string that such a test lets through."""
            if self._log_route_problems is not None:
                return self._log_route_problems
            rel, qual = LOG_ROUTER.split(":")
            m = self.mods.get(rel)
            f = m.fns.get(qual) if m is not None else None
            if f is None:
                self._log_route_problems = [f"R7: {LOG_ROUTER} does not exist"]
                return self._log_route_problems
            routed, out, matchers = self._route_collections(m), [], []
            title = (f.method_params() or [None])[0]
            for r in f.nodes:
                if not isinstance(r, ast.Return):
                    continue
                v = m.const_value(r.value, f) if r.value is not None else MISSING
                if not isinstance(v, str):
                    out.append(f"R7: {LOG_ROUTER} line {r.lineno} returns something other than a route name")
                    continue
                if v != LOG_ROUTE:
                    continue
                guard, in_body = _nearest_if(m, r, f)
                tests = _title_tests(m, guard.test, title, routed) if guard is not None and in_body else None
                if not tests:
                    out.append(f'R7: {LOG_ROUTER} line {r.lineno} returns "{LOG_ROUTE}" other than under a test of '
                           f"the title against {', '.join(sorted(routed)) or 'a routed collection'}")
                    continue
                matchers += tests
            for how, coll in matchers:
                items = [e.value for e in m.const_collection(ast.Name(id=coll), None).elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                for om in self.mods.values():
                    for text, line in _plain_strings(om):
                        if not FAIL_TITLE.search(text):
                            continue
                        for item in items:
                            if (how == "prefix" and text.startswith(item)) or (how == "contains" and item in text) \
                                    or (how == "equals" and text == item):
                                out.append(f"R7: {om.rel}:{line} failure-shaped {text[:40]!r} is routed to "
                                       f"\"{LOG_ROUTE}\" by {coll}[{item}]")
            self._log_route_problems = out
            return out

        def _game_counter(self, hit: Hit) -> str:
            """R8: `raise TaskDisabledException` in the true branch of `x == 0`, x read off
        the game screen in the same function, the reading and the branch logged."""
            m, fn, n = self.mods[hit.rel], hit.fn, hit.node
            if hit.rule != "OFF-skip" or fn is None or not isinstance(n, ast.Raise) \
                    or not _words(n.exc) & self.skip_classes(m)[0]:
                return ""
            guard, in_body = _nearest_if(m, n, fn)
            t = guard.test if guard is not None and in_body else None
            if not (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)):
                return ""
            sides = [t.left, t.comparators[0]]
            zero = any(isinstance(x, ast.Constant) and type(x.value) is int and x.value == 0 for x in sides)
            name = next((x.id for x in sides if isinstance(x, ast.Name)), None)
            chain = _screen_chain(fn, name) if zero and name else set()
            if not chain:
                return ""
            branch_logs = any(_is_task_log(x) and x.lineno < n.lineno for b in guard.body for x in ast.walk(b))
            reading_logged = any(_is_task_log(c) and any(isinstance(y, ast.Name) and y.id in chain
                                                         for a in [*c.args, *(k.value for k in c.keywords)]
                                                         for y in ast.walk(a)) for c in fn.calls)
            return f"R8 the game's own counter reads 0 ({name}, off the screen)" if branch_logs and reading_logged else ""

        def _ends_failed(self, hit: Hit) -> str:
            """R8b: a subclass of TaskDisabledException that the same file turns into a failure."""
            m, fn, n = self.mods[hit.rel], hit.fn, hit.node
            if hit.rule != "OFF-skip" or fn is None or not isinstance(n, ast.Raise):
                return ""
            base, subs = self.skip_classes(m)
            words = _words(n.exc)
            sub = words & subs
            if not sub or words & base:
                return ""
            skips = base | subs
            handlers = [h for h in ast.walk(m.tree) if isinstance(h, ast.ExceptHandler) and h.type is not None
                        and _words(h.type) & sub]
            for h in handlers:
                if any(_failure_raise(x, skips) for b in h.body for x in ast.walk(b)):
                    return f"R8b turned into a failure in its handler (line {h.lineno})"
            flags = {t.attr for x in fn.nodes if isinstance(x, ast.Assign) and x.lineno < n.lineno
                     for t in x.targets if isinstance(t, ast.Attribute)}
            for h in handlers:
                g, tr = m.scope.get(h), m.parent.get(h)
                if g is None or not isinstance(tr, ast.Try) or (h.body and isinstance(h.body[-1], ast.Raise)):
                    continue      # it always raises on: only (a) above can make that a failure
                for r in g.nodes:
                    if not _failure_raise(r, skips) or r.lineno <= tr.end_lineno:
                        continue
                    guard, in_body = _nearest_if(m, r, g)
                    if guard is not None and in_body and _expr_words(g, guard.test) & flags:
                        attr = "/".join(sorted(_expr_words(g, guard.test) & flags))
                        return (f"R8b recorded as .{attr} and raised as a failure after its handler "
                            f"(line {h.lineno}, raise line {r.lineno})")
            return ""

        def _reader_calls(self, m, fn, e, seen):
            """Calls in `e`, following locals that hold nothing but a call's result."""
            out = []
            if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not):
                e = e.operand
            if isinstance(e, ast.Call):
                out.append(e)
            elif isinstance(e, ast.Name) and e.id in fn.assigned and e.id not in seen:
                binds = fn.assigned[e.id]
                if all(k == "=" and isinstance(x, ast.Call) for k, x in binds):
                    for _, x in binds:
                        out += self._reader_calls(m, fn, x, seen | {e.id})
            return out

    def _ref(e) -> str:
        """`self._handled` -> "_handled", `seen` -> "seen"; '' for anything else."""
        return e.attr if isinstance(e, ast.Attribute) else e.id if isinstance(e, ast.Name) else ""

    def _words(e) -> set[str]:
        """Names, attributes and strings in an expression."""
        if e is None:
            return set()
        return {x.id if isinstance(x, ast.Name) else x.attr if isinstance(x, ast.Attribute) else x.value
                for x in ast.walk(e) if isinstance(x, (ast.Name, ast.Attribute))
                or (isinstance(x, ast.Constant) and isinstance(x.value, str))}

    def _switch_strings(keys: set[str]) -> set[str]:
        return {k for k in keys if SWITCH_KEY.match(k)}

    def _is_log(n) -> bool:
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute) or n.func.attr not in LOG_METHODS:
            return False
        b = n.func.value
        name = b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else ""
        return "log" in name.lower()

    def _body_if(m: Module, node, fn: Fn):
        """The nearest `if` whose body (not its test, not its else) holds `node`, or None."""
        x = node
        while x in m.parent and x is not fn.node:
            p = m.parent[x]
            if isinstance(p, ast.If) and any(x is s for s in p.body):
                return p
            x = p
        return None

    def _positive_calls(test) -> list:
        """Calls a condition makes true by being true: the call itself, or one and-ed in."""
        if isinstance(test, ast.Call):
            return [test]
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            return [c for v in test.values for c in _positive_calls(v)]
        return []

    def _constant_only(e) -> bool:
        """An expression built from constants alone (no name, attribute, call or subscript)."""
        return not any(isinstance(x, (ast.Name, ast.Attribute, ast.Call, ast.Subscript)) for x in ast.walk(e))

    def _nearest_if(m: Module, node, fn: Fn):
        """(the nearest `if` around `node`, whether `node` is in its body - not its test
    or its else); (None, False) when there is none inside `fn`."""
        x = node
        while x in m.parent and x is not fn.node:
            p = m.parent[x]
            if isinstance(p, ast.If):
                return p, any(x is b for b in p.body)
            x = p
        return None, False

    def _is_task_log(n) -> bool:
        """A log line: `log.info(...)`, or OK-WW's own `self.log_info(...)`."""
        return _is_log(n) or (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in TASK_LOGS)

    def _unnegated_calls(test) -> list:
        """Calls in a condition that are not under a `not`."""
        out, todo = [], [test]
        while todo:
            e = todo.pop()
            if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not):
                continue
            if isinstance(e, ast.Call):
                out.append(e)
            todo += list(ast.iter_child_nodes(e))
        return out

    def _exists_target(c: ast.Call):
        """The path an existence test asks about: `os.path.exists(p)` -> p, `p.exists()` -> p."""
        f = c.func
        if not isinstance(f, ast.Attribute):
            return None
        if f.attr in EXISTS_FUNCS and isinstance(f.value, ast.Attribute) and f.value.attr == "path" and c.args:
            return c.args[0]
        if f.attr in EXISTS_METHODS and not c.args and not c.keywords:
            return f.value
        return None

    def _title_tests(m: Module, test, title, routed: set[str]):
        """R7: [(how, collection)] when `test` checks the title against routed
    collections and nothing else - `title.startswith(C)`, `any(s in title for s
    in C)`, `title in C`, or an `or` of those; None otherwise."""
        def is_title(e):
            return isinstance(e, ast.Name) and e.id == title

        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
            parts = [_title_tests(m, v, title, routed) for v in test.values]
            return None if any(p is None for p in parts) else [x for p in parts for x in p]
        if isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute) and test.func.attr == "startswith" \
                and is_title(test.func.value) and len(test.args) == 1 and not test.keywords \
                and isinstance(test.args[0], ast.Name) and test.args[0].id in routed:
            return [("prefix", test.args[0].id)]
        if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.In) \
                and is_title(test.left) and isinstance(test.comparators[0], ast.Name) and test.comparators[0].id in routed:
            return [("equals", test.comparators[0].id)]
        if isinstance(test, ast.Call) and _call_name(test) == "any" and len(test.args) == 1 \
                and isinstance(test.args[0], ast.GeneratorExp) and len(test.args[0].generators) == 1:
            g, gen = test.args[0], test.args[0].generators[0]
            e = g.elt
            if not gen.ifs and isinstance(gen.target, ast.Name) and isinstance(gen.iter, ast.Name) \
                    and gen.iter.id in routed and isinstance(e, ast.Compare) and len(e.ops) == 1 \
                    and isinstance(e.ops[0], ast.In) and isinstance(e.left, ast.Name) and e.left.id == gen.target.id \
                    and is_title(e.comparators[0]):
                return [("contains", gen.iter.id)]
        return None

    def _plain_strings(m: Module):
        """(text, line) of every string in `m` that could be a title: literals and the
    literal parts of f-strings, not docstrings and not the arguments of a log line."""
        for n in ast.walk(m.tree):
            if isinstance(n, ast.JoinedStr):
                text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in m.docstrings \
                    and not isinstance(m.parent.get(n), ast.JoinedStr):
                text = n.value
            else:
                continue
            x = n
            while x in m.parent and not isinstance(x, ast.stmt) and not _is_log(x):
                x = m.parent[x]
            if not _is_log(x):
                yield text, n.lineno

    def _is_screen_read(c) -> bool:
        """OK-WW reading text off the game screen: `self.ocr(...)` / `task.ocr(...)`."""
        return isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == SCREEN_READ \
            and isinstance(c.func.value, ast.Name)

    def _screen_chain(fn: Fn, name: str) -> set[str]:
        """R8: the locals from `name` back to a screen read in `fn`, when every binding
    on the way is a constant, a screen read, or built from such locals alone (no
    parameter, no `self`, no `+=`); empty otherwise."""
        chain, todo, rooted = set(), [name], False
        while todo:
            x = todo.pop()
            if x in chain:
                continue
            if x in fn.params or not fn.assigned.get(x):
                return set()
            chain.add(x)
            for kind, e in fn.assigned[x]:
                if kind == "other" or e is None:
                    return set()
                if _constant_only(e):
                    continue
                reads = [c for c in ast.walk(e) if _is_screen_read(c)]
                rooted = rooted or bool(reads)
                inside = {id(y) for c in reads for y in ast.walk(c)}
                for y in ast.walk(e):
                    if id(y) in inside or not isinstance(y, ast.Name):
                        continue
                    if y.id in fn.params:
                        return set()
                    if y.id in fn.assigned:
                        todo.append(y.id)
        return chain if rooted else set()

    def _failure_raise(r, skips: set[str]) -> bool:
        """`raise X(...)` of a class that is neither TaskDisabledException nor a subclass of it."""
        if not isinstance(r, ast.Raise) or r.exc is None:
            return False
        e = r.exc.func if isinstance(r.exc, ast.Call) else r.exc
        name = e.id if isinstance(e, ast.Name) else e.attr if isinstance(e, ast.Attribute) else ""
        return bool(name) and name not in skips

    def _expr_words(fn: Fn, e) -> set[str]:
        """_words of `e` and of what its locals are bound to, two assignments deep."""
        words, todo, seen = _words(e), [(e, 0)], set()
        while todo:
            expr, depth = todo.pop()
            for name in {x.id for x in ast.walk(expr) if isinstance(x, ast.Name)} - seen:
                seen.add(name)
                for _, x in fn.assigned.get(name, []):
                    if x is not None and depth < 2:
                        words |= _words(x)
                        todo.append((x, depth + 1))
        return words

    def _inside_if(m: Module, node, fn: Fn) -> bool:
        n = node
        while n in m.parent and n is not fn.node:
            p = m.parent[n]
            if isinstance(p, ast.If) and n is not p.test:
                return True
            n = p
        return False

    # ----------------------------------------------------------------- the list

    # The key may hold spaces (`_LOG_ONLY_PREFIXES[⚠️ 自动采集：…]`): it is everything before the first " | ".
    LINE_RE = re.compile(r"^(?P<key>[^|\s][^|]*?\.py:[^|]*?\S)\s+\|\s+(?P<what>.+?)\s+\|\s+(?P<words>.+?)\s+\|\s+(?P<when>.+?)\s*$")
    QUOTE_RE = re.compile(r"「[^」]*[\u4e00-\u9fff][^」]*」")
    WHEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}\b")

    def read_list(text: str) -> tuple[dict[str, str], list[str]]:
        """{key: line}, and what is wrong with lines that lack one of the four fields."""
        out, bad = {}, []
        for i, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            mt = LINE_RE.match(line)
            if not mt:
                bad.append(f"USER-SWITCHES.txt:{i}: not `file:function | what | 「his words」 | YYYY-MM-DD HH:MM`")
                continue
            if not QUOTE_RE.search(mt["words"]):
                bad.append(f"USER-SWITCHES.txt:{i}: {mt['key']}: no quote of the user's own Chinese words in 「」")
            if not WHEN_RE.match(mt["when"]):
                bad.append(f"USER-SWITCHES.txt:{i}: {mt['key']}: no date and time (YYYY-MM-DD HH:MM)")
            out[mt["key"]] = line
        return out, bad

    def relay_sources(root: Path = RELAY) -> dict[str, str]:
        files = sorted((root / "ark_relay").rglob("*.py")) + [root / "service.py", root / "boot_stages.py",
                                                                   root / "watchdog_guard.py"]
        return {f.relative_to(root).as_posix(): f.read_text(encoding="utf-8") for f in files if f.is_file()}

    def command_records_hold(scan: Scan) -> list[str]:
        """Rule 2's readers are what COMMAND_RECORDS says: whitelisted, dispatched, present."""
        out = []
        cm = scan.mods.get("ark_relay/features/commands.py")
        if cm is None:
            return ["commands.py not found: rule 2 cannot be checked"]
        allowed = set()
        for name in ("REVERSIBLE", "MUTATING"):
            coll = cm.const_collection(ast.Name(id=name), None)
            allowed |= {e.value for e in (coll.elts if coll is not None else []) if isinstance(e, ast.Constant)}
        apply = cm.fns.get("apply_command")
        dispatched = {c.comparators[0].value for c in (apply.nodes if apply else [])
                      if isinstance(c, ast.Compare) and isinstance(c.left, ast.Name) and c.left.id == "action"
                      and isinstance(c.comparators[0], ast.Constant)}
        for action, reader in COMMAND_RECORDS.items():
            rel, qual = reader.split(":")
            if action not in allowed:
                out.append(f"rule 2: {action} is not in commands.REVERSIBLE | MUTATING")
            if action not in dispatched:
                out.append(f"rule 2: commands.apply_command does not dispatch {action}")
            if rel not in scan.mods or qual not in scan.mods[rel].fns:
                out.append(f"rule 2: the reader {reader} does not exist")
        return out

    # Queue pulls behind a module switch. The scan finds the API delete inside
    # commands.skip_script_in_queue, but not relay code that reaches it through a
    # default-argument wrapper (stagegate._gate_due -> skipper=_skip_default -> it), so
    # such a pull is named here: while its switch is on, the place is a hit like any
    # other and needs its line with the user's words. Read from the source (a literal
    # True / False at module level), not by importing the module.
    SWITCHED_PULLS = {"ark_relay/features/stagegate.py:_gate_due": "PULL_FROM_QUEUE"}

    def switched_pulls(sources: dict[str, str]) -> tuple[list[Hit], list[str]]:
        """(a hit for each SWITCHED_PULLS place whose switch is on, what is wrong with the table)."""
        hits, problems = [], []
        for key, flag in SWITCHED_PULLS.items():
            rel, _, fn = key.partition(":")
            if rel not in sources:
                problems.append(f"SWITCHED_PULLS: {rel} is gone")
                continue
            value, at = None, None
            for node in ast.parse(sources[rel]).body:
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == flag for t in node.targets):
                    value = node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == flag:
                    value = node.value
                elif isinstance(node, ast.FunctionDef) and node.name == fn:
                    at = node.lineno
            if at is None:
                problems.append(f"SWITCHED_PULLS: {key} - no such function any more")
            elif not (isinstance(value, ast.Constant) and isinstance(value.value, bool)):
                problems.append(f"SWITCHED_PULLS: {rel} must set {flag} to a literal True / False at module level")
            elif value.value:
                hits.append(Hit(rel, at, key, "OFF-pull",
                                f"{flag} is on: takes a script out of a queue (commands.skip_script_in_queue)"))
        return hits, problems

    def verdict(hits: list[Hit], listed: dict[str, str]) -> list[str]:
        fails = [f"{h.rel}:{h.line}: {h.key} [{h.rule}] is not in USER-SWITCHES.txt - {h.text}"
                 for h in hits if h.key not in listed]
        keys = {h.key for h in hits}
        fails += [f"USER-SWITCHES.txt: {k} has no hit any more - delete the line (a stale line pre-approves the next one)"
                  for k in listed if k not in keys]
        return fails

    def findings(scan: Scan) -> tuple[list[Hit], list[tuple[Hit, str]], list[tuple[Hit, str]]]:
        """(hits that need a line, hits that apply a stored user command, hits that pass R3-R5)."""
        need, commands, allowed = [], [], []
        for h in sorted(scan.hits, key=lambda h: (h.rel, h.line, h.rule)):
            if action := scan.user_command(h):
                commands.append((h, action))
            elif why := scan.allowed(h):
                allowed.append((h, why))
            else:
                need.append(h)
        return need, commands, allowed

    # ----------------------------------------------------------------- self-checks

    LOG = "import logging\nlog = logging.getLogger()\n"
    ERRWATCH = ("def going_down(extra=None):\n    return False\ndef system_shutting_down():\n    return False\n"
            "def relay_shutdown_issued():\n    return False\n")
    AUTO_START = dedent('''\
    import json
    def _auto(path, value):
        data = json.loads(path.read_text())
        was = bool(data.get("Auto Start", False))
        data["Auto Start"] = value
        path.write_text(json.dumps(data))
        return was
    ''')
    COMMAND_SAMPLE_BASE = {
        "ark_relay/features/commands.py": ('REVERSIBLE = {"debug_mode", "skip_today"}\nMUTATING = set()\n'
                              'def apply_command(cmd):\n    action = cmd["action"]\n'
                              '    if action == "debug_mode":\n        return 1\n'
                              '    if action == "skip_today":\n        return 2\n'),
        "ark_relay/features/modes.py": ('from . import queues\ndef debug_active(d):\n    return False\n'
                           'def _day_queues(store, day):\n    return []\n'
                           'def _maybe_engage(store, d, day):\n    wanted = _day_queues(store, day)\n'
                           '    for queue in wanted:\n        queues.apply(d, queue, enabled=False)\n'),
        "ark_relay/features/queues.py": 'def apply(d, name, enabled=None):\n    pass\n',
    }
    ESTOP_SAMPLE = {
        "ark_relay/features/commands.py": dedent('''\
        ESTOP_SEED = ({"start": "2026-09-30T09:46:28+08:00", "end": "2026-09-30T09:47:22+08:00"},)
        def _estop_windows_path(d):
            return d
        def _estop_window_mark(d, start):
            atomic_write_text(_estop_windows_path(d), start)
        def merge_estop_seed(d):
            atomic_write_text(_estop_windows_path(d), str(ESTOP_SEED))
        def estop_windows(d):
            return []
        def estop_label(windows, started, finished):
            return ""
        def estop(state_dir=None):
            _estop_window_mark(state_dir, "now")
            return True, ""
        '''),
        "ark_relay/features/handle.py": dedent('''\
        from . import commands
        def _estop_overlap(eng, rec):
            try:
                return commands.estop_label(commands.estop_windows(eng.d), rec.started, rec.finished)
            except Exception:
                pass
            return ""
        def backfill(eng, entries):
            windows = commands.estop_windows(eng.d)
            for e in entries:
                if not (label := commands.estop_label(windows, e["s"], e["f"])):
                    continue
                e["raw"]["manual_stop"] = label
        def _handle(eng, rec):
            if stop := _estop_overlap(eng, rec):
                rec.raw["manual_stop"] = stop
            if rec.raw.get("manual_stop"):
                return
            eng.notifier.send("❌ 失败", "b", alert=True)
        '''),
        "boot_stages.py": dedent('''\
        def _make_phone_cmd(cfg_state_dir):
            def run_phone_cmd(body):
                action = str(body.get("action") or "")
                if action == "estop":
                    from ark_relay.features.phone import commands as _cmd
                    ok, msg = _cmd.estop(state_dir=cfg_state_dir)
                    return
            return run_phone_cmd
        '''),
    }
    # R7 on a sample shaped like notify.py.
    NOTIFY = dedent('''\
    import logging
    log = logging.getLogger()
    _LOG_ONLY_PREFIXES = ("🔄 中继已更新", "✅ ")
    def route_of(title, *, alert=False, daily=False):
        if daily:
            return "daily"
        if title.startswith(_LOG_ONLY_PREFIXES):
            return "log"
        if alert:
            return "group"
        return "info"
    class Notifier:
        def send(self, title, body, *, alert=False, daily=False):
            route = route_of(title, alert=alert, daily=daily)
            if route == "log":
                log.info("不推送（日报或手机页已有）：%s", title)
                return []
            return self._fan_out(title, body)
    ''')
    # R8 on a sample shaped like ark_overrides' click_configured_boss_level.
    BOSS = dedent('''\
    def _left(text):
        return 0 if "0/3" in text else None
    class T:
        def click_level(self):
            left = None
            try:
                left = self.ocr(box=self.box_of_screen(0.58, 0.80, 0.98, 0.90))
                self.log_info(f"剩余次数原文: {left}")
            except Exception:
                pass
            text = " ".join(str(b) for b in (left or []))
            now = _left(text)
            if now == 0:
                self.log_info("本周次数已领满（0/3），跳过")
                raise TaskDisabledException()
            return now
    ''')
    # R8b on a sample shaped like ark_overrides' _ArkStop / _end_failed / FarmEchoTask.run.
    STOP = dedent('''\
    class Stopped(Exception):
        pass
    _Stop = Exception
    def install():
        global _Stop
        from ok import TaskDisabledException as _TDE
        _Stop = type("Stop", (_TDE,), {})
    def end_failed(task, why):
        task._failed = why
        raise _Stop()
    def run(self):
        try:
            got = self.inner()
        except _Stop:
            got = None
        why = getattr(self, "_failed", None)
        if why:
            raise Stopped(why)
        return got
    ''')
    BAD = {
        "literal False to enabled": ('def f(t):\n    t["enabled"] = False\n', "OFF-literal"),
        "If-switch off, deep key": ('def f(cfg):\n    cfg["Task"]["IfSanity"] = 0\n', "OFF-literal"),
        "flag keys in a loop": ('KEYS = ("enabled", "enabledByController")\ndef f(t):\n'
                            '    for k in KEYS:\n        t[k] = False\n', "OFF-literal"),
        "per-controller copy": ('def f(task):\n    ctl = task.get("enabledByController")\n'
                            '    for k in ctl:\n        ctl[k] = False\n', "OFF-literal"),
        "dict literal written": ('def f(api):\n    api.post({"Info": {"TimeEnabled": False}})\n', "OFF-literal"),
        "switch option": ('def f(ov):\n    ov["X"] = {"type": "switch", "value": False}\n', "OFF-literal"),
        "keyword enabled=False": ('from . import queues\ndef f(d, q):\n    queues.apply(d, q, enabled=False)\n',
                                  "OFF-literal"),
        "attribute switch": ('def f(task):\n    task.enabled = False\n', "OFF-literal"),
        "decision through a setter": ('import json\ndef _set(t, on):\n    t["enabled"] = on\n'
                                  'def narrow(path, want):\n    doc = json.loads(path.read_text())\n'
                                  '    for t in doc["tasks"]:\n        _set(t, t["taskName"] in want)\n',
                                      "OFF-decision"),
        "literal through a setter": ('def set_task(path, name, value):\n    j = {}\n'
                                 '    j[name] = {"enabled": bool(value)}\n'
                                 'def g(p):\n    set_task(p, "AutoCollect", False)\n', "OFF-literal"),
        "local decision": ('def f(t, store, now):\n    state = store.load()\n'
                       '    on = state.get("done") != week_key(now)\n    t["checked"] = on\n', "OFF-decision"),
        "Close constant to a writer": ('CLOSED = "Close"\ndef _write_setting(d, v):\n    d.write_text(v)\n'
                                   'class G:\n    def enforce(self):\n        _write_setting(self.d, CLOSED)\n',
                                       "OFF-close"),
        "Close in an API payload": ('def f(sid):\n    _mas("/api/scripts/user/update", '
                                '{"scriptId": sid, "data": {"Info": {"Annihilation": "Close"}}})\n', "OFF-close"),
        "Close stored in a config": ('def f(info, done):\n    info["Annihilation"] = "Close" if done else "x"\n',
                                     "OFF-close"),
        "task removed": ('def f(cfg, write):\n    tasks = list(cfg["TaskList"])\n'
                     '    tasks.remove("Weekly")\n    cfg["TaskList"] = tasks\n    write(cfg)\n', "OFF-remove"),
        "task list filtered": ('def f(cfg, path):\n    cfg["tasks"] = [t for t in cfg["tasks"] if t["n"] != "x"]\n'
                           '    path.write_text(str(cfg))\n', "OFF-remove"),
        "task list rebuilt": ('def f(doc, path, gone):\n    for inst in doc["instances"]:\n        keep = []\n'
                          '        for t in inst["tasks"]:\n            if t["n"] not in gone:\n'
                          '                keep.append(t)\n        inst["tasks"] = keep\n'
                          '    atomic_write_text(path, doc)\n', "OFF-remove"),
        "routes narrowed": ('def f(task, lists, failed, path):\n'
                        '    kept = {k: [r for r in v if r in failed] for k, v in lists.items()}\n'
                        '    for k, v in kept.items():\n        task["optionValues"][k]["caseNames"] = v\n'
                        '    atomic_write_text(path, task)\n', "OFF-remove"),
        "queue item deleted": ('def f(mas, q):\n    mas("/api/queue/item/delete", {"queueId": q})\n', "OFF-remove"),
        "queue item run days trimmed": ('def f(item, qid, uid, today):\n    run_days = [d for d in item["Days"] if d != today]\n'
                                    '    _mas("/api/queue/item/update", {"queueId": qid, "queueItemId": uid,'
                                    ' "data": {"Schedule": {"Days": run_days}}})\n', "OFF-remove"),
        "kept off by record": ('def f(store):\n    rec = store.get("updates", "x_disabled_y")\n    return rec\n',
                               "OFF-keep"),
        "kept off by log": (LOG + 'def f():\n    log.info("还是坏的，继续关着")\n', "OFF-keep"),
        "soft set": ('class E:\n    SOFT_FAILS = {"自动采集"}\n', "MUTE-name"),
        "soft use": ('def f(rec, eng):\n    if set(rec.failed_tasks) <= eng.SOFT_FAILS:\n        return\n', "MUTE-name"),
        "soft_only def": ('def soft_only(msg, soft):\n    return True\n', "MUTE-name"),
        "failed vs fixed set": ('def f(e):\n    if set(e["failed_tasks"]) <= {"A", "B"}:\n        return "s"\n',
                                "MUTE-filter"),
        "failed skipped by list": ('PASS = frozenset({"A"})\ndef f(failed):\n    for x in failed:\n'
                               '        if x in PASS:\n            continue\n', "MUTE-filter"),
        "daily-only log": (LOG + 'def f(r):\n    log.warning("%s 记日报不拉警报", r)\n', "MUTE-log"),
        "recovered, daily only": (LOG + 'from . import errwatch\ndef f(r):\n'
                              '    log.warning("%s 断了又好了", r, extra=errwatch.recovered())\n', "MUTE-recovered"),
        "f-string log": (LOG + 'def f(r):\n    log.info(f"{r} 只进日报")\n', "MUTE-log"),
        "log phrase in a later argument": (LOG + 'def f(r, ok):\n    log.info("%s", "只进日报" if ok else "x")\n',
                                           "MUTE-log"),
        "route table": ('_LOG_ONLY_PREFIXES = ("🔄 中继已更新", "⚠️ 采集没走通")\n'
                    'def route_of(t):\n    if t.startswith(_LOG_ONLY_PREFIXES):\n        return "log"\n'
                    '    return "group"\n', "MUTE-route"),
        "failure sent as information": ('def f(eng, b):\n    eng.notifier.send("❌ 采集失败", b)\n', "MUTE-info"),
        "failure title from a function": ('def title(s):\n    return f"⚠️ {s} 没能确认"\n'
                                      'def f(eng, b):\n    eng.notifier.send(title("x"), b)\n', "MUTE-info"),
        "hourly cap": ('MAX_PER_HOUR = 3\ndef room(p):\n    return len(p) < MAX_PER_HOUR\n', "MUTE-cap"),
        "once per key": ('def push(eng, key, t, b):\n    if eng._already_alerted(key):\n        return True\n'
                     '    eng.notifier.send(t, b, alert=True)\n', "MUTE-once"),
        "kind guard": ('def push(eng, rec, t, b):\n    if rec.maintenance:\n        return\n'
                   '    eng.notifier.send_group("❌ 采集失败", b)\n', "MUTE-guard"),
        "guard before a wrapper": ('def _send(eng, title, body):\n    eng.notifier.send(title, body, alert=True)\n'
                               'def push(eng, rec):\n    for f in rec.items:\n'
                               '        if f.cause == "soft":\n            continue\n        _send(eng, "x", f)\n',
                                   "MUTE-guard"),
        "OK-WW stop raised": ('class TaskDisabledException(Exception):\n    pass\n'
                          'def stop(t):\n    raise TaskDisabledException()\n', "OFF-skip"),
        "OK-WW stop patched in": ('_X_NEW = """    self.log_info(\'x\')\n    raise TaskDisabledException()"""\n'
                              'P = _Patch(new=_X_NEW)\n', "OFF-skip"),
        "on/off option through a setter": ('import json\ndef _set(path, value):\n    data = json.loads(path.read_text())\n'
                                       '    was = bool(data.get("Auto Start", False))\n    data["Auto Start"] = value\n'
                                       '    path.write_text(json.dumps(data))\ndef run(p):\n    _set(p, False)\n',
                                           "OFF-literal"),
        "membership dedupe": ('class W:\n    def tick(self, pid):\n        if pid in self._done:\n            return\n'
                          '        self._done.add(pid)\n        self.notifier.send("❌ 卡住", "b", alert=True)\n', "MUTE-once"),
        "fixed list of alarming kinds": ('STUCK = ("a", "b")\ndef say(eng, v):\n    if v.code not in STUCK:\n        return\n'
                                     '    eng.notifier.send("t", "b", alert=True)\n', "MUTE-guard"),
        "guard before a thread that alarms": ('import threading\nclass A:\n    def emit(self, r):\n        if self._sent:\n'
                                          '            return\n        threading.Thread(target=self._push).start()\n'
                                          '    def _push(self):\n        self.n.send("t", "b", alert=True)\n', "MUTE-once"),
        "alarm demoted to information": ('def f(eng, rec):\n    if rec.maintenance:\n        eng.notifier.send("⏸ 进不了游戏", "b")\n'
                                     '        return\n    eng.notifier.send("❌ 失败", "b", alert=True)\n', "MUTE-guard"),
        "debug-like guard not a stored command": ('def debug_active(d):\n    return True\n'
                                              'def check(eng):\n    if debug_active(eng.d):\n        return\n'
                                              '    eng.notifier.send("t", "b", alert=True)\n', "MUTE-guard"),
        # R3: the marker alone is not enough, and an identity alone is not enough
        "one-push marker on a per-day key": (dedent('''\
        def push(eng, day, rec, t, b):
            key = f"{day}|{rec.script}|{rec.user}"
            # one fault, one push: once a day per script
            if eng._already_alerted(day, key):
                return
            eng.notifier.send(t, b, alert=True)
        '''), "MUTE-once"),
        "per-record key without the marker": (dedent('''\
        def push(eng, day, rec, t, b):
            key = f"x|{rec.run_id}"
            if eng._already_alerted(day, key):
                return
            eng.notifier.send(t, b, alert=True)
        '''), "MUTE-once"),
        "one-push marker on a constant member": (dedent('''\
        def say(eng, day):
            done = eng.store.get("marks", f"alerted:{day}") or []
            # one fault, one push: once a day
            if "no-shutdown" in done:
                return
            eng.notifier.send("t", "b", alert=True)
        '''), "MUTE-once"),
        "an identity name bound to a constant": (dedent('''\
        def say(eng, sent):
            text = "今晚不关机"
            # one fault, one push: the same text
            if text in sent:
                return
            sent.add(text)
            eng.notifier.send("t", "b", alert=True)
        '''), "MUTE-once"),
        "one-push marker two lines above": (dedent('''\
        def push(eng, day, rec, t, b):
            key = f"x|{rec.run_id}"
            # one fault, one push: one record
            # (something else in between)
            if eng._already_alerted(day, key):
                return
            eng.notifier.send(t, b, alert=True)
        '''), "MUTE-once"),
        # R4: only service.py, only relay_shutdown_issued(), only its true branch, only below WARNING
        "the relay's power-off outside service.py": ({"ark_relay/features/errwatch.py": ERRWATCH, "ark_relay/_sample.py": LOG + dedent('''\
        from . import errwatch
        def f(eng):
            if errwatch.relay_shutdown_issued():
                log.info("按关机处理，不算故障")
                return
        ''')}, "MUTE-log"),
        "the relay's power-off negated": ({"ark_relay/features/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        def f(eng):
            from ark_relay.features.alarm import errwatch
            if not errwatch.relay_shutdown_issued():
                log.info("按关机处理，不算故障")
        ''')}, "MUTE-log"),
        "the else of the relay's power-off": ({"ark_relay/features/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        def f(eng):
            from ark_relay.features.alarm import errwatch
            if errwatch.relay_shutdown_issued():
                pass
            else:
                log.info("按关机处理，不算故障")
        ''')}, "MUTE-log"),
        "the relay's power-off asked with an argument": ({"ark_relay/features/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        def f(eng):
            from ark_relay.features.alarm import errwatch
            if errwatch.relay_shutdown_issued(lambda: True):
                log.info("按关机处理，不算故障")
        ''')}, "MUTE-log"),
        "a WARNING kept from the group at the relay's power-off": ({"ark_relay/features/errwatch.py": ERRWATCH,
                                                                    "service.py": LOG + dedent('''\
        def f(eng):
            from ark_relay.features.alarm import errwatch
            if errwatch.relay_shutdown_issued():
                log.warning("按关机处理，不算故障")
        ''')}, "MUTE-log"),
        "a wrapper that asks something besides the relay's power-off": ({"ark_relay/features/errwatch.py": ERRWATCH,
                                                                           "service.py": LOG + dedent('''\
        def _going_down_soon():
            from ark_relay.features.alarm import errwatch
            return errwatch.relay_shutdown_issued() or errwatch.system_shutting_down()
        def f(eng):
            if _going_down_soon():
                log.info("按关机处理，不算故障")
        ''')}, "MUTE-log"),
        "Windows going down": ({"ark_relay/features/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        def f(eng):
            from ark_relay.features.alarm import errwatch
            if errwatch.going_down():
                log.info("按关机处理，不算故障")
        ''')}, "MUTE-log"),
        "a wrapper that asks Windows going down": ({"ark_relay/features/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        import time
        def _going_down_soon(seconds=15.0):
            from ark_relay.features.alarm import errwatch
            deadline = time.monotonic() + seconds
            while not errwatch.going_down():
                if deadline - time.monotonic() <= 0:
                    return False
                time.sleep(0.5)
            return True
        class K:
            def exited(self):
                if _going_down_soon():
                    log.info("按关机处理，不算故障")
                    return
                log.warning("意外退出")
        ''')}, "MUTE-log"),
        # R5: given back in a finally, by the same setter, for the same thing - or it is a hit
        "temporary setting never put back": (AUTO_START + dedent('''\
        def run(p):
            was = _auto(p, False)
            launch(p)
        '''), "OFF-literal"),
        "put back, but not in a finally": (AUTO_START + dedent('''\
        def run(p):
            was = _auto(p, False)
            launch(p)
            _auto(p, was)
        '''), "OFF-literal"),
        "a finally that puts back another file": (AUTO_START + dedent('''\
        def run(p, q):
            was = _auto(p, False)
            try:
                launch(p)
            finally:
                _auto(q, was)
        '''), "OFF-literal"),
        # R6: a reader that also keeps something off
        "record read to switch on and off": (dedent('''\
        def enable(cfg, names):
            for t in cfg["tasks"]:
                if t["n"] in names:
                    t["enabled"] = True
            cfg.write_text("x")
        def disable(cfg, names):
            for t in cfg["tasks"]:
                t["enabled"] = False
            cfg.write_text("x")
        def keep(store, cfg):
            rec = store.get("updates", "x_disabled")
            enable(cfg, set())
            disable(cfg, set(rec.get("tasks") or []))
        '''), "OFF-keep"),
        "debug mode keeping an alarm away": ({**COMMAND_SAMPLE_BASE, "ark_relay/features/handle.py": (
            'from . import modes\ndef check(eng):\n    if modes.debug_active(eng.d):\n'
        '        return\n    eng.notifier.send("t", "b", alert=True)\n')}, "MUTE-guard"),
        "debug mode's 不报漏跑 line": ({**COMMAND_SAMPLE_BASE, "ark_relay/core/engine.py": LOG + (
            'from . import modes\ndef tick(eng):\n    if modes.debug_active(eng.d):\n'
        '        log.info("调试模式生效：不关机、不报漏跑")\n')}, "MUTE-log"),
        "the debug verdict's early exit": ({**COMMAND_SAMPLE_BASE, "ark_relay/features/shutdown.py": dedent('''\
        from . import modes
        def decide(eng):
            if modes.debug_active(eng.d):
                return V(False, "debug", "x")
            return V(True, "go", "")
        def maybe(eng):
            v = decide(eng)
            if v.code == "debug":
                return False
            eng.notifier.send("t", "b", alert=True)
        ''')}, "MUTE-guard"),
        "the red button's run kept from the group": (ESTOP_SAMPLE, "MUTE-guard"),
        # R7: a second way to the log route, or a failure title on a log-only prefix
        "a second way to the log route": ({"ark_relay/core/notify.py": NOTIFY.replace(
            '    if alert:\n', '    if "测试" in title:\n        return "log"\n    if alert:\n')}, "MUTE-log"),
        "the log route from a variable": ({"ark_relay/core/notify.py": NOTIFY.replace(
            '    if alert:\n', '    r = "log" if title.endswith("。") else "info"\n    if alert:\n').replace(
            '    return "info"\n', '    return r\n')}, "MUTE-log"),
        "the log branch not on route_of": ({"ark_relay/core/notify.py": NOTIFY.replace(
            'route = route_of(title, alert=alert, daily=daily)', 'route = "log" if body == "" else route_of(title)')},
            "MUTE-log"),
        "a failure title on a log-only prefix": ({"ark_relay/core/notify.py": NOTIFY + 'COLLECT_FAILED = "✅ 自动采集：3 条没走通"\n'},
                                                 "MUTE-log"),
        "the log line outside the log branch": ({"ark_relay/core/notify.py": NOTIFY.replace(
            '        if route == "log":\n            log.info("不推送（日报或手机页已有）：%s", title)\n            return []\n',
            '        log.info("不推送（日报或手机页已有）：%s", title)\n')}, "MUTE-log"),
        # R8: the game's own counter at 0, read off the screen in the same function, and logged
        "skipped on a config value": (BOSS.replace("now = _left(text)", 'now = self.config.get("Weekly Left", 3)'),
                                      "OFF-skip"),
        "skipped on a retry counter": (BOSS.replace("now = _left(text)", "now = 3\n        for b in left or []:\n"
                                                "            now -= 1"), "OFF-skip"),
        "skipped on a value handed in": (BOSS.replace("def click_level(self):", "def click_level(self, given):")
                                         .replace("now = _left(text)", "now = given"), "OFF-skip"),
        "skipped on the screen and the task's own state": (BOSS.replace("now = _left(text)",
                                                                        "now = _left(text) - self._tries"), "OFF-skip"),
        "skipped with no condition": (BOSS.replace("        if now == 0:\n            self.log_info",
                                                   "        self.log_info").replace(
            "            raise TaskDisabledException()", "        raise TaskDisabledException()"), "OFF-skip"),
        "skipped on a read other than 0": (BOSS.replace("if now == 0:", "if now == 1:"), "OFF-skip"),
        "skipped on a read that is not 0": (BOSS.replace("if now == 0:", "if now != 0:"), "OFF-skip"),
        "skipped without a word in the branch": (BOSS.replace('            self.log_info("本周次数已领满（0/3），跳过")\n', ""),
                                                 "OFF-skip"),
        "skipped without the reading in the log": (BOSS.replace('            self.log_info(f"剩余次数原文: {left}")\n',
                                                                "            pass\n"), "OFF-skip"),
        # R8b: a subclass raised is the skip unless the same file makes it a failure
        "alias of the stop raised": ('from ok import TaskDisabledException as _TDE\ndef stop(t):\n    raise _TDE()\n',
                                     "OFF-skip"),
        "subclass never caught": ('class Stop(TaskDisabledException):\n    pass\ndef end(t):\n    raise Stop()\n',
                                  "OFF-skip"),
        "type() subclass never caught": (STOP[:STOP.index("def run(self):")], "OFF-skip"),
        "subclass caught and swallowed": (STOP.replace('    why = getattr(self, "_failed", None)\n'
                                                   '    if why:\n        raise Stopped(why)\n', ""), "OFF-skip"),
        "subclass turned into a failure on another flag": (STOP.replace('getattr(self, "_failed", None)',
                                                                        'getattr(self, "_other", None)'), "OFF-skip"),
        "subclass always re-raised by its handler": (STOP.replace("    except _Stop:\n        got = None\n",
                                                                  "    except _Stop:\n        raise\n"), "OFF-skip"),
        "subclass handed on as another skip": (STOP.replace("    except _Stop:\n        got = None\n",
                                                            "    except _Stop:\n        raise _Skip()\n").replace(
            "class Stopped(Exception):", "class _Skip(TaskDisabledException):\n    pass\nclass Stopped(Exception):"),
                                               "OFF-skip"),
        # OFF-flag: a marker file that switches a step off
        "a marker file skips the step": ('import os\nFLAG = r"C:\\ProgramData\\x\\no-farm.flag"\nclass T:\n'
                                     '    def farm(self):\n        if os.path.exists(FLAG):\n'
                                     '            self.log_info("刷体力已禁用")\n            return None\n'
                                     '        return self.go()\n', "OFF-flag"),
        "a Path marker in a loop": ('from pathlib import Path\nSKIP = Path("C:/ProgramData") / "skip-weekly.flag"\n'
                                'def run(tasks):\n    for t in tasks:\n        if SKIP.is_file():\n'
                                '            continue\n        t.go()\n', "OFF-flag"),
        "a marker or-ed in": ('import os\ndef farm(self, weekly):\n    flag = "C:/x/no-claim"\n'
                          '    if not weekly or os.path.isfile(flag):\n        return\n    self.go()\n', "OFF-flag"),
        "a marker and-ed with a reading of something else": (
            'import os\nF = "C:/x/no-farm.flag"\ndef farm(self):\n    if os.path.exists(F) and self.read_text():\n'
        '        return\n    self.go()\n', "OFF-flag"),
    }

    # For samples with more than one place, the place that must be the hit.
    BAD_AT = {
        **{k: "Notifier.send" for k in ("a second way to the log route", "the log route from a variable",
                                        "the log branch not on route_of", "a failure title on a log-only prefix",
                                        "the log line outside the log branch")},
        **{k: "end_failed" for k in ("type() subclass never caught", "subclass caught and swallowed",
                                     "subclass turned into a failure on another flag",
                                     "subclass always re-raised by its handler", "subclass handed on as another skip")},
        **{k: "T.click_level" for k in BAD if k.startswith("skipped ")},
        "the debug verdict's early exit": "maybe",
        "the red button's run kept from the group": "_handle",
    }

    GOOD = {
        "turning on": 'def f(t):\n    t["enabled"] = True\n',
        "reading a switch": 'def f(t):\n    return t.get("enabled", False) is False\n',
        "comparing with Close": 'def f(v):\n    return "剿灭关闭" if v == "Close" else ""\n',
        "returned description": 'def read(on):\n    if not on:\n        return {"enabled": False, "label": "全关"}\n',
        "setter with a parameter": 'def set_task(t, value):\n    t["enabled"] = bool(value)\n',
        "user's command carried": ('from . import queues\ndef run(cmds, d):\n    for cmd in cmds:\n'
                               '        queues.apply(d, cmd.get("name"), cmd.get("enabled"))\n'),
        "user's command through a setter": ('def set_task(t, value):\n    t["enabled"] = bool(value)\n'
                                        'def apply(cmd, t):\n    set_task(t, cmd["value"])\n'),
        "user's choice computed from parameters": ('TASKS = ("A", "B")\ndef toggle(have, want_task):\n'
                                               '    for name in TASKS:\n        want_on = name == want_task\n'
                                               '        have[name]["enabled"] = want_on\n'),
        "restore saved flags": ('KEYS = ("enabled",)\ndef restore(t, saved):\n    for k in KEYS:\n'
                            '        t[k] = saved[k]\n'),
        "task moved, not removed": 'def f(tasks, s, i, p):\n    tasks.remove(s)\n    tasks.insert(i, s)\n    p.write_text("")\n',
        "reader filtering a parsed log": 'def parse(tasks, skipped):\n    tasks = [t for t in tasks if t not in skipped]\n'
                                     '    return tasks\n',
        "plain early exit before an alarm": ('def push(eng, rows):\n    if not rows:\n        return\n'
                                         '    eng.notifier.send("t", "b", alert=True)\n'),
        "waiting for retries is not muting": LOG + 'def f(r):\n    log.info("%s 失败，暂不推送，等重试结果", r)\n',
        "route of a non-failure": ('_LOG_ONLY_PREFIXES = ("🔄 中继已更新",)\n'
                               'def route_of(t):\n    if t.startswith(_LOG_ONLY_PREFIXES):\n        return "log"\n'),
        "information that is not a failure": 'def f(eng, b):\n    eng.notifier.send("🆕 游戏更新", b)\n',
        "a cap that is not about pushes": 'def f(got, cap):\n    return got >= cap\n',
        "off as a command key": 'def f(cmd):\n    return bool(cmd.get("off"))\n',
        "old patch text kept only to be found": ('_X_V1 = """    self.log_info(\'x\')\n    raise TaskDisabledException()"""\n'
                                             'OLD = [(_X_V1, "")]\n'),
        "skipping items in a loop with no alarm in it": ('PLUGINS = ("a",)\ndef end(self, procs):\n    for n in procs:\n'
                                                     '        if n not in PLUGINS:\n            continue\n        kill(n)\n'
                                                     '    self.notifier.send("t", "b", alert=True)\n'),
        "checking a send's result": ('def f(eng, b):\n    if eng.notifier.send("🆕 更新", b):\n        return\n'
                                 '    eng.notifier.send("t", b, alert=True)\n'),
        "a banner on the group is not an alarm": ('def f(eng, fresh):\n    if not fresh:\n        return\n'
                                              '    eng.notifier.send_group("📣 明天开卡池", "b")\n'),
        "Close passed to a text function": ('def body(what, detail, back):\n    return f"{what}{detail}{back}"\n'
                                        'def samples():\n    return [body("Annihilation", "", "Close")]\n'),
        "a missing file is nothing to read": ('import os\nF = "C:/x/state.json"\ndef read(self):\n'
                                          '    if not os.path.exists(F):\n        return None\n    return self.load(F)\n'),
        "the file already says it": ('from pathlib import Path\nPOINTER = Path(r"C:\\ProgramData\\p.txt")\n'
                                 'def point(d):\n    if POINTER.is_file() and POINTER.read_text().strip() == str(d):\n'
                                 '        return ""\n    POINTER.write_text(str(d))\n    return ""\n'),
        "a record read only to switch tasks back on": dedent('''\
        def enable(cfg, names):
            for t in cfg["tasks"]:
                if t["n"] in names:
                    t["enabled"] = True
            cfg.write_text("x")
        def reenable(store, cfg):
            rec = store.get("updates", "x_disabled")
            enable(cfg, set(rec.get("disabled") or []))
        '''),
    }

    # Hits that are there and must pass by the narrow rule named (R3 - R5).
    ALLOWED = {
        "one record is one fault": (dedent('''\
        def send(eng, day, rec, t, b):
            key = f"未解决|{rec.run_id}"
            # one fault, one push: one record handled twice is one fault
            if eng._already_alerted(day, key):
                return True
            eng.notifier.send(t, b, alert=True)
        '''), "R3"),
        "one process is one fault": (dedent('''\
        class W:
            def tick(self, pid):
                if pid in self._done:  # one fault, one push: one hung process, by its PID
                    return
                self._done.add(pid)
                self.notifier.send("❌ 卡住", "b", alert=True)
        '''), "R3"),
        "one missed slot is one fault": (dedent('''\
        def check(eng, day, queues):
            for q in queues:
                for hhmm in q["times"]:
                    key = f"{day}/{q['name']}/{hhmm}"
                    # one fault, one push: one queue that did not run at its time
                    if key in eng._missed_alerted:
                        continue
                    eng.notifier.send("t", "b", alert=True)
                    eng._missed_alerted.add(key)
        '''), "R3"),
        "the relay's own power-off, in service.py": ({"ark_relay/features/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        class K:
            def exited(self):
                from ark_relay.features.alarm import errwatch
                if errwatch.relay_shutdown_issued():
                    log.info("按关机处理，不算故障")
                    return
                log.warning("意外退出")
            def check(self):
                from ark_relay.features.alarm import errwatch
                if self.handle is None and errwatch.relay_shutdown_issued():
                    return
                self.notifier.send("❌ 起不来", "b", alert=True)
        ''')}, "R4"),
        "the relay's own power-off, waited for in service.py": ({"ark_relay/features/errwatch.py": ERRWATCH,
                                                                "ark_relay/features/procwatch.py": dedent('''\
        import time
        def _going_down_soon(seconds=15.0):
            from ark_relay.features.alarm import errwatch
            deadline = time.monotonic() + seconds
            while not errwatch.relay_shutdown_issued():
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                time.sleep(min(0.5, left))
            return True
        '''),
                                                                "ark_relay/features/automas_keeper.py": LOG + dedent('''\
        from ark_relay.features.host import shutdown_signs
        class K:
            def exited(self):
                if shutdown_signs._going_down_soon():
                    log.info("按关机处理，不算故障")
                    return
                log.warning("意外退出")
        ''')}, "R4"),
        "the log route of route_of's collections": ({"ark_relay/core/notify.py": NOTIFY}, "R7"),
        "the log route, three tests or-ed": ({"ark_relay/core/notify.py": NOTIFY.replace(
            "if title.startswith(_LOG_ONLY_PREFIXES):",
            "if title.startswith(_LOG_ONLY_PREFIXES) or any(s in title for s in _LOG_ONLY_CONTAINS) "
        "or title in _LOG_ONLY_TITLES:").replace(
            '_LOG_ONLY_PREFIXES = ("🔄 中继已更新", "✅ ")',
            '_LOG_ONLY_PREFIXES = ("🔄 中继已更新", "✅ ")\n_LOG_ONLY_CONTAINS = ("已送出机器",)\n'
        '_LOG_ONLY_TITLES = ("📱 配置已修改",)')}, "R7"),
        "the weekly counter read 0 off the screen": (BOSS, "R8"),
        "a subclass recorded and raised as a failure": (STOP, "R8b"),
        "a subclass turned into a failure in its handler": (
            'class Stop(TaskDisabledException):\n    pass\ndef end(t):\n    raise Stop()\n'
        'def run(self):\n    try:\n        self.inner()\n    except Stop as exc:\n'
        '        raise RuntimeError("failed") from exc\n', "R8b"),
        "a temporary setting put back in finally": (AUTO_START + dedent('''\
        def run(p):
            was = _auto(p, False)
            if was is None:
                return
            try:
                launch(p)
            finally:
                _auto(p, was)
        '''), "R5"),
        "a temporary setting put back only if it was on": (AUTO_START + dedent('''\
        def run(p):
            was = _auto(p, False)
            try:
                launch(p)
            finally:
                close(p)
                if was:
                    _auto(p, True)
        '''), "R5"),
    }

    # Rule 2 on a sample shaped like modes.py: his skip-today command's reader controls
    # the write, so it is not a hit that needs a line.
    COMMAND_SAMPLE = dict(COMMAND_SAMPLE_BASE)

    def _sample_scan(src) -> Scan:
        return Scan(src if isinstance(src, dict) else {"ark_relay/_sample.py": src})

    def self_check() -> list[str]:
        fails = []
        for label, (src, rule) in BAD.items():
            need, _, _ = findings(_sample_scan(src))
            if not any(h.rule == rule for h in need):
                fails.append(f"known-bad sample not flagged as {rule}: {label} (got {need})")
        # the hit must be the place the sample is about, not some other line of it
        for label, where in BAD_AT.items():
            src, rule = BAD[label]
            need, _, _ = findings(_sample_scan(src))
            if not any(h.rule == rule and h.key.endswith(":" + where) for h in need):
                fails.append(f"known-bad sample not flagged at {where}: {label} (got {need})")
        for label, src in GOOD.items():
            hits = _sample_scan(src).hits
            if hits:
                fails.append(f"known-good sample flagged: {label}: {hits}")
        for label, (src, rule) in ALLOWED.items():
            scan = _sample_scan(src)
            need, _, allowed = findings(scan)
            if need or not allowed or any(not why.startswith(rule + " ") for _, why in allowed) \
                    or (rule == "R4" and scan.wrapper_used and scan.wrapper_problems()):
                fails.append(f"sample must pass by {rule} alone: {label} (need {need}, passed {allowed})")
        scan = Scan(COMMAND_SAMPLE)
        need, applied, _ = findings(scan)
        if need or [a for _, a in applied] != ["skip_today"] or command_records_hold(scan):
            fails.append(f"rule 2 sample: need {need}, applied {applied}, records {command_records_hold(scan)}")
        _, bad = read_list("ark_relay/x.py:f | does a thing | he said so | 2026-10-06\n")
        if len(bad) != 2:
            fails.append(f"a line with no quote and no time must be refused twice, got {bad}")
        _, bad = read_list("ark_relay/x.py:f | does a thing | 「我说的」 | 2026-09-03 (time not recorded)\n")
        if len(bad) != 1:
            fails.append(f"a line with a date but no time must be refused, got {bad}")
        listed, bad = read_list("ark_relay/x.py:f | does | 「我说的」 | 2026-10-06 02:53\n"
                            "ark_relay/x.py:_T[⚠️ 采集 没走通] | does | 「我说的」 | 2026-10-06 02:53\n"
                            "ark_relay/y.py:g | does | 「我说的？就是这样，对吧」 | 2026-09-03 02:34 (Tokyo)\n")
        if bad or sorted(listed) != ["ark_relay/x.py:_T[⚠️ 采集 没走通]", "ark_relay/x.py:f", "ark_relay/y.py:g"]:
            fails.append(f"well-formed lines (a key with spaces, a time zone note) must be accepted, "
                     f"got {sorted(listed)} {bad}")
        if not verdict([], {"ark_relay/x.py:f": "x"}):
            fails.append("a listed key with no hit must fail")
        on, probs = switched_pulls({"ark_relay/features/stagegate.py": "PULL_FROM_QUEUE = True\ndef _gate_due():\n    pass\n"})
        if [h.key for h in on] != ["ark_relay/features/stagegate.py:_gate_due"] or probs:
            fails.append(f"a switched-on queue pull must be a hit, got {on} {probs}")
        off, probs = switched_pulls({"ark_relay/features/stagegate.py": "PULL_FROM_QUEUE = False\ndef _gate_due():\n    pass\n"})
        if off or probs:
            fails.append(f"a switched-off queue pull must not be a hit, got {off} {probs}")
        _, probs = switched_pulls({"ark_relay/features/stagegate.py": "PULL_FROM_QUEUE = bool(1)\ndef _gate_due():\n    pass\n"})
        if not probs:
            fails.append("a switch that is not a literal must be refused")
        return fails

    def main(argv: list[str]) -> int:
        fails = ["self-check: " + f for f in self_check()]
        print(f"  self-check: {len(BAD)} known-bad samples flagged, {len(GOOD)} known-good samples clean, "
          f"{len(ALLOWED)} samples pass by R3-R8b alone, rule 2 sample ok" if not fails else "  self-check FAILED")
        sources = relay_sources()
        scan = Scan(sources)
        need, applied, allowed = findings(scan)
        pulls, pull_problems = switched_pulls(sources)
        need = sorted(need + pulls, key=lambda h: (h.rel, h.line, h.rule))
        for p in pull_problems:
            print("  ✗ " + p)
        fails += pull_problems
        fails += command_records_hold(scan)
        if scan.log_route_used:
            fails += scan.log_route_problems()
        if scan.wrapper_used:
            fails += scan.wrapper_problems()
        if "--list" in argv:
            for h in need:
                print(f"  {h!r}")
        for h, action in applied:
            print(f"  · {h.rel}:{h.line} applies the user's own {action} command (rule 2) - {h.text}")
        for h, why in allowed:
            print(f"  · {h.rel}:{h.line} {h.key} [{h.rule}] passes {why}")
        listed, bad = read_list(LIST_FILE.read_text(encoding="utf-8") if LIST_FILE.is_file() else "")
        if not LIST_FILE.is_file():
            bad.append("relay/USER-SWITCHES.txt is missing")
        problems = bad + verdict(need, listed)
        if "--list" not in argv:
            for p in problems:
                print("  ✗ " + p)
        fails += problems
        print(f"  {len(need)} places switch something off or keep a failure from the group; "
          f"{sum(1 for h in need if h.key in listed)} of them on the user's list ({len(listed)} lines)")
        for f in fails:
            if f.startswith(("self-check", "rule 2", "R4", "R7")):
                print("  ✗ " + f)
        return 1 if fails else 0

    if __name__ == "__main__":
        sys.exit(main(sys.argv[1:]))


def _part_mute_verdicts():  # noqa: C901
    import re
    import subprocess
    import sys
    from pathlib import Path

    RELAY = Path(__file__).resolve().parents[1]
    LIST = RELAY / "USER-SWITCHES.txt"

    # Places that keep something from the group because it is not a fault at all - not
    # because it fixed itself. Adding one means editing this test, with its source.
    NOT_A_FAULT = {
        "ark_relay/features/automas_keeper.py:_AutomasKeeper.stopping":
            "only the farm's own deadline power-off: the mark the farm leaves right before shutdown /s, a normal "
        "outcome and a shutdown.exe request at most 30 min later (ark_relay/features/procwatch.py:"
        "farm_poweroff_planned); relay.log 2026-11-13 08:20:06 / 08:22:20 is such a power-off. Every other "
        "shutdown exit is still the WARNING in ark_relay/features/automas_keeper.py:_AutomasKeeper.stopping",
        "ark_relay/features/okww_files/ark_overrides.tasks.py:_skip_short":
            "only the skip is normal: no fight for no reward and no AUTO-MAS retry that would find no more "
        "waveplates; the shortage itself is red and pushed (ark_relay/features/outcome.py:okww_checks)",
        "ark_relay/features/shutdown.py:_say_if_moment_passed":
            "why the machine stays on past its moment: each reason is a state whose fault pushes on its own path "
        "(ark_relay/features/runwatch.py:check_timeouts, ark_relay/features/handle.py:_flush_pending); "
        "the relay losing track is a WARNING (ark_relay/features/shutdown.py:RELAY_LOST_TRACK)",
        "ark_relay/features/procwatch.py:_ProcessWatch._push_open_drop":
            "Windows tearing WMI down after a power-off request it logged is the shutdown itself (System log "
        "1074 at 10-10 04:27:24, the drop at 04:28:45); a drop before the request still pushes "
        "(ark_relay/features/procwatch.py:_ProcessWatch._push_open_drop)",
    }
    # What writes the red item for a fault that fixed itself (techlog.self_heal).
    RED_WRITERS = re.compile(r"\brecovered\(\)|\btechlog\.self_heal\(|\b_self_heal_red\(")

    VERDICT_RE = re.compile(r"\s\|\s+verdict:\s+(?P<kind>fixed|normal-state|task-switch)\b\s*(?P<rest>.*)$")
    SHA_RE = re.compile(r"^(?P<sha>[0-9a-f]{7,40})\b")
    UNKNOWN = ("not known", "unknown", "unexplained", "nothing explained", "not found", "tbd", "to be checked",
               "不明", "待查", "没查清", "还没查")
    KEPT = ("recovered", "daily report only", "daily-report-only", "not pushed", "只进日报", "不进群")

    def commit_exists(sha: str) -> bool:
        r = subprocess.run(["git", "-C", str(RELAY), "cat-file", "-e", f"{sha}^{{commit}}"],
                           capture_output=True, timeout=30)
        return r.returncode == 0

    REPO = RELAY.parent
    LAZY_RE = re.compile(r"his words|his own words|he asked|he did not want|he wants|his order|his rule|he said|"
                     r"on his\b|\bhis \d{1,2}:\d{2}|\bhis \d{2}-\d{2}|(?:the user|user|他)\W{0,3}(?:\d{4}-)?\d{2}-\d{2}|"
                     r"原话|按他|照他|他说|用户说", re.I)
    CODE_REF_RE = re.compile(r"(?P<path>[\w./-]+\.py):(?P<name>[A-Za-z_][\w.]*)")
    DOC_REF_RE = re.compile(r"(?P<path>(?:docs|relay)/[\w./-]+\.(?:md|txt))")
    LOG_REF_RE = re.compile(r"\b(?:relay\.log|app\.log|maafw\.log|ok-ww log|okww log|system log|event (?:id )?\d{3,5})\b"
                        r"[^;]*?\b\d{2}-\d{2}\b", re.I)
    URL_RE = re.compile(r"https?://\S+")
    COMMIT_REF_RE = re.compile(r"\bcommit (?P<sha>[0-9a-f]{7,40})\b")

    def code_ref_holds(path: str, name: str) -> bool:
        """`path.py:name` names a file under relay/ (or the repo) that defines or assigns `name`'s last part."""
        for base in (RELAY, REPO):
            f = base / path
            if f.is_file():
                leaf = re.escape(name.split(".")[-1].split("[")[0])
                src = f.read_text(encoding="utf-8")
                return bool(re.search(rf"^\s*(?:async\s+)?(?:def|class)\s+{leaf}\b|^\s*{leaf}\s*[:=]", src, re.M))
        return False

    def reason_problems(why: str, has_commit=commit_exists) -> list[str]:
        """A normal-state why: no lean on the user's words, and at least one source that holds."""
        out = []
        lazy = LAZY_RE.search(why)
        if lazy:
            out.append(f"normal-state whose why leans on the user's words ({lazy.group(0)!r}), not a reason")
        sources = 0
        for m in CODE_REF_RE.finditer(why):
            if code_ref_holds(m["path"], m["name"]):
                sources += 1
            else:
                out.append(f"cites {m['path']}:{m['name']}, which is not defined there")
        for m in DOC_REF_RE.finditer(why):
            if (REPO / m["path"]).is_file():
                sources += 1
            else:
                out.append(f"cites {m['path']}, which does not exist")
        for m in COMMIT_REF_RE.finditer(why):
            if has_commit(m["sha"]):
                sources += 1
            else:
                out.append(f"cites commit {m['sha']}, which is not a commit here")
        sources += len(LOG_REF_RE.findall(why)) + len(URL_RE.findall(why))
        if not sources:
            out.append("normal-state with no source (code `file.py:function`, a log with its date, "
                   "docs/…, a URL or `commit <sha>`)")
        return out

    def place_source(key: str) -> "str | None":
        """The source of the function a line's key names (file:func, file:Class.method,
    nested defs dotted), or None when it is not there."""
        import ast
        file, _, dotted = key.partition(":")
        path = RELAY / file
        try:
            text = path.read_text(encoding="utf-8")
            node = ast.parse(text)
        except (OSError, SyntaxError):
            return None
        for part in dotted.split("."):
            node = next((n for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                         and n.name == part and n is not node), None)
            if node is None:
                return None
        return ast.get_source_segment(text, node)

    def problems(line: str, has_commit=commit_exists, source=place_source) -> list[str]:
        """What is wrong with one entry line's verdict ([] when nothing)."""
        m = VERDICT_RE.search(line)
        if line.count("| verdict:") != 1 or not m:
            return ["no `| verdict: fixed <sha> | normal-state - why | task-switch - why` at its end"]
        kind, rest = m["kind"], m["rest"].lstrip(" -").strip()
        head = line[:m.start()]
        if kind == "fixed":
            s = SHA_RE.match(rest)
            if not s:
                return ["fixed without a commit"]
            if not has_commit(s["sha"]):
                return [f"fixed by {s['sha']}, which is not a commit here"]
            return []
        if len(rest) < 20:
            return [f"{kind} without a why"]
        if kind == "normal-state":
            kept = rest.split(";")[0].lower()
            bad = [w for w in UNKNOWN if w in kept]
            if bad:
                return [f"normal-state while its cause is unknown ({bad[0]})"]
            key = line.split(" | ")[0].strip()
            if rest.startswith("not-a-fault:"):
                if key not in NOT_A_FAULT:
                    return [f"not-a-fault, but {key} is not on NOT_A_FAULT"]
                return reason_problems(rest[len("not-a-fault:"):], has_commit)
            if not rest.startswith("recovered:"):
                return ["normal-state is neither `recovered:` nor `not-a-fault:`"]
            _, sep, unhealed = rest.partition(";")
            if not sep or "push" not in unhealed.lower():
                return ["recovered without saying what is pushed when it does not recover (after the first \";\")"]
            code = source(key)
            if code is None:
                return [f"recovered, but {key} is not in the code"]
            if not RED_WRITERS.search(code):
                return [f"recovered, but {key} writes no red item (errwatch.recovered() / techlog.self_heal)"]
            return reason_problems(rest[len("recovered:"):], has_commit)
        what = head.lower()
        bad = [w for w in KEPT if w in what]
        return [f"task-switch that keeps a failure from the group ({bad[0]})"] if bad else []

    print("[the gate itself rejects the known-bad shapes]")
    GOOD = "x.py:f | does a thing | 「他的话」 | 2026-10-10 13:35"
    check("no verdict", bool(problems(GOOD)), True)
    check("normal-state for a cause nobody found",
          bool(problems(GOOD + " | verdict: normal-state - it came back by itself, 根因不明 so far")), True)
    check("normal-state for a cause nobody found (English)",
          bool(problems(GOOD + " | verdict: normal-state - the drop's cause is not known, it came back")), True)
    check("fixed with a commit that does not exist",
          bool(problems(GOOD + " | verdict: fixed deadbeef0", has_commit=lambda s: False)), True)
    check("fixed with no commit", bool(problems(GOOD + " | verdict: fixed - trust me")), True)
    check("normal-state without a why", bool(problems(GOOD + " | verdict: normal-state - ok")), True)
    check("task-switch that keeps a failure out",
          bool(problems("x.py:f | marked recovered (daily report only) | 「他的话」 | 2026-10-10 13:35"
                    " | verdict: task-switch - his order to switch the farm off")), True)
    check("two verdicts", bool(problems(GOOD + " | verdict: task-switch - his order | verdict: fixed abc1234")), True)
    HEALS = lambda key: "def f():\n    log.warning('x', extra=errwatch.recovered())\n"  # noqa: E731
    QUIET = lambda key: "def f():\n    log.info('x 自己好了')\n"  # noqa: E731
    check("a good recovered passes",
          problems(GOOD + " | verdict: normal-state - recovered: an outside site answered its one retry "
                      "(ark_relay/core/notify.py:route_of); both failing is pushed, why it fails is not known",
                   source=HEALS), [])
    check("normal-state without recovered: / not-a-fault:",
          bool(problems(GOOD + " | verdict: normal-state - an outside site answered its one retry; both failing is pushed",
                        source=HEALS)), True)
    check("recovered that writes no red item",
          bool(problems(GOOD + " | verdict: normal-state - recovered: an outside site answered its one retry; both "
                           "failing is pushed", source=QUIET)), True)
    check("recovered that never says what is pushed when it does not recover",
          bool(problems(GOOD + " | verdict: normal-state - recovered: an outside site answered its one retry", source=HEALS)),
          True)
    check("not-a-fault for a place not on NOT_A_FAULT",
          bool(problems(GOOD + " | verdict: normal-state - not-a-fault: the daily report says it, that is enough")), True)
    DROP = "ark_relay/features/procwatch.py:_ProcessWatch._push_open_drop"
    check("not-a-fault for a place on NOT_A_FAULT passes",
          problems(DROP + " | x | 「他的话」 | 2026-10-10 13:35 | verdict: normal-state - not-a-fault: Windows tearing "
                      "WMI down after a power-off request it logged (System log 1074 at 10-10 04:27:24)"), [])
    check("the place finder finds a method", "def _push_open_drop" in (place_source(DROP) or ""), True)
    R = " | verdict: normal-state - recovered: "
    check("normal-state whose why is the user's words (10-06 weekly boss line)",
          bool(problems(GOOD + " | verdict: normal-state - not-a-fault: the weekly boss short on crystal waveplates is the "
                           "game's resources, not a fault (his 10-06 10:34 words)")), True)
    check("not-a-fault on NOT_A_FAULT resting on what he asked for (10-10 stay-on line)",
          bool(problems("ark_relay/features/shutdown.py:_say_if_moment_passed | x | 「他的话」 | 2026-10-10 23:22"
                    " | verdict: normal-state - not-a-fault: he asked for that one message only; see "
                    "ark_relay/core/notify.py:route_of")), True)
    check("recovered with a reason but no source",
          bool(problems(GOOD + R + "an outside site answered its one retry; both failing is pushed", source=HEALS)), True)
    check("recovered citing a function that is not there",
          bool(problems(GOOD + R + "an outside site answered its one retry "
                               "(ark_relay/core/notify.py:no_such_function_here); both failing is pushed",
                        source=HEALS)), True)
    check("recovered citing a doc that is not there",
          bool(problems(GOOD + R + "the game's own rule, docs/NO-SUCH-FILE.md; both failing is pushed", source=HEALS)),
          True)
    check("a good recovered passes (log source)",
          problems(GOOD + R + "it came back on the next try (relay.log 10-10 04:28:51); both failing is pushed",
                   source=HEALS), [])
    check("a good fixed passes", problems(GOOD + " | verdict: fixed abc1234", has_commit=lambda s: True), [])
    check("the commit lookup itself works (HEAD)", commit_exists("HEAD"), True)

    print("[every line of USER-SWITCHES.txt]")
    entries = [(i, l.strip()) for i, l in enumerate(LIST.read_text(encoding="utf-8").splitlines(), 1)
               if l.strip() and not l.lstrip().startswith("#")]
    check("the list has lines", len(entries) > 0, True)
    kinds = {}
    for i, line in entries:
        got = problems(line)
        check(f"USER-SWITCHES.txt:{i} {line.split(' | ')[0]}", got, [])
        m = VERDICT_RE.search(line)
        if m:
            kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
    print(f"  · {len(entries)} lines: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    listed = {line.split(" | ")[0].strip() for _, line in entries}
    for key, why in NOT_A_FAULT.items():
        check(f"NOT_A_FAULT {key} has its line", key in listed, True)
        check(f"NOT_A_FAULT {key} gives a reason with a source", reason_problems(why), [])

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_daily_format():
    """日报三家一个语义模板，以 MAA 为样板（用户 2026-09-02）："""
    from datetime import datetime, timedelta

    from ark_relay.core import collector
    from ark_relay.core import ledger as core
    from ark_relay.core.config import SERVER_TZ

    FX = fx_dir(Path(__file__), "fixtures")

    def ent(run_id, script, hh, mm, dur, ok=True, **kw):
        st = datetime(2026, 9, 2, hh, mm, tzinfo=SERVER_TZ)
        e = {"run_id": run_id, "script": script, "user": "u", "ok": ok,
             "started": st.isoformat(), "finished": (st + timedelta(minutes=dur)).isoformat(),
             "duration_known": True, "transitional": False, "failed_tasks": [] if ok else ["x"],
             "raw": {}, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}
        e.update(kw)
        return e

    print("[鸣潮：从真实日志算出来]")
    ww = collector.parse_okww_log(FX / "okww_sim_2026-09-02.log")
    check("刷的本", ww.get("okww_farm"), "模拟领域·贝币")
    check("产出类别", ww.get("okww_farm_reward"), "贝币")
    check("进本 2 局", ww.get("okww_runs"), 2)
    check("波片 168→88→8 花了 160", ww.get("okww_stamina_spent"), 160)
    check("备用体力没动", ww.get("okww_backup_spent"), None)
    check("进了游戏就不是 unreachable", ww.get("okww_unreachable"), None)
    bad = tmpdir() / "bad.log"; bad.write_text("2026-09-02 09:18:58,791 ERROR ok.core.start_controller start_controller:waiting for game to start error 鸣潮 is not connected\n", encoding="utf-8")
    check("等不到窗口且一局没开 → unreachable", collector.parse_okww_log(bad).get("okww_unreachable"), True)
    check("剩 8", ww.get("okww_stamina_left"), 8)
    check("两局都是双倍", ww.get("okww_runs_double"), 2)
    check("产出按满难度算：2×84000×2", ww.get("okww_farm_drops"), {"贝币": 336000})
    ww["sanity_full_at"] = "2026-09-03 08:53"

    print("[终末地：从真实日志算出来]")
    ef = collector.parse_maaend_log(FX / "maaend_full_2026-09-01.log")
    check("刷本任务", ef.get("maaend_farm"), "基质刷取")
    check("地点", ef.get("maaend_farm_place"), "枢纽区")
    check("次数", ef.get("maaend_farm_runs"), 2)
    check("理智 234→154→74 花了 160", ef.get("maaend_sanity_spent"), 160)
    check("刷本掉落只算基质", ef.get("maaend_farm_drops"), {"无暇基质": 6, "高纯基质": 4})
    check("没吃加强剂", ef.get("maaend_medicine"), None)
    check("剩余理智 74/360", (ef.get("sanity"), ef.get("sanity_cap")), (74, 360))
    check("失败清单为空", ef.get("tasks_failed"), None)

    print("[三家五行，同一语义]")
    entries = [
        ent("maa", "MAA", 9, 0, 17, raw={"stages": ["1-7"], "run_times": 10, "sanity_spent": 120,
                                           "medicine_used": 1},
            drops={"龙门币": 1440, "固源岩": 25}, recruits={"3★": 2}, sanity=0,
            sanity_full_at="理智将在 2026-09-03 06:07 回满"),
        ent("ww", "OK-WW", 9, 28, 13, raw=ww),
        ent("ef", "MaaEnd", 9, 42, 25, raw=ef, sanity=ef["sanity"], sanity_full_at="2026-09-02 21:00"),
        ent("bad", "OK-WW", 21, 30, 5, ok=False, failed_tasks=["OK-WW 流程产生错误"]),
    ]
    title, body = core.format_daily("2026-09-02", entries)
    print(body)
    blocks = [b for b in body.split("\n\n") if b.strip()]
    rows = lambda blk: blk.splitlines()[1:]  # noqa: E731
    check("MAA", rows(blocks[0]), [
        "· 做了　刷 1-7 ×10",
        "· 消耗　理智 120，吃药 1",
        "· 产出　龙门币×1440 固源岩×25",
        "· 剩余　理智 0，次日 06:07 回满（东京 07:07）",
        "· 备注　公招 3★×2"])
    check("鸣潮", rows(blocks[1]), [
        "· 做了　刷 模拟领域·贝币 ×2（双倍）",
        "· 消耗　波片 160，备用体力 0",
        "· 产出　贝币×336000",
        "· 剩余　波片 8/240，备用 0，次日 08:53 回满（东京 09:53）",
        "· 备注　残象聚落（已刷满）；周本（已完成，本周已领满）"])
    check("终末地（白名单不写没证据报错，只展正常产出）", rows(blocks[2]), [
        "· 做了　刷 基质刷取·枢纽区 ×2",
        "· 消耗　理智 160，加强剂 0",
        "· 产出　无暇基质×6 高纯基质×4",
        "· 剩余　理智 74/360，本日 21:00 回满（东京 22:00）",
        "· 备注　日常 1-5 项完成"])
    check("失败行严禁进日报（已推群、仅留技术日志）", (len(blocks), "❌" in body, "没跑成" in body, "没证据" in body),
          (3, False, False, False))
    check("「体力不够再开一局」不再出现", "体力不够" in body, False)
    foot = core.daily_footnote(entries)
    check("名单当注释放最末（只列有证据的）", foot, "———————\n日常：1.基建任务 2.信用点购物 3.应急理智加强剂 4.选剑演武 5.日常奖励领取")
    check("存在异常/未验证项时标题不用全绿也不塞报错词",
          ("全绿" in title, "没证据" in title, "失败" in title, title.endswith("今日日报")),
          (False, False, False, True))
    check("没有终末地成功记录就没有注释", core.daily_footnote(entries[:2]), "")
    _nf = {"script": "MAA", "ok": True, "sanity": 0,
           "started": "2026-09-04T12:41:00+08:00", "finished": "2026-09-04T12:52:00+08:00",
           "raw": {}, "drops": {}, "recruits": {}}
    _blk = "\n".join(core._block(_nf, datetime.fromisoformat(_nf["finished"])))
    check("作战关掉时说清做了什么", "只做日常" in _blk, True)
    check("没读过理智不印成理智 0", "理智 0" in _blk, False)
    # 真打完把理智花到 0 的，那个 0 要照印
    _f = dict(_nf, raw={"stages": ["1-7"], "sanity_spent": 120})
    _blk2 = "\n".join(core._block(_f, datetime.fromisoformat(_f["finished"])))
    check("真刷到 0 要照印", "理智 0" in _blk2, True)

    print("\n[不是采集日的那条自动采集记录不列出来（2026-09-13 周日 10:02→10:03）]")
    skip = ent("2026-09-13/endfield/MaaEnd-06-02-49", "MaaEnd", 10, 2, 1, True,
              raw={"tasks_done": ["自动采集", "结束进程"], "maaend_collect_skipped": "周日"})
    real = ent("2026-09-13/endfield/MaaEnd-05-36-46", "MaaEnd", 9, 37, 25, True,
              raw={"tasks_done": ["赠送干员礼物", "装备制造", "拜访好友"],
                   "tasks_evidence": {"赠送干员礼物": "获得 信用 ×400", "装备制造": "获得 嵌晶玉 ×25"},
                   "tasks_shot": ["拜访好友"]})
    t2, b2 = core.format_daily("2026-09-13", [real, skip])
    check("日报只有一条终末地", b2.count("终末地　"), 1)
    check("没有那条 0 分钟的", "10:02→10:03" in b2, False)
    check("标题还是全绿", "全绿" in t2, True)
    walked = ent("2026-09-14/endfield/MaaEnd-06-02-49", "MaaEnd", 10, 2, 30, True,
                raw={"tasks_done": ["自动采集", "结束进程"], "maaend_collect_total": 17, "maaend_collect_done": 17})
    t3, b3 = core.format_daily("2026-09-14", [walked])
    check("真走了路线的那条照常列", "自动采集 17/17 条走通" in b3, True)

    print("\n[剿灭理智不够连试三次：一行（2026-09-14 真实账本）]")
    a1 = ent("2026-09-14/arknights/MAA-05-00-01", "MAA", 9, 0, 2, False, failed_tasks=["MAA 部分任务执行失败"],
             raw={"annihilation": True, "maa_sanity_short": {"have": 17, "cost": 25}})
    a2 = ent("2026-09-14/arknights/MAA-05-02-33", "MAA", 9, 3, 1, False, failed_tasks=["MAA 部分任务执行失败"],
             raw={"annihilation": True, "maa_sanity_short": {"have": 17, "cost": 25}})
    a3 = ent("2026-09-14/arknights/MAA-05-04-50", "MAA", 9, 5, 1, False, failed_tasks=["MAA 部分任务执行失败"],
             raw={"annihilation": True, "maa_sanity_short": {"have": 17, "cost": 25}})
    daily = ent("2026-09-14/arknights/MAA-05-07-00", "MAA", 9, 7, 11, True, raw={"tasks_done": ["基建换班"]})
    t4, b4 = core.format_daily("2026-09-14", [a1, a2, a3, daily])
    check("标题全绿带说明", "全绿 ✅（有一关理智不够没打）" in t4, True)
    check("三次合成一行", b4.count("剿灭检查"), 1)
    check("写明连试 3 次", "连试 3 次" in b4, True)
    check("时间跨到最后一次", "09:00→09:06" in b4, True)
    check("备注写理智数", "理智 17 不够这关要的 25" in b4, True)
    check("日常那趟单独一行", b4.count("明日方舟　"), 1)

    print("\n[audit 11-08 C-02: a task left unjudged (MaaEnd's own record unread once) keeps the title off 全绿]")
    from ark_relay.core import ledger as _lr
    _e = {"run_id": "2026-11-08/endfield/MaaEnd-05-30-00", "script": "MaaEnd", "user": "endfield", "ok": True,
          "started": "2026-11-08T09:30:00+08:00", "finished": "2026-11-08T10:20:00+08:00", "failed_tasks": [],
          "raw": {"tasks_done": ["赠送干员礼物", "日常奖励领取"], "tasks_trail_miss": 1,
                  "tasks_trail": {"赠送干员礼物": {"found": False, "unread": True}},
                  "tasks_evidence": {"日常奖励领取": "获得 x"}}}
    check("unjudged this day", _lr.day_unjudged_items([_e]), ["赠送干员礼物"])
    _t, _ = _lr.format_daily("2026-11-08", [_e])
    check("title uses neutral 今日日报, not 全绿 and no error tag",
          ("今日日报" in _t, "全绿" in _t, "待核" in _t), (True, False, False))
    _e2 = dict(_e, run_id="2026-11-08/endfield/MaaEnd-13-30-00", started="2026-11-08T17:30:00+08:00",
               raw={"tasks_done": ["赠送干员礼物"], "tasks_trail_miss": 0,
                    "tasks_trail": {"赠送干员礼物": {"found": True, "ok": True}}})
    check("another run of the day backed it: not 待核", _lr.day_unjudged_items([_e, _e2]), [])


def _part_daily_partial_failure():
    """日报白名单：失败趟严禁进入日报正文（由群告警与技术日志承接），成功趟正常呈现且标题不误报全绿、不塞报错/重试词。"""
    import json

    from ark_relay.core import ledger as core

    entries = json.loads((fx_dir(Path(__file__), "fixtures") / "daily-2026-09-09.json")
                         .read_text(encoding="utf-8"))
    bare_title, bare_body = core.format_daily("2026-09-09", entries)
    check("账上没有证据：标题不用全绿，也不塞「没证据」报错词",
          ("全绿" in bare_title, "没证据" in bare_title, "今日日报" in bare_title, "没证据" in bare_body),
          (False, False, True, False))
    for e in entries:
        raw = e.get("raw") or {}
        if raw.get("tasks_done"):
            raw["tasks_evidence"] = {t: "获得 信用 ×400" for t in raw["tasks_done"]}
    tech_rows: list[str] = []
    title, body = core.format_daily("2026-09-09", entries, tech=tech_rows)
    blocks = body.split("\n\n")
    retry_run = next(b for b in blocks if "2m" in b and "终末地" in b)

    print("[失败的那趟进技术日志、不进日报；日报标题和正文 0 报错/重试词]")
    check("失败那趟已记进技术日志", any("据点交易" in ln for ln in tech_rows), True)
    check("日报正文没有失败与重试词", any(w in (title + body) for w in ("失败", "重试", "❌", "没跑成")), False)
    check("标题用中性今日日报，不误报全绿", ("今日日报" in title, "全绿" in title), (True, False))

    print("[成功的那趟照常按白名单简洁输出，不摆四个破折号]")
    check("只有一行", retry_run.count("· "), 1)
    check("那一行说了做的是什么", "据点交易" in retry_run)
    check("没有空占位", "—" not in retry_run)

    print("[脚注取的是真正做了日常的那趟，不是两分钟那趟]")
    foot = core.daily_footnote(entries)
    check("列出了完整日常", foot.count(".") >= 13)
    check("不是只有一项", "日常：1.据点交易" not in foot)


def _part_daily_range_prefix():
    """「日常 1-N 项完成」 only when the run's list is the footnote's first N names."""
    import json

    from ark_relay.core import ledger as core

    es = [json.loads(x) for x in (fx_dir(Path(__file__), "fixtures") / "ledger-1008-maaend-two-lists.jsonl").read_text(encoding="utf-8").splitlines()]
    _t, body = core.format_daily("2026-10-08", es, "", "")
    blocks = body.split("\n\n")
    late = next(b for b in blocks if "10:35→11:12" in b)
    require("failed early run is omitted by daily whitelist", not any("09:30→10:30" in b for b in blocks), body)
    require("10:35 run names its own tasks", "日常 1-" not in late and "做了 拜访好友" in late, late)
    require("10:35 run lists 自动采集 it did", "自动采集、日常奖励领取" in late, late)
    # Mark early run as ok=True to verify the 1-13 range-prefix rendering for a clean run
    es_ok = [dict(e, ok=True, failed_tasks=[]) for e in es]
    _t2, body2 = core.format_daily("2026-10-08", es_ok, "", "")
    early_ok = next(b for b in body2.split("\n\n") if "09:30→10:30" in b)
    require("the footnote's own clean run keeps 1-13", "日常 1-13 项完成" in early_ok, early_ok)
    require("footnote starts with 05:29's list", core.daily_footnote(es).startswith("———————\n日常：1.赠送干员礼物 2.装备制造"))


def _part_daily_techlog():
    """The daily report keeps what a person reads; the technical parts go to the technical log.
    """
    import json
    import os
    import re
    import types
    from datetime import datetime, timedelta

    from ark_relay.features import errwatch
    from ark_relay.features import report
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core import ledger as core, statestore as techlog
    from ark_relay.core.ledger import State

    report.plan = types.SimpleNamespace(
        schedule=lambda automas_dir: [{"name": "早班", "times": ["09:00"]}, {"name": "晚班", "times": ["21:30"]}],
        next_plan=lambda automas_dir: "",
        activity_countdown=lambda automas_dir: "",
    )
    report.banners = types.SimpleNamespace(
        collect=lambda now, skland_token="", failed=None, notes=None, trace=None, versions=None, leads=None,
        read_image=None, state_dir=None: ([], {}),
        image_reader=lambda state_dir: None,
        render=lambda rows, now, nxt, notes=None, trace=None, failed=None, leads=None: "",
        Trace=types.SimpleNamespace(new=lambda: None),
        save_trace=lambda state_dir, now, text, tr: None,
        update_history=lambda state_dir, now: [],
    )
    report.summary = types.SimpleNamespace(daily_report=lambda cfg, entries, plan="": "")

    TODAY = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    URL = "https://ark-evidence-1.cos.ap-shanghai.myqcloud.com/MAA-21-30.zip?q-signature=abc"
    VERSION = "v2.32.0-beta.1"
    PAK = "Content\\Paks\\pakchunk0.pak"
    # What a technical line looks like. None of it may reach the report body.
    TECH_IN_BODY = re.compile(
        r"Traceback|myqcloud\.com|证据包|v\d+\.\d+\.\d+|v20\d{12}|pakchunk|重试后成功|耗时"
        r"|今天中继改了什么|中继自己记下的报错|上机核对|中继体检|测试跑过")
    SCRIPT_ROW = re.compile(r"^\S+ (MAA|OK-WW|MaaEnd)(（|　)", re.M)
    TOOL_WORD = re.compile(r"(?<![A-Za-z])(MaaEnd|MAA|OK-WW|AUTO-MAS)(?![A-Za-z])")

    class Notifier:
        def __init__(self):
            self.sent: list = []
            self.broken = False

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body))
            return ["Server酱: 假装挂了"] if self.broken else []

        def send_group(self, title, body):
            return []

        def send_group_image(self, path):
            return []

    class Eng:
        """The slice of Engine the report uses; forwards exactly as engine.py does."""

        def __init__(self, state_dir: Path):
            self.cfg = types.SimpleNamespace(
                automas_dir=None, history_dir=None, okww_dir=None, skland_token="",
                state_dir=state_dir, last_run_after="21:30", interim_report=True)
            self.state = State(state_dir)
            self.notifier = Notifier()

        def _report_cutoff(self, now):
            return report._report_cutoff(self, now)

        def _scripts_running(self):
            return False

        def _unfinished_queues(self, now, entries):
            return []

        def _round_is_manual(self, new_entries):
            return False

        def _compose_daily(self, day, entries):
            return report._compose_daily(self, day, entries)

        def _announce_banners(self, now, nxt):
            return None

        def send_daily_now(self, mark=True, label="临时查看"):
            return report.send_daily_now(self, mark, label)

    def run(rid, script, hhmm, mins, ok, failed=(), transitional=False, **raw):
        start = datetime.fromisoformat(f"{TODAY}T{hhmm}:00+08:00")
        return {"run_id": f"{TODAY}/x/{rid}", "script": script, "user": "u",
                "started": start.isoformat(), "finished": (start + timedelta(minutes=mins)).isoformat(),
                "ok": ok, "failed_tasks": list(failed), "duration_known": True,
                "transitional": transitional, "raw": raw}

    ENTRIES = [
        # OK-WW: the restart dialog swapped a client file, then a clean run.
        run("ww1", "OK-WW", "09:00", 1, False, transitional=True, okww_restart_dialog=True,
            okww_client_change="patch", okww_client_files=[PAK]),
        run("ww2", "OK-WW", "09:02", 10, True, tasks_done=["日常"]),
        # MaaEnd: installed its new build and restarted, then a clean verified run.
        run("ef1", "MaaEnd", "09:20", 2, False, failed=["MaaEnd 进程超时"], maaend_update_restart=VERSION),
        run("ef2", "MaaEnd", "09:23", 20, True, tasks_done=["赠送干员礼物"], tasks_shot=["赠送干员礼物"]),
        # A test run inside a marked test window.
        run("test", "MAA", "12:00", 5, True, tasks_done=["日常"]),
        # MAA's evening run failed for good; its evidence bundle was uploaded.
        run("maa", "MAA", "21:30", 3, False, failed=["基建换班"], evidence_page=URL),
    ]

    def machine() -> Eng:
        """A machine with every technical source seeded."""
        root = tmpdir()
        sd = root / "state"
        sd.mkdir()
        e = Eng(sd)
        e.state.ledger_path(TODAY).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ENTRIES), encoding="utf-8")
        (sd / "test-windows.json").write_text(json.dumps(
            [{"since": f"{TODAY}T11:59:00+08:00", "until": f"{TODAY}T12:10:00+08:00"}]), encoding="utf-8")
        report.remember_change(sd, "周本领奖补回来了。", "20261011104917", day=TODAY)
        report.remember_change(sd, "通知分三路。", "20261011104918", day=TODAY)
        (sd / errwatch.DAY_DIR).mkdir()
        (sd / errwatch.DAY_DIR / f"{TODAY}.json").write_text(json.dumps({
            "k1": {"where": "ark.notify", "line": "推送重试后成功，耗时 3 秒", "count": 2, "pushed": 2,
                   "first": f"{TODAY} 10:00:00"}}, ensure_ascii=False), encoding="utf-8")
        log = root / "relay.log"
        log.write_text(f"{TODAY[5:]} 10:00:00 ERROR    ark.report 日报推送重试后成功\n", encoding="utf-8")
        os.environ["ARK_LOG_FILE"] = str(log)
        return e

    def at(hhmm):
        return datetime.fromisoformat(f"{TODAY}T{hhmm}:00+08:00").astimezone(SERVER_TZ)

    def tech_of(e) -> str:
        p = techlog.path_for(TODAY, e.cfg.state_dir)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    print("[每一路技术内容都进技术日志（先证明它真被造出来了）]")
    e = machine()
    report._maybe_daily_report(e, at("22:00"))
    check("日报发出去了", len(e.notifier.sent), 1)
    check("当天记号落了", e.state.report_sent(TODAY), True)
    title, body = e.notifier.sent[-1]
    tech = tech_of(e)
    check("技术日志在 <state>/../tech/<日期>.md",
          techlog.path_for(TODAY, e.cfg.state_dir) == (e.cfg.state_dir.parent / "tech" / f"{TODAY}.md").resolve())
    for heading in ("今天中继改了什么", "中继自己记下的报错", "上机核对（部署后机器自己核）", "中继体检",
                    "测试窗口里的记录（不计入日报）", "日报各行的证据包、版本和文件"):
        check(f"技术日志有「## HH:MM {heading}」", bool(re.search(rf"^## \d\d:\d\d {re.escape(heading)}$", tech, re.M)))
    check("部署说明在技术日志里", "周本领奖补回来了" in tech and "通知分三路" in tech)
    check("中继自己的报错原话在技术日志里", "推送重试后成功，耗时 3 秒" in tech)
    check("测试那一趟的趟号在技术日志里", f"{TODAY}/x/test" in tech)
    check("证据包链接在技术日志里，带趟号", f"{TODAY}/x/maa 证据包 {URL}" in tech)
    check("终末地的版本号在技术日志里", f"{TODAY}/x/ef1 MaaEnd 装新版 {VERSION} 后自己重启" in tech)
    check("鸣潮换了的文件在技术日志里", f"{TODAY}/x/ww1 OK-WW 游戏更新换了的文件：{PAK}" in tech)

    print("\n[日报正文里一行技术内容和报错/重启自愈内容都没有]")
    check("正文里没有技术行", TECH_IN_BODY.findall(body), [])
    check("行首是游戏名，不是脚本名", SCRIPT_ROW.findall(body), [])
    check("各游戏正常成功的行都在", all(f"✅ {g}　" in body for g in ("鸣潮", "终末地")))
    check("失败趟与更新重启过渡行严禁进日报（已进技术日志/群告警）",
          any(w in body for w in ("❌", "↪️", "没跑成", "失败于", "不算失败", "用掉一次重试")), False)
    check("部署只剩一句次数", body.rstrip().endswith("今天中继更新了 2 次"))
    check("测试那一趟不在日报里", "12:00→" in body, False)
    check("有失败趟时标题用中性今日日报（不误报全绿，也不塞失败词）",
          ("今日日报" in title, "全绿" in title, "没跑成" in title), (True, False, False))

    print("\n[只在发出并落记号的那一次写；重试发送不写第二遍]")
    e = machine()
    e.notifier.broken = True
    report._maybe_daily_report(e, at("22:00"))
    check("推送失败：不落记号", e.state.report_sent(TODAY), False)
    first = tech_of(e)
    check("推送失败那一次技术日志已经写了", "今天中继改了什么" in first)
    e.notifier.broken = False
    report._maybe_daily_report(e, at("22:05"))
    check("重试发出去了", e.state.report_sent(TODAY), True)
    check("重试没把技术日志再写一遍", tech_of(e).count("今天中继改了什么"), 1)

    print("\n[临时查看不写技术日志，正文一样干净]")
    e = machine()
    check("临时查看发出去了", e.send_daily_now(mark=False), True)
    check("临时查看不写技术日志", tech_of(e), "")
    check("临时查看的正文也没有技术行", TECH_IN_BODY.findall(e.notifier.sent[-1][1]), [])
    check("send_daily_now(mark=True) 写技术日志", (e.send_daily_now(mark=True), "日报各行的证据包" in tech_of(e)), (True, True))

    print("\n[技术日志写不进去：日报照旧、照发]")
    ok = machine()
    report._maybe_daily_report(ok, at("22:00"))
    e = machine()
    (e.cfg.state_dir.parent / "tech").write_text("not a directory", encoding="utf-8")
    report._maybe_daily_report(e, at("22:00"))
    check("日报照发、记号照落", (len(e.notifier.sent), e.state.report_sent(TODAY)), (1, True))
    check("正文和写得进去时一字不差", e.notifier.sent[-1][1], ok.notifier.sent[-1][1])
    check("一段都没记成已写，下次还能补", e.state.techlog_written(TODAY), set())

    print("\n[耗时留着：跑了多久是他看得懂的结果（验收 10-11）]")
    check("每行的时长还在", ("　10m　" in body, "　20m　" in body), (True, True))

    print("\n[跑完没自己退出：中继已替他收掉，进技术日志，不进行、不进标题（验收 10-11）]")
    hung = run("ef9", "MaaEnd", "09:20", 20, True, tasks_done=["赠送干员礼物"], tasks_shot=["赠送干员礼物"],
               maaend_no_self_exit=1)
    tech_rows: list = []
    t_hung, b_hung = core.format_daily(TODAY, [hung], tech=tech_rows)
    check("标题照旧全绿", t_hung.endswith("全绿 ✅"), True)
    check("正文里没有这一句", "没自己退出" in b_hung, False)
    check("技术日志那一行带趟号", tech_rows, [f"{TODAY}/x/ef9 终末地任务全完成，但跑完没自己退出（空等 1 分钟）"])

    print("\n[正文里不出现工具名，工具自己的话换成人话（验收 10-11）]")
    def maa_stop(rid, hhmm):
        return run(rid, "MAA", hhmm, 1, False, failed=["MAA 在完成任务前中止"], fight_count=0,
                   maa_result="MAA 在完成任务前中止", maa_config_rejected="理智作战 序列化失败，关卡 YW-4")

    day10 = [maa_stop("m1", "09:00"), maa_stop("m2", "09:01"), maa_stop("m3", "09:03"),
             run("m4", "MAA", "12:15", 19, True, stages=["YW-4"], run_times=14, sanity_spent=168,
                 hand_started="9c68")]
    e = machine()
    e.state.ledger_path(TODAY).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in day10), encoding="utf-8")
    from ark_relay.features import makeup, makeup as marker
    marker._write_marker(e.cfg.state_dir, TODAY, {"MAA": {
        "result": makeup.GAVE_UP, "run_id": f"{TODAY}/x/m3",
        "note": "不补跑：失败的不只是开始唤醒或连模拟器（MAA 在完成任务前中止），拿不准有没有打过仗"}})
    t10, b10 = e._compose_daily(TODAY, e.state.read_ledger(TODAY))
    check("标题、正文里一个工具名都没有", TOOL_WORD.findall(t10 + b10), [])
    e2 = machine()
    e2.state.ledger_path(TODAY).write_text(json.dumps(run(
        "x1", "MaaEnd", "09:20", 30, False, failed=["MaaEnd 进程超时"], tasks_done=["赠送干员礼物"],
        tasks_shot=["赠送干员礼物"]), ensure_ascii=False) + "\n", encoding="utf-8")
    t_x, b_x = e2._compose_daily(TODAY, e2.state.read_ledger(TODAY))
    check("失败趟不进日报且不露工具名",
          ("失败于" in b_x, "❌" in b_x, TOOL_WORD.findall(t_x + b_x)), (False, False, []))
    check("工具自己的话在 plain_words 里仍换成人话（供群告警与技术日志）",
          core.plain_words("MaaEnd 进程超时"), "终末地跑得太久，被停掉了")

    print("\n[日报白名单：失败行、补跑失败行、重试说明全部只进群/技术日志，绝不进日报]")
    check("日报正文无 ❌ 失败行、无补跑行，保留 12:15 正常成功行",
          ([l for l in b10.splitlines() if l.startswith("❌")], "补跑" in b10, "✅ 明日方舟　12:15" in b10),
          ([], False, True))
    check("存在失败记录时标题用中性今日日报（不误报全绿，不塞没跑成）",
          ("今日日报" in t10, "全绿" in t10, "没跑成" in t10), (True, False, False))

    print("\n[重试场景：失败趟不进日报、成功趟保留、日报正文与标题无「重试」字样]")
    retry = [run("r1", "MaaEnd", "09:20", 10, False, failed=["转交委托"], tasks_done=["赠送干员礼物"],
                 tasks_shot=["赠送干员礼物"]),
             run("r2", "MaaEnd", "09:40", 10, True, tasks_done=["转交委托"], tasks_shot=["转交委托"])]
    t_r, b_r = core.format_daily(TODAY, retry)
    check("成功趟照常保留、正文与标题 0 重试/失败词",
          ("✅ 终末地　09:40" in b_r, "重试" in (t_r + b_r), "失败" in (t_r + b_r), t_r.endswith("今日日报")),
          (True, False, False, True))

    print("\n[红项的格式：读取工具按这个认（ac38f466 的格式）]")
    when = datetime(2026, 10, 11, 21, 45, tzinfo=SERVER_TZ)
    d = tmpdir() / "state"
    check("每条红项带自己的编号", techlog.add_red(TODAY, "收工体检", ["收工体检：补丁不在", "明早的队列读不到"],
                                             state_dir=d, now=when),
          ["R-20261011-2145-1", "R-20261011-2145-2"])
    reds = [ln for ln in techlog.path_for(TODAY, d).read_text(encoding="utf-8").splitlines() if ln.startswith("🔴")]
    check("红项那一行的样子", reds, ["🔴 R-20261011-2145-1 收工体检：补丁不在",
                                  "🔴 R-20261011-2145-2 明早的队列读不到"])
    text = "\n".join(reds + [techlog.handled_line("R-20261011-2145-1", "abc1234")])
    check("已处理那一行的样子", techlog.handled_line("R-20261011-2145-1", "abc1234"),
          "✅ R-20261011-2145-1 已处理（abc1234）")
    check("处理过的不再算没处理", techlog.unhandled(text), [("R-20261011-2145-2", "明早的队列读不到")])
    d = tmpdir() / "state"
    check("空内容不写文件也算成功", (techlog.append(TODAY, "空", "  ", state_dir=d), techlog.path_for(TODAY, d).exists()),
          (True, False))
    check("一段写成 ## HH:MM 标题",
          (techlog.append(TODAY, "收工体检", "\n".join(reds), state_dir=d, now=when),
           techlog.path_for(TODAY, d).read_text(encoding="utf-8")),
          (True, "\n## 21:45 收工体检\n" + "\n".join(reds) + "\n"))

    print("\n[跨零点：记进前一天文件的红项和今天的自愈红项编号不撞（审查 10-13 s5 #2）]")
    # gamelog_errors writes into the round's start day with the current time as the
    # stamp; self_heal in the same minute writes into today's file. The Mac tool joins
    # all days by id, so a shared id hid one of the two.
    d = tmpdir() / "state"
    after_midnight = datetime(2026, 10, 13, 0, 20, tzinfo=SERVER_TZ)
    a = techlog.add_red("2026-10-12", "游戏日志里没登记的报错", ["23:50 开始的那一趟"], state_dir=d, now=after_midnight)
    b = techlog.self_heal("ark.gamelog_errors", "自己好了", state_dir=d, now=after_midnight)
    c = techlog.add_red("2026-10-12", "游戏日志里没登记的报错", ["又一趟"], state_dir=d, now=after_midnight)
    check("三条红项三个编号", len(set(a + b + c)), 3)
    joined = "".join(techlog.path_for(x, d).read_text(encoding="utf-8") for x in ("2026-10-12", "2026-10-13"))
    check("两天的文件合起来三条都还在", len(techlog.unhandled(joined)), 3)

    if fails:
        print(f"\nFAILED: {fails}")
        sys.exit(1)


def _part_no_model_daily_report():
    """The model-written daily report is gone; the template is the only path."""
    import inspect

    from ark_relay.core import summary
    from ark_relay.features import report

    for label, ok in (("summary.daily_report removed", not hasattr(summary, "daily_report")),
                      ("_compose_daily has no model branch", "日报由模型撰写" not in inspect.getsource(report._compose_daily))):
        print(("  ✓ " if ok else "  ✗ ") + label)
        if not ok:
            fails.append(label)


def _part_report_due():
    """日报什么时候该发、什么时候不许发，以及发出去的那份里必须有什么。"""
    import json
    import logging
    import types
    from datetime import datetime, timedelta

    from ark_relay.features import report, report as scoreboard
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.ledger import State

    # ---------------------------------------------------------- 把外面的世界掐掉
    # 卡池要连 prts.wiki / 库街区 / 森空岛；撰写模型要连大模型。两个都换成本地假货，
    # 这个文件才既跑得快又不会因为别人家的网站抖一下就变红。
    SCHEDULE: list = []
    report.plan = types.SimpleNamespace(
        schedule=lambda automas_dir: list(SCHEDULE),
        next_plan=lambda automas_dir: "",
        activity_countdown=lambda automas_dir: "",
    )
    report.banners = types.SimpleNamespace(
        collect=lambda now, skland_token="", failed=None, notes=None, trace=None, versions=None, leads=None,
        read_image=None, state_dir=None: ([], {}),
        image_reader=lambda state_dir: None,
        render=lambda rows, now, nxt, notes=None, trace=None, failed=None, leads=None: "",
        Trace=types.SimpleNamespace(new=lambda: None),
        save_trace=lambda state_dir, now, text, tr: None,
        update_history=lambda state_dir, now: [],
    )

    class LogGrab(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records: list = []

        def emit(self, record):
            self.records.append(record)

        def worst(self):
            return max((r.levelno for r in self.records), default=0)

    GRAB = LogGrab()
    # 直接挂 report 自己那个 logger 对象，不写死日志名：名字要是改了，这里跟着走。
    report.log.addHandler(GRAB)
    report.log.setLevel(logging.DEBUG)

    # --------------------------------------------------------------- 替身零件
    class FakeNotifier:
        """记下发出去的每一条；`broken` 时每次都返回「一个渠道都没送到」。"""

        def __init__(self):
            self.sent: list = []
            self.groups: list = []
            self.broken = False

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body, alert, daily))
            return ["Server酱: 假装挂了"] if self.broken else []

        def send_group(self, title, body):
            self.groups.append((title, body))
            return []

        def send_group_image(self, path):
            return []

        def titles(self):
            return [t for t, *_ in self.sent]

    class Eng:
        """Engine 里跟日报有关的那一小块，其余全部换成可控的替身。
    转发方式跟 engine.py 里一模一样，改了那边的签名这里会当场对不上。"""

        def __init__(self, state, *, interim=True, last_run_after="21:30"):
            self.cfg = types.SimpleNamespace(
                automas_dir=None, history_dir=None, okww_dir=None, skland_token="",
                state_dir=None, last_run_after=last_run_after, interim_report=interim)
            self.state = state
            self.notifier = FakeNotifier()
            self.running = False
            self.unfinished: list = []
            self.manual = False

        def _report_cutoff(self, now):
            return report._report_cutoff(self, now)

        def _scripts_running(self):
            return self.running

        def _unfinished_queues(self, now, entries):
            return list(self.unfinished)

        def _round_is_manual(self, new_entries):
            return self.manual

        def _compose_daily(self, day, entries):
            return report._compose_daily(self, day, entries)

        def _announce_banners(self, now, nxt):
            return None

        def send_daily_now(self, mark=True, label="临时查看"):
            return report.send_daily_now(self, mark, label)

    TODAY = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    YDAY = (datetime.now(tz=SERVER_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    def entry(day, n=1, script="MAA", ok=True):
        start = datetime.fromisoformat(f"{day}T09:0{n}:00+08:00")
        return {"run_id": f"{day}/ark/0{n}", "script": script, "user": "ark",
                "started": start.isoformat(),
                "finished": (start + timedelta(minutes=20)).isoformat(),
                "ok": ok, "failed_tasks": [] if ok else ["某一步炸了"], "raw": {}}

    def make(entries_by_day=None, **kw):
        """一台干净的机器：真 State（记号和账本都是真的），假通知和假队列。"""
        st = State(tmpdir())
        for day, rows in (entries_by_day or {}).items():
            st.ledger_path(day).write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                encoding="utf-8")
        return Eng(st, **kw)

    def at(day, hhmm):
        return datetime.fromisoformat(f"{day}T{hhmm}:00+08:00").astimezone(SERVER_TZ)

    # =========================================================== 日报什么时候到点
    print("[到点时刻跟着 AUTO-MAS 自己的队列走，不是写死的]")
    SCHEDULE[:] = [{"name": "早班", "times": ["09:00"]},
                   {"name": "晚班", "times": ["21:25"]}]
    e = make()
    check("取最晚那一条队列的时刻",
          e._report_cutoff(at(TODAY, "12:00")).strftime("%H:%M"), "21:25")
    SCHEDULE[:] = []
    check("读不到队列才退回 ARK_LAST_RUN_AFTER",
          e._report_cutoff(at(TODAY, "12:00")).strftime("%H:%M"), "21:30")
    bad = make(last_run_after="晚上")
    try:
        got = bad._report_cutoff(at(TODAY, "12:00")).strftime("%H:%M")
    except Exception as exc:  # noqa: BLE001
        got = f"抛了 {exc!r}"
    check("时刻写坏了兜底 21:30，不抛异常——抛了这一轮连关机也一起没了", got, "21:30")

    # ================================================= 昨天没发出去，今天必须先补
    print("\n[昨天的日报没发出去：过了零点只剩这一次机会]")
    e = make({YDAY: [entry(YDAY)], TODAY: [entry(TODAY)]})
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("补发那条排在最前", e.notifier.titles()[0].endswith("（补发）"), True)
    check("昨天的记号落上了", e.state.report_sent(YDAY), True)
    check("今天那条照发，不是拿补发顶替", len(e.notifier.sent), 2)
    check("今天的记号也落上了", e.state.report_sent(TODAY), True)

    print("\n[补发也推不出去时：不许落记号，下一轮还要再补]")
    e = make({YDAY: [entry(YDAY)]})
    e.notifier.broken = True
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("试着发了", len(e.notifier.sent), 1)
    check("昨天的记号绝不能落", e.state.report_sent(YDAY), False)
    e.notifier.broken = False
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("下一轮补上了", e.state.report_sent(YDAY), True)

    print("\n[昨天已经发过 / 昨天一条记录都没有：都不许补]")
    e = make({YDAY: [entry(YDAY)]})
    e.state.mark_report_sent(YDAY)
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("发过了就不重发", e.notifier.sent, [])
    e = make({TODAY: [entry(TODAY)]})
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("昨天没跑过就不补一份空的",
          [t for t in e.notifier.titles() if "补发" in t], [])

    # ============================================================ 同一天只发一遍
    print("\n[同一天不许发两遍]")
    e = make({TODAY: [entry(TODAY)]})
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("发了一条", len(e.notifier.sent), 1)
    check("落了 report:<日期> 记号", e.state.report_sent(TODAY), True)
    report._maybe_daily_report(e, at(TODAY, "22:05"))
    check("第二轮什么都不发", len(e.notifier.sent), 1)
    check("记号是写在 marks 里的",
          e.state.store.get("marks", f"report:{TODAY}") is not None, True)

    print("\n[当天部署过的更新说明进技术日志，日报只留一句次数（D-1010；更新通知本身不再推）]")
    from _parts import tmpdir as _tmpd0

    def _tmpd():
        # <tmp>/state, so the technical log (<state>/../tech) stays inside the tmp dir.
        d = _tmpd0() / "state"
        d.mkdir()
        return d

    e = make({TODAY: [entry(TODAY)]})
    e.cfg.state_dir = _tmpd()
    report.remember_change(e.cfg.state_dir, "周本领奖补回来了。", "20260914104917", day=TODAY)
    report.remember_change(e.cfg.state_dir, "通知分三路。", "20260914104918", day=TODAY)
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    body = e.notifier.sent[-1][1]
    check("日报不带「今天中继改了什么」", "今天中继改了什么" in body, False)
    check("日报不带部署说明", "周本领奖补回来了" in body or "通知分三路" in body, False)
    check("日报末尾一句部署次数", body.rstrip().endswith("今天中继更新了 2 次"), True)
    tech = (e.cfg.state_dir.parent / "tech" / f"{TODAY}.md").read_text(encoding="utf-8")
    check("两次部署的说明都在技术日志里", "## " in tech and "今天中继改了什么" in tech
          and "周本领奖补回来了" in tech and "通知分三路" in tech, True)
    check("日报走的是 daily（进群）", e.notifier.sent[-1][3], True)
    e2 = make({TODAY: [entry(TODAY)]})
    e2.cfg.state_dir = _tmpd()
    report._maybe_daily_report(e2, at(TODAY, "22:00"))
    check("没部署过就没有这一句", "中继更新了" in e2.notifier.sent[-1][1], False)

    print("\n[采集补跑结果按日报白名单绝不进用户日报，只记技术日志]")
    import json as _json
    e = make({TODAY: [entry(TODAY)]})
    e.cfg.state_dir = _tmpd()
    (e.cfg.state_dir / "collect-retry").mkdir()
    (e.cfg.state_dir / "collect-retry" / f"{TODAY}.json").write_text(_json.dumps(
        {"run_id": "x", "routes": ["AutoCollectRoute15", "AutoCollectRoute16"], "passed": ["AutoCollectRoute15"],
         "failed": ["AutoCollectRoute16"], "unknown": [], "note": ""}), encoding="utf-8")
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    body = e.notifier.sent[-1][1]
    tech = (e.cfg.state_dir.parent / "tech" / f"{TODAY}.md").read_text(encoding="utf-8")
    check("用户日报绝不含采集补跑/仍失败文案", ("自动采集补跑" in body, "仍失败" in body), (False, False))
    check("采集补跑明细记在技术日志里", "自动采集补跑：走通 AutoCollectRoute15；仍失败 AutoCollectRoute16" in tech, True)

    print("\n[推送失败时不许落记号：落了这一天就永远丢了]")
    e = make({TODAY: [entry(TODAY)]})
    e.notifier.broken = True
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("没落记号", e.state.report_sent(TODAY), False)
    e.notifier.broken = False
    report._maybe_daily_report(e, at(TODAY, "22:01"))
    check("下一轮重发成功", len(e.notifier.sent), 2)
    check("这才落记号", e.state.report_sent(TODAY), True)

    # ================================================================ 什么时候等
    print("\n[没到点、还在跑、队列没跑完——一律再等]")
    e = make({TODAY: [entry(TODAY)]})
    report._maybe_daily_report(e, at(TODAY, "20:00"))
    check("没到点不发", e.notifier.sent, [])
    e.running = True
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("脚本还在跑不发", e.notifier.sent, [])
    e.running = False
    e.unfinished = ["晚班还没跑完"]
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("队列没跑完不发——cutoff 就是晚班发车时刻，那几秒游戏还没起来",
          e.notifier.sent, [])
    check("也没落记号，不然晚班从此没人问", e.state.report_sent(TODAY), False)
    e.unfinished = []
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("跑完了才发", len(e.notifier.sent), 1)

    print("\n[一天里一条记录都没有]")
    e = make({TODAY: []})
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("不发空日报", e.notifier.sent, [])
    check("更不许落记号——落了，晚到的那趟就永远不会被报",
          e.state.report_sent(TODAY), False)
    print("  （人主动要的时候是另一回事：问了就得有答案）")
    e2 = make({TODAY: []})
    check("手动 report 命令照发", e2.send_daily_now(), True)
    check("正文说清楚今天没跑过", "今天没有任何运行记录。" in e2.notifier.sent[0][1], True)

    # ====================================================== 末尾那行版本记分牌
    print("\n[版本记分照算照记，但不再印进日报（用户 09-14：毫无意义）]")
    e = make({TODAY: [entry(TODAY, ok=False)]})
    e.state.store.set("versions", "code", "9.9.9")
    scoreboard.record(e.state.store, "9.9.9", ok=True)
    scoreboard.record(e.state.store, "9.9.9", ok=False)
    want_line = scoreboard.line(e.state.store, "9.9.9")
    check("记分牌自己算出来的那一串不是空的", want_line.startswith("代码 v9.9.9"), True)
    check("它数的是真跑过的趟数", "跑过 2 趟，失败 1 趟" in want_line, True)
    _, body = e._compose_daily(TODAY, e.state.read_ledger(TODAY))
    check("正文里不再有那一行", want_line in body, False)
    check("正文里没有「代码 v」字样", "代码 v" in body, False)
    e2 = make({TODAY: [entry(TODAY)]})
    _, body2 = e2._compose_daily(TODAY, e2.state.read_ledger(TODAY))
    check("没记录版本号时不留一截空尾巴", body2.rstrip(), body2)

    # ============================================== 结构化模板
    print("\n[日报只走结构化模板（模型撰写 08-30 废弃、已删），这是正常路径不是故障]")
    check("模型撰写那条路已删", hasattr(__import__("ark_relay.core.summary", fromlist=["x"]), "daily_report"), False)
    GRAB.records.clear()
    e = make({TODAY: [entry(TODAY)]})
    title, body = e._compose_daily(TODAY, e.state.read_ledger(TODAY))
    check("照样出得来一份日报", bool(title and body), True)
    check("走的是结构化模板那条路", "9:01" in body or "09:01" in body, True)
    check("日志里一条 WARNING 都不许有——假伤会让真伤没人看",
          GRAB.worst() < logging.WARNING, True)
    check("而且确实记了走白名单结构化模板",
          any("白名单结构化模板" in r.getMessage() for r in GRAB.records), True)

    # ============================================================ 白天那份速览
    print("\n[白天速览：关掉就不发]")
    e = make({TODAY: [entry(TODAY)]}, interim=False)
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("开关关着就一条都不发", e.notifier.sent, [])

    print("\n[到点之后不发速览，让真日报说话]")
    e = make({TODAY: [entry(TODAY)]})
    report._maybe_interim_report(e, at(TODAY, "22:00"))
    check("过了 cutoff 就闭嘴", e.notifier.sent, [])

    print("\n[今天日报已经发过 / 没有记录 / 还在跑 / 队列没完：都不发]")
    e = make({TODAY: [entry(TODAY)]})
    e.state.mark_report_sent(TODAY)
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("日报发过了就不再速览", e.notifier.sent, [])
    e = make({TODAY: []})
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("没记录不发", e.notifier.sent, [])
    e = make({TODAY: [entry(TODAY)]})
    e.running = True
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("还在跑不发", e.notifier.sent, [])
    e.running = False
    e.unfinished = ["早班还没跑完"]
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("队列没跑完不发", e.notifier.sent, [])

    print("\n[早班跑完就发一份速览，但**不许吃掉当天的日报**]")
    e = make({TODAY: [entry(TODAY, 1), entry(TODAY, 2)]})
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("发了一条", len(e.notifier.sent), 1)
    check("标题是 🔎 不是 📋", e.notifier.titles()[0].startswith("🔎"), True)
    check("说清是临时查看", "（临时查看）" in e.notifier.titles()[0], True)
    check("当天日报的记号绝不能落——落了晚上那份就没了",
          e.state.report_sent(TODAY), False)
    check("记下这一轮盖到第几条", e.state.interim_covered(TODAY), 2)

    print("\n[同一轮不重发；补跑多出来的那一条要另算一轮]")
    report._maybe_interim_report(e, at(TODAY, "12:05"))
    check("同一轮闭嘴", len(e.notifier.sent), 1)
    rows = e.state.read_ledger(TODAY) + [entry(TODAY, 3)]
    e.state.ledger_path(TODAY).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    report._maybe_interim_report(e, at(TODAY, "15:00"))
    check("补跑了就再报一次", len(e.notifier.sent), 2)
    check("覆盖数跟着往前推", e.state.interim_covered(TODAY), 3)

    print("\n[手动触发的那一轮要说是手动的——人得知道这份速览为什么冒出来]")
    e = make({TODAY: [entry(TODAY)]})
    e.manual = True
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("标签是手动执行", "（手动执行）" in e.notifier.titles()[0], True)

    print("\n[速览推不出去时不许记覆盖数，否则这一轮就永远没人报了]")
    e = make({TODAY: [entry(TODAY)]})
    e.notifier.broken = True
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("试着发了", len(e.notifier.sent), 1)
    check("没记覆盖数", e.state.interim_covered(TODAY), 0)

    print("\n[只有我们自己的测试跑（测试窗口里）的一轮不推速览——测试不进他眼（10-12 18:29 实发过一次）]")
    e = make({TODAY: [entry(TODAY)]})
    e.cfg.state_dir = e.state.dir
    (e.state.dir / "test-windows.json").write_text(json.dumps(
        [{"since": f"{TODAY}T09:00:00+08:00", "until": f"{TODAY}T09:02:00+08:00"}]),
        encoding="utf-8")
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("测试那一轮一条都不发", e.notifier.sent, [])
    check("但要记成已覆盖，下一轮真跑不把它算进去", e.state.interim_covered(TODAY), 1)
    rows = e.state.read_ledger(TODAY) + [entry(TODAY, 5)]
    e.state.ledger_path(TODAY).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    report._maybe_interim_report(e, at(TODAY, "15:00"))
    check("窗口外的真跑照常报", len(e.notifier.sent), 1)


def _part_llm_breaker():
    """The wording model is a garnish, but a dead endpoint is not free: each attempt
can cost the full 60 s timeout, inside the path that must finish before the
machine may power off. After a failure it rests summary.REST_S, then is asked again
(audit 11-08 B-D7: until then one failure closed it for the whole process); the group
hears of it once per process.
    """
    import logging
    import time

    from ark_relay.core import summary


    class Cfg:
        llm_key = "sk-test"
        llm_provider = "openai"
        llm_model = "deepseek-chat"
        llm_base_url = "https://api.deepseek.com"

    calls = []
    def slow_and_broken(*a, **kw):
        calls.append(1)
        time.sleep(0.05)                      # stand-in for a 60 s timeout
        raise OSError("connection refused")

    summary.urllib.request.urlopen = slow_and_broken
    summary._endpoint_dead = None
    NOW = [1000.0]
    summary._clock = lambda: NOW[0]


    class Levels(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.levels = []

        def emit(self, record):
            self.levels.append(record.levelname)


    levels = Levels()
    summary.log.addHandler(levels)
    summary.log.setLevel(logging.DEBUG)
    summary.log.propagate = False

    print("[first call tries, and fails]")
    check("returns nothing", summary._ask(Cfg(), "hi"), "")
    check("did attempt", len(calls), 1)

    print("\n[every later call in this process is free]")
    t0 = time.monotonic()
    for _ in range(20):
        summary._ask(Cfg(), "hi")
    elapsed = time.monotonic() - t0
    check("no further attempts", len(calls), 1)
    check("cost ~nothing", elapsed < 0.05, True)
    check("one WARNING (the group hears of it)", levels.levels, ["WARNING"])

    print("\n[after the rest it is asked again; failing again is INFO, not a second push]")
    NOW[0] += summary.REST_S - 1
    summary._ask(Cfg(), "hi")
    check("just before the rest ends: still skipped", len(calls), 1)
    NOW[0] += 2
    summary._ask(Cfg(), "hi")
    check("after the rest: asked again", len(calls), 2)
    check("……that failure is INFO", levels.levels, ["WARNING", "INFO"])


    class Resp:
        def read(self):
            return '{"choices": [{"message": {"content": "好"}}]}'.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


    summary.urllib.request.urlopen = lambda *a, **kw: calls.append(1) or Resp()
    NOW[0] += summary.REST_S
    check("back: the answer is used", summary._ask(Cfg(), "hi"), "好")
    check("……and the next call is not held back", (summary._endpoint_dead, summary._ask(Cfg(), "hi")), (None, "好"))
    summary.urllib.request.urlopen = slow_and_broken
    summary._endpoint_dead = NOW[0]          # dead again, resting
    calls[:] = [1]

    print("\n[the report still renders without it]")
    entry = {"run_id": "x", "script": "MAA", "user": "arknights",
             "started": "2026-08-21T21:30:00+08:00",
             "finished": "2026-08-21T22:15:00+08:00", "ok": True}
    check("diagnose returns empty, caller falls back",
          summary.diagnose(Cfg(), entry["script"], ["x"], "log tail"), "")

    print("\n[an explicit check must really ask again]")
    try:
        summary.check(Cfg())
    except Exception:  # noqa: BLE001
        pass
    check("breaker was reset by check()", len(calls), 2)

    print("\n[no key at all: never attempts]")
    class NoKey(Cfg):
        llm_key = ""
    summary._endpoint_dead = None
    before = len(calls)
    check("returns nothing", summary._ask(NoKey(), "hi"), "")
    check("no attempt", len(calls), before)


def _part_scoreboard_main():
    """版本记分牌：每个代码版本跑过几趟、失败几趟，由中继自己数。"""
    import json
    from datetime import datetime, timedelta

    from ark_relay.features import report as scoreboard
    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.core.ledger import State

    def rec(ok=True, transitional=False, run_id="r1"):
        now = datetime.now(tz=SERVER_TZ)
        return RunRecord(
            run_id=run_id, script="OK-WW", user="wuwa",
            started=now - timedelta(minutes=5), finished=now,
            ok=ok, failed_tasks=[] if ok else ["某一步"], duration_known=True,
            transitional=transitional, raw={})

    print("[数得对：成功、失败、被重试取代的各算什么]")
    d = tmpdir()
    st = State(d)
    st.store.set("versions", "code", "20260908010000")
    st.append_ledger(rec(ok=True, run_id="a"))
    st.append_ledger(rec(ok=False, run_id="b"))
    st.append_ledger(rec(ok=False, transitional=True, run_id="c"))
    board = st.store.get("versions", "scoreboard")["20260908010000"]
    check("三趟都数进去了", board["runs"], 3)
    check("只有真失败那一趟算失败", board["failed"], 1)
    check("记了起算时刻", bool(board.get("since")), True)

    print("\n[那一行的措辞]")
    line = scoreboard.line(st.store, "20260908010000")
    check("点名了版本号", "20260908010000" in line, True)
    check("说了跑过几趟", "跑过 3 趟" in line, True)
    check("说了失败几趟", "失败 1 趟" in line, True)

    st2 = State(tmpdir())
    st2.store.set("versions", "code", "v2")
    st2.append_ledger(rec(ok=True, run_id="x"))
    check("一趟没失败时明说", "一趟没失败" in scoreboard.line(st2.store, "v2"), True)
    check("没跑过的版本也有话说",
          scoreboard.line(st2.store, "从没跑过的版本"), "代码 v从没跑过的版本 · 这版还没跑过一趟")
    check("版本号读不到就不出这一行", scoreboard.line(st2.store, ""), "")

    print("\n[换了版本各记各的，不混在一起]")
    st.store.set("versions", "code", "20260908020000")
    st.append_ledger(rec(ok=False, run_id="d"))
    board = st.store.get("versions", "scoreboard")
    check("旧版本的账没被改", board["20260908010000"]["runs"], 3)
    check("新版本单独一条", board["20260908020000"], {"runs": 1, "failed": 1,
                                                       "since": board["20260908020000"]["since"]})

    print("\n[只留最近几个版本，state.json 不许无限长]")
    st3 = State(tmpdir())
    for i in range(scoreboard.KEEP_VERSIONS + 5):
        st3.store.set("versions", "code", f"v{i:03d}")
        st3.append_ledger(rec(run_id=f"n{i}"))
    board = st3.store.get("versions", "scoreboard")
    check(f"最多留 {scoreboard.KEEP_VERSIONS} 个", len(board), scoreboard.KEEP_VERSIONS)
    check("留的是最新的那些", "v012" in board and "v000" not in board, True)

    print("\n[记分牌坏了也不许拖垮记账——账本是主线]")
    d4 = tmpdir()
    st4 = State(d4)
    st4.store.set("versions", "code", "v9")
    orig = scoreboard.record
    scoreboard.record = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("故意炸"))
    try:
        st4.append_ledger(rec(run_id="boom"))
    finally:
        scoreboard.record = orig
    boom = rec(run_id="boom")
    day = boom.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
    lines = [json.loads(x) for x in (d4 / f"ledger-{day}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    check("账本照样写进去了", [x["run_id"] for x in lines], ["boom"])

    print("\n[跨午夜：00:03 跑完、23:58 开始的一趟，记在开始那天的账本里]")
    d5 = tmpdir()
    st5 = State(d5)
    st5.store.set("versions", "code", "v10")
    t_end = datetime(2026, 9, 19, 0, 3, tzinfo=SERVER_TZ)
    late = RunRecord(run_id="late", script="OK-WW", user="wuwa", started=t_end - timedelta(minutes=5),
                     finished=t_end, ok=True, failed_tasks=[], duration_known=True, transitional=False, raw={})
    st5.append_ledger(late)
    check("落在 09-18 的账本", (d5 / "ledger-2026-09-18.jsonl").exists(), True)
    check("09-19 的账本不存在", (d5 / "ledger-2026-09-19.jsonl").exists(), False)
    check("记分牌照样数了这一趟", st5.store.get("versions", "scoreboard")["v10"]["runs"], 1)

    print("\n[照算照记进日志，但不再印进日报（用户 2026-09-14）]")
    src = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "report.py").read_text(encoding="utf-8")
    check("日报流程里仍然算它", "scoreboard.line(" in src, True)
    check("不再拼进正文", "(act, pool, score)" in src, False)


def _part_scoreboard_log_time():
    """The scoreboard's 「自 … 起」 is on the machine clock, like the rest of relay.log."""
    from ark_relay.core.ledger import State
    from ark_relay.features import report as scoreboard

    d = tmpdir()
    st = State(Path(d))
    st.store.set("versions", "scoreboard", {"20261012033118": {"runs": 1, "since": "2026-10-12T11:38:15+08:00"}})
    got = scoreboard.line(st.store, "20261012033118")
    ok = "（自 10-12 11:38 起）" in got
    print(("  ✓ " if ok else "  ✗ ") + got)
    print("\n" + ("all checks passed" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


def _part_scoreboard_test_window():
    """A run inside a test window does not count on the scoreboard (like the report rows)."""
    import json
    from datetime import datetime

    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.ledger import State
    from ark_relay.features import report as scoreboard

    V = "20261013030327"
    d = tmpdir()
    st = State(Path(d))
    (Path(d) / "test-windows.json").write_text(json.dumps(
        [{"since": "2026-10-13T11:05:49+08:00", "until": "2026-10-13T11:57:41+08:00"}]), encoding="utf-8")
    scoreboard.record(st.store, V, True, started=datetime(2026, 10, 13, 11, 5, 49, tzinfo=SERVER_TZ))
    check("test run not counted", (st.store.get("versions", "scoreboard") or {}).get(V), None)
    scoreboard.record(st.store, V, True, started=datetime(2026, 10, 13, 9, 0, 36, tzinfo=SERVER_TZ))
    check("real run counted", ((st.store.get("versions", "scoreboard") or {}).get(V) or {}).get("runs"), 1)
    # Booked with no start time while a window is still open (no until): a test.
    (Path(d) / "test-windows.json").write_text(json.dumps(
        [{"since": datetime.now(tz=SERVER_TZ).replace(microsecond=0).isoformat()}]), encoding="utf-8")
    scoreboard.record(st.store, V, False)
    check("open window, no start: not counted", st.store.get("versions", "scoreboard")[V].get("failed"), None)


def _part_ledger_bad_times():
    """账本里一条时间不合法的记录，不能让整天的日报发不出去。"""
    import json
    import pathlib
    from datetime import datetime

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

    from ark_relay.core import ledger as core
    from ark_relay.core.config import SERVER_TZ
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

    d = tmpdir()
    st = core.State(d)
    good = {"run_id": "a", "script": "MAA", "user": "u", "ok": True,
            "started": datetime(2026, 9, 6, 9, 0, tzinfo=SERVER_TZ).isoformat(),
            "finished": datetime(2026, 9, 6, 9, 20, tzinfo=SERVER_TZ).isoformat()}
    bad_value = {**good, "run_id": "b", "started": "2026-09-06 09:0"}   # 被截断的一行
    bad_type = {**good, "run_id": "c", "finished": None}
    (d / "ledger-2026-09-06.jsonl").write_text(
        "\n".join(json.dumps(x) for x in (good, bad_value, bad_type)) + "\n", encoding="utf-8")

    rows = st.read_ledger("2026-09-06")
    ids = [r["run_id"] for r in rows]
    if ids != ["a"]:
        fails.append(f"应只留下合法那条，得到 {ids}")

    # 留下的那些，日报模板必须能渲染（这正是原来会炸的地方）
    try:
        title, body = core.format_daily("2026-09-06", rows)
        if "明日方舟" not in body:
            fails.append("日报里没有那条合法记录")
    except Exception as exc:  # noqa: BLE001
        fails.append(f"日报渲染炸了：{exc}")

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_ledger_guard():
    """A malformed ledger line must not be able to keep the machine powered on."""
    import json, logging

    from ark_relay.core.ledger import State, format_daily, log as core_log

    GOOD = {"run_id": "2026-08-21/arknights/21-30-00", "script": "MAA",
            "user": "arknights", "started": "2026-08-21T21:30:00+08:00",
            "finished": "2026-08-21T22:15:00+08:00", "ok": True,
            "failed_tasks": [], "raw": {"sanity": 6}}

    def ledger(*lines):
        d = tmpdir()
        (d / "ledger-2026-08-21.jsonl").write_text("\n".join(lines), encoding="utf-8")
        return State(d)

    print("[a good line survives]")
    check("kept", len(ledger(json.dumps(GOOD)).read_ledger("2026-08-21")), 1)

    print("\n[torn line: valid JSON, missing fields]")
    st = ledger(json.dumps(GOOD), json.dumps({"script": "MaaEnd"}))
    entries = st.read_ledger("2026-08-21")
    check("incomplete one dropped", len(entries), 1)
    check("the good one kept", entries[0]["run_id"], GOOD["run_id"])

    print("\n[unparseable line]")
    check("dropped", len(ledger(json.dumps(GOOD), "{not json").read_ledger("2026-08-21")), 1)

    print("\n[unparseable line is said once, not on every read]")

    class _Warn(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())

    _w = _Warn()
    core_log.addHandler(_w)
    try:
        st = ledger(json.dumps(GOOD), '{"run_id": "torn' + "x" * 200)
        st.read_ledger("2026-08-21")
        st.read_ledger("2026-08-21")
        torn = [ln for ln in _w.lines if "不是完整的 JSON" in ln]
        check("one WARNING for two reads", len(torn), 1)
        check("quotes the line, cut at 120 chars", torn and torn[0].endswith('{"run_id": "torn' + "x" * 104), True)
        p = st.ledger_path("2026-08-21")
        p.write_text(json.dumps(GOOD), encoding="utf-8")
        st.read_ledger("2026-08-21")
        p.write_text(json.dumps(GOOD) + "\n{bad", encoding="utf-8")
        st.read_ledger("2026-08-21")
        check("said again once the line was gone and a new one tore",
              len([ln for ln in _w.lines if "不是完整的 JSON" in ln]), 2)
    finally:
        core_log.removeHandler(_w)

    print("\n[a JSON value that is not an object]")
    check("dropped", len(ledger(json.dumps(GOOD), "[1,2,3]", '"x"').read_ledger("2026-08-21")), 1)

    print("\n[the report still renders - this is the whole point]")
    entries = ledger(json.dumps(GOOD), json.dumps({"script": "MaaEnd"})).read_ledger("2026-08-21")
    try:
        title, body = format_daily("2026-08-21", entries)
        check("rendered", bool(title and body), True)
        check("mentions the surviving run", "明日方舟" in body, True)
    except Exception as exc:  # noqa: BLE001
        check(f"rendered (raised {exc!r})", False, True)

    print("\n[every entry malformed: still no crash]")
    entries = ledger(json.dumps({"script": "MAA"}), "{bad").read_ledger("2026-08-21")
    check("nothing survives", entries, [])


def _part_ledger_incomplete():
    """A failed outcome check must reach the ledger and the daily headline."""
    import json
    import tempfile

    from ark_relay.core import ledger as core

    with tempfile.TemporaryDirectory() as d:
        st = core.State(Path(d)) if hasattr(core, "State") else None
        if st is None:
            # The ledger lives on whichever class owns append_ledger/read_ledger.
            owner = next(v for v in vars(core).values()
                         if isinstance(v, type) and hasattr(v, "read_ledger") and hasattr(v, "mark_incomplete"))
            st = owner(Path(d))
        day = "2026-09-10"
        e1 = {"run_id": f"{day}/endfield/MaaEnd-05-38-38", "script": "MaaEnd", "user": "endfield",
              "started": "2026-09-10T09:38:38", "finished": "2026-09-10T10:08:38", "ok": True,
              "failed_tasks": [], "raw": {"tasks_done": ["赠送干员礼物", "装备制造", "拜访好友", "基建任务"],
                                          "tasks_evidence": {"赠送干员礼物": "获得 信用 ×400", "装备制造": "获得 嵌晶玉 ×25",
                                                             "拜访好友": "获得 信用 ×200", "基建任务": "获得 燎石子簇 ×1"}}}
        e2 = {"run_id": f"{day}/endfield/MaaEnd-06-08-39", "script": "MaaEnd", "user": "endfield",
              "started": "2026-09-10T10:08:39", "finished": "2026-09-10T10:09:35", "ok": True,
              "failed_tasks": [], "raw": {"tasks_done": ["自动采集"]}}
        with st.ledger_path(day).open("w", encoding="utf-8") as f:
            f.write(json.dumps(e1, ensure_ascii=False) + "\n" + json.dumps(e2, ensure_ascii=False) + "\n")

        print("[写回账本]")
        why = ("MaaEnd 这一轮有 2 项没干成，但它自己没报错：\n"
               "· 新版本认得全部旧设置：MaaEnd 新版本不认 36 项旧设置\n"
               "· 自动采集 真的走了路线：自动采集 38 秒就报「任务完成」，日志里没有走了路线的痕迹")
        check("找得到那条并写回", st.mark_incomplete(day, e2["run_id"], why))
        check("找不到的 run_id 返回 False", st.mark_incomplete(day, "nope", why), False)
        back = st.read_ledger(day)
        check("两条都还在", len(back), 2)
        check("第一条没被碰", "incomplete" not in back[0])
        check("第二条带上原因", back[1].get("incomplete"), why)
        check("ok 仍然是 True（不进重试队列）", back[1]["ok"], True)

        print("\n[日报白名单：incomplete 明细只留技术日志和群告警，绝不进用户日报]")
        tech_rows: list[str] = []
        title, body = core.format_daily(day, back, tech=tech_rows)
        check("标题不再是全绿，也绝不塞没干完", ("全绿" in title, "没干完" in title, "今日日报" in title), (False, False, True))
        check("正文没有 ⚠️ 和没干完原因", ("⚠️" in body, "没干完" in body), (False, False))
        check("未完成原因留在技术日志里", any("没干完：" in ln and "自动采集" in ln for ln in tech_rows), True)
        check("好的那趟还是 ✅", "✅ 终末地" in body)

        print("\n[设置被新版本重置：同样只留技术日志/群告警，日报 0 报错词且不误报全绿]")
        from ark_relay.features import outcome
        reset = outcome.summarize([outcome.Check("任务全部完成（跑完没自己退出）", True),
                                   *outcome._dropped_checks(["AutoStockBuyDailyGoodsValleyIV"])], "MaaEnd")
        tech3: list[str] = []
        title3, body3 = core.format_daily(day, [e1, dict(e2, incomplete=reset)], tech=tech3)
        check("标题用中性今日日报，不误报全绿、不塞报错词",
              ("今日日报" in title3, "全绿" in title3, "没按你的设置跑" in title3, "没干完" in title3),
              (True, False, False, False))
        check("正文不塞没按你的设置跑/没干完，明细进技术日志",
              ("没按你的设置跑" in body3, "没干完" in body3, any("没按你的设置跑：自动囤货的设置" in ln for ln in tech3)),
              (False, False, True))

        print("\n[没有 incomplete 时一切照旧]")
        title2, _ = core.format_daily(day, [e1])
        check("纯绿仍报全绿", "全绿 ✅" in title2)


def _part_ledger_once_per_run():
    """One run is one ledger line, however many times its record is handled."""
    import json
    from datetime import datetime, timedelta

    from ark_relay.core import ledger
    from ark_relay.core.config import RunRecord, SERVER_TZ

    def rec(hms: str, ok: bool = True) -> RunRecord:
        t = datetime(2026, 10, 13, int(hms[:2]), int(hms[3:5]), int(hms[6:]), tzinfo=SERVER_TZ)
        return RunRecord(run_id=f"2026-10-13/arknights/{hms}", script="MAA", user="arknights",
                         started=t, finished=t + timedelta(minutes=20), ok=ok)

    def lines(st, day="2026-10-13"):
        p = st.ledger_path(day)
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    print("[handling raises after the ledger write; the record is retried 3 times]")
    st = ledger.State(tmpdir())
    st.store.set("versions", "code", "v1")
    r = rec("05-00-00")
    for _ in range(3):
        try:
            st.append_ledger(r)
            raise RuntimeError("judging failed after the ledger write")
        except RuntimeError:
            pass
    got = lines(st)
    check("exactly one ledger line for the run", [e["run_id"] for e in got], [r.run_id])

    print("[a mark written after the first append survives the retry]")
    st.mark_incomplete("2026-10-13", r.run_id, "no evidence")
    st.append_ledger(r)
    got = lines(st)
    check("still one line, mark kept", ([e["run_id"] for e in got], got[0].get("incomplete")),
          ([r.run_id], "no evidence"))

    print("[the scoreboard counts the run once]")
    board = st.store.get("versions", "scoreboard") or {}
    check("one run scored for v1", (board.get("v1") or {}).get("runs"), 1)

    print("[another run on the same day is still appended]")
    st.append_ledger(rec("06-00-00"))
    check("two runs, two lines", len(lines(st)), 2)

    if fails:
        print(f"\n{len(fails)} FAIL: {fails}")
        sys.exit(1)


def _part_ledger_rewrite_race():
    """An append landing during a ledger rewrite must not be lost."""
    import threading
    import time
    from datetime import datetime, timedelta

    from ark_relay.core import ledger
    from ark_relay.core.config import RunRecord, SERVER_TZ

    def rec(hms: str) -> RunRecord:
        t = datetime(2026, 10, 13, int(hms[:2]), int(hms[3:5]), int(hms[6:]), tzinfo=SERVER_TZ)
        return RunRecord(run_id=f"2026-10-13/arknights/{hms}", script="MAA", user="arknights",
                         started=t, finished=t + timedelta(minutes=20), ok=True)

    print("[an append runs while mark_incomplete is between its read and its replace]")
    st = ledger.State(tmpdir())
    st.append_ledger(rec("05-00-00"))
    real_write = ledger.atomic_write_text
    other: list = []

    def slow_write(path, text, *a, **k):
        if not other:
            t = threading.Thread(target=lambda: st.append_ledger(rec("06-00-00")))
            other.append(t)
            t.start()
            time.sleep(0.3)          # the append gets every chance to land now
        return real_write(path, text, *a, **k)

    ledger.atomic_write_text = slow_write
    try:
        hit = st.mark_incomplete("2026-10-13", "2026-10-13/arknights/05-00-00", "no evidence")
    finally:
        ledger.atomic_write_text = real_write
    other[0].join(5)
    rows = {e["run_id"]: e for e in st.read_ledger("2026-10-13")}
    check("the rewrite found its line", hit, True)
    check("the rewritten line carries the mark",
          rows.get("2026-10-13/arknights/05-00-00", {}).get("incomplete"), "no evidence")
    check("the appended run is still in the day", "2026-10-13/arknights/06-00-00" in rows, True)


def _part_ledger_scoreboard_started():
    """append_ledger hands the run's start time to the scoreboard when it takes one."""
    from datetime import datetime, timedelta

    from ark_relay.core import ledger
    from ark_relay.core.config import RunRecord, SERVER_TZ

    def rec(hms: str) -> RunRecord:
        t = datetime(2026, 10, 13, int(hms[:2]), int(hms[3:5]), int(hms[6:]), tzinfo=SERVER_TZ)
        return RunRecord(run_id=f"2026-10-13/arknights/{hms}", script="MAA", user="arknights",
                         started=t, finished=t + timedelta(minutes=20), ok=True)

    real = ledger.scoreboard.record
    calls = []
    try:
        print("[scoreboard.record takes started]")

        def new_record(store, code_version, ok, transitional=False, started=None):
            calls.append(started)
        ledger.scoreboard.record = new_record
        st = ledger.State(tmpdir())
        st.store.set("versions", "code", "v1")
        r = rec("05-00-00")
        st.append_ledger(r)
        check("passed the run's start time", calls, [r.started])

        print("[older scoreboard.record without started]")
        calls.clear()

        def old_record(store, code_version, ok, transitional=False):
            calls.append("called")
        ledger.scoreboard.record = old_record
        st.append_ledger(rec("06-00-00"))
        check("still called, no TypeError", calls, ["called"])
    finally:
        ledger.scoreboard.record = real

    if fails:
        print(f"\n{len(fails)} FAIL: {fails}")
        sys.exit(1)


def _part_ledger_truth():
    """The ledger tells the truth about killed runs: their verdict and their end."""
    import json
    from datetime import datetime

    from ark_relay.core import collector
    from ark_relay.core.config import SERVER_TZ

    root = tmpdir() / "AUTO-MAS"
    hist = root / "history"
    (root / "debug").mkdir(parents=True)
    (root / "debug" / "app.log").write_text("\n".join([
        "2026-10-01 09:18:16.344 | INFO     | MAA 自动代理 | MAA 任务结果: Success!, 日志锁已释放",
        "2026-10-01 11:20:12.246 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 13:21:12.400 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 15:23:06.615 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 16:10:00.012 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: MaaEnd 进程超时, 日志锁已释放",
        "2026-10-01 16:11:10.839 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: MaaEnd 部分任务执行失败: 🎁赠送干员礼物, 日志锁已释放",
        "2026-10-01 17:27:43.100 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: Success!, 日志锁已释放",
    ]) + "\n", encoding="utf-8")

    def record(user, stem, verdict, log_lines):
        d = hist / "2026-10-01" / user
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{stem}.json").write_text(json.dumps(verdict, ensure_ascii=False), encoding="utf-8")
        (d / f"{stem}.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        return collector.parse_record(d / f"{stem}.json", hist)

    def at(hh, mm, ss=0):
        return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)

    def okww_log(h, m, s, h2, m2, s2):
        return [f"2026-10-01 {h:02d}:{m:02d}:{s:02d},787 INFO MainThread ok:ok-script init v3.6.9-beta.1",
                f"2026-10-01 {h2:02d}:{m2:02d}:{s2:02d},632 INFO MainThread UpdateCard:update_available=False"]

    print("[OK-WW's three timed-out attempts end when AUTO-MAS killed them]")
    for stem, a, b, want in (("OK-WW-05-18-20", (9, 18, 37), (9, 19, 16), at(11, 20, 12)),
                             ("OK-WW-07-20-22", (11, 20, 35), (11, 21, 10), at(13, 21, 12)),
                             ("OK-WW-09-21-22", (13, 21, 35), (13, 22, 10), at(15, 23, 6))):
        r = record("wuwa", stem, {"general_result": "OK-WW 运行超时"}, okww_log(*a, *b))
        check(f"{stem} failed", r.ok, False)
        check(f"{stem} ends {want:%H:%M:%S}", r.finished, want)
        check(f"{stem} starts where its log starts", r.started, at(*a))

    print("\n[MaaEnd 15:24: plugin crashed, killed for 进程超时 -> a failure, ending 16:10:00]")
    r = record("endfield", "MaaEnd-11-23-07", {"maaend_result": "MaaEnd 进程超时"}, [
        "[2026-10-01 15:24:12.047] 正在连接窗口... Endfield",
        "[2026-10-01 15:26:00.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-01 15:27:00.000] 任务完成: 🎁赠送干员礼物",
        "[2026-10-01 15:28:00.000] 任务开始: 🛍️信用点购物",
        "[2026-10-01 15:29:59.681] 信用 ×300"])
    check("not a success", r.ok, False)
    check("says it timed out", r.failed_tasks, ["MaaEnd 进程超时"])
    check("ends 16:10:00", r.finished, at(16, 10, 0))

    print("\n[MaaEnd 16:11: a real partial failure keeps its own log end]")
    r = record("endfield", "MaaEnd-12-10-02",
               {"maaend_result": "MaaEnd 部分任务执行失败: 🎁赠送干员礼物、🔧装备制造"},
               ["[2026-10-01 16:11:06.462] 正在连接窗口... Endfield",
                "[2026-10-01 16:11:06.808] 稳定性最好，需要游戏窗口保持在最前且不被遮挡，会完全抢占鼠标"])
    check("failed", r.ok, False)
    check("its tasks", r.failed_tasks, ["赠送干员礼物", "装备制造"])
    check("ends 16:11:06", r.finished, at(16, 11, 6))

    print("\n[MaaEnd 16:12 Success!, MAA 09:00 Success! - unchanged]")
    r = record("endfield", "MaaEnd-12-11-12", {"maaend_result": "Success!"},
               ["[2026-10-01 16:12:15.138] 正在连接窗口... Endfield",
                "[2026-10-01 16:58:19.333] 任务开始: ❌关闭游戏（PC）",
                "[2026-10-01 16:58:22.143] 任务完成: ❌关闭游戏（PC）"])
    check("MaaEnd ok", (r.ok, r.finished), (True, at(16, 58, 22)))
    r = record("arknights", "MAA-05-00-01", {"maa_result": "Success!"},
               ["[2026-10-01 09:00:50.368][INF][Bootstrapper] ===", "[2026-10-01 09:18:15.000][INF] done"])
    check("MAA ok", (r.ok, r.finished), (True, at(9, 18, 15)))

    print("\n[MaaEnd finished every task, then never exited and was killed (09-28 11:22 shape)]")
    r = record("endfield", "MaaEnd-07-22-00", {"maaend_result": "MaaEnd 进程超时"}, [
        "[2026-10-01 10:29:47.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-01 10:40:00.000] 任务完成: 🎁赠送干员礼物",
        "[2026-10-01 11:22:10.000] 任务开始: ❌关闭游戏（PC）",
        "[2026-10-01 11:22:10.500] 任务完成: ❌关闭游戏（PC）"])
    check("the work was done -> ok", r.ok, True)
    check("marked as done-then-hung", r.raw.get("maaend_done_then_hung"), True)
    check("its work ended at 11:22:10", r.finished, at(11, 22, 10))

    print("\n[timed out, every started task finished, but 关闭游戏 never ran: hung between tasks -> failure]")
    r = record("endfield", "MaaEnd-07-30-00", {"maaend_result": "MaaEnd 进程超时"}, [
        "[2026-10-01 10:29:47.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-01 10:40:00.000] 任务完成: 🎁赠送干员礼物"])
    check("not a success", r.ok, False)
    check("says it timed out", r.failed_tasks, ["MaaEnd 进程超时"])
    check("not marked done-then-hung", r.raw.get("maaend_done_then_hung"), None)

    print("\n[timed out before any task started -> failure]")
    r = record("endfield", "MaaEnd-07-31-00", {"maaend_result": "MaaEnd 进程超时"}, [
        "[2026-10-01 10:29:47.000] 正在连接窗口... Endfield"])
    check("not a success", r.ok, False)

    print("\n[timed out inside 关闭游戏 (started, never finished) -> failure]")
    r = record("endfield", "MaaEnd-07-32-00", {"maaend_result": "MaaEnd 进程超时"}, [
        "[2026-10-01 10:29:47.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-01 10:40:00.000] 任务完成: 🎁赠送干员礼物",
        "[2026-10-01 11:22:10.000] 任务开始: ❌关闭游戏（PC）"])
    check("not a success", r.ok, False)

    print("\n[no app.log (older day, rotated away) -> keep the log end]")
    (root / "debug" / "app.log").unlink()
    r = record("wuwa", "OK-WW-01-00-00", {"general_result": "OK-WW 运行超时"}, okww_log(5, 0, 0, 5, 1, 0))
    check("falls back to the log", r.finished, at(5, 1, 0))


def _part_relay_log_rotation():
    """relay.log is rotated by size, and every reader still sees across the rotation (review of 2026-10-07, item 3).
    """
    import logging
    import logging.handlers
    import os
    import time
    from datetime import datetime

    from ark_relay import __main__ as relay_main
    from ark_relay.features import evidence as error_evidence, evidence
    from ark_relay.features import selfcheck
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import machinechecks as mc_runs, machinechecks as mc_system

    try:
        from ark_relay.core import statestore as logfile
    except ImportError:          # before the fix: there is no rotating handler at all
        logfile = None

    print("[_setup_logging：relay.log 用带大小上限的轮转 handler]")
    d = tmpdir()
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    root.handlers.clear()
    os.environ["ARK_LOG_FILE"] = str(d / "relay.log")
    try:
        relay_main._setup_logging(verbose=False)
        files = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        check("有一个写文件的 handler", len(files), 1)
        h = files[0] if files else None
        check("它会轮转", isinstance(h, logging.handlers.RotatingFileHandler), True)
        check("有大小上限", getattr(h, "maxBytes", 0) > 0, True)
        check("留了旧文件", getattr(h, "backupCount", 0) > 0, True)
        check("上限至少 8 MB（日志一天约 46 KB，轮转要很少见）", getattr(h, "maxBytes", 0) >= 8 * 1024 * 1024, True)
    finally:
        for h in root.handlers:
            h.close()
        root.handlers[:] = saved_handlers

    print("\n[真的会轮转：超过上限就挪到 relay.log.1，新内容写进新的 relay.log]")
    if logfile is None:
        check("有 ark_relay.core.logfile", False, True)
    else:
        d = tmpdir()
        lg = logging.getLogger("ark.test_texts")
        lg.propagate = False
        h = logfile.RelayLogHandler(d / "relay.log", max_bytes=2000, backups=2)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s", "%m-%d %H:%M:%S"))
        lg.addHandler(h)
        for i in range(60):
            lg.warning("line %03d %s", i, "x" * 40)
        check("relay.log.1 出现了", (d / "relay.log.1").exists(), True)
        check("relay.log 没超过上限太多", (d / "relay.log").stat().st_size < 2000 + 200, True)
        check("最后一行在 relay.log 里", "line 059" in (d / "relay.log").read_text(encoding="utf-8"), True)
        check("只留两份旧的", (d / "relay.log.3").exists(), False)

        print("\n[Windows 不让改名（有人开着 relay.log）：一行都不许丢，过后再轮转]")
        lg.removeHandler(h)
        h.close()
        d = tmpdir()
        h = logfile.RelayLogHandler(d / "relay.log", max_bytes=2000, backups=2)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s", "%m-%d %H:%M:%S"))
        lg.addHandler(h)
        # The failure is said through ark.logfile (logfile.RelayLogHandler.handle);
        # in production this handler sits on the root logger and gets that line.
        lf = logfile._log_logfile
        lf_prop, lf.propagate = lf.propagate, False
        lf.addHandler(h)
        real_rotate = h.rotate

        def locked(src, dst):
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        h.rotate = locked
        for i in range(60):
            lg.warning("held %03d %s", i, "y" * 40)
        text = (d / "relay.log").read_text(encoding="utf-8")
        check("60 行全在 relay.log 里", sum(f"held {i:03d}" in text for i in range(60)), 60)
        check("说了轮转没成", "轮转没成" in text, True)
        check("没有 relay.log.1（确实没改成名）", (d / "relay.log.1").exists(), False)
        h.rotate = real_rotate
        h._retry_at = time.monotonic() - 1          # the retry is due
        lg.warning("after the lock")
        check("锁放开后轮转成了", (d / "relay.log.1").exists(), True)
        check("轮转后新行在新文件里", "after the lock" in (d / "relay.log").read_text(encoding="utf-8"), True)
        lg.removeHandler(h)
        lf.removeHandler(h)
        lf.propagate = lf_prop
        h.close()

        print("\n[改名被拒时旧的三份一份都不许挪、不许丢（审查 10-13 s5 #1）]")
        # The stdlib shifted .2 -> .3 and .1 -> .2 before the refused rename of
        # relay.log, so every retry pushed one more backup off the end.
        d = tmpdir()
        for i, c in ((1, "A"), (2, "B"), (3, "C")):
            (d / f"relay.log.{i}").write_text(c * 10 + "\n", encoding="utf-8")
        h = logfile.RelayLogHandler(d / "relay.log", max_bytes=200, backups=3)
        lg.addHandler(h)
        lf.propagate = False
        lf.addHandler(h)
        h.rotate = locked
        for k in range(4):
            h._retry_at = time.monotonic() - 1          # every write is a due retry
            lg.warning("held %d %s", k, "z" * 250)

        def backups():
            return {i: (d / f"relay.log.{i}").read_text(encoding="utf-8")[:1]
                    if (d / f"relay.log.{i}").exists() else None for i in (1, 2, 3)}
        check("四次改名被拒后 .1/.2/.3 还是 A/B/C", backups(), {1: "A", 2: "B", 3: "C"})
        check("没留下转了一半的文件", (d / "relay.log.rotating").exists(), False)
        h.rotate = real_rotate
        h._retry_at = time.monotonic() - 1
        lg.warning("free %s", "z" * 250)
        check("放开后照常轮转：最老的 C 掉了，A/B 往后挪", {i: v for i, v in backups().items() if i > 1},
              {2: "A", 3: "B"})
        check("被拒期间写的行进了 relay.log.1", "held 3" in (d / "relay.log.1").read_text(encoding="utf-8"), True)
        check("新行在 relay.log", "free" in (d / "relay.log").read_text(encoding="utf-8"), True)

        print("\n[上一次轮转转了一半（服务被杀）：下次轮转先把它收尾，一行不丢]")
        (d / "relay.log.rotating").write_text("HALF\n", encoding="utf-8")
        h._retry_at = time.monotonic() - 1
        lg.warning("after half %s", "z" * 250)
        texts_ = [(d / f"relay.log.{i}").read_text(encoding="utf-8") for i in (1, 2, 3)]
        check("转了一半的那份进了备份", any(t.startswith("HALF") for t in texts_), True)
        check("没留下转了一半的文件", (d / "relay.log.rotating").exists(), False)
        lg.removeHandler(h)
        lf.removeHandler(h)
        lf.propagate = lf_prop
        h.close()

    print("\n[刚轮转过：读日志的五处都还读得到 relay.log.1 里的那一段]")
    # Midday stamps: relay.log has no zone and _line_ts reads it on this computer's
    # clock (Beijing on the machine, Tokyo here), so stamps near midnight would land
    # on another day here.
    now = datetime.now(tz=SERVER_TZ)
    md = now.strftime("%m-%d")
    d = tmpdir()
    log_path = d / "relay.log"
    older = (f"{md} 12:10:00 INFO    ark.service  中继代码版本 v1\n"
             f"{md} 12:20:00 INFO    ark.engine  本轮已处理完毕，60 秒后关机\n"
             f"{md} 12:20:30 INFO    ark.service  服务停止\n")
    newer = f"{md} 12:30:00 INFO    ark.service  服务模式启动，监视 x\n"
    Path(f"{log_path}.1").write_text(older, encoding="utf-8")
    log_path.write_text(newer, encoding="utf-8")
    os.environ["ARK_LOG_FILE"] = str(log_path)

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    data, _ = error_evidence._day_tail(log_path, day_start, now.replace(hour=23, minute=59, second=59), 10_000)
    check("每日上传带上了轮转前的那一段", "本轮已处理完毕" in data.decode("utf-8"), True)
    check("每日上传也带上了新的", "服务模式启动" in data.decode("utf-8"), True)

    win = (day_start.timestamp(), now.replace(hour=23, minute=59, second=59).timestamp())
    out = evidence.slice_log(log_path, win, d / "slice" / "relay.log")
    check("证据切片带上了轮转前的那一段", out is not None and "本轮已处理完毕" in out.read_text(encoding="utf-8"), True)

    check("上机核对读得到轮转前的那一段", "本轮已处理完毕" in mc_system.read_tail(str(log_path)), True)
    check("上机核对（跑次）读得到轮转前的那一段",
          any("本轮已处理完毕" in ln for ln in mc_runs._relay_today(now)), True)

    calls = []
    real_lines = selfcheck.daily_lines
    selfcheck.daily_lines = lambda day, text: calls.append(text) or []
    try:
        selfcheck.daily_section(now.strftime("%Y-%m-%d"), str(log_path))
    finally:
        selfcheck.daily_lines = real_lines
    check("每日体检读得到轮转前的那一段", bool(calls) and "本轮已处理完毕" in calls[0], True)

    print("\n[没轮转过：照旧只读 relay.log，不多也不少]")
    d = tmpdir()
    only = d / "relay.log"
    only.write_bytes(newer.encode("utf-8"))
    if logfile is not None:
        got, cut = logfile.tail_bytes(only, 10_000)
        check("内容不变", got.decode("utf-8"), newer)
        check("没有被截", cut, False)
        got, cut = logfile.tail_bytes(only, 10)
        check("只要尾巴时只给尾巴", got, newer.encode("utf-8")[-10:])
        check("说了前面还有", cut, True)


def _part_relay_poweroff_live():
    """Only the power-off the relay itself issued may keep a teardown out of the group (2026-10-06).
    """
    import types
    from datetime import datetime, timedelta

    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()

    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any

    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(_name, _Stub(_name))

    import boot_stages
    from ark_relay.features import errwatch
    from ark_relay.features import shutdown
    from ark_relay.core.config import SERVER_TZ

    now = datetime(2026, 10, 6, 22, 0, tzinfo=SERVER_TZ)
    eng = types.SimpleNamespace(_shutdown_issued=False, _shutdown_issued_at=None)
    print("[the relay has not issued a power-off]")
    check("not ours", boot_stages._relay_poweroff_live(eng, now), False)
    print("[issued a minute ago]")
    eng._shutdown_issued, eng._shutdown_issued_at = True, now - timedelta(minutes=1)
    check("ours, under way", boot_stages._relay_poweroff_live(eng, now), True)
    print("[issued long ago and the machine is still up: no longer excused]")
    eng._shutdown_issued_at = now - timedelta(minutes=shutdown.ISSUED_STUCK_MIN)
    check("not excused any more", boot_stages._relay_poweroff_live(eng, now), False)

    print("[errwatch: a stop or Windows' shutdown alone is not the relay's power-off]")
    errwatch._relay_poweroff[0] = lambda: False
    errwatch.mark_stopping()
    try:
        check("going_down() says yes", errwatch.going_down(), True)
        check("relay_shutdown_issued() says no", errwatch.relay_shutdown_issued(), False)
    finally:
        errwatch._stopping.clear()
    print("[install wires the probe in]")

    class _N:
        def send(self, *a, **k):
            return []

    h = errwatch.install(_N(), lambda: True)
    try:
        check("relay_shutdown_issued() follows the probe", errwatch.relay_shutdown_issued(), True)
    finally:
        import logging
        logging.getLogger(errwatch.ARK).removeHandler(h)
        errwatch._relay_poweroff[0] = lambda: False
    errwatch._relay_poweroff[0] = lambda: 1 / 0
    check("a broken probe answers 「not ours」, so it pushes", errwatch.relay_shutdown_issued(), False)
    errwatch._relay_poweroff[0] = lambda: False


def _part_record_names():
    import json
    import tempfile
    from pathlib import Path

    from ark_relay.core import collector
    from ark_relay.core.config import SERVER_TZ

    BODY = {"recruit_statistics": {}, "drop_statistics": {"AT-4": {"龙门币": 1008}},
            "sanity": 1, "maa_result": "Success!"}

    def one(root: Path, day: str, user: str, stem: str):
        d = root / day / user
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{stem}.json"
        p.write_text(json.dumps(BODY, ensure_ascii=False), encoding="utf-8")
        # scan() deliberately skips a fresh .json with no .log beside it - that is
        # a run still being written. Give it the pair a finished run would have.
        p.with_suffix(".log").write_text("", encoding="utf-8")
        return collector.parse_record(p, root)

    def main(root: Path) -> int:
        old = one(root, "2026-08-22", "arknights", "05-00-01")
        check("旧命名能解析", old is not None, True)
        new = one(root, "2026-08-23", "arknights", "MAA-05-00-00")
        check("新命名能解析", new is not None, True)
        end = one(root, "2026-08-23", "endfield", "MaaEnd-05-17-35")
        check("MaaEnd 新命名能解析", end is not None, True)

        if new:
            # 05:00 on AUTO-MAS's UTC+4 clock is 09:00 server time.
            check("新命名解析出的时刻正确",
                  new.started.astimezone(SERVER_TZ).strftime("%H:%M"), "09:00")
            check("脚本识别正确", new.script, "MAA")
            check("成功状态正确", new.ok, True)

        junk = one(root, "2026-08-23", "arknights", "readme")
        check("非记录文件仍被拒绝", junk is None, True)

        # scan() must see both days
        recs = collector.scan(root, set())
        days = {r.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d") for r in recs}
        check("scan 同时看到两天", "2026-08-23" in days and "2026-08-22" in days, True)

        print("[run records whose names no longer parse: one WARNING per scan, each file once]")
        import logging
        warned = []
        h = type("W", (logging.Handler,), {"emit": lambda self, r: warned.append(r.getMessage())})(level=logging.WARNING)
        collector.log.addHandler(h)
        boot = root / "boot"
        try:
            for attr in ("_unparsed_warned", "_unparsed_new"):
                getattr(collector, attr, set()).clear()
            bad = [f"MAA_05h{i:02d}m00s" for i in range(5)]
            for stem in bad:
                one(boot, "2026-10-10", "arknights", stem)
            one(boot, "2026-10-10", "arknights", "MAA-09-00-00")
            (boot / "2026-10-10" / "arknights" / "notes.json").write_text(json.dumps({"something": 1}),
                                                                           encoding="utf-8")
            warned.clear()
            recs = collector.scan(boot, set())
            check("the well-named record is still booked", [r.run_id for r in recs], ["2026-10-10/arknights/MAA-09-00-00"])
            check("five badly named records after a boot -> one WARNING", len(warned), 1)
            check("it gives the count and names the first files",
                  bool(warned) and "5" in warned[0] and bad[0] in warned[0], True)
            check("a JSON with no result key is not among them", bool(warned) and "notes" not in warned[0], True)
            collector.scan(boot, set())
            collector.scan(boot, set())
            check("rescans -> nothing new, no WARNING", len(warned), 1)
            one(boot, "2026-10-10", "arknights", "MAA_21h30m00s")
            collector.scan(boot, set())
            check("one more badly named record -> one WARNING for just that one",
                  (len(warned), "MAA_21h30m00s" in warned[-1], bad[0] in warned[-1]), (2, True, False))
        finally:
            collector.log.removeHandler(h)

        return 0 if not fails else 1

    if __name__ == "__main__":
        with tempfile.TemporaryDirectory() as d:
            raise SystemExit(main(Path(d)))


def _part_config_no_bot():
    """A config with Server酱 but no group robot must start, with a warning."""
    import logging
    import os

    HIST = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), WECOM_BOT_URL="", SERVERCHAN_KEY="SCT-test",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_AGENTID="")
    from ark_relay.core.config import Config

    said: list = []
    h = logging.Handler()
    h.emit = lambda r: said.append((r.levelname, r.getMessage()))
    ARK_ROOT = "ark"   # the parent of every relay logger
    logging.getLogger(ARK_ROOT).addHandler(h)

    print("[Server酱 only: starts, warns that alarms go to Server酱]")
    cfg = Config()
    check("no blocking problem", cfg.validate(), [])
    check("one WARNING line naming the fallback",
          [lvl for lvl, m in said if "WECOM_BOT_URL" in m and "Server酱" in m], ["WARNING"])

    print("\n[WeCom app only: group alarms have no channel at all -> still a problem]")
    os.environ.update(SERVERCHAN_KEY="", WECOM_CORPID="c", WECOM_SECRET="s", WECOM_AGENTID="1")
    check("blocked", len(Config().validate()), 1)


def _part_config_skip():
    """AUTO-MAS refused to start a script of a running queue: said at once, with its reason."""
    import json
    import logging
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "debug").mkdir()
    MORNING, EVENING = "cc32e55a-55d0-408d-980d-642e66d111ae", "6f09a385-b0ae-4ff6-9890-50339bdaddeb"
    S_MAA, S_OKWW, S_END = ("754d129e-d587-435b-b75f-a0b91aac7020", "c5e96ddc-aae9-4a73-b6fe-1312a417382d",
                            "59da8762-8fa7-4260-8aee-10f9ca00097a")
    doc = {"instances": [{"uid": MORNING, "type": "QueueConfig"}, {"uid": EVENING, "type": "QueueConfig"}]}
    for uid, name, t, items in ((MORNING, "早班", "09:00", (S_MAA, S_OKWW, S_END)), (EVENING, "晚班", "21:30", (S_MAA,))):
        doc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                    "SubConfigsInfo": {"TimeSet": {"0": {"Info": {"Enabled": True, "Time": t}}},
                                       "QueueItem": {str(i): {"Info": {"ScriptId": s}} for i, s in enumerate(items)}}}
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    scripts = {"instances": [{"uid": s} for s in (S_MAA, S_OKWW, S_END)]}
    for uid, name, path, user in ((S_MAA, "maa明日方舟", "D:\\ark\\MAA", "arknights"),
                                  (S_OKWW, "鸣潮", "D:\\ark\\okww", "wuwa"),
                                  (S_END, "MaaEnd", "D:\\ark\\maaend", "endfield")):
        scripts[uid] = {"Info": {"Name": name, "Path": path},
                        "SubConfigsInfo": {"UserData": {"u1": {"Info": {"Name": user}}}}}
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(scripts, ensure_ascii=False), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), ARK_SHUTDOWN_AFTER_RUN="1",
                      ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.core import engine as eng
    from ark_relay.core import ledger as core, texts
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features import errwatch, handle as missed
    from ark_relay.features import runwatch
    from ark_relay.features import shutdown
    from ark_relay.features import machinecheck as _mc
    _mc.load()
    _mc_real = dict(_mc.CHECKS)
    _mc.CHECKS.clear()

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return False

    class Src:
        def fetch(self, seen):
            return []

    def at(hh, mm, ss=0):
        return datetime(2026, 10, 16, hh, mm, ss, tzinfo=SERVER_TZ)

    APPLOG = AUTOMAS / "debug" / "app.log"
    LINES = [
        # Built from line 306's task id (the queue's own task), trigger.py's documented shape.
        "2026-10-16 09:00:00.780 | INFO     | 业务调度 | 创建任务: b5f541de-20a4-4b73-856a-027cd91161b2, 模式: AutoProxy, 触发来源: scheduled_task",
        # Verbatim, app.log 291-306.
        "2026-10-16 09:34:04.904 | INFO     | 配置管理 | 开始处理通用日志, 日志长度: 637, 日志标记: Success!",
        "2026-10-16 09:34:04.906 | SUCCESS  | 配置管理 | 通用日志统计完成, 日志路径: D:\\ark\\automas\\history\\2026-10-16\\wuwa\\OK-WW-05-20-13.log",
        "2026-10-16 09:34:04.917 | INFO     | OK-WW 通知工具 | 开始推送通知, 模式: 统计信息, 标题: 10-16 |√|  wuwa 的 OK-WW 自动代理统计报告",
        "2026-10-16 09:34:04.919 | SUCCESS  | OK-WW 自动代理 | 用户 50ca12aa-0288-4592-982e-60f0bd6dc74e 的 OK-WW 自动代理任务已完成",
        "2026-10-16 09:34:04.920 | INFO     | 任务执行 | 任务收尾完成: AutoProxyTask - 用时: 1.172秒",
        "2026-10-16 09:34:04.920 | INFO     | OK-WW 调度器 | 复原 OK-WW 脚本配置文件: D:\\ark\\automas\\data\\c5e96ddc-aae9-4a73-b6fe-1312a417382d\\Temp",
        "2026-10-16 09:34:04.948 | INFO     | 任务执行 | 任务执行结束，开始收尾: OkwwManager",
        "2026-10-16 09:34:04.948 | INFO     | OK-WW 调度器 | 复原 OK-WW 脚本配置文件: D:\\ark\\automas\\data\\c5e96ddc-aae9-4a73-b6fe-1312a417382d\\Temp",
        "2026-10-16 09:34:04.984 | INFO     | OK-WW 通知工具 | 开始推送通知, 模式: 代理结果, 标题: 10-16 | OK-WW的自动代理任务报告",
        "2026-10-16 09:34:04.986 | INFO     | 任务执行 | 任务收尾完成: OkwwManager - 用时: 0.031秒",
        "2026-10-16 09:34:04.988 | INFO     | 业务调度 | 任务开始: 59da8762-8fa7-4260-8aee-10f9ca00097a",
        "2026-10-16 09:34:05.023 | WARNING  | MaaEnd 调度器 | 未通过配置检查: 未找到终末地官方启动器, 请选择鹰角官方启动器 Launcher.exe 或 Games.exe！",
        "2026-10-16 09:34:05.027 | INFO     | 任务执行 | 任务执行结束，开始收尾: MaaEndManager",
        "2026-10-16 09:34:05.029 | INFO     | 任务执行 | 任务收尾完成: MaaEndManager - 用时: 0.000秒",
        "2026-10-16 09:34:05.029 | INFO     | 任务执行 | 任务执行结束，开始收尾: Task",
        "2026-10-16 09:34:05.030 | INFO     | 业务调度 | 任务结束: b5f541de-20a4-4b73-856a-027cd91161b2",
    ]
    SKIP_AT = 12          # index of the 未通过配置检查 line

    LEDGER = [("2026-10-16/arknights/MAA-05-00-24", "MAA", "arknights", at(9, 0, 27), at(9, 18, 20), True, False),
              ("2026-10-16/wuwa/OK-WW-05-18-27", "OK-WW", "wuwa", at(9, 19, 47), at(9, 20, 1), False, True),
              ("2026-10-16/wuwa/OK-WW-05-20-13", "OK-WW", "wuwa", at(9, 21, 26), at(9, 33, 54), True, False)]

    def build(state_dir=None, lines=None):
        APPLOG.write_text("".join(ln + "\n" for ln in LINES[:lines]), encoding="utf-8")
        cfg = Config()
        cfg.state_dir = state_dir or tmpdir()
        st = State(cfg.state_dir)
        if state_dir is None:
            st.ledger_path("2026-10-16").write_text("\n".join(json.dumps(
                {"run_id": r, "script": s, "user": u, "started": a.isoformat(), "finished": b.isoformat(), "ok": ok,
                 "failed_tasks": [], "transitional": tr, "raw": {}}) for r, s, u, a, b, ok, tr in LEDGER) + "\n",
                encoding="utf-8")
        e = eng.Engine(cfg, source=Src(), state=st, notifier=Notes())
        e._scripts_running = lambda: False
        e._boot_time = lambda now: at(8, 45, 0)        # relay-1016.log: the relay came up 08:45-08:46
        e._started_at = at(8, 45, 18)
        e._handled_any = True                          # it saw MAA and OK-WW land (09:18:29, 09:34:07)
        e.state.report_sent = lambda d: True
        return e

    def alarms(e):
        return [(t, b) for t, b, a in e.notifier.sent if a]

    print("[10-16 09:34:07: the tick that read app.log tells the group at once, with AUTO-MAS's reason]")
    e = build()
    e._run_watch(at(9, 34, 7))
    got = alarms(e)
    check("one alarm", len(got), 1)
    title, body = got[0] if got else ("", "")
    check("title names MaaEnd and the shift", title, "🔌 MaaEnd 没有运行（早班）")
    check("body gives the reason in plain words", "AUTO-MAS 开跑前检查没过：找不到终末地官方启动器" in body, True)
    check("body says the run did not happen and needs a fix", "没开跑" in body and "要有人去改" in body, True)
    check("body passes texts.plain()", texts.plain(body), [])
    check("no English file names or 调度器 in it", ("Launcher.exe" in body, "调度器" in body), (False, False))

    print("\n[the skip is the shift's MaaEnd result: on the ledger as a failed run]")
    rows = [r for r in e.state.read_ledger("2026-10-16") if r["script"] == "MaaEnd"]
    check("one MaaEnd row", len(rows), 1)
    check("…failed, at 09:34:05", (rows[0]["ok"], rows[0]["started"][:19]) if rows else None,
          (False, "2026-10-16T09:34:05"))

    def overdue_at(e):
        """One minute past the shift's overdue deadline, from the same source shutdown._shift_overdue
    uses (runwatch.planned_minutes + OVERRUN_SLACK_MIN). On the machine it was 12:08 (158 min
    planned); this fixture has no history, so planned is the default and the deadline later.
    A check before the deadline proves nothing: the overdue alarm cannot fire yet."""
        limit, _ = runwatch.planned_minutes(e, 9, 0, at(9, 0))
        return at(9, 0) + timedelta(minutes=limit + runwatch.OVERRUN_SLACK_MIN + 1)

    print("\n[10:34 (the hour backstop) and the overdue check (12:08 on the machine): nothing more for the same fault]")
    first = list(got)
    e._check_missed_runs(at(10, 34, 12))
    check("no 10:34 「缺项」 alarm: only the 09:34 one", alarms(e), first)
    shutdown._alarm_shift_overdue(e, overdue_at(e))
    check("no 「一直没出结果」 alarm past the overdue deadline", alarms(e), first)
    check("the 09:34 one was not empty", len(first), 1)
    check("no overdue wake-up left for 早班", shutdown.overdue_moments(e, at(9, 35)), [])

    print("\n[the shutdown gate: the shift is over at the skip, so the machine is not held on]")
    v = shutdown.decide(e, at(9, 35))
    check("not 「shift-running」 (还差 MaaEnd)", v.code != "shift-running", True)
    # Since 2026-11-20 (the user: 「早班的游戏任务没跑完，没修好，就不能关机」) a skip like this one,
    # which needs someone to fix the launcher path, keeps the machine on (shutdown._shift_unfixed).
    check("…the decision right after the shift: held by the unfixed-shift gate, naming MaaEnd",
          (v.code, "终末地" in v.reason), ("shift-failed", True))

    print("\n[the interim / daily title is not 全绿]")
    # The same steps report._compose_daily runs before format_daily (no history log for the row).
    from ark_relay.core import collector
    from ark_relay.features import report
    entries = [collector.refresh_raw(r, HIST, None) for r in e.state.read_ledger("2026-10-16")]
    report._fill_single_run_sanity(entries)
    entries, _tests = core.split_test(entries, [])
    title2, body2 = core.format_daily("2026-10-16", entries, shifts=[("早班", "09:00"), ("晚班", "21:30")])
    check("title is not 全绿 and has no failure text (neutral 今日日报)",
          ("全绿" in title2, "没跑成" in title2, "今日日报" in title2), (False, False, True))
    check("config-skip failure stays in group alarm only, omitted from daily body",
          ("开跑前检查没过" in body2, "❌" in body2), (False, False))

    print("\n[a relay restarted on the same day re-reads app.log from the top: no second alarm]")
    e2 = build(state_dir=e.cfg.state_dir)
    e2._run_watch(at(9, 50))
    check("restarted relay: nothing pushed", alarms(e2), [])
    check("still one MaaEnd row", len([r for r in e2.state.read_ledger("2026-10-16") if r["script"] == "MaaEnd"]), 1)

    print("\n[the skip line lands ~100 ms after the queue moves on: one extra wake right after running stops]")
    e3 = build(lines=SKIP_AT)                          # the 09:34:04.988 poll: skip line not written yet
    e3._run_watch(at(9, 34, 4))
    check("nothing yet", alarms(e3), [])
    moments = runwatch.next_moments(e3, at(9, 34, 4), True)
    check("while running: the minute recheck", [m for m, _ in moments], [at(9, 35, 4)])
    moments = runwatch.next_moments(e3, at(9, 34, 7), False)
    check("running went true -> false: one wake within seconds",
          len(moments) == 1 and at(9, 34, 7) < moments[0][0] <= at(9, 34, 20), True)
    check("asked again before it: the same wake", runwatch.next_moments(e3, at(9, 34, 8), False), moments)
    after = moments[0][0] + timedelta(seconds=1) if moments else at(9, 35)
    check("after it: nothing", runwatch.next_moments(e3, after, False), [])
    with APPLOG.open("a", encoding="utf-8") as fh:
        fh.write("".join(ln + "\n" for ln in LINES[SKIP_AT:]))
    e3._run_watch(moments[0][0] if moments else at(9, 34, 17))
    check("that wake reads the skip and alarms", len(alarms(e3)), 1)

    print("\n[without a skip line, the 「缺项」 check wakes at due + partial_grace, not at the hour backstop]")
    e4 = build(lines=SKIP_AT)
    e4._run_watch(at(9, 34, 7))
    nd = e4.next_deadline(at(9, 34, 7))
    check("next wake is 10:15 (09:00 + 75)", nd and nd[0], at(10, 15))
    cap = []

    class _H(logging.Handler):
        def emit(self, rec):
            cap.append(rec)

    h = _H()
    missed._log_missed.addHandler(h)
    try:
        e4._check_missed_runs(at(10, 15, 5))
    finally:
        missed._log_missed.removeHandler(h)
    check("the 10:15 alarm went out", [t for t, _ in alarms(e4)], ["🔌 MaaEnd 没有运行（早班）"])
    check("its log line is marked as already in the group (no 🩺 copy)",
          [bool(getattr(r, errwatch.PUSHED, False)) for r in cap if r.levelno >= logging.WARNING], [True])
    check("no overdue wake-up left for 早班 (MaaEnd is already in the group)", shutdown.overdue_moments(e4, at(10, 16)), [])
    shutdown._alarm_shift_overdue(e4, overdue_at(e4))
    check("and past the overdue deadline it is not said again", [t for t, _ in alarms(e4)], ["🔌 MaaEnd 没有运行（早班）"])

    print("\n[the same run with OK-WW also still missing: the overdue alarm still names OK-WW, not MaaEnd]")
    e5 = build(lines=SKIP_AT)
    e5.state.ledger_path("2026-10-16").write_text("\n".join(json.dumps(
        {"run_id": r, "script": s, "user": u, "started": a.isoformat(), "finished": b.isoformat(), "ok": ok,
         "failed_tasks": [], "transitional": tr, "raw": {}}) for r, s, u, a, b, ok, tr in LEDGER[:1]) + "\n",
        encoding="utf-8")
    missed._settle(e5, "2026-10-16", "2026-10-16/早班/09:00/MaaEnd")
    shutdown._alarm_shift_overdue(e5, overdue_at(e5))
    over = [b for t, b in alarms(e5) if "一直没出结果" in t]
    check("one overdue alarm", len(over), 1)
    check("…it names OK-WW and not MaaEnd", (("OK-WW" in over[0]) or ("鸣潮" in over[0]), "MaaEnd" in over[0]) if over else None,
          (True, False))

    print("\n[the skip alarm fails to send: the machine is held on, as for any failed alarm, and it goes out later]")

    class Down(Notes):
        def __init__(self):
            super().__init__()
            self.up = False

        def send(self, title, body="", **kw):
            if not self.up:
                return ["wecom: down"]
            return super().send(title, body, **kw)

    e6 = build()
    e6.notifier = Down()
    e6._run_watch(at(9, 34, 7))
    check("nothing went out", alarms(e6), [])
    check("the skip waits to be sent again", len(e6._unsent_skips), 1)
    v6 = shutdown.decide(e6, at(9, 34, 8))
    check("the shutdown waits for it (not go)", v6.code, "pending")
    e6.notifier.up = True
    e6._run_watch(at(9, 35, 7))
    check("next tick: the alarm with the reason goes out",
          [("找不到终末地官方启动器" in b) for t, b in alarms(e6)], [True])
    check("nothing left to send", e6._unsent_skips, [])
    check("then the shutdown no longer waits on the alarm (the unfixed shift holds it instead)",
          shutdown.decide(e6, at(9, 35, 8)).code, "shift-failed")

    _mc.CHECKS.update(_mc_real)


def _part_config_warn_once():
    """Warnings from the config readers are said once per condition, not on every call."""
    import json
    import logging

    from ark_relay.core import mastercfg, mastercfg as mastercfg_maa, plan

    class Catch(logging.Handler):
        def __init__(self) -> None:
            super().__init__(logging.WARNING)
            self.msgs: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.msgs.append(record.getMessage())

    catch = Catch()
    for name in ("ark.mastercfg", "ark.plan"):
        logging.getLogger(name).addHandler(catch)

    def said(part: str) -> int:
        return sum(part in m for m in catch.msgs)

    root = tmpdir()
    automas = root / "automas"
    (automas / "data" / "sid" / "Default" / "ConfigFile").mkdir(parents=True)
    master = automas / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
    maaend = root / "maaend"
    (maaend / "tasks").mkdir(parents=True)
    (maaend / "interface.json").write_text('{"import": ["tasks/AutoCollect.json"]}', encoding="utf-8")
    (maaend / "tasks" / "AutoCollect.json").write_text(json.dumps({
        "task": [{"name": "AutoCollect", "label": "$task.AutoCollect.label", "option": ["AutoCollectMode"]}],
        "option": {"AutoCollectMode": {"type": "select", "label": "$opt.AutoCollectMode", "cases": []}}}),
        encoding="utf-8")

    print("[MaaEnd master copy missing, read twice]")
    mastercfg.read_maaend(automas, maaend)
    mastercfg.read_maaend(automas, maaend)
    require("「母本配置文件不在」 said once", said("母本配置文件不在") == 1, repr(catch.msgs))

    print("[master back, with an untranslated option and no language pack]")
    master.write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
        {"taskName": "AutoCollect", "enabled": True,
         "optionValues": {"AutoCollectMode": {"type": "select", "caseName": "Always"}}}]}]}), encoding="utf-8")
    for _ in range(3):
        mastercfg.read_maaend(automas, maaend)
    require("「没有中文名」 said once over three reads", said("没有中文名") == 1, repr(catch.msgs))
    require("「没有可选值」 said once over three reads", said("没有可选值") == 1, repr(catch.msgs))
    require("「中文语言包」 said once over four reads", said("中文语言包") == 1, repr(catch.msgs))

    print("[master gone again: the condition came back, so it is said again]")
    master.unlink()
    mastercfg.read_maaend(automas, maaend)
    require("「母本配置文件不在」 said a second time", said("母本配置文件不在") == 2, repr(catch.msgs))

    print("[MAA master copy missing, read twice]")
    catch.msgs.clear()
    mastercfg_maa.read_maa(automas)
    mastercfg_maa.read_maa(automas)
    require("MAA 「母本配置文件不在」 said once", said("母本配置文件不在") == 1, repr(catch.msgs))

    print("[AUTO-MAS QueueConfig.json broken, read on every tick]")
    cfg = root / "AUTO-MAS" / "config"
    cfg.mkdir(parents=True)
    (cfg / "QueueConfig.json").write_text("{broken", encoding="utf-8")
    for _ in range(3):
        plan.schedule(root / "AUTO-MAS")
    require("「读取 QueueConfig.json 失败」 said once", said("读取 QueueConfig.json 失败") == 1, repr(catch.msgs))

    print("[no AUTO-MAS config directory, plan built twice]")
    plan.next_plan(root / "nowhere")
    plan.next_plan(root / "nowhere")
    require("「找不到 AUTO-MAS 配置目录」 said once", said("找不到 AUTO-MAS 配置目录") == 1, repr(catch.msgs))

    print("[no app.asar, labels asked twice]")
    plan._asar_value_labels(root / "AUTO-MAS", root)
    plan._asar_value_labels(root / "AUTO-MAS", root)
    require("「找不到 app.asar」 said once", said("找不到 app.asar") == 1, repr(catch.msgs))


def _part_config_writers():
    """The writers that touch production config, and the reader of the
sanity-booster step.
    """
    import json

    from ark_relay.features import gameupdate
    from ark_relay.core import mastercfg


    def maa_tree(drones="Money"):
        """An AUTO-MAS data dir holding MAA's master config, plus a MAA dir."""
        root = tmpdir()
        master = root / "AUTO-MAS" / "data" / "abc123" / "Default" / "ConfigFile"
        master.mkdir(parents=True)
        doc = {"Current": "Default", "Configurations": {"Default": {"TaskQueue": [
            {"Type": "StartUp"},
            {"Type": "Infrast", "UsesOfDrones": drones},
            {"Type": "Award", "Award": True, "Mail": False, "FreeGacha": False, "Orundum": False,
             "Mining": False, "SpecialAccess": False},
        ]}}}
        (master / "gui.new.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        maa = root / "MAA" / "config"
        maa.mkdir(parents=True)
        (maa / "gui.new.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return root / "AUTO-MAS", root / "MAA"


    def drones_in(path):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return mastercfg._maa_infrast(doc)["UsesOfDrones"]


    print("[无人机用途：改一次，两份都写到了]")
    automas, maa = maa_tree("Money")
    ok, msg = mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "PureGold")
    check("成功", ok, True)
    check("母本写了", drones_in(automas / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json"),
          "PureGold")
    check("MAA 目录那份也写了", drones_in(maa / "config" / "gui.new.json"), "PureGold")
    check("报告写清前后", ("龙门币" in msg and "赤金" in msg), True)
    check("报告说了写了几份", "2 份" in msg, True)

    print("\n[本来就是这个值：照样算成功，但不许假装改过]")
    ok, msg = mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "PureGold")
    check("成功", ok, True)
    check("说的是「本来就用在」", "本来就用在" in msg, True)

    print("\n[不认识的取值必须当场拒绝——826 就是编了一个含义写进去]")
    ok, msg = mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "黄金")
    check("拒绝", ok, False)
    check("盘上没被改", drones_in(maa / "config" / "gui.new.json"), "PureGold")
    check("报告列出合法取值", "_NotUse" in msg, True)

    print("\n[没开放的路径一律拒绝，不许顺手写别的字段]")
    ok, msg = mastercfg.write_maa(automas, maa, "Infrast/Drones", "Money")
    check("拒绝", ok, False)
    check("说清只开放哪一项", "Infrast/UsesOfDrones" in msg, True)

    print("\n[母本里没有基建任务：拒绝，而不是凭空造一个]")
    automas2, maa2 = maa_tree()
    f = automas2 / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json"
    f.write_text(json.dumps({"Current": "Default",
                             "Configurations": {"Default": {"TaskQueue": [{"Type": "StartUp"}]}}}),
                 encoding="utf-8")
    ok, msg = mastercfg.write_maa(automas2, maa2, "Infrast/UsesOfDrones", "Money")
    check("拒绝", ok, False)
    check("说清找不到什么", "UsesOfDrones" in msg, True)

    print("\n[领取奖励的开关：邮件那项 09-14 发现一直是关的]")
    automas3, maa3 = maa_tree("Money")
    check("读出来是关", mastercfg.read_maa(automas3)["values"].get("Award/Mail"), False)
    ok, msg = mastercfg.write_maa(automas3, maa3, "Award/Mail", True)
    check("成功", ok, True)
    check("报告写清前后", "关 → 开" in msg and "邮件" in msg, True)
    for f in (automas3 / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json", maa3 / "config" / "gui.new.json"):
        check(f"{f.parent.parent.name} 那份写了", mastercfg._maa_award(json.loads(f.read_text(encoding="utf-8")))["Mail"], True)
    check("读回是开", mastercfg.read_maa(automas3)["values"].get("Award/Mail"), True)
    ok, msg = mastercfg.write_maa(automas3, maa3, "Award/Mail", True)
    check("本来就是开的", ok and "本来就是" in msg, True)
    ok, msg = mastercfg.write_maa(automas3, maa3, "Award/Mail", "yes")
    check("非布尔值拒绝", ok, False)
    ok, msg = mastercfg.write_maa(automas3, maa3, "Award/FreeGacha", True)
    check("免费单抽现在开放，写得进去", ok, True)
    ok, msg = mastercfg.write_maa(automas3, maa3, "Award/NoSuchSwitch", True)
    check("没有的开关拒绝", ok, False)
    check("七个开关都读得出来", set(k for k in mastercfg.read_maa(automas3)["values"] if k.startswith("Award/")),
          {f"Award/{k}" for k in ("Award", "Mail", "FreeGacha", "Orundum", "Mining", "SpecialAccess", "SignInEvent")})

    print("\n[同一个任务两条：无名的真设置＋AUTO-MAS 回写时补的有名空壳（11-08 领奖励实际全关）]")

    def dup_tree():
        """The machine's master as Gemini found it on 2026-11-08: MAA's nameless entries
        hold the user's settings, the named copies appended at the end hold defaults."""
        root = tmpdir()
        master = root / "AUTO-MAS" / "data" / "abc123" / "Default" / "ConfigFile"
        master.mkdir(parents=True)
        award_off = {"Award": True, "Mail": False, "FreeGacha": False, "Orundum": False, "Mining": False,
                     "SpecialAccess": False, "SignInEvent": False}
        queue = [
            {"$type": "StartUpTask", "TaskType": "StartUp", "Name": "", "IsEnable": True, "AccountName": "a"},
            {"$type": "FightTask", "TaskType": "Fight", "Name": "理智作战", "IsEnable": True, "Stage": "1-7"},
            {"$type": "InfrastTask", "TaskType": "Infrast", "Name": "", "IsEnable": True, "UsesOfDrones": "PureGold"},
            {"$type": "MallTask", "TaskType": "Mall", "Name": "", "IsEnable": True,
             "FirstList": "招聘许可", "BlackList": "碳;家具;加急许可"},
            {"$type": "AwardTask", "TaskType": "Award", "Name": "", "IsEnable": True,
             **award_off, "Mail": True, "Orundum": True, "Mining": True, "SpecialAccess": True},
            {"$type": "FightTask", "TaskType": "Fight", "Name": "剿灭作战", "IsEnable": False, "Stage": "Annihilation"},
            {"$type": "StartUpTask", "TaskType": "StartUp", "Name": "开始唤醒", "IsEnable": False},
            {"$type": "InfrastTask", "TaskType": "Infrast", "Name": "基建换班", "IsEnable": False, "UsesOfDrones": "Money"},
            {"$type": "MallTask", "TaskType": "Mall", "Name": "信用收支", "IsEnable": False, "Shopping": True,
             "FirstList": "{{ HighPriorityDefault }}", "BlackList": "{{ BlacklistDefault }}"},
            {"$type": "AwardTask", "TaskType": "Award", "Name": "领取奖励", "IsEnable": False, **award_off},
        ]
        doc = {"Current": "Default", "Configurations": {"Default": {"TaskQueue": queue}}}
        for d in (master, root / "MAA" / "config"):
            d.mkdir(parents=True, exist_ok=True)
            (d / "gui.new.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return root / "AUTO-MAS", root / "MAA", master / "gui.new.json"

    def queue_of(path):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return doc["Configurations"]["Default"]["TaskQueue"]

    automas4, maa4, master4 = dup_tree()
    untouched = [t for t in queue_of(master4) if t.get("TaskType") != "Award"]
    shown = mastercfg.read_maa(automas4)["values"]
    check("手机页读的是 AUTO-MAS 交给 MAA 的有名那条：邮件关", shown.get("Award/Mail"), False)
    check("手机页读的是有名那条：无人机用在龙门币", shown.get("Infrast/UsesOfDrones"), "Money")
    ok, msg = mastercfg.write_maa(automas4, maa4, "Award/SignInEvent", True)
    check("写签到开关：成功", ok, True)
    for f in (master4, maa4 / "config" / "gui.new.json"):
        awards = [t for t in queue_of(f) if t.get("TaskType") == "Award"]
        check(f"{f.parent.parent.name} 那份：两条领取奖励都写上了", [t["SignInEvent"] for t in awards], [True, True])
        check(f"{f.parent.parent.name} 那份：别的任务一个字没动",
              [t for t in queue_of(f) if t.get("TaskType") != "Award"] == untouched, True)
    check("读回是开", mastercfg.read_maa(automas4)["values"].get("Award/SignInEvent"), True)
    ok, msg = mastercfg.write_maa(automas4, maa4, "Infrast/UsesOfDrones", "Chip")
    check("写无人机：两条基建都写上了",
          [t["UsesOfDrones"] for t in queue_of(master4) if t.get("TaskType") == "Infrast"], ["Chip", "Chip"])

    print("\n[开机合并：留下无名那条的真设置，占位符一个不留，名字改成 AUTO-MAS 认的]")
    automas5, maa5, master5 = dup_tree()
    before = master5.read_bytes()
    folded, note = mastercfg.heal_maa_master(automas5, maa5)
    check("合并了四种任务", sorted(folded), sorted(["开始唤醒（2 条合成 1 条）", "基建换班（2 条合成 1 条）",
                                               "信用收支（2 条合成 1 条）", "领取奖励（2 条合成 1 条）"]))
    check("报告说了两份都合了", "母本" in note and "MAA 自己那份" in note, True)
    baks = list(master5.parent.parent.glob("gui.new.json.bak-dedup-*"))
    check("母本先备份，放在 ConfigFile 外面（AUTO-MAS 会整个拷那个文件夹）", len(baks), 1)
    check("备份是原样", bool(baks) and baks[0].read_bytes() == before, True)
    for f in (master5, maa5 / "config" / "gui.new.json"):
        q = queue_of(f)
        who = f.parent.parent.name
        for task_type, zh in mastercfg.MAA_SINGLETON_TASKS.items():
            if task_type == "Recruit":   # not in this queue: nothing to fold, nothing made up
                check(f"{who}：没有的自动公招不会凭空造一条", [t for t in q if t.get("TaskType") == task_type], [])
                continue
            same = [t for t in q if t.get("TaskType") == task_type]
            check(f"{who}：{zh} 只剩一条，名字是 AUTO-MAS 认的", [t.get("Name") for t in same], [zh])
            check(f"{who}：{zh} 的 $type 在第一位", next(iter(same[0])), "$type")
        award = next(t for t in q if t.get("TaskType") == "Award")
        check(f"{who}：领取奖励留的是真设置（幸运墙开）", award["Orundum"], True)
        check(f"{who}：领取奖励的邮件开（任何一条开就开）", award["Mail"], True)
        check(f"{who}：免费单抽两条都关，还是关", award["FreeGacha"], False)
        mall = next(t for t in q if t.get("TaskType") == "Mall")
        check(f"{who}：信用收支优先买的还是招聘许可", mall["FirstList"], "招聘许可")
        check(f"{who}：空壳里有、真设置里没有的项补上了", mall.get("Shopping"), True)
        check(f"{who}：文件里一个占位符都没剩", "{{" in f.read_text(encoding="utf-8"), False)
        check(f"{who}：无人机还是真设置的赤金", next(t for t in q if t.get("TaskType") == "Infrast")["UsesOfDrones"],
              "PureGold")
        check(f"{who}：理智作战、剿灭作战两条都还在（不是一种一条的任务）",
              [t["Name"] for t in q if t.get("TaskType") == "Fight"], ["理智作战", "剿灭作战"])
        check(f"{who}：领取奖励留在原来的位置", [t.get("TaskType") for t in q].index("Award"), 4)
    check("合并后手机页读到的就是真设置", mastercfg.read_maa(automas5)["values"].get("Award/Orundum"), True)
    check("再开机一次：没有可合并的，什么都不写", mastercfg.heal_maa_master(automas5, maa5), ([], ""))
    check("再开机一次：不再多备份", len(list(master5.parent.parent.glob("gui.new.json.bak-dedup-*"))), 1)

    print("\n[合并：母本读不出来就不动，说清楚]")
    automas6, maa6, master6 = dup_tree()
    master6.write_text("{ broken", encoding="utf-8")
    folded, note = mastercfg.heal_maa_master(automas6, maa6)
    check("母本没合并", "读不出来" in note and str(master6) in note, True)
    check("母本没被改", master6.read_text(encoding="utf-8"), "{ broken")
    check("没有母本：什么都不做也不报", mastercfg.heal_maa_master(tmpdir(), None), ([], ""))

    print("\n[找不到母本时不许说成功]")
    ok, msg = mastercfg.write_maa(tmpdir(), None, "Infrast/UsesOfDrones", "Money")
    check("拒绝", ok, False)
    check("说清是找不到母本", "找不到" in msg, True)

    # ------------------------------------------------- MaaEnd：理智药那个确认节点长什么样

    def nodes(node):
        d = tmpdir()
        (d / "resource" / "pipeline").mkdir(parents=True)
        (d / "resource" / "pipeline" / "nodes.json").write_text(
            json.dumps({"AutoUseSpMedicationQuickUse": node} if node is not None else {},
                       ensure_ascii=False), encoding="utf-8")
        return d


    print("\n[理智药那个确认节点：修好了才认，光换版本号不算；认不出的每次开机报群，任务照开]")
    fixed = {"recognition": {"param": {"all_of": [{"recognition": "OCR", "expected": "确认"}]}}}
    check("修好了", gameupdate.spmed_shape(nodes(fixed)), "fixed")
    broken = {"recognition": {"param": {"all_of": [{"expected": "确认"}]}}}
    check("形状不对就是没修", gameupdate.spmed_shape(nodes(broken)), "broken")
    check("all_of 是空的：认不出", gameupdate.spmed_shape(
        nodes({"recognition": {"param": {"all_of": []}}})), "unknown")
    check("节点整个不在：改名或拿掉了", gameupdate.spmed_shape(nodes(None)), "missing")
    check("节点不是字典：认不出", gameupdate.spmed_shape(nodes("会开的")), "unknown")
    check("文件不存在：读不到", gameupdate.spmed_shape(tmpdir()), "unreadable")
    check("目录是 None：没东西可查", gameupdate.spmed_shape(None), "")


def _part_dotenv_hash():
    """The relay's .env loader must not cut a value at a '#' inside quotes or inside the value.
    """
    import os

    from ark_relay import __main__ as relay_main

    env = tmpdir() / ".env"
    env.write_text("\n".join([
        "# a comment line",
        'ARKT_QUOTED="https://example.invalid/hook#frag"   # trailing comment',
        "ARKT_SINGLE='p#ss word'",
        "ARKT_BARE=abc#def",
        "ARKT_COMMENTED=plain # a note",
        "ARKT_PLAIN=value",
        "ARKT_EMPTY=   # only a note",
        'ARKT_UNCLOSED="abc',
    ]) + "\n", encoding="utf-8")
    KEYS = ("ARKT_QUOTED", "ARKT_SINGLE", "ARKT_BARE", "ARKT_COMMENTED", "ARKT_PLAIN",
            "ARKT_EMPTY", "ARKT_UNCLOSED")
    for k in KEYS:
        os.environ.pop(k, None)
    relay_main._load_dotenv(env)
    # Test-only names, read through one dict so check-docs does not list them as relay settings.
    got = {k: os.environ.get(k) for k in KEYS}

    print("[a '#' inside the value survives; a ' #' comment is still dropped]")
    check("double-quoted value keeps its '#'", got["ARKT_QUOTED"], "https://example.invalid/hook#frag")
    check("single-quoted value keeps '#' and space", got["ARKT_SINGLE"], "p#ss word")
    check("unquoted '#' with no space before it is part of the value", got["ARKT_BARE"], "abc#def")
    check("unquoted ' #' starts a comment", got["ARKT_COMMENTED"], "plain")
    check("plain value", got["ARKT_PLAIN"], "value")
    check("a value that is only a ' #' comment loads as empty (not set)", got["ARKT_EMPTY"], None)
    check("an unclosed quote is stripped, as before", got["ARKT_UNCLOSED"], "abc")


def _part_engine_pending():  # noqa: C901
    """engine.py 里没人碰过的四段：告警落盘、首启接管历史、在跑判断的缓存、tick 逐段兜底。"""
    import json
    import os
    import time
    import types
    from datetime import datetime, timedelta

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.core import engine as eng
    from ark_relay.features import modes
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State

    class Notes:
        """假通知渠道：只记下来，不发出去。"""

        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return False        # False = 送出去了（真 Notifier 的口径：返回值是「有没有失败」）

    class Src:
        """假记录源：只给没见过的记录。"""

        def __init__(self, records=()):
            self.records = list(records)
            self.calls = 0

        def fetch(self, seen):
            self.calls += 1
            return [r for r in self.records if r.run_id not in (seen or set())]

    def rec(run_id, script="OK-WW", user="wuwa", ok=False):
        now = datetime.now(tz=SERVER_TZ)
        return RunRecord(run_id=run_id, script=script, user=user,
                         started=now - timedelta(minutes=10), finished=now,
                         ok=ok, failed_tasks=[] if ok else ["任务执行：某个错"], raw={})

    def build(state_dir=None, source=None):
        """一台干净的中继。state_dir 复用同一个就等于「重启一次」。"""
        cfg = Config()
        cfg.state_dir = state_dir or tmpdir()
        e = eng.Engine(cfg, source=source or Src(), state=State(cfg.state_dir),
                       notifier=Notes())
        e._scripts_running = lambda: False
        return e

    # ---------------------------------------------------------------- 告警落盘

    print("[待推告警落盘：存进去，重启后还在（09-08 轰炸事故就炸在这一行；_recovered 旁路已彻底删除）]")
    sdir = tmpdir()
    e1 = build(sdir)
    check("eng._recovered 旁路已彻底清除", hasattr(e1, "_recovered"), False)
    e1._pending[("OK-WW", "wuwa")] = rec("2026-09-08/wuwa/OK-WW-05-22-26")
    raised = ""
    try:
        e1._persist_pending()
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    check("_persist_pending 不抛异常", raised, "")

    e2 = build(sdir)          # 重启：同一个 state 目录，全新实例
    check("重启后待推告警还在", list(e2._pending), [("OK-WW", "wuwa")])
    check("内容没走样", e2._pending[("OK-WW", "wuwa")].failed_tasks, ["任务执行：某个错"])
    check("run_id 对得上", e2._pending[("OK-WW", "wuwa")].run_id,
          "2026-09-08/wuwa/OK-WW-05-22-26")
    check("重启不算「已处理」", e2._pending[("OK-WW", "wuwa")].ok, False)

    print("\n[重启后压着的失败还带着日志尾巴，再重启一次也还在（audit s2 F4）]")
    sdir_t = tmpdir()
    logf = sdir_t / "OK-WW-05-22-26.log"
    logf.write_text("2026-09-08 05:30:01 任务执行：某个错\n", encoding="utf-8")
    et = build(sdir_t)
    held = rec("2026-09-08/wuwa/OK-WW-05-22-26")
    held.log_path = logf
    et._pending[("OK-WW", "wuwa")] = held
    et._persist_pending()
    logf.unlink()             # after the restart only the copy on disk is left
    et2 = build(sdir_t)
    check("重启后日志尾巴还在", "某个错" in et2.log_tails.get(held.run_id, ""), True)
    et2._persist_pending()
    et3 = build(sdir_t)
    check("再重启一次也还在", "某个错" in et3.log_tails.get(held.run_id, ""), True)

    print("\n[推出去之后要能清干净，否则下次开机又推一遍]")
    e2._pending.clear()
    e2._persist_pending()
    e3 = build(sdir)
    check("清空后重启是空的", dict(e3._pending), {})

    print("\n[盘上有一条残缺记录，不许连累好的那条]")
    sdir2 = tmpdir()
    st = State(sdir2)
    from ark_relay.core.collector import record_to_payload
    try:
        st.save_pending({"pending": [record_to_payload(rec("2026-09-08/wuwa/OK-WW-1")),
                                     {"run_id": "缺时间字段"}],
                         "recovered": []})
    except Exception as exc:  # noqa: BLE001
        fails.append(f"save_pending 抛异常：{type(exc).__name__}: {exc}")
    import logging

    class _Warnings(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())

    _w = _Warnings()
    eng.log.addHandler(_w)
    try:
        e4 = build(sdir2)
    finally:
        eng.log.removeHandler(_w)
    check("好的那条读回来了", [r.run_id for r in e4._pending.values()],
          ["2026-09-08/wuwa/OK-WW-1"])
    check("丢掉的那条说了一声（WARNING，带 run_id）",
          [ln for ln in _w.lines if "恢复不出来" in ln and "缺时间字段" in ln] != [], True)

    print("\n[从没存过时不许抛异常（全新机器第一次开机走的就是这条）]")
    raised = ""
    try:
        build(tmpdir())
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    check("空目录能起来", raised, "")

    # ---------------------------------------------------------------- 首次启动

    print("\n[bootstrap：第一次启动把已有历史当作已处理]")
    old = [rec(f"2026-09-01/wuwa/OK-WW-0{i}") for i in range(1, 4)]
    sdir3 = tmpdir()
    src = Src(old)
    e5 = build(sdir3, source=src)
    check("接管了 3 条历史", e5.bootstrap(), 3)
    check("三条都记成已处理", sorted(e5.state.seen), sorted(r.run_id for r in old))
    check("seen 文件已落盘", e5.state.seen_path.exists(), True)

    print("\n[接管完再跑一轮，一条都不许推出去]")
    e5._maybe_shutdown = lambda *a, **k: False
    e5._maybe_daily_report = lambda *a, **k: False
    before = len(e5.notifier.sent)
    check("这一轮没有新记录", e5.tick(), 0)
    check("没有推送", len(e5.notifier.sent), before)

    print("\n[第二次启动不是「第一次」：历史不再接管，新记录才算新闻]")
    e6 = build(sdir3, source=Src(old))
    check("不再接管", e6.bootstrap(), 0)

    print("\n[历史是空的时候也要留下记号，否则下次开机又被当成第一次]")
    sdir4 = tmpdir()
    e7 = build(sdir4, source=Src([]))
    check("没有可接管的", e7.bootstrap(), 0)
    check("空文件也要建出来", e7.state.seen_path.exists(), True)
    e8 = build(sdir4, source=Src([rec("2026-09-08/wuwa/OK-WW-新的")]))
    check("下次启动不再当第一次", e8.bootstrap(), 0)

    # ---------------------------------------------------------------- 在跑判断

    print("\n[scripts_running：三秒缓存——一轮里十几处都在问，只许问一次]")
    real_win, real_busy, real_sub = eng.config.IS_WINDOWS, eng._automas_busy, eng.subprocess
    asked = []

    def fake_busy():
        asked.append(1)
        return fake_busy.answer

    try:
        eng.config.IS_WINDOWS = True     # the machine: the busy check asks AUTO-MAS
        eng._automas_busy = fake_busy

        fake_busy.answer = True
        eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
        check("第一次问 AUTO-MAS", eng.Engine._scripts_running(), True)
        check("确实问了一次", len(asked), 1)
        check("三秒内直接用上次的答案", eng.Engine._scripts_running(), True)
        check("没有再问第二次", len(asked), 1)

        fake_busy.answer = False
        eng.subprocess = types.SimpleNamespace(     # AUTO-MAS 说没在跑时才会去翻进程表
            run=lambda *a, **k: types.SimpleNamespace(stdout=b""),
            SubprocessError=real_sub.SubprocessError)
        check("缓存期内答案不变", eng.Engine._scripts_running(), True)
        check("缓存命中就没去问", len(asked), 1)
        eng._SCRIPTS_CACHE["at"] -= eng._SCRIPTS_TTL + 1        # 缓存过期
        check("过期后重新问", eng.Engine._scripts_running(), False)
        check("确实又问了", len(asked), 2)

        print("\n[缓存只敢缓存三秒：写配置要靠它判断，缓存久了就写进正在跑的那一份（826 那一类）]")
        check("TTL 不超过 3 秒", eng._SCRIPTS_TTL <= 3.0, True)

        print("\n[public 的 scripts_running 和内部判断必须是同一个答案]")
        e9 = build()
        del e9._scripts_running                     # 用回真的那个
        eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
        fake_busy.answer = True
        check("对外一致", e9.scripts_running(), True)

        print("\n[问不出来的时候宁可当作在跑：判断错方向就是写坏配置]")
        fake_busy.answer = None

        def blow_up(*a, **k):
            raise OSError("tasklist 跑不起来")

        eng.subprocess = types.SimpleNamespace(run=blow_up,
                                               SubprocessError=real_sub.SubprocessError)
        eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
        check("进程表也问不到 → 当作在跑", eng.Engine._scripts_running(), True)

        print("\n[Endfield.exe 也要算：MaaEnd 自己没有进程，只盯 MaaEnd.exe 会整段瞎掉]")
        for name, want in ((b"Endfield.exe", True), (b"MAA.exe", True),
                           (b"MaaEnd.exe", True), (b"explorer.exe", False)):
            eng.subprocess = types.SimpleNamespace(
                run=lambda *a, **k: types.SimpleNamespace(stdout=b'"%s","123"\r\n' % name),
                SubprocessError=real_sub.SubprocessError)
            eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
            check(f"进程表里只有 {name.decode()}", eng.Engine._scripts_running(), want)

        print("\n[OK-WW counts too, however it was started (10-27: a make-up run outside AUTO-MAS was 「nothing running」)]")
        from ark_relay.features import okww_overlay
        real_okww, real_env = okww_overlay.okww_running, os.environ.get("ARK_OKWW_DIR")
        okww_dir = tmpdir()
        logs = okww_dir / "data" / "apps" / "ok-ww" / "working" / "logs"
        logs.mkdir(parents=True)
        os.environ["ARK_OKWW_DIR"] = str(okww_dir)
        eng.subprocess = types.SimpleNamespace(                 # tasklist: only explorer
            run=lambda *a, **k: types.SimpleNamespace(stdout=b'"explorer.exe","123"\r\n'),
            SubprocessError=real_sub.SubprocessError)
        try:
            for up, quiet_s, want, label in (
                    (True, 30, True, "OK-WW up, its log written 30 s ago: running"),
                    (True, 120, True, "the 120 s travel wait (10-27 09:23:04-09:25:04): still running"),
                    (True, eng.OKWW_QUIET_MIN * 60 + 60, False, "log quiet past OKWW_QUIET_MIN: hung, not running"),
                    (False, 30, False, "no OK-WW process: not running"),
                    (None, 30, False, "process list unreadable: adds nothing")):
                okww_overlay.okww_running = lambda up=up: up
                log_file = logs / "ok-script.log"
                log_file.write_text("x", encoding="utf-8")
                os.utime(log_file, (time.time() - quiet_s, time.time() - quiet_s))
                eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
                check(label, eng.Engine._scripts_running(), want)
            okww_overlay.okww_running = lambda: True
            log_file.unlink()
            eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
            check("OK-WW up, no log to read: counted (cannot tell -> wait)", eng.Engine._scripts_running(), True)
        finally:
            okww_overlay.okww_running = real_okww
            if real_env is None:
                os.environ.pop("ARK_OKWW_DIR", None)
            else:
                os.environ["ARK_OKWW_DIR"] = real_env
    finally:
        eng.config.IS_WINDOWS, eng._automas_busy, eng.subprocess = real_win, real_busy, real_sub
        eng._SCRIPTS_CACHE.update(at=-1e9, val=False)

    # ---------------------------------------------------------------- tick 逐段兜底

    print("\n[tick 逐段兜底：八段里随便哪一段炸，另外七段照跑]")
    STEPS = ("_monthcard_notice", "_flush_pending",
             "_weekly_gates", "_check_missed_runs", "_maybe_interim_report",
             "_maybe_deferred_update", "_maybe_daily_report", "_maybe_shutdown")

    def arm(engine, broken):
        """把八段全换成记录器，其中一段改成会炸的。"""
        ran = []

        def make(name):
            def step(*a, **k):
                ran.append(name)            # 记下来再炸，证明它确实被调到了
                if name == broken:
                    raise RuntimeError(f"「{name}」这一段坏了")
            return step

        for name in STEPS:
            setattr(engine, name, make(name))
        return ran

    e10 = build()
    for broken in STEPS:
        ran = arm(e10, broken)
        raised = ""
        try:
            e10.tick()
        except Exception as exc:  # noqa: BLE001
            raised = f"{type(exc).__name__}: {exc}"
        check(f"「{broken}」炸了不许把异常抛出 tick", raised, "")
        missing = [s for s in STEPS if s not in ran]
        check(f"「{broken}」炸了，其余七段照跑", missing, [])

    print("\n[日报和关机是最后两段，被前面任何一段带走 = 机器整夜不关]")
    for broken in STEPS[:-2]:
        ran = arm(e10, broken)
        try:
            e10.tick()
        except Exception as exc:  # noqa: BLE001
            fails.append(f"「{broken}」把异常抛出了 tick：{type(exc).__name__}")
        check(f"「{broken}」炸了，日报和关机仍然跑到",
              ("_maybe_daily_report" in ran, "_maybe_shutdown" in ran), (True, True))

    print("\n[跳过模式那一段炸了也不许带走 tick（它在逐段循环之外）]")
    real_skip = modes.process_skip
    try:
        def boom(*a, **k):
            raise RuntimeError("QueueConfig 读不了")

        modes.process_skip = boom
        ran = arm(e10, None)
        raised = ""
        try:
            e10.tick()
        except Exception as exc:  # noqa: BLE001
            raised = f"{type(exc).__name__}: {exc}"
        check("跳过模式出错不抛出 tick", raised, "")
        check("八段照跑", [s for s in STEPS if s not in ran], [])
    finally:
        modes.process_skip = real_skip

    print("\n[同一条跳过模式的报错，一轮一轮地重复推 = 又一次群轰炸]")
    try:
        modes.process_skip = lambda *a, **k: ["队列「早班」不见了，恢复标记还压着"]
        e11 = build()
        e11._scripts_running = lambda: False
        for _ in range(5):
            e11._observe_modes()
        check("同一句只推一次", len(e11.notifier.sent), 1)
    finally:
        modes.process_skip = real_skip

    print("\n[处理单条记录出错，不许带走同一轮里的其他记录]")
    e12 = build(source=Src([rec("r1"), rec("r2"), rec("r3")]))
    handled = []

    def flaky(r):
        handled.append(r.run_id)
        if r.run_id == "r2":
            raise RuntimeError("这条记录处理不了")

    e12._handle = flaky
    for name in STEPS:
        setattr(e12, name, lambda *a, **k: None)
    check("三条都试过了", (e12.tick(), sorted(handled)), (3, ["r1", "r2", "r3"]))
    check("成功的两条记成已处理", sorted(e12.state.seen), ["r1", "r3"])

    print("\n[一条记录次次处理都出错：重试 HANDLE_TRIES 轮就放弃，群里只收到一条（audit s2 F3）]")
    from ark_relay.features import errwatch

    class GroupCount(errwatch.ErrorKindAlert):
        """The real errwatch handler (its level and filters), with the push replaced by a list."""

        def _take(self, record):
            self.taken.append(record.getMessage())

    sdir13 = tmpdir()
    src13 = Src([rec("bad")])
    e13 = build(sdir13, source=src13)
    e13.state.store.set("versions", "code", "v1")
    broken = [True]
    calls13 = []

    def _bad(r):
        calls13.append(r.run_id)
        if broken[0]:
            raise RuntimeError("这条记录永远处理不了")

    e13._handle = _bad
    for name in STEPS:
        setattr(e13, name, lambda *a, **k: None)
    group = GroupCount(Notes(), state_dir=tmpdir())
    group.taken = []
    ARK_ROOT = "ark"   # the parent of every relay logger
    logging.getLogger(ARK_ROOT).addHandler(group)
    for _ in range(6):                       # more ticks than the cap allows
        e13.tick()
    logging.getLogger(ARK_ROOT).removeHandler(group)
    check("群里只收到一条：最后那句「不再重试」", (len(group.taken), "不再重试" in "".join(group.taken)), (1, True))
    check("放弃后不再每轮重试", len(calls13), eng.HANDLE_TRIES)
    check("放弃的记录没混进「已处理」，记在放弃清单里带代码版本",
          ("bad" in e13.state.seen, (e13.state.store.get("queues", "given_up") or {}).get("bad", {}).get("code")),
          (False, "v1"))

    # Restart with new code (a deploy that fixed it): the record is tried again and booked.
    e13b = build(sdir13, source=src13)
    e13b.state.store.set("versions", "code", "v2")
    broken[0] = False
    e13b._handle = _bad
    for name in STEPS:
        setattr(e13b, name, lambda *a, **k: None)
    e13b.tick()
    check("部署新版后再试一次，成功就记成已处理、从放弃清单删掉",
          ("bad" in e13b.state.seen, e13b.state.store.get("queues", "given_up")), (True, None))

    # Same code after a restart: no retry.
    sdir13c = tmpdir()
    e13c = build(sdir13c, source=Src([rec("bad")]))
    e13c.state.store.set("versions", "code", "v1")
    e13c.state.store.set("queues", "given_up", {"bad": {"code": "v1", "at": datetime.now(tz=SERVER_TZ).isoformat()}})
    tried = []
    e13c._handle = lambda r: tried.append(r.run_id)
    for name in STEPS:
        setattr(e13c, name, lambda *a, **k: None)
    e13c.tick()
    check("代码没变就不再试", tried, [])

    print("[读模式开关炸了，也不许带走整轮——日报和关机在最后]")
    eng2 = build()
    ran = []
    eng2._observe_modes = lambda: (_ for _ in ()).throw(RuntimeError("模式文件读坏了"))
    for name in ("_monthcard_notice", "_flush_pending", "_maybe_daily_report"):
        setattr(eng2, name, (lambda n=name: (lambda *a, **k: ran.append(n)))())
    try:
        eng2.tick()
        check("tick 没有把异常抛出去", True, True)
    except Exception as e:  # noqa: BLE001
        check(f"tick 没有把异常抛出去（抛了 {e}）", False, True)
    check("后面的段照样跑到了", "_maybe_daily_report" in ran, True)


def _part_loop_parts():  # noqa: C901
    """主循环拆出来的两个部件：目录监听的退避、AUTO-MAS 保活的睡眠上限与退避。"""
    import types

    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()

    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any

    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    import service
    from ark_relay.features import automas_keeper, automas_keeper as automas_procs, automas_keeper as dirwatch, automas_keeper as mainloop, procwatch, procwatch as shutdown_signs

    def set_time(t):
        """service.py's code now lives in several modules, each reading its own `time`; swap it in all."""
        for m in (service, shutdown_signs, procwatch, dirwatch, automas_keeper, mainloop):
            m.time = t

    dirwatch.win32con.FILE_NOTIFY_CHANGE_FILE_NAME = 0x1
    dirwatch.win32con.FILE_NOTIFY_CHANGE_LAST_WRITE = 0x10
    import boot_stages

    class Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def exception(self, *a, **k): pass

    class Notifier:
        def __init__(self): self.sent = []
        def send(self, title, body, **k): self.sent.append(title); return []

    print("[目录监听：重建失败按 5→10→20…封顶 60 秒退避]")
    cfg = types.SimpleNamespace(history_dir=Path("/nope"))
    w = dirwatch._DirWatch(cfg, Notifier(), Log())
    w.handle = None
    boom = _Stub("win32file")
    boom.FindFirstChangeNotification = lambda *a: (_ for _ in ()).throw(OSError("no"))
    orig_file = dirwatch.win32file
    dirwatch.win32file = boom
    delays = []
    now = [1000.0]
    set_time(types.SimpleNamespace(monotonic=lambda: now[0], sleep=lambda s: None))
    for _ in range(5):
        now[0] = w.retry_at
        w.maybe_rebuild()
        delays.append(w.retry_delay)
    check("退避翻倍到 60 封顶", delays, [10.0, 20.0, 40.0, 60.0, 60.0])
    check("失败期间句柄仍是空", w.handle, None)
    now[0] = w.retry_at - 1
    before = w.retry_delay
    w.maybe_rebuild()
    check("没到点不重试", w.retry_delay, before)
    dirwatch.win32file = orig_file

    class RecLog:
        """Records (level, message) - WARNING/ERROR lines go straight to the group; INFO stays in log."""

        def __init__(self):
            self.lines = []

        def _add(self, level, fmt, *a, **k):
            self.lines.append((level, fmt % a if a else fmt))

        def info(self, fmt, *a, **k): self._add("INFO", fmt, *a, **k)
        def warning(self, fmt, *a, **k): self._add("WARNING", fmt, *a, **k)
        def exception(self, fmt, *a, **k): self._add("ERROR", fmt, *a, **k)

        def loud(self):
            """WARNING / ERROR lines errwatch pushes straight to the group."""
            return [m for lv, m in self.lines if lv != "INFO"]

        def infos(self):
            return [m for lv, m in self.lines if lv == "INFO"]

    def lost_watch():
        """A _DirWatch whose re-arm has just failed (the 2026-10-06 rule: decided by the rebuild)."""
        lg, n = RecLog(), Notifier()
        w = dirwatch._DirWatch(types.SimpleNamespace(history_dir=Path("/nope")), n, lg)
        rearm_fail = _Stub("win32file")
        rearm_fail.FindNextChangeNotification = lambda h: (_ for _ in ()).throw(OSError("rearm"))
        rearm_fail.FindCloseChangeNotification = lambda h: None
        dirwatch.win32file = rearm_fail
        w.rearm()
        return w, lg, n

    print("[目录监听：重新武装失败、几秒后自己重建好了 -> 报群（断开的原因还没查清，2026-10-10 起）]")
    now[0] = 5000.0
    w, lg, n = lost_watch()
    check("re-arm failure: nothing pushed yet", (lg.loud(), n.sent), ([], []))
    ok_file = _Stub("win32file")
    ok_file.FindFirstChangeNotification = lambda *a: "handle:9"
    dirwatch.win32file = ok_file
    now[0] = w.retry_at
    w.maybe_rebuild()
    check("rebuilt: one WARNING straight to group", len(lg.loud()), 1)
    check("it says how long and that results are handled at once again",
          bool(lg.loud()) and "目录变更通知断过" in lg.loud()[0] and "马上处理" in lg.loud()[0], True)
    check("no WATCH_LOST alarm on top", n.sent, [])
    check("armed again", (w.handle, w.lost_since), ("handle:9", None))

    print("[目录监听：断满 10 分钟还没重建 -> 报群一次；之后每次重建失败只记 INFO；最后重建好了 -> 记 INFO 闭环（不进日报也不重复刷群）]")
    now[0] = 6000.0
    w, lg, n = lost_watch()
    dirwatch.win32file = boom
    for _ in range(6):
        now[0] = max(w.retry_at, now[0])
        w.maybe_rebuild()
        now[0] += 100
    check("under 10 minutes: no alarm", n.sent, [])
    now[0] = w.lost_since + procwatch.OUTAGE_ALARM_SECONDS + 1
    w.retry_at = now[0]
    w.maybe_rebuild()
    check("10 minutes: the 「⚠️ 中继暂时不能…」 alarm, once", n.sent, [dirwatch.texts.WATCH_LOST])
    now[0] += 61
    w.retry_at = now[0]
    w.maybe_rebuild()
    check("a failed rebuild after the alarm: INFO (not pushed), no second alarm",
          (len(lg.loud()), n.sent), (0, [dirwatch.texts.WATCH_LOST]))
    check("the failed rebuild is still in the log", [lv for lv, m in lg.lines if "重建失败" in m][-1:], ["INFO"])
    for _ in range(60):     # an hour of failed rebuilds at the 60 s cap
        now[0] += 61
        w.retry_at = now[0]
        w.maybe_rebuild()
    check("an hour after the alarm: still nothing pushed, still one alarm",
          (len(lg.loud()), n.sent), (0, [dirwatch.texts.WATCH_LOST]))
    dirwatch.win32file = ok_file
    now[0] += 61
    w.retry_at = now[0]
    w.maybe_rebuild()
    check("rebuilt at last: logged as INFO closure (not pushed again, never enters daily report)",
          (len(lg.loud()), any("期间报过群" in m for m in lg.infos())), (0, True))

    print("[目录监听：断着时服务停了 -> WARNING（报群）]")
    now[0] = 9000.0
    w, lg, n = lost_watch()
    w.stopping()
    check("one WARNING", [("到中继停下时还没重建" in m) for m in lg.loud()], [True])
    w.stopping()
    check("said once", len(lg.loud()), 1)
    dirwatch.win32file = orig_file

    print("[目录监听：没配历史目录就彻底不管]")
    w2 = dirwatch._DirWatch(types.SimpleNamespace(history_dir=None), Notifier(), Log())
    w2.retry_at = 0
    w2.maybe_rebuild()
    check("不重建", w2.handle, None)

    print("[保活：句柄不在时不许睡过「该来了」那一刻]")
    k = automas_keeper._AutomasKeeper.__new__(automas_keeper._AutomasKeeper)
    k.log, k.notifier = Log(), Notifier()
    k.handle = None
    k.wmi_alive = {"ok": True}
    k.revive_deadline = 1030.0
    now[0] = 1000.0
    check("睡到 deadline（30 秒），不是一小时", k.cap_wait(3600.0), 30.0)
    k.revive_deadline = 999.0
    check("已经过点了也至少睡 1 秒", k.cap_wait(3600.0), 1.0)
    k.wmi_alive = {"ok": False}
    k.revive_deadline = None
    check("订阅不可用时退回活性检查间隔",
          k.cap_wait(3600.0), procwatch.AUTOMAS_CHECK_SECONDS)
    k.handle = object()
    check("句柄在就不压缩", k.cap_wait(3600.0), 3600.0)

    print("[保活：连败到阈值才告警，且只告一次]")
    k2 = automas_keeper._AutomasKeeper.__new__(automas_keeper._AutomasKeeper)
    n = Notifier()
    k2.log, k2.notifier = Log(), n
    k2.handle = None
    k2.wmi_alive = {"ok": True}
    k2.revive_deadline = None
    k2.revive_wait = float(automas_keeper.REVIVE_FIRST_WAIT)
    k2.revive_failures = automas_keeper.REVIVE_ALERT_AFTER - 1
    k2.revive_alerted = False
    k2.shell_only_since = None
    k2.shell_grace_noted = False
    k2.next_check = 0.0
    k2.gone = None          # no unexplained exit pending (since 2026-10-06)
    orig_running, orig_shell, orig_inst, orig_revive = (
        automas_procs._automas_running, automas_procs._automas_shell_running,
        automas_procs._installer_running, boot_stages._revive_automas)
    automas_procs._automas_running = lambda: False
    automas_procs._automas_shell_running = lambda: False
    automas_procs._installer_running = lambda: False
    boot_stages._revive_automas = lambda: None
    k2._revive(1000.0)
    check("到阈值告一次", n.sent, [dirwatch.texts.AUTOMAS_DOWN])
    k2._revive(1000.0)
    check("再败不重复告", n.sent, [dirwatch.texts.AUTOMAS_DOWN])
    automas_procs._automas_running, automas_procs._automas_shell_running = orig_running, orig_shell
    automas_procs._installer_running, boot_stages._revive_automas = orig_inst, orig_revive

    print("[保活：窗口在、后端不在 → 先给宽限，超时才动手]")
    k3 = automas_keeper._AutomasKeeper.__new__(automas_keeper._AutomasKeeper)
    k3.log, k3.notifier = Log(), Notifier()
    k3.revive_failures = 0
    k3.revive_alerted = False
    k3.shell_only_since = None
    k3.shell_grace_noted = False
    k3.gone = None
    revived = []
    automas_procs._automas_running = lambda: False
    automas_procs._automas_shell_running = lambda: True
    automas_procs._installer_running = lambda: False
    boot_stages._revive_automas = lambda: revived.append(1)
    k3._revive(1000.0)
    check("宽限期内不拉起", revived, [])
    k3._revive(1000.0 + automas_keeper.SHELL_GRACE_SECONDS - 1)
    check("还在宽限期，仍不拉起", revived, [])
    k3._revive(1000.0 + automas_keeper.SHELL_GRACE_SECONDS)
    check("超过宽限才拉起", revived, [1])
    automas_procs._automas_running, automas_procs._automas_shell_running = orig_running, orig_shell
    automas_procs._installer_running, boot_stages._revive_automas = orig_inst, orig_revive

    print("\n[清单-1108 A-04：目录监听断开时，循环按重建时刻醒，不再一觉睡到一小时的备用闹钟]")
    set_time(types.SimpleNamespace(monotonic=lambda: 5000.0, sleep=lambda s: None))
    cw = dirwatch._DirWatch(types.SimpleNamespace(history_dir=Path("/nope"), poll_seconds=300), Notifier(), Log())
    cw.handle, cw.retry_at = None, 5005.0
    check("断开、5 秒后重建：最多睡 5 秒", cw.cap_wait(3600.0), 5.0)
    cw.retry_at = 4000.0
    check("重建时刻已过：睡 1 秒就醒", cw.cap_wait(3600.0), 1.0)
    cw.retry_at = 99999.0
    check("退避再长也按定时扫描间隔醒来看记录", cw.cap_wait(3600.0), 300.0)
    cw.handle = object()
    check("挂着的时候不管", cw.cap_wait(3600.0), 3600.0)
    cw.handle = None
    cw.cfg.history_dir = None
    check("没有历史目录：不管", cw.cap_wait(3600.0), 3600.0)

    print("\n[清单-1108 A-04：几个句柄同时亮，每一个都处理，不只处理编号最小的那个]")
    lit = {1, 2, 3}
    mainloop.win32event = types.SimpleNamespace(
        WAIT_OBJECT_0=0,
        WaitForSingleObject=lambda h, ms: (_ for _ in ()).throw(OSError("closed")) if h == "gone" else (0 if h in lit else 258))
    check("等到 1 号（进程启动），2、3 号（目录变更、AUTO-MAS 退出）也亮着", mainloop._fired([0, 1, 2, 3], 1), {1, 2, 3})
    check("超时：谁也没亮", mainloop._fired([0, 5, 6], 258), set())
    check("已关掉的句柄算没亮", mainloop._fired([0, "gone", 2], 0), {0, 2})

    print("\n[清单-1108 A-05：脚本刚停，先补做推迟的待办，再跑 tick（关机判断要看见它）]")
    order = []

    def _keeper(*a):
        return types.SimpleNamespace(proc_evt="proc", handle=None, cap_wait=lambda w: w,
                                     on_process_started=lambda: order.append("proc"),
                                     stopping=lambda: None, check=lambda *x: None)

    def _roll(*a):
        return types.SimpleNamespace(cap_wait=lambda w: w, check=lambda: order.append("dayroll"))

    class _Watch:
        handle = None
        def __init__(self, *a): pass
        def maybe_rebuild(self): pass
        def cap_wait(self, w): return w
        def stopping(self): pass
        def close(self): pass

    waits = iter([258, 0])
    mainloop.win32event = types.SimpleNamespace(WAIT_OBJECT_0=0, WaitForMultipleObjects=lambda h, a, ms: next(waits),
                                                WaitForSingleObject=lambda h, ms: 258)
    saved = (mainloop.automas_keeper._AutomasKeeper, mainloop.day_roll._DayRoll, mainloop.dirwatch._DirWatch)
    mainloop.automas_keeper._AutomasKeeper, mainloop.day_roll._DayRoll, mainloop.dirwatch._DirWatch = _keeper, _roll, _Watch
    eng = types.SimpleNamespace(next_deadline=lambda: None, scripts_running=lambda: False, tick=lambda: order.append("tick"))
    try:
        mainloop._loop(types.SimpleNamespace(stop_event="stop"), types.SimpleNamespace(), eng, Notifier(),
                       types.SimpleNamespace(last_fetch_ok=True), lambda why: order.append(f"collect:{why}"), [True], Log())
    finally:
        mainloop.automas_keeper._AutomasKeeper, mainloop.day_roll._DayRoll, mainloop.dirwatch._DirWatch = saved
    check("推迟的待办在 tick 之前补做", order, ["collect:推迟补做", "tick", "dayroll"])


def _part_netretry():
    """Another try, inside the caller's own limit, for a request the network cut short
(dispatch relay-opt-round3-1108 O-03; core/netretry.py).
    """
    import http.client
    import logging
    import urllib.error
    import urllib.request
    from types import SimpleNamespace

    from ark_relay.core import notify as netretry, notify
    from ark_relay.features import maintenance as efstatus
    from ark_relay.features import needtable as build
    from ark_relay.features import phone as cos_store


    class Rows(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, record.getMessage()))


    rows = Rows()
    netretry._log_netretry.addHandler(rows)
    netretry._log_netretry.setLevel(logging.DEBUG)
    netretry._log_netretry.propagate = False
    notify._rng.seed(7)


    def http_error(code):
        return urllib.error.HTTPError("https://x.invalid/k", code, "test", {}, None)


    print("[什么算网络掐断、值得再试]")
    for exc, want in ((TimeoutError("timed out"), True), (http.client.IncompleteRead(b"half"), True),
                      (http.client.RemoteDisconnected("closed"), True), (ConnectionResetError(54, "reset"), True),
                      (urllib.error.URLError("no dns"), True), (http_error(502), True), (http_error(503), True),
                      (http_error(504), True), (http_error(404), False), (http_error(403), False),
                      (http_error(500), False), (ValueError("odd"), False)):
        check(f"{type(exc).__name__} {getattr(exc, 'code', '')}".strip(), netretry.transient(exc), want)


    class Clock:
        def __init__(self):
            self.t = 0.0

        def __call__(self):
            return self.t

        def sleep(self, s):
            self.t += s


    def run(answers, limit=8.0, cost=0.3):
        """call() over a scripted fn: each answer is raised or returned, costing `cost` seconds."""
        clock, seen = Clock(), []

        def fn(left):
            seen.append(round(left, 2))
            clock.t += cost
            got = answers.pop(0)
            if isinstance(got, BaseException):
                raise got
            return got
        rows.rows.clear()
        try:
            out = netretry.call(fn, "读测试页", limit, detail="https://x.invalid/k", clock=clock, sleep=clock.sleep)
        except Exception as exc:  # noqa: BLE001
            out = exc
        return out, seen, list(rows.rows)


    print("\n[call：在原来的时限里再试]")
    out, seen, logged = run([ConnectionResetError(54, "reset"), "ok"])
    check("断了一次、第二次成了", out, "ok")
    check("第一次用整个时限，第二次用剩下的", (seen[0], 0 < seen[1] < 8.0 - 0.3), (8.0, True))
    check("瞬态重试成功仅记 INFO（既不刷群也绝不进日报）", [lv for lv, _ in logged], ["INFO", "INFO"])
    out, seen, logged = run([http_error(503), http_error(502), http_error(504)])
    check("三次都是网关错：报最后一次", (getattr(out, "code", None), len(seen)), (504, notify._RETRIES))
    check("……没有 WARNING（由调用方报）", [lv for lv, _ in logged], ["INFO", "INFO"])
    out, seen, _ = run([http_error(404)])
    check("404：不再试，原样报出", (getattr(out, "code", None), len(seen)), (404, 1))
    out, seen, _ = run([TimeoutError("timed out"), "ok"], limit=8.0, cost=8.0)
    check("超时把时限用完：不再试（服务停止的 30 秒里放得下）", (type(out).__name__, len(seen)), ("TimeoutError", 1))
    out, seen, _ = run([ValueError("odd"), "ok"])
    check("别的错：不再试", (type(out).__name__, len(seen)), ("ValueError", 1))


    class Resp:
        def __init__(self, body=b"", status=200):
            self.body, self.status = body, status

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


    def scripted(answers):
        calls = []

        def urlopen(req, timeout=None):
            calls.append(timeout)
            got = answers.pop(0)
            if isinstance(got, BaseException):
                raise got
            return got
        return urlopen, calls


    REAL = urllib.request.urlopen
    cos = SimpleNamespace(host="b.cos.example.invalid", authorization=lambda method, key: "sig")
    real_sleep = netretry._sleep
    netretry._sleep = lambda s: None
    try:
        print("\n[腾讯云 COS：断一下再写一次；404 / 403 照旧]")
        urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
        check("写入：断了一次又写进去了", (cos_store.cos_put(cos, "state/k.json", b"{}", 8), len(calls)), (None, 2))
        urllib.request.urlopen, calls = scripted([http_error(403)])
        check("写入：403 不再试，说回 403", (cos_store.cos_put(cos, "state/k.json", b"{}", 8), len(calls)), ("回 403", 1))
        urllib.request.urlopen, calls = scripted([http_error(503), Resp(b"body")])
        check("读取：网关 503 后读到", (cos_store.cos_get(cos, "k", 8), len(calls)), ((b"body", ""), 2))
        urllib.request.urlopen, calls = scripted([http_error(404)])
        check("读取：404 就是没有这个对象，不再试", (cos_store.cos_get(cos, "k", 8), len(calls)), ((None, ""), 1))
        urllib.request.urlopen, calls = scripted([OSError("odd")])
        check("读取：别的错照旧不抛、说原因", (cos_store.cos_get(cos, "k", 8)[1], len(calls)), ("odd", 1))

        urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
        check("写入 retry=False：只写一次，说原因", (bool(cos_store.cos_put(cos, "state/k.json", b"{}", 8, retry=False)),
                                              len(calls)), (True, 1))

        print("\n[心跳：平时一跳只写一次（下一跳就是重试），关机那一跳在 8 秒里再写一次]")
        from ark_relay.features import phone
        from _parts import tmpdir
        hb = phone.Heartbeat("ark-test-topic", tmpdir(), post=lambda p, t: None, cos=cos)
        urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
        check("平时那一跳：断了就算这一跳没写上，只写一次", (hb.cos_beat(), len(calls)), (False, 1))
        urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
        check("关机那一跳：断了再写一次，写上了", (hb.cos_beat(bye=True), len(calls)), (True, 2))

        print("\n[终末地官方公告：网关 503 后在 8 秒里再读一次]")
        body = b'{"data": {"list": []}}'
        urllib.request.urlopen, calls = scripted([http_error(503), Resp(body)])
        check("读到了（今天没有版本更新）", (efstatus.update_hint(strict=True), len(calls)), ("", 2))
        check("第一次用 8 秒", calls[0], 8)
    finally:
        urllib.request.urlopen = REAL
        netretry._sleep = real_sleep

    print("\n[需求表建表：404 当场报，503 和断线照旧再问]")
    real_bsleep = build.time.sleep
    build.time.sleep = lambda s: None
    try:
        n = []

        def nf():
            n.append(1)
            raise http_error(404)
        try:
            build._retry(nf)
            out = None
        except urllib.error.HTTPError as exc:
            out = exc.code
        check("404：问一次就报", (out, len(n)), (404, 1))
        seq = [http_error(503), ConnectionResetError(54, "reset"), "ok"]

        def flaky():
            got = seq.pop(0)
            if isinstance(got, BaseException):
                raise got
            return got
        check("503、断线之后第三次成了", build._retry(flaky), "ok")
    finally:
        build.time.sleep = real_bsleep


def _part_tick_isolation():
    import json
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _parts import tmpdir
    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"; (AUTOMAS / "config").mkdir(parents=True)
    STATE = TMP / "state"; STATE.mkdir()
    HIST = TMP / "history"; HIST.mkdir()
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(STATE), SERVERCHAN_KEY="", ARK_LLM_KEY="")

    from ark_relay.core import engine as eng
    from ark_relay.core.config import Config
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import Notifier

    fails = []
    cfg = Config()
    E = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notifier(cfg))
    E._scripts_running = lambda: False

    class Src:
        def fetch(self, seen):
            return []
    E.source = Src()

    ran = []
    def boom(*a, **k):
        raise RuntimeError("这一段坏了")
    E._check_missed_runs = boom                      # 漏跑检查炸了
    E._maybe_interim_report = lambda *a, **k: ran.append("interim")
    E._maybe_daily_report = lambda *a, **k: ran.append("daily")
    E._maybe_shutdown = lambda *a, **k: ran.append("shutdown")

    try:
        E.tick()
    except Exception as exc:  # noqa: BLE001
        fails.append(f"tick 把一段的异常抛出来了：{exc}")
    for want in ("interim", "daily", "shutdown"):
        if want not in ran:
            fails.append(f"前面一段出错后「{want}」没跑")

    # 读记录本身炸了也一样：时钟类的段照做
    ran.clear()
    class BadSrc:
        def fetch(self, seen):
            raise OSError("history 目录读不了")
    E.source = BadSrc()
    E._check_missed_runs = lambda *a, **k: ran.append("missed")
    try:
        E.tick()
    except Exception as exc:  # noqa: BLE001
        fails.append(f"读记录失败被抛出来了：{exc}")
    if "shutdown" not in ran or "missed" not in ran:
        fails.append(f"读记录失败后其余段没跑：{ran}")

    # 从源码上钉死：五个时钟段必须在同一个逐段兜底的循环里
    src = (Path(__file__).resolve().parents[1] / "ark_relay" / "core" / "engine.py").read_text(encoding="utf-8")
    body = src[src.index("    def tick(self)"):]
    body = body[:body.index("\n    def ", 10)]
    for name in ("_check_missed_runs", "_maybe_interim_report", "_maybe_deferred_update",
                 "_maybe_daily_report", "_maybe_shutdown", "_flush_pending"):
        if f"self.{name})" not in body and f"self.{name}," not in body:
            fails.append(f"tick 里 {name} 没有走逐段兜底的循环")

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_yesterday_report_midnight_wait():
    """Cross-midnight yesterday report waits while scripts, queues, make-ups, or activity top-ups are still active."""
    import json
    import types
    from datetime import datetime

    from ark_relay.core import plan as _plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.ledger import State
    from ark_relay.features import activity, banners, makeup, report

    YDAY, TODAY = "2026-11-25", "2026-11-26"
    at_0005 = datetime(2026, 11, 26, 0, 5, tzinfo=SERVER_TZ)
    at_0900 = datetime(2026, 11, 26, 9, 0, tzinfo=SERVER_TZ)

    def make_eng():
        sd = tmpdir() / "state"
        sd.mkdir()
        st = State(sd)
        y_row = {
            "run_id": f"{YDAY}/ark/01", "script": "MAA", "user": "ark",
            "started": f"{YDAY}T21:35:00+08:00", "finished": f"{YDAY}T21:55:00+08:00",
            "ok": True, "failed_tasks": [], "raw": {},
        }
        t_row = {
            "run_id": f"{TODAY}/endfield/01", "script": "MaaEnd", "user": "endfield",
            "started": f"{TODAY}T00:01:00+08:00", "finished": f"{TODAY}T00:04:00+08:00",
            "ok": True, "failed_tasks": [], "raw": {},
        }
        st.ledger_path(YDAY).write_text(json.dumps(y_row, ensure_ascii=False) + "\n", encoding="utf-8")
        st.ledger_path(TODAY).write_text(json.dumps(t_row, ensure_ascii=False) + "\n", encoding="utf-8")
        sent: list = []
        seen_entries: list = []

        class Notes:
            def send(self, title, body, *, alert=False, daily=False):
                sent.append((title, body, daily))
                return []

        eng = types.SimpleNamespace(
            cfg=types.SimpleNamespace(
                automas_dir=None, history_dir=None, okww_dir=None, skland_token="",
                state_dir=sd, last_run_after="21:30", interim_report=False,
            ),
            state=st,
            notifier=Notes(),
            running=False,
            unfinished=[],
        )
        eng._report_cutoff = lambda now: report._report_cutoff(eng, now)
        eng._scripts_running = lambda: eng.running
        eng._unfinished_queues = lambda now, entries: (seen_entries.append([e["run_id"] for e in entries]), list(eng.unfinished))[1]
        eng._compose_daily = lambda day, entries: (f"📋 {day[5:]} · 全绿", "ok")
        eng._announce_banners = lambda now, nxt: None
        return eng, sent, seen_entries

    saved_collect, saved_sched = banners.collect, _plan.schedule
    banners.collect = lambda *a, **k: ([], {})
    _plan.schedule = lambda *a, **k: []
    try:
        # 1. Script still running past 00:00
        e, sent, seen = make_eng()
        e.running = True
        report._maybe_daily_report(e, at_0005)
        check("跨零点脚本在跑：不补发昨日日报且不落记号", (sent, e.state.report_sent(YDAY)), ([], False))

        # 2. Unfinished queue past 00:00 (and checks both today + yday ledger rows)
        e.running = False
        e.unfinished = ["队列「晚班」还差 MaaEnd"]
        report._maybe_daily_report(e, at_0005)
        check("跨零点队列未完：不补发昨日日报且不落记号", (sent, e.state.report_sent(YDAY)), ([], False))
        check("未完队列检查合并了今日与昨日账本",
              sorted(seen[-1]), sorted([f"{TODAY}/endfield/01", f"{YDAY}/ark/01"]))

        # 3. Make-up dispatched at 23:55 still in flight at 00:05
        e.unfinished = []
        makeup._write_marker(e.cfg.state_dir, YDAY, {
            "MAA": {"dispatched_at": f"{YDAY}T23:55:00+08:00", "result": makeup.DISPATCHED, "tries": 1},
        })
        report._maybe_daily_report(e, at_0005)
        check("跨零点补跑在途：不补发昨日日报且不落记号", (sent, e.state.report_sent(YDAY)), ([], False))

        # 4. Activity top-up dispatched at 23:55 (un-alarmed, within STALE) still waiting at 00:05
        makeup._write_marker(e.cfg.state_dir, YDAY, {
            "MAA": {"dispatched_at": f"{YDAY}T23:55:00+08:00", "result": makeup.OK, "tries": 1},
        })
        activity._write(e.cfg.state_dir, YDAY, {
            "booked": f"{YDAY}T09:30:00+08:00", "due": f"{YDAY}T21:30:00+08:00",
            "dispatched_at": f"{YDAY}T23:55:00+08:00", "result": "dispatched", "tries": 1,
        })
        report._maybe_daily_report(e, at_0005)
        check("跨零点活跃晚班补在途：不补发昨日日报且不落记号", (sent, e.state.report_sent(YDAY)), ([], False))

        # 5. All clear -> sends yesterday report with （补发） and marks report:yday
        activity._write(e.cfg.state_dir, YDAY, {
            "booked": f"{YDAY}T09:30:00+08:00", "due": f"{YDAY}T21:30:00+08:00",
            "dispatched_at": f"{YDAY}T23:55:00+08:00", "result": "landed", "tries": 1,
        })
        report._maybe_daily_report(e, at_0005)
        check("全部结束后补发昨日日报并落记号",
              ([t for t, _, _ in sent], e.state.report_sent(YDAY)),
              ([f"📋 {YDAY[5:]} · 全绿（补发）"], True))

        # 6. Stale 'booked' activity top-up from yesterday (evening never came) does NOT block next morning
        e2, sent2, _ = make_eng()
        activity._write(e2.cfg.state_dir, YDAY, {
            "booked": f"{YDAY}T09:30:00+08:00", "due": f"{YDAY}T21:30:00+08:00",
            "result": "booked", "tries": 0,
        })
        report._maybe_daily_report(e2, at_0900)
        check("昨日未派出的 booked 活跃补不卡住次日早间补发", e2.state.report_sent(YDAY), True)
    finally:
        banners.collect, _plan.schedule = saved_collect, saved_sched


def _part_flush_unsent_persist():
    """handle._flush_pending and handle.retry_unsent persist pending state after clearing _unsent_unresolved."""
    from ark_relay.core.config import Config
    from ark_relay.core.engine import Engine
    from ark_relay.core.ledger import State
    from ark_relay.features import handle

    sd = tmpdir()
    cfg = Config()
    cfg.state_dir = sd
    cfg.automas_dir = None

    class Notes:
        def __init__(self):
            self.broken = True
            self.sent: list = []

        def send(self, title, body, *, alert=False, daily=False):
            if self.broken:
                return ["down"]
            self.sent.append((title, body, alert))
            return []

    notes = Notes()
    e = Engine(cfg, source=None, state=State(sd), notifier=notes)
    e._scripts_running = lambda: False
    e._script_running = lambda name: False

    # Queue one unsent alert while _pending and _recovered are both empty
    errs = handle._push_now(e, "2026-11-26", "没干完", "2026-11-26/ark/r1", "⚠️ 标题", "正文")
    check("推送失败时入队并落盘",
          (bool(errs), len(e._unsent_unresolved), len(State(sd).load_pending().get("unsent", []))),
          (True, 1, 1))

    # Direct handle._flush_pending(e) clears _unsent_unresolved AND cleans persisted pending even when _pending/_recovered empty
    notes.broken = False
    handle._flush_pending(e)
    on_disk = State(sd).load_pending()
    check("直调 handle._flush_pending 清空内存并清理盘上待重发队列",
          (e._unsent_unresolved, on_disk.get("unsent")), ([], []))
    e_re = Engine(cfg, source=None, state=State(sd), notifier=notes)
    check("重启后不再读回已送达的 unsent 残留", e_re._unsent_unresolved, [])

    # Partial success in direct handle.retry_unsent: item 1 sent, item 2 fails -> persists only item 2
    notes.broken = True
    handle._push_now(e, "2026-11-26", "没干完", "2026-11-26/ark/r2", "⚠️ 第二条", "正文2")
    handle._push_now(e, "2026-11-26", "没干完", "2026-11-26/ark/r3", "⚠️ 第三条", "正文3")

    def fail_third(title, body, *, alert=False, daily=False):
        if "第三条" in title:
            return ["still down"]
        notes.sent.append((title, body, alert))
        return []

    notes.send = fail_third
    handle.retry_unsent(e)
    on_disk2 = State(sd).load_pending()
    check("部分送达时仅保留未送达项并同步落盘",
          ([x[2] for x in e._unsent_unresolved], [x[2] for x in on_disk2.get("unsent", [])]),
          (["2026-11-26/ark/r3"], ["2026-11-26/ark/r3"]))


if __name__ == "__main__":
    sys.exit(run_parts([_part_texts_gate_main, _part_texts_wording, _part_texts_structured_faults, _part_texts_plain_strict, _part_user_switches, _part_mute_verdicts, _part_daily_format, _part_daily_partial_failure, _part_daily_range_prefix, _part_daily_techlog, _part_no_model_daily_report, _part_report_due, _part_llm_breaker, _part_scoreboard_main, _part_scoreboard_log_time, _part_scoreboard_test_window, _part_ledger_bad_times, _part_ledger_guard, _part_ledger_incomplete, _part_ledger_once_per_run, _part_ledger_rewrite_race, _part_ledger_scoreboard_started, _part_ledger_truth, _part_relay_log_rotation, _part_relay_poweroff_live, _part_record_names, _part_config_no_bot, _part_config_skip, _part_config_warn_once, _part_config_writers, _part_dotenv_hash, _part_engine_pending, _part_loop_parts, _part_netretry, _part_tick_isolation, _part_yesterday_report_midnight_wait, _part_flush_unsent_persist]))
