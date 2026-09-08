# Why the infrastructure 「双指滑动到总览」 gesture fails (established 2026-08-28)

## Conclusion: a known upstream bug, already fixed, already in the version we run

**MAA issue [#17895], fix commit `b2fc6bf` (2026-08-26 16:51), confirmed to be an ancestor of
`v6.17.0-beta.7` (`compare` returns `behind_by=0`).**
We started running beta.7 with the 08-28 evening shift, and the first attempt that night succeeded.

The fix changes three things:

```cpp
// src/MaaCore/Controller/Controller.cpp
- CHECK_EXIST(m_controller, false);
- return m_controller->inject_input_event(event);
+ // 与 click/swipe 一致必须经 scale proxy，否则任务层的基准坐标未乘分辨率倍率直发设备
+ CHECK_EXIST(m_scale_proxy, false);
+ return m_scale_proxy->inject_input_event(event);
```

1. **The pinch gesture coordinates never went through the scale proxy** — the 1280×720 baseline values
   were sent straight to a 1600×900 device, so the travel was only 80% of what it should be and the
   zoom never reached its target. **That is the root cause.**
2. `InfrastInfoTask.cpp`: a single-step teleport → 20 interpolated steps (25 ms each) + hold 100 ms
   before lifting.
3. `resource/tasks/tasks.json`: `InfrastInfoZoomOutPointer1` start point `y 700 → 640`.

### It only affects non-720p devices

Scale factor = device width / 1280. Ours is 1600×900 → 1.25, so the pinch travel is cut by 20%.
**A user on native 1280×720 has a factor of 1.0; multiplying changes nothing, so they never hit it.**

So the answer to "would changing the emulator resolution avoid it" is: **yes, but it is not needed** —
beta.7 fixes it at the root, and 1600×900 is a configuration the official compatibility table lists
as 「完美支持」 for LDPlayer.
The official wording of the resolution requirement is 「仅对 **720p 以上 16:9 分辨率**支持较好」
(`docs/zh-cn/manual/device/windows.md`), and 1600×900 is well inside that range.

### Do not file another issue

#17895 already exists and is fixed and closed. Related: #17913, #17926.

---

## What follows is the evidence gathered at the time (kept for future comparison)

**Conclusion: a defect in MAA itself — not our configuration, not the emulator resolution, not the
beta build.**
The retry after each failure always succeeded, so the infrastructure shift change was never actually
skipped.

## Symptom

```
InfrastInfoTask | zoom gesture sent
InfrastInfoTask | no facility matched, attempt 1 / 2 / 3
[ERR] InfrastInfoTask | facility layout recognition failed after 3 attempts
```

## History of successes and failures (all of asst.log + asst.bak.log)

| Time | First attempt | Version |
|---|---|---|
| 08-26 15:24:37 | ❌ → 15:27:54 retry ✅ | beta.6 |
| 08-26 21:35:32 | ❌ → 21:38:55 retry ✅ | beta.6 |
| 08-26 22:58:57 | ✅ | beta.6 |
| 08-27 09:08:02 | ✅ | beta.6 |
| 08-27 21:35:12 | ❌ → 21:38:55 retry ✅ | beta.6 |
| 08-28 13:18:04 | ❌ → 13:23:56 retry ✅ | beta.6 |
| 08-28 21:35:58 | ✅ | beta.7 |

**beta.6 succeeded on the first attempt 2 times out of 6; beta.7 has exactly one sample.**
"beta.7 fixed it" does not hold statistically at all — at a 33% success rate, drawing one success is
an everyday event.

## Mechanism (source `src/MaaCore/Task/Infrast/InfrastInfoTask.cpp`)

`InfrastFacilityImageAnalyzer::analyze()` returns `return !m_result.empty();`
— **it returns false only when not one of the nine facility classes matches at either template size**.

The templates come in two **discrete fixed sizes** (`resource/tasks/tasks.json`):

| Facility | Normal template | Mini template | Threshold |
|---|---|---|---|
| 制造站 | 201×96 | 70×64 | 0.90 |
| 贸易站 | 199×93 | 71×63 | 0.90 |
| 会客室 | 95×83 | 60×43 | 0.95 |

MAA's own comment already spells out this failure mode:

> A pinch may advance only one zoom level. When the first gesture leaves the
> overview at an intermediate scale, waiting cannot make the fixed-size normal
> or mini templates match; pinch again before retrying.

## Measured (matching MAA's own templates against the failing frames)

Failing frames: `D:\ark\maa\debug\infrast\facility_layout\*_raw.png` (1280×720)

| Frame | Facility | Normal template | Mini template | Threshold |
|---|---|---|---|---|
| 08-28 | 制造站 | 0.499 | **0.814** | 0.90 |
| 08-28 | 贸易站 | 0.509 | 0.788 | 0.90 |
| 08-28 | 会客室 | 0.540 | 0.719 | 0.95 |
| 08-27 | 制造站 | 0.497 | **0.805** | 0.90 |

Multi-scale scan: 制造站 on screen is about 82×39, **stuck between 201×96 and 70×64**.

The numbers from the two days are almost identical (0.805 / 0.814), so it is the same stable
intermediate zoom state; it is only 0.09 short of the threshold, which is why it shows up
intermittently — pinch all the way and it passes, one notch short and it reads 0.81.

## Ruled out

* **Resolution**: LDPlayer9 1600×900 / DPI 240 / 16:9, and asst.log carries no resolution warning.
* **Touch mode**: `ConnectSettings.TouchMode = MiniTouch`, which supports multi-touch; the log says
  `zoom gesture sent`, not `unsupported` (the source prints the latter when multi-touch is unsupported).
* **Where the pinch lands**: `(980,180)→(650,350)` and `(300,640)→(630,370)`; on the failing frames
  both points land on empty-cell background, not on a facility card.
* **Version**: see the table above.

## Impact

A wrong value like `NumOfTrade 0` **does not affect the shift change**: `Infrast.DefaultInfrast =
user_defined`, so room iteration is driven by the custom roster. On the 08-28 evening shift round that
reported `NumOfTrade 0`, the rooms actually processed were
`Trade=[0,1,2,3] Mfg=[0,1,2,3,4] Power=[0,1,2] Dorm=[0,1,2,3,4]`, exactly the same as on every normal
evening. (A round that genuinely did nothing looks like this: 08-23 09:00 `Trade=[] Mfg=[]`.)

The cost is only about 5 extra minutes of retrying on the round that failed.

## The decisive comparison: a succeeding frame vs a failing frame (宿舍, same template, same ROI)

| Frame | Score at ×1.00 | Best scale | Threshold |
|---|---|---|---|
| 08-28 failing `facility_layout` | 0.787 ❌ | ×1.07 → 0.988 | 0.90 |
| 08-27 failing `facility_layout` | 0.752 ❌ | ×1.08 → 0.992 | 0.90 |
| 08-27 succeeding round `enter_facility` | **0.964 ✅** | ×1.02 → 0.972 | 0.90 |
| 08-26 succeeding round `enter_facility` | **0.964 ✅** | ×1.02 → 0.972 | 0.90 |

**On success the screen sits exactly at the template's native scale; on failure it is 7~8% larger.**
So a failing frame is not "zoomed all the way out and still not matching" — **the pinch did not zoom
far enough, it is one notch short**.
(On the succeeding frame the 制造站 template only scores 0.85 — 制造站 was never what carried it;
宿舍 at 0.964 is what pulled `analyze()` over the line. Do not draw conclusions from 制造站.)

**Resolution is irrelevant**: the succeeding and the failing frames both come from the same
1600×900 emulator, downsampled to 1280×720 the same way.
MAA's official requirement reads 「仅对 **720p 以上 16:9 分辨率**支持较好」
(`docs/zh-cn/manual/device/windows.md`), and 1600×900 is well inside that range;
LDPlayer is listed as 「完美支持」 in the official table. **Changing the resolution does not solve this.**

## LDPlayer's screenshot enhancement mode: it is on, and it is working (stop doubting it)

Configuration `ConnectSettings.Extras.LDPlayer.IsEnabled = True`, with runtime evidence (asst.log 21:31):

```
Loading library[libname=D:\LD-MRFZ\LDPlayer9\ldopengl64]
[ld_inst_index_=1000] [ld_pid_=8340]
LDExtras cost 24 ms
The fastest way is LDExtras , cost: 24 ms
```

**Careful not to misread this**: the `screencap | busybox nc` / `gzip -1` / `screencap -p` lines
immediately above are MAA **timing each method one by one** during its
`Try to find the fastest way to screencap` phase — it is not taking screenshots over adb. When the
timing finished it picked LDExtras (24 ms, against 238/261/496 ms for the adb methods).
On 2026-08-28 I read that timing pass as "it is using adb" and asserted "enhancement mode is off";
both were wrong.

The screenshot channel is LDPlayer's own fast direct path and the image is clean (宿舍 scores 0.964 on
the succeeding frame), **so those 7~8% are in-game zoom falling short, not a blurry screenshot.**

