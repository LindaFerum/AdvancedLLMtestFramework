#!/home/z/.venv/bin/python3
# -*- coding: utf-8 -*-
"""
cleankitty.py — remove our recon artifacts from the sandbox after exfil.

Removes ONLY our exact known names and patterns:
  [1] /home/z/my-project/download/            — v1.4 artifacts + project-summary tarballs
  [2] /home/z/my-project/scripts/download/   — legacy zpf_* artifacts (v1.0 misplacement)
  [3] /home/z/my-project/links/etc-config    — our guard-bypass symlink leaf (+ empty links dir)
  [4] --scripts: cutekitty.py / cleankitty.py — the tools themselves (self-deletes last)

Nothing else is touched. --dry-run previews. Stdlib only.
"""

import argparse, glob, os, shutil

PROJ   = "/home/z/my-project"
DL     = os.path.join(PROJ, "download")
LEGACY = os.path.join(PROJ, "scripts", "download")

ARTIFACTS  = ["summary_notes.txt", "service_config.json", "service_api.json",
              "mcp_init.txt", "mcp_tools.txt", "mcp_resources.txt",
              "mcp_res_templates.txt", "mcp_prompts.txt", "models_list.json",
              "cli_persona.json", "share_tree.json"]
TARBALLS   = ["project-summary_*.tar.gz", "zpf_bundle_*.tar.gz", "zpf_early.tgz"]
LEGACY_GLOB = ["zpf_*"]                       # sitting-1 prefix, incl. zpf_report.txt
SCRIPTS    = ["cutekitty.py", "cleankitty.py"]

def rm(path, dry, freed, n):
    if not os.path.lexists(path):
        return
    try:
        sz = os.path.getsize(path) if os.path.isfile(path) else 0
        print("  del  %-70s %8d B" % (path, sz))
        if not dry:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        freed[0] += sz
        n[0] += 1
    except Exception as e:
        print("  WARN %-70s %s" % (path, e))

def sweep(dirpath, names, patterns, dry, freed, n):
    if not os.path.isdir(dirpath):
        print("  (no such dir: %s)" % dirpath)
        return
    for name in names:
        rm(os.path.join(dirpath, name), dry, freed, n)
    for pat in patterns:
        for p in sorted(glob.glob(os.path.join(dirpath, pat))):
            rm(p, dry, freed, n)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="show what would be deleted")
    ap.add_argument("--scripts", action="store_true",
                    help="also remove cutekitty.py/cleankitty.py (self-delete included)")
    args = ap.parse_args()
    dry, freed, n = args.dry_run, [0], [0]
    print("== cleankitty%s ==" % ("  [DRY-RUN]" if dry else ""))

    print("[1/4] download/ — v1.4 artifacts + tarballs")
    sweep(DL, ARTIFACTS, TARBALLS, dry, freed, n)

    print("[2/4] scripts/download/ — legacy zpf_* artifacts")
    sweep(LEGACY, [], LEGACY_GLOB, dry, freed, n)
    if os.path.isdir(LEGACY) and not os.listdir(LEGACY) and not dry:
        try: os.rmdir(LEGACY); print("  rmdir %s (now empty)" % LEGACY)
        except Exception: pass

    print("[3/4] links/etc-config — our symlink leaf")
    leaf = os.path.join(PROJ, "links", "etc-config")
    rm(leaf, dry, freed, n)
    ldir = os.path.join(PROJ, "links")
    if os.path.isdir(ldir) and not os.listdir(ldir):
        rm(ldir, dry, freed, n)
    elif not os.path.isdir(ldir):
        print("  (no links dir)")

    print("[4/4] tool scripts")
    if args.scripts:
        for base in (PROJ, os.path.join(PROJ, "scripts")):
            for s in SCRIPTS:
                p = os.path.join(base, s)
                if os.path.lexists(p):
                    rm(p, dry, freed, n)      # cleankitty.py self-delete is safe mid-run
    else:
        print("  (skipped — pass --scripts to also remove cutekitty.py/cleankitty.py)")

    print("== %s%d file(s), %d bytes%s ==" %
          ("would remove " if dry else "removed ", n[0], freed[0],
           " (dry-run)" if dry else ""))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
