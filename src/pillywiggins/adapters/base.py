import logging
from abc import ABC, abstractmethod

from pillywiggins.adapters.models import list_models
from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.messaging.unified import UnifiedMessage

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    command_prefix: str = "!"  # Override in subclasses: "/" for Telegram, "!" for others

    def __init__(self, agent: PillywigginAgent, settings=None):
        self.agent = agent
        self.settings = settings
        if settings is not None:
            self._allowed_user_ids = settings.get_allowed_user_ids()
            self._allow_all = settings.allowed_user_ids.strip().lower() == "all"
        else:
            self._allowed_user_ids = set()
            self._allow_all = False

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def listen(self) -> None: ...

    @abstractmethod
    async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None: ...

    @abstractmethod
    def normalize(self, raw_message: dict) -> UnifiedMessage: ...

    async def shutdown(self) -> None:
        """Gracefully shut down the adapter. Default no-op; override in subclasses."""


    def _is_authorized(self, user_id) -> bool:
        if self._allow_all:
            return True
        allowed = {str(uid) for uid in self._allowed_user_ids}
        return str(user_id) in allowed

    @property
    def HELP_TEXT(self) -> str:
        prefix = self.command_prefix
        return (
            f"{{bold}}Pillywiggins Commands{{reset}}\n"
            f"{prefix}help — Show this message\n"
            f"{prefix}status — Show agent status (model, context size, etc.)\n"
            f"{prefix}models — List available LLM models\n"
            f"{prefix}model <name> — Switch to a different model\n"
            f"{prefix}skills — List loaded skills\n"
            f"{prefix}compact — Summarize conversation history to free context\n"
            f"{prefix}reset — Clear conversation history"
        )

    async def dispatch_command(self, text: str, conversation_key: str) -> str | None:
        """Parse and execute a command string, returning the response text.

        Handles: help, status, models, model <name>, skills, compact, reset.
        Returns None if the text is not a recognized command.
        """
        prefix = self.command_prefix
        # Strip the prefix character
        if not text.startswith(prefix):
            return None
        stripped = text[len(prefix):]
        parts = stripped.split(None, 1)
        if not parts:
            return None
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("help", "h"):
            return self.HELP_TEXT

        if cmd == "status":
            status = self.agent.get_status()
            return (
                f"Status\n"
                f"Model: {status['model_name']}\n"
                f"Messages: {status['message_count']}\n"
                f"Est. tokens: {status['estimated_tokens']}\n"
                f"Agent: {status['agent_id']}\n"
                f"Channel: {status['channel']}"
            )

        if cmd == "models":
            try:
                models = await list_models(
                    self.settings.llm_base_url,
                    self.settings.llm_api_key,
                    self.settings.llm_provider,
                )
                if not models:
                    return "No models available."
                models = sorted(models, key=lambda m: m.id)
                current = self.agent.model_name
                lines = []
                for m in models[:20]:
                    marker = " (current)" if m.id == current else ""
                    lines.append(f"  {m.id}{marker}")
                return "Available Models\n" + "\n".join(lines)
            except Exception as exc:
                return f"Could not list models: {exc}"

        if cmd == "model":
            if not arg:
                return f"Current model: {self.agent.model_name}"
            self.agent.switch_model(arg)
            return f"Switched to model {self.agent.model_name}"

        if cmd == "skills":
            registry = getattr(self.agent, "_skill_registry", None)
            if registry is None:
                return "No skill registry loaded."
            skills = registry.list_skills()
            if not skills:
                return "No skills loaded."
            lines = []
            for s in skills:
                lines.append(f"  {s.name} — {s.description or 'No description'}")
            return "Loaded Skills\n" + "\n".join(lines)

        if cmd == "compact":
            result = await self.agent.compact_history(conversation_key=conversation_key)
            return f"Compacted: {result}"

        if cmd == "reset":
            await self.agent.clear_history(conversation_key=conversation_key)
            return "Conversation history cleared."

        return None