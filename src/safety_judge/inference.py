"""Apply frozen approximate component bootstrap rules and explicit refusal."""

import math
import random
from collections import Counter
from typing import Final
lazy from collections.abc import Mapping

from pydantic import BaseModel

from safety_judge.analysis import (
    H1Analysis,
    LinearTarget,
    OutcomeTerm,
    create_completion_bounds,
)
from safety_judge.errors import InvalidValueError
from safety_judge.judging import JudgeRole

BOOTSTRAP_REPLICATES: Final = 9999
"""Frozen production simulation count; synthetic tests may supply shorter lists."""
BOOTSTRAP_SEED: Final = 2026101701
"""Frozen seed for Python Random MT19937 component-index draws."""
PRIMARY_ALPHA: Final = 0.025
"""Unchanged primary and four-secondary Holm family allocation."""
SECONDARY_BOUND_ALPHA: Final = 0.00625
"""Conservative simultaneous family lower-bound tail probability."""
EFFECT_BOUNDARY: Final = 0.05
"""Approved practical-effect null boundary, including equality in the null."""
PILOT_STRATUM_SIZE: Final = 8
"""Harmful pilot components drawn with replacement within each source stratum."""


class ComponentEndpoint(BaseModel, frozen=True, extra="forbid"):
    """Within-component endpoint contributions before source normalization.

    Attributes:
        component: Accepted linked component identity.
        source: Fixed generator role.
        lower: Lower completion contribution times original source support.
        upper: Upper completion contribution times original source support.
    """

    component: str
    source: JudgeRole
    lower: float
    upper: float


class BootstrapTarget(BaseModel, frozen=True, extra="forbid"):
    """An efficiently aggregated H1 target.

    Attributes:
        target: Original finite-data target and bounds.
        cells: Linear endpoint aggregates per component and source.
        components_by_source: Required source support, including zero-effect cells.
        components: Full eligible component resampling frame.
    """

    target: LinearTarget
    cells: tuple[ComponentEndpoint, ...]
    components_by_source: dict[JudgeRole, tuple[str, ...]]
    components: tuple[str, ...]


class EndpointReplicate(BaseModel, frozen=True, extra="forbid"):
    """A required paired lower/upper replicate, undefined if source support fails.

    Attributes:
        lower: Recomputed lower endpoint, absent for invalid replicates.
        upper: Recomputed upper endpoint, absent for invalid replicates.
        reason: Explicit invalidity reason, otherwise absent.
    """

    lower: float | None
    upper: float | None
    reason: str | None = None


class EndpointInference(BaseModel, frozen=True, extra="forbid"):
    """Assumption-conditional centered/basic inference or explicit refusal.

    Attributes:
        p_value: Raw p, or one for invalidity/multiplicity bookkeeping.
        lower_bound: Basic one-sided lower bound when inference is available.
        upper_bound: Descriptive basic upper bound using the upper endpoint.
        reason: Why uncertainty is unavailable, otherwise absent.
        alpha: Tail probability used for the basic bounds.
        boundary: Null boundary used for the centered test.
    """

    p_value: float
    lower_bound: float | None
    upper_bound: float | None
    reason: str | None
    alpha: float = PRIMARY_ALPHA
    boundary: float = EFFECT_BOUNDARY


def create_bootstrap_target(
    analysis: H1Analysis, target: LinearTarget
) -> BootstrapTarget:
    """Aggregate fixed-sign H1 endpoints once, avoiding row scans per replicate.

    Args:
        analysis: Supported H1 analysis with unique saved outcomes.
        target: One of that analysis's frozen targets.

    Returns:
        Component/source endpoint aggregates algebraically equivalent to copied rows.

    Raises:
        InvalidValueError: If the analysis is unsupported or outcomes are shared.
    """
    if analysis.undefined_reason is not None or target not in analysis.targets:
        message = "Bootstrap target lacks support. Supply a supported frozen H1 target."
        raise InvalidValueError(message)
    if len({term.variable_identifier for term in target.terms}) != len(target.terms):
        message = (
            "H1 saved outcomes repeat. Consolidate shared paired targets separately."
        )
        raise InvalidValueError(message)
    groups: dict[tuple[str, JudgeRole], list[OutcomeTerm]] = {}
    for term in target.terms:
        groups.setdefault((term.component_identifier, term.source), []).append(term)
    cells: list[ComponentEndpoint] = []
    for (component, source), terms in groups.items():
        bounds = create_completion_bounds(tuple(terms))
        support = len(analysis.harmful_components[source])
        cells.append(
            ComponentEndpoint(
                component=component,
                source=source,
                lower=bounds.lower * support,
                upper=bounds.upper * support,
            )
        )
    return BootstrapTarget(
        target=target,
        cells=tuple(cells),
        components_by_source=analysis.harmful_components,
        components=analysis.components,
    )


