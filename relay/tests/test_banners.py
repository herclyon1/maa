"""鸣潮卡池：两个免 token 接口的解析。

夹具是 2026-08-31 从线上抓的真实响应：
* `wuwa_home.json`   —— 库街区 wiki 首页 getPage，裁到「唤取」两个模块
* `wuwa_notice.html` —— 官方 3.6 版本内容说明，裁到「全新角色/武器」两节

这一版的现实是：上半两个池子里**清宵是首发、达妮娅是复刻**，
而 getPage 本身分不出来——只有公告的「全新角色」一节能分。
下面的用例就是钉住这件事。

另外钉住两个已经踩过的坑：
* `imgs[1:]` 在所有 tab 里是同一组通用条目，当成角色会每池多出三个名字；
* 下一期官方公布了人的时候不许再写「约」和「官方未公布」。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.banners import parse_wuwa, parse_wuwa_preview, render  # noqa: E402

FX = Path(__file__).parent / "fixtures"
FAILED: list[str] = []


def check(what, got, want):
    if got != want:
        FAILED.append(f"{what}: 得到 {got!r}，应为 {want!r}")


def main() -> int:
    home = json.loads((FX / "wuwa_home.json").read_text(encoding="utf-8"))
    notice = (FX / "wuwa_notice.html").read_text(encoding="utf-8")
    # 真实 entryId → 名字，省得测试联网
    names = {"1536353668409655296": "清宵", "1488852222116831232": "达妮娅"}
    pools = parse_wuwa(home, lambda e: names.get(e, ""))

    check("只认角色池，武器池排掉",
          [b.name for b in pools], ["仙风玉影水天清", "予明日以谎言"])
    check("游戏名", {b.game for b in pools}, {"鸣潮"})
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

    now = datetime(2026, 8, 31, 0, 0, 0)
    fresh = [b for b in pools if b.chars == ("清宵",)]
    out = render(fresh, now,
                 {"鸣潮": (datetime(2026, 9, 10, 9, 59, 59), "景燃「身赴三途」")})
    check("在开的首发池要报", "清宵" in out, True)
    check("复刻不进报告", "达妮娅" in out, False)
    check("下一期报出人名", "景燃「身赴三途」" in out, True)
    check("官方公布了人就不许写「约」", "下一期约" in out, False)
    check("官方公布了人就不许写「未公布」", "官方未公布" in out, False)

    blind = render([], now, {"终末地": (datetime(2026, 9, 2, 12, 0, 0), "")})
    check("没公布人时必须写「约」", "下一期约" in blind, True)
    check("没公布人时必须说明未公布", "官方未公布" in blind, True)

    check("一条都没有时整段为空", render([], now, {}), "")

    print("all checks passed" if not FAILED else "FAILED: " + "; ".join(FAILED))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
