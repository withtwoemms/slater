# --- Configuration ---
PYTHON ?= python3
UV_VENV ?= .venv
UV_INSTALLED := .uv-installed
DEPS_INSTALLED := ${UV_VENV}/.deps-installed

# --- Color Setup ---
GREEN := \033[0;32m
CYAN := \033[0;36m
YELLOW := \033[1;33m
RESET := \033[0m

# --- State Directory ---
SLATER_STATE ?= .slater_state

# --- Help Command ---
help:
	@echo "\n${YELLOW}Available commands:${RESET}\n"
	@echo "  ${CYAN}venv${RESET}              - Create local virtual environment @ \"${UV_VENV}/\" replete with dependencies using uv"
	@echo "  ${CYAN}requirements${RESET}      - Render dependencies as requirements.txt"
	@echo "  ${CYAN}tests${RESET}             - Run all tests"
	@echo "  ${CYAN}unit-tests${RESET}        - Run unit tests"
	@echo "  ${CYAN}integration-tests${RESET} - Run container tests"
	@echo "  ${CYAN}clean${RESET}             - Clean build artifacts and dependency state"
	@echo "  ${CYAN}clean-state${RESET}       - Remove agent state and history (${SLATER_STATE}/)"
	@echo

${UV_INSTALLED}:
	@command -v uv >/dev/null 2>&1 || { \
		echo "${GREEN}Installing uv...${RESET}"; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	}
	@touch ${UV_INSTALLED}

install-test: ${UV_INSTALLED}
	@uv sync --extra test

install: ${UV_INSTALLED} install-test
	@echo "${GREEN}Installing dependencies with uv...${RESET}"
	@uv sync

requirements: ${UV_INSTALLED}
	@uv export -o requirements.txt --no-extra test --no-hashes --no-editable --format requirements-txt

unit-tests: ${UV_INSTALLED} ${DEPS_INSTALLED}
	@uv run pytest -s -v tests/unit

integration-tests: ${UV_INSTALLED} build ${DEPS_INSTALLED}
	@uv run pytest -s -v tests/integration

tests: unit-tests integration-tests

${UV_VENV}: ${UV_INSTALLED}
	@echo "${GREEN}Creating local virtual environment (${UV_VENV})...${RESET}"
	@uv venv ${UV_VENV}

${DEPS_INSTALLED}: pyproject.toml | ${UV_VENV}
	@echo "Syncing dependencies into ${UV_VENV}"
	@UV_VENV=${UV_VENV} uv sync --extra test
	@touch ${DEPS_INSTALLED}

venv: ${UV_INSTALLED} ${DEPS_INSTALLED}
	@echo "${GREEN}Installing all dependencies into ${UV_VENV}...${RESET}"
	@UV_VENV=${UV_VENV} uv sync --extra test
	@echo "${CYAN}Done.${RESET}"
	@echo "${CYAN}Activate with:${RESET} source ${UV_VENV}/bin/activate"

clean-uv:
	@echo "${YELLOW}Removing uv and all associated state (destructive)...${RESET}"
	@if command -v uv >/dev/null 2>&1; then \
		uv cache clean || true; \
		rm -rf "$$(uv python dir)" "$$(uv tool dir)"; \
		rm -f "$${HOME}/.local/bin/uv" "$${HOME}/.local/bin/uvx"; \
		rm -f ${UV_INSTALLED}; \
		echo "${GREEN}uv fully removed.${RESET}"; \
	else \
		echo "${CYAN}uv not installed; nothing to clean.${RESET}"; \
	fi

clean: clean-uv
	@echo "${GREEN}Cleaning build artifacts and dependency state...${RESET}"
	@rm -f ${DEPS_INSTALLED} ${UV_INSTALLED}
	@rm -rf ${UV_VENV} .uv_cache .pytest_cache
	@find . -type d -name __pycache__ -exec rm -rf {} +

clean-state:
	@if [ -d "${SLATER_STATE}" ]; then \
		echo "${YELLOW}Removing agent state directory (${SLATER_STATE})...${RESET}"; \
		rm -rf ${SLATER_STATE}; \
		echo "${GREEN}State cleared.${RESET}"; \
	else \
		echo "${CYAN}No state directory found; nothing to clean.${RESET}"; \
	fi


.PHONY: help install install-test requirements dev build unit-tests integration-tests tests venv clean-uv clean clean-state