def create_component_replicate(
    prepared: BootstrapTarget, multiplicities: Mapping[str, int]
) -> EndpointReplicate:
    """Recompute copied-component source denominators using supplied multiplicity.

    Args:
        prepared: Preaggregated fixed-sign H1 target.
        multiplicities: Counts summing to the full component frame size.

    Returns:
        Recomputed endpoint pair or explicit missing-source-support refusal.

    """
    create_valid_multiplicities(prepared.components, multiplicities)
    denominators = {
        source: sum(multiplicities.get(component, 0) for component in components)
        for source, components in prepared.components_by_source.items()
    }
    if any(count == 0 for count in denominators.values()):
        return EndpointReplicate(
            lower=None,
            upper=None,
            reason="Replicate has absent harmful source support.",
        )
    lower = math.fsum(
        cell.lower * multiplicities.get(cell.component, 0) / denominators[cell.source]
        for cell in prepared.cells
    )
    upper = math.fsum(
        cell.upper * multiplicities.get(cell.component, 0) / denominators[cell.source]
        for cell in prepared.cells
    )
    return EndpointReplicate(lower=lower, upper=upper)


def create_valid_multiplicities(
    components: tuple[str, ...], multiplicities: Mapping[str, int]
) -> None:
    """Validate one full-frame component draw without touching random state.

    Args:
        components: Distinct accepted component frame.
        multiplicities: Sparse nonnegative integer counts summing to frame size.

    Raises:
        InvalidValueError: If the frame or counts cannot represent the required draw.
    """
    if (
        not components
        or len(set(components)) != len(components)
        or set(multiplicities) - set(components)
        or any(type(value) is not int or value < 0 for value in multiplicities.values())
        or sum(multiplicities.values()) != len(components)
    ):
        message = "Bootstrap copies are invalid. Supply one full known-component draw."
        raise InvalidValueError(message)


def select_component_multiplicities(
    components: tuple[str, ...], *, replicates: int = BOOTSTRAP_REPLICATES
) -> tuple[dict[str, int], ...]:
    """Draw full frames using local seeded MT19937 and randrange index sampling.

    The supplied tuple order is part of the frozen resampling frame. Python's
    Random/randrange implementation and interpreter version must be recorded.

    Args:
        components: Explicit ordered distinct component frame.
        replicates: Production default 9,999; smaller counts for synthetic checks.

    Returns:
        Sparse copied-component multiplicities, preserving every repeated draw.

    Raises:
        InvalidValueError: If the frame or requested replicate count is invalid.
    """
    if not components or len(set(components)) != len(components) or replicates < 1:
        message = (
            "Bootstrap frame is invalid. Supply distinct components and positive B."
        )
        raise InvalidValueError(message)
    generator = random.Random(BOOTSTRAP_SEED)  # noqa: S311 -- Statistical simulation only.
    return tuple(
        dict(
            Counter(
                components[generator.randrange(len(components))] for _ in components
            )
        )
        for _ in range(replicates)
    )


def create_nearest_rank(values: tuple[float, ...], probability: float) -> float:
    """Use the frozen ceil((B+1)p) rank, clipped to the observed range.

    Args:
        values: Finite simulated errors.
        probability: Quantile probability on the closed unit interval.

    Returns:
        The clipped nearest-rank ordered value.

    Raises:
        InvalidValueError: If values or probability are invalid.
    """
    if not values or not 0 <= probability <= 1 or not all(map(math.isfinite, values)):
        message = (
            "Quantile input is invalid. Supply finite errors and unit probability."
        )
        raise InvalidValueError(message)
    rank = max(1, min(len(values), math.ceil((len(values) + 1) * probability)))
    return sorted(values)[rank - 1]


