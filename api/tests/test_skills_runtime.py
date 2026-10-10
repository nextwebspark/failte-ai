"""Agent skills runtime: skill selection, prompt index, built-ins, the tool
restriction and save-time validation (pure, no database)."""

from collections.abc import Collection

import pytest

from api.db.skill_client import SkillFile
from api.db.skill_models import SkillStatus
from api.services.skills.runtime import (
    INDEX_HEADER,
    LOAD_SKILL,
    READ_SKILL_FILE,
    NodeSkills,
    NodeSkillSession,
    RuntimeSkill,
    SkillSet,
    builtin_function_definitions,
    load_call_skill_set,
    load_skill_result,
    load_skill_set,
    read_skill_file_result,
)
from api.services.workflow.skill_ref_validation import (
    reserved_custom_tool_name_error,
    reserved_transition_name_errors,
    validate_workflow_skill_refs,
)

RETURNS = RuntimeSkill(
    skill_uuid="11111111-1111-1111-1111-111111111111",
    name="returns-policy",
    description="Handle return and refund requests.",
    body_md="# Returns\nAsk for the order number first.",
    files=(SkillFile(path="references/policy.md", content="30 days."),),
    allowed_tool_uuids=frozenset({"tool-lookup"}),
)
BOOKING = RuntimeSkill(
    skill_uuid="22222222-2222-2222-2222-222222222222",
    name="appointment-booking",
    description="Book an appointment.",
    body_md="Offer two slots.",
)
WARRANTY = RuntimeSkill(
    skill_uuid="33333333-3333-3333-3333-333333333333",
    name="warranty",
    description="Warranty questions.",
    body_md="Check the purchase date.",
    allowed_tool_uuids=frozenset({"tool-warranty"}),
)
SKILLS = SkillSet.of([RETURNS, BOOKING, WARRANTY])


class TestSelection:
    def test_unset_narrowing_lists_all_skills(self) -> None:
        node = SKILLS.for_node(None)
        assert [s.name for s in node.listed] == [
            "appointment-booking",
            "returns-policy",
            "warranty",
        ]
        assert node.preloaded == ()

    def test_explicit_empty_narrowing_opts_the_node_out(self) -> None:
        assert SKILLS.for_node([]).is_empty
        # Preloads are explicit and still apply.
        node = SKILLS.for_node([], [BOOKING.skill_uuid])
        assert node.listed == ()
        assert node.preloaded == (BOOKING,)

    def test_narrowing_lists_only_named_skills_and_ignores_unknown(self) -> None:
        node = SKILLS.for_node([RETURNS.skill_uuid, "not-a-skill", RETURNS.skill_uuid])
        assert node.listed == (RETURNS,)
        assert node.get("appointment-booking") is None

    def test_preloaded_skills_leave_the_index(self) -> None:
        node = SKILLS.for_node(None, [BOOKING.skill_uuid])
        assert node.preloaded == (BOOKING,)
        assert BOOKING not in node.listed
        assert node.get("appointment-booking") is BOOKING

    def test_empty_skill_set_gives_empty_node(self) -> None:
        assert SkillSet.empty().for_node(None).is_empty


class TestPromptBlock:
    def test_index_only_names_and_descriptions(self) -> None:
        block = SKILLS.for_node([RETURNS.skill_uuid]).prompt_block()
        assert block.startswith(INDEX_HEADER)
        assert "- returns-policy: Handle return and refund requests." in block
        assert LOAD_SKILL in block
        assert RETURNS.body_md not in block
        assert "references/policy.md" not in block

    def test_preload_inlines_body_and_files(self) -> None:
        block = SKILLS.for_node(
            [BOOKING.skill_uuid], [RETURNS.skill_uuid]
        ).prompt_block()
        assert RETURNS.body_md in block
        assert "references/policy.md" in block
        assert "- appointment-booking: Book an appointment." in block

    def test_no_skills_no_block(self) -> None:
        assert NodeSkills().prompt_block() == ""


