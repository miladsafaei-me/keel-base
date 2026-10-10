#!/usr/bin/env python3
"""Refuse a package that would break the stores' affiliate-disclosure policy.

On 2026-09-21 the Chrome Web Store rejected five of our extensions (Quotex AI
Hunter Robot, Chinese Bot Pro Max, IQ OTC AI Bot, Olymp OTC AI Bot,
PocketOption OTC AI Bot) under violation "Grey Titanium": the extension uses an
affiliate program and neither its store description nor its interface said so.
Every one of them carries a "Register" button that opens our broker IB link,
and nothing anywhere told the user that the link pays us. The full rule and the
copy to use are in docs/store-policy.md; this script is the part of it a build
cannot skip.

What it checks, for one build folder or package:

  partner links   Any http(s) URL in a shipped .js/.html file whose host is not
                  ours (brand.json own_hosts), a support messenger, a store, or
                  an XML namespace. Every broker, exchange and prop-firm URL counts,
                  tracked or not: in these builds each one is an IB or
                  affiliate link.

  If the build has partner links:
    1. the interface discloses them where they are used: an element marked
       data-affiliate-disclosure="link" whose text says the link may earn
       the brand (brand.json "brand") a commission;
    2. the interface discloses them on the first screen a new user sees,
       before any link is tapped: data-affiliate-disclosure="first-run", same
       wording rule;
    3. every partner button is marked data-affiliate-link, so the two can be
       found together;
    4. no background or content script holds a partner URL, reads the
       affiliate config, or opens an external URL by itself - a partner link
       opens only when the user taps it;
    5. the store listing text (<family>/<slug>/store-listing.md, or
       store-listing.en.md inside <slug>-store-listings.zip) opens its
       Description with an "Affiliate disclosure" paragraph that mentions the
       commission, inside the first 800 characters.

    6. nothing still claims there are none: no data-affiliate-disclosure="none"
       line in the interface, no "no affiliate" wording in the listing. A build
       that gains a partner link keeps its old promise otherwise.

  For a family with a required partner link (brand.json family_links):
    7. the popup's config carries that exact link.

  If it has none:
    5'. the store listing still exists and its Description carries an
        "Affiliate disclosure" line saying the extension has no affiliate
        links, so a reviewer who follows our website link does not read the
        partner brokers on it as the extension's own program. The interface
        may say the same with data-affiliate-disclosure="none"; it need not.

Exits non-zero on any failure, so the build scripts stop before zipping.

Usage:
  check-store-policy.py <build-folder-or-package.zip> [...]
  check-store-policy.py --staged      every build whose version, or whose product's
                                      store-listing.md, is staged for commit (the
                                      pre-commit hook; packages are gitignored, so
                                      a new version is what a commit can show)
  check-store-policy.py --report      every build on disk, one line each; exits 0
"""
import json
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import layout  # noqa: E402
import brand  # noqa: E402

ROOT = brand.ROOT

# Hosts that are never a partner: ours (brand.json own_hosts), the support
# messengers, the stores the extensions are listed on, XML namespace URIs inside
# inline SVG, the error-page links a Svelte bundle carries, and any the repo adds
# in brand.json neutral_hosts (a flag-image CDN). A host is added only when it is
# provably not a place a user is sent to sign up; a broker's plain homepage is
# still a partner link.
NEUTRAL = brand.OWN_HOSTS + (
    "t.me", "telegram.me", "wa.me", "whatsapp.com",
    "chromewebstore.google.com", "chrome.google.com", "addons.mozilla.org",
    "microsoftedge.microsoft.com", "w3.org", "xmlns.com", "svelte.dev",
) + brand.NEUTRAL_HOSTS
# The files a user looks at and taps in: the popup (or options page) and the
# config it reads its links from. Every other script runs without the user -
# the background worker, content scripts, socket engines, page taps, offscreen
# documents - and the broker hosts inside those are trading APIs, not links.
UI_FILE = re.compile(r"^(popup|options|sidepanel)[^/]*\.(js|html)$|^config\.js$")
URL = re.compile(r"""https?://([A-Za-z0-9.-]+\.[A-Za-z]{2,})""")
# The attribute value is a space-separated list of roles: "link", "first-run",
# or "none". One element may carry "link first-run" when the partner button and
# its disclosure already sit on the first screen a new user sees.
MARKER = re.compile(r"""data-affiliate-disclosure\s*=\s*\\?["']([a-z -]+)""")
# Partner links a whole family must carry, from brand.json family_links. Every
# binary signal app carries the site's Olymp Trade IB link, whichever broker is
# selected (Milad, 2026-09-26); each site declares its own tracked URL.
FAMILY_LINKS = brand.FAMILY_LINKS
COMMISSION = re.compile(r"commission", re.I)
# A background or content script that opens a web page by itself.
SELF_OPEN = re.compile(r"""(tabs\.create|tabs\.update|windows\.create|setUninstallURL)\s*\(\s*\{?[^)]{0,200}?["'`]https?://""")
LISTING_HEAD = 800


