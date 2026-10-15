#!/home/z/.venv/bin/python3
"""subsys.py — extract subagent system prompts + dispatches from subagents_record.json"""
import hashlib, json, sys

def text_of(m):
    parts = []
    c = m.get("content")
    if isinstance(c, str) and c.strip():
        parts.append(c)
    elif isinstance(c, list) and c:
        parts.append(json.dumps(c, ensure_ascii=False))
    for b in (m.get("content_blocks") or []):
        if isinstance(b, dict):
            for k in ("content", "text", "reasoning"):
                v = b.get(k)
                if isinstance(v, str) and v.strip():
                    parts.append(v); break
    return "\n--BLOCK--\n".join(parts)

b = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "subagents_record.json",
                   encoding="utf-8"))
sysbuf = {}
for i, r in enumerate(b["data"]):
    ms = r.get("messages") or []
    for m in ms:
        if isinstance(m, dict) and m.get("role") == "system":
            t = text_of(m)
            h = hashlib.sha256(t.encode()).hexdigest()[:10]
            sysbuf.setdefault(h, t)
            print(f"rec{i} SYSTEM len={len(t)} sha={h}")
    us = [m for m in ms if isinstance(m, dict) and m.get("role") == "user"]
    if us:
        ut = text_of(us[0])
        print(f"rec{i} user[0] len={len(ut)} head={ut[:100]!r}")
    nb = sum(1 for m in ms for blk in (m.get("content_blocks") or [])
             if isinstance(blk, dict) and "reason" in str(blk.get("type", "")).lower())
    print(f"rec{i} reasoning_blocks={nb}  status={r.get('status')} turns={r.get('turn_count')}")

for h, t in sysbuf.items():
    fn = f"subagent_system_{h}.txt"
    open(fn, "w", encoding="utf-8").write(t)
    print(f"[out] {fn} ({len(t)} chars)")
