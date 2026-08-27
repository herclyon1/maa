# OK-WW 本地补丁 —— 改了什么、为什么、怎么算成功

改动位置：`D:\ark\okww\data\apps\ok-ww\working\src\task\DailyTask.py`
备份：`.bak-20260825-132036`、`.bak3-20260825-133303`
**这些改动会被 OK-WW 的自动更新覆盖**（更新走 CNB git）。上游合并前，每次更新后要重打。

上游仓库：<https://github.com/ok-oldking/ok-wuthering-waves>（★7154）

---

## 补丁一：`ensure_main` 有条件放行

### 上游已经有一版，但它是坏的

`DailyTask.run()` 里，最早见于 2026-06-16（PR #1393，作者 `1w1w11w1`）：

```python
self.get_task_by_class(NightmareNestTask).ensure_main = lambda *args, **kwargs: None
...
finally:
    self.get_task_by_class(NightmareNestTask).__dict__.pop('ensure_main', None)
```

**无条件**把 `ensure_main` 变成空转。而 `NightmareNestTask.run()` 的流程是：

```
ensure_main() → _init_queue() → get_nest_to_go() → openF2Book("gray_book_boss")
```

`ensure_main` 被废掉之后，任务**永远回不到主界面**。只要进任务时画面不在主界面，
`openF2Book` 必然失败 → **`can't find gray_book_boss`**。
**上游的抑制过头了，这正是 bug 本身**，不是"上游已修好、我们重复"。

### 我们的版本

```python
nest_task = self.get_task_by_class(NightmareNestTask)
_real_ensure_main = nest_task.ensure_main
def _ensure_main_keep_book(*args, **kwargs):
    if nest_task.find_one('gray_book_boss', box='box_gray_book', threshold=0.3):
        return None                                 # 书开着 → 别关
    return _real_ensure_main(*args, **kwargs)       # 书没开 → 真的回主界面
nest_task.ensure_main = _ensure_main_keep_book
```

只在书已经开着时才不动，否则照常回主界面。是严格改进。

### 判定成功的唯一标准

**跑一次日常，看还出不出 `can't find gray_book_boss`。不出 = 成功，提 PR。**
不是"验证补丁有没有被执行"。

---

## 补丁二：附加任务提到领奖之前

上游顺序（`DailyTask.run()` 末尾）：

```
claim_daily() → claim_mail() → claim_battle_pass() → run_additional_tasks()
```

附加任务（含**周常乐园** `CHECK_WEEKLY_GARDEN`）在最后。问题：周常打完**还有奖励要拿**，
但那时领奖已经跑完了。我们把 `run_additional_tasks()` 提到 `claim_daily()` 之前。

**注意这是作者有意为之**，`config_description` 里明写：

> "Nightmare Nest runs before stamina farming to help complete the daily task;
> **the other tasks run afterward.**"

**所以 PR 要按「做成可配置」提，不要直接翻转顺序**，否则作者多半不收。

---

## 待做功能：指定残象聚落刷取

底层**已经有一半**——`find_nest()` 给每个点位算了唯一标识，
而且"跳过指定点位"的机制已经在跑：

```python
cache_key = f'{action_name}:{denominator}:{row_slot}'   # 例如 go_nest:41:23
if cache_key in self._unreachable_nests:                # 传送不过去的点位就是这么跳掉的
    continue
```

**缺的是人能选的名字**。`cache_key` 是位置派生的（动作名:分母:行槽位），机器能用、人没法填。
`find_nest()` 的 OCR 区域 `(0.35,0.13)→(1,0.96)` 已经把整行框住了，
只是用 `match=self.count_re` 过滤成只留 `0/41` 这类计数框——**同名那一行的聚落名就在旁边**。

实现三步：
1. 定位到计数框后，同一行左侧再取一次不带过滤的 OCR，拿聚落名
2. 加配置 `'Which Nests to Farm'`（`multi_selection`，留空 = 全打，保持现有行为）
3. 在现有 `if cache_key in self._unreachable_nests` 旁边加名字白名单过滤——复用已有机制，不动主流程

顺带可一并提的脆弱点：

```python
if numerator != denominator and denominator in ['24','36','48','41'] and numerator == '0':
```

分母是**写死白名单**（出个 `0/52` 的新聚落就看不见），`numerator == '0'` 意味着**打了一半的聚落不会继续**。

---

## 不要再查的事

- `Which to Farm`（`NightmareNestTask` 的多选）**早就设成只留残象聚落**了，
  梦魇净化已去掉。见 memory `okww-already-configured`。
- `Which Tacet Suppression to Farm` / `Which Forgery Challenge to Farm` 是现成的
  "指定刷第几个"，只对无音清剿和凝素领域有效，残象聚落没有。
