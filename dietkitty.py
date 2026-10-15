#!/usr/bin/env python3
"""dietkitty.py — distill a sharegentle bundle to analysis-essential data.

Drops: batch (merged already), share tree, file blobs, verbose bodies.
Keeps: per-msg role/model/timestamp, tool-call names+args(head), usage,
       content-block histogram, and reasoning/thinking blocks (generous cap).

Output: <out>.json   — distilled bundle (bounded)
        <out>.reasoning.txt — all thinking blocks w/ message context (the gold)
        console     — summary block; paste this + reasoning.txt to the analyst.

Usage: python3 dietkitty.py sitting_share.json download/diet [--full 6000] [--short 240]
       (out base defaults to input name minus .json)
"""
import argparse, json, os, sys
from collections import Counter

THINK_TYPES = {"thinking", "reasoning", "reasoning_content", "thought", "reason"}
MSG_THINK_KEYS = ("reasoning", "thinking", "reasoning_content")

def block_text(b):
    for k in ("thinking", "reasoning_content", "reasoning", "text", "content", "output"):
        v = b.get(k)
        if isinstance(v, str) and v:
            return k, v
    return None, None

def tool_name(b):
    if isinstance(b.get("tool"), dict):
        n = b["tool"].get("name")
        if n: return n
    if isinstance(b.get("function"), dict):
        n = b["function"].get("name")
        if n: return n
    return b.get("name") or b.get("toolName") or "?"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("infile")
    ap.add_argument("outbase", nargs="?")
    ap.add_argument("--full", type=int, default=6000, help="cap per reasoning block")
    ap.add_argument("--short", type=int, default=240, help="cap per other text")
    a = ap.parse_args()
    base = a.outbase or os.path.splitext(a.infile)[0]
    bundle = json.load(open(a.infile, encoding="utf-8"))

    msgs = bundle.get("messages_flat") or []
    chat = (bundle.get("share") or {}).get("chat") or {}

    roles, models, btypes = Counter(), Counter(), Counter()
    usage = {"prompt": 0, "completion": 0, "n": 0}
    distilled, reason_lines = [], []

    for i, m in enumerate(msgs):
        role = m.get("role", "?")
        roles[role] += 1
        if role == "assistant" and m.get("model"):
            models[m["model"]] += 1
        e = {"i": i, "id": str(m.get("id", ""))[:8], "role": role,
             "ts": m.get("timestamp")}
        if m.get("model"): e["model"] = m["model"]
        if m.get("files"): e["files"] = [str(f.get("name", "?")) for f in m.get("files", [])
                                        if isinstance(f, dict)][:6]
        u = m.get("usage") or {}
        p = u.get("prompt_tokens") or u.get("prompt_token_count")
        c = u.get("completion_tokens") or u.get("completion_token_count")
        if p: usage["prompt"] += p
        if c: usage["completion"] += c
        if u: usage["n"] += 1

        blocks = []
        for b in m.get("content_blocks") or []:
            if not isinstance(b, dict):
                continue
            t = str(b.get("type", "?")); btypes[t] += 1
            tl = t.lower()
            if tl in THINK_TYPES or tl.startswith("think") or tl.startswith("reason"):
                k, v = block_text(b)
                if v:
                    blocks.append({"t": t, "k": k, "v": v[:a.full]})
                    reason_lines.append(f"### msg#{i} {role} model={m.get('model','?')} "
                                        f"[{k}/{t}]\n{v[:a.full]}\n")
            elif "tool" in tl or "function" in tl or "action" in tl:
                args = b.get("arguments") or b.get("input") or b.get("parameters") or {}
                if not isinstance(args, str):
                    args = json.dumps(args, ensure_ascii=False)
                blocks.append({"t": t, "name": tool_name(b), "args": str(args)[:a.short]})
            else:
                k, v = block_text(b)
                if v:
                    blocks.append({"t": t, "v": v[:a.short]})
        # legacy message-level reasoning fields (some shapes keep them here)
        for k in MSG_THINK_KEYS:
            v = m.get(k)
            if isinstance(v, str) and v:
                reason_lines.append(f"### msg#{i} {role} model={m.get('model','?')} "
                                    f"[{k}/msg-level]\n{v[:a.full]}\n")
        e["blocks"] = blocks
        distilled.append(e)

    suba = bundle.get("subagents") or {}
    sub_slim = suba
    if isinstance(suba, (list, dict)):
        items = suba if isinstance(suba, list) else list(suba.values())
        sub_slim = []
        for s in items[:40]:
            if isinstance(s, dict):
                sub_slim.append({k: (str(v)[:300] if isinstance(v, (str,)) else v)
                                 for k, v in s.items() if k != "content"})
    out = {"summary": {"roles": dict(roles), "models": dict(models),
                       "chat_models": chat.get("models") or [],
                       "block_types": dict(btypes), "usage": usage,
                       "subagent_count": len(suba) if hasattr(suba, "__len__") else 0},
           "distilled": distilled, "subagents": sub_slim}
    jtxt = json.dumps(out, ensure_ascii=False)
    with open(base + ".diet.json", "w", encoding="utf-8") as f:
        f.write(jtxt)
    with open(base + ".reasoning.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(reason_lines))
    print(json.dumps(out["summary"], ensure_ascii=False, indent=2))
    print(f"[out] {base}.diet.json ({len(jtxt)} B), {base}.reasoning.txt "
          f"({sum(len(x) for x in reason_lines)} B)")
    if len(jtxt) > 300_000:
        print("[hint] still large — rerun with --short 120 --full 3000")
    return 0

if __name__ == "__main__":
    sys.exit(main())
