"""仓内确定性铁律工程门禁（自动纳入 scripts/ci/relay-tests.sh）。

覆盖五大核心红线，且支持通过环境变量在隔离沙箱里做投毒突变验证：
- ARK_IRON_GATE_ROOT  ：覆写本次扫描与验证的仓库根目录（用于单仓投毒测试）
- ARK_IRON_GATE_REPOS ：覆写 G6 跨仓禁加密扫描目录（按 os.pathsep 分隔，缺路径直接报错）

门禁清单：
- G1 (D-1010 关机红线)：AST + 行为实测，严禁引入键鼠空闲检测（GetLastInputInfo/human_idle/user_idle/user32），
  验证排班跑完照常软关机，且系统事件 1075 取消时仅进群报一句。
- G2 (日报绝对白名单与禁压错红线)：AST 全量封禁 errwatch.recovered / RECOVERED / _note_recovered / _recovered 旁路
  与 texts.py 盲盒翻译；正向校验 report.py 白名单 Schema 硬拒绝非白名单区块；负向注入卡池崩/采集失败/补跑失败/
  关卡拦截/瞬态耗尽/账本失败未完未核 6 类异常，验证日报标题与正文 0 字节报错文案且报错通道 100% 收到推送；
  同步验证 notify.py 写盘异常 fail-closed 留机锁与 texts.py 结构化中文错因输出。
- G3-Boot (开机去海外依赖)：开机探网路径零海外 GitHub 探针，行为实测仅轮询国内 COS/官服域名。
- G4 (零硬编码最新版工具闸门)：全仓零 PowerShell 5.1 / 零 wmic / 零 /usr/bin/python3 / 零 PY314 / 零 Python314
  / 零静态版本 floor / 零裸 python3，并在 macOS 动态校验 called_ver == max_installed_ver。
- G5 (分层北京时间断电硬锁)：全 16 入口覆盖检查 + 7 个边界时刻（08:21/08:25/08:39/08:40/08:45/08:46/08:47）
  对公共库与真实代表入口的行为实测（第 1 层不误杀 08:25 只读探活，第 2 层严锁 08:22–08:46）。
- G6 (D213 私有工具禁加密)：跨 3 私有仓（maa-automation / ark-remote / transit-app）零 Keystore/Tink/AEAD/Fernet。
"""
from __future__ import annotations

# ruff: noqa: PLC0415
import ast
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, require, run_parts, tmpdir

_REAL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REAL_ROOT / "relay"))


def _gate_root() -> Path:
    """返回本次门禁待检仓库根目录（优先读取沙箱覆写变量 ARK_IRON_GATE_ROOT）。"""
    override = os.environ.get("ARK_IRON_GATE_ROOT", "").strip()
    return Path(override).resolve() if override else _REAL_ROOT


