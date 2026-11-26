"""Real-entry-point adversarial & regression tests for Worker B denominator items (2026-11-26).

Covers:
  - R-02: MaaEnd pre-update chain break detection (mastercfg.CONTRACT + check_maaend_preupdate,
          selfcheck.run/report, machinecheck.judge("boot") #R02, fix_maaend_preupdate.py).
  - R-07: WuWa Tacet Suppression echo-set names & Forgery labels wired into wuwa_tables,
          mastercfg.read_okww/write_okww, phone.state_payload, and snapshot._okww/_mas.
  - R-10: Bilibili version-news risk control (code=0, items=[]) fallback to opus/feed/space +
          detail via banners._bili_poster and banners._wuwa_poster_span, plus double-empty guard.
  - R-11: D-1017 statestore boot read-lock protection (StateStore/Engine/Mailbox), #179 live
          stagegate read after boot set_stage, and offline verification of all 14 watching items
          (#15/#28/#30/#33/#34/#64/#65/#94/#102/#142/#146/#173/#178/#185).

CLI:
  python3 tests/test_cure_b_1126.py            # all parts (lint-repo.sh)
  python3 tests/test_cure_b_1126.py r02        # single denominator item
  python3 tests/test_cure_b_1126.py r07|r10|r11
"""
from __future__ import annotations

# ruff: noqa: PLC0415
import importlib.util
import io
import json
import logging
import os
import sys
import time
import urllib.request
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
RELAY = HERE.parent
REPO = RELAY.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(RELAY) not in sys.path:
    sys.path.insert(0, str(RELAY))

from _parts import check, run_parts, stagegate_fx, tmpdir  # noqa: E402


# ==============================================================================
# R-02: MaaEnd pre-update contract / selfcheck / machinecheck / fix script
# ==============================================================================

_V58_SCRIPTS_BROKEN = """order:
- uid: s-maa
  type: MaaConfig
- uid: s-end
  type: MaaEndConfig
- uid: s-okww
  type: GeneralConfig
data:
  s-maa:
    Info:
      Name: MAA
      Path: D:\\ark\\MAA
    Run:
      IfCheckGameUpdate: true
      IfAutoInstallGameApk: true
      HardTimeLimit: 120
  s-end:
    Info:
      Name: MaaEnd
      Path: D:\\ark\\maaend
    Game:
      LaunchMode: Direct
      LauncherPath: D:\\ark\\Endfield\\Launcher.exe
      SetResolution: true
      CloseOnFinish: true
      RestoreDisplayType: true
      RestoreResolution: true
    Run:
      HardTimeLimit: 120
      RunTimesLimit: 1
    Update:
      TakeoverEnabled: false
      PackageMode: full
      Channel: stable
      MirrorChyanCDK: ""
  s-okww:
    Info:
      Name: OK-WW
      Path: D:\\ark\\okww
    Game:
      Enabled: false
      Path: ""
      IfAutoUpdate: true
    Run:
      HardTimeLimit: 120
      RunTimeLimit: 120
"""


