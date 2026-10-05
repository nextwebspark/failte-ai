# Asterisk for the Voiptel / SkyPhone trunk

An Asterisk 22 container that registers to Voiptel's hosted PBX as a SIP
extension and hands inbound calls to Dograh over ARI. Inbound only.

Dograh has no `voiptel` provider and will not get one — Voiptel is a carrier
with no programmable-voice API. Asterisk is the programmable layer; Dograh
talks to Asterisk through the existing **Asterisk ARI** provider.

```
PSTN → SkyPhone PBX 84.39.233.90:5071
          ▲ outbound TCP REGISTER — inbound INVITEs return down this socket
          ▼ RTP UDP (symmetric)
   router NAT → this Mac
        └── asterisk container
              ├── ARI 8088 ──▶ ari_manager on the host, via 127.0.0.1:8088
              └── externalMedia WS ──▶ ws://host.docker.internal:8000/…/ws/ari
```

Both Dograh legs are host-local, so **cloudflared is not needed** for this
integration. Only SIP and RTP cross the internet.

---

## Before you start

You need from Voiptel:

| | Why |
|---|---|
| SIP username and password | over a secure channel, not email |
| Confirmation of the registrar host | done: `demo7062.skyphonecentral.com` → `84.39.233.90` since 2026-09-11, see below |
| Every source IP their INVITEs arrive from | for `type=identify` |
| The PSTN number that rings extension `7065` | there is no end-to-end test without one |

See [`app-doc/voiptel-connection-questions.md`](../../app-doc/voiptel-connection-questions.md)
for the reply that asks for exactly these.

**Already verified against their platform** (2026-09-02), so you do not have to
re-derive it:

| | |
|---|---|
| Working SIP host | `84.39.233.90:5071`, answers on **both TCP and UDP** |
| Their platform | `Sky DANCE` (FreeSWITCH-based hosted PBX) |
| Digest realm | `demo7062.skyphonecentral.com`, the same value as `SIP_DOMAIN` and `REGISTRAR_HOST` |
| Username `7065` | Accepted as an AOR — the server issues a digest challenge rather than rejecting outright |
| Missing | Only the password. A wrong one returns `401` then `403 Forbidden`. |

<!-- -->

> **Do not leave Asterisk running with a placeholder password.** Repeated failed
> REGISTERs look like a brute-force attempt and can get this IP banned at their
> edge. `forbidden_retry_interval = 300` in `pjsip.conf` throttles retries to
> once every five minutes after a 403, but stop the container
> (`docker compose down`) rather than letting it grind.

**Register by domain (since 2026-09-11).** `demo7062.skyphonecentral.com` used
to resolve to `54.164.171.221`, which refused 5071. VoIPTel repointed it at
`84.39.233.90` and asked us to register with the domain, so set
`REGISTRAR_HOST=demo7062.skyphonecentral.com`. They also asked for our own SIP
port to be 5071: `pjsip.conf` binds 5071, which is the port our Contact
advertises and where their PBX delivers INVITEs. Media arrives from
`84.39.233.91`, not only `.90`.

---

## Step 0 — prove the credentials before building anything

The image takes several minutes to build. Settle host, port, transport and
credentials first, in seconds:

```bash
cd /Users/alokkumar/dev/voice-agent-sass

# Is anything listening, and what is it?
python3 scripts/sip_register_probe.py \
  --host 84.39.233.90 --host demo7062.skyphonecentral.com \
  --port 5071 --transport tcp \
  --domain demo7062.skyphonecentral.com --options

# Do the credentials work? (password read from SIP_PASSWORD or prompted)
python3 scripts/sip_register_probe.py \
  --host 84.39.233.90 --port 5071 --transport tcp \
  --user 7065 --domain demo7062.skyphonecentral.com -v
```

A `200 OK` on one host and a failure on the other is the evidence to send back
to Voiptel. If the authenticated REGISTER returns `403 Forbidden`, the realm or
the `SIP_DOMAIN` is wrong — ask them for the exact realm.

---

## Step 1 — configure

```bash
cd deploy/asterisk-voiptel
cp .env.example .env
$EDITOR .env
curl -s https://api.ipify.org   # put this in PUBLIC_IP
```

`.env` is covered by the repo's root `.gitignore`. Keep it that way; the SIP
password does not belong in git.

## Step 2 — build and start

```bash
docker compose up --build -d
docker compose logs -f asterisk
```

The build fails deliberately if `chan_websocket` or `res_websocket_client` are
missing — those two modules are what carry audio to Dograh, and a silent
absence would only surface later as "the caller hears nothing".

## Step 3 — verify the modules and the registration

