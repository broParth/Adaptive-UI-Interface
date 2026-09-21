"""
state_engine.py — Cognitive State Engine (FSM)
Finite State Machine that classifies user behavior into 5 states:
  - IDLE: No activity for 5.0+ seconds
  - BROWSING: Normal active computer use (reading, casual mouse movement, occasional clicks, scrolling)
  - FOCUS: Sustained concentrated interaction (typing with minimal pointer/scroll)
  - ACTIVE: High-intensity bursts (rapid mouse translation, click bursts, fast scrolling)
  - ASSIST: Specific interaction struggle / anomaly (e.g. rapid in-place rage clicking)

Production Enhancements:
  - Time-based 1.0s sliding window smoothing (invariant to cycle intervals)
  - History updated on EVERY path before evaluation (no stale history)
  - ASSIST evaluated before generic click fast-paths
  - Explicit numerical entry/exit hysteresis for ACTIVE and FOCUS
  - Multi-state ASSIST exit (re-classifies to appropriate state, not blindly forced to BROWSING)
  - Monotonic time (time.perf_counter) throughout
  - Injectable `now` parameter for deterministic testing without time.sleep()
"""

import time
import logging
from collections import deque

logger = logging.getLogger("AdaptiveUI.FSM")

# ─── Configurable Hysteresis Thresholds ───────────────────────────────────────
# ACTIVE: High-intensity interaction
ACTIVE_ENTRY_MOVE = 250.0      # px/s
ACTIVE_ENTRY_CLICKS = 2.5      # clicks/s
ACTIVE_ENTRY_SCROLLS = 1.5     # scrolls/s

ACTIVE_EXIT_MOVE = 140.0       # px/s
ACTIVE_EXIT_CLICKS = 1.0       # clicks/s
ACTIVE_EXIT_SCROLLS = 0.5      # scrolls/s

# FOCUS: Sustained concentrated typing
FOCUS_ENTRY_KEYS = 2.0         # keys/s (~24+ WPM)
FOCUS_ENTRY_MAX_MOVE = 40.0    # px/s (resting hand drift tolerance)
FOCUS_ENTRY_MAX_SCROLL = 0.5   # scrolls/s

FOCUS_EXIT_KEYS = 0.8          # keys/s (below ~9 WPM drops out)
FOCUS_EXIT_BREAK_MOVE = 80.0   # px/s (deliberate pointer move breaks focus)
FOCUS_EXIT_BREAK_SCROLL = 1.0  # scrolls/s (deliberate scroll breaks focus)

# ASSIST: Specific interaction anomaly
ASSIST_ENTRY_CLICKS = 4.0      # clicks/s
ASSIST_ENTRY_MAX_MOVE = 30.0   # px/s (in-place clicking on frozen target)

# IDLE: Absence of interaction
IDLE_THRESHOLD = 5.0           # seconds


