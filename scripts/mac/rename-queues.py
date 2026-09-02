#!/usr/bin/env python3
"""把 AUTO-MAS 的两条队列改名：新队列 → 早班，Evening-MAA → 晚班。

走后端 API（/api/queue/update），不碰文件——改文件会被内存副本冲掉。
机器必须开着、且没有任务在跑（跑着时配置锁定，API 会拒绝）。
改完回读核对，不一致就报错退出。可以重复跑：已是新名就什么都不做。

    ARK_HOST=100.65.39.119 scripts/mac/rename-queues.py
"""
import json
import os
import sys
import urllib.request

HOST = os.environ.get("ARK_HOST", "100.65.39.119")
PORT = os.environ.get("ARK_MAS_PORT", "36163")
BASE = f"http://{HOST}:{PORT}"
RENAME = {"新队列": "早班", "Evening-MAA": "晚班"}


def post(path, body=None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def queues():
    return {qid: str((q.get("Info") or {}).get("Name") or "")
            for qid, q in post("/api/queue/get")["data"].items()}


def main():
    before = queues()
    print("改前：", "、".join(f"{n}" for n in before.values()))
    todo = {qid: RENAME[n] for qid, n in before.items() if n in RENAME}
    if not todo:
        print("没有要改的（已是新名或没有旧名队列）")
        return 0
    for qid, new in todo.items():
        r = post("/api/queue/update", {"queueId": qid, "data": {"Info": {"Name": new}}})
        if str(r.get("status")) != "success":
            print(f"❌ 改「{before[qid]}」→「{new}」被拒：{r}")
            return 2
        print(f"  {before[qid]} → {new}")
    after = queues()
    bad = [qid for qid, new in todo.items() if after.get(qid) != new]
    if bad:
        print("❌ 回读不一致：", {qid: after.get(qid) for qid in bad})
        return 3
    print("✅ 改后：", "、".join(after.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
