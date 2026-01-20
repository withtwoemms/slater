import yaml

from pydantic import BaseModel, ConfigDict
from pathlib import Path


class RepoConfig(BaseModel):
    root: Path
    ignore: list[str] = []


class LLMConfig(BaseModel):
    provider: str
    model: str
    temperature: float = 0.2


class BootstrapConfig(BaseModel):
    goal: str | None = None
    repo: RepoConfig | None = None
    llm: LLMConfig | None = None

    model_config = ConfigDict(extra="allow")

    @classmethod
    def from_yaml(cls, path: str) -> "BootstrapConfig":
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        return cls.model_validate(data)
