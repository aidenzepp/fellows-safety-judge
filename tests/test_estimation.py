"""Cost and runtime scenarios preserve unknown funding and separate manual pauses."""

import pytest

from safety_judge.budget import ArmCap, BudgetPlan, FundingCommitment, TokenPrice
from safety_judge.estimation import ArmAssumption, EstimateInputs, create_study_estimate


def create_inputs(*, committed: int | None) -> EstimateInputs:
    return EstimateInputs(
        budget=BudgetPlan(
            identifier="synthetic",
            confirmed=False,
            global_cap=30_000_000,
            arms=(ArmCap(arm="main", cap=25_000_000),),
            funding=(
                FundingCommitment(
                    existing_credit=0,
                    account="test",
                    committed=committed,
                    usable_credit=0,
                ),
            ),
            other_costs=1_900_000,
        ),
        arms=(
            ArmAssumption(
                arm="main",
                route="synthetic-model",
                stage="main",
                calls=6555,
                attempts_per_call=1,
                input_tokens_per_call=1000,
                output_tokens_per_call=20,
                tokens_verified=False,
                price=TokenPrice(
                    account="test",
                    confirmed=False,
                    input_per_million=100_000,
                    output_per_million=200_000,
                ),
                mean_latency_seconds=10,
                concurrent_calls=16,
                requests_per_minute=None,
            ),
        ),
        human_pause_hours=None,
    )


def test_hours_and_token_liabilities_do_not_imply_funding() -> None:
    result = create_study_estimate(create_inputs(committed=None))
    assert result.arms[0].gross_usage == 681_720
    assert result.network_hours == 6555 * 10 / 16 / 3600
    assert result.elapsed_hours is None
    assert result.all_cost_exposure is None
    assert result.within_all_caps is None
    assert not result.execution_allowed


def test_known_commitments_and_fees_are_counted_in_full() -> None:
    result = create_study_estimate(create_inputs(committed=29_000_000))
    assert result.all_cost_exposure == 29_000_000 + 681_720 + 1_900_000
    assert result.within_all_caps is False


def create_attributed_inputs() -> EstimateInputs:
    original = create_inputs(committed=0)
    budget = BudgetPlan(
        identifier="attributed-scenario",
        confirmed=False,
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
    )
    arms = tuple(
        ArmAssumption.model_validate(
            {
                **original.arms[0].model_dump(),
                "arm": arm,
                "route": account,
                "calls": 1,
                "input_tokens_per_call": 1_000_000,
                "output_tokens_per_call": 0,
                "price": TokenPrice(
                    account=account,
                    confirmed=False,
                    input_per_million=charge,
                    output_per_million=0,
                ),
            }
        )
        for arm, account, charge in (
            ("DI", "deepinfra", 20_000_000),
            ("HF", "huggingface", 1_000_000),
        )
    )
    return EstimateInputs(budget=budget, arms=arms, human_pause_hours=None)


def test_estimator_uses_ledger_attribution_for_existing_credit_and_new_purchases() -> (
    None
):
    inputs = create_attributed_inputs()
    result = create_study_estimate(inputs)
    assert result.usage_plus_fees == 22_900_000
    assert result.all_cost_exposure == 26_900_000
    assert result.within_all_caps is True
    assert result.existing_credit == {"deepinfra": 50_000_000, "huggingface": 0}
    assert result.purchase_commitments == {"deepinfra": 0, "huggingface": 5_000_000}
    assert not result.execution_allowed


def test_estimator_rejects_global_excess_despite_existing_credit() -> None:
    inputs = create_attributed_inputs()
    price = TokenPrice(
        account="deepinfra",
        confirmed=False,
        input_per_million=23_100_001,
        output_per_million=0,
    )
    larger = ArmAssumption.model_validate(
        {**inputs.arms[0].model_dump(), "price": price}
    )
    result = create_study_estimate(
        EstimateInputs.model_validate(
            {**inputs.model_dump(), "arms": (larger, inputs.arms[1])}
        )
    )
    assert result.all_cost_exposure == 30_000_001
    assert result.within_all_caps is False


@pytest.mark.parametrize("unknown", ["existing_credit", "committed"])
def test_estimator_preserves_unknown_existing_credit_and_new_purchase_costs(
    unknown: str,
) -> None:
    inputs = create_attributed_inputs()
    funding = FundingCommitment.model_validate(
        {**inputs.budget.funding[0].model_dump(), unknown: None}
    )
    budget = BudgetPlan.model_validate(
        {**inputs.budget.model_dump(), "funding": (funding, inputs.budget.funding[1])}
    )
    result = create_study_estimate(
        EstimateInputs.model_validate({**inputs.model_dump(), "budget": budget})
    )
    assert result.all_cost_exposure is None
    assert result.within_all_caps is None
    assert not result.execution_allowed
