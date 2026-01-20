"""
Tests for BootstrapConfig and related configuration models.

These tests verify:
- YAML loading and Pydantic validation
- Structured field access (goal, repo, llm)
- Optional fields and null safety
- Extra fields are allowed (ConfigDict extra="allow")
"""

import pytest
from pathlib import Path

from slater.config import BootstrapConfig, RepoConfig, LLMConfig
from tests.fixtures import FIXTURESPATH


# ----------------------------------------------------------------------------
# RepoConfig
# ----------------------------------------------------------------------------


class TestRepoConfig:
    def test_repo_config_with_root_only(self):
        """RepoConfig requires root, ignore defaults to empty list."""
        config = RepoConfig(root=Path("/some/path"))

        assert config.root == Path("/some/path")
        assert config.ignore == []

    def test_repo_config_with_ignore_patterns(self):
        """RepoConfig accepts ignore patterns."""
        config = RepoConfig(root=Path("."), ignore=[".git", ".venv", "node_modules"])

        assert config.root == Path(".")
        assert config.ignore == [".git", ".venv", "node_modules"]

    def test_repo_config_coerces_string_to_path(self):
        """RepoConfig coerces string root to Path."""
        config = RepoConfig(root="./src")

        assert isinstance(config.root, Path)
        assert config.root == Path("./src")


# ----------------------------------------------------------------------------
# LLMConfig
# ----------------------------------------------------------------------------


class TestLLMConfig:
    def test_llm_config_required_fields(self):
        """LLMConfig requires provider and model."""
        config = LLMConfig(provider="openai", model="gpt-4")

        assert config.provider == "openai"
        assert config.model == "gpt-4"
        assert config.temperature == 0.2  # default

    def test_llm_config_custom_temperature(self):
        """LLMConfig accepts custom temperature."""
        config = LLMConfig(provider="anthropic", model="claude-3", temperature=0.7)

        assert config.temperature == 0.7

    def test_llm_config_missing_required_raises(self):
        """LLMConfig raises ValidationError for missing required fields."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LLMConfig(provider="openai")  # missing model


# ----------------------------------------------------------------------------
# BootstrapConfig - Direct Instantiation
# ----------------------------------------------------------------------------


class TestBootstrapConfigInstantiation:
    def test_empty_config(self):
        """BootstrapConfig can be created with no arguments."""
        config = BootstrapConfig()

        assert config.goal is None
        assert config.repo is None
        assert config.llm is None

    def test_config_with_goal_only(self):
        """BootstrapConfig accepts goal without repo/llm."""
        config = BootstrapConfig(goal="Refactor the authentication module")

        assert config.goal == "Refactor the authentication module"
        assert config.repo is None
        assert config.llm is None

    def test_config_with_nested_models(self):
        """BootstrapConfig accepts nested RepoConfig and LLMConfig."""
        config = BootstrapConfig(
            goal="Add tests",
            repo=RepoConfig(root=Path("/app"), ignore=[".git"]),
            llm=LLMConfig(provider="openai", model="gpt-4"),
        )

        assert config.goal == "Add tests"
        assert config.repo.root == Path("/app")
        assert config.repo.ignore == [".git"]
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4"

    def test_config_with_dict_for_nested_models(self):
        """BootstrapConfig validates nested dicts into models."""
        config = BootstrapConfig(
            goal="Fix bugs",
            repo={"root": ".", "ignore": [".venv"]},
            llm={"provider": "openai", "model": "gpt-4.1-mini"},
        )

        assert isinstance(config.repo, RepoConfig)
        assert isinstance(config.llm, LLMConfig)
        assert config.repo.root == Path(".")
        assert config.llm.model == "gpt-4.1-mini"

    def test_config_allows_extra_fields(self):
        """BootstrapConfig allows extra fields (ConfigDict extra='allow')."""
        config = BootstrapConfig(
            goal="Test extra fields",
            custom_setting="some_value",
            nested_extra={"key": "value"},
        )

        assert config.goal == "Test extra fields"
        assert config.custom_setting == "some_value"
        assert config.nested_extra == {"key": "value"}


# ----------------------------------------------------------------------------
# BootstrapConfig - YAML Loading
# ----------------------------------------------------------------------------


class TestBootstrapConfigFromYaml:
    def test_from_yaml_loads_fixture(self):
        """from_yaml loads and validates YAML file."""
        yaml_path = FIXTURESPATH / "test-slater.yaml"
        config = BootstrapConfig.from_yaml(str(yaml_path))

        assert isinstance(config, BootstrapConfig)

    def test_from_yaml_parses_repo_config(self):
        """from_yaml correctly parses repo section."""
        yaml_path = FIXTURESPATH / "test-slater.yaml"
        config = BootstrapConfig.from_yaml(str(yaml_path))

        assert config.repo is not None
        assert config.repo.root == Path(".")
        assert ".git" in config.repo.ignore
        assert ".venv" in config.repo.ignore

    def test_from_yaml_parses_llm_config(self):
        """from_yaml correctly parses llm section."""
        yaml_path = FIXTURESPATH / "test-slater.yaml"
        config = BootstrapConfig.from_yaml(str(yaml_path))

        assert config.llm is not None
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4.1-mini"
        assert config.llm.temperature == 0.2

    def test_from_yaml_preserves_extra_sections(self):
        """from_yaml preserves extra sections not in schema."""
        yaml_path = FIXTURESPATH / "test-slater.yaml"
        config = BootstrapConfig.from_yaml(str(yaml_path))

        # Extra sections allowed by ConfigDict(extra="allow")
        assert config.analysis == {"max_files": 500, "depth": "shallow"}
        assert config.validation == {"run_tests": True, "test_command": "pytest"}
        assert config.patching == {"strategy": "incremental"}

    def test_from_yaml_missing_file_raises(self):
        """from_yaml raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            BootstrapConfig.from_yaml("/nonexistent/path/config.yaml")

    def test_from_yaml_empty_file(self, tmp_path):
        """from_yaml handles empty YAML file gracefully."""
        empty_yaml = tmp_path / "empty.yaml"
        empty_yaml.write_text("")

        config = BootstrapConfig.from_yaml(str(empty_yaml))

        assert config.goal is None
        assert config.repo is None
        assert config.llm is None

    def test_from_yaml_with_goal(self, tmp_path):
        """from_yaml parses goal field."""
        yaml_content = """
goal: Implement user authentication
llm:
  provider: openai
  model: gpt-4
"""
        yaml_file = tmp_path / "with-goal.yaml"
        yaml_file.write_text(yaml_content)

        config = BootstrapConfig.from_yaml(str(yaml_file))

        assert config.goal == "Implement user authentication"
        assert config.llm.model == "gpt-4"
