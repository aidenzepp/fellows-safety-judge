"""Single-writer append-only evidence, with hash-chain replay and durable ordering.

Use select_artifact_writer for a run: it validates history once and holds the
exclusive lock across bounded incremental appends. One-off insert_artifact_event
is intended for bounded fixtures and tools, not a per-attempt runner loop.

The journal never records HTTP request headers or credentials. Callers supply all
configured secrets for rejection/redaction. Corrupt or partial tails stop replay;
there is no repair, resend or inferred delivery. A process lock serializes writers.
"""

import base64
import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from typing import Annotated, Literal
lazy from collections.abc import Generator
lazy from pathlib import Path
lazy from typing import BinaryIO

from pydantic import BaseModel, Field, SecretStr

from safety_judge.budget import (
    BudgetLedger,
    BudgetPlan,
    CallReservation,
    CallSettlement,
    create_reserved_ledger,
    create_settled_ledger,
)
from safety_judge.errors import InvalidValueError
from safety_judge.judging import TerminalOutcome, create_unique_json_object
from safety_judge.model_access import ModelRoute

type ArtifactDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
"""A SHA-256 digest in lowercase hexadecimal form."""

type ArtifactIdentifier = Annotated[str, Field(min_length=1)]
"""A durable run, assignment or attempt identity supplied by its owner."""


class RunManifest(BaseModel, frozen=True, extra="forbid"):
    """Frozen identities for exact replay without persisting secret configuration.

    Attributes:
        run: Unique run identity.
        configuration_sha256: Hash of all non-secret frozen runtime configuration.
        source_sha256: Hash of the pinned accepted source/eligibility artifact.
        assignments_sha256: Hash of the complete frozen assignment manifest.
        budget_plan: Exact monetary allocation and authority configuration.
        model_routes: Advertised served IDs/provider/date/precision, not runtime proof.
    """

    run: ArtifactIdentifier
    configuration_sha256: ArtifactDigest
    source_sha256: ArtifactDigest
    assignments_sha256: ArtifactDigest
    budget_plan: BudgetPlan
    model_routes: tuple[ModelRoute, ...]


class ManifestEvent(BaseModel, frozen=True, extra="forbid"):
    """First and only manifest record anchoring the journal.

    Attributes:
        kind: Stable event discriminator.
        manifest: Exact run identity and configuration.
    """

    kind: Literal["manifest"] = "manifest"
    manifest: RunManifest


class AttemptIntent(BaseModel, frozen=True, extra="forbid"):
    """Worst-case reservation and dispatch intent, persisted before any network.

    Attributes:
        kind: Stable event discriminator.
        assignment: Logical case/judge assignment; retries retain this identity.
        reservation: Distinct transport-attempt identity and full monetary bound.
        request_sha256: Hash of exact rendered request/configuration bytes.
    """

    kind: Literal["intent"] = "intent"
    assignment: ArtifactIdentifier
    reservation: CallReservation
    request_sha256: ArtifactDigest


class RawResponseEvent(BaseModel, frozen=True, extra="forbid"):
    """Unparsed response evidence, persisted before any outcome parsing.

    Attributes:
        kind: Stable event discriminator.
        attempt: Previously reserved attempt identity.
        status: HTTP status, or None for a transport failure.
        body_base64: Exact response bytes except explicit secret redactions.
        original_sha256: Hash of original bytes before redaction.
        redacted: Whether configured secret bytes were replaced.
        delivery: Observed delivery; uncertainty never permits automatic resend.
    """

    kind: Literal["raw"] = "raw"
    attempt: ArtifactIdentifier
    status: Annotated[int, Field(ge=100, le=599)] | None
    body_base64: str
    original_sha256: ArtifactDigest
    redacted: bool
    delivery: Literal["response", "unknown", "not_delivered"]


