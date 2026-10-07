#!/usr/bin/env python3
"""Phase FINAL-3 (local only): 
  1. filter/flag interesting strings in mcp_consts.txt
  2. roundtrip-salvage the mystery persisted output (94,913 bytes)
  3. parse tools_list_full.body into per-tool full descriptions
"""
import json
import marshal
import re
from pathlib import Path

DL = Path("/home/z/my-project/download")
TR = Path("/home/z/my-project/tool-results")
MAGIC = b"\xcb\x0d\x0d\x0a"

PREFIX_RE = re.compile(r"^ *\d+(?:\u2192|\xe2[^\n]{0,2}|[^\n])", re.UNICODE)


def recover_bytes(persisted_path):
    raw = Path(persisted_path).read_text(encoding="utf-8", errors="replace")
    stripped = []
    for ln in raw.split("\n"):
        m = PREFIX_RE.match(ln)
        stripped.append(ln[m.end():] if m else ln)
    return "\n".join(stripped).encode("latin-1", errors="ignore")


def salvage_consts(data):
    idx = data.find(MAGIC)
    if idx >= 0:
        for hdr in (16, 12):
            try:
                code = marshal.loads(data[idx + hdr:])
                found = []
                def walk(co, prefix):
                    for c in co.co_consts:
                        if hasattr(c, "co_consts"):
                            walk(c, prefix + "/" + (c.co_name or "?"))
                        elif isinstance(c, str) and len(c) >= 40:
                            found.append((prefix, c))
                walk(code, "<module>")
                return ("marshal", found)
            except Exception:
                continue
    found = [("<regex>", m.group(0).decode("ascii", errors="replace"))
             for m in re.finditer(rb"[\x20-\x7e\t\r\n]{60,}", data)]
    return ("regex", found)


INTERESTING = ("prompt", "sys.path", "path", "import", "zip", "app.",
               "internal-api", "gateway", "token", "system", "You are",
               "role", "messages", "completions", "chat", "http", "url")


def flag(consts):
    hits = []
    for tag, s in consts:
        low = s.lower()
        if any(k.lower() in low for k in INTERESTING):
            hits.append((tag, s))
    return hits


def main():
    print("=" * 60)
    print("PART 1: mcp_consts.txt — flagged strings")
    print("=" * 60)
    raw = (DL / "mcp_consts.txt").read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n===== \[([^\]]+)\] \(\d+ chars\) =====\n", raw)
    # blocks: ['', tag1, text1, tag2, text2, ...]
    consts = [(blocks[i], blocks[i + 1]) for i in range(1, len(blocks) - 1, 2)]
    print(f"parsed {len(consts)} consts from mcp_consts.txt")
    hot = flag(consts)
    out = DL / "mcp_consts_FLAGGED.txt"
    with out.open("w", encoding="utf-8") as f:
        for tag, s in hot:
            f.write(f"\n===== [{tag}] ({len(s)} chars) =====\n{s}\n")
    print(f"flagged {len(hot)}/{len(consts)} -> {out}")

    print()
    print("=" * 60)
    print("PART 2: mystery persisted output 94,913 bytes")
    print("=" * 60)
    mystery = TR / "read_1791363685228_536e1f484ace.txt"
    if mystery.exists():
        data = recover_bytes(mystery)
        (DL / "mystery_recovered.bin").write_bytes(data)
        is_pyc = data.find(MAGIC) >= 0
        print(f"roundtripped {len(data)} bytes; pyc magic present: {is_pyc}")
        print("head 120 bytes (repr):", repr(data[:120]))
        mode, consts2 = salvage_consts(data)
        print(f"salvage mode: {mode}, {len(consts2)} long strings")
        with (DL / "mystery_consts.txt").open("w", encoding="utf-8") as f:
            for tag, s in consts2:
                f.write(f"\n===== [{tag}] ({len(s)} chars) =====\n{s}\n")
        with (DL / "mystery_consts_FLAGGED.txt").open("w", encoding="utf-8") as f:
            for tag, s in flag(consts2):
                f.write(f"\n===== [{tag}] ({len(s)} chars) =====\n{s}\n")
    else:
        print("[mystery file gone]")

    print()
    print("=" * 60)
    print("PART 3: parse tools_list_full.body -> full tool descriptions")
    print("=" * 60)
    body = (DL / "tools_list_full.body").read_text(encoding="utf-8", errors="replace")
    payload = "".join(l[5:].lstrip() for l in body.splitlines()
                      if l.startswith("data:"))
    obj, _ = json.JSONDecoder().raw_decode(payload)
    tools = obj["result"]["tools"]
    print(f"{len(tools)} tools parsed")
    with (DL / "tools_full.json").open("w", encoding="utf-8") as f:
        json.dump(tools, f, indent=2, ensure_ascii=False)
    total = sum(len(t.get("description", "")) for t in tools)
    print(f"total description text: {total} chars -> tools_full.json")
    for t in tools:
        d = t.get("description", "")
        print(f"  {t['name']:24} desc={len(d):6} chars  "
              f"args={list(t.get('inputSchema', {}).get('properties', {}).keys())}")


if __name__ == "__main__":
    main()
