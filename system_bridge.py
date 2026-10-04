"""
system_bridge.py — System-Level Adaptive Bridge
Applies system-level changes based on FSM state:
  - Brightness control (with fallback to overlay dimming)
  - Desktop notifications with throttling (5s cooldown)

Phase 1.5 additions:
  - Capture original display brightness at startup; restore it on exit.
  - BROWSING restores the user's original captured brightness.
  - Skip redundant set_brightness() calls when the target value has not changed.
  - Routine FSM transitions do not generate OS-level Windows notifications.
  - If original brightness was never captured, restoration is a no-op (no fallback invented).
"""

import threading
import time
import logging
import ctypes
import json
import os
import atexit

logger = logging.getLogger("AdaptiveUI.Bridge")

_last_notification_time = 0.0
_notification_lock = threading.Lock()
NOTIFICATION_COOLDOWN = 5.0

_brightness_available = None
_prev_state = None
_state_lock = threading.Lock()

# ─── Brightness Ownership ───
# Original brightness captured at startup so it can be restored on exit.
_original_brightness = None          # int | None — captured once at init
_current_applied_brightness = None   # int | None — last value written to hardware
_brightness_lock = threading.Lock()

# ─── Mouse Speed Safety Globals ───
_original_mouse_speed = None
_mouse_speed_modified = False
_mouse_lock = threading.Lock()
SPI_GETMOUSESPEED = 0x0070
SPI_SETMOUSESPEED = 0x0071
SPIF_SENDCHANGE = 0x0002
RUNTIME_STATE_FILE = "runtime_state.json"
BRIGHTNESS_STATE_FILE = "brightness_state.json"

_brightness_recorded_in_sidecar = False
_startup_recovery_failed = False
_restored_once = False


def _init_mouse_safety():
    """Capture original speed and recover from past crashes."""
    global _original_mouse_speed
    try:
        # Check for crash recovery
        if os.path.exists(RUNTIME_STATE_FILE):
            with open(RUNTIME_STATE_FILE, "r") as f:
                data = json.load(f)
                recovered_speed = data.get("original_mouse_speed")
                if recovered_speed:
                    ctypes.windll.user32.SystemParametersInfoW(SPI_SETMOUSESPEED, 0, ctypes.c_void_p(recovered_speed), SPIF_SENDCHANGE)
                    logger.info("Recovered mouse speed from previous crash: %d", recovered_speed)
            os.remove(RUNTIME_STATE_FILE)

        # Capture current speed
        speed = ctypes.c_int()
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETMOUSESPEED, 0, ctypes.byref(speed), 0):
            _original_mouse_speed = speed.value
            logger.info("Original mouse speed captured: %d", _original_mouse_speed)
        else:
            _original_mouse_speed = 10
            logger.warning("Failed to get original mouse speed, assuming 10")

    except Exception as e:
        logger.warning("Mouse safety init failed: %s", e)
        _original_mouse_speed = 10

# Initialize immediately on import
_init_mouse_safety()


def _capture_original_brightness():
    """Read and cache the current display brightness once at startup."""
    global _original_brightness, _brightness_available, _startup_recovery_failed
    try:
        import screen_brightness_control as sbc

        if os.path.exists(BRIGHTNESS_STATE_FILE):
            try:
                with open(BRIGHTNESS_STATE_FILE, "r") as f:
                    data = json.load(f)
                    saved_orig = data.get("original_brightness")
                if saved_orig is not None:
                    saved_orig = int(saved_orig)
                    logger.info("Found stale brightness recovery record: %d%%", saved_orig)
                    sbc.set_brightness(saved_orig)
                    os.remove(BRIGHTNESS_STATE_FILE)
                    logger.info("Successfully recovered brightness from previous unclean exit.")
            except Exception as e:
                logger.warning("Failed to recover brightness from sidecar: %s", e)
                _startup_recovery_failed = True

        if _startup_recovery_failed:
            _original_brightness = None
            _brightness_available = False
            logger.warning("Startup recovery failed. Brightness control disabled for this session.")
            return

        value = sbc.get_brightness()
        # get_brightness returns a list; take the first monitor's value.
        if isinstance(value, (list, tuple)):
            value = value[0]
        _original_brightness = int(value)
        _brightness_available = True
        logger.info("Original brightness captured: %d%%", _original_brightness)
    except Exception as e:
        _brightness_available = False
        logger.info("Could not capture original brightness (brightness control unavailable): %s", e)


# Capture immediately on module load so every code path has access to it.
_capture_original_brightness()


def _record_brightness_sidecar():
    global _brightness_recorded_in_sidecar
    if _brightness_recorded_in_sidecar or _original_brightness is None or _startup_recovery_failed:
        return
    try:
        tmp_file = BRIGHTNESS_STATE_FILE + ".tmp"
        with open(tmp_file, "w") as f:
            json.dump({"original_brightness": _original_brightness}, f)
        os.replace(tmp_file, BRIGHTNESS_STATE_FILE)
        _brightness_recorded_in_sidecar = True
    except Exception as e:
        logger.warning("Failed to write brightness sidecar: %s", e)


def _set_brightness_safe(level):
    """Write brightness to hardware. Skips the call if the value is already applied."""
    global _brightness_available, _current_applied_brightness, _restored_once
    level = int(level)
    with _brightness_lock:
        if _current_applied_brightness == level:
            return  # Already at this level — no redundant hardware write.

    _record_brightness_sidecar()
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(level)
        with _brightness_lock:
            _current_applied_brightness = level
        _brightness_available = True
        _restored_once = False
    except Exception as e:
        _brightness_available = False
        logger.info("Brightness unavailable: %s", e)


