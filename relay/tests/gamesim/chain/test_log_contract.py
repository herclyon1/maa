"""T7: the log contract. What OK-WW and our overlay print is what the relay reads (gamesim design 3).

The relay judges an OK-WW run from its log alone: outcome.okww_checks (the run's verdict and
the group's 「没干成」 items), collector_okww (the report fields and the failure reason),
gamelog_errors (the ERROR lines that reach the group), weeklyboss (the claims left) and the
echo-farm watchdog (echofarm.progress_since / level_since). Every one of them keys on words
someone else prints. When the words and the rule drift apart nothing fails: the verdict just
goes quiet or wrong (09-08 a wrapper line nobody could read, 09-21 traceback frames booked as a
nest fight, 10-13 the stamina-flag rule keyed on a prefix the line no longer had).

Two parts, both judged by the relay's own code (never a copy of it):

  scenarios  each OK-WW scenario (relay/tests/gamesim/okww/scenarios/**) is played on Windows by
             the real OK-WW with the real overlay (ci_prepare.py, lane `installed`); the
             harness writes the lines the task logged, in OK-WW's own log format
             (harness._LogDump). Each scenario's `expect.verdict` says what the relay must
             make of that log, with its evidence. On Windows (`--logs DIR`) the fresh logs
             are judged; on the Mac the copies committed in chain/logs/ (refreshed from a
             Windows run with --save), and the Windows run also fails when the overlay no
             longer prints a line the committed copies count for a rule site
             (test_gl_rule_sites.py counts them).
  machine    real machine logs the relay misread (MACHINE below), each red at its fix's
             parent and green at the fix: `--prove` runs this file on `git archive` trees.

    relay-python tests/gamesim/chain/test_log_contract.py                    # Mac: committed logs
    relay-python tests/gamesim/chain/test_log_contract.py --logs DIR         # Windows: fresh logs
    relay-python tests/gamesim/chain/test_log_contract.py --save DIR --source TEXT
    relay-python tests/gamesim/chain/test_log_contract.py --prove [--case ID]
    ... [--relay-root DIR] [--case ID] [--show]
"""
from __future__ import annotations

import gzip
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent            # relay/tests/gamesim/chain
TESTS = HERE.parents[1]                           # relay/tests
OWN_RELAY = TESTS.parent                          # relay
REPO = OWN_RELAY.parent
OKWW = TESTS / "gamesim" / "okww"
LOGS = HERE / "logs"                              # committed scenario logs (<case>.log.gz)
MACHINE_DIR = HERE / "machine"
SOURCE = LOGS / "SOURCE.json"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(OKWW))
import scenario as scn  # noqa: E402  pure Python (scenario.py), no OK-WW needed

UID = re.compile(r"特征码[:：]\s*\d")
# The game server's clock (core/config.py SERVER_TZ): OK-WW's log lines carry the machine's
# local time, UTC+8, and echofarm reads them so.
SERVER_TZ = timezone(timedelta(hours=8))
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} ", re.M)

