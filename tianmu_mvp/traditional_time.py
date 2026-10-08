"""Traditional names mapped onto modern seconds; this module never runs a clock.

The product uses twelve two-hour periods and 96 fifteen-minute quarters per
day. Tea and incense durations are configurable product conventions, not claims
of a universal historical measure. Wall-clock expressions are parsed separately
from durations and never schedule an alarm or select a date/timezone.
"""

import datetime
import re


DEFAULT_TEA_SECONDS = 600
DEFAULT_INCENSE_SECONDS = 1800
QUARTER_SECONDS = 900
SHICHEN_SECONDS = 7200
MAX_DURATION_SECONDS = (1 << 31) - 1  # Catime's duration parser returns a C int.
BRANCHES = '子丑寅卯辰巳午未申酉戌亥'
_DIGITS = '零一二三四五六七八九'
_CLOCK_HINT = re.compile('[' + BRANCHES + '](?:时|初|正)')
_DURATION_TOKEN = re.compile(
    r'(?P<count>半|[0-9]+|[零〇一二两三四五六七八九十]+)\s*'
    r'(?P<unit>个\s*时辰|时辰|小时|分钟|分|秒|刻|盏茶|炷香)')
_CLOCK_PATTERN = re.compile(
    r'(?P<branch>[' + BRANCHES + r'])(?P<shi>时)?(?P<half>初|正)?'
    r'(?:(?P<quarter>[0-9]+|初|零|[一二三四五六七八九十]+)刻)?')


def validate_unit_seconds(tea_seconds=DEFAULT_TEA_SECONDS,
                          incense_seconds=DEFAULT_INCENSE_SECONDS):
    """Validate injected whole-second unit lengths without changing either one."""
    for value in (tea_seconds, incense_seconds):
        if type(value) is not int or not 0 < value <= MAX_DURATION_SECONDS:
            raise ValueError('香与茶的时长须为大于零的整数秒。')


def _quantity(text):
    if re.fullmatch(r'[0-9]+', text):
        if len(text) > 10:
            raise ValueError('时长超出范围。')
        return int(text)
    if text == '两':
        return 2
    if len(text) == 1 and text in _DIGITS:
        return _DIGITS.index(text)
    if re.fullmatch(r'十[一二三四五六七八九]?', text):
        return 10 + (_DIGITS.index(text[1]) if len(text) == 2 else 0)
    if re.fullmatch(r'[二三四五六七八九]十[一二三四五六七八九]?', text):
        return _DIGITS.index(text[0]) * 10 + (_DIGITS.index(text[2]) if len(text) == 3 else 0)
    raise ValueError('请使用明确的数字，例如三刻、半个时辰或两炷香。')


def _number(value, *, liang=False):
    if value == 2 and liang:
        return '两'
    if value < 10:
        return _DIGITS[value]
    if value < 100:
        tens, ones = divmod(value, 10)
        return ('' if tens == 1 else _DIGITS[tens]) + '十' + (_DIGITS[ones] if ones else '')
    return str(value)


def _whole_seconds(value):
    # Display also accepts long-lived stopwatch/legacy core values; do not apply
    # the input parser's int32 cap here or silently round away remaining seconds.
    if type(value) is not int or value < 0:
        raise ValueError('显示时长须为非负整数秒。')
    return value


def parse_traditional_duration(text, *, tea_seconds=DEFAULT_TEA_SECONDS,
                               incense_seconds=DEFAULT_INCENSE_SECONDS):
    """Parse explicit Chinese durations, with no guessed or partial matches.

    Accepts positive Arabic numbers, Chinese numbers 1–99, or 半; adjacent
    different units can be joined by 又. A half-unit must contain whole seconds.
    """
    validate_unit_seconds(tea_seconds, incense_seconds)
    if not isinstance(text, str) or '\0' in text:
        raise ValueError('请输入有效时长。')
    text = text.strip()
    if _CLOCK_HINT.search(text):
        raise ValueError('这是时刻，不是时长；倒计时请用三刻、一盏茶或一炷香。')
    units = {'时辰': SHICHEN_SECONDS, '小时': 3600, '刻': QUARTER_SECONDS,
             '分钟': 60, '分': 60, '秒': 1, '盏茶': tea_seconds, '炷香': incense_seconds}
    seen = set()
    total = position = 0
    while position < len(text):
        match = _DURATION_TOKEN.match(text, position)
        if match is None:
            raise ValueError('请输入完整时长，例如三刻、半个时辰、一盏茶或一炷香。')
        unit = re.sub(r'\s+', '', match['unit']).removeprefix('个')
        group = {'时辰': 'hour', '小时': 'hour', '分钟': 'minute', '分': 'minute'}.get(unit, unit)
        if group in seen:
            raise ValueError('请合并重复的时长单位。')
        seen.add(group)
        base = units[unit]
        if match['count'] == '半':
            if base % 2:
                raise ValueError('半个单位必须能换算为整数秒。')
            seconds = base // 2
        else:
            seconds = _quantity(match['count']) * base
        if seconds <= 0 or total + seconds > MAX_DURATION_SECONDS:
            raise ValueError('时长须大于零，且不能超出计时范围。')
        total += seconds
        position = match.end()
        while position < len(text) and text[position].isspace():
            position += 1
        if position < len(text) and text[position] == '又':
            position += 1
            while position < len(text) and text[position].isspace():
                position += 1
            if position == len(text):
                raise ValueError('又后面须有完整时长。')
    if total <= 0:
        raise ValueError('请输入大于零的有效时长。')
    return total


