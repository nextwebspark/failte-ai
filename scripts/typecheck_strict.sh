#!/usr/bin/env bash
# Strict type check for modules held to full typing (team, roles, invitations,
# email, local auth). The rest of api/ is checked non-strictly by scripts/lint.sh.
set -euo pipefail

mypy --strict --follow-imports=silent \
  api/db/account_client.py \
  api/errors/account.py \
  api/routes/auth.py \
  api/schemas/auth.py \
  api/services/auth/account_dependencies.py \
  api/services/auth/accounts.py \
  api/services/auth/oauth \
  api/db/invitation_client.py \
  api/db/membership_client.py \
  api/errors/domain.py \
  api/errors/integrations.py \
  api/errors/invitations.py \
  api/errors/membership.py \
  api/routes/integrations.py \
  api/routes/invitations.py \
  api/routes/team.py \
  api/schemas/integrations.py \
  api/schemas/team.py \
  api/services/auth/permissions.py \
  api/services/email \
  api/services/invitations \
  api/services/membership \
  api/services/rate_limit \
  api/services/tool_integrations \
  api/utils/text.py \
  api/utils/clock.py \
  api/utils/secure_token.py
