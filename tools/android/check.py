#!/usr/bin/env python3
"""The gates every Android build passes. Run by tools/build.sh; runs on its own too.

  brand     no brand.json forbidden_traces string in anything a user reads: the bundled app, the store listing, the
            built APK's strings (trace_exceptions, the partner URL, are allowed)
  partner   the partner link carries its disclosure, next to it, and only opens on a tap
  site      the bundled app is in step with the site (sync-from-site.py --check)
  package   the APK and the AAB are signed with the upload key, target the SDK Google Play requires, carry the member's
            application id and version, ask only for INTERNET
  listing   store-listing.md has every field Google Play asks for, within its length limits, the disclosure first

Usage: check.py <slug> [--apk PATH --aab PATH]
"""
import argparse
import os
import re
import subprocess
import sys
import zipfile

import mobile

TARGET_SDK = 36
SDK = os.path.expanduser(os.environ.get("ANDROID_HOME", "~/Android/Sdk"))
LIMITS = {"App name": 30, "Short description": 80, "Full description": 4000}


def build_tool(name):
    tools = os.path.join(SDK, "build-tools")
    versions = sorted(os.listdir(tools), key=lambda v: [int(x) for x in re.findall(r"\d+", v)])
    return os.path.join(tools, versions[-1], name)


def traces(text, brand):
    for exc in brand.get("trace_exceptions", []):
        text = text.replace(exc, "")
    low = text.lower()
    return [t for t in brand.get("forbidden_traces", []) if t.lower() in low]


def check_brand(brand, mdir, apk):
    bad = []
    roots = [os.path.join(mdir, "android", "assets"), os.path.join(mobile.ROOT, "shell")]
    files = [os.path.join(d, n) for r in roots for d, _, ns in os.walk(r) for n in ns if n.endswith((".html", ".js", ".css", ".json", ".xml"))]
    files += [os.path.join(mdir, "store-listing.md")]
    for f in files:
        if os.path.isfile(f):
            hit = traces(open(f, encoding="utf-8", errors="replace").read(), brand)
            if hit:
                bad.append("%s names %s" % (os.path.relpath(f, mobile.ROOT), ", ".join(hit)))
    if apk:
        with zipfile.ZipFile(apk) as z:
            for name in z.namelist():
                hit = traces(name, brand)
                if hit:
                    bad.append("the APK holds a file named %s" % name)
        dump = subprocess.run([build_tool("aapt2"), "dump", "strings", apk], capture_output=True, text=True).stdout
        if traces(dump, brand):
            bad.append("the APK's string pool names %s" % ", ".join(traces(dump, brand)))
    return bad


def check_partner(mdir):
    page = open(os.path.join(mdir, "android", "assets", "index.html"), encoding="utf-8").read()
    shell = open(os.path.join(mobile.ROOT, "shell", "assets", "shell", "shell.js"), encoding="utf-8").read()
    bad = []
    if 'data-affiliate-disclosure' not in page:
        bad.append("the partner link has no disclosure in the page")
    if 'rel="sponsored nofollow noopener"' not in page:
        bad.append('the partner link is not rel="sponsored nofollow noopener"')
    if re.search(r"AFFILIATE_URL[^;\n]*(location|window\.open|native\.open)", shell):
        bad.append("shell.js opens the partner link without a tap")
    return bad


def check_site(slug):
    run = subprocess.run([sys.executable, os.path.join(mobile.ROOT, "tools", "sync-from-site.py"), slug, "--check"], capture_output=True, text=True)
    return [] if run.returncode == 0 else [run.stdout.strip() or run.stderr.strip()]


def check_package(m, apk, aab):
    bad = []
    badging = subprocess.run([build_tool("aapt2"), "dump", "badging", apk], capture_output=True, text=True).stdout
    pkg = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging)
    target = re.search(r"targetSdkVersion:'(\d+)'", badging)
    if not pkg or pkg.group(1) != m["application_id"]:
        bad.append("the APK's application id is not %s" % m["application_id"])
    if pkg and (int(pkg.group(2)) != m["version_code"] or pkg.group(3) != m["version_name"]):
        bad.append("the APK's version is %s (%s), member.json says %s (%s)" % (pkg.group(3), pkg.group(2), m["version_name"], m["version_code"]))
    if not target or int(target.group(1)) < TARGET_SDK:
        bad.append("the APK targets SDK %s; Google Play needs %d" % (target and target.group(1), TARGET_SDK))
    perms = re.findall(r"uses-permission: name='([^']+)'", badging)
    extra = [p for p in perms if p != "android.permission.INTERNET" and not p.endswith("DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION")]
    if extra:
        bad.append("the APK asks for %s" % ", ".join(extra))
    sign = subprocess.run([build_tool("apksigner"), "verify", "--print-certs", apk], capture_output=True, text=True)
    if sign.returncode != 0 or "CN=" not in sign.stdout:
        bad.append("the APK is not signed: %s" % (sign.stderr.strip() or sign.stdout.strip())[:200])
    elif "CN=Android Debug" in sign.stdout:
        bad.append("the APK is signed with the debug key, not the upload key")
    jar = subprocess.run(["jarsigner", "-verify", aab], capture_output=True, text=True)
    if "jar verified" not in jar.stdout:
        bad.append("the AAB is not signed")
    return bad


def listing_fields(text):
    """Each "## Field" heading of store-listing.md and the first code block under it."""
    fields = {}
    for head, body in re.findall(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.S | re.M):
        block = re.search(r"```\w*\n(.*?)\n```", body, re.S)
        fields[head.strip()] = block.group(1) if block else body.strip()
    return fields


def check_listing(mdir):
    path = os.path.join(mdir, "store-listing.md")
    if not os.path.isfile(path):
        return ["no store-listing.md"]
    fields = listing_fields(open(path, encoding="utf-8").read())
    bad = []
    for field, limit in LIMITS.items():
        body = fields.get(field, "")
        if not body:
            bad.append("store-listing.md has no %s" % field)
        elif len(body) > limit:
            bad.append("%s is %d characters; Google Play takes %d" % (field, len(body), limit))
    if "Affiliate disclosure" not in fields.get("Full description", "")[:900]:
        bad.append("the Full description does not open with its affiliate disclosure")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--apk")
    ap.add_argument("--aab")
    args = ap.parse_args()
    brand = mobile.brand()
    m, mdir = mobile.member(args.slug)
    results = {"brand": check_brand(brand, mdir, args.apk), "partner": check_partner(mdir), "site": check_site(args.slug),
               "listing": check_listing(mdir)}
    if args.apk and args.aab:
        results["package"] = check_package(m, args.apk, args.aab)
    failed = False
    for gate, problems in results.items():
        print("%-8s %s" % (gate, "ok" if not problems else "FAIL"))
        for p in problems:
            print("         " + p)
        failed |= bool(problems)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
