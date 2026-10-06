#!/usr/bin/env python3
"""Give a packaged build a different product name from the Chrome one.

A store listing's name and the name the app shows its own user have to agree —
one of them saying "Quotex AI Hunter Robot" while the other says "Quotex AI Bot"
is the kind of split nobody notices until a customer asks which product they
bought. So this rewrites both, in the copy that is about to be packaged:

  manifest.json   name, action.default_title
  config.js       APP_NAME, APP_NAME_HTML

The HTML form is derived rather than asked for: every name in this family bolds
the "AI" (Quotex OTC <b>AI</b> Bot), so the plain name is enough to produce it.

The rename lives in the packaging step, never in the Chrome source, so the two
builds stay one codebase differing by two generated lines instead of a forked
config somebody has to remember to keep in step.

Usage: rename-product.py <build-dir> "<New Product Name>"
"""
import json
import re
import sys


def html_form(name):
    """Bold the AI in a product name, matching the family's own style."""
    if re.search(r"\bAI\b", name):
        return re.sub(r"\bAI\b", "<b>AI</b>", name, count=1)
    return name


def rename(build_dir, new_name):
    mpath = build_dir + "/manifest.json"
    m = json.load(open(mpath, encoding="utf-8"))
    old = m.get("name")
    m["name"] = new_name
    if isinstance(m.get("action"), dict) and "default_title" in m["action"]:
        m["action"]["default_title"] = new_name
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    cpath = build_dir + "/config.js"
    src = open(cpath, encoding="utf-8").read()
    before = src
    src = re.sub(r'(APP_NAME:\s*")[^"]*(")', lambda mo: mo.group(1) + new_name + mo.group(2), src, count=1)
    src = re.sub(r'(APP_NAME_HTML:\s*")[^"]*(")',
                 lambda mo: mo.group(1) + html_form(new_name) + mo.group(2), src, count=1)
    if src == before:
        sys.exit("config.js has no APP_NAME to rename: " + cpath)
    open(cpath, "w", encoding="utf-8").write(src)
    return old, new_name, html_form(new_name)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    old, new, html = rename(sys.argv[1], sys.argv[2])
    print('renamed "%s" -> "%s"  (in-app: %s)' % (old, new, html))
