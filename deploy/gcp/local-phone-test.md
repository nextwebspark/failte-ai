# Testing a code change on a real phone call, from your laptop

Run the API from a branch on your laptop and answer calls to the live number
(7065, extension 200 → VoIPTel → Asterisk on the SIP VM) with it, **before**
anything is released. The live app is out of the call path for the duration of
the test; revert the moment you are done.

Use it for anything a browser test cannot reproduce: 8 kHz phone audio, a line
that stops sending audio in silence, Asterisk behaviour, real latency.

## How the live call path works

```
caller → VoIPTel → Asterisk (sip VM, container asterisk-voiptel, host network)
                     ├─ ARI  :8088   ← live ari_manager (app VM) connects out
                     └─ media: websocket_client "dograh" → ws://<app VM>:8000/api/v1/telephony/ws/ari
```

Asterisk's `Stasis(dograh)` app has **one** event stream per client, and every
connected client gets every call. So a local test needs two things:

1. the local `ari_manager` connected to Asterisk's ARI (SSH tunnel, `-L`);
2. Asterisk's media websocket pointed at the laptop (SSH reverse tunnel, `-R`);

and the **live ari_manager must be parked**, or both stacks answer each call.

## Before you start

- Both VMs running (`gcloud compute instances list --project dograh-eu`). They
  stop at 23:00 Dublin (`dograh-dev-hours`). Never start only the app VM
  ([ARI config parks](README.md) when the SIP VM is off).
- Nobody is on a live call: `docker logs dograh-api-1 --since 5m | grep "Created inbound workflow run"` on the app VM.
- Local services running: Postgres (5432), Redis (6379), MinIO (9000), and the
  tool sidecars `calendar-shim` (8090) and `chmarine-product-service` (8091).
- `gcloud auth application-default login` done, with `roles/aiplatform.user`
  on `dograh-eu`, so Vertex works with your ADC.
- The branch worktree is checked out, e.g. `git worktree add ../lm-test <branch>`.
- Side effects to accept: bookings go to the **real Google Calendar**
  (calendar-shim), and Vertex usage is billed to `dograh-eu`. Email is off.

## 1. Copy the live data

```bash
gcloud sql export sql dograh-pg gs://dograh-voice-audio-eu/exports/dograh-$(date +%F)-phonetest.sql.gz \
  --database=dograh --project dograh-eu
gcloud storage cp gs://dograh-voice-audio-eu/exports/dograh-$(date +%F)-phonetest.sql.gz ~/dev/backups/
docker exec voice-agent-sass-postgres-1 psql -U postgres -c "CREATE DATABASE lm_phone_test"
gunzip -c ~/dev/backups/dograh-*-phonetest.sql.gz \
  | docker exec -i voice-agent-sass-postgres-1 psql -U postgres -d lm_phone_test -q
```

One error is expected: `role "cloudsqlsuperuser" does not exist`.

Point the tools at the local sidecars (live uses Docker hostnames):

```sql
update tools set definition = replace(replace(definition::text,
  'http://calendar-shim:8080','http://localhost:8090'),
  'http://chmarine-product-service:8080','http://localhost:8091')::json
where definition::text like '%calendar-shim:8080%'
   or definition::text like '%chmarine-product-service:8080%';
```

## 2. Local environment

Copy [phone-test/phone-test.env.example](phone-test/phone-test.env.example) to
`~/dev/backups/phone-test.env`, replace the `api/.env` path, fill in the MinIO
values and `chmod 600` it.

The copy's encrypted columns (telephony credentials, org config) need the live
encryption key. Append it **without printing it**:

```bash
printf 'CREDENTIALS_ENCRYPTION_KEYS=%s\n' \
  "$(gcloud secrets versions access latest --secret dograh-credentials-encryption-keys --project dograh-eu)" \
  >> ~/dev/backups/phone-test.env
```

Do not `cat` the file or the Asterisk `ari.conf` into a shared terminal or a
chat; both hold credentials.

## 3. Tunnel to the SIP VM

```bash
gcloud compute ssh dograh-sip --project dograh-eu --zone europe-west1-b --tunnel-through-iap --quiet \
  --ssh-flag="-o ExitOnForwardFailure=yes" --ssh-flag="-o ServerAliveInterval=15" \
  --ssh-flag="-o ServerAliveCountMax=6" \
  -- -N -L 8088:127.0.0.1:8088 -R 18001:127.0.0.1:8003
```

