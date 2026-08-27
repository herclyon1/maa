import re
import cv2
from dataclasses import dataclass

from ok import Logger
from src.task.BaseCombatTask import BaseCombatTask, CharRevivedException
from src.task.WWOneTimeTask import WWOneTimeTask

logger = Logger.get_logger(__name__)
# 只刷指定点位。上游没有这个能力：find_nest 扫到哪个算哪个，
# 想单独补某一个没打满的点位做不到（见 ok-oldking/ok-wuthering-waves#1622）。
ONLY_NESTS = 'Only Farm These Nests'
# 等点位列表渲染出来的秒数上限。够长能盖住加载慢，
# 又不至于在列表真的空时把任务拖死。
NEST_LIST_TIMEOUT = 15
# 计数框允许比名字框低几个行高（同一张卡片内）。
# 2026-08-27 在游戏里实测的坐标：
#     落渊南丘残象聚落  y=300 h=35  → 行中心 317.5
#     已击败残象：0/41  y=373 h=30  → 行中心 388.0     差 70.5px ≈ 2.35 行高
#     下一个点位 盲望之塌 y=523              距南丘名字 148px ≈ 4.9 行高
# 所以 4 行高（120px）既盖得住 2.35，又够不到 4.9，不会串到下一个点位。
# 原来写死 1 行高，永远配不上——名字和计数根本不在同一行。
NEST_ROW_SPAN = 4

TRAVEL_FEATURES = ['fast_travel_custom', 'gray_teleport', 'remove_custom']
CONFIRM_FEATURES = ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter']


@dataclass
class NestTarget:
    box: object
    cache_key: str
    # 已击败数。允许续刷未清空的点位之后，同一个 cache_key 会反复出现，
    # 靠它才能分清「打出了进展」和「原地空转」。
    progress: str = ""


