#!/home/z/.venv/bin/python3
"""sharegentle.py — fetch a fully content-complete shared chat from chat.z.ai.

Chain (all first-party endpoints used by the share page itself):
  1. GET  /api/v1/auths/                          -> anonymous guest session (Bearer JWT)
  2. GET  /api/v1/chats/share/{shareId}           -> chat metadata + message TREE (contents empty)
  3. POST /api/v1/chats/{shareId}/messages/batch  -> full message contents (content_blocks)
     NOTE: {shareId} in the path, NOT the inner chat id.
  4. GET  /api/v1/chats/subagents?chat_id={chatId}-> subagent task records (inner CHAT id)

Output: single JSON bundle {share, messages_flat, batch, subagents} +
console summary (model ids, content-block types, usage).

v1.1 vs v1.0: iterative cycle-safe tree walk (no recursion limit,
skips children missing from a pruned tree); retry w/ backoff on
connection errors + 5xx, 4xx fails fast; default output file (no silent
no-write); summary block (models, block-type histogram, reasoning-field
count, token usage).

Run: /home/z/.venv/bin/python3 sharegentle.py <shareId> [out.json]
"""
import json
import sys
import time
from collections import Counter

import requests

BASE = "https://chat.z.ai"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")
RETRIES, BACKOFF_S = 3, 2.0


def _attempt(func, url, **kw):
    """Request with retry on connection errors and 5xx; 4xx raises fast."""
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = func(url, timeout=30, **kw)
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code >= 500:
                last = e
            else:
                raise
        if attempt < RETRIES:
            time.sleep(BACKOFF_S * attempt)
    raise last


def get(session, url, token=None, **kw):
    headers = {"Accept": "application/json", "User-Agent": UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _attempt(session.get, url, headers=headers, **kw).json()


def post_json(session, url, token, payload):
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "User-Agent": UA, "Authorization": f"Bearer {token}"}
    return _attempt(session.post, url, headers=headers,
                   data=json.dumps(payload)).json()


def flatten_tree(messages, root_id=None):
    """Iterative preorder DFS; children chronological; cycle-safe; skips
    ids missing from the tree (pruned/deleted messages)."""
    if root_id is not None:
        roots = [messages[root_id]] if root_id in messages else []
    else:
        roots = sorted((m for m in messages.values() if not m.get("parentId")),
                       key=lambda m: m.get("timestamp") or 0)
    flat, seen = [], set()
    stack = [r["id"] for r in reversed(roots) if r and r.get("id")]
    while stack:
        mid = stack.pop()
        if mid in seen or mid not in messages:
            continue
        seen.add(mid)
        m = messages[mid]
        flat.append(m)
        kids = [c for c in (m.get("childrenIds") or []) if c in messages and c not in seen]
        kids.sort(key=lambda c: (messages[c].get("timestamp") or 0, c))
        stack.extend(reversed(kids))
    return flat


def fetch_shared_chat(share_id, out_path=None, verbose=True):
    s = requests.Session()

    auth = get(s, f"{BASE}/api/v1/auths/")
    token = auth["token"]
    if verbose:
        print(f"[auth] role={auth.get('role')} id={auth.get('id')}")

    share = get(s, f"{BASE}/api/v1/chats/share/{share_id}", token=token)
    chat = share.get("chat") or {}
    chat_id = chat.get("id")
    tree = (chat.get("history") or {}).get("messages") or {}
    if verbose:
        print(f"[share] title={share.get('title')!r} chat_id={chat_id} "
              f"messages={len(tree)}")
    if not tree:
        print("[warn] empty message tree — check the share id / share settings")

    ids = list(tree.keys())
    batch = post_json(s, f"{BASE}/api/v1/chats/{share_id}/messages/batch",
                      token, {"ids": ids})
    data = batch.get("data", {})
    if verbose:
        with_content = sum(1 for m in data.values()
                           if (m.get("content_blocks") or m.get("content")))
        print(f"[batch] returned={len(data)} with_content={with_content}")

    try:
        subagents = get(s, f"{BASE}/api/v1/chats/subagents", token=token,
                        params={"chat_id": chat_id})
    except requests.HTTPError as e:
        if verbose:
            print(f"[subagents] unavailable: {e}")
        subagents = {}

    flat = flatten_tree(tree)
    for m in flat:
        full = data.get(m["id"], {})
        m["content_blocks"] = full.get("content_blocks") or []
        m["content"] = full.get("content") or m.get("content") or ""
        m["files"] = full.get("files") or []
        m["usage"] = full.get("usage")

    bundle = {"share": share, "messages_flat": flat,
              "batch": batch, "subagents": subagents}

    # ---- summary: the actually-interesting bits ----
    roles = Counter(m.get("role", "?") for m in flat)
    models = Counter(m.get("model") for m in flat
                     if m.get("role") == "assistant" and m.get("model"))
    chat_models = {x for x in (chat.get("models") or []) if isinstance(x, str)}
    bt, usage = Counter(), {"prompt": 0, "completion": 0, "n": 0}
    reasoning_msgs = 0
    for m in flat:
        if m.get("reasoning") or m.get("thinking") or m.get("reasoning_content"):
            reasoning_msgs += 1
        for b in m.get("content_blocks") or []:
            if isinstance(b, dict):
                bt[str(b.get("type", "?"))] += 1
        u = m.get("usage") or {}
        p = u.get("prompt_tokens") or u.get("prompt_token_count")
        c = u.get("completion_tokens") or u.get("completion_token_count")
        if p:
            usage["prompt"] += p
        if c:
            usage["completion"] += c
        if u:
            usage["n"] += 1
    print(f"[summary] roles={dict(roles)}")
    print(f"[summary] assistant models={dict(models)} chat.models={sorted(chat_models) or '-'}")
    print(f"[summary] content-block types={dict(bt)}")
    print(f"[summary] msgs w/ reasoning fields={reasoning_msgs} usage="
          f"{usage}")

    if out_path:
        with open(out_path, "w") as f:
            json.dump(bundle, f, ensure_ascii=False)
        if verbose:
            print(f"[out] wrote {out_path} ({'ok'})")
    return bundle


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: /home/z/.venv/bin/python3 sharegentle.py <shareId> [out.json]")
        sys.exit(1)
    sid = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else f"share_{sid}.json"
    t0 = time.time()
    fetch_shared_chat(sid, out)
    print(f"[done] elapsed {time.time()-t0:.2f}s")
