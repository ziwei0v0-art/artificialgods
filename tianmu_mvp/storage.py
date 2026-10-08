"""Versioned JSON persistence with same-directory atomic replacement."""

import json
import datetime
import math
import os
import random
import re
import shutil
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from .model import GameState, Insect, ONBOARDING_STATES, COLORS, SHOP
from .timer import TimerSession
from .routine import RoutineState


SCHEMA_VERSION = 1
MAX_INTEGER = (1 << 63) - 1


class SaveLoadError(ValueError):
    """A stable startup classification that remains compatible with ValueError."""
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def _integer(value, label, minimum=0, maximum=MAX_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('{0}必须是范围内的整数'.format(label))
    return value


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError('{0}结构无效'.format(label))
    return value


def _sequence(value, label):
    if not isinstance(value, list):
        raise ValueError('{0}必须是列表'.format(label))
    return value


def _strings(value, label, allowed=None):
    values = _sequence(value, label)
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError('{0}包含无效文字'.format(label))
    if len(set(values)) != len(values):
        raise ValueError('{0}包含重复记录'.format(label))
    if allowed is not None and any(item not in allowed for item in values):
        raise ValueError('{0}包含未知内容'.format(label))
    return values


def _timestamp(value, label):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ValueError('{0}必须是有限时间戳'.format(label))
    return value


def _date(value, label):
    if not isinstance(value, str) or datetime.date.fromisoformat(value).isoformat() != value:
        raise ValueError('{0}日期无效'.format(label))
    return value


def _sign(value):
    valid = type(value) is int or (isinstance(value, str) and value.isascii() and value.isdigit())
    if not valid or not 0 <= int(value) < 12:
        raise ValueError('签文记录无效')
    return value


def _json_tree(value):
    if isinstance(value, tuple):
        return [_json_tree(item) for item in value]
    if isinstance(value, list):
        return [_json_tree(item) for item in value]
    return value


def _tuple_tree(value):
    if isinstance(value, list):
        return tuple(_tuple_tree(item) for item in value)
    return value


def _insect_dict(insect):
    return {
        "id": insect.id,
        "sex": insect.sex,
        "genotype": list(insect.genotype),
        "color": insect.color,
        "x": insect.x,
        "y": insect.y,
    }


def _insect_from_dict(raw):
    _mapping(raw, '虫体')
    if not isinstance(raw.get('id'), str) or not raw['id']:
        raise ValueError('存档个体 ID 无效')
    if raw.get("sex") not in ("F", "M"):
        raise ValueError("存档内有无效虫体性别")
    genotype = tuple(_sequence(raw.get("genotype"), '遗传信息'))
    if (len(genotype) != 2 or genotype[0] not in ("AA", "Aa", "aA", "aa")
            or genotype[1] not in ("BB", "Bb", "bB", "bb")):
        raise ValueError("存档内有无效遗传信息")
    if raw.get("color") != GameState.color_for(genotype):
        raise ValueError("存档体色与遗传信息不一致")
    for name in ('x', 'y'):
        value = raw.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('存档虫体坐标无效')
    return Insect(
        id=raw["id"], sex=raw["sex"], genotype=genotype,
        color=raw["color"], x=raw["x"], y=raw["y"],
    )


def _state_dict(state):
    return {
        "schema_version": SCHEMA_VERSION,
        "desktop": [_insect_dict(bug) for bug in state.desktop.values()],
        "bottle": [_insect_dict(bug) for bug in state.bottle.values()],
        "sold_ids": sorted(state.sold_ids),
        "discovered_colors": sorted(state.discovered_colors),
        "coins": state.coins,
        "owned_items": sorted(state.owned_items),
        "placed_item": state.placed_item,
        "placed_items": state.placed_items,
        "elapsed_seconds": state.elapsed_seconds,
        "active_capture_seconds": state.active_capture_seconds,
        "next_insect_number": state.next_insect_number,
        "timer_deadline": state.timer_deadline,
        "timer_remaining": state.timer_remaining,
        "timer_completed": state.timer_completed,
        "timer_session": state.timer_session.to_dict(),
        "routine": state.routine.to_dict(),
        "daily_sign_date": state.daily_sign_date,
        "daily_sign": state.daily_sign,
        "sign_history": state.sign_history,
        "discovery_dates": state.discovery_dates,
        "game_timezone": state.game_timezone,
        "onboarding": state.onboarding,
        "prices": state.prices,
        "first_spawn_at": state._first_spawn_at,
        "next_breed_at": state._next_breed_at,
        "next_auto_capture_at": state._next_auto_capture_at,
        "next_empty_refill_at": state._next_empty_refill_at,
        "rng_state": _json_tree(state.rng.getstate()),
    }


def _state_from_dict(raw):
    _mapping(raw, '存档')
    version = raw.get('schema_version')
    if type(version) is not int:
        raise ValueError('存档版本号无效')
    if version != SCHEMA_VERSION:
        raise SaveLoadError('save_incompatible', '不支持的存档版本：{0}；原文件已保留。'.format(version))
    # Preserve the established legacy default when game_timezone is absent.
    # This may inspect the local timezone, but never a save path or backup.
    state = GameState.new(rng=random.Random())
    state.onboarding = raw.get('onboarding', 'legacy')
    if not isinstance(state.onboarding, str) or state.onboarding not in ONBOARDING_STATES:
        raise ValueError('存档首次引导状态无效')
    desktop = list(map(_insect_from_dict, _sequence(raw['desktop'], '桌面虫体')))
    bottle = list(map(_insect_from_dict, _sequence(raw['bottle'], '虫瓶个体')))
    sold_ids = _strings(raw['sold_ids'], '已售个体')
    ids = [bug.id for bug in desktop + bottle] + sold_ids
    if len(set(ids)) != len(ids):
        raise ValueError("存档存在重复个体 ID")
    state.desktop = {bug.id: bug for bug in desktop}
    state.bottle = {bug.id: bug for bug in bottle}
    state.sold_ids = set(sold_ids)
    state.discovered_colors = set(_strings(raw['discovered_colors'], '已发现体色', COLORS))
    state.coins = _integer(raw['coins'], '铜钱')
    state.owned_items = set(_strings(raw['owned_items'], '已购物件', SHOP))
    state.placed_item = raw["placed_item"]
    state.placed_items = dict(_mapping(raw.get('placed_items', {}), '摆放物件'))
    if state.placed_item is not None and state.placed_item != 'offering_plate':
        raise ValueError('旧供盘摆放记录无效')
    if state.placed_item is not None and "plate" not in state.placed_items:
        state.placed_items["plate"] = state.placed_item
    for slot, item in state.placed_items.items():
        if (not isinstance(item, str) or item not in SHOP or item not in state.owned_items
                or slot != SHOP[item]['slot']):
            raise ValueError('摆放物件与槽位或所有权不符')
    if state.placed_item != state.placed_items.get('plate'):
        raise ValueError('供盘摆放记录不一致')
    state.elapsed_seconds = _integer(raw['elapsed_seconds'], '有效运行秒数')
    state.routine = (RoutineState.from_dict(raw['routine'], state.elapsed_seconds)
                     if 'routine' in raw else RoutineState.migrated(state.elapsed_seconds))
    for name in ('offering_count', 'fruit_started_active', 'fruit_mature_after',
                 'action_serial', 'action_started_active', 'action_duration', 'ambient_index'):
        _integer(getattr(state.routine, name), '日常' + name)
    state.active_capture_seconds = _integer(raw['active_capture_seconds'], '捕获累计秒数', maximum=86400)
    state.next_insect_number = _integer(raw['next_insect_number'], '下一个体编号', minimum=1)
    for insect_id in ids:
        match = re.fullmatch(r'bug-([0-9]{5,})', insect_id)
        if match and int(match.group(1)) >= state.next_insect_number:
            raise ValueError('下一个体编号会覆盖既有个体')
    state.timer_deadline = _timestamp(raw['timer_deadline'], '旧计时截止时间')
    state.timer_remaining = _integer(raw['timer_remaining'], '旧计时剩余秒数')
    state.timer_completed = raw.get('timer_completed', False)
    if type(state.timer_completed) is not bool:
        raise ValueError('旧计时完成状态无效')
    if 'timer_session' in raw:
        state.timer_session = TimerSession.from_dict(raw['timer_session'])
    else:
        # Migrate the original countdown-only fields without changing their meaning.
        state.timer_session.mode = "countdown"
        state.timer_session.deadline = state.timer_deadline
        state.timer_session.remaining_seconds = state.timer_remaining
        state.timer_session.status = (
            "running" if state.timer_deadline is not None
            else "finished" if state.timer_completed
            else "paused" if state.timer_remaining > 0
            else "idle"
        )
        state.timer_session = TimerSession.from_dict(state.timer_session.to_dict())
    state.daily_sign_date = raw["daily_sign_date"]
    state.daily_sign = raw["daily_sign"]
    state.sign_history = dict(_mapping(raw.get('sign_history', {}), '签文历史'))
    for date, index in state.sign_history.items():
        _date(date, '签文')
        _sign(index)
    if state.daily_sign_date is not None:
        _date(state.daily_sign_date, '今日签')
        _sign(state.daily_sign)
        if (state.daily_sign_date in state.sign_history
                and int(state.sign_history[state.daily_sign_date]) != int(state.daily_sign)):
            raise ValueError('今日签与签文历史不一致')
        state.sign_history.setdefault(state.daily_sign_date, state.daily_sign)
    elif state.daily_sign is not None:
        raise ValueError('今日签缺少日期')
    state.discovery_dates = dict(_mapping(raw.get('discovery_dates', {}), '发现日期'))
    for color, date in state.discovery_dates.items():
        if color not in state.discovered_colors:
            raise ValueError('发现日期包含尚未发现或未知体色')
        _date(date, '发现')
    state.game_timezone = raw.get("game_timezone", state.game_timezone)
    if not isinstance(state.game_timezone, str):
        raise ValueError('游戏时区无效')
    ZoneInfo(state.game_timezone)
    prices = _mapping(raw['prices'], '售价')
    if set(prices) != set(COLORS):
        raise ValueError('售价必须完整包含四种体色')
    state.prices = {color: _integer(value, '售价') for color, value in prices.items()}
    for name in ('first_spawn_at', 'next_breed_at', 'next_auto_capture_at', 'next_empty_refill_at'):
        value = raw[name]
        if value is not None:
            _integer(value, '排程' + name)
        setattr(state, '_' + name, value)
    state.rng.setstate(_tuple_tree(raw["rng_state"]))
    if 'routine' not in raw and state.bell_equipped:
        state.routine.request_bell(True)
    return state


def decode_state_bytes(data):
    """Validate JSON without reading or writing a save or its backup.

    The sole legacy environment default is the existing local game timezone
    when that field is absent; no running session or offline time is advanced.
    """
    try:
        def invalid_constant(value):
            raise ValueError('存档包含非有限数值：' + value)
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('存档包含重复字段：' + key)
                result[key] = value
            return result
        return _state_from_dict(json.loads(data, parse_constant=invalid_constant,
                                           object_pairs_hook=unique_object))
    except SaveLoadError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, RecursionError) as error:
        raise SaveLoadError('save_corrupt', '存档内容损坏；原文件已保留，未自动清空：{0}'.format(error)) from error


