"""三个游戏的卡池解析。

夹具都是 2026-08-31 从线上抓的真实响应：
* `wuwa_home.json`      —— 库街区 wiki 首页 getPage，裁到「唤取」两个模块
* `wuwa_notice.html`    —— 官方 3.6 版本内容说明，裁到「全新角色/武器」两节
* `prts_limited.wikitext` —— PRTS「卡池一览/限时寻访」全文
* `ak_schedule.js`      —— 一图流手工维护的方舟未来排期
* `endfield_pools.json`  —— 森空岛 char-pool 的 data.list
* `endfield_notice.html` —— 官方「版本更新说明」，裁到「全新干员」和寻访两节

钉住的都是已经踩过的坑：

1. PRTS 的 URL 少了 `page=`（`[:-6]` 多切了六个字符），请求变成
   `...&format=json卡池一览/限时寻访`，回一页 HTML，方舟那几行从来没出来过。
2. getPage 的 `imgs[1:]` 在所有 tab 里是同一组通用条目，当成角色会每池多三个名字。
3. getPage 分不出首发和复刻——3.6 上半两个池子里清宵是首发、达妮娅是复刻，
   只有官方公告的「全新角色」一节能分。
4. 「联合行动」这类池子里全是老干员，不能算首发。
5. 下一期官方公布了人的时候不许再写「约」和「官方未公布」；
   只给到日期的源不许硬凑出 00:00 冒充精确时刻。
6. 「已公布但不在开」不等于「下一期」——本版上半开完了也满足这个条件，
   照那个判据会把**上一期**当成下一期报出去。公告是按时间顺序列的，
   要取在开的那位**之后**的。
"""
import json
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.banners import (  # noqa: E402
    _AK_PAGES, _PRTS, debut_only, parse_ak_schedule, parse_arknights,
    gh_raw, group_notice, newest_version, opening_tomorrow, parse_endfield,
    parse_endfield_notice, parse_wuwa, parse_wuwa_preview, render, upcoming,
)

FX = Path(__file__).parent / "fixtures"
FAILED: list[str] = []


def check(what, got, want):
    if got != want:
        FAILED.append(f"{what}: 得到 {got!r}，应为 {want!r}")


