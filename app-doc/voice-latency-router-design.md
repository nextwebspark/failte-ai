# Voice latency: where the time goes, and a fast router in front of the LLM

Investigation for the CH Marine agent on the GCP deployment (2026-09-11). It
covers what each call measured, what a light "router" model can and cannot fix,
and the router design that was built for the node-based workflow engine.

## TL;DR

- **What the caller hears on the phone** (run 113, workflow 4, silence filler on):
  about **4.2 s** from the moment they stop speaking to the agent's first sound.
- **Half of that is Google finalising the transcript** (~2.1 s). No LLM-side
  trick touches this slice, because nothing can reply before the words are
  known, and `chirp_3` does not stream usable interim results (1 interim in a
  78 s call).
- **A light router can shrink the next slice.** The main LLM's first word takes
  ~1.0 s. A small EU model returns a full routing decision plus a spoken
  acknowledgement in **~0.4 s**. Speaking that acknowledgement while the main
  model works should cut dead air by about **0.6–0.7 s per turn**.
- **Built as workflow 6, "CH Marine fast router".** It keeps the same STT → LLM
  → TTS pipeline, and from the caller's side it behaves the same as workflow 4.
- **The router is never in charge.** It cannot answer, book, or move the
  conversation; the main model keeps full control.

## 1. Where the latency is

Run 113 (phone, extension 200 → 7065, workflow 4, gemini-3.5-flash, silence filler
on). Median per turn:

| Stage | Time | Share |
|---|---|---|
| VAD confirms the caller stopped (`stop_secs=0.2`) | ~0.2 s | 5 % |
| **Google STT final transcript** (turn released) | **2.10 s** | **50 %** |
| Main LLM first token (gemini-3.5-flash, global) | 1.00 s | 24 % |
| First sentence + TTS buffer to first audio | 0.40 s | 10 % |
| Asterisk → carrier → handset playout | ~0.5 s | 11 % |
| **What the caller heard (from the recording)** | **~4.2 s** | |

- **The goodbye turn took 6.2 s.** Ending takes two LLM calls: `end_call`, then
  the End Call node generates its farewell.
- **The prompt cache barely helps.** Only 15 % of prompt tokens came from cache
  on the global endpoint, so ~4–5k tokens are reprocessed on every call.

### How the numbers moved across the experiment

| Run | Setup | Typical turn | Notes |
|---|---|---|---|
| 108 | workflow 3, original | 9.5 s heard | Line drops audio in silence; STT stalled 4–8 s per turn |
| 109 | workflow 4, gemini-2.5-flash | 3.0 s heard | Fast, but end-of-call went silent and the wrong number was booked; reverted |
| 110 | workflow 4, gemini-3.5-flash | 4.2 s heard | Min-words interruptions; line 60 % gaps |
| 111 | + input silence filler | 3.40 s pipeline | STT wait fell from 2.6–3.2 s to 2.18 s |
| 112 | workflow 5, Gemini Live realtime | 3.37 s pipeline | No faster; poor transcription (one reply heard as Hindi), wrong digit booked; rejected |
| 113 | workflow 4 (baseline for this doc) | 4.2 s heard / 3.48 s pipeline | Table above |

## 2. What a router can and cannot fix

**It cannot touch the STT slice.**
- The router needs the caller's words, just like the main model does.
- An "eager" router that works on interim transcripts would get a head start,
  but it isn't available here. Streaming run 113's audio through `chirp_3`/`eu`
  produced **1 interim and 5 finals** in 78 s; the finals arrived 1.3–1.6 s
  after speech ended.
- The fix for this slice is a faster recogniser (for example Deepgram EU), not
  the LLM.

**It can replace the first-audio slice.** Router candidates were measured from
the app VM (europe-west1), with a ~400-token router prompt returning JSON:

| Model | Endpoint | First token | Full decision | Routes right (4 test turns) |
|---|---|---|---|---|
| gemini-2.5-flash-lite | europe-west1 | 0.32 s | 0.43 s | 4/4 (one ack named a product) |
| **gemini-2.5-flash** | **europe-west1** | **0.30 s** | **0.39 s** | **4/4, clean acks** |
| gemini-3.5-flash-lite | global | 0.42 s | 0.55 s | 4/4 |
| gemini-3.5-flash (main model) | global | 0.85 s | 1.02 s | 4/4 |

gemini-2.5-flash failed as the *main* agent. On the end-of-call and
number-correction turns it produced an empty reply or ignored the correction,
6 runs out of 6. The router job is much narrower (classify, and write at most
6 words), and it did that correctly. That narrow job is exactly why it is safe
here.

## 3. Options considered