def _docstring_ids(tree: ast.AST) -> set[int]:
    """收集 AST 中所有文档字符串节点 id，避免说明文字误报。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                ids.add(id(first.value))
    return ids


def _load_module_from(name: str, path: Path):
    """从指定路径动态加载 Python 模块，避免受 sys.modules 缓存干扰。"""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# G1: D-1010 关机红线（AST 严禁键鼠空闲检测 + 行为实测）
# ---------------------------------------------------------------------------

_G1_FORBIDDEN_IDLE_RE = re.compile(
    r"(?i)\b(GetLastInputInfo|LASTINPUTINFO|human_idle|user_idle|idle_seconds|check_idle|last_input_tick|get_idle_time)\b"
)


def _part_g1_d1010_shutdown():
    """G1：核验中继关机链路零键鼠空闲检测，并实测正常软关机与 1075 取消汇报行为。"""
    root = _gate_root()
    ark_dir = root / "relay" / "ark_relay"
    require("G1: relay/ark_relay 目录存在", ark_dir.is_dir(), str(ark_dir))

    # 1. 全量 AST 扫描 relay/ark_relay/ 严禁任何键鼠空闲检测符号或字符串，
    #    同时在 shutdown.py 内严禁调用 user32（仅允许 kernel32.GetTickCount64 读开机时长）。
    idle_hits: list[str] = []
    shutdown_user32_hits: list[str] = []
    for py_file in sorted(ark_dir.rglob("*.py")):
        rel = py_file.relative_to(root).as_posix()
        src = py_file.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src, filename=str(py_file))
        except SyntaxError as exc:
            idle_hits.append(f"{rel}: SyntaxError({exc})")
            continue
        doc_ids = _docstring_ids(tree)
        is_shutdown = py_file.name == "shutdown.py"
        for node in ast.walk(tree):
            tokens: list[tuple[int, str]] = []
            if isinstance(node, ast.Name):
                tokens.append((getattr(node, "lineno", 0), node.id))
            elif isinstance(node, ast.Attribute):
                tokens.append((getattr(node, "lineno", 0), node.attr))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                tokens.append((node.lineno, node.name))
            elif isinstance(node, ast.arg):
                tokens.append((getattr(node, "lineno", 0), node.arg))
            elif isinstance(node, ast.alias):
                tokens.append((getattr(node, "lineno", 0), node.name))
                if node.asname:
                    tokens.append((getattr(node, "lineno", 0), node.asname))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
                tokens.append((getattr(node, "lineno", 0), node.value))
            for ln, text in tokens:
                if _G1_FORBIDDEN_IDLE_RE.search(text):
                    idle_hits.append(f"{rel}:{ln}: {text[:80]}")
                if is_shutdown and re.search(r"(?i)\buser32\b", text):
                    shutdown_user32_hits.append(f"{rel}:{ln}: {text[:80]}")

    check("G1 AST: relay/ark_relay 零键鼠空闲检测符号", idle_hits, [])
    check("G1 AST: shutdown.py 零 user32 调用", shutdown_user32_hits, [])

    # 2. 行为实测：使用沙箱目录构造排班跑完的场景，验证 shutdown.decide 无条件判定 go，
    #    以及 1075 取消关机时仅生成一句简洁群通知（不含“去群里发消息取消关机”误导文案）。
    relay_str = str(root / "relay")
    if relay_str not in sys.path:
        sys.path.insert(0, relay_str)
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import Config, SERVER_TZ
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import Notifier
    from ark_relay.features import shutdown as sd

    tmp = tmpdir("iron-g1-")
    automas = tmp / "AUTO-MAS"
    (automas / "config").mkdir(parents=True)
    state_dir = tmp / "state"
    state_dir.mkdir()
    hist_dir = tmp / "history"
    hist_dir.mkdir()

    (automas / "config" / "QueueConfig.json").write_text(json.dumps({
        "instances": [{"uid": "q1"}],
        "q1": {
            "Info": {"Name": "Evening-MAA", "TimeEnabled": True, "AfterAccomplish": "NoAction"},
            "SubConfigsInfo": {
                "TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "21:30"}}},
                "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}},
            },
        },
    }), encoding="utf-8")
    (automas / "config" / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "s1"}],
        "s1": {
            "Info": {"Name": "arknights", "Path": r"D:\MAA"},
            "SubConfigsInfo": {"UserData": {"u1": {"Info": {"Name": "arknights", "Stage": "1-7"}, "Task": {}}}},
        },
    }), encoding="utf-8")

    os.environ.update(
        ARK_HISTORY_DIR=str(hist_dir),
        ARK_AUTOMAS_DIR=str(automas),
        ARK_STATE_DIR=str(state_dir),
        ARK_SHUTDOWN_AFTER_RUN="1",
        ARK_SHUTDOWN_MIN_UPTIME="600",
        SERVERCHAN_KEY="",
        ARK_LLM_KEY="",
    )
    cfg = Config()
    e = eng_mod.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notifier(cfg))
    e._scripts_running = lambda: False
    e.state.report_sent = lambda _d: True

    def at(hh: int, mm: int) -> datetime:
        return datetime(2026, 11, 28, hh, mm, tzinfo=SERVER_TZ)

    e._boot_time = lambda _now: at(21, 20)
    e._handled_any = True
    e._started_at = at(21, 20)
    (state_dir / "ledger-2026-11-28.jsonl").write_text(
        json.dumps({"script": "MAA", "started": at(21, 31).isoformat(), "finished": at(22, 5).isoformat(),
                    "ok": True, "run_id": "g1-ok"}) + "\n",
        encoding="utf-8",
    )
    verdict = sd.decide(e, at(22, 15))
    check("G1 行为: 晚班跑完无条件放行软关机 go", (verdict.go, verdict.code), (True, "go"))

    # 核验事件 1075 取消关机：仅报一句、非 go、不含错误指引
    cancel_v = sd._cancel_verdict(at(22, 15), at(22, 16))
    check("G1 行为: 1075 取消判定为 cancelled", (cancel_v.go, cancel_v.code), (False, "cancelled"))
    check("G1 行为: 1075 群报文案简洁且无误导",
          cancel_v.say.startswith("关机被取消") and ("\n" not in cancel_v.say) and ("发消息" not in cancel_v.say),
          True)


# ---------------------------------------------------------------------------
# G2: 日报绝对白名单 + 全仓禁压错（清零 recovered / _recovered）+ 去盲盒 + 留机锁加固
# ---------------------------------------------------------------------------

_G2_FORBIDDEN_DAILY_WORDS = (
    "失败", "没读到", "没干完", "没跑成", "没证据", "没走通", "没能开跑",
    "还是没成", "自己好了", "只进日报", "扣下", "未能读取", "没按你的设置跑",
    "重试", "不算失败", "报错", "异常", "待核", "❌", "⚠️", "↪️", "↻",
)
_G2_BLIND_BOX_TOKENS = ("这种报错中继还不认识", "原话有术语", "自己好了，只进日报", "只进日报")


def _g2_ast_scan(root: Path) -> dict[str, list[str]]:
    """全仓 AST 扫描 relay/（不含 tests/），封禁 errwatch.recovered / RECOVERED / _note_recovered / _recovered 与盲盒文案。"""
    relay_dir = root / "relay"
    skip_dirs = {"tests", "fixtures", "__pycache__", "okww_files"}
    hits: dict[str, list[str]] = {
        "recovered_call": [],
        "ark_recovered_const": [],
        "note_recovered": [],
        "eng_recovered": [],
        "errwatch_symbols": [],
        "blind_box_texts": [],
    }
    for cur_dir, dirs, files in os.walk(relay_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".venv")]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            py_file = Path(cur_dir) / fn
            rel = py_file.relative_to(root).as_posix()
            src = py_file.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(src, filename=str(py_file))
            except SyntaxError as exc:
                hits["recovered_call"].append(f"{rel}: SyntaxError({exc})")
                continue
            doc_ids = _docstring_ids(tree)
            is_errwatch = py_file.name == "errwatch.py"
            is_texts = py_file.name == "texts.py"
            _g2_walk_ast(rel, tree, doc_ids, is_errwatch, is_texts, hits)
    return hits


def _g2_walk_ast(rel: str, tree: ast.AST, doc_ids: set[int], is_errwatch: bool,
                 is_texts: bool, hits: dict[str, list[str]]) -> None:
    """检查单个 Python 文件的 AST 节点是否残留违禁压错或盲盒符号。"""
    for node in ast.walk(tree):
        ln = getattr(node, "lineno", 0)
        if isinstance(node, ast.Attribute):
            if node.attr == "recovered":
                hits["recovered_call"].append(f"{rel}:{ln}: .{node.attr}")
            elif node.attr == "_note_recovered":
                hits["note_recovered"].append(f"{rel}:{ln}: .{node.attr}")
            elif node.attr == "_recovered":
                hits["eng_recovered"].append(f"{rel}:{ln}: .{node.attr}")
            elif node.attr == "RECOVERED":
                hits["errwatch_symbols"].append(f"{rel}:{ln}: .{node.attr}")
        elif isinstance(node, ast.Name):
            if node.id == "_note_recovered":
                hits["note_recovered"].append(f"{rel}:{ln}: {node.id}")
            elif node.id == "_recovered":
                hits["eng_recovered"].append(f"{rel}:{ln}: {node.id}")
            elif is_errwatch and node.id in ("RECOVERED", "recovered"):
                hits["errwatch_symbols"].append(f"{rel}:{ln}: {node.id}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "_note_recovered":
                hits["note_recovered"].append(f"{rel}:{ln}: def {node.name}")
            elif is_errwatch and node.name == "recovered":
                hits["errwatch_symbols"].append(f"{rel}:{ln}: def {node.name}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
            if "ark_recovered" in node.value:
                hits["ark_recovered_const"].append(f"{rel}:{ln}: {node.value[:60]}")
            if is_texts and any(tok in node.value for tok in _G2_BLIND_BOX_TOKENS):
                hits["blind_box_texts"].append(f"{rel}:{ln}: {node.value[:60]}")


def _g2_schema_and_negative_behavior(root: Path) -> None:
    """G2 正向白名单 Schema 校验 + 5 类真实异常注入（卡池崩/采集失败/补跑失败/关卡拦截/瞬态耗尽+账本失败）。"""
    import logging

    relay_str = str(root / "relay")
    if relay_str not in sys.path:
        sys.path.insert(0, relay_str)

    from ark_relay.core import notify
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.ledger import State
    from ark_relay.features import banners, errwatch, maintenance, makeup, report, stagegate

    # 1. 正向白名单 Schema 门禁：注册表非空，合法区块放行，非白名单区块硬抛出 ValueError
    check("G2 Schema: DAILY_WHITELIST_SECTIONS 非空", len(report.DAILY_WHITELIST_SECTIONS) >= 5, True)
    ok_title, ok_render = report.render_daily_whitelisted("📋 11-28 · 全绿 ✅", [
        ("runs", "✅ 明日方舟　09:00→09:10　10m　东京 10:00→10:10"),
        ("tomorrow_plan", "明天 09:00 自动执行"),
    ])
    check("G2 Schema: 白名单区块正常渲染",
          ("全绿 ✅" in ok_title and "✅ 明日方舟" in ok_render and "明天 09:00" in ok_render), True)
    rejected: list[str] = []
    for bad_key in ("errors", "self_heal", "makeup_failed", "collect_retry", "stagegate"):
        try:
            report.render_daily_whitelisted("📋 11-28 · 今日日报", [(bad_key, "异常内容")])
        except ValueError:
            rejected.append(bad_key)
    check("G2 Schema: 非白名单区块全部被硬拒绝", rejected,
          ["errors", "self_heal", "makeup_failed", "collect_retry", "stagegate"])

    # 2. 负向行为门禁：在隔离目录同时注入 5 类异常 + 账本失败/未完/未核实/未读理智
    day = "2026-11-28"
    tmp = tmpdir("iron-g2-")
    sd = tmp / "state"
    sd.mkdir()
    (sd / "collect-retry").mkdir()
    (sd / "collect-retry" / f"{day}.json").write_text(json.dumps({
        "run_id": f"{day}/endfield/c1", "routes": ["AutoCollectRoute16"],
        "passed": [], "failed": ["AutoCollectRoute16"], "unknown": ["AutoCollectRoute17"],
        "recurrent": ["AutoCollectRoute16"], "blocked_again": True, "note": "还是没通",
    }, ensure_ascii=False), encoding="utf-8")
    makeup._write_marker(sd, day, {
        "MAA": {"result": makeup.FAILED, "run_id": f"{day}/ark/f1", "note": "还是没成"},
        "MaaEnd": {"result": makeup.NO_RECORD, "run_id": f"{day}/endfield/f2", "note": "超时"},
    })
    stagegate._note_due(sd, datetime(2026, 11, 28, 9, 0, tzinfo=SERVER_TZ), "早班", {
        "verdict": stagegate.NO, "pulled": True, "stage": "YW-4", "why": "还没开到这关", "others": [],
    })

    check("G2 负向: retry_line / makeup_line / stagegate.report_line 全部返回空串",
          (report.retry_line(sd, day), report.makeup_line(sd, day), stagegate.report_line(sd, day)),
          ("", "", ""))

    # 构造带真实 errwatch 捕手的日志监听，核验报错 100% 落入企微告警通道
    class _AlertSpy(errwatch.ErrorKindAlert):
        def __init__(self):
            super().__init__(types.SimpleNamespace(send=lambda *a, **k: []), state_dir=tmp / "ew")
            self.captured: list[tuple[str, str]] = []

        def _take(self, record):
            self.captured.append((record.name, record.getMessage()))

    spy = _AlertSpy()
    ark_root = "ark"
    ark_logger = logging.getLogger(ark_root)
    ark_logger.addHandler(spy)

    # 构造带正常成功趟 + 失败趟 + incomplete + 未核实 + 未读理智的混合当日账本
    entries = [
        {"run_id": f"{day}/ark/ok1", "script": "MAA", "user": "arknights", "ok": True,
         "started": f"{day}T09:00:00+08:00", "finished": f"{day}T09:12:00+08:00",
         "failed_tasks": [], "raw": {"stages": ["1-7"], "run_times": 5, "sanity_spent": 60, "sanity": 10}},
        {"run_id": f"{day}/ark/fail1", "script": "MAA", "user": "arknights", "ok": False,
         "started": f"{day}T09:15:00+08:00", "finished": f"{day}T09:17:00+08:00",
         "failed_tasks": ["基建换班"], "raw": {}},
        {"run_id": f"{day}/endfield/ok2", "script": "MaaEnd", "user": "endfield", "ok": True,
         "started": f"{day}T09:20:00+08:00", "finished": f"{day}T09:45:00+08:00",
         "failed_tasks": [], "incomplete": "MaaEnd 这一轮有 1 项没干成：自动采集没走路线",
         "raw": {"tasks_done": ["赠送干员礼物", "装备制造", "自动采集"],
                 "tasks_evidence": {"赠送干员礼物": "获得 信用 ×400"},
                 "tasks_trail": {"装备制造": {"found": False, "unread": True}},
                 "maaend_farm": "基质刷取", "maaend_farm_runs": 2, "maaend_sanity_unfit": "没对上"}},
        {"run_id": f"{day}/wuwa/upd1", "script": "OK-WW", "user": "wuwa", "ok": False, "transitional": True,
         "started": f"{day}T09:50:00+08:00", "finished": f"{day}T09:51:00+08:00",
         "failed_tasks": [], "raw": {"okww_restart_dialog": True}},
    ]

    eng = types.SimpleNamespace(
        cfg=types.SimpleNamespace(automas_dir=None, history_dir=None, maaend_dir=None,
                                  skland_token="", state_dir=sd),
        state=State(sd),
        _announce_banners=lambda *a, **k: None,
    )

    real_plan = report.plan
    real_banners = report.banners
    real_sleep = notify._sleep
    real_urlopen = maintenance.urllib.request.urlopen
    try:
        # 注入 1a: 卡池 collect 整体崩溃
        report.plan = types.SimpleNamespace(
            schedule=lambda _d: [{"name": "早班", "times": ["09:00"]}],
            next_plan=lambda _d: "明天 09:00 早班",
            activity_countdown=lambda _d: "",
        )
        report.banners = types.SimpleNamespace(
            collect=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("卡池源连接超时")),
            image_reader=lambda _sd: None,
            render=lambda *a, **k: "",
            Trace=types.SimpleNamespace(new=lambda: None),
            save_trace=lambda *a, **k: None,
            update_history=lambda *a, **k: [],
        )
        title_crash, body_crash = report._compose_daily(eng, day, entries)
        bad_hits_crash = [w for w in _G2_FORBIDDEN_DAILY_WORDS if w in (title_crash + body_crash)]
        check("G2 负向(卡池崩+5类异常): 日报标题与正文 0 字节报错/失败/自愈/没读到词", bad_hits_crash, [])
        check("G2 负向(卡池崩+5类异常): 日报仍保留正常白名单产出与中性标题",
              ("今日日报" in title_crash, "全绿" in title_crash,
               "✅ 明日方舟" in body_crash, "✅ 终末地" in body_crash, "明天 09:00 早班" in body_crash),
              (True, False, True, True, True))

        # 注入 1b: 单游戏卡池拉取失败 + render 仅出白名单正常行
        pool_partial = banners.render(
            [banners.Banner("终末地", "常驻寻访", ("管理员",),
                            datetime(2026, 11, 20, 4, 0), datetime(2026, 12, 10, 4, 0))],
            datetime(2026, 11, 28, 22, 0), {},
            notes={"鸣潮": "时间见官方活动日历"}, failed=["明日方舟", "鸣潮"],
        )
        check("G2 负向(单游戏卡池失败): banners.render 仅出正常行，0 失败/取不到词",
              ("常驻寻访" in pool_partial, any(w in pool_partial for w in ("失败", "取不到", "未能读取", "读不到"))),
              (True, False))

        # 注入 5: 瞬态重试耗尽（maintenance._get 连续超时耗尽重试）-> 中间重试仅 INFO，耗尽后由 today() 记 WARNING 直达企微群
        notify._sleep = lambda _s: None
        real_msleep = maintenance._sleep
        maintenance._sleep = lambda _s: None
        tries = []

        def _timeout_open(*_a, **_k):
            tries.append(1)
            raise TimeoutError("timed out")

        maintenance.urllib.request.urlopen = _timeout_open
        failed_maint: list[str] = []
        try:
            got_m = maintenance.today(
                now=datetime(2026, 11, 28, 9, 0, tzinfo=SERVER_TZ),
                sources={"明日方舟": lambda _n: maintenance._get("https://ak.invalid/bulletin")},
                failed=failed_maint,
            )
        finally:
            maintenance._sleep = real_msleep
        check("G2 负向(瞬态耗尽): 重试耗尽后返回空并记入 failed，不抛异常",
              (got_m, failed_maint, len(tries)), ({}, ["明日方舟"], maintenance.GET_ATTEMPTS))
    finally:
        ark_logger.removeHandler(spy)
        report.plan = real_plan
        report.banners = real_banners
        notify._sleep = real_sleep
        maintenance.urllib.request.urlopen = real_urlopen

    # 校验报错通道 100% 收到卡池崩、未读/未核实/待核告警与瞬态耗尽告警
    msgs = "\n".join(m for _, m in spy.captured)
    check("G2 告警通道收到卡池崩溃 WARNING", "卡池那一段整体失败" in msgs, True)
    check("G2 告警通道收到终末地未核实/未读理智 WARNING",
          ("没读到游戏内完成证据" in msgs and "理智" in msgs), True)
    check("G2 告警通道收到瞬态耗尽 WARNING",
          any("维护公告：明日方舟 官方公告取不到" in m for _, m in spy.captured), True)


def _g2_hardening_checks(root: Path) -> None:
    """G2 配套加固校验：texts.py 结构化人话错因（去盲盒）+ notify.py 写盘异常 fail-closed 留机锁。"""
    import logging

    relay_str = str(root / "relay")
    if relay_str not in sys.path:
        sys.path.insert(0, relay_str)

    from ark_relay.core import engine as eng_mod, notify, texts
    from ark_relay.core.config import Config, SERVER_TZ
    from ark_relay.core.ledger import State
    from ark_relay.features import modes, shutdown as sd

    # 1. texts.py 去盲盒：结构化中文原因 + 关键上下文 + 0 盲盒话术
    check("G2 去盲盒: RELAY_ERROR_UNREAD 已删除", hasattr(texts, "RELAY_ERROR_UNREAD"), False)
    r_http = texts.relay_error_body("ark.banners", "公告拉取失败 ｜ HTTP Error 503: Service Unavailable", "09:05:00")
    r_key = texts.relay_error_body("ark.service", "Traceback: KeyError 'stage'", "09:06:00")
    r_file = texts.relay_error_body("ark.config", "FileNotFoundError: [Errno 2] 'QueueConfig.json'", "09:07:00")
    check("G2 去盲盒: HTTP 503 输出状态码且无英文/盲盒",
          ("状态码 503" in r_http, texts.plain(r_http), "这种报错中继还不认识" in r_http), (True, [], False))
    check("G2 去盲盒: KeyError 输出直白原因且无盲盒",
          ("读取数据时缺少必要内容" in r_key, texts.plain(r_key), "这种报错中继还不认识" in r_key), (True, [], False))
    check("G2 去盲盒: FileNotFoundError 输出原因并保留文件名",
          ("找不到要用的文件" in r_file, "QueueConfig.json" in r_file, texts.plain(r_file)), (True, True, []))

    # 2. notify.py alarm_hold 落盘异常 fail-closed：必记 ERROR + 置内存级留机锁 + 阻止自动关机
    tmp = tmpdir("iron-g2-hold-")
    state_dir = tmp / "state"
    state_dir.mkdir()
    automas = tmp / "AUTO-MAS"
    (automas / "config").mkdir(parents=True)
    (automas / "config" / "QueueConfig.json").write_text(json.dumps({
        "instances": [{"uid": "q1"}],
        "q1": {
            "Info": {"Name": "Evening-MAA", "TimeEnabled": True, "AfterAccomplish": "NoAction"},
            "SubConfigsInfo": {
                "TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "21:30"}}},
                "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}},
            },
        },
    }), encoding="utf-8")
    (automas / "config" / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "s1"}],
        "s1": {
            "Info": {"Name": "arknights", "Path": r"D:\MAA"},
            "SubConfigsInfo": {"UserData": {"u1": {"Info": {"Name": "arknights"}, "Task": {}}}},
        },
    }), encoding="utf-8")

    err_lines: list[str] = []

    class _ErrCap(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                err_lines.append(record.getMessage())

    cap = _ErrCap()
    notify.log.addHandler(cap)
    orig_write = modes.set_alarm_hold
    orig_blackout = modes.in_preboot_blackout
    try:
        modes.set_alarm_hold = lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("disk readonly"))
        modes.in_preboot_blackout = lambda *_a, **_k: False
        n = notify.Notifier(types.SimpleNamespace(
            wecom_bot_url="", wecom_corpid="", wecom_secret="", wecom_agentid=0, wecom_touser="",
            serverchan_key="", state_dir=state_dir,
        ))
        n.note_alarm("模拟报警标题")
        check("G2 fail-closed: alarm_hold 落盘失败记录了 ERROR 日志",
              any("故障留机锁写盘失败" in m for m in err_lines), True)
        mem_info = modes.alarm_hold_info(state_dir)
        check("G2 fail-closed: 内存级留机锁已生效且保留原因与 memory_only 标记",
              (bool(mem_info), (mem_info or {}).get("reason"), (mem_info or {}).get("memory_only")),
              (True, "模拟报警标题", True))

        # 实测 shutdown.decide 在班次时间内必须因内存级留机锁拒绝自动关机（固定 21:35 触发 -> 22:15 判定，避免受真实钟点影响）
        at = lambda hh, mm: datetime(2026, 11, 28, hh, mm, tzinfo=SERVER_TZ)  # noqa: E731
        modes.set_memory_alarm_hold(state_dir, "模拟报警标题", now=at(21, 35))
        os.environ.update(
            ARK_HISTORY_DIR=str(tmp / "history"), ARK_AUTOMAS_DIR=str(automas),
            ARK_STATE_DIR=str(state_dir), ARK_SHUTDOWN_AFTER_RUN="1",
            ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="",
        )
        (tmp / "history").mkdir()
        cfg = Config()
        e = eng_mod.Engine(cfg, source=None, state=State(state_dir), notifier=notify.Notifier(cfg))
        e._scripts_running = lambda: False
        e.state.report_sent = lambda _d: True
        e._boot_time = lambda _now: at(21, 20)
        e._handled_any = True
        e._started_at = at(21, 20)
        (state_dir / "ledger-2026-11-28.jsonl").write_text(
            json.dumps({"script": "MAA", "started": at(21, 31).isoformat(),
                        "finished": at(22, 5).isoformat(), "ok": True, "run_id": "g2-ok"}) + "\n",
            encoding="utf-8",
        )
        verdict = sd.decide(e, at(22, 15))
        check("G2 fail-closed: 内存留机锁成功阻止自动关机", (verdict.go, verdict.code), (False, "alarm-hold"))
    finally:
        modes.set_alarm_hold = orig_write
        modes.in_preboot_blackout = orig_blackout
        notify.log.removeHandler(cap)
        modes.clear_memory_alarm_hold(state_dir)


def _part_g2_daily_whitelist_and_no_mute():
    """G2：核验日报绝对白名单、全仓零 recovered/_recovered 压错旁路、去盲盒翻译与 fail-closed 留机锁。"""
    root = _gate_root()
    hits = _g2_ast_scan(root)
    check("G2 AST: 全 relay/ 零 errwatch.recovered 调用", hits["recovered_call"], [])
    check("G2 AST: 全 relay/ 零 ark_recovered 常量", hits["ark_recovered_const"], [])
    check("G2 AST: 全 relay/ 零 _note_recovered 符号", hits["note_recovered"], [])
    check("G2 AST: 全 relay/ 零 eng._recovered 旁路", hits["eng_recovered"], [])
    check("G2 AST: errwatch.py 零 RECOVERED/recovered 定义", hits["errwatch_symbols"], [])
    check("G2 AST: texts.py 零盲盒/只进日报文案", hits["blind_box_texts"], [])

    _g2_schema_and_negative_behavior(root)
    _g2_hardening_checks(root)


# ---------------------------------------------------------------------------
# G3-Boot: 开机网络探针去海外 GitHub 依赖
# ---------------------------------------------------------------------------

def _part_g3_boot_no_github():
    """G3-Boot：核验开机路径零 raw.githubusercontent.com 且仅探测国内域名。"""
    root = _gate_root()
    boot_files = (root / "relay" / "service.py", root / "relay" / "boot_stages.py")
    raw_hits: list[str] = []
    for fp in boot_files:
        require(f"G3-Boot: {fp.name} 存在", fp.is_file(), str(fp))
        txt = fp.read_text(encoding="utf-8", errors="replace")
        for idx, ln in enumerate(txt.splitlines(), 1):
            if "raw.githubusercontent.com" in ln.lower():
                raw_hits.append(f"{fp.relative_to(root).as_posix()}:{idx}: {ln.strip()[:80]}")
    check("G3-Boot: service.py 与 boot_stages.py 零 raw.githubusercontent.com", raw_hits, [])

    # 行为实测：按函数切片执行 _wait_for_network，核验实际探测到的域名全为国内域名
    svc_src = (root / "relay" / "service.py").read_text(encoding="utf-8")
    fn_src = svc_src[svc_src.index("def _wait_for_network"):svc_src.index("class ArkRelayService")]
    probed: list[str] = []

    class _FakeSocket:
        @staticmethod
        def getaddrinfo(host, port):
            probed.append(str(host))
            if len(probed) < 2:
                raise OSError("dns busy")
            return [(2, 1, 6, "", ("1.2.3.4", port))]

    class _FakeLog:
        def info(self, *_a, **_kw):
            pass

        def warning(self, *_a, **_kw):
            pass

    now = [0.0]

    class _FakeTime:
        @staticmethod
        def monotonic():
            return now[0]

        @staticmethod
        def sleep(sec):
            now[0] += float(sec)

    ns = {"time": _FakeTime, "boot_stages": types.SimpleNamespace(_stop_requested=lambda: False)}
    exec(fn_src, ns)
    orig_sock = sys.modules.get("socket")
    sys.modules["socket"] = _FakeSocket  # type: ignore[assignment]
    try:
        ok = ns["_wait_for_network"](_FakeLog(), timeout=30.0)
    finally:
        if orig_sock is not None:
            sys.modules["socket"] = orig_sock
    check("G3-Boot 行为: 国内探针二次重试就绪", ok, True)
    check("G3-Boot 行为: 实际探测了 >= 2 个国内域名", len(probed) >= 2, True)
    check("G3-Boot 行为: 所有探针域名不含 github",
          all("github" not in h.lower() for h in probed), True)


# ---------------------------------------------------------------------------
# G4: 零硬编码最新版工具闸门（全仓扫描 + macOS 动态版本比对）
# ---------------------------------------------------------------------------

_G4_PS51_RE = re.compile(
    r"(?i)(powershell\.exe|WindowsPowerShell\\v1\.0|else\s*\(\s*powershell\b)"
)
_G4_WMIC_RE = re.compile(r"(?i)\bwmic(?:\.exe)?\b")
_G4_USR_BIN_PY_RE = re.compile(r"/usr/bin/python3\b")
_G4_VER_ID_RE = re.compile(r"\b(?:RELAY_)?PY3\d\d\b|Program Files\\+Python3\d\d\b")
# 覆盖引号外/内通配符（"Python 3.16."* 与 "Python 3.16.*"）、单项或多项 case、以及 Python 静态版本下限判断
_G4_STATIC_FLOOR_RE = re.compile(
    r"""(?:["']Python\s+3\.\d+\.?["']\*|["']Python\s+3\.\d+\.\*["']|\bPython\\?\s+3\.\d+\.\*|\bsys\.version_info\s*(?:>=|<=|<|>|==|!=)\s*\(\s*3\s*,\s*\d+|\.startswith\(\s*\(?["']Python\s+3\.\d+)"""
)
_G4_BARE_PY3_RE = re.compile(r"(?:^|[;&|(\s`=])python3(?:\s|$)")

# 按（相对路径 -> 行特征子串元组）精准豁免守卫脚本自身的规则定义/提示行，绝不做整文件豁免
_G4_DETECTOR_LINE_MARKERS: dict[str, tuple[str, ...]] = {
    "scripts/mac/lint-repo.sh": (
        'echo "▶ 2/17 ',
        'ok "全仓 0 处 ',
        "re.compile(",
        '", "wmic调用",',
        '", "系统旧版Python",',
    ),
    "scripts/mac/lib/shutdown_guard.py": (
        r"\bwmic(?:\.exe)?\b[^\r\n]*\bcall\s+(?:shutdown|reboot|Win32Shutdown)",
        r"(?:shutdown|logoff|cmd|pwsh|powershell|wmic|rundll32)(?:\.exe)?$",
    ),
    "scripts/mac/winps.sh": (
        r"grep -qE '\bssh\b|\bwmic\b'",
        'echo "winps: 脚本里出现了 ssh 或 wmic',
        'echo "       PowerShell 侧请用 Get-CimInstance 取代 wmic',
    ),
}


def _strip_shell_quotes(line: str) -> str:
    """移除单双引号字面量，仅保留脚本命令骨架用于检测裸 python3。"""
    s = re.sub(r"'[^']*'", "''", line)
    return re.sub(r'"[^"]*"', '""', s)


def _g4_is_detector_line(rel: str, st: str) -> bool:
    """按行特征表精准判断该行是否属于守卫自身的规则定义/提示行，严禁整文件放行。"""
    markers = _G4_DETECTOR_LINE_MARKERS.get(rel)
    if markers and any(m in st for m in markers):
        return True
    if rel == "relay/ark_relay/features/automas_keeper.py":
        return "powershell" in st.lower() and "process" in st.lower()
    return rel == "packaging/build.py" and "PY_VERSION" in st


def _g4_scan_repo(root: Path) -> dict[str, list[str]]:
    """全仓扫描 relay/ packaging/ scripts/ 违禁旧工具、静态版本 floor、硬编码版本号与裸 python3。"""
    skip_dirs = {"__pycache__", ".git", "fixtures", "tests", ".venv-relaytest"}
    code_exts = {".py", ".sh", ".ps1", ".cmd", ".bat", ".plist"}
    res: dict[str, list[str]] = {
        "ps51": [], "wmic": [], "usr_py": [], "ver_id": [],
        "static_floor": [], "bare_py": [], "env_shebang": [],
    }
    for base in (root / "relay", root / "packaging", root / "scripts"):
        if not base.exists():
            continue
        for cur_dir, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".venv")]
            for fn in sorted(files):
                p = Path(cur_dir) / fn
                if p.suffix not in code_exts:
                    continue
                rel = p.relative_to(root).as_posix()
                text = p.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                if rel.startswith("scripts/mac/") and p.suffix == ".py" and lines:
                    if lines[0].strip() == "#!/usr/bin/env python3":
                        res["env_shebang"].append(f"{rel}:1: {lines[0]}")
                _g4_scan_file_lines(rel, p.suffix, text, lines, res)
    return res


