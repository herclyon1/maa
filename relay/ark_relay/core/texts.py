"""Every piece of copy pushed to the user, in this one module and nowhere else.

Three rules, set by the user:
1. **Plain language only**: only product names and 「Boss」 are allowed English;
   exception names and raw logs never reach a notification.
2. **Nothing vague**: faults are classified into `ErrorCode` and rendered with
   closed plain-Chinese templates instead of raw English or blind boxes.
3. **Same kind, same phrasing**: weeklies and update notifications read alike.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from urllib.parse import urlsplit

from ark_relay.core.config import GAME_ZH

# 允许留在通知里的英文：产品名、游戏内常用词与需要原样照抄的命令名。
ALLOWED_WORDS = {
    "MAA", "MaaEnd", "OK-WW", "AUTO-MAS", "MXU", "Boss", "Annihilation", "F2",
    "PIN", "net", "stop", "start", "ark-relay", "deploy-relay.sh", "scripts/mac/deploy-relay.sh",
    "MuMu", "APK", "v", "DirectX",
}
VAGUE = ("未知错误", "这一步", "有问题", "出错", "多半", "可能", "大概", "大约", "应该是", "似乎",
         "疑似", "也许", "或许", "估计", "差不多", "左右", "好像", "不确定", "貌似", "大致", "约 ", "约一", "不一定")
JARGON = ("落盘", "回读", "兜底", "字段", "判据", "判定点", "监听", "句柄", "进程", "线程",
          "缓存", "重放", "拉起", "收窄", "节点", "实例", "退避", "调度器", "死键", "标记文件",
          "时间窗", "任务链", "冲掉", "结构化", "白名单", "凭空造", "原子", "幂等", "接口")
_THEIR_TERMS = ("结束进程", "周本领奖：回读", "MaaEnd 进程超时", "进程未退出", "调度器 \\| 未通过配置检查")


class _PlainSpec:
    """极简严格人话门禁（plain）的规则与扫描器，封在类内不混入对外文案常量扫描。"""

    EXTS = "py|rs|cs|js|ts|jsonl|json|log|txt|md|yaml|yml|toml|ini|cfg|conf|exe|dll|dmp|bat|cmd|ps1|sh|zip|gz|zst|db|sqlite|png|jpg|jpeg|webp|csv|xml|html|swift|lock|flag|bak|tmp|pth|whl|env|dat|crt|pem"
    PROTO_HEADS = frozenset({"http", "https", "grpc", "tls", "ssl", "quic", "rtsp", "sip", "ws", "wss", "mqtt", "ftp", "ssh", "tcp", "udp"})
    EXC_RE = re.compile(r"^(?:Error|Exception|Warning|Timeout|WinError|Errno|Traceback|gaierror|[A-Z][A-Za-z0-9]*(?:Error|Exception|Warning|Timeout|Interrupt|Failed|Failure|Refused|Reset|Aborted|Disconnected|Denied|Closed|Expired|Iteration|Redirects|Pipe|Read|Exists|Locked|NotFound|Exit)|(?:Bad|Cannot|NoSuch|ResponseNot|TooMany)[A-Z][A-Za-z0-9]+)$")
    CAMEL_TWO_RE, IDENT_RE = re.compile(r"^(?:[A-Z][a-z0-9]+[A-Z]|[A-Z]{3,}[a-z]{2})[A-Za-z0-9]*$"), re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    URL_AUTH_RE, URL_CHARS = re.compile(r"https?://(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9._~%-]+)(?::\d+)?", re.I), frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~:/?#@!$&*+,;=%()")
    WIKI_PAREN_RE, WIKI_NS_RE, PROTO_SLASH_RE, MATRIX_PARAM_RE = re.compile(r"^[a-z0-9_]+$"), re.compile(r"/(?:File|Category|Special)$"), re.compile(r"(?:https?|grpc|tls|ssl|quic|rtsp|sip|ws|wss|mqtt)/", re.I), re.compile(r"(?:jsessionid|phpsessid|sid)=[A-Za-z0-9._-]+", re.I)
    # 引号内 Windows/UNC、显式 Unix 根路径（含中文目录）、无引号 Windows/UNC（仅放行明确系统目录空格与纯中文目录空格）
    QUOTED_WIN_RE = re.compile(r"""(?P<q>['"])((?:[A-Za-z]:[\\/]|\\\\[^\\/\s'"]+[\\/])[^\r\n'"]*?)(?P=q)""")
    _UROOT = r"opt|etc|var|usr|Users|home|tmp|bin|sbin|Library|private|Applications|System|Volumes|dev|proc|srv|run|mnt"
    _USEG = r"[A-Za-z0-9_.+@~%\u4e00-\u9fff-]+"
    _UEND = rf"(?:[A-Za-z0-9_.+@~%-]*[\u4e00-\u9fff][A-Za-z0-9_.+@~%\u4e00-\u9fff-]*(?:\.(?i:{EXTS}))+(?![A-Za-z0-9_])|[A-Za-z0-9_.+@~%-]+)"
    UNIX_PATH_RE = re.compile(rf"""(?:^|(?<=[\s'"（(\[【：:，,、=\u4e00-\u9fff]))(?:/(?:{_UROOT})/(?:{_USEG}/)*{_UEND}?|(?:\./|\.\./|~/)(?:(?:{_USEG}/)+{_UEND}?|{_UEND}))""")
    _DIR = r"(?:(?:Program Files \(x86\)|Program Files \(x64\)|Program Files|Default User|Common Files|Application Data)|(?:[\u4e00-\u9fff][\u4e00-\u9fff0-9._-]*(?: (?:[\u4e00-\u9fff][\u4e00-\u9fff0-9._-]*|\d+(?:\.\d+)*))*)|[A-Za-z0-9_.+~@#%$-]+)"
    _END = rf"(?:[\u4e00-\u9fff][\u4e00-\u9fff0-9._-]*\.(?:{EXTS})|[A-Za-z0-9_.+~@#%$-]+)"
    WIN_UNC_RE = re.compile(rf"(?:(?<![A-Za-z0-9_])[A-Za-z]:[\\/](?:{_DIR}[\\/])*{_END}?|(?<![\\A-Za-z0-9_])\\\\[A-Za-z0-9_.-]+[\\/](?:(?:{_DIR}[\\/])+{_END}?|{_END}))", re.I)
    _RSEG = r"[A-Za-z0-9_.\u4e00-\u9fff-]+"
    _REND = rf"(?:[A-Za-z0-9_.-]*[\u4e00-\u9fff][A-Za-z0-9_.\u4e00-\u9fff-]*(?:\.(?i:{EXTS}))+|[A-Za-z0-9_.-]+)"
    REL_PATH_RE = re.compile(rf"((?:(?<![A-Za-z0-9_/:.\\\u4e00-\u9fff-])[\u4e00-\u9fff][\u4e00-\u9fff0-9_.-]*|(?<![A-Za-z0-9_/:.\\-])[A-Za-z0-9_.-]+)(?:[\\/]{_RSEG})*[\\/]{_REND})(?![A-Za-z0-9_])")
    EXT_END_RE, EXT_TAIL_RE, NUM_SEG_RE = re.compile(rf"(?:\.(?:{EXTS}))+$", re.I), re.compile(rf"\.(?:{EXTS})(?:\s+\S|[,;!][A-Za-z_])", re.I), re.compile(r"^v?\d+(?:\.\d+)*$", re.I)
    FILE_RE = re.compile(rf"(?<![A-Za-z0-9_/:.\\-])[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*?(?:\.(?:{EXTS}))+(?![A-Za-z0-9_])", re.I)
    SEMVER_RE, WORD_RE = re.compile(r"(?<![A-Za-z0-9_-])v\d+(?:\.\d+)*(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?(?![A-Za-z0-9_])"), re.compile(r"[A-Za-z][A-Za-z0-9./\-]*")
    DIRECT_RES = (UNIX_PATH_RE, WIN_UNC_RE, re.compile(r"(?<![A-Za-z0-9_/:.\\-])(?:scripts/mac/deploy-relay\.sh|resource/tasks|(?:state/)?shots/[A-Za-z0-9_./-]+|\d{4}-\d{2}-\d{2}/(?:ark|arknights|endfield|wuwa)/[A-Za-z0-9_.-]+)(?![A-Za-z0-9_])"), FILE_RE, re.compile(r"(?<![A-Za-z0-9])\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[Zz]|[+-]\d{2}:?\d{2})?(?![A-Za-z0-9])"), re.compile(r"(?<![A-Za-z0-9])0x[0-9A-Fa-f]+(?![A-Za-z0-9])"))

    @classmethod
    def is_exc(cls, word: str) -> bool:
        """判断词元是否为英文异常/报错类名，自动排除 ALLOWED_WORDS 白名单词。"""
        return word not in ALLOWED_WORDS and bool(cls.EXC_RE.match(word))

    @classmethod
    def scan_url(cls, text: str, start: int) -> int:
        """扫描合法 RFC 3986 URL：path 段遇 ,/;(!) 紧跟英文词即停（仅留 ;jsessionid= 矩阵参数），?query 内保 COS/REST ; , 并拦异常/协议/非法括号。"""
        if (start > 0 and text[start - 1].isascii() and text[start - 1].isalnum()) or not (m := cls.URL_AUTH_RE.match(text, start)):
            return start
        i, n, auth_end, in_query = m.end(), len(text), m.end(), False
        while i < n and text[i] in cls.URL_CHARS:
            ch = text[i]
            if ch == "?":
                in_query = True
            if ch == "(":
                close = text.find(")", i + 1) if i > auth_end and text[i - 1] == "_" else -1
                if close > i + 1 and cls.WIKI_PAREN_RE.match(text[i + 1 : close]):
                    i = close + 1
                    continue
                break
            if ch == ")" or (ch == ":" and not text.startswith("://", i) and i + 1 < n and text[i + 1].isascii() and text[i + 1].isalpha() and not cls.WIKI_NS_RE.search(text, auth_end, i)):
                break
            if ch == ":" and text.startswith("://", i):
                i += 3
                continue
            if ch in ",;!":
                rest = text[i + 1 :]
                wm = cls.IDENT_RE.match(rest)
                if not rest or rest[0] in "([)]\"'<> " or not rest[0].isascii() or cls.PROTO_SLASH_RE.match(rest):
                    break
                if not in_query:
                    if wm and not (ch == ";" and cls.MATRIX_PARAM_RE.match(rest)):
                        break
                elif wm and (cls.is_exc(wm.group(0)) or (wm.group(0) not in ALLOWED_WORDS and cls.CAMEL_TWO_RE.match(wm.group(0)) and not rest[wm.end() :].startswith(("=", "&")))):
                    break
            i += 1
        while i > auth_end and text[i - 1] in ".,;:!?":
            i -= 1
        return i if urlsplit(text[start:i]).netloc else start

    @classmethod
    def mask_urls(cls, text: str, repl) -> str:
        out, pos = [], 0
        for m in re.finditer(r"https?://", text, re.I):
            if m.start() >= pos and (end := cls.scan_url(text, m.start())) > m.start():
                out.extend((text[pos : m.start()], repl(text[m.start() : end])))
                pos = end
        return "".join((*out, text[pos:]))

    @classmethod
    def valid_rel(cls, cand: str) -> bool:
        segs = re.split(r"[\\/]", cand)
        s0 = re.sub(r"^[\u4e00-\u9fff]+", "", segs[0]) if segs else ""
        return (len(segs) >= 2 and bool(cls.EXT_END_RE.search(segs[-1]))
                and not (s0.lower() in cls.PROTO_HEADS or cls.NUM_SEG_RE.match(s0))
                and not any(cls.is_exc(w) for seg in segs[:-1] for w in cls.IDENT_RE.findall(seg)))

    @classmethod
    def mask_safe(cls, text: str, hold: list[str] | None = None, *, mask_hex: bool = True) -> str:
        """遮蔽合法 URL、显式/引号/相对路径、ISO 时间、版本号与十六进制码。"""
        def _put(val: str) -> str:
            if hold is None:
                return " "
            hold.append(val)
            return f"\x00{len(hold) - 1}\x00"

        def _qwin(m: re.Match) -> str:
            rest = m.group(2)[2:] if len(m.group(2)) >= 2 and m.group(2)[1] == ":" else m.group(2)
            last = ([seg for seg in re.split(r"[\\/]", rest) if seg] or [""])[-1]
            if ":" in rest or cls.EXT_TAIL_RE.search(last) or any(cls.is_exc(w) for w in cls.IDENT_RE.findall(rest)):
                return m.group(0)
            return _put(m.group(0))

        def _path(m: re.Match) -> str:
            val = m.group(0).rstrip(".,;:")
            tail = re.split(r"[\\/]", val)[-1]
            if tail and not cls.EXT_END_RE.search(tail) and cls.is_exc(tail):
                return m.group(0)
            return _put(val) + m.group(0)[len(val) :]

        s = cls.QUOTED_WIN_RE.sub(_qwin, cls.mask_urls(text, _put))
        for pat in cls.DIRECT_RES[:2]:
            s = pat.sub(_path, s)
        s = cls.DIRECT_RES[2].sub(lambda m: _put(m.group(0).rstrip(".,;:")), s)
        s = cls.REL_PATH_RE.sub(lambda m: _put(m.group(0)) if cls.valid_rel(m.group(0)) else m.group(0), s)
        for pat in (cls.DIRECT_RES[3:] if mask_hex else cls.DIRECT_RES[3:5]):
            s = pat.sub(lambda m: _put(m.group(0)), s)
        return cls.SEMVER_RE.sub(lambda m: _put(m.group(0)) if not ("-" in m.group(0) and any(cls.is_exc(x) for x in re.split(r"[.-]", m.group(0).split("-", 1)[1]))) else m.group(0), s)


def plain(text: str) -> list[str]:
    """极简严格人话门禁：检查未允许英文、模糊词与工程术语；返回空列表表示合格。"""
    problems = [f"英文「{w}」" for w in _PlainSpec.WORD_RE.findall(_PlainSpec.mask_safe(text)) if w not in ALLOWED_WORDS]
    problems.extend(f"模糊词「{v}」" for v in VAGUE if v in text)
    scrubbed = text
    for term in _THEIR_TERMS:
        scrubbed = scrubbed.replace(term, " ")
    return problems + [f"术语「{j}」" for j in JARGON if j in scrubbed]


# ---------------- titles ----------------
PREUPDATE = "🆕 预更新"
GAME_UPDATE = "🆕 游戏更新"
RERUN_AFTER_UPDATE = "🔁 更新后重跑"
WEEKLY = "🗓️ 周常"                 # one title for annihilation / weekly garden / weekly boss finishing
NEW_WEEK = "🗓️ 新的一周"           # Monday boot: one line of state for each of the three
# MAA's annihilation switch is off and this week is not done: nothing turns it back on
# (annihilation.WeeklyGate.switch_off_line; boot_stages._stage_annihilation).
ANNIHILATION_OFF = "⚠️ 剿灭开关关着"


def annihilation_off_body(name: str) -> str:
    return (f"{name}：开关是关闭，本周还没打满。调度程序和中继都不会把它打开，"
            "开关关着就一直不打剿灭；要打，把剿灭开关改成要打的关卡。")
SKIP_MODE = "⏭️ 跳过模式"
# A skip / restore of a queue that did not take: a failure, so the group (engine._observe_modes).
SKIP_FAILED = "⚠️ 跳过队列没办成"
ESTOP = "🛑 已停一切"
ESTOP_FAILED = "🛑 没能停干净"
SHUTDOWN_CANCELLED = "🌙 关机被取消"
ALARM_HOLD_EXPIRED = "⏰ 故障留机锁到期释放"
ALARM_SHUTDOWN_ABORTED = "🚨 故障留机期间拦下外部关机"
ALARM_EARLY_SHUTDOWN = "🚨 上次故障未修完时被提前关机"
ALARM_EARLY_NO_LOG = "系统日志读不到，无法确认上次关机发起方。"
ALARM_EARLY_NO_1074 = "系统日志里没有正常关机记录（直接断电或系统崩溃，无法确认发起方）。"
ALARM_HOLD_CORRUPT = "故障留机锁的保存内容损坏，已强制清理；请核查上次故障是否已修完。"


def alarm_hold_expired_body(reason: str, boot: str, in_window: bool) -> str:
    why = reason or "上次故障留机"
    if in_window:
        return (f"故障留机锁已到释放时刻（下次定时开机 {boot} 前 10 分钟），先放开以便按计划重启并准备下一班。\n"
                f"原留机原因：{why}\n"
                "如果问题还没修完，请在下次开机后第一时间补修。")
    return (f"故障留机锁已过释放时刻（预定开机 {boot}），已解除留机锁；离下次开机太近，这次不再安排关机。\n"
            f"原留机原因：{why}\n"
            "如果问题还没修完，请在下次开机后第一时间补修。")


def alarm_shutdown_aborted_body(ok: bool, rc: int, who: str, what: str, why: str) -> str:
    parts = [p for p in (
        f"发起账号：{who}" if who else "",
        f"发起程序：{what}" if what else "",
        f"说明：{why}" if why else "",
    ) if p]
    detail = "；".join(parts) if parts else "系统日志里没写发起方"
    if ok:
        return f"当前还有未修完的故障留机锁，刚才拦下了一次外部发起的关机。\n{detail}"
    return (f"当前还有未修完的故障留机锁，刚才发现外部发起关机，但自动取消没成功（退出码 {rc}），"
            f"机器会继续关机。\n{detail}")


def alarm_early_shutdown_body(reason: str, until: str, detail: str) -> str:
    why = reason or "上次故障留机"
    return (f"上次开机还有未修完的故障留机锁（原定留机至 {until}，原因：{why}），"
            f"但在到期前就已经关机。\n{detail}")
CONFIG_CHANGED = "📱 配置已修改"
CONFIG_FAILED = "📱 配置没改成"
# The receipt of a batch from the repo inbox (scripts/mac/order.sh, inbox.Inbox.poll) that
# went through: log only (notify._LOG_ONLY_PREFIXES). One with a ✗ line is CONFIG_FAILED.
INBOX_APPLIED = "⚙️ 配置已更新"
SELFUPDATE_FAILED = "⚠️ 中继自更新没成功"
WATCH_LOST = "⚠️ 中继暂时不能在脚本跑完时马上处理结果"
RELAY_ERROR = "🩺 中继自己报错了"
SELFCHECK_FAILED = "🩺 开机自检没过"
# The relay's pre-update just installed a new AUTO-MAS and a setting the relay reads is no
# longer where it looks (mascontract.check; selfcheck.report_contract).
AUTOMAS_CONTRACT = "⚠️ 调度程序升级后，中继有设置读不到"
AUTOMAS_DOWN = "🔌 AUTO-MAS 启动不起来"
ROUND_INCOMPLETE = "⚠️ 这一轮没干完"
ACTIVITY_TOPUP = "🔁 鸣潮早班活跃没满，晚班补"
ACTIVITY_TOPUP_WAIT = "鸣潮活跃晚班补还没完"
AK_ACTIVITY_OPEN = "🎉 明日方舟活动开启"


def ak_activity_open_body(name: str, kind_zh: str, start_txt: str,
                          end_txt: str = "", rerun: bool = False,
                          opening_today: bool = False) -> str:
    tag = f"{kind_zh}（复刻）" if rerun else kind_zh
    verb = "今日开启" if opening_today else "已开启"
    lines = [f"明日方舟{tag}「{name}」{verb}。"]
    if end_txt:
        lines.append(f"时间：{start_txt} 至 {end_txt}")
    else:
        lines.append(f"开启：{start_txt}")
    lines.append("请留意调整刷图关卡与理智安排。")
    return "\n".join(lines)


def activity_topup_body(points, due) -> str:
    got = f"{points} 分" if points is not None else "没满 100"
    return (f"今天早班鸣潮每日活跃 {got}：波片（连备用）不够，「累计消耗 180 点结晶波片」那一项没做完。"
            f"晚班（北京 {due:%H:%M}）跑完后中继再让鸣潮跑一次每日任务，把波片刷完补满；晚班还没满会再报。")


ACTIVITY_TOPUP_NEVER_RAN = "晚班没补上（那晚没开机，或者开了没轮到它）"


def activity_topup_not_dispatched(tries: int, why: str) -> str:
    return f"晚班派了 {tries} 次都没派下去（{why}）"


def activity_topup_no_record(sent) -> str:
    return f"晚班 {sent:%H:%M} 派下去了，过了两个小时还没有这一趟的记录"


def activity_topup_failed(points, why: str) -> str:
    """The alarm when the evening top-up did not get to run (activity._alarm)."""
    got = f"{points} 分" if points is not None else "没满 100"
    return f"鸣潮今天每日活跃 {got}，早班波片不够、说好晚班补，但{why}，所以今天没满 100。"


def activity_topup_detail(points, due) -> str:
    """The 「每日活跃满 100」 item of a morning booked for the top-up: passed, with why."""
    got = f"早班 {points} 分" if points is not None else "早班没满"
    return f"{got}，波片不够，晚班（北京 {due:%H:%M}）补"
# The sanity booster stays on, and a MaaEnd change that stops it applying is an
# alarm: a booster step in a shape the relay does not know rings the group at
# every boot (gameupdate.spmed_check).
SPMED_UNRECOGNISED = "⚠️ 终末地应急理智加强剂：中继确认不了还能不能用上"
# The make-up (makeup.py) switched 存放背包 on (and moved it in front) for one run,
# or an older make-up narrowed the tasks, and it can put neither the saved switches
# nor the full copy back: a real alarm, our side has to put it back.
MAKEUP_RESTORE_FAILED = "⚠️ 终末地设置没能自动改回"
MAAEND_PRUNED = "🧹 终末地配置清掉了死条目"
MAAEND_PRUNED_REFUSED = "⚠️ 终末地配置里的死条目没能清"
MAAEND_MIGRATED = "🧩 终末地新版本改了设置格式，已按原意换写"
ENDFIELD_NO_LAUNCHER = ("调度程序会拒绝开终末地：它从游戏所在的位置往上找不到终末地的官方启动器，"
                        "MaaEnd 每一趟都会在开跑前直接跳过")
# efstart_setup: AUTO-MAS cannot be put on 「MaaEnd 启动」 (window 1280x720, fullscreen back after),
# so it stays on the launcher's fullscreen start, which MaaEnd reads only with DirectX 11 ticked.
ENDFIELD_NO_MAAEND_START = ("调度程序没法让 MaaEnd 把终末地开成窗口，只能退回经官方启动器全屏开："
                            "官方启动器上「DirectX 11 启动」那一格没勾时，MaaEnd 每一趟都会认不出游戏画面")
# 采集补跑启动仅记日志；补跑最终结果（无论全通还是仍有失败/复发）一律直推企微群暴露首趟故障，绝不进日报、绝不静默吞错。
COLLECT_RETRY_START = "🔁 自动采集：只补跑失败的路线"
COLLECT_RETRY_OK = "⚠️ 自动采集：首趟失败，补跑后全部走完"
COLLECT_RETRY_FAILED = "⚠️ 自动采集：补跑仍有路线没走通"
COLLECT_RECURRENT = "🚩 自动采集：有路线连续两天补跑失败，是复发性问题"
EVIDENCE_SAVED = "🗂️ 证据包已送出机器"
# One line in a group alarm whose evidence bundle could not be uploaded.
EVIDENCE_NOT_SHIPPED = "证据包这次没传上去，原因记在机器上的中继日志里，我们这边照着查。"
EVIDENCE_SOURCE_CHANGED = "🧷 上游改了导出日志的代码，证据包的打法要重新核对"
# Skland answered with more than one Endfield role; nothing was read (resources.py).
SKLAND_MULTI_ROLE = "⚠️ 森空岛给了不止一个终末地角色，没有读"
MAAEND_STUCK_KILLED = "⚠️ 终末地 MaaEnd 卡住，已结束它让 AUTO-MAS 接着走"
MAAEND_STUCK_KILL_FAILED = "⚠️ 终末地 MaaEnd 卡死，没能结束"
MAAEND_WATCH_BLIND = "⚠️ 终末地看门狗读不到 MaaEnd 的运行日志"
MAA_START_STUCK_KILLED = "⚠️ 明日方舟开游戏卡住，已结束 MAA 让 AUTO-MAS 重开"
MAA_START_STUCK_KILL_FAILED = "⚠️ 明日方舟开游戏卡住，没能结束 MAA"


# A gathering route that walked through but hit the game's 「战斗中无法使用」 at a relay
# device gathered nothing (collector_maaend.blocked_routes). Said in the daily row, in
# the outcome check that hands it to the retry, and in the retry's daily line.
COLLECT_BLOCKED = "撞上「战斗中无法使用」没采到"


def collect_blocked_check(label: str) -> str:
    """outcome.maaend_checks: one blocked route, handed to the retry before power-off."""
    return f"自动采集 {label} {COLLECT_BLOCKED}，关机前单独补这一条"


def collect_blocked_row(labels: list[str], again: bool = False, first: bool = False) -> str:
    """ledger_rows / report.retry_line: the routes that hit it; `again` = during the retry,
    `first` = in the run the retry follows."""
    return ("补跑时又" if again else "第一趟" if first else "") + COLLECT_BLOCKED + "：" + "、".join(labels)


def collect_second_round(labels: list[str]) -> str:
    """One line of the retry's body: the routes its first round found blocked were walked
    once more on their own (collect_retry._bring_up_and_run)."""
    return "补跑第一轮" + COLLECT_BLOCKED + "，单独又补了一轮：" + "、".join(labels)


def collect_retry_body(passed: list[str], failed: list[str], unknown: list[str], note: str) -> str:
    lines = []
    if passed:
        lines.append("补跑走通：" + "、".join(passed))
    if failed:
        lines.append("补跑仍失败：" + "、".join(failed))
    if unknown:
        lines.append("没拿到结果：" + "、".join(unknown))
    if note:
        lines.append(note)
    return "\n".join(lines) or "没有要补跑的路线"


def maaend_crash_reason(code: str) -> str:
    """The plugin wrote a crash to its stderr; `code` is the 0x... exception code, or ""."""
    what = f"（错误码 {code}）" if code else "（原文在 debug\\go-service.stderr.log）"
    return f"判定原因：MaaEnd 的插件 agent\\go-service.exe 崩溃了{what}，之后 MaaEnd 不会再往下走。"


def maaend_plugin_gone_reason(seconds: int) -> str:
    return (f"判定原因：MaaEnd 还开着，它的插件 agent\\go-service.exe 已经不在了"
            f"（隔 {seconds} 秒查了两次都不在），MaaEnd 不会再往下走。")


def maaend_agreement_reason() -> str:
    """maaend_watchdog: the game held at the one-time 「协议更新」 dialog (2026-11-20, #187)."""
    return ("判定原因：终末地停在一次性的「协议更新」窗口，要点「同意」才进得去；MaaEnd 认不出这个窗口，"
            "后面的任务只会一个个等到超时（11 月 20 日早班这样白等了 83 分钟）。"
            "程序不替你点同意，也不做无效补跑，机器留着等你点完再跑。")


def maaend_logged_out_reason() -> str:
    """maaend_watchdog: the game held at the 「登录认证已失效」 dialog (logged in elsewhere)."""
    return ("判定原因：终末地弹出「登录认证已失效」（这个号在别的设备上登录了），之后进不了游戏；"
            "MaaEnd 认不出这个窗口，后面的任务只会一个个等到超时。"
            "之后照常重试和补跑：补跑会关掉游戏、重开客户端再试一次，不会替你输密码。")


def maaend_stall_reason(minutes: int, last: str) -> str:
    tail = f"（最后一行 {last}）" if last else ""
    return f"判定原因：MaaEnd 的运行日志 debug\\maafw.log 已 {minutes} 分钟没有新行{tail}；正常运行时两行最多隔 65 秒。"


def maaend_watch_blind_body(minutes: int) -> str:
    return (f"MaaEnd 已经跑了 {minutes} 分钟，看门狗一行运行日志（debug\\maafw.log）都没读到。\n"
            "读不到日志说明不了 MaaEnd 卡没卡，所以这次不结束它；已交给我们这边去查这个日志还在不在原处。")


def maa_start_stuck_body(started: str, minutes: int, presses: int, killed: bool, why: str,
                         quiet_minutes: int) -> str:
    """maa_start_watchdog: `started` 「09:03」 is when MAA began starting the game (the machine's
    clock), `minutes` the time since; `presses` how often MAA pressed 「开始唤醒」 meanwhile;
    `quiet_minutes` how long it has been since the last download or resource-check screen."""
    head = f"MAA {started} 开始开明日方舟，{minutes} 分钟了还没进到游戏里"
    if presses:
        head += f"，「开始唤醒」点了 {presses} 次画面都没变"
    head += f"；最近 {quiet_minutes} 分钟没在下载更新，也没在校验资源。平时开游戏 1 分钟多一点。"
    if killed:
        return head + ("\n已结束 MAA，模拟器和游戏留给 AUTO-MAS 关。AUTO-MAS 每分钟看一次，发现 MAA 不在了就算这一次失败："
                       "截图、关模拟器、重开一次（重试次数用完才算这一班 MAA 失败），不用再等它自己的时限。")
    return head + (f"\n结束 MAA 没成功（{why}），它还卡着，要等 AUTO-MAS 自己的时限才会被结束；"
                   "已交给我们这边去查为什么结束不了。")


def maaend_stuck_body(reason: str, killed: bool, why: str, left: "list[str] | tuple" = ()) -> str:
    """`left` names the plugins maaend_watchdog._end did not end (outside the agent
    directory, or taskkill failed), e.g. 「agent\\go-service.exe」
    (a path: the texts gate passes it; a bare name or PID it refuses)."""
    if killed:
        ended = ("已结束 MaaEnd，游戏本身没动；它的插件 " + "、".join(left) + " 没结束掉，还开着。" if left
                 else "已结束 MaaEnd 和它还开着的插件，游戏本身没动。")
        return (reason + "\n" + ended +
                "AUTO-MAS 接着按 MaaEnd 的日志判这一趟：没干完的、还有重试次数就马上重跑，"
                "已经干完的直接收尾——不用再等它的时限（MaaEnd 日志 40 分钟不动才结束）。")
    return (reason + f"\n结束 MaaEnd 没成功（{why}），它还卡着，"
            "要等到 AUTO-MAS 给 MaaEnd 的时限才会被结束；已交给我们这边去查为什么结束不了。")


def collect_recurrent_body(names: list[str]) -> str:
    return ("连续两天补跑都失败的：" + "、".join(names)
            + "。这不像偶发，中继不再自动重试这几条；已交给我们这边带上证据包整理成上游问题报告。"
            "对外发帖要你点头，发出去之前会先问你。")


def evidence_saved_body(script: str, started: str, files: int, page: str) -> str:
    """`started` is the run's start as 「09-11 10:18」, not its run_id (that is a path).
    `page` is the COS link: handle.py uploads through evidence.uploaders(), COS only."""
    head = f"{GAME_ZH.get(script, script)} {started} 那趟：一个压缩包，里面 {files} 个文件"
    return head + f"\n下载页：{page}"


def evidence_source_changed_body(names: list[str]) -> str:
    return ("变了的：" + "、".join(names)
            + "。只盯打包那几个函数，别处改动不会触发这条；所以这是打包代码本身变了。"
            "在重新核对之前，中继打的证据包不保证和官方按钮导出的一样。")
ECHO_FARM = "🥚 开始刷声骸"
ECHO_FARM_DONE = "🥚 刷声骸收工"
ECHO_FARM_TROUBLE = "⚠️ 刷声骸收工出了问题"
TACET_DROPS = "🖼️ 无音区产出"


# The title says when a patch could not be applied (a refused nest patch means
# every nest is farmed whatever the plan says), not only the lines under it.
_PATCH_TROUBLE = ("贴不上", "没贴上", "写不进", "叠了", "没能检查", "对不上", "自己报错了")


def patches(n: int, notes: "list[str] | None" = None, faults: "list[str] | tuple" = ()) -> str:
    """The title of one round of OK-WW patch notes.

    `faults` are notes the caller already knows are failures (okww_overlay.OverlayTrouble:
    the overrides or their master pointer are not in place); they count as such
    whatever their words. The other notes are judged by _PATCH_TROUBLE.
    """
    bad = len(faults) + sum(1 for x in (notes or [])
                            if x not in faults and any(k in x for k in _PATCH_TROUBLE))
    if bad:
        return f"⚠️ OK-WW 补丁有 {bad} 条没贴上（共 {n} 条）"
    return f"🩹 OK-WW 补丁（{n} 条）"


def unconfirmed(what: str, n: int) -> str:
    """How many items the pre-update / game update could not confirm."""
    return f"⚠️ {what}没能确认（{n} 项）"


def failed(script: str) -> str:
    return f"❌ {script} 失败"


def unresolved(game: str, shift: str) -> str:
    """A MAA / MaaEnd shift that failed and that the make-up did not fix (unresolved.py)."""
    return f"❌ {game}{shift}没跑成"


def unresolved_undone(game: str, shift: str) -> str:
    """A MAA / MaaEnd shift that ended with work left undone (unresolved.py)."""
    return f"⚠️ {game}{shift}没干完"


# outcome.summarize's head when a new version reset the user's settings and the run
# went by the defaults: the work was done, so it is not 「没干成」.
OUTCOME_SETTINGS_HEAD = "这一轮没按你的设置跑（新版本把设置重置成了默认值）："


def outcome_settings_only(msg: str) -> bool:
    """An outcome summary that says only that settings were reset, nothing left undone."""
    first = (msg or "").split("\n", 1)[0]
    return first.endswith(OUTCOME_SETTINGS_HEAD) and not first.startswith("另外")


# MaaEnd's essence farming in target mode ends with 「勾选武器的基质均已满足，结束任务」
# when the ticked weapons' essences are already owned (upstream plan_action.go
# "all targets satisfied"): nothing farmed, no sanity spent, not a fault.
# outcome.summarize names it on its own line; the daily report has one note.
OUTCOME_ESSENCE_MET_HEAD = "勾选的武器基质已经齐了、没刷："
ESSENCE_TARGET_MET = "基质刷取：勾选的武器要的基质都已经有了，这趟没刷、没花理智；可以换一把要刷的武器勾上"
ESSENCE_TARGET_MET_AFTER_FARM = "基质刷取：勾选的武器要的基质这趟刷齐了；可以换一把要刷的武器勾上"
ESSENCE_FILLER_SWITCHED = "🎯 终末地基质刷取已切刷垫子"


def essence_filler_on(names: list[str]) -> str:
    """essence.step switched 基质刷取 to filler mode after a target-met run (daily report, once)."""
    who = "和".join(names) if names else "勾选的武器"
    return f"基质刷取：{who}的基质都齐了，已切成随机地区刷垫子，刻写券关了"


def essence_filler_friend_body(names: list[str]) -> str:
    """Friend WeChat notice body when essence.step switches target mode back to filler mode."""
    clean = [str(w).strip() for w in names if str(w).strip()]
    who = f"「{'、'.join(clean)}」" if clean else ""
    return (f"终末地目标武器{who}基质已刷齐，已切回随机地区刷垫子，刻写券已关闭。\n"
            "可按需勾选下一把要刷的目标武器。")


# essence.step could not switch to filler mode (a group alarm).
ESSENCE_FILLER_FAILED = "⚠️ 基质刷取没能切成刷垫子"


def essence_filler_failed(why: str) -> str:
    return (f"勾选的武器基质都齐了，要把基质刷取切成随机地区刷垫子、关掉刻写券，但没改成：{why}。"
            "下次照旧按目标选择跑（会直接结束、不花理智）；已交给我们这边去改")


def unresolved_settings(game: str, shift: str) -> str:
    """A MaaEnd shift that did its work, but by the defaults: a new version reset the
    user's settings (outcome.settings_only)."""
    return f"⚠️ {game}{shift}没按你的设置跑"


def unresolved_head(game: str, shift: str, makeup: str, stuck: str, page: str) -> str:
    """The alarm's first line: the game, the shift, what came of the make-up, where it
    failed and the evidence link (see samples() for the copy)."""
    head = f"{game}{shift}没跑成，{makeup}"
    if stuck:
        head += ("；" if "：" in makeup else "：") + f"卡在 {stuck}"
    if page:
        head += f"（证据包 {page}）"
    return head + "\n"


NO_WHOLE_MAKEUP = "这一类不整轮补跑"


def collect_retry_ahead(labels: list[str], state: str = "ahead") -> str:
    """The clause after NO_WHOLE_MAKEUP: which routes, and whether the per-route retry is
    still to come (collect_retry.retry_ahead's answer)."""
    routes = "没走通的路线（" + "、".join(labels) + "）"
    if state == "debug":
        return routes + "要到中继关机前才单独补一次；现在调试模式开着、中继不关机，所以还没有补"
    if state == "spent":
        return routes + "不再补：今天单独补路线的那一次已经用过"
    return routes + "中继会在关机前单独补一次，补的结果另报"


def unresolved_undone_head(game: str, shift: str, items: str, page: str, retry: str = "") -> str:
    """The first line of a 「没干完」 alarm; no make-up is run for these. `retry` is what
    is said in place of 「这一类不补跑」 when the gathering routes get their per-route retry."""
    head = f"{game}{shift}跑完了但没干完" + (f"：{items}" if items else "") + "，" + (retry or "这一类不补跑")
    if page:
        head += f"（证据包 {page}）"
    return head + "\n"


def unresolved_settings_head(game: str, shift: str, items: str, page: str) -> str:
    """The first line of a 「没按你的设置跑」 alarm; nothing is re-run for these."""
    head = f"{game}{shift}跑完了，但新版本把设置重置成了默认值" + (f"：{items}" if items else "") + "，这一类不补跑"
    if page:
        head += f"（证据包 {page}）"
    return head + "\n"


def unverified_alarm(game: str, shift: str, n: int) -> str:
    """Items the program called done with no game evidence, once the round is over
    (handle._push_unverified)."""
    return f"⚠️ {game}{shift} {n} 项没证据，不算完成"


# Why a MaaEnd item does not count (maaend_unverified_why): the four tasks judged from
# MaaEnd's own record (maaend_fwlog.TRAIL_TASKS), and the rest, judged by a log line.
_END_TRAIL_WHY = "终末地自己的记录里看不到做成或没东西可做"
_END_LINE_WHY = "日志里没有游戏回显"


def maaend_unverified_why(trail_items: list, line_items: list) -> str:
    """Why MaaEnd's 「没证据」 items do not count (pushes._push_unverified): the ones of
    the four by MaaEnd's own record, the others by their log line; each part named
    when both kinds are on the list."""
    if trail_items and line_items:
        return (f"{'、'.join(trail_items)} 在{_END_TRAIL_WHY}，"
                f"{'、'.join(line_items)} 的{_END_LINE_WHY}")
    return _END_TRAIL_WHY if trail_items else _END_LINE_WHY


def trail_unread_note(tasks: list, miss: int, fail_at: int) -> str:
    """The daily-report note for MaaEnd tasks left unjudged because MaaEnd's own record
    (its framework log) held none of them (core.maaend_unjudged)."""
    return (f"终末地自己的记录这一趟没读到（连续第 {miss} 趟），{'、'.join(tasks)} 先不判："
            f"不算做成，也不报没证据；连续 {fail_at} 趟都读不到才报到群里")


# How a later retry did each of a failed run's tasks (core.retried_notes).
RETRY_DONE = "做成了"
RETRY_BARE = "程序说做完了，但没证据，不算完成"
RETRY_UNREAD = "终末地自己的记录没读到，先不判"


def retry_outcome(tasks: list, when: str, done: list, bare: list, unread: list) -> str:
    """The daily report's note on a failed run whose `tasks` a later retry (started
    `when`, 「10:35（东京 11:35）开始的」) went on to do: one wording when they all
    fared alike, else each kind with its tasks - done, done without evidence from the
    game, and not judged because MaaEnd's own record did not cover them."""
    head = f"{'、'.join(tasks)}　后来在 {when}那趟重试里"
    kinds = [(xs, w) for xs, w in ((done, RETRY_DONE), (bare, RETRY_BARE), (unread, RETRY_UNREAD)) if xs]
    if len(kinds) <= 1:
        return head + (kinds[0][1] if kinds else RETRY_DONE)
    return head + "：" + "；".join(f"{'、'.join(xs)} {w}" for xs, w in kinds)


def unverified_trail_lines(pairs: list) -> str:
    """For the 「没证据」 alarm (pushes._push_unverified): what MaaEnd's own record shows
    for each of the four tasks on it, [(task, what it shows)], one line each; '' for none."""
    return "".join(f"· {t}：{why}\n" for t, why in pairs if why)


def unverified_alarm_head(game: str, shift: str, items: str, why: str, page: str) -> str:
    """The first line of that alarm: which items, and why they do not count."""
    head = (f"{game}{shift}：{items} 程序说做完了，但游戏里拿不出证据"
            f"（{why}），不算完成，已交给我们这边去查")
    if page:
        head += f"（证据包 {page}）"
    return head + "\n"


def self_healed(script: str) -> str:
    """运行中途失败后经重试成功时的群告警标题（报错一律推群，绝不进日报）。"""
    return f"⚠️ {script} 中途失败过，重试后成功"


def cant_enter(script: str) -> str:
    return f"⏸ {script} 进不了游戏，稍后补跑"


def is_cant_enter(title: str) -> bool:
    return title.startswith("⏸ ") and " 进不了游戏" in title


def healed_after_update(script: str) -> str:
    """更新重启后重跑成功时的日志标题（不推群、不进日报）。"""
    return f"⚠️ {script} 更新时失败过，重跑后成功"


def makeup_passed(game: str, shift: str) -> str:
    """运行失败后经自动补跑走通时的群告警标题（原故障仍需排查，推群不进日报）。"""
    return f"⚠️ {game}{shift}失败过，补跑后走通了"


MAA_SANITY_SHORT = "⚠️ 明日方舟理智不够，这一趟没打"
# MaaEnd restarted itself to install a new build after its shift's round was already
# done; AUTO-MAS booked that attempt as failed (handle._drop_update_after_done). Not
# pushed: relay.log and the daily report's ↪️ row.
MAAEND_UPDATE_AFTER_DONE = "⚠️ 终末地装新版重启了这一趟（前面那趟已做完）"


# Appended to the final alarm when a MaaEnd round had the "never got into the
# game" shape but no official maintenance or update notice backs it
# (handle._confirm_unreachable): it is alarmed on as a fault.
UNREACHABLE_SHAPE_NOTE = ("每个任务都在 30 秒内失败、一个没完成，看着像没进游戏；"
                          "但今天没有官方维护或更新公告，所以按故障报，已交给我们这边去查游戏窗口、分辨率、游戏有没有闪退。")
# The same shape when the maintenance windows or the update notice could not be
# read (records._confirm_unreachable: raw maaend_unreachable_unread).
UNREACHABLE_UNREAD_NOTE = ("每个任务都在 30 秒内失败、一个没完成，看着像没进游戏；"
                           "官方维护和更新公告这次没读到，分不清是不是在维护，所以按故障报，"
                           "已交给我们这边去查游戏窗口、分辨率、游戏有没有闪退。")


# A run a person started at AUTO-MAS itself (trigger.py): alarmed like any
# other, with this line so the reader knows whose run it was.
HAND_STARTED_NOTE = "这一趟是有人在 AUTO-MAS 上手动开的，不是定时开的。"


def hand_fixed_note(hhmm: str) -> str:
    """On a held failure a person's own run got past: not 「自己好了」, so it is still
    reported (handle._hand_started_alarm)."""
    return f"后来 {hhmm} 有人在 AUTO-MAS 上手动开了一趟，跑成了；这次失败不是自己好的，照报。"


# A MAA failure on a day with a registered Arknights version update.
UPDATE_DAY_NOTE = "今天登记了明日方舟的版本更新。"


def skland_multi_role_body(roles: list) -> str:
    """resources.skland_session: Skland listed several Endfield roles for the account."""
    ids = "、".join(str(r) for r in roles) or "（没给编号）"
    return (f"森空岛这次给了 {len(roles)} 个终末地角色（角色编号 {ids}），中继不知道该读哪一个，一个都没读。\n"
            "手机页上终末地的数字这次读不出来。已交给我们这边去查该读哪一个角色。")


def missing(what: str) -> str:
    return f"🔌 {what}"


def not_run(queue: str) -> str:
    return f"{queue} 没有运行"


def not_run_in(kind: str, queue: str) -> str:
    return f"{kind} 没有运行（{queue}）"


def stage_gate(queue: str) -> str:
    """The stage gate pulled MAA from one shift: the stage set is one MAA cannot navigate to (stagegate.py)."""
    return f"⚠️ 明日方舟{queue}没开跑：关卡走不到"


def stage_why(code: str, stage: str, chapter: str = "", hard: bool = False) -> str:
    """Why MAA cannot navigate to `stage`, per the reason codes of stagegate.navigable."""
    if code == "no_chapter":
        return f"它的关卡资料里没有第 {chapter} 章的导航"
    if code == "bad_difficulty":
        return f"MAA 不认 {stage} 的难度写法（第 10 章起才能加难度，而且只认普通、磨难两种）"
    if code == "no_difficulty":
        return f"它的关卡资料里没有切换到{'磨难' if hard else '普通'}难度的导航"
    if code == "no_reopen":
        return "它的关卡资料里没有这个活动复刻关的导航"
    return f"它的关卡资料里没有这一关的导航（resource/tasks 里找不到 {stage}）"


def stage_gate_warn(queue: str) -> str:
    """Before a shift, the stage set is one MAA cannot navigate to; MAA is left in the
    queue (stagegate.PULL_FROM_QUEUE off) and will refuse it itself."""
    return f"⚠️ 明日方舟{queue}开跑前核到关卡走不到"


def stage_gate_warn_body(queue: str, stage: str, why: str) -> str:
    return (f"明日方舟{queue}开跑前核到关卡 {stage} MAA 走不到（{why}）。MAA 照跑，会被它拒掉；"
            "换一关，或等 MAA 更新关卡资料。")


def stage_refused(stage: str, why: str) -> str:
    """An order setting a stage MAA cannot navigate to, refused before anything is saved.
    The phone shows exactly 「MAA 走不到，修改失败」 first."""
    return f"MAA 走不到，修改失败：关卡 {stage}，{why}"


def stage_gate_body(stage: str, why: str, pulled: "bool | None") -> str:
    """pulled: True taken out of this shift, False could not be, None was not in it any more."""
    if pulled is None:
        return (f"关卡 {stage} MAA 走不到（{why}）。这一班的队列里本来就没有 MAA，下一班还会是这一关。"
                "换一关，或等 MAA 更新关卡资料。")
    if pulled:
        return (f"明日方舟这一班没开跑：关卡 {stage} MAA 走不到（{why}）。换一关，或等 MAA 更新关卡资料。"
                "这一班中继先把 MAA 从队列里拿掉，班次过后放回去。")
    return (f"关卡 {stage} MAA 走不到（{why}）。中继没能把 MAA 从这一班的队列里拿掉（原文已记日志），"
            "到点 MAA 会一开始就停下，这一班什么都不做。换一关，或等 MAA 更新关卡资料。")


def stage_gate_report(rows: list) -> str:
    """The daily report's lines for the shifts the stage gate stopped: rows of (queue, stage, why)."""
    if not rows:
        return ""
    return "关卡走不到、没开跑的班次\n" + "\n".join(
        f"· 明日方舟{q}：关卡 {stage} MAA 走不到（{why}）" for q, stage, why in rows)


# ---------------- bodies ----------------
def restart_was_last(result: str, at: str) -> str:
    """Line in a final alarm whose held record is an attempt AUTO-MAS recorded as a
    restart (collector._TRANSITIONAL) with no record of the script after it
    (handle._restart_note): what AUTO-MAS wrote and when the attempt began."""
    said = f"「{result}」" if result else "（没写结果）"
    return (f"{at} 开始的这一次，AUTO-MAS 记的结果是{said}，这种记录平常紧跟着会重来一次；"
            "这次之后没有再跑出一次记录。\n")


def maa_sanity_short_body(have, cost, at: str, booked_ok: bool = False) -> str:
    """Body of MAA_SANITY_SHORT (outcome.maa_sanity_short read both numbers off MAA's log).
    booked_ok: an Annihilation pass AUTO-MAS booked 「Success!」 all the same (handle._say_annihilation_short)."""
    if booked_ok:
        return (f"{at} 开始的这一趟剿灭：MAA 读到理智 {have}，剿灭一次要 {cost}，一次都没打就停了，"
                "AUTO-MAS 却把这一趟记成成功。")
    return (f"{at} 开始的这一趟：MAA 读到理智 {have}，要打的关一次要 {cost}，一次都没打就停了，"
            "AUTO-MAS 把这一趟记成失败。")


# ---- MAA refused its own config / fought nothing / never read sanity (collector_maa) ----
# What MAA's own words in gui.log / asst.log mean, keyed by the words matched there.
MAA_REJECT_WHY = {"序列化失败": "序列化失败", "添加任务失败": "添加任务失败",
                  "Cannot set stage": "关卡设不进去", "invalid params": "参数不被接受"}
# MAA's result JSON said 0 sanity with no refill time: it never read sanity that round.
SANITY_UNREAD = "理智没读到"
NO_FIGHT = "这一趟一仗都没打"
# MAA's Annihilation@UnableToAgent: the annihilation map's auto-deploy is locked (a new
# map is, until it is cleared once by hand with all 400 kills), so MAA cannot run it.
ANNIHILATION_NO_PROXY = "这张剿灭图的「代理指挥」没解锁，MAA 代理不了：要先手动打一次（满 400 杀）"


def maa_config_rejected(task: str, why: str, stage: str) -> str:
    """「理智作战 序列化失败，关卡 YW-4」: the task MAA would not take, MAA's own reason
    (MAA_REJECT_WHY) and the stage when the task is the fight."""
    return (f"{task} " if task else "") + why + (f"，关卡 {stage}" if stage else "")


def maa_rejected_line(what: str) -> str:
    """The failure alarm's line for a run whose config MAA refused (core.format_failure)."""
    return f"MAA 不接受这份配置：{what}"


def makeup_config_rejected(what: str) -> str:
    """Why a whole-MAA make-up is not run when MAA refused the config (makeup.maa_work_done)."""
    return f"MAA 不接受这份配置（{what}），原样补跑还是一样"


def makeup_no_fight(failed: str) -> str:
    """Why no make-up when the failure is not a start-up one but the log shows no fight."""
    return f"失败的不只是开始唤醒或连模拟器（{failed}），日志里这一轮一仗都没打"


RUN_LIMIT_RESET = "终末地失败重试上限已改回 1"
RUN_LIMIT_STUCK = "⚠️ 终末地失败重试上限改不回 1"


def run_limit_reset_body(game: str, cur, want) -> str:
    return (f"{game}在 AUTO-MAS 里的「失败重试上限」变成了 {cur}（AUTO-MAS 升级、或者有人在它界面上改过），"
            f"中继已经改回 {want}：失败时不再让它自己白跑几遍，缺什么由中继判断只补缺的")


def run_limit_stuck_body(game: str, cur, want, why: str) -> str:
    return (f"{game}在 AUTO-MAS 里的「失败重试上限」是 {cur}，中继连着 3 次没改回 {want}：{why}。"
            f"不改回来，{game}一失败 AUTO-MAS 会自己连跑几遍；已交给我们这边去查")


MAKEUP_STOPPED_PHRASE = "补跑被红按钮（停一切）停掉了，没再补"
AUTOMAS_MANUAL_STOP = "任务被用户手动停止"
MAKEUP_ONLY_GATHERING_MARK = "除了自动采集，别的都干完了"


def makeup_only_gathering(at: str) -> str:
    """Why no whole MaaEnd make-up: one attempt of the round did everything but gathering
    (makeup.maaend_round_only_gathering); `at` is that attempt's start, 「10:24」."""
    when = f"{at} 那一遍" if at else "这一轮有一遍"
    return (f"{when}{MAKEUP_ONLY_GATHERING_MARK}，整轮再跑只会把干完的再做一遍；"
            "没走通的采集路线关机前单独补")


def makeup_unsure(failed: str) -> str:
    """Why no make-up when the failure is not a start-up one and the log was not read."""
    return f"失败的不只是开始唤醒或连模拟器（{failed}），拿不准有没有打过仗"


def update_rerun_refused(script: str, why: str) -> str:
    """gameupdate._rerun_script: the client is updated, but the round rule refused
    the whole-round re-run. A GAME_UPDATE note (info route only, not the group). `why`
    is makeup.maa_round_work_done's reason."""
    return f"{script}：客户端更新好了，这一轮不再整轮补跑：{why}"


# What to do about a failure whose cause is known (collector_maaend
# _maaend_fail_causes). Said plainly instead of asking the model to guess.
_CAUSE_ADVICE = {
    "背包满了": "背包满了，领到的奖励放不下。清出背包空间后再跑。",
}


# An essence claim that failed with no storage-full notice is an ordinary failure; the
# raw MaaEnd lines around it go with the failure text (core.format_failure,
# collector_maaend.claim_lines). These are the headings over them.
CLAIM_LINES_RUN = "终末地日志原文，从点确认领取到任务失败："
CLAIM_LINES_FW = "同一段时间的终末地框架日志："


def claim_lines_fw_none(why: str) -> str:
    return f"同一段时间的终末地框架日志：没读到（{why}）"


def claim_lines_skipped(n: int) -> str:
    return f"……（中间 {n} 行没贴）……"


def claim_lines_head(task: str) -> str:
    return f"{task}：点了确认领取之后任务失败，没看到仓储已满的提示。"


_SPMED_WHY = {
    "broken": "用加强剂时点确认的那段，还是九月初那种点不到确认按钮的写法",
    "unknown": "用加强剂时点确认的那段换了写法，和中继认得的写法不一样",
    "missing": "用加强剂时点确认的那段改了名字或被拿掉了，中继找不到它",
    "unreadable": "中继读不到终末地 MaaEnd 里记着各段做法的那个文件",
}


def spmed_unrecognised_body(shape: str) -> str:
    """gameupdate.spmed_check's alarm, sent at every boot that sees it."""
    return (f"终末地 MaaEnd 里，{_SPMED_WHY.get(shape, _SPMED_WHY['unknown'])}，"
            "中继没法确认加强剂还能不能用上。应急理智加强剂一直开着，中继不会关它。"
            "已交给我们这边去认这种写法，并核对终末地下一次跑完有没有用掉加强剂；中继每次开机都会再查，认不出就再报。")


def known_cause(causes: dict) -> str:
    """「基质刷取：背包满了，…」 for each failure with a known cause; "" if none. A
    CLAIM_UNCONFIRMED cause (older ledger lines) says nothing."""
    from ark_relay.features.collector_maaend import CLAIM_UNCONFIRMED  # noqa: PLC0415
    return "\n".join(f"{name}：{_CAUSE_ADVICE.get(c, c)}" for name, c in (causes or {}).items()
                     if c != CLAIM_UNCONFIRMED)


def failed_body_head(attempts: int) -> str:
    return f"重试 {attempts} 次全部失败，已交给我们这边去查。\n" if attempts > 1 else "已交给我们这边去查。\n"


# An action id must never reach a push as it is: `set_config` is written for
# the program, and 「set_config」現在不能执行 answers nothing.
_ACTION_ZH = {
    "set_stage": "改关卡",
    "set_medicine": "改吃几瓶理智药",
    "set_wait_time": "改等待时间",
    "toggle_task": "开关某个任务",
    "run_now": "现在就跑一趟",
    "skip_today": "今天这趟跳过",
    "unskip_today": "取消今天的跳过",
    "debug_mode": "调试模式",
    "alarm_hold": "故障留机锁",
    "set_config": "改设置",
    "set_master": "改设置",
    "weekly_boss": "改打第几个周本",
    "skip_shutdown": "下次跑完不关机",
    "echo_farm": "开始刷声骸",
    "echo_farm_until": "改刷声骸的收工时刻",
    "echo_farm_stop": "刷声骸提前收工",
    "tacet_shots": "无音区结算截图",
    "monthcard": "登记月卡",
    "estop": "停止一切",
    "refresh": "刷新状态",
    "watch": "打开实时状态",
    "queue": "改队列",
    "sanity_plan": "改理智安排",
}


def action_name(action: str) -> str:
    return _ACTION_ZH.get(action, "这条设置")


# commands.apply_command's two gate refusals; they reach the group as the body of
# 「配置没改成」, so they name the action in words, never by its id.
def action_not_allowed(action: str) -> str:
    return f"「{action_name(action)}」不在允许的清单里，已拒绝"


def action_needs_confirm(action: str) -> str:
    return f"「{action_name(action)}」需要人工确认，未确认前不执行"


# D207: the receipt written the moment an order is queued behind a running script.
PHONE_QUEUED = "排队中，这一趟跑完执行"


def phone_busy_reason(action: str) -> str:
    """Why an order that starts a run was not carried out while a run was going."""
    if action == "run_now":
        return "这时正在跑，这一趟就是"
    return "这时正在跑，跑完不会接着开；要的话等跑完再发一次"


def makeup_restore_failed_body(master: str, record: str) -> str:
    return ("终末地设置被临时改过，自动改回失败，已交给我们这边去改回。\n"
            f"终末地设置文件：{master}\n"
            f"临时改动前的开关记录（读不出来）：{record}\n"
            "我们这边改好后会删掉这份记录，补跑才会再用；在那之前补跑不再改终末地的设置。")


def rerun_body(reran: list[str]) -> str:
    return "、".join(reran) + " 已单独开跑"


# Logger name -> what that part of the relay is called in a notification.
_RELAY_PARTS = {
    "ark.service": "主程序", "ark.engine": "核心", "ark.handle": "记账与告警", "ark.report": "日报",
    "ark.shutdown": "关机判定", "ark.missed": "漏跑核对", "ark.preupdate": "预更新", "ark.gameupdate": "游戏更新",
    "ark.efstart": "经官方启动器开终末地", "ark.efstart_setup": "终末地开游戏方式设置",
    "ark.maaend_launch": "终末地开成窗口的设置核对",
    "ark.selfupdate": "自更新", "ark.phone": "手机通道", "ark.evidence": "证据外送", "ark.collect_watch": "采集看守", "ark.display_wake": "开终末地时叫醒屏幕",
    "ark.collect_retry": "采集补跑", "ark.inbox": "待办信箱", "ark.snapshot": "状态快照", "ark.notify": "推送", "ark.netretry": "联网重试",
    "ark.banners": "卡池信息", "ark.needtable": "库存需求表", "ark.essence": "基质刷取切刷垫子", "ark.desktop": "桌面读屏", "ark.alertlog": "报警抄送",
    # Every WARNING reaches the group (errwatch), so these are named too.
    "ark.annihilation": "剿灭开关", "ark.garden": "周常乐园开关", "ark.weeklyboss": "周本开关",
    "ark.unresolved": "没处理好的报警", "ark.runwatch": "在跑巡查", "ark.trigger": "认手动开的趟",
    "ark.resources": "手机页的数字", "ark.skland": "森空岛", "ark.config": "读设置", "ark.makeup": "补跑", "ark.activity": "鸣潮活跃晚班补", "ark.core": "记账",
    "ark.collector": "读运行记录", "ark.collector_maaend": "终末地日志解析", "ark.selfcheck": "开机自检", "ark.maaend_watchdog": "终末地看门狗", "ark.maa_start_watchdog": "明日方舟开游戏看门狗",
    "ark.commands": "执行命令", "ark.task_shots": "任务截图", "ark.statestore": "状态档案",
    "ark.monthcard": "月卡提醒", "ark.echofarm": "刷声骸", "ark.maintenance": "停服维护公告",
    "ark.okww_overlay": "鸣潮补丁", "ark.mastercfg": "脚本设置",
    "ark.maaend": "终末地设置", "ark.queues": "队列设置", "ark.modes": "跳过开关", "ark.hardlock": "硬锁", "ark.plan": "排期",
    "ark.sanity_plan": "理智安排", "ark.summary": "文字撰写", "ark.watch": "盯运行记录目录",
    "ark.procs": "程序列表", "ark.tape": "回放用的输入记录",
    "ark": "主程序", "ark.errwatch": "报错转发", "ark.error_evidence": "当天日志外送",
    "ark.gamelog_errors": "游戏日志报错核对", "ark.outcome": "核对干没干成", "ark.logfile": "中继日志文件", "ark.machinecheck": "机器上的核对",
    "ark.runs": "按每趟记录做的机器上核对", "ark.system": "中继自身的机器上核对",
    "ark.macpush": "报警直送", "ark.phone_banners": "手机通道和卡池核对", "ark.shiftcheck": "收工体检",
    "ark.stagegate": "关卡能不能去的检查", "ark.techlog": "技术日志", "ark.weekgate": "鸣潮周常开关",
    "ark.procwatch": "关机防护", "ark.ak_activity": "明日方舟活动提醒", "ark.friend_events": "好友微信提醒",
}


def relay_part(where: str) -> str:
    """The plain name of the part of the relay a logger name stands for."""
    return _RELAY_PARTS.get(where, "一个不常见的部分")


# The AUTO-MAS settings the relay reads (ark_relay/core/mascontract.py CONTRACT), by feature:
# what the setting is, and what goes wrong while the relay cannot read it.
MAS_SETTING_WHAT = {
    "script_path": "各个脚本的安装位置",
    "script_name": "各个脚本的名字",
    "client_update": "明日方舟、鸣潮客户端自动更新的开关",
    "maaend_wait": "终末地的等待秒数",
    "maaend_launch": "终末地的游戏位置和开游戏方式",
    "maaend_window": "终末地跑脚本时开成窗口、跑完改回全屏的设置",
    "maaend_update": "终末地脚本开跑前更新的接管和通道设置",
    "stage": "方舟的关卡设置",
    "medicine": "方舟的理智药数量",
    "fight": "方舟的刷理智开关",
    "annihilation": "方舟的剿灭设置",
    "activity": "方舟的活动关设置",
    "maaend_phone": "终末地的理智用途和基质设置",
    "okww_quick": "鸣潮的快速配置",
    "queue_timer": "队列的定时设置",
    "queue_after": "队列跑完后做什么",
    "queue_startup": "调度程序一打开就跑队列的设置",
    "queue_items": "队列里排了哪些游戏、哪几天跑",
    "plan_table": "方舟的关卡计划表",
}
MAS_SETTING_BREAKS = {
    "script_path": "中继认不出哪个是方舟、终末地、鸣潮，开跑前查关卡、补跑、关机前等游戏跑完",
    "script_name": "手机上方舟的设置、剿灭开关和明日安排里鸣潮那几行",
    "client_update": "开机自检判断游戏出新版时有没有人更新客户端",
    "maaend_wait": "手机上改终末地的等待秒数",
    "maaend_launch": "开机时核对调度程序能不能经官方启动器开终末地",
    "maaend_window": "跑终末地前把游戏开成窗口（不勾 DirectX 11 时 MaaEnd 靠它认游戏画面）、跑完改回全屏",
    "maaend_update": "开机自检核对调度程序是不是在开跑前自动更新终末地脚本",
    "stage": "开跑前查关卡、明日安排、手机上显示和修改关卡",
    "medicine": "明日安排和手机上显示、修改理智药",
    "fight": "开跑前查关卡和明日安排",
    "annihilation": "明日安排里的剿灭、每周剿灭打没打满、手机上的剿灭开关",
    "activity": "手机上显示的活动关设置",
    "maaend_phone": "手机上显示和修改终末地的这几项",
    "okww_quick": "明日安排里鸣潮刷什么",
    "queue_timer": "排班：开跑前查关卡、超时报警、关机前等队列跑完、漏跑核对、明日安排、手机上的跳过",
    "queue_after": "明日安排里「跑完自动关机」那一行",
    "queue_startup": "手机上的「开机就跑」",
    "queue_items": "中继不知道每班跑哪些游戏，游戏更新日、关卡走不到时跳过当天那一项",
    "plan_table": "按计划表打关时，开跑前查关卡和明日安排",
}
# The AUTO-MAS setting groups by the column they are shown in.
MAS_GROUP_ZH = {"Info": "基本信息", "Stage": "关卡", "Task": "任务", "Data": "数据",
                "Run": "运行", "Game": "游戏", "Update": "更新", "Schedule": "日程", "ALL": "计划表全周"}
MAS_FILE_ZH = {"ScriptConfig.json": "脚本设置", "QueueConfig.json": "队列设置",
               "PlanConfig.json": "关卡计划表", "config": "设置文件夹"}
MAS_CONTRACT_CHECK = "中继要读的调度程序设置都在原处"


def mas_contract_lines(missing) -> list[str]:
    """One line per feature for the mascontract.Item list `missing`: which setting the relay
    can no longer read, in which column it is not found, and what goes wrong."""
    by_use: dict = {}
    for it in missing:
        cols = by_use.setdefault(it.use, [])
        col = MAS_GROUP_ZH.get(it.group, "另一")
        if col not in cols:
            cols.append(col)
    return [f"中继读不到{MAS_SETTING_WHAT.get(use, '一项设置')}（{'、'.join(c + '一栏' for c in cols)}里找不到），"
            f"{MAS_SETTING_BREAKS.get(use, '用到它的地方')}都不对了" for use, cols in by_use.items()]


def mas_contract_detail(result) -> str:
    """The self-check line's detail for a mascontract.Result."""
    parts = mas_contract_lines(result.missing)
    if result.unreadable:
        parts.append("读不到调度程序的" + "、".join(MAS_FILE_ZH.get(f, "设置") for f in result.unreadable))
    return "；".join(parts)


def automas_contract_body(version: str, lines: list[str]) -> str:
    """The alarm right after the pre-update installed a new AUTO-MAS (selfcheck.report_contract)."""
    body = "\n".join(f"· {x}" for x in lines)
    return (f"中继刚把调度程序（AUTO-MAS）升级到 {version}，升级后：\n{body}\n"
            "调度程序照常跑，读不到的这几处中继会当成没设。已交给我们这边去修。")


def selfcheck_failed_body(total: int, bad: list) -> str:
    """`bad` is [(name, detail)] of the checks that did not hold. Not every check stops
    the shift (some only slow the watchdog down), so the consequence is given per weight."""
    lines = "\n".join(f"· {n}" + (f"：{d}" if d else "") for n, d in bad)
    return (f"开机自检 {total} 项里有 {len(bad)} 项不成立：\n{lines}\n"
            "后果看是哪一项：重的会让这一班跑不了，轻的只是中继发现问题慢一些、或者看不见。已交给我们这边去修。")


# ---------- after-shift check (selfcheck/shiftcheck.py) ----------
# One relay.log INFO line per finished morning / evening shift; selfcheck.daily_lines
# quotes it in the daily report's 「中继体检」 section. Never pushed.
SHIFTCHECK_HEAD = "收工体检（"
SHIFTCHECK_ANNIHILATION = "明日方舟剿灭开关"
SHIFTCHECK_ANNIHILATION_UNREAD = "剿灭开关读不到"
SHIFTCHECK_SKIP = "「下次跑完不关机」"
# Read before the shutdown step spends the mark, so it is this shift's power-off it skips.
SHIFTCHECK_SKIP_ON = "这趟跑完时标记还没用上：这一趟跑完不关机，开到下一趟早班/晚班跑完才关"
SHIFTCHECK_DEBUG = "调试模式"
SHIFTCHECK_TEST_WINDOW = "测试窗口"


def shiftcheck_debug_on(until: str) -> str:
    return f"开着，到 {until}，这期间跑完不关机"


def shiftcheck_test_window_on(since: str) -> str:
    return f"{since or '时刻没记'} 起开着，这期间跑的记录不进日报正文"


def shiftcheck_summary(shift: str, total: int, bad: list, unread: list, notes: list = ()) -> str:
    """The one line for a shift. `bad` / `unread` are [(item, what was found)] of the
    items that did not hold / could not be judged; `notes` the owner's own switches
    found on (they hold, and are said as a note, not as 「不对」)."""
    head = f"{SHIFTCHECK_HEAD}{shift}）{total} 项"
    tail = ("；你自己开着的：" + "；".join(f"{n}：{d.rstrip('。')}" for n, d in notes)) if notes else ""
    if not bad and not unread:
        return head + "都对" + tail
    # The details are whole sentences elsewhere (annihilation_off_body); joined with 「；」 here.
    parts = [f"{n}：{d.rstrip('。')}" if d else n for n, d in bad]
    parts += [f"{n}：判不了，{d.rstrip('。')}" if d else f"{n}：判不了" for n, d in unread]
    return head + f"里 {len(bad)} 项不对、{len(unread)} 项判不了：" + "；".join(parts) + tail


def shiftcheck_broken(shift: str) -> str:
    return f"{SHIFTCHECK_HEAD}{shift}）这一趟没查完：体检程序自己坏了，原因写在中继日志里"


# What OK-WW's 「can not battle pass, maybe ended」 means (DailyTask.claim_battle_pass:
# no level digits read on the battle-pass page, the claim is skipped, the run goes on).
OKWW_BATTLE_PASS_UNCLAIMED = "战令奖励这次没领（战令页上没读到等级数字：这期战令已经结束，或者页面没打开）"
# The battle-pass item of 「⚠️ 这一轮没干完」 (outcome.battle_pass_checks), from the
# overlay's lines (ark_overrides.tasks.py BATTLE_PASS_*). The overlay opens the page a
# second time in the same run before it gives up; the claim clicks themselves are not
# checked, so the green label says the buttons were pressed, not that points arrived.
OKWW_BATTLE_PASS_LABEL = "战令（先约电台）点了领取"
OKWW_BATTLE_PASS_FAILED = "同一趟里重开了一次，战令页还是没打开，今天的战令点数没领到"
OKWW_BATTLE_PASS_RETRIED = "第一次没打开，同一趟里重开一次领了"
OKWW_BATTLE_PASS_UNCHECKED = "OK-WW 领战令的写法变了，这次照它原样领，没打开时不会重试"
OKWW_BATTLE_PASS_CLOSED = "战令（先约电台）这期已结束、下期还没开播，没有可领的"


RELAY_ERROR_TAIL = "已交给我们这边去修。"


def relay_error_body(where: str, what: str, at: str = "", fault: dict | None = None) -> str:
    """单条中继报错推群正文：`fault` 为源头活异常提取的结构化字典，缺省时兼容旧文本分类。"""
    return f"中继自己报错了{'（' + at + '）' if at else ''}，出在「{relay_part(where)}」。{_said(what, fault=fault)}\n" + RELAY_ERROR_TAIL


def relay_error_line(where: str, what: str, at: str, fixed_in: str = "", fixed_what: str = "",
                     fault: dict | None = None) -> str:
    """合包推送里的单条报错行：发生时间、模块名、复发标记与白话原因。"""
    again = (f"，v{fixed_in} 修过的又出现了" + (f"（当时修的是：{fixed_what}）" if fixed_what else "")) if fixed_in else ""
    return f"· {at}，出在「{relay_part(where)}」{again}。{_said(what, fault=fault)}"


def relay_errors_merged(title: str, n: int) -> str:
    """Title of one push carrying `n` records that waited together (errwatch.merge)."""
    return f"{title}（{n} 条）"


def evidence_link(url: str, at: str, truncated: bool = False) -> str:
    """The tail of a relay-error push: where today's relay.log is, readable with the
    machine off (error_evidence.py)."""
    note = "（当天日志过大，只传了最后一部分）" if truncated else ""
    return f"日志：{url}，出事时刻 {at}{note}"


# The tail of a relay-error push when today's relay.log did not reach COS: said in the
# same message (not a second one), the reasons stay in relay.log.
def gamelog_unknown_errors(game: str) -> str:
    """Title: a round booked as a success whose own log holds ERROR lines nobody has
    looked at yet (features/verify/gamelog_errors.py)."""
    return f"⚠️ {game}日志里有没查清的报错"


def gamelog_unknown_errors_body(game: str, at: str, kinds: int) -> str:
    when = f"{at} 开始的那一趟" if at else "这一趟"
    return (f"{game}{when}跑完了，结果记的是成功，但它自己的日志里有 {kinds} 种报错不在我们查清过的清单里，"
            "要查的是有没有哪一项其实没干成。我们这边已经收到，照着那一趟的日志查，查清了就修或者登记。")


# errwatch: the queue of group alarms saved before a restart could not be read back.
LOST_ALARM_QUEUE = "中继重启前还排着没送出去的群报警，这次开机读不出来，那几条丢了。我们这边照着机器上的中继日志查是哪几条。"
EVIDENCE_UPLOAD_FAILED = "当天日志这次没传上去，原因记在机器上的中继日志里，我们这边照着查。"


# ==============================================================================
# 源头结构化故障分类（ErrorCode）与封闭中文模板渲染
# 1. errwatch 源头直接读活异常对象属性（fault_from_exc），零文本猜测；
# 2. 旧队列/纯文本走简洁分类器（classify_fault），严格隔离 HTTP >= 400 与非零退出码；
# 3. 绝不做混合英文散文拆词缝合：仅「｜」左半段经轻度规整后 100% 过 plain() 才保留前缀。
# ==============================================================================

class ErrorCode(str, Enum):
    """标准故障分类代码：源头采集与文本分类共用同一套有限枚举。"""
    FILE_LOCKED = "file_locked"              # 文件被占用（WinError 32，高于无权限）
    PERMISSION_DENIED = "permission_denied"  # 无权限读写（PermissionError / Errno 13 / WinError 5）
    FILE_NOT_FOUND = "file_not_found"        # 找不到文件（FileNotFoundError / Errno 2 / WinError 2/3）
    HTTP_ERROR = "http_error"                # 服务器返回 RFC 合法错误状态码（>= 400）
    TIMEOUT = "timeout"                      # 连接或读写超时
    DNS_FAILED = "dns_failed"                # 域名解析失败
    CONN_RESET = "conn_reset"                # 对方拒连或中途断连
    SSL_ERROR = "ssl_error"                  # 加密连接或证书校验失败
    NET_ERROR = "net_error"                  # 网络请求未发出或未收到回答
    BAD_JSON = "bad_json"                    # 数据格式损坏、编码失败或压缩包损坏
    PROCESS_EXIT = "process_exit"            # 外部命令返回非零退出码
    KEY_ERROR = "key_error"                  # 读取数据缺少必要内容或属性缺失
    VALUE_ERROR = "value_error"              # 数据数值、类型或格式不对
    OS_ERROR = "os_error"                    # 本地文件或系统调用失败
    RUNTIME_ERROR = "runtime_error"          # 程序运行步骤执行失败
    UNKNOWN = "unknown"                      # 未归入上述类别的运行异常


@dataclass(frozen=True)
class FaultRecord:
    """结构化故障记录：供封闭中文模板确定性渲染。"""
    code: ErrorCode = ErrorCode.UNKNOWN
    http: int | None = None
    exit_code: int | str | None = None
    winerror: int | None = None
    errno: int | None = None
    hex_code: str = ""
    file_ref: str = ""


_FAULT_TEMPLATES: dict[ErrorCode, str] = {
    ErrorCode.FILE_LOCKED: "文件正被其他程序占用", ErrorCode.PERMISSION_DENIED: "没有权限读写要用的文件，或者文件正被其他程序占用",
    ErrorCode.FILE_NOT_FOUND: "找不到要用的文件", ErrorCode.HTTP_ERROR: "对方服务器返回了错误状态码",
    ErrorCode.TIMEOUT: "连接或读写超时", ErrorCode.DNS_FAILED: "域名解析失败，机器当时连不上网络",
    ErrorCode.CONN_RESET: "对方拒绝连接，或者连上后中途断开了", ErrorCode.SSL_ERROR: "加密连接没建立起来",
    ErrorCode.NET_ERROR: "网络请求没发出去，或者没收到回答", ErrorCode.BAD_JSON: "收到的数据格式是坏的",
    ErrorCode.PROCESS_EXIT: "外部命令执行失败", ErrorCode.KEY_ERROR: "读取数据时缺少必要内容",
    ErrorCode.VALUE_ERROR: "数据数值或格式不对", ErrorCode.OS_ERROR: "本地文件或系统操作失败",
    ErrorCode.RUNTIME_ERROR: "程序运行步骤执行失败", ErrorCode.UNKNOWN: "程序发生运行异常",
}
_ZH_PLAIN_MAP = (
    ("调度器", "调度程序"), ("标记文件", "状态记录"), ("时间窗", "时段"), ("任务链", "整套任务"), ("判定点", "核对项"), ("结构化", "按格式"), ("白名单", "允许清单"), ("凭空造", "自行编造"),
    ("落盘", "保存"), ("回读", "重读"), ("兜底", "备用方式"), ("字段", "内容项"), ("判据", "依据"), ("监听", "监测"), ("句柄", "连接号"), ("进程", "程序"), ("线程", "后台任务"), ("缓存", "本地记录"),
    ("重放", "重跑"), ("拉起", "启动"), ("收窄", "缩小范围"), ("节点", "步骤"), ("实例", "运行项"), ("退避", "延后重试"), ("死键", "无效项"), ("冲掉", "盖掉"), ("原子", "完整"), ("幂等", "防重复"),
    ("接口", "数据入口"), ("数据入口数据", "返回数据"), ("数据数据入口", "数据入口"), ("保存保存", "保存"),
    ("未知错误", "未识别故障"), ("这一步", "该环节"), ("有问题", "不正常"), ("出错", "失败"), ("不确定", "未能确认"), ("不一定", "未必"), ("约一", "一"),
    ("应该是", ""), ("差不多", ""), ("多半", ""), ("可能", ""), ("大概", ""), ("大约", ""), ("似乎", ""), ("疑似", ""), ("也许", ""), ("或许", ""), ("估计", ""), ("左右", ""), ("好像", ""), ("貌似", ""), ("大致", ""), ("约 ", ""),
)


class _FaultSpec:
    """故障分类器内部常量、正则与辅助方法（封在类内不混入对外文案常量扫描）。"""

    VALID_HTTP = frozenset({*range(400, 419), 421, 422, 423, 424, 425, 426, 428, 429, 431, 451, 499, *range(500, 509), 510, 511, *range(520, 528), 529, 530})
    HTTP_EXCS = frozenset({"HTTPError", "HTTPStatusError", "ClientResponseError"})
    FILE_CODES = frozenset({ErrorCode.FILE_LOCKED, ErrorCode.PERMISSION_DENIED, ErrorCode.FILE_NOT_FOUND, ErrorCode.OS_ERROR})
    MRO_PRE = ((ErrorCode.DNS_FAILED, {"gaierror", "NameResolutionError"}), (ErrorCode.TIMEOUT, {"TimeoutError", "TimeoutExpired", "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout"}), (ErrorCode.CONN_RESET, {"ConnectionResetError", "ConnectionRefusedError", "ConnectionAbortedError", "BrokenPipeError", "RemoteDisconnected", "IncompleteRead"}))
    MRO_POST = ((ErrorCode.PERMISSION_DENIED, {"PermissionError"}), (ErrorCode.FILE_NOT_FOUND, {"FileNotFoundError"}), (ErrorCode.BAD_JSON, {"JSONDecodeError", "UnicodeDecodeError", "UnicodeEncodeError", "BadZipFile"}), (ErrorCode.NET_ERROR, {"URLError", "ConnectionError", "ProxyError", "TooManyRedirects", "RequestException"}))
    MRO_TAIL = ((ErrorCode.KEY_ERROR, {"KeyError", "AttributeError"}), (ErrorCode.VALUE_ERROR, {"ValueError", "TypeError", "IndexError"}), (ErrorCode.OS_ERROR, {"OSError"}), (ErrorCode.RUNTIME_ERROR, {"RuntimeError", "StopIteration", "AssertionError"}))
    DATE_TIME_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|(?<!\d)\d{2}-\d{2}(?!\d)|\b\d{1,2}:\d{2}(?::\d{2})?\b")
    HTTP_RES = (re.compile(r"\bHTTP/\d(?:\.\d)?\s+(\d{3})\b|\bHTTP\s+(\d{3})\b|\bHTTP\s*Error\s*[:(]?\s*(\d{3})\b|\bHTTPStatusError\b[^\r\n]{0,60}?\b(\d{3})\b|\bClientResponseError\b[^\r\n]{0,40}?\b(\d{3})\b", re.I), re.compile(r"""\bstatus code does not indicate success\s*[:=]\s*(\d{3})\b|\breturned error\s*:\s*(\d{3})\b|(?<![A-Za-z0-9_-])["']?(?:status[_-]code|statusCode|http[_-]status|httpStatus)["']?\s*[:=]\s*(\d{3})\b|(?<![A-Za-z0-9_-])status\s+code\s*[:=]?\s*(\d{3})\b""", re.I))
    HTTP_BARE_RE, PROC_CTX_RE = re.compile(r"""(?<![A-Za-z0-9_-])["']?status["']?\s*[:=]\s*(\d{3})\b""", re.I), re.compile(r"\b(?:process|child|subprocess|waitpid|exited|exit|ended|taskkill|pwsh|powershell|git|ssh|adb|schtasks|CalledProcessError)\b", re.I)
    EXIT_RES = (re.compile(r"(?:退出码|返回码)\s*[:：=]?\s*(0x[0-9a-fA-F]+|-?\d+)(?!\.\d)|\b(?:CalledProcessError\s*\(|returned non-zero exit\s+status\s+)(0x[0-9a-fA-F]+|-?\d+)(?!\.\d)", re.I), re.compile(r"(?<![A-Za-z0-9_-])(?:(?:exit[\s_]+status|exit[\s_]+code|return[\s_]+code|returncode)\s*[:=\s]|rc\s*[:=]|(?-i:rc)\s+)\s*(0x[0-9a-fA-F]+|-?\d+)(?!\.\d)|(?<![A-Za-z0-9_-])(?:exit[-_]status|exit[-_]code|return[-_]code)-(\d+)(?!\.\d)|(?<![A-Za-z0-9_-])exited(?:\s+with(?:\s+(?:code|status))?)?\s*[:=]?\s*(0x[0-9a-fA-F]+|-?\d+)(?!\.\d)", re.I))
    EXIT_BARE_RE = re.compile(r"(?<![A-Za-z0-9_-])status(?!\s*[_-]?code)\s*[:=\s]\s*(0x[0-9a-fA-F]+|-?\d+)(?!\.\d)", re.I)
    WINERR_RE, ERRNO_RE, NTSTATUS_RE = re.compile(r"\bWinError\s+(\d+)\b", re.I), re.compile(r"\bErrno\s+(\d+)\b", re.I), re.compile(r"(?<![A-Za-z0-9])(0x[0-9a-fA-F]{8})(?![A-Za-z0-9])")
    QUOTED_FILE_RE, FILE_LIKE_RE = re.compile(r"""(?P<q>['"])([^\r\n'"]{2,200})(?P=q)"""), re.compile(rf"[\\/]|(?:\.(?:{_PlainSpec.EXTS}))$", re.I)
    RULES_PRE = ((ErrorCode.FILE_LOCKED, re.compile(r"being used by another process", re.I)), (ErrorCode.DNS_FAILED, re.compile(r"getaddrinfo failed|Name or service not known|Temporary failure in name resolution|nodename nor servname|SuspectDnsProbeFailed|gaierror|NameResolutionError", re.I)), (ErrorCode.TIMEOUT, re.compile(r"timed out|TimeoutError|TimeoutExpired|ReadTimeout|ConnectTimeout|WriteTimeout|PoolTimeout|ServerTimeoutError", re.I)), (ErrorCode.CONN_RESET, re.compile(r"Connection ?Refused|Connection ?Reset|Connection ?Aborted|RemoteDisconnected|IncompleteRead|EOF occurred|BrokenPipe", re.I)), (ErrorCode.SSL_ERROR, re.compile(r"SSLError|SSLCertVerificationError|CERTIFICATE_VERIFY_FAILED|\bSSL:", re.I)))
    RULES_POST = ((ErrorCode.PERMISSION_DENIED, re.compile(r"PermissionError|PermissionDenied|Access ?is ?denied|AccessDenied|Permission denied", re.I)), (ErrorCode.FILE_NOT_FOUND, re.compile(r"FileNotFoundError|No such file or directory", re.I)), (ErrorCode.BAD_JSON, re.compile(r"JSONDecodeError|Expecting value|Expecting property name|Unterminated string|Extra data|UnicodeDecodeError|UnicodeEncodeError|BadZipFile", re.I)), (ErrorCode.NET_ERROR, re.compile(r"URLError|urlopen error|ConnectionError|ProxyError|TooManyRedirects|Network is unreachable|RequestException", re.I)))
    RULES_TAIL = ((ErrorCode.KEY_ERROR, re.compile(r"\b(?:KeyError|AttributeError)\b")), (ErrorCode.VALUE_ERROR, re.compile(r"\b(?:ValueError|TypeError|IndexError)\b")), (ErrorCode.OS_ERROR, re.compile(r"\b(?:OSError|IOError|FileExistsError|FileExists)\b")), (ErrorCode.RUNTIME_ERROR, re.compile(r"\b(?:RuntimeError|StopIteration|AssertionError)\b")))

    @staticmethod
    def pos_int(val) -> int | None:
        return val if isinstance(val, int) and not isinstance(val, bool) and val > 0 else None

    @classmethod
    def norm_file(cls, cand: str) -> str:
        s = str(cand or "").strip().strip("'\"`").rstrip(".,;:")
        if not s or not cls.FILE_LIKE_RE.search(s):
            return ""
        s = ("\\\\" + re.sub(r"\\{2,}", r"\\", s[2:])) if s.startswith("\\\\") else re.sub(r"\\{2,}", r"\\", s)
        return s if not plain(s) else (f"'{s}'" if not plain(f"'{s}'") else "")

    @classmethod
    def os_code(cls, w: int | None, e: int | None, *, pre: bool) -> ErrorCode | None:
        if pre:
            return ErrorCode.FILE_LOCKED if w == 32 else ErrorCode.DNS_FAILED if e == 11001 else ErrorCode.TIMEOUT if w == 10060 else ErrorCode.CONN_RESET if w in (10053, 10054, 10061) else None
        return ErrorCode.PERMISSION_DENIED if (w == 5 or e == 13) else ErrorCode.FILE_NOT_FOUND if (w in (2, 3) or e == 2) else ErrorCode.NET_ERROR if w in (10064, 10065) else None

    @classmethod
    def pack(cls, code: ErrorCode, **kw) -> dict:
        return {"code": code.value, **{k: kw[k] for k in ("http", "exit", "winerror", "errno", "hex") if kw.get(k) not in (None, "")}, **({"file": kw["file"]} if kw.get("file") and code in cls.FILE_CODES else {})}

    @classmethod
    def extract_file(cls, raw: str, code: ErrorCode) -> str:
        if code not in cls.FILE_CODES:
            return ""
        no_url = _PlainSpec.mask_urls(raw, lambda _: " ")
        if ref := next((r for m in cls.QUOTED_FILE_RE.finditer(no_url) if (r := cls.norm_file(m.group(2)))), ""):
            return ref
        for pat in (_PlainSpec.UNIX_PATH_RE, _PlainSpec.WIN_UNC_RE):
            for m in pat.finditer(no_url):
                if pat is _PlainSpec.WIN_UNC_RE and re.match(r" [A-Za-z0-9_.-]+[\\/]", no_url[m.end() :]):
                    return ""
                if ref := cls.norm_file(m.group(0)):
                    return ref
        return next((r for pat in (_PlainSpec.REL_PATH_RE, _PlainSpec.FILE_RE) for m in pat.finditer(no_url) if (pat is not _PlainSpec.REL_PATH_RE or _PlainSpec.valid_rel(m.group(0).rstrip(".,;:"))) and (r := cls.norm_file(m.group(0)))), "")

    @classmethod
    def from_dict(cls, fault: dict) -> FaultRecord | None:
        try:
            ec = ErrorCode(str(fault.get("code")))
        except ValueError:
            ec = ErrorCode.UNKNOWN
        http = st if (st := cls.pos_int(fault.get("http"))) in cls.VALID_HTTP else None
        re_, hx = fault.get("exit"), str(fault.get("hex") or "")
        exit_c = re_ if isinstance(re_, int) and not isinstance(re_, bool) and re_ != 0 else (re_.lower() if isinstance(re_, str) and cls.NTSTATUS_RE.fullmatch(re_) and int(re_, 16) != 0 else None)
        hex_c = hx.lower() if cls.NTSTATUS_RE.fullmatch(hx) and int(hx, 16) != 0 else ""
        return FaultRecord(ec, http, exit_c, cls.pos_int(fault.get("winerror")), cls.pos_int(fault.get("errno")), hex_c, cls.norm_file(str(fault.get("file") or ""))) if (ec != ErrorCode.UNKNOWN or hex_c) else None


def fault_from_exc(exc: BaseException | type[BaseException] | None) -> dict | None:
    """源头活异常采集：直接读异常类与属性（winerror/errno/status_code/returncode/filename），零文本猜测。"""
    if exc is None:
        return None
    cls, inst = (exc, None) if isinstance(exc, type) else (type(exc), exc)
    mro = {c.__name__ for c in cls.__mro__}
    winerr, err_no = (_FaultSpec.pos_int(getattr(inst, "winerror", None)), _FaultSpec.pos_int(getattr(inst, "errno", None))) if inst is not None else (None, None)
    rc_raw = getattr(inst, "returncode", None) if inst is not None else None
    exit_c = rc_raw if isinstance(rc_raw, int) and not isinstance(rc_raw, bool) and rc_raw != 0 else None
    kw = {"winerror": winerr, "errno": err_no, "file": _FaultSpec.norm_file(getattr(inst, "filename", "") or "") if inst is not None else ""}
    is_http_cls, raw_sts = any("HTTP" in n or "Response" in n for n in mro), []
    if inst is not None:
        resp_st = _FaultSpec.pos_int(getattr(getattr(inst, "response", None), "status_code", None))
        raw_sts = ([resp_st] if resp_st is not None else []) + ([v for a in ("status_code", "status", "code") if (v := _FaultSpec.pos_int(getattr(inst, a, None))) is not None] if is_http_cls else [])
        st = next((v for v in raw_sts if v in _FaultSpec.VALID_HTTP), None)
        if st is None and is_http_cls and not any(100 <= v < 400 for v in raw_sts):
            st = classify_fault(f"{cls.__name__}: {inst}").http or next((int(m.group(1)) for m in re.finditer(r"\b(\d{3})\b", _FaultSpec.DATE_TIME_RE.sub(" ", _PlainSpec.mask_safe(str(inst)))) if int(m.group(1)) in _FaultSpec.VALID_HTTP), None)
        if st in _FaultSpec.VALID_HTTP:
            return _FaultSpec.pack(ErrorCode.HTTP_ERROR, http=st, **kw)
    if (ec := _FaultSpec.os_code(winerr, err_no, pre=True) or next((c for c, ns in _FaultSpec.MRO_PRE if mro & ns), None) or (ErrorCode.SSL_ERROR if any(n.startswith("SSL") for n in mro) else None)):
        return _FaultSpec.pack(ec, exit=exit_c if ec == ErrorCode.TIMEOUT else None, **kw)
    if isinstance(reason := getattr(inst, "reason", None) if inst is not None else None, BaseException) and (inner := fault_from_exc(reason)) and inner.get("code") != ErrorCode.UNKNOWN.value:
        return inner
    if (mro & _FaultSpec.HTTP_EXCS) and not any(100 <= v < 400 for v in raw_sts):
        return _FaultSpec.pack(ErrorCode.HTTP_ERROR, **kw)
    if (ec := _FaultSpec.os_code(winerr, err_no, pre=False) or next((c for c, ns in _FaultSpec.MRO_POST if mro & ns), None)):
        return _FaultSpec.pack(ec, **kw)
    if exit_c is not None:
        return _FaultSpec.pack(ErrorCode.PROCESS_EXIT, exit=exit_c, **kw)
    if (ec := next((c for c, ns in _FaultSpec.MRO_TAIL if mro & ns), None) or (ErrorCode.OS_ERROR if winerr is not None else None)):
        return _FaultSpec.pack(ec, **kw)
    if inst is not None and ((rec := classify_fault(f"{cls.__name__}: {inst}")).code != ErrorCode.UNKNOWN or rec.hex_code):
        return _FaultSpec.pack(rec.code, http=rec.http, exit=rec.exit_code, winerror=rec.winerror or winerr, errno=rec.errno or err_no, hex=rec.hex_code, file=rec.file_ref or kw["file"])
    return _FaultSpec.pack(ErrorCode.UNKNOWN, **kw)


def classify_fault(raw: str, fault: dict | None = None) -> FaultRecord:
    """把源头故障字典或原始日志文本归类为确定的 FaultRecord。"""
    if isinstance(fault, dict) and fault.get("code") and (rec := _FaultSpec.from_dict(fault)):
        return rec
    text = str(raw or "")
    if not text.strip():
        return FaultRecord()
    scan = _FaultSpec.DATE_TIME_RE.sub(" ", _PlainSpec.mask_safe(text, mask_hex=False))
    has_proc = bool(_FaultSpec.PROC_CTX_RE.search(scan))
    http = next((int(g) for p in _FaultSpec.HTTP_RES for m in p.finditer(scan) if (g := next((x for x in m.groups() if x), "")) and int(g) in _FaultSpec.VALID_HTTP), None)
    if http is None and not has_proc:
        http = next((int(m.group(1)) for m in _FaultSpec.HTTP_BARE_RE.finditer(scan) if int(m.group(1)) in _FaultSpec.VALID_HTTP), None)
    exit_c = next((v for p in ((*_FaultSpec.EXIT_RES, _FaultSpec.EXIT_BARE_RE) if has_proc else _FaultSpec.EXIT_RES) for m in p.finditer(scan) if (g := next((x for x in m.groups() if x), "")) and (v := (g.lower() if g.lower().startswith("0x") and int(g, 16) != 0 else int(g) if not g.lower().startswith("0x") and int(g) != 0 else None)) is not None), None)
    winerr = int(m.group(1)) if (m := _FaultSpec.WINERR_RE.search(scan)) and int(m.group(1)) > 0 else None
    err_no = int(m.group(1)) if (m := _FaultSpec.ERRNO_RE.search(scan)) and int(m.group(1)) > 0 else None
    hex_c = next((m.group(1).lower() for m in _FaultSpec.NTSTATUS_RE.finditer(scan) if int(m.group(1), 16) != 0), "")
    code = (_FaultSpec.os_code(winerr, err_no, pre=True) or next((c for c, p in _FaultSpec.RULES_PRE if p.search(scan)), None)
            or (ErrorCode.HTTP_ERROR if http is not None else None) or _FaultSpec.os_code(winerr, err_no, pre=False)
            or next((c for c, p in _FaultSpec.RULES_POST if p.search(scan)), None) or (ErrorCode.PROCESS_EXIT if exit_c is not None else None)
            or next((c for c, p in _FaultSpec.RULES_TAIL if p.search(scan)), None) or (ErrorCode.OS_ERROR if winerr is not None else ErrorCode.UNKNOWN))
    return FaultRecord(code, http, exit_c, winerr, err_no, hex_c, _FaultSpec.extract_file(text, code))


def _normalize_zh(text: str) -> str:
    """对纯中文句或安全前缀做轻度术语/模糊词规整，完整保护 URL/路径/ISO 时间/版本号。"""
    held: list[str] = []
    s = _PlainSpec.mask_safe(text, hold=held)
    for old, new in _ZH_PLAIN_MAP:
        s = s.replace(old, new)
    s = re.sub(r"^[\s，,、；;：:]+|[\s，,、；;：:]+$", "", re.sub(r"[，,、]{2,}", "，", s))
    for i, val in enumerate(held):
        s = s.replace(f"\x00{i}\x00", val)
    return s.strip()


def fault_cause(what: str, fault: dict | None = None) -> str:
    """把报错日志或结构化故障翻成简短中文原因；未识别返回空串（供 errwatch._kept 保留尾因）。"""
    rec = classify_fault(what, fault=fault)
    if rec.code == ErrorCode.UNKNOWN:
        return ""
    if rec.code == ErrorCode.HTTP_ERROR and rec.http is not None:
        return f"对方服务器返回了状态码 {rec.http}"
    if rec.code == ErrorCode.PROCESS_EXIT and rec.exit_code is not None:
        return f"外部命令执行失败（退出码 {rec.exit_code}）"
    return f"系统调用失败（系统错误码 {rec.winerror}）" if rec.code == ErrorCode.OS_ERROR and rec.winerror is not None else _FAULT_TEMPLATES[rec.code]


def _pure_zh(raw: str) -> str:
    if not raw or any(w not in ALLOWED_WORDS for w in _PlainSpec.WORD_RE.findall(_PlainSpec.mask_safe(raw))):
        return ""
    clean = raw if not plain(raw) else _normalize_zh(raw)
    return clean if clean and not plain(clean) else ""


def format_fault_reason(what: str, fault: dict | None = None) -> str:
    """统一白话故障渲染入口：纯中文轻度规整，含英文或结构化故障一律走封闭中文模板。"""
    raw = str(what or "").strip()
    if not raw and not fault:
        return "记录里没有写具体原因，详见中继日志"
    if not fault and (clean := _pure_zh(raw)):
        return clean
    rec = classify_fault(raw, fault=fault)
    cand = re.split(r"[｜|]", raw, maxsplit=1)[0].strip() if ("｜" in raw or "|" in raw) else (raw if fault else "")
    p_raw = cand if (cand and not plain(cand)) else (_normalize_zh(cand) if cand else "")
    prefix = p_raw if p_raw and re.search(r"[\u4e00-\u9fff]{2,}", p_raw) and not plain(p_raw) else ""
    base = f"对方服务器返回了状态码 {rec.http}" if rec.code == ErrorCode.HTTP_ERROR and rec.http is not None else ("系统调用失败" if rec.code == ErrorCode.OS_ERROR and rec.winerror is not None else _FAULT_TEMPLATES[rec.code])
    details = [d for d in (f"系统错误码 {rec.winerror}" if rec.code == ErrorCode.OS_ERROR and rec.winerror is not None else "", f"退出码 {rec.exit_code}" if rec.exit_code is not None else "", f"错误码 {rec.hex_code}" if rec.hex_code and rec.hex_code != rec.exit_code else "", f"文件 {rec.file_ref}" if rec.file_ref and rec.file_ref not in prefix else "") if d]
    body = f"{base}（{'，'.join(details)}）" if details else base
    out = f"{prefix}——{body}，原文已记日志" if prefix else f"{body}，原文已记日志"
    return out if not plain(out) else (f"{base}，原文已记日志" if not plain(f"{base}，原文已记日志") else "程序发生运行异常，原文已记日志")


def _said(what: str, fault: dict | None = None) -> str:
    """将单条报错转为推群可读白话：纯中文照抄，含英文或结构化故障走封闭中文模板。"""
    raw = str(what or "").strip()
    return f"它说：{clean}" if (not fault and (clean := _pure_zh(raw))) else f"原因：{format_fault_reason(raw, fault=fault)}"


def relay_error_recurred(fixed_in: str) -> str:
    """Title: a fault known_fixed.py records as fixed in `fixed_in` is back (an ERROR)."""
    return f"{RELAY_ERROR}（v{fixed_in} 修过的又出现了）" if fixed_in else f"{RELAY_ERROR}（修过的又出现了）"


def relay_error_recurred_body(where: str, what: str, at: str = "", fixed_what: str = "",
                              fault: dict | None = None) -> str:
    when = f"（{at}）" if at else ""
    fixed = f"当时修的是：{fixed_what}。" if fixed_what else ""
    return (f"一种已经修过的错又出现了{when}，出在「{relay_part(where)}」。{fixed}{_said(what, fault=fault)}\n"
            "修过的毛病又犯了，已交给我们这边去查为什么没修住。")


def relay_faults_section(rows: list) -> str:
    """技术日志中的当日中继报错汇总（仅写入技术日志，绝不进入用户日报；一律输出封闭白话错因）。"""
    if not rows:
        return ""
    lines = []
    for r in rows[:10]:
        n, pushed = int(r.get("count") or 1), int(r.get("pushed") or 0)
        tags = ([f"复发：v{r['fixed_in']} 修过的又出现了"] if r.get("fixed_in") else []) + [
            "已报群" if pushed >= n else (f"已报群 {pushed} 次，还有 {n - pushed} 次在排队等着报" if pushed else "还在排队等着报群")
        ]
        fault = r.get("fault") if isinstance(r.get("fault"), dict) else None
        said = format_fault_reason(str(r.get("line") or ""), fault=fault)
        lines.append(f"· {relay_part(str(r.get('where') or ''))}：{said}" + (f"（{n} 次）" if n > 1 else "") + f"｜{'；'.join(tags)}")
    if len(rows) > 10:
        lines.append(f"· 另外还有 {len(rows) - 10} 种，见中继日志")
    return "中继自己记下的报错\n" + "\n".join(lines)


def watch_lost_body() -> str:
    return ("脚本跑完的结果暂时要等到下一次定时检查才处理（最长一小时），不再是一跑完就处理。"
            "中继会自己反复尝试恢复；这条已交给我们这边，一直没恢复就由我们这边去修。")


def automas_down_body(tries: int) -> str:
    return f"已连续 {tries} 次启动 AUTO-MAS，都没起来，已交给我们这边去查。中继会继续试，间隔每次翻倍。"


def automas_boot_down_body() -> str:
    return ("开机后 AUTO-MAS 没起来，中继拉了一次也没起来。它不起来，接下来这一班就不会跑。"
            "中继 3 分钟后再拉一次，之后每次间隔翻倍，连拉 3 次还不行会再报一次。")


def preupdate_unconfirmed_tail() -> str:
    # Tail of a group alarm (boot_stages._stage_preupdate): what happens next.
    return "\n\n这次没确认到有没有更新。队列照常跑，明日方舟、终末地、鸣潮开跑时自己会查；AUTO-MAS 留到下次开机再查。"


def cant_enter_body(script: str, attempts: int, maint: bool, hint: str, quick_sec: int) -> str:
    """A run that never got into the game, with the official notice it was matched to (`hint`).
    `quick_sec`: the shape's threshold (collector_maaend._UNREACHABLE_QUICK_SEC)."""
    why = "官方停服维护中" if maint else f"每个任务 {quick_sec} 秒内失败、一个没完成"
    return (f"{script} 连试 {attempts} 次都没进游戏（{why}）。\n"
            + (f"官方依据：{hint}\n" if hint else "官方依据：这次没读到官方公告\n")
            + "队列跑完后中继会等开服、更新客户端、再单独补跑它。")


def missed_queue_body(late_min: int) -> str:
    return (f"已经晚了 {late_min} 分钟，今天没有任何该时段的运行记录。\n"
            "已交给我们这边去查三处：AUTO-MAS 有没有在跑、定时有没有触发、模拟器或游戏起没起来。")


def missed_item_body(ran: list[str], kind: str, late_min: int) -> str:
    return (f"这一轮跑了 {'、'.join(sorted(ran))}，但 {kind} 一次记录都没有，"
            f"已经晚了 {late_min} 分钟。\n"
            "队列本身是跑了的，所以不是没开机——是这一项自己没起来。")


# AUTO-MAS's own config-check refusals (repo app/task/<type>/manager.py check(), v5.7.0-beta.4),
# matched by the text before their first comma, said plainly (runwatch.check_config_skips).
CONFIG_SKIP_WHY = {
    "未找到终末地官方启动器": "找不到终末地官方启动器",
    "MaaEnd.exe文件不存在": "找不到 MaaEnd 的程序文件",
    "MAA.exe文件不存在": "找不到 MAA 的程序文件",
    "MaaEnd 配置文件不存在": "找不到 MaaEnd 的设置文件",
    "MAA配置文件不存在": "找不到 MAA 的设置文件",
    "未完成 MAA 全局设置": "MAA 的总设置没做",
    "未选择 MaaEnd 控制器": "MaaEnd 没选控制方式",
    "未完成游戏配置": "游戏那一栏没填好",
    "未完成模拟器配置": "模拟器那一栏没填好",
    "未填写配置路径": "设置文件的位置没填",
    "未填写日志路径": "日志的位置没填",
    "不支持的任务模式": "这一项的运行方式它不支持",
    "脚本配置类型错误": "这一项的脚本类型填错了",
}
CONFIG_SKIP_UNREAD = "它写的原因没法直接转成大白话，原话在中继的技术日志里"


def config_skip_why(reason: str) -> str:
    """AUTO-MAS's config-check refusal, said plainly; its own words when they already read plainly."""
    head = re.split(r"[,，]", reason or "", maxsplit=1)[0].strip().rstrip("！!。")
    for key, plain_why in CONFIG_SKIP_WHY.items():
        if key in head:
            return plain_why
    return head if head and not plain(head) else CONFIG_SKIP_UNREAD


def config_skip_body(game: str, why: str, when: str, queue: str) -> str:
    """AUTO-MAS refused to start one script of a running queue at its own config check
    (runwatch.check_config_skips): the run did not happen and will not until the setting is fixed."""
    shift = f"{queue}这一班的" if queue else "这一趟的"
    return (f"AUTO-MAS 开跑前检查没过：{why}。\n"
            f"{game}这一项 {when} 没开跑就被跳过了，游戏没开，{shift}{game}没做。\n"
            "设置不改的话，下次排到它还会一样被跳过，要有人去改。")


def attempt_timeout(game: str, script: str) -> str:
    return f"⏱️ {game}（{script}）跑超时，AUTO-MAS 正在重试"


def attempt_timeout_body(attempt: int, of: int, began, at) -> str:
    """A timeout of a script, pushed while AUTO-MAS still retries (runwatch); every one is pushed."""
    nth = f"第 {attempt}/{of} 次" if attempt and of else "这一次"
    span = (f"{began:%H:%M} 开跑，{at:%H:%M} 被 AUTO-MAS 结束（{int((at - began).total_seconds() // 60)} 分钟）"
            if began else f"{at:%H:%M} 被 AUTO-MAS 结束")
    if attempt and of and attempt < of:
        nxt = f"它还会再试 {of - attempt} 次；全部失败才会再来一条最终失败报警。"
    elif attempt and of:
        nxt = "这已是最后一次，最终结果出来再报。"
    else:
        nxt = "最终结果出来再报。"
    return f"{nth}跑超时：{span}。\n{nxt}"


def shift_overrun(queue: str) -> str:
    return f"⏰ {queue}超时还没跑完"


def _overrun_basis(limit_min: int, days: int) -> str:
    """Where the planned minutes came from: runwatch.planned_minutes' day count, 0 when
    no day was usable and the fixed fallback stands in for a history there is not."""
    if not days:
        return f"没有可参考的记录，按 {limit_min} 分钟算"
    return f"近 7 天和前两周同一天里最长 {limit_min} 分钟跑完"


def _restart_note(restarted) -> str:
    """The clause for a shift whose clock a retried timeout restarted (runwatch.retry_clock)."""
    return f"中间有脚本跑超时、AUTO-MAS {restarted:%H:%M} 重试，从那时重新算，" if restarted else ""


def shift_overrun_body(queue: str, due, now, limit_min: int, slack_min: int,
                       states: str, last_log: str, days: int = 1, restarted=None, started=None) -> str:
    """A queue still unfinished past its planned end (runwatch). `days`: how many past
    days the limit was taken from (runwatch.planned_minutes); `restarted`: when a retried
    timeout restarted the clock (runwatch.retry_clock), else None; `started`: when the
    running task was created after its due minute (runwatch._late_start: the phone's run_now
    of the queue), else None - the minutes run and the planned end are then counted from it,
    not from `due`."""
    from datetime import timedelta as _td  # noqa: PLC0415
    ran = int((now - (started or due)).total_seconds() // 60)
    opening = f"{queue}排的是 {due:%H:%M}，这趟 {started:%H:%M} 才开跑" if started else f"{queue} {due:%H:%M} 开跑"
    body = (f"{opening}，到现在 {now:%H:%M} 还没跑完，已跑 {ran} 分钟。\n"
            f"{_overrun_basis(limit_min, days)}，{_restart_note(restarted)}按 {limit_min} + {slack_min} 分钟算，"
            f"该在 {(restarted or started or due) + _td(minutes=limit_min + slack_min):%H:%M} 前结束。")
    if states:
        body += f"\n现在各脚本：{states}"
    if last_log:
        body += f"\nAUTO-MAS 最后一句：{last_log}"
    return body


def own_turn_note(script: str, since, now, own_min: int, slack_min: int) -> str:
    """One more line of the two shift alarms when they waited for the script whose turn it
    was (runwatch.turn_deadline): since when it has had its turn and by which of its own
    days the alarm still went out."""
    ran = int((now - since).total_seconds() // 60)
    return (f"轮到 {script} 是 {since:%H:%M}，到现在 {ran} 分钟；它自己单跑最长的一天是 {own_min} 分钟，"
            f"按 {own_min} + {slack_min} 分钟算也过了。")


def shift_no_result(queue: str) -> str:
    return f"⏰ {queue}有脚本一直没出结果"


def shift_no_result_body(queue: str, due, now, missing: str, limit_min: int, slack_min: int,
                         days: int = 1, restarted=None) -> str:
    """A shift script with no record past the shift's planned end, where AUTO-MAS did not show
    the shift still running (shutdown._alarm_shift_overdue). `restarted`: as shift_overrun_body."""
    ran = int((now - due).total_seconds() // 60)
    return (f"{queue} {due:%H:%M} 开跑，到现在 {now:%H:%M}（{ran} 分钟）{missing} 还没有结果。\n"
            f"{_overrun_basis(limit_min, days)}，{_restart_note(restarted)}按 {limit_min} + {slack_min} 分钟算早该跑完了。")


def estop_farm_left_body(farm: str, stopped: str) -> str:
    """The red button could not end the echo farm (redbutton.emergency_stop)."""
    return (f"刷声骸没结束{farm}。中继几分钟后会把鸣潮的脚本重新开起来，"
            f"已交给我们这边去结束刷声骸。其余已停：{stopped}")


def estop_not_clean_body(left: str, stopped: str, farm: str) -> str:
    """The red button's stop rounds left something running (redbutton.emergency_stop)."""
    return (f"没停干净：{left}。AUTO-MAS 那边停掉的：{stopped}。"
            "AUTO-MAS 会把被停掉的队列整队重跑，中继拦不住它；"
            f"已交给我们这边跑紧急停止的脚本，它会先把中继停掉再停其余的{farm}")


def echo_farm_game_left(names: list[str]) -> str:
    """echofarm.stop_okww: the game was still up after the desktop kill."""
    return "；**游戏没关掉（" + "、".join(names) + "），已交给我们这边去关**"


def echo_farm_stop_unconfirmed(names: list[str]) -> str:
    """echofarm.stop_okww: its time ran out before a look found the desktop clean."""
    return ("；**到时间还没确认关干净，最后一次看还开着的是：" + "、".join(names)
            + "，已交给我们这边去关**")


def echo_farm_level(read: "tuple[str, str] | None", name: str) -> str:
    """echofarm._finish: the level the game showed on the boss (echofarm.level_since),
    never the configured one - the game keeps its own where no level page appears."""
    if read is None:
        return "（等级没读到）"
    level, seen = read
    def plain(x: str) -> str:
        return "".join(ch for ch in x if ch not in " ·・･•‧.")
    if not seen or not name or plain(seen) == plain(name):
        return f"（游戏里 Lv.{level}）"
    return f"（游戏里读到的是 Lv.{level} {seen}）"


def echo_farm_progress(n: "int | None") -> str:
    """echofarm._finish: how many progress lines (a fight, an echo picked up, back in
    the realm) OK-WW logged during the farm; None when the log could not be read."""
    if n is None:
        return "**读不到 OK-WW 的日志，刷到没有不知道**"
    if n == 0:
        return "**OK-WW 日志里一次都没刷到（没打怪、没捡到声骸）**"
    return f"刷的过程中有 {n} 次进展（打怪、捡声骸、回到副本）"


def echo_farm_drops(drops: "dict | None", stat: str, sonata: str = "") -> str:
    """echofarm._finish of a farm by main stat: the echoes this farm picked up, the
    target's count and how many toasts were not read (each one may have been it)."""
    if drops is None:
        return ""          # the progress part already says the log could not be read
    unread = f"，{drops['未读出']} 个没读出主词条" if drops["未读出"] else ""
    if sonata:
        got = drops["套装"].get((stat, sonata), 0)
        unread += f"，{drops['套装未读出']} 个没认出套装" if drops["套装未读出"] else ""
        return f"；这一趟捡到声骸 {drops['总捡']} 个，其中「{sonata}·{stat}」{got} 个{unread}"
    return f"；这一趟捡到声骸 {drops['总捡']} 个，其中「{stat}」{drops.get(stat, 0)} 个{unread}"


def echo_farm_no_claim_left(path: str) -> str:
    """echofarm.finish: the no-claim marker of the farm could not be deleted."""
    return f"；**不领奖标记没删掉，周本会不领奖，已交给我们这边去删 {path}**"


def echo_farm_boss_not_back(wrote: bool) -> str:
    """echofarm.finish: the boss the farm set is still in OK-WW's config. `wrote` is
    False when the file could not be written at all."""
    did = "没改回去" if wrote else "没能改回去"
    return f"；**刷声骸用的 Boss 设置{did}，明早的周本会去打今晚刷声骸的那个 Boss，已交给我们这边去改回**"


def okww_autostart_not_restored(was_on: bool) -> str:
    """preupdate_okww: OK-WW's start-the-game-on-launch switch was not put back (a WARNING)."""
    return (f"预更新：OK-WW 的「启动时自动开游戏」没能改回原来的（{'开' if was_on else '关'}），"
            "已交给我们这边去改回 OK-WW 的基本设置")


SKIP_MARK_BROKEN = "跳过模式的恢复标记损坏，已清除；已交给我们这边去查队列要不要恢复"


def skip_restore_failed(queue: str, detail: str) -> str:
    """modes: putting a skipped queue back on did not take."""
    return f"跳过「{queue}」后恢复失败：{detail}；已交给我们这边去查"


def queue_item_deleted_old_way(queue: str, script: str) -> str:
    """commands.restore_script_in_queue: a skip from before 2026-10-11 deleted the item (a WARNING)."""
    return (f"队列「{queue}」里 {script} 是按旧办法整项删掉的，中继不再加回；"
            "已交给我们这边在调度程序里把它加回这个队列")


# Why the make-up leaves the Endfield settings alone (makeup.stash_first / _prepare_maaend).
MAKEUP_WAIT_FOR_US = "等我们这边改回"
MAKEUP_RESTORE_PENDING = "上次临时改过的终末地设置还没改回，" + MAKEUP_WAIT_FOR_US


def makeup_restore_skipped(err: str) -> str:
    return f"上次临时改过的终末地设置没能自动改回（{err or MAKEUP_WAIT_FOR_US}），这次不补"


# For the gate: every constant in this module, plus sample copy
def samples() -> list[str]:
    from datetime import datetime as _dt  # noqa: PLC0415
    t0, t1, t2 = _dt(2026, 10, 1, 9, 0), _dt(2026, 10, 1, 9, 18), _dt(2026, 10, 1, 11, 20)
    drops = {"总捡": 61, "未读出": 2, "套装未读出": 3, "套装": {("治疗效果加成", "茜染怀想之花"): 4}, "治疗效果加成": 9}
    return [
        echo_farm_drops(drops, "治疗效果加成", "茜染怀想之花"), echo_farm_drops(drops, "治疗效果加成"),
        echo_farm_drops(None, "治疗效果加成"),
        attempt_timeout_body(1, 3, t1, t2), attempt_timeout_body(3, 3, t1, t2),
        attempt_timeout_body(0, 0, None, t2),
        shift_overrun_body("早班", t0, _dt(2026, 10, 1, 13, 10), 220, 30,
                           "MAA 完成、OK-WW 运行、MaaEnd 等待", "正在启动游戏..."),
        own_turn_note("MaaEnd", _dt(2026, 11, 16, 10, 12), _dt(2026, 11, 16, 11, 47), 64, 30),
        shift_no_result_body("早班", t0, _dt(2026, 10, 1, 12, 31), "MaaEnd", 180, 30),
        shift_overrun_body("早班", t0, _dt(2026, 10, 1, 12, 31), 180, 30, "", "", 0),
        shift_overrun_body("晚班", _dt(2026, 11, 8, 21, 30), _dt(2026, 11, 9, 1, 44), 21, 30,
                           "MAA 运行", "", 7, started=_dt(2026, 11, 9, 0, 52, 21)),
        shift_no_result_body("早班", t0, _dt(2026, 10, 1, 12, 31), "MaaEnd", 180, 30, 0),
        UNREACHABLE_SHAPE_NOTE, UNREACHABLE_UNREAD_NOTE, PREUPDATE, GAME_UPDATE, RERUN_AFTER_UPDATE, WEEKLY, NEW_WEEK, ANNIHILATION_OFF,
        annihilation_off_body("明日方舟 · 剿灭"), SKIP_MODE, ESTOP,
        ESTOP_FAILED, SHUTDOWN_CANCELLED, ALARM_HOLD_EXPIRED, ALARM_SHUTDOWN_ABORTED, ALARM_EARLY_SHUTDOWN,
        ALARM_EARLY_NO_LOG, ALARM_EARLY_NO_1074, ALARM_HOLD_CORRUPT,
        alarm_hold_expired_body("这一轮没干完", "2026-11-24 21:20", True),
        alarm_hold_expired_body("这一轮没干完", "2026-11-24 21:20", False),
        alarm_shutdown_aborted_body(True, 0, "本机账号", "关机命令", "手动关机"),
        alarm_shutdown_aborted_body(False, 5, "", "", ""),
        alarm_early_shutdown_body("这一轮没干完", "2026-11-24 21:10", ALARM_EARLY_NO_1074),
        SKIP_FAILED, MAAEND_PRUNED, MAAEND_PRUNED_REFUSED, ESSENCE_FILLER_FAILED, essence_filler_failed("写进去之后读出来和写的不一样"),
        ESSENCE_TARGET_MET_AFTER_FARM, ESSENCE_FILLER_SWITCHED,
        essence_filler_on(["玉中身", "唤月"]), essence_filler_on([]),
        essence_filler_friend_body(["玉中身", "唤月"]), essence_filler_friend_body([]),
        ECHO_FARM, ECHO_FARM_DONE, ECHO_FARM_TROUBLE,
        CONFIG_CHANGED, CONFIG_FAILED, INBOX_APPLIED, SELFUPDATE_FAILED, WATCH_LOST,
        AUTOMAS_DOWN, ROUND_INCOMPLETE, AK_ACTIVITY_OPEN,
        ak_activity_open_body("雪山降临1101", "支线活动", "11-22 04:00（东京 05:00）",
                              "12-02 03:59（东京 04:59）", rerun=True),
        ak_activity_open_body("昨日海", "支线活动", "10-09 12:00（东京 13:00）", opening_today=True),
        SPMED_UNRECOGNISED, MAAEND_MIGRATED, TACET_DROPS, RELAY_ERROR,
        *(spmed_unrecognised_body(k) for k in ("broken", "unknown", "missing", "unreadable")),
        CLAIM_LINES_RUN, CLAIM_LINES_FW, claim_lines_fw_none("框架日志的文件夹不在"), claim_lines_head("基质刷取"),
        claim_lines_skipped(12),
        MAKEUP_RESTORE_FAILED, PHONE_QUEUED, phone_busy_reason("run_now"),
        unresolved("明日方舟", "早班"), unresolved_undone("终末地", "早班"), unresolved_settings("终末地", "早班"),
        unresolved_head("明日方舟", "早班", "补跑也没成", "开始唤醒", "https://gofile.io/d/xxxx"),
        unresolved_head("终末地", "早班", MAKEUP_STOPPED_PHRASE, "自动采集", ""),
        RUN_LIMIT_RESET, RUN_LIMIT_STUCK, run_limit_reset_body("终末地", 3, 1),
        run_limit_stuck_body("终末地", 3, 1, "调度程序没有接受这次修改：正在运行，无法更新配置项"),
        unresolved_head("明日方舟", "晚班", "没补跑：这一轮已经开始干活（打过关），再跑一遍会再吃一份理智药",
                        "开始唤醒", ""),
        unresolved_head("终末地", "早班", "补跑没能开跑（找不到终末地的母本）", "基质刷取（背包满了）", ""),
        unresolved_head("明日方舟", "晚班", "没补跑：补跑一天只有一次，今天的已经用过了", "", ""),
        unresolved_head("终末地", "早班", "没补跑：没等到补跑就过了零点，补跑只补当天的", "送礼", ""),
        unresolved_undone_head("明日方舟", "早班", "基建换班", "https://gofile.io/d/xxxx"),
        unresolved_settings_head("终末地", "早班", "自动囤货的设置", "https://gofile.io/d/xxxx"),
        unverified_alarm("终末地", "早班", 1),
        unverified_alarm_head("终末地", "早班", "赠送干员礼物、基建任务",
                              maaend_unverified_why(["赠送干员礼物"], ["基建任务"]), "https://gofile.io/d/xxxx"),
        maaend_unverified_why(["装备制造"], []),
        maaend_unverified_why([], ["基建任务"]),
        trail_unread_note(["赠送干员礼物", "装备制造"], 1, 2),
        retry_outcome(["基建任务", "选剑演武"], "10:35（东京 11:35）开始的", ["基建任务"], ["选剑演武"], []),
        retry_outcome(["装备制造", "转交委托"], "10:35（东京 11:35）开始的", [], [], ["装备制造", "转交委托"]),
        unverified_trail_lines([("装备制造", "终末地自己检查画面没过，把后面的任务全停了，这一项没做成")]),
        machinecheck_section([("#28", "终末地四个任务看得到做成了", "A", "HEALED",
                               "装备制造（10:34:11→10:34:16）没做成；同一天 09:30（东京 10:30）开始的那趟已经做成了，不用人管",
                               "2026-10-08 10:35:00")], []),
        phone_busy_reason("echo_farm"),
        makeup_restore_failed_body(r"D:\ark\automas\data\x\Default\ConfigFile\mxu-MaaEnd.json",
                                   r"C:\ProgramData\ark-relay\state\makeup\narrow.json"),
        relay_error_body("ark.service", "ConnectionRefusedError: [WinError 10061]", "21:21"),
        relay_error_body("ark.report", "日报没发出去", "10:47"),
        relay_error_recurred("20261005151027"), relay_error_recurred(""),
        relay_error_recurred_body("ark.banners", "库街区官方资讯里没找到 3.7 版本资讯帖", "21:47",
                                  "库街区官方资讯翻得不够多页，找不到当期版本资讯帖"),
        relay_faults_section([{"where": "ark.banners", "line": "官方图转 PNG 失败，原样交给系统 OCR", "count": 3,
                               "level": "WARNING", "fixed_in": "20261005151027", "pushed": 3},
                              {"where": "ark.report", "line": "日报没发出去", "count": 1,
                               "level": "ERROR", "pushed": 1},
                              {"where": "ark.engine", "line": "处理运行记录失败", "count": 2, "level": "ERROR",
                               "pushed": 1},
                              {"where": "ark.notify", "line": "x", "count": 1, "level": "ERROR"}]),
        RELAY_ERROR_TAIL, relay_errors_merged(RELAY_ERROR, 3), *_RELAY_PARTS.values(),
        SKLAND_MULTI_ROLE, HAND_STARTED_NOTE, hand_fixed_note("12:05"), UPDATE_DAY_NOTE,
        skland_multi_role_body(["1234567", "7654321"]),
        relay_error_line("ark.report", "日报没发出去", "21:21:05 起共 3 次，最后一次 21:25:10"),
        relay_error_body("ark.maintenance", "维护公告：终末地 官方公告取不到（官网：<urlopen error [Errno 11001] "
                         "getaddrinfo failed>），这次不知道它有没有停服维护", "05:20:16"),
        relay_error_line("ark.service", "Traceback: KeyError 'x'", "09:00:01"),
        *_FAULT_TEMPLATES.values(),
        format_fault_reason("关游戏失败 ｜ taskkill /F /IM Endfield.exe returned non-zero exit status 128"),
        format_fault_reason("官方数据返回异常 ｜ HTTP/1.1 502 Bad Gateway"),
        relay_error_body("ark.service", "中继更新出错", "09:20:01"),
        relay_error_line("ark.banners", "官方图转 PNG 失败，原样交给系统 OCR", "21:47:01", "20261005151027",
                         "游戏机缺读图组件，官方长图读不了"),
        AUTOMAS_CONTRACT, MAS_CONTRACT_CHECK,
        automas_contract_body("v5.7.0-beta.3", [
            "中继读不到方舟的关卡设置（关卡一栏里找不到），开跑前查关卡、明日安排、手机上显示和修改关卡都不对了"]),
        SELFCHECK_FAILED, selfcheck_failed_body(11, [("读得到每个程序是怎么启动的（系统自带的那条路）", "读不到"), ("调度程序的开机任务计划还在", "退出码 1")]),
        shiftcheck_summary("晚班", 4, [], []),
        shiftcheck_summary("早班", 4, [(SHIFTCHECK_ANNIHILATION, annihilation_off_body("明日方舟 · 剿灭")),
                                     (SHIFTCHECK_TEST_WINDOW, shiftcheck_test_window_on("2026-10-11 09:12:00"))],
                           [(SHIFTCHECK_ANNIHILATION, SHIFTCHECK_ANNIHILATION_UNREAD)],
                           [(SHIFTCHECK_SKIP, SHIFTCHECK_SKIP_ON),
                            (SHIFTCHECK_DEBUG, shiftcheck_debug_on("2026-10-11 20:50"))]),
        shiftcheck_summary("晚班", 4, [], [], [(SHIFTCHECK_SKIP, SHIFTCHECK_SKIP_ON)]),
        shiftcheck_test_window_on(""), shiftcheck_broken("晚班"), OKWW_BATTLE_PASS_UNCLAIMED,
        OKWW_BATTLE_PASS_LABEL, OKWW_BATTLE_PASS_FAILED, OKWW_BATTLE_PASS_RETRIED, OKWW_BATTLE_PASS_UNCHECKED,
        OKWW_BATTLE_PASS_CLOSED,
        COLLECT_RETRY_START, COLLECT_RETRY_OK, COLLECT_RETRY_FAILED, COLLECT_RECURRENT,
        collect_second_round(["采集协议纹石（路线2）"]),
        NO_WHOLE_MAKEUP, *(collect_retry_ahead(["采集血菌", "采集协议纹石（路线2）"], st) for st in ("ahead", "debug", "spent")),
        EVIDENCE_SAVED, EVIDENCE_SOURCE_CHANGED, EVIDENCE_UPLOAD_FAILED, LOST_ALARM_QUEUE,
        gamelog_unknown_errors("鸣潮"), gamelog_unknown_errors_body("鸣潮", "09:12", 2),
        gamelog_unknown_errors_body("终末地", "", 1),
        collect_retry_body(["路线16"], ["路线15"], [], ""),
        collect_blocked_check("路线10：重红柱状菌"), collect_blocked_row(["路线10：重红柱状菌"]),
        collect_blocked_row(["路线10：重红柱状菌"], again=True), collect_blocked_row(["路线10：重红柱状菌"], first=True),
        collect_recurrent_body(["路线15：红矛叶"]), evidence_saved_body("MaaEnd", "09-11 10:18", 3, "https://example.cos.ap-shanghai.myqcloud.com/x/index.html"),
        evidence_source_changed_body(["MaaEnd 导出"]),
        patches(3), unconfirmed("预更新", 2), failed("MaaEnd"), self_healed("OK-WW"),
        cant_enter("MaaEnd"), missing(not_run("早班")), missing(not_run_in("OK-WW", "早班")),
        healed_after_update("OK-WW"),
        restart_was_last("游戏更新成功，即将重启任务", "09:18"), restart_was_last("", "09:18"),
        makeup_passed("明日方舟", "早班"),
        stage_gate("早班"), stage_gate_warn("早班"),
        stage_gate_warn_body("早班", "12-17", stage_why("no_task", "12-17")), stage_refused("12-17", stage_why("no_task", "12-17")),
        *(stage_why(c, "12-17-1", "12", h) for c in ("no_chapter", "bad_difficulty", "no_reopen")
          for h in (True, False)),
        stage_why("no_difficulty", "12-17-1", "12", True), stage_why("no_difficulty", "12-17-1", "12", False),
        stage_gate_body("12-17", stage_why("no_task", "12-17"), True),
        stage_gate_body("12-17", stage_why("no_task", "12-17"), False),
        stage_gate_body("12-17", stage_why("no_task", "12-17"), None),
        stage_gate_report([("早班", "12-17", stage_why("no_task", "12-17"))]),
        MAA_SANITY_SHORT, maa_sanity_short_body(17, 25, "09:02"),
        *MAA_REJECT_WHY.values(), SANITY_UNREAD, NO_FIGHT,
        maa_rejected_line(maa_config_rejected("理智作战", "序列化失败", "1-7")),
        makeup_config_rejected(maa_config_rejected("理智作战", "序列化失败", "1-7")),
        makeup_config_rejected(maa_config_rejected("", "添加任务失败", "")),
        makeup_no_fight("基建换班"), makeup_unsure("MAA 在完成任务前中止"),
        makeup_only_gathering("10:24"), makeup_only_gathering(""),
        MAAEND_UPDATE_AFTER_DONE,
        cant_enter_body("MaaEnd", 3, False, "官方公告：今天 10:00「雪凇幽梦」版本更新", 30),
        failed_body_head(3),
        rerun_body(["OK-WW"]), watch_lost_body(), automas_down_body(4), automas_boot_down_body(),
        preupdate_unconfirmed_tail(), cant_enter_body("MaaEnd", 3, True, "", 30),
        missed_queue_body(30), missed_item_body(["MAA"], "OK-WW", 75),
        config_skip_body("终末地", config_skip_why("未找到终末地官方启动器, 请选择鹰角官方启动器 Launcher.exe 或 Games.exe！"),
                         "10-16 09:34（东京 10:34）", "早班"),
        config_skip_body("终末地", config_skip_why("未完成URL配置, 请检查"), "09:34", ""),
        attempt_timeout("鸣潮", "OK-WW"), shift_overrun("早班"), shift_no_result("早班"),
        MAAEND_STUCK_KILLED, MAAEND_STUCK_KILL_FAILED, MAAEND_WATCH_BLIND, maaend_watch_blind_body(10),
        MAA_START_STUCK_KILLED, MAA_START_STUCK_KILL_FAILED,
        maa_start_stuck_body("09:03", 5, 69, True, "", 5),
        maa_start_stuck_body("09:03", 25, 0, True, "", 5),
        maa_start_stuck_body("09:03", 5, 69, False, "退出码 128", 5),
        maaend_stuck_body(maaend_crash_reason("0xc0000005"), True, ""),
        maaend_stuck_body(maaend_crash_reason(""), False, "退出码 128"),
        maaend_stuck_body(maaend_plugin_gone_reason(60), True, ""),
        maaend_stuck_body(maaend_plugin_gone_reason(60), True, "", ["agent\\go-service.exe"]),
        maaend_stuck_body(maaend_stall_reason(10, "15:30:03"), False, "结束命令 30 秒没返回"),
        maaend_stuck_body(maaend_agreement_reason(), True, ""),
        maaend_stuck_body(maaend_logged_out_reason(), True, ""),
        machinecheck_failed("#4", "周本领奖"), machinecheck_failed_body("周本领奖", "领完奖再看选等级页，本周剩余次数没读到"),
        machinecheck_section([("#4", "周本领奖", "A", "PASS", "领完奖本周剩余 3/3→2/3", "2026-10-06 21:40:00"),
                              ("#11", "中继停下时推状态给手机", "B", "", "", "")],
                             [("#14", ("等待时间改写往返", "要我们这边在电脑上跑一个工具"))]),
        estop_farm_left_body("", "MAA、OK-WW"),
        estop_not_clean_body("鸣潮；AUTO-MAS 还记着有任务在跑：早班", "MAA", ""),
        echo_farm_game_left(["鸣潮（读不到正在运行的程序列表，查不到它还开没开着）"]), echo_farm_no_claim_left(r"C:\ProgramData\ark-okww-farm.no-claim"),
        echo_farm_boss_not_back(True), echo_farm_boss_not_back(False),
        okww_autostart_not_restored(True), okww_autostart_not_restored(False),
        SKIP_MARK_BROKEN, skip_restore_failed("早班", "写不进队列设置"),
        queue_item_deleted_old_way("早班", "OK-WW"),
        MAKEUP_RESTORE_PENDING, makeup_restore_skipped(""), makeup_restore_skipped("读不出母本"),
    ]


# ---- machine checks (machinecheck.py): changes confirmed on the machine by the machine ----
MACHINECHECK_FAIL = "🔬 上机核对没过"


def machinecheck_failed(cid: str, what: str) -> str:
    return f"{MACHINECHECK_FAIL}：{cid} {what}"


def machinecheck_failed_body(what: str, evidence: str) -> str:
    return (f"部署后机器自己核对「{what}」，这一次没过。\n"
            f"依据：{evidence or '（没有拿到依据）'}\n"
            "每次核对没过都会再报一次，直到修好。")


def machinecheck_section(rows: list, cannot: list) -> str:
    """The daily report's 「上机核对」 lines. rows: (id, what, kind, status, evidence, at) - status
    PASS / FAIL / HEALED (a PASS made up for by another run, machinecheck.daily_section)
    or '' for not judged yet; cannot: (id, (what, why))."""
    if not rows and not cannot:
        return ""
    mark = {"PASS": "✅", "FAIL": "❌"}
    lines = []
    for cid, what, kind, status, evidence, at in rows:
        if status == "HEALED":
            # A PASS only because another run of the day did what this one failed at.
            lines.append(f"↻ {cid} {what}：这一趟没过，同一天另一趟补上了：{evidence}（{at[5:16]}）")
        elif status in mark:
            lines.append(f"{mark[status]} {cid} {what}：{evidence}（{at[5:16]}）")
        else:
            wait = "等正常跑一趟" if kind == "A" else "等它自己被触发"
            lines.append(f"⏳ {cid} {what}：还没核（{wait}）")
    for cid, (what, why) in cannot:
        lines.append(f"✋ {cid} {what}：机器核不了，{why}")
    return "上机核对（部署后机器自己核）\n" + "\n".join(lines)
