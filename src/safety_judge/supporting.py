"""Supporting weighting and additive fits, never replacements for primary H1."""

import math
from collections import Counter
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
from pydantic import BaseModel
lazy from numpy.typing import NDArray

from safety_judge.analysis import (
    ROSTER_WEIGHTS,
    LinearTarget,
    OutcomeTerm,
    SavedJudgment,
    create_completion_bounds,
    create_judgment_lookup,
    create_row_weights,
    create_same_family,
    create_source_role,
)
from safety_judge.coin_flip import HARMFUL_REFERENCE_MINIMUM, EligibleResponse
from safety_judge.errors import InvalidValueError
from safety_judge.judging import JudgeRole

EQUAL_ROSTER_WEIGHTS: Final = dict.fromkeys(JudgeRole, 1 / len(JudgeRole))
"""Equal nominal-role margins, giving Gemma one half of each roster's mass."""

ADDITIVE_WEIGHT_DEFINITION: Final = (
    "Complete-case harmful rows only; recompute q_i=1/(K_g*A_gC*n_gCa) on that "
    "subset; observation weight w_ji=q_i*u_j*v_g with fixed family-balanced u/v."
)
"""The precise WLS weighting population and measure, totaling one with full support."""

ADDITIVE_MODEL_DEFINITION: Final = (
    "Binary benign prediction = item fixed effect + judge-by-original-ordinal "
    "categorical effects + judge-by-attack categorical effects + beta*own-family. "
    "Weighted within-item demeaning precedes SVD nuisance projection; beta exists "
    "only if the own-family predictor has a numerically nonzero nuisance-orthogonal "
    "residual. No p-value or confirmatory alpha."
)
"""Supporting additive specification, which cannot identify intrinsic causal bias."""

SELECTION_LIMITATION: Final = (
    "Complete-case selection can change the target population and select on judge "
    "failure; this supporting fit cannot repair or rescue primary H1."
)
"""A required interpretation limit whenever complete-case fitting is shown."""


type FloatingArray = NDArray[np.float64]
"""An internal NumPy float64 array; shape is established by the design constructor."""


class WeightingSensitivity(BaseModel, frozen=True, extra="forbid"):
    """A supporting own/outside contrast with explicitly normalized joint weights.

    Attributes:
        name: Raw-row or equal-four-roster variant identifier.
        weight_definition: Exact q/u/v and joint normalization definition.
        row_weights: Harmful response q weights, identical for every judge.
        judge_weights: Nominal judge margin.
        generator_weights: Nominal generator margin.
        own_family_mass: Sum u_j*v_g over same-family cells before normalization.
        outside_family_mass: Complementary joint mass before normalization.
        target: Sharp-bound supporting contrast, absent without full source support.
        valid_harmful_assignments: Valid harmful terminal predictions.
        assigned_harmful_judgments: All four assigned judgments for every harmful row.
        reason: Explicit absent-source-support reason, otherwise absent.
        limitation: Why the variant cannot replace primary inference.
    """

    name: Literal["raw_row_within_source", "equal_four_roster"]
    weight_definition: str
    row_weights: dict[str, float]
    judge_weights: dict[JudgeRole, float]
    generator_weights: dict[JudgeRole, float]
    own_family_mass: float
    outside_family_mass: float
    target: LinearTarget | None
    valid_harmful_assignments: int
    assigned_harmful_judgments: int
    reason: str | None
    limitation: str


def create_weighting_sensitivities(
    rows: tuple[EligibleResponse, ...], judgments: tuple[SavedJudgment, ...]
) -> tuple[WeightingSensitivity, WeightingSensitivity]:
    """Compute the two supporting variants with all assigned unknowns retained.

    Raw-row q is uniform within harmful source, keeping primary family u/v.
    Equal-four uses primary component/attack q and u=v=1/4; joint own mass is
    3/8 and outside mass 5/8. Its own/outside source margins differ, so primary
    additive-margin cancellation does not extend to this descriptive variant.

    Args:
        rows: Accepted original eligible records, including benign cases.
        judgments: Complete four-judge matrix, including unresolved assignments.

    Returns:
        Raw-row then equal-four supporting contrasts and exact weight definitions.
    """
    lookup = create_judgment_lookup(rows, judgments)
    balanced_q = create_row_weights(rows)
    harmful = tuple(row for row in rows if row.harmful)
    counts = Counter(create_source_role(row) for row in harmful)
    raw_q = {row.identifier: 1 / counts[create_source_role(row)] for row in harmful}
    raw = create_weighting_sensitivity(
        harmful,
        lookup,
        name="raw_row_within_source",
        row_weights=raw_q,
    )
    equal = create_weighting_sensitivity(
        harmful,
        lookup,
        name="equal_four_roster",
        row_weights=balanced_q,
    )
    return raw, equal


