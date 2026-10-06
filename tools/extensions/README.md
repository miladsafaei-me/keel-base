# Browser-extension build tools, shared by every site

Every site that ships browser extensions keeps them in its own repo,
`~/products/<site>-extensions`. These scripts build, check and inventory those
extensions for Chrome, Firefox and Edge. They hold no brand: each repo's
`brand.json` supplies its brand name, its own hosts, its Firefox id domain, its
logo file, its product families, its required partner links and the other
brands' names that must never reach its users. So two sites build their
extensions the same way, and neither build carries a trace of the other.

The process that uses these tools, and the rules every binary signal app
extension follows, is keel-kit's `methodology/signal-extension-standard.md`,
run by the `keel-kit:signal-extension` skill.

## How a repo uses them

A repo's `tools/` folder holds relative symlinks to the files here, plus any
script that is the repo's own (SignalBots keeps its `strip-autotrade.py` there,
named in `brand.json` `transforms.signal_only`). Commands stay the same in every
repo:

```bash
tools/build-chrome.sh <slug>      # package the canonical Chrome build
tools/build-firefox.sh <slug>     # derive, verify and package Firefox
tools/build-edge.sh <slug>        # derive, verify and package Edge
tools/check-brand.py --all        # no other brand's trace anywhere
tools/check-store-policy.py --report
tools/audit-builds.py             # ports in sync with Chrome
tools/inventory.py --write        # regenerate VERSIONS.md
tools/newest-member.py <family>   # the model for the next member
```

A tool finds its repo from `$EXT_ROOT`, else from the `tools/` folder it was
invoked through, else from the nearest `brand.json` above the current folder.

Setting up a new repo: create `brand.json` (fields in `brand.py`),
`store-listings.json` (may be `{}`), `docs/store-policy.md`, the family folders,
`tools/` with the symlinks, and `.githooks/pre-commit`; then run
`git config core.hooksPath .githooks`. `~/products/autotradingbots-extensions`
is the smallest complete example.

## What each file does

| File | Job |
|---|---|
| `brand.py` | Finds the repo and loads its `brand.json` |
| `layout.py` | `<family>/<slug>/<browser>/` and the package name |
| `build-chrome.sh`, `build-firefox.sh`, `build-edge.sh` | Package, derive the ports byte for byte, run every gate, prune, rewrite `VERSIONS.md` |
| `manifest-files.py`, `verify-package.py` | The shipped file list read off the manifest, and the zip proven against it |
| `check-store-policy.py` | The affiliate-disclosure gate the Chrome Web Store enforces |
| `check-brand.py` | Fails on any `brand.json` `forbidden_traces` string in a build or listing |
| `check-listings.py`, `listing.py`, `rename-product.py` | Per-store names and Firefox ids from `store-listings.json` |
| `audit-builds.py` | Ports that have fallen behind their Chrome source |
| `inventory.py` | One build per folder, `VERSIONS.md`, the version guard |
| `newest-member.py` | The family's most recently built member, the model for the next |
| `smoke-popup.py` | Runs a popup in headless Chromium against a stubbed `chrome` API |
| `firefox-shim.js` | Copied into every Firefox build |
