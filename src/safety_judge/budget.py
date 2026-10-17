"""Pure all-cost admission and replay contracts; persistence belongs to the caller.

Persist the returned reservation before dispatch. An interrupted or unknown delivery
retains its entire reservation. Only verified billing evidence can release money.
All amounts are integer microdollars. Existing credit pays for usage without
making that usage free; new experiment purchases count in full, including unused
credit, without counting purchased-credit consumption twice.
"""

from typing import Annotated, Self

from pydantic import BaseModel, Field, model_validator

from safety_judge.errors import InvalidValueError

type Microdollars = Annotated[int, Field(ge=0, strict=True)]
"""Nonnegative integer millionths of one US dollar."""

type BudgetName = Annotated[str, Field(min_length=1, strict=True)]
"""A nonempty durable arm, account, attempt, or plan key."""


class ArmCap(BaseModel, frozen=True, extra="forbid"):
    """An explicitly allocated cap on gross arm usage, including pending calls.

    Attributes:
        arm: Stable allocation identity.
        cap: Maximum gross usage in microdollars.
    """

    arm: BudgetName
    cap: Microdollars


class FundingCommitment(BaseModel, frozen=True, extra="forbid"):
    """One account's existing credit and experiment-attributable purchases.

    Existing credit was acquired outside this experiment: its unused balance is
    excluded, but experiment usage paid from it counts at the frozen token rates.
    ``committed`` includes only new experiment purchases, fees, taxes and renewals.
    Those purchases count fully even if unused. Only credit from these counted
    purchases can offset usage already paid for, never arm caps or other accounts.
    Unknown balances or purchase obligations use ``None`` and prevent admission.

    Attributes:
        account: Account whose liability and credit are inseparable.
        existing_credit: Verified credit acquired outside this experiment, or None.
        committed: New experiment purchase commitments, or None when unknown.
        usable_credit: Remaining credit from those counted experiment purchases.
    """

    account: BudgetName
    existing_credit: Microdollars | None
    committed: Microdollars | None
    usable_credit: Microdollars

    @model_validator(mode="after")
    def create_validated_credit(self) -> Self:
        """Reject credit that would offset uncounted spending.

        Returns:
            This immutable commitment.

        Raises:
            InvalidValueError: If credit exceeds a known purchase commitment.
        """
        if self.committed is not None and self.usable_credit > self.committed:
            message = "Usable credit exceeds its counted commitment; correct funding."
            raise InvalidValueError(message)
        return self


class BudgetPlan(BaseModel, frozen=True, extra="forbid"):
    """Explicit operator-confirmed allocation; a proposal cannot fund attempts.

    ``other_costs`` includes all non-account fees, taxes and liabilities. ``None``
    means unknown, never zero. Every arm/account must be declared even at zero.
    Plan identity and content must match when resuming a saved ledger.

    Attributes:
        identifier: Frozen configuration identity, including price/token manifest.
        confirmed: Explicit confirmation of the complete plan.
        global_cap: All-cost ceiling, at most thirty US dollars.
        arms: Complete nonoverlapping allocations for billed activities.
        funding: All accounts with credit commitments and outstanding obligations.
        other_costs: Non-account fees/liabilities, or None when unknown.
    """

    identifier: BudgetName
    confirmed: Annotated[bool, Field(strict=True)]
    global_cap: Annotated[int, Field(ge=0, le=30_000_000, strict=True)]
    arms: tuple[ArmCap, ...]
    funding: tuple[FundingCommitment, ...]
    other_costs: Microdollars | None

    @model_validator(mode="after")
    def create_validated_allocations(self) -> Self:
        """Reject duplicate allocations or allocations larger than the envelope.

        Returns:
            This immutable plan.

        Raises:
            InvalidValueError: If allocations are ambiguous or exceed the cap.
        """
        if (
            len({arm.arm for arm in self.arms}) != len(self.arms)
            or len({item.account for item in self.funding}) != len(self.funding)
            or sum(arm.cap for arm in self.arms) > self.global_cap
        ):
            message = "Budget allocations conflict; use unique keys within the cap."
            raise InvalidValueError(message)
        return self


class TokenPrice(BaseModel, frozen=True, extra="forbid"):
    """Confirmed account-specific microdollars per million billed tokens.

    Missing prices and confirmation remain explicit; zero is valid only when
    explicitly supplied and confirmed. Include all billed token classes in the
    input/output upper bounds, including reasoning, templates and caching rules.

    Attributes:
        account: Account whose confirmed rate schedule applies.
        confirmed: Whether the caller has established current complete pricing.
        input_per_million: Input billing rate, or None when missing.
        output_per_million: Output billing rate, or None when missing.
    """

    account: BudgetName
    confirmed: Annotated[bool, Field(strict=True)]
    input_per_million: Microdollars | None
    output_per_million: Microdollars | None


