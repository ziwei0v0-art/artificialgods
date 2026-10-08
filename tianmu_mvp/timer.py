"""Persisted Mac adapter for Catime's timer core; one session shared by all views.

The C core owns reset, timing arithmetic, pause/resume, the completion latch and
phase advancement. This module owns compatible saves and Tianmu's manual-next
policy. Caller-supplied real time preserves the existing sleep/restart contract.
"""

from dataclasses import asdict, dataclass, field
import ctypes
from functools import lru_cache
import math
import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from .duration import _library
from .clock import clock_readout


# Reserve headroom for sums/differences in the upstream int64 millisecond core.
# This still covers over 36 million years; malformed timestamps never wrap C.
_MAX_CORE_MS = ((1 << 63) - 1) // 8
_MAX_CORE_SECONDS = _MAX_CORE_MS // 1000


class _CoreState(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ('count_up', 'paused', 'completion_shown')] + [
        (name, ctypes.c_int64) for name in ('total_seconds', 'countdown_elapsed_seconds',
        'countup_elapsed_seconds', 'target_ms', 'start_ms', 'pause_ms')]


class _PomodoroState(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ('times_count', 'loop_count', 'time_index', 'complete_cycles')]


@lru_cache(maxsize=1)
def _core():
    library = _library()
    for name, result in (('Catime_ResetTimer', None), ('Catime_TogglePauseTimer', None),
                         ('Catime_ReadMilliseconds', ctypes.c_int64),
                         ('Catime_ReadSeconds', ctypes.c_int64), ('Catime_Tick', ctypes.c_int)):
        function = getattr(library, name)
        function.argtypes = (ctypes.POINTER(_CoreState), ctypes.c_int64)
        function.restype = result
    library.Catime_AdvancePomodoroState.argtypes = (ctypes.POINTER(_PomodoroState),)
    library.Catime_AdvancePomodoroState.restype = ctypes.c_int
    library.Catime_FormatSeconds.argtypes = (ctypes.c_int64, ctypes.c_char_p, ctypes.c_size_t)
    library.Catime_FormatSeconds.restype = None
    return library


def _timestamp_ms(value):
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        raise ValueError('计时时间戳无效')
    if not -_MAX_CORE_MS / 1000 <= value <= _MAX_CORE_MS / 1000:
        raise ValueError('计时时间戳超出范围')
    # Decimal millisecond floats such as 1.001 can multiply to 1000.9999999999.
    # Correct that single representational ULP without rounding future half-ms.
    return math.floor(math.nextafter(value * 1000, math.inf))


def _checked_seconds(value):
    if type(value) is not int or not 0 <= value <= _MAX_CORE_SECONDS:
        raise ValueError('计时时长超出范围')
    return value


def validate_presets(values):
    if (not isinstance(values, list) or len(values) != 4 or
            any(type(value) is not int or not 0 < value <= 86400 for value in values) or
            len(set(values)) != 4):
        raise ValueError('常用时长须为四个不同的正数，且不超过一天')
    return list(values)


