from pathlib import Path

from actionpack import Action

from slater.context import IterationContextView
from slater.state import IterationState
from slater.types import (
    Emission,
    EmissionSpec,
    Facts,
    KnowledgeFact,
    ProgressFact,
)


class SlaterAction(Action):
    """
    Immutable Action template.
    Materialized instances may have state and/or context bound.

    Subclasses should declare their emissions via the `emits` class attribute:

        class MyAction(SlaterAction):
            emits = EmissionSpec(
                result=Emission("session", KnowledgeFact),
                ready=Emission("session", ProgressFact),
            )

            def instruction(self) -> Facts:
                return self.emits.build(result=..., ready=...)

    This ensures the emission contract is declared once and validated at build time.
    """

    requires_state: bool = False
    requires_context: bool = False

    # Emission declaration - subclasses override with their EmissionSpec
    emits: EmissionSpec | None = None

    _state: IterationState | None = None
    _ctx: IterationContextView | None = None

    # ---- uniform accessors ----

    @property
    def state(self) -> IterationState:
        if self._state is None:
            raise RuntimeError(
                f"{self.__class__.__name__} requires state but none was bound"
            )
        return self._state

    @property
    def ctx(self) -> IterationContextView:
        if self._ctx is None:
            raise RuntimeError(
                f"{self.__class__.__name__} requires context but none was bound"
            )
        return self._ctx

    def _clone(self) -> "SlaterAction":
        """
        Subclasses may override if they have config.
        """
        clone = type(self)()
        clone.name = self.name or str(self.__class__.__name__)
        return clone

    def materialize(
        self,
        *,
        state: IterationState | None = None,
        ctx: IterationContextView | None = None,
    ) -> "SlaterAction":
        action = self._clone()

        if self.requires_state:
            if state is None:
                raise RuntimeError(f"{self.name} requires state")
            action._state = state

        if self.requires_context:
            if ctx is None:
                raise RuntimeError(f"{self.name} requires context")
            action._ctx = ctx

        return action


# TODO: implement PrepareUserQuestion and IntegrateUserInput

class ProposePlan(SlaterAction):
    """
    Produce or update a refactoring plan based on the user's goal
    and any available repository analysis.
    """
    requires_state = True
    requires_context = True

    def instruction(self) -> Facts:
        # ---- read from iteration context ----

        ctx = self.ctx
        llm = ctx.llm

        assert llm, f"LLM client must be available in context for {self.__class__.__name__}"

        state = self.state
        goal: str = state["goal"]  # required by EventPolicy
        analysis = state.get("analysis")  # optional

        # ---- construct prompt/messages ----

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a software refactoring assistant. "
                    "Your task is to propose a clear, step-by-step refactoring plan. "
                    "Do not write code. Do not speculate beyond the repository context."
                ),
            },
            {
                "role": "user",
                "content": f"Refactoring goal:\n{goal}",
            },
        ]

        if analysis is not None:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Repository analysis:\n"
                        f"{analysis}"
                    ),
                }
            )

        messages.append(
            {
                "role": "user",
                "content": (
                    "Produce a concise refactoring plan as a numbered list of steps. "
                    "Each step should describe *what* to change, not *how to code it*."
                ),
            }
        )

        # ---- invoke LLM (mechanism, not intent) ----

        plan_text: str = llm.chat(
            model="gpt-4.1-mini",
            messages=messages,
        )

        # ---- normalize output into state-friendly form ----

        plan = {
            "summary": goal,
            "steps": [
                line.strip()
                for line in plan_text.splitlines()
                if line.strip()
            ],
        }

        # ---- return value (actionpack wraps in Result) ----
        return Facts(
            plan=KnowledgeFact(key="plan", value=plan, scope="session"),
            plan_ready=ProgressFact(key="plan_ready", value=True, scope="session"),
        )


