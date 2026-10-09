"""Built-in providers. Add a module here and list it in ``build_registry``."""

from __future__ import annotations

from fallcha_tools.core.provider import ProviderRegistry


def build_registry() -> ProviderRegistry:
    """The providers this deployment serves (none yet: see the README)."""
    return ProviderRegistry([])
