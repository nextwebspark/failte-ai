"""API for the node-spec catalog.

Exposes the registered NodeSpecs (one per node type) so frontend renderers
and the LLM SDK can build forms / typed constructors from a single source
of truth.

Endpoints:
    GET /node-types          → list every registered NodeSpec
    GET /node-types/{name}   → single NodeSpec by name
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.db.models import UserModel
from api.sdk_expose import sdk_expose
from api.services.auth.depends import get_user, requires
from api.services.auth.permissions import Permission
from api.services.configuration.ai_model_configuration import customer_keys_allowed
from api.services.workflow.node_specs import (
    SPEC_VERSION,
    NodeSpec,
    all_specs,
    get_spec,
)

router = APIRouter(prefix="/node-types")

# The QA node's own-LLM fields hold a provider and key; customers on platform
# models use the agent's model instead (and the runtime ignores them there).
_MODEL_PROVIDER_FIELDS = {
    "qa": frozenset(
        {"qa_use_workflow_llm", "qa_provider", "qa_model", "qa_api_key", "qa_endpoint"}
    ),
}


def _for_user(spec: NodeSpec, user: UserModel) -> NodeSpec:
    hidden = _MODEL_PROVIDER_FIELDS.get(spec.name)
    if not hidden or customer_keys_allowed(user):
        return spec
    return spec.model_copy(
        update={
            "properties": [p for p in spec.properties if p.name not in hidden],
        }
    )


class NodeTypesResponse(BaseModel):
    spec_version: str
    node_types: list[NodeSpec]


@router.get(
    "",
    response_model=NodeTypesResponse,
    **sdk_expose(
        method="list_node_types",
        description="List every registered node type with its spec. Pinned to spec_version.",
    ),
    dependencies=requires(Permission.AGENTS_READ),
)
async def list_node_types(
    user: UserModel = Depends(get_user),
) -> NodeTypesResponse:
    """List every registered NodeSpec.

    SDK clients should pin to `spec_version` and warn if the server reports
    a higher version than what they were generated against.
    """
    return NodeTypesResponse(
        spec_version=SPEC_VERSION,
        node_types=[_for_user(spec, user) for spec in all_specs()],
    )


@router.get(
    "/{name}",
    response_model=NodeSpec,
    **sdk_expose(
        method="get_node_type",
        description="Fetch a single node spec by name.",
    ),
    dependencies=requires(Permission.AGENTS_READ),
)
async def get_node_type(
    name: str,
    user: UserModel = Depends(get_user),
) -> NodeSpec:
    spec = get_spec(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown node type: {name!r}")
    return _for_user(spec, user)
