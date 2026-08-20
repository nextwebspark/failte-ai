# Review — PR #3: Google voice catalogue picker + Claude/MaaS models on Vertex

Branch `feat/vertex-third-party-llms` → `main`, +4308/−37 across 35 files.
Reviewed against `ac8a22d4`.

Baseline checks: CI green (`pytest`, `drift-check`); `npx vitest run` on the two new UI test
files passes locally (9/9); `ruff check api --select I --select F401` and `tsc --noEmit` clean;
the fork is 0 commits behind upstream, so this lands on a fully synced base.

**Verdict: strong PR, mergeable after a short fix list.** The commit messages, the `FORK.md`
seam documentation, and the why-first comments are better than most production repos, and the
catalogue logic is correctly isolated in fork-owned `api/saas/`. The problems cluster in four
places: two bugs on the credential path, blocking I/O plus no catalogue caching in
`google_voices.py`, Vertex routing logic parked in the hottest upstream file, and 2,629 lines
of unrelated docs riding along.

---

## 1. Bugs

**1.1 — A malformed service-account credential is reported to the user as HTTP 400 "invalid
voice id", with the parse error in the response body.** `preview_audio` signals a bad
`voice_id` by raising `ValueError`, and the route maps `ValueError` → 400 with `detail=str(e)`
(`api/routes/user.py:569-570`). But `_credentials()` runs inside the same call and does
`json.loads(credentials_json)` — and `json.JSONDecodeError` **is** a `ValueError`. So a broken
stored credential produces a 400 whose detail is `Expecting value: line 1 column 1 (char 0)`:
a server-side misconfiguration reported as a client error, with a fragment of the credential
blob potentially echoed back. Raise a dedicated `InvalidVoiceIdError` for the validation case,
or resolve credentials outside the `try`.

**1.2 — `_google_tts_credentials` returns whatever `effective.tts.credentials` holds,
regardless of which TTS provider the org configured** (`api/routes/user.py:538-551`). An org on
ElevenLabs hands an ElevenLabs key to `service_account.Credentials.from_service_account_info()`,
which raises, is swallowed by the bare `except Exception`, and silently falls back to
Application Default Credentials. It works only by accident — and see 2.2 for why that fallback
matters.

**1.3 — Fifth install site missed, and `CHANGES.md` asserts otherwise.**
`scripts/setup_requirements.ps1:63` still installs pipecat without the `anthropic` extra, while
`saas/docs/CHANGES.md` states the extra was "added at all four install sites". A Windows
contributor selecting any `claude-*` model gets a raw `ModuleNotFoundError` from the lazy import.

**1.4 — The lazy import has no `ImportError` handling**
(`api/services/pipecat/service_factory.py:1051-1054`). The lazy import exists precisely so
Gemini-only deployments run without the `anthropic` extra — but such a deployment selecting a
Claude model surfaces `ModuleNotFoundError: anthropic` rather than "this deployment does not
support Claude on Vertex".

**1.5 — `_vertex_model_family` has no unknown outcome.** Anything that is not Gemini or Claude
falls through to the MaaS branch, so a typo (`gemni-3.5-flash`) is sent to Vertex's
OpenAI-compatible endpoint and fails there with an unrelated 404 instead of a config error.

---

## 2. Security

