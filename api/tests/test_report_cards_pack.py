"""Which pack heads Reports: one agent's, or for all agents together their
shared one, else the general (Standard) pack."""

import pytest

from api.services.report_cards import service
from api.services.report_cards.catalogue import Card, Pack


def _agents(*rows):
    return [{"id": agent_id, "status": status} for agent_id, status in rows]


@pytest.fixture
def templates(monkeypatch):
    by_agent: dict[int, str] = {}

    async def template_of(_organization_id, agent_id):
        return by_agent.get(agent_id, "general")

    monkeypatch.setattr(service, "_template_of", template_of)
    return by_agent


@pytest.mark.asyncio
async def test_one_agent_uses_its_own_pack(templates):
    templates.update({1: "restaurant", 2: "clinic"})
    template, pack, _ = await service.resolve_pack(9, 2, _agents((1, "active"), (2, "active")))
    assert template == "clinic"
    assert pack.pack == Pack.CLINIC


@pytest.mark.asyncio
async def test_all_agents_of_one_kind_share_their_pack(templates):
    templates.update({1: "restaurant", 2: "restaurant"})
    _, pack, _ = await service.resolve_pack(9, None, _agents((1, "active"), (2, "active")))
    assert pack.pack == Pack.RESTAURANT


@pytest.mark.asyncio
async def test_mixed_agents_get_the_standard_pack(templates):
    templates.update({1: "restaurant", 2: "clinic", 3: "trades"})
    template, pack, _ = await service.resolve_pack(
        9, None, _agents((1, "active"), (2, "active"), (3, "active"))
    )
    assert template == "general"
    assert pack.pack == Pack.STANDARD
    assert Card.COVERS_BOOKED not in pack.keys


@pytest.mark.asyncio
async def test_agents_switched_off_do_not_count(templates):
    templates.update({1: "restaurant", 2: "clinic"})
    _, pack, _ = await service.resolve_pack(9, None, _agents((1, "active"), (2, "inactive")))
    assert pack.pack == Pack.RESTAURANT


@pytest.mark.asyncio
async def test_no_agents_get_the_standard_pack(templates):
    _, pack, _ = await service.resolve_pack(9, None, [])
    assert pack.pack == Pack.STANDARD
