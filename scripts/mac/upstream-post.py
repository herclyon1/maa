#!/usr/bin/env python3
"""往上游仓库发 issue / discussion / PR 之前的闸门：按**人家的模板**逐条核对草稿。

为什么有它（2026-09-06 用户原话「给自己搞工具，严格按他们的要求」）：
* 09-01 MaaEnd 把我的 issue 关了：AI 味 + 没交日志。
* 09-06 AUTO-MAS#574 用命令行提，模板的标签没打上，重提。
* 09-06 发现 OK-WW 的三条建议全提错了地方——它的模板第一行写着「新功能建议请去讨论区」，
  标题要带 [Enhancement]，「验收示例」「需求热度」两栏也没填；四个 PR 全被关，
  是因为 PR 模板要求「新功能或大改先联系作者或在社区讨论」，一次都没做。
文档拦不住这些，工具才拦得住：草稿不过这里的核对，就不许发。

用法：
  upstream-post.py rules <owner/repo>                 拉下模板并打印这个仓库的规矩（缓存到 data/upstream-templates/）
  upstream-post.py lint  <owner/repo> <模板名> <草稿.md>   逐条核对草稿；退出码非 0 = 不许发（仓库没有模板时模板名写 -）
  upstream-post.py dup   <owner/repo> <关键词...>        查重（issue + discussion 的标题）
草稿格式：第一行 `# 标题`，其余按模板的字段名分段：`字段名:` 独占一行，下面写内容。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE = REPO_ROOT / "data" / "upstream-templates"
# 一眼 AI 的写法（docs/UPSTREAM-ISSUE-RULES.md 第三节），任何一条命中都不许发
AI_TONE = [
    (re.compile(r"^\s*#{1,3}\s", re.M), "自造的 # 标题（模板没有的标题不要加）"),
    (re.compile(r"\*\*[^*\n]{2,}\*\*"), "加粗"),
    (re.compile(r"^\s*\|.*\|\s*$", re.M), "表格"),
    (re.compile(r"如需.{0,12}(提供|补充)|另行提供"), "「如需……可另行提供」这类推脱"),
    (re.compile(r"(修复方案|优先级|建议方案)[:：]"), "顺手给修复方案 / 优先级"),
]
MAX_BODY = 2200        # 真人建议类正文一般几百字；证据类（带日志）放宽到这个数
MIN_CAP = 300          # floor for the per-repo cap, so a repo of one-line posts still leaves room for a log line
# 2026-10-06 (MistEO/MXU#371): the checks below were in UPSTREAM-ISSUE-RULES.md section 3
# but nothing enforced them; #371 passed with 867 chars (that repo: median 125, 90% <= 784
# over 68 issues) and a sentence about another issue number.
PARALLEL_LIST = re.compile(r"^\s*(?:\d+[.、)）]|[-*•])\s*\S")
OTHER_ISSUE = re.compile(r"(?<![\w/&])#\d{1,6}\b")


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


class TemplatesUnreadable(Exception):
    """gh failed on a template read for a reason other than 404 (network, auth, rate limit)."""


def _gh_unless_404(*args: str) -> str | None:
    """stdout of `gh args`; None when GitHub answered 404 (the file is not there).

    Any other failure raises TemplatesUnreadable: until 2026-10-10 every gh failure read
    as "the repo has no template", the empty result went into _parsed.json, and `lint - `
    passed a draft against no template at all.
    """
    try:
        return _gh(*args)
    except subprocess.CalledProcessError as e:
        if "(HTTP 404)" in (e.stderr or ""):
            return None
        raise TemplatesUnreadable(f"gh {' '.join(args[:2])} 失败：{(e.stderr or '').strip()[:300]}") from e


def _fetch_templates(repo: str) -> dict:
    """{name: {'kind': 'md'|'yml'|'pr', 'title': 前缀, 'labels': [...], 'fields': [(名, 必填)], 'route': 'issue'|'discussion', 'notes': [...]}}"""
    import os  # noqa: PLC0415
    d = CACHE / repo.replace("/", "__")
    d.mkdir(parents=True, exist_ok=True)
    cached = d / "_parsed.json"
    if os.environ.get("UPSTREAM_POST_OFFLINE") and cached.is_file():   # 闸门自检不联网
        return json.loads(cached.read_text(encoding="utf-8"))
    # Fetch everything first, write afterwards: a gh failure part-way (TemplatesUnreadable)
    # must leave the whole cache as it was, not half of it rewritten.
    fetched: dict[str, str] = {}
    listed = _gh_unless_404("api", f"repos/{repo}/contents/.github/ISSUE_TEMPLATE", "--jq", "[.[].name]")
    names = json.loads(listed) if listed is not None else []
    for name in names:
        raw = _gh_unless_404("api", f"repos/{repo}/contents/.github/ISSUE_TEMPLATE/{name}", "--jq", ".content")
        if raw is not None:
            fetched[name] = subprocess.run(["base64", "-d"], input=raw, capture_output=True, text=True).stdout
    raw = _gh_unless_404("api", f"repos/{repo}/contents/.github/PULL_REQUEST_TEMPLATE.md", "--jq", ".content")
    if raw is not None:
        fetched["PULL_REQUEST_TEMPLATE.md"] = subprocess.run(["base64", "-d"], input=raw,
                                                             capture_output=True, text=True).stdout
    out: dict = {}
    for name, text in fetched.items():
        (d / name).write_text(text, encoding="utf-8")
        if name == "PULL_REQUEST_TEMPLATE.md":
            out[name] = _parse_pr(text)
        elif name.endswith((".md",)):
            out[name] = _parse_md(text)
        elif name.endswith((".yml", ".yaml")) and name != "config.yml":
            out[name] = _parse_yml(text)
    (d / "_parsed.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def _repo_cap(repo: str) -> int | None:
    """90th percentile of the body length of the repo's own issues (up to 200, PRs left out),
    floored at MIN_CAP; cached next to the templates. None when it cannot be read.
    """
    import os  # noqa: PLC0415
    f = CACHE / repo.replace("/", "__") / "_lengths.json"
    if f.is_file() and (os.environ.get("UPSTREAM_POST_OFFLINE") or __import__("time").time() - f.stat().st_mtime < 7 * 86400):
        return json.loads(f.read_text(encoding="utf-8")).get("cap")
    if os.environ.get("UPSTREAM_POST_OFFLINE"):
        return None
    lens: list[int] = []
    for page in (1, 2):
        try:
            out = _gh("api", f"repos/{repo}/issues?state=all&per_page=100&page={page}",
                      "--jq", '.[] | select(.pull_request == null) | ((.body // "") | length)')
        except subprocess.CalledProcessError:
            break
        lens += [int(x) for x in out.split()]
    if len(lens) < 10:
        return None
    lens.sort()
    cap = max(MIN_CAP, lens[int(len(lens) * 0.9) - 1])
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"cap": cap, "n": len(lens), "median": lens[(len(lens) - 1) // 2]}), encoding="utf-8")
    return cap


def style_problems(body: str, repo: str | None = None, pr: bool = False) -> list[str]:
    """The template-free half of the lint: tone, lists, other issue numbers, length, logs.
    Used by cmd_lint and by ~/.claude/hooks/upstream-guard.py for comments. A PR keeps its
    template's checkbox list and must link an issue, so those two checks skip it.
    """
    bad = [f"AI 味：{why}" for rx, why in AI_TONE if "标题" not in why and rx.search(body)]
    prose = re.sub(r"```.*?```", "", body, flags=re.S)
    # Numbered repro steps of uneven length are how people write; the machine tell is a
    # run of items of about the same length (rules section 3), or a long checklist.
    items = [len(ln.strip()) for ln in prose.splitlines() if PARALLEL_LIST.match(ln)]
    if not pr and (len(items) >= 8 or (len(items) >= 3 and max(items) <= 1.5 * min(items))):
        bad.append(f"AI 味：并排列表 {len(items)} 行、长短差不多（有几句写几句，别排成清单）")
    if not pr and (refs := OTHER_ISSUE.findall(re.sub(r"`[^`]*`", "", prose))):
        bad.append(f"正文提了别的 issue 号 {refs[:3]}：只说自己遇到的这一件，相关帖、查重经过不写")
    cap = (_repo_cap(repo) if repo else None) or MAX_BODY
    if len(body) > cap:
        bad.append(f"正文 {len(body)} 字，超过 {cap}（{'这个仓库九成真人帖的长度' if cap != MAX_BODY else '上限'}）；砍到一件事、几句话")
    if re.search(r"日志|log", body, re.I) and not re.search(r"\.zip|附件|user-attachments", body):
        bad.append("提到日志却没有附件 / 压缩包（按人家要求的形式交文件，不贴文字）")
    return bad


def _parse_md(text: str) -> dict:
    fm = {}
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    body = text
    if m:
        for ln in m.group(1).splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1)
                fm[k.strip()] = v.strip().strip("'\"")
        body = m.group(2)
    # 字段 = 「名字:」独占一行、下一行是占位提示 [请…]；下一行是链接的是前置检查（搜索/疑难解答），不算字段。
    fields = []
    blines = body.splitlines()
    for i, ln in enumerate(blines):
        if not re.match(r"^[^\[\s#].{1,30}[:：]\s*$", ln):
            continue
        nxt = next((x for x in blines[i + 1:] if x.strip()), "")
        if re.match(r"^\[.*\]\(http", nxt) or nxt.startswith("http"):
            continue
        name = ln.rstrip(":：").strip()
        fields.append((name, not re.search(r"可选|optional", name, re.I)))
    route = "discussion" if re.search(r"请去讨论区|去 ?discussions|Discussions first.*not issues", body, re.I) else "issue"
    notes = [ln.strip() for ln in body.splitlines() if re.search(r"请去|先搜索|Search existing|请先", ln)]
    return {"kind": "md", "title": fm.get("title", ""), "labels": [x.strip() for x in fm.get("labels", "").split(",") if x.strip()],
            "fields": fields, "route": route, "notes": notes[:4]}


def _parse_yml(text: str) -> dict:
    fields, cur_label, cur_req = [], None, False
    for ln in text.splitlines():
        if m := re.match(r"\s*label:\s*(.+)", ln):
            if cur_label:
                fields.append((cur_label, cur_req))
            cur_label, cur_req = m.group(1).strip().strip("'\""), False
        if re.match(r"\s*required:\s*true", ln):
            cur_req = True
    if cur_label:
        fields.append((cur_label, cur_req))
    labels = re.search(r'labels:\s*\[(.*?)\]', text)
    return {"kind": "yml", "title": "", "labels": [x.strip().strip('"') for x in labels.group(1).split(",")] if labels else [],
            "fields": fields, "route": "issue", "notes": ["表单模板：必须走网页表单提交（命令行提不上标签，勾选框要真实点击）"]}


def _parse_pr(text: str) -> dict:
    fields = [(h.strip(), True) for h in re.findall(r"^##\s+(.+)$", text, re.M)]
    notes = [ln.strip() for ln in text.splitlines() if re.search(r"请先联系作者|discuss it with the community", ln)]
    return {"kind": "pr", "title": "", "labels": [], "fields": fields, "route": "pr", "notes": notes}


def _unreadable(repo: str, e: TemplatesUnreadable) -> int:
    print(f"✗ 读不到 {repo} 的模板（不是「没有模板」）：{e}")
    print("  缓存没动；网络 / 登录好了再跑一次。读不到模板就不许发。")
    return 3


def cmd_rules(repo: str) -> int:
    try:
        t = _fetch_templates(repo)
    except TemplatesUnreadable as e:
        return _unreadable(repo, e)
    print(f"▶ {repo} 的规矩（模板已缓存到 {CACHE / repo.replace('/', '__')}）")
    for name, info in t.items():
        print(f"\n  [{name}]  发到：{'讨论区 Discussions' if info['route'] == 'discussion' else info['route']}"
              f"{'  标题前缀 ' + info['title'] if info['title'] else ''}"
              f"{'  标签 ' + ','.join(info['labels']) if info['labels'] else ''}")
        for f, req in info["fields"]:
            print(f"     {'必填' if req else '选填'}  {f}")
        for n in info["notes"]:
            print(f"     ⚠ {n}")
    print("\n  通用：正文不许有自造 # 标题 / 加粗 / 表格 / 推脱话；先 dup 查重；发完用 gh 核实真的发出去了。")
    return 0


def _load_draft(path: Path, kind: str = "md", fields: set[str] | None = None) -> tuple[str, dict[str, str], str]:
    # `fields`: the template's own labels. A line that is exactly one of them plus a colon
    # opens that section whatever its length -- MAA's checkbox label is 80+ chars, which the
    # 30-char generic pattern below can never match, so no MAA draft could ever pass.
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = lines[0][1:].strip() if lines and lines[0].startswith("#") else ""
    body = "\n".join(lines[1:]).strip()
    sections: dict[str, str] = {}
    cur = None
    for ln in lines[1:]:
        if kind == "pr":
            m = re.match(r"^##\s+(.+?)\s*$", ln)
        elif fields and re.sub(r"[:：]\s*$", "", ln) in fields and re.search(r"[:：]\s*$", ln):
            m = re.match(r"^(.*?)[:：]\s*$", ln)
        else:
            m = re.match(r"^([^\s\[#].{1,30}?)[:：]\s*$", ln)
        if m:
            cur = m.group(1).strip()
            sections[cur] = ""
        elif cur is not None:
            sections[cur] += ln + "\n"
    return title, {k: v.strip() for k, v in sections.items()}, body


def cmd_lint(repo: str, template: str, draft: Path) -> int:
    try:
        t = _fetch_templates(repo)
    except TemplatesUnreadable as e:
        return _unreadable(repo, e)
    if template == "-" and not t:
        # The repo has no issue templates (MistEO/MXU): title and the style half only.
        info = {"kind": "md", "title": "", "fields": [], "route": "issue"}
    elif template not in t:
        print(f"✗ {repo} 没有模板 {template!r}，有的是：{', '.join(t) or '（一个都没有，模板名写 -）'}"); return 2
    else:
        info = t[template]
    title, sections, body = _load_draft(draft, kind=info["kind"], fields={f for f, _ in info["fields"]})
    bad: list[str] = []
    if info["kind"] == "pr":
        # PR 模板的勾选框：每个必须出现且要么 [x] 要么明确 [ ]，不许删
        want_boxes = [ln.strip() for ln in (CACHE / repo.replace("/", "__") / "PULL_REQUEST_TEMPLATE.md")
                      .read_text(encoding="utf-8").splitlines() if ln.strip().startswith("- [ ]")]
        for wb in want_boxes:
            label = wb[6:].strip()
            if label not in body:
                bad.append(f"PR 模板的勾选项没保留：{label[:40]}")
        if not re.search(r"- \[x\].*(已联系作者|不适用|Not applicable|contacted the author)", body):
            bad.append("「新功能或大改确认」那组勾选框一个都没勾——新功能必须先讨论并勾「已联系作者或已在社区讨论」")
        if not re.search(r"discussions/\d+|issues/\d+|#\d+", body):
            bad.append("PR 正文里没有任何 issue / 讨论链接（模板要「相关讨论链接」）")
    if not title:
        bad.append("草稿第一行要是 `# 标题`")
    if info["title"] and not title.startswith(info["title"]):
        bad.append(f"标题必须以 {info['title']} 开头（模板规定）")
    if info["route"] == "discussion":
        print("  ⚠ 这个模板明说要发到讨论区（Discussions），不是 issue")
    for f, req in info["fields"]:
        if f not in sections:
            bad.append(f"缺字段「{f}」（模板要求，{'必填' if req else '选填'}——选填也要写上字段名，没有就写「无」）")
        elif req and not sections[f]:
            bad.append(f"字段「{f}」是必填，现在是空的")
        elif re.search(r"\[.*(请|Describe|In one sentence).*\]", sections.get(f, "")):
            bad.append(f"字段「{f}」里还留着模板的占位提示")
    extra = [k for k in sections if k not in {f for f, _ in info["fields"]}]
    if extra and info["fields"]:
        bad.append(f"多出了模板没有的字段：{extra}（别自创分节）")
    allowed_heads = {f for f, _ in info["fields"]}
    stray = [h for h in re.findall(r"^\s*#{1,3}\s+(.+?)\s*$", body, re.M) if h.strip() not in allowed_heads]
    if stray:
        bad.append(f"AI 味：自造的标题（模板没有）：{stray[:3]}")
    bad += [b for b in style_problems(body, repo, pr=info["kind"] == "pr") if not b.startswith("提到日志")]
    if "日志" in " ".join(f for f, _ in info["fields"]) and not re.search(r"\.zip|附件|user-attachments", body):
        bad.append("模板要日志，草稿里没有附件/压缩包的字样——按人家要求的形式交文件")
    for b in bad:
        print(f"  ✗ {b}")
    if bad:
        print(f"❌ 草稿不过，{len(bad)} 处；不许发")
        return 1
    print(f"✅ 草稿符合 {repo} 的 {template}（{len(body)} 字，{len(sections)} 个字段）")
    return 0


def cmd_dup(repo: str, words: list[str]) -> int:
    q = " OR ".join(words)
    print(f"▶ {repo} 查重：{q}")
    try:
        print(_gh("issue", "list", "-R", repo, "--state", "all", "--search", q, "--limit", "10",
                  "--json", "number,title,state", "--jq", '.[] | "  issue #\\(.number) \\(.state) \\(.title)"') or "  （issue 无）")
    except subprocess.CalledProcessError as e:
        print("  issue 查重失败：", e.stderr.strip()[:200])
    owner, name = repo.split("/")
    for w in words:
        try:
            out = _gh("api", "graphql", "-f", f'query={{ search(query:"repo:{repo} {w}", type:DISCUSSION, first:5){{ nodes{{ ... on Discussion {{ number title category{{name}} }} }} }} }}',
                      "--jq", '.data.search.nodes[] | "  讨论 #\\(.number) [\\(.category.name)] \\(.title)"')
            print(out or f"  （讨论区无「{w}」）")
        except subprocess.CalledProcessError:
            print(f"  讨论区查「{w}」失败")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "rules":
        return cmd_rules(argv[1])
    if len(argv) >= 4 and argv[0] == "lint":
        return cmd_lint(argv[1], argv[2], Path(argv[3]))
    if len(argv) >= 3 and argv[0] == "dup":
        return cmd_dup(argv[1], argv[2:])
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
