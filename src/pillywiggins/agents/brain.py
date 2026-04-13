from pydantic_ai import Agent

from pillywiggins.agents.deps import AgentDeps


def create_brain(personality_prompt: str, model_name: str) -> Agent:
    agent = Agent(
        model=f"ollama:{model_name}",
        system_prompt=personality_prompt,
        deps_type=AgentDeps,
    )
    return agent