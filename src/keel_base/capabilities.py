"""Capability registry loader.

``keel-capabilities.yml`` (at the repo root) is the single source of truth that
renders BOTH the BOOTSTRAP fork picker and the ``SiteProfile`` admin panel. This
module reads it and answers three questions the base needs without importing any
capability:

  * which capabilities exist (the catalog),
  * which are *installed* (their pip package is importable), and
  * which are *enabled* (declared on the SiteProfile / settings).

The core never imports a capability package — it only checks importability by name,
so a CMS-only fork never drags in signals code and vice versa.
"""

from __future__ import annotations

import importlib.util
import os
from functools import lru_cache
from pathlib import Path

# Maps a capability id (from keel-capabilities.yml) to the top-level module that
# proves its package is installed. Kept here rather than in the YAML so the check
# stays a pure importability probe with no package side effects.
_IMPORT_PROBE = {
    "ui": "keel_ui",
    "cms": "keel_cms",
    "content_pipeline": "keel_content",
    "seo": "keel_seo",
    "web": "keel_web",
}


def _registry_path() -> Path | None:
    """Locate keel-capabilities.yml: explicit env override, else search upward."""
    override = os.environ.get("KEEL_CAPABILITIES_FILE")
    if override:
        p = Path(override)
        return p if p.is_file() else None
    # Search from the working dir up to the filesystem root, then from the package
    # file up. In dev the package lives in the repo tree so ``here.parents`` reaches
    # the repo-root yml; once pip-installed (site-packages) ``here.parents`` no longer
    # reaches the app, so ``cwd``'s parents (e.g. /app/backend -> /app) must be walked
    # to find the yml the image copies to /app.
    here = Path(__file__).resolve()
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents, *here.parents]:
        candidate = parent / "keel-capabilities.yml"
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def load_registry() -> list[dict]:
    """Return the capability catalog as a list of dicts, or [] if unavailable."""
    path = _registry_path()
    if path is None:
        return []
    try:
        import yaml
    except ImportError:
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [c for c in (data or []) if isinstance(c, dict) and c.get("id")]


def is_installed(capability_id: str) -> bool:
    """True if the capability's pip package is importable in this environment."""
    module = _IMPORT_PROBE.get(capability_id)
    if not module:
        return False
    return importlib.util.find_spec(module) is not None


def catalog_ids() -> list[str]:
    return [c["id"] for c in load_registry()]


def installed_ids() -> list[str]:
    return [cid for cid in catalog_ids() if is_installed(cid)]


def _by_id() -> dict[str, dict]:
    return {c["id"]: c for c in load_registry()}


def resolve_requires(selected: list[str]) -> list[str]:
    """Expand ``selected`` capability ids to their transitive ``requires`` closure,
    returned in dependency-first install order (a required capability always
    precedes the one that needs it).

    So ``resolve_requires(["cms"])`` returns ``["ui", "seo", "cms"]`` — cms
    requires ui and seo, and both must be installed and wired before it. Unknown
    ids are dropped (they cannot be wired). A ``requires`` cycle is broken
    defensively rather than looping forever.
    """
    registry = _by_id()
    ordered: list[str] = []
    visiting: set[str] = set()

    def visit(cid: str) -> None:
        if cid in ordered or cid not in registry:
            return
        if cid in visiting:  # defensive: a requires cycle — stop descending
            return
        visiting.add(cid)
        for dep in registry[cid].get("requires") or []:
            visit(dep)
        visiting.discard(cid)
        if cid not in ordered:
            ordered.append(cid)

    for cid in selected:
        visit(cid)
    return ordered


def wiring_for(selected: list[str]) -> dict:
    """Compute the concrete fork wiring for ``selected`` (and their transitive
    requires): the pip pins, INSTALLED_APPS additions, context processors, and
    KEEL_* settings stubs, in dependency-first order.

    Returned dict keys:
      * ``capabilities``       ordered capability ids (the resolved closure)
      * ``packages``           pip package names to pin in requirements.txt
      * ``installed_apps``     Django app labels to append to INSTALLED_APPS
      * ``context_processors`` template context processors to append
      * ``settings_stubs``     list of {id, stub} settings blocks
      * ``contracts``          the union of host-supplied contracts to fulfil
      * ``admin_os``           True if the closure includes an admin-os capability
                               (cms) whose staff panel is the fork's only admin surface
      * ``collectstatic_ignore``  a collectstatic ``--ignore`` glob the admin-os
                               capability needs (keel-web's tailwind source dir), or None

    A capability may carry an ``admin_os`` block in the registry (cms does): it
    "pulls" extra capabilities appended AFTER it (so its own template shadows win
    resolution), contributes admin-os apps + a settings stub, and flips ``admin_os``
    so the generator writes the admin-os URLconf / compose mounts / entrypoint.

    The generator turns this into the actual settings.py / requirements.txt edits;
    keeping the computation here keeps the registry the single source of truth.
    """
    registry = _by_id()
    ordered = resolve_requires(selected)
    packages: list[str] = []
    apps: list[str] = []
    context_processors: list[str] = []
    settings_stubs: list[dict] = []
    contracts: list[str] = []
    for cid in ordered:
        cap = registry[cid]
        if cap.get("package"):
            packages.append(cap["package"])
        if cap.get("app"):
            apps.append(cap["app"])
        for cp in cap.get("context_processors") or []:
            if cp not in context_processors:
                context_processors.append(cp)
        if cap.get("settings_stub"):
            settings_stubs.append({"id": cid, "stub": cap["settings_stub"].rstrip("\n")})
        for contract in cap.get("contracts") or []:
            if contract not in contracts:
                contracts.append(contract)

    # Admin-os composition (cms): a fork with an admin-os capability is authored
    # through that capability's staff panel. It pulls extra capabilities (keel-web)
    # for pins, appends their apps AFTER the admin-os capability's own app (so its
    # template shadows win), and appends an admin-os settings stub. Guarded so a
    # non-admin-os fork is untouched.
    admin_os = False
    collectstatic_ignore = None
    for cid in list(ordered):
        ao = registry[cid].get("admin_os")
        if not ao:
            continue
        admin_os = True
        for pulled in ao.get("pulls") or []:
            if pulled in registry and pulled not in ordered:
                ordered.append(pulled)
                pkg = registry[pulled].get("package")
                if pkg and pkg not in packages:
                    packages.append(pkg)
        for a in ao.get("apps") or []:
            if a not in apps:
                apps.append(a)
        if ao.get("settings_stub"):
            settings_stubs.append(
                {"id": f"{cid}_admin_os", "stub": ao["settings_stub"].rstrip("\n")}
            )
        if ao.get("collectstatic_ignore"):
            collectstatic_ignore = ao["collectstatic_ignore"]

    return {
        "capabilities": ordered,
        "packages": packages,
        "installed_apps": apps,
        "context_processors": context_processors,
        "settings_stubs": settings_stubs,
        "contracts": contracts,
        "admin_os": admin_os,
        "collectstatic_ignore": collectstatic_ignore,
    }
