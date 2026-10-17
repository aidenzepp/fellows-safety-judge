"""Sequence bounded network attempts through one exclusively locked durable writer.

Only the injected transport can perform network I/O. No default transport or CLI
command enables paid execution. Every four-judge row is admitted before any call;
intents and raw evidence are durable before dispatch and parsing respectively.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Final
lazy from pathlib import Path

from pydantic import BaseModel, Field, SecretStr

from safety_judge.analysis import SavedJudgment, create_pre_call_support_screen
from safety_judge.artifacts import (
    ArtifactDigest,
    ArtifactWriter,
    AttemptIntent,
    RawResponseEvent,
    ReplayState,
    SettlementEvent,
    TerminalEvent,
    create_artifact_digest,
    create_raw_body,
    create_raw_response_event,
    select_artifact_writer,
)
from safety_judge.budget import (
    ArmCap,
    CallReservation,
    CallSettlement,
    create_call_reservation,
)
from safety_judge.errors import InvalidValueError
from safety_judge.judging import (
    NormalizedTerminalOutcomes,
    UnresolvedJudgment,
    create_judge_request,
    create_normalized_terminal_outcomes,
    create_terminal_outcome,
)
from safety_judge.model_access import (
    HttpRequest,
    HttpResponse,
    HttpResult,
    HttpTransport,
    create_judge_http_request,
    create_provider_api_key,
    create_provider_observation,
    select_model_attempt,
)
from safety_judge.study import (
    RunAssignment,
    StudyConfiguration,
    create_configuration_digest,
    create_run_manifest,
)
lazy from safety_judge.coin_flip import EligibleResponse
lazy from safety_judge.settings import ApplicationSettings

SMOKE_ARM_CAPS: Final = (
    ("G1", 10_000),
    ("G27", 40_000),
    ("L8", 20_000),
    ("Q32", 30_000),
)
"""Fixed microdollar smoke subcaps, contained within the unchanged main arms."""

SMOKE_CONTEXT_INPUTS: Final = (
    ("G1", 32_768),
    ("G27", 131_072),
    ("L8", 131_072),
    ("Q32", 40_960),
)
"""Full advertised input contexts reserved before each bounded probe attempt."""

SMOKE_TOTAL_CAP: Final = 100_000
"""The absolute ten-cent bound on all smoke attempt liabilities."""

SMOKE_MAXIMUM_ATTEMPTS: Final = 2
"""One initial attempt and one certified non-delivery retry per assignment."""

SMOKE_OUTPUT_TOKENS: Final = 2048
"""Frozen output reservation for the operator-approved probe."""

SMOKE_TIMEOUT_SECONDS: Final = 120
"""Frozen per-request timeout for the operator-approved probe."""


class SmokeAuthorization(BaseModel, frozen=True, extra="forbid"):
    """Explicit first-row probe authority, distinct from permission for the main run.

    Attributes:
        confirmed: Whether the exact bounded execution was explicitly admitted.
        reference: Durable operator/internal admission evidence reference.
        configuration_sha256: Full source/matrix/configuration freeze being probed.
        assignment_identifiers: Exactly the first original and four roster judges.
        prior_arm_exposure: Previous smoke actual costs or retained liabilities.
    """

    confirmed: Annotated[bool, Field(strict=True)]
    reference: Annotated[str, Field(min_length=1)]
    configuration_sha256: ArtifactDigest
    assignment_identifiers: tuple[str, ...]
    prior_arm_exposure: tuple[ArmCap, ...] = ()


MAXIMUM_CONSECUTIVE_TRANSPORT_FAILURES: Final = 10
"""The frozen stop threshold; a completed in-flight batch cannot unlatch it."""

type ScheduledAttempt = tuple[tuple[RunAssignment, int], CallReservation, HttpRequest]
"""An admitted assignment/ordinal, reservation and exact credential-excluded request."""


def create_saved_judgments(
    configuration: StudyConfiguration, state: ReplayState
) -> tuple[SavedJudgment, ...]:
    """Reconstruct the full assigned matrix without replaying network calls.

    Missing or interrupted cells remain unresolved; a later certified retry owns
    the final value. Shared variable identities do not depend on retry count.

    Args:
        configuration: Exact frozen all-four assignment matrix.
        state: Integrity-checked journal under the identical manifest.

    Returns:
        One explicit outcome per assignment, including never-dispatched cells.

    Raises:
        InvalidValueError: If configuration differs or a journal assignment is foreign.
    """
    if state.manifest != create_run_manifest(configuration):
        message = "Run configuration changed; reconcile before reading judgments."
        raise InvalidValueError(message)
    assignments = {item.identifier: item for item in configuration.assignments}
    attempts: dict[str, str] = {}
    outcomes = {
        item.identifier: UnresolvedJudgment(reason="unknown")
        for item in configuration.assignments
    }
    resolved: dict[str, TerminalEvent] = {}
    for event in state.events:
        if isinstance(event, AttemptIntent):
            if event.assignment not in assignments:
                message = "Journal contains a foreign assignment; reconcile the run."
                raise InvalidValueError(message)
            attempts[event.reservation.attempt] = event.assignment
        elif isinstance(event, TerminalEvent):
            resolved[attempts[event.attempt]] = event
    return tuple(
        SavedJudgment(
            response_identifier=item.response_identifier,
            judge=item.judge,
            variable_identifier=item.identifier,
            outcome=resolved[item.identifier].outcome
            if item.identifier in resolved
            else outcomes[item.identifier],
        )
        for item in configuration.assignments
    )


def create_execution_ready(configuration: StudyConfiguration) -> None:
    """Require all independent gates before even constructing network requests.

    Args:
        configuration: Frozen source, budget, token and authority evidence.

    Raises:
        InvalidValueError: If any prerequisite or complete input bound is absent.
    """
    if (
        not all(configuration.gates.model_dump().values())
        or not configuration.budget.confirmed
        or any(item.maximum_input_tokens is None for item in configuration.assignments)
        or any(not price.confirmed for price in configuration.prices.values())
    ):
        message = (
            "Execution gates are closed; confirm source, tokens, rates, "
            "funding and runtime."
        )
        raise InvalidValueError(message)


def _create_assignment_request(
    configuration: StudyConfiguration,
    assignment: RunAssignment,
    response: EligibleResponse,
    settings: ApplicationSettings | None,
) -> HttpRequest:
    """Render one blinded request from the frozen source and route owners.

    Args:
        configuration: Immutable inputs and generation controls.
        assignment: Selected fixed original/judge cell.
        response: Already indexed accepted source record for this assignment.
        settings: Explicit parsed credentials, excluded from artifacts.

    Returns:
        One wire request, granting no dispatch authority itself.
    """
    route = next(
        route for route in configuration.routes if route.role == assignment.judge
    )
    return create_judge_http_request(
        request=create_judge_request(
            response.prompt, response.generation, configuration.rubric
        ),
        route=route,
        api_key=create_provider_api_key(settings, route)
        if settings is not None
        else SecretStr("synthetic-offline-no-network"),
        parameters=configuration.parameters,
    )


def _insert_attempt_result(
    writer: ArtifactWriter,
    attempt: str,
    result: HttpResult,
    secrets: tuple[SecretStr, ...],
) -> None:
    """Persist raw observation before parsing; retain missing billing in full.

    Args:
        writer: Exclusive session, poisoned on persistence failure.
        attempt: Durable intent identity whose response has arrived.
        result: One transport observation, never an automatic resend instruction.
        secrets: Credentials to redact from raw evidence.
    """
    writer.insert_event(
        create_raw_response_event(
            attempt=attempt,
            status=result.status if isinstance(result, HttpResponse) else None,
            body=result.body if isinstance(result, HttpResponse) else b"",
            delivery=result.delivery,
            secrets=secrets,
        )
    )
    if isinstance(result, HttpResponse):
        observation = create_provider_observation(result)
        outcome = create_terminal_outcome(
            observation.content,
            finish=observation.finish,
            judge_refused=observation.refused,
        )
    else:
        outcome = UnresolvedJudgment(reason="unknown")
    writer.insert_event(TerminalEvent(attempt=attempt, outcome=outcome))


def _insert_usage_settlement(
    writer: ArtifactWriter,
    configuration: StudyConfiguration,
    assignment: RunAssignment,
    attempt: str,
    result: HttpResult,
) -> None:
    """Settle only complete response usage under the exact frozen billing rates.

    Args:
        writer: Single durable journal owner.
        configuration: Confirmed price and conservative token bounds.
        assignment: Original cell owning the charge.
        attempt: Attempt being reconciled, including retries.
        result: Already persisted raw observation.

    Raises:
        InvalidValueError: If observed usage exceeds its frozen bound.
    """
    if not isinstance(result, HttpResponse):
        return
    observation = create_provider_observation(result)
    usage = observation.usage
    if usage is None or usage.prompt_tokens is None or usage.completion_tokens is None:
        return
    if (
        usage.reasoning_tokens is not None
        and usage.reasoning_tokens > usage.completion_tokens
    ):
        return
    if (
        assignment.maximum_input_tokens is None
        or usage.prompt_tokens > assignment.maximum_input_tokens
        or usage.completion_tokens > configuration.parameters.maximum_output_tokens
    ):
        message = (
            "Observed usage exceeds the frozen bound; pause and reconcile "
            "rates and billing."
        )
        raise InvalidValueError(message)
    price = configuration.prices[assignment.judge]
    actual = create_call_reservation(
        attempt=attempt,
        arm=assignment.judge.value,
        price=price,
        maximum_input_tokens=usage.prompt_tokens,
        maximum_output_tokens=usage.completion_tokens,
    )
    writer.insert_event(
        SettlementEvent(
            settlement=CallSettlement(
                attempt=attempt,
                actual_cost=actual.maximum_cost,
                evidence=f"usage:{create_artifact_digest(result.body)}",
            )
        )
    )


def _create_resumable_attempts(state: ReplayState) -> dict[str, int]:
    """Index certified retry eligibility once, retaining all crash-window intents.

    Args:
        state: Complete replay checkpoint from the exclusive writer.

    Returns:
        Existing assignments mapped to retry two or occupied zero.
    """
    assignments: dict[str, list[str]] = {}
    raw = {
        event.attempt: event
        for event in state.events
        if isinstance(event, RawResponseEvent)
    }
    terminal = {
        event.attempt for event in state.events if isinstance(event, TerminalEvent)
    }
    for event in state.events:
        if isinstance(event, AttemptIntent):
            assignments.setdefault(event.assignment, []).append(
                event.reservation.attempt
            )
    return {
        assignment: 2
        if len(attempts) == 1
        and attempts[0] in terminal
        and attempts[0] in raw
        and raw[attempts[0]].delivery == "not_delivered"
        else 0
        for assignment, attempts in assignments.items()
    }


def create_transport_failure_state(state: ReplayState) -> tuple[int, bool]:
    """Replay the durable transport-failure streak independently of judge validity.

    Args:
        state: Complete raw observations ordered by durable receipt.

    Returns:
        Current streak and latched ten-failure stop, including drained responses.
    """
    failures = 0
    stopped = False
    for event in state.events:
        if isinstance(event, RawResponseEvent):
            failures = failures + 1 if event.status is None else 0
            stopped = stopped or failures >= MAXIMUM_CONSECUTIVE_TRANSPORT_FAILURES
    return failures, stopped


def _insert_resumed_terminals(writer: ArtifactWriter) -> None:
    """Resolve saved raw evidence locally and preserve interrupted intents occupied.

    Args:
        writer: Exclusive complete journal session under the expected manifest.
    """
    state = writer.create_snapshot()
    terminal_attempts = {
        event.attempt for event in state.events if isinstance(event, TerminalEvent)
    }
    for event in state.events:
        if (
            isinstance(event, RawResponseEvent)
            and event.attempt not in terminal_attempts
        ):
            if event.status is not None and not event.redacted:
                observation = create_provider_observation(
                    HttpResponse(status=event.status, body=create_raw_body(event))
                )
                outcome = create_terminal_outcome(
                    observation.content,
                    finish=observation.finish,
                    judge_refused=observation.refused,
                )
            else:
                outcome = UnresolvedJudgment(reason="unknown")
            writer.insert_event(TerminalEvent(attempt=event.attempt, outcome=outcome))


def create_provider_batch(
    remaining: list[ScheduledAttempt], configuration: StudyConfiguration
) -> list[ScheduledAttempt]:
    """Select a bounded request batch without exceeding either account limit.

    Args:
        remaining: Already admitted and durably intended attempts awaiting dispatch.
        configuration: Explicit global and per-provider concurrency ceilings.

    Returns:
        Ordered selected attempts; this function performs no dispatch or mutation.
    """
    counts: dict[str, int] = {}
    batch: list[ScheduledAttempt] = []
    for entry in remaining:
        provider = entry[2].route.provider
        if (
            len(batch) < configuration.maximum_workers
            and counts.get(provider, 0) < configuration.maximum_per_provider
        ):
            batch.append(entry)
            counts[provider] = counts.get(provider, 0) + 1
    return batch


def create_saved_normalized_outcomes(
    state: ReplayState,
) -> dict[str, NormalizedTerminalOutcomes]:
    """Replay paired outcomes without changing raw journals or stored terminals.

    Args:
        state: Integrity-checked durable intents and credential-redacted raw data.

    Returns:
        Each intended attempt's raw and normalized outcomes; absent raw is unknown.
    """
    unknown = NormalizedTerminalOutcomes(
        raw=UnresolvedJudgment(reason="unknown"),
        normalized=UnresolvedJudgment(reason="unknown"),
    )
    outcomes: dict[str, NormalizedTerminalOutcomes] = {}
    for event in state.events:
        if isinstance(event, AttemptIntent):
            outcomes[event.reservation.attempt] = unknown
        elif (
            isinstance(event, RawResponseEvent)
            and event.status is not None
            and not event.redacted
        ):
            observation = create_provider_observation(
                HttpResponse(status=event.status, body=create_raw_body(event))
            )
            outcomes[event.attempt] = create_normalized_terminal_outcomes(
                observation.content,
                finish=observation.finish,
                judge_refused=observation.refused,
            )
    return outcomes


def create_smoke_admission(
    state: ReplayState,
    reservations: tuple[CallReservation, ...],
    scope: SmokeAuthorization,
) -> None:
    """Enforce smoke subcaps and attempt limits against all previous liabilities.

    Args:
        state: Durable full-manifest checkpoint with prior attempts and settlements.
        reservations: Complete next four-judge batch or certified retry subset.
        scope: Frozen first-row authorization and assignment allowlist.

    Raises:
        InvalidValueError: If a request escapes the four IDs, two-attempt limits,
            fixed arm subcaps, or absolute ten-cent smoke bound.
    """
    previous = {item.attempt: item.actual_cost for item in state.ledger.settlements}
    totals = {item.arm: item.cap for item in scope.prior_arm_exposure}
    if len(totals) != len(scope.prior_arm_exposure):
        message = "Prior smoke exposure repeats an arm; reconcile before dispatch."
        raise InvalidValueError(message)
    attempts: dict[str, int] = {}
    for item in (*state.ledger.reservations, *reservations):
        assignment = item.attempt.rsplit(":attempt:", 1)[0]
        if assignment not in scope.assignment_identifiers:
            message = (
                "Smoke journal contains another assignment; reconcile without dispatch."
            )
            raise InvalidValueError(message)
        attempts[assignment] = attempts.get(assignment, 0) + 1
        totals[item.arm] = totals.get(item.arm, 0) + previous.get(
            item.attempt, item.maximum_cost
        )
    caps = dict(SMOKE_ARM_CAPS)
    if (
        any(count > SMOKE_MAXIMUM_ATTEMPTS for count in attempts.values())
        or any(arm not in caps or amount > caps[arm] for arm, amount in totals.items())
        or sum(totals.values()) > SMOKE_TOTAL_CAP
    ):
        message = "Smoke attempts or monetary subcap exceeded; stop and reconcile."
        raise InvalidValueError(message)


def create_smoke_ready(
    configuration: StudyConfiguration,
    scope: SmokeAuthorization,
) -> None:
    """Validate probe-only authority without claiming full main-runtime clearance.

    Args:
        configuration: Full accepted source, support, and unshrunk assignment matrix.
        scope: Explicit admitted first-original/four-judge probe freeze.

    Raises:
        InvalidValueError: If source, funding, rates, controls or scope differ.
    """
    assignments = configuration.assignments[: len(SMOKE_ARM_CAPS)]
    controls = configuration.parameters
    if not (
        scope.confirmed
        and scope.configuration_sha256 == create_configuration_digest(configuration)
        and scope.assignment_identifiers
        == tuple(item.identifier for item in assignments)
        and configuration.execution_mode == "live"
        and not configuration.gates.execution_confirmed
        and configuration.gates.source_confirmed
        and configuration.gates.rates_confirmed
        and configuration.gates.funding_confirmed
        and configuration.budget.confirmed
        and all(price.confirmed for price in configuration.prices.values())
        and create_pre_call_support_screen(configuration.responses).passed
        and controls.maximum_output_tokens == SMOKE_OUTPUT_TOKENS
        and controls.temperature == 0
        and controls.timeout_seconds == SMOKE_TIMEOUT_SECONDS
        and configuration.maximum_workers == 1
        and configuration.maximum_per_provider == 1
        and tuple((item.judge.value, item.maximum_input_tokens) for item in assignments)
        == SMOKE_CONTEXT_INPUTS
    ):
        message = "Smoke authority or controls differ; reconcile before dispatch."
        raise InvalidValueError(message)


def select_first_row_smoke(
    configuration: StudyConfiguration,
    journal: Path,
    settings: ApplicationSettings,
    transport: HttpTransport,
    scope: SmokeAuthorization,
) -> ReplayState:
    """Dispatch only the first original's four fixed judges, retaining full evidence.

    Main execution stays unauthorized. Reuse of these paid original outcomes in a
    later main freeze requires explicit configuration/liability reconciliation.
    No HTTP refusal, billing error, timeout or uncertain delivery is retried.

    Args:
        configuration: Complete frozen source and matrix with main execution closed.
        journal: Explicit durable journal, reusable without repeating occupied cells.
        settings: Parsed credentials, never logged or serialized.
        transport: Explicit existing single-attempt transport or deterministic fake.
        scope: Exactly admitted first-row identities and configuration digest.

    Returns:
        Full manifest after at most two certified attempts per first-row cell.

    Admission failures propagate as InvalidValueError before any model call.
    """
    create_smoke_ready(configuration, scope)
    return _select_run(configuration, journal, settings, transport, scope)


def _create_dispatch_admission(
    writer: ArtifactWriter,
    reservations: tuple[CallReservation, ...],
    scope: SmokeAuthorization | None,
) -> None:
    """Check optional probe limits and the unchanged global ledger before dispatch.

    Args:
        writer: Exclusive journal owner with all existing liabilities.
        reservations: Complete next batch, or empty for checkpoint validation.
        scope: Explicit bounded probe authorization, absent for a complete run.

    Admission failures propagate before any transport receives the batch.
    """
    if scope is not None:
        create_smoke_admission(writer.create_snapshot(), reservations, scope)
    _ = writer.create_admitted_reservations(reservations)


def _select_run(
    configuration: StudyConfiguration,
    journal: Path,
    settings: ApplicationSettings | None,
    transport: HttpTransport,
    scope: SmokeAuthorization | None = None,
) -> ReplayState:
    """Execute an admitted matrix or its bounded probe through an injected edge.

    The writer lock spans this run. Main-thread persistence owns all mutations;
    workers hold only already-reserved requests. Each account has a bounded batch
    within a row, and no row is partially admitted for affordability. A crash after
    any intent leaves that cell occupied; only certified non-delivery can retry.
    All called transports, including synthetic ones, require explicit gates.

    Args:
        configuration: Complete immutable study with every execution gate confirmed.
        journal: Explicit append-only destination; existing manifests must match.
        settings: Parsed credentials; never serialized into the frozen snapshot.
        transport: Required one-attempt capability; there is no live default.
        scope: First-row probe authority; absent only for an admitted complete run.

    Returns:
        Final snapshot retaining every outstanding monetary liability.
    """
    assignments = (
        configuration.assignments
        if scope is None
        else configuration.assignments[: len(SMOKE_ARM_CAPS)]
    )
    secrets = tuple(
        secret
        for secret in (
            (settings.deepinfra_api_key, settings.huggingface_api_key)
            if settings
            else ()
        )
        if secret is not None
    )
    with select_artifact_writer(
        journal, create_run_manifest(configuration), secrets=secrets
    ) as writer:
        _insert_resumed_terminals(writer)
        initial_state = writer.create_snapshot()
        _create_dispatch_admission(writer, (), scope)
        next_attempts = _create_resumable_attempts(initial_state)
        failures, stopped = create_transport_failure_state(initial_state)
        responses = {row.identifier: row for row in configuration.responses}
        with ThreadPoolExecutor(max_workers=configuration.maximum_workers) as executor:
            for index in range(0, len(assignments), 4 * configuration.maximum_workers):
                if stopped:
                    break
                row = assignments[index : index + 4 * configuration.maximum_workers]
                for _retry_pass in range(2):
                    if stopped:
                        break
                    pending = tuple(
                        (item, number)
                        for item in row
                        if (number := next_attempts.get(item.identifier, 1)) != 0
                    )
                    if not pending:
                        break
                    requests = tuple(
                        _create_assignment_request(
                            configuration,
                            item,
                            responses[item.response_identifier],
                            settings,
                        )
                        for item, _ in pending
                    )
                    reservations = tuple(
                        create_call_reservation(
                            attempt=f"{item.identifier}:attempt:{number}",
                            arm=item.judge.value,
                            price=configuration.prices[item.judge],
                            maximum_input_tokens=item.maximum_input_tokens
                            if item.maximum_input_tokens is not None
                            else 0,
                            maximum_output_tokens=configuration.parameters.maximum_output_tokens,
                        )
                        for item, number in pending
                    )
                    _create_dispatch_admission(writer, reservations, scope)
                    for (item, _), reservation, request in zip(
                        pending, reservations, requests, strict=True
                    ):
                        writer.insert_event(
                            AttemptIntent(
                                assignment=item.identifier,
                                reservation=reservation,
                                request_sha256=create_artifact_digest(request.body),
                            )
                        )
                    remaining = list(zip(pending, reservations, requests, strict=True))
                    while remaining and not stopped:
                        batch = create_provider_batch(remaining, configuration)
                        for entry in batch:
                            remaining.remove(entry)
                        futures = tuple(
                            executor.submit(select_model_attempt, request, transport)
                            for _, _, request in batch
                        )
                        for ((item, _), reservation, _), future in zip(
                            batch, futures, strict=True
                        ):
                            result = future.result()
                            failures = (
                                failures + 1
                                if not isinstance(result, HttpResponse)
                                else 0
                            )
                            stopped = (
                                stopped
                                or failures >= MAXIMUM_CONSECUTIVE_TRANSPORT_FAILURES
                            )
                            next_attempts[item.identifier] = (
                                2
                                if result.delivery == "not_delivered"
                                and next_attempts.get(item.identifier, 1) == 1
                                else 0
                            )
                            _insert_attempt_result(
                                writer, reservation.attempt, result, secrets
                            )
                            _insert_usage_settlement(
                                writer, configuration, item, reservation.attempt, result
                            )
        return writer.create_snapshot()


def select_run(
    configuration: StudyConfiguration,
    journal: Path,
    settings: ApplicationSettings,
    transport: HttpTransport,
) -> ReplayState:
    """Dispatch explicit live requests only after all independent operator gates.

    Args:
        configuration: Frozen live study and complete authority evidence.
        journal: Exclusive durable destination.
        settings: Explicit parsed credentials.
        transport: Required one-attempt capability; never selected implicitly.

    Returns:
        Complete saved state under the exact requested manifest.

    Raises:
        InvalidValueError: If simulation mode or source support fails live admission.
    """
    if configuration.execution_mode != "live":
        message = "Simulation cannot select a live edge; use the mock workflow."
        raise InvalidValueError(message)
    if not create_pre_call_support_screen(configuration.responses).passed:
        message = (
            "Pre-call support screen failed; reconcile source support before execution."
        )
        raise InvalidValueError(message)
    create_execution_ready(configuration)
    return _select_run(configuration, journal, settings, transport)


def _create_simulated_response(request: HttpRequest) -> HttpResponse:
    """Return a synthetic ordinal without accessing any network or credentials.

    Args:
        request: Synthetic presentation whose persisted intent already exists.

    Returns:
        Clearly synthetic response bytes; usage is deliberately absent.
    """
    return HttpResponse(
        status=200,
        body=json.dumps(
            {
                "id": "synthetic:" + create_artifact_digest(request.body),
                "choices": [
                    {"message": {"content": '{"ordinal":3}'}, "finish_reason": "stop"}
                ],
            }
        ).encode(),
    )


def select_simulated_run(
    configuration: StudyConfiguration, journal: Path
) -> ReplayState:
    """Exercise durable all-four mechanics through a fixed in-memory fake edge.

    No settings are constructed and no credential or network capability is read.
    Request bytes use the same owning renderer as live provider requests.

    Args:
        configuration: Separately frozen synthetic-only scenario configuration.
        journal: New or exactly matching synthetic evidence journal.

    Returns:
        Synthetic saved state with outstanding simulated liabilities retained.

    Raises:
        InvalidValueError: If real-study provenance or live mode is supplied.
    """
    if (
        configuration.execution_mode != "simulated"
        or configuration.evidence_kind != "synthetic"
    ):
        message = (
            "Mock run requires a synthetic simulation freeze; prepare it explicitly."
        )
        raise InvalidValueError(message)
    return _select_run(configuration, journal, None, _create_simulated_response)
