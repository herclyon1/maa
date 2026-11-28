"""Every piece of copy pushed to the user, in this one module and nowhere else.

Three rules, set by the user:
1. **Plain language only**: the only English allowed is product names and
   「Boss」; task class names, exception names and raw log text never reach a
   notification.
2. **Nothing vague**: 「出错」「异常」「有问题」「这一步」「未知」 must not stand
   alone as a verdict - if it can be translated, write the specific thing; if it
   cannot, say so outright with 「中继还不认识，原文已记日志」.
3. **Same kind, same phrasing**: the three weeklies read alike, and so do the
   update notifications for the four programs.

`tests/test_texts_gate.py` enforces this: every notifier.send title in the code
must come from here, and every sentence here - along with the Chinese lookup
tables elsewhere - has to pass `plain()`.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from ark_relay.core.config import GAME_ZH

# English that is allowed: product names, common in-game terms, and commands a
# person has to copy verbatim.
ALLOWED_WORDS = {
    "MAA", "MaaEnd", "OK-WW", "AUTO-MAS", "MXU", "Boss", "Annihilation", "F2",
    "PIN", "net", "stop", "start", "ark-relay", "deploy-relay.sh", "scripts/mac/deploy-relay.sh",
    "MuMu", "APK", "v",
    "DirectX",      # the Endfield launcher's own label 「DirectX 11 启动」 (ENDFIELD_NO_MAAEND_START)
}
# Hedges are vagueness too: a sentence either states what was measured or says
# outright what could not be read - it never guesses.
VAGUE = ("未知错误", "这一步", "有问题", "出错",
         "多半", "可能", "大概", "大约", "应该是", "似乎", "疑似", "也许", "或许",
         "估计", "差不多", "左右", "好像", "不确定", "貌似", "大致", "约 ", "约一", "不一定")


# ==============================================================================
# 单遍确定性字符状态机词法分析器（Single-Pass Lexer）
#
# 设计原则（替代旧版互相打架的混合正则）：
# 1. 从左到右单遍扫描文本，按严格优先级一次性切出互不重叠的强类型 Token：
#    URL > UNC_PATH > WIN_PATH > REL_PATH > DATE > TIME > HEX > SEMVER > FLOAT/INT > IDENT > ZH > WS/PUNCT；
# 2. URL 走字符状态机 + urllib.parse.urlsplit 校验，遇中文/空白/非配对括号、紧跟字母的 ,/; /!
#    或路径后的 :异常类 立刻硬截停，绝不吞并紧贴 URL 的异常类名与 HTTP 头；
# 3. UNC 网络路径（\\host\share\...）一等建模，完整保留前导 \\；
# 4. Windows 盘符路径（WIN_PATH）取消扩展名白名单与 5 词上限，仅凭“段尾无 .ext + 后续先见 \ +
#    下词非异常边界词”三条硬条件决定空格是否归入目录名；
# 5. 相对/Unix 路径（REL_PATH）走严格正向白名单（已知真实扩展名，或 ./ ../ ~/ 与真实 Unix 根），
#    从源头杜绝 ValueError/KeyError、QUIC/v1、HTTP/2.0-draft、TLS/SSL、foo/bar、MIME 穿透门禁；
# 6. 日期/时间/预发布版本号/十六进制/浮点数均为独立原子 Token，数学上永不误拆成整数退出码或残渣 0。
# ==============================================================================

@dataclass(frozen=True)
class Token:
    """词法分析器切出的单个不可重叠词元。"""

    kind: str
    raw: str
    start: int
    end: int


class _LexSpec:
    """词法分析器内部规格表（封装为类命名空间，不混入对外文案常量集合）。"""

    # 允许作为真实文件路径后缀的扩展名（小写，不含点；刻意排除 .ops / .rst 等非项目后缀）。
    FILE_EXTS = frozenset({
        "py", "rs", "cs", "js", "ts", "jsonl", "json", "log", "txt", "md",
        "yaml", "yml", "toml", "ini", "cfg", "conf", "exe", "dll", "dmp",
        "bat", "cmd", "ps1", "sh", "zip", "gz", "zst", "db", "sqlite",
        "png", "jpg", "jpeg", "webp", "csv", "xml", "html", "swift",
        "lock", "flag", "bak", "tmp", "pth", "whl", "env", "dat",
    })
    # 允许作为无扩展名路径的真实 Unix 根目录前缀。
    UNIX_ROOTS = (
        "/Users/", "/opt/", "/etc/", "/var/", "/tmp/", "/home/", "/usr/", "/bin/",
    )
    # 通知文案与机器核对里固定出现的已知相对目录名/前缀（不含扩展名）。
    ALLOWED_REL_DIRS = frozenset({
        "resource/tasks",
        "scripts/mac/deploy-relay.sh",
    })
    ALLOWED_REL_PREFIXES = (
        "shots/",
        "state/shots/",
    )
    # RFC 3986 网址主体合法 ASCII 字符集合（不含空白、引号、反斜杠、尖括号与非 ASCII）。
    URL_CHARS = frozenset(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        "-._~:/?#@!$&*+,;=%()[]"
    )
    # Windows 目录/文件名单段内允许的常规 ASCII 字符（不含非法字符 <>:"|?*、引号、逗号、分号、感叹号）。
    WIN_SEG_CHARS = frozenset(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.+~@#%-"
    )
    # 相对/Unix 路径允许的 ASCII 字符（含路径分隔符 / 与 \，不含冒号、逗号、分号、引号、括号）。
    REL_PATH_CHARS = frozenset(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.+~@#%-/\\"
    )
    # 十六进制数字字符集合。
    HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
    # Windows 含空格目录续扫时不得跨过的 Python 异常/堆栈/协议边界词（小写）。
    WIN_SPACE_STOP_EXACT = frozenset({
        "traceback", "winerror", "errno", "http", "https", "grpc",
        "subprocess", "waitpid", "exited", "returned", "returncode",
        "calledprocesserror",
    })
    # 紧跟在路径/URL 冒号后判定为异常/协议边界的词尾与全称。
    EXC_SUFFIXES = ("error", "exception", "failure", "warning")
    # 段尾任意 1~6 位字母数字扩展名（用于 Windows 路径空格续扫阻断与 URL .ext:Ident 截停，不依赖扩展名白名单）。
    ANY_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,6}$")
    # 预发布版本号后缀（如 -beta.1、-rc-1、-rc.3、-rc3、-alpha-1，排除 -RuntimeError 等异常类名）。
    PRERELEASE_RE = re.compile(
        r"^(?:-(?:(?:alpha|beta|rc|pre|dev|preview|nightly|canary|snapshot|post|patch|hotfix|rel|release|build)"
        r"(?:[.-]?\d+)*|[abr]\d+(?:[.-]\d+)*|\d+(?:\.\d+)*))+"
    )
    # Windows 含空格目录向后探路时遇到即判“不再属于当前 Windows 路径”的字符。
    WIN_LOOKAHEAD_FORBID = frozenset('<>:"|?*\'`;,!/\n\r\t[]')
    # 常见命令行可执行名称（统一映射为 .exe 标准展示名，保持既有优先级顺序）。
    CMD_SPECS = (
        (re.compile(r"^(?:pwsh|powershell)(?:\.exe)?$", re.I), "pwsh.exe"),
        (re.compile(r"^schtasks(?:\.exe)?$", re.I), "schtasks.exe"),
        (re.compile(r"^taskkill(?:\.exe)?$", re.I), "taskkill.exe"),
        (re.compile(r"^tasklist(?:\.exe)?$", re.I), "tasklist.exe"),
        (re.compile(r"^wevtutil(?:\.exe)?$", re.I), "wevtutil.exe"),
        (re.compile(r"^shutdown(?:\.exe)?$", re.I), "shutdown.exe"),
        (re.compile(r"^adb(?:\.exe)?$", re.I), "adb.exe"),
        (re.compile(r"^pip(?:\.exe)?$", re.I), "pip.exe"),
        (re.compile(r"^git(?:\.exe)?$", re.I), "git.exe"),
        (re.compile(r"^ssh(?:\.exe)?$", re.I), "ssh.exe"),
        (re.compile(r"^curl(?:\.exe)?$", re.I), "curl.exe"),
        (re.compile(r"^pythonw?(?:\.exe)?$", re.I), "python.exe"),
    )
    # 退出语境下的外部命令名与触发词。
    PROC_CTX_WORDS = frozenset({
        "calledprocesserror", "subprocess", "waitpid",
        "taskkill", "tasklist", "pwsh", "schtasks", "wevtutil", "shutdown", "adb", "git", "ssh",
    })
    PROC_CTX_SUBJECTS = frozenset({"process", "child"})
    PROC_CTX_VERBS = frozenset({"ended", "exited", "terminated", "failed", "died", "crashed", "killed", "returned"})
    # 十六进制字节值前置词（如 UnicodeDecodeError 里的 byte 0xff，不算系统错误码）。
    BYTE_HEX_PREFIXES = frozenset({"byte", "bytes", "char", "character", "octet", "position", "offset"})
    # 显式退出码单词键（统一小写并折叠 _ 与 - 后比对）。
    EXIT_KEY_SINGLE = frozenset({
        "exitstatus", "exitstatuscode", "exitcode", "returncode", "rc",
    })
    # 显式 HTTP 状态码键（含下划线、连字符与驼峰 httpStatus / httpStatusCode）。
    HTTP_EXPLICIT_KEYS = frozenset({
        "httpstatus", "httpstatuscode",
    })
    # JSON 引号键或普通键值里的通用状态码名（含 statusCode / status_code / status-code）。
    STATUS_CODE_KEYS = frozenset({
        "statuscode",
    })
    GENERIC_STATUS_KEYS = frozenset({
        "status", "statuscode", "httpstatus", "httpstatuscode",
    })


def _is_ascii_alnum(ch: str) -> bool:
    """判断单个字符是否为 ASCII 字母或数字。"""
    return ch.isascii() and ch.isalnum()


def _is_ascii_ident_char(ch: str) -> bool:
    """判断单个字符是否为 ASCII 字母、数字或下划线。"""
    return ch.isascii() and (ch.isalnum() or ch == "_")


def _is_ascii_alpha(ch: str) -> bool:
    """判断单个字符是否为 ASCII 字母。"""
    return ch.isascii() and ch.isalpha()


def _is_exc_or_proto_word(word: str) -> bool:
    """判断英文标识符是否为异常/错误类名或协议边界词（如 PermissionError、HTTP、Traceback）。"""
    low = word.lower()
    if low in _LexSpec.WIN_SPACE_STOP_EXACT:
        return True
    return len(low) > 5 and low.endswith(_LexSpec.EXC_SUFFIXES)


def _scan_url_authority(text: str, start: int) -> tuple[int, bool]:
    """扫描 URL 的 authority 部分（含可选 userinfo@、IPv6 [...] 主机与 :port）。

    返回 (authority 结束位置, 是否允许继续扫描 path/query/fragment)。
    遇到非端口冒号（如 https://example.com:PermissionError）会立刻停止，不吞冒号与异常名。
    """
    n = len(text)
    j = start
    # 检查 authority 范围内是否存在 userinfo@（在首个 / ? # 空白 非ASCII 之前）。
    at_pos = -1
    k = j
    while k < n and text[k] not in "/?# \t\r\n" and ord(text[k]) < 128:
        if text[k] == "@":
            at_pos = k
            break
        k += 1
    if at_pos > j:
        j = at_pos + 1

    host_start = j
    if j < n and text[j] == "[":
        # IPv6 字面量主机，例如 [::1] 或 [2001:db8::1]。
        j += 1
        while j < n and text[j] in "0123456789abcdefABCDEF:.%":
            j += 1
        if j >= n or text[j] != "]":
            return start, False
        j += 1
    else:
        while j < n:
            c = text[j]
            if c in ",;!" and j + 1 < n and _is_ascii_alpha(text[j + 1]):
                break
            if c.isascii() and (c.isalnum() or c in "-._~%"):
                j += 1
            else:
                break

    if j == host_start:
        return start, False

    # 可选 :port（仅接受纯数字端口；遇到 :PermissionError 立刻截停）。
    if j < n and text[j] == ":":
        p = j + 1
        while p < n and text[p].isascii() and text[p].isdigit():
            p += 1
        if p > j + 1 and (p >= n or not _is_ascii_ident_char(text[p])):
            j = p
        else:
            return j, False
    return j, True


def _scan_url(text: str, i: int) -> int:
    """在位置 i 尝试扫描 RFC 3986 ASCII URL，并用 urllib.parse.urlsplit 校验合法性。"""
    n = len(text)
    if i > 0 and _is_ascii_ident_char(text[i - 1]):
        return i
    head = text[i:i + 8].lower()
    if head.startswith("https://"):
        auth_start = i + 8
    elif head.startswith("http://"):
        auth_start = i + 7
    else:
        return i

    j, allow_tail = _scan_url_authority(text, auth_start)
    if j == auth_start:
        return i

    paren_stack: list[int] = []
    bracket_stack: list[int] = []
    if allow_tail and j < n and text[j] in "/?#":
        path_start = j
        in_query_or_frag = text[j] in "?#"
        while j < n:
            c = text[j]
            if c.isspace() or ord(c) >= 128 or c not in _LexSpec.URL_CHARS:
                break
            if c in "?#":
                in_query_or_frag = True
            # 硬截停 1：, / ; / ! 后紧跟 ASCII 字母（如 ,HTTP/1.1、;RuntimeError、!KeyError）。
            if c in ",;!" and j + 1 < n and _is_ascii_alpha(text[j + 1]):
                break
            # 硬截停 2：进入 path 后遇 : 紧跟 ASCII 标识符（如 a.json:PermissionError 或 :RuntimeError:）。
            if c == ":" and j + 1 < n and (_is_ascii_alpha(text[j + 1]) or text[j + 1] == "_"):
                k = j + 1
                while k < n and (_is_ascii_ident_char(text[k]) or text[k] == "."):
                    k += 1
                ident = text[j + 1:k]
                is_nested_scheme = in_query_or_frag and ident.lower() in ("http", "https") and text[k:k + 2] == "//"
                if not is_nested_scheme:
                    has_second_colon = k < n and text[k] == ":"
                    after_ext = (not in_query_or_frag) and bool(_LexSpec.ANY_EXT_RE.search(text[path_start:j]))
                    if has_second_colon or after_ext or _is_exc_or_proto_word(ident):
                        break
            # 跟踪成对 () 与 []，未配对的闭括号不属于 URL。
            if c == "(":
                paren_stack.append(j)
            elif c == ")":
                if not paren_stack:
                    break
                paren_stack.pop()
            elif c == "[":
                bracket_stack.append(j)
            elif c == "]":
                if not bracket_stack:
                    break
                bracket_stack.pop()
            j += 1

    # 若 URL 内有未闭合开括号（如 https://x/a.json(TimeoutError），退回到开括号前。
    if paren_stack or bracket_stack:
        j = min((*paren_stack, *bracket_stack))
    while j > i and text[j - 1] in ".,;:!?":
        j -= 1
    if j <= auth_start:
        return i

    cand = text[i:j]
    try:
        parsed = urlsplit(cand)
        _ = parsed.port
    except ValueError:
        return i
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return i
    return j


def _ahead_has_win_backslash(text: str, pos: int) -> bool:
    """检查从 pos 起在同一行遇到任何 Windows 非法字符、引号、斜杠或非 ASCII 前能否先遇到反斜杠 \\。"""
    n = len(text)
    k = pos
    paren_depth = 0
    while k < n:
        c = text[k]
        if c == "\\":
            return paren_depth == 0
        if ord(c) >= 128 or c in _LexSpec.WIN_LOOKAHEAD_FORBID:
            return False
        if c == "(":
            paren_depth += 1
        elif c == ")":
            if paren_depth == 0:
                return False
            paren_depth -= 1
        k += 1
    return False


def _next_word_after_space(text: str, pos: int) -> str:
    """提取空格后紧跟的第一个英文词（若被圆括号包住如 (x86) 则取括号内词）。"""
    n = len(text)
    k = pos
    if k < n and text[k] == "(":
        k += 1
    start = k
    while k < n and (_is_ascii_ident_char(text[k]) or text[k] in ".-"):
        k += 1
    return text[start:k]


def _scan_win_segments(text: str, start: int, allow_slash: bool) -> int:
    """沿 Windows 目录段推进，按三条硬条件决定空格是否属于目录名（无扩展名白名单与词数上限）。"""
    n = len(text)
    j = start
    seg_start = start
    last_good = start
    while j < n:
        c = text[j]
        if c == "\\":
            while j < n and text[j] == "\\":
                j += 1
            seg_start = j
            continue
        if c == "/" and allow_slash:
            if j + 1 < n and text[j + 1] == "/":
                break
            j += 1
            seg_start = j
            continue
        if c == " ":
            # 仅同时满足三条件才把空格归入目录名：
            # ① 当前段空格前不带任何 .ext（不依赖写死的扩展名白名单）；
            # ② 同行后续在遇 Windows 非法字符/引号/中文/斜杠前能先遇下一个 \；
            # ③ 空格后首词不是 Python 异常/堆栈/协议边界词。
            cur_seg = text[seg_start:j]
            nxt_word = _next_word_after_space(text, j + 1)
            if (
                cur_seg
                and j + 1 < n
                and text[j + 1] != " "
                and not _LexSpec.ANY_EXT_RE.search(cur_seg)
                and _ahead_has_win_backslash(text, j + 1)
                and not _is_exc_or_proto_word(nxt_word)
            ):
                j += 1
                continue
            break
        if c == "(":
            # 仅放行目录/文件名里的简单成对括号（如 Program Files (x86)），绝不吞 (TimeoutError。
            if _LexSpec.ANY_EXT_RE.search(text[seg_start:j]):
                break
            close = j + 1
            while close < n and text[close] not in ")\r\n\\/":
                if ord(text[close]) >= 128 or text[close] in _LexSpec.WIN_LOOKAHEAD_FORBID:
                    close = -1
                    break
                close += 1
            if close <= j + 1 or close >= n or text[close] != ")":
                break
            inner = text[j + 1:close].strip()
            if not inner or any(_is_exc_or_proto_word(w) for w in inner.split()):
                break
            j = close + 1
            last_good = j
            continue
        if c in _LexSpec.WIN_SEG_CHARS:
            j += 1
            last_good = j
            continue
        break

    while last_good > start and text[last_good - 1] in ".,;:!?":
        last_good -= 1
    return last_good


def _scan_unc_path(text: str, i: int) -> int:
    """在位置 i 尝试扫描 UNC 网络路径（如 \\\\server\\share\\a.log 或 \\\\server\\share\\readme）。"""
    n = len(text)
    if not text.startswith("\\\\", i):
        return i
    if i > 0 and (_is_ascii_ident_char(text[i - 1]) or text[i - 1] in "\\:"):
        return i
    j = i
    while j < n and text[j] == "\\":
        j += 1
    if j - i < 2 or j >= n or not _is_ascii_alnum(text[j]):
        return i
    # 扫描主机名 <host>
    host_start = j
    while j < n and (text[j].isascii() and (text[j].isalnum() or text[j] in "_.-")):
        j += 1
    if j == host_start or j >= n or text[j] != "\\":
        return i
    while j < n and text[j] == "\\":
        j += 1
    # 扫描共享名 <share>
    share_start = j
    if j >= n or not (_is_ascii_ident_char(text[j]) or text[j] == "$"):
        return i
    while j < n and (text[j] in _LexSpec.WIN_SEG_CHARS or text[j] == "$"):
        j += 1
    if j == share_start:
        return i
    end = j
    if j < n and text[j] == "\\":
        tail_end = _scan_win_segments(text, j, allow_slash=False)
        if tail_end > j:
            end = tail_end
    while end > i and text[end - 1] in ".,;:!?":
        end -= 1
    return end


def _scan_win_path(text: str, i: int) -> int:
    """在位置 i 尝试扫描 Windows 盘符路径（[A-Za-z]:\\... 或 [A-Za-z]:/...）。"""
    n = len(text)
    if i + 2 >= n or not _is_ascii_alpha(text[i]) or text[i + 1] != ":" or text[i + 2] not in "\\/":
        return i
    if i > 0 and _is_ascii_ident_char(text[i - 1]):
        return i
    j = i + 2
    if text[j] == "/":
        if j + 1 < n and text[j + 1] == "/":
            return i
        j += 1
    else:
        while j < n and text[j] == "\\":
            j += 1
    end = _scan_win_segments(text, j, allow_slash=True)
    if end <= j:
        return i
    return end


def _has_known_file_ext(cand: str) -> bool:
    """判断候选相对路径是否以已知真实文件扩展名结尾（且扩展名前有合法文件名主干）。"""
    # 取最后一段文件名（兼容 / 与 \ 分隔符）。
    base = cand.replace("\\", "/").rsplit("/", 1)[-1]
    if base.lower() == ".env":
        return True
    dot = base.rfind(".")
    if dot <= 0:
        return False
    stem, ext = base[:dot], base[dot + 1:].lower()
    if ext not in _LexSpec.FILE_EXTS:
        return False
    # 主干末尾必须是字母、数字、下划线或连字符，杜绝 foo..py。
    return bool(stem) and (stem[-1].isascii() and (stem[-1].isalnum() or stem[-1] in "_-"))


def _scan_rel_path(text: str, i: int) -> int:
    """严格正向白名单扫描相对/Unix 路径（绝不把 ValueError/KeyError、QUIC/v1、TLS/SSL、foo/bar 当路径）。"""
    n = len(text)
    if i > 0 and (_is_ascii_ident_char(text[i - 1]) or text[i - 1] in "/\\"):
        return i
    ch = text[i]
    if ch not in _LexSpec.REL_PATH_CHARS:
        return i

    # 情形 1：显式相对/家目录/Unix 根目录前缀（./ ../ ~/ 或 /Users/ 等）。
    has_explicit_root = (
        text.startswith("./", i)
        or text.startswith("../", i)
        or text.startswith("~/", i)
        or any(text.startswith(root, i) for root in _LexSpec.UNIX_ROOTS)
    )
    if ch == "/" and not has_explicit_root:
        return i

    j = i
    while j < n and text[j] in _LexSpec.REL_PATH_CHARS:
        # 避免跨入 //（URL 或注释）。
        if text[j] == "/" and j + 1 < n and text[j + 1] == "/":
            break
        j += 1
    while j > i and text[j - 1] in ".,;:!?":
        j -= 1
    cand = text[i:j]
    if not cand:
        return i

    # 情形 1 落地：显式前缀后须至少包含一个有效路径字符。
    if has_explicit_root:
        prefix_len = 2 if cand.startswith(("./", "~/")) else 3 if cand.startswith("../") else next(
            len(r) for r in _LexSpec.UNIX_ROOTS if cand.startswith(r)
        )
        if len(cand) > prefix_len:
            return j
        return i

    # 情形 2：文案固定目录白名单（如 resource/tasks）与中继截图相对目录前缀（如 shots/2026-10-08/MaaEnd-10-32-23）。
    if cand in _LexSpec.ALLOWED_REL_DIRS:
        return j
    for rel_pre in _LexSpec.ALLOWED_REL_PREFIXES:
        if cand.startswith(rel_pre) and len(cand) > len(rel_pre):
            return j

    # 情形 3：以已知真实文件扩展名结尾的相对路径或独立文件名（如 a/b.txt、debug\maafw.log、state.json）。
    if not cand.startswith(("/", "\\")) and _has_known_file_ext(cand):
        return j
    return i


def _scan_date(text: str, i: int) -> int:
    """在位置 i 尝试扫描 YYYY-MM-DD 或 YYYY/MM/DD 日期原子词元。"""
    n = len(text)
    if i + 10 > n:
        return i
    if i > 0 and (_is_ascii_ident_char(text[i - 1]) or text[i - 1] in "-/"):
        return i
    sep = text[i + 4]
    if sep not in "-/" or text[i + 7] != sep:
        return i
    y, m, d = text[i:i + 4], text[i + 5:i + 7], text[i + 8:i + 10]
    if not (y.isascii() and y.isdigit() and m.isascii() and m.isdigit() and d.isascii() and d.isdigit()):
        return i
    if not (1 <= int(m) <= 12 and 1 <= int(d) <= 31):
        return i
    end = i + 10
    if end < n and ((text[end].isascii() and text[end].isdigit()) or text[end] == sep):
        return i
    return end


def _scan_time(text: str, i: int) -> int:
    """在位置 i 尝试扫描 HH:MM 或 HH:MM:SS 时刻原子词元。"""
    n = len(text)
    if i + 5 > n or text[i + 2] != ":":
        return i
    if i > 0 and (_is_ascii_ident_char(text[i - 1]) or text[i - 1] == ":"):
        return i
    hh, mm = text[i:i + 2], text[i + 3:i + 5]
    if not (hh.isascii() and hh.isdigit() and mm.isascii() and mm.isdigit()):
        return i
    if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
        return i
    end = i + 5
    if end + 3 <= n and text[end] == ":":
        ss = text[end + 1:end + 3]
        if ss.isascii() and ss.isdigit() and 0 <= int(ss) <= 59:
            end += 3
    if end < n and (_is_ascii_ident_char(text[end]) or text[end] == ":"):
        return i
    return end


def _scan_hex(text: str, i: int) -> int:
    """在位置 i 尝试扫描 0x[0-9a-fA-F]+ 十六进制原子词元（如 0xc0000005）。"""
    n = len(text)
    if i + 3 > n or text[i] != "0" or text[i + 1] not in "xX":
        return i
    if i > 0 and _is_ascii_ident_char(text[i - 1]):
        return i
    j = i + 2
    while j < n and text[j] in _LexSpec.HEX_DIGITS:
        j += 1
    if j == i + 2 or (j < n and _is_ascii_ident_char(text[j])):
        return i
    return j


def _scan_semver(text: str, i: int) -> int:
    """在位置 i 尝试扫描版本号原子词元（如 v2.34.0-rc-1、v2.28.0-beta.1、v1.0.0-alpha-1、v20261005151027）。"""
    n = len(text)
    # 紧跟在 / 后的（如 QUIC/v1、HTTP/2.0-draft）绝不当版本号放行。
    if i > 0 and (_is_ascii_ident_char(text[i - 1]) or text[i - 1] in "/."):
        return i
    j = i
    has_v = text[j] == "v"
    if has_v:
        j += 1
    if j >= n or not (text[j].isascii() and text[j].isdigit()):
        return i
    while j < n and text[j].isascii() and text[j].isdigit():
        j += 1
    dots = 0
    while j + 1 < n and text[j] == "." and text[j + 1].isascii() and text[j + 1].isdigit():
        dots += 1
        j += 1
        while j < n and text[j].isascii() and text[j].isdigit():
            j += 1
    # 尝试匹配合法预发布尾缀（如 -rc-1、-beta.1、-alpha-1、-rc3）。
    has_pre = False
    if j < n and text[j] == "-":
        if m := _LexSpec.PRERELEASE_RE.match(text[j:]):
            cand_end = j + m.end()
            if cand_end >= n or not _is_ascii_ident_char(text[cand_end]):
                j = cand_end
                has_pre = True
    # 无前导 v 时，必须至少包含一个点号且至少三段（1.2.3）或带合法预发布尾缀（2.0-rc.1），
    # 避免把普通小数 1.5 或关卡/短日期 11-28、12-17 误标为 SEMVER。
    if not has_v and (dots < 1 or (dots < 2 and not has_pre)):
        return i
    if j < n and _is_ascii_ident_char(text[j]):
        return i
    return j


def _scan_number(text: str, i: int) -> tuple[str, int]:
    """在位置 i 扫描独立整数 INT 或浮点数 FLOAT（若数字后紧贴字母则返回 OTHER，防误判退出码）。"""
    n = len(text)
    j = i
    if text[j] == "-":
        # 仅当负号位于一元语境（开头、空白或 = : ： ( [ , { 之后）才归入负数，
        # 从而 exit-status-500 切为 IDENT + '-' + 正整数 500，而 returncode=-1 切为负整数 -1。
        if j + 1 >= n or not (text[j + 1].isascii() and text[j + 1].isdigit()):
            return "", i
        if i > 0 and not (text[i - 1].isspace() or text[i - 1] in "=:：([,{"):
            return "", i
        j += 1
    if j >= n or not (text[j].isascii() and text[j].isdigit()):
        return "", i
    while j < n and text[j].isascii() and text[j].isdigit():
        j += 1
    if j + 1 < n and text[j] == "." and text[j + 1].isascii() and text[j + 1].isdigit():
        while j + 1 < n and text[j] == "." and text[j + 1].isascii() and text[j + 1].isdigit():
            j += 1
            while j < n and text[j].isascii() and text[j].isdigit():
                j += 1
        if j < n and _is_ascii_ident_char(text[j]):
            return "OTHER", j
        return "FLOAT", j
    if j < n and _is_ascii_ident_char(text[j]):
        return "OTHER", j
    return "INT", j


def _scan_ident(text: str, i: int) -> int:
    """在位置 i 扫描 ASCII 标识符（允许连字符连接字母段，如 OK-WW、AUTO-MAS、exit-status）。"""
    n = len(text)
    if not _is_ascii_alpha(text[i]):
        return i
    j = i + 1
    while j < n and _is_ascii_ident_char(text[j]):
        j += 1
    while j + 1 < n and text[j] == "-" and _is_ascii_alpha(text[j + 1]):
        j += 2
        while j < n and _is_ascii_ident_char(text[j]):
            j += 1
    return j


def _lex_text(text: str) -> list[Token]:
    """单遍确定性字符状态机词法分析器：一次性将文本切分为互不重叠的强类型 Token 序列。"""
    tokens: list[Token] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        # 1. 空白字符（保留换行以便上层识别行首堆栈帧）。
        if ch.isspace():
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            tokens.append(Token("WS", text[i:j], i, j))
            i = j
            continue
        # 2. 汉字连续片段。
        if "\u4e00" <= ch <= "\u9fff":
            j = i + 1
            while j < n and "\u4e00" <= text[j] <= "\u9fff":
                j += 1
            tokens.append(Token("ZH", text[i:j], i, j))
            i = j
            continue
        # 3. URL（http:// / https://）。
        if ch in "hH" and (end := _scan_url(text, i)) > i:
            tokens.append(Token("URL", text[i:end], i, end))
            i = end
            continue
        # 4. UNC 网络路径（\\host\share\...）。
        if ch == "\\" and (end := _scan_unc_path(text, i)) > i:
            tokens.append(Token("UNC_PATH", text[i:end], i, end))
            i = end
            continue
        # 5. Windows 盘符路径（C:\... 或 d:/...）。
        if _is_ascii_alpha(ch) and (end := _scan_win_path(text, i)) > i:
            tokens.append(Token("WIN_PATH", text[i:end], i, end))
            i = end
            continue
        # 6. 严格正向白名单相对/Unix 路径。
        if ch in _LexSpec.REL_PATH_CHARS and (end := _scan_rel_path(text, i)) > i:
            tokens.append(Token("REL_PATH", text[i:end], i, end))
            i = end
            continue
        # 7. 原子字面量：DATE / TIME / HEX / SEMVER / FLOAT / INT。
        if ch.isascii() and ch.isdigit():
            for kind, scanner in (
                ("DATE", _scan_date),
                ("TIME", _scan_time),
                ("HEX", _scan_hex),
                ("SEMVER", _scan_semver),
            ):
                if (end := scanner(text, i)) > i:
                    tokens.append(Token(kind, text[i:end], i, end))
                    i = end
                    break
            else:
                num_kind, end = _scan_number(text, i)
                if end > i:
                    tokens.append(Token(num_kind, text[i:end], i, end))
                    i = end
                else:
                    tokens.append(Token("PUNCT", ch, i, i + 1))
                    i += 1
            continue
        if ch == "v" and (end := _scan_semver(text, i)) > i:
            tokens.append(Token("SEMVER", text[i:end], i, end))
            i = end
            continue
        if ch == "-":
            num_kind, end = _scan_number(text, i)
            if end > i:
                tokens.append(Token(num_kind, text[i:end], i, end))
                i = end
                continue
        # 8. ASCII 标识符（用于 plain() 英文拦截、异常识别、退出码/HTTP 键值提取）。
        if _is_ascii_alpha(ch):
            end = _scan_ident(text, i)
            tokens.append(Token("IDENT", text[i:end], i, end))
            i = end
            continue
        # 9. 其他标点或符号。
        tokens.append(Token("PUNCT", ch, i, i + 1))
        i += 1
    return tokens


# Engineering words that mean nothing to the reader. A sentence has to say what
# happens in the game or on the phone, not what the code did.
JARGON = ("落盘", "回读", "兜底", "字段", "判据", "判定点", "监听", "句柄", "进程", "线程",
          "缓存", "重放", "拉起", "收窄", "节点", "实例", "退避", "调度器", "死键", "标记文件",
          "时间窗", "任务链", "冲掉", "结构化", "白名单", "凭空造", "原子", "幂等", "接口")


def plain(text: str) -> list[str]:
    """基于单遍词法分析器的正向白名单人话检查：返回空列表表示全部合规。"""
    problems: list[str] = []
    # 仅跳过合法 URL / 路径 / 十六进制 / 日期 / 时间 / 版本号与显式允许词，其余英文一律拦截。
    for tok in _lex_text(text):
        if tok.kind == "IDENT" and tok.raw not in ALLOWED_WORDS:
            problems.append(f"英文「{tok.raw}」")
    for v in VAGUE:
        if v in text:
            problems.append(f"模糊词「{v}」")
    # Names the programs themselves use are not our jargon: 「结束进程」 is a MaaEnd task.
    scrubbed = text
    for term in _THEIR_TERMS:
        scrubbed = scrubbed.replace(term, " ")
    for j in JARGON:
        if j in scrubbed:
            problems.append(f"术语「{j}」")
    return problems


# Quoted verbatim from logs, matched but never said to a person: upstream's
# 「结束进程」, the overlay's weekly read-back lines (outcome.WEEKLY_CLAIM_*), and
# AUTO-MAS's result text that ledger_report.plain_words rewrites before the report,
# AUTO-MAS's line for ending a MaaEnd that did not exit (collector._automas_ended_maaend),
# and the tag of AUTO-MAS's config-check refusal line (runwatch._CONFIG_SKIP; the message
# says config_skip_why instead).
_THEIR_TERMS = ("结束进程", "周本领奖：回读", "MaaEnd 进程超时", "进程未退出", "调度器 \\| 未通过配置检查")


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


def relay_error_body(where: str, what: str, at: str = "") -> str:
    """`where` is the logger name, `what` the first line of the WARNING / ERROR record,
    `at` when it was logged (errwatch.span).

    The record's own words are quoted only when they read as plain language;
    a line full of class names or English is said by the cause it names (_said),
    never a bare 「出错」.
    """
    part = relay_part(where)
    when = f"（{at}）" if at else ""
    return f"中继自己报错了{when}，出在「{part}」。{_said(what)}\n" + RELAY_ERROR_TAIL


def relay_error_line(where: str, what: str, at: str, fixed_in: str = "", fixed_what: str = "") -> str:
    """One record in a merged push (errwatch.merge): when, where, what it said."""
    again = ""
    if fixed_in:
        again = f"，v{fixed_in} 修过的又出现了" + (f"（当时修的是：{fixed_what}）" if fixed_what else "")
    return f"· {at}，出在「{relay_part(where)}」{again}。{_said(what)}"


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
# 故障词法拆解与白话渲染管线（替代旧版堆叠正则）
#
# 核心原则：
# 1. 合法 HTTP 状态码用有限集合 _VALID_HTTP_CODES 显式穷举，126/127/128/255 等退出码
#    在数学上绝不可能落进 HTTP 状态码分支；
# 2. 先剥离 URL、协议头（HTTP/1.1 等）与 MIME 类型（application/json 等），再按真实磁盘
#    路径或真实扩展名提取文件，按 (类型, 归一化值) 严格去重；
# 3. 先按「｜」或首个技术诊断起点把原始日志切为「中文业务主干」与「技术诊断片段」，
#    彻底杜绝挖词留下的 _=429、: : 22.、尾随 128 等乱码残片；
# 4. 纯中文路径（_said）与含英文路径（format_fault_reason）统一过白话术语/模糊词规范化，
#    保证最终推群内容 100% 通过 plain() 门禁。
# ==============================================================================

# 显式有限合法 HTTP 状态码集合（常见 RFC 响应码 + Cloudflare 52x）：
# 非法码（如 001/126/127/128/255/999）永远不会进入 HTTP 分支。
_VALID_HTTP_CODES = frozenset({
    100, 101,
    200, 201, 202, 204,
    301, 302, 304, 307, 308,
    400, 401, 403, 404, 405, 408, 409, 410, 413, 415, 418, 422, 429, 451,
    500, 502, 503, 504, 520, 521, 522, 524,
})


@dataclass(frozen=True)
class FaultInfo:
    """单条报错日志经词法拆解后的故障描述，用于统一模板拼装白话中文。"""

    head_zh: str = ""
    fault_kind: str = ""
    exit_code: int | str | None = None
    http_code: int | None = None
    win_error: int | None = None
    files: tuple[str, ...] = ()
    cmds: tuple[str, ...] = ()
    url: str = ""
    hex_code: str = ""


# 各故障类别对应的白话中文主因文案（不含括号细节，由 _render_fault 统一拼成单层括号）。
_FAULT_TEMPLATES = {
    "dns": "域名解析失败，机器当时连不上网络",
    "timeout": "连接或读写超时",
    "conn_reset": "对方拒绝连接，或者连上后中途断开了",
    "file_in_use": "文件正被其他程序占用",
    "permission": "没有权限读写要用的文件，或者文件正被其他程序占用",
    "process_exit": "外部命令执行失败",
    "http_error": "对方服务器返回了状态码",
    "not_found": "找不到要用的文件",
    "json_bad": "收到的数据格式是坏的",
    "encoding": "文本编码读取失败",
    "ssl": "加密连接没建立起来",
    "url_error": "网络请求没发出去，或者没收到回答",
    "import_error": "运行环境缺少必需组件",
    "db_error": "本地数据库正被占用或损坏",
    "key_error": "读取数据时缺少必要内容",
    "attr_error": "程序对象缺少预期能力",
    "type_error": "程序处理的数据类型不对",
    "index_error": "读取列表时越界",
    "value_error": "数据数值或格式不对",
    "zero_div": "程序计算时出现除以零",
    "win_error": "系统调用失败",
    "com_error": "系统组件调用失败",
    "os_error": "本地文件或系统操作失败",
    "runtime_error": "程序运行步骤执行失败",
}

# 高优先级精确故障规则（优先于外部命令退出码和 HTTP 状态码，例如「超时并伴随退出码 128」仍先说超时）。
_FAULT_RULES_PRE = (
    ("dns", re.compile(
        r"getaddrinfo failed|Name or service not known|Temporary failure in name resolution"
        r"|nodename nor servname|SuspectDnsProbeFailed|gaierror|NameResolutionError",
        re.I,
    )),
    ("timeout", re.compile(
        r"timed out|TimeoutError|TimeoutExpired|ReadTimeout|ConnectTimeout|WinError 10060\b",
        re.I,
    )),
    ("conn_reset", re.compile(
        r"Connection ?Refused|Connection ?Reset|Connection ?Aborted|RemoteDisconnected|IncompleteRead"
        r"|EOF occurred|BrokenPipe|WinError 1005[34]\b|WinError 10061\b",
        re.I,
    )),
    ("file_in_use", re.compile(r"WinError 32\b|being used by another process", re.I)),
    ("permission", re.compile(
        r"PermissionError|WinError 5\b|Access is denied|Permission denied",
        re.I,
    )),
)

# 常规异常分类规则（排在外部命令退出码与 HTTP 错误码 >= 400 之后，避免 URLError/RuntimeError 盖过具体状态码）。
_FAULT_RULES_POST = (
    ("not_found", re.compile(r"FileNotFoundError|WinError [23]\b|No such file or directory", re.I)),
    ("json_bad", re.compile(
        r"JSONDecodeError|Expecting value|Expecting property name|Unterminated string|Extra data",
        re.I,
    )),
    ("encoding", re.compile(r"UnicodeDecodeError|UnicodeEncodeError", re.I)),
    ("ssl", re.compile(r"SSLError|CERTIFICATE_VERIFY_FAILED|\bSSL:", re.I)),
    ("url_error", re.compile(
        r"URLError|urlopen error|ConnectionError|WinError 1006[45]\b|Network is unreachable",
        re.I,
    )),
    ("import_error", re.compile(r"ModuleNotFoundError|ImportError", re.I)),
    ("db_error", re.compile(r"database is locked|OperationalError|DatabaseError", re.I)),
    ("key_error", re.compile(r"\bKeyError\b")),
    ("attr_error", re.compile(r"\bAttributeError\b")),
    ("type_error", re.compile(r"\bTypeError\b")),
    ("index_error", re.compile(r"\bIndexError\b")),
    ("value_error", re.compile(r"\bValueError\b")),
    ("zero_div", re.compile(r"\bZeroDivisionError\b")),
)

# 宽泛基类异常规则（排在 WinError 之后，避免 OSError/RuntimeError 盖过具体的 [WinError N]）。
_FAULT_RULES_FALLBACK = (
    ("com_error", re.compile(r"com_error|pywintypes\.error|WMI", re.I)),
    ("os_error", re.compile(r"\b(?:OSError|IOError)\b")),
    ("runtime_error", re.compile(r"\bRuntimeError\b")),
)

# 整行开头即为纯技术异常头时，说明前面没有中文业务主干，避免把本地化报错尾误当主干。
_LEADING_EXC_RE = re.compile(
    r"^(?:Traceback\b|File\s+['\"][^'\"\n]+['\"]\s*,\s*line\s+\d+"
    r"|[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Failure)\b\s*[:(]"
    r"|HTTP(?:/\d|\s+Error)\b|\[?(?:WinError|Errno)\b|<urlopen\b)",
    re.I,
)

# Python 堆栈帧边界（无论有没有 Traceback 头，行首或换行后的 File "...", line N 都属于技术诊断区）。
_STACK_FRAME_CUT_RE = re.compile(
    r"(?:^|\r?\n)\s*(?:Traceback\b|File\s+['\"][^'\"\n]+['\"]\s*,\s*line\s+\d+)",
    re.I,
)

# 中文业务主干之后出现的首个技术诊断边界：从该处直接切开，绝不对英文技术尾做零碎挖词。
_TECH_BOUNDARY_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:Traceback\b"
    r"|File\s+['\"][^'\"\n]+['\"]\s*,\s*line\s+\d+"
    r"|[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Failure)\b"
    r"|HTTP(?:/\d+(?:\.\d+)?|\s*Error|\s+[1-5]\d{2})(?![0-9A-Za-z_])"
    r"|(?:http[\s_-]+)?status(?:[\s_-]*code)?(?![A-Za-z0-9_])[\s=:：]+-?\d+"
    r"|(?:httpStatus|statusCode)(?![A-Za-z0-9_])[\s=:：]+-?\d+"
    r"|(?:returned\s+non-zero\s+exit|exit(?:[\s_-]+status|[\s_-]+code)|return[\s_-]?code)(?![A-Za-z0-9_])"
    r"|exited(?:\s+with(?:\s+(?:non-zero\s+)?(?:exit\s+)?(?:status|code))?)?(?:\s*[:=：]\s*|\s+)(?:0x[0-9a-fA-F]+|-?\d+)(?![0-9A-Za-z_.:-])"
    r"|(?:waitpid|process\s+(?:ended|exited|terminated|failed)"
    r"|child\s+(?:process\s+)?(?:ended|exited|terminated|failed))(?![A-Za-z0-9_])"
    r"|Command\s+\["
    r"|subprocess(?:\.[A-Za-z_]+|\s+)"
    r"|(?:taskkill|tasklist|pwsh|powershell|schtasks|wevtutil|shutdown|adb|git|ssh|curl)(?:\.exe)?\s+[/-])"
    r"|(?<![A-Za-z0-9_-])rc(?:\s*[:=：]\s*|\s+)(?:0x[0-9a-fA-F]+|-?\d+)(?![0-9A-Za-z_.:-])"
    r"|(?:退出码|返回码)\s*[:=：]?\s*(?:0x[0-9a-fA-F]+|-?\d+)(?![0-9A-Za-z_.:-])"
    r"|\[?\s*(?:WinError|Errno)\s+\d+"
    r"|<urlopen\b"
    r"|\{\s*['\"][A-Za-z_]"
    r"|[:：]\s*(?:taskkill|tasklist|pwsh|powershell|schtasks|wevtutil|shutdown|adb|git|ssh|curl)\b"
    r"|[:：]\s*[A-Za-z_][A-Za-z0-9_.-]*\s+[A-Za-z]",
    re.I,
)

# 清洗中文主干内部残留的英文键值与成对括号块（全半角圆括号、中文方括号【】、英文方括号[]）。
_KV_ASCII_RE = re.compile(r"(?<![A-Za-z0-9_\x00])[A-Za-z_][A-Za-z0-9_.-]*\s*=\s*[^\s\x00，。；！？（）()【】\[\]]+")
_PAREN_BLOCK_RE = re.compile(r"（[^（）]*）|\([^()]*\)|【[^【】]*】|\[[^\[\]]*\]")

# 日志原话里的常见工程词转白话对照表（覆盖 JARGON 全部词条，按长词优先排列）。
_JARGON_PLAIN_MAP = (
    ("调度器", "调度程序"),
    ("标记文件", "状态记录"),
    ("时间窗", "时段"),
    ("任务链", "整套任务"),
    ("判定点", "核对项"),
    ("结构化", "按格式"),
    ("白名单", "允许清单"),
    ("凭空造", "自行编造"),
    ("落盘", "保存"),
    ("回读", "重读"),
    ("兜底", "备用方式"),
    ("字段", "内容项"),
    ("判据", "依据"),
    ("监听", "监测"),
    ("句柄", "连接号"),
    ("进程", "程序"),
    ("线程", "后台任务"),
    ("缓存", "本地记录"),
    ("重放", "重跑"),
    ("拉起", "启动"),
    ("收窄", "缩小范围"),
    ("节点", "步骤"),
    ("实例", "运行项"),
    ("退避", "延后重试"),
    ("死键", "无效项"),
    ("冲掉", "盖掉"),
    ("原子", "完整"),
    ("幂等", "防重复"),
    ("接口", "数据入口"),
)

# 术语替换为白话后可能产生的相邻叠词收口（如「接口数据」替换后出现的「数据入口数据」→「返回数据」）。
_PLAIN_DEDUP_MAP = (
    ("数据入口数据", "返回数据"),
    ("数据数据入口", "数据入口"),
    ("保存保存", "保存"),
    ("程序程序", "程序"),
)

# 日志原话里的模糊词规整对照表（覆盖 VAGUE 全部词条；保留否定含义，确保输出通过 plain()）。
_VAGUE_PLAIN_MAP = (
    ("未知错误", "未识别的错误"),
    ("这一步", "该环节"),
    ("有问题", "存在异常"),
    ("出错", "发生运行异常"),
    ("不确定", "未能确认"),
    ("不一定", "未必"),
    ("应该是", ""),
    ("差不多", ""),
    ("多半", ""),
    ("可能", ""),
    ("大概", ""),
    ("大约", ""),
    ("似乎", ""),
    ("疑似", ""),
    ("也许", ""),
    ("或许", ""),
    ("估计", ""),
    ("左右", ""),
    ("好像", ""),
    ("貌似", ""),
    ("大致", ""),
    ("约 ", ""),
    ("约一", "一"),
)

# 中文业务主干里表示“本身已经说出失败/异常结果”的常见谓词，用于判断未知故障是否需补「发生运行异常」。
_HEAD_FAIL_VERBS = (
    "失败", "没", "无法", "不能", "不到", "不对", "超时", "断开", "拒绝",
    "异常", "崩", "错", "停", "卡", "缺", "坏", "丢", "拒", "满", "冲突", "无效", "受限",
)


def _display_path(path: str) -> str:
    """将路径整理为干净展示形式：完整保留 UNC 前导 \\\\，仅折叠正文内部连续反斜杠。"""
    s = path.strip()
    if s.startswith("\\\\"):
        return "\\\\" + re.sub(r"\\{2,}", r"\\", s.lstrip("\\"))
    return re.sub(r"\\{2,}", r"\\", s)


def _path_norm_key(path: str) -> str:
    """生成路径去重与比对用的统一归一化键：保留 UNC 前导语义，统一斜杠并转小写。"""
    s = path.strip()
    if s.startswith("\\\\"):
        return "\\\\" + re.sub(r"[\\/]+", r"\\", s.lstrip("\\")).lower()
    return re.sub(r"[\\/]+", r"\\", s).lower()


def _parse_code_val(code_s: str) -> int | str:
    """将提取出的退出码字符串转为十进制整数或规范小写十六进制错误码字符串。"""
    return code_s.lower() if code_s.lower().startswith("0x") else int(code_s)


def _is_bare_cmd_token(tok: str) -> bool:
    """判断单个词元是不是不含目录的常见外部命令名（如 pwsh.exe），避免过早遮蔽导致命令边界失效。"""
    return "\\" not in tok and "/" not in tok and any(pat.fullmatch(tok) for pat, _ in _LexSpec.CMD_SPECS)


def _has_disallowed_english(text: str) -> bool:
    """判断文本中是否含有未放行的英文词（直接复用单遍词法分析器门禁）。"""
    return any(p.startswith("英文") for p in plain(text))


def _balance_brackets(text: str) -> str:
    """显式栈式括号配平（覆盖 () / （） / 【】 / []）。

    规则：
    1. 遇无对应开括号的多余闭括号（如「读取（旧配置）数据）」）直接丢弃；
    2. 遇外层匹配闭括号时，先对夹在中间的未闭内层括号收口，再闭合外层；
    3. 扫描结束对栈中剩余未闭开括号按 LIFO 顺序处理：内部无实质可读内容（汉字/字母/数字/占位符）
       则连同开括号一起剥离（如「下载失败（」「写入失败【」），有实质内容则清理尾标点后补齐对应闭括号；
    4. 清除只剩空白与标点的空括号。
    """
    pairs = {"(": ")", "（": "）", "【": "】", "[": "]"}
    closers = set(pairs.values())
    has_substance = re.compile(r"[\u4e00-\u9fffA-Za-z0-9\x00]")
    out: list[str] = []
    stack: list[tuple[str, int]] = []

    for ch in text:
        if ch in pairs:
            stack.append((ch, len(out)))
            out.append(ch)
        elif ch in closers:
            if stack and pairs[stack[-1][0]] == ch:
                stack.pop()
                out.append(ch)
            elif any(pairs[op] == ch for op, _ in stack):
                while stack and pairs[stack[-1][0]] != ch:
                    inner_op, inner_pos = stack.pop()
                    if has_substance.search("".join(out[inner_pos + 1:])):
                        out.append(pairs[inner_op])
                    else:
                        del out[inner_pos:]
                if stack and pairs[stack[-1][0]] == ch:
                    stack.pop()
                    out.append(ch)
            # 无对应开括号的多余闭括号：直接丢弃。
        else:
            out.append(ch)

    while stack:
        op, pos = stack.pop()
        if has_substance.search("".join(out[pos + 1:])):
            while len(out) > pos + 1 and out[-1] in "：:,，；;、｜|-—_ \t":
                out.pop()
            if len(out) > pos + 1 and has_substance.search("".join(out[pos + 1:])):
                out.append(pairs[op])
            else:
                del out[pos:]
        else:
            del out[pos:]

    s = "".join(out)
    for _ in range(3):
        nxt = re.sub(
            r"（\s*[，,、；;：:\-—]*\s*）|\(\s*[，,、；;：:\-—]*\s*\)"
            r"|【\s*[，,、；;：:\-—]*\s*】|\[\s*[，,、；;：:\-—]*\s*\]",
            "",
            s,
        )
        if nxt == s:
            break
        s = nxt
    return s


def _normalize_plain_zh(text: str, strip_vague: bool = False) -> str:
    """将中文文本里的工程术语与模糊词统一替换为直白人话，并清理删词后残留的孤立/重复标点与空括号。

    - 保护 _THEIR_TERMS（如上游原话「结束进程」「MaaEnd 进程超时」），避免改坏官方任务名；
    - strip_vague=False 用于纯中文日志（如「中继更新出错」→「中继更新发生运行异常」）；
    - strip_vague=True 用于含英文故障的中文主干（剥离「出错」等泛词，由右侧主因模板给出准确说法）。
    """
    s = str(text or "").strip()
    if not s:
        return ""
    held: list[str] = []
    for term in _THEIR_TERMS:
        if term in s:
            token = f"\x01{len(held)}\x01"
            held.append(term)
            s = s.replace(term, token)
    for _ in range(3):
        before = s
        for old, new in _JARGON_PLAIN_MAP:
            if old in s:
                s = s.replace(old, new)
        for old, new in _PLAIN_DEDUP_MAP:
            if old in s:
                s = s.replace(old, new)
        for old, new in _VAGUE_PLAIN_MAP:
            if old in s:
                s = s.replace(old, "" if strip_vague else new)
        if s == before:
            break
    for i, term in enumerate(held):
        s = s.replace(f"\x01{i}\x01", term)

    # 清理删除模糊词后留下的空括号、孤立前导/尾随逗号顿号及连续重复逗号（如「，，保存失败」→「保存失败」）。
    for _ in range(3):
        before = s
        s = re.sub(r"\s+([，,、；;：:。！？）)】\]])", r"\1", s)
        s = re.sub(r"([（(【\[])\s+", r"\1", s)
        s = re.sub(
            r"（\s*[，,、；;：:\-—]*\s*）|\(\s*[，,、；;：:\-—]*\s*\)"
            r"|【\s*[，,、；;：:\-—]*\s*】|\[\s*[，,、；;：:\-—]*\s*\]",
            "",
            s,
        )
        s = re.sub(r"([（(【\[])[，,、；;]+", r"\1", s)
        s = re.sub(r"[，,、；;]+([）)】\]])", r"\1", s)
        s = re.sub(r"([：:])[，,、；;]+", r"\1", s)
        s = re.sub(r"([，,、；;])[，,、；;]+", r"\1", s)
        s = re.sub(r"^[，,、；;\s]+", "", s)
        s = re.sub(r"[，,、\s]+$", "", s)
        if s == before:
            break
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _norm_key(raw: str) -> str:
    """将标识符统一小写并去除下划线与连字符，便于等价匹配 exit_status / exit-status / httpStatus。"""
    return raw.lower().replace("_", "").replace("-", "")


def _is_standalone_code(sig: list[Token], idx: int) -> bool:
    """判断非空白词元序列 sig[idx] 是否为独立整数或十六进制错误码（排除 11-28 / 9:30 等复合数字）。"""
    tok = sig[idx]
    if tok.kind not in ("INT", "HEX"):
        return False
    if tok.kind == "INT" and idx + 2 < len(sig):
        nxt, nxt2 = sig[idx + 1], sig[idx + 2]
        if (
            nxt.kind == "PUNCT"
            and nxt.raw in ("-", ":", ".")
            and nxt.start == tok.end
            and nxt2.kind == "INT"
            and nxt2.start == nxt.end
        ):
            return False
    return True


def _has_process_exit_ctx(sig: list[Token]) -> bool:
    """基于词元流判断本句是否处于外部命令/子程序退出语境，避免把裸 status=128/500 错判成 HTTP。"""
    m = len(sig)
    for i, tok in enumerate(sig):
        if tok.kind == "REL_PATH":
            base = tok.raw.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if base.endswith(".exe") and base[:-4] in _LexSpec.PROC_CTX_WORDS:
                return True
            continue
        if tok.kind != "IDENT":
            continue
        low = tok.raw.lower()
        if low in _LexSpec.PROC_CTX_WORDS or any(pat.fullmatch(low) for pat, _ in _LexSpec.CMD_SPECS[:1]):
            return True
        if low in _LexSpec.PROC_CTX_SUBJECTS:
            k = i + 1
            if k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == "process":
                k += 1
            if k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() in _LexSpec.PROC_CTX_VERBS:
                return True
        if low in ("exited", "ended", "terminated"):
            k = i + 1
            if k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == "with":
                k += 1
            if k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == "non-zero":
                k += 1
            if k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == "status":
                return True
        if low == "non-zero":
            k = i + 1
            if k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == "exit":
                k += 1
            if k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == "status":
                return True
    return False


def _match_exit_phrase(sig: list[Token], idx: int) -> tuple[Token, int] | None:
    """匹配中文「退出码/返回码」、CalledProcessError(N) 与 exited [with ...] <code> 短语。"""
    m = len(sig)
    tok = sig[idx]
    if tok.kind == "ZH" and tok.raw.endswith(("退出码", "返回码")):
        k = idx + 1
        if k < m and sig[k].kind == "PUNCT" and sig[k].raw in (":", "=", "："):
            k += 1
        return (sig[k], k) if k < m and _is_standalone_code(sig, k) else None
    if tok.kind != "IDENT":
        return None

    low = tok.raw.lower()
    if low == "calledprocesserror":
        k = idx + 1
        while k < m and sig[k].kind == "PUNCT" and sig[k].raw in ("(", "=", ":", "："):
            k += 1
        return (sig[k], k) if k < m and _is_standalone_code(sig, k) else None

    if low != "exited":
        return None
    if idx > 0 and sig[idx - 1].kind == "PUNCT" and sig[idx - 1].raw == "-" and sig[idx - 1].end == tok.start:
        return None
    k = idx + 1
    if k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == "with":
        k += 1
        for opt in ("non-zero", "exit"):
            if k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == opt:
                k += 1
        if k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() in ("status", "code"):
            k += 1
    if k < m and sig[k].kind == "PUNCT" and sig[k].raw in (":", "=", "："):
        k += 1
    return (sig[k], k) if k < m and _is_standalone_code(sig, k) else None


def _match_exit_kv(sig: list[Token], idx: int) -> tuple[Token, int] | None:
    """匹配退出码键值表达（exit_status / exit-status / exit_code / returncode / rc / exit status / return code）。"""
    m = len(sig)
    tok = sig[idx]
    if tok.kind != "IDENT":
        return None
    # 左侧紧贴连字符的（如 -rc-1、foo-rc=1）不作为独立退出码键。
    if idx > 0 and sig[idx - 1].kind == "PUNCT" and sig[idx - 1].raw == "-" and sig[idx - 1].end == tok.start:
        return None

    low = tok.raw.lower()
    nk = _norm_key(tok.raw)
    key_end = -1
    is_rc = False
    if nk in _LexSpec.EXIT_KEY_SINGLE:
        key_end = idx
        is_rc = (low == "rc")
    elif low == "exit" and idx + 1 < m and sig[idx + 1].kind == "IDENT" and sig[idx + 1].raw.lower() in ("status", "code"):
        key_end = idx + 1
        if sig[key_end].raw.lower() == "status" and key_end + 1 < m and sig[key_end + 1].kind == "IDENT" and sig[key_end + 1].raw.lower() == "code":
            key_end += 1
    elif low == "return" and idx + 1 < m and sig[idx + 1].kind == "IDENT" and sig[idx + 1].raw.lower() == "code":
        key_end = idx + 1
    if key_end < 0:
        return None

    k = key_end + 1
    if k < m and sig[k].kind == "PUNCT" and sig[k].raw in (":", "=", "："):
        k += 1
        return (sig[k], k) if k < m and _is_standalone_code(sig, k) else None
    if not is_rc and k < m and sig[k].kind == "PUNCT" and sig[k].raw == "-":
        k += 1
        if k < m and sig[k].kind == "INT" and not sig[k].raw.startswith("-") and _is_standalone_code(sig, k):
            return sig[k], k
        return None
    if k < m and sig[k].start > sig[key_end].end and _is_standalone_code(sig, k):
        return sig[k], k
    return None


def _match_explicit_exit(sig: list[Token], idx: int) -> tuple[Token, int] | None:
    """在词元位置 idx 尝试匹配显式退出码表达，命中返回 (码词元, 结束下标)。

    DATE / TIME / FLOAT / SEMVER 天然不是 INT/HEX，数学上绝不会误吃日期、时刻、小数或 -rc-1 版本号。
    """
    return _match_exit_phrase(sig, idx) or _match_exit_kv(sig, idx)


def _read_http_code_at(sig: list[Token], idx: int, used_exit_idx: set[int]) -> int | None:
    """在词元位置 idx 读取合法 3 位 HTTP 状态码（兼容可选引号包裹，如 JSON 值）。"""
    m = len(sig)
    k = idx
    if k < m and sig[k].kind == "PUNCT" and sig[k].raw in ("'", '"'):
        k += 1
    if k >= m or k in used_exit_idx:
        return None
    tok = sig[k]
    if tok.kind != "INT" or len(tok.raw) != 3 or not tok.raw.isdigit() or not _is_standalone_code(sig, k):
        return None
    val = int(tok.raw)
    return val if val in _VALID_HTTP_CODES else None


def _extract_http_candidates(sig: list[Token], used_exit_idx: set[int], in_process_ctx: bool) -> list[int]:
    """从词元流收集所有合法 HTTP 状态码（避开已归属退出码的词元，兼容 HTTP/1.1、JSON 蛇形与驼峰键）。"""
    m = len(sig)
    out: list[int] = []
    for i, tok in enumerate(sig):
        if i in used_exit_idx:
            continue
        if tok.kind == "ZH" and tok.raw.endswith("状态码"):
            k = i + 1
            if k < m and sig[k].kind == "PUNCT" and sig[k].raw in (":", "=", "："):
                k += 1
            if (val := _read_http_code_at(sig, k, used_exit_idx)) is not None:
                out.append(val)
            continue
        if tok.kind != "IDENT":
            continue
        low = tok.raw.lower()
        nk = _norm_key(tok.raw)
        # 1. HTTP/1.1 502、HTTP/2 429、HTTP Error 503、HTTP 429
        if low == "http":
            k = i + 1
            if k + 1 < m and sig[k].kind == "PUNCT" and sig[k].raw == "/" and sig[k + 1].kind in ("FLOAT", "INT"):
                k += 2
            elif k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == "error":
                k += 1
            elif k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() in ("status", "status_code", "status-code"):
                k += 1
                if k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == "code":
                    k += 1
            if k < m and sig[k].kind == "PUNCT" and sig[k].raw in (":", "=", "："):
                k += 1
            if (val := _read_http_code_at(sig, k, used_exit_idx)) is not None:
                out.append(val)
            continue
        # 2. 显式 HTTP 键（http_status / httpStatus / JSON "status_code" / "statusCode"）
        #    以及非进程退出语境下的通用 status / status_code / status code
        is_quoted = (
            i > 0 and sig[i - 1].kind == "PUNCT" and sig[i - 1].raw in ("'", '"')
            and i + 1 < m and sig[i + 1].kind == "PUNCT" and sig[i + 1].raw == sig[i - 1].raw
        )
        is_explicit_kv = nk in _LexSpec.HTTP_EXPLICIT_KEYS or (is_quoted and nk in _LexSpec.STATUS_CODE_KEYS)
        is_generic_kv = (not in_process_ctx) and nk in _LexSpec.GENERIC_STATUS_KEYS
        if not (is_explicit_kv or is_generic_kv):
            continue
        k = i + (2 if is_quoted else 1)
        if not is_quoted and low == "status" and k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == "code":
            k += 1
        has_sep = False
        if k < m and sig[k].kind == "PUNCT" and sig[k].raw in (":", "=", "："):
            k += 1
            has_sep = True
        if is_quoted and not has_sep:
            continue
        if (val := _read_http_code_at(sig, k, used_exit_idx)) is not None:
            out.append(val)
    return out


def _extract_codes(tokens: list[Token]) -> tuple[int | str | None, int | None, int | None, str]:
    """直接基于单遍词法分析器 Token 流提取退出码、HTTP 状态码、WinError 与十六进制错误码。"""
    # 用 URL_BARRIER 替代 URL 词元，防止 URL 前后原本隔开的词元被误拼相邻；空白词元跳过。
    sig = [
        Token("URL_BARRIER", "", t.start, t.end) if t.kind == "URL" else t
        for t in tokens
        if t.kind != "WS"
    ]
    m = len(sig)
    in_process_ctx = _has_process_exit_ctx(sig)

    # 1. 显式退出码（记录已占用词元下标，杜绝 exit status 500 被 HTTP 二次拾取）。
    exit_code: int | str | None = None
    used_exit_idx: set[int] = set()
    i = 0
    while i < m:
        hit = _match_explicit_exit(sig, i)
        if hit is not None:
            code_tok, end_idx = hit
            if exit_code is None:
                exit_code = _parse_code_val(code_tok.raw)
            used_exit_idx.update(range(i, end_idx + 1))
            i = end_idx + 1
        else:
            i += 1

    # 2. 外部命令退出语境下的裸 status=128 / status: 255 / status code 500。
    if exit_code is None and in_process_ctx:
        for i, tok in enumerate(sig):
            if i in used_exit_idx or tok.kind != "IDENT":
                continue
            if _norm_key(tok.raw) not in ("status", "statuscode"):
                continue
            k = i + 1
            if tok.raw.lower() == "status" and k < m and sig[k].kind == "IDENT" and sig[k].raw.lower() == "code":
                k += 1
            if k < m and sig[k].kind == "PUNCT" and sig[k].raw in (":", "=", "："):
                k += 1
            if k < m and k not in used_exit_idx and _is_standalone_code(sig, k):
                exit_code = _parse_code_val(sig[k].raw)
                used_exit_idx.update(range(i, k + 1))
                break

    # 3. 合法 HTTP 状态码（同时存在 200/302 与 >=400 错误码时优先保留 >=400）。
    http_candidates = _extract_http_candidates(sig, used_exit_idx, in_process_ctx)
    http_code: int | None = next((c for c in http_candidates if c >= 400), None)
    if http_code is None and http_candidates:
        http_code = http_candidates[0]

    # 4. Windows 系统错误码（WinError N）与十六进制错误码（排除 UnicodeDecodeError 里的 byte 0xff）。
    win_error: int | None = None
    hex_code = ""
    for i, tok in enumerate(sig):
        if win_error is None and tok.kind == "IDENT" and tok.raw.lower() == "winerror":
            k = i + 1
            if k < m and sig[k].kind == "PUNCT" and sig[k].raw in (":", "=", "："):
                k += 1
            if k < m and sig[k].kind == "INT" and sig[k].raw.isdigit() and _is_standalone_code(sig, k):
                win_error = int(sig[k].raw)
        if not hex_code and tok.kind == "HEX":
            prev_word = sig[i - 1].raw.lower() if i > 0 and sig[i - 1].kind == "IDENT" else ""
            if prev_word not in _LexSpec.BYTE_HEX_PREFIXES:
                hex_code = tok.raw
    return exit_code, http_code, win_error, hex_code


def _classify_fault_kind(
    tokens: list[Token], exit_code: int | str | None, http_code: int | None, win_error: int | None
) -> str:
    """按精确优先级归类故障类别：DNS/超时/占用 > 退出码 > HTTP 错误码(>=400) > 常规异常 > WinError。

    先用词法分析器遮蔽 URL 与文件路径（避免文件名里的 timeout/ssl 造成误判，也绝不丢失紧贴 URL 的异常名）；
    1xx/2xx/3xx（如 HTTP/1.1 200 OK）本身不是 HTTP 错误，绝不抢占 JSONDecodeError/KeyError 等真实故障类别。
    """
    diag = "".join(" " if t.kind in ("URL", "UNC_PATH", "WIN_PATH", "REL_PATH") else t.raw for t in tokens)
    for kind, pat in _FAULT_RULES_PRE:
        if pat.search(diag):
            return kind
    if exit_code is not None or re.search(r"\bCalledProcessError\b", diag):
        return "process_exit"
    if http_code is not None and http_code >= 400:
        return "http_error"
    for kind, pat in _FAULT_RULES_POST:
        if pat.search(diag):
            return kind
    if win_error is not None:
        return "win_error"
    for kind, pat in _FAULT_RULES_FALLBACK:
        if pat.search(diag):
            return kind
    return ""


def _extract_files_and_cmds(tokens: list[Token]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """直接基于词法分析器 Token 流提取命令名与真实文件路径，保留 UNC 前导 \\\\ 并严格去重。"""
    seen: set[tuple[str, str]] = set()
    cmds: list[str] = []
    files: list[str] = []

    # 收集词元流里的非路径命令候选（IDENT 与不含斜杠的裸文件名 REL_PATH），按既有优先级取首项。
    cand_words = [
        t.raw for t in tokens
        if t.kind == "IDENT" or (t.kind == "REL_PATH" and "\\" not in t.raw and "/" not in t.raw)
    ]
    for pat, label in _LexSpec.CMD_SPECS:
        if any(pat.fullmatch(w) for w in cand_words):
            key = ("cmd", label.lower())
            if key not in seen:
                seen.add(key)
                cmds.append(label)
                break

    cmd_norms = {c.lower() for c in cmds}
    for tok in tokens:
        if tok.kind not in ("UNC_PATH", "WIN_PATH", "REL_PATH"):
            continue
        raw_p = _display_path(tok.raw.rstrip(".,;:)'\"」）]"))
        if not raw_p:
            continue
        norm = _path_norm_key(raw_p)
        # 若裸文件名与已提取命令同名（如 pwsh.exe），只保留「命令 pwsh.exe」，避免重复输出。
        if "\\" not in norm and norm in cmd_norms:
            continue
        key = ("file", norm)
        if key not in seen:
            seen.add(key)
            files.append(raw_p)
        if len(files) >= 2:
            break
    return tuple(files), tuple(cmds)


def _strip_disallowed_tokens_segment(segment: str) -> str:
    """用单遍词法分析器清洗单个不含占位符的片段：去除未放行英文词、协议斜杠簇（QUIC/v1、TLS/SSL）与原子 HEX。"""
    toks = _lex_text(segment)
    n = len(toks)
    out: list[str] = []
    i = 0
    while i < n:
        tok = toks[i]
        if tok.kind == "HEX":
            # 原子十六进制错误码整块剥离，绝不切出孤立残渣 0（原值由 info.hex_code 统一渲染）。
            out.append(" ")
            i += 1
            continue
        if tok.kind == "IDENT" and tok.raw not in ALLOWED_WORDS:
            # 整簇清除紧跟在未放行英文后的协议/编码/斜杠残片（如 QUIC/v1、HTTP/2.0-draft、TLS/SSL、UTF-8/GBK、foo/bar、foo\bar）。
            i += 1
            while i < n:
                if (
                    toks[i].kind == "PUNCT"
                    and toks[i].raw in ("/", "\\", ".")
                    and toks[i].start == toks[i - 1].end
                    and i + 1 < n
                    and toks[i + 1].start == toks[i].end
                    and toks[i + 1].kind in ("IDENT", "FLOAT", "INT", "SEMVER", "OTHER")
                ):
                    i += 2
                    continue
                if (
                    toks[i].kind == "PUNCT"
                    and toks[i].raw == "-"
                    and toks[i].start == toks[i - 1].end
                    and i + 1 < n
                    and toks[i + 1].start == toks[i].end
                    and (
                        toks[i + 1].kind in ("FLOAT", "INT", "SEMVER", "OTHER")
                        or (toks[i + 1].kind == "IDENT" and toks[i + 1].raw not in ALLOWED_WORDS)
                    )
                ):
                    i += 2
                    continue
                break
            out.append(" ")
            continue
        out.append(tok.raw)
        i += 1
    return "".join(out)


def _hold_protected_tokens(text: str, kept: list[str], skip_bare_cmd: bool) -> str:
    """按单遍词法分析器结果保护合法 URL / 路径 / 版本号并整块剥离原子 HEX，防止后续切分误伤。"""
    out: list[str] = []
    for part in re.split(r"(\x00\d+\x00)", text):
        if part.startswith("\x00") and part.endswith("\x00"):
            out.append(part)
            continue
        for tok in _lex_text(part):
            if tok.kind == "URL":
                kept.append(tok.raw)
                out.append(f"\x00{len(kept) - 1}\x00")
            elif tok.kind in ("UNC_PATH", "WIN_PATH", "REL_PATH"):
                if skip_bare_cmd and tok.kind == "REL_PATH" and _is_bare_cmd_token(tok.raw):
                    out.append(tok.raw)
                else:
                    kept.append(_display_path(tok.raw))
                    out.append(f"\x00{len(kept) - 1}\x00")
            elif tok.kind in ("SEMVER", "DATE", "TIME"):
                kept.append(tok.raw)
                out.append(f"\x00{len(kept) - 1}\x00")
            elif tok.kind == "HEX":
                out.append(" ")
            else:
                out.append(tok.raw)
    return "".join(out)


def _extract_head_zh(raw: str, extracted_codes: set[int | str]) -> str:
    """从原始日志中切出干净的中文业务主干：堆栈帧切分 + 词法占位 + 括号配平 + 零残渣清理。"""
    # 1. 有显式分隔符「｜」或「|」时取其前段；同时在无 Traceback 头的 Python 堆栈帧（File "...", line N）前截断。
    cand = re.split(r"\s*[｜|]\s*", raw, maxsplit=1)[0]
    if m_sf := _STACK_FRAME_CUT_RE.search(cand):
        cand = cand[:m_sf.start()]
    cand = cand.strip()
    if not re.search(r"[\u4e00-\u9fff]", cand) or _LEADING_EXC_RE.search(cand):
        return ""

    # 2. 用单遍词法分析器先保护合法 URL / UNC / Windows / 相对路径 / 预发布版本号，并原子剥离 HEX（零残渣 0）。
    kept: list[str] = []
    cand = _hold_protected_tokens(cand, kept, skip_bare_cmd=True)

    # 3. 去掉成对括号块（含（）、()、【】、[]）内含未放行英文/协议/报错的补充说明。
    def _drop_tech_paren(m: re.Match) -> str:
        inner = re.sub(r"\x00\d+\x00", " ", m.group(0)[1:-1])
        return " " if _has_disallowed_english(inner) else m.group(0)

    for _ in range(3):
        nxt = _PAREN_BLOCK_RE.sub(_drop_tech_paren, cand)
        if nxt == cand:
            break
        cand = nxt

    # 4. 按中文之后出现的首个技术诊断边界截断（不把前导词如「subprocess调用失败」误切空）。
    for m in _TECH_BOUNDARY_RE.finditer(cand):
        if re.search(r"[\u4e00-\u9fff]", cand[:m.start()]):
            cand = cand[:m.start()]
            break

    # 5. 补保护剩余合法文件名（如主干中单独提到的 pwsh.exe），再按词法器整块清除残留英文键值与未允许标识符。
    s = _hold_protected_tokens(cand, kept, skip_bare_cmd=False)
    s = _KV_ASCII_RE.sub(" ", s)
    s = re.sub(r"<[^>]*>", " ", s)
    s = "".join(
        part if (part.startswith("\x00") and part.endswith("\x00")) else _strip_disallowed_tokens_segment(part)
        for part in re.split(r"(\x00\d+\x00)", s)
    )

    # 6. 术语与模糊词规范化，清理孤立符号、尾随错误码，再走显式栈括号配平，最后还原 URL/路径占位符。
    s = _normalize_plain_zh(s, strip_vague=True)
    s = re.sub(r"['\"`]", "", s)
    s = re.sub(r"[:：]\s*[:：]+", "：", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(?<!\d)[:：=_\-]+\s*-?\d+\.?\s*$", "", s)
    for code in extracted_codes:
        s = re.sub(rf"\s+{re.escape(str(code))}\.?\s*$", "", s)
    s = re.sub(r"[：:,，；;、.!！？?｜|\-—_\s]+$", "", s)
    s = re.sub(r"^[：:,，；;、.!！？?｜|\-—_）)】\]\s]+", "", s)
    s = _balance_brackets(s)
    s = re.sub(r"[：:,，；;、.!！？?｜|\-—_\s]+$", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()

    for i, val in enumerate(kept):
        s = s.replace(f"\x00{i}\x00", val)
    if len(re.findall(r"[\u4e00-\u9fff]", s)) < 2:
        return ""
    # 含完整 URL 或路径的主干绝不按固定字数拦腰切坏路径，仅对纯文本超长主干截断并重新配平括号。
    has_long_entity = any(t.kind in ("URL", "WIN_PATH", "UNC_PATH", "REL_PATH") for t in _lex_text(s))
    if len(s) > 72 and not has_long_entity:
        s = _balance_brackets(s[:72].rstrip("：:,，；;、.!！？?｜|-—_（(【[ "))
    return s


def _parse_fault(raw: str) -> FaultInfo:
    """结构化词法解析器：单遍分词拆解为 FaultInfo（主干、故障类型、退出码、HTTP码、文件、命令、URL）。"""
    text = str(raw or "").strip()
    if not text:
        return FaultInfo()

    tokens = _lex_text(text)
    url = next((t.raw for t in tokens if t.kind == "URL"), "")

    exit_code, http_code, win_error, hex_code = _extract_codes(tokens)
    fault_kind = _classify_fault_kind(tokens, exit_code, http_code, win_error)
    files, cmds = _extract_files_and_cmds(tokens)

    extracted_codes: set[int | str] = {c for c in (exit_code, http_code, win_error) if c is not None}
    head_zh = _extract_head_zh(text, extracted_codes)
    return FaultInfo(
        head_zh=head_zh,
        fault_kind=fault_kind,
        exit_code=exit_code,
        http_code=http_code,
        win_error=win_error,
        files=files,
        cmds=cmds,
        url=url,
        hex_code=hex_code,
    )


def _scrub_plain_violations(text: str, strip_vague: bool = True) -> str:
    """输出前 fail-closed 清理器：基于单遍词法分析器剥离任何残留未放行英文并重跑归一化与括号配平。"""
    s = _strip_disallowed_tokens_segment(text)
    s = _normalize_plain_zh(s, strip_vague=strip_vague)
    s = _balance_brackets(s)
    s = re.sub(r"[：:,，；;、.!！？?｜|\-—_\s]+$", "", s)
    s = re.sub(r"^[：:,，；;、.!！？?｜|\-—_\s]+", "", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def _render_fault(info: FaultInfo) -> str:
    """根据 FaultInfo 模板拼装干净白话中文，单层括号展示上下文细节，并执行输出前 fail-closed plain() 守卫。"""
    if info.fault_kind == "http_error" and info.http_code is not None:
        base_cause = f"对方服务器返回了状态码 {info.http_code}"
    else:
        base_cause = _FAULT_TEMPLATES.get(info.fault_kind, "")

    # 守卫 1：先对中文主干执行 plain() 核验，若残留未识别技术词则自动剥离并重跑归一化与括号配平。
    head = info.head_zh
    if head and plain(head):
        head = _scrub_plain_violations(head, strip_vague=True)
        if len(re.findall(r"[\u4e00-\u9fff]", head)) < 2:
            head = ""

    # 按 (类型, 归一化值) 统一去重拼装上下文细节，避免重复文件名（含双反斜杠/UNC/大小写差异）或双层括号。
    details: list[str] = []
    seen: set[tuple[str, str]] = set()

    def _add(kind: str, label: str, norm: str) -> None:
        key = (kind, norm.lower())
        if key not in seen:
            seen.add(key)
            details.append(label)

    head_file_keys = {
        _path_norm_key(_display_path(t.raw))
        for t in _lex_text(head)
        if t.kind in ("UNC_PATH", "WIN_PATH", "REL_PATH")
    }

    for cmd in info.cmds:
        if cmd.lower() not in head.lower():
            _add("cmd", f"命令 {cmd}", cmd)
    for fpath in info.files:
        disp = _display_path(fpath)
        norm = _path_norm_key(disp)
        if any(k == norm or k.endswith("\\" + norm) for k in head_file_keys):
            continue
        _add("file", f"文件 {disp}", norm)
    if info.hex_code and info.hex_code.lower() not in head.lower():
        _add("hex", f"错误码 {info.hex_code}", info.hex_code)
    # 仅 >= 400 的 HTTP 错误码才作为故障细节补充展示，200/302 等正常响应码不当故障渲染。
    if info.http_code is not None and info.http_code >= 400 and info.fault_kind != "http_error":
        _add("http", f"状态码 {info.http_code}", str(info.http_code))
    if info.exit_code is not None:
        if isinstance(info.exit_code, str) and info.exit_code.lower().startswith("0x"):
            if info.exit_code.lower() != info.hex_code.lower():
                _add("hex", f"错误码 {info.exit_code}", info.exit_code)
        else:
            _add("exit", f"退出码 {info.exit_code}", str(info.exit_code))
    if info.win_error is not None and info.fault_kind == "win_error":
        _add("win", f"系统错误码 {info.win_error}", str(info.win_error))

    parts: list[str] = []
    if head:
        parts.append(head)
    if base_cause and base_cause not in head:
        parts.append(base_cause)
    if not parts:
        parts.append("程序发生运行异常")
    elif not base_cause and not any(k in head for k in _HEAD_FAIL_VERBS):
        # 剥离模糊词后若主干仅剩动作短语（如「解析活动数据」），补齐失败谓词以免读起来像正常语句。
        parts.append("发生运行异常")

    msg = "——".join(parts)
    if details:
        msg += f"（{'，'.join(details)}）"
    out = f"{msg}，原文已记日志"

    # 守卫 2：终极 fail-closed plain() 校验，保证无论输入多极端，最终返回 100% 过 plain() 且绝不吞错。
    if plain(out):
        cleaned = _scrub_plain_violations(msg, strip_vague=True)
        out = f"{cleaned}，原文已记日志" if cleaned else "程序发生运行异常，原文已记日志"
        if plain(out):
            out = "程序发生运行异常，原文已记日志"
    return out


def fault_cause(what: str) -> str:
    """将日志原话中的系统/网络/HTTP/Win32/外部命令/Python 异常翻成直白中文原因；未匹配时返回空串。"""
    info = _parse_fault(what)
    if not info.fault_kind:
        return ""
    if info.fault_kind == "http_error" and info.http_code is not None:
        return f"对方服务器返回了状态码 {info.http_code}"
    if info.fault_kind == "process_exit":
        if info.exit_code is not None:
            if isinstance(info.exit_code, str) and info.exit_code.lower().startswith("0x"):
                return f"外部命令执行失败（错误码 {info.exit_code}）"
            return f"外部命令执行失败（退出码 {info.exit_code}）"
        return "外部命令执行失败"
    if info.fault_kind == "win_error" and info.win_error is not None:
        return f"系统调用失败（系统错误码 {info.win_error}）"
    return _FAULT_TEMPLATES.get(info.fault_kind, "")


def format_fault_reason(what: str) -> str:
    """统一的白话故障原因格式化入口：纯中文走规范化+括号配平，含英文走单遍词法解析+fail-closed 守卫。"""
    raw = str(what or "").strip()
    if not raw:
        return "记录里没有写具体原因，详见中继日志"
    if not _has_disallowed_english(raw):
        clean = _balance_brackets(_normalize_plain_zh(raw, strip_vague=False))
        if clean and not plain(clean):
            return clean
    return _render_fault(_parse_fault(raw))


def _said(what: str) -> str:
    """将一条报错日志转成推群可读的直白人话：纯中文也经统一白话规范化与 plain() 守卫，绝不漏网。"""
    raw = str(what or "").strip()
    if raw and not _has_disallowed_english(raw):
        clean = _balance_brackets(_normalize_plain_zh(raw, strip_vague=False))
        if clean and not plain(clean):
            return f"它说：{clean}"
    return f"原因：{format_fault_reason(raw)}"


def relay_error_recurred(fixed_in: str) -> str:
    """Title: a fault known_fixed.py records as fixed in `fixed_in` is back (an ERROR)."""
    return f"{RELAY_ERROR}（v{fixed_in} 修过的又出现了）" if fixed_in else f"{RELAY_ERROR}（修过的又出现了）"


def relay_error_recurred_body(where: str, what: str, at: str = "", fixed_what: str = "") -> str:
    when = f"（{at}）" if at else ""
    fixed = f"当时修的是：{fixed_what}。" if fixed_what else ""
    return (f"一种已经修过的错又出现了{when}，出在「{relay_part(where)}」。{fixed}{_said(what)}\n"
            "修过的毛病又犯了，已交给我们这边去查为什么没修住。")


def relay_faults_section(rows: list) -> str:
    """技术日志中的当日中继报错汇总（仅写入技术日志，绝不进入用户日报；一律输出结构化白话错因）。"""
    if not rows:
        return ""
    lines = []
    for r in rows[:10]:
        n = int(r.get("count") or 1)
        tags = []
        if r.get("fixed_in"):
            tags.append(f"复发：v{r['fixed_in']} 修过的又出现了")
        pushed = int(r.get("pushed") or 0)
        if pushed >= n:
            tags.append("已报群")
        elif pushed:
            tags.append(f"已报群 {pushed} 次，还有 {n - pushed} 次在排队等着报")
        else:
            tags.append("还在排队等着报群")
        said = format_fault_reason(str(r.get("line") or ""))
        lines.append(f"· {relay_part(str(r.get('where') or ''))}：{said}"
                     + (f"（{n} 次）" if n > 1 else "") + f"｜{'；'.join(tags)}")
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
