import pytest
from unittest.mock import AsyncMock, MagicMock

from pillywiggins.skills.builder import (
    DraftStatus,
    SkillDraft,
    deploy_skill,
)


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


class TestDeploySkillBroadcast:
    async def test_successful_deploy_broadcasts_skill_deployed(self):
        """After successful deploy_skill(), broadcast 'skill_deployed' via NATS."""
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

        result = await deploy_skill(
            draft,
            approved=True,
            skills_dir="/tmp",
            registry=registry,
            nats_bus=nats_bus,
        )

        assert "deployed successfully" in result
        registry.register_skill.assert_called_once_with(
            "my_skill", VALID_SKILL_CODE, {"name": "my_skill", "description": "A test skill"}
        )
        nats_bus.publish_broadcast.assert_awaited_once_with(
            "skill_deployed",
            {"skill_name": "my_skill", "meta": {"name": "my_skill", "description": "A test skill"}},
        )

    async def test_failed_deploy_does_not_broadcast(self):
        """If deploy is rejected or fails, no broadcast should be sent."""
        draft = SkillDraft(name="test", code="pass", status=DraftStatus.DRAFT)
        registry = MagicMock()
        nats_bus = MagicMock()
        nats_bus.publish_broadcast = AsyncMock()

        result = await deploy_skill(
            draft,
            approved=True,
            skills_dir="/tmp",
            registry=registry,
            nats_bus=nats_bus,
        )

        assert "cannot be deployed" in result
        registry.register_skill.assert_not_called()
        nats_bus.publish_broadcast.assert_not_called()

    async def test_deploy_without_nats_bus_still_works(self):
        """deploy_skill() must work when nats_bus is not provided (backward compat)."""
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

        result = await deploy_skill(
            draft,
            approved=True,
            skills_dir="/tmp",
            registry=registry,
        )

        assert "deployed successfully" in result
        registry.register_skill.assert_called_once()

    async def test_deploy_with_failing_tests_does_not_broadcast(self):
        """If tests fail, deploy is blocked and no broadcast is sent."""
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

        result = await deploy_skill(
            draft,
            approved=True,
            skills_dir="/tmp",
            registry=registry,
            nats_bus=nats_bus,
        )

        assert "failing test" in result
        registry.register_skill.assert_not_called()
        nats_bus.publish_broadcast.assert_not_called()

    async def test_deploy_without_approval_does_not_broadcast(self):
        """If not approved, no broadcast is sent."""
        draft = SkillDraft(name="test", code="pass", status=DraftStatus.TESTED)
        registry = MagicMock()
        nats_bus = MagicMock()
        nats_bus.publish_broadcast = AsyncMock()

        result = await deploy_skill(
            draft,
            approved=False,
            skills_dir="/tmp",
            registry=registry,
            nats_bus=nats_bus,
        )

        assert "not approved" in result
        registry.register_skill.assert_not_called()
        nats_bus.publish_broadcast.assert_not_called()
