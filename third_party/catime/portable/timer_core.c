/*
 * Derived from Catime, commit f47ed51044743d55e029872e7844ed6469a253dc.
 * Copyright Catime contributors. Licensed under Apache-2.0; ../upstream/LICENSE.
 *
 * Modified 2026-10-04 for Tianmu: Windows/global state becomes explicit state;
 * the caller supplies milliseconds. OS scheduling, rendering and notification
 * calls are removed. Arithmetic is widened to int64_t. The algorithm blocks
 * below are copied from the indicated upstream functions, not a second timer.
 */
#include "timer_core.h"
#include <stdbool.h>
#include <stdio.h>

#define DEFAULT_FALLBACK_TIME 60
#define CLOCK_COUNT_UP (state->count_up)
#define CLOCK_IS_PAUSED (state->paused)
#define CLOCK_TOTAL_TIME (state->total_seconds)
#define countdown_elapsed_time (state->countdown_elapsed_seconds)
#define countup_elapsed_time (state->countup_elapsed_seconds)
#define g_target_end_time (state->target_ms)
#define g_start_time (state->start_ms)
#define g_pause_start_time (state->pause_ms)
#define countdown_message_shown (state->completion_shown)
#define GetAbsoluteTimeMs() (now_ms)

/* timer.c:224-244, ResetTimer. Only platform-side display/baseline calls removed. */
void Catime_ResetTimer(CatimeTimerState* state, int64_t now_ms) {
    int64_t now = GetAbsoluteTimeMs();

    if (CLOCK_COUNT_UP) {
        countup_elapsed_time = 0;
        g_start_time = now;
    } else {
        countdown_elapsed_time = 0;
        if (CLOCK_TOTAL_TIME <= 0) {
            CLOCK_TOTAL_TIME = DEFAULT_FALLBACK_TIME;
        }
        g_target_end_time = now + ((int64_t)CLOCK_TOTAL_TIME * 1000);
    }

    CLOCK_IS_PAUSED = false;
    countdown_message_shown = false;
    g_pause_start_time = 0;
}

/* timer.c:247-266, TogglePauseTimer. A paused flag, rather than timestamp > 0,
 * also accepts a legitimate zero/negative epoch supplied by the host or tests. */
void Catime_TogglePauseTimer(CatimeTimerState* state, int64_t now_ms) {
    bool was_paused = CLOCK_IS_PAUSED;
    CLOCK_IS_PAUSED = !CLOCK_IS_PAUSED;

    int64_t now = GetAbsoluteTimeMs();

    if (CLOCK_IS_PAUSED && !was_paused) {
        g_pause_start_time = now;
    } else if (!CLOCK_IS_PAUSED && was_paused) {
        int64_t pause_duration = now - g_pause_start_time;
        g_target_end_time += pause_duration;
        g_start_time += pause_duration;
        g_pause_start_time = 0;
    }
}

/* timer_events_main.c:119-136, HandleMainTimer. Same floor/ceiling policy;
 * while paused, read at the recorded pause boundary. Keep ms for serialization. */
int64_t Catime_ReadMilliseconds(CatimeTimerState* state, int64_t now_ms) {
    int64_t currentTimeMs = CLOCK_IS_PAUSED ? g_pause_start_time : GetAbsoluteTimeMs();
    int64_t currentElapsedSec = 0;
    if (CLOCK_COUNT_UP) {
        int64_t elapsedMs = currentTimeMs - g_start_time;
        if (elapsedMs < 0) elapsedMs = 0;
        currentElapsedSec = elapsedMs / 1000;
        countup_elapsed_time = currentElapsedSec;
        return elapsedMs;
    } else {
        int64_t remainingMs = g_target_end_time - currentTimeMs;
        if (remainingMs < 0) remainingMs = 0;
        int64_t remainingSecRounded = remainingMs / 1000 + (remainingMs % 1000 != 0);
        currentElapsedSec = CLOCK_TOTAL_TIME - remainingSecRounded;
        if (currentElapsedSec > CLOCK_TOTAL_TIME) {
            currentElapsedSec = CLOCK_TOTAL_TIME;
        }
        if (currentElapsedSec < 0) currentElapsedSec = 0;
        countdown_elapsed_time = currentElapsedSec;
        /* Match upstream's whole-second upper clamp after a backward clock jump. */
        return remainingMs > CLOCK_TOTAL_TIME * 1000 ? CLOCK_TOTAL_TIME * 1000 : remainingMs;
    }
}

int64_t Catime_ReadSeconds(CatimeTimerState* state, int64_t now_ms) {
    Catime_ReadMilliseconds(state, now_ms);
    return CLOCK_COUNT_UP ? countup_elapsed_time : CLOCK_TOTAL_TIME - countdown_elapsed_time;
}

/* timer_events_main.c:138-155: retain the one-shot latch, emit a host event.
 * The host persists it before notifying; it decides when the next phase starts. */
int Catime_Tick(CatimeTimerState* state, int64_t now_ms) {
    if (CLOCK_IS_PAUSED) return false;
    Catime_ReadMilliseconds(state, now_ms);
    if (!CLOCK_COUNT_UP && CLOCK_TOTAL_TIME > 0 &&
        countdown_elapsed_time >= CLOCK_TOTAL_TIME) {
        if (!countdown_message_shown) {
            countdown_message_shown = true;
            return true;
        }
        countdown_elapsed_time = CLOCK_TOTAL_TIME;
    }
    return false;
}

#define pomodoro_initial_times_count (state->times_count)
#define pomodoro_initial_loop_count (state->loop_count)
#define current_pomodoro_time_index (state->time_index)
#define complete_pomodoro_cycles (state->complete_cycles)
#define FALSE false
#define TRUE true

/* timer_events_pomodoro.c:11-26, unchanged body; the host invokes only on Next. */
int Catime_AdvancePomodoroState(CatimePomodoroState* state) {
    if (pomodoro_initial_times_count == 0) {
        return FALSE;
    }

    current_pomodoro_time_index++;
    if (current_pomodoro_time_index >= pomodoro_initial_times_count) {
        current_pomodoro_time_index = 0;
        complete_pomodoro_cycles++;
        if (complete_pomodoro_cycles >= pomodoro_initial_loop_count) {
            return FALSE;
        }
    }

    return TRUE;
}

/* timer_format.c:11-15,36-39: same H/M/S decomposition, zero-padded text for
 * the existing Mac views; no Windows alignment spaces or system clock APIs. */
void Catime_FormatSeconds(int64_t seconds, char* output, size_t capacity) {
    if (!output || capacity == 0) return;
    if (seconds < 0) seconds = 0;
    int64_t hours = seconds / 3600;
    int64_t minutes = seconds % 3600 / 60;
    int64_t remainder = seconds % 60;
    if (hours > 0) snprintf(output, capacity, "%02lld:%02lld:%02lld",
                           (long long)hours, (long long)minutes, (long long)remainder);
    else snprintf(output, capacity, "%02lld:%02lld", (long long)minutes, (long long)remainder);
}
