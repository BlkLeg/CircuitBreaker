"""Integration plugin registry."""

from __future__ import annotations

from app.integrations.base import IntegrationPlugin
from app.integrations.native_probe import NativeProbePlugin
from app.integrations.uptime_kuma import UptimeKumaPlugin

INTEGRATION_REGISTRY: dict[str, type[IntegrationPlugin]] = {
    UptimeKumaPlugin.TYPE: UptimeKumaPlugin,
    NativeProbePlugin.TYPE: NativeProbePlugin,
}


def get_plugin(integration_type: str) -> type[IntegrationPlugin] | None:
    """Return the plugin class for a given type string, or None if unknown."""
    return INTEGRATION_REGISTRY.get(integration_type)


def list_registry() -> list[dict]:
    """Return plugin metadata + CONFIG_FIELDS for the frontend form renderer."""
    return [
        {
            "type": cls.TYPE,
            "display_name": cls.DISPLAY_NAME,
            "config_fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "type": f.type,
                    "required": f.required,
                    "secret": f.secret,
                    "placeholder": f.placeholder,
                }
                for f in cls.CONFIG_FIELDS
            ],
        }
        for cls in INTEGRATION_REGISTRY.values()
    ]
