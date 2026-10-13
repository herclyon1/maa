#!/usr/bin/env python3
"""Warnings from the config readers are said once per condition, not on every call.

errwatch pushes every WARNING to the group, and read_maaend / read_maa / the plan
run on every phone publish (50-80 a day on 10-10..10-12) and every engine tick;
relay.log 09-10 shows the same 「AutoCollectRoutes 没有中文名」 three times.
A condition that clears and comes back is said again.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import mastercfg, mastercfg_maa, plan

FAILED: list[str] = []


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


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

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
