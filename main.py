"""
main.py — Adaptive UI Engine Orchestrator (System Mode)
Runs as a background system tool with:
  - System tray icon
  - Global overlay windows
  - OS-level effects (brightness, notifications)
  - Dashboard accessible via tray menu

Pipeline: EventCapture → Analyzer → StateEngine → Overlays + OS Effects

Production Fixes:
  - Proper logging via logging module
  - Graceful shutdown: listeners → tray → overlays → root
  - Exception-safe update cycle with logger.exception()
"""

import logging
import sys
import customtkinter as ctk
from event_capture import EventCapture
from analyzer import compute_metrics
from state_engine import StateEngine
from ui_controller import AdaptiveUI
from overlay_manager import OverlayController
from tray_icon import TrayIcon
from system_bridge import apply_system_effects, reset_brightness

# ─── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("AdaptiveUI.Main")


class AdaptiveEngine:
    """
    Main application controller.
    Runs the FSM loop and coordinates all subsystems.
    """

    def __init__(self):
        logger.info("Initializing Adaptive UI Engine...")

        # ─── Root Window (hidden by default) ───
        self.root = ctk.CTk()
        self.root.withdraw()  # Start hidden — background mode

        # ─── Output Layer: Dashboard (built but hidden) ───
        self.dashboard = AdaptiveUI(self.root)
        self.dashboard_visible = False
        self.dashboard.on_tray_toggle_callback = self._handle_tray_toggle

        # ─── Output Layer: Global Overlays ───
        self.overlays = OverlayController(self.root)

        # ─── Input Layer ───
        self.capture = EventCapture()

        # ─── Analysis Layer ───
        self.engine = StateEngine()

        # ─── System Tray ───
        self.tray = TrayIcon(
            on_open_dashboard=self._toggle_dashboard,
            on_toggle_pause=self._toggle_pause,
            on_exit=self._exit_app,
        )

        # ─── Track state for overlay decisions ───
        self._prev_state = None
        self._shutting_down = False
        self.is_paused = False

        logger.info("All subsystems initialized.")

    def start(self):
        """Start all subsystems and enter main loop."""
        # Start input listeners
        self.capture.start()
        logger.info("Input listeners started.")

        # Start system tray icon
        self.tray.start()
        logger.info("System tray icon started.")

        # Start the 500ms update cycle
        self._update_cycle()

        # Handle window close → hide to tray (don't exit)
        self.root.protocol("WM_DELETE_WINDOW", self._hide_dashboard)

        logger.info("Entering main loop.")
        # Run tkinter mainloop
        self.root.mainloop()

    # ═══════════════════════════════════════════════════════════════════════════
    # 100ms UPDATE CYCLE
    # ═══════════════════════════════════════════════════════════════════════════

    def _update_cycle(self):
        """Core processing loop — runs every 100ms."""
        if self._shutting_down:
            return

        try:
            # 1. Get raw event data (clears buffer even if paused)
            clicks, keys, move_dist, scrolls, last_time = self.capture.get_and_reset()
            instant_click = self.capture.consume_instant_click()
            instant_typing = self.capture.consume_instant_typing()
            instant_scroll = self.capture.consume_instant_scroll()

            if self.is_paused:
                state = "PAUSED"
                metrics = {
                    "clicks_per_sec": 0.0,
                    "keys_per_sec": 0.0,
                    "movement_per_sec": 0.0,
                    "scrolls_per_sec": 0.0,
                    "idle_time": 0.0,
                    "neural_latency": 0,
                    "processing_cycle": 0,
                    "adaptation_response": 0,
                    "system_load": 0.0,
                    "throughput": 0,
                    "classification_confidence": 0.0,
                }
                state_duration = 0.0
                log_entries = self.engine.get_log()
            else:
                # 2. Compute metrics
                metrics = compute_metrics(clicks, keys, move_dist, scrolls, last_time,
                                         instant_click, instant_typing, instant_scroll)

                # 3. Determine FSM state
                state = self.engine.determine_state(metrics)
                state_duration = self.engine.get_state_duration()
                log_entries = self.engine.get_log()

            # 4. Update tray icon state
            self.tray.update_state(state)

            # 5. Apply System-Level effects (brightness + notifications + mouse speed)
            if not self.is_paused:
                apply_system_effects(state, state_duration)

            # 6. Update UI based on mode
            if self.dashboard_visible:
                self.overlays.hide()
                self.dashboard.apply_state(state, metrics, state_duration, log_entries)
            else:
                if self.is_paused:
                    self.overlays.hide()
                else:
                    self.overlays.show_state(state, metrics)

        except Exception:
            logger.exception("Critical runtime failure in update cycle")
        finally:
            # 7. Schedule next cycle safely regardless of errors
            if not self._shutting_down:
                self.root.after(75, self._update_cycle)

    # ═══════════════════════════════════════════════════════════════════════════
    # DASHBOARD SHOW/HIDE & PAUSE
    # ═══════════════════════════════════════════════════════════════════════════

    def _toggle_pause(self):
        """Toggle the pause state of the system."""
        self.is_paused = not self.is_paused
        self.tray.set_paused(self.is_paused)
        if self.is_paused:
            logger.info("Monitoring paused by user.")
            reset_brightness()  # Restore brightness while paused
        else:
            logger.info("Monitoring resumed by user.")
            
    def _toggle_dashboard(self):
        """Toggle dashboard visibility (called from tray)."""
        self.root.after(0, self._do_toggle_dashboard)

    def _do_toggle_dashboard(self):
        if self.dashboard_visible:
            self._hide_dashboard()
        else:
            self._show_dashboard()

    def _show_dashboard(self):
        """Show the dashboard window and hide overlays."""
        self.overlays.hide()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.dashboard_visible = True

    def _hide_dashboard(self):
        """Hide dashboard back to tray, resume overlays."""
        self.root.withdraw()
        self.dashboard_visible = False

    def _handle_tray_toggle(self, is_enabled):
        """Handle toggle switch for the system tray icon."""
        if is_enabled:
            self.tray.start()
        else:
            self.tray.stop()

    # ═══════════════════════════════════════════════════════════════════════════
    # EXIT — Graceful Shutdown
    # ═══════════════════════════════════════════════════════════════════════════

    def _exit_app(self):
        """Clean shutdown — stop everything."""
        self.root.after(0, self._do_exit_app)

    def _do_exit_app(self):
        """Graceful shutdown sequence: listeners → tray → overlays → root."""
        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("Shutting down Adaptive UI Engine...")

        try:
            reset_brightness()
            from system_bridge import restore_mouse_speed
            restore_mouse_speed()
        except Exception:
            logger.exception("Failed to reset system effects")

        try:
            self.capture.stop()
            logger.info("Input listeners stopped.")
        except Exception:
            logger.exception("Failed to stop input listeners")

        try:
            self.tray.stop()
            logger.info("Tray icon stopped.")
        except Exception:
            logger.exception("Failed to stop tray icon")

        try:
            self.overlays.destroy()
            logger.info("Overlays destroyed.")
        except Exception:
            logger.exception("Failed to destroy overlays")

        try:
            self.root.quit()
            self.root.destroy()
            logger.info("Root window destroyed. Goodbye.")
        except Exception:
            logger.exception("Failed to destroy root window")


def main():
    engine = AdaptiveEngine()
    engine.start()


if __name__ == "__main__":
    main()
