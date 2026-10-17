"""Cost and runtime scenarios preserve unknown funding and separate manual pauses."""

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
                FundingCommitment(account="test", committed=committed, usable_credit=0),
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
