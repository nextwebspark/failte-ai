# Telephony & SIP — end-to-end architecture

> **Status: investigation snapshot (2026-08-19).** Companion to the other architecture notes in
> `app-doc/`. This maps how phone calls work in this codebase end to end: the provider abstraction,
> configuration storage, the self-service setup flow, outbound and inbound call paths, media
> transport, SIP/BYOC support, and what to do to connect a new VoIP vendor. All paths are
> repo-relative; line numbers are from the current tree and will drift.

---

## 1. The mental model

Every phone call — regardless of carrier — ends up in the same place: a **pipecat pipeline**
processing bidirectional audio over a **WebSocket the carrier opens to our backend**. Everything
else is per-provider plumbing to get the carrier to open that WebSocket.

```
Outbound:
  UI / API / Campaign
        │ POST (initiate)
        ▼
  TelephonyProvider.initiate_call()  ──REST──►  Carrier (Twilio/Telnyx/...)
        ▲                                            │ dials the phone
        │ answer webhook (TwiML/NCCO/XML/CXML)       │ callee answers
        └──────────── carrier calls us ◄─────────────┘
                             │ markup says "open a media stream to wss://…"
                             ▼
  WS /api/v1/telephony/ws/{workflow_id}/{org_id}/{run_id}/{token}
        │
        ▼
  provider.handle_websocket() → run_pipeline_telephony() → pipecat pipeline
                                        (STT → LLM workflow engine → TTS)

Inbound:
  Caller dials number → carrier hits POST /api/v1/telephony/inbound/run
        → detect provider → find org+config+number by DB lookup
        → verify signature → pick workflow from the number's inbound_workflow_id
        → reply with the same "open a media stream" markup → same WS path as above
```

Three transport families exist:

| Family | Providers | Media path |
|---|---|---|
| **PSTN/cloud carriers** | Twilio, Telnyx, Plivo, Vonage, Vobiz | Carrier-hosted WebSocket media streams to our `/telephony/ws/...` endpoint |
| **SIP / BYOC** | Cloudonix (managed SIP trunks), Asterisk ARI (bring-your-own PBX, incl. VICIdial) | Cloudonix: SIP trunk into their cloud, then same WS. ARI: Asterisk `externalMedia` dials our WS directly |
| **WebRTC (browser)** | `smallwebrtc` run mode | Custom signaling WS + `SmallWebRTCTransport` — no carrier at all (§9) |

---

## 2. Provider abstraction

### The ABC