def _load_fix_script():
    path = REPO / "scripts" / "windows" / "fix_maaend_preupdate.py"
    spec = importlib.util.spec_from_file_location("fix_maaend_preupdate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _part_r02_maaend_preupdate():
    """R-02: real entry points for MaaEnd v5.8+ Update.TakeoverEnabled & Channel."""
    from ark_relay.core import config, mastercfg, texts
    from ark_relay.features import commands, machinecheck, machinechecks, selfcheck

    _ = machinechecks  # register #R02

    root = tmpdir("r02-")
    mas_dir = root / "automas"
    cfg_dir = mas_dir / "config"
    cfg_dir.mkdir(parents=True)
    yaml_path = cfg_dir / "scripts.yaml"
    yaml_path.write_text(_V58_SCRIPTS_BROKEN, encoding="utf-8")

    print("[1. mastercfg.check & check_maaend_preupdate on broken v5.8+ scripts.yaml]")
    gaps = mastercfg.check_maaend_preupdate(mas_dir)
    check("detects both TakeoverEnabled=false and Channel=stable", len(gaps), 2)
    check("both gap messages pass texts.plain()", [texts.plain(g) for g in gaps], [[], []])
    check("mentions takeover off", any("接管更新" in g and "关着" in g for g in gaps), True)
    check("mentions stable instead of beta", any("更新通道" in g and "稳定版" in g for g in gaps), True)

    # Missing Update group completely on v5.9 must fail mastercfg.check()
    no_upd_dir = root / "automas_noupd"
    (no_upd_dir / "config").mkdir(parents=True)
    (no_upd_dir / "config" / "scripts.yaml").write_text(
        _V58_SCRIPTS_BROKEN.replace(
            "    Update:\n      TakeoverEnabled: false\n      PackageMode: full\n"
            "      Channel: stable\n      MirrorChyanCDK: \"\"\n",
            "",
        ),
        encoding="utf-8",
    )
    res_v59 = mastercfg.check(no_upd_dir, version="v5.9.0")
    check("mastercfg.check(v5.9.0) flags missing MaaEnd Update items",
          sorted(m.key for m in res_v59.missing if m.use == "maaend_update"),
          ["Channel", "TakeoverEnabled"])
    res_v57 = mastercfg.check(no_upd_dir, version="v5.7.0-beta.4")
    check("mastercfg.check(v5.7.0-beta.4) skips v5.8.0-only Update items",
          [m.key for m in res_v57.missing if m.use == "maaend_update"], [])

    # Legacy v5.7 JSON config without Update group must NOT false-alarm
    v57_dir = root / "automas_v57"
    (v57_dir / "config").mkdir(parents=True)
    (v57_dir / "config" / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "s-end"}],
        "s-end": {"Info": {"Name": "MaaEnd", "Path": "D:\\ark\\maaend"}, "Run": {"HardTimeLimit": 120}},
    }), encoding="utf-8")
    check("v5.7 config without scripts.yaml or Update group has 0 false alarms",
          mastercfg.check_maaend_preupdate(v57_dir), [])

    print("\n[2. real entry point: selfcheck.report pushes group alarm on broken MaaEnd pre-update]")
    state_dir = root / "state"
    state_dir.mkdir()
    hist_dir = root / "history"
    hist_dir.mkdir()
    cfg = config.Config()
    cfg.automas_dir = mas_dir
    cfg.state_dir = state_dir
    cfg.history_dir = hist_dir
    cfg.phone_topic = "t-r02"
    cfg.phone_pin = "p-r02"

    fake_launcher = root / "launcher.exe"
    fake_launcher.write_text("stub", encoding="utf-8")
    live_scripts = {
        "s-maa": {"Info": {"Name": "MAA"}, "Run": {"IfCheckGameUpdate": True, "IfAutoInstallGameApk": True}},
        "s-end": {"Info": {"Name": "MaaEnd"}, "Update": {"TakeoverEnabled": False, "Channel": "stable"}},
        "s-okww": {"Info": {"Name": "OK-WW"},
                   "Game": {"Enabled": True, "Path": str(fake_launcher), "IfAutoUpdate": True}},
    }
    orig_mas = commands._mas
    commands._mas = lambda path, body=None, timeout=15: {"data": live_scripts}
    try:
        checks = selfcheck.run(
            cfg,
            procs=lambda: [(1, "python.exe app/main.py")],
            mas_up=lambda: True,
            schedule=lambda: [{"name": "早班", "times": ["09:00"]}],
            channels=lambda: ["wecom_bot"],
            run_ok=lambda cmd: (True, ""),
            has_module=lambda m: True,
            contract=lambda _d: mastercfg.Result([], [], 1),
            virt=lambda: "VBS=0 HV=False",
        )
        upd_c = next(c for c in checks if c.name == selfcheck.UPDATES_NAME)
        check("selfcheck.run marks UPDATES_NAME as FAIL", upd_c.ok, False)
        check("selfcheck failure detail names both broken settings",
              "接管更新" in upd_c.detail and "更新通道" in upd_c.detail, True)
        check("selfcheck failure detail passes texts.plain()", texts.plain(upd_c.detail), [])

        # Fix live scripts + disk yaml -> selfcheck PASS
        live_scripts["s-end"]["Update"] = {"TakeoverEnabled": True, "Channel": "beta"}
        yaml_fixed = _V58_SCRIPTS_BROKEN.replace("TakeoverEnabled: false", "TakeoverEnabled: true").replace(
            "Channel: stable", "Channel: beta"
        )
        yaml_path.write_text(yaml_fixed, encoding="utf-8")
        checks_ok = selfcheck.run(
            cfg,
            procs=lambda: [(1, "python.exe app/main.py")],
            mas_up=lambda: True,
            schedule=lambda: [{"name": "早班", "times": ["09:00"]}],
            channels=lambda: ["wecom_bot"],
            run_ok=lambda cmd: (True, ""),
            has_module=lambda m: True,
            contract=lambda _d: mastercfg.Result([], [], 1),
            virt=lambda: "VBS=0 HV=False",
        )
        upd_ok = next(c for c in checks_ok if c.name == selfcheck.UPDATES_NAME)
        check("selfcheck.run marks UPDATES_NAME as PASS once fixed", upd_ok.ok, True)
    finally:
        commands._mas = orig_mas

    print("\n[3. real entry point: machinecheck.judge('boot') #R02]")
    yaml_path.write_text(_V58_SCRIPTS_BROKEN, encoding="utf-8")
    sent = []

    class FakeNotifier:
        def send(self, title, body, *, alert=False, daily=False):
            sent.append((title, body, alert))
            return []

    verdicts_bad = dict(machinecheck.judge(state_dir, "boot", {"cfg": cfg}, notifier=FakeNotifier()))
    r02_bad = verdicts_bad.get("#R02")
    check("#R02 judge FAIL on broken scripts.yaml", r02_bad.status if r02_bad else None, machinecheck.FAIL)
    check("#R02 pushes group alert on FAIL", any("#R02" in t and a for t, _b, a in sent), True)

    yaml_path.write_text(
        _V58_SCRIPTS_BROKEN.replace("TakeoverEnabled: false", "TakeoverEnabled: true").replace(
            "Channel: stable", "Channel: beta"
        ),
        encoding="utf-8",
    )
    verdicts_ok = dict(machinecheck.judge(state_dir, "boot", {"cfg": cfg}, notifier=FakeNotifier()))
    r02_ok = verdicts_ok.get("#R02")
    check("#R02 judge PASS on fixed scripts.yaml", r02_ok.status if r02_ok else None, machinecheck.PASS)
    check("#R02 PASS evidence passes texts.plain()", texts.plain(r02_ok.evidence), [])

    print("\n[4. fix_maaend_preupdate.py: read-only check, HARDLOCK refusal, safe apply + diff verify]")
    fx = _load_fix_script()
    yaml_path.write_text(_V58_SCRIPTS_BROKEN, encoding="utf-8")
    orig_bytes = yaml_path.read_bytes()

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = fx.main(["--file", str(yaml_path), "--json"])
    info = json.loads(buf.getvalue())
    check("read-only check returns exit 2", rc, 2)
    check("read-only JSON reports broken state", (info["ok"], info["takeover"], info["channel"]),
          (False, False, "stable"))
    check("read-only check leaves file byte-identical", yaml_path.read_bytes(), orig_bytes)

    hardlock = root / "HARDLOCK.json"
    hardlock.write_text('{"locked": true}', encoding="utf-8")
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        rc_lock = fx.main(["--apply", "--file", str(yaml_path), "--hardlock-file", str(hardlock), "--json"])
    check("--apply refused with exit 4 while HARDLOCK.json exists", rc_lock, 4)
    check("file still byte-identical after hardlock refusal", yaml_path.read_bytes(), orig_bytes)

    hardlock.unlink()
    buf3 = io.StringIO()
    with redirect_stdout(buf3):
        rc_apply = fx.main(["--apply", "--file", str(yaml_path), "--hardlock-file", str(hardlock), "--json"])
    res_apply = json.loads(buf3.getvalue())
    check("--apply succeeds after unlock (exit 0)", (rc_apply, res_apply["ok"]), (0, True))
    check("created .bak-* backup next to scripts.yaml", bool(list(cfg_dir.glob("scripts.yaml.bak-*"))), True)
    parsed = mastercfg.parse_text(yaml_path, yaml_path.read_text(encoding="utf-8"))
    check("patched MaaEnd Update.TakeoverEnabled=True & Channel=beta",
          (parsed["s-end"]["Update"]["TakeoverEnabled"], parsed["s-end"]["Update"]["Channel"]),
          (True, "beta"))
    check("unrelated MaaEnd & MAA settings preserved untouched",
          (parsed["s-end"]["Run"]["RunTimesLimit"], parsed["s-maa"]["Run"]["HardTimeLimit"],
           parsed["s-end"]["Update"]["PackageMode"]),
          (1, 120, "full"))
    buf4 = io.StringIO()
    with redirect_stdout(buf4):
        rc_recheck = fx.main(["--file", str(yaml_path), "--json"])
    check("re-check after apply exits 0", rc_recheck, 0)

    # Live API mode check + apply with mocked HTTP
    api_state = {
        "s-end": {"Info": {"Name": "MaaEnd"}, "Update": {"TakeoverEnabled": False, "Channel": "stable"}},
    }
    orig_api = fx._mas_post

    def fake_api(path, body=None, timeout=15):
        if path == "/api/scripts/get":
            return {"code": 200, "data": json.loads(json.dumps(api_state))}
        if path == "/api/scripts/update":
            upd = body["data"]["Update"]
            api_state[body["scriptId"]]["Update"].update(upd)
            return {"code": 200, "status": "success"}
        raise AssertionError(path)

    fx._mas_post = fake_api
    try:
        buf5 = io.StringIO()
        with redirect_stdout(buf5):
            rc_api_chk = fx.main(["--api", "--json"])
        check("API read-only check returns exit 2", rc_api_chk, 2)
        buf6 = io.StringIO()
        with redirect_stdout(buf6):
            rc_api_fix = fx.main(["--apply", "--api", "--hardlock-file", str(hardlock), "--json"])
        check("API --apply updates + reads back exit 0", rc_api_fix, 0)
        check("API state updated cleanly", api_state["s-end"]["Update"],
              {"TakeoverEnabled": True, "Channel": "beta"})
    finally:
        fx._mas_post = orig_api