class GatherContext(SlaterAction):
    """
    Discover baseline repository context required for agent operation.
    This action performs *fact gathering*, not analysis or planning.
    """
    requires_state = True

    def instruction(self) -> Facts:
        state = self.state

        # ---- determine repo root ----

        repo_root = state.get("repo_root")
        if repo_root is None:
            repo_root = Path.cwd()
        else:
            repo_root = Path(repo_root)

        assert repo_root.exists(), f"Repo root does not exist: {repo_root}"

        # ---- gather repo tree (bounded, shallow) ----

        repo_tree: list[str] = []

        for path in repo_root.rglob("*"):
            # skip common noise
            if path.is_dir() and path.name in {".git", "__pycache__", ".venv"}:
                continue
            if path.is_file():
                repo_tree.append(str(path.relative_to(repo_root)))

        # ---- infer language (very naive, prototype-safe) ----

        language = None
        if any(p.endswith(".py") for p in repo_tree):
            language = "python"
        elif any(p.endswith(".ts") or p.endswith(".js") for p in repo_tree):
            language = "javascript"
        elif any(p.endswith(".go") for p in repo_tree):
            language = "go"

        # ---- infer build system (best-effort) ----

        build_system = None
        if "pyproject.toml" in repo_tree or "setup.py" in repo_tree:
            build_system = "python"
        elif "package.json" in repo_tree:
            build_system = "node"
        elif "go.mod" in repo_tree:
            build_system = "go"

        # ---- return discovered context ----

        return Facts(
            repo_root=KnowledgeFact(key="repo_root", value=str(repo_root)),
            repo_tree=KnowledgeFact(key="repo_tree", value=repo_tree),
            language=KnowledgeFact(key="language", value=language),
            build_system=KnowledgeFact(key="build_system", value=build_system),
            context_ready=ProgressFact(key="context_ready", value=True, scope="session"),
        )


class AnalyzeRepo(SlaterAction):
    """
    Interpret repository structure discovered by GatherContext and
    derive high-level structural signals.

    This action performs no filesystem access and relies entirely
    on repo_tree and related facts already present in state.
    """
    requires_state = True

    def instruction(self) -> Facts:
        state = self.state

        # ---- required inputs from GatherContext ----

        repo_tree: list[str] = state["repo_tree"]
        primary_language = state.get("language")
        build_system = state.get("build_system")

        # ---- basic metrics ----

        file_count = len(repo_tree)

        # ---- aggregate language signals ----

        languages: set[str] = set()

        for path in repo_tree:
            if path.endswith(".py"):
                languages.add("python")
            elif path.endswith(".ts"):
                languages.add("typescript")
            elif path.endswith(".js"):
                languages.add("javascript")
            elif path.endswith(".go"):
                languages.add("go")

        # Fall back to GatherContext inference if needed
        if not languages and primary_language:
            languages.add(primary_language)

        # ---- test discovery ----

        has_tests = any(
            p.startswith("tests/")
            or p.endswith("_test.py")
            or p.endswith(".spec.ts")
            for p in repo_tree
        )

        # ---- entrypoint discovery ----

        entrypoints: list[str] = []

        if "python" in languages:
            for candidate in ("main.py", "app.py", "__main__.py"):
                if candidate in repo_tree:
                    entrypoints.append(candidate)

        if {"javascript", "typescript"} & languages:
            if "package.json" in repo_tree:
                entrypoints.append("package.json")

        # ---- human-readable structural notes ----

        notes: list[str] = []

        if file_count > 500:
            notes.append("Large repository; refactors should be incremental.")

        if not has_tests:
            notes.append("No obvious test suite detected.")

        if len(languages) > 1:
            notes.append("Multiple languages detected.")

        if build_system is None:
            notes.append("Build system could not be confidently inferred.")

        # ---- return analysis ----

        return Facts(
            repo=Facts(
                file_count=KnowledgeFact(key="file_count", value=file_count),
                languages=KnowledgeFact(key="languages", value=sorted(languages)),
                has_tests=KnowledgeFact(key="has_tests", value=has_tests),
                entrypoints=KnowledgeFact(key="entrypoints", value=entrypoints),
                build_system=KnowledgeFact(key="build_system", value=build_system),
                notes=KnowledgeFact(key="notes", value=notes),
            ),
            analysis_ready=ProgressFact(key="analysis_ready", value=True, scope="session"),
        )


