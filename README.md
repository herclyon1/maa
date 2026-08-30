# 游戏机自动化

一台 Windows 机器每天自动开机两次，运行三款游戏的日常任务，把结果推送出去，
随后自动关机。控制端是一台 Mac，经 Tailscale + SSH 远程管理。

被自动化的是 [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights)（明日方舟）、
[MaaEnd](https://github.com/MaaEnd/MaaEnd)（终末地）与
[OK-WW](https://github.com/ok-oldking/ok-wuthering-waves)（鸣潮），
由 [AUTO-MAS](https://github.com/AUTO-MAS-Project/AUTO-MAS) 统一调度。

`relay/` 是自建的通知中继，运行于游戏机：读取各脚本自身的日志核对运行结果、
在开机至队列启动之间完成各程序的更新、推送汇报与日报、在队列结束后关机。

| 目录 | 内容 |
|---|---|
| `relay/` | 中继源码与测试 |
| `queue/` | 下发给机器的指令 |
| `scripts/` | 控制端与游戏机两侧的工具脚本 |
| `docs/` | 运维参考、配置清单、故障记录 |