```bash
docker compose exec asterisk asterisk -rx "module show like chan_websocket"
docker compose exec asterisk asterisk -rx "module show like res_websocket_client"
docker compose exec asterisk asterisk -rx "pjsip show registrations"
docker compose exec asterisk asterisk -rx "pjsip show endpoint voiptel"
```

Expect both modules **Running** and the registration **Registered**. If it is
not:

```bash
docker compose exec asterisk asterisk -rx "pjsip set logger on"
docker compose logs -f asterisk
```

## Step 4 — verify ARI from the host

```bash
curl -s -u dograh:YOUR_ARI_PASSWORD http://127.0.0.1:8088/ari/asterisk/info | head
```

## Step 5 — configure Dograh

Start the backend with `ENABLE_ARI_MANAGER=true` (the default), then at
**/telephony-configurations → Add configuration → Asterisk ARI**:

| Field | Value |
|---|---|
| ARI Endpoint | `http://127.0.0.1:8088` |
| Stasis App Name | `dograh` — must equal `STASIS_APP` in `.env` |
| ARI Password | `ARI_PASSWORD` from `.env` |
| websocket_client.conf Name | `dograh` — same value again |
| From Extensions | leave empty; inbound only |

Then under **Phone numbers**, add `7065` — exactly the string the PBX presents —
and set its **Inbound workflow**.

`ari_manager` re-reads configurations every 60 seconds, so give a change a
minute before concluding it failed.

## Step 6 — place a test call

Dial the PSTN number that rings extension `7065`. Watch both sides:

```bash
docker compose exec asterisk asterisk -rvvv     # expect from-voiptel NoOp, then Stasis
tail -f ../../logs/latest/*.log                 # Dograh side
```

Success looks like: `from-voiptel` NoOp → `Stasis(dograh)` → an inbound workflow
run appears in Dograh → two-way audio.

---

## Troubleshooting

**Registration fails with 403.** Wrong realm or wrong `SIP_DOMAIN`. Run the
probe script with `-v` and read the `realm=` in the challenge.

**Registration succeeds but calls never arrive.** The PBX is signalling from an
IP not in `PBX_SIGNALLING_IPS`, or it is opening a fresh connection to our
Contact rather than reusing the registration socket. `line = yes` on the
registration covers the first case; the second needs TCP 5071 forwarded from
your router to this Mac.

**Call arrives, Dograh hangs up immediately.** Exactly two log lines explain it:
*"no matching phone number registered for config"* — the `EXTEN` reaching
`Stasis()` is not the string you stored, so read the `NoOp` line and store that
verbatim — or *"has no inbound_workflow_id assigned"*.

Note that `+7065`, `7065` and `sip:7065@host` are three different stored
addresses. There is no fuzzy fallback on the ARI path.

**The Dograh configuration keeps deactivating itself.** Either
`websocket_client.conf Name` is empty (`ari_manager` parks the config rather
than answering calls into silence), or five consecutive ARI auth failures parked
it — check `ARI_PASSWORD`.

**Calls connect but there is no audio, or audio one way.** In order:

1. `docker compose exec asterisk asterisk -rx "core show channels verbose"`
   mid-call and confirm G.711 was negotiated, not G.722 or G.729.
2. Confirm `PUBLIC_IP` in `.env` still matches `curl -s https://api.ipify.org`.
3. Set `PUBLIC_IP=` (empty) and restart — this strips `external_media_address`
   and relies on the far end latching to our RTP source address, which often
   works better through double NAT.
4. Enable Docker Desktop host networking
   (Settings → Resources → Network) and switch the compose file to
   `network_mode: host`.
5. If it still fails, move this container to a VPS with a public IP. Two layers
   of NAT plus UDP is the fundamental weakness of running Asterisk on a laptop;
   everything except the media leg will already have been proven out here.

**`TELEPHONY_WS_TOKEN_SECRET` mismatch.** The `api` process and `ari_manager`
must share it — `ari_manager` mints the media-WebSocket token and `api` verifies
it. With `TELEPHONY_WS_TOKEN_ENFORCE` on, a mismatch is a total outage with no
obvious symptom.

---

## What this deliberately does not do

- **No outbound.** Adding it means a `[dograh-outbound]` context dialling
  `PJSIP/${EXTEN}@voiptel`, a **From Extensions** value on the Dograh config,
  and answers from Voiptel about accepted caller ID and emergency calling.
- **No E.164 rewriting.** The PBX presents short extensions, Dograh stores them
  verbatim as `sip_extension`, and they match. Rewriting would break that.
- **No TLS or SRTP.** Voiptel offered neither on port 5071. Signalling metadata
  and audio are in the clear across the internet — acceptable for a demo trunk,
  not for production traffic.