class TestBuiltins:
    def test_definitions_only_when_node_has_skills(self) -> None:
        assert builtin_function_definitions(NodeSkills()) == []
        defs = builtin_function_definitions(SKILLS.for_node([RETURNS.skill_uuid]))
        assert [d.name for d in defs] == [LOAD_SKILL, READ_SKILL_FILE]
        assert defs[0].properties["name"]["enum"] == ["returns-policy"]

    def test_load_skill_returns_body_and_file_paths(self) -> None:
        node = SKILLS.for_node(None)
        result, loaded = load_skill_result(
            node, "returns-policy", allowed_function_names=None
        )
        assert loaded is RETURNS
        assert result == {
            "name": "returns-policy",
            "instructions": RETURNS.body_md,
            "files": ["references/policy.md"],
        }

    def test_load_skill_reports_allowed_tools(self) -> None:
        result, _ = load_skill_result(
            SKILLS.for_node(None),
            "returns-policy",
            allowed_function_names=["lookup_order"],
        )
        assert result["allowed_tools"] == ["lookup_order"]

    @pytest.mark.parametrize("name", ["unknown", "", None, 3])
    def test_load_skill_rejects_unknown_names(self, name: object) -> None:
        result, loaded = load_skill_result(
            SKILLS.for_node(None), name, allowed_function_names=None
        )
        assert loaded is None
        assert "error" in result

    def test_load_skill_rejects_skill_outside_the_node(self) -> None:
        node = SKILLS.for_node([BOOKING.skill_uuid])
        result, loaded = load_skill_result(
            node, "returns-policy", allowed_function_names=None
        )
        assert loaded is None
        assert "appointment-booking" in result["error"]

    def test_read_skill_file_exact_match(self) -> None:
        result = read_skill_file_result(
            SKILLS.for_node(None), "returns-policy", "references/policy.md"
        )
        assert result == {
            "name": "returns-policy",
            "path": "references/policy.md",
            "content": "30 days.",
        }

    @pytest.mark.parametrize(
        "path",
        [
            "../references/policy.md",
            "references/../references/policy.md",
            "/references/policy.md",
            "./references/policy.md",
            "references/Policy.md",
            "references/policy.md ",
            "SKILL.md",
            "",
            None,
        ],
    )
    def test_read_skill_file_rejects_anything_else(self, path: object) -> None:
        result = read_skill_file_result(SKILLS.for_node(None), "returns-policy", path)
        assert "error" in result
        assert "content" not in result


class TestSession:
    def test_restriction_is_union_of_loaded_restricted_skills(self) -> None:
        session = NodeSkillSession("n", "Node", SKILLS.for_node(None))
        session.tool_functions.update(
            {"lookup_order": "tool-lookup", "check_warranty": "tool-warranty"}
        )
        assert session.is_tool_allowed("tool-anything")
        session.record_load(BOOKING)  # unrestricted: no effect
        assert session.allowed_tool_uuids is None
        session.record_load(RETURNS)
        assert not session.is_tool_allowed("tool-warranty")
        assert session.allowed_function_names(session.allowed_tool_uuids) == [
            "lookup_order"
        ]
        session.record_load(WARRANTY)
        assert session.is_tool_allowed("tool-warranty")
        session.record_load(BOOKING)  # does not lift the restriction
        assert not session.is_tool_allowed("tool-anything")
        assert session.loaded_skill_names == (
            "appointment-booking",
            "returns-policy",
            "warranty",
        )


class _Store:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[int] = []
        self._error = error

    async def list_runtime_skills(self, organization_id: int) -> list:
        self.calls.append(organization_id)
        if self._error:
            raise self._error
        return []


@pytest.mark.asyncio
async def test_load_skill_set_degrades_to_empty_on_error() -> None:
    store = _Store(RuntimeError("db down"))
    skill_set = await load_skill_set(store, 7)
    assert len(skill_set) == 0
    assert store.calls == [7]


class _Directory:
    def __init__(self, states: dict[str, SkillStatus]) -> None:
        self.states = states
        self.calls: list[tuple[int, set[str]]] = []

    async def skill_uuid_states(
        self, organization_id: int, skill_uuids: Collection[str]
    ) -> dict[str, SkillStatus]:
        self.calls.append((organization_id, set(skill_uuids)))
        return {u: st for u, st in self.states.items() if u in skill_uuids}


