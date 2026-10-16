#!/bin/bash
# certbot deploy hook for the release-deploy install. Install once on the app
# VM (it replaces the hook setup_remote.sh / setup_custom_domain.sh wrote,
# which is pinned to the old install path):
#
#   sudo install -m 755 /opt/lightmove/dograh/deploy/gcp/certbot-deploy-hook.sh \
#     /etc/letsencrypt/renewal-hooks/deploy/dograh-reload.sh
#
# On renewal of the certificate for PUBLIC_HOST (from .env), copies it into
# certs/ (what nginx mounts) and restarts nginx. Other certificates are ignored.
set -euo pipefail

APP_DIR="${LIGHTMOVE_APP_DIR:-/opt/lightmove/dograh}"
host="$(grep -E '^PUBLIC_HOST=' "$APP_DIR/.env" | tail -1 | cut -d= -f2- | tr -d '"')"
[[ -n "$host" && "${RENEWED_LINEAGE:-}" == "/etc/letsencrypt/live/$host" ]] || exit 0

cp "$RENEWED_LINEAGE/fullchain.pem" "$APP_DIR/certs/local.crt"
cp "$RENEWED_LINEAGE/privkey.pem" "$APP_DIR/certs/local.key"
chmod 644 "$APP_DIR/certs/local.crt"
chmod 600 "$APP_DIR/certs/local.key"
cd "$APP_DIR" && docker compose restart nginx >/dev/null 2>&1 || true
