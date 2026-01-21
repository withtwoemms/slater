import argparse
from pathlib import Path


from slater.actions import (
    AnalyzeRepo,
    ApplyPatch,
    Finalize,
    GatherContext,
    ProposePlan,
    Validate,
)
from slater.config import BootstrapConfig
from slater.controller import AgentController
from slater.phases import PhaseEnum, PhaseRule
from slater.policies import ControlPolicy, TransitionPolicy
from slater.procedures import ProcedureTemplate
from slater.spec import AgentSpec
from slater.state import FileSystemStateStore, InMemoryStateStore


# ---- define agent phases ----
Phase = PhaseEnum.create(
    "NEEDS_CONTEXT",
    "READY_TO_CONTINUE",
    "PROCEDURE_SUCCEEDED",
    "PROCEDURE_FAILED",
    "TASK_COMPLETE",
    class_name="Phase",
)


# ---- entrypoint ----

def main():
    parser = argparse.ArgumentParser(description="Run a Slater agent")
    parser.add_subparsers = parser.add_subparsers(dest="run")
    parser.add_argument("--agent-id", default="default-agent")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--bootstrap-config", default=str(Path(".slater.yaml")))
    args = parser.parse_args()

    # ---- bootstrap config ----
    bootstrap_config = BootstrapConfig.from_yaml(args.bootstrap_config)

    # optional overlay
    if args.goal:
        bootstrap_config.goal = args.goal

    # ---- event policy (intentionally minimal) ----
    control_policy = ControlPolicy(
        # Agent can proceed autonomously once discovery + analysis exist
        required_state_keys={
            "context_ready",
            "analysis_ready",
        },

        # Missing information that *must* come from the user
        user_required_keys=set(),
            # e.g. later:
            # "missing_requirements",
            # "ambiguous_goal",

        # Signals that the agent is finished
        completion_keys={
            "task_complete",
        },

        # Signals that the agent cannot continue
        failure_keys={
            "blocked",
        },
    )

    transition_policy = TransitionPolicy(
        rules=[
            PhaseRule(
                enter=Phase.NEEDS_CONTEXT,
                when_all=frozenset({"context_required"}),
            ),
            PhaseRule(
                enter=Phase.READY_TO_CONTINUE,
                when_all=frozenset({"analysis_ready", "context_ready"}),
                when_none=frozenset({"plan_ready"}),
            ),
            PhaseRule(
                enter=Phase.PROCEDURE_SUCCEEDED,
                when_all=frozenset({"plan_ready"}),
                when_none=frozenset({"validation_passed"}),
            ),
            PhaseRule(
                enter=Phase.PROCEDURE_FAILED,
                when_all=frozenset({"blocked"}),
            ),
            PhaseRule(
                enter=Phase.TASK_COMPLETE,
                when_all=frozenset({"validation_passed"}),
            ),
        ],
        default=Phase.NEEDS_CONTEXT,
    )

    # ---- procedures ----
    procedures = {
        Phase.NEEDS_CONTEXT: ProcedureTemplate(
            name="discover_and_analyze",
            actions=[
                GatherContext(),
                AnalyzeRepo(),
            ],
        ),
        # TODO: implement goal normalization and ambiguity detection
        Phase.READY_TO_CONTINUE: ProcedureTemplate(
            name="plan_next_step",
            actions=[
                # NormalizeGoal(),
                # DetectAmbiguity(),
                ProposePlan(),
            ],
        ),
        # TODO: Implement user input handling
        # Event.NEEDS_USER_INPUT: ProcedureTemplate(
        #     name="resolve_user_input",
        #     actions=[
        #         PrepareUserQuestion(),
        #         IntegrateUserInput(),
        #     ],
        # ),
        Phase.PROCEDURE_SUCCEEDED: ProcedureTemplate(
            name="execute_and_validate",
            actions=[
                ApplyPatch(),
                Validate(),
            ],
        ),
        # TODO: implement failure assessment
        Phase.PROCEDURE_FAILED: ProcedureTemplate(
            name="reflect_and_replan",
            actions=[
                # AssessFailure(),
                AnalyzeRepo(),  # intentionally reused to re-ground planning in current facts
                ProposePlan(),
            ],
        ),
        Phase.TASK_COMPLETE: ProcedureTemplate(
            name="finalize_task",
            actions=[
                Finalize(),
            ],
        ),
    }

    # ---- agent spec ----
    phases = set(Phase)

    spec = AgentSpec(
        name="slater-refactor-agent",
        version="0.1.0",
        phases=phases,
        control_policy=control_policy,
        transition_policy=transition_policy,
        procedures=procedures,
    )

    controller = AgentController(
        spec=spec,
        agent_id=args.agent_id,
        bootstrap_config=bootstrap_config,
        state_store=FileSystemStateStore(),
    )

    controller.run()


if __name__ == "__main__":
    main()
