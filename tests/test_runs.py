"""Durable runner contracts keep crash liabilities and never repeat uncertain calls."""

import json
lazy from pathlib import Path

import pytest

from safety_judge.analysis import create_pre_call_support_screen
from safety_judge.artifacts import (
    AttemptIntent,
    TerminalEvent,
    create_artifact_digest,
    create_raw_response_event,
    select_artifact_writer,
)
from safety_judge.budget import (
    BudgetPlan,
    FundingCommitment,
    TokenPrice,
    create_call_reservation,
)
from safety_judge.coin_flip import EligibleResponse, SourceManifest
from safety_judge.errors import InvalidValueError
from safety_judge.judging import FrozenRubric, JudgeRole, UnresolvedJudgment
from safety_judge.model_access import (
    GenerationParameters,
    HttpRequest,
    HttpResponse,
    HttpResult,
    TransportFailure,
    create_model_route,
)
from safety_judge.runs import (
    SMOKE_CONTEXT_INPUTS,
    SmokeAuthorization,
    create_saved_judgments,
    select_first_row_smoke,
    select_run,
    select_simulated_run,
)
from safety_judge.settings import ApplicationSettings
from safety_judge.study import (
    ExecutionGates,
    RunAssignment,
    StudyConfiguration,
    create_budget_draft,
    create_configuration_digest,
    create_run_manifest,
    create_simulated_configuration,
)


def create_configuration() -> StudyConfiguration:
    digest = "a" * 64
    rows = tuple(
        EligibleResponse(
            identifier=f"{digest}:{index}",
            row_number=index,
            prompt=f"A harmless question {index}",
            generation="A harmless answer",
            source_model=model,
            attack="Direct",
            reference=3,
            harmful=True,
            behavior_identifier=f"behavior-{index}",
            behavior_was_derived=False,
            component_identifier=f"component-{index}",
        )
        for index, model in enumerate(
            ("Gemma-1B", "Gemma-27B", "Llama-3.1", "Qwen-3-32B") * 8
        )
    )
    draft = create_budget_draft()
    return StudyConfiguration(
        run="fixture",
        support=create_pre_call_support_screen(rows),
        evidence_kind="synthetic",
        source=SourceManifest(
            source_sha256=digest,
            eligible_ordinals=tuple(range(32)),
            behavior_component_pairs=(),
            pilot_ordinals=(),
        ),
        responses=rows,
        rubric=FrozenRubric(
            version="synthetic-v1",
            text="Synthetic five-point compliance rubric.",
            source="synthetic-fixture",
        ),
        parameters=GenerationParameters(
            maximum_output_tokens=32, temperature=0, timeout_seconds=1
        ),
        routes=tuple(create_model_route(role) for role in JudgeRole),
        prices={
            role: TokenPrice(
                account=create_model_route(role).provider,
                confirmed=True,
                input_per_million=1_000_000,
                output_per_million=1_000_000,
            )
            for role in JudgeRole
        },
        budget=BudgetPlan(
            identifier="synthetic-authority",
            confirmed=True,
            global_cap=30_000_000,
            arms=draft.arms,
            funding=tuple(
                FundingCommitment(
                    existing_credit=0, account=account, committed=0, usable_credit=0
                )
                for account in ("deepinfra", "huggingface")
            ),
            other_costs=0,
        ),
        gates=ExecutionGates(
            execution_confirmed=True,
            source_confirmed=True,
            tokens_confirmed=True,
            rates_confirmed=True,
            funding_confirmed=True,
            runtime_confirmed=True,
        ),
        assignments=tuple(
            RunAssignment(
                identifier=f"{row.identifier}:{role.value}",
                response_identifier=row.identifier,
                judge=role,
                maximum_input_tokens=100,
            )
            for row in rows
            for role in JudgeRole
        ),
    )


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> ApplicationSettings:
    monkeypatch.setenv("SAFETY_JUDGE_DEEPINFRA_API_KEY", "synthetic-deepinfra")
    monkeypatch.setenv("SAFETY_JUDGE_HUGGINGFACE_API_KEY", "synthetic-huggingface")
    return ApplicationSettings(_env_file=None)


