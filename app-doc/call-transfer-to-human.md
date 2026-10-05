# Call transfer to a human extension

How "I want to talk to a human agent" works in this deployment, why it failed in
run 122, and what was changed on 2026-09-12.

## Summary

Transfer is not a feature that needs building. It is implemented end to end in
Dograh for the ARI provider, and the CH Marine agent has already been calling it.
The only defect was the destination string: it named an Asterisk endpoint that
does not exist.

## The path a transfer takes

1. **The model calls the tool.** `transfer_to_team`
   (`153b6f07-6f78-46b4-9ae0-30da9be12b99`) is a `transfer_call` tool attached to
   the "Main Agenda" node of workflows 3, 4, 5 and 6. It takes no arguments. Its
   description tells the model to use it when the caller says yes to speaking
   with someone, or when a question needs a human.

2. **The router speaks first.** With the fast router on, the caller hears an
   acknowledgement before the tool even runs. Run 122:
   `route=transfer ack='Of course, one moment.' 422 ms -> spoken`.

3. **The destination is resolved.**
   `_create_transfer_call_handler` (`api/services/workflow/pipecat_engine_custom_tools.py:558`)
   rejects text chat and WebRTC modes, then calls `resolve_transfer_config`.
   This tool uses `destination_source: "dynamic"`, so it POSTs to
   `http://chmarine-product-service:8080/transfer_destination`, which returns
   `transfer_context.destination` and a spoken `custom_message`. Took 25 ms.

4. **A second call leg is originated.**
   `ARIProvider.transfer_call` (`api/services/telephony/providers/ari/provider.py:425`)
   POSTs `/channels` with `endpoint=<destination>`, `app=dograh` and
   `appArgs=transfer,<transfer_id>`. The pipeline is muted and hold music plays.

5. **Dograh waits on Redis pub/sub.** When the destination channel answers, it
   arrives in Stasis with those appArgs; `ari_manager` correlates it and
   publishes `DESTINATION_ANSWERED`. Busy, no-answer and rejection map from the
   SIP cause code.

6. **The legs are swapped.** The handler ends the pipeline with
   `EndTaskReason.TRANSFER_CALL`. `AsteriskFrameSerializer` sees that reason and
   runs `ARIBridgeSwapStrategy` (`providers/ari/strategies.py:15`): add the
   destination channel to the caller's existing mixing bridge, remove the bot's
   external-media channel, hang that channel up.

The caller and the human stay in the bridge that was already carrying the call.
This is a bridge swap, not a SIP REFER — nothing in the repo sends a REFER — and
it is the right choice here, because the caller's audio path is never rebuilt.

If the transfer fails at any step the agent is **not** dropped: the failure is
returned to the model as a tool result with a spoken explanation, the pipeline is
unmuted, and the conversation continues. Run 122 did exactly this and went on to
book a callback instead.

## Why run 122 failed

```
[ARI Transfer] Initiating transfer ... to PJSIP/chmarine-sales (timeout: 30s)
[ARI Transfer] ARI channel creation failed: 500 {"error": "Allocation failed"}
```

Asterisk's own log gives the real reason:

```
chan_pjsip.c:2794 request: Unable to create PJSIP channel
  - endpoint 'chmarine-sales' was not found
```

`provider.py:469-472` passes a destination through unchanged when it already
starts with `PJSIP/` or `SIP/`, and otherwise wraps it as `PJSIP/{destination}`.
Either way the part after `PJSIP/` must name a **configured endpoint**. In
dograh-sip there is exactly one:

```
Endpoint:  voiptel     Not in use    0 of inf
  OutAuth:  voiptel-auth/7065
Objects found: 1
```

`chmarine-sales` was a placeholder that was never a dialable thing.

## The fix

Destinations must be trunk-qualified, the same shape the `dograh-outbound`
dialplan context uses (`Dial(PJSIP/${EXTEN}@voiptel,60)`):

| Destination | Result |
|---|---|
| `PJSIP/chmarine-sales` | `endpoint 'chmarine-sales' was not found` |
| `PJSIP/200@voiptel` | allocates; Asterisk logs `Called 200@voiptel` |

Verified on 2026-09-12 by originating to an unassigned extension, which rings
nobody:

```bash
asterisk -rx "channel originate PJSIP/999999@voiptel application Echo"
#  -- Called 999999@voiptel
```

**What changed.** One environment variable on dograh-app:

```
deploy/gcp/secrets/product-service.env
-TRANSFER_DESTINATION=PJSIP/chmarine-sales
+TRANSFER_DESTINATION=PJSIP/200@voiptel
```

then `docker compose up -d chmarine-product-service`. Backup:
`product-service.env.bak-2026-09-12-transfer`.

No Dograh code, no image rebuild, no workflow republish. Because all four
workflows share the one tool, they all move together.

## Testing it

Call 7065 and say "I want to talk to a human". Expect: the acknowledgement, then
"No problem, let me put you through now. One moment.", then hold music, then
ext 200 rings.

**Caveat:** if you place the test call *from* ext 200, the transfer dials ext 200
back and will most likely come back busy. That still proves the fix — a `486
Busy` means the channel allocated and the INVITE reached the PBX, which is
exactly what was broken. For a clean end-to-end test, call from a different
handset than the one you want to ring.

## If you want a proper feature rather than a single destination

- **Route by department.** The resolver already supports it; return a different
  destination per call. Or switch the tool to `destination_source:
  "context_mapping"` and drive it from gathered context with no HTTP hop.
- **Bare extensions.** To write `200` instead of `PJSIP/200@voiptel`, the ARI
  provider needs an outbound-trunk config field, the way Cloudonix has
  `outbound_trunk_name`, applied in `provider.py:469-472`. That is a code change
  and would need a patch mount.
- **Business hours.** Nothing checks whether anyone is there. Today an
  out-of-hours transfer rings out for the full 30 s timeout before the agent
  apologises. The resolver is the natural place to decide, since it can return a
  failure and let the agent offer a callback instead.