[api/services/telephony/base.py:107](../api/services/telephony/base.py#L107) — `TelephonyProvider`.
Every carrier implements:

- **Outbound**: `initiate_call`, `get_webhook_response` (answer markup), `handle_websocket` (media)
- **Inbound**: `can_handle_webhook` (classmethod — webhook fingerprinting), `parse_inbound_webhook`,
  `verify_inbound_signature`, `start_inbound_stream`
- **Config/lifecycle**: `validate_config`, `validate_account_id`, `validate_phone_number`,
  `configure_inbound` (sync webhook URL to the carrier), `provision_phone_number` (optional),
  `get_sip_connectivity_details` (optional), `get_call_status`, `parse_status_callback`,
  `get_call_cost`, `generate_error_response`
- **Transfers**: `transfer_call`, `supports_transfers` (Vonage returns `False`)
- **AMD**: `supports_answering_machine_detection` + apply/parse hooks (Twilio implements)

Key DTOs in the same file: `CallInitiationResult`, `NormalizedInboundData`, `ProviderSyncResult`,
`SIPConnectivityDetails` / `SIPRegionDetails` / `SIPTransportDetails`.

### Registry + factory

- [api/services/telephony/registry.py](../api/services/telephony/registry.py) — each provider
  package registers a frozen `ProviderSpec` (line 100): provider class, config request/response
  Pydantic classes, **`ui_metadata`** (drives the whole frontend form — §4), `transport_factory`,
  `transport_sample_rate`, `account_id_credential_field`, `server_managed_credential_fields`,
  `preprocess_credentials_on_save` hook.
- Registration is an import side effect:
  [api/services/telephony/providers/\_\_init\_\_.py](../api/services/telephony/providers/__init__.py)
  imports the 7 packages; each package `__init__.py` calls `register(SPEC)`.
- [api/services/telephony/factory.py](../api/services/telephony/factory.py) resolves configs to
  provider instances: `get_telephony_provider_by_id:147`, `get_default_telephony_provider:176`,
  `get_telephony_provider_for_run:158` (reads `telephony_configuration_id` stamped in the run's
  `initial_context`), `find_telephony_config_for_inbound:92`. It joins `telephony_phone_numbers`
  into the credential object as `from_numbers` / `default_from_number` (`_normalize_with_phone_numbers:247`).
- All provider instances are wrapped by
  [api/services/telephony/failure_reporting.py](../api/services/telephony/failure_reporting.py)
  (`instrument_telephony_provider`) so carrier failures are classified and can auto-deactivate a config.
- Contract doc for new providers:
  [api/services/telephony/providers/AGENTS.md](../api/services/telephony/providers/AGENTS.md), plus
  the public guide [docs/integrations/telephony/custom.mdx](../docs/integrations/telephony/custom.mdx).

### The 7 registered providers

| Provider | Class | Answer style | Wire audio | Account-id field | Notes |
|---|---|---|---|---|---|
| `twilio` | [providers/twilio/provider.py:30](../api/services/telephony/providers/twilio/provider.py#L30) | TwiML `<Connect><Stream>` | µ-law 8 kHz | `account_sid` | AMD support; conference-based transfers |
| `telnyx` | [providers/telnyx/provider.py](../api/services/telephony/providers/telnyx/provider.py) | Call Control REST (`answer_and_stream`) | PCMU/PCMA 8 kHz | `connection_id` | Ed25519 webhook signatures (`webhook_public_key`) |
| `plivo` | [providers/plivo/provider.py](../api/services/telephony/providers/plivo/provider.py) | Plivo XML `<Stream>` | µ-law 8 kHz | `auth_id` | |
| `vonage` | [providers/vonage/provider.py](../api/services/telephony/providers/vonage/provider.py) | NCCO JSON `connect→websocket` | **L16 PCM 16 kHz** | `api_key` | JWT auth, `signature_secret` signed webhooks, no transfers |
| `vobiz` | [providers/vobiz/provider.py:32](../api/services/telephony/providers/vobiz/provider.py#L32) | Plivo-compatible XML | µ-law 8 kHz | `auth_id` | HMAC body signing |
| `cloudonix` | [providers/cloudonix/provider.py:85](../api/services/telephony/providers/cloudonix/provider.py#L85) | CXML embedded in REST call | µ-law 8 kHz | `domain_id` | The SIP-trunk/BYOC provider — §8 |
| `ari` | [providers/ari/provider.py:30](../api/services/telephony/providers/ari/provider.py#L30) | ARI REST + Stasis app | µ-law 8 kHz raw binary | *(none — one config per org)* | Bring-your-own Asterisk; VICIdial adapter |

Exotel and Genesys serializers exist in the pipecat submodule but have **no** backend provider
package — they are not usable today.

---

## 3. Configuration storage

### Tables ([api/db/models.py](../api/db/models.py))

- **`telephony_configurations`** (line 221): `organization_id`, `name`, `provider`,
  **`credentials` (plain JSONB)**, `is_default_outbound`, `inactive` / `inactive_since` /
  `inactive_reason`. Unique `(org, name)`; partial unique index enforces one default-outbound per org.
- **`telephony_phone_numbers`** (line 271): `telephony_configuration_id` FK, `address`,
  `address_normalized`, `address_type` (`pstn` | `sip_uri` | `sip_extension`), `country_code`,
  `label`, **`inbound_workflow_id`** (FK → workflows, SET NULL), `is_active`,
  `is_default_caller_id`. Unique `(org, address_normalized)`; partial unique one default caller ID
  per config; partial index on `(address_normalized, organization_id) WHERE is_active` for inbound routing.
- `organization_configurations` holds `CONCURRENT_CALL_LIMIT` and the legacy pre-migration
  `TELEPHONY_CONFIGURATION` blob (backfilled into the new tables by migration `a2355fc6bdc1`).
- `campaigns.telephony_configuration_id` pins a campaign to one config.
- Every workflow run stamps `telephony_configuration_id` into `initial_context` at creation, so the
  media WS and status callbacks can reload the exact same credentials later.

### Credentials: masked, not encrypted

**There is no encryption at rest.** `credentials` is plain JSONB; a repo-wide grep for
Fernet/encrypt/decrypt finds nothing. Protection is masking-on-read:

- Fields flagged `sensitive` in the provider's `ui_metadata` are masked in every API response
  ([api/routes/organization.py:104-127](../api/routes/organization.py#L104-L127)).
- Re-submitting a masked value preserves the stored secret (`preserve_masked_fields`,
  [api/routes/organization.py:570](../api/routes/organization.py#L570);
  helpers in [api/services/configuration/masking.py](../api/services/configuration/masking.py)).
- **Server-managed fields** (e.g. auto-created application IDs) are never accepted from clients,
  carried forward on update, and invalidated when the account-id field changes
  ([api/routes/organization.py:608-641](../api/routes/organization.py#L608-L641)).

### CRUD surface ([api/routes/organization.py](../api/routes/organization.py))

`GET /api/v1/organizations/telephony-providers/metadata` (UI form schema),
`GET|POST /telephony-configs`, `GET|PUT|DELETE /telephony-configs/{id}`,
`POST .../set-default-outbound`, `POST .../reactivate`,
`GET /telephony-config-warnings` (Telnyx missing public key / Vonage missing signature secret counts),
and under each config: `GET|POST .../phone-numbers`, `GET|PUT|DELETE` by id,
`POST .../set-default-caller`. A legacy singleton `GET|POST /telephony-config` still exists as a shim.

---

## 4. Self-service flow (how a user connects a vendor)

The whole UI is **metadata-driven — zero per-provider frontend code**. The backend's
`ProviderSpec.ui_metadata` describes every credential field (`name, label, type, required,
sensitive, options, visible_when, section`), and
[ui/src/components/telephony/ConfigFormDialog.tsx](../ui/src/components/telephony/ConfigFormDialog.tsx)
renders it generically (text/password/textarea/number/boolean/select; dot-path flatten/nest for
nested objects). Adding a backend provider automatically produces its settings form.

### The user journey

1. **Sidebar → Telephony** → [ui/src/app/telephony-configurations/page.tsx](../ui/src/app/telephony-configurations/page.tsx).
2. **Add configuration**: name → pick provider (locked after create) → optional "default for
   outbound" → provider credential fields → Create.
   On save the backend may **auto-create carrier-side objects** via
   `preprocess_credentials_on_save`: Telnyx Call Control Application, Plivo/Vobiz Application,
   Cloudonix domain UUID + Voice Application + outbound trunks (§8).
3. **Manage Phone Numbers** → detail page
   [ui/src/app/telephony-configurations/\[configId\]/page.tsx](../ui/src/app/telephony-configurations/[configId]/page.tsx):
   masked credentials, the org-wide **inbound webhook URL** with copy button, SIP connectivity card
   (Cloudonix), phone-number table.
4. **Add phone number** ([PhoneNumberDialog.tsx](../ui/src/components/telephony/PhoneNumberDialog.tsx)):
   address (E.164, `sip:` URI, or bare extension — validated client-side mirroring
   [api/utils/telephony_address.py](../api/utils/telephony_address.py)), country hint, label,
   **inbound workflow** dropdown, active flag, default-caller-ID flag. Address immutable after create.
   On save the backend:
   - Verifies the number exists on the carrier account (`validate_phone_number`) or provisions it
     (Cloudonix DNID — the only provider implementing `provision_phone_number`;
     [api/routes/organization.py:652-699](../api/routes/organization.py#L652-L699)).
   - **Auto-binds the inbound webhook** on the carrier (`configure_inbound` — Twilio `VoiceUrl`,
     Plivo/Vobiz/Telnyx/Vonage app config, Cloudonix Voice Application URL;
     [api/routes/organization.py:702-734](../api/routes/organization.py#L702-L734)). Partial
     failure returns `provider_sync: {ok:false}` → UI shows a "saved, but failed to sync" warning toast.
   - Rejects a **global routing conflict**: same `(provider, account_id, address)` already routed in
     any org (`find_inbound_routing_conflict`).
5. **Test call**: workflow editor header → Phone Call →
   [PhoneCallDialog.tsx](../ui/src/app/workflow/[workflowId]/components/PhoneCallDialog.tsx) —
   pick config, caller ID, destination (international phone input, or a "Use SIP endpoint" toggle
   accepting `PJSIP/1234` / `SIP/1234`). Zero configs → gate screen routing to setup.

Guided walkthrough for end users:
[docs/getting-started/connect-telephony.mdx](../docs/getting-started/connect-telephony.mdx).
Per-provider setup docs: [docs/integrations/telephony/](../docs/integrations/telephony/).

### Degraded states

- **Auto-deactivation**: repeated carrier failures set `inactive` + `inactive_reason` (failure
  classification in `failure_reporting.py`; ARI manager has its own thresholds,
  [ari_manager.py:61-75](../api/services/telephony/ari_manager.py#L61-L75)). UI shows the reason and
  a **Reactivate** button (`POST .../reactivate`).
- **Warning banners** + sidebar red dot for Telnyx configs missing `webhook_public_key` and Vonage
  configs missing `signature_secret`
  ([TelephonyConfigWarningsContext.tsx](../ui/src/context/TelephonyConfigWarningsContext.tsx)).
- Deleting a config is blocked while campaigns reference it.

### Managed SIP at signup

Org bootstrap best-effort provisions a managed Cloudonix config named `"Dograh Cloudonix SIP"`
(`managed_by="dograh-mps"`), with domain + bearer token minted through the MPS service
([api/services/telephony/providers/cloudonix/provisioning.py](../api/services/telephony/providers/cloudonix/provisioning.py),
called from [api/services/organization_bootstrap.py:227](../api/services/organization_bootstrap.py#L227)).
So a fresh org can have SIP connectivity with zero manual carrier setup.

**No number purchasing exists anywhere** — users always bring numbers they already own on the carrier.

---

## 5. Outbound call flow (detail)

Three entry points, one shape:

| Entry | Route | File |
|---|---|---|
| UI test call | `POST /api/v1/telephony/initiate-call` | [api/routes/telephony.py:81](../api/routes/telephony.py#L81) |
| Public API (API-key) | `POST /api/v1/public/agent/{uuid}`, `/public/workflow/{uuid}`, `/test/...` | [api/routes/public_agent.py:403](../api/routes/public_agent.py#L403) |
| Campaign dispatcher | ARQ `process_campaign_batch` → `dispatch_call` | [api/services/campaign/campaign_call_dispatcher.py:229](../api/services/campaign/campaign_call_dispatcher.py#L229) |

Common sequence (test-call line numbers):

1. Resolve provider — explicit `telephony_configuration_id` else the org's default-outbound config.
2. `validate_config()` → 400 `telephony_not_configured`.
3. Resolve caller ID from `telephony_phone_numbers` (explicit `from_phone_number_id`, else default
   caller ID; campaigns lease from a Redis **from-number pool** — one live call per number,
   [rate_limiter.py:421](../api/services/call_concurrency/rate_limiter.py#L421)).
4. `acquire_org_slot(...)` concurrency check → 429 (§10).
5. Create workflow run: `mode=<provider>`, `call_type=OUTBOUND`, `initial_context` stamped with
   `{phone_number, called_number, direction, provider, telephony_configuration_id}`.
6. Quota check `authorize_workflow_run_start` → 402.
7. Build answer-webhook URL:
   `{backend}/api/v1/telephony/{WEBHOOK_ENDPOINT}?workflow_id=..&workflow_run_id=..&organization_id=..`
   (`twiml` for Twilio/Cloudonix, `plivo-xml`, `vobiz-xml`, `/ncco` GET for Vonage; base URL from
   `BACKEND_API_ENDPOINT`, with Cloudflare-tunnel fallback for non-public hosts —
   [api/utils/common.py:134](../api/utils/common.py#L134)).
8. `provider.initiate_call(...)` — the carrier REST call:
   - Twilio: `POST .../Calls.json` with `Url` + `StatusCallback` (`initiated,ringing,answered,completed`) + optional AMD params.
   - Cloudonix: `POST https://api.cloudonix.io/calls/{domain}/application` with inline CXML,
     `trunk` pinned to the managed outbound trunk.
   - ARI: `POST {ari}/ari/channels` with `endpoint=PJSIP/{number}` (raw `SIP/`/`PJSIP/` strings pass through).
9. Carrier answers → hits our answer webhook → provider route
   (e.g. [providers/twilio/routes.py:47](../api/services/telephony/providers/twilio/routes.py#L47))
   verifies signature, returns markup telling the carrier to open the media WebSocket.
10. Carrier connects `WS /api/v1/telephony/ws/{workflow_id}/{org_id}/{run_id}/{token}` → §7.

Status callbacks (`.../{provider}/status-callback/...`, hangup/ring callbacks, Telnyx events) feed
[api/services/telephony/status_processor.py](../api/services/telephony/status_processor.py), which
drives campaign retries (`busy`/`no-answer` are the retryable set) and enqueues post-run
integrations even for calls that never connected.

---

## 6. Inbound call flow (detail)

One org-agnostic webhook for all carriers: **`POST /api/v1/telephony/inbound/run`**
([api/routes/telephony.py:786](../api/routes/telephony.py#L786)). This is the URL
`configure_inbound` syncs onto carriers, and what the UI shows for manual setup.

1. Parse form/JSON + raw body ([api/utils/telephony_helper.py:139](../api/utils/telephony_helper.py#L139)).
2. **Detect the provider** — loop all registered providers calling
   `can_handle_webhook(data, headers)` (each carrier's payload shape is fingerprintable).
3. Normalize to `NormalizedInboundData` (caller, called number, carrier account id).
4. **One SQL join resolves everything**
   ([api/db/telephony_phone_number_client.py:130](../api/db/telephony_phone_number_client.py#L130)):
   match `provider` + `credentials->>account_id_field` + `address_normalized` + `is_active` +
   config not inactive → yields `(config, phone_row)` and therefore the org. This is why the same
   URL works for every org: **the account credentials in the webhook payload identify the tenant.**
5. **Workflow selection** = `phone_row.inbound_workflow_id` (the dropdown from §4). None assigned →
   provider-formatted "not found" response.
6. Verify webhook signature (Twilio HMAC, Telnyx Ed25519, Vonage JWT, Plivo V2/V3, Vobiz HMAC,
   Cloudonix `x-cx-apikey`; ARI n/a).
7. Concurrency slot + quota (over-limit returns polite provider markup, not a 4xx).
8. Create run (`call_type=INBOUND`, raw webhook stashed in `logs.inbound_webhook`).
9. `start_inbound_stream(...)` returns the provider's stream-open markup (TwiML / Plivo `<Stream
   bidirectional>` / NCCO websocket connect / Telnyx REST answer+stream / CXML) → carrier opens
   the same media WS as outbound.

Also present: deprecated per-workflow webhook `POST /telephony/inbound/{workflow_id}`, and
`POST /telephony/inbound/fallback` ("system unavailable" markup).

**ARI inbound is different**: no HTTP webhook. A standalone **ARI manager** process
([api/services/telephony/ari_manager.py](../api/services/telephony/ari_manager.py), enabled by
`ENABLE_ARI_MANAGER`, separate deployment in helm) keeps one ARI WebSocket per active config,
consumes Stasis events, creates the run on `StasisStart`, answers the channel, and wires
`externalMedia` + bridge to our media WS.

**Agent-stream (BYO gateway)**: `WS /api/v1/agent-stream/{provider}/{workflow_uuid}`
([api/routes/agent_stream.py:33](../api/routes/agent_stream.py#L33)) lets an external gateway open
the media stream directly, skipping the webhook dance. Cloudonix-only today
(`handle_external_websocket`; session validated from the in-band `accountSid`).

---

## 7. Media transport & audio

- Media WS routes: [api/routes/telephony.py:559-608](../api/routes/telephony.py#L559-L608)
  (`/ws/ari` + tokenized 3/4-segment variants). Shared handler `_handle_telephony_websocket:611`:
  capability-token check → load run (org-scoped) → run must be `initialized` (else 4409) →
  provider-name must match run mode → mark `running` → `provider.handle_websocket(...)`.
- **WS auth** ([api/services/telephony/ws_auth.py](../api/services/telephony/ws_auth.py)):
  HMAC-SHA256 over `workflow_id:org_id:run_id`, secret `TELEPHONY_WS_TOKEN_SECRET`, enforcement
  gated by `TELEPHONY_WS_TOKEN_ENFORCE` (two-phase rollout). Known documented gaps: token is
  stateless/replayable while the run is still `initialized`, and appears in access logs (path segment).
- Provider handshake extracts carrier stream IDs (e.g. Twilio `connected`/`start` frames →
  `streamSid`/`callSid`), then calls
  [run_pipeline_telephony](../api/services/pipecat/run_pipeline.py#L257).
- That builds `AudioConfig` from `ProviderSpec.transport_sample_rate`
  ([api/services/pipecat/audio_config.py:73](../api/services/pipecat/audio_config.py#L73); pipeline
  capped at 16 kHz for VAD), calls the provider's `transport_factory`
  (`providers/<name>/transport.py` — all build pipecat `FastAPIWebsocketTransport` with the
  provider's `FrameSerializer`), then converges on the shared `_run_pipeline_impl:549` — same
  pipeline builder, quota accounting, mixers and realtime overrides as WebRTC.
- Serializers live in the pipecat submodule
  ([pipecat/src/pipecat/serializers/](../pipecat/src/pipecat/serializers/)): µ-law 8 kHz for
  twilio/plivo/vobiz/cloudonix, PCMU/PCMA for telnyx, L16 16 kHz for vonage, raw binary µ-law
  (no JSON envelope) for asterisk.

---

## 8. SIP / BYOC specifics

### Cloudonix — managed SIP trunks (the "connect any VoIP vendor via SIP" answer)

- **Inbound (their trunk → us)**: customer points their SIP trunk at a regional Cloudonix edge.
  Regions in [providers/cloudonix/regions.py:28](../api/services/telephony/providers/cloudonix/regions.py#L28)
  (India `in.dimi.tel`, UAE `uae.dimi.tel`, Global `sip.cloudonix.net` — UDP/TCP/TLS ports + edge
  IPs). `get_sip_connectivity_details` builds per-region SIP URIs
  (`{domain_uuid}.{suffix}:{port}[;transport=tcp|tls]`), exposed as `sip_connectivity` on the
  config GET and rendered by
  [SipConnectivityCard.tsx](../ui/src/components/telephony/SipConnectivityCard.tsx). Auth is
  IP/hostname-based — **no SIP registration**.
- **Outbound BYOC trunks (us → their carrier)**:
  `CloudonixOutboundTrunkConfiguration` — user supplies only `name`, `region`, `sip_domain`
  ([CloudonixOutboundTrunkForm.tsx](../ui/src/components/telephony/CloudonixOutboundTrunkForm.tsx));
  remote peer IP/port/transport derived from the region. Trunk create/update/deactivate lifecycle
  against the Cloudonix API in
  [providers/cloudonix/\_\_init\_\_.py:330-575](../api/services/telephony/providers/cloudonix/__init__.py#L330-L575);
  server-minted trunk UUIDs stored in server-managed `outbound_trunk_uuids`. Outbound calls pin
  `trunk` to the enabled managed trunk.

### Asterisk ARI — bring your own PBX

- Config: `ari_endpoint`, `app_name`/`app_password` (Stasis app), `ws_client_name` (the
  `websocket_client.conf` connection Asterisk uses to dial back), optional VICIdial `external_pbx`
  block. `from_numbers` are SIP extensions, not E.164.
- Outbound dial string `PJSIP/{number}`; media via ARI `externalMedia` (`format=ulaw`,
  `transport=websocket`, run identity passed in `transport_data`), Asterisk connects to
  `/api/v1/telephony/ws/ari` with `Sec-WebSocket-Protocol: media`.
- One config per org (no account-id field). Broken PBX auto-deactivates; manual Reactivate.
- VICIdial rides on ARI via the external-PBX adapter
  ([providers/ari/external_pbx/](../api/services/telephony/providers/ari/external_pbx/)) — agent
  transfers into in-groups, lead field mapping. Gated by the org flag surfaced as
  `externalPbxIntegrationsEnabled` in the UI.
- Full Asterisk-side setup (ari.conf, pjsip.conf, websocket_client.conf, ulaw requirement):
  [docs/integrations/telephony/asterisk-ari.mdx](../docs/integrations/telephony/asterisk-ari.mdx).

### Generic SIP addressing

[api/utils/telephony_address.py](../api/utils/telephony_address.py) normalizes every stored
address into one of three types: `pstn` (E.164 with country-hint), `sip_uri` (RFC 3261 parse,
default ports dropped), `sip_extension`. Carrier webhook sync is skipped for non-PSTN addresses.
The test-call dialog likewise accepts `SIP/…`/`PJSIP/…` endpoints directly.

**So "connecting a VoIP vendor" has three tiers**: (a) the vendor is one of the 7 providers →
enter credentials, done; (b) any SIP-capable vendor → point their trunk at the Cloudonix managed
SIP config (or write a Cloudonix outbound trunk to them); (c) self-hosted Asterisk/VICIdial → ARI.

---

## 9. WebRTC (browser) vs PSTN

| | PSTN/SIP | WebRTC |
|---|---|---|
| Entry | initiate/inbound routes | `WS /api/v1/signaling/{workflow_id}/{run_id}` ([api/routes/webrtc_signaling.py:764](../api/routes/webrtc_signaling.py#L764)); public embed `WS /api/v1/public/signaling/{session_token}` |
| Run mode | provider name | `smallwebrtc` |
| Transport | `FastAPIWebsocketTransport` + serializer | pipecat `SmallWebRTCTransport` ([api/services/pipecat/transport_setup.py](../api/services/pipecat/transport_setup.py)) |
| Audio | 8 kHz µ-law (16 kHz Vonage) | Opus/PCM, 16 kHz |
| Frontend | — | hand-rolled `RTCPeerConnection` + custom JSON signaling, **not** a pipecat/Daily client SDK: [useWebSocketRTC.tsx](../ui/src/app/workflow/[workflowId]/run/[runId]/hooks/useWebSocketRTC.tsx); TURN creds from `/api/v1/turn/credentials` |
| Embed widget | — | [ui/public/embed/failte-widget.js](../ui/public/embed/failte-widget.js), token-scoped public endpoints (`/public/embed/*`) |

Both converge on the same `_run_pipeline_impl`, so workflow behavior is identical; the telephony
media WS explicitly rejects `smallwebrtc` runs (4400) and vice versa. The signaling WS also streams
realtime feedback events (`rtf-*`: transcription, bot text, node transitions, TTFB metrics).

---

## 10. Campaigns, limits, and safety rails

- **Campaigns**: CSV (must contain `phone_number`; other columns become `initial_context`) →
  presigned upload to S3/MinIO → ARQ `process_campaign_batch` → dispatcher. Pinned telephony
  config; effective concurrency = `min(org limit, campaign setting, phone-number count)` (one live
  call per caller-ID). Retry config (busy/no-answer/voicemail toggles), day-of-week call schedule
  with timezone, circuit breaker (failure % over window) —
  [api/services/campaign/](../api/services/campaign/), orchestrator process gated by
  `ENABLE_CAMPAIGN_ORCHESTRATOR`, per-second dial rate token bucket (`rate_limit_per_second`, default 1).
- **Org concurrency**: Redis ZSET + Lua atomic acquire
  ([api/services/call_concurrency/](../api/services/call_concurrency/)); limit from org config
  `CONCURRENT_CALL_LIMIT` else `DEFAULT_ORG_CONCURRENCY_LIMIT` (10). Stale slots reclaimed after
  20 min. Fleet-wide mirror feeds autoscaling (`GET /health/autoscale-metric`, KEDA-friendly,
  behind `X-Dograh-Devops-Secret`).
- **Call duration**: `max_call_duration` default 300 s, hard cap 1200 s, enforced in-pipeline;
  plus user-idle timeout and 300 s recording cap.
- **Quota/billing**: `authorize_workflow_run_start` on every entry path (402 / provider markup).
- **Transfers**: Redis pub/sub transfer bus
  ([call_transfer_manager.py](../api/services/telephony/call_transfer_manager.py)) + per-provider
  strategies (Twilio conference, ARI bridge-swap, etc.); result webhooks per provider. Vonage
  doesn't support transfers.

Key env vars: `BACKEND_API_ENDPOINT`/`PUBLIC_BASE_URL` (webhook base), `TELEPHONY_WS_TOKEN_SECRET`
/ `_ENFORCE`, `ENABLE_ARI_MANAGER`, `ENABLE_CAMPAIGN_ORCHESTRATOR`, `DEFAULT_ORG_CONCURRENCY_LIMIT`,
`REDIS_URL`. Provider credentials are **DB-only, never env**.

---

## 11. Adding a new VoIP vendor (custom provider)

Follow [docs/integrations/telephony/custom.mdx](../docs/integrations/telephony/custom.mdx) and
[providers/AGENTS.md](../api/services/telephony/providers/AGENTS.md). In short, create
`api/services/telephony/providers/<name>/` with:

1. `config.py` — Pydantic credential request/response models.
2. `provider.py` — `TelephonyProvider` subclass (outbound REST call, answer markup, webhook
   fingerprint + signature verification, `start_inbound_stream`, `handle_websocket`).
3. `serializers.py` — a pipecat `FrameSerializer` for the carrier's wire format (reuse an existing
   one if the format is Twilio/Plivo-compatible — Vobiz and Cloudonix do exactly that).
4. `transport.py` — `FastAPIWebsocketTransport` factory.
5. `routes.py` — answer webhook + status callbacks under `/api/v1/telephony/`.
6. `__init__.py` — build `ProviderSpec` (incl. `ui_metadata` — this alone creates the settings UI)
   and `register(SPEC)`; import it from `providers/__init__.py`.

No frontend work needed; the metadata-driven form renders it.

---

## 12. Gaps & drift worth knowing (as of this snapshot)

- **Credentials unencrypted at rest** (masking only) — worth an encryption pass if this goes multi-tenant SaaS-serious.
- Media-WS token replayable pre-connect and logged in access logs (documented in `ws_auth.py`).
- No number purchasing / carrier search — bring-your-own-number only.
- Legacy surface still alive: singleton `GET|POST /organizations/telephony-config`, per-workflow
  inbound webhook, `TelephonyConfigurationResponse` union the SDK docstring says should die.
- Docs drift: [custom.mdx](../docs/integrations/telephony/custom.mdx) documents wrong UI path and
  wrong field-type list (`string-array` unimplemented; `boolean`/`select` undocumented);
  [overview.mdx](../docs/integrations/telephony/overview.mdx) omits Telnyx and VICIdial from the
  provider cards; SIP connectivity card, Telnyx `webhook_public_key`, config auto-deactivation /
  Reactivate, `provider_sync` warning, and the SIP-endpoint test-call mode have **no** user docs.
- Branding mid-migration: UI says "Failte AI" (`SipConnectivityCard`, `failte-widget.js`,
  `window.FailteWidget`) while docs say Dograh; `dograh-widget.js` shim still ships.
- Exotel/Genesys pipecat serializers exist but no provider packages; `api/services/telephony/README.md`
  describes the pre-refactor layout.
