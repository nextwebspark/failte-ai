# Per-Agent (Per-Workflow) Model, Voice & Telephony Configuration

> Status: research document. Describes what exists today and what changes would be needed. **No code changes have been made.**

The question this answers: model, voice, and telephony are configured at the organization level today — can they be configured per agent (per workflow), while API keys and credentials (e.g. Vertex AI service-account JSON) stay central at the org level?

Short answer:

| Concern | Per-agent today? | Keys stay central? |
|---|---|---|
| LLM model / TTS voice / STT | **Yes — "Model Overrides" in workflow settings** | Partially — org keys are *copied* into the workflow at save time (stale after rotation) |
| Inbound phone number → agent | **Yes** — each number maps to a workflow | Yes — SIP/provider credentials are org-level only |
| Outbound trunk / caller ID | No — per campaign or per call only | Yes |
| SIP / PBX credentials | Never per-agent (by design) | Yes |

---

## 1. Model & voice configuration — current architecture

### 1.1 Org-level storage

- Table `organization_configurations` (`api/db/models.py:198`), key `MODEL_CONFIGURATION_V2` (`api/enums.py:105`). One JSON document per org.
- Document shape: `OrganizationAIModelConfigurationV2` (`api/schemas/ai_model_configuration.py`):

```
version: 2
mode: "dograh" | "byok"
dograh?:  { api_key, voice, speed, language }        # Dograh-managed models
byok?:
  mode: "pipeline" | "realtime"
  pipeline?: { llm, tts, stt, embeddings? }          # per-service typed configs
  realtime?: { realtime, llm, embeddings? }
```

- Per-provider service configs (provider, model, voice, api_key, credentials, …) live in the registry `api/services/configuration/registry.py` (~30 providers, discriminated unions `LLMConfig` / `TTSConfig` / `STTConfig` / `RealtimeConfig` / `EmbeddingsConfig`). Note: `api_key` is a **required** field on `BaseServiceConfiguration`, and it may be a list (key rotation — a random key is picked per access).
- `compile_ai_model_configuration_v2()` (same schema file) flattens the stored doc into the runtime object `EffectiveAIModelConfiguration` (`.llm/.tts/.stt/.embeddings/.realtime`, `is_realtime`, …). Everything downstream consumes only this compiled object.
- Legacy v1 (`UserConfigurationKey.MODEL_CONFIGURATION`, per-user) is dead at runtime; only migration endpoints read it.

### 1.2 Per-workflow override — **already exists**

- UI: workflow settings page → **Model Overrides** section (`ui/src/app/workflow/[workflowId]/settings/page.tsx`, `WorkflowModelOverridesSection` ~line 1379). A "Override for this workflow" switch mounts the same `AIModelConfigurationV2Editor` used by the org page; toggling off deletes the override keys.
- Storage: `workflow_configurations` JSON blob (typed `WorkflowConfigurationDefaults`, `api/schemas/workflow_configurations.py:67`, `extra="allow"`), on **`WorkflowDefinitionModel`** (versioned source of truth, `api/db/models.py:360`) and mirrored on `WorkflowModel` (`api/db/models.py:431`). Runs pin a `definition_id`, so config is immutable per run.
- Two generations coexist inside the blob:
  - `model_overrides` — legacy partial per-section overlay (llm/tts/stt/realtime), deep-merged onto org config via `resolve_effective_config` (`api/services/configuration/resolve.py`).
  - `model_configuration_v2_override` — current: a **complete** `OrganizationAIModelConfigurationV2` document that fully replaces the org config. Key constant `WORKFLOW_MODEL_CONFIGURATION_V2_OVERRIDE_KEY` (`api/services/configuration/ai_model_configuration.py:38`).
- Save path: generic `PUT /api/v1/workflow/{workflow_id}` with `workflow_configurations` (no dedicated endpoint). UI helper: `saveWorkflowConfigurations` in `ui/src/app/workflow/[workflowId]/hooks/useWorkflowState.ts`.