def _g4_scan_file_lines(rel: str, suffix: str, text: str, lines: list[str], res: dict[str, list[str]]) -> None:
    """逐行检查单个源码文件的违禁工具调用、静态版本 floor 与裸 python3。"""
    check_bare = (
        suffix == ".sh"
        and (rel.startswith("scripts/mac/") or rel == "scripts/ci/relay-tests.sh")
        and not (rel == "scripts/ci/relay-tests.sh" and "Darwin" in text)
    )
    for idx, raw in enumerate(lines, 1):
        st = raw.strip()
        if not st:
            continue
        if idx > 1 and (st.startswith("#") or st.startswith("//") or st.lower().startswith("rem ")):
            continue
        if not _g4_is_detector_line(rel, st):
            if _G4_PS51_RE.search(raw):
                res["ps51"].append(f"{rel}:{idx}: {st[:80]}")
            if _G4_WMIC_RE.search(raw):
                res["wmic"].append(f"{rel}:{idx}: {st[:80]}")
            if _G4_USR_BIN_PY_RE.search(raw):
                res["usr_py"].append(f"{rel}:{idx}: {st[:80]}")
            if _G4_VER_ID_RE.search(raw):
                res["ver_id"].append(f"{rel}:{idx}: {st[:80]}")
            if _G4_STATIC_FLOOR_RE.search(raw):
                res["static_floor"].append(f"{rel}:{idx}: {st[:80]}")
        if check_bare and not (rel == "scripts/mac/lint-repo.sh" and "bare_re" in st):
            code_part = _strip_shell_quotes(raw.split("#", 1)[0])
            if _G4_BARE_PY3_RE.search(code_part) and "/python3" not in code_part:
                res["bare_py"].append(f"{rel}:{idx}: {st[:80]}")


