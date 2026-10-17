"""Render saved evidence with primary, supporting and exploratory claims separated."""

from typing import Literal

from pydantic import BaseModel

from safety_judge.analysis import (
    AccuracySummary,
    ContrastSlice,
    EffectBenchmark,
    H1Analysis,
    ReferenceErrorScenario,
    SavedJudgment,
    SupportScreen,
    create_accuracy_summary,
    create_contrast_slices,
    create_effect_benchmarks,
    create_h1_analysis,
    create_reference_error_sensitivities,
    create_support_screen,
    create_supporting_slices,
)
from safety_judge.inference import (
    EndpointInference,
    EndpointReplicate,
    H1Decisions,
    create_bootstrap_target,
    create_component_replicate,
    create_endpoint_inference,
    create_h1_decisions,
    select_component_multiplicities,
)
from safety_judge.judging import JudgeRole, NormalizedTerminalOutcomes
from safety_judge.supporting import (
    WeightedAdditiveFit,
    WeightingSensitivity,
    create_weighted_additive_fit,
    create_weighting_sensitivities,
)
lazy from safety_judge.coin_flip import EligibleResponse


class NormalizationCoverage(BaseModel, frozen=True, extra="forbid"):
    """Separate format coverage on the identical assigned response denominator.

    Attributes:
        assigned: Total cells including unresolved or absent responses.
        raw_valid: Cells accepted by the unchanged raw strict parser.
        normalized_valid: Cells accepted after the frozen outer-fence rule.
        raw_rate: Raw validity fraction, absent when no cells were assigned.
        normalized_rate: Normalized validity fraction with the same denominator.
    """

    assigned: int
    raw_valid: int
    normalized_valid: int
    raw_rate: float | None
    normalized_rate: float | None


def create_normalization_coverage(
    outcomes: tuple[NormalizedTerminalOutcomes, ...],
) -> NormalizationCoverage:
    """Report both parser coverages without selecting responses by validity.

    Args:
        outcomes: One predetermined response per cell, including unresolved ones.

    Returns:
        Raw and normalized counts/rates with the same complete denominator.
    """
    raw = sum(item.raw.kind == "judgment" for item in outcomes)
    normalized = sum(item.normalized.kind == "judgment" for item in outcomes)
    assigned = len(outcomes)
    return NormalizationCoverage(
        assigned=assigned,
        raw_valid=raw,
        normalized_valid=normalized,
        raw_rate=raw / assigned if assigned else None,
        normalized_rate=normalized / assigned if assigned else None,
    )


class ReportProvenance(BaseModel, frozen=True, extra="forbid"):
    """Explicit evidence identity distinguishes simulations from saved live runs.

    Attributes:
        evidence_kind: Synthetic fixture or study observations.
        execution_mode: Exact saved mode, without inferring it from output quality.
        configuration_sha256: Journal configuration hash, absent for pure analyses.
    """

    evidence_kind: Literal["synthetic", "study"]
    execution_mode: Literal["simulated", "live"]
    configuration_sha256: str | None


class StudyReport(BaseModel, frozen=True, extra="forbid"):
    """All fixed report families; synthetic results retain explicit provenance.

    Attributes:
        evidence_kind: Supplied synthetic/study provenance, never a result claim.
        execution_mode: Explicit saved simulated/live execution provenance.
        configuration_sha256: Journal identity, absent for pure analyses.
        weighting: Raw-row and equal-four supporting sensitivity contrasts.
        additive_fit: Supporting complete-case item-adjusted association.
        limitations: Scope and statistical-interpretation constraints.
        analysis: Sole pooled primary and fixed secondary finite-data contrasts.
        support: Component support/leverage heuristic, not a power guarantee.
        primary: Pooled approximate inference, absent for undefined support.
        secondary: All four secondary inferences using conservative tail bounds.
        decisions: Fixed primary-gated Holm decisions, absent without support.
        accuracy: Supporting valid-only accuracy and coverage, overall and slices.
        contrasts: Supporting attack/severity rebalanced contrasts.
        effects: All twelve exploratory judge-by-three/five/ten-point rows.
        reference_error: One/five/ten-percent boundary-adverse heuristics.
        bootstrap_replicates: Requested draw count; fixtures lack tail power.
    """

    evidence_kind: str
    execution_mode: Literal["simulated", "live"]
    configuration_sha256: str | None
    weighting: tuple[WeightingSensitivity, WeightingSensitivity]
    additive_fit: WeightedAdditiveFit
    limitations: tuple[str, ...]
    analysis: H1Analysis
    support: SupportScreen
    primary: EndpointInference | None
    secondary: dict[JudgeRole, EndpointInference]
    decisions: H1Decisions | None
    accuracy: tuple[AccuracySummary, ...]
    contrasts: tuple[ContrastSlice, ...]
    effects: tuple[EffectBenchmark, ...]
    reference_error: tuple[ReferenceErrorScenario, ...]
    bootstrap_replicates: int