class CallReservation(BaseModel, frozen=True, extra="forbid"):
    """One unique attempt's worst-case cost; retries require another identifier.

    Attributes:
        attempt: Durable transport-attempt identity.
        arm: Allocation funding this attempt.
        account: Account incurring this attempt's charge.
        maximum_cost: Complete conservative upper bound in microdollars.
    """

    attempt: BudgetName
    arm: BudgetName
    account: BudgetName
    maximum_cost: Microdollars


class CallSettlement(BaseModel, frozen=True, extra="forbid"):
    """Verified final billing for an attempt, with durable evidence identity.

    Zero is allowed only with evidence that no charge is outstanding. A network
    error, timeout, missing response or missing usage is not such evidence.

    Attributes:
        attempt: Previously reserved attempt being reconciled.
        actual_cost: Verified final all-inclusive usage charge in microdollars.
        evidence: Durable identity of the billing/no-delivery evidence.
    """

    attempt: BudgetName
    actual_cost: Microdollars
    evidence: BudgetName


class BudgetLedger(BaseModel, frozen=True, extra="forbid"):
    """Replayable ledger retaining all attempts and terminal billing evidence.

    ``reservations`` includes dispatched, undispatched and uncertain attempts;
    pending amounts count in full. Settled attempts count their final bill.
    Hydration rechecks every invariant; do not bypass validation with model_copy
    or model_construct. The caller serializes and atomically persists transitions.

    Attributes:
        plan: Frozen authority and full allocation/commitment configuration.
        reservations: Every attempt's original worst-case liability.
        settlements: Verified terminal bills, at most one per attempt.
    """

    plan: BudgetPlan
    reservations: tuple[CallReservation, ...]
    settlements: tuple[CallSettlement, ...]

    @model_validator(mode="after")
    def create_validated_ledger(self) -> Self:
        """Validate references, final bills and caps, including on crash replay.

        Returns:
            This immutable ledger.

        Raises:
            InvalidValueError: If records conflict, obligations are unknown or
                monetary exposure exceeds an arm or the global ceiling.
        """
        reservations = {item.attempt: item for item in self.reservations}
        settlements = {item.attempt: item for item in self.settlements}
        if len(reservations) != len(self.reservations) or len(settlements) != len(
            self.settlements
        ):
            message = "Duplicate ledger attempts; replay each durable record once."
            raise InvalidValueError(message)
        for item in self.settlements:
            reservation = reservations.get(item.attempt)
            if reservation is None or item.actual_cost > reservation.maximum_cost:
                message = "Settlement lacks coverage; retain liability and reconcile."
                raise InvalidValueError(message)
        return self

    @model_validator(mode="after")
    def create_validated_exposure(self) -> Self:
        """Enforce funding authority and all arm/global exposure ceilings.

        Returns:
            This immutable ledger.

        Raises:
            InvalidValueError: If caps or confirmed funding are insufficient.
        """
        settlements = {item.attempt: item for item in self.settlements}
        arm_caps = {item.arm: item.cap for item in self.plan.arms}
        accounts = {item.account for item in self.plan.funding}
        for item in self.reservations:
            if item.arm not in arm_caps or item.account not in accounts:
                message = "Attempt uses an undeclared arm/account; correct the plan."
                raise InvalidValueError(message)
        for arm, cap in arm_caps.items():
            exposure = sum(
                settlements[item.attempt].actual_cost
                if item.attempt in settlements
                else item.maximum_cost
                for item in self.reservations
                if item.arm == arm
            )
            if exposure > cap:
                message = f"Arm {arm} exceeds its cap; stop dispatch and reconcile."
                raise InvalidValueError(message)
        if self.reservations and not self.plan.confirmed:
            message = "Plan is unconfirmed; obtain confirmation before reserving."
            raise InvalidValueError(message)
        total = create_total_exposure(self)
        if total is None:
            if self.reservations:
                message = "Costs are unknown; resolve them before reserving."
                raise InvalidValueError(message)
        elif total > self.plan.global_cap:
            message = "All-cost exposure exceeds the global cap; stop and reconcile."
            raise InvalidValueError(message)
        return self


def create_funding_exposure(funding: FundingCommitment, usage: int) -> int | None:
    """Count experiment purchases fully and existing-credit usage at its charge.

    Args:
        funding: Explicit existing-credit and new experiment-purchase attribution.
        usage: Nonnegative settled charges plus outstanding worst-case liability.

    Returns:
        Attributable microdollars, or None for an unknown funding fact. Existing
        credit never offsets usage; counted purchases offset only their own usage.

    Raises:
        InvalidValueError: If usage is not a nonnegative integer microdollar amount.
    """
    if type(usage) is not int or usage < 0:
        message = "Usage must be nonnegative integer microdollars; correct attribution."
        raise InvalidValueError(message)
    if funding.existing_credit is None or funding.committed is None:
        return None
    return funding.committed + max(0, usage - funding.usable_credit)


