# pyc_extract.py — run with /home/z/.venv/bin/python3 (exact CPython 3.12 match)
import marshal, sys

raw = open(sys.argv[1], "rb").read()
# strip possible leading line numbers if the tool prepended "     1→"; find magic
idx = raw.find(b"\xcb\x0d\x0d\x0a")
if idx < 0:
    print("magic not found; first bytes:", raw[:16]); sys.exit(1)
data = raw[idx + 16:]  # 4B magic + 4B flags + 8B mtime/size header
code = marshal.loads(data)

def walk(co, depth=0):
    for c in co.co_consts:
        if hasattr(c, "co_consts"):
            walk(c, depth + 1)
        elif isinstance(c, str) and len(c) > 40:
            print(f"--- const ({len(c)} chars) ---")
            print(c)

walk(code)
