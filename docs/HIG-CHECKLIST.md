# The phone page against Apple's Human Interface Guidelines

Two sources, both from Apple, both read 2026-09-14:

1. **The HIG** - https://developer.apple.com/design/human-interface-guidelines,
   the live site, read through its JSON endpoints (lists-and-tables, toggles,
   tab-bars, segmented-controls, materials, layout, typography, color, feedback,
   settings, designing-for-ios, motion) - the edition that describes Liquid
   Glass, i.e. iOS 26 and later. It gives the rules, mostly not the numbers.
2. **The iOS and iPadOS 27 UI kit** (Apple's Figma design kit, the user's copy,
   file key in `~/.config/ark/push.env` as `FIGMA_IOS_KIT`), read through the
   Figma REST API (`/v1/files/<key>/nodes?ids=<node>`). It gives the numbers.
   The node ids in the table are the components the value was read from:
   Row `550:50430`, Section Title `50:56535`, Grouped Table Footer `35:55757`,
   Separator `5469:7924`, Toggles `5433:19059`, Tab Bar `3:70967`,
   Tab Bar Button `5735:65307`, Row-Button `550:49677`, Text styles `5418:17464`.

3. **The simulator itself** - **Simplified Chinese** (so Settings uses the same
   PingFang metrics as the page). The numbers below were measured on iPhone 17 Pro
   Max / iOS 26.5, Settings › 辅助功能 and › 动态效果, pixel by pixel on 2026-09-15
   00:13; that runtime was deleted the same morning and the device is now iPhone
   18 Pro Max / iOS 27.0 (`8E793B8A-922B-46BC-86E2-E0F2BE845CA5`) - re-measure
   there before trusting a number that iOS 27 could have changed. Where the kit and the
   simulator disagree, the simulator wins: card margin 20.33, corner 26-27, row
   53.33, text inset 20 (kit: 16), separator hairline inset 20 on both sides
   (kit: left only), toggle 63×28 inset 18, header 17 semibold 28 above / 6 below,
   footer 13/18 with 6 above / 24 below, cards 35 apart when nothing is between
   them, large title ink at the 20 margin. WebKit's own `switch` control renders
   71×31, so it is scaled by .887 to the Settings size.

A rendering check runs in the iOS 27.0 simulator (Xcode 27.0, iPhone 18 Pro Max)
next to the Settings app; `scripts/mac/sf-symbols-export.swift` pulls the tab
symbols from the system font. Each rule below is the source's wording condensed,
followed by what `web/index.html` / `web/app.js` does about it. A change to the
page that breaks a line here is a regression.

