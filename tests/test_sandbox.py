import pytest


@pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
class TestSandboxExecution:
    @pytest.mark.asyncio
    async def test_run_skill_sandboxed_executes_skill(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
    @pytest.mark.asyncio
    async def test_run_skill_sandboxed_returns_result(self):
        ...


@pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
class TestSandboxTimeout:
    @pytest.mark.asyncio
    async def test_timeout_kills_runaway_skill_after_30_seconds(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
    @pytest.mark.asyncio
    async def test_timeout_returns_error_result(self):
        ...


@pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
class TestSandboxRestrictedEnv:
    def test_restricted_env_removes_database_url(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
    def test_restricted_env_removes_channel_tokens(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
    def test_restricted_env_sets_working_dir_to_tmp(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
    def test_restricted_env_allows_network_when_permitted(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
    def test_restricted_env_blocks_network_by_default(self):
        ...


@pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
class TestSandboxPermissions:
    @pytest.mark.asyncio
    async def test_network_false_prevents_outbound_requests(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
    @pytest.mark.asyncio
    async def test_subprocess_false_prevents_subprocess_calls(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.skills.sandbox not yet implemented")
    @pytest.mark.asyncio
    async def test_file_write_false_prevents_file_modification(self):
        ...