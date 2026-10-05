# VoIPTel — media streaming capability: what to ask, and how

Companion to `voiptel-connection-questions.md`. That document assumes the SIP
path (register as extension 7065, terminate SIP/RTP in our own Asterisk). This
one covers the alternative VoIPTel raised in the meeting: that they can deliver
a call to an **HTTP webhook plus a WebSocket audio stream**, which would remove
Asterisk from the picture entirely.

---

## Why the ask has to be precise

"We can do webhooks and websockets" is true of almost every modern platform and
tells us nothing. What decides whether this works is the **wire format**, and
there are only three outcomes:

| Tier | What they can do | Work on our side |
|---|---|---|
| **1** | Twilio-compatible: TwiML-shaped webhook + Twilio Media Streams JSON | Near zero. Precedent: Cloudonix is a non-Twilio carrier already running through our TwiML endpoint (`providers/cloudonix/provider.py:92`, serializer inherits `TwilioFrameSerializer`). |
| **2** | Their own documented webhook + WS audio format | New provider package: config + provider + serializer + transport. Bounded — seven exist as templates — but it needs their full spec up front. |
| **3** | SIP/RTP only; "websocket" meant something else (call events, CDR push, a browser SDK) | Asterisk stays. Current plan continues. |

The failure mode to avoid: they say yes, we build, and then discover mid-project
that the stream is receive-only (no agent audio back into the call), or that
there is no way to flush their playout buffer, which makes barge-in impossible
and the agent talks over the caller.

So: ask which tier, and demand the spec.

---

## The email

> Subject: Follow-up — media streaming (webhook + WebSocket) for the Dograh integration
>
> Hi <name>,
>
> Following our call, you mentioned you can deliver an inbound call to an HTTP
> webhook and stream the call audio over a WebSocket, rather than us taking the
> call over SIP. If that's available it is our strongly preferred path — it
> removes the SIP/RTP infrastructure on our side entirely, and it removes the
> NAT and port-forwarding questions we had been working through.
>
> Before we commit to it, could you confirm a few specifics? We've kept these to
> the points that actually change our implementation.
>
> **First, the quickest question:** is your media streaming interface
> **Twilio-compatible** — i.e. a TwiML-style webhook, and a Media Streams
> WebSocket carrying `{"event":"media","media":{"payload":"<base64 G.711>"}}`
> frames? If yes, we are essentially already integrated and the rest of this
> email is moot. We already run a non-Twilio carrier over that same interface.
>
> If it is your own format, please send us the developer documentation, and
> confirm the following:
>
> **The webhook**
> 1. What HTTP request do you send when a call arrives — method, content type,
>    and a sample payload?
> 2. Does it include a stable identifier for our account/tenant, plus the
>    calling number and the dialled number? We use the account identifier to
>    route the call to the right customer, so it needs to be in every payload.
> 3. Is the webhook signed (HMAC, JWT, shared secret)? What is the scheme?
> 4. Does our HTTP response control the call — i.e. can we reply with an
>    instruction to start streaming — or is the webhook informational only, with
>    streaming configured statically in your portal?
>
> **The audio WebSocket**
> 5. **Direction of connection:** do you connect out to a URL we host? We cannot
>    dial into your platform per call, so we need you to be the client.
> 6. Can that URL be a fixed base URL to which you append per-call query
>    parameters, or do you pass call identity in a first WebSocket message? We
>    need to correlate the socket with the webhook that preceded it.
> 7. **Is it bidirectional?** Specifically, can we send audio *back* on the same
>    socket and have it played to the caller? A receive-only stream does not
>    work for us.
> 8. **Audio format:** codec, sample rate, channels, and frame size — e.g.
>    G.711 µ-law, 8 kHz, mono, 20 ms frames. G.711 µ-law at 8 kHz is ideal;
>    linear PCM 16-bit is also fine.
> 9. **Framing:** raw binary WebSocket frames, or JSON with base64 audio? One
>    audio frame per WebSocket message?
> 10. Is there a handshake — a `start`/`connected` message with call metadata —
>     or does audio begin immediately? Do you require a specific
>     `Sec-WebSocket-Protocol` subprotocol?
> 11. **Interruption handling — the important one.** When the caller starts
>     speaking while our agent is talking, we need to stop the agent's audio
>     immediately. Is there a control message that **clears or flushes any audio
>     we have already sent but which is still queued for playout**? Without it,
>     the agent keeps talking over the caller for as long as your buffer is
>     deep. If there is no such message, how much audio do you buffer ahead?
> 12. What is the typical one-way latency from your media edge to the WebSocket,
>     and where is that edge hosted geographically?
>
> **Call control and events**
> 13. How are DTMF digits delivered — as a WebSocket event, in-band audio, or
>     not at all?
> 14. How do we **end the call** from our side? A WebSocket message, an API
>     call, or simply closing the socket?
> 15. How are we notified that the **caller** hung up, and do we get a hangup
>     cause and a call-ended event?
> 16. Can we **transfer** the call to a human agent or an external number
>     mid-call? If so, by what mechanism?
>
> **Security and limits**
> 17. Is the WebSocket `wss://` (TLS)? How do you authenticate to us — bearer
>     token, a signed query parameter, mutual TLS, or source-IP only? If
>     source-IP, please send the full list or CIDR of addresses you will
>     connect from.
> 18. What is our concurrent-call limit on this interface?
>
> **To let us test**
> 19. Can you provide a test DID and a sandbox account so we can validate the
>     integration end to end before go-live?
>
> If it turns out the WebSocket streaming is for something else — call events,
> CDR delivery, or a browser SDK — just say so and we'll continue on the SIP
> path we already discussed; in that case the outstanding item there is still
> the SIP password for extension 7065, plus the registrar address question.
>
> Thanks,
> <you>

---

## How to read their answer

- **Q5 "we connect to you" + Q7 "yes, bidirectional" + Q11 "yes, there is a
  clear/flush"** — the integration is real. Proceed.
- **Q7 receive-only** — dead end for a voice agent. Fall back to SIP.
- **Q11 no flush, deep buffer** — technically works, but barge-in will be poor.
  Ask for the buffer depth before deciding; under ~200 ms is tolerable.
- **Q2 no account identifier in the payload** — we can work around it by giving
  them a per-tenant webhook URL, but say so early.
- **Q1 answer looks like TwiML** — jump straight to Tier 1, skip the rest.

## What changes on our side per tier

- **Tier 1**: a telephony configuration row, provider `cloudonix`-style
  detection added to `_detect_provider` (`api/routes/telephony.py:352`). Days.
- **Tier 2**: new package under `api/services/telephony/providers/voiptel/`
  mirroring an existing one (`plivo` and `vobiz` are the smallest), a serializer
  under `pipecat/src/pipecat/serializers/`, and a registry `ProviderSpec`.
  Weeks, not months — but only once their spec is in hand.
- **Tier 3**: `deploy/asterisk-voiptel/` as already built.
