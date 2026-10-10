from __future__ import annotations

"""Utilities for masking API keys before they are sent to the client.

The rules are simple:
1. Only expose the last *visible* characters (default 4) of a key.
2. Incoming masked keys are considered a placeholder – if they equal the mask of
   the already-stored key, we treat them as *unchanged* and keep the real value
   in storage.
"""

import copy
from typing import Any, Dict, Optional

from api import constants
from api.schemas.ai_model_configuration import EffectiveAIModelConfiguration
from api.services.configuration.registry import ServiceConfig
from api.services.integrations import get_node_secret_fields

VISIBLE_CHARS = 4  # number of trailing characters to reveal
MASK_CHAR = "*"
MASK_MARKER = "***"  # substring that indicates a masked key
SERVICE_SECRET_FIELDS = (
    "api_key",
    "credentials",
    "aws_access_key",
    "aws_secret_key",
    "aws_session_token",
)
MODEL_OVERRIDE_FIELDS = ("llm", "tts", "stt", "realtime")
# Operator infrastructure behind platform-managed services. Customers choose
# models and voices; where and as whom they run is not theirs to see.
PLATFORM_HIDDEN_FIELDS = ("project_id", "location", "credentials")


def contains_masked_key(value: str | list[str] | None) -> bool:
    """Return True if *value* looks like a masked placeholder."""
    if value is None:
        return False
    keys = value if isinstance(value, list) else [value]
    return any(MASK_MARKER in k for k in keys)


def check_for_masked_keys(config: "EffectiveAIModelConfiguration") -> None:
    """Raise ValueError if any service in *config* still has a masked secret."""
    for field in ("llm", "tts", "stt", "embeddings", "realtime"):
        service = getattr(config, field, None)
        if service is None:
            continue
        for secret_field in SERVICE_SECRET_FIELDS:
            if not hasattr(service, secret_field):
                continue
            if secret_field == "api_key" and hasattr(service, "get_all_api_keys"):
                secret_value = service.get_all_api_keys()
            else:
                secret_value = getattr(service, secret_field, None)
            if contains_masked_key(secret_value):
                raise ValueError(
                    f"The {field} {secret_field} appears to be masked. "
                    "Please provide the actual value, not the masked value."
                )


def mask_key(real_key: str, visible: int = VISIBLE_CHARS) -> str:
    """Return a masked representation of *real_key*.

    Example:
        >>> mask_key("sk-1234567890abcdef")
        '****************cdef'
    """
    if real_key is None:
        return ""

    if visible <= 0 or visible >= len(real_key):
        # mask entire key or nothing to mask – edge-cases
        return MASK_CHAR * len(real_key)

    masked_part = MASK_CHAR * (len(real_key) - visible)
    return f"{masked_part}{real_key[-visible:]}"


def _mask_secret_value(value: str | list[str]) -> str | list[str]:
    if isinstance(value, list):
        return [mask_key(k) for k in value]
    return mask_key(value)


def is_mask_of(masked: str, real_key: str) -> bool:
    """Return *True* if *masked* equals the mask of *real_key* under the current rules."""
    return mask_key(real_key) == masked


def resolve_masked_api_keys(
    incoming: str | list[str], existing: str | list[str]
) -> str | list[str]:
    """Resolve masked API keys against existing real keys.

    For each incoming key, if it matches the mask of an existing key, the real
    key is restored.  New (unmasked) keys are kept as-is.  This handles adds,
    removes, reorders, and partial replacements correctly.
    """
    if isinstance(incoming, str) and isinstance(existing, str):
        return existing if is_mask_of(incoming, existing) else incoming

    existing_list = existing if isinstance(existing, list) else [existing]
    incoming_list = incoming if isinstance(incoming, list) else [incoming]

    resolved: list[str] = []
    used: set[int] = set()
    for key in incoming_list:
        matched = False
        for i, real in enumerate(existing_list):
            if i not in used and is_mask_of(key, real):
                resolved.append(real)
                used.add(i)
                matched = True
                break
        if not matched:
            resolved.append(key)
    return resolved


def secrets_hidden_for(user: Any) -> bool:
    """Whether responses to *user* must carry no secrets at all, not even masked.

    On a platform-models server customers never hold keys. Superusers still get
    masked values so their GET -> PUT round trips keep stored keys.
    """
    return constants.PLATFORM_MODELS_ENABLED and not getattr(
        user, "is_superuser", False
    )


def hide_secret(container: Dict[str, Any], key: str, *, drop: bool) -> None:
    """Mask a stored secret in an API response, or drop it entirely."""
    if drop:
        container.pop(key, None)
    else:
        container[key] = _mask_secret_value(container[key])


# ---------------------------------------------------------------------------
# High-level helpers for EffectiveAIModelConfiguration objects
# ---------------------------------------------------------------------------


