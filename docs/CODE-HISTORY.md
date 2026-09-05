# 代码里搬出来的来龙去脉

第三步（2026-09-06）：代码只留「为什么这样写」一句，事故经过搬到这里。
每一节的标题是 `文件:函数`，正文是从那个位置原样搬出来的注释。

## service.py:(模块级)

```
# How long a *live* Electron shell with no backend is left alone before the
# revival is allowed to force-kill it. The stuck state this guard exists for
# lasts hours; a first-run environment wizard - installing Python, pip and
# git, then cloning the backend - legitimately has no backend for several
# minutes and looks identical. On 2026-08-22 the revival killed that wizard
# twice mid-clone and the operator was told all six mirrors had failed.
```

## service.py:SvcStop

```
# 硬保险：15 秒还没退干净就强制退出进程。
# 用户 2026-08-31：「中继服务卡在 STOP_PENDING 这个不要再出现了，
# 直接浪费很长时间，杜绝。」——那天一上午卡了四次，每次部署白等
# 十分钟，还得远程强杀。
# 为什么强退是对的：卡在 STOP_PENDING 比强退坏得多——部署整个瘫掉、
# 通知链路一直断着、还要人去救。而这个进程的状态全是原子写盘的
# （见 config.atomic_write_text），强退不会写坏任何东西；
# 真丢的只是「本轮还没处理完的那几条记录」，下次启动会重新扫到。
```

## service.py:main

```
# New code before anything else uses it. This block was silently lost
# in a refactor on 2026-08-17 - a range replace swallowed it - and for
# three commits the machine stopped receiving updates at all while the
# log still looked healthy. Keep it adjacent to its own marker.
# Before anything reaches for the network. Both the update and the
# inbox run in the seconds after boot, and on a cold boot there is no
# DNS yet - so both used to fail on every single boot and give up.
```

## service.py:_stage_patch_okww

```
# 每次启动都贴一次 OK-WW 补丁——幂等，在位就一句话都不写。
#
# 以前只在开机预更新那一段里贴，于是白天改完补丁、部署、服务重启，
# 补丁**要等到第二天开机才生效**。2026-08-27 就这么发生了：残像聚落
# 「只刷落渊南丘」的修复推上了机器，文件却还是旧的，我以为已经好了。
# 「更新必须立即生效」是死命令，部署完就该是最终状态，不能留一个
# 「等下次开机」的尾巴。
```

## service.py:_stage_announce_update

```
# 人话优先。用户 2026-08-26：「更新内容用人话写」——
# 一串文件名对着看不懂代码的人等于什么都没说。RELEASE-NOTES.md
# 由部署时一起推上来，写的是「修好了你遇到过的哪个毛病」。
# 文件名退居其次，只在没有说明文件时才列出来兜底。
```

## service.py:_stage_inbox_and_phone

```
# Once, at startup. The machine boots for each queue, so a change
# pushed while it is off - which is nearly always - lands before that
# day's run. Re-checking on a timer was added and removed again: it
# bought nothing the boot check did not already cover.
# ---------- 手机端 ----------
# 用户 2026-08-31 定的形状：开机必取一次指令、必上报一次状态；
# 关机前必上报；手机按刷新能实时拿到状态（仅机器开着时）；
# 在线/离线不许靠轮询。做法见 phone.py 的模块说明。
```

## service.py:_stage_preupdate

```
# MaaEnd updates itself at startup and restarts its own process when it
# finds a new build. AUTO-MAS kills and relaunches it before every
# round, so every round lands on that check, and the restart orphans
# the log monitor AUTO-MAS just attached - every task in the round is
# reported failed seconds later. Measured 2026-08-22; the channel is
# `beta`, which ships most days, so most days opened with a wasted
# attempt and a failure alert.
#
# Auto-update stays on - being current is the point of it. The update
# is moved instead: done here, in the gap between boot and the first
# queue, where a restart costs nothing. By the time the queue starts,
# the check answers "有更新=false" and the process AUTO-MAS launches is
# the one that stays.
```

## service.py:_stage_preupdate