| # | Severity | Finding |
|---|---|---|
| 2.1 | Medium | Preview route returns `Cache-Control: public, max-age=86400` (`api/routes/user.py:578`) on an endpoint behind `Depends(get_user)`, with no `Vary: Authorization`. `public` authorizes shared/proxy caches to store an authenticated response. Use `private`. |
| 2.2 | Medium | **Fail-open on the credential path.** `_google_tts_credentials` swallows every exception and returns `None`, which means "use the platform's Application Default Credentials", logged at `debug`. A transient DB error or a config-resolution bug silently converts a BYOK tenant request into one authorized by and billed to the platform's own GCP identity — and the tenant never sees that their credentials are broken, because the picker keeps working. Narrow the except, log at `warning`, distinguish "no config" from "lookup failed". |
| 2.3 | Medium | No rate limit or quota on `/configurations/voices/google/preview`. Any authenticated user can walk distinct voice ids and force ~1,568 Google-billed synthesis calls (against the org's key, or the platform's per 2.2). The disk cache only suppresses repeats. |
| 2.4 | Medium | **`/tmp` cache directory.** `mkdir(exist_ok=True)` on `/tmp/dograh-voice-previews` succeeds against an attacker-pre-created directory or symlink on a shared host, and `read_bytes()` then trusts whatever is at that path — a local write primitive becomes "attacker controls the audio served to an authenticated user". No `mode=0o700`, no realpath check. This is also the only `/tmp/` literal in all of `api/`. |
| 2.5 | Low | Cache key is `sha256(voice_id\|PREVIEW_TEXT)` — not tenant-scoped. Content is a fixed English sentence, so this is billing/attribution rather than data leakage, but a tenant whose credentials are revoked keeps getting previews. |
| 2.6 | Low | `logger.exception(f"...{voice_id}")` logs unvalidated user input; the credential path can put a parse message (and a fragment of the key blob) into a traceback. |

Handled well: `voice_id` is validated with `re.fullmatch(r"[A-Za-z0-9-]{3,64}", ...)` *before*
it reaches a filename or an outbound request, and the traversal cases are parameterized in
`api/tests/test_google_voice_catalog.py:153-161`; the cache path is hash-derived, so `voice_id`
never touches the filesystem. Credentials are never logged. Org scoping goes through
`user.selected_organization_id` per `api/AGENTS.md`. Google's error bodies reach the logs but
never the client. Route ordering (`/voices/{provider}` declared before `/voices/google/preview`)
is safe — the segment counts differ. In the UI, `src.startsWith("/")` keeps the bearer token on
the app's own origin, and the blob URL is revoked on `ended`, `error`, close, and unmount, all
tested.

---

## 3. Correctness / performance

| # | Severity | Finding |
|---|---|---|
| 3.1 | High | **No catalogue caching.** `list_voices()` fetches Google's full ~1,568-voice list *and* mints a fresh OAuth token on every call. The picker filters server-side behind a 300 ms debounce, so each keystroke costs a token mint plus a full catalogue fetch. Cache per (credential fingerprint, model) with a TTL. |
| 3.2 | High | **Blocking I/O on the event loop.** `creds.refresh(GoogleAuthRequest())` is a synchronous HTTPS round trip, `from_service_account_info` does RSA parsing, and `read_bytes`/`write_bytes` are sync — all inside `async def` handlers on a process that also runs live voice pipelines. The repo already uses `asyncio.to_thread` for this (`api/services/filesystem/minio.py:106`), and `vertex_llm.py:124` does too, so the PR is inconsistent with its own code. |
| 3.3 | Medium | `_GoogleCredentialsAuth` checks `creds.valid` and refreshes with no lock (`api/services/pipecat/vertex_llm.py:106-126`). Concurrent requests each mint a token while other coroutines read `self._creds.token`. Add an `asyncio.Lock`; the sync flow also calls the blocking `refresh()` directly. |
| 3.4 | Medium | **Non-atomic cache write.** `cached.write_bytes(audio)` — a crash mid-write leaves a truncated `.mp3` served forever, since the read path only checks `exists()`. The repo's own `api/services/pipecat/audio_file_cache.py:136` does this correctly with `tempfile.mkstemp(dir=CACHE_DIR)` + rename. An `OSError` also turns a successful synthesis into a 502. |
| 3.5 | Medium | The Google branch bypasses failure telemetry. The MPS branch below classifies via `log_failure(classify_exception(...))` and maps `MPSUnavailableError` → 503 (`api/routes/user.py:520-531`); the Google branch is a bare `except Exception` → 502, so its failures never reach the telemetry the rest of the route feeds. |
| 3.6 | Medium | **Per-agent temperature is silently dropped for Vertex.** The factory receives `temperature` but all three Vertex branches hardcode `0.1`. It matches the pre-existing branches, but the PR entrenches it while `app-doc/per-agent-model-overrides.md` rides along in the same diff. |
| 3.7 | Low | `MODEL_ID_TO_FAMILY` has 8 keys but `GOOGLE_TTS_MODELS = ("chirp_3_hd",)` — 7 are unreachable, and an unrecognized model silently disables family filtering rather than erroring. |
| 3.8 | Low | `REGION_NAMES` mixes demonyms with place names (`"ES": "Spain"`, `"PT": "Portugal"` beside `"MX": "Mexican"`), so the UI renders "Spain female" / "Portugal male". |
| 3.9 | Low | `PREVIEW_TEXT` is one English sentence used to preview every voice, including the ~50 non-English languages. |
| 3.10 | Low | `project_id` is `str \| None` in the factory but non-optional in `vertex_llm.py`; a `None` reaches the f-string and yields `.../projects/None/...`. The registry marks it required, so this is defense-in-depth only. |
| 3.11 | Low | Per-entry shaping has no try/except (one malformed voice aborts the whole catalogue) while entries missing name/locale are silently skipped with no counter, so an upstream shape change is invisible. `resp.json()["audioContent"]` is unguarded. |

