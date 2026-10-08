"""Deterministic, UI-independent rules for the first playable Tianmu MVP."""

from dataclasses import dataclass, field
import random
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .timer import TimerSession
from .routine import RoutineState
from . import tuning
from .tuning import COLORS, PRICES, SHOP, AUTO_CAPTURE_LIMIT, DESKTOP_SOFT_LIMIT


ONBOARDING_STATES = frozenset(('shrine', 'capture', 'bottle', 'done', 'skipped', 'legacy'))
ONBOARDING_UNFINISHED = frozenset(('shrine', 'capture', 'bottle'))


def local_timezone():
    resolved = str(Path("/etc/localtime").resolve())
    if "zoneinfo/" in resolved:
        candidate = resolved.split("zoneinfo/", 1)[1]
        try:
            ZoneInfo(candidate)
            return candidate
        except (ValueError, KeyError):
            pass
    return "UTC"


@dataclass(frozen=True)
class Insect:
    id: str
    sex: str
    genotype: Tuple[str, str]
    color: str
    x: float
    y: float


@dataclass
class GameState:
    rng: object = field(repr=False)
    desktop: Dict[str, Insect] = field(default_factory=dict)
    bottle: Dict[str, Insect] = field(default_factory=dict)
    sold_ids: Set[str] = field(default_factory=set)
    discovered_colors: Set[str] = field(default_factory=set)
    coins: int = 0
    owned_items: Set[str] = field(default_factory=set)
    placed_item: Optional[str] = None
    placed_items: Dict[str, str] = field(default_factory=dict)
    elapsed_seconds: int = 0
    active_capture_seconds: int = 0
    next_insect_number: int = 1
    timer_deadline: Optional[float] = None
    timer_remaining: int = 0
    timer_completed: bool = False
    timer_session: TimerSession = field(default_factory=TimerSession)
    routine: RoutineState = field(default_factory=RoutineState)
    daily_sign_date: Optional[str] = None
    daily_sign: Optional[str] = None
    sign_history: Dict[str, str] = field(default_factory=dict)
    discovery_dates: Dict[str, str] = field(default_factory=dict)
    game_timezone: str = field(default_factory=local_timezone)
    onboarding: str = 'shrine'
    prices: Dict[str, int] = field(default_factory=lambda: dict(PRICES))
    _first_spawn_at: Optional[int] = tuning.FIRST_SPAWN_SECONDS
    _next_breed_at: Optional[int] = None
    _next_auto_capture_at: Optional[int] = None
    _next_empty_refill_at: Optional[int] = None

    @classmethod
    def new(cls, rng=None):
        return cls(rng=rng or random.Random())

    @property
    def desktop_count(self):
        return len(self.desktop)

    @property
    def auto_capture_paused(self):
        return self.active_capture_seconds >= AUTO_CAPTURE_LIMIT

    @staticmethod
    def color_for(genotype: Tuple[str, str]) -> str:
        first, second = genotype
        if "A" in first and "B" in second:
            return "普通褐色"
        if "A" in first:
            return "中褐色"
        if "B" in second:
            return "深褐色"
        return "白色"

    def _new_insect(self, sex: Optional[str] = None,
                    genotype: Tuple[str, str] = ("Aa", "Bb")) -> Insect:
        number = self.next_insect_number
        self.next_insect_number += 1
        return Insect(
            id="bug-{0:05d}".format(number),
            sex=sex or self.rng.choice(("F", "M")),
            genotype=genotype,
            color=self.color_for(genotype),
            x=self.rng.uniform(0.08, 0.92),
            y=self.rng.uniform(0.18, 0.78),
        )

    def make_offspring(self, mother_first: str, mother_second: str,
                       father_first: str, father_second: str) -> Insect:
        first = self.rng.choice(mother_first) + self.rng.choice(father_first)
        second = self.rng.choice(mother_second) + self.rng.choice(father_second)
        return self._new_insect(genotype=(first, second))

    def _add_initial_insects(self):
        for index in range(tuning.FIRST_SPAWN_COUNT):
            sex = "F" if index < tuning.FIRST_SPAWN_COUNT // 2 else "M"
            insect = self._new_insect(sex=sex, genotype=("Aa", "Bb"))
            self.desktop[insect.id] = insect

    def _add_refill_insects(self):
        if len(self.desktop) >= DESKTOP_SOFT_LIMIT:
            return
        for index in range(min(tuning.REFILL_COUNT, DESKTOP_SOFT_LIMIT - len(self.desktop))):
            insect = self._new_insect(sex="F" if index == 0 else "M")
            self.desktop[insect.id] = insect

    def _breed(self):
        if len(self.desktop) >= DESKTOP_SOFT_LIMIT:
            return
        females = [bug for bug in self.desktop.values() if bug.sex == "F"]
        males = [bug for bug in self.desktop.values() if bug.sex == "M"]
        if not females or not males:
            return
        birth_count = min(tuning.BREED_BATCH_MAX, DESKTOP_SOFT_LIMIT - len(self.desktop))
        for _ in range(birth_count):
            mother = self.rng.choice(females)
            father = self.rng.choice(males)
            child = self.make_offspring(
                mother.genotype[0], mother.genotype[1],
                father.genotype[0], father.genotype[1]
            )
            self.desktop[child.id] = child

    @property
    def bell_equipped(self):
        return 'bell' in self.owned_items and self.placed_items.get('bell') == 'bell'

    def sync_routine(self, now=None):
        self.routine.observe_calendar(now, self.game_timezone, self.elapsed_seconds)
        self.routine.settle(self.elapsed_seconds, self.bell_equipped)

    def request_bell(self, now=None):
        self.routine.request_bell(self.bell_equipped)
        self.sync_routine(now)

    def advance(self, seconds: int, now=None):
        """Advance only active seconds; ``now`` is the wall time at interval end.

        Calendar gaps are never replayed. A resumed one-second heartbeat uses
        only the current one-second interval even if days passed while closed.
        Optional ``now`` preserves existing pure simulation callers.
        """
        if seconds <= 0:
            return
        seconds = int(seconds)
        wall_start = None if now is None else now - seconds
        self.sync_routine(wall_start)
        for offset in range(1, seconds + 1):
            self.elapsed_seconds += 1
            event_time = self.elapsed_seconds
            self.active_capture_seconds = min(
                AUTO_CAPTURE_LIMIT,
                self.active_capture_seconds + 1,
            )
            wall_time = None if now is None else wall_start + offset
            self.sync_routine(wall_time)
            if self._first_spawn_at is not None and self._first_spawn_at <= event_time:
                self._add_initial_insects()
                self._first_spawn_at = None
                self._next_breed_at = event_time + tuning.BREED_INTERVAL_SECONDS
                self._next_auto_capture_at = event_time + tuning.AUTO_CAPTURE_INTERVAL_SECONDS
            if self._next_empty_refill_at is not None and self._next_empty_refill_at <= event_time:
                if not self.desktop and self.routine.fruit_stage(event_time) == 'ripe':
                    self._add_refill_insects()
                # If fruit is not ready, preserve this one overdue opportunity;
                # the first ripe active second may refill, with no backlog.
                if self.desktop:
                    self._next_empty_refill_at = None
                if self.desktop and self._next_breed_at is None:
                    self._next_breed_at = event_time + tuning.REFILL_FIRST_BREED_SECONDS
                if self.desktop and self._next_auto_capture_at is None:
                    self._next_auto_capture_at = event_time + tuning.AUTO_CAPTURE_INTERVAL_SECONDS
            if self._next_breed_at == event_time:
                self._breed()
                self._next_breed_at = event_time + tuning.BREED_INTERVAL_SECONDS
            if self._next_auto_capture_at == event_time:
                self.routine.pending_capture = bool(self.desktop) and not self.auto_capture_paused
                self._next_auto_capture_at = event_time + tuning.AUTO_CAPTURE_INTERVAL_SECONDS
            if self.auto_capture_paused or not self.desktop:
                self.routine.pending_capture = False
            if self.routine.pending_capture and not self.routine.occupied(event_time):
                insect = self.rng.choice(list(self.desktop.values()))
                if self.catch([insect.id], now=wall_time):
                    self.routine.start_capture(event_time)

    def catch(self, ids: Iterable[str], now=None) -> List[str]:
        zone = ZoneInfo(self.game_timezone)
        capture_time = datetime.datetime.now(zone) if now is None else datetime.datetime.fromtimestamp(now, zone)
        capture_date = capture_time.date().isoformat()
        moved = []
        for insect_id in dict.fromkeys(ids):
            insect = self.desktop.pop(insect_id, None)
            if insect is None:
                continue
            self.bottle[insect.id] = insect
            if insect.color not in self.discovered_colors:
                self.discovered_colors.add(insect.color)
                self.discovery_dates.setdefault(insect.color, capture_date)
            moved.append(insect.id)
        if moved and not self.desktop:
            self._next_empty_refill_at = self.elapsed_seconds + tuning.EMPTY_REFILL_SECONDS
            self._next_breed_at = None
            self._next_auto_capture_at = None
        return moved

    def _select_bottle(self, color: str, sex: Optional[str], count: int) -> List[str]:
        if count <= 0:
            return []
        matches = [bug for bug in self.bottle.values()
                   if bug.color == color and (sex is None or bug.sex == sex)]
        return [bug.id for bug in matches[:count]]

    def quote_sale(self, color: str, sex: Optional[str], count: int):
        """Preview sale IDs and proceeds without changing inventory or clocks."""
        selected = self._select_bottle(color, sex, count)
        amount = sum(self.prices[self.bottle[insect_id].color] for insect_id in selected)
        return selected, amount

    def release(self, color: str, sex: Optional[str], count: int) -> List[str]:
        selected = self._select_bottle(color, sex, count)
        if not selected:
            return []
        for insect_id in selected:
            self.desktop[insect_id] = self.bottle.pop(insect_id)
        self.active_capture_seconds = 0
        self._next_empty_refill_at = None
        if self._next_breed_at is None:
            self._next_breed_at = self.elapsed_seconds + tuning.BREED_INTERVAL_SECONDS
        if self._next_auto_capture_at is None:
            self._next_auto_capture_at = self.elapsed_seconds + tuning.AUTO_CAPTURE_INTERVAL_SECONDS
        return selected

    def sell(self, color: str, sex: Optional[str], count: int) -> List[str]:
        selected = self._select_bottle(color, sex, count)
        return self.sell_ids(selected)

    def sell_ids(self, insect_ids: Iterable[str]) -> List[str]:
        """Sell exactly the confirmed bottle IDs, failing atomically if stale."""
        selected = list(dict.fromkeys(insect_ids))
        if not selected:
            return []
        if any(insect_id not in self.bottle for insect_id in selected):
            return []
        total = sum(self.prices[self.bottle[insect_id].color] for insect_id in selected)
        for insect_id in selected:
            self.bottle.pop(insect_id)
            self.sold_ids.add(insect_id)
        self.coins += total
        self.active_capture_seconds = 0
        return selected

    @property
    def shrine_stage(self):
        return {"shrine_g1": 1, "shrine_g2": 2}.get(self.placed_items.get("shrine"), 0)

    def purchase_unavailable_reason(self, item_id: str) -> Optional[str]:
        """New purchase policy; existing ownership and placement stay valid."""
        item = SHOP.get(item_id)
        if item is None:
            return '物件不存在'
        if item_id in self.owned_items:
            return '已拥有'
        if item.get('requires') is not None and item['requires'] not in self.owned_items:
            return '先整修神龛'
        if self.coins < item['price']:
            return '铜钱不足'
        return None

    def buy(self, item_id: str) -> bool:
        if self.purchase_unavailable_reason(item_id) is not None:
            return False
        self.coins -= SHOP[item_id]['price']
        self.owned_items.add(item_id)
        return True

    def place(self, item_id: str) -> bool:
        if item_id not in self.owned_items:
            return False
        slot = SHOP[item_id]["slot"]
        if self.placed_items.get(slot) == item_id:
            self.placed_items.pop(slot)
        else:
            self.placed_items[slot] = item_id
        self.placed_item = self.placed_items.get("plate")
        if item_id == 'bell':
            if self.bell_equipped and not self.routine.bell_trial_played:
                self.routine.request_bell(True)
            elif not self.bell_equipped:
                self.routine.pending_bell = False
        return True
