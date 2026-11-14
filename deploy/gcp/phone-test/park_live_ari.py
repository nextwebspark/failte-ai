"""Park or reactivate the live ARI telephony config.

Run inside the live api container (`docker cp` it in, then
`docker exec dograh-api-1 python /tmp/park_live_ari.py park 3 1`). A parked
config makes the live ari_manager drop its connection to Asterisk within its
60 s refresh, so a local ari_manager can take over the Stasis app.

Usage: park_live_ari.py park|unpark <telephony_config_id> <organization_id>
"""

import asyncio
import sys

from api.db import db_client


async def main(action: str, config_id: int, organization_id: int) -> None:
    if action == "park":
        changed = await db_client.set_telephony_configuration_inactive(
            config_id, organization_id, "manual: local phone test"
        )
    elif action == "unpark":
        changed = await db_client.set_telephony_configuration_active(
            config_id, organization_id
        )
    else:
        raise SystemExit(__doc__)
    config = await db_client.get_telephony_configuration(config_id)
    if config is None:
        raise SystemExit(f"No telephony config with id {config_id}")
    print(f"{action}: changed={changed} inactive={config.inactive}")


if len(sys.argv) != 4:
    raise SystemExit(__doc__)
asyncio.run(main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3])))
