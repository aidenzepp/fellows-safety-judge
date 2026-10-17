"""Frozen balanced contrasts preserve margins, source support and saved identities."""

import itertools

import pytest

from safety_judge.analysis import (
    OutcomeTerm,
    SavedJudgment,
    create_accuracy_summary,
    create_boundary_error_ranking,
    create_cell_coefficient,
    create_completion_bounds,
    create_contrast_slices,
    create_effect_benchmarks,
    create_h1_analysis,
    create_pre_call_support_screen,
    create_reference_error_scenario,
    create_reference_error_sensitivities,
    create_row_weights,
    create_support_screen,
    create_supporting_slices,
)
from safety_judge.coin_flip import SOURCE_MODEL_ROLES, EligibleResponse
from safety_judge.errors import InvalidValueError
from safety_judge.judging import JudgeRole, OrdinalJudgment, UnresolvedJudgment


def create_rows(*, copies: int = 1) -> tuple[EligibleResponse, ...]:
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
            behavior_identifier=f"behavior:{copy}",
            behavior_was_derived=False,
            component_identifier=f"component:{copy}",
        )
        for index, model in enumerate(SOURCE_MODEL_ROLES)
        for copy in range(copies)
    )


def create_judgments(rows: tuple[EligibleResponse, ...]) -> tuple[SavedJudgment, ...]:
    return tuple(
        SavedJudgment(
            response_identifier=row.identifier,
            judge=judge,
            variable_identifier=f"{row.identifier}:{judge}",
            outcome=OrdinalJudgment(
                ordinal=1 if judge.value == SOURCE_MODEL_ROLES[row.source_model] else 5
            ),
        )
        for row in rows
        for judge in JudgeRole
    )


def test_component_attack_and_row_weights_are_balanced_within_each_source() -> None:
    row = create_rows()[0]
    rows = (
        row,
        row.model_copy(update={"identifier": "second"}),
        row.model_copy(update={"identifier": "other-attack", "attack": "second"}),
        row.model_copy(
            update={"identifier": "other-component", "component_identifier": "other"}
        ),
    )
    weights = create_row_weights(rows)
    assert weights == {
        row.identifier: 0.125,
        "second": 0.125,
        "other-attack": 0.25,
        "other-component": 0.5,
    }


def test_balanced_contrast_cancels_additive_judge_and_source_margins() -> None:
    for target in (None, *JudgeRole):
        for judge in JudgeRole:
            assert sum(
                create_cell_coefficient(target, judge, source) for source in JudgeRole
            ) == pytest.approx(0)
        for source in JudgeRole:
            assert sum(
                create_cell_coefficient(target, judge, source) for judge in JudgeRole
            ) == pytest.approx(0)


def test_delta_equals_the_fixed_weighted_average_of_relative_theta() -> None:
    rows = create_rows()
    analysis = create_h1_analysis(rows, create_judgments(rows))
    delta, first, second, third, fourth = analysis.targets
    assert delta.bounds.point == pytest.approx(5 / 6)
    assert delta.bounds.point == pytest.approx(
        first.bounds.lower / 6
        + second.bounds.lower / 6
        + third.bounds.lower / 3
        + fourth.bounds.lower / 3
    )
    assert len(create_effect_benchmarks(analysis)) == 12


def test_sharp_unknown_bounds_match_every_binary_completion() -> None:
    terms = tuple(
        OutcomeTerm(
            variable_identifier=identifier,
            coefficient=coefficient,
            value=None,
            component_identifier="component",
            source=JudgeRole.LLAMA_EIGHT,
        )
        for identifier, coefficient in (("a", 0.5), ("b", -0.3), ("a", -0.2))
    )
    bounds = create_completion_bounds(terms)
    completions = [
        0.3 * first - 0.3 * second
        for first, second in itertools.product((0, 1), repeat=2)
    ]
    assert bounds.lower == pytest.approx(min(completions))
    assert bounds.upper == pytest.approx(max(completions))
    assert bounds.point is None
    canceled = create_completion_bounds(
        (terms[0], terms[0].model_copy(update={"coefficient": -0.5}))
    )
    assert canceled.point == 0
    assert canceled.unknown_variables == 0


def test_duplicate_assignments_and_saved_outcome_ids_are_rejected() -> None:
    rows = create_rows()
    judgments = create_judgments(rows)
    with pytest.raises(InvalidValueError, match="incomplete or duplicated"):
        _ = create_h1_analysis(rows, (*judgments, judgments[0]))
    with pytest.raises(InvalidValueError, match="incomplete or duplicated"):
        _ = create_h1_analysis(
            rows,
            (
                judgments[0].model_copy(
                    update={"variable_identifier": judgments[1].variable_identifier}
                ),
                *judgments[1:],
            ),
        )
    with pytest.raises(InvalidValueError, match="Response IDs repeat"):
        _ = create_row_weights((rows[0], rows[0]))


def test_absent_harmful_source_support_is_undefined_instead_of_zero_imputed() -> None:
    rows = create_rows()[:-1]
    analysis = create_h1_analysis(rows, create_judgments(rows))
    assert analysis.targets == ()
    assert analysis.undefined_reason is not None
    assert {row.relation for row in create_effect_benchmarks(analysis)} == {"undefined"}


