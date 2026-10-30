"""The sanity-booster step check, and the names of the old switch-off records.

spmed_check reports when the sanity-booster step in MaaEnd's nodes.json has a
shape this module does not recognise; it changes nothing.

Re-exported from gameupdate, so callers write gameupdate.xxx.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path


log = logging.getLogger("ark.gameupdate")


# state.json records (section "updates") that once named MaaEnd tasks the relay
# switched off. Nothing writes them any more and the machine holds none (audit s18
# F5), so the boot step that switched their tasks back on is gone; machine check
# #63 (machinechecks/system.py) still confirms none is left.
_OFF_RECORDS = ("maaend_disabled_1_5_3", "maaend_reenable_next_boot", "maaend_disabled_spmed")


# The sanity-booster (应急理智加强剂) step in MaaEnd's resource/pipeline/nodes.json
# is only inspected here; no task is switched off because of it.
# SPMED_NODE is the confirm node's name before v2.32. Its recognition.param.all_of
# lists nodes; an inline recognition must sit inside its own "recognition" block
# (the shape after upstream PR #5453, "fixed"); an inline element with type/param
# directly on it is not understood by the framework ("broken").
# Fixtures: tests/fixtures/maaend-v2.30.0-beta.4-spmed (node absent),
# tests/fixtures/maaend-v2.32-spmed (SPMED_NODE_V232),
# tests/fixtures/maaend-v2.33.0-rc.1-spmed (SPMED_NODE_V232, "ocr").
SPMED_NODE = "AutoUseSpMedicationQuickUse"
# The node from v2.32 on: the click on the detail page's use button; its all_of
# holds only node names. From v2.33.0-rc.1 (upstream PR #6476, commit cfd2e875) the
# same node clicks the restore-sanity dialog's confirm button found by its own OCR
# in a fixed region ("ocr"): game 1.6 changed that button's icon, so
# YellowConfirmButtonType2 no longer matched it.
SPMED_NODE_V232 = "__AutoUseSpMedicationUseEmergencySpBooster"
SPMED_NODES = (SPMED_NODE, SPMED_NODE_V232)


def spmed_shape(maaend_dir) -> str:
    """How the booster's confirm node reads in this MaaEnd install:
    "fixed" (the shape upstream PR #5453 produced), "ocr" (v2.33.0-rc.1 on: the
    v2.32 node clicks the text its own OCR finds in a fixed region; see
    _is_region_ocr_click), "broken" (inline element without its own recognition block),
    "unknown" (the node is there in a shape this file does not know), "missing"
    (no node of that name: renamed or removed upstream), "unreadable" (nodes.json
    cannot be read), "" (no MaaEnd directory configured)."""
    if not maaend_dir:
        return ""
    f = Path(maaend_dir) / "resource" / "pipeline" / "nodes.json"
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable"
    if not isinstance(doc, dict):
        return "unreadable"
    name = next((n for n in SPMED_NODES if n in doc), None)
    if name is None:
        return "missing"
    node = doc[name]
    if not isinstance(node, dict) or not isinstance(node.get("recognition"), dict):
        return "unknown"
    if name == SPMED_NODE_V232 and _is_region_ocr_click(node):
        return "ocr"
    # all_of only means something under an "And" recognition (older test fixtures
    # leave the type out); an all_of tucked into an OCR or any other type is not
    # one of the shapes below.
    if node["recognition"].get("type", "And") != "And":
        return "unknown"
    all_of = (node["recognition"].get("param") or {}).get("all_of")
    if not isinstance(all_of, list) or not all_of:
        return "unknown"
    # Fixed: every element is a node name, or an inline recognition inside its own
    # recognition block. Broken: an inline element without that block.
    if any(not isinstance(x, (str, dict)) for x in all_of):
        return "unknown"
    return "fixed" if all(isinstance(x, str) or "recognition" in x for x in all_of) else "broken"


# The v2.33.0-rc.1 confirm node, as shipped by upstream PR #6476 (commit cfd2e875),
# and v2.36.0-rc.1+ after PR #6933 (commit 45ba41caec) widened the box to [860, 465, 390, 120].
SPMED_OCR_ROI = [860, 465, 300, 90]
SPMED_OCR_ROIS = (SPMED_OCR_ROI, [860, 465, 390, 120])
SPMED_OCR_WORDS = frozenset({"确认", "確定", "(?i)Confirm", "확인"})


def _is_region_ocr_click(node: dict) -> bool:
    """The v2.33.0-rc.1 / v2.36.0 confirm node: action "Click" (plain string, so no
    click target of its own) on a recognition that is only {"type": "OCR", "param":
    {"expected", "roi"}}, roi in SPMED_OCR_ROIS, expected only the dialog's
    confirm words and including the Simplified Chinese one; the node not disabled,
    not inverted, and with no v1 click target. The roi and the words are what keep
    the click on the dialog's confirm button and off the rewards screen's claim
    button behind it (PR #6476, PR #6933), so any
    other roi or text, a retune included, alarms and a person re-checks it (D210)."""
    if node.get("action") != "Click" or node.get("inverse") or node.get("enabled") is False:
        return False
    if "target" in node or "target_offset" in node:
        return False
    reco = node["recognition"]
    param = reco.get("param")
    if set(reco) != {"type", "param"} or reco.get("type") != "OCR" or not isinstance(param, dict):
        return False
    if set(param) != {"expected", "roi"}:
        return False
    expected, roi = param["expected"], param["roi"]
    return (isinstance(expected, list) and all(isinstance(x, str) for x in expected)
            and "确认" in expected and set(expected) <= SPMED_OCR_WORDS
            and type(roi) is list and len(roi) == 4
            and all(type(x) is int for x in roi) and roi in SPMED_OCR_ROIS)


def spmed_check(cfg) -> str:
    """The booster step's shape when it calls for the boot alarm (texts.SPMED_UNRECOGNISED,
    body texts.spmed_unrecognised_body), '' when it is a known-good shape ("fixed" or
    "ocr") or there is no MaaEnd directory.

    Called at every boot; the task itself is never changed here."""
    shape = spmed_shape(getattr(cfg, "maaend_dir", None))
    if not shape:
        return ""
    if shape == "fixed":
        log.info("开机：应急理智加强剂那段是认得的修好写法")
        return ""
    if shape == "ocr":
        log.info("开机：应急理智加强剂那段是认得的写法（v2.33 起按文字认确认按钮）")
        return ""
    # INFO, not WARNING: the caller sends the alarm, and errwatch forwards every
    # relay WARNING to the group as well.
    log.info("开机：应急理智加强剂那段认不出（%s），报群", shape)
    return shape
