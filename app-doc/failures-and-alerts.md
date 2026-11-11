# Failures: what gets logged, who is told, what callers hear

How LightMove handles things going wrong. Written 2026-11-06.

## 1. Every failure is logged

Classified failures go through `log_failure` (`api/errors/failure.py`). It
writes one structured line per failure, `DOGRAH_FAILURE [src=… type=… code=…]
[owner=…]`, with the workspace id and safe context. Secrets are redacted.
Search Cloud Logging (or Sentry, if `SENTRY_DSN` is set) for
`DOGRAH_FAILURE`.

| Field | Meaning |
|---|---|
| `source` | llm, tts, stt, telephony, transport, webhook, integration, tool, knowledge_base, platform |
| `type` | config_error, quota_error, provider_error, system_error |
| `owner` | `user`: the workspace can fix it. `operator`: we must fix it |

## 2. Critical failures alert a person

`api/services/failure_alerts.py` listens to every logged failure. Alerts are
queued as a background job (`send_failure_alert`), so a call is never slowed
down.

| Failure | Who is emailed | Example |
|---|---|---|
| owner `user`, type config, quota or provider, with a workspace | That workspace's **admins and owners** | A number with no agent, credit used up, their telephony account failing |
| owner `operator` | **Founders**: `OPERATOR_ALERT_EMAILS`, else every platform admin | A platform or system error |
| marked `notification_eligible: False` | Nobody (only logged) | A bad webhook signature, which anyone can send |

Each alert, per workspace and failure code, is sent **at most once every 6
hours**. The process skips repeats, and a Redis key stops several workers
from sending the same one.

## 3. Callers hear a plain line

When a call can't go through, before any agent starts, the carrier reads a
short line. It never reads configuration details.

| Situation | Caller hears |
|---|---|
| Call limit reached | "Sorry, all our lines are busy right now. Please try again in a few minutes. Goodbye." |
| Workspace being deleted | "This number is not in service. Goodbye." |
| Anything else (no agent on the number, out of credit, bad setup) | "Sorry, we can't take your call right now. Please try again later. Goodbye." |

The detailed reason stays in the log and the workspace's alert. During a
call, the agent's tools return a `say` line and a `handoff` (see
`bookings-and-roles.md`), so the agent transfers the caller or takes a
message rather than failing silently.

## 4. Production refuses unsafe settings

With `ENVIRONMENT=production` the API won't start, and logs a CRITICAL line
naming the problem, when:
- email is off (nobody could sign up);
- billing is off (calls would be free);
- links point at localhost.

`ALLOW_INCOMPLETE_PRODUCTION_CONFIG=true` starts it anyway, for a deliberate
choice such as no billing. See `api/services/production_readiness.py`.

## Not covered yet

- What a caller hears if the agent itself crashes mid-call. The call ends as
  `PIPELINE_ERROR`; a spoken apology before hanging up is still to do.
- Running out of credit mid-call still cuts the call without a goodbye.
- No alert is sent when the API refuses to start, since it can't send
  email. Use Cloud Logging log-based alerts on CRITICAL lines.