def main() -> int:
    # ── 鸣潮 ───────────────────────────────────────────────
    home = json.loads((FX / "wuwa_home.json").read_text(encoding="utf-8"))
    notice = (FX / "wuwa_notice.html").read_text(encoding="utf-8")
    names = {"1536353668409655296": "清宵", "1488852222116831232": "达妮娅"}
    pools = parse_wuwa(home, lambda e: names.get(e, ""))

    check("只认角色池，武器池排掉",
          [b.name for b in pools], ["仙风玉影水天清", "予明日以谎言"])
    check("每池只有一个角色（imgs 后几项是共用条目）",
          [b.chars for b in pools], [("清宵",), ("达妮娅",)])
    check("起始时刻按服务器时间原样解析",
          pools[0].start, datetime(2026, 8, 20, 11, 0, 0))
    check("结束时刻补到 59 秒",
          pools[0].end, datetime(2026, 9, 10, 9, 59, 59))

    debut = parse_wuwa_preview(notice)
    check("公告只给全新角色，整版上下半一次给全",
          debut, [("清宵", "仙风玉影水天清"), ("景燃", "身赴三途")])
    check("复刻不在「全新角色」那一节里",
          "达妮娅" in {w for w, _ in debut}, False)
    check("正文取不到时返回空而不是炸", parse_wuwa_preview(""), [])
    check("没有那一节时返回空", parse_wuwa_preview("<p>啥也没有</p>"), [])

    # ── 明日方舟 ────────────────────────────────────────────
    page = urllib.parse.quote(_AK_PAGES[0])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(_PRTS + page).query)
    check("PRTS 的 URL 必须带 page 参数",
          q.get("page"), ["卡池一览/限时寻访"])
    check("只读限时寻访一页（轮换池那页恒为 0 条且没有首发）",
          len(_AK_PAGES), 1)

    ak = parse_arknights((FX / "prts_limited.wikitext").read_text(encoding="utf-8"))
    check("限时寻访解析条数", len(ak), 163)
    check("最后一条是联合行动23", ak[-1].name, "联合行动23")
    check("联合行动23 在开时收录的是十个老干员", len(ak[-1].chars), 10)

    fresh = debut_only(ak)
    check("联合行动不算首发",
          [b for b in fresh if b.name == "联合行动23"], [])
    check("首发池里没有复刻",
          [b.name for b in fresh if "复刻" in b.name], [])
    check("2026 夏限是首发，且只留新干员",
          next((b.chars for b in fresh
                if b.name == "【限定寻访·夏季】车辙与风的归所"), None),
          ("予愿安洁莉娜", "珊比", "嘉辛塔"))

    sched = parse_ak_schedule((FX / "ak_schedule.js").read_text(encoding="utf-8"))
    check("一图流排期按时间正序",
          [(n, f"{d:%Y-%m-%d}", ok) for n, d, ok in sched],
          [("P3R联动", "2026-09-04", False), ("感谢庆典", "2026-11-01", False)])
    check("排期是空文本时返回空", parse_ak_schedule(""), [])

    # ── 终末地 ─────────────────────────────────────────────
    ef_pools = json.loads((FX / "endfield_pools.json").read_text(encoding="utf-8"))
    ef = parse_endfield(ef_pools, lambda gid: {"1683": "梨诺"}.get(gid, ""))
    check("终末地池名", [b.name for b in ef], ["晨星于此闪耀"])
    check("角色名要按 pcLink 里的 gameEntryId 去查", ef[0].chars, ("梨诺",))
    # 时间戳换算依赖本机时区，所以比时间戳本身，不比挂钟读数
    check("起止时间戳原样还原",
          (int(ef[0].start.timestamp()), int(ef[0].end.timestamp())),
          (1786248000, 1788300000))

    not_up = json.loads(json.dumps(ef_pools))
    for c in not_up[0]["chars"]:
        c["dotType"] = "label_type_normal"
    check("不是 UP 的角色不进报告", parse_endfield(not_up, lambda g: "梨诺"), [])

    ef_notice = (FX / "endfield_notice.html").read_text(encoding="utf-8")
    ef_debut = parse_endfield_notice(ef_notice)
    check("官方公告一次给全整版上下半的新干员和池名",
          ef_debut, [("诀", "临渊望北"), ("梨诺", "晨星于此闪耀")])
    check("公告取不到时返回空", parse_endfield_notice(""), [])
    check("没有「全新干员」那一节时返回空",
          parse_endfield_notice("<p>只有更新维护时间</p>"), [])

    # ── 「下一期」只能取在开的那位之后的 ────────────────────
    check("本版最后一个在开时，本版没有下一期了",
          upcoming(ef_debut, {"梨诺"}), [])
    check("本版第一个在开时，下一期是第二个",
          upcoming(ef_debut, {"诀"}), [("梨诺", "晨星于此闪耀")])
    check("上半开完了也不许被当成下一期",
          [w for w, _ in upcoming(ef_debut, {"梨诺"})], [])
    check("鸣潮同理：清宵在开，下一期是景燃",
          upcoming(debut, {"清宵", "达妮娅"}), [("景燃", "身赴三途")])
    check("一个都没在开时不猜",
          upcoming(debut, set()), [])

    # ── 渲染 ───────────────────────────────────────────────
    now = datetime(2026, 8, 31, 0, 0, 0)
    live = [b for b in pools if b.chars == ("清宵",)]
    out = render(live, now,
                 {"鸣潮": (datetime(2026, 9, 10, 9, 59, 59), "景燃「身赴三途」")})
    check("在开的首发池要报", "清宵" in out, True)
    check("复刻不进报告", "达妮娅" in out, False)
    check("下一期报出人名", "景燃「身赴三途」" in out, True)
    check("官方公布了人就不许写「约」", "预告　约" in out, False)
    check("官方公布了人就不许写「未公布」", "官方未公布" in out, False)

    blind = render([], now, {"终末地": (datetime(2026, 9, 2, 6, 0, 0), "")})
    check("没公布人时必须写「约」", "预告　约" in blind, True)
    check("没公布人时必须说明未公布", "官方未公布" in blind, True)
    check("有确切时刻就把时刻写出来", "09-02 06:00" in blind, True)

    dateonly = render([], now, {"明日方舟": (datetime(2026, 9, 4, 0, 0, 0),
                                            "P3R联动（排期是预测，未官宣）")})
    check("只给到日期的源不许凑出 00:00", "00:00" in dateonly, False)
    check("只给到日期时写到日", "09-04 开" in dateonly, True)

    # ── 3.7 发布后 3.6 还挂着，必须只认版本号大的那条 ──────
    check("两版并存时取版本号大的",
          newest_version([("「甲」3.6版本内容说明", "旧"),
                          ("「乙」3.7版本内容说明", "新")]), "新")
    check("顺序反过来结果不变",
          newest_version([("「乙」3.7版本内容说明", "新"),
                          ("「甲」3.6版本内容说明", "旧")]), "新")
    check("跨大版本也要比对(9.9 < 10.0)",
          newest_version([("9.9版本内容说明", "旧"),
                          ("10.0版本内容说明", "新")]), "新")
    check("一条都没有时返回空", newest_version([]), "")

    # 2026-08-31 实测：游戏机上 raw.githubusercontent 要 33 秒（超时失败），
    # jsDelivr 2.8 秒。镜像顺序是按实测速度排的，别退回去。
    mirrors = gh_raw("o", "r", "main", "a/b.js")
    check("jsDelivr 排在最前", "jsdelivr" in mirrors[0], True)
    check("raw.githubusercontent 只做最后兜底",
          mirrors[-1], "https://raw.githubusercontent.com/o/r/main/a/b.js")
    check("每条镜像都指向同一个文件",
          all(m.endswith("a/b.js") for m in mirrors), True)

    # ── 只有「明天开」的才发群 ──────────────────────────
    # 日报是晚上发的。按「24 小时内」算的话，21:30 会把后天早上六点开的
    # 也算进来——那不是明天。所以比的是日期。
    evening = datetime(2026, 8, 31, 21, 30)
    pool_nxt = {
        "终末地": (datetime(2026, 9, 2, 6, 0), "提弗洛斯"),      # 后天，不发
        "明日方舟": (datetime(2026, 9, 1, 0, 0), "P3R联动"),      # 明天，发
        "鸣潮": (datetime(2026, 8, 31, 23, 0), "景燃"),          # 今天，不发
    }
    due = opening_tomorrow(evening, pool_nxt)
    check("只留明天开的", [g for g, _, _ in due], ["明日方舟"])
    check("后天开的不算明天",
          "终末地" in {g for g, _, _ in due}, False)
    check("今天开的也不算明天（24 小时内会算错）",
          "鸣潮" in {g for g, _, _ in due}, False)
    check("一个都没有时返回空", opening_tomorrow(evening, {}), [])

    two = opening_tomorrow(evening, {
        "明日方舟": (datetime(2026, 9, 1, 0, 0), "P3R联动"),
        "鸣潮": (datetime(2026, 9, 1, 11, 0), "景燃「身赴三途」")})
    check("同一天两个游戏换池都要留下，按时刻排",
          [g for g, _, _ in two], ["明日方舟", "鸣潮"])

    title, body = group_notice(two)
    check("群通知标题点名是哪几个游戏",
          title, "🎴 明天开新卡池：明日方舟、鸣潮")
    check("只给到日期的不凑 00:00", "00:00" in body, False)
    check("有时刻的写出时刻", "09-01 11:00" in body, True)
    check("人名带上", "景燃「身赴三途」" in body, True)
    check("没有要播的就不发", group_notice([]), ("", ""))

    check("一条都没有时整段为空", render([], now, {}), "")

    # ── 只报最高稀有度（用户 2026-09-03）────────────────────
    from ark_relay.banners import parse_endfield_notice, six_star_only
    notice_html = "<p>■ 全新干员 6星干员【提弗洛斯】、5星干员【噗切娜】 ■ 全新武器 …</p><p>1.「冬猎」特许寻访 · 寻访说明：6星干员【提弗洛斯】获取概率提升</p>"
    check("终末地公告：5 星赠送角色不进首发名单", parse_endfield_notice(notice_html), [("提弗洛斯", "冬猎")])
    fake_prts = lambda n: {"予愿安洁莉娜": "|稀有度=5", "珊比": "|稀有度=5", "嘉辛塔": "|稀有度=4"}.get(n, "")
    b6 = Banner("明日方舟", "车辙与风的归所", ("予愿安洁莉娜", "珊比", "嘉辛塔"), datetime(2026, 8, 1), datetime(2026, 8, 15))
    check("方舟池只留六星（PRTS 稀有度 5=六星）", six_star_only(b6, fake_prts).chars, ("予愿安洁莉娜", "珊比"))
    check("稀有度查不到的名字去掉，不冒充", six_star_only(Banner("明日方舟", "x", ("无名",), datetime(2026, 8, 1), datetime(2026, 8, 15)), fake_prts).chars, ())

    # ── 按游戏分块，每家一个样（用户 2026-09-02）──────────────
    both = render(live, now, {"鸣潮": (datetime(2026, 9, 10, 9, 59, 59), "景燃「身赴三途」"),
                              "明日方舟": (datetime(2026, 9, 4, 0, 0, 0), "P3R联动（排期是预测，未官宣）")})
    lines = both.splitlines()
    check("标题", lines[0], "🎴 卡池")
    check("游戏顺序按日报顺序：方舟在前", lines.index("明日方舟") < lines.index("鸣潮"), True)
    check("方舟没有在开的 UP 就没有「当期」行",
          any(l.startswith("· 当期") for l in lines[lines.index("明日方舟") + 1:lines.index("鸣潮")]), False)
    check("鸣潮有当期也有预告",
          [l.split("　")[0] for l in lines[lines.index("鸣潮") + 1:]], ["· 当期", "· 预告"])
    check("当期带结束时刻", "（09-10 09:59 结束）" in both, True)

    print("all checks passed" if not FAILED else "FAILED: " + "; ".join(FAILED))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
