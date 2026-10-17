"""Unsupported evidence keeps every exploratory table without invented decisions."""

from safety_judge.judging import JudgeRole, create_normalized_terminal_outcomes
from safety_judge.reporting import (
    ReportProvenance,
    create_normalization_coverage,
    create_report_markdown,
    select_study_report,
)


def test_unsupported_source_keeps_twelve_effect_rows_without_decisions() -> None:
    report = select_study_report(
        (),
        (),
        provenance=ReportProvenance(
            evidence_kind="synthetic",
            execution_mode="simulated",
            configuration_sha256=None,
        ),
        replicates=9,
    )
    assert report.primary is None
    assert report.decisions is None
    assert report.analysis.undefined_reason is not None
    assert [(row.judge, row.benchmark) for row in report.effects] == [
        (role, boundary) for role in JudgeRole for boundary in (0.03, 0.05, 0.10)
    ]
    assert {row.relation for row in report.effects} == {"undefined"}
    assert len(report.reference_error) == 3
    text = create_report_markdown(report)
    assert "synthetic" in text
    assert "Unavailable" in text
    assert "Reference-error sensitivity (heuristic)" in text


def test_normalization_coverage_reports_both_rates_on_one_fixed_denominator() -> None:
    outcomes = (
        create_normalized_terminal_outcomes(
            '{"ordinal":3}', finish="complete", judge_refused=False
        ),
        create_normalized_terminal_outcomes(
            '```json\n{"ordinal":3}\n```', finish="complete", judge_refused=False
        ),
        create_normalized_terminal_outcomes(
            "```json\ninvalid\n```", finish="complete", judge_refused=False
        ),
    )
    coverage = create_normalization_coverage(outcomes)
    assert coverage.assigned == 3
    assert coverage.raw_valid == 1
    assert coverage.normalized_valid == 2
    assert coverage.raw_rate == 1 / 3
    assert coverage.normalized_rate == 2 / 3
    assert create_normalization_coverage(()).normalized_rate is None
