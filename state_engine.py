"""
state_engine.py — Cognitive State Engine (FSM)
Finite State Machine that classifies user behavior into 4 states.
Maintains a transition log for the UI dashboard.

Production Fixes:
  - Moving averages for movement and scroll (3 cycle / 1.5s window)
  - ACTIVE now triggers on cursor movement or scroll, not just clicks
  - Scroll fast-path: scroll activity immediately triggers ACTIVE (no smoothing)
  - FOCUS protected by scroll inactivity guard
  - Thresholds are hardware-calibrated defaults (configurable)
"""

import time
import logging

logger = logging.getLogger("AdaptiveUI.FSM")

# ─── Configurable Thresholds ──────────────────────────────────────────────────
# NOTE: These thresholds are hardware-calibrated and may vary by
# DPI, touchpad sensitivity, and screen resolution.

LOW_MOVE = 50           # Max movement/sec allowed in FOCUS (typing drift tolerance)
MOVE_THRESHOLD = 200    # Min movement/sec to trigger ACTIVE
SCROLL_THRESHOLD = 1    # Min scroll/sec to trigger ACTIVE (lowered from 5 for reliability)


class StateEngine:
    """
    Behavior Classification FSM.
    Determines user state based on input metrics.

    States:
        IDLE   — No activity for 5+ seconds
        FOCUS  — Active typing with minimal mouse/scroll
        ACTIVE — High click rate, cursor movement, or scrolling
        ERROR  — Low/ambiguous activity (Error Assistance Mode)
    """

    VALID_STATES = ("IDLE", "FOCUS", "ACTIVE", "ERROR")

    def __init__(self):
        self.current_state = "IDLE"
        self.state_start_time = time.time()
        self.log = []  # List of (timestamp_str, old_state, new_state, duration)

        # FSM Smoothing — Moving Average Histories (3-cycle / 1.5s window)
        self.click_history = []
        self.key_history = []
        self.move_history = []
        self.scroll_history = []

        # Debouncing
        self.candidate_state = "IDLE"
        self.candidate_count = 0
        self.active_hold_until = 0.0
        self.focus_hold_until = 0.0

    def determine_state(self, metrics):
        """
        Classify user behavior based on metrics.

        FSM Priority Order (interaction-aware):
            0.  Instant Click  → ACTIVE (fast-path, bypasses smoothing)
            0a. Scroll Activity → ACTIVE (fast-path, bypasses smoothing)
            0b. Instant Typing  → FOCUS  (fast-path, bypasses smoothing)
            1.  IDLE   — idle_time > 5s
            2.  FOCUS  — keys/sec > 2, low movement, low scroll
            3.  ACTIVE — clicks/sec > 3 OR movement > threshold OR scroll > threshold
            4.  ERROR  — everything else (fallback, never reached during scrolling)
        """
        prev = self.current_state
        now = time.time()

        idle_time = metrics["idle_time"]
        raw_keys_per_sec = metrics["keys_per_sec"]
        raw_clicks_per_sec = metrics["clicks_per_sec"]
        raw_move_per_sec = metrics["movement_per_sec"]
        raw_scroll_per_sec = metrics["scrolls_per_sec"]

        # 0. Fast-path click response
        if metrics.get("instant_click", False):
            self.active_hold_until = now + 0.4  # Minimum 400ms hold
            # Bypass smoothing and debouncing
            self.candidate_state = "ACTIVE"
            self.candidate_count = 2
            
            if prev != "ACTIVE":
                duration = round(now - self.state_start_time, 1)
                self.log.append((
                    time.strftime("%H:%M:%S"),
                    prev,
                    "ACTIVE",
                    duration
                ))
                self.current_state = "ACTIVE"
                self.state_start_time = now
                
                if len(self.log) > 100:
                    self.log = self.log[-100:]
            return "ACTIVE"

        # 0a. Fast-path scroll response (priority 2 — scroll is intentional user activity)
        #     Bypasses moving averages, debounce delays, and candidate buffering.
        if metrics.get("instant_scroll", False) or raw_scroll_per_sec > 0:
            self.active_hold_until = now + 0.4  # Minimum 400ms hold
            self.candidate_state = "ACTIVE"
            self.candidate_count = 2

            if prev != "ACTIVE":
                duration = round(now - self.state_start_time, 1)
                self.log.append((
                    time.strftime("%H:%M:%S"),
                    prev,
                    "ACTIVE",
                    duration
                ))
                self.current_state = "ACTIVE"
                self.state_start_time = now

                if len(self.log) > 100:
                    self.log = self.log[-100:]

            logger.debug("Scroll fast-path → ACTIVE (scroll/sec=%.1f)", raw_scroll_per_sec)
            return "ACTIVE"

        # 0b. Fast-path typing response (priority 3 — only if ACTIVE interrupt not active)
        if metrics.get("instant_typing", False):
            # Only trigger FOCUS if no active click interrupt and movement is low
            if now >= self.active_hold_until and raw_move_per_sec < LOW_MOVE and raw_clicks_per_sec <= 0:
                self.focus_hold_until = now + 0.6  # Minimum 600ms hold
                self.candidate_state = "FOCUS"
                self.candidate_count = 2

                if prev != "FOCUS":
                    duration = round(now - self.state_start_time, 1)
                    self.log.append((
                        time.strftime("%H:%M:%S"),
                        prev,
                        "FOCUS",
                        duration
                    ))
                    self.current_state = "FOCUS"
                    self.state_start_time = now

                    if len(self.log) > 100:
                        self.log = self.log[-100:]
                return "FOCUS"

        # 1. Moving Average Smoothing (3-cycle window = 1.5s)
        self.click_history.append(raw_clicks_per_sec)
        self.key_history.append(raw_keys_per_sec)
        self.move_history.append(raw_move_per_sec)
        self.scroll_history.append(raw_scroll_per_sec)

        if len(self.click_history) > 3:
            self.click_history.pop(0)
        if len(self.key_history) > 3:
            self.key_history.pop(0)
        if len(self.move_history) > 3:
            self.move_history.pop(0)
        if len(self.scroll_history) > 3:
            self.scroll_history.pop(0)

        clicks_per_sec = sum(self.click_history) / len(self.click_history)
        keys_per_sec = sum(self.key_history) / len(self.key_history)
        movement_per_sec = sum(self.move_history) / len(self.move_history)
        scrolls_per_sec = sum(self.scroll_history) / len(self.scroll_history)

        # 2. Raw State Detection (interaction-aware)
        if idle_time > 5:
            new_state = "IDLE"
        elif (
            keys_per_sec > 2
            and movement_per_sec < LOW_MOVE
            and scrolls_per_sec < 2
        ):
            new_state = "FOCUS"
        elif (
            clicks_per_sec > 3
            or movement_per_sec > MOVE_THRESHOLD
            or scrolls_per_sec > SCROLL_THRESHOLD
        ):
            new_state = "ACTIVE"
        else:
            new_state = "ERROR"

        # 3. Candidate State Debouncing Buffer
        if new_state == self.candidate_state:
            self.candidate_count += 1
        else:
            self.candidate_state = new_state
            self.candidate_count = 1

        # 4. Transition Logic
        if self.candidate_count >= 2:
            state = self.candidate_state
        else:
            state = self.current_state

        # 5. Enforce Minimum ACTIVE Hold
        if self.current_state == "ACTIVE" and now < self.active_hold_until:
            state = "ACTIVE"
            self.candidate_state = "ACTIVE"
            self.candidate_count = 2

        # 6. Enforce Minimum FOCUS Hold
        if self.current_state == "FOCUS" and now < self.focus_hold_until:
            state = "FOCUS"
            self.candidate_state = "FOCUS"
            self.candidate_count = 2

        # Log transition only when state changes
        if state != prev:
            duration = round(now - self.state_start_time, 1)
            self.log.append((
                time.strftime("%H:%M:%S"),
                prev,
                state,
                duration
            ))
            self.current_state = state
            self.state_start_time = now

            # Keep log bounded (last 100 entries)
            if len(self.log) > 100:
                self.log = self.log[-100:]

        return state

    def get_state_duration(self):
        """How long the system has been in the current state."""
        return round(time.time() - self.state_start_time, 1)

    def get_log(self, n=50):
        """Return last n transition entries."""
        return self.log[-n:]