```
# Anything that could not be *checked* lands here. A pre-update
# that cannot tell whether an update exists must say so: on
# 2026-08-25 OK-WW was launched into session 0, its updater
# never ran, and the unchanged version file was reported as
# 无需更新 while v3.6.5 had been out for fourteen hours.
```

## service.py:_stage_preupdate

```
# OK-WW 的自动更新会整段覆盖 src，把本地补丁抹掉
# （2026-08-26 实测：v3.6.5 → v3.6.6-beta.1 之后两个补丁全没了，
#  连备份一起）。所以每轮开机都贴一次——幂等，在位就什么都不做。
# 放在 run_okww 之后：先让它更新完，再往新代码上贴。
```

## service.py:_loop

```
# A pause order that failed to download is not a pause order. On
# 2026-08-17 the queue file was unreachable all evening and the
# operator's stop order silently never arrived - so a failed boot
# fetch is retried every five minutes until the file has actually
# been read once, instead of waiting a whole day for the next boot.
```

## okww_patch.py:ensure_patches

```
# 2026-08-31 撤回：前提就是错的。ok.util.logger.Logger.error 的签名是
# error(self, message, exception=None)，第二个参数**本来就是异常**，
# 它内部走 exception_to_str(exception) 打印堆栈。上游写法没问题。
# 而我加的 exc_info=True 这个封装根本不认，当场 TypeError，
# 把一次可恢复的重试变成了硬崩溃（16:00 那趟就是这么死的）。
```

## engine.py:Engine

```
# MaaEnd 里这几项失败是上游/游戏本身的问题，不是要人半夜处理的故障：
#   应急理智加强剂：beta.5 在「选择加强剂」那步坏了（09-03 实录，已关掉等上游）
#   自动采集：15 条路线里总有两三条「采集失败」，任务整体就报失败，其余都采了
# 用户 2026-09-03：「今天下午或者明天再报错你就滚」——这类只进日报，不推 ⚠️。
```

## engine.py:_scripts_running

```
# Endfield.exe is on this list because MaaEnd has NO process of its
# own - AUTO-MAS's python drives it in-process (verified 2026-08-20:
# during a MaaEnd run tasklist shows only the game). Watching for
# "MaaEnd.exe" alone made this check blind through the entire 终末地
# phase; the game binary is the only visible sign that phase is live.
```

## handle.py:_maa_app_log

```
# 只有起点没有终点会把**后面几趟**也扫进来。2026-08-30 空跑时
# 08-29 晚班读到 72810 行（今早那趟的两倍），技能失败数变成 20+21=41，
# 等于把今早的错算到了昨晚头上。所以必须有上界。
# `until` 给 None 时不设上界——`duration_known=False` 的记录时间不可信，
# 那种情况宁可多取也不要把整趟切没了。
```

## handle.py:_handle

```
# Only a pass that actually reached the weekly cap counts. MAA
# reports Success! even when it stops early for want of sanity, and
# closing 剿灭 on that would skip the rest of the week with the cap
# unmet - the run on 2026-08-17 needed five sorties and 125 sanity
# to get from 0 to 1800.
```

## handle.py:_handle

```
# 2026-08-26：这里原本写的是 `notes.append(msg)`，可这个作用域里
# 根本没有 notes——一路 NameError 把整个 _handle 打断，那条
# OK-WW 记录当场「处理运行记录失败」。照 🗓️ 剿灭 那支写，
# 两条周门本来就该是一个形状。
```

## handle.py:_handle

```
# AUTO-MAS 说「这个脚本正常退出了」，不等于它把活干成了。
# 2026-08-27：OK-WW 连着三轮没打残象聚落、MaaEnd 卡在弹窗上
# 把失败当做完自己关掉——两边一个 ERROR 都没报，而这里照样
# 记 ✅、照样静默。用户的原话是「他不报错，他直接把自己关掉了」。
# 所以退出之前先按证据核对一遍，没干成的必须出声。
```

## handle.py:_handle

