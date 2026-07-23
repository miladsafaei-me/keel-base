"""SiteProfile — a single structured-facts row every Keel fork owns.

This is a *placeholder* the base ships so a fresh fork has one obvious home for the
site's identity (brand, domain, theme signal) and its capability wiring. Capability
packages read from it (e.g. keel-ui's theme signal name, keel-seo's canonical host)
instead of hard-coding a project's values. BOOTSTRAP.md seeds row pk=1 on fork.

Namespacing discipline (see CLAUDE.md): explicit ``keel_base_core_*`` db_table so the
base coexists with a host's own apps and with third-party apps without collision.
Never rename a released label or db_table — additive changes only.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from . import capabilities


class SiteProfile(models.Model):
    """Singleton (pk=1). Structured facts rendered from keel-capabilities.yml."""

    brand_name = models.CharField(max_length=120, default="Keel Site")
    brand_tagline = models.CharField(max_length=255, blank=True, default="")
    # Canonical public host without scheme, e.g. "example.com". Consumed by
    # keel-seo (canonical URLs / sitemap host) and the deploy smoke tests.
    primary_domain = models.CharField(max_length=255, blank=True, default="")
    # The HTML data-attribute a fork uses to signal light/dark, e.g.
    # "data-keel-theme". keel-ui reads this rather than assuming one.
    theme_signal = models.CharField(max_length=64, default="data-keel-theme")
    # Capability ids (from keel-capabilities.yml) this site intends to run. Enabled
    # here + installed as a package = active. Enforced by clean() below.
    enabled_capabilities = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "keel_base_core_siteprofile"
        verbose_name = "Site profile"
        verbose_name_plural = "Site profile"

    def __str__(self) -> str:
        return self.brand_name

    def save(self, *args, **kwargs):
        # Enforce the singleton: there is exactly one site profile per project.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "SiteProfile":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def enabled_but_not_installed(self) -> list[str]:
        """Capabilities enabled here whose package is not importable.

        This is the installed-vs-enabled guard: enabling a capability without pip-
        installing its package (and redeploying) is a misconfiguration.
        """
        return [
            cid
            for cid in (self.enabled_capabilities or [])
            if not capabilities.is_installed(cid)
        ]

    def clean(self):
        unknown = set(self.enabled_capabilities or []) - set(capabilities.catalog_ids())
        # An empty catalog means keel-capabilities.yml was not found; skip the
        # unknown-id check rather than reject every value.
        if capabilities.catalog_ids() and unknown:
            raise ValidationError(
                {"enabled_capabilities": f"Unknown capability id(s): {sorted(unknown)}"}
            )
