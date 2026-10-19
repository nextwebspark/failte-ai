"""Write the starter agents to the workflow_templates table.

Run from the repo root with the api environment available:

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
        fields = [field.model_dump(exclude_none=True) for field in starter.setup_fields]
        existing = await client.get_workflow_template_by_name(starter.name)
        if existing:
            await client.update_workflow_template(
                existing.id,
                template_json=starter.definition,
                template_description=starter.description,
                setup_fields=fields,
            )
            logger.info(f"Updated template {starter.name!r} (id {existing.id})")
        else:
            created = await client.create_workflow_template(
                starter.name, starter.description, starter.definition, fields
            )
            logger.info(f"Created template {starter.name!r} (id {created.id})")


if __name__ == "__main__":
    asyncio.run(main())