```
# MaaEnd 启动时会「Auto-cleared log files and debug artifacts」——
# 上一轮的 on_error 截图和日志在**下一次启动的瞬间**就被它自己删光。
# 2026-08-27 早上卡弹窗那三张截图就是这么没的：中午一重试，证据全无，
# 事后只能凭当时抄下的文件名说话。所以失败一落账就立刻把证据搬走。
```

## handle.py:(模块级)

```
# 同一件事当天只报一次。2026-09-01 群里同一个 OK-WW 失败连推三条
# （17:00 / 08:29 / 11:54），用户：「赶紧去修，报了三次了。」
# 键 = 脚本 + 失败在哪一步：同一步反复失败是同一件事，不许反复推；
# 换了一步失败就是新事，照报。当天记账在 state/alerted-<日期>.json，
# 日报仍会汇总全部失败趟数，静默的只是重复的即时推送。
```

## report.py:_maybe_daily_report

```
# Yesterday first. Everything below keys off "today", so a report that
# could not be delivered before midnight (channel outage - it has
# happened: 60020 all day on 2026-08-20) used to be abandoned the
# moment the date rolled: today's ledger is a different file, and no
# code path ever looked back. The runs are still in yesterday's
# ledger; send their report late rather than never.
```

## report.py:_compose_daily

```
# Event countdown rides on every report (operator order, 2026-08-20):
# a fixed-stage config plus an event ending overnight is a silent
# next-morning failure. Appended outside the model's text so a model
# outage can never drop it.
```

## claim.py:(模块级)

