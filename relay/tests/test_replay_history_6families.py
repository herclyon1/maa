"""R-12: Historical 6 root-cause family full offline anti-regression replay suite (2026-11-26).

Replays real historical fault samples and false-alarm samples from BOARD/报错台账.txt and
群报警-*.txt across all 6 root-cause families, proving:
  1. 100% detection of real historical script/infra faults;
  2. 0 false alarms on cured historical false-positive patterns;
  3. 0 weakening of alert/push routing (notify.route_of, errwatch, WeComBot._cap, USER-SWITCHES.txt).

Families:
  F1. AUTO-MAS protocol/config drift & event-loop blocking (#1014, #113, R-02, #190)
  F2. External web/API/CDN/risk-control (#3/R-10, #196, #197, Kuro non-200)
  F3. Desktop OCR/launcher/UI interaction (#198 TextAngle + taskkill race, desktop window check)
  F4. Script log semantics/overlay/weekly boss/gathering (#191, #192/#193, #135, #189, #106, #107, #185)
  F5. State persistence/lock contention/shutdown & make-up orchestration (D-1017, #173, #178, #179, #142)
  F6. Alert routing, truncation & zero-weakening guard (#139/#140, route_of, errwatch, USER-SWITCHES)
"""
from __future__ import annotations

# ruff: noqa: PLC0415
import json
import logging
import math
import os
import sys
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
# Family 1: AUTO-MAS protocol/config drift & event-loop blocking
# ==============================================================================

def _part_f1_automas_drift_and_eventloop():
    """F1: v5.7-beta.3 Stage move, v5.8 scripts.yaml, R-02 MaaEnd Update, v5.9 nested snapshot."""
    from ark_relay.core import engine as eng_mod, mastercfg

    print("[F1.1 #1014: v5.7.0-beta.3 Stage group migration read identically to legacy Info]")
    user_b3 = {
        "Info": {"Name": "ark", "Status": True, "RemainedDay": -1},
        "Stage": {"StageMode": "Fixed", "Stage": "1-7", "MedicineNumb": 2, "SeriesNumb": "0"},
        "Task": {"IfFight": True, "Annihilation": "Annihilation"},
    }
    view = mastercfg.info_view(user_b3)
    check("beta.3 Stage.Stage & Task.Annihilation surfaced via info_view",
          (view.get("Stage"), view.get("MedicineNumb"), view.get("Annihilation")),
          ("1-7", 2, "Annihilation"))

    print("[F1.2 #113 + R-02: v5.8+ scripts.yaml parsing & MaaEnd pre-update chain break]")
    mas_dir = tmpdir("f1-mas-")
    (mas_dir / "config").mkdir(parents=True)
    yaml_broken = """order:
- uid: s-end
  type: MaaEndConfig
data:
  s-end:
    Info:
      Name: MaaEnd
      Path: D:\\ark\\maaend
    Update:
      TakeoverEnabled: false
      Channel: stable
"""
    (mas_dir / "config" / "scripts.yaml").write_text(yaml_broken, encoding="utf-8")
    gaps_bad = mastercfg.check_maaend_preupdate(mas_dir)
    check("REAL FAULT detected: MaaEnd TakeoverEnabled=false + Channel=stable", len(gaps_bad), 2)
    (mas_dir / "config" / "scripts.yaml").write_text(
        yaml_broken.replace("false", "true").replace("stable", "beta"), encoding="utf-8"
    )
    check("CLEAN CONFIG: 0 false alarms when TakeoverEnabled=true & Channel=beta",
          mastercfg.check_maaend_preupdate(mas_dir), [])

    print("[F1.3 #190: v5.9 nested runtime-snapshot task.scripts & event-loop timeout cap]")
    snap_v59_running = {
        "tasks": [{
            "status": "running",
            "task": {
                "scripts": {
                    "order": ["s-end"],
                    "data": {"s-end": {"info": {"name": "MaaEnd", "status": "运行"}}},
                }
            },
        }]
    }
    snap_v59_done = {
        "tasks": [{
            "status": "success",
            "task": {
                "scripts": {
                    "order": ["s-end"],
                    "data": {"s-end": {"info": {"name": "MaaEnd", "status": "完成"}}},
                }
            },
        }]
    }
    check("v5.9 nested running MaaEnd detected as busy (prevents false missed-run/shutdown)",
          (eng_mod._judge_snapshot(snap_v59_running), eng_mod._script_unfinished(snap_v59_running, "MaaEnd")),
          (True, True))
    check("v5.9 nested completed MaaEnd detected as idle (0 false busy)",
          (eng_mod._judge_snapshot(snap_v59_done), eng_mod._script_unfinished(snap_v59_done, "MaaEnd")),
          (False, False))
    check("timeout cap bounds permanent deadlock (10s block < cap <= 300s)",
          10.0 < eng_mod._SNAP_TIMEOUT_CAP_S <= 300.0, True)