def save_state(path, state):
    # Preflight before mkdir, backup rotation or temporary-file creation. This
    # lets the service roll back an invalid/overflowing transaction in memory.
    try:
        encoded = json.dumps(_state_dict(state), ensure_ascii=False, separators=(',', ':'),
                             allow_nan=False).encode('utf-8')
        decode_state_bytes(encoded)
    except SaveLoadError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, RecursionError) as error:
        raise SaveLoadError('save_corrupt', '待保存数据无效，未写入：{0}'.format(error)) from error
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    backup_temporary = None
    try:
        # Keep the last known-good file before replacing it. Use a same-folder
        # temporary so the backup itself is also replaced atomically.
        if path.exists():
            descriptor, backup_name = tempfile.mkstemp(
                prefix=path.name + ".bak.", suffix=".tmp", dir=str(path.parent)
            )
            backup_temporary = Path(backup_name)
            with os.fdopen(descriptor, "wb") as stream:
                with path.open("rb") as previous:
                    shutil.copyfileobj(previous, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(backup_temporary), str(path) + ".bak")
            backup_temporary = None
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary_path), str(path))
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
        if backup_temporary is not None:
            try:
                backup_temporary.unlink()
            except OSError:
                pass
        raise


def load_state(path):
    path = Path(path)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        try:
            backup_exists = Path(str(path) + '.bak').exists()
        except OSError as error:
            raise SaveLoadError('save_unreadable', '无法检查存档备份：{0}'.format(error)) from error
        if backup_exists:
            raise SaveLoadError('save_missing', '主存档缺失，但备份仍存在；未创建新档。')
        return GameState.new()
    except OSError as error:
        raise SaveLoadError('save_unreadable', '存档无法读取；原文件已保留：{0}'.format(error)) from error
    return decode_state_bytes(data)
