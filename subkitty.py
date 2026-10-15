#!/home/z/.venv/bin/python3
"""subkitty.py — triage a subagents record without reading 3MB by eye.
Usage: python3 subkitty.py subagents_record.json [out_prefix]"""
import json, sys
from collections import Counter

raw = json.load(open(sys.argv[1], encoding="utf-8"))
data = raw.get("data") if isinstance(raw, dict) else raw
print("[top] type:", type(raw).__name__, "| keys:", list(raw)[:8] if isinstance(raw, dict) else "-")

recs = data if isinstance(data, list) else (list(data.values()) if isinstance(data, dict) else [data])
print(f"[data] {len(recs)} record(s)")

prefix = sys.argv[2] if len(sys.argv) > 2 else "subagent"
for n, r in enumerate(recs):
    if not isinstance(r, dict):
        print(f"[{n}] non-dict: {type(r).__name__}"); continue
    print(f"\n=== record {n} ===")
    for k, v in r.items():
        s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
        if k.lower() in ("messages", "history", "content_blocks", "transcript", "content", "chat"):
            print(f"  {k}: <{len(s)} chars — bulk>")
        else:
            print(f"  {k}: {s[:220]}")
    keys = {k.lower(): k for k in r}
    for want in ("model", "usage", "status", "type", "subagent_type", "task_id", "prompt"):
        hit = keys.get(want)
        if hit:
            print(f"  [want] {want} = {json.dumps(r[hit], ensure_ascii=False)[:400]}")
    msgs = None
    for k in ("messages", "history", "transcript", "content_blocks"):
        if k in r and isinstance(r[k], (list, dict)):
            msgs = r[k]; print(f"  [bulk] key '{k}' holds the transcript"); break
    if msgs is not None:
        if isinstance(msgs, dict):
            msgs = list(msgs.values())
        roles = Counter(str(m.get("role", "?")) if isinstance(m, dict) else "?" for m in msgs)
        print(f"  [census] {len(msgs)} messages, roles={dict(roles)}")
        # dump a slim version: role/model/ts + block types per message, text/reasoning capped
        slim = []
        for i, m in enumerate(msgs):
            if not isinstance(m, dict): continue
            e = {"i": i, "role": m.get("role"), "model": m.get("model"), "ts": m.get("timestamp")}
            bl = []
            for b in (m.get("content_blocks") or []):
                if isinstance(b, dict):
                    t = b.get("type")
                    if t == "tool_calls":
                        cs = b.get("content") if isinstance(b.get("content"), list) else []
                        for c in cs[:4]:
                            fn = (c.get("function") or {}) if isinstance(c, dict) else {}
                            bl.append({"t": "tool", "name": fn.get("name")})
                    else:
                        for key in ("content", "text", "reasoning"):
                            v = b.get(key)
                            if isinstance(v, str) and v:
                                bl.append({"t": t, "v": v[:2000]}); break
            e["blocks"] = bl
            slim.append(e)
        out = f"{prefix}_{n}_slim.json"
        json.dump(slim, open(out, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  [out] wrote {out}")
