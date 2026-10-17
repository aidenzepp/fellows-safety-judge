"""Frozen component multiplicities and refusal rules protect conditional inference."""

import pytest

from safety_judge.analysis import (
    SavedJudgment,
    create_h1_analysis,
    create_row_weights,
    create_same_family,
)
from safety_judge.coin_flip import SOURCE_MODEL_ROLES, EligibleResponse
from safety_judge.errors import InvalidValueError
from safety_judge.inference import (
    SECONDARY_BOUND_ALPHA,
    EndpointInference,
    EndpointReplicate,
    create_bootstrap_target,
    create_component_replicate,
    create_descriptive_uncertainty,
    create_endpoint_inference,
    create_h1_decisions,
    create_nearest_rank,
    create_paired_pilot,
    create_pilot_replicates,
    select_component_multiplicities,
    select_pilot_multiplicities,
)
from safety_judge.judging import JudgeRole, OrdinalJudgment, UnresolvedJudgment


def create_source_rows(
    *, copies: int = 2, shared: bool = True
) -> tuple[EligibleResponse, ...]:
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
            component_identifier=f"component:{copy}" if shared else f"{index}:{copy}",
        )
        for index, model in enumerate(SOURCE_MODEL_ROLES)
        for copy in range(copies)
    )


def create_saved_outcomes(
    rows: tuple[EligibleResponse, ...], *, unresolved: bool = False
) -> tuple[SavedJudgment, ...]:
    return tuple(
        SavedJudgment(
            response_identifier=row.identifier,
            judge=judge,
            variable_identifier=f"{row.identifier}:{judge}",
            outcome=UnresolvedJudgment(reason="unknown")
            if unresolved
            else OrdinalJudgment(
                ordinal=1
                if row.identifier.endswith(":0")
                and judge.value == SOURCE_MODEL_ROLES[row.source_model]
                else 5
            ),
        )
        for row in rows
        for judge in JudgeRole
    )


def test_copied_components_recompute_denominators_and_match_full_row_weights() -> None:
    rows = create_source_rows(copies=3)
    analysis = create_h1_analysis(rows, create_saved_outcomes(rows))
    target = analysis.targets[0]
    counts = {"component:0": 2, "component:1": 1}
    copied = create_component_replicate(
        create_bootstrap_target(analysis, target), counts
    )
    weights = create_row_weights(rows, counts)
    expected = sum(
        term.coefficient
        * weights[term.variable_identifier.rsplit(":", 1)[0]]
        / analysis.row_weights[term.variable_identifier.rsplit(":", 1)[0]]
        * (term.value or 0)
        for term in target.terms
    )
    assert copied.lower == pytest.approx(expected)
    assert copied.upper == pytest.approx(expected)
    assert copied.lower != pytest.approx(target.bounds.lower)


def test_a_missing_source_replicate_is_retained_and_refuses_inference() -> None:
    rows = create_source_rows(copies=1, shared=False)
    analysis = create_h1_analysis(rows, create_saved_outcomes(rows))
    prepared = create_bootstrap_target(analysis, analysis.targets[0])
    failed = create_component_replicate(prepared, {"0:0": 4})
    assert failed.lower is None
    result = create_endpoint_inference(
        EndpointReplicate(lower=0.2, upper=0.2),
        (EndpointReplicate(lower=0.1, upper=0.1), failed),
    )
    assert result.p_value == 1
    assert result.lower_bound is None
    assert result.reason is not None


def test_zero_variance_and_nonfinite_endpoints_cannot_produce_finite_bounds() -> None:
    observed = EndpointReplicate(lower=0.2, upper=0.3)
    constant = create_endpoint_inference(observed, (observed, observed))
    assert constant.p_value == 1
    assert constant.lower_bound is None
    nonfinite = create_endpoint_inference(
        observed, (observed, EndpointReplicate(lower=float("nan"), upper=0.4))
    )
    assert nonfinite.p_value == 1
    assert nonfinite.upper_bound is None


def test_nearest_rank_and_centered_p_include_equality_at_the_null_boundary() -> None:
    assert create_nearest_rank((-0.2, 0, 0.1, 0.3), 0.75) == 0.3
    assert create_nearest_rank((-0.2, 0, 0.1, 0.3), 0) == -0.2
    observed = EndpointReplicate(lower=0.05, upper=0.05)
    result = create_endpoint_inference(
        observed,
        (
            EndpointReplicate(lower=0, upper=0),
            EndpointReplicate(lower=0.05, upper=0.05),
            EndpointReplicate(lower=0.1, upper=0.1),
        ),
        alpha=0.25,
    )
    assert result.p_value == 0.75
    assert result.lower_bound == pytest.approx(0)
    assert result.upper_bound == pytest.approx(0.1)