def _g4_verify_macos_dynamic(root: Path) -> None:
    """macOS 运行时动态核验：called_ver == max_installed_ver（含 micro 补丁位，零硬编码版本号）。"""
    cellar = Path("/opt/homebrew/Cellar")
    installed: list[tuple[int, int, int]] = []
    if cellar.is_dir():
        for d in cellar.glob("python@*"):
            for vd in d.iterdir():
                if vd.is_dir() and (m := re.match(r"^(\d+)\.(\d+)\.(\d+)", vd.name)):
                    installed.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    require("G4 macOS: Homebrew Cellar 存在已装 Python", len(installed) > 0)
    max_ver = max(installed)

    brew_py = Path("/opt/homebrew/bin/python3")
    require("G4 macOS: /opt/homebrew/bin/python3 可执行", brew_py.is_file())
    out_v = subprocess.check_output([str(brew_py), "--version"], text=True, timeout=10).strip()
    m_cur = re.search(r"Python\s+(\d+)\.(\d+)\.(\d+)", out_v)
    require("G4 macOS: 解析 /opt/homebrew/bin/python3 版本成功", bool(m_cur), out_v)
    cur_ver = (int(m_cur.group(1)), int(m_cur.group(2)), int(m_cur.group(3)))
    check("G4 macOS: /opt/homebrew/bin/python3 版本 == 本机最高已装版本", cur_ver, max_ver)

    rp_sh = root / "scripts" / "mac" / "lib" / "relay-python.sh"
    r_rp = subprocess.run(["bash", str(rp_sh)], capture_output=True, text=True, timeout=15)
    check("G4 macOS: relay-python.sh 退出码 0", r_rp.returncode, 0)
    if r_rp.returncode == 0:
        resolved_py = r_rp.stdout.strip().splitlines()[-1]
        v_res = subprocess.check_output([resolved_py, "--version"], text=True, timeout=10).strip()
        m_res = re.search(r"Python\s+(\d+)\.(\d+)\.(\d+)", v_res)
        res_ver = (int(m_res.group(1)), int(m_res.group(2)), int(m_res.group(3))) if m_res else None
        check("G4 macOS: relay-python.sh 返回解释器版本 == 最高版本", res_ver, max_ver)

    # 补丁位动态拦截自证：伪造同主次版本更高 micro 补丁（如 cur + 1），relay-python.sh 必须返回 RC=4
    fake_cellar = tmpdir("iron-g4-cellar-")
    (fake_cellar / f"python@{cur_ver[0]}.{cur_ver[1]}" / f"{cur_ver[0]}.{cur_ver[1]}.{cur_ver[2] + 1}").mkdir(parents=True)
    r_micro = subprocess.run(
        ["bash", str(rp_sh)],
        capture_output=True, text=True,
        env={**os.environ, "RELAY_HOMEBREW_CELLAR": str(fake_cellar)},
        timeout=15,
    )
    check("G4 macOS: relay-python.sh 同主次旧补丁版本拦截 (RC=4)", r_micro.returncode, 4)