class TerminalEvent(BaseModel, frozen=True, extra="forbid"):
    """Parsed terminal evidence; requires a previously durable raw observation.

    Attributes:
        kind: Stable event discriminator.
        attempt: Previously reserved attempt identity.
        outcome: Owning judging module's explicit terminal result.
    """

    kind: Literal["terminal"] = "terminal"
    attempt: ArtifactIdentifier
    outcome: TerminalOutcome


class SettlementEvent(BaseModel, frozen=True, extra="forbid"):
    """Verified billing reconciliation, independent of parse success.

    Attributes:
        kind: Stable event discriminator.
        settlement: Verified final bill with durable external evidence identity.
    """

    kind: Literal["settlement"] = "settlement"
    settlement: CallSettlement


type ArtifactEvent = Annotated[
    ManifestEvent | AttemptIntent | RawResponseEvent | TerminalEvent | SettlementEvent,
    Field(discriminator="kind"),
]
"""The closed set of ordered durable run events."""


class JournalRecord(BaseModel, frozen=True, extra="forbid"):
    """One hash-linked journal envelope; digests detect corruption, not forgery.

    Attributes:
        sequence: Contiguous zero-based append position.
        previous_sha256: Previous envelope digest, or None for the manifest.
        event: Validated domain evidence.
        sha256: Canonical hash of sequence, previous digest and event.
    """

    sequence: Annotated[int, Field(ge=0, strict=True)]
    previous_sha256: ArtifactDigest | None
    event: ArtifactEvent
    sha256: ArtifactDigest


class ReplayState(BaseModel, frozen=True, extra="forbid"):
    """Reconstructed evidence with all prior liabilities and no resend decision.

    Attributes:
        manifest: Exact manifest checked against requested resume configuration.
        ledger: Reservation/settlement transitions replayed in journal order.
        events: Every accepted event in chronological order.
        pending_attempts: Intents lacking terminal outcomes; none are free retries.
    """

    manifest: RunManifest
    ledger: BudgetLedger
    events: tuple[ArtifactEvent, ...]
    pending_attempts: tuple[str, ...]


def create_artifact_digest(content: bytes) -> str:
    """Hash exact bytes without environmental inputs.

    Args:
        content: Canonical bytes supplied by the artifact owner.

    Returns:
        SHA-256 lowercase hexadecimal digest.
    """
    return hashlib.sha256(content).hexdigest()


def create_raw_response_event(
    *,
    attempt: str,
    status: int | None,
    body: bytes,
    delivery: Literal["response", "unknown", "not_delivered"],
    secrets: tuple[SecretStr, ...],
) -> RawResponseEvent:
    """Preserve unparsed bytes while redacting every explicitly supplied secret.

    Args:
        attempt: Previously persisted attempt identity.
        status: HTTP status, or None for a transport failure.
        body: Unparsed response bytes; request headers must never be supplied.
        delivery: Explicit transport observation.
        secrets: All configured credentials, never persisted themselves.

    Returns:
        Safe raw evidence with original digest and redaction indicator.
    """
    safe_body = body
    for secret in secrets:
        secret_bytes = secret.get_secret_value().encode()
        if secret_bytes:
            safe_body = safe_body.replace(secret_bytes, b"[REDACTED]")
    return RawResponseEvent(
        attempt=attempt,
        status=status,
        body_base64=base64.b64encode(safe_body).decode("ascii"),
        original_sha256=create_artifact_digest(body),
        redacted=safe_body != body,
        delivery=delivery,
    )


