"""OK-WW 的本地补丁：贴得上、幂等、认不出就别动、坏了要还原。

为什么值得测：这套东西一年也许只在「OK-WW 刚更新完」那一刻跑几次，
出错的那次多半没人盯着。2026-08-26 就有一次——`service.py` 漏了一行
`import okww_patch`，整段代码从来没执行过，而日志里安静得像它成功了。

这里用临时目录造一份「上游原样」的文件，跑真的 ensure_patches，
再回读文件内容验收。不 mock 写盘那一步：写坏文件正是要防的事故。
"""
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import okww_patch                       # noqa: E402

# 「故意改坏」那个用例会让 py_compile 抛异常，模块用 exc_info 记了一整段
# traceback。它是预期内的，打在测试输出最上面只会让人以为测试炸了。
logging.getLogger("ark.okww_patch").setLevel(logging.CRITICAL)

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


UPSTREAM_DAILY = '''class DailyTask:
    def run(self):
        self.claim_daily()

        self.claim_mail()
        self.sleep(1)
        self.claim_battle_pass()
        self.run_additional_tasks()
        self.log_info('Daily Task Completed', notify=True)
'''

UPSTREAM_DOMAIN = '''import re


from ok import Logger
from src.task.BaseCombatTask import BaseCombatTask, NotInCombatException, CharDeadException
from src.task.WWOneTimeTask import WWOneTimeTask


class DomainTask:
    def farm_in_domain(self, must_use=0):
        while True:
            try:
                self.combat_once()
                self.sleep(3)
                self.walk_to_treasure()
                self.pick_f(handle_claim=False)
            except (NotInCombatException, CharDeadException):
                self.log_info('farm_in_domain: death recovered, exiting domain')
                self.make_sure_in_world()
                return False, must_use
'''


# 巢穴补丁是整文件替换 + 哈希守卫，所以「上游原样」必须真的是参照的那一份，
# 随手编一段假的会被守卫正确地拒绝（那反而说明守卫是好的）。
UPSTREAM_COMBAT = '''import time


class BaseCombatTask:
    def _choose_switch_target_by_buff_time(self, current_char, candidates):
        if not candidates:
            return current_char
        return self._switch_rule_3_target(candidates)
'''

UPSTREAM_NEST = (Path(__file__).resolve().parents[1]
                 / "ark_relay" / "okww_files"
                 / "NightmareNestTask.upstream.py").read_text(encoding="utf-8")

_UNUSED_NEST_SAMPLE = '''from src.task.WWOneTimeTask import WWOneTimeTask


class NightmareNestTask:
    def __init__(self):
        self._unreachable_nests = set()
        self._nest_tab_of_current_nest = 'go_nest'

    def run(self):
        self._unreachable_nests.clear()
        WWOneTimeTask.run(self)
        self.ensure_main(time_out=30)
        self._init_queue()
        self.log_info('opened gray_book_boss')
        while nest := self.get_nest_to_go():
            self.combat_nest(nest)
        self.ensure_main(time_out=30)

    def run_capture_mode(self):
        self._unreachable_nests.clear()
        WWOneTimeTask.run(self)
        self.ensure_main(time_out=30)
        self._init_queue()
        self.log_info('opened gray_book_boss')
        while nest := self.get_nest_to_go():
            self.combat_nest(nest)
            if self._capture_success:
                break
        self.ensure_main(time_out=30)
'''


def _make(root: Path, daily=UPSTREAM_DAILY, domain=UPSTREAM_DOMAIN,
          nest=UPSTREAM_NEST, combat=UPSTREAM_COMBAT) -> Path:
    d = root / "data" / "apps" / "ok-ww" / "working" / "src" / "task"
    d.mkdir(parents=True, exist_ok=True)
    (d / "DailyTask.py").write_text(daily, encoding="utf-8")
    (d / "DomainTask.py").write_text(domain, encoding="utf-8")
    (d / "NightmareNestTask.py").write_text(nest, encoding="utf-8")
    (d / "BaseCombatTask.py").write_text(combat, encoding="utf-8")
    return d


def test_applies(tmp: Path) -> None:
    print("[贴得上]")
    d = _make(tmp)
    notes = okww_patch.ensure_patches(tmp)
    check("四条补丁都报告贴上了", len(notes), 4)

    daily = (d / "DailyTask.py").read_text(encoding="utf-8")
    check("附加任务排到了领奖前面",
          daily.find("run_additional_tasks") < daily.find("claim_daily"), True)

    domain = (d / "DomainTask.py").read_text(encoding="utf-8")
    check("WaitFailedException 进了 except",
          "NotInCombatException, CharDeadException, WaitFailedException" in domain, True)
    check("import 也补上了",
          "from ok import Logger, WaitFailedException" in domain, True)
    check("只改一处 import，没波及别的 from ok",
          domain.count("from ok import"), 1)

    nest = (d / "NightmareNestTask.py").read_text(encoding="utf-8")
    patched = (Path(__file__).resolve().parents[1] / "ark_relay" / "okww_files"
               / "NightmareNestTask.patched.py").read_text(encoding="utf-8")
    check("整份换成了我们的版本", nest == patched, True)
    check("允许续刷（不再要求 已击败 == 0）",
          any(l.lstrip().startswith("if numerator != denominator")
              for l in nest.splitlines()), True)
    check("带了「只刷指定点位」", "Only Farm These Nests" in nest, True)

    combat = (d / "BaseCombatTask.py").read_text(encoding="utf-8")
    check("主C饿死兜底已贴上", "_starved_main_dps_target" in combat, True)
    check("兜底排在原逻辑之前（否则等于没加）",
          combat.find("_starved_main_dps_target(candidates)")
          < combat.find("_switch_rule_3_target"), True)


