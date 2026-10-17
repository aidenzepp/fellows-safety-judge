"""Explicit offline file workflows; this entry point never dispatches model calls."""

import argparse
import json
import sys
from pathlib import Path
lazy from collections.abc import Sequence

from pydantic import TypeAdapter, ValidationError

from safety_judge.analysis import create_pre_call_support_screen
from safety_judge.artifacts import create_replay_state, select_artifact_events
from safety_judge.budget import TokenPrice
from safety_judge.coin_flip import (
    CONSERVATIVE_BEHAVIOR_LINKS,
    create_source_audit,
    create_source_manifest,
    select_source_inventory,
)
from safety_judge.errors import InvalidValueError, SafetyJudgeError
from safety_judge.estimation import EstimateInputs, create_study_estimate
from safety_judge.judging import FrozenRubric, JudgeRole
from safety_judge.model_access import GenerationParameters, create_model_route
from safety_judge.reporting import (
    ReportProvenance,
    StudyReport,
    create_report_markdown,
    select_study_report,
)
from safety_judge.review import (
    PilotSample,
    ReviewCase,
    ReviewContract,
    ReviewRecord,
    create_fidelity_gate,
    create_pilot_sample,
    create_rewrite_request,
)
from safety_judge.runs import create_saved_judgments, select_simulated_run
from safety_judge.study import (
    OfflineSource,
    RunAssignment,
    StudyConfiguration,
    create_budget_draft,
    create_run_manifest,
    create_simulated_configuration,
)


class CommandArguments(argparse.Namespace):
    """Typed parsed machine interface; paths are always explicitly supplied."""

    command: str = ""
    source: Path = Path()
    output: Path = Path()
    rubric: Path = Path()
    parameters: Path = Path()
    run: str = ""
    configuration: Path = Path()
    journal: Path = Path()
    markdown: Path | None = None
    replicates: int = 9999
    contract: Path = Path()
    cases: Path = Path()
    records: Path = Path()
    main_report: Path = Path()
    component_links: Path | None = None
    assumptions: Path = Path()
    frozen_output: Path = Path()


