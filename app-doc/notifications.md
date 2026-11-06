# After-call notifications: how they work

What the business hears about its calls, what the caller is texted, and how
to switch texts on. Last updated 2026-11-06 (PR "post-call notifications").

## 1. What gets sent

After each **inbound phone call**, at most:

- **one email to the business**, about the most important thing that
  happened on the call: a booking, a message, or a missed call;
- **one text to the caller**, only when the calendar confirmed a booking.

Nothing is sent for browser test calls (WebRTC), text chats, or outbound
calls. The rule is the run's `mode` (a phone provider such as `twilio`, `ari`,
`telnyx`, i.e. the telephony channel in `WORKFLOW_RUN_MODES_BY_CHANNEL`) and
`call_type = inbound`.

## 2. Which email

The email picks the first of these that applies:

| Email | When |
|---|---|
| **New booking** | A `book_appointment` call to the calendar answered `booked: true` with an event id, and no later `cancel_appointment` on the same call cancelled it. |
| **New message** | The agent captured any of `caller_name`, `callback_number`, `call_reason`, or `booking_outcome` is `requested`. Also when `booking_outcome` is `booked` but the calendar never confirmed a booking: the email then says "The agent noted a booking, but the calendar did not confirm one" so someone checks. |
| **Missed call** | See below. |
| nothing | Anything else, e.g. the caller asked about opening hours, got an answer and said goodbye, or a person took the transferred call. |

### What counts as a missed call

An inbound phone call with no booking and no message, where one of these is
true (checked in this order, from the stored run):

1. **It never reached the agent**: `call_status` is `no-answer`, `busy`,
   `failed`, `canceled` or `error` (the carrier's status callback, or a call
   rejected at the start).
2. **It broke**: `call_status` is `pipeline_error` or `unexpected_error`.
3. **The caller never spoke**: the run has no `user_speech` tag (no final
   transcription with words in it), e.g. they hung up during the greeting or
   stayed silent until the idle timeout.
4. **They hung up straight away**: `call_status` is `user_hangup` and the call
   lasted under 15 seconds (`usage_info.call_duration_seconds`).
5. **A transfer wasn't answered**: the call log has a transfer function result
   with `status: transfer_failed` (no answer, busy, no number set up), and the
   call then ended without a message.

A call ending in `transfer_call` (a person answered) is never missed.

The code is `api/services/call_notifications/outcome.py`; each rule has a test
in `api/tests/test_call_notifications.py`.

## 3. Who gets the email

- The workspace's **Owners and Admins** (roles `viewer` and `admin`) with an
  email address, unless "Send to owners and admins" is off.
- Plus up to 10 **extra addresses** (e.g. the restaurant's front desk).
- Each address once. Developers and Staff are not emailed.

Each email is short: what happened, the caller's details, and a **See the
call** link to `/workflow/{workflow_id}/run/{run_id}` in the app.

## 4. The text to the caller

```
Luigi's: your booking for Saturday 14 Nov at 7:30pm, table for 4, is confirmed. To change it call +35315550100.
```

- **Only for calendar-confirmed bookings.** Never from what the LLM extracted
  after the call (`booking_date`, `booking_time`, `party_size`).
- **Where the details come from.** Each tool call the agent makes is stored on
  the run in `gathered_context.tool_results` (`ToolExecutionOwner` →
  `PipecatEngine.record_tool_result`), with its arguments and result. MCP
  calls are stored there too: `function_name` is
  `mcp__<server>__book_appointment` and `result` is the tool's JSON text,
  `{"booked": true, "event_id": "...", "say": "..."}`. The calendar's result
  has no time in it, but the calendar books exactly the slot it is given:
  `slot_id` in the arguments is that slot's ISO time, and `party_size` is the
  size it stored on the event. So the text uses `slot_id` and `party_size`
  from the call the calendar said yes to.
- **Time** is read in the calendar's own time zone (the slot's offset), in
  English: "Saturday 14 Nov at 7:30pm". "table for N" only when a party size
  was given.
- **Business name**: the agent's `business_name` (setup wizard), else the
  workspace name. **Business number**: the number the caller dialled.
- **Who is texted**: the first usable mobile number of: the caller's line
  (`initial_context.caller_number`), the phone number given to the calendar,
  `callback_number`. Numbers are turned into E.164 with Ireland (+353) as the
  home country ("087 123 4567" → +353871234567). Withheld numbers and Irish
  landlines (they can't take texts) are skipped.
- If the agent books twice on one call, the text is about the latest booking;
  the email lists all of them.

## 5. Settings (per workspace)

**Settings → Notifications**, for Owners and Admins (`notifications:manage`):

| Setting | Default |
|---|---|
| Email us after calls | on |
| When a booking is made / a message is taken / a call is missed | all on |
| Send to owners and admins | on |
| Also send to | none |
| Text callers a booking confirmation | on (only sends once texting is set up) |

Stored as the organization configuration `CALL_NOTIFICATIONS`
(`GET`/`PUT /api/v1/organizations/notifications`).

## 6. Sent once, even on a retry

The post-call job (`api/tasks/workflow_completion.py`, last step; and the
standalone integrations job for calls that never reached the agent) claims a
row in `call_notifications` for (run, `email`) and (run, `sms`) **before**
sending. A retried or duplicate job finds the row and sends nothing. The row
keeps only the status (`sent`, `partial`, `failed`, or `logged` when no
provider is set up), how many recipients it reached, and the first error; no
addresses or content. It is deleted with the run.

At most once means a send that fails is not retried automatically; the
failure is in the row and the logs.

## 7. Switching texts on

Until then, texts are only logged (`SMS_PROVIDER=none`, the default). Calls and
emails work either way.

- **Locally / any install**: in `api/.env`
  ```
  SMS_PROVIDER=twilio
  TWILIO_SMS_ACCOUNT_SID=AC...
  TWILIO_SMS_AUTH_TOKEN=...
  SMS_FROM=+3531XXXXXXX     # a number on the Twilio account, or a sender id like LightMove
  ```
- **GCP**: create the secrets `dograh-twilio-sms-account-sid` and
  `dograh-twilio-sms-auth-token`, grant them to `dograh-app-sa`, and run
  `sudo DOGRAH_SMS_FROM=+3531XXXXXXX ./deploy/gcp/configure-env.sh` once,
  then `sudo docker compose up -d api`. See `deploy/gcp/README.md`, "Texts to
  callers".

A wrong value (missing token, bad sender) turns texts off with an error in the
log; it never stops a call or an email. Alphanumeric sender ids can't receive
replies, which is why the text gives the business number.

Emails use the existing email setup (`EMAIL_PROVIDER`, Resend in production).

## 8. Where things live

| Part | Code |
|---|---|
| What happened on the call | `api/services/call_notifications/outcome.py` |
| Email and text wording | `api/services/call_notifications/messages.py`, `api/services/email/templates.py` (`call_notice_message`) |
| Phone numbers | `api/services/call_notifications/phone.py` |
| Sending, once | `api/services/call_notifications/service.py`, `api/db/call_notification_client.py`, migration `c4e8f1a2b3d6` |
| Settings | `api/services/call_notifications/settings.py`, `api/schemas/call_notifications.py`, `api/routes/notifications.py`, `ui/src/app/settings/notifications/` |
| Text provider | `api/services/sms/` (`none`, `twilio` via its REST API) |