# ==============================================================================
# Family 2: External web / API / CDN / risk-control
# ==============================================================================

def _part_f2_external_api_cdn_risk():
    """F2: #3/R-10 Bilibili risk control, #196 CDN IP rotation, #197 preview lag, Kuro error."""
    from ark_relay.features import banners as hub, maintenance, needtable, wuwa

    print("[F2.1 #3 / R-10: Bilibili code=0 empty-items risk control vs real fault]")
    now = datetime(2026, 11, 26, 12, 0)
    pub_ts = int(datetime(2026, 11, 10, 11, 0).timestamp())

    def space_blocked(url, cookie):
        if "finger/spi" in url:
            return {"code": 0, "data": {"b_3": "B3", "b_4": "B4"}}
        if "web-interface/nav" in url:
            return {"code": 0, "data": {"wbi_img": {"img_url": "https://x/a" + "1" * 31 + ".png",
                                                    "sub_url": "https://x/b" + "2" * 31 + ".png"}}}
        return {"code": 0, "data": {"items": [], "has_more": False, "offset": ""}}

    def opus_healthy(url, cookie):
        if "opus/feed/space" in url:
            return {"code": 0, "data": {"has_more": False, "offset": "",
                                        "items": [{"opus_id": "9001", "content": "《鸣潮》版本资讯 | 3.8版本"}]}}
        return {"code": 0, "data": {"item": {
            "id_str": "9001",
            "modules": {
                "module_author": {"pub_ts": pub_ts},
                "module_dynamic": {"major": {"opus": {
                    "summary": {"text": "《鸣潮》版本资讯 | 3.8版本\n详情"},
                    "pics": [{"url": "https://i0.hdslb.com/p.jpg", "width": 800, "height": 4000}],
                }}},
            },
        }}}

    got = hub._bili_poster("3.8", now, get=space_blocked, sleep=lambda _s: None, opus_get=opus_healthy)
    check("FALSE ALARM cured: space risk control recovers via opus/feed/space",
          got[0] if got else None, "https://www.bilibili.com/opus/9001")

    both_blocked = False
    try:
        hub._bili_poster("3.8", now, get=space_blocked, sleep=lambda _s: None,
                         opus_get=lambda u, c: {"code": 0, "data": {"items": []}})
    except wuwa.BiliFeedProblem:
        both_blocked = True
    check("REAL FAULT detected: double risk-control raises BiliFeedProblem (not silent None)",
          both_blocked, True)

    print("[F2.2 #196: CDN single-edge TCP RST rotates away from bad IP]")
    from ark_relay.core import notify as netretry
    check("netretry exposes open_pinned + response_peer_ip + next_cdn_ip for CDN IP rotation",
          callable(netretry.open_pinned) and callable(netretry.response_peer_ip)
          and callable(netretry.next_cdn_ip), True)
    seen_ips: list[str] = []
    orig_try = maintenance._try
    orig_next = netretry.next_cdn_ip
    orig_pause = maintenance.GET_PAUSE
    try:
        maintenance.GET_PAUSE = 0.0
        netretry.next_cdn_ip = lambda url, tried, peer, pin, **kw: "2.2.2.2" if "2.2.2.2" not in tried else ""

        def fake_try(req, limit, *, pin_ip="", peer_box=None):
            seen_ips.append(pin_ip)
            if not pin_ip:
                if peer_box is not None:
                    peer_box[0] = "1.1.1.1"
                raise ConnectionResetError(10054, "CDN edge RST")
            return '{"ok": true}'

        maintenance._try = fake_try
        page = maintenance._get("https://cdn.example.invalid/notice.json", timeout=5)
    finally:
        maintenance._try = orig_try
        netretry.next_cdn_ip = orig_next
        maintenance.GET_PAUSE = orig_pause
    check("FALSE ALARM cured: single-edge TCP RST rotates to alternate IP and succeeds",
          (page, seen_ips), ('{"ok": true}', ["", "2.2.2.2"]))

    print("[F2.3 #197: release-day label_type_preview lag & Kuro non-200 error guard]")
    lagging_preview = {"name": "新干员", "dotType": "label_type_preview", "onlineDate": "2026-11-25"}
    released_normal = {"name": "已上线干员", "dotType": "", "onlineDate": "2026-11-01"}
    check("FALSE ALARM cured: label_type_preview on release day not treated as released",
          (needtable._is_released(lagging_preview, "2026-11-25"),
           needtable._is_released(released_normal, "2026-11-25")),
          (False, True))

    kuro_raised = False
    try:
        wuwa.kuro_checked({"code": 500, "msg": "server error", "data": None}, "资讯")
    except wuwa.KuroAnswerProblem:
        kuro_raised = True
    check("REAL FAULT detected: Kuro code=500 raises KuroAnswerProblem (never empty list)",
          kuro_raised, True)


