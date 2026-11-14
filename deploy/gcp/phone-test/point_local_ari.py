"""Point the local copy's ARI telephony config at the SSH tunnel.

Run against the local database copy (env from phone-test.env). It prints the
config's key names and current endpoint, never the password.

Usage: point_local_ari.py <telephony_config_id> [new_ari_endpoint]
"""

import asyncio
import sys

from api.db import db_client


async def main(config_id: int, endpoint: str | None) -> None:
    config = await db_client.get_telephony_configuration(config_id)
    credentials = dict(config.credentials)
    print(
        "keys:",
        sorted(credentials),
        "| endpoint:",
        credentials.get("ari_endpoint"),
        "| app:",
        credentials.get("app_name"),
        "| ws_client:",
        credentials.get("ws_client_name"),
    )
    if endpoint:
        credentials["ari_endpoint"] = endpoint
        row = await db_client.update_telephony_configuration(
            config_id, config.organization_id, credentials=credentials
        )
        print("endpoint ->", dict(row.credentials)["ari_endpoint"])


if len(sys.argv) not in (2, 3):
    raise SystemExit(__doc__)
asyncio.run(main(int(sys.argv[1]), sys.argv[2] if len(sys.argv) == 3 else None))