| Pattern | Verdict |
|---|---|
| **A. Fast acknowledger in parallel with the main LLM** | **Chosen.** Low risk: the main LLM is unchanged and the router only fills silence. |
| B. Router answers simple turns itself (small talk, confirmations) | Later. Bigger win on those turns, but it splits the conversation across two "brains" and needs guardrails for anything with side effects. |
| C. Router picks the node or pre-fetches the tool | Later. It pays off in multi-node workflows (it saves the transition round trip) and for tool prefetch. It needs a shared `engine.transition_to()` extracted from the transition function. |
| D. Speech-to-speech (Gemini Live) | Tested as workflow 5, run 112. No latency gain on this line, worse transcription, wrong booking. |

## 4. The design (pattern A)

```
            ┌──────────────── user turn released ────────────────┐
STT ─► user aggregator ─► FastRouterProcessor ─► main LLM ─► engine callbacks ─► AckGate ─► TTS ─► phone
                                │   forwards the LLMContextFrame first,          ▲
                                │   so the main LLM starts immediately           │ TTSSpeakFrame(ack)
                                └── light model (~0.4 s) ── {"route","ack"} ─────┘ only if no LLM text yet
```

### Components

`api/services/pipecat/fast_router.py`:

- **`FastRouterProcessor`** sits directly before the main LLM.
  - It fires on every `LLMContextFrame` whose last message is the caller's.
  - It forwards the frame **before** consulting the router, so the main LLM is
    never delayed.
  - It then starts a background call to the light model, with a transcript of
    the last N spoken messages.
  - It cancels that call on interruption or when the call ends.
- **`AckGate`** sits directly before TTS.
  - Each turn is opened with `begin_turn()`.
  - The router's acknowledgement is spoken only if no main-LLM text (and no
    engine speech) has reached TTS for that turn yet. If the answer arrived
    first, the acknowledgement is dropped.
  - **One filler per turn.** Once the acknowledgement has been spoken, a
    tool's scripted line (`append_to_context=False`) is dropped until the
    LLM's own text arrives. When the router stayed silent (for example on
    "yes, that's correct", which triggers the booking), the tool's line plays
    as usual.
- **`safe_ack()`** blocks acknowledgements that are not safe to speak: any with
  digits or currency, longer than 8 words, or on the `end_call` route.

### Why the gate sits after the LLM

The Google LLM service processes an `LLMContextFrame` inline
(`pipecat/src/pipecat/services/google/llm.py:699-720`). A frame queued behind it
waits for the whole generation to finish. An acknowledgement pushed from in
front of the LLM would therefore be spoken *after* the answer. The gate
injects it downstream of the LLM instead, the same way the engine uses
`llm.queue_frame` and `transport_output.queue_frame` to bypass processors.

### The prompt split

**The router gets its own short prompt** (workflow configuration
`fast_router.prompt`):
- a route list;
- a 6-word acknowledgement, fitted to what comes next;
- hard rules: never state a price, stock level, product, time, date, address
  or any fact; never promise or book anything; return `""` for yes/no answers,
  personal details, corrections, goodbyes, and the `end_call` route.

**The main LLM keeps its full prompt, with one rule changed.** An
acknowledgement has usually been spoken already, so it must not open with its
own or say "let me check". It goes straight to the answer, or calls the tool
with no words.

**The acknowledgement is not written into the LLM context**
(`append_to_context=False`, as transition speech already works). It is written
to the run logs (`persist_to_logs=True`), so it appears in the transcript view.

### Fit with the node-based engine

- **Config today is per workflow:**
  `workflow_configurations.fast_router = {enabled, model, location, timeout_ms,
  history_messages, prompt}`. It is read in `run_pipeline.py` next to
  `input_silence_fill_enabled`. The schema allows extra keys, and the
  Configurations dialog keeps unknown keys when it saves.
- **Per node (next step):** make the router node-aware. Derive the route list
  from the current node's tools and edges, and allow a node-level router prompt
  or acknowledgement mode. Node fields are declared once in
  `api/services/workflow/dto.py` (`@node_spec`), and the UI renders them
  generically.
- **Router-driven transitions (pattern C):** `engine.set_node()` does not start
  generation, so a router could switch nodes before forwarding the held context
  frame. That needs the transition side effects (variable extraction,
  transition speech, end-node hang-up) pulled into one `engine.transition_to()`,
  plus gating so the LLM's settings are not swapped mid-generation.
- **Tools:** the router workflow keeps the tools that have a `customMessage`,
  as a fallback. The gate drops a tool's line when the router has already
  acknowledged the turn, so nothing is said twice. A version that used tools
  without spoken lines (run 114) left the booking confirmation silent for
  5.3 s, because the router rightly says nothing on "yes".

### How it fails safe

| Situation | Behaviour |
|---|---|
| Router slower than the main LLM | Acknowledgement dropped (`late`); the turn is identical to workflow 4 |
| Router timeout (1.2 s) or error | No acknowledgement; logged at INFO; the turn is unaffected |
| Unsafe acknowledgement (digits, too long, end of call) | Not spoken |
| Caller talks over the acknowledgement | Normal interruption (needs 3+ words with `min_words`) |
| Router task still running when the caller interrupts or hangs up | Cancelled |

