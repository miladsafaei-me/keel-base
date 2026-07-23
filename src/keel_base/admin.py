from django.contrib import admin

from .models import SiteProfile


@admin.register(SiteProfile)
class SiteProfileAdmin(admin.ModelAdmin):
    list_display = ("brand_name", "primary_domain", "theme_signal")
    readonly_fields = ("created_at", "updated_at", "_enabled_but_not_installed")

    fieldsets = (
        ("Identity", {"fields": ("brand_name", "brand_tagline", "primary_domain")}),
        ("Theme", {"fields": ("theme_signal",)}),
        (
            "Capabilities",
            {
                "fields": ("enabled_capabilities", "_enabled_but_not_installed"),
                "description": (
                    "Capability ids from keel-capabilities.yml. A capability is only "
                    "active when enabled here AND its package is installed + deployed."
                ),
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        # Singleton: only ever pk=1.
        return not SiteProfile.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Enabled but not installed")
    def _enabled_but_not_installed(self, obj):
        missing = obj.enabled_but_not_installed()
        return ", ".join(missing) if missing else "— (all enabled capabilities installed)"
