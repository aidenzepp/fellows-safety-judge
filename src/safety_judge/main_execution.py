"""Execute one controlled full matrix with incremental guards and durable billing."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http import HTTPStatus
from typing import Final, Literal
lazy from collections.abc import Callable
lazy from pathlib import Path

from pydantic import BaseModel, SecretStr

from safety_judge.analysis import create_pre_call_support_screen
from safety_judge.artifacts import (
    ArtifactEvent,
    ArtifactWriter,
    AttemptIntent,
    RawResponseEvent,
    ReplayState,
    SettlementEvent,
    TerminalEvent,
    create_artifact_digest,
    create_raw_body,
    select_artifact_writer,
)
from safety_judge.budget import (
    ArmCap,
    BudgetLedger,
    create_call_reservation,
    create_total_exposure,
)
from safety_judge.errors import InvalidValueError
from safety_judge.judging import (
    JudgeRole,
    NormalizedTerminalOutcomes,
    UnresolvedJudgment,
    create_normalized_terminal_outcomes,
)
from safety_judge.model_access import (
    HttpResponse,
    HttpTransport,
    create_model_route,
    create_provider_observation,
    select_model_attempt,
)
from safety_judge.runs import (
    ScheduledAttempt,
    create_assignment_request,
    create_execution_ready,
    create_mode_probe_step,
    create_resumable_attempts,
    insert_attempt_result,
    insert_resumed_terminals,
    insert_usage_settlement,
)
from safety_judge.study import RunAssignment, StudyConfiguration, create_run_manifest
lazy from safety_judge.settings import ApplicationSettings

CERTIFIED_RETRY_ORDINAL: Final = 2
"""The sole permitted retry ordinal after certified non-delivery."""

PROVIDER_ERROR_LIMIT: Final = 10
"""Ten consecutive errors on either account latch a global dispatch stop."""

type StopReason = Literal[
    "systemic_failure", "provider_errors", "projection_over_cap", "budget_cap"
]
"""The frozen operational stop reasons, never an outcome-based model change."""


class MainProgress(BaseModel, frozen=True, extra="forbid"):
    """Small sanitized progress checkpoint, containing no model/source text.

    Attributes:
        completed: Unique completed logical cells per judge.
        raw_valid: Strict raw valid counts on the same cells.
        normalized_valid: Frozen normalized valid counts on the same cells.
        attempts: Paid/possibly paid attempts including certified retry attempts.
        exposure: Actual plus retained unknown liability and protected reserves.
        projected_total: Conditional remaining maximum-output planning projection.
        steady: Whether the error-free initial-window ramp is active.
        stop_reason: Latched global stop or None while dispatch may continue.
    """

    completed: dict[JudgeRole, int]
    raw_valid: dict[JudgeRole, int]
    normalized_valid: dict[JudgeRole, int]
    attempts: int
    exposure: int | None
    projected_total: int | None
    steady: bool
    stop_reason: StopReason | None


type ProgressSink = Callable[[MainProgress], None]
"""Explicit ignored status-writer capability supplied by the admitted driver."""


class MainMonitor:
    """Incremental distinct-cell guard state; initialization replays history once."""

    def __init__(self, configuration: StudyConfiguration, state: ReplayState) -> None:
        """Initialize one monitor from its exact complete checkpoint.

        Args:
            configuration: Frozen all-four modes, rates and controlled policy.
            state: Existing matching journal, including reused canonical smoke.
        """
        super().__init__()
        self.configuration = configuration
        self.completed = dict.fromkeys(JudgeRole, 0)
        self.raw_valid = dict.fromkeys(JudgeRole, 0)
        self.normalized_valid = dict.fromkeys(JudgeRole, 0)
        self.input_totals = dict.fromkeys(JudgeRole, 0)
        self.usage_counts = dict.fromkeys(JudgeRole, 0)
        self.assigned = dict.fromkeys(JudgeRole, 0)
        self.reserved_cells: set[str] = set()
        self.outcomes: dict[str, tuple[JudgeRole, NormalizedTerminalOutcomes]] = {}
        self.provider_streaks = {"deepinfra": 0, "huggingface": 0}
        self.had_provider_error = False
        self.attempts = len(state.ledger.reservations)
        self.next_attempts = create_resumable_attempts(state)
        self.stop_reason: StopReason | None = None
        self._update_replayed_observations(state)

    def _update_replayed_observations(self, state: ReplayState) -> None:
        """Replay receipt metadata once without invoking any transport.

        Args:
            state: Matching intent/raw/terminal history from the exclusive writer.
        """
        assignments = {item.identifier: item for item in self.configuration.assignments}
        intents = {
            event.reservation.attempt: event.assignment
            for event in state.events
            if isinstance(event, AttemptIntent)
        }
        received: set[str] = set()
        for identifier in intents.values():
            self.update_intent(identifier, assignments[identifier].judge)
        for event in state.events:
            if isinstance(event, RawResponseEvent):
                assignment = assignments[intents[event.attempt]]
                received.add(assignment.identifier)
                result = (
                    HttpResponse(status=event.status, body=create_raw_body(event))
                    if event.status is not None and not event.redacted
                    else None
                )
                self.update_observation(
                    assignment.identifier,
                    assignment.judge,
                    result,
                    retry_pending=event.delivery == "not_delivered"
                    and event.attempt.endswith(":attempt:1"),
                )

        for identifier in set(intents.values()) - received:
            self.update_observation(
                identifier, assignments[identifier].judge, None, retry_pending=False
            )

    def update_intent(self, identifier: str, judge: JudgeRole) -> None:
        """Count a reserved cell once, so projection never recharges pending cells.

        Args:
            identifier: Stable main cell identity, independent of retry attempt.
            judge: Owning fixed nominal judge.
        """
        if identifier not in self.reserved_cells:
            self.reserved_cells.add(identifier)
            self.assigned[judge] += 1

    def update_observation(
        self,
        identifier: str,
        judge: JudgeRole,
        result: HttpResponse | None,
        *,
        retry_pending: bool,
    ) -> None:
        """Update one receipt without treating a certified retry as another cell.

        Args:
            identifier: Stable main cell, shared by every certified attempt.
            judge: Owning nominal judge, never inferred from response content.
            result: Persisted HTTP observation, absent for unknown/non-delivery.
            retry_pending: Whether certified intermediate non-delivery may retry.
        """
        provider = create_model_route(judge).provider
        failed = result is None or result.status != HTTPStatus.OK
        self.had_provider_error = self.had_provider_error or failed
        self.provider_streaks[provider] = (
            self.provider_streaks[provider] + 1 if failed else 0
        )
        if self.provider_streaks[provider] >= PROVIDER_ERROR_LIMIT:
            self.stop_reason = "provider_errors"
        if retry_pending:
            return
        unknown = UnresolvedJudgment(reason="unknown")
        outcome = NormalizedTerminalOutcomes(raw=unknown, normalized=unknown)
        if result is not None:
            observation = create_provider_observation(result)
            outcome = create_normalized_terminal_outcomes(
                observation.content,
                finish=observation.finish,
                judge_refused=observation.refused,
            )
            if (
                observation.usage is not None
                and observation.usage.prompt_tokens is not None
            ):
                self.input_totals[judge] += observation.usage.prompt_tokens
                self.usage_counts[judge] += 1
        old = self.outcomes.get(identifier)
        if old is not None:
            self.raw_valid[judge] -= int(old[1].raw.kind == "judgment")
            self.normalized_valid[judge] -= int(old[1].normalized.kind == "judgment")
        else:
            self.completed[judge] += 1
        self.outcomes[identifier] = (judge, outcome)
        self.raw_valid[judge] += int(outcome.raw.kind == "judgment")
        self.normalized_valid[judge] += int(outcome.normalized.kind == "judgment")
        policy = self.configuration.main_policy
        if (
            policy is not None
            and self.completed[judge] >= policy.initial_rows
            and (
                self.completed[judge] - self.normalized_valid[judge]
                > self.completed[judge] / 2
            )
        ):
            self.stop_reason = "systemic_failure"

    def create_steady_state(self) -> bool:
        """Determine the frozen error-free ramp from distinct completed cells.

        Returns:
            True only after every judge completes the initial window without error.
        """
        policy = self.configuration.main_policy
        return (
            policy is not None
            and not self.had_provider_error
            and min(self.completed.values()) >= policy.initial_rows
        )

    def create_progress(self, ledger: BudgetLedger) -> MainProgress:
        """Compute small current exposure and conditional remaining projection.

        Args:
            ledger: Compact current exposure from the incremental writer.

        Returns:
            Sanitized counts, preserved liabilities and a latched guard decision.
        """
        policy = self.configuration.main_policy
        exposure = create_total_exposure(ledger)
        projected = exposure
        if exposure is None:
            self.stop_reason = "budget_cap"
        if policy is not None and projected is not None:
            for judge in JudgeRole:
                inputs = max(
                    policy.projected_input_tokens[judge],
                    (self.input_totals[judge] + self.usage_counts[judge] - 1)
                    // self.usage_counts[judge]
                    if self.usage_counts[judge]
                    else 0,
                )
                remaining = len(self.configuration.responses) - self.assigned[judge]
                charge = create_call_reservation(
                    attempt="projection",
                    arm=judge.value,
                    price=self.configuration.prices[judge],
                    maximum_input_tokens=inputs,
                    maximum_output_tokens=self.configuration.parameters.maximum_output_tokens,
                ).maximum_cost
                amount = remaining * policy.projection_attempts * charge
                projected += amount
                current = sum(
                    item.maximum_cost
                    for item in ledger.reservations
                    if item.arm == judge.value
                )
                cap = next(
                    item.cap for item in ledger.plan.arms if item.arm == judge.value
                )
                if current + amount > cap:
                    self.stop_reason = "projection_over_cap"
            if projected > ledger.plan.global_cap:
                self.stop_reason = "projection_over_cap"
        return MainProgress(
            completed=self.completed,
            raw_valid=self.raw_valid,
            normalized_valid=self.normalized_valid,
            attempts=self.attempts,
            exposure=create_total_exposure(ledger),
            projected_total=projected,
            steady=self.create_steady_state(),
            stop_reason=self.stop_reason,
        )


@dataclass(frozen=True)
class MainCapabilities:
    """One long-lived owner session and explicitly injected network/status edges.

    Attributes:
        configuration: Exact full controlled freeze.
        settings: Parsed credentials, never serialized.
        transport: Single-attempt network capability.
        progress: Sanitized durable progress capability.
        secrets: All credentials supplied to raw redaction.
    """

    configuration: StudyConfiguration
    settings: ApplicationSettings
    transport: HttpTransport
    progress: ProgressSink
    secrets: tuple[SecretStr, ...]


def create_controlled_batch(
    remaining: list[ScheduledAttempt],
    capabilities: MainCapabilities,
    monitor: MainMonitor,
) -> list[ScheduledAttempt]:
    """Select a bounded global/HF/DI batch from the frozen operational ramp.

    Args:
        remaining: Already reserved and durably intended attempts.
        capabilities: Explicit controlled policy and edges.
        monitor: Incremental ramp/latched stop owner.

    Returns:
        Ordered subset within both account and global request ceilings.
    """
    policy = capabilities.configuration.main_policy
    if policy is None:
        return []
    steady = monitor.create_steady_state()
    limits = policy.steady_provider_limits if steady else policy.initial_provider_limits
    maximum = policy.steady_workers if steady else policy.initial_workers
    counts: dict[str, int] = {}
    batch: list[ScheduledAttempt] = []
    for entry in remaining:
        provider = entry[2].route.provider
        if len(batch) < maximum and counts.get(provider, 0) < limits[provider]:
            batch.append(entry)
            counts[provider] = counts.get(provider, 0) + 1
    return batch


def _create_main_scheduled_attempts(
    capabilities: MainCapabilities,
    row: tuple[RunAssignment, ...],
    next_attempts: dict[str, int],
) -> list[ScheduledAttempt]:
    """Prepare exact pending requests and conservative complete liabilities.

    Args:
        capabilities: Full source, frozen modes, rates and parsed settings.
        row: Complete four-judge row window, never a selected outcome subset.
        next_attempts: Occupied zero or next certified attempt ordinal per cell.

    Returns:
        Pending calls without dispatch or journal mutation.
    """
    configuration = capabilities.configuration
    responses = {item.identifier: item for item in configuration.responses}
    scheduled: list[ScheduledAttempt] = []
    for item in row:
        number = next_attempts.get(item.identifier, 1)
        if number:
            reservation = create_call_reservation(
                attempt=f"{item.identifier}:attempt:{number}",
                arm=item.judge.value,
                price=configuration.prices[item.judge],
                maximum_input_tokens=item.maximum_input_tokens or 0,
                maximum_output_tokens=configuration.parameters.maximum_output_tokens,
            )
            request = create_assignment_request(
                configuration,
                item,
                responses[item.response_identifier],
                capabilities.settings,
            )
            scheduled.append(((item, number), reservation, request))
    return scheduled


def _create_admitted_main_window(
    writer: ArtifactWriter,
    capabilities: MainCapabilities,
    row: tuple[RunAssignment, ...],
    monitor: MainMonitor,
) -> tuple[tuple[RunAssignment, ...], list[ScheduledAttempt]]:
    """Shrink a proposed window by complete rows before declaring a cap stop.

    Args:
        writer: Exclusive incremental owner retaining all existing liabilities.
        capabilities: Frozen requests and conservative full-context reservations.
        row: Complete candidate four-judge rows in the frozen source order.
        monitor: Current occupied/certified retry identities and stop state.

    Returns:
        Largest affordable complete prefix and its still-unpersisted requests.
    """
    candidate = row
    while candidate:
        scheduled = _create_main_scheduled_attempts(
            capabilities, candidate, monitor.next_attempts
        )
        try:
            _ = writer.create_admitted_reservations(
                tuple(item[1] for item in scheduled)
            )
        except InvalidValueError:
            candidate = candidate[: -len(JudgeRole)]
        else:
            return candidate, scheduled
    monitor.stop_reason = "budget_cap"
    return (), []


def _select_main_window(
    writer: ArtifactWriter,
    capabilities: MainCapabilities,
    monitor: MainMonitor,
    scheduled: list[ScheduledAttempt],
    executor: ThreadPoolExecutor,
) -> None:
    """Admit the entire window, dispatch bounded batches, and drain after a stop.

    Args:
        writer: Exclusive incremental durable journal owner.
        capabilities: Exact network/status authority and frozen policy.
        monitor: Incremental distinct-cell and provider stop owner.
        scheduled: Complete next row window or certified retry subset.
        executor: One long-lived bounded request executor.
    """
    try:
        _ = writer.create_admitted_reservations(tuple(item[1] for item in scheduled))
    except InvalidValueError:
        monitor.stop_reason = "budget_cap"
        return
    for (assignment, _), reservation, request in scheduled:
        writer.insert_event(
            AttemptIntent(
                assignment=assignment.identifier,
                reservation=reservation,
                request_sha256=create_artifact_digest(request.body),
            )
        )
        monitor.update_intent(assignment.identifier, assignment.judge)
    remaining = scheduled.copy()
    while remaining and monitor.stop_reason is None:
        batch = create_controlled_batch(remaining, capabilities, monitor)
        for entry in batch:
            remaining.remove(entry)
        futures = tuple(
            executor.submit(select_model_attempt, request, capabilities.transport)
            for _, _, request in batch
        )
        for ((assignment, number), reservation, _), future in zip(
            batch, futures, strict=True
        ):
            result = future.result()
            retry = result.delivery == "not_delivered" and number == 1
            monitor.next_attempts[assignment.identifier] = 2 if retry else 0
            insert_attempt_result(
                writer, reservation.attempt, result, capabilities.secrets
            )
            insert_usage_settlement(
                writer,
                capabilities.configuration,
                assignment,
                reservation.attempt,
                result,
            )
            monitor.attempts += 1
            monitor.update_observation(
                assignment.identifier,
                assignment.judge,
                result if isinstance(result, HttpResponse) else None,
                retry_pending=retry,
            )
        capabilities.progress(monitor.create_progress(writer.create_exposure()))


def select_controlled_main(
    configuration: StudyConfiguration,
    journal: Path,
    settings: ApplicationSettings,
    transport: HttpTransport,
    *,
    progress: ProgressSink,
) -> ReplayState:
    """Run the full assigned matrix under one writer until completion or hard stop.

    Args:
        configuration: Explicit full main freeze with all independent gates true.
        journal: New reconciled journal containing canonical current-mode smoke only.
        settings: Parsed credentials, never logged or serialized.
        transport: Explicit existing one-POST capability, never automatic fallback.
        progress: Durable sanitized checkpoints and owner-monitoring callback.

    Returns:
        Final complete or explicitly stopped full-manifest checkpoint.

    Raises:
        InvalidValueError: If the controlled policy or four frozen modes are absent.
    """
    if (
        configuration.execution_mode != "live"
        or not create_pre_call_support_screen(configuration.responses).passed
    ):
        message = (
            "Controlled main source or live mode differs; reconcile before dispatch."
        )
        raise InvalidValueError(message)
    create_execution_ready(configuration)
    policy = configuration.main_policy
    if policy is None or set(configuration.output_modes) != set(JudgeRole):
        message = (
            "Controlled main policy or all-four modes missing; restore the freeze."
        )
        raise InvalidValueError(message)
    capabilities = MainCapabilities(
        configuration,
        settings,
        transport,
        progress,
        tuple(
            secret
            for secret in (settings.deepinfra_api_key, settings.huggingface_api_key)
            if secret is not None
        ),
    )
    with select_artifact_writer(
        journal, create_run_manifest(configuration), secrets=capabilities.secrets
    ) as writer:
        insert_resumed_terminals(writer)
        state = writer.create_snapshot()
        monitor = MainMonitor(configuration, state)
        progress(monitor.create_progress(writer.create_exposure()))
        index = 0
        with ThreadPoolExecutor(max_workers=policy.steady_workers) as executor:
            while (
                index < len(configuration.assignments) and monitor.stop_reason is None
            ):
                rows = (
                    policy.steady_workers
                    if monitor.create_steady_state()
                    else policy.initial_provider_limits["huggingface"]
                )
                proposed = configuration.assignments[index : index + 4 * rows]
                row, scheduled = _create_admitted_main_window(
                    writer, capabilities, proposed, monitor
                )
                index += len(row)
                for retry_pass in range(2):
                    if monitor.stop_reason is not None:
                        break
                    if retry_pass:
                        scheduled = _create_main_scheduled_attempts(
                            capabilities, row, monitor.next_attempts
                        )
                    if not scheduled:
                        break
                    _select_main_window(
                        writer,
                        capabilities,
                        monitor,
                        scheduled,
                        executor,
                    )
        progress(monitor.create_progress(writer.create_exposure()))
        return writer.create_snapshot()


class ModeReconciliation(BaseModel, frozen=True, extra="forbid"):
    """Explicit bridge from capability namespaces into canonical main cells.

    Attributes:
        events: Selected current-mode event copies with main cell identities.
        original_attempts: Main-to-original mapping preserving source provenance.
        diagnostic_exposure: All unselected probe charges or unknown liabilities.
    """

    events: tuple[ArtifactEvent, ...]
    original_attempts: dict[str, str]
    diagnostic_exposure: tuple[ArmCap, ...]


def create_mode_reconciliation(
    configuration: StudyConfiguration, probe: ReplayState
) -> ModeReconciliation:
    """Reuse final chronological current-mode responses without selecting validity.

    Args:
        configuration: Full main source, selected modes and exact schema freeze.
        probe: Separate integrity-checked finite mode-probe journal.

    Returns:
        Provenance-preserving canonical event copies and all remaining liabilities.

    Raises:
        InvalidValueError: If source/routes/modes differ or a request hash changes.
    """
    if (
        probe.manifest.source_sha256 != configuration.source.source_sha256
        or probe.manifest.model_routes != configuration.routes
    ):
        message = "Mode-probe source/routes differ; reconcile without new dispatch."
        raise InvalidValueError(message)
    selected: dict[str, str] = {}
    responses = {row.identifier: row for row in configuration.responses}
    for assignment in configuration.assignments[: len(JudgeRole)]:
        mode = create_mode_probe_step(probe, assignment).mode
        intents = tuple(
            event
            for event in probe.events
            if isinstance(event, AttemptIntent)
            and event.assignment == f"{assignment.identifier}:mode:{mode}"
        )
        if not intents or mode != configuration.output_modes[assignment.judge]:
            message = (
                "Current mode has no canonical probe response; reconcile capability."
            )
            raise InvalidValueError(message)
        intent = intents[-1]
        request = create_assignment_request(
            configuration, assignment, responses[assignment.response_identifier], None
        )
        if intent.request_sha256 != create_artifact_digest(request.body):
            message = "Canonical request hash differs; preserve probe and stop."
            raise InvalidValueError(message)
        selected[intent.reservation.attempt] = assignment.identifier
    events: list[ArtifactEvent] = []
    for event in probe.events:
        attempt = create_event_attempt(event)
        if attempt not in selected:
            continue
        identifier = selected[attempt]
        replacement = f"{identifier}:attempt:1"
        events.append(create_reconciled_event(event, identifier, replacement))
    actual = {item.attempt: item.actual_cost for item in probe.ledger.settlements}
    diagnostics = tuple(
        ArmCap(
            arm=role.value,
            cap=sum(
                actual.get(item.attempt, item.maximum_cost)
                for item in probe.ledger.reservations
                if item.arm == role.value and item.attempt not in selected
            ),
        )
        for role in JudgeRole
    )
    return ModeReconciliation(
        events=tuple(events),
        original_attempts={
            f"{identifier}:attempt:1": attempt
            for attempt, identifier in selected.items()
        },
        diagnostic_exposure=diagnostics,
    )


def create_event_attempt(event: ArtifactEvent) -> str:
    """Read the owning attempt identity without changing the event.

    Args:
        event: One immutable manifest/intent/raw/terminal/settlement event.

    Returns:
        Its attempt identity, or empty for the unique manifest.
    """
    if isinstance(event, AttemptIntent):
        return event.reservation.attempt
    if isinstance(event, SettlementEvent):
        return event.settlement.attempt
    return event.attempt if isinstance(event, (RawResponseEvent, TerminalEvent)) else ""


def create_reconciled_event(
    event: ArtifactEvent, assignment: str, attempt: str
) -> ArtifactEvent:
    """Copy canonical event identities while preserving raw bytes/hash/cost facts.

    Args:
        event: Selected event from the immutable capability-probe journal.
        assignment: Main original/judge identity, never a replacement case.
        attempt: Explicit new-main attempt identity in the recorded provenance map.

    Returns:
        An event with the same evidence and the explicitly reconciled identity.
    """
    if isinstance(event, AttemptIntent):
        return event.model_copy(
            update={
                "assignment": assignment,
                "reservation": event.reservation.model_copy(
                    update={"attempt": attempt}
                ),
            }
        )
    if isinstance(event, SettlementEvent):
        return event.model_copy(
            update={
                "settlement": event.settlement.model_copy(update={"attempt": attempt})
            }
        )
    return event.model_copy(update={"attempt": attempt})