```
# ---- 真正领周本奖励 --------------------------------------------------------
#
# 2026-09-01 凌晨,用户看着屏幕说的:「打完之后拿声骸直接一直重开去刷,
# 这不是拿宝箱奖励」「这是声骸模式」。日志完全印证:三轮都是
# 打 Boss → farm echo on the face → 点掉退出弹窗 → 重开,
# 本周剩余次数一直 3/3、波片 91 一点没掉。
#
# **我之前的整个前提是错的。** `FarmEchoTask` + `Teleport to Boss =
# Weekly Challenge` 是**刷 4C 声骸**的模式——传送到周本 Boss 那儿反复刷,
# 领奖那一步根本不在这条代码路径里。那句「结晶波片不足,无法获取奖励,
# 请确认是否继续进入」只是**进本前的提醒**,不是「进本时扣波片发奖励」,
# 我把它读反了,还据此写了文档和三条补丁。
#
# 真正的领奖:打完 Boss **走到结晶前按 F,花 60 波片**。同仓库的
# `TacetTask` 里就有这套现成写法(凝素领域也是花体力领奖):
#     walk_to_treasure() → pick_f(handle_claim=False)
#     → has_claim_stamina() → use_stamina(once=60)
#
# 插在「退秘境」之前。安全性:`has_claim_stamina()` 是门,认不出那个
# 界面就什么都不花、原样走老路;整段包在 try 里,任何异常都只是回到
# 原来的行为,不会把日常任务带崩。
```

## core.py:_Patch

```
# 这条补丁**跨版本不变**的特征串（比如那句日志）。贴完之后它必须只出现
# 一次；出现多次就说明旧版本没还原干净、叠了两层。
# 为什么不能拿 new 的头一行当判据：叠加是「旧版本 + 新版本」并存，
# 新版本仍然只出现一次，数它永远抓不到。2026-09-01 就是这么漏掉的。
```

## core.py:_apply_one

```
# 注意 present() 的判据必须跟着 new 一起改。
# 2026-08-31 踩过：我给「波片不足时跳过周本」加了调试行，present() 认的
# 还是那句没变过的日志，_apply_one 判成「已在位」直接返回，新版本
# **一声不吭地没部署**，我却在日志里找那行调试输出，白等一趟。
# 判据要认 new 里**这一版独有**的东西，改了内容就要跟着改判据。
```

## count.py:(模块级)

```
# ---- 进本之前拍一张 Boss 页面，看本周还剩几次 ----------------------------
#
# 2026-08-31 用户问：「你确定刷的两次周本奖励是 90 级的副本？」——问得对，
# 等级 90 是 16:20 才写进母本、16:41 才同步过去，之前几趟点的都是
# 「推荐等级80」。而「已用 2 次」这个数是我从体力消耗**推算**的，
# 不是读到的。推算已经错过好几回了，这次去读真的。
#
# 安全性：波片不足时进不去（会弹「结晶波片不足」，我们的补丁取消并跳过），
# **不消耗次数**。所以这张图可以在波片不够的时候放心拍。
```

## domain.py:(模块级)

```
# ── 补丁二：副本没打通不该把整个每日任务带走 ──────────────────
# 2026-08-26 实测：凝素领域限时没打完 → 不掉宝箱 → walk_to_treasure 抛
# WaitFailedException → 它不在 except 里 → 一路穿到 DailyTask.run。
# 当天连续四次「Daily Task exception stopped」，领奖 / 邮件 / 附加任务全跳过，
# total daily points 0。而紧邻的 farm_domain_with_recovery_loop 里作者写了
# max_recovery_retries=3 的恢复重试，只能通过 return False 进入，
# 于是对这个失败模式完全是死代码。
```

## farmerr.py:(模块级)

```
# ---- 周本活锁：把被吞掉的异常打出来 ----------------------------------------
#
# 2026-08-31 实测：12:35:53→12:47:44 之间「传送 → found a claim reward → 传送」
# 转了 21 圈、35 秒一圈，白烧 12 分钟才真打上 Boss。上游那段是：
#
#     except Exception as e:
#         logger.error('farm 4c error, try handle monthly card', e)
#         if self.handle_claim_button() or self.handle_monthly_card():
#             self.run()
#
# logging 把第二个位置参数当成 msg 的 printf 参数，而 msg 里没有 %s，
# 于是**异常内容整个丢掉**——日志里只剩一句没有信息量的 'farm 4c error'，
# 真因查不到。这条补丁只把它改成 exc_info=True，**不动任何控制流**：
# 递归、重试次数、判定全部原样。下一次周本一跑，真因就会自己写在日志里。
#
# 递归没有上限这件事是上游的设计问题，已提 issue，本地不擅自改控制流——
# 改了就等于在没有证据的情况下动生产脚本。
```

## letpass.py:(模块级)

```
# ---- 让「主动跳过」这个信号穿过兜底 ----------------------------------------
#
# teleport_to_configured_boss_and_prepare 的兜底把**所有**异常包成 RuntimeError：
#     except Exception as e:
#         raise RuntimeError('Teleport to boss failed') from e
# 于是我们主动抛的 TaskDisabledException 也被包住，run() 那句
# `except TaskDisabledException: pass` 永远看不到它，落进后面的通用兜底，
# 打一条 farm 4c error 再递归重试。
#
# 2026-08-31 实测：波片不足时确实跳过了、Boss 一轮都没白打，但日志里
# 仍有 3 条 farm 4c error、跳过也重复了 3 次——就是被这层包装挡的。
# 放行 TaskDisabledException，其余照旧包成 RuntimeError。
```

## nest.py:_apply_nest

```
# 上游永远不会包含我们自己造的这个配置常量，所以见到它就说明现场那份
# 是我们贴过的某个版本，照常覆盖。
# 为什么不只靠 _NEST_KNOWN_OURS：那张表要求**每次改补丁都手动补一条哈希**，
# 2026-08-29 我改了补丁却忘了补，于是修复推不上去，部署还照常报成功
# （只在日志里留了一行 warning）。靠人记的步骤迟早会漏，标记不会。
```

## nofarm.py:(模块级)

```
# ---- 禁用刷体力，把波片留给周本 --------------------------------------------
#
# 用户 2026-09-01 03:25：「把刷贝币刷体力的任务禁用，这样就不可能会出现
# 波片被消耗的情况。」周本领一次奖要 60 波片，三次 180；而日常刷取
# （凝素/深渊/模拟领域）会把波片吃光——两者抢同一份资源。
# 2026-08-31 就是这么被吃掉的：18:23 贝币刷取把波片从 41 花到 1。
#
# `Which to Farm` 只有三个选项（凝素/深渊/模拟领域），**没有「不刷」**，
# 所以只能打补丁。用**标记文件**而不是配置项：想恢复只要删掉那个文件，
# 不用改代码、不用重新部署。
```

## nowave.py:(模块级)

```
# ---- 波片不足时干净跳过，不空转不白打 --------------------------------------
#
# 2026-08-31 拍到了失败那一刻的画面，游戏弹的是：
#     「结晶波片不足，无法获取奖励，请确认是否继续进入？」[取消][确认]
#
# 三件事因此对上了：
#   * 周本没有「打完开宝箱」这一步，奖励是**进本时扣 60 结晶波片**直接给的；
#   * 波片不够时这个弹窗**挡住了「开启挑战」**，wait_click_feature 超时抛
#     WaitFailedException，run() 兜底又递归重来 → 12:35→12:47 空转 21 圈；
#   * 选「确认」是不拿奖励地进去，所以三轮打完体力 56→56 一动没动，纯白打。
#
# 波片不够进去也拿不到奖励，正确做法是点「取消」并把这次周本安静跳过。
# 抛 TaskDisabledException 是因为 run() 对它的处理就是 `pass`——
# FarmEchoTask 静默结束，日常任务继续往下跑，不会像抛普通异常那样
# 把整个日常带崩（我 16:00 那次就是这么崩的）。
```

## nowave.py:(模块级)

```
# v1 那一版的原文。留着**只为了还原**：它的替换文本末尾自带锚点
# `self.click_team_challenge()`，所以我把 present() 改成认 v3 之后，
# _apply_one 又在它上面贴了一层——两段检查同时存在，v1 在前面先跑，
# 而 v1 正是会误判的那版。2026-09-01 实测：波片 91（>60）也被判成
# 「不足」跳过了。补丁的 new 里带着自己的 old，是这次叠加的根源。
```

## nowave.py:(模块级)

```
# 上一版 v3 的原文，留着**只为了还原**。它把锚点 click_team_challenge()
# 整句吃掉了，所以再想改这条补丁，必须先把它还原成上游原样，
# 否则 _apply_one 找不到 old、报「贴不上了」——2026-09-01 就是这样，
# 而我 grep 部署输出时只筛了「部署完成/❌」，把那条告警漏了过去，
# 机器上跑了 95 分钟的空转我却以为新补丁在跑。
```

## retrycap.py:(模块级)

```
# ---- 兜底重试上限：连败三次就退出，不许无限转 ----------------------------
#
# 上游 run() 的兜底是 handle_claim_button() 成立就无上限递归重试。
# 2026-09-01 实测转了 81 轮、50 分钟。用户：「一直卡循环了……你没有写
# 退出机制。」加上限：连续 3 次 farm 4c error 就结束本次任务，
# 抛 TaskDisabledException（run 自己会安静吞掉，不拖垮日常）。
```

## shot.py:(模块级)

```
# ── 补丁：周本领奖那一刻先截一张图 ────────────────────────────
# 2026-08-31：周本打满三轮，体力一点没动，说明奖励没领到。
# 那行代码是 `wait_click_feature('claim_cancel_button…', relative_x=2)`——
# `relative_x` 是「框内相对 X」，2 就是从取消按钮左边缘往右两个按钮宽度，
# **本意就是去点右边的领取按钮**（用户说领取在弹窗右下角）。日志里点在
# (538, 675)，偏够没偏够，不看那一刻的画面就说不清。
#
# 这个补丁**不改任何行为**，只是在点击之前存一张图。下次周本一跑就有证据，
# 不用再靠猜按钮坐标——猜坐标去改生产脚本正是 826 那类错。
```

## shot2.py:(模块级)

```
# ---- 周本退秘境前先留证据 -------------------------------------------------
#
# 2026-08-31 定位到：打完 Boss、捡完声骸之后，`do_run` 走的是
#     if self._in_realm and not self.in_world():
#         self.send_key('esc', ...)                 ← 直接退秘境
# 宝箱那一步整个不存在。上一版截图拍在 esc **之后**，只拍到「确认离开」
# 弹窗，白拍一次。这次挪到 esc **之前**，拍的是 Boss 刚死那一刻的画面，
# 用来确认宝箱到底以什么形式出现（F 提示？图标？还是要走过去？）。
#
# 零行为改动：只加一次截图，try 包住，失败也不影响流程。
```

## starve.py:(模块级)

```
# ── 补丁四：主C饿死兜底 ────────────────────────────────────────
# 协奏攒不满时 has_buff() 恒为 False，_unbuffed_non_main_target 会让两个辅助
# 无限互切，主C永远上不了场——而主C正是唯一有机会把协奏打起来的人。
# 2026-08-26 实测：56 次切人决策里主C 0 次，全程零输出被磨死。
# 根因是游戏键位被改过（见 issue #1626），已经修好；这条留作保险，
# 平时处于休眠状态（实测健康局面下切人序列与上游完全一致）。
# 2026-08-27：它当初是手工打的、没进这个清单，OK-WW 一更新就被冲掉了。
```

## teamshot.py:(模块级)

```
# ---- 找不到「开启挑战」时留证据 -------------------------------------------
#
# 2026-08-31 真因（堆栈从 12:35 起就在日志里，是我没去读）：
#     teleport_to_configured_boss_and_prepare
#       → teleport_to_configured_boss
#         → click_team_challenge()
#           → wait_click_feature('team_start_challenge', raise_if_not_found=True)
#             → WaitFailedException
# 传送到周本之后找不到「开启挑战」按钮，于是抛异常 → 重试 → 再传送，
# 12:35→12:47 空转 21 圈。上游 #1551 讲的是同一个模板匹配失败。
#
# 周本这条路在点按钮之前还有一次写死坐标的点击 self.click(0.880, 0.911)，
# 那一下歪了后面就全错。到底是模板没匹配上还是页面根本没打开，
# **不看那一刻的画面说不清**，所以先留图再抛，`raise` 保证行为不变。
```

## service.py:_wait_for_network

```
Measured 2026-08-21 21:20:19, one second after the service started on a
fresh boot: all four update doors failed with
`[Errno 11001] getaddrinfo failed`, and thirty seconds later raw was still
only getting as far as a TLS handshake timeout. The relay starts within a
second or two of logon, well before Windows has finished bringing up DNS,
so the boot-window update - the whole point of that window - was reaching
the network before there was one, every single boot.