def create_weighting_sensitivity(
    harmful: tuple[EligibleResponse, ...],
    lookup: dict[tuple[str, JudgeRole], SavedJudgment],
    *,
    name: Literal["raw_row_within_source", "equal_four_roster"],
    row_weights: dict[str, float],
) -> WeightingSensitivity:
    """Expand one explicitly weighted supporting own/outside contrast.

    Args:
        harmful: All original harmful-reference rows, including unresolved cases.
        lookup: Validated complete terminal assignments.
        name: Supporting variant identifier.
        row_weights: Explicit within-source row measure.

    Returns:
        Fixed-normalization supporting contrast with sharp unknown completions.
    """
    if name == "raw_row_within_source":
        margins = ROSTER_WEIGHTS
        weight_definition = (
            "q_i=1/n_g among all harmful rows from source g; "
            "u=v=(1/6,1/6,1/3,1/3); own-family joint mass=1/3, outside=2/3; "
            "c_ji=q_i*u_j*v_g*(I_same/(1/3)-I_outside/(2/3))."
        )
        limitation = (
            "Raw rows can overrepresent components/attacks with more rows; "
            "all unknown assignments remain in sharp bounds; supporting only."
        )
    else:
        margins = EQUAL_ROSTER_WEIGHTS
        weight_definition = (
            "q_i=1/(K_g*A_gC*n_gCa) over all harmful rows; "
            "u=v=(1/4,1/4,1/4,1/4); own-family joint mass=3/8, outside=5/8; "
            "c_ji=q_i*u_j*v_g*(I_same/(3/8)-I_outside/(5/8))."
        )
        limitation = (
            "Gemma has half the roster mass; own/outside source/judge margins "
            "differ, so shared additive effects need not cancel; supporting only."
        )
    own_mass = math.fsum(
        margins[judge] * margins[source]
        for judge in JudgeRole
        for source in JudgeRole
        if create_same_family(judge, source)
    )
    outside_mass = 1 - own_mass
    source_support = {create_source_role(row) for row in harmful}
    terms: list[OutcomeTerm] = []
    valid = 0
    for row in harmful:
        source = create_source_role(row)
        for judge in JudgeRole:
            outcome = lookup[row.identifier, judge].outcome
            known = outcome.kind == "judgment"
            valid += int(known)
            coefficient = row_weights[row.identifier] * margins[judge] * margins[source]
            coefficient *= (
                1 / own_mass if create_same_family(judge, source) else -1 / outside_mass
            )
            terms.append(
                OutcomeTerm(
                    variable_identifier=lookup[
                        row.identifier, judge
                    ].variable_identifier,
                    coefficient=coefficient,
                    value=int(outcome.ordinal < HARMFUL_REFERENCE_MINIMUM)
                    if outcome.kind == "judgment"
                    else None,
                    component_identifier=row.component_identifier,
                    source=source,
                )
            )
    supported = source_support == set(JudgeRole)
    frozen_terms = tuple(terms)
    return WeightingSensitivity(
        name=name,
        weight_definition=weight_definition,
        row_weights=row_weights,
        judge_weights=margins,
        generator_weights=margins,
        own_family_mass=own_mass,
        outside_family_mass=outside_mass,
        target=LinearTarget(
            name=name, terms=frozen_terms, bounds=create_completion_bounds(frozen_terms)
        )
        if supported
        else None,
        valid_harmful_assignments=valid,
        assigned_harmful_judgments=len(harmful) * len(JudgeRole),
        reason=None if supported else "A generator has absent harmful source support.",
        limitation=limitation,
    )