def create_parser() -> argparse.ArgumentParser:
    """Create the discoverable offline command surface with no inference command.

    Returns:
        Parser whose subcommands require explicit local input/output paths.
    """
    parser = argparse.ArgumentParser(
        description="Offline evidence workflows. No model calls or purchases."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser(
        "audit", help="Audit an explicit local CSV and freeze source/pilot manifests."
    )
    _ = audit.add_argument("--source", required=True, type=Path)
    _ = audit.add_argument("--output", required=True, type=Path)
    _ = audit.add_argument(
        "--component-links",
        type=Path,
        help="Explicit custom edge JSON; defaults to accepted source edges.",
    )
    prepare = commands.add_parser(
        "prepare",
        help="Freeze an unfunded study from audit, rubric and generation JSON.",
    )
    for name in ("source", "rubric", "parameters", "output"):
        _ = prepare.add_argument(f"--{name}", required=True, type=Path)
    _ = prepare.add_argument("--run", required=True)
    for name, help_text in (
        ("inspect", "Validate/replay a journal and export saved judgments."),
        (
            "report",
            "Analyze saved judgments; all fixed report families remain visible.",
        ),
    ):
        command = commands.add_parser(name, help=help_text)
        for path in ("configuration", "journal", "output"):
            _ = command.add_argument(f"--{path}", required=True, type=Path)
        if name == "report":
            _ = command.add_argument("--markdown", type=Path)
            _ = command.add_argument("--replicates", type=int, default=9999)
    requests = commands.add_parser(
        "review-requests",
        help="Export fixed pilot rewrite requests; never execute them.",
    )
    _ = requests.add_argument("--configuration", required=True, type=Path)
    _ = requests.add_argument("--output", required=True, type=Path)
    review = commands.add_parser(
        "review-import",
        help="Validate independently saved review records and evaluate the fixed gate.",
    )
    for name in ("contract", "cases", "records", "main-report", "output"):
        _ = review.add_argument(f"--{name}", required=True, type=Path)
    estimate = commands.add_parser(
        "estimate",
        help="Estimate per-arm cost and runtime hours from explicit JSON assumptions.",
    )
    _ = estimate.add_argument("--assumptions", required=True, type=Path)
    _ = estimate.add_argument("--output", required=True, type=Path)
    mock = commands.add_parser(
        "mock-dry-run",
        help="Run a synthetic fixture with no credentials or network.",
    )
    for name in ("configuration", "journal", "frozen-output", "output"):
        _ = mock.add_argument(f"--{name}", required=True, type=Path)
    presentations = commands.add_parser(
        "review-presentations",
        help="Export blinded paired requests from explicitly saved ReviewCase JSON.",
    )
    _ = presentations.add_argument("--cases", required=True, type=Path)
    _ = presentations.add_argument("--output", required=True, type=Path)
    return parser


def insert_json(path: Path, value: object) -> None:
    """Write a new explicit local JSON artifact without overwriting prior evidence.

    Args:
        path: Caller-selected destination with an existing parent.
        value: JSON-serializable model data, without credentials.
    """
    with path.open("x", encoding="utf-8") as destination:
        _ = destination.write(
            json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
        )


def _select_audit(arguments: CommandArguments) -> None:
    """Audit exact local bytes using the accepted linkage owner and pilot quotas.

    Args:
        arguments: Explicit source and new output destination.
    """
    inventory = select_source_inventory(arguments.source)
    links = (
        CONSERVATIVE_BEHAVIOR_LINKS
        if arguments.component_links is None
        else TypeAdapter(tuple[tuple[str, str], ...]).validate_json(
            arguments.component_links.read_bytes()
        )
    )
    audit = create_source_audit(inventory, component_links=links)
    pilot = create_pilot_sample(audit.responses)
    bundle = OfflineSource(
        source=create_source_manifest(
            inventory,
            audit,
            pilot.candidate_ordinals if isinstance(pilot, PilotSample) else (),
        ),
        audit=audit,
        pilot=pilot,
        support=create_pre_call_support_screen(audit.responses),
    )
    insert_json(arguments.output, bundle.model_dump(mode="json"))


def _select_prepared_configuration(arguments: CommandArguments) -> None:
    """Freeze all-four assignments under unconfirmed funding and token bounds.

    Args:
        arguments: Audit bundle, exact rubric and generation controls.
    """
    source = OfflineSource.model_validate_json(arguments.source.read_bytes())
    configuration = StudyConfiguration(
        run=arguments.run,
        source=source.source,
        support=source.support,
        responses=source.audit.responses,
        rubric=FrozenRubric.model_validate_json(arguments.rubric.read_bytes()),
        parameters=GenerationParameters.model_validate_json(
            arguments.parameters.read_bytes()
        ),
        routes=tuple(create_model_route(role) for role in JudgeRole),
        prices={
            role: TokenPrice(
                account=create_model_route(role).provider,
                confirmed=False,
                input_per_million=None,
                output_per_million=None,
            )
            for role in JudgeRole
        },
        budget=create_budget_draft(),
        assignments=tuple(
            RunAssignment(
                identifier=f"{row.identifier}:{role.value}",
                response_identifier=row.identifier,
                judge=role,
                maximum_input_tokens=None,
            )
            for row in source.audit.responses
            for role in JudgeRole
        ),
    )
    insert_json(arguments.output, configuration.model_dump(mode="json"))


def _select_journal_command(arguments: CommandArguments) -> None:
    """Replay exact persisted evidence and optionally render the full fixed report.

    Args:
        arguments: Matching configuration/journal and explicit new destinations.
    """
    configuration = StudyConfiguration.model_validate_json(
        arguments.configuration.read_bytes()
    )
    state = create_replay_state(
        select_artifact_events(arguments.journal), create_run_manifest(configuration)
    )
    judgments = create_saved_judgments(configuration, state)
    if arguments.command == "inspect":
        insert_json(
            arguments.output,
            {
                "evidence_kind": configuration.evidence_kind,
                "pending_attempts": state.pending_attempts,
                "ledger": state.ledger.model_dump(mode="json"),
                "judgments": [item.model_dump(mode="json") for item in judgments],
            },
        )
        return
    report = select_study_report(
        configuration.responses,
        judgments,
        provenance=ReportProvenance(
            evidence_kind=configuration.evidence_kind,
            execution_mode=configuration.execution_mode,
            configuration_sha256=state.manifest.configuration_sha256,
        ),
        replicates=arguments.replicates,
    )
    insert_json(arguments.output, report.model_dump(mode="json"))
    if arguments.markdown is not None:
        with arguments.markdown.open("x", encoding="utf-8") as destination:
            _ = destination.write(create_report_markdown(report))


def _select_review_requests(arguments: CommandArguments) -> None:
    """Render exact fixed-pilot rewrite requests without model dispatch.

    Args:
        arguments: Frozen configuration and new local request manifest path.
    """
    configuration = StudyConfiguration.model_validate_json(
        arguments.configuration.read_bytes()
    )
    pilot = set(configuration.source.pilot_ordinals)
    insert_json(
        arguments.output,
        {
            "configuration_sha256": create_run_manifest(
                configuration
            ).configuration_sha256,
            "execution_allowed": False,
            "requests": [
                {
                    "case_identifier": row.identifier,
                    "request": create_rewrite_request(
                        row.prompt, row.generation
                    ).model_dump(mode="json"),
                }
                for row in configuration.responses
                if row.row_number in pilot
            ],
        },
    )


def _select_review_presentations(arguments: CommandArguments) -> None:
    """Export frozen pair-visible requests without labels or another reviewer's work.

    Args:
        arguments: Saved review cases and new blinded presentation destination.
    """
    cases = TypeAdapter(tuple[ReviewCase, ...]).validate_json(
        arguments.cases.read_bytes()
    )
    insert_json(
        arguments.output,
        {
            "execution_allowed": False,
            "presentations": [
                {
                    "case_identifier": case.response.identifier,
                    "request": case.request.model_dump(mode="json")
                    if case.request
                    else None,
                }
                for case in cases
            ],
        },
    )


def _select_imported_reviews(arguments: CommandArguments) -> None:
    """Validate imported independent records against saved cases and main results.

    Args:
        arguments: Exact contract, cases, separate reviews and saved main report.

    Raises:
        InvalidValueError: If the main report belongs to a different configuration.
    """
    contract = ReviewContract.model_validate_json(arguments.contract.read_bytes())
    cases = TypeAdapter(tuple[ReviewCase, ...]).validate_json(
        arguments.cases.read_bytes()
    )
    records = TypeAdapter(tuple[ReviewRecord, ...]).validate_json(
        arguments.records.read_bytes()
    )
    report = StudyReport.model_validate_json(arguments.main_report.read_bytes())
    if report.configuration_sha256 != contract.original_configuration_sha256:
        message = (
            "Main report configuration differs; supply the frozen original report."
        )
        raise InvalidValueError(message)
    gate = create_fidelity_gate(
        cases,
        records,
        contract,
        main_h1_rejected=report.decisions.primary_rejected
        if report.decisions
        else False,
    )
    insert_json(arguments.output, gate.model_dump(mode="json"))


def _select_estimate(arguments: CommandArguments) -> None:
    """Write scenario costs and hours with unknown inputs explicitly retained.

    Args:
        arguments: Explicit complete assumptions file and new estimate destination.
    """
    inputs = EstimateInputs.model_validate_json(arguments.assumptions.read_bytes())
    insert_json(arguments.output, create_study_estimate(inputs).model_dump(mode="json"))


def _select_mock_run(arguments: CommandArguments) -> None:
    """Freeze and run a separate simulated matrix without reading any settings.

    Args:
        arguments: Prepared configuration plus distinct synthetic destinations.
    """
    configuration = create_simulated_configuration(
        StudyConfiguration.model_validate_json(arguments.configuration.read_bytes())
    )
    insert_json(arguments.frozen_output, configuration.model_dump(mode="json"))
    state = select_simulated_run(configuration, arguments.journal)
    insert_json(
        arguments.output,
        {
            "evidence_kind": "synthetic",
            "judgments": [
                item.model_dump(mode="json")
                for item in create_saved_judgments(configuration, state)
            ],
        },
    )


def select_command_line(arguments: Sequence[str] | None = None) -> int:
    """Execute offline file commands and return a stable process exit status.

    Args:
        arguments: Explicit token sequence, or None for normal process arguments.

    Returns:
        Zero on success; two for invalid source, configuration or storage inputs.
    """
    parsed = create_parser().parse_args(arguments, namespace=CommandArguments())
    operations = {
        "audit": _select_audit,
        "estimate": _select_estimate,
        "mock-dry-run": _select_mock_run,
        "prepare": _select_prepared_configuration,
        "inspect": _select_journal_command,
        "report": _select_journal_command,
        "review-requests": _select_review_requests,
        "review-import": _select_imported_reviews,
        "review-presentations": _select_review_presentations,
    }
    try:
        _ = operations[parsed.command](parsed)
    except (SafetyJudgeError, ValidationError, OSError) as cause:
        _ = sys.stderr.write(f"Offline command failed: {cause}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(select_command_line())