## Recurrence rate

4 of the 7 first attempts failed (about 57%), so **it does recur**; but the retry after all 4 failures
succeeded **4 out of 4**, at a cost of about 5 extra minutes on that round.

## Possible fixes (not carried out, awaiting the user's decision)

| Option | What it does | Risk |
|---|---|---|
| A: do nothing | Let MAA heal itself with its own retry | None. About 5 extra minutes each time |
| B: file an issue | Give upstream the match scores from this document: the pinch travel is too short / suggest adding scale tolerance or more retries | None. Slow to take effect |
| C: change the pinch coordinates locally | Edit `InfrastInfoZoomOutPointer0/1` in `resource/tasks/tasks.json`, widening the start-point spacing and narrowing the end-point spacing | **High**: ① MAA runs `ResourceIntegrityChecker` at startup (08-28 evening shift: "Integrity check passed, 9302 file(s) verified"), and the edit may be judged a failure; ② `tasks.json` gets overwritten by OTA updates |

Recommended: **A + B**. Do not do C before that is sorted out.


## 2026-08-29 evening shift (v6.17.0-beta.7): infrastructure failed again, but with different symptoms

What the `asst.log` of last night's 21:30 round actually says. First, **which parts are written in the
log and which parts I have no evidence for**.

### What the log really contains