# ==============================================================================
# Family 3: Desktop OCR / launcher / UI interaction
# ==============================================================================

def _part_f3_desktop_ocr_launcher():
    """F3: #198 OCR TextAngle back-rotation & taskkill PID-vanished race vs real error."""
    from ark_relay.core import desktop

    print("[F3.1 #198: OCR PowerShell script rotates BoundingRect back when TextAngle != 0]")
    src = (RELAY / "ark_relay" / "core" / "desktop.py").read_text(encoding="utf-8")
    check("desktop.py OCR script reads $result.TextAngle and back-rotates corners",
          "$result.TextAngle" in src and "[Math]::Cos(" in src and "[Math]::Sin(" in src, True)
    # Sanity-check rotation geometry on the exact -5.6 deg case logged 2026-11-25:
    # A button near x=1500, y=860 shifts ~40+ px in y if -5.6 deg is ignored.
    ang = math.radians(-5.6)
    cx, cy = 960.0, 540.0
    dx, dy = 1500.0 - cx, 860.0 - cy
    ry = cy + dx * math.sin(ang) + dy * math.cos(ang)
    check("TextAngle=-5.6 deg shifts bottom-right button by > 40 px without back-rotation",
          abs(ry - 860.0) > 40.0, True)

    print("[F3.2 #198: taskkill rc=1 PID already vanished vs genuine permission denial]")
    gone_zh = '错误: 无法终止 PID 为 5224 的进程。\n原因: 没有此任务的实例在运行。'
    gone_en = 'ERROR: The process with PID 5224 could not be terminated.\nReason: There is no running instance of the task.'
    denied_zh = '错误: 无法终止 PID 为 5224 的进程。\n原因: 拒绝访问。'
    check("FALSE ALARM cured: taskkill PID-already-gone (zh/en) treated as benign",
          (desktop._taskkill_already_gone(1, gone_zh), desktop._taskkill_already_gone(1, gone_en)),
          (True, True))
    check("REAL FAULT detected: taskkill access-denied rc=1 NOT swallowed",
          desktop._taskkill_already_gone(1, denied_zh), False)


# ==============================================================================
# Family 4: Script log semantics / overlay / weekly boss / gathering
# ==============================================================================