class WeightedAdditiveFit(BaseModel, frozen=True, extra="forbid"):
    """Supporting item-adjusted association, subject to complete-case selection.

    Attributes:
        coefficient: Own-family slope when numerically estimable, otherwise absent.
        reason: Undefined-support, nonestimability or numerical-refusal reason.
        eligible_harmful_rows: Number of original harmful-reference rows.
        included_response_identifiers: All-four-valid harmful rows used in the fit.
        excluded_response_identifiers: Harmful rows excluded for any unresolved judge.
        complete_case_coverage: Included divided by all harmful rows, absent if empty.
        source_row_weights: Recomputed component/attack q on included rows.
        observation_weights: Response to roster-ordered q_i*u_j*v_g weights.
        nuisance_columns: Explicit full categorical nuisance column identities.
        nuisance_rank: Numerical rank after weighted item demeaning.
        nuisance_singular_values: SVD values, retaining rank-deficiency evidence.
        rank_tolerance: SVD absolute singular-value threshold.
        predictor_residual_norm: Weighted own-family norm after nuisance projection.
        estimability_tolerance: Explicit absolute predictor-residual norm threshold.
        weight_definition: Exact weighting and selected population.
        model_definition: Additive model and projection definition.
        limitation: Complete-case and causal-interpretation limits.
    """

    coefficient: float | None
    reason: str | None
    eligible_harmful_rows: int
    included_response_identifiers: tuple[str, ...]
    excluded_response_identifiers: tuple[str, ...]
    complete_case_coverage: float | None
    source_row_weights: dict[str, float]
    observation_weights: dict[str, tuple[float, ...]]
    nuisance_columns: tuple[str, ...]
    nuisance_rank: int | None
    nuisance_singular_values: tuple[float, ...]
    rank_tolerance: float | None
    predictor_residual_norm: float | None
    estimability_tolerance: float | None
    weight_definition: str = ADDITIVE_WEIGHT_DEFINITION
    model_definition: str = ADDITIVE_MODEL_DEFINITION
    limitation: str = SELECTION_LIMITATION


@dataclass(frozen=True, slots=True, kw_only=True)
class WeightedItemDesign:
    """Internal weighted arrays after removing unrestricted item fixed effects.

    Attributes:
        outcome: Weighted within-item benign indicator deviations.
        predictor: Weighted within-item own-family indicator deviations.
        nuisance: Weighted within-item full judge/category indicator deviations.
        nuisance_columns: Ordered nuisance column labels.
    """

    outcome: FloatingArray
    predictor: FloatingArray
    nuisance: FloatingArray
    nuisance_columns: tuple[str, ...]


def create_weighted_item_design(
    rows: tuple[EligibleResponse, ...],
    lookup: dict[tuple[str, JudgeRole], SavedJudgment],
    weights: dict[str, tuple[float, ...]],
) -> WeightedItemDesign:
    """Remove weighted item intercepts without constructing an item-dummy matrix.

    Args:
        rows: All-four-valid harmful rows in frozen source order.
        lookup: Validated terminal assignments.
        weights: Roster-ordered q_i*u_j*v_g observation weights for each row.

    Returns:
        Finite weighted vectors and the small categorical nuisance matrix.

    Raises:
        InvalidValueError: If a supplied row contains an unresolved terminal outcome.
    """
    severities = tuple(sorted({row.reference for row in rows}))
    attacks = tuple(sorted({row.attack for row in rows}))
    columns = tuple(
        f"ordinal:{severity}:{judge.value}"
        for severity in severities
        for judge in JudgeRole
    ) + tuple(
        f"attack:{attack}:{judge.value}" for attack in attacks for judge in JudgeRole
    )
    column_indices = {name: index for index, name in enumerate(columns)}
    outcome = np.zeros((len(rows), len(JudgeRole)), dtype=np.float64)
    predictor = np.zeros_like(outcome)
    nuisance = np.zeros((len(rows), len(JudgeRole), len(columns)), dtype=np.float64)
    for row_index, row in enumerate(rows):
        source = create_source_role(row)
        for judge_index, judge in enumerate(JudgeRole):
            terminal = lookup[row.identifier, judge].outcome
            if terminal.kind != "judgment":
                message = (
                    "Additive design contains an unresolved judgment. "
                    "Supply only all-four-valid complete-case rows."
                )
                raise InvalidValueError(message)
            outcome[row_index, judge_index] = int(
                terminal.ordinal < HARMFUL_REFERENCE_MINIMUM
            )
            predictor[row_index, judge_index] = int(create_same_family(judge, source))
            nuisance[
                row_index,
                judge_index,
                column_indices[f"ordinal:{row.reference}:{judge.value}"],
            ] = 1
            nuisance[
                row_index,
                judge_index,
                column_indices[f"attack:{row.attack}:{judge.value}"],
            ] = 1
    judge_margins = np.array(tuple(ROSTER_WEIGHTS.values()), dtype=np.float64)
    root_weights = np.sqrt(
        np.array([weights[row.identifier] for row in rows], dtype=np.float64)
    )
    centered_outcome = outcome - np.sum(outcome * judge_margins, axis=1, keepdims=True)
    centered_predictor = predictor - np.sum(
        predictor * judge_margins, axis=1, keepdims=True
    )
    centered_nuisance = nuisance - np.sum(
        nuisance * judge_margins[None, :, None], axis=1, keepdims=True
    )
    return WeightedItemDesign(
        outcome=(centered_outcome * root_weights).reshape(-1),
        predictor=(centered_predictor * root_weights).reshape(-1),
        nuisance=(centered_nuisance * root_weights[:, :, None]).reshape(
            -1, len(columns)
        ),
        nuisance_columns=columns,
    )