# ------------------------------------------------------------------------------ machine cases
# Real machine logs the relay misread, each with what it must say (from evidence, not from the
# code) and the fix that made it say so. `judge` names what is read: "checks" (okww_checks with
# `args`) and / or "error" (collector_okww._okww_error), both always computed.
MACHINE = [
    {
        "id": "0908-refused-start",
        "incident": "gamesim incidents.csv 09-08 V2: 22:55 OK-WW wrapper line unreadable; 23:02 "
                    "refusal to start reported as 'stopped'",
        "input": "gamesim/chain/machine/2026-09-08_OK-WW-05-35-44.log.gz",
        "args": {"expect_nest": False},
        "expect": {
            # Upstream's own words for the failure, line 241 of this log:
            # 「DailyTask:info_set 错误 Please start in game world and in team!」 - the game
            # was not in the open world with a team out. The reason must say that, not quote
            # the wrapper raw or say only that the daily list stopped.
            "error_any_of": [["大世界", "游戏世界"], ["队伍"]],
            "error_lacks": ["不认识", "原文照抄", "Daily Task exception stopped", "整个停了"],
        },
        "evidence": [
            {"kind": "log", "ref": "AUTO-MAS history 2026-09-08/wuwa/OK-WW-05-35-44.log:241-249 "
                                   "(upstream: 'Please start in game world and in team!', then "
                                   "TaskExecutor's '📅 Daily Task exception stopped' wrapper)"},
            {"kind": "relay", "ref": "relay.log 09-08 09:46:09 WARNING ark.collector 「OK-WW 报错中继还没有"
                                     "翻译，通知里只能说不认识：任务 TaskExecutor，异常 Exception，原文「📅 Daily "
                                     "Task exception stopped」」 - what the relay made of this run"},
            {"kind": "commit", "ref": "ed5189f3: 「The notification said only 「日常清单整个停了」 - the "
                                      "outermost wrapper」; the reason is upstream's own error line"},
        ],
        "proof": {"red_at": ["43b9d6ff~1", "ed5189f3~1"], "green_at": "ed5189f3"},
    },
    {
        "id": "0921-traceback-not-a-nest-fight",
        "incident": "gamesim incidents.csv 09-21 V1: weekly-boss traceback words "
                    "(click_team_challenge / echo captured) counted an unfarmed nest as farmed",
        "input": "fixtures/m6-okww/0921-weekly.log",
        "args": {"expect_nest": True},
        "expect": {
            # The slice holds the weekly boss's part of the run only: no nest line at all.
            # The words the old rule matched sit in traceback frames of FarmEchoTask's error
            # (lines 27-28, 65-66 of the slice), so the nest must not be booked as done.
            "done_lacks": ["残象聚落"],
            "has": ["残象聚落"],
        },
        "evidence": [
            {"kind": "log", "ref": "fixtures/m6-okww/0921-weekly.log: 212 lines, each verbatim in the "
                                   "machine's 2026-09-21 OK-WW-05-33-53.log (gamesim corpus okww, UID "
                                   "aside); lines 27-28 and 65-66 are traceback frames "
                                   "(self.click_team_challenge()) of FarmEchoTask's 'Teleport to boss failed'"},
            {"kind": "ledger", "ref": "wuwa-audit #5 (gamesim failures incidents.csv row 18): the nest "
                                      "was counted farmed from those frames"},
            {"kind": "commit", "ref": "6585d7f3: upstream never logs click_team_challenge / echo "
                                      "captured (BaseWWTask.py:678-683, :1115-1117 have no log call)"},
        ],
        "proof": {"red_at": ["6585d7f3~1"], "green_at": "6585d7f3"},
    },
]

# Relay fixes a scenario's verdict depends on: the scenario log (the overlay's real lines) is judged
# wrong by the relay before the fix and right at it. `--prove` runs them like the machine cases.
SCENARIO_PROOFS = [
    {"case": "three_failures_arkstopped", "red_at": ["5fddd375~1"], "green_at": "5fddd375",
     "why": "ledger 761 (BOARD/报错台账.txt): a log with 「这一趟按失败结束：」 was judged all done"},
    {"case": "no_stamina_flag", "red_at": ["5ea2cc7f~1"], "green_at": "5ea2cc7f",
     "why": "the 「不刷体力」 flag's refusal line was not read: the stamina item gave another reason"},
    {"case": "main_path_1012", "red_at": ["f22fe3e7~1"], "green_at": "f22fe3e7",
     "why": "a verified weekly claim's 60 waveplates were not counted spent (10-12 11:41: three claims, "
            "nothing spent shown; audit 2026-10-13 item 12)"},
    {"case": "main_book_team_1013", "red_at": ["e0448a66~1"], "green_at": "e0448a66",
     "why": "the echo-farm wrap-up could not name the level the game showed (10-13: Lv.90 fought, 80 configured)"},
    {"case": "revive_is_revived_continues", "red_at": ["2d2d45fc~1"], "green_at": "2d2d45fc",
     "why": "5538a9a2's rule, progress not noise: the watchdog had no count of progress lines, so a revive "
            "and farming on was not progress"},
]

# ------------------------------------------------------------------------------ the relay


def _first(names, attr):
    """`attr` of the first importable module of `names` that has it (the relay moved modules
    between eras); None when no era module has it - that era said nothing there."""
    for name in names:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name and name.startswith(exc.name):
                continue
            raise
        if hasattr(mod, attr):
            return getattr(mod, attr)
    return None