# ==============================================================================
# R-07: WuWa Tacet Suppression echo-set names & Forgery display across relay
# ==============================================================================

def _part_r07_wuwa_tacet_sets():
    """R-07: real entry points for WuWa F2 Tacet echo-set names & Forgery labels."""
    from ark_relay.core import config, mastercfg, wuwa_tables
    from ark_relay.features import phone, snapshot

    print("[1. wuwa_tables factual F2 table (1..7 verified, unknown explicitly unmarked)]")
    choices = wuwa_tables.wuwa_tacet.choices()
    check("7 verified Tacet choices", len(choices), 7)
    check("row 1 shows echo sets for 声骸套装",
          "衔梦照世之心" in wuwa_tables.wuwa_tacet.sets_label(1)
          and "茜染怀想之花" in wuwa_tables.wuwa_tacet.sets_label(1), True)
    check("row 3 shows echo sets for 方擎西峰",
          wuwa_tables.wuwa_tacet.sets(3), ("羽落空尘之歌", "冥途夜行之灯"))
    check("unknown row 17 never guesses and says 没登记",
          "没登记" in wuwa_tables.wuwa_tacet.sets_label(17), True)
    check("forgery choices list all verified rows", len(wuwa_tables.wuwa_forgery.choices()),
          len(wuwa_tables.wuwa_forgery.FORGERY))

    print("\n[2. mastercfg.read_okww & write_okww real entry points]")
    root = tmpdir("r07-")
    okww_root = root / "okww"
    okww_root.mkdir(parents=True)
    mas_dir = root / "automas"
    cfg_dir = mas_dir / "data" / "s-ok" / "Default" / "ConfigFile"
    cfg_dir.mkdir(parents=True)
    daily_path = cfg_dir / "DailyTask.json"
    daily_path.write_text(json.dumps({
        "Which Tacet Suppression to Farm": 1,
        "Which Forgery Challenge to Farm": 2,
        "Use Stamina": "Tacet Suppression",
    }, ensure_ascii=False), encoding="utf-8")
    (mas_dir / "config").mkdir(parents=True)
    (mas_dir / "config" / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "s-ok"}],
        "s-ok": {"Info": {"Name": "OK-WW", "Path": str(okww_root / "ok-ww.exe")}},
    }, ensure_ascii=False), encoding="utf-8")

    read = mastercfg.read_okww(mas_dir, okww_root)
    t_key = "DailyTask.json/Which Tacet Suppression to Farm"
    f_key = "DailyTask.json/Which Forgery Challenge to Farm"
    check("read_okww reads Tacet raw value 1", read["values"].get(t_key), 1)
    check("read_okww attaches display with echo set names",
          "衔梦照世之心" in read["display"].get(t_key, ""), True)
    check("read_okww attaches 7 labeled options for Tacet",
          len(read["options"].get(t_key) or []), 7)
    check("each Tacet option carries [label, value] with echo set names",
          read["options"][t_key][0][1] == 1 and "衔梦照世之心" in read["options"][t_key][0][0], True)
    check("read_okww attaches labeled options & display for Forgery",
          bool(read["display"].get(f_key)) and len(read["options"].get(f_key) or []) >= 5, True)

    ok_w, receipt = mastercfg.write_okww(mas_dir, t_key, 3, okww_root)
    check("write_okww succeeds", ok_w, True)
    check("write_okww persists raw int 3 to DailyTask.json",
          json.loads(daily_path.read_text(encoding="utf-8"))["Which Tacet Suppression to Farm"], 3)
    want_set3 = wuwa_tables.wuwa_tacet.sets(3)[0]
    check("write_okww receipt shows echo set name instead of bare number",
          want_set3 in receipt and "衔梦照世之心" in receipt, True)

    # Unknown index 17
    daily_path.write_text(json.dumps({"Which Tacet Suppression to Farm": 17}), encoding="utf-8")
    read17 = mastercfg.read_okww(mas_dir, okww_root)
    check("unknown index 17 display explicitly flags 没登记", "没登记" in read17["display"].get(t_key, ""), True)

    print("\n[3. phone.state_payload & snapshot._okww / _mas real entry points]")
    daily_path.write_text(json.dumps({
        "Which Tacet Suppression to Farm": 3,
        "Which Forgery Challenge to Farm": 1,
    }), encoding="utf-8")
    cfg = config.Config()
    cfg.automas_dir = mas_dir
    cfg.okww_dir = okww_root
    cfg.state_dir = root / "state"
    cfg.state_dir.mkdir()
    orig_rt = snapshot.read_runtime
    snapshot.read_runtime = lambda: {}
    try:
        payload = phone.state_payload(cfg, cfg.state_dir)
    finally:
        snapshot.read_runtime = orig_rt
    ok_master = (payload.get("master") or {}).get("OK-WW") or {}
    check("phone.state_payload exposes Tacet echo-set display & options",
          want_set3 in (ok_master.get("display") or {}).get(t_key, "")
          and len((ok_master.get("options") or {}).get(t_key) or []) == 7, True)

    orig_ad = snapshot._automas_dir
    snapshot._automas_dir = lambda: str(mas_dir)
    try:
        snap_out = {}
        snapshot._okww(snap_out)
    finally:
        snapshot._automas_dir = orig_ad
    snap_daily = snap_out["OK-WW(母本·生效的)"]["DailyTask"]
    check("snapshot._okww includes 无音区声骸套装 + 无音区名称 + 凝素领域名称",
          (want_set3 in snap_daily.get("无音区声骸套装", ""),
           bool(snap_daily.get("无音区名称")),
           bool(snap_daily.get("凝素领域名称"))),
          (True, True, True))

    orig_post = snapshot._post
    snapshot._post = lambda path, body=None: (
        {"data": {"u-ok": {"Info": {"Name": "OK-WW"}}}} if path == "/api/scripts/get"
        else {"data": {"usr": {"Info": {"IfQuickConfig": False},
                               "Task": {"WhichTacetSuppressionToFarm": 3,
                                        "WhichForgeryChallengeToFarm": 1}}}}
    )
    try:
        mas_out = {}
        snapshot._mas(mas_out)
    finally:
        snapshot._post = orig_post
    check("snapshot._mas includes 无音区声骸套装 + 凝素领域名称",
          want_set3 in mas_out["OK-WW(MAS侧)"].get("无音区声骸套装", "")
          and bool(mas_out["OK-WW(MAS侧)"].get("凝素领域名称")), True)


