import pystray

def dynamic_text(item):
    return "Dynamic"

try:
    item = pystray.MenuItem(dynamic_text, None, enabled=False)
    print("Callable text works")
except Exception as e:
    print(f"Callable text ERROR: {e}")
