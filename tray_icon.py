"""
tray_icon.py — System Tray Controller
Runs the app icon in the system tray (like Discord, Spotify).
Provides right-click menu: Open Dashboard, Exit.
"""

import threading
import logging
from PIL import Image, ImageDraw
import pystray

logger = logging.getLogger("AdaptiveUI.Tray")


def _create_icon_image():
    """Generate a simple tray icon programmatically (no external file needed)."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark circle background
    draw.ellipse([4, 4, 60, 60], fill="#0d2137", outline="#00d4aa", width=2)

    # Brain emoji approximation — inner shape
    draw.ellipse([18, 14, 46, 42], fill="#00d4aa")
    draw.ellipse([22, 18, 42, 38], fill="#0d2137")
    draw.ellipse([26, 22, 38, 34], fill="#00d4aa")

    # Bottom dot (status indicator)
    draw.ellipse([26, 46, 38, 54], fill="#00ffcc")

    return img


class TrayIcon:
    """
    System tray icon with menu:
      - Open Dashboard
      - Engine Status (read-only)
      - Pause/Resume Monitoring
      - Exit
    """

    def __init__(self, on_open_dashboard, on_toggle_pause, on_exit):
        self.on_open_dashboard = on_open_dashboard
        self.on_toggle_pause = on_toggle_pause
        self.on_exit = on_exit
        self._state = "IDLE"
        self._is_paused = False
        self._icon = None
        self._thread = None

    def set_paused(self, is_paused):
        """Update the paused state so the menu text can update."""
        self._is_paused = is_paused
        if self._icon:
            self._icon.update_menu()

    def _build_menu(self):
        """Build the right-click menu."""
        return pystray.Menu(
            pystray.MenuItem(
                "🧠 Adaptive UI Engine",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Open Dashboard",
                self._on_open,
            ),
            pystray.MenuItem(
                lambda item: f"State: {self._state}",
                None,
                enabled=False,
            ),
            pystray.MenuItem(
                lambda item: "▶ Resume Monitoring" if self._is_paused else "⏸ Pause Monitoring",
                self._on_toggle_pause_click,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Exit",
                self._on_exit,
            ),
        )

    def _on_open(self, icon, item):
        """Handle 'Open Dashboard' click."""
        self.on_open_dashboard()

    def _on_toggle_pause_click(self, icon, item):
        """Handle 'Pause/Resume' click."""
        self.on_toggle_pause()

    def _on_exit(self, icon, item):
        """Handle 'Exit' click."""
        self.on_exit()

    def update_state(self, state):
        """Update the displayed state in the menu."""
        if self._state != state:
            self._state = state
            if self._icon:
                self._icon.update_menu()

    def start(self):
        """Start the tray icon in a background thread."""
        if self._icon is not None:
            return

        self._icon = pystray.Icon(
            name="adaptive_ui",
            icon=_create_icon_image(),
            title="Adaptive UI Engine — Running",
            menu=self._build_menu(),
        )

        # Run in background thread (pystray has its own event loop)
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the tray icon."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