def _mask_service(
    service_cfg: Optional[ServiceConfig], drop_secrets: bool = False
) -> Optional[Dict[str, Any]]:
    if service_cfg is None:
        return None

    # Work on a dict copy so we don't mutate original models
    data = service_cfg.model_dump()
    for secret_field in SERVICE_SECRET_FIELDS:
        if secret_field not in data or not data[secret_field]:
            continue
        hide_secret(data, secret_field, drop=drop_secrets)
    return data


def mask_user_config(
    config: EffectiveAIModelConfiguration, *, drop_secrets: bool = False
) -> Dict[str, Any]:
    """Return a JSON-serialisable dict of *config* with every api_key masked.

    Platform-managed services also lose their project, location and
    credentials entirely, since those belong to the operator.
    """

    def service(service_cfg: Optional[ServiceConfig]) -> Optional[Dict[str, Any]]:
        data = _mask_service(service_cfg, drop_secrets)
        if data is not None and config.platform_managed:
            for field in PLATFORM_HIDDEN_FIELDS:
                data.pop(field, None)
        return data

    return {
        "llm": service(config.llm),
        "tts": service(config.tts),
        "stt": service(config.stt),
        "embeddings": service(config.embeddings),
        "realtime": service(config.realtime),
        "is_realtime": config.is_realtime,
        "test_phone_number": config.test_phone_number,
        "timezone": config.timezone,
    }


def mask_workflow_configurations(
    config: Optional[Dict], *, drop_secrets: bool = False
) -> Optional[Dict]:
    """Mask secret fields inside workflow-level model overrides for API responses."""
    if not config:
        return config

    masked = copy.deepcopy(config)
    model_overrides = masked.get("model_overrides")
    if isinstance(model_overrides, dict):
        for section in MODEL_OVERRIDE_FIELDS:
            override = model_overrides.get(section)
            if not isinstance(override, dict):
                continue
            for secret_field in SERVICE_SECRET_FIELDS:
                if override.get(secret_field):
                    hide_secret(override, secret_field, drop=drop_secrets)

    voicemail = masked.get("voicemail_detection")
    if drop_secrets and isinstance(voicemail, dict):
        # The classifier's own-LLM key; ignored on platform-models servers.
        voicemail.pop("api_key", None)

    v2_override = masked.get("model_configuration_v2_override")
    if isinstance(v2_override, dict):
        _mask_nested_service_secrets(v2_override, drop_secrets)

    return masked


def _mask_nested_service_secrets(value, drop_secrets: bool):
    if isinstance(value, dict):
        for key, nested in list(value.items()):
            if key in SERVICE_SECRET_FIELDS and nested:
                hide_secret(value, key, drop=drop_secrets)
            else:
                _mask_nested_service_secrets(nested, drop_secrets)
    elif isinstance(value, list):
        for item in value:
            _mask_nested_service_secrets(item, drop_secrets)


# ---------------------------------------------------------------------------
# Workflow definition helpers – mask / merge node API keys
# ---------------------------------------------------------------------------

_NODE_SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    "qa": ("qa_api_key",),
}


def _secret_fields_for_node_type(node_type: str | None) -> tuple[str, ...]:
    if not node_type:
        return ()
    return _NODE_SECRET_FIELDS.get(node_type, ()) or get_node_secret_fields(node_type)


def mask_workflow_definition(
    workflow_definition: Optional[Dict], *, drop_secrets: bool = False
) -> Optional[Dict]:
    """Return a copy of *workflow_definition* with node secret fields masked."""
    if not workflow_definition:
        return workflow_definition

    import copy

    masked = copy.deepcopy(workflow_definition)
    for node in masked.get("nodes", []):
        secret_fields = _secret_fields_for_node_type(node.get("type"))
        if not secret_fields:
            continue
        data = node.get("data", {})
        for field in secret_fields:
            raw_key = data.get(field)
            if not raw_key:
                continue
            if drop_secrets and field in _NODE_SECRET_FIELDS.get("qa", ()):
                # Model-provider keys only; integration secrets stay masked.
                data.pop(field)
            else:
                data[field] = mask_key(raw_key)
    return masked


def merge_workflow_api_keys(
    incoming_definition: Optional[Dict], existing_definition: Optional[Dict]
) -> Optional[Dict]:
    """Preserve real node secret fields when the incoming value is masked."""
    if not incoming_definition or not existing_definition:
        return incoming_definition

    existing_nodes: Dict[str, Dict] = {}
    for node in existing_definition.get("nodes", []):
        if _secret_fields_for_node_type(node.get("type")):
            existing_nodes[node["id"]] = node.get("data", {})

    for node in incoming_definition.get("nodes", []):
        secret_fields = _secret_fields_for_node_type(node.get("type"))
        if not secret_fields:
            continue
        data = node.get("data", {})

        old_data = existing_nodes.get(node["id"])
        if not old_data:
            continue

        for field in secret_fields:
            incoming_key = data.get(field)
            if not incoming_key:
                continue

            old_key = old_data.get(field, "")
            if old_key and is_mask_of(incoming_key, old_key):
                data[field] = old_key

    return incoming_definition
