# Email to Voiptel — SIP status + the webhook/streaming ask

Short, send-ready version. The long technical question list lives in
`voiptel-media-streaming-ask.md` — send that only once they confirm they have a
streaming interface and ask for detail.

---

> **Subject:** Dograh integration — SIP status, and a question on your webhook / media streaming option

Hi <name>,

Quick update on where we are with the SIP interconnect, and a question about the
alternative you mentioned on our call.

---

**1. What we have working on the SIP path**

- Built and deployed an Asterisk 22 server on our side, configured for your trunk.
- Registration to extension **7065** is **live and stable** — authenticating
  successfully and renewing cleanly on the 180-second cycle.
- Codecs agreed (G.711 µ-law/a-law), inbound call routing and our AI agent
  pipeline are wired up and ready.

So the SIP side is essentially built and waiting on you.

**2. Two things we found in the details you sent**

- `demo7062.skyphonecentral.com` resolves to `54.164.171.221`, which **refuses
  connections on port 5071**. The address that actually answers is
  `84.39.233.90`. We are pointing at that directly for now — could you correct
  the DNS record, or confirm we should keep using the IP?
- You listed `84.39.232.90` as the signalling/RTP address, but the live server
  is `84.39.**233**.90` — one digit apart. Please confirm which address your
  calls will actually come from. We need the full list if there is more than one.

**3. What we still need from you to complete the SIP test**

- **The PSTN number (DDI) that rings extension 7065.** We cannot place a single
  test call without it — this is the one item blocking us.
- The **concurrent call limit** on this extension.
- Confirmation of **DTMF method** (we expect RFC 2833).

---

**4. The better option — your webhook + media streaming**

On our call you mentioned you can deliver a call to an **HTTP webhook** and
stream the audio over a **WebSocket**. If that is available, we would strongly
prefer it, for concrete reasons:

- **It removes an entire server from the picture.** Today we have to run,
  secure and patch our own Asterisk just to convert your SIP into something our
  platform can consume.
- **It removes the whole class of SIP problems** — NAT traversal, RTP port
  ranges, firewall rules, IP allowlists, one-way audio. These are exactly the
  issues we have been working through above.
- **Our platform supports this natively.** Dograh is built to consume webhook +
  audio-stream telephony providers directly — that is how our other carriers
  connect. Your calls would reach our AI agents with no intermediate
  infrastructure at all.
- **It is faster to production and cheaper to scale.** Fewer moving parts, and
  no per-region SIP infrastructure to stand up as volume grows.

**5. What we need to know to evaluate it**

The quickest question first — if the answer is yes, most of the rest falls away:

- **Is your interface Twilio-compatible?** That is, a TwiML-style webhook plus a
  Twilio Media Streams WebSocket. If so, we are effectively already integrated.

If it is your own format, please send the developer documentation, plus:

1. **The webhook** — sample payload on an inbound call, and does it carry the
   calling number, the dialled number, and an account identifier? Is it signed?
2. **Who connects to whom** — do you open the WebSocket to a URL we host? We
   cannot dial into your platform per call.
3. **Is the audio bidirectional?** We must be able to send our agent's speech
   back on the same connection. A listen-only stream will not work.
4. **Audio format and framing** — codec, sample rate, frame size, and whether
   frames are raw binary or JSON/base64. G.711 µ-law at 8 kHz is ideal for us.
5. **Interruption handling** — when the caller speaks over our agent, is there a
   message that clears audio we have already sent but which is still queued for
   playback? Without it the agent talks over the caller. If there is none, how
   much audio do you buffer?
6. **Call control** — how DTMF digits reach us, how we end a call, how we are
   told the caller hung up, and whether we can transfer to a human.
7. **A test number and sandbox account**, so we can validate before go-live.

---

If the WebSocket you mentioned turns out to be for something else — call events,
CDRs, or a browser SDK — no problem, just let us know and we will continue on
the SIP path. In that case the only thing blocking us is the DDI for extension
7065, plus the two address questions in point 2.

Happy to jump on a short technical call with whoever looks after this if that is
quicker than email.

Thanks,
<you>