def test_idempotent(tmp: Path) -> None:
    print("[幂等：第二次什么都不做]")
    _make(tmp)
    okww_patch.ensure_patches(tmp)
    check("第二次没有任何动作", okww_patch.ensure_patches(tmp), [])


def test_refuses_unknown(tmp: Path) -> None:
    """上游改了结构就必须停手并出声——硬替换只会把文件改坏。"""
    print("[认不出上游就不动，而且要出声]")
    d = _make(tmp, domain="import re\n\nfrom ok import Logger\n\n# 上游重写过了\n")
    before = (d / "DomainTask.py").read_text(encoding="utf-8")
    notes = okww_patch.ensure_patches(tmp)
    check("文件一个字都没动",
          (d / "DomainTask.py").read_text(encoding="utf-8"), before)
    check("有一条「贴不上了」的告警",
          any("贴不上了" in n for n in notes), True)


def test_reverts_on_syntax_error(tmp: Path) -> None:
    """写进去不等于对。语法坏了必须还原，否则整个日常任务起不来。"""
    print("[改坏了要还原]")
    d = _make(tmp)
    bad = okww_patch._DOMAIN_NEW + "\n   this is not python("     # noqa: SLF001
    orig_new = okww_patch._DOMAIN_NEW                             # noqa: SLF001
    okww_patch._DOMAIN_NEW = bad                                  # noqa: SLF001
    try:
        before = (d / "DomainTask.py").read_text(encoding="utf-8")
        notes = okww_patch.ensure_patches(tmp)
        check("已经还原成上游版",
              (d / "DomainTask.py").read_text(encoding="utf-8"), before)
        check("而且说了「已还原」", any("已还原" in n for n in notes), True)
    finally:
        okww_patch._DOMAIN_NEW = orig_new                         # noqa: SLF001


def test_missing_dir_is_quiet(tmp: Path) -> None:
    print("[没配 okww 目录就安静跳过]")
    check("None 直接返回空", okww_patch.ensure_patches(None), [])


def main() -> int:
    for fn in (test_applies, test_idempotent, test_refuses_unknown,
               test_reverts_on_syntax_error, test_missing_dir_is_quiet):
        with tempfile.TemporaryDirectory() as t:
            fn(Path(t))
    # ── 2026-08-27：点进列表才 2 秒就 OCR，读不到 → 残像聚落整段跳过 ──
    root = Path(__file__).resolve().parents[1]
    nest_src = (root / "ark_relay" / "okww_files"
                / "NightmareNestTask.patched.py").read_text(encoding="utf-8")
    wanted = nest_src.split("def _wanted_nest_rows")[1].split("\n    def ")[0]
    check("有等待上限常量", "NEST_LIST_TIMEOUT" in nest_src, True)
    check("等到能读出计数才判断", "match=self.count_re" in wanted, True)
    # OCR 读出来是「落渊南丘残象聚落」，配置写的是「落渊南丘」——
    # ocr(match=...) 是精确相等，必须改成包含匹配。
    check("点位名用包含匹配", "if name in (box.name or '')" in wanted, True)
    check("不再用 ocr(match=name)", "match=name" in wanted, False)
    check("找不到点位要报错并通知", "notify=True" in wanted, True)
    check("找不到时打印实际读到的名字", "实际读到的是" in wanted, True)

    # 护栏原本只认上游和当前，导致我们自己的修复永远推不上去
    patch_src = (root / "ark_relay" / "okww_patch.py").read_text(encoding="utf-8")
    check("有历史版本清单", "_NEST_KNOWN_OURS" in patch_src, True)
    check("护栏检查里用上了它",
          "_sha(cur) not in _NEST_KNOWN_OURS" in patch_src, True)

    # ── 2026-08-27：补丁以前只在开机预更新里贴，白天部署完要等第二天才生效 ──
    svc = (Path(__file__).resolve().parents[1] / "service.py").read_text(encoding="utf-8")
    head = svc.split("服务模式启动")[1][:1400]
    check("服务一启动就贴补丁", "ensure_patches(okww_at_boot)" in head, True)
    check("贴不上也不挡住服务启动", "服务照常继续" in head, True)

    # ── 明日安排：必须反映真正生效的配置，不是母本 ──
    plan_src = (root / "ark_relay" / "plan.py").read_text(encoding="utf-8")
    check("快速配置会覆盖母本", "_okww_quick_overrides" in plan_src, True)
    check("覆盖后才算 bits", "daily = {**daily, **quick}" in plan_src, True)
    check("认得出 OK-WW 的路径字段",
          'info_node.get("RootPath")' in plan_src, True)
    check("MaaEnd 自动采集会预告", "_maaend_extra_bits" in plan_src, True)
    # 汇报里不许出现英文任务名，译文取 OK-WW 自带的官方语言包
    check("用官方语言包翻译", "_okww_zh" in plan_src, True)
    check("译文来自 ok.po", "LC_MESSAGES" in plan_src, True)
    check("附加任务也翻译", "zh.get(str(a), str(a))" in plan_src, True)

    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())

