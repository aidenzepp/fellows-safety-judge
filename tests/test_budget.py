from typing import assert_type

import pytest
from pydantic import ValidationError

from safety_judge.budget import (
    ArmCap,
    BudgetLedger,
    BudgetPlan,
    CallReservation,
    CallSettlement,
    FundingCommitment,
    TokenPrice,
    create_call_reservation,
    create_reserved_ledger,
    create_resumed_ledger,
    create_settled_ledger,
    create_total_exposure,
)
from safety_judge.errors import InvalidValueError


@pytest.fixture
def ledger() -> BudgetLedger:
    return BudgetLedger(
        plan=BudgetPlan(
            identifier="confirmed-v1",
            confirmed=True,
            global_cap=30_000_000,
            arms=(ArmCap(arm="main", cap=25_000_000), ArmCap(arm="h2", cap=5_000_000)),
            funding=(
                FundingCommitment(
                    existing_credit=0, account="provider", committed=0, usable_credit=0
                ),
            ),
            other_costs=0,
        ),
        reservations=(),
        settlements=(),
    )


def create_reservation(
    attempt: str, amount: int, *, arm: str = "main", account: str = "provider"
) -> CallReservation:
    return CallReservation(
        attempt=attempt, arm=arm, account=account, maximum_cost=amount
    )


def test_exact_global_and_arm_caps_are_admitted_and_one_microdollar_more_is_not(
    ledger: BudgetLedger,
) -> None:
    full = create_reserved_ledger(
        ledger,
        (
            create_reservation("first", 25_000_000),
            create_reservation("second", 5_000_000, arm="h2"),
        ),
    )
    assert create_total_exposure(full) == 30_000_000
    with pytest.raises(InvalidValueError, match="cap"):
        _ = create_reserved_ledger(full, (create_reservation("retry", 1),))
    assert len(full.reservations) == 2


def test_failed_row_batch_never_admits_only_the_affordable_judges(
    ledger: BudgetLedger,
) -> None:
    with pytest.raises(InvalidValueError, match="cap"):
        _ = create_reserved_ledger(
            ledger,
            tuple(create_reservation(str(index), 7_000_000) for index in range(4)),
        )
    assert ledger.reservations == ()
    assert create_total_exposure(ledger) == 0


def test_prepaid_credit_counts_once_and_cannot_cover_another_account(
    ledger: BudgetLedger,
) -> None:
    plan = BudgetPlan.model_validate(
        {
            **ledger.plan.model_dump(),
            "funding": (
                FundingCommitment(
                    existing_credit=0,
                    account="provider",
                    committed=10_000_000,
                    usable_credit=8_000_000,
                ),
                FundingCommitment(
                    existing_credit=0, account="reviewer", committed=0, usable_credit=0
                ),
            ),
            "other_costs": 2_000_000,
        }
    )
    prepaid = BudgetLedger(plan=plan, reservations=(), settlements=())
    covered = create_reserved_ledger(prepaid, (create_reservation("one", 8_000_000),))
    assert create_total_exposure(covered) == 12_000_000
    uncovered = create_reserved_ledger(
        covered, (create_reservation("two", 5_000_000, account="reviewer"),)
    )
    assert create_total_exposure(uncovered) == 17_000_000
    exceeded_credit = create_reserved_ledger(
        uncovered, (create_reservation("three", 3_000_000),)
    )
    assert create_total_exposure(exceeded_credit) == 20_000_000


def test_nonusage_costs_can_exhaust_global_cap_before_arm_caps(
    ledger: BudgetLedger,
) -> None:
    plan = BudgetPlan.model_validate(
        {**ledger.plan.model_dump(), "other_costs": 29_000_000}
    )
    expensive = BudgetLedger(plan=plan, reservations=(), settlements=())
    full = create_reserved_ledger(expensive, (create_reservation("one", 1_000_000),))
    assert create_total_exposure(full) == 30_000_000
    with pytest.raises(InvalidValueError, match="global cap"):
        _ = create_reserved_ledger(full, (create_reservation("two", 1),))


@pytest.mark.parametrize("unknown", ["fees", "commitment", "unconfirmed"])
def test_missing_obligations_or_unconfirmed_plans_never_fund_calls(
    ledger: BudgetLedger, unknown: str
) -> None:
    values = ledger.plan.model_dump()
    if unknown == "fees":
        values["other_costs"] = None
    elif unknown == "commitment":
        values["funding"] = (
            FundingCommitment(
                existing_credit=0, account="provider", committed=None, usable_credit=0
            ),
        )
    else:
        values["confirmed"] = False
    unfunded = BudgetLedger(
        plan=BudgetPlan.model_validate(values), reservations=(), settlements=()
    )
    with pytest.raises(InvalidValueError):
        _ = create_reserved_ledger(unfunded, (create_reservation("one", 0),))


