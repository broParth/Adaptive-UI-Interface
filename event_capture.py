"""
event_capture.py — Neural Input Layer
Hybrid event capture for reliable Windows input detection.

Architecture:
  - pynput: clicks + keyboard (reliable on all Windows)
  - Win32 GetCursorPos polling: cursor movement (100% reliable fallback)
  - pynput on_scroll + Win32 hook: scroll detection (best-effort)

Why polling instead of hooks for movement?
  pynput's on_move works in SOME environments but silently fails in others.
  Win32 low-level mouse hooks (WH_MOUSE_LL) fail with error 126 in Python.
  GetCursorPos polling at ~60Hz is lightweight and ALWAYS works.

Why scroll detection is best-effort?
  Many Windows touchpads use Precision Touchpad drivers that handle scrolling
  at a higher OS level, completely bypassing low-level mouse hooks.
  Cursor movement detection alone is sufficient to prevent false IDLE,
  since users naturally move the cursor while browsing/scrolling.

Production Fixes:
  - Euclidean distance for hardware-independent movement
  - 3px dead zone to ignore jitter / sensor drift
  - ~60Hz polling rate for low CPU usage
  - All interaction types reset last_event_time
"""

from pynput import mouse, keyboard
import ctypes
import ctypes.wintypes
import time
import math
import logging
from threading import Lock, Thread

logger = logging.getLogger("AdaptiveUI.Capture")

# Polling interval for cursor position (~60Hz)
_POLL_INTERVAL = 0.016  # 16ms

# Dead zone threshold — ignore tiny jitter below this pixel distance
_MOVE_DEAD_ZONE = 3

# Win32 API
_user32 = ctypes.windll.user32


