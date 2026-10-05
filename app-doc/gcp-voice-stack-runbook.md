# Failte AI on GCP — deployment, telephony and latency runbook

Everything built and learned while putting the CH Marine voice agent on GCP and
cutting its response latency. State verified on **2026-09-12**.

Companion document: `app-doc/voice-latency-router-design.md` (the latency
measurements and the fast-router design in full).

---

## 1. Infrastructure

Project **`dograh-eu`**, zone **`europe-west1-b`** (Belgium, for EU residency).

| Component | Detail |
|---|---|
| App VM | `dograh-app`, e2-standard-2, internal `10.132.0.2`, public `35.240.85.9`, tag `dograh-app` |
| SIP VM | `dograh-sip`, e2-small, internal `10.132.0.3`, public `104.155.49.203`, tag `dograh-sip` |
| Database | Cloud SQL `dograh-pg`, POSTGRES_17, db-g1-small, **private IP `10.70.0.3`**, database `dograh` |
| Object storage | `gs://dograh-voice-audio-eu` via the S3-compatible XML API and an HMAC key |
| Images | Artifact Registry `europe-west1-docker.pkg.dev/dograh-eu/dograh` |
| Public URL | **https://35-240-85-9.sslip.io** — dashes, not dots. The dotted form has no certificate. |

**Schedule** (`dograh-dev-hours`, attached to both VMs, Europe/Dublin):
start `0 8 * * *`, stop `0 23 * * *`. The stop is abrupt and **cuts live calls**.
Remove the policy before go-live:

```bash
gcloud compute instances remove-resource-policies dograh-app \
  --resource-policies=dograh-dev-hours --zone=europe-west1-b --project=dograh-eu
```

