"""Catalog integrations hosted by the Fallcha tools service (``tools/``).

Distinct from ``api.services.integrations``, the post-call plugin system.
"""

from api import constants
from api.errors.integrations import ToolsServiceNotConfiguredError
from api.services.tool_integrations.client import Caller, ToolsServiceClient
from api.services.tool_integrations.resources import DbIntegrationResources
from api.services.tool_integrations.service import Actor, IntegrationService


def get_integration_service() -> IntegrationService:
    """FastAPI dependency; 503 until the tools service is configured."""
    secret = constants.TOOLS_INTERNAL_SECRET
    base_url = constants.TOOLS_SERVICE_URL
    if not secret or not base_url:
        raise ToolsServiceNotConfiguredError()
    return IntegrationService(
        tools_service=ToolsServiceClient(base_url=base_url, internal_secret=secret),
        resources=DbIntegrationResources(),
        tools_base_url=base_url,
    )


__all__ = [
    "Actor",
    "Caller",
    "IntegrationService",
    "ToolsServiceClient",
    "get_integration_service",
]
