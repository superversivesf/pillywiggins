import os

from pydantic_ai import Agent

from pillywiggins.agents.deps import AgentDeps


def create_brain(
    personality_prompt: str,
    model_name: str,
    provider: str,
    base_url: str,
    api_key: str,
) -> Agent:
    if provider == "ollama":
        os.environ["OLLAMA_BASE_URL"] = base_url or "http://localhost:11434"
        if api_key:
            os.environ["OLLAMA_API_KEY"] = api_key
        model = f"ollama:{model_name}"
    else:
        model = f"openai:{model_name}"
        os.environ["OPENAI_API_KEY"] = api_key
        if base_url:
            os.environ["OPENAI_BASE_URL"] = base_url

    agent = Agent(
        model=model,
        system_prompt=personality_prompt,
        deps_type=AgentDeps,
    )
    return agent