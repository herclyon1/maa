# The phone page against Apple's Human Interface Guidelines

Source: https://developer.apple.com/design/human-interface-guidelines (read
2026-09-14 through the site's JSON endpoints: lists-and-tables, toggles,
tab-bars, segmented-controls, materials, layout, typography, color, feedback,
settings, designing-for-ios). Each rule below is the HIG's wording condensed,
followed by what `web/index.html` / `web/app.js` does about it. A change to the
page that breaks a line here is a regression.

| HIG page | Rule | On the page |
|---|---|---|
| Lists and tables | iOS grouped style: headers, footers and extra space separate groups | `section` = grey 13pt header above a white inset card (`.group`, 22pt radius); explanatory text is grey footer text, not a box |
| Lists and tables | Keep item text succinct; avoid over-large rows | one setting per row, hint under the name in 13pt; long option sets fold behind 「已选 N/M ›」 (progressive disclosure) |
| Toggles | A toggle chooses between two opposing values; make the states obvious, not by colour alone | every on/off setting (config and relay) is the same 51×31 switch, knob position + green; nothing on/off is a button |
| Tab bars | Navigation only, not actions; keep tabs visible; single-word labels; avoid overflow (iPhone: at most five) | five tabs 状态 · 方舟 · 终末地 · 鸣潮 · 手机, always visible, floating at the bottom; actions live in the content as buttons |
| Materials (Liquid Glass) | Controls and navigation float above content in Liquid Glass; do not use it in the content layer; use it sparingly | only the tab bar, the save bar and the toast are glass (translucent + blur + specular edge); cards are solid standard material |
| Layout | Order by importance, align, group related items, differentiate controls from content | 16pt margins, name left / control right on one baseline, hairline separators inset to the text, min 44pt row height |
| Typography | Large Title 34, Body 17, Subheadline 15, Footnote 13; system font | `h1` 34/700, row names 17, values 17, hints and headers 13, `-apple-system` first |
| Color | Use system colours; support Dark Mode | Apple's palette as `:root` tokens (blue #007AFF, green #34C759, red #FF3B30, grey #8E8E93, grouped background #F2F2F7 / black); dark values under `prefers-color-scheme` |
| Feedback | Integrate status feedback near the item; confirm significant actions; alerts only for critical, actionable information | every order shows 「已寄出 … 等回执」 under its own row and clears on the machine's receipt; a toast confirms sends; `confirm()` only before spending sanity/波片 or stopping everything |
| Settings | Minimise settings; respect systemwide settings, no redundant versions | the 外观 group (light/dark override, accent colour) was removed 2026-09-14; the page follows the system appearance |
| Designing for iOS | Limit onscreen controls; reachable controls in the middle/bottom | one page per tab; the tab bar and save bar at the bottom |

Not done (and why): SF Symbols in the tab bar - the page is a web page without
the symbol font; text labels only, which the HIG allows (「Include tab labels」).
Swipe-back between pages does not exist because there is no navigation stack.