@dataclass
class TimerSession:
    mode: str = "clock"
    status: str = "idle"
    deadline: Optional[float] = None
    remaining_seconds: int = 0
    countdown_seconds: int = 10 * 60
    started_at: Optional[float] = None
    elapsed_seconds: int = 0
    work_seconds: int = 25 * 60
    break_seconds: int = 5 * 60
    phase: str = "work"
    clock_timezone: str = "local"
    show_traditional: bool = True
    sound_enabled: bool = True
    widget_enabled: bool = True
    notification_enabled: bool = True
    # Optional in old saves: whole-second mirrors remain compatible with views.
    remaining_milliseconds: Optional[int] = None
    elapsed_milliseconds: Optional[int] = None
    pause_started_at: Optional[float] = None
    preset_seconds: list = field(default_factory=lambda: [300, 900, 1500, 2700])
    # Product conventions, not fixed historical units. Old saves receive defaults.
    tea_seconds: int = 600
    incense_seconds: int = 1800

    def _remaining_ms(self):
        return self.remaining_milliseconds if self.remaining_milliseconds is not None else _checked_seconds(self.remaining_seconds) * 1000

    def _elapsed_ms(self):
        return self.elapsed_milliseconds if self.elapsed_milliseconds is not None else _checked_seconds(self.elapsed_seconds) * 1000

    def _state(self, now):
        now_ms = _timestamp_ms(now)
        state = _CoreState()
        state.count_up = self.mode == 'stopwatch'
        state.paused = self.status != 'running'
        state.completion_shown = self.status == 'finished'
        phase_duration = self.work_seconds if self.phase == 'work' else self.break_seconds
        state.total_seconds = _checked_seconds(max(1, self.remaining_seconds,
            phase_duration if self.mode == 'pomodoro' else self.countdown_seconds))
        state.pause_ms = _timestamp_ms(self.pause_started_at) if self.pause_started_at is not None else now_ms
        base_ms = state.pause_ms if state.paused else now_ms
        if state.count_up:
            start_ms = _timestamp_ms(self.started_at) if self.started_at is not None else base_ms
            state.start_ms = start_ms - self._elapsed_ms()
        else:
            state.target_ms = _timestamp_ms(self.deadline) if self.deadline is not None else base_ms + self._remaining_ms()
        return state, now_ms

    def _remember_remaining(self, state, now_ms):
        self.remaining_milliseconds = _core().Catime_ReadMilliseconds(ctypes.byref(state), now_ms)
        self.remaining_seconds = _core().Catime_ReadSeconds(ctypes.byref(state), now_ms)

    def _remember_elapsed(self, state, now_ms):
        self.elapsed_milliseconds = _core().Catime_ReadMilliseconds(ctypes.byref(state), now_ms)
        self.elapsed_seconds = _core().Catime_ReadSeconds(ctypes.byref(state), now_ms)

    def start(self, mode=None, now=0.0, minutes=None):
        previous_status = self.status
        if mode is not None:
            if mode not in ("countdown", "stopwatch", "pomodoro"):
                raise ValueError("未知计时模式：{0}".format(mode))
            self.mode = mode
        now_ms = _timestamp_ms(now)
        self.status = "running"
        self.pause_started_at = None
        if self.mode == "stopwatch":
            if previous_status in ("idle", "finished"):
                self.elapsed_seconds = 0
                self.elapsed_milliseconds = 0
            state = _CoreState(count_up=1)
            _core().Catime_ResetTimer(ctypes.byref(state), now_ms)
            self.started_at = state.start_ms / 1000
            return
        if self.mode == "pomodoro":
            self.remaining_seconds = self.work_seconds if self.phase == "work" else self.break_seconds
            self.remaining_milliseconds = None
        elif minutes is not None:
            self.countdown_seconds = max(1, int(minutes)) * 60
            self.remaining_seconds = self.countdown_seconds
            self.remaining_milliseconds = None
        elif self.remaining_seconds <= 0:
            self.remaining_seconds = self.countdown_seconds
            self.remaining_milliseconds = None
        state = _CoreState(total_seconds=_checked_seconds(self.remaining_seconds))
        _core().Catime_ResetTimer(ctypes.byref(state), now_ms)
        # Existing partially elapsed sessions may have a subsecond remainder.
        state.target_ms -= state.total_seconds * 1000 - self._remaining_ms()
        self.deadline = state.target_ms / 1000
        self._remember_remaining(state, now_ms)

    def pause(self, now=0.0):
        if self.status != "running":
            return False
        # Leave an already-due timer running until tick consumes its one expiry.
        # A pause callback must never turn a pending reminder into paused zero.
        state, now_ms = self._state(now)
        if self.mode != "stopwatch" and _core().Catime_ReadMilliseconds(ctypes.byref(state), now_ms) == 0:
            return False
        _core().Catime_TogglePauseTimer(ctypes.byref(state), now_ms)
        if self.mode == "stopwatch":
            self._remember_elapsed(state, now_ms)
            self.started_at = None
        else:
            self._remember_remaining(state, now_ms)
            self.deadline = None
        self.pause_started_at = state.pause_ms / 1000
        self.status = "paused"
        return True

    def resume(self, now=0.0):
        if self.status != "paused":
            return False
        state, now_ms = self._state(now)
        _core().Catime_TogglePauseTimer(ctypes.byref(state), now_ms)
        self.status = "running"
        if self.mode == "stopwatch":
            self.started_at = (state.start_ms + self._elapsed_ms()) / 1000
        else:
            self.deadline = state.target_ms / 1000
        self.pause_started_at = None
        return True

    def toggle(self, now=0.0, minutes=None):
        if self.status == "running":
            return self.pause(now)
        if self.status == "paused":
            return self.resume(now)
        self.start(self.mode, now=now, minutes=minutes)
        return True

    def tick(self, now=0.0):
        if self.status != "running" or self.mode == "stopwatch":
            return "unchanged"
        state, now_ms = self._state(now)
        expired = _core().Catime_Tick(ctypes.byref(state), now_ms)
        self._remember_remaining(state, now_ms)
        if not expired:
            return "running"
        self.deadline = None
        self.status = "finished"
        return "expired"

    def stop(self):
        self.status = "idle"
        self.deadline = None
        self.started_at = None
        self.remaining_seconds = 0
        self.elapsed_seconds = 0
        self.remaining_milliseconds = None
        self.elapsed_milliseconds = None
        self.pause_started_at = None
        if self.mode == "pomodoro":
            self.phase = "work"

    def finish_stopwatch(self, now=0.0):
        if self.mode != "stopwatch":
            return False
        if self.status == "running":
            state, now_ms = self._state(now)
            self._remember_elapsed(state, now_ms)
        self.started_at = None
        self.pause_started_at = None
        self.status = "finished"
        return True

    def next_phase(self):
        if self.mode != "pomodoro" or self.status != "finished":
            return False
        # Reuse upstream sequence advancement only after the explicit Next.
        # A pair repeats indefinitely here; unattended multi-round playback is
        # intentionally excluded by the product's manual-confirmation contract.
        phase = _PomodoroState(times_count=2, loop_count=2, time_index=0 if self.phase == 'work' else 1)
        if not _core().Catime_AdvancePomodoroState(ctypes.byref(phase)):
            return False
        self.phase = 'work' if phase.time_index == 0 else 'break'
        self.status = "idle"
        self.remaining_seconds = self.work_seconds if self.phase == "work" else self.break_seconds
        self.remaining_milliseconds = None
        return True

    def seconds(self, now=0.0):
        if self.mode == "stopwatch" or self.status == "running":
            state, now_ms = self._state(now)
            return _core().Catime_ReadSeconds(ctypes.byref(state), now_ms)
        return self.remaining_seconds

    def readout(self, now=0.0):
        if self.mode == "clock":
            return clock_readout(now, timezone=self.clock_timezone, show_traditional=self.show_traditional)
        if self.status == "finished" and self.mode != "stopwatch":
            return "已结束"
        if self.status == "idle" and self.mode == "countdown" and self.remaining_seconds <= 0:
            return "尚未开始"
        if self.status == "idle" and self.mode == "pomodoro" and self.remaining_seconds <= 0:
            return _format_seconds(self.work_seconds if self.phase == "work" else self.break_seconds)
        return _format_seconds(self.seconds(now))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict) or not raw:
            raise ValueError('存档计时状态无效')
        required = {'mode', 'status', 'deadline', 'remaining_seconds', 'started_at', 'elapsed_seconds'}
        if raw.get('mode') == 'countdown':
            required.add('countdown_seconds')
        elif raw.get('mode') == 'pomodoro':
            required.update(('phase', 'work_seconds', 'break_seconds'))
        if not required.issubset(raw):
            raise ValueError('存档计时缺少必要状态字段')
        allowed = cls.__dataclass_fields__
        timer = cls(**{key: value for key, value in raw.items() if key in allowed})
        if timer.mode not in ("clock", "countdown", "stopwatch", "pomodoro"):
            raise ValueError("存档计时模式无效")
        if timer.status not in ("idle", "running", "paused", "finished") or timer.phase not in ("work", "break"):
            raise ValueError("存档计时状态无效")
        for name in ("remaining_seconds", "elapsed_seconds", "countdown_seconds", "work_seconds", "break_seconds"):
            value = getattr(timer, name)
            if type(value) is not int or not 0 <= value <= _MAX_CORE_SECONDS:
                raise ValueError("存档计时时长无效")
        if min(timer.countdown_seconds, timer.work_seconds, timer.break_seconds) <= 0:
            raise ValueError("存档计时时长必须大于零")
        for name in ("deadline", "started_at", "pause_started_at"):
            value = getattr(timer, name)
            if value is not None:
                _timestamp_ms(value)
        for name in ('remaining_milliseconds', 'elapsed_milliseconds'):
            value = getattr(timer, name)
            if value is not None and (type(value) is not int or not 0 <= value <= _MAX_CORE_MS):
                raise ValueError('存档计时精度字段无效')
        if (timer.remaining_milliseconds is not None and
                (timer.remaining_milliseconds + 999) // 1000 != timer.remaining_seconds):
            raise ValueError('存档计时剩余精度与整秒字段不符')
        if (timer.elapsed_milliseconds is not None and
                timer.elapsed_milliseconds // 1000 != timer.elapsed_seconds):
            raise ValueError('存档计时已用精度与整秒字段不符')
        if timer.pause_started_at is not None and timer.status != 'paused':
            raise ValueError('存档计时暂停时间与状态不符')
        timer.preset_seconds = validate_presets(timer.preset_seconds)
        for name in ('tea_seconds', 'incense_seconds'):
            if type(getattr(timer, name)) is not int or not 1 <= getattr(timer, name) <= 86400:
                raise ValueError('茶与香的约定时长须为1秒至24小时')
        for name in ('show_traditional', 'sound_enabled', 'widget_enabled', 'notification_enabled'):
            if type(getattr(timer, name)) is not bool:
                raise ValueError('存档计时开关无效')
        if timer.clock_timezone not in ("local", "Asia/Shanghai"):
            raise ValueError("钟显时区无效")
        if timer.mode == "clock" and timer.status != "idle":
            raise ValueError("时钟不能保存为计时任务")
        if timer.status == "running":
            required = timer.started_at if timer.mode == "stopwatch" else timer.deadline
            if required is None:
                raise ValueError("运行中的计时缺少起点或截止时间")
        if timer.deadline is not None and (timer.status != 'running' or timer.mode == 'stopwatch'):
            raise ValueError('存档计时截止时间与状态不符')
        if timer.started_at is not None and (timer.status != 'running' or timer.mode != 'stopwatch'):
            raise ValueError('存档计时起点与状态不符')
        return timer


def _format_seconds(value):
    total = _checked_seconds(max(0, int(value)))
    buffer = ctypes.create_string_buffer(64)
    _core().Catime_FormatSeconds(total, buffer, len(buffer))
    return buffer.value.decode('ascii')