**UI error handling** (`ui/src/components/VoiceSelectorModal.tsx`): the preview failure path is
an empty `catch {}` with no logging and no user feedback, so a 502 is indistinguishable from a
voice with no preview — `ui/AGENTS.md` mandates `logger` + `detailFromError` here. The main
fetch has no try/catch, so a network rejection leaves `isLoading` stuck `true`. The modal also
lacks the `authLoading`/`user` guard `ui/AGENTS.md` requires for authenticated calls. And
`playPreview` has no request-generation guard (unlike the catalogue fetch, which uses
`requestId`), so previewing B while A is still fetching can leave A's blob URL in the ref.

`feedbackId` is a correct fix, but
`ui/src/app/workflow/[workflowId]/run/[runId]/hooks/useWebSocketRTC.tsx:488` still uses
`` `func-${Date.now()}` ``. That one is deliberately deterministic for the dedup check on the
next line — but the exception is undocumented and carries the exact collision risk the module
was created to remove.

**Verified correct:** the Claude model ids are right for Vertex — bare ids for
current-generation models and `@`-separated dated snapshots are both valid — and the temperature
guard matches reality, since sampling params are rejected on Sonnet 5 / Opus 4.7+. pipecat leaves
`top_k`/`top_p` as `NOT_GIVEN`, so stripping `temperature` alone is sufficient. The manual smoke
test in the PR body remains unchecked; it is the one thing tests cannot cover.

---

## 4. Hardcoded values that belong in config

Repo convention: provider option lists live in `api/services/configuration/options/<provider>.py`
and surface through `registry.py` field metadata. The PR follows that correctly for
`GOOGLE_VERTEX_MODELS`. These do not:

- `PREVIEW_CACHE = Path("/tmp/dograh-voice-previews")` — fixed absolute path, not
  env-configurable, no eviction, lost on restart, not shared across workers, and it hardcodes the
  upstream brand inside a Failte-branded fork. The house convention is
  `api/services/pipecat/audio_file_cache.py:21` (`CACHE_DIR` derived from `APP_ROOT_DIR`).
- `preview_url` hardcodes `"/api/v1/user/configurations/voices/google/preview?voice_id=..."`
  inside a service module while `API_PREFIX` lives at `api/app.py:50`. Four places must agree, and
  the id is not URL-encoded (safe today only because Google names are `[A-Za-z0-9-]`).
- The synthesis URL is an inline literal at `api/saas/voice_catalog/google_voices.py:270` while
  the catalogue URL is the `VOICES_URL` constant — same class of value, two conventions.
  `"MP3"` / `.mp3` / `audio/mpeg` must agree across three places.
- `PREVIEW_TEXT`; `timeout=30.0` vs `timeout=60.0` with no stated reason; `resp.text[:200]`
  twice; `max_age=86400`.
- `SCOPES` duplicates the identical literal in pipecat's Vertex service and requests full
  `cloud-platform` scope for a voice listing.