**Firewall** (default-deny ingress; the VPC's own `default-allow-*` rules also exist):

| Rule | Source | Ports | Target |
|---|---|---|---|
| `allow-web` | 0.0.0.0/0 | tcp 80, 443 | dograh-app |
| `allow-turn` | 0.0.0.0/0 | udp/tcp 3478, 5349; udp 49152-49200 | dograh-app |
| `allow-sip` | **84.39.233.90/32** | **tcp 5071** | dograh-sip |
| `allow-rtp` | **84.39.233.90/32, 84.39.233.91/32** | udp 10000-10120 | dograh-sip |
| `allow-ari` | tag `dograh-app` | tcp 8088 | dograh-sip |
| `allow-media-ws` | tag `dograh-sip` | tcp 8000 | dograh-app |
| `allow-ssh-iap` | 35.235.240.0/20 | tcp 22 | both |

SSH is via IAP: `gcloud compute ssh dograh-app --zone=europe-west1-b --tunnel-through-iap`.

---

## 2. How the stack is deployed

**The app VM runs the standard Compose stack plus a GCP overlay.** `.env` pins both
so a bare `docker compose` command can never miss the overlay — without it the base
file silently starts a local Postgres and ignores Cloud SQL:

```ini
COMPOSE_FILE=docker-compose.yaml:deploy/gcp/docker-compose.override.yaml
COMPOSE_PROFILES=remote
```

The overlay drops the `postgres` service, keeps `minio` (nginx hardcodes a
`/voice-audio/` proxy to it), adds the two tool sidecars, sets `restart:
unless-stopped` on the core services, and adds the patch mounts below.

**Code changes are deployed as mounted files, not a new image.** Four files sit in
`deploy/gcp/patches/` and are bind-mounted over the image:

```
fast_router.py  input_silence_filler.py  pipeline_builder.py  run_pipeline.py
```

> **These mounts shadow the image.** Before deploying a newly built API image,
> remove the mount lines from the overlay, or the old patched copies silently win.
> The same code lives in the local repo, uncommitted.

Deploy loop used throughout:

```bash
# copy the changed file, restart, verify the container runs exactly it
gcloud compute scp api/services/pipecat/<file>.py dograh-app:~/dograh/dograh/deploy/gcp/patches/ \
  --zone=europe-west1-b --project=dograh-eu --tunnel-through-iap
# on the VM:
docker compose up -d api          # wait for healthy
docker compose restart nginx      # nginx caches the api container's old IP
docker compose exec -T api md5sum api/services/pipecat/<file>.py
```

Images are built with Cloud Build (`deploy/gcp/cloudbuild.yaml`); current tags are
`dograh-api|dograh-ui: latest, vertex-retry, 6ef81149` and `asterisk-voiptel:22`.

**Database backups:** take one before any schema or bulk change,
`gcloud sql backups create --instance=dograh-pg`. A pre-experiment backup exists
(`1789138769498`).

---

## 3. Telephony: VoIPTel, Asterisk and the control link

### Call path

```
VoIPTel PBX ──SIP/TCP 5071──► Asterisk (dograh-sip) ──Stasis(dograh)──► Dograh ARI manager
                                    │                                        │
                                    └──── RTP udp 10000-10120 ───────────────┘
                                    ext media channel ──ws──► api :8000 /telephony/ws/ari
```

### Registration (Asterisk → carrier)

- Registers as extension **7065** to **`demo7062.skyphonecentral.com:5071`** over **TCP**,
  at VoIPTel's request (moved from 5060 on 2026-09-11).
- Our Contact advertises `104.155.49.203:5071`.
- Asterisk 22 runs in Docker with host networking, `INBOUND_MODE=stasis`,
  `STASIS_APP=dograh`, `DOGRAH_WS_URI=ws://10.132.0.2:8000/api/v1/telephony/ws/ari`.
- The bind port lives in `~/asterisk-voiptel/etc/pjsip.conf` on the VM, bind-mounted
  over the image's template so a port change needs no 30-minute Asterisk rebuild.

Check it:

```bash
docker exec asterisk-voiptel asterisk -rx "pjsip show registrations"   # expect: Registered
docker exec asterisk-voiptel asterisk -rx "pjsip show contacts"        # expect: Avail
```

### The control link (Dograh → Asterisk) — and the trap that bit us

**Registration and the control link are different things.** Registration only tells the
carrier where to send calls. The agent is reachable only if Dograh has also opened an
ARI WebSocket to Asterisk on port 8088 and registered the Stasis app `dograh`:

```bash
docker exec asterisk-voiptel asterisk -rx "ari show apps"   # expect: dograh
```

Dograh opens that link **only for telephony configurations that are active**
(`telephony_configurations.inactive = false`).

> **The trap.** If the app VM runs while the SIP VM is off, the ARI manager retries
> for an hour and then **parks the configuration**: `inactive = true`, with
> `inactive_reason = "ari-timeout: ..."`. Parking is **one-way by design**
> (`api/services/telephony/ari_manager.py`, auto-deactivation policy) — it never
> un-parks itself, so calls ring and drop with no agent while registration still
> looks perfectly healthy. This happened on 2026-09-12 at 01:06.

**Never start one VM alone.** Start both, or expect to reactivate afterwards:

```python
await db_client.set_telephony_configuration_active(config_id=3, organization_id=1)
```

The manager re-reads configurations every 60 s; the link then connects in milliseconds.

### Inbound routing

One row maps the number to a workflow, and one number maps to exactly one workflow:

```sql
-- telephony_phone_numbers: id 1, address 7065, telephony_configuration_id 3
UPDATE telephony_phone_numbers SET inbound_workflow_id = 3 WHERE id = 1;  -- back to production
```

### Open items with VoIPTel

- **The full carrier source-IP list.** Only `84.39.233.90` is confirmed for signalling;
  `.91` was added for media. If a call connects with no audio, media is arriving from
  an address the firewall doesn't allow — see `app-doc/voiptel-connection-questions.md`.
- **A real DDI** for end-to-end testing from the PSTN.
- **Whether they can deliver calls over a webhook + WebSocket** instead of SIP, which
  would remove Asterisk entirely — `app-doc/voiptel-media-streaming-ask.md`.

---

## 4. Workflows

All in organization 1. Workflow 3 is the production agent and was never modified;
each experiment is a copy.

| ID | Name | Ver | Mode | Main model | Router | Filler | Turn start |
|---|---|---|---|---|---|---|---|
| 3 | CH Marine product enquiries | 10 | pipeline | gemini-3.5-flash | — | — | default |
| 4 | CH Marine low latency | 4 | pipeline | gemini-3.5-flash | — | on | min_words |
| 5 | CH Marine realtime | 2 | realtime | gemini-live-2.5-flash-native-audio | — | on | min_words |
| 6 | **CH Marine fast router** | 4 | pipeline | gemini-3.5-flash | gemini-2.5-flash-lite | on | min_words |

**Workflow 4** — the pipeline baseline: a static text greeting (no LLM call), the
greeting stage merged into the main stage (removing one round trip), tool copies that
speak a line before each lookup, `min_words` so noise cannot interrupt, and the input
silence filler.

**Workflow 5** — speech-to-speech, **rejected**. See §5.

**Workflow 6** — workflow 4 plus the fast router. See §6.

Tools are org-scoped rows; the nodes reference them by UUID. The two sidecars run on the
app VM with no published ports, reachable only from the api container:
`http://chmarine-product-service:8080` and `http://calendar-shim:8080`, authenticated
with `X-API-Key`.

---

## 5. What we measured about latency

Full detail in `app-doc/voice-latency-router-design.md`. The short version:

**A typical turn on workflow 4 (run 113), from the caller stopping to the first sound:**

| Stage | Time | Share |
|---|---|---|
| VAD confirms silence | ~0.2 s | 5 % |
| **Google STT final transcript** | **2.10 s** | **50 %** |
| Gemini's first token | 1.00 s | 24 % |
| First sentence + TTS buffer | 0.40 s | 10 % |
| Asterisk → carrier → handset | ~0.5 s | 11 % |

**Progress across the runs** (runs exist up to 122; 115–118 and 120–122 are unanalysed):

| Run | Setup | Result |
|---|---|---|
| 108 | workflow 3 | 9.5 s per turn — the caller's line dropped audio in silence, stalling STT 4–8 s |
| 109 | workflow 4 on gemini-2.5-flash | 3.0 s, but silent goodbye and a wrong booking — model reverted |
| 111 | workflow 4 + silence filler | STT wait 2.6–3.2 s → **2.18 s**; filler covered 39 % of the call |
| 112 | workflow 5 realtime | no faster (3.37 s), worse transcription, wrong digit booked — **rejected** |
| 113 | workflow 4 baseline | 3.48 s per turn / 4.2 s heard |
| 114 | workflow 6 router | **3.04 s** per turn / 3.9 s heard; first sound after 0.89 s instead of 1.40 s |

**Model verdicts** (each reproduced 6/6 on the exact failing turns):

- **gemini-3.5-flash** — the only reliable main model. Ends the call correctly, honours
  number corrections.
- **gemini-2.5-flash** — returns an *empty* reply to "no, I'm good" and ignores a
  corrected phone number. Unusable as the main agent; fine as a narrow router.
- **gemini-3.5-flash-lite** — books without confirming and mangles numbers. Unusable
  as the main agent.
- **Gemini Live (2.5 native audio)** — no latency gain, transcription errors (one reply
  transcribed as Hindi), wrong digit booked, ~20 s stall at the goodbye.

**Two fixes that worked, both switched on per workflow:**

1. **Input silence filler** (`input_silence_fill_enabled`). Some phone lines stop sending
   audio during silence — 39–62 % of these calls. Google then cannot tell the caller
   finished, so transcripts stall and its stream eventually times out (`409`). The filler
   feeds real-time silence into the input so STT and VAD see the pause immediately. Worth
   ~0.5 s per turn, and it also improved accuracy.
2. **Fast router** (`fast_router`). See §6.

**The biggest remaining lever is speech recognition** (~50 % of the delay). `chirp_3`
emits finals only — one interim in a 78-second call — so nothing can start earlier.
Deepgram's EU endpoint finalises in ~0.3 s instead of ~1.2 s, which needs an account, a
DPA, and a small change to pass `base_url`.

---

## 6. The fast-router pattern

**The idea.** The main model takes ~1 s to decide anything, and a tool's scripted line
can only play *after* that decision. A light model can read the same words and produce a
short acknowledgement in ~0.3 s, so the agent starts speaking sooner.

```
caller's words ready
   ├──► main Gemini (unchanged, ~1 s)  ────────────► real answer
   └──► light model (~0.3 s) ─► "Sure, one moment." (spoken first)
```

**Implementation** (`api/services/pipecat/fast_router.py`):

- `FastRouterProcessor` sits before the main LLM. It forwards the context frame **first**,
  so the main model is never delayed, then asks the light model in the background.
- `AckGate` sits before TTS and speaks the acknowledgement **only if** no answer text has
  reached TTS for that turn. The gate must be *after* the LLM: the Google service handles
  a context frame inline, so anything queued in front of it would be spoken *after* the
  answer.
- **One filler per turn.** If the router spoke, the tool's scripted line is dropped; if the
  router stayed silent (on "yes", names, numbers, goodbyes), the tool's line plays. This
  fixed a 5.3 s silence during the booking confirmation in run 114.
- **Safety:** the acknowledgement is rejected if it contains digits or currency, exceeds
  8 words, or the route is `end_call`. The router can never answer, book or end a call.
- **Fails safe:** on timeout (1.2 s) or error, nothing is spoken and the turn behaves
  exactly as workflow 4.

**Configuration** lives in `workflow_configurations.fast_router` — the UI does not render
it, but it survives edits because the dialog preserves unknown keys:

```json
{"enabled": true, "model": "gemini-2.5-flash-lite", "location": "europe-west1",
 "timeout_ms": 1200, "history_messages": 6, "prompt": "…"}
```

**The prompts are split.** The router's own short prompt forbids stating prices, times or
facts and tells it to stay silent on confirmations and goodbyes. The main model's prompt
says an acknowledgement has usually been spoken, so it must not add its own.

**Measured:** router decisions in 265–635 ms; first sound 0.67–0.84 s after the words are
ready, against 1.2–1.4 s on workflow 4. **Cost: $0.00018 per turn** (423 input + 23 output
tokens), about **$1.84 per 1,000 calls**, roughly 2 % on top of the main model.

**Log lines to grep:**

```
FastRouterProcessor#0: route=product_search ack='Sure, let me look that up.' 468 ms -> spoken
AckGate#0: dropped 'Let me have a look for you.'; the router already acknowledged this turn
InputSilenceFiller#0: filled 36.9s of silence in 54 gaps over 71.4s (52%)
```

Neither Dograh nor pipecat has a native router pattern; this is built on pipecat's
standard processor interfaces. The closest in-repo precedent is the voicemail detector's
parallel classifier.

---

## 7. Code changed in this work (all uncommitted)

| File | Change |
|---|---|
| `api/services/pipecat/input_silence_filler.py` | new — fills inbound audio gaps |
| `api/services/pipecat/fast_router.py` | new — `FastRouterProcessor`, `AckGate`, safety filter, Vertex decider |
| `api/tests/test_input_silence_filler.py` | new — 4 tests |
| `api/tests/test_fast_router.py` | new — 13 tests |
| `api/services/pipecat/pipeline_builder.py` | slots for the filler, router and gate |
| `api/services/pipecat/run_pipeline.py` | builds both when the workflow enables them |
| `api/services/pipecat/service_factory.py` | **Vertex 429 retry** — google-genai ships a retry policy but leaves it off, so one rate-limit error killed a turn |
| `deploy/gcp/**`, `deploy/asterisk-voiptel/**` | the whole deployment, still untracked |

Run tests with:
`source venv/bin/activate && set -a && source api/.env.test && set +a && python -m pytest api/tests/test_fast_router.py api/tests/test_input_silence_filler.py -q`

---

## 8. Operating notes

**Start / stop**

```bash
gcloud compute instances start dograh-app dograh-sip --zone=europe-west1-b --project=dograh-eu
# always both — see the parking trap in §3
```

**Health after a boot**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://35-240-85-9.sslip.io/api/v1/health   # 200
docker compose ps                                                # on dograh-app
docker exec asterisk-voiptel asterisk -rx "pjsip show registrations"   # Registered
docker exec asterisk-voiptel asterisk -rx "ari show apps"             # dograh
```

**Analysing a call**

- Per-turn events: `workflow_runs.logs -> 'realtime_feedback_events'`, which carry
  `rtf-user-transcription`, `rtf-bot-text`, `rtf-ttfb-metric`, `rtf-latency-measured`,
  `rtf-function-call-*` and `rtf-pipeline-error`.
- `rtf-latency-measured` is VAD-stop → first bot audio. Splitting it at the final
  transcript separates the STT wait from everything after it.
- Recordings: `gs://dograh-voice-audio-eu/recordings/<run>/user.wav` and `bot.wav`,
  plus the mixed `recordings/<run>.wav`. Measuring silence between the caller's speech
  ending and the bot's audio starting gives the **true caller-perceived gap**; digital
  zeros in `user.wav` mean the line sent nothing at all.
- API logs: `docker compose logs api --since 2h | grep -F "[run_id=NNN]"`. Container logs
  are **UTC**; the schedule and everything else here is Europe/Dublin.

**Gotchas that cost time**

- A bare `docker compose up` without the overlay points the API at an empty local
  Postgres. `COMPOSE_FILE` in `.env` prevents it.
- After recreating the api container, **restart nginx** or it serves 502 from a stale IP.
- `gcloud compute ssh` fails with "failed to connect to backend" while a VM is still
  booting — retry, it is not an error.
- Quoting: send SQL and scripts to the VM **base64-encoded**; `$$`-quoting gets mangled
  in transit.

---

## 9. Open items

**Security**

- **Signup is open** (`ENABLE_SIGNUP` unset defaults to true). Anyone reaching the public
  URL can register, and each signup provisions a model key and SIP connectivity. Set
  `ENABLE_SIGNUP=false`.
- The VPC's `default-allow-ssh` still permits tcp 22 from 0.0.0.0/0, which defeats the
  IAP-only intent of `allow-ssh-iap`.
- `external_credentials.credential_data` is stored in plaintext despite the model comment.
- Tool rows store their `X-API-Key` in the database, and the same key lives in the
  sidecars' `.env`. Rotating means changing both.

**Product / infrastructure**

- Put the deployment and the new code into git — production currently runs code that
  exists only on one laptop and one VM.
- Remove the patch mounts when a new API image is built.
- Decide on Deepgram EU for speech recognition (the largest remaining latency win).
- A static farewell line on the End Call node would remove one LLM round trip from the
  ~6 s goodbye.
- Prompt caching: only 0–16 % of the main model's prompt is cached, and it is ~97 % of
  the AI spend.
- Self-healing for the parked-config trap: a 5-minute check that reactivates a config
  **only** when its reason is a timeout **and** port 8088 is reachable.
- Point 7065 back to workflow 3 when testing ends.

---

## Appendix A — what was tried, in order

Times are Europe/Dublin. Every experiment was a copy; workflow 3 was never modified.

### 2026-09-10 — getting onto GCP

| What | Outcome |
|---|---|
| Built the two VMs, Cloud SQL, bucket, registry; migrated the local Postgres and MinIO data | 2 users, 2 orgs, 3 workflows, 96 runs restored; recordings served from signed GCS URLs |
| Google APIs and IAM | Enabled speech, texttospeech, aiplatform; granted `roles/speech.client`; fixed a stale `project_id` that lived in **8** rows (1 org config + 7 workflow definitions), which is why changing it in the UI alone didn't work |
| Vertex 429 "resource exhausted" | Root cause: google-genai ships a retry policy but **leaves it disabled**, so one rate-limit error killed a turn. Fixed in `service_factory.py`, built as image tag `vertex-retry` |
| A bare `docker compose up -d api` | Pointed the API at an **empty local Postgres** for ~10 minutes. Nothing was written to it. Fixed by pinning `COMPOSE_FILE` in `.env` |
| Added the user `ambrish.java@gmail.com` to org 1 | Sees all workflows; there are no roles, so every org member has full access |

### 2026-09-11 — telephony change and the latency work

| Time | What | Outcome |
|---|---|---|
| morning | VoIPTel asked for SIP on **5071** and registration by domain | `pjsip.conf` bind moved to 5071 and bind-mounted; `allow-sip` updated; registration healthy |
| morning | Core services had **no restart policy**, so the 19:00 stop left the platform down until started by hand | `restart: unless-stopped` added to api, ui, nginx, redis, minio |
| 13:01 | **Run 108**, workflow 3 | 9.5 s per turn. Caller's line sent **no audio during silence** (66 % digital zeros), so Google couldn't finalise; one Google stream died with `409` |
| — | **Workflow 4** created (static greeting, merged stage, tool lines, shorter answers, gemini-2.5-flash EU) | — |
| 15:13 | **Run 109** | 3.0 s per turn, but the goodbye went silent and a **wrong phone number was booked** — both traced to 2.5-flash, reproduced 6/6 |
| — | Reverted workflow 4 to gemini-3.5-flash, added `min_words` so echo can't interrupt | — |
| 16:40 | **Run 110** | 4.2 s heard; line 60 % gaps |
| evening | **Input silence filler** built, tested, deployed as a mounted file | — |
| 18:11 | **Run 111** | STT wait 2.6–3.2 s → **2.18 s**; turn 3.40 s; filler covered 39 % of the call |
| — | **Workflow 5** created — Gemini Live speech-to-speech, europe-west1, voice Aoede | — |
| 19:37 | **Run 112** | **Rejected**: no faster (3.37 s), "life jacket" heard as "jacket in the background", one reply transcribed as Hindi, wrong digit booked, ~20 s stall at the goodbye |
| 18:42 | **Run 113**, workflow 4 baseline | 3.48 s per turn / 4.2 s heard — the reference for the router |
| evening | **Fast router** designed and built; **workflow 6** created | — |
| 20:44 | **Run 114** | **3.04 s** per turn; acknowledgements spoken 468–635 ms after the words were ready; first sound 0.89 s instead of 1.40 s. One regression: the booking confirmation sat silent for 5.3 s |
| 20:5x | Fixed with **one filler per turn** (workflow 6 v3): the tool's line plays when the router stays silent | — |
| 21:0x | Router switched to **gemini-2.5-flash-lite** (v4) after measuring 0.347 s against 0.568 s | — |

### 2026-09-12 — the parked-config morning

| Time | What | Outcome |
|---|---|---|
| 00:00 | Both VMs stopped on the schedule | — |
| 00:02 | **App VM started alone** to read the database | Mistake: the ARI manager kept reaching for an Asterisk that was off |
| 01:06 | Dograh **parked the telephony config** (`ari-timeout`) | Registration stayed healthy, but no agent could be reached — parking is one-way |
| 10:05 | Both VMs started | Registration fine; `ari show apps` **empty** — the manager found no active config and idled |
| 10:39 | Config reactivated | WebSocket connected in 6 ms; `ari show apps` → `dograh` |
| 10:44 | **Run 119** | A real call reached workflow 6 and ran cleanly — the chain is proven end to end |
| — | Schedule changed twice: 08:00–12:00, then the stop moved to **23:00** | Runs 08:00–23:00 daily until changed |

Schedule history: 08:00–19:00 weekdays → stop moved to 00:00 daily → 08:00–12:00 → 08:00–23:00.

Runs exist up to **122**; 115–118 and 120–122 have not been analysed.

---

## Appendix B — what a fresh session reloads automatically

These are stored outside the repo, in Claude's project memory, and are loaded at the
start of every session:

| Memory | Why it matters |
|---|---|
| `server-first-then-sync-repo` | Apply and test GCP changes on the servers first, then mirror into the repo |
| `chmarine-low-latency-experiment` | Workflows 4/5/6, what 7065 points at, the patch mounts, and the results so far |
| `gemini-flash-variants-break-chmarine-agent` | 2.5-flash and 3.5-flash-lite fail the end-call and number-correction turns; keep 3.5-flash |
| `ari-config-parks-when-sip-vm-off` | Never start the app VM alone, or the telephony config parks itself |

This document plus `voice-latency-router-design.md` hold the detail; the memories hold the
handful of facts that would otherwise be re-learned the hard way.
