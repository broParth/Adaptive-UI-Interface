import pystray
try:
    item = pystray.MenuItem("Test", None, enabled=False)
    print("MenuItem with None is OK")
except Exception as e:
    print(f"ERROR: {e}")
