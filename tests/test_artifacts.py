import base64
import json
import os
lazy from pathlib import Path
lazy from typing import BinaryIO

import pytest
from pydantic import SecretStr, ValidationError

import safety_judge.artifacts as artifacts_module
from safety_judge.artifacts import (
    AttemptIntent,
    ManifestEvent,
    RawResponseEvent,
    RunManifest,
    SettlementEvent,
    TerminalEvent,
    create_artifact_digest,
    create_raw_body,
    create_raw_response_event,
    create_replay_state,
    insert_artifact_event,
    select_artifact_events,
    select_artifact_writer,
)
from safety_judge.budget import (
    ArmCap,
    BudgetPlan,
    CallReservation,
    CallSettlement,
    FundingCommitment,
    create_total_exposure,
)
from safety_judge.errors import InvalidValueError
from safety_judge.judging import JudgeRole, OrdinalJudgment, UnresolvedJudgment
from safety_judge.model_access import create_model_route


@pytest.fixture
def manifest() -> RunManifest:
    digest = create_artifact_digest(b"frozen input")
    return RunManifest(
        run="synthetic-run",
        configuration_sha256=digest,
        source_sha256=digest,
        assignments_sha256=digest,
        budget_plan=BudgetPlan(
            identifier="test-plan",
            confirmed=True,
            global_cap=30_000_000,
            arms=(ArmCap(arm="main", cap=30_000_000),),
            funding=(FundingCommitment(account="test", committed=0, usable_credit=0),),
            other_costs=0,
        ),
        model_routes=(create_model_route(JudgeRole.GEMMA_ONE),),
    )


@pytest.fixture
def journal(tmp_path: Path, manifest: RunManifest) -> Path:
    path = tmp_path / "events.jsonl"
    insert_artifact_event(path, ManifestEvent(manifest=manifest), secrets=())
    return path


def create_intent(attempt: str = "attempt-one") -> AttemptIntent:
    return AttemptIntent(
        assignment="case-one/G1",
        reservation=CallReservation(
            attempt=attempt, arm="main", account="test", maximum_cost=10_000_000
        ),
        request_sha256=create_artifact_digest(b"request"),
    )


def create_raw(attempt: str = "attempt-one") -> RawResponseEvent:
    return create_raw_response_event(
        attempt=attempt,
        status=200,
        body=b'{"ordinal": 4}',
        delivery="response",
        secrets=(),
    )


def test_intent_before_dispatch_crash_retains_full_liability_without_a_resend_flag(
    journal: Path,
    manifest: RunManifest,
) -> None:
    insert_artifact_event(journal, create_intent(), secrets=())
    replay = create_replay_state(select_artifact_events(journal), manifest)
    assert replay.pending_attempts == ("attempt-one",)
    assert create_total_exposure(replay.ledger) == 10_000_000
    with pytest.raises(InvalidValueError, match="Duplicate"):
        insert_artifact_event(journal, create_intent(), secrets=())
    assert len(select_artifact_events(journal)) == 2


def test_raw_saved_before_parse_can_be_replayed_without_another_call(
    journal: Path,
    manifest: RunManifest,
) -> None:
    insert_artifact_event(journal, create_intent(), secrets=())
    raw = create_raw()
    insert_artifact_event(journal, raw, secrets=())
    replay = create_replay_state(select_artifact_events(journal), manifest)
    assert replay.pending_attempts == ("attempt-one",)
    assert create_raw_body(raw) == b'{"ordinal": 4}'
    insert_artifact_event(
        journal,
        TerminalEvent(
            attempt="attempt-one", outcome=UnresolvedJudgment(reason="unknown")
        ),
        secrets=(),
    )
    terminal = create_replay_state(select_artifact_events(journal), manifest)
    assert terminal.pending_attempts == ()
    assert create_total_exposure(terminal.ledger) == 10_000_000


def test_verified_billing_releases_only_the_saved_unused_reservation(
    journal: Path,
    manifest: RunManifest,
) -> None:
    insert_artifact_event(journal, create_intent(), secrets=())
    insert_artifact_event(
        journal,
        SettlementEvent(
            settlement=CallSettlement(
                attempt="attempt-one", actual_cost=1_000_000, evidence="verified-bill"
            )
        ),
        secrets=(),
    )
    replay = create_replay_state(select_artifact_events(journal), manifest)
    assert create_total_exposure(replay.ledger) == 1_000_000
    assert replay.pending_attempts == ("attempt-one",)