def set_brightness(level):
    threading.Thread(target=_set_brightness_safe, args=(level,), daemon=True).start()


def is_brightness_available():
    return _brightness_available is True


def _notify_safe(title, message):
    global _last_notification_time
    with _notification_lock:
        now = time.time()
        if now - _last_notification_time < NOTIFICATION_COOLDOWN:
            return
        _last_notification_time = now
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="Adaptive UI Engine", timeout=3)
    except Exception as e:
        logger.info("Notification failed: %s", e)


def notify(title, message):
    threading.Thread(target=_notify_safe, args=(title, message), daemon=True).start()


def _set_mouse_speed(level, record_modified=True):
    global _mouse_speed_modified
    with _mouse_lock:
        # Prevent unnecessary API spam
        if record_modified and _mouse_speed_modified:
            return
        if not record_modified and not _mouse_speed_modified:
            return

        try:
            ctypes.windll.user32.SystemParametersInfoW(SPI_SETMOUSESPEED, 0, ctypes.c_void_p(level), SPIF_SENDCHANGE)
            _mouse_speed_modified = record_modified

            if record_modified:
                # Write recovery file to protect against crashes
                with open(RUNTIME_STATE_FILE, "w") as f:
                    json.dump({"original_mouse_speed": _original_mouse_speed}, f)
            else:
                # Remove recovery file once safely restored
                if os.path.exists(RUNTIME_STATE_FILE):
                    os.remove(RUNTIME_STATE_FILE)
        except Exception as e:
            logger.warning("Failed to set mouse speed: %s", e)


def apply_mouse_slowdown():
    if _original_mouse_speed and _original_mouse_speed > 8:
        _set_mouse_speed(8, record_modified=True)


def restore_mouse_speed():
    if _original_mouse_speed:
        _set_mouse_speed(_original_mouse_speed, record_modified=False)


def invalidate_brightness_state():
    """
    Force the next apply_system_effects() call to re-apply the current FSM
    state's brightness even if the state name has not changed.

    Used on resume from manual pause: the hardware brightness has been restored
    to original, so the FSM state's target must be written again regardless of
    whether _prev_state matches the current state.
    """
    global _prev_state
    with _state_lock:
        _prev_state = None


def apply_system_effects(state, state_duration=0.0):
    global _prev_state

    # ─── 1. Mouse Speed Persistence (Duration Based) ───
    if state == "FOCUS" and state_duration >= 3.0:
        apply_mouse_slowdown()
    else:
        restore_mouse_speed()

    # ─── 2. General State Effects (Debounced on state change) ───
    #
    # Routine FSM transitions do NOT generate OS-level Windows notifications.
    # The in-app adaptive overlay is the primary real-time feedback channel.
    # Notifications are reserved for out-of-band or user-critical alerts only.
    with _state_lock:
        if state == _prev_state:
            return  # State unchanged — skip redundant effect application.
        _prev_state = state

    if state == "IDLE":
        set_brightness(30)           # Dim screen on inactivity
    elif state == "FOCUS":
        set_brightness(80)           # Comfortable reading brightness for focused work
    elif state == "ACTIVE":
        set_brightness(100)          # Full brightness for high-intensity interaction
    elif state in ("BROWSING", "NORMAL"):
        # Restore original pre-application brightness when returning to normal use.
        # This handles transitions like ACTIVE(100%) -> BROWSING where the display
        # would otherwise stay at the previous state's brightness level.
        if _original_brightness is not None:
            set_brightness(_original_brightness)
        # If original was never captured, leave hardware untouched.
    elif state in ("ASSIST", "ERROR", "ANOMALY"):
        pass  # No brightness change for ASSIST


def restore_original_brightness():
    """
    Restore the display brightness to the value captured at application startup.

    Called on clean application exit, manual pause, and any other path where
    the application is relinquishing brightness control.

    If the original brightness could not be captured at startup (e.g. the
    display driver does not support brightness control), this function logs
    a notice and returns WITHOUT touching hardware.  No fallback value such
    as 50% or 100% is invented.
    """
    global _restored_once, _brightness_recorded_in_sidecar, _current_applied_brightness
    if _restored_once:
        return

    if _original_brightness is None:
        logger.info(
            "restore_original_brightness: original value was not captured "
            "(brightness control unavailable at startup); leaving hardware unchanged."
        )
        return

    logger.info("Restoring display brightness to %d%% (original)", _original_brightness)
    try:
        import screen_brightness_control as sbc
        with _brightness_lock:
            needs_write = (_current_applied_brightness != _original_brightness)

        if needs_write:
            sbc.set_brightness(_original_brightness)
            with _brightness_lock:
                _current_applied_brightness = _original_brightness

        if os.path.exists(BRIGHTNESS_STATE_FILE):
            os.remove(BRIGHTNESS_STATE_FILE)

        _brightness_recorded_in_sidecar = False
        _restored_once = True
    except Exception as e:
        logger.warning("restore_original_brightness failed: %s", e)


def reset_brightness():
    """Legacy alias — restores the original pre-application brightness."""
    restore_original_brightness()


atexit.register(restore_original_brightness)
