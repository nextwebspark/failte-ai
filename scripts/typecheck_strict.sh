#!/usr/bin/env bash
# Strict type check for modules held to full typing (team, roles, invitations,
# email). The rest of api/ is checked non-strictly by scripts/lint.sh.
set -euo pipefail

mypy --strict --follow-imports=silent \
  api/db/invitation_client.py \
  api/db/membership_client.py \
  api/errors/domain.py \
  api/errors/invitations.py \
  api/errors/membership.py \
  api/routes/invitations.py \
  api/routes/team.py \
  api/schemas/team.py \
  api/services/auth/permissions.py \
  api/services/email \
  api/services/invitations \
  api/services/membership \
  api/utils/clock.py \
  api/utils/secure_token.py