def select_study_report(
    rows: tuple[EligibleResponse, ...],
    judgments: tuple[SavedJudgment, ...],
    *,
    provenance: ReportProvenance,
    replicates: int = 9999,
) -> StudyReport:
    """Analyze saved judgments using the fixed shared component draws and thresholds.

    Args:
        rows: Frozen accepted originals, including benign reference cases.
        judgments: Complete saved terminal matrix; unresolved cells stay assigned.
        provenance: Exact saved evidence kind, mode and configuration identity.
        replicates: Fixed production 9,999; smaller counts only for offline fixtures.

    Returns:
        Full machine-readable report with unavailable uncertainty kept explicit.
    """
    analysis = create_h1_analysis(rows, judgments)
    primary = None
    secondary: dict[JudgeRole, EndpointInference] = {}
    decisions = None
    if analysis.targets:
        draws = select_component_multiplicities(
            analysis.components, replicates=replicates
        )
        for target in analysis.targets:
            aggregated = create_bootstrap_target(analysis, target)
            result = create_endpoint_inference(
                EndpointReplicate(lower=target.bounds.lower, upper=target.bounds.upper),
                tuple(create_component_replicate(aggregated, draw) for draw in draws),
                alpha=0.025 if target.name == "Delta" else 0.00625,
            )
            if target.name == "Delta":
                primary = result
            else:
                secondary[JudgeRole(target.name)] = result
        if primary is not None:
            decisions = create_h1_decisions(primary, secondary)
    return StudyReport(
        evidence_kind=provenance.evidence_kind,
        execution_mode=provenance.execution_mode,
        configuration_sha256=provenance.configuration_sha256,
        weighting=create_weighting_sensitivities(rows, judgments),
        additive_fit=create_weighted_additive_fit(rows, judgments),
        limitations=(
            (
                "Finite selected release; nominal families do not establish "
                "historical checkpoint identity or causal bias."
            ),
            (
                "Released labels are fallible compliance references, "
                "not technical safety ground truth."
            ),
            (
                "H2 is exploratory and requires independent 40/40 fidelity "
                "plus main-H1 scheduling gates."
            ),
            (
                "Synthetic fixtures demonstrate mechanics only; "
                "no real experiment result is implied."
            ),
        ),
        analysis=analysis,
        support=create_support_screen(analysis),
        primary=primary,
        secondary=secondary,
        decisions=decisions,
        accuracy=tuple(
            create_accuracy_summary(rows, judgments, role) for role in JudgeRole
        )
        + create_supporting_slices(rows, judgments),
        contrasts=create_contrast_slices(rows, judgments),
        effects=create_effect_benchmarks(analysis),
        reference_error=create_reference_error_sensitivities(rows, judgments),
        bootstrap_replicates=replicates,
    )


def create_report_markdown(report: StudyReport) -> str:
    """Render fixed exploratory effect tables beside evidence and coverage caveats.

    Args:
        report: Saved-evidence analysis, never live provider observations.

    Returns:
        Portable Markdown with every judge at every effect threshold.
    """
    lines = [
        f"# Safety judge report ({report.evidence_kind})",
        "",
        *report.limitations,
        "",
        "## H1 pooled primary",
        "",
        report.primary.model_dump_json()
        if report.primary
        else "Unavailable: " + str(report.analysis.undefined_reason),
        "",
        "## Secondary decisions",
        "",
        report.decisions.model_dump_json() if report.decisions else "Unavailable",
        "",
        "## Exploratory effect thresholds",
        "",
        "| Judge | Percentage points | Relation | Harmful coverage |",
        "| --- | ---: | --- | ---: |",
    ]
    lines.extend(
        f"| {item.judge.value} | {item.benchmark * 100:g} | "
        f"{item.relation} | {item.coverage} |"
        for item in report.effects
    )
    lines.extend(
        (
            "",
            "## Support and leverage",
            "",
            report.support.model_dump_json(),
            "",
            "## Coverage and valid-only accuracy",
            "",
        )
    )
    lines.extend(item.model_dump_json() for item in report.accuracy)
    lines.extend(("", "## Supporting weighting sensitivities", ""))
    lines.extend(item.model_dump_json() for item in report.weighting)
    lines.extend(
        ("", "## Supporting additive fit", "", report.additive_fit.model_dump_json())
    )
    lines.extend(("", "## Reference-error sensitivity (heuristic)", ""))
    lines.extend(item.model_dump_json() for item in report.reference_error)
    return "\n".join(lines) + "\n"
