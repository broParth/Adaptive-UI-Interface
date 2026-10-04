"""
tests/test_phase1_metrics_fsm.py
Comprehensive deterministic test suite for Phase 1 + Phase 1.5:
- True elapsed-time metric calculations across variable dt
- Semantic FSM state classification (BROWSING as normal use, ACTIVE as high-intensity)
- Ordinary click & scroll handling (stays in BROWSING)
- Rage-click ASSIST anomaly detection prioritized over ACTIVE
- Multi-state ASSIST exit re-classification
- Sustained typing vs transient burst handling for FOCUS
- Exact IDLE boundary at 10.0 seconds (Phase 1.5: increased from 5.0s)
- Numerical hysteresis boundaries for ACTIVE and FOCUS
- Rolling history integrity across all code paths
- 100% deterministic (zero time.sleep()) via mock timestamps
- Phase 1.5: notification suppression, brightness deduplication, original brightness restoration
"""

import unittest
from unittest.mock import patch, MagicMock
from analyzer import compute_metrics
from state_engine import StateEngine, IDLE_THRESHOLD


class MockClock:
    """Deterministic monotonic clock for FSM testing."""
    def __init__(self, start=1000.0):
        self.current = start

    def advance(self, seconds):
        self.current += seconds
        return self.current

    def __call__(self):
        return self.current