```
21:36:20 [INF] InfrastInfoTask | zoom gesture sent
21:38:59 [INF] SubTaskError {"class":"asst::ProcessTask","first":["Infrast...
21:42:02 [INF] SubTaskError {"class":"asst::ProcessTask","first":["Infrast...
21:42:02 [ERR] asst::InfrastAbstractTask::click_clear_button clear failed
21:42:19 [TRC] asst::InfrastAbstractTask::on_run_fails | enter
21:42:21 [TRC] asst::InfrastAbstractTask::on_run_fails | leave, 2006 ms
```

The whole stretch has **37 ERR lines / 1869 WRN lines**; deduplicated, the most frequent are:

| Count | Content |
|------|------|
| ×20 | `skill has no recognition result` |
| ×7 | `Unknown task: FightSeries-OldMethodFlag` |
| ×7 | `Task FightSeries-OldMethodFlag not found` |
| ×1 | `asst::InfrastAbstractTask::click_clear_button clear failed` |
| ×1 | `asst::VisionHelper::correct_rect image is empty` |

`on_run_fails` did run, which means **the infrastructure task really did fail** — this is not
"it logged an error but got through".

### How it differs from the morning failure

The morning one was **the zoom gesture coordinates not being multiplied by the resolution factor**
(upstream #17895).
Last night there was **no zoom-related error at all** after `zoom gesture sent`; the failure points
were `click_clear_button` (the button that clears the operator selection) and 20 occurrences of
`skill has no recognition result` (the operator skill icons not being recognized).

**Whether the two share a root cause is something I have no evidence for; do not treat them as the
same thing.**
The "cannot recognize it" family of symptoms looks like it has a common origin (templates failing to
match at the current resolution), but the zoom part is already fixed in beta.7, and last night
reported no zoom error.

### Still to investigate

- `FightSeries-OldMethodFlag` is referenced 7 times but has no definition anywhere; possibly the
  program version and the resource version do not match. Not investigated.
