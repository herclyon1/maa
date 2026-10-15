"""T8: OK-WW run verdicts on real runs, against verdicts fixed by evidence outside the code.

gamesim unit U13a (design: offline game-layer harness, section 3 "Corpora", T8). Each case in
tests/gamesim/corpus/okww/cases.json is one real AUTO-MAS record of an OK-WW run (the
history .json and its .log, kept gzipped under runs/<date>/wuwa/) and what the relay must say
about it. The expected values never come from the code under test: every case carries an
`evidence` list (the owner's failure ledger line, his words, the fix commit, the alarm the
relay actually pushed, a frame), and every listed failure was shown red at its fix's parent
and green at the fix (gamesim/corpus/okww/prove.py; results in the corpus README).

What is run is the relay's own verdict path, as handle.py runs it after a record lands:
  * collector.parse_record - the record: ok, failed_tasks, the okww_* report fields
    (collector_okww);
  * verdict._verify_outcome - the outcome check (outcome.okww_checks + summarize), with the
    OK-WW config in effect laid out where gamelogs._okww_master_config reads it;
  * gamelog_errors.unregistered - the ERROR lines of a successful round that reach the
    group.
The same file runs against an older relay tree (`--relay-root DIR`, a `git archive` of
another commit's relay/): the functions are looked up where each era kept them, and a
function an era did not have yet means that era said nothing there. Run against this
tree, every one of them must exist.

    python3.14 tests/test_gl_corpus_okww.py [--case ID] [--relay-root DIR] [--show]
"""
from __future__ import annotations

import gzip
import importlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OWN_RELAY = HERE.parent
CORPUS = HERE / "gamesim" / "corpus" / "okww"
FLOOR = 10      # cases.json holds at least this many runs; fewer = the corpus was lost
EVIDENCE_KINDS = ("ledger", "owner", "commit", "alarm", "frame", "log", "relay")
UID = re.compile(r"特征码[:：]\s*\d")


def _args(argv: list[str]) -> dict:
    out = {"case": None, "root": None, "show": False}
    it = iter(argv)
    for a in it:
        if a == "--case":
            out["case"] = next(it)
        elif a == "--relay-root":
            out["root"] = Path(next(it)).resolve()
        elif a == "--show":
            out["show"] = True
        else:
            raise SystemExit(f"unknown argument {a!r}")
    return out


def _first(names: list[str], attr: str, required: bool):
    """The attribute `attr` of the first importable module in `names`; None when no era
    module has it and `required` is false."""
    for name in names:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name and name.startswith(exc.name):
                continue
            raise
        if hasattr(mod, attr):
            return getattr(mod, attr)
    if required:
        raise RuntimeError(f"HARNESS: {attr} not found in any of {names}")
    return None


class Relay:
    """The verdict functions of one relay tree, wherever its era kept them."""

    def __init__(self, root: Path, tmp: Path):
        own = root == OWN_RELAY
        os.environ.update(ARK_STATE_DIR=str(tmp / "state"), ARK_HISTORY_DIR=str(tmp / "history"),
                          ARK_AUTOMAS_DIR="", ARK_OKWW_DIR="", ARK_MAAEND_DIR="", ARK_MAA_DIR="",
                          ARK_ALERT_PUSH_URL="")
        sys.path.insert(0, str(root))
        self.parse_record = _first(["ark_relay.core.collector", "ark_relay.collector"], "parse_record", True)
        self.verify_outcome = _first(["ark_relay.features.alarm.verdict", "ark_relay.handle"],
                                     "_verify_outcome", True)
        # Added 2026-10-11 (a6fdd68b): before it, a successful round's unknown ERROR line
        # reached nobody, which is what an era without it is taken to say.
        self.unregistered = _first(["ark_relay.features.verify.gamelog_errors"], "unregistered", own)


def _materialise(case: dict, tmp: Path) -> Path:
    """The case's record and log as AUTO-MAS lays them out: <tmp>/history/<date>/wuwa/<stem>.*"""
    src = CORPUS / "runs" / case["run"]
    dst = tmp / "history" / case["run"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src.with_suffix(".json"), dst.with_suffix(".json"))
    gz = src.with_name(src.name + ".log.gz")
    if gz.exists():
        dst.with_suffix(".log").write_bytes(gzip.decompress(gz.read_bytes()))
    return dst.with_suffix(".json")