@pytest.mark.parametrize(
    ("input_rate", "output_rate", "confirmed"),
    [(None, 1, True), (1, None, True), (1, 1, False)],
)
def test_missing_or_unconfirmed_prices_cannot_become_zero_cost(
    input_rate: int | None, output_rate: int | None, *, confirmed: bool
) -> None:
    with pytest.raises(InvalidValueError, match="unbounded"):
        _ = create_call_reservation(
            attempt="attempt",
            arm="main",
            price=TokenPrice(
                account="provider",
                confirmed=confirmed,
                input_per_million=input_rate,
                output_per_million=output_rate,
            ),
            maximum_input_tokens=1,
            maximum_output_tokens=1,
        )


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens", "expected"),
    [(1, 0, 1), (500_000, 500_000, 1), (1_000_001, 0, 2), (0, 0, 0)],
)
def test_token_costs_round_up_conservatively_without_floats(
    input_tokens: int, output_tokens: int, expected: int
) -> None:
    reservation = create_call_reservation(
        attempt="one",
        arm="main",
        price=TokenPrice(
            account="provider",
            confirmed=True,
            input_per_million=1,
            output_per_million=1,
        ),
        maximum_input_tokens=input_tokens,
        maximum_output_tokens=output_tokens,
    )
    _ = assert_type(reservation, CallReservation)
    assert reservation.maximum_cost == expected


@pytest.mark.parametrize("tokens", [-1, True])
def test_invalid_token_bounds_are_refused(tokens: int) -> None:
    with pytest.raises(InvalidValueError, match="unbounded"):
        _ = create_call_reservation(
            attempt="one",
            arm="main",
            price=TokenPrice(
                account="provider",
                confirmed=True,
                input_per_million=1,
                output_per_million=1,
            ),
            maximum_input_tokens=tokens,
            maximum_output_tokens=1,
        )


def test_settlement_releases_only_verified_unused_liability_and_replay_is_idempotent(
    ledger: BudgetLedger,
) -> None:
    reserved = create_reserved_ledger(ledger, (create_reservation("one", 10_000_000),))
    receipt = CallSettlement(attempt="one", actual_cost=2_000_000, evidence="bill:1")
    settled = create_settled_ledger(reserved, receipt)
    assert create_total_exposure(settled) == 2_000_000
    assert create_total_exposure(reserved) == 10_000_000
    assert create_settled_ledger(settled, receipt) is settled
    with pytest.raises(InvalidValueError, match="conflicts"):
        _ = create_settled_ledger(
            settled, CallSettlement(attempt="one", actual_cost=0, evidence="other")
        )


@pytest.mark.parametrize(("attempt", "cost"), [("unknown", 0), ("one", 11)])
def test_unreserved_or_overrunning_settlements_are_not_released(
    ledger: BudgetLedger, attempt: str, cost: int
) -> None:
    reserved = create_reserved_ledger(ledger, (create_reservation("one", 10),))
    with pytest.raises(InvalidValueError, match="coverage"):
        _ = create_settled_ledger(
            reserved, CallSettlement(attempt=attempt, actual_cost=cost, evidence="bill")
        )
    assert create_total_exposure(reserved) == 10


def test_crash_replay_preserves_unknown_delivery_and_retry_needs_separate_funding(
    ledger: BudgetLedger,
) -> None:
    intent = create_reserved_ledger(ledger, (create_reservation("first", 20_000_000),))
    restored = BudgetLedger.model_validate_json(intent.model_dump_json())
    resumed = create_resumed_ledger(restored, ledger.plan)
    assert create_total_exposure(resumed) == 20_000_000
    with pytest.raises(InvalidValueError, match="cap"):
        _ = create_reserved_ledger(resumed, (create_reservation("retry", 20_000_000),))
    with pytest.raises(InvalidValueError, match="Duplicate"):
        _ = create_reserved_ledger(resumed, (create_reservation("first", 20_000_000),))
    affordable_retry = create_reserved_ledger(
        resumed, (create_reservation("retry", 5_000_000),)
    )
    assert create_total_exposure(affordable_retry) == 25_000_000


def test_resume_refuses_changed_configuration(ledger: BudgetLedger) -> None:
    changed = BudgetPlan.model_validate(
        {**ledger.plan.model_dump(), "identifier": "changed"}
    )
    with pytest.raises(InvalidValueError, match="changed"):
        _ = create_resumed_ledger(ledger, changed)


@pytest.mark.parametrize("cap", [30_000_001, -1, True])
def test_hard_ceiling_cannot_be_expanded_or_coerced(
    ledger: BudgetLedger, cap: int
) -> None:
    with pytest.raises(ValidationError):
        _ = BudgetPlan.model_validate({**ledger.plan.model_dump(), "global_cap": cap})