def _part_g4_zero_hardcode_tool_gate():
    """G4：核验全仓零 5.1 / 零 wmic / 零旧 Python 硬编码，且 macOS 动态满足 called_ver == max_installed_ver。"""
    root = _gate_root()
    res = _g4_scan_repo(root)
    check("G4: 全仓零 PowerShell 5.1 活跃调用", res["ps51"], [])
    check("G4: 全仓零 wmic 活跃调用", res["wmic"], [])
    check("G4: 全仓零 /usr/bin/python3 活跃调用", res["usr_py"], [])
    check("G4: 全仓零 PY3xx / Python3xx 硬编码命名与路径", res["ver_id"], [])
    check("G4: 全仓零静态 Python 版本 floor（覆盖全 scripts/ 与 relay/）", res["static_floor"], [])
    check("G4: scripts/mac/*.sh 零裸 python3", res["bare_py"], [])
    check("G4: scripts/mac/*.py 零 #!/usr/bin/env python3", res["env_shebang"], [])

    # B2 仓外演练脚本检查（仅在未用 ARK_IRON_GATE_ROOT 切向沙箱且文件存在时执行）
    b2_reh = Path("/Users/herclyon/Money/styl-work/remote-ref/tools/relay_shift_rehearsal.py")
    if not os.environ.get("ARK_IRON_GATE_ROOT") and b2_reh.is_file():
        b2_txt = b2_reh.read_text(encoding="utf-8", errors="replace")
        check("G4 B2: relay_shift_rehearsal.py 零 powershell.exe", "powershell.exe" in b2_txt.lower(), False)
        check("G4 B2: relay_shift_rehearsal.py 零旧 automas Python 3.12 路径",
              r"D:\ark\automas\environment\python\python.exe" in b2_txt, False)

    if sys.platform == "darwin":
        _g4_verify_macos_dynamic(root)