def _automas(case: dict, tmp: Path) -> "Path | None":
    """The OK-WW config in effect, where gamelogs._okww_master_config reads it."""
    cfg = case.get("config")
    if cfg is None:
        return None
    d = tmp / "automas" / case["id"]
    cf = d / "data" / "okww" / "Default" / "ConfigFile"
    cf.mkdir(parents=True, exist_ok=True)
    for name, body in cfg.items():
        if not name.startswith("_"):
            (cf / f"{name}.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return d


class _Cfg:
    maa_dir = maaend_dir = history_dir = state_dir = None

    def __init__(self, automas_dir):
        self.automas_dir = str(automas_dir) if automas_dir else None


class _Eng:
    def __init__(self, automas_dir):
        self.cfg = _Cfg(automas_dir)


def judge(relay: Relay, case: dict, tmp: Path) -> dict:
    """What the relay makes of one case's run."""
    js = _materialise(case, tmp)
    rec = relay.parse_record(js, tmp / "history")
    if rec is None:
        raise RuntimeError(f"HARNESS: parse_record did not take {case['run']} as a run")
    got = {"ok": rec.ok, "failed_tasks": list(rec.failed_tasks or []),
           "raw": {k: v for k, v in (rec.raw or {}).items() if k.startswith("okww_")}}
    says = relay.verify_outcome(_Eng(_automas(case, tmp)), rec)
    if says and "结果核对没跑成" in says:
        raise RuntimeError(f"HARNESS: the outcome check crashed: {says.splitlines()[0]}")
    got["verdict"] = says
    got["undone"] = [ln for ln in (says or "").splitlines() if ln.startswith("· ")]
    text = rec.log_path.read_text(encoding="utf-8", errors="replace") if rec.log_path else ""
    got["unregistered"] = [ln for ln, _ in relay.unregistered("OK-WW", text)] if relay.unregistered else []
    return got


def _text(v) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def compare(case: dict, got: dict) -> list[str]:
    """Each expectation of the case that `got` breaks, in words."""
    exp, bad = case["expect"], []
    if "ok" in exp and got["ok"] != exp["ok"]:
        bad.append(f"record ok: want {exp['ok']}, got {got['ok']}")
    for key, want in (exp.get("raw") or {}).items():
        if got["raw"].get(key) != want:
            bad.append(f"raw {key}: want {want!r}, got {got['raw'].get(key)!r}")
    for key, subs in (exp.get("raw_has") or {}).items():
        seen = _text(got["raw"].get(key, ""))
        bad += [f"raw {key} lacks {s!r}: {seen[:300]!r}" for s in subs if s not in seen]
    for key, subs in (exp.get("raw_lacks") or {}).items():
        seen = _text(got["raw"].get(key, ""))
        bad += [f"raw {key} has {s!r}: {seen[:300]!r}" for s in subs if s in seen]
    ft = "\n".join(got["failed_tasks"])
    for s in (exp.get("failed_tasks") or {}).get("has", []):
        if s not in ft:
            bad.append(f"failed_tasks lacks {s!r}: {got['failed_tasks']!r}")
    for s in (exp.get("failed_tasks") or {}).get("lacks", []):
        if s in ft:
            bad.append(f"failed_tasks has {s!r}: {got['failed_tasks']!r}")
    for alts in (exp.get("failed_tasks") or {}).get("any_of", []):
        if not any(s in ft for s in alts):
            bad.append(f"failed_tasks has none of {alts!r}: {got['failed_tasks']!r}")
    v = exp.get("verdict") or {}
    undone = "\n".join(got["undone"])
    if "clean" in v and (got["verdict"] is None) != v["clean"]:
        bad.append(f"verdict clean: want {v['clean']}, got {got['verdict']!r}")
    bad += [f"undone items lack {s!r}: {got['undone']!r}" for s in v.get("has", []) if s not in undone]
    bad += [f"undone items have {s!r}: {got['undone']!r}" for s in v.get("lacks", []) if s in undone]
    # What reaches the group for a successful round: the undone items and the ERROR lines
    # nobody registered (handle._handle_success).
    group = undone + "\n" + "\n".join(got["unregistered"])
    for alts in (exp.get("group") or {}).get("any_of", []):
        if not any(s in group for s in alts):
            bad.append(f"the group hears none of {alts!r}: {group.strip()[:400]!r}")
    bad += [f"the group hears {s!r}: {group.strip()[:400]!r}"
            for s in (exp.get("group") or {}).get("none_of", []) if s in group]
    return bad


def corpus_problems(cases: list[dict]) -> list[str]:
    """The corpus itself: evidence on every case, inputs present, no secret in the files."""
    out = []
    if len(cases) < FLOOR:
        out.append(f"only {len(cases)} cases in cases.json, at least {FLOOR} expected")
    ids = [c.get("id") for c in cases]
    if len(set(ids)) != len(ids):
        out.append("duplicate case ids")
    for c in cases:
        ev = c.get("evidence") or []
        if not ev or not all(isinstance(e, dict) and e.get("kind") in EVIDENCE_KINDS and e.get("ref")
                             for e in ev):
            out.append(f"{c.get('id')}: every case needs evidence [{{kind, ref}}] outside the code "
                       f"(kinds: {', '.join(EVIDENCE_KINDS)})")
        if not c.get("expect"):
            out.append(f"{c.get('id')}: no expectation")
        src = CORPUS / "runs" / c.get("run", "?")
        if not src.with_suffix(".json").is_file():
            out.append(f"{c.get('id')}: {src.with_suffix('.json')} missing")
        proof = c.get("proof") or {}
        if not (proof.get("red_at") and all(isinstance(x, str) and x for x in proof["red_at"])
                and isinstance(proof.get("green_at"), str) and proof["green_at"]):
            out.append(f"{c.get('id')}: proof needs red_at [commits] and green_at (a commit): "
                       "a case is accepted only red before green")
    for f in sorted((CORPUS / "runs").rglob("*")):
        if not f.is_file():
            continue
        body = f.read_bytes()
        if f.suffix == ".gz":
            body = gzip.decompress(body)
        for needle in (b"AKID", b"qyapi.weixin.qq.com/cgi-bin/webhook", b"sctapi.ftqq.com/SCT"):
            if needle in body:
                out.append(f"{f.relative_to(CORPUS)} carries {needle.decode()!r}: redact it")
        # The player UID: OK-WW's OCR dumps read the game's bottom-right UID strip (the
        # strip W/config.py blur_area blacks out in screenshots). The repo is public.
        if UID.search(body.decode("utf-8", errors="replace")):
            out.append(f"{f.relative_to(CORPUS)} carries a player UID (特征码 digits): redact it")
    return out


def main(argv: list[str]) -> int:
    a = _args(argv)
    sys.path.insert(0, str(HERE))
    from _tmp import tmpdir  # noqa: PLC0415 - after HERE is on the path
    tmp = tmpdir("gl-okww-")
    cases = json.loads((CORPUS / "cases.json").read_text(encoding="utf-8"))["cases"]
    fails: list[str] = []
    own = a["root"] is None or a["root"] == OWN_RELAY
    if own:
        for p in corpus_problems(cases):
            fails.append(p)
            print(f"  ✗ corpus: {p}")
    if a["case"]:
        cases = [c for c in cases if c["id"] == a["case"]]
        if not cases:
            raise SystemExit(f"no case {a['case']!r}")
    relay = Relay(a["root"] or OWN_RELAY, tmp)
    for c in cases:
        got = judge(relay, c, tmp)
        if a["show"]:
            print(json.dumps({"id": c["id"], **got}, ensure_ascii=False, indent=1, default=str))
        bad = compare(c, got)
        if bad:
            fails.append(c["id"])
            print(f"  ✗ {c['id']} ({c['run']})")
            for b in bad:
                print(f"      {b}")
        else:
            print(f"  ✓ {c['id']} ({c['run']})")
    print(f"\nOK-WW verdict corpus: {len(cases)} runs, "
          + (f"FAILED: {len(fails)}" if fails else "all checks passed"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