def test_fixed_seed_preserves_component_copies_without_global_randomness() -> None:
    first = select_component_multiplicities(("a", "b", "c"), replicates=3)
    assert first == select_component_multiplicities(("a", "b", "c"), replicates=3)
    assert [sum(draw.values()) for draw in first] == [3, 3, 3]
    with pytest.raises(InvalidValueError, match="invalid"):
        _ = select_component_multiplicities(("a", "a"), replicates=3)


def test_primary_gate_holm_and_conservative_strict_effect_bounds_are_all_required() -> (
    None
):
    primary = EndpointInference(
        p_value=0.001, lower_bound=0.1, upper_bound=0.2, reason=None
    )
    secondary = {
        role: EndpointInference(
            p_value=p_value,
            lower_bound=0.1,
            upper_bound=0.2,
            reason=None,
            alpha=SECONDARY_BOUND_ALPHA,
        )
        for role, p_value in zip(JudgeRole, (0.001, 0.004, 0.02, 1), strict=True)
    }
    decisions = create_h1_decisions(primary, secondary)
    assert decisions.primary_rejected
    assert list(decisions.holm_adjusted_p.values()) == pytest.approx(
        [0.004, 0.012, 0.04, 1]
    )
    assert list(decisions.secondary_rejected.values()) == [True, True, False, False]
    equality = primary.model_copy(update={"lower_bound": 0.05})
    blocked = create_h1_decisions(equality, secondary)
    assert not blocked.primary_rejected
    assert list(blocked.secondary_rejected.values()) == [False] * 4
    secondary[JudgeRole.GEMMA_ONE] = primary.model_copy(
        update={"lower_bound": 0.05, "alpha": SECONDARY_BOUND_ALPHA}
    )
    assert not create_h1_decisions(primary, secondary).secondary_rejected[
        JudgeRole.GEMMA_ONE
    ]


def test_paired_pilot_uses_eight_copies_per_source_and_cancels_shared_unknowns() -> (
    None
):
    rows = create_source_rows(copies=8, shared=False)
    analysis = create_h1_analysis(rows, create_saved_outcomes(rows, unresolved=True))
    pilot = create_paired_pilot(analysis, analysis)
    assert pilot.reduction.bounds.point == 0
    assert pilot.reduction.bounds.lower == 0
    assert pilot.reduction.bounds.upper == 0
    draws = select_pilot_multiplicities(pilot, replicates=3)
    for draw in draws:
        assert [
            sum(draw.get(component, 0) for component in pilot.strata[source])
            for source in JudgeRole
        ] == [8, 8, 8, 8]
        original, rewrite, reduction = create_pilot_replicates(pilot, draw)
        assert original == rewrite
        assert reduction.lower == reduction.upper == 0
    with pytest.raises(InvalidValueError, match="quota"):
        _ = create_pilot_replicates(pilot, {"0:0": 32})


def test_decisions_reject_secondary_bounds_with_the_wrong_tail_probability() -> None:
    result = EndpointInference(
        p_value=0.001, lower_bound=0.1, upper_bound=0.2, reason=None
    )
    with pytest.raises(InvalidValueError, match="Test tails differ"):
        _ = create_h1_decisions(result, dict.fromkeys(JudgeRole, result))


def test_paired_uncertainty_is_descriptive_and_retains_invalid_replicates() -> None:
    observed = EndpointReplicate(lower=0.1, upper=0.3)
    result = create_descriptive_uncertainty(
        observed,
        (
            EndpointReplicate(lower=0.05, upper=0.2),
            EndpointReplicate(lower=0.15, upper=0.4),
        ),
        alpha=0.1,
    )
    assert result.lower == pytest.approx(0.05)
    assert result.upper == pytest.approx(0.4)
    assert "p_value" not in result.model_dump()
    invalid = create_descriptive_uncertainty(
        observed,
        (
            EndpointReplicate(lower=0.05, upper=0.2),
            EndpointReplicate(lower=None, upper=None, reason="missing support"),
        ),
        alpha=0.1,
    )
    assert invalid.lower is None
    assert invalid.reason is not None


