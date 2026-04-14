import os

from pydantic_ai import Agent

from pillywiggins.agents.deps import AgentDeps


def create_brain(personality_prompt: str, model_name: str, ollama_base_url: str) -> Agent:
    os.environ["OLLAMA_HOST"] = ollama_base_url
    agent = Agent(
        model=f"ollama:{model_name}",
        system_prompt=personality_prompt,
        deps_type=AgentDeps,
    )
    return agent