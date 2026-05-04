import pytest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.agents.personality import Personality
from pillywiggins.skills.builder import (
    DraftStatus,
    SkillDraft,
    publish_skill,
)
from pillywiggins.skills.registry import SkillRegistry


VALID_SKILL_CODE = """\
SKILL_META = {
    "name": "double",
    "description": "Double a number",
    "parameters": {"x": {"type": "number", "description": "Number to double"}},
    "returns": "dict with result",
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""


class TestPublishSkillBroadcast:
    async def test_successful_publish_broadcasts_skill_deployed(self):
        """After successful publish_skill(), broadcast 'skill_deployed' via NATS."""
        draft = SkillDraft(
            name="my_skill",
            code=VALID_SKILL_CODE,
            meta={"name": "my_skill", "description": "A test skill"},
            status=DraftStatus.TESTED,
            test_results=[
                {
                    "passed": True,
                    "args": {},
                    "actual": None,
                    "expected": None,
                    "error": None,
                    "timed_out": False,
                    "execution_time_ms": 1.0,
                },
            ],
        )
        registry = MagicMock()
        nats_bus = MagicMock()
        nats_bus.publish_broadcast = AsyncMock()

        result = await publish_skill(
            draft,
            approved=True,
            skills_dir="/tmp",
            registry=registry,
            nats_bus=nats_bus,
        )

        assert "published successfully" in result
        registry.register_skill.assert_called_once_with(
            "my_skill", VALID_SKILL_CODE, {"name": "my_skill", "description": "A test skill"}
        )
        nats_bus.publish_broadcast.assert_awaited_once_with(
            "skill_deployed",
            {"skill_name": "my_skill", "agent_id": ANY, "deployed_at": ANY},
        )

    async def test_failed_publish_does_not_broadcast(self):
        """If publish is rejected or fails, no broadcast should be sent."""
        draft = SkillDraft(name="test", code="pass", status=DraftStatus.DRAFT)
        registry = MagicMock()
        nats_bus = MagicMock()
        nats_bus.publish_broadcast = AsyncMock()

        result = await publish_skill(
            draft,
            approved=True,
            skills_dir="/tmp",
            registry=registry,
            nats_bus=nats_bus,
        )

        assert "cannot be published" in result
        registry.register_skill.assert_not_called()
        nats_bus.publish_broadcast.assert_not_called()

    async def test_publish_without_nats_bus_still_works(self):
        """publish_skill() must work when nats_bus is not provided (backward compat)."""
        draft = SkillDraft(
            name="my_skill",
            code=VALID_SKILL_CODE,
            meta={"name": "my_skill"},
            status=DraftStatus.TESTED,
            test_results=[
                {
                    "passed": True,
                    "args": {},
                    "actual": None,
                    "expected": None,
                    "error": None,
                    "timed_out": False,
                    "execution_time_ms": 1.0,
                },
            ],
        )
        registry = MagicMock()

        result = await publish_skill(
            draft,
            approved=True,
            skills_dir="/tmp",
            registry=registry,
        )

        assert "published successfully" in result
        registry.register_skill.assert_called_once()

    async def test_publish_with_failing_tests_does_not_broadcast(self):
        """If tests fail, publish is blocked and no broadcast is sent."""
        draft = SkillDraft(
            name="test",
            code="pass",
            status=DraftStatus.TESTED,
            test_results=[
                {
                    "passed": False,
                    "args": {},
                    "actual": None,
                    "expected": None,
                    "error": "fail",
                    "timed_out": False,
                    "execution_time_ms": 1.0,
                },
            ],
        )
        registry = MagicMock()
        nats_bus = MagicMock()
        nats_bus.publish_broadcast = AsyncMock()

        result = await publish_skill(
            draft,
            approved=True,
            skills_dir="/tmp",
            registry=registry,
            nats_bus=nats_bus,
        )

        assert "failing test" in result
        registry.register_skill.assert_not_called()
        nats_bus.publish_broadcast.assert_not_called()

    async def test_publish_without_approval_does_not_broadcast(self):
        """If not approved, no broadcast is sent."""
        draft = SkillDraft(name="test", code="pass", status=DraftStatus.TESTED)
        registry = MagicMock()
        nats_bus = MagicMock()
        nats_bus.publish_broadcast = AsyncMock()

        result = await publish_skill(
            draft,
            approved=False,
            skills_dir="/tmp",
            registry=registry,
            nats_bus=nats_bus,
        )

        assert "not approved" in result
        registry.register_skill.assert_not_called()
        nats_bus.publish_broadcast.assert_not_called()


VALID_SKILL_CODE_ASYNC = '''\
SKILL_META = {
    "name": "double",
    "description": "Double a number",
    "parameters": {"x": {"type": "number", "description": "Number to double"}},
    "returns": "dict with result",
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

async def run(x: int = 0) -> dict:
    return {"result": x * 2}
'''


class TestSkillBroadcastCrossAgent:
    """Simulate Agent A deploying a skill and Agent B picking it up via broadcast."""

    @pytest.fixture
    def personality(self):
        return Personality(
            name="puck",
            channel="telegram",
            description="A mischievous test fairy",
            system_prompt="You are Puck.",
            traits=["playful"],
            scheduling={"interval": 60},
        )

    @pytest.fixture
    def skills_dir(self, tmp_path):
        return tmp_path / "skills"

    @pytest.fixture
    def agent_a(self, skills_dir, personality):
        """Agent A has its own SkillRegistry and can broadcast."""
        bus = MagicMock()
        bus.publish_broadcast = AsyncMock()
        reg = SkillRegistry(skills_dir=skills_dir, agent_id="agent_a", nats_bus=bus)
        with patch("pillywiggins.agents.base.create_brain") as mock_brain:
            mock_brain.return_value = MagicMock()
            agent = PillywigginAgent(
                agent_id="agent_a",
                personality=personality,
                model_name="qwen3.5:8b",
                provider="ollama",
                base_url="http://localhost:11434",
                api_key="",
                skill_registry=reg,
            )
            agent._nats_bus = bus
        return agent

    @pytest.fixture
    def agent_b(self, skills_dir, personality):
        """Agent B shares the skills_dir and receives the broadcast."""
        bus = MagicMock()
        bus.publish_broadcast = AsyncMock()
        reg = SkillRegistry(skills_dir=skills_dir, agent_id="agent_b", nats_bus=bus)
        with patch("pillywiggins.agents.base.create_brain") as mock_brain:
            mock_brain.return_value = MagicMock()
            agent = PillywigginAgent(
                agent_id="agent_b",
                personality=personality,
                model_name="qwen3.5:8b",
                provider="ollama",
                base_url="http://localhost:11434",
                api_key="",
                skill_registry=reg,
            )
            agent._nats_bus = bus
        return agent

    @pytest.mark.asyncio
    async def test_agent_b_picks_up_skill_after_broadcast(self, agent_a, agent_b, skills_dir):
        """
        a. Agent A deploys a new skill (writes .py + updates registry.json)
        b. Agent A broadcasts `skill_deployed` via mock NatsBus
        c. Agent B receives the broadcast
        d. Agent B's registry reload picks up the new skill
        e. Verify skill is in Agent B's registry
        """
        # --- a. Agent A deploys the skill ---
        draft = SkillDraft(
            name="double",
            code=VALID_SKILL_CODE_ASYNC,
            meta={
                "name": "double",
                "description": "Double a number",
                "parameters": {"x": {"type": "number", "description": "Number to double"}},
                "permissions": {"network": False, "subprocess": False, "file_write": False},
            },
            status=DraftStatus.TESTED,
            test_results=[{"passed": True, "args": {"x": 3}, "expected": {"result": 6}, "actual": {"result": 6}, "error": None, "timed_out": False, "execution_time_ms": 1.0}],
        )

        result = await publish_skill(
            draft,
            approved=True,
            skills_dir=str(skills_dir),
            registry=agent_a._skill_registry,
            nats_bus=agent_a._nats_bus,
        )
        assert "published successfully" in result
        assert (skills_dir / "double.py").exists()

        # --- b. Verify Agent A broadcast skill_deployed ---
        bus_a = agent_a._nats_bus
        bus_a.publish_broadcast.assert_awaited_once()
        call_args = bus_a.publish_broadcast.await_args_list[0]
        assert call_args[0][0] == "skill_deployed"
        assert call_args[0][1]["skill_name"] == "double"

        # --- c. Agent B receives the broadcast ---
        broadcast_data = call_args[0][1]
        await agent_b._on_nats_message("skill_deployed", broadcast_data, from_agent="agent_a", timestamp="2026-01-01T00:00:00Z")

        # --- d. Agent B's SkillRegistry picked up the new skill ---
        # e. Verify skill is in Agent B's registry
        skill = agent_b._skill_registry.get_skill("double")
        assert skill is not None, "Agent B should have 'double' skill loaded after broadcast"
        assert skill.name == "double"
        assert skill.description == "Double a number"