class TestPhase1MetricsAndFSM(unittest.TestCase):

    def setUp(self):
        self.clock = MockClock(start=1000.0)
        self.engine = StateEngine(window_duration=1.0)
        # Initialize engine to BROWSING with a warm base state
        self.engine.current_state = "BROWSING"
        self.engine.state_start_time = self.clock()

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. METRICS TIMING & RATE CALCULATIONS
    # ═══════════════════════════════════════════════════════════════════════════

    def test_variable_dt_rate_calculations(self):
        """Rates must correctly scale with true elapsed time dt."""
        intervals = [0.05, 0.075, 0.1, 0.25, 0.5, 1.0]
        event_time = self.clock() - 0.2  # 0.2s idle

        for dt in intervals:
            # Suppose in dt time, user clicked 2 times and moved 50px
            metrics = compute_metrics(
                clicks=2,
                keys=4,
                move_distance=50.0,
                scroll_count=1.0,
                last_event_time=event_time,
                elapsed_sec=dt,
                now_perf=self.clock(),
            )
            expected_clicks_rate = 2 / dt
            expected_keys_rate = 4 / dt
            expected_move_rate = 50.0 / dt
            expected_scroll_rate = 1.0 / dt

            self.assertAlmostEqual(metrics["clicks_per_sec"], expected_clicks_rate, places=2)
            self.assertAlmostEqual(metrics["keys_per_sec"], expected_keys_rate, places=2)
            self.assertAlmostEqual(metrics["movement_per_sec"], expected_move_rate, places=2)
            self.assertAlmostEqual(metrics["scrolls_per_sec"], expected_scroll_rate, places=2)
            self.assertAlmostEqual(metrics["idle_time"], 0.2, places=2)

    def test_rate_calculation_guards_zero_or_negative_dt(self):
        """Non-positive or tiny dt should be safely guarded without ZeroDivisionError."""
        event_time = self.clock()
        metrics = compute_metrics(
            clicks=1,
            keys=1,
            move_distance=10.0,
            scroll_count=0.0,
            last_event_time=event_time,
            elapsed_sec=0.0,
            now_perf=self.clock(),
        )
        self.assertGreater(metrics["clicks_per_sec"], 0)
        self.assertGreaterEqual(metrics["elapsed_sec"], 0.001)

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. SEMANTIC CLASSIFICATION: BROWSING AS NORMAL USE
    # ═══════════════════════════════════════════════════════════════════════════

    def test_ordinary_single_click_stays_browsing(self):
        """An ordinary single click in a cycle must resolve to BROWSING, NOT ACTIVE."""
        now = self.clock.advance(0.1)
        # 1 click in 0.1s cycle with calm movement (10px)
        metrics = compute_metrics(
            clicks=1, keys=0, move_distance=10.0, scroll_count=0.0,
            last_event_time=now, elapsed_sec=0.1, now_perf=now,
            instant_click=True
        )
        state = self.engine.determine_state(metrics, now=now)
        self.assertEqual(state, "BROWSING", "Single occasional click must remain in BROWSING")

    def test_ordinary_scroll_stays_browsing(self):
        """Normal reading/browsing scrolling must resolve to BROWSING, NOT ACTIVE."""
        now = self.clock.advance(0.1)
        # 1 scroll notch in 0.1s cycle
        metrics = compute_metrics(
            clicks=0, keys=0, move_distance=5.0, scroll_count=1.0,
            last_event_time=now, elapsed_sec=0.1, now_perf=now,
            instant_scroll=True
        )
        state = self.engine.determine_state(metrics, now=now)
        self.assertEqual(state, "BROWSING", "Normal scrolling must remain in BROWSING")

    def test_normal_mouse_movement_stays_browsing(self):
        """Gentle cursor movement (e.g. 100 px/s) must resolve to BROWSING."""
        now = self.clock.advance(0.1)
        # 10 px in 0.1s = 100 px/s
        metrics = compute_metrics(
            clicks=0, keys=0, move_distance=10.0, scroll_count=0.0,
            last_event_time=now, elapsed_sec=0.1, now_perf=now
        )
        state = self.engine.determine_state(metrics, now=now)
        self.assertEqual(state, "BROWSING", "Gentle mouse tracking must remain in BROWSING")

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. HIGH-INTENSITY ACTIVE BEHAVIOR
    # ═══════════════════════════════════════════════════════════════════════════

    def test_rapid_movement_triggers_active(self):
        """Fast pointer sweeps (>= 250 px/s over window) must trigger ACTIVE."""
        # Warm the 1.0s window with 300 px/s movement over 1.0s (10 cycles of 0.1s with 30px each)
        for _ in range(10):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=0, keys=0, move_distance=30.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now
            )
            state = self.engine.determine_state(metrics, now=now)

        self.assertEqual(state, "ACTIVE", "300 px/s sustained movement must trigger ACTIVE")

    def test_rapid_click_burst_triggers_active(self):
        """Rapid click burst (>= 2.5 clicks/s with movement) must trigger ACTIVE."""
        # 3 clicks over 0.3 seconds with 20px movement
        for _ in range(3):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=1, keys=0, move_distance=20.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now,
                instant_click=True
            )
            state = self.engine.determine_state(metrics, now=now)

        self.assertEqual(state, "ACTIVE", "3 rapid clicks with normal movement must trigger ACTIVE")

    # ═══════════════════════════════════════════════════════════════════════════
    # 4. ASSIST ANOMALY DETECTION & PRIORITY OVER ACTIVE
    # ═══════════════════════════════════════════════════════════════════════════

    def test_rage_clicking_triggers_assist_over_active(self):
        """Rapid repetitive clicking in place (>= 4 clicks/s, < 30px move, no keys) triggers ASSIST."""
        # 4 clicks over 0.4 seconds in place (0 px movement)
        for _ in range(4):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=1, keys=0, move_distance=0.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now,
                instant_click=True
            )
            state = self.engine.determine_state(metrics, now=now)

        self.assertEqual(state, "ASSIST", "Rage clicking in place must trigger ASSIST even with instant_click")

    def test_assist_exit_reclassifies_properly(self):
        """When assist_hold_until expires, system re-classifies to appropriate state, not blindly BROWSING."""
        # Step 1: Trigger ASSIST
        for _ in range(4):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=1, keys=0, move_distance=0.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now,
                instant_click=True
            )
            self.engine.determine_state(metrics, now=now)

        self.assertEqual(self.engine.current_state, "ASSIST")

        # Step 2: Advance beyond assist_hold_until (1.2s) while user starts rapid active mouse sweeps (350 px/s)
        # Clear old clicks from the 1.0s window by advancing 1.3s with high movement
        for _ in range(13):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=0, keys=0, move_distance=35.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now
            )
            state = self.engine.determine_state(metrics, now=now)

        self.assertEqual(state, "ACTIVE", "After ASSIST expires, high movement must reclassify to ACTIVE")

    # ═══════════════════════════════════════════════════════════════════════════
    # 5. SUSTAINED TYPING & FOCUS BEHAVIOR
    # ═══════════════════════════════════════════════════════════════════════════

    def test_sustained_typing_triggers_focus(self):
        """Sustained typing flow (>= 2.0 keys/s with calm mouse) must trigger FOCUS."""
        for _ in range(10):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=0, keys=1, move_distance=2.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now,
                instant_typing=True
            )
            state = self.engine.determine_state(metrics, now=now)

        self.assertEqual(state, "FOCUS", "Sustained typing at 10 keys/s with 20 px/s move must enter FOCUS")

    def test_short_typing_burst_does_not_permanently_lock_focus(self):
        """A brief 2-key tap must return to BROWSING once hold expires."""
        # 2 keys in 0.1s
        now = self.clock.advance(0.1)
        metrics = compute_metrics(
            clicks=0, keys=2, move_distance=0.0, scroll_count=0.0,
            last_event_time=now, elapsed_sec=0.1, now_perf=now,
            instant_typing=True
        )
        self.engine.determine_state(metrics, now=now)

        # Advance past 1.0s window and focus hold (0.6s) with calm browsing
        for _ in range(12):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=0, keys=0, move_distance=10.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now
            )
            state = self.engine.determine_state(metrics, now=now)

        self.assertEqual(state, "BROWSING", "Short burst must not permanently lock FOCUS")

    # ═══════════════════════════════════════════════════════════════════════════
    # 6. IDLE BOUNDARY EXACTNESS (5.0s)
    # ═══════════════════════════════════════════════════════════════════════════

    def test_idle_boundary_exact_10s(self):
        """IDLE requires idle_time >= 10.0s strictly (Phase 1.5 threshold)."""
        self.assertEqual(IDLE_THRESHOLD, 10.0, "IDLE_THRESHOLD must be 10.0s in Phase 1.5")
        last_event = self.clock()

        # At 9.99s: NOT IDLE
        now_999 = self.clock.advance(9.99)
        metrics_999 = compute_metrics(
            clicks=0, keys=0, move_distance=0.0, scroll_count=0.0,
            last_event_time=last_event, elapsed_sec=0.1, now_perf=now_999
        )
        state_999 = self.engine.determine_state(metrics_999, now=now_999)
        self.assertNotEqual(state_999, "IDLE", "idle_time = 9.99s must NOT be IDLE")

        # At 10.00s: STRICTLY IDLE
        now_1000 = self.clock.advance(0.01)
        metrics_1000 = compute_metrics(
            clicks=0, keys=0, move_distance=0.0, scroll_count=0.0,
            last_event_time=last_event, elapsed_sec=0.01, now_perf=now_1000
        )
        state_1000 = self.engine.determine_state(metrics_1000, now=now_1000)
        self.assertEqual(state_1000, "IDLE", "idle_time >= 10.0s must strictly trigger IDLE")

        # Breaking out of IDLE upon new input:
        now_input = self.clock.advance(0.1)
        metrics_input = compute_metrics(
            clicks=0, keys=0, move_distance=15.0, scroll_count=0.0,
            last_event_time=now_input, elapsed_sec=0.1, now_perf=now_input
        )
        state_input = self.engine.determine_state(metrics_input, now=now_input)
        self.assertEqual(state_input, "BROWSING", "New input must immediately break out of IDLE to BROWSING")

    # ═══════════════════════════════════════════════════════════════════════════
    # 7. NUMERICAL HYSTERESIS
    # ═══════════════════════════════════════════════════════════════════════════

    def test_hysteresis_active_boundary(self):
        """ACTIVE entry >= 250 px/s; exit < 140 px/s. Intermediate values stay in current state."""
        # Enter ACTIVE at 280 px/s over 1.0s
        for _ in range(10):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=0, keys=0, move_distance=28.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now
            )
            state = self.engine.determine_state(metrics, now=now)
        self.assertEqual(state, "ACTIVE")

        # Slow down to 180 px/s (18px/0.1s) for 1.0s (past active hold time 0.5s)
        # 180 px/s is below entry (250) but above exit (140) -> MUST STAY ACTIVE
        for _ in range(10):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=0, keys=0, move_distance=18.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now
            )
            state = self.engine.determine_state(metrics, now=now)
        self.assertEqual(state, "ACTIVE", "Movement at 180 px/s must remain ACTIVE due to hysteresis")

        # Further slow down to 80 px/s (8px/0.1s) for 1.0s
        # 80 px/s is below exit (140) -> MUST DROP TO BROWSING
        for _ in range(10):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=0, keys=0, move_distance=8.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now
            )
            state = self.engine.determine_state(metrics, now=now)
        self.assertEqual(state, "BROWSING", "Movement at 80 px/s must drop to BROWSING")

    def test_hysteresis_focus_boundary(self):
        """FOCUS entry >= 2.0 keys/s; exit < 0.8 keys/s or move > 80. Brief pause keeps FOCUS."""
        # Enter FOCUS: 3.0 keys/s for 1.0s
        for _ in range(10):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=0, keys=1, move_distance=1.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now
            )
            state = self.engine.determine_state(metrics, now=now)
        self.assertEqual(state, "FOCUS")

        # Brief typing pause of 0.4s (within focus_hold_until 0.6s)
        for _ in range(4):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=0, keys=0, move_distance=1.0, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now
            )
            state = self.engine.determine_state(metrics, now=now)
        self.assertEqual(state, "FOCUS", "Pause under 0.6s must keep FOCUS via hold-time")

    # ═══════════════════════════════════════════════════════════════════════════
    # 8. ROLLING HISTORY INTEGRITY & TRANSITION LOGGING
    # ═══════════════════════════════════════════════════════════════════════════

    def test_rolling_history_integrity_on_all_paths(self):
        """Rolling history must be recorded on every single cycle without stale state."""
        self.assertEqual(len(self.engine._history), 0)

        # Run 5 cycles of varying actions
        for i in range(5):
            now = self.clock.advance(0.1)
            metrics = compute_metrics(
                clicks=i % 2, keys=i, move_distance=10.0 * i, scroll_count=0.0,
                last_event_time=now, elapsed_sec=0.1, now_perf=now
            )
            self.engine.determine_state(metrics, now=now)

        self.assertEqual(len(self.engine._history), 5, "History deque must have recorded all 5 samples")

    def test_transition_log_structure(self):
        """Transition log entries must have (timestamp_str, prev_state, new_state, duration)."""
        now = self.clock.advance(0.1)
        metrics_active = compute_metrics(
            clicks=0, keys=0, move_distance=300.0, scroll_count=0.0,
            last_event_time=now, elapsed_sec=0.1, now_perf=now
        )
        self.engine.determine_state(metrics_active, now=now)

        log = self.engine.get_log()
        self.assertGreaterEqual(len(log), 1)
        entry = log[-1]
        self.assertEqual(len(entry), 4)
        self.assertIsInstance(entry[0], str)  # timestamp
        self.assertEqual(entry[1], "BROWSING") # prev
        self.assertEqual(entry[2], "ACTIVE")   # new
        self.assertIsInstance(entry[3], float) # duration


