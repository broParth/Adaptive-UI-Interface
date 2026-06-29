"""Final scroll test — fix ctypes overflow and capture scroll properly."""
import ctypes
import ctypes.wintypes
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", ctypes.wintypes.POINT),
        ("mouseData", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

# Use LPARAM as c_ssize_t to handle 64-bit pointers correctly
HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,         # LRESULT
    ctypes.c_int,          # nCode
    ctypes.c_size_t,       # WPARAM (unsigned pointer-size)
    ctypes.c_ssize_t,      # LPARAM (signed pointer-size) — FIX for 64-bit
)

# Fix CallNextHookEx argument types for 64-bit
user32.CallNextHookEx.restype = ctypes.c_long
user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p,   # HHOOK
    ctypes.c_int,      # nCode
    ctypes.c_size_t,   # WPARAM
    ctypes.c_ssize_t,  # LPARAM
]

scroll_events = []
move_count = [0]
hook_val = [None]

def hook_proc(nCode, wParam, lParam):
    if nCode >= 0:
        if wParam == WM_MOUSEMOVE:
            move_count[0] += 1
        elif wParam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
            try:
                hs = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                delta = ctypes.c_short(hs.mouseData >> 16).value
                scroll_events.append(delta)
                print(f"  SCROLL: delta={delta}")
            except Exception as e:
                print(f"  SCROLL parse error: {e}")
    return user32.CallNextHookEx(hook_val[0], nCode, wParam, lParam)

callback = HOOKPROC(hook_proc)

print("=" * 50)
print("FIXED SCROLL TEST — 64-bit safe")
print("=" * 50)
print("Move your mouse AND SCROLL for 8 seconds...")
print()

hook_val[0] = user32.SetWindowsHookExW(WH_MOUSE_LL, callback, 0, 0)
print(f"Hook: {hook_val[0]}")

if hook_val[0]:
    msg = ctypes.wintypes.MSG()
    start = time.time()
    while time.time() - start < 8:
        ret = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
        if ret:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        else:
            time.sleep(0.002)
    user32.UnhookWindowsHookEx(hook_val[0])
    
    print()
    print(f"Moves: {move_count[0]}")
    print(f"Scrolls: {len(scroll_events)}")
    if scroll_events:
        print(f"Scroll deltas: {scroll_events[:20]}")
        print("SCROLL CAPTURE: WORKING!")
    else:
        print("SCROLL CAPTURE: STILL FAILED")
        print("(This may be a touchpad driver issue)")
else:
    print("Hook failed to install")