class NightmareNestTask(WWOneTimeTask, BaseCombatTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': True}
        self.trigger_interval = 0.1
        self.target_enemy_time_out = 10
        self.name = "🌙 Nightmare Nest Task"
        self.description = "Auto Farm all Nightmare Nest"
        self.support_schedule_task = True
        self.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        self.queues = []
        self._capture_success = False
        self._capture_mode = False
        self._unreachable_nests = set()
        self._attempted_nests = set()
        self._nest_tab_of_current_nest = 'go_nest'
        self.default_config.update({'Which to Farm': ['Nightmare Purification', 'Tacet Discord Nest'],
                                    ONLY_NESTS: ''})
        self.config_type['Which to Farm'] = {'type': "multi_selection",
                                             'options': ['Nightmare Purification', 'Tacet Discord Nest']}
        self.config_description[ONLY_NESTS] = (
            '只刷指定的点位，填名字里认得出的一段即可，多个用逗号隔开，'
            '例如「落渊南丘」。留空＝按原来的行为刷全部。')

    def run(self):
        self._capture_mode = False
        self._capture_success = False
        self._unreachable_nests.clear()
        self._attempted_nests.clear()
        WWOneTimeTask.run(self)
        self.ensure_main(time_out=30)
        self._init_queue()
        self.log_info('opened gray_book_boss')
        while nest := self._next_nest_with_progress():
            self.combat_nest(nest)
        self.ensure_main(time_out=30)

    def _next_nest_with_progress(self):
        """取下一个巢穴；同一个巢穴打完计数没动就不再重试。

        `find_nest()` 会一直挑没打满的巢穴，所以一局打完计数没涨的话，
        下一轮它还会被选中——形成无限循环。队伍打不过挑战时最明显：
        游戏弹「挑战失败」（提示提升角色/武器/声骸/技能等级），
        而这个界面 OK-WW 并不认识，于是每两分钟原地重进一次，永不放弃。

        这里不去识别失败界面（多一个模板就多一处会随版本失效的地方），
        而是用「打完一局计数没变」这个**结果**判定：无论打不过、没刷新、
        还是传送点不对，都一视同仁地跳过，把时间让给下一个巢穴。
        """
        while nest := self.get_nest_to_go():
            if not isinstance(nest, NestTarget):
                return nest                 # 认不出身份的目标，交给原有流程
            # 键里带上进度：打出了进展就是新的一次机会，原地不动才算白打。
            stamp = f'{nest.cache_key}@{nest.progress}'
            if stamp in self._attempted_nests:
                self._unreachable_nests.add(nest.cache_key)
                self.log_info('nightmare nest: no progress after an attempt, '
                              f'skip: {nest.cache_key} (still {nest.progress})')
                continue                    # 下一轮 find_nest 会跳过它
            self._attempted_nests.add(stamp)
            return nest

    def run_capture_mode(self):
        self._capture_mode = True
        self._capture_success = False
        self._unreachable_nests.clear()
        self._attempted_nests.clear()
        WWOneTimeTask.run(self)
        self.ensure_main(time_out=30)
        self._init_queue()
        self.log_info('opened gray_book_boss')
        while nest := self._next_nest_with_progress():
            self.combat_nest(nest)
            if self._capture_success:
                break
        self.ensure_main(time_out=30)

    def on_combat_check(self):
        if self._capture_mode:
            self.pick_f(handle_claim=False)
            if self.has_echo_notification():
                return self.reset_to_false(reason='echo captured')
        return True

    def has_echo_notification(self):
        if self.find_best_match_in_box(self.box_of_screen(0.078, 0.488, 0.094, 0.514),
                                       ['char_1_text', 'char_3_text'], 0.6,
                                       frame_processor=convert_image_to_negative):
            self._capture_success = True
        return self._capture_success

    def combat_nest(self, nest):
        target_box = nest.box if isinstance(nest, NestTarget) else nest
        self.click(target_box, after_sleep=2)
        feature = self.wait_feature(['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close'], time_out=10,
                                    settle_time=0.5, raise_if_not_found=True)
        is_team = feature.name == 'team_close'
        if is_team:
            self.click_team_challenge()
            self.wait_in_team_and_world(time_out=120)
        else:
            if not self._travel_to_nest_or_skip(nest):
                return
            self.sleep(1)
            while self.find_f_with_text():
                self.send_key('f', after_sleep=1)
                self.wait_in_team_and_world(time_out=40, raise_if_not_found=False)
            self.sleep(2)
            self.run_until(self.in_combat, 'w', time_out=10, running=False, target=True)
        wait_combat_time = 10
        while True:
            try:
                need_find = self.combat_once(wait_combat_time=wait_combat_time, target=True,
                                             raise_if_not_found=False)
            except CharRevivedException:
                self.log_info('nightmare nest: death recovered, re-enter from F2 book')
                return
            captured_early = False
            if self._capture_mode:
                if self._capture_success or self.wait_until(self.has_echo_notification, time_out=3):
                    self.log_info("Captured echo during combat, skipping search.")
                    captured_early = True
            if not captured_early:
                self.sleep(3)
                if need_find and not self.walk_find_echo(time_out=5, backward_time=2.5):
                    dropped = self.yolo_find_echo(turn=True, use_color=False, time_out=30)[0]
                    logger.info(f'farm echo yolo find {dropped}')
                    if not dropped and not is_team:
                        # 保底：没有收取到声骸时，重新打开图鉴传送回当前聚落（传送点面朝金色声骸群），再搜索一次
                        self.log_info('no echo collected, re-teleport to current nest as fallback')
                        self.ensure_main(time_out=30)
                        self.openF2Book("gray_book_boss")
                        getattr(self, self._nest_tab_of_current_nest)()
                        self.sleep(1)
                        self.click(target_box, after_sleep=2)
                        if self.wait_feature(TRAVEL_FEATURES, time_out=5, settle_time=0.5,
                                            raise_if_not_found=False) and self._travel_to_nest_or_skip(nest):
                            self.sleep(2)
                            self.run_until(lambda: False, 'w', time_out=2, running=True)
                            if not self.walk_find_echo(time_out=5, backward_time=2.5):
                                dropped = self.yolo_find_echo(turn=True, use_color=False, time_out=30)[0]
                                logger.info(f'farm echo yolo find after re-teleport {dropped}')
                            else:
                                dropped = True
                                self.log_info('farm echo walk find true after re-teleport')
                else:
                    dropped = True
                    self.log_info(f'farm echo walk find true')
                self._capture_success = dropped
            if not self._should_continue_combat_after_pickup():
                break
            self.log_info('nightmare nest: combat detected after pickup')
            wait_combat_time = 1
        # 与刷全部一致：退本后再结束 combat_nest，避免还在巢穴内回 Daily/开书
        if is_team:
            self.esc_world_confirm()
        self.sleep(1)

    def _should_continue_combat_after_pickup(self):
        return not self._capture_mode and self.wait_combat(
            target=True, time_out=3, raise_if_not_found=False)

    def _travel_to_nest_or_skip(self, nest):
        travel = self.wait_until(self._find_travel_button, raise_if_not_found=False, time_out=1)
        if travel:
            self.click(travel, after_sleep=1)
            if confirm := self._find_first_feature(CONFIRM_FEATURES, threshold=0.6):
                self.click(confirm, after_sleep=1)

        button_still_visible = travel and self.find_one(travel.name, threshold=0.7)
        if travel and not button_still_visible and self.wait_in_team_and_world(
                time_out=120, raise_if_not_found=False):
            return True

        if isinstance(nest, NestTarget):
            self._unreachable_nests.add(nest.cache_key)
            self.log_info(f'nightmare nest unreachable, skip this run: {nest.cache_key}')
        else:
            self.log_info('nightmare nest unreachable, skip this run')
        self.back(after_sleep=1)
        return False

    def _find_travel_button(self):
        return self._find_first_feature(TRAVEL_FEATURES, threshold=0.7)

    def _find_first_feature(self, feature_names, threshold):
        for feature_name in feature_names:
            if feature := self.find_one(feature_name, threshold=threshold):
                return feature

    def get_nest_to_go(self):
        self.openF2Book("gray_book_boss")

        while self.queues:
            self.queues[0]()
            if nest := self.find_nest():
                self._nest_tab_of_current_nest = self.queues[0].__name__
                return nest
            self.queues.pop(0)

    def _init_queue(self):
        quests = self.config.get('Which to Farm') or ['Nightmare Purification', 'Tacet Discord Nest']
        actions = []
        if 'Tacet Discord Nest' in quests:
            actions.append(self.go_nest)
        if 'Nightmare Purification' in quests:
            actions.append(self.go_nightmare)
            actions.append(self.go_nightmare_scroll)
        self.queues = actions

    def go_nightmare(self):
        self.open_boss_book('mengyan')
        self.log_info('go nightmare')

    def go_nightmare_scroll(self):
        self.open_boss_book('mengyan')
        self.click(3737 / 3840, 0.54, after_sleep=1)
        self.log_info('go nightmare scroll')

    def go_nest(self):
        self.open_boss_book('canxiang')

    def _wanted_nest_rows(self):
        """配置了「只刷指定点位」时，那些点位各自在第几行（返回行中心的 y）。

        名字和计数属于同一张卡片，但**不在同一行**——实测计数在名字下方
        两行多（见 NEST_ROW_SPAN 的注释）。所以先按名字定位到行，
        再在下方 NEST_ROW_SPAN 个行高之内去认它的计数框。
        返回 None 表示没配置，照旧刷全部。
        """
        raw = (self.config.get(ONLY_NESTS) or '').strip()
        if not raw:
            return None
        names = [n.strip() for n in re.split(r'[,，]', raw) if n.strip()]
        # 点进列表之后它还要渲染一会儿。2026-08-27 实测：点击后才 2 秒就 OCR，
        # 一个名字都读不到，于是判定「找不到指定点位」→ find_nest 直接返回 None
        # → 残像聚落整段跳过，那天一次都没刷。所以先等列表真的出来。
        # 「出来了」的判据是能读到任意一个「x/y」计数，不是等固定秒数。
        for _ in range(NEST_LIST_TIMEOUT):
            if self.ocr(0.35, 0.13, 1, 0.96, match=self.count_re):
                break
            self.sleep(1)
        # 用**包含**匹配，不能用 ocr(match=...)：那个是精确相等。
        # 2026-08-27 实测，OCR 读出来的是「落渊南丘残象聚落」，
        # 而配置里写的是「落渊南丘」——精确匹配一个都对不上，
        # 于是判成「列表里没有这个点位」，整段跳过，那天一次没刷。
        boxes = self.ocr(0.35, 0.13, 1, 0.96)
        rows = []
        for name in names:
            for box in boxes:
                if name in (box.name or ''):
                    rows.append(box.y + box.height / 2)
        if not rows:
            # 这不是「打满了」，是「配的名字根本不在列表里」，两者后果一样
            # （什么都不刷）但原因完全不同，必须让人看见，不能只写进日志。
            seen = [b.name for b in boxes]
            self.log_error('nightmare nest: 列表里没找到指定的点位 '
                           f'{names}；实际读到的是 {seen}', notify=True)
        return rows

    def find_nest(self):
        wanted_rows = self._wanted_nest_rows()
        if wanted_rows is not None and not wanted_rows:
            return None                     # 指定了，但一个都没在列表里 → 什么都别刷
        hit_wanted = False
        counts = self.ocr(0.35, 0.13, 1, 0.96, match=self.count_re)
        for count_box in counts:
            if wanted_rows is not None:
                row = count_box.y + count_box.height / 2
                # 名字和计数属于同一张卡片，但不一定在同一行——计数常在
                # 名字下面一两行。所以只认「计数在名字下方 NEST_ROW_SPAN
                # 个行高以内」，既能跨行，又不会串到下一个点位上去。
                # 具体数值由上面那条几何日志量出来，不是拍脑袋。
                span = count_box.height * NEST_ROW_SPAN
                if not any(-count_box.height <= row - w <= span
                           for w in wanted_rows):
                    self.log_debug(f'nightmare nest: 计数 {count_box.name} '
                                   f'(y={row}) 不属于任何指定点位 {wanted_rows}')
                    continue
                hit_wanted = True
            for match in re.finditer(self.count_re, count_box.name):
                numerator = match.group(1)
                denominator = match.group(2)
                # 只要没打满就能接着打，不要求「一只都没打过」。
                # 原来这里还有一个 `numerator == '0'`：一个点位只要刷过一只，
                # 就被永久跳过，剩下的 40 多只再也不会去打。2026-08-26 实测，
                # 四个残象聚落刷到 10/41、6/48、48/48、24/24 之后，
                # 任务每轮都报「没有可刷的巢穴」直接收工——两个没满的都被这行挡掉了。
                if numerator != denominator and denominator in ['24', '36', '48', '41']:
                    cache_key = self._make_nest_cache_key(count_box, denominator)
                    if cache_key in self._unreachable_nests:
                        self.log_info(f'skip cached unreachable nightmare nest: {cache_key}')
                        continue
                    self.log_info(f'{count_box} is not complete')
                    count_box.x = self.width_of_screen(0.9)
                    count_box.y -= count_box.height * 0.9
                    count_box.height = 1
                    count_box.width = 1
                    return NestTarget(count_box, cache_key, numerator)
        if wanted_rows is not None and hit_wanted:
            self.log_info('nightmare nest: 指定点位都已打满，跳过')

    def _make_nest_cache_key(self, count_box, denominator):
        action_name = self.queues[0].__name__ if self.queues else 'unknown'
        screen_height = max(self.height_of_screen(1), 1)
        row_y = (count_box.y + count_box.height / 2) / screen_height
        row_slot = round(row_y / 0.02)
        # 使用粗粒度行槽位，避免 OCR 坐标轻微抖动导致同一目标被重复点击。
        return f'{action_name}:{denominator}:{row_slot}'


def convert_image_to_negative(img):
    to_gray = False
    _mat = img
    if len(_mat.shape) == 3:
        to_gray = True
        _mat = cv2.cvtColor(_mat, cv2.COLOR_BGR2GRAY)
    _, _mat = cv2.threshold(_mat, 80, 255, cv2.THRESH_BINARY)
    _mat = cv2.bitwise_not(_mat)
    if to_gray:
        _mat = cv2.cvtColor(_mat, cv2.COLOR_GRAY2BGR)
    return _mat


from ok import run_task
from config import config

if __name__ == "__main__":
    run_task(config, task=NightmareNestTask, debug=True)