def create_total_exposure(ledger: BudgetLedger) -> int | None:
    """Calculate experiment purchases plus usage not covered by those purchases.

    Args:
        ledger: Immutable reservations, settlements and funding commitments.

    Returns:
        Conservative microdollar exposure, or None for an unknown obligation.
    """
    if ledger.plan.other_costs is None:
        return None
    total = ledger.plan.other_costs
    settlements = {item.attempt: item.actual_cost for item in ledger.settlements}
    for funding in ledger.plan.funding:
        usage = sum(
            settlements.get(item.attempt, item.maximum_cost)
            for item in ledger.reservations
            if item.account == funding.account
        )
        account_exposure = create_funding_exposure(funding, usage)
        if account_exposure is None:
            return None
        total += account_exposure
    return total


def create_call_reservation(
    *,
    attempt: str,
    arm: str,
    price: TokenPrice,
    maximum_input_tokens: int,
    maximum_output_tokens: int,
) -> CallReservation:
    """Round worst-case token charges upward to an integer microdollar.

    Args:
        attempt: New durable identity for this specific transport attempt.
        arm: Explicit arm receiving this charge.
        price: Confirmed complete token rates for the intended account.
        maximum_input_tokens: Complete nonnegative input billing bound.
        maximum_output_tokens: Complete nonnegative output billing bound.

    Returns:
        Worst-case reservation, still requiring atomic ledger admission.

    Raises:
        InvalidValueError: If prices are missing/unconfirmed or bounds invalid.
    """
    if (
        not price.confirmed
        or price.input_per_million is None
        or price.output_per_million is None
        or type(maximum_input_tokens) is not int
        or type(maximum_output_tokens) is not int
        or maximum_input_tokens < 0
        or maximum_output_tokens < 0
    ):
        message = "Call cost is unbounded; confirm rates and complete token bounds."
        raise InvalidValueError(message)
    numerator = (
        maximum_input_tokens * price.input_per_million
        + maximum_output_tokens * price.output_per_million
    )
    return CallReservation(
        attempt=attempt,
        arm=arm,
        account=price.account,
        maximum_cost=(numerator + 999_999) // 1_000_000,
    )


def create_reserved_ledger(
    ledger: BudgetLedger, reservations: tuple[CallReservation, ...]
) -> BudgetLedger:
    """Admit a whole row/batch atomically, or retain the unchanged prior ledger.

    Args:
        ledger: Last durable snapshot, including all outstanding attempts.
        reservations: Distinct new attempt reservations; retries use new keys.

    Returns:
        New immutable snapshot to persist before any associated network call.

    Admission propagates InvalidValueError for any plan or cap violation.
    """
    return BudgetLedger(
        plan=ledger.plan,
        reservations=ledger.reservations + reservations,
        settlements=ledger.settlements,
    )


def create_settled_ledger(
    ledger: BudgetLedger, settlement: CallSettlement
) -> BudgetLedger:
    """Release only verified unused liability, idempotently on identical replay.

    Args:
        ledger: Snapshot retaining the original worst-case reservation.
        settlement: Evidence-backed final bill for a known attempt.

    Returns:
        New snapshot, or the same snapshot for an identical settlement replay.

    Raises:
        InvalidValueError: If evidence conflicts or billing exceeds reservation.
    """
    for previous in ledger.settlements:
        if previous.attempt == settlement.attempt:
            if previous == settlement:
                return ledger
            message = "Settlement replay conflicts; reconcile billing evidence."
            raise InvalidValueError(message)
    return BudgetLedger(
        plan=ledger.plan,
        reservations=ledger.reservations,
        settlements=(*ledger.settlements, settlement),
    )


def create_resumed_ledger(
    ledger: BudgetLedger, expected_plan: BudgetPlan
) -> BudgetLedger:
    """Refuse changed configuration and preserve unknown-delivery liabilities.

    Args:
        ledger: Validated snapshot read from the durable journal.
        expected_plan: Exact current confirmed configuration, including rates'
            allocation identity supplied by the orchestrator.

    Returns:
        Original snapshot with every outstanding reservation retained.

    Raises:
        InvalidValueError: If the saved and requested plans differ.
    """
    if ledger.plan != expected_plan:
        message = "Saved plan changed; reconcile liabilities before resuming."
        raise InvalidValueError(message)
    return ledger