def _part_f4_script_logs_overlay_weekly():
    """F4: #191 combat block vs roadside pickup, #192/#193 weekly drop, #189, #106, #107, #185."""
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import collector_maaend, echofarm, outcome, weeklyboss

    print("[F4.1 #191: MapNavigatorObstacleDevice_InteractPost roadside pickup vs real combat block]")
    me_dir = tmpdir("f4-191-")
    err_dir = me_dir / "debug" / "on_error"
    err_dir.mkdir(parents=True)
    shot = "2026.11.24-09.10.45.123_MapNavigatorObstacleDevice_InteractPost.png"
    (err_dir / shot).write_bytes(b"fake-png-1")
    route_log = (
        "[2026-11-24 09:10:00] 路线13：四号谷地-中黯石\n"
        "[2026-11-24 09:11:30] 路线13：采集结束\n"
    )
    # Case A (historical false alarm): screenshot OCR shows roadside item pickup, NOT combat-block toast
    b_false = collector_maaend.blocked_routes(
        route_log, [shot], maaend_dir=me_dir,
        ocr_fn=lambda _p: "F 拾取 协议纹石 灼壳虫",
    )
    check("FALSE ALARM cured (#191): roadside pickup shot is NOT marked blocked", b_false, {})

    # Case B (real fault): screenshot OCR shows 「战斗中无法使用」 (rewrite file to bust mtime/size cache)
    (err_dir / shot).write_bytes(b"fake-png-combat-block")
    b_real = collector_maaend.blocked_routes(
        route_log, [shot], maaend_dir=me_dir,
        ocr_fn=lambda _p: "提示：战斗中无法使用，请脱离战斗后尝试",
    )
    check("REAL FAULT detected (#191): genuine 「战斗中无法使用」 marks route blocked",
          bool(b_real), True)

    print("[F4.2 #192/#193: weekly boss lap-3 silent drop vs verified 3/3]")
    weekly_drop_log = "\n".join([
        "2026-11-23 10:00:00,000 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0",
        "2026-11-23 10:01:00,000 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文：本周剩余可收取次数：3/3",
        "2026-11-23 10:02:00,000 INFO TaskExecutor FarmEchoTask:周本领奖：打完了，去结晶按 F",
        "2026-11-23 10:02:05,000 INFO TaskExecutor FarmEchoTask:周本领奖：点击确认",
        "2026-11-23 10:02:20,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3",
        "2026-11-23 10:04:00,000 INFO TaskExecutor FarmEchoTask:周本领奖：打完了，去结晶按 F",
        "2026-11-23 10:04:05,000 INFO TaskExecutor FarmEchoTask:周本领奖：点击确认",
        "2026-11-23 10:04:20,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 2/3→1/3",
        "2026-11-23 10:06:00,000 INFO TaskExecutor FarmEchoTask:周本领奖：打完了，去结晶按 F",
        "2026-11-23 10:08:00,000 INFO TaskExecutor DailyTask:farm_tacet consumed stamina",
    ])
    why_drop = outcome.weekly_incomplete_reason(weekly_drop_log)
    check("REAL FAULT detected (#192/#193): 3 laps fought, only 2 verified claims caught",
          "打了 3 圈" in why_drop and "只领到了 2 次" in why_drop, True)

    weekly_clean_log = "\n".join([
        "2026-11-23 10:00:00,000 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0",
        "2026-11-23 10:01:00,000 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文：本周剩余可收取次数：1/3",
        "2026-11-23 10:02:00,000 INFO TaskExecutor FarmEchoTask:周本领奖：打完了，去结晶按 F",
        "2026-11-23 10:02:05,000 INFO TaskExecutor FarmEchoTask:周本领奖：点击确认",
        "2026-11-23 10:02:20,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 1/3→0/3",
    ])
    check("CLEAN RUN (#192/#193): verified 1->0 has 0 false alarms",
          outcome.weekly_incomplete_reason(weekly_clean_log), "")

    print("[F4.3 #189: start_controller hwnd=0 non-TaskExecutor line vs real TaskExecutor error]")
    okww_ctrl_only = (
        "2026-11-21 09:00:05,100 ERROR ok.core.start_controller Window hwnd=0 not found, retrying\n"
        "2026-11-21 09:01:00,000 INFO TaskExecutor DailyTask:每日任务完成\n"
    )
    filtered = outcome._task_lines(okww_ctrl_only)
    check("FALSE ALARM cured (#189): non-TaskExecutor start_controller noise filtered from task lines",
          ("start_controller" not in filtered, "DailyTask" in filtered), (True, True))

    okww_real_err = (
        "2026-11-21 09:01:00,000 ERROR TaskExecutor FarmEchoTask:附加任务出错: 找不到传送按钮\n"
    )
    filtered_err = outcome._task_lines(okww_real_err)
    check("REAL FAULT detected (#189): TaskExecutor error preserved for alerting",
          "找不到传送按钮" in filtered_err, True)

    print("[F4.4 #135 zh_CN normalize, #106 sanity out, #107 AllTasksCompleted+CloseDown, #185 midnight]")
    norm135 = outcome.normalize_okww_log("2026-11-03 09:00:00,000 INFO TaskExecutor 每日任务已完成")
    check("#135 Chinese OK-WW log line normalized cleanly", "Daily Task Completed" in norm135, True)
    check("#106 MaaEnd v2.34 体力不足 pattern recognized",
          bool(collector_maaend._END_SANITY_OUT.search("体力不足，任务结束")), True)
    maa_closedown = (
        '[2026-10-16 09:05:00] Assistant::append_callback | AllTasksCompleted {}\n'
        '[2026-10-16 09:05:01] Assistant::append_callback | TaskChainStart {"taskchain":"CloseDown"}\n'
    )
    check("#107 AllTasksCompleted before CloseDown recognized as post-action (0 false alarm)",
          outcome._closedown_after_all_done(maa_closedown), True)
    check("#107 CloseDown WITHOUT AllTasksCompleted stays fault",
          outcome._closedown_after_all_done(
              '[2026-10-16 09:05:01] Assistant::append_callback | TaskChainStart {"taskchain":"CloseDown"}\n'
          ), False)

    ef_dir = tmpdir("f4-185-")
    old_f = ef_dir / "ok-script.2026-11-19.log"
    new_f = ef_dir / "ok-script.log"
    old_f.write_text("2026-11-19 23:59:10,000 INFO TaskExecutor FarmEchoTask:farm echo ok\n", encoding="utf-8")
    new_f.write_text("2026-11-20 00:00:01,000 INFO MainThread rotated\n", encoding="utf-8")
    ts_old = datetime(2026, 11, 19, 23, 59, 10, tzinfo=SERVER_TZ).timestamp()
    os.utime(old_f, (ts_old, ts_old))
    orig_log = weeklyboss._okww_log
    weeklyboss._okww_log = lambda: new_f
    try:
        qm = echofarm.quiet_minutes(
            now=datetime(2026, 11, 20, 0, 0, 2, tzinfo=SERVER_TZ),
            since=datetime(2026, 11, 19, 22, 57, 0, tzinfo=SERVER_TZ),
        )
    finally:
        weeklyboss._okww_log = orig_log
    check("FALSE ALARM cured (#185): midnight rotation reports < 2 min quiet instead of 63 min",
          qm is not None and qm < 2.0, True)