def neutral(host):
    host = host.lower()
    return any(host == n or host.endswith("." + n) for n in NEUTRAL)


def read_build(path):
    """{relative name: text} of every shipped .js/.html, and the manifest."""
    files = {}
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith((".js", ".html", ".json")) and not name.startswith("tests/"):
                    files[name] = zf.read(name).decode("utf-8", "replace")
    else:
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if d != "tests"]
            for f in filenames:
                if f.endswith((".js", ".html", ".json")):
                    full = os.path.join(dirpath, f)
                    files[os.path.relpath(full, path)] = open(full, encoding="utf-8", errors="replace").read()
    manifest = json.loads(files.pop("manifest.json", "{}") or "{}")
    return manifest, files


def locate(path):
    """(family, slug, browser) from <family>/<slug>/<browser>[/package.zip]."""
    folder = os.path.dirname(path) if path.endswith(".zip") else path
    parts = os.path.relpath(os.path.abspath(folder), ROOT).split(os.sep)
    if len(parts) == 3 and parts[0] in layout.FAMILIES and parts[2] in layout.BROWSERS:
        return tuple(parts)
    return None, None, None


def ui_files(files):
    return {n: t for n, t in files.items() if UI_FILE.match(os.path.basename(n))}


def unattended_scripts(files):
    """Scripts that run without the user. config.js is data the worker imports
    and may hold the partner URLs, since the popup reads them from it; what must
    never hold one is code that runs on its own."""
    return [n for n in files if n.endswith(".js") and not UI_FILE.match(os.path.basename(n))
            and os.path.basename(n) != "firefox-shim.js"]


def description(listing_text):
    m = re.search(r"^## Description\s*\n(.*?)(?=^## |\Z)", listing_text, re.S | re.M)
    return m.group(1).strip() if m else None


def roles(files):
    """Every (roles, text, end) of a disclosure marker in the shipped files."""
    for text in files.values():
        for m in MARKER.finditer(text):
            yield m.group(1).split(), text, m.end()


def marker_ok(files, role):
    """A marker of this role exists and the words near it mention the commission."""
    return any(role in r and COMMISSION.search(t[e:e + 600]) for r, t, e in roles(files))