def test_nested_models_are_immutable_and_unknown_fields_are_forbidden(
    ledger: BudgetLedger,
) -> None:
    with pytest.raises(ValidationError, match="frozen"):
        ledger.plan.confirmed = False  # pyright: ignore[reportAttributeAccessIssue] -- Test runtime immutability.
    with pytest.raises(ValidationError, match="extra"):
        _ = BudgetLedger.model_validate({**ledger.model_dump(), "free_money": 1})


def test_credit_must_be_backed_by_counted_commitment() -> None:
    with pytest.raises(InvalidValueError, match="exceeds"):
        _ = FundingCommitment(
            existing_credit=0, account="provider", committed=1, usable_credit=2
        )


@pytest.mark.parametrize("field", ["arms", "funding"])
def test_duplicate_plan_keys_are_refused(ledger: BudgetLedger, field: str) -> None:
    values = ledger.plan.model_dump()
    values[field] = (*values[field], *values[field])
    with pytest.raises(InvalidValueError, match="allocations"):
        _ = BudgetPlan.model_validate(values)


def test_undeclared_accounts_and_arms_are_refused(ledger: BudgetLedger) -> None:
    for reservation in (
        create_reservation("one", 1, arm="unknown"),
        create_reservation("one", 1, account="unknown"),
    ):
        with pytest.raises(InvalidValueError, match="undeclared"):
            _ = create_reserved_ledger(ledger, (reservation,))


@pytest.mark.parametrize("amount", [-1, True, 1.5])
def test_money_fields_reject_negative_coerced_and_fractional_microdollars(
    amount: float,
) -> None:
    with pytest.raises(ValidationError):
        _ = CallReservation.model_validate(
            {
                "attempt": "one",
                "arm": "main",
                "account": "provider",
                "maximum_cost": amount,
            }
        )


def test_hydration_rejects_saved_exposure_above_the_cap(ledger: BudgetLedger) -> None:
    saved = ledger.model_dump()
    saved["reservations"] = (create_reservation("one", 25_000_001).model_dump(),)
    with pytest.raises(InvalidValueError, match="cap"):
        _ = BudgetLedger.model_validate(saved)


def test_saved_settlement_cannot_bypass_reference_validation(
    ledger: BudgetLedger,
) -> None:
    saved = ledger.model_dump()
    saved["settlements"] = (
        CallSettlement(attempt="unknown", actual_cost=0, evidence="bill").model_dump(),
    )
    with pytest.raises(InvalidValueError, match="coverage"):
        _ = BudgetLedger.model_validate(saved)


def test_allocated_arms_cannot_exceed_the_global_envelope(
    ledger: BudgetLedger,
) -> None:
    values = ledger.plan.model_dump()
    values["arms"] = (ArmCap(arm="main", cap=30_000_001),)
    with pytest.raises(InvalidValueError, match="allocations"):
        _ = BudgetPlan.model_validate(values)


def create_attributed_ledger() -> BudgetLedger:
    return BudgetLedger(
        plan=BudgetPlan(
            identifier="experiment-attribution-v1",
            confirmed=True,
            global_cap=30_000_000,
            arms=(ArmCap(arm="DI", cap=24_820_000), ArmCap(arm="HF", cap=3_280_000)),
            funding=(
                FundingCommitment(
                    account="deepinfra",
                    existing_credit=50_000_000,
                    committed=0,
                    usable_credit=0,
                ),
                FundingCommitment(
                    account="huggingface",
                    existing_credit=0,
                    committed=5_000_000,
                    usable_credit=5_000_000,
                ),
            ),
            other_costs=1_900_000,
        ),
        reservations=(),
        settlements=(),
    )


def test_operator_excluded_landed_hf_balance_counts_only_experiment_usage() -> None:
    ledger = create_attributed_ledger()
    data = ledger.model_dump(mode="json")
    data["plan"]["funding"][1].update(
        existing_credit=10_000_000, committed=0, usable_credit=0
    )
    ledger = BudgetLedger.model_validate(data)
    assert create_total_exposure(ledger) == 1_900_000
    used = create_reserved_ledger(
        ledger,
        (
            create_reservation("DI-call", 20_000_000, arm="DI", account="deepinfra"),
            create_reservation("HF-call", 1_000_000, arm="HF", account="huggingface"),
        ),
    )
    assert create_total_exposure(used) == 22_900_000


