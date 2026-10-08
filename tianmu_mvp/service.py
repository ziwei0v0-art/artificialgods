"""Presentation-independent application boundary for the 1.0 native interface.

Rules and migrations are reused from the verified prototype; no Tk import or
window ownership is permitted here. Each consequential command persists before
returning success. The caller renders snapshots instead of mutating GameState.
"""

import copy
import datetime
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .content import INSECT_DESCRIPTIONS, SIGN_TEXTS
from .duration import parse_duration
from .model import COLORS, SHOP, ONBOARDING_UNFINISHED
from .storage import load_state, save_state
from .timer import validate_presets
from .traditional_time import duration_label, traditional_elapsed, traditional_clock_label


class ApplicationService:
    def __init__(self, save_path, initial_state=None):
        self.save_path = Path(save_path)
        self.game = load_state(self.save_path) if initial_state is None else initial_state
        self.pending_sale = None

    def snapshot(self, now):
        game = self.game
        timer = game.timer_session
        clock = copy.copy(timer)
        clock.mode = "clock"
        units = {'tea_seconds': timer.tea_seconds, 'incense_seconds': timer.incense_seconds}
        moment = (datetime.datetime.fromtimestamp(now).astimezone() if timer.clock_timezone == 'local'
                  else datetime.datetime.fromtimestamp(now, ZoneInfo(timer.clock_timezone)))
        clock_traditional = traditional_clock_label(moment)
        total = (timer.work_seconds if timer.phase == 'work' else timer.break_seconds) if timer.mode == 'pomodoro' else timer.countdown_seconds
        displayed_seconds = timer.seconds(now)
        if timer.mode == 'pomodoro' and timer.status == 'idle' and timer.remaining_seconds <= 0:
            displayed_seconds = total
        traditional = clock_traditional if timer.mode == 'clock' else traditional_elapsed(displayed_seconds)
        unit_presets = [{'label': label, 'input': text, 'seconds': seconds} for label, text, seconds in (
            ('一盏茶', '一盏茶', timer.tea_seconds), ('一刻', '一刻', 900),
            ('一炷香', '一炷香', timer.incense_seconds), ('一时辰', '一时辰', 7200))]
        # The bottle draws a bounded sample of actual adults, retaining rare
        # colours and stable identities even when dictionary order changes.
        bottle_groups = {color: [] for color in COLORS}
        for bug in sorted(game.bottle.values(), key=lambda item: item.id):
            if len(bottle_groups[bug.color]) < 12:
                bottle_groups[bug.color].append(bug)
        bottle_sample = [group[index] for index in range(12)
                         for group in bottle_groups.values() if index < len(group)][:12]
        shop = []
        for key, item in SHOP.items():
            reason = game.purchase_unavailable_reason(key)
            shop.append({'id': key, **item, 'owned': key in game.owned_items,
                         'placed': game.placed_items.get(item['slot']) == key,
                         'requires': item.get('requires'), 'can_buy': reason is None,
                         'unavailable_reason': reason})
        return {
            'coins': game.coins,
            'desktop': [{'id': bug.id, 'color': bug.color, 'sex': bug.sex, 'x': bug.x, 'y': bug.y}
                        for bug in game.desktop.values()],
            'bottle_individuals': [{'id': bug.id, 'color': bug.color, 'sex': bug.sex}
                                   for bug in bottle_sample],
            'bottle': [{'color': color,
                        'female': sum(bug.color == color and bug.sex == 'F' for bug in game.bottle.values()),
                        'male': sum(bug.color == color and bug.sex == 'M' for bug in game.bottle.values()),
                        'price': game.prices[color]} for color in COLORS],
            'capture_seconds': game.active_capture_seconds,
            'auto_paused': game.auto_capture_paused,
            'shop': shop,
            'placed_items': dict(game.placed_items),
            'shrine_stage': game.shrine_stage,
            'discoveries': [{'color': color, 'date': game.discovery_dates.get(color),
                             'found': color in game.discovered_colors,
                             'description': INSECT_DESCRIPTIONS[color]} for color in COLORS],
            'daily_sign_date': game.daily_sign_date,
            'signs': [{'date': date, 'verse': SIGN_TEXTS[int(index)][0], 'meaning': SIGN_TEXTS[int(index)][1]}
                      for date, index in sorted(game.sign_history.items(), reverse=True)],
            'timer': {**timer.to_dict(), 'readout': timer.readout(now), 'clock_readout': clock.readout(now),
                      'traditional_readout': traditional if timer.show_traditional else '',
                      'clock_traditional_readout': clock_traditional if timer.show_traditional else '',
                      'duration_equivalent': duration_label(total, **units), 'unit_presets': unit_presets},
            'game_timezone': game.game_timezone,
            'onboarding': game.onboarding,
            'routine': game.routine.snapshot(game.elapsed_seconds),
        }

    @staticmethod
    def _count(request):
        value = request.get('count', 0)
        if type(value) is not int or value <= 0:
            raise ValueError('请选择至少一只虫。')
        return value

    def _selection(self, request):
        color, sex = request.get('color'), request.get('sex')
        if color not in COLORS or sex not in (None, 'F', 'M'):
            raise ValueError('请选择有效的体色和性别。')
        return color, sex, self._count(request)

    def handle(self, request, now=None):
        if now is None:
            now = datetime.datetime.now().timestamp()
        before = copy.deepcopy(self.game)
        pending_before = copy.deepcopy(self.pending_sale)
        extra = {}
        try:
            action = request.get('action')
            timer = self.game.timer_session
            message = ''
            if action == 'snapshot':
                return {'ok': True, 'state': self.snapshot(now), 'new_discoveries': []}
            if action == 'sale_preview':
                ids, amount = self.game.quote_sale(*self._selection(request))
                if not ids:
                    raise ValueError('所选条件下没有可出售的虫。')
                token = secrets.token_hex(12)
                self.pending_sale = (token, ids, amount)
                return {'ok': True, 'sale': {'token': token, 'count': len(ids), 'amount': amount},
                        'state': self.snapshot(now), 'new_discoveries': []}
            if action == 'sale_cancel':
                had_pending_sale = self.pending_sale is not None
                self.pending_sale = None
                result = {'ok': True, 'state': self.snapshot(now), 'new_discoveries': []}
                if had_pending_sale:
                    result['message'] = '已取消，没有改变库存。'
                return result
            if action == 'checkpoint':
                message = '存档已保存。'
            elif action == 'onboarding_visit':
                page = request.get('page')
                if page not in ('神前', '虫瓶'):
                    raise ValueError('首次引导页面无效。')
                if self.game.onboarding == 'shrine' and page == '神前':
                    self.game.onboarding = 'capture'
                elif self.game.onboarding == 'bottle' and page == '虫瓶':
                    self.game.onboarding = 'done'
            elif action == 'onboarding_skip':
                if self.game.onboarding in ONBOARDING_UNFINISHED:
                    self.game.onboarding = 'skipped'
                    message = '已跳过首次引导。'
            elif action == 'game_timezone_set':
                zone = request.get('timezone')
                if not isinstance(zone, str) or not zone:
                    raise ValueError('游戏时区无效，请选择有效的时区。')
                try:
                    ZoneInfo(zone)
                except (ValueError, ZoneInfoNotFoundError):
                    raise ValueError('游戏时区无效，请选择有效的时区。')
                if zone != self.game.game_timezone:
                    self.game.routine.rebase_calendar(now, zone)
                    self.game.game_timezone = zone
                message = '游戏时区已保存。'
            elif action == 'sale_confirm':
                if not self.pending_sale or request.get('token') != self.pending_sale[0]:
                    raise ValueError('这次确认已失效，请重新选择。')
                _, ids, amount = self.pending_sale
                if not self.game.sell_ids(ids):
                    raise ValueError('库存已变化，请重新选择。')
                self.pending_sale = None
                message = '已出售 {0} 只，到账 {1} 铜钱。'.format(len(ids), amount)
            elif action == 'catch':
                ids = request.get('ids', [])
                if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
                    raise ValueError('捕获请求无效。')
                caught = self.game.catch(ids, now=now)
                if caught and self.game.onboarding == 'capture':
                    self.game.onboarding = 'bottle'
                message = '捕获 {0} 只，已放入虫瓶。'.format(len(caught))
            elif action == 'release':
                released = self.game.release(*self._selection(request))
                if not released:
                    raise ValueError('所选条件下没有可放回的虫。')
                message = '已放回 {0} 只原个体。'.format(len(released))
            elif action in ('buy', 'place'):
                item_id = request.get('item')
                if item_id not in SHOP:
                    raise ValueError('物件不存在。')
                success = self.game.buy(item_id) if action == 'buy' else self.game.place(item_id)
                if not success:
                    reason = (self.game.purchase_unavailable_reason(item_id) if action == 'buy'
                              else '物件尚未购买')
                    raise ValueError(reason + '；没有扣款。')
                message = ('已购买' if action == 'buy' else '已更新摆放：') + SHOP[item_id]['name']
                if action == 'place':
                    self.game.sync_routine(now)
            elif action == 'sign':
                date = datetime.datetime.fromtimestamp(now, ZoneInfo(self.game.game_timezone)).date().isoformat()
                index = self.game.sign_history.setdefault(date, str(sum(map(ord, date)) % len(SIGN_TEXTS)))
                self.game.daily_sign_date, self.game.daily_sign = date, index
                message = '今日签已保存，同日结果不变。'
            elif action == 'timer_start':
                mode = request.get('mode')
                if mode not in ('countdown', 'stopwatch', 'pomodoro'):
                    raise ValueError('请选择计时模式。')
                if timer.status in ('running', 'paused') and request.get('replace') is not True:
                    raise ValueError('已有计时任务，请明确确认替换。')
                timer.stop()
                timer.mode = mode
                if mode == 'countdown':
                    timer.countdown_seconds = parse_duration(request.get('duration', '25'), tea_seconds=timer.tea_seconds, incense_seconds=timer.incense_seconds)
                if mode == 'pomodoro':
                    timer.work_seconds = parse_duration(request.get('work', '25'), tea_seconds=timer.tea_seconds, incense_seconds=timer.incense_seconds)
                    timer.break_seconds = parse_duration(request.get('rest', '5'), tea_seconds=timer.tea_seconds, incense_seconds=timer.incense_seconds)
                timer.start(mode, now=now)
                message = '计时已开始。'
            elif action == 'timer_pause':
                if timer.tick(now) == 'expired':
                    extra['events'] = ['timer_expired']
                    self.game.request_bell(now)
                else:
                    timer.pause(now)
                message = '本轮已结束。' if timer.status == 'finished' else '计时已暂停。'
            elif action == 'timer_resume':
                if not timer.resume(now):
                    raise ValueError('只有暂停的计时可以继续。')
                message = '计时继续。'
            elif action == 'timer_end':
                if timer.mode == 'stopwatch':
                    timer.finish_stopwatch(now)
                else:
                    timer.stop()
                message = '本轮已结束。'
            elif action == 'timer_next':
                if not timer.next_phase():
                    raise ValueError('当前番茄段尚未结束。')
                timer.start(now=now)
                message = '下一段已开始。'
            elif action == 'timer_preferences':
                old_units = {'tea_seconds': timer.tea_seconds, 'incense_seconds': timer.incense_seconds}
                next_units = {}
                for request_key, field in (('tea_duration', 'tea_seconds'), ('incense_duration', 'incense_seconds')):
                    if request_key in request:
                        value = parse_duration(request[request_key], **old_units)
                        if not 1 <= value <= 86400:
                            raise ValueError('茶与香的约定时长须为1秒至24小时')
                        next_units[field] = value
                for field, value in next_units.items():
                    setattr(timer, field, value)
                if 'preset_durations' in request:
                    durations = request['preset_durations']
                    if not isinstance(durations, list) or len(durations) != 4 or any(type(value) is not str for value in durations):
                        raise ValueError('请填写四个常用时长。')
                    timer.preset_seconds = validate_presets([parse_duration(value, tea_seconds=timer.tea_seconds, incense_seconds=timer.incense_seconds) for value in durations])
                zone = request.get('timezone', timer.clock_timezone)
                if zone not in ('local', 'Asia/Shanghai'):
                    raise ValueError('钟显时区无效。')
                timer.clock_timezone = zone
                for name in ('sound_enabled', 'widget_enabled', 'notification_enabled', 'show_traditional'):
                    if name in request:
                        if type(request[name]) is not bool:
                            raise ValueError('提醒开关必须是开或关。')
                        setattr(timer, name, request[name])
                message = '计时设置已保存。'
            else:
                raise ValueError('不支持的操作。')
            if action != 'game_timezone_set':
                self._sync_timer()
            save_state(self.save_path, self.game)
            new_discoveries = [color for color in COLORS
                               if color in self.game.discovered_colors and color not in before.discovered_colors]
            return {'ok': True, 'message': message, 'state': self.snapshot(now),
                    'new_discoveries': new_discoveries, **extra}
        except (ValueError, OSError, TypeError) as error:
            self.game, self.pending_sale = before, pending_before
            return {'ok': False, 'error': str(error), 'state': self.snapshot(now), 'new_discoveries': []}

    def _sync_timer(self):
        timer = self.game.timer_session
        self.game.timer_deadline = timer.deadline
        self.game.timer_remaining = timer.remaining_seconds
        self.game.timer_completed = timer.status == 'finished'

    def tick(self, now, active_seconds):
        before = copy.deepcopy(self.game)
        try:
            # The native scheduler supplies only awake elapsed seconds.
            if type(active_seconds) is not int or not 0 <= active_seconds <= 2:
                raise ValueError('游戏时间增量无效，不补离线收益。')
            self.game.advance(active_seconds, now=now)
            expired = self.game.timer_session.tick(now) == 'expired'
            if expired:
                self.game.request_bell(now)
            self._sync_timer()
            save_state(self.save_path, self.game)
            new_discoveries = [color for color in COLORS
                               if color in self.game.discovered_colors and color not in before.discovered_colors]
            return {'ok': True, 'events': ['timer_expired'] if expired else [],
                    'state': self.snapshot(now), 'new_discoveries': new_discoveries}
        except (ValueError, OSError) as error:
            self.game = before
            return {'ok': False, 'error': str(error), 'events': [],
                    'state': self.snapshot(now), 'new_discoveries': []}