class EventCapture:
    """
    Captures mouse and keyboard events with thread-safe counters.
    Uses GetCursorPos polling for reliable cursor movement detection
    and pynput for clicks/keyboard/scroll.
    """

    def __init__(self):
        self.click_count = 0
        self.key_count = 0
        self.move_distance = 0.0
        self.scroll_count = 0.0
        self.last_event_time = time.perf_counter()
        self.last_scroll_time = 0.0
        self.instant_click_detected = False
        self.instant_typing_detected = False
        self.instant_scroll_detected = False
        self.recent_keypress_times = []
        self.lock = Lock()

        # Cursor polling state
        self._last_x = None
        self._last_y = None
        self._poll_running = False
        self._poll_thread = None

        # pynput listeners: clicks + keyboard + scroll (scroll is best-effort)
        self.mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self.keyboard_listener = keyboard.Listener(on_press=self._on_key)

        # Mark as daemon so they die with the main thread
        self.mouse_listener.daemon = True
        self.keyboard_listener.daemon = True

    # ═══════════════════════════════════════════════════════════════════════════
    # CURSOR MOVEMENT — Win32 GetCursorPos Polling (100% reliable)
    # ═══════════════════════════════════════════════════════════════════════════

    def _poll_cursor(self):
        """
        Poll cursor position at ~60Hz using Win32 GetCursorPos.
        This is the most reliable way to detect cursor movement on Windows.
        """
        pt = ctypes.wintypes.POINT()

        while self._poll_running:
            try:
                _user32.GetCursorPos(ctypes.byref(pt))
                x, y = pt.x, pt.y

                with self.lock:
                    if self._last_x is not None and self._last_y is not None:
                        dx = x - self._last_x
                        dy = y - self._last_y
                        distance = math.sqrt(dx * dx + dy * dy)

                        # Dead zone: ignore tiny jitter / sensor drift
                        if distance >= _MOVE_DEAD_ZONE:
                            self.move_distance += distance
                            self.last_event_time = time.perf_counter()

                    # Always update position for next delta
                    self._last_x = x
                    self._last_y = y

            except Exception:
                pass  # Never crash the polling thread

            time.sleep(_POLL_INTERVAL)

    # ═══════════════════════════════════════════════════════════════════════════
    # PYNPUT CALLBACKS
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_scroll(self, x, y, dx, dy):
        """
        Mouse scroll callback (best-effort via pynput).
        May not fire on all systems (Precision Touchpad drivers bypass hooks).
        Triggers instant_scroll_detected for FSM fast-path activation.
        """
        scroll_amount = abs(dy) if abs(dy) >= 0.1 else 0
        if scroll_amount > 0:
            with self.lock:
                self.scroll_count += scroll_amount
                self.last_event_time = time.perf_counter()
                self.last_scroll_time = time.perf_counter()
                self.instant_scroll_detected = True
            logger.debug("SCROLL DETECTED: dy=%s amount=%s", dy, scroll_amount)

    def _on_click(self, x, y, button, pressed):
        """Mouse click callback — only count presses, not releases."""
        if pressed:
            with self.lock:
                self.click_count += 1
                self.instant_click_detected = True
                self.last_event_time = time.perf_counter()

    def _on_key(self, key):
        """Keyboard press callback."""
        with self.lock:
            self.key_count += 1
            self.last_event_time = time.perf_counter()

            # Ignore modifier keys and special keys, allow letters, numbers, space, backspace, enter
            if hasattr(key, 'char') and key.char is not None:
                is_valid = True
            elif key in (keyboard.Key.space, keyboard.Key.backspace, keyboard.Key.enter):
                is_valid = True
            else:
                is_valid = False

            if is_valid:
                now = time.perf_counter()
                self.recent_keypress_times.append(now)
                # Keep only keypresses from the last 0.3 seconds (~300ms)
                self.recent_keypress_times = [t for t in self.recent_keypress_times if now - t <= 0.3]

                # If we have 2 or more keys within ~300ms, trigger instant typing
                if len(self.recent_keypress_times) >= 2:
                    self.instant_typing_detected = True

    # ═══════════════════════════════════════════════════════════════════════════
    # START / STOP
    # ═══════════════════════════════════════════════════════════════════════════

    def start(self):
        """Start all input capture systems."""
        # Start pynput for clicks + keyboard + scroll (best-effort)
        self.mouse_listener.start()
        self.keyboard_listener.start()

        # Start cursor polling thread (reliable movement detection)
        self._poll_running = True
        self._poll_thread = Thread(target=self._poll_cursor, daemon=True)
        self._poll_thread.start()
        logger.info("Cursor polling started (GetCursorPos @ ~60Hz).")

    def stop(self):
        """Gracefully stop all listeners."""
        # Stop pynput
        self.mouse_listener.stop()
        self.keyboard_listener.stop()

        # Stop cursor polling
        self._poll_running = False
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=2)

    def get_and_reset(self):
        """
        Atomically read and reset counters.
        IMPORTANT: last_event_time is NEVER reset — only updated by real events.
        This prevents false idle detection.

        Returns:
            tuple: (clicks, keys, move_distance, scroll_count, last_event_time)
        """
        with self.lock:
            clicks = self.click_count
            keys = self.key_count
            move_dist = self.move_distance
            scrolls = self.scroll_count
            last_time = self.last_event_time

            # Reset only counts, NOT last_event_time
            self.click_count = 0
            self.key_count = 0
            self.move_distance = 0.0
            self.scroll_count = 0.0

        return clicks, keys, move_dist, scrolls, last_time

    def consume_instant_click(self):
        """Atomically read and reset the instant click flag."""
        with self.lock:
            val = self.instant_click_detected
            self.instant_click_detected = False
            return val

    def consume_instant_typing(self):
        """Atomically read and reset the instant typing flag."""
        with self.lock:
            val = self.instant_typing_detected
            self.instant_typing_detected = False
            return val

    def consume_instant_scroll(self):
        """Atomically read and reset the instant scroll flag."""
        with self.lock:
            val = self.instant_scroll_detected
            self.instant_scroll_detected = False
            return val