# ---------------------------------------------------------------------------
# G5: 分层北京时间断电硬锁（全 16 入口覆盖 + 7 边界时刻行为实测）
# ---------------------------------------------------------------------------

_G5_IN_REPO_ENTRIES = (
    "scripts/mac/adbdo.sh",
    "scripts/mac/deploy-relay.sh",
    "scripts/mac/estop.sh",
    "scripts/mac/lib/deploy-pkg.sh",
    "scripts/mac/lib/shutdown_guard.py",
    "scripts/mac/mas-api.py",
    "scripts/mac/okww-task.sh",
    "scripts/mac/publish-cos.py",
    "scripts/mac/stream-ins.sh",
    "scripts/mac/techlog.py",
    "scripts/mac/watch-run.sh",
    "scripts/mac/wingui.sh",
    "scripts/mac/winps.sh",
    "scripts/mac/winrun.sh",
)

# 7 个核心边界时刻（北京时间 +08:00）：(ISO 时间, Tier1 预期阻塞, Tier2 预期阻塞)
_G5_BOUNDARY_CASES = (
    ("2026-11-28T08:21:59+08:00", False, False),
    ("2026-11-28T08:25:00+08:00", False, True),
    ("2026-11-28T08:39:59+08:00", False, True),
    ("2026-11-28T08:40:00+08:00", True, True),
    ("2026-11-28T08:45:59+08:00", True, True),
    ("2026-11-28T08:46:00+08:00", False, True),
    ("2026-11-28T08:47:00+08:00", False, False),
)