Nothing downstream retried its way out of that: _best_manifest asks each
door once and returns None if none answer, so the round was abandoned
before the doors were reachable.

The boot-to-queue gap is about ten minutes, so waiting up to ninety
seconds here is cheap. Failing to wait costs the entire update.
```

## service.py:run

```
2026-08-30 之前这里是「一次性」的：RPC 一抖（relay.log 里
`SWbemEventSource 远程过程调用失败`，08-24 到 08-29 共 24 次），
线程直接退出，剩下**整个开机周期**都停在 120 秒轮询上。
机器一天只开两次机，所以中继大部分运行时间都在降级模式跑。
兜底有，但兜底不该是终点。
```

## service.py:collect

```
改配置必须避开脚本运行期。AUTO-MAS 在跑的时候会用它内存里的那份
覆写 ScriptConfig.json，此时写进去的值会被静静冲掉——2026-08-20
实测两次：set_wait_time 120 被冲回 60，剿灭开关被冲回打开，于是
每轮又白跑一次剿灭。engine.scripts_running() 本来就是为这件事
准备的守卫，这里补上调用。
```

## okww_patch.py:ensure_patches

```
2026-08-30 从四个减到一个。留下的只有残象聚落那份整份替换，
因为「只刷指定点位」上游根本没有，只能靠换掉整个文件拿到。