# =============================================================================
# PHASE 1.5 TESTS
# =============================================================================

class TestPhase15Polish(unittest.TestCase):
    """Focused tests for Phase 1.5 behavioral changes."""

    # ─────────────────────────────────────────────────────────────────────────
    # 1. NOTIFICATION SUPPRESSION
    # ─────────────────────────────────────────────────────────────────────────

    def test_routine_fsm_transitions_do_not_notify(self):
        """
        Routine FSM transitions (IDLE, FOCUS, ACTIVE, ASSIST) must NOT invoke
        the notify() function. The in-app overlay is the sole feedback channel.
        """
        import system_bridge as sb

        states_under_test = ["IDLE", "FOCUS", "ACTIVE", "ASSIST",
                             "BROWSING", "ERROR", "ANOMALY"]

        for target_state in states_under_test:
            # Reset bridge state so each call triggers the state-change branch.
            sb._prev_state = None
            with patch.object(sb, "notify") as mock_notify, \
                 patch.object(sb, "set_brightness"), \
                 patch.object(sb, "apply_mouse_slowdown"), \
                 patch.object(sb, "restore_mouse_speed"):
                sb.apply_system_effects(target_state, state_duration=0.0)
                if mock_notify.called:
                    self.fail(
                        f"notify() must NOT be called for state '{target_state}' in Phase 1.5, "
                        f"but was called with: {mock_notify.call_args_list}"
                    )

    # ─────────────────────────────────────────────────────────────────────────
    # 2. IDLE THRESHOLD = 10 SECONDS
    # ─────────────────────────────────────────────────────────────────────────

    def test_idle_threshold_is_10_seconds(self):
        """IDLE_THRESHOLD must be exactly 10.0 seconds in Phase 1.5."""
        self.assertEqual(
            IDLE_THRESHOLD, 10.0,
            "Phase 1.5 requires IDLE_THRESHOLD == 10.0 seconds"
        )

    def test_user_reading_pause_does_not_trigger_idle(self):
        """A 9-second pause (e.g. reading) must NOT trigger IDLE with the 10s threshold."""
        clock = MockClock(start=2000.0)
        engine = StateEngine(window_duration=1.0)
        engine.current_state = "BROWSING"
        engine.state_start_time = clock()
        last_event = clock()

        # Simulate 9 seconds of no input (user is reading)
        now = clock.advance(9.0)
        metrics = compute_metrics(
            clicks=0, keys=0, move_distance=0.0, scroll_count=0.0,
            last_event_time=last_event, elapsed_sec=9.0, now_perf=now
        )
        state = engine.determine_state(metrics, now=now)
        self.assertNotEqual(state, "IDLE",
            "A 9-second reading pause must NOT trigger IDLE at the 10s threshold")

    # ─────────────────────────────────────────────────────────────────────────
    # 3. BRIGHTNESS DEDUPLICATION (no repeated hardware writes)
    # ─────────────────────────────────────────────────────────────────────────

    def test_brightness_not_written_when_value_unchanged(self):
        """
        _set_brightness_safe must skip the sbc.set_brightness() call when
        the requested value matches _current_applied_brightness.
        """
        import system_bridge as sb
        sb._current_applied_brightness = 80  # Simulate brightness already at 80%

        with patch("screen_brightness_control.set_brightness") as mock_sbc:
            sb._set_brightness_safe(80)  # Same value — should be a no-op
            if mock_sbc.called:
                self.fail(
                    "set_brightness() must not call hardware when value is already 80%, "
                    f"but was called with: {mock_sbc.call_args_list}"
                )

    def test_brightness_written_when_value_changes(self):
        """
        _set_brightness_safe must call sbc.set_brightness() when the requested
        value differs from the currently applied value.
        """
        import system_bridge as sb
        sb._current_applied_brightness = 30  # Simulate current brightness at 30%

        with patch("screen_brightness_control.set_brightness") as mock_sbc:
            sb._set_brightness_safe(80)  # Different value — must write
            mock_sbc.assert_called_once_with(80)

    # ─────────────────────────────────────────────────────────────────────────
    # 4. ORIGINAL BRIGHTNESS RESTORATION
    # ─────────────────────────────────────────────────────────────────────────

    def test_restore_original_brightness_uses_captured_value(self):
        """
        restore_original_brightness() must restore _original_brightness, NOT a
        hardcoded 100% value.
        """
        import system_bridge as sb
        original = sb._original_brightness  # Save real value

        try:
            sb._original_brightness = 65   # Simulate user had 65% brightness
            sb._current_applied_brightness = 30  # Simulate IDLE dimmed it to 30%

            with patch("screen_brightness_control.set_brightness") as mock_sbc:
                sb.restore_original_brightness()
                mock_sbc.assert_called_once_with(65)
        finally:
            sb._original_brightness = original  # Restore real value after test

    def test_restore_original_brightness_no_fallback_when_capture_failed(self):
        """
        If _original_brightness was not captured at startup, restore_original_brightness()
        must NOT write any brightness value to hardware.
        No arbitrary fallback such as 50% or 100% may be used.
        """
        import system_bridge as sb
        original = sb._original_brightness

        try:
            sb._original_brightness = None
            sb._current_applied_brightness = 30

            with patch("screen_brightness_control.set_brightness") as mock_sbc:
                sb.restore_original_brightness()
                # Must NOT call hardware at all — no fallback value invented.
                if mock_sbc.called:
                    self.fail(
                        "restore_original_brightness() must leave hardware unchanged "
                        "when original was not captured, but called sbc.set_brightness"
                        f" with: {mock_sbc.call_args_list}"
                    )
        finally:
            sb._original_brightness = original

    # ─────────────────────────────────────────────────────────────────────────
    # 5. BROWSING BRIGHTNESS RESTORATION
    # ─────────────────────────────────────────────────────────────────────────

    def test_browsing_restores_original_brightness_when_captured(self):
        """
        BROWSING/NORMAL must call set_brightness(original) when original was captured.
        Ensures ACTIVE(100%) -> BROWSING resets the display to pre-application brightness.
        """
        import system_bridge as sb
        original = sb._original_brightness
        original_prev = sb._prev_state

        try:
            sb._original_brightness = 72   # Simulate user's saved brightness
            sb._prev_state = None           # Force state-change branch

            with patch.object(sb, "set_brightness") as mock_set, \
                 patch.object(sb, "apply_mouse_slowdown"), \
                 patch.object(sb, "restore_mouse_speed"):
                sb.apply_system_effects("BROWSING", state_duration=0.0)
                mock_set.assert_called_once_with(72)
        finally:
            sb._original_brightness = original
            sb._prev_state = original_prev

    def test_browsing_no_brightness_write_when_original_not_captured(self):
        """
        BROWSING must NOT invent a brightness if original was never captured.
        """
        import system_bridge as sb
        original = sb._original_brightness
        original_prev = sb._prev_state

        try:
            sb._original_brightness = None
            sb._prev_state = None

            with patch.object(sb, "set_brightness") as mock_set, \
                 patch.object(sb, "apply_mouse_slowdown"), \
                 patch.object(sb, "restore_mouse_speed"):
                sb.apply_system_effects("BROWSING", state_duration=0.0)
                if mock_set.called:
                    self.fail(
                        "BROWSING must not call set_brightness() when original was "
                        f"not captured, but called with: {mock_set.call_args_list}"
                    )
        finally:
            sb._original_brightness = original
            sb._prev_state = original_prev

    # ─────────────────────────────────────────────────────────────────────────
    # 6. PAUSE / RESUME BRIGHTNESS CONSISTENCY
    # ─────────────────────────────────────────────────────────────────────────

    def test_invalidate_brightness_state_forces_reapply(self):
        """
        invalidate_brightness_state() must clear _prev_state so that the next
        apply_system_effects() call re-applies brightness even if the FSM state
        name has not changed.

        Scenario: ACTIVE at 100%, pause (original restored), resume while still ACTIVE.
        Without invalidation, apply_system_effects would see ACTIVE == _prev_state
        and skip the write, leaving the display at original brightness.
        """
        import system_bridge as sb
        original_prev = sb._prev_state

        try:
            # Simulate: ACTIVE was already applied (prev_state = "ACTIVE")
            with sb._state_lock:
                sb._prev_state = "ACTIVE"

            # Simulate resume — invalidate so next cycle re-applies
            sb.invalidate_brightness_state()

            # _prev_state must now be None
            self.assertIsNone(sb._prev_state,
                "invalidate_brightness_state() must set _prev_state to None")

            # The next apply_system_effects("ACTIVE") must call set_brightness(100)
            with patch.object(sb, "set_brightness") as mock_set, \
                 patch.object(sb, "apply_mouse_slowdown"), \
                 patch.object(sb, "restore_mouse_speed"):
                sb.apply_system_effects("ACTIVE", state_duration=0.0)
                mock_set.assert_called_once_with(100)
        finally:
            with sb._state_lock:
                sb._prev_state = original_prev

    # ─────────────────────────────────────────────────────────────────────────
    # 7. BRIGHTNESS CRASH RECOVERY (SIDECAR)
    # ─────────────────────────────────────────────────────────────────────────

    def test_first_brightness_modification_creates_recovery_state(self):
        import system_bridge as sb
        import tempfile
        import os, json

        tmp = tempfile.mktemp()
        original_file = sb.BRIGHTNESS_STATE_FILE
        original_val = sb._original_brightness
        original_recorded = sb._brightness_recorded_in_sidecar

        try:
            sb.BRIGHTNESS_STATE_FILE = tmp
            sb._original_brightness = 55
            sb._brightness_recorded_in_sidecar = False
            sb._current_applied_brightness = None

            with patch("screen_brightness_control.set_brightness"):
                sb._set_brightness_safe(80)

            self.assertTrue(os.path.exists(tmp), "Sidecar must be created on first modification")
            with open(tmp, "r") as f:
                data = json.load(f)
            self.assertEqual(data.get("original_brightness"), 55)
            self.assertTrue(sb._brightness_recorded_in_sidecar)
        finally:
            sb.BRIGHTNESS_STATE_FILE = original_file
            sb._original_brightness = original_val
            sb._brightness_recorded_in_sidecar = original_recorded
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_repeated_state_changes_do_not_overwrite_recovery_value(self):
        import system_bridge as sb
        import tempfile
        import os, json

        tmp = tempfile.mktemp()
        original_file = sb.BRIGHTNESS_STATE_FILE
        original_val = sb._original_brightness
        original_recorded = sb._brightness_recorded_in_sidecar

        try:
            sb.BRIGHTNESS_STATE_FILE = tmp
            sb._original_brightness = 60
            sb._brightness_recorded_in_sidecar = True # simulate already recorded

            # create file with some OTHER value
            with open(tmp, "w") as f:
                json.dump({"original_brightness": 99}, f)

            with patch("screen_brightness_control.set_brightness"):
                sb._set_brightness_safe(100)

            # verify it was NOT overwritten
            with open(tmp, "r") as f:
                data = json.load(f)
            self.assertEqual(data.get("original_brightness"), 99)
        finally:
            sb.BRIGHTNESS_STATE_FILE = original_file
            sb._original_brightness = original_val
            sb._brightness_recorded_in_sidecar = original_recorded
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_clean_restoration_removes_recovery_state(self):
        import system_bridge as sb
        import tempfile
        import os

        tmp = tempfile.mktemp()
        original_file = sb.BRIGHTNESS_STATE_FILE
        original_val = sb._original_brightness
        original_recorded = sb._brightness_recorded_in_sidecar
        original_restored = sb._restored_once

        try:
            sb.BRIGHTNESS_STATE_FILE = tmp
            sb._original_brightness = 75
            sb._current_applied_brightness = 100
            sb._brightness_recorded_in_sidecar = True
            sb._restored_once = False

            # create fake sidecar
            with open(tmp, "w") as f:
                f.write('{"original_brightness": 75}')

            with patch("screen_brightness_control.set_brightness"):
                sb.restore_original_brightness()

            self.assertFalse(os.path.exists(tmp), "Clean restoration must remove sidecar")
            self.assertFalse(sb._brightness_recorded_in_sidecar, "Flag must be reset")
        finally:
            sb.BRIGHTNESS_STATE_FILE = original_file
            sb._original_brightness = original_val
            sb._brightness_recorded_in_sidecar = original_recorded
            sb._restored_once = original_restored
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_startup_detects_stale_recovery_state(self):
        import system_bridge as sb
        import tempfile
        import os

        tmp = tempfile.mktemp()
        original_file = sb.BRIGHTNESS_STATE_FILE
        original_val = sb._original_brightness
        original_fail = sb._startup_recovery_failed

        try:
            sb.BRIGHTNESS_STATE_FILE = tmp
            sb._startup_recovery_failed = False

            with open(tmp, "w") as f:
                f.write('{"original_brightness": 42}')

            with patch("screen_brightness_control.set_brightness") as mock_set, \
                 patch("screen_brightness_control.get_brightness", return_value=[42]):
                sb._capture_original_brightness()
                mock_set.assert_called_once_with(42)

            self.assertFalse(os.path.exists(tmp), "Startup recovery must remove sidecar after success")
            self.assertEqual(sb._original_brightness, 42)
        finally:
            sb.BRIGHTNESS_STATE_FILE = original_file
            sb._original_brightness = original_val
            sb._startup_recovery_failed = original_fail
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_malformed_recovery_data_handled_safely(self):
        import system_bridge as sb
        import tempfile
        import os

        tmp = tempfile.mktemp()
        original_file = sb.BRIGHTNESS_STATE_FILE
        original_val = sb._original_brightness
        original_fail = sb._startup_recovery_failed

        try:
            sb.BRIGHTNESS_STATE_FILE = tmp
            sb._startup_recovery_failed = False

            with open(tmp, "w") as f:
                f.write('invalid json!!!')

            with patch("screen_brightness_control.get_brightness"):
                sb._capture_original_brightness()

            self.assertTrue(sb._startup_recovery_failed, "Startup recovery must fail on bad json")
            self.assertIsNone(sb._original_brightness, "Original brightness must be None if recovery fails")
            self.assertFalse(sb._brightness_available, "Brightness must be disabled")
        finally:
            sb.BRIGHTNESS_STATE_FILE = original_file
            sb._original_brightness = original_val
            sb._startup_recovery_failed = original_fail
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_pause_resume_then_final_restore(self):
        """
        Tests the lifecycle bug:
        ACTIVE -> Pause (restore) -> Resume -> ACTIVE -> final restore.
        _restored_once must be reset to False upon new writes so final restore succeeds.
        """
        import system_bridge as sb
        import tempfile
        import os

        tmp = tempfile.mktemp()
        original_file = sb.BRIGHTNESS_STATE_FILE
        original_val = sb._original_brightness
        original_recorded = sb._brightness_recorded_in_sidecar
        original_restored = sb._restored_once
        original_applied = sb._current_applied_brightness

        try:
            sb.BRIGHTNESS_STATE_FILE = tmp
            sb._original_brightness = 55
            sb._brightness_recorded_in_sidecar = False
            sb._restored_once = False
            sb._current_applied_brightness = None

            with patch("screen_brightness_control.set_brightness") as mock_set:
                # 1. Enter ACTIVE (100%)
                sb._set_brightness_safe(100)
                mock_set.assert_called_with(100)
                self.assertFalse(sb._restored_once)

                # 2. Pause (restores to original 55%)
                sb.restore_original_brightness()
                mock_set.assert_called_with(55)
                self.assertTrue(sb._restored_once)

                # 3. Resume -> ACTIVE (100%)
                # Resuming invalidates state, so apply_system_effects will call set_brightness(100) again
                sb._set_brightness_safe(100)
                mock_set.assert_called_with(100)
                self.assertFalse(sb._restored_once, "Re-acquiring control must reset _restored_once")

                # 4. Final Clean Shutdown
                sb.restore_original_brightness()
                mock_set.assert_called_with(55) # Must be called again!
                self.assertTrue(sb._restored_once)

        finally:
            sb.BRIGHTNESS_STATE_FILE = original_file
            sb._original_brightness = original_val
            sb._brightness_recorded_in_sidecar = original_recorded
            sb._restored_once = original_restored
            sb._current_applied_brightness = original_applied
            if os.path.exists(tmp):
                os.remove(tmp)

if __name__ == "__main__":
    unittest.main()