def _part_g5_tiered_powercut_guard():
    """G5：核验全部 16 入口挂载分层断电硬锁，并在 7 个边界时刻做真实行为实测。"""
    root = _gate_root()
    pc_py = root / "scripts" / "mac" / "lib" / "powercut_guard.py"
    pc_sh = root / "scripts" / "mac" / "lib" / "powercut-guard.sh"
    require("G5: powercut_guard.py 存在", pc_py.is_file(), str(pc_py))
    require("G5: powercut-guard.sh 存在", pc_sh.is_file(), str(pc_sh))

    # 1. 静态覆盖核验：14 个仓内入口必须全部接入 powercut-guard.sh 或 powercut_guard
    missing_guard: list[str] = []
    for rel in _G5_IN_REPO_ENTRIES:
        fp = root / rel
        if not fp.is_file():
            missing_guard.append(f"{rel}(文件不存在)")
            continue
        txt = fp.read_text(encoding="utf-8", errors="replace")
        if "powercut-guard.sh" not in txt and "powercut_guard" not in txt:
            missing_guard.append(rel)
    check("G5 静态覆盖: 14 个仓内 Mac->游戏机入口全部接入断电硬锁", missing_guard, [])

    # B2 仓外 2 个入口核验（verify.py + relay_shift_rehearsal.py）
    b2_verify = Path("/Users/herclyon/Money/styl-work/remote-ref/tools/verify.py")
    b2_reh = Path("/Users/herclyon/Money/styl-work/remote-ref/tools/relay_shift_rehearsal.py")
    if not os.environ.get("ARK_IRON_GATE_ROOT") and b2_verify.is_file() and b2_reh.is_file():
        check("G5 B2: verify.py 接入第 1 层断电硬锁", "powercut_guard" in b2_verify.read_text(encoding="utf-8"), True)
        b2_reh_txt = b2_reh.read_text(encoding="utf-8")
        check("G5 B2: relay_shift_rehearsal.py 复用 powercut_guard 第 2 层断电硬锁 RC=78",
              ("RC_POWERCUT_BLOCKED = 78" in b2_reh_txt and "import powercut_guard" in b2_reh_txt), True)

    # 2. 公共 Python 库 7 边界时刻实测（API + CLI 子进程，全平台运行）
    pcg = _load_module_from("iron_powercut_guard", pc_py)
    for ts, want_t1, want_t2 in _G5_BOUNDARY_CASES:
        dt_bj = pcg.parse_beijing_clock(ts)
        a1, _ = pcg.check_powercut(tier=1, caller="gate", now=dt_bj)
        a2, _ = pcg.check_powercut(tier=2, caller="gate", now=dt_bj)
        check(f"G5 API Tier1 {ts[11:19]}", not a1, want_t1)
        check(f"G5 API Tier2 {ts[11:19]}", not a2, want_t2)

        env = {**os.environ, "ARK_CLOCK_OVERRIDE": ts}
        r1 = subprocess.run([sys.executable, str(pc_py), "check", "--tier", "1", "--caller", "gate"],
                            capture_output=True, text=True, env=env, timeout=10)
        r2 = subprocess.run([sys.executable, str(pc_py), "check", "--tier", "2", "--caller", "gate"],
                            capture_output=True, text=True, env=env, timeout=10)
        check(f"G5 CLI Tier1 {ts[11:19]}", r1.returncode, 78 if want_t1 else 0)
        check(f"G5 CLI Tier2 {ts[11:19]}", r2.returncode, 78 if want_t2 else 0)

    # 3. POSIX 平台：实测 powercut-guard.sh 以及真实入口脚本（全程用桩命令隔离网络）
    if os.name == "posix":
        for ts, want_t1, want_t2 in _G5_BOUNDARY_CASES:
            env = {**os.environ, "ARK_CLOCK_OVERRIDE": ts}
            s1 = subprocess.run(["bash", "-c", f'. "{pc_sh}" && ark_powercut_guard 1 gate'],
                                capture_output=True, text=True, env=env, timeout=10)
            s2 = subprocess.run(["bash", "-c", f'. "{pc_sh}" && ark_powercut_guard 2 gate'],
                                capture_output=True, text=True, env=env, timeout=10)
            check(f"G5 SH Tier1 {ts[11:19]}", s1.returncode, 78 if want_t1 else 0)
            check(f"G5 SH Tier2 {ts[11:19]}", s2.returncode, 78 if want_t2 else 0)

        # 构造桩命令目录：ssh / scp / open / git / moonlight 一律立刻返回非 78 退出码，确保零真实发包或误启桌面程序
        stub = tmpdir("iron-g5-stub-")
        for tool, body in (
            ("ssh", "#!/bin/sh\nexit 99\n"),
            ("scp", "#!/bin/sh\nexit 99\n"),
            ("open", "#!/bin/sh\nexit 99\n"),
            ("moonlight", "#!/bin/sh\nexit 99\n"),
            ("git", "#!/bin/sh\necho not-main\nexit 0\n"),
        ):
            fp = stub / tool
            fp.write_text(body, encoding="utf-8")
            fp.chmod(fp.stat().st_mode | stat.S_IXUSR)

        base_env = {
            **os.environ,
            "PATH": f"{stub}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "ARK_HOST": "127.0.0.1",
            "ARK_MAS_PORT": "1",
            "ARK_MOONLIGHT_BIN": str(stub / "moonlight"),
            "TECHLOG_PROBE": "127.0.0.1:1",
            "TECHLOG_PROBE_TIMEOUT": "0.2",
            "ARK_ACTION_LOG": "/dev/null",
        }

        # 代表性第 1 层入口：08:40 & 08:45 必返 78；08:25 绝不返 78（不误杀只读探活）
        tier1_cmds = (
            ("winps.sh", ["bash", str(root / "scripts/mac/winps.sh"), "Write-Output ok"]),
            ("winrun.sh", ["bash", str(root / "scripts/mac/winrun.sh"), "--cmd", "echo ok"]),
            ("wingui.sh", ["bash", str(root / "scripts/mac/wingui.sh"), "shot"]),
            ("stream-ins.sh", ["bash", str(root / "scripts/mac/stream-ins.sh")]),
            ("mas-api.py", [sys.executable, str(root / "scripts/mac/mas-api.py"), "paths"]),
            ("techlog.py", [sys.executable, str(root / "scripts/mac/techlog.py"), "red"]),
        )
        for name, cmd in tier1_cmds:
            for ts in ("2026-11-28T08:40:00+08:00", "2026-11-28T08:45:59+08:00"):
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   env={**base_env, "ARK_CLOCK_OVERRIDE": ts}, timeout=15)
                check(f"G5 真实入口 Tier1 {name} @ {ts[11:19]} -> RC=78", r.returncode, 78)
            r_25 = subprocess.run(cmd, capture_output=True, text=True,
                                  env={**base_env, "ARK_CLOCK_OVERRIDE": "2026-11-28T08:25:00+08:00"}, timeout=15)
            check(f"G5 真实入口 Tier1 {name} @ 08:25:00 不误杀 (RC!=78)", r_25.returncode != 78, True)

        # 代表性第 2 层入口：将 deploy-relay.sh 挂入无 git 仓库的隔离镜像目录（保真测试其断电硬锁），
        # 在 08:25 / 08:40 / 08:46 必返 78；在 08:21 / 08:47 放行过关后即因非 main 分支秒退 2（绝不触发测试或网络）。
        stage_repo = tmpdir("iron-g5-deploy-")
        (stage_repo / "relay").mkdir()
        stage_mac = stage_repo / "scripts" / "mac"
        stage_mac.mkdir(parents=True)
        os.symlink(root / "scripts" / "mac" / "lib", stage_mac / "lib")
        staged_deploy = stage_mac / "deploy-relay.sh"
        staged_deploy.write_text((root / "scripts" / "mac" / "deploy-relay.sh").read_text(encoding="utf-8"), encoding="utf-8")
        staged_deploy.chmod(0o755)
        deploy_cmd = ["bash", str(staged_deploy)]
        for ts in ("2026-11-28T08:25:00+08:00", "2026-11-28T08:40:00+08:00", "2026-11-28T08:46:00+08:00"):
            r = subprocess.run(deploy_cmd, capture_output=True, text=True,
                               env={**base_env, "ARK_CLOCK_OVERRIDE": ts}, timeout=15)
            check(f"G5 真实入口 Tier2 deploy-relay.sh @ {ts[11:19]} -> RC=78", r.returncode, 78)
        for ts in ("2026-11-28T08:21:59+08:00", "2026-11-28T08:47:00+08:00"):
            r = subprocess.run(deploy_cmd, capture_output=True, text=True,
                               env={**base_env, "ARK_CLOCK_OVERRIDE": ts}, timeout=15)
            check(f"G5 真实入口 Tier2 deploy-relay.sh @ {ts[11:19]} 放行 (RC!=78)", r.returncode != 78, True)

        # B2 第 2 层入口实测（relay_shift_rehearsal.py，显式指向 127.0.0.1 与桩 ssh 确保零真连；同时覆盖 HH:MM:SS）
        if not os.environ.get("ARK_IRON_GATE_ROOT") and b2_reh.is_file():
            reh_cmd = [sys.executable, str(b2_reh), "--mode", "preflight", "--host", "127.0.0.1", "--ssh-timeout", "2"]
            for ts in ("08:22:00", "2026-11-28T08:25:00+08:00", "2026-11-28T08:40:00+08:00", "08:46:59"):
                r = subprocess.run(reh_cmd, capture_output=True, text=True,
                                   env={**base_env, "ARK_CLOCK_OVERRIDE": ts}, timeout=15)
                check(f"G5 B2 Tier2 relay_shift_rehearsal.py @ {ts} -> RC=78", r.returncode, 78)
            for ts in ("08:21:59", "08:47:00"):
                r_ok = subprocess.run(reh_cmd, capture_output=True, text=True,
                                      env={**base_env, "ARK_CLOCK_OVERRIDE": ts}, timeout=15)
                check(f"G5 B2 Tier2 relay_shift_rehearsal.py @ {ts} 放行进桩探活 (RC=20，非崩溃/非78)",
                      r_ok.returncode, 20)


