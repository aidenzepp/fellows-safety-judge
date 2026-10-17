"""Controlled main keeps distinct-cell stops, conservative caps and linear replay."""

import json
lazy from pathlib import Path

import pytest

from safety_judge.analysis import create_pre_call_support_screen
from safety_judge.artifacts import (
    ArtifactWriter,
    AttemptIntent,
    RawResponseEvent,
    ReplayState,
    create_artifact_digest,
    select_artifact_writer,
)
from safety_judge.budget import (
    BudgetPlan,
    FundingCommitment,
    TokenPrice,
    create_call_reservation,
)
from safety_judge.coin_flip import EligibleResponse, SourceManifest
from safety_judge.judging import FrozenRubric, JudgeRole
from safety_judge.main_execution import (
    MainMonitor,
    MainProgress,
    create_mode_reconciliation,
    select_controlled_main,
)
from safety_judge.model_access import (
    GenerationParameters,
    HttpRequest,
    HttpResponse,
    HttpResult,
    TransportFailure,
    create_model_route,
)
from safety_judge.runs import (
    create_assignment_request,
    insert_attempt_result,
    insert_usage_settlement,
)
from safety_judge.settings import ApplicationSettings
from safety_judge.study import (
    ExecutionGates,
    MainExecutionPolicy,
    RunAssignment,
    StudyConfiguration,
    create_budget_draft,
    create_run_manifest,
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


def create_controlled_configuration() -> StudyConfiguration:
    configuration = create_configuration()
    return configuration.model_copy(
        update={
            "output_modes": dict.fromkeys(JudgeRole, "json_schema"),
            "output_schema_sha256": (
                "688e7a68e55e0c09e7144eec3f3b428aced1cfaec0742e25dc89a1d982e055bb"
            ),
            "main_policy": MainExecutionPolicy(
                initial_workers=6,
                initial_provider_limits={"huggingface": 2, "deepinfra": 4},
                steady_workers=24,
                steady_provider_limits={"huggingface": 8, "deepinfra": 16},
                projected_input_tokens=dict.fromkeys(JudgeRole, 100),
            ),
        }
    )


def test_controlled_main_completes_once_and_materializes_history_only_at_checkpoints(
    tmp_path: Path, settings: ApplicationSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    configuration = create_controlled_configuration()
    calls: list[HttpRequest] = []
    checkpoints: list[MainProgress] = []
    snapshots: list[int] = []
    original = ArtifactWriter.create_snapshot

    def create_counted_snapshot(writer: ArtifactWriter) -> ReplayState:
        snapshots.append(1)
        return original(writer)

    def select_recorded(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        return create_response(request)

    monkeypatch.setattr(ArtifactWriter, "create_snapshot", create_counted_snapshot)
    journal = tmp_path / "main.jsonl"
    state = select_controlled_main(
        configuration, journal, settings, select_recorded, progress=checkpoints.append
    )
    assert len(calls) == 128
    assert len(snapshots) <= 3
    assert checkpoints[-1].completed == dict.fromkeys(JudgeRole, 32)
    assert checkpoints[-1].steady
    assert checkpoints[-1].stop_reason is None
    assert (
        select_controlled_main(
            configuration,
            journal,
            settings,
            select_recorded,
            progress=checkpoints.append,
        )
        == state
    )
    assert len(calls) == 128


def test_systemic_failure_waits_for_twenty_logical_cells_then_latches_on_resume(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    configuration = create_controlled_configuration()
    calls: list[HttpRequest] = []
    checkpoints: list[MainProgress] = []

    def select_judge_response(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        if request.route.role == JudgeRole.GEMMA_ONE:
            data = json.loads(create_response(request).body)
            data["choices"][0]["message"]["content"] = "1"
            return HttpResponse(status=200, body=json.dumps(data).encode())
        return create_response(request)

    journal = tmp_path / "main.jsonl"
    state = select_controlled_main(
        configuration,
        journal,
        settings,
        select_judge_response,
        progress=checkpoints.append,
    )
    assert len(calls) == 78
    assert checkpoints[-1].completed == {
        JudgeRole.GEMMA_ONE: 20,
        JudgeRole.GEMMA_TWENTY_SEVEN: 20,
        JudgeRole.LLAMA_EIGHT: 19,
        JudgeRole.QWEN_THIRTY_TWO: 19,
    }
    assert checkpoints[-1].normalized_valid[JudgeRole.GEMMA_ONE] == 0
    assert checkpoints[-1].stop_reason == "systemic_failure"
    assert (
        select_controlled_main(
            configuration,
            journal,
            settings,
            select_judge_response,
            progress=checkpoints.append,
        )
        == state
    )
    assert len(calls) == 78


def test_large_window_shrinks_to_affordable_complete_rows_before_a_cap_stop(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    configuration = create_controlled_configuration()
    policy = configuration.main_policy
    assert policy is not None
    configuration = configuration.model_copy(
        update={
            "main_policy": policy.model_copy(
                update={
                    "projected_input_tokens": dict.fromkeys(JudgeRole, 0),
                    "projection_attempts": 1,
                }
            ),
            "budget": configuration.budget.model_copy(
                update={
                    "arms": tuple(
                        arm.model_copy(update={"cap": 1400}) if arm.arm == "G1" else arm
                        for arm in configuration.budget.arms
                    )
                }
            ),
        }
    )
    calls: list[HttpRequest] = []
    checkpoints: list[MainProgress] = []

    def select_recorded(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        return create_response(request)

    _ = select_controlled_main(
        configuration,
        tmp_path / "main.jsonl",
        settings,
        select_recorded,
        progress=checkpoints.append,
    )
    assert len(calls) == 128
    assert checkpoints[-1].stop_reason is None
    assert checkpoints[-1].completed == dict.fromkeys(JudgeRole, 32)


def test_certified_intermediate_attempts_never_become_replayed_logical_failures(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    configuration = create_controlled_configuration()
    attempts: dict[bytes, int] = {}
    checkpoints: list[MainProgress] = []

    def select_once_not_delivered(request: HttpRequest) -> HttpResult:
        attempts[request.body] = attempts.get(request.body, 0) + 1
        if request.route.role == JudgeRole.GEMMA_ONE and attempts[request.body] == 1:
            return TransportFailure(reason="network", delivery="not_delivered")
        return create_response(request)

    state = select_controlled_main(
        configuration,
        tmp_path / "main.jsonl",
        settings,
        select_once_not_delivered,
        progress=checkpoints.append,
    )
    replayed = MainMonitor(configuration, state)
    assert replayed.stop_reason is None
    assert (
        replayed.completed == checkpoints[-1].completed == dict.fromkeys(JudgeRole, 32)
    )
    assert (
        replayed.normalized_valid
        == checkpoints[-1].normalized_valid
        == dict.fromkeys(JudgeRole, 32)
    )
    assert sum(attempts.values()) == 160


def test_mode_bridge_preserves_raw_and_reuses_four_cells_without_duplicate_calls(
    tmp_path: Path, settings: ApplicationSettings
) -> None:
    configuration = create_controlled_configuration()
    initial = configuration.model_copy(update={"main_policy": None})
    probe_journal = tmp_path / "probe.jsonl"
    with select_artifact_writer(
        probe_journal, create_run_manifest(initial), secrets=()
    ) as writer:
        for assignment in initial.assignments[:4]:
            response = initial.responses[0]
            modes = (
                ("json_schema", "json_object")
                if assignment.judge == JudgeRole.LLAMA_EIGHT
                else ("json_schema",)
            )
            for number, mode in enumerate(modes, 1):
                request = create_assignment_request(
                    initial, assignment, response, None, mode
                )
                namespace = f"{assignment.identifier}:mode:{mode}"
                reservation = create_call_reservation(
                    attempt=f"{namespace}:attempt:{number}",
                    arm=assignment.judge.value,
                    price=initial.prices[assignment.judge],
                    maximum_input_tokens=100,
                    maximum_output_tokens=32,
                )
                writer.insert_event(
                    AttemptIntent(
                        assignment=namespace,
                        reservation=reservation,
                        request_sha256=create_artifact_digest(request.body),
                    )
                )
                result = (
                    HttpResponse(
                        status=400,
                        body=b'{"error":{"message":"json_schema is not supported"}}',
                    )
                    if number == 1 and len(modes) == 2
                    else create_response(request)
                )
                insert_attempt_result(writer, reservation.attempt, result, ())
                insert_usage_settlement(
                    writer, initial, assignment, reservation.attempt, result
                )
        probe = writer.create_snapshot()
    configuration = configuration.model_copy(
        update={
            "output_modes": {
                role: (
                    "json_object" if role == JudgeRole.LLAMA_EIGHT else "json_schema"
                )
                for role in JudgeRole
            }
        }
    )
    before = probe_journal.read_bytes()
    bridge = create_mode_reconciliation(configuration, probe)
    assert len(bridge.original_attempts) == 4
    assert {item.arm: item.cap for item in bridge.diagnostic_exposure}["L8"] == 132
    original_raw = {
        event.attempt: event
        for event in probe.events
        if isinstance(event, RawResponseEvent)
    }
    for event in bridge.events:
        if isinstance(event, RawResponseEvent):
            original = original_raw[bridge.original_attempts[event.attempt]]
            assert event.body_base64 == original.body_base64
            assert event.original_sha256 == original.original_sha256
    journal = tmp_path / "main.jsonl"
    with select_artifact_writer(
        journal, create_run_manifest(configuration), secrets=()
    ) as writer:
        for event in bridge.events:
            writer.insert_event(event)
    calls: list[HttpRequest] = []
    progress: list[MainProgress] = []

    def select_recorded(request: HttpRequest) -> HttpResponse:
        calls.append(request)
        return create_response(request)

    _ = select_controlled_main(
        configuration, journal, settings, select_recorded, progress=progress.append
    )
    assert len(calls) == 124
    assert progress[-1].completed == dict.fromkeys(JudgeRole, 32)
    assert probe_journal.read_bytes() == before