class ApplyPatch(SlaterAction):
    """
    Apply a refactoring plan to the repository.

    Prototype behavior:
    - Materializes the current plan as a markdown file in the repo root.
    """
    requires_state = True

    def instruction(self) -> Facts:
        state = self.state

        repo_root = Path(state["repo_root"])
        plan = state["plan"]

        patch_file = repo_root / ".slater_plan.md"

        try:
            # ---- materialize plan as a patch artifact ----
            # TODO: make this its own Action that ApplyPatch can depend on

            lines = ["# Slater Refactoring Plan", ""]

            summary = plan.get("summary")
            if summary:
                lines.append(f"## Goal\n{summary}\n")

            steps = plan.get("steps", [])
            if steps:
                lines.append("## Proposed Steps")
                for i, step in enumerate(steps, start=1):
                    lines.append(f"{i}. {step}")

            patch_file.write_text("\n".join(lines))

            return Facts(
                patch_applied=ProgressFact(key="patch_applied", value=True, scope="session"),
                patch_summary=KnowledgeFact(key="patch_summary", value=f"Wrote refactoring plan to {patch_file.name}", scope="session"),
            )

        except Exception as exc:
            return Facts(
                patch_applied=ProgressFact(key="patch_applied", value=False, scope="session"),
                patch_errors=KnowledgeFact(key="patch_errors", value=[str(exc)], scope="session"),
            )


class Validate(SlaterAction):
    """
    Validate the outcome of the most recent patch application.

    Prototype behavior:
    - Confirms that the patch artifact exists and is readable.

    Beyond prototype, this action could:
    - Run tests to confirm no regressions
    - Perform static analysis or linting
    - Solicit human feedback
    """
    requires_state = True

    def instruction(self) -> Facts:
        state = self.state

        repo_root = Path(state["repo_root"])
        patch_applied = state.get("patch_applied", False)
        patch_errors = state.get("patch_errors")

        errors: list[str] = []

        if not patch_applied:
            errors.append("Patch was not applied.")

        patch_file = repo_root / ".slater_plan.md"

        if patch_applied:
            if not patch_file.exists():
                errors.append("Expected patch artifact '.slater_plan.md' does not exist.")
            elif not patch_file.is_file():
                errors.append("Patch artifact exists but is not a file.")
            else:
                try:
                    patch_file.read_text()
                except Exception as exc:
                    errors.append(f"Patch artifact is unreadable: {exc}")

        if patch_errors:
            errors.extend(patch_errors)

        if errors:
            return Facts(
                validation_passed=ProgressFact(key="validation_passed", value=False, scope="session"),
                validation_errors=KnowledgeFact(key="validation_errors", value=errors, scope="session"),
            )

        return Facts(
            validation_passed=ProgressFact(key="validation_passed", value=True, scope="session"),
        )


class Finalize(SlaterAction):
    """
    Finalize the agent run by marking the task complete and
    emitting a human-readable summary of the outcome.
    """
    requires_state = True

    def instruction(self) -> Facts:
        state = self.state

        summary_lines: list[str] = []

        plan = state.get("plan")
        if plan:
            goal = plan.get("summary")
            if goal:
                summary_lines.append(f"Goal: {goal}")

        if state.get("validation_passed"):
            summary_lines.append("Status: Refactoring step completed successfully.")
        else:
            summary_lines.append("Status: Task completed with unresolved issues.")

        errors = state.get("validation_errors")
        if errors:
            summary_lines.append("Validation errors:")
            for err in errors:
                summary_lines.append(f"- {err}")

        patch_summary = state.get("patch_summary")
        if patch_summary:
            summary_lines.append(f"Patch: {patch_summary}")

        final_summary = "\n".join(summary_lines) if summary_lines else "Task completed."

        return Facts(
            task_complete=ProgressFact(key="task_complete", value=True, scope="session"),
            final_summary=KnowledgeFact(key="final_summary", value=final_summary),
        )