- `defaultAccent="gb"` inline at `ui/src/components/ServiceConfigurationForm.tsx:732` — a
  fork-specific product decision as a bare literal inside a generic form renderer, on the upstream
  side of the boundary. The adjacent comment says "opens on British female", but only the accent
  is passed; the gender comes from the modal's own `DEFAULT_GENDER`, so the default is split
  across two files. Also a product question: an Irish-branded deployment defaulting to British
  voices, when `"IE": "Irish"` already exists in `REGION_NAMES`.
- `_VERTEX_TEMPERATURE_UNSUPPORTED` sits in `service_factory.py` while the model catalogue it
  describes sits in `options/google.py` — every Claude release needs edits in two unlinked files.
  Four of its five entries are unreleased names, and `startswith` matching silently captures
  variants (intentional but unstated).
- Three different location defaults inside one `elif` branch: `location or "global"` (Claude),
  raw `location` (MaaS), `location or "us-east4"` (Gemini).
- `api_key="unused"` three times; `httpx.Limits(100, 1000, None)` copied verbatim from pipecat's
  default with no comment.
- `LANGUAGE_NAMES` / `REGION_NAMES` duplicate the UI's `LANGUAGE_DISPLAY_NAMES` /
  `ACCENT_DISPLAY_NAMES`; `MODEL_FAMILIES` and `MODEL_ID_TO_FAMILY` restate the same tokens, and
  the ordering of `MODEL_FAMILIES` is load-bearing (`Chirp3-HD` must precede `Chirp-HD`) but
  undocumented.

Done right: `_DEFAULT_MAAS_REGION` is a named constant with a rationale; the
`VoiceSelectorModal` constants (`ALL_FILTER_VALUE`, `SEARCH_DEBOUNCE_MS`, the three defaults) are
properly factored.

---

## 5. Naming

Overall good, and the comments explain *why* rather than *what* — the strongest quality signal in
this PR. Nits, roughly by cost:

- `_create_message_stream(self, api_call, params)` **accepts `api_call` and silently discards
  it**, substituting `self._client.messages.create`. A caller passing the beta endpoint gets
  something else. Rename to `_api_call` with a comment, or drop it.
- `_vertex_model_family` returns stringly-typed `"gemini" | "anthropic" | "openai_compat"` —
  three naming axes in one return set (vendor / vendor / protocol), compared against bare literals
  at two call sites. `StrEnum` or `Literal`; the repo already uses enums for this
  (`ServiceProviders`).
- `locale = re.match(...)` binds a `re.Match | None` to a name that reads as a locale string.
- `_family()` in `google_voices.py` and `_vertex_model_family()` in `service_factory.py` use the
  same word for entirely different concepts.
- `_label()` returns four unnamed positional strings and needs a nine-line docstring to explain
  them; a `NamedTuple` would replace the docstring.
- `_credentials()` is a noun that performs a network refresh; `_google_tts_credentials` returns a
  JSON *string*, not credentials.
- `temp` holds a temperature and reads as "temporary"; `q`, `human`, `matches`, `m` are vague;
  `let src` means a URL path on one line and a blob URL twenty lines later.
- Class naming axis is inconsistent: `DograhVertexAnthropicLLMService` (vendor),
  `DograhVertexMaaSLLMService` (Google marketing jargon that expands nowhere in code),
  `DograhGoogleVertexLLMService` (API). The `Dograh` prefix matches upstream convention, but the
  fork is mid-rebrand — worth confirming it's deliberate, as with `/tmp/dograh-voice-previews`.
- `feedbackId(prefix)` reads like a value rather than a factory (`nextFeedbackId`).

---

## 6. Structure / SOLID

1. **Routing logic in the wrong module.** `_vertex_model_family` and
   `_VERTEX_TEMPERATURE_UNSUPPORTED` encode Vertex- and Anthropic-specific knowledge but live in
   the generic factory, in the file's TTS region, two functions from any Anthropic code. Adding a
   fourth Vertex family means editing two files. Move them into `vertex_llm.py` behind one
   `build_vertex_llm_service(model, project_id, location, credentials)`; the factory keeps a
   single call. This is simultaneously the SRP fix and the largest fork-maintenance win (§7).