def check(path):
    problems = []
    family, slug, browser = locate(path)
    if not slug:
        return ["%s is not <family>/<slug>/<browser>/ (see layout.py)" % path], False
    _manifest, files = read_build(path)

    partners = {}
    for name, text in ui_files(files).items():
        for host in URL.findall(text):
            if not neutral(host):
                partners.setdefault(host.lower(), set()).add(name)
    has_partners = bool(partners)

    listing = layout.listing_text(os.path.join(ROOT, family, slug))
    desc = None
    if listing is None:
        problems.append("no store listing text: %s/%s/store-listing.md or store-listing.en.md in "
                        "%s-store-listings.zip (template in docs/store-policy.md)" % (family, slug, slug))
    else:
        desc = description(listing)
        if not desc:
            problems.append("store-listing.md has no '## Description' section")

    if has_partners:
        if not marker_ok(files, "link"):
            problems.append('partner links, but no data-affiliate-disclosure="link" next to them '
                            'saying %s may earn a commission' % brand.BRAND)
        if not marker_ok(files, "first-run"):
            problems.append('partner links, but no data-affiliate-disclosure="first-run" on the '
                            'first screen, before any link is tapped')
        if any("none" in r for r, _t, _e in roles(files)):
            problems.append('partner links, but the interface still says there are none '
                            '(data-affiliate-disclosure="none")')
        if not any("data-affiliate-link" in t for t in files.values()):
            problems.append("partner links, but no button is marked data-affiliate-link")
        for name in unattended_scripts(files):
            text = files[name]
            leaked = sorted(h for h in partners if h in text)
            if leaked:
                problems.append("%s runs without the user and holds partner URLs: %s" % (name, ", ".join(leaked)))
            if re.search(r"\bAFFILIATE", text):
                problems.append("%s runs without the user and reads the affiliate config" % name)
            if SELF_OPEN.search(text):
                problems.append("%s opens an external web page by itself" % name)
        if desc is not None:
            head = desc[:LISTING_HEAD]
            i = head.find("Affiliate disclosure")
            if i < 0 or not COMMISSION.search(desc[i:i + 700]):
                problems.append("store-listing.md: the Description must open (first %d characters) with an "
                                "'Affiliate disclosure' paragraph that mentions the commission" % LISTING_HEAD)
            if re.search(r"no affiliate", desc, re.I):
                problems.append("store-listing.md says the extension has no affiliate links, but it has")
    elif desc is not None:
        i = desc.find("Affiliate disclosure")
        if i < 0 or not re.search(r"no affiliate", desc[i:i + 400], re.I):
            problems.append("store-listing.md: the Description needs an 'Affiliate disclosure' line "
                            "saying the extension has no affiliate links")

    if family in FAMILY_LINKS:
        name, url = FAMILY_LINKS[family]
        if not any(url in t for t in ui_files(files).values()):
            problems.append("every %s build carries our %s partner link (%s); this one does not"
                            % (family, name, url))

    return problems, sorted(partners)


def _git(*args):
    r = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _version(blob):
    try:
        return json.loads(blob).get("version")
    except ValueError:
        return None


def staged_builds():
    """Build folders a commit ships a new version of, or re-lists."""
    out = set()
    for p in _git("diff", "--cached", "--name-only", "--diff-filter=AM").split():
        parts = p.split("/")
        if len(parts) == 4 and parts[0] in layout.FAMILIES and parts[2] in layout.BROWSERS \
                and parts[3] == "manifest.json":
            if _version(_git("show", ":" + p)) != _version(_git("show", "HEAD:" + p)):
                out.add(os.path.join(ROOT, *parts[:3]))
        elif len(parts) == 3 and parts[0] in layout.FAMILIES and parts[2] in (
                "store-listing.md", parts[1] + "-store-listings.zip"):
            for browser in layout.BROWSERS:
                d = os.path.join(ROOT, parts[0], parts[1], browser)
                if os.path.isfile(os.path.join(d, "manifest.json")):
                    out.add(d)
    return sorted(out)


def main(argv):
    if not argv:
        sys.exit(__doc__)
    if argv == ["--report"]:
        for family, slug in layout.products():
            for browser in layout.BROWSERS:
                d = layout.build_dir(slug, browser)
                if os.path.isfile(os.path.join(d, "manifest.json")):
                    problems, partners = check(d)
                    state = "ok" if not problems else "FAILS (%d)" % len(problems)
                    print("%-8s %-28s partner hosts=%-3d %s" % (browser, slug, len(partners), state))
        return 0
    targets = staged_builds() if argv == ["--staged"] else argv
    failed = False
    for t in targets:
        problems, partners = check(t)
        if problems:
            failed = True
            print("store policy: %s" % os.path.relpath(os.path.abspath(t), ROOT), file=sys.stderr)
            if partners:
                print("  partner links found: %s" % ", ".join(partners), file=sys.stderr)
            for p in problems:
                print("  - %s" % p, file=sys.stderr)
    if failed:
        print("see docs/store-policy.md", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