class Relay:
    """The relay's log-reading functions, from one relay tree."""

    def __init__(self, root: Path, tmp: Path):
        os.environ.update(ARK_STATE_DIR=str(tmp / "state"), ARK_HISTORY_DIR=str(tmp / "history"),
                          ARK_AUTOMAS_DIR="", ARK_OKWW_DIR="", ARK_MAAEND_DIR="", ARK_MAA_DIR="",
                          ARK_ALERT_PUSH_URL="")
        sys.path.insert(0, str(root))
        out = ["ark_relay.features.verify.outcome", "ark_relay.outcome"]
        col = ["ark_relay.features.verify.collector_okww", "ark_relay.collector_okww", "ark_relay.collector"]
        self.okww_checks = _first(out, "okww_checks")
        self.summarize = _first(out, "summarize")
        self.parse_okww_log = _first(col, "parse_okww_log")
        self.okww_error = _first(col, "_okww_error")
        self.unregistered = _first(["ark_relay.features.verify.gamelog_errors"], "unregistered")
        self.left_after_claims = _first(["ark_relay.features.weekly.weeklyboss", "ark_relay.weeklyboss"],
                                        "left_after_claims")
        ef = ["ark_relay.features.echofarm.echofarm", "ark_relay.echofarm"]
        self.progress_since = _first(ef, "progress_since")
        self.level_since = _first(ef, "level_since")
        if self.okww_checks is None or self.parse_okww_log is None:
            raise RuntimeError(f"HARNESS: no okww_checks / parse_okww_log under {root}")


def _start(text: str) -> "datetime | None":
    m = _TS.search(text)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=SERVER_TZ) - timedelta(seconds=1)


def judge(relay: Relay, text: str, args: dict, log_path: Path) -> dict:
    """What the relay makes of one OK-WW log."""
    sig = inspect.signature(relay.okww_checks).parameters
    checks = relay.okww_checks(text, **{k: v for k, v in args.items() if k in sig})
    got = {
        "failed": [f"{c.label}：{c.detail}" if c.detail else c.label for c in checks if not c.ok],
        "done": [c.label for c in checks if c.ok],
        "clean": relay.summarize(checks, "OK-WW") is None if relay.summarize else None,
        "raw": {k: v for k, v in relay.parse_okww_log(log_path).items() if k.startswith("okww_")},
        "error": relay.okww_error(text) if relay.okww_error else None,
        "unregistered": [ln for ln, _ in relay.unregistered("OK-WW", text)] if relay.unregistered else None,
        "weekly_left": relay.left_after_claims(text) if relay.left_after_claims else None,
    }
    os.environ["ARK_OKWW_LOG"] = str(log_path)
    start = _start(text)
    got["progress"] = relay.progress_since(start) if relay.progress_since else None
    lvl = relay.level_since(start) if relay.level_since else None
    got["level"] = list(lvl) if lvl else None
    return got


