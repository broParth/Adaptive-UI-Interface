"""
system_bridge.py — System-Level Adaptive Bridge
Applies system-level changes based on FSM state:
  - Brightness control (with fallback to overlay dimming)
  - Desktop notifications with throttling (5s cooldown)
"""

import threading
import time
import logging
import ctypes
import json
import os

logger = logging.getLogger("AdaptiveUI.Bridge")

_last_notification_time = 0.0
_notification_lock = threading.Lock()
NOTIFICATION_COOLDOWN = 5.0

_brightness_available = None
_prev_state = None
_state_lock = threading.Lock()

# ─── Mouse Speed Safety Globals ───
_original_mouse_speed = None
_mouse_speed_modified = False
_mouse_lock = threading.Lock()
SPI_GETMOUSESPEED = 0x0070
SPI_SETMOUSESPEED = 0x0071
SPIF_SENDCHANGE = 0x0002
RUNTIME_STATE_FILE = "runtime_state.json"


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


def _set_brightness_safe(level):
    global _brightness_available
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(level)
        _brightness_available = True
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


def apply_system_effects(state, state_duration=0.0):
    global _prev_state
    
    # ─── 1. Mouse Speed Persistence (Duration Based) ───
    if state == "FOCUS" and state_duration >= 3.0:
        apply_mouse_slowdown()
    else:
        restore_mouse_speed()

    # ─── 2. General State Effects (Debounced) ───
    with _state_lock:
        if state == _prev_state:
            return
        _prev_state = state

    if state == "IDLE":
        set_brightness(30)
        notify("💤 System Paused", "No activity detected — screen dimmed")
    elif state == "FOCUS":
        set_brightness(80)
        notify("🎯 Focus Mode", "Distraction-free workspace enabled")
    elif state == "ACTIVE":
        set_brightness(100)
        notify("⚡ Active Mode", "UI optimized for rapid interaction")
    elif state == "ERROR":
        set_brightness(70)
        notify("⚠️ Error Assistance", "Low confidence input — assistance enabled")


def reset_brightness():
    set_brightness(100)
