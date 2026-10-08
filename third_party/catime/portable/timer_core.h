/* Catime f47ed51044743d55e029872e7844ed6469a253dc, Apache-2.0.
 * Platform adapter: explicit per-session state and caller-provided milliseconds.
 * See ../README.md for upstream function/line mappings and modifications. */
#ifndef TIANMU_CATIME_TIMER_CORE_H
#define TIANMU_CATIME_TIMER_CORE_H

#include <stdint.h>
#include <stddef.h>

typedef struct {
    int count_up;
    int paused;
    int completion_shown;
    int64_t total_seconds;
    int64_t countdown_elapsed_seconds;
    int64_t countup_elapsed_seconds;
    int64_t target_ms;
    int64_t start_ms;
    int64_t pause_ms;
} CatimeTimerState;

typedef struct {
    int times_count;
    int loop_count;
    int time_index;
    int complete_cycles;
} CatimePomodoroState;

void Catime_ResetTimer(CatimeTimerState* state, int64_t now_ms);
void Catime_TogglePauseTimer(CatimeTimerState* state, int64_t now_ms);
int64_t Catime_ReadMilliseconds(CatimeTimerState* state, int64_t now_ms);
int64_t Catime_ReadSeconds(CatimeTimerState* state, int64_t now_ms);
int Catime_Tick(CatimeTimerState* state, int64_t now_ms);
int Catime_AdvancePomodoroState(CatimePomodoroState* state);
void Catime_FormatSeconds(int64_t seconds, char* output, size_t capacity);

#endif