def _text(v) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def compare(exp: dict, got: dict) -> "list[str]":
    """Each expectation `got` breaks, in words."""
    bad = []
    failed, done = "\n".join(got["failed"]), "、".join(got["done"])
    if "clean" in exp and got["clean"] != exp["clean"]:
        bad.append(f"clean: want {exp['clean']}, got {got['clean']} (failed {got['failed']})")
    bad += [f"failed items lack {s!r}: {got['failed']}" for s in exp.get("has", []) if s not in failed]
    bad += [f"failed items have {s!r}: {got['failed']}" for s in exp.get("lacks", []) if s in failed]
    bad += [f"passed items lack {s!r}: {got['done']}" for s in exp.get("done_has", []) if s not in done]
    bad += [f"passed items have {s!r}: {got['done']}" for s in exp.get("done_lacks", []) if s in done]
    for key, want in (exp.get("raw") or {}).items():
        if got["raw"].get(key) != want:
            bad.append(f"raw {key}: want {want!r}, got {got['raw'].get(key)!r}")
    for key, subs in (exp.get("raw_has") or {}).items():
        seen = _text(got["raw"].get(key, ""))
        bad += [f"raw {key} lacks {s!r}: {seen[:300]!r}" for s in subs if s not in seen]
    for key, subs in (exp.get("raw_lacks") or {}).items():
        seen = _text(got["raw"].get(key, ""))
        bad += [f"raw {key} has {s!r}: {seen[:300]!r}" for s in subs if s in seen]
    err = got["error"] or ""
    bad += [f"error reason lacks {s!r}: {err!r}" for s in exp.get("error_has", []) if s not in err]
    bad += [f"error reason has {s!r}: {err!r}" for s in exp.get("error_lacks", []) if s in err]
    for alts in exp.get("error_any_of", []):
        if not any(s in err for s in alts):
            bad.append(f"error reason has none of {alts!r}: {err!r}")
    if "unregistered" in exp:
        lines, want = got["unregistered"], exp["unregistered"]
        if lines is None:
            bad.append("this relay has no gamelog_errors.unregistered")
        else:
            bad += [f"unregistered ERROR line not expected: {ln[:200]!r}" for ln in lines
                    if not any(s in ln for s in want)]
            bad += [f"no unregistered ERROR line has {s!r}" for s in want if not any(s in ln for ln in lines)]
    if "weekly_left" in exp and got["weekly_left"] != exp["weekly_left"]:
        bad.append(f"weekly_left: want {exp['weekly_left']}, got {got['weekly_left']}")
    if "progress_min" in exp and (got["progress"] or 0) < exp["progress_min"]:
        bad.append(f"echo-farm progress lines: want at least {exp['progress_min']}, got {got['progress']}")
    if "level" in exp and got["level"] != exp["level"]:
        bad.append(f"echo-farm level: want {exp['level']}, got {got['level']}")
    return bad


# ------------------------------------------------------------------------------ inputs

def _read(path: Path) -> str:
    data = path.read_bytes()
    if path.name.endswith(".gz"):
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def with_context(text: str, context: "list[dict]") -> str:
    """The scenario's log with the verdict's context lines first, stamped with its first time:
    the lines upstream's run() logs before the part of the run a scenario starts at."""
    if not context:
        return text
    m = _TS.search(text)
    stamp = m.group(0).rstrip() if m else "1970-01-01 00:00:00,000"
    return "".join(f"{stamp} {c['text']}\n" for c in context) + text


def scenarios() -> "list[tuple[str, scn.Scenario]]":
    """(path under scenarios/, scenario) of every scenario file."""
    return [(p.relative_to(scn.SCENARIOS).as_posix(), scn.load(p)) for p in sorted(scn.SCENARIOS.rglob("*.json"))]