撤掉的三个，理由都是**没有证据说它们现在还在起作用**：

* 主C饿死兜底 —— 是我们自己改过游戏键位造成的（已在上游 #1632
承认并自行关闭 PR）。键位改回默认后症状再没出现。
* 副本失败不拖垮每日任务 —— 对应 08-26 那次「走向宝箱捡不到东西 →
等待超时 → 整个日常崩掉」，多半是背包满。而这条补丁是 08-28 才加的，
**症状 08-27 就已经不再出现**，加它之前病就好了。
* 领奖置底 —— 上游作者 2026-08-29 关闭了 PR #1631，没有留任何说明。
而且这个顺序是作者有意为之，`config_description` 里明写着。
改成 issue 去问「能不能做成可配置」，本地不再改。

三个都主动还原，不是只停止重打。
```

## handle.py:_okww_nest_expected

```
原来读不到就返回 False，于是「配置说不用打」和「我根本没读到配置」
长得一模一样——后者会让残象聚落那一项**整个消失**，OK-WW 照报全绿。
`_okww_master_config` 在没有 automas_dir、没有 data 目录、JSON 读坏
这三种情况下都返回 `{}`，任何一种都会走到这里。
这就是 2026-08-30 排查出的那一类 bug：前置不满足 → 静默什么都不做 → 看着像成功。
```

## handle.py:_maaend_app_log

```
收尾标记「INFO [App] 自动执行任务完成，关闭自身」只出现在
`<maaend>/debug/YYYY-MM-DD-N.log` 里，**不在 AUTO-MAS 的 history 日志里**。
2026-08-29 早班就是只核对了后者，于是「MaaEnd 跑完」这条恒为假，
推了一条「这一轮没干完」的假告警——而 MaaEnd 当时 09:54:38 明明打了那句。
判据没错，错在没把它该看的文件给它。
```

## handle.py:_maa_app_log

```
AUTO-MAS 的 history 日志只记「脚本跑完了没有」，**没有子任务级别的成败**。
所以在 2026-08-30 之前，基建整个失败（`InfrastAbstractTask::on_run_fails`）
也照样被记成全绿——用户连着两天看到的「全绿」就是这么来的。