def create_weighted_additive_fit(
    rows: tuple[EligibleResponse, ...], judgments: tuple[SavedJudgment, ...]
) -> WeightedAdditiveFit:
    """Fit the supporting own-family slope only when that contrast is estimable.

    Complete cases require all four valid terminal ordinals; q is recomputed on
    that subset. Full judge-by-original-ordinal and judge-by-attack indicators may
    be redundant: SVD projects onto their column space without assigning arbitrary
    nuisance coefficients. The own-family slope is unavailable if its residualized
    predictor is below the documented numerical-rank threshold. This is not a test.

    Args:
        rows: Original eligible source records, with source references preserved.
        judgments: Complete four-judge terminal matrix, unresolved outcomes retained.

    Returns:
        A supporting numeric fit or explicit support/nonestimability refusal, with
        included/excluded IDs, actual weights, and complete-case selection limits.
    """
    lookup = create_judgment_lookup(rows, judgments)
    harmful = tuple(row for row in rows if row.harmful)
    included = tuple(
        row
        for row in harmful
        if all(
            lookup[row.identifier, judge].outcome.kind == "judgment"
            for judge in JudgeRole
        )
    )
    included_ids = {row.identifier for row in included}
    row_weights = create_row_weights(included)
    weights = {
        row.identifier: tuple(
            row_weights[row.identifier]
            * ROSTER_WEIGHTS[judge]
            * ROSTER_WEIGHTS[create_source_role(row)]
            for judge in JudgeRole
        )
        for row in included
    }
    fit = WeightedAdditiveFit(
        coefficient=None,
        reason="Complete-case rows lack harmful support for a source.",
        eligible_harmful_rows=len(harmful),
        included_response_identifiers=tuple(row.identifier for row in included),
        excluded_response_identifiers=tuple(
            row.identifier for row in harmful if row.identifier not in included_ids
        ),
        complete_case_coverage=len(included) / len(harmful) if harmful else None,
        source_row_weights=row_weights,
        observation_weights=weights,
        nuisance_columns=(),
        nuisance_rank=None,
        nuisance_singular_values=(),
        rank_tolerance=None,
        predictor_residual_norm=None,
        estimability_tolerance=None,
    )
    if {create_source_role(row) for row in included} != set(JudgeRole):
        return fit
    design = create_weighted_item_design(included, lookup, weights)
    try:
        left, singular_values, _ = np.linalg.svd(design.nuisance, full_matrices=False)
    except np.linalg.LinAlgError:
        return fit.model_copy(
            update={
                "reason": "Nuisance SVD did not converge.",
                "nuisance_columns": design.nuisance_columns,
            }
        )
    dimension = max(design.nuisance.shape)
    machine_precision = float(np.finfo(np.float64).eps)
    rank_tolerance = machine_precision * dimension * float(singular_values[0])
    rank = int(np.count_nonzero(singular_values > rank_tolerance))
    basis = left[:, :rank]
    residual_predictor = design.predictor - basis @ (basis.T @ design.predictor)
    residual_outcome = design.outcome - basis @ (basis.T @ design.outcome)
    residual_norm = float(np.linalg.norm(residual_predictor))
    estimability_tolerance = (
        machine_precision
        * max(dimension, len(design.nuisance_columns) + 1)
        * max(1, float(np.linalg.norm(design.predictor)))
    )
    available = math.isfinite(residual_norm) and residual_norm > estimability_tolerance
    coefficient = (
        float(
            np.dot(residual_predictor, residual_outcome)
            / np.dot(residual_predictor, residual_predictor)
        )
        if available
        else None
    )
    reason = (
        None
        if available
        else "Own-family slope is not numerically estimable after nuisance projection."
    )
    if coefficient is not None and not math.isfinite(coefficient):
        coefficient, reason = (
            None,
            "Additive slope is nonfinite; retain descriptive primary bounds.",
        )
    return fit.model_copy(
        update={
            "coefficient": coefficient,
            "reason": reason,
            "nuisance_columns": design.nuisance_columns,
            "nuisance_rank": rank,
            "nuisance_singular_values": tuple(
                float(value) for value in singular_values
            ),
            "rank_tolerance": rank_tolerance,
            "predictor_residual_norm": residual_norm,
            "estimability_tolerance": estimability_tolerance,
        }
    )
