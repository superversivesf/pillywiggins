"""Tests for brain memory tools: recall_private_memory, save_to_private_memory,
query_council_memory, share_to_council."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext

from pillywiggins.agents.brain import (
    recall_private_memory,
    save_to_private_memory,
    query_council_memory,
    share_to_council,
)
from tests.helpers import make_ctx

_make_ctx = make_ctx


class TestRecallPrivateMemoryEdgeCases:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_private_memory_none(self):
        ctx = _make_ctx(private_memory=None)
        result = await recall_private_memory(ctx, "test query")
        assert result == "Private memory is not available."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_message_when_embedding_is_none(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = None
        memory = MagicMock()
        ctx = _make_ctx(private_memory=memory)
        result = await recall_private_memory(ctx, "test")
        assert result == "Private memory could not generate embedding for search."
        memory.search.assert_not_called()

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_not_found_when_search_empty(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        memory = MagicMock()
        memory.search = AsyncMock(return_value=[])
        ctx = _make_ctx(private_memory=memory)
        result = await recall_private_memory(ctx, "nothing here")
        assert result == "No memories found matching that query."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_formatted_results_when_found(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        memory = MagicMock()
        memory.search = AsyncMock(
            return_value=[
                {"content": "I like tea", "similarity": 0.95},
                {"content": "I live in London", "similarity": 0.80},
            ]
        )
        ctx = _make_ctx(private_memory=memory)
        result = await recall_private_memory(ctx, "preferences")
        assert "I like tea" in result
        assert "0.95" in result
        assert "I live in London" in result
        assert "0.80" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_search_uses_embedding_from_settings(self, mock_settings_cls, mock_embed):
        mock_settings = MagicMock()
        mock_settings.llm_base_url = "http://custom:11434"
        mock_settings.llm_api_key = "key"
        mock_settings.llm_provider = "ollama"
        mock_settings.embedding_model = "nomic-embed-text"
        mock_settings_cls.return_value = mock_settings
        mock_embed.return_value = [0.5]
        memory = MagicMock()
        memory.search = AsyncMock(return_value=[])
        ctx = _make_ctx(private_memory=memory)
        await recall_private_memory(ctx, "test")
        mock_embed.assert_awaited_once_with(
            "test",
            base_url="http://custom:11434",
            api_key="key",
            provider="ollama",
            model="nomic-embed-text",
            expected_dimension=mock_settings.embedding_dimension,
        )


class TestSaveToPrivateMemoryEdgeCases:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_private_memory_none(self):
        ctx = _make_ctx(private_memory=None)
        result = await save_to_private_memory(ctx, "something")
        assert result == "Private memory is not available."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_error_when_embedding_is_none(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = None
        memory = MagicMock()
        ctx = _make_ctx(private_memory=memory)
        result = await save_to_private_memory(ctx, "something")
        assert result == "Private memory could not generate embedding."
        memory.save.assert_not_called()

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_saves_content_with_embedding(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        memory = MagicMock()
        memory.save = AsyncMock()
        ctx = _make_ctx(private_memory=memory)
        result = await save_to_private_memory(ctx, "I prefer tea over coffee")
        memory.save.assert_awaited_once_with("I prefer tea over coffee", [0.1, 0.2, 0.3])
        assert result == "Remembered: I prefer tea over coffee"

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_confirmation_includes_content(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.5]
        memory = MagicMock()
        memory.save = AsyncMock()
        ctx = _make_ctx(private_memory=memory)
        result = await save_to_private_memory(ctx, "user likes cats")
        assert "Remembered:" in result
        assert "user likes cats" in result


class TestQueryCouncilMemory:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_council_memory_none(self):
        ctx = _make_ctx(council_memory=None)
        result = await query_council_memory(ctx, "test query")
        assert result == "Council memory is not available."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_not_found_when_search_empty(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.search = AsyncMock(return_value=[])
        ctx = _make_ctx(council_memory=council)
        result = await query_council_memory(ctx, "nothing here")
        assert result == "No council insights found matching that query."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_formatted_results_when_found(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.search = AsyncMock(
            return_value=[
                {"content": "sky is blue", "contributing_agent": "puck", "message_type": "insight"},
                {
                    "content": "water is wet",
                    "contributing_agent": "oberon",
                    "message_type": "observation",
                },
            ]
        )
        ctx = _make_ctx(council_memory=council)
        result = await query_council_memory(ctx, "nature facts")
        assert "[insight]" in result
        assert "sky is blue" in result
        assert "puck" in result
        assert "[observation]" in result
        assert "water is wet" in result
        assert "oberon" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_message_when_embedding_is_none(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = None
        council = MagicMock()
        ctx = _make_ctx(council_memory=council)
        result = await query_council_memory(ctx, "test")
        assert result == "Council memory could not generate embedding for search."
        council.search.assert_not_called()


class TestShareToCouncil:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_council_memory_none(self):
        ctx = _make_ctx(council_memory=None)
        result = await share_to_council(ctx, "insight content")
        assert result == "Council memory is not available."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_error_when_embedding_is_none(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = None
        council = MagicMock()
        ctx = _make_ctx(council_memory=council)
        result = await share_to_council(ctx, "something")
        assert result == "Council memory could not generate embedding."
        council.write_entry.assert_not_called()

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_writes_entry_with_parsed_tags(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.write_entry = AsyncMock(
            return_value={"success": True, "error": None, "id": "abc-123"}
        )
        ctx = _make_ctx(council_memory=council, nats_bus=None)
        result = await share_to_council(
            ctx, "important finding", tags="idea, learning", message_type="insight"
        )
        council.write_entry.assert_awaited_once_with(
            content="important finding",
            tags=["idea", "learning"],
            embedding=[0.1, 0.2, 0.3],
            message_type="insight",
        )
        assert result == "Shared to council: important finding"

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_writes_entry_with_empty_tags(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.write_entry = AsyncMock(
            return_value={"success": True, "error": None, "id": "abc-123"}
        )
        ctx = _make_ctx(council_memory=council, nats_bus=None)
        result = await share_to_council(ctx, "tagless insight")
        council.write_entry.assert_awaited_once_with(
            content="tagless insight",
            tags=[],
            embedding=[0.1, 0.2, 0.3],
            message_type="insight",
        )
        assert result == "Shared to council: tagless insight"

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_publishes_via_nats_bus(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.write_entry = AsyncMock(
            return_value={"success": True, "error": None, "id": "abc-123"}
        )
        nats = MagicMock()
        nats.publish_broadcast = AsyncMock()
        ctx = _make_ctx(council_memory=council, nats_bus=nats)
        result = await share_to_council(ctx, "shared finding", tags="idea", message_type="insight")
        nats.publish_broadcast.assert_awaited_once_with(
            "insight", {"content": "shared finding", "tags": ["idea"], "embedding": [0.1, 0.2, 0.3]}
        )
        assert result == "Shared to council: shared finding"

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_error_on_write_failure(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.write_entry = AsyncMock(
            return_value={"success": False, "error": "Rate limit exceeded", "id": None}
        )
        ctx = _make_ctx(council_memory=council, nats_bus=None)
        result = await share_to_council(ctx, "too many posts")
        assert "Rate limit exceeded" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_nats_publish_failure_does_not_crash(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.write_entry = AsyncMock(
            return_value={"success": True, "error": None, "id": "abc-123"}
        )
        nats = MagicMock()
        nats.publish_broadcast = AsyncMock(side_effect=ConnectionError("NATS down"))
        ctx = _make_ctx(council_memory=council, nats_bus=nats)
        result = await share_to_council(ctx, "still works")
        assert result == "Shared to council: still works"


class TestSanitizerIntegrationMemory:
    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_recall_private_memory_sanitized(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        memory = MagicMock()
        memory.search = AsyncMock(
            return_value=[
                {"content": "I like tea", "similarity": 0.95},
            ]
        )
        ctx = _make_ctx(private_memory=memory)
        result = await recall_private_memory(ctx, "preferences")
        assert "I like tea" in result
        assert "0.95" in result