和 MaaEnd 不一样的地方：MaaEnd 每轮一个新文件，可以按 mtime 挑；
MAA 是**一个滚动的 asst.log**，只能按行首时间戳切。
```

## handle.py:_warn_if_evidence_stale

```
中继是靠监视 AUTO-MAS 的 history 才知道失败的，而 AUTO-MAS 整轮跑完
才写记录。等消息到手，MaaEnd 往往已经重试成功、启动时把 debug 清空了，
于是存下来的是**重试成功那次**的日志。

2026-09-05 就这么绕了一圈：证据目录名是失败那次（MaaEnd-05-27-42），
里面的 maafw.log 却只覆盖 09:57–09:59，那是成功那次（MaaEnd-05-56-35）。
真正定位问题靠的是同时存下来的 AUTO-MAS 那份 .json。

run_id 形如 `<日期>/<用户>/MaaEnd-HH-MM-SS`，末段就是这一轮的开始时刻。
```

## report.py:_fill_single_run_sanity

```
「当前理智」是每次领取**之前**播报的，所以一趟只有一个读数、零个步长，
这一条自己算不出消耗。2026-09-04 的日报里就印成了一条横杠：
那趟其实从 116 刷到 37，花了 79，只是这两个数分别落在前后两条记录里。

只在同一天、同一脚本、且两边都有余量读数时补，补不出来就维持空着——
宁可空，也不写一个编出来的数。
```

## report.py:_announce_banners

```
用户 2026-08-31 定的：只有「任意游戏的新卡池开放的前一天」才发群，
其余时间他自己看 Server酱。所以走 send_group 而不是 send——
后者 Server酱 优先且第一个成功就停，永远到不了群里。

按「游戏+开始时刻」打标记：同一天两个游戏换池要各播一条，
而同一期不许因为日报补发就播第二遍。
```

## shutdown.py:_boot_time

```
Uptime, not the relay's own start time. The relay restarts itself for
every selfupdate, so `eng._started_at` moves - and an update that ran
past a queue's time made the new process disqualify itself from
reporting the missed run, on precisely the boot where something had
already gone slowly enough to be worth knowing about.

`GetTickCount64` is milliseconds since boot and never needs a clock
that agrees with anything. It is Windows-only; anywhere else this
returns None and the callers fall back to their own start time, which
is the conservative direction - a missed-run alarm that is skipped
beats one invented out of a wrong boot time.

