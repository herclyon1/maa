# 工具使用规矩 —— 826 那天踩出来的 21 个坑

这份文档存在的唯一理由：**同一个坑不许踩第二次。**
2026-08-26 一天之内有错误文本的失败共 21 类，其中最高频的一个撞了 **36 次**。
详见 memory `incident-826`、`fix-dont-work-around`。

---

## 远程执行

| 场景 | 用什么 | 不要用什么 |
|---|---|---|
| 多行逻辑、要解析文件 | `scripts/mac/winrun.sh --py <本地.py>` | 内联拼命令 |
| 要看屏幕 / 枚举窗口 / 起图形程序 | `winrun.sh --py1`（走交互桌面会话） | `--py`（在 session 0，没有桌面） |
| 取文件内容 | `winrun.sh --get '<远端路径>'` | 远端 `type`/`cat` 再读 stdout |
| 一次性 PowerShell | `winrun.sh --ps '<单引号包住>'` | 双引号（`$_` 会被 bash 提前展开） |

**PowerShell 一律 `pwsh`（7.6.5），不许 `powershell`（5.1）。**
5.1 默认不是 UTF-8，`ConvertFrom-Json` 读中文 JSON 必失败、输出必乱码。

**ssh 送 PowerShell 一律 base64**，不要拼引号——一条内联命令要穿过
bash → ssh → cmd → PowerShell 四层，每层啃一遍。`winrun.sh` 里的
`run_remote_ps()` 就是标准写法，照抄：

```bash
b64=$(printf '%s' "$PS" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')
ssh "$USER_AT" "pwsh -NoProfile -EncodedCommand $b64"
```

**`winrun.sh --py` 的失败语义**（2026-08-26 修好，之前会静默成功）：

| 退出码 | 含义 |
|---:|---|
| 0 | 正常，有输出 |
| 3 | 脚本送不上去（scp 失败） |
| 4 | 远端没产生 `winrun.out`（脚本没跑起来 / 机器不可达） |
| 5 | **跑了但 0 字节输出**——不是成功，按失败处理 |

**永远不要全盘 `rglob` 找文件。** 826 那天搜 `relay.log` 全盘遍历
`C:\` + `D:\`，10 分钟超时被杀，什么也没找到。**路径应该从代码里读出来**：

* 中继日志：`C:\ProgramData\ark-relay\relay.log`（`deploy-relay.sh` 的
  `REMOTE_DIR` + `service.py` 的 `ARK_LOG_FILE`）
* 中继状态：`C:\ProgramData\ark-relay\state`
* MAS 配置：`D:\ark\automas\config\`
* MaaEnd 日志：`D:\ark\maaend\debug\<date>-<n>.log`、`maafw.log`
* MAA 日志：`D:\ark\maa\debug\gui.log`（界面）、`asst.log`（内核，更细）

---

## AUTO-MAS API（`http://<host>:36163`）

* **全部端点只接受 POST**，GET 一律 `Method Not Allowed`
* 取脚本配置要先 `POST /api/scripts/get {}` 拿 uid，再
  `POST /api/scripts/user/get {"scriptId": "<uid>"}`
* 改配置：`POST /api/scripts/user/update {"scriptId","userId","data"}`
* 队列：`POST /api/queue/update {"queueId","data"}`
* 起停：`POST /api/dispatch/start {"taskId","mode"}` / `/api/dispatch/stop {"taskId"}`
* 字段定义看 `GET /openapi.json` 的 `components.schemas`

**`ValueError: 配置已锁定, 无法修改`**：有任务在跑时配置只读。
**正确做法是先 `dispatch/stop` 把任务停掉、等 AUTO-MAS 进程空下来再写**，
不是硬重试——826 那天连试 18 次全失败。已验证：没有任务在跑时写入立即成功。

**`Config.json` 里 `Data.Stage` 是字符串套 JSON**，要 `json.loads` 两次：

```python
st = c["Data"]["Stage"]
if isinstance(st, str): st = json.loads(st)
```

**MaaEnd 的 `interface.json` 里 `task` 数组是空的**，45 个任务靠 `import`
从 `tasks/*.json` 引进来。只看 `task` 字段会得出「它没有任务」的错误结论。

---

## 中继（ark-relay）

**`ark-relay` 会自动把 AUTO-MAS 拉起来。** `service.py` 的 `_revive_automas()`
是**无条件调用**的，没有 debug 门控（调试模式只管「不关机、不报漏跑」）。
它还挂了进程句柄 + WMI 事件订阅盯着 AUTO-MAS。

**所以任何「停掉一切」的操作必须先停 `ark-relay` 服务**，否则杀掉的 MAS
几十秒后就回来。红按钮 `scripts/mac/estop.sh` 已按这个顺序：
**中继 → MAS → 脚本 → 游戏**。

---

## 本地命令行

* **一律用绝对路径。** 每次 heredoc 之后 shell 的 cwd 会被重置回默认目录，
  相对路径必然失效——826 那天这一条撞了 **36 次**，是当天最高频的问题。
* `gh api` 的 URL 含 `?` 必须加引号，否则 zsh 当通配符报 `no matches found`
* `gh search repos` 的 `--json` 没有 `stargazerCount`（那是 GraphQL 的名字）；
  搜仓库用 `gh search repos --topic=<topic>`，`gh api search/repositories` 常返回空
* macOS 没有 `timeout` 命令。用 Bash 工具自带的 timeout 参数，
  或 ssh 的 `-o ConnectTimeout=`
* 前台 `sleep` 被禁用。要等就用条件轮询，别用 `ping` 凑数
* Chrome headless 会往 stderr 喷噪音（`Trying to load the allocator multiple times`、
  `task_policy_set`）。**`--log-level=3` 对它们无效**——那些行写在日志系统
  初始化之前（2026-08-26 实测）。也**不能 `2>/dev/null`**：Chrome 把
  「N bytes written to file」这条成功信息也写在 stderr。
  **一律用 `scripts/mac/html2png.sh`**，它精确滤掉已知无害行、
  用产出文件本身判成败（Chrome 渲染失败也常返回 0）
* 单次输出超过约 37KB 会被转存到文件而不是直接显示。
  **主动限制输出量**（`head`、只打印需要的字段），别指望全量刷屏

---

## 抓网页

* `WebFetch` 遇跨域重定向**不会自动跟**，要拿到新 URL 再发一次
* 有些站点直接 403（`endfieldtools.dev`、`mobalytics.gg`、`icy-veins.com`、萌娘百科）。
  **正确替代是用浏览器工具真实打开**（`mcp__Claude_Browser__*`），
  那不是绕路，是换成对的工具——WebFetch 是简单抓取器，不是浏览器

---

## 本机已装的额外工具

| 工具 | 位置 | 装的理由 |
|---|---|---|
| `shellcheck` 0.11.0 | `~/.local/bin/shellcheck` | `estop.sh` 是安全关键脚本，`bash -n` 只查语法不查逻辑 |

这台 Mac **没有 Homebrew**。单个静态二进制走官方 release 即可
（`gh release download --repo <owner/repo> --pattern '<name>'`）。
评估过 `coreutils` / `pytest` 不值得装。
