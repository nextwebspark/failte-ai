# The voice agent — framework, runtime, and call lifecycle

> **Status: architecture reference (2026-08-20).** Companion to
> [`app-doc/telephony-architecture.md`](./telephony-architecture.md) (carrier plumbing) and
> [`app-doc/tool-catalog.md`](./tool-catalog.md) (future tool-library design). This document answers:
> *what framework runs the agent, how a call starts, what the agent actually "is" while the call is
> live, which tools it can call, and what happens when the call ends.* All paths are repo-relative;
> line numbers are from the current tree and will drift.
>
> For the product-level version of the same story, see the Mintlify page
> [`docs/core-concepts/how-dograh-works.mdx`](../docs/core-concepts/how-dograh-works.mdx). This file is
> the engineering-level one.

---

## 1. The one-paragraph model

Dograh runs conversational voice agents on **[pipecat](https://github.com/pipecat-ai/pipecat)** — a
frame-based real-time media framework — using a **vendored fork** checked in as the `pipecat/` git
submodule. A call is a `Pipeline` of `FrameProcessor`s: audio enters from a transport, becomes text
(STT), text goes to an LLM, the reply becomes audio (TTS), audio leaves via the same transport.

The *agent* is not a single prompt. It is a **directed graph of nodes** authored in the UI and stored
as ReactFlow JSON. A driver class, `PipecatEngine`, walks that graph. On every node entry it **rebuilds
the entire LLM context**: one system prompt string and one flat list of function schemas. The LLM
"walks" the graph by calling a function named after an outgoing edge. Everything else — tools, variable
extraction, hangup, transfer — hangs off that loop.

```
                                  ┌──────────────────────────────────────────┐
  caller audio ──► transport.in ─►│ STT ─► user_agg ─► LLM ─► callbacks ─►TTS│─► transport.out ──► caller
                                  └───────────▲──────────────┬───────────────┘
                                              │              │ function call = edge label
                                       system prompt +        ▼
                                       tool schemas    ┌──────────────┐
                                              │        │ PipecatEngine│  walks WorkflowGraph
                                              └────────┤  .set_node() │  node → prompt + tools
                                                       └──────────────┘
```

---

## 2. Technology stack

### Backend (`api/`)

| Layer | Choice | Where |
|---|---|---|
| Language | Python 3.13 | [api/pyproject.toml](../api/pyproject.toml) |
| HTTP / WS | FastAPI 0.135 + uvicorn | [api/app.py](../api/app.py) |
| Voice framework | **pipecat** (fork, submodule) + `tuner-pipecat-sdk` | [pipecat/](../pipecat/), [api/requirements.txt](../api/requirements.txt) |
| DB | PostgreSQL + SQLAlchemy 2 async + asyncpg, Alembic, `pgvector` | [api/db/](../api/db/) |
| Cache / pub-sub / queue | Redis + **ARQ** | [api/tasks/arq.py](../api/tasks/arq.py) |
| Object storage | S3 or MinIO (switched by `ENABLE_AWS_S3`) | [api/services/storage.py](../api/services/storage.py) |
| Tracing | OpenTelemetry → **Langfuse** (per-org routing) | [api/services/pipecat/tracing_config.py](../api/services/pipecat/tracing_config.py) |
| Product analytics / errors | PostHog, Sentry | |
| MCP | `fastmcp` (Dograh both *hosts* an MCP server and *consumes* customer MCP servers) | [api/mcp_server/](../api/mcp_server/) |

### Frontend (`ui/`)

Next.js 15 / React 19 / TypeScript / Tailwind + shadcn. The workflow canvas is
**`@xyflow/react`** (ReactFlow) with `@dagrejs/dagre` auto-layout and `zustand` + `zundo` for
undo/redo state. The API client (`ui/src/client/*.gen.ts`) is **generated from the backend OpenAPI
spec** — so the Pydantic schemas in `api/schemas/` are the single source of truth for UI forms.

### Processes

One `api` container runs several roles, selected by env flags (see [docker-compose.yaml](../docker-compose.yaml)):

| Process | Script | Role |
|---|---|---|
| web | `scripts/run_web.sh` | FastAPI — REST + WebSockets. **The voice pipeline runs in-process here.** |
| arq worker | `scripts/run_arq_worker.sh` | Post-call jobs, webhooks, campaign batches, KB ingestion |
| campaign orchestrator | `scripts/run_campaign_orchestrator.sh` | `ENABLE_CAMPAIGN_ORCHESTRATOR` — Redis event loop that schedules dial batches |
| ARI manager | `scripts/run_ari_manager.sh` | `ENABLE_ARI_MANAGER` — Asterisk Stasis event loop for BYO-PBX |

---

## 3. pipecat, and why it is a fork

Upstream pipecat gives us: `Frame` / `FrameProcessor` / `Pipeline` / `PipelineWorker`, the service
adapters (Deepgram, Cartesia, ElevenLabs, OpenAI, Anthropic, Google…), transports
(`FastAPIWebsocketTransport`, `SmallWebRTCTransport`), telephony frame serializers, VAD, turn-taking
strategies, and the context aggregators.

`pipecat/` is a submodule pointing at `https://github.com/dograh-hq/pipecat.git` — a *merge-tracked*
fork (upstream `v1.7.0` merged in, never rebased). It is installed from source, not PyPI
([api/Dockerfile](../api/Dockerfile#L38-L40)); there is no pipecat pin in `requirements.txt`.

What the fork adds, by area:

| Area | Addition |
|---|---|
| Managed services | `services/dograh/` — `DograhLLMService`, `DograhSTTService`, `DograhFluxSTTService`, `DograhTTSService`, `mps_billing.py` (Dograh's own hosted inference endpoints) |
| New providers | `services/huggingface/`, `services/speaches/`, `services/minimax/` |
| Telephony | New serializers `asterisk.py`, `vobiz.py`, `cloudonix.py`; new `call_strategies.py` defining `TransferStrategy` / `HangupStrategy` abstractions consumed by Twilio/Telnyx/Plivo/Vonage |
| Turn taking | `CallbackUserMuteStrategy`, `ProvisionalVADUserTurnStartStrategy`, external-turn strategy fixes |
| Core | `PipelineWorker` gains `conversation_parent_context` / `conversation_type` / `wait_for_observers()`; `TurnTrackingObserver` becomes mute-aware and emits four new sync events |
| Utils | `utils/run_context.py` (`run_id_var` / `org_id_var` / `turn_var` contextvars), Langfuse tracing helpers, `EndTaskReason` enum, XML function-tag filter |
| Test harness | `src/pipecat/tests/` — `MockTransport`, `MockLLMService`, `MockTTSService` |

> Note this repo is *itself* a fork of `dograh-hq/dograh`; the SaaS-layer deltas are tracked in
> [`saas/docs/FORK.md`](../saas/docs/FORK.md) and [`saas/docs/CHANGES.md`](../saas/docs/CHANGES.md).

---

## 4. The pipeline

### 4.1 Where it is assembled

[api/services/pipecat/pipeline_builder.py](../api/services/pipecat/pipeline_builder.py) is the only
place processor order is decided.

- `create_pipeline_components(audio_config)` — [:13](../api/services/pipecat/pipeline_builder.py#L13) — makes the `AudioBufferProcessor` (recording) and the shared `LLMContext`.
- `build_pipeline(...)` — [:28](../api/services/pipecat/pipeline_builder.py#L28) — the cascaded STT→LLM→TTS pipeline.
- `build_realtime_pipeline(...)` — [:97](../api/services/pipecat/pipeline_builder.py#L97) — speech-to-speech.
- `create_pipeline_task(...)` — [:155](../api/services/pipecat/pipeline_builder.py#L155) — wraps it in a `PipelineWorker`.

**Cascaded order:**

```
transport.input()
  → stt
  → [voicemail_detector.detector()]      # optional
  → user_context_aggregator
  → [voicemail_detector.llm_gate()]      # optional
  → llm
  → PipelineEngineCallbacksProcessor
  → [RecordingRouterProcessor]           # optional — pre-recorded audio vs TTS
  → tts
  → transport.output()
  → audio_buffer                         # records both directions
  → assistant_context_aggregator
  → PipelineMetricsAggregator
```

The voicemail detector deliberately sits **before** `user_context_aggregator` so classification does
not trigger main-LLM completions, and its TTS `gate()` is deliberately **not** used so speech keeps
flowing during classification ([:59-64](../api/services/pipecat/pipeline_builder.py#L59-L64)).

**Realtime (speech-to-speech) order** is asymmetric — no STT, no TTS, and the detector sits *below*
the LLM:

```
transport.input() → user_context_aggregator → realtime_llm
  → [voicemail_detector.detector()] → PipelineEngineCallbacksProcessor → transport.output()
  → audio_buffer → assistant_context_aggregator → PipelineMetricsAggregator
```

### 4.2 Task and runner

`create_pipeline_task` builds a `PipelineWorker` with metrics, usage metrics and heartbeats enabled,
`conversation_id = str(workflow_run_id)`, and tracing on. `run_pipeline_worker(worker)`
([api/services/pipecat/worker_runner.py:7](../api/services/pipecat/worker_runner.py#L7)) runs it via
`WorkerRunner(handle_sigint=False, handle_sigterm=False)` and blocks for the whole call.

### 4.3 Dograh's own frame processors

Only four exist:

| Class | File | Job |
|---|---|---|
| `PipelineEngineCallbacksProcessor` | [pipeline_engine_callbacks_processor.py:18](../api/services/pipecat/pipeline_engine_callbacks_processor.py#L18) | Enforces `max_call_duration_seconds` on each `HeartbeatFrame`; fires the generation-started callback; feeds LLM text to the engine for TTS-aggregation correction |
| `PipelineMetricsAggregator` | [pipeline_metrics_aggregator.py:22](../api/services/pipecat/pipeline_metrics_aggregator.py#L22) | Accumulates LLM tokens, TTS chars, STT seconds, call duration → `usage_info` |
| `RecordingRouterProcessor` | [recording_router_processor.py:38](../api/services/pipecat/recording_router_processor.py#L38) | Buffers streaming text until it sees marker `▸` (speak via TTS) or `●` (play a cached recording, suppress TTS) |
| `_TextChatCaptureProcessor` | [text_chat_runner.py:211](../api/services/workflow/text_chat_runner.py#L211) | Text-chat-only output capture |

### 4.4 Observers

| Observer | File | Job |
|---|---|---|
| `RealtimeFeedbackObserver` | [realtime_feedback_observer.py:74](../api/services/pipecat/realtime_feedback_observer.py#L74) | Streams live transcripts, bot text, function-call start/end, TTFB and errors to the UI WebSocket + an in-memory log buffer. Bot text is captured *after* the output transport so UI text tracks the audio clock. |
| `TranscriptLogCoordinator` | [transcript_log_coordinator.py:51](../api/services/pipecat/transcript_log_coordinator.py#L51) | Subscribes to the fork's turn events and emits immutable per-turn transcripts |
| `PaygentCollector` | [api/services/integrations/paygent/collector.py:496](../api/services/integrations/paygent/collector.py#L496) | Integration-specific collection |
| pipecat built-ins | — | `turn_tracking_observer`, `turn_trace_observer`, `user_bot_latency_observer` |

Feedback event types are enumerated in the fork:
[pipecat/src/pipecat/utils/enums.py](../pipecat/src/pipecat/utils/enums.py) → `RealtimeFeedbackType`.

### 4.5 Service selection

[api/services/pipecat/service_factory.py](../api/services/pipecat/service_factory.py) has one factory
per role, each wrapped in `@_report_service_factory_failures(...)` so a constructor failure is
attributed to the right config section:

- `create_stt_service` — Deepgram (incl. Flux), Cartesia, ElevenLabs, AssemblyAI, Gladia, Google, Azure, OpenAI, Sarvam, Speechmatics, Smallest, Speaches, HuggingFace, Dograh
- `create_tts_service`, `create_llm_service`, `create_llm_service_with_model_override`
- `create_realtime_llm_service` — OpenAI Realtime, Azure Realtime, Grok, Gemini Live, Gemini Live on Vertex, Ultravox

SaaS-fork additions: [vertex_llm.py](../api/services/pipecat/vertex_llm.py) (Gemini / Anthropic /
OpenAI-compatible MaaS routing on Vertex) and
[vertex_anthropic_llm.py](../api/services/pipecat/vertex_anthropic_llm.py) (Claude via
`AsyncAnthropicVertex`).

Which provider is used is resolved per call from org config + per-workflow overrides —
see [`app-doc/per-agent-model-overrides.md`](./per-agent-model-overrides.md).

### 4.6 Transports

| Family | Transport | Notes |
|---|---|---|
| Telephony (7 carriers) | `FastAPIWebsocketTransport` + a per-provider `FrameSerializer` | Twilio, Telnyx, Plivo, Vonage, Vobiz, Cloudonix, Asterisk ARI. Registry-driven — [api/services/telephony/registry.py](../api/services/telephony/registry.py) |
| Browser / embed | `SmallWebRTCTransport` | [transport_setup.py:15](../api/services/pipecat/transport_setup.py#L15). **smallwebrtc, not Daily/LiveKit.** |
| Text chat | none — a `_TaskQueueProxy` stands in for a transport | [text_chat_runner.py](../api/services/workflow/text_chat_runner.py) |

Sample rates flow from `ProviderSpec.transport_sample_rate` (8 kHz Twilio, 16 kHz Vonage, …) into
`AudioConfig` ([audio_config.py:14](../api/services/pipecat/audio_config.py#L14)); the pipeline itself
is capped at 16 kHz for VAD and the transports resample.

---

## 5. Starting a call

Every start path converges on the same three steps: **create a `WorkflowRun` → get the media onto a
WebSocket → call `run_pipeline_*`.** All routes are mounted under `/api/v1`.

### 5.1 The five entry points

| Path | Route | Run name |
|---|---|---|
| Outbound test call (dashboard) | `POST /telephony/initiate-call` — [telephony.py:88](../api/routes/telephony.py#L88) | `WR-TEL-OUT-…` |
| Outbound via public API key | `POST /public/agent/{uuid}` and 3 variants — [public_agent.py:427](../api/routes/public_agent.py#L427) | `WR-API-…` / `WR-TEST-…` |
| Outbound via campaign | `CampaignCallDispatcher.dispatch_call` — [campaign_call_dispatcher.py:214](../api/services/campaign/campaign_call_dispatcher.py#L214) | `WR-CAMPAIGN-…` |
| Inbound from a carrier | `POST /telephony/inbound/run` — [telephony.py:787](../api/routes/telephony.py#L787) | `WR-TEL-IN-…` |
| Browser / website embed | `POST /workflow/{id}/runs` + `WS /ws/signaling/…` — [webrtc_signaling.py](../api/routes/webrtc_signaling.py) | — |

Plus `WS /agent-stream/{provider}/{workflow_uuid}` ([agent_stream.py:34](../api/routes/agent_stream.py#L34))
for PBX-driven inbound (`WR-AGS-…`).

### 5.2 Outbound, step by step

Using the dashboard test call as the reference implementation
([`initiate_call`](../api/routes/telephony.py#L88)):

1. **Resolve the telephony config** — explicit id, else the org default. `provider.validate_config()`.
2. **Acquire an org concurrency slot** — `call_concurrency.acquire_org_slot(..., timeout=0)`; 429 if
   the org is at its limit.
3. **Create the `WorkflowRun`** — `prepare_workflow_run_inputs(...)`
   ([run_creation.py:18](../api/services/workflow/run_creation.py#L18)) **pins a definition version**
   onto the run (`definition_id`): the *draft* for test calls, the *released* definition for
   production. `initial_context` is seeded with `phone_number`, `called_number`,
   `direction`, `provider`, `telephony_configuration_id`.
4. **Bind the slot to the run** — `bind_workflow_run(slot, run_id)`. Slots are accounted per
   `workflow_run_id`, not per socket; a second bind raises `WorkflowRunSlotAlreadyBoundError` (409).
5. **Quota check** — `authorize_workflow_run_start(...)`, deliberately *after* run creation so hosted
   billing can mint its correlation id. Failure → `mark_workflow_run_failed` + release slot + 402.
6. **Dial** — `provider.initiate_call(to, webhook_url, run_id, from_number, …)`. The webhook URL is
   `{backend}/api/v1/telephony/{provider.WEBHOOK_ENDPOINT}?workflow_id=…&workflow_run_id=…&organization_id=…`.
7. **Carrier answers → hits our answer webhook** (`/telephony/twiml`, `/plivo-xml`, `/ncco`, …), whose
   only job is to reply with markup saying *"open a media WebSocket to `wss://…`"*. The URL is signed
   by [ws_auth.build_media_ws_url](../api/services/telephony/ws_auth.py).

### 5.3 Inbound, step by step

[`handle_inbound_run`](../api/routes/telephony.py#L787) is provider-agnostic:

1. `_detect_provider(...)` ([:352](../api/routes/telephony.py#L352)) fingerprints the webhook by asking
   every registered provider `can_handle_webhook(...)` (headers, User-Agent, ID prefixes).
2. Normalize to a `NormalizedInboundData` ([base.py:78](../api/services/telephony/base.py#L78)).
3. **One query routes the call**: `find_inbound_route_by_account(provider, account_id, to_number, …)`
   returns the config *and* the phone-number row — the org is derived from that row, which is what
   enforces tenant isolation.
4. The workflow comes from `phone_row.inbound_workflow_id`.
5. Verify the provider signature against the matched config's credentials.
6. Slot → run (`_create_inbound_workflow_run`, [:465](../api/routes/telephony.py#L465)) → bind → quota.
7. `provider.start_inbound_stream(...)` replies with the same "open a media stream" markup.

A fallback route `POST /telephony/inbound/fallback` returns a provider-specific "system unavailable"
hangup response.

### 5.4 The media WebSocket

```
WS /api/v1/telephony/ws/{workflow_id}/{organization_id}/{workflow_run_id}[/{token}]
```
[telephony.py:587-589](../api/routes/telephony.py#L587-L589) — declared twice because some carriers
strip query strings, so the capability token also has a path form.
[`_handle_telephony_websocket`](../api/routes/telephony.py#L611):

1. Validate the HMAC capability token (`TELEPHONY_WS_TOKEN_SECRET`, enforced by
   `TELEPHONY_WS_TOKEN_ENFORCE`) → close 4401.
2. Load run + workflow **scoped by `organization_id`** → 4404 / 4400.
3. **State gate**: the run must still be `INITIALIZED`, else close 4409. This is what stops replay.
4. Cross-check the provider recorded in `initial_context`.
5. `update_workflow_run(state=RUNNING)`.
6. `provider.handle_websocket(...)` → provider handshake (e.g. Twilio waits for `connected` then
   `start`, pulls `streamSid`/`callSid`) → `run_pipeline_telephony(..., transport_kwargs=…)`.

### 5.5 `_run_pipeline_impl` — the composition root

[api/services/pipecat/run_pipeline.py:549](../api/services/pipecat/run_pipeline.py#L549). Ordered:

1. Reject an already-completed run.
2. Merge `workflow_run.initial_context` with caller-supplied `call_context_vars`
   (`merge_external_initial_context` — refuses to let callers overwrite `provider`,
   `runtime_configuration`, or the billing correlation id).
3. **Read the pinned definition** (`workflow_run.definition.workflow_json`) — never the workflow's
   current draft. This is what makes runs reproducible.
4. Extract run configs: `max_call_duration`, `max_user_idle_timeout`, STT `dictionary` keyterms,
   transcript options.
5. Resolve the effective model config (org + per-workflow overrides).
6. Build the `WorkflowGraph` from the ReactFlow DTO.
7. Create services (STT/TTS/LLM, or a realtime service + a separate text LLM for inference, plus a
   dedicated variable-extraction LLM on the managed provider).
8. Persist `initial_context["runtime_configuration"]` — the resolved provider/model triple, for
   post-call analytics.
9. Fire the **pre-call fetch** as a background task if the Start node enables it for this direction.
10. Construct `PipecatEngine`.
11. Choose turn-taking strategies (§9.3), mute strategies, VAD.
12. Add the callbacks processor, metrics aggregator, idle handlers, optional voicemail detector,
    optional recording router.
13. `build_pipeline` → `create_pipeline_task` → attach transcript coordinator, integrations,
    feedback observer → `engine.initialize()` → `register_event_handlers` →
    `register_audio_data_handler`.
14. `await run_pipeline_worker(task)` — blocks for the call.
15. `finally:` close MCP sessions (must happen in the same task that opened them — anyio cancel-scope
    affinity) and clean up the observer.

### 5.6 When does the agent actually speak first?

[`maybe_trigger_initial_response`](../api/services/pipecat/event_handlers.py#L105) — the conversation
starts only once **both** `on_pipeline_started` and `on_client_connected` have fired. If a pre-call
fetch is still in flight it plays a **ringer loop as filler**, merges the fetched variables into the
call context, and only then calls `engine.set_node(start_node_id)` +
`engine.queue_node_opening(..., generate_if_no_greeting=True)`.

### 5.7 The run record

`WorkflowRunModel` — [api/db/models.py:524](../api/db/models.py#L524), table `workflow_runs`.

Notable columns: `definition_id` (pinned version), `mode` (provider name / `smallwebrtc` / `textchat`),
`call_type` (`inbound|outbound`), `state` (`initialized|running|completed`), `is_completed`,
`recording_url`, `transcript_url`, `extra` (per-track recording metadata), `storage_backend`,
`usage_info`, `cost_info`, `initial_context`, `gathered_context`, `logs`, `annotations`,
`campaign_id`, `queued_run_id`, `public_access_token`.

**State machine:** `initialized` (any start path) → `running` (WS accepted / signaling connected) →
`completed`. There is no `failed` state — failures are `completed` plus `gathered_context["error"]`.

All JSON columns **merge** rather than replace on update
([workflow_run_client.py:339](../api/db/workflow_run_client.py#L339), which also takes a
`SELECT … FOR UPDATE`).

---

## 6. The agent brain — `PipecatEngine` and the workflow graph

[api/services/workflow/pipecat_engine.py](../api/services/workflow/pipecat_engine.py) (~1140 lines) is
the class that makes a graph behave like an agent.

### 6.1 Node types

[api/services/workflow/dto.py:25](../api/services/workflow/dto.py#L25):

| `NodeType` | Value | Conversational? | Carries tools? |
|---|---|---|---|
| `startNode` | `startCall` | yes | **yes** |
| `agentNode` | `agentNode` | yes | **yes** |
| `endNode` | `endCall` | yes (terminal) | no (extraction only) |
| `globalNode` | `globalNode` | prompt fragment only | no |
| `trigger` | `trigger` | no — API entry point | no |
| `webhook` | `webhook` | no — post-call HTTP push | no |
| `qa` | `qa` | no — post-call LLM scoring | no |

Node data models are composed from mixins ([dto.py:110-180](../api/services/workflow/dto.py#L110-L180)):
`_PromptedNodeDataMixin` (`prompt`, `allow_interrupt`, `add_global_prompt`),
`_ExtractionNodeDataMixin` (`extraction_enabled`, `extraction_prompt`, `extraction_variables`),
`_ToolDocumentRefsMixin` (`tool_uuids`, `document_uuids`, `mcp_tool_filters`).

Integration node types plug in through `api/services/integrations/` via `get_node_data_model`.

### 6.2 Graph validation

`ReactFlowDTO` ([dto.py:1070](../api/services/workflow/dto.py#L1070)) validates referential integrity;
`RFNodeDTO._validate` resolves the right data model per node `type` and requires a prompt on the four
conversational types. `sanitize_workflow_definition` strips UI-only keys before persistence.

`WorkflowGraph` ([workflow_graph.py:222](../api/services/workflow/workflow_graph.py#L222)) then builds
`Node`/`Edge` objects and runs `_validate_graph`:

- instance-count constraints per node spec (`min_instances` / `max_instances`)
- connection-count constraints (`min/max_incoming`, `min/max_outgoing`)
- `validate_unique_transition_tool_names` — two edges out of one node whose labels slugify identically
- **`_assert_acyclic` exists but is commented out — cycles are allowed.**

The single source of truth for "is this workflow valid" is `_validate_workflow_definition`
([api/routes/workflow.py:158](../api/routes/workflow.py#L158)), which also checks trigger paths and
cross-namespace tool-name collisions.

### 6.3 Node entry — the rebuild

`set_node(node_id)` — [pipecat_engine.py:614](../api/services/workflow/pipecat_engine.py#L614):

1. Set `_current_node`, append its name to `gathered_context["nodes_visited"]`.
2. Fire the node-transition callback (streamed to the UI as `rtf-node-transition`).
3. Dispatch to `_handle_start_node` / `_handle_end_node` / `_handle_agent_node` — all three ultimately
   call `_setup_llm_context(node)`.
4. Kick off background context summarization if enabled.

`_setup_llm_context` — [:571](../api/services/workflow/pipecat_engine.py#L571):

1. Register one **transition function per outgoing edge** (`_register_transition_function_with_llm`).
2. Register the node's custom / MCP tool handlers.
3. Register the knowledge-base tool if the node references documents.
4. `compose_system_prompt_for_node(...)`
5. `compose_functions_for_node(...)`
6. `_update_llm_context(system_prompt, functions)`

### 6.4 How prompt + tools reach the LLM

[pipecat_engine_context_composer.py:49](../api/services/workflow/pipecat_engine_context_composer.py#L49):

```
system_prompt =
      global node prompt        (only if workflow has a global node AND node.add_global_prompt)
  +   node.prompt
  +   RECORDING_RESPONSE_MODE_INSTRUCTIONS   (only if org has recordings AND the prompt mentions RECORDING_ID:)
```
…each fragment rendered through `render_template(prompt, self._call_context_vars)`.

`compose_functions_for_node` ([:86](../api/services/workflow/pipecat_engine_context_composer.py#L86))
returns, in order: KB tool → custom/MCP tool schemas → one schema per outgoing edge (the edge's
**label** becomes the function name, the edge's **condition** becomes the function description).

`_update_llm_context` ([:229](../api/services/workflow/pipecat_engine.py#L229)) then does:

```python
if functions:
    self.context.set_tools(ToolsSchema(standard_tools=functions))
await self.llm._update_settings(LLMSettings(system_instruction=system_prompt))
```

> **Gotcha:** that `if functions:` means a node with *zero* functions (a terminal `endCall`) does not
> clear the tool list — the previous node's tools stay advertised.

### 6.5 A transition, in slow motion

`_create_transition_func` — [pipecat_engine.py:248](../api/services/workflow/pipecat_engine.py#L248).
When the LLM calls an edge function:

1. **Extract variables from the node being left** (`_perform_variable_extraction_if_needed`).
2. **Play transition speech** — either a pre-recorded clip or a `TTSSpeakFrame` with
   `append_to_context=False`. This is Dograh's filler-word mechanism: it covers LLM latency but is
   deliberately *not* added to the conversation context.
3. `await self.set_node(target)` — prompt and tools swap **before** the function result is returned.
4. `result_callback({"status": "done"}, properties=FunctionCallResultProperties(on_context_updated=…))`
   — the next generation only runs once the result is in context. If the new node `is_end`, the
   `on_context_updated` hook calls `end_call_with_reason(USER_QUALIFIED)`.

Transition functions are registered with `is_node_transition=True`, which in the fork makes pipecat
broadcast a `NodeTransitionStartedFrame` and gate on context aggregation — an ordering guarantee that
prevents the model answering with the old node's tools.

---

## 7. Tools — what the agent can actually call

### 7.1 The complete function namespace

There are exactly **five** `llm.register_function(...)` call sites in the backend:

| Registered name | Site | What |
|---|---|---|
| `<slugified edge label>` | [pipecat_engine.py:374](../api/services/workflow/pipecat_engine.py#L374) | Node transition |
| `retrieve_from_knowledge_base` | [pipecat_engine.py:431](../api/services/workflow/pipecat_engine.py#L431) | RAG lookup over attached documents |
| `safe_calculator` | [pipecat_engine_custom_tools.py:394](../api/services/workflow/pipecat_engine_custom_tools.py#L394) | Built-in arithmetic |
| `mcp__<server-slug>__<tool>` | [pipecat_engine_custom_tools.py:282](../api/services/workflow/pipecat_engine_custom_tools.py#L282) | One per tool on a connected MCP server |
| `<slugified tool name>` | [pipecat_engine_custom_tools.py:306](../api/services/workflow/pipecat_engine_custom_tools.py#L306) | HTTP API / End Call / Transfer Call tools |

### 7.2 The honest answer about "hidden tools"

**There are no always-on ambient tools.** `end_call` and `transfer_call` are *not* built-in
capabilities the model always has — they are user-created `ToolModel` rows with a category, attached to
a node via `data.tool_uuids`, exactly like an HTTP tool. If no node on the path references an
end-call tool, the model has no way to hang up other than reaching an `endCall` node.

The only genuinely auto-injected tool lives in the pipecat fork —
`cancel_async_tool_call` ([pipecat/src/pipecat/utils/async_tool_cancellation.py:17](../pipecat/src/pipecat/utils/async_tool_cancellation.py#L17)),
injected only when a function is registered with `cancel_on_interruption=False`. Dograh never does
that, so in practice it never appears.

`ToolCategory` ([api/enums.py:169](../api/enums.py#L169)) also declares `NATIVE` and `INTEGRATION`,
but **neither has a runtime implementation** — `NATIVE` is the placeholder for future DTMF input
(the UI shows it disabled as "Native (Coming Soon)"). Likewise
[api/services/workflow/tools/timezone.py](../api/services/workflow/tools/timezone.py) defines
`get_current_time` / `convert_time` but **nothing imports it**; time is exposed as template variables
instead (§8.3). Appointment booking is not a built-in either — it is modeled as an HTTP tool or MCP.

### 7.3 Tool definitions

Discriminated union on `type` — [api/schemas/tool.py:529](../api/schemas/tool.py#L529):

| Type | Config highlights |
|---|---|
| `http_api` | `method`, `url`, `headers`, `credential_uuid`, `parameters` (LLM-supplied), `preset_parameters` (Dograh-injected via `value_template`), `body_template`, `timeout_ms`, optional spoken "one moment" message |
| `end_call` | `messageType` (`none|custom|audio`), `customMessage`, `audioRecordingId`, `endCallReason` (adds a required `reason` argument the model must supply) |
| `transfer_call` | `destination_source` (`static|dynamic|context_mapping`), `destination`, `timeout` (5–120 s), `resolver` (HTTP), `context_mapping` (ordered rules + fallback) |
| `calculator` | no config |
| `mcp` | `transport: streamable_http`, `url`, `credential_uuid`, `tools_filter`, timeouts, cached `discovered_tools` |

`tool_to_function_schema` ([custom_tool.py:60](../api/services/workflow/tools/custom_tool.py#L60))
turns a definition into an LLM schema. Two behaviours worth knowing:

- a **static** transfer exposes **no parameters at all** to the model, whatever is configured;
- a **dynamic** transfer's parameters come from the *resolver* config, not the tool's own list.

### 7.4 Execution

`CustomToolManager` ([pipecat_engine_custom_tools.py:94](../api/services/workflow/pipecat_engine_custom_tools.py#L94))
builds schemas and handlers, and picks a per-category timeout.

**HTTP tool** — `execute_http_tool` ([custom_tool.py:277](../api/services/workflow/tools/custom_tool.py#L277)):

1. headers from config + `build_auth_header(credential)` when a `credential_uuid` is set
2. resolve `preset_parameters` by rendering `value_template` against initial + gathered context
3. `resolved_arguments = {**preset_arguments, **llm_arguments}` — **the LLM wins on conflict**
4. URL render precedence: `preset < initial_context < gathered_context < llm_arguments`
5. `validate_user_configured_service_url` — SSRF guard
6. JSON body (type-preserving when a `body_template` value is exactly one placeholder), or query params
7. returns `{"status": "success"|"error", …}`; failures classified through [api/errors/failure.py](../api/errors/failure.py)

**End call** — writes `gathered_context["call_disposition"]` from the model-supplied reason, appends
the `end_call_tool` tag, plays the goodbye, then calls `end_call_with_reason(END_CALL_TOOL_REASON)`
with `abort_immediately=False` if a message played (so the audio drains) or `True` if not.

**Transfer** — the longest path in the codebase
([pipecat_engine_custom_tools.py:558](../api/services/workflow/pipecat_engine_custom_tools.py#L558)):
rejects text-chat and WebRTC modes; flushes variable extraction for context-mapped routing; plays a
wait message; resolves the destination
([transfer_resolver.py:410](../api/services/workflow/tools/transfer_resolver.py#L410) — static /
context-mapping / HTTP resolver); stores a `TransferContext` in Redis; mutes the pipeline; calls
`provider.transfer_call(...)`; **plays hold music in a loop** while blocking on a Redis pub/sub wait
for completion. On `destination_answered` → `end_call_with_reason(TRANSFER_CALL)`; on failure the
result goes *back to the model* so the agent can explain. External PBX (VICIdial) takes a separate
branch that maps gathered context onto lead fields first.

**MCP** — sessions are opened **once per call** for every MCP tool referenced by *any* node
(`_open_mcp_sessions`, [pipecat_engine.py:1042](../api/services/workflow/pipecat_engine.py#L1042)) and
closed in `close_mcp_sessions` — not in `cleanup()`, because anyio cancel scopes are task-affine. A
failed server degrades to `available=False` and never raises. Per-node allowlisting via
`mcp_tool_filters: {tool_uuid: [names]}` (`None` = all, `[]` = none).

**Knowledge base** — [tools/knowledge_base.py](../api/services/workflow/tools/knowledge_base.py):
one `query: string` parameter, embedding + pgvector search, top 3 chunks.

### 7.5 Name-collision rules

Function names must be unique within a node's namespace. Three checks:
edge-vs-edge ([workflow_graph.py:24](../api/services/workflow/workflow_graph.py#L24)), tool-vs-tool and
edge-vs-tool ([tool_name_validation.py:18](../api/services/workflow/tool_name_validation.py#L18)).
Calculator and MCP are exempt because their names are derived at runtime.

---

## 8. Context and variables

### 8.1 Two dictionaries, and the difference matters

| | `_call_context_vars` | `_gathered_context` |
|---|---|---|
| Initialized | [pipecat_engine.py:103](../api/services/workflow/pipecat_engine.py#L103) from the merged initial context | [:112](../api/services/workflow/pipecat_engine.py#L112), starts empty |
| Filled by | `workflow_run.initial_context`, caller-supplied `call_context_vars`, pre-call fetch, `runtime_configuration` | LLM variable extraction, nodes visited, disposition, tags |
| Consumed by | **node prompts, greetings, transition speech** (`render_template(prompt, _call_context_vars)`) | HTTP tool presets / URL / body, transfer routing, webhooks, post-call analytics |

> **The most important gotcha in the system: extracted variables do NOT reach node prompts.**
> `_format_prompt` renders against `_call_context_vars` only, and nothing merges gathered → call
> context. `{{gathered_context.x}}` inside a node prompt renders empty. Extracted values influence
> later turns only *implicitly* (the transcript is already in the context window) and *explicitly*
> through tool arguments, tool URLs/bodies, transfer routing, and webhook payloads.

### 8.2 Where the initial context comes from

- `merge_external_initial_context` ([initial_context.py:17](../api/services/workflow/initial_context.py#L17))
  merges caller-supplied vars but blocks `RESERVED_INITIAL_CONTEXT_KEYS` — `provider`,
  `runtime_configuration`, and the billing correlation id — so an external caller cannot spoof
  run-owned metadata.
- **Pre-call fetch** ([pre_call_fetch.py:53](../api/services/pipecat/pre_call_fetch.py#L53)) — an HTTP
  GET fired at pipeline start when the Start node enables it for this direction
  (`disabled|always|inbound|outbound`). Its response (`initial_context`, or legacy
  `dynamic_variables`, at top level or under `call_inbound`) is merged into
  `engine._call_context_vars` **before** the first `set_node`, with ringer audio as filler.
- `greeting_override` (text or audio) can be passed per call and beats the Start node's greeting.

### 8.3 Template rendering

[api/utils/template_renderer.py](../api/utils/template_renderer.py). Syntax `{{ path | filter:value }}`.

- dotted paths via `get_nested_value`; both `{{x}}` and `{{initial_context.x}}` resolve
- built-ins: `current_time`, `current_time_<IANA_TZ>`, `current_weekday`, `current_weekday_<TZ>` —
  and `{{current_weekday}}` inherits the timezone from a sibling `current_time_<TZ>` in the same prompt
- fallbacks: `{{var | default}}`, legacy `{{var | fallback:default}}`
- `render_url_template` percent-encodes, rejects arrays/objects/empties, and forbids scheme changes

`WorkflowGraph.get_required_template_variables()` scans prompts, greetings and transition speech for
`{{var}}` — that's how a campaign CSV knows which columns it must supply.

### 8.4 Variable extraction

Configured per node: `extraction_enabled`, `extraction_prompt`, `extraction_variables[{name,type,prompt}]`.

- Runs **before** leaving a node (from the transition function), in the background by default; text
  chat forces it synchronous.
- Writes to **both** `gathered_context[name]` and `gathered_context["extracted_variables"][name]`.
- `flush_variable_extraction` is **repeatable** (used by transfers that may fail and resume);
  `perform_final_variable_extraction` is one-shot and guarded.
- The extractor ([pipecat_engine_variable_extractor.py:19](../api/services/workflow/pipecat_engine_variable_extractor.py#L19))
  linearizes the conversation *including tool responses*, drops the noise (`{"status":"done"}`
  transition results, `status`/`status_code` wrappers), truncates at 2000 chars, and calls
  `run_inference` out-of-band on a dedicated LLM so it never disturbs the live turn.

---

## 9. Guardrails — interruption, silence, voicemail, compaction

### 9.1 Barge-in / muting

Three mute strategies are stacked ([run_pipeline.py:885-889](../api/services/pipecat/run_pipeline.py#L885-L889)):
`MuteUntilFirstBotCompleteUserMuteStrategy`, `FunctionCallUserMuteStrategy`, and the fork-only
`CallbackUserMuteStrategy(should_mute_callback=engine.should_mute_user)`.

`should_mute_user` ([pipecat_engine.py:922](../api/services/workflow/pipecat_engine.py#L922)) doubles as
the speaking-state tracker and returns `True` when:

- the pipeline is muted for shutdown/transfer, **or**
- queued transition speech / a tool message is pending or playing, **or**
- the bot is speaking on a node whose `allow_interrupt` is `False`.

`allow_interrupt` is **per node** — default `False` on Start, `True` on Agent. That is the barge-in
control surface.

### 9.2 Silence / idle

`UserIdleHandler` ([pipecat_engine_callbacks.py:31](../api/services/workflow/pipecat_engine_callbacks.py#L31))
escalates in two strikes:

1. appends *"The user has been quiet. Politely and briefly ask if they're still there in the language
   that the user has been speaking so far."*
2. appends a goodbye, then `end_call_with_reason(USER_IDLE_MAX_DURATION_EXCEEDED)`

Timeout comes from the workflow's `max_user_idle_timeout`.

### 9.3 Turn taking

Non-realtime start strategies, selected by `run_configs["turn_start_strategy"]`
([run_pipeline.py:150](../api/services/pipecat/run_pipeline.py#L150)):

| Value | Strategy |
|---|---|
| `min_words` | `MinWordsUserTurnStartStrategy(turn_start_min_words)` |
| `provisional_vad` | `ProvisionalVADUserTurnStartStrategy` (fork-only) |
| (STT owns turns) | `ExternalUserTurnStartStrategy` — local VAD deliberately excluded |
| default | `[TranscriptionUserTurnStartStrategy(), VADUserTurnStartStrategy()]` |

Stop strategies: `ExternalUserTurnStopStrategy`, `TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3)`,
or `SpeechTimeoutUserTurnStopStrategy`. Realtime providers get per-provider configs — Gemini Live keeps
local VAD but disables local interruptions; OpenAI/Azure/Grok go fully external; Ultravox uses local
VAD. User-facing version: [docs/configurations/interruption.mdx](../docs/configurations/interruption.mdx).

### 9.4 Voicemail detection

Driven by `workflow_configurations["voicemail_detection"]` (own LLM or the workflow's, `long_speech_timeout`,
custom system prompt) using the fork's `VoicemailDetector`. On detection →
`end_call_with_reason(VOICEMAIL_DETECTED, abort_immediately=True)`. **Disabled in realtime mode.**

### 9.5 Context compaction

`ContextSummarizationManager` ([pipecat_engine_context_summarizer.py:22](../api/services/workflow/pipecat_engine_context_summarizer.py#L22))
runs in the background after each non-first node transition when
`workflow_configurations["context_compaction_enabled"]` is set. Target 4000 tokens; its real purpose is
purging orphaned tool calls from prior nodes. **Also disabled in realtime mode.**

### 9.6 TTS aggregation correction

`create_aggregation_correction_callback` repairs corrupted TTS word-alignment text (an ElevenLabs
quirk) by two-pointer aligning it against the accumulated LLM reference text that
`PipelineEngineCallbacksProcessor` feeds to the engine.

---

## 10. Ending a call

### 10.1 Every hangup goes through one method

`PipecatEngine.end_call_with_reason(reason, abort_immediately)` —
[pipecat_engine.py:807](../api/services/workflow/pipecat_engine.py#L807).

| Trigger | Where | `EndTaskReason` |
|---|---|---|
| Caller hangs up / transport disconnects | [event_handlers.py:180](../api/services/pipecat/event_handlers.py#L180) | `USER_HANGUP` (abort) |
| Fatal pipeline error | [event_handlers.py:201](../api/services/pipecat/event_handlers.py#L201) | `PIPELINE_ERROR` (abort) |
| Max call duration (checked on each heartbeat) | [pipecat_engine_callbacks.py:75](../api/services/workflow/pipecat_engine_callbacks.py#L75) | `CALL_DURATION_EXCEEDED` (abort) |
| User idle, second strike | [pipecat_engine_callbacks.py:57](../api/services/workflow/pipecat_engine_callbacks.py#L57) | `USER_IDLE_MAX_DURATION_EXCEEDED` (graceful) |
| Voicemail detected | [run_pipeline.py:1016](../api/services/pipecat/run_pipeline.py#L1016) | `VOICEMAIL_DETECTED` (abort) |
| `end_call` tool invoked | [pipecat_engine_custom_tools.py:539](../api/services/workflow/pipecat_engine_custom_tools.py#L539) | `END_CALL_TOOL_REASON` |
| Transfer completed | [pipecat_engine_custom_tools.py:978](../api/services/workflow/pipecat_engine_custom_tools.py#L978) | `TRANSFER_CALL` (graceful) |
| Reached an `endCall` node | [pipecat_engine.py:328](../api/services/workflow/pipecat_engine.py#L328) | `USER_QUALIFIED` |

Reasons are enumerated in the fork:
[pipecat/src/pipecat/utils/enums.py](../pipecat/src/pipecat/utils/enums.py) → `EndTaskReason`.

Inside the method:

1. idempotency guard on `_call_disposed`; `_mute_pipeline = True`
2. unless the reason is `PIPELINE_ERROR` / `VOICEMAIL_DETECTED`, run final variable extraction
   **synchronously**
3. pick `CancelFrame(reason)` (abort) or `EndFrame(reason)` (graceful drain)
4. compute `call_disposition` / `mapped_call_disposition`, append `call_tags`
5. **persist `gathered_context` before queueing the frame** — external-PBX hangup strategies read the
   final lead fields off it
6. `task.queue_frame(frame)`

### 10.2 Killing the carrier leg

The terminal frame reaches the serializer, which dispatches to the fork's strategy abstractions:
`TransferStrategy.execute_transfer` when the reason is `TRANSFER_CALL`, else
`HangupStrategy.execute_hangup`. Twilio's implementations live in
[api/services/telephony/providers/twilio/strategies.py](../api/services/telephony/providers/twilio/strategies.py)
(conference TwiML for transfer; `Status=completed` for hangup, treating 404 as already-terminated).
Same pattern per provider.

### 10.3 In-process post-call work

`on_pipeline_finished` — [event_handlers.py:235](../api/services/pipecat/event_handlers.py#L235), in order:

1. `task.wait_for_observers()` then flush the transcript coordinator — drain before snapshotting
2. `audio_buffer.stop_recording()`
3. snapshot `gathered_context`, add the Langfuse `trace_url`
4. call tags: `user_speech` if the caller ever spoke; promote any `tag_*` keys into `call_tags`
5. register the disposition code on the workflow (so it appears in run filters)
6. run integration `on_call_finished` hooks
7. `usage_info = pipeline_metrics_aggregator.get_all_usage_metrics_serialized()` — LLM tokens per
   model, TTS chars, STT seconds, call duration
8. **`update_workflow_run(usage_info, gathered_context, is_completed=True, state=COMPLETED)`**
9. PostHog `call_completed`
10. save realtime-feedback events + integration logs into `logs`
11. **upload artifacts** (§10.4)
12. **enqueue `process_workflow_completion`**

Audio never touches disk during the call — it accumulates in `InMemoryRecordingBuffers`.

### 10.4 Artifacts

[api/services/workflow_run_artifacts.py:46](../api/services/workflow_run_artifacts.py#L46) uploads
straight from memory to S3/MinIO:

| Key | Sets |
|---|---|
| `recordings/{run_id}.wav` (mixed) | `recording_url`, `storage_backend` |
| `recordings/{run_id}/user.wav`, `/bot.wav` | `extra["recordings"][track]` |
| `transcripts/{run_id}.txt` | `transcript_url` |

Each is independent — one failure doesn't block the others. Deliberately runs *before* the ARQ job so
QA and webhooks can see the files.

### 10.5 Calls that never connected

Carrier status callbacks land in `_process_status_update`
([status_processor.py:113](../api/services/telephony/status_processor.py#L113)), which is idempotent
(webhook and CDR may both arrive):

- always appends to `logs["telephony_status_callbacks"]`
- `completed` → release the concurrency slot, record circuit-breaker success, mark completed
- `failed|busy|no-answer|canceled|error` → release the slot; circuit-breaker failure for
  `error|failed`; **publish a retry event** for `busy|no-answer` on campaign runs; tag the run
  `not_connected` + `telephony_{status}`; set the disposition
- if the run never left `initialized`, write `usage_info={"call_duration_seconds": …}` and enqueue
  **only** `run_integrations_post_workflow_run` — deliberately *not* `process_workflow_completion`, so
  an unconnected call still fires webhooks without incurring platform billing
- `initiated|ringing|in-progress|answered` → no-op

Pre-pipeline failures (quota rejected, dial threw) go through `mark_workflow_run_failed`
([workflow_run_failure.py:25](../api/services/workflow_run_failure.py#L25)), which also writes a
synthetic pipeline-error feedback event so the run page shows *something*.

**Two distinct paths write `state=COMPLETED`** — `on_pipeline_finished` for connected calls, and
`_process_status_update` for calls that never connected. They are mutually guarded by state checks.

### 10.6 Slot release — five safety nets

1. the `finally` in `run_pipeline_telephony` / `run_pipeline_smallwebrtc` (the normal path)
2. `campaign_call_dispatcher.release_call_slot(run_id)` on any terminal carrier status (also returns
   the `from_number` to the pool)
3. `ARIConnection._handle_stasis_end` for Asterisk
4. a Redis stale-slot timeout in [api/services/call_concurrency/rate_limiter.py](../api/services/call_concurrency/rate_limiter.py)
5. the `finally` in the agent-stream WebSocket

Drain/autoscale surface: `GET /api/v1/health/active-calls` (per worker) and
`GET /api/v1/health/autoscale-metric` (fleet-wide), both behind `X-Dograh-Devops-Secret`.

---

## 11. Post-call background work (ARQ)

[api/tasks/arq.py](../api/tasks/arq.py) — `WorkerSettings`, `max_jobs=10`, `enqueue_job()`.

| Job | Impl | Role |
|---|---|---|
| `process_workflow_completion` | [workflow_completion.py:10](../api/tasks/workflow_completion.py#L10) | Main post-call job: run integrations, then report platform usage for billing |
| `run_integrations_post_workflow_run` | [run_integrations.py:174](../api/tasks/run_integrations.py#L174) | QA scoring + integrations + webhooks |
| `deliver_webhook` | [webhook_delivery.py](../api/tasks/webhook_delivery.py) | Durable retrying HTTP delivery |
| `sync_campaign_source` / `process_campaign_batch` | [campaign_tasks.py](../api/tasks/campaign_tasks.py) | Campaign CSV sync / batch dialing |
| `process_knowledge_base_document` | [knowledge_base_processing.py](../api/tasks/knowledge_base_processing.py) | KB ingestion (not call-path) |
| `complete_inactive_text_chat_session` | [text_chat_inactivity.py](../api/tasks/text_chat_inactivity.py) | Text-chat analogue of hangup |

Cron: `sweep_webhook_deliveries` every 5 min (re-enqueues deliveries lost to worker restarts),
`sweep_inactive_text_chat_sessions`.

`run_integrations_post_workflow_run`, step by step:

1. load the run + org, register the org's Langfuse credentials
2. read the **pinned** definition; partition nodes into `qa` and `webhook`
3. early-out if there is nothing to do and no campaign
4. mint the `public_access_token` used for public recording/transcript links
5. **QA analysis** per `qa` node, gated by min call duration, a voicemail toggle, and a sample rate;
   results land in `annotations`, QA LLM tokens are folded back into `usage_info`
6. integration completion handlers → merged into `annotations`
7. **webhook nodes** — build the render context (`workflow_run_id`, `workflow_name`, `campaign_id`,
   `call_time`, `initial_context`, `gathered_context`, usage, `annotations`, `extra`, plus signed
   download URLs), render the payload template, persist a `WebhookDeliveryModel` row idempotent on
   `(workflow_run_id, webhook_node_id)`, enqueue `deliver_webhook`

**Cost note:** there is no local rating engine. `workflow_runs.cost_info` is never written by `api/`,
and `TelephonyProvider.get_call_cost` is implemented by every provider but has **no call sites** —
both are latent surface for future carrier-cost reconciliation. Credit accounting lives in the
managed platform service ([workflow_run_billing.py](../api/services/workflow_run_billing.py)).

---

## 12. Campaigns (agents at scale)

Models: `CampaignModel` ([models.py:687](../api/db/models.py#L687)) — states
`created|syncing|running|paused|completed|failed`, `rate_limit_per_second`, `retry_config`,
`orchestrator_metadata` (max concurrency, schedule window, parent campaign);
`QueuedRunModel` ([models.py:793](../api/db/models.py#L793)) — one row per contact,
`queued|processing|processed|failed`.

```
POST /campaign/{id}/start
   → state=syncing, enqueue sync_campaign_source
        → CSV parsed into queued_runs, state=running, publish SyncCompletedEvent (Redis)
             → CampaignOrchestrator (standalone process) schedules PROCESS_CAMPAIGN_BATCH
                  → CampaignCallDispatcher.process_batch
                       claim rows (SELECT FOR UPDATE SKIP LOCKED)
                       → rate limit (token bucket) → concurrency slot → dispatch_call
                            → acquire a unique from_number from the pool
                            → create WorkflowRun → bind slot → quota → provider.initiate_call
                  ◄── BatchCompletedEvent schedules the next batch
```

- **Orchestrator** — [campaign_orchestrator.py:41](../api/services/campaign/campaign_orchestrator.py#L41),
  subscribed to the Redis `campaign_events` channel, plus a stale-campaign sweep. Enforces the
  schedule window (day-of-week + start/end in the campaign timezone, failing open).
- **Retries** — `busy` / `no-answer` publish a `RetryNeededEvent`; the orchestrator checks
  `retry_config` and schedules a new queued run with `source_uuid + "_retry_N"` and a delay.
- **Circuit breaker** — [circuit_breaker.py](../api/services/campaign/circuit_breaker.py), two Redis
  sliding windows (failures / successes). Tripping pauses the campaign. Fed from the status processor,
  `on_pipeline_error`, and dial failures.
- **Redial** — `POST /campaign/{id}/redial`, once per completed campaign, over unique subscribers
  whose last call was voicemail / no-answer / busy.

---

## 13. Gotchas worth memorising

1. **`end_call` and `transfer_call` are configured tools, not ambient capabilities.** Attach them to a
   node or the agent cannot hang up or transfer.
2. **Extracted variables are not available as `{{...}}` in node prompts** — only in tool preset params,
   tool URLs/bodies, transfer routing, and webhooks (§8.1).
3. **Transition speech is intentionally excluded from the LLM context** (`append_to_context=False`) —
   it is a latency filler, not dialogue.
4. **A node with zero functions does not clear the previously advertised tools** (§6.4).
5. **A static transfer tool exposes no parameters to the LLM**, whatever the config says.
6. **Cycles in the workflow graph are allowed** — the acyclic assertion is commented out.
7. **Voicemail detection and context compaction are silently disabled in realtime mode.**
8. **MCP sessions are per-call and opened for every node's MCP tools up front**, not lazily per node.
9. **`ToolCategory.NATIVE` / `INTEGRATION` and `tools/timezone.py` have no runtime implementation.**
   DTMF-as-a-tool does not exist today.
10. **A run always executes its pinned definition** (`workflow_run.definition_id`), never the
    workflow's current draft.
11. **The media WebSocket URL is a bearer capability** — see the `TODO(security)` at
    [telephony.py:625](../api/routes/telephony.py#L625) and the two-stage rollout via
    `TELEPHONY_WS_TOKEN_SECRET` → `TELEPHONY_WS_TOKEN_ENFORCE`.
12. **Concurrency slots are bound to a `workflow_run_id`, not a socket** — `acquire_org_slot` then
    `bind_workflow_run` is the two-step everywhere.

---

## 14. Read these first

| Goal | File |
|---|---|
| How a call is assembled | [api/services/pipecat/run_pipeline.py](../api/services/pipecat/run_pipeline.py) |
| Processor order, task params | [api/services/pipecat/pipeline_builder.py](../api/services/pipecat/pipeline_builder.py) |
| The agent brain | [api/services/workflow/pipecat_engine.py](../api/services/workflow/pipecat_engine.py) |
| Prompt + tool composition | [api/services/workflow/pipecat_engine_context_composer.py](../api/services/workflow/pipecat_engine_context_composer.py) |
| Tool schemas + handlers | [api/services/workflow/pipecat_engine_custom_tools.py](../api/services/workflow/pipecat_engine_custom_tools.py), [api/services/workflow/tools/](../api/services/workflow/tools/) |
| Graph model + validation | [api/services/workflow/dto.py](../api/services/workflow/dto.py), [api/services/workflow/workflow_graph.py](../api/services/workflow/workflow_graph.py) |
| Provider matrix | [api/services/pipecat/service_factory.py](../api/services/pipecat/service_factory.py) |
| Carrier plug-in model | [api/services/telephony/registry.py](../api/services/telephony/registry.py) + [providers/twilio/](../api/services/telephony/providers/twilio/) |
| Call end + post-call | [api/services/pipecat/event_handlers.py](../api/services/pipecat/event_handlers.py), [api/tasks/run_integrations.py](../api/tasks/run_integrations.py) |
| Fork surface | `git -C pipecat diff c49bf69df HEAD -- src` |

### Related documents

- [`app-doc/telephony-architecture.md`](./telephony-architecture.md) — carriers, SIP, BYOC, inbound routing
- [`app-doc/per-agent-model-overrides.md`](./per-agent-model-overrides.md) — how the model/voice for a call is resolved
- [`app-doc/tool-catalog.md`](./tool-catalog.md) — proposed curated tool library (design, not shipped)
- [`docs/core-concepts/`](../docs/core-concepts/) — the user-facing version of this material
