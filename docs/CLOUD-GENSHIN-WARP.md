# 云原神:挂 WARP 直接玩(不经卢电脑)

2026-09-09 实测通过:派到节点、排队、出画面。

## 每次玩,只做两步

1. 双击桌面的 **云原神.app**(它会把 WARP 打开,再用 Chrome 打开云原神页面)。
2. 登录,点「进入游戏」。

没有别的动作。测速那一步由装在 Chrome 里的小插件自动处理。

## 一次性准备(装插件,做一次就好)

Chrome 地址栏输入 `chrome://extensions` 回车,然后:

1. 右上角 **Developer mode** 开关打开。
2. 左上角点 **Load unpacked**。
3. 选这个文件夹:`Claude/maa-automation/scripts/mac/cloud-genshin-ext`,点 **Select**。

列表里出现 **Cloud Genshin ping prewarm** 就装好了。

Chrome 大版本更新后有可能把它自动关掉(Chrome 对这类手动加载的插件就是这么处理的)。
症状是又弹「网络错误」。处理:回到 `chrome://extensions`,把它的开关重新打开。

## 它到底修了什么

云原神网页派节点前要测速:同时连 9 个国内测速点,**每个点限时 1 秒**收满 20 个回包,这 1 秒写死在米哈游的 SDK 里(`testRttMs(20, 1e3)`)。
走 WARP 到国内一个来回约 270 毫秒,三次握手就用掉 800 多毫秒,9 个点全部超时,提交给服务器的是空表,服务器回 `-110013 网络连接失败`,页面显示「网络错误 / 当前网络异常」。

插件在页面打开时就把这 9 条 WebSocket 连接建好并一直挂着。SDK 测速时拿到的是复用现成连接的薄壳,1 秒只需覆盖 20 个回包(约 300 毫秒)。
上报的延迟是真实回包时间,不造假。服务器不卡延迟大小:1005 毫秒的结果照样派节点。

## 文件

| 文件 | 用途 |
|---|---|
| `scripts/mac/cloud-genshin-ext/` | Chrome 插件(日常用这个) |
| `scripts/mac/cloud-genshin-prewarm.user.js` | 同一段代码的 Tampermonkey 版 |
| `scripts/mac/cloud-genshin-prewarm.bookmarklet.txt` | 同一段代码的书签版,不装插件时应急 |
| `scripts/mac/make-cloud-genshin-app.sh` | 重新生成桌面的 云原神.app |

## 还没验证

WARP 下画面流畅度没量过(能进、能出画面已验证)。如果卡,再回到经卢电脑的方案(`docs/HOME-NETWORK.md`,`cn-route-pf.sh`)。