# ---------------------------------------------------------------------------
# G6: D213 私有工具禁加密（跨 3 私有仓扫描，支持 ARK_IRON_GATE_REPOS 严格覆写）
# ---------------------------------------------------------------------------

_G6_SKIP_DIRS = {
    ".git", ".build", ".swiftpm", "build", ".gradle", "node_modules",
    "__pycache__", ".venv-relaytest", "Vendor", "Data", "Layers", "fixtures", "logs", "dist",
}
_G6_CODE_EXTS = {
    ".py", ".kt", ".java", ".swift", ".ts", ".tsx", ".js", ".jsx",
    ".gradle", ".kts", ".sh", ".ps1", ".xml", ".plist",
}
_G6_CRYPTO_RE = re.compile(
    r"(AndroidKeyStore|KeyStore\.getInstance|com\.google\.crypto\.tink|AeadConfig|"
    r"EncryptedSharedPreferences|EncryptedFile|\bMasterKey\b|KeyGenParameterSpec|"
    r"SecretKeyFactory|AES/GCM|AES\.GCM|ChaChaPoly|javax\.crypto\.Cipher|"
    r"cryptography\.fernet|\bFernet\b|Crypto\.Cipher|nacl\.secret|"
    r"SecItemAdd|kSecClassGenericPassword|\bTink\b|\bAEAD\b)"
)


def _part_g6_d213_no_crypto_private_repos():
    """G6：核验私有工具仓库（maa-automation / ark-remote / transit-app）零加密存储与 Keystore/Tink。"""
    root = _gate_root()
    env_repos = os.environ.get("ARK_IRON_GATE_REPOS", "").strip()
    if env_repos:
        # 显式指定 ARK_IRON_GATE_REPOS 时严格要求每个目录都存在，绝不静默跳过
        repo_paths = [Path(x).resolve() for x in env_repos.split(os.pathsep) if x.strip()]
        require("G6: ARK_IRON_GATE_REPOS 非空", len(repo_paths) > 0)
        for rp in repo_paths:
            require(f"G6: 指定扫描仓存在 ({rp})", rp.is_dir(), str(rp))
    else:
        repo_paths = [root]
        for sib in (Path.home() / "Claude" / "ark-remote", Path.home() / "Claude" / "transit-app"):
            if sib.is_dir():
                repo_paths.append(sib.resolve())

    self_file = Path(__file__).resolve()
    hits: list[str] = []
    for repo in repo_paths:
        for cur_dir, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in _G6_SKIP_DIRS and not d.startswith(".venv")]
            for fn in sorted(files):
                p = Path(cur_dir) / fn
                if p.suffix not in _G6_CODE_EXTS:
                    continue
                if p.resolve() == self_file or p.name == "test_iron_rules_gate.py":
                    continue
                try:
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for idx, ln in enumerate(txt.splitlines(), 1):
                    if m := _G6_CRYPTO_RE.search(ln):
                        hits.append(f"{repo.name}/{p.relative_to(repo).as_posix()}:{idx}: {m.group(0)}")
    check("G6 D213: 私有工具仓零 Keystore/Tink/AEAD/Fernet 加密防护", hits, [])


if __name__ == "__main__":
    sys.exit(run_parts([
        _part_g1_d1010_shutdown,
        _part_g2_daily_whitelist_and_no_mute,
        _part_g3_boot_no_github,
        _part_g4_zero_hardcode_tool_gate,
        _part_g5_tiered_powercut_guard,
        _part_g6_d213_no_crypto_private_repos,
    ]))
