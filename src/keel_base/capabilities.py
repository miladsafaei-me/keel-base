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
    here = Path(__file__).resolve()
    for parent in [Path.cwd(), *here.parents]:
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
