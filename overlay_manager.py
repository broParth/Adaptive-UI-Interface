"""
overlay_manager.py — Global Overlay Controller
Creates borderless, always-on-top, click-through overlay windows
that appear on top of ALL other applications based on FSM state.

Critical Fixes Applied:
  - Win32 WS_EX_LAYERED | WS_EX_TRANSPARENT for click-through
  - Animation generation counters to cancel stale fades
  - Destroyed-window protection
  - ~60 FPS fade interpolation (16ms steps)
  - Multi-monitor aware positioning via screeninfo
"""

import customtkinter as ctk
import ctypes
import logging

logger = logging.getLogger("AdaptiveUI.Overlay")

# ─── Win32 Constants for Click-Through ────────────────────────────────────────
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080  # Hide from taskbar


def _make_click_through(window):
    """
    Apply Win32 extended styles to make a window click-through.
    WS_EX_LAYERED | WS_EX_TRANSPARENT allows the overlay to remain visible
    but pass all mouse events through to the desktop/apps below.
    WS_EX_TOOLWINDOW hides it from the taskbar.
    """
    try:
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        logger.debug("Click-through applied to overlay hwnd=%s", hwnd)
    except Exception as e:
        logger.warning("Failed to apply click-through style: %s", e)


class OverlayController:
    """
    Manages state-specific overlay windows:
      - IDLE:   Full-screen dim overlay with "SYSTEM PAUSED"
      - FOCUS:  Minimal floating bar at top-center
      - ACTIVE: Small corner widget at bottom-right
      - ERROR:  Warning bar at top-center

    All overlays are click-through (Win32) and use non-blocking fade animations.
    """

    def __init__(self, root):
        self.root = root
        self._current_overlay = None

        # Get screen dimensions
        self.screen_w = root.winfo_screenwidth()
        self.screen_h = root.winfo_screenheight()

        # Animation generation counters (per window) for stale fade cancellation
        self._fade_gen = {}

        # IDLE overlay delay — prevents instant flash on brief inactivity
        self._idle_fade_pending = False
        self._idle_delay_gen = 0  # generation counter to cancel stale delays

        # Pre-build all overlays (hidden by default)
        self._build_idle_overlay()
        self._build_focus_overlay()
        self._build_active_overlay()
        self._build_error_overlay()

        # Apply click-through AFTER windows are mapped
        self.root.after(200, self._apply_all_click_through)

    def _apply_all_click_through(self):
        """Apply click-through styles to all overlay windows after they are realized."""
        for win in [self.idle_win, self.focus_win, self.active_win, self.error_win]:
            try:
                win.deiconify()
                win.update_idletasks()
                _make_click_through(win)
                win.withdraw()
            except Exception as e:
                logger.warning("Click-through setup failed for a window: %s", e)

    # ═══════════════════════════════════════════════════════════════════════════
    # IDLE OVERLAY — Full screen dim
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_idle_overlay(self):
        self.idle_win = ctk.CTkToplevel(self.root)
        self.idle_win.title("")
        self.idle_win.geometry(f"{self.screen_w}x{self.screen_h}+0+0")
        self.idle_win.overrideredirect(True)
        self.idle_win.attributes("-topmost", True)
        self.idle_win.attributes("-alpha", 0.0)
        self.idle_win._target_alpha = 0.0
        # Use semi-transparent dark instead of solid black
        self.idle_win.configure(fg_color="#0a0a1a")

        ctk.CTkLabel(
            self.idle_win,
            text="⏸  SYSTEM PAUSED",
            font=ctk.CTkFont(family="Consolas", size=42, weight="bold"),
            text_color="#4a4a6a",
        ).place(relx=0.5, rely=0.4, anchor="center")

        ctk.CTkLabel(
            self.idle_win,
            text="Move mouse or press any key to resume",
            font=ctk.CTkFont(family="Segoe UI", size=16),
            text_color="#3a3a5a",
        ).place(relx=0.5, rely=0.48, anchor="center")

        ctk.CTkLabel(
            self.idle_win,
            text="🧠 Adaptive UI Engine — Monitoring Input Streams",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#2a2a4a",
        ).place(relx=0.5, rely=0.58, anchor="center")

        self._fade_gen[id(self.idle_win)] = 0
        self.idle_win.withdraw()

    # ═══════════════════════════════════════════════════════════════════════════
    # FOCUS OVERLAY — Minimal floating bar
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_focus_overlay(self):
        bar_w, bar_h = 380, 40
        x = (self.screen_w - bar_w) // 2
        y = 8

        self.focus_win = ctk.CTkToplevel(self.root)
        self.focus_win.title("")
        self.focus_win.geometry(f"{bar_w}x{bar_h}+{x}+{y}")
        self.focus_win.overrideredirect(True)
        self.focus_win.attributes("-topmost", True)
        self.focus_win.attributes("-alpha", 0.0)
        self.focus_win._target_alpha = 0.0
        self.focus_win.configure(fg_color="#12111a")

        # Inner frame with border effect
        inner = ctk.CTkFrame(
            self.focus_win, fg_color="#12111a",
            corner_radius=12, border_width=1, border_color="#7c4dff"
        )
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        ctk.CTkLabel(
            inner,
            text="🎯  FOCUS MODE ACTIVE  —  Distractions minimized",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#b388ff",
        ).pack(expand=True)

        self._fade_gen[id(self.focus_win)] = 0
        self.focus_win.withdraw()

    # ═══════════════════════════════════════════════════════════════════════════
    # ACTIVE OVERLAY — Corner widget
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_active_overlay(self):
        widget_w, widget_h = 280, 70
        x = (self.screen_w - widget_w) // 2
        y = 8

        self.active_win = ctk.CTkToplevel(self.root)
        self.active_win.title("")
        self.active_win.geometry(f"{widget_w}x{widget_h}+{x}+{y}")
        self.active_win.overrideredirect(True)
        self.active_win.attributes("-topmost", True)
        self.active_win.attributes("-alpha", 0.0)
        self.active_win._target_alpha = 0.0
        self.active_win.configure(fg_color="#0d2137")

        inner = ctk.CTkFrame(
            self.active_win, fg_color="#0d2137",
            corner_radius=12, border_width=1, border_color="#00d4aa"
        )
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        ctk.CTkLabel(
            inner,
            text="⚡ ACTIVE MODE",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color="#00ffcc",
        ).pack(pady=(8, 0))

        self.active_metrics_label = ctk.CTkLabel(
            inner,
            text="Clicks: 0/s  |  Latency: 8ms",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color="#00d4aa",
        )
        self.active_metrics_label.pack(pady=(0, 8))

        self._fade_gen[id(self.active_win)] = 0
        self.active_win.withdraw()

    # ═══════════════════════════════════════════════════════════════════════════
    # ERROR OVERLAY — Warning bar
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_error_overlay(self):
        bar_w, bar_h = 420, 40
        x = (self.screen_w - bar_w) // 2
        y = 8

        self.error_win = ctk.CTkToplevel(self.root)
        self.error_win.title("")
        self.error_win.geometry(f"{bar_w}x{bar_h}+{x}+{y}")
        self.error_win.overrideredirect(True)
        self.error_win.attributes("-topmost", True)
        self.error_win.attributes("-alpha", 0.0)
        self.error_win._target_alpha = 0.0
        self.error_win.configure(fg_color="#1f0f0f")

        inner = ctk.CTkFrame(
            self.error_win, fg_color="#1f0f0f",
            corner_radius=12, border_width=1, border_color="#ff5252"
        )
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        ctk.CTkLabel(
            inner,
            text="⚠️  ERROR ASSISTANCE MODE  —  Low confidence input detected",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#ff8a80",
        ).pack(expand=True)

        self._fade_gen[id(self.error_win)] = 0
        self.error_win.withdraw()

    # ═══════════════════════════════════════════════════════════════════════════
    # ANIMATION AND MULTI-MONITOR
    # ═══════════════════════════════════════════════════════════════════════════

    def _get_active_monitor(self):
        """Find the monitor where the cursor is currently located, scaled to Tkinter's logical pixels."""
        try:
            from screeninfo import get_monitors
            monitors = get_monitors()
            
            # Calculate scaling factor (Tkinter logical width / Primary physical width)
            primary = next((m for m in monitors if m.is_primary), monitors[0])
            scale_x = self.screen_w / primary.width
            scale_y = self.screen_h / primary.height
            
            # Pointer is in logical pixels, convert to physical to find correct monitor
            cx = self.root.winfo_pointerx() / scale_x
            cy = self.root.winfo_pointery() / scale_y
            
            class LogicalMonitor:
                def __init__(self, m):
                    self.x = int(m.x * scale_x)
                    self.y = int(m.y * scale_y)
                    self.width = int(m.width * scale_x)
                    self.height = int(m.height * scale_y)
                    
            for m in monitors:
                if m.x <= cx <= m.x + m.width and m.y <= cy <= m.y + m.height:
                    return LogicalMonitor(m)
                    
            # Default to primary if pointer is somehow out of bounds
            return LogicalMonitor(primary)
            
        except Exception as e:
            logger.warning(f"Monitor detection failed: {e}")

        # Fallback to logical primary screen
        class DummyMonitor:
            x, y = 0, 0
            width, height = self.screen_w, self.screen_h
        return DummyMonitor()

    def _fade_to(self, win, target_alpha, step=0.05):
        """
        Non-blocking smooth fade to target alpha using the event loop.
        Uses generation counters to safely cancel stale animations.
        """
        win_id = id(win)
        # Increment generation to cancel any in-flight fade for this window
        self._fade_gen[win_id] = self._fade_gen.get(win_id, 0) + 1
        gen = self._fade_gen[win_id]
        win._target_alpha = target_alpha
        self._fade_step(win, target_alpha, step, gen)

    def _fade_step(self, win, target_alpha, step, gen):
        """Single step of a non-blocking fade animation (~60 FPS)."""
        win_id = id(win)

        # Stale fade check — cancel if a newer fade was started
        if self._fade_gen.get(win_id, 0) != gen:
            return

        # Destroyed window protection
        try:
            if not win.winfo_exists():
                return
        except Exception:
            return

        try:
            current = win.attributes("-alpha")
        except Exception:
            return  # Window destroyed mid-fade

        if abs(current - target_alpha) < step:
            try:
                win.attributes("-alpha", target_alpha)
                if target_alpha == 0.0:
                    win.withdraw()
            except Exception:
                pass
            return

        new_alpha = current + step if target_alpha > current else current - step
        new_alpha = max(0.0, min(1.0, new_alpha))  # Clamp to [0, 1]

        try:
            win.attributes("-alpha", new_alpha)
        except Exception:
            return  # Window destroyed

        # Schedule next step at ~60 FPS (16ms)
        self.root.after(16, lambda: self._fade_step(win, target_alpha, step, gen))

    def _format_active_label(self, metrics):
        """Build the ACTIVE overlay metric string showing cursor activity."""
        mps = metrics.get("movement_per_sec", 0)
        sps = metrics.get("scrolls_per_sec", 0)
        cps = metrics.get("clicks_per_sec", 0)
        lat = metrics.get("neural_latency", 8)
        # Show the dominant activity signal
        if mps > 50:
            return f"Move: {mps:.0f}px/s  |  Latency: {lat}ms"
        elif sps > 1:
            return f"Scroll: {sps:.0f}/s  |  Latency: {lat}ms"
        else:
            return f"Clicks: {cps:.0f}/s  |  Latency: {lat}ms"

    def show_state(self, state, metrics=None):
        """
        Show the overlay for the given state, hide all others.

        IDLE Safety Guard:
            The overlay is only shown when movement_per_sec < 5 AND
            scrolls_per_sec == 0, even if the FSM says IDLE.
            This prevents false SYSTEM PAUSED while browsing/scrolling.

        IDLE Fade-In Delay:
            The overlay waits 1.5s before fading in.  If the state changes
            within that window the fade is cancelled — no flash.
        """

        # ── IDLE safety: reject IDLE if cursor/scroll is happening ──
        if state == "IDLE" and metrics:
            mps = metrics.get("movement_per_sec", 0)
            sps = metrics.get("scrolls_per_sec", 0)
            if mps >= 5 or sps > 0:
                # There IS meaningful interaction — do NOT show IDLE overlay
                # Cancel any pending IDLE fade-in
                self._idle_delay_gen += 1
                self._idle_fade_pending = False
                # If IDLE overlay is currently visible, hide it
                if self._current_overlay == "IDLE":
                    self._hide_all()
                    self._current_overlay = None
                return

        if state == self._current_overlay:
            # If ACTIVE mode metrics changed, update label without repositioning/fading again
            if state == "ACTIVE" and metrics:
                try:
                    self.active_metrics_label.configure(
                        text=self._format_active_label(metrics)
                    )
                except Exception:
                    pass
            return

        # Not IDLE anymore → cancel any pending IDLE delay
        if state != "IDLE":
            self._idle_delay_gen += 1
            self._idle_fade_pending = False

        # Hide all first
        self._hide_all()

        m = self._get_active_monitor()

        if state == "IDLE":
            # Delayed fade-in — wait 1.5s before actually showing
            if not self._idle_fade_pending:
                self._idle_fade_pending = True
                self._idle_delay_gen += 1
                gen = self._idle_delay_gen
                self.root.after(1500, lambda: self._show_idle_after_delay(gen, m))
                self._current_overlay = state  # mark intent immediately
                return  # do NOT show yet

        elif state == "FOCUS":
            bar_w, bar_h = 380, 40
            x = m.x + (m.width - bar_w) // 2
            y = m.y + 8
            self.focus_win.geometry(f"{bar_w}x{bar_h}+{x}+{y}")
            self.focus_win.deiconify()
            self.focus_win.lift()
            if self.focus_win.attributes("-alpha") == 0.0:
                self.focus_win.attributes("-alpha", 0.7)  # Appear immediately
            self._fade_to(self.focus_win, 0.88, 0.10)

        elif state == "ACTIVE":
            if metrics:
                self.active_metrics_label.configure(
                    text=self._format_active_label(metrics)
                )
            widget_w, widget_h = 280, 70
            x = m.x + (m.width - widget_w) // 2
            y = m.y + 8
            self.active_win.geometry(f"{widget_w}x{widget_h}+{x}+{y}")
            self.active_win.deiconify()
            self.active_win.lift()
            if self.active_win.attributes("-alpha") == 0.0:
                self.active_win.attributes("-alpha", 0.75)  # Appear immediately
            self._fade_to(self.active_win, 0.88, 0.10)

        elif state == "ERROR":
            bar_w, bar_h = 420, 40
            x = m.x + (m.width - bar_w) // 2
            y = m.y + 8
            self.error_win.geometry(f"{bar_w}x{bar_h}+{x}+{y}")
            self.error_win.deiconify()
            self.error_win.lift()
            self._fade_to(self.error_win, 0.88, 0.06)

        self._current_overlay = state

    def _show_idle_after_delay(self, gen, m):
        """
        Show the IDLE overlay after a 1.5s delay.
        If the generation counter has changed, a newer state change
        cancelled this request — bail out.
        """
        if gen != self._idle_delay_gen:
            return  # Stale — state changed before the delay expired
        if self._current_overlay != "IDLE":
            return  # State already changed

        self._idle_fade_pending = False
        self.idle_win.geometry(f"{m.width}x{m.height}+{m.x}+{m.y}")
        self.idle_win.deiconify()
        self.idle_win.lift()
        self._fade_to(self.idle_win, 0.75, 0.03)  # Slower fade for smooth appearance

    def _hide_all(self):
        """Hide all overlay windows with fade-out."""
        self._fade_to(self.idle_win, 0.0, 0.12)
        self._fade_to(self.focus_win, 0.0, 0.12)
        self._fade_to(self.active_win, 0.0, 0.12)
        self._fade_to(self.error_win, 0.0, 0.12)

    def hide(self):
        """Hide all overlays (when dashboard is open)."""
        self._hide_all()
        self._current_overlay = None

    def destroy(self):
        """Clean up all overlay windows."""
        for win in [self.idle_win, self.focus_win, self.active_win, self.error_win]:
            try:
                win.destroy()
            except Exception:
                pass