def create_endpoint_inference(
    observed: EndpointReplicate,
    replicates: tuple[EndpointReplicate, ...],
    *,
    alpha: float = PRIMARY_ALPHA,
    boundary: float = EFFECT_BOUNDARY,
) -> EndpointInference:
    """Apply centered errors, simulation-corrected p and basic one-sided bounds.

    Any required invalid replicate or zero variance in either endpoint refuses
    uncertainty; no draws are removed. Small-B fixtures do not certify tail power.

    Args:
        observed: Observed finite lower and upper endpoints.
        replicates: Every supplied required draw, including invalid draws.
        alpha: Requested basic-bound tail probability.
        boundary: Null effect boundary, default frozen five percentage points.

    Returns:
        Approximate inference or p=1 with no finite bounds and an explicit reason.

    Raises:
        InvalidValueError: If alpha or the boundary is invalid.
    """
    if not 0 < alpha < 1 or not math.isfinite(boundary):
        message = (
            "Inference threshold is invalid. Supply finite boundary and unit alpha."
        )
        raise InvalidValueError(message)
    endpoints = (observed, *replicates)
    if not replicates or any(
        item.reason is not None
        or item.lower is None
        or item.upper is None
        or not math.isfinite(item.lower)
        or not math.isfinite(item.upper)
        for item in endpoints
    ):
        return EndpointInference(
            p_value=1,
            lower_bound=None,
            upper_bound=None,
            reason="A required endpoint is undefined or nonfinite.",
            alpha=alpha,
            boundary=boundary,
        )
    lower = tuple(item.lower for item in replicates if item.lower is not None)
    upper = tuple(item.upper for item in replicates if item.upper is not None)
    if len(set(lower)) == 1 or len(set(upper)) == 1:
        return EndpointInference(
            p_value=1,
            lower_bound=None,
            upper_bound=None,
            reason="Endpoint bootstrap variance is zero.",
            alpha=alpha,
            boundary=boundary,
        )
    if observed.lower is None or observed.upper is None:
        message = "Observed endpoints are absent. Supply finite descriptive bounds."
        raise InvalidValueError(message)
    errors = tuple(value - observed.lower for value in lower)
    upper_errors = tuple(value - observed.upper for value in upper)
    p_value = (1 + sum(error >= observed.lower - boundary for error in errors)) / (
        len(replicates) + 1
    )
    return EndpointInference(
        p_value=p_value,
        lower_bound=observed.lower - create_nearest_rank(errors, 1 - alpha),
        upper_bound=observed.upper - create_nearest_rank(upper_errors, alpha),
        reason=None,
        alpha=alpha,
        boundary=boundary,
    )


class H1Decisions(BaseModel, frozen=True, extra="forbid"):
    """The fixed gated primary and secondary decisions.

    Attributes:
        primary_rejected: Both fixed pooled requirements hold.
        secondary_rejected: Gated Holm plus conservative-bound requirements by judge.
        holm_adjusted_p: Four-family adjusted p-values, including invalid p=1 entries.
    """

    primary_rejected: bool
    secondary_rejected: dict[JudgeRole, bool]
    holm_adjusted_p: dict[JudgeRole, float]


def create_h1_decisions(
    primary: EndpointInference, secondary: Mapping[JudgeRole, EndpointInference]
) -> H1Decisions:
    """Apply roster-tied Holm and the unchanged conservative-bound primary gate.

    Secondary inputs must use alpha=.00625 basic bounds; primary uses .025.

    Args:
        primary: Pooled five-point test and .025 lower bound.
        secondary: All four tests and .00625 lower bounds, invalid tests retained.

    Returns:
        Fixed formal H1 decisions and adjusted secondary p-values.

    Raises:
        InvalidValueError: If a roster test is absent or a p-value is invalid.
    """
    if (
        primary.alpha != PRIMARY_ALPHA
        or primary.boundary != EFFECT_BOUNDARY
        or any(
            result.alpha != SECONDARY_BOUND_ALPHA or result.boundary != EFFECT_BOUNDARY
            for result in secondary.values()
        )
    ):
        message = (
            "Test tails differ from the protocol. "
            "Use .025 primary and .00625 secondary."
        )
        raise InvalidValueError(message)
    if set(secondary) != set(JudgeRole) or any(
        not 0 <= result.p_value <= 1 for result in (primary, *secondary.values())
    ):
        message = "Hypothesis family is incomplete. Retain all four tests, using p=1."
        raise InvalidValueError(message)
    primary_rejected = (
        create_effective_p_value(primary) <= PRIMARY_ALPHA
        and primary.reason is None
        and primary.p_value <= PRIMARY_ALPHA
        and primary.lower_bound is not None
        and primary.lower_bound > EFFECT_BOUNDARY
    )
    ordered = sorted(
        JudgeRole,
        key=lambda role: (
            create_effective_p_value(secondary[role]),
            tuple(JudgeRole).index(role),
        ),
    )
    adjusted: dict[JudgeRole, float] = {}
    running = 0.0
    for index, role in enumerate(ordered):
        running = max(
            running, (len(ordered) - index) * create_effective_p_value(secondary[role])
        )
        adjusted[role] = min(1, running)
    rejected: dict[JudgeRole, bool] = {}
    for role in JudgeRole:
        result = secondary[role]
        rejected[role] = (
            primary_rejected
            and adjusted[role] <= PRIMARY_ALPHA
            and result.reason is None
            and result.lower_bound is not None
            and result.lower_bound > EFFECT_BOUNDARY
        )
    return H1Decisions(
        primary_rejected=primary_rejected,
        secondary_rejected=rejected,
        holm_adjusted_p=adjusted,
    )


