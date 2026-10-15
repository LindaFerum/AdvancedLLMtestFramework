#!/home/z/.venv/bin/python3 
import json, sys
b = json.load(open(sys.argv[1]))
for i, m in enumerate(b.get("messages_flat") or []):
    if m.get("role") != "assistant":
        continue
    u = m.get("usage") or {}
    nb = m.get("content_blocks") or []
    nr = sum(1 for x in nb if isinstance(x, dict)
             and "reason" in str(x.get("type", "")).lower())
    print(i, "prompt=", u.get("prompt_tokens"),
          "completion=", u.get("completion_tokens"),
          "reasoning_blocks=", nr)
sa = b.get("subagents")
print("subagents payload:", list(sa.keys()) if isinstance(sa, dict)
      else type(sa).__name__)
