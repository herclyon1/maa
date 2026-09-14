# Which Apple app each block of the phone page copies

Surveyed 2026-09-15 00:30-00:50 Tokyo, on the user's order 「集百家之所长，不要漏掉
别的原生软件」. Two sources, and they are not interchangeable:

- **The iOS simulator (Simplified Chinese)** - the only place the *numbers* (row
  height, insets, fonts, toggle size) may come from, because the page renders at
  phone width with PingFang. Measured on iOS 26.5 / iPhone 17 Pro Max; since
  2026-09-15 08:20 the only device is **iPhone 18 Pro Max, iOS 27.0**
  (`8E793B8A-922B-46BC-86E2-E0F2BE845CA5`, same 440×956 pt) - the 26.5 runtime
  and its devices were deleted on the user's order, the page's localStorage
  (mailbox, PIN, game credentials) was carried over. Measured pages are listed in
  HIG-CHECKLIST.md. Apps present: Settings, Health, Shortcuts, Reminders, Fitness,
  Maps, Contacts, Calendar, Passwords, Wallet, Watch, Messages, Files, Safari.
  Absent: Home, App Store, Music, Mail, Clock, Weather, Notes, Camera.
- **macOS 26 (this Mac, English)** - a source of *patterns* only: the same app
  families exist, but they lay out for a desktop (13pt text, sidebars, toolbars),
  so nothing is measured there. Screenshotted in the background with the
  computer-use tools: Home, Find My, Weather, Clock, Stocks, Reminders, Calendar,
  App Store (Music/Books/Podcasts are blocked for automation; Shortcuts on the Mac
  is flagged as an IDE and was not opened - the simulator has it).

What each app turned out to offer, and what the page takes from it:

| App (where) | What it shows | Taken for |
|---|---|---|
| Settings › 动态效果 / 辅助功能 (simulator) | inset grouped list: rows, toggles, inline pickers, headers, footers, button rows | the three game tabs, the 手机 tab, and every configuration row on the 状态 tab - **measured, applied** |
| Health › 摘要 (simulator, after the onboarding) | notice cards: small grey caption + close, bold one-liner, grey explanation, tinted capsule button; 「置顶」 cards: coloured symbol + name + chevron, big value below | 机器状态 card (在线/关机 · 最后状态 · one button 「刷新」); failure card (「路线 16 没走通」 + 「看证据」) |
| Shortcuts › 资料库 (simulator) | white background, grey rounded action tiles (icon + name), tap to run, 20pt margins, 3-tab glass bar | the action block on 状态: 让它现在跑一趟 / 跳过它下一趟 / 开始刷 / 停止一切 (red) |
| Reminders sidebar (Mac; identical tiles on iOS) | 2×2 summary tiles: symbol top-left, big number top-right, label below, one colour per tile | the numbers on 状态: 今天跑了几趟 / 下一趟几点 / 理智 / 波片 |
| Weather (Mac) | city list rows with a big value on the right; dashboard cards with an icon+caption header | same family as the Health cards; confirms the caption-in-card pattern |
| Clock › Timers (Mac) | big duration display, a label field, Start/Cancel | the 刷声骸 block (boss + 刷到几点 + 开始刷) stays a Settings form; the timer form is the same idea but desktop-shaped |
| Calendar (Mac) | month grid | nothing - the 排班 list stays a Settings-style list |
| App Store (Mac) | editorial cards with a small uppercase caption | nothing beyond the caption pattern already covered |
| Home (Mac) | **empty** without accessories - only a 「Discover Home」 banner | nothing measurable; HomeKit Accessory Simulator (Additional Tools for Xcode) would be needed to see tiles |
| Find My (Mac) | **empty** without iCloud - 「Me · Locating…」 | the device card (status line + 「x 分钟前」 + action buttons) is exactly the 机器状态 idea, but cannot be seen here |
| Stocks (Mac) | welcome screen only on first launch | nothing |

Rule: a block copies one app; the numbers of that block come from the simulator
measurement of that app (or, when the app is not in the simulator, from the
closest one that is - Reminders' tiles are measured on the simulator's Reminders).
