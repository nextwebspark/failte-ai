# Changes from the upstream base

Running log of what this fork has changed relative to upstream
[dograh-hq/dograh](https://github.com/dograh-hq/dograh) (see FORK.md for the
fork mechanics). Three tracks so far: the Google voice catalogue, the Google
Vertex model expansion, and the UI re-brand.

## 1. Google voice catalogue (`d8d6d87b`, `fa248e61`)

Upstream serves TTS voice catalogues from its hosted MPS service, which knows
nothing about Google — a BYOK Google deployment only got a free-text "Enter
voice ID" box. This fork adds its own catalogue so agent settings open the
same picker dialog the managed pipeline uses.

- `api/saas/voice_catalog/google_voices.py` — catalogue over all 1,568
  Chirp3-HD voices, answering the existing dialog contract (server-side
  gender/accent/language/q filters plus facets). Voices are keyed on base
  language ("en") with the region in accent ("gb"); gender is normalised to
  female/male/neutral.
- Previews are synthesised on demand (Google publishes no sample URLs) and
  cached on disk — ~666 ms first play, ~14 ms after.
- `api/routes/user.py` — a `provider == "google"` branch before the MPS call,
  the preview route, and "google" added to the `TTSProvider` literal.
- Synthesis derives `language_code` from the voice id's locale prefix, so a
  picker that only sets the voice can no longer produce the 400 that a
  mismatched language/voice pair triggers.
- UI: `ServiceConfigurationForm.tsx` renders the dialog for the Google voice
  field (before the `allow_custom_input` check, which previously made the
  picker unreachable); `VoiceSelectorModal.tsx` fetches preview URLs with a
  bearer token and plays them as a blob; opening filters became props.
- Fixes a duplicate-key error in the live transcript: feedback row ids come
  from a counter (`ui/src/lib/feedbackId.ts`) instead of `Date.now()`.
- 29 new tests across catalogue shaping, language derivation, dialog defaults,
  preview playback, and id uniqueness.

Upstream seams touched are each recorded in FORK.md.

## 2. More LLM models for Google Vertex (`c7d14bc4`, PR #3)

Upstream's Vertex provider hardcoded three Gemini models and always built the
Gemini-only pipecat service. The catalogue now lists 19 models across three
families, and the service factory routes by model id:

- `gemini*` / `gemma*` / `google/*` — unchanged native Gemini path.
- `claude*` — new `DograhVertexAnthropicLLMService`
  (`api/services/pipecat/vertex_llm.py`): pipecat's `AnthropicLLMService` with
  an injected `AsyncAnthropicVertex` client (per-request OAuth refresh); both
  inference paths overridden to use the non-beta Messages endpoint Vertex
  requires. Sonnet 5 / Opus 4.7+ omit `temperature` (they 400 on non-default
  sampling).
- everything else — new `DograhVertexMaaSLLMService`: Vertex's
  OpenAI-compatible MaaS endpoint with an httpx auth hook refreshing the
  service-account token per request; `global` location auto-maps to
  `us-central1` (MaaS is regional). Covers Meta Llama, DeepSeek, Qwen,
  OpenAI gpt-oss, Kimi K2, MiniMax M2 — and any future MaaS publisher via the
  "Enter Custom Value" field with no code change.

Notes:

- Proprietary OpenAI models (GPT-5/4o) are not on Vertex (Azure-exclusive);
  Mistral is excluded because it uses a native non-OpenAI-compatible API.
- MaaS models need per-project Model Garden enablement.
- pipecat's `anthropic` extra added at all four install sites (setup scripts
  and both Dockerfiles); the factory imports the new module lazily so
  Gemini-only deployments run without the package.
- No UI changes — the model dropdown is schema-driven and picks the list up
  from the regenerated OpenAPI spec.

## 3. UI changes (`578642d5`, `90052a24`, `03e75701`, `4d9ee39d`)

The fork's UI is de-branded from Dograh and carries the Failte AI identity.
Decisions are recorded in FORK.md (`487483a1`).

- `578642d5` — remove Dograh branding, docs links, and the lead-gen funnel:
  logos and brand imprints deleted, the embeddable widget renamed
  `dograh-widget.js` → `failte-widget.js`, and branded copy swept across
  auth, billing, files, overview, and model-configuration pages.
- `03e75701` — Failte AI mark (`ui/public/brand/failte-mark.svg`) used as the
  tab favicon; `BrandLogo.tsx` reworked around it.
- `90052a24` — embed tests assert the renamed widget path and context
  attribute.
- `4d9ee39d` — typed trigger node regenerated from `node_specs` after the
  rename sweep.

The voice-picker dialog wiring in `ServiceConfigurationForm.tsx` /
`VoiceSelectorModal.tsx` (track 1) is the other substantive UI change to date.