2. **Duplicated upstream implementation.** `DograhVertexAnthropicLLMService.run_inference` is a
   near-verbatim copy of pipecat's `AnthropicLLMService.run_inference` (line-for-line equivalent
   apart from dropping `betas` and swapping the endpoint). The streaming path solves the same
   problem in four lines via `_create_message_stream`. pipecat is a vendored submodule upstream
   bumps regularly, so a change there will **silently diverge** — and the tests mock `self._client`,
   so they would keep passing. Use one shared `_strip_betas(params)` and delegate to `super()`.
3. **Coupling to six pipecat private members** — `_get_credentials` (a `@staticmethod` called from
   outside its class, in two places), `_create_message_stream`, `_settings`, `_client`,
   `_should_inject_trailing_user_message`. Pragmatic for a vendored dep, but wrap
   `_get_credentials` in one local helper so a rename is a one-line fix. Meanwhile
   `google_voices.py` re-implements that same credential logic a third time, so the feature has
   two credential paths.
4. **`create_llm_service_from_provider` is a ~170-line `elif` chain**; the Vertex branch is now 35
   lines with three returns and two inline lazy imports. `create_tts_service` is ~380 lines. Both
   are pre-existing open/closed violations this PR extends rather than introduces — a
   provider→builder dispatch table is the standing refactor.
5. **`list_voices` is 76 lines doing six jobs** (auth, fetch, error translation, shaping,
   filtering, faceting), with a nested `matches` closure defined mid-function. `google_voices.py`
   as a whole owns credentials, HTTP, label i18n, filtering, synthesis, and a disk cache in 285
   lines. Extracting `_to_voice_info(entry)`, the label tables, and a small cache class would also
   make the cache directory injectable — which is what the missing cache tests need.
6. **Untyped dict contract.** `list_voices() -> dict` is splatted into `VoiceInfo(**voice)` at the
   route; the repo's convention is pydantic schemas under `api/schemas/`.
7. **UI:** `renderFieldInput` is ~190 lines and now carries a 20-line provider-specific special
   case whose own comment notes it must run *before* the branch below it. That ordering coupling is
   fragile; a `voiceFieldRenderers[provider]` lookup would reduce the upstream edit to one line.
   `VoiceSelectorModal.tsx` is 505 lines covering fetching, debounce, race handling, blob
   lifecycle, playback, and markup.
8. `api/saas/__init__.py` and `api/saas/voice_catalog/__init__.py` are empty — no re-export, so
   callers reach into the module directly.

---

## 7. Fork maintainability

Genuine strengths: 27 of 35 files are new and therefore conflict-free; every upstream edit is an
insertion at a seam rather than an interleaved rewrite; `VoiceSelectorModal.tsx` and
`ServiceConfigurationForm.tsx` are model examples of additive, backward-compatible seam work (new
optional props defaulting to the previous constants, so MPS providers take the identical old
path); the OpenAPI regeneration is surgically clean — a structural diff is 110 lines of intended
content with zero tool-version churn; and `FORK.md` gained a seam table documenting the three
traps a future merge must preserve.

### Upstream churn against edit size

| Upstream file this PR edits | Commits/yr upstream | Edit |
|---|---:|---|
| `api/services/configuration/registry.py` | 75 | +10/−2, descriptions only |
| `api/services/pipecat/service_factory.py` | 72 | +69/−1, three separate hunks |
| `api/Dockerfile` | 31 | one extras line |
| `ui/.../useWebSocketRTC.tsx` | 28 | six one-line swaps |
| `api/routes/user.py` | 17 | +76/−2, mostly appended at EOF |
| `ui/src/components/ServiceConfigurationForm.tsx` | 9 | +27, one insertion |
| `api/services/configuration/options/google.py` | 4 | +27, interleaved into upstream's block |
| `ui/src/components/VoiceSelectorModal.tsx` | 1 | +65/−12, additive |

The two hottest files take the two largest edits. `registry.py` is description-only (cheap to
resolve), but `service_factory.py` gets three hunks including an `import re` on line 1. §6.1
collapses that to one call site.

### Issues, in order of cost