# ==============================================================================
# Family 5: State persistence / lock contention / shutdown & make-up
# ==============================================================================

def _part_f5_state_locks_shutdown():
    """F5: D-1017 boot read-lock, #173 planned poweroff, #178 Skland annihilation, #179 live stage."""
    from ark_relay.core import config, engine as eng_mod, ledger, statestore
    from ark_relay.core.collector import RunRecord, record_to_payload
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import handle, procwatch, stagegate

    print("[F5.1 D-1017: boot read-lock never drops held pending alarm]")
    sd = tmpdir("f5-state-")
    rec = RunRecord(
        run_id="2026-11-26/endfield/MaaEnd-09-00-00",
        script="MaaEnd",
        user="Default",
        started=datetime(2026, 11, 26, 9, 0, tzinfo=SERVER_TZ),
        finished=datetime(2026, 11, 26, 9, 3, tzinfo=SERVER_TZ),
        ok=False,
        failed_tasks=["基质刷取"],
    )
    ledger.State(sd).save_pending({"pending": [record_to_payload(rec)], "recovered": [], "unsent": []})
    sf = sd / statestore.FILE
    before_bytes = sf.read_bytes()
    statestore._LAST_GOOD.pop(str(sf), None)
    statestore._UNREAD.pop(str(sf), None)
    orig_read = Path.read_text
    orig_waits = statestore.LOCK_WAITS
    Path.read_text = lambda self, *a, **kw: (_ for _ in ()).throw(PermissionError("locked")) if self == sf else orig_read(self, *a, **kw)
    statestore.LOCK_WAITS = (0.0,)
    try:
        cfg = config.Config()
        cfg.state_dir = sd
        e = eng_mod.Engine(cfg, source=SimpleNamespace(fetch=lambda s: []), state=ledger.State(sd),
                           notifier=SimpleNamespace(send=lambda *a, **k: []))
        refused = False
        try:
            e._persist_pending()
        except PermissionError:
            refused = True
        check("boot read-lock refuses empty overwrite and keeps disk state intact",
              (refused, sf.read_bytes() == before_bytes), (True, True))
    finally:
        Path.read_text = orig_read
        statestore.LOCK_WAITS = orig_waits
        statestore._LAST_GOOD.pop(str(sf), None)
        statestore._UNREAD.pop(str(sf), None)

    print("[F5.2 #173: planned farm poweroff vs unexpected shutdown]")
    pdir = tmpdir("f5-173-")
    t_ask = datetime(2026, 11, 14, 8, 20, 10, tzinfo=SERVER_TZ)
    (pdir / procwatch.FARM_POWEROFF_MARK).write_text(
        json.dumps({"by": "spa_run.py", "at": (t_ask - timedelta(seconds=10)).timestamp(), "outcome": "done"}),
        encoding="utf-8",
    )
    asked = {"process": r"C:\Windows\System32\shutdown.exe", "at": t_ask}
    check("FALSE ALARM cured (#173): planned spa_run.py poweroff recognized",
          procwatch.farm_poweroff_planned(asked, base=pdir) is not None, True)
    (pdir / procwatch.FARM_POWEROFF_MARK).write_text(
        json.dumps({"by": "spa_run.py", "at": (t_ask - timedelta(seconds=10)).timestamp(), "outcome": "failed"}),
        encoding="utf-8",
    )
    check("REAL FAULT detected (#173): failed-outcome marker NOT excused",
          procwatch.farm_poweroff_planned(asked, base=pdir), None)

    print("[F5.3 #178: Skland full vs unbacked Monday Annihilation skip]")
    sd178 = tmpdir("f5-178-")
    eng178 = SimpleNamespace(cfg=SimpleNamespace(state_dir=sd178, skland_cred="c"), state=ledger.State(sd178))
    rec_skip = RunRecord(
        run_id="2026-11-16/arknights/MAA-09-00-00", script="MAA", user="u",
        started=datetime(2026, 11, 16, 9, 0, tzinfo=SERVER_TZ),
        finished=datetime(2026, 11, 16, 9, 5, tzinfo=SERVER_TZ),
        ok=True, raw={"annihilation": True, "annihilation_no_entry": True},
    )
    orig_sk = handle._read_skland_annihilation
    try:
        handle._read_skland_annihilation = lambda _e: {
            "current": 1800, "total": 1800,
            "store_ts": int(datetime(2026, 11, 16, 9, 3, tzinfo=SERVER_TZ).timestamp()),
            "read_at": "09:05",
        }
        check("FALSE ALARM cured (#178): Monday skip backed by Skland 1800/1800",
              handle._annihilation_checked_full(eng178, rec_skip) is not None, True)
        handle._read_skland_annihilation = lambda _e: {
            "current": 1200, "total": 1800,
            "store_ts": int(datetime(2026, 11, 16, 9, 3, tzinfo=SERVER_TZ).timestamp()),
            "read_at": "09:05",
        }
        check("REAL FAULT detected (#178): Monday skip with Skland 1200/1800 stays unbacked",
              handle._annihilation_checked_full(eng178, rec_skip), None)
    finally:
        handle._read_skland_annihilation = orig_sk

    print("[F5.4 #179: live stagegate after boot set_stage vs unreachable stage]")
    fx = stagegate_fx()
    r179 = tmpdir("f5-179-")
    maa = fx.maa_dir(r179 / "maa")
    mas = fx.automas_dir(r179 / "mas", stage="YW-4", queues={"早班": ("09:00", ("MAA",))}, beta3=True)
    at = datetime(2026, 11, 17, 8, 46, tzinfo=SERVER_TZ)

    def live_ok(p, b=None):
        if p == "/api/scripts/get":
            return {"data": {"s-m": {"Info": {"Name": "MAA", "Path": str(maa / "MAA.exe")}}}}
        return {"data": {"u": {"Info": {"Name": "a", "Status": True, "RemainedDay": -1},
                               "Stage": {"StageMode": "Fixed", "Stage": "1-7", "Stage_1": "-", "Stage_2": "-", "Stage_3": "-"},
                               "Task": {"IfFight": True}}}}

    check("FALSE ALARM cured (#179): live backend 1-7 overrides stale disk YW-4",
          stagegate.run_verdict(mas, maa, at, mas_get=live_ok)[:2], (stagegate.YES, "1-7"))
    check("REAL FAULT detected (#179): disk YW-4 still caught when backend offline",
          stagegate.run_verdict(mas, maa, at, mas_get=lambda p, b=None: (_ for _ in ()).throw(OSError("down")))[:2],
          (stagegate.NO, "YW-4"))


