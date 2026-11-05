"""Print the focused Chrome tab's accessibility tree with neutral roles.
usage: dump.py [url]   (navigates with real keystrokes first if url given)"""
import sys
import time

from desktop import get_desktop

d = get_desktop()
d.launch_application("chrome")
if len(sys.argv) > 1:
    d.press("focus_address_bar"); d.type_text(sys.argv[1]); d.press("enter")
    time.sleep(6)
root = None
for _ in range(10):
    root = d.web_root("chrome")
    if root and len(root.children):
        break
    time.sleep(1)
print("WINDOW:", d.window_title("chrome"))
if not root:
    sys.exit("no web document")
n = 0
def show(node, depth):
    global n
    n += 1
    bits = [node.role] + [f'{k}="{v[:100]}"' for k, v in (("name", node.name), ("value", node.value)) if v]
    if node.dom_id:
        bits.append("#" + node.dom_id)
    print("  " * depth + " ".join(bits))
    for c in node.children:
        show(c, depth + 1)
show(root, 0)
print("NODES:", n)
