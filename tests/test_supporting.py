"""Supporting sensitivities keep explicit weights, selection limits and estimability."""

import math

import pytest

from safety_judge.analysis import (
    ROSTER_WEIGHTS,
    SavedJudgment,
    create_h1_analysis,
    create_same_family,
)
from safety_judge.coin_flip import SOURCE_MODEL_ROLES, EligibleResponse
from safety_judge.judging import JudgeRole, OrdinalJudgment, UnresolvedJudgment
from safety_judge.supporting import (
    create_weighted_additive_fit,
    create_weighting_sensitivities,
)


def create_source_rows(*, copies: int = 1) -> tuple[EligibleResponse, ...]:
    return tuple(
        EligibleResponse(
            identifier=f"{model}:{copy}",
            row_number=index * copies + copy,
            prompt="Synthetic request",
            generation="Synthetic response",
            source_model=model,
            attack="first",
            reference=3,
            harmful=True,
            behavior_identifier=f"{index}:{copy}",
            behavior_was_derived=False,
            component_identifier=f"{index}:{copy}",
        )
        for index, model in enumerate(SOURCE_MODEL_ROLES)
        for copy in range(copies)
    )


def create_saved_outcomes(
    rows: tuple[EligibleResponse, ...],
) -> tuple[SavedJudgment, ...]:
    return tuple(
        SavedJudgment(
            response_identifier=row.identifier,
            judge=judge,
            variable_identifier=f"{row.identifier}:{judge.value}",
            outcome=OrdinalJudgment(
                ordinal=1
                if create_same_family(
                    judge, JudgeRole(SOURCE_MODEL_ROLES[row.source_model])
                )
                else 5
            ),
        )
        for row in rows
        for judge in JudgeRole
    )


def test_weighting_variants_normalize_actual_joint_own_and_outside_mass() -> None:
    rows = create_source_rows()
    raw, equal = create_weighting_sensitivities(rows, create_saved_outcomes(rows))
    assert raw.own_family_mass == pytest.approx(1 / 3)
    assert raw.outside_family_mass == pytest.approx(2 / 3)
    assert equal.own_family_mass == 3 / 8
    assert equal.outside_family_mass == 5 / 8
    assert raw.target is not None
    assert equal.target is not None
    assert raw.target.bounds.point == pytest.approx(1)
    assert equal.target.bounds.point == pytest.approx(1)
    assert math.fsum(
        term.coefficient for term in equal.target.terms if term.coefficient > 0
    ) == pytest.approx(1)
    assert math.fsum(
        term.coefficient for term in equal.target.terms if term.coefficient < 0
    ) == pytest.approx(-1)
    assert equal.judge_weights == dict.fromkeys(JudgeRole, 0.25)
    assert "margins differ" in equal.limitation


def test_raw_rows_change_component_multiplicity_without_changing_primary() -> None:
    base = create_source_rows()
    first = base[0]
    second = first.model_copy(update={"identifier": "second", "row_number": 10})
    third = first.model_copy(
        update={
            "identifier": "third",
            "row_number": 11,
            "component_identifier": "other-component",
        }
    )
    rows = (*base, second, third)
    outcomes = tuple(
        item.model_copy(
            update={
                "outcome": OrdinalJudgment(
                    ordinal=1
                    if item.response_identifier == "third"
                    and item.judge
                    in (JudgeRole.GEMMA_ONE, JudgeRole.GEMMA_TWENTY_SEVEN)
                    else 5
                )
            }
        )
        for item in create_saved_outcomes(rows)
    )
    primary_before = create_h1_analysis(rows, outcomes)
    raw, equal = create_weighting_sensitivities(rows, outcomes)
    assert raw.row_weights[first.identifier] == pytest.approx(1 / 3)
    assert raw.row_weights["third"] == pytest.approx(1 / 3)
    assert equal.row_weights[first.identifier] == 0.25
    assert equal.row_weights["third"] == 0.5
    assert raw.target is not None
    assert equal.target is not None
    assert raw.target.bounds.point == pytest.approx(1 / 18)
    assert equal.target.bounds.point == pytest.approx(1 / 6)
    assert primary_before.targets[0].bounds.point == pytest.approx(1 / 12)
    assert create_h1_analysis(rows, outcomes) == primary_before


def test_weighting_sensitivities_retain_unknowns_and_explicit_absent_support() -> None:
    rows = create_source_rows()
    outcomes = create_saved_outcomes(rows)
    unresolved = (
        outcomes[0].model_copy(
            update={"outcome": UnresolvedJudgment(reason="unknown")}
        ),
        *outcomes[1:],
    )
    for result in create_weighting_sensitivities(rows, unresolved):
        assert result.target is not None
        assert result.target.bounds.point is None
        assert result.target.bounds.unknown_variables == 1
        assert result.valid_harmful_assignments == 15
        assert result.assigned_harmful_judgments == 16
    for result in create_weighting_sensitivities(
        rows[:-1], create_saved_outcomes(rows[:-1])
    ):
        assert result.target is None
        assert result.reason is not None