Each router decision is logged as
`FastRouterProcessor#N: route=... ack='...' 412 ms -> spoken|late|no-ack|stale`.

## 5. Implementation

| File | Change |
|---|---|
| `api/services/pipecat/fast_router.py` | **new**: `FastRouterProcessor`, `AckGate`, `safe_ack`, `transcript_from_messages`, `vertex_router_decider` (google-genai, Vertex, JSON mode, thinking off) and `create_fast_router` |
| `api/tests/test_fast_router.py` | **new**: 13 tests covering acknowledgement ordering, dropping when late, one filler per turn (a tool line dropped after an acknowledgement, and played when the router is silent), no call without a user turn, router failure, safety filter and transcript rendering |
| `api/services/pipecat/pipeline_builder.py` | `fast_router` goes before the LLM; `ack_gate` goes after the callbacks and recording router, before TTS |
| `api/services/pipecat/run_pipeline.py` | Builds both when `fast_router.enabled`, using the main LLM's Vertex `project_id` (ADC credentials) |

Deployed the same way as the silence filler: the files are bind-mounted over
the image in the server's `deploy/gcp/docker-compose.override.yaml`, from
`deploy/gcp/patches/`. **Remove those mounts before deploying a new API image**,
or the old copies will silently override it.

### Workflow 6, "CH Marine fast router"

Workflow 6 is a copy of workflow 4 (low latency, with the silence filler), with
these differences:
- `fast_router`: **gemini-2.5-flash-lite** @ europe-west1, timeout 1200 ms, last 6
  messages (version 4). flash-lite answers the router job in ~0.35 s against
  ~0.57 s for flash, at about a third of the price; the router only classifies
  and writes six words, so flash's extra capability was unused. The prompt keeps
  its full route list — a lean variant made flash-lite return loose labels such
  as "call back" — and two rules are sharpened: keep the acknowledgement generic
  (it once named a product, which the digit filter cannot catch), and spell the
  route exactly;
- the start node keeps workflow 4's tools with spoken lines, and the gate
  allows one filler per turn (published version 3);
- one prompt rule in the main node is updated as described above.

Everything else is identical: gemini-3.5-flash @ global, Google STT `chirp_3`/`eu`,
Chirp 3 HD voice, silence filler, `min_words` interruptions, static greeting and
merged node. Workflows 3, 4 and 5 are untouched.

## 6. How to test

Use the same script as runs 108–113: ask about a life jacket, ask for the detail
on one, book a callback, correct the phone number, then say "No, I'm good".

**Pass criteria:**
- an acknowledgement is heard within ~1 s of finishing most questions, and is
  never heard mid-answer;
- the tool turns sound natural, with no double "let me check";
- the caller-perceived gap (measured from the recording) falls from ~4.2 s to
  ~3.5 s;
- booking, the number correction and the goodbye behave exactly as in
  workflow 4;
- the api log shows `-> spoken` for most turns and rarely `-> late`.

### First result: run 114 (workflow 6, version 2, tools without spoken lines)

| | Run 114 (router) | Run 113 (no router) |
|---|---|---|
| Median turn (VAD stop → first audio) | **3.04 s** | 3.48 s |
| Turn released → first audio | **0.89 s** | 1.40 s |
| Google STT wait (the router can't touch this) | 2.17 s | 2.10 s |
| Caller-perceived gap (from the recording) | **3.90 s** | 4.20 s |

- **Acknowledgements:** spoken on all 3 lookup turns, 468–635 ms after the turn
  was released. The first audio came 0.67–0.84 s after release, about
  0.4–0.5 s sooner than workflow 4's scripted lines. None was late, and none
  cut into an answer.
- **Router timeout:** once (1.2 s). That turn behaved exactly like workflow 4.
- **Silence where intended:** the router stayed silent on times, names,
  numbers, confirmations and goodbyes.
- **One regression:** "yes, that's correct" triggered the booking with nothing
  spoken for 5.3 s. Fixed in version 3 with the one-filler-per-turn rule.

## 7. What's next, by expected gain

1. **Faster STT** (Deepgram nova-3 or Flux, EU endpoint). This attacks the 50 %
   slice. It needs an account and a DPA, and a small factory change to pass
   `base_url`.
2. **A static farewell on the End Call node.** It removes a whole LLM round
   trip from the 6.2 s goodbye.
3. **A node-aware router** (routes derived from the node's tools and edges),
   then **router-driven transitions** for multi-node workflows.
4. **Explicit prompt caching** for gemini-3.5-flash. Only 15 % of the prompt is
   cached today.
5. **Filler for realtime and Gemini Live VAD tuning.** Only worth it if speech-
   to-speech is revisited.