class PairedPilot(BaseModel, frozen=True, extra="forbid"):
    """Exploratory paired targets retaining shared saved-variable identities.

    Attributes:
        original: Signed original Delta on the 32 harmful pilot rows.
        rewrite: Signed rewritten Delta using identical pilot weights.
        reduction: Original minus rewrite, consolidated before completion bounds.
        absolute_gap_change: Absolute-gap reduction when both gaps are known.
        sign_reversal: Whether known original and residual gaps have opposite signs.
        strata: Four ordered source strata, each containing eight components.
    """

    original: LinearTarget
    rewrite: LinearTarget
    reduction: LinearTarget
    absolute_gap_change: float | None
    sign_reversal: bool | None
    strata: dict[JudgeRole, tuple[str, ...]]


def create_paired_pilot(original: H1Analysis, rewrite: H1Analysis) -> PairedPilot:
    """Combine saved-original and rewrite Delta terms before missing completions.

    Args:
        original: Pilot-only original analysis, preserving saved identities.
        rewrite: Same rows/components/weights with rewritten terminal outcomes.

    Returns:
        Exploratory signed paired targets and absolute-gap diagnostics; no test.

    Raises:
        InvalidValueError: If harmful quotas, pairing or weights differ.
    """
    if (
        original.undefined_reason is not None
        or rewrite.undefined_reason is not None
        or original.row_weights != rewrite.row_weights
        or original.harmful_components != rewrite.harmful_components
        or any(
            len(ids) != PILOT_STRATUM_SIZE
            for ids in original.harmful_components.values()
        )
        or len(
            {
                component
                for ids in original.harmful_components.values()
                for component in ids
            }
        )
        != PILOT_STRATUM_SIZE * len(JudgeRole)
        or len(original.row_weights) != PILOT_STRATUM_SIZE * len(JudgeRole)
    ):
        message = (
            "Pilot pairing is invalid. Supply the same eight harmful rows per source."
        )
        raise InvalidValueError(message)
    first, second = original.targets[0], rewrite.targets[0]
    terms = first.terms + tuple(
        term.model_copy(update={"coefficient": -term.coefficient})
        for term in second.terms
    )
    reduction = LinearTarget(
        name="A", terms=terms, bounds=create_completion_bounds(terms)
    )
    first_point, second_point = first.bounds.point, second.bounds.point
    return PairedPilot(
        original=first,
        rewrite=second,
        reduction=reduction,
        absolute_gap_change=abs(first_point) - abs(second_point)
        if first_point is not None and second_point is not None
        else None,
        sign_reversal=first_point * second_point < 0
        if first_point is not None and second_point is not None
        else None,
        strata=original.harmful_components,
    )


def select_pilot_multiplicities(
    pilot: PairedPilot, *, replicates: int = BOOTSTRAP_REPLICATES
) -> tuple[dict[str, int], ...]:
    """Draw eight of eight independently within the four harmful generator strata.

    Uses local Python Random MT19937, fixed roster order and randrange draws.
    Benign pilot components are absent from this resampling frame.

    Args:
        pilot: Validated paired harmful pilot.
        replicates: Production default 9,999; smaller counts for synthetic fixtures.

    Returns:
        Paired multiplicities shared by original, rewrite and reduction endpoints.

    Raises:
        InvalidValueError: If B is not positive.
    """
    if replicates < 1:
        message = "Pilot replicate count is invalid. Supply positive B."
        raise InvalidValueError(message)
    generator = random.Random(BOOTSTRAP_SEED)  # noqa: S311 -- Statistical simulation only.
    return tuple(
        dict(
            Counter(
                pilot.strata[source][generator.randrange(PILOT_STRATUM_SIZE)]
                for source in JudgeRole
                for _ in range(PILOT_STRATUM_SIZE)
            )
        )
        for _ in range(replicates)
    )