- **`FORK.md`'s seam table covers only half the PR.** Track 2 is absent: `options/google.py`,
  `registry.py`, both Dockerfiles, and both setup scripts are unlisted, `vertex_llm.py`'s
  placement outside `api/saas/` is unrecorded, and the `service_factory.py` row cites only the TTS
  `language_code` change — not the larger Vertex routing block in the same file. `CHANGES.md`
  narrates it, but a changelog is not the merge-conflict playbook, and FORK.md's own rule is "keep
  this list short and current".
- **The four duplicated extras lines are a guaranteed recurring conflict.** That pipecat-extras
  string is exactly what upstream edits when adding a provider, and the fork now diverges on it in
  four places — five, counting the `.ps1` site the PR missed (§1.3). There is no single source of
  truth for it.
- **Silent divergence against the pinned pipecat submodule** (§6.2) is arguably a bigger long-term
  cost than every git conflict above, because nothing fails loudly when it happens.
- **`vertex_llm.py` is fork code in an upstream-owned directory.** Practical collision risk is
  near zero, but it defeats the "ours vs theirs by path" heuristic the rest of the fork relies on,
  and it is inconsistent with the other track in the same PR.
- **Undeclared transitive dependency.** `pipecat[anthropic]` resolves to plain
  `anthropic>=0.49.0,<1` (`pipecat/pyproject.toml:66`). `AsyncAnthropicVertex` needs `google-auth`,
  which the `anthropic[vertex]` extra declares; it imports today only because `google-auth 2.56.3`
  arrives via the Google TTS libraries. Pin `anthropic[vertex]` in the fork-owned
  `api/requirements.txt`.
- `gemini-3.5-pro` is interleaved into upstream's contiguous Gemini block in `options/google.py` —
  a tuple upstream demonstrably churns. `GOOGLE_VERTEX_MODELS = (*UPSTREAM, *OURS)` would have been
  conflict-free.

---

## 8. Scope / PR hygiene

- **2,629 of the 4,308 added lines (61%) are unrelated docs.**
  `app-doc/tenancy-auth-roadmap.md` (795), `tenancy-stack-auth.md` (717), `tool-catalog.md` (486),
  `telephony-architecture.md` (460), `per-agent-model-overrides.md` (171) entered through the
  `d054a2b5` merge of `feature/cleanup`, are absent from `main`, and are not mentioned in the PR
  description.
- **They carry an architectural decision with them.** `saas/docs/AUTH-PROVIDER.md` flips from
  "Status: open. No decision made." to "**Status: closed. Decision: Stack Auth, self-hosted in the
  EU**". That is a significant, separately-reviewable choice landing inside a PR titled "Vertex
  third-party LLMs".
