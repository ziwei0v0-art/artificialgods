"""Differential tests against compiled, unmodified upstream function bodies.

Only the oracle's Windows paint/scheduler/notification endpoints are stubbed.
Neither implementation reads a user save, launches a worker, or opens windows.
"""

import ctypes
import hashlib
import json
from pathlib import Path
import random
import re
import subprocess
import tempfile
import unittest

from tianmu_mvp.timer import TimerSession, _CoreState, _PomodoroState, _core


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'third_party/catime'


def upstream_function(path, name):
    source = (VENDOR / 'upstream' / path).read_text()
    match = re.search(r'(?m)^(?:static )?(?:void|BOOL|int)\s+' + name + r'\([^;]*?\)\s*\{', source)
    if not match:
        raise AssertionError('Missing upstream function: ' + name)
    opening = source.index('{', match.start())
    depth = 1
    for offset in range(opening + 1, len(source)):
        depth += (source[offset] == '{') - (source[offset] == '}')
        if depth == 0:
            return source[match.start():offset + 1]
    raise AssertionError('Incomplete upstream function: ' + name)


ORACLE_PRELUDE = r'''
#include <stdbool.h>
#include <stdint.h>
#include "timer_core.h"
typedef int BOOL;
typedef unsigned int UINT;
typedef uint32_t DWORD;
typedef void* HWND;
#define TRUE true
#define FALSE false
#define DEFAULT_FALLBACK_TIME 60
static bool CLOCK_COUNT_UP, CLOCK_IS_PAUSED, CLOCK_SHOW_CURRENT_TIME, CLOCK_IS_DRAGGING;
static bool countdown_message_shown;
static int CLOCK_TOTAL_TIME, countdown_elapsed_time, countup_elapsed_time;
static int last_displayed_second;
static int64_t g_target_end_time, g_start_time, g_pause_start_time, oracle_now;
static int oracle_notifications;
static int pomodoro_initial_times_count, pomodoro_initial_loop_count;
static int current_pomodoro_time_index, complete_pomodoro_cycles;
static int64_t GetAbsoluteTimeMs(void) { return oracle_now; }
static DWORD GetTickCount(void) { return (DWORD)oracle_now; }
static UINT GetTimerInterval(void) { return 1000; }
static void InitializeHighPrecisionTimer(void) {}
static void ResetMillisecondAccumulator(void) {}
static void PauseTimerMilliseconds(void) {}
static void MainTimer_SetInterval(UINT ignored) { (void)ignored; }
static void TryRestorePendingWindowPosition(HWND ignored) { (void)ignored; }
static void EnforceTopmostOverTaskbar(HWND ignored) { (void)ignored; }
static BOOL TimerEvents_ShouldRenderMainTimer(void) { return FALSE; }
static void TimerEvents_RequestWindowRepaint(HWND ignored) { (void)ignored; }
static void TrayAnimation_RecomputeTimerDelay(void) {}
static BOOL TimerEvents_IsActivePomodoroTimer(void) { return FALSE; }
static BOOL TimerEvents_HandlePomodoroCompletion(HWND ignored) { (void)ignored; return FALSE; }
static void TimerEvents_HandleCountdownCompletion(HWND ignored) { (void)ignored; oracle_notifications++; }
static BOOL TimerEvents_ShouldCheckActiveTimerRender(int sec, int* last, BOOL* has) {
    (void)sec; (void)last; (void)has; return FALSE;
}
'''

ORACLE_BRIDGE = r'''
static void Load(CatimeTimerState* state, int64_t now) {
    CLOCK_COUNT_UP = state->count_up; CLOCK_IS_PAUSED = state->paused;
    countdown_message_shown = state->completion_shown;
    CLOCK_TOTAL_TIME = (int)state->total_seconds;
    countdown_elapsed_time = (int)state->countdown_elapsed_seconds;
    countup_elapsed_time = (int)state->countup_elapsed_seconds;
    g_target_end_time = state->target_ms; g_start_time = state->start_ms;
    g_pause_start_time = state->pause_ms; oracle_now = now;
}
static void Save(CatimeTimerState* state) {
    state->count_up = CLOCK_COUNT_UP; state->paused = CLOCK_IS_PAUSED;
    state->completion_shown = countdown_message_shown;
    state->total_seconds = CLOCK_TOTAL_TIME;
    state->countdown_elapsed_seconds = countdown_elapsed_time;
    state->countup_elapsed_seconds = countup_elapsed_time;
    state->target_ms = g_target_end_time; state->start_ms = g_start_time;
    state->pause_ms = g_pause_start_time;
}
void Oracle_Reset(CatimeTimerState* state, int64_t now) { Load(state, now); ResetTimer(); Save(state); }
void Oracle_Pause(CatimeTimerState* state, int64_t now) { Load(state, now); TogglePauseTimer(); Save(state); }
int Oracle_Tick(CatimeTimerState* state, int64_t now) {
    Load(state, now); int before = oracle_notifications; HandleMainTimer(NULL); Save(state);
    return oracle_notifications - before;
}
int Oracle_Pomodoro(CatimePomodoroState* state) {
    pomodoro_initial_times_count = state->times_count;
    pomodoro_initial_loop_count = state->loop_count;
    current_pomodoro_time_index = state->time_index;
    complete_pomodoro_cycles = state->complete_cycles;
    int result = TimerEvents_AdvancePomodoroState();
    state->time_index = current_pomodoro_time_index;
    state->complete_cycles = complete_pomodoro_cycles;
    return result;
}
'''


class CatimeCoreDifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='tianmu-catime-oracle-')
        folder = Path(cls.temporary.name)
        source = ORACLE_PRELUDE + '\n'.join([
            upstream_function('src/timer/timer.c', 'ResetTimer'),
            upstream_function('src/timer/timer.c', 'TogglePauseTimer'),
            upstream_function('src/timer/timer_events_main.c', 'HandleMainTimer'),
            upstream_function('src/timer/timer_events_pomodoro.c', 'TimerEvents_AdvancePomodoroState'),
        ]) + ORACLE_BRIDGE
        (folder / 'oracle.c').write_text(source)
        subprocess.run(['clang', '-dynamiclib', '-O2', '-std=c11', '-I', str(VENDOR / 'portable'),
                        str(folder / 'oracle.c'), '-o', str(folder / 'oracle.dylib')],
                       check=True, capture_output=True, timeout=30)
        cls.oracle = ctypes.CDLL(str(folder / 'oracle.dylib'))
        for name, result in (('Oracle_Reset', None), ('Oracle_Pause', None), ('Oracle_Tick', ctypes.c_int)):
            function = getattr(cls.oracle, name)
            function.argtypes = (ctypes.POINTER(_CoreState), ctypes.c_int64)
            function.restype = result
        cls.oracle.Oracle_Pomodoro.argtypes = (ctypes.POINTER(_PomodoroState),)
        cls.oracle.Oracle_Pomodoro.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_vendored_core_originals_match_official_git_blobs(self):
        manifest = json.loads((VENDOR / 'UPSTREAM_CORE.json').read_text())
        self.assertEqual(manifest['commit'], 'f47ed51044743d55e029872e7844ed6469a253dc')
        for row in manifest['files']:
            data = (VENDOR / 'upstream' / row['path']).read_bytes()
            git_blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            self.assertEqual(git_blob, row['git_blob_sha'], row['path'])

    def test_native_timer_matches_upstream_across_jitter_pause_resume_and_expiry(self):
        rng = random.Random(167)
        for count_up in (0, 1):
            for duration in (1, 60, 1500):
                with self.subTest(count_up=count_up, duration=duration):
                    actual = _CoreState(count_up=count_up, total_seconds=duration)
                    expected = _CoreState(count_up=count_up, total_seconds=duration)
                    now = 100000
                    _core().Catime_ResetTimer(ctypes.byref(actual), now)
                    self.oracle.Oracle_Reset(ctypes.byref(expected), now)
                    for index in range(400):
                        now += rng.randrange(1, 2101)
                        real_event = _core().Catime_Tick(ctypes.byref(actual), now)
                        oracle_event = self.oracle.Oracle_Tick(ctypes.byref(expected), now)
                        self.assertEqual(real_event, oracle_event)
                        for field in ('target_ms', 'start_ms', 'pause_ms', 'paused', 'completion_shown',
                                      'countdown_elapsed_seconds', 'countup_elapsed_seconds'):
                            self.assertEqual(getattr(actual, field), getattr(expected, field), (index, field))
                        if index % 7 == 0:
                            _core().Catime_TogglePauseTimer(ctypes.byref(actual), now)
                            self.oracle.Oracle_Pause(ctypes.byref(expected), now)

    def test_session_readouts_follow_upstream_pause_resume_sequence(self):
        for mode in ('countdown', 'stopwatch'):
            with self.subTest(mode=mode):
                timer = TimerSession(countdown_seconds=60)
                timer.start(mode, now=100)
                oracle = _CoreState(count_up=mode == 'stopwatch', total_seconds=60)
                self.oracle.Oracle_Reset(ctypes.byref(oracle), 100000)
                for index in range(40):
                    now = 100000 + index * 10000 + 333
                    self.oracle.Oracle_Tick(ctypes.byref(oracle), now)
                    expected = oracle.countup_elapsed_seconds if oracle.count_up else 60 - oracle.countdown_elapsed_seconds
                    self.assertEqual(timer.seconds(now=now / 1000), expected)
                    timer.pause(now=now / 1000)
                    self.oracle.Oracle_Pause(ctypes.byref(oracle), now)
                    # The serialized host adapter must not lose the oracle's fraction.
                    timer = TimerSession.from_dict(json.loads(json.dumps(timer.to_dict())))
                    resume = now + 9667
                    timer.resume(now=resume / 1000)
                    self.oracle.Oracle_Pause(ctypes.byref(oracle), resume)
                self.oracle.Oracle_Tick(ctypes.byref(oracle), resume)
                expected = oracle.countup_elapsed_seconds if oracle.count_up else 60 - oracle.countdown_elapsed_seconds
                self.assertEqual(timer.seconds(now=resume / 1000), expected)

    def test_pomodoro_sequence_and_cycle_end_match_unmodified_upstream(self):
        for count in (0, 1, 2, 4):
            for loops in (1, 3):
                actual = _PomodoroState(times_count=count, loop_count=loops)
                expected = _PomodoroState(times_count=count, loop_count=loops)
                for index in range(max(1, count * loops)):
                    self.assertEqual(_core().Catime_AdvancePomodoroState(ctypes.byref(actual)),
                                     self.oracle.Oracle_Pomodoro(ctypes.byref(expected)))
                    self.assertEqual((actual.time_index, actual.complete_cycles),
                                     (expected.time_index, expected.complete_cycles))

    def test_zero_epoch_pause_is_supported_by_the_documented_host_adapter(self):
        state = _CoreState(count_up=1)
        _core().Catime_ResetTimer(ctypes.byref(state), 0)
        _core().Catime_TogglePauseTimer(ctypes.byref(state), 0)
        _core().Catime_TogglePauseTimer(ctypes.byref(state), 10000)
        self.assertEqual(_core().Catime_ReadMilliseconds(ctypes.byref(state), 11001), 1001)


if __name__ == '__main__':
    unittest.main()
