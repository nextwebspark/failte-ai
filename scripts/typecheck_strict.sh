#!/usr/bin/env bash
# Strict type check for modules held to full typing (team, roles, invitations,
# email, local auth, skills and the skills runtime). The rest of api/ is checked non-strictly by scripts/lint.sh.
set -euo pipefail

mypy --strict --follow-imports=silent \
  api/db/account_client.py \
  api/db/credential_encryption_client.py \
  api/db/encrypted_json.py \
  api/errors/account.py \
  api/routes/auth.py \
  api/schemas/auth.py \
  api/services/auth/account_dependencies.py \
  api/services/auth/accounts.py \
  api/services/auth/oauth \
  api/db/invitation_client.py \
  api/db/membership_client.py \
  api/db/skill_client.py \
  api/db/skill_models.py \
  api/errors/domain.py \
  api/errors/integrations.py \
  api/errors/invitations.py \
  api/errors/membership.py \
  api/errors/skills.py \
  api/routes/integrations.py \
  api/routes/invitations.py \
  api/routes/skills.py \
  api/routes/team.py \
  api/schemas/integrations.py \
  api/schemas/skills.py \
  api/schemas/team.py \
  api/services/auth/permissions.py \
  api/services/auth/platform_admin.py \
  api/services/credential_encryption.py \
  api/services/email \
  api/services/invitations \
  api/services/membership \
  api/services/rate_limit \
  api/services/skills \
  api/services/tool_integrations \
  api/services/workflow/pipecat_engine_skills.py \
  api/services/workflow/skill_ref_validation.py \
  api/utils/text.py \
  api/utils/trusted_origins.py \
  api/utils/clock.py \
  api/utils/credential_crypto.py \
  api/utils/secure_token.py