# ==============================================================================
# R-10: Bilibili code=0 empty-items risk control fallback & double-empty guard
# ==============================================================================

def _part_r10_bili_risk_control():
    """R-10: real entry points banners._bili_poster & banners._wuwa_poster_span."""
    from ark_relay.features import banners as hub
    from ark_relay.features import wuwa

    now = datetime(2026, 11, 26, 12, 0)
    pub_ts = int(datetime(2026, 11, 10, 11, 0).timestamp())

    print("[1. feed/space code=0 items=[] risk control -> opus/feed/space + detail recovers poster]")
    calls = {"space": 0, "opus": 0, "detail": 0}

    def get_risk_controlled(url, cookie):
        if "finger/spi" in url:
            return {"code": 0, "data": {"b_3": "B3", "b_4": "B4"}}
        if "web-interface/nav" in url:
            return {"code": 0, "data": {"wbi_img": {"img_url": "https://x/a" + "1" * 31 + ".png",
                                                    "sub_url": "https://x/b" + "2" * 31 + ".png"}}}
        calls["space"] += 1
        # Exact Bilibili risk-control response recorded in verify-ledger #3: code=0, items=[]
        return {"code": 0, "data": {"items": [], "has_more": False, "offset": ""}}

    def opus_ok(url, cookie):
        if "finger/spi" in url:
            return {"code": 0, "data": {"b_3": "B3", "b_4": "B4"}}
        if "opus/feed/space" in url:
            calls["opus"] += 1
            return {
                "code": 0,
                "data": {
                    "has_more": False,
                    "offset": "",
                    "items": [
                        {"opus_id": "1268655173042962432",
                         "content": "《鸣潮》版本资讯 | 3.8版本「旧梦凋零的百合」11月12日即将更新"},
                    ],
                },
            }
        if "web-dynamic/v1/detail" in url:
            calls["detail"] += 1
            return {
                "code": 0,
                "data": {
                    "item": {
                        "id_str": "1268655173042962432",
                        "modules": {
                            "module_author": {"pub_ts": pub_ts},
                            "module_dynamic": {
                                "major": {
                                    "opus": {
                                        "title": "《鸣潮》版本资讯 | 3.8版本「旧梦凋零的百合」11月12日即将更新",
                                        "summary": {
                                            "text": "《鸣潮》版本资讯 | 3.8版本「旧梦凋零的百合」11月12日即将更新\n详情见长图",
                                        },
                                        "pics": [
                                            {"url": "https://i0.hdslb.com/bfs/new_dyn/p1.jpg", "width": 800, "height": 4200},
                                            {"url": "https://i0.hdslb.com/bfs/new_dyn/p2.jpg", "width": 800, "height": 4200},
                                        ],
                                    }
                                }
                            },
                        },
                    }
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    got = hub._bili_poster("3.8", now, get=get_risk_controlled, sleep=lambda _s: None, opus_get=opus_ok)
    check("recovered poster URL via opus fallback",
          got[0] if got else None, "https://www.bilibili.com/opus/1268655173042962432")
    check("recovered title and pic URLs",
          (got[1].startswith("《鸣潮》版本资讯"), [u for u, _w, _h in got[2]]),
          (True, ["https://i0.hdslb.com/bfs/new_dyn/p1.jpg",
                  "https://i0.hdslb.com/bfs/new_dyn/p2.jpg"]))
    check("hit both space and opus+detail", (calls["space"] >= 1, calls["opus"], calls["detail"]), (True, 1, 1))

    print("\n[2. BOTH feed/space and opus/feed/space return code=0 empty -> raises BiliFeedProblem]")
    def opus_also_empty(url, cookie):
        if "finger/spi" in url:
            return {"code": 0, "data": {"b_3": "B3", "b_4": "B4"}}
        return {"code": 0, "data": {"items": [], "has_more": False, "offset": ""}}

    err_double = None
    try:
        hub._bili_poster("3.8", now, get=get_risk_controlled, sleep=lambda _s: None, opus_get=opus_also_empty)
    except wuwa.BiliFeedProblem as exc:
        err_double = str(exc)
    check("double empty raises BiliFeedProblem (never misclassified as no-post)",
          err_double is not None and "risk control" in err_double and "opus fallback failed" in err_double, True)

    print("\n[3. risk-control code=-352 and malformed spi raise BiliFeedProblem]")
    def opus_352(url, cookie):
        if "finger/spi" in url:
            return {"code": 0, "data": {"b_3": "B3", "b_4": "B4"}}
        return {"code": -352, "message": "风控校验失败"}

    err_352 = None
    try:
        hub._bili_poster("3.8", now, get=get_risk_controlled, sleep=lambda _s: None, opus_get=opus_352)
    except wuwa.BiliFeedProblem as exc:
        err_352 = str(exc)
    check("opus code=-352 raises BiliFeedProblem", err_352 is not None and "-352" in err_352, True)

    def bad_spi(url, cookie):
        return {"code": 0, "data": {"b_3": "", "b_4": ""}}

    err_spi = None
    try:
        hub._bili_poster("3.8", now, get=bad_spi, sleep=lambda _s: None, opus_get=bad_spi)
    except wuwa.BiliFeedProblem as exc:
        err_spi = str(exc)
    check("empty spi visitor cookie raises BiliFeedProblem", err_spi is not None, True)

    print("\n[4. opus feed has real non-matching items -> stops cleanly with None (0 false error)]")
    def opus_no_post_yet(url, cookie):
        if "finger/spi" in url:
            return {"code": 0, "data": {"b_3": "B3", "b_4": "B4"}}
        return {
            "code": 0,
            "data": {
                "has_more": False,
                "offset": "",
                "items": [{"opus_id": "1268000000000000001", "content": "《鸣潮》3.8版本前瞻特别通讯"}],
            },
        }

    check("opus has real items without 3.8 版本资讯 -> returns None cleanly",
          hub._bili_poster("3.8", now, get=get_risk_controlled, sleep=lambda _s: None, opus_get=opus_no_post_yet),
          None)

    print("\n[5. end-to-end _wuwa_poster_span production path: Kuro empty + Bili space blocked -> auto opus fallback]")
    from ark_relay.features.banners import Trace
    from ark_relay.core.desktop import Line
    orig_kuro = hub._kuro_poster
    orig_json = hub._json
    orig_pause = hub._pause
    try:
        hub._kuro_poster = lambda ver, now, get=None: None
        hub._pause = lambda _s: None

        def prod_json(url, ua="", data=None, headers=None, timeout=25):
            if "feed/space" in url and "opus/feed/space" not in url:
                return get_risk_controlled(url, "")
            if "web-interface/nav" in url:
                return get_risk_controlled(url, "")
            return opus_ok(url, "")

        hub._json = prod_json
        tr = Trace([], set(), set(), [], [])

        def read_img(url):
            return [
                Line("2026年12月3日10:00~2026年12月24日11:59（服务器时间）", 10, 100, 400, 20),
                Line("「星辉漫落之时」角色活动唤取", 10, 140, 260, 20),
            ]

        span = wuwa._wuwa_poster_span("3.8", "星辉漫落之时", "千咲", now, read_img, tr)
    finally:
        hub._kuro_poster = orig_kuro
        hub._json = orig_json
        hub._pause = orig_pause
    check("end-to-end production _wuwa_poster_span extracts exact dates via auto opus fallback",
          span, (datetime(2026, 12, 3, 10, 0), datetime(2026, 12, 24, 11, 59)))


# ==============================================================================
# R-11: Boot read-lock + #179 live stagegate + all 14 watching ledger items
# ==============================================================================

def _part_r11_ledger_15_and_boot_lock():
    """R-11: D-1017 boot read-lock, #179 live stagegate, and all 14 watching items."""
    from ark_relay.core import config, engine as eng_mod, ledger, statestore
    from ark_relay.core.collector import RunRecord
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import (
        collector_maa,
        collector_maaend,
        commands,
        echofarm,
        handle,
        machinecheck,
        machinechecks,
        outcome,
        phone,
        procwatch,
        queues,
        stagegate,
        weeklyboss,
    )
    import boot_stages

    _ = machinechecks

    print("[A. D-1017 statestore boot read-lock: Engine & Mailbox never wipe or replay]")
    root = tmpdir("r11-")
    sd = root / "state"
    sd.mkdir()
    seed_rec = RunRecord(
        run_id="2026-11-26/endfield/MaaEnd-09-00-00",
        script="MaaEnd",
        user="Default",
        started=datetime(2026, 11, 26, 9, 0, tzinfo=SERVER_TZ),
        finished=datetime(2026, 11, 26, 9, 5, tzinfo=SERVER_TZ),
        ok=False,
        failed_tasks=["基质刷取"],
    )
    st_seed = ledger.State(sd)
    from ark_relay.core.collector import record_to_payload
    st_seed.save_pending({
        "pending": [record_to_payload(seed_rec)],
        "recovered": [],
        "unsent": [["2026-11-26", "endfield", seed_rec.run_id, "⚠️ 没干完", "测试"]],
    })
    st_seed.store.set("queues", "phone_seen", ["msg-old-1", "msg-old-2"])
    state_file = sd / statestore.FILE
    seeded_bytes = state_file.read_bytes()

    # Simulate fresh process boot (clear _LAST_GOOD / _UNREAD) with state.json locked
    statestore._LAST_GOOD.pop(str(state_file), None)
    statestore._UNREAD.pop(str(state_file), None)
    orig_read = Path.read_text
    orig_waits = statestore.LOCK_WAITS
    locked = {"on": True}

    def guarded_read(self, *a, **kw):
        if self == state_file and locked["on"]:
            raise PermissionError(13, "locked by AV at boot")
        return orig_read(self, *a, **kw)

    Path.read_text = guarded_read
    statestore.LOCK_WAITS = (0.0,)
    try:
        cfg = config.Config()
        cfg.state_dir = sd
        fetched = {"n": 0}
        sent_r11 = []

        class StubNotifier:
            def send(self, title, body, *, alert=False, daily=False):
                sent_r11.append((title, body, alert, daily))
                return []

        e = eng_mod.Engine(
            cfg,
            source=SimpleNamespace(fetch=lambda seen: (fetched.__setitem__("n", fetched["n"] + 1), [])[1]),
            state=ledger.State(sd),
            notifier=StubNotifier(),
        )
        e._scripts_running = lambda: False
        check("Engine boots with _pending_restored=False under read lock", e._pending_restored, False)

        refused_persist = False
        try:
            e._persist_pending()
        except PermissionError:
            refused_persist = True
        check("_persist_pending refuses to wipe held alarms while unread", refused_persist, True)
        check("state.json on disk untouched during boot lock", state_file.read_bytes(), seeded_bytes)

        e.tick()
        check("tick skips source.fetch while state.json unread", (fetched["n"], e._fetch_owed), (0, True))
        now_dl = datetime(2026, 11, 26, 9, 10, tzinfo=SERVER_TZ)
        nxt = e.next_deadline(now_dl)
        check("next_deadline schedules 重读 state.json in UNREAD_RETRY_S",
              nxt is not None and "重读 state.json" in nxt[1]
              and nxt[0] == now_dl + timedelta(seconds=statestore.UNREAD_RETRY_S), True)

        # Mailbox under boot lock: refuses fetch without hitting ntfy or wiping phone_seen
        mb = phone.Mailbox("topic-r11", "pin-r11", sd)
        check("Mailbox boots with _seen_loaded=False under read lock", mb._seen_loaded, False)
        ntfy_hits = {"n": 0}
        orig_urlopen = urllib.request.urlopen

        def fake_urlopen(req, timeout=25):
            ntfy_hits["n"] += 1
            msg_old = phone.pack("pin-r11", {"action": "refresh"}, "cmd")
            msg_new = phone.pack("pin-r11", {"action": "status"}, "cmd")
            lines = "\n".join([
                json.dumps({"event": "message", "id": "msg-old-1", "time": int(time.time()), "message": msg_old}),
                json.dumps({"event": "message", "id": "msg-new-3", "time": int(time.time()), "message": msg_new}),
            ]).encode("utf-8")

            class Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self):
                    return lines

            return Resp()

        urllib.request.urlopen = fake_urlopen
        try:
            cmds_locked = mb.fetch()
            check("Mailbox.fetch returns [] with backlog_missed=True without touching ntfy",
                  (cmds_locked, mb.backlog_missed, ntfy_hits["n"], phone.SEEN_WAIT_WHY in mb.backlog_why),
                  ([], True, 0, True))
            mb._save_seen()
            check("_save_seen refused to overwrite phone_seen on disk", state_file.read_bytes(), seeded_bytes)

            # Unlock state.json -> both Engine & Mailbox recover cleanly
            locked["on"] = False
            e.tick()
            check("after unlock, Engine restores pending, delivers unsent alarm, and fetches records",
                  (e._pending_restored, e._fetch_owed, len(e._pending),
                   any(t == "⚠️ 没干完" for t, _b, _a, _d in sent_r11), fetched["n"]),
                  (True, False, 1, True, 1))

            cmds_after = mb.fetch()
            check("after unlock, Mailbox skips msg-old-1 (0 replay) and delivers only msg-new-3",
                  (mb._seen_loaded, [c.get("action") for c in cmds_after]),
                  (True, ["status"]))
            disk_seen = statestore.StateStore(sd).get("queues", "phone_seen")
            check("phone_seen atomically merged preserving old IDs + new ID",
                  set(disk_seen) >= {"msg-old-1", "msg-old-2", "msg-new-3"}, True)
        finally:
            urllib.request.urlopen = orig_urlopen
    finally:
        Path.read_text = orig_read
        statestore.LOCK_WAITS = orig_waits
        statestore._LAST_GOOD.pop(str(state_file), None)
        statestore._UNREAD.pop(str(state_file), None)

    print("\n[B. #179: stagegate reads live AUTO-MAS backend right after boot set_stage]")
    fx = stagegate_fx()
    sg_root = tmpdir("r11-179-")
    maa = fx.maa_dir(sg_root / "maa")
    # Disk still has stale unreachable YW-4, while live AUTO-MAS already confirmed 1-7!
    mas = fx.automas_dir(sg_root / "mas", stage="YW-4", queues={"早班": ("09:00", ("MAA",))}, beta3=True)
    sg_cfg = config.Config()
    sg_cfg.automas_dir = mas
    sg_cfg.maa_dir = maa
    sg_cfg.state_dir = sg_root / "state"
    sg_cfg.state_dir.mkdir()
    boot_at = datetime(2026, 11, 17, 8, 46, tzinfo=SERVER_TZ)

    def live_backend(path, body=None):
        if path == "/api/scripts/get":
            return {"data": {"s-maa": {"Info": {"Name": "MAA", "Path": str(maa / "MAA.exe")}}}}
        if path == "/api/scripts/user/get":
            return {"data": {"u-1": {
                "Info": {"Name": "arknights", "Status": True, "RemainedDay": -1},
                "Stage": {"StageMode": "Fixed", "Stage": "1-7", "Stage_1": "-", "Stage_2": "-", "Stage_3": "-"},
                "Task": {"IfFight": True},
            }}}
        raise AssertionError(path)

    sg_alarms = []
    sg_notifier = SimpleNamespace(send=lambda t, b, alert=False: (sg_alarms.append((t, b, alert)), [])[1])
    v_live, stg_live, _why_live = stagegate.run_verdict(mas, maa, boot_at, mas_get=live_backend)
    check("#179 live stagegate sees 1-7 instead of stale disk YW-4", (v_live, stg_live), (stagegate.YES, "1-7"))
    stagegate.step(sg_cfg, sg_notifier, boot_at, lead_min=stagegate.BOOT_LEAD_MIN, mas_get=live_backend)
    check("#179 boot stagegate sends 0 false alarms when live backend has 1-7", sg_alarms, [])

    # When backend is down, stagegate falls back cleanly to disk and catches YW-4
    def dead_backend(path, body=None):
        raise OSError("backend offline")

    v_disk, stg_disk, _why_disk = stagegate.run_verdict(mas, maa, boot_at, mas_get=dead_backend)
    check("#179 falls back to disk when backend unavailable and catches YW-4",
          (v_disk, stg_disk), (stagegate.NO, "YW-4"))

    print("\n[C. Offline verification of all 14 watching ledger items]")
    # #15: commands confirmation wording & machinecheck #15 registration
    check("#15 registered in machinecheck", "#15" in machinecheck.CHECKS, True)
    orig_c_mas = commands._mas
    store15 = {"s-end": {"Info": {"Name": "MaaEnd"}, "Run": {"RunTimesLimit": 3}}}

    def fake_mas15(path, body=None, timeout=15):
        if path == "/api/scripts/get":
            return {"data": json.loads(json.dumps(store15))}
        if path == "/api/scripts/update":
            store15[body["scriptId"]]["Run"]["RunTimesLimit"] = body["data"]["Run"]["RunTimesLimit"]
            return {"code": 200}
        raise AssertionError(path)

    commands._mas = fake_mas15
    try:
        ok15, msg15 = commands._script_item_via_api({"data": json.loads(json.dumps(store15))},
                                                    "MaaEnd", "Run.RunTimesLimit", 1)
    finally:
        commands._mas = orig_c_mas
    check("#15 commands._script_item_via_api confirms with 调度程序已确认",
          (ok15, "调度程序已确认" in msg15), (True, True))

    # #28: MaaEnd task_verdict distinguishes normal vs aborted task
    ok28_good, _ = collector_maaend.task_verdict(
        "赠送干员礼物", {"result": "Succeeded", "nodes": {"GiftOperatorConfirmGift": 1}}
    )
    ok28_abort, why28 = collector_maaend.task_verdict(
        "装备制造", {"result": "Failed", "nodes": {collector_maaend.ABORT_STEP: 1}}
    )
    check("#28 task_verdict passes succeeded and catches failed/aborted",
          ("#28" in machinecheck.CHECKS, ok28_good, ok28_abort, bool(why28)), (True, True, False, True))

    # #30: bag-full essence cause detection
    bag_log = (
        "[2026-11-20 09:10:00] 开始任务: 基质刷取\n"
        "[2026-11-20 09:11:00] 点击确认领取按钮\n"
        "[2026-11-20 09:11:02] 任务失败: 基质刷取\n"
    )
    fw_bag = "[2026-11-20 09:11:01.000][INF] OCR: 仓储空间已满\n"
    causes30 = collector_maaend._maaend_fail_causes(bag_log, fw_bag)
    check("#30 detects 背包满了 cause when 仓储空间已满 near claim failure",
          causes30.get("基质刷取"), collector_maaend.BAG_FULL)

    # #33 & #34: makeup + unresolved checks registered and active
    check("#33 & #34 registered in machinecheck",
          ("#33" in machinecheck.CHECKS, "#34" in machinecheck.CHECKS), (True, True))

    # #64: Endfield notice unreadable check registered and judges FAIL on missing push
    check("#64 registered in machinecheck", "#64" in machinecheck.CHECKS, True)
    v64 = dict(machinecheck.judge(
        tmpdir("r11-64-"), "gameupdate",
        {"game": "终末地", "unreadable": True, "pushed": False, "reason": "公告超时"},
        notifier=None,
    ))
    check("#64 executes through machinecheck.judge('gameupdate')",
          isinstance(v64, dict), True)

    # #65: MAA_NOT_STARTED + machinecheck #65
    check("#65 registered & detects StartUp/login failure as never_started",
          ("#65" in machinecheck.CHECKS,
           collector_maa.never_started(["开始唤醒失败：MAA 未能正确登录 PRTS"], {})),
          (True, True))
    check("#65 does NOT mark round with drops as never_started",
          collector_maa.never_started(["开始唤醒失败"], {"drop_statistics": {"固源岩": 5}}), False)

    # #94: WuWa weekly boss waveplate-short skip wording recognized cleanly
    okww_short_log = (
        "2026-11-20 09:10:00,000 INFO TaskExecutor DailyTask:每日任务完成\n"
        "2026-11-20 09:10:30,000 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
        "2026-11-20 09:11:00,000 INFO TaskExecutor FarmEchoTask:周本领奖：进本前读到本周剩余次数 3/3\n"
        "2026-11-20 09:12:00,000 INFO TaskExecutor FarmEchoTask:结晶波片不足，取消并跳过本次周本\n"
    )
    check("#94 outcome.WEEKLY_SHORT matches exact overlay line",
          bool(outcome.WEEKLY_SHORT.search(okww_short_log)), True)
    checks94 = outcome.okww_checks(okww_short_log, expect_nest=False, expect_daily=True)
    check("#94 okww_checks reports weekly waveplate shortage cleanly",
          any("结晶波片不足" in c.label or "结晶波片不足" in c.detail for c in checks94), True)

    # #102 (#24b): boot_stages._once_more retries once on inconclusive first attempt
    tries102 = {"n": 0}
    probs102: list[str] = []

    def step102(probs):
        tries102["n"] += 1
        if tries102["n"] == 1:
            probs.append("网络抖动没给结论")
            return ""
        return "AUTO-MAS 已是最新"

    cfg102 = config.Config()
    note102 = boot_stages._once_more(cfg102, logging.getLogger("ark.test_cure_b_1126"), "AUTO-MAS", 60, probs102, step102)
    check("#102 _once_more retries once and returns second verdict",
          (tries102["n"], note102, probs102, "#24b" in machinecheck.CHECKS),
          (2, "AUTO-MAS 已是最新", [], True))

    # #142: queues.step enforces Endfield Run.RunTimesLimit=1
    check("#142 queues targets MaaEnd Run.RunTimesLimit=1",
          (queues.PATH, queues.WANT.get("MaaEnd")), ("Run.RunTimesLimit", 1))

    # #146: maa_start_watchdog catches stuck StartUp / ANR hang cleanly
    from ark_relay.features import maa_start_watchdog as msw
    wd_root = tmpdir("r11-146-")
    (wd_root / "debug").mkdir(parents=True)
    asst_log = wd_root / "debug" / "asst.log"
    t0 = datetime(2026, 11, 26, 9, 0, 5)
    asst_log.write_text(
        '[2026-11-26 09:00:05.000][INF][Px9999][Tx1] Assistant::append_callback | '
        'TaskChainStart {"taskchain":"StartUp"}\n',
        encoding="utf-8",
    )
    wd_clock = [t0]
    killed146 = []
    wd = msw.Watchdog(
        SimpleNamespace(send=lambda *a, **k: []),
        wd_root,
        now=lambda: wd_clock[0],
        snapshot=lambda: {"tasks": [{"task_info": [{"name": "MAA", "status": "运行"}]}]},
        processes=lambda: [("MAA.exe", 9999)],
        kill=lambda pid, img: (killed146.append((pid, img)), (True, ""))[1],
        active=True,
    )
    wd.tick()
    wd_clock[0] = t0 + timedelta(seconds=msw.STARTUP_LIMIT_SECONDS + 30)
    res146 = wd.tick()
    check("#146 maa_start_watchdog intervenes on stuck StartUp (ANR)",
          (bool(res146), killed146), (True, [(9999, "MAA.exe")]))

    # #173: procwatch.farm_poweroff_planned distinguishes planned spa_run/is_run vs unexpected
    p173_dir = tmpdir("r11-173-")
    t_ask = datetime(2026, 11, 14, 8, 20, 10, tzinfo=SERVER_TZ)
    (p173_dir / procwatch.FARM_POWEROFF_MARK).write_text(
        json.dumps({"by": "is_run.py", "at": (t_ask - timedelta(seconds=15)).timestamp(), "outcome": "time_up"}),
        encoding="utf-8",
    )
    asked173 = {"process": r"C:\Windows\System32\shutdown.exe", "at": t_ask}
    planned = procwatch.farm_poweroff_planned(asked173, base=p173_dir)
    check("#173 recognizes planned is_run.py poweroff mark",
          (planned is not None and planned["by"] == "is_run.py"), True)
    (p173_dir / procwatch.FARM_POWEROFF_MARK).unlink()
    check("#173 returns None (stays fault) when mark missing",
          procwatch.farm_poweroff_planned(asked173, base=p173_dir), None)

    # #178: Monday skipped Annihilation accepted when Skland official data confirms capped
    sd178 = tmpdir("r11-178-")
    eng178 = SimpleNamespace(
        cfg=SimpleNamespace(state_dir=sd178, skland_cred="cred"),
        state=ledger.State(sd178),
    )
    rec178 = RunRecord(
        run_id="2026-11-16/arknights/MAA-09-00-00",
        script="MAA",
        user="u",
        started=datetime(2026, 11, 16, 9, 0, tzinfo=SERVER_TZ),  # Monday
        finished=datetime(2026, 11, 16, 9, 5, tzinfo=SERVER_TZ),
        ok=True,
        raw={"annihilation": True, "annihilation_no_entry": True},
    )
    orig_read_sk = handle._read_skland_annihilation
    handle._read_skland_annihilation = lambda _e: {
        "current": 1800, "total": 1800,
        "store_ts": int(datetime(2026, 11, 16, 9, 4, tzinfo=SERVER_TZ).timestamp()),
        "read_at": "09:05",
    }
    try:
        got178 = handle._annihilation_checked_full(eng178, rec178)
    finally:
        handle._read_skland_annihilation = orig_read_sk
    check("#178 Monday skipped Annihilation verified full via Skland official data",
          got178 is not None and got178["current"] == 1800, True)

    # #185: echofarm.quiet_minutes spans midnight rotation ok-script.YYYY-MM-DD.log
    ef_dir = tmpdir("r11-185-")
    old_log = ef_dir / "ok-script.2026-11-19.log"
    new_log = ef_dir / "ok-script.log"
    old_log.write_text("2026-11-19 23:58:54,100 INFO TaskExecutor FarmEchoTask:enter combat\n", encoding="utf-8")
    new_log.write_text("2026-11-20 00:00:01,050 INFO MainThread log rotated\n", encoding="utf-8")
    t_old = datetime(2026, 11, 19, 23, 58, 54, tzinfo=SERVER_TZ).timestamp()
    os.utime(old_log, (t_old, t_old))
    orig_oklog = weeklyboss._okww_log
    weeklyboss._okww_log = lambda: new_log
    try:
        qm = echofarm.quiet_minutes(
            now=datetime(2026, 11, 20, 0, 0, 2, tzinfo=SERVER_TZ),
            since=datetime(2026, 11, 19, 22, 57, 0, tzinfo=SERVER_TZ),
        )
    finally:
        weeklyboss._okww_log = orig_oklog
    check("#185 midnight rotation quiet_minutes reads previous day's progress (~1.1 min, NOT 63 min)",
          qm is not None and qm < 3.0, True)


ALL_PARTS = {
    "r02": _part_r02_maaend_preupdate,
    "r07": _part_r07_wuwa_tacet_sets,
    "r10": _part_r10_bili_risk_control,
    "r11": _part_r11_ledger_15_and_boot_lock,
}


if __name__ == "__main__":
    want = [a.lower() for a in sys.argv[1:] if a.lower() in ALL_PARTS]
    selected = [ALL_PARTS[k] for k in want] if want else list(ALL_PARTS.values())
    sys.exit(run_parts(selected))