def traditional_elapsed(seconds):
    """Exact elapsed/remaining expression, derived from supplied integer seconds."""
    shichen, remainder = divmod(_whole_seconds(seconds), SHICHEN_SECONDS)
    quarters, remainder = divmod(remainder, QUARTER_SECONDS)
    minutes, remainder = divmod(remainder, 60)
    parts = []
    if shichen:
        parts.append(_number(shichen) + '时辰')
    if quarters:
        parts.append(_number(quarters) + '刻')
    if minutes:
        parts.append(str(minutes) + '分')
    if remainder:
        parts.append(str(remainder) + '秒')
    return ''.join(parts) or '0秒'


def duration_label(seconds, *, tea_seconds=DEFAULT_TEA_SECONDS,
                   incense_seconds=DEFAULT_INCENSE_SECONDS):
    """Concise exact alias for a configured duration; no approximation marker.

    Whole/half shichen and whole quarters stay familiar; one configured tea or
    incense has its named alias. Other exact small multiples use those units;
    remaining values use the exact quarter/minute/second expression.
    """
    validate_unit_seconds(tea_seconds, incense_seconds)
    seconds = _whole_seconds(seconds)
    if not seconds or seconds % SHICHEN_SECONDS == 0:
        return traditional_elapsed(seconds)
    if seconds == SHICHEN_SECONDS // 2:
        return '半个时辰'
    if seconds == incense_seconds:
        return '一炷香'
    if seconds == tea_seconds:
        return '一盏茶'
    if seconds % QUARTER_SECONDS == 0:
        return traditional_elapsed(seconds)
    for unit, base in (('炷香', incense_seconds), ('盏茶', tea_seconds)):
        if base % 2 == 0 and seconds == base // 2:
            return '半' + unit
        count, remainder = divmod(seconds, base)
        if not remainder and 1 < count < 100:
            return _number(count, liang=True) + unit
    return traditional_elapsed(seconds)


def traditional_clock_label(moment):
    """Display an already-localized wall time using 初/正 and 15-minute quarters."""
    if not isinstance(moment, (datetime.datetime, datetime.time)):
        raise ValueError('传统时刻需要有效的当地时间。')
    branch = BRANCHES[((moment.hour + 1) // 2) % 12]
    half = '初' if moment.hour % 2 else '正'
    quarter = ('', '一刻', '二刻', '三刻')[moment.minute // 15]
    return branch + half + quarter


def parse_traditional_clock(text):
    """Return a naive time-of-day, never a duration or a scheduled deadline.

    Product shorthand 辰时三刻 means 07:45 (three quarters after 辰初).
    Explicit 初/正 accepts 0–3 quarters; the whole 时 period accepts 0–7.
    Resolving a date, DST gap/fold, or future alarm is deliberately caller-owned.
    """
    if not isinstance(text, str) or '\0' in text:
        raise ValueError('请输入有效传统时刻。')
    match = _CLOCK_PATTERN.fullmatch(text.strip())
    if match is None or not (match['shi'] or match['half']):
        raise ValueError('请输入明确时刻，例如辰时三刻或辰正二刻。')
    quarter_text = match['quarter']
    quarter = 0 if quarter_text in (None, '初', '零') else _quantity(quarter_text)
    if not 0 <= quarter <= (3 if match['half'] else 7):
        raise ValueError('初或正各为四刻；一个时辰共八刻。')
    start_hour = (BRANCHES.index(match['branch']) * 2 + 23) % 24
    minutes = start_hour * 60 + (60 if match['half'] == '正' else 0) + quarter * 15
    hour, minute = divmod(minutes % 1440, 60)
    return datetime.time(hour, minute)
