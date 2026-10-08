"""Clock policy for pausable game simulation, independent of wall-clock timers."""

import datetime
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .traditional_time import traditional_clock_label


def clock_readout(now, timezone='local', show_traditional=True):
    """Read an explicit timestamp in the selected zone; do not advance game time."""
    if type(now) not in (int, float) or (type(now) is float and not math.isfinite(now)):
        raise ValueError('时钟时间戳无效。')
    if not isinstance(timezone, str) or type(show_traditional) is not bool:
        raise ValueError('时钟显示设置无效。')
    try:
        moment = (datetime.datetime.fromtimestamp(now).astimezone() if timezone == 'local'
                  else datetime.datetime.fromtimestamp(now, ZoneInfo(timezone)))
    except (OverflowError, OSError, ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError('时钟时间或时区无效。') from error
    modern = moment.strftime('%H:%M:%S')
    return modern + '\n' + traditional_clock_label(moment) if show_traditional else modern


def consume_active_delta(wall_delta, visible, fractional=0.0):
    """Return (whole active seconds, fractional carry) for one UI heartbeat.

    A gap above two seconds is treated as a suspend/event-loop stall and is
    discarded, so a resumed app never catches up offline gameplay.
    """
    if not visible or wall_delta < 0 or wall_delta > 2.0:
        return 0, 0.0
    accumulated = fractional + wall_delta
    whole_seconds = int(accumulated)
    return whole_seconds, accumulated - whole_seconds
