"""Persisted attendant work driven by game dates and active elapsed seconds.

No wall-clock reads, randomness, rendering, inventory writes, or private timers.
The game model alone performs catches after this scheduler permits them.
"""
from dataclasses import asdict, dataclass, field
import datetime
import math
from zoneinfo import ZoneInfo

from . import tuning


ACTIONS = {'idle', 'walk', 'sweep', 'read', 'rest', 'practice', 'offer', 'catch', 'bell'}
SHORT_WORK = {'practice', 'offer', 'catch', 'bell'}


@dataclass
class RoutineState:
    game_date: str | None = None
    last_observed_wall: float | None = None
    calendar_rebased_wall: float | None = None
    last_offered_date: str | None = None
    offering_count: int = 1
    fruit_started_active: int = 0
    fruit_mature_after: int = tuning.FIRST_SPAWN_SECONDS
    practiced_periods: list[str] = field(default_factory=list)
    current_period: str | None = None
    night: bool = False
    action: str = 'offer'
    action_serial: int = 1
    action_started_active: int = 0
    action_duration: int = tuning.OFFER_SECONDS
    practice_period: str | None = None
    ambient_index: int = 0
    pending_capture: bool = False
    pending_bell: bool = False
    bell_trial_played: bool = False

    @classmethod
    def migrated(cls, elapsed_seconds):
        if elapsed_seconds == 0:
            return cls()
        # Old saves already had a supplied fruit plate. Preserve its age and all
        # existing game schedules; bind it to the first observed date on resume.
        return cls(action='idle', action_duration=0,
                   action_started_active=elapsed_seconds,
                   fruit_started_active=0)

    def fruit_stage(self, elapsed):
        age = max(0, elapsed - self.fruit_started_active)
        if age >= self.fruit_mature_after:
            return 'ripe'
        if age >= self.fruit_mature_after * tuning.FRUIT_SOFT_FRACTION:
            return 'soft'
        return 'fresh'

    def observe_calendar(self, now, timezone, elapsed):
        if now is None:
            return  # Legacy pure-active-time callers do not invent a calendar.
        if self.calendar_rebased_wall is not None:
            # The first batched heartbeat can begin just before the settings
            # command. Active seconds still count, but that overlap must not
            # rewind the freshly aligned date or interrupt an ongoing ritual.
            last_seen = self.last_observed_wall if self.last_observed_wall is not None else self.calendar_rebased_wall
            if now < max(self.calendar_rebased_wall, last_seen):
                return
            # An intervening place/bell command may also observe the calendar.
            # Keep the guard through the service's two-second heartbeat overlap
            # and until the short work preserved by the change has completed.
            if now >= self.calendar_rebased_wall + 2 and not self.occupied(elapsed):
                self.calendar_rebased_wall = None
        moment = datetime.datetime.fromtimestamp(now, ZoneInfo(timezone))
        interrupted = (self.last_observed_wall is not None
                       and not 0 <= now - self.last_observed_wall <= 2)
        self.last_observed_wall = now
        date = moment.date().isoformat()
        if self.game_date is None:
            self.game_date = date
            self.last_offered_date = date
        elif date != self.game_date:
            self.game_date = date
            self.practiced_periods = []
            # A missed previous-day ritual is never replayed on wake/reopen.
            if self.action in ('practice', 'offer'):
                self.action_duration = 0
        self.current_period = next((name for name, start, end in tuning.PRACTICE_WINDOWS
                                    if start <= moment.hour < end), None)
        self.night = moment.hour >= tuning.NIGHT_START_HOUR or moment.hour < tuning.NIGHT_END_HOUR
        # A ritual already begun while awake completes its 45 active seconds,
        # even just beyond the window edge. A sleep/close past that window does
        # not replay its remaining work when the app resumes hours later.
        if interrupted and self.action == 'practice' and self.practice_period != self.current_period:
            self.action_duration = 0

    def rebase_calendar(self, now, timezone):
        """Align an explicit zone change without granting or replaying work.

        The existing fruit and short action keep their active-time schedules.
        Mark only windows that already started in the new calendar; future
        windows and the next natural midnight retain their normal behavior.
        """
        moment = datetime.datetime.fromtimestamp(now, ZoneInfo(timezone))
        date = moment.date().isoformat()
        if date != self.game_date:
            self.practiced_periods = []
        for name, start, _ in tuning.PRACTICE_WINDOWS:
            if moment.hour >= start and name not in self.practiced_periods:
                self.practiced_periods.append(name)
        self.game_date = date
        self.last_offered_date = date
        self.last_observed_wall = now
        self.calendar_rebased_wall = now
        self.current_period = next((name for name, start, end in tuning.PRACTICE_WINDOWS
                                    if start <= moment.hour < end), None)
        self.night = moment.hour >= tuning.NIGHT_START_HOUR or moment.hour < tuning.NIGHT_END_HOUR

    def _start(self, action, elapsed, duration, period=None):
        self.action = action
        self.action_started_active = elapsed
        self.action_duration = duration
        self.action_serial += 1
        self.practice_period = period

    def occupied(self, elapsed):
        return (self.action in SHORT_WORK
                and elapsed < self.action_started_active + self.action_duration)

    def settle(self, elapsed, bell_equipped):
        if not bell_equipped:
            self.pending_bell = False
            if self.action == 'bell':
                self.action_duration = 0
        if self.occupied(elapsed):
            return
        needs_offer = self.game_date is not None and self.last_offered_date != self.game_date
        # Preserve a visible first-ripening heartbeat across midnight; otherwise
        # the new day's fruit would replace it in the exact first-spawn tick.
        first_ripening = (self.offering_count == 1
                          and elapsed <= self.fruit_started_active + self.fruit_mature_after)
        if needs_offer and not first_ripening:
            self.last_offered_date = self.game_date
            self.offering_count += 1
            self.fruit_started_active = elapsed
            self.fruit_mature_after = tuning.FRUIT_RIPEN_SECONDS
            self._start('offer', elapsed, tuning.OFFER_SECONDS)
            return
        if self.current_period is not None and self.current_period not in self.practiced_periods:
            self.practiced_periods.append(self.current_period)
            self._start('practice', elapsed, tuning.PRACTICE_SECONDS, self.current_period)
            return
        if self.pending_bell and bell_equipped:
            self.pending_bell = False
            self.bell_trial_played = True
            self._start('bell', elapsed, tuning.BELL_SECONDS)
            return
        ambient_running = self.action not in SHORT_WORK and elapsed < self.action_started_active + self.action_duration
        if ambient_running and (self.action == 'rest') == self.night:
            return
        if self.night:
            self._start('rest', elapsed, tuning.REST_SECONDS)
        else:
            action, duration = tuning.AMBIENT_CYCLE[self.ambient_index % len(tuning.AMBIENT_CYCLE)]
            self.ambient_index += 1
            self._start(action, elapsed, duration)

    def start_capture(self, elapsed):
        self.pending_capture = False
        self._start('catch', elapsed, tuning.CATCH_SECONDS)

    def request_bell(self, equipped):
        if equipped:
            self.pending_bell = True

    def snapshot(self, elapsed):
        progress = min(1.0, max(0.0, (elapsed - self.action_started_active) / max(1, self.action_duration)))
        return {'action': self.action, 'progress': progress,
                'action_duration': self.action_duration,
                'action_elapsed': min(self.action_duration, max(0, elapsed - self.action_started_active)),
                'fruit_stage': self.fruit_stage(elapsed), 'action_serial': self.action_serial,
                'game_date': self.game_date, 'practice_period': self.practice_period,
                'pending_bell': self.pending_bell, 'pending_capture': self.pending_capture}

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw, elapsed):
        if not isinstance(raw, dict):
            raise ValueError('存档日常状态无效')
        state = cls(**{key: value for key, value in raw.items() if key in cls.__dataclass_fields__})
        if state.action not in ACTIONS:
            raise ValueError('存档日常动作无效')
        for name in ('offering_count', 'fruit_started_active', 'fruit_mature_after',
                     'action_serial', 'action_started_active', 'action_duration', 'ambient_index'):
            value = getattr(state, name)
            if type(value) is not int or value < 0:
                raise ValueError('存档日常时序无效')
        if state.fruit_mature_after == 0 or state.offering_count == 0:
            raise ValueError('存档供果状态无效')
        for name in ('last_observed_wall', 'calendar_rebased_wall'):
            value = getattr(state, name)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError('存档日常日历时间无效')
        if max(state.fruit_started_active, state.action_started_active) > elapsed:
            raise ValueError('存档日常动作超出有效运行时间')
        for name in ('night', 'pending_capture', 'pending_bell', 'bell_trial_played'):
            if type(getattr(state, name)) is not bool:
                raise ValueError('存档日常开关无效')
        for name in ('game_date', 'last_offered_date'):
            value = getattr(state, name)
            if value is not None:
                datetime.date.fromisoformat(value)
        periods = {'morning', 'evening'}
        if (not isinstance(state.practiced_periods, list)
                or any(value not in periods for value in state.practiced_periods)
                or state.current_period not in (None, 'morning', 'evening')
                or state.practice_period not in (None, 'morning', 'evening')):
            raise ValueError('存档功课记录无效')
        return state