def test_changed_frozen_configuration_refuses_resume(
    journal: Path,
    manifest: RunManifest,
) -> None:
    changed = RunManifest.model_validate(
        {
            **manifest.model_dump(),
            "configuration_sha256": create_artifact_digest(b"changed"),
        }
    )
    with pytest.raises(InvalidValueError, match="changed"):
        _ = create_replay_state(select_artifact_events(journal), changed)


@pytest.mark.parametrize("suffix", [b'{"partial":', b"\n", b"garbage\n"])
def test_corrupt_or_partial_tails_are_preserved_and_block_read_and_append(
    journal: Path,
    suffix: bytes,
) -> None:
    damaged = journal.read_bytes() + suffix
    _ = journal.write_bytes(damaged)
    with pytest.raises(InvalidValueError):
        _ = select_artifact_events(journal)
    with pytest.raises(InvalidValueError):
        insert_artifact_event(journal, create_intent(), secrets=())
    assert journal.read_bytes() == damaged


def test_modified_complete_records_break_the_hash_chain(journal: Path) -> None:
    original = journal.read_bytes()
    modified = original.replace(b"synthetic-run", b"different-run")
    assert modified != original
    _ = journal.write_bytes(modified)
    with pytest.raises(InvalidValueError, match="hash chain"):
        _ = select_artifact_events(journal)


def test_duplicate_reordered_or_missing_intents_never_advance_the_journal(
    journal: Path,
) -> None:
    original = journal.read_bytes()
    for event in (
        create_raw(),
        TerminalEvent(
            attempt="attempt-one", outcome=UnresolvedJudgment(reason="unknown")
        ),
    ):
        with pytest.raises(InvalidValueError):
            insert_artifact_event(journal, event, secrets=())
        assert journal.read_bytes() == original


def test_journal_rejects_a_second_manifest(
    journal: Path, manifest: RunManifest
) -> None:
    original = journal.read_bytes()
    with pytest.raises(InvalidValueError, match="repeats"):
        insert_artifact_event(journal, ManifestEvent(manifest=manifest), secrets=())
    assert journal.read_bytes() == original


def test_raw_credentials_are_redacted_even_inside_base64_artifacts(
    journal: Path,
) -> None:
    secret = SecretStr("synthetic-bearer-secret")
    body = b"error echoed Authorization: Bearer synthetic-bearer-secret"
    raw = create_raw_response_event(
        attempt="attempt-one",
        status=401,
        body=body,
        delivery="response",
        secrets=(secret,),
    )
    insert_artifact_event(journal, create_intent(), secrets=(secret,))
    insert_artifact_event(journal, raw, secrets=(secret,))
    assert raw.redacted
    assert b"synthetic-bearer-secret" not in create_raw_body(raw)
    assert raw.original_sha256 == create_artifact_digest(body)
    assert b"synthetic-bearer-secret" not in journal.read_bytes()
    unsafe = create_raw_response_event(
        attempt="attempt-two", status=401, body=body, delivery="response", secrets=()
    )
    with pytest.raises(InvalidValueError, match="credentials"):
        insert_artifact_event(journal, unsafe, secrets=(secret,))


