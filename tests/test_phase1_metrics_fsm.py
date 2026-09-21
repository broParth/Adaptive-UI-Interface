"""
tests/test_phase1_metrics_fsm.py
Comprehensive deterministic test suite for Phase 1:
- True elapsed-time metric calculations across variable dt
- Semantic FSM state classification (BROWSING as normal use, ACTIVE as high-intensity)
- Ordinary click & scroll handling (stays in BROWSING)
- Rage-click ASSIST anomaly detection prioritized over ACTIVE
- Multi-state ASSIST exit re-classification
- Sustained typing vs transient burst handling for FOCUS
- Exact IDLE boundary at 5.0 seconds
- Numerical hysteresis boundaries for ACTIVE and FOCUS
- Rolling history integrity across all code paths
- 100% deterministic (zero time.sleep()) via mock timestamps
"""

import unittest
from analyzer import compute_metrics
from state_engine import StateEngine


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

    def test_idle_boundary_exact_5s(self):
        """IDLE requires idle_time >= 5.0s strictly."""
        last_event = self.clock()

        # At 4.99s: NOT IDLE
        now_499 = self.clock.advance(4.99)
        metrics_499 = compute_metrics(
            clicks=0, keys=0, move_distance=0.0, scroll_count=0.0,
            last_event_time=last_event, elapsed_sec=0.1, now_perf=now_499
        )
        state_499 = self.engine.determine_state(metrics_499, now=now_499)
        self.assertNotEqual(state_499, "IDLE", "idle_time = 4.99s must NOT be IDLE")

        # At 5.00s: STRICTLY IDLE
        now_500 = self.clock.advance(0.01)
        metrics_500 = compute_metrics(
            clicks=0, keys=0, move_distance=0.0, scroll_count=0.0,
            last_event_time=last_event, elapsed_sec=0.01, now_perf=now_500
        )
        state_500 = self.engine.determine_state(metrics_500, now=now_500)
        self.assertEqual(state_500, "IDLE", "idle_time >= 5.0s must strictly trigger IDLE")

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


if __name__ == "__main__":
    unittest.main()