def create_pilot_replicates(
    pilot: PairedPilot, multiplicities: Mapping[str, int]
) -> tuple[EndpointReplicate, EndpointReplicate, EndpointReplicate]:
    """Recompute all exploratory paired endpoints using exactly the same copies.

    Args:
        pilot: Validated original/rewrite/reduction targets.
        multiplicities: Eight copied components per source stratum.

    Returns:
        Original, rewritten and signed-reduction endpoint pairs without inference.

    Raises:
        InvalidValueError: If a stratum draw differs from the fixed eight of eight.
    """
    frame = tuple(component for ids in pilot.strata.values() for component in ids)
    create_valid_multiplicities(frame, multiplicities)
    if any(
        sum(multiplicities.get(component, 0) for component in ids) != PILOT_STRATUM_SIZE
        for ids in pilot.strata.values()
    ):
        message = "Pilot draw breaks a quota. Supply eight copies within every source."
        raise InvalidValueError(message)
    results: list[EndpointReplicate] = []
    for target in (pilot.original, pilot.rewrite, pilot.reduction):
        terms = tuple(
            term.model_copy(
                update={
                    "coefficient": term.coefficient
                    * multiplicities.get(term.component_identifier, 0)
                }
            )
            for term in target.terms
        )
        bounds = create_completion_bounds(terms)
        results.append(EndpointReplicate(lower=bounds.lower, upper=bounds.upper))
    return results[0], results[1], results[2]


class DescriptiveUncertainty(BaseModel, frozen=True, extra="forbid"):
    """Exploratory basic bootstrap uncertainty with no p-value or success decision.

    Attributes:
        lower: Descriptive lower basic bound, absent upon refusal.
        upper: Descriptive upper basic bound, absent upon refusal.
        alpha: Explicit caller-selected tail probability for descriptive bounds.
        reason: Invalidity or degeneracy reason, otherwise absent.
    """

    lower: float | None
    upper: float | None
    alpha: float
    reason: str | None


def create_descriptive_uncertainty(
    observed: EndpointReplicate,
    replicates: tuple[EndpointReplicate, ...],
    *,
    alpha: float,
) -> DescriptiveUncertainty:
    """Summarize paired exploratory endpoints without an H2 hypothesis test.

    Args:
        observed: Finite pilot endpoint pair.
        replicates: Every same-pair stratified bootstrap endpoint for this target.
        alpha: Explicit descriptive tail probability; no confirmatory allocation.

    Returns:
        Descriptive basic uncertainty or an explicit undefined/zero-variance refusal.

    Raises:
        InvalidValueError: If alpha is not strictly within the unit interval.
    """
    if not 0 < alpha < 1:
        message = (
            "Descriptive tail is invalid. Supply alpha strictly between zero and one."
        )
        raise InvalidValueError(message)
    if not replicates or any(
        item.reason is not None
        or item.lower is None
        or item.upper is None
        or not math.isfinite(item.lower)
        or not math.isfinite(item.upper)
        for item in (observed, *replicates)
    ):
        return DescriptiveUncertainty(
            lower=None,
            upper=None,
            alpha=alpha,
            reason="Required paired endpoint is undefined.",
        )
    lower = tuple(item.lower for item in replicates if item.lower is not None)
    upper = tuple(item.upper for item in replicates if item.upper is not None)
    if len(set(lower)) == 1 or len(set(upper)) == 1:
        return DescriptiveUncertainty(
            lower=None,
            upper=None,
            alpha=alpha,
            reason="Paired endpoint bootstrap variance is zero.",
        )
    if observed.lower is None or observed.upper is None:
        message = "Observed pilot is undefined. Retain descriptive finite bounds only."
        raise InvalidValueError(message)
    lower_errors = tuple(value - observed.lower for value in lower)
    upper_errors = tuple(value - observed.upper for value in upper)
    return DescriptiveUncertainty(
        lower=observed.lower - create_nearest_rank(lower_errors, 1 - alpha),
        upper=observed.upper - create_nearest_rank(upper_errors, alpha),
        alpha=alpha,
        reason=None,
    )


def create_effective_p_value(result: EndpointInference) -> float:
    """Retain invalid/unrun targets as p=1 in the fixed hypothesis family.

    Args:
        result: A target's approximate inference or explicit refusal.

    Returns:
        Raw p only for finite available bounds, otherwise one for bookkeeping.
    """
    if (
        result.reason is not None
        or result.lower_bound is None
        or result.upper_bound is None
        or not math.isfinite(result.lower_bound)
        or not math.isfinite(result.upper_bound)
    ):
        return 1
    return result.p_value
