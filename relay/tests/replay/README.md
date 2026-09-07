# 回放样本库（根治第 2 项）

机器上真实跑出来的运行记录，原样（脱敏后）存在这里；所有「判断」函数改动前后都要
过一遍回放，结果和 `expected.json` 逐项比对。**新 bug 先加样本、看它红，再修。**

目录：`tests/replay/<日期>/<账号>/<脚本>-HH-MM-SS.json` + 同名 `.log`，
同一目录下 `expected.json` 记每条记录的判定：`ok`、`failed_tasks`、以及 `raw` 里
挑出来的字段（`okww_steps`、`okww_unreachable`、`okww_error`、`maaend_name_mismatch`、
`tasks_failed` 等）。

拉样本：`scripts/mac/pull-replay.sh 2026-09-07`（机器开着时），会把那天的 history
拷过来、脱敏、并用**当前**解析器生成 `expected.json` 草稿——草稿要人看过再提交，
看的就是「这样判对不对」。
跑回放：`python3 tests/test_replay.py`（也在全套测试和 lint 里）。