- **`app-doc/` is a new top-level directory `FORK.md` does not mention.** Its "Where our code
  goes" table lists `saas/docs/`, `saas/dev/`, `api/saas/`, `ui/src/saas/`. The fork now has three
  doc locations (`saas/docs/`, `app-doc/`, upstream's `docs/`) with no stated rule.
- Two independent features in one PR; each is separately revertable, and the PR body already
  narrates them as separate sections.
- Underneath the docs noise the real change is small and well balanced: ~747 production lines
  against ~697 test lines.

---

## 9. Tests

Good: docstrings state *why*; "facets describe the whole catalogue, not the filtered view" is
exactly the invariant that regresses silently; `test_upstream_failure_is_not_swallowed` and the
parameterized `voice_id` rejection cases cover the load-bearing guards; the UI suite covers
bearer-token blob playback, revocation, and the MPS absolute-URL path; the factory tests correctly
patch in the `vertex_llm` namespace, which the lazy import requires.

Gaps:

- Nothing patches `PREVIEW_CACHE`, so any test reaching the disk path touches the developer's real
  `/tmp/dograh-voice-previews` and can pass on a warm cache.
- No test for the cache-hit path, the cache key staying hash-derived, or atomicity.
- No test for `_google_tts_credentials`' fallback — the behaviour behind bugs 1.1, 1.2 and
  finding 2.2.
- No test looping `GOOGLE_VERTEX_MODELS` and asserting which service class each id resolves to.
  That single test pins the routing table to the catalogue and catches a future id silently landing
  in the MaaS branch.
- Nothing asserts the preview route's auth dependency or `Cache-Control` header.
- **CI never runs the UI tests.** `.github/workflows/api-tests.yml` runs `pytest` only;
  `ui/package.json` has `"test": "vitest run"` with no workflow calling it, so the 210 new UI test
  lines rot unnoticed. Adding a vitest job is fork-owned with no upstream conflict cost.
- Tests reach into private members (`service._client`, `_create_message_stream`) — mirroring
  production coupling rather than adding new coupling, but §6.2/§6.3 would let them assert against
  a narrower seam.

---

## 10. Fix list

### Before merge

1. Fix the `ValueError` conflation so a bad credential is not a 400 "invalid voice id" with the
   parse error in the body (1.1).
2. Narrow `_google_tts_credentials`: check the provider is Google, catch a specific exception, log
   at `warning` (1.2, 2.2).
3. Add `anthropic` to `scripts/setup_requirements.ps1` and correct the "four install sites" claim
   in `CHANGES.md` (1.3).
4. Wrap the lazy import in `ImportError` handling with an actionable message (1.4).
5. `Cache-Control: private` (2.1).
6. Move credential refresh, credential parsing, and cache file I/O off the event loop with
   `asyncio.to_thread` (3.2).
7. Cache the voice catalogue with a TTL (3.1).
8. Split the `app-doc/` docs and the `AUTH-PROVIDER.md` decision flip into their own PR (§8).

### Before the next upstream sync

9. Move Vertex routing into `vertex_llm.py`; the factory keeps one call (6.1) — this also resolves
   the split `_VERTEX_TEMPERATURE_UNSUPPORTED` (§4).
10. Add the track-2 seams to `FORK.md`; record or fix `vertex_llm.py`'s location; register
    `app-doc/` in the "where our code goes" table (§7, §8).
11. Pin `anthropic[vertex]` in `api/requirements.txt` (§7).
12. De-duplicate `run_inference` against pipecat's implementation, and wrap `_get_credentials` in
    one local helper (6.2, 6.3).

### Cleanups

13. `asyncio.Lock` around token refresh (3.3); atomic cache write reusing `audio_file_cache.py`'s
    `mkstemp` pattern (3.4).
14. Route Google failures through `classify_exception`/`log_failure` like the MPS branch (3.5).
15. Make the cache dir, preview text, timeouts, and the `gb` default configurable; derive
    `preview_url` from `API_PREFIX` (§4).
16. `_label` → `NamedTuple`; `_vertex_model_family` → `StrEnum` with an explicit unknown case; drop
    or rename the unused `api_call` param; fix the `REGION_NAMES` demonyms (§5, 1.5, 3.8).
17. UI: log and surface preview failures, add the `authLoading` guard, guard `playPreview` against
    out-of-order responses, document the `func-` id exception (§3).
18. Add a vitest CI job and the five missing tests (§9).

---

## Verification

```bash
# backend
source venv/bin/activate && set -a && source api/.env.test && set +a
python -m pytest api/tests/test_google_voice_catalog.py api/tests/test_vertex_third_party_llm.py \
  api/tests/test_google_vertex_llm_service_factory.py api/tests/test_google_tts_service_factory.py

# frontend
cd ui && npx vitest run src/components/VoiceSelectorModal.test.tsx src/lib/feedbackId.test.ts

# drift gates CI enforces
./scripts/format.sh && git diff --exit-code api ui
source venv/bin/activate && set -a && source api/.env && set +a && python -m scripts.dump_docs_openapi

# manual, still unchecked in the PR body
# Model Overrides -> claude-sonnet-4-6, then a MaaS id (meta/llama-3.3-70b-instruct-maas):
# text chat + one short voice call against a real Vertex project with Model Garden enabled.
# Agent settings -> Google TTS -> voice picker: preview a voice twice (cold vs cached), confirm
# a non-en-US voice synthesises without a 400, and confirm a broken credential surfaces as 5xx.
```