def fresh_logs(folder: Path) -> "dict[str, list[tuple[Path, dict]]]":
    """case -> [(log, meta)] that harness._dump_chain wrote in one Windows run."""
    out: dict = {}
    for meta_path in sorted(folder.glob("*.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        out.setdefault(meta["case"], []).append((meta_path.with_suffix(".log"), meta))
    return out


def save(folder: Path, source: str) -> int:
    """Refresh chain/logs/ from a Windows run's chain folder (the job artifact)."""
    logs = fresh_logs(folder)
    LOGS.mkdir(exist_ok=True)
    kept = {}
    for rel, sc in scenarios():
        runs = logs.get(sc.case)
        if not runs:
            raise SystemExit(f"{folder} has no log of {rel}")
        log, meta = runs[0]
        data = log.read_bytes()
        if UID.search(data.decode("utf-8", errors="replace")):
            raise SystemExit(f"{log} carries a player UID (特征码 digits); the repository is public")
        (LOGS / f"{sc.case}.log.gz").write_bytes(gzip.compress(data, mtime=0))
        kept[sc.case] = {k: meta.get(k) for k in ("scenario", "test", "lane", "okww_tag", "overlay",
                                                  "overlay_sha256", "lines")}
    SOURCE.write_text(json.dumps({"source": source, "logs": kept}, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
    print(f"{len(kept)} scenario logs written to {LOGS} ({source})")
    return 0


# ------------------------------------------------------------------------------ the checks

def check_scenarios(relay: Relay, tmp: Path, fresh: "Path | None", only: "str | None", show: bool) -> "list[str]":
    fails = []
    logs = fresh_logs(fresh) if fresh else None
    for rel, sc in scenarios():
        if only and sc.case != only:
            continue
        v = sc.expect.get("verdict")
        if v is None:
            fails.append(f"{rel}: no expect.verdict (what the relay must make of its log)")
            print(f"  ✗ {rel}: no expect.verdict")
            continue
        if logs is not None:
            runs = [log for log, _meta in logs.get(sc.case, [])]
            if not runs:
                fails.append(f"{rel}: this run wrote no log for it")
                print(f"  ✗ {rel}: no log in {fresh}")
                continue
        else:
            committed = LOGS / f"{sc.case}.log.gz"
            if not committed.is_file():
                fails.append(f"{rel}: no committed log {committed.relative_to(TESTS)} (--save from a Windows run)")
                print(f"  ✗ {rel}: no committed log")
                continue
            runs = [committed]
        for src in runs:
            text = with_context(_read(src), v.get("context", []))
            path = tmp / f"{sc.case}.log"
            path.write_text(text, encoding="utf-8")
            got = judge(relay, text, v["args"], path)
            if show:
                print(json.dumps({"case": sc.case, **got}, ensure_ascii=False, default=str))
            bad = compare(v, got)
            if bad:
                fails.append(sc.case)
                print(f"  ✗ {rel} ({src.name})")
                for b in bad:
                    print(f"      {b}")
            else:
                print(f"  ✓ {rel}")
    return fails


def check_machine(relay: Relay, tmp: Path, only: "str | None", show: bool) -> "list[str]":
    fails = []
    for c in MACHINE:
        if only and c["id"] != only:
            continue
        src = TESTS / c["input"]
        text = _read(src)
        path = tmp / f"{c['id']}.log"
        path.write_text(text, encoding="utf-8")
        got = judge(relay, text, c.get("args", {"expect_nest": False}), path)
        if show:
            print(json.dumps({"case": c["id"], **got}, ensure_ascii=False, default=str))
        bad = compare(c["expect"], got)
        if bad:
            fails.append(c["id"])
            print(f"  ✗ {c['id']} ({c['input']})")
            for b in bad:
                print(f"      {b}")
        else:
            print(f"  ✓ {c['id']} ({c['input']})")
    return fails


def check_inputs() -> "list[str]":
    """The committed inputs themselves: evidence and proof on every machine case, no UID, the
    scenario logs' source named."""
    out = []
    ids = [c["id"] for c in MACHINE]
    if len(set(ids)) != len(ids):
        out.append("duplicate machine case ids")
    for c in MACHINE:
        if not c.get("evidence") or not all(e.get("kind") and e.get("ref") for e in c["evidence"]):
            out.append(f"{c['id']}: evidence [{{kind, ref}}] outside the code")
        p = c.get("proof") or {}
        if not (p.get("red_at") and p.get("green_at")):
            out.append(f"{c['id']}: proof needs red_at and green_at (red before green)")
        if not (TESTS / c["input"]).is_file():
            out.append(f"{c['id']}: input {c['input']} missing")
    for f in [*sorted(MACHINE_DIR.glob("*")), *sorted(LOGS.glob("*.log.gz"))]:
        body = _read(f)
        if UID.search(body):
            out.append(f"{f.relative_to(TESTS)} carries a player UID (特征码 digits)")
        for needle in ("AKID", "qyapi.weixin.qq.com/cgi-bin/webhook", "sctapi.ftqq.com/SCT"):
            if needle in body:
                out.append(f"{f.relative_to(TESTS)} carries {needle!r}")
    if any(LOGS.glob("*.log.gz")) and not SOURCE.is_file():
        out.append(f"{SOURCE.relative_to(TESTS)} missing: which Windows run wrote the logs")
    return out


def check_coverage(fresh: Path) -> "list[str]":
    """A rule site the committed scenario logs give a line must still get one from this run's
    logs: test_gl_rule_sites.py counts the committed copies on the Mac."""
    import test_gl_rule_sites as rs  # noqa: PLC0415 - imports the relay; after Relay set the env
    committed = rs.Lines(sorted(LOGS.glob("*.log.gz")))
    now = rs.Lines(sorted(fresh.glob("*.log")))
    out = []
    for r in rs.sites():
        if rs.hit(r, committed) is not None and rs.hit(r, now) is None:
            out.append(f"{r['module']}:{r['line']} {r['pat']!r}: the committed scenario logs have a line "
                       "for it, this run's do not (the overlay no longer prints it): refresh chain/logs")
    return out


def prove(only: "str | None") -> int:
    """Run the machine cases and SCENARIO_PROOFS at each red_at / green_at commit (git archive of
    relay/): red must be this case failing an expectation, never a harness error."""
    import tempfile  # noqa: PLC0415
    bad = 0
    todo = [(c["id"], c["proof"], ["--machine-only"]) for c in MACHINE]
    todo += [(s["case"], s, []) for s in SCENARIO_PROOFS]
    for cid, proof, extra in todo:
        if only and cid != only:
            continue
        for rev, want in [*((r, 1) for r in proof["red_at"]), (proof["green_at"], 0)]:
            with tempfile.TemporaryDirectory(prefix="t7-prove-") as d:
                tar = subprocess.run(["git", "-C", str(REPO), "archive", rev, "relay"], check=True,
                                     capture_output=True).stdout
                subprocess.run(["tar", "-x", "-C", d], input=tar, check=True)
                p = subprocess.run([sys.executable, str(Path(__file__).resolve()), *extra,
                                    "--relay-root", str(Path(d) / "relay"), "--case", cid],
                                   capture_output=True, text=True)
            out = p.stdout + p.stderr
            harness = "HARNESS" in out or "Traceback" in out
            mine = any(ln.startswith("  ✗ ") and (f"✗ {cid} " in ln or f"/{cid}.json" in ln) for ln in out.splitlines())
            ok = p.returncode == want and not harness and (want == 0 or mine)
            first = next((ln.strip() for ln in out.splitlines() if ln.startswith("      ")), "")
            print(f"  {'✓' if ok else '✗'} {cid} at {rev}: {'red' if p.returncode else 'green'}"
                  f" (want {'red' if want else 'green'}) {first[:160]}")
            if not ok:
                bad += 1
                if harness:
                    print(out[-1500:])
    print("\n" + ("all checks passed" if not bad else f"FAILED: {bad}"))
    return 1 if bad else 0


def main(argv: "list[str]") -> int:
    a = {"logs": None, "root": None, "case": None, "show": False, "save": None, "source": None,
         "prove": False, "machine_only": False}
    it = iter(argv)
    for x in it:
        if x == "--logs":
            a["logs"] = Path(next(it)).resolve()
        elif x == "--relay-root":
            a["root"] = Path(next(it)).resolve()
        elif x == "--case":
            a["case"] = next(it)
        elif x == "--save":
            a["save"] = Path(next(it)).resolve()
        elif x == "--source":
            a["source"] = next(it)
        elif x == "--show":
            a["show"] = True
        elif x == "--prove":
            a["prove"] = True
        elif x == "--machine-only":
            a["machine_only"] = True
        else:
            raise SystemExit(f"unknown argument {x!r}")
    if a["save"]:
        if not a["source"]:
            raise SystemExit("--save needs --source (the Windows run it came from)")
        return save(a["save"], a["source"])
    if a["prove"]:
        return prove(a["case"])
    from _tmp import tmpdir  # noqa: PLC0415 - relay/tests/_tmp.py
    tmp = tmpdir("gl-t7-")
    relay = Relay(a["root"] or OWN_RELAY, tmp)
    fails = []
    if a["root"] is None and not a["case"]:
        for p in check_inputs():
            fails.append(p)
            print(f"  ✗ inputs: {p}")
    print("machine logs:")
    fails += check_machine(relay, tmp, a["case"], a["show"])
    if not a["machine_only"]:
        print("scenario logs" + (f" ({a['logs']})" if a["logs"] else " (committed)") + ":")
        fails += check_scenarios(relay, tmp, a["logs"], a["case"], a["show"])
        if a["logs"] and not a["case"]:
            for p in check_coverage(a["logs"]):
                fails.append(p)
                print(f"  ✗ coverage: {p}")
    print("\nT7 log contract: " + (f"FAILED: {len(fails)}" if fails else "all checks passed"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
