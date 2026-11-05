"""OK-WW's zh_CN log lines are turned back into English from the machine's own catalogs (okww_i18n).

Ledger #136 (2026-11-04): ok-script's 「当前游戏或模拟器不支持选择的截图方式!」 reached the group as an
unknown error because only a hand-written pair would have turned it back. Checked here:
* the .po and .ts readers (multi-line strings, escapes, obsolete / plural / unfinished entries);
* the tables: exact whole messages, concatenated prefixes, placeholders ({}, {name}, %s, %1),
  ambiguous translations dropped;
* normalize only touches a whole OK-WW log message: our own Chinese lines, OCR text and a short
  catalog word inside a longer message stay as they were, English logs are returned unchanged;
* with the real catalogs (OK-WW v3.7.19 ok.po, ok-script 3.0.3 zh_CN.ts, fixtures/okww-i18n) the
  #136 line and full upstream messages come back in English, and outcome.normalize_okww_log still
  applies the hand-written pairs for what the catalogs do not hold;
* a changed catalog is read again.
"""
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from ark_relay.features.verify import okww_i18n as I  # noqa: E402
from ark_relay.features.verify import outcome  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


def root_with(po_text=None, ts_text=None, name="r"):
    root = TMP / name
    if po_text is not None:
        p = root / I.PO_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(po_text, encoding="utf-8")
    if ts_text is not None:
        t = root / I.TS_REL
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(ts_text, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return root


def line(msg, logger="NightmareNestTask", level="INFO"):
    return f"2026-11-05 09:21:32,123 {level} TaskExecutor {logger}:{msg}"


print("[readers]")
PO = '''msgid ""
msgstr ""
"Language: zh_CN\\n"

msgid "Daily Task Completed"
msgstr "每日任务已完成"

msgid "enter combat "
msgstr "进入战斗，控物状态："

msgid ""
"teleport_to_boss "
"prepared as {}"
msgstr "首领传送准备结果：{}"

msgid "found {name} at {pos}"
msgstr "在{pos}找到{name}"

msgid "skip %s of %s"
msgstr "跳过%s/%s"

msgid "Start"
msgstr "开始"

msgid "Begin"
msgstr "开始"

msgid "quote \\"x\\""
msgstr "引号「\\"x\\"」"

#~ msgid "Old line"
#~ msgstr "旧的一句"

msgid "one apple"
msgid_plural "{} apples"
msgstr[0] "{}个苹果"

msgid "Untranslated"
msgstr ""
'''
pairs = dict(I.po_pairs(PO))
check("multi-line msgid joined", pairs.get("teleport_to_boss prepared as {}"), "首领传送准备结果：{}")
check("escaped quotes read", pairs.get('quote "x"'), '引号「"x"」')
check("obsolete entry left out", "Old line" in pairs, False)
check("plural entry left out", "one apple" in pairs, False)
check("empty translation left out", "Untranslated" in pairs, False)
check("header entry left out", "" in pairs, False)
TS = '''<?xml version="1.0" encoding="utf-8"?><TS version="2.1" language="zh_CN"><context><name>app</name>
<message><source>Selected capture method is not supported by the game or your system!</source><translation>当前游戏或模拟器不支持选择的截图方式!</translation></message>
<message><source>Game window is not connected, %1</source><translation>游戏窗口未连接，%1</translation></message>
<message><source>Half done</source><translation type="unfinished">做了一半</translation></message>
</context></TS>'''
tp = dict(I.ts_pairs(TS))
check("ts translation read", tp.get("Selected capture method is not supported by the game or your system!"), "当前游戏或模拟器不支持选择的截图方式!")
check("ts unfinished left out", "Half done" in tp, False)
check("broken ts: nothing, no crash", I.ts_pairs("<TS><message>"), [])

print("[tables]")
R = root_with(PO, TS, "small")
t = I.tables(R)
check("exact", t.message("每日任务已完成"), "Daily Task Completed")
check("concatenated prefix (source ends in a space)", t.message("进入战斗，控物状态：True"), "enter combat True")
check("placeholder", t.message("首领传送准备结果：True"), "teleport_to_boss prepared as True")
check("named placeholders reordered", t.message("在(10, 20)找到残象"), "found 残象 at (10, 20)")
check("printf placeholders", t.message("跳过3/5"), "skip 3 of 5")
check("Qt %1 placeholder", t.message("游戏窗口未连接，请重开"), "Game window is not connected, 请重开")
check("ambiguous translation (Start/Begin) dropped", t.message("开始"), None)
check("not a catalog message", t.message("指定点位都已打满，跳过"), None)

print("[normalize: whole messages only]")
ours = "\n".join([
    line("nightmare nest: 只刷 ['落渊南丘']（设置来自母本）"),
    line("left_click 已击败残象：0/41 (1729, 347) after_sleep 2"),
    line("每日任务已完成还有别的字"),
    line("指定点位都已打满，跳过"),
]) + "\n"
check("our own lines, OCR text and a catalog word inside a longer message stay", I.normalize(ours, R), ours)
eng = line("Daily Task Completed", "DailyTask") + "\n" + line("enter combat True") + "\n"
check("an English log comes back as the same object", I.normalize(eng, R) is eng, True)
mixed = line("每日任务已完成", "DailyTask") + "\r\n" + line("指定点位都已打满，跳过") + "\n"
check("a translated line turned back, line ending kept, other line untouched",
      I.normalize(mixed, R), line("Daily Task Completed", "DailyTask") + "\r\n" + line("指定点位都已打满，跳过") + "\n")
check("not an OK-WW log line: untouched", I.normalize("每日任务已完成\n", R), "每日任务已完成\n")
check("no catalogs at all: unchanged", I.normalize(mixed, TMP / "nowhere"), mixed)

print("[the real catalogs: OK-WW v3.7.19 ok.po + ok-script 3.0.3 zh_CN.ts]")
real = TMP / "real"
(real / I.PO_REL).parent.mkdir(parents=True)
(real / I.TS_REL).parent.mkdir(parents=True)
shutil.copy(HERE / "fixtures" / "okww-i18n" / "ok-v3.7.19.po", real / I.PO_REL)
shutil.copy(HERE / "fixtures" / "okww-i18n" / "okscript-3.0.3-zh_CN.ts", real / I.TS_REL)
rt = I.tables(real)
check("hundreds of whole messages read", len(rt.exact) > 1000, True)
check("ledger #136: the framework's line from zh_CN.ts",
      I.normalize(line("当前游戏或模拟器不支持选择的截图方式!", "start_controller", "ERROR"), real),
      line("Selected capture method is not supported by the game or your system!", "start_controller", "ERROR"))
check("a full upstream message the hand table only had half of",
      I.normalize(line("每日任务已完成，开始传送并刷取4C声骸", "DailyTask"), real),
      line("Daily task completed, start teleport to farm 4C echo", "DailyTask"))
check("captured echo, full message",
      I.normalize(line("战斗中已吸收声骸，跳过搜索。"), real), line("Captured echo during combat, skipping search."))

print("[outcome.normalize_okww_log: catalogs first, then the hand-written pairs]")
os.environ["ARK_OKWW_DIR"] = str(real)
check("catalog line", outcome.normalize_okww_log(line("战斗中已吸收声骸，跳过搜索。")),
      line("Captured echo during combat, skipping search."))
check("a string only the hand-written pairs know still turns back",
      outcome.normalize_okww_log(line("等待游戏启动错误", "ok", "ERROR")), line("waiting for game to start error", "ok", "ERROR"))
os.environ["ARK_OKWW_DIR"] = str(TMP / "nowhere")
check("no catalogs on the machine: the hand-written pairs alone, as before",
      outcome.normalize_okww_log(line("战斗中已吸收声骸")), line("Captured echo during combat"))

print("[a changed catalog is read again]")
R2 = root_with('msgid "Alpha one"\nmsgstr "第一句"\n', None, "changing")
check("before", I.tables(R2).message("第一句"), "Alpha one")
time.sleep(0.01)
(R2 / I.PO_REL).write_text('msgid "Alpha two"\nmsgstr "第一句"\n\nmsgid "Beta"\nmsgstr "第二句"\n', encoding="utf-8")
os.utime(R2 / I.PO_REL, (time.time() + 5, time.time() + 5))
check("after the upgrade: the new source", I.tables(R2).message("第一句"), "Alpha two")
check("after the upgrade: the new string", I.tables(R2).message("第二句"), "Beta")

print("all checks passed" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