def test_invalid_secondary_remains_p_one_even_if_its_supplied_raw_p_is_favorable() -> (
    None
):
    primary = EndpointInference(
        p_value=0.001, lower_bound=0.1, upper_bound=0.2, reason=None
    )
    secondary = {
        role: primary.model_copy(update={"alpha": SECONDARY_BOUND_ALPHA})
        for role in JudgeRole
    }
    secondary[JudgeRole.GEMMA_ONE] = primary.model_copy(
        update={
            "p_value": 0,
            "lower_bound": None,
            "upper_bound": None,
            "reason": "unrun",
            "alpha": SECONDARY_BOUND_ALPHA,
        }
    )
    decisions = create_h1_decisions(primary, secondary)
    assert decisions.holm_adjusted_p[JudgeRole.GEMMA_ONE] == 1
    assert not decisions.secondary_rejected[JudgeRole.GEMMA_ONE]


def test_main_bootstrap_preserves_unequal_support_and_benign_only_components() -> None:
    base = create_source_rows(copies=3)
    rows = tuple(
        row for index, row in enumerate(base) if index in (0, 1, 3, 7, 8, 9, 11)
    )
    benign = base[2].model_copy(
        update={
            "identifier": "benign-only",
            "reference": 2,
            "harmful": False,
            "component_identifier": "benign-only",
        }
    )
    rows = (*rows, benign)
    row_lookup = {row.identifier: row for row in rows}
    outcomes = tuple(
        item.model_copy(
            update={
                "outcome": OrdinalJudgment(
                    ordinal=1
                    if row_lookup[item.response_identifier].component_identifier
                    == "component:0"
                    and create_same_family(
                        item.judge,
                        JudgeRole(
                            SOURCE_MODEL_ROLES[
                                row_lookup[item.response_identifier].source_model
                            ]
                        ),
                    )
                    else 5
                )
            }
        )
        for item in create_saved_outcomes(rows)
    )
    analysis = create_h1_analysis(rows, outcomes)
    target = create_bootstrap_target(analysis, analysis.targets[0])
    assert target.components == (
        "benign-only",
        "component:0",
        "component:1",
        "component:2",
    )
    copies = {"component:0": 2, "component:1": 1, "benign-only": 1}
    weights = create_row_weights(rows, copies)
    assert weights[base[0].identifier] == pytest.approx(2 / 3)
    assert weights[base[3].identifier] == 1
    assert weights[base[7].identifier] == 1
    assert weights[base[9].identifier] == 1
    assert "benign-only" not in weights
    replicate = create_component_replicate(target, copies)
    assert replicate.lower == pytest.approx(11 / 18)
    assert replicate.upper == pytest.approx(11 / 18)


def test_asymmetric_pilot_reuses_identical_copies_with_fixed_eight_denominators() -> (
    None
):
    rows = create_source_rows(copies=8, shared=False)
    row_lookup = {row.identifier: row for row in rows}
    saved = create_saved_outcomes(rows)
    original = tuple(
        item.model_copy(
            update={
                "outcome": OrdinalJudgment(
                    ordinal=1
                    if item.response_identifier.endswith(":0")
                    and create_same_family(
                        item.judge,
                        JudgeRole(
                            SOURCE_MODEL_ROLES[
                                row_lookup[item.response_identifier].source_model
                            ]
                        ),
                    )
                    else 5
                )
            }
        )
        for item in saved
    )
    rewrite = tuple(
        item.model_copy(
            update={
                "variable_identifier": f"rewrite:{item.variable_identifier}",
                "outcome": OrdinalJudgment(
                    ordinal=1
                    if item.response_identifier.endswith(":1")
                    and create_same_family(
                        item.judge,
                        JudgeRole(
                            SOURCE_MODEL_ROLES[
                                row_lookup[item.response_identifier].source_model
                            ]
                        ),
                    )
                    else 5
                ),
            }
        )
        for item in saved
    )
    pilot = create_paired_pilot(
        create_h1_analysis(rows, original), create_h1_analysis(rows, rewrite)
    )
    copies: dict[str, int] = {}
    for source_index, count in enumerate((3, 2, 1, 4)):
        copies[f"{source_index}:0"] = count
        copies[f"{source_index}:1"] = 8 - count
    first, second, reduction = create_pilot_replicates(pilot, copies)
    assert pilot.original.bounds.point == pytest.approx(1 / 8)
    assert pilot.rewrite.bounds.point == pytest.approx(1 / 8)
    assert first.lower == first.upper == pytest.approx(5 / 16)
    assert second.lower == second.upper == pytest.approx(11 / 16)
    assert reduction.lower == reduction.upper == pytest.approx(-3 / 8)