### 1.3 Runtime resolution

Single choke point: `get_effective_ai_model_configuration_for_workflow(organization_id, workflow_configurations)` — `api/services/configuration/ai_model_configuration.py:85`:

1. If `model_configuration_v2_override` present → compile it directly. **Org config is not consulted at all.**
2. Else → load org `MODEL_CONFIGURATION_V2`, apply legacy `model_overrides` merge if present.

Callers (all read the run's *pinned definition* configs):

| Caller | Location |
|---|---|
| Telephony WS pipeline | `api/services/pipecat/run_pipeline.py:358` |
| WebRTC pipeline | `api/services/pipecat/run_pipeline.py:488` |
| Pipeline impl fallback | `api/services/pipecat/run_pipeline.py:643` |
| Text chat runner | `api/services/workflow/text_chat_runner.py:463` |
| QA node LLM | `api/services/workflow/qa/llm_config.py:62` |
| Quota / call authorization | `api/services/quota_service.py:764` |

Downstream, `service_factory.py` builds Pipecat STT/TTS/LLM services from the compiled config; `pipeline_builder.py` has no config awareness. Resolved provider/model pairs are stamped into `workflow_run.initial_context["runtime_configuration"]` for analytics.

### 1.4 The caveat: API keys are snapshotted into the workflow

This is the part that violates "keys stay central":

- On first save of a v2 override, `api/routes/workflow.py:1141–1203` calls `merge_ai_model_configuration_v2_secrets(override, org_config)` — **copies the org's real API keys / Vertex credentials into the workflow blob**, validates, persists. The legacy path uses `enrich_overrides_with_api_keys` (`resolve.py:37`), whose docstring states the intent: the override is deliberately self-contained.
- Secret fields: `SERVICE_SECRET_FIELDS = ("api_key", "credentials", "aws_access_key", "aws_secret_key")` (`api/services/configuration/masking.py:22`).
- Because secrets live in the workflow blob, a full mask/unmask protocol exists: `mask_workflow_configurations()` (`masking.py:147`) masks on read at 6 route sites in `routes/workflow.py`; `merge_workflow_configuration_secrets()` (`api/services/configuration/merge.py:119`) restores real keys when the client sends back a mask; `check_for_masked_keys_in_ai_model_configuration_v2` rejects leftover masks.
- Consequences:
  - The user never re-types a key (good UX), but each overridden workflow holds a **stale snapshot**. Rotating the org's Vertex credentials does **not** propagate to overridden workflows until each is re-saved.
  - `duplicate_workflow` (`api/services/workflow/duplicate.py:86–119`) deep-copies the blob **including embedded keys**.
  - Every historical `workflow_definitions` version also embeds keys.

### 1.5 Using the existing feature today (walkthrough)

1. Open the agent → Settings → **Model Overrides**.
2. Enable "Override for this workflow".
3. Pick provider/model/voice in the editor (same tabs as org page: Speech-to-Speech / Managed / BYOK). Existing org keys are auto-carried; no re-entry needed.
4. Save. This workflow now uses its own model/voice; all other workflows keep the org config.
5. Caveat: if org keys later rotate, re-save the override on each workflow to refresh the embedded copy.

---

## 2. Proposed design: key-free overrides (future work, not implemented)

Goal: an override stores **only** provider/model/voice/speed/language; all secrets resolved from the org config at call time, so rotation propagates instantly.

### 2.1 Design decisions

- **Override shape**: keep the full v2 document, minus secret fields, stored as a raw dict. Zero shape migration; old key-embedded rows are just the "already-has-secrets" case of the same shape. Because `api_key` is pydantic-required, a stripped doc must never be `model_validate`d standalone — inject secrets into the raw dict first, then validate.
- **Secret resolution**: build a provider-keyed secret map from the whole org config (`dograh.api_key` under `"dograh"`; every byok section contributes `api_key` / Vertex `credentials` / Bedrock AWS keys under its provider name). At merge time:
  - Provider in map → org secret **overwrites** anything embedded (instant rotation, even for old pinned definitions).
  - Provider not in map but override embeds a secret → keep embedded (back-compat for old definitions).
  - Neither → 422 at save time, descriptive error at runtime.
  - Practical rule: override provider choices restricted to providers that have org-level credentials; a per-provider key vault is future work.

### 2.2 Changes (concentrated in 3 places)

1. **New module** `api/services/configuration/workflow_override_secrets.py`: `build_provider_secret_map(org)`, `strip_secret_fields(override)`, `inject_secrets_into_v2_override(override, map)`, `resolve_v2_override_with_org_secrets(override, org)`.
2. **Runtime** — `get_effective_ai_model_configuration_for_workflow` v2 branch: load org config, `resolve_v2_override_with_org_secrets`, then compile. All 6 callers and everything downstream unchanged.
3. **Save path** — `routes/workflow.py` v2 branch: strip `SERVICE_SECRET_FIELDS` from the incoming override; inject org secrets into a *copy* for `UserConfigurationValidator`; persist the **stripped** dict. Drop the mask-merge calls in this branch only.

Supporting work:

- **Masking machinery stays** — old rows/definitions still embed keys; masking is a no-op on stripped rows. `merge_ai_model_configuration_v2_secrets` remains for the org-config save path.
- **Alembic data migration** (hygiene pass, ship last; precedent: `api/alembic/versions/b41f7c9d2e05_…`): per org, strip secrets inside `model_configuration_v2_override` in both `workflows` and `workflow_definitions` rows — only where the section's provider resolves in that org's secret map. Legacy `model_overrides` untouched. No-op downgrade. Idempotent.
- **UI**: `hideSecretFields` prop on `AIModelConfigurationV2Editor` → `ServiceConfigurationForm`; hides api_key / credentials / AWS fields and skips key-required client validation when the editor runs in workflow-override context (`WorkflowModelOverridesSection` passes it).
- **Tests**: new `api/tests/test_workflow_override_secret_resolution.py` (secret map incl. Vertex credentials + key lists; strip; org-wins rotation; embedded fallback; missing-both error; end-to-end resolution). Extend `test_ai_model_configuration_v2.py` (override path now consults org config) and a route-level save test (persisted blob has no secrets; unresolvable provider → 422). Run legacy suites unchanged: `test_resolve_effective_config.py`, `test_masked_key_rejection.py`.

Sequencing: runtime (backward-compatible with key-embedding rows) → save path → UI → migration.

Verification commands (per AGENTS.md):

```bash
source venv/bin/activate && set -a && source api/.env.test && set +a && \
python -m pytest api/tests/test_workflow_override_secret_resolution.py \
  api/tests/test_ai_model_configuration_v2.py \
  api/tests/test_resolve_effective_config.py \
  api/tests/test_masked_key_rejection.py
cd ui && npx tsc --noEmit && npm run lint
```

Manual check: save an override changing only model/voice → DB blob has no `api_key`/`credentials`; rotate org Vertex credentials → existing overridden workflow's next call uses new credentials without re-save.

---

## 3. Telephony / SIP: per-agent status

### 3.1 Storage (org-scoped)

- `telephony_configurations` (`api/db/models.py:221`): `organization_id`, `name`, `provider`, `credentials` JSON, `is_default_outbound` (partial-unique: one default per org), inactive flags. 7 providers, each with typed config in `api/services/telephony/providers/<name>/config.py`: `twilio`, `plivo`, `vonage`, `vobiz`, `cloudonix` (incl. `outbound_trunks` — real SIP trunks synced on the domain), `telnyx`, `ari` (Asterisk REST Interface — direct SIP/PBX, incl. optional `external_pbx` VICIdial block).
- `telephony_phone_numbers` (`api/db/models.py:271`): number rows tied to a config, with `is_default_caller_id`, `is_active`, and — the key field — **`inbound_workflow_id`**.
- All CRUD routes live under the **organization** router (`api/routes/organization.py:742+`) — telephony is modeled as an org resource. SIP credentials/trunks are **never** stored per workflow.
- The old `OrganizationConfigurationKey.TELEPHONY_CONFIGURATION` blob is deprecated; migrated to these tables by alembic `a2355fc6bdc1`.

### 3.2 Inbound — already per-agent

Each phone number maps to a workflow via `telephony_phone_numbers.inbound_workflow_id`.

Runtime chain (`POST /api/v1/telephony/inbound/run`, `api/routes/telephony.py:786–960`): detect provider from webhook → normalize (to/from number, account id) → single SQL join over configs + numbers resolves org **and** number row → `workflow_id = phone_row.inbound_workflow_id` (null → hang up with `WORKFLOW_NOT_FOUND`) → verify signature against the matched config's credentials → create workflow run with `initial_context` (caller/called number, direction, `telephony_configuration_id`) → start media stream. ARI/SIP inbound does the same off the dialed extension (`api/services/telephony/ari_manager.py:786–900`).

UI: phone-number dialog has an "Inbound workflow" selector (`ui/src/components/telephony/PhoneNumberDialog.tsx`); the config detail page lists numbers with their inbound workflow (`ui/src/app/telephony-configurations/[configId]/page.tsx`).

### 3.3 Outbound — per campaign / per call, not per workflow

- Selection helpers in `api/services/telephony/factory.py`: explicit config id → else org default (`is_default_outbound`). Caller ID via `select_from_number` (`api/services/telephony/base.py:120`): explicit > config default > random from active pool.
- Three initiation paths, all "request override else org default":
  - Test call: `api/routes/telephony.py:81–296` (`telephony_configuration_id`, `from_phone_number_id` in request; UI: `PhoneCallDialog.tsx`, per-call, not persisted).
  - **Campaign: pinned per campaign** — `CampaignModel.telephony_configuration_id` (`api/db/models.py:697`), required picker at campaign create. Dispatcher manages a per-config from-number pool (`api/services/campaign/campaign_call_dispatcher.py`).
  - API / public agent trigger: `api/routes/public_agent.py:193–240`.
- `WorkflowModel` has **no** telephony column — no per-workflow outbound trunk or default caller ID today.
- Future option (small change): put nullable `telephony_configuration_id` (+ optional `from_phone_number_id`) into the `workflow_configurations` blob (`extra="allow"` — round-trips without schema change) and resolve it before the org-default fallback at the three initiation sites. Downstream already honors per-run config: `initial_context["telephony_configuration_id"]` → `get_telephony_provider_for_run` → transport.

### 3.4 External PBX (VICIdial)

- Connection is org-level: gated by `external_pbx_integrations_enabled` (`ORGANIZATION_PREFERENCES`), credentials inside the ARI config's `credentials.external_pbx`.
- What IS per-workflow is only **data mapping** (`workflow_configurations.external_pbx_field_mappings` / `external_pbx_lead_headers`, `api/schemas/workflow_configurations.py:104–112`): push gathered-context values into VICIdial lead fields, capture SIP INVITE headers off the inbound leg. `apply_external_pbx_mapping_policy` (`api/services/workflow/configuration_policy.py`) is a save-time guard preserving these keys when the org toggle hides the UI section — a useful precedent for "preserve stored values the request omitted".

---

## 4. Open decisions / limitations

- Key-free overrides restrict per-agent provider choice to providers with org-level credentials; a per-provider org key vault would lift that later.
- Per-node model choice (different model per conversation node inside one agent) is out of scope; the only precedent is the QA node's own LLM config (`qa_provider`/`qa_model` node fields).
- Line numbers in this doc reflect the codebase as of 2026-08-19 (branch `feature/cleanup`) and will drift.
