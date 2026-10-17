"""Estimate costs and hours from explicit assumptions without claiming measurements."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from safety_judge.budget import BudgetPlan, TokenPrice, create_funding_exposure
from safety_judge.errors import InvalidValueError


class ArmAssumption(BaseModel, frozen=True, extra="forbid"):
    """Explicit full-token and attempt assumptions for one billed route.

    Attributes:
        arm: Allocation identity receiving all attempts, including retries.
        route: Exact serving model identity, not merely its family.
        stage: Sequential main/rewrite/review/rewritten pipeline stage.
        calls: Logical assigned calls before the attempt multiplier.
        attempts_per_call: One normally; two is the allowed worst-case ceiling.
        input_tokens_per_call: Complete input bound including templates/context.
        output_tokens_per_call: Complete billed output, including reasoning.
        tokens_verified: True only for established complete bounds; otherwise scenario.
        price: Explicit account-specific rate observations, potentially unknown.
        mean_latency_seconds: Assumed measured/scenario latency, absent if unknown.
        concurrent_calls: Explicit proposed route concurrency, never quota evidence.
        requests_per_minute: Account/route throughput ceiling, absent if unknown.
    """

    arm: str
    route: str
    stage: Literal["main", "rewrite", "review", "rewritten"]
    calls: Annotated[int, Field(ge=0, strict=True)]
    attempts_per_call: Annotated[int, Field(ge=1, le=2, strict=True)]
    input_tokens_per_call: Annotated[int, Field(ge=0, strict=True)]
    output_tokens_per_call: Annotated[int, Field(ge=0, strict=True)]
    tokens_verified: bool
    price: TokenPrice
    mean_latency_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None
    concurrent_calls: Annotated[int, Field(gt=0, le=128, strict=True)]
    requests_per_minute: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None


class EstimateInputs(BaseModel, frozen=True, extra="forbid"):
    """Scenario inputs keep purchases, usage, fees and review pauses distinct.

    Attributes:
        budget: All approved caps and actual or unknown purchase commitments.
        arms: Complete model-specific assumptions; no inferred prices or tokenizers.
        human_pause_hours: Separate manual review delay, unknown until supplied.
        latency_verified: Whether latencies are measured, rather than scenarios.
        quotas_verified: Whether all concurrent/RPM assumptions are established.
    """

    budget: BudgetPlan
    arms: tuple[ArmAssumption, ...]
    human_pause_hours: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
    latency_verified: bool = False
    quotas_verified: bool = False


class ArmEstimate(BaseModel, frozen=True, extra="forbid"):
    """Per-route conservative gross usage, with unverified inputs explicit.

    Attributes:
        arm: Owning allocation identity, possibly shared by rewritten models.
        route: Exact proposed model route.
        attempts: Maximum scenario transport attempts.
        gross_usage: Integer microdollars, absent if either billing rate is unknown.
        network_hours: Latency/RPM scenario bound, absent if latency is unknown.
        tokens_verified: Whether supplied full token bounds are established.
        price_confirmed: Whether billing metadata is confirmed.
    """

    arm: str
    route: str
    attempts: int
    gross_usage: int | None
    network_hours: float | None
    tokens_verified: bool
    price_confirmed: bool


class StudyEstimate(BaseModel, frozen=True, extra="forbid"):
    """Cost/runtime scenarios are planning evidence and never execution authority.

    Attributes:
        arms: Every route's input-derived usage and duration.
        arm_usage: Combined reservation totals per allocation, unknown preserved.
        arm_caps: Frozen approved ceilings for comparison.
        usage_plus_fees: Gross model usage plus all known non-account costs.
        other_costs: Explicit known fees/liabilities, or None when unknown.
        global_cap: Frozen all-cost ceiling in integer microdollars.
        existing_credit: Declared out-of-experiment balances, never a usage discount.
        purchase_commitments: New experiment purchases counted fully, or unknown.
        all_cost_exposure: Purchase commitments plus uncovered usage plus fees.
        within_all_caps: None for unknown costs; otherwise all-cost/arm fit.
        stage_hours: Parallel maximum per stage, then stages sum sequentially.
        network_hours: Total scenario network hours, absent when any input unknown.
        elapsed_hours: Network plus manual review delay, absent if unknown.
        execution_allowed: Always false: an estimator never authorizes dispatch.
        limitations: Missing evidence and scenario interpretation.
    """

    arms: tuple[ArmEstimate, ...]
    arm_usage: dict[str, int | None]
    arm_caps: dict[str, int]
    usage_plus_fees: int | None
    other_costs: int | None
    global_cap: int
    existing_credit: dict[str, int | None]
    purchase_commitments: dict[str, int | None]
    all_cost_exposure: int | None
    within_all_caps: bool | None
    stage_hours: dict[str, float | None]
    network_hours: float | None
    elapsed_hours: float | None
    execution_allowed: Literal[False] = False
    limitations: tuple[str, ...]


def create_arm_estimate(assumption: ArmAssumption) -> ArmEstimate:
    """Round complete token liability upward and apply latency/RPM hour assumptions.

    Args:
        assumption: Explicit route count, token prices and concurrency scenario.

    Returns:
        Cost and runtime, preserving unknown metadata instead of assuming zero.
    """
    attempts = assumption.calls * assumption.attempts_per_call
    price = assumption.price
    usage = None
    if price.input_per_million is not None and price.output_per_million is not None:
        numerator = (
            assumption.input_tokens_per_call * price.input_per_million
            + assumption.output_tokens_per_call * price.output_per_million
        )
        usage = attempts * ((numerator + 999_999) // 1_000_000)
    hours = None
    if assumption.mean_latency_seconds is not None:
        hours = (
            attempts
            * assumption.mean_latency_seconds
            / assumption.concurrent_calls
            / 3600
        )
        if assumption.requests_per_minute is not None:
            hours = max(hours, attempts / assumption.requests_per_minute / 60)
    return ArmEstimate(
        arm=assumption.arm,
        route=assumption.route,
        attempts=attempts,
        gross_usage=usage,
        network_hours=hours,
        tokens_verified=assumption.tokens_verified,
        price_confirmed=price.confirmed,
    )


def create_study_estimate(inputs: EstimateInputs) -> StudyEstimate:
    """Compare all scenario liabilities against every frozen cap and gross commitment.

    Args:
        inputs: Complete proposed model activities, funding and duration assumptions.

    Returns:
        Per-arm/global feasibility and hours, with execution always disabled.

    Raises:
        InvalidValueError: If assumptions omit an arm or use unknown accounts.
    """
    caps = {item.arm: item.cap for item in inputs.budget.arms}
    if {item.arm for item in inputs.arms} != set(caps) or any(
        item.price.account not in {fund.account for fund in inputs.budget.funding}
        for item in inputs.arms
    ):
        message = "Estimate omits an arm or account; supply every allocated activity."
        raise InvalidValueError(message)
    arms = tuple(create_arm_estimate(item) for item in inputs.arms)
    arm_usage = {
        name: None
        if any(item.gross_usage is None for item in arms if item.arm == name)
        else sum(item.gross_usage or 0 for item in arms if item.arm == name)
        for name in caps
    }
    gross = (
        None
        if inputs.budget.other_costs is None
        or any(item.gross_usage is None for item in arms)
        else inputs.budget.other_costs + sum(item.gross_usage or 0 for item in arms)
    )
    exposure = inputs.budget.other_costs
    for funding in inputs.budget.funding:
        account_items = tuple(
            result
            for assumption, result in zip(inputs.arms, arms, strict=True)
            if assumption.price.account == funding.account
        )
        if exposure is None or any(item.gross_usage is None for item in account_items):
            exposure = None
            break
        account_exposure = create_funding_exposure(
            funding, sum(item.gross_usage or 0 for item in account_items)
        )
        if account_exposure is None:
            exposure = None
            break
        exposure += account_exposure
    stages: dict[str, float | None] = {}
    for stage in ("main", "rewrite", "review", "rewritten"):
        members = tuple(
            result
            for assumption, result in zip(inputs.arms, arms, strict=True)
            if assumption.stage == stage
        )
        stages[stage] = (
            None
            if any(item.network_hours is None for item in members)
            else max((item.network_hours or 0 for item in members), default=0)
        )
    network = (
        None
        if any(value is None for value in stages.values())
        else sum(value or 0 for value in stages.values())
    )
    return StudyEstimate(
        arms=arms,
        arm_usage=arm_usage,
        arm_caps=caps,
        usage_plus_fees=gross,
        other_costs=inputs.budget.other_costs,
        global_cap=inputs.budget.global_cap,
        existing_credit={
            item.account: item.existing_credit for item in inputs.budget.funding
        },
        purchase_commitments={
            item.account: item.committed for item in inputs.budget.funding
        },
        all_cost_exposure=exposure,
        within_all_caps=None
        if exposure is None or any(value is None for value in arm_usage.values())
        else exposure <= inputs.budget.global_cap
        and all((arm_usage[name] or 0) <= cap for name, cap in caps.items()),
        stage_hours=stages,
        network_hours=network,
        elapsed_hours=None
        if network is None or inputs.human_pause_hours is None
        else network + inputs.human_pause_hours,
        limitations=(
            "Scenario inputs remain unverified until independently measured.",
            (
                "Parallel route maxima assume independently available quotas; "
                "shared account limits can make execution slower."
            ),
            "Sterling funds accounts manually; no automatic payment authority.",
        ),
    )
