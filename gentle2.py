#!/usr/bin/env python3
"""Phase FINAL-2: byte-roundtrip mcp.pyc from persisted output; capture full tools/list.

Recovery chain for the .pyc:
  persisted file (UTF-8 text) -> strip "NNNâ]" line prefixes -> join -> encode latin-1
  -> original bytes (each byte became exactly one codepoint U+00xx, so this is
  reversible) -> find magic \xcb\x0d\x0d\x0a -> marshal.loads -> walk code objects.

  Caveat: _format_numbered_lines does expandtabs(), so 0x09 bytes inside the
  marshal stream were expanded to spaces -> length prefixes past the first tab
  may be shifted. If marshal.loads fails, fall back to regex-extracting long
  printable runs from the roundtripped bytes (string constants survive this).
"""
import json
import marshal
import re
import requests

URL = "http://127.0.0.1:12600/mcp"
HDRS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
DL = "/home/z/my-project/download"
PERSISTED = "/home/z/my-project/tool-results/read_1791371335337_ae9040be651c.txt"
MAGIC = b"\xcb\x0d\x0d\x0a"

_dec = json.JSONDecoder()


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


# ------------------------------------------------------- .pyc recovery

PREFIX_RE = re.compile(r"^ *\d+(?:\u2192|\xe2[^\n]{0,2}|[^\n])", re.UNICODE)


def recover_bytes(persisted_path):
    raw = open(persisted_path, encoding="utf-8", errors="replace").read()
    lines = raw.split("\n")
    stripped = []
    for ln in lines:
        m = PREFIX_RE.match(ln)
        if m:
            stripped.append(ln[m.end():])
        else:
            stripped.append(ln)   # continuation of a \r-split? keep as-is
    text = "\n".join(stripped)
    # latin-1 roundtrip: codepoints above 0xFF are formatter artifacts (arrow);
    # they were stripped with the prefix. Ignore anything unreachable.
    data = text.encode("latin-1", errors="ignore")
    return data


def salvage_consts(data):
    """Try marshal on recovered bytes; else regex printable runs."""
    idx = data.find(MAGIC)
    if idx >= 0:
        for hdr in (16, 12):
            try:
                code = marshal.loads(data[idx + hdr:])
                found = []

                def walk(co, prefix):
                    try:
                        for c in co.co_consts:
                            if hasattr(c, "co_consts"):
                                walk(c, prefix + "/" + (c.co_name or "?"))
                            elif isinstance(c, str) and len(c) >= 40:
                                found.append((prefix, c))
                    except Exception:
                        pass

                walk(code, "<module>")
                return ("marshal", found)
            except Exception:
                continue
    # regex fallback on raw bytes
    found = []
    for m in re.finditer(rb"[\x20-\x7e\t\r\n]{60,}", data):
        found.append(("<regex>", m.group(0).decode("ascii", errors="replace")))
    return ("regex", found)


# ------------------------------------------------------- main

def main():
    import os
    report = []

    def log(s):
        report.append(s)
        print(s, flush=True)

    # ---- Part 1: recover mcp.pyc from persisted output ----
    log("=== Part 1: mcp.pyc byte recovery ===")
    try:
        data = recover_bytes(PERSISTED)
        open(f"{DL}/mcp_recovered.bin", "wb").write(data)
        log(f"roundtripped {len(data)} bytes from persisted output")
        mode, consts = salvage_consts(data)
        log(f"salvage mode: {mode}, {len(consts)} long strings")
        with open(f"{DL}/mcp_consts.txt", "w", encoding="utf-8") as f:
            for tag, s in consts:
                f.write(f"\n===== [{tag}] ({len(s)} chars) =====\n{s}\n")
        # names/structure if marshal worked: look for sys.path hints
        if mode == "marshal":
            idx = data.find(MAGIC)
            code = marshal.loads(data[idx + 16:])
            with open(f"{DL}/mcp_structure.txt", "w") as f:
                def walk(co, d):
                    f.write(f"{'  '*d}CODE {co.co_name} names={co.co_names}\n")
                    for c in co.co_consts:
                        if hasattr(c, "co_consts"):
                            walk(c, d + 1)
                walk(code, 0)
            log(f"structure dump -> mcp_structure.txt; module names: {code.co_names}")
    except Exception as e:
        log(f"[recovery failed: {type(e).__name__}: {e}]")

    # ---- Part 2: check for other persisted outputs ----
    log("\n=== Part 2: tool-results inventory ===")
    try:
        for f in sorted(os.listdir("/home/z/my-project/tool-results")):
            p = f"/home/z/my-project/tool-results/{f}"
            log(f"  {os.path.getsize(p):>9}  {f}")
    except Exception as e:
        log(f"  [{e}]")

    # ---- Part 3: full untruncated tools/list ----
    log("\n=== Part 3: full tools/list capture ===")
    r = requests.post(URL, headers=HDRS, json={
        "jsonrpc": "2.0", "id": 99, "method": "tools/list"}, timeout=120)
    open(f"{DL}/tools_list_full.body", "wb").write(r.content)
    texts = extract_texts(r.text)
    total = sum(len(t) for t in texts)
    log(f"tools/list: {len(r.content)} bytes raw, {len(texts)} text fields, "
        f"{total} chars of tool description text")
    # quick sanity: count occurrences of known description markers
    for marker in ("Executes a given bash command", "Fast file pattern matching",
                   "ripgrep", "TodoWrite"):
        log(f"  contains '{marker}': {marker in r.text}")

    with open(f"{DL}/phase_final2_report.txt", "w") as f:
        f.write("\n".join(report))
    print(f"\nReport: {DL}/phase_final2_report.txt")


if __name__ == "__main__":
    main()
