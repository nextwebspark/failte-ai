"""Write the starter agents to the workflow_templates table.

The api container runs this on every start, after the migrations
(scripts/start_services_docker.sh; scripts/run_migrate.sh for Helm). By hand,
from the repo root with the api environment available:

    python -m scripts.sync_agent_templates

A template whose name already exists is updated in place, so re-running after
editing api/services/workflow/starter_templates.py is safe. Templates that are
not in the catalogue are left alone.
"""

import asyncio

from loguru import logger

from api.db.workflow_template_client import WorkflowTemplateClient
from api.services.workflow.starter_templates import STARTER_TEMPLATES


async def main() -> None:
    client = WorkflowTemplateClient()
    for starter in STARTER_TEMPLATES:
        template, created = await client.upsert_workflow_template(
            starter.name, starter.row()
        )
        action = "Created" if created else "Updated"
        logger.info(f"{action} template {starter.name!r} (id {template.id})")


if __name__ == "__main__":
    asyncio.run(main())