| HIG page | Rule | On the page |
|---|---|---|
| Lists and tables; kit Section Title `50:56535`, Footer `35:55757`, Row `550:50430` | iOS grouped style: headers, footers and extra space separate groups. Kit: header 17pt semibold secondary label, 9pt below it; footer 13/18 secondary label, padding 8/16/6; row 52pt, 16pt side padding, title 17/22, subtitle 15/20 | `h2` 17px/600 `--dim` padding 28px 20px 6px; `.foot` 13px/18px padding 6px 20px 24px; `.row` min-height 53.33, padding 15.5px 18px 15.5px 20px, label 17/22, hint 15/20; hairline 1 device pixel inset 20 both sides; white inset card `.group` (26px radius, measured in Settings) |
| Lists and tables | Keep item text succinct; avoid over-large rows | one setting per row, hint under the name in 13pt; long option sets fold behind 「已选 N/M ›」 (progressive disclosure) |
| Toggles; kit `5433:19059` | A toggle chooses between two opposing values; make the states obvious, not by colour alone. Kit (iOS 26): track 64×28 radius 100, on #34c759, off `rgba(60,60,67,.3)`, knob a 38×24 white pill | every on/off setting (config and relay) is the same 63×28 `.sw` with a 38×24 pill knob. Its motion was measured on the simulator's own recording of Settings › 动态效果 › 首选非闪动光标 (2026-09-15 04:58, `simctl io recordVideo`, sampled at 120/s): the whole flip ≈0.34 s - the knob stretches and lands on the far side within ≈0.1 s, relaxes back to 38pt over the next ≈0.2 s, the track cross-fades green↔grey over ≈0.2 s. The page's `knob-on/knob-off` keyframes (0.34 s, stretch to 46 at 30 %) and the 0.2 s track transition reproduce that; recorded the same way, the page's flip lands and cross-fades within ≈50 ms of the native one; WebKit's own `switch` control was tried and dropped - 71×31 and no motion; knob position + green; nothing on/off is a button. Flipping one does not send anything: it joins the 待保存 list and goes out after 保存修改, like every config row |
| Tab bars | Navigation only, not actions; keep tabs visible; single-word labels; use the number of tabs the app needs but 「it's generally easier to navigate among fewer tabs」; avoid overflow (when the width runs out iOS turns the trailing tabs into a More tab) | five tabs 状态 · 方舟 · 终末地 · 鸣潮 · 手机, always visible, floating at the bottom. There is no hard cap of five for tab bars (that number is the HIG's guidance for *segmented controls* on iPhone); with more games than fit, the plan is a 游戏 tab holding a list with detail pages (which then also gets the back button and gesture) |
| Materials (Liquid Glass) | Controls and navigation float above content in Liquid Glass; do not use it in the content layer; use it sparingly | only the tab bar, the save bar and the toast are glass (translucent + blur + specular edge); cards are solid standard material |
| Layout | Order by importance, align, group related items, differentiate controls from content | 16pt margins, name left / control right on one baseline, hairline separators inset to the text, min 44pt row height |
| Typography; kit text styles `5418:17464` | Large Title 34/41, Body 17/22, Subheadline 15/20, Footnote 13/18, Caption 2 11/13; system font | `h1` 34/700, row names 17/22, values 17, hints 15/20, footers and receipts 13/18, tab labels 10/12 (kit tab button), `-apple-system` first |
| Color; kit Colors `5707:28659`, Row-Button `550:49677` | Use system colours; support Dark Mode. Kit: tint #0088ff, destructive #ff383c, disabled #aeaeb2, secondary label `rgba(60,60,67,.6)`, separator `rgba(60,60,67,.29)`, green #34c759 | `:root` tokens `--accent:#0088ff`, `--bad:#ff383c`, `--dim:rgba(60,60,67,.6)`, `--line:rgba(60,60,67,.29)`, `--ok:#34c759`, grouped background #f2f2f7 / black; dark values under `prefers-color-scheme` |
| Feedback | Integrate status feedback near the item; confirm significant actions; alerts only for critical, actionable information | every order shows 「已寄出 … 等回执」 under its own row and clears on the machine's receipt; a toast confirms sends; `confirm()` only before spending sanity/波片 or stopping everything |
| Settings | Minimise settings; respect systemwide settings, no redundant versions | the 外观 group (light/dark override, accent colour) was removed 2026-09-14; the page follows the system appearance |
| Designing for iOS | Limit onscreen controls; reachable controls in the middle/bottom | one page per tab; the tab bar and save bar at the bottom |

| Tab bars; kit Tab Bar `3:70967`, Tab Bar Button `5735:65307` | Consider SF Symbols for tab icons; include labels. Kit: glass capsule 62pt high, buttons 72×54 with padding 8/6/7, a 28pt symbol line, label 10pt semibold; selected = capsule #ededed (light) / #121212 (dark) with tint; unselected #1a1a1a / #f5f5f5 | `nav.tabs .seg` 62px capsule with 4px inset, buttons min-width 72 height 54 padding 6px 8px 7px, `.ico` 28×28, label 10px/600, `.glide` capsule `--tabsel`, `--tab` for unselected; 状态/手机 are SF Symbols exported from the system font by `scripts/mac/sf-symbols-export.swift` as CSS masks (`TAB_ICONS`: gauge.with.dots.needle.67percent, iphone); the three game tabs show the games' own icons (`TAB_IMAGES`, desaturated until selected) - his 09-15 order after a morning with shield/mountain/waves (「毫不相关」) |
| Motion | Add motion purposefully; brief and precise; avoid motion on frequent interactions; make it optional | the selection capsule slides in the tab bar (0.28s); tab content switches instantly (a cross-fade read as 「闪一下」 and was removed); switches and pressed rows use the system-like 0.2s; everything is off under `prefers-reduced-motion` |
| Buttons; kit Row-Button `550:49677` | Full-width text rows in a group; destructive in red. Kit: 52pt row, 17pt regular, text left-aligned, tint / #ff383c destructive / #aeaeb2 disabled | `.acts button` 52px, 17/22, `text-align:left`, `--accent`; `.danger` = `--bad`; disabled = #aeaeb2; stacked full-width rows with inset hairlines (no side-by-side grid - its middle divider never lined up); the 复制免输入链接 row is one of these, not a pill beside a label |