def create_record_digest(
    sequence: int, previous_sha256: str | None, event: ArtifactEvent
) -> str:
    """Hash a canonical envelope excluding its own digest.

    Args:
        sequence: Contiguous append position.
        previous_sha256: Digest of the prior envelope, or None at the start.
        event: Typed event with stable JSON serialization.

    Returns:
        Digest for the canonical envelope.
    """
    content = json.dumps(
        {
            "sequence": sequence,
            "previous_sha256": previous_sha256,
            "event": event.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return create_artifact_digest(content)


class _ArtifactState:
    """Incremental in-memory event state; monetary policy stays in budget.py."""

    def __init__(self, manifest: RunManifest) -> None:
        """Start empty caches for one exact manifest.

        Args:
            manifest: Requested immutable run configuration.
        """
        super().__init__()
        self.manifest = manifest
        self.events: list[ArtifactEvent] = []
        self.reservations: dict[str, CallReservation] = {}
        self.settlements: dict[str, CallSettlement] = {}
        self.requests: dict[str, str] = {}
        self.raw_attempts: set[str] = set()
        self.terminal_attempts: set[str] = set()
        self.exposure = BudgetLedger(
            plan=manifest.budget_plan, reservations=(), settlements=()
        )

    def create_admitted_reservations(
        self, reservations: tuple[CallReservation, ...]
    ) -> tuple[CallReservation, ...]:
        """Check a batch against all liabilities without changing session state.

        Synthetic identities isolate compact exposure entries from real attempts.
        BudgetLedger still owns all cap, funding and account-credit arithmetic.

        Args:
            reservations: Distinct new attempt reservations.

        Returns:
            Original reservations when the whole batch fits current exposure.

        Raises:
            InvalidValueError: If any attempt identity is repeated.
        """
        attempts = {reservation.attempt for reservation in reservations}
        if len(attempts) != len(reservations) or not attempts.isdisjoint(
            self.reservations
        ):
            message = "Duplicate attempt intent; retain prior liability and reconcile."
            raise InvalidValueError(message)
        probe = tuple(
            CallReservation(
                attempt=f"new:{index}",
                arm=item.arm,
                account=item.account,
                maximum_cost=item.maximum_cost,
            )
            for index, item in enumerate(reservations)
        )
        _ = create_reserved_ledger(self.exposure, probe)
        return reservations

    def _create_changed_exposure(
        self, reservation: CallReservation, difference: int
    ) -> BudgetLedger:
        """Aggregate exposure by arm/account before invoking budget invariants.

        Args:
            reservation: Identity of the exposure allocation being changed.
            difference: Reserved addition or verified unused-cost subtraction.

        Returns:
            Compact ledger with identical monetary exposure to exact records.
        """
        totals = {
            (item.arm, item.account): item.maximum_cost
            for item in self.exposure.reservations
        }
        key = (reservation.arm, reservation.account)
        totals[key] = totals.get(key, 0) + difference
        return BudgetLedger(
            plan=self.manifest.budget_plan,
            reservations=tuple(
                CallReservation(
                    attempt=f"exposure:{index}",
                    arm=arm,
                    account=account,
                    maximum_cost=amount,
                )
                for index, ((arm, account), amount) in enumerate(totals.items())
            ),
            settlements=(),
        )

    def _create_intent_exposure(self, event: AttemptIntent) -> BudgetLedger:
        """Check request immutability and atomic funding before recording intent.

        Args:
            event: Proposed dispatch intent, not yet persisted.

        Returns:
            New compact exposure after budget-owned validation.

        Raises:
            InvalidValueError: If the assignment's frozen request changed.
        """
        previous = self.requests.get(event.assignment)
        if previous is not None and previous != event.request_sha256:
            message = "Assignment request changed; reconcile the frozen run."
            raise InvalidValueError(message)
        _ = self.create_admitted_reservations((event.reservation,))
        return self._create_changed_exposure(
            event.reservation, event.reservation.maximum_cost
        )

    def _create_settled_exposure(self, event: SettlementEvent) -> BudgetLedger:
        """Reconcile only budget-validated final bills against exact reservations.

        Args:
            event: Evidence-backed proposed settlement.

        Returns:
            Reduced compact exposure, unchanged for identical receipt replay.

        Raises:
            InvalidValueError: If settlement evidence conflicts or lacks intent.
        """
        settlement = event.settlement
        previous = self.settlements.get(settlement.attempt)
        if previous is not None:
            if previous != settlement:
                message = "Settlement replay conflicts; reconcile billing evidence."
                raise InvalidValueError(message)
            return self.exposure
        reservation = self.reservations.get(settlement.attempt)
        if reservation is None:
            message = "Settlement lacks matching coverage; restore its original intent."
            raise InvalidValueError(message)
        original = BudgetLedger(
            plan=self.manifest.budget_plan,
            reservations=(reservation,),
            settlements=(),
        )
        _ = create_settled_ledger(original, settlement)
        return self._create_changed_exposure(
            reservation, settlement.actual_cost - reservation.maximum_cost
        )

    def _create_manifest_exposure(self, event: ManifestEvent) -> BudgetLedger:
        """Check the unique frozen manifest before applying monetary events.

        Args:
            event: Proposed manifest at the start of the complete stream.

        Returns:
            Unchanged empty exposure under the exact requested configuration.

        Raises:
            InvalidValueError: If the manifest repeats or its configuration differs.
        """
        if self.events:
            message = "Journal repeats its manifest; restore one complete run."
            raise InvalidValueError(message)
        if event.manifest != self.manifest:
            message = "Run configuration changed; reconcile before resuming."
            raise InvalidValueError(message)
        return self.exposure

    def create_next_exposure(self, event: ArtifactEvent) -> BudgetLedger:
        """Validate the next event without mutating any recorded state.

        Args:
            event: Proposed event in chronological order.

        Returns:
            Budget-owned exposure after the proposed transition.

        Raises:
            InvalidValueError: If manifest or raw/terminal ordering conflicts.
        """
        if not self.events and not isinstance(event, ManifestEvent):
            message = "Artifact manifest is missing; restore the complete journal."
            raise InvalidValueError(message)
        match event:
            case ManifestEvent():
                return self._create_manifest_exposure(event)
            case AttemptIntent():
                return self._create_intent_exposure(event)
            case SettlementEvent():
                return self._create_settled_exposure(event)
            case RawResponseEvent(attempt=attempt):
                _ = create_raw_body(event)
                if attempt not in self.reservations or attempt in self.raw_attempts:
                    message = (
                        "Raw evidence lacks unique intent; reconcile journal order."
                    )
                    raise InvalidValueError(message)
            case TerminalEvent(attempt=attempt):
                if (
                    attempt not in self.raw_attempts
                    or attempt in self.terminal_attempts
                ):
                    message = (
                        "Terminal lacks unique raw evidence; reconcile journal order."
                    )
                    raise InvalidValueError(message)
        return self.exposure

    def create_applied_event(
        self, event: ArtifactEvent, exposure: BudgetLedger
    ) -> None:
        """Apply a prevalidated transition to these explicit mutable caches.

        Args:
            event: Validated event, durably saved first when used by a writer.
            exposure: Budget result produced by create_next_exposure.
        """
        self.exposure = exposure
        self.events.append(event)
        match event:
            case AttemptIntent(reservation=reservation):
                self.reservations[reservation.attempt] = reservation
                self.requests[event.assignment] = event.request_sha256
            case SettlementEvent(settlement=settlement):
                self.settlements[settlement.attempt] = settlement
            case RawResponseEvent(attempt=attempt):
                self.raw_attempts.add(attempt)
            case TerminalEvent(attempt=attempt):
                self.terminal_attempts.add(attempt)
            case ManifestEvent():
                pass

    def create_snapshot(self) -> ReplayState:
        """Materialize complete immutable evidence only at explicit checkpoints.

        Returns:
            Full exact attempt ledger, events and remaining occupied attempts.

        Raises:
            InvalidValueError: If the journal has no manifest.
        """
        if not self.events:
            message = "Artifact manifest is missing; restore the complete journal."
            raise InvalidValueError(message)
        return ReplayState(
            manifest=self.manifest,
            ledger=BudgetLedger(
                plan=self.manifest.budget_plan,
                reservations=tuple(self.reservations.values()),
                settlements=tuple(self.settlements.values()),
            ),
            events=tuple(self.events),
            pending_attempts=tuple(
                sorted(self.reservations.keys() - self.terminal_attempts)
            ),
        )


def create_replay_state(
    events: tuple[ArtifactEvent, ...], expected_manifest: RunManifest
) -> ReplayState:
    """Replay each event once, retaining liabilities and rejecting changed config.

    Domain/order failures propagate as InvalidValueError. No pending intent or
    raw response is interpreted as permission to repeat a network attempt.

    Args:
        events: Complete ordered evidence, never a selected suffix.
        expected_manifest: Exact requested manifest, including budget authority.

    Returns:
        Complete immutable state, materialized once after incremental replay.
    """
    state = _ArtifactState(expected_manifest)
    for event in events:
        exposure = state.create_next_exposure(event)
        state.create_applied_event(event, exposure)
    return state.create_snapshot()


def create_raw_body(event: RawResponseEvent) -> bytes:
    """Decode saved raw bytes and verify an unredacted original digest.

    Args:
        event: Raw response evidence loaded from the journal.

    Returns:
        Original bytes, or explicitly redacted bytes.

    Raises:
        InvalidValueError: If base64 is corrupt or unredacted bytes changed.
    """
    try:
        body = base64.b64decode(event.body_base64, validate=True)
    except ValueError as cause:
        message = "Raw evidence encoding is corrupt; restore the journal from evidence."
        raise InvalidValueError(message) from cause
    if not event.redacted and create_artifact_digest(body) != event.original_sha256:
        message = "Raw evidence digest differs; restore the original evidence."
        raise InvalidValueError(message)
    return body


def create_journal_records(content: bytes) -> tuple[JournalRecord, ...]:
    """Validate a complete newline-terminated chain without repairing any bytes.

    Args:
        content: All bytes currently present in one journal.

    Returns:
        Ordered records, or an empty tuple for a newly created empty journal.

    Raises:
        InvalidValueError: If any line, digest, sequence or tail is corrupt.
    """
    if content and not content.endswith(b"\n"):
        message = "Journal has a partial tail; preserve and reconcile it."
        raise InvalidValueError(message)
    records: list[JournalRecord] = []
    previous: str | None = None
    for sequence, line in enumerate(content.splitlines()):
        try:
            _ = json.loads(line, object_pairs_hook=create_unique_json_object)
            record = JournalRecord.model_validate_json(line)
        except (ValueError, InvalidValueError) as cause:
            message = "Journal record is corrupt; preserve it and restore evidence."
            raise InvalidValueError(message) from cause
        if (
            record.sequence != sequence
            or record.previous_sha256 != previous
            or record.sha256 != create_record_digest(sequence, previous, record.event)
        ):
            message = "Journal hash chain is broken; preserve and reconcile the file."
            raise InvalidValueError(message)
        records.append(record)
        previous = record.sha256
    return tuple(records)


def select_artifact_events(path: Path) -> tuple[ArtifactEvent, ...]:
    """Read one complete journal under a shared process lock.

    Corruption raises InvalidValueError; filesystem failures preserve their
    OSError identity for the caller's storage handling.

    Args:
        path: Explicit journal location; no implicit directory lookup.

    Returns:
        Every event after integrity validation, in append order.
    """
    with path.open("rb") as journal:
        fcntl.flock(journal.fileno(), fcntl.LOCK_SH)
        records = create_journal_records(journal.read())
    return tuple(record.event for record in records)


def _create_secret_free_event(
    event: ArtifactEvent, secrets: tuple[SecretStr, ...]
) -> ArtifactEvent:
    """Reject known credentials in serialized fields or decoded raw evidence.

    Args:
        event: Typed proposed event, with no request-header fields.
        secrets: Every configured credential to exclude from durable bytes.

    Returns:
        Original event when safe to persist.

    Raises:
        InvalidValueError: If a configured secret occurs in evidence.
    """
    encoded_event = event.model_dump_json().encode()
    inspected = encoded_event
    if isinstance(event, RawResponseEvent):
        inspected += create_raw_body(event)
    if any(
        secret.get_secret_value()
        and (
            secret.get_secret_value().encode() in inspected
            or json.dumps(secret.get_secret_value(), ensure_ascii=False)[1:-1].encode()
            in inspected
        )
        for secret in secrets
    ):
        message = "Artifact contains credentials; redact them before persisting."
        raise InvalidValueError(message)
    return event


def _insert_durable_record(
    journal: BinaryIO, path: Path, record: JournalRecord
) -> None:
    """Write and synchronize one envelope without rewriting an uncertain tail.

    Args:
        journal: Already locked append-only stream.
        path: Journal location whose parent directory must also be synchronized.
        record: Prevalidated envelope to append.

    Raises:
        InvalidValueError: If the stream reports an incomplete write.
    """
    encoded = record.model_dump_json().encode() + b"\n"
    if journal.write(encoded) != len(encoded):
        message = (
            "Journal write is incomplete; preserve the file and restart validation."
        )
        raise InvalidValueError(message)
    journal.flush()
    os.fsync(journal.fileno())
    directory_descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def insert_artifact_event(
    path: Path, event: ArtifactEvent, *, secrets: tuple[SecretStr, ...]
) -> None:
    """Append one valid event and fsync file/directory before returning.

    A failed/partial write is never rewritten. A subsequent read/append fails
    closed. The lock spans read, state validation and append; all writers must
    use this boundary. Parent directories must already exist. Domain and storage
    failures propagate; do not dispatch a network call if this operation fails.

    Args:
        path: Exact journal path, created exclusively by this workflow.
        event: Next typed event; a new journal requires ManifestEvent first.
        secrets: Every configured credential, rejected even inside raw base64.

    Raises:
        InvalidValueError: If the first event is not a manifest.
    """
    _ = _create_secret_free_event(event, secrets)
    with path.open("a+b") as journal:
        fcntl.flock(journal.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _ = journal.seek(0)
        records = create_journal_records(journal.read())
        events = (*tuple(record.event for record in records), event)
        first_event = events[0]
        if not isinstance(first_event, ManifestEvent):
            message = "First artifact must be a manifest; initialize the run."
            raise InvalidValueError(message)
        manifest = first_event.manifest
        _ = create_replay_state(events, manifest)
        previous = records[-1].sha256 if records else None
        record = JournalRecord(
            sequence=len(records),
            previous_sha256=previous,
            event=event,
            sha256=create_record_digest(len(records), previous, event),
        )
        _insert_durable_record(journal, path, record)


class ArtifactWriter:
    """Locked session performing bounded incremental transitions and durable appends.

    Construct only through select_artifact_writer. The context owns the stream
    and lock. A failed append poisons this instance; close it and validate the
    complete saved journal in a new context before any further network dispatch.
    Snapshots copy the entire history and belong at explicit checkpoints, never
    inside the per-event append path.
    """

    def __init__(
        self,
        journal: BinaryIO,
        path: Path,
        manifest: RunManifest,
        records: tuple[JournalRecord, ...],
        secrets: tuple[SecretStr, ...],
    ) -> None:
        """Replay an integrity-checked journal once under its held exclusive lock.

        Args:
            journal: Locked append-only stream owned by the selecting context.
            path: Exact journal path for directory synchronization.
            manifest: Exact expected configuration, including all liabilities.
            records: Complete hash-validated saved envelopes.
            secrets: Every configured credential to exclude from artifacts.
        """
        super().__init__()
        self._journal = journal
        self._path = path
        self._secrets = secrets
        self._state = _ArtifactState(manifest)
        self._active = True
        self._sequence = len(records)
        self._previous = records[-1].sha256 if records else None
        for record in records:
            _ = _create_secret_free_event(record.event, secrets)
            exposure = self._state.create_next_exposure(record.event)
            self._state.create_applied_event(record.event, exposure)

    def _create_active_access(self) -> None:
        """Refuse use after a failed append or after the selecting context closes.

        Raises:
            InvalidValueError: If this session is closed or write-poisoned.
        """
        if not self._active:
            message = (
                "Artifact session is closed or failed; restart full journal validation."
            )
            raise InvalidValueError(message)

    def create_admitted_reservations(
        self, reservations: tuple[CallReservation, ...]
    ) -> tuple[CallReservation, ...]:
        """Check a row/batch atomically against all current liabilities.

        This does not persist intent or grant dispatch authority. Persist every
        admitted intent before any associated network call. Validation failures
        propagate without changing the session's valid prior state.

        Args:
            reservations: Entire intended batch, including all judge attempts.

        Returns:
            Original tuple when budget-owned cap/credit checks all pass.
        """
        self._create_active_access()
        return self._state.create_admitted_reservations(reservations)

    def create_snapshot(self) -> ReplayState:
        """Copy full exact history at an explicit checkpoint, outside append loops.

        Returns:
            Immutable event history and exact original attempt/settlement ledger.
        """
        self._create_active_access()
        return self._state.create_snapshot()

    def insert_event(self, event: ArtifactEvent) -> None:
        """Validate, append, flush and fsync one event without replaying history.

        In-memory state advances only after file/directory synchronization. Any
        interruption in that write/commit window permanently invalidates this
        session; its complete journal must be validated again on restart.
        Validation failures before writing preserve a usable prior session.

        Args:
            event: Next typed event; raw evidence must precede its terminal.
        """
        self._create_active_access()
        _ = _create_secret_free_event(event, self._secrets)
        exposure = self._state.create_next_exposure(event)
        record = JournalRecord(
            sequence=self._sequence,
            previous_sha256=self._previous,
            event=event,
            sha256=create_record_digest(self._sequence, self._previous, event),
        )
        try:
            _insert_durable_record(self._journal, self._path, record)
            self._state.create_applied_event(event, exposure)
            self._sequence += 1
            self._previous = record.sha256
        except BaseException:
            self._active = False
            raise

    def remove_access(self) -> None:
        """Invalidate this session when its owning context releases the lock."""
        self._active = False


@contextmanager
def select_artifact_writer(
    path: Path, expected_manifest: RunManifest, *, secrets: tuple[SecretStr, ...]
) -> Generator[ArtifactWriter]:
    """Hold one exclusive writer lock and replay once for the entire context.

    An empty journal receives its manifest durably before the writer is yielded.
    Existing journals must match the exact manifest and all integrity/state
    checks. Full histories are not reread, revalidated or copied on append.
    Filesystem/domain failures propagate and the stream closes on every exit.

    Args:
        path: Explicit journal path in an already existing parent directory.
        expected_manifest: Exact frozen run configuration required on restart.
        secrets: All configured SecretStr credentials for exclusion/redaction.

    Yields:
        Incremental writer; use insert_event and batch admission inside the lock.

    Raises:
        InvalidValueError: If another writer already holds the journal lock.
    """
    with path.open("a+b") as journal:
        try:
            fcntl.flock(journal.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as cause:
            message = "Journal already has a writer; wait for its session to close."
            raise InvalidValueError(message) from cause
        _ = journal.seek(0)
        records = create_journal_records(journal.read())
        writer = ArtifactWriter(journal, path, expected_manifest, records, secrets)
        try:
            if not records:
                writer.insert_event(ManifestEvent(manifest=expected_manifest))
            yield writer
        finally:
            writer.remove_access()