def test_existing_credit_excludes_unused_balance_but_counts_usage() -> None:
    ledger = create_attributed_ledger()
    assert create_total_exposure(ledger) == 6_900_000
    used = create_reserved_ledger(
        ledger,
        (
            create_reservation("DI-call", 20_000_000, arm="DI", account="deepinfra"),
            create_reservation("HF-call", 1_000_000, arm="HF", account="huggingface"),
        ),
    )
    assert create_total_exposure(used) == 26_900_000
    assert used.plan.funding[0].existing_credit == 50_000_000
    assert BudgetLedger.model_validate_json(used.model_dump_json()) == used
    settled = create_settled_ledger(
        used,
        CallSettlement(
            attempt="DI-call", actual_cost=18_000_000, evidence="verified-bill"
        ),
    )
    assert create_total_exposure(settled) == 24_900_000
    assert create_total_exposure(used) == 26_900_000


def test_new_purchase_counts_fully_even_when_unused_without_double_counting() -> None:
    ledger = create_attributed_ledger()
    assert create_total_exposure(ledger) == 6_900_000
    used = create_reserved_ledger(
        ledger,
        (create_reservation("HF-call", 3_280_000, arm="HF", account="huggingface"),),
    )
    assert create_total_exposure(used) == 6_900_000
    settled = create_settled_ledger(
        used,
        CallSettlement(
            attempt="HF-call", actual_cost=500_000, evidence="verified-hf-bill"
        ),
    )
    assert create_total_exposure(settled) == 6_900_000
    with pytest.raises(InvalidValueError, match="exceeds"):
        _ = FundingCommitment(
            account="huggingface",
            existing_credit=50_000_000,
            committed=0,
            usable_credit=5_000_000,
        )


def test_existing_credit_cannot_expand_the_global_cap_or_ignore_the_fee_reserve() -> (
    None
):
    ledger = create_attributed_ledger()
    full = create_reserved_ledger(
        ledger,
        (create_reservation("DI-call", 23_100_000, arm="DI", account="deepinfra"),),
    )
    assert create_total_exposure(full) == 30_000_000
    with pytest.raises(InvalidValueError, match="global cap"):
        _ = create_reserved_ledger(
            full,
            (create_reservation("one-micro-over", 1, arm="DI", account="deepinfra"),),
        )
    assert create_total_exposure(full) == 30_000_000


def test_existing_credit_cannot_cover_an_arm_overrun_on_the_new_purchase_account() -> (
    None
):
    ledger = create_attributed_ledger()
    with pytest.raises(InvalidValueError, match="Arm HF"):
        _ = create_reserved_ledger(
            ledger,
            (
                create_reservation(
                    "HF-overrun", 3_280_001, arm="HF", account="huggingface"
                ),
            ),
        )


@pytest.mark.parametrize("unknown", ["existing_credit", "committed"])
def test_unknown_credit_attribution_keeps_even_zero_cost_reservations_closed(
    unknown: str,
) -> None:
    ledger = create_attributed_ledger()
    funding = list(ledger.plan.funding)
    funding[0] = FundingCommitment.model_validate(
        {**funding[0].model_dump(), unknown: None}
    )
    plan = BudgetPlan.model_validate({**ledger.plan.model_dump(), "funding": funding})
    unknown_ledger = BudgetLedger(plan=plan, reservations=(), settlements=())
    assert create_total_exposure(unknown_ledger) is None
    with pytest.raises(InvalidValueError, match="unknown"):
        _ = create_reserved_ledger(
            unknown_ledger,
            (
                create_reservation(
                    "unknown-funded-call", 0, arm="DI", account="deepinfra"
                ),
            ),
        )


def test_missing_attribution_is_not_silently_inferred_during_saved_model_import() -> (
    None
):
    with pytest.raises(ValidationError, match="existing_credit"):
        _ = FundingCommitment.model_validate(
            {"account": "deepinfra", "committed": 0, "usable_credit": 0}
        )


def test_mixed_existing_and_new_credit_counts_purchase_then_only_uncovered_usage() -> (
    None
):
    ledger = create_attributed_ledger()
    funding = FundingCommitment(
        account="deepinfra",
        existing_credit=50_000_000,
        committed=5_500_000,
        usable_credit=5_000_000,
    )
    plan = BudgetPlan.model_validate(
        {**ledger.plan.model_dump(), "funding": (funding,), "other_costs": 0}
    )
    mixed = BudgetLedger(plan=plan, reservations=(), settlements=())
    used = create_reserved_ledger(
        mixed,
        (create_reservation("mixed-call", 8_000_000, arm="DI", account="deepinfra"),),
    )
    assert create_total_exposure(used) == 8_500_000
    assert create_resumed_ledger(used, used.plan) == used
    changed = BudgetPlan.model_validate(
        {
            **plan.model_dump(),
            "funding": (
                FundingCommitment(
                    account="deepinfra",
                    existing_credit=49_000_000,
                    committed=5_500_000,
                    usable_credit=5_000_000,
                ),
            ),
        }
    )
    with pytest.raises(InvalidValueError, match="changed"):
        _ = create_resumed_ledger(used, changed)