def _definition(**data: object) -> dict:
    return {
        "nodes": [{"id": "n1", "type": "agentNode", "data": {"name": "A", **data}}],
        "edges": [],
    }


class TestSaveValidation:
    @pytest.mark.asyncio
    async def test_unknown_or_foreign_skill_uuids_rejected(self) -> None:
        directory = _Directory({"mine": SkillStatus.ACTIVE})
        errors = await validate_workflow_skill_refs(
            _definition(skill_uuids=["mine", "theirs"], preload_skill_uuids=["x"]),
            5,
            directory,
        )
        assert directory.calls == [(5, {"mine", "theirs", "x"})]
        assert {(e["field"], e["message"].rsplit(": ", 1)[1]) for e in errors} == {
            ("data.skill_uuids", "theirs"),
            ("data.preload_skill_uuids", "x"),
        }

    @pytest.mark.asyncio
    async def test_owned_or_absent_refs_pass_without_query(self) -> None:
        directory = _Directory(
            {"mine": SkillStatus.ACTIVE, "old": SkillStatus.ARCHIVED}
        )
        # An archived skill of the same workspace is accepted.
        assert (
            await validate_workflow_skill_refs(
                _definition(skill_uuids=["mine"], preload_skill_uuids=["old"]),
                5,
                directory,
            )
            == []
        )
        assert await validate_workflow_skill_refs(_definition(), 5, directory) == []
        assert len(directory.calls) == 1

    def test_transition_label_cannot_shadow_builtins(self) -> None:
        definition = {
            "nodes": [],
            "edges": [
                {"id": "e1", "data": {"label": "Load Skill"}},
                {"id": "e2", "data": {"label": "read skill file"}},
                {"id": "e3", "data": {"label": "Done"}},
            ],
        }
        assert [e["id"] for e in reserved_transition_name_errors(definition)] == [
            "e1",
            "e2",
        ]

    def test_custom_tool_cannot_shadow_builtins(self) -> None:
        assert reserved_custom_tool_name_error("n", "load_skill", "Load Skill")
        assert reserved_custom_tool_name_error("n", "lookup", "Lookup") is None


class TestPreloadPrompt:
    def test_preload_restriction_line(self) -> None:
        node = SKILLS.for_node([], [RETURNS.skill_uuid])
        block = node.prompt_block(preload_allowed_tools=["lookup_order"])
        assert block.endswith(
            "Only these tools are available: lookup_order (plus step "
            "transitions and call controls)."
        )
        assert "Only these tools" not in node.prompt_block()

    def test_without_builtins_no_index_and_no_file_list(self) -> None:
        node = SKILLS.for_node(None, [RETURNS.skill_uuid])
        block = node.prompt_block(with_builtins=False)
        assert INDEX_HEADER not in block
        assert RETURNS.body_md in block
        assert "references/policy.md" not in block


@pytest.mark.asyncio
async def test_disabled_workflow_loads_nothing() -> None:
    store = _Store()
    assert await load_call_skill_set(store, 3, {"skills_enabled": False}) is None
    assert store.calls == []
    assert await load_call_skill_set(store, 3, {}) is not None
    assert await load_call_skill_set(store, 3, None) is not None
    assert store.calls == [3, 3]


def test_python_sdk_keeps_explicit_empty_skill_uuids() -> None:
    import sys
    from pathlib import Path

    sdk_src = Path(__file__).resolve().parents[2] / "sdk" / "python" / "src"
    if str(sdk_src) not in sys.path:
        sys.path.insert(0, str(sdk_src))
    from dograh_sdk.typed.agent_node import AgentNode

    opted_out = AgentNode(name="A", prompt="p", skill_uuids=[]).to_dict()
    assert opted_out["skill_uuids"] == []
    default = AgentNode(name="A", prompt="p").to_dict()
    assert "skill_uuids" not in default
    assert "tool_uuids" not in AgentNode(name="A", prompt="p", tool_uuids=[]).to_dict()