| 状态 tab blocks (2026-09-15) | see PHONE-NATIVE-REFERENCES.md | device card = Find My › Devices card structure (icon, name, status line) on the Settings card metrics; notice cards = Health › 摘要 (inset 16, caption 13 + hairline, title 17 semibold, body 15 secondary, tinted capsule button 30 high, cards 10 apart); action tiles = Reminders' 2×2 tile geometry (two columns, 8 gap, 80 high, radius 16) with Find My's tile look (28pt coloured circle + SF Symbol, 15 semibold title, 13 secondary subtitle); 明日安排 = Settings rows instead of a `<pre>` |

| Number tiles (2026-09-15) | Reminders' 2×2 tiles | the page asks 森空岛 (明日方舟/终末地 sanity, requests signed in the browser - `web/stamina.js` ports `skland.sign_headers`) and 库街区 (鸣潮 waveplate) itself; both APIs allow cross-origin calls (preflights verified 2026-09-15). Only Skland's token→cred exchange cannot run in a browser, so the relay hands its session over in the snapshot (`密钥.sk`); the Kuro token/did are pasted on the 手机 tab. Read only on page open, pull to refresh and the 刷新 tile; a reading younger than a minute is reused; no timer; the tile is Reminders' own: white card 80.33 high radius 16, a 32pt coloured circle with a white symbol top-left, the count 24pt bold in the label colour top-right with the limit as a grey suffix, the name 15pt semibold grey at the bottom; the tile's symbol is the *resource* (brain.fill for 理智, cube.fill for the crystal cube 波片) because the tab bar already carries each game's own icon - his 09-15 order: the tab shows the game, the two must not repeat. The gradient-filled version of 09-15 morning was Shortcuts' tile, i.e. 「tap to run」, on a number that is only read - replaced. Live values: Skland's Arknights `ap.current` is frozen at `lastApAddTime` (the page showed 2/210 all morning) - the page adds 1 per 6 min up to `max`; Endfield's `curStamina` is live (7.2 min a point by `maxTs`); Kuro's `akiBox/baseData.energy` is frozen too - the page reads `gamer/widget/game3/refresh` (`energyData.cur/total/refreshTimeStamp`, CORS verified 09-15) |
| App icons (2026-09-15) | Apple's Icon Composer (Xcode 26 › Open Developer Tool) | the home-screen icon is an Icon Composer document (`data/icon-source/remote.icon`: system blue gradient + the `gamecontroller.fill` symbol as a white Liquid Glass layer) exported with 「Export Icon as PNG」 at 1024, the transparent corners filled with the icon's own gradient so the file is a full-bleed square (iOS masks it itself); `apple-touch-icon.png` 180, `icon-192/512.png` |
| Typography (Dynamic Type) | `-apple-system-body` | the root font is the system Body text style and every size is in em of it, so the page follows Settings › 显示与亮度 › 文字大小 like a native list |
| Navigation bars | large title collapses into a compact bar on scroll | `.topbar` (glass, 44pt, 17 semibold centred) is driven by scroll position: its glass and hairline appear as content slides under it (`--bar`); measured on the simulator's recording of Settings (2026-09-15 05:04, slow drag) the large title fades out while sliding under the bar and the small title fades in only after it is gone - so `--big` fades the large title over ~90 % of its height and `--title` starts the small one at the 50 % mark (no cross-fade, no jump) |
| Refresh | pull to refresh with UIActivityIndicatorView | touch pull past 72pt at the top grows the eight-bar indicator; release spins it and calls `ping()`; the 刷新 tile shows the same indicator in place of its symbol while the machine is being asked |

Not done (and why): the swipe-back gesture belongs to a navigation stack
(pushed detail views); this page has tabs, not a stack, and the HIG tab bar has
no back gesture. If a detail page is ever added, it gets a real back button and
the gesture with it.