def test_every_append_fsyncs_file_and_parent_directory(
    journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptors: list[int] = []
    monkeypatch.setattr(os, "fsync", descriptors.append)
    insert_artifact_event(journal, create_intent(), secrets=())
    assert len(descriptors) == 2
    assert descriptors[0] != descriptors[1]


def test_fsync_failure_never_reports_success_or_erases_written_intent(
    journal: Path,
    manifest: RunManifest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def insert_failed_sync(_descriptor: int) -> None:
        message = "synthetic fsync failure"
        raise OSError(message)

    monkeypatch.setattr(os, "fsync", insert_failed_sync)
    with pytest.raises(OSError, match="fsync"):
        insert_artifact_event(journal, create_intent(), secrets=())
    replay = create_replay_state(select_artifact_events(journal), manifest)
    assert create_total_exposure(replay.ledger) == 10_000_000


@pytest.mark.parametrize(
    "encoding", ["!not-base64", base64.b64encode(b"changed").decode()]
)
def test_saved_raw_corruption_is_rejected(encoding: str) -> None:
    raw = RawResponseEvent.model_validate(
        {**create_raw().model_dump(), "body_base64": encoding}
    )
    with pytest.raises(InvalidValueError):
        _ = create_raw_body(raw)


def test_empty_journal_cannot_begin_with_an_attempt(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    with pytest.raises(InvalidValueError, match="manifest"):
        insert_artifact_event(path, create_intent(), secrets=())
    assert path.read_bytes() == b""


def test_duplicate_json_keys_in_saved_envelopes_are_rejected(journal: Path) -> None:
    original = journal.read_bytes()
    duplicated = original.replace(b'"sequence":0', b'"sequence":9,"sequence":0')
    assert duplicated != original
    _ = journal.write_bytes(duplicated)
    with pytest.raises(InvalidValueError, match="corrupt"):
        _ = select_artifact_events(journal)


def test_json_escaped_credentials_are_also_refused(
    tmp_path: Path,
    manifest: RunManifest,
) -> None:
    secret = SecretStr('synthetic"secret')
    unsafe = RunManifest.model_validate(
        {**manifest.model_dump(), "run": secret.get_secret_value()}
    )
    with pytest.raises(InvalidValueError, match="credentials"):
        insert_artifact_event(
            tmp_path / "unsafe.jsonl",
            ManifestEvent(manifest=unsafe),
            secrets=(secret,),
        )
    assert not (tmp_path / "unsafe.jsonl").exists()


def test_retry_cannot_change_an_assignments_frozen_request(journal: Path) -> None:
    insert_artifact_event(journal, create_intent(), secrets=())
    changed = AttemptIntent.model_validate(
        {
            **create_intent("attempt-two").model_dump(),
            "request_sha256": create_artifact_digest(b"different request"),
        }
    )
    with pytest.raises(InvalidValueError, match="request changed"):
        insert_artifact_event(journal, changed, secrets=())
    assert len(select_artifact_events(journal)) == 2


def test_session_appends_incrementally_and_restarts_with_exact_liability(
    journal: Path,
    manifest: RunManifest,
) -> None:
    with select_artifact_writer(journal, manifest, secrets=()) as writer:
        admitted = writer.create_admitted_reservations((create_intent().reservation,))
        assert admitted == (create_intent().reservation,)
        writer.insert_event(create_intent())
        writer.insert_event(create_raw())
        writer.insert_event(
            TerminalEvent(
                attempt="attempt-one", outcome=UnresolvedJudgment(reason="unknown")
            )
        )
        writer.insert_event(
            SettlementEvent(
                settlement=CallSettlement(
                    attempt="attempt-one",
                    actual_cost=1_000_000,
                    evidence="verified bill",
                )
            )
        )
        snapshot = writer.create_snapshot()
        assert create_total_exposure(snapshot.ledger) == 1_000_000
        assert snapshot.pending_attempts == ()
    with select_artifact_writer(journal, manifest, secrets=()) as restarted:
        assert restarted.create_snapshot() == snapshot
    assert create_replay_state(select_artifact_events(journal), manifest) == snapshot


def test_session_initializes_manifest_before_yielding_and_rejects_use_after_close(
    tmp_path: Path,
    manifest: RunManifest,
) -> None:
    path = tmp_path / "session.jsonl"
    with select_artifact_writer(path, manifest, secrets=()) as writer:
        assert len(writer.create_snapshot().events) == 1
        writer.insert_event(create_intent())
    with pytest.raises(InvalidValueError, match="session"):
        writer.insert_event(create_raw())
    with pytest.raises(InvalidValueError, match="session"):
        _ = writer.create_snapshot()
    with pytest.raises(InvalidValueError, match="session"):
        _ = writer.create_admitted_reservations((create_intent("retry").reservation,))


def test_session_excludes_another_writer_for_its_entire_lifetime(
    journal: Path,
    manifest: RunManifest,
) -> None:
    with select_artifact_writer(journal, manifest, secrets=()) as writer:
        writer.insert_event(create_intent())
        with (
            pytest.raises(InvalidValueError, match="already has a writer"),
            select_artifact_writer(journal, manifest, secrets=()),
        ):
            pytest.fail("a second writer acquired the held lock")
        with pytest.raises(BlockingIOError):
            insert_artifact_event(journal, create_raw(), secrets=())
        assert len(writer.create_snapshot().events) == 2
    with select_artifact_writer(journal, manifest, secrets=()) as restarted:
        restarted.insert_event(create_raw())


def test_session_does_not_reread_or_full_replay_history_on_append(
    journal: Path,
    manifest: RunManifest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with select_artifact_writer(journal, manifest, secrets=()) as writer:

        def create_forbidden_history_read(_content: bytes) -> None:
            pytest.fail("an append reparsed the complete journal")

        monkeypatch.setattr(
            artifacts_module, "create_journal_records", create_forbidden_history_read
        )
        monkeypatch.setattr(
            artifacts_module, "create_replay_state", create_forbidden_history_read
        )
        writer.insert_event(create_intent())
        writer.insert_event(create_raw())
        assert len(writer.create_snapshot().events) == 3


def test_failed_session_write_retains_uncertain_intent_and_refuses_further_access(
    journal: Path,
    manifest: RunManifest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with select_artifact_writer(journal, manifest, secrets=()) as writer:

        def insert_failed_sync(_descriptor: int) -> None:
            message = "synthetic storage failure"
            raise OSError(message)

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", insert_failed_sync)
            with pytest.raises(OSError, match="storage failure"):
                writer.insert_event(create_intent())
        with pytest.raises(InvalidValueError, match="session"):
            writer.insert_event(create_raw())
        with pytest.raises(InvalidValueError, match="session"):
            _ = writer.create_snapshot()
    with select_artifact_writer(journal, manifest, secrets=()) as restarted:
        snapshot = restarted.create_snapshot()
        assert snapshot.pending_attempts == ("attempt-one",)
        assert create_total_exposure(snapshot.ledger) == 10_000_000


def test_partial_session_write_poisoning_does_not_repair_the_tail_on_restart(
    journal: Path,
    manifest: RunManifest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def insert_partial_record(
        stream: BinaryIO,
        _path: Path,
        _record: artifacts_module.JournalRecord,
    ) -> None:
        _ = stream.write(b'{"partial":')
        stream.flush()
        message = "synthetic partial write"
        raise OSError(message)

    with select_artifact_writer(journal, manifest, secrets=()) as writer:
        with monkeypatch.context() as patch:
            patch.setattr(
                artifacts_module, "_insert_durable_record", insert_partial_record
            )
            with pytest.raises(OSError, match="partial write"):
                writer.insert_event(create_intent())
        with pytest.raises(InvalidValueError, match="session"):
            writer.insert_event(create_intent("retry"))
    damaged = journal.read_bytes()
    with (
        pytest.raises(InvalidValueError, match="partial tail"),
        select_artifact_writer(journal, manifest, secrets=()),
    ):
        pytest.fail("partial tail was accepted")
    assert journal.read_bytes() == damaged


def test_session_releases_its_lock_on_caller_exception(
    journal: Path,
    manifest: RunManifest,
) -> None:
    def select_failed_session() -> None:
        with select_artifact_writer(journal, manifest, secrets=()) as writer:
            writer.insert_event(create_intent())
            message = "synthetic caller failure"
            raise InvalidValueError(message)

    with pytest.raises(InvalidValueError, match="synthetic caller"):
        select_failed_session()
    with select_artifact_writer(journal, manifest, secrets=()) as restarted:
        assert restarted.create_snapshot().pending_attempts == ("attempt-one",)


def test_session_batch_admission_and_credit_settlement_use_all_prior_liabilities(
    journal: Path,
    manifest: RunManifest,
) -> None:
    with select_artifact_writer(journal, manifest, secrets=()) as writer:
        for index in range(3):
            writer.insert_event(create_intent(f"attempt-{index}"))
        with pytest.raises(InvalidValueError, match="cap"):
            _ = writer.create_admitted_reservations(
                (create_intent("fourth").reservation,)
            )
        writer.insert_event(
            SettlementEvent(
                settlement=CallSettlement(
                    attempt="attempt-0", actual_cost=0, evidence="verified unused"
                )
            )
        )
        _ = writer.create_admitted_reservations((create_intent("fourth").reservation,))
        writer.insert_event(create_intent("fourth"))
        assert create_total_exposure(writer.create_snapshot().ledger) == 30_000_000


def test_session_validation_failure_preserves_valid_prior_state(
    journal: Path,
    manifest: RunManifest,
) -> None:
    with select_artifact_writer(journal, manifest, secrets=()) as writer:
        with pytest.raises(InvalidValueError):
            writer.insert_event(create_raw())
        writer.insert_event(create_intent())
        assert create_total_exposure(writer.create_snapshot().ledger) == 10_000_000


def test_compact_session_exposure_matches_exact_prepaid_credit_accounting(
    tmp_path: Path,
    manifest: RunManifest,
) -> None:
    plan = BudgetPlan.model_validate(
        {
            **manifest.budget_plan.model_dump(),
            "funding": (
                FundingCommitment(
                    account="test", committed=12_000_000, usable_credit=10_000_000
                ),
            ),
            "other_costs": 1_000_000,
        }
    )
    funded = RunManifest.model_validate({**manifest.model_dump(), "budget_plan": plan})
    path = tmp_path / "prepaid.jsonl"
    with select_artifact_writer(path, funded, secrets=()) as writer:
        writer.insert_event(create_intent("one"))
        assert create_total_exposure(writer.create_snapshot().ledger) == 13_000_000
        writer.insert_event(create_intent("two"))
        assert create_total_exposure(writer.create_snapshot().ledger) == 23_000_000
        with pytest.raises(InvalidValueError, match="global cap"):
            _ = writer.create_admitted_reservations(
                (create_intent("three").reservation,)
            )
        receipt = SettlementEvent(
            settlement=CallSettlement(
                attempt="one", actual_cost=1_000_000, evidence="verified billing"
            )
        )
        writer.insert_event(receipt)
        writer.insert_event(receipt)
        assert create_total_exposure(writer.create_snapshot().ledger) == 14_000_000
        writer.insert_event(create_intent("three"))
        snapshot = writer.create_snapshot()
        assert create_total_exposure(snapshot.ledger) == 24_000_000
    with select_artifact_writer(path, funded, secrets=()) as restarted:
        assert restarted.create_snapshot() == snapshot


def test_session_rejects_conflicting_settlement_and_overrun_without_releasing_cost(
    journal: Path,
    manifest: RunManifest,
) -> None:
    with select_artifact_writer(journal, manifest, secrets=()) as writer:
        writer.insert_event(create_intent())
        with pytest.raises(InvalidValueError, match="coverage"):
            writer.insert_event(
                SettlementEvent(
                    settlement=CallSettlement(
                        attempt="attempt-one",
                        actual_cost=10_000_001,
                        evidence="overrun",
                    )
                )
            )
        assert create_total_exposure(writer.create_snapshot().ledger) == 10_000_000
        writer.insert_event(
            SettlementEvent(
                settlement=CallSettlement(
                    attempt="attempt-one", actual_cost=1_000_000, evidence="first"
                )
            )
        )
        with pytest.raises(InvalidValueError, match="conflicts"):
            writer.insert_event(
                SettlementEvent(
                    settlement=CallSettlement(
                        attempt="attempt-one", actual_cost=0, evidence="changed"
                    )
                )
            )
        assert create_total_exposure(writer.create_snapshot().ledger) == 1_000_000


def test_incremental_session_caps_are_bounded_by_allocation_count_not_attempt_count(
    tmp_path: Path,
    manifest: RunManifest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = artifacts_module.create_reserved_ledger
    sizes: list[int] = []

    def create_measured_admission(
        ledger: artifacts_module.BudgetLedger,
        reservations: tuple[CallReservation, ...],
    ) -> artifacts_module.BudgetLedger:
        sizes.append(len(ledger.reservations))
        return original(ledger, reservations)

    monkeypatch.setattr(
        artifacts_module, "create_reserved_ledger", create_measured_admission
    )
    path = tmp_path / "bounded.jsonl"
    with select_artifact_writer(path, manifest, secrets=()) as writer:
        for index in range(50):
            writer.insert_event(
                AttemptIntent.model_validate(
                    {
                        **create_intent(str(index)).model_dump(),
                        "reservation": CallReservation(
                            attempt=str(index),
                            arm="main",
                            account="test",
                            maximum_cost=1,
                        ),
                    }
                )
            )
        assert len(writer.create_snapshot().ledger.reservations) == 50
    assert max(sizes) == 1


@pytest.mark.parametrize("ordinal", [True, 1.0, 5.0])
def test_nested_saved_terminal_json_refuses_boolean_and_float_ordinals(
    ordinal: object,
) -> None:
    payload = {
        "attempt": "attempt-one",
        "outcome": {"kind": "judgment", "ordinal": ordinal},
    }
    with pytest.raises(ValidationError):
        _ = TerminalEvent.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("ordinal", [True, 1.0])
def test_actual_journal_replay_refuses_nested_ordinal_coercion(
    journal: Path,
    manifest: RunManifest,
    ordinal: object,
) -> None:
    insert_artifact_event(journal, create_intent(), secrets=())
    insert_artifact_event(journal, create_raw(), secrets=())
    insert_artifact_event(
        journal,
        TerminalEvent(attempt="attempt-one", outcome=OrdinalJudgment(ordinal=1)),
        secrets=(),
    )
    lines = journal.read_bytes().splitlines()
    terminal = json.loads(lines[-1])
    terminal["event"]["outcome"]["ordinal"] = ordinal
    # Retain the integer digest: coercion would otherwise normalize and accept it.
    lines[-1] = json.dumps(terminal, separators=(",", ":")).encode()
    damaged = b"\n".join(lines) + b"\n"
    _ = journal.write_bytes(damaged)
    with pytest.raises(InvalidValueError, match="corrupt"):
        _ = select_artifact_events(journal)
    with (
        pytest.raises(InvalidValueError, match="corrupt"),
        select_artifact_writer(journal, manifest, secrets=()),
    ):
        pytest.fail("the saved ordinal was coerced during session replay")
    assert journal.read_bytes() == damaged