`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8088/ari/api-docs/resources.json`
should print `401` (reachable, needs auth). The tunnel dropped once in
testing; if calls stop connecting, check it first and re-run the command.

## 4. Local API, worker and ARI config

From the branch worktree, with the main checkout's venv (the worktree has none):

```bash
set -a; . ~/dev/backups/phone-test.env; set +a
export PYTHONPATH=$PWD
python deploy/gcp/phone-test/point_local_ari.py <config_id> http://localhost:8088   # prints keys, not the password
uvicorn api.app:app --host 127.0.0.1 --port 8003 &
python -m arq api.tasks.arq.WorkerSettings --custom-log-dict api.tasks.arq.LOG_CONFIG &
curl -s http://127.0.0.1:8003/api/v1/health      # platform_models_enabled must be true
```

## 5. Take the live app off the number

Copy [phone-test/park_live_ari.py](phone-test/park_live_ari.py) onto the app VM
and run it in the api container (config id and org from
`select id, organization_id, provider from telephony_configurations`):

```bash
gcloud compute scp deploy/gcp/phone-test/park_live_ari.py dograh-app:/tmp/ --project dograh-eu --zone europe-west1-b --tunnel-through-iap
gcloud compute ssh dograh-app --project dograh-eu --zone europe-west1-b --tunnel-through-iap --command \
  'sudo docker cp /tmp/park_live_ari.py dograh-api-1:/tmp/ && sudo docker exec dograh-api-1 python /tmp/park_live_ari.py park 3 1'
```

Wait about 70 s. The live log shows the ARI connection stopping.

## 6. Redirect Asterisk's media to the laptop

The edit lives only inside the running container, so a container restart also
undoes it.

```bash
gcloud compute ssh dograh-sip --project dograh-eu --zone europe-west1-b --tunnel-through-iap --command '
  sudo docker exec asterisk-voiptel sh -c "
    cp /etc/asterisk/websocket_client.conf /etc/asterisk/websocket_client.conf.bak-phonetest &&
    sed -i \"s#^uri = .*#uri = ws://127.0.0.1:18001/api/v1/telephony/ws/ari#\" /etc/asterisk/websocket_client.conf &&
    asterisk -rx \"module reload res_websocket_client\""'
```

Then start the local ARI manager and call the number:

```bash
python -m api.services.telephony.ari_manager &     # logs "WebSocket connected to http://localhost:8088"
```

Look for `input silence filler enabled` and `Created inbound workflow run <id>`
in the logs, then place the call from extension 200.

## 7. Read the result

Per-turn latency is in the run's `logs`:

```sql
select e->>'type', e->'payload'->>'latency_seconds'
from workflow_runs, jsonb_array_elements((logs::jsonb)->'realtime_feedback_events') e
where id = <run id> and e->>'type' = 'rtf-latency-measured';
```

Compare with live runs the same way (web ≈ 1–2 s). Recordings are in local
MinIO under `recordings/<id>/`.

## 8. Revert (always, in this order)

1. Stop the local `ari_manager` first, then uvicorn and arq. Two ARI managers
   on one Stasis app answer every call twice.
2. Restore Asterisk: copy `websocket_client.conf.bak-phonetest` back over
   `websocket_client.conf` and `module reload res_websocket_client`. Check
   `grep ^uri` shows the app VM address again.
3. Reactivate the live config: `park_live_ari.py unpark 3 1`, same way as step 5.
4. Close the SSH tunnel.
5. Verify: the live log shows `WebSocket connected to http://<sip internal ip>:8088`,
   and `asterisk -rx "ari show apps"` lists `dograh`. Then place one live call.

`lm_phone_test` and the exported dump can be deleted afterwards; they hold a
copy of live data, so do not leave them around.

## What went wrong the first time, so it does not again

- **`platform_models_enabled: false` locally** → workflows using platform
  models fail. The `PLATFORM_*` variables in the env template fix it.
- **Encrypted telephony credentials** do not decrypt without the live
  `CREDENTIALS_ENCRYPTION_KEYS`.
- **Tool URLs** in the copy use Docker hostnames that do not exist on a laptop.
- **Email**: `EMAIL_PROVIDER=none`, or a test call sends real missed-call emails.
- **IAP SSH tunnels drop** when idle; keep `ServerAliveInterval` set.