def test_additive_slope_is_identified_despite_redundant_nuisance_columns() -> None:
    rows = create_source_rows()
    fit = create_weighted_additive_fit(rows, create_saved_outcomes(rows))
    assert fit.reason is None
    assert fit.coefficient == pytest.approx(1)
    assert fit.nuisance_rank == 3
    assert fit.nuisance_rank < len(fit.nuisance_columns)
    assert fit.predictor_residual_norm is not None
    assert fit.estimability_tolerance is not None
    assert fit.predictor_residual_norm > fit.estimability_tolerance
    assert math.fsum(
        weight for weights in fit.observation_weights.values() for weight in weights
    ) == pytest.approx(1)
    assert "p_value" not in fit.model_dump()


def test_item_and_judge_global_outcomes_have_zero_adjusted_own_family_slope() -> None:
    rows = create_source_rows()
    saved = create_saved_outcomes(rows)
    judge_only = tuple(
        item.model_copy(
            update={
                "outcome": OrdinalJudgment(
                    ordinal=1 if item.judge == JudgeRole.GEMMA_ONE else 5
                )
            }
        )
        for item in saved
    )
    item_only = tuple(
        item.model_copy(
            update={
                "outcome": OrdinalJudgment(
                    ordinal=1 if item.response_identifier == rows[0].identifier else 5
                )
            }
        )
        for item in saved
    )
    assert create_weighted_additive_fit(rows, judge_only).coefficient == pytest.approx(
        0
    )
    assert create_weighted_additive_fit(rows, item_only).coefficient == pytest.approx(0)


def test_complete_case_fit_reports_exclusions_and_recomputes_the_subset_weights() -> (
    None
):
    rows = create_source_rows(copies=2)
    saved = create_saved_outcomes(rows)
    outcomes = (
        saved[0].model_copy(
            update={"outcome": UnresolvedJudgment(reason="parse_error")}
        ),
        *saved[1:],
    )
    fit = create_weighted_additive_fit(rows, outcomes)
    assert fit.coefficient == pytest.approx(1)
    assert fit.eligible_harmful_rows == 8
    assert fit.complete_case_coverage == 7 / 8
    assert fit.excluded_response_identifiers == (rows[0].identifier,)
    assert fit.source_row_weights[rows[1].identifier] == 1
    assert fit.source_row_weights[rows[2].identifier] == 0.5
    assert fit.observation_weights[rows[1].identifier] == pytest.approx(
        tuple(ROSTER_WEIGHTS[judge] / 6 for judge in JudgeRole)
    )
    assert "selection" in fit.limitation


def test_judge_by_severity_alias_makes_the_own_family_slope_unavailable() -> None:
    base = create_source_rows()
    rows = tuple(
        row.model_copy(update={"reference": severity})
        for row, severity in zip(base, (3, 3, 4, 5), strict=True)
    )
    fit = create_weighted_additive_fit(rows, create_saved_outcomes(rows))
    assert fit.coefficient is None
    assert "not numerically estimable" in (fit.reason or "")
    assert fit.predictor_residual_norm is not None
    assert fit.estimability_tolerance is not None
    assert fit.predictor_residual_norm <= fit.estimability_tolerance


def test_complete_case_source_loss_is_unavailable_without_zero_imputation() -> None:
    rows = create_source_rows()
    saved = create_saved_outcomes(rows)
    outcomes = (
        saved[0].model_copy(update={"outcome": UnresolvedJudgment(reason="unknown")}),
        *saved[1:],
    )
    fit = create_weighted_additive_fit(rows, outcomes)
    assert fit.coefficient is None
    assert fit.complete_case_coverage == 0.75
    assert "lack harmful support" in (fit.reason or "")
    assert fit.nuisance_rank is None


def test_judge_attack_nuisance_is_removed_with_unbalanced_source_support() -> None:
    base = create_source_rows(copies=2)
    rows = tuple(
        row.model_copy(update={"attack": "second"})
        if row.identifier.endswith(":1")
        else row
        for row in base
    )
    rows = tuple(row for index, row in enumerate(rows) if index not in (1, 2))
    lookup = {row.identifier: row for row in rows}
    outcomes = tuple(
        item.model_copy(
            update={
                "outcome": OrdinalJudgment(
                    ordinal=1
                    if (
                        lookup[item.response_identifier].attack == "first"
                        and item.judge == JudgeRole.GEMMA_ONE
                    )
                    or (
                        lookup[item.response_identifier].attack == "second"
                        and item.judge == JudgeRole.LLAMA_EIGHT
                    )
                    else 5
                )
            }
        )
        for item in create_saved_outcomes(rows)
    )
    fit = create_weighted_additive_fit(rows, outcomes)
    assert fit.reason is None
    assert fit.coefficient == pytest.approx(0, abs=1e-12)
    assert "attack:first:G1" in fit.nuisance_columns
    assert "attack:second:L8" in fit.nuisance_columns


def test_balanced_single_stratum_fit_matches_the_hand_calculated_five_sixths_gap() -> (
    None
):
    rows = create_source_rows()
    outcomes = tuple(
        item.model_copy(
            update={
                "outcome": OrdinalJudgment(
                    ordinal=1
                    if item.judge.value
                    == SOURCE_MODEL_ROLES[
                        next(
                            row.source_model
                            for row in rows
                            if row.identifier == item.response_identifier
                        )
                    ]
                    else 5
                )
            }
        )
        for item in create_saved_outcomes(rows)
    )
    fit = create_weighted_additive_fit(rows, outcomes)
    assert fit.coefficient == pytest.approx(5 / 6)