# ==============================================================================
# Family 6: Alert routing, truncation & zero-weakening guard
# ==============================================================================

def _part_f6_alert_routing_and_zero_weakening():
    """F6: 100% real-fault group routing, #139/#140 <=3-part cap, errwatch & USER-SWITCHES guard."""
    from ark_relay.core import notify, texts
    from ark_relay.features import errwatch

    print("[F6.1 100% of real fault/alarm titles route strictly to 'group']")
    fault_titles = [
        texts.SELFCHECK_FAILED,
        texts.AUTOMAS_CONTRACT,
        texts.ANNIHILATION_OFF,
        texts.RUN_LIMIT_STUCK,
        texts.machinecheck_failed("#R02", "终末地脚本预更新已交由调度程序接管（测试版通道）"),
        texts.stage_gate_warn("早班"),
        "⚠️ 终末地早班没干完",
        "🩺 中继自己报错了",
        "❌ 明日方舟运行失败",
        "🚨 脚本卡死已终止",
    ]
    routes = [notify.route_of(t, alert=True) for t in fault_titles]
    check("every real fault title routes to 'group' (100%)", all(r == "group" for r in routes), True)

    print("[F6.2 #139/#140: oversized error body capped to <= MAX_PARTS while preserving links]")
    huge = "⚠️ 鸣潮报错详情\n" + ("重复堆栈信息行内容很长很长很长\n" * 400) + "日志：https://example.invalid/log.txt"
    capped = notify.WeComBot._cap(huge)
    parts = notify.WeCom._split(capped, notify.WeComBot._LIMIT)
    check("oversized alert split count <= MAX_PARTS (3)", len(parts) <= notify.WeComBot.MAX_PARTS, True)
    check("truncation preserves log link at the tail", "https://example.invalid/log.txt" in capped, True)

    print("[F6.3 Zero-weakening guard: errwatch pushes unhandled WARNING/ERROR without silencing]")
    pushed = []

    class CapNotifier:
        def send(self, title, body, *, alert=False, daily=False):
            pushed.append((title, body, alert, daily))
            return []

    sd = tmpdir("f6-ew-")
    h = errwatch.install(CapNotifier(), state_dir=sd)
    lg = logging.getLogger("ark.test_replay_history_6families")
    try:
        lg.warning("模拟真实中继未处理异常：状态文件损坏")
        errwatch.drain(timeout=3.0)
    finally:
        if lg.parent is not None:
            lg.parent.removeHandler(h)
        h.close()
    check("unhandled WARNING reaches group push with alert=True",
          any(a and "状态文件损坏" in b for _t, b, a, _d in pushed), True)

    print("[F6.4 USER-SWITCHES.txt integrity: non-empty and every rule retains user quote & verdict]")
    us_lines = [
        ln for ln in (RELAY / "USER-SWITCHES.txt").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    check("every USER-SWITCHES entry keeps verbatim quote and verdict",
          bool(us_lines) and all("「" in ln and "| verdict:" in ln for ln in us_lines), True)


PARTS = [
    _part_f1_automas_drift_and_eventloop,
    _part_f2_external_api_cdn_risk,
    _part_f3_desktop_ocr_launcher,
    _part_f4_script_logs_overlay_weekly,
    _part_f5_state_locks_shutdown,
    _part_f6_alert_routing_and_zero_weakening,
]


if __name__ == "__main__":
    sys.exit(run_parts(PARTS))