This method was referenced from three places since 2026-08-21 and never
actually written. It raised AttributeError inside `_check_missed_runs`,
which the service loop caught and logged, so the relay stayed up while
silently doing none of the work that follows: no missed-run alarms, no
daily report, no power-off. See PITFALLS.
```

## shutdown.py:_unfinished_queues

```
"No game process" is not the same as "the queue is finished". Between
two scripts in one queue there is a window - MAA has exited, MaaEnd's
game is still launching - where neither process exists, and the same
window exists at the very start before the first game comes up. Acting
in it costs a run: it cost 终末地 the morning of 2026-08-16.
```

## shutdown.py:_work_is_done

```
The durable version of `_handled_any`, which only knows what *this
process* watched land. A relay restart after the last run - a
selfupdate is exactly that - cleared the flag, so nothing was left to
trigger the shutdown and the machine stayed awake all night. It cost
2026-08-20 a manual power-off.

Two requirements, and dropping either one costs a run:

A queue must actually have come due. "Nothing is unfinished" is
vacuously true at 08:50 with the 09:00 queue still ahead, and acting on
it would power the machine off minutes before its own run.

And the machine must have booted *before* that queue was due - this
boot has to be the one the queue was scheduled for. Without that test
the rule reaches a machine somebody powered on at 10:35 to work on: the
09:00 queue is still inside its two-hour window and its records are
already in the ledger from the morning, so "everything is finished"
reads true and the machine switches off under them ten minutes later.
Uptime is what distinguishes the two, not the relay's start time, which
every selfupdate resets.

Residual, deliberately not widened: `recent_due_queues` forgets a queue
two hours after it was due, so a restart later than that still leaves
no one to shut down. Widening the window here would also widen the
"wait for a script that never ran" hold that shares it.
```

## shutdown.py:_round_is_manual

```
Manual rounds have to be labelled separately (operator order,
2026-08-20): a scheduled round and a hand-triggered make-up run must
be distinguishable at a glance, or the operator cannot judge whether
a given message was supposed to appear at all.

The test looks only at how far this round's earliest record sits from
a scheduled time - and the scheduled times are read straight from
AUTO-MAS's queue config, so changing the schedule needs no matching
change here. If no schedule can be read it returns False: better to
leave a round unlabelled than to mislabel a scheduled one as manual.
```

## shutdown.py:_last_round_manual

```
A manual round must not count as "the day's work is done". On
2026-08-21 a hand-triggered MaaEnd test finished at 12:29 and the
relay promptly powered the machine off - while the operator was in
the middle of working on it, and hours before the evening queue.

The round is the group of records that finished close together; two
hours is comfortably wider than a full queue (MAA then MaaEnd) and
far narrower than the gap between the morning and evening queues.
```

## shutdown.py:decide

```
- 功能没开 -> never
- 调试模式 / 已被吃掉的这一次机会 -> never（2026-08-31 改判，见下）
- 已经下过关机令 -> never（2026-08-16 一分钟内报了三次、关了两次）
- 本次开机还没跑完队列 -> never
- 开机不够久 -> never（防开机即关机的死循环）
- 有脚本在跑 / 有告警没推 / 客户端在更新 -> never
- 最近一轮是手动跑的 -> never（2026-08-21 把正在维护的机器关了）
- 队列还差脚本 -> never（2026-08-16 两个脚本之间的空档关掉了终末地）
- 到点了但日报没发 -> never（关机等日报，日报从不静默）
```

## core.py:_stacked

```
2026-09-01 踩的坑：v1 的替换文本**末尾自带锚点**
`self.click_team_challenge()`，我把 present() 改成认新版本之后，
_apply_one 就在 v1 上面又贴了一层——两段检查同时存在，旧那段先跑，
而它正是会误判的那版。波片 91（>60）也被判成「不足」跳过。
没有这道自查，叠加是**看不出来的**：文件语法没错、present() 也为真。

判据用 new 的第一行（各版本独有的那句注释/代码），出现超过一次就是叠了。
```

