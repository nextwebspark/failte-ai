#!/usr/bin/env bash
# Runs on the app VM as the SSH user; deploy.yml pipes it in:
#
#   gcloud compute ssh dograh-app ... --command "bash -s -- 0.2.0 /opt/lightmove/dograh <unit>" \
#     < deploy/gcp/remote-deploy.sh
#
# Starts the *target* release's deploy/gcp/deploy.sh as a transient systemd
# unit and streams its log. The unit is independent of this SSH session, so a
# dropped tunnel or a cancelled job cannot stop a deploy halfway: it still
# finishes or rolls back. Read it afterwards with `journalctl -u <unit>`.
set -euo pipefail

VERSION="$1"
APP_DIR="$2"
UNIT="$3"
SCRIPT="/run/${UNIT}.sh"

sudo git -C "$APP_DIR" fetch --quiet --tags --force origin
sudo git -C "$APP_DIR" show "v${VERSION}:deploy/gcp/deploy.sh" | sudo tee "$SCRIPT" >/dev/null
sudo chmod 700 "$SCRIPT"

# HOME=/root so docker finds root's Artifact Registry credential helper
# (gcloud auth configure-docker); /snap/bin for gcloud on Ubuntu images.
sudo systemd-run --unit="$UNIT" --quiet --property=RemainAfterExit=yes \
  --setenv=HOME=/root \
  --setenv=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin \
  --setenv=LIGHTMOVE_APP_DIR="$APP_DIR" \
  /bin/bash "$SCRIPT" "$VERSION"

# Stream the unit's log by polling with a journal cursor. A background
# `journalctl -f` can outlive this script (sudo does not reliably pass the
# kill on) and then holds the SSH session open, so the job never finishes.
cursor=""
print_new_lines() {
  local out last
  local -a args=(-u "$UNIT" -o cat --no-pager --show-cursor)
  if [[ -n "$cursor" ]]; then args+=(--after-cursor "$cursor"); fi
  out="$(sudo journalctl "${args[@]}" 2>/dev/null | grep -v '^-- No entries --$' || true)"
  if [[ -z "$out" ]]; then return 0; fi
  last="${out##*$'\n'}"
  if [[ "$last" == "-- cursor: "* ]]; then
    cursor="${last#-- cursor: }"
    if [[ "$out" == *$'\n'* ]]; then out="${out%$'\n'*}"; else out=""; fi
  fi
  if [[ -n "$out" ]]; then printf '%s\n' "$out"; fi
}

# Type=simple + RemainAfterExit: "running" until the script exits, then
# "exited" (success) or "failed".
while [[ "$(sudo systemctl show -p SubState --value "$UNIT")" == "running" ]]; do
  print_new_lines
  sleep 5
done
print_new_lines

status="$(sudo systemctl show -p ExecMainStatus --value "$UNIT")"
sudo systemctl stop "$UNIT" 2>/dev/null || true
sudo systemctl reset-failed "$UNIT" 2>/dev/null || true
sudo rm -f "$SCRIPT"
exit "${status:-1}"