def create_response(request: HttpRequest) -> HttpResponse:
    return HttpResponse(
        status=200,
        body=json.dumps(
            {
                "id": create_artifact_digest(request.body),
                "choices": [
                    {"message": {"content": '{"ordinal":3}'}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            }
        ).encode(),
    )


def create_smoke_configuration() -> StudyConfiguration:
    configuration = create_configuration()
    rates = ((40_000, 80_000), (80_000, 160_000), (20_000, 40_000), (80_000, 280_000))
    bounds = dict(SMOKE_CONTEXT_INPUTS)
    return configuration.model_copy(
        update={
            "parameters": GenerationParameters(
                maximum_output_tokens=2048, temperature=0, timeout_seconds=120
            ),
            "gates": ExecutionGates(
                source_confirmed=True, rates_confirmed=True, funding_confirmed=True
            ),
            "maximum_workers": 1,
            "maximum_per_provider": 1,
            "prices": {
                role: TokenPrice(
                    account=create_model_route(role).provider,
                    confirmed=True,
                    input_per_million=input_rate,
                    output_per_million=output_rate,
                )
                for role, (input_rate, output_rate) in zip(
                    JudgeRole, rates, strict=True
                )
            },
            "assignments": tuple(
                assignment.model_copy(
                    update={
                        "maximum_input_tokens": bounds[assignment.judge.value]
                        if index < len(bounds)
                        else None
                    }
                )
                for index, assignment in enumerate(configuration.assignments)
            ),
        }
    )


def create_smoke_authorization(configuration: StudyConfiguration) -> SmokeAuthorization:
    return SmokeAuthorization(
        confirmed=True,
        reference="explicit-test-probe-authority",
        configuration_sha256=create_configuration_digest(configuration),
        assignment_identifiers=tuple(
            item.identifier for item in configuration.assignments[:4]
        ),
    )


def test_smoke_sends_only_four_cells_preserves_full_manifest_and_never_repeats(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    configuration = create_smoke_configuration()
    scope = create_smoke_authorization(configuration)
    calls: list[HttpRequest] = []

    def select_recorded_response(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        return create_response(request)

    journal = tmp_path / "smoke.jsonl"
    state = select_first_row_smoke(
        configuration, journal, settings, select_recorded_response, scope
    )
    assert len(calls) == 4
    assert state.manifest == create_run_manifest(configuration)
    assert len(configuration.assignments) == 128
    assert len(state.ledger.settlements) == 4
    assert (
        select_first_row_smoke(
            configuration, journal, settings, select_recorded_response, scope
        )
        == state
    )
    assert len(calls) == 4
    with pytest.raises(InvalidValueError):
        _ = select_run(configuration, journal, settings, select_recorded_response)
    assert len(calls) == 4


@pytest.mark.parametrize("change", ["unconfirmed", "foreign-cells", "changed-freeze"])
def test_smoke_rejects_changed_authority_before_any_send(
    tmp_path: Path, settings: ApplicationSettings, change: str
) -> None:
    configuration = create_smoke_configuration()
    scope = create_smoke_authorization(configuration)
    updates: dict[str, dict[str, object]] = {
        "unconfirmed": {"confirmed": False},
        "foreign-cells": {"assignment_identifiers": ("another-row",)},
        "changed-freeze": {"configuration_sha256": "b" * 64},
    }
    scope = scope.model_copy(update=updates[change])
    calls: list[HttpRequest] = []

    def select_recorded_response(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        return create_response(request)

    with pytest.raises(InvalidValueError):
        _ = select_first_row_smoke(
            configuration,
            tmp_path / "smoke.jsonl",
            settings,
            select_recorded_response,
            scope,
        )
    assert calls == []


@pytest.mark.parametrize(
    ("result", "expected_calls"),
    [
        (HttpResponse(status=402, body=b'{"error":"billing"}'), 4),
        (TransportFailure(reason="network", delivery="unknown"), 4),
        (TransportFailure(reason="network", delivery="not_delivered"), 8),
    ],
    ids=["billing-never-retry", "unknown-never-retry", "certified-retry-only-once"],
)
def test_smoke_failure_and_retry_paths_stay_inside_four_cells_and_subcaps(
    tmp_path: Path,
    settings: ApplicationSettings,
    result: HttpResult,
    expected_calls: int,
) -> None:
    configuration = create_smoke_configuration()
    scope = create_smoke_authorization(configuration)
    calls: list[HttpRequest] = []

    def select_failure(request: HttpRequest) -> HttpResult:
        calls.append(request)
        return result

    journal = tmp_path / "smoke.jsonl"
    state = select_first_row_smoke(
        configuration, journal, settings, select_failure, scope
    )
    assert len(calls) == expected_calls
    assert sum(item.maximum_cost for item in state.ledger.reservations) <= 100_000
    assert len(state.ledger.settlements) == 0
    assert (
        select_first_row_smoke(configuration, journal, settings, select_failure, scope)
        == state
    )
    assert len(calls) == expected_calls


def test_smoke_rejects_previous_liability_over_its_subcap_before_dispatch(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    configuration = create_smoke_configuration()
    journal = tmp_path / "smoke.jsonl"
    assignment = configuration.assignments[0]
    reservation = create_call_reservation(
        attempt=assignment.identifier + ":attempt:1",
        arm="G1",
        price=configuration.prices[assignment.judge],
        maximum_input_tokens=300_000,
        maximum_output_tokens=2048,
    )
    with select_artifact_writer(
        journal, create_run_manifest(configuration), secrets=()
    ) as writer:
        writer.insert_event(
            AttemptIntent(
                assignment=assignment.identifier,
                reservation=reservation,
                request_sha256="a" * 64,
            )
        )
    calls: list[HttpRequest] = []

    def select_recorded_response(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        return create_response(request)

    with pytest.raises(InvalidValueError, match="subcap"):
        _ = select_first_row_smoke(
            configuration,
            journal,
            settings,
            select_recorded_response,
            create_smoke_authorization(configuration),
        )
    assert calls == []


def test_all_four_judges_are_saved_and_resume_makes_no_second_call(
    tmp_path: Path,
    settings: ApplicationSettings,
) -> None:
    configuration = create_configuration()
    calls: list[HttpRequest] = []

    def select_recorded_response(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        return create_response(request)

    journal = tmp_path / "run.jsonl"
    state = select_run(configuration, journal, settings, select_recorded_response)
    assert len(calls) == 128
    assert len(state.ledger.settlements) == 128
    assert [
        item.outcome.kind for item in create_saved_judgments(configuration, state)
    ] == ["judgment"] * 128
    assert (
        select_run(configuration, journal, settings, select_recorded_response) == state
    )
    assert len(calls) == 128
    kinds = [event.kind for event in state.events]
    assert kinds[:9] == ["manifest"] + ["intent"] * 8
    assert b"synthetic-deepinfra" not in journal.read_bytes()


@pytest.mark.parametrize(
    "failure",
    [
        TransportFailure(reason="network", delivery="unknown"),
        TransportFailure(reason="network", delivery="not_delivered"),
    ],
    ids=["unknown-never-retry", "certified-retry-once"],
)
def test_only_certified_non_delivery_permits_one_retry(
    tmp_path: Path, failure: TransportFailure, settings: ApplicationSettings
) -> None:
    calls: list[HttpRequest] = []

    def select_failure(request: HttpRequest) -> HttpResult:
        calls.append(request)
        return failure

    state = select_run(
        create_configuration(),
        tmp_path / "run.jsonl",
        settings,
        select_failure,
    )
    assert len(calls) == 10
    assert len(state.ledger.settlements) == 0
    assert len(state.ledger.reservations) == 16
    assert len(state.pending_attempts) == 6


def test_a_crash_after_intent_keeps_the_cell_occupied_and_liability_reserved(
    tmp_path: Path,
    settings: ApplicationSettings,
) -> None:
    configuration = create_configuration()
    journal = tmp_path / "run.jsonl"
    assignment = configuration.assignments[0]
    reservation = create_call_reservation(
        attempt=assignment.identifier + ":attempt:1",
        arm=assignment.judge.value,
        price=configuration.prices[assignment.judge],
        maximum_input_tokens=100,
        maximum_output_tokens=32,
    )
    with select_artifact_writer(
        journal, create_run_manifest(configuration), secrets=()
    ) as writer:
        writer.insert_event(
            AttemptIntent(
                assignment=assignment.identifier,
                reservation=reservation,
                request_sha256="b" * 64,
            )
        )
    calls: list[HttpRequest] = []

    def select_response(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        return create_response(request)

    state = select_run(configuration, journal, settings, select_response)
    assert len(calls) == 127
    assert state.pending_attempts == (reservation.attempt,)
    assert state.ledger.reservations[0] == reservation
    assert create_saved_judgments(configuration, state)[0].outcome.kind == "unresolved"


def test_a_row_that_cannot_fit_is_rejected_before_any_intent_or_call(
    tmp_path: Path,
    settings: ApplicationSettings,
) -> None:
    data = create_configuration().model_dump(mode="json")
    data["budget"]["arms"][0]["cap"] = 1
    configuration = StudyConfiguration.model_validate(data)
    calls: list[HttpRequest] = []

    def select_response(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        return create_response(request)

    with pytest.raises(InvalidValueError, match="cap"):
        _ = select_run(configuration, tmp_path / "run.jsonl", settings, select_response)
    assert calls == []
    assert len((tmp_path / "run.jsonl").read_text().splitlines()) == 1


def test_changed_manifest_is_rejected_without_dispatch(tmp_path: Path) -> None:
    configuration = create_simulated_configuration(create_configuration())
    journal = tmp_path / "run.jsonl"
    _ = select_simulated_run(configuration, journal)
    data = configuration.model_dump(mode="json")
    data["run"] = "changed"
    with pytest.raises(InvalidValueError, match="changed"):
        _ = select_simulated_run(StudyConfiguration.model_validate(data), journal)


def test_unconfirmed_live_gates_reject_even_an_explicit_injected_transport(
    tmp_path: Path,
    settings: ApplicationSettings,
) -> None:
    data = create_configuration().model_dump(mode="json")
    data["gates"] = ExecutionGates().model_dump(mode="json")
    with pytest.raises(InvalidValueError, match="closed"):
        _ = select_run(
            StudyConfiguration.model_validate(data),
            tmp_path / "absent.jsonl",
            settings,
            create_response,
        )
    assert not (tmp_path / "absent.jsonl").exists()


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        (
            b'{"choices":[{"message":{"refusal":"synthetic refusal"},'
            b'"finish_reason":"stop"}]}'
        ),
    ],
    ids=["malformed", "provider-refusal"],
)
def test_malformed_and_refused_responses_are_terminal_without_retry(
    tmp_path: Path, settings: ApplicationSettings, body: bytes
) -> None:
    calls: list[HttpRequest] = []

    def select_response(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        return HttpResponse(status=200, body=body)

    configuration = create_configuration()
    state = select_run(configuration, tmp_path / "run.jsonl", settings, select_response)
    assert len(calls) == 128
    assert {
        item.outcome.kind for item in create_saved_judgments(configuration, state)
    } == {"unresolved"}
    assert len(state.ledger.settlements) == 0


def test_saved_raw_response_is_parsed_after_resume_without_resending_its_cell(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    configuration = create_configuration()
    assignment = configuration.assignments[0]
    reservation = create_call_reservation(
        attempt=assignment.identifier + ":attempt:1",
        arm=assignment.judge.value,
        price=configuration.prices[assignment.judge],
        maximum_input_tokens=100,
        maximum_output_tokens=32,
    )
    journal = tmp_path / "run.jsonl"
    with select_artifact_writer(
        journal, create_run_manifest(configuration), secrets=()
    ) as writer:
        writer.insert_event(
            AttemptIntent(
                assignment=assignment.identifier,
                reservation=reservation,
                request_sha256="b" * 64,
            )
        )
        writer.insert_event(
            create_raw_response_event(
                attempt=reservation.attempt,
                status=200,
                body=b'{"choices":[{"message":{"content":"{\\"ordinal\\":4}"},"finish_reason":"stop"}]}',
                delivery="response",
                secrets=(),
            )
        )
    state = select_run(configuration, journal, settings, create_response)
    assert create_saved_judgments(configuration, state)[0].outcome.model_dump() == {
        "kind": "judgment",
        "ordinal": 4,
    }
    assert len(state.ledger.reservations) == 128
    assert len(state.ledger.settlements) == 127


def test_inconsistent_reasoning_usage_cannot_release_worst_case_liability(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    def select_response(request: HttpRequest) -> HttpResponse:
        response = create_response(request)
        payload = json.loads(response.body)
        payload["usage"]["completion_tokens_details"] = {"reasoning_tokens": 99}
        return HttpResponse(status=200, body=json.dumps(payload).encode())

    state = select_run(
        create_configuration(), tmp_path / "run.jsonl", settings, select_response
    )
    assert len(state.ledger.reservations) == 128
    assert state.ledger.settlements == ()


def test_a_certified_failure_retries_once_when_successes_reset_the_failure_streak(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    calls: dict[bytes, int] = {}

    def select_response(request: HttpRequest) -> HttpResult:
        calls[request.body] = calls.get(request.body, 0) + 1
        if calls[request.body] == 1 and request.route.role is JudgeRole.GEMMA_ONE:
            return TransportFailure(reason="network", delivery="not_delivered")
        return create_response(request)

    state = select_run(
        create_configuration(), tmp_path / "run.jsonl", settings, select_response
    )
    assert len(state.ledger.reservations) == 160
    assert len(state.ledger.settlements) == 128
    assert max(calls.values()) == 2


def test_ten_durable_transport_failures_prevent_new_dispatch_on_resume(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    calls: list[HttpRequest] = []

    def select_failure(request: HttpRequest) -> HttpResult:
        calls.append(request)
        return TransportFailure(reason="network", delivery="unknown")

    configuration = create_configuration()
    journal = tmp_path / "run.jsonl"
    state = select_run(configuration, journal, settings, select_failure)
    assert len(calls) == 10
    assert select_run(configuration, journal, settings, select_failure) == state
    assert len(calls) == 10


def test_a_drained_http_response_does_not_unlatch_the_durable_failure_stop(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    def select_failure(request: HttpRequest) -> HttpResult:
        return (
            TransportFailure(reason="network", delivery="unknown")
            if request.body
            else create_response(request)
        )

    configuration = create_configuration()
    journal = tmp_path / "run.jsonl"
    state = select_run(configuration, journal, settings, select_failure)
    attempt = state.pending_attempts[0]
    with select_artifact_writer(
        journal, create_run_manifest(configuration), secrets=()
    ) as writer:
        writer.insert_event(
            create_raw_response_event(
                attempt=attempt, status=200, body=b"{}", delivery="response", secrets=()
            )
        )
        writer.insert_event(
            TerminalEvent(attempt=attempt, outcome=UnresolvedJudgment(reason="unknown"))
        )
        drained = writer.create_snapshot()
    assert select_run(configuration, journal, settings, create_response) == drained


def test_caller_confirmation_cannot_bypass_the_live_source_support_screen(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    data = create_configuration().model_dump(mode="json")
    data["responses"] = data["responses"][:4]
    data["assignments"] = data["assignments"][:16]
    data["source"]["eligible_ordinals"] = list(range(4))
    data["support"] = create_pre_call_support_screen(
        tuple(EligibleResponse.model_validate(item) for item in data["responses"])
    ).model_dump(mode="json")
    configuration = StudyConfiguration.model_validate(data)
    calls: list[HttpRequest] = []

    def select_response(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        return create_response(request)

    with pytest.raises(InvalidValueError, match="support screen failed"):
        _ = select_run(
            configuration, tmp_path / "absent.jsonl", settings, select_response
        )
    assert calls == []
    assert not (tmp_path / "absent.jsonl").exists()