def test_support_screens_use_absolute_outcome_leverage_and_all_linked_components() -> (
    None
):
    rows = create_rows(copies=30)
    screen = create_support_screen(create_h1_analysis(rows, create_judgments(rows)))
    assert screen.passed
    assert screen.targets[0].absolute_coefficient_sum == pytest.approx(2)
    assert screen.targets[0].maximum_component_fraction == pytest.approx(1 / 30)
    assert screen.targets[0].worst_case_variance == pytest.approx(1 / 30)
    assert screen.targets[1].absolute_coefficient_sum == pytest.approx(8 / 3)


def test_supporting_agreement_keeps_unresolved_assignments_in_coverage() -> None:
    rows = create_rows()
    judgments = create_judgments(rows)
    judgments = (
        judgments[0].model_copy(
            update={"outcome": UnresolvedJudgment(reason="unknown")}
        ),
        *judgments[1:],
    )
    summary = create_accuracy_summary(rows, judgments, JudgeRole.GEMMA_ONE)
    assert summary.assigned == 4
    assert summary.valid == 3
    assert summary.coverage == 0.75
    assert summary.accuracy == 1
    assert summary.specificity is None
    assert summary.balanced_accuracy is None


def test_reference_error_rank_and_budget_scenarios_match_full_recomputation() -> None:
    original = create_rows(copies=3)
    rows = tuple(
        row.model_copy(update={"reference": 2, "harmful": False})
        if row.row_number % 3 == 2
        else row
        for row in original
    )
    judgments = create_judgments(rows)
    ranking = create_boundary_error_ranking(rows, judgments)
    assert ranking is not None
    expected: list[tuple[float, int, str]] = []
    for row in rows:
        scenario = create_reference_error_scenario(rows, judgments, (row.identifier,))
        assert scenario.analysis is not None
        expected.append(
            (
                round(scenario.analysis.targets[0].bounds.lower, 12),
                row.row_number,
                row.identifier,
            )
        )
    assert ranking == tuple(identifier for _, _, identifier in sorted(expected))
    scenarios = create_reference_error_sensitivities(rows, judgments)
    assert [scenario.assumed_fraction for scenario in scenarios] == [0.01, 0.05, 0.10]
    assert [len(scenario.affected_identifiers) for scenario in scenarios] == [1, 1, 2]
    assert scenarios[2].affected_identifiers == ranking[:2]
    assert scenarios[2].actual_fraction == pytest.approx(2 / 12)
    assert [row.reference for row in rows] == [3, 3, 2] * 4
    assert "not an adversarial optimum" in scenarios[2].method


def test_reference_errors_report_support_risk_and_insufficient_candidates() -> None:
    rows = create_rows()
    unavailable = create_reference_error_sensitivities(rows, create_judgments(rows))
    assert [scenario.analysis for scenario in unavailable] == [None, None, None]
    assert "support" in (unavailable[0].reason or "")
    stable = tuple(
        row.model_copy(update={"reference": 4}) for row in create_rows(copies=3)
    )
    too_few = create_reference_error_sensitivities(stable, create_judgments(stable))
    assert [scenario.analysis for scenario in too_few] == [None, None, None]
    assert "Too few" in (too_few[0].reason or "")


def test_pre_call_support_needs_no_outcomes_and_matches_post_call_coefficients() -> (
    None
):
    rows = create_rows(copies=30)
    assert create_pre_call_support_screen(rows) == create_support_screen(
        create_h1_analysis(rows, create_judgments(rows))
    )


def test_supporting_slices_include_all_judges_and_original_reference_severities() -> (
    None
):
    rows = create_rows()
    slices = create_supporting_slices(rows, create_judgments(rows))
    overall = [summary for summary in slices if summary.slice_name == "overall"]
    severity = [summary for summary in slices if summary.slice_name == "severity:3"]
    assert [summary.judge for summary in overall] == list(JudgeRole)
    assert [summary.assigned for summary in severity] == [4, 4, 4, 4]


def test_boundary_ranking_recomputes_attack_counts_and_unknown_endpoints() -> None:
    base = create_rows(copies=3)
    extra = base[0].model_copy(
        update={"identifier": "extra", "attack": "second", "row_number": 100}
    )
    rows = (*base, extra)
    judgments = tuple(
        item.model_copy(
            update={
                "outcome": UnresolvedJudgment(reason="unknown")
                if item.response_identifier.endswith(":0")
                else OrdinalJudgment(ordinal=5)
            }
        )
        for item in create_judgments(rows)
    )
    expected: list[tuple[float, int, str]] = []
    for row in rows:
        scenario = create_reference_error_scenario(rows, judgments, (row.identifier,))
        assert scenario.analysis is not None
        expected.append(
            (
                round(scenario.analysis.targets[0].bounds.lower, 12),
                row.row_number,
                row.identifier,
            )
        )
    assert create_boundary_error_ranking(rows, judgments) == tuple(
        identifier for _, _, identifier in sorted(expected)
    )


def test_supporting_attack_contrast_is_undefined_without_all_source_generators() -> (
    None
):
    base = create_rows()
    rows = (base[0].model_copy(update={"attack": "isolated"}), *base[1:])
    slices = create_contrast_slices(rows, create_judgments(rows))
    isolated = next(item for item in slices if item.name == "attack:isolated")
    assert isolated.analysis.targets == ()
    assert isolated.analysis.undefined_reason is not None