class StateEngine:
    """
    Behavior Classification Finite State Machine.
    Classifies user behavior based on sliding-window metrics.
    """

    VALID_STATES = ("IDLE", "BROWSING", "FOCUS", "ACTIVE", "ASSIST")
    STATE_ALIASES = {
        "NORMAL": "BROWSING",
        "ERROR": "ASSIST",
        "ANOMALY": "ASSIST",
    }

    def __init__(self, window_duration=1.0):
        self.window_duration = window_duration
        self.current_state = "IDLE"
        self.state_start_time = time.perf_counter()
        self.log = []  # List of (timestamp_str, old_state, new_state, duration)

        # Sliding window history: stores (timestamp, clicks, keys, move_dist, scrolls, dt)
        self._history = deque()

        # Hold times (monotonic timestamps)
        self.active_hold_until = 0.0
        self.focus_hold_until = 0.0
        self.assist_hold_until = 0.0

    @classmethod
    def normalize_state(cls, state):
        """Map legacy or alternative state names to canonical names."""
        return cls.STATE_ALIASES.get(state, state)

    def _update_window_history(self, metrics, now):
        """
        Record current cycle metrics and prune samples outside the time window.
        Always executed first on every cycle to eliminate stale history bugs.
        """
        dt = metrics.get("elapsed_sec", 0.1)
        if dt <= 0:
            dt = 0.001

        clicks = metrics.get("raw_clicks", metrics.get("clicks_per_sec", 0.0) * dt)
        keys = metrics.get("raw_keys", metrics.get("keys_per_sec", 0.0) * dt)
        move = metrics.get("raw_move", metrics.get("movement_per_sec", 0.0) * dt)
        scrolls = metrics.get("raw_scrolls", metrics.get("scrolls_per_sec", 0.0) * dt)

        self._history.append((now, clicks, keys, move, scrolls, dt))

        # Prune samples older than the sliding window duration
        cutoff = now - self.window_duration
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

    def _compute_window_rates(self):
        """
        Compute smoothed rate-per-second across the sliding time window.
        Uses max(total_dt, window_duration) as effective baseline duration
        to prevent single isolated events in a tiny slice from computing false high rates.
        """
        if not self._history:
            return {
                "clicks_per_sec": 0.0,
                "keys_per_sec": 0.0,
                "movement_per_sec": 0.0,
                "scrolls_per_sec": 0.0,
            }

        total_clicks = sum(item[1] for item in self._history)
        total_keys = sum(item[2] for item in self._history)
        total_move = sum(item[3] for item in self._history)
        total_scrolls = sum(item[4] for item in self._history)
        total_dt = sum(item[5] for item in self._history)

        effective_duration = max(total_dt, self.window_duration)

        return {
            "clicks_per_sec": total_clicks / effective_duration,
            "keys_per_sec": total_keys / effective_duration,
            "movement_per_sec": total_move / effective_duration,
            "scrolls_per_sec": total_scrolls / effective_duration,
        }

    def _transition_to(self, target_state, now):
        """Record transition log entry if state changes and update state metadata."""
        target_state = self.normalize_state(target_state)
        prev = self.current_state

        if target_state != prev:
            duration = round(now - self.state_start_time, 1)
            self.log.append((
                time.strftime("%H:%M:%S"),
                prev,
                target_state,
                duration,
            ))
            self.current_state = target_state
            self.state_start_time = now

            if len(self.log) > 100:
                self.log = self.log[-100:]

            logger.info("State transition: %s -> %s (held %.1fs)", prev, target_state, duration)

        return self.current_state

    def determine_state(self, metrics, now=None):
        """
        Classify user behavior into one of: IDLE, BROWSING, FOCUS, ACTIVE, ASSIST.

        Args:
            metrics: dict containing rates, raw counts, idle_time, and flags.
            now: Monotonic timestamp (time.perf_counter), injectable for deterministic testing.

        Returns:
            str: The active FSM state.
        """
        if now is None:
            now = time.perf_counter()

        # ─── 1. Update rolling history first on every path ──────────────────
        self._update_window_history(metrics, now)
        smoothed = self._compute_window_rates()

        idle_time = metrics.get("idle_time", 0.0)

        # ─── 2. IDLE Check (Strict boundary: >= 5.0 seconds) ────────────────
        if idle_time >= IDLE_THRESHOLD:
            self._history.clear()
            self.active_hold_until = 0.0
            self.focus_hold_until = 0.0
            self.assist_hold_until = 0.0
            return self._transition_to("IDLE", now)

        # ─── 3. ASSIST Anomaly Evaluation (Priority over ACTIVE bursts) ─────
        # Specific anomaly: rage clicking (rapid clicking in place with no typing)
        if (
            smoothed["clicks_per_sec"] >= ASSIST_ENTRY_CLICKS
            and smoothed["movement_per_sec"] < ASSIST_ENTRY_MAX_MOVE
            and smoothed["keys_per_sec"] == 0.0
        ):
            self.assist_hold_until = now + 1.2
            return self._transition_to("ASSIST", now)

        # ─── 4. Hold-time guards ────────────────────────────────────────────
        if self.current_state == "ASSIST":
            if now < self.assist_hold_until:
                return "ASSIST"
            # Once assist_hold_until expires, fall through to re-classify into ACTIVE, FOCUS, or BROWSING

        if self.current_state == "ACTIVE" and now < self.active_hold_until:
            return "ACTIVE"

        if self.current_state == "FOCUS" and now < self.focus_hold_until:
            return "FOCUS"

        # ─── 5. High-Intensity ACTIVE Evaluation (with Hysteresis) ──────────
        if self.current_state == "ACTIVE":
            # Exit condition: interaction settles below exit thresholds
            if (
                smoothed["movement_per_sec"] < ACTIVE_EXIT_MOVE
                and smoothed["clicks_per_sec"] < ACTIVE_EXIT_CLICKS
                and smoothed["scrolls_per_sec"] < ACTIVE_EXIT_SCROLLS
            ):
                # Dropped out of ACTIVE; continue evaluating FOCUS / BROWSING
                pass
            else:
                return "ACTIVE"
        else:
            # Entry condition: high-intensity burst
            if (
                smoothed["movement_per_sec"] >= ACTIVE_ENTRY_MOVE
                or smoothed["clicks_per_sec"] >= ACTIVE_ENTRY_CLICKS
                or smoothed["scrolls_per_sec"] >= ACTIVE_ENTRY_SCROLLS
            ):
                self.active_hold_until = now + 0.5
                return self._transition_to("ACTIVE", now)

        # ─── 6. Sustained FOCUS Evaluation (with Hysteresis) ────────────────
        if self.current_state == "FOCUS":
            # Exit condition: typing stops or deliberate pointer/scroll movement occurs
            if (
                smoothed["keys_per_sec"] < FOCUS_EXIT_KEYS
                or smoothed["movement_per_sec"] > FOCUS_EXIT_BREAK_MOVE
                or smoothed["scrolls_per_sec"] >= FOCUS_EXIT_BREAK_SCROLL
            ):
                # Dropped out of FOCUS; continue evaluating BROWSING
                pass
            else:
                return "FOCUS"
        else:
            # Entry condition: sustained typing with calm mouse/scroll
            if (
                smoothed["keys_per_sec"] >= FOCUS_ENTRY_KEYS
                and smoothed["movement_per_sec"] <= FOCUS_ENTRY_MAX_MOVE
                and smoothed["scrolls_per_sec"] < FOCUS_ENTRY_MAX_SCROLL
            ):
                self.focus_hold_until = now + 0.6
                return self._transition_to("FOCUS", now)

        # ─── 7. Default State: BROWSING ─────────────────────────────────────
        # Ordinary computer use: reading, casual cursor movement, occasional clicks, normal scrolling
        return self._transition_to("BROWSING", now)

    def get_state_duration(self, now=None):
        """How long the system has been in the current state in seconds."""
        current_time = time.perf_counter() if now is None else now
        return round(current_time - self.state_start_time, 1)

    def get_log(self, n=50):
        """Return last n transition entries."""
        return self.log[-n:]
